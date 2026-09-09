#!/usr/bin/env python3
"""Replay a CI job locally by running the workflow's OWN `run:` steps.

    uv run --frozen python scripts/run-gate-locally.py
    uv run --frozen python scripts/run-gate-locally.py --job X
    uv run --frozen python scripts/run-gate-locally.py --root W
    uv run --frozen python scripts/run-gate-locally.py --list
    uv run --frozen python scripts/run-gate-locally.py --self-test

The first form replays the `gate` job; `--job` picks another; `--root`
replays a worktree; `--list` prints every job with its steps, or
the one named by `--job`;
`--self-test` plants failures and requires detection.

WHY THIS EXISTS. A gate run without CI's flags is a different, weaker
question, and it was measured twice on this family: a bare `pytest`
where CI says `uv run --frozen pytest --cov ...`, and a `python3` where
CI says `uv run --frozen python`, each read as green or as a defect
that CI did not share. The fix that keeps failing is "copy the lines
out of ci.yml"; people copy them once and the copy drifts. So this
tool has NO copy: it parses `.github/workflows/ci.yml` and runs each
`run:` block of the chosen job, in order, with the job's and the
step's `env:` applied, and prints one `STEP <name>: rc=<n>` line per
step so every exit code is read on its own line.

THE SHELL IS THE ONE GITHUB WOULD USE, NOT THE ONE THAT SOUNDS RIGHT.
GitHub's workflow-syntax reference, verbatim: "By default, fail-fast
behavior is enforced using `set -e` for both `sh` and `bash`. When
`shell: bash` is specified, `-o pipefail` is also applied." So a step
with no `shell:` (and no `defaults.run.shell` on its job or workflow)
runs under `bash -e`, WITHOUT pipefail, and `cmd1 | cmd2` passes when
`cmd1` fails; an explicit `shell: bash` runs under
`bash --noprofile --norc -eo pipefail`. The first version of this tool
hardcoded the second form for every step and would have false-failed
any adopter whose steps pipe; its reviewer caught it from the primary
source. Any other shell value is refused.

A THIRD DRIFT, FOUND BY THIS TOOL ON ITS FIRST RUN. The hand-copied
replay this tool replaced ran the default-branch gate WITHOUT its
step `env:`, so the checker fell back to reading git and passed; CI
passes it `DEFAULT_BRANCH` set from
`github.event.repository.default_branch`. Same script, different code
path, same green. GitHub expressions are therefore handled explicitly:
the tool expands the ones it can PROVE locally (today exactly one, the
default branch, read from `refs/remotes/origin/HEAD`) and REFUSES any
other, in `run:` and in `env:` alike. Guessing `main` would replay
that gate against a value nobody measured.

WHAT IT REFUSES, loudly, rather than approximating, each exit 2 with
the step named: an expression it cannot resolve, in `run:` or in
`env:` at any of the three scopes; a step with `if:`, and a JOB with
`if:` (every job here except the gate carries one, and a job replayed
past its own condition is a green nobody asked for); a shell other
than the default or `bash`; a step with `continue-on-error:`, because
honouring it would need the replay to keep going past a red step and
refusing is the honest cheap option; a `working-directory` that does
not exist (the step's own, or `defaults.run.working-directory` at
the job or workflow scope, which is honoured the way `shell:` is); a
job with `container:` or `services:`, because a replay on this host
would substitute its own toolchain for the declared image and start
no service; an unknown job; a job whose `steps:` is empty or null;
and a job that would replay ZERO run steps.
A replay that silently skipped or
softened a step would be a green that tested nothing, which is the
defect this whole repository is built to refuse. `uses:` steps
(checkout, setup-uv) are environment, not checks; they are listed as
not replayed and counted, never skipped silently.

KNOWN GAPS, stated rather than hidden. `timeout-minutes:` is ignored,
which only makes a local replay more patient than CI; it cannot
manufacture a pass. `needs:` and `outputs:` between jobs are not
modelled: one job is replayed at a time, and an expression that reads
another job's output is refused as unresolvable rather than guessed.
A SIGKILL of this process (not Ctrl-C, which `subprocess.run` turns
into a kill of the child) leaves the step's temporary script on disk
and the step's own children running, because nothing can run after
SIGKILL; every other exit path removes the file. YAML scalars that
are not strings reach a step as GitHub renders them: booleans
lowercase, null as empty, other scalars as str() prints them.

WHAT IT IS NOT. It is not a checker and must never be wired into CI:
CI running a replay of itself proves nothing. It is excused in
`docs/reviews/check-checkers-are-wired.py` for that reason, like
`refreeze.sh`. It also does not reproduce the runner's environment
(`CI=true`, the ubuntu image, secrets); a step that depends on those
fails here and says so, which is information.

Exit 0 = every replayed step exited 0. Otherwise the first failing
step's exit code (or the last one with --keep-going). Exit 2 = the
replay itself could not be trusted.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXIT_UNTRUSTED = 2
# GitHub, Linux, no `shell:` anywhere: `bash -e {0}`.
SHELL_DEFAULT = ["bash", "-e"]
# GitHub, explicit `shell: bash`:
# `bash --noprofile --norc -eo pipefail {0}`.
SHELL_BASH = ["bash", "--noprofile", "--norc", "-eo", "pipefail"]
EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")

Resolvers = dict[str, Callable[[], str]]


def default_branch(root: Path) -> str:
    """The default branch as GitHub would report it, from origin/HEAD.

    `git clone` sets `refs/remotes/origin/HEAD`; `git remote set-head
    origin -a` repairs it. Raises rather than guessing when it is
    unset, because the default-branch gate is exactly the check that
    a guessed `main` would render meaningless.
    """
    done = subprocess.run(  # noqa: S603 - argv list, no shell=True
        [
            "git",
            "-C",
            str(root),
            "symbolic-ref",
            "--short",
            "refs/remotes/origin/HEAD",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    name = done.stdout.strip()
    if done.returncode != 0 or not name:
        msg = (
            "refs/remotes/origin/HEAD is unset, so the default branch cannot "
            "be proved; run `git remote set-head origin -a`"
        )
        raise LookupError(msg)
    return name.removeprefix("origin/")


def resolvers_for(root: Path) -> Resolvers:
    """The expressions this tool can prove, and how."""
    return {
        "github.event.repository.default_branch": lambda: default_branch(root),
    }


def unresolvable(value: str, resolvers: Resolvers) -> list[str]:
    """Expressions in `value` that no resolver covers."""
    return [m.group(1) for m in EXPR.finditer(value) if m.group(1) not in resolvers]


def resolve(value: str, resolvers: Resolvers) -> str:
    """Expand every expression in `value`; caller has screened them."""
    return EXPR.sub(lambda m: resolvers[m.group(1)](), value)


def gh_text(value: Any) -> str:
    """A YAML scalar as GitHub renders it into a step's environment.

    PyYAML gives `true` as Python's True, and str(True) is "True";
    a step testing `[ "$FLAG" = "true" ]` would then diverge from
    the runner. Round 3 planted exactly that.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def load_workflow(workflow: Path) -> dict[str, Any]:
    """Parse the workflow file; raise KeyError if it has no jobs."""
    doc: Any = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict):
        msg = f"{workflow} has no jobs mapping"
        raise KeyError(msg)
    return doc


