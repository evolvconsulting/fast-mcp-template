#!/usr/bin/env python3
r"""Task #240: mutated source FILE -> the tests that actually cover it.

METHOD, stated because a map whose method is not stated is not
a measurement.

`pytest --cov-context=test` makes coverage.py record, per measured
line or arc, WHICH test was running when it executed. That is a
dynamic per-test record, not a static import graph and not a guess
from file names: a test that imports a module but never runs a line
in it does NOT appear. This reads the resulting SQLite directly:

    file(id, path)         one row per measured source file
    context(id, context)   one row per dynamic context; pytest-cov
                           writes "<nodeid>|<phase>", where phase is
                           setup, run or teardown
    line_bits(file_id, context_id, numbits)   LINE coverage
    arc(file_id, context_id, fromno, tono)    BRANCH coverage

BOTH TABLES ARE READ, and that is not defensiveness. This project
runs `branch = true`, so coverage.py writes `arc` and leaves
`line_bits` EMPTY. The first version of this script read only
`line_bits`, got zero rows, and would have reported "no test covers
any file" with a perfectly plausible story attached. A clean zero
that explains itself is the bug: the join key was wrong, not the
codebase. The counts of both tables are printed so the next reader
can see which one carried the data.

So "the tests covering FILE" is the set of DISTINCT node ids in
either table for that file, with the "|phase" suffix stripped and
the EMPTY context dropped and counted separately.

WHY THE EMPTY CONTEXT IS DROPPED. Every module imported at
collection time runs its top-level lines under the empty context.
Folding that into the per-test count would make every file look
covered by all tests or by none, depending only on how you rounded
it - which is exactly the clean-zero / clean-888 pair this task was
warned about.

USAGE

    COVERAGE_FILE=/tmp/prof240/.coverage-ctx \\
      uv run --frozen pytest tests -q -p no:cacheprovider \\
        --cov=src/fast_mcp_template --cov-context=test --cov-report=
    python3 scripts/coverage-test-map.py \\
        --data /tmp/prof240/.coverage-ctx --total 888 \\
        --harnesses --phases run
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import sqlite3
import sys

HARNESS_DIR = pathlib.Path(__file__).resolve().parent

# The two tables coverage.py may put per-context data in. A LITERAL
# TUPLE, not a parameter: these names are interpolated into SQL, and
# a name arriving from anywhere else would be an injection seat.
DATA_TABLES = ("line_bits", "arc")


def harness_subjects() -> dict[str, list[str]]:
    """Map each harness to the src/ files its own source names.

    Read from the harness's OWN SOURCE, the same derivation
    ci-harness-gate.sh uses for its vocabulary, so a harness that
    changes subject cannot leave a stale row here.
    """
    pat = re.compile(r'^[A-Z_]+="(src/[^"]+)"', re.M)
    out: dict[str, list[str]] = {}
    for p in sorted(HARNESS_DIR.glob("check-*.sh")):
        subs = pat.findall(p.read_text())
        if subs:
            out[p.name] = sorted(set(subs))
    return out


def load_map(
    data_path: pathlib.Path,
    phases: tuple[str, ...] | None = None,
) -> tuple[dict[str, set[str]], dict[str, int]]:
    """Return file -> covering node ids and file -> bare rows."""
    if not data_path.exists():
        sys.exit(
            f"no coverage data at {data_path} - run pytest --cov-context=test first"
        )
    con = sqlite3.connect(f"file:{data_path}?mode=ro", uri=True)
    rows: list[tuple[str, str]] = []
    counts: dict[str, int] = {}
    try:
        for table in DATA_TABLES:
            got = con.execute(
                "SELECT DISTINCT f.path, c.context "  # noqa: S608 - literal
                f"FROM {table} t "
                "JOIN file f ON f.id = t.file_id "
                "JOIN context c ON c.id = t.context_id"
            ).fetchall()
            counts[table] = len(got)
            rows.extend(got)
    except sqlite3.OperationalError as exc:
        sys.exit(f"cannot read {data_path}: {exc}")
    finally:
        con.close()

    print(
        f"SOURCE TABLES  line_bits={counts.get('line_bits')} "
        f"arc={counts.get('arc')}   "
        "(branch=true puts the data in arc; line_bits empty is NORMAL)"
    )

    if not rows:
        sys.exit(
            f"{data_path} has ZERO (file, context) rows in BOTH "
            "line_bits and arc. Either --cov-context=test was not "
            "passed or nothing was measured. A clean empty here is "
            "the bug, not the answer."
        )

    covering: dict[str, set[str]] = {}
    bare: dict[str, int] = {}
    for path, ctx in rows:
        rel = os.path.relpath(path, os.getcwd())
        if not ctx:
            bare[rel] = bare.get(rel, 0) + 1
            continue
        nodeid, _, phase = ctx.partition("|")
        if phases is not None and phase not in phases:
            continue
        covering.setdefault(rel, set()).add(nodeid)
    return covering, bare


PHASE_HELP = (
    "comma-separated pytest-cov phases to keep "
    "(setup,run,teardown). Empty = all. `run` alone excludes the "
    "fixture traffic that makes an autouse fixture look like "
    "universal coverage: tests/conftest.py's autouse breaker reset "
    "calls jobvite_client.reset_breaker(), so ALL 888 tests touch "
    "that file in setup AND teardown through exactly 3 arcs of one "
    "2-line helper."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=".coverage", type=pathlib.Path)
    ap.add_argument("--total", type=int, default=0, help="suite size, for the % column")
    ap.add_argument(
        "--harnesses", action="store_true", help="also print the per-harness join"
    )
    ap.add_argument("--phases", default="", help=PHASE_HELP)
    args = ap.parse_args()

    phases = tuple(p for p in args.phases.split(",") if p) or None
    print(f"PHASES {phases or 'ALL (setup+run+teardown)'}")
    covering, bare = load_map(args.data, phases)

    print(
        f"DATA {args.data}  measured_files={len(covering)}  "
        f"files_with_import_only_rows={len(bare)}"
    )
    print()
    print(f"{'covering tests':>14}  {'% of suite':>10}  source file")
    for path in sorted(covering, key=lambda p: (-len(covering[p]), p)):
        n = len(covering[path])
        pct = f"{100.0 * n / args.total:.1f}%" if args.total else "-"
        print(f"{n:>14}  {pct:>10}  {path}")

    if args.harnesses:
        print()
        print("PER-HARNESS JOIN - a harness's covering set is the UNION")
        print("over its subjects: one row mutates one file, but the rows")
        print("of one harness sit on several, and a per-harness selection")
        print("would have to run the union.")
        print()
        print(f"{'union':>7}  {'% of suite':>10}  harness")
        subs = harness_subjects()
        unions = {
            name: set().union(*(covering.get(s, set()) for s in files))
            for name, files in subs.items()
        }
        for name in sorted(unions, key=lambda k: (-len(unions[k]), k)):
            missing = [s for s in subs[name] if s not in covering]
            u = len(unions[name])
            pct = f"{100.0 * u / args.total:.1f}%" if args.total else "-"
            tail = f"   [NOT MEASURED: {' '.join(missing)}]" if missing else ""
            print(f"{u:>7}  {pct:>10}  {name}{tail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
