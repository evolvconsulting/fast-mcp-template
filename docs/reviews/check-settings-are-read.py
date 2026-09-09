#!/usr/bin/env python3
"""Flag a `Settings` field that NOTHING outside `config.py` reads.

    python3 docs/reviews/check-settings-are-read.py

**This exists because the question it asks has produced two findings in
one day and no gate here asked it.** §4.3's "a total outbound budget,
configured" was promised and nothing implemented one until U7.
§10.1's variable list specifies a self-throttle and
**`outbound_rate_limit` is still read by nothing** - it is declared,
typed, defaulted, documented in `.env.example` and covered by config
tests, every one of which passes on a setting no code consumes.

**THE `STALE EXEMPTION` ARM IS THE TRIPWIRE FOR THAT ONE.** DESIGN.md
§4.4 now carries rules for a throttle nobody has built, which is the
same shape as a setting nothing reads unless something makes the
implementer read them. The moment `outbound_rate_limit` gains a reader
it leaves the unread set, its exemption goes STALE, and this exits 1
pointing at §4.4. Verified by planting a reader: the arm fires.

**A declared-and-unread setting is worse than a missing one.** A missing
setting fails loudly at the first attempt to use it. A declared one
ships in `.env.example`, an operator sets it, and it silently does
nothing - and `server.json` advertises it to registry consumers as a
knob that works.

**THE RULE IS "READ ANYWHERE BUT ITS OWN DECLARATION", AND MY FIRST
VERSION HAD IT WRONG.** I began with "read outside `config.py`", which
reported FIVE findings - and four were false. `tls_terminated_by_proxy`
and `http_tokens` are consumed by `validate_settings` in `config.py`
itself: refusing to boot IS their behaviour, and no other module needs
to see them. `feed_key`, `feed_secret` and `enable_writes` appear in
`TOOL_REQUIREMENTS`, which is how a deployment is refused for missing
them. A rule that called those unread would have landed a knowingly red
gate on four false positives, which is the failure this project has
refused four times.

**WHAT THIS STILL CANNOT DO.** It proves a NAME is referenced in code,
not that the value changes behaviour. A field read into a variable that
is never used passes here. That is the same "resolves is not correct"
gap the citation checkers have, said out loud rather than discovered
later.

Fields may be exempted with a reason in `EXEMPT`, and an exemption
without a reason is refused - which is the shape `.file-type-allowlist`
already uses for the committed-file-type gate.
"""

from __future__ import annotations

import ast
import json
import pathlib
import subprocess
import sys
import tokenize

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / "src" / "fast_mcp_template" / "config.py"

#: Fields that are deliberately not read by `src/`, each with the reason
#: a reader needs. A bare name is refused: the reason IS the exemption.
#:
#: EMPTY HERE, AND IT WAS NOT UNTIL THIS COMMIT. It carried one row for
#: `outbound_rate_limit`, citing the source project's ADR-0025 and its
#: DESIGN.md §4.4. This template has neither: `docs/adr/` holds only
#: `0000-template.md`, and `Settings` has no such field. So the row
#: could never match `unread`, and the STALE EXEMPTION arm below
#: reported it as "is read now; drop its EXEMPT entry" - which is the
#: opposite of true, the field does not exist at all.
#:
#: THAT MESSAGE WAS INVISIBLE UNTIL THE SAME COMMIT EMPTIED
#: `UNIMPLEMENTED_MARKER`. The marker arm refused first, on a missing
#: `server.json`, and returned before this arm was ever reported. One
#: early refusal was hiding a wrong answer from a later stage, in the
#: file next to the one where the same shape hid a foreign commit.
EXEMPT: dict[str, str] = {}

