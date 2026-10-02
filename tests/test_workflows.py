"""Tests for the CI workflows folded in from fast-mcp-ado (EC-639).

They read the YAML and, for the PR-title gate, RUN its real bash step,
because a regex copied into a test would pass while the workflow rots.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name: str) -> dict[Any, Any]:
    data = yaml.safe_load((WORKFLOWS / name).read_text())
    assert isinstance(data, dict)
    return data


def _run_steps(job: dict[str, Any]) -> list[str]:
    return [s["run"] for s in job["steps"] if "run" in s]


# --- pr-title ---------------------------------------------------------


def _title_ok(title: str, key: str = "EC") -> bool:
    step = next(
        s for s in _load("pr-title.yml")["jobs"]["title"]["steps"] if "run" in s
    )
    env = {**os.environ, "PR_TITLE": title, "TICKET_KEY": key}
    done = subprocess.run(
        ["bash", "-c", step["run"]], env=env, capture_output=True, check=False
    )
    return done.returncode == 0


@pytest.mark.parametrize(
    "title",
    [
        "feat(EC-639): fold the building blocks",
        "fix(EC-1): a",
        "chore(EC-12345): subject with (parens) and: colons",
    ],
)
def test_pr_title_accepts_the_convention(title: str) -> None:
    assert _title_ok(title)


@pytest.mark.parametrize(
    "title",
    [
        "fold the building blocks",
        "feat: no ticket",
        "feat(EC-639):no space",
        "feat(EC-639): ",
        "feature(EC-639): wrong type",
        "feat(ABC-639): wrong key",
        "feat(EC-x): not a number",
        "$(touch /tmp/pwned) feat(EC-1): injected prefix",
    ],
)
def test_pr_title_refuses_everything_else(title: str) -> None:
    assert not _title_ok(title)


def test_pr_title_key_is_one_adopter_edit() -> None:
    assert _title_ok("feat(ABC-639): other project", key="ABC")
    assert not _title_ok("feat(EC-639): other project", key="ABC")


def test_pr_title_reaches_the_shell_only_through_env() -> None:
    text = (WORKFLOWS / "pr-title.yml").read_text()
    for step in _load("pr-title.yml")["jobs"]["title"]["steps"]:
        assert "github.event" not in step.get("run", "")
    assert "PR_TITLE: ${{ github.event.pull_request.title }}" in text


# --- concurrency, per workflow ----------------------------------------


def test_concurrency_is_per_workflow_not_one_rule() -> None:
    assert _load("pr-title.yml")["concurrency"]["cancel-in-progress"] is True
    # a cancelled trunk check is not a failed one
    assert _load("main-only-by-pr.yml")["concurrency"]["cancel-in-progress"] is False
    ci = _load("ci.yml")["concurrency"]["cancel-in-progress"]
    assert "default_branch" in ci  # the trunk is exempt, and derived


# --- main-only-by-pr --------------------------------------------------


def test_main_only_by_pr_derives_the_trunk_from_the_repository() -> None:
    wf = _load("main-only-by-pr.yml")
    job = wf["jobs"]["merged-pr-only"]
    assert "default_branch" in job["if"]
    step = next(s for s in job["steps"] if "run" in s)
    assert step["env"]["TRUNK"] == "${{ github.event.repository.default_branch }}"
    assert 'base.ref == \\"${TRUNK}\\"' in step["run"]
    assert '"main"' not in step["run"]  # no literal trunk name
    assert "set -euo pipefail" in step["run"]


# --- security job and weekly audit -----------------------------------


def _security() -> dict[Any, Any]:
    job: dict[Any, Any] = _load("ci.yml")["jobs"]["security"]
    return job


def test_security_scans_full_history_with_unverified_findings() -> None:
    checkout = _security()["steps"][0]
    assert checkout["with"]["fetch-depth"] == 0
    scan = next(r for r in _run_steps(_security()) if "trufflehog" in r)
    assert "--fail" in scan
    # `--only-verified` leaves a planted fake key green (measured).
    assert "--only-verified" not in scan
    assert re.search(r"trufflehog:3\.88\.0@sha256:[0-9a-f]{64}", scan)


def test_security_audits_strictly_through_the_advisory_table() -> None:
    audit = next(r for r in _run_steps(_security()) if "pip-audit" in r)
    assert "scripts/check_advisories.py" in audit
    assert "--strict" in audit
    assert "--with pip-audit" not in audit  # never unpinned, outside the lock
    install = next(r for r in _run_steps(_security()) if "uv sync" in r)
    assert "--no-install-project" in install


def test_security_emits_both_sbom_formats() -> None:
    formats = [
        s["with"]["format"]
        for s in _security()["steps"]
        if "sbom-action" in s.get("uses", "")
    ]
    assert sorted(formats) == ["cyclonedx-json", "spdx-json"]


def test_weekly_lock_audit_is_scheduled_only_and_leaves_the_lock_alone() -> None:
    job = _load("ci.yml")["jobs"]["weekly-lock-audit"]
    assert job["if"] == "github.event_name == 'schedule'"
    assert "schedule" in _load("ci.yml")[True]  # PyYAML reads `on` as True
    script = "\n".join(_run_steps(job))
    assert "git archive HEAD" in script  # upgrade happens in a scratch copy
    assert "pip-audit" in script


def test_actions_in_the_security_jobs_are_pinned_by_sha() -> None:
    for name in ("security", "weekly-lock-audit"):
        for step in _load("ci.yml")["jobs"][name]["steps"]:
            if "uses" in step:
                assert re.search(r"@[0-9a-f]{40}$", step["uses"]), step["uses"]


def test_pip_audit_is_a_pinned_dev_dependency() -> None:
    text = (ROOT / "pyproject.toml").read_text()
    assert re.search(r'"pip-audit==\d+\.\d+\.\d+"', text)


# --- build, deploy and the OIDC probe ---------------------------------

SHA_PINNED = re.compile(r"@[0-9a-f]{40}$")


def _steps(workflow: str, job: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = _load(workflow)["jobs"][job]["steps"]
    return steps


def _index(steps: list[dict[str, Any]], needle: str) -> int:
    for i, s in enumerate(steps):
        if needle in (s.get("name", "") + s.get("run", "") + s.get("uses", "")):
            return i
    raise AssertionError(f"no step mentions {needle!r}")


def test_no_workflow_runs_on_pull_request_target_or_writes_with_the_default_token() -> (
    None
):
    for path in sorted(WORKFLOWS.glob("*.yml")):
        wf = yaml.safe_load(path.read_text())
        assert "pull_request_target" not in wf[True], path.name
        top = wf.get("permissions", {})
        assert (
            not any(v == "write" for v in top.values())
            or path.name == "oidc-claims-probe.yml"
        ), path.name


def test_build_pushes_last_after_every_step_that_can_fail() -> None:
    steps = _steps("build-image.yml", "build")
    order = [
        _index(steps, "Build the ARM64 image"),
        _index(steps, "SBOM (CycloneDX)"),
        _index(steps, "SBOM (SPDX)"),
        _index(steps, "Image scan"),
        _index(steps, "Assume the build role"),
        _index(steps, "Refuse when the tag already exists"),
        _index(steps, "Log in to ECR"),
        _index(steps, "Push and print the digest"),
    ]
    assert order == sorted(order), (
        "ECR tags are immutable: nothing may fail after the push"
    )
    assert order[-1] == len(steps) - 1


def test_build_never_cancels_and_only_the_build_job_may_mint_a_token() -> None:
    wf = _load("build-image.yml")
    assert wf["concurrency"]["cancel-in-progress"] is False
    assert wf["jobs"]["build"]["permissions"]["id-token"] == "write"  # noqa: S105
    assert "id-token" not in wf["permissions"]
    assert "default_branch" in wf["jobs"]["build"]["if"]
    scan = next(
        s for s in _steps("build-image.yml", "build") if "trivy" in s.get("uses", "")
    )
    assert scan["with"]["exit-code"] == "1" and "CRITICAL" in scan["with"]["severity"]


def test_deploy_is_dispatch_only_with_no_environment_and_never_cancels() -> None:
    wf = _load("deploy.yml")
    assert list(wf[True]) == ["workflow_dispatch"]
    assert wf["concurrency"]["cancel-in-progress"] is False
    assert "environment" not in wf["jobs"]["deploy"]
    assert "default_branch" in wf["jobs"]["deploy"]["if"]


def test_deploy_inputs_reach_the_shell_only_through_env() -> None:
    for step in _steps("deploy.yml", "deploy"):
        assert "inputs." not in step.get("run", ""), step.get("name")
        assert "github.event" not in step.get("run", ""), step.get("name")
    env = _load("deploy.yml")["jobs"]["deploy"]["env"]
    assert env["INPUT_STAGE"] == "${{ inputs.stage }}"
    assert env["INPUT_IMAGE_SHA"] == "${{ inputs.image_sha }}"


def test_deploy_checks_and_validates_before_it_assumes_the_role() -> None:
    steps = _steps("deploy.yml", "deploy")
    stage_check = _index(steps, "check-stage-files.py")
    validate = _index(steps, "render-taskdef.py validate")
    assume = _index(steps, "Assume the deploy role")
    assert stage_check < assume and validate < assume


def test_deploy_registers_a_rendered_digest_pinned_definition_with_a_circuit_breaker() -> (
    None
):
    deploy = next(
        s for s in _steps("deploy.yml", "deploy") if s.get("name") == "Deploy the stage"
    )["run"]
    assert "render-taskdef.py render --digest" in deploy
    assert "check-stage-files.py --rendered" in deploy
    assert "deploymentCircuitBreaker={enable=true,rollback=true}" in deploy
    assert deploy.index("rollback target") < deploy.index("register-task-definition")
    assert "wait services-stable" in deploy


def test_third_party_actions_in_build_and_deploy_are_pinned_by_sha() -> None:
    for name, job in (("build-image.yml", "build"), ("deploy.yml", "deploy")):
        for step in _steps(name, job):
            if "uses" in step:
                assert SHA_PINNED.search(step["uses"]), (name, step["uses"])


def test_the_probe_binds_itself_and_demands_access_denied_from_both_roles() -> None:
    wf = _load("oidc-claims-probe.yml")
    assert list(wf[True]) == ["workflow_dispatch"]
    steps = wf["jobs"]["probe"]["steps"]
    assert all("uses" not in s for s in steps), "no third-party action in the probe"
    run = steps[0]["run"]
    assert "::add-mask::" in run
    assert "endswith($want)" in run  # the binding proof
    assert "(AccessDenied)" in run and "SUCCEEDED" in run  # the negative proof
    assert "for role in BUILD DEPLOY" in run
    # the token is never printed
    assert 'echo "${token}"' not in run and "echo $token" not in run


# --- action pins (EC-639 L2) -------------------------------------------


def _pins(*paths: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check-action-pins.py"),
            *map(str, paths),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_every_workflow_action_is_sha_pinned() -> None:
    done = _pins(*sorted(WORKFLOWS.glob("*.y*ml")))
    assert done.returncode == 0, done.stdout


def test_ci_runs_the_pin_gate() -> None:
    assert any(
        "check-action-pins.py" in r for r in _run_steps(_load("ci.yml")["jobs"]["gate"])
    )


def test_the_pin_gate_fires_on_a_tag_and_exempts_local_actions(tmp_path: Path) -> None:
    sha = "a" * 40
    ok = tmp_path / "ok.yml"
    ok.write_text(f"steps:\n  - uses: a/b@{sha} # v1\n  - uses: ./local\n")
    assert _pins(ok).returncode == 0
    for bad in ("a/b@v1", "a/b@main", f"a/b@{sha[:39]}", "a/b"):
        f = tmp_path / "bad.yml"
        f.write_text(f"steps:\n  - uses: {bad}\n")
        assert _pins(f).returncode == 1, bad
