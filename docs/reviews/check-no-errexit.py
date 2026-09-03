#!/usr/bin/env python3
"""No tracked shell script may enable `errexit`. Here is why.

    python3 docs/reviews/check-no-errexit.py

**THE INVARIANT.** Every tracked `.sh` here runs under
`set -uo pipefail` with **no `-e`**, and a great deal now depends on
that. The harness timeout work is written as

    timeout 900 uv run --frozen pytest ...
    baseline_rc=$?

A BARE command followed by a capture. Under `errexit` the shell dies at
the command and `baseline_rc=$?` is never reached, so **every timeout
arm becomes dead code** - the abort branches, the "this row never
finished" messages, all of it. The script would still exit non-zero, so
CI would still be red, but it would be red for a reason nobody could
read.

That is not hypothetical. It is the same defect as the sixteen
unreachable CI diagnostic branches fixed at `3ee39e5`, and as a local
gate that printed `ruff EXIT=1` and pushed anyway because the status was
consumed by `$?` instead of gating.

**WHY A GATE RATHER THAN A CONVENTION.** The invariant has been
hand-measured three separate times - at `2d20ed6`, at `5eb64b0`, and by
review R10, which enumerated 43 tracked `.sh` and found every one
`set -uo pipefail` with zero `-e`. Three people re-establishing the same
fact is the signal that it wants an executable home. Nothing recorded it
anywhere a machine could check, so each measurement expired the moment
it was written.

**`-e` IS NOT SIMPLY WORSE, AND THIS FILE MUST NOT PRETEND IT IS.**
`errexit` is good practice in most shell. It is refused HERE because
these scripts deliberately run commands that are EXPECTED to fail - a
mutation that should turn a suite red, a probe whose non-zero exit IS
the observation - and then read the status. `docs/reviews/`'s own
`probe-set-e-vs-harness.sh` exists to demonstrate exactly that, and says
so: *"a probe that cannot survive its own finding proves nothing."*
Anyone adding a harness with `set -euo pipefail` is following good
general advice; this gate has to tell them why it does not apply here,
or they will reasonably conclude the gate is the bug.

**WHAT IT CANNOT DO.** It is STATIC. A `set` whose flags are composed at
runtime is invisible to it - `probe-set-e-vs-harness.sh:18` has exactly
such a line, `set '"$flags"'`, inside a `bash -c`, and that is the one
place in the tree where enabling `-e` is the POINT. A checker that
flagged it would be wrong, and one that could see through it would need
to be a shell interpreter. So: this gate covers the literal form, which
is the form anyone will actually write by accident.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

#: A `set` line that turns errexit ON, in either spelling: a short-flag
#: cluster containing `e` (`-e`, `-eu`, `-euo pipefail`), or the long
#: form. Anchored at the start of a line so a `set` nested inside a
#: quoted `bash -c` body - always indented in this tree - is not matched
#: by accident. The blind spot is stated in the docstring rather than
#: papered over.
ERREXIT = re.compile(
    r"^set\s+(-[a-zA-Z]*e[a-zA-Z]*|-o\s+errexit)\b",
    re.MULTILINE,
)

#: Scripts that may enable errexit, each with the reason. **A bare name
#: is refused: the reason IS the exemption**, the same shape
#: `check-settings-are-read.py` uses.
#:
#: THIS DICT EXISTS BECAUSE MY FIRST VERSION WAS TOO BROAD. It refused
#: `-e` in every tracked `.sh`, conflating two different kinds of file.
#: A HARNESS runs commands that are EXPECTED to fail and then reads
#: their status - errexit makes that unreachable. A CHECKER's own exit
#: code IS the measurement, and it guards each fallible call with
#: `|| true`, so errexit is correct there and protects it from a typo
#: silently continuing.
#:
#: The merge is what surfaced this: the rule and the script it refuses
#: were written on different branches by different authors, each
#: correct alone.
EXEMPT: dict[str, str] = {
    "scripts/check-pytest-bounded.sh": (
        "a CHECKER, not a harness. Its own line 24 states the deviation "
        "by purpose, every fallible call is guarded with `|| true`, and "
        "its exit code is the measurement rather than something it reads."
    ),
}
assert all(v.strip() for v in EXEMPT.values()), "a blank reason is not an exemption"


def tracked_shell_scripts() -> list[pathlib.Path]:
    """Every tracked `.sh`, from git - NOT a path glob.

    `scripts/*.sh` is the narrowing that hid three unbounded pytest
    calls in `docs/reviews/` from the sweep that existed to find them.
    The container is what git tracks.
    """
    done = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "*.sh"],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise SystemExit(f"git ls-files failed: {done.stderr.strip()}")
    return [ROOT / line for line in done.stdout.split()]


def main() -> int:
    scripts = tracked_shell_scripts()
    if not scripts:
        print("MATCHED ZERO tracked .sh files. An empty population reports")
        print("a clean result, which would mean nothing here. Exit 2.")
        return 2

    offenders: list[str] = []
    exempted: list[str] = []
    for path in scripts:
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if ERREXIT.match(line):
                rel = str(path.relative_to(ROOT))
                if EXEMPT.get(rel, "").strip():
                    exempted.append(f"{rel}: {EXEMPT[rel]}")
                    continue
                offenders.append(f"{rel}:{number}  {line.strip()}")

    print(f"Tracked shell scripts checked: {len(scripts)}")
    for entry in exempted:
        print(f"  EXEMPT   {entry}")
    if not offenders:
        print("None enables errexit. The `cmd; rc=$?` form is reachable.")
        return 0

    print(f"\n{len(offenders)} script(s) enable errexit:")
    for hit in offenders:
        print(f"  {hit}")
    print(
        "\nThese harnesses run commands that are EXPECTED to fail and then\n"
        "read the status. Under errexit the shell exits AT the command, so\n"
        "`cmd; rc=$?` never runs and every branch below it is dead code -\n"
        "including the timeout aborts. Use `set -uo pipefail`, and gate an\n"
        "individual command with `|| rc=$?` or an `if` where you need it."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
