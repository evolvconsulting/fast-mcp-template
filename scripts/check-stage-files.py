#!/usr/bin/env python3
"""Refuse a dangerous or incomplete production task definition.

Two uses, one rule set:

* no argument: render every `deploy/stages/*.json` over
  `deploy/taskdef.base.json` with a dummy digest and check each rendered
  definition, plus the stage-file shape;
* `--rendered FILE`: check one already-rendered task definition (what
  the deploy workflow registers).

The gateway-specific names live in `deploy/gateway.json` (account,
region, container, env prefix, ports, required and forbidden settings),
so this script is the same in every gateway.

REFUSED (a planted value for each is in
`tests/test_check_stage_files.py`):

* any environment name starting `TEST_` or `<prefix>TEST_` (back doors);
* any `forbidden_env` name (prefixed) or `forbidden_env_exact` name, set
  to ANYTHING: the unauthenticated escape hatch, a LocalStack endpoint,
  static AWS keys;
* `LOG_LEVEL=DEBUG` (third-party bodies reach the log);
* a secret-shaped name under `environment` (it belongs under `secrets`
  with an ARN);
* a `secrets` entry whose `valueFrom` is not a Secrets Manager ARN in
the
  configured account and region.

REQUIRED (else the boot control it feeds is inert at its code default):

* every `required_env` (prefixed) and `required_env_exact` value;
* every `required_secrets` name (prefixed) under `secrets`;
* `stopTimeout` of at least the graceful-shutdown setting (default 30)
  plus 5, at most 120;
* the configured port mappings, both roles, `runtimePlatform` ARM64 and
a
  valid Fargate cpu/memory pair, FARGATE and awsvpc, ECS exec off.

Exit codes: 0 clean, 1 refused, 2 the check could not run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# Valid Fargate cpu -> memory (MiB) pairs.
_FARGATE = {
    "256": {"512", "1024", "2048"},
    "512": {str(m) for m in range(1024, 4097, 1024)},
    "1024": {str(m) for m in range(2048, 8193, 1024)},
    "2048": {str(m) for m in range(4096, 16385, 1024)},
    "4096": {str(m) for m in range(8192, 30721, 1024)},
}
STAGE_KEYS = {
    "stage",
    "note",
    "rollback_revision",
    "load_balancers",
    "environment",
    "secrets",
}
_SECRET_SHAPED = re.compile(r"(SECRET|PASSWORD|TOKEN)|(_KEY|_PAT)$|REDIS_URL$")


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Read `deploy/gateway.json`."""
    cfg: dict[str, Any] = json.loads(
        (path or ROOT / "deploy" / "gateway.json").read_text()
    )
    return cfg


