"""HTTP serving blocks: request id, audit, limits, errors, order.

`wrap_http_app` wraps the WHOLE app (outside fastmcp's auth);
`build_http_middleware` is the list passed to `mcp.http_app(...)`
(inside fastmcp's auth, so `scope["user"]` is already set). Every
block joins one of these two functions rather than adding a third
place to compose, so the order is written in exactly one place.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis
from starlette.middleware import Middleware as StarletteMiddleware
from starlette.types import ASGIApp

from fast_mcp_template.config import Settings
from fast_mcp_template.http.audit import AuthAuditMiddleware
from fast_mcp_template.http.body_limit import BodySizeLimitMiddleware
from fast_mcp_template.http.request_id import RequestIdMiddleware
from fast_mcp_template.limits.middleware import RateLimitMiddleware

logger = logging.getLogger(__name__)


def wrap_http_app(app: ASGIApp, settings: Settings) -> ASGIApp:
    """Wrap the assembled app: request id outermost, then the audit.

    The audit layer must sit OUTSIDE fastmcp's auth: anything that
    fails inside auth (a 401, a raising `verify_token`) still gets
    exactly one line. `scope["user"]` is set in place on the shared
    scope dict, so the claims still reach it.

    A hop count above the real proxy count lets a short
    X-Forwarded-For fall to a client-chosen entry, so a client could
    pick its own rate-limit bucket: warn when it is above 1.
    """
    if settings.trusted_proxy_hops > 1:
        logger.warning(
            "trusted_proxy_hops is above 1; it must equal the number "
            "of proxies that append X-Forwarded-For",
            extra={
                "event": "trusted_proxy_hops_high",
                "trusted_proxy_hops": settings.trusted_proxy_hops,
            },
        )
    return RequestIdMiddleware(AuthAuditMiddleware(app, settings=settings))


def build_http_middleware(
    settings: Settings, redis: Redis | None
) -> list[StarletteMiddleware]:
    """Return the middleware list for `mcp.http_app(middleware=...)`.

    Outermost first, inside fastmcp's auth. The body limit sits outside
    the rate limit and answers 413 HERE, not in an exception handler.
    """
    return [
        StarletteMiddleware(BodySizeLimitMiddleware, settings=settings),
        StarletteMiddleware(RateLimitMiddleware, settings=settings, redis=redis),
    ]
