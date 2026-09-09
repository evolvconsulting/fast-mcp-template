#!/usr/bin/env python3
"""ADR-0010's coverage floors, enforced instead of documented.

    uv run --frozen pytest --cov --cov-report=json python3
    docs/reviews/check-coverage-floors.py [coverage.json]

**THE DEFECT THIS EXISTS FOR, quoted from the artefact that had it.**
`pyproject.toml` said:

    Only the overall floor is expressible as a single fail_under; the
    per-module floors are enforced by the units that create those
    modules.

That is an obligation with no enforcer. The aggregate floor is 80 and
the suite measures 95%+, so `pytest --cov` was green for weeks with TWO
critical paths under their own floor - `approval.py` at 78.57% branch
and `tools/candidates.py` at 80.77%, against 90. It is the same shape
this project has now refused five times: a setting nothing reads
(ADR-0025), a comment naming a variable that does not exist, the
`incomplete` flag (#86), the row floors (#79), and this.

**BOTH THE FLOORS AND THE MODULE LIST ARE DERIVED, NOT TYPED.**

- The floors come from `DESIGN.md`'s coverage sentence, parsed. A number
  retyped here would be a second copy of ADR-0010's decision, and this
  repository has watched a retyped constant rot in a brief, two
  obligation rows, a CI comment and three harness floors.
- The critical-path ROLES come from the same sentence's parenthesis.
- The role-to-MODULE mapping is NOT here. Each module declares its own
  `COVERAGE_ROLE`, and this file enumerates the package and asserts the
  declared set EQUALS the design's set, in both directions. **A checker
  carrying its own list of what it checks is the container defect this
  project has found eight times, one of them in a checker written for
  that very defect**, so the list is not carried: it is joined.

**WHAT AN EQUALITY FAILS ON, and both directions matter.** A role in the
design that no module claims is an unenforced floor - the state this
file was written to end. A role claimed by a module that the design does
not name is a floor invented locally. Either is a stop.

**WHAT IT DELIBERATELY DOES NOT CHECK.** Whether a covered branch is
TESTED. Coverage is walked-through, not asserted, and this project's
record is exactly that gap: R3-M2 and R7-L1 were assertions that could
not fail. `scripts/check-critical-coverage-amputation.sh` answers that
question by deleting behaviours and requiring something to go red. This
answers the narrower one completely and says which one it answered.

**`__main__.py` is not exempted and must not be.** Its arms run out of
process and the instrument does not see them; `pyproject.toml` records
at length why an `omit` row there would make the number look right by
measuring less. It has no `COVERAGE_ROLE`, so no floor here applies to
it, which is the honest position rather than a suppression.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DESIGN = ROOT / "docs/DESIGN.md"
PACKAGE = ROOT / "src/fast_mcp_template"

#: The design's coverage sentence, in four independent pieces so that a
#: reflow between them cannot silently drop one. Each is required; a
#: pattern that stops matching is a hard stop, never a skipped floor.
#:
#: `[^0-9]{0,40}` rather than `.*`: a greedy gap would let one role's
#: pattern match across the next clause and read the wrong number,
#: which is the shape of a wrong answer that explains itself. Measured
#: in the source project on its "90% the Jobvite client" against its
#: "95% on `utils/`".
DESIGN_FLOORS = {
    "overall": re.compile(r"(\d+)%\s*floor overall"),
    "tool modules": re.compile(r"(\d+)%[^0-9]{0,40}tool modules"),
    "utils/": re.compile(r"(\d+)%[^0-9]{0,20}`utils/`"),
    "critical line": re.compile(r"(\d+)%\s*line with"),
    "critical branch": re.compile(r"(\d+)%\s*branch on\s*\n?critical paths"),
}

#: The parenthesised role list. Read from the design so that adding a
#: sixth critical path to the design fails this checker until a module
#: claims it.
DESIGN_ROLES = re.compile(r"critical paths \(([^)]*)\)")

#: `COVERAGE_ROLE: Final = "..."` at module level, read by AST rather
#: than by regex: a string that appears in a docstring or a comment is
#: not a declaration, and a regex cannot tell the difference.
ROLE_NAME = "COVERAGE_ROLE"


#: Overrides, and they exist for ONE reason:
#: `tests/test_coverage_floors.py` has to be able to drive this checker
#: into each of its failure arms against a synthetic design and a
#: synthetic package. A control that cannot vary the input is a control
#: that never fires - and a gate nobody has watched fail is not known to
#: work. CI passes neither flag, so the real run reads the real paths
#: and nothing else.
def parse_argv(argv: list[str]) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """`[report] [--design PATH] [--package PATH]`; repo defaults."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", nargs="?", default="coverage.json")
    parser.add_argument("--design", default=None)
    parser.add_argument("--package", default=None)
    args = parser.parse_args(argv)
    return (
        pathlib.Path(args.report),
        pathlib.Path(args.design) if args.design else DESIGN,
        pathlib.Path(args.package) if args.package else PACKAGE,
    )


