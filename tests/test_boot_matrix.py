"""One test per boot refusal in `dual.resolve_auth_mode` (plan T-A3, M2.8).

Every refusal is an `AuthConfigError` whose message names the variable to fix.
"""

import logging
from collections.abc import Callable
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis
from pydantic import SecretStr

from fast_mcp_template.auth.dual import (
    DualModeVerifier,
    _check_strength,
    build_verifier,
    resolve_auth_mode,
)
from fast_mcp_template.auth.platform import PlatformKeyVerifier
from fast_mcp_template.auth.types import AuthConfigError, AuthMode
from fast_mcp_template.config import Settings, env_name

MakeSettings = Callable[..., Settings]
MODES: tuple[AuthMode, ...] = ("legacy", "dual", "platform")
SHARED = "shared-Kq7vR2mXz9LpW4nYt6BdJ8sHc3FgUa5e"  # 47 chars, not evc_-shaped
REDIS = "redis://redis:6379/0"
BE: dict[str, Any] = {
    "be_base_url": "http://backend:8000",
    "internal_auth_secret": "s3cret-Hv7Qm2Zx9Lp4Wn8Tb6Jd3Fs5Yc1Ra",
}


def ok_kwargs(mode: AuthMode) -> dict[str, Any]:
    """A settings set that boots in `mode`."""
    kw: dict[str, Any] = {"auth_mode": mode, "redis_url": REDIS}
    if mode != "platform":
        kw["api_key"] = SHARED
    if mode != "legacy":
        kw.update(BE)
    return kw


def refused(make: MakeSettings, name: str, **kw: Any) -> None:
    with pytest.raises(AuthConfigError) as exc:
        resolve_auth_mode(make(**kw))
    assert name in str(exc.value), f"the message must name {name}: {exc.value}"


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("blank", [None, "", "  "])
def test_redis_required_in_every_mode(
    make_settings: MakeSettings, mode: AuthMode, blank: Any
) -> None:
    refused(
        make_settings,
        "MCP_TEMPLATE_REDIS_URL",
        **{**ok_kwargs(mode), "redis_url": blank},
    )


@pytest.mark.parametrize("mode", ["dual", "platform"])
@pytest.mark.parametrize("missing", ["be_base_url", "internal_auth_secret"])
def test_dual_requires_be_and_secret(
    make_settings: MakeSettings, mode: AuthMode, missing: str
) -> None:
    refused(make_settings, env_name(missing), **{**ok_kwargs(mode), missing: None})


def test_dual_names_every_missing_field(make_settings: MakeSettings) -> None:
    kw = {**ok_kwargs("dual"), "be_base_url": None, "internal_auth_secret": None}
    refused(make_settings, "MCP_TEMPLATE_BE_BASE_URL", **kw)
    refused(make_settings, "MCP_TEMPLATE_INTERNAL_AUTH_SECRET", **kw)


def test_platform_forbids_shared_key(make_settings: MakeSettings) -> None:
    refused(
        make_settings, "MCP_TEMPLATE_API_KEY", **ok_kwargs("platform"), api_key=SHARED
    )


@pytest.mark.parametrize("mode", ["legacy", "dual"])
def test_shared_key_with_platform_prefix_is_refused(
    make_settings: MakeSettings, mode: AuthMode
) -> None:
    """The key passes every strength floor, so only the prefix check can refuse it (R3 #38)."""
    key = "evc_Xk9Qm2Vb7Lp4Zr8Tn3Wd6Hc1Js5Gf0Ya"
    _check_strength(
        "MCP_TEMPLATE_API_KEY", key, "S8"
    )  # would raise if the floor also refused it
    with pytest.raises(AuthConfigError, match="starts with 'evc_'"):
        resolve_auth_mode(make_settings(**{**ok_kwargs(mode), "api_key": key}))


@pytest.mark.parametrize("field", ["be_base_url", "internal_auth_secret"])
@pytest.mark.parametrize("blank", [" ", "\t\n"])
def test_whitespace_secret_is_missing(
    make_settings: MakeSettings, field: str, blank: str
) -> None:
    """A quoting slip must refuse to boot, not boot and latch every valid user's key."""
    refused(make_settings, field.upper(), **{**ok_kwargs("dual"), field: blank})


@pytest.mark.parametrize("mode", ["dual", "platform"])
def test_disable_auth_only_in_legacy(
    make_settings: MakeSettings, mode: AuthMode
) -> None:
    refused(
        make_settings,
        "MCP_TEMPLATE_DANGEROUSLY_DISABLE_AUTH",
        **ok_kwargs(mode),
        dangerously_disable_auth=True,
    )


