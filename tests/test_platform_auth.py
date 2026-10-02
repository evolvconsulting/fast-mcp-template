"""`PlatformKeyVerifier` state machine, lockout, negative cache, rate limit (§4.2(a) 1-7)."""

import asyncio
import hmac
import json
import logging
import time
import types
from collections.abc import Callable
from typing import Any, cast

import httpx2 as httpx
import pytest
from fakeredis.aioredis import FakeRedis
from pydantic import SecretStr
from redis.asyncio import Redis

from fast_mcp_template.auth import key_format
from fast_mcp_template.auth import platform as platform_auth
from fast_mcp_template.auth.platform import (
    IP_SPRAY_METRIC,
    IP_THRESHOLD,
    PREFIX_THRESHOLD,
    PlatformKeyVerifier,
    check_lockout,
    record_failure,
)
from fast_mcp_template.config import Settings
from fast_mcp_template.http import net

SERVER_KEY = "template"


MAC_LABEL = f"{SERVER_KEY}/{platform_auth._RECORD_MAC_LABEL}".encode()


def keycache_key(key_hash: str) -> str:
    return platform_auth.keycache_key(SERVER_KEY, key_hash)


def stale_key(key_hash: str) -> str:
    return platform_auth.stale_key(SERVER_KEY, key_hash)


def tombstone_key(key_hash: str) -> str:
    return platform_auth.tombstone_key(SERVER_KEY, key_hash)


def budget_key(rate_key: str | None) -> str:
    return platform_auth.budget_key(SERVER_KEY, rate_key)


IDENTITY = {
    "user_id": "11111111-1111-1111-1111-111111111111",
    "scopes": {"servers": ["template"]},
    "rate_limit": None,
}


SECRET = "rig-internal-secret-Wq4nZ8vT2xK6pL9mRb"


class FakeHttp:
    """Stand-in for the verifier's httpx client: scripted responses + call log.

    A scripted item is a Response, an Exception to raise, or an async callable run first
    (it may write to Redis, then returns the Response).
    """

    def __init__(self, *responses: Any) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def post(
        self, url: str, *, json: Any = None, headers: Any = None
    ) -> httpx.Response:
        self.calls.append({"url": url, "json": json, "headers": headers})
        result = self._responses.pop(0)
        if callable(result) and not isinstance(result, httpx.Response):
            result = await result()
        if isinstance(result, Exception):
            raise result
        return cast(httpx.Response, result)


