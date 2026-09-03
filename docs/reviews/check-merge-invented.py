#!/usr/bin/env python3
"""Find content that entered the tree INSIDE a merge resolution.

    uv run --frozen python docs/reviews/check-merge-invented.py \
        --range origin/main..HEAD

THE DISCRIMINATOR IS NOT A NON-EMPTY COMBINED DIFF. `git show --cc`
reports every region BOTH sides touched, so two agents editing
ADJACENT ROWS of one table produce hunks while each row is taken
whole from one side. Merge `043cc6f` has 983 bytes of combined diff
and invented nothing, and it is this file's negative control. A byte
count is a screening filter; it is not a finding.

What this checks instead:

    a line present in the merge's version of a file
    and in NEITHER parent's version of THAT SAME FILE

Such a line was typed by whoever resolved the merge. It is an
addition in no branch diff, so no reviewer of either branch could
have seen it, and `git log -p` skips merges by default.

SET SEMANTICS, DELIBERATELY:

- A line that merely CHANGES COUNT (once in a parent, twice in the
  merge) is not invention. Multiset arithmetic would report
  re-ordering and duplication as authored content.
- A file present in only ONE parent - added on a branch, or renamed -
  yields no lines for the other side. Because a line must be absent
  from BOTH parents, whole new files are correctly not flagged.

WHAT IT CANNOT SEE. A reflow that re-wraps a paragraph changes every
line boundary, so an unchanged sentence can surface here as many
"invented" lines. The output is a population to READ, not a verdict.
It also cannot see a line the resolver typed that happens to exist
elsewhere in the same file - deletion of one duplicate and insertion
of another is invisible to a set.

Exit codes:

    0  ran successfully (findings are REPORTED, not gated)
    1  --strict was given and at least one invented line was found
    2  usage, or a git failure
"""

from __future__ import annotations

import argparse
import subprocess
import sys

# Lines whose presence in a merge and absence from both parents
# carries no information about authored content. Kept deliberately
# tiny and explicit: an over-broad ignore list is how a detector
# prints a clean zero that explains itself.
_TRIVIAL = {"", "-", "--", "---", "```", "}", ")", "];", "});"}


def git(repo: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed rc={proc.returncode}: {proc.stderr.strip()}"
        )
    return proc.stdout


def parents(repo: str, rev: str) -> list[str]:
    line = git(repo, "rev-list", "--parents", "-n", "1", rev).split()
    return line[1:]


