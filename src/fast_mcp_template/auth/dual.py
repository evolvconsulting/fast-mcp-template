"""Boot-time auth mode resolution and the dual-mode token dispatcher.

Authentication fails CLOSED: every inconsistent or missing setting raises
`AuthConfigError` at boot, naming the variable to fix. The only path that yields no
verifier is the `dangerously_disable_auth` flag in `legacy` mode outside production.
"""

import logging
import math
import re
import ssl
import string
import zlib
from collections import Counter
from typing import Final
from urllib.parse import parse_qs, urlparse

from fastmcp.server.auth import AccessToken, TokenVerifier
from pydantic import SecretStr
from redis.asyncio import Redis

from fast_mcp_template.auth.legacy import LegacyKeyVerifier
from fast_mcp_template.auth.platform import PlatformKeyVerifier
from fast_mcp_template.auth.types import (
    DEFAULT_AUTH_MODE,
    PLATFORM_TOKEN_PREFIX,
    AuthConfigError,
    AuthMode,
    is_platform_token,
)
from fast_mcp_template.config import Settings, env_name, internal_ca_pem, url_scheme

logger = logging.getLogger(__name__)

# The variable NAMES a boot refusal tells the operator to fix, derived from the
# settings prefix so they stay right when the project is renamed.
API_KEY = env_name("api_key")
REDIS_URL = env_name("redis_url")
BE_BASE_URL = env_name("be_base_url")
INTERNAL_AUTH_SECRET = env_name("internal_auth_secret")
INTERNAL_AUTH_SECRET_NEXT = env_name("internal_auth_secret_next")
INTERNAL_CA_CERT = env_name("internal_ca_cert")
AUTH_MODE = env_name("auth_mode")
DISABLE_AUTH = env_name("dangerously_disable_auth")
ENVIRONMENT = env_name("environment")

# S8: a shared key this short is brute-forceable, so boot refuses it. Stage 0 rotates it.
MIN_SHARED_KEY_CHARS: Final = 32
# Pattern floor shared by every long-lived secret (N5, L11, R5 L2): `"a" * 32` is 32 characters
# and guessable. It measures randomness against the alphabet the value actually uses, so a random
# digit string is judged as digits (3.3 bits a symbol), not as base64. The floor catches
# accidents; the control is generating the secret with `openssl rand -base64 48`.
# Empirical bits of the whole value. 128 would refuse every random 32-digit secret (106 bits at
# most); random 32 digits give 100 on average and 75 at worst in 200,000 draws.
MIN_ENTROPY_BITS: Final = 64
MIN_ENTROPY_RATIO: Final = (
    0.6  # empirical bits a symbol over log2(alphabet), or log2(length)
)
CHANCE_ODDS: Final = (
    1e-7  # a pattern this long occurs by chance in fewer random values than this
)


def _raw(value: SecretStr | str | None) -> str:
    """The clear text of a setting, `SecretStr` or not. Whitespace-only counts as blank."""
    text = value.get_secret_value() if isinstance(value, SecretStr) else (value or "")
    return text.strip()


def _check_shared_key(key: str) -> None:
    """Refuse a platform-shaped or too-short shared key (S8, R-prefix collision)."""
    if key.startswith(PLATFORM_TOKEN_PREFIX):
        raise AuthConfigError(
            f"{API_KEY} starts with {PLATFORM_TOKEN_PREFIX!r}: such a token is always "
            "routed to the platform verifier, so the shared key could never authenticate. "
            f"Rotate {API_KEY} to a value that does not start with it."
        )
    _check_strength(API_KEY, key, "S8")


_RUN_LIMIT: Final = (
    6  # a same-character or consecutive run at least this long is a pattern
)


def _longest_run(value: str, step: int) -> int:
    """The longest run where each character is `step` code points after the previous one."""
    best = run = 1
    for prev, cur in zip(value, value[1:], strict=False):
        run = run + 1 if ord(cur) - ord(prev) == step else 1
        best = max(best, run)
    return best


# A secret that deflates below this fraction of its order-0 entropy repeats itself (a phrase
# repeated with noise, a tiled block); random text never deflates below its entropy (L2).
_MAX_COMPRESSION_RATIO: Final = 0.6
_KEYBOARD_ROWS: Final = ("qwertyuiop", "asdfghjkl", "zxcvbnm", "1234567890")


def _compresses_well(value: str) -> bool:
    """True if raw deflate shrinks `value` below `_MAX_COMPRESSION_RATIO` of its entropy size."""
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = packer.compress(value.encode()) + packer.flush()
    # L2 (R4): against the order-0 entropy bound, not the length: random hex or digits over a
    # small alphabet deflates below its length once long, but never below its own entropy.
    counts = Counter(value)
    entropy_bytes = -sum(n * math.log2(n / len(value)) for n in counts.values()) / 8
    return len(packed) < _MAX_COMPRESSION_RATIO * entropy_bytes


