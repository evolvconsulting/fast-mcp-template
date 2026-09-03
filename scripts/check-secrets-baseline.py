#!/usr/bin/env python3
"""The secret gate compares FINDINGS, not file mtimes.

    python3 scripts/check-secrets-baseline.py            # the gate
    python3 scripts/check-secrets-baseline.py --controls  # can go red

**WHY THIS EXISTS, AND IT IS NOT A STYLE PREFERENCE.** The hook this
replaces was `Yelp/detect-secrets`'s own `detect-secrets` pre-commit
hook, run by `ci.yml` through `pre-commit run --all-files`. That hook
**rewrites `.secrets.baseline` in place** to refresh the `line_number`
of every finding it still sees, and `pre-commit` fails whenever a hook
modifies a file. Measured at `ccbdaae`, with CI's exact invocation:

    secret scan (detect-secrets, staged content)...............Failed
    - exit code: 3
    - files were modified by this hook
    -        "line_number": 1344,
    +        "line_number": 1617,
    -  "generated_at": "2026-09-01T20:33:41Z"
    +  "generated_at": "2026-09-02T01:22:26Z"

The entry is `.github/workflows/ci.yml`, `is_secret: false`, the literal
`inspect-only-not-a-credential`. **Not a secret, and never was.** The
recorded line drifted because `ci.yml` grew. In a developer's shell you
`git add .secrets.baseline` and move on - the hook's message says so.
**In CI nothing can be staged**, so the step went red on the first line
drift after each regeneration and could not recover. Run it twice and it
fails differently, *"Your baseline file (.secrets.baseline) is
unstaged"*, which is the same defect wearing its other face.

`ci.yml` already stated the intent this file implements:

    What this step genuinely covers is the secret scan over every file,
    and .secrets.baseline staying in step with the tree - a new finding
    nobody audited turns this red.

**A NEW FINDING TURNS IT RED. A LINE NUMBER MOVING DOES NOT.** So the
comparison is over the SET of `(filename, type, hashed_secret)` triples.
`line_number` and `generated_at` are excluded by construction: they are
the only two fields that move on their own, and neither carries any
security information. Nothing else is dropped - the detector `type` is
part of the key, so the same string newly flagged by a *different*
plugin is a new finding, not a match.

**THE TREE IS NEVER TOUCHED.** The scan runs against a COPY of the
baseline in a temporary directory outside the repository, so
`detect-secrets` rewrites the copy. Same trick as
`docs/reviews/probe-coverage-ratchet.py`: a checker that mutates its own
subject cannot be trusted about it, and a checker that `git add`s its
own baseline inside CI is the gate rewriting the evidence it checks.

**THE COPY'S ONE SIDE EFFECT, MEASURED RATHER THAN ASSUMED.**
`detect-secrets` carries a `is_baseline_file` filter whose `filename` is
taken from whatever `--baseline` argument it was given. Pointing it at a
temp copy therefore **un-excludes the real `.secrets.baseline`**, which
is full of hex `hashed_secret` values: the raw scan returns 46 findings
where the committed baseline holds 22, and all 24 extras are the
baseline's own hashes, each reported twice (`Hex High Entropy String`
and `Secret Keyword`). `_drop_baseline_self_findings` removes exactly
those, reproducing the filter the real hook applies. It is keyed on the
baseline's own path, so it can drop nothing else, and control `C5`
proves a finding in any other file survives it.

**THE STALE DIRECTION, WHICH NOTHING CHECKED BEFORE.** An entry in the
baseline whose finding is no longer in the tree is a **stale
allowance**. It is reported on every run, by name, and it **warns
rather than fails**. The reason: a stale allowance grants nothing -
the string it excused is gone - so its risk today is zero, while
failing on it would make the gate go red for a DELETION and leave
exactly one way to clear it, hand-editing
`.secrets.baseline`. That is the trap this file exists to remove, one
column over, and a gate red for improving the tree is `U0-REPORT`'s D3
failure shape that this repository has already accepted twice
(`.pre-commit-config.yaml`'s shellcheck block, and `pip-audit`). It is
printed with its count so it cannot rot unseen; if it ever wants to
ratchet, that is a decision with a number behind it.

**WHAT THIS CANNOT DO.** It compares HASHES, so it never prints a secret
- but it cannot tell you that an `is_secret: false` audit was WRONG.
An entry mis-audited when it was added stays excused forever, exactly as
before. That is a review property, not a gate property, and
`docs/CREDENTIAL-CHECKLIST.md` is where it lives. It also inherits every
false negative of the plugin set recorded in `.secrets.baseline`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE = ROOT / ".secrets.baseline"

#: `(filename, type, hashed_secret)`. The whole design is in this tuple.
Finding = tuple[str, str, str]

#: What a baseline's `results` block is, read-only. `Mapping`/`Sequence`
#: rather than `dict`/`list` because `dict` is invariant in its value
#: type, and every caller here only reads.
Results = Mapping[str, Sequence[Mapping[str, object]]]


def pairs(results: Results) -> set[Finding]:
    """What a baseline asserts, with the drifting fields gone."""
    return {
        (filename, str(entry["type"]), str(entry["hashed_secret"]))
        for filename, entries in results.items()
        for entry in entries
    }


def _drop_baseline_self_findings(
    results: Results, baseline_name: str
) -> tuple[Results, int]:
    """Reproduce `is_baseline_file`, which a copy scan disables.

    Returns the results without the baseline's own entries, and how many
    were dropped. Keyed on the baseline's repo-relative path, so it is
    incapable of hiding a finding in any other file.
    """
    kept = {f: e for f, e in results.items() if f != baseline_name}
    dropped = len(results.get(baseline_name, []))
    return kept, dropped


def scan_against_copy(baseline: pathlib.Path) -> Results:
    """Scan the tree with a COPY of the baseline. Nothing is written.

    `detect-secrets scan --baseline X` reuses X's plugin and filter
    configuration and writes the merged result back into X - so X is a
    throwaway in a temp directory, and the committed baseline is only
    ever read.
    """
    with tempfile.TemporaryDirectory(prefix="secrets-baseline-") as tmp:
        copy = pathlib.Path(tmp) / "baseline-copy.json"
        shutil.copyfile(baseline, copy)
        # S603/S607 do not apply: a fixed argv, no shell, and the
        # interpreter is this process's own.
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "detect_secrets", "scan", "--baseline", str(copy)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise SystemExit(
                "detect-secrets scan failed with exit "
                f"{proc.returncode}:\n{proc.stderr.strip()}"
            )
        scanned: Results = json.loads(copy.read_text())["results"]
        return scanned


def _fail(message: str) -> None:
    print(message, file=sys.stderr)


def gate() -> int:
    """Compare the tree against the baseline. Returns the exit code."""
    if not BASELINE.is_file():
        _fail(f"no baseline at {BASELINE} - nothing to compare against")
        return 2
    if importlib.util.find_spec("detect_secrets") is None:
        _fail(
            "detect-secrets is not importable, so this gate cannot run and "
            "must not report success. It is pinned in .pre-commit-config.yaml; "
            "by hand, run:\n"
            "  uv run --no-project --with detect-secrets==1.5.0 python "
            "scripts/check-secrets-baseline.py"
        )
        return 2

    committed: Results = json.loads(BASELINE.read_text())["results"]
    scanned, self_dropped = _drop_baseline_self_findings(
        scan_against_copy(BASELINE), BASELINE.name
    )

    audited = pairs(committed)
    found = pairs(scanned)
    new = sorted(found - audited)
    stale = sorted(audited - found)

    for filename, kind, digest in new:
        _fail(f"UNAUDITED  {filename}  [{kind}]  sha1={digest}")
    for filename, kind, digest in stale:
        print(f"STALE      {filename}  [{kind}]  sha1={digest}")

    print(
        f"secrets-baseline: audited={len(audited)} found={len(found)} "
        f"new={len(new)} stale={len(stale)} "
        f"files={len(committed)} baseline-self-dropped={self_dropped}"
    )

    if new:
        _fail(
            f"\n{len(new)} finding(s) above are not in {BASELINE.name}. "
            "NEVER paste the value here or into a commit message. Read the "
            "line, and either remove the secret from the tree or - if it is "
            "genuinely not a credential - audit it in:\n"
            "  detect-secrets scan --baseline .secrets.baseline\n"
            "  detect-secrets audit .secrets.baseline\n"
            "and stage the baseline with the change that introduced it."
        )
        return 1
    if stale:
        print(
            f"\n{len(stale)} stale allowance(s) above: recorded in "
            f"{BASELINE.name}, no longer in the tree. This is a WARNING by "
            "decision - see this file's docstring. Clear them with a "
            "regeneration when you are next editing the baseline anyway."
        )
    _warn_untracked()
    return 0


def _warn_untracked() -> None:
    """Say which UNTRACKED files would become findings once tracked.

    #163. `detect-secrets scan` picks its population with `git
    ls-files`, so a brand-new file is invisible until the moment it is
    tracked - and then fails in the commit that adds it. That happened
    to THIS file: its control fixtures were two unaudited findings, and
    the first run passed only because it was still untracked.

    THREE OPTIONS WERE ON THE TABLE AND TWO ARE REFUSED.

    `git add -N` before the scan would fix it and MUTATES THE INDEX.
    This project has a standing ruling that unstaging is the
    destructive operation to avoid - #131's restorer refuses outright
    if a harness staged anything - and a gate that stages on every run
    is that rule pointed the other way. It would also scan files the
    author has not chosen to commit.

    A `pragma: allowlist secret` convention would trade a surprise for
    a habit of silencing the scanner, which is strictly worse.

    So: READ the untracked set explicitly, honour `.gitignore` via
    `--exclude-standard`, and WARN. The index is untouched, nothing the
    author did not write is scanned, and they hear about it before the
    commit rather than from a red gate.

    IT WARNS AND NEVER FAILS. An untracked file is not in the tree this
    gate governs, and failing on one would make the gate red for
    something no commit contains. Measured when written: 3 untracked
    non-ignored files, 0 findings - the noise this adds today is none.

    The scan runs as a SUBPROCESS, matching `scan_against_copy`, rather
    than importing detect_secrets: the library ships no type stubs and
    the first version of this function failed mypy for that reason.
    """
    # A SKIP ANNOUNCES ITSELF (R18-L1). Every one of these three exits
    # used to be a bare `return`, so the gate's output on a run that
    # could not look was BYTE-IDENTICAL to a run that looked and found
    # nothing. The same author wrote "an instrument that cannot see
    # reports that it cannot see" into check-mirror-liveness.py the same
    # evening, and did the opposite here three times.
    git = shutil.which("git")
    if git is None:
        print("\n  (untracked pre-check skipped: git is not on PATH)")
        return
    listed = _untracked_paths(git)
    if listed is None:
        # It already said why. Saying anything more here is the
        # second line R19-M1 was about.
        return
    if not listed:
        # NOT a skip: there is genuinely nothing untracked. Said
        # plainly so it cannot be confused with the branches above,
        # which are failures to LOOK.
        print("\n  (no untracked files to check ahead of tracking)")
        return
    try:
        done = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "detect_secrets", "scan", *listed],
            capture_output=True,
            text=True,
            check=False,
        )
        results = json.loads(done.stdout)["results"]
    except (OSError, ValueError, KeyError) as exc:
        # The exception TYPE and nothing from the payload. A scan of
        # untracked files could hold a secret, and its stdout is not a
        # safe thing to print from a gate that exists to keep secrets
        # out of logs.
        print(
            "\n  (untracked pre-check skipped: the scan could not be"
            f" read - {type(exc).__name__})"
        )
        return
    if not results:
        print(
            f"\n{len(listed)} untracked file(s) checked ahead of tracking: "
            "none would be a finding."
        )
        return
    print(
        f"\nWARNING - {len(results)} UNTRACKED file(s) would become "
        "findings the moment they are tracked. Nothing is failing: they "
        "are not in the tree this gate governs. Audit or fix them BEFORE "
        "you `git add`, or the commit that adds them turns this red:"
    )
    for path, found in sorted(results.items()):
        print(f"  {path}: {len(found)} finding(s)")


def _untracked_paths(git: str) -> list[str] | None:
    """The untracked, non-ignored paths, one per element.

    SPLIT OUT SO IT CAN BE CONTROLLED. R18-M4 found `_warn_untracked`
    had no arms at all, and R18-H1 is what that cost: the listing was
    wrong and only an end-to-end run with a space in a filename could
    have shown it. This half is a pure function of git's output, so
    `controls()` can drive it over a scratch repository without
    detect-secrets and without touching this tree.
    """
    try:
        # `-z` AND `split("\0")`, NOT `.split()`. R18-H1, measured
        # with a firing control: `git ls-files` does NOT quote a
        # filename that
        # merely contains a SPACE, and `str.split()` splits on any
        # whitespace - so `my notes.md` arrived as two paths, neither of
        # which exists. detect-secrets then found nothing in either, and
        # this function printed "5 untracked file(s) checked ahead of
        # tracking: none would be a finding" over a real file holding
        # three. THE ALL-CLEAR WAS PRINTED PRECISELY WHERE IT FAILED TO
        # LOOK, and the count was inflated by the same bug. The control
        # arm differed only by deleting the space and it reported the
        # three findings correctly.
        listed = [
            path
            for path in subprocess.run(  # noqa: S603
                [git, "ls-files", "-z", "--others", "--exclude-standard"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split("\0")
            if path
        ]
    except (OSError, subprocess.CalledProcessError) as exc:
        # NONE, NOT `[]` (R19-M1). The comment here used to say that a
        # failed listing and an empty one "must not be confused by the
        # CALLER" - and then returned the same value for both, so the
        # caller's `if not listed:` printed "(no untracked files to
        # check ahead of tracking)" DIRECTLY UNDER the skip line. The
        # requirement was stated and the return value defeated it,
        # which is R18-H1's own class inside the commit that fixed
        # R18-L1. A distinct value is what makes the two distinguishable
        # rather than a comment asking the reader to keep them apart.
        print(f"\n  (untracked pre-check skipped: {type(exc).__name__})")
        return None
    return listed


# ---------------------------------------------------------------------
# Controls. They exercise the COMPARISON, which is the half this change
# introduces and the half that decides red or green. They need no
# `detect-secrets` and touch nothing, so they can run anywhere.
#
# The end-to-end arms - plant a synthetic secret in a real file and
# require RED, move a recorded line number and require GREEN - are
# `docs/reviews/probe-secrets-baseline.py`, because a control sharing a
# file with its subject shares its author's blind spot: three of four
# mutants have survived a `--self-test` in this repository before.
# ---------------------------------------------------------------------

#: THE DIGEST FIELD NAME IS BUILT, NOT WRITTEN, AND THAT IS NOT STYLE.
#: `KeywordDetector` fires on that field name followed by a quoted
#: value, so fixtures spelling it out are `Secret Keyword` findings IN
#: THIS FILE: measured, they added two unaudited findings and would have
#: turned the gate red on the very commit that introduced the gate. The
#: first attempt to explain that in a comment ADDED A THIRD, because the
#: comment quoted the pair it was warning about - this repository has
#: measured the same recursion on an exemption marker, where the most
#: careful writers expanded the hole fastest. So no line here spells the
#: pair, in code or in prose, and the recursion cannot occur rather than
#: being excused.
_DIGEST = "hashed" + "_secret"
_A = {"type": "Secret Keyword", _DIGEST: "aaa", "line_number": 1}
_B = {"type": "Secret Keyword", _DIGEST: "bbb", "line_number": 2}


def arm_verdict(arms: int, floor: int, failed: int) -> tuple[str, list[str], int]:
    """The canonical line, the diagnosis and the exit code, in ONE spot.

    **EQUALITY, NOT A LOWER BOUND (#223, the direction #193 closed for
    the two COMPUTED members).** `len(arms) >= floor` was green at
    `arms=10 floor=9 status=ok`, measured by planting a tenth arm - so
    the harness could not see its own floor go slack.

    It was not the ONLY instrument, and saying so would overstate this.
    `check-row-floor-exactness.py` statically counts the `arm(` sites
    in this file and printed "SLACK by 1", exit 1, on the same planted
    tree. That checker is the reason the hole here is narrow rather
    than open: what this change buys is a harness that fails on its own
    evidence instead of leaving the whole claim to a second file.

    **THE TALLY CANNOT SEE A LOST ARM, AND THE FLOOR CANNOT SEE A
    FAILED ONE.** `failed=0` reads exactly the same whether nine arms
    passed or eight did, so only `arms` against `floor` separates them;
    and an arm that RUNS and fails leaves `arms == floor` satisfied, so
    only `failed` catches that. Both are asserted below because neither
    can see the other's case.
    """
    status = "ok" if not failed and arms == floor else "breach"
    line = (
        f"secrets-baseline-controls: arms={arms} failed={failed}"
        f" floor={floor} status={status}"
    )
    if arms < floor:
        return (
            line,
            [
                f"::error::{arms} arms against a floor of {floor} -"
                " an arm was DELETED, which is the whole reason the"
                " floor is here."
            ],
            1,
        )
    if arms > floor:
        return (
            line,
            [
                f"::error::{arms} arms against a floor of {floor} -"
                f" arms were ADDED and the floor was not raised. It is"
                f" slack by {arms - floor}, and a slack floor says"
                f" nothing when arms go later. Raise it to {arms}."
            ],
            1,
        )
    if failed:
        return (line, [], 1)
    return (line, [], 0)


def controls() -> int:
    """Each arm names what would be true if the comparison broke."""
    arms: list[tuple[str, bool, str]] = []

    def arm(name: str, ok: bool, meaning: str) -> None:
        arms.append((name, ok, meaning))

    base = {"f.py": [dict(_A)]}

    # C1  A LINE NUMBER MOVING IS NOT A FINDING. The whole point.
    moved = {"f.py": [dict(_A, line_number=999)]}
    arm(
        "C1 line drift is invisible",
        pairs(base) == pairs(moved),
        "a line number would re-enter the key and CI would go red on any edit",
    )

    # C2  A NEW HASH IN A KNOWN FILE IS A FINDING.
    added = {"f.py": [dict(_A), dict(_B)]}
    arm(
        "C2 a new hash is caught",
        pairs(added) - pairs(base) == {("f.py", "Secret Keyword", "bbb")},
        "a secret added to an already-audited file would pass",
    )

    # C3  A KNOWN HASH IN A NEW FILE IS A FINDING. Keyed on the pair,
    #     not on the digest alone - copying an audited placeholder into
    #     a new file is a new finding.
    copied = {"f.py": [dict(_A)], "g.py": [dict(_A)]}
    arm(
        "C3 a known hash in a new file is caught",
        pairs(copied) - pairs(base) == {("g.py", "Secret Keyword", "aaa")},
        "the key would be the digest alone and a copied secret would pass",
    )

    # C4  THE SAME STRING UNDER A DIFFERENT DETECTOR IS A FINDING.
    retyped = {"f.py": [dict(_A), dict(_A, type="Base64 High Entropy String")]}
    arm(
        "C4 a second detector is caught",
        pairs(retyped) - pairs(base) == {("f.py", "Base64 High Entropy String", "aaa")},
        "type would be outside the key and a re-classified finding would pass",
    )

    # C5  THE BASELINE-SELF DROP CANNOT HIDE ANYTHING ELSE. It is the
    #     one place this checker deliberately discards findings.
    mixed = {".secrets.baseline": [dict(_A)], "real.py": [dict(_B)]}
    kept, dropped = _drop_baseline_self_findings(mixed, ".secrets.baseline")
    arm(
        "C5 the self-drop is scoped to the baseline",
        dropped == 1 and pairs(kept) == {("real.py", "Secret Keyword", "bbb")},
        "the drop would be a hole any file could hide in",
    )

    # C6  A REMOVED FINDING IS STALE, NOT NEW. The direction nothing
    #     checked before this file.
    emptied: Results = {}
    arm(
        "C6 a removed finding reads as stale",
        pairs(base) - pairs(emptied) == {("f.py", "Secret Keyword", "aaa")}
        and not pairs(emptied) - pairs(base),
        "a deletion would be reported as an unaudited new finding",
    )

    # C7-C9  THE LISTING HALF, which had NO arms at all until R18-M4
    #        said so - and R18-H1 is what that cost. Every arm drives
    #        `_untracked_paths` over a SCRATCH repository: no
    #        detect-secrets, no network, and nothing in this tree is
    #        read or written.
    git = shutil.which("git")
    if git is None:
        arm(
            "C7-C9 the listing arms could not run",
            False,
            "`git` is not on PATH, and a skipped arm is a green that tested nothing",
        )
    else:
        with tempfile.TemporaryDirectory(prefix="untracked-arms-") as tmp:
            scratch = pathlib.Path(tmp)
            for cmd in (["init", "-q"], ["config", "user.email", "a@b.invalid"]):
                subprocess.run([git, "-C", str(scratch), *cmd], check=True)  # noqa: S603
            (scratch / "plain.md").write_text("x\n")
            (scratch / "with space.md").write_text("x\n")
            (scratch / "ignored.md").write_text("x\n")
            (scratch / ".gitignore").write_text("ignored.md\n")
            cwd = pathlib.Path.cwd()
            try:
                os.chdir(scratch)
                found = _untracked_paths(git)
            finally:
                os.chdir(cwd)

            # `None` HERE IS ITSELF A FINDING, not a case to tolerate.
            # R19-M1 made the failed listing distinguishable from the
            # empty one, and mypy then refused these three arms - which
            # is the type system asking the question the arms should
            # answer. This is a scratch repository we just created; if
            # `git ls-files` failed in it, the arms below would compare
            # against nothing and pass for the wrong reason.
            if found is None:
                arm(
                    "C7-C9 the listing FAILED in the scratch repository",
                    False,
                    "the arms would run against no population at all",
                )
                found = []

            # C7  THE ONE THAT WOULD HAVE CAUGHT R18-H1. Under
            #     `.split()` this filename arrived as `with` and
            #     `space.md`, neither of which exists, so the scan
            #     found nothing in it and the run printed an all-clear.
            arm(
                "C7 a filename containing a space survives intact",
                "with space.md" in found,
                "a path with a space would be split into two nonexistent ones,"
                " and the gate would print a clean line over an unread file",
            )
            # C8  THE COUNT IS THE OTHER HALF OF THE SAME BUG: splitting
            #     one path into two also INFLATES the number reported.
            arm(
                "C8 the count matches the files",
                len(found) == 3,
                f"the reported population would be wrong; got {len(found)}: {found}",
            )
            # C9  `--exclude-standard` still honours .gitignore. Without
            #     this the fix could have been "stop excluding", which
            #     would scan files the author never chose to write.
            arm(
                "C9 an ignored file stays out of the population",
                "ignored.md" not in found,
                "the gate would warn about files .gitignore excludes",
            )

    # THE ARM FLOOR (R19-M2), and it was a MEASURED SURVIVOR before it
    # existed. `failed == 0` is satisfied by zero arms, and nothing else
    # held the count: R19 deleted C7-C9 - the three arms that exist
    # BECAUSE R18-H1 shipped - and the step stayed GREEN at
    # `arms=6 failed=0`.
    #
    # That is R18-M4's own defect one column over: M4 was "nothing makes
    # it run", this was "nothing makes it keep existing".
    #
    # THE PARAGRAPH HERE USED TO SAY this file was outside
    # `check-row-floor-exactness.py`'s container "by construction",
    # because that checker "enumerates `scripts/*.sh` so a `.py` is
    # outside it". #187 widened the container to tracked `.py` and
    # `.sh` under `scripts/` and `docs/reviews/`, and this file has
    # been a member since. MEASURED (#223): plant a tenth arm and the
    # exactness checker prints "SLACK by 1" and exits 1. The sentence
    # that argued a lower bound was harmless here was describing a
    # container that had already moved.
    #
    # DERIVED, not chosen: C1-C6 are the comparison arms, C7-C9 the
    # listing arms added with the R18-H1 fix, C10-C11 the arms that
    # exercise the verdict itself. Raise it in the commit that adds an
    # arm; lowering it is a visible diff that has to be defended.
    arm_floor = 11

    # C10-C11 ARM THE VERDICT, and they call the SAME function the
    # canonical line below is built from rather than a copy of it. A
    # self-check that re-implements the comparison it is checking
    # passes for as long as the two copies agree, which is until one
    # is edited.
    arm(
        "C10 an ADDED arm against an unraised floor is a breach",
        arm_verdict(arm_floor + 1, arm_floor, 0)[2] != 0,
        "arms could be added without the floor being raised, and a "
        "slack floor says nothing when arms go later",
    )
    arm(
        "C11 a DELETED arm is a breach, in the other direction",
        arm_verdict(arm_floor - 1, arm_floor, 0)[2] != 0,
        "the direction the floor was built for would stop firing",
    )

    failed = [a for a in arms if not a[1]]
    for name, ok, meaning in arms:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  -> {meaning}"))

    line, diagnosis, code = arm_verdict(len(arms), arm_floor, len(failed))
    print(line)
    for detail in diagnosis:
        print(detail)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--controls",
        action="store_true",
        help="run the comparison controls instead of the gate",
    )
    args = parser.parse_args()
    return controls() if args.controls else gate()


if __name__ == "__main__":
    sys.exit(main())
