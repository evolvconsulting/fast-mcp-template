# fast-mcp-template gateway image. ARM64 in production (Fargate), digest-pinned bases.
#
# Both base digests are multi-arch INDEX digests, read 2026-09-30 (fast-mcp-ado) with
#   docker buildx imagetools inspect python:3.12-slim
#   docker buildx imagetools inspect ghcr.io/astral-sh/uv:0.7.12
# An index digest is still immutable (it names exact per-platform manifests) and resolves to
# linux/arm64 for the production build and to linux/amd64 for the CI smoke build.
# RE-READ THEM when you adopt this file: a base ages, and the image scan fails on its CVEs.
# If a CVE has a fixed package and no newer base yet, add a NAMED, exact-version
# `apt-get install --only-upgrade` layer for just that package (never a floating
# full-system upgrade) and remove it in the digest-bump PR.

FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS builder

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.7.12@sha256:4faec156e35a5f345d57804d8858c6ba1cf6352ce5f4bffc11b7fdebdef46a38 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# `license-files` in pyproject.toml makes the build read LICENSE and NOTICE.
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY src/ src/

# FROZEN: a stale lock fails the image build (no floating install). Add
# `--extra platform-auth` when the gateway uses the vault (boto3).
RUN uv sync --frozen --no-dev

FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

# Numeric ids, no login shell, no home: the task runs as 10001 and never needs more.
RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin appuser

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_TEMPLATE_MCP_HOST=0.0.0.0 \
    MCP_TEMPLATE_MCP_PORT=8000

USER 10001

# Plain HTTP: the load balancer's target (and the health check) lives here.
EXPOSE 8000

# The stdlib probe: no curl in a slim image. Keep it in step with the
# `healthCheck` in deploy/taskdef.base.json.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Exec form: the server is PID 1 and gets SIGTERM directly.
ENTRYPOINT ["fast-mcp-template"]
CMD ["http"]
