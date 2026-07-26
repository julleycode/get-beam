# PVL Iteration 002 — capacity-hardening

Date: 2026-07-25
Loop: PVL (plan-validate-fix)
Cycle: 2 (re-validation from V1 after cycle-1 supplement)
Plan: capacity-hardening_PLAN_25-07-26.md
Verdict: Gate: BLOCKED (verbatim: 1 root-cause FAIL surfacing in 2 dimensions — the scheduled full-recompute mechanism named by the plan does not exist and is delivered by no plan item; Phase 1's stated correctness gap is left unresolved)

## Cycle-1 verification results

All 9 cycle-1 supplement fixes re-verified against source — 7/9 fully verified, Gaps 5/6 verified as diagnoses but their fixes hit by the new FAIL. Both cycle-1 FAILs (merge design, test tiering) CLOSED.

## New findings

| Gap | Severity | Root cause |
|---|---|---|
| 10 | FAIL | "Worker deploy activates beat_schedule" claim factually false — plain `celery worker` runs no beat; only `celery beat` / `worker -B` does; neither exists in Dockerfile/railway.json/docker-compose. Ordering constraint 1(a)-last justified by wrong fact |
| 11 | FAIL | D7 staleness bound names hourly beat sweep as repair cadence — no plan item delivers it; APScheduler (only live scheduler) has zero aggregation jobs. Flag-ON would freeze intent_score/avg_time_on_page permanently |
| 12 | FAIL | Phase 1 names 3 dead beat jobs as "the correctness gap" but delivers no revival/descope/backlog routing; exit gate tickable with defect intact |

2 new CONCERNs (D6 ai_source desync under symmetric COALESCE; ip_address missing from 7-column table) — RESOLVED IN-CONTRACT by validate-agent (E13/E14 + AC-V3/AC-V4), no user action.

## Loop health

- Gap trajectory: 9 → 3 (improving; no plateau)
- Cycle count: 2/10 cap
- Regression check: new FAILs in already-hot Phase 1↔3 coupling area, not gap-free areas → no HALT_REGRESSION
- Contract: rewritten in plan, generated-by: outer-pvl, supersedes cycle-1 contract, validator 0 failures (939 lines)

## Gate decision pending (BLOCKED escalation step 3 — user choice)

Mechanism choice for scheduled full recompute (Gap 11 root): APScheduler job / celery beat via worker -B / separate beat service / descope with named residual. Orchestrator recommendation: APScheduler (works today, no deploy change, matches live scheduler pattern; cost = scheduler.py enters Phase 3 blast radius + celery/apscheduler duplication NOTE).

Still shippable while BLOCKED: Phase 4d (redis socket_timeout) — no dependency, no FAIL against it.
