#!/usr/bin/env bash
# Controls for check-brief-report-references.py.
#
# Every arm drives the REAL checker against FIXTURES and reads ITS exit
# code. Nothing here re-implements the rule, and nothing mutates the
# repository to watch a gate fail - a control that edits the tree it is
# checking is how a killed harness strands a mutation.
#
# The eight amputations are the load-bearing arms: each deletes one
# failure branch from a COPY of the checker and requires the matching
# positive arm to go green. A positive arm nobody has watched fail is a
# claim, not a control. A8 earned that on its first run: A3's fixture
# tripped TWO failure branches, so amputating one left the other and the
# arm proved nothing about the branch it named.
#
# A19 EARNED IT A SECOND TIME, against the fix that added it. The #199
# age display read `reason.split()[0]` and raised IndexError on an empty
# reason - the exact input #199 exists to reject. A16 could not see it,
# because the refusal it was testing fires first; A19, which removes that
# refusal, turned the expected rc=0 into a traceback at rc=1. A guard
# that holds only while its neighbour holds is not a guard, and the arm
# that found it was written to test the neighbour.
#
# Reason strings are SINGLE-quoted. A backtick inside a double-quoted
# string is command substitution, and the first version of this file ran
# `resolved` as a command - the same defect this project already has a
# rule about for commit messages, in a place the rule did not name.

set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

# THE ONE CANONICAL RESULT LINE (#107), sourced rather than re-typed.
# This harness printed its own `HARNESS-RESULT ...` by hand at first, and
# that is exactly the "second shape" the library exists to delete: it
# emitted `name=brief-report-refs-controls` where every consumer looks
# for `name=<the path it was invoked as>`, so
# `check-row-floor-controls.sh` could neutralise a row, watch this
# harness go red for the right reason, and still refuse - "the harness
# printed NO 'HARNESS-RESULT name=...' line ... A missing line is NOT a
# pass". Hand-rolling the line is what made this floor unwatchable
# (#194), not the directory it lives in.
# shellcheck source=../../scripts/lib/harness-result.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../scripts" && pwd)/lib/harness-result.sh"
CHECKER="$ROOT/docs/reviews/check-brief-report-references.py"
PY=(uv run --frozen python)

ROW_FLOOR=25
ROWS=0
FIRED=0

tmp=$(mktemp -d) || exit 3
trap 'harness_result_emit; rm -rf "$tmp"' EXIT

if [ ! -f "$CHECKER" ]; then
  echo "MUTATION TARGET NOT FOUND: $CHECKER"
  exit 3
fi

# --- fixtures -----------------------------------------------------------
# briefs/  one brief citing REVIEW-PRESENT.md and REVIEW-ABSENT.md
# tracked  a newline listing standing in for `git ls-files`
mkdir -p "$tmp/briefs"
cat > "$tmp/briefs/BRIEF-fixture.md" <<'EOF'
See `docs/reviews/REVIEW-PRESENT.md` and also REVIEW-ABSENT.md.
EOF
printf 'docs/reviews/REVIEW-PRESENT.md\nsrc/other.py\n' > "$tmp/tracked"

record() { printf '%s\n' "$@" > "$tmp/record"; }

run() {  # run <checker> -> exit code
  "${PY[@]}" "$1" --briefs "$tmp/briefs" --record "$tmp/record" \
    --tracked "$tmp/tracked" >/dev/null 2>&1
}

row() {  # row <label> <checker> <expected-rc>
  ROWS=$((ROWS + 1))
  run "$2"
  rc=$?
  if [ "$rc" -eq "$3" ]; then
    FIRED=$((FIRED + 1))
    echo "  ok   $1 (rc=$rc)"
  else
    echo "  FAIL $1 (rc=$rc, wanted $3)"
  fi
}

