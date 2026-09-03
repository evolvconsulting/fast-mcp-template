# shellcheck shell=bash
# THE ONE CANONICAL RESULT LINE. Task #107.
#
# WHY THIS FILE EXISTS. Every harness under `scripts/` reported its verdict in
# PROSE, and the checkers reading those verdicts carried a hand-kept list of the
# prose SHAPES they would accept. `docs/reviews/check-row-floor-controls.sh` held
# THREE breach-message literals in `floor_line()` plus a parallel display grep
# that had to be kept matching the same three; its own comment recorded that the
# list "HAS NOW MISSED ONE THREE TIMES", and #102 found a SIXTH tally shape
# elsewhere in the family. When the list and the reality drift the failure is
# SILENT: #102 watched "CONTROL FIRED" print above a BLANK evidence block,
# because the display grep matched a shape the assertion did not.
#
# That is this project's most-repeated defect - a hand-kept list of the forms to
# accept is blind to the form nobody added - and the durable fix is not a fourth
# literal. It is for every harness to print ONE line in a format that appears in
# exactly one place: here.
#
#   HARNESS-RESULT name=<basename> rows=<n> floor=<n> [<tally>] status=<ok|breach|refused>
#
# THE HUMAN PROSE STAYS. This is an addition, not a replacement: a person reading
# a CI log needs the sentence, and a checker needs the line. Neither is the other.
#
# WHY THERE IS NO GENERIC `fired=` FIELD, AND WHY THE TALLY IS NAMED INSTEAD.
# The first draft of this grammar had a single `fired=`. Across this family the
# tally has FOUR incompatible meanings - `N/M controls fired.`, `RESULT: N
# killed, M not killed`, `ROWS: N   ANCHORS APPLIED: M`, and for the amputation
# harnesses an INVERTED pass condition where survivors are the OUTPUT rather
# than a failure (which is why `ci-harness-gate.sh` has an `--amputation` flag at
# all). `ci-harness-gate.sh` states the reason itself, about the very phrases
# such a field would absorb: "each is printed beside a different diagnosis, and
# collapsing them would send the next reader to the wrong place." A field
# carrying four meanings lies more loudly than an absent one. That judgement
# stands and this file still refuses the generic field.
#
# WHAT #120 ADDED IS ONE NAME PER MEANING, not one field over four: `fired=N/M`,
# `killed=N/M`, `applied=N/M`. A harness publishes AT MOST ONE of them,
# `harness_result_tally` refuses any other name, and `ci-harness-gate.sh` selects
# the field ITS flag names and prints a message written for that field alone. The
# three are not interchangeable and nothing here may read one for another.
#
# THE AMPUTATION INVERSION DELIBERATELY HAS NO FIELD. It is not a tally at all -
# it is a reading of the exit code, and `--amputation` is where it lives. A
# fourth field would be the collapse arriving by the back door.
#
# WHY THIS IS NOT JUST `status` READ TWICE. Every one of the 26 harnesses that
# prints a tally also gates on that tally and exits non-zero when it is short
# (measured 2026-09-01, #120), so `status=ok` already implies a complete tally.
# Deriving the gate's tally check from `status` would therefore agree with it on
# every run and prove nothing - and it would make the check a restatement of the
# exit code, which is precisely what the C8 amputation in
# `docs/reviews/check-harness-result-controls.sh` exists to forbid. The field is
# reported from the harness's OWN counters, so DELETING a harness's internal
# comparison leaves the field short and the gate still fails. That independence
# is the whole reason the field is worth its bytes.
#
# WHY EVERY SCRIPT AND NOT "EVERY HARNESS". The population is the glob
# `scripts/*.sh`, with no exceptions, including `ci-harness-gate.sh` which is a
# gate rather than a harness. A partition into "harnesses" and "not harnesses"
# would be a hand-kept list one level up from the one this file deletes. The
# `name=` field is what disambiguates: a gate echoes the output of the harness it
# ran, so two HARNESS-RESULT lines appear, and they differ by `name=`. A checker
# selects on `name=` and is never ambiguous.

# `set -u` is on in every caller, so every variable is initialised here at source
# time and none is left to a code path that may not run.
HR_NAME=""
HR_ROWS=0
HR_FLOOR=0
HR_RAN=0
HR_EMITTED=0
HR_TALLY=""

# The name is taken at SOURCE time from the sourcing file, not from `$0`. `$0` is
# whatever path the caller was invoked by - `scripts/check-x.sh`, `./check-x.sh`,
# or an absolute path from `ci-harness-gate.sh` - and a checker matching on
# `name=` must not have to know which. BASH_SOURCE[1] is the file that sourced
# this one; the `${...:-}` guard keeps `-u` happy if that is ever empty.
HR_NAME="$(basename "${BASH_SOURCE[1]:-${0}}")"

