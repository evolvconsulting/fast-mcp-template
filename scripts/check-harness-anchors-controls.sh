#!/usr/bin/env bash
# AMPUTATION harness for scripts/check-harness-anchors.py.
#
# The static anchor checker exists to notice that a harness stopped checking.
# Its own failure mode is the one it hunts: it reports OK, and it reports OK
# because a parser shape stopped matching rather than because the anchors are
# sound. A checker that has only ever passed is indistinguishable from one that
# cannot fail, so every row here DELETES one of its behaviours and requires it
# to stop finding a defect it finds intact.
#
# Rows 1-2 are POSITIVE CONTROLS on the checker's subject: break the real source
# and require exit 1. Rows 3+ are amputations of the checker: break the source
# AND delete the rule that notices, then require exit 0. A row that stays red
# after its rule is deleted is a row whose rule was never what found the defect.
#
# EVERYTHING RUNS IN A COPY. This harness never edits the working tree - two
# commits on this project captured an amputated src/ because a harness was
# killed mid-run, and `git status` after a run is the check that catches it.
set -uo pipefail

# THE ONE CANONICAL RESULT LINE (task #107). This arms an EXIT trap that prints
# `HARNESS-RESULT name=... rows=... floor=... status=refused` on ANY exit, so an
# abort cannot render identically to a pass. `harness_result_ran` below upgrades
# it to ok/breach from the real exit code. The format lives in the sourced file
# and nowhere else - the shape lists it replaces are why.
# shellcheck source=lib/harness-result.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/harness-result.sh"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECKER_REL="scripts/check-harness-anchors.py"
WORK="$(mktemp -d)"
trap 'harness_result_emit; rm -rf "$WORK"' EXIT

export PYTHONDONTWRITEBYTECODE=1

FIRED=0
TOTAL=0

# A pristine copy of everything the checker reads. Rebuilt per row, so no row
# can see another row's edits.
#
# THE UNIT OF STAGING IS THE TREE, not a named pair of directories. This copied
# `scripts` and `src` and nothing else, which was true of what the anchors
# pointed at on the day it was written. The moment the checker learned to read
# `sed -i`, U0's rows arrived pointing at `.env.example`, `.gitignore`,
# `pyproject.toml` and `tests/conftest.py` - none of them staged - and five of
# seven rows went red reporting "target file does not exist" about files that
# exist. The failure was in this function, not in anything under test.
#
# That is the same defect check-u0-test-controls.sh has now hit FIVE times and
# whose comment is three paragraphs long: a hand-kept list of paths selects for
# the path nobody thought of. `git ls-files` is the authority, so the next
# anchor into a new file needs no edit here.
build_tree() {
  local dest="$1"
  rm -rf "$dest"
  mkdir -p "$dest"
  local n
  n=$(cd "$REPO" && git ls-files | wc -l)
  [ "$n" -gt 0 ] || { echo "  STAGING CONTROL: git ls-files returned nothing"; return 1; }
  (cd "$REPO" && git ls-files -z | tar --null -cf - -T -) | (cd "$dest" && tar -xf -) || return 1
  # Positive control on the staging itself: a copy that silently contains
  # nothing produces row failures that read exactly like real findings.
  local probe
  for probe in scripts/check-harness-anchors.py src pyproject.toml; do
    [ -e "$dest/$probe" ] || { echo "  STAGING CONTROL: $probe missing from the copy"; return 1; }
  done
}

