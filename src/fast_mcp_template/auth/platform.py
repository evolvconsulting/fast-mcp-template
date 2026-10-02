"""Per-user platform key verification (the optional Evolv platform auth).

Replaces the shared-key path for per-user `evc_live_…` keys: a key is CRC-checked
offline, hashed, looked up in the signed Redis keycache and (on a miss) validated
against the BE's internal endpoint.

Fail directions (§7.2, deliberate asymmetry):
  * authentication fails **CLOSED** - BE unreachable / unexpected status → None,
    except the revocation-safe stale-serve tier below;
  * lockout (availability control) fails **OPEN** - Redis errors are swallowed;
  * the validate-key BUDGET (S30) does neither: Redis errors fall back to a
    process-local token bucket with the same rate (DESIGN 8.5).

Rate limiting is NOT here: it lives in `RateLimitMiddleware`. This module keeps
only the validate-key budget, which protects the shared backend from novel-key sprays.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Final

import httpx2 as httpx
from fastmcp.server.auth import AccessToken, TokenVerifier
from redis.asyncio import Redis

from fast_mcp_template.auth import key_format
from fast_mcp_template.auth.types import (
    CLAIM_AUTH_PATH,
    CLAIM_RATE_LIMIT,
    CLAIM_SCOPES,
    CLAIM_USER_ID,
    PLATFORM_CLIENT_ID_PREFIX,
)
from fast_mcp_template.config import Settings, internal_verify
from fast_mcp_template.http import net
from fast_mcp_template.limits.ratelimit import take_token

logger = logging.getLogger(__name__)

# The per-deployment server identity is `settings.server_key`: the `server`
# value in the validate-key body, the keycache segment, the rate-limit segment.

DENIED = "DENIED"  # literal negative-cache marker (§13.5)

# Lockout thresholds (§5.3/§13.5). Module constants because §13.4 pins helper
# signatures that carry no settings handle.
PREFIX_THRESHOLD = 5
IP_THRESHOLD = 20
COUNTER_TTL_SECONDS = 300
LATCH_TTL_SECONDS = 60

# Metric name for the alert-only per-IP arm - the "metric-shaped record" §4.2(a)
# step 3 requires. One log line carries it until a real metrics sink exists.
IP_SPRAY_METRIC = "mcp.auth.ip_spray_threshold_crossed"

# S30: validate-key calls per client IP are budgeted per minute.
VALIDATE_KEY_WINDOW_S: Final = 60
# L4: the hang bound of the validate-key call (resilience.md: explicit timeout, shorter than the
# inbound deadline), and its circuit breaker: this many consecutive outage-class failures open it
# for this many seconds.
VALIDATE_KEY_TIMEOUT_S: Final = 5.0
BREAKER_FAILURES: Final = 5
BREAKER_OPEN_S: Final = 30.0
# The signed validate-key 200 must be this fresh (M4.2): |now - ts| <= 60 s.
RESPONSE_MAX_SKEW_S: Final = 60

PURPOSE_KEYCACHE: Final = "keycache"
PURPOSE_KEYOK: Final = "keyok"
_RECORD_FIELDS: Final = frozenset(
    {"key_hash", "user_id", "server", "scopes", "rate_limit", "purpose", "exp"}
)

# Write the keycache and stale records unless a tombstone exists (S6): one atomic step,
# so a revoke landing between the backend's 200 and this write is never undone.
_WRITE_LUA: Final = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[2])
if ARGV[3] ~= '' then redis.call('SET', KEYS[3], ARGV[3], 'EX', ARGV[4]) end
return 1
"""
# A backend 401 negative-caches the hash and deletes the stale record in the same step.
_DENY_LUA: Final = """
redis.call('SET', KEYS[1], 'DENIED', 'EX', ARGV[1])
redis.call('DEL', KEYS[2])
return 1
"""


def keycache_key(server_key: str, key_hash: str) -> str:
    """The signed keycache record (or the DENIED marker) for a key hash."""
    return f"mcp:keycache:{server_key}:{key_hash}"


def stale_key(server_key: str, key_hash: str) -> str:
    """The signed stale-serve record (S30), written only after a backend 200."""
    return f"mcp:keyok:{server_key}:{key_hash}"