# Sets the global AMP. It must NOT be called as `amp=$(amputate ...)`:
# command substitution runs it in a SUBSHELL, so its ROWS increment is
# discarded and its FAIL message is captured into the variable instead
# of printed. The first version of this file did exactly that, and A11
# silently never ran - a harness losing a row is the failure this whole
# file exists to make impossible.
AMP=""
amputate() {  # amputate <name> <sed-expr> ; sets AMP, returns 0/1
  AMP="$tmp/amp-$1.py"
  sed "$2" "$CHECKER" > "$AMP"
  if cmp -s "$AMP" "$CHECKER"; then
    echo "  FAIL amputation '$1' CHANGED NOTHING - ANCHOR NOT FOUND"
    ROWS=$((ROWS + 1))
    return 1
  fi
  return 0
}

# Every arm that changes the fixture brief restores it, so an arm can
# never inherit the previous arm's world.
fixture_default() {
  cat > "$tmp/briefs/BRIEF-fixture.md" <<'EOF'
See `docs/reviews/REVIEW-PRESENT.md` and also REVIEW-ABSENT.md.
EOF
}
fixture_longer_name() {
  cat > "$tmp/briefs/BRIEF-fixture.md" <<'EOF'
See `docs/CODE-REVIEW-CHECKLIST.md`, which is not a report citation.
EOF
}

# A brief one directory down. Before #200 `cited()` used a NON-recursive
# glob, so this file was invisible and its dangling citation was free.
fixture_subdir() {
  mkdir -p "$tmp/briefs/archive"
  cat > "$tmp/briefs/archive/BRIEF-filed-away.md" <<'EOF'
See REVIEW-SUBDIR.md, which nothing tracks.
EOF
}
fixture_subdir_clear() { rm -rf "$tmp/briefs/archive"; }

echo "########## positives"

# A1 - an unrecorded dangling citation must FAIL.
record ""
row "A1 unrecorded dangling -> 1" "$CHECKER" 1

# A2 - recorded, so the same tree must PASS.
record "REVIEW-ABSENT.md  2026-09-02 recorded for the control"
row "A2 recorded -> 0" "$CHECKER" 0

# A3 - a recorded entry that RESOLVES must FAIL (the record went stale).
# BOTH lines are needed and that is the point: with only the PRESENT line
# the fixture also trips `unrecorded`, so A3 would be red for two reasons
# and its amputation would still find one of them. A8 caught exactly that
# and the first version of this arm was confounded.
record "REVIEW-PRESENT.md  2026-09-02 wrongly recorded; it is tracked" \
       'REVIEW-ABSENT.md  2026-09-02 recorded, so only resolved can fire'
row "A3 recorded-but-present -> 1" "$CHECKER" 1

# A4 - a recorded entry nothing cites must FAIL. Same isolation rule:
# REVIEW-ABSENT.md is recorded so only `unreferenced` can fire.
record "REVIEW-ABSENT.md  2026-09-02 ok" "REVIEW-NOBODY-CITES.md  2026-09-02 stale line"
row "A4 recorded-but-uncited -> 1" "$CHECKER" 1

# A5 - an unreadable listing must REFUSE (exit 2), not pass.
record "REVIEW-ABSENT.md  2026-09-02 ok"
mv "$tmp/tracked" "$tmp/tracked.hidden"
row "A5 unreadable listing -> 2 (refusal)" "$CHECKER" 2
mv "$tmp/tracked.hidden" "$tmp/tracked"

# A6 - an EMPTY listing is not the same as an unreadable one: everything
# dangles and it must FAIL, not refuse. None-vs-empty, measured.
record "REVIEW-ABSENT.md  2026-09-02 ok"
: > "$tmp/tracked"
row "A6 empty listing -> 1 (not 2)" "$CHECKER" 1
printf 'docs/reviews/REVIEW-PRESENT.md\nsrc/other.py\n' > "$tmp/tracked"