_REPEAT_CHUNK: Final = 16


def _repeats_a_chunk(value: str) -> bool:
    """True if some `_REPEAT_CHUNK` characters occur twice (overlap allowed).

    Catches a block repeated whatever the length (`"abcdefghij" * 4 + "a"`, a phrase with a
    tail): a value that is its own prefix repeated has a repeat of at least half its length,
    and values are at least 32 characters. Random text over a 10-symbol alphabet has no such
    repeat, even at 1 KiB (chance about 1e-10 per value).
    """
    return any(
        value[i : i + _REPEAT_CHUNK] in value[i + 1 :]
        for i in range(len(value) - _REPEAT_CHUNK)
    )


_ALPHABETS: Final = tuple(
    (frozenset(chars), size)
    for chars, size in (
        (string.digits, 10),
        (string.digits + "abcdef", 16),
        (string.digits + "ABCDEF", 16),
        (string.ascii_lowercase, 26),
        (string.ascii_uppercase, 26),
        (string.ascii_lowercase + string.digits, 36),
        (string.ascii_uppercase + string.digits, 36),
        (string.ascii_letters, 52),
        (string.ascii_letters + string.digits, 62),
        (string.ascii_letters + string.digits + "+/=", 64),
        (string.ascii_letters + string.digits + "-_=", 64),
    )
)
_PRINTABLE_SIZE: Final = 94


def _alphabet_size(value: str) -> int:
    """The size of the smallest common alphabet holding every character of `value`."""
    chars = set(value)
    return next(
        (size for alphabet, size in _ALPHABETS if chars <= alphabet), _PRINTABLE_SIZE
    )


def _entropy_per_symbol(value: str) -> float:
    """The order-0 entropy of `value`, bits a symbol, from its own character counts."""
    return -sum(
        n / len(value) * math.log2(n / len(value)) for n in Counter(value).values()
    )


def _is_low_entropy(value: str) -> bool:
    """True if `value` carries too few bits, or uses too little of the alphabet it is written in.

    The yardstick is the alphabet in use: random digits (3.3 bits a symbol) are not refused for
    having fewer distinct characters than base64 would. Short samples of any alphabet repeat
    symbols, so the ratio is against the log of the length when that is smaller.
    """
    bits = _entropy_per_symbol(value)
    best = min(math.log2(_alphabet_size(value)), math.log2(len(value)))
    return bits * len(value) < MIN_ENTROPY_BITS or bits < MIN_ENTROPY_RATIO * best


def _chance_len(value: str, tries: int) -> int:
    """The shortest pattern that a random `value` shows by chance in under `CHANCE_ODDS`.

    `tries` is how many places and shapes the pattern is looked for; each extra symbol cuts the
    odds by the alphabet size. Never below `_RUN_LIMIT`. This keeps the sequence checks from
    refusing random digits (a run of 6 appears in 0.3% of random 256-digit values) while a 6-run
    in a 64-symbol alphabet still counts.
    """
    needed = math.log(tries * len(value) / CHANCE_ODDS) / math.log(
        _alphabet_size(value)
    )
    return max(_RUN_LIMIT, math.ceil(needed))


def _has_a_run(value: str) -> bool:
    """True if one character repeats, or consecutive code points run, for a chance-proof length."""
    limit = _chance_len(value, 3)
    return any(_longest_run(value, step) >= limit for step in (0, 1, -1))


def _interleaves_a_run(value: str) -> bool:
    """True if every 2nd, 3rd or 4th character (any offset, case folded) forms a run.

    `a1b2c3d4...`, `aAbBcC...`, `1q2w3e4r...` and `1qaz2wsx3edc...` hide a sequence between
    filler that the plain run check never sees.
    """
    limit = _chance_len(value, 27)
    return any(
        _longest_run(value[offset::stride].casefold(), step) >= limit
        for stride in (2, 3, 4)
        for offset in range(stride)
        for step in (0, 1, -1)
    )


# Words and constants a person reaches for. One long word with a year, or any two words, is a
# phrase, not a random value; a single short word is not enough (it would occur by chance).
_WEAK_WORDS: Final = (
    "password",
    "changeme",
    "secret",
    "rotate",
    "welcome",
    "letmein",
    "qwerty",
    "admin",
    "prod",
    "token",
    "apikey",
    "evolv",
    "consulting",
    "spring",
    "summer",
    "autumn",
    "winter",
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
    "correct",
    "horse",
    "battery",
    "staple",
)
_YEAR: Final = re.compile(r"(?:19|20)\d\d")
_CONSTANT_DIGITS: Final = (
    "31415926535897932384626433832795",
    "27182818284590452353602874713526",
)
_CONSTANT_RUN: Final = 12