def response(status: int, body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(status_code=status, json=body if body is not None else {})


def ok(
    key: str,
    *,
    secret: str = SECRET,
    ts: int | None = None,
    expires_at: int | None = None,
    sig: bool = True,
    **identity: Any,
) -> httpx.Response:
    """A signed validate-key 200 (M4.2, S33) for `key`."""
    ident = {**IDENTITY, **identity}
    ts = int(time.time()) if ts is None else ts
    body = {**ident, "expires_at": expires_at, "ts": ts}
    if sig:
        payload = [
            "validate-key-response",
            key_format.key_hash(key),
            ts,
            ident["user_id"],
            ident["scopes"],
            ident["rate_limit"],
            expires_at,
        ]
        body["sig"] = platform_auth._mac(secret, payload)
    return response(200, body)


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


async def get_json(redis: Any, name: str) -> Any:
    """Read a Redis string and parse it as JSON (it must exist)."""
    raw = await redis.get(name)
    assert raw is not None, name
    return json.loads(raw)


class FakeBuckets:
    """Stand-in for `ratelimit.take_token` (lane B, plan M2.13) behind `platform_auth._take_token`.

    Same contract: a Redis hash {tokens, ts(ms)} refilled at capacity/period, and a
    process-local bucket when Redis errors (S15). Phase 3 runs the real one.
    """

    def __init__(self) -> None:
        self.local: dict[str, tuple[float, float]] = {}
        self.last_call: dict[str, Any] = {}

    async def __call__(
        self, redis: Any, key: str, *, capacity: int, refill_period_s: int
    ) -> bool:
        self.last_call = {
            "key": key,
            "capacity": capacity,
            "refill_period_s": refill_period_s,
        }
        now = time.time()
        try:
            h = await redis.hgetall(key)
            tokens, ts = (
                (float(h["tokens"]), float(h["ts"]) / 1000) if h else (capacity, now)
            )
        except Exception:  # noqa: BLE001 - the local fallback
            tokens, ts = self.local.get(key, (float(capacity), now))
            h = None
        tokens = min(float(capacity), tokens + (now - ts) * capacity / refill_period_s)
        allowed = tokens >= 1
        tokens -= 1 if allowed else 0
        if h is None and not await _alive(redis):
            self.local[key] = (tokens, now)
        else:
            await redis.hset(
                key, mapping={"tokens": str(tokens), "ts": str(int(now * 1000))}
            )
        return allowed


async def _alive(redis: Any) -> bool:
    try:
        await redis.ping()
    except Exception:  # noqa: BLE001
        return False
    return True


FAKE = FakeBuckets()
REAL_TAKE_TOKEN = (
    platform_auth._take_token
)  # captured before the autouse fixture patches it


@pytest.fixture(autouse=True)
def _fake_take_token(monkeypatch: pytest.MonkeyPatch) -> None:
    FAKE.local.clear()
    monkeypatch.setattr(platform_auth, "_take_token", FAKE)


class DownRedis:
    """Every command raises, as a dead Redis does."""

    def __getattr__(self, name: str) -> Callable[..., Any]:
        async def boom(*_a: Any, **_k: Any) -> None:
            raise ConnectionError("redis is down")

        return boom


def fake_http(*responses: Any) -> httpx.AsyncClient:
    return cast(httpx.AsyncClient, FakeHttp(*responses))


def calls(verifier: PlatformKeyVerifier) -> list[dict[str, Any]]:
    return cast(FakeHttp, verifier._http).calls


def make_verifier(
    redis: Any, *responses: Any, **settings_kw: Any
) -> PlatformKeyVerifier:
    verifier = PlatformKeyVerifier(
        be_base_url="http://backend:8000/",
        internal_auth_secret=SECRET,
        redis=redis,
        settings=Settings(**settings_kw),
    )
    verifier._http = fake_http(*responses)
    return verifier


async def put_keycache(
    verifier: PlatformKeyVerifier,
    key: str,
    *,
    entry: dict[str, Any] | None = None,
    exp: float | None = None,
    purpose: str = "keycache",
    at: str | None = None,
) -> None:
    """Write a correctly sealed record straight into Redis (as a prior 200 would)."""
    h = key_format.key_hash(key)
    raw = verifier._seal(purpose, h, entry or IDENTITY, exp or time.time() + 30)
    dest = at or (keycache_key(h) if purpose == "keycache" else stale_key(h))
    await verifier.redis.set(dest, raw)


async def cache_keys(redis: FakeRedis) -> list[str]:
    """Every key except the validate-key budget buckets."""
    return [str(k) for k in await redis.keys("*") if not str(k).startswith("rate:")]


def drain_budget(redis_: FakeRedis, ip_key: str = "unknown") -> Any:
    """Empty the validate-key bucket for a client (as a spray would)."""
    return redis_.hset(
        budget_key(ip_key),
        mapping={"tokens": "0", "ts": str(int(time.time() * 1000))},
    )


@pytest.fixture
def key() -> str:
    return key_format.mint_key()


# ---------------------------------------------------------------- state machine


async def test_malformed_key_is_rejected_offline(redis: FakeRedis, key: str) -> None:
    """Step 1: no BE call, no Redis writes, and NO lockout state recorded."""
    verifier = make_verifier(
        redis
    )  # zero scripted responses: any POST would IndexError
    assert await verifier.verify_token("evc_live_not-a-real-key") is None
    assert calls(verifier) == []
    assert await redis.keys("*") == []


async def test_cache_miss_calls_the_be_and_caches_the_identity(
    redis: FakeRedis, key: str
) -> None:
    verifier = make_verifier(redis, ok(key))
    token = await verifier.verify_token(key)

    assert token is not None
    assert token.client_id == f"platform:{IDENTITY['user_id']}"
    assert token.claims == {**IDENTITY, "auth_path": "platform"}
    assert token.token == key

    call = calls(verifier)[0]
    assert call["url"] == "http://backend:8000/api/v1/internal/validate-key"
    assert call["json"] == {"key_hash": key_format.key_hash(key), "server": SERVER_KEY}
    assert call["headers"]["X-Internal-Auth"] == SECRET
    assert key not in json.dumps(call["json"]), "raw key must never leave verify_token"

    cached = await get_json(redis, keycache_key(key_format.key_hash(key)))
    assert {k: cached[k] for k in IDENTITY} == IDENTITY
    assert (
        cached["purpose"] == "keycache"
        and cached["server"] == SERVER_KEY
        and "sig" in cached
    )
    assert 0 < await redis.ttl(keycache_key(key_format.key_hash(key))) <= 30


async def test_cache_hit_short_circuits_the_be(redis: FakeRedis, key: str) -> None:
    verifier = make_verifier(redis)  # no scripted response: a BE call would raise
    await put_keycache(verifier, key)
    token = await verifier.verify_token(key)
    assert token is not None and token.claims["user_id"] == IDENTITY["user_id"]
    assert token.claims["auth_path"] == "platform"
    assert calls(verifier) == []


async def test_401_caches_denied_and_records_a_failure(
    redis: FakeRedis, key: str
) -> None:
    verifier = make_verifier(redis, response(401, {"detail": "invalid key"}))
    assert await verifier.verify_token(key) is None
    assert await redis.get(keycache_key(key_format.key_hash(key))) == "DENIED"
    assert await redis.get(f"mcp:lockout:prefix:{key_format.key_prefix(key)}") == "1"


async def test_denied_cache_hit_records_a_failure(redis: FakeRedis, key: str) -> None:
    """§4.2(a) step 4 - §7.4's NAT control false-reds without this."""
    await redis.set(keycache_key(key_format.key_hash(key)), "DENIED")
    verifier = make_verifier(redis)
    assert await verifier.verify_token(key) is None
    assert calls(verifier) == [], "a DENIED hit must not reach the BE"
    assert await redis.get(f"mcp:lockout:prefix:{key_format.key_prefix(key)}") == "1"


async def test_be_down_fails_closed(redis: FakeRedis, key: str) -> None:
    verifier = make_verifier(redis, httpx.ConnectError("connection refused"))
    assert await verifier.verify_token(key) is None
    assert await redis.get(keycache_key(key_format.key_hash(key))) is None


@pytest.mark.parametrize("status", [403, 422, 500, 503])
async def test_unexpected_status_fails_closed(
    redis: FakeRedis, key: str, status: int
) -> None:
    verifier = make_verifier(redis, response(status))
    assert await verifier.verify_token(key) is None
    assert await redis.get(keycache_key(key_format.key_hash(key))) is None


async def test_200_with_a_non_json_body_fails_closed(
    redis: FakeRedis, key: str
) -> None:
    """An HTML error page returned with 200 must land on the None rung, not raise."""
    verifier = make_verifier(
        redis, httpx.Response(200, text="<html>502 upstream</html>")
    )
    assert await verifier.verify_token(key) is None
    assert await redis.get(keycache_key(key_format.key_hash(key))) is None


@pytest.mark.parametrize(
    "body", [{"scopes": {"servers": ["template"]}}, {"user_id": "u1"}, {}]
)
async def test_200_missing_a_required_field_fails_closed(
    redis: FakeRedis, key: str, body: dict[str, Any]
) -> None:
    """BE schema drift must fail closed, not escape as a 500."""
    verifier = make_verifier(redis, response(200, body))
    assert await verifier.verify_token(key) is None
    assert await redis.get(keycache_key(key_format.key_hash(key))) is None


@pytest.mark.parametrize("poison", ['"denied"', "5", "[1,2]", "null", '{"scopes": {}}'])
async def test_poisoned_cache_entry_is_treated_as_a_miss(
    redis: FakeRedis, key: str, poison: str
) -> None:
    """A JSON-but-unusable cache entry must not raise out of verify_token."""
    await redis.set(keycache_key(key_format.key_hash(key)), poison)
    verifier = make_verifier(redis, ok(key))
    token = await verifier.verify_token(key)
    assert token is not None and token.claims["user_id"] == IDENTITY["user_id"]
    assert len(calls(verifier)) == 1, "a poisoned entry must fall through to the BE"


async def test_locked_prefix_short_circuits_before_the_be(
    redis: FakeRedis, key: str
) -> None:
    await redis.set(f"mcp:lockout:prefix:{key_format.key_prefix(key)}:locked", "1")
    verifier = make_verifier(redis, ok(key))
    assert await verifier.verify_token(key) is None
    assert calls(verifier) == [], "lockout must short-circuit before the BE"


async def test_keycache_key_is_server_segmented(key: str) -> None:
    assert keycache_key("abc") == f"mcp:keycache:{SERVER_KEY}:abc"
    assert SERVER_KEY == Settings().server_key


# ---------------------------------------------------------------- dual lockout


async def test_prefix_arm_latches_at_its_threshold(redis: FakeRedis) -> None:
    for i in range(1, PREFIX_THRESHOLD + 1):
        await record_failure(redis, None, "abcdef123456")
        latched = await check_lockout(redis, None, "abcdef123456")
        assert latched is (i >= PREFIX_THRESHOLD), f"after {i} failures"
    assert 0 < await redis.ttl("mcp:lockout:prefix:abcdef123456") <= 300
    assert 0 < await redis.ttl("mcp:lockout:prefix:abcdef123456:locked") <= 60


async def test_ip_arm_counts_and_alerts_but_never_latches(
    redis: FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    """RATIFIED 2026-07-29: the per-IP arm is ALERT-ONLY.

    A spray presents a fresh prefix each time, so only the IP arm accumulates.
    Crossing the threshold must emit the alert + metric record and MUST NOT latch.
    """
    overshoot = (
        IP_THRESHOLD + 3
    )  # past the crossing: the alert must not re-fire per attempt
    with caplog.at_level(logging.WARNING, logger="fast_mcp_template.auth.platform"):
        for i in range(1, overshoot + 1):
            await record_failure(redis, "10.1.2.3", f"prefix{i:06d}")

    assert await redis.get("mcp:lockout:ip:10.1.2.3") == str(overshoot)
    assert 0 < await redis.ttl("mcp:lockout:ip:10.1.2.3") <= 300
    # The latch key is neither written nor read (§5.3).
    assert await redis.keys("mcp:lockout:ip:*") == ["mcp:lockout:ip:10.1.2.3"]
    assert await check_lockout(redis, "10.1.2.3", "unrelated123") is False

    alerts = [
        r for r in caplog.records if getattr(r, "metric", None) == IP_SPRAY_METRIC
    ]
    assert len(alerts) == 1, "exactly one alert per window at the crossing"
    assert alerts[0].__dict__["metric_value"] == IP_THRESHOLD
    assert alerts[0].__dict__["client_ip"] == "10.1.2.3"
    assert alerts[0].__dict__["threshold"] == IP_THRESHOLD
    assert alerts[0].levelno >= logging.WARNING


async def test_ip_arm_does_not_alert_below_threshold(
    redis: FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="fast_mcp_template.auth.platform"):
        for i in range(IP_THRESHOLD - 1):
            await record_failure(redis, "10.1.2.3", f"prefix{i:06d}")
    assert await redis.get("mcp:lockout:ip:10.1.2.3") == str(IP_THRESHOLD - 1)
    assert [
        r for r in caplog.records if getattr(r, "metric", None) == IP_SPRAY_METRIC
    ] == []
    assert await check_lockout(redis, "10.1.2.3", "unrelated123") is False


async def test_a_stale_ip_latch_key_is_ignored(redis: FakeRedis) -> None:
    """Left over from a pre-ratification deploy: it must never be consulted."""
    await redis.set("mcp:lockout:ip:10.1.2.3:locked", "1")
    assert await check_lockout(redis, "10.1.2.3", "unrelated123") is False


async def test_spray_from_an_ip_alerts_but_a_valid_key_from_that_ip_still_works(
    redis: FakeRedis, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The whole point of alert-only: office NAT/VPN/CGNAT users are not collateral.

    Both halves in one test - the spray crosses the per-IP threshold AND a valid
    key presented from that same IP still authenticates.
    """
    monkeypatch.setattr(net, "current_client_ip", lambda hops: "203.0.113.7")
    sprayed = [key_format.mint_key() for _ in range(IP_THRESHOLD)]
    verifier = make_verifier(
        redis, *[response(401, {"detail": "invalid key"})] * IP_THRESHOLD
    )

    with caplog.at_level(logging.WARNING, logger="fast_mcp_template.auth.platform"):
        for bad in sprayed:
            assert await verifier.verify_token(bad) is None

    assert await redis.get("mcp:lockout:ip:203.0.113.7") == str(IP_THRESHOLD)
    assert [
        r for r in caplog.records if getattr(r, "metric", None) == IP_SPRAY_METRIC
    ] != [], "the spray crossed the threshold but no alert fired"

    good = key_format.mint_key()
    assert good not in sprayed
    verifier._http = fake_http(ok(good))
    token = await verifier.verify_token(good)
    assert token is not None, (
        "a valid key from the sprayed IP was denied - the IP latched"
    )
    assert token.claims["user_id"] == IDENTITY["user_id"]


async def test_the_prefix_arm_still_latches_under_the_same_spray_conditions(
    redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-prefix arm is UNCHANGED by the ratification: it still latches."""
    monkeypatch.setattr(net, "current_client_ip", lambda hops: "203.0.113.7")
    target = key_format.mint_key()
    verifier = make_verifier(
        redis, *[response(401, {"detail": "invalid key"})] * PREFIX_THRESHOLD
    )
    for _ in range(PREFIX_THRESHOLD):
        assert await verifier.verify_token(target) is None

    assert (
        await redis.get(f"mcp:lockout:prefix:{key_format.key_prefix(target)}:locked")
        == "1"
    )
    assert (
        await check_lockout(redis, "203.0.113.7", key_format.key_prefix(target)) is True
    )
    # And it short-circuits: the next attempt never reaches the BE.
    verifier._http = fake_http()  # any POST would IndexError
    assert await verifier.verify_token(target) is None
    assert calls(verifier) == []


async def test_lockout_helpers_fail_open_on_redis_errors() -> None:
    broken = cast(Redis, DownRedis())
    assert await check_lockout(broken, "10.1.2.3", "abcdef123456") is False
    await record_failure(broken, "10.1.2.3", "abcdef123456")  # must not raise


async def test_verify_token_still_authenticates_with_redis_down(key: str) -> None:
    """Auth fails closed on the BE, but a Redis outage must not deny a live key."""
    verifier = make_verifier(DownRedis(), ok(key))
    token = await verifier.verify_token(key)
    assert token is not None and token.claims["user_id"] == IDENTITY["user_id"]


# ------------------------------------------------- 403 on the internal hop (§4.2(a) 5)


async def test_403_fails_closed_without_caching_or_penalising_the_user(
    redis: FakeRedis,
    key: str,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RATIFIED 2026-07-29: a 403 means THIS gateway's X-Internal-Auth is wrong.

    The user's key was never judged, so it must not be negative-cached and must not
    move any lockout counter. Asserted directly against fakeredis, not via a proxy.
    """
    monkeypatch.setattr(net, "current_client_ip", lambda hops: "203.0.113.7")
    verifier = make_verifier(redis, response(403, {"detail": "forbidden"}))

    with caplog.at_level(logging.ERROR, logger="fast_mcp_template.auth.platform"):
        assert await verifier.verify_token(key) is None

    assert await redis.get(keycache_key(key_format.key_hash(key))) is None, (
        "must not cache DENIED"
    )
    # T-A2: the validate-key budget bucket (rate:*) is the ONLY key a 403 may leave behind
    assert await cache_keys(redis) == [], "a 403 must write no cache or lockout state"
    assert await redis.get(f"mcp:lockout:prefix:{key_format.key_prefix(key)}") is None
    assert await redis.get("mcp:lockout:ip:203.0.113.7") is None

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1, "a distinct ERROR must name the gateway misconfiguration"
    assert errors[0].__dict__["event"] == "internal_auth_misconfigured"
    assert "MISCONFIGURATION" in errors[0].getMessage()


async def test_401_is_the_contrast_case_and_still_caches_and_penalises(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control for the test above: the same shape at 401 DOES write both."""
    monkeypatch.setattr(net, "current_client_ip", lambda hops: "203.0.113.7")
    verifier = make_verifier(redis, response(401, {"detail": "invalid key"}))
    assert await verifier.verify_token(key) is None

    assert await redis.get(keycache_key(key_format.key_hash(key))) == "DENIED"
    assert await redis.get(f"mcp:lockout:prefix:{key_format.key_prefix(key)}") == "1"
    assert await redis.get("mcp:lockout:ip:203.0.113.7") == "1"


async def test_403_does_not_lock_out_a_second_valid_user(
    redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure this ratification exists to prevent: a rotated internal secret
    must not latch every user's prefix and deny them once the secret is fixed."""
    monkeypatch.setattr(net, "current_client_ip", lambda hops: "203.0.113.7")
    victim = key_format.mint_key()
    verifier = make_verifier(redis, *[response(403)] * (PREFIX_THRESHOLD + 2))
    for _ in range(PREFIX_THRESHOLD + 2):
        assert await verifier.verify_token(victim) is None

    assert await cache_keys(redis) == []
    verifier._http = fake_http(ok(victim))  # secret fixed
    assert await verifier.verify_token(victim) is not None, (
        "the key was latched by a 403 volley"
    )


# ------------------------------------------------- Arm-4 canary flag (§4.2(d))


async def test_canary_flag_is_off_by_default(
    redis: FakeRedis, key: str, caplog: pytest.LogCaptureFixture
) -> None:
    assert Settings().test_emit_canary_secret_log is False
    verifier = make_verifier(redis, ok(key))
    with caplog.at_level(logging.INFO, logger="fast_mcp_template.auth.platform"):
        platform_auth.logger.info("CAPTURE-IS-LIVE")  # positive control for the capture
        assert await verifier.verify_token(key) is not None

    assert any("CAPTURE-IS-LIVE" in r.getMessage() for r in caplog.records), (
        "capture was dead"
    )
    assert [r for r in caplog.records if "rig-internal-secret" in r.getMessage()] == []


async def test_canary_flag_emits_a_real_leak_for_the_arm4_positive_control(
    redis: FakeRedis, key: str, caplog: pytest.LogCaptureFixture
) -> None:
    verifier = make_verifier(redis, ok(key), test_emit_canary_secret_log=True)
    with caplog.at_level(logging.INFO, logger="fast_mcp_template.auth.platform"):
        assert await verifier.verify_token(key) is not None

    assert caplog.records, "nothing was captured at all"
    leaks = [r for r in caplog.records if "rig-internal-secret" in r.getMessage()]
    assert len(leaks) == 1, "exactly one deliberate canary line"
    assert leaks[0].levelno == logging.INFO


# ------------------------------------------------- T-A2: claims, rate limiting moved (R5)


async def test_platform_claims_carry_auth_path(redis: FakeRedis, key: str) -> None:
    verifier = make_verifier(redis)
    await put_keycache(verifier, key)
    token = await verifier.verify_token(key)
    assert token is not None
    assert token.claims["auth_path"] == "platform"
    assert token.client_id == f"platform:{IDENTITY['user_id']}"


async def test_authorize_does_not_rate_limit(redis: FakeRedis, key: str) -> None:
    # T-A2: rate limiting moved to ratelimit.py (R5)
    verifier = make_verifier(redis, default_rate_limit_per_user=1)
    await put_keycache(verifier, key, entry={**IDENTITY, "rate_limit": 1})
    for _ in range(500):
        assert await verifier.verify_token(key) is not None
    assert [k for k in await redis.keys("rate:*")] == [], (
        "a cache hit touches no bucket"
    )


async def test_failure_records_xff_ip(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []

    async def spy(_redis: object, ip: str | None, prefix12: str) -> None:
        seen.append(ip)

    monkeypatch.setattr(net, "current_client_ip", lambda hops: "203.0.113.7")
    monkeypatch.setattr(platform_auth, "record_failure", spy)
    verifier = make_verifier(redis, response(401))
    assert await verifier.verify_token(key) is None
    assert seen == ["203.0.113.7"]


async def test_trusted_hops_setting_reaches_the_ip_lookup(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    hops = []
    monkeypatch.setattr(net, "current_client_ip", lambda h: hops.append(h))
    verifier = make_verifier(redis, ok(key), trusted_proxy_hops=3)
    assert await verifier.verify_token(key) is not None
    assert hops == [3]


# ------------------------------------------------- S14: signed cache records


async def test_unsigned_keycache_entry_is_a_miss(redis: FakeRedis, key: str) -> None:
    await redis.set(keycache_key(key_format.key_hash(key)), json.dumps(IDENTITY))
    verifier = make_verifier(redis, ok(key))
    assert await verifier.verify_token(key) is not None
    assert len(calls(verifier)) == 1, "an unsigned entry must fall through to the BE"


async def test_entry_signed_for_another_hash_is_a_miss(
    redis: FakeRedis, key: str
) -> None:
    other = key_format.mint_key()
    verifier = make_verifier(redis, ok(key))
    raw = verifier._seal(
        "keycache", key_format.key_hash(other), IDENTITY, time.time() + 30
    )
    await redis.set(keycache_key(key_format.key_hash(key)), raw)
    assert await verifier.verify_token(key) is not None
    assert len(calls(verifier)) == 1


async def test_replayed_entry_after_exp_is_a_miss(redis: FakeRedis, key: str) -> None:
    verifier = make_verifier(redis, ok(key))
    await put_keycache(verifier, key, exp=time.time() - 1)
    assert await verifier.verify_token(key) is not None
    assert len(calls(verifier)) == 1


async def test_keycache_entry_copied_to_keyok_is_refused(
    redis: FakeRedis, key: str
) -> None:
    """A keycache record (purpose `keycache`) placed at the stale key is not served."""
    verifier = make_verifier(redis)
    stale = stale_key(key_format.key_hash(key))
    await put_keycache(verifier, key, purpose="keycache", at=stale)
    await drain_budget(redis)
    assert await verifier.verify_token(key) is None
    assert calls(verifier) == []


async def test_altered_rate_limit_is_a_miss(redis: FakeRedis, key: str) -> None:
    verifier = make_verifier(redis, ok(key))
    await put_keycache(verifier, key)
    name = keycache_key(key_format.key_hash(key))
    rec = await get_json(redis, name)
    rec["rate_limit"] = 1_000_000
    await redis.set(name, json.dumps(rec))
    token = await verifier.verify_token(key)
    assert token is not None and token.claims["rate_limit"] is None, (
        "the altered value was used"
    )
    assert len(calls(verifier)) == 1


async def test_keycache_entry_signed_with_the_previous_secret_verifies_during_overlap(
    redis: FakeRedis, key: str
) -> None:
    """S13/S14: current = B, NEXT = A. A record signed with A verifies; new ones use B only."""
    old = make_verifier(redis)  # current secret = SECRET (this is "A")
    await put_keycache(old, key)
    rotated = PlatformKeyVerifier(
        be_base_url="http://backend:8000",
        internal_auth_secret="secret-B",
        redis=redis,
        settings=Settings(internal_auth_secret_next=SecretStr(SECRET)),
    )
    rotated._http = fake_http()
    assert await rotated.verify_token(key) is not None and calls(rotated) == []

    await redis.delete(keycache_key(key_format.key_hash(key)))
    rotated._http = fake_http(ok(key, secret="secret-B"))
    assert await rotated.verify_token(key) is not None
    new = await redis.get(keycache_key(key_format.key_hash(key)))
    only_b = PlatformKeyVerifier(
        be_base_url="x",
        internal_auth_secret="secret-B",
        redis=redis,
        settings=Settings(),
    )
    only_a = make_verifier(redis)
    h = key_format.key_hash(key)
    assert only_b._open(new, "keycache", h) is not None
    assert only_a._open(new, "keycache", h) is None, (
        "a new record must be signed with B only"
    )


# ------------------------------------------------- S30: per-IP validate-key budget


def at_ip(monkeypatch: pytest.MonkeyPatch, ip: str | None) -> None:
    monkeypatch.setattr(net, "current_client_ip", lambda hops: ip)


async def test_validate_key_budget_is_per_client_ip(
    redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = [key_format.mint_key() for _ in range(4)]
    verifier = make_verifier(
        redis, *[ok(k) for k in keys], validate_key_budget_per_ip=2
    )
    at_ip(monkeypatch, "203.0.113.7")
    assert await verifier.verify_token(keys[0]) is not None
    assert await verifier.verify_token(keys[1]) is not None
    assert await verifier.verify_token(keys[2]) is None, (
        "the third miss from one IP is refused"
    )
    assert len(calls(verifier)) == 2, "an exhausted budget makes no backend call"
    at_ip(monkeypatch, "198.51.100.9")
    assert await verifier.verify_token(keys[2]) is not None, "another IP is unaffected"


async def test_cache_hit_does_not_spend_budget(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    at_ip(monkeypatch, "203.0.113.7")
    verifier = make_verifier(redis, validate_key_budget_per_ip=1)
    await put_keycache(verifier, key)
    for _ in range(5):
        assert await verifier.verify_token(key) is not None
    assert await redis.keys("rate:*") == []


async def test_known_key_survives_an_empty_budget(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    at_ip(monkeypatch, "203.0.113.7")
    verifier = make_verifier(redis, ok(key), validate_key_budget_per_ip=1)
    assert await verifier.verify_token(key) is not None  # spends the one token
    await redis.delete(
        keycache_key(key_format.key_hash(key))
    )  # the 30 s keycache lapsed
    token = await verifier.verify_token(key)
    assert token is not None and token.claims["user_id"] == IDENTITY["user_id"]
    assert len(calls(verifier)) == 1, "stale-serve makes no backend call"
    stranger = key_format.mint_key()
    assert await verifier.verify_token(stranger) is None, (
        "an unknown key gets no stale record"
    )


async def test_ipv6_clients_in_one_64_share_a_bucket(
    redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = key_format.mint_key(), key_format.mint_key()
    verifier = make_verifier(redis, ok(first), ok(second), validate_key_budget_per_ip=1)
    at_ip(monkeypatch, "2001:db8:0:1::5")
    assert await verifier.verify_token(first) is not None
    at_ip(monkeypatch, "2001:db8:0:1:ffff::9")
    assert await verifier.verify_token(second) is None
    assert await redis.keys("rate:*") == ["rate:mcp:template:tb:vk:2001:db8:0:1::/64"]


async def test_no_client_ip_uses_one_bucket(
    redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = key_format.mint_key(), key_format.mint_key()
    verifier = make_verifier(redis, ok(first), ok(second), validate_key_budget_per_ip=1)
    at_ip(monkeypatch, None)
    assert await verifier.verify_token(first) is not None
    assert await verifier.verify_token(second) is None, (
        "no IP is one shared bucket, not free"
    )
    assert await redis.keys("rate:*") == ["rate:mcp:template:tb:vk:unknown"]


async def test_budget_uses_a_local_bucket_when_redis_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither open nor closed: the same rate, enforced in-process (DESIGN 8.5)."""
    keys = [key_format.mint_key() for _ in range(3)]
    verifier = make_verifier(
        DownRedis(), *[ok(k) for k in keys], validate_key_budget_per_ip=2
    )
    at_ip(monkeypatch, "203.0.113.7")
    assert await verifier.verify_token(keys[0]) is not None
    assert await verifier.verify_token(keys[1]) is not None
    assert await verifier.verify_token(keys[2]) is None
    assert len(calls(verifier)) == 2


async def test_budget_key_is_the_m5_key_for_the_client_ip(
    redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M5: rate:mcp:template:tb:vk:{rate_key_for_ip(ip)}, for IPv4, IPv6 (/64) and no IP."""
    for ip in ("203.0.113.7", "2001:db8:0:1::5", None):
        at_ip(monkeypatch, ip)
        k = key_format.mint_key()
        verifier = make_verifier(redis, ok(k))
        assert await verifier.verify_token(k) is not None
        expected = f"rate:mcp:{SERVER_KEY}:tb:vk:{net.rate_key_for_ip(ip) or 'unknown'}"
        assert expected in await redis.keys("rate:*")
        assert (
            FAKE.last_call["capacity"] == verifier.settings.validate_key_budget_per_ip
        )
        assert FAKE.last_call["refill_period_s"] == 60


async def test_a_failing_budget_seam_refuses_and_makes_no_backend_call(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_a: Any, **_k: Any) -> bool:
        raise RuntimeError("ratelimit module missing")

    monkeypatch.setattr(platform_auth, "_take_token", boom)
    verifier = make_verifier(redis, ok(key))
    assert await verifier.verify_token(key) is None
    assert calls(verifier) == []


# ------------------------------------------------- S6: revocation-safe stale-serve


async def test_revoked_tombstone_blocks_stale_serve(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    at_ip(monkeypatch, "203.0.113.7")
    verifier = make_verifier(redis, ok(key), validate_key_budget_per_ip=1)
    assert await verifier.verify_token(key) is not None
    h = key_format.key_hash(key)
    # the backend revokes: drops the keycache entry and writes the tombstone
    await redis.delete(keycache_key(h))
    await redis.set(tombstone_key(h), "1", ex=600)
    assert await redis.exists(stale_key(h)), "a stale record still exists"
    assert await verifier.verify_token(key) is None

    # and on the stale path itself (the tombstone landing after the keycache read)
    async def missed(_h: str) -> None:
        return None

    monkeypatch.setattr(verifier, "_cache_get", missed)
    assert await verifier.verify_token(key) is None
    await redis.delete(tombstone_key(h))
    assert await verifier.verify_token(key) is not None, (
        "control: without it the record serves"
    )


async def test_stale_record_is_signed(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    at_ip(monkeypatch, "203.0.113.7")
    verifier = make_verifier(redis, response(401), validate_key_budget_per_ip=1)
    h = key_format.key_hash(key)
    assert await verifier.verify_token(key) is None
    assert not await redis.exists(stale_key(h)), "written only after a 200"

    await redis.delete(
        keycache_key(h), *await redis.keys("rate:*")
    )  # DENIED and budget lapse
    signed = make_verifier(redis, ok(key), validate_key_budget_per_ip=2)
    assert await signed.verify_token(key) is not None
    await redis.delete(keycache_key(h))
    await drain_budget(redis, "203.0.113.7")
    name = stale_key(h)
    good = await get_json(redis, name)
    assert await signed.verify_token(key) is not None, (
        "control: the intact record serves"
    )
    for tampered in (
        json.dumps(IDENTITY),  # unsigned
        json.dumps({**good, "sig": "0" * 64}),  # wrong signature
        json.dumps({**good, "user_id": "someone-else"}),  # altered body
    ):
        await redis.set(name, tampered)
        assert await signed.verify_token(key) is None


async def test_backend_401_deletes_the_stale_record(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    at_ip(monkeypatch, "203.0.113.7")
    verifier = make_verifier(redis, ok(key), response(401))
    h = key_format.key_hash(key)
    assert await verifier.verify_token(key) is not None
    assert await redis.exists(stale_key(h))
    await redis.delete(keycache_key(h))
    assert await verifier.verify_token(key) is None
    assert not await redis.exists(stale_key(h))
    assert await redis.get(keycache_key(h)) == "DENIED"
    await redis.delete(keycache_key(h))  # DENIED expired
    await drain_budget(redis, "203.0.113.7")
    assert await verifier.verify_token(key) is None, "the empty-budget path must refuse"


async def test_tombstone_blocks_a_keycache_hit(redis: FakeRedis, key: str) -> None:
    verifier = make_verifier(redis)
    await put_keycache(verifier, key)
    await redis.set(tombstone_key(key_format.key_hash(key)), "1")
    assert await verifier.verify_token(key) is None
    assert calls(verifier) == []


async def test_tombstone_read_error_on_a_keycache_hit_is_a_miss(
    redis: FakeRedis, key: str
) -> None:
    class MgetDown(FakeRedis):
        async def mget(self, *a: Any, **k: Any) -> Any:
            raise ConnectionError("redis is down")

    r = MgetDown(decode_responses=True)
    verifier = make_verifier(r, ok(key))
    await put_keycache(verifier, key)
    assert await verifier.verify_token(key) is not None
    assert len(calls(verifier)) == 1, "the hit became a miss and revalidated"


async def test_tombstone_read_error_refuses_stale_serve(
    key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TombstoneReadFails(FakeRedis):
        broken = False

        async def mget(self, *names: Any) -> Any:
            if self.broken and any(str(n).startswith("mcp:revoked:") for n in names):
                raise ConnectionError("redis is down")
            return await super().mget(*names)

    r = TombstoneReadFails(decode_responses=True)
    at_ip(monkeypatch, "203.0.113.7")
    verifier = make_verifier(r, ok(key), validate_key_budget_per_ip=1)
    assert await verifier.verify_token(key) is not None
    await r.delete(keycache_key(key_format.key_hash(key)))
    r.broken = True
    assert await verifier.verify_token(key) is None, (
        "an unreadable tombstone must refuse"
    )
    r.broken = False
    assert await verifier.verify_token(key) is not None, "control: readable, it serves"


async def test_stale_record_not_written_after_a_tombstone(
    redis: FakeRedis, key: str
) -> None:
    """The in-flight race: the tombstone lands between the backend's 200 and our write."""
    h = key_format.key_hash(key)

    async def revoke_then_answer() -> httpx.Response:
        await redis.set(tombstone_key(h), "1", ex=600)
        return ok(key)

    verifier = make_verifier(redis, revoke_then_answer)
    assert await verifier.verify_token(key) is None, (
        "L2: a revoked key is not authorized"
    )
    assert not await redis.exists(keycache_key(h)) and not await redis.exists(
        stale_key(h)
    )


async def test_stale_record_exp_is_capped_by_key_expiry(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = key_format.key_hash(key)
    expires_at = int(time.time()) + 40
    verifier = make_verifier(
        redis, ok(key, expires_at=expires_at), validate_key_budget_per_ip=1
    )
    at_ip(monkeypatch, "203.0.113.7")
    assert await verifier.verify_token(key) is not None
    stale = await get_json(redis, stale_key(h))
    cache = await get_json(redis, keycache_key(h))
    assert stale["exp"] <= expires_at and cache["exp"] <= expires_at
    assert await redis.ttl(stale_key(h)) <= 40

    other = key_format.mint_key()
    await redis.delete(*await redis.keys("rate:*"))
    plain = make_verifier(redis, ok(other))
    assert await plain.verify_token(other) is not None
    rec = await get_json(redis, stale_key(key_format.key_hash(other)))
    assert abs(rec["exp"] - (time.time() + 300)) <= 3, "null expires_at keeps now + 300"

    # after the key's expiry the empty-budget path refuses
    await redis.delete(keycache_key(h))
    later = types.SimpleNamespace(
        time=lambda: time.time() + 41, monotonic=time.monotonic
    )
    monkeypatch.setattr(platform_auth, "time", later)
    assert await verifier.verify_token(key) is None


@pytest.mark.parametrize(
    "then,served",
    [
        (response(401), False),
        (response(403), False),
        (response(422), False),
        (httpx.ConnectTimeout("slow"), True),
        (httpx.ConnectError("refused"), True),
        (response(502), True),
        (response(503), True),
        ("empty-budget", True),
    ],
)
async def test_stale_serve_only_when_budget_empty_or_backend_unreachable(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch, then: Any, served: bool
) -> None:
    at_ip(monkeypatch, "203.0.113.7")
    nxt = [] if then == "empty-budget" else [then]
    verifier = make_verifier(redis, ok(key), *nxt)
    assert await verifier.verify_token(key) is not None
    h = key_format.key_hash(key)
    await redis.delete(keycache_key(h))
    if then == "empty-budget":
        await drain_budget(redis, "203.0.113.7")
    token = await verifier.verify_token(key)
    assert (token is not None) is served


# ------------------------------------------------- S13 / S33: rotation and signed responses


async def test_403_retries_once_with_the_next_secret(
    redis: FakeRedis, key: str
) -> None:
    verifier = make_verifier(
        redis,
        response(403),
        ok(key, secret="secret-B"),
        internal_auth_secret_next=SecretStr("secret-B"),
    )
    assert await verifier.verify_token(key) is not None
    assert [c["headers"]["X-Internal-Auth"] for c in calls(verifier)] == [
        SECRET,
        "secret-B",
    ]


async def test_no_next_secret_keeps_fail_closed(redis: FakeRedis, key: str) -> None:
    verifier = make_verifier(redis, response(403))
    assert await verifier.verify_token(key) is None
    assert len(calls(verifier)) == 1
    assert await cache_keys(redis) == []


async def test_a_second_403_after_the_retry_fails_closed(
    redis: FakeRedis, key: str
) -> None:
    verifier = make_verifier(
        redis,
        response(403),
        response(403),
        internal_auth_secret_next=SecretStr("secret-B"),
    )
    assert await verifier.verify_token(key) is None
    assert len(calls(verifier)) == 2 and await cache_keys(redis) == []


async def test_signed_response_verifies_with_the_next_secret_after_a_403_retry(
    redis: FakeRedis, key: str
) -> None:
    verifier = PlatformKeyVerifier(
        be_base_url="http://backend:8000",
        internal_auth_secret="secret-A",
        redis=redis,
        settings=Settings(internal_auth_secret_next=SecretStr("secret-B")),
    )
    verifier._http = fake_http(response(403), ok(key, secret="secret-B"))
    assert await verifier.verify_token(key) is not None
    # the backend is on B already: a 200 signed with A would NOT have verified
    wrong = PlatformKeyVerifier(
        be_base_url="http://backend:8000",
        internal_auth_secret="secret-A",
        redis=FakeRedis(decode_responses=True),
        settings=Settings(internal_auth_secret_next=SecretStr("secret-B")),
    )
    wrong._http = fake_http(response(403), ok(key, secret="secret-A"))
    assert await wrong.verify_token(key) is None


async def test_whitespace_next_secret_is_not_a_retry_secret(
    redis: FakeRedis, key: str
) -> None:
    verifier = make_verifier(
        redis, response(403), internal_auth_secret_next=SecretStr("   ")
    )
    assert verifier._next_secret is None
    assert await verifier.verify_token(key) is None
    assert len(calls(verifier)) == 1


@pytest.mark.parametrize(
    "bad",
    [
        lambda key: ok(key, sig=False),
        lambda key: ok(key, secret="not-the-secret"),
        lambda key: ok(key, ts=int(time.time()) - 3600),
        lambda key: ok(key, ts=int(time.time()) + 3600),
        lambda key: ok(
            key, user_id="22222222-2222-2222-2222-222222222222", secret="wrong"
        ),
    ],
)
async def test_unsigned_validate_key_response_is_refused(
    redis: FakeRedis, key: str, bad: Callable[[str], httpx.Response]
) -> None:
    verifier = make_verifier(redis, bad(key))
    assert await verifier.verify_token(key) is None
    assert await cache_keys(redis) == [], "a refused 200 must not be cached"


async def test_response_altered_after_signing_is_refused(
    redis: FakeRedis, key: str
) -> None:
    good = ok(key).json()
    good["user_id"] = (
        "22222222-2222-2222-2222-222222222222"  # a swapped identity, old sig
    )
    verifier = make_verifier(redis, response(200, good))
    assert await verifier.verify_token(key) is None


# ------------------------------------------------- edges: expiry, bytes, write failures, the seam


async def test_an_already_expired_key_is_refused_and_not_cached(
    redis: FakeRedis, key: str
) -> None:
    verifier = make_verifier(redis, ok(key, expires_at=int(time.time()) - 5))
    assert await verifier.verify_token(key) is None
    assert await cache_keys(redis) == []


async def test_a_bytes_redis_client_reads_records_too(key: str) -> None:
    """A client built without decode_responses returns bytes for every value."""
    raw_redis = FakeRedis()  # bytes
    verifier = make_verifier(raw_redis, ok(key))
    assert await verifier.verify_token(key) is not None  # 200, records written
    assert (
        await verifier.verify_token(key) is not None
    )  # keycache hit, read back as bytes
    assert len(calls(verifier)) == 1
    h = key_format.key_hash(key)
    await raw_redis.set(keycache_key(h), "DENIED")
    assert await verifier.verify_token(key) is None, "a bytes DENIED is still DENIED"
    assert await verifier._stale_serve(key, h, "backend_unreachable") is not None, (
        "and the stale record reads as bytes"
    )


@pytest.mark.parametrize("raw", ["{not json", "", "[]", "null", '{"sig": 5}'])
async def test_garbage_cache_records_are_misses(
    redis: FakeRedis, key: str, raw: str
) -> None:
    verifier = make_verifier(redis, ok(key))
    await redis.set(keycache_key(key_format.key_hash(key)), raw)
    assert await verifier.verify_token(key) is not None
    assert len(calls(verifier)) == 1


async def test_a_failing_cache_write_does_not_deny_a_validated_key(key: str) -> None:
    class NoScripts(FakeRedis):
        async def eval(self, *a: Any, **k: Any) -> Any:
            raise ConnectionError("scripts unavailable")

    verifier = make_verifier(NoScripts(decode_responses=True), ok(key))
    assert await verifier.verify_token(key) is not None
    denied = make_verifier(NoScripts(decode_responses=True), response(401))
    assert await denied.verify_token(key) is None


async def test_the_budget_seam_calls_ratelimit_take_token(
    monkeypatch: pytest.MonkeyPatch, redis: FakeRedis
) -> None:
    """The real `_take_token` (not the autouse fake) calls `take_token`."""
    seen: list[dict[str, Any]] = []

    async def take_token(
        _redis: Any, name: str, *, capacity: int, refill_period_s: int
    ) -> Any:
        seen.append(
            {"key": name, "capacity": capacity, "refill_period_s": refill_period_s}
        )
        return types.SimpleNamespace(allowed=len(seen) == 1)

    monkeypatch.setattr(platform_auth, "take_token", take_token)
    monkeypatch.setattr(platform_auth, "_take_token", REAL_TAKE_TOKEN)
    assert (
        await platform_auth._take_token(redis, "k", capacity=3, refill_period_s=60)
        is True
    )
    assert (
        await platform_auth._take_token(redis, "k", capacity=3, refill_period_s=60)
        is False
    )
    assert seen[0] == {"key": "k", "capacity": 3, "refill_period_s": 60}


async def test_the_real_take_token_spends_the_validate_key_bucket(
    monkeypatch: pytest.MonkeyPatch, redis: FakeRedis
) -> None:
    """Integration (A/B seam): the real `ratelimit.take_token` behind the seam, real key shape.

    The key is `rate:mcp:{SERVER_KEY}:tb:vk:{rate_key_for_ip(ip)}`; capacity 2 admits two
    and refuses the third, and the bucket lives in Redis under exactly that name.
    """
    from fast_mcp_template.http.net import rate_key_for_ip

    monkeypatch.setattr(platform_auth, "_take_token", REAL_TAKE_TOKEN)
    verifier = make_verifier(redis, response(401), validate_key_budget_per_ip=2)
    rate_key = rate_key_for_ip("203.0.113.9")
    expected = f"rate:mcp:{SERVER_KEY}:tb:vk:{rate_key}"
    assert budget_key(rate_key) == expected
    spent = [await verifier._spend_budget(rate_key) for _ in range(3)]
    assert spent == [True, True, False]
    assert await redis.exists(expected) == 1


# ------------------------------------------------- review R1 fixes (lane A fix1)

OTHER_USER = "22222222-2222-2222-2222-222222222222"


@pytest.mark.parametrize("purpose", ["keycache", "keyok"])
async def test_entry_signed_for_another_server_is_a_miss(
    redis: FakeRedis, key: str, purpose: str
) -> None:
    """M3: a record sealed for the `jira` gateway, MAC and all, must not open here."""
    verifier = make_verifier(redis)
    other = make_verifier(redis, server_key="jira")  # the `jira` gateway's verifier
    h0 = key_format.key_hash(key)
    jira_where = f"mcp:{'keycache' if purpose == 'keycache' else 'keyok'}:jira:{h0}"
    await put_keycache(other, key, purpose=purpose, at=jira_where)
    h = key_format.key_hash(key)
    # put it where THIS gateway reads it (the jira gateway's keys differ only by segment)
    src = f"mcp:{'keycache' if purpose == 'keycache' else 'keyok'}:jira:{h}"
    dest = keycache_key(h) if purpose == "keycache" else stale_key(h)
    await redis.rename(src, dest)
    assert verifier._open(await redis.get(dest), purpose, h) is None


@pytest.mark.parametrize("change", ["extra", "missing"])
async def test_record_with_an_extra_or_missing_field_is_a_miss(
    redis: FakeRedis, key: str, change: str
) -> None:
    """M3: the field set is part of the record contract, even if the MAC would cover it."""
    verifier = make_verifier(redis)
    h = key_format.key_hash(key)
    rec = json.loads(verifier._seal("keycache", h, IDENTITY, time.time() + 30))
    rec.pop("sig")
    if change == "extra":
        rec["admin"] = True
    else:
        del rec["rate_limit"]
    rec["sig"] = platform_auth._mac(SECRET, rec, label=MAC_LABEL)
    assert verifier._open(json.dumps(rec), "keycache", h) is None


async def test_constant_time_compare_is_used_at_every_site(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M4: the response signature, the record signature and the legacy key all go through
    hmac.compare_digest. `==` on a secret leaks timing (S9)."""
    from fast_mcp_template.auth.legacy import LegacyKeyVerifier

    seen: list[tuple[Any, Any]] = []
    real = hmac.compare_digest

    def spy(a: Any, b: Any) -> bool:
        seen.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    verifier = make_verifier(redis, ok(key))
    assert await verifier.verify_token(key) is not None  # response signature checked
    n_response = len(seen)
    assert n_response >= 1, "the validate-key response signature"
    assert await verifier.verify_token(key) is not None  # record signature checked
    assert len(seen) > n_response, "the signed record"
    before = len(seen)
    shared = LegacyKeyVerifier("shared-Kq7vR2mXz9LpW4nYt6BdJ8sHc3FgUa5e")
    assert await shared.verify_token("wrong") is None
    assert len(seen) == before + 1, "the legacy shared key"


@pytest.mark.parametrize("purpose", ["keycache", "keyok"])
async def test_a_non_ascii_signature_is_a_miss_not_a_500(
    redis: FakeRedis, key: str, purpose: str
) -> None:
    """L1: hmac.compare_digest raises TypeError on a non-ASCII str."""
    verifier = make_verifier(redis, ok(key))
    h = key_format.key_hash(key)
    rec = json.loads(verifier._seal(purpose, h, IDENTITY, time.time() + 30))
    rec["sig"] = "\u00e9" * 64
    dest = keycache_key(h) if purpose == "keycache" else stale_key(h)
    await redis.set(dest, json.dumps(rec))
    assert verifier._open(json.dumps(rec), purpose, h) is None
    if purpose == "keycache":
        assert await verifier.verify_token(key) is not None, (
            "falls through to the backend"
        )


@pytest.mark.parametrize(
    "then", ["transport", "503"], ids=["next-unreachable", "next-5xx"]
)
async def test_no_stale_serve_after_a_403_even_if_the_next_retry_is_unreachable(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch, then: str
) -> None:
    """L3: the 403 means this gateway's secret was refused; nothing may stale-serve after."""
    at_ip(monkeypatch, "203.0.113.7")
    verifier = make_verifier(
        redis, ok(key), internal_auth_secret_next=SecretStr("secret-B")
    )
    assert await verifier.verify_token(key) is not None  # writes the stale record
    await redis.delete(keycache_key(key_format.key_hash(key)))
    verifier._http = fake_http(
        response(403),
        httpx.ConnectError("down") if then == "transport" else response(503),
    )
    assert await verifier.verify_token(key) is None


async def test_only_a_403_triggers_the_next_retry(redis: FakeRedis, key: str) -> None:
    """L12 (#28): a 401 with NEXT set is one backend call, then DENIED."""
    verifier = make_verifier(
        redis, response(401), internal_auth_secret_next=SecretStr("secret-B")
    )
    assert await verifier.verify_token(key) is None
    assert len(calls(verifier)) == 1


@pytest.mark.parametrize(
    "identity",
    [
        {"user_id": "../../other/x"},
        {"user_id": ""},
        {"user_id": 7},
        {"scopes": {"servers": ["jira"]}},
        {"scopes": {"servers": SERVER_KEY}},
        {"scopes": "all"},
    ],
    ids=[
        "traversal",
        "empty",
        "int",
        "other-server",
        "servers-not-list",
        "scopes-not-dict",
    ],
)
async def test_backend_identity_is_validated(
    redis: FakeRedis, key: str, identity: dict[str, Any]
) -> None:
    """L5: a signed 200 is still refused when its user_id or scopes are not acceptable."""
    verifier = make_verifier(redis, ok(key, **identity))
    assert await verifier.verify_token(key) is None
    assert await cache_keys(redis) == []


async def test_a_sealed_record_with_a_bad_identity_is_a_miss(
    redis: FakeRedis, key: str
) -> None:
    """L5 on the read side: a correctly MACed record is still checked."""
    verifier = make_verifier(redis)
    h = key_format.key_hash(key)
    raw = verifier._seal(
        "keycache", h, {**IDENTITY, "user_id": "../x"}, time.time() + 30
    )
    assert verifier._open(raw, "keycache", h) is None


async def test_record_mac_key_is_derived_not_the_raw_secret(
    redis: FakeRedis, key: str
) -> None:
    """L6: a record MACed with the raw secret (what a wire observer holds) does not open."""
    verifier = make_verifier(redis)
    h = key_format.key_hash(key)
    rec = json.loads(verifier._seal("keycache", h, IDENTITY, time.time() + 30))
    rec.pop("sig")
    rec["sig"] = platform_auth._mac(SECRET, rec)  # no label: the raw-secret MAC
    assert verifier._open(json.dumps(rec), "keycache", h) is None
    assert platform_auth._mac(SECRET, rec) != platform_auth._mac(
        SECRET, rec, label=MAC_LABEL
    )


async def test_next_secret_use_is_logged_without_the_secret(
    redis: FakeRedis, key: str, caplog: pytest.LogCaptureFixture
) -> None:
    """L7: the rotation runbook needs to see NEXT being used (INFO, no secret)."""
    caplog.set_level(logging.INFO, logger="fast_mcp_template.auth.platform")
    verifier = make_verifier(
        redis, response(403), ok(key, secret="secret-B-0123456789"),
        internal_auth_secret_next=SecretStr("secret-B-0123456789"),
    )  # fmt: skip
    assert await verifier.verify_token(key) is not None
    events = [
        r
        for r in caplog.records
        if getattr(r, "event", "") == "internal_secret_next_used"
    ]
    assert [r.__dict__["via"] for r in events] == ["validate_key"]
    assert events[0].levelno == logging.INFO
    assert "secret-B-0123456789" not in caplog.text and SECRET not in caplog.text
    # a record sealed with the old secret, read when only NEXT matches
    old = make_verifier(redis)
    h = key_format.key_hash(key)
    sealed = old._seal("keycache", h, IDENTITY, time.time() + 30)
    caplog.clear()
    rotated = PlatformKeyVerifier(
        be_base_url="http://b",
        internal_auth_secret="brand-new-0123456789-abcdefghij",
        redis=redis,
        settings=Settings(internal_auth_secret_next=SecretStr(SECRET)),
    )
    assert rotated._open(sealed, "keycache", h) is not None
    assert any(getattr(r, "via", "") == "cache_record" for r in caplog.records)


async def test_stale_serve_log_carries_user_and_reason(
    redis: FakeRedis,
    key: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """L7: who was served stale, and why."""
    at_ip(monkeypatch, "203.0.113.7")
    verifier = make_verifier(redis, ok(key))
    assert await verifier.verify_token(key) is not None
    await redis.delete(keycache_key(key_format.key_hash(key)))
    await drain_budget(redis, "203.0.113.7")
    caplog.set_level(logging.WARNING, logger="fast_mcp_template.auth.platform")
    assert await verifier.verify_token(key) is not None
    rec = next(r for r in caplog.records if getattr(r, "event", "") == "stale_serve")
    assert (
        rec.__dict__["reason"] == "budget_empty"
        and rec.__dict__["user_id"] == IDENTITY["user_id"]
    )


async def test_validate_key_forwards_the_request_id(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L8 (LO10): trace the request across the service boundary."""
    monkeypatch.setattr(net, "current_request_id", lambda: "req-abc-123")
    verifier = make_verifier(redis, ok(key))
    assert await verifier.verify_token(key) is not None
    assert calls(verifier)[0]["headers"]["X-Request-ID"] == "req-abc-123"


async def test_concurrent_misses_for_one_key_make_one_backend_call(
    redis: FakeRedis, key: str
) -> None:
    """L9: five simultaneous first requests cost one validate-key call and one budget token."""
    gate = asyncio.Event()

    async def slow_ok() -> httpx.Response:
        await gate.wait()
        return ok(key)

    verifier = make_verifier(redis, slow_ok)
    tasks = [asyncio.create_task(verifier.verify_token(key)) for _ in range(5)]
    await asyncio.sleep(0.05)
    gate.set()
    tokens = await asyncio.gather(*tasks)
    assert all(t is not None for t in tokens)
    assert len(calls(verifier)) == 1
    assert verifier._flights == {}, (
        "the per-key lock is dropped when the last holder leaves"
    )


async def test_concurrent_misses_for_different_keys_do_not_serialize(
    redis: FakeRedis,
) -> None:
    """L9: the lock is per key_hash, not global."""
    k1, k2 = key_format.mint_key(), key_format.mint_key()
    gate = asyncio.Event()

    async def held(k: str) -> httpx.Response:
        await gate.wait()
        return ok(k)

    verifier = make_verifier(redis, lambda: held(k1), lambda: held(k2))
    t1 = asyncio.create_task(verifier.verify_token(k1))
    t2 = asyncio.create_task(verifier.verify_token(k2))
    await asyncio.sleep(0.05)
    assert len(calls(verifier)) == 2, (
        "both reached the backend while the first was in flight"
    )
    gate.set()
    assert await t1 is not None and await t2 is not None


async def test_response_signature_is_keyed_with_the_raw_secret(
    redis: FakeRedis, key: str
) -> None:
    """EC-637 contract: HMAC-SHA256(raw secret, canonical json list), no derivation."""
    h = key_format.key_hash(key)
    ts = int(time.time())
    payload = [
        "validate-key-response",
        h,
        ts,
        IDENTITY["user_id"],
        IDENTITY["scopes"],
        None,
        None,
    ]
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(SECRET.encode(), data, "sha256").hexdigest()
    body = {**IDENTITY, "expires_at": None, "ts": ts, "sig": sig}
    verifier = make_verifier(redis, response(200, body))
    assert await verifier.verify_token(key) is not None
    derived = platform_auth._mac(SECRET, payload, label=MAC_LABEL)
    assert derived != sig
    other = make_verifier(
        FakeRedis(decode_responses=True), response(200, {**body, "sig": derived})
    )
    assert await other.verify_token(key) is None, (
        "a label-derived response signature must fail"
    )


# ------------------------------------------------ single-flight shares the outcome (R2 M2)


def _failing_after(delay: float, exc: Exception) -> Callable[[], Any]:
    async def slow_fail() -> Exception:
        await asyncio.sleep(delay)
        return exc

    return slow_fail


async def _timed_five(
    verifier: PlatformKeyVerifier, key: str
) -> tuple[list[Any], float]:
    started = time.monotonic()
    results = await asyncio.gather(*(verifier.verify_token(key) for _ in range(5)))
    return list(results), time.monotonic() - started


async def test_followers_share_a_failing_backends_one_answer_not_five_serial_calls(
    redis: FakeRedis, key: str
) -> None:
    """M2: five concurrent misses, backend failing after 0.5 s: ~0.5 s and ONE call, all stale."""
    verifier = make_verifier(redis, ok(key))
    assert await verifier.verify_token(key) is not None  # writes the stale record
    await redis.delete(keycache_key(key_format.key_hash(key)))
    verifier._http = fake_http(_failing_after(0.5, httpx.ConnectError("down")))
    results, elapsed = await _timed_five(verifier, key)
    assert all(r is not None for r in results), (
        "every follower got the leader's stale-serve"
    )
    assert len(calls(verifier)) == 1
    # One call is 0.5 s, five in turn 2.5 s; the bound sits between them.
    assert elapsed < 2.0, f"{elapsed:.2f}s: followers queued behind the dead backend"


async def test_followers_share_a_leader_that_produced_nothing(
    redis: FakeRedis, key: str
) -> None:
    """M2: no stale record, backend down: the leader's None is everyone's answer, at once."""
    verifier = make_verifier(redis, _failing_after(0.5, httpx.ConnectError("down")))
    results, elapsed = await _timed_five(verifier, key)
    assert results == [None] * 5
    assert (
        len(calls(verifier)) == 1 and elapsed < 2.0
    )  # one call 0.5 s, five in turn 2.5 s


async def test_followers_share_a_refusal_and_a_denial(
    redis: FakeRedis, key: str
) -> None:
    """M2: a 403 (refused) and a 401 (denied) are also one call with one shared answer."""
    for status in (403, 401):

        async def slow(status: int = status) -> httpx.Response:
            await asyncio.sleep(
                0.1
            )  # overlap: the followers arrive while the leader is out
            return response(status)

        verifier = make_verifier(FakeRedis(decode_responses=True), slow)
        results, _ = await _timed_five(verifier, key)
        assert results == [None] * 5 and len(calls(verifier)) == 1, status


@pytest.mark.parametrize("takeover_delay", [None, 0.3])
async def test_a_cancelled_leader_hands_over_and_the_followers_still_complete(
    redis: FakeRedis, key: str, takeover_delay: float | None
) -> None:
    """M2: a client disconnect must neither hang nor cancel the followers.

    The takeover answers at once (delay None: a late follower finds the cache filled, which only
    the compute's cache re-read saves it from a backend call) or slowly (delay 0.3: followers
    must share ONE takeover flight; an instant answer would hide a double leader, R3 #2).
    """
    never = asyncio.Event()

    async def hangs() -> httpx.Response:
        await never.wait()
        return ok(key)

    async def slow_takeover() -> httpx.Response:
        await asyncio.sleep(takeover_delay or 0)
        return ok(key)

    verifier = make_verifier(
        redis, hangs, ok(key) if takeover_delay is None else slow_takeover
    )
    leader = asyncio.create_task(verifier.verify_token(key))
    await asyncio.sleep(0.05)
    followers = [asyncio.create_task(verifier.verify_token(key)) for _ in range(4)]
    await asyncio.sleep(0.05)
    leader.cancel()
    async with asyncio.timeout(3):
        tokens = await asyncio.gather(*followers)
    assert all(t is not None for t in tokens)
    assert len(calls(verifier)) == 2, (
        "the cancelled leader's call plus ONE takeover, not four"
    )
    assert verifier._flights == {}


async def test_a_raising_leader_fails_only_itself(
    redis: FakeRedis, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2: an unexpected exception reaches the leader alone; a follower takes over."""
    verifier = make_verifier(redis, ok(key))
    real = verifier._validate_remote
    gate = asyncio.Event()
    first = [True]

    async def flaky(key_hash: str) -> Any:
        if first[0]:
            first[0] = False
            await gate.wait()
            raise RuntimeError("unexpected")
        return await real(key_hash)

    monkeypatch.setattr(verifier, "_validate_remote", flaky)
    leader = asyncio.create_task(verifier.verify_token(key))
    await asyncio.sleep(0.05)
    follower = asyncio.create_task(verifier.verify_token(key))
    await asyncio.sleep(0.05)
    gate.set()
    with pytest.raises(RuntimeError, match="unexpected"):
        await leader
    assert await follower is not None
    assert verifier._flights == {}


async def test_concurrent_flights_for_two_keys_keep_each_keys_own_identity(
    redis: FakeRedis,
) -> None:
    """EC-644: two keys, cold keycache, five callers each: no token carries the other's identity.

    The flight is keyed by the key hash. A constant flight key would hand key B's callers key
    A's leader result (a user-id and scopes leak), which no single-key test can see.
    """
    keys = [key_format.mint_key(), key_format.mint_key()]
    idents: list[dict[str, Any]] = [
        {
            "user_id": "aaaaaaaa-1111-4111-8111-111111111111",
            "scopes": {"servers": [SERVER_KEY, "a"]},
        },
        {
            "user_id": "bbbbbbbb-2222-4222-8222-222222222222",
            "scopes": {"servers": [SERVER_KEY, "b"]},
        },
    ]
    by_hash = {
        key_format.key_hash(k): (k, i) for k, i in zip(keys, idents, strict=True)
    }
    posted: list[str] = []
    gate = asyncio.Event()  # opens once every follower has queued behind its leader
    asyncio.get_running_loop().call_later(0.1, gate.set)

    class ByHashHttp:
        """Answers each validate-key call for the key hash it carries, whatever the order."""

        async def post(
            self, url: str, *, json: Any = None, headers: Any = None
        ) -> httpx.Response:
            posted.append(json["key_hash"])
            await (
                gate.wait()
            )  # both leaders are out together; their results settle together
            k, ident = by_hash[json["key_hash"]]
            return ok(k, **ident)

    verifier = make_verifier(redis)
    verifier._http = cast(httpx.AsyncClient, ByHashHttp())
    order = [keys[n % 2] for n in range(10)]  # interleaved: A B A B ...
    async with asyncio.timeout(5):
        tokens = await asyncio.gather(*(verifier.verify_token(k) for k in order))
    for k, token in zip(order, tokens, strict=True):
        ident = idents[keys.index(k)]
        assert token is not None
        assert token.claims["user_id"] == ident["user_id"]
        assert token.claims["scopes"] == ident["scopes"]
        assert token.client_id.endswith(ident["user_id"])
    assert sorted(posted) == sorted(by_hash), (
        "one validate-key call per key, not per caller"
    )
    assert verifier._flights == {}


# ------------------------------------------------ identity matches the backend model (R2 L5)


@pytest.mark.parametrize(
    "identity",
    [
        {"scopes": {}},
        {"scopes": {"servers": None}},
        {"rate_limit": True},
        {"rate_limit": "5"},
        {"rate_limit": -1},
        {"rate_limit": 0},
        {"rate_limit": 1.5},
        {"user_id": "{11111111-1111-1111-1111-111111111111}"},
        {"user_id": "11111111111111111111111111111111"},
        {"user_id": "urn:uuid:11111111-1111-1111-1111-111111111111"},
        {"scopes": "all"},
    ],
    ids=[
        "no-servers",
        "null-servers",
        "bool",
        "string",
        "negative",
        "zero",
        "float",
        "braces",
        "no-hyphens",
        "urn",
        "scopes-not-dict",
    ],  # fmt: skip
)
async def test_backend_identity_matches_the_backend_model(
    redis: FakeRedis, key: str, identity: dict[str, Any]
) -> None:
    """L5: `ValidationResult` needs servers containing this gateway and rate_limit int|None."""
    verifier = make_verifier(redis, ok(key, **identity))
    assert await verifier.verify_token(key) is None
    assert await cache_keys(redis) == []


async def test_an_upper_case_user_id_is_normalized_to_one_spelling(
    redis: FakeRedis, key: str
) -> None:
    """L5: the id is the vault path and partition key; the signature covers what was SENT."""
    upper = "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE"
    verifier = make_verifier(redis, ok(key, user_id=upper, rate_limit=7))
    token = await verifier.verify_token(key)
    assert token is not None
    assert token.claims["user_id"] == upper.lower() and token.claims["rate_limit"] == 7
    assert token.client_id.endswith(upper.lower())
    h = key_format.key_hash(key)
    stored = await get_json(redis, keycache_key(h))
    assert stored["user_id"] == upper.lower()
    sealed = verifier._seal(
        "keycache", h, {**IDENTITY, "user_id": upper}, time.time() + 30
    )
    opened = verifier._open(
        sealed, "keycache", h
    )  # a stored upper-case record reads canonical
    assert opened is not None and opened["user_id"] == upper.lower()


@pytest.mark.parametrize("rate_limit", [True, "5", 0, -3, 2.0])
async def test_a_sealed_record_with_a_bad_rate_limit_is_a_miss(
    redis: FakeRedis, key: str, rate_limit: Any
) -> None:
    verifier = make_verifier(redis)
    h = key_format.key_hash(key)
    raw = verifier._seal(
        "keycache", h, {**IDENTITY, "rate_limit": rate_limit}, time.time() + 30
    )
    assert verifier._open(raw, "keycache", h) is None
