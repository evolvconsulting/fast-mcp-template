#!/usr/bin/env python3
# mypy: allow-untyped-defs, allow-untyped-calls
# ^ This file is a PROBE: its helpers build throwaway clients and
#   responders whose only caller is the arms below. mypy READS it -
#   that is the point of putting docs/reviews in `files` - and every
#   other strict check applies; only the two annotation knobs the ruff
#   per-file-ignores entry already relaxes for ANN are relaxed here, so
#   the two tools say the same thing about the same population.
"""Positive-control harness for check-coupling.py.

Each control is a one-line mutation of a COPY of DESIGN.md held in a
temp file. A control PASSES only when the gate exits 1 AND its output
contains the expected substring. The real docs/DESIGN.md is opened
read-only and never written.
"""

import pathlib
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable

# Derived from this file's location. It was hardcoded to one developer's
# home directory, which is unrunnable for anyone else in a repository
# that ships public.
REPO = pathlib.Path(__file__).resolve().parents[2]
GATE = REPO / "docs/reviews/check-coupling.py"
SRC = (REPO / "docs/DESIGN.md").read_text()

CLOSING_MARK = "### Threshold disposition"


def assert_changed(before: str, after: str, what: str) -> str:
    assert before != after, (
        f"mutation {what!r} was a no-op; the control would be vacuous"
    )
    return after


def droprow(text: str, rid: str) -> str:
    lines = text.splitlines(keepends=True)
    keep = [ln for ln in lines if not ln.startswith(f"| {rid} |")]
    assert len(keep) == len(lines) - 1, (
        f"droprow {rid} removed {len(lines) - len(keep)} lines"
    )
    return "".join(keep)


def test_cell(text: str, rid: str, new: str) -> str:
    """Replace the final (Test) cell of the STRIDE row `rid`."""
    out = re.sub(
        rf"(?m)^(\| {rid} \|.*\| )[^|]*\|$",
        lambda m: m.group(1) + new + " |",
        text,
    )
    return assert_changed(text, out, f"test cell of {rid}")


def mitigation_cell(text: str, rid: str, new: str) -> str:
    """Replace the Mitigation cell (col 6 of 7) of STRIDE row `rid`."""
    out = re.sub(
        rf"(?m)^(\| {rid} \|(?:[^|]*\|){{4}} )[^|]*(\| [^|]*\|)$",
        lambda m: m.group(1) + new + " " + m.group(2),
        text,
    )
    return assert_changed(text, out, f"mitigation cell of {rid}")


def _col(text: str, rid: str, n: int, new: str, what: str) -> str:
    """Replace column `n` (0-based, 0 is the id) of STRIDE row `rid`."""
    out = re.sub(
        rf"(?m)^(\| {rid} \|(?:[^|]*\|){{{n - 1}}} )[^|]*(\|)",
        lambda m: m.group(1) + new + " " + m.group(2),
        text,
        count=1,
    )
    return assert_changed(text, out, f"{what} of {rid}")


def likelihood_cell(text: str, rid: str, new: str) -> str:
    return _col(text, rid, 2, new, "likelihood cell")


def impact_cell(text: str, rid: str, new: str) -> str:
    return _col(text, rid, 3, new, "impact cell")


def risk_cell(text: str, rid: str, new: str) -> str:
    return _col(text, rid, 4, new, "risk cell")


#: a whole-section rewriter handed to `in_closing`/`roster`
Edit = Callable[[str], str]


def in_closing(text: str, fn: Edit) -> str:
    i = text.index(CLOSING_MARK)
    return assert_changed(text, text[:i] + fn(text[i:]), "closing-section edit")


def drop_from_must_table(text: str, rid: str) -> str:
    def fn(closing):
        return "".join(
            ln
            for ln in closing.splitlines(keepends=True)
            if not ln.startswith(f"| {rid} |")
        )

    return in_closing(text, fn)


def roster(text: str, fn: Edit) -> str:
    start = text.index("**Already mitigated at Critical or High**")
    end = text.index("### Residual Risks", start)
    return assert_changed(
        text, text[:start] + fn(text[start:end]) + text[end:], "roster edit"
    )


