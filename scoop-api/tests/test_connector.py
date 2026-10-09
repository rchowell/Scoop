import json
from dataclasses import dataclass, field

import pytest

from api.connector import TableNotFoundError, create_connector

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
    placeholder: str = "?"


BACKENDS = {
    "sqlite": Backend(("main",), ("INTEGER", "VARCHAR")),
    "duckdb": Backend(("memory", "main"), ("INTEGER", "VARCHAR")),
    "postgres": Backend(
        ("public",), ("integer", "character varying"), placeholder="%s"
    ),
    "mysql": Backend(
        ("test",),
        ("int", "varchar"),
        seed=[SEED[0].replace("VARCHAR", "VARCHAR(255)"), *SEED[1:]],
        placeholder="%s",
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
    for stmt in [*RESET, *BACKENDS[backend].seed]:
        c.execute(stmt).close()
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


def test_execute_pages(conn):
    with conn.execute("SELECT id, name FROM users ORDER BY id", page_size=2) as result:
        assert [c.name for c in result.columns] == ["id", "name"]
        pages = list(result)
    assert [len(p) for p in pages] == [2, 2, 1]
    assert pages[0].data == {"id": [1, 2], "name": ["a", "b"]}
    assert pages[2].data == {"id": [5], "name": [None]}
    assert json.loads(json.dumps(pages[1].data)) == {"id": [3, 4], "name": ["c", "d"]}
    assert list(result) == []


def test_execute_empty(conn):
    with conn.execute("SELECT id, name FROM users WHERE id < 0") as result:
        assert [c.name for c in result.columns] == ["id", "name"]
        assert list(result) == []


def test_execute_params(conn, spec):
    query = f"SELECT name FROM users WHERE id = {spec.placeholder}"
    with conn.execute(query, [3]) as result:
        assert [p.data for p in result] == [{"name": ["c"]}]


def test_execute_duplicate_columns(conn):
    with conn.execute("SELECT id, id, id FROM users WHERE id = 1") as result:
        assert [p.data for p in result] == [{"id": [1], "id_1": [1], "id_2": [1]}]


def test_concurrent_results(conn):
    with (
        conn.execute("SELECT id FROM users ORDER BY id", page_size=1) as a,
        conn.execute("SELECT name FROM users ORDER BY id", page_size=1) as b,
    ):
        assert next(a).data == {"id": [1]}
        assert next(b).data == {"name": ["a"]}
        assert next(a).data == {"id": [2]}


def test_close_stops_iteration(conn):
    result = conn.execute("SELECT id FROM users", page_size=1)
    next(result)
    result.close()
    assert list(result) == []


def test_invalid_page_size(conn):
    with pytest.raises(ValueError):
        conn.execute("SELECT 1", page_size=0)
