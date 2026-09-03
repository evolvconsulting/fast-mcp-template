#!/usr/bin/env python3
"""#116 container gate: no abort message may retype a seconds figure.

THE DEFECT THIS EXISTS FOR. A bounded harness holds one decision
twice - once as the operative `timeout` argument, and once retyped
into the prose that explains it:

    timeout 900 uv run --frozen pytest ...
    if [ "$baseline_rc" -eq 124 ]; then
      echo "ABORT: THE BASELINE HUNG - 900s with no result ..."

Change the bound and the message lies, at exit 0, in the exact
output a reader turns to when something has already gone wrong.
That was watched live under #108: a probe rewrote the timeout to 1
and the message still said "900s".

The remedy is that a value chosen once appears once. This checker
asserts the property over the CONTAINER rather than over a list of
files someone maintained by hand - a hand-kept list of the files to
fix is the same defect one level up, and it is blind to the file
nobody added to it.

WHAT COUNTS AS A FINDING: a shell `echo` whose text contains a bare
digit seconds figure (`900s`). A figure interpolated from a name
(`${ROW_TIMEOUT}s`, `${elapsed}s`) is derived and passes - that is
the whole point. Comments are NOT scanned: prose about a past
measurement ("24m19s and PASSES") is a dated record, not a claim
about today's bound, and the two must not be conflated.

THE ZERO IS PROVED NON-VACUOUS by `--self-test`, which runs the
same detector over a planted lying line and requires it to fire. A
detector that finds nothing because it is looking nowhere reports a
clean empty identical to a real absence.
"""

import argparse
import re
import subprocess
import sys

FIGURE = re.compile(r"(?<![\w${])\b\d+s\b")


def strip_comment(line: str) -> str:
    """Drop a trailing shell comment.

    Quote handling is crude but adequate: all we need to know is
    whether `echo` and the figure sit inside CODE rather than in a
    comment.
    """
    out: list[str] = []
    quote: str | None = None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out)


def scan_text(text: str) -> list[tuple[int, str, str]]:
    """Find every retyped seconds figure.

    Returns one `(lineno, figure, line)` per finding.
    """
    hits: list[tuple[int, str, str]] = []
    for i, raw in enumerate(text.splitlines(), 1):
        code = strip_comment(raw)
        if "echo" not in code:
            continue
        for m in FIGURE.finditer(code):
            hits.append((i, m.group(0), raw.strip()))
    return hits


def self_test() -> bool:
    """Prove the detector fires on a planted lying line."""
    planted = (
        "set -uo pipefail\n"
        "ROW_TIMEOUT=300\n"
        'timeout "$ROW_TIMEOUT" pytest x\n'
        'echo "  TIMED OUT after 300s - this row NEVER FINISHED."\n'
        'echo "  DERIVED after ${ROW_TIMEOUT}s - never finished."\n'
        "# a dated record, not a bound: the step took 24m19s in run 7\n"
    )
    figs = [f for _, f, _ in scan_text(planted)]
    if figs != ["300s"]:
        print(f"SELF-TEST FAILED: expected exactly ['300s'], got {figs}")
        return False
    print("self-test: the retyped literal `300s` FIRES              [ok]")
    print("self-test: the derived `${ROW_TIMEOUT}s` does NOT fire   [ok]")
    print("self-test: the `24m19s` in a COMMENT does NOT fire       [ok]")
    return True


def main() -> None:
    """Run the container gate, or the self-test."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--self-test",
        action="store_true",
        help="prove the detector fires on a planted lying line, then exit",
    )
    args = ap.parse_args()

    if args.self_test:
        sys.exit(0 if self_test() else 1)

    # S603/S607: a fixed argv, no shell, and `git` from PATH - the same
    # justification the sibling checkers in this directory record.
    files = subprocess.check_output(  # noqa: S603
        ["git", "ls-files", "scripts/*.sh"],  # noqa: S607
        text=True,
    ).split()
    if not files:
        print(
            "::error::the container is EMPTY - `git ls-files 'scripts/*.sh'` "
            "matched nothing. That is an instrument failure, not a clean tree."
        )
        sys.exit(2)

    findings: list[tuple[str, int, str, str]] = []
    echo_lines = 0
    for f in files:
        with open(f) as fh:
            text = fh.read()
        echo_lines += sum(
            1 for line in text.splitlines() if "echo" in strip_comment(line)
        )
        for lineno, fig, line in scan_text(text):
            findings.append((f, lineno, fig, line))

    print(f"scanned {len(files)} scripts, {echo_lines} echo lines")
    if findings:
        print(
            f"::error::{len(findings)} abort message(s) retype a seconds "
            "figure instead of deriving it:"
        )
        for f, lineno, fig, line in findings:
            print(f"  {f}:{lineno}: bare `{fig}` in: {line}")
        print(
            "::error::Bind the bound to a name and interpolate it "
            "(`${BASELINE_TIMEOUT}s`), so the message moves with the value."
        )
        sys.exit(1)
    print("0 retyped seconds figures. Every bound appears once. (#116)")
    sys.exit(0)


if __name__ == "__main__":
    main()
