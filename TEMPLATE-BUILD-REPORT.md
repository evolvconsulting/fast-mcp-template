# Template build report

**Extracted from:** `fast-mcp-jobvite` at **`6827e9d`** (main) · **Built:** 2026-09-02

This file records what was carried, what was dropped, every hardcoded floor and
anchor that was neutralised, and the measured proof that the Gate tier is green
on an empty project. **Delete it once your project is real** — it is a record of
how the template was made, not a document about your project.

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

### 2.2 The five ENABLED gates

| Gate | What it asserts |
|---|---|
| `check-checkers-are-wired.py` (+ `--self-test`) | the registry above; 53/53 controls |
| `check-design-freeze.py` | `docs/DESIGN.md` at the SHA in `DESIGN-FREEZE.txt` is the same **blob** as on the trunk |
| `check-adr-numbers.py` | ADR numbers unique and contiguous, and `adr/README.md` lists every one — **checked in both directions** |
| `check-obligations.py` | every row in `OBLIGATIONS.md` resolves to a line containing its subject; zero rows is a FAILURE |
| `check-quickstart.py` | the commands in `README.md`'s Quickstart are parsed out of it and RUN |

Plus the ordinary tooling: `uv lock --check`, `ruff check`, `ruff format
--check`, `mypy --strict` (over `src`, `tests`, `docs/reviews`, `scripts`),
`pytest --cov` with a zero-skips guard, and actionlint on the Merge tier.

**Why five and not thirty-seven.** 68 checkers exist in the source; 31 are
unit-specific and encode that project's tool surface, so none of them transfers.
Of the 37 generic ones, enabling all of them here would hand every child
repository three dozen gates it has not earned. That is precisely how the source
repository reached its documentation ratio. The five above are the ones that hold
on a project with no code in it yet.

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
| `uv run --frozen ruff format --check .` | 37 files already formatted |
| `uv run --frozen mypy` | Success: no issues found in 37 source files |
| `uv run --frozen pytest --cov` | 5 passed, **0 skipped**, coverage 88.46% against `fail_under = 80` |
| `check-quickstart.py` | 3 commands parsed, 2 skipped with stated reasons, 1 RUN and asserted |
| `check-design-freeze.py` | frozen blob == trunk blob |
| `check-adr-numbers.py` | 1 ADR, `0000-0000`, index agrees both ways |
| `check-obligations.py` | 5 mappings, 4 anchors verified, 1 ABSENT |
| `check-checkers-are-wired.py` | 44 members, 5 WIRED, 39 excused, **0 unexplained** |
| `check-checkers-are-wired.py --self-test` | **53/53 controls passed** |
| actionlint 1.7.7, `SHELLCHECK_OPTS=--severity=warning` | exit 0, no findings |

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
- **`fetch-depth: 0`** is required on any job running `check-design-freeze.py`.
  A depth-1 checkout makes it exit 3 with a message that says so, but the message
  is easy to misread as evidence the design moved.
