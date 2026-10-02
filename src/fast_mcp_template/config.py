"""Settings, read from the environment.

Every field here is a name a deployer has to know about, so the
template ships the SEAM rather than a set of fields: add yours, and
`docs/reviews/check-settings-are-read.py` (carried, disabled) is the
gate that refuses a field nothing outside this module reads.
"""

from __future__ import annotations

import ssl
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    The prefix is the ONE place the environment-variable namespace is
    written. Change it when you rename the project; nothing else
    should spell it out.
    """

    model_config = SettingsConfigDict(env_prefix="MCP_TEMPLATE_", extra="forbid")

    #: How the server greets a caller. A placeholder field so the
    #: settings seam is exercised by a real reader rather than being
    #: an empty class nothing can go wrong in.
    greeting: str = "hello"

    # --- HTTP serving (the `http` entry point) -----------------------
    #: Bind address of the HTTP listener.
    mcp_host: str = "127.0.0.1"
    #: Port of the HTTP listener.
    mcp_port: int = Field(default=8000, ge=1, le=65535)
    #: Mount path of the MCP endpoint. Distinct per server so several
    #: gateways can share one load balancer by path.
    mcp_path: str = "/mcp"
    #: X-Forwarded-For entries appended by proxies YOU trust (an ALB
    #: appends one). Must equal the real proxy count: too high lets a
    #: client choose its own client IP.
    trusted_proxy_hops: int = Field(default=1, ge=0, le=5)
    #: Request-body ceiling in bytes (1 MiB). fastmcp enforces none.
    max_request_body_bytes: int = Field(default=1_048_576, ge=1024)
    #: Redis URL. Blank means no Redis (limits and caches that need it
    #: are then off, and say so).
    redis_url: str | None = None
    #: PEM of the private CA that signed your internal certificates
    #: (Redis `rediss://`, a backend `https://`). Public material, held
    #: in memory and used as the SOLE trust root for those connections.
    internal_ca_cert: str | None = None


def load_settings() -> Settings:
    """Read settings from the environment."""
    return Settings()


def url_scheme(url: str | None) -> str:
    """Return the lower-cased scheme of a URL setting.

    A blank or malformed value gives ''. One reader for the boot check
    and the Redis client, so they never disagree about `rediss`.
    """
    return urlparse((url or "").strip()).scheme.lower()


def internal_ca_pem(settings: Settings) -> str | None:
    """Return the internal CA PEM, or None when unset or blank."""
    return (settings.internal_ca_cert or "").strip() or None


def internal_verify(settings: Settings) -> ssl.SSLContext | bool:
    """Return the `verify=` for a client of an internal service.

    Trusts ONLY the internal CA. Returns True (default trust) when no
    CA is configured, i.e. for plain-http setups. Raises `ssl.SSLError`
    on a PEM that does not parse.
    """
    pem = internal_ca_pem(settings)
    return ssl.create_default_context(cadata=pem) if pem else True
