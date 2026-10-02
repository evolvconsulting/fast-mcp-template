# Changelog

Notable changes to this project. Newest first.

## Unreleased

- BREAKING: `fast-mcp-template http` now refuses to boot without authentication.
  With the default `MCP_TEMPLATE_AUTH_MODE=legacy`, required: `MCP_TEMPLATE_API_KEY` (a strong
  shared key) and `MCP_TEMPLATE_REDIS_URL`. `dual` and `platform` also need
  `MCP_TEMPLATE_BE_BASE_URL` (https in production) and a strong
  `MCP_TEMPLATE_INTERNAL_AUTH_SECRET`, and `platform` refuses to boot if `MCP_TEMPLATE_API_KEY`
  is set.
  With `MCP_TEMPLATE_ENVIRONMENT=production` the Redis URL must be `rediss://` and
  `MCP_TEMPLATE_INTERNAL_CA_CERT` must be set. The only way to run without a credential is
  the dev-only `MCP_TEMPLATE_DANGEROUSLY_DISABLE_AUTH` (refused in production). See
  "Upgrading" in the README.
- EC-639: every `uses:` in `ci.yml` is SHA-pinned and `scripts/check-action-pins.py`
  (a Gate step) fails on any that is not.

- EC-639 step 1: HTTP serving blocks (client IP, request id, body limit,
  problem+json errors, `fast-mcp-template http`) and the Redis client with
  internal-CA TLS.
- EC-639 step 2: health endpoints with a pluggable readiness check list
  (`HealthRegistry`), cached 5 s, each check capped at 2 s.
- EC-639 step 3: free security CI (`security`, `weekly-lock-audit`),
  `main-only-by-pr.yml`, `pr-title.yml`; `check_advisories.py` is now wired.
- EC-639 step 4: tool safety (`path_segment`, `raise_tool_error`, annotation
  classes) and three per-tool sweeps, each with a control.
- EC-639 step 5: Redis Lua token bucket and `RateLimitMiddleware`,
  `AuthAuditMiddleware`, `FailureAlarm`, `ToolCallAuditMiddleware`;
  `wrap_http_app` now adds the audit layer, `build_http_middleware` the rate
  limit. Tests gain pytest-asyncio (`asyncio_mode = "auto"`) and fakeredis.
- EC-639 step 6: authentication. `fast-mcp-template http` now fails closed:
  it needs a configured credential and Redis, or the explicit
  `MCP_TEMPLATE_DANGEROUSLY_DISABLE_AUTH` escape (never in production).
  Adds `DualModeVerifier`, `LegacyKeyVerifier`, the optional platform auth
  (`PlatformKeyVerifier`, `key_format`, vault) and the boot refusals.
- EC-639: `ConcurrencyLimitMiddleware` and `RequestBodyGuard`, wired in `build_app`.
- EC-639 step 7a: production stage files, base task definition, and
  `scripts/check-stage-files.py` (a Gate step) driven by `deploy/gateway.json`.
- EC-639 step 7b: Dockerfile and the `image` CI job, `build-image.yml`, `deploy.yml`,
  `oidc-claims-probe.yml`, `scripts/render-taskdef.py`, `infra/` (workflow-bound OIDC trusts,
  least-privilege policies, ECR, CloudWatch census) and a rollback runbook.
