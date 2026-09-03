#!/usr/bin/env python3
"""Every mapping in docs/OBLIGATIONS.md still resolves TO ITS SUBJECT.

CONF-6 finding F-9, and the only fix in that report aimed at the
mechanism rather than at a row.

THE PROBLEM THIS SOLVES. CONF-6 classified 28 tracked-open obligations
and found twelve met - and of those twelve, exactly ONE (B58) had its
B-number recorded anywhere near the artifact that satisfies it. The
other nine met-in-substance rows are met BY ACCIDENT: correct today
because somebody independently followed the standard, with nothing in
the tree that would notice a regression. Delete `"DTZ",` from
pyproject.toml and B51 silently reverts, and no check anywhere mentions
B51.

An obligation propagated in this project if and only if a document
somebody actually EXECUTED AGAINST happened to name it.
`docs/OBLIGATIONS.md` plus this script is that document, made
executable, so the mapping is maintained by a failing build rather than
by whoever remembers.

WHAT IT CHECKS, and why each one is not the obvious weaker version:

  1. The cited file EXISTS. A grep at a path that does not exist returns
     the same clean empty as a real absence, and this repository has
     produced that mistake more than once.
  2. The cited LINE exists in it.
  3. The cited line CONTAINS THE SUBJECT. This is the whole point.
     Checking that a line number resolves, or that the line is
     non-blank, passes against any edit that shifts the file - which is
     precisely how a citation rots.
     `docs/reviews/CITATION-RANGE-AUDIT.md` records the same failure in
     this corpus: a contracted citation range still resolves, still
     quotes accurately, and is still wrong.
  4. If the subject is NOT on the cited line but IS elsewhere in the
     file, the failure names the line it moved to. A drifted anchor
     should cost one edit, not one investigation.
  5. The subject is long enough to be a subject. A one- or two-character
     subject matches everything and turns row 3 into a formality.
  6. B-numbers are unique, classes are from the vocabulary, and every
     row whose class claims an artifact actually cites one.

SELECTOR CONTROL: parsing zero rows is a FAILURE, never a pass.

WHAT IT DELIBERATELY DOES NOT DO. It does not judge whether an
obligation is MET - that is a human reading a clause against an
artifact, and CONF-6 is that reading. It checks that the reading's
evidence still points at what the reading said it pointed at. A green
here means "the map has not rotted", never "the repository is
conformant".

Usage:
    python3 docs/reviews/check-obligations.py [path/to/OBLIGATIONS.md]
    python3 docs/reviews/check-obligations.py --controls

Exit 0 on success, 1 on any failure. No dependencies.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

DEFAULT_MAP = "docs/OBLIGATIONS.md"

# A subject shorter than this matches too much to be evidence of
# anything.
MIN_SUBJECT = 6

# Classes that must carry an artifact, and classes that must not.
NEEDS_ARTIFACT = {"MET", "CONTRADICTED", "SUPERSEDED"}
NO_ARTIFACT = {"ABSENT"}
CLASSES = NEEDS_ARTIFACT | NO_ARTIFACT

UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
# `B\d+[a-z]?`, not `B\d+`: B49b is a real obligation id in this project
# and the bare form SILENTLY SKIPS its row, which is the one failure
# this file exists to prevent - a row that looks tracked and is never
# verified.
#
# `BASH-\d+` is a SECOND namespace, and it is separate on purpose. The
# `B` numbers are CONF-6's corpus; `devops/bash.md` is not in that
# corpus at all (`grep -i bash docs/reviews/CONF-6-PROPAGATION-AUDIT.md`
# returns nothing), which is precisely why it reached this repository
# with zero coverage. Numbering its clauses `B107`, `B108` would assert
# they were part of a census that never enumerated them - a fabricated
# identifier is worse than an ugly one. A new prefix says "verified
# here, not inherited from CONF-6".
ROW = re.compile(r"\|\s*(B\d+[a-z]?|BASH-\d+)\s*\|")
#: `path` or `path:line`. **The line number is OPTIONAL and
#: deprecated.**
#:
#: A line number in an anchor pins nothing the SUBJECT does not already
#: pin, and it is the only part that drifts. Four separate repoint
#: operations were needed in one day - a ci.yml insertion moved two
#: anchors, a docstring reflow moved a third, and deleting two stale
#: comment lines moved eight - and every one was mechanical, carried no
#: information, and risked retyping a number.
#:
#: A line-free anchor cannot drift. The subject must then be UNIQUE in
#: the file, which is a stronger property than "appears at line N" and
#: is checked.
ANCHOR = re.compile(r"^(?P<path>[^:]+)(?::(?P<line>\d+))?$")


def cells(line: str) -> list[str]:
    return [c.strip() for c in UNESCAPED_PIPE.split(line.rstrip())[1:-1]]


def unmark(cell: str) -> str:
    """Strip a table cell's markdown, leaving the literal text."""
    return re.sub(r"^[`*]+|[`*]+$", "", cell.strip()).strip()


