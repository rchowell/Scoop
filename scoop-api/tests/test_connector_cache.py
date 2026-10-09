import json
import sqlite3
import uuid

import pytest

from api.connector import ConnectorError
from api.connector_cache import ConnectorCache
from api.db import SCHEMA, connect


@pytest.fixture
def db(tmp_path):
    conn = connect(str(tmp_path / "app.sqlite3"))
    conn.executescript(SCHEMA)
    yield conn
    conn.close()


@pytest.fixture
def cache():
    cache = ConnectorCache()
    yield cache
    cache.close()


def _insert(db, kind="sqlite", options=None) -> uuid.UUID:
    id = uuid.uuid4()
    db.execute(
        "INSERT INTO connectors (id, name, kind, options, created_at) VALUES (?, ?, ?, ?, ?)",
        (str(id), "c", kind, json.dumps(options or {}), "2026-01-01T00:00:00+00:00"),
    )
    return id


def _closed(connector) -> bool:
    try:
        connector.execute("SELECT 1").close()
    except sqlite3.ProgrammingError:
        return True
    return False


def test_miss_then_hit(db, cache, tmp_path):
    id = _insert(db, options={"path": str(tmp_path / "x.db")})
    first = cache.get(id, db)
    assert first is not None
    assert cache.get(id, db) is first


def test_unknown_id(db, cache):
    assert cache.get(uuid.uuid4(), db) is None


def test_factory_error_not_cached(db, cache):
    id = _insert(db, kind="oracle")
    with pytest.raises(ConnectorError):
        cache.get(id, db)
    assert id not in cache._connectors


def test_evict_closes_and_rebuilds(db, cache, tmp_path):
    id = _insert(db, options={"path": str(tmp_path / "x.db")})
    first = cache.get(id, db)
    cache.evict(id)
    assert _closed(first)
    second = cache.get(id, db)
    assert second is not first and not _closed(second)
    cache.evict(uuid.uuid4())  # evicting an uncached id is a no-op


def test_close_closes_all(db, cache, tmp_path):
    ids = [_insert(db, options={"path": str(tmp_path / f"{i}.db")}) for i in range(2)]
    connectors = [cache.get(id, db) for id in ids]
    cache.close()
    assert all(_closed(c) for c in connectors)
    assert cache._connectors == {}
