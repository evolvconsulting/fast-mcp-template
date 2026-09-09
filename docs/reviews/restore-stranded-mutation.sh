#!/usr/bin/env bash
# PUT BACK A MUTATION A KILLED HARNESS STRANDED. Task #131.
#
#   docs/reviews/restore-stranded-mutation.sh [--check|--restore-only] [--repo PATH]
#
# THE PROBLEM, measured four times in one day and never once by a gate.
# A mutation harness edits a tracked file, runs a suite, and restores. SIGKILL
# runs no `trap` and no `finally`, so a harness killed mid-row leaves its
# mutation live in the working tree and nothing owns putting it back. Three of
# the four were found by an operator running `git status` out of habit; the
# fourth was found because the agent that caused it happened to be looking.
# In one of them the stranded edit had disabled every bearer-token check on the
# HTTP transport, in a tree someone was about to commit from.
#
# WHY `git status` IS NOT THE ANSWER, and this is the part that makes the tool
# worth having rather than dangerous. `git status` says the tree is DIRTY. It
# cannot say whether that dirt has an OWNER. At the moment of one of the
# incidents above, two OTHER worktrees of this repo were also dirty and both
# were entirely legitimate - probes were actively running in them. A tool that
# cleaned everything dirty would have destroyed live work. So this reads the run
# state file, not the tree, to decide whether anything is stranded at all.
#
# ============================================================================
# WHAT THIS DELIBERATELY DOES **NOT** DO. Read this before trusting it.
# ============================================================================
#
# 1. IT DOES NOT COVER HARNESSES THIS PROBE DID NOT LAUNCH. The state file is
#    written by `docs/reviews/probe-harness-exit-codes.sh`, which is the only
#    driver that currently knows both that the tree was clean before the row and
#    which harness it started. A harness run by hand, by a shell loop, or by
#    `scripts/ci-harness-gate.sh` writes NO state file, and this tool then
#    refuses to attribute the dirt rather than guessing. Two of #131's own three
#    incidents were of exactly that kind. Closing that gap means every
#    `scripts/check-*.sh` writing its own state, which is a change to a file
#    family this task does not own.
#
# 2. IT NEVER DELETES AN UNTRACKED FILE. An untracked file cannot be restored -
#    there is nothing to restore it to - and deleting one is unrecoverable. They
#    are reported and left alone.
#
# 3. IT NEVER TOUCHES THE INDEX, and refuses outright if the harness staged
#    anything. Measured and ruled twice on this project: `git checkout -- <f>`
#    restores from the INDEX, while `git checkout HEAD -- <f>` rewrites the
#    index too and SILENTLY DESTROYS staged work. This tool uses NEITHER. It
#    writes file bytes with `cp` from a blob it extracts itself, so the index is
#    not a participant - and where the index HAS moved it stops and says so,
#    because un-staging is precisely the destructive operation that ruling is
#    about.
#
# 4. IT IS NOT A LOCK. It does not stop a second harness starting. The probe's
#    own pre-flight does that, by refusing to run on a dirty tree.
#
# THE REFERENCE QUESTION MUST MATCH THE ANSWER THE RESTORE WRITES FROM - this
# project's rule, and it is why the state file records a commit sha. The sha is
# recorded at a moment when the pre-flight has PROVED worktree, index and HEAD
# all agree, so restoring to it cannot destroy staged work: at that instant
# there was none. The verification is `cmp` against the extracted blob, never
# `git diff --quiet`, because `git diff` answers a question about the index and
# the index is not what we wrote.
#
# `-e` deliberately omitted: this reads exit codes of commands expected to fail.
# See docs/adr/0023-harnesses-drop-e-from-strict-mode.md
#
# EXIT CODES, kept apart because they need different actions:
#   0  nothing is stranded, or a restore completed AND verified
#   1  a stranded mutation IS present (--check reports, changes nothing)
#   2  usage or instrument error
#   3  REFUSED - the owner is still running, or the dirt cannot be attributed
#   4  a restore was attempted and FAILED verification. The tree is NOT clean.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/harness-state.sh
. "$HERE/lib/harness-state.sh"

