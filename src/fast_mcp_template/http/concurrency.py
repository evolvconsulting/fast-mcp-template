"""In-flight request limiting and the slow-body guard.

`ConcurrencyLimitMiddleware` answers 503 once `limit` requests are in
flight, with per-client, per-credential and unverified-token caps so one
holder cannot take every slot, and `/health*` never counted or refused
(a saturated gateway keeps passing the load balancer's check and is not
replaced). `RequestBodyGuard` closes the socket on a response sent with
the request body unread and answers 408 to a stalled body: uvicorn has no
body-read deadline of its own.

Ported from fast-mcp-ado; the `R5`, `R6`... tags in comments are its review
rounds and the history of each rule.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from collections.abc import MutableMapping
from typing import Any, Final

from starlette.types import ASGIApp, Receive, Scope, Send

from fast_mcp_template.http.errors import problem_response
from fast_mcp_template.http.net import client_ip_from_scope, rate_key_for_ip

logger = logging.getLogger(__name__)

# S35: requests in flight, one count for the whole process (both listeners), and `/health*`
# is never counted or refused, so a saturated gateway keeps passing the ALB and ECS checks
# and is not replaced (M1). uvicorn's own `limit_concurrency` cannot be that limit: it answers
# 503 to a request, `/health` included, whenever open CONNECTIONS (idle ones too) reach it.
# It is set anyway, at CONNECTION_BACKSTOP_FACTOR times the in-flight limit, as a coarse
# backstop: below that, idle sockets never touch `/health`; above it, uvicorn sheds requests.
# It does NOT close or refuse connections, and uvicorn 0.51.0 has no header-read deadline
# (`timeout_keep_alive` arms only after a response), so an idle, partial-head or trickling
# connection stays open until the peer or the ALB closes it. That bound is the ALB's, plus
# the security group that lets only the ALB reach the task ports. The keep-alive exceeds the
# ALB idle timeout default (60 s) so the ALB, not uvicorn, closes idle connections: no 502s.
LIMIT_CONCURRENCY: Final = 100
CONNECTION_BACKSTOP_FACTOR: Final = 4
TIMEOUT_KEEP_ALIVE: Final = 75
SHUTDOWN_RESERVE_S: Final = 2  # of GRACEFUL_SHUTDOWN_TIMEOUT: lifespan cleanup and exit
H11_MAX_INCOMPLETE_EVENT_SIZE: Final = 16_384  # request line plus headers, bytes
# uvicorn has no body-read deadline and keeps a connection open while a request body is unread
# (H1, M1). A body not fully received this long after the request arrived is answered 408 and
# the socket closed, so a slow or trickled body holds an in-flight slot for at most this long.
# A deadline on the whole body, not per chunk: one byte every few seconds would reset a per-chunk
# timer for ever. JSON-RPC bodies are small; well under the ALB's 60 s idle timeout.
BODY_READ_DEADLINE_S: Final = 10.0
# L1: the deadline grows with the declared Content-Length so an honest upload of the largest
# legal body (1 MiB) over a slow link finishes: base + length / this minimum uplink rate,
# capped (the ALB idle timeout is 60 s). Chunked or unknown lengths keep the base.
BODY_MIN_RATE_BPS: Final = 64 * 1024
BODY_DEADLINE_CAP_S: Final = 60.0
# R5 L3: the plan's `max_request_body_bytes` (1 MiB). A declared length above it earns no time.
MAX_BODY_BYTES: Final = 1_048_576
# One client (authenticated user or, here, client IP) may hold at most this fraction of
# LIMIT_CONCURRENCY in flight, so a single holder cannot take every slot (M1).
PER_CLIENT_DIVISOR: Final = 4
# R5 M1: one credential may hold at most limit // 2 whatever the number of source IPs.
PER_CREDENTIAL_DIVISOR: Final = 2
# R5 L1: every token not yet verified, per IP, shares limit // 10 slots.
UNVERIFIED_DIVISOR: Final = 10
# R6 L1: all unverified tokens together, over every IP, hold at most limit // 2 slots.
UNVERIFIED_TOTAL_DIVISOR: Final = 2
MAX_VERIFIED: Final = 10_000  # credentials remembered as verified (16 hex each)
_SHUTDOWN_MARGIN_S: Final = (
    0.25  # kept back from the deadline for the cancel and the reply
)


# The only paths the limiter never counts or refuses. An exact set, not a prefix: a prefix
# would also exempt `/healthz` and `/health/../mcp`.
_EXEMPT_PATHS: Final = frozenset({"/health", "/health/live", "/health/ready"})
# Credential headers dropped from an exempt path's scope: health never authenticates, and the
# auth middleware would otherwise validate a bearer sent there, uncounted (R7 M1).
_CREDENTIAL_HEADERS: Final = frozenset({b"authorization"})
_SHED_LOG_INTERVAL_S: Final = 1.0


def _release(counts: dict[str, int], key: str) -> None:
    """Drop one from `counts[key]`, removing the entry at zero."""
    if counts[key] <= 1:
        del counts[key]
    else:
        counts[key] -= 1


class ConcurrencyLimitMiddleware:
    """Answer 503 once `limit` HTTP requests are in flight. `_EXEMPT_PATHS` are never counted.

    By design (R6 L2): the shared legacy key is ONE identity for every legacy user, so all of
    them together hold at most `limit // 2` slots, and any two valid credentials (the shared key
    plus one platform key, or two platform accounts) can between them use every slot. The legacy
    path has no per-user identity to split on; lane B's per-user token bucket bounds a platform
    user. Recorded in the DESIGN residuals.

    By design (R7 L3): the verified set is per process and starts empty, so after a deploy every
    user is unverified and shares the `limit // 2` unverified pool. A junk flood of CRC-valid
    tokens against a slow backend can briefly 503 valid users who have not yet been verified
    (already-verified users are unaffected). The per-IP validate-key budget bounds how fast the
    flood can hold slots. Runbook note for operators; no warm-up from the key cache.
    """

    def __init__(
        self,
        app: ASGIApp,
        limit: int,
        trusted_hops: int = 1,
        *,
        auth_enabled: bool = True,
    ) -> None:
        """Wrap `app`; the in-flight and shed counts start at zero.

        `auth_enabled` False (legacy + DANGEROUSLY_DISABLE_AUTH, non-production) means nothing
        ever verifies, so every client is counted by IP alone in the per-client bucket.
        """
        self.app = app
        self.limit = limit
        self.per_client = max(1, limit // PER_CLIENT_DIVISOR)
        # M1 (R5): one credential over ANY number of IPs; L1 (R5): all unverified tokens per IP.
        self.per_credential = max(1, limit // PER_CREDENTIAL_DIVISOR)
        self.per_unverified = max(1, limit // UNVERIFIED_DIVISOR)
        # R6 L1: the whole unverified class, over every IP, keeps verified callers half the slots.
        self.unverified_total = max(1, limit // UNVERIFIED_TOTAL_DIVISOR)
        self.auth_enabled = auth_enabled
        self._unverified_inflight = 0
        self.trusted_hops = trusted_hops
        self.inflight = 0
        self._by_client: dict[str, int] = {}
        self._by_credential: dict[str, int] = {}
        # Credentials whose request passed auth (`scope['user'].is_authenticated`), oldest first.
        self._verified: dict[str, None] = {}
        self.shed = 0
        self._last_shed_log: float | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Count the request, or refuse it with a problem+json 503 when the limit is hit."""
        path = scope.get("path", "")
        if scope["type"] == "websocket":
            # R8 M1: the gateway serves no websocket, but the auth middleware would still call the
            # backend for a bearer on the handshake, outside every cap. Refuse before auth.
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":  # lifespan
            await self.app(scope, receive, send)
            return
        if path in _EXEMPT_PATHS:
            # R7 M1: strip credentials so auth never calls the backend for an uncounted request.
            headers = [
                (k, v)
                for k, v in scope.get("headers") or []
                if k.lower() not in _CREDENTIAL_HEADERS
            ]
            await self.app({**scope, "headers": headers}, receive, send)
            return
        digest, ip = self._identity(scope)
        verified = digest in self._verified or not self.auth_enabled
        # L1 (R5): a token that has not passed auth yet shares ONE small bucket per IP, however
        # many distinct junk tokens it sends: each would otherwise get its own bucket and its own
        # slots. A verified credential gets its own bucket and, whatever the IP, its own cap (M1).
        if not self.auth_enabled:
            client, credential = f"open@{ip}", None  # no credential means anything here
        else:
            client = f"{digest}@{ip}" if verified else f"unverified@{ip}"
            credential = digest if verified else None
        cap = self.per_client if verified else self.per_unverified
        if (
            self.inflight >= self.limit
            or (not verified and self._unverified_inflight >= self.unverified_total)
            or self._by_client.get(client, 0) >= cap
            or (
                credential is not None
                and self._by_credential.get(credential, 0) >= self.per_credential
            )
        ):
            self._note_shed()
            response = problem_response(
                503,
                title="Service Unavailable",
                type_="/problems/overloaded",
                detail="The server is at its concurrent request limit",
                instance=path,
                # 1 to 3 s: one fixed value would make every shed client retry together (N2).
                headers={"Retry-After": str(random.randint(1, 3))},  # noqa: S311 - not security
            )
            await response(scope, receive, send)
            return
        self.inflight += 1
        self._by_client[client] = self._by_client.get(client, 0) + 1
        if credential is not None:
            self._by_credential[credential] = self._by_credential.get(credential, 0) + 1
        if not verified:
            self._unverified_inflight += 1

        async def watching_send(message: MutableMapping[str, Any]) -> None:
            # R6 M1: "verified" is the auth middleware's verdict, read from the shared scope,
            # never a status code: 404, 405 and 307 answer before auth runs.
            user = scope.get("user")
            if message["type"] == "http.response.start" and getattr(
                user, "is_authenticated", False
            ):
                self._note_verified(digest)
            await send(message)

        try:
            await self.app(scope, receive, watching_send if not verified else send)
        finally:
            self.inflight -= 1
            _release(self._by_client, client)
            if credential is not None:
                _release(self._by_credential, credential)
            if not verified:
                self._unverified_inflight -= 1

    def _note_verified(self, digest: str) -> None:
        """Remember a credential whose request passed auth.

        Bounded and oldest-first: a junk token never gets here (auth refused it, and a route
        that answers before auth leaves `scope['user']` unauthenticated), so the set holds only
        credentials that were once accepted. ponytail: no revocation; a revoked
        key keeps its own bucket until it ages out, which only costs it the shared one.
        """
        self._verified[digest] = None
        while len(self._verified) > MAX_VERIFIED:
            del self._verified[next(iter(self._verified))]

    def mark_verified(self, authorization: bytes) -> None:
        """Treat the credential in this Authorization header value as verified (tests, warm-up)."""
        self._note_verified(self._digest(authorization))

    @staticmethod
    def _digest(auth: bytes) -> str:
        """16 hex of SHA-256 of the canonical credential, never the raw token.

        M1 (R4): hashed the way auth parses it (scheme case-insensitive, token trimmed), so
        `Bearer`, `bearer` and `BEARER` with one token share one bucket.
        """
        scheme, _, token = auth.partition(b" ")
        canonical = token.strip() if scheme.lower() == b"bearer" else auth
        return hashlib.sha256(canonical).hexdigest()[:16]

    def _identity(self, scope: Scope) -> tuple[str, str]:
        """The credential digest and the client IP (IPv6 folded to /64) of a request."""
        ip = (
            rate_key_for_ip(client_ip_from_scope(scope, self.trusted_hops)) or "unknown"
        )
        auth = bytes(
            next(
                (
                    v
                    for k, v in scope.get("headers") or []
                    if k.lower() == b"authorization"
                ),
                b"",
            )
        )
        return self._digest(auth), ip

    def _note_shed(self) -> None:
        """Count the refusal and log it at most once per second, with the running total."""
        self.shed += 1
        now = time.monotonic()
        if (
            self._last_shed_log is None
            or now - self._last_shed_log >= _SHED_LOG_INTERVAL_S
        ):
            self._last_shed_log = now
            logger.warning(
                "concurrent request limit reached; shedding requests",
                extra={
                    "event": "overloaded",
                    "inflight": self.inflight,
                    "limit": self.limit,
                    "shed_total": self.shed,
                },
            )


