"""`DualModeVerifier` sends each token to exactly one verifier (plan T-A3, M2.8)."""

import pytest
from fastmcp.server.auth import AccessToken, TokenVerifier

from fast_mcp_template.auth.dual import DualModeVerifier
from fast_mcp_template.auth.types import AuthConfigError, AuthMode


class Stub(TokenVerifier):
    def __init__(self, result: AccessToken | None) -> None:
        super().__init__()
        self.calls, self.result = 0, result

    async def verify_token(self, token: str) -> AccessToken | None:
        self.calls += 1
        return self.result


def tok(path: str) -> AccessToken:
    return AccessToken(
        token="t",
        client_id=path,
        scopes=[],
        expires_at=None,
        claims={"auth_path": path},
    )


@pytest.mark.parametrize(
    "mode,token,l_ok,p_ok,expect,lc,pc",
    [
        ("legacy", "shared", True, True, "legacy", 1, 0),
        ("legacy", "evc_live_x", True, True, None, 0, 0),
        ("dual", "shared", True, True, "legacy", 1, 0),
        ("dual", "evc_live_x", True, True, "platform", 0, 1),
        ("dual", "shared", False, True, None, 1, 0),
        ("dual", "evc_live_x", True, False, None, 0, 1),
        ("platform", "shared", True, True, None, 0, 0),
        ("platform", "evc_live_x", True, True, "platform", 0, 1),
    ],
)
async def test_dispatch_matrix(
    mode: AuthMode,
    token: str,
    l_ok: bool,
    p_ok: bool,
    expect: str | None,
    lc: int,
    pc: int,
) -> None:
    legacy, platform = (
        Stub(tok("legacy") if l_ok else None),
        Stub(tok("platform") if p_ok else None),
    )
    v = DualModeVerifier(
        mode=mode,
        legacy=None if mode == "platform" else legacy,
        platform=None if mode == "legacy" else platform,
    )
    result = await v.verify_token(token)
    assert (result.claims["auth_path"] if result else None) == expect
    assert (legacy.calls, platform.calls) == (lc, pc)


async def test_dispatch_prefix_collision_is_platform_only() -> None:
    legacy, platform = Stub(tok("legacy")), Stub(None)
    v = DualModeVerifier(mode="dual", legacy=legacy, platform=platform)
    assert await v.verify_token("evc_looks_like_a_shared_key") is None
    assert legacy.calls == 0


def test_missing_verifier_for_mode_is_config_error() -> None:
    with pytest.raises(AuthConfigError):
        DualModeVerifier(mode="dual", legacy=None, platform=Stub(None))
    with pytest.raises(AuthConfigError):
        DualModeVerifier(mode="dual", legacy=Stub(None), platform=None)
    with pytest.raises(AuthConfigError):
        DualModeVerifier(mode="legacy", legacy=None, platform=None)
    with pytest.raises(AuthConfigError):
        DualModeVerifier(mode="platform", legacy=None, platform=None)


async def test_mode_is_exposed() -> None:
    legacy = Stub(tok("legacy"))
    assert (
        DualModeVerifier(mode="legacy", legacy=legacy, platform=None).mode == "legacy"
    )


async def test_mode_guards_hold_even_when_the_wiring_is_wider_than_the_mode() -> None:
    """L12 (#36, #37): a verifier wired for a mode it is not in is never consulted."""
    legacy, platform = Stub(tok("legacy")), Stub(tok("platform"))
    in_platform = DualModeVerifier(mode="platform", legacy=legacy, platform=platform)
    assert await in_platform.verify_token("shared") is None
    assert legacy.calls == 0, "platform mode must not reach the legacy verifier"
    in_legacy = DualModeVerifier(mode="legacy", legacy=legacy, platform=platform)
    assert await in_legacy.verify_token("evc_live_x") is None
    assert platform.calls == 0, "legacy mode must not reach the platform verifier"
