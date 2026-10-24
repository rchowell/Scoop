import json
import sqlite3
import tomllib
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from api.assist.agent import AssistEvent, QueryAgentDep
from api.config import get_settings
from api.connector import (
    CLIENT_ERRORS,
    CONNECTORS,
    Column,
    Connector,
    InvalidOptionsError,
    TableNotFoundError,
    collect,
    connector_class,
    validate_options,
)
from api.connector.cache import ConnectorCache, ConnectorCacheDep
from api.db import Db
from api.models import Column as ColumnModel
from api.models import Connector as ConnectorModel
from api.models import (
    ConnectorKind,
    ConnectorKindInfo,
    ConnectorKindList,
    ConnectorOption,
    ConnectorPage,
    CreateConnector,
    ExecuteRequest,
    ExecuteResult,
    GenerateRequest,
    Health,
    HealthStatus,
    OptionType,
    Pagination,
    Table,
    TableList,
    UpdateConnector,
)
from api.problem import Problem, problem_handler

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


# ============================================================================
# Helpers and dependencies
# ============================================================================

# Rows fetched from the backend per round trip.
MAX_PAGE_SIZE = 1000
# ExecuteRequest's default, for a client that sends max_rows: null.
DEFAULT_MAX_ROWS: int = ExecuteRequest.model_fields["max_rows"].default


def _not_found(id: UUID) -> Problem:
    return Problem(404, "Not Found", f"connector not found: {id}")


def _model(row: sqlite3.Row) -> ConnectorModel:
    return ConnectorModel(**{**dict(row), "options": json.loads(row["options"])})


def _column(column: Column) -> ColumnModel:
    return ColumnModel(**vars(column))


def _load(db: Db, id: UUID) -> ConnectorModel:
    row = db.execute("SELECT * FROM connectors WHERE id = ?", (str(id),)).fetchone()
    if row is None:
        raise _not_found(id)
    return _model(row)


def _validate(kind: ConnectorKind, options: dict[str, Any]) -> None:
    """Reject options the connector can't be created from; the raw options are what gets stored."""
    try:
        validate_options(connector_class(kind.value).options(), options)
    except InvalidOptionsError as e:
        raise Problem(422, "Invalid Options", "; ".join(e.problems)) from e


def open_connector(id: UUID, db: Db, cache: ConnectorCacheDep) -> Connector:
    """Get the stored connector's live, cached instance."""
    try:
        connector = cache.get(id, db)
    except CLIENT_ERRORS as e:
        raise Problem(400, "Connector Unavailable", str(e)) from e
    if connector is None:
        raise _not_found(id)
    return connector


OpenConnector = Annotated[Connector, Depends(open_connector)]


_OPTION_TYPES = {
    str: OptionType.STRING,
    int: OptionType.INTEGER,
    bool: OptionType.BOOLEAN,
}


def _info(connector: type[Connector]) -> ConnectorKindInfo:
    return ConnectorKindInfo(
        kind=ConnectorKind(connector.kind()),
        name=connector.display_name(),
        options=[
            ConnectorOption(
                name=key,
                type=_OPTION_TYPES[option.type],
                description=option.description,
                required=option.required,
                default=option.default,
                secret=option.secret,
            )
            for key, option in connector.options().items()
        ],
    )


def _sse(events: Iterator[AssistEvent]) -> Iterator[str]:
    for event in events:
        yield f"event: {event.type}\ndata: {event.model_dump_json(by_alias=True)}\n\n"


# ============================================================================
# Routes, in scoop.tsp order
# ============================================================================


@app.get("/v1/health")
def get_health(db: Db) -> Health:
    db.execute("SELECT 1")
    return Health(status=HealthStatus.OK, version=VERSION)


@app.get("/v1/connector-kinds")
def list_connector_kinds() -> ConnectorKindList:
    return ConnectorKindList(kinds=[_info(c) for c in CONNECTORS.values()])


