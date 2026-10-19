import sqlite3

import duckdb
import pytest

from api.sql import (
    Dialect,
    DuckDBDialect,
    MySQLDialect,
    PostgresDialect,
    SqliteDialect,
    UnsupportedSyntax,
)
from models import Query
from tests.test_ast import AGGREGATE, SCALARS, binary, call, col, lit

DIALECTS = [Dialect, SqliteDialect, DuckDBDialect, PostgresDialect, MySQLDialect]
STAR = {"kind": "star"}


def select(expr, **clauses):
    return Query.model_validate({"select": [{"expr": expr}], **clauses})


def compile_expr(dialect, expr):
    sql, params = dialect.compile(select(expr))
    assert sql.startswith("SELECT ")
    return sql.removeprefix("SELECT "), params


def unary(op, operand):
    return {"kind": "unary", "op": op, "operand": operand}


def table(*path):
    return {"kind": "table", "path": list(path)}


def joined(join_type, left, right, on=None):
    data = {"kind": "join", "join_type": join_type, "left": left, "right": right}
    return data if on is None else {**data, "on": on}


AGGREGATE_WIDE = """\
SELECT "c"."region", count(*) AS "n", sum("o"."total") AS "revenue"
FROM "orders" AS "o" LEFT JOIN "customers" AS "c" ON "o"."customer_id" = "c"."id"
WHERE "o"."status" IN (?, ?)
  AND "o"."created_at" BETWEEN CAST(? AS date) AND CAST(? AS date)
  AND "c"."deleted_at" IS NULL
GROUP BY "c"."region"
HAVING count(*) > ?
ORDER BY "revenue" DESC NULLS LAST
LIMIT 10
OFFSET 20"""

AGGREGATE_NARROW = """\
SELECT
  "c"."region",
  count(*) AS "n",
  sum("o"."total") AS "revenue"
FROM "orders" AS "o"
LEFT JOIN "customers" AS "c"
  ON "o"."customer_id" = "c"."id"
WHERE "o"."status" IN (?, ?)
  AND "o"."created_at" BETWEEN CAST(? AS date) AND CAST(? AS date)
  AND "c"."deleted_at" IS NULL
GROUP BY "c"."region"
HAVING count(*) > ?
ORDER BY "revenue" DESC NULLS LAST
LIMIT 10
OFFSET 20"""

AGGREGATE_PARAMS = ["paid", "shipped", "2026-01-01", "2026-12-31", 1]

SCALARS_WIDE = """\
SELECT DISTINCT
  CASE WHEN "amount" < ? THEN ? ELSE ? END AS "kind",
  coalesce("nickname", "name") AS "label",
  nullif("discount", ?) AS "discount",
  count(DISTINCT "user_id") AS "users"
FROM (SELECT * FROM "events" WHERE "name" NOT LIKE ?) AS "e\""""

SCALARS_NARROW = """\
SELECT DISTINCT
  CASE
    WHEN "amount" < ? THEN ?
    ELSE ?
  END AS "kind",
  coalesce(
    "nickname",
    "name"
  ) AS "label",
  nullif("discount", ?) AS "discount",
  count(DISTINCT "user_id") AS "users"
FROM (
  SELECT *
  FROM "events"
  WHERE "name" NOT LIKE ?
) AS "e\""""

SCALARS_PARAMS = [0, "refund", "sale", 0, "test%"]


@pytest.mark.parametrize(
    ("data", "width", "expected", "params"),
    [
        (AGGREGATE, 100, AGGREGATE_WIDE, AGGREGATE_PARAMS),
        (AGGREGATE, 40, AGGREGATE_NARROW, AGGREGATE_PARAMS),
        (SCALARS, 100, SCALARS_WIDE, SCALARS_PARAMS),
        (SCALARS, 40, SCALARS_NARROW, SCALARS_PARAMS),
    ],
    ids=["aggregate-wide", "aggregate-narrow", "scalars-wide", "scalars-narrow"],
)
def test_golden(data, width, expected, params):
    assert SqliteDialect().compile(Query.model_validate(data), width) == (
        expected,
        params,
    )


def test_mysql_golden():
    sql, params = MySQLDialect().compile(Query.model_validate(AGGREGATE), 100)
    assert sql == (
        AGGREGATE_WIDE.replace('"', "`")
        .replace("?", "%s")
        .replace("`revenue` DESC NULLS LAST", "`revenue` IS NULL, `revenue` DESC")
    )
    assert params == AGGREGATE_PARAMS


