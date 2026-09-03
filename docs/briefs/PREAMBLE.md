# Brief preamble

**Paste this block verbatim at the top of every agent brief.** It is not
boilerplate: every paragraph is here because its absence produced a defect.

---

## Ground rules

1. **`docs/DESIGN.md` is the authority, and it is FROZEN.** Read it at the SHA
   in `docs/DESIGN-FREEZE.txt`, which this brief repeats below. A finding
   against the design is not an edit request — it is an ADR.

2. **Your file domain is exclusive.** You may write only the paths listed under
   "Domain" below. Two agents in one file is how a merge puts damage back.

3. **Verify against the code, not against a document about the code.** A commit
   message, an audit claim and a checklist tick are all reports. `git` and the
   source are the ground truth.

4. **A count you state must be DERIVED, with the command beside it, or pinned
   as-at a SHA.** A figure copied out of a program is a cache and it goes stale
   silently. `grep -c` counts LINES, not matches.

5. **Verify a path exists before believing a zero from it.** A search at a path
   that does not exist returns the same clean empty as a real absence.

6. **A green check licenses only what it checked.** A skip is a green that
   tested nothing. A control that never invokes the artefact tests a proxy.

7. **Never leave a mutation in the tree.** If you run a harness that edits
   `src/` or `tests/`, confirm `git status --porcelain -- src tests` is empty
   afterwards — a killed harness leaves its mutation behind.

8. **Report what you could NOT settle.** The "did not verify" list is for things
   you could not settle, not things you did not get to.

---

## This brief

- **Task:** TODO
- **Domain (exclusive write paths):** TODO
- **Design SHA:** TODO — obtained in the same command as the line numbers below
- **Branch:** TODO
- **Deliverable:** TODO, plus a completion report sent back on the same channel
  this brief arrived on.
