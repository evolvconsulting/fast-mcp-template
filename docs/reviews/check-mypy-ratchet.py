#!/usr/bin/env python3
"""The set of mypy errors may not grow.

    python3 docs/reviews/check-mypy-ratchet.py
    python3 docs/reviews/check-mypy-ratchet.py --record  # on adoption

**WHY THIS EXISTS - the same argument as the coverage ratchet.** Full
strictness on a repository that has never had a type gate is not a
setting, it is a project. Measured on a real adoption, 2026-09-03:
**158 errors across 20 files** (131 in `src/`, 27 in `tests/`;
union-attr 72, no-untyped-def 27, type-arg 16, call-overload 15,
return-value 13, no-any-return 5, and 10 others). Shipping that as a
gate means every one of the nine planned migrations opens with a red
build, and a gate that lands red is one people learn to ignore.

**STRICTNESS IS NOT WEAKENED, AND THAT IS THE POINT.** The setting in
`pyproject.toml` is untouched: mypy still runs at full strictness and
still reports every one of those 158 errors, in full, on every run.
What changes is the GATE - what makes the build red is a NEW error,
not the inherited ones. Only the cliff is removed.

## A SET, NOT A COUNT (#151)

The baseline records `path<TAB>code<TAB>count`. A bare count would let
one error clearing and another arriving cancel to the same total while
the sets diverged - a green that says the codebase is unchanged when two
things changed. So the comparison is per (file, code) pair.

**IT FAILS IN BOTH DIRECTIONS, deliberately.** A new error is a
regression. A FIXED error is also a failure, because a baseline nobody
shrinks is a permanent allowance: the errors get fixed, the file keeps
excusing them, and six months later it is a list of problems this
repository does not have. Both messages say exactly which pairs moved
and which way.

## Why (file, code) and not (file, line, code)

Line numbers churn on every edit, so a line-keyed baseline would be red
on any change and would be re-recorded blindly - a ratchet that has
stopped ratcheting. (file, code) is coarse enough to survive a rename
inside a file and fine enough that a genuinely new mistake in a new
place still shows up. The COUNT per pair is what catches a second
instance of an error the file already has.

## The baseline is never invented

An absent baseline is exit 2 with the command to record one, never a
default and never a pass. A checker that invents its own threshold is
a floor wearing a ratchet's name.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
BASELINE = ROOT / "docs" / "mypy-baseline.txt"

#: `path:line: error: message  [code]`. The code is the last bracketed
#: token on the line, which is where mypy puts it.
ERROR = re.compile(
    r"^(?P<path>[^:]+):\d+:(?:\d+:)? error: .*\[(?P<code>[a-z0-9-]+)\]\s*$"
)


def run_mypy() -> list[str]:
    """Mypy output lines. Its exit code is EXPECTED to be non-zero."""
    done = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-error-summary", "--no-color-output"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = done.stdout + done.stderr
    # EXIT 2 IS MYPY SAYING IT COULD NOT RUN - a bad config, an
    # unreadable file - as distinct from exit 1, "I found errors". Only
    # the second is a measurement. Treating them alike is how a broken
    # type gate reports a clean baseline.
    if done.returncode not in (0, 1):
        print(f"mypy exited {done.returncode}, which is not a measurement:")
        print(output)
        print("This is a BROKEN INSTRUMENT, not a finding. Exit 3.")
        raise SystemExit(3)
    return output.splitlines()


def measure() -> Counter[tuple[str, str]]:
    """Errors as a Counter over (path, code)."""
    found: Counter[tuple[str, str]] = Counter()
    for line in run_mypy():
        match = ERROR.match(line.strip())
        if match:
            found[(match.group("path"), match.group("code"))] += 1
    return found


def load() -> Counter[tuple[str, str]] | None:
    """The recorded baseline, or None when the file does not exist.

    An EMPTY baseline file is a legitimate measurement - it is what a
    type-clean repository records - and is returned as an empty Counter,
    which is a different thing from None.
    """
    if not BASELINE.exists():
        return None
    recorded: Counter[tuple[str, str]] = Counter()
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        path, code, count = line.split("\t")
        recorded[(path, code)] = int(count)
    return recorded


def record(found: Counter[tuple[str, str]]) -> int:
    """Write the baseline."""
    lines = [
        "# MYPY RATCHET BASELINE, measured - never decreed.",
        "#",
        "# One row per (file, error code), with how many of that pair exist.",
        "# Written by:",
        "#   python3 docs/reviews/check-mypy-ratchet.py --record",
        "#",
        "# `strict = true` is UNCHANGED in pyproject.toml. mypy still reports",
        "# every error below on every run. This file only decides which of",
        "# them make the BUILD red: the new ones.",
        "#",
        "# Rows come OUT of this file as they are fixed, in the same commit",
        "# as the fix. A baseline nobody shrinks is a permanent allowance.",
    ]
    for (path, code), count in sorted(found.items()):
        lines.append(f"{path}\t{code}\t{count}")
    BASELINE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    total = sum(found.values())
    print(f"Recorded {total} error(s) across {len(found)} (file, code) pair(s)")
    print(f"  in {BASELINE.relative_to(ROOT)}")
    print("COMMIT IT. An unrecorded baseline ratchets nothing.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="the mypy error set may not grow")
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()

    found = measure()
    print(
        f"Measured: {sum(found.values())} error(s), "
        f"{len(found)} (file, code) pair(s)"
    )

    if args.record:
        return record(found)

    baseline = load()
    if baseline is None:
        print()
        print("NO MYPY BASELINE HAS BEEN RECORDED IN THIS REPOSITORY.")
        print("This is a TASK, not a broken instrument. On adoption:")
        print("  python3 docs/reviews/check-mypy-ratchet.py --record")
        print("then commit docs/mypy-baseline.txt.")
        print()
        print("It is NOT defaulted to zero. `strict = true` from a standing")
        print("start measured 158 errors in 20 files on a real repository,")
        print("and a gate that lands red is one people learn to ignore.")
        print("Exit 2.")
        return 2

    print(f"Baseline: {sum(baseline.values())} error(s), {len(baseline)} pair(s)")

    worse = {
        k: (baseline.get(k, 0), v)
        for k, v in found.items()
        if v > baseline.get(k, 0)
    }
    better = {
        k: (v, found.get(k, 0))
        for k, v in baseline.items()
        if found.get(k, 0) < v
    }

    if worse:
        print()
        print(f"{len(worse)} (file, code) pair(s) got WORSE:")
        for (path, code), (was, now) in sorted(worse.items()):
            print(f"  {path}  [{code}]  {was} -> {now}")
        print()
        print("These are NEW type errors. Fix them, or - if one is genuinely")
        print("unavoidable - re-record in the SAME commit so a reviewer sees")
        print("the allowance being granted.")
        return 1

    if better:
        print()
        print(f"{len(better)} (file, code) pair(s) got BETTER:")
        for (path, code), (was, now) in sorted(better.items()):
            print(f"  {path}  [{code}]  {was} -> {now}")
        print()
        print("RE-RECORD IT, in this commit:")
        print("  python3 docs/reviews/check-mypy-ratchet.py --record")
        print()
        print("A baseline nobody shrinks becomes a list of problems this")
        print("repository no longer has, still being excused. Exit 1.")
        return 1

    print("\nThe mypy error set is exactly its recorded baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
