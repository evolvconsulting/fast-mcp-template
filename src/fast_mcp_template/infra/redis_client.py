"""The one process-wide Redis client.

Connect and socket timeouts are set (2 s each): with none, a dead
Redis meant a 127 s hang and a crash loop (EC-600). A `rediss://` URL
trusts ONLY the internal CA (`internal_verify`), never the system store.
"""

from __future__ import annotations

import ssl
from collections.abc import Mapping
from typing import Any, Final
from urllib.parse import urlparse

from redis.asyncio import ConnectionPool, Redis
from redis.asyncio.connection import Connection, SSLConnection, parse_url

from fast_mcp_template.config import Settings, internal_verify, url_scheme

REDIS_CONNECT_TIMEOUT_S: Final = 2.0
REDIS_SOCKET_TIMEOUT_S: Final = 2.0

_client: Redis | None = None


def _internal_ca_connection(context: ssl.SSLContext) -> type[SSLConnection]:
    """Return an SSLConnection class trusting ONLY `context` (EC-637).

    redis-py builds its own context from `ssl.create_default_context()`,
    which loads the system CA store, then adds `ssl_ca_data` on top, so
    a public CA would also be trusted. Handing the connection our own
    context (the internal CA alone) replaces that.
    """

    class InternalCAConnection(SSLConnection):
        def _connection_arguments(self) -> Mapping[str, Any]:
            # Skip SSLConnection's own context; use Connection's args.
            kwargs = dict(Connection._connection_arguments(self))  # noqa: SLF001
            kwargs["ssl"] = context
            return kwargs

    return InternalCAConnection


def get_redis(settings: Settings) -> Redis | None:
    """Return the shared client, or None when `redis_url` is blank.

    Built once per process from the first non-blank URL seen.
    """
    global _client  # noqa: PLW0603 - one client per process
    url = (settings.redis_url or "").strip()
    if not url:
        return None
    if _client is None:
        timeouts: dict[str, Any] = {
            "decode_responses": True,
            "socket_connect_timeout": REDIS_CONNECT_TIMEOUT_S,
            "socket_timeout": REDIS_SOCKET_TIMEOUT_S,
        }
        if url_scheme(url) == "rediss":
            context = internal_verify(settings)
            if not (urlparse(url).hostname and isinstance(context, ssl.SSLContext)):
                # Never fall back to the system trust store (EC-637).
                raise RuntimeError("rediss needs internal_ca_cert and a host")
            # `from_url` lets the URL's own connection class win.
            options: dict[str, Any] = {**parse_url(url), **timeouts}
            options["connection_class"] = _internal_ca_connection(context)
            pool = ConnectionPool(**options)
            client = Redis(connection_pool=pool)
            client.auto_close_connection_pool = True
        else:
            client = Redis.from_url(url, **timeouts)
        _client = client
    return _client


def reset_redis_for_tests() -> None:
    """Forget the process-wide client so a test can build its own."""
    global _client  # noqa: PLW0603 - see get_redis
    _client = None
