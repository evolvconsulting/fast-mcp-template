#!/usr/bin/env bash
# ONE gate for every mutation and amputation harness, runnable locally.
#
# WHY IT EXISTS (task #27). The U1 amputation gate's logic lived inline in a
# ci.yml `run:` block, so it could not be run locally, reviewed as code, or
# exercised by a control. The agent before this one verified a change to it by
# hand-copying the block into a local script and replaying recorded output, then
# deliberately did NOT commit the copy - a hand-copied twin of a gate is the
# two-lists defect: ci.yml moves, the twin does not, and the twin keeps passing.
# That refusal was right. This is the real thing, called by ci.yml, with no twin.
#
# WHY IT IS SHARED (task #29). Six steps could not detect a stale anchor. The
# fix is NOT six copies of one grep: the harnesses use different vocabulary, and
# a grep for a string a harness never prints is an INOPERATIVE gate - the same
# defect as the stale anchor, arriving from the other side, and worse than the
# gap because it looks like coverage.
#
# So the vocabulary is DERIVED, not configured. For each harness this reads the
# HARNESS'S OWN SOURCE, keeps the anchor-failure phrases that actually appear in
# it, and greps the log for exactly those. A phrase a harness cannot print is
# never grepped, and a harness that can print NONE of them fails the gate
# outright with a message saying so - because a harness that cannot report a
# failed anchor cannot be gated on one, and that is a defect in the harness.
#
# SCOPE DECISION, task #27, MINE AND STATED. Every harness step in ci.yml now
# calls this; none is left inline. Converting one step would have made the file
# inconsistent for no gain, and the sibling steps were near-identical copies of
# each other already - which is what let U3's and U4's mutation steps BOTH ship
# the same anchor blindness and get fixed twice. The non-harness steps (lint,
# types, the licence gate) are untouched: they are single commands, not
# multi-branch logic, and inline is the right form for them.
#
# THIS IS THE SECOND LAYER, NOT THE FIRST. scripts/check-harness-anchors.py
# reads the anchors statically and catches a stale one in milliseconds, without
# running anything. This catches what only running can show - a mutation that
# applied and then landed on nothing, a row that hung, a control that did not
# fire - and it is also what covers a harness inventing a phrase the static
# checker's shapes cannot see.
#
# Usage:
#   ci-harness-gate.sh <harness.sh> [options]
#     --controls-fired        require `fired=N/M` on the harness's canonical line, N == M, M > 0
#     --result-killed         require `killed=N/M` on it, N == M, M > 0
#     --anchors-applied       require `applied=N/M` on it, N == M, M > 0
#     --min-rows N --row-re RE  require at least N lines matching RE
#     --require RE            require at least one line matching RE
#     --amputation            survivors are output, so exit 0 is not the only pass;
#                             exit 1 is a FINDING, exit 3 is "could not run", and
#                             exit 5 is REFUSED - a row whose pytest run was not a
#                             measurement (#254)
set -uo pipefail

# THE ONE CANONICAL RESULT LINE (task #107). This arms an EXIT trap that prints
# `HARNESS-RESULT name=... rows=... floor=... status=refused` on ANY exit, so an
# abort cannot render identically to a pass. `harness_result_ran` below upgrades
# it to ok/breach from the real exit code. The format lives in the sourced file
# and nowhere else - the shape lists it replaces are why.
# shellcheck source=lib/harness-result.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/harness-result.sh"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# THE ANCHOR-FAILURE VOCABULARY, all of it, across every harness here. A phrase
# is grepped for ONLY when the harness's own source contains it, so this list
# can gain a phrase without making any existing gate inoperative.
#
# `MUTATION TARGET NOT FOUND` and `BROKEN CONTROL` come from U15's controls;
# `ANCHOR MISSING`/`ANCHOR NOT UNIQUE` from the suite-floor harness and the
# shared python mutators; `COULD NOT APPLY` from U3, U4 and U5; `DID NOT LAND`
# from U1's controls and the suite-floor harness; `anchor is not unique` from
# U1's amputation harness. They are NOT unified into one phrase: each is printed
# beside a different diagnosis, and collapsing them would send the next reader to
# the wrong place - the same defect one layer up that this file's exit-code
# branches exist to avoid.
VOCABULARY=(
  'COULD NOT APPLY'
  'DID NOT LAND'
  'ANCHOR MISSING'
  'ANCHOR NOT UNIQUE'
  'anchor is not unique'
  'MUTATION TARGET NOT FOUND'
  'BROKEN CONTROL'
  'STAGING ERROR'
  'the mutation target was not found'
)

