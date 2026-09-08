#!/usr/bin/env python3
"""Advisory-expiry owner: steps 3 and 4 of the advisory-ignore policy.

THE POLICY IS NOT IN THIS TEMPLATE'S DESIGN.md YET. docs/DESIGN.md is a
placeholder, so the policy steps this file names are the SOURCE
project's, carried so the shape survives. Until 2026-09-08 this
docstring cited six line ranges in the 1500s of that project's design
document, every one dangling here; they are written out as steps now,
and deliberately not quoted in citation shape, because the citation
checker's regex reads any such string as live. When your DESIGN.md
gains an advisory-ignore section, cite it in this file and turn the
gate on. The instrument for catching drift afterwards is
check-design-citations.py, which is carried but cannot run until its
register file, docs/reviews/REPOINT-EXEMPT.txt, is restored: it was
not carried into the template (defect D9, with the three other
checkers that still cite the source project's line numbers).

WHY THIS EXISTS. `pip-audit` fails on ANY advisory: it has no severity
threshold, so one advisory anywhere in the transitive tree turns a
required check red and blocks every merge, including the merge that
fixes it. `fastmcp` is pinned to an exact version in pyproject.toml
(4.0.3 as of 2026-09-08) rather than a range, so we should expect
advisories against a tree that does not float, and owe them a
sanctioned response - because the unsanctioned response is a blanket
ignore, which is the silent suppression the design forbids and which
nobody ever removes.

`pip-audit` has **no expiry concept and no `pyproject.toml` ignore
section of its own**. That gap is the entire reason this script exists.
It reads `[tool.fast-mcp-template.advisory-ignores]`, emits the
`--ignore-vuln` flags `pip-audit` actually takes, and exits non-zero on
any expired entry, so an ignore cannot outlive its justification by
drifting.

**THE TABLE IS THE SINGLE SOURCE FOR BOTH THE FLAGS AND THE EXPIRY.**
Nothing here hand-maintains a second list of ids beside it. Two lists
that must agree is the defect the policy's step 4 names, and it fails
by going silently stale.

WHAT THIS DOES NOT DO, stated because a control trusted for the wrong
thing is worse than no control. **Step 1 of the policy - reachability -
is human judgement written down, and it is NOT here**
(policy step 1). This script cannot tell whether our code reaches
a vulnerable path. It enforces the SHAPE of a recorded judgement: that
one was made, was written down, named a single advisory, and carries an
expiry that has not passed. A well-formed entry with a dishonest
`reason` passes this gate cleanly.

THE FOUR FIELDS a legal entry must carry (policy step 3):

  id the advisory id. Required and non-blank. An entry without one is a
          BLANKET ignore - it suppresses every future advisory, not just
          this one - and step 4 forbids it outright.
  date the date the judgement was recorded. Required, because the 30-day
          budget is measured FROM it.
  reason a written reason the advisory is unreachable. Required and
          non-blank.
  expires the expiry. Required, no more than 30 days after `date`, and
  not in
          the past.

WHY THE 30 DAYS IS MEASURED FROM `date` AND NOT FROM NOW. Measured from
now, the budget would refill on every CI run and an entry could sit
legal forever, which is the exact drift the expiry exists to stop.
Measured from `date` the budget is fixed when the judgement is made and
cannot be extended without editing the recorded date, which is visible
in a diff.

FAIL-CLOSED. Exit 0 = every entry legal, flags on stdout. Exit 1 = an
entry was refused. Exit 2 = the gate itself could not run. A control
that fails open is worse than none, because it is trusted.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

MAX_IGNORE_DAYS = 30
"""Policy step 3: `an expiry date no more than 30 days out`."""

TABLE_PATH = ("tool", "fast-mcp-template", "advisory-ignores")
"""The single source. Nothing else in this file names an advisory id."""

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_CANNOT_RUN = 2


class AdvisoryTableError(Exception):
    """The table could not be read or is not shaped like a table."""


def _as_date(value: Any, field: str, where: str) -> dt.date:  # noqa: ANN401
    """Coerce a TOML value to a date.

    TOML parses a bare `2026-08-28` to `datetime.date` natively; a
    quoted one arrives as `str`. Both are accepted, anything else is
    refused rather than guessed at.

    Args:
        value: The raw value read from the table.
        field: The field name, for the refusal message.
        where: Which entry this is, for the refusal message.

    Returns:
        The value as a date.

    Raises:
        ValueError: The value is not a date and cannot be read as one.
    """
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError as exc:
            msg = f"{where}: {field} is not an ISO date: {value!r}"
            raise ValueError(msg) from exc
    msg = f"{where}: {field} is not a date: {value!r}"
    raise ValueError(msg)


def _looks_like(candidate: str, target: str) -> bool:
    """Is `candidate` plausibly a misspelling of `target`?

    Deliberately narrow. A prefix relationship catches the
    singular/plural slip that actually happened (`advisory-ignore` for
    `advisory-ignores`), and an equal-length one-character difference
    catches a transposition or typo. It does NOT do fuzzy distance over
    everything, because a false positive here raises on somebody's
    unrelated tool table.
    """
    if candidate.startswith(target) or target.startswith(candidate):
        return True
    if len(candidate) == len(target):
        return sum(a != b for a, b in zip(candidate, target, strict=True)) == 1
    return False


def load_entries(pyproject: Path) -> list[Any]:
    """Read the ignore table out of `pyproject.toml`.

    Args:
        pyproject: Path to the manifest holding the table.

    Returns:
        The `entries` list, empty if the table is absent.

    Raises:
        AdvisoryTableError: The file is unreadable, is not valid TOML,
            or the table is not shaped as expected.
    """
    try:
        raw = pyproject.read_bytes()
    except OSError as exc:
        msg = f"cannot read {pyproject}: {exc}"
        raise AdvisoryTableError(msg) from exc
    try:
        doc: Any = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        msg = f"cannot parse {pyproject}: {exc}"
        raise AdvisoryTableError(msg) from exc

    # FAIL-CLOSED ON A MISSPELLING, which this used to fail OPEN on.
    #
    # Walking TABLE_PATH and returning [] the moment a key is missing
    # cannot tell "no ignore table, which is the normal state" from "the
    # table is there and I spelled its name wrong". Measured before the
    # fix: renaming the table to `advisory-ignore` (no s) with a
    # SIX-YEAR-EXPIRED entry inside it exited 0 with no output and no
    # warning - a wrong zero that explains itself, and the exact shape
    # of every silent-failure defect this repository has recorded.
    #
    # So the parent table is inspected for near-misses before the
    # absence is accepted. An unrelated `[tool.something-else]` is not
    # our business; a key under `[tool]` that looks like ours and is not
    # ours is a typo, not a state.
    for depth, key in enumerate(TABLE_PATH):
        if not isinstance(doc, dict):
            msg = f"[{'.'.join(TABLE_PATH[:depth])}] is not a table"
            raise AdvisoryTableError(msg)
        if key not in doc:
            near = sorted(k for k in doc if k != key and _looks_like(k, key))
            if near:
                msg = (
                    f"[{'.'.join([*TABLE_PATH[:depth], key])}] is absent, but "
                    f"{near} is present at the same level. That is a misspelled "
                    "advisory-ignore table, not an empty one, and treating it as "
                    "empty would silently honour nothing while reporting success"
                )
                raise AdvisoryTableError(msg)
            return []
        doc = doc[key]
    if not isinstance(doc, dict):
        msg = f"[{'.'.join(TABLE_PATH)}] is not a table"
        raise AdvisoryTableError(msg)

    # An unknown key inside OUR table is a misspelling too -
    # `entires = [...]` would otherwise read as an empty table with a
    # stray value beside it.
    unknown = sorted(k for k in doc if k != "entries")
    if unknown:
        msg = (
            f"[{'.'.join(TABLE_PATH)}] carries unknown keys {unknown}. The only "
            "key here is `entries`; anything else is a typo that would leave real "
            "ignores unread"
        )
        raise AdvisoryTableError(msg)

    entries = doc.get("entries", [])
    if not isinstance(entries, list):
        msg = f"[{'.'.join(TABLE_PATH)}] entries is not an array"
        raise AdvisoryTableError(msg)
    return entries


def check_entries(
    entries: Sequence[Any],
    now: dt.date,
) -> tuple[list[str], list[str]]:
    """Validate every entry and derive the flags from those that pass.

    The clock is a PARAMETER, never read inside. A test that computes
    its fixture dates from a runtime clock and compares them against a
    runtime clock passes on any implementation, so the boundary cases
    here are only real boundaries if the caller pins both.

    Args:
        entries: The raw `entries` array from the table.
        now: The date to judge expiry against.

    Returns:
        A `(flags, refusals)` pair. `flags` holds the `--ignore-vuln`
        pairs for the entries that passed, derived from the same table
        rows that were validated. `refusals` holds one message per
        illegal entry.
    """
    flags: list[str] = []
    refusals: list[str] = []

    for index, entry in enumerate(entries):
        where = f"entry {index}"
        if not isinstance(entry, dict):
            refusals.append(f"{where}: not a table")
            continue

        advisory_id = entry.get("id")
        if not isinstance(advisory_id, str) or not advisory_id.strip():
            refusals.append(
                f"{where}: no advisory id - a BLANKET ignore, forbidden by "
                f"policy step 4"
            )
            continue
        where = f"entry {index} ({advisory_id})"

        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            refusals.append(f"{where}: no written reason the advisory is unreachable")
            continue

        if "expires" not in entry:
            refusals.append(
                f"{where}: no expiry - an ignore with no expiry never expires"
            )
            continue
        if "date" not in entry:
            refusals.append(f"{where}: no date - the 30-day budget is measured from it")
            continue

        try:
            expires = _as_date(entry["expires"], "expires", where)
            recorded = _as_date(entry["date"], "date", where)
        except ValueError as exc:
            refusals.append(str(exc))
            continue

        # M1: THE PREMISE, not just the arithmetic. The budget is
        # measured from `recorded` (ADR-0020), and until this check
        # existed nothing said `recorded` had to be in the past.
        # `date = "2030-01-01"` with `expires = "2030-01-31"` computes a
        # budget of 30, passes, and stays legal for years - the exact
        # unbounded ignore ADR-0020 chose this measurement to prevent.
        # The gate enforced the arithmetic and not the premise it rests
        # on.
        if recorded > now:
            refusals.append(
                f"{where}: recorded {recorded.isoformat()} is in the future "
                f"(today {now.isoformat()}). The 30-day budget runs from that "
                "date, so a future one is an unbounded ignore"
            )
            continue

        budget = (expires - recorded).days
        # L1: a NEGATIVE budget passed the `> MAX` check, and
        # `expires < now` only catches it when the expiry is also past.
        # An entry expiring BEFORE the day it was recorded is incoherent
        # whatever today is.
        if budget < 0:
            refusals.append(
                f"{where}: expiry {expires.isoformat()} precedes the recorded "
                f"date {recorded.isoformat()}"
            )
            continue

        if budget > MAX_IGNORE_DAYS:
            refusals.append(
                f"{where}: expiry is {budget} days after {recorded.isoformat()}, "
                f"more than the {MAX_IGNORE_DAYS} policy step 3 allows"
            )
            continue

        if expires < now:
            refusals.append(
                f"{where}: expired {expires.isoformat()} (today {now.isoformat()}) "
                f"- re-assess reachability or fix it; do not extend the date"
            )
            continue

        flags.extend(["--ignore-vuln", advisory_id])

    return flags, refusals


def main(argv: Sequence[str] | None = None) -> int:
    """Run the gate.

    Args:
        argv: Command line arguments, defaulting to `sys.argv[1:]`.

    Returns:
        0 if every entry is legal, 1 if any was refused, 2 if the gate
        could not run.
    """
    parser = argparse.ArgumentParser(
        description="Advisory-expiry gate, policy steps 3 and 4."
    )
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "pyproject.toml",
        help="the manifest holding the ignore table",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="ISO date to judge expiry against; defaults to today in UTC. "
        "Exists so the boundary cases can be tested against a pinned clock.",
    )
    args = parser.parse_args(argv)

    if args.now is None:
        now = dt.datetime.now(dt.UTC).date()
    else:
        try:
            now = dt.date.fromisoformat(args.now)
        except ValueError:
            print(f"advisory gate: --now is not an ISO date: {args.now!r}")
            return EXIT_CANNOT_RUN

    try:
        entries = load_entries(args.pyproject)
    except AdvisoryTableError as exc:
        print(f"advisory gate: {exc}")
        return EXIT_CANNOT_RUN

    flags, refusals = check_entries(entries, now)

    if refusals:
        for refusal in refusals:
            print(f"advisory gate: REFUSED {refusal}")
        print(
            f"advisory gate: {len(refusals)} illegal entry/entries; no flags emitted."
        )
        return EXIT_REFUSED

    if flags:
        print(" ".join(flags))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
