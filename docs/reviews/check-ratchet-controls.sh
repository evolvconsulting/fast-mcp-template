#!/usr/bin/env bash
# Controls for the two ratchets that replaced the two fixed floors:
#   docs/reviews/check-coverage-ratchet.py   (was fail_under = 80)
#   docs/reviews/check-mypy-ratchet.py       (was strict = true, as a gate)
#
# THE RISK THESE ARMS ADDRESS IS SPECIFIC. Converting a floor to a ratchet
# is one keystroke away from converting it to NOTHING - and a gate that
# passes everything looks exactly like a gate that passes. So the arms
# below never ask "is it green?"; each plants a REGRESSION and requires the
# ratchet to go red, then plants an IMPROVEMENT and requires it to go red
# the other way, with a healthy arm in between so the refusals are not
# just a checker refusing everything.
#
# A "MEASURED" ARM IS NOT A CONTROL. The coverage arms build their own
# coverage.json rather than running pytest, so the input under test is the
# thing this checker actually reads and the arm cannot pass by accident on
# whatever the suite happened to do.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

arms=0
passed=0

# $1 arm name, $2 tree dir, $3 script, $4 expected rc
run_arm() {
  local name=$1 dir=$2 script=$3 want=$4 got
  arms=$((arms + 1))
  (cd "$dir" && python3 "$script") >"$WORK/out" 2>&1
  got=$?
  if [ "$got" -eq "$want" ]; then
    passed=$((passed + 1))
    printf 'PASS  %-40s rc=%s (wanted %s)\n' "$name" "$got" "$want"
  else
    printf 'FAIL  %-40s rc=%s (wanted %s)\n' "$name" "$got" "$want"
    sed 's/^/        /' "$WORK/out"
  fi
}

# =====================================================================
# COVERAGE RATCHET
# =====================================================================
CHECKER=docs/reviews/check-coverage-ratchet.py

# $1 name, $2 measured percent, $3 baseline ("NONE" to omit the file)
cov_tree() {
  local dir="$WORK/cov-$1"
  mkdir -p "$dir/docs/reviews"
  cp "$ROOT/$CHECKER" "$dir/docs/reviews/"
  printf '{"totals": {"percent_covered": %s, "num_statements": 500}}\n' "$2" \
    >"$dir/coverage.json"
  if [ "$3" != "NONE" ]; then printf '%s\n' "$3" >"$dir/docs/coverage-baseline.txt"; fi
  echo "$dir"
}

# A1. The healthy arm: measurement equals baseline.
run_arm "COV A1 at baseline" "$(cov_tree hold 80.00 80.00)" "$CHECKER" 0
# A2. THE REGRESSION. This is what fail_under used to be for, and it must
# survive the conversion to a ratchet.
run_arm "COV A2 REGRESSED 80 -> 72" "$(cov_tree drop 72.00 80.00)" "$CHECKER" 1
# A3. A LOW BASELINE STILL RATCHETS. The subject of the real adoption sat
# at 7.45%; the whole claim of this change is that such a repo gets a
# working gate rather than a permanent red. Prove the gate still bites
# there - otherwise "usable on any repo" means "inert on a bad one".
run_arm "COV A3 7.45 baseline, drop to 6" "$(cov_tree low 6.00 7.45)" "$CHECKER" 1
run_arm "COV A3b 7.45 baseline, held" "$(cov_tree lowok 7.45 7.45)" "$CHECKER" 0
# A4. IMPROVEMENT IS ALSO A FAILURE, so the baseline cannot silently rot.
run_arm "COV A4 improved, must re-record" "$(cov_tree up 91.00 80.00)" "$CHECKER" 1
# A5. NO BASELINE is a task (2), never a pass.
run_arm "COV A5 no baseline recorded" "$(cov_tree none 80.00 NONE)" "$CHECKER" 2
# A6. ZERO STATEMENTS reports 100% and must refuse as an empty population.
zero="$WORK/cov-zero"; mkdir -p "$zero/docs/reviews"
cp "$ROOT/$CHECKER" "$zero/docs/reviews/"
printf '{"totals": {"percent_covered": 100.0, "num_statements": 0}}\n' >"$zero/coverage.json"
printf '80.00\n' >"$zero/docs/coverage-baseline.txt"
run_arm "COV A6 zero statements = empty pop" "$zero" "$CHECKER" 3
# A7. NO coverage.json at all is a broken instrument, not a green.
noreport="$WORK/cov-noreport"; mkdir -p "$noreport/docs/reviews"
cp "$ROOT/$CHECKER" "$noreport/docs/reviews/"
printf '80.00\n' >"$noreport/docs/coverage-baseline.txt"
run_arm "COV A7 no coverage.json" "$noreport" "$CHECKER" 3

# =====================================================================
# MYPY RATCHET
# =====================================================================
MCHECK=docs/reviews/check-mypy-ratchet.py

# A REAL mypy RUN, not a fake. $1 name, $2 python source, $3 baseline body
# ("NONE" to omit). The tree gets its own mypy config so strictness is the
# thing under test rather than something inherited from the parent repo.
mypy_tree() {
  local dir="$WORK/mypy-$1"
  mkdir -p "$dir/docs/reviews" "$dir/src"
  cp "$ROOT/$MCHECK" "$dir/docs/reviews/"
  printf '%s\n' "$2" >"$dir/src/thing.py"
  printf '[tool.mypy]\nstrict = true\nfiles = ["src"]\n' >"$dir/pyproject.toml"
  if [ "$3" != "NONE" ]; then printf '%b' "$3" >"$dir/docs/mypy-baseline.txt"; fi
  echo "$dir"
}

CLEAN='def f(x: int) -> int:
    return x'
DIRTY='def f(x):
    return x'

# B1. Clean code, empty baseline. An EMPTY baseline is a real measurement
# (a type-clean repo) and must not read as "no baseline".
run_arm "MYPY B1 clean, empty baseline" "$(mypy_tree clean "$CLEAN" '# empty\n')" "$MCHECK" 0
# B2. THE REGRESSION. An untyped def appears where the baseline had none.
# This is the arm that proves the ratchet did not become a no-op.
run_arm "MYPY B2 NEW error vs empty baseline" "$(mypy_tree new "$DIRTY" '# empty\n')" "$MCHECK" 1
# B3. THE INHERITED ERROR IS TOLERATED - the entire purpose. Same dirty
# file, but the baseline records it. Without B2 beside it this arm would
# be indistinguishable from a checker that never fails.
run_arm "MYPY B3 error IS in the baseline" \
  "$(mypy_tree known "$DIRTY" 'src/thing.py\tno-untyped-def\t1\n')" "$MCHECK" 0
# B4. FIXED, so the baseline must shrink. Fails the other way.
run_arm "MYPY B4 fixed, baseline must shrink" \
  "$(mypy_tree fixed "$CLEAN" 'src/thing.py\tno-untyped-def\t1\n')" "$MCHECK" 1
# B5. NO BASELINE is a task (2), never a pass.
run_arm "MYPY B5 no baseline recorded" "$(mypy_tree nobase "$CLEAN" NONE)" "$MCHECK" 2

echo
echo "arms=$arms passed=$passed"
[ "$arms" -eq "$passed" ] || exit 1
# ARM FLOOR. Thirteen arms are declared; fewer is a defect in this file, not
# a green.
[ "$arms" -eq 13 ] || { echo "ARM FLOOR: expected 13 arms, ran $arms"; exit 1; }
echo "ALL ARMS FIRED"
