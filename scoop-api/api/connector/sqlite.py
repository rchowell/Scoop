from __future__ import annotations

from typing import Any

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
from api.db import connect


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


class SqliteConnector(Connector):
    """SQLite backend. Tables are addressed as (schema, table); schema is main, temp or an attached db."""

    def __init__(self, path: str) -> None:
        self._conn = connect(path)
        self._conn.row_factory = None
        self._conn.isolation_level = None  # autocommit, like JDBC's default

    def _schemas(self) -> list[str]:
        return [
            name
            for (name,) in self._conn.execute("SELECT name FROM pragma_database_list")
        ]

    def list_tables(self, namespace: TablePath = ()) -> list[TablePath]:
        paths: list[TablePath] = []
        for schema in self._schemas():
            if namespace and namespace[0] != schema:
                continue
            rows = self._conn.execute(
                f"SELECT name FROM {_quote(schema)}.sqlite_master "
                "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name"
            )
            paths.extend((schema, name) for (name,) in rows)
        return [p for p in paths if p[: len(namespace)] == namespace]

    def get_table(self, path: TablePath) -> Table:
        if len(path) == 1:
            path = ("main", *path)
        if len(path) != 2 or path[0] not in self._schemas():
            raise TableNotFoundError(path)
        schema, name = path
        row = self._conn.execute(
            f"SELECT type FROM {_quote(schema)}.sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (name,),
        ).fetchone()
        if row is None:
            raise TableNotFoundError(path)
        columns = [
            Column(col_name, col_type or None, not notnull)
            for col_name, col_type, notnull in self._conn.execute(
                'SELECT name, type, "notnull" FROM pragma_table_info(?, ?) ORDER BY cid',
                (name, schema),
            )
        ]
        return Table(path, row[0], columns)

    def execute(
        self, query: str, params: Params = None, *, page_size: int = 1000
    ) -> Result:
        cursor = self._conn.cursor()
        cursor.execute(query, params if params is not None else ())
        # sqlite3 only reports declared types for table columns, not query results.
        return Cursor(cursor, page_size, lambda _: None)

    def close(self) -> None:
        self._conn.close()


class SqliteConnectorFactory(ConnectorFactory):
    def kind(self) -> str:
        return "sqlite"

    def name(self) -> str:
        return "SQLite"

    def options(self) -> dict[str, Option]:
        return {"path": Option(str, "Database file path")}

    def _connect(self, options: dict[str, Any]) -> Connector:
        return SqliteConnector(options["path"])
