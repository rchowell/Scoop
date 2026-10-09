from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from api.connector.base import Connector, ConnectorError, ConnectorFactory
from api.connector.duckdb import DuckDBConnectorFactory
from api.connector.mysql import MySQLConnectorFactory
from api.connector.postgres import PostgresConnectorFactory
from api.connector.sqlite import SqliteConnectorFactory

FACTORIES: dict[str, ConnectorFactory] = {
    f.kind(): f
    for f in (
        SqliteConnectorFactory(),
        DuckDBConnectorFactory(),
        PostgresConnectorFactory(),
        MySQLConnectorFactory(),
    )
}


def get_factory(kind: str) -> ConnectorFactory:
    try:
        return FACTORIES[kind]
    except KeyError:
        raise ConnectorError(f"unknown connector kind: {kind}") from None


def create_connector(kind: str, options: Mapping[str, Any]) -> Connector:
    return get_factory(kind).create(options)
