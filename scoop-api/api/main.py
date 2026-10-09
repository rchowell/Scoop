import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.connector_cache import ConnectorCache
from api.db import Db
from api.problem import Problem, problem_handler
from api.routes import assist, connector_kinds, connectors
from models import Health, HealthStatus

with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
    VERSION: str = tomllib.load(f)["project"]["version"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.connector_cache = ConnectorCache()
    try:
        yield
    finally:
        app.state.connector_cache.close()


app = FastAPI(title="Scoop API", version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(Problem, problem_handler)
app.include_router(connectors.router)
app.include_router(connector_kinds.router)
app.include_router(assist.router)


@app.get("/")
def hello() -> dict[str, str]:
    return {"message": "Hello, World!"}


@app.get("/v1/health")
def health(db: Db) -> Health:
    db.execute("SELECT 1")
    return Health(status=HealthStatus.OK, version=VERSION)
