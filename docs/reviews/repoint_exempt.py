#!/usr/bin/env python3
"""The register that grants citation exemptions.

It is the only thing that does.

#142. Before this, `REPOINT-EXEMPT` anywhere on a line made both wired
citation gates skip the WHOLE line, with no scope and no
reason. Measured consequences, on the tree at `ee20c94`:

  - 51 lines were exempt in `check-design-citations.py`'s container and
    25 in `check-design-citation-shape.py`'s - two numbers, because the
    gates do not share a container.
  - **36 of the 51 carried no citation at all.** The marker is a bare
    substring, so every line that merely NAMED it exempted itself: the
    constant's own definition, the docstrings describing the mechanism,
    the reports about the defect. The three largest holders were the
    checker, its probe, and the report about the probe.
  - A line reading `<the design>:99999-99999 REPOINT-EXEMPT` passed both
    gates at exit 0 - a citation 97,866 lines past the end of a
    2133-line file.

THE MARKER IS NOW NECESSARY AND NOT SUFFICIENT. A citation is exempt if
its line carries the marker AND the `(path, address)` pair is registered
here with a non-blank reason. Two consequences worth stating:

  - The 36 mention-only lines needed NO EDIT. They carry the marker and
    cite nothing, so they grant nothing and are scanned normally. There
    is no migration and no grandfather clause.
  - **The recursion is structurally impossible, not merely controlled.**
    Writing this mechanism's own documentation cannot exempt anything,
    because documentation is not the register - and the register is
    `.txt`, which is in neither gate's suffix set, so it is never
    scanned. A register written in Python would be scanned by the gate
    it governs and would have to exempt itself, which is the defect.

The key carries no line number, per #6. A `path:line` key rots on the
first edit above the line and silently re-exempts whatever moves in.

    python3 docs/reviews/repoint_exempt.py   # print it, self-check
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTER = ROOT / "docs" / "reviews" / "REPOINT-EXEMPT.txt"

#: Necessary, not sufficient. It selects the LINE; the register decides
#: whether the citation on it is exempt. Split so this file is
#: not itself carrying the marker it describes.
MARKER = "REPOINT" + "-EXEMPT"


class RegisterError(Exception):
    """Malformed. A broken register is not an empty one."""


def _rows() -> list[tuple[str, str, str]]:
    if not REGISTER.exists():
        raise RegisterError(f"{REGISTER} is missing. That is a BROKEN INSTRUMENT.")
    rows: list[tuple[str, str, str]] = []
    for num, raw in enumerate(REGISTER.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) != 3:
            raise RegisterError(
                f"{REGISTER.name}:{num}: expected 3 tab-separated fields, got "
                f"{len(parts)}"
            )
        path, address, reason = (p.strip() for p in parts)
        # A BLANK REASON IS NOT AN EXEMPTION - the same assertion
        # check-no-errexit.py makes, for the same reason: the reason IS
        # the exemption, and a register nobody has to argue in front of
        # is a list.
        if not reason:
            raise RegisterError(f"{REGISTER.name}:{num}: blank reason for {path}")
        start, _, end = address.partition("-")
        if not (start.isdigit() and end.isdigit()):
            raise RegisterError(
                f"{REGISTER.name}:{num}: address {address!r} is not <start>-<end>"
            )
        rows.append((path, address, reason))
    if not rows:
        raise RegisterError(
            f"{REGISTER.name} parsed ZERO rows. A register that grants nothing "
            "looks identical to one that is not being read."
        )
    return rows


_TABLE: dict[tuple[str, str], str] | None = None


def table() -> dict[tuple[str, str], str]:
    """`(relative path, "<start>-<end>") -> reason`, parsed once."""
    global _TABLE
    if _TABLE is None:
        _TABLE = {(p, a): r for p, a, r in _rows()}
    return _TABLE


def reason(rel_path: str, start: int, end: int) -> str | None:
    """Why this citation is exempt, or None if it is not registered."""
    return table().get((rel_path, f"{start}-{end}"))


def is_exempt(line: str, rel_path: str, start: int, end: int) -> bool:
    """Both halves: the marker selects, the register grants."""
    return MARKER in line and reason(rel_path, start, end) is not None


def report() -> str:
    """The register, printed every run. An unseen set is #142."""
    rows = sorted(table().items())
    out = [f"{len(rows)} registered citation exemption(s):"]
    out += [f"  EXEMPT   {p}  {a}  - {r}" for (p, a), r in rows]
    return "\n".join(out)


def stale() -> list[str]:
    """Rows that grant nothing: path gone, or no marked line.

    A hand-kept list beside its container rots where no step looks.
    `check-checkers-are-wired.py` reports its stale and unknown entries
    for the same reason; this is that check for this register.
    """
    import re

    cite = re.compile(r"DESIGN\.md:(\d+)(?:-(\d+))?")
    bad: list[str] = []
    for (rel, address), _ in sorted(table().items()):
        path = ROOT / rel
        if not path.exists():
            bad.append(f"  STALE    {rel}  {address}  - the path no longer exists")
            continue
        used = False
        for line in path.read_text(errors="replace").splitlines():
            if MARKER not in line:
                continue
            for m in cite.finditer(line):
                s = int(m.group(1))
                e = int(m.group(2)) if m.group(2) else s
                if f"{s}-{e}" == address:
                    used = True
        if not used:
            bad.append(
                f"  STALE    {rel}  {address}  - no marked line in that file "
                "carries this citation"
            )
    return bad


def _self_check() -> int:
    """The smallest thing that fails if the two-of-two rule breaks."""
    rows = _rows()
    probe_path, probe_addr, _ = rows[0]
    start, _, end = probe_addr.partition("-")
    marked = f"a citation and the {MARKER} marker"
    assert is_exempt(marked, probe_path, int(start), int(end)), "registered+marked"
    assert not is_exempt("no marker here", probe_path, int(start), int(end)), (
        "the register alone must NOT exempt an unmarked line"
    )
    assert not is_exempt(marked, probe_path, 99999, 99998), (
        "the marker alone must NOT exempt an unregistered address"
    )
    assert not is_exempt(marked, "no/such/file.py", int(start), int(end)), (
        "the marker alone must NOT exempt an unregistered path"
    )
    print("  4/4 self-checks passed (marked+registered, marker-only, register-only x2)")
    return 0


def main() -> int:
    try:
        print(report())
    except RegisterError as exc:
        print(f"BROKEN REGISTER: {exc}")
        return 2
    rows = stale()
    if rows:
        print(f"\n{len(rows)} stale row(s):")
        print("\n".join(rows))
    else:
        print("\nNo stale rows: every row is used by a marked line.")
    rc = _self_check()
    return 1 if rows else rc


if __name__ == "__main__":
    sys.exit(main())
