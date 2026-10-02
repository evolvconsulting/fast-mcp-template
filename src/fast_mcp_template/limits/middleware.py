"""Rate limit middleware: buckets per client IP, per user, or both.

Shared-credential (`legacy`) traffic is bucketed per client IP. Per-user
(`platform`) traffic is bucketed per user AND per IP. 429 problem+json
with the standard headers; never calls the app when refused. With
`redis=None` nothing is limited, and only `settings.mcp_path` is.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from redis.asyncio import Redis
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fast_mcp_template.auth.claims import auth_path_of, claims_of
from fast_mcp_template.auth.types import CLAIM_RATE_LIMIT, CLAIM_USER_ID
from fast_mcp_template.config import Settings
from fast_mcp_template.http.errors import problem_response
from fast_mcp_template.http.log import present
from fast_mcp_template.http.net import client_ip_from_scope, rate_key_for_ip
from fast_mcp_template.limits.ratelimit import (
    RateDecision,
    ip_bucket_key,
    platform_ip_bucket_key,
    take_token,
    user_bucket_key,
)

logger = logging.getLogger(__name__)

#: A backend `rate_limit` claim is clamped to this multiple of the
#: per-user default, so a backend bug or compromise cannot switch the
#: limiter off with a huge value.
RATE_LIMIT_CLAIM_CEILING_FACTOR: Final = 10

#: The per-user traffic's per-IP bucket holds this multiple of the
#: per-user default: 20 users at the full rate can share one egress
#: IP, and the per-user bucket stays the real limiter. It has its own
#: key, so shared-credential clients on the same address keep theirs.
PLATFORM_IP_BUCKET_FACTOR: Final = 20


def _int_claim(claims: dict[str, Any], name: str) -> int | None:
    value = claims.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class RateLimitMiddleware:
    """Token buckets: per IP, or per user AND per IP."""

    def __init__(
        self, app: ASGIApp, *, settings: Settings, redis: Redis | None
    ) -> None:
        """Wrap `app`; with `redis=None` nothing is limited."""
        self.app = app
        self.settings = settings
        self.redis = redis

    def _platform_capacity(self, claims: dict[str, Any]) -> int:
        """Return the user capacity: claim (clamped) or default."""
        s = self.settings
        claim = _int_claim(claims, CLAIM_RATE_LIMIT)
        if claim is None:
            return s.default_rate_limit_per_user
        return min(
            claim, RATE_LIMIT_CLAIM_CEILING_FACTOR * s.default_rate_limit_per_user
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Limit `settings.mcp_path`; pass everything else through."""
        s = self.settings
        if (
            self.redis is None
            or scope["type"] != "http"
            or scope.get("path") != s.mcp_path
        ):
            await self.app(scope, receive, send)
            return

        auth_path = auth_path_of(scope)
        if auth_path == "none":  # RequireAuth answers 401; nothing to bucket
            await self.app(scope, receive, send)
            return

        claims = claims_of(scope)
        user_id = claims.get(CLAIM_USER_ID)
        client_ip = client_ip_from_scope(scope, s.trusted_proxy_hops)
        ip_name = rate_key_for_ip(client_ip) or "unknown"
        key = s.server_key
        platform_ip = (
            "ip",
            platform_ip_bucket_key(key, ip_name),
            PLATFORM_IP_BUCKET_FACTOR * s.default_rate_limit_per_user,
        )
        # Every scope must pass. Per-user traffic takes the USER bucket
        # first: a refused user never spends a token from the IP bucket
        # shared with colleagues behind one egress IP. An IP refusal
        # then costs the refused request one token of its own user.
        if auth_path == "platform" and user_id:
            checks = [
                (
                    "user",
                    user_bucket_key(key, str(user_id)),
                    self._platform_capacity(claims),
                ),
                platform_ip,
            ]
        elif auth_path == "platform":
            checks = [platform_ip]
        else:
            checks = [("ip", ip_bucket_key(key, ip_name), s.legacy_rate_limit_per_ip)]

        decisions: list[RateDecision] = []
        for scope_kind, bucket, capacity in checks:
            decision = await take_token(
                self.redis,
                bucket,
                capacity=capacity,
                refill_period_s=s.rate_limit_window_s,
            )
            decisions.append(decision)
            if not decision.allowed:
                await self._refuse(
                    scope,
                    receive,
                    send,
                    decision,
                    scope_kind,
                    auth_path,
                    user_id,
                    client_ip,
                )
                return
        # Headers reflect the limiter closest to exhaustion.
        headers = self._headers(min(decisions, key=lambda d: d.remaining))

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable = MutableHeaders(scope=message)
                for name, value in headers.items():
                    mutable[name] = value
            await send(message)

        await self.app(scope, receive, send_wrapper)

    async def _refuse(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        decision: RateDecision,
        scope_kind: str,
        auth_path: str,
        user_id: object,
        client_ip: str | None,
    ) -> None:
        """Answer 429 problem+json and log `rate_limited`."""
        logger.warning(
            "rate limited",
            extra=present(
                event="rate_limited",
                auth_path=auth_path,
                scope=scope_kind,
                user_id=user_id if auth_path == "platform" else None,
                client_ip=client_ip if scope_kind == "ip" else None,
                limit=decision.limit,
                retry_after_s=decision.retry_after_s,
            ),
        )
        response = problem_response(
            429,
            title="Rate Limited",
            type_="/problems/rate-limited",
            detail="Rate limit exceeded",
            instance=scope["path"],
            headers={
                **self._headers(decision),
                "Retry-After": str(decision.retry_after_s),
            },
        )
        await response(scope, receive, send)

    @staticmethod
    def _headers(d: RateDecision) -> dict[str, str]:
        values = {"Limit": d.limit, "Remaining": d.remaining, "Reset": d.reset_s}
        return {
            f"{prefix}-{name}": str(value)
            for prefix in ("RateLimit", "X-RateLimit")
            for name, value in values.items()
        }
