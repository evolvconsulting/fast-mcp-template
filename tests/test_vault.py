"""The vault client: per-user downstream credentials from Secrets Manager.

Runs against moto (an in-process Secrets Manager), so the real boto3
code path, its error mapping and its timeouts budget are exercised.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from fast_mcp_template.auth import vault as vault_module
from fast_mcp_template.auth.vault import (
    READINESS_SENTINEL_USER,
    VAULT_BUDGET_SECONDS,
    VAULT_MAX_RETRIES,
    VaultClient,
    VaultUnavailableError,
    build_vault,
    check_vault,
    fingerprint,
)
from fast_mcp_template.config import Settings
from fast_mcp_template.http.health import CheckResult

USER = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def secrets(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        yield boto3.client("secretsmanager")


def make(**kw: Any) -> VaultClient:
    return VaultClient(secrets_prefix="mcp", server_key="svc", endpoint_url=None, **kw)


async def test_a_stored_credential_is_returned(secrets: Any) -> None:
    secrets.create_secret(
        Name=f"mcp/users/{USER}/svc",
        SecretString=json.dumps({"organization": "org", "token": "tok"}),
    )
    assert await make().get_credentials(USER) == {
        "organization": "org",
        "token": "tok",
    }


async def test_absence_is_none_not_an_error(
    secrets: Any, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        assert await make().get_credentials(USER) is None
    assert any("no credentials stored" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    "payload", ["not json", "[1, 2]", '{"a": 1}', '{"a": null}', '"text"']
)
async def test_an_unusable_payload_fails_closed(secrets: Any, payload: str) -> None:
    secrets.create_secret(Name=f"mcp/users/{USER}/svc", SecretString=payload)
    with pytest.raises(VaultUnavailableError, match="payload unusable"):
        await make().get_credentials(USER)


async def test_a_bad_endpoint_is_unavailable_not_a_crash() -> None:
    # `AWS_ENDPOINT_URL=host:4566` (no scheme) makes boto3 raise a plain
    # ValueError at client construction; it must land on the same rung.
    client = VaultClient(
        secrets_prefix="mcp", server_key="svc", endpoint_url="host:4566"
    )
    with pytest.raises(VaultUnavailableError):
        await client.get_credentials(USER)


async def test_only_hits_are_cached(secrets: Any) -> None:
    client = make()
    assert await client.get_credentials(USER) is None  # a miss is not cached
    secrets.create_secret(
        Name=f"mcp/users/{USER}/svc", SecretString=json.dumps({"k": "v1"})
    )
    assert await client.get_credentials(USER) == {"k": "v1"}  # found at once
    secrets.put_secret_value(
        SecretId=f"mcp/users/{USER}/svc", SecretString=json.dumps({"k": "v2"})
    )
    assert await client.get_credentials(USER) == {"k": "v1"}  # the cached hit


async def test_an_expired_hit_is_read_again(
    secrets: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(vault_module, "monotonic", lambda: now[0])
    client = make(cache_ttl_seconds=60)
    secrets.create_secret(
        Name=f"mcp/users/{USER}/svc", SecretString=json.dumps({"k": "v1"})
    )
    await client.get_credentials(USER)
    secrets.put_secret_value(
        SecretId=f"mcp/users/{USER}/svc", SecretString=json.dumps({"k": "v2"})
    )
    now[0] += 61
    assert await client.get_credentials(USER) == {"k": "v2"}


async def test_the_cache_is_reaped_on_write(
    secrets: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(vault_module, "monotonic", lambda: now[0])
    client = make(cache_ttl_seconds=60)
    for name in ("a", "b"):
        secrets.create_secret(
            Name=f"mcp/users/{name}/svc", SecretString=json.dumps({"k": name})
        )
    await client.get_credentials("a")
    now[0] += 61
    await client.get_credentials("b")  # reaps the expired "a"
    assert list(client._cache) == ["b"]  # noqa: SLF001


async def test_log_lines_carry_a_fingerprint_never_the_secret(
    secrets: Any, caplog: pytest.LogCaptureFixture
) -> None:
    body = json.dumps({"token": "super-secret-token-value"})
    secrets.create_secret(Name=f"mcp/users/{USER}/svc", SecretString=body)
    with caplog.at_level(logging.INFO):
        await make().get_credentials(USER)
    text = " ".join(
        r.getMessage() + json.dumps(r.__dict__, default=str) for r in caplog.records
    )
    assert "super-secret-token-value" not in text
    assert fingerprint(body) in text


def test_the_failure_budget_is_one_attempt_and_five_seconds() -> None:
    # botocore counts RETRIES in `max_attempts`: 1 would silently double
    # the budget. 0 is the only value that yields a single attempt.
    assert VAULT_MAX_RETRIES == 0
    assert VAULT_BUDGET_SECONDS == 5


def test_fingerprint_is_stable_and_short() -> None:
    assert fingerprint("x") == fingerprint("x") != fingerprint("y")
    assert len(fingerprint("x")) == 16


def test_build_vault_reads_the_settings() -> None:
    v = build_vault(
        Settings(
            mcp_secrets_prefix="p",
            server_key="gw",
            aws_endpoint_url="http://localstack:4566",
            vault_cache_ttl_seconds=7,
        )
    )
    assert (v.secrets_prefix, v.server_key, v.endpoint_url, v.cache_ttl_seconds) == (
        "p",
        "gw",
        "http://localstack:4566",
        7,
    )
    assert v._secret_name("u") == "p/users/u/gw"  # noqa: SLF001


async def test_the_readiness_check_distinguishes_not_found_from_unavailable(
    secrets: Any,
) -> None:
    # not found on the sentinel user: the read path works
    assert await check_vault(make()) == CheckResult("vault", True, "read path ok")
    secrets.create_secret(
        Name=f"mcp/users/{READINESS_SENTINEL_USER}/svc", SecretString="not json"
    )
    assert await check_vault(make()) == CheckResult("vault", False, "unavailable")
