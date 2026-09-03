# DESIGN — TODO: name the server

**Status:** placeholder · **Revision:** 0

> **THIS IS A SHAPE, NOT A DESIGN.** Replace every section below. Then put the
> commit SHA that carries your version into `docs/DESIGN-FREEZE.txt`, and from
> that moment only a numbered ADR may change this file.
>
> The headings are here because they are the questions that turned out to
> matter, in the order they turned out to matter. Deleting a section is a
> decision; leaving it as TODO is not.

---

## 1. What this server is for

TODO. One paragraph. Who calls it, and to do what.

## 2. Tool surface

TODO. One row per tool: name, arguments, what it returns, and whether it
writes. A tool that writes is a different risk class from one that reads, and
the split belongs here rather than in the code.

| Tool | Reads or writes | Arguments | Returns |
|---|---|---|---|
| TODO | read | TODO | TODO |

## 3. Module layout

TODO. Which module owns which concern, and which may import which. The
carried `check-coupling.py` (disabled) enforces a stated layering against this
section — turn it on once this section says something.

## 4. The upstream client

TODO. Base URL, auth mechanism, pagination, rate limits, and what the client
does on each failure class.

## 5. Error contract

TODO. Every error a caller can see, and what it is allowed to contain. State
explicitly what must NEVER reach a caller: credentials, upstream exception
text, internal paths.

## 6. Configuration

TODO. Every environment variable, its default, and whether it is a secret.
`config.py`'s `env_prefix` is the one place the namespace is spelled out.

## 7. Testing strategy

TODO. In particular: which arms are excluded from the default suite and by
what mechanism. **Deselect by marker, never `skipif`** — a skip is a green
that tested nothing, and the Gate tier is written to refuse skips.

## 8. Threat model

TODO. One row per threat, its mitigation, and where the mitigation lives.

## 9. Observability

TODO. What is logged, at what level, and what is redacted before it is.

## 10. CI

The three tiers are in `.github/workflows/ci.yml` and described in `README.md`.
State here which gates this project has EARNED and turned on, and why — a
sentence saying "CI runs X" is a specification until a step exists, and this
section is where that difference gets noticed.

## 11. Deviations

Recorded as numbered ADRs under `docs/adr/`, never here.