MODE="check"
REPO="$(cd "$HERE/../.." && pwd)"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --check)        MODE="check"; shift ;;
    --restore-only) MODE="restore"; shift ;;
    # NORMALISED, and it matters more since the `repo=` comparison landed
    # (R18-N1). `harness_state_file` keys the state path on a cksum of this
    # string and the file records it verbatim, so `--repo /x/y/` and
    # `--repo /x/y` name DIFFERENT state files for the SAME checkout and now
    # also produce a false "DIFFERENT repository" refusal. `cd`+`pwd`
    # resolves symlinks and `..` too, so the two forms cannot diverge.
    --repo)         REPO="$(cd "$2" 2>/dev/null && pwd || printf %s "${2%/}")"; shift 2 ;;
    -h|--help)
      sed -n '2,4p' "${BASH_SOURCE[0]}" >&2
      exit 2 ;;
    *) echo "::error::unknown argument: $1" >&2; exit 2 ;;
  esac
done

# PROVE THE PATH RESOLVES. A search at a path that does not exist exits
# clean-empty, which is byte-identical to a real absence - and this tool's whole
# output is an absence claim.
if [ ! -d "$REPO/.git" ] && [ ! -f "$REPO/.git" ]; then
  echo "::error::$REPO is not a git working tree (no .git). A clean result from" >&2
  echo "         a path that does not resolve is a false 'nothing stranded'." >&2
  exit 2
fi

STATE=$(harness_state_file "$REPO")
porcelain=$(git -C "$REPO" status --porcelain)

echo "repo       : $REPO"
echo "state file : $STATE"

# ---- 1. no state file: this tool has nothing to attribute dirt TO ----------
if [ ! -f "$STATE" ]; then
  if [ -z "$porcelain" ]; then
    echo "NOTHING STRANDED: no run state file, and the tree is clean."
    exit 0
  fi
  echo "::error::THE TREE IS DIRTY AND THIS TOOL CANNOT ATTRIBUTE IT." >&2
  echo "         There is no run state file, so nothing here recorded a harness" >&2
  echo "         mutating this tree. That means one of two things, and they need" >&2
  echo "         OPPOSITE actions:" >&2
  echo "           (a) these are your own legitimate edits - do nothing;" >&2
  echo "           (b) a harness NOT launched by probe-harness-exit-codes.sh" >&2
  echo "               was killed - most harnesses write no state file yet." >&2
  echo "         REFUSING TO GUESS. Measured once: two worktrees were dirty at" >&2
  echo "         the same moment as a real stranding and BOTH were legitimate," >&2
  echo "         so a tool that cleaned every dirty tree would have destroyed" >&2
  echo "         live work. Read the diff and decide:" >&2
  echo "           git -C $REPO diff" >&2
  printf '           %s\n' "$porcelain" >&2
  exit 3
fi

# ---- 2. a state file exists: who owns it, and is that owner alive? ---------
state_harness=$(sed -n 's/^harness=//p' "$STATE")
state_commit=$(sed -n 's/^commit=//p' "$STATE")
state_pid=$(sed -n 's/^pid=//p' "$STATE")
state_started=$(sed -n 's/^started_human=//p' "$STATE")
state_repo=$(sed -n 's/^repo=//p' "$STATE")

