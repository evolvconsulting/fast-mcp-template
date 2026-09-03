#!/usr/bin/env bash
# CONTROLS for scripts/ci-harness-gate.sh - the gate every harness step calls.
#
# A gate whose whole job is to notice that a harness stopped checking is worth
# nothing until something has watched it FAIL. Task #27 exists because that gate
# lived inline in a ci.yml `run:` block and could not be exercised at all.
#
# EACH ROW SUBSTITUTES A STUB HARNESS that replays RECORDED output - the real
# lines the real harnesses print - and exits with a chosen code. Stubs, because
# the arms worth testing are the ones a healthy repository never produces: a
# moved anchor, a hung row, a control that did not fire. Waiting for a real
# harness to fail is not a test plan, and a green repository cannot supply one.
#
# THE STUB IS NOT A TWIN OF THE GATE. The thing being tested is the real
# scripts/ci-harness-gate.sh, copied unmodified and invoked as CI invokes it;
# only its SUBJECT is substituted. A twin of the gate would be the two-lists
# defect this whole change exists to remove.
set -uo pipefail

# THE ONE CANONICAL RESULT LINE (task #107). This arms an EXIT trap that prints
# `HARNESS-RESULT name=... rows=... floor=... status=refused` on ANY exit, so an
# abort cannot render identically to a pass. `harness_result_ran` below upgrades
# it to ok/breach from the real exit code. The format lives in the sourced file
# and nowhere else - the shape lists it replaces are why.
# shellcheck source=lib/harness-result.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/harness-result.sh"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'harness_result_emit; rm -rf "$WORK"' EXIT

mkdir -p "$WORK/scripts"
cp "$REPO/scripts/ci-harness-gate.sh" "$WORK/scripts/"

# THE SHARED LIBRARY COMES WITH IT, and its absence was a real defect measured
# on 2026-09-01 while #120 was being written. Only the gate was copied here, so
# the gate under test resolved `lib/harness-result.sh` to a path in $WORK that
# did not exist and printed, on every one of the 24 rows:
#
#   .../scripts/ci-harness-gate.sh: line 57: .../scripts/lib/harness-result.sh:
#       No such file or directory
#   .../scripts/ci-harness-gate.sh: line 150: harness_result_ran: command not found
#
# Every row still passed, because `row` compares only the exit code and a
# `command not found` under `set -uo pipefail` with no `-e` changes none. So
# since #107 this harness had been certifying a gate whose canonical-line
# machinery was entirely absent - the switched-off-vs-broken shape, inside the
# controls written to prevent it. The stubs below now source the same file.
cp -R "$REPO/scripts/lib" "$WORK/scripts/"

FIRED=0
TOTAL=0

# stub <name> <vocab: yes|no> <exit code> <tally: "kind n m" | -> <lines...>
#
# THE TALLY IS PUBLISHED THROUGH THE REAL SHARED FILE, not replayed as a
# recorded string. #120 moved the three tally flags off prose and onto the
# canonical line's named fields, and a stub that echoed a hand-typed
# `HARNESS-RESULT ...` line would put a second copy of that format here - the
# exact defect scripts/lib/harness-result.sh exists to delete. Sourcing it
# instead means these rows exercise the REAL emitter against the REAL gate.
#
# `-` publishes NO tally, which is its own arm: a harness that never calls
# `harness_result_tally` must be CAUGHT by any flag asking for one, never
# passed over. A gate that greps for a field nothing writes is inoperative.
#
# `vocab` puts the anchor-failure phrases in the stub's SOURCE, as a comment,
# without PRINTING them. That separation is the whole subject: the gate derives
# what to grep for from the harness's source and then looks for it in the
# harness's OUTPUT, and a stub that conflated the two could not tell the two
# halves apart. `vocab no` is C4 - the harness that cannot report a moved anchor
# at all, which is the defect check-u15-gate-amputation.sh actually had.
#
# Lines are emitted single-quoted, NOT with `printf %q`. %q backslash-escapes
# the spaces, so `echo COULD\ NOT\ APPLY` does not contain the phrase
# `COULD NOT APPLY` as source text - and the first run of this harness had 21 of
# 23 rows refused for want of a vocabulary that was there all along, in a form
# no `grep -F` could see. An escaping that survives execution but not inspection
# is invisible in exactly the direction that matters here.
stub() {
  local name="$1" vocab="$2" code="$3" tally="$4"; shift 4
  { echo '#!/usr/bin/env bash'
    echo 'set -uo pipefail'
    echo '. "$(dirname "${BASH_SOURCE[0]}")/lib/harness-result.sh"'
    if [ "$vocab" = yes ]; then
      echo '# recorded vocabulary, present in source and NOT printed:'
      echo '#   COULD NOT APPLY / DID NOT LAND / ANCHOR NOT UNIQUE'
    fi
    local line
    for line in "$@"; do printf "echo '%s'\n" "$line"; done
    echo 'harness_result_ran 1 0'
    [ "$tally" = - ] || echo "harness_result_tally $tally"
    echo "exit $code"
  } > "$WORK/scripts/$name"
  chmod +x "$WORK/scripts/$name"
}

