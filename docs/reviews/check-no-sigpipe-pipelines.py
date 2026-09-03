#!/usr/bin/env python3
"""`printf ... | grep -q` under `pipefail` returns 141 when big.

    python3 docs/reviews/check-no-sigpipe-pipelines.py

**THE DEFECT, measured rather than argued.** `grep -q` exits the instant
it matches. If the writer is still writing it takes SIGPIPE, and
`set -o pipefail` promotes that 141 to the pipeline's status - so a
string that IS present reports as ABSENT:

    large output, needle PRESENT -> 141 <- the bug small output, needle
    PRESENT -> 0 <- why it hides large output, needle ABSENT -> 1

It only fires once the output outruns the pipe buffer, so it arrives as
a function of suite growth. `check-u0-test-controls.sh` judged a row
"the expected test was NOT the failing test" and printed that exact test
as failing three lines below, out of the same variable, because that row
breaks ~89 tests and every other row breaks one or two.

**Sixteen sites were fixed in one day (#85), and I found only five of
them on the first pass** - my sweep for siblings stopped at the
directory I was editing. This file is the reason a seventeenth cannot
arrive unnoticed.

**THE FIX IS A HERE-STRING, NOT A BASH TEST, WHERE `^` IS INVOLVED.**
`grep -qE` matches PER LINE; bash `=~` matches the whole string, so `^`
anchors to the start of the OUTPUT. Measured against an output whose
second line is the match: pipe 141, `=~` 1, here-string 0. Six of the
eleven `ci.yml` sites anchor with `^`.

**AND THIS CHECKER FILTERS COMMENTS, WHICH IS NOT AN OPTIMISATION.** Two
agents independently grepped for this pattern to confirm it was gone and
both matched the COMMENT EXPLAINING THE FIX - the repaired code sits
directly under a note quoting the broken form in order to forbid it. A
checker that greps for a defect will always find that defect's
documentation, and the better a codebase is at explaining its fixes the
more false positives it produces.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

#: The container, enumerated rather than listed. `scripts/*.sh` plus the
#: workflow, because the first sweep fixed five sites in `scripts/`,
#: grepped `scripts/`, came back clean, and left ELEVEN in `ci.yml`.
FAMILIES = ("scripts/*.sh", ".github/workflows/*.yml")

#: `printf ... | grep -q`, in any of its spellings: `-q`, `-qF`, `-qE`,
#: `-Fxq`. Deliberately broad - a narrowed pattern stops matching a real
#: instance before it stops matching a comment.
SIGPIPE = re.compile(r"printf\b[^|\n]*\|\s*grep\s+-[a-zA-Z]*q[a-zA-Z]*\b")

#: A line whose first non-space character is `#`. Filtering these is why
#: this checker does not report the notes that forbid the defect.
COMMENT = re.compile(r"^\s*#")


def main() -> int:
    found = sorted({p for f in FAMILIES for p in ROOT.glob(f)})
    if not found:
        print(f"MATCHED ZERO FILES across {FAMILIES!r}.")
        print("A search at a path that does not exist returns a clean empty,")
        print("indistinguishable from real absence - so this is exit 2.")
        return 2

    hits: list[str] = []
    commented = 0
    for path in found:
        for num, text in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if not SIGPIPE.search(text):
                continue
            if COMMENT.match(text):
                commented += 1
                continue
            hits.append(f"{path.relative_to(ROOT)}:{num}  {text.strip()[:72]}")

    print(f"Files scanned: {len(found)}")
    print(f"Occurrences inside COMMENTS, ignored: {commented}")
    if not hits:
        print("\nNo `printf | grep -q` in executable code. OK.")
        return 0

    print(f"\n{len(hits)} live occurrence(s):")
    for hit in hits:
        print(f"  {hit}")
    print(
        "\nUnder `set -o pipefail` each of these returns 141 when the match is\n"
        "found early on a large output, reporting a string that IS present as\n"
        'ABSENT. Replace with `grep -q... <<< "$out"`, which keeps grep\'s\n'
        "PER-LINE semantics, or with a bash substring test where no `^` or\n"
        "line anchoring is involved."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