def parse(text: str) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    problems: list[str] = []
    seen: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), 1):
        match = ROW.match(line)
        if not match:
            continue
        row = cells(line)
        if len(row) != 6:
            problems.append(
                f"OBLIGATIONS.md:{lineno}: {match.group(1)} has {len(row)} "
                f"cells, expected 6 "
                "(B | Class | Artifact | Subject | Standard clause | Note)."
            )
            continue
        bnum, klass, artifact, subject, clause, _note = (unmark(c) for c in row)
        if bnum in seen:
            problems.append(f"OBLIGATIONS.md:{lineno}: {bnum} is mapped twice.")
            continue
        seen.add(bnum)
        if klass not in CLASSES:
            problems.append(
                f"OBLIGATIONS.md:{lineno}: {bnum}'s class {klass!r} is not one of "
                f"{sorted(CLASSES)}."
            )
            continue
        rows.append(
            {
                "b": bnum,
                "class": klass,
                "artifact": artifact,
                "subject": subject,
                "clause": clause,
                "lineno": str(lineno),
            }
        )
    return rows, problems


def verify(row: dict[str, str], root: pathlib.Path) -> str | None:
    """A failure message, or None if the row's evidence holds."""
    bnum, klass, artifact, subject = (
        row["b"],
        row["class"],
        row["artifact"],
        row["subject"],
    )

    if klass in NO_ARTIFACT:
        if artifact not in ("-", ""):
            return (
                f"{bnum}: class {klass} cites an artifact ({artifact}). "
                f"An absence has no "
                "artifact; if one exists the class is wrong."
            )
        return None

    if artifact in ("-", ""):
        return (
            f"{bnum}: class {klass} must cite an artifact at path:line, and cites none."
        )

    anchor = ANCHOR.match(artifact)
    if not anchor:
        return f"{bnum}: artifact {artifact!r} is not of the form path:line."

    if len(subject) < MIN_SUBJECT:
        return (
            f"{bnum}: subject {subject!r} is {len(subject)} characters. "
            "A subject that short matches too much to be evidence; quote "
            "enough of the line to be distinctive."
        )

    path = root / anchor.group("path")
    if not path.is_file():
        return (
            f"{bnum}: {path} does not exist. A check at a missing path "
            "returns the same clean "
            "empty as a passing one, so this is a failure, not a skip."
        )

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    if anchor.group("line") is None:
        # Line-free anchor: the subject locates itself, and must be
        # unique.
        hits = [i for i, line in enumerate(lines, 1) if subject in line]
        if not hits:
            return (
                f"{bnum}: {subject!r} is nowhere in {artifact}. Either the "
                f"obligation regressed or the artifact moved; {row['clause']} "
                "is the clause to re-read."
            )
        if len(hits) > 1:
            return (
                f"{bnum}: {subject!r} appears {len(hits)} times in {artifact} "
                f"(lines {hits}). A line-free anchor needs a subject that is "
                "unique in the file - quote more of the line. Ambiguity is "
                "refused rather than resolved to the first hit, because the "
                "first hit is not evidence of anything."
            )
        return None

    want = int(anchor.group("line"))
    if want > len(lines):
        return f"{bnum}: {artifact} is past the end of the file ({len(lines)} lines)."

    if subject in lines[want - 1]:
        return None

    elsewhere = [i for i, line in enumerate(lines, 1) if subject in line]
    if elsewhere:
        return (
            f"{bnum}: {artifact} no longer contains {subject!r} - it is now at "
            f"{anchor.group('path')}:{elsewhere[0]}. Repoint the anchor."
        )
    return (
        f"{bnum}: {subject!r} is nowhere in {anchor.group('path')}. "
        "Either the obligation "
        f"regressed or the artifact moved; {row['clause']} is the clause to re-read."
    )


