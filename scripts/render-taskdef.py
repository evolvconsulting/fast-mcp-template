#!/usr/bin/env python3
"""Validate deploy inputs and render one stage into a task definition.

Used by `.github/workflows/deploy.yml`, never by hand against
production:

    render-taskdef.py validate            (inputs from INPUT_* env vars)
    render-taskdef.py render --digest sha256:<64 hex> --out FILE

`validate` refuses an unknown stage, a malformed image SHA, a rollback
combined with anything else, and a deploy without an image. `render`
writes `deploy/taskdef.base.json` + `deploy/stages/<stage>.json` with
the
image pinned BY DIGEST and then runs the same refusals as
`check-stage-files.py --rendered`, so a definition that would be refused
is never written. Inputs reach this script only through the environment,
never through a shell-interpolated workflow expression.

Exit codes: 0 ok, 1 refused, 2 the script could not run.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
# `fullmatch`, never `$`: `$` accepts a trailing newline.
_SHA = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REVISION = re.compile(r"[1-9][0-9]{0,8}")
_STAGE = re.compile(r"[0-9]+-[a-z0-9-]+")


def _checker() -> Any:
    path = ROOT / "scripts" / "check-stage-files.py"
    spec = importlib.util.spec_from_file_location("check_stage_files", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stages() -> list[str]:
    """Return the committed stage names."""
    return sorted(p.stem for p in (ROOT / "deploy" / "stages").glob("*.json"))


def validate_inputs(stage: str, image_sha: str, rollback_to: str) -> list[str]:
    """Return every refusal for one dispatch's inputs."""
    problems: list[str] = []
    if rollback_to:
        if not _REVISION.fullmatch(rollback_to):
            problems.append("rollback_to_revision must be a positive integer")
        if image_sha:
            problems.append(
                "rollback_to_revision runs ONLY the rollback path: "
                "leave image_sha empty"
            )
        return problems
    if not _STAGE.fullmatch(stage) or stage not in stages():
        problems.append(f"stage must be one of {stages()}")
    if not _SHA.fullmatch(image_sha):
        problems.append("image_sha must be a full 40-hex commit SHA")
    return problems


def render(stage_name: str, digest: str) -> dict[str, Any]:
    """Return the task definition for a stage, pinned to `digest`."""
    if not _DIGEST.fullmatch(digest):
        raise ValueError("digest must be sha256:<64 hex>")
    checker = _checker()
    cfg = checker.load_config()
    base = json.loads((ROOT / "deploy" / "taskdef.base.json").read_text())
    stage_path = ROOT / "deploy" / "stages" / f"{stage_name}.json"
    stage = json.loads(stage_path.read_text())
    rendered: dict[str, Any] = checker.render_for_check(base, stage, cfg)
    container = next(
        c for c in rendered["containerDefinitions"] if c["name"] == cfg["container"]
    )
    registry = f"{cfg['account']}.dkr.ecr.{cfg['region']}.amazonaws.com"
    container["image"] = f"{registry}/{cfg['ecr_repository']}@{digest}"
    problems = checker.check_stage_file(stage, stage_name) + checker.check_rendered(
        rendered, cfg=cfg, require_digest=True
    )
    if problems:
        raise ValueError("; ".join(problems))
    return rendered


def main(argv: list[str] | None = None) -> int:
    """Run `validate` or `render`."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    rend = sub.add_parser("render")
    rend.add_argument("--digest", required=True)
    rend.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    stage = os.environ.get("INPUT_STAGE", "")
    try:
        if args.command == "validate":
            problems = validate_inputs(
                stage,
                os.environ.get("INPUT_IMAGE_SHA", ""),
                os.environ.get("INPUT_ROLLBACK_TO_REVISION", ""),
            )
            for problem in problems:
                print(f"REFUSED: {problem}")
            return 1 if problems else 0
        args.out.write_text(json.dumps(render(stage, args.digest), indent=2) + "\n")
    except (OSError, KeyError, StopIteration) as exc:
        print(f"ERROR: could not run: {exc!r}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"REFUSED: {exc}")
        return 1
    print(f"rendered {stage} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