# A10 - A LONGER NAME MUST NOT MATCH ITS TAIL. This is the arm for a
# FALSE FINDING I published: `docs/CODE-REVIEW-CHECKLIST.md` exists and
# is cited by two briefs, and without a left boundary the pattern read
# it as `REVIEW-CHECKLIST.md`, which never has. The fixture cites only
# the longer name, so a correct checker sees NO report citation at all.
fixture_longer_name
record ""
row "A10 longer name not matched by its tail -> 0" "$CHECKER" 0
fixture_default

# --- #200: the PATH a brief writes is a claim ---------------------------
# A12 - the file exists, at a DIFFERENT path from the one cited. Before
# #200 the prefix was captured OUTSIDE group 1 and thrown away, so this
# passed. REVIEW-ABSENT.md is recorded so that ONLY `misplaced` can fire -
# the A8 lesson: an arm red for two reasons proves nothing about either.
printf 'docs/briefs/REVIEW-PRESENT.md\nsrc/other.py\n' > "$tmp/tracked"
record "REVIEW-ABSENT.md  2026-09-02 recorded, so only misplaced can fire"
row "A12 cited at the wrong path -> 1" "$CHECKER" 1
printf 'docs/reviews/REVIEW-PRESENT.md\nsrc/other.py\n' > "$tmp/tracked"

# --- #200: a brief one directory down --------------------------------
# A14 - the subdirectory brief cites a report nothing tracks, so a gate
# that SEES it must fail. With the old non-recursive glob the file was
# never opened and its citation cost nothing.
fixture_subdir
record "REVIEW-ABSENT.md  2026-09-02 recorded, so only the subdir citation fires"
row "A14 subdirectory brief is scanned -> 1" "$CHECKER" 1
fixture_subdir_clear

# --- #199: a recorded line must be WELL FORMED -------------------------
# Exit 2, not 1: a record that does not parse is a BROKEN INSTRUMENT, and
# the gate says nothing about the briefs until it does.
# A16 - the measured defect: a bare name, no reason at all, exited 0.
record "REVIEW-ABSENT.md"
row "A16 recorded with NO reason -> 2 (refusal)" "$CHECKER" 2

# A17 - a reason that argues something but carries no date.
record "REVIEW-ABSENT.md  the agent has not written it yet"
row "A17 recorded with no ISO date -> 2 (refusal)" "$CHECKER" 2

# A18 - THE ANTI-VACUITY ARM. A16 and A17 both refuse, so on their own
# they are equally satisfied by a checker that refuses EVERYTHING. This
# one proves a well-formed line is still admitted.
record "REVIEW-ABSENT.md  2026-09-02 in flight; the agent commits it next"
row "A18 well-formed line still ADMITTED -> 0" "$CHECKER" 0

echo "########## amputations"

# A7 - delete the unrecorded-dangling branch; A1 must go green.
if amputate unrecorded 's/^    if unrecorded:$/    if False:/'; then
  record ""
  row "A7 AMP unrecorded -> A1 survives at 0" "$AMP" 0
fi

# A8 - delete the resolved branch; A3 must go green.
if amputate resolved 's/^    if resolved:$/    if False:/'; then
  record 'REVIEW-PRESENT.md  2026-09-02 wrongly recorded; it is tracked' \
         'REVIEW-ABSENT.md  2026-09-02 recorded, so only resolved can fire'
  row "A8 AMP resolved -> A3 survives at 0" "$AMP" 0
fi

# A9 - delete the uncited branch; A4 must go green.
if amputate unreferenced 's/^    if unreferenced:$/    if False:/'; then
  record 'REVIEW-ABSENT.md  2026-09-02 ok' 'REVIEW-NOBODY-CITES.md  2026-09-02 stale line'
  row "A9 AMP unreferenced -> A4 survives at 0" "$AMP" 0
fi

