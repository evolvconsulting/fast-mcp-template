"""Auth names shared by the verifiers, the middleware and credentials.

No imports from this package, so every module can import it without a
cycle. A verifier stamps these claims on the `AccessToken` it returns;
the rate limiter and the audit layer read them back.
"""

from __future__ import annotations

import hashlib
from typing import Final, Literal

#: Which credential family authenticated the request. `legacy` is a
#: shared key (limited per client IP); `platform` is a per-user key
#: (limited per user AND per IP).
AuthPath = Literal["legacy", "platform"]
#: `legacy` accepts only the shared key; `dual` accepts both (the
#: cutover
#: stage); `platform` accepts only per-user keys.
AuthMode = Literal["legacy", "dual", "platform"]
AUTH_MODES: Final[tuple[AuthMode, ...]] = ("legacy", "dual", "platform")
DEFAULT_AUTH_MODE: Final[AuthMode] = "legacy"

CLAIM_AUTH_PATH: Final = "auth_path"
CLAIM_USER_ID: Final = "user_id"
CLAIM_SCOPES: Final = "scopes"
CLAIM_RATE_LIMIT: Final = "rate_limit"
CLAIM_KEY_FP: Final = "key_fp"

LEGACY_CLIENT_ID: Final = "legacy"
PLATFORM_CLIENT_ID_PREFIX: Final = "platform:"
PLATFORM_TOKEN_PREFIX: Final = "evc_"  # noqa: S105 - a key-shape prefix, not a secret


class AuthConfigError(RuntimeError):
    """Every boot refusal: the message names the variable to fix."""


def is_platform_token(token: str) -> bool:
    """Return True for a bearer token shaped like a platform key."""
    return token.startswith(PLATFORM_TOKEN_PREFIX)


def key_fingerprint(secret: str) -> str:
    """Return eight hex characters identifying a key in logs."""
    return hashlib.sha256(secret.encode()).hexdigest()[:8]
