#!/usr/bin/env python3
"""The design at the declared freeze must be the design on the trunk.

    python3 docs/reviews/check-design-freeze.py

**WHY THIS EXISTS.** `docs/DESIGN.md` is frozen: only a numbered ADR may
change it, and every brief hands its agent a SHA to read it at. On
2026-09-01 review R10 found the two had come apart:

    aca9397:docs/DESIGN.md -> e009ac4   <- what every pointer named
    HEAD:docs/DESIGN.md    -> 639f4b7   <- what was actually on main

`86ab20e` edited the design - correcting a STRIDE row's disposition -
and no freeze pointer moved. Four live sites went on naming the old
object, including a brief written that same day that dispatched an
agent to read it as "the authority".

**IT WAS BENIGN BY LUCK, WHICH IS THE ARGUMENT FOR THE GATE.** The edit
replaced one line in place; both blobs are 2133 lines, no citation
moved, and both citation checkers still exited 0. Had the edit inserted
or removed a line, every line-numbered citation past it would have
pointed one line off - resolving, plausible, and wrong. Nothing checked
which of those two it was.

**WHAT IT CHECKS.** That the SHA in `docs/DESIGN-FREEZE.txt` and `HEAD`
name the same DESIGN.md BLOB. Blob identity, not a diff summary and
not a line count: two files can share a line count and still differ,
which is exactly what happened here.

**WHAT IT CANNOT DO.** It cannot tell a legitimate ADR-driven edit from
an unauthorised one. Both look like a moved blob. It only forces the
question to be answered - by advancing the freeze deliberately - rather
than left unasked.

**THREE OUTCOMES, THREE EXIT CODES, and the split is a fix rather than
a nicety.**

    0   the frozen blob and the trunk blob are the same object
    1   THE DESIGN MOVED. A finding about the repository.
    2   NOT FROZEN YET. A task: run `scripts/refreeze.sh`.
    3   BROKEN INSTRUMENT. Do not believe this output.

Exit 2 exists because of a measured misdiagnosis. A child repository
that copies the template's `DESIGN-FREEZE.txt` inherits a SHA from
ANOTHER repository, and `git rev-parse` fails on it - so every child
used to open with *"This is a BROKEN INSTRUMENT."* The instrument was
fine. `--is-shallow-repository` is the discriminator: an absent
object in a SHALLOW clone is a genuine instrument failure
(`fetch-depth: 1`); in a COMPLETE clone the pointer is someone else's.
Presence itself is asked with `git cat-file -e`, never inferred from an
error message - the first attempt at this fix grepped stderr, met a
third wording, and fell straight back through to exit 3.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
FREEZE_FILE = ROOT / "docs" / "DESIGN-FREEZE.txt"
DESIGN = "docs/DESIGN.md"


#: The sentinel a fresh child repository ships with. It is NOT a SHA, on
#: purpose - see `_refuse_unfrozen`.
UNFROZEN = "UNFROZEN"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run git in the repo. The caller decides what a failure means."""
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False
    )


def _is_shallow() -> bool:
    """Is this a shallow clone? The discriminator, not a guess."""
    done = _run("rev-parse", "--is-shallow-repository")
    return done.returncode == 0 and done.stdout.strip() == "true"


def _refuse_unfrozen(why: str) -> None:
    """The design is not frozen YET. Say what to do, and exit 2.

    **THIS IS THE DIFFERENCE BETWEEN A TASK AND A BROKEN MACHINE, and
    getting it wrong cost every child repository its first impression.**
    A template ships `DESIGN-FREEZE.txt`; copied into a child, its SHA
    names a commit in ANOTHER repository, `git rev-parse` fails, and the
    checker printed *"This is a BROKEN INSTRUMENT. Exit 3."* Measured on
    a real adoption, 2026-09-03: every child starts by reporting that
    its instrument is broken, when in fact the instrument is fine and
    the project simply has not frozen its design yet.

    Exit 2 is this file's *you have work to do* code. Exit 3 is *do not
    believe my output*. They are different facts and must not print the
    same.
    """
    print(why)
    print()
    print("THE DESIGN IS NOT FROZEN IN THIS REPOSITORY YET.")
    print("This is a TASK, not a broken instrument.")
    print()
    print("  1. Write docs/DESIGN.md and commit it.")
    print("  2. bash scripts/refreeze.sh")
    print("  3. Commit docs/DESIGN-FREEZE.txt.")
    print()
    print("It is two commits because no commit can contain its own SHA.")
    print("Exit 2.")
    raise SystemExit(2)