def parse_design(text: str) -> tuple[dict[str, int], set[str]]:
    """Floors and critical-path roles, from the design sentence."""
    floors: dict[str, int] = {}
    missing: list[str] = []
    for name, pattern in DESIGN_FLOORS.items():
        match = pattern.search(text)
        if match is None:
            missing.append(name)
        else:
            floors[name] = int(match.group(1))
    if missing:
        raise SystemExit(
            "THE DESIGN'S COVERAGE SENTENCE DID NOT PARSE for: "
            + ", ".join(missing)
            + "\nThe sentence moved or was reworded. FIX THE PATTERN - do not\n"
            "type the number in here, which is how the floor acquires a\n"
            "second copy that then rots."
        )

    roles_match = DESIGN_ROLES.search(text)
    if roles_match is None:
        raise SystemExit(
            "THE CRITICAL-PATH ROLE LIST DID NOT PARSE. Without it this\n"
            "checker would silently enforce nothing, which is the state it\n"
            "exists to end."
        )
    roles = {part.strip() for part in roles_match.group(1).split(",") if part.strip()}
    return floors, roles


def declared_roles(package: pathlib.Path) -> tuple[dict[str, str], list[str]]:
    """Every `COVERAGE_ROLE` in the package, keyed by module path.

    THE CONTAINER IS THE PACKAGE, walked with `rglob`. A list of files
    written here would be blind to the module nobody added to it, which
    is the whole reason the declaration lives in the modules.
    """
    roles: dict[str, str] = {}
    duplicates: list[str] = []
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            target: ast.expr | None = None
            value: ast.expr | None = None
            if isinstance(node, ast.AnnAssign):
                target, value = node.target, node.value
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value = node.targets[0], node.value
            if not isinstance(target, ast.Name) or target.id != ROLE_NAME:
                continue
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                continue
            rel = str(path.resolve().relative_to(package.resolve().parent.parent))
            if value.value in roles.values():
                duplicates.append(f"{value.value} ({rel})")
            roles[rel] = value.value
    return roles, duplicates


def measure(data: dict[str, object], key: str) -> tuple[float, float]:
    """Line and branch percentages for one file in `coverage json`.

    A module with no branches at all is 100% branch by definition, not
    a division by zero and not a skip.
    """
    files = data["files"]
    assert isinstance(files, dict)
    summary = files[key]["summary"]
    line = 100.0 * summary["covered_lines"] / summary["num_statements"]
    branch = (
        100.0 * summary["covered_branches"] / summary["num_branches"]
        if summary["num_branches"]
        else 100.0
    )
    return line, branch


