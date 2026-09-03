# shellcheck shell=bash
# ONLY 0 AND 1 ARE MEASUREMENTS (#254). The ONE copy, sourced, never retyped.
#
# Every amputation harness in this repository reads its verdict by counting
# `^PASSED ` lines and treats "no PASSED lines" as "every assertion died",
# i.e. a successful kill. That inference is only valid if pytest actually
# COLLECTED and RAN the suite.
#
# It fails OPEN, not closed. A collection error (rc=2), an internal error
# (rc=3), a usage error (rc=4) or a timeout (rc=124) all produce an output
# file with no `PASSED ` lines in it, so the loudest possible breakage is
# reported as the cleanest possible result: "survivors: NONE".
#
# WHY A SOURCED FUNCTION AND NOT FOURTEEN COPIES. The defect was found in
# check-u3-audit-amputation.sh and fixed there inline; a review then read the
# other thirteen and found the identical hole in every one. A copy is what
# drifts, and this repository has measured that drift more than once. One
# function, called from every harness, is both the smaller diff and the only
# shape where a later correction reaches all of them.
#
# MEASURED, on the tree that had no guard: a one-row derivative of
# check-u4-client-amputation.sh whose A1 replacement is invalid Python printed
#   E   SyntaxError: '(' was never closed
#   survivors: NONE - no assertion passed against this tree
#   HARNESS-RESULT name=... rows=1 floor=0 applied=1/1 status=ok
# and exited 0. The loudest possible breakage, scored as a perfect kill.
#
# CALL IT AFTER THE RESTORE, ALWAYS. It `exit`s, and exiting with an
# amputation still applied leaves the next reader a mutated checkout and no
# note saying why. Every call site below the `git checkout --` is correct;
# one above it is not.
#
# AND BEFORE THE VERDICT. Both constraints, because satisfying only the first
# is a real state one adopter shipped in: check-body-cap-amputation.sh had the
# guard after its restore AND after its `survivors:` block, so with
# ROW_TIMEOUT=1 a refused row printed
#     survivors: NONE - no assertion passed against this tree
#     REFUSING: an unfinished row has no verdict.
# in that order. The exit code was correct and the log stated the false kill
# this function exists to suppress, one line before suppressing it. A guard
# downstream of the verdict does not guard the verdict; it annotates it.
#
# The order is therefore: capture rc -> restore -> verdict_guard -> verdict.
#
# EXIT 5, a code no harness here used before. It is not 1 (a FINDING - an
# assertion survived something that should have killed it) and not 3 (could
# not run - a red baseline or a dirty tree). A refusal is a third thing: the
# harness ran, the row landed, and the row's result is not interpretable.
# scripts/ci-harness-gate.sh gives it its own diagnosis.
#
# verdict_guard <pytest-rc> <output-file> <timeout-seconds>
verdict_guard() {
  case "$1" in
    0|1) return 0 ;;
    124)
      echo "  TIMED OUT after ${3}s - this row NEVER FINISHED."
      echo "  REFUSING: an unfinished row has no verdict. A timeout produces the"
      echo "  same empty output as a perfect kill, so continuing would count it"
      echo "  as one. Raise the row timeout (currently ${3}s) or fix what is"
      echo "  hanging, then re-run."
      exit 5
      ;;
    *)
      echo "  REFUSING: pytest exited $1, which is not a measurement."
      echo "  This harness reads 'no PASSED lines' as 'everything died', so a"
      echo "  collection error (2), internal error (3) or usage error (4) would"
      echo "  be counted as a successful kill. The last 20 lines of its output:"
      sed 's/^/    /' "$2" | tail -20
      exit 5
      ;;
  esac
}
