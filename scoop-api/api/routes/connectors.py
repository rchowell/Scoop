import json
import sqlite3
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response

from api.connector import (
    Connector,
    InvalidOptionsError,
    TableNotFoundError,
    get_factory,
)
from api.connector_cache import ConnectorCacheDep
from api.db import Db
from api.problem import Problem
from api.query import CLIENT_ERRORS, collect
from models import Column as ColumnModel
from models import Connector as ConnectorModel
from models import (
    ConnectorKind,
    ConnectorPage,
    CreateConnector,
    ExecuteRequest,
    ExecuteResult,
    Pagination,
    Table,
    TableList,
    UpdateConnector,
)

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])

MAX_PAGE_SIZE = 1000


def _model(row: sqlite3.Row) -> ConnectorModel:
    return ConnectorModel(**{**dict(row), "options": json.loads(row["options"])})


def _load(db: Db, id: UUID) -> ConnectorModel:
    row = db.execute("SELECT * FROM connectors WHERE id = ?", (str(id),)).fetchone()
    if row is None:
        raise Problem(404, "Not Found", f"connector not found: {id}")
    return _model(row)


def _validate(kind: ConnectorKind, options: dict[str, Any]) -> None:
    """Reject options the factory can't instantiate; the raw options are what gets stored."""
    try:
        get_factory(kind.value).validate(options)
    except InvalidOptionsError as e:
        raise Problem(422, "Invalid Options", "; ".join(e.problems)) from e


def open_connector(id: UUID, db: Db, cache: ConnectorCacheDep) -> Connector:
    """Get the stored connector's live, cached instance."""
    try:
        connector = cache.get(id, db)
    except CLIENT_ERRORS as e:
        raise Problem(400, "Connector Unavailable", str(e)) from e
    if connector is None:
        raise Problem(404, "Not Found", f"connector not found: {id}")
    return connector


OpenConnector = Annotated[Connector, Depends(open_connector)]


@router.get("")
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


@router.post("", status_code=201)
def post_connector(db: Db, body: CreateConnector) -> ConnectorModel:
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
            str(model.id.root),
            model.name,
            model.kind.value,
            json.dumps(model.options),
            model.created_at.isoformat(),
        ),
    )
    return model


@router.get("/{id}")
def get_connector(db: Db, id: UUID) -> ConnectorModel:
    return _load(db, id)


@router.patch("/{id}")
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


@router.delete("/{id}", status_code=204)
def delete_connector(db: Db, cache: ConnectorCacheDep, id: UUID) -> Response:
    if db.execute("DELETE FROM connectors WHERE id = ?", (str(id),)).rowcount == 0:
        raise Problem(404, "Not Found", f"connector not found: {id}")
    cache.evict(id)
    return Response(status_code=204)


@router.get("/{id}/tables")
def list_tables(
    connector: OpenConnector,
    namespace: Annotated[list[str] | None, Query()] = None,
) -> TableList:
    paths = connector.list_tables(tuple(namespace or ()))
    return TableList(tables=[list(p) for p in paths])


@router.get("/{id}/table")
def get_table(
    connector: OpenConnector, path: Annotated[list[str], Query(min_length=1)]
) -> Table:
    try:
        table = connector.get_table(tuple(path))
    except TableNotFoundError as e:
        raise Problem(404, "Not Found", str(e)) from e
    return Table(
        path=list(table.path),
        kind=table.kind,
        columns=[ColumnModel(**vars(c)) for c in table.columns],
    )


@router.post("/{id}/execute")
def execute(connector: OpenConnector, body: ExecuteRequest) -> ExecuteResult:
    max_rows = body.max_rows or 1000
    try:
        with connector.execute(
            body.query, body.params, page_size=min(max_rows, MAX_PAGE_SIZE)
        ) as result:
            columns = result.columns
            data, truncated = collect(result, max_rows)
    except CLIENT_ERRORS as e:
        raise Problem(400, "Query Failed", str(e)) from e
    return ExecuteResult(
        columns=[ColumnModel(**vars(c)) for c in columns],
        data=data,
        truncated=truncated,
    )
