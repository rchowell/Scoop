"""ANSI SQL generation from the query AST, with hooks for backend dialects.

Each backend's Dialect subclass lives beside its connector in api/connector/.
"""

import re
from dataclasses import dataclass
from typing import Any

from api.models import (
    BetweenExpr,
    BinaryExpr,
    BinaryOp,
    CallExpr,
    CaseExpr,
    CastExpr,
    ColumnExpr,
    DerivedTable,
    Expr,
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
from api.sql.doc import Doc, concat, group, join, line, nest, render, softline, text
from api.sql.visitor import Visitor

INDENT = 2

# Binding strength, loosest first. A child is parenthesized when it binds more
# loosely than its parent requires.
OR, AND, NOT, COMPARE, CONCAT, ADD, MUL, NEG, ATOM = range(1, 10)

# Operator spelling and binding strength
_BINARY = {
    BinaryOp.OR: ("OR", OR),
    BinaryOp.AND: ("AND", AND),
    BinaryOp.EQ: ("=", COMPARE),
    BinaryOp.NE: ("<>", COMPARE),
    BinaryOp.LT: ("<", COMPARE),
    BinaryOp.LE: ("<=", COMPARE),
    BinaryOp.GT: (">", COMPARE),
    BinaryOp.GE: (">=", COMPARE),
    BinaryOp.CONCAT: ("||", CONCAT),
    BinaryOp.ADD: ("+", ADD),
    BinaryOp.SUB: ("-", ADD),
    BinaryOp.MUL: ("*", MUL),
    BinaryOp.DIV: ("/", MUL),
    BinaryOp.MOD: ("%", MUL),
}

# Function names and type names are spliced into the SQL text, so only allow plain words.
_FUNCTION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TYPE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_ ]*(\(\d+(\s*,\s*\d+)?\))?")

# Stands in for each placeholder until compile() splices in the real ones, so
# escape() sees all SQL text except the placeholders.
_PARAM = "\0"


class UnsupportedSyntax(ValueError):
    pass


@dataclass(frozen=True)
class Ctx:
    params: list[Any]  # shared by every node; bound values in placeholder order
    prec: int = 0  # how tightly the parent binds this node


def _conjuncts(expr: Expr) -> list[Expr]:
    out: list[Expr] = []
    stack = [expr]
    while stack:
        e = stack.pop()
        if isinstance(e, BinaryExpr) and e.op is BinaryOp.AND:
            stack += (e.right, e.left)
        else:
            out.append(e)
    return out


