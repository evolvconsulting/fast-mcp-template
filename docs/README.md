# Documentation index

This page says which documents are **current**, which are **historical record**,
and which ones a new reader should actually open.

*(No document count and no byte total here on purpose. Both go stale inside an
afternoon, and an index whose own header is wrong is worse than no index.)*

## Read these

| Document | What it is |
|---|---|
| [`DESIGN.md`](DESIGN.md) | **The authority, and FROZEN.** The record of which version is authoritative is the SHA in [`DESIGN-FREEZE.txt`](DESIGN-FREEZE.txt), not the revision counter in the file's own header. `reviews/check-design-freeze.py` runs in CI and compares that SHA's blob to the trunk's. **Only a numbered ADR may change it.** |
| [`OBLIGATIONS.md`](OBLIGATIONS.md) | Standards clause → the artefact that discharges it, with a subject string a checker asserts. |
| [`adr/README.md`](adr/README.md) | The decision index: every decision, one line, without opening a file. |

## Consulted rather than read through

| Document | What it is |
|---|---|
| [`adr/`](adr/) | The decision records. Ships empty apart from `0000-template.md`. |
| [`research/FASTMCP.md`](research/FASTMCP.md) | FastMCP capabilities. Carried from the first project in this series; **verify it against the version you pin** before relying on it. |
| [`reviews/`](reviews/) | The checkers. Five are wired; the rest are carried, disabled, each with a reason in `check-checkers-are-wired.py`. Run that file to see the list. |
| [`CODE-REVIEW-CHECKLIST.md`](CODE-REVIEW-CHECKLIST.md) | What a review round covers, and what it is allowed to conclude. |
| [`CREDENTIAL-CHECKLIST.md`](CREDENTIAL-CHECKLIST.md) | What to observe the day a real upstream credential first exists. |
| [`briefs/PREAMBLE.md`](briefs/PREAMBLE.md) | The block every agent brief carries verbatim. |

## Historical record

Nothing yet, and that is the point of starting from a template.

**When there is: review rounds, worklogs, audits and briefs are DATED
ARTEFACTS, not current statements.** Where one disagrees with `DESIGN.md`, the
design wins. Keep them under `archive/` once nothing reads them, and edit every
register that names them **in the same commit** — a register pointing at a moved
file is a dangling link nothing will notice.
