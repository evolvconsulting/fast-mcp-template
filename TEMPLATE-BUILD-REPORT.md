# Template build report

**Extracted from:** `fast-mcp-jobvite` at **`6827e9d`** (main) · **Built:** 2026-09-02
**Revised:** 2026-09-03, after the template was applied to a real repository and
**green was not reached**. See §8.

This file records what was carried, what was dropped, every hardcoded floor and
anchor that was neutralised, the measured proof that the Gate tier is green on
an empty project, and — since the revision — the eight defects that only
appeared when the template met code it had not written. **Delete it once your
project is real** — it is a record of how the template was made, not a document
about your project.

> **THE SINGLE MOST IMPORTANT THING IN THIS FILE.** Everything above §8 was
> written while the template's only subject was itself, and it was all true and
> all green. Applying it to one real repository produced **eight defects in one
> afternoon**, four of which no amount of self-testing could have surfaced,
> because a template that grades its own homework passes. §8 is the part that
> was measured against something else.

---

## 1. The reduction

Derived, not estimated. Both figures come from the same command run against each
repository's tracked set (`git ls-files`), so neither counts an untracked
artefact the other happens not to have:

```bash
git ls-files -z | ( n=0; b=0; l=0
  while IFS= read -r -d '' f; do
    n=$((n+1)); b=$((b+$(stat -c%s "$f"))); l=$((l+$(wc -l < "$f")))
  done; echo "files=$n bytes=$b lines=$l" )
```

| | `fast-mcp-jobvite` @ `6827e9d` | template | change |
|---|---:|---:|---:|
| tracked files | 580 | 74 | **−87.2%** |
| bytes | 10,350,025 | 1,215,995 | **−88.3%** |
| lines | 193,810 | 21,628 | **−88.8%** |

**The template figures are AS AT the tree that produced them, EXCLUDING this
file** — a report that counts itself changes the number it reports on every
save. Re-derive with the command above; do not trust the table.

Where the remaining 1.2MB is (bytes, same measurement):

| area | bytes | note |
|---|---:|---|
| root | 366,811 | `uv.lock` alone is 336,202 — a generated artefact, not prose |
| `docs/` | 631,884 | 601,000 of it is the 44 carried checker scripts under `docs/reviews/` |
| `scripts/` | 201,453 | harness machinery and generic checkers |
| `.github/` | 10,942 | the three-tier `ci.yml` |
| `src/` | 3,013 | the placeholder server |
| `tests/` | 1,892 | its suite |

The docs-to-source ratio the source repository reached (5.43x on live surface,
bytes) is not meaningfully comparable here, because the template's "source" is a
40-line placeholder. **The number that matters is that `docs/` holds ZERO
records**: no review round, no worklog, no audit, no brief, no numbered decision.
Everything under `docs/reviews/` is a runnable checker.

---

## 2. What was carried, and why

### 2.1 The registry mechanism — the single most valuable file

`docs/reviews/check-checkers-are-wired.py`, **WIRED**. It enumerates every
tracked `.py`/`.sh` under `docs/reviews/` and `scripts/` and requires each to be
either invoked by a `run:` step in `.github/workflows/` or listed in
`UNWIRED_BY_DECISION` **with a non-empty reason**. It parses the workflow YAML
rather than grepping it, because a grep counts a name in a comment as wired. It
also checks the reverse direction: an exemption naming a checker that IS wired,
or a file that does not exist, is a failure.

That reverse check is why this is the mechanism that prevents rot. Turning a gate
on is two edits in one commit — wire the step, delete the row — and doing either
alone fails the build.

**`UNWIRED_BY_DECISION` was emptied of the source project's 79 entries and
repopulated with 39 of the template's own**, each stating *when to turn that gate
on*. Not one reason was inherited.

### 2.2 The ENABLED gates

**This section said FIVE and now says six, and the swap is the honest part.**
`check-quickstart.py` was one of the original five and is now shipped DISABLED;
three gates were added after §8. Derive the current list rather than trusting
this table — `uv run --frozen python docs/reviews/check-checkers-are-wired.py`
prints WIRED and EXEMPT with reasons, and it is the thing CI reads.