# break_source <tree> - reflow a comment INSIDE a live anchor, which is exactly
# what B49b did to U3's M8. Derived from the checker's own output rather than
# hard-coded: the first shell-arg anchor in U3's amputation harness that spans
# more than one line is the subject, so this control cannot rot into pointing at
# a row that no longer exists.
break_source() {
  local tree="$1"
  python3 - "$tree" <<'PY'
import pathlib, sys
tree = pathlib.Path(sys.argv[1])
target = tree / "src/fast_mcp_template/audit.py"
s = target.read_text()
old = "        return ATTRIBUTION_UNAVAILABLE if self.transport is Transport.STDIO else None"
if s.count(old) != 1:
    print(f"CONTROL SETUP FAILED: the subject line is not unique ({s.count(old)} hits)")
    sys.exit(3)
# The same shape a reflow produces: the statement wrapped across two lines. The
# code is equivalent; only the TEXT the anchor matches on has changed.
new = ("        return (\n"
       "            ATTRIBUTION_UNAVAILABLE if self.transport is Transport.STDIO else None\n"
       "        )")
target.write_text(s.replace(old, new))
PY
}

# break_sed_anchor <tree> - invalidate one of U0's `sed -i` anchors in the copy.
#
# The SUBJECT IS DERIVED, never named here. The checker itself is imported and
# asked which sed anchors it reads; the first one is taken, the text it matches
# in its target file is found, and a character is inserted into the middle of
# THAT MATCH. So the mutation is guaranteed to invalidate the anchor whatever
# the anchor currently is, and this row cannot rot into breaking a pattern no
# row uses any more - which is exactly how the first version of
# probe-bash-namespace-amputation.sh went vacuous within the hour.
#
# Asking the checker to pick the subject is safe for a POSITIVE control: it
# chooses WHERE to break the tree, and must then independently report the break.
# A checker that picks a row and then cannot see the damage still fails here.
break_sed_anchor() {
  local tree="$1"
  python3 - "$tree" <<'PY'
import importlib.util, pathlib, re, sys

tree = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location(
    "anchors", tree / "scripts/check-harness-anchors.py"
)
mod = importlib.util.module_from_spec(spec)
# REGISTERED BEFORE EXEC, not after. `@dataclass` resolves its annotations
# through `sys.modules[cls.__module__]`, so executing this module unregistered
# dies inside dataclasses.py with an AttributeError about NoneType - nothing
# that names the real cause. Measured, not anticipated.
sys.modules["anchors"] = mod
spec.loader.exec_module(mod)

picked = None
for h in sorted((tree / "scripts").glob("check-*.sh")):
    if h.name.startswith("check-harness-anchors"):
        continue
    for a in mod.collect(h)[0]:
        if a.shape == "sed-bre":
            picked = a
            break
    if picked:
        break

if picked is None:
    print("CONTROL SETUP FAILED: the checker reads no `sed -i` anchors at all")
    sys.exit(3)

target = tree / picked.target
text = target.read_text()
hits = list(re.finditer(picked.text, text, re.M))
if len(hits) != 1:
    print(f"CONTROL SETUP FAILED: {picked.target} has {len(hits)} hits, wanted 1")
    sys.exit(3)
m = hits[0]
matched = m.group(0)
mangled = matched[: len(matched) // 2] + "ZZ" + matched[len(matched) // 2 :]
target.write_text(text[: m.start()] + mangled + text[m.end() :])
if len(re.findall(picked.text, target.read_text(), re.M)) != 0:
    print("CONTROL SETUP FAILED: the anchor still matches after the mutation")
    sys.exit(3)
PY
}

# break_widened_anchor <tree> <old> <new> - break an anchor that ONLY the rule
# `<old>` can see, deriving WHICH anchor that is from the rule itself.
#
# WHY IT IS DERIVED THIS WAY. A widening is unprovable unless something breaks
# an anchor the OLD selector could not see and the new one can. Naming that
# anchor here would be a hand-kept list of one, and it would rot the first time
# a row moved. So the subject is computed: the checker is asked for its anchors,
# then asked again with the rule under test deleted, and the anchors that
# VANISH are exactly the ones that rule is responsible for. The first of those
# is broken in the copy.
#
# The vacuity guard is the point of the exercise. If deleting the rule removes
# no anchors at all, the widening is not doing anything and this prints so
# rather than passing - a widening that leaves the count unchanged did nothing,
# and a control that cannot tell those apart is the defect one level up.
break_widened_anchor() {
  local tree="$1" old="$2" new="$3"
  TREE="$tree" REL="$CHECKER_REL" OLD="$old" NEW="$new" python3 - <<'PY'
import importlib.util, os, pathlib, re, sys

tree = pathlib.Path(os.environ["TREE"])
rel = os.environ["REL"]
old, new = os.environ["OLD"], os.environ["NEW"]


def anchors_of(path):
    # REGISTERED BEFORE EXEC, and under a FRESH name each time: `@dataclass`
    # resolves its annotations through `sys.modules[cls.__module__]`, and
    # reusing one name would hand the second load the first module's globals.
    name = f"anchors_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    out = []
    for h in sorted((tree / "scripts").glob("check-*.sh")):
        if h.name.startswith("check-harness-anchors"):
            continue
        out.extend(mod.collect(h)[0])
    return out


checker = tree / rel
src = checker.read_text()
if src.count(old) != 1:
    print(f"    CONTROL SETUP FAILED: the rule is not unique ({src.count(old)} hits)")
    sys.exit(3)

# The amputated checker lives beside the real one, so both are read from the
# SAME tree and any difference is the rule, not the tree.
maimed = checker.with_name("cha-amputated.py")
maimed.write_text(src.replace(old, new))

full = anchors_of(checker)
reduced = anchors_of(maimed)
maimed.unlink()

seen = {(a.harness, a.line, a.shape, a.target, a.text) for a in reduced}
lost = [a for a in full if (a.harness, a.line, a.shape, a.target, a.text) not in seen]
if not lost:
    print("    CONTROL SETUP FAILED: deleting this rule removes NO anchors, so")
    print("    the widening it represents does nothing and this row proves nothing.")
    sys.exit(3)

def spans(anchor, text):
    """Where this anchor matches `text`, by the same rule the checker uses."""
    if anchor.shape in ("py-regex", "sed-bre"):
        flags = re.S if anchor.shape == "py-regex" else re.M
        return [m.span() for m in re.finditer(anchor.text, text, flags)]
    out, i = [], text.find(anchor.text)
    while i != -1:
        out.append((i, i + len(anchor.text)))
        i = text.find(anchor.text, i + 1)
    return out


# TWO THINGS HAVE TO HOLD, and the first version of this checked NEITHER. It
# spliced `ZZ` into the middle of the match and declared the anchor broken,
# and the harness reported three survivors that were all faults in here:
#
#   THE BREAK MUST ACTUALLY BREAK IT. Row H's anchor is a regex with `.*?`
#   in it, so a character dropped in the middle lands inside the wildcard
#   and the pattern still matches. The insertion point is searched for now,
#   and a candidate whose anchor cannot be invalidated at all is passed
#   over rather than reported as broken.
#
#   THE BREAK MUST BE ISOLATED. The first lost anchor was
#   `"TOOL_REQUIREMENTS: Final[dict[str, tuple[str, ...]]] = {"`, which is
#   also the opening of a `re.sub` pattern the OLD selector already read.
#   Breaking it breaks both, so the amputated checker stayed red and the
#   row read as a survivor while the widening was fine. A subject is only
#   usable if no anchor that SURVIVES the amputation matches the same text.
target = None
for a in lost:
    text = (tree / a.target).read_text()
    found = spans(a, text)
    if not found:
        continue
    start, end = found[0]
    mangled = None
    for pos in range(start, end + 1):
        cand = text[:pos] + "ZZ" + text[pos:]
        if not spans(a, cand):
            mangled = cand
            break
    if mangled is None:
        continue
    collateral = [
        o
        for o in reduced
        if o.target == a.target and spans(o, text) and not spans(o, mangled)
    ]
    if collateral:
        continue
    target = tree / a.target
    target.write_text(mangled)
    print(f"    subject: {a.harness}:{a.line} [{a.shape}] -> {a.target}")
    break

if target is None:
    print("    CONTROL SETUP FAILED: none of the anchors this rule adds could be")
    print("    broken without also breaking one the amputated checker still reads.")
    sys.exit(3)
PY
}

# amputate_checker <tree> <old> <new> - delete one rule from the checker.
amputate_checker() {
  local tree="$1" old="$2" new="$3"
  OLD="$old" NEW="$new" FILE="$tree/$CHECKER_REL" python3 - <<'PY'
import os, pathlib, sys
p = pathlib.Path(os.environ["FILE"])
s = p.read_text()
old, new = os.environ["OLD"], os.environ["NEW"]
if s.count(old) != 1:
    print(f"    ANCHOR NOT UNIQUE ({s.count(old)} hits) in the checker", file=sys.stderr)
    sys.exit(1)
p.write_text(s.replace(old, new))
PY
}

# row <label> <want_rc> <break?> [old new] - run the checker in a fresh tree.
row() {
  local label="$1" want="$2" dobreak="$3"; shift 3
  TOTAL=$((TOTAL + 1))
  local tree="$WORK/t$TOTAL"
  build_tree "$tree" || { echo "  $label: STAGING FAILED"; return; }

  case "$dobreak" in
    yes) break_source "$tree" || { echo "  $label: SETUP FAILED"; return; } ;;
    sed) break_sed_anchor "$tree" || { echo "  $label: SETUP FAILED"; return; } ;;
    # `widen` breaks an anchor only the rule in $1 can see. The SAME pair is
    # passed to both arms of a widening: the positive arm adds a third word so
    # the amputation below is skipped, and the amputation arm passes two so it
    # fires. Both arms rebuild the tree and re-derive the subject, which is
    # deterministic, so they are provably breaking the same anchor.
    widen) break_widened_anchor "$tree" "$1" "$2" || { echo "  $label: SETUP FAILED"; return; } ;;
  esac

  if [ "$#" -eq 2 ]; then
    local backup="$WORK/backup$TOTAL"
    cp "$tree/$CHECKER_REL" "$backup"
    if ! amputate_checker "$tree" "$1" "$2"; then
      echo "  $label: DID NOT LAND - the checker anchor moved. Fix this harness."
      return
    fi
    # LANDED? `cmp` against the backup, never `git diff`: the copy is UNTRACKED,
    # and `git diff` reports NO DIFFERENCE for an untracked file whatever it
    # contains. Four rows once reported "did not land" when all four had.
    if cmp -s "$tree/$CHECKER_REL" "$backup"; then
      echo "  $label: DID NOT LAND (file unchanged) - this row proves nothing"
      return
    fi
  fi

  local out rc
  out=$(cd "$tree" && python3 "$CHECKER_REL" 2>&1); rc=$?
  if [ "$rc" -eq "$want" ]; then
    FIRED=$((FIRED + 1))
    echo "  FIRED    $label (exit $rc, wanted $want)"
  else
    echo "  SURVIVED $label (exit $rc, wanted $want)"
    printf '%s\n' "$out" | tail -4 | sed 's/^/      /'
  fi
}