# A11 - delete the LEFT BOUNDARY; A10 must go red. Without this arm the
# lookbehind can be removed and nothing notices, which is exactly how
# the false finding shipped in the first place.
#
# THE ANCHOR MOVED WITH #209 AND HAD TO. It was `/(?<!/d` - delete every
# line containing the lookbehind. That was safe while the lookbehind
# appeared once in a comment and once inside `re.compile`; now it is a
# NAMED CONSTANT that `REF` and `RECIPE` are both built from, so
# deleting the line raises NameError at import and the arm would go red
# at rc=1 for a reason that has nothing to do with the boundary. Same
# colour, different subject - which is the failure A8 named. Emptying
# the constant removes the boundary from BOTH consumers and from
# nothing else, which is the amputation this arm claims to be.
fixture_longer_name
if amputate boundary 's/^BOUNDARY = .*$/BOUNDARY = ""/'; then
  record ""
  row "A11 AMP left boundary -> A10 goes red at 1" "$AMP" 1
fi
fixture_default

# A13 - delete the wrong-path branch; A12 must go green.
if amputate misplaced 's/^    if misplaced:$/    if False:/'; then
  printf 'docs/briefs/REVIEW-PRESENT.md\nsrc/other.py\n' > "$tmp/tracked"
  record 'REVIEW-ABSENT.md  2026-09-02 recorded, so only misplaced can fire'
  row "A13 AMP misplaced -> A12 survives at 0" "$AMP" 0
  printf 'docs/reviews/REVIEW-PRESENT.md\nsrc/other.py\n' > "$tmp/tracked"
fi

# A15 - put the NON-recursive glob back; A14 must go green, because the
# subdirectory brief stops being opened at all. This amputates the fix
# itself rather than a failure branch: the defect was never a missing
# check, it was a check that never saw the file.
fixture_subdir
if amputate rglob 's/for p in sorted(briefs\.rglob("\*\.md")):/for p in sorted(briefs.glob("*.md")):/'; then
  record 'REVIEW-ABSENT.md  2026-09-02 recorded, so only the subdir citation fires'
  row "A15 AMP rglob -> A14 survives at 0" "$AMP" 0
fi
fixture_subdir_clear

# A20 - R20-N3: A5 was the only positive arm whose subject nobody had
# watched being removed. Deleting the refusal makes the None fall through
# to the unpack, so it dies with a TypeError at rc=1 rather than passing.
# R20's suggested anchor was `if names is None:`; #200 renamed that
# variable to `index`, so the sed it proposed would have matched NOTHING
# and the arm would have reported "ANCHOR NOT FOUND" instead of running.
if amputate refusal 's/^    if index is None:$/    if False:/'; then
  record 'REVIEW-ABSENT.md  2026-09-02 ok'
  mv "$tmp/tracked" "$tmp/tracked.hidden"
  row "A20 AMP refusal -> A5 dies at 1, not 0" "$AMP" 1
  mv "$tmp/tracked.hidden" "$tmp/tracked"
fi

# A19 - delete the well-formedness refusal; A16 must go green, which is
# precisely the pre-#199 behaviour R20-M3 measured: a bare name, exit 0.
if amputate wellformed 's/^        if not WELL_FORMED\.match(reason):$/        if False:/'; then
  record 'REVIEW-ABSENT.md'
  row "A19 AMP well-formedness -> A16 survives at 0" "$AMP" 0
fi

# A21 - #205: a MISSING --briefs directory must REFUSE at 2, not report
# a clean scan over nothing. `rglob` on a path that does not exist
# returns empty without erroring, so before this the checker printed
# "Briefs scanned: 0 ... rc=0" - a SUCCESS IT HAD NOT EARNED, which is a
# worse member of the family than a failure nobody reads.
record 'REVIEW-ABSENT.md  2026-09-02 ok'
ROWS=$((ROWS + 1))
rc=0
"${PY[@]}" "$CHECKER" --briefs "$tmp/no-such-dir" --record "$tmp/record" \
  --tracked "$tmp/tracked" >/dev/null 2>&1 || rc=$?
if [ "$rc" -eq 2 ]; then
  FIRED=$((FIRED + 1)); echo "  ok   A21 missing --briefs dir -> 2 (refusal) (rc=$rc)"
else
  echo "  FAIL A21 missing --briefs dir (rc=$rc, wanted 2)"