harness=""
want_controls_fired=0
want_result_killed=0
want_anchors_applied=0
min_rows=0
row_re=""
amputation=0
requires=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --controls-fired)  want_controls_fired=1; shift ;;
    --result-killed)   want_result_killed=1; shift ;;
    --anchors-applied) want_anchors_applied=1; shift ;;
    --amputation)      amputation=1; shift ;;
    --min-rows)        min_rows="$2"; shift 2 ;;
    --row-re)          row_re="$2"; shift 2 ;;
    --require)         requires+=("$2"); shift 2 ;;
    -*) echo "::error::unknown option $1"; exit 2 ;;
    *)  harness="$1"; shift ;;
  esac
done

[ -n "$harness" ] || { echo "::error::no harness named"; exit 2; }
HARNESS_PATH="$REPO/scripts/$harness"
[ -f "$HARNESS_PATH" ] || { echo "::error::no such harness: scripts/$harness"; exit 2; }

# Derive this harness's vocabulary from its own source BEFORE running it, so a
# harness that cannot report a failed anchor fails in seconds rather than after
# the run. THE HARNESS'S OWN GATE VOCABULARY IS THE ONE THING NOT TAKEN ON
# TRUST: task #29 measured that check-u15-gate-amputation.sh had none at all, so
# no step could gate on it, and it had been passing for months on that basis.
present=()
for phrase in "${VOCABULARY[@]}"; do
  if grep -qF -- "$phrase" "$HARNESS_PATH"; then present+=("$phrase"); fi
done

if [ "${#present[@]}" -eq 0 ]; then
  echo "::error::scripts/$harness prints NO anchor-failure phrase, so nothing can gate"
  echo "         on one. A mutation that applies to nothing tests nothing, and this"
  echo "         harness cannot say that it happened. Give it one of:"
  printf '           %s\n' "${VOCABULARY[@]}"
  exit 2
fi
echo "gate vocabulary for $harness (derived from its source): ${present[*]}"

# THE TREE BEFORE THE RUN. A mutation harness edits the working tree and
# restores; if it is interrupted between those steps THE MUTATION STAYS, and
# nothing here used to say so. Measured 2026-08-29: a killed
# check-u9-http-amputation.sh left `build_token_verifier` cut to
# `if True: return None` - every bearer-token check on the HTTP transport
# disabled - in a tree someone was about to commit from. It was found only
# because an agent ran `git status` out of habit. No gate spoke.
#
# Pre-existing dirt is TOLERATED and recorded, not failed on: this gate runs in
# worktrees where an agent is legitimately mid-change. What is failed on is dirt
# that APPEARED during the run, which is the harness's own doing.
tree_before=$(git -C "$REPO" status --porcelain 2>/dev/null || true)

# ---- #131: leave a trail a SIGKILL cannot erase -----------------------------
#
# A mutation harness edits a tracked file and restores in a `trap`. SIGKILL runs
# no trap, so a killed harness leaves its mutation live in the tree and nothing
# owns putting it back. It happened four times in one day here, and
# `docs/reviews/restore-stranded-mutation.sh` was built to repair it - but it
# reads a STATE FILE rather than `git status`, because `git status` can say the
# tree is dirty and can never say whether that dirt has an owner. Its own header
# names the gap this closes: only `probe-harness-exit-codes.sh` wrote that state,
# so a harness run through THIS gate - which is every harness step in CI, and the
# way they are run by hand - was invisible to the restorer.
#
# Fixed HERE, at the one shared entry point, rather than in twenty-odd harnesses.
#
# THREE CONDITIONS, and each one's failure is PRINTED rather than silent, because
# a state file that was never written and one that was written and lost look
# identical to the restorer:
#
#   * The tree must be CLEAN. The recorded commit is the restore reference, and
#     it is only sound when worktree, index and HEAD agree at this instant. This
#     gate deliberately tolerates pre-existing dirt (see above), so on a dirty
#     tree it records nothing and says so.
#   * HEAD must resolve. No sha, no reference, no state.
#   * An existing state file is NEVER overwritten. It is another run's evidence,
#     and clobbering it would destroy the only record of what that run mutated.
# shellcheck source=../docs/reviews/lib/harness-state.sh
. "$REPO/docs/reviews/lib/harness-state.sh"
state_written=0
existing_state=$(harness_state_file "$REPO")
head_sha=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)
if [ -f "$existing_state" ]; then
  echo "NOTE: a harness run state file already exists at $existing_state."
  echo "      Not overwriting it - it is another run's evidence. This run is"
  echo "      NOT covered by restore-stranded-mutation.sh."
