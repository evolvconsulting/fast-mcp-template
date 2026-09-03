#!/usr/bin/env python3
"""Report the commits on the trunk that NO review round has covered.

    python3 docs/reviews/check-review-coverage.py [--ref origin/main]

**WHY THIS EXISTS.** On 2026-09-01 I found 45 consecutive commits that
no review round had examined - 133 files, +7787/-2561 - including nine
ADRs applied to the frozen design, a tenth applied after it, and the
fixes an earlier round had itself demanded. I found them by accident,
while checking whether a filename collided.

**IT WAS NOT AN OVERSIGHT, IT WAS THE MODEL.** Every round through R8
reviewed a UNIT - `REVIEW-R4` says *"U5, search_jobs"*. R9 was the first
to review a RANGE. So fixes, chores, checkers, CI and ADR application
were never in any round's scope by construction. Of those 45 commits,
zero mention a unit; all 18 merges are `fix/*` or `chore/*`. **The
least-reviewed code here is the code that does the reviewing.**

**WHY IT REFUSES TO GUESS.** Deriving a round's coverage from whatever
SHA its document happens to cite would **manufacture coverage for code
nobody read** and certify it forever - strictly worse than the gap,
because an absence you can see beats a false presence you cannot.

## PATHS, and why a range alone was not enough

Two reviewers found the same hole independently. A round is dispatched
over a commit range AND a path filter: R11 took `src tests docs/adr
docs/DESIGN.md`, R12 took `docs/reviews scripts .github`, over the SAME
45 commits. Union the ranges and ignore the paths, and **either
declaration alone makes all 45 read as covered** while half the files
were never opened. That is manufactured coverage arriving from the
AUTHOR's side rather than the inferrer's - the very thing the paragraph
above refuses.

So a declaration may name the paths it read:

    <!-- REVIEW-COVERS: f699f74..dad014e PATHS: docs/reviews scripts -->
    <!-- REVIEW-COVERS: 8695101..f699f74 -->        (no PATHS = all)

A commit counts as covered only when **every file it touches** is
claimed by some round whose range contains it. Two path-split rounds
compose; either alone leaves the commit PARTIALLY covered, reported
separately from untouched - a half-read commit and an unread one are
different facts and must not print the same.

Omitting PATHS still means the whole tree, so older declarations keep
working and the broad claim stays the default.

## THE RANGE IS NOT ENOUGH FOR `NONE` EITHER (R17-H1)

The paragraph above closed the hole for `covered` and left it open for
`NONE`, which is the number every handoff quotes as *"nobody has looked
at these"*. Until #168, `NONE` was decided by RANGE MEMBERSHIP ALONE and
the path filter ran afterwards only to pick `PARTIAL`. So a declaration
with a WIDE range and a NARROW path list moved commits out of `NONE`
without reading them: R17 measured one declaration over the whole
container claiming a single seven-character file taking `COVERED BY
NOTHING` **26 -> 0** and `PARTIAL` 42 -> 62.

**This is R12-H3 one column over** - that metric improved when you
DELETED a declaration, this one improved when you ADDED one that read
nothing. So a round now reaches a commit only if it claims **at least
one non-record file the commit actually touches**.

**THE HOLE COULD NOT SHRINK THE BACKLOG, AND CLOSING IT DOES NOT GROW
IT.** A commit whose files nobody claims was ALREADY outstanding - it
was recorded `PARTIAL` rather than `NONE`. Measured at `22c9873`, this
rule alone leaves the outstanding SET identical at 53 and moves 28
commits `PARTIAL -> NONE`, none the other way. What was manipulable was
the KIND, which is the half of the record a handoff quotes. Anyone
expecting a fix here to raise the backlog COUNT is looking one column
over.

The count does move, DOWNWARDS by 5, and for a different reason: the
content ruling below takes five clean merges out of the question
entirely. 53 -> 48 outstanding, `NONE` 17 -> 40.

**A COMMIT WITH NOTHING IN IT TO READ IS DECIDED BY ITS CONTENT, NEVER
BY A DECLARATION.** A clean merge's `--cc` diff is empty and its content
is scored at the branch commits (REVIEW-R16 section 3 and REVIEW-151-R1,
both of which raised this and WITHDREW it); a record-only commit touches
only `RECORD_PATHS`. Requiring the range for these would leave R17-H1
alive at reduced scale - measured, a planted full-range declaration
still cleared five of them - so the content test runs FIRST.

## Defects review R12 found in this file, and the fix for each

**THE CONTAINER BASE IS FIXED, NOT DERIVED (R12-H3).** It was
`min(declared bases)`, which made the metric MANIPULABLE IN THE WRONG
DIRECTION: deleting a declaration moved the base forward and dropped
`COVERED BY NOTHING` from 59 to 2. A gate whose number IMPROVES when you
remove a declaration teaches the behaviour it exists to prevent.

**THE TRUNK IS A NAMED REF, NOT `HEAD` (R12-H3, second half).** Under
`actions/checkout` HEAD is the PR's merge commit, so wiring it as-is
would turn every pull request red for its own not-yet-trunk commits.

**THE POPULATION IS A REGEX OVER EVERY `.md` HERE (R12-M4).** The glob
`*REVIEW-R*.md` silently missed `REVIEW-CODE-R2.md` - a real round, in
no bucket at all. Third pattern-shaped population loss in one day, in
the file written to enforce container thinking.

**AN EXEMPTION NEEDS A NON-EMPTY REASON (R12-M5), A GIT FAILURE EXITS 3
(R12-L3), AND TWO DECLARATIONS REFUSE (R12-N2).**

## IT IS A RATCHET, NOT A DEMAND FOR ZERO (#151)

This used to return 1 whenever any trunk commit was uncovered. **On a
trunk anyone is still committing to that is red by construction** -
every merge adds commits no round has yet examined - and a gate that
can never be green gets switched off, which is how 119 consecutive CI
failures went unread here once already.

So it enforces a recorded SET, `review-coverage-backlog.txt`, and fails
on any DIFFERENCE from what it measures. The question becomes *"did the
unread set change without anyone saying so?"*, which has an attainable
yes. A HOLDING RATCHET IS NOT FULL COVERAGE and the output says so.

**A SET, NOT A COUNT**, because a count lets one commit entering and
another clearing cancel to zero. **BOTH KINDS**, because ratcheting
`NONE` alone leaves the 39 `PARTIAL` commits red by construction - the
same defect, one column over, which is how the first version of this
change was written. **NO `--write-backlog`**, because a gate that
regenerates its own baseline certifies whatever it just saw.

Pinned by `docs/reviews/probe-coverage-ratchet.py`, 10 arms, none of
which modifies the tree - hence `--backlog` and `--reviews`.

**THE RATCHET HAS TWO INPUTS AND MY FIRST EIGHT ARMS PERTURBED ONE
(R1-H1).** The recorded side is the backlog; the MEASURED side is
whatever `docs/reviews/*.md` declares. Every arm poked the backlog, so a
FABRICATED DECLARATION was unguarded: one new file holding a single
`REVIEW-COVERS` line over the whole range, plus an emptied backlog,
took 58 to 0 at exit 0. The PLANT arm closes it. A control that
perturbs only the input its author was thinking about is the shape this
directory keeps re-finding.

**THE LAG IS REAL, AND IT IS N+1, NOT ONE (R1-H2).** A commit cannot
record its own sha, so a merge's commits enter the backlog in the NEXT
change. I first wrote that this makes it "red for exactly one commit
every time". **That was wrong, and wrong in this very tree**:
`rev-list` enumerates every commit a push ADDS, so merging N commits
leaves N+1 outstanding. Measured the moment the ref was refreshed: 5.

Run against `origin/main` from a pull request and that is what you
want - the PR's own commits are not on the trunk yet, so the gate is
green, and whoever opens the next PR pastes the lines printed for the
merge before it.

**AND IT CAN MOVE FORWARD UNDER YOU, WHICH IS THE OPPOSITE SHAPE AND
WAS RECORDED NOWHERE.** R16 ran one command minutes apart and got 287
trunk commits / 60 merges, then 300 / 62; two of its measurements
disagreed until it found the cause. Tier 0 and R16 also reported 13 and
15 for "the same" set - `ccbdaae..6e07131` against `ccbdaae..2d886a4`.
Both arithmetics were right and only the POPULATION differed, which is
the same shape as 80-vs-78 and 389-vs-115 elsewhere in this repository.
**A long-running reader must PIN a sha, say which, and re-derive at the
end** - the printed `Trunk ref: <ref> = <sha>` line exists so that two
reports can be compared at all.

**AND THE REF IT READS CAN BE STALE (found by the same measurement).**
`origin/main` is a LOCAL remote-tracking ref. Mine sat five commits
behind a trunk I had already pushed, so the whole backlog was measured
against a tree nobody was on, and it said "58 recorded, 58 measured,
exit 0" without ever naming which ref that was. The resolved sha is now
printed beside the ref on every run. Under `actions/checkout` the ref is
fetched fresh, so this bites locally, not in CI - which is exactly the
kind of difference this project keeps finding out the hard way.

**WHAT IT STILL CANNOT DO.** It checks that a commit's files fall inside
some round's declared range and paths. It cannot check the round READ
them. A declaration is a claim by its author; this only makes the claim
explicit, total, and composable.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
REVIEWS = ROOT / "docs" / "reviews"

#: The commit from which review coverage is claimed. **A CONSTANT, never
#: derived from the declarations** - see R12-H3. Moving it FORWARD hides
#: commits, so it changes only with a recorded reason.
CONTAINER_BASE = "8695101"

IS_REVIEW = re.compile(r"REVIEW.*-R\d+", re.IGNORECASE)
NOT_A_COMMIT_REVIEW = re.compile(r"^PLAN-REVIEW|REVIEW$", re.IGNORECASE)

DECLARATION = re.compile(
    r"^<!--\s*REVIEW-COVERS:\s*"
    r"(?P<base>[0-9a-f]{7,40})\.\.(?P<head>[0-9a-f]{7,40})"
    r"(?:\s+PATHS:\s*(?P<paths>[^>]*?))?\s*-->\s*$",
    re.MULTILINE,
)

#: Rounds that reviewed a UNIT at a tree state and have no range to
#: recover. **A blank reason is not an exemption** (R12-M5).
UNDECLARED_BY_HISTORY: dict[str, str] = {
    "REVIEW-CODE-R2.md": "reviewed U1/U3/U4 at a pinned SHA, not a range",
    "REVIEW-R3.md": "reviewed 'the seven merged units', not a range",
    "REVIEW-R4.md": "reviewed U5 at 555bad6, a tree state, not a range",
    "REVIEW-R5.md": "reviewed U6 at d0abd10, a tree state, not a range",
    "REVIEW-R6.md": "reviewed U7 at ec38835, a tree state, not a range",
    "REVIEW-R7.md": "reviewed U8/U9/U12/U10 at bc0f958, a tree state",
    "REVIEW-R8.md": "reviewed U14 at 2c6ff19, a tree state, not a range",
}
assert all(v.strip() for v in UNDECLARED_BY_HISTORY.values()), (
    "a blank reason is not an exemption"
)


#: Paths that are RECORDS OF WORK rather than the work, each with the
#: reason. A record is an account of something that already happened;
#: the thing it accounts for is reviewed where it lives. **A bare path
#: is refused: the reason IS the exemption**, the same shape every other
#: exemption in `docs/reviews/` uses.
#:
#: THIS IS A RULING, NOT A CONVENIENCE, and the line it draws is
#: narrow. `docs/briefs/` is deliberately NOT here: a brief INSTRUCTS an
#: agent and has carried substantive rulings (ADR-BATCH.md), so a wrong
#: brief produces wrong work rather than merely misdescribing it. Nor
#: are `pyproject.toml`, `.env.example`, `.pre-commit-config.yaml`,
#: `server.json` or `README.md` - dependencies, secret-class values,
#: hook config and the published manifest are load-bearing and stay in
#: scope.
RECORD_PATHS: dict[str, str] = {
    "CHANGELOG.md": (
        "a dated account of changes that are themselves reviewed where "
        "they live. Reviewing it means re-reading a summary of reviewed "
        "code, which is coverage theatre rather than coverage."
    ),
    "docs/worklogs": (
        "reports of measurements already made. The measurement's SUBJECT "
        "is in src/, tests/ or scripts/ and is covered there; the report "
        "is the record that it happened."
    ),
    "docs/reviews/review-coverage-backlog.txt": (
        "THIS GATE'S OWN LEDGER, and leaving it out made the ratchet FEED "
        "ITSELF (R18-M5). A top-up commit touches this file and nothing "
        "else, so it became an uncovered trunk commit that the NEXT "
        "top-up had to record - e6333ef recorded 3987403, 39bfab8 "
        "recorded e6333ef, a36883f recorded 39bfab8, e845839 recorded "
        "a36883f, and e845839 was outstanding when R18 arrived. Four "
        "commits of pure self-reference. Its content is DERIVED from "
        "what this checker measures and its shape is gated here by the "
        "SUBJECT comparison, so reading it as a review is re-reading a "
        "list the tool prints. A commit that touches this file AND a "
        "real one is still scored on the real one: `substantive` drops "
        "record paths and only an EMPTY remainder skips."
    ),
    "docs/archive": (
        "the retirement shelf. A file arrives here ONLY by `git mv` from "
        "`docs/reviews/` or `docs/worklogs/`, both already records, and "
        "only after nothing in the tracked tree names it - so its "
        "exemption is inherited, not new. THE MOVE ITSELF IS INVISIBLE "
        "TO THIS GATE and that is worth stating, because it looks like "
        "the kind of change that would break it: this checker reads the "
        "file lists git recorded AT each commit, so a path retired today "
        "leaves every historical commit reading exactly as before. "
        "Measured at the retirement commit: the whole report was "
        "byte-identical except `Excluded, with a reason: 84 -> 63`. This "
        "row is FORWARD-looking - it keeps a future commit that touches "
        "only the shelf from entering the backlog as if it were work."
    ),
    "docs/plans": (
        "ruled a RECORD at 0ec4c85 (task #111) - not repointed, not "
        "rewritten, and the SHA that makes that safe is guarded. A record "
        "that must not change cannot meaningfully be re-reviewed."
    ),
}
assert all(v.strip() for v in RECORD_PATHS.values()), (
    "a blank reason is not an exemption"
)


def is_record(path: str) -> bool:
    """Is this path a record of work rather than the work itself?"""
    return any(path == p or path.startswith(p.rstrip("/") + "/") for p in RECORD_PATHS)


#: The RATCHET. Task #151 ruled that this gate cannot demand
#: `COVERED BY NOTHING == 0` on a trunk anyone is still committing to:
#: every merge adds commits that no round has yet examined, so a
#: zero-demanding gate is red by construction and gets switched off,
#: which is how 119 consecutive failures went unread here once already.
#:
#: So the gate checks a SET, not a count. This file records exactly
#: which commits are known to be uncovered. The measured set must EQUAL
#: it: a commit that entered the backlog unrecorded fails, and so does
#: one still recorded after a round covered it. A count would let two
#: errors in opposite directions cancel; a set cannot.
#:
#: **THERE IS DELIBERATELY NO `--write-backlog`.** A gate that rewrites
#: the baseline it then checks passes for free, which is how a secret
#: scanner here spent an hour certifying its own output. The exact lines
#: to paste are printed instead; adding them is a human act, recorded in
#: a diff, with a commit message that has to say why the backlog grew.
BACKLOG = REVIEWS / "review-coverage-backlog.txt"


#: The two ways a commit can be outstanding, and they are NOT the same
#: fact: NONE means no round's range contains it, PARTIAL means a round
#: claimed the range but not every file it touches. A commit moving
#: NONE -> PARTIAL is real progress, so the backlog records the kind and
#: the ratchet notices the move. Collapsing them to one count would let
#: a half-read commit and an unread one print identically, which is the
#: distinction this checker was written to keep.
KINDS = ("NONE", "PARTIAL")


def read_backlog(path: pathlib.Path) -> dict[str, tuple[str, str]]:
    """Recorded outstanding commits: short sha -> (kind, subject).

    Missing file is NOT an empty backlog - an absent baseline that reads
    as "nothing is outstanding" is a false green. It exits 3, the code
    reserved for a broken instrument.
    """
    if not path.exists():
        print(f"{path} is missing. An absent backlog is not an empty")
        print("one; it would report the whole backlog as new. Exit 3.")
        raise SystemExit(3)
    recorded: dict[str, tuple[str, str]] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        sha, _, rest = line.partition(" ")
        kind, _, subject = rest.strip().partition(" ")
        if kind not in KINDS:
            print(f"{path.name}:{number} has kind {kind!r}, not one of")
            print(f"{KINDS}. A malformed line is a broken instrument, and")
            print("skipping it would silently shrink the baseline. Exit 3.")
            raise SystemExit(3)
        if sha in recorded:
            print(f"{path.name}:{number} repeats {sha}. Two lines for one")
            print("commit make the recorded count disagree with the recorded")
            print("SET, and only one of them can be right. Exit 3.")
            raise SystemExit(3)
        recorded[sha] = (kind, subject.strip())
    return recorded


class Round:
    """One round's claim: which commits, and which paths it read."""

    def __init__(self, name: str, commits: set[str], paths: list[str]) -> None:
        """Empty `paths` means the whole tree - the broad default."""
        self.name = name
        self.commits = commits
        #: Empty means the WHOLE TREE - the broad, honest default.
        self.paths = paths

    def claims(self, path: str) -> bool:
        """Does this round's path filter cover `path`?"""
        if not self.paths:
            return True
        return any(
            path == claim or path.startswith(claim.rstrip("/") + "/")
            for claim in self.paths
        )


