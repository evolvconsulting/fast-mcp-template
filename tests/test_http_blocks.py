"""Tests for the HTTP blocks: net, request id, errors, body limit."""

from __future__ import annotations

import asyncio
import ssl
import uuid
from typing import Any

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette.types import Scope

from fast_mcp_template.__main__ import build_app
from fast_mcp_template.config import Settings, internal_verify, url_scheme
from fast_mcp_template.http import build_http_middleware, wrap_http_app
from fast_mcp_template.http.body_limit import BodySizeLimitMiddleware
from fast_mcp_template.http.errors import register_error_handlers
from fast_mcp_template.http.net import (
    client_ip_from_scope,
    current_request_id,
    rate_key_for_ip,
    valid_request_id,
)
from fast_mcp_template.http.request_id import RequestIdMiddleware
from fast_mcp_template.infra import redis_client


def _scope(xff: list[str], peer: str | None = "10.0.0.9") -> Scope:
    headers = [(b"x-forwarded-for", v.encode()) for v in xff]
    return {"headers": headers, "client": (peer, 1) if peer else None}


# --- net -------------------------------------------------------------


@pytest.mark.parametrize(
    ("xff", "hops", "want"),
    [
        (["1.1.1.1, 2.2.2.2"], 1, "2.2.2.2"),  # Nth from the RIGHT
        (["9.9.9.9, 1.1.1.1, 2.2.2.2"], 2, "1.1.1.1"),
        (["1.1.1.1", "2.2.2.2"], 1, "2.2.2.2"),  # repeated lines join
        (["1.1.1.1"], 3, "1.1.1.1"),  # short list: left-most
        (["1.1.1.1"], 0, "10.0.0.9"),  # no trusted hop: the peer
        (["junk"], 1, "10.0.0.9"),  # not an IP: the peer
        (["fe80::1%eth0"], 1, "10.0.0.9"),  # scope id refused
        (["::ffff:1.2.3.4"], 1, "1.2.3.4"),  # mapped folds to v4
    ],
)
def test_client_ip(xff: list[str], hops: int, want: str) -> None:
    assert client_ip_from_scope(_scope(xff), hops) == want


def test_client_ip_none_without_peer() -> None:
    assert client_ip_from_scope(_scope([], peer=None), 1) is None


def test_rate_key_folds_ipv6_to_its_64() -> None:
    a = rate_key_for_ip("2001:db8::1")
    b = rate_key_for_ip("2001:db8::ffff")
    assert a == b == "2001:db8::/64"
    assert rate_key_for_ip("1.2.3.4") == "1.2.3.4"
    assert rate_key_for_ip(None) is None
    with pytest.raises(ValueError):
        rate_key_for_ip("not-an-ip")


def test_valid_request_id_is_strict() -> None:
    good = str(uuid.uuid4())
    assert valid_request_id(good)
    assert not valid_request_id(good.upper())
    assert not valid_request_id(str(uuid.uuid1()))
    assert not valid_request_id("")
    assert not valid_request_id(None)


# --- request id ------------------------------------------------------


def _echo_app() -> Starlette:
    async def echo(request: Request) -> Response:
        return JSONResponse(
            {
                "state": request.state.request_id,
                "var": current_request_id(),
            }
        )

    async def boom(request: Request) -> Response:
        raise RuntimeError("secret-detail")

    app = Starlette(routes=[Route("/", echo), Route("/boom", boom)])
    register_error_handlers(app)
    return app


def test_request_id_minted_and_visible_inside_the_app() -> None:
    client = TestClient(RequestIdMiddleware(_echo_app()))
    resp = client.get("/")
    rid = resp.headers["x-request-id"]
    assert valid_request_id(rid)
    assert resp.json() == {"state": rid, "var": rid}


def test_request_id_reuses_valid_and_replaces_invalid() -> None:
    client = TestClient(RequestIdMiddleware(_echo_app()))
    good = str(uuid.uuid4())
    assert (
        client.get("/", headers={"X-Request-ID": good}).headers["x-request-id"] == good
    )
    bad = client.get("/", headers={"X-Request-ID": "x" * 40})
    assert bad.headers["x-request-id"] != "x" * 40
    assert valid_request_id(bad.headers["x-request-id"])