#: **THE OPERATOR-FACING HALF, AND IT IS SYMMETRIC** (R11-M2). An
#: exemption above is a note between maintainers; `README.md` and
#: `.env.example` are what the person deploying this reads, and both
#: described `JOBVITE_OUTBOUND_RATE_LIMIT` as a working control while
#: `EXEMPT` recorded that nothing reads it. Someone who set it to 1
#: because they were worried about their tenant got no protection and
#: no signal - switched-off and working rendered identically.
#:
#: So an exempt-as-unimplemented field owes a marker in every artefact
#: below, and the rule runs BOTH WAYS: while the field is unread the
#: marker must be PRESENT, and the moment it gains a reader the marker
#: must be GONE. **The second direction is the one that matters.**
#: Without it the throttle ships and these two files keep telling
#: operators it does not work - the same defect pointing the other way,
#: which is exactly how the first one survived a split review.
#:
#: In a TEXT artefact the variable name and the marker must share a
#: LINE, so this cannot pass on a sentence about something else that
#: happens to contain the phrase. In a JSON artefact that rule is
#: structurally unsatisfiable - `"name"` and `"description"` are always
#: on different lines - so the entry is looked up by name and its
#: description is what must carry the marker. Same question, asked in
#: the form each file can actually answer.
#:
#: **`server.json` WAS MISSING FROM THIS TUPLE FOR ITS WHOLE LIFE, AND
#: THE DOCSTRING ABOVE NAMES IT AS THE HARM** (R14-H1). The paragraph
#: that argues this arm into existence ends *"and `server.json`
#: advertises it to registry consumers as a knob that works"* - then the
#: enforced list held `README.md` and `.env.example` and stopped. The
#: omitted artefact is the ONLY one of the three that leaves this
#: repository: `.env.example` and `README.md` are read by someone who
#: has already cloned us, while `server.json` is the PUBLISHED MCP
#: manifest a registry consumer reads without ever seeing the other two.
#: The check covered the two audiences that could recover, and skipped
#: the one that could not.
#:
#: This is the hand-kept-list failure in its usual form: a list written
#: beside its container is blind to the member nobody added. The three
#: artefacts here are the same three `check-env-vars-are-declared.py`
#: names in its own docstring; if a fourth operator-facing artefact ever
#: appears, it must be added HERE TOO, and nothing but review enforces
#: that.
#:
#: EMPTY HERE. Its one row named `outbound_rate_limit` and
#: `JOBVITE_OUTBOUND_RATE_LIMIT`, a setting of the source project that
#: this template's `Settings` does not have, so the row could never
#: match. Add a row when a setting here is declared and documented
#: before it is implemented.
UNIMPLEMENTED_MARKER: dict[str, tuple[str, str, tuple[str, ...]]] = {}


def marker_lines(variable: str, marker: str, name: str) -> list[int]:
    """Lines of `name` carrying BOTH `variable` and `marker`.

    Refuses a path that does not resolve rather than reporting zero
    hits: a search at a missing file exits clean-empty, which is
    indistinguishable from a real absence and would make the
    "marker present" arm pass by never looking.

    **THE LOOKUP IS SCOPED TO `packages[*].environmentVariables`, and
    a DUPLICATE NAME IS REFUSED** (R14-R1 H2). The first version walked
    the WHOLE document and accepted the entry if ANY node with a
    matching name carried the marker. Two plants passed against a lying
    manifest: a DUPLICATE entry with one marked and one not, and a
    marked look-alike planted OUTSIDE `environmentVariables` while the
    real entry was stripped. The manifest's root object also carries
    `name` and `description`, so the walk was searching places that are
    not variable declarations at all. That is the hand-kept-list defect
    this arm was written to fix, surviving inside the fix.

    **JSON IS READ STRUCTURALLY, NOT BY LINE - AND THE FIRST VERSION OF
    THIS PARAGRAPH OVERSTATED WHY** (R14-R1 H1). It claimed the line
    rule "would report a clean zero no matter what the manifest said".
    That is FALSE against the manifest this round wrote:
    `server.json`'s description BEGINS with the variable name, so the
    name and the marker do share a line and the plain rule matches. An
    amputation deleting this whole branch exits 0 - it is a SURVIVOR on
    today's tree, and the claim was refuted by the very wording the same
    round chose.

    **What the branch actually prevents is a FALSE POSITIVE, not a false
    pass.** A description that carries `NOT YET IMPLEMENTED` without
    repeating the variable name is a correctly marked manifest, and the
    line rule calls it unmarked and fails the gate. That is the load-
    bearing case, it is measured by the probe's LINE-RULE arm, and it is
    the honest reason to parse rather than grep. The wording of any one
    description is not something this checker should depend on.
    """
    path = ROOT / name
    if not path.is_file():
        message = f"{name} does not exist, so this check would pass vacuously"
        raise SystemExit(message)
    if path.suffix == ".json":
        return _json_marker_lines(path, variable, marker)
    body = path.read_text(encoding="utf-8").splitlines()
    return [n for n, line in enumerate(body, 1) if variable in line and marker in line]


def _json_marker_lines(path: pathlib.Path, variable: str, marker: str) -> list[int]:
    """The line of `variable`'s entry, if its description is marked.

    Returns the line the NAME sits on so the "lingering marker" message
    can cite a real place to go and delete it, exactly as the line-based
    arm does. An empty list means the entry exists without the marker,
    or does not exist at all - and those are the same failure to a
    consumer reading the manifest.
    """
    text = path.read_text(encoding="utf-8")
    document = json.loads(text)
    if not isinstance(document, dict):
        message = f"{path.name} is not a JSON object"
        raise SystemExit(message)
    entries = [
        entry
        for package in document.get("packages", [])
        if isinstance(package, dict)
        for entry in package.get("environmentVariables", [])
        if isinstance(entry, dict) and entry.get("name") == variable
    ]
    if not entries:
        message = f"{path.name} declares no {variable} entry, so this cannot match"
        raise SystemExit(message)
    if len(entries) > 1:
        message = (
            f"{path.name} declares {variable} {len(entries)} times. Which one an "
            "operator reads is undefined, so this refuses rather than picking."
        )
        raise SystemExit(message)
    if marker not in str(entries[0].get("description", "")):
        return []
    quoted = f'"{variable}"'
    return [n for n, line in enumerate(text.splitlines(), 1) if quoted in line]


