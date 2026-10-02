"""The requests-per-tool-call multiplier, measured rather than assumed.

`default_rate_limit_per_user` counts authenticated HTTP REQUESTS (`verify_token` runs
once per request), but people reason in TOOL CALLS, and one tool call costs several
requests. Wave 4 shipped a limit derived from the wrong unit, 6x too small, because
nothing measured the conversion. This does, on fastmcp 4.0.3 / mcp 2.1.1, in BOTH eras:

- (a) stateless: `http_app(stateless_http=True)` (what production runs) with the default
  client, which speaks the sessionless 2026-07-28 protocol;
- (b) session: `http_app(stateless_http=False)` with a handshake-era client
  (`Client(mode="legacy")`: initialize, notifications/initialized, the SSE GET,
  tools/call, teardown).

`REQUESTS_PER_TOOL_CALL` is the MAXIMUM of the two, so the budget can only be
over-provisioned. Everything runs in-process through `httpx2.ASGITransport`: no socket,
no uvicorn, so the count cannot be disturbed by a port race.
"""

import asyncio
from typing import Any

import httpx2
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth import AccessToken, TokenVerifier

from fast_mcp_template.config import (
    DEFAULT_TOOL_CALLS_PER_MINUTE,
    REQUESTS_PER_TOOL_CALL,
    Settings,
)


class CountingVerifier(TokenVerifier):
    """Accepts everything and counts: one count per authenticated HTTP request."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def verify_token(self, token: str) -> AccessToken | None:
        self.calls += 1
        return AccessToken(
            token=token,
            client_id="platform:measure",
            scopes=[],
            expires_at=None,
            claims={"user_id": "measure", "scopes": None, "rate_limit": None},
        )


async def _count(
    *, stateless: bool, mode: str, n_calls: int, path: str = "/mcp"
) -> int:
    """Authenticated requests for a COMPLETE client session doing `n_calls` tool calls."""
    verifier = CountingVerifier()
    mcp = FastMCP("multiplier", auth=verifier)

    @mcp.tool
    def ping() -> str:
        """Cheapest possible tool: the transport, not the tool, is under measurement."""
        return "pong"

    app = mcp.http_app(path="/mcp", stateless_http=stateless)

    def factory(**kwargs: Any) -> httpx2.AsyncClient:
        kwargs.setdefault("follow_redirects", True)
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://test", **kwargs
        )

    async with app.router.lifespan_context(app):
        transport = StreamableHttpTransport(
            f"http://test{path}",
            auth="measure-token",
            httpx_client_factory=factory,  # type: ignore[arg-type]
        )
        async with Client(transport, mode=mode) as client:
            for _ in range(n_calls):
                await client.call_tool("ping")
        await asyncio.sleep(
            0.1
        )  # let teardown requests land before reading the counter
    return verifier.calls


@pytest.fixture(scope="module")
async def measured() -> dict[str, int]:
    return {
        "stateless_one": await _count(stateless=True, mode="auto", n_calls=1),
        "stateless_two": await _count(stateless=True, mode="auto", n_calls=2),
        "session_one": await _count(stateless=False, mode="legacy", n_calls=1),
        "session_two": await _count(stateless=False, mode="legacy", n_calls=2),
        "legacy_client_on_stateless_one": await _count(
            stateless=True, mode="legacy", n_calls=1
        ),
        "stateless_one_via_redirect": await _count(
            stateless=True, mode="auto", n_calls=1, path="/mcp/"
        ),
    }


async def test_one_tool_call_costs_the_pinned_number_of_requests(
    measured: dict[str, int],
) -> None:
    """THE pin: the constant equals the measured maximum over both eras."""
    assert measured["stateless_one"] > 0, "nothing was counted: the measurement is dead"
    worst = max(
        measured["stateless_one"],
        measured["session_one"],
        measured["legacy_client_on_stateless_one"],
    )
    assert worst == REQUESTS_PER_TOOL_CALL, (
        f"measured {measured}; the worst 1-tool-call session cost {worst} authenticated "
        f"requests, not {REQUESTS_PER_TOOL_CALL}. Re-derive default_rate_limit_per_user "
        f"(config.py) from the new figure, in tool calls."
    )


async def test_each_era_costs_what_was_measured(measured: dict[str, int]) -> None:
    """The per-era figures recorded in the worklog (fastmcp 4.0.3, mcp 2.1.1)."""
    assert measured["stateless_one"] == 3
    assert measured["session_one"] == 6
    assert measured["legacy_client_on_stateless_one"] == 4


def test_the_default_limit_is_derived_from_the_measured_multiplier() -> None:
    """The arithmetic itself, so a hand-edited default cannot drift from its rationale."""
    settings = Settings()
    assert settings.default_rate_limit_per_user == (
        DEFAULT_TOOL_CALLS_PER_MINUTE * REQUESTS_PER_TOOL_CALL
    )
    assert settings.rate_limit_window_s == 60


async def test_an_extra_call_in_a_live_session_is_cheaper_than_a_fresh_one(
    measured: dict[str, int],
) -> None:
    """Setup is amortised, so the pinned figure is the conservative per-call cost."""
    for era in ("stateless", "session"):
        marginal = measured[f"{era}_two"] - measured[f"{era}_one"]
        assert 0 < marginal < measured[f"{era}_one"] <= REQUESTS_PER_TOOL_CALL


async def test_a_trailing_slash_redirect_doubles_the_cost(
    measured: dict[str, int],
) -> None:
    """A client that hits `{mcp_path}/` is redirected (307) and verified twice per
    request: auth runs in ASGI middleware before routing, so the 307 is itself
    authenticated and charged, and the followed request is charged again."""
    assert measured["stateless_one_via_redirect"] == 2 * measured["stateless_one"]
