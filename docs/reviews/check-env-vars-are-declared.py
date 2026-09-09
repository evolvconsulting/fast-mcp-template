#!/usr/bin/env python3
"""Flag an env-prefixed name that `src/` documents but nothing declares.

    python3 docs/reviews/check-env-vars-are-declared.py

**This is the MIRROR of `check-settings-are-read.py`, and the two
questions are not the same.** That one asks *"is this declared setting
consumed?"* and starts from the `Settings` class. This one asks *"is
this documented variable declared?"* and starts from the strings in the
source. **A name invented in a comment is invisible to the first checker
by construction**, because it never reaches `Settings` at all.

**THE TWO PARAGRAPHS BELOW ARE HISTORY, in the identifiers of their
own time.** They record the measurement in fast-mcp-jobvite that
produced this checker. No file, variable or design section they name
exists in this template, and they are kept rather than rewritten
because a past measurement is not made true or false by a later
extraction. What the checker DOES is stated above and below them.

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
through composition - `f"{PREFIX}{suffix}"` - is invisible to it, and
so is one documented in prose that never appears in `src/`. Stated
here rather than discovered later.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / "src" / "fast_mcp_template" / "config.py"


def _config_text() -> str:
    """`config.py`'s source, or a NAMED REFUSAL at exit 3.

    **A MISSING CONFIG IS A BROKEN INSTRUMENT, NOT A FINDING.** Both
    readers of this file used bare `read_text`, so a CONFIG pointing at
    a path that is not there raised FileNotFoundError as an unhandled
    traceback, and an unhandled exception exits 1 - the code `main()`
    uses for a real undeclared name. A broken instrument was wearing a
    finding's exit code, which is the exact distinction the rest of this
    directory keeps.

    THAT IS REACHABLE RATHER THAN CONTRIVED. This checker's own registry
    row tells an adopter to point CONFIG at their renamed package, and
    the moment between editing that constant and moving the file is
    precisely when it is wrong. Found by review round 1 on this branch,
    in code this branch had just added, in the same shape this branch
    had already fixed three times in other files.

    ONE HELPER FOR BOTH READ SITES, deliberately: `_env_prefix` and
    `declared` each read the same file, and two guards written
    separately are two guards that can drift.
    """
    try:
        return CONFIG.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"{CONFIG} could not be read: {exc}")
        print("Point CONFIG at this project's settings module.")
        print("This is a BROKEN INSTRUMENT, not a finding. Exit 3.")
        raise SystemExit(3) from exc


def _env_prefix() -> str:
    """This project's env prefix, READ from config.py, never retyped.

    It arrived from the extraction as the literal `JOBVITE_`, so this
    checker was scanning this repository for ANOTHER project's
    variables and could match nothing here whatever `src/` said. A
    constant that mirrors a value living in another file drifts the
    moment that file changes; reading it cannot.
    """
    found = re.search(r'env_prefix\s*=\s*"([A-Za-z0-9_]+)"', _config_text())
    if not found:
        print(f"no env_prefix= in {CONFIG}. Point CONFIG at this")
        print("project's settings module. This is a BROKEN INSTRUMENT,")
        print("not a finding. Exit 3.")
        raise SystemExit(3)
    return found.group(1)


PREFIX = _env_prefix()
# `(?<![\w])` IS LOAD-BEARING. Without it this matched
# `_JOBVITE_BREAKER`, a PRIVATE MODULE VARIABLE, and reported it as an
# undeclared environment variable - one false finding out of five on the
# first run (in the source project, whose prefix that was). A checker
# whose first output is 20% noise is one nobody reads twice.
NAME = re.compile(rf"(?<![\w]){PREFIX}[A-Z][A-Z0-9_]*")

#: Names that are deliberately not `Settings` fields, each with the
#: reason a reader needs. A bare name is refused: the reason IS the
#: exemption, the same shape `.file-type-allowlist` uses.
#:
#: EMPTY HERE. Its one row exempted `JOBVITE_CANDIDATE_DATA`, a FENCE
#: TAG in the source project's `utils/redaction.py`, a file this
#: template does not have; with the prefix now derived, that name
#: cannot match at all. The row is deleted rather than kept, because a
#: dead exemption reads as a decision someone made about THIS
#: repository. Add one when a literal here matches the pattern and is
#: not a setting.
EXEMPT: dict[str, str] = {}


def declared() -> set[str]:
    """Prefixed names a `Settings` field would answer to.

    pydantic-settings maps a field to `<PREFIX><FIELD>` through
    `env_prefix`, so the literal never appears in `config.py` - which is
    why this is derived from the field names rather than grepped.
    """
    tree = ast.parse(_config_text())
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
    scratch file could supply a prefixed literal and manufacture an
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
    """Every prefixed literal in `src/`, mapped to where it is."""
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
    print(f"`{PREFIX}*` names appearing in src/: {len(seen)}")

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

    print(f"\nEvery `{PREFIX}*` name in src/ is a declared Settings field,")
    print("or")
    print("exempt with a reason. NOTE: this matches LITERALS - a name built by")
    print("composition, or documented only in prose, is invisible to it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
