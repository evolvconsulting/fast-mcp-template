#!/usr/bin/env bash
# Assert a pytest run selected at least FLOOR tests.
#
#   check-suite-floor.sh <floor> <<< "$pytest_output"
#
# WHY THIS EXISTS. `ci.yml` guarded the suite with `grep -qE '[1-9][0-9]* passed'`,
# which is satisfied by "1 passed". Three hundred tests could be deleted, renamed
# out of collection, or silently deselected by an addopts edit and the step would
# stay green - the guard proves the selection was non-empty, never that it was
# whole. Nothing else in the pipeline floors the count either: coverage is a
# ratio, so removing a test and the code it covered can raise it.
#
# This is a RATCHET. The floor lives in `ci.yml` next to the step it guards.
# Raising it when tests are added is routine; LOWERING it is a visible diff that
# has to be defended in review, which is the whole mechanism.
#
# It deliberately does NOT parse "failed" or "error" - the exit code already
# covers those, and a guard that re-checks what the exit code saw would give the
# false impression this step is a second opinion on failure. It is not. It is a
# guard against a run that passed everything it was given, having been given too
# little.
set -uo pipefail

# THE ONE CANONICAL RESULT LINE (task #107). This arms an EXIT trap that prints
# `HARNESS-RESULT name=... rows=... floor=... status=refused` on ANY exit, so an
# abort cannot render identically to a pass. `harness_result_ran` below upgrades
# it to ok/breach from the real exit code. The format lives in the sourced file
# and nowhere else - the shape lists it replaces are why.
# shellcheck source=lib/harness-result.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/harness-result.sh"

floor="${1:-}"
case "$floor" in
  '' | *[!0-9]*)
    echo "usage: check-suite-floor.sh <floor>  (a non-negative integer)" >&2
    exit 2
    ;;
esac

out=$(cat)
printf '%s\n' "$out"

# The summary line is the LAST "N passed" in the output: pytest prints it at the
# end, and a test's own captured stdout can contain the same words earlier. `tail
# -1` is load-bearing, not defensive.
passed=$(printf '%s\n' "$out" | grep -oE '[0-9]+ passed' | tail -1 | cut -d' ' -f1)

if [ -z "$passed" ]; then
  echo "::error::no passed-count in the output. The run did not reach a summary line," >&2
  echo "         so this guard cannot tell a healthy suite from an empty one." >&2
  exit 1
fi

# The canonical result line's numbers, taken from the harness's own
# counter and its own floor - never a second copy. Called BEFORE the
# comparison below, because that branch exits.
harness_result_ran "$passed" "$floor"
if [ "$passed" -lt "$floor" ]; then
  echo "::error::$passed passed, but the floor is $floor." >&2
  echo "         Tests were removed, renamed out of collection, or deselected." >&2
  echo "         If the removal is intended, lower the floor in ci.yml in the same" >&2
  echo "         commit and say why in the message." >&2
  exit 1
fi

echo "suite floor OK: $passed passed, floor $floor"
