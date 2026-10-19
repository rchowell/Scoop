import typing

import pytest

import models
from api.visitor import Visitor
from models import (
    BetweenExpr,
    BinaryExpr,
    BinaryOp,
    CallExpr,
    CaseExpr,
    CastExpr,
    ColumnExpr,
    DerivedTable,
    Expr,
    FromItem,
    InListExpr,
    IsNullExpr,
    Join,
    JoinType,
    LikeExpr,
    LiteralExpr,
    OrderItem,
    Query,
    SelectItem,
    StarExpr,
    TableRef,
    UnaryExpr,
    UnaryOp,
    WhenClause,
)
from tests.test_ast import AGGREGATE, SCALARS


class KindVisitor(Visitor[list[str], str]):
    """Records which visit_* method each node was dispatched to."""

    def _record(self, name: str, ctx: list[str]) -> str:
        ctx.append(name)
        return name

    def visit_query(self, node, ctx):
        return self._record("visit_query", ctx)

    def visit_select_item(self, node, ctx):
        return self._record("visit_select_item", ctx)

    def visit_order_item(self, node, ctx):
        return self._record("visit_order_item", ctx)

    def visit_when_clause(self, node, ctx):
        return self._record("visit_when_clause", ctx)

    def visit_table_ref(self, node, ctx):
        return self._record("visit_table_ref", ctx)

    def visit_join(self, node, ctx):
        return self._record("visit_join", ctx)

    def visit_derived_table(self, node, ctx):
        return self._record("visit_derived_table", ctx)

    def visit_literal_expr(self, node, ctx):
        return self._record("visit_literal_expr", ctx)

    def visit_column_expr(self, node, ctx):
        return self._record("visit_column_expr", ctx)

    def visit_star_expr(self, node, ctx):
        return self._record("visit_star_expr", ctx)

    def visit_unary_expr(self, node, ctx):
        return self._record("visit_unary_expr", ctx)

    def visit_binary_expr(self, node, ctx):
        return self._record("visit_binary_expr", ctx)

    def visit_is_null_expr(self, node, ctx):
        return self._record("visit_is_null_expr", ctx)

    def visit_in_list_expr(self, node, ctx):
        return self._record("visit_in_list_expr", ctx)

    def visit_between_expr(self, node, ctx):
        return self._record("visit_between_expr", ctx)

    def visit_like_expr(self, node, ctx):
        return self._record("visit_like_expr", ctx)

    def visit_case_expr(self, node, ctx):
        return self._record("visit_case_expr", ctx)

    def visit_cast_expr(self, node, ctx):
        return self._record("visit_cast_expr", ctx)

    def visit_call_expr(self, node, ctx):
        return self._record("visit_call_expr", ctx)


class ColumnCollector(Visitor[list[tuple[str, ...]], None]):
    """Walks the whole tree, appending every column path to ctx in visit order."""

    def _all(self, nodes, ctx):
        for node in nodes or ():
            self.visit(node, ctx)

    def _opt(self, node, ctx):
        if node is not None:
            self.visit(node, ctx)

    def visit_query(self, node, ctx):
        self._all(node.select, ctx)
        self._opt(node.from_, ctx)
        self._opt(node.where, ctx)
        self._all(node.group_by, ctx)
        self._opt(node.having, ctx)
        self._all(node.order_by, ctx)

    def visit_select_item(self, node, ctx):
        self.visit(node.expr, ctx)

    def visit_order_item(self, node, ctx):
        self.visit(node.expr, ctx)

    def visit_when_clause(self, node, ctx):
        self.visit(node.when, ctx)
        self.visit(node.then, ctx)

    def visit_table_ref(self, node, ctx):
        pass

    def visit_join(self, node, ctx):
        self.visit(node.left, ctx)
        self.visit(node.right, ctx)
        self._opt(node.on, ctx)

    def visit_derived_table(self, node, ctx):
        self.visit(node.query, ctx)

    def visit_literal_expr(self, node, ctx):
        pass

    def visit_column_expr(self, node, ctx):
        ctx.append(tuple(node.path))

    def visit_star_expr(self, node, ctx):
        pass

    def visit_unary_expr(self, node, ctx):
        self.visit(node.operand, ctx)

    def visit_binary_expr(self, node, ctx):
        self.visit(node.left, ctx)
        self.visit(node.right, ctx)

    def visit_is_null_expr(self, node, ctx):
        self.visit(node.expr, ctx)

    def visit_in_list_expr(self, node, ctx):
        self.visit(node.expr, ctx)
        self._all(node.list_, ctx)

    def visit_between_expr(self, node, ctx):
        self.visit(node.expr, ctx)
        self.visit(node.low, ctx)
        self.visit(node.high, ctx)

    def visit_like_expr(self, node, ctx):
        self.visit(node.expr, ctx)
        self.visit(node.pattern, ctx)

    def visit_case_expr(self, node, ctx):
        self._opt(node.operand, ctx)
        self._all(node.whens, ctx)
        self._opt(node.else_, ctx)

    def visit_cast_expr(self, node, ctx):
        self.visit(node.expr, ctx)

    def visit_call_expr(self, node, ctx):
        self._all(node.args, ctx)


