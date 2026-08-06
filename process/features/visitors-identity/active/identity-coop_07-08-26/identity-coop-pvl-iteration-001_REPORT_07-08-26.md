---
name: identity-coop-pvl-iteration-001
description: PVL supplement cycle 1 — 8 plan-fixable gaps settled; phase 1 held Dependency-BLOCKED on SPEC A LIVE
date: 2026-08-07
metadata:
  type: pvl-iteration-report
  plan: phase-1-ledger-substrate_PLAN_07-08-26.md
  cycle: 1
  loop: PVL
---

# PVL Iteration 001 — identity-coop phase-1

**Trigger:** outer-PVL pass 2 `Gate: BLOCKED` (F1 external + F2/F3 plan-fixable + 5 CONCERNs).

## Settled this cycle (8 gaps: F2, F3, C1, C2, C3, C5, C6, C8)

- **D-A (F2):** `_upsert_beam_identity` `→ bool`; accrual hook gated on it. D4 diff budget raised 6→12 lines with rationale (billing correctness > diff-cosmetic cap). One production caller verified (`identity_resolver.py:1252`).
- **D-B (F3+C1+C2):** write NOTHING when graph write blocked (option a — privacy-first). C2 step-4 suppression re-check deleted. `ERASURE_TARGETS` untouched → SPEC A sweep semantics intact. New testable privacy invariant; F6 retired.
- **D-C (C3):** `is_bot_suspect` in fraud gate; `excluded_reason` vocab `fraud_flagged`/`duplicate`/NULL.
- **D-D (C6, schema-freeze decision):** ledger stays `site_id`-only; Phase 2 aggregates `site_id → sites.user_id` before `billing.check_usage_allowed`. Mirrored into registry Phase 2 entry.
- **D-E (C8):** partial unique index `uq_coop_accrued_site_email (site_id, email_bidx) WHERE accrued IS TRUE` — DB-enforced one-credit-per-identity-per-site; repeats audit as `duplicate`.
- **C5:** AC-10 adopted into Phase 1 + minimal E4 `terms_version` validator + new test.
- Registry: migration path corrected (both phases), `status: Dependency-BLOCKED` appended to Phase 1 with claim-surface deltas.
- Backlog NOTE written: `backlog/identity-coop-entry-gate-spec-a-live_NOTE_07-08-26.md` (4 clearing conditions + re-run PVL from V1 + evidence-pack requirement).

## Disposition (autopilot run 07-08-26)

**F1 stands — sole blocker, external:** entry gate requires SPEC A (graph-erasure) LIVE; its real state is CODE DONE (14 integration gates never run — Docker down; migration round-trip deferred; devjulley unpushed). Phase 1 held **Dependency-BLOCKED**; Phases 2-3 skip per Step-0 dependency rule. NO re-validate now (verdict cannot change while entry gate unmet). When SPEC A goes LIVE: re-run PVL from V1, then high-risk evidence pack (billing/credits + migration) before EXECUTE.

Umbrella coverage-map note: AC-10 reassignment (Phase 3 → Phase 1) amended inline in the phase plan; umbrella file NOT edited (out of supplement scope) — reconcile at UPDATE PROCESS.
