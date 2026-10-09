from __future__ import annotations

from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo

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


class PostgresConnector(Connector):
    """Postgres backend. Tables are addressed as (schema, table) within the connected database."""

    def __init__(self, conninfo: str) -> None:
        self._conn = psycopg.connect(conninfo, autocommit=True)

    def list_tables(self, namespace: TablePath = ()) -> list[TablePath]:
        rows = self._conn.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
            "AND table_schema NOT LIKE 'pg\\_toast%' ORDER BY 1, 2"
        ).fetchall()
        return [tuple(r) for r in rows if tuple(r[: len(namespace)]) == namespace]

    def get_table(self, path: TablePath) -> Table:
        if len(path) == 1:
            (schema,) = self._conn.execute("SELECT current_schema()").fetchone()
            path = (schema, *path)
        if len(path) != 2:
            raise TableNotFoundError(path)
        row = self._conn.execute(
            "SELECT table_type FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s",
            path,
        ).fetchone()
        if row is None:
            raise TableNotFoundError(path)
        columns = [
            Column(name, data_type, is_nullable == "YES")
            for name, data_type, is_nullable in self._conn.execute(
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                path,
            ).fetchall()
        ]
        return Table(path, _KINDS.get(row[0], row[0].lower()), columns)

    def _type_name(self, oid: int) -> str | None:
        info = self._conn.adapters.types.get(oid)
        return info.regtype if info else None

    def execute(
        self, query: str, params: Params = None, *, page_size: int = 1000
    ) -> Result:
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        return Cursor(cursor, page_size, self._type_name)

    def close(self) -> None:
        self._conn.close()


class PostgresConnectorFactory(ConnectorFactory):
    def kind(self) -> str:
        return "postgres"

    def name(self) -> str:
        return "PostgreSQL"

    def options(self) -> dict[str, Option]:
        return {
            "host": Option(str, "Server hostname"),
            "port": Option(int, "Server port", required=False, default=5432),
            "user": Option(str, "Username"),
            "password": Option(str, "Password", required=False, secret=True),
            "dbname": Option(str, "Database name"),
        }

    def _connect(self, options: dict[str, Any]) -> Connector:
        return PostgresConnector(make_conninfo(**options))