# THE STATE FILE SAYS WHICH REPOSITORY IT IS ABOUT, AND UNTIL NOW NOTHING READ
# IT. `harness_state_begin` has always written `repo=`, but the path to the file
# is `$TMPDIR/fmj-harness-state-<cksum of the repo path>.state` - and `cksum` is
# a 32-bit CRC over a path, so two DIFFERENT checkouts can name the same file.
# Nothing downstream would have noticed: this tool would read the other tree's
# harness name and commit, and then write file bytes from a blob resolved in
# THIS repository at THAT repository's sha. Usually that fails loudly with
# "does not exist at <sha>"; where both trees hold a path of the same name it
# does not fail at all, and restores the wrong content.
#
# The field costs one comparison to check and the collision is otherwise
# invisible, which is the combination that makes it worth checking. An older
# state file with no `repo=` line is TOLERATED rather than refused - it predates
# the field and refusing it would strand exactly the mutation this tool exists
# to put back - but it is called out, because a check that cannot see its input
# and a check that passes must not look the same.
if [ -z "$state_repo" ]; then
  echo "NOTE: this state file records no \`repo=\` line, so it cannot be"
  echo "      confirmed to be about this checkout. Proceeding, because a file"
  echo "      written before that field existed is still evidence - but read"
  echo "      the diff below yourself before accepting any restore."
elif [ "$state_repo" != "$REPO" ]; then
  echo "::error::REFUSING: this state file is about a DIFFERENT repository." >&2
  echo "         state file says : $state_repo" >&2
  echo "         this checkout is: $REPO" >&2
  echo "         The path to the state file is keyed by a 32-bit cksum of the" >&2
  echo "         repository path, so two checkouts can collide on it. Acting" >&2
  echo "         on it here would restore file bytes from a blob resolved in" >&2
  echo "         THIS repository at THAT one's sha. Run this tool with" >&2
  echo "         --repo \"$state_repo\", or set HARNESS_STATE_FILE." >&2
  exit 2
fi

if [ -z "$state_harness" ] || [ -z "$state_commit" ] || [ -z "$state_pid" ]; then
  echo "::error::the state file is incomplete and cannot be acted on:" >&2
  cat "$STATE" >&2
  echo "         A half-written state file is indistinguishable from a corrupt" >&2
  echo "         one. Delete it only after reading \`git diff\` yourself." >&2
  exit 2
fi

echo "owner      : $state_harness (pid $state_pid, started $state_started)"
echo "reference  : $state_commit"

if harness_state_owner_alive "$state_pid"; then
  echo "::error::REFUSING: pid $state_pid IS STILL ALIVE, so $state_harness is" >&2
  echo "         RUNNING and owns this tree for the rest of its run. Its" >&2
  echo "         mutation is not stranded, it is IN USE - restoring now would" >&2
  echo "         corrupt a live measurement and make the harness report a" >&2
  echo "         result about code it is no longer running." >&2
  echo "         Wait for it, or kill it and re-run this." >&2
  exit 3
fi

if [ -z "$porcelain" ]; then
  echo "NOTHING STRANDED: the owner (pid $state_pid) is gone and the tree is"
  echo "clean, so $state_harness restored itself before it died. Clearing the"
  echo "stale state file."
  harness_state_end "$REPO"
  exit 0
fi

# ---- 3. stranded. Report it identically in both modes before acting. -------
echo
echo "::error::STRANDED MUTATION from $state_harness."
echo "         Its owner (pid $state_pid) is gone and the tree is still dirty,"
echo "         so it was killed between mutating and restoring. SIGKILL runs no"
echo "         trap and no finally; nothing else was ever going to put this"
echo "         back. DO NOT COMMIT FROM THIS TREE, and do not trust any"
echo "         measurement taken in it since $state_started."
printf '           %s\n' "$porcelain"

if [ "$MODE" = "check" ]; then
  echo
  echo "--check changes nothing. Put it back with:"
  echo "  bash docs/reviews/restore-stranded-mutation.sh --restore-only"
  exit 1
fi

# ---- 4. --restore-only --------------------------------------------------
# THE INDEX MUST NOT HAVE MOVED. Column 1 of porcelain is the INDEX status.
# Anything but a space or `?` there means the harness staged something, and
# putting the worktree back would leave a staged diff behind - a tree that still
# reports dirty, from a tool that just said it restored it. Un-staging is the
# destructive index operation this file's header refuses to perform, so this
# stops instead.
staged=$(awk 'substr($0,1,1) != " " && substr($0,1,1) != "?"' <<< "$porcelain")
if [ -n "$staged" ]; then
  echo "::error::REFUSING: these entries are STAGED (column 1 is not blank), so" >&2
  echo "         the harness touched the index, not only the worktree." >&2
  printf '           %s\n' "$staged" >&2
  echo "         Restoring the worktree alone would leave a staged diff and a" >&2
  echo "         tree that still reads dirty. Un-staging is the operation that" >&2
  echo "         silently destroys staged work, so this tool will not do it." >&2
  echo "         Inspect with \`git -C $REPO diff --cached\` and decide." >&2
  exit 3