def check(map_path: pathlib.Path, root: pathlib.Path | None = None) -> int:
    if not map_path.is_file():
        print(f"FAIL: {map_path} does not exist.")
        return 1
    root = root if root is not None else map_path.parent.parent

    rows, failures = parse(map_path.read_text(encoding="utf-8"))

    if not rows:
        failures.append(
            "FAIL: parsed zero mappings (selector control). A green from a checker "
            "that read nothing is the wrong zero this whole file exists to prevent."
        )

    checked = 0
    for row in rows:
        problem = verify(row, root)
        if problem:
            failures.append(f"FAIL: {problem}")
        elif row["class"] in NEEDS_ARTIFACT:
            checked += 1

    absent = sum(1 for r in rows if r["class"] in NO_ARTIFACT)
    print(
        f"Mappings: {len(rows)}  |  anchors verified against their "
        f"subject: {checked}  |  "
        f"recorded as absent: {absent}"
    )

    if failures:
        print()
        for failure in failures:
            print(failure)
        print(f"\n{len(failures)} failure(s).")
        return 1

    print("Every mapped anchor still contains its subject. OK.")
    return 0


# ----------------------------------------------------------------------
# Controls. The important ones mutate the TARGET rather than the map:
# the claim this script makes is that deleting `"DTZ",` from
# pyproject.toml breaks something that names B51, and only a control
# that actually deletes it can establish that.
# ----------------------------------------------------------------------


def _first_mapped(
    rows: list[dict[str, str]],
    want_class: str = "MET",
) -> dict[str, str]:
    for row in rows:
        if row["class"] == want_class:
            return row
    raise AssertionError(f"no {want_class} row to mutate")


def _c_duplicate_subject(tree: pathlib.Path, rows: list[dict[str, str]]) -> str:
    """Make a subject appear twice, so it no longer locates one line.

    **This control REPLACED `_c_break_line`.** That one pointed a good
    anchor at line 1 and expected a failure, which is unfirable once
    anchors carry no line - it went green and said so, which is how the
    replacement got written. Ambiguity is the property a line-free
    anchor actually rests on, so it is what gets a control.
    """
    row = _first_mapped(rows)
    path = tree / row["artifact"].rsplit(":", 1)[0]
    text = path.read_text(encoding="utf-8")
    first = next(line for line in text.splitlines() if row["subject"] in line)
    path.write_text(text.replace(first, first + "\n" + first, 1), encoding="utf-8")
    return f"subject duplicated so it is no longer unique ({row['b']})"


def _c_delete_target(tree: pathlib.Path, rows: list[dict[str, str]]) -> str:
    """Delete a cited file - the wrong-zero control."""
    row = _first_mapped(rows)
    (tree / row["artifact"].rsplit(":", 1)[0]).unlink()
    return f"cited file deleted ({row['b']})"


def _c_regress_subject(tree: pathlib.Path, rows: list[dict[str, str]]) -> str:
    """Remove the subject - the regression this map exists to catch."""
    row = _first_mapped(rows)
    path = tree / row["artifact"].rsplit(":", 1)[0]
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(row["subject"], "", 1), encoding="utf-8")
    return f"subject removed from the artifact ({row['b']})"


def _n_move_subject(tree: pathlib.Path, rows: list[dict[str, str]]) -> str:
    """NEGATIVE control: shifting the artifact must NOT fail the map.

    **This is the guarantee the whole line-free scheme exists to make**,
    and it is the one property no ordinary control can express, because
    a control asserts that something FIRES. Drift must not fire, so it
    is run in its own list with the verdict inverted.

    Without it, the scheme's central claim is untested: every remaining
    control would still pass against a checker that had quietly gone
    back to matching on line numbers.
    """
    row = _first_mapped(rows)
    path = tree / row["artifact"].rsplit(":", 1)[0]
    text = path.read_text(encoding="utf-8")
    path.write_text("\n" * 5 + text, encoding="utf-8")
    return f"artifact shifted by five lines ({row['b']})"


def _c_trivial_subject(tree: pathlib.Path, rows: list[dict[str, str]]) -> str:
    """Weaken a subject to something that matches anything."""
    row = _first_mapped(rows)
    path = tree / DEFAULT_MAP
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(f"`{row['subject']}`", "`=`", 1), encoding="utf-8")
    return f"subject weakened to a single character ({row['b']})"


def _c_regress_b51_dtz(tree: pathlib.Path, _rows: list[dict[str, str]]) -> str:
    r"""Delete the DTZ rule from pyproject.toml.

    Named rather than generic, because it is the specific claim this
    file makes about itself: "delete `\"DTZ\",` from pyproject.toml and
    B51 silently reverts, and no check anywhere mentions B51." A control
    that only ever breaks the FIRST mapped row proves the machinery
    works; it does not prove that sentence. This one does.
    """
    path = tree / "pyproject.toml"
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if '"DTZ",' not in line]
    assert len(kept) == len(lines) - 1, "control expected exactly one DTZ line"
    path.write_text("\n".join(kept), encoding="utf-8")
    return "the DTZ rule deleted from pyproject.toml (B51's own claim)"


