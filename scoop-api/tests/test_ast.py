import pydantic
import pytest

from api.models import (
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
from tests.helpers import AGGREGATE, SCALARS, lit

EXPR = pydantic.TypeAdapter(Expr)


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