def job_spec(doc: dict[str, Any], job: str) -> dict[str, Any]:
    """Return the job mapping for `job`, or raise KeyError naming it."""
    jobs: dict[str, Any] = doc["jobs"]
    if job not in jobs:
        msg = f"no job {job!r}; jobs: {sorted(jobs)}"
        raise KeyError(msg)
    spec: dict[str, Any] = jobs[job]
    return spec


def declared_shell(
    doc: dict[str, Any], spec: dict[str, Any], step: dict[str, Any]
) -> Any:
    """The `shell:` in force: step, then job, then workflow defaults."""
    if "shell" in step:
        return step["shell"]
    for scope in (spec, doc):
        run_defaults = (scope.get("defaults") or {}).get("run") or {}
        if "shell" in run_defaults:
            return run_defaults["shell"]
    return None


def declared_workdir(
    doc: dict[str, Any], spec: dict[str, Any], step: dict[str, Any]
) -> str:
    """The `working-directory` in force: step, job, then workflow."""
    if "working-directory" in step:
        return str(step["working-directory"])
    for scope in (spec, doc):
        run_defaults = (scope.get("defaults") or {}).get("run") or {}
        if "working-directory" in run_defaults:
            return str(run_defaults["working-directory"])
    return "."


def shell_for(declared: Any) -> list[str] | None:
    """GitHub's invocation for a declared shell; None if unsupported."""
    if declared is None:
        return SHELL_DEFAULT
    if declared == "bash":
        return SHELL_BASH
    return None


