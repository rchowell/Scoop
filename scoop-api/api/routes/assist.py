from collections.abc import Iterator
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.assist.agent import AssistEvent, QueryAgentDep
from api.db import Db
from api.routes.connectors import OpenConnector, _load
from models import GenerateRequest

router = APIRouter(prefix="/v1/connectors", tags=["assist"])


def _sse(events: Iterator[AssistEvent]) -> Iterator[str]:
    for event in events:
        yield f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


@router.post("/{id}/generate")
def generate(
    id: UUID,
    body: GenerateRequest,
    db: Db,
    connector: OpenConnector,
    agent: QueryAgentDep,
) -> StreamingResponse:
    dialect = _load(db, id).kind.value
    events = agent.generate(connector, dialect, body.prompt, body.context)
    return StreamingResponse(
        _sse(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
