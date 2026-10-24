import json

import pytest

from api.connector import TableNotFoundError, create_connector
from api.models import Query
from tests.backends import RESET
from tests.helpers import binary, col, lit, run_sql, select, table

USERS = table("users")


@pytest.fixture
def conn(spec, options):
    with create_connector(spec.kind, options) as c:
        run_sql(c, [*RESET, *spec.seed])
        yield c


def test_list_tables(conn, spec):
    prefix = spec.prefix  # a list: list_tables accepts any sequence
    assert conn.list_tables() == [(*prefix, "named_users"), (*prefix, "users")]
    assert conn.list_tables(prefix) == conn.list_tables()
    assert conn.list_tables(("nope",)) == []


def test_get_table(conn, spec):
    users = conn.get_table(("users",))
    assert users.path == (*spec.prefix, "users")
    assert users.kind == "table"
    assert [(c.name, c.type, c.nullable) for c in users.columns[:2]] == [
        ("id", spec.types[0], False),
        ("name", spec.types[1], True),
    ]
    assert [c.name for c in users.columns] == ["id", "name", "avatar"]
    assert conn.get_table(users.path) == users
    assert conn.get_table(("named_users",)).kind == "view"


def test_get_table_missing(conn):
    with pytest.raises(TableNotFoundError):
        conn.get_table(("missing",))
    with pytest.raises(TableNotFoundError):
        conn.get_table(("a", "b", "c", "d"))


def users(*columns, **clauses) -> Query:
    return select(*columns, from_=USERS, **clauses)


BY_ID = [{"expr": col("id")}]
ORDERED_IDS = users(col("id"), order_by=BY_ID)
ORDERED_NAMES = users(col("name"), order_by=BY_ID)


def test_execute_pages(conn):
    query = users(col("id"), col("name"), order_by=BY_ID)
    with conn.execute(query, page_size=2) as result:
        assert [c.name for c in result.columns] == ["id", "name"]
        pages = list(result)
    assert [len(p) for p in pages] == [2, 2]
    assert pages[0].data == {"id": [1, 2], "name": ["a", "b"]}
    assert json.loads(json.dumps(pages[1].data)) == {"id": [3, 4], "name": ["c", None]}
    assert list(result) == []


def test_execute_empty(conn):
    query = users(col("id"), col("name"), where=binary("lt", col("id"), lit(0)))
    with conn.execute(query) as result:
        assert [c.name for c in result.columns] == ["id", "name"]
        assert list(result) == []


def test_execute_literals_are_bound(conn):
    query = users(col("name"), where=binary("eq", col("id"), lit(3)))
    with conn.execute(query) as result:
        assert [p.data for p in result] == [{"name": ["c"]}]


def test_execute_dialect_syntax(conn):
    # MOD needs %% escaping on pyformat drivers; OFFSET without LIMIT and
    # NULLS FIRST need rewriting on SQLite and MySQL.
    query = users(
        binary("mod", col("id"), lit(2)),
        where=binary("gt", col("id"), lit(1)),
        order_by=BY_ID,
        offset=2,
    )
    with conn.execute(query) as result:
        assert [p.data[result.columns[0].name] for p in result] == [[0]]
    query = users(
        col("name"), order_by=[{"expr": col("name"), "nulls": "first"}], limit=2
    )
    with conn.execute(query) as result:
        assert [p.data for p in result] == [{"name": [None, "a"]}]


def test_execute_duplicate_columns(conn):
    query = users(
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
