"""`RequestBodyGuard`: a response sent with an unread body closes the socket.

uvicorn keeps a connection open after a response while the body is unread
and has no body-read deadline: one byte every few seconds held a socket
for ever. The guard marks such a response `Connection: close` and answers
408 to a body still incomplete at the deadline.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from starlette.types import Message, Receive, Scope, Send

from fast_mcp_template.http import concurrency as c


def scope(*headers: tuple[bytes, bytes]) -> Scope:
    return {"type": "http", "path": "/mcp", "method": "POST", "headers": list(headers)}


async def run(
    app: Any,
    sc: Scope,
    receive: Receive,
) -> tuple[int | None, dict[str, str], bytes]:
    sent: list[Message] = []

    async def send(m: Message) -> None:
        sent.append(m)

    await app(sc, receive, send)
    start = next((m for m in sent if m["type"] == "http.response.start"), None)
    headers = {
        k.decode().lower(): v.decode() for k, v in (start or {"headers": []})["headers"]
    }
    body = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return (start["status"] if start else None), headers, body


async def answer_at_once(sc: Scope, receive: Receive, send: Send) -> None:
    """A 401 that never reads the body."""
    await send({"type": "http.response.start", "status": 401, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def read_all(sc: Scope, receive: Receive, send: Send) -> None:
    while (await receive()).get("more_body"):
        pass
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def never_arrives() -> Message:
    await asyncio.sleep(30)
    return {"type": "http.request", "body": b""}


async def one_chunk() -> Message:
    return {"type": "http.request", "body": b"x", "more_body": False}


async def test_an_early_refusal_with_an_unread_body_carries_connection_close() -> None:
    status, headers, _ = await run(
        c.RequestBodyGuard(answer_at_once),
        scope((b"content-length", b"10")),
        one_chunk,
    )
    assert status == 401
    assert headers["connection"] == "close"


async def test_a_response_with_no_declared_body_keeps_the_connection() -> None:
    _, headers, _ = await run(c.RequestBodyGuard(answer_at_once), scope(), one_chunk)
    assert "connection" not in headers
    _, headers, _ = await run(
        c.RequestBodyGuard(answer_at_once), scope((b"content-length", b"0")), one_chunk
    )
    assert "connection" not in headers


async def test_chunked_counts_as_a_declared_body() -> None:
    _, headers, _ = await run(
        c.RequestBodyGuard(answer_at_once),
        scope((b"transfer-encoding", b"chunked")),
        one_chunk,
    )
    assert headers["connection"] == "close"


async def test_a_body_fully_read_leaves_the_connection_alive() -> None:
    status, headers, body = await run(
        c.RequestBodyGuard(read_all), scope((b"content-length", b"1")), one_chunk
    )
    assert (status, body) == (200, b"ok")
    assert "connection" not in headers


async def test_a_stalled_body_is_answered_408_at_the_deadline() -> None:
    status, headers, body = await run(
        c.RequestBodyGuard(read_all, deadline_s=0.05),
        scope((b"content-length", b"10")),
        never_arrives,
    )
    assert status == 408
    assert headers["connection"] == "close"
    problem = json.loads(body)
    assert problem["type"] == "/problems/request-body-timeout"
    assert problem["status"] == 408


async def test_after_the_408_the_app_sees_a_disconnect_and_its_own_reply_is_dropped() -> (
    None
):
    seen: list[str] = []

    async def app(sc: Scope, receive: Receive, send: Send) -> None:
        seen.append((await receive())["type"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"too late"})

    status, _, body = await run(
        c.RequestBodyGuard(app, deadline_s=0.05),
        scope((b"content-length", b"10")),
        never_arrives,
    )
    assert seen == ["http.disconnect"]
    assert status == 408
    assert b"too late" not in body


async def test_a_guard_adds_no_second_connection_header() -> None:
    async def app(sc: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"connection", b"close")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    _, headers, _ = await run(
        c.RequestBodyGuard(app), scope((b"content-length", b"10")), one_chunk
    )
    assert headers["connection"] == "close"


async def test_a_non_http_scope_passes_through_untouched() -> None:
    seen: list[str] = []

    async def app(sc: Scope, receive: Receive, send: Send) -> None:
        seen.append(sc["type"])

    async def nothing(_m: Message) -> None:
        return None

    await c.RequestBodyGuard(app)({"type": "lifespan"}, one_chunk, nothing)
    assert seen == ["lifespan"]


@pytest.mark.parametrize(
    ("length", "expected"),
    [
        (b"", c.BODY_READ_DEADLINE_S),  # unknown: the base
        (b"abc", c.BODY_READ_DEADLINE_S),  # junk: the base
        (b"0", c.BODY_READ_DEADLINE_S),
        (b"65536", c.BODY_READ_DEADLINE_S + 1.0),  # 64 KiB at 64 KiB/s
        (
            b"99999999999999999999",
            c.BODY_READ_DEADLINE_S + c.MAX_BODY_BYTES / c.BODY_MIN_RATE_BPS,
        ),
    ],
)
def test_the_deadline_is_base_plus_length_over_rate_and_never_counts_over_the_limit(
    length: bytes, expected: float
) -> None:
    sc = scope((b"content-length", length)) if length else scope()
    assert c.RequestBodyGuard(read_all)._deadline_for(sc) == pytest.approx(expected)  # noqa: SLF001


def test_the_scaled_deadline_is_capped() -> None:
    guard = c.RequestBodyGuard(read_all, max_body=10**9)
    sc = scope((b"content-length", str(10**9).encode()))
    assert guard._deadline_for(sc) == c.BODY_DEADLINE_CAP_S  # noqa: SLF001


def test_an_explicit_deadline_is_not_scaled() -> None:
    sc = scope((b"content-length", b"65536"))
    assert c.RequestBodyGuard(read_all, deadline_s=0.5)._deadline_for(sc) == 0.5  # noqa: SLF001


def test_the_body_deadline_constants_are_pinned_to_their_literals() -> None:
    assert c.BODY_READ_DEADLINE_S == 10.0
    assert c.BODY_MIN_RATE_BPS == 64 * 1024
    assert c.BODY_DEADLINE_CAP_S == 60.0
    assert c.LIMIT_CONCURRENCY == 100
