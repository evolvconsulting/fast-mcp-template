"""Shared fixtures.

`make_settings` builds Settings from explicit overrides only: every
`MCP_TEMPLATE_*` variable is cleared first, so a developer's shell
cannot leak into a test that asserts a default. `fake_redis` is an
in-memory Redis that also runs Lua (`fakeredis[lua]`; plain fakeredis
answers `unknown command 'evalsha'`).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import fakeredis
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from fast_mcp_template.config import Settings
from fast_mcp_template.infra.redis_client import reset_redis_for_tests


@pytest.fixture(autouse=True)
def _fresh_redis() -> Iterator[None]:
    """No test may leave the process-wide Redis client set."""
    reset_redis_for_tests()
    yield
    reset_redis_for_tests()


@pytest.fixture
def make_settings(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:
    """Build Settings from explicit overrides only."""
    for name in list(os.environ):
        if name.startswith("MCP_TEMPLATE_"):
            monkeypatch.delenv(name, raising=False)

    def _make(**overrides: Any) -> Settings:
        return Settings(**overrides)

    return _make


@pytest.fixture
def fake_redis() -> Iterator[fakeredis.aioredis.FakeRedis]:
    """An in-memory Redis that also runs Lua."""
    yield fakeredis.aioredis.FakeRedis(decode_responses=True)


@dataclass(frozen=True)
class InternalCA:
    """A throwaway self-signed CA, as PEM text (public material only)."""

    ca_pem: str


def _make_ca(common_name: str) -> InternalCA:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .sign(key, hashes.SHA256())
    )
    return InternalCA(cert.public_bytes(serialization.Encoding.PEM).decode())


@pytest.fixture(scope="session")
def internal_ca() -> InternalCA:
    """The good internal CA."""
    return _make_ca("test internal CA")


@pytest.fixture(scope="session")
def other_ca() -> InternalCA:
    """An unrelated CA: trusting it must not validate the good CA's leaves."""
    return _make_ca("some other CA")
