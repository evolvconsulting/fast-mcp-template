"""Tool safety: path segments, error mapping, annotations, and sweeps.

The three SWEEPS scale to any number of tools for free: write a tool
and each sweep covers it. Each sweep ships with a CONTROL, because a
sweep over an empty or blind population is a green that tested
nothing. The controls feed the same function a source or a server that
is known to be bad and require it to say so.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from fast_mcp_template import server
from fast_mcp_template.tools import errors
from fast_mcp_template.tools.errors import (
    GENERIC_TOOL_ERROR,
    raise_tool_error,
    register_safe_error,
    safe_error_text,
)
from fast_mcp_template.tools.validation import ValidationError, path_segment

SRC = Path(__file__).resolve().parent.parent / "src" / "fast_mcp_template"
#: Where tools live: the server module and anything under tools/.
TOOL_SOURCES = [SRC / "server.py", *sorted((SRC / "tools").glob("*.py"))]
SECRET = "abc123SECRET-token-value"  # noqa: S105 - a fake, planted on purpose


# --- path_segment ----------------------------------------------------


def test_path_segment_accepts_and_encodes() -> None:
    assert path_segment("Proj", field="project") == "Proj"
    assert path_segment("My Project", field="project") == "My%20Project"
    assert path_segment("a.b-c_d~e", field="p") == "a.b-c_d~e"
    assert path_segment("caf\u00e9", field="p") == "caf%C3%A9"


@pytest.mark.parametrize(
    "bad",
    [
        "../otherorg",
        "a/b",
        "a\\b",
        "..",
        ".",
        "a..b",
        "",
        " lead",
        "trail ",
        "line\nbreak",
        "trailing newline\n",
        "nul\x00",
        "del\x7f",
        "c1\x85",
        "zero\u200bwidth",
        "bidi\u202eoverride",
        "x" * 257,
        "lone\ud800surrogate",
    ],
)
def test_path_segment_refuses(bad: str) -> None:
    with pytest.raises(ValidationError) as info:
        path_segment(bad, field="project")
    assert info.value.field == "project"
    assert "project" in str(info.value)


def test_path_segment_refuses_a_non_string() -> None:
    with pytest.raises(ValidationError):
        path_segment(5, field="project")  # type: ignore[arg-type]


def test_path_segment_boundary_length() -> None:
    assert path_segment("x" * 256, field="p") == "x" * 256


# --- raise_tool_error ------------------------------------------------


def test_a_safe_type_passes_its_message_with_the_request_id() -> None:
    with pytest.raises(ToolError, match=r"project: must be .* \(request_id=unknown\)"):
        raise_tool_error(ValidationError("project", "must be a segment"), operation="t")


def test_anything_else_is_generic_logged_and_never_echoed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR), pytest.raises(ToolError) as info:
        raise_tool_error(RuntimeError(SECRET), operation="t")
    assert str(info.value) == f"{GENERIC_TOOL_ERROR} (request_id=unknown)"
    assert SECRET not in str(info.value)
    rec = next(r for r in caplog.records if r.__dict__.get("event") == "tool_failed")
    assert rec.__dict__["operation"] == "t"
    assert rec.exc_info is not None  # the traceback is kept server side


def test_a_toolerror_is_never_rewrapped() -> None:
    inner = ToolError("already mapped")
    with pytest.raises(ToolError) as info:
        raise_tool_error(inner, operation="t")
    assert info.value is inner


def test_the_request_id_is_taken_from_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(errors, "current_request_id", lambda: "rid-1")
    with pytest.raises(ToolError, match=r"\(request_id=rid-1\)"):
        raise_tool_error(RuntimeError("x"), operation="t")


def test_register_safe_error_is_explicit_and_idempotent() -> None:
    class MineError(Exception):
        pass

    before = list(errors.SAFE_ERROR_TYPES)
    try:
        assert safe_error_text(MineError("nope")) == GENERIC_TOOL_ERROR
        register_safe_error(MineError)
        register_safe_error(MineError)
        assert errors.SAFE_ERROR_TYPES.count(MineError) == 1
        assert safe_error_text(MineError("caller text")) == "caller text"
    finally:
        errors.SAFE_ERROR_TYPES[:] = before


# --- sweep helpers ---------------------------------------------------


def tool_args(tool: Any) -> dict[str, Any]:
    """Return minimal valid arguments built from the tool's schema."""
    sample = {
        "string": "x",
        "integer": 1,
        "number": 1.0,
        "boolean": True,
        "array": [],
        "object": {},
    }
    props = tool.parameters.get("properties", {})
    return {
        name: sample.get(props[name].get("type"), "x")
        for name in tool.parameters.get("required", [])
    }