def tombstone_key(server_key: str, key_hash: str) -> str:
    """The revocation tombstone the backend writes (EC-636, S6). Present = refuse."""
    return f"mcp:revoked:{server_key}:{key_hash}"


def budget_key(server_key: str, rate_key: str | None) -> str:
    """The validate-key bucket for a client; no client IP shares the one `vk:unknown`."""
    return f"rate:mcp:{server_key}:tb:vk:{rate_key or 'unknown'}"


async def check_lockout(redis: Redis, ip: str | None, prefix12: str) -> bool:
    """True if the per-key-prefix latch is set. Fails OPEN (False) on Redis errors.

    `ip` is accepted (§13.4 signature) but deliberately unused: the per-IP arm is
    ALERT-ONLY as of the 2026-07-29 ratification, so `mcp:lockout:ip:{ip}:locked`
    is neither written nor read. A per-IP latch let any unauthenticated attacker
    take out every user behind a shared egress IP (office NAT/VPN/CGNAT) for 60 s,
    re-trippably, for free - and lockout was never a secrecy control (256-bit keys
    are unguessable), only defence-in-depth against BE load that the negative
    cache already carries.
    """
    del ip  # alert-only arm: never latched, never consulted (§4.2(a) step 3)
    try:
        return bool(await redis.exists(f"mcp:lockout:prefix:{prefix12}:locked"))
    except Exception as exc:  # noqa: BLE001 - availability control fails open (§7.2)
        logger.warning("lockout check failed open", extra={"error": str(exc)})
        return False


async def record_failure(redis: Redis, ip: str | None, prefix12: str) -> None:
    """Count a failed attempt on both fixed-window arms.

    Per-key-prefix arm **latches** at its threshold (5 / 300 s / 60 s). Per-IP arm
    **counts and alerts only** - crossing 20 / 300 s emits a log line + metric-shaped
    record and never writes a latch (ratified 2026-07-29; see `check_lockout`).

    Fails OPEN (silently) on Redis errors - §7.2.
    """
    try:
        prefix_counter = f"mcp:lockout:prefix:{prefix12}"
        count = await _incr_window(redis, prefix_counter)
        if count >= PREFIX_THRESHOLD:
            await redis.set(f"{prefix_counter}:locked", "1", ex=LATCH_TTL_SECONDS)
            logger.warning("auth lockout latched", extra={"key": prefix_counter})

        if ip:
            count = await _incr_window(redis, f"mcp:lockout:ip:{ip}")
            if count == IP_THRESHOLD:  # once per window: the crossing is the alert
                logger.warning(
                    "auth failure spray threshold crossed from one IP (alert-only, "
                    "no lockout applied)",
                    extra={
                        "metric": IP_SPRAY_METRIC,
                        "metric_value": count,
                        "client_ip": ip,
                        "window_seconds": COUNTER_TTL_SECONDS,
                        "threshold": IP_THRESHOLD,
                    },
                )
    except Exception as exc:  # noqa: BLE001 - availability control fails open (§7.2)
        logger.warning("lockout record failed open", extra={"error": str(exc)})


async def _incr_window(redis: Redis, counter: str) -> int:
    """INCR + first-write EXPIRE - the fixed-window pattern (`rate_limit.py:54-55`)."""
    count = await redis.incr(counter)
    if count == 1:
        await redis.expire(counter, COUNTER_TTL_SECONDS)
    return int(count)


async def _take_token(
    redis: Redis, key: str, *, capacity: int, refill_period_s: int
) -> bool:
    """True when `key`'s bucket had a token (taken): `ratelimit.take_token`.

    Kept as a seam: most tests monkeypatch this function; `test_the_real_take_token_*`
    runs the real one.
    """
    decision = await take_token(
        redis, key, capacity=capacity, refill_period_s=refill_period_s
    )
    return bool(decision.allowed)


# Purpose label for the gateway-only record MAC key (L6). The validate-key RESPONSE is signed
# by the backend with the raw secret (EC-637 contract); the records only this gateway writes
# and reads use a key derived from the secret under this label instead of the raw value.
_RECORD_MAC_LABEL: Final = "keycache-record-mac/v1"  # prefixed with the server key


