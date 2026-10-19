import json
from dataclasses import dataclass, field

import pytest

from api.connector import TableNotFoundError, create_connector
from models import Query
from tests.test_ast import binary, col, lit
from tests.test_sql import table

SEED = [
    "CREATE TABLE users (id INTEGER NOT NULL, name VARCHAR)",
    "INSERT INTO users VALUES (1, 'a'), (2, 'b'), (3, 'c'), (4, 'd'), (5, NULL)",
    "CREATE VIEW named_users AS SELECT * FROM users WHERE name IS NOT NULL",
]
RESET = ["DROP VIEW IF EXISTS named_users", "DROP TABLE IF EXISTS users"]


@dataclass(frozen=True)
class Backend:
    prefix: tuple[str, ...]
    types: tuple[str, str]  # expected native types of users.id, users.name
    seed: list[str] = field(default_factory=lambda: SEED)


BACKENDS = {
    "sqlite": Backend(("main",), ("INTEGER", "VARCHAR")),
    "duckdb": Backend(("memory", "main"), ("INTEGER", "VARCHAR")),
    "postgres": Backend(("public",), ("integer", "character varying")),
    "mysql": Backend(
        ("test",),
        ("int", "varchar"),
        seed=[SEED[0].replace("VARCHAR", "VARCHAR(255)"), *SEED[1:]],
    ),
}


@pytest.fixture(params=list(BACKENDS))
def backend(request):
    return request.param


@pytest.fixture
def conn(request, backend, tmp_path):
    match backend:
        case "sqlite":
            options = {"path": str(tmp_path / "t.sqlite3")}
        case "duckdb":
            options = {}
        case "postgres" | "mysql":
            options = request.getfixturevalue(f"{backend}_options")
    c = create_connector(backend, options)
    # execute() only takes queries, so seed through the driver
    cursor = c._cursor()
    for stmt in [*RESET, *BACKENDS[backend].seed]:
        cursor.execute(stmt)
    cursor.close()
    with c:
        yield c


@pytest.fixture
def spec(backend) -> Backend:
    return BACKENDS[backend]


def test_list_tables(conn, spec):
    prefix = spec.prefix
    assert conn.list_tables() == [(*prefix, "named_users"), (*prefix, "users")]
    assert conn.list_tables(prefix) == conn.list_tables()
    assert conn.list_tables(("nope",)) == []


def test_get_table(conn, spec):
    users = conn.get_table(("users",))
    assert users.path == (*spec.prefix, "users")
    assert users.kind == "table"
    assert [(c.name, c.type, c.nullable) for c in users.columns] == [
        ("id", spec.types[0], False),
        ("name", spec.types[1], True),
    ]
    assert conn.get_table(users.path) == users
    assert conn.get_table(("named_users",)).kind == "view"


def test_get_table_missing(conn):
    with pytest.raises(TableNotFoundError):
        conn.get_table(("missing",))
    with pytest.raises(TableNotFoundError):
        conn.get_table(("a", "b", "c", "d"))


def select(*columns, **clauses) -> Query:
    return Query.model_validate(
        {"select": [{"expr": c} for c in columns], "from": table("users"), **clauses}
    )


BY_ID = [{"expr": col("id")}]
ORDERED_IDS = select(col("id"), order_by=BY_ID)
ORDERED_NAMES = select(col("name"), order_by=BY_ID)


def test_execute_pages(conn):
    query = select(col("id"), col("name"), order_by=BY_ID)
    with conn.execute(query, page_size=2) as result:
        assert [c.name for c in result.columns] == ["id", "name"]
        pages = list(result)
    assert [len(p) for p in pages] == [2, 2, 1]
    assert pages[0].data == {"id": [1, 2], "name": ["a", "b"]}
    assert pages[2].data == {"id": [5], "name": [None]}
    assert json.loads(json.dumps(pages[1].data)) == {"id": [3, 4], "name": ["c", "d"]}
    assert list(result) == []


def test_execute_empty(conn):
    query = select(col("id"), col("name"), where=binary("lt", col("id"), lit(0)))
    with conn.execute(query) as result:
        assert [c.name for c in result.columns] == ["id", "name"]
        assert list(result) == []


def test_execute_literals_are_bound(conn):
    query = select(col("name"), where=binary("eq", col("id"), lit(3)))
    with conn.execute(query) as result:
        assert [p.data for p in result] == [{"name": ["c"]}]


def test_execute_dialect_syntax(conn):
    # MOD needs %% escaping on pyformat drivers; OFFSET without LIMIT and
    # NULLS FIRST need rewriting on SQLite and MySQL.
    query = select(
        binary("mod", col("id"), lit(2)),
        where=binary("gt", col("id"), lit(1)),
        order_by=BY_ID,
        offset=2,
    )
    with conn.execute(query) as result:
        assert [p.data[result.columns[0].name] for p in result] == [[0, 1]]
    query = select(
        col("name"), order_by=[{"expr": col("name"), "nulls": "first"}], limit=2
    )
    with conn.execute(query) as result:
        assert [p.data for p in result] == [{"name": [None, "a"]}]


def test_execute_duplicate_columns(conn):
    query = select(
        col("id"), col("id"), col("id"), where=binary("eq", col("id"), lit(1))
    )
    with conn.execute(query) as result:
        assert [p.data for p in result] == [{"id": [1], "id_1": [1], "id_2": [1]}]


def test_concurrent_results(conn):
    with (
        conn.execute(ORDERED_IDS, page_size=1) as a,
        conn.execute(ORDERED_NAMES, page_size=1) as b,
    ):
        assert next(a).data == {"id": [1]}
        assert next(b).data == {"name": ["a"]}
        assert next(a).data == {"id": [2]}


def test_close_stops_iteration(conn):
    result = conn.execute(ORDERED_IDS, page_size=1)
    next(result)
    result.close()
    assert list(result) == []


def test_invalid_page_size(conn):
    with pytest.raises(ValueError):
        conn.execute(ORDERED_IDS, page_size=0)
