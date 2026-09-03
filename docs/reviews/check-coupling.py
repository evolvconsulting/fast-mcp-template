#!/usr/bin/env python3
"""Check DESIGN.md §11's threat model against itself and §8.

Why this exists: the coupling claim in section 11 ("every mitigated
Critical or High row has a required test in section 8") was hand-checked
and wrong on three consecutive review rounds, and the disposition tables
silently dropped six rows that had been added to the analysis. Both are
checkable properties of the document. This script checks them.

Checks, in order:
  1. Every STRIDE row id is unique and matches C<n>-<STRIDE letter><k>.
  2. Every component covers all six STRIDE categories. 2b. Every row is
     either fully unrated (Likelihood, Impact and Risk all "-") or fully
     rated, and a rated row's Risk cell is EXACTLY what the matrix at
     threat-modeling.md:78-82 yields from its Likelihood and Impact. A
     row that cannot be evaluated is a failure, never a row to skip. 2c.
     `no credible threat` is available ONLY to an unrated row, and an
     unrated row must use it. Enforced in both directions.
  3. Every mitigated row of ANY severity accounts for itself in its Test
     column, either by naming a section 8 case that appears verbatim in
     section 8's required-cases list, or by carrying an explicit "not
     required (<rating>)" disposition. Critical and High rows may not
     use that disposition: at those ratings a mitigation must have a
     test. Where the disposition is used, the rating it names must be
     the row's own, so an exemption cannot be granted against a band the
     row does not sit in.
  4. Every Critical or High row that is NOT mitigated appears either in
     the must-mitigate table or in Residual Risks.
  5. Every row id referenced anywhere in section 11 outside the STRIDE
     tables is defined by them.
  6. The "Already mitigated at Critical or High" roster matches the set
     the tables imply, exactly.
  7. Every Test cell, on every row of every severity, is drawn from the
     recognised vocabulary, so a typo or an invented disposition cannot
     pass as one. Any section 8 reference resolves, whether the row is
     mitigated or not.

Why check 3 covers every severity: it originally covered Critical and
High only, which left the property it exists to enforce - a row naming a
test that exists - hand-checked at Medium and Low. Two Medium rows were
added carrying section 8 cases the script could not see. Hand-checking
is what was wrong three rounds running, so the band it is done in does
not make it reliable.

Usage: python3 docs/reviews/check-coupling.py [path/to/DESIGN.md] Exit
code 0 on success, 1 on any failure. No dependencies.

A green from this script is only worth what its failure modes are worth,
so every check has been made to fire against a deliberately broken copy.
Those controls used to live here as prose telling a reader to "copy
DESIGN.md and apply one break", which is a control nobody runs. They are
now executable:

    python3 docs/reviews/check-coupling-controls.py

One mutation of a temp copy per failure mode, each required to produce
exit 1 AND its expected message. DESIGN.md is opened read-only and never
written. Run it whenever this file changes; a check that cannot be shown
to fail is not a check.

AND, because hand-picked controls are not enough - see FIX-10 below:

    python3 docs/reviews/check-coupling-sweep.py

A subject-free harness. It does not choose rows or mutations; it takes
EVERY row that names a §8 case, substitutes EVERY recognised
disposition, and reports every substitution the gate lets through. The
only escapes it should report are the designed exemption - a Medium or
Low mitigated row taking `not required (<its own rating>)`. Anything
else is a hole.

What this script does NOT check, stated so a green is not read as more
than it is:
  - Whether a §8 case a row names actually TESTS what the row claims.
    The check is that the case text exists in §8, not that the test
    behind it is adequate, or written at all.
  - Whether a row's Likelihood and Impact JUDGEMENTS are right. Check 2b
    makes the Risk cell a computed consequence of L and I, so a rerating
    can no longer launder a row into a lower band - but L and I are
    still judgement calls, and someone who wants a Critical row rated
    Medium can still get there by arguing the Impact down. That is a
    review question, not a machine one.
  - Whether a mitigation described in the Mitigation column is real,
    implemented, or sufficient.
  - Anything in §11 outside the STRIDE and closing tables: the prose,
    the counts written out in it, and the Residual Risks rationales are
    all unchecked.
FIX-8 and FIX-9, and how the loophole was closed from both ends. Check 3
used to iterate only rows whose Mitigation column contained the literal
word "Mitigated". Eight rows describe a real mitigation without ever
using it - C1-D1's reads "`RateLimitingMiddleware` with a mandatory
`get_client_id`, sized per session" - so they were skipped in silence.
The check was right; the selector decided it never ran. Check 3 now
iterates EVERY row, and vocabulary, band matching, the Critical/High
exemption ban and §8 resolution are all keyed on the rating or on the
Test cell itself, never on prose. Nothing can be made invisible by
wording.

Inverting the loop alone was NOT sufficient, and the controls proved it:
doing only that let a mitigated row swap its §8 case for a bare
"residual" and go green - controls 3, 10 and 11 all started passing.
Mitigation status is information the Test cell cannot supply, so the
status token in the Mitigation column is still consulted. What changed
is that §11 now states that token deliberately on every row that claims
a mitigation (FIX-9), so it is data rather than a word the prose
happened to contain.

FIX-10, the fifth defect, and why the controls could not have found it.
Round 5 (DESIGN-R5.md, H1) found that `no credible threat` fell through
DISPOSITION_RE unconditionally at every severity and was absent from
NOT_MITIGATED_RE. So a row could carry the "Mitigated" token AND dispose
of itself as "no credible threat": check 3 accepted the disposition, the
biconditional saw no contradiction, and check 4 skipped the row because
the token had placed it in the mitigated set. Measured, not argued - an
exhaustive sweep of 19 rows x 8 dispositions, 152 gate runs, found 25
green results, of which 19 were illegitimate and were exactly the
`no credible threat` column: EVERY row naming a §8 case, the four
Criticals included (the 200-with-401 trap, prompt injection, EEO
exclusion, PII in logs). Checks 2b and 2c close it, and the same sweep
now reports 6 escapes, all of them the designed Medium/Low exemption.

The lesson is about the controls, not the checks. The 21 hand-written
controls found zero of those 19, and could not have: controls 16a and
16b chose C1-S1 and C1-D1, 14d chose C5-R1, 15 chose C3-I1 - all rows
the mutation they encode was designed around, and not one of them
substitutes the one string that opened the hole. A control whose subject
is chosen from the covered set can only confirm the coverage it was
chosen from. That was already written in this file as the FIX-8 lesson,
and it was then re-committed while writing the FIX-9 arms. Hence
check-coupling-sweep.py, which chooses nothing.

The token and the Test cell must now agree BOTH ways, which is what
closes the loophole:
  - a row claiming a mitigation (a §8 case, or "not required
    (<rating>)") must carry the token;
  - a row carrying the token may not dispose of itself as residual /
    unmitigated / accepted.
Verified against the document: 33 rows claim a mitigation, 33 carry the
token, zero violations in either direction. Neither half alone is enough
- the first lets a mitigation hide by dropping the token, the second
lets one hide by never claiming anything.
"""

