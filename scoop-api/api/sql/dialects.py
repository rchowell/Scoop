"""Backend dialects: small departures from the ANSI rendering in Dialect."""

from api.sql.dialect import COMPARE, Ctx, Dialect, UnsupportedSyntax
from api.sql.doc import Doc, concat, group, join
from models import BinaryExpr, BinaryOp, JoinType, NullsOrder, OrderItem


class _PyformatParams(Dialect):
    """For drivers that use %s placeholders, where a literal % must be written %%."""

    def placeholder(self, index: int) -> str:
        return "%s"

    def escape(self, sql: str) -> str:
        return sql.replace("%", "%%")


class SqliteDialect(Dialect):
    no_limit = -1


class DuckDBDialect(Dialect):
    pass


class PostgresDialect(_PyformatParams):
    pass


class MySQLDialect(_PyformatParams):
    quote_char = "`"
    no_limit = 2**64 - 1  # MySQL's documented "no limit"

    def visit_binary_expr(self, node: BinaryExpr, ctx: Ctx) -> Doc:
        if node.op is not BinaryOp.CONCAT:
            return super().visit_binary_expr(node, ctx)
        # || is logical OR unless PIPES_AS_CONCAT is set
        args = [self._sub(node.left, ctx, 0), self._sub(node.right, ctx, 0)]
        return group("CONCAT(", join(", ", args), ")")

    def join_keyword(self, join_type: JoinType) -> str:
        if join_type is JoinType.FULL:
            raise UnsupportedSyntax("MySQL does not support FULL JOIN")
        return super().join_keyword(join_type)

    def visit_order_item(self, node: OrderItem, ctx: Ctx) -> Doc:
        # No NULLS FIRST/LAST: sort on `x IS NULL` first (false, i.e. non-null, sorts low)
        if node.nulls is None:
            return super().visit_order_item(node, ctx)
        # Render the key before the item so params stay in placeholder order
        key = concat(
            self._sub(node.expr, ctx, COMPARE + 1),
            " IS NULL DESC" if node.nulls is NullsOrder.FIRST else " IS NULL",
        )
        item = super().visit_order_item(node.model_copy(update={"nulls": None}), ctx)
        return concat(key, ", ", item)
