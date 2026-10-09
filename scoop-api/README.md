# scoop-api

FastAPI service backed by SQLite (`scoop.sqlite3`).

```bash
uv run fastapi dev api/main.py   # http://127.0.0.1:8000, docs at /docs
uv run pytest
```

Set `SCOOP_DB_PATH` to use a different database file. Endpoints take a
per-request connection via the `Db` dependency (`api/db.py`). Connector routes
get live, cached `Connector` instances via `ConnectorCacheDep`
(`api/connector_cache.py`); PATCH and DELETE evict the cached instance.
