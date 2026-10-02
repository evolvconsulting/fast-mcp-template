"""`ConcurrencyLimitMiddleware` semantics on a stub app (S35, R2 M3, L1).

The counter, the exemption set and the shed response are pinned directly, not through a real
server: each of these lines is load-bearing for availability and was once unpinned.
"""

import asyncio
import itertools
import logging
import time
from typing import Any

import pytest
from starlette.types import Message, Receive, Scope, Send

from fast_mcp_template.http import concurrency as entry
from fast_mcp_template.http.net import request_id_var


class Stub:
    """An ASGI app that holds every request until released, or raises when told to."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.raise_on: set[str] = set()
        self.started = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.started += 1
        if scope["path"] in self.raise_on:
            raise RuntimeError("boom")
        await self.release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


async def _noop_receive() -> Message:
    return {"type": "http.request"}


_callers = itertools.count(1)


def call(
    app: Any, path: str = "/mcp", method: str = "POST", ip: str | None = None
) -> "asyncio.Task[int]":
    """Run one request through `app`; the task's result is the response status.

    Each call is a different client (its own IP) unless `ip` is given, so the per-client cap
    does not colour the tests of the global limit.
    """
    n = next(_callers)
    ip = ip or f"10.0.{n // 250}.{n % 250 + 1}"
    status: list[int] = []

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            status.append(message["status"])

    async def run() -> int:
        scope = {
            "type": "http",
            "path": path,
            "method": method,
            "headers": [(b"x-forwarded-for", ip.encode())],
        }
        await app(scope, _noop_receive, send)
        return status[0]

    return asyncio.create_task(run())


async def settle() -> None:
    await asyncio.sleep(0.02)


async def test_the_count_returns_to_zero_after_completion() -> None:
    """Mutation: never decrementing answers 503 to every /mcp request after `limit` requests."""
    stub = Stub()
    stub.release.set()
    app = entry.ConcurrencyLimitMiddleware(stub, 3)
    for _ in range(10):  # more than the limit, sequentially
        assert await call(app) == 200
    assert app.inflight == 0


async def test_the_request_after_the_limit_is_shed_not_admitted() -> None:
    """R9 mutant `inflight >`: at exactly `limit` in flight the next is 503, and fails fast."""
    stub = Stub()
    app = entry.ConcurrencyLimitMiddleware(stub, 2, auth_enabled=False)
    held = [call(app) for _ in range(2)]
    await settle()
    assert app.inflight == 2
    assert (
        await asyncio.wait_for(call(app), 1) == 503
    )  # admitted, it would block, not answer
    assert stub.started == 2
    stub.release.set()
    assert [await h for h in held] == [200, 200]


async def test_cancelled_and_raising_requests_release_their_slot() -> None:
    stub = Stub()
    # auth off: the class caps (R6 L1) are not what this test pins, only slot release
    app = entry.ConcurrencyLimitMiddleware(stub, 3, auth_enabled=False)
    held = [call(app) for _ in range(3)]
    await settle()
    assert app.inflight == 3
    held[0].cancel()
    held[1].cancel()
    await settle()
    assert app.inflight == 1, "a cancelled request frees its slot"
    stub.raise_on.add("/boom")
    for _ in range(5):
        with pytest.raises(RuntimeError, match="boom"):
            await call(app, "/boom")
    assert app.inflight == 1, "an exception reaches the caller and frees the slot"
    stub.release.set()
    assert await held[2] == 200
    assert app.inflight == 0


@pytest.mark.parametrize("method", ["POST", "GET"])
async def test_a_request_over_the_limit_is_shed_whatever_the_method(
    method: str,
) -> None:
    """Mutation: exempting every POST would switch the limit off for the whole MCP surface."""
    stub = Stub()
    app = entry.ConcurrencyLimitMiddleware(stub, 1)
    held = call(app)
    await settle()
    assert await call(app, "/mcp", method) == 503
    assert app.shed == 1 and stub.started == 1, "the shed request never reached the app"
    stub.release.set()
    assert await held == 200


@pytest.mark.parametrize("path", ["/health", "/health/live", "/health/ready"])
async def test_health_paths_are_never_counted_or_shed(path: str) -> None:
    stub = Stub()
    app = entry.ConcurrencyLimitMiddleware(stub, 1)
    held = call(app)
    await settle()
    probe = call(app, path, "GET")
    await settle()
    assert stub.started == 2, "the health request reached the app at saturation"
    assert app.inflight == 1, "and was not counted"
    stub.release.set()
    assert await probe == 200 and await held == 200


@pytest.mark.parametrize(
    "path",
    [
        "/healthz",
        "/health-anything",
        "/healthy",
        "/health/../mcp",
        "/health/zzz",
        "/health/",
        "/",
    ],
)
async def test_the_health_exemption_is_an_exact_set_not_a_prefix(path: str) -> None:
    """Mutation: `startswith("/health")` would exempt `/healthz` and `/health/../mcp`."""
    stub = Stub()
    app = entry.ConcurrencyLimitMiddleware(stub, 1)
    held = call(app)
    await settle()
    assert await call(app, path, "GET") == 503, path
    stub.release.set()
    await held


async def test_non_http_scopes_pass_through_uncounted() -> None:
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    app = entry.ConcurrencyLimitMiddleware(
        inner, 0
    )  # limit 0: any counted request is shed
    await app({"type": "lifespan"}, _noop_receive, None)  # type: ignore[arg-type]
    assert seen == ["lifespan"] and app.inflight == 0


async def test_the_shed_response_is_problem_json_with_the_request_id_and_retry_after() -> (
    None
):
    stub = Stub()
    app = entry.ConcurrencyLimitMiddleware(stub, 0)
    bodies: list[Message] = []
    started: list[Message] = []

    async def send(message: Message) -> None:
        (started if message["type"] == "http.response.start" else bodies).append(
            message
        )

    token = request_id_var.set("0b9c1d2e-3f40-4a5b-8c6d-7e8f90a1b2c3")
    try:
        await app({"type": "http", "path": "/mcp", "method": "POST", "headers": []},
                  _noop_receive, send)  # fmt: skip
    finally:
        request_id_var.reset(token)
    headers = {k.decode(): v.decode() for k, v in started[0]["headers"]}
    assert started[0]["status"] == 503
    assert headers["content-type"].startswith("application/problem+json")
    assert 1 <= int(headers["retry-after"]) <= 3
    assert b"0b9c1d2e-3f40-4a5b-8c6d-7e8f90a1b2c3" in bodies[0]["body"], (
        "the body id is the request's"
    )


async def test_shedding_is_logged_with_a_running_counter_once_per_interval(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L1: saturation must be visible to an operator, without a line per shed request."""
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    app = entry.ConcurrencyLimitMiddleware(Stub(), 0)
    caplog.set_level(logging.WARNING, logger="fast_mcp_template.http.concurrency")
    for _ in range(3):
        await call(app)
    clock[0] += 1.5
    await call(app)
    lines = [r for r in caplog.records if getattr(r, "event", "") == "overloaded"]
    assert [r.__dict__["shed_total"] for r in lines] == [1, 4]
    assert lines[0].__dict__["limit"] == 0 and lines[0].levelno == logging.WARNING
