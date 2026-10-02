"""Tests for the health endpoints and the pluggable check list."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx2 as httpx
import pytest
from fastmcp import FastMCP
from starlette.testclient import TestClient

from fast_mcp_template.__main__ import build_app
from fast_mcp_template.config import Settings
from fast_mcp_template.http.errors import register_error_handlers
from fast_mcp_template.http.health import (
    CheckResult,
    HealthRegistry,
    check_http,
    check_redis,
    register_health_routes,
)
from fast_mcp_template.http.request_id import RequestIdMiddleware
from fast_mcp_template.infra import redis_client
from fast_mcp_template.server import health as server_health


class Clock:
    """A settable monotonic clock for the cache."""

    def __init__(self) -> None:
        """Start at an arbitrary time."""
        self.t = 100.0

    def __call__(self) -> float:
        """Return the current fake time."""
        return self.t


def _client(registry: HealthRegistry) -> TestClient:
    mcp = FastMCP("t")
    register_health_routes(mcp, registry)
    app = mcp.http_app(path="/mcp")
    register_error_handlers(app)
    return TestClient(RequestIdMiddleware(app), raise_server_exceptions=False)


def _ok(name: str) -> Any:
    async def check() -> CheckResult:
        return CheckResult(name, True, "fine")

    return check


def test_live_and_alias_are_200_with_no_checks() -> None:
    c = _client(HealthRegistry())
    for path in ("/health", "/health/live"):
        assert c.get(path).json() == {"status": "ok"}


def test_ready_with_no_checks_is_ok_and_lists_them_when_present() -> None:
    reg = HealthRegistry()
    assert _client(reg).get("/health/ready").json() == {
        "status": "ok",
        "checks": [],
    }
    reg.add("a", _ok("a"))
    reg.add("b", _ok("b"))
    body = _client(reg).get("/health/ready").json()
    assert body["checks"] == [
        {"name": "a", "ok": True},
        {"name": "b", "ok": True},
    ]
    assert reg.names() == ["a", "b"]


def test_a_failed_check_is_a_503_problem_naming_only_the_check() -> None:
    async def bad() -> CheckResult:
        return CheckResult("db", False, "SECRET-DETAIL")

    reg = HealthRegistry()
    reg.add("ok", _ok("ok"))
    reg.add("db", bad)
    resp = _client(reg).get("/health/ready")
    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert "Failed checks: db" in resp.json()["detail"]
    assert "SECRET-DETAIL" not in resp.text


def test_a_raising_check_is_a_failed_check_without_exception_text() -> None:
    async def boom() -> CheckResult:
        raise RuntimeError("password=hunter2")

    reg = HealthRegistry()
    reg.add("boom", boom)
    resp = _client(reg).get("/health/ready")
    assert resp.status_code == 503
    assert "hunter2" not in resp.text
    assert asyncio.run(reg.run()) == [CheckResult("boom", False, "RuntimeError")]


def test_a_hung_check_times_out_as_a_failed_check() -> None:
    async def hang() -> CheckResult:
        await asyncio.sleep(30)
        return CheckResult("hang", True, "")

    reg = HealthRegistry(timeout_s=0.05)
    reg.add("hang", hang)
    assert asyncio.run(reg.run()) == [CheckResult("hang", False, "timeout")]


def test_checks_run_concurrently_not_in_series() -> None:
    async def slow() -> CheckResult:
        await asyncio.sleep(0.2)
        return CheckResult("s", True, "")

    reg = HealthRegistry(timeout_s=1.0)
    for i in range(5):
        reg.add(f"s{i}", slow)

    async def timed() -> float:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await reg.run()
        return loop.time() - t0

    assert asyncio.run(timed()) < 0.6  # 5 x 0.2 s in series would be 1.0 s


def test_ready_is_cached_for_the_ttl_then_refreshed() -> None:
    clock = Clock()
    calls: list[int] = []

    async def counted() -> CheckResult:
        calls.append(1)
        return CheckResult("c", True, "")

    reg = HealthRegistry(now=clock)
    reg.add("c", counted)
    c = _client(reg)
    c.get("/health/ready")
    c.get("/health/ready")
    assert len(calls) == 1
    clock.t += 4.9
    c.get("/health/ready")
    assert len(calls) == 1
    clock.t += 0.2
    c.get("/health/ready")
    assert len(calls) == 2


def test_concurrent_callers_share_one_run() -> None:
    calls: list[int] = []

    async def slow() -> CheckResult:
        calls.append(1)
        await asyncio.sleep(0.05)
        return CheckResult("s", True, "")

    reg = HealthRegistry()
    reg.add("s", slow)

    async def many() -> None:
        await asyncio.gather(*(reg.cached() for _ in range(10)))

    asyncio.run(many())
    assert len(calls) == 1


def test_adding_a_check_drops_the_stale_cached_answer() -> None:
    reg = HealthRegistry()
    reg.add("a", _ok("a"))
    c = _client(reg)
    assert len(c.get("/health/ready").json()["checks"]) == 1
    reg.add("b", _ok("b"))
    assert len(c.get("/health/ready").json()["checks"]) == 2


def test_same_name_replaces_rather_than_duplicates() -> None:
    reg = HealthRegistry()
    reg.add("a", _ok("a"))
    reg.add("a", _ok("a"))
    assert reg.names() == ["a"]


# --- the stock checks ------------------------------------------------


class _Redis:
    def __init__(self, policy: Any = "noeviction", up: bool = True) -> None:
        self.policy = policy
        self.up = up

    async def ping(self) -> bool:
        if not self.up:
            raise ConnectionError("down")
        return True

    async def config_get(self, key: str) -> dict[str, Any]:
        if self.policy is None:
            raise RuntimeError("CONFIG disabled")
        return {key: self.policy}


def test_check_redis_records_the_policy_and_warns_when_not_noeviction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    res = asyncio.run(check_redis(_Redis()))  # type: ignore[arg-type]
    assert res == CheckResult("redis", True, "maxmemory-policy=noeviction")
    assert not caplog.records
    with caplog.at_level(logging.WARNING):
        res = asyncio.run(check_redis(_Redis("allkeys-lru")))  # type: ignore[arg-type]
    assert res.ok
    assert any(
        r.__dict__.get("event") == "redis_eviction_policy" for r in caplog.records
    )
    unavailable = asyncio.run(check_redis(_Redis(None)))  # type: ignore[arg-type]
    assert unavailable.detail == "maxmemory-policy=unavailable"


def test_check_redis_propagates_a_dead_redis_for_the_registry_to_catch() -> None:
    reg = HealthRegistry()
    redis = _Redis(up=False)
    reg.add("redis", lambda: check_redis(redis))  # type: ignore[arg-type]
    assert asyncio.run(reg.run()) == [CheckResult("redis", False, "ConnectionError")]


@pytest.mark.parametrize(("status", "ok"), [(200, True), (503, False)])
def test_check_http_reads_the_status(status: int, ok: bool) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status))
    res = asyncio.run(
        check_http("backend", "http://be/api/health/live", transport=transport)
    )
    assert res == CheckResult("backend", ok, f"status={status}")


# --- the template's own wiring ---------------------------------------


@pytest.fixture
def clean_server_health() -> Any:
    before = dict(server_health._checks)  # noqa: SLF001
    yield
    server_health._checks.clear()  # noqa: SLF001
    server_health._checks.update(before)  # noqa: SLF001
    server_health._at = None  # noqa: SLF001
    redis_client.reset_redis_for_tests()


def test_build_app_serves_health_and_registers_the_redis_check_once(
    clean_server_health: Any,
) -> None:
    kw: dict[str, Any] = {
        "dangerously_disable_auth": True,
        "redis_url": "redis://localhost:1/0",
    }
    c = TestClient(build_app(Settings(**kw)))
    assert c.get("/health").status_code == 200
    assert server_health.names() == ["redis"]
    build_app(Settings(**kw))  # twice: no duplicates
    assert server_health.names() == ["redis"]
