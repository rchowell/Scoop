from __future__ import annotations

import sqlite3
from typing import Any

from api.connector.connector import Column, Table, TableNotFoundError, TablePath
from api.connector.dbapi import DbApiConnector, within
from api.connector.options import Option
from api.sql import Dialect


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


class SQLiteDialect(Dialect):
    no_limit = -1


class SQLiteConnector(DbApiConnector):
    """SQLite backend. Tables are addressed as (schema, table); schema is main, temp or an attached db."""

    @classmethod
    def kind(cls) -> str:
        return "sqlite"

    @classmethod
    def display_name(cls) -> str:
        return "SQLite"

    @classmethod
    def options(cls) -> dict[str, Option]:
        return {"database": Option(str, "Database file path")}

    @classmethod
    def dialect(cls) -> SQLiteDialect:
        return SQLiteDialect()

    @classmethod
    def errors(cls) -> tuple[type[Exception], ...]:
        return (sqlite3.Error,)

    def __init__(self, database: str) -> None:
        # Cached connectors serve requests from any threadpool worker.
        # isolation_level=None is autocommit, like JDBC's default.
        self._conn = sqlite3.connect(
            database, check_same_thread=False, isolation_level=None
        )

    def _schemas(self) -> list[str]:
        return [
            name for (name,) in self._fetchall("SELECT name FROM pragma_database_list")
        ]

    def list_tables(self, namespace: TablePath = ()) -> list[TablePath]:
        paths: list[TablePath] = []
        for schema in self._schemas():
            if namespace and namespace[0] != schema:
                continue
            rows = self._fetchall(
                f"SELECT name FROM {_quote(schema)}.sqlite_master "
                "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name"
            )
            paths.extend((schema, name) for (name,) in rows)
        return within(paths, namespace)

    def get_table(self, path: TablePath) -> Table:
        if len(path) == 1:
            path = ("main", *path)
        if len(path) != 2 or path[0] not in self._schemas():
            raise TableNotFoundError(path)
        schema, name = path
        rows = self._fetchall(
            f"SELECT type FROM {_quote(schema)}.sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (name,),
        )
        if not rows:
            raise TableNotFoundError(path)
        columns = [
            Column(col_name, col_type or None, not notnull)
            for col_name, col_type, notnull in self._fetchall(
                'SELECT name, type, "notnull" FROM pragma_table_info(?, ?) ORDER BY cid',
                (name, schema),
            )
        ]
        return Table(path, rows[0][0], columns)

    # No _type_name: sqlite3 only reports declared types for table columns, not query results.
    def _cursor(self) -> Any:
        return self._conn.cursor()

    def close(self) -> None:
        self._conn.close()
