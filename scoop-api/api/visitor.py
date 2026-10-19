"""Type-dispatched visitor over the query AST."""

from abc import ABC, abstractmethod
from functools import singledispatchmethod
from typing import Generic, TypeVar

from models import (
    BetweenExpr,
    BinaryExpr,
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
    LikeExpr,
    LiteralExpr,
    OrderItem,
    Query,
    SelectItem,
    StarExpr,
    TableRef,
    UnaryExpr,
    WhenClause,
)

# Context threaded through the walk, and the result of visiting a node.
C = TypeVar("C")
R = TypeVar("R")

Node = Query | SelectItem | OrderItem | WhenClause | FromItem | Expr


class Visitor(ABC, Generic[C, R]):
    """Dispatches visit(node, ctx) to the visit_<node> method for the node's type.

    The base class does no traversal; implementations recurse into children by
    calling self.visit(child, ctx).
    """

    @singledispatchmethod
    def visit(self, node: Node, ctx: C) -> R:
        raise TypeError(f"{type(self).__name__} cannot visit {type(node).__name__}")

    @visit.register
    def _(self, node: Query, ctx: C) -> R:
        return self.visit_query(node, ctx)

    @visit.register
    def _(self, node: SelectItem, ctx: C) -> R:
        return self.visit_select_item(node, ctx)

    @visit.register
    def _(self, node: OrderItem, ctx: C) -> R:
        return self.visit_order_item(node, ctx)

    @visit.register
    def _(self, node: WhenClause, ctx: C) -> R:
        return self.visit_when_clause(node, ctx)

    @visit.register
    def _(self, node: TableRef, ctx: C) -> R:
        return self.visit_table_ref(node, ctx)

    @visit.register
    def _(self, node: Join, ctx: C) -> R:
        return self.visit_join(node, ctx)

    @visit.register
    def _(self, node: DerivedTable, ctx: C) -> R:
        return self.visit_derived_table(node, ctx)

    @visit.register
    def _(self, node: LiteralExpr, ctx: C) -> R:
        return self.visit_literal_expr(node, ctx)

    @visit.register
    def _(self, node: ColumnExpr, ctx: C) -> R:
        return self.visit_column_expr(node, ctx)

    @visit.register
    def _(self, node: StarExpr, ctx: C) -> R:
        return self.visit_star_expr(node, ctx)

    @visit.register
    def _(self, node: UnaryExpr, ctx: C) -> R:
        return self.visit_unary_expr(node, ctx)

    @visit.register
    def _(self, node: BinaryExpr, ctx: C) -> R:
        return self.visit_binary_expr(node, ctx)

    @visit.register
    def _(self, node: IsNullExpr, ctx: C) -> R:
        return self.visit_is_null_expr(node, ctx)

    @visit.register
    def _(self, node: InListExpr, ctx: C) -> R:
        return self.visit_in_list_expr(node, ctx)

    @visit.register
    def _(self, node: BetweenExpr, ctx: C) -> R:
        return self.visit_between_expr(node, ctx)

    @visit.register
    def _(self, node: LikeExpr, ctx: C) -> R:
        return self.visit_like_expr(node, ctx)

    @visit.register
    def _(self, node: CaseExpr, ctx: C) -> R:
        return self.visit_case_expr(node, ctx)

    @visit.register
    def _(self, node: CastExpr, ctx: C) -> R:
        return self.visit_cast_expr(node, ctx)

    @visit.register
    def _(self, node: CallExpr, ctx: C) -> R:
        return self.visit_call_expr(node, ctx)

    # Query

    @abstractmethod
    def visit_query(self, node: Query, ctx: C) -> R: ...

    @abstractmethod
    def visit_select_item(self, node: SelectItem, ctx: C) -> R: ...

    @abstractmethod
    def visit_order_item(self, node: OrderItem, ctx: C) -> R: ...

    @abstractmethod
    def visit_when_clause(self, node: WhenClause, ctx: C) -> R: ...

    # From

    @abstractmethod
    def visit_table_ref(self, node: TableRef, ctx: C) -> R: ...

    @abstractmethod
    def visit_join(self, node: Join, ctx: C) -> R: ...

    @abstractmethod
    def visit_derived_table(self, node: DerivedTable, ctx: C) -> R: ...

    # Expressions

    @abstractmethod
    def visit_literal_expr(self, node: LiteralExpr, ctx: C) -> R: ...

    @abstractmethod
    def visit_column_expr(self, node: ColumnExpr, ctx: C) -> R: ...

    @abstractmethod
    def visit_star_expr(self, node: StarExpr, ctx: C) -> R: ...

    @abstractmethod
    def visit_unary_expr(self, node: UnaryExpr, ctx: C) -> R: ...

    @abstractmethod
    def visit_binary_expr(self, node: BinaryExpr, ctx: C) -> R: ...

    @abstractmethod
    def visit_is_null_expr(self, node: IsNullExpr, ctx: C) -> R: ...

    @abstractmethod
    def visit_in_list_expr(self, node: InListExpr, ctx: C) -> R: ...

    @abstractmethod
    def visit_between_expr(self, node: BetweenExpr, ctx: C) -> R: ...

    @abstractmethod
    def visit_like_expr(self, node: LikeExpr, ctx: C) -> R: ...

    @abstractmethod
    def visit_case_expr(self, node: CaseExpr, ctx: C) -> R: ...

    @abstractmethod
    def visit_cast_expr(self, node: CastExpr, ctx: C) -> R: ...

    @abstractmethod
    def visit_call_expr(self, node: CallExpr, ctx: C) -> R: ...
