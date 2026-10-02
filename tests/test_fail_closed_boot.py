"""Fail-closed verifier construction (§4.2(b)/§6.3) and the D6 base-URL seams."""

import logging
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis
from fastmcp.server.auth import TokenVerifier
from pydantic import SecretStr

from fast_mcp_template.auth import key_format
from fast_mcp_template.auth.dual import DualModeVerifier, build_verifier
from fast_mcp_template.auth.legacy import LegacyKeyVerifier
from fast_mcp_template.auth.platform import PlatformKeyVerifier
from fast_mcp_template.auth.types import AuthConfigError
from fast_mcp_template.config import Settings, log_test_overrides

# ------------------------------------------------------------- dual.build_verifier

SHARED = "shared-Kq7vR2mXz9LpW4nYt6BdJ8sHc3FgUa5e"
MCP_TEMPLATE_REDIS_URL = "redis://redis:6379/0"
PLATFORM_OK: dict[str, Any] = dict(
    auth_mode="platform",
    api_key=None,  # conftest sets one in the environment
    be_base_url="http://backend:8000",
    internal_auth_secret="s3cret-Hv7Qm2Zx9Lp4Wn8Tb6Jd3Fs5Yc1Ra",
    redis_url=MCP_TEMPLATE_REDIS_URL,
)


def build(**kw: Any) -> TokenVerifier | None:
    return build_verifier(Settings(**kw), FakeRedis(decode_responses=True))


def test_platform_mode_builds_the_platform_verifier() -> None:
    provider = build(**PLATFORM_OK)
    assert isinstance(provider, DualModeVerifier) and provider.mode == "platform"
    assert isinstance(provider._platform, PlatformKeyVerifier)


@pytest.mark.parametrize(
    "missing", ["be_base_url", "internal_auth_secret", "redis_url"]
)
def test_platform_mode_refuses_to_boot_with_a_missing_field(missing: str) -> None:
    with pytest.raises(AuthConfigError) as exc:
        build(**{**PLATFORM_OK, missing: None})
    assert missing.upper() in str(exc.value), (
        "the error must name the missing variable (§6.3)"
    )


def test_legacy_mode_with_a_key_uses_the_shared_key_verifier() -> None:
    """The shared MCP_TEMPLATE_API_KEY keeps working exactly as today."""
    provider = build(api_key=SHARED, redis_url=MCP_TEMPLATE_REDIS_URL)
    assert isinstance(provider, DualModeVerifier) and provider.mode == "legacy"
    assert isinstance(provider._legacy, LegacyKeyVerifier)


def test_legacy_mode_without_a_key_is_a_startup_error() -> None:
    """The former fail-open branch is closed."""
    with pytest.raises(AuthConfigError) as exc:
        build(api_key=None, redis_url=MCP_TEMPLATE_REDIS_URL)
    assert "MCP_TEMPLATE_API_KEY" in str(exc.value)


async def test_platform_key_is_not_accepted_by_the_legacy_verifier() -> None:
    """A platform-shaped token never reaches the shared-key comparison."""
    provider = build(api_key=SHARED, redis_url=MCP_TEMPLATE_REDIS_URL)
    assert provider is not None
    assert await provider.verify_token(key_format.mint_key()) is None


# ----------------------------------------------------- the one explicit escape


def test_dangerous_flag_is_the_only_path_to_no_auth(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.CRITICAL):
        assert (
            build(dangerously_disable_auth=True, redis_url=MCP_TEMPLATE_REDIS_URL)
            is None
        )
    assert caplog.text.strip(), "nothing was logged at all"
    assert "MCP_TEMPLATE_DANGEROUSLY_DISABLE_AUTH" in caplog.text


def test_platform_mode_refuses_to_boot_with_the_dangerous_flag() -> None:
    """§6.3: a leftover MCP_TEMPLATE_DANGEROUSLY_DISABLE_AUTH must not disarm platform mode."""
    with pytest.raises(AuthConfigError) as exc:
        build(**PLATFORM_OK, dangerously_disable_auth=True)
    assert "MCP_TEMPLATE_DANGEROUSLY_DISABLE_AUTH" in str(exc.value)


@pytest.mark.parametrize(
    "missing", ["be_base_url", "internal_auth_secret", "redis_url"]
)
@pytest.mark.parametrize("blank", ["", " ", "\t\n"])
def test_whitespace_only_required_settings_are_missing(
    missing: str, blank: str
) -> None:
    """A quoting slip must refuse to boot, not boot and latch every valid key."""
    with pytest.raises(AuthConfigError) as exc:
        build(**{**PLATFORM_OK, missing: blank})
    assert missing.upper() in str(exc.value)


# ------------------------------------------------------------------ test seams


def test_a_set_test_flag_logs_critical(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.CRITICAL):
        log_test_overrides(Settings(test_emit_canary_secret_log=True))
    lines = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(lines) == 1
    assert (
        "TEST OVERRIDE ACTIVE: test_emit_canary_secret_log=True"
        in lines[0].getMessage()
    )


