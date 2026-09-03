#!/usr/bin/env python3
r"""A brief must cite a report that EXISTS in the repository.

    uv run --frozen python docs/reviews/check-brief-report-references.py

**THE DEFECT.** `REVIEW-R18.md` - 28KB, ten findings, the only narrative
record of its round - sat UNTRACKED in `fmj-worktrees/r18` for hours
while nothing in the repository could see it. `PREAMBLE.md:133` already
required the opposite: a report must be *"committed on your branch ...
Never only a worktree, never `/tmp`: a 48KB report with nineteen
findings was destroyed exactly that way"*. So the rule was written after
one loss and did not prevent the next near-loss. **A rule nothing checks
is a rule that documents its own violations.**

**AND THE BRIEF ITSELF OVERRODE THE RULE.**
`BRIEF-R19-the-fix-round.md` §A told the reviewer to read R18's report
*"on branch `review/r18` in `fmj-worktrees/r18`; read it from there"*.
It was not on that branch. A brief that names a WORKTREE path points at
something that stops existing when the agent finishes.

**THE SECOND DEFECT IS MINE, AND IT IS WHY THIS FILE EXISTS RATHER THAN
A EULOGY.** I searched every ref with `git cat-file -e` and every add
with `git log --all --diff-filter=A`, got nothing from both, and wrote
that the report was LOST. Both measurements were correct: it is in no
commit and in no dangling blob, because it was never `git add`ed.
**"In no git object" is not "gone".** An untracked file lives in the
FILESYSTEM - the one place a search over refs and objects cannot look -
and `suborch-170` looked there and found it.

The premise that carried the error was never measured at all. I wrote
"the worktree is gone"; `.git/worktrees` held fourteen entries and r18
was one of them. **A loss claim needs its own evidence, and it needs to
name all three places: refs, objects, filesystem.** An alarming
conclusion gets re-checked least, because re-checking feels like
doubting a loss.

**WHY THIS IS A RATCHET AND NOT A ZERO.** A brief legitimately names the
report its agent has not written yet. Demanding zero would be red by
construction and switched off within a day. So the gate records the
KNOWN-unresolvable set and fails when a NEW one appears.

**IT FAILS IN BOTH DIRECTIONS, which is the half that rots otherwise.**
A recorded entry that now RESOLVES is an error, and so is one nothing
cites any more. The record must shrink when the world does, or it
becomes a permanent excuse list nobody re-reads - the failure mode of
every allowlist this project has built. That is not theoretical here:
the entry for an in-flight worklog is designed to go red the moment the
agent commits it, which is how it deletes itself.

**RULED: THIS GATE CANNOT TELL A CITATION FROM A QUOTATION, AND THAT
FALSE POSITIVE IS ACCEPTED.** Its population is every report name
written in a brief, so a brief DISCUSSING a lost report - including this
one's own brief - is inside the population and goes red for naming it.
That happened twice in one hour, independently, to Tier 0 and to
`suborch-199`, on the same sentence in `BRIEF-199-ratchet-defects.md`.

The remedy is to REWRITE THE PROSE: describe the report instead of
writing its basename, and let the file's git history hold the names.
Both instances were fixed that way in under a minute, which is the whole
argument - the failure is loud, immediate, and cheap.

**THREE FIXES CONSIDERED AND REFUSED:**

- **An `EXEMPT` marker.** Refused on measurement, not taste: this
  project already deployed a bare-substring marker and watched it
  inflate a population from 47 to 61 PURELY FROM PROSE ABOUT THE MARKER.
  The most careful writers - the ones who document the mechanism - widen
  the hole fastest. `suborch-199` argued the same and was right.
- **A syntax split**, counting only path-qualified forms as citations
  and treating a bare basename as prose. Refused because it is FALSE
  HERE: `suborch-199` measured six names cited BOTH ways, so the bare
  form carries real citations and the split would drop them.
- **Recording the name in the ratchet.** Refused because that file's own
  header says recording is not a waiver, and a waiver for a file that
  NEVER EXISTED is the one thing it must not hold.

**WHAT MAKES THE FALSE POSITIVE TOLERABLE** is that it is confined to
one directory and one habit. A brief is written once and read by an
agent; a red here costs a sentence. Compare the defect it exists to
catch: a 28KB report written into a worktree, declared destroyed, and
recoverable only because someone looked in a third place.

**RE-DERIVING THE POPULATION, AND WHAT THAT IS STILL FOR.** Print the
shell recipe and run it:

    CHK=docs/reviews/check-brief-report-references.py
    uv run --frozen python "$CHK" --recipe
    uv run --frozen python "$CHK" --list-names

The first prints a `grep` one-liner; the second prints the gate's own
population. They must agree exactly, and arm A23 of the controls
proves they do by running one against the other.

**THE RECIPE USED TO BE A SECOND, HAND-WRITTEN SELECTOR, AND IT
MANUFACTURED THE FALSE FINDING THE COMMENT ON `REF` BELOW RECORDS.** It
read `grep -rhoE '(REVIEW|WORKLOG|FINDINGS)-...'` with NO left
boundary, so it returned `REVIEW-CHECKLIST.md` - the truncated name
`1985471` retracted, which has never been a file. Measured over
`docs/briefs`: the loose recipe gave 27 names, `REF` gave 26, and the
one name between them was that phantom. A reader following the
paragraph that exists *so nobody has to trust this file* got 27
against the gate's 26 and would read the gap as a gate MISS.

That was one edge of three. The same hunk had already fixed the
recipe's DIRECTORY edge (`docs/briefs/*.md` -> `docs/briefs`, because
the glob stops at the top level and `cited()` does not) and left the
LEFT edge loose; the FILE-TYPE edge was loose too, since `grep -r`
reads every file while `cited()` reads `*.md` only.

**SO THE SELECTOR IS NOW WRITTEN ONCE.** `BOUNDARY` and `NAME` below
are shared: `REF` is composed from them and so is `RECIPE`. There is
no second pattern left to drift.

**WHAT THE RECIPE STILL CHECKS, HONESTLY.** It no longer checks the
SELECTOR independently - by construction it cannot, and that is the
point, because a second hand-written selector is what published a false
finding. What it still checks is everything AROUND the selector, with a
standard tool and a traversal this file does not control: that
`cited()` walks the directory the recipe walks, that it opens the files
the recipe opens, and that the count this gate prints is the count of
that population. Those are the parts that were wrong in `1985471`'s
neighbourhood twice, and a `grep` still falsifies them.
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRIEFS = ROOT / "docs/briefs"
RECORD = ROOT / "docs/reviews/brief-report-refs-known-missing.txt"

# --briefs/--record/--tracked exist so the CONTROLS can point this at
# fixtures rather than mutating the real tree to watch a gate fail. CI
# runs it BARE, which is the real container - a control needing a flag
# CI does not pass asks a different question from the one CI asks, so
# the defaults are not conveniences, they ARE the gate.

# The KIND is a report the briefs treat as a deliverable: a review, a
# worklog or a findings document. Matched by NAME, not by directory, so
# a citation that omits the path is still a citation.
#
# THE LEFT BOUNDARY IS LOAD-BEARING AND ITS ABSENCE PUBLISHED A FALSE
# FINDING. Without `(?<![A-Za-z0-9._-])` this matches the TAIL of a
# longer name: `docs/CODE-REVIEW-CHECKLIST.md`, which exists and is
# cited by two briefs, was reported as `REVIEW-CHECKLIST.md`, which
# never has. I put that in a commit message and told another agent, who
# then searched four places for a file whose real name I had truncated
# and correctly found nothing - confirming my false finding rather than
# catching it, because we were both searching for the string my
# instrument produced. An anchor is not decoration; a pattern with a
# free left edge selects for names it was never shown.
BOUNDARY = r"(?<![A-Za-z0-9._-])"
NAME = r"(?:REVIEW|WORKLOG|FINDINGS)-[A-Za-z0-9._-]+\.md"
REF = re.compile(BOUNDARY + r"(docs/(?:reviews|worklogs)/)?" + f"({NAME})")

# THE PUBLISHED RECIPE IS COMPOSED FROM THE SAME TWO STRINGS `REF` IS,
# so it cannot say something different from the gate. It used to be
# typed out a second time and it drifted on two edges at once - the
# module docstring above records which, and what a recipe that shares
# the selector is still good for.
#
# `-P`, not `-E`: the lookbehind is PCRE and is NOT optional. Without it
# this returns `REVIEW-CHECKLIST.md`, the name `1985471` retracted.
# `--include='*.md'`: `cited()` reads `*.md`, and `grep -r` reads every
# file. Today `docs/briefs` holds 83 files and all 83 are `.md`, so the
# flag changes nothing NOW - it changes what happens the first time
# somebody drops a `.txt` in there, which is the same reason `rglob`
# replaced `glob`. Arm A25 is the one that would notice.
RECIPE = "grep -rhoP --include='*.md' '" + BOUNDARY + NAME + "' {briefs} | sort -u"


def tracked_index(listing: Path | None = None) -> tuple[set[str], set[str]] | None:
    """(tracked paths, tracked basenames), or None if git is unreadable.

    BOTH are returned because a citation naming a PATH is a stronger
    claim than one naming a file, and the gate was answering the weaker
    question for every citation - including the 20 of 22 that had said
    exactly where the file lives.

    None and empty must stay distinguishable: an empty set would make
    every reference dangling and the report would be spectacular and
    wrong. R18-M1 measured that exact shape one file over.
    """
    if listing is not None:
        if not listing.exists():
            return None
        raw = listing.read_text().split("\n")
    else:
        try:
            out = subprocess.run(
                ["git", "-C", str(ROOT), "ls-files", "-z"],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        raw = out.stdout.split("\0")
    paths = {p for p in raw if p.strip()}
    return paths, {p.rsplit("/", 1)[-1] for p in paths}


WELL_FORMED = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+\S")


def read_record(record: Path) -> tuple[dict[str, str], list[str]]:
    """Map each recorded name to its reason; list the MALFORMED lines.

    A LINE WITH NO REASON WAS ACCEPTED SILENTLY, in a file whose own
    header says "Recording a line is NOT a waiver". `partition("  ")` on
    a bare `REVIEW-X.md` returns `("REVIEW-X.md", "", "")`: the name was
    recorded, the reason was empty, and nothing looked at it. A bare
    name IS a waiver: it suppresses the error and argues nothing.
    Measured before the fix: a record holding only the bare name
    `REVIEW-ABSENT.md` exited 0.

    THE DATE IS NOT A SECOND GATE, IT IS THE AGE MADE VISIBLE. Nothing
    here expires a line on a timer, deliberately: a check that goes red
    on a schedule is red by construction and gets switched off. The date
    is required so the summary can print how old each excuse is - the
    fact a human needs, and the one the line did not carry.

    A SINGLE-SPACE separator was already safe and still is: it makes the
    whole line the NAME, which then matches no citation and trips two
    loud branches. Only the no-reason form was silent, so only it was
    the defect.
    """
    if not record.exists():
        return {}, []
    out: dict[str, str] = {}
    malformed: list[str] = []
    for n, line in enumerate(record.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, reason = line.partition("  ")
        reason = reason.strip()
        if not WELL_FORMED.match(reason):
            malformed.append(f"line {n}: {line}")
        out[name.strip()] = reason
    return out, malformed


def cited(briefs: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(basename -> citing briefs, basename -> the PATHS they wrote).

    `rglob`, not `glob`: a brief filed one directory down was invisible,
    which is how a gate quietly stops covering things. There are no
    subdirectories under docs/briefs today, so this changes NOTHING
    now - it changes what happens the first time somebody makes one.
    """
    refs: dict[str, set[str]] = {}
    paths: dict[str, set[str]] = {}
    for p in sorted(briefs.rglob("*.md")):
        for m in REF.finditer(p.read_text()):
            refs.setdefault(m.group(2), set()).add(p.name)
            if m.group(1):
                paths.setdefault(m.group(2), set()).add(m.group(1) + m.group(2))
    return refs, paths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--briefs", type=Path, default=BRIEFS)
    ap.add_argument("--record", type=Path, default=RECORD)
    ap.add_argument("--tracked", type=Path, default=None)
    ap.add_argument(
        "--recipe",
        action="store_true",
        help="print the shell re-derivation recipe for --briefs and exit",
    )
    ap.add_argument(
        "--list-names",
        action="store_true",
        help="print the gate's own population, one name per line, and exit",
    )
    args = ap.parse_args()

    # A MISSING BRIEFS DIRECTORY IS A BROKEN INSTRUMENT, NOT AN EMPTY
    # ONE. `rglob` on a path that does not exist returns empty WITHOUT
    # erroring, so `--briefs /nonexistent` would report a perfect result
    # over a population of zero - indistinguishable from a clean tree.
    # `suborch-199` hit exactly that on itself: a bad extraction gave
    # "Briefs scanned: 0 ... rc=0".
    #
    # THIS FILE ALREADY MADE THIS DISTINCTION ONE COLUMN OVER.
    # `tracked_index` returns None for unreadable and [] for empty, and
    # the caller below refuses on None. The same author, in the same
    # file, drew the line for one input and not the other - and the one
    # left undrawn is on the CONTROLS' path, which is the code that
    # proves the gate works. A gate that prints a SUCCESS IT HAS NOT
    # EARNED is worse than one that prints a failure nobody reads.
    if not args.briefs.is_dir():
        print(f"::error::{args.briefs} is not a directory, so NOTHING was")
        print("checked. This is a refusal, not a pass - an empty scan over")
        print("a path that does not exist reads exactly like a clean tree.")
        return 2

    # --recipe and --list-names are BELOW the missing-directory refusal
    # on purpose: a recipe pointed at a path that does not exist, and an
    # empty population read off one, are both the clean-zero this file
    # already refuses once. They are ABOVE `tracked_index` because
    # neither needs git, and refusing them when the index is unreadable
    # would make the controls depend on a thing they are not testing.
    if args.recipe:
        print(RECIPE.format(briefs=shlex.quote(str(args.briefs))))
        return 0

    if args.list_names:
        for n in sorted(cited(args.briefs)[0]):
            print(n)
        return 0

    index = tracked_index(args.tracked)
    if index is None:
        print("::error::could not read `git ls-files`, so NOTHING was checked.")
        print("This is a refusal, not a pass - an unreadable index would")
        print("otherwise make every reference look dangling.")
        return 2
    tracked_paths, names = index

    refs, cited_paths = cited(args.briefs)
    record, malformed = read_record(args.record)

    # A MALFORMED RECORD IS A BROKEN INSTRUMENT, NOT A FAILING SUBJECT.
    # Exit 2 for the same reason an unreadable index does: the gate
    # cannot say anything about the briefs until its own record parses.
    if malformed:
        print("::error::A RECORDED LINE IS NOT WELL FORMED, so NOTHING was checked.")
        for m in malformed:
            print(f"  {m}")
        print("Every line must read:  <basename>  <ISO date> <reason>")
        print("A name with no reason is a waiver, and that file's own")
        print("header says recording a line is NOT a waiver. The date is")
        print("there so the summary can print the age of the excuse.")
        return 2

    dangling = {n: s for n, s in refs.items() if n not in names}

    # THE PATH A BRIEF WROTE IS A CLAIM, AND IT IS MECHANICAL TO CHECK.
    # Not recordable on purpose: unlike a missing report, a file in the
    # wrong place is fixed by correcting one of the two, never excused.
    misplaced = {
        n: sorted(c for c in cp if c not in tracked_paths)
        for n, cp in sorted(cited_paths.items())
        if n in names and any(c not in tracked_paths for c in cp)
    }
    unrecorded = sorted(set(dangling) - set(record))
    resolved = sorted(n for n in record if n in names)
    unreferenced = sorted(n for n in record if n not in refs)

    print(f"Briefs scanned:            {len(list(args.briefs.rglob('*.md')))}")
    print(f"Report names cited:        {len(refs)}")
    print(f"Cited but not in the repo: {len(dangling)}")
    print(f"Cited at the wrong path:   {len(misplaced)}")
    print(f"Recorded as known-missing: {len(record)}")
    # THE DISPLAY MUST NOT ASSUME THE REFUSAL ABOVE RAN. It wrote
    # `reason.split()[0]` and raised IndexError on an empty reason - the
    # exact input #199 is about. A16 could not see it (the refusal fires
    # first) and A19, which amputates the refusal, did: the crash was
    # rc=1 where the pre-fix behaviour is rc=0. A guard that only holds
    # while its neighbour holds is not a guard.
    for n, reason in sorted(record.items()):
        stamp = reason.split(maxsplit=1)
        today = datetime.now(tz=UTC).date()
        try:
            added = date.fromisoformat(stamp[0] if stamp else "")
        except ValueError:
            continue
        print(f"  recorded {(today - added).days:>4}d ago  {n}")

    failed = False

    if unrecorded:
        failed = True
        print()
        print("::error::A BRIEF CITES A REPORT THAT EXISTS NOWHERE IN THE REPO.")
        for n in unrecorded:
            print(f"  {n}   cited by {', '.join(sorted(dangling[n]))}")
        print("Either commit the report, or record it in")
        print(f"  {args.record}")
        print("with the reason it cannot be committed. Recording it is not a")
        print("waiver - it is a statement that the loss is known and accepted.")

    if misplaced:
        failed = True
        print()
        print("::error::A BRIEF CITES A REPORT AT A PATH IT IS NOT AT.")
        for n, bad in misplaced.items():
            real = sorted(t for t in tracked_paths if t.rsplit("/", 1)[-1] == n)
            for c in bad:
                print(f"  {c}   is actually at {', '.join(real)}")
        print("Fix the brief, or move the report. This is not recordable:")
        print("the file exists, so there is nothing to excuse.")

    if resolved:
        failed = True
        print()
        print("::error::A RECORDED ENTRY NOW RESOLVES, so the record is stale.")
        for n in resolved:
            print(f"  {n}   is tracked now; delete its line")
        print("An excuse list that only grows stops being read. It must")
        print("shrink when the world does.")

    if unreferenced:
        failed = True
        print()
        print("::error::A RECORDED ENTRY IS NO LONGER CITED BY ANY BRIEF.")
        for n in unreferenced:
            print(f"  {n}   nothing cites it; delete its line")

    if failed:
        return 1

    print()
    print("Every report a brief cites is committed, or recorded as lost.")
    print("NOTE: this proves the file EXISTS, and - where the brief wrote a")
    print("path - that it is THERE. It still cannot prove the file is the")
    print("report the brief meant: that is identity, and a citation is a name.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
