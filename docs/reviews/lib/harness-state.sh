#!/usr/bin/env bash
# THE RUN-STATE FILE, and the ONE place its path and format are derived.
# Task #131.
#
# WHY IT EXISTS. A mutation harness edits a tracked file, runs, and restores.
# SIGKILL runs no `finally` and no `trap`, so a harness killed mid-row leaves
# its mutation in the working tree and NOTHING owns putting it back. Measured
# three times in one day (#131), and a fourth time by accident the same night
# when suborch-148's negative-arm control ran real amputation harnesses under
# `timeout 25` and left ` M src/fast_mcp_jobvite/audit.py` behind.
#
# `git status` alone CANNOT answer the question that matters. It says the tree
# is dirty; it cannot say whether the dirt has an OWNER. Two worktrees were
# dirty at the same moment as one of the incidents above and BOTH were
# legitimate - probes were actively running in them. A naive "clean anything
# dirty" would have destroyed live work. That is the whole reason for a state
# file: dirt + a state file naming a dead owner is STRANDED; dirt with no state
# file is UNATTRIBUTED and must not be touched.
#
# WHAT IT DELIBERATELY IS NOT. It is not a lock, and it does not make any
# harness safe on its own. It is written by the PROBE, which is the only driver
# that currently knows (a) the tree was clean before the row and (b) which
# harness it launched. A harness run by hand, by a `for` loop, or by
# `ci-harness-gate.sh` writes no state file, and the restorer says so out loud
# rather than guessing. Closing that gap means every `scripts/check-*.sh`
# writing its own state, which is a separate change to a file family this task
# does not own.
#
# `-e` deliberately omitted, for the reason ADR-0023 gives: callers read exit
# codes of things expected to fail.
# See docs/adr/0023-harnesses-drop-e-from-strict-mode.md
#
# NOT A HARNESS. This file emits no HARNESS-RESULT line and is not in
# `scripts/*.sh`, so `docs/reviews/check-harness-result.sh` does not enumerate
# it. It is a library, like `scripts/lib/harness-result.sh` is for the result
# line, and it exists for the same stated reason: so that no caller has to
# carry a second copy of a format.

# harness_state_file <repo-abs-path>
#
# The path is DERIVED FROM THE REPO PATH, never configured, so the probe and
# the restorer cannot disagree about where to look - the two-lists defect this
# repo keeps finding. `HARNESS_STATE_FILE` overrides it for tests only.
#
# IT LIVES OUTSIDE THE REPO ON PURPOSE, and this was a measured near-miss while
# writing it. A state file inside the working tree is an UNTRACKED FILE, and the
# probe's own pre-flight refuses to start on `git status --porcelain` being
# non-empty - which includes untracked. So an in-tree state file would have made
# the probe abort on itself, and the in-loop check would have blamed the running
# harness for the probe's own bookkeeping. Keying by repo path also keeps
# concurrent worktrees from sharing one file, which matters here: several agents
# run in sibling worktrees of this repo at once.
harness_state_file() {
  local repo="$1"
  if [ -n "${HARNESS_STATE_FILE:-}" ]; then
    printf '%s\n' "$HARNESS_STATE_FILE"
    return 0
  fi
  # NORMALISED HERE TOO, not only in the tool (R18-N1). The key is a
  # cksum of the path STRING, so `/x/y` and `/x/y/` name different files
  # for one checkout - and since the restorer began comparing `repo=`,
  # they also produce a false "DIFFERENT repository" refusal. The tool
  # normalises its `--repo`; this closes the same hole for any OTHER
  # caller, which is where the two-lists defect this function's header
  # warns about would come back.
  repo="${repo%/}"
  local key
  key=$(printf '%s' "$repo" | cksum | awk '{print $1}')
  printf '%s/fmj-harness-state-%s.state\n' "${TMPDIR:-/tmp}" "$key"
}

# harness_state_begin <repo> <harness-name> <commit-sha>
#
# Called with the tree ALREADY VERIFIED CLEAN. That precondition is what makes
# the commit sha a sound restore reference: worktree, index and HEAD all agree
# at this instant, so "put it back to <sha>" cannot destroy staged work because
# there is none. The restorer re-states this rather than assuming it.
harness_state_begin() {
  local repo="$1" harness="$2" commit="$3" f
  f=$(harness_state_file "$repo")
  # Written in one `cat` so a reader never sees a half-written file. A partial
  # state file would be indistinguishable from a corrupt one, and the restorer
  # would have to guess which.
  cat >"$f" <<EOF
repo=$repo
harness=$harness
commit=$commit
pid=$$
started=$(date +%s)
started_human=$(date -Is)
EOF
}

# harness_state_end <repo>
#
# Called ONLY after the row completed and the tree was verified clean again.
# Removing it earlier would erase the evidence at exactly the moment it is
# needed.
harness_state_end() {
  rm -f "$(harness_state_file "$1")"
}

# harness_state_owner_alive <pid>
#
# Is the recorded owner still running? `kill -0` and NOTHING ELSE - not `pgrep`,
# not `ps` filtered by name. PROTOCOL-sub-orchestrators.md records the measured
# reason: with several agents live in one repo the process list is other
# people's data, and an agent once proved a job was running using a SIBLING
# agent's pytest process. The pid here is one this probe spawned and recorded
# itself.
#
# THE KNOWN HOLE, stated rather than hidden: pids are reused, so a recycled pid
# can make a dead owner look alive. The failure is in the SAFE direction - the
# restorer refuses to touch the tree and tells the operator to look - and
# `started` is printed so a wildly newer process is visible as the anomaly.
harness_state_owner_alive() {
  kill -0 "$1" 2>/dev/null
}