async def _tool(mcp: FastMCP, name: str) -> Any:
    """Return the registered tool `name` (Any: it is patched)."""
    tool = await mcp.get_tool(name)
    assert tool is not None, name
    return tool


async def leak_report(mcp: FastMCP) -> tuple[int, list[str]]:
    """Make every tool raise SECRET; return (tools swept, failures)."""
    swept = 0
    bad: list[str] = []
    for listed in await mcp.list_tools():
        tool = await _tool(mcp, listed.name)
        original = tool.fn

        def boom(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError(SECRET)

        tool.fn = boom
        try:
            async with Client(mcp) as client:
                result = await client.call_tool(
                    tool.name, tool_args(tool), raise_on_error=False
                )
        finally:
            tool.fn = original
        swept += 1
        dump = json.dumps([c.model_dump() for c in result.content], default=str)
        dump += json.dumps(result.structured_content, default=str)
        if result.is_error is not True or SECRET in dump:
            bad.append(f"{tool.name}: is_error={result.is_error} {dump[:160]}")
    return swept, bad


# --- sweep 1: no tool leaks exception text ---------------------------


def test_sweep_no_tool_leaks_exception_text() -> None:
    swept, bad = asyncio.run(leak_report(server.mcp))
    assert swept >= 1  # the control: the population is not empty
    assert bad == []


def test_sweep_control_an_unmasked_server_is_caught_leaking() -> None:
    scratch: FastMCP = FastMCP("scratch", mask_error_details=False)

    @scratch.tool
    def leaky() -> str:
        """Fail with a message that carries a secret."""
        raise RuntimeError(SECRET)

    swept, bad = asyncio.run(leak_report(scratch))
    assert swept == 1
    assert len(bad) == 1  # the instrument can see a leak


def test_a_guarded_tool_reports_the_generic_text_and_a_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The REAL ping body, with the failure injected below it, so the
    # try/except and `raise_tool_error` are what is under test.
    def boom(name: str) -> str:
        raise RuntimeError(SECRET)

    monkeypatch.setattr(server, "greet", boom)

    async def call() -> str:
        async with Client(server.mcp) as client:
            result = await client.call_tool("ping", {"name": "x"}, raise_on_error=False)
        assert result.is_error is True
        return json.dumps([c.model_dump() for c in result.content])

    text = asyncio.run(call())
    assert GENERIC_TOOL_ERROR in text
    assert "request_id=" in text
    assert SECRET not in text


# --- sweep 2: annotations --------------------------------------------

#: The tools that destroy or overwrite. Named by hand, never derived
#: from the HTTP verb: a destructive POST or PATCH must not slip by.
EXPECTED_DESTRUCTIVE: set[str] = set()


def verbs_by_tool(source: str, client: str = "client") -> dict[str, set[str]]:
    """Return function name -> the `<client>.<verb>` verbs it calls."""
    out: dict[str, set[str]] = {}
    for fn in ast.parse(source).body:
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        out[fn.name] = {
            c.func.attr
            for c in ast.walk(fn)
            if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute)
            and isinstance(c.func.value, ast.Name)
            and c.func.value.id == client
        }
    return out


HINTS = ("read_only_hint", "destructive_hint", "idempotent_hint", "open_world_hint")