def test_contextvar_is_reset_after_the_request() -> None:
    client = TestClient(RequestIdMiddleware(_echo_app()))
    client.get("/")
    assert current_request_id() is None


# --- errors ----------------------------------------------------------


def test_404_and_500_are_problem_json_with_matching_ids() -> None:
    client = TestClient(RequestIdMiddleware(_echo_app()), raise_server_exceptions=False)
    nf = client.get("/nope")
    assert nf.status_code == 404
    assert nf.headers["content-type"].startswith("application/problem+json")
    body = nf.json()
    assert set(body) == {
        "type",
        "title",
        "status",
        "detail",
        "instance",
        "request_id",
        "timestamp",
    }
    assert body["request_id"] == nf.headers["x-request-id"]
    ise = client.get("/boom")
    assert ise.status_code == 500
    assert "secret-detail" not in ise.text  # no detail leak on a 500


def test_405_keeps_the_allow_header() -> None:
    client = TestClient(RequestIdMiddleware(_echo_app()))
    resp = client.post("/")
    assert resp.status_code == 405
    assert "GET" in resp.headers["allow"]


# --- body limit ------------------------------------------------------


def _limited(limit: int) -> TestClient:
    async def read(request: Request) -> Response:
        return JSONResponse({"n": len(await request.body())})

    settings = Settings(max_request_body_bytes=limit)
    app = Starlette(
        routes=[Route("/", read, methods=["POST"])],
        middleware=[Middleware(BodySizeLimitMiddleware, settings=settings)],
    )
    return TestClient(RequestIdMiddleware(app))


def test_body_under_the_limit_passes() -> None:
    assert _limited(1024).post("/", content=b"x" * 1024).json() == {"n": 1024}


def test_declared_length_over_the_limit_is_413() -> None:
    resp = _limited(1024).post("/", content=b"x" * 1025)
    assert resp.status_code == 413
    assert resp.json()["type"] == "/problems/payload-too-large"
    assert valid_request_id(resp.headers["x-request-id"])


def test_streamed_body_over_the_limit_is_413() -> None:
    def chunks() -> Any:
        yield b"x" * 600
        yield b"x" * 600

    resp = _limited(1024).post("/", content=chunks())  # no Content-Length
    assert resp.status_code == 413


def test_body_limit_floor_is_enforced_by_settings() -> None:
    with pytest.raises(ValueError):
        Settings(max_request_body_bytes=10)


# --- whole app -------------------------------------------------------


def test_build_app_wires_request_id_body_limit_and_problem_errors() -> None:
    settings = Settings(max_request_body_bytes=1024)
    client = TestClient(build_app(settings), raise_server_exceptions=False)
    nf = client.get("/nope")
    assert nf.status_code == 404
    assert nf.json()["request_id"] == nf.headers["x-request-id"]
    big = client.post(settings.mcp_path, content=b"x" * 2048)
    assert big.status_code == 413  # the body limit runs before the app


def test_middleware_list_holds_the_body_limit_only() -> None:
    mw = build_http_middleware(Settings())
    assert [m.cls for m in mw] == [BodySizeLimitMiddleware]  # type: ignore[comparison-overlap]


def test_wrap_warns_when_trusted_hops_is_above_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    wrap_http_app(_echo_app(), Settings(trusted_proxy_hops=2))
    assert any(
        r.__dict__.get("event") == "trusted_proxy_hops_high" for r in caplog.records
    )
    caplog.clear()
    wrap_http_app(_echo_app(), Settings(trusted_proxy_hops=1))
    assert not caplog.records


# --- redis client ----------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_redis() -> Any:
    redis_client.reset_redis_for_tests()
    yield
    redis_client.reset_redis_for_tests()


def test_blank_redis_url_gives_no_client() -> None:
    assert redis_client.get_redis(Settings()) is None
    assert redis_client.get_redis(Settings(redis_url="  ")) is None


