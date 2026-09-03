#!/usr/bin/env python3
"""Subject-free mutation sweep for check-coupling.py.

It chooses nothing.

Why this exists, and why it is not the same thing as
check-coupling-controls.py.

The controls harness is 21 hand-written mutations. Each one names its
subject row and its substitution, both picked by whoever wrote the check
being tested. That is the FIX-8 lesson, already recorded in
check-coupling.py's docstring: **a control whose subject is chosen from
the covered set can only confirm the coverage it was chosen from.** The
lesson was recorded and then immediately re-committed - the two newest
control arms (16a, 16b) chose C1-S1 and C1-D1, rows the mutation they
encode was designed around.

Round 5 (DESIGN-R5.md, H1) found the fifth gate defect by not choosing:
it took EVERY row naming a §8 case and substituted EVERY recognised
disposition. 152 runs. The 21 controls had found zero escapes; the sweep
found 19, covering every row that names a test and all four Critical
rows. This file is that sweep, landed so it runs on demand instead of
living in a review transcript.

What it does:
  For each STRIDE row whose Test cell names a §8 case, replace that cell
  with each disposition in the gate's recognised vocabulary, one at a
  time, against a temp copy. Report every substitution the gate accepts.

How to read the result. Exactly one class of escape is legitimate, and
it is the designed exemption stated in check-coupling.py's check 3: a
row rated Medium or Low may drop its §8 case for
`not required (<its own rating>)`, because at those bands a mitigation
is not required to carry a test. Every other escape is a hole in the
gate. The exit code encodes that: 0 when every escape is the designed
exemption, 1 otherwise.

This never writes docs/DESIGN.md. It reads it once and mutates copies in
a temp directory.

Usage: python3 docs/reviews/check-coupling-sweep.py [path/to/DESIGN.md]
[path/to/gate.py]

The optional second argument exists so this harness can be shown to
fail. Point it at a copy of check-coupling.py with checks 2b/2c removed
and it reports the 19 holes again; a sweep that has only ever printed "0
holes" is the same unfalsifiable green as the prose controls it
replaced.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

GATE = pathlib.Path(__file__).resolve().parent / "check-coupling.py"

# The gate's closed vocabulary, spelled out rather than imported, so
# that a mistake in the gate's own regexes cannot narrow what this sweep
# tries. If the gate's vocabulary grows, add it here too.
DISPOSITIONS = [
    "no credible threat",
    "residual",
    "accepted",
    "unmitigated",
    "not required (Critical)",
    "not required (High)",
    "not required (Medium)",
    "not required (Low)",
]


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def main(path: pathlib.Path, gate_path: pathlib.Path = GATE) -> int:
    src = path.read_text().splitlines(keepends=True)
    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="coupling-sweep-"))
    tmp = tmpdir / path.name

    def gate(lines: list[str]) -> int:
        tmp.write_text("".join(lines))
        return subprocess.run(
            [sys.executable, str(gate_path), str(tmp)], capture_output=True, text=True
        ).returncode

    if gate(src) != 0:
        print(
            "ABORT: the unmutated document is already red. Fix that before sweeping "
            "- every "
            "mutation below would be reported as caught, and none of them would have "
            "been."
        )
        return 1

    # each entry is (line index, id, rating, test cell)
    subjects: list[tuple[int, str, str, str]] = []
    for i, line in enumerate(src):
        if not line.startswith("| C"):
            continue
        c = cells(line)
        if len(c) == 7 and c[6].startswith("§8:"):
            subjects.append((i, c[0], c[4].strip("* "), c[6]))

    if not subjects:
        print(
            "ABORT: no row names a §8 case. Either the table shape changed or the "
            "coupling this "
            "sweep exists to attack is gone; either way a green here would mean "
            "nothing."
        )
        return 1

    runs = 0
    designed: list[tuple[str, str, str]] = []
    holes: list[tuple[str, str, str]] = []

    for idx, rid, rating, test in subjects:
        for disp in DISPOSITIONS:
            mutated = src[:]
            mutated[idx] = src[idx].replace(f"| {test} |", f"| {disp} |")
            if mutated[idx] == src[idx]:
                continue
            runs += 1
            if gate(mutated) != 0:
                continue
            # An escape. Is it the designed exemption, or a hole?
            if disp == f"not required ({rating})" and rating in ("Medium", "Low"):
                designed.append((rid, rating, disp))
            else:
                holes.append((rid, rating, disp))

    print(
        f"{path}: {len(subjects)} rows name a §8 case; {runs} substitutions run "
        f"against the gate."
    )
    print(f"  {len(designed)} escapes are the designed Medium/Low exemption:")
    for rid, rating, disp in designed:
        print(f"    - {rid} ({rating}) -> {disp!r}")

    if not holes:
        print(
            f"  0 escapes are holes. Every one of the {len(subjects)} rows that "
            f"names a §8 case "
            "loses its green when that reference is removed."
        )
        return 0

    print(
        f"  {len(holes)} escapes are HOLES - the row dropped its §8 case and the "
        f"gate stayed "
        "green:"
    )
    for rid, rating, disp in holes:
        print(f"    - {rid} ({rating}) -> {disp!r}")
    crit = [h for h in holes if h[1] in ("Critical", "High")]
    if crit:
        print(
            f"  {len(crit)} of them are Critical or High rows, where §11 permits no "
            f"exemption "
            "from having a test at all."
        )
    return 1


if __name__ == "__main__":
    # Default relative to THIS file, not the caller's cwd: the gate
    # lives two levels below the repo root and must give the same
    # verdict from wherever it is run. It previously defaulted to a
    # cwd-relative path, so running it from the directory it lives in
    # produced a FileNotFoundError traceback instead of a verdict.
    arg = (
        sys.argv[1]
        if len(sys.argv) > 1
        else str(pathlib.Path(__file__).resolve().parents[2] / "docs/DESIGN.md")
    )
    gate = pathlib.Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else GATE
    sys.exit(main(pathlib.Path(arg), gate))