def refusals(
    doc: dict[str, Any], spec: dict[str, Any], resolvers: Resolvers, root: Path
) -> list[str]:
    """Why this job cannot be replayed faithfully, one line each."""
    out: list[str] = []
    if "if" in spec:
        out.append("the job has an if: condition")
    for key in ("container", "services"):
        if key in spec:
            out.append(f"the job declares {key}:, which this host cannot honour")
    for scope, block in (("workflow", doc.get("env")), ("job", spec.get("env"))):
        for key, value in (block or {}).items():
            for expr in unresolvable(gh_text(value), resolvers):
                out.append(
                    f"{scope} env {key} carries an unresolvable expression: {expr}"
                )
    run_steps = 0
    for i, step in enumerate(spec.get("steps") or [], start=1):
        name = step.get("name", f"step {i}")
        if "run" not in step:
            continue
        run_steps += 1
        for expr in unresolvable(gh_text(step["run"]), resolvers):
            out.append(f"step {i} ({name}) run: unresolvable expression: {expr}")
        for key, value in (step.get("env") or {}).items():
            for expr in unresolvable(gh_text(value), resolvers):
                out.append(
                    f"step {i} ({name}) env {key} carries an unresolvable "
                    f"expression: {expr}"
                )
        if "if" in step:
            out.append(f"step {i} ({name}) has an if: condition")
        if "continue-on-error" in step:
            out.append(f"step {i} ({name}) sets continue-on-error")
        declared = declared_shell(doc, spec, step)
        if shell_for(declared) is None:
            out.append(f"step {i} ({name}) declares shell {declared!r}, not bash")
        cwd = root / declared_workdir(doc, spec, step)
        if not cwd.is_dir():
            out.append(f"step {i} ({name}) working-directory {cwd} does not exist")
    if run_steps == 0:
        out.append("the job has no run: steps, so a replay would test nothing")
    return out


