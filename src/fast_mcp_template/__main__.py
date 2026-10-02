"""Console entry point.

`fast-mcp-template` runs the server on stdio. `fast-mcp-template http`
serves it over HTTP under uvicorn (see `build_app`).
"""

from __future__ import annotations

import sys

import uvicorn
from starlette.types import ASGIApp

from fast_mcp_template.auth.dual import build_verifier, resolve_auth_mode
from fast_mcp_template.config import Settings, load_settings, log_test_overrides
from fast_mcp_template.http import build_http_middleware, wrap_http_app
from fast_mcp_template.http.concurrency import (
    LIMIT_CONCURRENCY,
    ConcurrencyLimitMiddleware,
    RequestBodyGuard,
)
from fast_mcp_template.http.errors import register_error_handlers
from fast_mcp_template.http.health import check_redis
from fast_mcp_template.infra.redis_client import get_redis
from fast_mcp_template.server import build_server, health


def build_app(settings: Settings) -> ASGIApp:
    """Return the whole ASGI app.

    Outermost to innermost: request id, audit (both `wrap_http_app`, so
    the audit line sits OUTSIDE fastmcp's auth), the slow-body guard,
    the
    in-flight limiter, then `http_app`.

    Authentication is built here (`build_verifier`), so serving over
    HTTP
    without a configured credential refuses to boot.


    `host_origin_protection` and `allowed_hosts` are NOT passed:
    fastmcp then leaves its Host guard off, which is deliberate behind
    a load balancer that presents IP-literal and internal Host headers.
    Cross-origin abuse of a bearer-token API is a residual risk to
    record in your own threat model.
    """
    log_test_overrides(settings)
    # Boot refusals (a bad internal CA, named) run BEFORE `get_redis`
    # builds
    # the TLS pool, so the operator sees the variable to fix, not a pool
    # error.
    resolve_auth_mode(settings)
    redis = get_redis(settings)
    if redis is not None:
        health.add("redis", lambda: check_redis(redis))
    server = build_server()
    # Fails CLOSED at boot: no key, a weak key or a half-configured mode
    # raises `AuthConfigError` naming the variable. None only for
    # `dangerously_disable_auth` in legacy mode outside production.
    server.auth = build_verifier(settings, redis)
    inner = server.http_app(
        path=settings.mcp_path,
        stateless_http=True,
        middleware=build_http_middleware(settings, redis),
    )
    register_error_handlers(inner)
    # The limiter sits INSIDE the request id and audit layers, so a shed
    # 503
    # carries X-Request-ID and is logged too; the body guard sits
    # outside it.
    limiter = ConcurrencyLimitMiddleware(
        inner,
        LIMIT_CONCURRENCY,
        trusted_hops=settings.trusted_proxy_hops,
        auth_enabled=not settings.dangerously_disable_auth,
    )
    guarded = RequestBodyGuard(limiter, max_body=settings.max_request_body_bytes)
    return wrap_http_app(guarded, settings)


def main(argv: list[str] | None = None) -> None:
    """Run on stdio, or over HTTP when the first argument is `http`."""
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["http"]:
        settings = load_settings()
        uvicorn.run(
            build_app(settings),
            host=settings.mcp_host,
            port=settings.mcp_port,
            proxy_headers=False,
        )
        return
    build_server().run()


if __name__ == "__main__":
    main()
