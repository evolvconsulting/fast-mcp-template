import logging
import time
from collections.abc import Iterator
from typing import Any, cast

import pytest
import redis.exceptions
from fakeredis.aioredis import FakeRedis
from redis.asyncio import Redis

from fast_mcp_template.limits import ratelimit
from fast_mcp_template.limits.ratelimit import (
    ip_bucket_key,
    take_token,
    user_bucket_key,
)


@pytest.fixture(autouse=True)
def _clean_local_buckets() -> Iterator[None]:
    ratelimit._LOCAL_BUCKETS.clear()
    ratelimit._fail_open_log.update(
        last=-ratelimit.FAIL_OPEN_LOG_INTERVAL_S, skipped=0.0
    )
    ratelimit._table_full_log.update(
        last=-ratelimit.FAIL_OPEN_LOG_INTERVAL_S, skipped=0.0
    )
    yield
    ratelimit._LOCAL_BUCKETS.clear()


async def test_full_bucket_allows_capacity_then_refuses(fake_redis: FakeRedis) -> None:
    k = user_bucket_key("svc", "u1")
    for i in range(5):
        d = await take_token(
            fake_redis, k, capacity=5, refill_period_s=60, now_ms=1_000
        )
        assert d.allowed and d.remaining == 4 - i and d.limit == 5
    d = await take_token(fake_redis, k, capacity=5, refill_period_s=60, now_ms=1_000)
    assert (
        not d.allowed and d.retry_after_s == 12 and d.remaining == 0
    )  # 60/5 = 12 s per token


async def test_refills_over_time(fake_redis: FakeRedis) -> None:
    k = user_bucket_key("svc", "u2")
    for _ in range(2):
        await take_token(fake_redis, k, capacity=2, refill_period_s=60, now_ms=0)
    refused = await take_token(
        fake_redis, k, capacity=2, refill_period_s=60, now_ms=29_000
    )
    assert not refused.allowed
    assert (
        await take_token(fake_redis, k, capacity=2, refill_period_s=60, now_ms=30_000)
    ).allowed


async def test_rejected_requests_do_not_consume(fake_redis: FakeRedis) -> None:
    k = user_bucket_key("svc", "u3")
    assert (
        await take_token(fake_redis, k, capacity=1, refill_period_s=60, now_ms=0)
    ).allowed
    for t in range(1, 50):
        assert not (
            await take_token(fake_redis, k, capacity=1, refill_period_s=60, now_ms=t)
        ).allowed
    assert (
        await take_token(fake_redis, k, capacity=1, refill_period_s=60, now_ms=60_000)
    ).allowed


async def test_zero_capacity_refuses(fake_redis: FakeRedis) -> None:
    d = await take_token(
        fake_redis,
        user_bucket_key("svc", "u4"),
        capacity=0,
        refill_period_s=60,
        now_ms=0,
    )
    assert not d.allowed and d.retry_after_s == 60


async def test_bucket_is_a_hash_with_tokens_ts_and_a_ttl(fake_redis: FakeRedis) -> None:
    k = user_bucket_key("svc", "u5")
    await take_token(fake_redis, k, capacity=4, refill_period_s=60, now_ms=5_000)
    h = await fake_redis.hgetall(k)
    assert (
        set(h) == {"tokens", "ts"} and h["ts"] == "5000" and float(h["tokens"]) == 3.0
    )
    assert 0 < await fake_redis.pttl(k) <= 120_000


async def test_a_clock_that_steps_back_does_not_refill(fake_redis: FakeRedis) -> None:
    k = user_bucket_key("svc", "u6")
    assert (
        await take_token(fake_redis, k, capacity=1, refill_period_s=60, now_ms=10_000)
    ).allowed
    assert not (
        await take_token(fake_redis, k, capacity=1, refill_period_s=60, now_ms=9_000)
    ).allowed
    # 60 s after the FIRST take (not after the backwards step) the token is back.
    assert (
        await take_token(fake_redis, k, capacity=1, refill_period_s=60, now_ms=70_000)
    ).allowed


def _r(fake: object) -> Redis:
    """A hand-built fake standing in for the Redis client."""
    return cast(Redis, fake)


class _Broken:
    def __init__(self, calls: list[int]) -> None:
        self.calls = calls

    def register_script(self, *_a: Any) -> Any:
        self.calls.append(1)

        async def run(*_a: Any, **_k: Any) -> None:
            raise redis.exceptions.ConnectionError("down")

        return run


