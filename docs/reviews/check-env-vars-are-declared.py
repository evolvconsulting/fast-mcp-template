#!/usr/bin/env python3
"""Flag a `JOBVITE_*` name that `src/` documents but nothing declares.

    python3 docs/reviews/check-env-vars-are-declared.py

**This is the MIRROR of `check-settings-are-read.py`, and the two
questions are not the same.** That one asks *"is this declared setting
consumed?"* and starts from the `Settings` class. This one asks *"is
this documented variable declared?"* and starts from the strings in the
source. **A name invented in a comment is invisible to the first checker
by construction**, because it never reaches `Settings` at all.

**MEASURED at `0fe4628`.** Four names appear only in `#:` comments
beside `Final` constants in `services/jobvite_client.py`:
`JOBVITE_OUTBOUND_BUDGET_SECONDS`, `JOBVITE_RETRY_MAX_ATTEMPTS`,
`JOBVITE_BREAKER_FAILURE_THRESHOLD` and
`JOBVITE_BREAKER_RECOVERY_SECONDS`. None is a `Settings` field, none is
in `.env.example`, `README.md` or `server.json`. **An operator who reads
the source and sets one gets nothing**, and the comment reads exactly
like documentation for a knob that works.

**The frozen design names none of the four**, which is the sharper half:
§4.3 requires "a total outbound budget, configured",
and the plan's §U9 records why naming a variable is the design's call
and not an implementation's - a whole unit was once unbuildable because
three variables had no names, and a reviewer's guesses were correctly
not adopted on that basis.

**WHAT THIS CANNOT DO.** It matches a literal string. A variable read
through composition - `f"JOBVITE_{suffix}"` - is invisible to it, and so
is one documented in prose that never appears in `src/`. Stated here
rather than discovered later.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / "src" / "fast_mcp_template" / "config.py"
PREFIX = "JOBVITE_"
# `(?<![\w])` IS LOAD-BEARING. Without it this matched
# `_JOBVITE_BREAKER`, a PRIVATE MODULE VARIABLE, and reported it as an
# undeclared environment variable - one false finding out of five on the
# first run. A checker whose first output is 20% noise is one nobody
# reads twice.
NAME = re.compile(r"(?<![\w])JOBVITE_[A-Z][A-Z0-9_]*")

#: Names that are deliberately not `Settings` fields, each with the
#: reason a reader needs. A bare name is refused: the reason IS the
#: exemption, the same shape `.file-type-allowlist` uses.
EXEMPT: dict[str, str] = {
    "JOBVITE_CANDIDATE_DATA": (
        "Not a variable at all: it is the FENCE TAG `utils/redaction.py` wraps "
        "untrusted candidate content in. The checker matches any JOBVITE_* "
        "literal, so a fence name reads like a setting - the second "
        "false-positive class it has produced, after a private module "
        "variable. Exempted rather than narrowed, because a pattern that "
        "tried to tell a tag from a variable would start guessing."
    ),
}


def declared() -> set[str]:
    """`JOBVITE_*` names a `Settings` field would answer to.

    pydantic-settings maps a field to `JOBVITE_<FIELD>` through
    `env_prefix`, so the literal never appears in `config.py` - which is
    why this is derived from the field names rather than grepped.
    """
    tree = ast.parse(CONFIG.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            return {
                PREFIX + stmt.target.id.upper()
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and not stmt.target.id.startswith("_")
            }
    message = "no `Settings` class in config.py - the selector is broken"
    raise SystemExit(message)


def _tracked_sources() -> list[pathlib.Path]:
    """Every tracked `.py` under `src/`, selected by KIND not by PATH.

    `git ls-files` enumerates the container and the suffix is the
    filter. The previous form, `(ROOT / "src").rglob("*.py")`, selected
    by PATH: it admitted any UNTRACKED `.py` left under `src/`, so a
    scratch file could supply a `JOBVITE_*` literal and manufacture an
    undeclared-name finding that no committed source contains.

    MEASURED WHEN THIS CHANGED, and the honest reading is the weaker
    one: both forms yielded the same 23 files, so this closes a defect
    that has not yet happened rather than one that has.
    `check-design-citations.py` is the shape this copies; if the two
    ever disagree, that is the bug.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "src"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    files = sorted(
        ROOT / name
        for name in out.split("\0")
        if name and pathlib.Path(name).suffix == ".py"
    )
    if not files:
        message = "no tracked `.py` under src/ - the selector is broken"
        raise SystemExit(message)
    return files


def mentioned() -> dict[str, list[str]]:
    """Every `JOBVITE_*` literal in `src/`, mapped to where it is."""
    found: dict[str, list[str]] = {}
    for path in _tracked_sources():
        for num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for name in NAME.findall(line):
                found.setdefault(name, []).append(f"{path.relative_to(ROOT)}:{num}")
    return found


def main() -> int:
    known = declared()
    seen = mentioned()
    if not seen:
        print("MATCHED ZERO NAMES. The selector is broken; a green means nothing.")
        return 1

    print(f"`Settings` declares: {len(known)}")
    print(f"`JOBVITE_*` names appearing in src/: {len(seen)}")

    undeclared = {n: w for n, w in seen.items() if n not in known}
    bad = {n: w for n, w in undeclared.items() if n not in EXEMPT}
    stale = [n for n in EXEMPT if n in known or n not in seen]

    for name in sorted(undeclared):
        if name in EXEMPT:
            print(f"  EXEMPT       {name}\n               {EXEMPT[name]}")
        else:
            print(f"  UNDECLARED   {name}")
            for where in undeclared[name]:
                print(f"               {where}")

    for name in sorted(stale):
        print(f"  STALE EXEMPTION  {name} is declared or gone; drop its EXEMPT entry")

    if bad or stale:
        print(f"\n{len(bad)} undeclared name(s), {len(stale)} stale exemption(s).")
        print("A name documented beside a constant reads as a knob that works.")
        print("An operator sets it and gets nothing.")
        return 1

    print("\nEvery `JOBVITE_*` name in src/ is a declared Settings field, or")
    print("exempt with a reason. NOTE: this matches LITERALS - a name built by")
    print("composition, or documented only in prose, is invisible to it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