class Dialect(Visitor[Ctx, Doc]):
    """Renders a Query as ANSI SQL with every literal bound as a parameter.

    Subclasses adapt it to a backend by overriding the hooks below, or any visit_* method.
    """

    quote_char = '"'
    no_limit: int | None = None  # LIMIT to emit when OFFSET is only valid after LIMIT

    def compile(self, query: Query, width: int = 80) -> tuple[str, list[Any]]:
        """Render `query` as SQL fitted to `width` columns, plus its parameters in order."""
        ctx = Ctx(params=[])
        first, *rest = render(self.visit(query, ctx), width).split(_PARAM)
        sql = self.escape(first) + "".join(
            self.placeholder(i) + self.escape(chunk) for i, chunk in enumerate(rest, 1)
        )
        return sql, ctx.params

    # Hooks

    def escape(self, sql: str) -> str:
        """Escape SQL text (never a placeholder) for the driver."""
        return sql

    def quote_ident(self, name: str) -> str:
        if _PARAM in name:
            raise UnsupportedSyntax("identifiers cannot contain NUL")
        q = self.quote_char
        return q + name.replace(q, q + q) + q

    def placeholder(self, index: int) -> str:
        """Placeholder for the `index`th parameter, counting from 1."""
        return "?"

    def binary_op(self, op: BinaryOp) -> str:
        return _BINARY[op][0]

    def join_keyword(self, join_type: JoinType) -> str:
        return f"{join_type.upper()} JOIN"

    def limit_offset(self, limit: int | None, offset: int | None) -> list[Doc]:
        if offset is not None and limit is None:
            limit = self.no_limit
        clauses: list[Doc] = []
        if limit is not None:
            clauses.append(text(f"LIMIT {limit}"))
        if offset is not None:
            clauses.append(text(f"OFFSET {offset}"))
        return clauses

    # Helpers

    def _sub(self, node: Expr, ctx: Ctx, prec: int) -> Doc:
        return self.visit(node, Ctx(ctx.params, prec))

    def _wrap(self, doc: Doc, ctx: Ctx, prec: int) -> Doc:
        return concat("(", doc, ")") if prec < ctx.prec else doc

    def _predicate(self, ctx: Ctx, *parts: Expr | Doc | str) -> Doc:
        # A comparison-level construct; operands that are themselves comparisons get parens
        docs = [
            p if isinstance(p, Doc | str) else self._sub(p, ctx, COMPARE + 1)
            for p in parts
        ]
        return self._wrap(concat(*docs), ctx, COMPARE)

    def _path(self, path: list[str]) -> str:
        return ".".join(self.quote_ident(p) for p in path)

    def _list(self, docs: list[Doc]) -> Doc:
        # Comma-separated, one item per line if the group must break
        return join(concat(",", line), docs)

    def _clause(self, keyword: str, docs: list[Doc]) -> Doc:
        return group(keyword, nest(INDENT, line, self._list(docs)))

    def _condition(self, keyword: str, expr: Expr, ctx: Ctx) -> Doc:
        # A top-level AND chain breaks before each AND
        conjuncts = _conjuncts(expr)
        prec = AND if len(conjuncts) > 1 else 0
        first, *rest = (self._sub(c, ctx, prec) for c in conjuncts)
        return group(
            keyword, " ", first, nest(INDENT, *(concat(line, "AND ", c) for c in rest))
        )

    # Query

    def visit_query(self, node: Query, ctx: Ctx) -> Doc:
        ctx = Ctx(ctx.params)
        keyword = "SELECT DISTINCT" if node.distinct else "SELECT"
        clauses = [self._clause(keyword, [self.visit(s, ctx) for s in node.select])]
        if node.from_ is not None:
            clauses.append(group("FROM ", self.visit(node.from_, ctx)))
        if node.where is not None:
            clauses.append(self._condition("WHERE", node.where, ctx))
        if node.group_by:
            clauses.append(
                self._clause("GROUP BY", [self.visit(e, ctx) for e in node.group_by])
            )
        if node.having is not None:
            clauses.append(self._condition("HAVING", node.having, ctx))
        if node.order_by:
            clauses.append(
                self._clause("ORDER BY", [self.visit(o, ctx) for o in node.order_by])
            )
        clauses.extend(self.limit_offset(node.limit, node.offset))
        return group(join(line, clauses))

    def visit_select_item(self, node: SelectItem, ctx: Ctx) -> Doc:
        expr = self.visit(node.expr, ctx)
        if node.alias is None:
            return expr
        return concat(expr, " AS ", self.quote_ident(node.alias))

    def visit_order_item(self, node: OrderItem, ctx: Ctx) -> Doc:
        parts: list[Doc | str] = [self.visit(node.expr, ctx)]
        if node.direction is not None:
            parts.append(" " + node.direction.upper())
        if node.nulls is not None:
            parts.append(" NULLS " + node.nulls.upper())
        return concat(*parts)

    def visit_when_clause(self, node: WhenClause, ctx: Ctx) -> Doc:
        return concat(
            "WHEN ", self.visit(node.when, ctx), " THEN ", self.visit(node.then, ctx)
        )

    # From

    def visit_table_ref(self, node: TableRef, ctx: Ctx) -> Doc:
        path = self._path(node.path)
        if node.alias is None:
            return text(path)
        return concat(path, " AS ", self.quote_ident(node.alias))

    def visit_join(self, node: Join, ctx: Ctx) -> Doc:
        cross = node.join_type is JoinType.CROSS
        if cross and node.on is not None:
            raise UnsupportedSyntax("CROSS JOIN takes no ON condition")
        if not cross and node.on is None:
            raise UnsupportedSyntax(
                f"{node.join_type.value} join requires an ON condition"
            )
        right = self.visit(node.right, ctx)
        if isinstance(node.right, Join):
            # Joins chain left-deep; a nested right-hand join needs grouping
            right = concat("(", nest(INDENT, softline, right), softline, ")")
        parts = [
            self.visit(node.left, ctx),
            line,
            self.join_keyword(node.join_type),
            " ",
            right,
        ]
        if node.on is not None:
            parts.append(nest(INDENT, line, "ON ", self.visit(node.on, ctx)))
        return concat(*parts)

    def visit_derived_table(self, node: DerivedTable, ctx: Ctx) -> Doc:
        return group(
            "(",
            nest(INDENT, softline, self.visit(node.query, ctx)),
            softline,
            ") AS ",
            self.quote_ident(node.alias),
        )

    # Expressions

    def visit_literal_expr(self, node: LiteralExpr, ctx: Ctx) -> Doc:
        if node.value is None:
            return text("NULL")
        ctx.params.append(node.value)
        return text(_PARAM)

    def visit_column_expr(self, node: ColumnExpr, ctx: Ctx) -> Doc:
        return text(self._path(node.path))

    def visit_star_expr(self, node: StarExpr, ctx: Ctx) -> Doc:
        if not node.qualifier:
            return text("*")
        return concat(self._path(node.qualifier), ".*")

    def visit_unary_expr(self, node: UnaryExpr, ctx: Ctx) -> Doc:
        if node.op is UnaryOp.NOT:
            return self._wrap(
                concat("NOT ", self._sub(node.operand, ctx, NOT)), ctx, NOT
            )
        # NEG + 1 so that a nested negation renders -(-x), never the comment --x
        return self._wrap(concat("-", self._sub(node.operand, ctx, NEG + 1)), ctx, NEG)

    def visit_binary_expr(self, node: BinaryExpr, ctx: Ctx) -> Doc:
        prec = _BINARY[node.op][1]
        if node.op is BinaryOp.CONCAT:
            # Backends disagree on where || binds relative to arithmetic, so
            # parenthesize any operator beneath it
            left_prec = right_prec = NEG
        elif prec == COMPARE:
            # Comparisons don't chain
            left_prec = right_prec = prec + 1
        else:
            # Left-associative
            left_prec, right_prec = prec, prec + 1
        doc = concat(
            self._sub(node.left, ctx, left_prec),
            " ",
            self.binary_op(node.op),
            " ",
            self._sub(node.right, ctx, right_prec),
        )
        return self._wrap(doc, ctx, prec)

    def visit_is_null_expr(self, node: IsNullExpr, ctx: Ctx) -> Doc:
        return self._predicate(
            ctx, node.expr, " IS NOT NULL" if node.negated else " IS NULL"
        )

    def visit_in_list_expr(self, node: InListExpr, ctx: Ctx) -> Doc:
        items = [self._sub(e, ctx, 0) for e in node.list_]
        return self._predicate(
            ctx,
            node.expr,
            group(
                " NOT IN (" if node.negated else " IN (",
                nest(INDENT, softline, self._list(items)),
                softline,
                ")",
            ),
        )

    def visit_between_expr(self, node: BetweenExpr, ctx: Ctx) -> Doc:
        keyword = " NOT BETWEEN " if node.negated else " BETWEEN "
        return self._predicate(ctx, node.expr, keyword, node.low, " AND ", node.high)

    def visit_like_expr(self, node: LikeExpr, ctx: Ctx) -> Doc:
        keyword = " NOT LIKE " if node.negated else " LIKE "
        return self._predicate(ctx, node.expr, keyword, node.pattern)

    def visit_case_expr(self, node: CaseExpr, ctx: Ctx) -> Doc:
        ctx = Ctx(ctx.params)
        head: list[Doc | str] = ["CASE"]
        if node.operand is not None:
            head += [" ", self.visit(node.operand, ctx)]
        branches = [self.visit(w, ctx) for w in node.whens]
        if node.else_ is not None:
            branches.append(concat("ELSE ", self.visit(node.else_, ctx)))
        return group(
            *head, nest(INDENT, *(concat(line, b) for b in branches)), line, "END"
        )

    def visit_cast_expr(self, node: CastExpr, ctx: Ctx) -> Doc:
        if not _TYPE_NAME.fullmatch(node.type):
            raise UnsupportedSyntax(f"invalid type name: {node.type!r}")
        return concat("CAST(", self._sub(node.expr, ctx, 0), " AS ", node.type, ")")

    def visit_call_expr(self, node: CallExpr, ctx: Ctx) -> Doc:
        if not _FUNCTION_NAME.fullmatch(node.name):
            raise UnsupportedSyntax(f"invalid function name: {node.name!r}")
        args = self._list([self._sub(a, ctx, 0) for a in node.args])
        distinct = "DISTINCT " if node.distinct else ""
        return group(
            node.name, "(", nest(INDENT, softline, distinct, args), softline, ")"
        )


class PyformatDialect(Dialect):
    """For drivers that use %s placeholders, where a literal % must be written %%."""

    def placeholder(self, index: int) -> str:
        return "%s"

    def escape(self, sql: str) -> str:
        return sql.replace("%", "%%")
