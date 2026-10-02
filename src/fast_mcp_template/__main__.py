"""Console entry point.

`fast-mcp-template` runs the server on stdio. `fast-mcp-template http`
serves it over HTTP under uvicorn (see `build_app`).
"""

from __future__ import annotations

import sys

import uvicorn
from starlette.types import ASGIApp

from fast_mcp_template.config import Settings, load_settings
from fast_mcp_template.http import build_http_middleware, wrap_http_app
from fast_mcp_template.http.errors import register_error_handlers
from fast_mcp_template.http.health import check_redis
from fast_mcp_template.infra.redis_client import get_redis
from fast_mcp_template.server import build_server, health


def build_app(settings: Settings) -> ASGIApp:
    """Return the whole ASGI app: request id and audit, then `http_app`.

    `host_origin_protection` and `allowed_hosts` are NOT passed:
    fastmcp then leaves its Host guard off, which is deliberate behind
    a load balancer that presents IP-literal and internal Host headers.
    Cross-origin abuse of a bearer-token API is a residual risk to
    record in your own threat model.
    """
    redis = get_redis(settings)
    if redis is not None:
        health.add("redis", lambda: check_redis(redis))
    inner = build_server().http_app(
        path=settings.mcp_path,
        stateless_http=True,
        middleware=build_http_middleware(settings, redis),
    )
    register_error_handlers(inner)
    return wrap_http_app(inner, settings)


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