def s8_drop_case(text: str, case: str) -> str:
    """Delete §8's required-case bullet for `case`; §11 is untouched."""
    i = text.index("Required cases, each failing if its defence is removed:")
    j = text.index("\n## 9.", i)
    s8 = text[i:j]
    b = s8.index("- **" + case)
    e = s8.index("\n- **", b + 1)
    return assert_changed(
        text, text[:i] + s8[:b] + s8[e + 1 :] + text[j:], f"§8 drop {case!r}"
    )


CONTROLS = [
    # --- the eight the script already shipped with ---
    (
        "1  duplicate id: C1-S2 renamed C1-S1",
        lambda t: assert_changed(t, t.replace("| C1-S2 |", "| C1-S1 |", 1), "dup id"),
        "duplicate row id 'C1-S1'",
    ),
    (
        "2  STRIDE gap: the C7-E1 row deleted",
        lambda t: droprow(t, "C7-E1"),
        "component C7 has no row for STRIDE E",
    ),
    (
        "3  High mitigated row's §8 case replaced by a bare 'residual' (C1-R1)",
        lambda t: test_cell(t, "C1-R1", "residual"),
        "C1-R1 states a mitigation but its Test cell is 'residual'",
    ),
    (
        "4  §8 case deleted, §11 unchanged (H2's exact failure mode)",
        lambda t: s8_drop_case(t, "an off-loopback bind without TLS refuses to start"),
        "names §8 case 'an off-loopback bind without TLS refuses to start', "
        "which does not appear in §8",
    ),
    # Re-anchored 2026-08-27. This arm deleted a row from the
    # must-mitigate table; that table is now empty, because C5-R1 and
    # C5-E1 were both closed, so the mutation became a no-op. The
    # control reported itself VACUOUS rather than passing - the property
    # worth keeping - and is re-pointed at the live inverse: a mitigated
    # High silently dropped from the roster.
    (
        "5  C5-E1 dropped from the mitigated roster",
        lambda t: roster(t, lambda r: re.sub(r"C5-E1[^,.]*", "", r)),
        "roster omits C5-E1, a mitigated Critical/High row",
    ),
    (
        "6  must-mitigate table renames C5-R1 to C5-R9",
        lambda t: in_closing(t, lambda c: c.replace("C5-R1", "C5-R9")),
        "closing tables reference 'C5-R9', which no STRIDE row defines",
    ),
    # The roster is prose, so this arm matches C9-T1's clause by pattern
    # rather than by an exact literal. The literal broke the moment
    # C8-I1 was added to the roster and C9-T1 stopped being the last
    # entry. `roster()` asserts the mutation changed something, so the
    # arm went loudly vacuous instead of silently passing - which is the
    # behaviour to keep, but a control that needs repairing every time
    # the sentence is reworded is a control people will delete.
    (
        "7  C9-T1 dropped from the mitigated roster",
        lambda t: roster(t, lambda r: re.sub(r"C9-T1[^,]*, ", "", r)),
        "roster omits C9-T1, a mitigated Critical/High row",
    ),
    # Re-anchored 2026-08-27: C5-R1 became genuinely mitigated, so
    # claiming it in the roster stopped being a lie and this arm stopped
    # testing anything. C4-S1 is residual and NOT mitigable server-side,
    # so it is the durable subject - a row that cannot become mitigated.
    (
        "8  C4-S1, a residual row, claimed in the mitigated roster",
        lambda t: roster(
            t, lambda r: r.replace("C7-I1 PII in logs", "C7-I1 PII in logs, C4-S1")
        ),
        "roster claims C4-S1 is a mitigated Critical/High row; it is not",
    ),
    # --- new: the severity band the widening added ---
    (
        "9  NEW BAND: §8 case deleted under the Medium row C3-T1, §11 unchanged",
        lambda t: s8_drop_case(
            t,
            "a control character or bidi override in a string argument rejected before "
            "dispatch",
        ),
        "C3-T1 names §8 case 'a control character or bidi override in a string "
        "argument "
        "rejected before dispatch', which does not appear in §8",
    ),
    (
        "10 NEW BAND: Medium mitigated row C3-D1 swaps its §8 case for a bare "
        "'residual'",
        lambda t: test_cell(t, "C3-D1", "residual"),
        "C3-D1 states a mitigation but its Test cell is 'residual', which means the "
        "row "
        "is NOT mitigated",
    ),
    (
        "11 NEW BAND: Low mitigated row C6-T1 swaps its §8 case for a bare 'residual'",
        lambda t: test_cell(t, "C6-T1", "residual"),
        "C6-T1 states a mitigation but its Test cell is 'residual', which means the "
        "row "
        "is NOT mitigated",
    ),
    (
        "12 VOCABULARY: invented disposition on a Medium row (typo 'not required "
        "(Meduim)')",
        lambda t: test_cell(t, "C2-I1", "not required (Meduim)"),
        "C2-I1 has an unrecognised Test cell 'not required (Meduim)'",
    ),
    (
        "13 STRICTNESS SURVIVES: mitigated High row C1-S1 uses 'not required (High)'",
        lambda t: test_cell(t, "C1-S1", "not required (High)"),
        "C1-S1 is a High row and may not use 'not required (High)'",
    ),
    # --- the arm that would have caught FIX-8 --- C1-D1's Mitigation
    # column describes a real mitigation and never uses the word
    # "Mitigated". Under the keyword selector every one of these three
    # passed at exit 0. They are the reason check 3 now iterates every
    # row: a control whose subject is chosen from the covered set can
    # only ever confirm the coverage it was chosen from.
    (
        "14a KEYWORD-BLIND ROW, band laundering: C1-D1 (no literal 'Mitigated' in its "
        "prose)",
        lambda t: test_cell(t, "C1-D1", "not required (Low)"),
        "C1-D1 is rated Medium but its disposition 'not required (Low)' claims "
        "exemption "
        "at Low",
    ),
    (
        "14b KEYWORD-BLIND ROW, dangling §8 case: C4-I1 (no literal 'Mitigated' in its "
        "prose)",
        lambda t: test_cell(t, "C4-I1", "§8: a case that was never written"),
        "C4-I1 names §8 case 'a case that was never written', which does not appear in "
        "§8",
    ),
    (
        "14c KEYWORD-BLIND ROW, invented disposition: C9-S1 (no literal 'Mitigated' in "
        "its prose)",
        lambda t: test_cell(t, "C9-S1", "not requried (Medium)"),
        "C9-S1 has an unrecognised Test cell 'not requried (Medium)'",
    ),
    (
        "14d CRITICAL/HIGH may not claim exemption, even with no keyword: C5-R1 (High, "
        "unmitigated)",
        lambda t: test_cell(t, "C5-R1", "not required (High)"),
        "C5-R1 is a High row and may not use 'not required (High)'",
    ),
    (
        "14 BAND LAUNDERING: Medium row C5-T1 claims exemption at Low",
        lambda t: test_cell(t, "C5-T1", "not required (Low)"),
        "C5-T1 is rated Medium but its disposition 'not required (Low)' claims "
        "exemption "
        "at Low",
    ),
    # --- the status-token invariant (FIX-9): the token and the Test
    # cell must agree both ways ---
    (
        "16a STATUS TOKEN STRIPPED from a row that names a §8 case (C1-S1)",
        lambda t: mitigation_cell(
            t,
            "C1-S1",
            "Off-loopback requires TLS or a declared "
            "terminating "
            "proxy; absence is a startup failure, not a "
            "warning (§7.1)",
        ),
        "C1-S1 claims a mitigation in its Test cell ('§8: an off-loopback bind without "
        "TLS refuses to start') but its Mitigation column carries no status token",
    ),
    (
        "16b STATUS TOKEN STRIPPED from a keyword-added row that claims exemption "
        "(C1-D1)",
        lambda t: mitigation_cell(
            t,
            "C1-D1",
            "`RateLimitingMiddleware` with a mandatory "
            "`get_client_id`, sized per session (§4.4)",
        ),
        "C1-D1 claims a mitigation in its Test cell ('not required (Medium)') but its "
        "Mitigation column carries no status token",
    ),
    (
        "15 DANGLING REF ON AN UNMITIGATED ROW: C3-I1 points at a case never written",
        lambda t: test_cell(t, "C3-I1", "§8: a case that was never written"),
        "C3-I1 names §8 case 'a case that was never written', which does not appear in "
        "§8",
    ),
    # --- FIX-10: the H1 hole, and the matrix check that closes the
    # gate's own declared blind spot. SUBJECT RULE, and it is the whole
    # point: every arm below uses a row NO existing control uses. The 21
    # arms above found none of the 19 escapes R5 measured, and could not
    # have - 16a/16b/14d/15 chose C1-S1, C1-D1, C5-R1 and C3-I1, all
    # rows their own mutation was designed around. Picking from the
    # covered set confirms only the coverage it was picked from.
    # check-coupling-sweep.py is the harness that picks nothing; these
    # arms just pin the individual messages.
    (
        "17a H1, CRITICAL: C5-S1 swaps its §8 case for 'no credible threat' (the exact "
        "escape R5 ran)",
        lambda t: test_cell(t, "C5-S1", "no credible threat"),
        "C5-S1 is a rated Critical row and may not dispose of itself as 'no credible "
        "threat'",
    ),
    (
        "17b H1, HIGH: C2-R1 swaps its §8 case for 'no credible threat'",
        lambda t: test_cell(t, "C2-R1", "no credible threat"),
        "C2-R1 is a rated High row and may not dispose of itself as 'no credible "
        "threat'",
    ),
    (
        "17c H1, MEDIUM: C7-T1 swaps its exemption for 'no credible threat'",
        lambda t: test_cell(t, "C7-T1", "no credible threat"),
        "C7-T1 is a rated Medium row and may not dispose of itself as 'no credible "
        "threat'",
    ),
    (
        "17d H1 OTHER DIRECTION: the unrated row C6-E1 disposes of itself as "
        "'residual'",
        lambda t: test_cell(t, "C6-E1", "residual"),
        "C6-E1 is unrated (Likelihood, Impact and Risk are all '-') but its Test cell "
        "is "
        "'residual'",
    ),
    # 18a is the mutation the gate's own docstring used to name as the
    # thing it could not see: "A Critical threat rated Medium escapes
    # the Critical/High strictness entirely."
    (
        "18a MATRIX: C6-I1 rerated Critical -> Medium with L and I untouched, test "
        "dropped",
        lambda t: test_cell(
            risk_cell(t, "C6-I1", "Medium"), "C6-I1", "not required (Medium)"
        ),
        "C6-I1 is rated 'Medium' but Likelihood H x Impact H yields 'Critical' by the "
        "matrix",
    ),
    (
        "18b MATRIX: C8-E2 (L x H) rerated Medium -> Low",
        lambda t: risk_cell(t, "C8-E2", "Low"),
        "C8-E2 is rated 'Low' but Likelihood L x Impact H yields 'Medium' by the "
        "matrix",
    ),
    (
        "18c MATRIX FAILS LOUD rather than skipping: C9-D1's Likelihood set to 'Med'",
        lambda t: likelihood_cell(t, "C9-D1", "Med"),
        "C9-D1 cannot be evaluated against the matrix: Likelihood 'Med' and Impact 'L' "
        "must each be H, M or L",
    ),
    (
        "18d MATRIX FAILS LOUD on a half-unrated row: C1-E1's Impact blanked to '-'",
        lambda t: impact_cell(t, "C1-E1", "-"),
        "C1-E1 cannot be evaluated against the matrix",
    ),
    # --- GATE-1: a §8 case's SUBJECT must exist on disk, not merely be
    # named in the document.
    #
    # These exist because C5-E1 was marked Mitigated naming a case
    # asserted "against the committed files", where one of those files
    # was README.md - which does not exist. Well-formed row, present
    # case, every gate green, evidence unproducible.
    #
    # 19 is the SELECTOR's control and it is the one that matters. The
    # check is keyed on a prose phrase, and every prose-keyed selector
    # in this gate has gone vacuous at least once - FIX-8 was exactly
    # that. Reword the phrase and the check examines nothing and passes
    # beautifully.
    (
        "19 GATE-1 SELECTOR: the artifact-assertion phrase reworded, so the check "
        "selects "
        "nothing",
        lambda t: t.replace(
            "against the committed files", "against the files in the repo"
        ),
        "no §8 case claims to assert 'against the committed files'",
    ),
    # 20 proves the assertion fires on a file that is simply absent. It
    # targets .gitignore specifically: an earlier version of the check
    # required a 2-4 character suffix at the end of the token, which
    # silently skipped BOTH files in this bullet, so the bullet was
    # selected and nothing in it was ever examined.
    (
        "20 GATE-1 ASSERTION: a §8 case names a repository file that does not exist",
        lambda t: t.replace(
            "`.gitignore` covers the credential patterns",
            "`NO-SUCH-GITIGNORE.md` covers the credential patterns",
        ),
        "'NO-SUCH-GITIGNORE.md' is not in the repository",
    ),
    # 21 is the one the first two versions of this check FAILED. A
    # bullet may legitimately name a file that does not exist yet,
    # provided it says that arm is gated on the file's presence. Gating
    # per-BULLET meant one gated arm excused every path named anywhere
    # near it, so swapping a real file for a nonexistent one inside that
    # bullet went green. A gate excuses the file it names, and proximity
    # is not reference.
    (
        "21 GATE-1 GATING IS PER-FILE: a nonexistent file borrows another arm's gate",
        lambda t: t.replace("`CREDENTIAL-CHECKLIST.md`", "`NO-SUCH-FILE.md`"),
        "'NO-SUCH-FILE.md' is not in the repository",
    ),
    # --- GATE-2: every §8 case names its owner.
    #
    # The resolution check runs ONE direction, §11 row -> §8 case, so a
    # case no row names is an orphan and deleting it is invisible. Seven
    # of 25 cases were orphans. Most legitimately serve a conformance
    # OBLIGATION rather than a threat row, and requiring a row for those
    # would invent threats to satisfy a checker - so the bar is "a row
    # names it, or it cites who requires it".
    #
    # This does NOT make deletion visible, and the design says so. It
    # stops a case's justification being stripped while the case stays
    # put, which is the failure that leaves a test nobody can explain
    # and the next reader deletes.
    (
        "22 GATE-2: a case's owner citation stripped, leaving a bare unattributed test",
        lambda t: t.replace(
            "- **a 4xx not tripping the circuit breaker** - §4.3 states it and "
            "`backend/resilience.md:166-168` (B37) requires it: a bad candidate id is "
            "the "
            "caller's "
            "error, not an outage, and a breaker that counts it takes the server down "
            "on "
            "a caller's typo;",
            "- a 4xx not tripping the circuit breaker;",
        ),
        "has no owner",
    ),
    # 23 is the SELECTOR's control, same reasoning as 19: if the §8
    # parse yields nothing this check examines nothing and passes.
    (
        "23 GATE-2 SELECTOR: §8's required-case list emptied",
        lambda t: (
            t[: t.index("Required cases")]
            + "Required cases, each failing if its defence is removed:\n\n"
            + t[t.index("Transport substitution") :]
        ),
        "examining nothing",
    ),
]


