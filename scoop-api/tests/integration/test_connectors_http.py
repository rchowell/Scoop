"""End-to-end tests of /v1/connectors against every registered connector backend."""

import pytest

from api.connector import CONNECTORS
from api.models import Query
from tests.backends import BACKENDS
from tests.helpers import alias, binary, call, cast, col, lit, select, table

pytestmark = pytest.mark.integration

PROBLEM_JSON = "application/problem+json"

STAR = {"kind": "star"}
USERS = table("users")
BY_ID = [{"expr": col("id")}]

# Per backend, (alias, expression, JSON value) covering common scalar types.
_SCALARS = [
    ("i", lit(1), 1),
    ("f", lit(1.5), 1.5),
    ("t", lit("x"), "x"),
    ("n", lit(None), None),
]
_TEMPORAL = [
    ("d", cast(lit("2024-01-02"), "DATE"), "2024-01-02"),
    ("ts", cast(lit("2024-01-02 03:04:05"), "TIMESTAMP"), "2024-01-02T03:04:05"),
    ("dec", cast(lit(1.25), "DECIMAL(5, 2)"), "1.25"),
]
TYPE_PROBES = {
    "sqlite": [*_SCALARS, ("bo", lit(True), 1)],
    "duckdb": [
        *_SCALARS,
        ("bo", lit(True), True),
        *_TEMPORAL,
        ("l", call("list_value", lit(1), lit(2)), [1, 2]),
    ],
    "postgres": [
        *_SCALARS,
        ("bo", lit(True), True),
        *_TEMPORAL,
        ("j", cast(lit('{"k": [1]}'), "jsonb"), {"k": [1]}),
    ],
    "mysql": [
        *_SCALARS,
        ("bo", lit(True), 1),
        ("d", cast(lit("2024-01-02"), "DATE"), "2024-01-02"),
        ("ts", cast(lit("2024-01-02 03:04:05"), "DATETIME"), "2024-01-02T03:04:05"),
        ("dec", cast(lit(1.25), "DECIMAL(5, 2)"), "1.25"),
    ],
}


def _url(id: str, suffix: str = "") -> str:
    return f"/v1/connectors/{id}{suffix}"


def _execute(client, id, query: Query, **body):
    json = query.model_dump(mode="json", by_alias=True, exclude_unset=True)
    return client.post(_url(id, "/execute"), json={"query": json, **body})


def _assert_problem(resp, status: int, title: str) -> None:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"] == PROBLEM_JSON
    assert resp.json()["title"] == title
    assert resp.json()["detail"]


def test_every_kind_has_a_spec():
    assert set(BACKENDS) == set(CONNECTORS)
    assert set(TYPE_PROBES) == set(CONNECTORS)


# -- connector resource ------------------------------------------------------


def test_kind_is_advertised(client, spec):
    kinds = {k["kind"]: k for k in client.get("/v1/connector-kinds").json()["kinds"]}
    assert [o["name"] for o in kinds[spec.kind]["options"]] == list(
        CONNECTORS[spec.kind].options()
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


def test_execute_literals_are_bound(client, spec, target):
    query = select(
        col("id"),
        col("name"),
        from_=USERS,
        where=binary("gt", col("id"), lit(1)),
        order_by=BY_ID,
    )
    resp = _execute(client, target, query)
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert [c["name"] for c in result["columns"]] == ["id", "name"]
    assert result["data"] == {"id": [2, 3, 4], "name": ["b", "c", None]}
    assert result["truncated"] is False


@pytest.mark.parametrize(
    ("max_rows", "expected", "truncated"),
    [(2, [1, 2], True), (3, [1, 2, 3], True), (4, [1, 2, 3, 4], False)],
)
def test_execute_max_rows(client, target, max_rows, expected, truncated):
    query = select(col("id"), from_=USERS, order_by=BY_ID)
    result = _execute(client, target, query, max_rows=max_rows).json()
    assert result["data"] == {"id": expected}
    assert result["truncated"] is truncated


def test_execute_empty_keeps_columns(client, target):
    query = select(
        col("id"), col("name"), from_=USERS, where=binary("lt", col("id"), lit(0))
    )
    result = _execute(client, target, query).json()
    assert [c["name"] for c in result["columns"]] == ["id", "name"]
    assert result["data"] == {"id": [], "name": []}
    assert result["truncated"] is False


def test_execute_duplicate_columns(client, target):
    query = select(
        col("id"), col("id"), from_=USERS, where=binary("eq", col("id"), lit(1))
    )
    result = _execute(client, target, query).json()
    assert result["data"] == {"id": [1], "id_1": [1]}


def test_execute_types(client, spec, target):
    probes = TYPE_PROBES[spec.kind]
    query = select(*(alias(expr, name) for name, expr, _ in probes))
    resp = _execute(client, target, query)
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert [c["name"] for c in result["columns"]] == [name for name, _, _ in probes]
    assert result["data"] == {name: [value] for name, _, value in probes}


def test_execute_blob_column(client, target):
    query = select(col("avatar"), from_=USERS, order_by=BY_ID)
    result = _execute(client, target, query).json()
    assert result["data"] == {"avatar": ["/wA=", None, None, None]}


# -- errors ------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        select(STAR, from_=table("missing_table")),
        select(col("missing_column"), from_=USERS),
        select(call("no_such_function", lit(1))),
    ],
    ids=["table", "column", "function"],
)
def test_execute_unknown_name(request, client, spec, target, query):
    if spec.kind == "sqlite" and "column" in request.node.callspec.id:
        # SQLite reads a double-quoted unknown identifier as a string literal.
        pytest.xfail("SQLite DQS quirk: unknown quoted column becomes a string")
    _assert_problem(_execute(client, target, query), 400, "Query Failed")


def test_execute_unsupported_syntax(client, target):
    query = select(cast(lit(1), "INT; DROP TABLE users"))
    _assert_problem(_execute(client, target, query), 400, "Query Failed")


def test_connection_survives_failed_query(client, target):
    _execute(client, target, select(STAR, from_=table("missing_table")))
    result = _execute(client, target, select(alias(lit(1), "x"))).json()
    assert result["data"] == {"x": [1]}


@pytest.mark.parametrize(
    ("method", "suffix", "kwargs"),
    [
        ("get", "/tables", {}),
        ("get", "/table", {"params": {"path": "users"}}),
        ("post", "/execute", {"json": {"query": {"select": [{"expr": lit(1)}]}}}),
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
