"""Settings, read from the environment.

Every field here is a name a deployer has to know about, so the
template ships the SEAM rather than a set of fields: add yours, and
`docs/reviews/check-settings-are-read.py` (carried, disabled) is the
gate that refuses a field nothing outside this module reads.
"""

from __future__ import annotations

import ssl
from typing import Self
from urllib.parse import urlparse

from pydantic import AwareDatetime, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The rate limiter counts authenticated HTTP REQUESTS (`verify_token`
# runs once per request); people reason in TOOL CALLS, and one tool
# call costs several requests. MEASURED on fastmcp 4.0.3 (fast-mcp-ado
# EC-571), in-process: one tool call from a fresh client costs 3
# authenticated requests on the stateless protocol and 6 on the
# handshake-era session protocol. The constant is the MAXIMUM of the
# eras, pinned by `tests/test_rate_limit_multiplier.py`, so a transport
# or SDK change fails loudly instead of silently eating every budget.
# A client that hits the mount path with the wrong trailing slash gets
# a 307 and BOTH requests are authenticated: it burns 2x this figure.
REQUESTS_PER_TOOL_CALL = 6

# The per-user ceiling in the unit a human reasons about: 60 tool
# calls per minute is ~1/s sustained, far above any interactive
# cadence, so it binds a runaway loop rather than normal work.
DEFAULT_TOOL_CALLS_PER_MINUTE = 60


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

    # --- Rate limiting and audit (limits/, http/audit.py) -------------
    #: Names this server in rate-limit keys (`rate:mcp:<key>:tb:...`),
    #: so several gateways can share one Redis.
    server_key: str = "template"
    #: Per-user bucket capacity, in REQUESTS (REQUESTS_PER_TOOL_CALL).
    #: A per-key `rate_limit` claim overrides it, clamped to 10x.
    default_rate_limit_per_user: int = Field(
        default=DEFAULT_TOOL_CALLS_PER_MINUTE * REQUESTS_PER_TOOL_CALL, ge=1
    )
    #: Refill window of every bucket, in seconds.
    rate_limit_window_s: int = Field(default=60, ge=1)
    #: Shared-credential traffic is bucketed per client IP. Unset, it
    #: is derived as twice the per-user budget.
    legacy_rate_limit_per_ip: int = Field(default=1, ge=1)
    #: Deprecation headers (RFC 9745 / RFC 8594) for a retiring shared
    #: credential, set per stage. Unset means no headers.
    legacy_deprecated_at: AwareDatetime | None = None
    legacy_sunset_at: AwareDatetime | None = None
    #: Where a caller replaces the retiring credential (the `Link`).
    manage_mcp_url: str | None = None

    @model_validator(mode="after")
    def _derive_legacy_rate_limit(self) -> Self:
        """Default the per-IP shared budget to 2x the per-user one."""
        if "legacy_rate_limit_per_ip" not in self.model_fields_set:
            self.legacy_rate_limit_per_ip = 2 * self.default_rate_limit_per_user
        return self


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
