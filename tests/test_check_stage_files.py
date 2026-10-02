"""`scripts/check-stage-files.py` refuses a dangerous or incomplete task definition.

Every refusal has a planted value; the committed stage files are the
positive control (they must be clean), so a checker that refuses nothing,
or everything, fails here.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load() -> Any:
    path = ROOT / "scripts" / "check-stage-files.py"
    spec = importlib.util.spec_from_file_location("script_check_stage_files", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["script_check_stage_files"] = module
    spec.loader.exec_module(module)
    return module


csf = _load()
CFG = csf.load_config()
P = CFG["env_prefix"]
STAGES = sorted((ROOT / "deploy" / "stages").glob("*.json"))


def rendered(stage_file: Path) -> dict[str, Any]:
    base = json.loads((ROOT / "deploy" / "taskdef.base.json").read_text())
    return dict(csf.render_for_check(base, json.loads(stage_file.read_text())))


def with_env(task_def: dict[str, Any], name: str, value: str) -> dict[str, Any]:
    planted = copy.deepcopy(task_def)
    container = planted["containerDefinitions"][0]
    container["environment"] = [
        e for e in container["environment"] if e["name"] != name
    ]
    container["environment"].append({"name": name, "value": value})
    return planted


def test_the_committed_stage_files_are_clean() -> None:
    assert [p.stem for p in STAGES] == ["0-legacy", "1-dual", "3-platform"]
    for path in STAGES:
        assert csf.check_rendered(rendered(path)) == [], path.name
        assert csf.check_stage_file(json.loads(path.read_text()), path.stem) == [], (
            path.name
        )
    assert csf.main([]) == 0


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TEST_ANYTHING", "1"),
        (f"{P}TEST_EMIT_CANARY_SECRET_LOG", "true"),
        ("test_lowercase_probe", "1"),
        (f"{P}DANGEROUSLY_DISABLE_AUTH", "false"),  # set to ANYTHING, including false
        (f"{P}DANGEROUSLY_DISABLE_AUTH", "true"),
        ("LOG_LEVEL", "DEBUG"),
        ("LOG_LEVEL", "debug"),
        ("AWS_ENDPOINT_URL", "http://localstack:4566"),
        ("AWS_ACCESS_KEY_ID", "AKIAXXXXXXXXXXXXXXXX"),
        ("AWS_SECRET_ACCESS_KEY", "x"),
        (f"{P}API_KEY", "plaintext"),  # a secret-shaped name under environment
        (f"{P}INTERNAL_AUTH_SECRET", "plaintext"),
        (f"{P}REDIS_URL", "redis://plaintext"),
    ],
)
def test_stage_files_refuse_dangerous_settings(name: str, value: str) -> None:
    for path in STAGES:
        problems = csf.check_rendered(with_env(rendered(path), name, value))
        assert problems, f"{path.name}: {name}={value} was not refused"
        assert any(name.lower() in p.lower() for p in problems), problems


def test_a_server_key_is_not_mistaken_for_a_secret() -> None:
    # `_KEY` is a secret shape, but the server key names the gateway.
    for path in STAGES:
        assert f"{P}SERVER_KEY" in json.loads(path.read_text())["environment"]
        assert csf.check_rendered(rendered(path)) == []


@pytest.mark.parametrize(
    ("name", "wrong"),
    [
        (f"{P}ENVIRONMENT", "local"),
        (f"{P}ENVIRONMENT", "staging"),
        ("AWS_DEFAULT_REGION", "us-east-1"),
    ],
)
def test_stage_files_set_the_production_switches(name: str, wrong: str) -> None:
    for path in STAGES:
        assert csf.check_rendered(with_env(rendered(path), name, wrong)), (
            f"{name}={wrong}"
        )
        missing = rendered(path)
        missing["containerDefinitions"][0]["environment"] = [
            e
            for e in missing["containerDefinitions"][0]["environment"]
            if e["name"] != name
        ]
        assert csf.check_rendered(missing), (
            f"a stage file without {name} was not refused"
        )


@pytest.mark.parametrize("secret", [f"{P}REDIS_URL", f"{P}INTERNAL_CA_CERT"])
def test_required_secrets_must_be_present_and_every_secret_an_arn(secret: str) -> None:
    for path in STAGES:
        base = rendered(path)
        missing = copy.deepcopy(base)
        secrets = missing["containerDefinitions"][0]["secrets"]
        missing["containerDefinitions"][0]["secrets"] = [
            s for s in secrets if s["name"] != secret
        ]
        assert any(secret in p for p in csf.check_rendered(missing))
        bad = copy.deepcopy(base)
        bad["containerDefinitions"][0]["secrets"][0]["valueFrom"] = "plaintext-secret"
        assert any("Secrets Manager ARN" in p for p in csf.check_rendered(bad))


def test_a_secret_arn_in_another_account_or_region_is_refused() -> None:
    base = rendered(STAGES[0])
    first = base["containerDefinitions"][0]["secrets"][0]
    for old, new in ((CFG["account"], "111111111111"), (CFG["region"], "eu-west-1")):
        planted = copy.deepcopy(base)
        planted["containerDefinitions"][0]["secrets"][0] = {
            **first,
            "valueFrom": first["valueFrom"].replace(old, new),
        }
        assert any("Secrets Manager ARN" in p for p in csf.check_rendered(planted))


@pytest.mark.parametrize("stop", [None, 10, 34, 121, "40", True])
def test_stop_timeout_must_cover_the_graceful_shutdown_and_fit_fargate(
    stop: Any,
) -> None:
    planted = rendered(STAGES[0])
    planted["containerDefinitions"][0]["stopTimeout"] = stop
    assert any("stopTimeout" in p for p in csf.check_rendered(planted))
    for ok in (35, 120):
        planted["containerDefinitions"][0]["stopTimeout"] = ok
        assert csf.check_rendered(planted) == []


def test_a_longer_graceful_shutdown_raises_the_floor() -> None:
    planted = with_env(rendered(STAGES[0]), f"{P}GRACEFUL_SHUTDOWN_TIMEOUT", "60")
    assert any("stopTimeout" in p for p in csf.check_rendered(planted))  # 35 < 65
    planted["containerDefinitions"][0]["stopTimeout"] = 65
    assert csf.check_rendered(planted) == []
    bad = with_env(rendered(STAGES[0]), f"{P}GRACEFUL_SHUTDOWN_TIMEOUT", "soon")
    assert any("must be an integer" in p for p in csf.check_rendered(bad))


def test_structure_refusals() -> None:
    base = rendered(STAGES[0])

    def mutate(fn: Any) -> list[str]:
        planted = copy.deepcopy(base)
        fn(planted)
        problems: list[str] = csf.check_rendered(planted)
        return problems

    def c(t: dict[str, Any]) -> dict[str, Any]:
        container: dict[str, Any] = t["containerDefinitions"][0]
        return container

    assert any(
        "portMappings" in p for p in mutate(lambda t: c(t).update(portMappings=[]))
    )
    assert any(
        "executionRoleArn" in p for p in mutate(lambda t: t.pop("executionRoleArn"))
    )
    assert any("taskRoleArn" in p for p in mutate(lambda t: t.pop("taskRoleArn")))
    assert any(
        "ARM64" in p
        for p in mutate(lambda t: t["runtimePlatform"].update(cpuArchitecture="X86_64"))
    )
    assert any(
        "Fargate pair" in p
        for p in mutate(lambda t: t.update(cpu="256", memory="8192"))
    )
    assert any("awsvpc" in p for p in mutate(lambda t: t.update(networkMode="bridge")))
    assert any(
        "ECS exec" in p
        for p in mutate(
            lambda t: c(t).update(linuxParameters={"initProcessEnabled": True})
        )
    )
    assert any("ECS exec" in p for p in mutate(lambda t: c(t).update(privileged=True)))
    assert any(
        "exactly one container" in p
        for p in mutate(lambda t: c(t).update(name="other"))
    )


def test_the_rendered_image_must_be_pinned_by_digest() -> None:
    planted = rendered(STAGES[0])
    assert csf.check_rendered(planted, require_digest=True) == []
    planted["containerDefinitions"][0]["image"] = "repo/app:latest"
    assert any("digest" in p for p in csf.check_rendered(planted, require_digest=True))
    assert csf.check_rendered(planted) == []  # only the rendered check demands it


def test_stage_file_shape() -> None:
    good = json.loads(STAGES[0].read_text())
    assert csf.check_stage_file(good, "0-legacy") == []
    assert any("does not match" in p for p in csf.check_stage_file(good, "9-other"))
    assert any(
        "unknown top-level" in p
        for p in csf.check_stage_file({**good, "extra": 1}, "0-legacy")
    )
    for bad in (0, -1, "2", True):
        assert any(
            "rollback_revision" in p
            for p in csf.check_stage_file(
                {**good, "rollback_revision": bad}, "0-legacy"
            )
        )
    assert csf.check_stage_file({**good, "rollback_revision": 7}, "0-legacy") == []


def test_main_checks_a_rendered_file_and_names_the_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = tmp_path / "rendered.json"
    good.write_text(json.dumps(rendered(STAGES[0])))
    assert csf.main(["--rendered", str(good)]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            with_env(rendered(STAGES[0]), f"{P}DANGEROUSLY_DISABLE_AUTH", "true")
        )
    )
    assert csf.main(["--rendered", str(bad)]) == 1
    assert "REFUSED bad.json" in capsys.readouterr().out


def test_main_exits_2_when_it_cannot_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # no stage files: a check that guards nothing must say so, not pass
    shutil.copytree(ROOT / "deploy", tmp_path / "deploy")
    for stage in (tmp_path / "deploy" / "stages").glob("*.json"):
        stage.unlink()
    monkeypatch.setattr(csf, "ROOT", tmp_path)
    assert csf.main([]) == 2
    assert "guarding nothing" in capsys.readouterr().err
    # an unreadable rendered file
    assert csf.main(["--rendered", str(tmp_path / "missing.json")]) == 2
