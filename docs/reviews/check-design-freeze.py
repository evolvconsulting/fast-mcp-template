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
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
FREEZE_FILE = ROOT / "docs" / "DESIGN-FREEZE.txt"
DESIGN = "docs/DESIGN.md"


def git(*args: str) -> str:
    """Run git in the repo; return stdout, or raise with its stderr."""
    done = subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True
    )
    if done.returncode != 0:
        detail = done.stderr.strip()
        print(f"git {' '.join(args)} failed: {detail}")
        if "invalid object name" in detail or "bad object" in detail:
            print("THE FROZEN SHA IS NOT IN THIS CLONE. That is almost always a")
            print("SHALLOW checkout - `actions/checkout` defaults to depth 1 and")
            print("cannot see the commit DESIGN-FREEZE.txt names. Set")
            print("`fetch-depth: 0` on the job. It is NOT evidence the design moved.")
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
        print("compare nothing and pass. Exit 2.")
        return 2

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
