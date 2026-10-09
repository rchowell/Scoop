"""Minimal, JDBC-inspired interface for querying diverse database backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Self

# Hierarchical table identifier, e.g. ("main", "users") or ("memory", "main", "users").
TablePath = tuple[str, ...]

Params = Sequence[Any] | Mapping[str, Any] | None


class ConnectorError(Exception):
    pass


class TableNotFoundError(ConnectorError):
    def __init__(self, path: TablePath) -> None:
        super().__init__(f"table not found: {'.'.join(path)}")
        self.path = path


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
    @abstractmethod
    def list_tables(self, namespace: TablePath = ()) -> list[TablePath]:
        """List tables and views whose path starts with `namespace`."""

    @abstractmethod
    def get_table(self, path: TablePath) -> Table:
        """Describe a table or view; raises TableNotFoundError if it doesn't exist."""

    @abstractmethod
    def execute(
        self, query: str, params: Params = None, *, page_size: int = 1000
    ) -> Result:
        """Run `query` with DB-API style `params`, returning pages of at most `page_size` rows."""

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class InvalidOptionsError(ConnectorError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("invalid options: " + "; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Option:
    """Describes one option a ConnectorFactory needs to instantiate its connector."""

    type: type  # str | int | bool
    description: str
    required: bool = True
    default: Any = None
    secret: bool = False  # e.g. passwords; should be masked when displayed


def _coerce(value: Any, expected: type) -> Any:
    # bool is a subclass of int, so check it explicitly in both directions.
    if expected is int and isinstance(value, str):
        return int(value)
    if isinstance(value, expected) and not (
        expected is int and isinstance(value, bool)
    ):
        return value
    raise TypeError(f"expected {expected.__name__}, got {type(value).__name__}")


class ConnectorFactory(ABC):
    """Describes a connector backend and instantiates it from a dict of options."""

    @abstractmethod
    def kind(self) -> str:
        """Stable identifier, e.g. "postgres"."""

    @abstractmethod
    def name(self) -> str:
        """Display name, e.g. "PostgreSQL"."""

    @abstractmethod
    def options(self) -> dict[str, Option]:
        """Every option needed to instantiate the connector, keyed by option name."""

    def create(self, options: Mapping[str, Any]) -> Connector:
        """Validate `options` and instantiate the connector."""
        return self._connect(self.validate(options))

    def validate(self, options: Mapping[str, Any]) -> dict[str, Any]:
        """Check `options` against `self.options()`, returning them coerced with defaults filled in."""
        spec = self.options()
        problems = [f"unknown option: {key}" for key in options if key not in spec]
        out: dict[str, Any] = {}
        for key, option in spec.items():
            value = options.get(key)
            if value is None:
                if option.required:
                    problems.append(f"missing required option: {key}")
                out[key] = option.default
                continue
            try:
                out[key] = _coerce(value, option.type)
            except (TypeError, ValueError):
                problems.append(f"{key}: expected {option.type.__name__}")
        if problems:
            raise InvalidOptionsError(problems)
        return out

    @abstractmethod
    def _connect(self, options: dict[str, Any]) -> Connector:
        """Instantiate the connector from options that have already been validated."""


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


class Cursor(Result):
    """Result over any DB-API 2.0 cursor that has already executed a query."""

    def __init__(
        self, cursor: Any, page_size: int, type_name: Callable[[Any], str | None]
    ) -> None:
        if page_size < 1:
            cursor.close()
            raise ValueError("page_size must be >= 1")
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