@app.get("/v1/connectors")
def list_connectors(
    db: Db,
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ConnectorPage:
    rows = db.execute(
        "SELECT * FROM connectors ORDER BY created_at, id LIMIT ? OFFSET ?",
        (page_size + 1, (page - 1) * page_size),
    ).fetchall()
    has_next = len(rows) > page_size
    items = [_model(r) for r in rows[:page_size]]
    url = request.url
    return ConnectorPage(
        items=items,
        pagination=Pagination(
            page=page,
            page_size=len(items),
            next=str(url.include_query_params(page=page + 1)) if has_next else None,
            prev=str(url.include_query_params(page=page - 1)) if page > 1 else None,
        ),
    )


@app.post("/v1/connectors", status_code=201)
def create_connector(db: Db, body: CreateConnector) -> ConnectorModel:
    _validate(body.kind, body.options)
    model = ConnectorModel(
        id=uuid4(),
        name=body.name,
        kind=body.kind,
        options=body.options,
        created_at=datetime.now(UTC),
    )
    db.execute(
        "INSERT INTO connectors (id, name, kind, options, created_at) VALUES (?, ?, ?, ?, ?)",
        (
            str(model.id),
            model.name,
            model.kind.value,
            json.dumps(model.options),
            model.created_at.isoformat(),
        ),
    )
    return model


@app.get("/v1/connectors/{id}")
def get_connector(db: Db, id: UUID) -> ConnectorModel:
    return _load(db, id)


@app.patch("/v1/connectors/{id}")
def update_connector(
    db: Db, cache: ConnectorCacheDep, id: UUID, body: UpdateConnector
) -> ConnectorModel:
    model = _load(db, id)
    _validate(model.kind, body.options)
    db.execute(
        "UPDATE connectors SET name = ?, options = ? WHERE id = ?",
        (body.name, json.dumps(body.options), str(id)),
    )
    cache.evict(id)
    return model.model_copy(update={"name": body.name, "options": body.options})


@app.delete("/v1/connectors/{id}", status_code=204)
def delete_connector(db: Db, cache: ConnectorCacheDep, id: UUID) -> Response:
    if db.execute("DELETE FROM connectors WHERE id = ?", (str(id),)).rowcount == 0:
        raise _not_found(id)
    cache.evict(id)
    return Response(status_code=204)


@app.get("/v1/connectors/{id}/tables")
def list_connector_tables(
    connector: OpenConnector,
    namespace: Annotated[list[str] | None, Query()] = None,
) -> TableList:
    paths = connector.list_tables(tuple(namespace or ()))
    return TableList(tables=[list(p) for p in paths])


@app.get("/v1/connectors/{id}/table")
def get_connector_table(
    connector: OpenConnector, path: Annotated[list[str], Query(min_length=1)]
) -> Table:
    try:
        table = connector.get_table(tuple(path))
    except TableNotFoundError as e:
        raise Problem(404, "Not Found", str(e)) from e
    return Table(
        path=list(table.path),
        kind=table.kind,
        columns=[_column(c) for c in table.columns],
    )


@app.post("/v1/connectors/{id}/execute")
def execute_connector_query(
    connector: OpenConnector, body: ExecuteRequest
) -> ExecuteResult:
    max_rows = body.max_rows or DEFAULT_MAX_ROWS
    try:
        with connector.execute(
            body.query, page_size=min(max_rows, MAX_PAGE_SIZE)
        ) as result:
            columns = result.columns
            data, truncated = collect(result, max_rows)
    except CLIENT_ERRORS as e:
        raise Problem(400, "Query Failed", str(e)) from e
    return ExecuteResult(
        columns=[_column(c) for c in columns], data=data, truncated=truncated
    )


@app.post("/v1/connectors/{id}/generate")
def generate_connector_query(
    body: GenerateRequest, connector: OpenConnector, agent: QueryAgentDep
) -> StreamingResponse:
    events = agent.generate(connector, body.prompt, body.context)
    return StreamingResponse(
        _sse(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
