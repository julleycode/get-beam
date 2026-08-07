---
name: report:identity-coop-entry-gate-spec-a-live
description: "Identity Co-op Phase 1 is Dependency-BLOCKED on SPEC A (graph-erasure-compliance) reaching LIVE — F1 re-entry conditions"
date: 07-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: phase-1
---

# Identity Co-op Phase 1 — Dependency-BLOCKED on SPEC A going LIVE (F1)

**TL;DR** — Phase 1 of the identity-coop program cannot enter EXECUTE until
`graph-erasure-compliance_07-08-26` (SPEC A) is LIVE, not merely code-complete. Every other FAIL and
CONCERN from the 2nd outer-PVL pass was fixed in plan text on 07-08-26. This note records the one
external dependency and the exact conditions that clear it.

## Status

| Item | State |
|---|---|
| Phase | `phase-1-ledger-substrate` of `identity-coop_07-08-26` |
| Registry status | `Dependency-BLOCKED — entry gate SPEC A not LIVE; files never modified` |
| Files modified in the repo | **none** — no source file has been touched for this phase |
| Plan gate | `Gate: BLOCKED` on F1 only |

## The dependency

Phase 1's Entry Gate requires SPEC A `graph-erasure-compliance_07-08-26` to be **LIVE**. As of
07-08-26 its own report states `CODE DONE` / `status: COMPLETE_WITH_GAPS`, not `EVL GREEN`:

- the 14 integration gates (T-I1…T-I10) are written and collect cleanly but have **never executed**
  (Docker down — re-confirmed this cycle, `docker info` fails)
- the migration live round-trip is **deferred, not passed**
- nothing is deployed: branch `devjulley`, unpushed; `graph_erasure_sweep_enabled` (default `True`)
  has never run in any real environment

Phase 1 now depends on that code *behaviourally*, not just for a suppression surface: decision D-A
gates credit accrual on `_upsert_beam_identity` returning `True`, and that `False` path is SPEC A's
write boundary. Accruing against an unproven boundary would put unverified privacy logic directly on
the billing/credits surface.

## Clearing conditions (all four)

1. ~~SPEC A reaches **EVL GREEN**~~ — **MET 07-08-26 (fix-batch, commit `81eb4e6`):** the 8
   fixture-blocked gates were repaired (test-side only) and the full file now passes **14/14**
   against real Postgres. See `docker-gate-run-findings_NOTE_07-08-26.md` resolution header.
2. ~~SPEC A's **migration live round-trip**~~ — **MET 07-08-26:** `d1a6c4e93f27` round-tripped
   clean on a disposable postgres:16-alpine (full 64-rev chain from empty; 17-rev down/up).
3. ~~SPEC A is **pushed and deployed**~~ — **MET 07-08-26:** graph-erasure shipped to prod in the
   `f0c95e6` main push (Railway deploy SUCCESS, healthcheck green); migration `d1a6c4e93f27`
   confirmed applied in prod via read-only `alembic_version` SELECT.
4. Phase 1's other Entry Gate items are re-derived LIVE at that time — `alembic heads` (moves ~daily)
   and an `identity_resolver.py` drift re-check.

Alternative path: the umbrella explicitly redefines "LIVE" for this gate **and** the user accepts
that redefinition on the record. Silent redefinition is not acceptable — this is the money surface.

## What was fixed in plan text this cycle (07-08-26, PVL supplement cycle 1)

Recorded here so a future reader does not re-litigate them. Full rationale lives in the phase plan's
`## PLAN Decisions Settled at PVL Supplement` section.

| Gap | Resolution |
|---|---|
| **F2** — credit minted when no graph write happened | D-A: `_upsert_beam_identity` returns `bool`; hook gated on it; D4 diff budget raised 6 → 12 lines |
| **F3** — erased person gets a new `email_bidx` row outside `ERASURE_TARGETS` | D-B: write NOTHING when the graph write was blocked; `ERASURE_TARGETS` untouched |
| **C1** — suppression scope set too narrow | Resolved by deletion (D-B) — the co-op module no longer lists any scope |
| **C2** — duplicated privacy gate | Same: the duplicate is deleted, not widened |
| **C3** — fraud gate missed `is_bot_suspect` | D-C: signature widened; `excluded_reason='fraud_flagged'` |
| **C5** — AC-10 orphaned | Adopted into Phase 1 + E4 minimal `terms_version` validator + `test_flag_on_requires_acceptance` |
| **C6** — `site_id` ledger vs `user_id` gate | D-D: no `user_id` column; Phase 2 aggregates via `sites.user_id` at gate time (recorded in the registry) |
| **C8** — daily re-accrual on an already-owned identity | D-E: partial unique index `uq_coop_accrued_site_email` — one credit per identity per site, ever |
| **C4** — registry migration path wrong | Corrected to `apps/api/migrations/versions/` in Phase 1 and Phase 2 registry entries |

## Re-entry procedure

When conditions 1–4 above hold: **re-run PVL from V1** on
`process/features/visitors-identity/active/identity-coop_07-08-26/phase-1-ledger-substrate_PLAN_07-08-26.md`.
Do not resume from the existing contract — it is `generated-by: outer-pvl` and predates SPEC A being
live.

## Still required before EXECUTE (independent of F1)

The 5-artifact high-risk evidence pack (`risk-gate.json`, `context-snippets.json`,
`verification.json`, `review-decision.json`, `adversarial-validation.json`) under
`process/features/visitors-identity/active/identity-coop_07-08-26/harness/` — this phase is two
high-risk classes at once (billing/credits + schema/migration). It does not exist yet. Manual-first
by design.
