#!/usr/bin/env python3
"""Refuse two ADRs with one number, and a gap in the sequence.

    python3 docs/reviews/check-adr-numbers.py

**Written because it happened.** `u10-write` checked `git log --all`
before choosing a number, found 0026 taken and 0027 free, and was
correct at the moment it looked. I created a different 0027 afterwards,
on another branch. **Neither of us did anything wrong and both files
merged cleanly**, because they have different filenames and git has no
opinion about the digits in them.

**A duplicate number is worse than it sounds.** Every inbound reference
- a code comment, a report, a task, a commit message - resolves to
"ADR-0027" and there are now two of them. The reader who follows one
gets a coherent document about the wrong subject, which is the same
failure mode as a citation landing on real prose that is not its
subject, and this project has now recorded that eleven times.

A GAP is also refused, because ADR numbers are cited from code and a
missing number is either a deleted decision - which should be a
superseding ADR, not a hole - or a reference nobody can follow.

**What it cannot do**: it reads filenames. An ADR whose FILENAME says
0028 and whose HEADING says 0027 passes here, so the heading is checked
too - that mismatch is exactly what a renumbering leaves behind when it
is done by `git mv` alone.

**THE INDEX TABLE IS CHECKED IN BOTH DIRECTIONS, and it is here because
it had silently stopped at 0023 with twelve ADRs missing** - including
`0034` and `0035`, which the as-at-acceptance ruling twenty lines above
the table cites BY NUMBER. Nothing regenerated the table, so every ADR
after 0023 landed without one and no gate looked.

Both directions, because the two failures are different:

- a FILE with no ROW is an ADR a reader of the index cannot find;
- a ROW with no FILE is a link that 404s, which is what a rename or a
  withdrawal leaves behind.

A one-directional check passes on half of that, and this repository has
now recorded three separate cases where the direction nobody checked is
the one that broke. `check-row-floor-exactness.py` uses the same
equal-in-both-directions shape for its container-versus-table check.

The table is still hand-maintained; this refuses to let it drift rather
than generating it. A generator would also have to invent the Decision
column, which is prose a human writes.
"""

from __future__ import annotations

import collections
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
ADR_DIR = ROOT / "docs" / "adr"
INDEX = ADR_DIR / "README.md"
FILENAME = re.compile(r"^(\d{4})-[a-z0-9-]+\.md$")
HEADING = re.compile(r"^#\s*ADR-(\d{4})\b")
INDEX_ROW = re.compile(r"^\|\s*\[(\d{4})\]\(([^)]+)\)")


def _index_rows() -> tuple[dict[int, str], str | None]:
    """Every `| [NNNN](file.md) |` row of the index, by number.

    Returns `({}, reason)` when the index cannot be read, so an absent
    or unreadable README is a REFUSAL rather than a clean zero - a
    selector over a path that does not exist exits empty and looks
    identical to a table with no defects.
    """
    if not INDEX.is_file():
        return {}, f"NO INDEX at {INDEX}"
    rows: dict[int, str] = {}
    duplicated: list[int] = []
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        match = INDEX_ROW.match(line)
        if match is None:
            continue
        number = int(match.group(1))
        if number in rows:
            duplicated.append(number)
        rows[number] = match.group(2)
    if not rows:
        return {}, f"{INDEX.name} MATCHED ZERO INDEX ROWS. The selector is broken."
    if duplicated:
        listed = ", ".join(f"{n:04d}" for n in sorted(set(duplicated)))
        return rows, f"{INDEX.name} lists these twice: {listed}"
    return rows, None


def _check_index(numbers: dict[int, list[str]]) -> list[str]:
    """The index and the files must agree, EQUAL IN BOTH DIRECTIONS."""
    rows, reason = _index_rows()
    if reason is not None:
        return [reason]

    problems: list[str] = []
    for number in sorted(set(numbers) - set(rows)):
        problems.append(
            f"NO ROW    {number:04d} - {numbers[number][0]} exists and the index "
            f"does not list it"
        )
    for number in sorted(set(rows) - set(numbers)):
        problems.append(
            f"NO FILE   {number:04d} - the index links `{rows[number]}` and no "
            f"such ADR exists"
        )
    for number in sorted(set(rows) & set(numbers)):
        actual = numbers[number][0]
        if rows[number] != actual:
            problems.append(
                f"BAD LINK  {number:04d} - the index links `{rows[number]}`, the "
                f"file is `{actual}`"
            )
    return problems