def _require_commit(sha: str) -> None:
    """The frozen commit must be an object here. Else 2 or 3, never 0.

    **THE QUESTION IS ASKED DIRECTLY, NOT INFERRED FROM STDERR.** The
    first version of this fix grepped `git rev-parse` for
    `invalid object name`. Its own control refused it: resolving
    `<sha>:docs/DESIGN.md` against an absent commit says
    *"path 'docs/DESIGN.md' exists on disk, but not in '<sha>'"* - a
    third message, matching neither pattern, so the fix fell through to
    exit 3 and rebuilt the very defect it was written to close. An error
    string is a thing a tool's author picks. `cat-file -e` is a
    question with an exit code.
    """
    if _run("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0:
        return

    if _is_shallow():
        print(f"The frozen commit {sha} IS NOT IN THIS CLONE, and this clone")
        print("is SHALLOW. `actions/checkout` defaults to depth 1 and cannot")
        print("see the commit DESIGN-FREEZE.txt names. Set `fetch-depth: 0`")
        print("on the job. It is NOT evidence the design moved.")
        print("This is a BROKEN INSTRUMENT, not a finding. Exit 3.")
        raise SystemExit(3)

    _refuse_unfrozen(
        f"The frozen commit {sha} is not an object in this repository,\n"
        "and this clone is NOT shallow, so it never will be. It names a\n"
        "commit somewhere else - almost always the template's own, copied\n"
        "in with the rest of the machinery."
    )


def git(*args: str) -> str:
    """Run git in the repo; return stdout, or refuse with its stderr."""
    done = _run(*args)
    if done.returncode != 0:
        print(f"git {' '.join(args)} failed: {done.stderr.strip()}")
        print("This is a BROKEN INSTRUMENT, not a finding. Exit 3.")
        raise SystemExit(3)
    return done.stdout.strip()


def main() -> int:
    if not FREEZE_FILE.exists():
        print(f"{FREEZE_FILE.relative_to(ROOT)} is missing.")
        print("Without it nothing declares which SHA the design is frozen")
        print("at, and every brief's citation is unanchored. Exit 2.")
        return 2

    frozen = FREEZE_FILE.read_text(encoding="utf-8").strip()
    if not frozen:
        print("DESIGN-FREEZE.txt is EMPTY. A blank declaration would")
        print("compare nothing and pass.")
        _refuse_unfrozen("")

    if frozen.split()[0].upper() == UNFROZEN:
        _refuse_unfrozen(
            "DESIGN-FREEZE.txt carries the UNFROZEN sentinel rather than a SHA."
        )

    _require_commit(frozen)
    frozen_blob = git("rev-parse", f"{frozen}:{DESIGN}")
    head_blob = git("rev-parse", f"HEAD:{DESIGN}")

    print(f"Declared freeze: {frozen}")
    print(f"  {DESIGN} at {frozen}: {frozen_blob}")
    print(f"  {DESIGN} at HEAD:      {head_blob}")

    if frozen_blob == head_blob:
        print("\nThe frozen design and the trunk's design are the same blob.")
        return 0

    print("\nTHE DESIGN HAS MOVED SINCE ITS DECLARED FREEZE.")
    print("Every brief handing out that SHA is naming a stale object, and")
    print("any line-numbered citation may now resolve to the wrong line.")
    print("\nWhat changed:")
    print(git("diff", "--stat", frozen, "HEAD", "--", DESIGN))
    print("\nIf the edit was authorised by a numbered ADR, advance")
    print("docs/DESIGN-FREEZE.txt to the commit carrying it. If not,")
    print("revert it - the design is frozen.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
