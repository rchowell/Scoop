import pydantic
import pytest

from models import (
    BinaryExpr,
    BinaryOp,
    CaseExpr,
    ColumnExpr,
    Expr,
    Join,
    LiteralExpr,
    Query,
    SelectItem,
    WhenClause,
)

EXPR = pydantic.TypeAdapter(Expr)


def col(*path):
    return {"kind": "column", "path": list(path)}


def lit(value):
    return {"kind": "literal", "value": value}


def call(name, *args, **kw):
    return {"kind": "call", "name": name, "args": list(args), **kw}


def binary(op, left, right):
    return {"kind": "binary", "op": op, "left": left, "right": right}


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


@pytest.mark.parametrize("data", [AGGREGATE, SCALARS], ids=["aggregate", "scalars"])
def test_round_trip(data):
    query = Query.model_validate(data)
    assert query.model_dump(by_alias=True, exclude_unset=True) == data


def test_python_keyword_fields_are_aliased():
    query = Query.model_validate(AGGREGATE)
    assert isinstance(query.from_, Join)

    case = Query.model_validate(SCALARS).select[0].expr
    assert isinstance(case, CaseExpr)
    assert case.else_.value == "sale"


def test_construct_in_python():
    # kind defaults from the class; keyword fields take their Python names
    case = CaseExpr(
        whens=[
            WhenClause(
                when=BinaryExpr(
                    op=BinaryOp.LT,
                    left=ColumnExpr(path=["amount"]),
                    right=LiteralExpr(value=0),
                ),
                then=LiteralExpr(value="refund"),
            )
        ],
        else_=LiteralExpr(value="sale"),
    )
    query = Query(select=[SelectItem(expr=case, alias="kind")])
    # Defaulted kinds count as unset, so dump with exclude_none, not exclude_unset
    data = query.model_dump(by_alias=True, exclude_none=True)
    assert data["select"][0]["expr"]["else"] == {"kind": "literal", "value": "sale"}
    assert Query.model_validate(data) == query


def test_select_without_from():
    query = Query.model_validate({"select": [{"expr": lit(1)}]})
    assert query.from_ is None
    assert query.distinct is False


def test_unknown_kind_rejected():
    with pytest.raises(pydantic.ValidationError, match="union_tag_invalid"):
        EXPR.validate_python({"kind": "exists"})