from __future__ import annotations

import pathlib
import re
import sys

# Repository root, derived from this file's location rather than the
# caller's cwd, so the artifact-existence check below resolves the same
# way from anywhere.
REPO = pathlib.Path(__file__).resolve().parents[2]

ID_RE = re.compile(r"^C(\d+)-([STRIDE])(\d+)$")
REF_RE = re.compile(r"\bC\d+-[STRIDE]\d*\b")
CATEGORIES = ["S", "T", "R", "I", "D", "E"]

# The closed vocabulary a Test cell may use when it does not name a §8
# case. Anything outside this is rejected by check 7 rather than
# silently accepted, so an invented or mistyped disposition cannot pass
# for a real one. Derived from the dispositions the document actually
# uses.
NOT_REQUIRED_RE = re.compile(r"^not required \((Critical|High|Medium|Low)\)$")
# Dispositions that assert the row is NOT mitigated. A row claiming a
# mitigation may not use one. `no credible threat` is in this set
# (FIX-10). It was omitted originally, and that omission was the whole
# of the H1 hole: a row could carry the "Mitigated" token AND dispose of
# itself as "no credible threat", and neither direction of the
# biconditional objected.
NOT_MITIGATED_RE = re.compile(
    r"^(?:no credible threat|residual"
    r"|accepted(?: \(B\d+(?:, ?B\d+)*\))?"
    r"|unmitigated(?: \(B\d+(?:, ?B\d+)*\))?)$"
)
LEVEL_RE = re.compile(r"^[HML]$")
# `threat-modeling.md:78-82`, transcribed. Keyed (Likelihood, Impact).
MATRIX = {
    ("H", "L"): "Medium",
    ("H", "M"): "High",
    ("H", "H"): "Critical",
    ("M", "L"): "Low",
    ("M", "M"): "Medium",
    ("M", "H"): "High",
    ("L", "L"): "Low",
    ("L", "M"): "Low",
    ("L", "H"): "Medium",
}
DISPOSITION_RE = re.compile(
    r"^(?:"
    r"no credible threat"
    r"|residual"
    r"|accepted(?: \(B\d+(?:, ?B\d+)*\))?"
    r"|unmitigated(?: \(B\d+(?:, ?B\d+)*\))?"
    r"|not required \((?:Critical|High|Medium|Low)\)"
    r")$"
)


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def slice_section(text: str, start: str, end: str | None) -> str:
    i = text.index(start)
    j = text.index(end, i) if end else len(text)
    return text[i:j]