def main(argv: list[str] | None = None) -> int:
    report, design, package = parse_argv(sys.argv[1:] if argv is None else argv)
    if not report.is_file():
        print(f"{report} does not exist. Run:")
        print("  uv run --frozen pytest --cov --cov-report=json")
        print("A search at a path that does not exist returns a clean empty,")
        print("indistinguishable from a real pass - so this is exit 2.")
        return 2
    if not design.is_file():
        print(f"{design} does not exist. Every floor below would be invented.")
        return 2
    if not package.is_dir():
        print(f"{package} is not a directory. The container is missing, so the")
        print("role join would compare the design against an empty set and")
        print("report every floor unclaimed for the wrong reason.")
        return 2

    data = json.loads(report.read_text(encoding="utf-8"))
    files = data["files"]
    if not files:
        print("THE COVERAGE REPORT MEASURED ZERO FILES. A report with nothing")
        print("in it satisfies every floor vacuously; that is exit 2.")
        return 2

    floors, design_role_set = parse_design(design.read_text(encoding="utf-8"))
    roles, duplicates = declared_roles(package)
    declared_role_set = set(roles.values())

    print("FLOORS, derived from DESIGN.md's coverage sentence:")
    for name, value in floors.items():
        print(f"  {name:<20} {value}%")
    print()

    failures: list[str] = []

    # ---------------------------------------------------------------
    # THE JOIN. Both directions, because they are different defects.
    # ---------------------------------------------------------------
    # THE SOURCE PROJECT ADDED ONE ROLE HERE that its design named and
    # this template's does not, so the expected set is exactly what the
    # design declares. An adopter whose design names a role the
    # DESIGN_FLOORS patterns cannot see adds it in both places.
    expected = design_role_set
    unclaimed = expected - declared_role_set
    invented = declared_role_set - expected
    if duplicates:
        failures.append(
            "TWO MODULES CLAIM THE SAME ROLE: "
            + ", ".join(duplicates)
            + " - one of them is not the path the design means, and a floor"
            " applied to the wrong module reads as discharged."
        )
    if unclaimed:
        failures.append(
            "THE DESIGN NAMES A ROLE NO MODULE CLAIMS: "
            + ", ".join(sorted(unclaimed))
            + " - that floor is enforced by nothing, which is the exact state"
            " this checker exists to end. Add COVERAGE_ROLE to the module."
        )
    if invented:
        failures.append(
            "A MODULE CLAIMS A ROLE THE DESIGN DOES NOT NAME: "
            + ", ".join(sorted(invented))
            + " - a floor invented locally is not ADR-0010's floor."
        )

    # ---------------------------------------------------------------
    # THE FLOORS. `max` over every applicable family rather than a
    # precedence rule: `tools/candidates.py` is both a tool module and a
    # critical path, and the strictest floor is the one that holds.
    # ---------------------------------------------------------------
    print(f"{'MODULE':<48}{'ROLE':<22}{'LINE':>8}{'FLOOR':>7}{'BRANCH':>9}{'FLOOR':>7}")
    for key in sorted(files):
        rel = key if key.startswith("src/") else f"src/{key}"
        role = roles.get(rel)
        line_floor = 0
        branch_floor = 0
        family = "-"
        if "/tools/" in rel:
            line_floor, family = floors["tool modules"], "tool module"
        if "/utils/" in rel:
            line_floor, family = max(line_floor, floors["utils/"]), "utils/"
        if role is not None:
            line_floor = max(line_floor, floors["critical line"])
            branch_floor = floors["critical branch"]
            family = role
        if line_floor == 0:
            continue

        line, branch = measure(data, key)
        print(
            f"{rel:<48}{family:<22}{line:7.2f}%{line_floor:6}%"
            f"{branch:8.2f}%{(str(branch_floor) + '%') if branch_floor else '-':>7}"
        )
        if line < line_floor:
            failures.append(f"{rel}: {line:.2f}% line, below {line_floor}%")
        if branch_floor and branch < branch_floor:
            failures.append(f"{rel}: {branch:.2f}% branch, below {branch_floor}%")

    totals = data["totals"]
    overall = 100.0 * totals["covered_lines"] / totals["num_statements"]
    print(f"\nOverall: {overall:.2f}% line against a {floors['overall']}% floor")
    if overall < floors["overall"]:
        failures.append(f"overall: {overall:.2f}% line, below {floors['overall']}%")

    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"  {failure}")
        print(
            "\nThe aggregate `fail_under` cannot see any of these: it is 80 and\n"
            "the suite measures 95%+, so a critical path can sit ten points\n"
            "under its own floor with every gate green. That is what happened."
        )
        return 1

    print("\nEvery declared role matches the design, and every floor holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
