#!/usr/bin/env bash
# Controls for docs/reviews/check-default-branch-is-triggered.py.
#
# THE CHECKER EXISTS BECAUSE A SILENT GREY LOOKED LIKE A GREEN, so a
# control that only ever sees the healthy tree would reproduce exactly
# that defect one column over. Every arm here PLANTS the damage into a
# throwaway copy of the repository and asserts the checker REFUSES it.
#
# Each arm prints its own name and the exit code it got, so a reader can
# see which arm fired rather than trusting a single tally at the end.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHECKER="docs/reviews/check-default-branch-is-triggered.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

arms=0
passed=0

# Build a throwaway tree: the workflow, plus the checker, plus a git
# repo so nothing reaches outside. $1 is the yaml to write.
plant() {
  local dir="$WORK/$1"
  rm -rf "$dir"
  mkdir -p "$dir/.github/workflows" "$dir/docs/reviews"
  cp "$ROOT/$CHECKER" "$dir/docs/reviews/"
  git -C "$dir" init -q
  echo "$dir"
}

# $1 arm name, $2 tree dir, $3 DEFAULT_BRANCH, $4 expected rc
run_arm() {
  local name=$1 dir=$2 branch=$3 want=$4 got
  arms=$((arms + 1))
  DEFAULT_BRANCH="$branch" python3 "$dir/$CHECKER" >"$WORK/out" 2>&1
  got=$?
  if [ "$got" -eq "$want" ]; then
    passed=$((passed + 1))
    printf 'PASS  %-34s rc=%s (wanted %s)\n' "$name" "$got" "$want"
  else
    printf 'FAIL  %-34s rc=%s (wanted %s)\n' "$name" "$got" "$want"
    sed 's/^/        /' "$WORK/out"
  fi
}

# ---------------------------------------------------------------------
# A1. THE HEALTHY TREE. The real workflow, told its own default branch.
# Without this arm every refusal below could be the checker refusing
# everything, which is a control that proves nothing.
# ---------------------------------------------------------------------
healthy="$(plant healthy)"
cp "$ROOT/.github/workflows/ci.yml" "$healthy/.github/workflows/ci.yml"
run_arm "A1 healthy, default=main" "$healthy" main 0

# ---------------------------------------------------------------------
# A2. THE MEASURED DEFECT, REPRODUCED. The workflow AS IT SHIPPED
# (`branches: [main]`) against a repository whose default branch is
# `dev` - the real subject of the 2026-09-03 application. That tree was
# green and its CI was off. This arm is the decisive one: it fails on
# the pre-fix workflow, which is the only way to know the checker is
# catching the thing that actually shipped rather than a tree I built
# to be caught.
# ---------------------------------------------------------------------
prefix_tree="$(plant prefix)"
sed 's|^    branches: \[main, master, dev\]$|    branches: [main]|' \
  "$ROOT/.github/workflows/ci.yml" >"$prefix_tree/.github/workflows/ci.yml"
if ! grep -qx '    branches: \[main\]' "$prefix_tree/.github/workflows/ci.yml"; then
  echo "SETUP FAILED: A2 did not restore the pre-fix trigger; its result would be vacuous." >&2
  exit 2
fi
run_arm "A2 PRE-FIX [main] vs default=dev" "$prefix_tree" dev 1

# ---------------------------------------------------------------------
# A2b. THE SAME REPOSITORY ON THE FIXED WORKFLOW. Without this arm, A2
# would be satisfied by a checker that refuses `dev` unconditionally.
# ---------------------------------------------------------------------
dev="$(plant dev)"
cp "$ROOT/.github/workflows/ci.yml" "$dev/.github/workflows/ci.yml"
run_arm "A2b POST-FIX vs default=dev" "$dev" dev 0

# ---------------------------------------------------------------------
# A3. A default branch nobody predicted. `main, master, dev` is a guess
# about the world, and this arm is the proof that the guess FAILS LOUDLY
# rather than silently when it is wrong.
# ---------------------------------------------------------------------
trunk="$(plant trunk)"
cp "$ROOT/.github/workflows/ci.yml" "$trunk/.github/workflows/ci.yml"
run_arm "A3 default=trunk, unpredicted" "$trunk" trunk 1

# ---------------------------------------------------------------------
# A4. THE REVERSE DIRECTION. The push trigger is right and a Merge-tier
# `if:` still names a literal trunk - the half of the defect that a fix
# to the trigger alone would leave behind. This is the arm that catches
# the fix rebuilding its own defect one column over.
# ---------------------------------------------------------------------
regress="$(plant regress)"
sed "s|&& github.ref == format('refs/heads/{0}', github.event.repository.default_branch)|\&\& github.ref == 'refs/heads/main'|" \
  "$ROOT/.github/workflows/ci.yml" >"$regress/.github/workflows/ci.yml"
if ! grep -q "refs/heads/main'" "$regress/.github/workflows/ci.yml"; then
  echo "SETUP FAILED: A4 planted nothing, so its result would be vacuous." >&2
  exit 2
fi
run_arm "A4 hardcoded if: reintroduced" "$regress" main 1

# ---------------------------------------------------------------------
# A5. NO PUSH FILTER AT ALL. Deleting the key is the other way to make
# the trigger stop describing the repository, and it must not read as
# "nothing to check".
# ---------------------------------------------------------------------
nofilter="$(plant nofilter)"
python3 - "$ROOT/.github/workflows/ci.yml" "$nofilter/.github/workflows/ci.yml" <<'PY'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src).read()
text = re.sub(r"\n    branches: \[[^\]]*\]\n", "\n", text, count=1)
open(dst, "w").write(text)
PY
run_arm "A5 push branches: key deleted" "$nofilter" main 1

# ---------------------------------------------------------------------
# A6. THE INSTRUMENT REFUSES RATHER THAN GUESSING. No DEFAULT_BRANCH and
# no origin/HEAD must be exit 3, never a pass. A checker that cannot see
# its subject and prints a green is the whole defect class.
# ---------------------------------------------------------------------
run_arm "A6 no default determinable" "$healthy" "" 3

echo
echo "arms=$arms passed=$passed"
[ "$arms" -eq "$passed" ] || exit 1
# ARM FLOOR. A control file that silently loses an arm reports a smaller,
# quieter, greener result. Six arms are declared here; fewer is a defect
# in this file, not a green.
[ "$arms" -eq 7 ] || { echo "ARM FLOOR: expected 7 arms, ran $arms"; exit 1; }
echo "ALL ARMS FIRED"