| Gate | What it asserts |
|---|---|
| `check-checkers-are-wired.py` (+ `--self-test`) | the registry above; 53/53 controls |
| `check-design-freeze.py` | `docs/DESIGN.md` at the SHA in `DESIGN-FREEZE.txt` is the same **blob** as on the trunk |
| `check-adr-numbers.py` | ADR numbers unique and contiguous, and `adr/README.md` lists every one — **checked in both directions** |
| `check-obligations.py` | every row in `OBLIGATIONS.md` resolves to a line containing its subject; zero rows is a FAILURE |
| `check-default-branch-is-triggered.py` | **added by §8.** This repository's default branch is in the workflow's push trigger, and no `if:` names a trunk literally |
| `check-coverage-ratchet.py` | **added by §8.** Coverage has not fallen below `docs/coverage-baseline.txt` |
| `check-mypy-ratchet.py` | **added by §8.** No mypy error absent from `docs/mypy-baseline.txt` |

`check-quickstart.py` is **carried DISABLED** with its reason in
`UNWIRED_BY_DECISION`. It hardcodes `fastmcp inspect`, which takes a *file* and
cannot load a package using relative imports — the Python norm. It passed here
only because the placeholder server happens to use an absolute one, which made
it a gate built to pass its own check (§8, defect 3).

**Each of the three new gates ships a controls script that plants the failure
and requires the checker to refuse it**, and those controls run in Gate. Every
one of them caught something while being written — see §8's "what the controls
caught" column, which is the argument for writing the failing arm first.

Plus the ordinary tooling: `uv lock --check`, `ruff check`, `ruff format
--check` (excluding the carried machinery — §8, defect 2), `mypy --strict` (over
`src`, `tests`, `docs/reviews`, `scripts`), `pytest --cov` with a zero-skips
guard, and actionlint on the Merge tier.

**Why a small core and not thirty-seven.** 68 checkers exist in the source; 31
are unit-specific and encode that project's tool surface, so none of them
transfers. Of the 37 generic ones, enabling all of them here would hand every
child repository three dozen gates it has not earned. That is precisely how the
source repository reached its documentation ratio. The enabled ones are those
that hold on a project with no code in it yet — **and §8 is the evidence that
"holds on an empty project" and "holds on a real one" are different claims.**

### 2.3 The 39 carried-but-DISABLED members

Present in the tree, each with a one-line note in `UNWIRED_BY_DECISION` saying
when to enable it. See them with:

```bash
uv run --frozen python docs/reviews/check-checkers-are-wired.py
```

Two are disabled **with their original arguments intact**, because those
arguments still hold and are worth reading:

- **`check-review-coverage.py`** — belongs on PULL REQUESTS, not on a push: a
  merge cannot record its own sha, so on `main` it reports a backlog it created.
  Wire it as a SET-ratchet against a recorded backlog file, never as a demand for
  zero, which is red by construction on a moving trunk.
- **`check-merge-invented.py`** — content can enter a repository inside a MERGE
  RESOLUTION, present in neither parent, invisible to every branch diff and every
  reviewer. It can only be honest looking FORWARD, from a day you name.

### 2.4 The harness libraries

`scripts/lib/harness-result.sh`, `scripts/lib/verdict-guard.sh`,
`scripts/lib/select-covering-tests.py`, and `scripts/ci-harness-gate.sh`. All
four are disabled-by-non-use: they are sourced or called by harnesses, and this
template ships no harnesses. They become wired through their first caller.

`verdict-guard.sh` carries the lesson that justifies it: a `^PASSED ` verdict
reads the ABSENCE of passing lines as a perfect kill, and a run that never
measured (pytest rc 2/3/4, or a timeout) produces exactly that absence — so a
harness publishes its most reassuring possible verdict for a row that ran nothing.

### 2.5 The CI shape

`.github/workflows/ci.yml`, three tiers:

| Tier | Trigger | Target |
|---|---|---|
| Gate | every push and PR | under 3 min |
| Merge | push to `main` (CodeQL + actionlint) | under 6 min |
| Assurance | weekly cron, manual dispatch, or a push touching code | 60–70 min, **one serial job** |

Carried deliberately: `concurrency: cancel-in-progress` (exempting `main`), path
filters that keep a README-only change off the suite *except* `README.md` itself
because the Quickstart gate parses it, `runs-on: ubuntu-latest` everywhere, and
`fetch-depth: 0` on the jobs that resolve the freeze SHA.

