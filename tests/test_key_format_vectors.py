"""Copy 2 of `key_format.py` reproduces the shared vectors byte-identically (§13.2).

The vectors are VENDORED (EC-568): `tests/fixtures/key_format_vectors.json` is a copy of
`evolv/harness/vectors/key_format_vectors.json` at evolv commit 3610faa, sha256
0e764bfceabd69d14112cb71d7cc299a89b060208557acdf0f68d204b4ad300d. Before EC-571 these tests
read that file from OUTSIDE the repository, so they passed only on a machine with the evolv
checkout beside it and failed on a CI runner.

Two tripwires keep the vendored copies honest without reaching outside the repo:
- `test_vectors_match_canonical_sha256`: the vendored vectors' sha256 equals the constant;
- `test_copy_is_byte_identical_to_the_canonical_copy`: this module's body (every line after
  the copy-number line) hashes to the canonical copy 3's body hash, recorded below.
Re-vendor both from evolv/harness and update both constants in the same commit.

No `pytest.skip` anywhere: a missing vectors file is a HARD failure (Wave-1 review
H1 - a skip turns the drift detector off while the suite still reads green).
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from fast_mcp_template.auth import key_format

VECTORS_PATH = Path(__file__).resolve().parent / "fixtures" / "key_format_vectors.json"
VECTORS_SHA256 = "0e764bfceabd69d14112cb71d7cc299a89b060208557acdf0f68d204b4ad300d"
# sha256 of "\n".join(lines[1:]) of evolv/harness/key_format.py (COPY 3 OF 3) at 3610faa.
CANONICAL_BODY_SHA256 = (
    "a09ae7bc4319d77819f2e26bc44d8948dd6c2d1acaa438d9377578bb06f8aa9a"
)


def test_vectors_match_canonical_sha256() -> None:
    """EC-568: the vendored vectors are byte-identical to the canonical harness copy."""
    assert VECTORS_PATH.is_file(), f"vendored vectors file is missing: {VECTORS_PATH}"
    digest = hashlib.sha256(VECTORS_PATH.read_bytes()).hexdigest()
    assert digest == VECTORS_SHA256, (
        f"vendored vectors drifted: sha256 {digest}, expected {VECTORS_SHA256}. "
        "Re-vendor from evolv/harness/vectors and update VECTORS_SHA256 together."
    )


def load_vectors() -> list[dict[str, Any]]:
    assert VECTORS_PATH.is_file(), f"shared vectors file is missing: {VECTORS_PATH}"
    vectors: list[dict[str, Any]] = json.loads(VECTORS_PATH.read_text())
    assert len(vectors) >= 6, f"expected >= 6 shared vectors, got {len(vectors)}"
    return vectors


def test_vectors_reproduce_byte_identically() -> None:
    for v in load_vectors():
        key = v["key"]
        assert key_format.crc32_ok(key) is v["valid"], key
        if v["valid"]:
            assert key_format.key_hash(key) == v["key_hash"], key
            assert key_format.split_key(key) == (v["body"], v["crc"]), key
            assert key_format.key_prefix(key) == v["key_prefix"], key
        else:
            # invalid vectors carry null derived fields by convention
            assert v["key_hash"] is None and v["body"] is None, key


def test_vectors_cover_the_required_cases() -> None:
    """§13.2 mandates the shape coverage; asserted by property, not position."""
    vectors = load_vectors()
    keys = [v["key"] for v in vectors]
    assert any(v["valid"] and v["body"].startswith("0") for v in vectors), (
        "no leading-zero body"
    )
    assert any(
        v["valid"] is False and key_format.split_key(k) is not None
        for v, k in zip(vectors, keys, strict=True)
    ), "no bad-CRC case (well-shaped but wrong checksum)"
    assert any(
        k.startswith(key_format.KEY_ENV_PREFIX)
        and key_format.split_key(k) is None
        and k != ""
        for k in keys
    ), "no wrong-length case"
    assert any(k and not k.startswith(key_format.KEY_ENV_PREFIX) for k in keys), (
        "no wrong-prefix"
    )
    assert any(k == "" for k in keys), "no empty-string case"


def test_copy_is_byte_identical_to_the_canonical_copy() -> None:
    """All three copies differ only in the copy-number docstring line (§13.2)."""
    mine = Path(key_format.__file__).read_text().splitlines()
    assert "COPY 2 OF 3" in mine[0]
    assert (
        hashlib.sha256("\n".join(mine[1:]).encode()).hexdigest()
        == CANONICAL_BODY_SHA256
    )


def test_mint_key_round_trips() -> None:
    """`mint_key` is unused gateway-side but must stay in lockstep (§13.2)."""
    for _ in range(200):
        key = key_format.mint_key()
        assert key_format.crc32_ok(key)
        parts = key_format.split_key(key)
        assert parts is not None
        body, crc = parts
        assert len(body) == key_format.BODY_LEN and len(crc) == key_format.CRC_LEN
        assert key_format.key_prefix(key) == body[: key_format.KEY_PREFIX_LEN]