def test_every_test_field_is_announced(caplog: pytest.LogCaptureFixture) -> None:
    """Derived from model_fields: adding or renaming a `test_*` setting cannot go quiet."""
    test_fields = [f for f in Settings.model_fields if f.startswith("test_")]
    assert test_fields, "the population is empty: this test checks nothing"
    assert "test_emit_canary_secret_log" in test_fields
    truthy: dict[str, Any] = {
        f: (True if Settings.model_fields[f].annotation is bool else "x")
        for f in test_fields
    }
    with caplog.at_level(logging.CRITICAL):
        log_test_overrides(Settings(**truthy))
    announced = {
        r.getMessage().split("TEST OVERRIDE ACTIVE: ")[1].split("=")[0]
        for r in caplog.records
    }
    assert announced == set(test_fields)


def test_unset_test_overrides_log_nothing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.CRITICAL):
        log_test_overrides(Settings())
    assert caplog.records == []


# ------------------------------------------------------------- env-var binding
# `Settings` uses extra="forbid" for init, but the ENVIRONMENT binding is
# by prefix: a wrong env var name is silently ignored, so each is pinned.


@pytest.mark.parametrize(
    "env_name,field,raw,expected",
    [
        ("MCP_TEMPLATE_AUTH_MODE", "auth_mode", "dual", "dual"),
        (
            "MCP_TEMPLATE_BE_BASE_URL",
            "be_base_url",
            "http://backend:8000",
            "http://backend:8000",
        ),
        (
            "MCP_TEMPLATE_INTERNAL_AUTH_SECRET",
            "internal_auth_secret",
            "s3cret-Hv7Qm2Zx9Lp4Wn8Tb6Jd3Fs5Yc1Ra",
            SecretStr("s3cret-Hv7Qm2Zx9Lp4Wn8Tb6Jd3Fs5Yc1Ra"),
        ),
        (
            "MCP_TEMPLATE_REDIS_URL",
            "redis_url",
            "redis://redis:6379/0",
            "redis://redis:6379/0",
        ),
        (
            "MCP_TEMPLATE_AWS_ENDPOINT_URL",
            "aws_endpoint_url",
            "http://localstack:4566",
            "http://localstack:4566",
        ),
        ("MCP_TEMPLATE_MCP_SECRETS_PREFIX", "mcp_secrets_prefix", "x/y", "x/y"),
        ("MCP_TEMPLATE_KEY_CACHE_TTL_SECONDS", "key_cache_ttl_seconds", "45", 45),
        ("MCP_TEMPLATE_VAULT_CACHE_TTL_SECONDS", "vault_cache_ttl_seconds", "90", 90),
        (
            "MCP_TEMPLATE_DANGEROUSLY_DISABLE_AUTH",
            "dangerously_disable_auth",
            "true",
            True,
        ),
        (
            "MCP_TEMPLATE_DEFAULT_RATE_LIMIT_PER_USER",
            "default_rate_limit_per_user",
            "120",
            120,
        ),
        ("MCP_TEMPLATE_RATE_LIMIT_WINDOW_S", "rate_limit_window_s", "30", 30),
        (
            "MCP_TEMPLATE_TEST_EMIT_CANARY_SECRET_LOG",
            "test_emit_canary_secret_log",
            "true",
            True,
        ),
    ],
)
def test_every_new_setting_binds_from_its_env_var(
    monkeypatch: pytest.MonkeyPatch, env_name: str, field: str, raw: str, expected: Any
) -> None:
    baseline = getattr(Settings(), field)
    assert baseline != expected, f"{field}: the test value equals the default (vacuous)"
    monkeypatch.setenv(env_name, raw)
    assert getattr(Settings(), field) == expected


# ------------------------------------------------- internal_auth_secret masking


def test_internal_auth_secret_never_renders_in_the_clear() -> None:
    """§7.3 rule 3: a config repr / traceback / `model_dump()` must not print it.

    The `.get_secret_value()` arm is a positive control: without it this test
    would also pass against a field that had simply lost the value.
    """
    settings = Settings(**PLATFORM_OK)
    assert settings.internal_auth_secret is not None
    assert (
        settings.internal_auth_secret.get_secret_value()
        == "s3cret-Hv7Qm2Zx9Lp4Wn8Tb6Jd3Fs5Yc1Ra"
    )
    for rendered in (
        repr(settings),
        str(settings),
        repr(settings.internal_auth_secret),
        str(settings.internal_auth_secret),
        str(settings.model_dump()),
    ):
        assert "s3cret-Hv7Qm2Zx9Lp4Wn8Tb6Jd3Fs5Yc1Ra" not in rendered, rendered


def test_the_verifier_is_built_with_the_real_secret_not_the_mask() -> None:
    """The catastrophic failure mode: a missed `.get_secret_value()` does not raise.

    `SecretStr.__str__` is `'**********'`, so the gateway would boot happily and
    send that literal as `X-Internal-Auth` - and the BE would answer 403 to every
    single request. Nothing else in the suite would notice, because "403 on a
    wrong secret" is also the correct behaviour.
    """
    provider = build(**PLATFORM_OK)
    assert isinstance(provider, DualModeVerifier)
    assert isinstance(provider._platform, PlatformKeyVerifier)
    assert (
        provider._platform.internal_auth_secret
        == "s3cret-Hv7Qm2Zx9Lp4Wn8Tb6Jd3Fs5Yc1Ra"
    )