**THE `if:` FAIL-OPEN FINDING IS CARRIED, code and comment.** At
`harness-assurance`:

```yaml
|| (github.event_name == 'push' && needs.changes.outputs.code != 'false')
```

`needs.<job>.outputs.<name>` is the **empty string** when that job was skipped or
failed. Written `== 'true'` the condition then evaluates false and the whole tier
is skipped — and a skipped job renders GREY, not red, so a broken classifier
silently deletes the tier and nobody sees a failure. Written `!= 'false'` the same
breakage runs the tier, which fails CLOSED. The `changes` job carries the same
shape internally: an empty `git diff` (first push, force-push, shallow fetch)
answers `code=true`, not `false`.

**This is NOT a verbatim copy of the source `ci.yml`.** That file is 2,243 lines
and 128KB, most of it commentary about one project's units, deferrals and
incident history. Copying it would have imported the archaeology this extraction
exists to leave behind. The tier structure, the triggers, the concurrency and
path rules, the `bash -e` / `set +e` idiom with its explanation, and the
fail-closed `if:` were carried; the Jobvite-specific step bodies were not.

### 2.6 Shapes, gutted

`docs/DESIGN.md`, `docs/OBLIGATIONS.md`, `docs/README.md`, `docs/adr/README.md`,
`docs/CODE-REVIEW-CHECKLIST.md`, `docs/CREDENTIAL-CHECKLIST.md`,
`docs/briefs/PREAMBLE.md`, `docs/adr/0000-template.md`. Structure, headings and
the rules that made each one worth having; zero project content.

`docs/research/FASTMCP.md` is carried whole — it is the one research document
that transfers to an MCP series. **Verify it against the FastMCP version you
pin** before relying on it.

---

## 3. What was DROPPED, asserted by file count

Counted with `git ls-files <pattern> | wc -l` in each repository:

| Class | source @ `6827e9d` | template | what survives |
|---|---:|---:|---|
| `docs/reviews/REVIEW*` | 27 | **0** | — |
| `docs/worklogs/*` | 57 | **0** | — |
| `docs/briefs/*` | 83 | **1** | `PREAMBLE.md`, the shape |
| `docs/adr/0*.md` | 35 | **1** | `0000-template.md`, the shape |
| `docs/plans/*` | 1 | **0** | the plan is not carried |
| `docs/research/*` | 22 | **1** | `FASTMCP.md` only |
| `docs/archive/*` | 30 | **0** | — |

And by name over every tracked file under `docs/`:

| name contains | source | template |
|---|---:|---:|
| `AUDIT` | 16 | **0** |
| `MEASURED` | 17 | **0** |
| `REPORT` | 52 | **0** |
| `WORKLOG` | 26 | **0** |
| `BRIEF` | 36 | **0** |
| `REVIEW` | 45 | **1** (`CODE-REVIEW-CHECKLIST.md`, a shape) |
| `HANDOFF` | 1 | **0** |
| `PROFILE` | 1 | **0** |

**Dropped entirely, by decision:**

- `check-standards-citations.py` — the standards-corpus gate. It has been
  green-and-inert since it was written because the corpus needs a token nobody
  provisioned. **An inert gate in a template is worse than no gate, because it
  looks like coverage.** `check-clause-citations.py`, `check-resweep-verdicts.py`
  and `check-plan-measurements.py` went with it: each needs a corpus this
  template does not ship (a standards corpus, a review-round corpus, a plans
  corpus), and a checker over an empty population reports full coverage.
- All 31 unit-specific checkers (`check-u0`…`check-u15`, body-cap,
  critical-coverage, log-redaction, audit, jobs, inbound) — they encode one
  project's tool surface.
- Every `probe-*`, `measure-*`, `sample-*`, `apply-*` and `one-shot/` file —
  one-shot measurements of a specific past question.
- `check-mirror-liveness.py` and its controls — they check a `mirror.yml`
  workflow this template does not ship.

---

## 4. Every floor, anchor and literal that was NEUTRALISED

The hard warning was that carried checkers hardcode the source project's numbers
and the template's first CI run would be red before anyone wrote a line of code.
This is the complete list of what was changed, and all of it landed in the same
commit as the copy.

