import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    db_path: str = "scoop.sqlite3"
    # Comma-separated in SCOOP_CORS_ORIGINS; defaults to the scoop-app dev server.
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    # The query assistant is disabled (503) without a key.
    anthropic_api_key: str | None = None
    assist_model: str = "claude-sonnet-5-5"


@lru_cache
def get_settings() -> Settings:
    origins = os.environ.get("SCOOP_CORS_ORIGINS")
    return Settings(
        db_path=os.environ.get("SCOOP_DB_PATH", Settings.db_path),
        cors_origins=(
            tuple(o.strip() for o in origins.split(",") if o.strip())
            if origins is not None
            else Settings.cors_origins
        ),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        assist_model=os.environ.get("SCOOP_ASSIST_MODEL", Settings.assist_model),
    )
