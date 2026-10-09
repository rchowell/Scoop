import uuid

import pytest
from fastapi.testclient import TestClient

from api.config import Settings, get_settings
from api.main import app


@pytest.fixture
def client(tmp_path):
    app.dependency_overrides[get_settings] = lambda: Settings(
        db_path=str(tmp_path / "app.sqlite3")
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_crud(client, tmp_path):
    body = {"name": "db", "kind": "sqlite", "options": {"path": str(tmp_path / "x.db")}}
    created = client.post("/v1/connectors", json=body).json()
    assert {k: created[k] for k in body} == body
    url = f"/v1/connectors/{created['id']}"

    assert client.get(url).json() == created

    listing = client.get("/v1/connectors").json()
    assert [c["id"] for c in listing["items"]] == [created["id"]]
    assert listing["pagination"]["next"] is None

    new_options = {"path": str(tmp_path / "y.db")}
    patched = client.patch(url, json={"name": "renamed", "options": new_options})
    assert patched.status_code == 200
    assert patched.json()["name"] == "renamed"
    assert client.get(url).json() == patched.json()
    assert patched.json()["options"] == new_options

    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    assert client.delete(url).status_code == 404


def test_list_pagination(client, tmp_path):
    for i in range(3):
        client.post(
            "/v1/connectors",
            json={
                "name": f"c{i}",
                "kind": "duckdb",
                "options": {"database": str(tmp_path / f"{i}.db")},
            },
        )
    first = client.get("/v1/connectors", params={"page_size": 2}).json()
    assert [c["name"] for c in first["items"]] == ["c0", "c1"]
    assert first["pagination"]["prev"] is None
    second = client.get(first["pagination"]["next"]).json()
    assert [c["name"] for c in second["items"]] == ["c2"]
    assert second["pagination"]["next"] is None


def test_invalid_kind(client):
    resp = client.post(
        "/v1/connectors", json={"name": "x", "kind": "oracle", "options": {}}
    )
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "options,problem",
    [
        ({"path": "x", "bogus": 1}, "unknown option: bogus"),
        ({}, "missing required option: path"),
        ({"path": 1}, "path: expected str"),
    ],
)
def test_invalid_options(client, options, problem):
    resp = client.post(
        "/v1/connectors", json={"name": "x", "kind": "sqlite", "options": options}
    )
    assert resp.status_code == 422
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json()["title"] == "Invalid Options"
    assert resp.json()["detail"] == problem
    assert client.get("/v1/connectors").json()["items"] == []


def test_update_invalid_options(client, tmp_path):
    body = {"name": "db", "kind": "sqlite", "options": {"path": str(tmp_path / "x")}}
    url = f"/v1/connectors/{client.post('/v1/connectors', json=body).json()['id']}"
    resp = client.patch(url, json={"name": "db", "options": {"database": "x"}})
    assert resp.status_code == 422
    assert client.get(url).json()["options"] == body["options"]


def test_options_stored_raw(client):
    options = {"host": "localhost", "port": "6543", "user": "u", "dbname": "d"}
    created = client.post(
        "/v1/connectors", json={"name": "pg", "kind": "postgres", "options": options}
    ).json()
    assert created["options"] == options
    assert client.get(f"/v1/connectors/{created['id']}").json()["options"] == options


def test_unreachable_connector(client):
    options = {"host": "127.0.0.1", "port": 1, "user": "u", "dbname": "d"}
    id = client.post(
        "/v1/connectors", json={"name": "pg", "kind": "postgres", "options": options}
    ).json()["id"]
    resp = client.get(f"/v1/connectors/{id}/tables")
    assert resp.status_code == 400
    assert resp.json()["title"] == "Connector Unavailable"


def test_list_connector_kinds(client):
    kinds = {k["kind"]: k for k in client.get("/v1/connections").json()["kinds"]}
    assert set(kinds) == {"sqlite", "duckdb", "postgres", "mysql"}
    pg = kinds["postgres"]
    assert pg["name"] == "PostgreSQL"
    assert [o["name"] for o in pg["options"]] == [
        "host",
        "port",
        "user",
        "password",
        "dbname",
    ]
    opts = {o["name"]: o for o in pg["options"]}
    assert opts["port"] == {
        "name": "port",
        "type": "integer",
        "description": "Server port",
        "required": False,
        "default": 5432,
        "secret": False,
    }
    assert opts["password"]["secret"] is True
    assert opts["host"]["type"] == "string" and opts["host"]["required"] is True


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("get", ""),
        ("get", "/tables"),
        ("get", "/table?path=users"),
        ("post", "/execute"),
    ],
)
def test_unknown_connector(client, method, suffix):
    kwargs = {"json": {"query": "SELECT 1"}} if method == "post" else {}
    resp = getattr(client, method)(f"/v1/connectors/{uuid.uuid4()}{suffix}", **kwargs)
    assert resp.status_code == 404
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json()["status"] == 404


def _cached(client, id):
    return client.app.state.connector_cache._connectors.get(uuid.UUID(id))


def test_connector_is_cached(client, tmp_path):
    body = {"name": "db", "kind": "sqlite", "options": {"path": str(tmp_path / "x.db")}}
    id = client.post("/v1/connectors", json=body).json()["id"]
    assert _cached(client, id) is None
    assert client.get(f"/v1/connectors/{id}/tables").status_code == 200
    first = _cached(client, id)
    assert first is not None
    client.get(f"/v1/connectors/{id}/tables")
    assert _cached(client, id) is first


def test_update_evicts_cached_connector(client, tmp_path):
    body = {"name": "db", "kind": "sqlite", "options": {"path": str(tmp_path / "x.db")}}
    url = f"/v1/connectors/{client.post('/v1/connectors', json=body).json()['id']}"
    client.post(f"{url}/execute", json={"query": "CREATE TABLE a (v INTEGER)"})
    assert client.get(f"{url}/tables").json()["tables"] == [["main", "a"]]

    new_options = {"path": str(tmp_path / "y.db")}
    client.patch(url, json={"name": "db", "options": new_options})
    assert client.get(f"{url}/tables").json()["tables"] == []


def test_delete_evicts_cached_connector(client, tmp_path):
    body = {"name": "db", "kind": "sqlite", "options": {"path": str(tmp_path / "x.db")}}
    id = client.post("/v1/connectors", json=body).json()["id"]
    client.get(f"/v1/connectors/{id}/tables")
    assert _cached(client, id) is not None
    assert client.delete(f"/v1/connectors/{id}").status_code == 204
    assert _cached(client, id) is None
    assert client.get(f"/v1/connectors/{id}/tables").status_code == 404