| Site | Was | Now |
|---|---|---|
| `check-quickstart.py` `MUST_PRINT` | the literal string `"fast-mcp-jobvite"` | `_project_name()`, **read from `pyproject.toml`'s `[project] name`** with `tomllib`. A literal here goes on asserting the previous project's name after a rename: green where the rename was incomplete, red where it was complete, wrong either way. |
| `check-checkers-are-wired.py` `UNWIRED_BY_DECISION` | 79 entries about another repository's tasks, branches and incidents | emptied; 39 template entries, each naming a turn-on condition |
| `check-checkers-are-wired.py` self-test control 1 and 2b | hardcoded `check-design-citations.py` as the known-wired subject — **not wired here**, so both controls would have failed | `_WIRED_SUBJECT = "check-design-freeze.py"`, with a comment recording that it is hardcoded ON PURPOSE (deriving it from `wired_names()` would move with the bug the control exists to catch) |
| `check-checkers-are-wired.py` self-test control 7 | required a `probe-*` member in the container — the template ships no probes, so the control would have failed | asserts the container holds at least one member **not** named `check-*`, which is the property the old prefix filter would have broken, rather than one prefix's name. A `docs/reviews/` arm was added alongside the existing `scripts/` arm. |
| `check-checkers-are-wired.py` closing NOTE | quoted a denominator "86, 87, 89 and 90 across one day's commits" and a population "MEASURED AT ZERO" in another repo | rewritten to state the residual and the command, carrying no figure |
| `check-env-vars-are-declared.py`, `check-settings-are-read.py` `CONFIG` | `src/fast_mcp_jobvite/config.py` | `src/fast_mcp_template/config.py` (both are disabled; their rows say to repoint on rename) |
| `check-coverage-floors.py` `PACKAGE` | `src/fast_mcp_jobvite` | `src/fast_mcp_template` |
| `coverage-test-map.py` `--cov=` target | `src/fast_mcp_jobvite` | `src/fast_mcp_template` |
| `check-harness-anchors-controls.sh` mutation target | `src/fast_mcp_jobvite/audit.py` | `src/fast_mcp_template/audit.py`; its exemption row says to retarget it at a real module before wiring |
| `check_advisories.py` `TABLE_PATH` | `("tool", "fast-mcp-jobvite", "advisory-ignores")` | `("tool", "fast-mcp-template", …)`, matching the table in `pyproject.toml` |
| `check-harness-anchors.py` `--floor` | default `0` (already correct) | **left at 0 deliberately**, and its exemption row says so: an anchor floor carried from another project is a number that is wrong on arrival |
| `.file-type-allowlist` | `src/fast_mcp_jobvite/py.typed` | `src/fast_mcp_template/py.typed`, which now exists |
| `.pre-commit-config.yaml` | three hooks, one of them pointing at a `.secrets.baseline` describing another tree | the secrets hook is REMOVED with the reason and the regeneration command in a comment; file-types and shellcheck remain |
| `.gitignore` | prose citing another project's ADRs and incidents | rewritten; the same patterns, the same stated cost, no cross-references |
| `pyproject.toml` | Jobvite's 8 runtime dependencies, per-module coverage prose, W505 sweep history | `fastmcp`, `fastmcp-slim`, `pydantic-settings`; `fail_under = 80` labelled explicitly as **a starting floor, not a measurement** |

**Floors that were NOT changed, and why.** `ROW_FLOOR=4` in
`check-suite-floor-amputation.sh`, `ROW_FLOOR=15` in
`check-harness-anchors-controls.sh` and `ROW_FLOOR=25` in
`check-brief-report-refs-controls.sh` are each a count of **that script's own
control arms**. They are self-referential, still correct in the carried file, and
changing them would break the harness they belong to. All three are in disabled
scripts.

`check-suite-floor.sh` takes its floor as a command-line ARGUMENT, so there is
nothing hardcoded to zero.

---

## 5. Proof

### 5.1 Gate tier, GREEN on a fresh clone of an empty project

A fresh `git clone` into a temporary path, then the Gate tier's exact commands.
Results are in §5.4 of the run recorded below; every step exits 0.

