from __future__ import annotations

from typing import Any

import psycopg

from api.connector.connector import Table, TableNotFoundError, TablePath
from api.connector.dbapi import DbApiConnector, within
from api.connector.options import Option
from api.sql import PyformatDialect


class PostgresDialect(PyformatDialect):
    pass


class PostgresConnector(DbApiConnector):
    """Postgres backend. Tables are addressed as (schema, table) within the connected database."""

    @classmethod
    def kind(cls) -> str:
        return "postgres"

    @classmethod
    def display_name(cls) -> str:
        return "PostgreSQL"

    @classmethod
    def options(cls) -> dict[str, Option]:
        return {
            "host": Option(str, "Server hostname"),
            "port": Option(int, "Server port", default=5432),
            "user": Option(str, "Username"),
            "password": Option(str, "Password", optional=True, secret=True),
            "database": Option(str, "Database name"),
        }

    @classmethod
    def dialect(cls) -> PostgresDialect:
        return PostgresDialect()

    @classmethod
    def errors(cls) -> tuple[type[Exception], ...]:
        return (psycopg.Error,)

    def __init__(self, database: str, **options: Any) -> None:
        self._conn = psycopg.connect(dbname=database, autocommit=True, **options)

    def list_tables(self, namespace: TablePath = ()) -> list[TablePath]:
        rows = self._fetchall(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
            "AND table_schema NOT LIKE 'pg\\_toast%' ORDER BY 1, 2"
        )
        return within(rows, namespace)

    def get_table(self, path: TablePath) -> Table:
        if len(path) == 1:
            ((schema,),) = self._fetchall("SELECT current_schema()")
            path = (schema, *path)
        if len(path) != 2:
            raise TableNotFoundError(path)
        return self._describe(path, ("table_schema", "table_name"))

    def _type_name(self, oid: int) -> str | None:
        info = self._conn.adapters.types.get(oid)
        return info.regtype if info else None

    def _cursor(self) -> Any:
        return self._conn.cursor()

    def close(self) -> None:
        self._conn.close()
