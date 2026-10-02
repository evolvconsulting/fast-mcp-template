"""Health endpoints with a pluggable readiness check list.

- `GET /health` and `GET /health/live`: liveness, always 200.
- `GET /health/ready`: runs the registered checks, 200 or a 503
  problem+json. Unauthenticated, so the result is cached in-process
  (5 s, one refresh in flight) and the body never carries exception
  text.

The seam: a gateway registers its own checks on a `HealthRegistry`
(`registry.add("vault", my_async_check)`). `check_redis` and
`check_http` are the two stock checks. A check is an async callable
returning a `CheckResult`; if it raises or hangs it becomes a failed
check, never an exception out of the endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

import httpx2 as httpx
from fastmcp import FastMCP
from redis.asyncio import Redis
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from fast_mcp_template.http.errors import problem_response

logger = logging.getLogger(__name__)

READY_CHECK_TIMEOUT_S: Final = 2.0
READY_CACHE_TTL_S: Final = 5.0


@dataclass(frozen=True)
class CheckResult:
    """One readiness check; `detail` never holds a secret."""

    name: str
    ok: bool
    detail: str


Check = Callable[[], Awaitable[CheckResult]]


async def check_redis(redis: Redis) -> CheckResult:
    """PING Redis and record its eviction policy."""
    await redis.ping()
    try:
        config = await redis.config_get("maxmemory-policy")
        policy = str(config.get("maxmemory-policy", "unavailable"))
    except Exception:  # noqa: BLE001 - CONFIG is often disabled
        policy = "unavailable"
    if policy != "noeviction":
        logger.warning(
            "redis maxmemory-policy is not noeviction: keys can be evicted",
            extra={"event": "redis_eviction_policy", "policy": policy},
        )
    return CheckResult("redis", True, f"maxmemory-policy={policy}")


async def check_http(
    name: str,
    url: str,
    *,
    verify: ssl.SSLContext | bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CheckResult:
    """GET `url`; it must answer 200 (a backend liveness probe)."""
    async with httpx.AsyncClient(
        timeout=READY_CHECK_TIMEOUT_S, verify=verify, transport=transport
    ) as client:
        resp = await client.get(url)
    return CheckResult(name, resp.status_code == 200, f"status={resp.status_code}")


class HealthRegistry:
    """The ordered, named readiness checks plus the 5 s result cache."""

    def __init__(
        self,
        *,
        now: Callable[[], float] = time.monotonic,
        ttl_s: float = READY_CACHE_TTL_S,
        timeout_s: float = READY_CHECK_TIMEOUT_S,
    ) -> None:
        """Create an empty registry (clock injectable for tests)."""
        self._checks: dict[str, Check] = {}
        self._now = now
        self._ttl_s = ttl_s
        self._timeout_s = timeout_s
        self._lock = asyncio.Lock()
        self._at: float | None = None
        self._results: list[CheckResult] = []

    def add(self, name: str, check: Check) -> None:
        """Register `check` under `name`; the same name replaces."""
        self._checks[name] = check
        self._at = None  # the cached answer no longer describes the list

    def names(self) -> list[str]:
        """Return the registered check names, in order."""
        return list(self._checks)

    async def _bounded(self, name: str, check: Check) -> CheckResult:
        """Run one check under the cap; failure is data, not a crash."""
        try:
            return await asyncio.wait_for(check(), self._timeout_s)
        except TimeoutError:
            return CheckResult(name, False, "timeout")
        except Exception as exc:  # noqa: BLE001
            return CheckResult(name, False, type(exc).__name__)

    async def run(self) -> list[CheckResult]:
        """Run every check concurrently, each under the timeout."""
        return list(
            await asyncio.gather(
                *(self._bounded(n, c) for n, c in self._checks.items())
            )
        )

    async def cached(self) -> list[CheckResult]:
        """Return the last result while fresh; one refresh at a time."""
        async with self._lock:
            now = self._now()
            if self._at is None or now - self._at >= self._ttl_s:
                self._results = await self.run()
                self._at = self._now()
            return self._results


def register_health_routes(mcp: FastMCP, registry: HealthRegistry) -> None:
    """Add `/health`, `/health/live`, `/health/ready` (no auth)."""

    async def live(request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def ready(request: Request) -> Response:
        results = await registry.cached()
        failed = [c.name for c in results if not c.ok]
        if failed:
            return problem_response(
                503,
                title="Not Ready",
                type_="/problems/not-ready",
                detail=f"Failed checks: {', '.join(failed)}",
                instance=request.url.path,
            )
        return JSONResponse(
            {
                "status": "ok",
                "checks": [{"name": c.name, "ok": c.ok} for c in results],
            }
        )

    routes = (
        ("/health", live),
        ("/health/live", live),
        ("/health/ready", ready),
    )
    for path, handler in routes:
        mcp.custom_route(path, methods=["GET"])(handler)