def _c_duplicate_row(tree: pathlib.Path, _rows: list[dict[str, str]]) -> str:
    """Map one B-number twice."""
    path = tree / DEFAULT_MAP
    lines = path.read_text(encoding="utf-8").splitlines()
    index = next(i for i, line in enumerate(lines) if ROW.match(line))
    lines.insert(index + 1, lines[index])
    path.write_text("\n".join(lines), encoding="utf-8")
    return "one B-number mapped twice"


def _c_absent_with_artifact(tree: pathlib.Path, rows: list[dict[str, str]]) -> str:
    """Claim an artifact for a row recorded as absent."""
    row = _first_mapped(rows, "ABSENT")
    path = tree / DEFAULT_MAP
    lines = path.read_text(encoding="utf-8").splitlines()
    target = int(row["lineno"]) - 1
    lines[target] = lines[target].replace("| - | - |", "| `LICENSE:1` | `Apache` |", 1)
    path.write_text("\n".join(lines), encoding="utf-8")
    return f"an ABSENT row given an artifact ({row['b']})"


def _c_empty_map(tree: pathlib.Path, _rows: list[dict[str, str]]) -> str:
    """Remove every mapping - the selector control."""
    path = tree / DEFAULT_MAP
    text = path.read_text(encoding="utf-8")
    path.write_text(
        "\n".join(line for line in text.splitlines() if not ROW.match(line)),
        encoding="utf-8",
    )
    return "every mapping removed (selector control)"


NEGATIVE_CONTROLS = [_n_move_subject]

CONTROLS = [
    _c_duplicate_subject,
    _c_delete_target,
    _c_regress_subject,
    _c_trivial_subject,
    _c_regress_b51_dtz,
    _c_duplicate_row,
    _c_absent_with_artifact,
    _c_empty_map,
]


def run_controls(map_path: pathlib.Path) -> int:
    root = map_path.parent.parent
    if check(map_path, root) != 0:
        print(
            "\nABORT: the real map is already red, so no control below "
            "proves anything.",
        )
        return 1
    print("\n--- controls ---")

    rows, _ = parse(map_path.read_text(encoding="utf-8"))
    bad = 0

    for control in CONTROLS:
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp) / "tree"
            # copy the tracked working tree, minus .git, which is large
            # and irrelevant here
            shutil.copytree(
                root,
                tree,
                ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"),
            )
            try:
                label = control(tree, rows)
            except (AssertionError, StopIteration, FileNotFoundError) as exc:
                print(
                    f"  DID NOT FIRE  {control.__name__}: could not apply "
                    f"the mutation ({exc})"
                )
                bad += 1
                continue
            result = subprocess.run(
                [sys.executable, __file__, str(tree / DEFAULT_MAP)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(f"  DID NOT FIRE  {label}")
                bad += 1
            else:
                print(f"  fired         {label}")

    print(f"\n{len(CONTROLS) - bad}/{len(CONTROLS)} controls fired.")

    # NEGATIVE controls: these must leave the map GREEN. A control list
    # that only ever asserts failure cannot express "this must not
    # matter", and "line drift must not matter" is the entire point of a
    # line-free anchor.
    print("--- negative controls (these must NOT fire) ---")
    for control in NEGATIVE_CONTROLS:
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp) / "tree"
            shutil.copytree(
                root,
                tree,
                ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"),
            )
            try:
                label = control(tree, rows)
            except (AssertionError, StopIteration, FileNotFoundError) as exc:
                print(f"  BROKEN        {control.__name__}: could not apply ({exc})")
                bad += 1
                continue
            result = subprocess.run(
                [sys.executable, __file__, str(tree / DEFAULT_MAP)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(f"  tolerated     {label}")
            else:
                print(f"  WRONGLY FIRED {label}")
                print(f"                {result.stdout.strip().splitlines()[-1]}")
                bad += 1

    if bad:
        return 1
    print(
        f"post-run re-check of the real {map_path.name}: exit={check(map_path, root)}",
    )
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--controls"]
    map_path = pathlib.Path(args[0]) if args else pathlib.Path(DEFAULT_MAP)
    if "--controls" in sys.argv[1:]:
        return run_controls(map_path)
    return check(map_path)


if __name__ == "__main__":
    sys.exit(main())