# A stub that does not source the shared file at all, so it emits NO canonical
# line. Separate from `stub` because it is a different claim: `-` above is a
# harness that emits the line WITHOUT a tally field, this is one that emits no
# line. The two failure messages in the gate are written apart and both are
# reachable only if both stubs exist.
stub_no_line() {
  local name="$1"
  { echo '#!/usr/bin/env bash'
    echo '# recorded vocabulary, present in source and NOT printed:'
    echo '#   COULD NOT APPLY / DID NOT LAND / ANCHOR NOT UNIQUE'
    echo "echo 'ran some things'"
    echo 'exit 0'
  } > "$WORK/scripts/$name"
  chmod +x "$WORK/scripts/$name"
}

# row <label> <want rc> <harness> <gate args...>
row() {
  local label="$1" want="$2" harness="$3"; shift 3
  TOTAL=$((TOTAL + 1))
  local out rc
  out=$(bash "$WORK/scripts/ci-harness-gate.sh" "$harness" "$@" 2>&1); rc=$?
  if [ "$rc" -eq "$want" ]; then
    FIRED=$((FIRED + 1))
    echo "  FIRED    $label (exit $rc)"
  else
    echo "  SURVIVED $label (exit $rc, wanted $want)"
    printf '%s\n' "$out" | sed 's/^/      /'
  fi
}

echo "########## THE ANCHOR GATE - the defect that started all of this"

# The vocabulary is DERIVED from the stub's own source, so a stub that prints
# COULD NOT APPLY also contains it and the gate greps for it. That coupling is
# the point: a phrase a harness cannot print is never grepped for.
stub clean.sh yes 0 'killed 12 12' 'RESULT: 12 killed, 0 not killed'
row "C1 a clean mutation harness passes" 0 clean.sh --result-killed

stub moved.sh yes 0 'killed 12 12' \
  'M8: COULD NOT APPLY - the anchor moved. Fix the harness.' \
  'RESULT: 11 killed, 0 not killed'
row "C2 COULD NOT APPLY is caught even though the harness exited 0" 1 moved.sh --result-killed

stub notland.sh yes 0 'killed 12 12' \
  '  AMPUTATION DID NOT LAND despite a successful write' \
  'RESULT: 12 killed, 0 not killed'
row "C3 DID NOT LAND is caught even though the harness exited 0" 1 notland.sh --result-killed

echo
echo "########## THE HARNESS THAT CANNOT REPORT ONE AT ALL - task #29's sharpest item"

# No phrase from the vocabulary anywhere in its source. The gate must REFUSE it
# rather than pass it, because a grep for a string a harness never prints is an
# inoperative gate that looks exactly like coverage.
stub mute.sh no 0 'killed 12 12' 'everything is fine'
row "C4 a harness with no anchor-failure vocabulary is REFUSED" 2 mute.sh --result-killed

echo
echo "########## EXIT CODES - three, kept apart"

stub survivor.sh yes 1 - '  UNEXPECTED SURVIVOR: tests/test_boot.py::test_x'
row "C5 an amputation exit 1 is a FINDING, not a pass" 1 survivor.sh --amputation

stub cannotrun.sh yes 3 - 'baseline is red'
row "C6 an amputation exit 3 is could-not-run" 1 cannotrun.sh --amputation

stub weird.sh yes 7 - 'something else'
row "C7 any other non-zero exit fails" 1 weird.sh --amputation

echo
echo "########## A HUNG ROW MEASURES NOTHING AND READS AS A PASS"

stub hung.sh yes 0 - '  TIMED OUT after 300s' \
  '########## A1 x' '########## A2 x'
row "C8 TIMED OUT is caught" 1 hung.sh --amputation

echo
echo "########## THE COUNTING ARMS"

# THE PROSE IS STILL PRINTED AND IS NO LONGER READ. Each stub below echoes the
# sentence its real harness echoes AND publishes the field the gate now reads,
# so a row that passed for the prose and fails for the field - or the reverse -
# is visible here rather than in CI. #120.

stub fired.sh yes 0 'fired 14 14' '14/14 controls fired.'
row "C9 all controls fired passes" 0 fired.sh --controls-fired

stub partial.sh yes 0 'fired 13 14' '13/14 controls fired.'
row "C10 13 of 14 fired is caught" 1 partial.sh --controls-fired

# A harness that holds ZERO controls reports "0/0 controls fired." and every
# equality check passes. A green from it means nothing, and equality alone
# cannot tell it apart from a harness that ran everything.
stub zero.sh yes 0 'fired 0 0' '0/0 controls fired.'
row "C11 zero controls held is caught, though 0 == 0" 1 zero.sh --controls-fired

# THE FIELD IS ABSENT, one row per flag. This is the arm the whole change turns
# on: a gate that reads a field no harness writes greps for nothing, finds
# nothing, and - if it failed OPEN - would pass forever while checking nothing.
# This family has shipped exactly that defect before. The prose is still printed
# in each case, so these rows also prove the gate is no longer reading it.
stub notally.sh yes 0 - '13/14 controls fired.'
row "C12 a canonical line with no fired= field is caught" 1 notally.sh --controls-fired

