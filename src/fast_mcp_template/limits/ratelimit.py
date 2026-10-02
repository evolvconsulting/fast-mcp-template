"""Redis Lua token bucket.

One `take_token` call is one atomic EVALSHA of `ratelimit.lua`. A
bucket is a hash with the fields `tokens` (float) and `ts` (ms). When
Redis errors the limiter does NOT open completely: it falls back to a
process-local bucket with the same arithmetic, so a single task still
enforces the limit during a Redis outage.
"""

from __future__ import annotations

import importlib.resources
import logging
import math
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Final

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

#: Bound on the process-local fallback (one entry per key seen during
#: an outage).
MAX_LOCAL_BUCKETS: Final = 10_000

_LUA: Final = (importlib.resources.files(__package__) / "ratelimit.lua").read_text(
    encoding="utf-8"
)

# key -> (tokens, ts_ms, refill_period_s); least recently used first.
_LOCAL_BUCKETS: OrderedDict[str, tuple[float, int, int]] = OrderedDict()

# The fail-open WARNING is logged at most once per this many seconds
# per process; the calls skipped in between are counted and reported on
# the next line (a Redis outage at 400 rps must not write 400 warnings
# a second).
FAIL_OPEN_LOG_INTERVAL_S: Final = 30.0
_fail_open_log: dict[str, float] = {
    "last": -FAIL_OPEN_LOG_INTERVAL_S,
    "skipped": 0.0,
}
# Same throttle for the "local table full" refusal, on its own state so
# one event never hides the other.
_table_full_log: dict[str, float] = {
    "last": -FAIL_OPEN_LOG_INTERVAL_S,
    "skipped": 0.0,
}


@dataclass(frozen=True)
class RateDecision:
    """The outcome of one token take."""

    allowed: bool
    limit: int  # bucket capacity
    remaining: int  # whole tokens left, >= 0
    reset_s: int  # seconds until the bucket is full again, >= 0
    retry_after_s: int  # 0 when allowed; >= 1 when refused


def user_bucket_key(server_key: str, user_id: str) -> str:
    """Return the Redis key of a per-user credential's bucket."""
    return f"rate:mcp:{server_key}:tb:user:{user_id}"


def ip_bucket_key(server_key: str, ip: str) -> str:
    """Return the Redis key of a shared-key client IP's bucket."""
    return f"rate:mcp:{server_key}:tb:ip:{ip}"


def platform_ip_bucket_key(server_key: str, ip: str) -> str:
    """Return the key of a client IP's bucket for PER-USER traffic.

    Separate from `ip_bucket_key`: the Lua refill rate and cap come
    from the `capacity` argument of each call, so sharing one key would
    hand shared-credential clients on the same IP the larger refill.
    """
    return f"rate:mcp:{server_key}:tb:pip:{ip}"


def _ceil(value: float) -> int:
    """Ceiling that ignores float noise (12.000000000001 is 12)."""
    return math.ceil(round(value, 6))


def _decision(
    tokens: float, allowed: bool, capacity: int, refill_period_s: int
) -> RateDecision:
    """Build a decision from the tokens left AFTER the take."""
    per_token_s = refill_period_s / capacity
    return RateDecision(
        allowed=allowed,
        limit=capacity,
        remaining=max(0, math.floor(round(tokens, 6))),
        reset_s=max(0, _ceil((capacity - tokens) * per_token_s)),
        retry_after_s=0 if allowed else max(1, _ceil((1 - tokens) * per_token_s)),
    )


def _evict_one_idle(now_ms: int) -> bool:
    """Drop the oldest bucket idle for a full refill period.

    An idle bucket is full again, so dropping it loses nothing. A
    bucket still in use is NEVER dropped: that would hand its client a
    fresh full bucket (the "reset on eviction" an attacker with 10,001
    sources could use).
    """
    for key, (_tokens, ts, period_s) in _LOCAL_BUCKETS.items():
        if now_ms - ts >= period_s * 1000:
            del _LOCAL_BUCKETS[key]
            return True
    return False


def _take_local(
    key: str, capacity: int, refill_period_s: int, now_ms: int
) -> RateDecision:
    """Run the same bucket arithmetic as the Lua, in process memory.

    When the table is full of buckets all still in use, a NEW key is
    refused (fail closed) and not stored: existing clients keep their
    exact state.
    """
    if key not in _LOCAL_BUCKETS and len(_LOCAL_BUCKETS) >= MAX_LOCAL_BUCKETS:
        if not _evict_one_idle(now_ms):
            _log_table_full()
            return RateDecision(False, capacity, 0, refill_period_s, refill_period_s)
    tokens, ts, _ = _LOCAL_BUCKETS.pop(key, (float(capacity), now_ms, refill_period_s))
    elapsed = max(0, now_ms - ts)
    tokens = min(
        float(capacity), tokens + elapsed * capacity / (refill_period_s * 1000)
    )
    allowed = tokens >= 1
    if allowed:
        tokens -= 1
    _LOCAL_BUCKETS[key] = (tokens, max(ts, now_ms), refill_period_s)
    return _decision(tokens, allowed, capacity, refill_period_s)


def _throttled_warning(state: dict[str, float], message: str, **fields: object) -> None:
    """Log one WARNING per interval, with the skipped count."""
    now = time.monotonic()
    if now - state["last"] < FAIL_OPEN_LOG_INTERVAL_S:
        state["skipped"] += 1
        return
    skipped = int(state["skipped"])
    state.update(last=now, skipped=0.0)
    logger.warning(message, extra={**fields, "suppressed_since_last": skipped})


def _log_fail_open(exc: RedisError) -> None:
    """Log the throttled fail-open WARNING."""
    _throttled_warning(
        _fail_open_log,
        "rate limit Redis error; using the process-local bucket",
        event="rate_limit_fail_open",
        error_type=type(exc).__name__,
    )


def _log_table_full() -> None:
    """Log that a new key was refused because the local table is full.

    Without it an operator cannot tell this from an ordinary per-user
    429.
    """
    _throttled_warning(
        _table_full_log,
        "process-local rate limit table is full; refusing a new key",
        event="rate_limit_local_table_full",
        max_buckets=MAX_LOCAL_BUCKETS,
    )


async def take_token(
    redis: Redis,
    key: str,
    *,
    capacity: int,
    refill_period_s: int,
    now_ms: int | None = None,
) -> RateDecision:
    """Take one token from bucket `key`; never consumes on a refusal.

    `capacity <= 0` always refuses. Any `redis.exceptions.RedisError`
    (connection and timeout errors included) falls back to the
    process-local bucket and logs a throttled WARNING
    `rate_limit_fail_open`; builtin exceptions are bugs and propagate.
    """
    if capacity <= 0:
        return RateDecision(
            False, max(0, capacity), 0, refill_period_s, refill_period_s
        )
    now = int(time.time() * 1000) if now_ms is None else now_ms
    try:
        # register_script per call, on the client given: the Script
        # object binds a client.
        script = redis.register_script(_LUA)
        allowed, tokens = await script(
            keys=[key], args=[capacity, refill_period_s, now]
        )
    except RedisError as exc:
        _log_fail_open(exc)
        return _take_local(key, capacity, refill_period_s, now)
    return _decision(float(tokens), bool(int(allowed)), capacity, refill_period_s)
