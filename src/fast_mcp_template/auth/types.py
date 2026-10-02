"""Auth names shared by the verifiers, the middleware and credentials.

No imports from this package, so every module can import it without a
cycle. A verifier stamps these claims on the `AccessToken` it returns;
the rate limiter and the audit layer read them back.
"""

from __future__ import annotations

from typing import Final, Literal

#: Which credential family authenticated the request. `legacy` is a
#: shared key (limited per client IP); `platform` is a per-user key
#: (limited per user AND per IP).
AuthPath = Literal["legacy", "platform"]

CLAIM_AUTH_PATH: Final = "auth_path"
CLAIM_USER_ID: Final = "user_id"
CLAIM_SCOPES: Final = "scopes"
CLAIM_RATE_LIMIT: Final = "rate_limit"
CLAIM_KEY_FP: Final = "key_fp"
