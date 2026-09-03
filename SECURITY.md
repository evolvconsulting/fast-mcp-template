# Security

## Reporting

Report a suspected vulnerability privately to evolv Consulting rather than in a
public issue. Include what you observed, how to reproduce it, and the commit
you observed it at. Expect an acknowledgement within a few working days.

## What this project does about it

- **Credentials never reach a caller, a log or a test failure.** Redaction is
  asserted by a test, not assumed from a helper's existence.
- **Dependencies are pinned and locked.** `uv lock --check` runs in the Gate
  tier, so an unfrozen resolve cannot slip in.
- **CodeQL runs on the Merge tier.** Weekly-class defects do not need to run on
  every push, but they do need to run.
- **`scripts/check_advisories.py` is carried, disabled.** Wire it together with
  a `pip-audit` step: an advisory-ignore mechanism with no audit behind it is a
  flag generator connected to nothing. An ignore entry is legal only for an
  advisory this code cannot reach, and only with an id, a date, a written
  unreachability reason, and an expiry no more than 30 days out. Never a
  blanket ignore, never a raised threshold.
- **Secrets scanning runs at commit time** via `.pre-commit-config.yaml`.
  Regenerate `.secrets.baseline` for this project before relying on it; the
  carried baseline describes a different tree.
