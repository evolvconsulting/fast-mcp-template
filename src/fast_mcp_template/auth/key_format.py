"""Pure key-format module - plan §13.2 / §5.5. COPY 2 OF 3.

Identical bytes in all three copies (evolv-coder-be `app/domain/users/key_format.py`,
fast-mcp-ado `src/fast_mcp_ado/key_format.py`, harness `harness/key_format.py`).
Zero imports beyond stdlib; drift is caught by the shared vectors in
`harness/vectors/key_format_vectors.json`.

    evc_live_<body: 43 base62 chars = 256 bits>_<crc: 6 base62 chars>
    crc = CRC32(IEEE) of the ASCII bytes of "evc_live_" + body, base62, zero-padded
"""

import hashlib
import secrets
import zlib

KEY_ENV_PREFIX = "evc_live_"  # issuer+environment prefix, constant this slice
BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BODY_LEN = 43  # base62 chars, zero-padded ('0' = alphabet[0])
CRC_LEN = 6  # base62 chars, zero-padded
KEY_PREFIX_LEN = 12  # chars of body stored/displayed as key_prefix


def b62encode(data: bytes, min_len: int) -> str:
    """Big-endian int -> base62, left-padded with '0' to min_len."""
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, rem = divmod(n, 62)
        out = BASE62_ALPHABET[rem] + out
    return out.rjust(min_len, BASE62_ALPHABET[0])


def _crc_for(body: str) -> str:
    checksum = zlib.crc32(f"{KEY_ENV_PREFIX}{body}".encode())
    return b62encode(checksum.to_bytes(4, "big"), CRC_LEN)


def mint_key() -> str:
    """Return a fresh `evc_live_<body>_<crc>` key."""
    body = b62encode(secrets.token_bytes(32), BODY_LEN)
    return f"{KEY_ENV_PREFIX}{body}_{_crc_for(body)}"


def split_key(key: str) -> tuple[str, str] | None:
    """Return (body, crc), or None if the key's shape is malformed."""
    if not isinstance(key, str) or not key.startswith(KEY_ENV_PREFIX):
        return None
    rest = key[len(KEY_ENV_PREFIX) :]
    body, sep, crc = rest.partition("_")
    if not sep or len(body) != BODY_LEN or len(crc) != CRC_LEN:
        return None
    if any(c not in BASE62_ALPHABET for c in body + crc):
        return None
    return body, crc


def crc32_ok(key: str) -> bool:
    """Shape check + CRC re-computation. NEVER raises."""
    parts = split_key(key)
    if parts is None:
        return False
    body, crc = parts
    return _crc_for(body) == crc


def key_hash(key: str) -> str:
    """Hex SHA-256 of the FULL key string (prefix and CRC included)."""
    return hashlib.sha256(key.encode()).hexdigest()


def key_prefix(key: str) -> str:
    """First KEY_PREFIX_LEN chars of the body. Assumes crc32_ok(key)."""
    parts = split_key(key)
    return "" if parts is None else parts[0][:KEY_PREFIX_LEN]
