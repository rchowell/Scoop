"""Run small, read-only queries on behalf of the query assistant."""

from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from api.connector import Column, Connector
from api.query import CLIENT_ERRORS, collect

MAX_CELL_CHARS = 200

# Statement kinds the assistant may run; anything else (DML, DDL, SET, PRAGMA, ...) is refused.
_READ_ROOTS = (exp.Query, exp.Describe, exp.Show)
# Nodes that write, even when nested in an otherwise read-only statement
# (e.g. Postgres' `WITH d AS (DELETE ... RETURNING *) SELECT ...`).
_WRITE_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Copy,
    exp.Into,
    exp.Command,
)


class NotReadOnlyError(ValueError):
    pass


def parse_one(sql: str, dialect: str) -> exp.Expression:
    """Parse exactly one statement; raises ParseError or NotReadOnlyError."""
    statements = [s for s in sqlglot.parse(sql, dialect=dialect) if s is not None]
    if len(statements) != 1:
        raise NotReadOnlyError(f"expected exactly one statement, got {len(statements)}")
    return statements[0]


def check_read_only(sql: str, dialect: str) -> exp.Expression:
    """Return the parsed statement if it only reads; raise NotReadOnlyError otherwise."""
    try:
        statement = parse_one(sql, dialect)
    except ParseError as e:
        raise NotReadOnlyError(f"could not parse SQL: {e}") from e
    if not isinstance(statement, _READ_ROOTS):
        raise NotReadOnlyError(
            f"only SELECT, DESCRIBE and SHOW are allowed, not {statement.key.upper()}"
        )
    if writer := next(statement.find_all(*_WRITE_NODES), None):
        raise NotReadOnlyError(f"{writer.key.upper()} is not allowed")
    return statement


@dataclass(frozen=True)
class Sample:
    columns: list[Column]
    rows: list[list[Any]]
    truncated: bool


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + "…"
    return value


def _run(connector: Connector, sql: str, max_rows: int) -> Sample:
    with connector.execute(sql, page_size=max_rows) as result:
        columns = result.columns
        data, truncated = collect(result, max_rows)
    rows = [list(r) for r in zip(*(data[c.name] for c in columns))]
    return Sample(
        columns=columns,
        rows=[[_clip(v) for v in row] for row in rows],
        truncated=truncated,
    )


def run_read_only(
    connector: Connector, dialect: str, sql: str, max_rows: int = 20
) -> Sample:
    """Run `sql` if it only reads, returning at most `max_rows` rows.

    Queries are wrapped in an outer LIMIT so the backend doesn't compute rows
    nobody reads. Some valid queries can't be wrapped (e.g. MySQL rejects a
    derived table with duplicate column names), so those run as written and
    are truncated while reading.
    """
    statement = check_read_only(sql, dialect)
    sql = sql.strip().rstrip(";")
    if isinstance(statement, exp.Query):
        # Newlines keep a trailing `-- comment` from swallowing the closing paren.
        wrapped = f"SELECT * FROM (\n{sql}\n) AS _sample LIMIT {max_rows + 1}"
        try:
            return _run(connector, wrapped, max_rows)
        except CLIENT_ERRORS:
            pass
    return _run(connector, sql, max_rows)