async def test_redis_error_falls_back_to_a_local_bucket(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[int] = []
    with caplog.at_level(logging.WARNING):
        d = await take_token(
            _r(_Broken(calls)), "k", capacity=1, refill_period_s=60, now_ms=0
        )
        assert d.allowed  # the local bucket has a token
        assert calls == [1]  # the broken client really ran
        d2 = await take_token(
            _r(_Broken(calls)), "k", capacity=1, refill_period_s=60, now_ms=1
        )
    assert not d2.allowed  # NOT unlimited: the local bucket is empty (S15)
    assert d2.retry_after_s >= 1
    assert any(
        getattr(r, "event", None) == "rate_limit_fail_open"
        and r.levelno == logging.WARNING
        for r in caplog.records
    )


async def test_local_fallback_is_per_key_and_refills() -> None:
    b = _Broken([])
    assert (
        await take_token(_r(b), "a", capacity=1, refill_period_s=60, now_ms=0)
    ).allowed
    assert (
        await take_token(_r(b), "b", capacity=1, refill_period_s=60, now_ms=0)
    ).allowed
    assert not (
        await take_token(_r(b), "a", capacity=1, refill_period_s=60, now_ms=1)
    ).allowed
    assert (
        await take_token(_r(b), "a", capacity=1, refill_period_s=60, now_ms=60_000)
    ).allowed


async def test_local_fallback_memory_is_bounded() -> None:
    b = _Broken([])
    for i in range(10_050):  # literals, so raising the cap cannot move the goalposts
        await take_token(_r(b), f"k{i}", capacity=1, refill_period_s=60, now_ms=i)
    assert len(ratelimit._LOCAL_BUCKETS) <= 10_000


async def test_a_non_redis_exception_is_not_swallowed() -> None:
    class Boom:
        def register_script(self, *_a: Any) -> Any:
            async def run(*_a: Any, **_k: Any) -> None:
                raise ValueError("bug")

            return run

    with pytest.raises(ValueError):
        await take_token(_r(Boom()), "k", capacity=1, refill_period_s=60, now_ms=0)


async def test_lua_is_registered_per_call_on_the_given_client() -> None:
    calls: list[int] = []
    for _ in range(2):
        await take_token(
            _r(_Broken(calls)), "kk", capacity=9, refill_period_s=60, now_ms=0
        )
    assert calls == [1, 1]


def test_key_shapes() -> None:
    assert user_bucket_key("svc", "abc") == "rate:mcp:svc:tb:user:abc"
    assert ip_bucket_key("svc", "1.2.3.4") == "rate:mcp:svc:tb:ip:1.2.3.4"


async def test_refill_is_capped_at_capacity(fake_redis: FakeRedis) -> None:
    k = user_bucket_key("svc", "u7")
    await take_token(fake_redis, k, capacity=3, refill_period_s=60, now_ms=0)
    for i in range(3):  # a day later the bucket holds 3 tokens, not 1000s
        d = await take_token(
            fake_redis, k, capacity=3, refill_period_s=60, now_ms=86_400_000
        )
        assert d.allowed and d.remaining == 2 - i
    assert not (
        await take_token(
            fake_redis, k, capacity=3, refill_period_s=60, now_ms=86_400_000
        )
    ).allowed


async def test_zero_capacity_refusal_resets_after_a_full_period(
    fake_redis: FakeRedis,
) -> None:
    d = await take_token(
        fake_redis,
        user_bucket_key("svc", "u8"),
        capacity=0,
        refill_period_s=60,
        now_ms=0,
    )
    assert (d.retry_after_s, d.reset_s, d.limit, d.remaining) == (60, 60, 0, 0)


async def test_a_backwards_clock_never_rewinds_the_stored_ts(
    fake_redis: FakeRedis,
) -> None:
    k = user_bucket_key("svc", "u9")
    await take_token(fake_redis, k, capacity=2, refill_period_s=60, now_ms=10_000)
    await take_token(fake_redis, k, capacity=2, refill_period_s=60, now_ms=4_000)
    assert await fake_redis.hget(k, "ts") == "10000"


async def test_fail_open_warning_is_logged_once_per_interval(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    b = _Broken([])
    with caplog.at_level(logging.WARNING):
        for i in range(100):
            await take_token(_r(b), f"k{i}", capacity=5, refill_period_s=60, now_ms=i)
        lines = [
            r
            for r in caplog.records
            if getattr(r, "event", "") == "rate_limit_fail_open"
        ]
        assert len(lines) == 1 and lines[0].suppressed_since_last == 0  # type: ignore[attr-defined]
        clock[0] += ratelimit.FAIL_OPEN_LOG_INTERVAL_S
        await take_token(_r(b), "again", capacity=5, refill_period_s=60, now_ms=200)
    lines = [
        r for r in caplog.records if getattr(r, "event", "") == "rate_limit_fail_open"
    ]
    assert len(lines) == 2 and lines[1].suppressed_since_last == 99  # type: ignore[attr-defined]


async def test_a_busy_bucket_is_never_evicted_so_nobody_gets_a_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ratelimit, "MAX_LOCAL_BUCKETS", 3)
    b = _r(_Broken([]))
    assert (
        await take_token(b, "victim", capacity=1, refill_period_s=60, now_ms=0)
    ).allowed
    assert not (
        await take_token(b, "victim", capacity=1, refill_period_s=60, now_ms=1)
    ).allowed
    # An attacker floods new keys: the table is full of buckets still in use, so the
    # new keys are refused and the victim's exhausted bucket survives untouched.
    for i in range(50):
        d = await take_token(b, f"new{i}", capacity=1, refill_period_s=60, now_ms=2 + i)
        assert len(ratelimit._LOCAL_BUCKETS) <= 3
        assert d.allowed == (i < 2)  # two free slots (new0, new1); the rest are refused
    assert not (
        await take_token(b, "victim", capacity=1, refill_period_s=60, now_ms=100)
    ).allowed


async def test_idle_buckets_are_evicted_oldest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ratelimit, "MAX_LOCAL_BUCKETS", 3)
    b = _r(_Broken([]))
    for k in ("a", "b", "c"):
        await take_token(b, k, capacity=1, refill_period_s=60, now_ms=0)
    await take_token(
        b, "c", capacity=1, refill_period_s=60, now_ms=61_000
    )  # c is busy again
    await take_token(b, "d", capacity=1, refill_period_s=60, now_ms=61_000)
    assert set(ratelimit._LOCAL_BUCKETS) == {"b", "c", "d"}  # a: the oldest idle one


