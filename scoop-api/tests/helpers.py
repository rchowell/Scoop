"""Query AST builders and seeding helpers shared by the tests."""

from typing import Any

from api.connector import Connector
from api.models import Query


def col(*path):
    return {"kind": "column", "path": list(path)}


def lit(value):
    return {"kind": "literal", "value": value}


def call(name, *args, **kw):
    return {"kind": "call", "name": name, "args": list(args), **kw}


def cast(expr, type):
    return {"kind": "cast", "expr": expr, "type": type}


def unary(op, operand):
    return {"kind": "unary", "op": op, "operand": operand}


def binary(op, left, right):
    return {"kind": "binary", "op": op, "left": left, "right": right}


def table(*path):
    return {"kind": "table", "path": list(path)}


def joined(join_type, left, right, on=None):
    data = {"kind": "join", "join_type": join_type, "left": left, "right": right}
    return data if on is None else {**data, "on": on}


def alias(expr, name):
    """A select item: `expr AS name`."""
    return {"expr": expr, "alias": name}


def select(*items, **clauses: Any) -> Query:
    """SELECT `items` (expressions, or alias(...) items); pass from_=... for FROM."""
    if "from_" in clauses:
        clauses["from"] = clauses.pop("from_")
    # Expressions have a `kind`; select items don't.
    select = [{"expr": i} if "kind" in i else i for i in items]
    return Query.model_validate({"select": select, **clauses})


# SELECT c.region, count(*) AS n, sum(o.total) AS revenue
# FROM orders o LEFT JOIN customers c ON o.customer_id = c.id
# WHERE o.status IN ('paid', 'shipped')
#   AND o.created_at BETWEEN CAST('2026-01-01' AS date) AND CAST('2026-12-31' AS date)
#   AND c.deleted_at IS NULL
# GROUP BY c.region
# HAVING count(*) > 1
# ORDER BY revenue DESC NULLS LAST
# LIMIT 10 OFFSET 20
AGGREGATE = {
    "select": [
        {"expr": col("c", "region")},
        {"expr": call("count", {"kind": "star"}), "alias": "n"},
        {"expr": call("sum", col("o", "total")), "alias": "revenue"},
    ],
    "from": {
        "kind": "join",
        "join_type": "left",
        "left": {"kind": "table", "path": ["orders"], "alias": "o"},
        "right": {"kind": "table", "path": ["customers"], "alias": "c"},
        "on": binary("eq", col("o", "customer_id"), col("c", "id")),
    },
    "where": binary(
        "and",
        binary(
            "and",
            {
                "kind": "in_list",
                "expr": col("o", "status"),
                "list": [lit("paid"), lit("shipped")],
            },
            {
                "kind": "between",
                "expr": col("o", "created_at"),
                "low": {"kind": "cast", "expr": lit("2026-01-01"), "type": "date"},
                "high": {"kind": "cast", "expr": lit("2026-12-31"), "type": "date"},
            },
        ),
        {"kind": "is_null", "expr": col("c", "deleted_at")},
    ),
    "group_by": [col("c", "region")],
    "having": binary("gt", call("count", {"kind": "star"}), lit(1)),
    "order_by": [{"expr": col("revenue"), "direction": "desc", "nulls": "last"}],
    "limit": 10,
    "offset": 20,
}

# SELECT DISTINCT
#   CASE WHEN amount < 0 THEN 'refund' ELSE 'sale' END AS kind,
#   coalesce(nickname, name) AS label,
#   nullif(discount, 0) AS discount,
#   count(DISTINCT user_id) AS users
# FROM (SELECT * FROM events WHERE name NOT LIKE 'test%') AS e
SCALARS = {
    "distinct": True,
    "select": [
        {
            "expr": {
                "kind": "case",
                "whens": [
                    {"when": binary("lt", col("amount"), lit(0)), "then": lit("refund")}
                ],
                "else": lit("sale"),
            },
            "alias": "kind",
        },
        {"expr": call("coalesce", col("nickname"), col("name")), "alias": "label"},
        {"expr": call("nullif", col("discount"), lit(0)), "alias": "discount"},
        {"expr": call("count", col("user_id"), distinct=True), "alias": "users"},
    ],
    "from": {
        "kind": "subquery",
        "alias": "e",
        "query": {
            "select": [{"expr": {"kind": "star"}}],
            "from": {"kind": "table", "path": ["events"]},
            "where": {
                "kind": "like",
                "expr": col("name"),
                "pattern": lit("test%"),
                "negated": True,
            },
        },
    },
}


def run_sql(connector: Connector, statements: list[str]) -> None:
    """Run raw SQL through the driver; Connector.execute only takes queries."""
    cursor = connector._cursor()
    try:
        for stmt in statements:
            cursor.execute(stmt)
    finally:
        cursor.close()
