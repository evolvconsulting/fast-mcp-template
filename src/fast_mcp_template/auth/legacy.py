"""Legacy shared-key authentication for the MCP endpoint.

- Timing-safe comparison to prevent timing attacks.
- No lockout and no counters: a global lockout let any unauthenticated
caller lock the
  shared key out for everyone. The per-IP alert lives in
  `AuthAuditMiddleware`.
"""

import hmac

from fastmcp.server.auth import AccessToken, TokenVerifier

from fast_mcp_template.auth.types import (
    CLAIM_AUTH_PATH,
    CLAIM_KEY_FP,
    LEGACY_CLIENT_ID,
    key_fingerprint,
)


class LegacyKeyVerifier(TokenVerifier):
    """Verifies the one shared key and stamps the legacy claims."""

    def __init__(self, api_key: str) -> None:
        """Hold the shared key as bytes, plus its log fingerprint."""
        super().__init__()
        self._api_key = api_key.encode()
        self._key_fp = key_fingerprint(api_key)

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the legacy `AccessToken` for the key, else None."""
        # Bytes, so a non-ASCII token is a plain mismatch and never a
        # TypeError.
        if not hmac.compare_digest(token.encode(), self._api_key):
            return None
        return AccessToken(
            token=token,
            client_id=LEGACY_CLIENT_ID,
            scopes=[],
            expires_at=None,
            claims={CLAIM_AUTH_PATH: "legacy", CLAIM_KEY_FP: self._key_fp},
        )
