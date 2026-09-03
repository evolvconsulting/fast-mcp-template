#!/usr/bin/env python3
"""Flag `DESIGN.md:N` citations whose target CANNOT be their subject.

    python3 docs/reviews/check-design-citation-shape.py [--sha <ref>]

R4 found ten of eighteen sampled citations in U5 landing **one paragraph
short** of their subject, and recommended a checker over the whole
population rather than finishing 29 more by hand. This is that checker
for the part a machine can decide.

**WHAT IT CANNOT DO, said first because it is the important half.** It
cannot tell whether a citation is RIGHT. Only a reader who knows the
claim can. `docs/reviews/check-design-citations.py` already proves a
citation RESOLVES, and this project has found that "resolves" and
"correct" are different things nine times over.

**WHAT IT CAN DECIDE.** A citation whose range is out of bounds,
entirely blank, or nothing but a code fence or table separator has a
target that cannot be anyone's subject, whatever the claim. And a range
that STARTS on a blank line is the exact shape of the off-by-one R4
measured: the author counted the paragraph break rather than the
paragraph.

Measured when written, against the freeze OF THAT DAY, and over the
NARROWER population it scanned then - `src/ tests/ scripts/`, before the
scan was widened to every tracked `.py`/`.sh` including the checkers in
`docs/reviews/`. The numbers below are that measurement and are not
re-derived. **The current freeze is the `--sha` default and nowhere
else in this file** - it has moved three times, and a second copy of it
in prose went stale on the second move:
399 occurrences, 206 distinct ranges, 0 out of bounds, 8 entirely blank,
11 fence-or-separator only. A record of where a defect WAS, so it does
not move: `DESIGN.md:311` (REPOINT-EXEMPT) was cited for "a URL
containing a secret is never constructed"; 311 was blank and the
sentence was at 312-313.

**Not a CI gate yet.** It reports a lower bound on a defect population
nobody has finished counting, and wiring a gate whose backlog is unknown
lands red - which this project has refused three times. Run it, fix what
it names, then wire it.

**R12-N1 ADDED A FOURTH SHAPE: a range that ENDS on a blank line**, i.e.
one line longer than its subject. The start check had had no mirror
since it was written. It was raised off TWO instances a reviewer had
read - `DESIGN.md:373-383` and `:674-680`, REPOINT-EXEMPT because
this line RECORDS where the defect was - and the check then found
FORTY-SIX, which is this docstring's own lesson arriving at the
person writing the check. Harmless per instance and cumulative in
the aggregate: a range that can grow a line at every repoint
eventually spans the next section, and `check-design-citations.py`
will keep calling it resolved the whole way. Re-measured on the
merged trunk the population was FORTY-SEVEN, not forty-six, and
#126 swept it: the backlog this paragraph is about is now zero, and
the number is printed by the run rather than trusted from here.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import subprocess
import sys

import repoint_exempt

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CITE = re.compile(r"DESIGN\.md:(\d+)(?:-(\d+))?")

#: The population is chosen by KIND, not by PATH. Every tracked `.py`
#: or `.sh` file is CODE, wherever it lives, and its citations are
#: claims about the design as it is NOW. Prose is excluded by SUFFIX: a
#: review or worklog `.md` cites the design as it stood when it was
#: written, and re-pointing those would rewrite history to match the
#: present.
#:
#: This was `LIVE = ("src", "tests", "scripts")`, and it excluded
#: `docs/reviews/` for exactly the prose reason above. That reasoning is
#: right for a review DOCUMENT and wrong for the ~40 CHECKERS in the
#: same directory - wired CI gates, linted and type-checked, whose
#: citations had never been scanned by anything.
#: `check-settings-are-read.py:9` carried a citation that RESOLVED and
#: named the wrong sentence; both citation gates passed it and a reader
#: found it (#114, fixed at dad014e). A path list cannot see the KIND of
#: the thing at the path.
CODE_SUFFIXES = {".py", ".sh"}

STRUCTURAL = ("```", "|---", "---", "|--", ":--")

#: Necessary, not sufficient, since #142: the marker selects the line
#: and docs/reviews/REPOINT-EXEMPT.txt grants the citation.
EXEMPT = repoint_exempt.MARKER


def code_files() -> list[pathlib.Path]:
    """Every tracked code file, enumerated from the CONTAINER.

    `git ls-files` is the authority rather than a list of directories,
    so a new directory of checkers is scanned the day it lands. A
    hand-kept list is blind to the member nobody adds to it.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(
        ROOT / name
        for name in out.split("\0")
        if name and pathlib.Path(name).suffix in CODE_SUFFIXES
    )


