"""`build_app` builds authentication, and refuses to serve without it.

The dispatch, boot and verifier matrices live in their own files; this
one proves the WIRING: that the verifier reaches fastmcp's auth layer,
that a request without credentials is a 401 carrying a request id, and
that the audit layer writes one line for it.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from starlette.testclient import TestClient

from fast_mcp_template import server
from fast_mcp_template.__main__ import build_app
from fast_mcp_template.auth.types import AuthConfigError
from fast_mcp_template.config import Settings

KEY = "kQ7vN2xZp9Lm4Rt8Wd3Hs6Jf1Yc5Ba0Gu"  # noqa: S105 - a fake shared key
REDIS = "redis://localhost:1/0"
INIT: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "1"},
    },
}
HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture(autouse=True)
def _restore_server_auth() -> Any:
    before = server.mcp.auth
    yield
    server.mcp.auth = before


def test_serving_without_any_credential_refuses_to_boot() -> None:
    with pytest.raises(AuthConfigError, match="MCP_TEMPLATE_API_KEY"):
        build_app(Settings(redis_url=REDIS))


def test_serving_without_redis_refuses_to_boot() -> None:
    with pytest.raises(AuthConfigError, match="MCP_TEMPLATE_REDIS_URL"):
        build_app(Settings(api_key=KEY))  # type: ignore[arg-type]


def test_a_missing_bearer_is_a_401_with_a_request_id_and_one_audit_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(build_app(Settings(api_key=KEY, redis_url=REDIS)))  # type: ignore[arg-type]
    with caplog.at_level(logging.INFO):
        resp = client.post("/mcp", json=INIT, headers=HEADERS)
    assert resp.status_code == 401
    assert resp.headers["x-request-id"]
    lines = [r for r in caplog.records if getattr(r, "event", "") == "mcp_auth"]
    assert len(lines) == 1
    assert lines[0].__dict__["status"] == 401
    assert lines[0].__dict__["auth_path"] == "none"


def test_a_wrong_bearer_is_a_401() -> None:
    client = TestClient(build_app(Settings(api_key=KEY, redis_url=REDIS)))  # type: ignore[arg-type]
    resp = client.post(
        "/mcp", json=INIT, headers={**HEADERS, "Authorization": "Bearer nope"}
    )
    assert resp.status_code == 401


def test_the_right_bearer_gets_through_to_the_mcp_endpoint() -> None:
    # Redis is unreachable here, so the limiter falls back to its local
    # bucket (fail-open to LOCAL, never to unlimited) and the request passes.
    with TestClient(build_app(Settings(api_key=KEY, redis_url=REDIS))) as client:  # type: ignore[arg-type]
        resp = client.post(
            "/mcp", json=INIT, headers={**HEADERS, "Authorization": f"Bearer {KEY}"}
        )
    assert resp.status_code == 200
    assert resp.headers["ratelimit-limit"]
    assert resp.headers["x-request-id"]


def test_health_needs_no_credential() -> None:
    client = TestClient(build_app(Settings(api_key=KEY, redis_url=REDIS)))  # type: ignore[arg-type]
    assert client.get("/health").status_code == 200


def test_the_escape_hatch_serves_unauthenticated_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.CRITICAL):
        build_app(Settings(dangerously_disable_auth=True, redis_url=REDIS))
    assert server.mcp.auth is None
    assert any("UNAUTHENTICATED" in r.getMessage() for r in caplog.records)


def test_the_escape_hatch_is_refused_in_production() -> None:
    with pytest.raises(AuthConfigError, match="DANGEROUSLY_DISABLE_AUTH"):
        build_app(
            Settings(
                dangerously_disable_auth=True,
                redis_url="rediss://cache.internal:6380/0",
                environment="production",
            )
        )
