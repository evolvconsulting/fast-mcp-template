#!/usr/bin/env python3
"""Every checker and probe we ship runs in CI, or says why it does not.

    python3 docs/reviews/check-checkers-are-wired.py
    python3 docs/reviews/check-checkers-are-wired.py --self-test

**WHY THIS EXISTS.** Three checkers here were written, measured,
committed - and never wired into CI. Nothing said so. They sat green and
inert while being cited as gates, which is strictly worse than not
having them: an unwired checker is a claim of coverage that costs
nothing to make and nobody can see is false.

**IT IS THE SAME MISTAKE TWICE, WITH THE SAME INSTRUMENT.** The obvious
census is `grep <basename> .github/workflows/ci.yml`. That counts a name
in a COMMENT as wired. Review R12 used it and mislabelled three files; I
used it earlier the same day and reported
`check-design-citation-shape.py` as WIRED, then spent hours calling an
unwired scan a gate. My replacement parser was ALSO wrong: it matched
only block-form `run: |` and missed every single-line `run:`, reporting
`check-coupling.py` as unwired twenty minutes after I had read its step.
The contradiction between two wrong instruments is the only reason
either was caught.

So this file does not grep the workflow. It **parses the YAML** and
reads `jobs.*.steps[].run` - the only place a step can actually execute
- and strips shell comments from those bodies before looking for a name.

**THE EXEMPTION IS A DECISION, NOT A HOLE.** A checker may be unwired on
purpose: `check-review-coverage.py` reports a real backlog and exits 1
until that backlog clears. Being unwired is fine. Being unwired *and
unrecorded* is the defect. So an exemption needs a non-empty reason, and
a blank one is refused.

**IT ALSO CHECKS THE REVERSE, which nothing else here does.** An
exemption naming a checker that IS wired is stale - the reason has
outlived the condition, and a stale exemption is how a list stops
describing the thing it lists. That is a failure too, not a nit.

## Scope: the CONTAINER, not a prefix inside it (#153, #155, #149)

The container is **every tracked `.py` or `.sh` under `docs/reviews/`
and `scripts/`**, enumerated from git. Membership is decided by KIND -
a runnable script file, by suffix - and never by what its name starts
with. That is #115's doctrine, and until 2026-09-01 this file was the
loudest violation of it.

**IT USED TO BE TWO GLOBS WEARING A CONTAINER'S NAME**:
`docs/reviews/check-*.py` and `docs/reviews/check-*.sh`. Measured at
`2d886a4`, that selected 28 of the 123 files here, and it printed
*"Every checker is wired"* about the other 95.

It was blind in three directions at once, and they are three separate
mistakes that happened to share a line:

- **BY PATH (#153).** `scripts/` was excluded, with a stated reason:
  those are per-unit mutation HARNESSES reaching CI through
  `scripts/ci-harness-gate.sh`, a second container with its own gate.
  The reason was true and the exclusion still did harm, because
  `scripts/` had stopped holding only harnesses. Two real gates live
  there now, and one of them - `check-timeout-literals.py` - was
  committed UNWIRED by the very task that built it, at exit 0.
- **BY PREFIX (#155).** `probe-*` was never in the population, so
  nobody was ever ASKED for a reason. 33 of the 34 probes here are
  unwired. `measure-*` and `sample-*` were a third and fourth prefix
  nobody had noticed at all.
- **BY ITS OWN ESCAPE HATCH (#149).** `probe-midsentence-shape.py`
  says in its docstring that it is named `probe-` *"so it cannot
  become a gate by accident"* - it was using the prefix filter AS a
  mechanism. The widening removes that hatch on purpose: a file opts
  out by RECORDING A REASON, which someone can read and argue with,
  never by choosing a name this checker cannot see.

**THE PATH SCOPE IS STILL A PATH, AND THAT IS NOT THE DEFECT.** A
container has to be bounded somewhere. The defect was filtering by NAME
inside the bound, because a name is a thing an author picks and a
container is not.

**MOST MEMBERS ARE NOT GATES AND MUST NOT BECOME ONE.** A control that
breaks its subject, a one-shot whose question is settled, a reporting
instrument that must never refuse - each is a legitimate reason to be
unwired, and each is now WRITTEN DOWN in `UNWIRED_BY_DECISION` instead
of being implied by a filename. `scripts/*` harnesses reached through
`ci-harness-gate.sh` read as WIRED here for free, because that gate
names each one in a `run:` body.

**WHAT IT CANNOT DO.** It proves a checker is INVOKED, not that its exit
code gates the job. A step that runs a checker and swallows its status
reads as WIRED here, and "wired" must not be read as "gating".

**THAT POPULATION HAS BEEN MEASURED AND IT IS ZERO.** GitHub runs every
`run:` as `bash -e {0}`, so a failure anywhere fails the step unless the
block turns errexit off - which makes the container small and enumerable
rather than the whole file. **EVERY step the selector below picks tests
a status.** The property is stated; the digits are not, and the command
at the bottom of this docstring returns them.

**THE SELECTOR IS A SUPERSET, AND SAYING OTHERWISE WAS WRONG (R20-L2).**
It matches `set +e` OR `set -uo pipefail`, and this file described both
as "disables or bypasses errexit". Only the first does. MEASURED, under
the shell GitHub actually uses:

    $ cat e1.sh                    $ cat e2.sh
    set -uo pipefail               set +e
    false                          false
    echo REACHED                   echo REACHED

    $ bash -e e1.sh   -> exit 1, nothing printed   errexit STILL ON
    $ bash -e e2.sh   -> exit 0, REACHED           errexit OFF

`set -uo pipefail` sets nounset and pipefail and touches errexit not at
all; under `bash -e` the shell still dies at the first failure. So those
steps were never members of the population this paragraph is about.

**THE ZERO SURVIVES BECAUSE A SUPERSET CAN ONLY ADD FALSE MEMBERS**, and
every one of them tested a status anyway. What was wrong is the sentence
telling the next reader what the container IS - and a reader who trusts
it would conclude that `set -uo pipefail` is a way to turn errexit off,
which is the opposite of true and the kind of belief that ships a step
whose failure is silent.

**NO COUNT IS WRITTEN HERE, AND THAT IS THE THIRD REMEDY THIS SENTENCE
HAS HAD.** It said "of 94 steps", which was the NAMED-step count and a
join over the wrong population - 17 of those are `uses:` steps that
execute no shell and can never be members. Corrected to 86 `run:` steps;
the same commit added a step and made it 87. Then it was written in the
PAST TENSE with a date, on the theory that a dated figure cannot go
stale. **It went stale anyway and the date could not tell anyone**:
every commit in that range carries 2026-09-02, and across it the
denominator reads 86, 86, 87, 89, 89, 90. A dated past-tense figure only
resolves an ambiguity COARSER than the rate the figure moves, and this
one moves faster than its own timestamp.

So the count is DELETED, which is what ADR-0034 ruled for exactly this
shape and what I failed to apply to my own file twice. **A ratio is a
join, and a join over two populations is wrong even when both of its
numbers are right** - that lesson is the reason the sentence was
rewritten the first time, and it survives without either digit.

    uv run --frozen python - <<'EOF'
    import yaml, pathlib
    y = pathlib.Path(".github/workflows/ci.yml")
    d = yaml.safe_load(y.read_text())
    n = off = 0
    for job in d["jobs"].values():
        for st in job.get("steps", []):
            if "run" not in st:
                continue
            n += 1
            if "set +e" in st["run"] or "set -uo pipefail" in st["run"]:
                off += 1
    print(n, off)
    EOF

So the gap is real as a statement and empty as a population, and NO GATE
WAS BUILT FOR IT: a step whose green is
guaranteed by having no members is a step whose green means nothing.

**THE ZERO IS ATTRIBUTABLE, not assumed.** A planted swallowing step -
`out=$(checker); rc=$?` with `rc` never tested - is returned by the same
selector, so the empty result is a fact about the file rather than about
the search. RE-DERIVE IT rather than trusting this paragraph: find steps
matching `set +e` or `set -uo pipefail` whose body contains no
`|| exit`, `|| {`, `-ne 0` or `exit $rc`.

**AND MY FIRST SELECTOR REPORTED THREE FINDINGS, ALL FALSE.** It looked
for `|| exit` and could not see `|| { echo ...; exit 1; }`, which is the
form this file actually uses. A crude selector in the ALARMING direction
costs a reader the whole diagnosis, and it was the third such instance
in one night.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import shlex
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

#: A checker a HUMAN HAS READ A STEP FOR in `ci.yml`. Controls 1 and 2b
#: below assert it reads WIRED.
#:
#: **IT IS HARDCODED ON PURPOSE, and deriving it would be the defect.**
#: Control 1 exists to catch the parser returning nothing and every
#: answer reading "unwired"; a subject derived FROM `wired_names()`
#: would move with the bug and the row would pass either way. That is
#: the shape this file records one function down: a control whose
#: subject is selected through the construct it is testing kills
#: nothing.
#:
#: The cost of hardcoding is that **this line has to change whenever
#: the step that wires this checker is renamed or removed** - and the
#: control fails loudly when it does, which is the correct trade.
_WIRED_SUBJECT = "check-design-freeze.py"

#: Checkers that are deliberately not wired, each with the reason. **A
#: bare name is refused: the reason IS the exemption.**
#:
#: **EVERY ENTRY BELOW IS THE TEMPLATE'S OWN**, written when the checker
#: was carried here. None was inherited: an exemption reason describes a
#: condition in THIS repository, and a reason copied from another one is
#: a sentence nobody can act on.
#:
#: Each reason states **when to turn the gate on**. That is the whole
#: design of this template: a short list is wired and the rest are
#: present and off, because a project that starts with three dozen
#: gates it has not earned spends its first month servicing them.
#:
#: A DIGIT USED TO SIT IN THAT SENTENCE, saying five, and it was
#: already false when it was read: `main()` printed a larger figure on
#: the same tree. It is deleted rather than corrected, for the reason
#: the docstring above gives - a denominator that moves with every
#: commit goes stale faster than any date could qualify it - and
#: `main()` prints the live one on every run.
#:
#: Wire one when the artefact it checks exists - AND only after
#: measuring it green, since a gate that lands red is one people learn
#: to ignore.
#:
#: DELETING an entry is how a gate gets turned on: wire the step, delete
#: the row, in one commit. Leaving the row behind fails the build on the
#: stale-exemption check below, which is the point of checking the
#: reverse direction.
UNWIRED_BY_DECISION: dict[str, str] = {
    "refreeze.sh": (
        "NOT A CHECKER: the one-line procedure that writes the commit "
        "carrying docs/DESIGN.md into docs/DESIGN-FREEZE.txt. It is a "
        "TOOL a human runs on adoption and after every design change, "
        "so it can only ever read UNWIRED - the container is bounded by "
        "directory and suffix on purpose, and carving out an exception "
        "for 'tools' is how a population starts filtering by a property "
        "somebody picks. Wiring it would make CI REWRITE the freeze "
        "pointer, which is the one thing the freeze gate exists to stop."
    ),
    "check-quickstart.py": (
        "SHIPPED DISABLED, and the reason is a measurement rather than "
        "a preference. Its MUST_PRINT is hardcoded to `Tools:` - the "
        "output of `fastmcp inspect` - and `fastmcp inspect` takes a "
        "FILE, so it cannot load a package whose modules use RELATIVE "
        "imports. Applied to a real MCP server on 2026-09-03 it was "
        "unfixable by configuration: `attempted relative import with "
        "no known parent package`. The template's own placeholder "
        "passes only because it happens to use an ABSOLUTE import, "
        "which makes this a gate built to pass its own check. It also "
        "hardcodes the `## Quickstart` heading. TURN ON once the "
        "assertion is PROJECT-DECLARED - your README naming what its "
        "last Quickstart command must print - rather than "
        "`fastmcp inspect`-shaped, and only after measuring it green."
    ),
    "check-brief-report-references.py": (
        "TURN ON when docs/briefs/ holds real briefs. It refuses a "
        "brief that cites a report nobody committed; over the "
        "PREAMBLE shape alone it would parse zero briefs, and a "
        "checker over an empty population reports full coverage."
    ),
    "check-brief-report-refs-controls.sh": (
        "the controls for the checker one row up; wire it in the "
        "same commit as its subject, never before."
    ),
    "check-committed-file-types.py": (
        "TURN ON once `.file-type-allowlist` names the kinds this "
        "project really commits. It refuses a committed file whose "
        "extension is not on that list, which is the cheapest guard "
        "against a stray artefact, a weights blob or a `.env` "
        "reaching the remote."
    ),
    "check-coupling.py": (
        "TURN ON when DESIGN.md §3 states a real module layering. "
        "It enforces that layering against the code; against the "
        "placeholder §3 it has nothing to enforce."
    ),
    "check-coupling-controls.py": (
        "the controls for check-coupling.py; wire it in the same commit as its subject."
    ),
    "check-coupling-sweep.py": (
        "the subject-free sweep behind check-coupling.py; same trigger as its subject."
    ),
    "check-coverage-floors.py": (
        "TURN ON when DESIGN.md names per-module coverage floors. "
        "It parses them OUT of the design and joins them to "
        "`coverage json`, so the numbers live in one place; with no "
        "sentence to parse it exits on an empty population."
    ),
    "check-cross-references.py": (
        "TURN ON once DESIGN.md has numbered sections that cite "
        "each other. It refuses a `§n.m` pointer that resolves to "
        "no heading."
    ),
    "check-design-citations.py": (
        "TURN ON once code and documents cite THIS project's "
        "DESIGN.md at `file:line`. It checks every citation resolves "
        "to a line that exists. ITS BACKLOG IS NOW ZERO and its "
        "register is restored: defect D9 is closed as of 2026-09-08. "
        "The 13 strings its regex read as citations into the SOURCE "
        "project's design are gone - six were pointers extraction "
        "left dangling and three more sat in this checker's own "
        "narrative, all nine now prose - and the four that remain are "
        "this checker showing what its own pattern MATCHES, on two "
        "lines, marked AND registered by address in "
        "docs/reviews/REPOINT-EXEMPT.txt. WHAT STOPS IT NOW IS THE "
        "OPPOSITE CONDITION, and it is the rule two rows of this dict "
        "already apply: the corpus is EMPTY. With every remaining "
        "citation exempt, citations() returns nothing and the checker "
        "refuses at its own SELECTOR CONTROL, exit 1, because a "
        "checker over an empty population reports full coverage. THE "
        "TWO GUARD SITES, named by FUNCTION and by MESSAGE rather "
        "than by line so the next reader can find them without "
        "taking this on trust: _report_bounds in "
        "check-design-citations.py, printing 'SELECTOR CONTROL: no "
        "DESIGN.md citations found anywhere'; and _scan in "
        "check-design-citation-shape.py, printing 'PARSED ZERO "
        "CITATIONS. The selector is broken; a green means nothing.' "
        "THE LINE NUMBERS ARE DELETED RATHER THAN CORRECTED, and "
        "that is a measurement rather than fastidiousness. This row "
        "carried them for exactly one commit. They were 185-190 and "
        "305-307 at the branch point, 187-192 and 308-310 when this "
        "row first quoted them, and the NEXT commit inserted a "
        "wrapper above the second guard and renamed the function "
        "around it, making 308-310 wrong and 'main()' wrong in the "
        "same edit. Two decays inside one branch, in the row written "
        "to explain a checker for citations that stop resolving. "
        "Nothing in this repository checks a cross-file line "
        "reference, so grep the message. "
        "BOTH DIRECTIONS, and run it rather than trusting this "
        "sentence: with the register intact and the backlog swept it "
        "exits 1 at its own SELECTOR CONTROL, and with the register "
        "missing or malformed it exits 3 and prints BROKEN INSTRUMENT, "
        "which is the whole point of separating the two. THE FIRST "
        "VERSION OF THIS SENTENCE SAID BOTH WERE 1. It was true when "
        "written and false three commits later, because the commit "
        "that made a broken register exit 3 did not come back and "
        "correct the prose describing it. Fourth claim on this branch "
        "to decay, and the first that was neither a line number nor a "
        "count, so grep the two quoted phrases above rather than the "
        "digits beside them. "
        "WHAT TURNS IT ON: write your design, cite it from code at "
        "file:line, run this checker until it exits 0, then wire it "
        "and the shape checker in one commit and delete both rows."
    ),
    "check-design-citation-shape.py": (
        "TURN ON with check-design-citations.py, in the same commit "
        "and for the same measured reason. It scans the SHAPE of a "
        "citation - a range that is blank, or nothing but a fence, or "
        "starts or ends on a blank line, cannot be anyone's subject - "
        "and it needs a citation corpus to scan. This template has "
        "none: measured 2026-09-08 with D9 swept, every remaining "
        "citation is exempt and it refuses at its own PARSED ZERO "
        "CITATIONS guard, in _scan, exit 1. Named by function and by "
        "message rather than by line; the row above carries the "
        "measurement that settled why."
    ),
    "check-env-vars-are-declared.py": (
        "TURN ON when config.py declares more than the placeholder "
        "field. It flags an environment variable that src/ "
        "documents and nothing declares. Set its CONFIG constant to "
        "your renamed package first."
    ),
    "check-settings-are-read.py": (
        "the MIRROR of the row above: a Settings field nothing "
        "outside config.py reads. TURN ON with it, and repoint "
        "CONFIG at your package in the same edit."
    ),
    "check-harness-result.sh": (
        "TURN ON when this project has mutation or amputation "
        "harnesses. It asserts every one of them emits the "
        "canonical HARNESS-RESULT line, which is what makes a "
        "verdict machine-readable instead of prose."
    ),
    "check-harness-result-controls.sh": (
        "the controls for the row above; wire it in the same commit as its subject."
    ),
    "check-harness-anchors.py": (
        "TURN ON with the first harness. It refuses a harness "
        "anchor that no longer resolves to its subject, and takes "
        "`--floor N` for the anchor count. THE FLOOR IS DERIVED, "
        "NEVER RETYPED - it defaults to 0 here on purpose, because "
        "a floor carried over from another project is a number that "
        "is wrong on arrival."
    ),
    "check-harness-anchors-controls.sh": (
        "the controls for the row above. It PLANTS a mutation in a "
        "src/ module, so retarget its `target =` line at one of "
        "yours before wiring it."
    ),
    "check-landing-published.py": (
        "TURN ON with the first harness. It refuses a harness that "
        "diagnoses a landing failure and then discards the outcome."
    ),
    "check-merge-invented.py": (
        "DELIBERATELY UNWIRED, and this reason is carried from the "
        "project that wrote it because the argument still holds. "
        "Content can enter a repository inside a MERGE RESOLUTION - "
        "present in neither parent, invisible to every branch diff "
        "and every reviewer. This measures that. It is unwired "
        "because the baseline of already-merged content is unread, "
        "so it can only be honest looking FORWARD; wiring it before "
        "that baseline exists makes it red by construction. Wire it "
        "on the day you decide to hold the line from, and say which "
        "day that is."
    ),
    "check-review-coverage.py": (
        "DELIBERATELY UNWIRED, reason carried intact. It reports "
        "which commits no review round has covered. It belongs on "
        "PULL REQUESTS, not on a push: a merge cannot record its "
        "own sha, so on `main` it reports a backlog it created. "
        "Wire it as a PR-only step, as a SET-ratchet against a "
        "recorded backlog file - never as a demand for zero, which "
        "is red by construction on a moving trunk."
    ),
    "check-no-errexit.py": (
        "TURN ON once this project has shell harnesses. It refuses "
        "a harness that enables errexit, which makes a row abort "
        "where it should be recorded as a failure. Over the carried "
        "scripts alone it measures the template's own machinery, "
        "which is not this project's code."
    ),
    "check-no-shared-tmp-paths.py": (
        "TURN ON with the first harness. It refuses a fixed /tmp "
        "path, which is how two concurrent runs silently collide "
        "and one reports the other's result."
    ),
    "check-no-sigpipe-pipelines.py": (
        "TURN ON with the first harness. It refuses a SIGPIPE-prone "
        "pipeline judging a gate - `cmd | head` can kill `cmd` and "
        "the verdict then describes a truncated run."
    ),
    "check-pytest-bounded.sh": (
        "TURN ON once a harness invokes pytest. It refuses an "
        "unbounded pytest call, which is how a hung run burns a "
        "job's whole budget."
    ),
    "check-secrets-baseline.py": (
        "TURN ON once `.secrets.baseline` is regenerated for THIS "
        "project. The carried baseline is the previous project's "
        "and would audit the wrong tree. Note the trap it was "
        "written against: the scan hook REWRITES the baseline it "
        "then fails on."
    ),
    "check-timeout-literals.py": (
        "TURN ON once timeouts live in one place. It refuses an "
        "abort message that retypes a seconds figure, because a "
        "retyped constant is a second place to change one value."
    ),
    "check-row-floors.py": (
        "TURN ON with the first harness. It reports every harness "
        "whose row count is floored at neither layer - an unfloored "
        "harness can lose rows and stay green."
    ),
    "check-row-floor-exactness.py": (
        "TURN ON with the row above. It asserts a declared floor "
        "EQUALS the live row count rather than merely bounding it: "
        "`>=` is blind to a floor set slack, which was measured "
        "passing at arms=10 floor=9."
    ),
    "check-row-floor-controls.sh": (
        "the controls for the two rows above; wire them together."
    ),
    "check-row-floor-control.sh": (
        "the second control harness for the floor checkers; wire "
        "with its subject. Two files, two different arms - do not "
        "delete one as a duplicate without reading both."
    ),
    "check-suite-floor.sh": (
        "TURN ON once the suite is large enough for a floor to mean "
        "something. It takes the floor as an ARGUMENT, so nothing "
        "is hardcoded - but `pytest --cov` alone does not floor the "
        "count, because deleting a test and the code it covered can "
        "RAISE the ratio."
    ),
    "check-suite-floor-amputation.sh": (
        "the amputation harness proving the suite-floor guard can "
        "fail; wire it in the same commit as its subject."
    ),
    "check_advisories.py": (
        "TURN ON together with a `pip-audit` step. It emits "
        "pip-audit's --ignore-vuln flags from the advisory table in "
        "pyproject and refuses an expired entry. Wired without the "
        "audit step it is a flag generator connected to nothing, "
        "which is exactly how it shipped inert once already."
    ),
    "ci-harness-gate.sh": (
        "the LIBRARY every harness step should call, not a "
        "standalone gate. It reads a harness's exit code, its "
        "canonical result line and its row floor instead of "
        "trusting the step's own `||`. It becomes wired the moment "
        "your first harness step invokes it."
    ),
    "ci-harness-gate-controls.sh": (
        "the controls for the gate library; wire with the first "
        "harness step that uses it."
    ),
    "coverage-test-map.py": (
        "TURN ON only if a harness needs per-row test selection. It "
        "maps a mutated source file to the tests that actually "
        "cover it. Selection is worth roughly 3x on a slow harness "
        "and nothing at all on a fast one - measure before adopting "
        "it."
    ),
    "repoint_exempt.py": (
        "NOT A CHECKER: the register that grants citation exemptions, "
        "imported by check-design-citations.py and "
        "check-design-citation-shape.py. It is a MODULE, so it is never "
        "invoked by a step and can only ever read UNWIRED - the "
        "container is bounded by directory and suffix on purpose, and "
        "carving out an exception for 'library files' is how the "
        "population starts filtering by a property somebody picks. It "
        "becomes reachable when either of its two importers is wired."
    ),
    "select-covering-tests.py": (
        "the library `coverage-test-map.py` feeds; same trigger. It "
        "is sourced by harnesses, not invoked by a CI step, so it "
        "becomes wired through its caller."
    ),
    "harness-result.sh": (
        "the shell library that PRINTS the canonical HARNESS-RESULT "
        "line. Sourced by a harness, never run by a step - it "
        "becomes wired when a harness that sources it is wired."
    ),
    "verdict-guard.sh": (
        "the guard that must be called BEFORE any `^PASSED ` parse. "
        "Absence of passing lines reads as a perfect kill, and a "
        "run that never measured (pytest rc 2/3/4, or a timeout) "
        "produces exactly that absence. Sourced, never run "
        "directly; wired through its caller."
    ),
}

#: THE EXEMPTION IS A DECISION WITH AN END CONDITION, not a hole. In the
#: project this machinery came from, a checker sat here while a backlog
#: of citations was swept; the sweep landed, the checker went green, it
#: was wired, and this entry was deleted in the same commit. Had it been
#: left behind, the stale-exemption check in `main()` would have failed
#: the build - a reason that outlives its condition is how a list stops
#: describing the thing it lists.


def _reasons_are_non_empty() -> None:
    """A blank reason is not an exemption."""
    blank = [k for k, v in UNWIRED_BY_DECISION.items() if not v.strip()]
    if blank:
        raise SystemExit(f"blank exemption reason(s): {blank}")


#: The container's BOUND. A container must be bounded somewhere; what
#: it must not do is filter by NAME inside the bound, because a name is
#: a thing an author picks. Adding a directory here is a decision;
#: adding a file to one of them is not.
CONTAINER_DIRS = ("docs/reviews", "scripts")

#: The KIND. A runnable script file, by suffix. `.md`, `.txt`, `.toml`
#: and the rest are not things that could be wired into a `run:` body,
#: so asking whether they are wired is not a question.
CONTAINER_SUFFIXES = (".py", ".sh")


def container() -> list[str]:
    """Every tracked runnable script under `CONTAINER_DIRS`, as paths.

    Enumerated from the CONTAINER, never a hand-kept list beside it -
    a list maintained next to the thing it describes is blind to the
    member nobody added, which is how three checkers went unwired.

    **AND NEVER BY NAME PREFIX**, which is the same defect wearing a
    container's clothes: the prefix `check-` was the filter here for
    months, and `probe-`, `measure-` and `sample-` files sat outside
    the population while this file printed that everything was wired.
    """
    done = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", *CONTAINER_DIRS],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        print(f"git ls-files failed: {done.stderr.strip()}")
        print("This is a BROKEN INSTRUMENT, not a finding. Exit 3.")
        raise SystemExit(3)
    return sorted(
        p
        for p in done.stdout.split()
        if pathlib.PurePath(p).suffix in CONTAINER_SUFFIXES
    )


def path_of() -> dict[str, str]:
    """Basename -> path, for the whole container.

    **The basename is the key everywhere below, and that is a claim
    this file has to earn.** A step invokes `docs/reviews/check-x.py`,
    so the basename is the substring to look for; but two directories
    can hold the same basename, and if they ever did, one member's
    wiring would silently answer for the other's. Control 6 asserts
    they do not collide. It is 123 distinct basenames over 123 paths at
    `2d886a4`; the day that stops being true, the control fails rather
    than the census quietly merging two files into one row.
    """
    index: dict[str, str] = {}
    for p in container():
        index.setdefault(pathlib.PurePath(p).name, p)
    return index


def checkers() -> list[str]:
    """Basenames of every container member.

    Derived from `container()` rather than re-running the enumeration,
    so the two can never answer different questions. A second selector
    that agreed today and drifted tomorrow is the shape #142 measured:
    two gates, two containers, and one number reported as if it were
    both.
    """
    #: THIS FILE IS IN ITS OWN POPULATION, deliberately - a checker that
    #: exempts itself from its own container is the precise blind spot
    #: it exists to catch. **That is ASSERTED by control 4, not claimed
    #: here**, because this comment was INERT when it was written: git
    #: lists only TRACKED files, the checker was still untracked, and it
    #: excluded itself for a reason no line of code mentions. The census
    #: read 26 and became 27 on the commit that tracked it.
    return sorted(pathlib.PurePath(p).name for p in container())


def strip_comments(body: str) -> str:
    """Drop shell comments, so a `#` line does not read as wired.

    This is the exact false positive that mislabelled three checkers
    twice. The rule is deliberately blunt: from an unquoted `#` to end
    of line. A `#` inside a quoted string would be over-stripped, which
    can only ever cause a FALSE 'unwired' - the safe direction for a
    gate whose job is to find things nobody wired.
    """
    return re.sub(r"(?m)(?<!\$)#.*$", "", body)


#: A heredoc, from its `<<`/`<<-` opener to its terminator on a line of
#: its own. Non-greedy and both ends anchored, so it takes ONE body and
#: not everything between the first opener and the last terminator.
_HEREDOC = re.compile(r"(?ms)<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1.*?^\s*\2\s*$")


def strip_heredocs(body: str) -> str:
    """Drop heredoc bodies, so quoted DATA does not read as a command.

    **MEASURED, AND IT IS THE FALSE-GREEN DIRECTION.** `strip_comments`
    above closes the mention-shaped false positive for `#` lines, and
    the `_sources` docstring claimed on that basis that the question
    asked is the one bash answers. It was not, in one shape: a heredoc
    body is inert text, but a `. "$d/lib/verdict-guard.sh"` line inside
    one starts at a line start and satisfied `_sources`. Planted at
    `check-u12-jobfeed-amputation.sh` with the REAL source line deleted
    and the call left in place - the checker returned rc=0 and named
    nothing. That is the founding #254 defect surviving the instrument
    built to catch it.

    Nothing in this repository was close to it, so this is a latent
    hole rather than a live one - which is exactly when it is cheap to
    close. Stripping is deliberately blunt, as it is for comments: an
    unterminated opener or a `<<` inside a quoted string over-strips,
    and over-stripping can only ever produce a FALSE 'unsourced' - a
    loud wrong red, never a quiet wrong green.
    """
    return _HEREDOC.sub("", body)


def script_body(rel: str) -> str:
    """The inert text of a shell file removed: comments AND heredocs.

    **ONE preparation, used by BOTH shell arms.** The two arms below
    ask different questions of the same bytes, and a stripper wired
    into only one of them is this file's own recurring defect - a fix
    that rebuilds itself one column over. Heredocs first: a `#` inside
    a heredoc body must not truncate the line the terminator is on.
    """
    return strip_comments(strip_heredocs((ROOT / rel).read_text()))


#: Shell operators that END one command and begin the next. A step body
#: is not one command: `out=$(python3 x.py 2>&1); rc=$?` is three, and
#: without this split the first token is `out=$(python3`, which no
#: interpreter test can match. Sixteen of ci.yml's checker steps are
#: written in exactly that capture-and-check shape.
_SEGMENT = re.compile(r"\$\(|`|\)|\(|&&|\|\||;|\||\{|\}|\n")

#: Runners that reach the PROJECT environment, so a `python` token after
#: one of them is NOT bare, however many flags sit in between.
#:
#: **This is a TOKEN test, and that is the whole fix.** The old form
#: was two negative lookbehinds, `(?<!uv run )(?<!uv run --frozen )`.
#: A Python lookbehind must be FIXED WIDTH, so it can spell exactly
#: one prefix and no other, so
#: exact prefix - `uv run  --frozen` with two spaces and
#: `uv run --frozen -- python` both slipped past it and were reported as
#: bare interpreters, failing the build for a reason that was not about
#: the code. Neither can be expressed as a lookbehind at all.
_PROJECT_RUNNERS = frozenset({"uv", "poetry", "pipenv", "hatch", "tox"})

#: A token that IS a bare interpreter, by basename: `python`, `python3`,
#: `python3.12`, and any path to one of them.
_INTERPRETER = re.compile(r"^python(?:\d+(?:\.\d+)*)?$")

#: Interpreter options that consume the FOLLOWING token, so what comes
#: after them is an option ARGUMENT and not the script.
#:
#: `-X faulthandler` is why this set exists. "the first token after the
#: interpreter that does not start with `-`" - the obvious rule, and the
#: one suggested to me - picks `faulthandler` as the script and the
#: detector goes quiet again, one flag later.
_OPT_WITH_VALUE = frozenset({"-X", "-W", "--check-hash-based-pycs"})

#: Options after which there is no script path to find at all.
_OPT_NO_SCRIPT = ("-c", "-m")

#: `-m` modules that RUN A SCRIPT GIVEN FURTHER RIGHT, so `-m` does NOT
#: mean "no script path" for them.
#:
#: `python3 -m coverage run <checker>` executes the checker under a BARE
#: interpreter and ships the identical `ModuleNotFoundError` this file
#: exists to prevent - and it read SILENT until R14 measured it. It is
#: the next spelling of the founding defect: not exotic, just one the
#: rule had not been written against, exactly like the `-u` before it.
_MODULE_RUNNERS = frozenset({"coverage", "trace", "cProfile", "profile", "pdb"})


#: The script token must BE one of OURS, not merely contain the name.
#:
#: **THIS USED TO BE `^check-[\w-]+\.py$` AND THAT WAS THE SAME DEFECT
#: ONE COLUMN OVER.** Widening the population while leaving the
#: bare-interpreter arm matching `check-*` would have rebuilt the
#: prefix blindness inside the fix for it: a `probe-*.py` needing
#: `httpx2`, wired as bare `python3`, would ship the founding
#: `ModuleNotFoundError` and this arm would stay silent. Ten container
#: members need a third-party module and only one of them is a
#: `check-*` file.
#:
#: So membership in the container IS the test, and it is a set lookup
#: rather than a pattern - a pattern is the thing that keeps being
#: defeated by one flag here.
def _is_ours(name: str) -> bool:
    """Is this script token a member of our container?"""
    return name in path_of()


#: `import x` / `from x import ...` at the start of a line - top-level
#: imports only, which is where an unavailable module kills the process.
_IMPORT = re.compile(r"^(?:import|from)\s+([\w.]+)", re.MULTILINE)


def third_party_imports(name: str) -> list[str]:
    """Modules a checker imports that the stdlib does not ship.

    Local-only names are excluded: this asks what a BARE interpreter
    would fail to find, not what is merely unusual.
    """
    #: RESOLVED THROUGH THE CONTAINER, not by joining a hardcoded
    #: directory. This read `ROOT/"docs"/"reviews"/name` while the
    #: population was that one directory; the moment `scripts/` joined,
    #: that join returned a path that does not exist for every member
    #: of the new half - and this function answers `[]` for a path it
    #: cannot resolve. Every `scripts/` checker would have read
    #: 'stdlib-only', and the bare-interpreter arm would have gone
    #: silent about exactly the files the widening was for. A wrong
    #: ZERO that explains itself.
    #:
    #: **AND IT FALLS BACK TO THE TOKEN AS A PATH, WHICH IS NOT A
    #: CONVENIENCE.** If this resolved ONLY container members, it would
    #: share its entire domain with `_is_ours`, and the control that
    #: proves `_is_ours` is not `True` would be vacuous BY
    #: CONSTRUCTION: amputate the membership test and a non-member
    #: would still report no imports, so the row would stay silent
    #: either way. A control whose subject is selected through the
    #: construct it is testing kills nothing - this file already
    #: records that lesson one function down, and it applies here.
    relative = path_of().get(name, name)
    path = ROOT / relative
    if not path.exists() or path.suffix != ".py":
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    found = {m.group(1).split(".")[0] for m in _IMPORT.finditer(text)}
    local = {p.stem for p in path.parent.glob("*.py")}
    return sorted(
        mod
        for mod in found
        if mod not in sys.stdlib_module_names
        and mod != "__future__"
        and mod not in local
    )


def _commands(text: str) -> list[list[str]]:
    """Every command in `text`, as a list of argv tokens.

    Segmented on shell operators first, then `shlex.split`. Tokenising
    is what makes the walk below flag-tolerant; a regex cannot be, which
    is the entire lesson of the defect this replaced.
    """
    out: list[list[str]] = []
    for chunk in _SEGMENT.split(text):
        stripped = chunk.strip()
        if not stripped:
            continue
        try:
            tokens = shlex.split(stripped, comments=True)
        except ValueError:
            #: An unbalanced quote inside ONE segment. A whitespace
            #: split keeps the command visible; dropping it would make
            #: the detector silently blind to exactly the body it could
            #: not parse, which is the failure shape this file is about.
            tokens = stripped.split()
        if tokens:
            out.append(tokens)
    return out


def _runner_script(rest: list[str]) -> str | None:
    """The script a `-m` runner module executes, if there is one.

    A runner takes its OWN sub-commands and options before the script,
    and they are not interpreter options: `coverage run <checker>` puts
    a bare `run` in the way. The interpreter walk in `_script_of` stops
    at the first token not starting with `-`, so handing it `rest` after
    the module name returns `run` - a plausible-looking answer that is
    not a script, and the row would pass for the wrong reason.

    R14's suggested fix did exactly that; it was measured before it was
    applied. So scan right instead, past options and sub-commands, for
    the first token that could BE a script. `.py` is the same suffix
    `_is_ours` implies for a `.py` member, so this narrows nothing.
    """
    for token in rest:
        if token.startswith("-"):
            continue
        if pathlib.PurePath(token).suffix == ".py":
            return token
    return None


def _script_of(tokens: list[str]) -> str | None:
    """The script a BARE interpreter in `tokens` runs, if there is one.

    `None` when the command runs no bare interpreter, when a project
    runner supplies the environment, or when `-c`/`-m` means there is no
    script path at all.
    """
    for i, token in enumerate(tokens):
        if not _INTERPRETER.match(pathlib.PurePath(token).name):
            continue
        if any(t in _PROJECT_RUNNERS for t in tokens[:i]):
            return None
        rest = tokens[i + 1 :]
        j = 0
        while j < len(rest):
            opt = rest[j]
            # `--` NEEDS NO BRANCH OF ITS OWN, and it used to have one.
            # The branch could only change the answer for a token
            # starting with `-`, and `_is_ours` rejects exactly
            # those - so no input existed for which it moved
            # `bare_python_steps`'s output, and deleting it killed no
            # control. The generic break below reaches the same token.
            if not opt.startswith("-") or opt == "-":
                break
            if opt.startswith(_OPT_NO_SCRIPT):
                after = rest[j + 1 : j + 2]
                if opt == "-m" and after and after[0] in _MODULE_RUNNERS:
                    return _runner_script(rest[j + 2 :])
                return None
            j += 2 if opt in _OPT_WITH_VALUE else 1
        return rest[j] if j < len(rest) else None
    return None


def bare_python_steps(text: str) -> list[tuple[str, list[str]]]:
    r"""Checkers run by a bare interpreter that need more than stdlib.

    **THIS EXISTS BECAUSE I SHIPPED EXACTLY THIS AND TURNED main RED.**
    Every other checker in `docs/reviews/` is stdlib-only, so the family
    convention is `run: python3 ...`. This one imports `yaml`; I tested
    it with `uv run`, wired it as `python3`, and my local `python3`
    happened to have pyyaml while the runner's did not. It died with
    `ModuleNotFoundError` on the commit that wired it.

    A convention that is safe for every existing member is not safe for
    the member that breaks the assumption the convention rests on.

    **AND IT WAS DEFEATED BY ONE FLAG FOR ITS WHOLE FIRST DAY.** The
    original was a regex whose path segment was `\S*?`, which cannot
    cross a space, so `python3 -u <checker>` - an ordinary thing to
    write for a step whose Actions output you want unbuffered -
    shipped the identical defect and this said nothing. Widening the
    regex was the tempting repair and it is the wrong one: `-\w+\s+`
    still misses `-X faulthandler`, and nothing pattern-shaped can
    cover `python3.12`.
    So the invocation is TOKENISED and walked instead. The spellings are
    controls in `--self-test`, one per spelling, including the negative
    arm - a detector that fires on everything is as useless as one that
    fires on nothing, and only the negative arm tells them apart.
    """
    problems: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for tokens in _commands(text):
        script = _script_of(tokens)
        if script is None:
            continue
        name = pathlib.PurePath(script).name
        if not _is_ours(name) or name in seen:
            continue
        #: The TOKEN, not the basename. A container member resolves
        #: either way, but the negative control's subject lives outside
        #: the container and only its written path can find it.
        needed = third_party_imports(script)
        if needed:
            seen.add(name)
            problems.append((name, needed))
    return problems


def _sources(text: str, lib: str) -> bool:
    """Is `lib` actually SOURCED here, or merely mentioned?

    **MEASURED, AS THE CONTROL FOR THE CHECK ABOVE.** The first form of
    this test was `lib in body` - the basename appearing anywhere. It
    reported CLEAN on a tree where the `source` lines had been deleted
    from `check-u3-audit-amputation.sh` and
    `check-u12-jobfeed-amputation.sh` and the calls left in place: the
    exact defect, and the check said nothing. What kept it quiet was the
    file's own DOCUMENTATION - the `# shellcheck source=lib/...`
    directive and a comment pointing at the library both contain the
    name, so a substring test finds the prose that describes the
    dependency instead of the dependency.

    So the question asked here is the one bash answers: is there a `.`
    or `source` COMMAND naming this file. Comments are stripped before
    it is asked, AND SO ARE HEREDOC BODIES - see `strip_heredocs`. The
    docstring here used to say only "comments are stripped", which was
    true and not sufficient: a heredoc body carrying a line-start
    source line satisfied this test with the real source line deleted,
    measured and now closed. Callers must prepare the text with
    `script_body`; this function does not strip anything itself.
    """
    #: `[^\n]*` and NOT `\S*`: the argument is
    #: `"$(dirname "${BASH_SOURCE[0]}")/lib/<file>"`, which contains a
    #: SPACE inside the command substitution. `\S*` matched none of the
    #: 94 real source lines in this repository and reported every one of
    #: them as unsourced - a wrong 100% that looked exactly like a wrong
    #: 0% would have, which is why both directions get a control.
    pattern = rf"(?m)^\s*(?:\.|source)\s+[^\n]*{re.escape(lib)}"
    return re.search(pattern, text) is not None


def _calls(text: str, func: str) -> bool:
    r"""Is `func` used in COMMAND POSITION, rather than named as data?

    **A BARE NAME SEARCH IS A FALSE POSITIVE MACHINE, MEASURED.** The
    first form of this check reported
    `docs/reviews/probe-floor-checker-planted-defect.sh` as calling
    `harness_result_ran` without sourcing the library. It does not call
    it at all: it is a mutation probe whose arms are `sed` expressions
    that NAME the function in order to delete or corrupt its call site
    (`:120`, `:127`, `:132`). The name appears; the call does not.

    So the test is the signal bash itself carries - command position -
    and not a substring. A command starts a line, or follows one of
    `; & | ( ) { }` or a `then`/`else`/`do`. Inside `sed 's/^func /'`
    the name follows `/^`, which is none of those.

    **THE CEILING THIS DOCSTRING USED TO NAME WAS NOT ONE, MEASURED.**
    It said a call written as the right-hand side of a command
    substitution assignment (`x=$(func ...)`) is not matched, and that
    widening to catch it would re-admit the `sed` string. Both halves
    are false: the `(` of `$(` is already in the segment class below,
    so `g=$(verdict_guard ...)` returns True today - planted as a
    mutation and CAUGHT - and nothing therefore needs widening. A
    stated ceiling that the code does not have is worse than none: it
    invites a widening that would buy nothing and cost the false
    positive the class was trimmed to avoid.

    KNOWN CEILING, as it actually stands, and measured in the
    `_calls` control rows of `self_test`:

      g=`verdict_guard 1 x 1`     backtick substitution - the segment
                                  class holds `` ` `` for the `$(`
                                  form's sake but a backtick OPENS a
                                  substitution here, and the name
                                  follows it directly with no operator
                                  between, so the leading-boundary
                                  test never fires.
      x=1 verdict_guard a b c     an env-var prefix. The name is in
                                  command position, but what precedes
                                  it is an assignment word, not an
                                  operator.

    `if`/`while`/`until`/`!` WERE in this list and are not any more -
    they are keywords, so `\b` bounds them exactly as it does
    `then`/`else`/`do`, and adding them cannot re-admit the `sed`
    string (`/^` is not a keyword). No call site in this repository
    uses any of these five forms today; that is a fact about the tree,
    not a property of the regex, which is why both remaining ceilings
    are named rather than left to be discovered.
    """
    #: `)` and `}` are deliberately NOT in this set, and that is a
    #: correctness point rather than a concession. Bash cannot start a
    #: command straight after either - `(sub) cmd` and `{ ...; } cmd`
    #: are syntax errors, both need a `;` or a newline first - so a
    #: name following one is always data. MEASURED: with `)` included,
    #: `docs/reviews/check-harness-result.sh` was reported as calling
    #: `harness_result_ran`, from the ERE
    #: `'(^|[^_[:alnum:]])harness_result_ran '` at its `:133`, which
    #: is the checker's SEARCH PATTERN for that call.
    #: `!` is not a word, so `\b` cannot bound it. It only means
    #: negation when a blank follows - `!cmd` is history expansion -
    #: so the blank is required as a zero-width lookahead, leaving the
    #: `\s*` below to consume it.
    pattern = (
        rf"(?m)(?:^|[;&|(]|!(?=\s)|\bthen\b|\belse\b|\bdo\b"
        rf"|\bif\b|\bwhile\b|\buntil\b)\s*{re.escape(func)}\b"
    )
    return re.search(pattern, text) is not None


def library_functions() -> dict[str, str]:
    """Every `scripts/lib/` function name, mapped to its file basename.

    Split out of `unsourced_library_calls` so the `^PASSED ` arm below
    derives the guard's NAME from the library that defines it rather
    than spelling `verdict_guard` into a second place. A hardcoded
    identifier in the second arm would go silent on the day somebody
    renames the function - and go silent in the arm whose entire
    purpose is to notice a guard that is not there.
    """
    #: `name() {` at the start of a line - the one form every
    #: definition in `scripts/lib/` uses. A definition indented inside
    #: another function is not a library export.
    definition = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{", re.M)
    libs: dict[str, str] = {}
    for path in sorted((ROOT / "scripts" / "lib").glob("*.sh")):
        for func in definition.findall(path.read_text()):
            libs[func] = path.name
    return libs


#: The library whose functions make a `^PASSED ` verdict safe. Named
#: once, here, because it is the arm's SUBJECT - the function names
#: themselves are derived from it.
_GUARD_LIB = "verdict-guard.sh"

#: A verdict inferred from `^PASSED ` lines: any `grep` whose pattern
#: is `^PASSED `. This is the SHAPE OF THE DEFECT (#254), not a list of
#: the files that have it. `check-suite-floor-amputation.sh` is not in
#: this population and needs no exemption to stay out of it: its
#: verdict reads `tail -1` for `failed` (`:73`, `:93`) and treats the
#: ABSENCE of that word as a SURVIVOR, so a non-measurement rc reads as
#: alarming rather than as a perfect kill. It fails CLOSED, which is
#: why the rule can be about `^PASSED ` and not about amputation
#: harnesses in general.
_PASSED_VERDICT = re.compile(r"(?m)\bgrep\b[^\n]*\^PASSED ")

#: Scripts that read a `^PASSED ` verdict WITHOUT the guard, each with
#: its reason. Reported on every run and NOT fatal.
#:
#: **THIS IS A RATCHET OVER A SET, AND IT IS NOW EMPTY.** A gate on a
#: moving trunk that demands a zero is red by construction on the day
#: it lands, so the two live instances were named here with their
#: ticket while they were open, and printed under a heading that
#: called them open - switched-off and broken must not render
#: identically. Both were fixed in the same commit that emptied this
#: dict: `check-u1-boot-amputation.sh` and
#: `check-u15-gate-amputation.sh` now source the guard library and
#: call the guard before their `^PASSED ` parse (#283).
#:
#: EMPTY IS THE FIX, NOT A REASON TO DELETE THE ARM. Anything NOT in
#: this dict fails the build, which is the arm's whole point: the next
#: harness to grow a `^PASSED ` verdict cannot arrive unguarded.
#: Adding an entry is a deliberate, visible loosening and needs a
#: ticket in the reason; a new violator with no entry is a red gate,
#: and that is the ratchet.
PASSED_VERDICT_WITHOUT_GUARD: dict[str, str] = {}


def unguarded_passed_verdicts() -> list[str]:
    """Scripts that infer a verdict from `^PASSED ` without the guard.

    **THIS ARM EXISTS BECAUSE THE RULE IT REPLACES WAS PROSE, AND THE
    PROSE WAS FALSE ON THE DAY IT SHIPPED.** The `verdict-guard.sh`
    exemption stated the population as a rule so it could not decay
    into a stale count - *"every amputation harness whose verdict reads
    `^PASSED ` sources it"* - and named
    `check-suite-floor-amputation.sh` as **the** harness deliberately
    outside the set. Measured at `fb9cad2`: FOURTEEN harnesses read a
    `^PASSED ` verdict, thirteen adopters do not all read one
    (`check-u9-http-amputation.sh` reads `^FAILED `), and TWO more -
    `check-u1-boot-amputation.sh` and `check-u15-gate-amputation.sh` -
    read `^PASSED ` with no guard at all. Restating a count as a rule
    does not make the rule true; it just moves where the error lives.

    So the rule is asked of the tree instead. The population is
    DERIVED - any container `.sh` whose text greps `^PASSED ` - and the
    guard's function names are derived from
    `scripts/lib/verdict-guard.sh`, so neither half is a list that
    misses the file nobody thought of.

    Returns EVERY container-relative path that reads a `^PASSED `
    verdict without the guard, ratcheted or not. The caller partitions
    it against `PASSED_VERDICT_WITHOUT_GUARD` - which is what lets a
    ratchet entry whose file has since been FIXED be reported as
    stale, rather than sitting there excusing a defect that is gone.
    """
    guards = [f for f, lib in library_functions().items() if lib == _GUARD_LIB]
    if not guards:
        raise SystemExit(
            f"scripts/lib/{_GUARD_LIB} defines no functions, so this arm "
            "has nothing to look for and would report every `^PASSED ` "
            "reader as clean. BROKEN INSTRUMENT, not a green."
        )

    problems: list[str] = []
    for rel in container():
        if not rel.endswith(".sh") or rel.startswith("scripts/lib/"):
            continue
        body = script_body(rel)
        if not _PASSED_VERDICT.search(body):
            continue
        if any(_calls(body, func) for func in guards):
            continue
        problems.append(rel)
    return problems


def unsourced_library_calls() -> list[tuple[str, str, str]]:
    """Scripts that CALL a `scripts/lib/` function without sourcing it.

    **THIS IS THE FAILURE THAT ACTUALLY HAPPENED, AND EVERY OTHER
    INSTRUMENT WAS GREEN FOR IT.** #254 lifted a guard out of one
    harness into `scripts/lib/verdict-guard.sh` and adopted it in
    thirteen. One harness got the CALL and no `source` line. Bash
    without `-e` (ADR-0023) prints `verdict_guard: command not found`,
    carries on, scores the row by the exact inference the guard exists
    to forbid, and exits 0 with `status=ok`. `bash -n` cannot see it -
    the call is syntactically fine. `shellcheck` cannot see it either:
    CI and the pre-commit hook both pass `--severity=warning` with no
    `-x`, so it never follows a source. A one-file library is a single
    point of SILENT failure across every adopter, and the lift removed
    nothing that would notice.

    The pairing is DERIVED, never listed. Function names come out of
    every `scripts/lib/*.sh` by reading its definitions, and the
    membership test is the library's BASENAME appearing in the caller -
    which matches both the `scripts/` form
    (`"$(dirname ...)"/lib/verdict-guard.sh`) and the `docs/reviews/`
    form (`.../../scripts/lib/harness-result.sh`). A hardcoded
    `verdict_guard` here would have been a list that misses the next
    library somebody adds, which is the shape this file was widened
    twice to escape.

    Returns (caller, function, library-basename) triples.
    """
    libs = library_functions()
    problems: list[tuple[str, str, str]] = []
    for rel in container():
        if not rel.endswith(".sh") or rel.startswith("scripts/lib/"):
            continue
        stripped = script_body(rel)
        for func, lib in sorted(libs.items()):
            if not _calls(stripped, func) or _sources(stripped, lib):
                continue
            problems.append((rel, func, lib))
    return problems


def wired_names(text: str) -> set[str]:
    """Basenames that appear as a real TOKEN in a run body.

    **THIS WAS `name in text`, A BARE SUBSTRING, AND #153's WIDENING
    PROVED IT UNSOUND ON THE FIRST RUN.**
    `scripts/lib/harness-result.sh` read WIRED because
    `docs/reviews/check-harness-result.sh` is invoked at `ci.yml:272`
    and the shorter name is a SUBSTRING of the longer one. A member
    reported as wired because a DIFFERENT member's name contains it is
    a false GREEN - the direction this file exists to prevent - and it
    was invisible while every member was `check-*` with names that
    happened not to nest.

    The old test survived only because its population was small enough
    for the collision not to have happened yet. That is not a property
    anyone chose; it is one that expired.

    So the bodies are TOKENISED - the same `_commands` walk the
    interpreter test uses, which is already the sound instrument in
    this file - and a name counts as wired when it is the BASENAME of
    an actual argv token. `check-harness-result.sh` and
    `harness-result.sh` are different tokens, and a token cannot be
    half of another one.
    """
    seen: set[str] = set()
    for tokens in _commands(text):
        for token in tokens:
            seen.add(pathlib.PurePath(token).name)
    return seen


def run_bodies() -> tuple[str, int]:
    """Every `jobs.*.steps[].run` in every workflow, comment-stripped.

    Returns the concatenated text and the number of run steps seen. The
    count exists so a parse that silently yields nothing cannot report
    'nothing is wired' with a straight face.
    """
    bodies: list[str] = []
    steps = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            continue
        for job in (loaded.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if isinstance(step, dict) and isinstance(step.get("run"), str):
                    steps += 1
                    bodies.append(strip_comments(step["run"]))
    return "\n".join(bodies), steps


def _control_subjects() -> tuple[str, str]:
    """A checker needing a third-party module, and one that does not.

    **DERIVED from the population, never named.** A name written into
    the control here would invert SILENTLY the day that checker's
    imports changed - the row would keep printing PASS while
    asserting the opposite of what it says. That is the same failure
    the census itself is built to avoid, one level up.
    """
    #: PATHS, not basenames, because the container spans two
    #: directories now and `docs/reviews/{name}` was a hardcoded join
    #: that would have built control bodies naming files that do not
    #: exist the moment the chosen subject came from `scripts/`.
    pys = [p for p in container() if p.endswith(".py")]
    needs = [p for p in pys if third_party_imports(p)]
    stdlib = [p for p in pys if not third_party_imports(p)]
    if not needs or not stdlib:
        raise SystemExit(
            "cannot build the spelling controls: the population holds "
            f"{len(needs)} member(s) needing a third-party module and "
            f"{len(stdlib)} stdlib-only. Both arms need at least one; "
            "without the stdlib arm a detector that fires on EVERY "
            "line would pass every row below."
        )
    return needs[0], stdlib[0]


def _non_member_subject() -> str:
    """A real `.py` OUTSIDE the container that needs a third party.

    This is the subject of the `_is_ours` control, and it has to be a
    file that EXISTS: `third_party_imports` returns `[]` for a path
    that does not resolve, so a fabricated name stays silent whatever
    `_is_ours` does and the row would kill nothing. (R14 suggested a
    fabricated `notacheck-...py`; measured, it kills nothing.)

    **AND IT MUST BE OUTSIDE THE CONTAINER, which is a CHANGE, not a
    rewording.** The old subject was a `docs/reviews/` file that merely
    did not start with `check-`. Under the widened population every
    such file is now a MEMBER, so that subject would fire rather than
    stay silent and the control would assert the opposite of what it
    says. The discriminator moved from the name to the container, so
    the control's subject has to move with it - a control that keeps
    its old subject across a rule change is the shape that goes on
    passing while testing nothing.

    Selected by walking `src/`, which is the one tree here that is
    neither container nor test and is guaranteed to import `httpx2`.

    **THE MEMBERSHIP TEST HERE IS `path_of()` DIRECTLY, DELIBERATELY
    NOT `_is_ours`, and that is not a style choice - it was MEASURED.**
    The first version of this function called `_is_ours` to skip
    container members. Arm C of `probe-wired-checker-amputation.py`
    amputates `_is_ours` to always-True; every file then looked like a
    member, this function found no subject at all, and it raised
    `SystemExit` instead of producing a failing row. A control that
    selects its own subject THROUGH the construct it is testing does
    not fail when that construct dies - it disappears, which reads as
    an instrument error rather than a kill. The predecessor of this
    function carried the same warning about `_CHECKER_NAME`, and I
    reintroduced the defect one identifier over while rewriting it.
    """
    members = path_of()
    for path in sorted((ROOT / "src").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if path.name in members:
            continue
        if third_party_imports(relative):
            return relative
    raise SystemExit(
        "cannot build the `_is_ours` control: no `.py` outside the "
        "container imports a third-party module. Without one, nothing "
        "separates 'the script token must BE one of ours' from 'any "
        "script token will do'."
    )


def _spelling_controls() -> list[tuple[str, bool]]:
    """One `(step body, must it fire?)` pair per interpreter spelling.

    The positive rows are the ways a bare interpreter can be spelled;
    every one of them ships the `ModuleNotFoundError` this file exists
    to prevent, and the regex this replaced caught only four of them.

    The `uv` rows are the FALSE-POSITIVE direction: a safe invocation
    reported as bare fails the build for a reason that is not about the
    code, which is how the two-space form (`uv run  --frozen`) behaved.

    The last two rows are the NEGATIVE ARM and they are the load-bearing
    ones. Every positive row above would also pass for a detector that
    simply returned True for any line containing a checker name. Only a
    stdlib-only checker, invoked bare, staying SILENT separates a
    detector from a rubber stamp.
    """
    needs, stdlib = _control_subjects()
    notamember = _non_member_subject()
    return [
        # Bare interpreters. All must fire.
        (f"python3 {needs}", True),
        (f"python {needs}", True),
        (f"python3 -u {needs}", True),
        (f"python3 -X faulthandler {needs}", True),
        (f"python3 -B {needs}", True),
        (f"python3.12 {needs}", True),
        (f"/usr/bin/python3 {needs}", True),
        (f"env python3 {needs}", True),
        (f"python3 -- {needs}", True),
        (f"python3 {needs} --self-test", True),
        (f"out=$(python3 {needs} 2>&1); rc=$?", True),
        # The directory is DERIVED from the chosen subject. It was
        # hardcoded `cd docs/reviews`, which stops being the subject's
        # directory the moment the container spans two of them.
        (
            f"cd {pathlib.PurePath(needs).parent} && "
            f"python3 {pathlib.PurePath(needs).name}",
            True,
        ),
        # THE OTHER TWO MEMBERS OF `_OPT_WITH_VALUE`. Only `-X` was
        # covered, so the set could be reduced to `{"-X"}` and every
        # control still passed. A set with an uncovered member is a
        # list nobody is checking the rest of.
        (f"python3 -W error {needs}", True),
        (f"python3 --check-hash-based-pycs always {needs}", True),
        # THE RUNNER IDIOM. `-m` normally means there is no script, but
        # these run one, under a bare interpreter, with the third-party
        # import unavailable. All three read SILENT until R14. This row
        # is also the ONLY thing standing behind `_OPT_NO_SCRIPT`: see
        # the `-m pytest` row below, which does not do that job.
        (f"python3 -m coverage run {needs}", True),
        (f"python3 -m cProfile -o /tmp/prof.out {needs}", True),
        # The project environment. None may fire.
        (f"uv run python {needs}", False),
        (f"uv run --frozen python {needs}", False),
        (f"uv run  --frozen python {needs}", False),
        (f"uv run --frozen python3 {needs}", False),
        (f"uv run --frozen -- python {needs}", False),
        # No interpreter at all, and no script to find.
        (f"{needs}", False),
        # NOT A CONTROL FOR `_OPT_NO_SCRIPT`, THOUGH IT LOOKS LIKE ONE.
        # Empty `_OPT_NO_SCRIPT` and the walk yields `pytest`, which
        # `_is_ours` rejects - so this row passes either way, for a
        # reason that has nothing to do with the `-m` guard. It sat in
        # the space where the real control belonged, which is worse
        # than an empty space. `-m coverage run` above is the control.
        ("python3 -m pytest", False),
        # THE NEGATIVE ARM. A stdlib-only member must stay silent.
        (f"python3 {stdlib}", False),
        (f"python3 -u {stdlib}", False),
        (f"/usr/bin/python3 -X faulthandler {stdlib}", False),
        # A REAL SCRIPT THAT IS NOT ONE OF OURS. Without this the
        # membership test could be `True` and nothing would notice:
        # every other negative row is a file that is either stdlib-only
        # or does not exist, so none of them can see the difference.
        # The subject is a `src/` module - it EXISTS and it needs
        # `httpx2`, so the ONLY thing keeping this row silent is that
        # it is not in the container.
        (f"python3 -u {notamember}", False),
    ]


def self_test() -> int:
    """Controls, each aimed at a way this checker could lie."""
    text, steps = run_bodies()
    failures: list[str] = []

    # 1. A name I have read a step for must read WIRED. Without this the
    #    parser could return nothing and every answer would be
    #    'unwired'.
    invoked = wired_names(text)
    if _WIRED_SUBJECT not in invoked:
        failures.append(f"{_WIRED_SUBJECT} is wired but reads UNWIRED")

    # 2. A name that exists nowhere must read UNWIRED. A checker that
    #    finds everything is as useless as one that finds nothing.
    if "check-a-name-nobody-has-written.py" in invoked:
        failures.append("a fabricated name reads WIRED")

    # 2b. A NAME THAT IS ONLY A SUBSTRING OF A WIRED ONE MUST READ
    #     UNWIRED. This is not hypothetical and it is not a nit:
    #     `scripts/lib/harness-result.sh` read WIRED under the old
    #     `name in text` test because `check-harness-result.sh` is
    #     invoked at ci.yml:272 and contains it. A FALSE GREEN, found
    #     by #153's widening on its first run, and invisible for as
    #     long as the population happened to hold no nested names.
    #
    #     The subject is BUILT BY CONCATENATION from a name that really
    #     is wired, so this row cannot go stale by pointing at a file
    #     somebody renamed - it re-derives the collision every run.
    real = _WIRED_SUBJECT
    if real not in invoked:
        failures.append("control 2b's premise failed: its subject is not wired")
    elif real[len("check-") :] in invoked:
        failures.append(
            f"`{real[len('check-') :]}` reads WIRED, but it is only a "
            f"SUBSTRING of `{real}`. The wiring test is matching text, "
            "not tokens."
        )

    # 3. The comment strip must actually strip. This is THE defect that
    #    produced two wrong censuses, so it gets a control of its own.
    if "zzz" in strip_comments("echo hi  # zzz\n"):
        failures.append("strip_comments left a commented name behind")

    # 4. THIS FILE MUST BE IN ITS OWN POPULATION, asserted rather than
    #    commented. The comment in `checkers()` claimed it already was,
    #    and the claim was INERT when I wrote it: `git ls-files` lists
    #    only TRACKED files, and the checker was still untracked, so it
    #    excluded itself for a reason the code never mentions. The
    #    census
    #    read 26 and silently became 27 on the commit that tracked it.
    #    A rename that stops matching the glob would do the same thing.
    me = pathlib.Path(__file__).name
    if me not in checkers():
        failures.append(f"{me} is NOT in its own population")

    # 5. ONE CONTROL PER INTERPRETER SPELLING, WITH A NEGATIVE ARM.
    #    The detector this replaced was a regex, and it was defeated by
    #    a single `-u` for its whole first day - in the function whose
    #    docstring says it exists because that exact defect turned main
    #    red. There is no spelling below that a reader can look at and
    #    call unreasonable, and that is the point: the failure was never
    #    an exotic invocation, it was an ordinary one the pattern had
    #    not been written against.
    spellings = _spelling_controls()
    for body, must_fire in spellings:
        fired = bool(bare_python_steps(body))
        if fired != must_fire:
            wanted = "fire" if must_fire else "stay silent"
            failures.append(f"spelling `{body}` should {wanted}, got fired={fired}")

    # 6. NO BASENAME COLLISIONS. The basename is the key everywhere in
    #    this file, and that is safe only while it is unique across the
    #    container. Two directories, two chances to hold the same name -
    #    and if they ever did, one member's wiring would silently answer
    #    for the other's, which is a WRONG GREEN rather than a wrong
    #    red. Asserted, because the widening is what made it possible.
    paths = container()
    seen_names: dict[str, str] = {}
    for p in paths:
        n = pathlib.PurePath(p).name
        if n in seen_names:
            failures.append(f"basename collision: {seen_names[n]} and {p}")
        seen_names[n] = p

    # 7. THE CONTAINER SPANS BOTH DIRECTORIES AND BOTH PREFIXES.
    #    Without this, `CONTAINER_DIRS` could be trimmed back to
    #    `docs/reviews` and every control above would still pass: the
    #    spelling rows derive their subjects FROM the container, so they
    #    move with it. A population that shrinks quietly is exactly the
    #    defect #153 fixed, and it must not be able to come back by an
    #    edit no control notices.
    if not any(p.startswith("scripts/") for p in paths):
        failures.append("the container holds NOTHING under scripts/")
    if not any(p.startswith("docs/reviews/") for p in paths):
        failures.append("the container holds NOTHING under docs/reviews/")
    if not any(pathlib.PurePath(p).name.startswith("check-") for p in paths):
        failures.append("the container holds NO check-* member")
    #: AND AT LEAST ONE MEMBER THAT IS **NOT** `check-*`. The population
    #: was filtered by that prefix once, and `probe-`, `measure-` and
    #: `sample-` files sat outside it while this file printed that
    #: everything was wired. The upstream row named `probe-` directly;
    #: this template ships no probes, so the assertion is written
    #: against the PROPERTY the prefix filter would break - a member
    #: the old selector could not see - rather than against one
    #: prefix's name. `ci-harness-gate.sh` and `check_advisories.py`
    #: are two of them today.
    if not any(not pathlib.PurePath(p).name.startswith("check-") for p in paths):
        failures.append(
            "every container member is named check-*, so a selector "
            "filtering on that prefix would be indistinguishable from "
            "this one and control 7 tests nothing"
        )

    # 8. A SET, NOT A COUNT. `main` partitions the container into wired,
    #    excused and unexplained; assert here that the partition is
    #    exhaustive and disjoint. A count lets one member entering and
    #    another leaving cancel - #151 measured that exact cancellation
    #    on the coverage ratchet, and it is why that gate is a set.
    text_now, _ = run_bodies()
    names_now = set(checkers())
    invoked_now = wired_names(text_now)
    wired_now = {n for n in names_now if n in invoked_now}
    unwired_now = names_now - wired_now
    excused_now = {n for n in unwired_now if UNWIRED_BY_DECISION.get(n, "").strip()}
    unexplained_now = unwired_now - excused_now
    if wired_now | excused_now | unexplained_now != names_now:
        failures.append("the three buckets do not cover the container")
    if wired_now & excused_now or wired_now & unexplained_now:
        failures.append("the buckets overlap; a member is counted twice")

    # 9. `_calls` AND `_sources`, ROW BY ROW, BOTH DIRECTIONS. The
    #    `_calls` docstring named a ceiling the code did not have
    #    (`x=$(func ...)`, asserted as NOT matched, measured as
    #    matched) and stayed wrong for as long as nobody drove the
    #    function directly. A prose claim about a regex is a claim
    #    nothing checks. These rows ARE the ceiling statement now: the
    #    two False rows at the end are the ceiling, and the next person
    #    to widen the alternation finds out here which way they moved
    #    it.
    subject = "verdict_guard"
    call_rows: list[tuple[str, bool]] = [
        (f'  {subject} "$rc" "$OUT" 1', True),
        (f'g=$({subject} "$rc" "$OUT" 1)', True),
        (f"if {subject} 1 x 1; then :; fi", True),
        (f"while {subject} 1 x 1; do :; done", True),
        (f"until {subject} 1 x 1; do :; done", True),
        (f"! {subject} 1 x 1", True),
        (f"sed 's/^{subject} /XX/' f", False),
        (f"echo {subject}", False),
        (f"g=`{subject} 1 x 1`", False),
        (f"x=1 {subject} a b c", False),
    ]
    for body, must_match in call_rows:
        got = _calls(body, subject)
        if got != must_match:
            failures.append(f"_calls(`{body}`) is {got}, want {must_match}")

    lib = _GUARD_LIB
    source_rows: list[tuple[str, bool]] = [
        (f'. "$(dirname "${{BASH_SOURCE[0]}}")/lib/{lib}"', True),
        (f"# shellcheck source=lib/{lib}", False),
        (f'echo ". lib/{lib}"', False),
        # THE L3 ROW. A heredoc body carrying a line-start source line
        # satisfied `_sources` with the real source line deleted -
        # planted, rc=0, nothing named. This row is the fix's control
        # and it fails the moment `strip_heredocs` stops stripping.
        (f"cat >/dev/null <<'DOC'\n. \"$d/lib/{lib}\"\nDOC\n", False),
    ]
    for body, must_match in source_rows:
        got = _sources(strip_comments(strip_heredocs(body)), lib)
        if got != must_match:
            failures.append(f"_sources(`{body!r}`) is {got}, want {must_match}")

    # 10. THE `^PASSED ` ARM, ALL THREE DIRECTIONS, ON SYNTHETIC BODIES.
    #     A script that reads the verdict and does NOT guard must be
    #     named; one that guards must not; one on the ratchet must not.
    #     Driven through the same `_PASSED_VERDICT` / `_calls` pair
    #     `unguarded_passed_verdicts` uses, so a widening of either
    #     shows up here.
    unguarded_body = "survivors=$(grep -E '^PASSED ' \"$OUT\" | sed 's/^PASSED //')"
    guarded_body = f'{subject} "$rc" "$OUT" 1\n{unguarded_body}'
    if not _PASSED_VERDICT.search(unguarded_body):
        failures.append("_PASSED_VERDICT does not match a real survivor extraction")
    if _PASSED_VERDICT.search("grep -E '^FAILED ' \"$OUT\""):
        failures.append("_PASSED_VERDICT matches a `^FAILED ` verdict")
    if _calls(unguarded_body, subject):
        failures.append(f"an unguarded body reads as calling {subject}")
    if not _calls(guarded_body, subject):
        failures.append(f"a guarded body does not read as calling {subject}")

    # 10b. THE RATCHET MUST HOLD REAL, NON-EMPTY REASONS, and every
    #      entry must name a container member. An entry whose reason is
    #      blank excuses a live defect with nothing a reader can weigh.
    member_names = {pathlib.PurePath(p).name for p in paths}
    for name, reason in PASSED_VERDICT_WITHOUT_GUARD.items():
        if not reason.strip():
            failures.append(f"ratchet entry {name} has an empty reason")
        if name not in member_names:
            failures.append(f"ratchet entry {name} is not a container member")

    total = (
        8
        + len(spellings)
        + len(call_rows)
        + len(source_rows)
        + 4
        + 2 * len(PASSED_VERDICT_WITHOUT_GUARD)
    )
    # NAME THE CONTAINER BESIDE THE COUNT (R14 review, L-1). This
    # walks EVERY workflow; probe-ci-checker-steps.py pins ci.yml
    # alone. Both were right and neither said so, so 80 vs 78 read
    # as a contradiction and cost a reviewer a detour to settle.
    parsed_from = ", ".join(sorted(w.name for w in WORKFLOWS.glob("*.yml")))
    print(f"run steps parsed: {steps}  (across {parsed_from})")
    for line in failures:
        print(f"  CONTROL FAILED: {line}")
    if failures:
        print(f"\n{len(failures)} of {total} control(s) failed. The instrument")
        print("is wrong.")
        return 1
    print(f"{total}/{total} controls passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="are the checkers wired?")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    _reasons_are_non_empty()
    if args.self_test:
        return self_test()

    names = checkers()
    if not names:
        print("MATCHED ZERO checkers. An empty population reports full")
        print("coverage, which would mean nothing here. Exit 2.")
        return 2

    text, steps = run_bodies()
    if steps == 0:
        print("PARSED ZERO run steps out of the workflows. Every checker")
        print("would read as unwired for a reason that is not about the")
        print("checkers. This is a BROKEN INSTRUMENT. Exit 3.")
        return 3

    invoked = wired_names(text)
    wired = [n for n in names if n in invoked]
    unwired = [n for n in names if n not in invoked]

    excused = [n for n in unwired if UNWIRED_BY_DECISION.get(n, "").strip()]
    unexplained = [n for n in unwired if n not in excused]
    stale = [n for n in UNWIRED_BY_DECISION if n in wired]
    unknown = [n for n in UNWIRED_BY_DECISION if n not in names]

    #: SET EQUALITY, NOT A COUNT. Every member must land in exactly one
    #: of the three buckets, and the three together must BE the
    #: container. A count would let one member entering and another
    #: leaving cancel to the same total while the sets diverged - the
    #: exact shape #151 measured on the coverage ratchet. This is an
    #: assertion about the partition, so a future edit that drops a
    #: member from every bucket fails here rather than reporting a
    #: smaller, quieter, greener population.
    examined = set(wired) | set(excused) | set(unexplained)
    if examined != set(names):
        missing = sorted(set(names) - examined)
        extra = sorted(examined - set(names))
        print("THE EXAMINED SET IS NOT THE ENUMERATED SET. Exit 3.")
        print(f"  enumerated but not examined: {missing}")
        print(f"  examined but not enumerated: {extra}")
        print("This is a BROKEN INSTRUMENT, not a finding.")
        return 3

    dirs = ", ".join(f"{d}/" for d in CONTAINER_DIRS)
    kinds = ", ".join(CONTAINER_SUFFIXES)
    print(f"Container: tracked {kinds} under {dirs}")
    print(f"Members: {len(names)}")
    print(f"Run steps parsed from {WORKFLOWS.name}/: {steps}")
    print(f"WIRED: {len(wired)}")
    print(f"UNWIRED, with a stated reason: {len(excused)}")
    for name in excused:
        print(f"  EXEMPT   {name}: {UNWIRED_BY_DECISION[name]}")

    problems = False
    if unexplained:
        problems = True
        print(f"\n{len(unexplained)} checker(s) are UNWIRED and unexplained:")
        for name in unexplained:
            print(f"  {name}")
        print(
            "\nAn unwired checker is a claim of coverage nobody can see is\n"
            "false. Either wire it - after measuring it GREEN, because a\n"
            "gate that lands red is one people learn to ignore - or add it\n"
            "to UNWIRED_BY_DECISION with the reason."
        )

    if stale:
        problems = True
        print(f"\n{len(stale)} exemption(s) name a checker that IS wired:")
        for name in stale:
            print(f"  {name}")
        print("The reason has outlived the condition. Delete the entry.")

    bare = bare_python_steps(text)
    if bare:
        problems = True
        print(f"\n{len(bare)} checker(s) run by a BARE interpreter but need")
        print("more than the standard library:")
        for name, needed in bare:
            print(f"  {name}  needs {', '.join(needed)}")
        print(
            "\nA bare `python3` reaches only the standard library. The step\n"
            "passes wherever the module happens to be installed and dies\n"
            "with ModuleNotFoundError on a clean runner. Use\n"
            "`uv run --frozen python ...`, and declare the module in\n"
            "pyproject's dev group - a transitive dependency is a fact\n"
            "nobody promised you."
        )

    unsourced = unsourced_library_calls()
    if unsourced:
        problems = True
        print(f"\n{len(unsourced)} script(s) CALL a scripts/lib/ function without")
        print("sourcing the file that defines it:")
        for caller, func, lib in unsourced:
            print(f"  {caller}  calls {func}()  but never sources {lib}")
        print(
            "\nWithout `set -e` this is SILENT: bash prints 'command not\n"
            "found', the script carries on, and it exits 0. `bash -n` sees\n"
            "nothing wrong and shellcheck at --severity=warning does not\n"
            "follow a source. Add the `. .../lib/<file>` line, and give it\n"
            "a `|| { ...; exit 3; }` so a missing library is loud too."
        )

    #: PARTITIONED, AND THE KNOWN HALF IS PRINTED WHETHER OR NOT
    #: ANYTHING FAILS. The ratchet's entries are open defects; a run
    #: that mentioned them only when a THIRD one appeared would make
    #: "two known holes" and "no holes" render identically on the
    #: terminal - the shape that let 119 consecutive red CI runs read
    #: as normal. And the reverse direction is a finding too: an entry
    #: whose file has since been FIXED must be reported stale, or the
    #: ratchet only ever loosens.
    violators = unguarded_passed_verdicts()
    violating = {pathlib.PurePath(p).name for p in violators}
    known_open = sorted(violating & set(PASSED_VERDICT_WITHOUT_GUARD))
    new_open = [
        p
        for p in violators
        if pathlib.PurePath(p).name not in PASSED_VERDICT_WITHOUT_GUARD
    ]
    stale_open = sorted(set(PASSED_VERDICT_WITHOUT_GUARD) - violating)

    if known_open:
        print(f"\n{len(known_open)} script(s) read a `^PASSED ` verdict WITHOUT the")
        print("guard - KNOWN AND OPEN, ratcheted, not a decision:")
        for name in known_open:
            print(f"  OPEN     {name}: {PASSED_VERDICT_WITHOUT_GUARD[name]}")

    if new_open:
        problems = True
        print(f"\n{len(new_open)} script(s) infer a verdict from `^PASSED ` lines")
        print("without calling the guard, and are not on the ratchet:")
        for rel in new_open:
            print(f"  {rel}")
        print(
            "\nA `^PASSED ` verdict reads the ABSENCE of passing lines as\n"
            "'every assertion died' - a perfect kill. A run that never\n"
            "measured (pytest rc=2/3/4, or a timeout) produces exactly that\n"
            "absence, so the harness publishes its most reassuring possible\n"
            "verdict for a row that ran nothing (#254). Source\n"
            f"scripts/lib/{_GUARD_LIB} and call the guard BEFORE the\n"
            "`^PASSED ` parse - or, if this script genuinely fails closed,\n"
            "add it to PASSED_VERDICT_WITHOUT_GUARD with the reason."
        )

    if stale_open:
        problems = True
        print(f"\n{len(stale_open)} ratchet entry(s) no longer name a violation:")
        for name in stale_open:
            print(f"  {name}")
        print(
            "The file was fixed, renamed or deleted. Delete the entry - a\n"
            "ratchet that only ever loosens is a list of excuses."
        )

    if unknown:
        problems = True
        print(f"\n{len(unknown)} exemption(s) name a file that does not exist:")
        for name in unknown:
            print(f"  {name}")
        print("A renamed or deleted checker leaves its exemption behind.")

    if problems:
        return 1

    print("\nEvery checker is wired, or unwired for a recorded reason.")
    print("NOTE: THIS PROVES EACH IS INVOKED, NOT THAT ITS EXIT CODE GATES")
    print("THE JOB. A step that runs a checker and swallows its status")
    print("reads as WIRED here. Audit that separately: find `run:` steps")
    print("matching `set +e` or `set -uo pipefail` whose body has no")
    print("`|| exit`, `|| {`, `-ne 0` or `exit $rc`. Count `run:` steps,")
    print("never steps - a `uses:` step executes no shell and can never")
    print("be a member. NO COUNT IS PRINTED HERE ON PURPOSE: a")
    print("denominator that moves with every commit goes stale faster")
    print("than any date could qualify it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