def test_legacy_default_when_unset(make_settings: MakeSettings) -> None:
    kw = ok_kwargs("legacy")
    del kw["auth_mode"]
    assert resolve_auth_mode(make_settings(**kw)) == "legacy"


@pytest.mark.parametrize(
    "key",
    [
        None,
        "",
        "   ",
        "short",
        "abcdefghijklmnopqrstuvwxyz01234",
        "  abcdefghijklmnopqrstuvwxyz01234  ",
        "a b " * 7,
    ],
)
def test_short_or_blank_shared_key_refuses_to_boot(
    make_settings: MakeSettings, key: str | None
) -> None:
    refused(
        make_settings, "MCP_TEMPLATE_API_KEY", **{**ok_kwargs("legacy"), "api_key": key}
    )
    refused(
        make_settings, "MCP_TEMPLATE_API_KEY", **{**ok_kwargs("dual"), "api_key": key}
    )


def test_a_32_character_key_boots(make_settings: MakeSettings) -> None:
    assert (
        resolve_auth_mode(
            make_settings(
                **{**ok_kwargs("legacy"), "api_key": "Kq7vR2mXz9LpW4nYt6BdJ8sHc3FgUa5e"}
            )
        )
        == "legacy"
    )


@pytest.mark.parametrize("mode", MODES)
def test_disable_auth_refused_when_environment_is_production(
    make_settings: MakeSettings, mode: AuthMode
) -> None:
    kw = {
        **ok_kwargs(mode),
        "dangerously_disable_auth": True,
        "environment": "production",
    }
    refused(make_settings, "MCP_TEMPLATE_DANGEROUSLY_DISABLE_AUTH", **kw)
    if (
        mode == "legacy"
    ):  # the legacy cell fails ONLY because of MCP_TEMPLATE_ENVIRONMENT
        refused(make_settings, "MCP_TEMPLATE_ENVIRONMENT", **kw)
        assert (
            resolve_auth_mode(make_settings(**{**kw, "environment": "local"}))
            == "legacy"
        )


def test_whitespace_next_secret_is_unset(make_settings: MakeSettings) -> None:
    """S13: MCP_TEMPLATE_INTERNAL_AUTH_SECRET_NEXT="  " is treated as unset."""
    verifier = build_verifier(
        make_settings(**ok_kwargs("dual"), internal_auth_secret_next=SecretStr("  ")),
        FakeRedis(decode_responses=True),
    )
    assert isinstance(verifier, DualModeVerifier)
    platform = verifier._platform
    assert isinstance(platform, PlatformKeyVerifier) and platform._next_secret is None


def test_a_real_next_secret_is_kept(make_settings: MakeSettings) -> None:
    verifier = build_verifier(
        make_settings(
            **ok_kwargs("dual"),
            internal_auth_secret_next=SecretStr(" next-Bt5Yc1Ra8Nv3Kq7Hm2Zx9Lp4Wd6Jf "),
        ),
        FakeRedis(decode_responses=True),
    )
    assert isinstance(verifier, DualModeVerifier)
    assert isinstance(verifier._platform, PlatformKeyVerifier)
    assert verifier._platform._next_secret == "next-Bt5Yc1Ra8Nv3Kq7Hm2Zx9Lp4Wd6Jf"


# ------------------------------------------------------------------- positive builds


@pytest.mark.parametrize("mode", MODES)
def test_positive_build_per_mode(make_settings: MakeSettings, mode: AuthMode) -> None:
    verifier = build_verifier(
        make_settings(**ok_kwargs(mode)), FakeRedis(decode_responses=True)
    )
    assert isinstance(verifier, DualModeVerifier) and verifier.mode == mode
    assert (verifier._legacy is not None) is (mode != "platform")
    assert isinstance(verifier._platform, PlatformKeyVerifier) is (mode != "legacy")


def test_platform_verifier_is_built_with_the_real_secret_not_the_mask(
    make_settings: MakeSettings,
) -> None:
    """A missed `.get_secret_value()` does not raise: the BE would 403 every request."""
    verifier = build_verifier(
        make_settings(**ok_kwargs("dual")), FakeRedis(decode_responses=True)
    )
    assert isinstance(verifier, DualModeVerifier)
    assert isinstance(verifier._platform, PlatformKeyVerifier)
    assert (
        verifier._platform.internal_auth_secret
        == "s3cret-Hv7Qm2Zx9Lp4Wn8Tb6Jd3Fs5Yc1Ra"
    )
    assert verifier._platform.be_base_url == "http://backend:8000"


