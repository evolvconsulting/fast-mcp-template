#!/usr/bin/env python3
"""Task #152 - an anchor-landing outcome must not be discarded.

WHY THIS EXISTS, AND WHY IT IS NARROWER THAN THE TASK THAT ASKED FOR IT.

`scripts/lib/harness-result.sh:163` is the one `printf` that emits the
canonical HARNESS-RESULT line, and everything downstream starts from
what it ACTUALLY EMITS: the #120 census, the field-name checker,
`ci-harness-gate.sh`'s flag reader. So "which harnesses publish a
tally?" has always been answered by grepping OUTPUT - and a harness that
computes a tally and never prints it is invisible to every one of them.
#120 fixed what happens to a tally ONCE PRINTED. It said nothing about
one never printed.

#152 proposed deriving the EXPECTED publishers from each harness's
SHAPE and asserting set equality against the observed ones:
`check-*-controls.sh` publishes `fired=`, `-amputation.sh` publishes
`applied=`. THAT RULE WAS MEASURED AND IT IS WRONG, on 4 of the 6
harnesses it would have named:

  - `check-body-cap-amputation.sh` and `check-u15-gate-amputation.sh`
    `exit 1` on a non-landing row. `applied < rows` is IMPOSSIBLE at
    exit 0, so an `applied=` field would be a fabricated N/N - the exact
    thing `harness-result.sh:157-162` refuses ("a fabricated `fired=0/0`
    would be read as a harness that held zero controls - a false
    finding").
  - `check-suite-floor-amputation.sh` computes `fired`/`total`, which is
    a KILLED tally, not an anchor tally. The shape rule names the wrong
    FIELD.
  - `check-u1-boot-amputation.sh` verified anchors with `assert count ==
    1` inside 13 unguarded Python heredocs under `set -uo pipefail`. It
    had no landing tally to publish because it never CONSUMED the
    failure at all - a different and worse defect, which the shape rule
    would have papered over by demanding a field. Closed by #156, which
    also found the failure was never SILENT: the harness went red naming
    three correct tests as false instruments.

A rule that fires on N harnesses is a SEARCH. The wider rule "every
incremented counter must reach the canonical line" was also measured: 12
of 37 files, 11 of them the single `VACUOUS` class. #159 then ruled that
one out by reading every site - 10 of the 10 that compute a vacuity
counter already GATE on it at exit nonzero, so a published field would
have had no job. It is deliberately NOT gated here.

WHAT IS GATED IS THE ONE INVARIANT THAT SURVIVED READING EVERY SITE:

    A harness that diagnoses a per-row anchor-landing failure must not
    let that row continue silently. Either the branch is FATAL, or the
    harness publishes a named tally, so that the row reaches the
    canonical line as a short count.

Both arms are real: `exit` makes the invariant structural, a published
tally makes it counted. What is forbidden is the third option - print
prose, continue, and count the row as if its anchor had landed. That is
what `check-u4-client-amputation.sh` and `check-u3-audit-amputation.sh`
did, and `check-u4-client-amputation.sh:21` asserted a CI gate that read
the anchor tally while no counter, no field and no `--anchors-applied`
flag existed anywhere.

Exit codes: 0 clean, 1 findings, 2 the container came back empty or
unreadable. An instrument failure must never render as a clean tree.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# The vocabulary a harness uses to say an anchor did not land. Selected
# by
# reading all 17 `-amputation.sh` files, not guessed: these are the
# phrases
# that actually appear at a landing branch.
LANDING_DIAGNOSTIC = re.compile(
    r"DID NOT LAND|COULD NOT APPLY|ANCHOR NOT UNIQUE|ANCHOR MISSING",
    re.IGNORECASE,
)

# A harness publishes SOME named tally with this call.
# `harness_result_tally`
# validates the NAME itself (lib/harness-result.sh:113-126), so this
# cannot
# drift into accepting an unknown field.
#
# WHY ANY TALLY AND NOT `applied` SPECIFICALLY. The first draft of this
# checker
# demanded `applied=` and reported 26 findings across 14 files - the
# whole
# `-controls.sh` family. That was a SEARCH, not a diagnosis. A controls
# harness
# mutates in order to prove a control FIRES, and a mutation that does
# not land
# leaves `FIRED < TOTAL`, so the landing failure IS counted - in the
# `fired`
# tally, under the only name that fits its meaning. Demanding `applied=`
# there
# would have forced a second field with a fourth meaning into harnesses
# that
# already report the fact, which is the collapse
# lib/harness-result.sh:24-44
# exists to refuse.
#
# WHAT THAT LEAVES UNSETTLED, stated rather than gated: for a harness
# publishing `killed=$PASS/$((PASS + FAIL))`, a row that never landed
# may be
# counted in NEITHER `PASS` nor `FAIL`, which would shrink the
# denominator
# instead of failing the tally. That is a real question about 14 files
# and it
# was not settled by reading all of them, so it is reported, not
# enforced here.
PUBLISHES_TALLY = re.compile(r"^\s*harness_result_tally\s+\w+\s", re.M)

# How far past a diagnostic to look for the branch's disposition. Every
# landing
# branch measured is 1-4 lines long (`echo`, optional `echo`, optional
# restore
# `cp`, then the disposition), so 5 covers them with a line to spare.
DISPOSITION_WINDOW = 5
# A disposition is FATAL wherever it appears on the line, not only at
# its start. The `|| exit 1` guard #156 put after all 13 of
# check-u1-boot-amputation.sh's heredocs is the standard shape here,
# and an anchored `^\s*exit` cannot see it - the line begins with `[`.
#
# FOUND BY INVERTING THIS CHECK, which is the point of the inversion:
# the first run reported row H's `assert n == 1, "...DID NOT LAND"` as
# an undisposed branch. Reading the site showed the assert raises,
# python exits nonzero, and the guard three lines later exits 1. The
# branch was disposed of; the DETECTOR could not see the disposition.
# Reported as a defect it would have sent someone to "fix" a harness
# that #156 had just made correct - the misdiagnosis shape #156 itself
# found one layer down.
FATAL = re.compile(r"(^\s*(exit\s+\d+|sys\.exit\(\d*\)|die\b)|\|\|\s*exit\s+\d+)")
NONFATAL = re.compile(r"^\s*return\b")


#: Files whose landing VOCABULARY is data, not a diagnosis. `ci-harness-
#: gate.sh` holds the array of phrases every harness is checked against,
#: so its own lines match the detector while diagnosing nothing. It is
#: the READER of these diagnostics, not a producer.
#:
#: Measured rather than assumed: it holds 6 matching lines, 2 of them
#: comments already excluded, and 4 are the VOCABULARY entries at 74-77.
#: It is NOT excluded by the tally check - its only
#: `harness_result_tally` occurrence is inside an `echo`, so the
#: anchored PUBLISHES_TALLY does not match. I expected the early return
#: to cover it and it does not; R16 was right.
EXEMPT_VOCABULARY: dict[str, str] = {
    "ci-harness-gate.sh": (
        "holds the VOCABULARY array every harness's diagnostics are "
        "matched against. Its lines are the phrase list itself, not a "
        "branch that diagnoses a landing failure."
    ),
}
assert all(v.strip() for v in EXEMPT_VOCABULARY.values()), (
    "a blank reason is not an exemption"
)


def container() -> list[Path]:
    """Enumerate the container, never a hand-written list (#115).

    `scripts/lib/` holds the sourced library, not harnesses; it
    defines the diagnostics rather than emitting them.
    """
    out = subprocess.run(
        ["git", "ls-files", "scripts/*.sh"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [Path(f) for f in out if not f.startswith("scripts/lib/")]


def findings_for(path: Path) -> list[tuple[int, str, str]]:
    """Landing diagnostics whose branch neither exits nor is counted."""
    if path.name in EXEMPT_VOCABULARY:
        return []
    text = path.read_text()
    if PUBLISHES_TALLY.search(text):
        # The harness publishes a named tally, so a non-landing row
        # reaches
        # the canonical line as a short count for the gate to read. A
        # non-fatal branch is then legitimate. What this gate forbids is
        # a
        # landing failure in a harness that publishes NOTHING - where
        # the row
        # is counted in `rows=` exactly as if its anchor had landed, and
        # no
        # field anywhere records that it did not.
        return []

    lines = text.splitlines()
    out: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        if not LANDING_DIAGNOSTIC.search(line):
            continue
        # A comment is prose ABOUT the diagnostic, not the diagnostic.
        # This
        # repo has measured five times that a grep for a defect pattern
        # finds
        # the comment forbidding it.
        if line.lstrip().startswith("#"):
            continue
        window = lines[i + 1 : i + 1 + DISPOSITION_WINDOW]
        # REPORT UNLESS POSITIVELY DISPOSED OF (R16-M2). This used to
        # report only when the window held a `return`, so a branch that
        # printed the diagnostic and FELL THROUGH was neither fatal nor
        # counted, and was not reported - while the docstring above
        # states the invariant as "either FATAL or publishes a tally".
        # The prose was right and the code enforced the narrower half.
        #
        # Measured both ways with a planted TRACKED script: fall-through
        # gave 0 findings at exit 0; the same file with `return 1` gave
        # 1 finding at exit 1.
        if any(FATAL.search(w) for w in window):
            continue
        shape = (
            "returns" if any(NONFATAL.search(w) for w in window) else "falls through"
        )
        out.append((i + 1, line.strip(), shape))
    return out


def self_test() -> int:
    """Prove the inverted rule sees both shapes, in a scratch clone.

    EVERY ARM ASSERTS THE POPULATION SIZE, not just the finding count.
    R16's own arm for this finding was VACUOUS because `container()`
    reads `git ls-files` and its plant was UNTRACKED - the scan saw 37
    scripts and none of them was the fixture, so "0 findings" said
    nothing. Only the printed count told it. That is #163's trap and it
    has now bitten twice, so the size is asserted here rather than
    trusted.

    Nothing in the working tree is written: the fixtures are committed
    into a throwaway `git archive` clone.
    """
    import shutil
    import subprocess
    import tarfile
    import tempfile

    # THREE parents: this file is docs/reviews/<name>.py, so two lands
    # in docs/ and the archive extracts a tree with no docs/reviews in
    # it. The first version did exactly that and died on the copy.
    root = Path(__file__).resolve().parent.parent.parent
    fall = (
        "#!/usr/bin/env bash\n"
        "harness_result_ran 1 0\n"
        'if [ "$n" -ne 1 ]; then\n'
        '  echo "DID NOT LAND - the anchor moved"\n'
        "fi\n"
        "echo done\n"
    )
    results: list[tuple[bool, str, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "w"
        work.mkdir()
        # NO SHELL. `git archive | tar -x` needs a pipeline, and a
        # shell=True call in a checker is both an S602 finding and a
        # quoting hazard for a path nobody controls. Archive to a file,
        # extract with the stdlib.
        bundle = Path(tmp) / "tree.tar"
        subprocess.run(
            ["git", "-C", str(root), "archive", "-o", str(bundle), "HEAD"],
            check=True,
        )
        with tarfile.open(bundle) as tar:
            tar.extractall(work, filter="data")
        shutil.copy(__file__, work / "docs/reviews/check-landing-published.py")
        # `container()` reads `git ls-files`, so the scratch tree must
        # be a real repository or every fixture is invisible and arms
        # passes on an empty population - the exact vacuity this
        # self-test exists to rule out.
        for cmd in (
            ["git", "-C", str(work), "init", "-q"],
            ["git", "-C", str(work), "add", "-A"],
            [
                "git",
                "-C",
                str(work),
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-qm",
                "base",
            ],
        ):
            subprocess.run(cmd, check=True, capture_output=True)

        def run() -> tuple[int, str]:
            done = subprocess.run(
                [sys.executable, "docs/reviews/check-landing-published.py"],
                cwd=work,
                capture_output=True,
                text=True,
                check=False,
            )
            return done.returncode, done.stdout + done.stderr

        # THE BASELINE COMES FROM THE CHECKER'S OWN OUTPUT, not from
        # `git ls-files scripts/*.sh`. My first version used the latter
        # and expected 39 where the checker scans 38: `container()`
        # excludes `scripts/lib/`, so the two populations differ by
        # exactly the sourced library. Comparing a count to a DIFFERENT
        # instrument's count is the 80-vs-78 shape, in the arm whose
        # whole job is to prove the population is right.
        base_rc, base_out = run()
        base_match = re.search(r"(\d+) scripts scanned", base_out)
        if base_rc != 0 or not base_match:
            print("  BROKEN CONTROL: the unmutated clone is not clean")
            print(f"    exit {base_rc}: {base_out.strip()[:200]}")
            return 1
        base = int(base_match.group(1))

        for label, body, want_rc in (
            ("A1 a FALL-THROUGH diagnostic is reported", fall, 1),
            (
                "A2 the same branch made fatal is not",
                # `exit 1` ON ITS OWN LINE. FATAL matches a line START
                # or a `|| exit N`; `echo "..."; exit 1` is NEITHER, and
                # my first fixture used exactly that - so A2 reported a
                # failure that was really my fixture not being fatal at
                # all. A control's fixture is as much a subject as the
                # code it tests.
                fall.replace(
                    '  echo "DID NOT LAND - the anchor moved"\n',
                    '  echo "DID NOT LAND - the anchor moved"\n  exit 1\n',
                ),
                0,
            ),
        ):
            (work / "scripts/zz-selftest-fixture.sh").write_text(body)
            subprocess.run(
                ["git", "-C", str(work), "add", "-A"], check=True, capture_output=True
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(work),
                    "-c",
                    "user.email=t@t",
                    "-c",
                    "user.name=t",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                check=True,
                capture_output=True,
            )
            rc, out = run()
            scanned = re.search(r"(\d+) scripts scanned", out)
            n = int(scanned.group(1)) if scanned else -1
            tracked = n == base + 1
            results.append(
                (
                    rc == want_rc and tracked,
                    label,
                    f"exit {rc} (want {want_rc}); scanned {n}, expected"
                    f" {base + 1} - the fixture IS in the population: {tracked}",
                )
            )

    for ok, label, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}: {detail}")
    passed = sum(1 for ok, _, _ in results if ok)
    print(f"\n{passed}/{len(results)} arms passed.")
    return 0 if passed == len(results) else 1


def main() -> int:
    files = container()
    if not files:
        print(
            "::error::check-landing-published: the container `git ls-files "
            "'scripts/*.sh'` came back EMPTY.\n"
            "         That is an instrument failure, not a clean tree, so this "
            "exits 2 rather than 0.",
            file=sys.stderr,
        )
        return 2

    total = 0
    for path in sorted(files):
        for lineno, snippet, shape in findings_for(path):
            total += 1
            print(
                f"::error file={path},line={lineno}::{path}:{lineno} "
                f"an anchor-landing failure is diagnosed and then discarded"
            )
            print(f"    {snippet}")
            print(
                f"    The branch {shape}, so the row is counted as having run "
                "with an anchor that never landed."
            )
            print(
                "    FIX: either make the branch fatal (`exit 1`), or count "
                "landings and call"
            )
            print(
                '         `harness_result_tally applied "$APPLIED" "$ROWS"` so '
                "the gate can read"
            )
            print("         it with `--anchors-applied`.")

    scanned = len(files)
    published = sum(1 for p in files if PUBLISHES_TALLY.search(p.read_text()))
    print(
        f"check-landing-published: {scanned} scripts scanned, "
        f"{published} publish a tally, {total} finding(s)"
    )
    return 1 if total else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    sys.exit(main())