def run_step(
    shell: list[str], script: str, env: dict[str, str], cwd: Path
) -> tuple[int, str, float]:
    """Run one `run:` block under the shell GitHub would use for it.

    GitHub writes the block to a file and runs `bash -e {0}` on it;
    so does this, rather than `bash -c "<script>"`, so that `$0` and
    `BASH_SOURCE` name a file as they do on a runner.
    """
    start = time.monotonic()
    with tempfile.NamedTemporaryFile(
        "w", suffix=".sh", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(script)
        path = handle.name
    try:
        done = subprocess.run(  # noqa: S603 - argv list, no shell=True
            [*shell, path],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        os.unlink(path)
    return done.returncode, done.stdout + done.stderr, time.monotonic() - start


def replay(
    workflow: Path,
    job: str,
    *,
    root: Path,
    resolvers: Resolvers | None = None,
    keep_going: bool = False,
    tail: int = 60,
    verbose: bool = False,
) -> int:
    """Replay `job` from `workflow`; return the exit code to use."""
    resolvers = resolvers_for(root) if resolvers is None else resolvers
    try:
        doc = load_workflow(workflow)
        spec = job_spec(doc, job)
    except KeyError as exc:
        print(f"REFUSED: {exc}")
        return EXIT_UNTRUSTED
    problems = refusals(doc, spec, resolvers, root)
    if problems:
        print(f"REFUSED to replay job {job!r}:")
        for line in problems:
            print(f"  - {line}")
        return EXIT_UNTRUSTED

    try:
        base_env = dict(os.environ)
        # A GitHub runner carries no VIRTUAL_ENV. When this tool is
        # launched through `uv run`, uv exports one for THIS project,
        # and each `uv run` inside a replayed step then warns that it
        # does not match the target root and ignores it. Measured on
        # a --root replay of another repository. Dropped, so a step
        # sees the environment CI gives it.
        base_env.pop("VIRTUAL_ENV", None)
        # GitHub layers env: workflow, then job, then step, later
        # scopes winning. The workflow scope was silently dropped
        # until review round 2 planted one and watched it vanish.
        for block in (doc.get("env"), spec.get("env")):
            for key, value in (block or {}).items():
                base_env[key] = resolve(gh_text(value), resolvers)
    except LookupError as exc:
        print(f"REFUSED: {exc}")
        return EXIT_UNTRUSTED

    # Steps may append to $GITHUB_OUTPUT; give them a real file, then
    # remove it, so a replay leaves nothing behind.
    fd, output_path = tempfile.mkstemp(suffix=".github-output")
    os.close(fd)
    base_env["GITHUB_OUTPUT"] = output_path
    steps = spec.get("steps") or []
    total = len(steps)
    worst = 0
    replayed = 0
    not_replayed = 0
    try:
        for i, step in enumerate(steps, start=1):
            name = step.get("name", f"step {i}")
            if "run" not in step:
                action = step.get("uses", "?")
                print(f"STEP {i}/{total} {name}: uses {action} (not replayed)")
                not_replayed += 1
                continue
            env = dict(base_env)
            try:
                for key, value in (step.get("env") or {}).items():
                    env[key] = resolve(gh_text(value), resolvers)
                script = resolve(gh_text(step["run"]), resolvers)
            except LookupError as exc:
                print(f"REFUSED at step {i} ({name}): {exc}")
                return EXIT_UNTRUSTED
            shell = shell_for(declared_shell(doc, spec, step))
            if shell is None:  # screened by refusals(); kept for the type
                print(f"REFUSED at step {i} ({name}): unsupported shell")
                return EXIT_UNTRUSTED
            cwd = root / declared_workdir(doc, spec, step)
            rc, output, seconds = run_step(shell, script, env, cwd)
            replayed += 1
            print(f"STEP {i}/{total} {name}: rc={rc} ({seconds:.1f}s)")
            if verbose or rc != 0:
                lines = output.rstrip("\n").splitlines()
                shown = lines if verbose else lines[-tail:]
                for line in shown:
                    print(f"    {line}")
            if rc != 0:
                worst = rc
                if not keep_going:
                    break
    finally:
        Path(output_path).unlink(missing_ok=True)
    print(
        f"REPLAY {job}: {replayed} run-steps replayed, "
        f"{not_replayed} uses-steps not replayed, exit {worst}"
    )
    return worst


def self_test() -> int:
    """Plant each refusal and each shell rule; require detection."""
    fake: Resolvers = {"github.event.repository.default_branch": lambda: "main"}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "sub").mkdir()
        wf = root / "ci.yml"

        def write(text: str) -> None:
            wf.write_text(text, encoding="utf-8")

        head = "on: push\njobs:\n  gate:\n    runs-on: x\n    steps:\n"
        cases: list[tuple[str, str, int]] = [
            (
                "second step exits 3 and is reported",
                head + "      - name: ok\n        run: echo fine\n"
                "      - name: bad\n        run: echo planted; exit 3\n"
                "      - name: never\n        run: echo unreachable\n",
                3,
            ),
            (
                "job env reaches the step",
                "on: push\njobs:\n  gate:\n    runs-on: x\n    env:\n"
                "      PLANT: seed\n    steps:\n      - name: env\n"
                '        run: test "$PLANT" = seed\n',
                0,
            ),
            (
                "a block scalar run with env and two lines",
                head + "      - name: block\n        env:\n          A: one\n"
                '        run: |\n          test "$A" = one\n          echo second\n',
                0,
            ),
            (
                "a known expression in env is resolved",
                head + "      - name: env\n        env:\n"
                "          B: ${{ github.event.repository.default_branch }}\n"
                '        run: test "$B" = main\n',
                0,
            ),
            (
                "a known expression in run is resolved",
                head + "      - name: run\n"
                '        run: test "${{ github.event.repository.default_branch }}"'
                " = main\n",
                0,
            ),
            (
                "an unknown expression in env is refused",
                head + "      - name: env\n        env:\n"
                "          S: ${{ github.sha }}\n        run: echo $S\n",
                EXIT_UNTRUSTED,
            ),
            (
                "an unknown expression in run is refused",
                head + "      - name: expr\n        run: echo ${{ github.sha }}\n",
                EXIT_UNTRUSTED,
            ),
            (
                "if: condition is refused",
                head + "      - name: cond\n        if: always()\n"
                "        run: echo x\n",
                EXIT_UNTRUSTED,
            ),
            (
                "continue-on-error is refused",
                head + "      - name: soft\n        continue-on-error: true\n"
                "        run: exit 1\n",
                EXIT_UNTRUSTED,
            ),
            (
                "a shell other than bash is refused",
                head + "      - name: sh\n        shell: sh\n        run: echo x\n",
                EXIT_UNTRUSTED,
            ),
            (
                "a workflow-level default shell other than bash is refused",
                "on: push\ndefaults:\n  run:\n    shell: pwsh\njobs:\n  gate:\n"
                "    runs-on: x\n    steps:\n      - name: a\n        run: echo x\n",
                EXIT_UNTRUSTED,
            ),
            (
                "a missing working-directory is refused, not a traceback",
                head + "      - name: wd\n        working-directory: nope/here\n"
                "        run: echo x\n",
                EXIT_UNTRUSTED,
            ),
            (
                "an existing working-directory is honoured",
                head + "      - name: wd\n        working-directory: sub\n"
                '        run: test "$(basename "$PWD")" = sub\n',
                0,
            ),
            (
                "zero run steps is refused",
                head + "      - uses: actions/checkout@v6\n",
                EXIT_UNTRUSTED,
            ),
            (
                "unknown job is refused",
                "on: push\njobs:\n  other:\n    runs-on: x\n    steps:\n"
                "      - name: a\n        run: echo a\n",
                EXIT_UNTRUSTED,
            ),
            (
                "the default shell has NO pipefail, like GitHub",
                head + "      - name: pipe\n        run: false | cat\n",
                0,
            ),
            (
                "an explicit shell: bash HAS pipefail, like GitHub",
                head + "      - name: pipe\n        shell: bash\n"
                "        run: false | cat\n",
                1,
            ),
            (
                "a job-level default shell: bash HAS pipefail",
                "on: push\njobs:\n  gate:\n    runs-on: x\n    defaults:\n"
                "      run:\n        shell: bash\n    steps:\n"
                "      - name: pipe\n        run: false | cat\n",
                1,
            ),
            (
                # Quoted on purpose: a bare `false` is a YAML boolean.
                # gh_text() renders it lowercase as GitHub does, so both
                # forms run `false` now; the quotes keep the fixture
                # reading as the shell command it is.
                "the default shell still stops on a failing command",
                head + '      - name: e\n        run: "false"\n',
                1,
            ),
            (
                "a non-string run scalar does not crash the replay",
                head + "      - name: num\n        run: 123\n",
                127,
            ),
            (
                "workflow-level env reaches the step",
                "on: push\nenv:\n  PLANT: seed\njobs:\n  gate:\n    runs-on: x\n"
                "    steps:\n      - name: env\n"
                '        run: test "$PLANT" = seed\n',
                0,
            ),
            (
                "a workflow-level env expression nobody can resolve is refused",
                "on: push\nenv:\n  X: ${{ secrets.NOPE }}\njobs:\n  gate:\n"
                "    runs-on: x\n    steps:\n      - name: a\n        run: echo x\n",
                EXIT_UNTRUSTED,
            ),
            (
                "a job-level if: is refused",
                "on: push\njobs:\n  gate:\n    runs-on: x\n    if: always()\n"
                "    steps:\n      - name: a\n        run: echo x\n",
                EXIT_UNTRUSTED,
            ),
            (
                "the script runs from a file, so $0 names one, as on a runner",
                head + '      - name: zero\n        run: test -f "$0"\n',
                0,
            ),
            (
                "a job-level default working-directory is honoured",
                "on: push\njobs:\n  gate:\n    runs-on: x\n    defaults:\n"
                "      run:\n        working-directory: sub\n    steps:\n"
                '      - name: wd\n        run: test "$(basename "$PWD")" = sub\n',
                0,
            ),
            (
                "a boolean env value reaches the step lowercase, as on GitHub",
                head + "      - name: flag\n        env:\n          FLAG: true\n"
                '        run: test "$FLAG" = true\n',
                0,
            ),
            (
                "a job with container: is refused",
                "on: push\njobs:\n  gate:\n    runs-on: x\n    container: node:20\n"
                "    steps:\n      - name: a\n        run: echo x\n",
                EXIT_UNTRUSTED,
            ),
            (
                "a job with services: is refused",
                "on: push\njobs:\n  gate:\n    runs-on: x\n    services:\n"
                "      db:\n        image: postgres:16\n"
                "    steps:\n      - name: a\n        run: echo x\n",
                EXIT_UNTRUSTED,
            ),
            (
                "a null steps: is refused, not a traceback",
                "on: push\njobs:\n  gate:\n    runs-on: x\n    steps:\n",
                EXIT_UNTRUSTED,
            ),
            (
                "the parent's VIRTUAL_ENV does not reach a step",
                head + '      - name: venv\n        run: test -z "${VIRTUAL_ENV:-}"\n',
                0,
            ),
        ]
        failed = 0
        # The VIRTUAL_ENV case is vacuous unless the parent carries
        # one, so the whole battery runs with one set; no other case
        # depends on its absence.
        saved = os.environ.get("VIRTUAL_ENV")
        os.environ["VIRTUAL_ENV"] = str(root / "not-a-venv")
        try:
            for label, jobs, expected in cases:
                write(jobs)
                got: int | str
                try:
                    got = replay(wf, "gate", root=root, resolvers=fake, tail=5)
                except Exception as exc:
                    # Round 2 amputated a refusal and the whole battery
                    # died at case 12 of 22 with a traceback; the nine
                    # cases behind it never ran. A crash is one FAIL.
                    got = f"{type(exc).__name__}: {exc}"
                ok = got == expected
                mark = "ok  " if ok else "FAIL"
                print(f"{mark} {label}: expected {expected}, got {got}")
                failed += 0 if ok else 1
        finally:
            if saved is None:
                os.environ.pop("VIRTUAL_ENV", None)
            else:
                os.environ["VIRTUAL_ENV"] = saved
        # The real resolver must refuse, not guess, when origin/HEAD is
        # unset: a temp dir is not a repository.
        try:
            default_branch(root)
            print("FAIL unset origin/HEAD is refused: no LookupError raised")
            failed += 1
        except LookupError:
            print("ok   unset origin/HEAD is refused")
        total = len(cases) + 1
    print(f"self-test: {total - failed} of {total} passed")
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    """Parse arguments and dispatch."""
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--job", default=None, help="job to replay or list; default gate")
    ap.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository to replay in (a worktree, for instance); default: this one",
    )
    ap.add_argument(
        "--workflow",
        type=Path,
        default=None,
        help="workflow file; default: <root>/.github/workflows/ci.yml",
    )
    ap.add_argument("--list", action="store_true", help="show jobs and steps")
    ap.add_argument("--keep-going", action="store_true")
    ap.add_argument("--tail", type=int, default=60)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    root: Path = args.root.resolve()
    workflow: Path = args.workflow or root / ".github" / "workflows" / "ci.yml"
    if args.self_test:
        return self_test()
    if args.list:
        doc = load_workflow(workflow)
        try:
            listed = (
                doc["jobs"] if args.job is None else {args.job: job_spec(doc, args.job)}
            )
        except KeyError as exc:
            print(f"REFUSED: {exc}")
            return EXIT_UNTRUSTED
        for job, spec in listed.items():
            steps = spec.get("steps") or []
            runs = sum(1 for s in steps if "run" in s)
            print(f"{job}: {runs} run-steps, {len(steps) - runs} uses-steps")
            for i, s in enumerate(steps, start=1):
                kind = "run " if "run" in s else "uses"
                print(f"  {i:2d} {kind} {s.get('name', s.get('uses', '?'))}")
        return 0
    return replay(
        workflow,
        args.job or "gate",
        root=root,
        keep_going=args.keep_going,
        tail=args.tail,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
