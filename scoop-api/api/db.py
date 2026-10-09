import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends

from api.config import Settings, get_settings


def connect(db_path: str) -> sqlite3.Connection:
    # FastAPI may run a sync dependency and its endpoint on different threadpool
    # workers; each request gets its own connection, so this is safe.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS connectors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    options TEXT NOT NULL CHECK (json_valid(options)),
    created_at TEXT NOT NULL
);
"""


def get_db(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[sqlite3.Connection]:
    """Yield a per-request connection; commit on success, roll back on error."""
    conn = connect(settings.db_path)
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]