def git(*args: str) -> str:
    """Run git; return stdout, or exit 3.

    A broken instrument is not a finding and must not share an exit
    code with one (R12-L3).
    """
    done = subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True
    )
    if done.returncode != 0:
        print(f"git {' '.join(args)} failed: {done.stderr.strip()}")
        print("This is a BROKEN INSTRUMENT, not a finding. Exit 3.")
        raise SystemExit(3)
    return done.stdout.strip()


def review_documents(reviews: pathlib.Path) -> tuple[list[pathlib.Path], list[str]]:
    """The code-review documents, and what was excluded and why."""
    kept: list[pathlib.Path] = []
    skipped: list[str] = []
    for path in sorted(reviews.glob("*.md")):
        if not IS_REVIEW.search(path.stem):
            skipped.append(f"{path.name} (no round number)")
        elif NOT_A_COMMIT_REVIEW.search(path.stem):
            skipped.append(f"{path.name} (reviews a document, not commits)")
        else:
            kept.append(path)
    return kept, skipped


def declared_rounds(docs: list[pathlib.Path]) -> tuple[list[Round], list[str]]:
    """Each document's claim, and the documents declaring none."""
    rounds: list[Round] = []
    undeclared: list[str] = []
    for path in docs:
        found = DECLARATION.findall(path.read_text(encoding="utf-8"))
        if len(found) > 1:
            print(f"\n{path.name} carries {len(found)} REVIEW-COVERS lines.")
            print("Only the first would be read. Refusing rather than")
            print("picking one. Exit 2.")
            raise SystemExit(2)
        if not found:
            undeclared.append(path.name)
            continue
        base, head, raw_paths = found[0]
        commits = set(git("rev-list", f"{base}..{head}").split())
        paths = raw_paths.split()
        rounds.append(Round(path.name, commits, paths))
        claim = " ".join(paths) if paths else "(whole tree)"
        print(f"  DECLARED  {path.name}: {base}..{head}")
        print(f"            {len(commits)} commits, paths: {claim}")
    return rounds, undeclared


