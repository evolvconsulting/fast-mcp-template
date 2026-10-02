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
from typing import Any

import fakeredis
import pytest

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
