"""Input validation for values a tool puts into an upstream request.

`path_segment` is the one to reach for in any REST-proxy gateway: a
tool that interpolates a caller-supplied `project` into
`/{project}/items` lets `project="../otherorg"` reach another tenant.
The fast-mcp-ado rebuild had exactly this bug; every proxy gateway has
the same bug class.
"""

from __future__ import annotations

import re
from typing import Final
from urllib.parse import quote


class ValidationError(Exception):
    """Raised when a tool argument fails validation.

    Its message is written for the caller, so `raise_tool_error`
    passes it through (it is registered as a safe error type).
    """

    def __init__(self, field: str, message: str) -> None:
        """Record the offending `field` and the message."""
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


#: Refused inside a segment: separators, C0 and C1 controls, line and
#: paragraph separators, and the zero-width, bidi-mark and
#: bidi-override characters that spoof a name in logs and error text.
SEGMENT_RE: Final = re.compile(
    r"[^/\\\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060\u2066-\u2069\ufeff]{1,256}"
)


def path_segment(value: str, *, field: str) -> str:
    r"""Return `value` percent-encoded as ONE URL path segment.

    A `/`, `\`, control or bidi character, `..` or edge whitespace
    could rewrite the request path or spoof a logged name, so it is
    refused. `fullmatch` has no `$`, so a trailing newline is caught
    by the character class.

    Args:
        value: the caller-supplied text.
        field: the argument name, for the error message.

    Returns:
        The percent-encoded segment.

    Raises:
        ValidationError: when `value` is not one safe segment.
    """
    if (
        not isinstance(value, str)
        or not SEGMENT_RE.fullmatch(value)
        or ".." in value  # also covers ".." itself
        or value == "."
        or value != value.strip()
    ):
        raise ValidationError(
            field,
            "must be a single path segment (no '/', '\\', '..' or control characters)",
        )
    try:
        return quote(value, safe="")
    except UnicodeEncodeError:  # a lone surrogate is invalid input
        raise ValidationError(field, "must be valid Unicode text") from None
