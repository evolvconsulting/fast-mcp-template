"""Tests for the legacy shared-key verifier (plan T-A1)."""

from fast_mcp_template.auth.legacy import LegacyKeyVerifier


async def test_accepts_exact_key_and_stamps_claims() -> None:
    tok = await LegacyKeyVerifier("s3cret-shared").verify_token("s3cret-shared")
    assert tok is not None and tok.client_id == "legacy"
    assert tok.scopes == [] and tok.expires_at is None
    assert tok.claims["auth_path"] == "legacy" and len(tok.claims["key_fp"]) == 8
    assert set(tok.claims) == {"auth_path", "key_fp"}


async def test_rejects_near_misses() -> None:
    v = LegacyKeyVerifier("s3cret-shared")
    for bad in (
        "",
        "s3cret-share",
        "s3cret-shared ",
        "S3CRET-SHARED",
        "s3cret-shared\n",
    ):
        assert await v.verify_token(bad) is None


async def test_no_lockout_after_many_failures() -> None:
    v = LegacyKeyVerifier("s3cret-shared")
    for _ in range(100):
        assert await v.verify_token("wrong") is None
    assert await v.verify_token("s3cret-shared") is not None


async def test_non_ascii_token_does_not_raise() -> None:
    assert await LegacyKeyVerifier("s3cret-shared").verify_token("s3crét") is None
