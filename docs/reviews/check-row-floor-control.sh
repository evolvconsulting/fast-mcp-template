#!/usr/bin/env bash
# POSITIVE CONTROL for the row floors added by task #79.
#
# WHY THIS EXISTS. Ten harnesses now carry a ROW_FLOOR. Every one of those
# numbers was derived from a run, but a floor that has never been watched
# FAIL is still only a typed number: the comparison could be inverted, the
# variable could be misspelled under `set -u`, the exit could be swallowed.
# This deletes a real row from a real harness and reads that harness's own
# exit code.
#
# It picks check-u15-gate-amputation.sh because that harness deliberately
# does NOT fail on survivors, so it is the one where "exit 1" can only mean
# the floor fired - nothing else in it exits 1 on a healthy tree.
#
# NOT A CI GATE, on purpose: it edits a tracked file in the working tree.
# It restores by byte-comparison against a backup rather than by re-editing,
# because a `sed` that matches nothing succeeds silently.
#
# Run it from anywhere. Takes about a minute.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
S="$REPO/scripts/check-u15-gate-amputation.sh"
B="$(mktemp)"

# A dirty subject file means someone else is mid-edit; measuring it would
# measure them, not the floor.
# `git status --porcelain`, NOT `git diff --quiet`. `git diff` compares the
# worktree to the INDEX, so a file edited and then `git add`-ed reads CLEAN
# and this guard waves it through. Measured: modify + `git add` gives
# `git diff --quiet` exit 0 and `--porcelain` a non-empty `M `.
# THE ONE SANCTIONED BYPASS, AND IT IS NAMED. `probe-floor-checker-planted-
# defect.sh` is the negative control FOR this file: it plants a defect into the
# subject on purpose and needs this control to measure the planted version.
# It used to get that by STAGING the plant, because the guard here was
# `git diff --quiet` and `git add` made the worktree match the index - the
# blindness was the mechanism, written down in that probe's header as if it
# were a technique. Widening the guard broke it, which is how the coupling was
# found. An opt-in the caller must set BY NAME is the same capability with the
# dependency declared, so the next person to harden this guard sees who relies
# on it instead of discovering it from a red probe.
if [ "${ROW_FLOOR_CONTROL_ALLOW_PLANTED:-0}" != "1" ] &&
   [ -n "$(git -C "$REPO" status --porcelain -- "$S")" ]; then
  echo "ABORT: $S has uncommitted changes (staged or not); refusing to"
  echo "       measure someone else's tree"
  rm -f "$B"
  exit 3
fi

# THE BACKUP IS TAKEN BEFORE THE TRAP IS ARMED, and that order is the whole
# point. Armed first, an abort on the line above would fire the trap and copy
# the EMPTY file mktemp just made over the harness - a restore that destroys
# the thing it restores. Caught by reading, before this script ever ran.
cp "$S" "$B"
trap 'cp "$B" "$S"; rm -f "$B" "$B.out"' EXIT

# The anchor must be unique and present BEFORE the deletion. A row that was
# already renamed would otherwise delete nothing and pass for the wrong reason.
ANCHOR='report "E. git is not on PATH at all" "$WORK/E" "$WORK/nogit"'
n=$(grep -Fc -- "$ANCHOR" "$S")
echo "anchor occurrences: $n (must be exactly 1)"
[ "$n" -eq 1 ] || { echo "ABORT: the anchor is not unique - repoint it"; exit 9; }

grep -vF -- "$ANCHOR" "$B" > "$S"
if cmp -s "$S" "$B"; then
  echo "ABORT: the deletion did NOT land - the file is unchanged"
  exit 9
fi
echo "deletion landed: $(( $(wc -l < "$B") - $(wc -l < "$S") )) line(s) removed"

echo "--- running the harness with 4 of its 5 rows ---"
PYTHONDONTWRITEBYTECODE=1 bash "$S" > "$B.out" 2>&1
rc=$?
# THE CANONICAL LINE, PARSED AND ASSERTED ON. Task #107.
#
# WHAT USED TO BE HERE, and why it was worse than its sibling:
#
#     grep -E '^########## [0-9]+/[0-9]+ ROWS|LOST ROWS' "$B.out"
#
# Two hand-kept prose shapes - the defect #107 exists to delete - and, unlike
# the same list in `check-row-floor-controls.sh`, NOTHING ASSERTED ON IT. Its
# output was displayed and then discarded; the verdict below rested on `rc`
# alone. So a harness that reworded its floor message, or printed no floor
# message at all, produced a BLANK line here and still reached
# "CONTROL FIRED" - the exact shape task #102 caught in the plural file,
# standing unfixed in the singular one because the fix was applied to the
# instance that was reported rather than to its sibling.
#
# It now reads the one canonical line and asserts on its fields, so the
# evidence and the verdict come from the same source.
RESULT=$(grep -E "^HARNESS-RESULT name=check-u15-gate-amputation\.sh " "$B.out" | tail -1)
echo "${RESULT:-<the harness printed no canonical line at all>}"
echo "exit with a deleted row: $rc (must be 1)"

field() { printf '%s\n' "$1" | tr ' ' '\n' | sed -n "s/^$2=//p"; }
FLOOR=$(grep -oE '^[[:space:]]*ROW_FLOOR=[0-9]+[[:space:]]*$' "$B" | grep -oE '[0-9]+')
bad=0
if [ -z "$RESULT" ]; then
  echo "::error::the harness printed NO canonical result line. A missing verdict"
  echo "         is not a passing one - nothing here can say the floor fired."
  bad=1
else
  [ "$(field "$RESULT" status)" = "breach" ] || {
    echo "::error::status=$(field "$RESULT" status), wanted breach - the floor"
    echo "         comparison did not fire, or the harness never reached it."
    bad=1; }
  [ "$(field "$RESULT" floor)" = "$FLOOR" ] || {
    echo "::error::the harness reported floor=$(field "$RESULT" floor) but its"
    echo "         source declares ROW_FLOOR=$FLOOR."
    bad=1; }
  # ONE row was deleted, so the reported count must be one BELOW the floor.
  # This is the claim an impossible-floor run cannot reach: it says the counter
  # tracks rows, not merely that some comparison went off.
  [ "$(field "$RESULT" rows)" = "$((FLOOR - 1))" ] || {
    echo "::error::the harness reported rows=$(field "$RESULT" rows) after one row"
    echo "         was deleted; with floor $FLOOR it must report $((FLOOR - 1))."
    echo "         The counter does not track rows."
    bad=1; }
fi

cp "$B" "$S"
if cmp -s "$S" "$B"; then echo "restored: byte-identical to the backup"; fi
git -C "$REPO" diff --quiet -- "$S" \
  && echo "restored: and identical to the commit" \
  || { echo "::error::RESTORE FAILED - $S still differs from HEAD"; exit 9; }

rm -f "$B.out"
[ "$rc" -eq 1 ] || { echo "::error::CONTROL DID NOT FIRE - the floor let a lost row through"; bad=1; }
[ "$bad" -eq 0 ] || exit 1
echo "CONTROL FIRED: a deleted row is caught by the floor, which reported"
echo "               rows=$((FLOOR - 1)) floor=$FLOOR status=breach and exited $rc."