stub notallyk.sh yes 0 - 'RESULT: 11 killed, 1 not killed'
row "C25 a canonical line with no killed= field is caught" 1 notallyk.sh --result-killed

stub notallya.sh yes 0 - 'ROWS: 11   ANCHORS APPLIED: 9'
row "C26 a canonical line with no applied= field is caught" 1 notallya.sh --anchors-applied

# NO CANONICAL LINE AT ALL, which is a different defect from a line without the
# field and carries a different message in the gate. Without this row that
# message is unreachable and untested.
stub_no_line nocanon.sh
row "C27 a harness emitting no HARNESS-RESULT line at all is caught" 1 nocanon.sh --controls-fired

# THE THREE NAMES ARE NOT INTERCHANGEABLE, and this is the row that proves the
# gate did not quietly collapse them into one reader. The stub publishes a
# PERFECT applied=11/11 and the flag asks for fired=; a gate matching "any
# tally field" would pass it, and would then read an anchor count as a control
# count on every harness that carries both meanings.
stub wrongkind.sh yes 0 'applied 11 11' '11/11 controls fired.'
row "C28 a tally of the WRONG kind does not satisfy the flag" 1 wrongkind.sh --controls-fired

stub survived.sh yes 0 'killed 11 12' 'RESULT: 11 killed, 1 not killed'
row "C13 a surviving mutation is caught" 1 survived.sh --result-killed

stub nokill.sh yes 0 'killed 0 0' 'RESULT: 0 killed, 0 not killed'
row "C14 zero mutations killed is caught, though 0 survived" 1 nokill.sh --result-killed

stub applied.sh yes 0 'applied 11 11' 'ROWS: 11   ANCHORS APPLIED: 11'
row "C15 every anchor applied passes" 0 applied.sh --anchors-applied

stub short.sh yes 0 'applied 9 11' 'ROWS: 11   ANCHORS APPLIED: 9'
row "C16 9 of 11 anchors applied is caught" 1 short.sh --anchors-applied

# C11 and C14 are this row's siblings, and its absence was the defect: `rows -ne
# applied` is FALSE at 0 == 0, so a harness that ran NOTHING passed the gate
# while the other two flags already refused their own zero. The generic form of
# R4-M4, and it applied to every harness gated this way, not just U5's.
stub norows.sh yes 0 'applied 0 0' 'ROWS: 0   ANCHORS APPLIED: 0'
row "C24 zero rows is caught, though 0 == 0" 1 norows.sh --anchors-applied

echo
echo "########## ROW COUNT - how a row goes missing without a red run"

stub rows.sh yes 0 - \
  '########## A1 x' '########## A2 x' '########## A3 x'
row "C17 enough rows passes" 0 rows.sh --amputation --min-rows 3 --row-re '^########## A[0-9]+ '
row "C18 a vanished row is caught" 1 rows.sh --amputation --min-rows 4 --row-re '^########## A[0-9]+ '

# The U4 lesson, as a row: `A[0-9]+ ` requires a space straight after the
# digits, so A9b..A9f are invisible to it and the gate reports the number of
# rows it can SEE. The correct pattern counts them.
stub suffixed.sh yes 0 - \
  '########## A9b x' '########## A9c x' '########## A9d x'
row "C19 a suffixed row id is INVISIBLE to the naive pattern" 1 suffixed.sh \
  --amputation --min-rows 3 --row-re '^########## A[0-9]+ '
row "C20 and visible to the corrected one" 0 suffixed.sh \
  --amputation --min-rows 3 --row-re '^########## A[0-9]+[a-z]* '

echo
echo "########## --require, which is how a restore failure is noticed"

stub restored.sh yes 0 - \
  'post-run re-check of the real script: exit=0'
row "C21 the restore line present passes" 0 restored.sh --amputation \
  --require 'post-run re-check of the real script: exit=0'

stub norestore.sh yes 0 - '4/4 amputations killed a test.'
row "C22 a missing restore line is caught" 1 norestore.sh --amputation \
  --require 'post-run re-check of the real script: exit=0'

echo
echo "########## MISUSE - a gate misconfigured must not read as a pass"

row "C23 a harness that does not exist is refused" 2 no-such-harness.sh --result-killed

echo
echo "$FIRED/$TOTAL controls fired."
# The canonical result line's tally, from the SAME two counters the line
# above prints and the harness's own gate compares - never a recount.
harness_result_tally fired "$FIRED" "$TOTAL"

# The canonical result line's row count, from the harness's own
# counter. This harness declares no ROW_FLOOR, so the floor is 0:
# 0 is not a floor anything can breach, and it reads as absent.
harness_result_ran "$TOTAL" 0
if [ "$TOTAL" -eq 0 ]; then
  echo "::error::the harness holds zero rows; a green from it means nothing"
  exit 1
fi
if [ "$FIRED" -ne "$TOTAL" ]; then
  echo "::error::$FIRED of $TOTAL fired. Every survivor names an arm of the gate that"
  echo "         does not do what its own message says it does."
  exit 1
fi
