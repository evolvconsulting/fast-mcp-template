"""R5 M1, L1, L3: the limiter caps a credential across IPs, bounds unverified tokens per IP, and
the body deadline never counts a declared length above the body limit."""

import asyncio
from typing import Any

from starlette.types import Message, Receive, Scope, Send

from fast_mcp_template.http import concurrency as entry
from tests.test_concurrency_limit import Stub, settle


def _auth_scope(auth: bytes, ip: str = "10.9.0.1") -> Scope:
    headers = [(b"x-forwarded-for", ip.encode())]
    if auth:
        headers.append((b"authorization", auth))
    return {"type": "http", "path": "/mcp", "method": "POST", "headers": headers}


def _call_auth(app: Any, auth: bytes, ip: str = "10.9.0.1") -> "asyncio.Task[int]":
    status: list[int] = []

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            status.append(message["status"])

    async def noop() -> Message:
        return {"type": "http.request"}

    async def run() -> int:
        await app(_auth_scope(auth, ip), noop, send)
        return status[0]

    return asyncio.create_task(run())


def _cl(value: bytes) -> Scope:
    return {"type": "http", "headers": [(b"content-length", value)]}


class Answer:
    """An app that answers at once with a fixed status."""

    def __init__(self, status: int) -> None:
        self.status = status

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {"type": "http.response.start", "status": self.status, "headers": []}
        )
        await send({"type": "http.response.body", "body": b""})


async def test_one_credential_from_four_ips_cannot_take_every_slot() -> None:
    """M1: 4 IPs x 25 held bodies took all 100 slots and a third party got 503."""
    stub = Stub()
    app = entry.ConcurrencyLimitMiddleware(stub, 100)
    app.mark_verified(b"Bearer attacker")
    holders = [
        _call_auth(app, b"Bearer attacker", ip=f"10.9.0.{ip}")
        for ip in range(1, 5)
        for _ in range(25)
    ]
    await settle()
    assert app.inflight == app.per_credential == 50, (
        "limit // 2 for a credential, any IP"
    )
    app.mark_verified(b"Bearer other")
    third = _call_auth(app, b"Bearer other", ip="10.9.0.5")
    stub.release.set()
    assert await third == 200, "a third party with another key still gets through"
    statuses = [await h for h in holders]
    assert statuses.count(200) == 50 and statuses.count(503) == 50
    assert app._by_credential == {} and app._by_client == {} and app.inflight == 0


async def test_a_credential_cap_is_released_for_the_next_holder() -> None:
    stub = Stub()
    app = entry.ConcurrencyLimitMiddleware(stub, 4)
    app.mark_verified(b"Bearer k")
    first = [_call_auth(app, b"Bearer k", ip=f"10.9.1.{n}") for n in range(2)]
    await settle()
    assert app.inflight == 2 == app.per_credential
    assert await _call_auth(app, b"Bearer k", ip="10.9.1.9") == 503
    first[0].cancel()
    await settle()
    again = _call_auth(app, b"Bearer k", ip="10.9.1.9")
    stub.release.set()
    assert await again == 200


async def test_distinct_unverified_tokens_share_one_small_bucket_per_ip() -> None:
    """L1: 120 CRC-valid junk tokens each got their own bucket and held 99 slots."""
    stub = Stub()
    app = entry.ConcurrencyLimitMiddleware(stub, 100)
    junk = [
        _call_auth(app, f"Bearer evc_junk{n}".encode(), ip="10.9.2.1")
        for n in range(120)
    ]
    await settle()
    assert app.inflight == app.per_unverified == 10, "bounded per IP, not per token"
    other = _call_auth(app, b"Bearer evc_junk-from-elsewhere", ip="10.9.2.2")
    await settle()
    assert app.inflight == 11, "another IP has its own small bucket"
    stub.release.set()
    statuses = [await j for j in junk]
    assert statuses.count(200) == 10 and statuses.count(503) == 110
    assert await other == 200
    assert app._by_client == {} and app.inflight == 0


async def test_two_ips_of_junk_leave_most_slots_free() -> None:
    stub = Stub()
    app = entry.ConcurrencyLimitMiddleware(stub, 100)
    for ip in ("10.9.3.1", "10.9.3.2"):
        for n in range(60):
            _call_auth(app, f"Bearer evc_{ip}-{n}".encode(), ip=ip)
    await settle()
    assert app.inflight == 20
    stub.release.set()
    await settle()


# R6: `test_a_401_never_verifies_and_a_200_does` pinned the status-code rule (a stub that
# answered 200 with no auth verified its caller). Replaced by
# `test_only_an_authenticated_scope_verifies_whatever_the_status` in test_limiter_r6.py.


async def test_a_verified_credential_leaves_the_shared_bucket() -> None:
    """After one accepted request a user is no longer capped with the junk."""
    stub = Stub()
    app = entry.ConcurrencyLimitMiddleware(stub, 100)
    app.mark_verified(b"Bearer user")
    held = [_call_auth(app, b"Bearer user", ip="10.9.4.1") for _ in range(20)]
    await settle()
    assert app.inflight == 20 > app.per_unverified
    stub.release.set()
    assert [await h for h in held] == [200] * 20


async def test_the_verified_set_is_bounded() -> None:
    app = entry.ConcurrencyLimitMiddleware(Answer(200), 100)
    for n in range(entry.MAX_VERIFIED + 5):
        app.mark_verified(f"Bearer t{n}".encode())
    assert len(app._verified) == entry.MAX_VERIFIED
    assert app._digest(b"Bearer t0") not in app._verified, "the oldest went first"
    assert app._digest(f"Bearer t{entry.MAX_VERIFIED + 4}".encode()) in app._verified


async def test_the_new_caps_are_pinned() -> None:
    assert (entry.PER_CREDENTIAL_DIVISOR, entry.UNVERIFIED_DIVISOR) == (2, 10)
    app = entry.ConcurrencyLimitMiddleware(Stub(), 100)
    assert (app.per_client, app.per_credential, app.per_unverified) == (25, 50, 10)


# ------------------------------------------------------ L3: the declared length is clamped


def test_a_declared_length_above_the_body_limit_earns_no_more_time() -> None:
    """L3: a declared 4 MB body held a slot 60 s; clamped it is the 1 MiB allowance, 26 s."""
    guard = entry.RequestBodyGuard(Stub())
    one_mib = guard._deadline_for(_cl(b"1048576"))
    assert one_mib == 10.0 + 16.0 == 26.0
    for declared in (b"1048577", b"4000000", b"10000000", b"9" * 13, b"9" * 5000):
        assert guard._deadline_for(_cl(declared)) == one_mib, declared


def test_the_clamp_follows_the_configured_limit() -> None:
    guard = entry.RequestBodyGuard(Stub(), max_body=65536)
    assert guard._deadline_for(_cl(b"4000000")) == 11.0
    assert guard._deadline_for(_cl(b"1000")) == 10.0 + 1000 / 65536
