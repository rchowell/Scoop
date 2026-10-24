"""Minimal, JDBC-inspired interface for querying diverse database backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

from api.models import Query
from api.sql import Dialect

if TYPE_CHECKING:
    from api.connector.options import Option

# Hierarchical table identifier, e.g. ("main", "users") or ("memory", "main", "users").
TablePath = tuple[str, ...]

# Rows per page when the caller doesn't say.
PAGE_SIZE = 1000


class ConnectorError(Exception):
    pass


class TableNotFoundError(ConnectorError):
    def __init__(self, path: TablePath) -> None:
        super().__init__(f"table not found: {'.'.join(map(str, path))}")
        self.path = path


class InvalidOptionsError(ConnectorError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("invalid options: " + "; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Column:
    name: str
    type: str | None  # backend-native type name; None when the backend can't say
    nullable: bool | None = None


@dataclass(frozen=True)
class Table:
    path: TablePath
    kind: str  # "table" | "view"
    columns: list[Column]


@dataclass(frozen=True)
class Page:
    """A batch of rows in columnar form: {column_name: [values...]}."""

    columns: list[Column]
    data: dict[str, list[Any]]

    def __len__(self) -> int:
        return len(self.data[self.columns[0].name]) if self.columns else 0


class Result(ABC, Iterator[Page]):
    """An iterator of result pages. Close it (or use it as a context manager) when done."""

    @property
    @abstractmethod
    def columns(self) -> list[Column]: ...

    @abstractmethod
    def __next__(self) -> Page: ...

    @abstractmethod
    def close(self) -> None: ...

    def __iter__(self) -> Self:
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class Connector(ABC):
    """A live connection to one database backend.

    Implementations describe their backend with the classmethods below and are
    created by `create_connector`, which validates a dict of options against
    `options()` and passes them to `__init__` as keyword arguments.
    """

    @classmethod
    @abstractmethod
    def kind(cls) -> str:
        """Stable identifier, e.g. "postgres"."""

    @classmethod
    @abstractmethod
    def display_name(cls) -> str:
        """Display name, e.g. "PostgreSQL"."""

    @classmethod
    @abstractmethod
    def options(cls) -> dict[str, Option]:
        """Every option needed to connect, keyed by option name, in display order."""

    @classmethod
    @abstractmethod
    def dialect(cls) -> Dialect:
        """Renders a Query AST as this backend's SQL."""

    @classmethod
    def errors(cls) -> tuple[type[Exception], ...]:
        """Driver errors caused by bad input (SQL, paths, credentials), not server faults."""
        return ()

    @abstractmethod
    def list_tables(self, namespace: TablePath = ()) -> list[TablePath]:
        """List tables and views whose path starts with `namespace`."""

    @abstractmethod
    def get_table(self, path: TablePath) -> Table:
        """Describe a table or view; raises TableNotFoundError if it doesn't exist."""

    @abstractmethod
    def execute(self, query: Query, *, page_size: int = PAGE_SIZE) -> Result:
        """Run `query`, returning pages of at most `page_size` rows."""

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