def main() -> int:
    if not ADR_DIR.is_dir():
        print(f"NO ADR DIRECTORY at {ADR_DIR}. Exiting 2, not 0.")
        return 2

    numbers: dict[int, list[str]] = collections.defaultdict(list)
    mismatched: list[str] = []
    for path in sorted(ADR_DIR.glob("*.md")):
        match = FILENAME.match(path.name)
        if match is None:
            continue  # README.md and anything else deliberately unnumbered
        number = int(match.group(1))
        numbers[number].append(path.name)

        first = path.read_text(encoding="utf-8").splitlines()[0]
        heading = HEADING.match(first)
        if heading is None:
            mismatched.append(f"{path.name}: first line is not `# ADR-NNNN`")
        elif int(heading.group(1)) != number:
            mismatched.append(
                f"{path.name}: filename says {number:04d}, heading says "
                f"{heading.group(1)}"
            )

    if not numbers:
        print("MATCHED ZERO ADRs. The selector is broken; a green means nothing.")
        return 1

    duplicates = {n: names for n, names in numbers.items() if len(names) > 1}
    lowest, highest = min(numbers), max(numbers)
    gaps = [n for n in range(lowest, highest + 1) if n not in numbers]
    index_problems = _check_index({n: v for n, v in numbers.items()})

    print(
        f"ADRs: {sum(len(v) for v in numbers.values())}, numbered "
        f"{lowest:04d}-{highest:04d}"
    )

    for number, names in sorted(duplicates.items()):
        print(f"  DUPLICATE {number:04d}:")
        for name in names:
            print(f"      {name}")
    for number in gaps:
        print(f"  GAP       {number:04d} - no ADR carries this number")
    for problem in mismatched:
        print(f"  HEADING   {problem}")
    for problem in index_problems:
        print(f"  INDEX     {problem}")

    if duplicates or gaps or mismatched or index_problems:
        print(
            f"\n{len(duplicates)} duplicate(s), {len(gaps)} gap(s), "
            f"{len(mismatched)} heading mismatch(es), "
            f"{len(index_problems)} index disagreement(s)."
        )
        print("An ADR number is cited from code. Two documents cannot share one.")
        print(f"{INDEX.name}'s table must list every ADR and only ADRs that exist.")
        return 1

    print(
        f"Every ADR number is unique, contiguous, and matches its own heading, "
        f"and {INDEX.name}'s table lists all {sum(len(v) for v in numbers.values())} "
        f"of them and nothing else."
    )
    _report_branches(highest)
    return 0


def _branch_numbers() -> dict[int, set[str]] | None:
    """ADR numbers claimed on EVERY local branch, not just this one.

    **R8-L1: this checker read only the working tree, so it reported
    0030 as free on a branch where another branch had already taken
    it.** A reviewer on `review/r8` was told "ADRs: 29, numbered
    0001-0029, exit 0" while ADR-0030 was already Accepted on `main`,
    which was not an ancestor of its base. The checker was right about
    the tree and wrong about the question anyone asks it, which is
    "may I take the next number?".

    That is the two-agents-both-correct-when-they-looked collision this
    project has already had once, with U10 and me both taking 0027.

    **`check=True` made the considered answer unreachable.** Outside a
    git repo `git for-each-ref` exits 128, `check=True` raised
    `CalledProcessError`, and the traceback exited 1 - the SAME exit
    code a real duplicate or gap produces, from a checker that had a
    written answer for this exact case (*"No branches scanned"*) and
    could never give it.

    Fail-loud, not fail-closed: the branch scan is ADVISORY, answering
    "which number may I take next", not the numbering check itself, so
    it failing must not decide the gate. `check=False`, and the git
    failure returns **None** where an empty-but-real repo returns an
    empty dict - the None-for-a-failure / empty-for-empty split R19-M1
    established in `check-harness-anchors.py`, because "the scan could
    not run" and "the scan ran and found nothing" must not render
    identically.
    """
    import subprocess

    claimed: dict[int, set[str]] = collections.defaultdict(set)
    listed = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode != 0:
        print(
            f"\nBRANCH SCAN COULD NOT RUN: `git for-each-ref` exited "
            f"{listed.returncode} in {ROOT}."
        )
        for line in listed.stderr.splitlines():
            print(f"  git: {line}")
        return None
    branches = listed.stdout.split()
    for branch in branches:
        listing = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", branch, "--", "docs/adr/"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        for path in listing.stdout.splitlines():
            match = re.search(r"docs/adr/(\d{4})-", path)
            if match:
                claimed[int(match.group(1))].add(branch)
    return claimed


def _report_branches(highest_here: int) -> None:
    """Say what the NEXT FREE number is across every branch."""
    claimed = _branch_numbers()
    if claimed is None:
        print("The ADR numbering and index checks above are unaffected; only")
        print("the next-free-number advice is missing.")
        return
    if not claimed:
        print("\nNo branches scanned; the cross-branch check did not run.")
        return

    highest = max(claimed)
    print(
        f"\nAcross {len({b for v in claimed.values() for b in v})} local branch(es): "
        f"highest ADR number claimed anywhere is {highest:04d}."
    )

    elsewhere = sorted(n for n in claimed if n > highest_here)
    for number in elsewhere:
        print(
            f"  ELSEWHERE {number:04d} exists on {', '.join(sorted(claimed[number]))}",
        )
        print("            but NOT in this checkout - do not reuse this number.")

    print(f"NEXT FREE ADR NUMBER: {max(highest, highest_here) + 1:04d}")
    if elsewhere:
        print("Take it from THIS line, not from the count above: a number can be")
        print("claimed on a branch this checkout cannot see.")


if __name__ == "__main__":
    sys.exit(main())