elif [ -n "$tree_before" ]; then
  echo "NOTE: the tree was already dirty before this run, so no restore"
  echo "      reference was recorded. A mutation stranded by a kill here"
  echo "      cannot be attributed, and the dirt would not be new anyway."
elif [ -z "$head_sha" ]; then
  echo "NOTE: HEAD does not resolve, so there is no restore reference to"
  echo "      record. This run is not covered by the stranded-mutation tool."
else
  harness_state_begin "$REPO" "$harness" "$head_sha"
  state_written=1
fi

out=$(bash "$HARNESS_PATH" 2>&1); rc=$?

# A gate invocation runs exactly ONE harness, so its own row count is 1
# and it has no floor. Called HERE rather than earlier so that every
# refusal above - no harness named, no such harness, no gate vocabulary -
# still reports status=refused, which is what those refusals are.
harness_result_ran 1 0
echo "$out"

# ---- did the harness put the tree back? ------------------------------------
tree_after=$(git -C "$REPO" status --porcelain 2>/dev/null || true)

# THE STATE FILE IS CLEARED ONLY WHEN THE TREE CAME BACK, and only when THIS
# run wrote it. Clearing it on a tree that did not come back would erase the
# record at the exact moment the restorer needs it - which is the mistake
# `harness_state_end`'s own comment warns about, from the other side.
if [ "$state_written" -eq 1 ] && [ "$tree_before" = "$tree_after" ]; then
  harness_state_end "$REPO"
elif [ "$state_written" -eq 1 ]; then
  echo "NOTE: the run state file is being LEFT IN PLACE because the tree did"
  echo "      not come back. Run docs/reviews/restore-stranded-mutation.sh."
fi

if [ "$tree_before" != "$tree_after" ]; then
  # TWO DIFFERENT FAILURES, and they must not share a message. This file
  # already says why, one section down: "a message that misdescribes what
  # happened sends the next reader to the wrong place". Measured while
  # writing this - a control that WIPED pre-existing dirt was reported as
  # a stranded mutation, which would have sent someone hunting a mutation
  # that was not there.
  appeared=$(comm -13 <(printf '%s\n' "$tree_before" | sort) \
                      <(printf '%s\n' "$tree_after" | sort))
  vanished=$(comm -23 <(printf '%s\n' "$tree_before" | sort) \
                      <(printf '%s\n' "$tree_after" | sort))

  if [ -n "$appeared" ]; then
    echo "::error::$harness DID NOT RESTORE THE WORKING TREE."
    echo "         A mutation harness owns the tree for its whole run and restores"
    echo "         at the end. What changed DURING this run and is still changed is"
    echo "         almost certainly a STRANDED MUTATION - source edited to be wrong"
    echo "         on purpose, left in place. Measured once: a killed harness left"
    echo "         every bearer-token check on the HTTP transport disabled."
    echo "         DO NOT COMMIT FROM THIS TREE. Read the diff first:"
    printf '           %s\n' "$appeared"
  fi

  if [ -n "$vanished" ]; then
    echo "::error::$harness DESTROYED UNCOMMITTED WORK that predated it."
    echo "         These files were modified before the run and are clean now, so"
    echo "         the harness's restore - which is \`git checkout --\` - discarded"
    echo "         someone else's edits. This is why a harness refuses to start on"
    echo "         a dirty tree; that refusal is a guard, not an obstacle."
    printf '           %s\n' "$vanished"
  fi
  exit 1
fi

# ---- interrupted is NOT the same as failed ---------------------------------
# A signal death and a finding both arrive as a non-zero code, and reporting
# them the same way is the switched-off-vs-broken shape: 128+N means the run
# was KILLED and measured nothing, so its silence is not evidence of anything.
if [ "$rc" -ge 128 ]; then
  echo "::error::$harness was KILLED by signal $((rc - 128)) and did not finish."
  echo "         This is NOT a verdict. The harness measured nothing, and a green"
  echo "         from a later step does not cover what it would have checked."
  echo "         The tree was verified restored above; re-run it before trusting"
  echo "         any result that depended on it."
  exit 1
fi

