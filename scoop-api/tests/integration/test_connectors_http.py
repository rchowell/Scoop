"""End-to-end tests of /v1/connectors against every registered connector backend."""

import pytest

from api.connector import FACTORIES
from tests.integration.conftest import BACKENDS

pytestmark = pytest.mark.integration

PROBLEM_JSON = "application/problem+json"

# One SELECT per backend covering common scalar types, and the JSON it should produce.
TYPE_PROBES = {
    "sqlite": (
        "SELECT 1 AS i, 1.5 AS f, 'x' AS t, NULL AS n, TRUE AS bo, X'FF00' AS b",
        {"i": 1, "f": 1.5, "t": "x", "n": None, "bo": 1, "b": "/wA="},
    ),
    "duckdb": (
        (
            "SELECT 1 AS i, 1.5::DOUBLE AS f, 'x' AS t, NULL AS n, TRUE AS bo, "
            "DATE '2024-01-02' AS d, TIMESTAMP '2024-01-02 03:04:05' AS ts, "
            r"1.25::DECIMAL(5, 2) AS dec, '\xFF\x00'::BLOB AS b, [1, 2] AS l"
        ),
        {
            "i": 1,
            "f": 1.5,
            "t": "x",
            "n": None,
            "bo": True,
            "d": "2024-01-02",
            "ts": "2024-01-02T03:04:05",
            "dec": "1.25",
            "b": "/wA=",
            "l": [1, 2],
        },
    ),
    "postgres": (
        (
            "SELECT 1 AS i, 1.5::float8 AS f, 'x'::text AS t, NULL AS n, TRUE AS bo, "
            "DATE '2024-01-02' AS d, TIMESTAMP '2024-01-02 03:04:05' AS ts, "
            r"1.25::numeric(5, 2) AS dec, '\xff00'::bytea AS b, "
            """'{"k": [1]}'::jsonb AS j"""
        ),
        {
            "i": 1,
            "f": 1.5,
            "t": "x",
            "n": None,
            "bo": True,
            "d": "2024-01-02",
            "ts": "2024-01-02T03:04:05",
            "dec": "1.25",
            "b": "/wA=",
            "j": {"k": [1]},
        },
    ),
    "mysql": (
        (
            "SELECT 1 AS i, 1.5e0 AS f, 'x' AS t, NULL AS n, TRUE AS bo, "
            "DATE '2024-01-02' AS d, TIMESTAMP '2024-01-02 03:04:05' AS ts, "
            "CAST(1.25 AS DECIMAL(5, 2)) AS `dec`, X'FF00' AS b"
        ),
        {
            "i": 1,
            "f": 1.5,
            "t": "x",
            "n": None,
            "bo": 1,
            "d": "2024-01-02",
            "ts": "2024-01-02T03:04:05",
            "dec": "1.25",
            "b": "/wA=",
        },
    ),
}


def _url(id: str, suffix: str = "") -> str:
    return f"/v1/connectors/{id}{suffix}"


def _execute(client, id, query, **body):
    return client.post(_url(id, "/execute"), json={"query": query, **body})


def _assert_problem(resp, status: int, title: str) -> None:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"] == PROBLEM_JSON
    assert resp.json()["title"] == title
    assert resp.json()["detail"]


def test_every_kind_has_a_spec():
    assert set(BACKENDS) == set(FACTORIES)
    assert set(TYPE_PROBES) == set(FACTORIES)


# -- connector resource ------------------------------------------------------


def test_kind_is_advertised(client, spec):
    kinds = {k["kind"]: k for k in client.get("/v1/connections").json()["kinds"]}
    assert [o["name"] for o in kinds[spec.kind]["options"]] == list(
        FACTORIES[spec.kind].options()
    )


def test_crud(client, spec, options):
    body = {"name": "db", "kind": spec.kind, "options": options}
    resp = client.post("/v1/connectors", json=body)
    assert resp.status_code == 201
    created = resp.json()
    assert {k: created[k] for k in body} == body
    url = _url(created["id"])

    assert client.get(url).json() == created
    assert [c["id"] for c in client.get("/v1/connectors").json()["items"]] == [
        created["id"]
    ]

    patched = client.patch(url, json={"name": "renamed", "options": options})
    assert patched.status_code == 200
    assert patched.json() == {**created, "name": "renamed"}
    assert client.get(url).json() == patched.json()

    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    assert client.get(_url(created["id"], "/tables")).status_code == 404


# -- metadata ----------------------------------------------------------------


def test_list_tables(client, spec, target):
    prefix = spec.prefix
    expected = [[*prefix, "named_users"], [*prefix, "users"]]
    tables = client.get(_url(target, "/tables")).json()["tables"]
    assert tables == expected

    scoped = client.get(_url(target, "/tables"), params={"namespace": prefix})
    assert scoped.json()["tables"] == expected

    none = client.get(_url(target, "/tables"), params={"namespace": "nope"})
    assert none.json()["tables"] == []


