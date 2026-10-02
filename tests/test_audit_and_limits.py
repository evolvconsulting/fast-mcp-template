import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fakeredis.aioredis import FakeRedis
from fastmcp.server.auth import AccessToken
from redis.asyncio import Redis
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fast_mcp_template.config import Settings
from fast_mcp_template.http import audit as audit_module
from fast_mcp_template.http.net import request_id_var
from tests._timing import assert_grows_at_most
from tests.mwshim import mw

MakeSettings = Callable[..., Settings]
FIELDS = {"type", "title", "status", "detail", "instance", "request_id", "timestamp"}
TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")


def token(auth_path: str, **claims: Any) -> AccessToken:
    return AccessToken(
        token="x",
        client_id="legacy"
        if auth_path == "legacy"
        else f"platform:{claims.get('user_id')}",
        scopes=[],
        expires_at=None,
        claims={"auth_path": auth_path, **claims},
    )


class Echo:
    """Inner app. Simulates fastmcp's auth by reading the user from test headers."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.calls = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.calls += 1
        await send(
            {"type": "http.response.start", "status": self.status, "headers": []}
        )
        await send({"type": "http.response.body", "body": b"ok"})


def with_user(app: ASGIApp, claims_by_header: dict[str, Any] | None) -> ASGIApp:
    """Set scope["user"] like mcp's AuthenticationMiddleware, from `claims_by_header`."""

    async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and claims_by_header is not None:
            scope["user"] = SimpleNamespace(access_token=token(**claims_by_header))
        await app(scope, receive, send)

    return wrapped


async def call(
    app: ASGIApp,
    path: str = "/mcp",
    headers: dict[str, str] | None = None,
    client: tuple[str, int] | None = ("10.0.0.1", 1234),
    method: str = "POST",
    body: bytes = b"",
    chunks: list[bytes] | None = None,
) -> SimpleNamespace:
    scope: Scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
        "client": client,
    }
    parts = list(chunks) if chunks is not None else [body]
    sent: list[Message] = []

    async def receive() -> Message:
        if parts:
            more = len(parts) > 1
            return {"type": "http.request", "body": parts.pop(0), "more_body": more}
        return {"type": "http.disconnect"}

    async def send(m: Message) -> None:
        sent.append(m)

    await app(scope, receive, send)
    start = next((m for m in sent if m["type"] == "http.response.start"), None)
    hdrs = {
        k.decode().lower(): v.decode() for k, v in (start or {"headers": []})["headers"]
    }
    payload = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return SimpleNamespace(
        status=start["status"] if start else None, headers=hdrs, body=payload
    )


def audit(
    settings: Settings, app: ASGIApp, claims: dict[str, Any] | None = None
) -> Any:
    """The audit middleware inside a fake auth layer (which sets the user first)."""
    inner = mw.AuthAuditMiddleware(app, settings=settings)
    outer: Any = with_user(inner, claims)
    outer.alarm = inner.alarm
    return outer


def events(caplog: pytest.LogCaptureFixture, name: str) -> list[Any]:
    return [r for r in caplog.records if getattr(r, "event", None) == name]


# ---------------------------------------------------------------- auth_path_of


def test_auth_path_of() -> None:
    assert (
        mw.auth_path_of({"user": SimpleNamespace(access_token=token("legacy"))})
        == "legacy"
    )
    assert (
        mw.auth_path_of({"user": SimpleNamespace(access_token=token("platform"))})
        == "platform"
    )
    assert mw.auth_path_of({}) == "none"
    assert mw.auth_path_of({"user": object()}) == "none"


# ------------------------------------------------------- deprecation headers


DEP = datetime(2026, 10, 1, tzinfo=UTC)
SUN = datetime(2026, 12, 1, tzinfo=UTC)


async def test_legacy_gets_deprecation_headers_in_exact_formats(
    make_settings: MakeSettings,
) -> None:
    s = make_settings(
        legacy_deprecated_at=DEP,
        legacy_sunset_at=SUN,
        manage_mcp_url="https://m.example/x",
    )
    r = await call(audit(s, Echo(), {"auth_path": "legacy"}))
    assert r.headers["deprecation"] == f"@{int(DEP.timestamp())}"
    assert r.headers["sunset"] == "Tue, 01 Dec 2026 00:00:00 GMT"
    assert (
        r.headers["link"]
        == '<https://m.example/x>; rel="deprecation"; type="text/html"'
    )


async def test_sunset_with_a_non_utc_offset_is_rendered_in_gmt(
    make_settings: MakeSettings,
) -> None:
    from datetime import timedelta, timezone

    at = datetime(2026, 12, 1, 5, 0, tzinfo=timezone(timedelta(hours=5)))
    s = make_settings(legacy_sunset_at=at, manage_mcp_url="https://m.example/x")
    r = await call(audit(s, Echo(), {"auth_path": "legacy"}))
    assert r.headers["sunset"] == "Tue, 01 Dec 2026 00:00:00 GMT"
    assert "deprecation" not in r.headers and "link" in r.headers


async def test_no_link_header_without_a_manage_url(
    make_settings: MakeSettings,
) -> None:
    """The `Link` points at where a caller replaces the key: no URL, no Link."""
    s = make_settings(legacy_deprecated_at=DEP, legacy_sunset_at=SUN)
    r = await call(audit(s, Echo(), {"auth_path": "legacy"}))
    assert "deprecation" in r.headers and "sunset" in r.headers
    assert "link" not in r.headers


