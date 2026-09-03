#!/usr/bin/env python3
"""Print the pytest node ids that executed the lines an anchor spans.

    printf '%s' "$OLD_ANCHOR" \
      | COVERAGE_DB=/path/to/.coverage \
        python3 scripts/lib/select-covering-tests.py src/pkg/x.py

WHY THIS IS NOT A WEAKENING (#238). An amputation row's verdict is
"did any test go red". A test that never EXECUTES the mutated
statements cannot go red because of them, so running only the tests
that did execute them asks the identical question at a fraction of
the cost. Every anchor these harnesses mutate sits inside a function
body, so the statements' executions are attributed to real test
contexts, not to import time.

The failure directions are chosen deliberately:

  * The coverage database is missing, the anchor is absent, or the
    anchor is not unique -> exit 2 and print NOTHING. The caller
    must abort; a selection computed from a wrong precondition is a
    silent wrong zero.
  * The anchor resolves but NO in-process test covered its lines ->
    exit 4 and print nothing. The caller runs the FULL suite for
    that row: the kill may live in a subprocess-driving test the
    in-process map cannot see, and "run everything" is the fail-safe
    wide answer, never "run nothing".

THE SUBPROCESS BLIND SPOT IS NOT ONLY AN EMPTY-SELECTION PROBLEM, and
the rc=4 fallback above does not cover it. A row can have plenty of
in-process coverage AND a killer that only reaches these lines through
a spawned server; that killer is simply absent from the returned set.
#286 measured one: U9 row A14 selects 8 ids and kills, while the full
suite kills with 5, the four extra being `spawn_marker_server` tests in
tests/test_boot.py and tests/test_shutdown.py. So the first paragraph's
premise should be read precisely - "never EXECUTES ... IN THIS PROCESS".
The consequence is one-directional and safe: the returned ids are a
SUBSET of the suite, so this can under-report a row's killers or turn a
real kill into a loud vacuous row, never turn a vacuous row green.

The database comes from the SAME run's baseline (`pytest --cov
--cov-context=test`), so it can never be stale against the tree
being mutated. Contexts are read from the `arc` table because this
project measures branch coverage (pyproject sets `branch = true`).
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: select-covering-tests.py <src-file-relpath>", file=sys.stderr)
        return 2
    rel = sys.argv[1]
    db_path = os.environ.get("COVERAGE_DB", "")
    if not db_path or not pathlib.Path(db_path).is_file():
        print(f"COVERAGE_DB missing or not a file: {db_path!r}", file=sys.stderr)
        return 2

    anchor = sys.stdin.read()
    if not anchor:
        print("no anchor text on stdin", file=sys.stderr)
        return 2

    src = pathlib.Path(rel)
    if not src.is_file():
        print(f"source file does not exist: {rel}", file=sys.stderr)
        return 2
    text = src.read_text(encoding="utf-8")
    n = text.count(anchor)
    if n != 1:
        # The same uniqueness rule the harnesses already enforce before
        # mutating; a non-unique anchor selects for the wrong lines.
        print(f"anchor not unique in {rel}: {n} hits", file=sys.stderr)
        return 2
    start = text[: text.index(anchor)].count("\n") + 1
    end = start + anchor.count("\n")

    db = sqlite3.connect(db_path)
    try:
        file_ids = [
            fid
            for (fid, path) in db.execute("SELECT id, path FROM file")
            if path.endswith("/" + rel) or path == rel
        ]
        if len(file_ids) != 1:
            print(
                f"{rel} matches {len(file_ids)} file rows in the coverage db; "
                "the join is wrong and a wrong join reports a reassuring zero",
                file=sys.stderr,
            )
            return 2
        contexts: set[str] = set()
        rows = db.execute(
            "SELECT DISTINCT c.context FROM arc a JOIN context c "
            "ON a.context_id = c.id WHERE a.file_id = ? "
            "AND ((ABS(a.fromno) BETWEEN ? AND ?) "
            "  OR (ABS(a.tono) BETWEEN ? AND ?))",
            (file_ids[0], start, end, start, end),
        )
        for (ctx,) in rows:
            if not ctx:
                continue
            node = ctx.split("|", 1)[0]  # strip the |setup / |teardown phase
            if "::" in node:
                contexts.add(node)
    finally:
        db.close()

    if not contexts:
        print(
            f"no in-process test covered {rel}:{start}-{end}; "
            "caller must fall back to the full suite",
            file=sys.stderr,
        )
        return 4
    print(" ".join(sorted(contexts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
