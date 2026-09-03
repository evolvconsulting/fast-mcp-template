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

1. `git clone`, then `rm -rf .git && git init` — a template must not carry
   history into its children.
2. Rename in this order, because later steps depend on earlier ones:
   `src/fast_mcp_template/` → your package; `pyproject.toml`'s `name`,
   `[project.scripts]`, `[tool.hatch...]`, `[tool.coverage.run] source`,
   `[tool.<name>.advisory-ignores]`; `FastMCP("...")` in `server.py`; the
   `env_prefix` in `config.py`; this README's Quickstart and title.
   Then `uv lock && uv sync`.
3. **Delete first:** `ping` and its tests, `docs/research/FASTMCP.md` once you
   have read it, and every `TODO` in the document shapes.
4. Write `docs/DESIGN.md`, then freeze it: put the commit SHA that carries it
   into `docs/DESIGN-FREEZE.txt`. Until you do, the freeze gate is comparing
   the placeholder against itself, which is true and worth nothing.
5. Fill `docs/OBLIGATIONS.md` with the standards clauses you actually owe.

## The three CI tiers

| Tier | Trigger | Target |
|---|---|---|
| **Gate** | every push and PR | under 3 min |
| **Merge** | push to `main` | under 6 min |
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
| `check-quickstart.py` | the commands in this README's Quickstart are **parsed out of it and run** |

Plus the ordinary tooling: `ruff check`, `ruff format --check`, `mypy --strict`,
`pytest --cov`, `uv lock --check`, and actionlint on the workflows.

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
src/fast_mcp_template/     DELETE the placeholder server and write yours
```

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`.
