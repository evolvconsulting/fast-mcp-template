"""HTTP serving blocks: request id, body limit, errors, order.

`wrap_http_app` wraps the WHOLE app (outside fastmcp's auth);
`build_http_middleware` is the list passed to `mcp.http_app(...)`
(inside fastmcp's auth). Later blocks (rate limit, audit) join these
two functions rather than adding a third place to compose.
"""

from __future__ import annotations

import logging

from starlette.middleware import Middleware as StarletteMiddleware
from starlette.types import ASGIApp

from fast_mcp_template.config import Settings
from fast_mcp_template.http.body_limit import BodySizeLimitMiddleware
from fast_mcp_template.http.request_id import RequestIdMiddleware

logger = logging.getLogger(__name__)


def wrap_http_app(app: ASGIApp, settings: Settings) -> ASGIApp:
    """Wrap the assembled HTTP app with the request-id layer.

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
    return RequestIdMiddleware(app)


def build_http_middleware(settings: Settings) -> list[StarletteMiddleware]:
    """Return the middleware list for `mcp.http_app(middleware=...)`.

    Outermost first, inside fastmcp's auth. The body limit answers 413
    HERE, not in an exception handler.
    """
    return [StarletteMiddleware(BodySizeLimitMiddleware, settings=settings)]
