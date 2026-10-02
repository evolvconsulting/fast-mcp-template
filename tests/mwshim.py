"""One namespace for the middleware names the ported tests use.

The fast-mcp-ado suite imported one `middleware` module; the template
splits it (`http.audit`, `http.body_limit`, `limits.middleware`,
`http`). The tests keep reading `mw.X` and this module answers.
"""

from __future__ import annotations

from types import SimpleNamespace

from fast_mcp_template.auth.claims import auth_path_of
from fast_mcp_template.http import build_http_middleware, wrap_http_app
from fast_mcp_template.http.audit import (
    AuthAuditMiddleware,
    FailureAlarm,
    ToolCallAuditMiddleware,
)
from fast_mcp_template.http.body_limit import BodySizeLimitMiddleware
from fast_mcp_template.limits.middleware import (
    PLATFORM_IP_BUCKET_FACTOR,
    RATE_LIMIT_CLAIM_CEILING_FACTOR,
    RateLimitMiddleware,
)

mw = SimpleNamespace(
    __name__="fast_mcp_template",
    auth_path_of=auth_path_of,
    build_http_middleware=build_http_middleware,
    wrap_http_app=wrap_http_app,
    AuthAuditMiddleware=AuthAuditMiddleware,
    FailureAlarm=FailureAlarm,
    ToolCallAuditMiddleware=ToolCallAuditMiddleware,
    BodySizeLimitMiddleware=BodySizeLimitMiddleware,
    RateLimitMiddleware=RateLimitMiddleware,
    PLATFORM_IP_BUCKET_FACTOR=PLATFORM_IP_BUCKET_FACTOR,
    RATE_LIMIT_CLAIM_CEILING_FACTOR=RATE_LIMIT_CLAIM_CEILING_FACTOR,
)
