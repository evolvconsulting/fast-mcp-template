#!/usr/bin/env python3
"""Coverage may not fall below what this project has already reached.

    uv run --frozen pytest --cov --cov-report=json:coverage.json
    python3 docs/reviews/check-coverage-ratchet.py
    python3 docs/reviews/check-coverage-ratchet.py --record

**WHY THIS REPLACED `fail_under = 80`.** A fixed floor in a template
meant for EXISTING repositories is red by construction. Measured on a
real adoption, 2026-09-03: the subject repo's coverage is **7.45%**
(2,829 statements, 2,581 missed, 26 tests). Reaching 80 there is roughly
200 additional tests - derived from that repo's own observed density of
~9.5 statements per test, and labelled an estimate because it is one.

That is not a migration step, it is a project. And a gate that cannot
go green gets switched off, which is how 119 consecutive CI failures
went unread on the repo this machinery came from. **Switched-off and
broken render identically.**

**SO THE THRESHOLD IS MEASURED, NOT DECREED.** Run `--record` on the day
you adopt the template. Whatever the number is - 7% or 94% - it becomes
the line, and the only rule is that it may not go DOWN. A project at 7%
gets a gate that works from day one and that ratchets up as tests land,
instead of a red build it learns to ignore.

**THIS IS NOT LOWERING A FLOOR TO REACH GREEN**, and the distinction is
the whole point. Lowering a floor hides a regression. A ratchet records
where you actually are and then refuses to let you slide - it makes the
same regression IMPOSSIBLE TO MISS, at every level, including the low
ones a fixed floor was silently ignoring because the build was already
red for other reasons.

**IMPROVEMENT IS NOT SILENT EITHER.** Rising above the baseline prints a
loud instruction to re-record. A ratchet nobody advances is a floor with
extra steps, and the number quietly stops describing the project.

**THE PRECEDENT IS `check-review-coverage.py`**, which enforces a
recorded backlog rather than demanding zero, for exactly this reason.
That file argues the principle; this one applies it to the number the
template actually shipped wrong.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
BASELINE = ROOT / "docs" / "coverage-baseline.txt"
REPORT = ROOT / "coverage.json"

#: How far coverage may drift DOWN before this is called a
#: regression, in percentage points.
#:
#: NOT ZERO, and the reason is arithmetic rather than leniency. Total
#: coverage is a ratio, so adding a fully-tested module still moves
#: the last decimal place; a zero-tolerance ratchet would go red on
#: rounding and teach people to re-record without reading, which is a
#: ratchet that has stopped ratcheting. A tenth of a point is far
#: below any real regression - deleting one covered line of ten
#: thousand is 0.01 - and far above float noise.
TOLERANCE = 0.1


def measured() -> float:
    """Total coverage percent from `coverage.json`, or refuse."""
    if not REPORT.exists():
        print(f"{REPORT.name} is missing. Nothing to compare.")
        print("Produce it first:")
        print("  uv run --frozen pytest --cov --cov-report=json:coverage.json")
        print("This is a BROKEN INSTRUMENT, not a finding. Exit 3.")
        raise SystemExit(3)

    data = json.loads(REPORT.read_text(encoding="utf-8"))
    totals = data.get("totals", {})
    percent = totals.get("percent_covered")
    if not isinstance(percent, (int, float)):
        print(f"{REPORT.name} carries no totals.percent_covered. Exit 3.")
        raise SystemExit(3)

    statements = totals.get("num_statements", 0)
    if not statements:
        # ZERO STATEMENTS IS A PERFECT SCORE OVER NOTHING. `coverage`
        # reports 100% for an empty population, and a ratchet that
        # accepted it would record 100 and then fail forever the moment
        # real code arrived. An empty population reports full coverage,
        # which means nothing here.
        print("coverage measured ZERO STATEMENTS. An empty population")
        print("reports full coverage, which would mean nothing. Exit 3.")
        raise SystemExit(3)

    print(f"Measured: {percent:.2f}% over {statements} statements")
    return float(percent)


def recorded() -> float | None:
    """The baseline, or None when it has never been recorded."""
    if not BASELINE.exists():
        return None
    text = BASELINE.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return float(stripped)
    return None


def record(percent: float) -> int:
    """Write the baseline, with the note a later reader needs."""
    BASELINE.write_text(
        "# COVERAGE RATCHET BASELINE, measured - never decreed.\n"
        "#\n"
        "# Written by:\n"
        "#   uv run --frozen pytest --cov --cov-report=json:coverage.json\n"
        "#   python3 docs/reviews/check-coverage-ratchet.py --record\n"
        "#\n"
        "# It may go UP. It may not go DOWN. Raising it is a commit that\n"
        "# says so; lowering it is a commit that has to be defended.\n"
        f"{percent:.2f}\n",
        encoding="utf-8",
    )
    print(f"Recorded {percent:.2f}% in {BASELINE.relative_to(ROOT)}")
    print("COMMIT IT. An unrecorded baseline ratchets nothing.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="coverage may not regress")
    parser.add_argument(
        "--record",
        action="store_true",
        help="write the current measurement as the baseline",
    )
    args = parser.parse_args()

    percent = measured()

    if args.record:
        return record(percent)

    baseline = recorded()
    if baseline is None:
        print()
        print("NO COVERAGE BASELINE HAS BEEN RECORDED IN THIS REPOSITORY.")
        print("This is a TASK, not a broken instrument. On adoption:")
        print("  python3 docs/reviews/check-coverage-ratchet.py --record")
        print("then commit docs/coverage-baseline.txt.")
        print()
        print("It is NOT defaulted to a number. A ratchet that invents its")
        print("own baseline is a floor wearing a ratchet's name, and the")
        print("number it invents is the one that made this template")
        print("unusable on a real repository. Exit 2.")
        return 2

    print(f"Baseline: {baseline:.2f}%  (tolerance {TOLERANCE})")

    if percent < baseline - TOLERANCE:
        print()
        print(f"COVERAGE REGRESSED: {baseline:.2f}% -> {percent:.2f}%")
        print(f"  down {baseline - percent:.2f} points")
        print()
        print("Add tests for what you just wrote, or - if the drop is")
        print("deliberate and defensible - re-record the baseline in the")
        print("SAME commit, where a reviewer can see it.")
        return 1

    if percent > baseline + TOLERANCE:
        print()
        print(f"COVERAGE IMPROVED: {baseline:.2f}% -> {percent:.2f}%")
        print("RE-RECORD IT, in this commit:")
        print("  python3 docs/reviews/check-coverage-ratchet.py --record")
        print()
        print("A ratchet nobody advances is a floor, and the recorded")
        print("number quietly stops describing the project. Exit 1.")
        return 1

    print("\nCoverage holds at its recorded baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
