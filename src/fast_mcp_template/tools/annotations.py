"""The five tool-annotation classes, classified by what a tool does.

Pick the class from the HTTP verbs the tool issues (the sweep in
`tests/test_tool_safety.py` enforces that a GET-only tool is read-only
and that every DELETE or PUT tool is destructive):

- `READ_ONLY`: only reads. GET.
- `WRITE_IDEMPOTENT`: writes, and a repeat changes nothing more. PUT
  to a non-destructive resource.
- `CREATE`: writes something new each call. POST that creates.
- `DESTRUCTIVE`: removes or overwrites, repeat-safe. DELETE, PUT over
  an existing resource.
- `DESTRUCTIVE_NON_IDEMPOTENT`: removes or changes state and a repeat
  does more. POST that triggers (run a pipeline), bulk PATCH.

`open_world_hint` is True everywhere: a gateway tool reaches an
upstream service by definition. Set it False for a tool that does not.
"""

from __future__ import annotations

from typing import Final

from mcp.types import ToolAnnotations

READ_ONLY: Final = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)
WRITE_IDEMPOTENT: Final = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)
CREATE: Final = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
DESTRUCTIVE: Final = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=True,
)
DESTRUCTIVE_NON_IDEMPOTENT: Final = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=True,
)