async def test_no_deprecation_headers_unless_configured(
    make_settings: MakeSettings,
) -> None:
    r = await call(audit(make_settings(), Echo(), {"auth_path": "legacy"}))
    assert not {"deprecation", "sunset", "link"} & set(r.headers)


async def test_no_deprecation_headers_for_platform_or_none(
    make_settings: MakeSettings,
) -> None:
    s = make_settings(legacy_deprecated_at=DEP, legacy_sunset_at=SUN)
    for claims in ({"auth_path": "platform", "user_id": "u"}, None):
        r = await call(audit(s, Echo(), claims))
        assert not {"deprecation", "sunset", "link"} & set(r.headers)


async def test_no_deprecation_headers_or_audit_on_health(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture
) -> None:
    s = make_settings(legacy_deprecated_at=DEP, legacy_sunset_at=SUN)
    with caplog.at_level(logging.INFO):
        for path in ("/health", "/health/live", "/health/ready"):
            r = await call(audit(s, Echo(), {"auth_path": "legacy"}), path=path)
            assert not {"deprecation", "sunset", "link"} & set(r.headers)
    assert events(caplog, "mcp_auth") == []
    assert events(caplog, "http_access") == []  # INFO stays quiet for ALB probes


async def test_health_requests_are_logged_at_debug(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture
) -> None:
    """Rule 4 holds for /health too: the line exists, at DEBUG (F6)."""
    with caplog.at_level(logging.DEBUG, logger=mw.__name__):
        await call(audit(make_settings(), Echo()), path="/health/ready", method="GET")
    (line,) = events(caplog, "http_access")
    assert (
        line.levelno == logging.DEBUG
        and line.path == "/health/ready"
        and line.status == 200
    )


@pytest.mark.parametrize(
    ("path", "method", "status"),
    [("/nope", "GET", 404), ("/mcp/", "POST", 307), ("/other", "DELETE", 405)],
)
async def test_every_non_mcp_request_gets_one_access_line(
    make_settings: MakeSettings,
    caplog: pytest.LogCaptureFixture,
    path: str,
    method: str,
    status: int,
) -> None:
    """404 probes and the trailing-slash 307 were invisible (F3, rule 4)."""
    rid = str(uuid.uuid4())
    token_ = request_id_var.set(rid)
    try:
        with caplog.at_level(logging.INFO):
            await call(
                audit(make_settings(), Echo(status=status)), path=path, method=method
            )
    finally:
        request_id_var.reset(token_)
    (line,) = events(caplog, "http_access")
    assert line.levelno == logging.INFO
    assert (line.path, line.method, line.status, line.request_id) == (
        path,
        method,
        status,
        rid,
    )
    assert line.client_ip == "10.0.0.1" and line.duration_ms >= 0
    assert events(caplog, "mcp_auth") == []


