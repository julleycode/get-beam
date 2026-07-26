# PVL Iteration 003 — capacity-hardening

Date: 2026-07-25
Loop: PVL (plan-validate-fix)
Cycle: 3 (supplement for cycle-2 Gaps 10-12; user gate resolved)
Plan: capacity-hardening_PLAN_25-07-26.md

## User decision (BLOCKED escalation step 3)

Mechanism for scheduled full recompute: **APScheduler job** (user-selected over celery worker -B / separate beat service / descope).

## Gaps addressed (3/3, all FAIL)

| Gap | Resolution |
|---|---|
| 10 | False "worker activates beat_schedule" premise removed (verified: no beat process anywhere). Ordering re-derived — 1(a) now optional capacity, last by preference not constraint. New hard guard: `-B`/beat BANNED while APScheduler sweep exists |
| 11 | Phase 3 item 11(a-g): `_aggregation_sweep_job` in jobs/scheduler.py mirroring `aggregation_tasks._aggregate_all`; `aggregation_sweep_interval_minutes` config default 60; participates in `agg:debounce:{site_id}`; pool-aware (sequential per site, no gather). Public Contracts freshness: staleness = sweep interval, in-API-process, NO worker dependency. scheduler.py → Phase 3 touchpoints; blast radius 6→7 files |
| 12 | beat_schedule enumerated: `aggregate-visitors-hourly` SUPERSEDED (code comment required); `process-pending-visitors-hourly` + `check-segmentation-triggers` → backlog NOTE celery-beat-vs-apscheduler-duplication_NOTE_25-07-26.md (created). Phase 1 item 9 + 3-clause exit gate |

## Artifacts

- Plan validator: 0 failures, 0 warnings
- 6 new Verification Evidence rows (sweep AST check, since=None, sweep debounce, beat-off grep, disposition grep, scheduler count 12)
- Next: re-spawn vc-validate-agent from V1 (cycle 3 re-validation)