# ---- exit code -------------------------------------------------------------
# An amputation harness exits 0 by design because SURVIVORS ARE ITS OUTPUT, so
# the exit code alone cannot be the verdict. U1's harness distinguishes three
# codes and the messages are kept apart on purpose: a message that misdescribes
# what happened sends the next reader to the wrong place.
if [ "$amputation" -eq 1 ]; then
  if [ "$rc" -eq 1 ]; then
    echo "::error::$harness: an amputation was survived by an assertion that exists to"
    echo "         notice it, or a row could not be measured. Search the log above for"
    echo "         UNEXPECTED SURVIVOR and TIMED OUT."
    exit 1
  fi
  if [ "$rc" -eq 3 ]; then
    echo "::error::$harness could not run: the intact baseline is red, or a declared"
    echo "         test id no longer exists (a rename silently voids its row)."
    exit 1
  fi
  # 5 = REFUSED (#254). Kept apart from 1 and 3 for the same reason those two
  # are kept apart: without this arm it fell through to the generic
  # "$harness exited 5" below, which is precisely the message-that-misdescribes
  # shape the comment above forbids. A refusal is neither a finding nor a
  # could-not-run: the harness ran, the row's mutation landed, and the row's
  # result is not interpretable.
  if [ "$rc" -eq 5 ]; then
    echo "::error::$harness REFUSED a row: pytest exited with a code that is not a"
    echo "         measurement (collection error, internal error, usage error, or a"
    echo "         timeout). This is NOT 'every assertion died' - the row measured"
    echo "         nothing. Search the log above for REFUSING."
    exit 1
  fi
fi
if [ "$rc" -ne 0 ]; then
  echo "::error::$harness exited $rc"
  exit 1
fi

fail=0

# ---- the anchor gate, uniform and never inoperative ------------------------
for phrase in "${present[@]}"; do
  # `grep -q` exits on its FIRST match; if the writer is still
  # writing it takes SIGPIPE, and `pipefail` promotes that 141 to
  # the pipeline's status - so a string that IS present reports as
  # ABSENT, but only once the output outruns the pipe buffer.
  # Measured: present+large 141, present+small 0. A bash test has
  # no second process and cannot SIGPIPE.
  if [[ "$out" == *"$phrase"* ]]; then
    echo "::error::$harness printed '$phrase' - a row's anchor moved and that row"
    echo "         tested NOTHING. The harness still exited 0; that is the point."
    fail=1
  fi
done

# ---- a hang measures nothing, and a timed-out row reads as a pass ----------
# THIS SITE FAILED OPEN: a 141 read as "no TIMED OUT found", on
# exactly the run whose output is longest - the run most likely to
# have timed out. See the SIGPIPE note above.
if [[ "$out" == *"TIMED OUT"* ]]; then
  echo "::error::$harness: a row hung. It produced no result lines, so every"
  echo "         assertion 'did not survive' and the row reads as a pass."
  fail=1
fi

# ---- THE TALLY, READ FROM THE CANONICAL LINE AND NOT FROM PROSE ------------
# TASK #120, and this is the half #107 left open. These three flags used to
# parse three hand-kept PROSE shapes out of the harness's log - `N/M controls
# fired.`, `RESULT: N killed, M not killed`, and `ROWS: N   ANCHORS APPLIED: M`,
# the last carrying three significant spaces. Three literals in THIS file that
# had to stay byte-matched to one echo statement in each of twenty-six others:
# the same hand-kept shape list #107 deleted from the floor half, still standing
# in the tally half.
#
# THE HUMAN PROSE STAYS in the harnesses. What moved is the MACHINE's reading of
# it: each harness now publishes `fired=`/`killed=`/`applied=` through
# scripts/lib/harness-result.sh, where the format has one home, and this reads
# that field by name. A harness rewording its sentence can no longer break a
# gate, and a gate can no longer be quietly reworded away from its harness.
#
# THE MEANINGS ARE STILL FOUR AND ARE STILL KEPT APART. There is one field name
# per meaning, this reads only the one its own flag names, and the three
# diagnoses below are written separately on purpose - a message that
# misdescribes what happened sends the next reader to the wrong place, which is
# what this file says about the anchor vocabulary one section up.
#
# THE LINE IS SELECTED BY `name=`, NEVER BY POSITION. This gate sources the same
# shared file and emits its OWN canonical line, so the step's log holds more than
# one; and a harness that echoes an artifact it ran would put a second one inside
# `$out` itself. `tail -1` over all of them would read the wrong harness's tally.
# The prose shapes had no name field and could not make this distinction at all.
tally_n=0
tally_m=0

