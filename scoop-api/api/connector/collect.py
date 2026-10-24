"""Reading a Result into JSON-ready columnar rows."""

import base64
from typing import Any

from api.connector.connector import Result


def jsonable(value: Any) -> Any:
    # Pydantic serializes bytes as UTF-8, which fails on arbitrary BLOBs.
    if isinstance(value, bytes | bytearray | memoryview):
        return base64.b64encode(value).decode()
    return value


def collect(result: Result, max_rows: int) -> tuple[dict[str, list[Any]], bool]:
    """Read up to `max_rows` JSON-ready rows from `result` in columnar form; also
    return whether more remained."""
    data: dict[str, list[Any]] = {c.name: [] for c in result.columns}
    remaining = max_rows
    for page in result:
        take = min(len(page), remaining)
        for name, values in page.data.items():
            data[name].extend(jsonable(v) for v in values[:take])
        remaining -= take
        if take < len(page):
            return data, True
        if remaining == 0:
            return data, next(result, None) is not None
    return data, False
