"""Run small samples of a query on behalf of the query assistant."""

from dataclasses import dataclass
from typing import Any

from api.connector import Column, Connector
from api.query import collect
from models import Query

MAX_CELL_CHARS = 200


@dataclass(frozen=True)
class Sample:
    columns: list[Column]
    rows: list[list[Any]]
    truncated: bool


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + "…"
    return value


def run_sample(connector: Connector, query: Query, max_rows: int = 20) -> Sample:
    """Run `query`, returning at most `max_rows` rows.

    The query's LIMIT is lowered to one past `max_rows` so the backend doesn't
    compute rows nobody reads, while still showing whether more remained.
    """
    cap = max_rows + 1
    limit = cap if query.limit is None else min(query.limit, cap)
    capped = query.model_copy(update={"limit": limit})
    with connector.execute(capped, page_size=max_rows) as result:
        columns = result.columns
        data, truncated = collect(result, max_rows)
    rows = [list(r) for r in zip(*(data[c.name] for c in columns))]
    return Sample(
        columns=columns,
        rows=[[_clip(v) for v in row] for row in rows],
        truncated=truncated,
    )
