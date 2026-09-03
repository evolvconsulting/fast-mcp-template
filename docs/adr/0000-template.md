# ADR-0000: the shape of an ADR

**Status:** Template · **Type:** - · **Date:** -

> Copy this file to `0001-<short-slug>.md`, set the heading to `# ADR-0001: ...`,
> and add a row to `README.md`'s index **in the same commit** — the checker
> refuses the table in both directions, so a file without a row is a red build.
>
> **Before you write one, check it is a decision.** An ADR records a decision
> that constrains future code. A measurement is not an ADR.

**Status** is one of `Proposed`, `Accepted`, `Rejected`, `Superseded by ADR-NNNN`.
**Type** is one of `Deviation`, `Design change`, `Both`.

## Context

What forced the decision. Name the clause being deviated from at its
`file:line`, or the design section being changed at its `§n`. State what was
measured, with the command, and what was merely reasoned about — those are
different kinds of evidence and a reader has to be able to tell them apart.

## Decision

One paragraph, in the imperative. What we will do.

## Consequences

What this costs, what it forecloses, and what now has to be true for it to keep
holding. Include the consequences you dislike; an ADR listing only benefits is
a sales document.

## Evidence

Commands and their output, or a path to the artefact that holds them. A figure
copied out of a program is a cache — say when it was measured and at which SHA,
or give the command so the next reader can re-derive it.