def main() -> int:
    parser = argparse.ArgumentParser(description="review coverage")
    parser.add_argument(
        "--ref",
        # origin/main, NOT main (R15-H1). R12-H3 moved this off HEAD
        # for the right reason - under actions/checkout, HEAD is the
        # PR's merge commit - and stopped one step short. That action
        # also leaves a DETACHED HEAD and creates NO local `main`.
        #
        # Reproduced in an init+fetch+detach clone, the shape the
        # action actually leaves: `main` does not resolve, `origin/main`
        # does, and this checker then exits 3, the code it reserves for
        # a BROKEN INSTRUMENT. Wiring the gate with the old default
        # would have failed every PR with "broken instrument" and
        # taught nobody anything. The docstring has said origin/main
        # since this file was written; only the default disagreed.
        #
        # Pinned by docs/reviews/probe-coverage-ref-resolves.py, whose
        # first version was VACUOUS - it ran the source tree's copy
        # with cwd set to the clone, and this checker derives its repo
        # from __file__, not the working directory.
        default="origin/main",
        help="trunk ref; never HEAD - under checkout that is a merge commit",
    )
    parser.add_argument(
        "--backlog",
        type=pathlib.Path,
        default=BACKLOG,
        # A CONTROL MUST NOT MUTATE THE TREE TO TEST THIS. Without this
        # flag the only way to prove the ratchet fires is to edit the
        # real backlog and put it back, and a harness killed mid-row
        # then leaves the edit behind for the next run to blame on
        # someone else (#131, #146 - and I stranded two plant files
        # that way myself tonight).
        help="the backlog file to enforce; for controls, never the tree's",
    )
    parser.add_argument(
        "--reviews",
        type=pathlib.Path,
        default=REVIEWS,
        # THE OTHER INPUT (R1-H1). The backlog is the recorded
        # side; this directory is the MEASURED side, and my 8 arms
        # perturbed only the former, so a FABRICATED DECLARATION was
        # unguarded. A control needs somewhere that is not the tree to
        # plant one.
        help="the directory of review documents; for controls, a copy",
    )
    args = parser.parse_args()

    resolved = git("rev-parse", "--short=7", args.ref)
    print(f"Trunk ref: {args.ref} = {resolved}")
    if args.reviews != REVIEWS:
        print(f"Review documents read from {args.reviews} (NOT the tree)")
    docs, skipped = review_documents(args.reviews)
    print(f"Review documents in the population: {len(docs)}")
    print(f"Excluded, with a reason: {len(skipped)}")
    if not docs:
        print("MATCHED ZERO review documents. An empty population reports")
        print("full coverage, which would mean nothing. Exit 2.")
        return 2

    rounds, undeclared = declared_rounds(docs)

    unexplained: list[str] = []
    for name in sorted(undeclared):
        reason = UNDECLARED_BY_HISTORY.get(name, "").strip()
        if reason:
            print(f"  HISTORIC  {name}: no range - {reason}")
        else:
            unexplained.append(name)
            print(f"  UNDECLARED {name}: no REVIEW-COVERS, and no reason")

    if not rounds:
        print("\nNo document declares a range, so nothing can be checked.")
        return 2

    trunk = git("rev-list", f"{CONTAINER_BASE}..{args.ref}").split()
    untouched: list[str] = []
    partial: list[tuple[str, list[str]]] = []
    records_skipped = 0
    nothing_to_read = 0
    for sha in trunk:
        files = git("show", "--name-only", "--pretty=format:", sha).split()
        in_range = [r for r in rounds if sha in r.commits]
        # The record touches a covering round did not have to claim.
        # Counted against the IN-RANGE set, which is what the printed
        # number meant before this rule existed.
        if in_range:
            records_skipped += sum(
                1
                for f in files
                if not any(r.claims(f) for r in in_range) and is_record(f)
            )
        substantive = [f for f in files if not is_record(f)]
        if not substantive:
            # NOTHING TO READ, AND THAT IS DECIDED BY THE COMMIT,
            # NOT BY ANY DECLARATION - which is why this test comes
            # FIRST, ahead of the range. Two shapes land here, both
            # SETTLED:
            #
            # A CLEAN MERGE prints no files, because `git show
            # --name-only` defaults to `--cc` and a clean merge has no
            # merge-unique content. Its content is its branch commits,
            # which `rev-list` enumerates and this loop scores
            # INDIVIDUALLY. REVIEW-151-R1 (its own-mistakes section) and
            # REVIEW-R16 section 3 each wrote this up as a defect and
            # each WITHDREW it; R16 settled it over the container -
            # for all 60 merges in 8695101..ccbdaae, every file in the
            # first-parent diff is either merge-unique (so `--cc` prints
            # it, and it is scored here) or carried by a branch commit
            # that is itself in the rev-list. Unaccounted files: 0. An
            # EVIL merge has merge-unique files, so `--cc` prints them,
            # `substantive` is non-empty, and it is scored below like
            # anything else.
            #
            # A RECORD-ONLY COMMIT touches only RECORD_PATHS, whose
            # ruling already says the work is reviewed where it lives.
            #
            # **WHY NOT REQUIRE THE RANGE ANYWAY.** My first version of
            # this fix did, and the WIDTH arm caught it: with the range
            # still required, a planted full-range declaration claiming
            # ONE file moved five of these commits out of `NONE` while
            # reading nothing - R17-H1 surviving at reduced scale in the
            # fix for R17-H1. A commit with nothing in it to read must
            # not be something a declaration can win. Deciding it on
            # CONTENT takes the surface away entirely: no declaration,
            # of any width, moves these commits in either direction.
            #
            # The other two candidate rulings were REJECTED, measured:
            # scoring them `NONE` moves 89 commits (60 merges + 29
            # record-only, at 22c9873) into a backlog of commits with
            # nothing in them to read, against two rounds' settled
            # findings; leaving the range requirement in place keeps the
            # five-commit hole above.
            nothing_to_read += 1
            continue
        if not in_range:
            untouched.append(sha)
            continue
        claiming = [r for r in in_range if any(r.claims(f) for f in substantive)]
        if not claiming:
            # IN RANGE IS NOT YET COVERAGE (R17-H1). Every file this
            # commit touches falls outside every in-range round's paths,
            # so nobody read it. That is NONE, not PARTIAL: a wide range
            # with a narrow path list must not move a commit out of
            # COVERED BY NOTHING.
            untouched.append(sha)
            continue
        unread = [f for f in substantive if not any(r.claims(f) for r in claiming)]
        if unread:
            partial.append((sha, unread))

    covered = len(trunk) - len(untouched) - len(partial)
    print(f"\nTrunk commits on {args.ref} since {CONTAINER_BASE}: {len(trunk)}")
    print(f"Fully covered - range AND every path: {covered}")
    print(f"PARTIALLY covered - some files claimed by nobody: {len(partial)}")
    print(f"COVERED BY NOTHING: {len(untouched)}")
    # COUNTED, NEVER SILENT. An exemption nobody reports is how a
    # population shrinks without anyone noticing, and this one was added
    # in the same session that found 22 commits reading as fully covered
    # because a path filter went undeclared.
    print(
        f"Record-file touches skipped, across {len(trunk)} trunk commits"
        f" (not the work, an account of it): {records_skipped}"
    )
    # COUNTED, NEVER SILENT, for the same reason the line above is. This
    # is the population the R17-H1 rule does NOT apply to, and a reader
    # is entitled to see how big it is before believing the NONE count.
    print(
        f"Nothing to read - a clean merge's --cc diff is empty and its"
        f" content is scored at the branch commits, or the commit touches"
        f" only RECORD paths: {nothing_to_read}"
    )
    for name, why in sorted(RECORD_PATHS.items()):
        print(f"  RECORD   {name}: {why}")

    # THE RATCHET. Compare SETS of (sha, kind), and say the size of
    # each before printing any sample - an earlier version of this
    # report printed `untouched[:15]` and a reader (me) took 15 for the
    # population while writing a handoff about that exact mistake.
    #
    # PARTIAL is in the ratchet for the same reason NONE is (#151): 39
    # commits are partially covered right now, so a gate that demanded
    # zero of either would be red by construction and would get
    # switched off, which is how 119 consecutive CI failures went
    # unread here once already.
    recorded = read_backlog(args.backlog)
    measured: dict[str, str] = {}
    for sha in untouched:
        measured[git("rev-parse", "--short=7", sha)] = "NONE"
    for sha, _ in partial:
        measured[git("rev-parse", "--short=7", sha)] = "PARTIAL"

    entered = sorted(sha for sha in measured if sha not in recorded)
    cleared = sorted(sha for sha in recorded if sha not in measured)
    moved = sorted(
        sha for sha in measured if sha in recorded and recorded[sha][0] != measured[sha]
    )
    # THE SUBJECT IS CHECKED TOO (R1-M3). It was decoration - recorded,
    # never compared - and a decorative field drifts until someone reads
    # it as evidence. Compared as a PREFIX because the printed lines are
    # truncated to fit; a truncation is not a mismatch.
    mislabelled = sorted(
        sha
        for sha in measured
        if sha in recorded
        and recorded[sha][1]
        and not git("log", "-1", "--format=%s", sha).startswith(recorded[sha][1])
    )

    print(f"\nBacklog recorded in {args.backlog.name}: {len(recorded)}")
    print(f"Backlog measured now: {len(measured)}")
    print(f"ENTERED, unrecorded: {len(entered)}")
    print(f"CLEARED, still recorded: {len(cleared)}")
    print(f"CHANGED KIND: {len(moved)}")
    print(f"SUBJECT disagrees with the commit: {len(mislabelled)}")

    if entered:
        print("\nOutstanding and not in the backlog. Either declare a round")
        print("that covers them, or paste these lines into the backlog in")
        print("the SAME commit that explains why it grew:")
        for sha in entered:
            subject = git("log", "-1", "--format=%s", sha)[:56]
            print(f"  {sha} {measured[sha]} {subject}")
    for sha in cleared:
        kind, subject = recorded[sha]
        print(f"  CLEARED  {sha} {kind} {subject[:52]} - delete this line")
    for sha in moved:
        was, now = recorded[sha][0], measured[sha]
        print(f"  KIND     {sha} recorded {was}, measured {now} - update it")
    for sha in mislabelled:
        actual = git("log", "-1", "--format=%s", sha)
        print(f"  SUBJECT  {sha} recorded as {recorded[sha][1][:40]!r}")
        print(f"           but reads {actual[:40]!r}")

    # THE CAVEAT PRINTS ON EVERY PATH (R1-H1, second half). It used to
    # print only on the failure branch, so the GREEN path emitted the
    # strongest sentence in the file with nothing qualifying it - while
    # the docstring promised the output says so. The line that
    # most needs the caveat is the one saying everything is fine.
    print(
        "\nNOTE: this proves a commit's files fall inside some round's\n"
        "declared range and paths, NOT that the round read them - a\n"
        "declaration is a claim by its author."
    )

    if entered or cleared or moved or mislabelled or unexplained:
        return 1

    if measured:
        print(f"\nThe backlog holds at {len(measured)}, every commit recorded.")
        print("A HOLDING RATCHET IS NOT FULL COVERAGE. It says the unread")
        print("set did not grow and nothing in it went unnoticed.")
    else:
        print(f"\nEvery trunk commit on {args.ref} ({resolved}) falls inside")
        print("a declared round's range and paths. That is what was checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
