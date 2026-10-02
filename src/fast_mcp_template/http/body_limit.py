"""413 for a request body over the configured ceiling.

fastmcp 4.0.3 enforces no body limit of its own.
"""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fast_mcp_template.config import Settings
from fast_mcp_template.http.errors import problem_response


class _BodyTooLargeError(Exception):
    """Raised in the wrapped `receive` once the limit is passed."""


def _header(scope: Scope, name: str) -> str | None:
    """Return the first request header `name` (lower case), or None."""
    want = name.encode()
    for k, v in scope.get("headers") or []:
        if bytes(k).lower() == want:
            return bytes(v).decode("latin-1")
    return None


class BodySizeLimitMiddleware:
    """Refuse a body over `max_request_body_bytes` with a 413."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        """Wrap `app`."""
        self.app = app
        self.limit = settings.max_request_body_bytes

    def _too_large(self, scope: Scope) -> JSONResponse:
        return problem_response(
            413,
            title="Payload Too Large",
            type_="/problems/payload-too-large",
            detail=f"Request body exceeds {self.limit} bytes",
            instance=scope["path"],
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Refuse an oversized body as early as possible."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _header(scope, "content-length")
        if (
            declared is not None
            and declared.strip().isdigit()
            and int(declared) > self.limit
        ):
            await self._too_large(scope)(scope, receive, send)
            return

        total = 0
        overflowed = False
        started = False

        async def limited_receive() -> Message:
            nonlocal total, overflowed
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.limit:
                    overflowed = True
                    raise _BodyTooLargeError
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if overflowed and not started:
                return  # the app's own answer loses to our 413
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not overflowed:
                raise
        if overflowed and not started:
            await self._too_large(scope)(scope, receive, send)