def _is_guessable_text(value: str) -> bool:
    """True if `value` is made of common words, a word and a year, or digits of pi or e."""
    low = value.lower()
    words = {w for w in _WEAK_WORDS if w in low}
    if len(words) >= 2 or (any(len(w) >= 6 for w in words) and _YEAR.search(low)):
        return True
    return any(
        value[i : i + _CONSTANT_RUN] in digits
        for digits in _CONSTANT_DIGITS
        for i in range(len(value) - _CONSTANT_RUN + 1)
    )


def _has_keyboard_walk(value: str) -> bool:
    """True if `value` holds a chance-proof run of keys along a keyboard row, either way."""
    limit = _chance_len(value, 20)
    lowered = value.lower()
    for row in _KEYBOARD_ROWS:
        for text in (row, row[::-1]):
            if any(
                text[i : i + limit] in lowered for i in range(len(text) - limit + 1)
            ):
                return True
    return False


def _check_strength(name: str, value: str, ref: str) -> None:
    """Refuse a secret that is malformed, too short or patterned. Never echoes it.

    These values travel in HTTP headers, so each character must be printable ASCII with no
    whitespace inside (a newline makes httpx raise, a non-ASCII byte fails closed on every
    call, and the backend compares the unstripped value).
    """
    if not all(0x21 <= ord(c) <= 0x7E for c in value):
        raise AuthConfigError(
            f"{name} must contain only printable ASCII characters and no whitespace ({ref}); "
            "rotate it."
        )
    if len(value) < MIN_SHARED_KEY_CHARS:
        raise AuthConfigError(
            f"{name} must be at least {MIN_SHARED_KEY_CHARS} characters ({ref}); rotate it."
        )
    if (
        _is_low_entropy(value)
        or _compresses_well(value)
        or _repeats_a_chunk(value)
        or _has_keyboard_walk(value)
        or _has_a_run(value)
        or _interleaves_a_run(value)
        or _is_guessable_text(value)
    ):
        raise AuthConfigError(
            f"{name} looks guessable or patterned ({ref}): it uses little of its alphabet, repeats "
            "a block, a character, a sequence or a keyboard walk, interleaves one, or is made of "
            "common words, a year or a constant. A random secret is never refused for these "
            "(rarely, by chance: regenerate it). Generate one with `openssl rand -base64 48`; "
            "this check only catches accidents, the generator is the control; rotate it."
        )


def _scheme(url: str | None) -> str:
    return url_scheme(_raw(url))


def _check_internal_tls(settings: Settings, mode: AuthMode) -> None:
    """EC-637 boot refusals for the internal TLS paths. Names the variable, never a value."""
    production = settings.environment == "production"
    redis_tls = _scheme(settings.redis_url) == "rediss"
    be_scheme = _scheme(settings.be_base_url)
    if production and not redis_tls:
        raise AuthConfigError(
            f"{REDIS_URL} must be a rediss:// URL when {ENVIRONMENT}=production (EC-637): "
            "plain redis:// is refused."
        )
    if production:
        parsed = urlparse(_raw(settings.redis_url))
        if not parsed.hostname:
            raise AuthConfigError(f"{REDIS_URL} must name a host (EC-637).")
        if any(name.lower().startswith("ssl_") for name in parse_qs(parsed.query)):
            raise AuthConfigError(
                f"{REDIS_URL} must carry no ssl_* query parameter when {ENVIRONMENT}=production "
                f"(EC-637): TLS trust comes from {INTERNAL_CA_CERT} only."
            )
    if production and mode in ("dual", "platform") and be_scheme != "https":
        raise AuthConfigError(
            f"{BE_BASE_URL} must be an https:// URL when {ENVIRONMENT}=production and {AUTH_MODE}={mode} "
            "(EC-637): any other scheme (plain http://, a bare host) is refused."
        )
    if not (redis_tls or be_scheme == "https"):
        return
    pem = internal_ca_pem(settings)
    if pem is None:
        raise AuthConfigError(
            f"{INTERNAL_CA_CERT} is required when {REDIS_URL} is rediss:// or {BE_BASE_URL} is https:// "
            "(EC-637): set it to the PEM of the internal CA."
        )
    try:
        ssl.create_default_context(cadata=pem)
    except (ssl.SSLError, ValueError) as exc:
        raise AuthConfigError(
            f"{INTERNAL_CA_CERT} is not a valid PEM certificate bundle (EC-637)."
        ) from exc


