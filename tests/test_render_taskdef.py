"""`scripts/render-taskdef.py`: validate dispatch inputs, render a pinned task definition."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
DIGEST = "sha256:" + "ab" * 32
SHA = "0123456789abcdef0123456789abcdef01234567"


def _load() -> Any:
    path = ROOT / "scripts" / "render-taskdef.py"
    spec = importlib.util.spec_from_file_location("script_render_taskdef", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["script_render_taskdef"] = module
    spec.loader.exec_module(module)
    return module


rt = _load()


def test_the_stages_the_script_knows_are_the_committed_ones() -> None:
    assert rt.stages() == ["0-legacy", "1-dual", "3-platform"]


@pytest.mark.parametrize(
    ("stage", "sha", "rollback", "ok"),
    [
        ("0-legacy", SHA, "", True),
        ("3-platform", SHA, "", True),
        ("", "", "7", True),  # a rollback needs no stage and no image
        ("0-legacy", SHA.upper(), "", False),  # lower-case hex only
        ("0-legacy", SHA[:-1], "", False),
        ("0-legacy", "", "", False),  # a deploy needs an image
        ("", SHA, "", False),  # and a stage
        ("9-nope", SHA, "", False),  # unknown stage
        ("../../etc/passwd", SHA, "", False),  # never a path
        ("0-legacy", SHA + "\n", "", False),
        ("", "", "0", False),
        ("", "", "-3", False),
        ("", "", "1; rm -rf /", False),
        ("", SHA, "7", False),  # a rollback runs ONLY the rollback path
    ],
)
def test_input_validation_matrix(stage: str, sha: str, rollback: str, ok: bool) -> None:
    assert (rt.validate_inputs(stage, sha, rollback) == []) is ok


def test_render_pins_the_image_by_digest_and_passes_the_stage_checks() -> None:
    for stage in rt.stages():
        rendered = rt.render(stage, DIGEST)
        image = rendered["containerDefinitions"][0]["image"]
        assert image.endswith(f"@{DIGEST}") and ":REPLACED" not in image


@pytest.mark.parametrize(
    "digest", ["latest", "sha256:abc", "sha256:" + "G" * 64, DIGEST + "x", ""]
)
def test_render_refuses_anything_but_a_full_digest(digest: str) -> None:
    with pytest.raises(ValueError, match="digest"):
        rt.render("0-legacy", digest)


def test_render_refuses_a_stage_the_checker_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a copy of the deploy inputs and the checker, with one planted back door
    shutil.copytree(ROOT / "deploy", tmp_path / "deploy")
    shutil.copytree(ROOT / "scripts", tmp_path / "scripts")
    stage_file = tmp_path / "deploy" / "stages" / "0-legacy.json"
    stage = json.loads(stage_file.read_text())
    stage["environment"]["MCP_TEMPLATE_DANGEROUSLY_DISABLE_AUTH"] = "true"
    stage_file.write_text(json.dumps(stage))
    monkeypatch.setattr(rt, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="DANGEROUSLY_DISABLE_AUTH"):
        rt.render("0-legacy", DIGEST)
    # the committed stage still renders: the refusal is the planted value
    monkeypatch.setattr(rt, "ROOT", ROOT)
    assert rt.render("0-legacy", DIGEST)


def test_main_validate_reads_the_environment_and_names_the_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("INPUT_STAGE", "0-legacy")
    monkeypatch.setenv("INPUT_IMAGE_SHA", SHA)
    monkeypatch.setenv("INPUT_ROLLBACK_TO_REVISION", "")
    assert rt.main(["validate"]) == 0
    monkeypatch.setenv("INPUT_IMAGE_SHA", "not-a-sha")
    assert rt.main(["validate"]) == 1
    assert "40-hex" in capsys.readouterr().out


def test_main_render_writes_the_file_and_refuses_a_bad_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("INPUT_STAGE", "1-dual")
    out = tmp_path / "rendered.json"
    assert rt.main(["render", "--digest", DIGEST, "--out", str(out)]) == 0
    assert json.loads(out.read_text())["family"] == "fast-mcp-template"
    bad = tmp_path / "bad.json"
    assert rt.main(["render", "--digest", "latest", "--out", str(bad)]) == 1
    assert not bad.exists()  # nothing written for a refused render
    assert "REFUSED" in capsys.readouterr().out


def test_main_exits_2_for_a_stage_with_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INPUT_STAGE", "7-missing")
    assert (
        rt.main(["render", "--digest", DIGEST, "--out", str(tmp_path / "x.json")]) == 2
    )