fi

# A22 - delete that refusal and A21 must stop refusing. Without this the
# guard can be removed and nothing notices. THE ANCHOR IS DERIVED FROM
# THE FILE, not copied from a report: R20-N3's suggested sed named a
# variable that had been renamed and would have matched nothing.
if amputate briefsdir 's/^    if not args\.briefs\.is_dir():$/    if False:/'; then
  # THE RECORD MUST BE EMPTY HERE. With the guard gone the scan finds no
  # briefs, so a recorded entry becomes UNCITED and the `unreferenced`
  # branch fires at rc=1 - the arm would then be red for a reason that
  # has nothing to do with the guard it names. Third time this exact
  # confound has appeared in this harness; an arm must isolate the ONE
  # branch it is about.
  record ""
  ROWS=$((ROWS + 1))
  rc=0
  "${PY[@]}" "$AMP" --briefs "$tmp/no-such-dir" --record "$tmp/record" \
    --tracked "$tmp/tracked" >/dev/null 2>&1 || rc=$?
  if [ "$rc" -eq 0 ]; then
    FIRED=$((FIRED + 1)); echo "  ok   A22 AMP briefs-dir -> A21 scans nothing at 0 (rc=$rc)"
  else
    echo "  FAIL A22 AMP briefs-dir (rc=$rc, wanted 0)"
  fi
fi

# --- #209: the PUBLISHED RECIPE and the GATE must be one population ----
# The docstring's "re-derive without trusting this file" recipe used to
# be a SECOND hand-written selector, and it drifted: no left boundary,
# so it returned `REVIEW-CHECKLIST.md` - the truncated name 1985471
# retracted, which has never been a file. Measured over docs/briefs at
# a52af14: the loose recipe 27 names, the gate 26, and the single
# difference was that phantom. `--recipe` now prints a one-liner
# composed from the SAME `BOUNDARY` and `NAME` the gate's `REF` is
# composed from, and these three arms are what stops the two ever
# disagreeing again.
#
# THE FIXTURE CARRIES BOTH TRAPS AT ONCE: the longer name whose TAIL a
# free left edge matches, and a non-`.md` file that `grep -r` reads and
# `cited()` does not.
mkdir -p "$tmp/recipe-briefs/sub"
cat > "$tmp/recipe-briefs/BRIEF-a.md" <<'EOF'
See `docs/reviews/REVIEW-PRESENT.md` and REVIEW-ABSENT.md.
Also `docs/CODE-REVIEW-CHECKLIST.md`, which is NOT a report citation.
EOF
cat > "$tmp/recipe-briefs/sub/BRIEF-b.md" <<'EOF'
Filed one directory down, citing WORKLOG-SUB.md.
EOF
cat > "$tmp/recipe-briefs/notes.txt" <<'EOF'
Not a brief, and it names FINDINGS-NOT-A-BRIEF.md.
EOF