echo "########## POSITIVE CONTROLS - the checker's subject, intact checker"

row "P1 an intact tree passes" 0 no
row "P2 a reflowed line inside a live anchor is caught" 1 yes

# Shape D's subject. U0's rows are sed PATTERNS, not string literals, and until
# the checker learned to read them all eleven were invisible - it named the
# harness as UNREAD rather than counting it clean, which is the only reason this
# was a task and not an incident.
row "P3 an invalidated sed -i anchor is caught" 1 sed

echo
echo "########## AMPUTATIONS - the same broken tree, one rule deleted per row"

# The uniqueness rule itself. Without it nothing compares the hit count at all.
row "A1 the hit-count comparison is deleted" 0 yes \
  'if hits != 1:' \
  'if False:'

# `!= 1` weakened to `> 1`: catches the ambiguous anchor and MISSES the stale
# one. This is the specific half that B49b's failure needed.
row "A2 zero hits is no longer a failure, only ambiguity is" 0 yes \
  'if hits != 1:' \
  'if hits > 1:'

# The shell-arg shape, which is where the reflowed anchor lives.
row "A3 the shell-helper shape parses nothing" 0 yes \
  '    carriers = {h: pb for h, pb in sigs.items() if "old" in pb[0]}' \
  '    carriers = {}'

