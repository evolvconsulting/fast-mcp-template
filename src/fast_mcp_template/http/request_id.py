"""Whole-app request-id middleware.

Reuses a valid inbound `X-Request-ID` (UUID v4, canonical lowercase) or
mints one, stores it in `scope["state"]["request_id"]` and
`request_id_var`, and echoes it on every response. Any other scope
type, `lifespan` included, passes through unchanged.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fast_mcp_template.http.net import (
    REQUEST_ID_HEADER,
    STATE_REQUEST_ID,
    new_request_id,
    request_id_var,
    valid_request_id,
)


class RequestIdMiddleware:
    """Pure ASGI middleware that must wrap the WHOLE app.

    fastmcp runs its auth outside `middleware=`, so only a wrapper
    around the finished app sees a 401 and can stamp it.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap `app`."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Assign a request id to HTTP requests; pass others through."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = next(
            (
                bytes(v).decode("latin-1")
                for k, v in scope.get("headers") or []
                if bytes(k).lower() == REQUEST_ID_HEADER.encode()
            ),
            None,
        )
        request_id = (
            inbound if inbound and valid_request_id(inbound) else new_request_id()
        )
        scope.setdefault("state", {})[STATE_REQUEST_ID] = request_id
        token = request_id_var.set(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Compare lowercased: an inner app may use any case.
                if not any(
                    bytes(k).lower() == REQUEST_ID_HEADER.encode()
                    for k, _ in message.get("headers") or []
                ):
                    MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)
