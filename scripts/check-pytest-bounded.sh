#!/usr/bin/env bash
# Every pytest invocation in a tracked shell script must carry a `timeout`.
#
#   scripts/check-pytest-bounded.sh              # the gate
#   scripts/check-pytest-bounded.sh --self-test  # prove it can go red
#
# WHY THIS EXISTS, and why it enumerates rather than lists. Task #108 bounded
# "64 of 64" pytest calls, measured with `grep -nE 'uv run --frozen pytest'
# scripts/*.sh`. That selector was narrow in TWO ways at once and the real
# figure was 64 of 73:
#
#   - BY SPELLING. Four harnesses hold the interpreter in an array and run
#     `"${PY[@]}" -m pytest`, which the pattern cannot match.
#   - BY PATH. `scripts/*.sh` cannot see the seven tracked `.sh` files in
#     `docs/reviews/`, three of which called pytest unbounded.
#
# The nine it missed were found by enumerating the CONTAINER - `git ls-files`
# - and asserting bounded == total. That assertion is this script. A hand-kept
# list of paths, or a pattern for one spelling, is blind to the member nobody
# thought of; #108's own fix was written by someone who had just written that
# lesson down, which is why it is enforced here instead of remembered.
#
# ADR-0023 does NOT cover this file and it is not claimed to. That ADR scopes
# its `-e` deviation by PURPOSE - artefacts whose measurement is the exit code
# of a command EXPECTED to fail - and the harnesses it covers are measuring
# pytest. This script measures a grep over source text. So it takes the
# standard's own prescribed form: `set -euo pipefail`, with the commands that
# may legitimately return non-zero guarded explicitly. `grep` exits 1 when it
# matches nothing, and here that is the GOOD case.
set -euo pipefail

# THE ONE CANONICAL RESULT LINE (task #107). Sourced BEFORE the `cd` below,
# because `dirname "${BASH_SOURCE[0]}"` has to be read relative to how this
# script was invoked and not to a directory it has already moved to.
#
# THIS FILE IS A CHECKER, NOT A HARNESS, AND IT EMITS ANYWAY. #107 chose the
# glob `scripts/*.sh` as the population with no exceptions, because a partition
# into "harness" and "not a harness" is the same hand-kept list the canonical
# line exists to delete - one level up. This script is the first member to test
# that choice, and the choice holds: it counts something real, its exit code is
# a verdict, and both belong in the line.
# shellcheck source=lib/harness-result.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/harness-result.sh"

cd "$(dirname "$0")/.."

# Both spellings, comment lines excluded. Kept as one pattern so the two
# halves cannot drift apart into two lists that disagree.
PATTERN='(uv run --frozen|-m) pytest'

sites() {  # -> every non-comment pytest invocation, `path:line:text`
  local out=""
  local -a files=()
  # `git ls-files` is the authority. A new directory of scripts is covered
  # the day it lands, without anyone remembering to add it here.
  #
  # NUL-DELIMITED into an array rather than an unquoted `$(...)`. The bare
  # form is SC2046 and it is a real defect, not a style note: a tracked
  # path containing a space would split into two nonexistent paths, and
  # `grep` at a path that does not exist exits clean-empty - which this
  # script would then read as "nothing to check". Wrong in the reassuring
  # direction, which is the only direction that matters for a gate.
  mapfile -d '' files < <(git ls-files -z '*.sh')
  if [ "${#files[@]}" -eq 0 ]; then
    return 0
  fi
  # EXCLUDE THIS FILE. Its own source MUST contain the pattern - the
  # --self-test plants an unbounded call as a string literal, so the
  # scan matches the plant and reports the guard as a violation of
  # itself. That is the executable form of "a grep for a defect finds
  # the comment forbidding it", and it only appeared once this branch
  # met a gate written on another one.
  out=$(grep -nE "$PATTERN" "${files[@]}" | grep -vE ':[0-9]+: *#' \
        | grep -v '^scripts/check-pytest-bounded\.sh:') || true
  printf '%s' "$out"
}

if [ "${1:-}" = "--self-test" ]; then
  # A POSITIVE CONTROL. A gate that has never been seen red is a gate whose
  # green means nothing - this one's whole job is to notice an unbounded
  # call, so it must be watched noticing one.
  work=$(mktemp -d)
  trap 'harness_result_emit; rm -rf "$work"' EXIT
  printf '#!/usr/bin/env bash\nuv run --frozen pytest -q\n' > "$work/unbounded.sh"
  found=$(grep -cnE "$PATTERN" "$work/unbounded.sh") || found=0
  bounded=$(grep -nE "$PATTERN" "$work/unbounded.sh" | grep -c 'timeout ') || bounded=0
  echo "SELF-TEST: a planted unbounded call -> total=$found bounded=$bounded"
  if [ "$found" -eq 1 ] && [ "$bounded" -eq 0 ]; then
    echo "SELF-TEST PASSED: the selector sees the call and judges it unbounded."
    exit 0
  fi
  echo "SELF-TEST FAILED: the selector cannot see its own planted call."
  exit 1
fi

all=$(sites)
if [ -z "$all" ]; then
  # An empty population reports perfect compliance. Refuse it: a broken
  # selector and a fully-bounded tree print the same clean zero otherwise.
  echo "MATCHED ZERO pytest invocations. The selector is broken; a green"
  echo "here would mean nothing."
  exit 2
fi

total=$(printf '%s\n' "$all" | wc -l)
unbounded=$(printf '%s\n' "$all" | grep -v 'timeout ') || true
count=0
[ -n "$unbounded" ] && count=$(printf '%s\n' "$unbounded" | wc -l)

# THE CANONICAL RESULT LINE'S NUMBERS (task #107), from this script's own
# counters and never a second copy.
#
# `rows` is the number of pytest invocation sites the selector actually saw -
# the population this run examined, which is exactly what `rows` means
# everywhere else.
#
# `floor` IS ZERO, AND DELIBERATELY NOT `$total`. This check's pass condition is
# an EQUALITY - every site bounded, `count == 0` - not a minimum. Reporting
# `floor=$total` would render an equality as a tight floor, and a reader
# comparing `rows` against `floor` would draw a conclusion this script never
# made. Zero is what #107 documents for a script with no floor: it is not a
# floor anything can breach, and it reads as absent.
#
# The three statuses fall out of the exit codes already here, without a branch:
#   exit 0  every site bounded                  -> ok
#   exit 1  unbounded site(s) found             -> breach
#   exit 2  the selector matched NOTHING        -> refused, and it never
#           reaches this line, so `refused` is the default rather than a
#           claim - which is right, because that run measured nothing.
#   --self-test also never reaches here, so a run that exercised the selector
#           instead of the repository reports `refused` too. That is the useful
#           answer: a CI step that accidentally ran --self-test would show
#           `status=refused`, not a green `ok` over a population of zero.
harness_result_ran "$total" 0

echo "pytest invocations in tracked .sh: $total"
echo "bounded by a timeout:              $((total - count))"

if [ "$count" -ne 0 ]; then
  echo
  echo "::error::$count pytest invocation(s) run unbounded. A hung suite"
  echo "         produces no result lines, so every assertion 'did not"
  echo "         survive' and the row reads as a pass."
  printf '%s\n' "$unbounded" | sed 's/^/  /'
  exit 1
fi

echo
echo "All $total bounded. NOTE: this proves a timeout is PRESENT, not that"
echo "its value is right, and not that the harness reads 124 as anything"
echo "other than a result."
