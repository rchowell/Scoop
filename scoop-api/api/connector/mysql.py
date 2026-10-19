from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pymysql
from pymysql.constants import FIELD_TYPE

from api.connector.base import (
    Column,
    Connector,
    ConnectorFactory,
    Option,
    Table,
    TableNotFoundError,
    TablePath,
)
from api.sql import MySQLDialect

Params = Sequence[Any] | Mapping[str, Any] | None

_KINDS = {"BASE TABLE": "table", "VIEW": "view", "SYSTEM VIEW": "view"}
_SYSTEM_SCHEMAS = ("mysql", "sys", "performance_schema", "information_schema")

# FIELD_TYPE has aliases (CHAR = TINY, INTERVAL = ENUM); keep the first name defined.
_TYPE_NAMES: dict[int, str] = {}
for _name, _code in vars(FIELD_TYPE).items():
    if _name.isupper():
        _TYPE_NAMES.setdefault(_code, _name.lower())


class MySQLConnector(Connector):
    """MySQL backend. Tables are addressed as (database, table)."""

    dialect = MySQLDialect()

    def __init__(self, **connect_kwargs: Any) -> None:
        self._conn = pymysql.connect(**connect_kwargs, autocommit=True)

    def _query(self, query: str, params: Params = None) -> list[tuple[Any, ...]]:
        with self._conn.cursor() as cursor:
            cursor.execute(query, params)
            return list(cursor.fetchall())

    def list_tables(self, namespace: TablePath = ()) -> list[TablePath]:
        rows = self._query(
            "SELECT table_schema AS s, table_name AS t FROM information_schema.tables "
            "WHERE table_schema NOT IN %s ORDER BY s, t",
            (_SYSTEM_SCHEMAS,),
        )
        return [tuple(r) for r in rows if tuple(r[: len(namespace)]) == namespace]

    def get_table(self, path: TablePath) -> Table:
        if len(path) == 1:
            ((database,),) = self._query("SELECT DATABASE()")
            if database is None:
                raise TableNotFoundError(path)
            path = (database, *path)
        if len(path) != 2:
            raise TableNotFoundError(path)
        rows = self._query(
            "SELECT table_type AS k FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s",
            path,
        )
        if not rows:
            raise TableNotFoundError(path)
        columns = [
            Column(name, data_type, is_nullable == "YES")
            for name, data_type, is_nullable in self._query(
                "SELECT column_name AS n, data_type AS t, is_nullable AS nl "
                "FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                path,
            )
        ]
        kind = rows[0][0]
        return Table(path, _KINDS.get(kind, kind.lower()), columns)

    def _cursor(self) -> Any:
        return self._conn.cursor()

    def _type_name(self, type_code: Any) -> str | None:
        return _TYPE_NAMES.get(type_code)

    def close(self) -> None:
        self._conn.close()


class MySQLConnectorFactory(ConnectorFactory):
    def kind(self) -> str:
        return "mysql"

    def name(self) -> str:
        return "MySQL"

    def options(self) -> dict[str, Option]:
        return {
            "host": Option(str, "Server hostname"),
            "port": Option(int, "Server port", required=False, default=3306),
            "user": Option(str, "Username"),
            "password": Option(str, "Password", required=False, secret=True),
            "database": Option(str, "Database name"),
        }

    def _connect(self, options: dict[str, Any]) -> Connector:
        return MySQLConnector(**options)