def _mac(secret: str, payload: object, *, label: bytes | None = None) -> str:
    """Hex HMAC-SHA256 over the canonical JSON of `payload` (sorted keys, no spaces).

    With `label`, the key is `HMAC(secret, label)`, not the secret itself.
    """
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    key = secret.encode()
    if label is not None:
        key = hmac.new(key, label, hashlib.sha256).digest()
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def _canonical_user_id(
    server_key: str, user_id: object, scopes: object, rate_limit: object
) -> str | None:
    """The lower-case canonical user id when the identity is acceptable, else None (L5).

    Mirrors the backend's `ValidationResult`: a UUID `user_id`, `scopes` a dict whose
    `servers` is a list naming this gateway (missing or null is refused: the backend's own
    `validate_hash` requires it), and `rate_limit` an int >= 1 or None (a bool is not an int).
    The id becomes the vault path and a partition key, so one user must have one spelling.
    """
    if not isinstance(user_id, str):
        return None
    try:
        canonical = str(uuid.UUID(user_id))
    except ValueError:
        return None
    if (
        canonical != user_id.lower()
    ):  # braces, urn:, missing hyphens: not the backend's form
        return None
    if not isinstance(scopes, dict):
        return None
    servers = scopes.get("servers")
    if not isinstance(servers, list) or server_key not in servers:
        return None
    if rate_limit is not None and (
        isinstance(rate_limit, bool)
        or not isinstance(rate_limit, int)
        or rate_limit < 1
    ):
        return None
    return canonical


class _Revoked:
    """Sentinel: a revocation tombstone exists for the key."""


_REVOKED = _Revoked()


class _Flight:
    """One validation in flight for a key.

    `settled` False means the leader raised or was cancelled: followers must not take its
    (absent) result, one of them leads instead.
    """

    __slots__ = ("done", "result", "settled")

    def __init__(self) -> None:
        self.done = asyncio.Event()
        self.result: AccessToken | None = None
        self.settled = False


class _Outcome:
    """What a backend validate-key round trip produced."""

    __slots__ = ("answered", "entry", "expires_at", "kind")

    def __init__(
        self,
        kind: str,
        entry: dict[str, Any] | None = None,
        expires_at: int | None = None,
        *,
        answered: bool = True,
    ) -> None:
        self.kind = kind  # ok | denied | unreachable | refused
        # False only for a local failure: the backend never answered (R8 N3).
        self.answered = answered
        self.entry = entry
        self.expires_at = expires_at


