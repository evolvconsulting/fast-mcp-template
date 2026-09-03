"""The placeholder tool, and the seam the template promises.

These tests exist so a fresh clone has a suite that is not empty. An
empty suite is a green that tested nothing, and `pytest` exits 5 on
one - which would make the Gate tier red for a reason that is not about
the project.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fast_mcp_template import __main__ as main_module
from fast_mcp_template.config import Settings
from fast_mcp_template.server import build_server, greet


def test_greet_uses_the_configured_greeting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TEMPLATE_GREETING", "hi")
    assert greet("world") == "hi world"


def test_greet_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_TEMPLATE_GREETING", raising=False)
    assert greet("world") == "hello world"


def test_the_server_is_named_after_the_project() -> None:
    assert build_server().name == "fast-mcp-template"


def test_main_runs_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    # __main__ runs OUT OF PROCESS in real use, so coverage would never
    # see it. Driving `main()` with a stub in place tests the wiring -
    # that the entry point reaches the factory and calls run() - which
    # is the part that breaks on a rename.
    called: list[str] = []

    class _Stub:
        def run(self) -> None:
            called.append("run")

    monkeypatch.setattr(main_module, "build_server", lambda: _Stub())
    main_module.main()
    assert called == ["run"]


def test_settings_reject_an_unknown_field() -> None:
    # `extra="forbid"` is the assertion, not a style choice: a typo in
    # an environment variable name must be loud, never ignored.
    with pytest.raises(ValidationError):
        Settings(nonesuch="x")  # type: ignore[call-arg]