async def test_the_mcp_request_gets_only_the_mcp_auth_line(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        await call(audit(make_settings(), Echo(), {"auth_path": "legacy"}))
    assert len(events(caplog, "mcp_auth")) == 1 and events(caplog, "http_access") == []


async def test_access_line_path_is_one_bounded_line(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        await call(
            audit(make_settings(), Echo(status=404)), path="/a\nFORGED " + "x" * 5000
        )
    (line,) = events(caplog, "http_access")
    assert "\n" not in line.path and len(line.path) <= 200 and line.path.endswith("...")


# --------------------------------------------------------------- audit line


async def test_one_audit_line_per_mcp_request(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture
) -> None:
    s = make_settings()
    app = audit(s, Echo(), {"auth_path": "platform", "user_id": "u-1"})
    with caplog.at_level(logging.INFO):
        await call(app, headers={"x-forwarded-for": "9.9.9.9"})
        await call(app)
    lines = events(caplog, "mcp_auth")
    assert len(lines) == 2
    first = lines[0]
    assert first.levelno == logging.INFO
    assert (first.auth_path, first.user_id, first.status) == ("platform", "u-1", 200)
    assert (first.method, first.path, first.client_ip) == ("POST", "/mcp", "9.9.9.9")
    assert isinstance(first.duration_ms, float)


async def test_legacy_audit_line_carries_key_fp(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture
) -> None:
    app = audit(make_settings(), Echo(), {"auth_path": "legacy", "key_fp": "abcd1234"})
    with caplog.at_level(logging.INFO):
        await call(app)
    (line,) = events(caplog, "mcp_auth")
    assert (line.auth_path, line.key_fp) == ("legacy", "abcd1234")


async def test_audit_logs_429_status(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture, fake_redis: FakeRedis
) -> None:
    s = make_settings(default_rate_limit_per_user=1)
    inner = mw.RateLimitMiddleware(Echo(), settings=s, redis=fake_redis)
    app = audit(s, inner, {"auth_path": "platform", "user_id": "u-429"})
    with caplog.at_level(logging.INFO):
        assert (await call(app)).status == 200
        assert (await call(app)).status == 429
    assert [r.status for r in events(caplog, "mcp_auth")] == [200, 429]


async def test_audit_line_is_written_even_when_the_app_raises(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture
) -> None:
    async def boom(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("x")

    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError):
        await call(audit(make_settings(), boom))
    assert [r.status for r in events(caplog, "mcp_auth")] == [500]


async def test_audit_line_carries_the_request_id(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture
) -> None:
    rid = str(uuid.uuid4())
    token_ = request_id_var.set(rid)
    try:
        with caplog.at_level(logging.INFO):
            await call(audit(make_settings(), Echo()))
    finally:
        request_id_var.reset(token_)
    (line,) = events(caplog, "mcp_auth")
    assert (line.auth_path, line.request_id) == ("none", rid)


# -------------------------------------------------------------- failure alarm


def test_failure_alarm_fires_once_per_crossing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    alarm = mw.FailureAlarm()
    with caplog.at_level(logging.WARNING):
        results = [alarm.record("1.2.3.4") for _ in range(21)]
    assert results.count(True) == 1 and results[19] is True  # the 20th failure crosses
    (line,) = events(caplog, "auth_failure_spray")
    assert (line.client_ip, line.threshold, line.window_seconds) == (
        "1.2.3.4",
        20,
        300.0,
    )


def test_failure_alarm_window_expires_and_can_fire_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    alarm = mw.FailureAlarm(threshold=2, window_s=10)
    assert [alarm.record("a"), alarm.record("a")] == [False, True]
    clock[0] = 11
    assert [alarm.record("a"), alarm.record("a")] == [False, True]


def test_failure_alarm_bounded_memory() -> None:
    alarm = mw.FailureAlarm(max_ips=100)
    for i in range(1000):
        alarm.record(f"10.0.{i // 250}.{i % 250}")
    assert len(alarm._hits) <= 100
    assert len(alarm._armed) <= 100


def test_failure_alarm_bounds_the_entries_per_ip_too() -> None:
    alarm = mw.FailureAlarm(threshold=20)
    for _ in range(5_000):
        alarm.record("1.2.3.4")
    (hits,) = alarm._hits.values()
    assert len(hits) <= 20


def test_failure_alarm_record_is_constant_time_for_one_noisy_ip() -> None:
    """100,000 garbage-token 401s from one IP: was quadratic (111 s), now linear."""

    def record(n: int) -> int:
        alarm = mw.FailureAlarm()
        return sum(alarm.record("1.2.3.4") for _ in range(n))

    assert_grows_at_most(
        lambda n: n, record, 20_000, 3.0, runs=7
    )  # x2 linear, x4 quadratic
    fired = record(100_000)
    assert fired == 1  # one crossing, then silence while the burst lasts


def test_failure_alarm_eviction_forgets_the_armed_flag() -> None:
    alarm = mw.FailureAlarm(threshold=1, max_ips=1)
    assert alarm.record("1.1.1.1") is True
    assert alarm.record("2.2.2.2") is True  # evicts 1.1.1.1 and its armed flag
    assert alarm._armed == {"2.2.2.2"}
    assert alarm.record("1.1.1.1") is True  # a forgotten client can alarm again


def test_failure_alarm_ipv6_clients_in_one_64_share_a_counter() -> None:
    alarm = mw.FailureAlarm(threshold=3)
    assert [alarm.record(f"2001:db8:1:2::{i}") for i in range(1, 4)] == [
        False,
        False,
        True,
    ]


def test_failure_alarm_handles_no_ip() -> None:
    alarm = mw.FailureAlarm(threshold=2)
    assert [alarm.record(None), alarm.record(None)] == [False, True]


async def test_audit_feeds_the_alarm_on_401_only(make_settings: MakeSettings) -> None:
    s = make_settings()
    app = audit(s, Echo(status=401))
    for _ in range(19):
        await call(app)
    assert app.alarm.record("10.0.0.1") is True  # the 20th failure from 10.0.0.1
    ok = audit(s, Echo(status=200))
    for _ in range(30):
        await call(ok)
    assert ok.alarm._hits == {} or len(ok.alarm._hits) == 0


@pytest.mark.parametrize("status", [403, 429, 400, 500])
async def test_only_a_401_feeds_the_spray_alarm(
    make_settings: MakeSettings, status: int
) -> None:
    app = audit(make_settings(), Echo(status=status))
    for _ in range(30):
        await call(app)
    assert len(app.alarm._hits) == 0


# ------------------------------------------------------------- rate limiting


def limiter(
    s: Settings,
    redis: object | None,
    app: ASGIApp | None = None,
    claims: dict[str, Any] | None = None,
) -> ASGIApp:
    inner = mw.RateLimitMiddleware(
        app or Echo(), settings=s, redis=cast(Redis | None, redis)
    )
    return with_user(inner, claims)


async def test_platform_bucket_429_problem_json(
    make_settings: MakeSettings, fake_redis: FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    s = make_settings(default_rate_limit_per_user=2)
    echo = Echo()
    app = limiter(s, fake_redis, echo, {"auth_path": "platform", "user_id": "u-1"})
    rid = str(uuid.uuid4())
    tok = request_id_var.set(rid)
    try:
        await call(app)
        await call(app)
        with caplog.at_level(logging.WARNING):
            r = await call(app)
    finally:
        request_id_var.reset(tok)
    assert echo.calls == 2  # the inner app was NOT called for the refused request
    assert r.status == 429
    assert r.headers["content-type"] == "application/problem+json"
    body = json.loads(r.body)
    assert set(body) == FIELDS
    assert (body["type"], body["title"], body["status"]) == (
        "/problems/rate-limited",
        "Rate Limited",
        429,
    )
    assert (body["detail"], body["instance"], body["request_id"]) == (
        "Rate limit exceeded",
        "/mcp",
        rid,
    )
    assert TS_RE.match(body["timestamp"])
    assert int(r.headers["retry-after"]) >= 1
    assert r.headers["x-request-id"] == rid
    for prefix in ("ratelimit", "x-ratelimit"):
        assert r.headers[f"{prefix}-limit"] == "2"
        assert r.headers[f"{prefix}-remaining"] == "0"
        assert int(r.headers[f"{prefix}-reset"]) >= 1
    (line,) = events(caplog, "rate_limited")
    assert line.levelno == logging.WARNING
    assert (line.auth_path, line.user_id, line.limit) == ("platform", "u-1", 2)
    assert not hasattr(line, "client_ip")  # R3 F3: a user-scope refusal carries no IP
    assert line.retry_after_s == int(r.headers["retry-after"])


async def test_429_request_id_is_a_uuid4_even_without_the_outer_middleware(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings(default_rate_limit_per_user=1)
    app = limiter(s, fake_redis, claims={"auth_path": "platform", "user_id": "u-x"})
    await call(app)
    r = await call(app)
    rid = json.loads(r.body)["request_id"]
    assert uuid.UUID(rid).version == 4 and r.headers["x-request-id"] == rid


async def test_success_carries_ratelimit_headers(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings(default_rate_limit_per_user=5)
    app = limiter(s, fake_redis, claims={"auth_path": "platform", "user_id": "u-2"})
    r = await call(app)
    assert r.status == 200 and "retry-after" not in r.headers
    for prefix in ("ratelimit", "x-ratelimit"):
        assert r.headers[f"{prefix}-limit"] == "5"
        assert r.headers[f"{prefix}-remaining"] == "4"
        assert int(r.headers[f"{prefix}-reset"]) >= 1


async def test_claim_rate_limit_overrides_default(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings(default_rate_limit_per_user=100)
    app = limiter(
        s,
        fake_redis,
        claims={"auth_path": "platform", "user_id": "u-3", "rate_limit": 1},
    )
    assert (await call(app)).status == 200
    assert (await call(app)).status == 429


async def test_null_claim_rate_limit_uses_the_default(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings(default_rate_limit_per_user=7)
    app = limiter(
        s,
        fake_redis,
        claims={"auth_path": "platform", "user_id": "u-4", "rate_limit": None},
    )
    assert (await call(app)).headers["ratelimit-limit"] == "7"


async def test_users_have_separate_buckets(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings(default_rate_limit_per_user=1)
    a = limiter(s, fake_redis, claims={"auth_path": "platform", "user_id": "ua"})
    b = limiter(s, fake_redis, claims={"auth_path": "platform", "user_id": "ub"})
    assert (await call(a)).status == 200
    assert (await call(b)).status == 200
    assert (await call(a)).status == 429


async def test_platform_traffic_is_also_limited_per_ip(
    make_settings: MakeSettings, fake_redis: FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    """RL5: the per-IP scope applies to platform users too, at 20 x the per-user default."""
    s = make_settings(default_rate_limit_per_user=1)
    assert mw.PLATFORM_IP_BUCKET_FACTOR == 20
    users = [
        limiter(s, fake_redis, claims={"auth_path": "platform", "user_id": f"u-ip{n}"})
        for n in range(22)
    ]
    with caplog.at_level(logging.WARNING):
        statuses = [(await call(app)).status for app in users]
    assert statuses == [200] * 20 + [429] * 2
    (first, line) = events(caplog, "rate_limited")
    assert first.limit == 20 and first.retry_after_s >= 1
    assert (line.scope, line.auth_path, line.client_ip, line.user_id) == (
        "ip",
        "platform",
        "10.0.0.1",
        "u-ip21",
    )
    # F2: the platform bucket has its OWN key; the legacy key is never touched
    assert await fake_redis.exists("rate:mcp:template:tb:pip:10.0.0.1")
    assert not await fake_redis.exists("rate:mcp:template:tb:ip:10.0.0.1")
    fresh = limiter(
        s, fake_redis, claims={"auth_path": "platform", "user_id": "u-elsewhere"}
    )
    assert (
        await call(fresh, client=("10.0.0.2", 1))
    ).status == 200  # another IP, own bucket


async def test_platform_ip_capacity_follows_the_per_user_default_not_the_legacy_limit(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings(default_rate_limit_per_user=3, legacy_rate_limit_per_ip=2)
    app = limiter(s, fake_redis, claims={"auth_path": "platform", "user_id": "u-cap"})
    r = await call(app)
    assert r.headers["ratelimit-limit"] == "3"  # the user bucket is the closest limiter
    assert (
        await fake_redis.hget("rate:mcp:template:tb:pip:10.0.0.1", "tokens")
        == "59.000000000"
    )


async def test_legacy_clients_do_not_get_the_platform_refill_on_a_shared_ip(
    make_settings: MakeSettings, fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2: a platform call must not hand legacy clients on the same address its bigger refill."""
    clock = [1000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    s = make_settings(default_rate_limit_per_user=2)  # legacy cap 4, platform IP cap 40
    legacy = limiter(s, fake_redis, claims={"auth_path": "legacy"})
    platform = limiter(
        s, fake_redis, claims={"auth_path": "platform", "user_id": "u-shared"}
    )
    assert [(await call(legacy)).status for _ in range(5)] == [200] * 4 + [429]
    clock[0] += (
        10  # legacy refill: 4 per 60 s, so 0.67 tokens. The platform rate would give 6.
    )
    assert (await call(platform)).status == 200
    assert (await call(legacy)).status == 429


async def test_a_user_refusal_spends_no_ip_token(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings(default_rate_limit_per_user=1)
    app = limiter(s, fake_redis, claims={"auth_path": "platform", "user_id": "u-spare"})
    assert (await call(app)).status == 200
    for _ in range(10):
        assert (await call(app)).status == 429  # the user bucket is empty
    # the shared IP bucket only paid for the one allowed call
    assert (
        await fake_redis.hget("rate:mcp:template:tb:pip:10.0.0.1", "tokens")
        == "19.000000000"
    )


# The CI gate fails on a skipped test, so the real-Redis arm exists only when
# `MCP_TEMPLATE_TEST_REDIS_URL` names one (for example redis://localhost:6393/0); it is never skipped.
REAL_REDIS_URL = os.environ.get("MCP_TEMPLATE_TEST_REDIS_URL")


@pytest.fixture(params=["fakeredis", *(["real"] if REAL_REDIS_URL else [])])
async def scenario_redis(request: pytest.FixtureRequest, fake_redis: FakeRedis) -> Any:
    """fakeredis always; a real Redis too when `MCP_TEMPLATE_TEST_REDIS_URL` is set."""
    if request.param == "fakeredis":
        yield fake_redis
        return
    assert REAL_REDIS_URL
    client = Redis.from_url(REAL_REDIS_URL, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


async def test_a_runaway_user_does_not_starve_a_polite_colleague_behind_the_same_ip(
    make_settings: MakeSettings, scenario_redis: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F1: the runaway hammers 5 req/s for 3 minutes, the polite user sends 1 per 20 s.

    With the IP bucket taken first (the old order) every refused runaway request still
    spent a shared IP token, the bucket (80 per minute) ran dry within seconds, and the
    polite user got 429s though they never exceeded their own limit.
    """
    clock = [1000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    s = make_settings(default_rate_limit_per_user=4)  # user 4/min, shared IP 80/min
    runaway = limiter(
        s, scenario_redis, claims={"auth_path": "platform", "user_id": "u-run"}
    )
    polite = limiter(
        s, scenario_redis, claims={"auth_path": "platform", "user_id": "u-polite"}
    )
    polite_statuses: list[int] = []
    runaway_allowed = 0
    for step in range(900):  # 0.2 s per step, 180 s
        if (await call(runaway)).status == 200:
            runaway_allowed += 1
        if step % 100 == 0:  # every 20 s
            polite_statuses.append((await call(polite)).status)
        clock[0] += 0.2
    assert polite_statuses == [200] * 9
    assert runaway_allowed <= 4 + 4 * 3 + 1  # still contained by its OWN limit


async def test_headers_show_the_limiter_closest_to_exhaustion(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings(
        default_rate_limit_per_user=2
    )  # user claim below: 20; IP bucket: 40
    for n in range(19):  # 19 colleagues take 38 of the 40 IP tokens
        other = limiter(
            s, fake_redis, claims={"auth_path": "platform", "user_id": f"u-o{n}"}
        )
        assert [(await call(other)).status for _ in range(2)] == [200, 200]
    app = limiter(
        s,
        fake_redis,
        claims={"auth_path": "platform", "user_id": "u-hdr", "rate_limit": 20},
    )
    r = await call(app)  # user bucket: 19 left; IP bucket: 1 left
    assert (r.headers["ratelimit-limit"], r.headers["ratelimit-remaining"]) == (
        "40",
        "1",
    )
    fresh = limiter(
        s,
        fake_redis,
        claims={"auth_path": "platform", "user_id": "u-hdr2", "rate_limit": 20},
    )
    r2 = await call(
        fresh, client=("10.0.0.9", 1)
    )  # fresh IP: the user bucket is closer
    assert (r2.headers["ratelimit-limit"], r2.headers["ratelimit-remaining"]) == (
        "20",
        "19",
    )


async def test_a_huge_backend_rate_limit_claim_is_clamped_to_the_ceiling(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    """RL7: a claim of 10**9 must not switch the limiter off."""
    s = make_settings(default_rate_limit_per_user=5)
    ceiling = mw.RATE_LIMIT_CLAIM_CEILING_FACTOR * 5
    app = limiter(
        s,
        fake_redis,
        claims={"auth_path": "platform", "user_id": "u-big", "rate_limit": 10**9},
    )
    assert (await call(app)).headers["ratelimit-limit"] == str(ceiling)
    small = limiter(
        s,
        fake_redis,
        claims={"auth_path": "platform", "user_id": "u-sm", "rate_limit": 3},
    )
    assert (await call(small)).headers[
        "ratelimit-limit"
    ] == "3"  # below the ceiling: honoured


@pytest.mark.parametrize("claim", [True, False])
async def test_a_boolean_rate_limit_claim_is_not_a_number(
    make_settings: MakeSettings, fake_redis: FakeRedis, claim: bool
) -> None:
    """`True` is an int in Python: a backend `rate_limit: true` must not become capacity 1."""
    s = make_settings(default_rate_limit_per_user=7)
    app = limiter(
        s,
        fake_redis,
        claims={"auth_path": "platform", "user_id": "u-bool", "rate_limit": claim},
    )
    assert (await call(app)).headers["ratelimit-limit"] == "7"


async def test_legacy_limited_per_ip_at_twice_default(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings(default_rate_limit_per_user=2)
    assert s.legacy_rate_limit_per_ip == 4
    app = limiter(s, fake_redis, claims={"auth_path": "legacy"})
    for _ in range(4):
        assert (await call(app, client=("8.8.8.8", 1))).status == 200
    r = await call(app, client=("8.8.8.8", 1))
    assert r.status == 429 and r.headers["ratelimit-limit"] == "4"
    assert (
        await call(app, client=("8.8.4.4", 1))
    ).status == 200  # another IP, own bucket


async def test_forged_xff_prefix_does_not_change_the_bucket(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings(
        default_rate_limit_per_user=1
    )  # legacy: 2 per IP, one trusted hop
    app = limiter(s, fake_redis, claims={"auth_path": "legacy"})
    statuses = []
    for i in range(3):
        forged = (
            f"6.6.6.{i}, 203.0.113.9"  # the ALB appended the real client on the right
        )
        r = await call(app, headers={"x-forwarded-for": forged})
        statuses.append(r.status)
    assert statuses == [200, 200, 429]


async def test_ipv6_clients_in_one_64_share_a_bucket(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings(default_rate_limit_per_user=1)
    app = limiter(s, fake_redis, claims={"auth_path": "legacy"})
    statuses = [
        (await call(app, client=(f"2001:db8:1:2::{i}", 1))).status for i in range(1, 4)
    ]
    assert statuses == [200, 200, 429]
    assert (
        await call(app, client=("2001:db8:1:3::1", 1))
    ).status == 200  # a different /64
    assert await fake_redis.exists("rate:mcp:template:tb:ip:2001:db8:1:2::/64") == 1


async def test_no_client_ip_uses_the_unknown_bucket(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings(default_rate_limit_per_user=1)
    app = limiter(s, fake_redis, claims={"auth_path": "legacy"})
    assert (await call(app, client=None)).status == 200
    assert await fake_redis.exists("rate:mcp:template:tb:ip:unknown") == 1


async def test_none_auth_path_not_limited(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings(default_rate_limit_per_user=1)
    echo = Echo(status=401)
    app = limiter(s, fake_redis, echo, claims=None)
    for _ in range(10):
        assert (await call(app)).status == 401
    assert echo.calls == 10 and await fake_redis.dbsize() == 0


async def test_redis_none_skips_limit(make_settings: MakeSettings) -> None:
    s = make_settings(default_rate_limit_per_user=1)
    app = limiter(s, None, claims={"auth_path": "platform", "user_id": "u"})
    for _ in range(5):
        r = await call(app)
        assert r.status == 200 and "ratelimit-limit" not in r.headers


async def test_only_the_mcp_path_is_limited(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings(default_rate_limit_per_user=1)
    app = limiter(s, fake_redis, claims={"auth_path": "platform", "user_id": "u"})
    for _ in range(5):
        assert (await call(app, path="/health")).status == 200
    assert await fake_redis.dbsize() == 0


async def test_non_http_scope_passes_through(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    seen: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(_m: Message) -> None:
        return None

    limiters: list[ASGIApp] = [
        mw.RateLimitMiddleware(
            app, settings=make_settings(), redis=cast(Redis, fake_redis)
        ),
        mw.AuthAuditMiddleware(app, settings=make_settings()),
        mw.BodySizeLimitMiddleware(app, settings=make_settings()),
    ]
    for middleware in limiters:
        await middleware({"type": "lifespan"}, receive, send)
    assert seen == ["lifespan"] * 3


async def test_redis_error_does_not_break_a_request(
    make_settings: MakeSettings,
) -> None:
    import redis.exceptions

    class Broken:
        def register_script(self, *_a: Any) -> Any:
            async def run(*_a: Any, **_k: Any) -> None:
                raise redis.exceptions.ConnectionError("down")

            return run

    from fast_mcp_template.limits import ratelimit

    ratelimit._LOCAL_BUCKETS.clear()
    s = make_settings(default_rate_limit_per_user=1)
    app = limiter(s, Broken(), claims={"auth_path": "platform", "user_id": "u-broken"})
    assert (await call(app)).status == 200  # fail open on the first token
    assert (await call(app)).status == 429  # NOT unlimited (S15)
    ratelimit._LOCAL_BUCKETS.clear()


# ------------------------------------------------------------ tool-call audit


def _ctx(name: str) -> Any:
    """A stand-in for fastmcp's MiddlewareContext: only `.message.name` is read."""
    return SimpleNamespace(message=SimpleNamespace(name=name))


async def test_audit_line_carries_tool_name(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        audit_module, "get_access_token", lambda: token("platform", user_id="u-9")
    )

    async def call_next(_ctx: Any) -> Any:
        return "result"

    rid = str(uuid.uuid4())
    tok = request_id_var.set(rid)
    try:
        with caplog.at_level(logging.INFO):
            out = await mw.ToolCallAuditMiddleware().on_call_tool(
                _ctx("list_projects"), cast(Any, call_next)
            )
    finally:
        request_id_var.reset(tok)
    assert cast(Any, out) == "result"
    (line,) = events(caplog, "mcp_tool_call")
    assert line.levelno == logging.INFO
    assert (line.tool, line.auth_path, line.user_id, line.outcome) == (
        "list_projects",
        "platform",
        "u-9",
        "ok",
    )
    assert line.request_id == rid
    assert not hasattr(line, "key_fp")


async def test_tool_call_audit_legacy_carries_key_fp_and_error_outcome(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        audit_module, "get_access_token", lambda: token("legacy", key_fp="deadbeef")
    )

    async def call_next(_ctx: Any) -> Any:
        raise ValueError("tool blew up")

    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        await mw.ToolCallAuditMiddleware().on_call_tool(
            _ctx("get_x"), cast(Any, call_next)
        )
    (line,) = events(caplog, "mcp_tool_call")
    assert (line.auth_path, line.key_fp, line.outcome) == (
        "legacy",
        "deadbeef",
        "error",
    )


async def test_tool_call_audit_without_a_token(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit_module, "get_access_token", lambda: None)

    async def call_next(_ctx: Any) -> Any:
        return 1

    with caplog.at_level(logging.INFO):
        await mw.ToolCallAuditMiddleware().on_call_tool(_ctx("t"), cast(Any, call_next))
    (line,) = events(caplog, "mcp_tool_call")
    assert line.auth_path == "none"


# ------------------------------------------------------------ body size limit


def sized(s: Settings, app: ASGIApp | None = None) -> ASGIApp:
    return cast(ASGIApp, mw.BodySizeLimitMiddleware(app or Echo(), settings=s))


async def test_oversized_body_413_problem_json(make_settings: MakeSettings) -> None:
    s = make_settings(max_request_body_bytes=1024)
    echo = Echo()
    r = await call(sized(s, echo), headers={"content-length": "1025"}, body=b"x" * 1025)
    assert r.status == 413 and echo.calls == 0  # the inner app never ran
    assert r.headers["content-type"] == "application/problem+json"
    body = json.loads(r.body)
    assert set(body) == FIELDS
    assert (body["type"], body["title"], body["status"]) == (
        "/problems/payload-too-large",
        "Payload Too Large",
        413,
    )
    assert body["instance"] == "/mcp" and uuid.UUID(body["request_id"]).version == 4
    assert TS_RE.match(body["timestamp"])


async def test_body_at_limit_passes(make_settings: MakeSettings) -> None:
    s = make_settings(max_request_body_bytes=1024)
    echo = Echo()
    r = await call(sized(s, echo), headers={"content-length": "1024"}, body=b"x" * 1024)
    assert r.status == 200 and echo.calls == 1


class Reader:
    """Inner app that drains the body like a real endpoint."""

    def __init__(self) -> None:
        self.read = 0
        self.completed = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            m = await receive()
            if m["type"] != "http.request":
                break
            self.read += len(m["body"])
            if not m.get("more_body"):
                break
        self.completed = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


async def test_chunked_body_over_limit_413(make_settings: MakeSettings) -> None:
    s = make_settings(max_request_body_bytes=1024)
    reader = Reader()
    chunks = [b"x" * 600, b"x" * 600, b"x" * 600]
    r = await call(sized(s, reader), chunks=chunks)  # no Content-Length
    assert (
        r.status == 413 and json.loads(r.body)["type"] == "/problems/payload-too-large"
    )
    assert (
        reader.completed is False and reader.read <= 600
    )  # it never saw the third chunk


async def test_chunked_body_at_limit_passes(make_settings: MakeSettings) -> None:
    s = make_settings(max_request_body_bytes=1024)
    reader = Reader()
    r = await call(sized(s, reader), chunks=[b"x" * 512, b"x" * 512])
    assert r.status == 200 and reader.read == 1024


async def test_413_wins_when_the_app_swallows_the_error_and_answers_400(
    make_settings: MakeSettings,
) -> None:
    async def swallowing(scope: Scope, receive: Receive, send: Send) -> None:
        try:
            while (await receive()).get("more_body"):
                pass
        except Exception:
            await send({"type": "http.response.start", "status": 400, "headers": []})
            await send({"type": "http.response.body", "body": b"parse error"})

    s = make_settings(max_request_body_bytes=1024)
    r = await call(sized(s, swallowing), chunks=[b"x" * 600, b"x" * 600])
    assert r.status == 413 and b"parse error" not in r.body


async def test_body_limit_applies_to_every_path(make_settings: MakeSettings) -> None:
    s = make_settings(max_request_body_bytes=1024)
    r = await call(sized(s), path="/health", headers={"content-length": "5000"})
    assert r.status == 413


async def test_junk_content_length_is_ignored(make_settings: MakeSettings) -> None:
    s = make_settings(max_request_body_bytes=1024)
    r = await call(sized(s), headers={"content-length": "abc"})
    assert r.status == 200


# --------------------------------------------------------------- the list


def test_build_http_middleware_order(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    s = make_settings()
    built = mw.build_http_middleware(s, fake_redis)
    assert [cast(Any, m).cls for m in built] == [
        mw.BodySizeLimitMiddleware,  # the audit layer is NOT in this list (R3 F1)
        mw.RateLimitMiddleware,
    ]
    assert cast(Any, built[1]).kwargs == {"settings": s, "redis": fake_redis}
    assert cast(Any, built[0]).kwargs == {"settings": s}


def built_stack(s: Settings, redis: object, app: ASGIApp) -> ASGIApp:
    """The real middleware list wrapped around `app`, outermost first."""
    for m in reversed(mw.build_http_middleware(s, cast(Redis, redis))):
        app = cast(Any, m).cls(app, *cast(Any, m).args, **cast(Any, m).kwargs)
    return cast(
        ASGIApp, mw.wrap_http_app(app, s)
    )  # the audit layer wraps everything (R3 F1)


@pytest.mark.parametrize("path", ["/mcp", "/nope"])
@pytest.mark.parametrize("chunked", [False, True])
async def test_oversized_body_gets_one_access_line_with_413(
    make_settings: MakeSettings,
    fake_redis: FakeRedis,
    caplog: pytest.LogCaptureFixture,
    path: str,
    chunked: bool,
) -> None:
    """F3: declared and chunked 413s on the MCP path and another path: one line, status 413."""
    s = make_settings(max_request_body_bytes=1024)
    app = with_user(
        built_stack(s, fake_redis, Reader()), {"auth_path": "platform", "user_id": "u"}
    )
    with caplog.at_level(logging.DEBUG, logger="fast_mcp_template"):
        if chunked:
            r = await call(app, path=path, chunks=[b"x" * 600, b"x" * 600, b"x" * 600])
        else:
            r = await call(app, path=path, headers={"content-length": "5000"})
    assert r.status == 413
    lines = events(caplog, "mcp_auth") + events(caplog, "http_access")
    assert len(lines) == 1
    assert lines[0].status == 413 and lines[0].event == (
        "mcp_auth" if path == "/mcp" else "http_access"
    )


async def test_tool_name_is_one_bounded_line(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 10 KB attacker-chosen tool name with a newline must not forge a line."""
    monkeypatch.setattr(
        audit_module, "get_access_token", lambda: token("platform", user_id="u-9")
    )

    async def call_next(_ctx: Any) -> Any:
        return "result"

    evil = "x\nFORGED line " + "A" * 10_000
    with caplog.at_level(logging.INFO):
        await mw.ToolCallAuditMiddleware().on_call_tool(
            _ctx(evil), cast(Any, call_next)
        )
    (line,) = events(caplog, "mcp_tool_call")
    assert "\n" not in line.tool and len(line.tool) <= 256 and line.tool.endswith("...")


@pytest.mark.parametrize("path", ["/mcp", "/nope"])
async def test_a_huge_http_method_is_bounded_in_the_log_line(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture, path: str
) -> None:
    """R3 F2d: the method is client text; it is cleaned and cut like the path."""

    async def ok(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = audit(make_settings(), ok)
    with caplog.at_level(logging.DEBUG, logger="fast_mcp_template"):
        await call(app, method="M" * 16000, path=path)
    (rec,) = [
        cast(Any, r)
        for r in caplog.records
        if getattr(r, "event", None) in ("mcp_auth", "http_access")
    ]
    assert rec.method == "M" * 13 + "..."


async def test_platform_request_without_a_user_id_is_limited_per_ip_only(
    make_settings: MakeSettings, fake_redis: FakeRedis
) -> None:
    """R3 F3: the IP-only branch uses the platform IP key at 20 x the per-user default."""
    s = make_settings(default_rate_limit_per_user=3)
    app = limiter(s, fake_redis, claims={"auth_path": "platform"})
    r = await call(app)
    assert r.status == 200 and r.headers["ratelimit-limit"] == "60"
    assert (
        await fake_redis.hget("rate:mcp:template:tb:pip:10.0.0.1", "tokens")
        == "59.000000000"
    )
    assert not await fake_redis.exists("rate:mcp:template:tb:ip:10.0.0.1")
    assert not [k async for k in fake_redis.scan_iter("rate:mcp:template:tb:user:*")]


@pytest.mark.parametrize(("hops", "warned"), [(0, 0), (1, 0), (2, 1), (5, 1)])
def test_wrap_http_app_warns_when_trusted_proxy_hops_is_above_one(
    make_settings: MakeSettings,
    caplog: pytest.LogCaptureFixture,
    hops: int,
    warned: int,
) -> None:
    async def noop(scope: Scope, receive: Receive, send: Send) -> None:
        return None

    with caplog.at_level(logging.WARNING, logger="fast_mcp_template"):
        mw.wrap_http_app(noop, make_settings(trusted_proxy_hops=hops))
    lines = events(caplog, "trusted_proxy_hops_high")
    assert len(lines) == warned
    assert all(
        r.levelno == logging.WARNING and r.trusted_proxy_hops == hops for r in lines
    )


# ------------------------------------------------------------ R4 tidy-ups


async def test_a_client_that_disconnects_before_the_response_is_logged_as_499(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture
) -> None:
    """R4 F1: a cancelled request that sent nothing is not a server error."""
    gate = asyncio.Event()

    async def slow(scope: Scope, receive: Receive, send: Send) -> None:
        await gate.wait()

    task = asyncio.create_task(call(audit(make_settings(), slow)))
    await asyncio.sleep(0)
    with caplog.at_level(logging.INFO):
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert [r.status for r in events(caplog, "mcp_auth")] == [499]


async def test_a_cancel_after_the_response_started_keeps_its_status(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture
) -> None:
    async def half(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise asyncio.CancelledError

    with caplog.at_level(logging.INFO), pytest.raises(asyncio.CancelledError):
        await call(audit(make_settings(), half))
    assert [r.status for r in events(caplog, "mcp_auth")] == [200]


@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
async def test_non_http_scopes_pass_through_the_audit_layer_untouched(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture, scope_type: str
) -> None:
    """R4 F3: no bogus access line at startup, and the inner app is called."""
    inner = Echo()
    app = mw.wrap_http_app(inner, make_settings())

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(_m: Message) -> None:
        return None

    with caplog.at_level(logging.DEBUG):
        await app({"type": scope_type}, receive, send)
    assert inner.calls == 1
    assert events(caplog, "http_access") == [] and events(caplog, "mcp_auth") == []


@pytest.mark.parametrize(
    "path", ["/healthz", "/healthx", "/health-probe", "/healthcheck-evil"]
)
async def test_health_lookalike_paths_log_at_info(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture, path: str
) -> None:
    """R4 F3: only /health and /health/* drop to DEBUG; a scan of /health* stays visible."""
    with caplog.at_level(logging.DEBUG, logger=mw.__name__):
        await call(audit(make_settings(), Echo()), path=path, method="GET")
    (line,) = events(caplog, "http_access")
    assert line.levelno == logging.INFO
