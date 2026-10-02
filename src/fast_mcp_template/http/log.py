"""Log-safety helpers for caller-controlled text."""

from __future__ import annotations

import re
from typing import Final

_CONTROL_CHARS_RE: Final = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def present(**fields: object) -> dict[str, object]:
    """Return `fields` without None values (absent claim, no field)."""
    return {k: v for k, v in fields.items() if v is not None}


def clean_log_text(value: object, limit: int = 256) -> str:
    """Return `value` as one bounded line.

    Control characters become `?` and long text is cut. For
    caller-controlled strings (a tool name, a request path) so one
    request cannot forge a console line or write a megabyte event.
    """
    text = _CONTROL_CHARS_RE.sub("?", str(value))
    return text if len(text) <= limit else text[: limit - 3] + "..."