def run(text: str) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(text)
        p = f.name
    r = subprocess.run([sys.executable, str(GATE), p], capture_output=True, text=True)
    pathlib.Path(p).unlink()
    return r.returncode, (r.stdout + r.stderr).replace(p, "<temp copy of DESIGN.md>")


print("=" * 80)
print("BASELINE: the real docs/DESIGN.md, unmutated")
rc, out = run(SRC)
print(out.rstrip())
print(f"exit={rc}  -> {'baseline green' if rc == 0 else 'BASELINE IS RED'}")
print("=" * 80)

bad = 0
for name, mutate, expect in CONTROLS:
    print(f"\n--- CONTROL {name}")
    try:
        rc, out = run(mutate(SRC))
    except Exception as e:
        print(f"    MUTATION ERROR: {e}")
        bad += 1
        continue
    print("\n".join("    " + ln for ln in out.rstrip().splitlines()))
    ok = rc == 1 and expect in out
    print(
        f"    exit={rc}, expected message present={expect in out} -> "
        f"{'CONTROL FIRED' if ok else 'CONTROL DID NOT FIRE'}"
    )
    bad += 0 if ok else 1

print("\n" + "=" * 80)
print(f"{len(CONTROLS) - bad}/{len(CONTROLS)} controls fired.")

rc, out = run(SRC)
print(
    f"post-run re-check of the real DESIGN.md: exit={rc} "
    f"({'still green' if rc == 0 else 'RED'})"
)
sys.exit(1 if bad else 0)
