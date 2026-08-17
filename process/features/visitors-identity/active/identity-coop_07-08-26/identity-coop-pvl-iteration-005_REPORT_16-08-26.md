---
name: report:identity-coop-pvl-iteration-005
description: "PVL cycle 5 (16-08-26) — re-validate of repaired supplement: 7/8 closed, new FAIL SUP2-F1 (bare try/except cannot preserve ErasureRequest; needs begin_nested savepoint) + 3 new CONCERNs"
date: 16-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: phase-1-ledger-substrate
  iteration: 5
---

# PVL Iteration 005 — Cycle-2 re-validate of the repaired supplement (16-08-26)

## Verdict

`Gate: BLOCKED` (cycle 2). Supplement contract superseded in place
(`supersedes: 2026-08-16 cycle 1`, `generated-by: inner-pvl: phase-1-supplement`).

## Closed and VERIFIED against source (7 of 8 cycle-1 gaps)

- SUP-F1 (item 9a keeps `test_flag_on_requires_acceptance` satisfiable — walked test:444-521 vs
  guard sites.py:417-438), SUP-F2 (zero residual bad paths), SUP-C1, SUP-C3, SUP-C4, SUP-C6.
- SUP-C2 — SG-6/SG-6b proven NON-VACUOUS by source walk: `GRAPH_WRITE_BLOCKING_SCOPES ==
  _TOMBSTONE_SCOPES`, blocked upsert returns False, hook at resolver:1310 never fires; WITHOUT S2
  the graph write succeeds and mints 1 event + 1 ACCRUE → SG-6's zero goes RED. Gate can fail if
  the fix is absent — the property cycle 1 lacked.

## Remaining FAIL

- **SUP2-F1** — item 5a's bare `try/except` around the tombstone execute does NOT preserve the
  `ErasureRequest`: `AsyncSession.execute()` autoflushes the added row into the same transaction;
  a DB-level tombstone failure (deadlock/timeout/conn-loss — `on_conflict_do_nothing` only removes
  unique-violation) aborts the transaction; the later `commit()` raises `PendingRollbackError`
  (route still deletes the only match-key source) or is discarded while returning a row id (false
  compliance receipt). GDPR path strictly WORSE than today. Required shape: `async with
  db.begin_nested():` savepoint (repo idiom: identity_coop.py:175, sites.py:206; ~11 lines,
  inside the ≤18 budget). SG-15 as specified is vacuous against this (fake-session raise never
  aborts a transaction) — strengthen with the fake-savepoint pattern
  (tests/unit/test_site_limit.py:100-114).

## New CONCERNs

- **SUP2-C1** — item 9a scopes the monkeypatch to "200-path steps only"; guard sits BEFORE the
  digest comparison, so flag-OFF steps 1-3 short-circuit on 422 and never reach the digest branch
  (3 digest legs go vacuous, incl. the named vacuous-guard case at :476). Fix: monkeypatch the
  whole test function.
- **SUP2-C2** — gate table needs 9 distinct integration test functions (every `-k` selector);
  checklist describes 3-4; SG-10 has no checklist item; item 14's single test cannot match both
  SG-4 and SG-5 selectors; ≤190-line budget vs ~450 realistic → correct implementation trips the
  plan's own budget-breach STOP.
- **SUP2-C3** — models/suppression.py docstring still claims rows "were hard-deleted" (falsified
  by at-enqueue tombstone); ≤3-line budget shorter than the clause being replaced.

## Next

Plan-fix cycle 3 (Gaps SUP2-F1 + SUP2-C1/C2/C3), then inner PVL re-run from V1.
EXECUTE remains forbidden. Cycle count 3/10 — no plateau (gap set strictly shrinking:
8 → 4, all mechanical).
