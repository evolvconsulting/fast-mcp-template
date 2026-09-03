#!/usr/bin/env python3
"""Every `§n.m` pointer resolves to a heading that exists.

**Why this exists.** `DESIGN.md` cited `§5.4` from §5.3's "the v1
`jobFeed` URL is itself a secret" sentence. Section 5 runs 5.1, 5.2, 5.3
and then section 6 begins, so the pointer resolved to nothing.
It was found by an implementer who happened to follow it while building
U3 - seven review rounds, three gate scripts and a frozen-object freeze
had all passed over it, because **no gate reads cross-references.**
`check-coupling.py` checks section 8 cases against threat rows, which is
a different property entirely.

ADR-0019 records the fix and says plainly that the population was
unmeasured. This script is what measures it, and it is deliberately
written to run over ANY document in the corpus rather than only the one
that had the known defect - a checker aimed at the single instance
somebody already found would be theatre.

WHAT IT CHECKS

  1. Every `§n` and `§n.m` reference points at a heading that exists in
     the same file.
  2. Headings are collected from markdown `#`-prefixed lines whose text
     starts with a number, so `## 5. Errors...` and
     `### 5.1 The error contract` both register.
  3. Each file is judged against ITSELF PLUS ITS DECLARED REFERENT.
     `COMPLIANCE-SPEC.md` legitimately says "§5.4" and has its own 5.4;
     `DESIGN.md` says "§5.4" and does not. Judging the corpus as one
     flat namespace would call the first a defect and mask the second.

     **The referent is not optional, and the first version of this
     script omitted it.** Judging every file against itself alone
     reported 30 unresolved references, of which 27 were mine:
     `IMPLEMENTATION-PLAN.md` cites the DESIGN's sections constantly
     ("the §7.4 shutdown requirement", "§11's threat rows"), and those
     all resolve - in `DESIGN.md`, which is what the plan is a plan FOR.
     A checker whose own model is wrong produces findings shaped exactly
     like real ones, and 27 of 30 is the ratio that would have gone into
     a report.

SELECTOR CONTROLS, because a checker that silently matches nothing is
the failure mode this repository keeps paying for:

  - A file yielding ZERO headings is a failure, not a pass.
  - Finding zero references across ALL files is a failure - the
    reference pattern is presumed to appear somewhere in a corpus that
    uses section numbering throughout.
  - `--controls` mutates a real file in memory and asserts the checker
    goes red, so a green means the instrument fires rather than that it
    looked.

Usage:
    python3 docs/reviews/check-cross-references.py [path ...] # default:
    the doc corpus python3 docs/reviews/check-cross-references.py
    --controls

Exit 0 on success, 1 on any unresolved reference. No dependencies.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# `## 5. Errors...`, `### 5.1 The error contract`, `#### 5.1.2 ...`
_HEADING = re.compile(r"^#{1,6}\s+(\d+(?:\.\d+)*)\.?\s")
# `§5.4`, `§8`, `§5.1/§5.4`. The section sign is the anchor; bare "5.4"
# is far too noisy.
_REFERENCE = re.compile(r"§\s*(\d+(?:\.\d+)*)")
# A markdown filename on the same line means the reference belongs to
# THAT document.
# A line that NAMES the document it cites is not citing THIS document's
# numbering, so its `§n` is not ours to resolve. That was spelled as
# "mentions a `.md` file", which silently excluded EXTERNAL
# specifications: `RFC 9457 §4.2.1` read as a broken internal reference
# (#139, three sites across ADR-0017 and ADR-0030, all correct as
# written). The rule was always about NAMING, never about the `.md`
# suffix - an RFC number identifies its document at least as precisely
# as a filename does.
_NAMES_A_DOCUMENT = re.compile(r"[A-Za-z0-9_-]+\.md|\bRFC\s*\d+")

# References that resolve in a document this checker does not read, on
# lines that do not name it. Each needs a REASON, not just a coordinate.
#
# KEYED ON CONTENT, NOT ON A LINE NUMBER, and that is a correction
# rather than a preference. The first version keyed them on (line,
# reference); merging draft 9 moved one from 1091 to 1150 and the
# exemption silently stopped applying, turning a known-external
# reference back into a "defect". A coordinate-keyed exemption rots
# exactly like the citation it exempts - which is the failure this whole
# script exists to catch, reproduced inside its own suppression list.
_EXEMPT: dict[str, list[tuple[str, str]]] = {
    # No entry for IMPLEMENTATION-PLAN.md. It had one, for a §16.3 that
    # named "the spike" and not the file. impl-plan-draft9 FIXED THE
    # CITATION INSTEAD - the line now reads `FASTMCP-SPIKE-4.md:1431`
    # with the section title quoted - which is strictly better than
    # exempting it: a reader following the pointer now arrives
    # somewhere. An exemption should be the last resort, not the first,
    # and this one lasted two commits.
    "docs/DESIGN.md": [
        # FASTMCP-SPIKE-4.md's §20.2, the executed spike the dual-era
        # guard rests on. Verified by reading the surrounding paragraph,
        # which is entirely about that spike; the filename is not on the
        # citing line.
        ("20.2", "MRTR raising on handshake"),
    ],
}

# document -> the document whose section numbering it ALSO cites, or
# None. The plan is a plan for the design and cites its sections
# throughout.
# **THE REFERENT IS A CLAIM ABOUT WHOSE NUMBERING A DOCUMENT'S BARE `§n`
# REFERENCES USE - NOT ABOUT WHAT THE DOCUMENT IS.** #139 surfaced the
# doubt in a useful form: `STANDARDS.md` is a survey of an EXTERNAL
# corpus, so naming the design as its referent felt like a statement
# that the document is about our design. It is not. Its bare `§n` refs
# cite the design's sections, measurably - all four resolve there and
# every target was read and is on subject. Whose numbering, not whose
# subject.
#
# `data-inventory.md` (15) and `STANDARDS.md` (4) were the whole
# WRONG REFERENT class: 19 of the 46 unresolved references, and BOTH GO
# TO ZERO with this referent. Measured, not assumed.
DEFAULT_TARGETS: dict[str, str | None] = {
    "docs/DESIGN.md": None,
    "docs/plans/IMPLEMENTATION-PLAN.md": "docs/DESIGN.md",
    "docs/research/COMPLIANCE-SPEC.md": None,
    "docs/data-inventory.md": "docs/DESIGN.md",
    "docs/research/STANDARDS.md": "docs/DESIGN.md",
}


def headings(text: str) -> set[str]:
    """Every numbered heading in one document, as dotted strings."""
    return {m.group(1) for line in text.splitlines() if (m := _HEADING.match(line))}


def unresolved(
    text: str, referent: str | None = None, name: str = ""
) -> list[tuple[int, str]]:
    """Every `§n.m` in neither this document nor its referent."""
    known = headings(text)
    if referent:
        known |= headings((REPO_ROOT / referent).read_text())
    # THE GUARD RUNS AFTER THE REFERENT IS MERGED IN, and it used to run
    # before (#139). Its purpose is to refuse a check against an EMPTY
    # heading set, where every reference would be reported broken and
    # the finding would be an artefact of the instrument. But run before
    # the merge it also refused every document that has NO numbered
    # headings OF ITS OWN and cites another document's - which is
    # precisely what an ADR is. MEASURED: 22 of the 30 non-record
    # documents carrying section references were rejected this way,
    # including 21 ADRs, so the load-bearing half of the population was
    # structurally uncheckable while the checker reported success on the
    # three documents it did admit.
    if not known:
        raise ValueError("no numbered headings found at all")
    missing: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        # A line that NAMES another document is citing that document's
        # numbering. `Review and `JOBVITE-API.md` §0.2 cover that` is
        # correct and unresolvable here. Refining the checker to see
        # this took the second pass; the first reported eight such
        # references as defects.
        if _NAMES_A_DOCUMENT.search(line):
            continue
        for ref in _REFERENCE.findall(line):
            if ref in known:
                continue
            if any(r == ref and marker in line for r, marker in _EXEMPT.get(name, [])):
                continue
            missing.append((lineno, ref))
    return missing


def check(targets: dict[str, str | None]) -> int:
    total_refs = 0
    failures: list[str] = []
    for name, referent in targets.items():
        path = REPO_ROOT / name
        if not path.exists():
            failures.append(
                f"{path}: does not exist - a check at a missing path is a "
                f"clean empty, never a pass"
            )
            continue
        text = path.read_text()
        try:
            missing = unresolved(text, referent, name)
        except ValueError as exc:
            failures.append(f"{path}: {exc}")
            continue
        refs = len(_REFERENCE.findall(text))
        total_refs += refs
        rel = path.relative_to(REPO_ROOT)
        via = f" (+{referent})" if referent else ""
        print(
            f"  {rel}{via}: {len(headings(text))} numbered headings, {refs} "
            f"references, {len(missing)} unresolved"
        )
        for lineno, ref in missing:
            failures.append(f"{rel}:{lineno}: §{ref} does not exist in this document")

    if total_refs == 0:
        failures.append(
            "SELECTOR CONTROL: zero references found across every file. "
            "The "
            "pattern is broken, not the corpus."
        )

    if failures:
        print(f"\n{len(failures)} problem(s):")
        for f in failures:
            print(f"  FAIL: {f}")
        return 1
    print("\nEvery section reference resolves within its own document. OK.")
    return 0


def controls() -> int:
    """Prove each check can go red, on real content not a toy."""
    design = REPO_ROOT / "docs" / "DESIGN.md"
    text = design.read_text()
    design_name = "docs/DESIGN.md"
    fired = 0
    total = 0

    # THE NAME IS LOAD-BEARING AND THESE CONTROLS OMITTED IT (#139).
    # `unresolved()` consults `_EXEMPT[name]`, so a call without `name`
    # asks a DIFFERENT QUESTION than the gate asks: DESIGN.md's §20.2
    # exemption stops applying and the document reads as having one
    # unresolved reference. The third control below therefore reported
    # "the real file is red" against a file the gate calls clean, and it
    # had been doing so unnoticed because CI runs this checker WITHOUT
    # `--controls`. A control that does not reproduce the gate's own
    # call is measuring its own construction.
    total += 1
    if unresolved(text.replace("§8", "§99", 1), None, design_name):
        fired += 1
        print("  CONTROL a dangling reference is caught -> FIRED")
    else:
        print("  CONTROL a dangling reference is caught -> DID NOT FIRE")

    total += 1
    try:
        unresolved("no headings here, just prose mentioning §4")
        print("  CONTROL a file with no headings is a failure -> DID NOT FIRE")
    except ValueError:
        fired += 1
        print("  CONTROL a file with no headings is a failure -> FIRED")

    total += 1
    if not unresolved(text, None, design_name):
        fired += 1
        print("  CONTROL the unmutated document is clean -> FIRED")
    else:
        print(
            "  CONTROL the unmutated document is clean -> DID NOT FIRE "
            "(the real file is red; fix that first)"
        )

    print(f"\n{fired}/{total} controls fired.")
    return 0 if fired == total else 1


def main(argv: list[str]) -> int:
    if "--controls" in argv:
        return controls()
    named: dict[str, str | None] = {a: None for a in argv[1:]}
    targets = named or DEFAULT_TARGETS
    return check(targets)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