def _declares_body(scope: Scope) -> bool:
    """True if the request head promises a body (Content-Length above 0, or chunked)."""
    for name, value in scope.get("headers") or []:
        key = bytes(name).lower()
        if key == b"transfer-encoding":
            return True
        if key == b"content-length":
            return bytes(value).strip() not in (b"", b"0")
    return False


class RequestBodyGuard:
    """Close the socket on a response sent with the request body unread; 408 a stalled body.

    uvicorn keeps a connection open after a response while the body is unread, and has no
    body-read deadline: one byte every few seconds held a socket forever with no slot, and
    enough of them make `/health` fail at the connection backstop. Every response started
    while the body is still pending (a 401, a 503 shed, any early refusal) carries
    `Connection: close`; a body still incomplete `deadline_s` after the request arrived is
    answered 408 plus close and the app sees `http.disconnect`.
    """

    def __init__(
        self,
        app: ASGIApp,
        deadline_s: float | None = None,
        max_body: int = MAX_BODY_BYTES,
    ) -> None:
        """Wrap `app`; the deadline defaults to `BODY_READ_DEADLINE_S` read at construction."""
        self.app = app
        self.deadline_s = BODY_READ_DEADLINE_S if deadline_s is None else deadline_s
        self.max_body = max_body
        self._fixed = deadline_s is not None  # an explicit deadline is not scaled

    def _deadline_for(self, scope: Scope) -> float:
        """`deadline_s`, plus declared length over `BODY_MIN_RATE_BPS`, capped (L1).

        The length counts at most `max_body` (R5 L3): a declared 4 MB body is over the body
        limit and earns no more time than a 1 MiB one, so it cannot hold a slot for the cap.
        """
        if self._fixed:
            return self.deadline_s
        for name, value in scope.get("headers") or []:
            if bytes(name).lower() == b"content-length":
                text = bytes(value).strip()
                if text.isdigit():
                    # 13 or more digits is over any limit, and `int` of 4,300 digits raises
                    length = min(
                        int(text) if len(text) <= 12 else self.max_body, self.max_body
                    )
                    scaled = self.deadline_s + length / BODY_MIN_RATE_BPS
                    return min(scaled, max(BODY_DEADLINE_CAP_S, self.deadline_s))
        return self.deadline_s

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Wrap `receive` and `send` for one request."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        pending = _declares_body(scope)
        started = cut = False
        limit_s = self._deadline_for(scope)
        due = time.monotonic() + limit_s

        async def guarded_send(message: MutableMapping[str, Any]) -> None:
            nonlocal started
            if cut:
                return  # the 408 is the response; whatever the app tries now is dropped
            if message["type"] == "http.response.start":
                started = True
                if pending and not any(
                    k.lower() == b"connection" for k, _ in message["headers"]
                ):
                    message = {
                        **message,
                        "headers": [*message["headers"], (b"connection", b"close")],
                    }
            await send(message)

        async def guarded_receive() -> MutableMapping[str, Any]:
            nonlocal pending, cut, started
            if not pending:
                return await receive()
            try:
                message = await asyncio.wait_for(
                    receive(), max(0.0, due - time.monotonic())
                )
            except TimeoutError:
                pending = False
                if not started:
                    response = problem_response(
                        408,
                        title="Request Timeout",
                        type_="/problems/request-body-timeout",
                        detail=f"The request body was not received within {limit_s:g} s",
                        instance=scope.get("path", ""),
                        headers={"Connection": "close"},
                    )
                    await response(scope, receive, send)
                    cut = True
                    started = True
                return {"type": "http.disconnect"}
            if message["type"] == "http.disconnect" or not message.get(
                "more_body", False
            ):
                pending = False
            return message

        await self.app(scope, guarded_receive, guarded_send)