class PlatformKeyVerifier(TokenVerifier):
    """FastMCP TokenVerifier backed by the platform key registry (§4.2(a))."""

    def __init__(
        self,
        *,
        be_base_url: str,
        internal_auth_secret: str,
        redis: Redis,
        settings: Settings,
    ) -> None:
        """Wire the verifier; the secret is passed UNWRAPPED (see the note below)."""
        # `internal_auth_secret` is the UNWRAPPED clear-text value, deliberately:
        # `settings.internal_auth_secret` is a `SecretStr` and the caller unwraps
        # it (dual.build_verifier). This class is the one that puts the
        # value on the wire, and a `SecretStr` here would render as the literal
        # `'**********'` in the header below - which the BE would answer 403 to,
        # silently, for every request.
        super().__init__()
        self.be_base_url = be_base_url.rstrip("/")
        self.internal_auth_secret = internal_auth_secret
        nxt = settings.internal_auth_secret_next
        value = nxt.get_secret_value().strip() if nxt is not None else ""
        # S13: a blank or whitespace NEXT is unset. Stored stripped: that is the value used.
        self._next_secret: str | None = value or None
        self.redis = redis
        self.settings = settings
        self.server_key = settings.server_key
        self._mac_label = f"{settings.server_key}/{_RECORD_MAC_LABEL}".encode()
        self._http = httpx.AsyncClient(
            timeout=VALIDATE_KEY_TIMEOUT_S, verify=internal_verify(settings)
        )
        # L4: consecutive outage-class failures, and the monotonic time the breaker stays open to.
        self._failures = 0
        self._open_until = 0.0
        self._probing = False  # a half-open probe is in flight (L3)
        # R8 L1: bumped on every transition; an outcome from an older epoch is a straggler.
        self._epoch = 0
        # key_hash -> the validation in flight; followers share its outcome (L9, M2).
        self._flights: dict[str, _Flight] = {}

    async def aclose(self) -> None:
        """Close the pooled validate-key client (L3): sockets end closed, not dropped at exit."""
        await self._http.aclose()

    @property
    def _secrets(self) -> list[str]:
        """Secrets a signed record may verify against: current, then NEXT (S13)."""
        return [self.internal_auth_secret] + (
            [self._next_secret] if self._next_secret else []
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        """The platform `AccessToken` for a valid per-user key, else None (401)."""
        if self.settings.test_emit_canary_secret_log:
            # E4 Arm-4 positive control (§4.2(d)): one deliberate raw-secret line so
            # the log scan can prove it catches a real leak. The internal auth secret
            # is the leaked value because it is the only Arm-4 needle visible in this
            # frame - downstream credentials live in vault.py, outside this
            # module. Emitted per request (not at startup) so it lands inside the
            # harness's `--since` capture window.
            logger.info("CANARY internal_auth_secret=%s", self.internal_auth_secret)

        # 1. Offline shape+CRC check. Malformed → no network, no Redis, and
        #    deliberately NO lockout state (a malformed volley must never latch
        #    the presenting IP - E5's presence control depends on this).
        if not key_format.crc32_ok(token):
            return None

        # 2. Hash. The raw key never leaves this frame. The IP is validated text or None;
        #    its rate KEY (the IPv6 /64) is what every per-IP counter uses (S9, S16).
        key_hash = key_format.key_hash(token)
        prefix12 = key_format.key_prefix(token)
        ip = net.rate_key_for_ip(
            net.current_client_ip(self.settings.trusted_proxy_hops)
        )

        # 3. Dual lockout - latches checked first.
        if await check_lockout(self.redis, ip, prefix12):
            logger.warning(
                "auth attempt refused by lockout", extra={"key_prefix": prefix12}
            )
            return None

        # 4. Keycache, read together with the revocation tombstone (S6).
        cached = await self._cache_get(key_hash)
        if cached == DENIED or cached is _REVOKED:
            # A hammered revoked key is signal: record it BEFORE returning
            # (§4.2(a) step 4 - §7.4's NAT control depends on this line).
            await record_failure(self.redis, ip, prefix12)
            return None
        if isinstance(cached, dict):
            return await self._authorize(token, cached)

        # Concurrent misses for one key share ONE validation and its outcome (L9, M2): success,
        # refusal and "nothing" alike. The same token hashes to the same key, so the answer is
        # the same; re-running it per follower only queued them behind a dead backend.
        return await self._single_flight(
            key_hash, lambda: self._miss(token, key_hash, prefix12, ip)
        )

    async def _miss(
        self, token: str, key_hash: str, prefix12: str, ip: str | None
    ) -> AccessToken | None:
        """The leader's work: re-read the cache (a flight may have just ended), then validate."""
        cached = await self._cache_get(key_hash)
        if cached == DENIED or cached is _REVOKED:
            return None
        if isinstance(cached, dict):
            return await self._authorize(token, cached)
        return await self._validate_and_cache(token, key_hash, prefix12, ip)

    async def _validate_and_cache(
        self, token: str, key_hash: str, prefix12: str, ip: str | None
    ) -> AccessToken | None:
        """Steps 5-7 of the miss path: budget, backend validate-key, cache write."""
        # 5. Miss. The per-IP validate-key budget bounds novel-key sprays (S30); an empty
        #    budget makes no backend call and may only serve an intact stale record.
        if not await self._spend_budget(ip):
            return await self._stale_serve(token, key_hash, "budget_empty")

        # 6. BE validate-key. Fails CLOSED on anything unexpected, except that an
        #    UNREACHABLE backend may serve an intact stale record (never after a 401/403).
        outcome = await self._validate_remote(key_hash)
        if outcome.kind == "denied":
            await self._deny(key_hash)
            await record_failure(self.redis, ip, prefix12)
            return None
        if outcome.kind == "unreachable":
            return await self._stale_serve(token, key_hash, "backend_unreachable")
        if outcome.kind != "ok" or outcome.entry is None:
            return None

        expires_at = outcome.expires_at
        if expires_at is not None and expires_at <= time.time():
            logger.warning("validate-key returned an already expired key; refusing")
            return None
        if not await self._cache_set(key_hash, outcome.entry, expires_at):
            # A tombstone landed between the backend's 200 and the write (L2, S6).
            logger.warning("key revoked while validating; refusing")
            return None

        # 7. Claims are the identity carrier; downstream reads ONLY these.
        return await self._authorize(token, outcome.entry)

    async def _single_flight(
        self, key_hash: str, compute: Callable[[], Awaitable[AccessToken | None]]
    ) -> AccessToken | None:
        """Run `compute` once per key at a time; concurrent callers share its result.

        A leader that raises or is cancelled settles nothing: each waiting follower then
        either finds a new leader or becomes it, so one client's disconnect cannot fail or
        hang the others and an exception reaches only the caller that hit it.
        """
        flight = self._flights.get(key_hash)
        while flight is not None:
            await (
                flight.done.wait()
            )  # an Event: a cancelled follower cannot cancel the leader
            if flight.settled:
                return flight.result
            flight = self._flights.get(key_hash)
        flight = self._flights[key_hash] = _Flight()
        try:
            flight.result = await compute()
            flight.settled = True
            return flight.result
        finally:
            del self._flights[key_hash]
            flight.done.set()

    # --- helpers ------------------------------------------------------------

    async def _authorize(self, token: str, entry: dict[str, Any]) -> AccessToken:
        """Mint the token. Runs on the cache-hit and the BE-validation path alike.

        T-A2: rate limiting moved to ratelimit.py (R5): nothing is counted here.
        """
        return self._token(token, entry)

    async def _spend_budget(self, rate_key: str | None) -> bool:
        """Take one validate-key token for this client (S30, DESIGN 8.5).

        The bucket math, and its process-local fallback when Redis errors (plan M2.13, S15),
        belong to `ratelimit.take_token`; this only decides what a refusal means. An
        unexpected failure of the seam refuses: the budget protects the shared backend.
        """
        try:
            return await _take_token(
                self.redis,
                budget_key(self.server_key, rate_key),
                capacity=self.settings.validate_key_budget_per_ip,
                refill_period_s=VALIDATE_KEY_WINDOW_S,
            )
        except Exception as exc:  # noqa: BLE001 - never unlimited (DESIGN 8.5)
            logger.warning(
                "validate-key budget unavailable; refusing", extra={"error": str(exc)}
            )
            return False

    async def _post(self, key_hash: str, secret: str) -> httpx.Response:
        headers = {"X-Internal-Auth": secret}
        request_id = net.current_request_id()
        if request_id:  # trace the request across the service boundary (LO10)
            headers["X-Request-ID"] = request_id
        return await self._http.post(
            f"{self.be_base_url}/api/v1/internal/validate-key",
            json={"key_hash": key_hash, "server": self.server_key},
            headers=headers,
        )

    async def _validate_remote(self, key_hash: str) -> _Outcome:
        """`_call_remote` behind a circuit breaker on the one outbound dependency (L4).

        After `BREAKER_FAILURES` consecutive outage-class outcomes (transport error or 5xx) the
        breaker opens for `BREAKER_OPEN_S`: calls then fail fast as `unreachable`, so the
        stale-serve rules apply unchanged and no request waits out the timeout holding a slot.
        When the time is up the breaker is half-open: exactly ONE probe goes through while every
        other caller fails fast as `unreachable`; the probe's failure reopens it, an answer from
        the backend closes it. Every transition is logged with the request id (resilience.md).
        There is no bulkhead beyond the global in-flight limiter, which is the bulkhead: it caps
        the slots any caller class can hold, and this is the only outbound dependency.
        """
        if time.monotonic() < self._open_until:
            return _Outcome("unreachable")
        half_open = self._failures >= BREAKER_FAILURES
        if half_open and self._probing:
            return _Outcome("unreachable")
        try:
            if half_open:
                self._probing = True
                self._transition("half_open")
            epoch = self._epoch
            outcome = await self._call_remote(key_hash)
        finally:
            if half_open:
                self._probing = False
        if epoch != self._epoch:
            # R8 L1: the breaker changed state while this call was in flight; the outcome belongs
            # to a past epoch and must not log, re-arm the window or reset the count.
            return outcome
        if outcome.kind == "unreachable":
            self._failures += 1
            if self._failures >= BREAKER_FAILURES:
                self._open_until = time.monotonic() + BREAKER_OPEN_S
                self._transition("open", was_half_open=half_open)
        elif outcome.kind in ("ok", "denied") or (
            half_open and outcome.kind == "refused" and outcome.answered
        ):
            # R7 L2: a 401/403 (refused) probe proves the backend is up, so it closes the breaker;
            # R8 N3: only if the backend really answered, not on a local exception.
            if half_open:
                self._open_until = 0.0
                self._transition("closed")
            self._failures = 0
        return outcome

    def _transition(self, state: str, *, was_half_open: bool = False) -> None:
        """Log one breaker state change (closed, open, half_open) with the request id."""
        self._epoch += 1
        logger.log(
            logging.ERROR if state == "open" else logging.WARNING,
            "validate-key circuit breaker %s",
            state.replace("_", "-"),
            extra={
                "event": f"validate_key_breaker_{state}",
                "from_half_open": was_half_open,
                "open_s": BREAKER_OPEN_S,
                "request_id": net.current_request_id(),
            },
        )

    async def _call_remote(self, key_hash: str) -> _Outcome:
        secret = self.internal_auth_secret
        refused_once = False  # a 403 was seen: nothing after it may stale-serve (L3)
        try:
            # R9 L1: the httpx timeout is per read, so a body dripped one byte at a time never
            # trips it; this bounds the WHOLE call (both posts), so a dripping probe ends too.
            async with asyncio.timeout(VALIDATE_KEY_TIMEOUT_S):
                resp = await self._post(key_hash, secret)
                if resp.status_code == 403 and self._next_secret:
                    # S13: rotation in flight, the backend may already be on NEXT. Once.
                    refused_once = True
                    secret = self._next_secret
                    resp = await self._post(key_hash, secret)
                    if resp.status_code == 200:
                        logger.info(
                            "authenticated to the backend with INTERNAL_AUTH_SECRET_NEXT",
                            extra={
                                "event": "internal_secret_next_used",
                                "via": "validate_key",
                            },
                        )
        except (
            httpx.TransportError,
            TimeoutError,
        ) as exc:  # timeout, refused/reset: UNREACHABLE
            logger.warning("validate-key unreachable", extra={"error": str(exc)})
            return _Outcome("refused" if refused_once else "unreachable")
        except Exception as exc:  # noqa: BLE001 - authentication fails closed (§7.2)
            logger.warning(
                "validate-key failed; failing closed", extra={"error": str(exc)}
            )
            return _Outcome("refused", answered=False)

        status = resp.status_code
        if status == 401:
            return _Outcome("denied")
        if status == 403:
            # THIS gateway's X-Internal-Auth is wrong. The BE raises 403 before any key
            # lookup (§4.1(d)), so the user's key was never judged: fail closed, but do
            # NOT cache "DENIED" and do NOT record a lockout failure - otherwise a
            # rotated/mistyped internal secret negative-caches and prefix-latches every
            # valid user's key, re-arming on each retry (ratified 2026-07-29).
            logger.error(
                "validate-key rejected this gateway's X-Internal-Auth (403): "
                "GATEWAY MISCONFIGURATION, not a bad user key. Failing closed "
                "without caching a denial or recording a lockout failure.",
                extra={"event": "internal_auth_misconfigured", "status_code": 403},
            )
            return _Outcome("refused")
        if status >= 500:
            logger.warning(
                "validate-key returned 5xx; unreachable", extra={"status_code": status}
            )
            return _Outcome("refused" if refused_once else "unreachable")
        if status != 200:
            logger.warning(
                "validate-key returned an unexpected status; failing closed",
                extra={"status_code": status},
            )
            return _Outcome("refused")
        return self._parse_200(resp, key_hash, secret)

    def _parse_200(self, resp: httpx.Response, key_hash: str, secret: str) -> _Outcome:
        """Verify the signed 200 (S33, M4.2) with the secret that authenticated the call."""
        try:
            body = resp.json()
            # Required keys are indexed, not `.get`: a BE field rename must fail
            # closed and loudly, not silently put None in the claims.
            sent_user_id = body[CLAIM_USER_ID]
            scopes = body[CLAIM_SCOPES]
            rate_limit = body.get(CLAIM_RATE_LIMIT)
            user_id = _canonical_user_id(
                self.server_key, sent_user_id, scopes, rate_limit
            )
            if user_id is None:
                logger.error(
                    "validate-key 200 has an invalid user id, scopes or rate limit; failing closed",
                    extra={"event": "validate_key_identity_invalid"},
                )
                return _Outcome("refused")
            entry = {
                CLAIM_USER_ID: user_id,
                CLAIM_SCOPES: scopes,
                CLAIM_RATE_LIMIT: rate_limit,
            }
            expires_at = body.get("expires_at")
            ts, sig = body["ts"], body["sig"]
            signed = [
                "validate-key-response",
                key_hash,
                ts,
                sent_user_id,  # the signature covers what the backend sent, not our spelling
                scopes,
                rate_limit,
                expires_at,
            ]
            fresh = (
                isinstance(ts, int | float)
                and abs(time.time() - ts) <= RESPONSE_MAX_SKEW_S
            )
            if not (
                isinstance(sig, str)
                and fresh
                and hmac.compare_digest(sig, _mac(secret, signed))
                and (expires_at is None or isinstance(expires_at, int))
            ):
                logger.error(
                    "validate-key 200 has a missing, stale or wrong signature; failing closed",
                    extra={"event": "validate_key_response_unsigned"},
                )
                return _Outcome("refused")
        except Exception as exc:  # noqa: BLE001 - the parse fails closed (§7.2)
            logger.warning(
                "validate-key failed; failing closed", extra={"error": str(exc)}
            )
            return _Outcome("refused")
        return _Outcome("ok", entry, expires_at)

    def _seal(
        self, purpose: str, key_hash: str, entry: dict[str, Any], exp: int | float
    ) -> str:
        """A record signed with the CURRENT secret over the whole entry (S14)."""
        body = {
            "key_hash": key_hash,
            "user_id": entry[CLAIM_USER_ID],
            "server": self.server_key,
            "scopes": entry[CLAIM_SCOPES],
            "rate_limit": entry[CLAIM_RATE_LIMIT],
            "purpose": purpose,
            "exp": int(exp),
        }
        sig = _mac(self.internal_auth_secret, body, label=self._mac_label)
        return json.dumps({**body, "sig": sig})

    def _open(
        self, raw: str | bytes | None, purpose: str, key_hash: str
    ) -> dict[str, Any] | None:
        """The entry inside a signed record, or None (a miss) for ANY defect (S14)."""
        if isinstance(raw, bytes):
            raw = raw.decode(errors="replace")
        if raw is None:
            return None
        try:
            rec = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("cache record was not JSON; treating as a miss")
            return None
        # A poisoned/legacy record (non-object, unsigned, wrong shape) must be a miss,
        # not a TypeError/KeyError escaping verify_token as a 500.
        if not isinstance(rec, dict):
            return None
        sig = rec.pop("sig", None)
        exp = rec.get("exp")
        if (
            not isinstance(sig, str)
            or not sig.isascii()  # compare_digest raises on non-ASCII str: a miss, not a 500
            or set(rec) != _RECORD_FIELDS
            or rec["purpose"] != purpose
            or rec["key_hash"] != key_hash
            or rec["server"] != self.server_key
            or isinstance(exp, bool)
            or not isinstance(exp, int | float)
            or time.time() > exp
            or _canonical_user_id(
                self.server_key, rec["user_id"], rec["scopes"], rec["rate_limit"]
            )
            is None
        ):
            logger.warning("cache record failed verification; treating as a miss")
            return None
        # `any()` would short-circuit on the first match and hide WHICH secret verified.
        matched = [
            i
            for i, s in enumerate(self._secrets)
            if hmac.compare_digest(sig, _mac(s, rec, label=self._mac_label))
        ]
        if not matched:
            logger.warning("cache record failed verification; treating as a miss")
            return None
        if matched[0] > 0:
            logger.info(
                "cache record verified with INTERNAL_AUTH_SECRET_NEXT",
                extra={"event": "internal_secret_next_used", "via": "cache_record"},
            )
        return {
            CLAIM_USER_ID: str(
                uuid.UUID(rec[CLAIM_USER_ID])
            ),  # validated above: one spelling
            CLAIM_SCOPES: rec[CLAIM_SCOPES],
            CLAIM_RATE_LIMIT: rec[CLAIM_RATE_LIMIT],
        }

    async def _cache_get(self, key_hash: str) -> dict[str, Any] | str | _Revoked | None:
        """A verified entry (dict), DENIED, `_REVOKED`, or None. Redis errors are a miss.

        The tombstone is read in the same round trip: a tombstone hit ends the key even on
        a live keycache entry, and a read error makes a hit a miss (S6).
        """
        try:
            raw, tombstone = await self.redis.mget(
                keycache_key(self.server_key, key_hash),
                tombstone_key(self.server_key, key_hash),
            )
        except Exception as exc:  # noqa: BLE001 - a cache outage falls through to the BE
            logger.warning("keycache read failed", extra={"error": str(exc)})
            return None
        if tombstone is not None:
            return _REVOKED
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode(errors="replace")
        if raw == DENIED:
            return DENIED
        return self._open(raw, PURPOSE_KEYCACHE, key_hash)

    async def _cache_set(
        self, key_hash: str, entry: dict[str, Any], expires_at: int | None
    ) -> bool:
        """Write the keycache and stale records after a 200, unless a tombstone exists.

        Each record's `exp` is `min(now + its TTL, expires_at)`: nothing outlives the key.
        False means a tombstone exists (refuse); a Redis error is best-effort and True.
        """
        now = time.time()
        cap = float("inf") if expires_at is None else expires_at - now
        cache_ttl = max(1, int(min(self.settings.key_cache_ttl_seconds, cap)))
        stale_ttl = int(min(self.settings.validate_key_stale_serve_s, cap))
        try:
            written = await self.redis.eval(
                _WRITE_LUA,
                3,
                tombstone_key(self.server_key, key_hash),
                keycache_key(self.server_key, key_hash),
                stale_key(self.server_key, key_hash),
                self._seal(PURPOSE_KEYCACHE, key_hash, entry, now + cache_ttl),
                str(cache_ttl),
                self._seal(PURPOSE_KEYOK, key_hash, entry, now + stale_ttl)
                if stale_ttl > 0
                else "",
                str(max(stale_ttl, 1)),
            )
        except Exception as exc:  # noqa: BLE001 - cache write is best-effort
            logger.warning("keycache write failed", extra={"error": str(exc)})
            return True
        return int(written) != 0

    async def _deny(self, key_hash: str) -> None:
        """Negative-cache the hash and delete its stale record in one step (S6)."""
        try:
            await self.redis.eval(
                _DENY_LUA,
                2,
                keycache_key(self.server_key, key_hash),
                stale_key(self.server_key, key_hash),
                str(self.settings.key_cache_ttl_seconds),
            )
        except Exception as exc:  # noqa: BLE001 - cache write is best-effort
            logger.warning("keycache write failed", extra={"error": str(exc)})

    async def _stale_serve(
        self, token: str, key_hash: str, reason: str
    ) -> AccessToken | None:
        """Serve an intact stale record: empty budget or unreachable backend ONLY (S30).

        The tombstone is read in the same round trip (MGET) and wins; it existing, or the
        read erroring, refuses.
        """
        try:
            raw, tombstone = await self.redis.mget(
                stale_key(self.server_key, key_hash),
                tombstone_key(self.server_key, key_hash),
            )
            if tombstone is not None:
                return None
        except Exception as exc:  # noqa: BLE001 - an unreadable tombstone means refuse (S6)
            logger.warning(
                "stale-serve refused: redis read failed", extra={"error": str(exc)}
            )
            return None
        if raw is None:
            return None
        entry = self._open(raw, PURPOSE_KEYOK, key_hash)
        if entry is None:
            return None
        logger.warning(
            "serving a stale validated key",
            extra={
                "event": "stale_serve",
                "reason": reason,
                "user_id": entry[CLAIM_USER_ID],
            },
        )
        return self._token(token, entry)

    @staticmethod
    def _token(token: str, entry: dict[str, Any]) -> AccessToken:
        return AccessToken(
            token=token,
            client_id=f"{PLATFORM_CLIENT_ID_PREFIX}{entry[CLAIM_USER_ID]}",
            scopes=[],
            expires_at=None,
            claims={
                CLAIM_AUTH_PATH: "platform",
                CLAIM_USER_ID: entry[CLAIM_USER_ID],
                CLAIM_SCOPES: entry.get(CLAIM_SCOPES),
                CLAIM_RATE_LIMIT: entry.get(CLAIM_RATE_LIMIT),
            },
        )
