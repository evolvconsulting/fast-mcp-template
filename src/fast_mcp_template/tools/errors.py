"""Tool failures become `ToolError` with a stable message.

The contract: a tool's caller sees either a message written for them
(an exception type registered with `register_safe_error`) or
`GENERIC_TOOL_ERROR`, and always the request id. Exception text from
anything else (a PAT in a URL, an upstream body, a stack frame) never
reaches the client; it goes to the log with the traceback.

Pair this with `FastMCP(..., mask_error_details=True)`, which masks
whatever a tool forgot to wrap.
"""

from __future__ import annotations

import logging
from typing import Final, NoReturn

from fastmcp.exceptions import ToolError

from fast_mcp_template.http.net import current_request_id
from fast_mcp_template.tools.validation import ValidationError

logger = logging.getLogger(__name__)

#: The text for any failure whose own text is not for the caller.
#: Reword it for your service ("Unexpected error while calling X").
GENERIC_TOOL_ERROR: Final = "Unexpected error while running the tool"

#: Exception types whose message is written for the caller.
SAFE_ERROR_TYPES: list[type[BaseException]] = [ValidationError]


def register_safe_error(exc_type: type[BaseException]) -> None:
    """Declare that `exc_type`'s message is safe to show a caller."""
    if exc_type not in SAFE_ERROR_TYPES:
        SAFE_ERROR_TYPES.append(exc_type)


def safe_error_text(exc: BaseException) -> str:
    """Return the text of `exc` that is safe to show a caller."""
    if isinstance(exc, tuple(SAFE_ERROR_TYPES)):
        return str(exc)
    return GENERIC_TOOL_ERROR


def _rid_suffix(req_id: str | None) -> str:
    return f" (request_id={req_id or 'unknown'})"


def raise_tool_error(exc: BaseException, *, operation: str) -> NoReturn:
    """Turn any tool failure into a `ToolError` carrying the request id.

    A registered safe type passes its own message through. Anything
    else is logged with its traceback and replaced by
    `GENERIC_TOOL_ERROR`.

    Args:
        exc: what the tool body caught.
        operation: the tool name, for the log line.

    Raises:
        ToolError: always.
    """
    if isinstance(exc, ToolError):  # already mapped; never re-wrap
        raise exc
    req_id = current_request_id()
    if isinstance(exc, tuple(SAFE_ERROR_TYPES)):
        raise ToolError(f"{exc}{_rid_suffix(req_id)}") from exc
    logger.exception(
        "tool_failed",
        extra={
            "event": "tool_failed",
            "operation": operation,
            "error_type": type(exc).__name__,
            "request_id": req_id,
        },
    )
    raise ToolError(f"{GENERIC_TOOL_ERROR}{_rid_suffix(req_id)}") from exc