async def test_a_local_backwards_clock_never_rewinds_the_stored_ts() -> None:
    """The local twin of the Lua test above (F7): the stored ts only moves forward."""
    b = _r(_Broken([]))
    await take_token(b, "k", capacity=2, refill_period_s=60, now_ms=10_000)
    await take_token(b, "k", capacity=2, refill_period_s=60, now_ms=4_000)
    assert ratelimit._LOCAL_BUCKETS["k"][1] == 10_000


async def test_a_full_local_table_refusal_is_logged_apart_from_a_normal_refusal(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F6: an operator must be able to tell 'table full' from 'user over limit'."""
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ratelimit, "MAX_LOCAL_BUCKETS", 2)
    b = _r(_Broken([]))

    def full_lines() -> list[Any]:
        return [
            r
            for r in caplog.records
            if getattr(r, "event", "") == "rate_limit_local_table_full"
        ]

    with caplog.at_level(logging.WARNING):
        for k in ("a", "b"):
            await take_token(b, k, capacity=1, refill_period_s=60, now_ms=0)
        assert full_lines() == []  # nothing refused yet
        for i in range(50):
            d = await take_token(
                b, f"new{i}", capacity=1, refill_period_s=60, now_ms=1 + i
            )
            assert not d.allowed
        assert len(full_lines()) == 1 and full_lines()[0].suppressed_since_last == 0
        clock[0] += ratelimit.FAIL_OPEN_LOG_INTERVAL_S
        await take_token(b, "later", capacity=1, refill_period_s=60, now_ms=100)
    assert len(full_lines()) == 2 and full_lines()[1].suppressed_since_last == 49
    assert full_lines()[0].max_buckets == 2


async def test_a_local_refusal_never_says_retry_after_zero() -> None:
    """R3 F3: a bucket short by float noise still answers Retry-After >= 1."""
    ratelimit._LOCAL_BUCKETS["noise"] = (0.99999999999, 0, 60)
    d = await take_token(
        _r(_Broken([])), "noise", capacity=1, refill_period_s=60, now_ms=0
    )
    assert not d.allowed and d.retry_after_s == 1


async def test_a_local_refill_is_capped_at_capacity() -> None:
    """R3 F3: the local twin of `test_refill_is_capped_at_capacity`."""
    b = _r(_Broken([]))
    await take_token(b, "cap", capacity=3, refill_period_s=60, now_ms=0)
    day = 86_400_000
    for i in range(3):
        d = await take_token(b, "cap", capacity=3, refill_period_s=60, now_ms=day)
        assert d.allowed and d.remaining == 2 - i
    assert not (
        await take_token(b, "cap", capacity=3, refill_period_s=60, now_ms=day)
    ).allowed