# The verdict. If the exit code is not derived from the findings, printing them
# is decoration - the same defect as a gate that greps and ignores the result.
row "A4 findings are printed but the exit code ignores them" 0 yes \
  '    if stale:
        print(f"FAIL: {len(stale)} of {total} anchors do not resolve uniquely.")
        return 1' \
  '    if stale:
        print(f"FAIL: {len(stale)} of {total} anchors do not resolve uniquely.")'

# The sed shape, which is where the invalidated pattern lives. Without this row
# shape D is a rule that has never been shown to be what finds anything.
row "A5 the sed -i shape parses nothing" 0 sed \
  '    d_anchors, d_seen = _shape_d(path.name, src, variables)' \
  '    d_anchors, d_seen = ([], 0)'

echo
echo "########## WIDENINGS - each proved by the anchor only it can see"

# Task #167. Three selector limits made live anchors invisible at 22c9873, all
# three in check-u1-boot-amputation.sh: `re.subn` (row H), and the
# index-and-slice splices (rows K and M) whose heredocs the old body-text gate
# skipped WHOLE. A widening that nothing breaks is a widening nobody can tell
# from a no-op, so each gets a PAIR: the anchor only the new rule can see is
# broken, the real checker must report it, and the same tree with that one rule
# deleted must go green again.
#
# WHICH anchor gets broken is derived from the rule (see break_widened_anchor),
# and a rule whose deletion removes no anchors fails the row instead of passing
# it.
#
# The pair is written ONCE per widening and passed to both arms, so the `a` row
# and the `b` row cannot drift apart into testing two different rules.
SUBN_OLD='                and node.func.attr in ("sub", "subn")'
SUBN_NEW='                and node.func.attr == "sub"'
SPLICE_OLD='                and node.func.attr in ("index", "find", "count")'
SPLICE_NEW='                and node.func.attr in ("__no_such_method__",)'
GATE_OLD='        if "python3" not in head:'
GATE_NEW='        if ".replace(" not in body and "re.sub(" not in body:'