def test_redis_client_has_timeouts_and_is_shared() -> None:
    s = Settings(redis_url="redis://localhost:6379/0")
    a = redis_client.get_redis(s)
    assert a is not None
    kw = a.connection_pool.connection_kwargs
    assert kw["socket_connect_timeout"] == redis_client.REDIS_CONNECT_TIMEOUT_S
    assert kw["socket_timeout"] == redis_client.REDIS_SOCKET_TIMEOUT_S
    assert redis_client.get_redis(s) is a


def test_rediss_without_an_internal_ca_refuses_never_system_trust() -> None:
    s = Settings(redis_url="rediss://redis.internal:6380/0")
    with pytest.raises(RuntimeError, match="internal_ca_cert"):
        redis_client.get_redis(s)


def test_url_scheme_and_internal_verify() -> None:
    assert url_scheme("REDISS://h:1") == "rediss"
    assert url_scheme(None) == ""
    assert internal_verify(Settings()) is True
    with pytest.raises(ssl.SSLError):
        internal_verify(Settings(internal_ca_cert="not a pem"))


# --- coverage of the remaining branches ------------------------------


def _ca_pem() -> str:
    from datetime import UTC, datetime, timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
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
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_rediss_with_an_internal_ca_uses_only_that_context() -> None:
    s = Settings(redis_url="rediss://redis.internal:6380/0", internal_ca_cert=_ca_pem())
    client = redis_client.get_redis(s)
    assert client is not None
    pool = client.connection_pool
    conn = pool.connection_class(**pool.connection_kwargs)
    ctx = conn._connection_arguments()["ssl"]  # type: ignore[attr-defined]  # noqa: SLF001
    assert isinstance(ctx, ssl.SSLContext)
    # exactly the one internal CA, no system store
    assert len(ctx.get_ca_certs()) == 1


def test_main_runs_stdio_by_default_and_uvicorn_for_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fast_mcp_template.__main__ as entry

    calls: list[Any] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    monkeypatch.setattr(
        entry,
        "build_server",
        lambda: type("S", (), {"run": lambda self: calls.append("stdio")})(),
    )
    entry.main([])
    assert calls == ["stdio"]
    calls.clear()
    monkeypatch.setattr(entry, "build_app", lambda s: object())
    entry.main(["http"])
    assert calls == [{"host": "127.0.0.1", "port": 8000, "proxy_headers": False}]


async def _noop_receive() -> dict[str, Any]:
    return {"type": "lifespan.startup"}


def test_non_http_scopes_pass_through_both_middlewares() -> None:
    seen: list[str] = []

    async def app(scope: Scope, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    async def send(message: Any) -> None:
        return None

    for mw in (
        RequestIdMiddleware(app),
        BodySizeLimitMiddleware(app, settings=Settings()),
    ):
        asyncio.run(mw({"type": "lifespan"}, _noop_receive, send))
    assert seen == ["lifespan", "lifespan"]


def test_current_ids_outside_a_request_are_none() -> None:
    from fast_mcp_template.http.net import current_client_ip

    assert current_client_ip(1) is None
    assert current_request_id() is None


def test_current_ids_fall_back_to_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from fast_mcp_template.http import net

    scope = _scope(["1.1.1.1, 2.2.2.2"])
    scope["type"] = "http"
    scope["state"] = {"request_id": "rid-from-state"}
    req = Request(scope)
    monkeypatch.setattr(net, "get_http_request", lambda: req)
    assert net.current_client_ip(1) == "2.2.2.2"
    assert net.current_request_id() == "rid-from-state"


def test_app_that_overflows_after_responding_keeps_its_response() -> None:
    # The app starts its response, THEN reads past the limit: our 413
    # must not be appended to a response already on the wire.
    async def app(scope: Scope, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()
        await send({"type": "http.response.body", "body": b"ok"})

    c = TestClient(
        BodySizeLimitMiddleware(app, settings=Settings(max_request_body_bytes=1024))
    )
    # no Content-Length: a generator body
    resp = c.post("/", content=(b"x" * 2048 for _ in range(1)))
    assert resp.status_code == 200
