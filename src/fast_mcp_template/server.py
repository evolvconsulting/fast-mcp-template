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

mcp: FastMCP = FastMCP("fast-mcp-template")


def greet(name: str) -> str:
    """Return the configured greeting followed by `name`.

    Args:
        name: who to greet.

    Returns:
        The greeting.
    """
    return f"{load_settings().greeting} {name}"


@mcp.tool
def ping(name: str) -> str:
    """Return a greeting. Replace this with the first real tool.

    Args:
        name: who to greet.

    Returns:
        The configured greeting followed by `name`.
    """
    return greet(name)


def build_server() -> FastMCP:
    """Return the configured server.

    A factory, not a bare module global, because `fastmcp inspect` and
    the tests should reach the server the same way the entry point does.
    """
    return mcp
