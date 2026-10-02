# Changelog

Notable changes to this project. Newest first.

## Unreleased

- EC-639 step 1: HTTP serving blocks (client IP, request id, body limit,
  problem+json errors, `fast-mcp-template http`) and the Redis client with
  internal-CA TLS.
- EC-639 step 2: health endpoints with a pluggable readiness check list
  (`HealthRegistry`), cached 5 s, each check capped at 2 s.
- EC-639 step 3: free security CI (`security`, `weekly-lock-audit`),
  `main-only-by-pr.yml`, `pr-title.yml`; `check_advisories.py` is now wired.
