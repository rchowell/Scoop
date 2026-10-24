from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from api.connector.connector import Connector, ConnectorError
from api.connector.duckdb import DuckDBConnector
from api.connector.mysql import MySQLConnector
from api.connector.options import validate_options
from api.connector.postgres import PostgresConnector
from api.connector.sqlite import SQLiteConnector

CONNECTORS: dict[str, type[Connector]] = {
    c.kind(): c
    for c in (SQLiteConnector, DuckDBConnector, PostgresConnector, MySQLConnector)
}

# Errors a backend can raise from bad input (SQL, params, paths) rather than a server fault.
CLIENT_ERRORS: tuple[type[Exception], ...] = (
    ConnectorError,
    ValueError,
    *(e for c in CONNECTORS.values() for e in c.errors()),
)


def connector_class(kind: str) -> type[Connector]:
    try:
        return CONNECTORS[kind]
    except KeyError:
        raise ConnectorError(f"unknown connector kind: {kind}") from None


def create_connector(kind: str, options: Mapping[str, Any]) -> Connector:
    """Validate `options` for `kind` and connect."""
    cls = connector_class(kind)
    return cls(**validate_options(cls.options(), options))
