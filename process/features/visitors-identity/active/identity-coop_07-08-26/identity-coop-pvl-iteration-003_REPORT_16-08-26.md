---
name: report:identity-coop-pvl-iteration-003
description: "PVL supplement cycle 3 (16-08-26) — post-audit fix supplement S1-S7 applied after human REJECT verdict on the Phase 1 evidence pack"
date: 16-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: phase-1-ledger-substrate
  iteration: 3
---

# PVL Iteration 003 — Post-Audit Fix Supplement (16-08-26)

## Trigger

Independent re-audit of the executed-and-EVL-green Phase 1, ordered by the user before signing
the evidence pack:

- **vc-tester re-run (16-08-26):** all 11 re-run contract gates STILL GREEN on today's tree
  (HEAD `d82a1dc`, alembic head `d7e2b4c81f93`, single head). Zero coop regressions. Evidence:
  `harness/verification-reaudit-16-08-26.json`. One integration failure attributed to a
  pre-existing ip-org lock-serialization flake (passes isolated).
- **vc-code-reviewer adversarial pass (16-08-26):** 2 HIGH + 3 MEDIUM + 6 LOW findings OUTSIDE
  the gate-fenced resolve path: H1 site-delete cascade omits the 3 co-op tables (credit
  resurrection on site re-create); H2 enqueue→sweep tombstone window (default 5 min) permanently
  mints a bidx row + credit for an already-queued erasure (co-op tables not in ERASURE_TARGETS);
  M2 `contribution_enabled` flip live on prod ungated on `identity_coop_enabled` (placeholder
  terms digest); M3 hook wiring has zero test execution; L1 harness non-vacuity claims overstate
  (armed mocks unreachable).

## Human verdict

**REJECTED** — `review-decision.json` to be updated to `rejected` (reviewer: Julley Thai, via
orchestrator session 16-08-26; checklist item R1 in the supplement). Re-approval expected after
the supplement's gates go green.

## Supplement applied (SUPPLEMENT_APPLIED — 6 gaps addressed)

`## Post-Audit Fix Supplement (16-08-26)` appended to
`phase-1-ledger-substrate_PLAN_07-08-26.md`: checklist groups S1–S7, 14 test gates (incl. SG-6
window-race leg + SG-7 non-vacuity proof), per-file diff budgets, 5 constraints.

Design decisions settled:

- **H1-D:** cascade gains `identity_contribution_events` + `identity_credit_ledger` only;
  `identity_contribution_consent_acceptances` RETAINED on site delete (proof-of-lawful-basis for
  contributions already credited to other tenants; inherited acceptance is inert because a
  re-created site starts `contribution_enabled=False` and a True-flip demands a fresh acceptance
  row in-transaction).
- **H2-D:** shape (a) — suppression tombstone written inside `enqueue_erasure`'s transaction.
  Strictly fail-safe (every `is_email_suppressed_any` caller uses suppression to withhold);
  sweep's tombstone write degrades to no-op via existing `on_conflict_do_nothing`. Shape (b)
  credit-reversal semantics deferred to a named Phase 2 backlog note.
- **M2:** True-flip additionally gated on `settings.identity_coop_enabled`, 422 posture
  (matching sibling terms-digest guard; 404 reserved for tenancy).

## Known-gaps accepted at this cycle

- No gate proves H2 under real multi-process concurrency; SG-6 covers the sequential window
  (the reported defect shape). Recorded in the plan.

## Next

Fresh PVL from V1 scoped to S1–S7 (existing validate-contract covers original scope only), then
EXECUTE on user approval, then vc-tester re-audit, then re-present evidence pack for verdict.
