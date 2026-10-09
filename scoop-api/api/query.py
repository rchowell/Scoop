"""Helpers shared by everything that runs SQL against a connector."""

import base64
import sqlite3
from typing import Any

import duckdb
import psycopg
import pymysql

from api.connector import ConnectorError, Result

# Errors a backend can raise from bad input (SQL, params, paths) rather than a server fault.
CLIENT_ERRORS = (
    ConnectorError,
    ValueError,
    sqlite3.Error,
    duckdb.Error,
    psycopg.Error,
    pymysql.Error,
)


def jsonable(value: Any) -> Any:
    # Pydantic serializes bytes as UTF-8, which fails on arbitrary BLOBs.
    if isinstance(value, bytes | bytearray | memoryview):
        return base64.b64encode(value).decode()
    return value


def collect(result: Result, max_rows: int) -> tuple[dict[str, list[Any]], bool]:
    """Read up to `max_rows` rows from `result` in columnar form; also return whether more remained."""
    data: dict[str, list[Any]] = {c.name: [] for c in result.columns}
    remaining = max_rows
    for page in result:
        take = min(len(page), remaining)
        for name, values in page.data.items():
            data[name].extend(jsonable(v) for v in values[:take])
        remaining -= take
        if take < len(page):
            return data, True
        if remaining == 0:
            return data, next(result, None) is not None
    return data, False