def test_short_query_fits_on_one_line():
    query = select(lit(1), **{"from": table("t")})
    assert Dialect().compile(query) == ('SELECT ? FROM "t"', [1])


@pytest.mark.parametrize(
    ("expr", "sql", "value"),
    [
        (binary("add", lit(1), binary("mul", lit(2), lit(3))), "? + ? * ?", 7),
        (binary("mul", binary("add", lit(1), lit(2)), lit(3)), "(? + ?) * ?", 9),
        (binary("sub", binary("sub", lit(1), lit(2)), lit(3)), "? - ? - ?", -4),
        (binary("sub", lit(1), binary("sub", lit(2), lit(3))), "? - (? - ?)", 2),
        (unary("neg", unary("neg", lit(1))), "-(-?)", 1),
        (unary("neg", binary("add", lit(1), lit(2))), "-(? + ?)", -3),
        (
            binary("or", lit(True), binary("and", lit(False), lit(False))),
            "? OR ? AND ?",
            1,
        ),
        (
            binary("and", binary("or", lit(True), lit(False)), lit(False)),
            "(? OR ?) AND ?",
            0,
        ),
        (unary("not", binary("and", lit(True), lit(False))), "NOT (? AND ?)", 1),
        (binary("eq", binary("eq", lit(1), lit(1)), lit(1)), "(? = ?) = ?", 1),
        (
            binary("concat", binary("add", lit(1), lit(2)), lit("x")),
            "(? + ?) || ?",
            "3x",
        ),
        (
            binary("mul", binary("concat", lit("1"), lit("2")), lit(2)),
            "(? || ?) * ?",
            24,
        ),
        (
            {"kind": "is_null", "expr": binary("eq", lit(1), lit(None))},
            "(? = NULL) IS NULL",
            1,
        ),
    ],
)
def test_precedence(expr, sql, value):
    rendered, params = compile_expr(SqliteDialect(), expr)
    assert rendered == sql
    # The parenthesization means what the AST means
    assert sqlite3.connect(":memory:").execute(
        f"SELECT {rendered}", params
    ).fetchone() == (value,)


def test_params_follow_placeholder_order():
    case = {
        "kind": "case",
        "operand": lit("a"),
        "whens": [{"when": lit("b"), "then": lit("c")}],
        "else": lit("d"),
    }
    expr = call("coalesce", case, lit(None), lit("e"))
    assert compile_expr(PostgresDialect(), expr) == (
        "coalesce(CASE %s WHEN %s THEN %s ELSE %s END, NULL, %s)",
        ["a", "b", "c", "d", "e"],
    )


def test_identifiers_are_quoted_and_escaped():
    assert compile_expr(Dialect(), col("t", 'we"ird'))[0] == '"t"."we""ird"'
    assert compile_expr(MySQLDialect(), col("t", "we`ird"))[0] == "`t`.`we``ird`"
    assert compile_expr(Dialect(), {"kind": "star", "qualifier": ["t"]})[0] == '"t".*'


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        (SqliteDialect(), '? % ? AS "5%"'),
        (PostgresDialect(), '%s %% %s AS "5%%"'),
        (MySQLDialect(), "%s %% %s AS `5%%`"),
    ],
)
def test_percent_escaped_for_pyformat(dialect, sql):
    query = Query.model_validate(
        {"select": [{"expr": binary("mod", lit(5), lit(2)), "alias": "5%"}]}
    )
    assert dialect.compile(query) == (f"SELECT {sql}", [5, 2])


def test_mysql_concat():
    expr = binary("concat", col("a"), binary("concat", col("b"), col("c")))
    assert compile_expr(MySQLDialect(), expr)[0] == "CONCAT(`a`, CONCAT(`b`, `c`))"


