# Code review checklist

A review round is a pass by a **fresh** reviewer over a named commit range. The
range and the reviewer both go in the report; a review with no stated range
cannot be repeated and cannot be shown to be incomplete.

## Before the round

- [ ] Name the range: `git log --oneline <base>..<head>`. `A..B` is not two
      ancestor tests — state which commits are actually in it.
- [ ] Read `docs/DESIGN.md` at the frozen SHA, not at HEAD.
- [ ] Note which gates were GREEN on this range, and which never ran.

## The pass

- [ ] **Silence, not incorrectness.** In a tested codebase the surviving bugs
      are the ones that fail quietly: a swallowed exception, an `except` that
      returns a default, a guard that prints instead of exiting.
- [ ] **Fail-closed on error is not fail-closed on empty.** Check both.
- [ ] Every new test's BODY, not its name. A test name is an unverified claim.
- [ ] Every new gate: can it fail? Plant the defect it exists to catch and watch
      it fire. A gate never seen red is a gate nobody has tested.
- [ ] Every count, floor and anchor in prose: re-derive it.
- [ ] Every citation `file:line`: open it and check the line contains the
      subject. A citation that resolves to real prose that is not its subject is
      the dominant failure mode here.
- [ ] Error paths: does anything reach a caller that should not — credentials,
      upstream exception text, internal paths?
- [ ] Fix one instance, then check its siblings. A sweep is not done until the
      SELECTOR is right, not until the named instance is fixed.

## The report

- [ ] Findings ranked by severity, each with `file:line` evidence and **a
      suggested fix**. A finding with no proposed remedy is an observation.
- [ ] A finding you could not confirm is reported as unconfirmed, with what you
      tried.
- [ ] State plainly what you did NOT look at.
- [ ] A TRUE zero is `0 Critical / 0 High / 0 Medium` after at least two
      independent passes. One pass finding nothing is one pass.

## After

- [ ] Every finding becomes a tracked item or is ruled, in writing, with a
      reason. Findings left in chat are findings lost.
- [ ] A fix gets a **new** reviewer, not the one who found it.