def test_get_table(client, spec, target):
    full = [*spec.prefix, "users"]
    resp = client.get(_url(target, "/table"), params={"path": full})
    assert resp.status_code == 200
    table = resp.json()
    assert table["path"] == full
    assert table["kind"] == "table"
    assert [(c["name"], c["type"], c["nullable"]) for c in table["columns"][:2]] == [
        ("id", spec.types[0], False),
        ("name", spec.types[1], True),
    ]
    assert [c["name"] for c in table["columns"]] == ["id", "name", "avatar"]

    bare = client.get(_url(target, "/table"), params={"path": "users"})
    assert bare.json() == table

    view = client.get(_url(target, "/table"), params={"path": "named_users"})
    assert view.json()["kind"] == "view"
    assert view.json()["path"] == [*spec.prefix, "named_users"]


@pytest.mark.parametrize("path", [["missing"], ["a", "b", "c", "d"]])
def test_get_table_missing(client, target, path):
    resp = client.get(_url(target, "/table"), params={"path": path})
    _assert_problem(resp, 404, "Not Found")


# -- execute -----------------------------------------------------------------


def test_execute_positional_params(client, spec, target):
    resp = _execute(
        client,
        target,
        f"SELECT id, name FROM users WHERE id > {spec.positional} ORDER BY id",
        params=[1],
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert [c["name"] for c in result["columns"]] == ["id", "name"]
    assert result["data"] == {"id": [2, 3, 4], "name": ["b", "c", None]}
    assert result["truncated"] is False


def test_execute_named_params(client, spec, target):
    resp = _execute(
        client,
        target,
        f"SELECT name FROM users WHERE id = {spec.named('id')}",
        params={"id": 3},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"name": ["c"]}


@pytest.mark.parametrize(
    ("max_rows", "expected", "truncated"),
    [(2, [1, 2], True), (3, [1, 2, 3], True), (4, [1, 2, 3, 4], False)],
)
def test_execute_max_rows(client, target, max_rows, expected, truncated):
    result = _execute(
        client, target, "SELECT id FROM users ORDER BY id", max_rows=max_rows
    ).json()
    assert result["data"] == {"id": expected}
    assert result["truncated"] is truncated


def test_execute_empty_keeps_columns(client, target):
    result = _execute(client, target, "SELECT id, name FROM users WHERE id < 0").json()
    assert [c["name"] for c in result["columns"]] == ["id", "name"]
    assert result["data"] == {"id": [], "name": []}
    assert result["truncated"] is False


def test_execute_duplicate_columns(client, target):
    result = _execute(client, target, "SELECT id, id FROM users WHERE id = 1").json()
    assert result["data"] == {"id": [1], "id_1": [1]}


def test_execute_types(client, spec, target):
    query, expected = TYPE_PROBES[spec.kind]
    resp = _execute(client, target, query)
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert [c["name"] for c in result["columns"]] == list(expected)
    assert result["data"] == {k: [v] for k, v in expected.items()}


def test_execute_blob_column(client, spec, target):
    _execute(
        client, target, f"UPDATE users SET avatar = {spec.blob_literal} WHERE id = 1"
    )
    result = _execute(client, target, "SELECT avatar FROM users ORDER BY id").json()
    assert result["data"] == {"avatar": ["/wA=", None, None, None]}


def test_writes_persist_across_requests(client, spec, target):
    """Writes must be committed, not left pending on the cached connection."""
    for stmt in [
        "DROP TABLE IF EXISTS scratch",
        "CREATE TABLE scratch (v INTEGER)",
        "INSERT INTO scratch VALUES (7)",
    ]:
        resp = _execute(client, target, stmt)
        assert resp.status_code == 200, resp.text

    tables = client.get(_url(target, "/tables")).json()["tables"]
    assert [*spec.prefix, "scratch"] in tables
    assert _execute(client, target, "SELECT v FROM scratch").json()["data"] == {
        "v": [7]
    }
    _execute(client, target, "DROP TABLE scratch")


# -- errors ------------------------------------------------------------------


@pytest.mark.parametrize(
    "query", ["SELEC nope", "SELECT * FROM missing_table", "SELECT 1/"]
)
def test_execute_bad_sql(client, target, query):
    _assert_problem(_execute(client, target, query), 400, "Query Failed")


def test_execute_wrong_param_count(client, spec, target):
    query = f"SELECT {spec.positional} AS a, {spec.positional} AS b"
    _assert_problem(_execute(client, target, query, params=[1]), 400, "Query Failed")


def test_connection_survives_failed_query(client, target):
    _execute(client, target, "SELEC nope")
    assert _execute(client, target, "SELECT 1 AS x").json()["data"] == {"x": [1]}


@pytest.mark.parametrize(
    ("method", "suffix", "kwargs"),
    [
        ("get", "/tables", {}),
        ("get", "/table", {"params": {"path": "users"}}),
        ("post", "/execute", {"json": {"query": "SELECT 1"}}),
    ],
)
def test_unavailable_connector(client, spec, bad_options, method, suffix, kwargs):
    resp = client.post(
        "/v1/connectors",
        json={"name": "bad", "kind": spec.kind, "options": bad_options},
    )
    assert resp.status_code == 201, "options are valid; connecting is what fails"
    resp = getattr(client, method)(_url(resp.json()["id"], suffix), **kwargs)
    _assert_problem(resp, 400, "Connector Unavailable")