row "W1a an invalidated re.subn anchor is caught" 1 widen "$SUBN_OLD" "$SUBN_NEW" keep
row "W1b without the re.subn rule the same break passes" 0 widen "$SUBN_OLD" "$SUBN_NEW"

row "W2a an invalidated index-and-slice anchor is caught" 1 widen "$SPLICE_OLD" "$SPLICE_NEW" keep
row "W2b without the index-and-slice rule the same break passes" 0 widen "$SPLICE_OLD" "$SPLICE_NEW"

row "W3a an anchor in a heredoc the old prose gate skipped is caught" 1 widen "$GATE_OLD" "$GATE_NEW" keep
row "W3b with the prose gate back the same break passes" 0 widen "$GATE_OLD" "$GATE_NEW"

echo
echo "########## FLOOR - a shape can vanish with every remaining anchor sound"

# A2-A4 break the tree; this one does NOT. It deletes a whole parser shape from
# an INTACT tree, so every anchor that still parses resolves perfectly and the
# checker reports OK on a fraction of its coverage. Only the floor sees it.
TOTAL=$((TOTAL + 1))
tree="$WORK/floor"
build_tree "$tree" || echo "  F1: STAGING FAILED"
cp "$tree/$CHECKER_REL" "$WORK/floor-backup"
if amputate_checker "$tree" \
     '    c_anchors, c_seen = _shape_c(path.name, src, variables)' \
     '    c_anchors, c_seen = ([], 0)' \
   && ! cmp -s "$tree/$CHECKER_REL" "$WORK/floor-backup"; then
  # NOT `--quiet`: that flag suppresses the `anchors resolved:` line, which is
  # the line the floor below is read from. The first version of this derivation
  # kept it and reported "could not read the intact anchor count" - loudly,
  # which is the only reason it is not still here silently reading an empty
  # string.
  before=$(cd "$REPO" && python3 "$CHECKER_REL" 2>&1)
  # THE FLOOR IS DERIVED, NEVER RETYPED. This line read `--floor 154`, a second
  # copy of a number whose one home is ci.yml - in the very harness that exists
  # to prove the floor works. Adding eleven anchors would have left it passing
  # for the wrong reason: 154 is below the new intact count, so the row would
  # have gone green whether or not the deleted shape mattered. It is now read
  # back out of the intact run above, so it cannot disagree with the tree.
  intact=$(printf '%s\n' "$before" | sed -n 's/^anchors resolved: //p')
  case "$intact" in
    ''|*[!0-9]*) intact=0 ;;
  esac
  unfloored=$(cd "$tree" && python3 "$CHECKER_REL" 2>&1); un_rc=$?
  floored=$(cd "$tree" && python3 "$CHECKER_REL" --floor "$intact" 2>&1); fl_rc=$?
  if [ "$intact" -eq 0 ]; then
    echo "  SURVIVED F1: the intact anchor count could not be read, so there is"
    echo "           no floor to test with. This row proves nothing."
  elif [ "$un_rc" -eq 0 ] && [ "$fl_rc" -eq 1 ]; then
    FIRED=$((FIRED + 1))
    echo "  FIRED    F1 a deleted shape passes WITHOUT the floor (exit 0) and fails WITH it (exit 1)"
    printf '%s\n' "$unfloored" | grep -E '^(anchors resolved|OK)' | sed 's/^/      no floor:   /'
    printf '%s\n' "$floored" | grep -E '^FAIL' | sed 's/^/      with floor: /'
    printf '%s\n' "$before" | sed 's/^/      intact:     /'
  else
    echo "  SURVIVED F1 (no-floor exit $un_rc wanted 0, floored exit $fl_rc wanted 1)"
  fi
