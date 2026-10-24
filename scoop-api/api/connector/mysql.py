from __future__ import annotations

from typing import Any

import pymysql
from pymysql.constants import FIELD_TYPE

from api.connector.connector import Table, TableNotFoundError, TablePath
from api.connector.dbapi import DbApiConnector, within
from api.connector.options import Option
from api.models import BinaryExpr, BinaryOp, JoinType, NullsOrder, OrderItem
from api.sql import PyformatDialect, UnsupportedSyntax
from api.sql.dialect import COMPARE, Ctx
from api.sql.doc import Doc, concat, group, join

_SYSTEM_SCHEMAS = ("mysql", "sys", "performance_schema", "information_schema")

# FIELD_TYPE has aliases (CHAR = TINY, INTERVAL = ENUM); keep the first name defined.
_TYPE_NAMES: dict[int, str] = {}
for _name, _code in vars(FIELD_TYPE).items():
    if _name.isupper():
        _TYPE_NAMES.setdefault(_code, _name.lower())


class MySQLDialect(PyformatDialect):
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


class MySQLConnector(DbApiConnector):
    """MySQL backend. Tables are addressed as (database, table)."""

    @classmethod
    def kind(cls) -> str:
        return "mysql"

    @classmethod
    def display_name(cls) -> str:
        return "MySQL"

    @classmethod
    def options(cls) -> dict[str, Option]:
        return {
            "host": Option(str, "Server hostname"),
            "port": Option(int, "Server port", default=3306),
            "user": Option(str, "Username"),
            "password": Option(str, "Password", optional=True, secret=True),
            "database": Option(str, "Database name"),
        }

    @classmethod
    def dialect(cls) -> MySQLDialect:
        return MySQLDialect()

    @classmethod
    def errors(cls) -> tuple[type[Exception], ...]:
        return (pymysql.Error,)

    def __init__(self, **options: Any) -> None:
        self._conn = pymysql.connect(**options, autocommit=True)

    def list_tables(self, namespace: TablePath = ()) -> list[TablePath]:
        rows = self._fetchall(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN %s ORDER BY 1, 2",
            (_SYSTEM_SCHEMAS,),
        )
        return within(rows, namespace)

    def get_table(self, path: TablePath) -> Table:
        if len(path) == 1:
            ((database,),) = self._fetchall("SELECT DATABASE()")
            if database is None:
                raise TableNotFoundError(path)
            path = (database, *path)
        if len(path) != 2:
            raise TableNotFoundError(path)
        return self._describe(path, ("table_schema", "table_name"))

    def _cursor(self) -> Any:
        return self._conn.cursor()

    def _type_name(self, type_code: Any) -> str | None:
        return _TYPE_NAMES.get(type_code)

    def close(self) -> None:
        self._conn.close()