def blob_text(repo: str, rev: str, path: str) -> list[str] | None:
    """Lines of <rev>:<path>, or None when it does not exist there.

    None and the empty list stay DISTINCT so a caller can tell
    "file absent at this parent" from "file empty at this parent".
    """
    proc = subprocess.run(
        ["git", "-C", repo, "show", f"{rev}:{path}"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.splitlines()


def changed_paths(repo: str, merge: str, parent_revs: list[str]) -> list[str]:
    """Union of the paths where the merge differs from ANY parent.

    Scanning only these is not a narrowing. A path byte-identical to
    every parent cannot hold a line absent from every parent.
    """
    paths: set[str] = set()
    for parent in parent_revs:
        out = git(repo, "diff", "--name-only", "--diff-filter=d", parent, merge)
        paths.update(x for x in out.splitlines() if x)
    return sorted(paths)


def invented(
    repo: str, merge: str
) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Return (parents, paths scanned, {path: merge-invented lines}).

    The scanned-path list is returned so a ZERO can be shown
    non-vacuous. A zero over zero paths is an instrument that never
    looked, and it reads identically to a clean merge.
    """
    parent_revs = parents(repo, merge)
    if len(parent_revs) < 2:
        raise RuntimeError(f"{merge} is not a merge commit ({len(parent_revs)} parent)")

    scanned: list[str] = []
    findings: dict[str, list[str]] = {}
    for path in changed_paths(repo, merge, parent_revs):
        merged = blob_text(repo, merge, path)
        if merged is None:
            continue
        scanned.append(path)
        union: set[str] = set()
        for parent in parent_revs:
            side = blob_text(repo, parent, path)
            if side:
                union |= set(side)
        seen: set[str] = set()
        new: list[str] = []
        # Order of first appearance in the MERGE's own file, never
        # sorted: these lines are prose that has to be READ, and
        # sorting shreds the argument they make.
        for line in merged:
            if line in union or line in seen:
                continue
            if not line.strip() or line.strip() in _TRIVIAL:
                continue
            seen.add(line)
            new.append(line)
        if new:
            findings[path] = new
    return parent_revs, scanned, findings


def combined_diff_bytes(repo: str, merge: str) -> int:
    return len(git(repo, "show", "--cc", "--format=", merge).encode())


def report(repo: str, merge: str) -> int:
    short = git(repo, "rev-parse", "--short", merge).strip()
    subject = git(repo, "log", "-1", "--format=%s", merge).strip()
    parent_revs, scanned, findings = invented(repo, merge)
    shorts = [git(repo, "rev-parse", "--short", p).strip() for p in parent_revs]
    total = sum(len(v) for v in findings.values())
    print(
        f"{short}  parents={','.join(shorts)}  "
        f"cc={combined_diff_bytes(repo, merge)}B  "
        f"paths_scanned={len(scanned)}  invented={total}"
    )
    print(f"    {subject}")
    for path in sorted(findings):
        print(f"  {path}: {len(findings[path])}")
        for line in findings[path]:
            print(f"      + {line}")
    return total


# The merge that motivated this file. `suborch-213` verified BY HAND
# that this string is in the merge and in neither parent; it is the
# one case whose answer was known before the detector existed.
POSITIVE_MERGE = "73dd717"
POSITIVE_NEEDLE = "A syntax split"

# Non-empty `--cc`, nothing invented: two agents changed ADJACENT
# ROWS of one table and each row came whole from one side. A detector
# that flags this is measuring `--cc`, not authorship.
NEGATIVE_MERGE = "043cc6f"


def self_test(repo: str) -> int:
    """The two repo-history controls. Both must hold."""
    rc = 0
    try:
        _, _, findings = invented(repo, POSITIVE_MERGE)
    except RuntimeError as exc:
        print(f"POSITIVE CONTROL ERROR: {exc}")
        return 2
    hit = [
        (path, line)
        for path, lines in findings.items()
        for line in lines
        if POSITIVE_NEEDLE in line
    ]
    if hit:
        print(
            f"POSITIVE CONTROL PASS: {POSITIVE_MERGE} -> {len(hit)} "
            f"line(s) containing {POSITIVE_NEEDLE!r}"
        )
        for path, line in hit:
            print(f"    {path}: {line.strip()}")
    else:
        print(
            f"POSITIVE CONTROL FAIL: {POSITIVE_MERGE} yielded no line "
            f"containing {POSITIVE_NEEDLE!r}"
        )
        rc = 1

    try:
        _, neg_scanned, neg = invented(repo, NEGATIVE_MERGE)
    except RuntimeError as exc:
        print(f"NEGATIVE CONTROL ERROR: {exc}")
        return 2
    neg_total = sum(len(v) for v in neg.values())
    neg_cc = combined_diff_bytes(repo, NEGATIVE_MERGE)
    if neg_cc == 0:
        print(
            f"NEGATIVE CONTROL INCONCLUSIVE: {NEGATIVE_MERGE} cc=0B, so "
            f"it does not exercise the screening filter at all"
        )
        rc = 1
    elif neg_total == 0:
        print(
            f"NEGATIVE CONTROL PASS: {NEGATIVE_MERGE} cc={neg_cc}B "
            f"paths_scanned={len(neg_scanned)} invented=0"
        )
    else:
        print(
            f"NEGATIVE CONTROL FAIL: {NEGATIVE_MERGE} cc={neg_cc}B invented={neg_total}"
        )
        for path in sorted(neg):
            for line in neg[path]:
                print(f"    {path}: {line}")
        rc = 1
    return rc


def synthetic_test() -> int:
    """Build two merges from scratch and separate them.

    This control does NOT depend on this repository's history. It
    exists because `--self-test` proves only that the detector agrees
    with one hand-traced case, and a detector that special-cased that
    one SHA would pass it too.

    ARM A - INVENTION. Both branches edit the same line and the
    resolver types a THIRD version on neither side. Must be reported.

    ARM B - ADJACENT ROWS. Each branch adds its own row to one table
    and the merge keeps both verbatim. `--cc` is non-empty and
    nothing was authored, so it must come back clean. This is the
    shape of `043cc6f`.
    """
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="merge-invented-control-")
    try:

        def g(*args: str) -> str:
            return git(tmp, *args)

        def write(text: str) -> None:
            with open(f"{tmp}/table.md", "w") as handle:
                handle.write(text)

        subprocess.run(["git", "init", "-q", tmp], check=True, capture_output=True)
        g("config", "user.email", "control@example.invalid")
        g("config", "user.name", "control")
        write("row one\nrow two\nrow three\n")
        g("add", "table.md")
        g("commit", "-q", "-m", "base")
        g("branch", "-M", "base")

        rc = 0

        g("checkout", "-q", "-b", "a1", "base")
        write("row one\nAAA from branch a1\nrow three\n")
        g("commit", "-q", "-am", "a1 edits row two")
        g("checkout", "-q", "-b", "a2", "base")
        write("row one\nBBB from branch a2\nrow three\n")
        g("commit", "-q", "-am", "a2 edits row two")
        g("checkout", "-q", "a1")
        subprocess.run(
            ["git", "-C", tmp, "merge", "--no-commit", "a2"],
            capture_output=True,
        )
        write("row one\nCCC typed only in the resolution\nrow three\n")
        g("add", "table.md")
        g("commit", "-q", "-m", "merge a2: resolved by hand")
        _, a_scanned, a_found = invented(tmp, g("rev-parse", "HEAD").strip())
        a_lines = [ln for lines in a_found.values() for ln in lines]
        if a_lines == ["CCC typed only in the resolution"]:
            print(
                f"SYNTHETIC ARM A PASS: paths_scanned={len(a_scanned)} "
                f"invented={a_lines}"
            )
        else:
            print(f"SYNTHETIC ARM A FAIL: got {a_lines}")
            rc = 1

        g("checkout", "-q", "-b", "b1", "base")
        write("row one\nrow two\nrow B1 added\nrow three\n")
        g("commit", "-q", "-am", "b1 adds a row")
        g("checkout", "-q", "-b", "b2", "base")
        write("row one\nrow two\nrow B2 added\nrow three\n")
        g("commit", "-q", "-am", "b2 adds a row")
        g("checkout", "-q", "b1")
        subprocess.run(
            ["git", "-C", tmp, "merge", "--no-commit", "b2"],
            capture_output=True,
        )
        write("row one\nrow two\nrow B1 added\nrow B2 added\nrow three\n")
        g("add", "table.md")
        g("commit", "-q", "-m", "merge b2: both rows kept")
        arm_b = g("rev-parse", "HEAD").strip()
        _, b_scanned, b_found = invented(tmp, arm_b)
        b_lines = [ln for lines in b_found.values() for ln in lines]
        b_cc = combined_diff_bytes(tmp, arm_b)
        if b_cc == 0:
            print(
                "SYNTHETIC ARM B INCONCLUSIVE: cc=0B, so this arm does "
                "not exercise the screening filter"
            )
            rc = 1
        elif not b_lines:
            print(
                f"SYNTHETIC ARM B PASS: cc={b_cc}B "
                f"paths_scanned={len(b_scanned)} invented=0"
            )
        else:
            print(f"SYNTHETIC ARM B FAIL: cc={b_cc}B flagged {b_lines}")
            rc = 1
        return rc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="find merge-invented lines")
    ap.add_argument("revs", nargs="*", help="merge commits to inspect")
    ap.add_argument("--repo", default=".", help="repository (default: cwd)")
    ap.add_argument("--range", dest="rng", help="inspect every merge in a commit range")
    ap.add_argument(
        "--self-test",
        action="store_true",
        help="run the two repo-history controls",
    )
    ap.add_argument(
        "--synthetic-test",
        action="store_true",
        help="build two merges from scratch and separate them",
    )
    ap.add_argument("--strict", action="store_true", help="exit 1 on any finding")
    args = ap.parse_args()

    if args.synthetic_test:
        return synthetic_test()
    if args.self_test:
        return self_test(args.repo)

    revs = list(args.revs)
    if args.rng:
        try:
            revs.extend(git(args.repo, "rev-list", "--merges", args.rng).split())
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if not revs:
        ap.print_usage(sys.stderr)
        return 2

    total = 0
    for rev in revs:
        try:
            total += report(args.repo, rev)
        except RuntimeError as exc:
            print(f"ERROR {rev}: {exc}", file=sys.stderr)
            return 2
    print(f"TOTAL merges={len(revs)} invented_lines={total}")
    if args.strict and total:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