# read_tally <field> <what>: sets tally_n/tally_m, or complains and returns 1.
# The two STRUCTURAL failures - no canonical line, no such field on it - are one
# defect with one meaning ("this harness published no tally"), so they share a
# message. The numeric comparisons do NOT: those are per-flag, below.
read_tally() {
  local field="$1" what="$2" line
  # A here-string, not a pipe: `grep -q`-style early exit under `pipefail`
  # promotes SIGPIPE to 141 on long output, which this file has been bitten by
  # twice. See the note above the anchor gate.
  line=$(grep -E "^HARNESS-RESULT name=$harness " <<< "$out" | tail -1)
  if [ -z "$line" ]; then
    echo "::error::$harness printed no HARNESS-RESULT line naming itself, so its"
    echo "         $what cannot be read. Every script under scripts/ emits one"
    echo "         from scripts/lib/harness-result.sh; docs/reviews/"
    echo "         check-harness-result.sh asserts that as a set equality."
    return 1
  fi
  tally_n=$(tr ' ' '\n' <<< "$line" | sed -n "s|^$field=\([0-9][0-9]*\)/[0-9][0-9]*$|\1|p")
  tally_m=$(tr ' ' '\n' <<< "$line" | sed -n "s|^$field=[0-9][0-9]*/\([0-9][0-9]*\)$|\1|p")
  if [ -z "$tally_n" ] || [ -z "$tally_m" ]; then
    echo "::error::$harness's canonical line carries no readable '$field=N/M'"
    echo "         field, so its $what was never published:"
    echo "           $line"
    echo "         Call \`harness_result_tally $field <n> <m>\` beside the"
    echo "         harness's own tally line. A gate reading a field nothing"
    echo "         writes is INOPERATIVE and looks exactly like coverage."
    return 1
  fi
  return 0
}

if [ "$want_controls_fired" -eq 1 ]; then
  if read_tally fired "controls tally"; then
    if [ "$tally_m" -eq 0 ]; then
      echo "::error::$harness holds ZERO controls; a green from it means nothing"; fail=1
    elif [ "$tally_n" -ne "$tally_m" ]; then
      echo "::error::$harness: only $tally_n of $tally_m controls fired"; fail=1
    fi
  else
    fail=1
  fi
fi

if [ "$want_result_killed" -eq 1 ]; then
  if read_tally killed "mutation tally"; then
    # ZERO FIRST. `n -ne m` is FALSE at 0 == 0, so a harness that ran NO
    # mutations would sail through the comparison below saying nothing survived.
    if [ "$tally_m" -eq 0 ]; then
      echo "::error::$harness killed ZERO mutations - it ran nothing"; fail=1
    elif [ "$tally_n" -ne "$tally_m" ]; then
      echo "::error::$harness: $((tally_m - tally_n)) mutations survived"; fail=1
    fi
  else
    fail=1
  fi
fi

if [ "$want_anchors_applied" -eq 1 ]; then
  if read_tally applied "anchor tally"; then
    # ZERO FIRST, for the reason its two siblings above give: a harness that ran
    # NOTHING reports 0/0 and every equality check passes. Without this the
    # script disagreed with ITSELF about whether an empty run is acceptable,
    # depending only on which flag you passed. The generic form of R4-M4.
    if [ "$tally_m" -eq 0 ]; then
      echo "::error::$harness ran ZERO rows; a green from it means nothing"; fail=1
    elif [ "$tally_n" -ne "$tally_m" ]; then
      echo "::error::$harness: only $tally_n of $tally_m anchors applied"; fail=1
    fi
  else
    fail=1
  fi
fi

# ---- row count -------------------------------------------------------------
# A gate reporting the number of rows it can SEE is how a row goes missing
# without a red run: U4's pattern once required a space straight after the
# digits, so it counted 12 while 17 ran.
if [ "$min_rows" -gt 0 ]; then
  [ -n "$row_re" ] || { echo "::error::--min-rows needs --row-re"; exit 2; }
  rows=$(printf '%s\n' "$out" | grep -cE "$row_re")
  if [ "$rows" -lt "$min_rows" ]; then
    echo "::error::$harness: only $rows rows ran, expected at least $min_rows"; fail=1
  fi
fi

# ---- arbitrary required lines ---------------------------------------------
for re in ${requires+"${requires[@]}"}; do
  # The `!` made this site fail CLOSED - a 141 became a gate failure,
  # so it was loud rather than silent, and still wrong.
  #
  # **A HERE-STRING, NOT bash's `=~`, AND THE DIFFERENCE IS SEMANTIC.**
  # `grep -qE` matches PER LINE; bash `=~` matches the whole string, so
  # `^` anchors to the start of the OUTPUT rather than of a line. Every
  # row regex here starts with `^`, so `=~` would only ever match when
  # the very first line is a row. Measured on an output whose second
  # line is a row: pipe 141, `=~` 1, here-string 0.
  #
  # A here-string has no pipeline, so `pipefail` has nothing to promote
  # and grep's own status is the result.
  if ! grep -qE -- "$re" <<< "$out"; then
    echo "::error::$harness did not print a line matching: $re"; fail=1
  fi
done

exit "$fail"
