#!/usr/bin/env python3
"""Every harness must have a ROW FLOOR at one layer or the other.

    python3 docs/reviews/check-row-floors.py

**The defect this exists for, measured on `check-u9-http-controls.sh`.**
`FIRED -ne TOTAL` is satisfied by `0 == 0`. With thirteen of its
fourteen rows deleted that harness printed *"1/1 controls fired"* and
exited **0**; with a floor it prints *"1/14 ROWS"* and exits **1**.

R4-M4 recorded the defect. R7-H2 found U9 still had no floor and framed
it as three of four siblings fixed and one missed. **That framing is
the same defect one level up:** R7 enumerated the four units named in
its own brief. A review scoped to its own assignment is itself a
hand-kept list.

**THIS CHECKER GOT THE SAME THING WRONG TWICE, WHICH IS WHY IT SAYS SO
HERE.** Its first version globbed only `check-*-controls.sh`, so the
thirteen `-amputation.sh` harnesses were never in its container either.
And it judged `check-harness-anchors-controls.sh` unwired because that
one is invoked directly rather than through `ci-harness-gate.sh` - the
detector knew one spelling and reported a confident false negative.
Both are exactly the failure it exists to catch, found within an hour
of writing it, in the artefact whose whole point was to catch them.

**THE FLOOR LIVES AT EITHER OF TWO LAYERS, and checking one is how you
get a wrong answer.** A harness may declare `ROW_FLOOR=<n>` internally,
or `ci.yml` may pass `--min-rows <n>` to `ci-harness-gate.sh`. Nine
harnesses have an external floor and no internal one. A checker that
looked only inside the scripts would call all nine defective; one that
looked only at `ci.yml` would miss the internally-floored. Only the
JOIN answers the question.

**What it deliberately does NOT check: whether a floor is RIGHT.** A
floor is honest only if DERIVED from a run of that harness, and no
static reader can tell a derived number from a typed one - branch-local
floors have been wrong here four times. This answers the narrower
question completely and says which one it answered.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CI = ROOT / ".github/workflows/ci.yml"

#: Both families. The first version of this file listed only the first
#: pattern, which is the whole lesson in the docstring above.
FAMILIES = ("scripts/check-*-controls.sh", "scripts/check-*-amputation.sh")

#: `ROW_FLOOR=25`, a literal integer. `ROW_FLOOR=$TOTAL` is not a floor:
#: it equals TOTAL by construction and passes with every row deleted.
FLOOR = re.compile(r"^\s*ROW_FLOOR=(\d+)\s*$", re.M)

#: The floor must be READ, not only assigned. A harness that sets
#: ROW_FLOOR and never compares it is inoperative code that would
#: satisfy a checker looking only for the assignment.
USES = re.compile(r"\$\{?ROW_FLOOR\}?")


def ci_floors() -> tuple[dict[str, int | None], set[str]]:
    """`--min-rows` per harness, and every harness `ci.yml` mentions.

    Two return values because they answer different questions and
    conflating them is how the first version of this file decided a
    directly-invoked harness was unwired. **Mentioned-at-all** is a
    plain substring search, so it is blind to no spelling; the
    `--min-rows` map only covers the `ci-harness-gate.sh` form, which
    is the only form that takes that flag.
    """
    text = CI.read_text(encoding="utf-8")
    floors: dict[str, int | None] = {}
    # `\Z` is load-bearing and was missing. Without it the LAST gate
    # invocation in the file matches nothing - there is no following
    # blank line or `- name:` at EOF - so its `--min-rows` is invisible
    # and the harness is reported as having no floor. Control C2 caught
    # this; reading the code did not.
    pattern = (
        r"ci-harness-gate\.sh\s+(\S+)((?:.|\n)*?)"
        r"(?=\n\s*\n|\n\s*- name:|\Z)"
    )
    for match in re.finditer(pattern, text):
        rows = re.search(r"--min-rows\s+(\d+)", match.group(2))
        floors[match.group(1)] = int(rows.group(1)) if rows else None

    mentioned = set()
    for family in FAMILIES:
        for path in ROOT.glob(family):
            if path.name in text:
                mentioned.add(path.name)
    return floors, mentioned


def main() -> int:
    found = sorted({p for f in FAMILIES for p in ROOT.glob(f)})
    if not found:
        print("MATCHED ZERO HARNESSES. A search at a path that does not")
        print("exist returns a clean empty, indistinguishable from real")
        print("absence - so this is exit 2, never a green.")
        return 2
    if not CI.is_file():
        print(f"{CI} does not exist. Half the join is missing.")
        return 2

    floors, mentioned = ci_floors()
    print(f"{'HARNESS':<46}{'INTERNAL':<10}{'CI':<8}{'--min-rows':<11}")
    unwired: list[str] = []
    ungated: list[str] = []

    for path in found:
        name = path.name
        text = path.read_text(encoding="utf-8", errors="replace")
        match = FLOOR.search(text)
        internal = int(match.group(1)) if match and USES.search(text) else None
        external = floors.get(name)
        wired = name in mentioned

        print(
            f"{name:<46}{str(internal or '-'):<10}"
            f"{('yes' if wired else 'NO'):<8}"
            f"{str(external if external is not None else '-'):<11}"
        )
        if not wired:
            unwired.append(name)
        elif internal is None and external is None:
            ungated.append(name)

    print(f"\nHarnesses: {len(found)}")
    print(f"  not referenced by ci.yml at all : {len(unwired)}")
    print(f"  wired but no floor at either layer: {len(ungated)}")
    for name in unwired:
        print(f"    UNWIRED  {name}")
    for name in ungated:
        print(f"    NO FLOOR {name}")

    if unwired or ungated:
        print(
            "\nAn unwired harness runs nowhere: it is a green that was never\n"
            "asked. A floorless one reports fully green with all but one row\n"
            "deleted, because `FIRED -ne TOTAL` is satisfied by 0 == 0.\n"
            "DERIVE any floor you add from a run of that harness. Typing one\n"
            "in clears this check and buys nothing."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
