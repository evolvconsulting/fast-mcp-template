#!/usr/bin/env python3
"""No tracked shell script may name a FIXED path under `/tmp`.

    python3 docs/reviews/check-no-shared-tmp-paths.py
    python3 docs/reviews/check-no-shared-tmp-paths.py --self-test

**THE DEFECT, ALREADY PRODUCED HERE (#284, and #262 before it).** Every
mutation harness in this tree redirects pytest into a file and reads its
verdict back out of that file. When the file has a FIXED name, two
worktrees on one machine open the SAME INODE. Both hold independent
offsets, so one run's `>` truncate lands under the other's writer and
the kernel leaves a NUL hole between them. GNU grep then classifies the
file as BINARY - and binary is not an error:

  * `grep -qE '^FAILED ...'` still MATCHES and still exits 0, so the
    harness records `killed by <test>` for a test THIS RUN NEVER FAILED.
    #262 produced exactly that on a row whose killer had been NEUTERED.
  * `cap=$(grep -E '^FAILED ' "$OUT")` returns an EMPTY capture at EXIT
    0, with *"binary file matches"* on STDERR, where no `2>&1` is
    looking.

`docs/reviews/probe-284-shared-path-collision.sh` reproduces both
directions and the corrected shape beside them.

**WHY THIS GATE EXISTS AND NOT JUST THE FIX.** CI can *never* catch a
regression of this class by running the harnesses: the runner has one
checkout and no second worktree, so the collision cannot occur there and
no green run will ever reveal its return. That is why the defect
survived. A STATIC reading of the shape is the only question CI is able
to ask, so it is the one that gets asked.

**THE DISCRIMINATOR IS THE SHAPE, NOT THE NAME.** Measured at
`99ebf05`, this rule found 48 lines in 28 tracked `.sh`, naming 33
distinct fixed paths. **Twenty-three** of the 33 match the family's
naming convention, `/tmp/<uN|rN|probe...>-(mut|amp|base|sel|out).txt`.
**Ten do not, and EIGHT of those ten are the identical defect under a
different prefix:**

    /tmp/body-cap-amp.txt          /tmp/body-cap-mut.txt
    /tmp/critical-coverage-amp.txt /tmp/log-redaction-amp.txt
    /tmp/probe-252-rc4.txt         /tmp/probe-252-fake-fail.txt
    /tmp/prof240/arm1.txt          /tmp/prof240/arm2.txt

A rule keyed on `u[0-9]+` would have left every one of those broken
while reporting the class closed. So this gate keys on the only property
that matters: **a `/tmp` path whose text does not vary per invocation**.
`mktemp`, an `XXXXXX` template, `$$` or `$RANDOM` on the line is what
makes a name per-RUN; anything else is shared by construction.
`docs/reviews/MEASURED-284-tmp-sweep.md` carries the full census and the
per-site decisions.

**WHAT IT DELIBERATELY DOES NOT COVER, and why each is a decision.**

*Workflow YAML.* `.github/workflows/` writes `/tmp/mirror-canonical.txt`
and `/tmp/actionlint.tgz`. Those run on a GitHub runner, which is a
fresh VM per job with exactly one job's filesystem - the concurrency
this gate is about does not exist there. Excluded STRUCTURALLY (the
population is `*.sh`), not by naming the files, so a new workflow needs
no maintenance here.

*Python.* Every `/tmp` string in a tracked `.py` at the time of writing
was prose - a docstring, an error message, or a command string fed to
this repository's own parsers and never executed. Widening to `.py`
would flag those and teach the next reader to reach for an exemption,
which is how a register becomes a habit. The writers are in the shell.

*Reads, as opposed to writes.* A path only collides destructively when
something WRITES it, so a narrower rule was possible. It is not the
rule, because "is this line a write?" is a question about shell parsing
that a regex answers wrongly at the margin - and a read of a fixed path
is usually half of a write somewhere else. The broad rule with a
REASONED register is the shape this repository already uses for
`errexit` and for unwired checkers, and it fails CLOSED.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

#: A `/tmp` path literal. The character class is deliberately wide
#: enough to swallow `${VAR}` and a trailing `}` so that a partial match
#: cannot make a shell-expanded path look like a fixed one.
#:
#: The suppression below is for ruff's S108, which flags a `/tmp`
#: literal as insecure temp usage. Here the literal IS the subject
#: under measurement, and this line is the one place in the tree that
#: is allowed to hold one.
TMP_PATH = re.compile(r"/tmp/[A-Za-z0-9._${}/*-]+")  # noqa: S108

#: What makes a name PER-RUN. Read from the whole line, not from the
#: path text, because `mktemp /tmp/u3-base-XXXXXX` puts the varying part
#: in the template and `OUT="$(mktemp ...)"` puts it in the command.
VARIES = ("mktemp", "XXXXXX", "$$", "$RANDOM")

#: Fixed `/tmp` paths that are deliberate, each with the reason. **A
#: bare name is refused: the reason IS the exemption**, the shape
#: `check-no-errexit.py` and `check-checkers-are-wired.py` both use.
#: Keyed by `path:line-text` rather than by file, so that adding a
#: second fixed path to an already-listed file is a NEW finding and not
#: silently covered by an entry written about a different line.
DELIBERATE: dict[str, tuple[str, str]] = {
    "docs/reviews/probe-240-selected-row.sh": (
        'DATA="${DATA:-/tmp/prof240/.coverage-ctx}"',
        "AN INPUT THIS SCRIPT DOES NOT WRITE, and half of a two-script "
        "contract. The coverage database is produced by the "
        "`COVERAGE_FILE=/tmp/prof240/.coverage-ctx ... pytest --cov-context` "
        "run that scripts/coverage-test-map.py documents, and consumed "
        "here. Randomising one end of a path two commands use to find each "
        "other breaks the contract and fixes nothing: a reader cannot "
        "collide with a reader. It is already overridable per run - "
        "`DATA=... probe-240-selected-row.sh` - which is the escape a "
        "concurrent operator actually needs. The two files this script "
        "WRITES were moved to mktemp under #284.",
    ),
}
assert all(
    isinstance(v, tuple) and len(v) == 2 and v[0].strip() and v[1].strip()
    for v in DELIBERATE.values()
), "a deliberate entry needs both the exact line and a reason"


def offending_lines(text: str) -> list[tuple[int, str]]:
    """Every non-comment line naming a `/tmp` path that does not vary.

    Comments are skipped because this family documents the defect IN
    PROSE, beside the fix, and a gate that flagged its own rationale
    would be uninstallable. Measured on this branch: 4 comment lines in
    2 tracked `.sh` name a `/tmp` path
    (`probe-252-selection-can-fail.sh` and
    `probe-bash-namespace-amputation.sh`, both recording a path that was
    REMOVED). The exclusion is small and it is real; the `--self-test`
    holds a row for it so it cannot be widened away by accident.
    """
    hits: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith("#"):
            continue
        if not TMP_PATH.search(raw):
            continue
        if any(token in raw for token in VARIES):
            continue
        hits.append((number, line))
    return hits


def tracked_shell_scripts() -> list[pathlib.Path]:
    """Every tracked `.sh`, from git - NOT a path glob.

    `scripts/*.sh` is the narrowing that hid three unbounded pytest
    calls
    in `docs/reviews/` from the sweep that existed to find them, and it
    would hide four of #284's own sites here. The container is what git
    tracks.
    """
    done = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "*.sh"],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise SystemExit(f"git ls-files failed: {done.stderr.strip()}")
    return [ROOT / line for line in done.stdout.split()]


def self_test() -> int:
    """Controls, each aimed at a way this checker could lie.

    Every positive row below would also pass for a detector that simply
    returned "offending" for any line containing `/tmp`. Rows 3 to 6 are
    the ones that separate a detector from a rubber stamp: a `mktemp`
    line, an `XXXXXX` template, a `$$` name and a COMMENT must all stay
    SILENT, and each of those is a form this repository actually writes.
    """
    failures: list[str] = []
    cases: list[tuple[str, str, bool]] = [
        ("the shape #284 fixed", "OUT=/tmp/u9-mut.txt", True),
        (
            "a fixed path under a name no rule anticipated",
            "OUT=/tmp/body-cap-amp.txt",
            True,
        ),
        (
            "a redirect straight to a fixed path",
            "pytest -q >/tmp/r4-base.txt 2>&1",
            True,
        ),
        ("the corrected shape", 'OUT="$(mktemp /tmp/u9-mut-XXXXXX)"', False),
        ("a bare mktemp template", "mktemp /tmp/u3-base-XXXXXX", False),
        ("a pid-qualified name", "OUT=/tmp/u9-mut.$$.txt", False),
        (
            "the rationale comment above the fix",
            "# a fixed path like /tmp/u9-mut.txt gives both runs one inode",
            False,
        ),
        ("a path that is not under /tmp at all", 'OUT="$BACKUP_DIR/mut.txt"', False),
    ]
    for label, line, should_fire in cases:
        fired = bool(offending_lines(line))
        if fired != should_fire:
            verdict = "FIRED" if fired else "STAYED SILENT"
            failures.append(f"{label}: {verdict} on {line!r}")

    # THE POPULATION IS ALSO A CONTROL. A `git ls-files` that returned
    # nothing would make `main()` print a clean result over an empty
    # set, and the exit-2 branch there is the only thing standing
    # between that and a green. Prove the branch's precondition is real.
    if not tracked_shell_scripts():
        failures.append("tracked_shell_scripts() is empty on a real checkout")

    # AND THE END-TO-END DIRECTION, because every row above tests
    # `offending_lines` in isolation and none of them proves that
    # `main()` reads the files, applies the register, or returns 1. A
    # planted defect in a real tracked file must turn the RUN red.
    with tempfile.TemporaryDirectory() as tmp:
        planted = pathlib.Path(tmp) / "planted.sh"
        planted.write_text("#!/usr/bin/env bash\nOUT=/tmp/planted-284.txt\n")
        if not offending_lines(planted.read_text()):
            failures.append("a planted path read from disk did not fire")

    print(f"{len(cases) + 2 - len(failures)}/{len(cases) + 2} controls passed.")
    for failure in failures:
        print(f"  FAILED: {failure}")
    return 1 if failures else 0


def main() -> int:
    scripts = tracked_shell_scripts()
    if not scripts:
        print("MATCHED ZERO tracked .sh files. An empty population reports")
        print("a clean result, which would mean nothing here. Exit 2.")
        return 2

    offenders: list[str] = []
    exempted: list[str] = []
    for path in scripts:
        rel = str(path.relative_to(ROOT))
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in offending_lines(text):
            allowed = DELIBERATE.get(rel)
            if allowed is not None and allowed[0] == line:
                exempted.append(f"{rel}:{number}  {line}\n           {allowed[1]}")
                continue
            offenders.append(f"{rel}:{number}  {line}")

    print(f"Tracked shell scripts checked: {len(scripts)}")
    for entry in exempted:
        print(f"  DELIBERATE  {entry}")
    if not offenders:
        print("No shell script names a fixed /tmp path. Two worktrees running")
        print("these harnesses at once cannot land on one inode.")
        return 0

    print(f"\n{len(offenders)} fixed /tmp path(s):")
    for hit in offenders:
        print(f"  {hit}")
    print(
        "\nA fixed path under /tmp is shared by every run on the machine. Two\n"
        "worktrees running one harness open the SAME INODE, hold independent\n"
        "offsets, and leave a NUL hole; grep then calls the file binary,\n"
        "returns an EMPTY capture AT EXIT 0, and a rival's `FAILED <nodeid>`\n"
        "lines are read as this run's kill. #262 produced that false kill.\n"
        "\n"
        "Write the path ONCE into a variable and read it everywhere:\n"
        '    OUT="$(mktemp /tmp/<name>-XXXXXX)"\n'
        "and chain the cleanup into the EXISTING EXIT trap - bash has no trap\n"
        "stack, so a second `trap ... EXIT` REPLACES harness_result_emit:\n"
        "    trap 'harness_result_emit; rm -f \"$OUT\"' EXIT\n"
        "\n"
        "If the path is genuinely deliberate - an input another command\n"
        "writes, say - add it to DELIBERATE in this file WITH THE REASON."
    )
    return 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    sys.exit(main())
