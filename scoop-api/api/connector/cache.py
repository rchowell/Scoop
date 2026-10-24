import json
import sqlite3
import threading
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from api.connector import Connector, create_connector


class ConnectorCache:
    """Live Connector instances keyed by connector id, created on first use."""

    def __init__(self) -> None:
        self._connectors: dict[UUID, Connector] = {}
        # Guards the dict only; never held while connecting to a backend.
        self._lock = threading.Lock()

    def get(self, id: UUID, db: sqlite3.Connection) -> Connector | None:
        """Return the cached connector, or build it from its stored row; None if no such connector."""
        with self._lock:
            connector = self._connectors.get(id)
        if connector is not None:
            return connector
        row = db.execute(
            "SELECT kind, options FROM connectors WHERE id = ?", (str(id),)
        ).fetchone()
        if row is None:
            return None
        connector = create_connector(row["kind"], json.loads(row["options"]))
        with self._lock:
            winner = self._connectors.setdefault(id, connector)
        if winner is not connector:  # a concurrent miss cached one first
            connector.close()
        return winner

    def evict(self, id: UUID) -> None:
        with self._lock:
            connector = self._connectors.pop(id, None)
        if connector is not None:
            connector.close()

    def close(self) -> None:
        with self._lock:
            connectors = list(self._connectors.values())
            self._connectors.clear()
        for connector in connectors:
            connector.close()


def get_connector_cache(request: Request) -> ConnectorCache:
    return request.app.state.connector_cache


ConnectorCacheDep = Annotated[ConnectorCache, Depends(get_connector_cache)]