def settings_fields() -> dict[str, int]:
    """Every annotated `Settings` field, mapped to its own line."""
    tree = ast.parse(CONFIG.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            return {
                stmt.target.id: stmt.lineno
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and not stmt.target.id.startswith("_")
            }
    message = "no `Settings` class in config.py - the selector is broken"
    raise SystemExit(message)


def _code_lines(path: pathlib.Path) -> list[str]:
    """`path`'s lines with comments stripped.

    A COMMENT MENTIONING THE NAME IS NOT A READ, and that is exactly why
    the `outbound_rate_limit` gap was invisible: `jobvite_client.py`
    names it once, in a comment, to say what it is NOT.

    TOKENIZED, NOT SPLIT ON THE FIRST `#`. The split form truncated any
    line at its first hash regardless of context, so a genuine read
    sitting after a `#` inside a string literal - a URL fragment, a
    format template - vanished and its field reported UNREAD. No line in
    `src/` does that today; this closes it before one does, because the
    failure would look exactly like a real finding.
    """
    body = path.read_text(encoding="utf-8").splitlines()
    with path.open("rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type == tokenize.COMMENT:
                row = token.start[0] - 1
                body[row] = body[row][: token.start[1]]
    return body


def _tracked_sources() -> list[pathlib.Path]:
    """Every tracked `.py` under `src/`, selected by KIND not by PATH.

    `git ls-files` enumerates the container and the suffix is the
    filter. The previous form, `(ROOT / "src").rglob("*.py")`, selected
    by PATH: it admitted any UNTRACKED `.py` left under `src/`. Here
    that direction is a FALSE NEGATIVE and so the worse one - a field
    referenced only from an uncommitted scratch file would be reported
    READ, and the gap this checker exists to find would go unreported.

    MEASURED WHEN THIS CHANGED, and the honest reading is the weaker
    one: both forms yielded the same 23 files, so this closes a defect
    that has not yet happened rather than one that has.
    `check-design-citations.py` is the shape this copies; if the two
    ever disagree, that is the bug.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "src"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    files = sorted(
        ROOT / name
        for name in out.split("\0")
        if name and pathlib.Path(name).suffix == ".py"
    )
    if not files:
        message = "no tracked `.py` under src/ - the selector is broken"
        raise SystemExit(message)
    return files


def references(field: str, declaration_line: int) -> list[str]:
    """Every reference to `field` that is not its declaration."""
    hits = []
    for path in _tracked_sources():
        for num, code in enumerate(_code_lines(path), 1):
            if path == CONFIG and num == declaration_line:
                continue
            if field in code:
                hits.append(f"{path.relative_to(ROOT)}:{num}")
    return hits


def main() -> int:
    fields = settings_fields()
    if not fields:
        print("PARSED ZERO FIELDS. A green here would mean nothing.")
        return 1

    unread = {f: references(f, line) for f, line in fields.items()}
    unread = {f: h for f, h in unread.items() if not h}

    print(f"`Settings` fields: {len(fields)}")
    print(
        f"Referenced in src/ outside their own declaration: "
        f"{len(fields) - len(unread)}",
    )

    bad = [f for f in unread if f not in EXEMPT]
    stale = [f for f in EXEMPT if f not in unread]

    # The operator-facing half (R11-M2), in both directions.
    missing: list[str] = []
    lingering: list[str] = []
    for field, (variable, marker, artefacts) in UNIMPLEMENTED_MARKER.items():
        for name in artefacts:
            found = marker_lines(variable, marker, name)
            if field in unread and not found:
                missing.append(
                    f"{name} does not say {variable} is {marker!r}, but nothing "
                    "reads it - an operator setting it gets no protection and "
                    "no signal"
                )
            if field not in unread and found:
                lingering.append(
                    f"{name}:{found[0]} still says {variable} is {marker!r}, but "
                    "it has a reader now - the marker is the stale half"
                )

    for field in sorted(unread):
        if field in EXEMPT:
            print(f"  EXEMPT   {field}\n           {EXEMPT[field]}")
        else:
            print(f"  UNREAD   {field} - declared, defaulted, and consumed by nothing")

    for field in sorted(stale):
        print(f"  STALE EXEMPTION  {field} is read now; drop its EXEMPT entry")

    for problem in missing + lingering:
        print(f"  MARKER   {problem}")

    if bad or stale or missing or lingering:
        print(
            f"\n{len(bad)} unread field(s), {len(stale)} stale exemption(s), "
            f"{len(missing) + len(lingering)} marker problem(s)."
        )
        print("A declared-and-unread setting ships in .env.example and does nothing.")
        return 1

    print(
        "Unimplemented-marker artefacts checked: "
        f"{sum(len(v[2]) for v in UNIMPLEMENTED_MARKER.values())}"
    )
    print("\nEvery Settings field is referenced somewhere but its own declaration,")
    print("or exempt with a reason. NOTE: this proves the NAME is referenced, not")
    print("that the value changes behaviour - a field read into an unused variable")
    print("passes here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