# recipe_row <label> <checker> <same | the exact names the recipe ADDS>
#
# It runs the checker's OWN printed recipe through a real shell, so the
# subject is the published text and not a copy of it. `set -o pipefail`
# inside that shell is load-bearing: without it the pipeline's status is
# `sort`'s, so an UNSUPPORTED `-P` or a bad pattern would exit 0 with an
# empty result and read as "the gate found nothing" - the clean zero
# that explains itself. grep's rc=1 (no matches) is a legitimate answer
# and is admitted; anything above 1 is a broken instrument and the arm
# says so instead of comparing two empty files.
recipe_row() {
  ROWS=$((ROWS + 1))
  local cmd rc
  if ! cmd=$("${PY[@]}" "$2" --briefs "$tmp/recipe-briefs" --recipe 2>&1); then
    echo "  FAIL $1 - --recipe itself failed: $cmd"
    return 0
  fi
  rc=0
  bash -c "set -o pipefail; $cmd" > "$tmp/recipe.out" 2>"$tmp/recipe.err" || rc=$?
  if [ "$rc" -gt 1 ]; then
    echo "  FAIL $1 - the recipe command exited $rc (broken instrument)"
    sed 's/^/       /' "$tmp/recipe.err"
    return 0
  fi
  if ! "${PY[@]}" "$2" --briefs "$tmp/recipe-briefs" --list-names \
      > "$tmp/listnames.out" 2>/dev/null; then
    echo "  FAIL $1 - --list-names itself failed"
    return 0
  fi
  # The comparison is SET-WISE and in BOTH directions, and the expected
  # difference is NAMED. "they differ" would be satisfied by any two
  # edges being loose at once, which is how an arm ends up red for a
  # reason other than the one it claims.
  local added removed
  added=$(comm -23 "$tmp/recipe.out" "$tmp/listnames.out" | tr '\n' ' ')
  removed=$(comm -13 "$tmp/recipe.out" "$tmp/listnames.out" | tr '\n' ' ')
  added=${added% }
  removed=${removed% }
  if [ -n "$removed" ]; then
    echo "  FAIL $1 - the GATE sees names the recipe does not: $removed"
    return 0
  fi
  local want=""
  if [ "$3" != "same" ]; then want="$3"; fi
  if [ "$added" = "$want" ]; then
    FIRED=$((FIRED + 1))
    if [ "$3" = "same" ]; then
      echo "  ok   $1 (identical, $(wc -l < "$tmp/listnames.out") names)"
    else
      echo "  ok   $1 (recipe adds exactly: $added)"
    fi
  else
    echo "  FAIL $1 (recipe adds [$added], wanted [$want])"
  fi
}

# A23 - the published recipe returns EXACTLY the gate's population.
recipe_row "A23 --recipe == --list-names -> identical" "$CHECKER" same

echo "########## amputations (recipe)"

# A24 - PUT THE #209 DEFECT BACK: `-E`, no lookbehind. A23 must go red
# and the name that appears must be `REVIEW-CHECKLIST.md`, the phantom
# 1985471 retracted.
#
# IT KEEPS `--include='*.md'`, WHICH THE PRE-FIX RECIPE DID NOT HAVE.
# The real pre-fix line had BOTH edges loose, so an arm asserting only
# "they differ" would have been satisfied by the file-type edge alone
# and would have proved nothing about the boundary it names - the A8
# confound, for the third time in this file. Each arm loosens ONE edge
# and NAMES the one name that must appear.
if amputate recipe_loose "s#^RECIPE = .*\$#RECIPE = \"grep -rhoE --include='*.md' '(REVIEW|WORKLOG|FINDINGS)-[A-Za-z0-9._-]+[.]md' {briefs} | sort -u\"#"; then
  recipe_row "A24 AMP loose recipe -> A23 goes red" "$AMP" REVIEW-CHECKLIST.md
fi

# A25 - drop `--include='*.md'` and keep the selector. `grep -r` then
# reads notes.txt, which `cited()` never opens. This edge costs nothing
# TODAY - all 83 files under docs/briefs are .md - so without this arm
# it would be prose nobody could falsify.
if amputate recipe_allfiles "s#^RECIPE = .*\$#RECIPE = \"grep -rhoP '\" + BOUNDARY + NAME + \"' {briefs} | sort -u\"#"; then
  recipe_row "A25 AMP no --include -> A23 goes red" "$AMP" FINDINGS-NOT-A-BRIEF.md
fi

harness_result_tally fired "$FIRED" "$ROWS"
harness_result_ran "$ROWS" "$ROW_FLOOR"
if [ "$ROWS" -ne "$ROW_FLOOR" ]; then
  echo "::error::$ROWS rows against ROW_FLOOR=$ROW_FLOOR."
  exit 1
fi
if [ "$FIRED" -ne "$ROWS" ]; then
  echo "::error::$FIRED of $ROWS fired. Read WHICH arm failed."
  exit 1
fi
echo "$FIRED/$ROWS controls fired."
