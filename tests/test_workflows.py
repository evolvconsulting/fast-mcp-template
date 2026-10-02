"""Tests for the CI workflows folded in from fast-mcp-ado (EC-639).

They read the YAML and, for the PR-title gate, RUN its real bash step,
because a regex copied into a test would pass while the workflow rots.
"""

from __future__ import annotations

import os
import re
import subprocess
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
