# Obligations map: a clause, and the artefact that discharges it

**Checked by:** `docs/reviews/check-obligations.py`, which runs in CI.

## Why this file exists

An obligation from a standards corpus propagates into a repository if and only
if a document somebody actually executed against happened to name it. Everything
else is met *by accident* — correct today because somebody independently
followed the standard, with nothing in the tree that would notice a regression.

This file is the executable version of that record. Each row names an
obligation, the artefact that discharges it, and **a subject string that must
appear in that artefact**. The checker asserts the subject, not merely that a
path resolves: an anchor that resolves to *some* line is exactly how a citation
rots.

**Anchors carry NO line number, deliberately.** A line number pins nothing the
subject does not already pin, and it is the only part of an anchor that drifts.
The subject must therefore be UNIQUE in the file, which is a stronger property
than "appears at line N" — and the checker refuses ambiguity rather than
resolving it to the first hit.

**Parsing zero rows is a FAILURE, never a pass.** An empty map reports perfect
coverage. That is why the table below ships with real rows rather than a
header: delete them only as you replace them.

## The vocabulary

| Class | Meaning | Artefact |
|---|---|---|
| `MET` | discharged by something in this tree | required |
| `CONTRADICTED` | this tree does the opposite, knowingly | required (the ADR) |
| `SUPERSEDED` | an ADR replaced the clause | required (the ADR) |
| `ABSENT` | nothing here discharges it yet | must be `-` |

**An `ABSENT` row has no anchor, so nothing checks it and its prose decays
silently.** A green from the checker is not evidence about those rows. Re-read
them whenever work lands that could discharge one.

## The map

Row ids are `B<n>` (or `B<n><letter>`) and `BASH-<n>`. Keep the two namespaces
separate: a fabricated identifier is worse than an ugly one.

| B | Class | Artifact | Subject | Standard clause | Note |
|---|---|---|---|---|---|
| B1 | MET | `pyproject.toml` | `line-length = 88` | `python.md` line length | TODO: repoint at your corpus' real clause |
| B2 | MET | `pyproject.toml` | `max-doc-length = 72` | `python.md` comments and docstrings | W505 is inert unless this is set |
| B3 | MET | `pyproject.toml` | `strict = true` | `python.md` type hints required | mypy over src, tests and both checker directories |
| B4 | MET | `.github/workflows/ci.yml` | `cancel-in-progress: ${{ github.ref` | CI cost control | the one line that stops superseded runs billing. The subject quotes MORE than the bare setting name on purpose: `cancel-in-progress` alone also matches the comment two lines above, and the checker refuses ambiguity rather than resolving it to the first hit |
| B5 | ABSENT | - | - | TODO: your first real unmet obligation | replace this row |
