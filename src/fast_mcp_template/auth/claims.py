"""Read the verified claims back out of an ASGI scope.

fastmcp's auth layer stores the `AccessToken` the verifier returned on
`scope["user"]`. The middleware that sits inside that layer (the rate
limiter) or reads it at response time (the audit layer) uses these.
"""

from __future__ import annotations

from typing import Any, Literal

from starlette.types import Scope

from fast_mcp_template.auth.types import CLAIM_AUTH_PATH, AuthPath


def claims_of(scope: Scope) -> dict[str, Any]:
    """Return the claims of the authenticated user in `scope`, or {}."""
    token = getattr(scope.get("user"), "access_token", None)
    claims = getattr(token, "claims", None)
    return claims if isinstance(claims, dict) else {}


def auth_path_of(scope: Scope) -> AuthPath | Literal["none"]:
    """Return the `auth_path` claim of the user, else "none"."""
    path = claims_of(scope).get(CLAIM_AUTH_PATH)
    return path if path in ("legacy", "platform") else "none"
