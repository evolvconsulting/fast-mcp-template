"""RFC 9457 problem responses and the app's error handlers.

Split out of the health module on purpose: the body-size and rate
limit middleware both build their refusals with `problem_response`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from fast_mcp_template.http.net import current_request_id, new_request_id

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


def problem_response(
    status: int,
    *,
    title: str,
    type_: str,
    detail: str,
    instance: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Return an RFC 9457 body with all seven required fields.

    The id in the body is also the `X-Request-ID` header, so the two
    always agree even where no `RequestIdMiddleware` wraps the response
    (a layer tested on its own).
    """
    request_id = current_request_id() or new_request_id()
    body = {
        "type": type_,
        "title": title,
        "status": status,
        "detail": detail,
        "instance": instance,
        "request_id": request_id,
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }
    return JSONResponse(
        body,
        status_code=status,
        media_type=PROBLEM_JSON,
        headers={**(headers or {}), "X-Request-ID": request_id},
    )


def register_error_handlers(app: Starlette) -> None:
    """Answer 404, 405 and unhandled errors with problem+json.

    The 500 detail is generic; the traceback goes to the log only.
    """

    async def not_found(request: Request, exc: Exception) -> Response:
        return problem_response(
            404,
            title="Resource Not Found",
            type_="/problems/resource-not-found",
            detail="The requested resource was not found",
            instance=request.url.path,
        )

    async def method_not_allowed(request: Request, exc: Exception) -> Response:
        allow = getattr(exc, "headers", None) or {}
        return problem_response(
            405,
            title="Method Not Allowed",
            type_="/problems/method-not-allowed",
            detail=f"{request.method} is not supported for this endpoint",
            instance=request.url.path,
            headers={k: v for k, v in allow.items() if k.lower() == "allow"},
        )

    async def unhandled(request: Request, exc: Exception) -> Response:
        logger.error(
            "unhandled error",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={
                "event": "unhandled_error",
                "path": request.url.path,
                "error_type": type(exc).__name__,
            },
        )
        return problem_response(
            500,
            title="Internal Server Error",
            type_="/problems/internal-error",
            detail="An unexpected error occurred",
            instance=request.url.path,
        )

    handlers: dict[Any, Any] = {
        404: not_found,
        405: method_not_allowed,
        Exception: unhandled,
    }
    for key, handler in handlers.items():
        app.add_exception_handler(key, handler)
