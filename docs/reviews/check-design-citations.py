#!/usr/bin/env python3
"""Every `DESIGN.md:N` citation points at a line that exists.

After an edit it also says which ones moved.

**Why this exists, and why now.** Three citations to `DESIGN.md` have
been found pointing at the wrong lines, none of them by a gate. They
were found in the SOURCE project this template was extracted from, and
their addresses are deliberately NOT reproduced here: this project's
`docs/DESIGN.md` is a placeholder, so each would be a citation into a
document that has no such line. What survives is the KIND of each
failure, which is the part that is about citations rather than about
that design:

  - one cited a section that did not exist at all. ADR-0019.
  - one had been contracted by a line, and so dropped the `http`
    transport row §7.2 leans on - found by U1, in a brief I wrote.
  - three separate citations of the three runtime pins pointed nine
    lines above them, at the prose paragraph about the resolve - found
    by U4.

`check-cross-references.py` cannot see any of these: it validates `§n.m`
SECTION pointers, and these are `file:line` RANGES. **Nothing checks a
line range at all.**

A contracted range is the sharper failure. A dangling one announces
itself; a contracted one still resolves, still quotes accurately, and
lands the reader on text that reads exactly like it could be the
subject.

WHAT THIS CAN AND CANNOT DO, stated plainly because the gap matters:

  It CAN check that a cited line exists, and it CAN say which citations
  a given edit to DESIGN.md moved, and where to.

  It CANNOT check that a range CONTAINS ITS SUBJECT. That needs a
  subject recorded beside the citation, which is what
  `docs/OBLIGATIONS.md` does for its 28 rows and what task #30 proposes
  generalising. **A green here means "the citation resolves", never "the
  citation is right"** - which is exactly the distinction that let all
  three defects above survive.

THE `--since` MODE IS THE POINT. `docs/DESIGN.md`'s freeze SHA lives in
`docs/DESIGN-FREEZE.txt` and is not retyped here - it was retyped
once, the design moved at `86ab20e`, and every copy went on naming
the old object. That edit shifts an unknown number of the citations in
the tree it is run against; in the source project there were 841 of
them (by this script, not by the grep I first reached for, which said
836). Run:

    python3 docs/reviews/check-design-citations.py \
        --since "$(cat docs/DESIGN-FREEZE.txt)"

before and after, and it maps old line numbers to new ones through a
real diff, then reports every citation whose target moved. Without it,
applying those ADRs means either re-checking them by hand or shipping
them unverified. MEASURED: a five-line insertion at line 300 moves 723
of the 841.

Usage:
    python3 docs/reviews/check-design-citations.py # bounds + inventory
    python3 docs/reviews/check-design-citations.py --since <sha> python3
    docs/reviews/check-design-citations.py --controls

Exit 0 when every citation resolves, 1 otherwise. No dependencies.
"""

from __future__ import annotations

import difflib
import pathlib
import re
import subprocess
import sys

import repoint_exempt

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DESIGN = REPO_ROOT / "docs" / "DESIGN.md"

# Examples, REPOINT-EXEMPT: `DESIGN.md:603`, `DESIGN.md:918-924` - these
# are what the pattern MATCHES, not citations of anything, so they must
# not move. The filename is required so this does not match a bare
# number, and `docs/DESIGN.md:` forms are caught by the same pattern.
_CITATION = re.compile(r"DESIGN\.md:(\d+)(?:-(\d+))?")

_SEARCH_SUFFIXES = {".py", ".toml", ".md", ".yml", ".yaml", ".sh"}
_SKIP_PARTS = {".git", ".venv", "venv", "__pycache__", ".ruff_cache", ".pytest_cache"}


