from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import duckdb

from api.connector.connector import Table, TableNotFoundError, TablePath
from api.connector.dbapi import DbApiConnector, within
from api.connector.options import Option
from api.sql import Dialect


class DuckDBDialect(Dialect):
    pass


class DuckDBConnector(DbApiConnector):
    """DuckDB backend. Tables are addressed as (catalog, schema, table)."""

    @classmethod
    def kind(cls) -> str:
        return "duckdb"

    @classmethod
    def display_name(cls) -> str:
        return "DuckDB"

    @classmethod
    def options(cls) -> dict[str, Option]:
        return {
            "database": Option(
                str, "Database file path, or :memory:", default=":memory:"
            )
        }

    @classmethod
    def dialect(cls) -> DuckDBDialect:
        return DuckDBDialect()

    @classmethod
    def errors(cls) -> tuple[type[Exception], ...]:
        return (duckdb.Error,)

    def __init__(self, database: str = ":memory:") -> None:
        self._conn = duckdb.connect(database)

    def list_tables(self, namespace: TablePath = ()) -> list[TablePath]:
        rows = self._fetchall(
            "SELECT table_catalog, table_schema, table_name FROM information_schema.tables ORDER BY ALL"
        )
        return within(rows, namespace)

    def _resolve(self, path: TablePath) -> TablePath:
        if len(path) == 3:
            return path
        ((catalog, schema),) = self._fetchall(
            "SELECT current_database(), current_schema()"
        )
        if len(path) == 2:
            return (catalog, *path)
        if len(path) == 1:
            return (catalog, schema, *path)
        raise TableNotFoundError(path)

    def get_table(self, path: TablePath) -> Table:
        return self._describe(
            self._resolve(path), ("table_catalog", "table_schema", "table_name")
        )

    def _fetchall(self, sql: str, params: Sequence[Any] | None = None) -> list[tuple]:
        # A DuckDB cursor is a duplicate connection; metadata reuses the main one.
        return [tuple(row) for row in self._conn.execute(sql, params).fetchall()]

    def _cursor(self) -> Any:
        return self._conn.cursor()

    def _type_name(self, type_code: Any) -> str | None:
        return str(type_code)

    def close(self) -> None:
        self._conn.close()
