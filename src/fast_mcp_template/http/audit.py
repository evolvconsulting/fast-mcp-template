"""Audit middleware: one structured line per request and per tool call.

- `AuthAuditMiddleware`: one `mcp_auth` line per MCP request, an
  `http_access` line for everything else (`/health*` at DEBUG so ALB
  probes do not flood the log), optional deprecation headers for a
  retiring credential, and the per-IP `FailureAlarm`.
- `FailureAlarm`: ALERT-only counter of 401s per client. It fires once
  per burst and never latches or blocks (a latch lets one attacker lock
  out a whole office NAT).
- `ToolCallAuditMiddleware`: a fastmcp `Middleware`, registered on the
  server (not the HTTP app), one `mcp_tool_call` line per tool call.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict, deque
from datetime import UTC
from email.utils import format_datetime

import mcp_types as mt
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware
from fastmcp.server.middleware.middleware import CallNext, MiddlewareContext
from fastmcp.tools.base import ToolResult
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fast_mcp_template.auth.claims import auth_path_of, claims_of
from fast_mcp_template.auth.types import (
    CLAIM_AUTH_PATH,
    CLAIM_KEY_FP,
    CLAIM_USER_ID,
)
from fast_mcp_template.config import Settings
from fast_mcp_template.http.log import clean_log_text, present
from fast_mcp_template.http.net import (
    client_ip_from_scope,
    current_request_id,
    rate_key_for_ip,
)

logger = logging.getLogger(__name__)


def _is_health(path: str) -> bool:
    return path == "/health" or path.startswith("/health/")


class FailureAlarm:
    """In-process, alert-only counter of 401s per client.

    IPv6 clients are counted per /64. Bounded twice: at most `max_ips`
    clients are tracked (the least recently seen is dropped) and each
    keeps at most `threshold` timestamps, so a record is O(1) and an
    unauthenticated flood from one address costs constant memory.
    """

    def __init__(
        self,
        *,
        threshold: int = 20,
        window_s: float = 300.0,
        max_ips: int = 10_000,
    ) -> None:
        """Alarm when `threshold` failures land inside `window_s`."""
        self.threshold = threshold
        self.window_s = window_s
        self.max_ips = max_ips
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._armed: set[str] = set()  # fired for the current burst

    def record(self, ip: str | None) -> bool:
        """Record one failure; True exactly on the crossing."""
        try:
            key = rate_key_for_ip(ip) or "unknown"
        except ValueError:
            key = "unknown"
        now = time.monotonic()
        hits = self._hits.get(key)
        if hits is None:
            hits = self._hits[key] = deque(maxlen=self.threshold)
            while len(self._hits) > self.max_ips:
                evicted, _ = self._hits.popitem(last=False)
                self._armed.discard(evicted)
        else:
            self._hits.move_to_end(key)
        hits.append(now)
        burst = len(hits) == self.threshold and now - hits[0] < self.window_s
        if not burst:
            self._armed.discard(key)
            return False
        if key in self._armed:
            return False
        self._armed.add(key)
        logger.warning(
            "repeated failed authentication from one client",
            extra={
                "event": "auth_failure_spray",
                "client_ip": ip,
                "threshold": self.threshold,
                "window_seconds": self.window_s,
            },
        )
        return True


class AuthAuditMiddleware:
    """One log line per HTTP request; the MCP path gets `mcp_auth`.

    Every other request (404 probes, 307s, 405s) gets an `http_access`
    line at INFO, and `/health*` the same line at DEBUG. Only the MCP
    path gets deprecation headers.
    """

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        """Wrap `app`; `settings.mcp_path` gets the audit line."""
        self.app = app
        self.settings = settings
        self.alarm = FailureAlarm()

    def _deprecation_headers(self) -> list[tuple[str, str]]:
        s = self.settings
        out: list[tuple[str, str]] = []
        if s.legacy_deprecated_at is not None:
            out.append(("Deprecation", f"@{int(s.legacy_deprecated_at.timestamp())}"))
        if s.legacy_sunset_at is not None:
            out.append(
                (
                    "Sunset",
                    format_datetime(s.legacy_sunset_at.astimezone(UTC), usegmt=True),
                )
            )
        if out and s.manage_mcp_url:
            out.append(
                ("Link", f'<{s.manage_mcp_url}>; rel="deprecation"; type="text/html"')
            )
        return out

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Log every http request; audit and alarm on the MCP path."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_mcp = scope.get("path") == self.settings.mcp_path
        status = 500  # what the caller sees if the app raises first
        response_started = False
        cancelled = False
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                # This layer wraps the whole app, so the claims exist
                # only once the auth layer inside has run: read them at
                # response time, not before.
                if is_mcp and auth_path_of(scope) == "legacy":
                    headers = MutableHeaders(scope=message)
                    for name, value in self._deprecation_headers():
                        headers.append(name, value)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            if cancelled and not response_started:
                status = 499  # the client went away: not a server error
            auth_path = auth_path_of(scope)
            client_ip = client_ip_from_scope(scope, self.settings.trusted_proxy_hops)
            method = clean_log_text(scope.get("method", ""), 16)
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            if is_mcp:
                claims = claims_of(scope)
                logger.info(
                    "mcp_auth",
                    extra=present(
                        event="mcp_auth",
                        auth_path=auth_path,
                        client_ip=client_ip,
                        user_id=claims.get(CLAIM_USER_ID),
                        key_fp=claims.get(CLAIM_KEY_FP),
                        status=status,
                        method=method,
                        path=scope["path"],
                        duration_ms=duration_ms,
                        request_id=current_request_id(),
                    ),
                )
                if status == 401:
                    self.alarm.record(client_ip)
            else:
                path = clean_log_text(scope.get("path", ""), 200)
                logger.log(
                    logging.DEBUG if _is_health(path) else logging.INFO,
                    "http_access",
                    extra=present(
                        event="http_access",
                        client_ip=client_ip,
                        status=status,
                        method=method,
                        path=path,
                        duration_ms=duration_ms,
                        request_id=current_request_id(),
                    ),
                )


class ToolCallAuditMiddleware(Middleware):
    """One `mcp_tool_call` line per tool call: who, which, outcome."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Log the tool name, the caller and the outcome."""
        outcome = "error"
        try:
            result = await call_next(context)
            outcome = "ok"
            return result
        finally:
            token = get_access_token()
            claims = (token.claims if token is not None else None) or {}
            auth_path = claims.get(CLAIM_AUTH_PATH)
            logger.info(
                "mcp_tool_call",
                extra=present(
                    event="mcp_tool_call",
                    tool=clean_log_text(context.message.name),
                    auth_path=auth_path
                    if auth_path in ("legacy", "platform")
                    else "none",
                    user_id=claims.get(CLAIM_USER_ID),
                    key_fp=claims.get(CLAIM_KEY_FP),
                    outcome=outcome,
                    request_id=current_request_id(),
                ),
            )
