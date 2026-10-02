"""Fail on any workflow `uses:` not pinned to a commit SHA (EC-639).

Local actions (`./...`) are exempt. Usage:
check-action-pins.py [workflow ...]
(default: every file in .github/workflows/).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)")
PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def unpinned(path: Path) -> list[str]:
    bad = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        m = USES.match(line)
        if m and not m.group(1).startswith("./") and not PINNED.match(m.group(1)):
            bad.append(f"{path}:{n}: {m.group(1)}")
    return bad


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv] or sorted(Path(".github/workflows").glob("*.y*ml"))
    if not files:
        print("::error::no workflow files found; the gate checked nothing")
        return 3
    bad = [b for f in files for b in unpinned(f)]
    for b in bad:
        print(f"::error::not SHA-pinned: {b}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
