#!/usr/bin/env bash
# Re-freeze docs/DESIGN.md at the commit that carries it.
#
#     bash scripts/refreeze.sh          # do it
#     bash scripts/refreeze.sh --show   # print what it would do
#
# WHY THIS IS A SCRIPT AND NOT A PARAGRAPH. `docs/DESIGN-FREEZE.txt`
# names the commit whose `docs/DESIGN.md` is authoritative, and the
# child repository has to produce that name for ITSELF - the template
# cannot know it. Left as prose, every adopter re-derives the procedure,
# and the procedure has a genuinely surprising step in it.
#
# THE SURPRISING STEP: NO COMMIT CAN CONTAIN ITS OWN SHA. So freezing is
# necessarily TWO commits - one that lands the design, one that records
# where it landed. That is not a defect to be engineered away; it is a
# property of content-addressed history, and it is written here so that
# nobody spends an afternoon looking for the single-commit version.
#
# WHAT IT DOES. Writes the SHA of the last commit that touched
# `docs/DESIGN.md` into `docs/DESIGN-FREEZE.txt`. That is the commit at
# which the current blob became current, so the gate's blob comparison
# passes and the pointer names something meaningful rather than merely
# something recent.
set -euo pipefail

# THE CANONICAL RESULT LINE. docs/reviews/check-harness-result.sh
# asserts { scripts that emit the line } == { scripts that exist },
# over the glob scripts/*.sh, and its own header says there is "no
# table in this file, no allowlist, and no harness vs not a harness
# partition - a partition would be the same hand-kept list one level
# up". This script was in that glob and emitted nothing, so the gate
# was red for exactly the reason it is designed to go red: a script
# was added and not wired. Sourcing the library arms an EXIT trap
# that prints the line on every path.
# shellcheck source=lib/harness-result.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/harness-result.sh"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESIGN="docs/DESIGN.md"
FREEZE="docs/DESIGN-FREEZE.txt"

cd "$ROOT"

if [ ! -f "$DESIGN" ]; then
  echo "$DESIGN does not exist. Write the design before freezing it." >&2
  exit 2
fi

if [ -n "$(git status --porcelain -- "$DESIGN")" ]; then
  echo "$DESIGN has UNCOMMITTED changes." >&2
  echo "Freezing now would name a commit that does not carry what is on" >&2
  echo "disk. Commit the design first, then run this again." >&2
  exit 2
fi

# RAN, with no rows and no floor. The library's own comment says 0
# "is not a floor anything can breach, and it reads as absent",
# which is the honest shape for a tool that freezes one file and
# counts nothing. Called here, past every refusal above, so the
# line says refused when this script refuses and ok when it works.
harness_result_ran 0 0

sha="$(git log -1 --format=%H -- "$DESIGN")"
if [ -z "$sha" ]; then
  echo "No commit in this repository has ever touched $DESIGN." >&2
  echo "Commit it first; a freeze pointer needs something to point at." >&2
  exit 2
fi

blob="$(git rev-parse "HEAD:$DESIGN")"

if [ "${1:-}" = "--show" ]; then
  echo "would write $sha to $FREEZE"
  echo "  $DESIGN blob at HEAD: $blob"
  exit 0
fi

echo "$sha" > "$FREEZE"
echo "Froze $DESIGN at $sha"
echo "  blob: $blob"
echo
echo "NOW COMMIT $FREEZE. This is the second of the two commits the"
echo "header explains: the first landed the design, this one records"
echo "where it landed. Until it is committed the gate still reads the"
echo "old value."
echo
echo "  git add $FREEZE && git commit -m 'Freeze the design at the commit that carries it'"
