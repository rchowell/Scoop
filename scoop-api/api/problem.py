"""RFC 9457 Problem Details errors."""

from fastapi import Request
from fastapi.responses import JSONResponse

from models import ProblemDetail


class Problem(Exception):
    def __init__(self, status: int, title: str, detail: str | None = None) -> None:
        super().__init__(detail or title)
        self.status = status
        self.title = title
        self.detail = detail


def problem_handler(request: Request, exc: Problem) -> JSONResponse:
    body = ProblemDetail(
        type="about:blank",
        title=exc.title,
        status=exc.status,
        detail=exc.detail,
        instance=request.url.path,
    )
    return JSONResponse(
        body.model_dump(mode="json", exclude_none=True),
        status_code=exc.status,
        media_type="application/problem+json",
    )
