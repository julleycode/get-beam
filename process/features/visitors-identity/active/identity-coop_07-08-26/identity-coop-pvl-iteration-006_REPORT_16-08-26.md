---
name: report:identity-coop-pvl-iteration-006
description: "PVL cycle 6 (16-08-26) — fix cycle 3 applied: SUP2-F1 savepoint rewrite + SG-15 fake-savepoint gate, whole-function monkeypatch, 9-test enumeration (budget 480), docstring both sentences; re-validate from V1 pending"
date: 16-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: phase-1-ledger-substrate
  iteration: 6
---

# PVL Iteration 006 — Fix cycle 3 (16-08-26)

## Applied (SUPPLEMENT_APPLIED — 4 gaps)

- **SUP2-F1:** item 5a rewritten — tombstone execute inside `async with db.begin_nested():`
  (repo idiom identity_coop.py:175 / sites.py:206), except-wrapped, `tombstone_write_failed`
  warning, commit proceeds; bare-try/except failure mechanism documented (autoflush →
  PendingRollbackError → match-key loss / false receipt). SG-15 strengthened to fake-savepoint
  pattern (must fail vs bare try/except: asserts begin_nested entered + ErasureRequest survives +
  commit awaited). NEW optional 5c/SG-16 Hybrid real-DB-failure leg — accepted known-gap if
  skipped. graph_erasure.py budget stays ≤18.
- **SUP2-C1:** item 9a monkeypatches global flag for the WHOLE `test_flag_on_requires_acceptance`;
  flag-OFF 422 contract moved to its own `test_contribution_flip_gated_on_global_flag` (SG-9).
- **SUP2-C2:** authoritative 9-function table; item 14 split 14a/14b (SG-4/SG-5); item 15 split
  15a-15e (SG-6, SG-6b, SG-7, SG-8, SG-10 — SG-10 previously itemless); SG-6/SG-6b renamed
  `..._blocked`/`..._control` (disjoint -k matches); integration budget ≤190 → ≤480; split escape
  hatch to `test_identity_coop_supplement.py` only above ~1000 lines, `...` shorthand redefined
  to directory-run so -k gates resolve either way.
- **SUP2-C3:** item 6a replaces BOTH falsified suppression.py docstring sentences with exact
  wording; budget ≤3 → ≤8.

Plan validator: 0 failures.

## Validator scope notes (for cycle-3 PVL)

1. Cycle-2 contract's own gate table is now stale (SG-6/6b rename + shorthand redefinition) —
   the plan's `## Test Gates (Supplement)` table is authoritative; re-derive from it.
2. SG-16 optional: without it, SG-15 proves savepoint entered, not that Postgres honours it —
   declared known-gap on a GDPR surface.

## Next

Inner PVL re-run from V1 (validate cycle 3). Gap trajectory 8 → 4 → 0 claimed; verify.
