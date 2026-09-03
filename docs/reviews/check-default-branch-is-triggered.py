#!/usr/bin/env python3
"""The default branch must be in the workflow's push trigger.

    python3 docs/reviews/check-default-branch-is-triggered.py

**WHY THIS EXISTS.** `on: push: branches:` is static YAML. GitHub
evaluates no expression at that key, so it cannot say
`github.event.repository.default_branch` the way every other branch
condition in `ci.yml` now does. It has to be a literal list, and a
literal list is a claim about a repository that nobody rechecks.

**AND THE FAILURE IS SILENT, WHICH IS WHY A COMMENT WAS NOT ENOUGH.**
Applying this template to a real MCP server on 2026-09-03 - a repository
whose default branch is `dev` against a workflow naming `main` - the
Gate tier did not run on a push to the trunk, and CodeQL and actionlint
did not run at all. Nothing went red. The jobs were simply ABSENT, and
an absent job renders GREY. Switched-off and broken must not render
identically; on the project this machinery came from that shape hid 119
consecutive failures.

So the literal list is asserted against the repository it is actually
in. A missing default branch is a RED, naming the one line to edit.

**THE REVERSE DIRECTION IS CHECKED TOO.** A push trigger that lists the
right branch buys nothing if the Merge-tier jobs still compare
`github.ref` to a hardcoded `refs/heads/main`. So every `if:` in the
workflow is scanned for a hardcoded `refs/heads/<name>`, and one is a
finding. Both halves of the defect were the same edit, so both halves
have to be held.

**HOW THE DEFAULT BRANCH IS DETERMINED, in order, and it REFUSES rather
than guessing.**

1. `$DEFAULT_BRANCH` - what the workflow step passes from
   `github.event.repository.default_branch`. Authoritative in CI.
2. `git symbolic-ref --short refs/remotes/origin/HEAD` - what a local
   clone records. Authoritative locally, when a remote exists.
3. Nothing. Then it is a BROKEN INSTRUMENT (exit 3), never a pass. A
   checker that cannot determine its subject and prints a green is the
   defect this whole file exists to stop.

There is deliberately NO fallback to `main`. A default that defaults to
the very literal under test would make this checker green on exactly the
repository it was written for and vacuous everywhere else - which is the
same shape as a gate built to pass its own check.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

#: A hardcoded trunk in a condition. The Merge tier compared
#: `github.ref` to this literal and so never ran on a repo whose
#: trunk is named anything else.
HARDCODED_REF = re.compile(r"refs/heads/(?!\{)([A-Za-z0-9._/-]+)")


def default_branch() -> str:
    """This repository's default branch, or refuse. Never guessed."""
    from_env = os.environ.get("DEFAULT_BRANCH", "").strip()
    if from_env:
        print(f"Default branch, from $DEFAULT_BRANCH: {from_env}")
        return from_env

    done = subprocess.run(
        ["git", "-C", str(ROOT), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    ref = done.stdout.strip()
    if done.returncode == 0 and ref:
        # `origin/dev` -> `dev`. The remote name is whatever `origin` is
        # called here, so split on the FIRST slash rather than assuming.
        name = ref.split("/", 1)[1] if "/" in ref else ref
        print(f"Default branch, from refs/remotes/origin/HEAD: {name}")
        return name

    print("CANNOT DETERMINE THIS REPOSITORY'S DEFAULT BRANCH.")
    print("  $DEFAULT_BRANCH is unset or empty, and")
    print("  git symbolic-ref refs/remotes/origin/HEAD did not resolve")
    print("  (no remote, or the remote HEAD was never fetched - try")
    print("   `git remote set-head origin --auto`).")
    print()
    print("There is NO fallback to 'main' on purpose: a default that")
    print("defaults to the literal under test is green on one repository")
    print("and vacuous on every other.")
    print("This is a BROKEN INSTRUMENT, not a finding. Exit 3.")
    raise SystemExit(3)


def push_branches() -> list[str]:
    """The literal list at `on: push: branches:`, or refuse."""
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # `on` is the YAML 1.1 boolean `True` after a safe_load, which
    # is the commonest way a workflow parser silently reads nothing.
    triggers = loaded.get("on", loaded.get(True))
    if not isinstance(triggers, dict):
        print(f"PARSED NO TRIGGER BLOCK out of {WORKFLOW.name}.")
        print("This is a BROKEN INSTRUMENT, not a finding. Exit 3.")
        raise SystemExit(3)

    push = triggers.get("push")
    if not isinstance(push, dict) or "branches" not in push:
        print("The workflow has NO `on: push: branches:` filter.")
        print("Every branch push then runs Gate, which is not this")
        print("template's shape and doubles the bill on every PR branch.")
        raise SystemExit(1)

    branches = push["branches"]
    if not isinstance(branches, list) or not branches:
        print("`on: push: branches:` parsed as empty. Exit 3.")
        raise SystemExit(3)
    return [str(b) for b in branches]


def hardcoded_conditions() -> list[tuple[str, str]]:
    """Every `if:` naming a literal `refs/heads/<name>`, with it."""
    found: list[tuple[str, str]] = []
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = loaded.get("jobs", {})
    if not isinstance(jobs, dict):
        return found
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        conditions = [job.get("if")]
        for step in job.get("steps", []) or []:
            if isinstance(step, dict):
                conditions.append(step.get("if"))
        for condition in conditions:
            if not isinstance(condition, str):
                continue
            for match in HARDCODED_REF.finditer(condition):
                found.append((str(job_name), match.group(1)))
    return found


def main() -> int:
    if not WORKFLOW.exists():
        print(f"{WORKFLOW} is missing. Exit 3.")
        return 3

    trunk = default_branch()
    branches = push_branches()
    print(f"on.push.branches: {branches}")

    problems = False

    if trunk not in branches:
        problems = True
        print()
        print(f"THIS REPOSITORY'S DEFAULT BRANCH ({trunk!r}) IS NOT IN THE")
        print("WORKFLOW'S PUSH TRIGGER.")
        print()
        print("A push to the trunk therefore runs NO Gate, NO CodeQL and")
        print("NO actionlint - and none of that renders red. The jobs are")
        print("absent, and an absent job is grey.")
        print()
        print(f"FIX: add {trunk!r} to `on: push: branches:` in")
        print("     .github/workflows/ci.yml. That key is static YAML and")
        print("     is the ONE branch name in the file that cannot derive")
        print("     itself; every other condition already does.")

    hardcoded = hardcoded_conditions()
    if hardcoded:
        problems = True
        print()
        print(f"{len(hardcoded)} condition(s) compare github.ref to a HARDCODED ref:")
        for job_name, name in hardcoded:
            print(f"  job {job_name}: refs/heads/{name}")
        print()
        print("A tier gated on a literal trunk name does not run at all on")
        print("a repository whose trunk is named otherwise, and a job that")
        print("does not run renders GREY. Use")
        print("  github.ref == format('refs/heads/{0}',")
        print("                       github.event.repository.default_branch)")

    if problems:
        return 1

    print()
    print(f"The default branch {trunk!r} is in the push trigger, and no")
    print("condition names a trunk literally.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
