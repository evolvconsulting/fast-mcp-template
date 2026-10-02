"""Fail on any workflow `uses:` not pinned to a commit SHA (EC-639).

Local actions (`./...`) are exempt. Usage:
check-action-pins.py [workflow ...]
(default: every file in .github/workflows/).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def _uses(doc: object) -> list[object]:
    """Every job-level and step-level `uses`, in any YAML spelling."""
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    found: list[object] = []
    for job in (jobs or {}).values() if isinstance(jobs, dict) else []:
        if not isinstance(job, dict):
            continue
        found.append(job.get("uses"))
        found += [s.get("uses") for s in job.get("steps") or [] if isinstance(s, dict)]
    return [u for u in found if u is not None]


def unpinned(path: Path) -> list[str]:
    return [
        f"{path}: {u}"
        for u in map(str, _uses(yaml.safe_load(path.read_text())))
        if not u.startswith("./") and not PINNED.match(u)
    ]


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