def design_lines(sha: str) -> list[str]:
    out = subprocess.run(
        ["git", "show", f"{sha}:docs/DESIGN.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.splitlines()


def classify(start: int, end: int, lines: list[str]) -> str | None:
    """Why this citation cannot be its subject, or None if it can be.

    LIFTED OUT OF `main`'s LOOP so it can be exercised directly. While
    this logic lived inline, the only way to reach it was to scan the
    whole tree, which meant nothing tested it - and R10 measured the
    consequence: deleting the blank-start branch outright left the
    scan's output byte-identical at 148 files / 875 citations / 0
    findings, with both population controls still printing FIRED. A
    detector no test can reach is a detector whose absence is invisible.
    """
    if end > len(lines):
        return "past the end of DESIGN.md"
    body = lines[start - 1 : end]
    if not "".join(body).strip():
        return "the entire range is blank"
    if all(line.strip().startswith(STRUCTURAL) for line in body if line.strip()):
        return "only a fence or table separator"
    if not body[0].strip():
        return "starts on a BLANK line (the off-by-one shape)"
    # R12-N1, re-applied into `classify` rather than merged as its hunk:
    # R12 wrote this against the inline chain R10 had already lifted out
    # here, so the diff conflicted while the INTENT did not.
    #
    # `end > start` is LOAD-BEARING: it keeps single-line citations
    # out, since a wholly blank one is caught by the branch above.
    #
    # R12 raised this off TWO instances it had read; the check it then
    # wrote found FORTY-SIX. Its words: a finding raised from a partial
    # read IS a partial check - this file's own opening lesson, landing
    # on the reviewer writing the fix for it.
    if end > start and not body[-1].strip():
        return "ends on a BLANK line (one line too long)"
    return None


def detector_controls(lines: list[str]) -> tuple[int, int]:
    """Each detector must FIRE on a citation built to trip it.

    Built from the frozen design in memory, so this costs nothing and
    writes no files. These are the controls whose absence R10-M2
    recorded: the two below prove the POPULATION is right and say
    nothing about whether anything is still being detected in it.
    """
    blank = next(i for i, t in enumerate(lines, 1) if not t.strip())
    starts_blank = next(
        i
        for i, t in enumerate(lines, 1)
        if not t.strip()
        and i < len(lines)
        and lines[i].strip()
        and not lines[i].strip().startswith(STRUCTURAL)
    )
    # The mirror of `starts_blank`, for the branch R12 added: a
    # range whose LAST line is blank. Without this case the new
    # detector would have NO control - the exact defect R10-M2
    # recorded one branch above, which I nearly re-created here
    # while merging the fix for it.
    ends_blank = next(
        i
        for i, t in enumerate(lines, 1)
        if not t.strip() and i > 1 and lines[i - 2].strip()
    )
    solid = next(
        i
        for i, t in enumerate(lines, 1)
        if t.strip() and not t.strip().startswith(STRUCTURAL)
    )

    cases: list[tuple[str, int, int, str | None]] = [
        ("past the end", len(lines) + 1000, len(lines) + 1000, "past the end"),
        ("ends on a blank line", ends_blank - 1, ends_blank, "ends on a BLANK"),
        ("entirely blank", blank, blank, "entire range is blank"),
        ("starts on a blank line", starts_blank, starts_blank + 2, "starts on a BLANK"),
        # THE NEGATIVE CONTROL. Without it every arm above passes on a
        # `classify` that simply returns a finding for everything.
        ("a citation that RESOLVES", solid, solid, None),
    ]

    fired = 0
    for label, start, end, expect in cases:
        got = classify(start, end, lines)
        ok = (got is None) if expect is None else (got is not None and expect in got)
        if ok:
            fired += 1
            print(f"  DETECTOR {label} -> FIRED ({got or 'no finding, as required'})")
        else:
            print(f"  DETECTOR {label} -> DID NOT FIRE; the branch is dead (got {got})")
    return fired, len(cases)


def controls(lines: list[str]) -> int:
    """Prove the population is by KIND, and that it is still scanned.

    A narrowed exclusion that STILL misses `docs/reviews/` looks exactly
    like one that was removed - both print a clean run. These say which
    it is, and they go red if the selector is re-narrowed to a directory
    list. The detector arm answers the other half: a right population
    that nothing examines also prints a clean run.
    """
    names = {p.relative_to(ROOT).as_posix() for p in code_files()}
    fired = total = 0

    total += 1
    checkers = sorted(n for n in names if n.startswith("docs/reviews/"))
    if checkers:
        fired += 1
        print(f"  CONTROL the checkers are IN ({len(checkers)} files) -> FIRED")
    else:
        print("  CONTROL the checkers are IN -> DID NOT FIRE, the scan skips them")

    total += 1
    prose = [n for n in names if n.endswith(".md")]
    if not prose:
        fired += 1
        print("  CONTROL prose (.md) stays OUT -> FIRED")
    else:
        print(f"  CONTROL prose (.md) stays OUT -> DID NOT FIRE ({len(prose)} in)")

    det_fired, det_total = detector_controls(lines)
    fired += det_fired
    total += det_total

    print(f"\n{fired}/{total} controls fired.")
    return 0 if fired == total else 1


def frozen_sha() -> str:
    """The frozen-design SHA, READ from `docs/DESIGN-FREEZE.txt`.

    Never a literal here. The SHA was retyped into two checkers and a
    brief, the design moved at `86ab20e`, and all three kept naming the
    old object - benign only because the edit happened to fall outside
    what anyone was reading. A value chosen once appears once.
    """
    return (ROOT / "docs" / "DESIGN-FREEZE.txt").read_text(encoding="utf-8").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", default=frozen_sha(), help="the frozen DESIGN.md")
    parser.add_argument(
        "--controls", action="store_true", help="prove the population is by kind"
    )
    args = parser.parse_args()

    lines = design_lines(args.sha)

    if args.controls:
        return controls(lines)

    findings: dict[str, list[str]] = collections.defaultdict(list)
    seen = 0
    exempted = 0

    paths = code_files()
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        body_lines = path.read_text(errors="replace").splitlines()
        for num, text in enumerate(body_lines, 1):
            for match in CITE.finditer(text):
                start = int(match.group(1))
                end = int(match.group(2) or match.group(1))
                # #142. A line that RECORDS where a defect was must not
                # be repointed and must not be reported - but it must
                # say WHICH citation it is recording, in the register,
                # or the marker exempts whatever else lands on the line.
                # Kept narrow: it skips the CITATION, not the line.
                if repoint_exempt.is_exempt(text, rel, start, end):
                    exempted += 1
                    continue
                seen += 1
                where = f"{path.relative_to(ROOT)}:{num}  {match.group(0)}"
                verdict = classify(start, end, lines)
                if verdict is not None:
                    findings[verdict].append(where)

    if seen == 0:
        print("PARSED ZERO CITATIONS. The selector is broken; a green means nothing.")
        return 1

    print(f"DESIGN.md citations in {len(paths)} tracked .py/.sh files: {seen}")
    print(f"Checked against {args.sha}, {len(lines)} lines.")
    # THE EXEMPTION SET IS PART OF THE RESULT. Any line can opt out of
    # this checker with a comment marker, and a growing exemption set
    # would otherwise be invisible in the very report that depends on
    # it - including from a genuinely wrong citation sharing the line.
    print(f"{exempted} citation(s) exempt (marked AND registered).")
    print(repoint_exempt.report() + chr(10))

    total = sum(len(v) for v in findings.values())
    for reason, rows in sorted(findings.items()):
        print(f"{len(rows):4}  {reason}")
        for row in rows:
            print(f"        {row}")

    print(
        f"\n{total} citation(s) point at something that cannot be their subject.\n"
        "This is a LOWER BOUND on wrong citations, and says nothing about the\n"
        "ones that land on real prose - only a reader who knows the claim can\n"
        "judge those. 'Resolves' and 'correct' are different things."
    )
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