def test_build_requires_a_redis_client(make_settings: MakeSettings) -> None:
    with pytest.raises(AuthConfigError, match="MCP_TEMPLATE_REDIS_URL"):
        build_verifier(make_settings(**ok_kwargs("dual")), None)


def test_rediss_url_boots(make_settings: MakeSettings, internal_ca: Any) -> None:
    kw = {
        **ok_kwargs("dual"),
        "redis_url": "rediss://cache.internal:6380/0",
        "internal_ca_cert": internal_ca.ca_pem,
    }
    assert resolve_auth_mode(make_settings(**kw)) == "dual"


def test_disable_flag_is_the_only_path_to_no_verifier(
    make_settings: MakeSettings, caplog: pytest.LogCaptureFixture
) -> None:
    kw = {"auth_mode": "legacy", "redis_url": REDIS, "dangerously_disable_auth": True}
    with caplog.at_level(logging.CRITICAL):
        assert (
            build_verifier(make_settings(**kw), FakeRedis(decode_responses=True))
            is None
        )
    assert "MCP_TEMPLATE_DANGEROUSLY_DISABLE_AUTH" in caplog.text


def test_none_only_for_legacy_plus_the_flag(make_settings: MakeSettings) -> None:
    """Exhaustive over mode x key x flag x environment: None exactly for legacy+flag+local."""
    seen_none = 0
    for mode in MODES:
        for has_key in (True, False):
            for flag in (True, False):
                for env in ("local", "production"):
                    kw: dict[str, Any] = {
                        "auth_mode": mode,
                        "redis_url": REDIS,
                        "dangerously_disable_auth": flag,
                        "environment": env,
                        "api_key": SHARED if has_key else None,
                    }
                    if mode != "legacy":
                        kw.update(BE)
                    try:
                        verifier = build_verifier(make_settings(**kw), FakeRedis())
                    except AuthConfigError:
                        continue
                    if verifier is None:
                        seen_none += 1
                        assert mode == "legacy" and flag and env == "local"
    assert seen_none == 2, f"legacy+flag+local with and without a key, got {seen_none}"


@pytest.mark.parametrize("mode", ["dual", "platform"])
@pytest.mark.parametrize(
    "secret,why",
    [
        ("short", "length"),
        ("ab" * 20, "distinct"),
        ("a" * 40, "distinct"),
        ("x" * 31, "length"),
    ],
)
def test_weak_internal_auth_secret_is_refused(
    make_settings: MakeSettings, mode: AuthMode, secret: str, why: str
) -> None:
    """L11: the secret keys the S14 MACs; a short or patterned one must not boot."""
    kw = {**ok_kwargs(mode), "internal_auth_secret": SecretStr(secret)}
    with pytest.raises(AuthConfigError) as exc:
        resolve_auth_mode(make_settings(**kw))
    assert "MCP_TEMPLATE_INTERNAL_AUTH_SECRET" in str(exc.value)
    assert secret not in str(exc.value), "the refusal never echoes the secret"


def test_weak_next_secret_is_refused_but_blank_next_is_not(
    make_settings: MakeSettings,
) -> None:
    """L11: NEXT is checked only when set."""
    weak = {**ok_kwargs("dual"), "internal_auth_secret_next": SecretStr("tooshort")}
    refused(make_settings, "MCP_TEMPLATE_INTERNAL_AUTH_SECRET_NEXT", **weak)
    blank = {**ok_kwargs("dual"), "internal_auth_secret_next": SecretStr("  ")}
    assert resolve_auth_mode(make_settings(**blank)) == "dual"


@pytest.mark.parametrize("key", ["a" * 32, "ab" * 20, "01234" * 8])
def test_patterned_shared_key_is_refused(make_settings: MakeSettings, key: str) -> None:
    """N5: length alone is not entropy."""
    refused(
        make_settings, "MCP_TEMPLATE_API_KEY", **{**ok_kwargs("legacy"), "api_key": key}
    )


# ------------------------------------------------------------ floors, R2 L2


@pytest.mark.parametrize("mode", ["dual", "platform"])
def test_the_floor_is_entropy_against_the_alphabet_not_a_distinct_character_count(
    make_settings: MakeSettings, mode: AuthMode
) -> None:
    """R5 L2: 4 random symbols over 40 characters is skewed (2 bits a symbol) and refused; 32
    random digits (the same 10 distinct characters the old count wanted, 3.3 bits) are accepted."""
    skewed = "vvvqqvqKv7qKKvvqKKKKqqKv7vqq7vKKv7vK77q7"
    digits = "52601815908301661318609139099603"
    for field in ("internal_auth_secret", "api_key"):
        if field == "api_key" and mode == "platform":
            continue
        ok_kw = {**ok_kwargs(mode)}
        wrap = SecretStr if field == "internal_auth_secret" else str
        refused(make_settings, field.upper(), **{**ok_kw, field: wrap(skewed)})
        assert (
            resolve_auth_mode(make_settings(**{**ok_kw, field: wrap(digits)})) == mode
        )