@pytest.mark.parametrize(
    ("nulls", "sql"),
    [
        ("first", "`x` + %s IS NULL DESC, `x` + %s ASC"),
        ("last", "`x` + %s IS NULL, `x` + %s ASC"),
    ],
)
def test_mysql_nulls_order(nulls, sql):
    key = binary("add", col("x"), lit(1))
    query = select(
        col("x"), order_by=[{"expr": key, "direction": "asc", "nulls": nulls}]
    )
    assert MySQLDialect().compile(query) == (f"SELECT `x` ORDER BY {sql}", [1, 1])


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        (Dialect(), 'SELECT * FROM "t" OFFSET 5'),
        (SqliteDialect(), 'SELECT * FROM "t" LIMIT -1 OFFSET 5'),
        (MySQLDialect(), "SELECT * FROM `t` LIMIT 18446744073709551615 OFFSET 5"),
    ],
)
def test_offset_without_limit(dialect, sql):
    query = select(STAR, **{"from": table("t"), "offset": 5})
    assert dialect.compile(query) == (sql, [])


def test_nested_right_join_is_parenthesized():
    on = binary("eq", col("b", "id"), col("c", "id"))
    right = joined("inner", table("b"), table("c"), on)
    query = select(STAR, **{"from": joined("cross", table("a"), right)})
    assert Dialect().compile(query)[0] == (
        'SELECT * FROM "a" CROSS JOIN ("b" INNER JOIN "c" ON "b"."id" = "c"."id")'
    )


def _join(join_type, on=None):
    return select(STAR, **{"from": joined(join_type, table("a"), table("b"), on)})


@pytest.mark.parametrize(
    ("dialect", "query", "match"),
    [
        (MySQLDialect(), _join("full", lit(True)), "FULL JOIN"),
        (Dialect(), _join("inner"), "requires an ON"),
        (Dialect(), _join("cross", lit(True)), "takes no ON"),
        (Dialect(), select(call("drop table x;--")), "function name"),
        (
            Dialect(),
            select({"kind": "cast", "expr": lit(1), "type": "int); --"}),
            "type name",
        ),
        (Dialect(), select(col("a\0b")), "NUL"),
    ],
    ids=[
        "mysql-full-join",
        "missing-on",
        "cross-with-on",
        "function-name",
        "type-name",
        "nul-identifier",
    ],
)
def test_unsupported(dialect, query, match):
    with pytest.raises(UnsupportedSyntax, match=match):
        dialect.compile(query)


@pytest.mark.parametrize(
    "type_name", ["date", "varchar(10)", "decimal(10, 2)", "double precision"]
)
def test_cast_type_names(type_name):
    expr = {"kind": "cast", "expr": col("x"), "type": type_name}
    assert compile_expr(Dialect(), expr)[0] == f'CAST("x" AS {type_name})'


@pytest.mark.parametrize("dialect", DIALECTS, ids=lambda d: d.__name__)
def test_dialects_are_concrete(dialect):
    dialect()


SETUP = [
    "CREATE TABLE customers (id INTEGER, region TEXT, deleted_at TEXT)",
    "INSERT INTO customers VALUES (1, 'east', NULL), (2, 'west', NULL), (3, 'east', '2026-02-01')",
    "CREATE TABLE orders (customer_id INTEGER, total INTEGER, status TEXT, created_at DATE)",
    """INSERT INTO orders VALUES
        (1, 10, 'paid', '2026-03-01'), (1, 20, 'shipped', '2026-04-01'),
        (1, 99, 'cancelled', '2026-04-01'), (2, 5, 'paid', '2026-03-01'),
        (3, 7, 'paid', '2026-03-01'), (3, 8, 'paid', '2026-03-02')""",
    "CREATE TABLE events (amount INTEGER, nickname TEXT, name TEXT, discount INTEGER, user_id INTEGER)",
]

# AGGREGATE without its LIMIT/OFFSET, which skip every row of this tiny dataset
UNPAGED = Query.model_validate(
    {k: v for k, v in AGGREGATE.items() if k not in ("limit", "offset")}
)


def test_executes_on_duckdb():
    conn = duckdb.connect()
    for statement in SETUP:
        conn.execute(statement)
    sql, params = DuckDBDialect().compile(UNPAGED)
    assert conn.execute(sql, params).fetchall() == [("east", 2, 30)]


def test_executes_on_sqlite():
    conn = sqlite3.connect(":memory:")
    for statement in SETUP:
        conn.execute(statement)
    # SQLite has no date type: CAST(... AS date) yields a number, so just check it runs
    for query in (UNPAGED, Query.model_validate(SCALARS)):
        sql, params = SqliteDialect().compile(query)
        conn.execute(sql, params).fetchall()