# THE HARNESS COMPLETED ITS ROWS. Call this ONCE, at the point where the row
# count and the floor are both known and every row has run - in practice the line
# immediately above the floor comparison, where `$TOTAL`/`$ROWS`/`$HELD` and
# `$ROW_FLOOR` are already in scope. Pass 0 as the floor for a harness that has
# none; 0 is not a floor anything can breach, and it reads as absent.
#
# It does NOT print. Printing here would put the line before the harness's own
# closing prose and, worse, would make the line's status a PREDICTION of the exit
# code rather than a report of it.
harness_result_ran() {
  HR_ROWS="$1"
  HR_FLOOR="$2"
  HR_RAN=1
}

# THE TALLY, PUBLISHED AS A NAMED FIELD. Task #120. Call it beside the harness's
# own closing tally line, with the SAME two counters that line prints and the
# same two the harness's own gate compares - never a recount, which would be a
# second copy free to disagree with the first.
#
#   harness_result_tally fired   "$FIRED"   "$TOTAL"
#   harness_result_tally killed  "$PASS"    "$((PASS + FAIL))"
#   harness_result_tally applied "$APPLIED" "$ROWS"
#
# `n` is what was achieved and `m` is what was held, in that order, for all three
# names. It does NOT print, for the same reason `harness_result_ran` does not.
#
# THE NAME IS CHECKED, NOT TAKEN ON TRUST. An unknown name would emit a field no
# reader looks for: a gate that greps for something nothing writes is the
# inoperative-gate shape - silent, and indistinguishable from coverage. A fifth
# meaning therefore needs a name HERE and a reader in `ci-harness-gate.sh`, and
# cannot be smuggled in through a caller.
harness_result_tally() {
  case "$1" in
    fired | killed | applied) ;;
    *)
      echo "::error::harness_result_tally: unknown tally kind '$1'." >&2
      echo "         It must be fired, killed or applied - one name per meaning." >&2
      echo "         A new meaning needs a name here AND a reader in" >&2
      echo "         scripts/ci-harness-gate.sh, or the field is written and" >&2
      echo "         never read." >&2
      return 2
      ;;
  esac
  HR_TALLY="$1=$2/$3"
}

# THE EMITTER, armed on EXIT so that it CANNOT BE FORGOTTEN on an abort path.
#
# `refused` IS THE DEFAULT, and that is the whole design. A harness that dies in
# setup, refuses a dirty tree, or is killed never reaches `harness_result_ran`,
# so its line says `refused` without anyone having to remember to say it. A
# silent harness and a passing one must never render identically - that is the
# shape that let 119 consecutive CI runs fail unread here, and a default of `ok`
# or an absent line would reproduce it exactly.
#
# `$?` IS CAPTURED ON THE FIRST LINE and returned on the last. Captured first,
# because anything before it - a `basename`, a `[` - would overwrite the status
# the trap fired with. Returned last, because in the traps this is chained into
# it is followed by the harness's own cleanup, and a cleanup that reads `$?`
# must see the script's status and not this function's.
harness_result_emit() {
  local rc=$?
  local status

  if [ "$HR_EMITTED" -ne 0 ]; then return "$rc"; fi
  HR_EMITTED=1

  if [ "$HR_RAN" -eq 0 ]; then
    status=refused
  elif [ "$rc" -eq 0 ]; then
    status=ok
  else
    status=breach
  fi

  # THE FORMAT LIVES HERE AND NOWHERE ELSE. A second copy is the defect.
  # The tally field is OMITTED when the harness published none, rather than
  # written as an empty or zero pair: `key=value` pairs looked up by name
  # tolerate an absent field, and a fabricated `fired=0/0` would be read by
  # `ci-harness-gate.sh` as a harness that held zero controls - a false finding
  # on every script that simply has no tally to report.
  printf 'HARNESS-RESULT name=%s rows=%s floor=%s %sstatus=%s\n' \
    "$HR_NAME" "$HR_ROWS" "$HR_FLOOR" "${HR_TALLY:+$HR_TALLY }" "$status"

  return "$rc"
}

# Armed immediately, so that an abort between here and the harness's own `trap`
# still reports. The harness's own EXIT trap, set later, REPLACES this one -
# bash has no trap stack - which is why `harness_result_emit` is also chained
# into the front of every such trap. Only one EXIT trap is ever live, so the
# line is printed once; `HR_EMITTED` guards the case anyway rather than relying
# on that reasoning holding for the next editor.
trap harness_result_emit EXIT
