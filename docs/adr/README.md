# Architecture Decision Records

**This template ships ZERO decisions.** The only file here is
[`0000-template.md`](0000-template.md), which is the shape, numbered so that
`check-adr-numbers.py` has a non-empty population to check rather than a green
over nothing. Your first real decision is `0001`.

## The rule that keeps the count down

> **An ADR records a decision that constrains future code. A measurement is not
> an ADR.**

Write a measurement down where it was made — in the worklog, the probe, or the
commit that used it — and cite it. A repository that files every measurement as
a decision record ends up with hundreds of immutable documents, thousands of
inbound citations pointing into them, and no way to renumber or condense any of
it. The cost of a large ADR set is not the count; it is that a reader must open
every file to learn what was decided. Which is what the index below is for.

## The two jobs an ADR does here

1. **`Deviation`** — records a decision that departs from a `priority: required`
   standard, or that a reviewer would otherwise be right to file as a defect.
   **Independent of the design freeze**: a deviation is recorded when it is
   decided, which is why ADRs can exist against a design that is not yet frozen.
2. **`Design change`** — after the freeze, an ADR is the **only** instrument that
   may change `docs/DESIGN.md`. This job begins at the freeze and not before.

**Every ADR carries a `Type:` field** — `Deviation`, `Design change`, or `Both`.
Once the convention exists, the ABSENCE of the field reads as "not a deviation"
rather than "written before the field did", so it is never optional.

Format: Status, Type, Context, Decision, Consequences. Every ADR cites the
clause it deviates from at its `file:line`, and says what evidence the decision
rests on.

**Citations inside an accepted ADR are AS AT its acceptance and are NOT
repointed.** An ADR is an immutable record of what was true when the decision
was made; silently updating its line numbers rewrites history to look correct.

## The index: every decision, one line, without opening a file

Each row states the **DECISION**, not the topic. Where a decision is qualified,
partial, or explicitly leaves something open, the row says so rather than
reading clean.

The number of ADRs is not written here as a literal. Derive it:

    ls docs/adr/0*.md | wc -l                  # the numbered files
    python3 docs/reviews/check-adr-numbers.py  # unique, contiguous, all listed

That checker refuses this table in **both directions** — a file with no row, and
a row with no file — so it cannot silently stop short.

| ADR | Type | Decision |
|---|---|---|
| [0000](0000-template.md) | - | Not a decision. The shape every ADR below copies. |
