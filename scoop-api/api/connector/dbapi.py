"""Shared implementation for connectors whose driver follows DB-API 2.0."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable, Iterable, Sequence
from contextlib import closing
from typing import Any

from api.connector.connector import (
    PAGE_SIZE,
    Column,
    Connector,
    Page,
    Result,
    Table,
    TableNotFoundError,
    TablePath,
)
from api.models import Query

# information_schema.tables.table_type values, normalized to Table.kind.
TABLE_KINDS = {
    "BASE TABLE": "table",
    "LOCAL TEMPORARY": "table",
    "VIEW": "view",
    "SYSTEM VIEW": "view",
}


class DbApiConnector(Connector):
    """A Connector over a DB-API 2.0 driver: queries run on `_cursor()` cursors,
    rendered by the class's dialect."""

    def execute(self, query: Query, *, page_size: int = PAGE_SIZE) -> Result:
        if page_size < 1:
            raise ValueError("page_size must be >= 1")
        sql, params = self.dialect().compile(query)
        cursor = self._cursor()
        cursor.execute(sql, params)
        return CursorResult(cursor, page_size, self._type_name)

    @abstractmethod
    def _cursor(self) -> Any:
        """A fresh DB-API 2.0 cursor."""

    def _type_name(self, type_code: Any) -> str | None:
        """Backend-native type name for a cursor description's type_code."""
        return None

    def _fetchall(self, sql: str, params: Sequence[Any] | None = None) -> list[tuple]:
        """Run a metadata query on a fresh cursor."""
        with closing(self._cursor()) as cursor:
            if params is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, params)
            return [tuple(row) for row in cursor.fetchall()]

    def _describe(self, path: TablePath, keys: Sequence[str]) -> Table:
        """Describe `path` from information_schema, matching each part to a column in `keys`."""
        where = " AND ".join(
            f"{key} = {self.dialect().placeholder(i)}" for i, key in enumerate(keys, 1)
        )
        rows = self._fetchall(
            f"SELECT table_type FROM information_schema.tables WHERE {where}",
            list(path),
        )
        if not rows:
            raise TableNotFoundError(path)
        columns = [
            Column(name, data_type, is_nullable == "YES")
            for name, data_type, is_nullable in self._fetchall(
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                f"WHERE {where} ORDER BY ordinal_position",
                list(path),
            )
        ]
        kind = rows[0][0]
        return Table(path, TABLE_KINDS.get(kind, kind.lower()), columns)


def within(paths: Iterable[Sequence[str]], namespace: Sequence[str]) -> list[TablePath]:
    """The paths that start with `namespace`."""
    namespace = tuple(namespace)
    return [tuple(p) for p in paths if tuple(p[: len(namespace)]) == namespace]


def dedupe_names(names: Sequence[str]) -> list[str]:
    """Suffix repeated names (a, a -> a, a_1) so they can key a columnar dict."""
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        candidate, n = name, 0
        while candidate in seen:
            n += 1
            candidate = f"{name}_{n}"
        seen.add(candidate)
        out.append(candidate)
    return out


class CursorResult(Result):
    """Result over any DB-API 2.0 cursor that has already executed a query."""

    def __init__(
        self, cursor: Any, page_size: int, type_name: Callable[[Any], str | None]
    ) -> None:
        self._cursor = cursor
        self._page_size = page_size
        self._closed = False
        description = cursor.description or []
        names = dedupe_names([d[0] for d in description])
        self._columns = [
            Column(name, type_name(d[1])) for name, d in zip(names, description)
        ]

    @property
    def columns(self) -> list[Column]:
        return self._columns

    def __next__(self) -> Page:
        if self._closed or not self._columns:
            self.close()
            raise StopIteration
        rows = self._cursor.fetchmany(self._page_size)
        if not rows:
            self.close()
            raise StopIteration
        data = {
            col.name: list(values) for col, values in zip(self._columns, zip(*rows))
        }
        return Page(self._columns, data)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._cursor.close()
