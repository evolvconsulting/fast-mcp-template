# Contributing

## Before you push

Run what CI runs, with CI's exact flags. A gate run without them is a
different, weaker question:

```bash
uv sync --frozen
uv lock --check
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy
uv run --frozen pytest --cov
uv run --frozen python docs/reviews/check-quickstart.py
uv run --frozen python docs/reviews/check-design-freeze.py
uv run --frozen python docs/reviews/check-adr-numbers.py
uv run --frozen python docs/reviews/check-obligations.py
uv run --frozen python docs/reviews/check-checkers-are-wired.py
uv run --frozen python docs/reviews/check-checkers-are-wired.py --self-test
```

## Rules

- **Never merge on red.** Triage a failure to real defect, harness defect or
  flake before doing anything else; "it's probably flaky" is a conclusion, not
  a starting assumption.
- **`docs/DESIGN.md` is frozen.** Only a numbered ADR may change it, and the
  ADR and the edit land in the same commit as an advance of
  `docs/DESIGN-FREEZE.txt`.
- **Turning a gate on is two edits in one commit:** wire the step in `ci.yml`,
  and delete its row from `UNWIRED_BY_DECISION`. Either alone fails the build,
  which is the point.
- **Measure a gate green before wiring it.** A gate that lands red is one
  people learn to ignore.
- **History is not rewritten on `main`.** Force-push, when unavoidable on a
  branch, is `--force-with-lease` and never bare `--force`.
- **No `Co-Authored-By` or generated-by trailers.**

## Commit messages

State what changed and what it is now true of, in the imperative. If a number
appears, say how it was derived or at which SHA it was measured.
