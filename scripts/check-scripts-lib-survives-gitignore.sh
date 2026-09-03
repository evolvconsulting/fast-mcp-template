#!/usr/bin/env bash
# PROOF that `scripts/lib/` survives adoption into a repo with a stock
# Python .gitignore.
#
# THE DEFECT, MEASURED 2026-09-03. GitHub's standard Python .gitignore
# carries `lib/` in its packaging block. Git applies a bare `lib/` at ANY
# DEPTH, so `scripts/lib/` - three harness libraries - was excluded in a
# real adoption. `git add -A` printed nothing, `git status` printed
# nothing, and the files were simultaneously present on disk and absent
# from git. Nothing in the tree could see it except the wiring registry,
# which refused with "3 exemption(s) name a file that does not exist".
#
# WHY THIS IS A SCRIPT AND NOT A COMMENT. The template's own tree does
# not contain `lib/`, so the template can never reproduce the defect by
# running its own gates. The bug lives at the SEAM, and the only way to
# test a seam is to build one. Each arm here creates a scratch repo with
# a stock gitignore, copies the template's `scripts/` in, and asks git
# what it actually tracks.
#
# ARM 3 IS THE ONE THAT EARNED ITS PLACE: it proves the ORDER matters,
# and the first version of the fix had the order wrong.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The three files the defect ate, derived from the template rather than
# retyped - a retyped list goes stale the day a fourth is added.
mapfile -t LIBS < <(cd "$ROOT" && git ls-files scripts/lib/ | sed 's|^scripts/lib/||')
if [ "${#LIBS[@]}" -eq 0 ]; then
  echo "SETUP FAILED: the template tracks NOTHING under scripts/lib/." >&2
  echo "Either the directory moved or this proof is already vacuous." >&2
  exit 2
fi
echo "Subject: ${#LIBS[@]} file(s) under scripts/lib/ - ${LIBS[*]}"
echo

arms=0
passed=0

# $1 = arm name, $2 = the .gitignore body, $3 = expected tracked count
arm() {
  local name=$1 ignore=$2 want=$3 dir="$WORK/$RANDOM$RANDOM" got
  arms=$((arms + 1))
  mkdir -p "$dir"
  cp -r "$ROOT/scripts" "$dir/scripts"
  printf '%s\n' "$ignore" >"$dir/.gitignore"
  git -C "$dir" init -q
  git -C "$dir" add -A >/dev/null 2>&1
  got=$(git -C "$dir" ls-files scripts/lib/ | wc -l)
  if [ "$got" -eq "$want" ]; then
    passed=$((passed + 1))
    printf 'PASS  %-44s tracked=%s (wanted %s)\n' "$name" "$got" "$want"
  else
    printf 'FAIL  %-44s tracked=%s (wanted %s)\n' "$name" "$got" "$want"
    git -C "$dir" check-ignore -v scripts/lib/* 2>&1 | sed 's/^/        /'
  fi
}

STOCK='# Byte-compiled
__pycache__/
*.py[cod]

# Distribution / packaging
build/
develop-eggs/
dist/
eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/'

TEMPLATE_TAIL='!scripts/lib/
!scripts/lib/**'

# ---------------------------------------------------------------------
# A1. THE DEFECT, REPRODUCED. Stock gitignore, no re-inclusion. If this
# arm ever reports the files tracked, the whole proof is vacuous - it
# would mean git stopped applying `lib/` at depth and there is nothing
# left to defend against.
# ---------------------------------------------------------------------
arm "A1 stock gitignore ALONE (the defect)" "$STOCK" 0

# ---------------------------------------------------------------------
# A2. THE FIX. Same stock gitignore, template's re-inclusion appended -
# which is what the template's .gitignore instructs an adopter to do.
# ---------------------------------------------------------------------
arm "A2 stock + re-inclusion AFTER" "$STOCK
$TEMPLATE_TAIL" "${#LIBS[@]}"

# ---------------------------------------------------------------------
# A3. THE ORDER IS LOAD-BEARING. Re-inclusion written BEFORE `lib/`.
# Git takes the LAST matching pattern, so this does NOTHING - and it is
# the obvious place to put it, which is why the first version of this
# fix put it there. Without this arm the .gitignore comment saying
# "these lines go at the END" would be an untested assertion.
# ---------------------------------------------------------------------
arm "A3 re-inclusion BEFORE lib/ (inert)" "$TEMPLATE_TAIL
$STOCK" 0

# ---------------------------------------------------------------------
# A4. THE TEMPLATE'S OWN .gitignore, verbatim, on a scratch tree. The
# template has no `lib/` line, so this must track everything - the arm
# that proves the fix did not somehow start EXCLUDING the directory.
# ---------------------------------------------------------------------
arm "A4 template's own .gitignore" "$(cat "$ROOT/.gitignore")" "${#LIBS[@]}"

# ---------------------------------------------------------------------
# A5. DIRECTORY-ONLY RE-INCLUSION. `!scripts/lib/` without the `**`
# form. Recorded because the two lines answer different questions and a
# future tidy-up will be tempted to delete one of them.
# ---------------------------------------------------------------------
arm "A5 !scripts/lib/ alone" "$STOCK
!scripts/lib/" "${#LIBS[@]}"

echo
echo "arms=$arms passed=$passed"
[ "$arms" -eq "$passed" ] || exit 1
# ARM FLOOR. Five arms are declared; fewer is a defect in this file.
[ "$arms" -eq 5 ] || { echo "ARM FLOOR: expected 5 arms, ran $arms"; exit 1; }
echo "ALL ARMS FIRED"