def _union_members(alias) -> set[type]:
    # Expr/FromItem are TypeAliasType(Annotated[Union[...], discriminator]);
    # some members are forward references by name.
    (union, *_) = typing.get_args(alias.__value__)
    return {
        getattr(models, m.__forward_arg__) if isinstance(m, typing.ForwardRef) else m
        for m in typing.get_args(union)
    }


AST_NODES = (
    {Query, SelectItem, OrderItem, WhenClause}
    | _union_members(FromItem)
    | _union_members(Expr)
)

COL = ColumnExpr(path=["x"])
ONE = LiteralExpr(value=1)
TABLE = TableRef(path=["t"])
QUERY = Query(select=[SelectItem(expr=StarExpr())], from_=TABLE)

NODES = [
    QUERY,
    SelectItem(expr=COL, alias="x"),
    OrderItem(expr=COL),
    WhenClause(when=COL, then=ONE),
    TABLE,
    Join(join_type=JoinType.CROSS, left=TABLE, right=TABLE),
    DerivedTable(query=QUERY, alias="d"),
    ONE,
    COL,
    StarExpr(),
    UnaryExpr(op=UnaryOp.NEG, operand=COL),
    BinaryExpr(op=BinaryOp.ADD, left=COL, right=ONE),
    IsNullExpr(expr=COL),
    InListExpr(expr=COL, list_=[ONE]),
    BetweenExpr(expr=COL, low=ONE, high=ONE),
    LikeExpr(expr=COL, pattern=LiteralExpr(value="a%")),
    CaseExpr(whens=[WhenClause(when=COL, then=ONE)]),
    CastExpr(expr=COL, type="date"),
    CallExpr(name="count", args=[StarExpr()]),
]


def _method_name(cls: type) -> str:
    # CamelCase class name -> visit_snake_case
    snake = "".join(f"_{c.lower()}" if c.isupper() else c for c in cls.__name__)
    return f"visit{snake}"


def test_nodes_cover_ast():
    assert {type(node) for node in NODES} == AST_NODES


def test_abstract_methods_cover_ast():
    assert Visitor.__abstractmethods__ == {_method_name(cls) for cls in AST_NODES}


@pytest.mark.parametrize("node", NODES, ids=lambda node: type(node).__name__)
def test_dispatch(node):
    # Dispatch alone does not recurse, e.g. into Query's children
    ctx = []
    expected = _method_name(type(node))
    assert KindVisitor().visit(node, ctx) == expected
    assert ctx == [expected]


@pytest.mark.parametrize(
    ("data", "columns"),
    [
        (
            AGGREGATE,
            [
                ("c", "region"),
                ("o", "total"),
                ("o", "customer_id"),
                ("c", "id"),
                ("o", "status"),
                ("o", "created_at"),
                ("c", "deleted_at"),
                ("c", "region"),
                ("revenue",),
            ],
        ),
        (
            SCALARS,
            [
                ("amount",),
                ("nickname",),
                ("name",),
                ("discount",),
                ("user_id",),
                ("name",),
            ],
        ),
    ],
    ids=["aggregate", "scalars"],
)
def test_recursive_walk(data, columns):
    ctx = []
    assert ColumnCollector().visit(Query.model_validate(data), ctx) is None
    assert ctx == columns


def test_incomplete_visitor_is_abstract():
    class Partial(Visitor[None, None]):
        def visit_query(self, node, ctx):
            return None

    with pytest.raises(TypeError, match="abstract"):
        Partial()


def test_unknown_node_rejected():
    with pytest.raises(TypeError, match="KindVisitor cannot visit object"):
        KindVisitor().visit(object(), [])