def main(path: pathlib.Path) -> int:
    text = path.read_text()
    s8 = slice_section(text, "\n## 8. Testing", "\n## 9.")
    s11 = slice_section(text, "\n## 11. Threat model", "\n## 12.")

    stride = slice_section(s11, "\n### STRIDE Analysis", "\n### Threshold disposition")
    closing = s11[s11.index("\n### Threshold disposition") :]

    failures: list[str] = []
    rows: dict[str, dict[str, str]] = {}

    for line in stride.splitlines():
        if not line.startswith("| C"):
            continue
        c = cells(line)
        if len(c) != 7:
            failures.append(f"row has {len(c)} columns, expected 7: {c[0]!r}")
            continue
        rid, threat, lik, imp, risk, mitigation, test = (
            c[0],
            c[1],
            c[2],
            c[3],
            c[4],
            c[5],
            c[6],
        )
        if not ID_RE.match(rid):
            failures.append(f"id {rid!r} does not match C<n>-<STRIDE letter><k>")
            continue
        if rid in rows:
            failures.append(f"duplicate row id {rid!r}")
            continue
        rows[rid] = {
            "threat": threat,
            "lik": lik,
            "imp": imp,
            "risk": risk,
            "mitigation": mitigation,
            "test": test,
        }

    if not rows:
        print("FAIL: no STRIDE rows parsed; the table shape changed")
        return 1

    # 2. six categories per component
    seen: dict[str, set[str]] = {}
    for rid in rows:
        m = ID_RE.match(rid)
        assert m
        seen.setdefault(m.group(1), set()).add(m.group(2))
    for comp in sorted(seen, key=int):
        missing = [k for k in CATEGORIES if k not in seen[comp]]
        if missing:
            failures.append(
                f"component C{comp} has no row for STRIDE {','.join(missing)}",
            )

    # required-case bullets in section 8
    s8_required = s8[s8.index("Required cases") :]

    haystack = re.sub(r"\s+", " ", s8_required)

    def names_missing_case(test: str) -> str | None:
        """The §8 case this Test cell names but §8 lacks, else None."""
        case = test.split("§8:", 1)[1].strip()
        return None if re.sub(r"\s+", " ", case) in haystack else case

    # 2a-bis. A CASE'S SUBJECT MUST EXIST ON DISK (GATE-1).
    #
    #     The check above confirms a row names a §8 case PRESENT IN THIS
    #     DOCUMENT. It says nothing about whether the artifact that case
    #     asserts against exists at all. That gap was not hypothetical:
    #     C5-E1 was marked Mitigated naming a case asserted "against the
    #     committed files", where one of those files was README.md -
    #     which does not exist and which §10.1 deliberately withholds.
    #     Well-formed row, present case, every gate green, evidence
    #     unproducible. C8-I1 closed on the same shape of evidence with
    #     both halves present.
    #
    #     Scope, deliberately narrow: only bullets that claim to assert
    #     against the repository. A case may legitimately name a file it
    #     does NOT assert against - a citation, an example - and failing
    #     those would make this check noise that someone turns off.
    #
    #     The gating escape hatch is honoured: a bullet may name a file
    #     that does not exist yet PROVIDED it says the arm is gated on
    #     the file's presence. That is not a loophole, it is the
    #     difference between "asserts a thing that cannot be true" and
    #     "asserts a thing when it becomes checkable". A skip is a green
    #     that tested nothing; a declared gate is a stated condition.
    #     What is forbidden is the silent version.
    ARTIFACT_MARKER = "against the committed files"  # noqa: N806 - a selector
    gating_markers = (
        "gated on",
        "once a",
        "when a",
        "when the implementation "  # noqa: N806
        "produces",
    )

    artifact_bullets = [
        b for b in re.split(r"\n- ", s8_required) if ARTIFACT_MARKER in b
    ]

    #     THE SELECTOR'S OWN CONTROL. Every prose-keyed selector in this
    #     gate has gone vacuous at least once - FIX-8 was exactly that,
    #     a row selector keyed on a keyword that silently stopped
    #     matching 8 rows. If the marker phrase is reworded this check
    #     would examine nothing and pass beautifully, which is the
    #     failure it exists to prevent. A selection of zero is therefore
    #     a FAILURE, not a pass.
    if not artifact_bullets:
        failures.append(
            "no §8 case claims to assert " + repr(ARTIFACT_MARKER) + " - either the "
            "artifact-"
            "asserting cases were removed, or the phrase this check selects on was "
            "reworded and the check is now examining nothing"
        )

    def _resolve(token: str) -> bool:
        """Does this repository contain the named file?

        A case names a file the way prose does -
        `CREDENTIAL-CHECKLIST.md`, not `docs/CREDENTIAL-CHECKLIST.md`.
        Resolving bare names against the repo root only was the first
        version of this check, and it reported an existing file as
        missing: a FALSE FAIL, which is worse than a false pass because
        it trains a reader to disbelieve the gate.
        """
        if "/" in token:
            return (REPO / token).exists()
        return any(REPO.rglob(token))

    def _gated_for(bullet: str, token: str) -> bool:
        """Is THIS token's arm gated, or another token's in the bullet?

        Gating per-bullet was the second defect: one gated arm exempted
        every path named anywhere in the same bullet, so substituting a
        nonexistent file for a real one went green. A gate is only an
        excuse for the file it actually names.
        """
        stem = re.split(r"[./]", token)[0].lower().lstrip(".")
        low = bullet.lower()
        for marker in gating_markers:
            start = 0
            while (idx := low.find(marker, start)) != -1:
                # FORWARD window only, and short. A gating clause names
                # its own subject AFTER the marker - "once a README
                # exists". Looking backwards as well let a token 60
                # characters upstream borrow a gate meant for a
                # different file: substituting a nonexistent path for a
                # real one in the same bullet went green. Proximity is
                # not reference.
                if stem in low[idx : idx + 50]:
                    return True
                start = idx + 1
        return False

    for bullet in artifact_bullets:
        for token in sorted(set(re.findall(r"`([^`]+)`", bullet))):
            # A repository path, not a variable or a header: no spaces,
            # and either a file suffix or a separator. Bare identifiers
            # like `request_id` are not candidates. A repository path,
            # not an identifier: no spaces, and it carries a dot or a
            # separator. An earlier version required a 2-4 character
            # suffix at the end, which silently skipped `.gitignore` and
            # `.env.example` - the two files in the OTHER
            # artifact-asserting case, so that whole bullet was examined
            # and nothing in it was ever checked.
            if " " in token or not re.search(r"[./]", token):
                continue
            if _resolve(token):
                continue
            if _gated_for(bullet, token):
                continue
            failures.append(
                f"§8 case asserts {ARTIFACT_MARKER} but {token!r} is not in the "
                f"repository, and "
                f"the case does not declare that arm gated on the file's presence"
            )

    # 2a-ter. EVERY §8 CASE HAS AN OWNER (GATE-2).
    #
    #     The resolution check above runs ONE DIRECTION: §11 row -> §8
    #     case. A case that no row names is an orphan, and deleting it
    #     is invisible. Measured: removing the SIGTERM case leaves the
    #     gate at exit 0, while removing a case a row names is caught.
    #     So a §8 case was not, on its own, a thing this gate could
    #     protect - and this document asserted otherwise until the claim
    #     was tested.
    #
    #     §8 answers to two masters, which is why "named by a §11 row"
    #     is the wrong bar on its own: some cases exist because a THREAT
    #     row needs a test, others because a conformance OBLIGATION does
    #     (B42's request_id echo, the marker-collection guarantee §7.3
    #     rests on). Requiring a threat row for the second kind would
    #     invent threats to satisfy a checker.
    #
    #     So a case is accounted for if a §11 row names it, OR it cites
    #     who requires it - a B-number or a section. A bare one-line
    #     case citing nothing has no stated owner, and nothing anywhere
    #     records why it must exist or what breaks if it goes.
    named_cases = {
        re.sub(r"\s+", " ", m.group(1).strip())
        for m in re.finditer(r"§8: ([^|]+)\|", text)
    }
    s8_bullets = [b.strip() for b in re.split(r"\n- ", s8_required)[1:]]
    if not s8_bullets:
        failures.append(
            "§8's required-case list parsed as empty - the check that "
            "every case has "
            "an owner is examining nothing"
        )
    for bullet in s8_bullets:
        flat = re.sub(r"\s+", " ", bullet)
        if any(n in flat or flat.startswith(n[:60]) for n in named_cases):
            continue
        if re.search(r"\bB\d{1,3}\b|§\d", flat):
            continue
        failures.append(
            "§8 case has no owner - no §11 row names it and it cites no B-number or "
            "section "
            f"saying who requires it: {flat[:90]!r}"
        )

    # 2b. RATINGS ARE COMPUTED, NOT CHOSEN (FIX-10 / H2). §11 convention
    # 3 asserts "Machine-checked:
    #     every rated row agrees with [the matrix]". Until this loop
    #     existed, no machine checked it - the claim was hand-checked at
    #     R3, R4 and R5 while the docstring below disclaimed the check
    #     outright. That is the same shape as the universally quantified
    #     coupling sentence §11 retired: a claim about coverage is worth
    #     exactly the check that was run against it.
    #
    #     This is also the gate's own worst declared blind spot. Without
    #     it, a Critical row rerated to Medium with its Likelihood and
    #     Impact left untouched escapes the Critical/High strictness
    #     entirely and every other check waves it through.
    #
    #     It FAILS on a row it cannot evaluate rather than skipping it.
    #     Skipping is what FIX-8 was: the selector decided the check
    #     never ran. A row is either fully unrated (all three cells "-")
    #     or fully rated with L and I drawn from the ladders at
    #     `:62-74`; anything else - a blank cell, "Med", a half-rated
    #     row - is a failure, not a row to pass over.
    unrated: set[str] = set()
    for rid in sorted(rows):
        lik, imp = rows[rid]["lik"], rows[rid]["imp"]
        rating = rows[rid]["risk"].strip("* ")
        if lik == "-" and imp == "-" and rating == "-":
            unrated.add(rid)
            continue
        if not (LEVEL_RE.match(lik) and LEVEL_RE.match(imp)):
            failures.append(
                f"{rid} cannot be evaluated against the matrix: Likelihood {lik!r} and "
                f"Impact "
                f"{imp!r} must each be H, M or L, or all three of Likelihood, Impact "
                f"and Risk must be '-' for an unrated row"
            )
            continue
        expected = MATRIX[(lik, imp)]
        if rating != expected:
            failures.append(
                f"{rid} is rated {rating!r} but Likelihood {lik} x Impact {imp} yields "
                f"{expected!r} by the matrix at threat-modeling.md:78-82; the Risk "
                f"cell is computed, not chosen"
            )

    high = {
        r for r, v in rows.items() if "Critical" in v["risk"] or "High" in v["risk"]
    }
    all_mitigated = {r for r, v in rows.items() if "Mitigated" in v["mitigation"]}
    mitigated = high & all_mitigated
    unmitigated = high - mitigated

    # 3. EVERY row disposes of itself. This loop iterates all rows
    #    rather than a selected subset, because the selection is what
    #    failed: this check used to run only over rows whose Mitigation
    #    column contained the literal word "Mitigated", and eight rows
    #    describe a real mitigation without ever using it (C1-D1's is
    #    "`RateLimitingMiddleware` with a mandatory `get_client_id`,
    #    sized per session"). Those rows were skipped in silence, and
    #    the check was correct the whole time - the selector decided it
    #    never ran. Nothing below consults mitigation prose, so no
    #    future wording can make a row invisible again.
    for rid in sorted(rows):
        test = rows[rid]["test"]
        rating = rows[rid]["risk"].strip("* ")
        if test.startswith("§8:"):
            absent = names_missing_case(test)
            if absent is not None:
                failures.append(
                    f"{rid} names §8 case {absent!r}, which does not appear in §8",
                )
        elif (m := NOT_REQUIRED_RE.match(test)) is not None:
            if rid in high:
                # "not required" is an exemption from having a test. At
                # Critical and High there is no such exemption: the row
                # either names a §8 case, or says plainly that it is not
                # mitigated (residual / unmitigated / accepted). Keyed
                # on the rating, not on prose.
                failures.append(
                    f"{rid} is a {rating} row and may not use {test!r}: at Critical "
                    f"and High a row "
                    f"either names a §8 case or declares itself unmitigated"
                )
            elif m.group(1) != rating:
                # The disposition names the band it is claiming
                # exemption at. If that band is not the row's own
                # rating, the exemption was granted against a rating the
                # row does not have, which is how a Medium mitigation
                # gets waved through as though it were Low.
                failures.append(
                    f"{rid} is rated {rating} but its disposition {test!r} claims "
                    f"exemption at "
                    f"{m.group(1)}; the rating in the disposition must match the row's "
                    f"own"
                )
        elif not DISPOSITION_RE.match(test):
            failures.append(
                f"{rid} has an unrecognised Test cell {test!r}; expected a '§8: "
                f"<case>' reference "
                f"or one of: no credible threat / residual / accepted / unmitigated / "
                f"not required (<rating>)"
            )
        # H1 / FIX-10. `no credible threat` is not a disposition a rated
        # row may take. §11 convention 4 defines it as what a row says
        # WHERE A CATEGORY CARRIES NO CREDIBLE THREAT, and every such
        # row carries "-" in Likelihood, Impact and Risk. Nothing tied
        # the disposition to an unrated row, so it fell through
        # DISPOSITION_RE unconditionally at every severity - and because
        # it was absent from NOT_MITIGATED_RE, a row could carry the
        # "Mitigated" token beside it and neither direction of the
        # biconditional objected. Measured before the fix: ALL 19 rows
        # naming a §8 case could swap it for this string and the gate
        # stayed green, the four Criticals included. Enforced as a
        # biconditional in both directions, because either half alone
        # leaves the other open.
        if test == "no credible threat" and rid not in unrated:
            failures.append(
                f"{rid} is a rated {rating} row and may not dispose of itself as "
                f"'no credible threat'; that disposition belongs only to a row whose "
                f"Likelihood, Impact and Risk are all '-'"
            )
        if rid in unrated and test != "no credible threat":
            failures.append(
                f"{rid} is unrated (Likelihood, Impact and Risk are all '-') but its "
                f"Test cell is "
                f"{test!r}; an unrated row disposes of itself as 'no credible threat'"
            )

        disposed = test.startswith("§8:") or NOT_REQUIRED_RE.match(test)
        if disposed and rid not in all_mitigated:
            # The other half of the biconditional. A Test cell that
            # names a §8 case or claims a "not required" exemption is
            # asserting the row IS mitigated, so the Mitigation column
            # must say so with the status token. Without this,
            # mitigation status could drift back into being inferred
            # from prose - which is the FIX-8 defect re-entering by the
            # door it left by. Verified against the document: 33 rows
            # claim a mitigation, 33 carry the token, zero violations in
            # either direction.
            failures.append(
                f"{rid} claims a mitigation in its Test cell ({test!r}) but its "
                f"Mitigation column "
                f"carries no status token; a row that claims a mitigation must state it"
            )

        if rid in all_mitigated and NOT_MITIGATED_RE.match(test):
            # A row that claims a mitigation may not dispose of itself
            # with a disposition that means "not mitigated". This is the
            # ONE place the prose keyword is still consulted, and it is
            # deliberately used to ADD a requirement, never to decide
            # whether the row is checked at all - which is the direction
            # that produced FIX-8. A row that drops the keyword loses
            # this extra check but keeps every other one above; see the
            # limitation recorded in the module docstring.
            failures.append(
                f"{rid} states a mitigation but its Test cell is {test!r}, which means "
                f"the row is "
                f"NOT mitigated; a mitigated row names a §8 case or carries 'not "
                f"required (<rating>)'"
            )

    # 4. unmitigated Critical/High must be disposed of
    must = closing[closing.index("Must mitigate before implementation proceeds") :]
    must = must[: must.index("\n\n**", must.index("| Row |"))]
    residual = closing[closing.index("### Residual Risks") :]
    for rid in sorted(unmitigated):
        if rid not in must and rid not in residual:
            failures.append(
                f"{rid} is an unmitigated {rows[rid]['risk'].strip('*')} row and "
                f"appears in neither the must-mitigate table nor Residual Risks"
            )

    # 5. every id referenced outside the STRIDE tables is defined
    for ref in sorted(set(REF_RE.findall(closing))):
        if ref not in rows:
            failures.append(
                f"closing tables reference {ref!r}, which no STRIDE row defines",
            )

    # 6. the "already mitigated" roster matches the tables exactly
    roster_start = closing.index("**Already mitigated at Critical or High**")
    roster = closing[roster_start : closing.index("### Residual Risks", roster_start)]
    claimed = set(REF_RE.findall(roster))
    if claimed != mitigated:
        for extra in sorted(claimed - mitigated):
            failures.append(
                f"roster claims {extra} is a mitigated Critical/High row; it is not",
            )
        for omitted in sorted(mitigated - claimed):
            failures.append(f"roster omits {omitted}, a mitigated Critical/High row")

    # (The former check 7 - vocabulary, and §8 resolution on rows that
    # are not mitigated - is now
    #  part of check 3, which iterates every row. Keeping it separate is
    #  what let the two loops disagree about which rows they covered.)

    rated = set(rows) - unrated
    tested = sum(1 for r in rows if rows[r]["test"].startswith("§8:"))
    print(
        f"{path}: {len(rows)} STRIDE rows, {len(high)} Critical/High "
        f"({len(mitigated)} mitigated by the roster's reckoning, {len(unmitigated)} "
        f"not); "
        f"all {len(rows)} rows checked for disposition, {tested} naming a §8 case."
    )
    if failures:
        print(f"FAIL: {len(failures)} problem(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(
        f"PASS: ids unique, STRIDE coverage complete, all {len(rated)} rated rows "
        f"agree with the "
        f"matrix at threat-modeling.md:78-82 and all {len(unrated)} unrated rows are "
        f"fully "
        f"unrated, all {len(rows)} rows at EVERY severity dispose of themselves by "
        f"naming a §8 "
        "case that exists or carrying a recognised disposition at their own rating, "
        "'no credible threat' is used by unrated rows and only by unrated rows, no "
        "Critical/High "
        "row claims exemption from having a test, mitigation status and Test cell "
        "agree in both "
        "directions, every unmitigated Critical/High row is disposed of, and every "
        "id the closing tables name is defined."
    )
    return 0


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
    sys.exit(main(pathlib.Path(arg)))
