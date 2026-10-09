from __future__ import annotations

from typing import Any

import duckdb

from api.connector.base import (
    Column,
    Connector,
    ConnectorFactory,
    Cursor,
    Option,
    Params,
    Result,
    Table,
    TableNotFoundError,
    TablePath,
)

_KINDS = {"BASE TABLE": "table", "VIEW": "view", "LOCAL TEMPORARY": "table"}


class DuckDBConnector(Connector):
    """DuckDB backend. Tables are addressed as (catalog, schema, table)."""

    def __init__(self, database: str = ":memory:") -> None:
        self._conn = duckdb.connect(database)

    def list_tables(self, namespace: TablePath = ()) -> list[TablePath]:
        rows = self._conn.execute(
            "SELECT table_catalog, table_schema, table_name FROM information_schema.tables ORDER BY ALL"
        ).fetchall()
        return [tuple(r) for r in rows if tuple(r[: len(namespace)]) == namespace]

    def _resolve(self, path: TablePath) -> TablePath:
        if len(path) == 3:
            return path
        catalog, schema = self._conn.execute(
            "SELECT current_database(), current_schema()"
        ).fetchone()
        if len(path) == 2:
            return (catalog, *path)
        if len(path) == 1:
            return (catalog, schema, *path)
        raise TableNotFoundError(path)

    def get_table(self, path: TablePath) -> Table:
        path = self._resolve(path)
        row = self._conn.execute(
            "SELECT table_type FROM information_schema.tables "
            "WHERE table_catalog = ? AND table_schema = ? AND table_name = ?",
            list(path),
        ).fetchone()
        if row is None:
            raise TableNotFoundError(path)
        columns = [
            Column(name, data_type, is_nullable == "YES")
            for name, data_type, is_nullable in self._conn.execute(
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                "WHERE table_catalog = ? AND table_schema = ? AND table_name = ? ORDER BY ordinal_position",
                list(path),
            ).fetchall()
        ]
        return Table(path, _KINDS.get(row[0], row[0].lower()), columns)

    def execute(
        self, query: str, params: Params = None, *, page_size: int = 1000
    ) -> Result:
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        return Cursor(cursor, page_size, str)

    def close(self) -> None:
        self._conn.close()


class DuckDBConnectorFactory(ConnectorFactory):
    def kind(self) -> str:
        return "duckdb"

    def name(self) -> str:
        return "DuckDB"

    def options(self) -> dict[str, Option]:
        return {
            "database": Option(
                str,
                "Database file path, or :memory:",
                required=False,
                default=":memory:",
            )
        }

    def _connect(self, options: dict[str, Any]) -> Connector:
        return DuckDBConnector(options["database"])
