"""The MCP server object and its one placeholder tool.

DELETE `greet` and `ping` and write your own tools. They exist so that a
fresh clone has a server `fastmcp inspect` can find, which is what makes
the Quickstart gate a real assertion rather than a skipped step.

**THE TOOL BODY IS A PLAIN FUNCTION AND THE DECORATED NAME WRAPS IT.**
Decorating the implementation directly rebinds the name to a tool
object, so a test importing it can no longer call it - the workaround
is to reach through an attribute of the tool wrapper, which is a
private detail of whatever FastMCP version you pinned. Keeping the
logic in a plain function means the tests exercise the code and the
decorator stays a thin registration.
"""

from __future__ import annotations

from fastmcp import FastMCP

from fast_mcp_template.config import load_settings
from fast_mcp_template.http.audit import ToolCallAuditMiddleware
from fast_mcp_template.http.health import HealthRegistry, register_health_routes
from fast_mcp_template.tools.annotations import READ_ONLY
from fast_mcp_template.tools.errors import raise_tool_error

# `mask_error_details=True` masks the text of any exception a tool did
# not map itself, so a forgotten try/except cannot leak a secret.
mcp: FastMCP = FastMCP("fast-mcp-template", mask_error_details=True)
# One `mcp_tool_call` line per tool call; registered once, here, so
# building the app twice never doubles the line.
mcp.add_middleware(ToolCallAuditMiddleware())

#: The readiness checks behind `/health/ready`. Register yours with
#: `health.add(name, check)` (see `http/health.py`); the routes are
#: added once, here, so building the app twice never doubles them.
health: HealthRegistry = HealthRegistry()
register_health_routes(mcp, health)


def greet(name: str) -> str:
    """Return the configured greeting followed by `name`.

    Args:
        name: who to greet.

    Returns:
        The greeting.
    """
    return f"{load_settings().greeting} {name}"


@mcp.tool(annotations=READ_ONLY)
def ping(name: str) -> str:
    """Return a greeting. Replace this with the first real tool.

    Every tool body follows this shape: do the work, and map ANY
    failure through `raise_tool_error` so the caller sees a stable
    message plus the request id, never exception text.

    Args:
        name: who to greet.

    Returns:
        The configured greeting followed by `name`.
    """
    try:
        return greet(name)
    except Exception as exc:  # noqa: BLE001 - the mapping IS the contract
        raise_tool_error(exc, operation="ping")


def build_server() -> FastMCP:
    """Return the configured server.

    A factory, not a bare module global, because `fastmcp inspect` and
    the tests should reach the server the same way the entry point does.
    """
    return mcp