| Step | Result |
|---|---|
| `uv sync --frozen` | ok, 93 packages |
| `uv lock --check` | ok |
| `uv run --frozen ruff check .` | All checks passed |
| `uv run --frozen ruff format --check .` | 6 files already formatted (was 37; the carried machinery is format-excluded — §8, defect 2) |
| `uv run --frozen mypy` | Success: no issues found in 40 source files |
| `uv run --frozen pytest --cov` | 5 passed, **0 skipped**, coverage 88.46% — now against the RATCHET in `docs/coverage-baseline.txt`, not `fail_under` (§8, defect 4) |
| `check-quickstart.py` | **no longer a Gate step.** Shipped disabled — §8, defect 3 |
| `check-design-freeze.py` | frozen blob == trunk blob |
| `check-adr-numbers.py` | 1 ADR, `0000-0000`, index agrees both ways |
| `check-obligations.py` | 5 mappings, 4 anchors verified, 1 ABSENT |
| `check-checkers-are-wired.py` | 52 members, 11 WIRED, 41 excused, **0 unexplained** (was 44/5/39 before §8) |
| `check-checkers-are-wired.py --self-test` | **53/53 controls passed, unchanged by §8** |
| `check-default-branch-controls.sh` | 7/7 arms |
| `check-design-freeze-controls.sh` | 6/6 arms |
| `check-ratchet-controls.sh` | 13/13 arms |
| `check-scripts-lib-survives-gitignore.sh` | 5/5 arms on scratch repos |
| actionlint 1.7.7, `SHELLCHECK_OPTS=--severity=warning` | exit 0, no findings |

**Re-measured on a fresh clone of the post-§8 branch: 17 of 17 steps exit 0.**

**Two things went red before they went green, and both were real:**

1. **The coverage floor.** `fail_under = 80` against the placeholder server gave
   65.38% — `__main__.py` is 0% because in real use it runs out of process. The
   fix is a test that drives `main()` with a stub, **not** a lowered floor: a
   floor weakened to fit the artefact is not a floor. 65.38% → 88.46%.
2. **`check-obligations.py` refused row B4.** Its subject was
   `cancel-in-progress`, which appears twice in `ci.yml` — once in the setting and
   once in the comment above it — and the checker refuses ambiguity rather than
   resolving it to the first hit. The subject now quotes enough of the line to be
   unique. The gate was doing exactly its job on its first run.

### 5.2 The registry balances

```
Container: tracked .py, .sh under docs/reviews/, scripts/
Members: 44
Run steps parsed from workflows/: 17
WIRED: 5
UNWIRED, with a stated reason: 39
Every checker is wired, or unwired for a recorded reason.
```

5 + 39 = 44, and `main()` asserts SET equality between the three buckets and the
enumerated container, not a count — so a member dropping out of every bucket is a
failure rather than a smaller, quieter, greener population.

### 5.3 Forbidden classes

Asserted by file count in §3. Every class is 0, except the four single files that
are deliberate shapes and are named there.

---

## 6. What I could not do as specified

**The deliverable asked for ONE commit. It is TWO, and the second is one line.**

`docs/DESIGN-FREEZE.txt` names the commit whose `docs/DESIGN.md` blob is
authoritative, and **no commit can contain its own SHA**. A one-commit template
could therefore only ship the freeze gate pointing at `HEAD`, where it compares a
blob to itself and asserts nothing — an inert gate, which is the thing this
template exists to avoid shipping.

Amending was measured and rejected: it leaves the named commit unreachable, and
`git clone` fetches only reachable objects, so a fresh clone would hit the
checker's "THE FROZEN SHA IS NOT IN THIS CLONE" branch and exit 3 as a broken
instrument. The second commit is the only form in which this gate is real.

`docs/adr/0000-template.md` is numbered, and that is deliberate: the ADR filename
pattern is `NNNN-slug.md`, so an unnumbered `template.md` would leave the
population empty and `check-adr-numbers.py` prints "MATCHED ZERO ADRs. The
selector is broken" and exits 1. **The template ships zero DECISIONS**; it ships
one numbered shape so the gate has a real population to check rather than a green
over nothing. Your first real decision is `0001`.

---

## 7. Residual risks, stated rather than discovered

- **The Assurance tier has no harness to run.** Its one live step prints that the
  tier was reached, which proves the schedule/dispatch path fires and nothing
  else. Delete that step when you add a real harness — two of them is one that
  nobody reads.
- **`docs/research/FASTMCP.md` is dated third-party research.** It is carried
  because it transfers; it is not carried because it was re-verified.
