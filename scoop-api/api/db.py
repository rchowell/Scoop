import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends

from api.config import Settings, get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS connectors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    options TEXT NOT NULL CHECK (json_valid(options)),
    created_at TEXT NOT NULL
);
"""

# Data migrations in order; PRAGMA user_version counts how many have been applied.
MIGRATIONS = [
    # Every kind names its database option `database` (was sqlite `path`, postgres `dbname`).
    """
    UPDATE connectors
    SET options = json_set(json_remove(options, '$.path'), '$.database', json_extract(options, '$.path'))
    WHERE kind = 'sqlite' AND json_type(options, '$.path') IS NOT NULL;
    UPDATE connectors
    SET options = json_set(json_remove(options, '$.dbname'), '$.database', json_extract(options, '$.dbname'))
    WHERE kind = 'postgres' AND json_type(options, '$.dbname') IS NOT NULL;
    """,
]


def connect(db_path: str) -> sqlite3.Connection:
    # FastAPI may run a sync dependency and its endpoint on different threadpool
    # workers; each request gets its own connection, so this is safe.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema if needed and apply any pending migrations."""
    conn.executescript(SCHEMA)
    (version,) = conn.execute("PRAGMA user_version").fetchone()
    for number, script in enumerate(MIGRATIONS[version:], version + 1):
        conn.executescript(f"BEGIN; {script} PRAGMA user_version = {number}; COMMIT;")


def get_db(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[sqlite3.Connection]:
    """Yield a per-request connection; commit on success, roll back on error."""
    conn = connect(settings.db_path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]