def _tracked_files() -> list[pathlib.Path]:
    """Every tracked file worth scanning.

    `git ls-files` is the authority.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    ).stdout
    files = []
    for name in out.split("\0"):
        if not name:
            continue
        path = REPO_ROOT / name
        if path.suffix not in _SEARCH_SUFFIXES:
            continue
        if any(part in _SKIP_PARTS for part in pathlib.Path(name).parts):
            continue
        files.append(path)
    return files


#: A line carrying this marker is an EXAMPLE of a citation, not a
#: citation OF anything, and `check-design-citation-shape.py` honours
#: the same one. THIS CHECKER DID NOT, which is the asymmetry: a review
#: in the source project quoted the deliberately-out-of-bounds
#: citations its own probe had planted, as EVIDENCE, and one of those
#: lines already carried the marker and was flagged anyway. A wired
#: gate went red on a report describing the very defect the gate looks
#: for. That review is NOT carried here and is described rather than
#: named: the template's docs/ holds no records, so naming it would be
#: a pointer to a file nobody can open.
EXEMPT_MARKER = repoint_exempt.MARKER
#: CITATIONS skipped, not LINES. #142 changed the unit deliberately:
#: the old line count reported 51 while 36 of those lines carried no
#: citation at all, so the number that was supposed to make the
#: exemption visible was mostly counting prose about the exemption.
EXEMPT_SKIPPED = 0


def citations() -> list[tuple[pathlib.Path, int, int, int]]:
    """Every citation as (file, line-it-appears-on, start, end).

    Lines marked `REPOINT-EXEMPT` are skipped and COUNTED, so the
    exemption can never be silent - a skip nobody reports is how a
    population shrinks without anyone noticing.
    """
    found: list[tuple[pathlib.Path, int, int, int]] = []
    global EXEMPT_SKIPPED
    EXEMPT_SKIPPED = 0
    for path in _tracked_files():
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in _CITATION.finditer(line):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else start
                # #142: the marker selects the LINE and the register
                # grants the CITATION. Neither alone is an exemption,
                # and anything else on the line stays in the
                # population - which is the granularity half of R13-H1.
                if repoint_exempt.is_exempt(line, rel, start, end):
                    EXEMPT_SKIPPED += 1
                    continue
                found.append((path, lineno, start, end))
    return found


def line_map(old_text: str, new_text: str) -> dict[int, int | None]:
    """Map each 1-based line of `old_text` into `new_text`, or None.

    None means the line was deleted or changed, so a citation pointing
    at it can no longer be resolved automatically and needs a human.
    """
    old = old_text.splitlines()
    new = new_text.splitlines()
    mapping: dict[int, int | None] = {}
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, _ in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                mapping[i1 + offset + 1] = j1 + offset + 1
        elif tag in ("replace", "delete"):
            for i in range(i1, i2):
                mapping[i + 1] = None
    return mapping


def _report_bounds(total_lines: int) -> int:
    found = citations()
    if not found:
        print(
            "SELECTOR CONTROL: no DESIGN.md citations found anywhere. The "
            "pattern is broken, not the corpus."
        )
        return 1

    bad = [
        f"{p.relative_to(REPO_ROOT)}:{ln}: DESIGN.md:{s}"
        + (f"-{e}" if e != s else "")
        + f" is past the end of DESIGN.md ({total_lines} lines)"
        for p, ln, s, e in found
        if s > total_lines or e > total_lines or s < 1 or e < s
    ]
    print(
        f"  {len(found)} DESIGN.md citations across "
        f"{len({p for p, _, _, _ in found})} files"
    )
    print(f"  highest line cited: {max(e for _, _, _, e in found)} of {total_lines}")
    # R13-H1: THIS LINE DID NOT EXIST AND THE DOCSTRING SAID IT DID.
    # `citations()` says skips are "COUNTED, so the exemption can never
    # be silent - a skip nobody reports is how a population shrinks
    # without anyone noticing." EXEMPT_SKIPPED was assigned, reset and
    # incremented - and READ NOWHERE. I wrote both the counter and the
    # claim, on the same day, and never ran the check it describes.
    #
    # The review proved the consequence with a plant: ONE line carrying
    # the marker and an address tens of thousands of lines past the end
    # of the design passed THIS gate and the shape gate, both exit 0,
    # nothing printed. The plant is described and not reproduced,
    # because written out in citation shape it would be a live citation
    # here, needing a register row of its own for a demonstration whose
    # evidence this template does not carry.
    print(f"  citations exempt (marked AND registered): {EXEMPT_SKIPPED}")
    print(repoint_exempt.report())
    if bad:
        print(f"\n{len(bad)} problem(s):")
        for b in bad:
            print(f"  FAIL: {b}")
        return 1
    print("\nEvery citation resolves to a line that exists.")
    print(
        "NOTE: that is NOT the same as pointing at the right line. This checker "
        "cannot see a contracted range; three have been found by hand."
    )
    return 0


def _report_moves(sha: str) -> int:
    # `check=True` USED TO RAISE HERE, and the traceback it produced
    # cost three CI rounds to read. On a SHALLOW checkout the blob is
    # simply absent, `git show` exits 128, and CalledProcessError
    # propagated out of a probe two layers up - where it surfaced as
    # `exit=1 failed=none`, which names nothing at all.
    #
    # A MISSING OBJECT IS A BROKEN INSTRUMENT, NOT A FINDING, and the
    # two must not share an exit code. `check-design-freeze.py` already
    # says this for the same cause; here is its sibling learning it.
    done = subprocess.run(
        ["git", "show", f"{sha}:docs/DESIGN.md"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if done.returncode != 0:
        detail = done.stderr.strip()
        print(f"git show {sha}:docs/DESIGN.md failed: {detail}")
        # THE PHRASING IS THE WHOLE TRICK, and my first version missed
        # the one git actually emits. A depth-1 clone that HAS the path
        # but not the commit says "exists on disk, but not in <sha>" -
        # not "bad object", which is what a wholly unknown ref gets.
        # Matching only the second left the hint silent in the exact
        # case it was written for; a local shallow-clone control is
        # what showed that.
        missing = (
            "bad object",
            "unknown revision",
            "exists on disk, but not in",
            "does not exist",
        )
        if any(phrase in detail for phrase in missing):
            print(f"THE COMMIT {sha[:7]} IS NOT IN THIS CLONE. That is almost")
            print("always a SHALLOW checkout - `actions/checkout` defaults to")
            print("fetch-depth 1 and cannot see it. Set `fetch-depth: 0` on the")
            print("job. It is NOT evidence that any citation moved.")
        print("This is a BROKEN INSTRUMENT, not a finding. Exit 3.")
        return 3
    old = done.stdout
    new = DESIGN.read_text()
    if old == new:
        print(f"DESIGN.md is byte-identical to {sha}. No citation can have moved.")
        return 0

    mapping = line_map(old, new)
    moved: list[str] = []
    broken: list[str] = []
    for path, lineno, start, end in citations():
        new_start, new_end = mapping.get(start), mapping.get(end)
        rel = path.relative_to(REPO_ROOT)
        cited = f"DESIGN.md:{start}" + (f"-{end}" if end != start else "")
        if new_start is None or new_end is None:
            broken.append(
                f"{rel}:{lineno}: {cited} - that line CHANGED; a human "
                "must re-read the subject"
            )
        elif (new_start, new_end) != (start, end):
            new_cited = f"DESIGN.md:{new_start}" + (
                f"-{new_end}" if new_end != new_start else ""
            )
            moved.append(f"{rel}:{lineno}: {cited} -> {new_cited}")

    print(
        f"  against {sha}: {len(moved)} citation(s) moved, "
        f"{len(broken)} point at changed lines"
    )
    for line in broken:
        print(f"  BROKEN: {line}")
    for line in moved:
        print(f"  MOVED:  {line}")
    return 1 if (moved or broken) else 0


def controls() -> int:
    """Prove each check can go red, on real content."""
    fired = total = 0
    text = DESIGN.read_text()

    total += 1
    mapping = line_map(text, "inserted\n" + text)
    if mapping.get(10) == 11:
        fired += 1
        print("  CONTROL an inserted line shifts the map -> FIRED")
    else:
        print(
            f"  CONTROL an inserted line shifts the map -> DID NOT FIRE "
            f"(got {mapping.get(10)})"
        )

    total += 1
    lines = text.splitlines()
    lines[9] = "THIS LINE IS REPLACED"
    if line_map(text, "\n".join(lines)).get(10) is None:
        fired += 1
        print("  CONTROL a changed line maps to None -> FIRED")
    else:
        print("  CONTROL a changed line maps to None -> DID NOT FIRE")

    total += 1
    if _CITATION.findall("see DESIGN.md:918-924 and DESIGN.md:603"):  # REPOINT-EXEMPT
        fired += 1
        print("  CONTROL the pattern reads both forms -> FIRED")
    else:
        print("  CONTROL the pattern reads both forms -> DID NOT FIRE")

    print(f"\n{fired}/{total} controls fired.")
    return 0 if fired == total else 1


def main(argv: list[str]) -> int:
    # A BROKEN REGISTER IS A BROKEN INSTRUMENT, NOT A FINDING, and the
    # two must not share an exit code. That is the rule `_report_moves`
    # already states one function up for a missing git object, and this
    # file was not applying it to its own register: a missing or
    # malformed REPOINT-EXEMPT.txt let `RegisterError` escape as a raw
    # traceback and exit 1, which is the code that means "a citation
    # does not resolve". A reader would have read a broken instrument as
    # a finding.
    #
    # EXIT 3 IS THE MAJORITY CONVENTION HERE, and no digit says how big
    # the majority is. This comment said "nine checkers" and was wrong
    # twice over. A review counted EIGHT by reading each file and
    # setting aside the ones that are a CONTROL for another checker;
    # a plain search over the container returns SEVENTEEN by counting
    # them all; and nothing in this repository defines which of those
    # two populations the word "checker" names. A count whose
    # partition is undefined is not a fact about the tree, it is a
    # fact about the counter, and this branch has now deleted three
    # such digits for the same reason.
    #
    # THE PARTITION IS BY CONTENT, AND A FILENAME FILTER PROVABLY
    # FAILS IT. This comment first said EIGHT was reached "by
    # excluding the `-controls.sh` harnesses". Applied literally that
    # rule yields TEN, because `check-row-floor-control.sh` calls
    # itself a POSITIVE CONTROL in its own first line and carries a
    # real `exit 3`, while its name is singular and misses the plural
    # suffix; a sibling one character longer, `-controls.sh`, is a
    # different file. A rule stated as a name pattern is blind to the
    # member whose name nobody matched, which is the defect this
    # sentence was already about, one column over.
    #
    # The same sentence also called `repoint_exempt.main`'s exit 2 "the
    # odd one out". It is not the only one:
    # `check-brief-report-references.py` also exits 2 for this concept
    # and IS a checker rather than a module, so the exception is
    # neither unique nor explained by being a `__main__`. Exit 3 is
    # still the right code for this file, because its own sibling path
    # `_report_moves` already uses it; that argument never needed a
    # census and should not have been given one.
    try:
        if "--controls" in argv:
            return controls()
        if "--since" in argv:
            return _report_moves(argv[argv.index("--since") + 1])
        return _report_bounds(len(DESIGN.read_text().splitlines()))
    except repoint_exempt.RegisterError as exc:
        print(f"BROKEN REGISTER: {exc}")
        print("This is a BROKEN INSTRUMENT, not a finding. Exit 3.")
        return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