def _int_or_none(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


def check_rendered(
    task_def: dict[str, Any],
    *,
    cfg: dict[str, Any] | None = None,
    require_digest: bool = False,
) -> list[str]:
    """Return every refusal for one rendered task definition."""
    cfg = cfg or load_config()
    prefix: str = cfg["env_prefix"]
    account, region = cfg["account"], cfg["region"]
    arn = re.compile(
        rf"^arn:aws:secretsmanager:{region}:{account}:secret:[A-Za-z0-9/_+=.@-]+$"
    )
    forbidden = {prefix + n for n in cfg["forbidden_env"]} | set(
        cfg["forbidden_env_exact"]
    )
    exempt = {prefix + n for n in cfg.get("not_secret_shaped", [])}

    problems: list[str] = []
    containers = [
        c
        for c in task_def.get("containerDefinitions") or []
        if c.get("name") == cfg["container"]
    ]
    if len(containers) != 1:
        return [
            f"the task definition needs exactly one container named {cfg['container']}"
        ]
    container = containers[0]
    env = {e["name"]: e.get("value", "") for e in container.get("environment") or []}
    secrets = {
        s["name"]: s.get("valueFrom", "") for s in container.get("secrets") or []
    }

    for name in sorted(env):
        upper = name.upper()
        if upper.startswith(("TEST_", prefix.upper() + "TEST_")):
            problems.append(
                f"environment {name}: TEST_* variables never reach production"
            )
        if name in forbidden:
            problems.append(f"environment {name}: refused in a production stage file")
        if name not in exempt and _SECRET_SHAPED.search(name):
            problems.append(
                f"environment {name}: a secret-shaped name belongs under "
                "`secrets` with an ARN"
            )
    for name in sorted(secrets):
        if (
            name.upper().startswith(("TEST_", prefix.upper() + "TEST_"))
            or name in forbidden
        ):
            problems.append(f"secrets {name}: refused in a production stage file")
        if not arn.match(str(secrets[name])):
            problems.append(
                f"secrets {name}: valueFrom is not a Secrets Manager ARN "
                f"in {account}/{region}"
            )
    if env.get("LOG_LEVEL", "").upper() == "DEBUG":
        problems.append(
            "environment LOG_LEVEL=DEBUG: third-party request bodies "
            "would reach the log"
        )
    required = {prefix + k: v for k, v in cfg["required_env"].items()} | dict(
        cfg["required_env_exact"]
    )
    for name, want in required.items():
        if env.get(name) != want:
            problems.append(
                f"environment {name} must be {want!r} (got {env.get(name)!r})"
            )
    for name in cfg["required_secrets"]:
        if prefix + name not in secrets:
            problems.append(f"secrets {prefix + name} is required in every stage")

    ports = {int(m["containerPort"]) for m in container.get("portMappings") or []}
    if ports != set(cfg["ports"]):
        problems.append(
            f"portMappings must be exactly {sorted(cfg['ports'])} (got {sorted(ports)})"
        )
    for role in ("executionRoleArn", "taskRoleArn"):
        if not task_def.get(role):
            problems.append(f"{role} is required (two roles from stage 0)")
    if (task_def.get("runtimePlatform") or {}).get("cpuArchitecture") != "ARM64":
        problems.append("runtimePlatform.cpuArchitecture must be ARM64")
    if str(task_def.get("memory")) not in _FARGATE.get(str(task_def.get("cpu")), set()):
        problems.append(
            f"cpu {task_def.get('cpu')} and memory {task_def.get('memory')} "
            "is not a valid Fargate pair"
        )
    if (
        task_def.get("requiresCompatibilities") != ["FARGATE"]
        or task_def.get("networkMode") != "awsvpc"
    ):
        problems.append(
            "requiresCompatibilities must be [FARGATE] and networkMode awsvpc"
        )
    if (container.get("linuxParameters") or {}).get(
        "initProcessEnabled"
    ) or container.get("privileged"):
        problems.append(
            "linuxParameters.initProcessEnabled and privileged are "
            "refused (ECS exec stays off)"
        )
    # ECS sends SIGKILL `stopTimeout` seconds after SIGTERM; the process
    # uses the
    # graceful-shutdown setting (default 30) as the ceiling for the
    # WHOLE stop.
    graceful = _int_or_none(env.get(prefix + "GRACEFUL_SHUTDOWN_TIMEOUT", "30"))
    stop = container.get("stopTimeout")
    if graceful is None:
        problems.append(
            f"environment {prefix}GRACEFUL_SHUTDOWN_TIMEOUT must be an integer"
        )
    elif (
        not isinstance(stop, int)
        or isinstance(stop, bool)
        or not graceful + 5 <= stop <= 120
    ):
        problems.append(
            f"stopTimeout must be an integer from the graceful shutdown "
            f"+ 5 ({graceful + 5}) "
            f"to 120, the Fargate maximum (got {stop!r})"
        )
    if require_digest and not re.search(
        r"@sha256:[0-9a-f]{64}$", str(container.get("image"))
    ):
        problems.append("the rendered image must be pinned by digest")
    return problems


def check_stage_file(stage: dict[str, Any], expected_name: str) -> list[str]:
    """Return the refusals for a stage file's shape."""
    problems: list[str] = []
    extra = set(stage) - STAGE_KEYS
    if extra:
        problems.append(f"unknown top-level keys {sorted(extra)}")
    if stage.get("stage") != expected_name:
        problems.append(
            f"stage field {stage.get('stage')!r} does not match the file "
            f"name {expected_name!r}"
        )
    revision = stage.get("rollback_revision")
    if revision is not None and (
        not isinstance(revision, int) or isinstance(revision, bool) or revision < 1
    ):
        problems.append("rollback_revision must be a positive integer or null")
    return problems


def render_for_check(
    base: dict[str, Any], stage: dict[str, Any], cfg: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Render a stage over the base with a dummy digest."""
    cfg = cfg or load_config()
    rendered: dict[str, Any] = json.loads(json.dumps(base))
    container = next(
        c for c in rendered["containerDefinitions"] if c["name"] == cfg["container"]
    )
    registry = f"{cfg['account']}.dkr.ecr.{cfg['region']}.amazonaws.com"
    container["image"] = f"{registry}/{cfg['ecr_repository']}@sha256:{'0' * 64}"
    container["environment"] = [
        {"name": k, "value": v} for k, v in sorted(stage["environment"].items())
    ]
    container["secrets"] = [
        {"name": k, "valueFrom": v} for k, v in sorted(stage["secrets"].items())
    ]
    return rendered


def main(argv: list[str] | None = None) -> int:
    """Check one rendered file, or every committed stage file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rendered", type=Path, help="check one rendered task definition"
    )
    args = parser.parse_args(argv)
    failed = False
    try:
        cfg = load_config()
        if args.rendered:
            targets = [
                (
                    args.rendered.name,
                    check_rendered(
                        json.loads(args.rendered.read_text()),
                        cfg=cfg,
                        require_digest=True,
                    ),
                )
            ]
        else:
            base = json.loads((ROOT / "deploy" / "taskdef.base.json").read_text())
            files = sorted((ROOT / "deploy" / "stages").glob("*.json"))
            if not files:
                print(
                    "ERROR: deploy/stages has no stage files; this check is "
                    "guarding nothing.",
                    file=sys.stderr,
                )
                return 2
            targets = []
            for path in files:
                stage = json.loads(path.read_text())
                targets.append(
                    (
                        path.name,
                        check_stage_file(stage, path.stem)
                        + check_rendered(render_for_check(base, stage, cfg), cfg=cfg),
                    )
                )
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        print(f"ERROR: the check could not run: {exc!r}", file=sys.stderr)
        return 2
    for name, problems in targets:
        for problem in problems:
            print(f"REFUSED {name}: {problem}")
            failed = True
        if not problems:
            print(f"OK {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
