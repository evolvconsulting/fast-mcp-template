"""Secrets Manager vault client for per-user DOWNSTREAM credentials.

A gateway that calls an upstream service on behalf of each user keeps that
user's upstream credential here, not in the key the user presents to the
gateway. Reads `{secrets_prefix}/users/{user_id}/{server_key}`: a JSON object
of string fields, written by the platform backend. What the fields are (an
organisation and a PAT, a token, a refresh token) is the gateway's business.

Fail directions (§7.2 - credential resolution fails CLOSED, always):
  * `ResourceNotFoundException` → ``None``. Absence is a *normal* state that feeds
    the fail-closed decision in `resolve_identity`, not an error.
  * **Any** other failure → :class:`VaultUnavailableError`, which `resolve_identity`
    converts to `MissingCredentialsError` → 401. Deliberately not limited to
    botocore exceptions: endpoint unreachable, throttling, access denied, an
    unparseable payload, and a malformed `endpoint_url` (a plain `ValueError`
    from client construction) all land on the same 401 rung.

Secret handling (§7.3): the payload is never logged. Log lines carry
``{user_id, secret_name, fingerprint}`` only.

boto3 is imported lazily: install the `platform-auth` extra to use this module.
"""

import hashlib
import json
import logging
from time import monotonic
from typing import Any

from anyio import to_thread

from fast_mcp_template.config import Settings
from fast_mcp_template.http.health import CheckResult

logger = logging.getLogger(__name__)

# Bounded failure budget (§7.2 - failing closed is only fail-closed if it is *fast*).
# botocore's defaults are 60 s connect + 60 s read, multiplied by an adaptive retry
# policy: a paused vault measured ~630 s to a 401. That is an outage, not a refusal.
# Budget: 2 s connect + 3 s read, one attempt, no retries = 5 s worst case, chosen because this
# lookup sits on the request-serving hot path behind a 60 s in-proc cache - a healthy
# Secrets Manager (or LocalStack) answers in well under a second, so 5 s is ~10x
# headroom over normal while staying inside any sane client/ALB timeout. Retries are
# off on purpose: the caller retries by making another request, and the fan-out risk
# is occupied connections, not a lost lookup.
VAULT_CONNECT_TIMEOUT_SECONDS = 2
VAULT_READ_TIMEOUT_SECONDS = 3
# Named RETRIES, not attempts: measured against botocore 1.43.58, `max_attempts`
# counts *retries* in every mode (`{"mode": "standard", "max_attempts": 1}`
# normalizes to `total_max_attempts: 2`), so `1` would silently double the budget.
# 0 is the only value that yields a single attempt. Asserted in the unit test.
VAULT_MAX_RETRIES = 0
VAULT_TOTAL_ATTEMPTS = VAULT_MAX_RETRIES + 1
VAULT_BUDGET_SECONDS = (
    VAULT_CONNECT_TIMEOUT_SECONDS + VAULT_READ_TIMEOUT_SECONDS
) * VAULT_TOTAL_ATTEMPTS


class VaultUnavailableError(RuntimeError):
    """Any vault failure that is *not* a clean not-found (§4.2(c))."""


#: A user's downstream credential: the JSON object's string fields.
Credentials = dict[str, str]


def fingerprint(secret: str) -> str:
    """`sha256(secret)[:16]` - the only secret-derived value allowed in a log."""
    return hashlib.sha256(secret.encode()).hexdigest()[:16]


