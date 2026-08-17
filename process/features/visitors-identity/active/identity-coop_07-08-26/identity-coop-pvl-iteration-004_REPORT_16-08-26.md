---
name: report:identity-coop-pvl-iteration-004
description: "PVL supplement cycle 4 (16-08-26) — BLOCKED verdict repaired: SUP-F1/F2 + 6 CONCERNs closed in one plan-fix pass; re-validate from V1 pending"
date: 16-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: phase-1-ledger-substrate
  iteration: 4
---

# PVL Iteration 004 — Supplement repair after `Gate: BLOCKED` (16-08-26)

## Trigger

Inner PVL (V1, scoped S1–S7) on the post-audit fix supplement returned `Gate: BLOCKED`:

- **SUP-F1** — S3's `identity_coop_enabled` gate reddens existing green
  `test_flag_on_requires_acceptance` (asserts 200, no monkeypatch); SG-1/SG-11 mutually
  unsatisfiable with S3 as written.
- **SUP-F2** — 7 gates (SG-3..SG-8, SG-11) + items 13/14/15 targeted nonexistent
  `tests/integration/test_identity_coop.py` (real file: `test_identity_coop_contribution.py`).
- 6 CONCERNs, two load-bearing: **SUP-C2** (SG-6 — sole H2 gate — vacuous with flags OFF) and
  **SUP-C5** (S2 tombstone failure would roll back ErasureRequest while visitor rows still get
  deleted → permanently unrecoverable erasure).

Validator also CONFIRMED against source: H2-D fail-safe claim (11 call sites enumerated, all
withhold), conflict-target match for `on_conflict_do_nothing`, H1-D holds independent of M2,
M2 gate not bypassable, anchors/budgets resolve.

## Repair applied (SUPPLEMENT_APPLIED — 8 gaps addressed)

- S3 item 9a: monkeypatch global flag True for 200-path + new 422-with-valid-digest negative leg.
- All new integration legs INTO existing `test_identity_coop_contribution.py` (no new file);
  paths corrected everywhere; blast-radius row retargeted (≤190 added lines).
- SG-6 rewritten non-vacuous (both flags ON, enqueue-then-resolve, 0 events + 0 ledger) +
  SG-6b positive control (no enqueue → exactly 1 event + 1 ACCRUE). SG-7 table name fixed
  (`suppression_list`).
- S2 item 5a: tombstone execute in own try/except, `tombstone_write_failed` log, never aborts
  ErasureRequest insert; item 5b + SG-15 unit gate for the failure path.
- SG-9/SG-10 re-tiered Hybrid (PG :5433); S1 item 3 reworded (204 no body — do not add one);
  `"erased"` scope docstring update item added.
- Budget change: `graph_erasure.py` ≤10 → ≤18 touched lines; new rows
  `tests/unit/test_graph_erasure.py` (≤30), `models/suppression.py` (≤3, docstring-only).

## Carried residuals (declared, unchanged)

1. No multi-process concurrency probe for H2 — SG-6/SG-6b prove the sequential window only.
2. M2 contract guard has no unit fast-lane until an `update_site` unit harness exists.

## Next

Re-run inner PVL from V1 on the repaired supplement. EXECUTE remains forbidden until
`Gate: PASS` (or user-accepted CONDITIONAL).