fi

# Renames are not restorable by writing one path's bytes back, and the
# clean-tree precondition makes them near-impossible here. Refuse rather than
# half-restore.
if awk 'substr($0,1,2) ~ /R/' <<< "$porcelain" | grep -q .; then
  echo "::error::REFUSING: a RENAME is present. Restoring bytes to one path" >&2
  echo "         cannot undo a rename, and a partial restore is worse than" >&2
  echo "         none. Read the diff and repair by hand." >&2
  exit 3
fi

echo
echo "restoring from $state_commit, file bytes only, index untouched:"

restored=0
skipped=0
failed=0

# `-z` so a path with a space or a quote cannot be mis-split. `git status`
# without it QUOTES such paths, and the quotes then become part of the filename
# the restore writes to - a wrong path that reports success.
while IFS= read -r -d '' entry; do
  code="${entry:0:2}"
  path="${entry:3}"

  if [ "$code" = "??" ]; then
    echo "  LEFT ALONE (untracked, nothing to restore to): $path"
    skipped=$((skipped + 1))
    continue
  fi

  blob=$(mktemp)
  if ! git -C "$REPO" cat-file blob "$state_commit:$path" > "$blob" 2>/dev/null; then
    echo "  CANNOT RESTORE: $path does not exist at $state_commit."
    echo "                  The harness created it; deleting is unrecoverable,"
    echo "                  so it is left in place for you to judge."
    rm -f "$blob"
    skipped=$((skipped + 1))
    continue
  fi

  # `cmp`, NOT `git diff --quiet`. git diff answers a question about the INDEX;
  # the index is not what we are about to write, and this project has twice
  # recorded a wrong answer from asking git the question that does not match
  # the answer the restore writes from.
  if cmp -s "$blob" "$REPO/$path"; then
    echo "  already correct: $path"
    rm -f "$blob"
    continue
  fi

  cp "$blob" "$REPO/$path"

  # VERIFY THE WRITE LANDED. A cp that silently failed - read-only file, full
  # disk - would otherwise be reported as a restore. The second cmp is the
  # measurement; the first was only the decision to act.
  if cmp -s "$blob" "$REPO/$path"; then
    echo "  RESTORED and verified by cmp: $path"
    restored=$((restored + 1))
  else
    echo "  ::error::RESTORE FAILED, file still differs after write: $path"
    failed=$((failed + 1))
  fi
  rm -f "$blob"
done < <(git -C "$REPO" status --porcelain -z)

echo
echo "restored=$restored  left-alone=$skipped  failed=$failed"

if [ "$failed" -ne 0 ]; then
  echo "::error::$failed path(s) could not be restored. The tree is NOT clean." >&2
  exit 4
fi

after=$(git -C "$REPO" status --porcelain)
if [ -n "$after" ] && [ "$skipped" -eq 0 ]; then
  echo "::error::the tree is STILL dirty after a restore that reported no" >&2
  echo "         failures. That is an instrument failure, not a clean result." >&2
  printf '           %s\n' "$after" >&2
  exit 4
fi

# The state file is cleared LAST, and only once the tree is verified. Clearing
# it earlier would erase the evidence at the moment it is needed.
harness_state_end "$REPO"

if [ -n "$after" ]; then
  echo "RESTORED, but $skipped path(s) were left alone (listed above) and the"
  echo "tree is therefore still dirty. Judge those by hand."
  exit 0
fi
echo "RESTORED. The tree is clean and the state file is cleared."
exit 0