def resolve_auth_mode(settings: Settings) -> AuthMode:
    """The effective auth mode, or `AuthConfigError` naming the setting that is wrong."""
    mode: AuthMode = settings.auth_mode or DEFAULT_AUTH_MODE
    disabled = settings.dangerously_disable_auth

    if not _raw(settings.redis_url):
        raise AuthConfigError(
            f"{REDIS_URL} is required in every auth mode ({AUTH_MODE}={mode}): rate limiting, the "
            "keycache and the validate-key budget all need it."
        )
    if disabled and mode != "legacy":
        raise AuthConfigError(
            f"{DISABLE_AUTH} is only allowed with {AUTH_MODE}=legacy (no code path may "
            f"disable auth in {mode} mode). Unset {DISABLE_AUTH}."
        )
    if disabled and settings.environment == "production":
        raise AuthConfigError(
            f"{DISABLE_AUTH} is refused when {ENVIRONMENT}=production (S26). "
            f"Unset {DISABLE_AUTH}."
        )
    if mode in ("dual", "platform"):
        # Whitespace-only is missing: a quoting slip must refuse to boot, not boot and
        # then negative-cache and latch every valid user's key.
        missing = [
            name
            for name, value in (
                (f"{BE_BASE_URL}", settings.be_base_url),
                (f"{INTERNAL_AUTH_SECRET}", settings.internal_auth_secret),
            )
            if not _raw(value)
        ]
        if missing:
            raise AuthConfigError(
                f"{AUTH_MODE}={mode} requires {', '.join(missing)} to be set to non-empty values."
            )
        # They key the S14 record MACs and authenticate to the backend (L11).
        _check_strength(
            INTERNAL_AUTH_SECRET, _raw(settings.internal_auth_secret), "S14"
        )
        if _raw(settings.internal_auth_secret_next):
            _check_strength(
                INTERNAL_AUTH_SECRET_NEXT,
                _raw(settings.internal_auth_secret_next),
                "S14",
            )

    _check_internal_tls(settings, mode)

    key = _raw(settings.api_key)
    if mode == "platform" and key:
        raise AuthConfigError(
            f"{API_KEY} must be unset with {AUTH_MODE}=platform: the shared key is "
            "retired in that mode."
        )
    if mode in ("legacy", "dual"):
        if key:
            _check_shared_key(key)
        elif not (mode == "legacy" and disabled):
            raise AuthConfigError(
                f"{API_KEY} is not set and {AUTH_MODE}={mode}: refusing to serve an "
                f"unauthenticated MCP endpoint. Set {API_KEY}."
            )
    return mode


class DualModeVerifier(TokenVerifier):
    """Sends each bearer token, by its shape, to exactly one verifier. Never to both."""

    def __init__(
        self,
        *,
        mode: AuthMode,
        legacy: TokenVerifier | None,
        platform: TokenVerifier | None,
    ) -> None:
        """Wire the verifiers the mode needs; a missing one is an `AuthConfigError`."""
        super().__init__()
        if mode != "platform" and legacy is None:
            raise AuthConfigError(
                f"{AUTH_MODE}={mode} needs the legacy verifier ({API_KEY})"
            )
        if mode != "legacy" and platform is None:
            raise AuthConfigError(f"{AUTH_MODE}={mode} needs the platform verifier")
        self.mode: AuthMode = mode
        self._legacy = legacy
        self._platform = platform

    async def aclose(self) -> None:
        """Close the platform verifier's pooled client, if this mode has one (L3)."""
        close = getattr(self._platform, "aclose", None)
        if close is not None:
            await close()

    async def verify_token(self, token: str) -> AccessToken | None:
        """Dispatch by token shape. An `evc_` token NEVER reaches the legacy verifier."""
        if is_platform_token(token):
            if self.mode == "legacy" or self._platform is None:
                return None
            return await self._platform.verify_token(token)
        if self.mode == "platform" or self._legacy is None:
            return None
        return await self._legacy.verify_token(token)


def build_verifier(settings: Settings, redis: Redis | None) -> TokenVerifier | None:
    """The token verifier for the resolved mode; None ONLY for legacy + the disable flag."""
    mode = resolve_auth_mode(settings)
    if redis is None:
        raise AuthConfigError(
            f"{REDIS_URL} is required in every auth mode: no Redis client."
        )
    if mode == "legacy" and settings.dangerously_disable_auth:
        logger.critical(
            f"{DISABLE_AUTH}=true - the MCP endpoint is UNAUTHENTICATED. "
            "Local tool development only; never set this in a deployed environment."
        )
        return None
    legacy = (
        LegacyKeyVerifier(_raw(settings.api_key))
        if mode in ("legacy", "dual")
        else None
    )
    platform = None
    if mode in ("dual", "platform"):
        platform = PlatformKeyVerifier(
            be_base_url=_raw(settings.be_base_url),
            # The verifier holds the UNWRAPPED secret: it puts the value on the wire, and
            # one unwrap here beats a `.get_secret_value()` at every use site (a missed
            # one sends `**********` as the header and 403s the whole platform path).
            internal_auth_secret=_raw(settings.internal_auth_secret),
            redis=redis,
            settings=settings,
        )
    return DualModeVerifier(mode=mode, legacy=legacy, platform=platform)
