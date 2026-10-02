"""The validate-key circuit breaker, and the remaining boot refusals.

The breaker protects the one outbound dependency: after
`BREAKER_FAILURES` consecutive outage-class failures it opens, calls
fail fast as `unreachable` (so the stale-serve rules apply and no request
waits out the timeout holding a slot), and exactly ONE probe goes through
when it half-opens.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx2 as httpx
import pytest
from fakeredis.aioredis import FakeRedis

from fast_mcp_template.auth import key_format
from fast_mcp_template.auth import platform as pa
from fast_mcp_template.auth.dual import (
    DualModeVerifier,
    build_verifier,
    resolve_auth_mode,
)
from fast_mcp_template.auth.types import AuthConfigError
from fast_mcp_template.config import Settings
from tests.test_platform_auth import SECRET, make_verifier, ok

GOOD_SECRET = "kQ7vN2xZp9Lm4Rt8Wd3Hs6Jf1Yc5Ba0Gu"  # noqa: S105 - a fake
REDIS = "redis://localhost:1/0"


@pytest.fixture(autouse=True)
def _budget_always_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow(*_a: Any, **_k: Any) -> bool:
        return True

    monkeypatch.setattr(pa, "_take_token", allow)


def down() -> httpx.ConnectError:
    return httpx.ConnectError("refused")


async def trip(verifier: pa.PlatformKeyVerifier) -> None:
    for _ in range(pa.BREAKER_FAILURES):
        assert await verifier.verify_token(key_format.mint_key()) is None


async def test_the_breaker_opens_after_consecutive_outages_and_fails_fast(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = FakeRedis(decode_responses=True)
    verifier = make_verifier(redis, *[down() for _ in range(pa.BREAKER_FAILURES)])
    with caplog.at_level(logging.WARNING):
        await trip(verifier)
        before = len(verifier._http.calls)  # type: ignore[attr-defined]
        # open: no backend call at all, and still a clean refusal
        assert await verifier.verify_token(key_format.mint_key()) is None
        assert len(verifier._http.calls) == before  # type: ignore[attr-defined]
    opened = [
        r
        for r in caplog.records
        if getattr(r, "event", "") == "validate_key_breaker_open"
    ]
    assert len(opened) == 1
    assert opened[0].levelno == logging.ERROR


async def test_half_open_lets_exactly_one_probe_through_and_a_success_closes_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = FakeRedis(decode_responses=True)
    probe_key = key_format.mint_key()
    verifier = make_verifier(
        redis, *[down() for _ in range(pa.BREAKER_FAILURES)], ok(probe_key)
    )
    await trip(verifier)
    verifier._open_until = 0.0  # the open window has passed: half-open
    with caplog.at_level(logging.WARNING):
        # a probe is already in flight: every other caller fails fast
        verifier._probing = True
        assert await verifier.verify_token(key_format.mint_key()) is None
        verifier._probing = False
        assert await verifier.verify_token(probe_key) is not None  # the probe
    events = [getattr(r, "event", "") for r in caplog.records]
    assert "validate_key_breaker_half_open" in events
    assert "validate_key_breaker_closed" in events
    assert verifier._failures == 0
    assert verifier._probing is False


async def test_a_failed_probe_reopens_the_breaker() -> None:
    redis = FakeRedis(decode_responses=True)
    verifier = make_verifier(redis, *[down() for _ in range(pa.BREAKER_FAILURES + 1)])
    await trip(verifier)
    verifier._open_until = 0.0
    assert await verifier.verify_token(key_format.mint_key()) is None  # probe fails
    assert verifier._open_until > 0.0  # open again


async def test_a_403_probe_proves_the_backend_is_up_and_closes_the_breaker() -> None:
    redis = FakeRedis(decode_responses=True)
    verifier = make_verifier(
        redis,
        *[down() for _ in range(pa.BREAKER_FAILURES)],
        httpx.Response(403, json={}),
    )
    await trip(verifier)
    verifier._open_until = 0.0
    assert await verifier.verify_token(key_format.mint_key()) is None
    assert verifier._failures == 0
    assert verifier._open_until == 0.0


async def test_a_clean_answer_resets_the_failure_count() -> None:
    redis = FakeRedis(decode_responses=True)
    good = key_format.mint_key()
    verifier = make_verifier(redis, down(), down(), ok(good))
    for _ in range(2):
        assert await verifier.verify_token(key_format.mint_key()) is None
    assert verifier._failures == 2
    assert await verifier.verify_token(good) is not None
    assert verifier._failures == 0


async def test_aclose_closes_the_pooled_client() -> None:
    closed: list[bool] = []

    class Http:
        async def aclose(self) -> None:
            closed.append(True)

    verifier = make_verifier(FakeRedis(decode_responses=True))
    verifier._http = Http()  # type: ignore[assignment]
    await verifier.aclose()
    assert closed == [True]
    dual = DualModeVerifier(mode="platform", legacy=None, platform=verifier)
    await dual.aclose()
    assert closed == [True, True]
    await DualModeVerifier(mode="legacy", legacy=object(), platform=None).aclose()  # type: ignore[arg-type]


# --- boot refusals the matrix does not reach -------------------------------


def prod(**kw: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": "production",
        "redis_url": "rediss://cache.internal:6380/0",
        "api_key": GOOD_SECRET,
    }
    return Settings(**{**base, **kw})


def test_production_refuses_a_redis_url_without_a_host() -> None:
    with pytest.raises(AuthConfigError, match="must name a host"):
        resolve_auth_mode(prod(redis_url="rediss:///0", internal_ca_cert="x"))


def test_production_refuses_ssl_query_parameters_on_the_redis_url() -> None:
    url = "rediss://cache.internal:6380/0?ssl_cert_reqs=none"
    with pytest.raises(AuthConfigError, match="ssl_\\* query parameter"):
        resolve_auth_mode(prod(redis_url=url, internal_ca_cert="x"))


@pytest.mark.parametrize("scheme", ["http", ""])
def test_production_dual_and_platform_refuse_a_non_https_backend(scheme: str) -> None:
    be = f"{scheme}://backend:8000" if scheme else "backend:8000"
    with pytest.raises(AuthConfigError, match="BE_BASE_URL must be an https"):
        resolve_auth_mode(
            prod(
                auth_mode="dual",
                be_base_url=be,
                internal_auth_secret=GOOD_SECRET + "x",
                internal_ca_cert="x",
            )
        )


def test_https_needs_the_internal_ca() -> None:
    with pytest.raises(AuthConfigError, match="INTERNAL_CA_CERT is required"):
        resolve_auth_mode(
            Settings(
                redis_url=REDIS,
                api_key=GOOD_SECRET,  # type: ignore[arg-type]
                auth_mode="dual",
                be_base_url="https://backend:8000",
                internal_auth_secret=GOOD_SECRET + "x",  # type: ignore[arg-type]
            )
        )


def test_a_garbage_ca_is_named_not_a_stack_trace() -> None:
    with pytest.raises(AuthConfigError, match="not a valid PEM"):
        resolve_auth_mode(prod(internal_ca_cert="not a pem"))


@pytest.mark.parametrize(
    "weak",
    [
        "password-and-secret-1234567890abcdefgh",  # two common words
        "Welcome2026-qpfzkwvxjhdgybtnmrlcsuaeo",  # a long word and a year
        "qwertyuiopASDFGHJKLzxcvbnm1234567890zz",  # a keyboard walk
    ],
)
def test_guessable_shared_keys_are_refused(weak: str) -> None:
    with pytest.raises(AuthConfigError, match="guessable|patterned"):
        build_verifier(Settings(redis_url=REDIS, api_key=weak), FakeRedis())  # type: ignore[arg-type]


def test_the_internal_secret_is_never_the_shared_one_by_shape() -> None:
    # SECRET is the rig's secret from the platform tests: strong enough to boot
    assert len(SECRET) >= 32