- **The carried checkers' docstrings still argue from measurements taken in
  another repository.** Those arguments are why the files are worth having, and
  the figures in them are labelled as past measurements — but a reader should
  treat every number inside a carried checker's prose as historical, not as a
  claim about this project.
  **REFUTED, and it was the loudest risk on this list.** Applied to a real
  repository, the 39 disabled checkers' Jobvite-derived docstrings caused *zero*
  confusion — read in situ they parse as arguments, not as claims. Recorded
  because a risk that was predicted and did not materialise is worth as much as
  one that did.
- **`fetch-depth: 0`** is required on any job running `check-design-freeze.py`.
  A depth-1 checkout makes it exit 3 with a message that says so, but the message
  is easy to misread as evidence the design moved.
  **PARTLY CLOSED.** The exit-3 case is now discriminated from the far commoner
  one — a child repository carrying the template's own freeze SHA — which exits
  **2** with "not frozen yet, run `scripts/refreeze.sh`". `fetch-depth: 0`
  remains required and the shallow message is unchanged (§8, defect 5).

**THE OTHER PHASE 4 RISK ALSO REFUTED:** not one of the neutralised floors or
anchors in §4 fired a false red on a foreign repository. `_project_name()` read
the host's name out of its `pyproject.toml` correctly; the `PACKAGE`/`CONFIG`/
`TABLE_PATH` renames were mechanical. **Both of the two loudest predictions in
this document were wrong, in the safe direction.** The eight things that did go
wrong are in §8, and none of them appears anywhere above.

---

## 8. What one real repository found, and the eight fixes