def test_sweep_every_tool_declares_all_four_hints() -> None:
    tools = asyncio.run(server.mcp.list_tools())
    assert len(tools) >= 1  # the control
    for tool in tools:
        assert tool.annotations is not None, tool.name
        for hint in HINTS:
            assert isinstance(getattr(tool.annotations, hint), bool), (tool.name, hint)


def test_sweep_destructive_hint_matches_the_hand_written_list() -> None:
    for tool in asyncio.run(server.mcp.list_tools()):
        assert tool.annotations is not None
        assert tool.annotations.destructive_hint is (tool.name in EXPECTED_DESTRUCTIVE)
        if tool.name in EXPECTED_DESTRUCTIVE:
            assert tool.annotations.read_only_hint is False, tool.name


SAMPLE_TOOLS = """
async def get_a(): return await client.get("/a")
async def get_b(): return await client.get("/b")
async def drop_c(): return await client.delete("/c")
async def put_d(): return await client.put("/d", {})
async def other(): return await other_thing.get("/e")
def helper(): return 1
"""


def test_sweep_control_the_verb_scan_finds_each_class() -> None:
    verbs = verbs_by_tool(SAMPLE_TOOLS)
    assert [n for n, v in verbs.items() if v == {"get"}] == ["get_a", "get_b"]
    assert {n for n, v in verbs.items() if "delete" in v} == {"drop_c"}
    assert {n for n, v in verbs.items() if "put" in v} == {"put_d"}
    assert verbs["other"] == set()  # another object's .get is not ours
    assert verbs["helper"] == set()


def test_sweep_verbs_agree_with_annotations_for_the_real_tools() -> None:
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    for path in TOOL_SOURCES:
        for name, verbs in verbs_by_tool(path.read_text()).items():
            if name not in tools or not verbs:
                continue
            ann = tools[name].annotations
            assert ann is not None
            if verbs <= {"get", "head"}:
                assert ann.read_only_hint is True, name
            if verbs & {"delete", "put"}:
                assert name in EXPECTED_DESTRUCTIVE, name
                assert ann.destructive_hint is True, name


# --- sweep 3: no raw argument reaches a URL path ---------------------


def raw_path_arguments(source: str) -> dict[str, set[str]]:
    """Return function -> args interpolated RAW into a path template.

    A path template is an f-string whose first constant starts with
    `/`. An interpolation is safe when its expression calls
    `path_segment`; a bare argument name is not. The check is static
    and deliberately narrow: it finds the bug class, not every bug.
    """
    found: dict[str, set[str]] = {}
    for fn in ast.parse(source).body:
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        params = {a.arg for a in fn.args.args}
        for node in ast.walk(fn):
            if not isinstance(node, ast.JoinedStr):
                continue
            first = node.values[0] if node.values else None
            if not (
                isinstance(first, ast.Constant) and str(first.value).startswith("/")
            ):
                continue
            for part in node.values:
                if not isinstance(part, ast.FormattedValue):
                    continue
                calls = {
                    c.func.id
                    for c in ast.walk(part.value)
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                }
                if "path_segment" in calls:
                    continue
                for n in ast.walk(part.value):
                    if isinstance(n, ast.Name) and n.id in params:
                        found.setdefault(fn.name, set()).add(n.id)
    return found


SAMPLE_PATHS = """
async def bad(project: str, repo: str):
    return await client.get(f"/{project}/repos/{repo}")
async def good(project: str):
    return await client.get(f"/{path_segment(project, field='project')}/repos")
async def not_a_path(project: str):
    return f"hello {project}"
async def mixed(project: str, repo: str):
    return await client.get(f"/{path_segment(project, field='p')}/{repo}")
"""


def test_sweep_control_the_path_scan_finds_the_raw_arguments() -> None:
    found = raw_path_arguments(SAMPLE_PATHS)
    assert found == {"bad": {"project", "repo"}, "mixed": {"repo"}}


def test_sweep_no_tool_interpolates_a_raw_argument_into_a_path() -> None:
    for path in TOOL_SOURCES:
        assert raw_path_arguments(path.read_text()) == {}, path.name
