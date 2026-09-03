#!/usr/bin/env bash
# Controls for docs/reviews/check-design-freeze.py.
#
# THE DEFECT THIS GUARDS was a checker that reported its own instrument
# broken when the real answer was "you have not frozen your design yet".
# Every child repository of this template opened on that message. So the
# arms here are ABOUT THE EXIT CODES, and each one plants a distinct
# reason for the checker to refuse.
#
#     0  same blob      1  design moved
#     2  not frozen yet  3  broken instrument
#
# A1/A2 are the pair that matters: the SAME missing object is exit 3 in
# a SHALLOW clone and exit 2 in a COMPLETE one. Run one without the
# other and you cannot tell whether the discriminator does anything.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHECKER="docs/reviews/check-design-freeze.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

arms=0
passed=0

# A throwaway repository with a design, one commit, and a freeze file.
# $1 = name, $2 = what to put in DESIGN-FREEZE.txt ("SELF" = the real sha).
plant() {
  local dir="$WORK/$1" freeze="$2"
  rm -rf "$dir"
  mkdir -p "$dir/docs/reviews"
  cp "$ROOT/$CHECKER" "$dir/docs/reviews/"
  printf 'the design\n' >"$dir/docs/DESIGN.md"
  git -C "$dir" init -q
  git -C "$dir" -c user.email=c@example.com -c user.name=c add -A >/dev/null
  git -C "$dir" -c user.email=c@example.com -c user.name=c commit -qm one
  if [ "$freeze" = "SELF" ]; then
    git -C "$dir" log -1 --format=%H -- docs/DESIGN.md >"$dir/docs/DESIGN-FREEZE.txt"
  else
    printf '%s\n' "$freeze" >"$dir/docs/DESIGN-FREEZE.txt"
  fi
  echo "$dir"
}

# $1 arm name, $2 tree dir, $3 expected rc
run_arm() {
  local name=$1 dir=$2 want=$3 got
  arms=$((arms + 1))
  python3 "$dir/$CHECKER" >"$WORK/out" 2>&1
  got=$?
  if [ "$got" -eq "$want" ]; then
    passed=$((passed + 1))
    printf 'PASS  %-38s rc=%s (wanted %s)\n' "$name" "$got" "$want"
  else
    printf 'FAIL  %-38s rc=%s (wanted %s)\n' "$name" "$got" "$want"
    sed 's/^/        /' "$WORK/out"
  fi
}

# A FOREIGN SHA: well-formed, 40 hex, and in no repository built here.
FOREIGN=7e9e44c09ef65be4bc28fade4af2c70612b24230

# ---------------------------------------------------------------------
# A1. THE MEASURED DEFECT. A child repository carrying the TEMPLATE's
# freeze SHA, in a complete clone. This printed "BROKEN INSTRUMENT,
# exit 3" on every child; it must now be exit 2, a task.
# ---------------------------------------------------------------------
run_arm "A1 foreign sha, complete clone" "$(plant foreign "$FOREIGN")" 2

# ---------------------------------------------------------------------
# A2. THE SAME MISSING OBJECT, SHALLOW. Still a genuine instrument
# failure - `fetch-depth: 1` really does hide a commit that exists. If
# A1 and A2 ever return the same code, the discriminator is dead and the
# fix has silently become a blanket downgrade of exit 3.
# ---------------------------------------------------------------------
shallow="$(plant shallow "$FOREIGN")"
printf '%s\n' "$FOREIGN" >"$shallow/.git/shallow"
if [ "$(git -C "$shallow" rev-parse --is-shallow-repository)" != "true" ]; then
  echo "SETUP FAILED: A2 is not a shallow clone; its result would be vacuous." >&2
  exit 2
fi
run_arm "A2 foreign sha, SHALLOW clone" "$shallow" 3

# ---------------------------------------------------------------------
# A3. THE SENTINEL. A repository that says out loud it is not frozen.
# ---------------------------------------------------------------------
run_arm "A3 UNFROZEN sentinel" "$(plant sentinel UNFROZEN)" 2

# ---------------------------------------------------------------------
# A4. EMPTY. A blank declaration compares nothing; it must not pass.
# ---------------------------------------------------------------------
run_arm "A4 empty freeze file" "$(plant empty "")" 2

# ---------------------------------------------------------------------
# A5. THE HEALTHY TREE. Without it every refusal above could be the
# checker refusing everything.
# ---------------------------------------------------------------------
run_arm "A5 frozen at its own commit" "$(plant good SELF)" 0

# ---------------------------------------------------------------------
# A6. THE DESIGN MOVED. The finding the checker was built for, which
# must NOT be swallowed by any of the new exit-2 paths.
# ---------------------------------------------------------------------
moved="$(plant moved SELF)"
printf 'the design, edited\n' >"$moved/docs/DESIGN.md"
git -C "$moved" -c user.email=c@example.com -c user.name=c commit -qam two
run_arm "A6 design moved since freeze" "$moved" 1

echo
echo "arms=$arms passed=$passed"
[ "$arms" -eq "$passed" ] || exit 1
# ARM FLOOR. Six arms are declared; fewer is a defect in this file.
[ "$arms" -eq 6 ] || { echo "ARM FLOOR: expected 6 arms, ran $arms"; exit 1; }
echo "ALL ARMS FIRED"