**Subject:** `jeremy-newhouse/fast-mcp-jira` at `522f91b`, cloned read-only.
**Full measurement:** `reports/REPORT-accelerator-validation.md` in the evolv
master folder (it lived at that folder's root until the 2026-09-08 reorganisation).
**Re-runnable:** `reapply.sh` re-applies the FIXED template to a fresh clone and
prints the Gate tier with real exit codes. It was archived, with the two scratch
clones it drives, at `~/backups/phase5-jira-proof-2026-09-08/` when the Phase 5
workspace was deleted on 2026-09-08 (restore the bundles with `--mirror`).

**Before: 5 of 11 Gate steps green. After: 11 of 12.**

The step SET is not identical, so this is not a step-for-step comparison and
should not be read as one: `check-quickstart` was removed, and three gates were
added. What is comparable is that **every red that was a defect in the template
is now green, and the one that remains is not a template defect.**

### 8.1 The eight, and what closed each

| # | Defect | Fix | What the controls caught |
|---|---|---|---|
| 1 | `ci.yml` hardcoded `main` at **four functional sites**; the subject's trunk is `dev`, so Gate, CodeQL and actionlint were **silently off** — grey, not red | Three sites derive from `github.event.repository.default_branch`. The fourth, `on: push: branches:`, is static YAML and cannot; it ships `[main, master, dev]` **and** a gate fails loudly on a trunk it does not list | A2 is the decisive arm: the **pre-fix** workflow against `default=dev`. Without it the suite proves only that the new code likes itself |
| 2 | `ruff format --check .` **unsatisfiable at any width** | The carried machinery is excluded from FORMAT only. Lint still covers it — `E501` can only be *satisfied* by widening, never introduced by it, so the two are not symmetric | Re-measured at a **third** width (120 → 27 machinery files), closing the original report's open question. The two arms stay two arms, and it gets worse |
| 3 | `check-quickstart.py` cannot load a normally-structured package | Shipped DISABLED with its turn-on condition. Separately, `MUST_NOT_PRINT` is now tested **before** `MUST_PRINT`, so an exit-0-with-`ERROR` reports the error rather than a missing needle | — |
| 4 | `fail_under = 80` is a **floor**; the subject measures 7.45% | `fail_under` deleted; a ratchet against `docs/coverage-baseline.txt`, measured on adoption | An arm at the subject's own 7.45% proves the gate **still bites** there. "Usable on any repo" must not mean "inert on a bad one" |
| 5 | `DESIGN-FREEZE.txt` made every child open with "BROKEN INSTRUMENT, exit 3" | Exit 2 = *not frozen yet*, discriminated by `--is-shallow-repository`. Plus `scripts/refreeze.sh` | **A1 refused my first fix.** It grepped stderr for `invalid object name`; git says something else entirely here, so the fix fell through to exit 3 and rebuilt the defect one column over. It asks `git cat-file -e` now |
| 6 | `.gitignore` had never met `lib/` | `!scripts/lib/` appended, **at the end** | **A3 refused my first placement.** Git takes the *last* matching pattern, so the negation written above `lib/` — the obvious place — does nothing. A1 reproduces the defect at 0 of 3 tracked; A2 fixes it at 3 |
| 7 | The `[tool.*]` blocks are a **replacement** presented as a rename | A "keep these" list beside the "rename these" list | **Found by re-running: it is THREE channels, not one.** See §8.2 |
| 8 | `OBLIGATIONS.md` makes the template's style values load-bearing silently | All five rows marked PLACEHOLDER, with a table pairing each guarded value to its row | Writing it **broke B3**: a new comment repeated `strict = true` and made the anchor ambiguous. The register refused it, so the comment was rewritten rather than the anchor |

### 8.2 Defect 7 was bigger than the original report found

The report named `asyncio_mode` and `pytest-asyncio`. Re-running the adoption
showed **three independent channels**, and fixing only the first still left the
suite dead:

1. **`asyncio_mode`** — a dropped pytest key. A *warning*.
2. **`markers = [...]`** — replacing the host's list while `addopts` carries
   `--strict-markers` turns an unlisted marker into a **collection ERROR**, not
   a warning. The subject died at `'asyncio' not found in markers configuration
   option`, which survives fixing (1).
3. **`[dependency-groups]` vs `[project.optional-dependencies]`** — the template
   declares dev tools where `uv sync` installs them; a host declaring them the
   other way has them silently absent. That is how `pytest-asyncio` went missing
   while the host's own `pyproject.toml` still named it.

**With all three kept, the subject's suite runs 26 passed — exactly its
pre-template baseline.** The cheapest check that a merge landed is to compare
the PASSED count before and after; a collection error is not a smaller number,
it is no number at all.

### 8.3 Three numbers reproduced independently

The re-application re-derives the original report's three headline figures from
scratch, on a fresh clone, through different code:

| Figure | Original report | Re-derived |
|---|---|---|
| Subject coverage | 7.45% | **7.45%** (2,829 statements) |
| mypy `--strict` errors | 158 in 20 files | **158**, across 34 (file, code) pairs |
| Suite | 26 passed, 0 skipped | **26 passed** |

### 8.4 The one remaining red, and it is not ours to close

`ruff check .` exits 1 with **197 findings**, all but one in `src/`. Derived
with `ruff check . --output-format concise | grep -oE '\b[A-Z]+[0-9]+\b' |
sort | uniq -c | sort -rn`:

- **131 W505** — `max-doc-length = 72`, a template doc-width policy the host
  never opted into. It is anchored by `OBLIGATIONS.md` row B2, which now says in
  as many words that it is a placeholder to replace. **A per-project decision the
  template documents and does not make.**
- **48** annotation and docstring findings (ANN401 21, ANN204 14, D107 8, D301 4,
  D104 1) — style policy, a day's work or a ratchet.
- **18 substantive findings in the host's own code** (B904 ×9 losing exception
  causes, S110 ×2 silent `except: pass`, DTZ005, B905, and five deprecated
  imports) that its own `select = ["E","F","I","W"]` could never surface.

**Those 18 are the template earning its money**, and they are the reason this
red should stay red. 131 + 48 + 18 = 197.

### 8.5 What is still not settled

- **None of this has run on GitHub Actions.** Every number here is local. The
  Gate tier's wall-time target is untested against a real repository, and the
  branch-derivation expressions in `ci.yml` are validated by actionlint and by
  reading, not by a live run.
- **How many of the other eight repos default to `dev`** is unknown. Defect 1's
  blast radius is therefore unquantified — but it is now loud rather than silent
  on every one of them, which was the point.
- **Whether `ruff format`'s two arms stay two arms below 88.** Three points were
  measured (88, 100, 120) and the mechanism predicts monotonicity upward only.
- **The subject is on `fastmcp` 3.x and the template pins a 4.x release** (`4.0.0b4`
  when this was written; `4.0.3`, the GA line, since 2026-09-08). Untouched,
  because closing it means editing someone else's dependency graph.
