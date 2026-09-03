# Credential checklist

What to establish **before** a real upstream credential is issued, and what to
observe the first day one exists. Rows 1-4 block any claim that the success
path is verified. Row 0 must be answered before a key is requested.

## Row 0 — ask before a key is issued

- [ ] What scopes does this credential carry, and is a read-only one available?
      A write-capable key issued for a read-only integration is a permanent
      liability nobody revisits.
- [ ] Who owns rotation, and on what interval?
- [ ] Is there a sandbox or test tenant? If not, say so here — every row below
      then runs against production data and the risk is real, not theoretical.

## Rows 1-4 — the first day

- [ ] **1. Authentication succeeds**, and the failure mode when it does not is
      the error contract's, not a raw upstream exception.
- [ ] **2. A real response is parsed** by the real client, not a fixture. Record
      one anonymised response body; the fixture is derived from it, not written
      to match the code.
- [ ] **3. Pagination is exercised past the first page.** The first page is the
      one case that works by accident.
- [ ] **4. Rate limiting is observed**: what the upstream actually returns, and
      what the client does with it.

## Standing rules

- **Never print a credential**, including in a diagnostic, a test failure, or a
  log line built from a request object. Redaction is asserted by a test, not
  assumed from a helper's existence.
- **Credentialed tests are DESELECTED from the default suite by marker**, never
  `skipif`. A skip is a green that tested nothing. They are still COLLECTED
  (`--collect-only`) so they cannot rot unnoticed.
- Any `.env` stays untracked. `.env.example` carries the names and never values.