else
  echo "  F1: DID NOT LAND - the shape-C call site moved. Fix this harness."
fi

echo
echo "$FIRED/$TOTAL controls fired."
# The canonical result line's tally, from the SAME two counters the line
# above prints and the harness's own gate compares - never a recount.
harness_result_tally fired "$FIRED" "$TOTAL"

# THE ROW FLOOR. `FIRED -ne TOTAL` is satisfied by 0 == 0, so a harness
# whose rows were deleted - or whose rows stopped being counted - reports
# fully green. `TOTAL -eq 0` catches only the total case; PARTIAL deletion
# is the realistic shape. DERIVED: this harness printed "9/9 controls
# fired." at 20e71ed, and "15/15" once #167 added three widening PAIRS
# (a positive arm and an amputation arm each). Lowering this number is a
# visible diff that has to be defended.
ROW_FLOOR=15
# The canonical result line's numbers, taken from the harness's own
# counter and its own floor - never a second copy. Called BEFORE the
# comparison below, because that branch exits.
harness_result_ran "$TOTAL" "$ROW_FLOOR"
if [ "$TOTAL" -lt "$ROW_FLOOR" ]; then
  echo "::error::$TOTAL/$ROW_FLOOR ROWS - THE HARNESS LOST ROWS."
  echo "         A harness with fewer rows than its floor is green for the wrong reason."
  exit 1
fi
if [ "$FIRED" -ne "$TOTAL" ]; then
  echo "::error::$FIRED of $TOTAL fired. A SURVIVOR names a rule that is not what"
  echo "         finds the defect it claims to find. Read it before trusting it."
  exit 1
fi
