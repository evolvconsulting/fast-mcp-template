"""Client IP and request-id helpers.

Imports starlette and `fastmcp.server.dependencies` only. The
correlation names are the org canon: header `X-Request-ID`,
`request.state.request_id`, log key `request_id`, ContextVar
`request_id_var`.
"""

from __future__ import annotations

import ipaddress
import uuid
from contextvars import ContextVar
from typing import Final

from fastmcp.server.dependencies import get_http_request
from starlette.types import Scope

#: Response header, written as "X-Request-ID".
REQUEST_ID_HEADER: Final = "x-request-id"
#: Key in scope["state"] (= request.state.request_id).
STATE_REQUEST_ID: Final = "request_id"
request_id_var: ContextVar[str | None] = ContextVar("request_id_var", default=None)


def _xff_entries(scope: Scope) -> list[str]:
    """Return every X-Forwarded-For entry (repeated lines join)."""
    lines = [
        bytes(v).decode("latin-1")
        for k, v in scope.get("headers") or []
        if bytes(k).lower() == b"x-forwarded-for"
    ]
    return [h.strip() for ln in lines for h in ln.split(",") if h.strip()]


def _as_ip(value: str) -> str | None:
    """Return the canonical text of `value` if it is an IP, else None.

    IPv6 scope ids (`fe80::1%eth0`) parse but carry caller text, so
    they are refused; IPv4-mapped IPv6 is folded to IPv4 so one client
    holds one bucket.
    """
    if "%" in value:
        return None
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return str(ip)


def client_ip_from_scope(scope: Scope, trusted_hops: int) -> str | None:
    """Return the client IP: Nth X-Forwarded-For entry from the right.

    With no trusted hops, no usable header, or a chosen entry that is
    not an IP address (a port, junk, control characters), the socket
    peer is used. When the header holds fewer entries than the hop
    count, the left-most entry is the best available answer. The result
    is always a canonical address or None.
    """
    xff = _xff_entries(scope)
    if trusted_hops > 0 and xff:
        entry = xff[-trusted_hops] if len(xff) >= trusted_hops else xff[0]
        chosen = _as_ip(entry)
        if chosen is not None:
            return chosen
    client = scope.get("client")
    return _as_ip(client[0]) if client else None


def rate_key_for_ip(ip: str | None) -> str | None:
    """Return the rate-limit KEY for a client IP.

    An IPv6 client owns a whole /64, so keying by the full address
    hands one attacker 2^64 buckets. IPv6 is folded to its /64 network
    text; IPv4 (and None) pass through.
    """
    if ip is None:
        return None
    canonical = _as_ip(ip)
    if canonical is None:
        raise ValueError("rate_key_for_ip: not a plain IP address")
    addr = ipaddress.ip_address(canonical)
    if isinstance(addr, ipaddress.IPv6Address):
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return canonical


def current_client_ip(trusted_hops: int) -> str | None:
    """Return the client IP of the current request, else None."""
    try:
        request = get_http_request()
    except RuntimeError:
        return None
    return client_ip_from_scope(request.scope, trusted_hops)


def new_request_id() -> str:
    """Return a fresh UUID v4 request id."""
    return str(uuid.uuid4())


def valid_request_id(value: str | None) -> bool:
    """Return True only for a UUID v4 in canonical lowercase text."""
    if not value:
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value


def current_request_id() -> str | None:
    """Return the request id (ContextVar, else request state)."""
    value = request_id_var.get()
    if value is not None:
        return value
    try:
        request = get_http_request()
    except RuntimeError:
        return None
    state = request.scope.get("state") or {}
    value = state.get(STATE_REQUEST_ID)
    return value if isinstance(value, str) else None
