# fast-mcp-template

A starting point for an MCP server: the CI tiering, the gate machinery, and the
document shapes, with **none** of any previous project's content.

It ships a working placeholder server (`ping`) so a fresh clone is green before
you write anything. Delete it in your first commit.

---

## Quickstart

```bash
git clone https://github.com/evolvconsulting/fast-mcp-template.git
uv sync --frozen
uv run --frozen fastmcp inspect src/fast_mcp_template/server.py:mcp
```

## Start a project from this

**Greenfield takes under an hour. Adopting an EXISTING repository does not** —
budget 1–2 days for the machinery and the documents, and read
[the migration note](#adopting-an-existing-repository) first. Every step
below that is marked **MEASURED** exists because it was skipped once, on a
real repository, on 2026-09-03, and the failure was silent.

1. `git clone`, then `rm -rf .git && git init` — a template must not carry
   history into its children.
2. **MEASURED — do this before anything else: put your default branch in
   `on: push: branches:` in `.github/workflows/ci.yml`.** That key is static
   YAML and is the only branch name in the file that cannot derive itself;
   everything else now reads
   `github.event.repository.default_branch`. It ships `[main, master, dev]`.
   On a repo whose trunk is none of those, Gate, CodeQL and actionlint are
   all **silently off** — the jobs are absent, and absent renders grey, not
   red. `check-default-branch-is-triggered.py` runs in Gate and will fail
   loudly if you skip this, which is the only reason it is safe to write
   down rather than engineer away.
3. Rename in this order, because later steps depend on earlier ones:
   `src/fast_mcp_template/` → your package; `pyproject.toml`'s `name`,
   `[project.scripts]`, `[tool.hatch...]`, `[tool.coverage.run] source`,
   `[tool.<name>.advisory-ignores]`; `FastMCP("...")` in `server.py`; the
   `env_prefix` in `config.py`; this README's title.
   Then `uv lock && uv sync`.
4. **Record the two baselines.** Neither is defaulted, and neither can be
   guessed:

   ```bash
   uv run --frozen pytest --cov --cov-report=json:coverage.json
   uv run --frozen python docs/reviews/check-coverage-ratchet.py --record
   uv run --frozen python docs/reviews/check-mypy-ratchet.py --record
   git add docs/coverage-baseline.txt docs/mypy-baseline.txt
   ```

5. **Delete first:** `ping` and its tests, `docs/research/FASTMCP.md` once you
   have read it, and every `TODO` in the document shapes.
6. Write `docs/DESIGN.md`, commit it, then freeze it:

   ```bash
   bash scripts/refreeze.sh && git add docs/DESIGN-FREEZE.txt && git commit
   ```

   It is **two commits** because no commit can contain its own SHA. Until you
   do this the freeze gate exits 2 — a task, not a failure — and says so.
7. Fill `docs/OBLIGATIONS.md` with the standards clauses you actually owe.
   **All five rows it ships are placeholders anchored on the template's own
   config values**, so until you replace them a green there says nothing
   about your project. And note the coupling that file now spells out:
   **changing `line-length` means editing row B1 in the same commit**, or the
   build goes red naming it.

## Adopting an existing repository

The template was applied to a real MCP server on 2026-09-03 and **green was
not reached**. Eight defects came out of that; these are what is left for
you after they were fixed.

**`pyproject.toml`'s `[tool.*]` blocks are a REPLACEMENT, not a rename.**
Keep every key your project already relies on before you paste them over —
`asyncio_mode` cost the subject all 26 of its tests, erroring at collection,
with nothing warning it. The block itself carries the full note.

**KEEP THESE, whatever the template says.** The rename list above tells you
what to change; nothing told you what not to lose, which is how the subject
lost its whole suite. Before pasting any `[tool.*]` block, copy out of your
existing one:

| key | why losing it hurts |
|---|---|
| `[tool.pytest.ini_options] asyncio_mode` | every async test errors at collection, and pytest reports it as an error rather than a failure |
| `[tool.pytest.ini_options] testpaths` | the template's value points at *its* layout; yours may collect nothing, which reads as a pass |
| `[tool.pytest.ini_options] markers` | unregistered markers become warnings, and `filterwarnings = error` turns them into failures |
| `[tool.coverage.run] source` / `omit` | the wrong `source` measures the wrong tree and reports a number that means nothing |
| `[tool.ruff] line-length` | see the next paragraph — this one decides whether a gate is satisfiable at all |
| `[tool.mypy] files` / any `overrides` | narrowing `files` silently un-checks whatever you drop |

The rule behind the table: **a key whose absence changes what gets COLLECTED
or MEASURED is not a style choice.** Losing it does not go red; it goes quiet.

**`ruff format --check .` will be red on your first run, and the fix is one
command.** The Gate runs it (`ci.yml:120`) and the template's carried
machinery — every checker and probe under `docs/reviews/` and `scripts/` — is
formatted at `line-length = 88`. If your project uses any other width, that
machinery is unformatted *by your rules* and the gate is unsatisfiable until
somebody reformats it. Measured on the subject at both 88 and 100: red at
each, for opposite reasons, because a line split to fit a narrower limit gets
re-joined at a wider one.

So set your width first, then reformat everything you inherited, in the
adoption commit:

```bash
# after editing [tool.ruff] line-length to your project's value
uv run --frozen ruff format .
git add -A && git commit -m "chore: reformat carried machinery at our width"
```

Do this BEFORE you push, or the first CI run is red for a reason that has
nothing to do with your code. It is a one-time cost: once the machinery is at
your width, the gate stays satisfiable.

**`.gitignore`: two lines.** Delete any `uv.lock` entry — the Gate runs
`uv sync --frozen` and `uv lock --check`, which need it tracked. And if your
`.gitignore` has a stock Python `lib/` line, the `!scripts/lib/` re-inclusion
this template ships must end up **after** it; git takes the last matching
pattern. `scripts/check-scripts-lib-survives-gitignore.sh` proves both.

**The policy tier arrives as ratchets, not floors.** `fail_under = 80` and a
bare `--strict` gate are red by construction on any repository with history —
the subject measured 7.45% coverage and 158 mypy errors. Both are now
baselines you record on day one and may not regress. That is the difference
between a gate that works from day one at 7% and one that gets switched off.

**Expect real findings, and they are the point.** Ruff's wider selection
surfaced 18 substantive issues in the subject's code that its own
`select = ["E","F","I","W"]` could never see — missing `raise ... from`,
silent `except: pass`, naive `datetime.now()`, `zip()` without `strict=`.

## The three CI tiers

| Tier | Trigger | Target |
|---|---|---|
| **Gate** | every push and PR | under 3 min |
| **Merge** | push to the default branch | under 6 min |
| **Assurance** | weekly cron, manual dispatch, or a push touching code | 60-70 min |

`concurrency: cancel-in-progress` is set on Gate and Merge and is the single
highest-value line in the workflow: without it a busy branch bills every
superseded run. `runs-on: ubuntu-latest` everywhere — a macOS runner bills at
10x, so a 93-second macOS job costs 20 minutes.

## What is actually enforced today

**Five gates are ENABLED.** They are the ones that hold on a project with no
code in it yet:

| Gate | What it asserts |
|---|---|
| `check-checkers-are-wired.py` | every checker in the repo is wired into CI, or is excused **with a written reason**. This is the registry, and it is the mechanism that stops the rest of this list from rotting. |
| `check-design-freeze.py` | `docs/DESIGN.md` at the SHA in `DESIGN-FREEZE.txt` is the same **blob** as on the trunk |
| `check-adr-numbers.py` | ADR numbers are unique and contiguous, and `adr/README.md` lists every one |
| `check-obligations.py` | every row in `OBLIGATIONS.md` still resolves to a line containing its subject |
| `check-default-branch-is-triggered.py` | this repository's default branch is in the workflow's push trigger, and no `if:` names a trunk literally |
| `check-coverage-ratchet.py` | coverage has not fallen below `docs/coverage-baseline.txt` |
| `check-mypy-ratchet.py` | no mypy error that `docs/mypy-baseline.txt` does not already record |

Each of the last three ships with a controls script that plants the failure
and requires the checker to refuse it, and those controls run in Gate too — a
gate nobody has watched fail is a gate nobody has tested.

`check-quickstart.py` **ships DISABLED.** It hardcodes `fastmcp inspect`,
which takes a *file* and therefore cannot load a package using relative
imports — the Python norm. The template's placeholder passes it only because
that one file happens to use an absolute import, which made it a gate built
to pass its own check. Its `UNWIRED_BY_DECISION` row names the turn-on
condition.

Plus the ordinary tooling: `ruff check`, `ruff format --check`, `mypy --strict`,
`pytest --cov`, `uv lock --check`, and actionlint on the workflows.

**`ruff format --check` excludes `docs/reviews/` and `scripts/`.** Not
laziness: format-checking the carried machinery is unsatisfiable at any
width. Measured, same tree, one variable — at `line-length = 88` ruff wants
to rewrap 21 of a real subject's source files; at 100 it wants to rewrap 23
of the template's own checkers; at 120, 27. Widening re-joins lines that were
split for 88, so there is no width where both sides are green. Lint is
unaffected and still covers everything: `E501` can only be satisfied by
widening, never introduced by it.

**The other checkers under `docs/reviews/` and `scripts/` are carried but
DISABLED**, each with a one-line note in `UNWIRED_BY_DECISION` saying when to
turn it on. That is deliberate. A project that starts with three dozen gates it
has not earned spends its first month servicing them; the source repository this
came from reached 5.4x documentation-to-source that way. Turn a gate on when you
have the artefact it checks — and only after you have measured it green, because
a gate that lands red is one people learn to ignore.

To see the list and the reasons:

```bash
uv run --frozen python docs/reviews/check-checkers-are-wired.py
```

**Before you push, replay the Gate the way CI runs it.** Do not copy
lines out of `ci.yml` by hand; that copy drifts, and a gate run without
CI's flags is a weaker question (measured twice on this family). The
replayer parses the workflow and runs the Gate job's own `run:` steps
under the shell GitHub would use for each, one exit code per line,
refusing anything it cannot replay faithfully:

```bash
uv run --frozen python scripts/run-gate-locally.py
```

## ADRs

Ship **zero** numbered ADRs from here. `docs/adr/0000-template.md` is the shape.

> An ADR records a decision that constrains future code. **A measurement is not
> an ADR.** Write the measurement down where it was made and cite it.

## Layout

```
.github/workflows/ci.yml   the three tiers
docs/DESIGN.md             the authority, frozen by DESIGN-FREEZE.txt
docs/OBLIGATIONS.md        standards clause -> the artefact discharging it
docs/adr/                  decisions; 0000-template.md only
docs/briefs/PREAMBLE.md    the block every agent brief carries verbatim
docs/research/FASTMCP.md   FastMCP capabilities, carried from the first project
docs/reviews/              the checkers, 5 enabled and the rest disabled
scripts/                   harness machinery and the generic checkers
scripts/lib/               harness-result.sh, verdict-guard.sh, select-covering-tests.py
scripts/refreeze.sh        re-freeze DESIGN.md at the commit carrying it
src/fast_mcp_template/     DELETE the placeholder server and write yours
```

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`.