class VaultClient:
    """Reads one user's downstream credential from Secrets Manager."""

    def __init__(
        self,
        *,
        secrets_prefix: str,
        server_key: str,
        endpoint_url: str | None,
        cache_ttl_seconds: int = 60,
    ) -> None:
        """Configure the client; nothing is read until the first lookup."""
        self.secrets_prefix = secrets_prefix
        self.server_key = server_key
        self.endpoint_url = endpoint_url
        self.cache_ttl_seconds = cache_ttl_seconds
        # Only *hits* are cached. A miss is not cached on purpose: it fails the
        # request closed anyway (no ADO traffic to shield), and caching it would
        # add up to `cache_ttl_seconds` of latency to a user who has just stored
        # their credentials.
        self._cache: dict[str, tuple[float, Credentials]] = {}
        self._client: Any | None = None

    def _secret_name(self, user_id: str) -> str:
        return f"{self.secrets_prefix}/users/{user_id}/{self.server_key}"

    def _boto_client(self) -> Any:  # noqa: ANN401 - an untyped boto3 client
        # ponytail: no lock - a race just builds one throwaway client, and boto3
        # clients are independent. Add a lock only if client construction gets costly.
        if self._client is None:
            import boto3  # noqa: PLC0415 - optional extra, imported when first used
            from botocore.config import Config  # noqa: PLC0415

            self._client = boto3.client(
                "secretsmanager",
                endpoint_url=self.endpoint_url,
                config=Config(
                    connect_timeout=VAULT_CONNECT_TIMEOUT_SECONDS,
                    read_timeout=VAULT_READ_TIMEOUT_SECONDS,
                    retries={"mode": "standard", "max_attempts": VAULT_MAX_RETRIES},
                ),
            )
        return self._client

    def _fetch(self, secret_name: str) -> tuple[Credentials, str] | None:
        """Blocking Secrets Manager read. Runs in a worker thread."""
        from botocore.exceptions import ClientError  # noqa: PLC0415 - optional extra

        try:
            response = self._boto_client().get_secret_value(SecretId=secret_name)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return None
            raise VaultUnavailableError(f"vault read failed: {secret_name}") from exc
        except Exception as exc:  # noqa: BLE001 - §4.2(c): ANY other failure fails CLOSED
            # Deliberately broader than botocore: `boto3.client(endpoint_url=...)` raises
            # a plain ValueError for a scheme-less endpoint (`AWS_ENDPOINT_URL=host:4566`),
            # and `Settings` uses extra="ignore", so config typos surface only here. A
            # non-VaultUnavailableError escape becomes an MCP internal error instead of the
            # pinned 401 - a failure oracle (§7.3 rule 4) that §7.4 Arm 3's `!= 200`
            # row would not catch.
            raise VaultUnavailableError(f"vault read failed: {secret_name}") from exc

        try:
            raw = response["SecretString"]
            payload = json.loads(raw)
            if not isinstance(payload, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in payload.items()
            ):
                raise TypeError("payload must be a JSON object of string fields")
            return payload, raw
        except Exception as exc:  # noqa: BLE001 - an unusable payload fails CLOSED
            raise VaultUnavailableError(
                f"vault payload unusable: {secret_name}"
            ) from exc

    async def get_credentials(self, user_id: str) -> Credentials | None:
        """Credentials for ``user_id``; ``None`` if the secret does not exist.

        Raises:
            VaultUnavailableError: on any other vault failure (→ 401 upstream).
        """
        secret_name = self._secret_name(user_id)

        cached = self._cache.get(user_id)
        if cached is not None:
            stored_at, hit = cached
            if monotonic() - stored_at < self.cache_ttl_seconds:
                return hit
            del self._cache[user_id]

        # boto3 is blocking; aioboto3 was rejected (§13.4 conditional-item 2).
        fetched = await to_thread.run_sync(self._fetch, secret_name)

        if fetched is None:
            logger.info(
                "vault lookup: no credentials stored",
                extra={"user_id": user_id, "secret_name": secret_name},
            )
            return None

        credentials, raw = fetched
        # Reap on write (miss path only, so never on the hot path): without it the
        # dict grows with every distinct user ever seen and holds their secrets in
        # memory long past their TTL.
        now = monotonic()
        self._cache = {
            uid: entry
            for uid, entry in self._cache.items()
            if now - entry[0] < self.cache_ttl_seconds
        }
        self._cache[user_id] = (now, credentials)
        logger.info(
            "vault lookup: credentials resolved",
            extra={
                "user_id": user_id,
                "secret_name": secret_name,
                "fingerprint": fingerprint(raw),
            },
        )
        return credentials


#: A user id no real user has: NotFound on it means the read path
#: (credentials, KMS, network) works; AccessDenied or a timeout means not.
READINESS_SENTINEL_USER = "__readiness__"


def build_vault(settings: Settings) -> VaultClient:
    """Return a `VaultClient` configured from `settings`."""
    return VaultClient(
        secrets_prefix=settings.mcp_secrets_prefix,
        server_key=settings.server_key,
        endpoint_url=settings.aws_endpoint_url,
        cache_ttl_seconds=settings.vault_cache_ttl_seconds,
    )


async def check_vault(vault: VaultClient) -> CheckResult:
    """Readiness check: a read of the sentinel user's secret.

    None (not found) is healthy; any other failure is not. Register it:
    `health.add("vault", lambda: check_vault(vault))`.
    """
    try:
        await vault.get_credentials(READINESS_SENTINEL_USER)
    except VaultUnavailableError:
        return CheckResult("vault", False, "unavailable")
    return CheckResult("vault", True, "read path ok")