@pytest.mark.parametrize(
    "secret",
    [
        "Kq7vR2mXz9LpW4nYt6\nBdJ8sHc3FgUa5eNb1",  # newline inside
        "Kq7vR2mXz9LpW4nYt6\tBdJ8sHc3FgUa5eNb1",  # tab inside
        "Kq7vR2mXz9LpW4nYt6 BdJ8sHc3FgUa5eNb1",  # space inside
        "éééééKq7vR2mXz9LpW4nYt6BdJ8sHc3FgUa5e",  # non-ASCII
        "Kq7vR2mXz9LpW4nYt6BdJ8sHc3Fg\x00Ua5eNb1",  # NUL
        "Kq7vR2mXz9LpW4nYt6BdJ8sHc3Fg\x7fUa5eNb1",  # DEL
    ],
    ids=["newline", "tab", "space", "non-ascii", "nul", "del"],
)
@pytest.mark.parametrize(
    "field", ["internal_auth_secret", "internal_auth_secret_next", "api_key"]
)
def test_a_secret_with_a_control_blank_or_non_ascii_character_is_refused(
    make_settings: MakeSettings, field: str, secret: str
) -> None:
    """They travel in headers: a newline breaks httpx, a non-ASCII byte fails every call."""
    kw = {
        **ok_kwargs("dual"),
        field: SecretStr(secret) if "secret" in field else secret,
    }
    with pytest.raises(AuthConfigError) as exc:
        resolve_auth_mode(make_settings(**kw))
    assert field.upper() in str(exc.value)
    assert secret not in str(exc.value) and secret.strip() not in str(exc.value)


@pytest.mark.parametrize(
    "secret",
    [
        "abcdefghij" * 4,  # one block repeated
        "abcdefghij" + "a" * 30,  # 10 distinct, long run
        "Kq7vR2mXz9LpW4nYt6BdJ8sHc3Fg" + "abcdefgh",  # ascending sequence
        "Kq7vR2mXz9LpW4nYt6BdJ8sHc3Fg" + "hgfedcba",  # descending sequence
        "Kq7vR2mXz9LpW4nYt6BdJ8sHc3Fg" + "zzzzzz",  # one character repeated
        "Kq7vR2mXz9" * 4,
    ],
    ids=["block", "run", "ascending", "descending", "repeat", "block-random"],
)
def test_an_obviously_patterned_secret_is_refused_in_every_field(
    make_settings: MakeSettings, secret: str
) -> None:
    refused(
        make_settings,
        "MCP_TEMPLATE_INTERNAL_AUTH_SECRET",
        **{**ok_kwargs("dual"), "internal_auth_secret": SecretStr(secret)},
    )
    refused(
        make_settings,
        "MCP_TEMPLATE_API_KEY",
        **{**ok_kwargs("legacy"), "api_key": secret},
    )


def test_a_random_looking_secret_with_short_runs_boots(
    make_settings: MakeSettings,
) -> None:
    """No false positive: runs of 5 and a long random value are accepted."""
    secret = "Kq7vR2mXz9LpW4nYt6BdJ8sHc3FgUa5eNb1aaaaa12345"
    assert (
        resolve_auth_mode(
            make_settings(
                **{**ok_kwargs("dual"), "internal_auth_secret": SecretStr(secret)}
            )
        )
        == "dual"
    )


@pytest.mark.parametrize(
    "field", ["internal_auth_secret", "internal_auth_secret_next", "api_key"]
)
def test_the_length_floor_is_exactly_thirty_two(
    make_settings: MakeSettings, field: str
) -> None:
    """Mutation: floor 32 -> 31 survived once `"x" * 31` also tripped the pattern floor."""
    base = "Kq7vR2mXz9LpW4nYt6BdJ8sHc3FgUa5eNb1"
    wrap = (lambda v: SecretStr(v)) if "secret" in field else (lambda v: v)
    kw = {**ok_kwargs("dual")}
    refused(make_settings, field.upper(), **{**kw, field: wrap(base[:31])})
    assert resolve_auth_mode(make_settings(**{**kw, field: wrap(base[:32])})) == "dual"
