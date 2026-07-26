---
name: report:celery-beat-vs-apscheduler-duplication
description: "Inventory of the three dormant Celery beat_schedule jobs — which is superseded by the Phase 3 APScheduler sweep, which are still dead, and the decision owed later"
date: 25-07-26
metadata:
  node_type: memory
  type: report
  feature: general
  phase: capacity-hardening Phase 1 (W3)
---

# Celery `beat_schedule` vs APScheduler — duplication inventory

**TL;DR:** `apps/api/services/celery_app.py:27-40` defines three recurring jobs that have never
run — no beat process is deployed anywhere. One of them is now formally superseded by an
APScheduler job; the other two are still dead with no decided successor. This NOTE records the
inventory so the disposition is not lost. No code change is requested here.

## Verified fact: nothing executes this schedule

- A Celery `beat_schedule` is executed only by a **beat** process: `celery ... beat` or
  `celery ... worker -B`.
- A plain `celery ... worker` consumes queued tasks and runs **no scheduler**.
- No beat process exists: `Dockerfile` CMD is `alembic upgrade head && uvicorn`; `railway.json`
  declares one service with no `startCommand`; `infra/docker-compose.yml` has no worker/beat
  service.

Therefore all three entries below are dormant, and deploying a worker (capacity-hardening Phase
1(a)) would **not** wake them.

## Inventory

| Beat job key | Task | Schedule | Status |
|---|---|---|---|
| `aggregate-visitors-hourly` | `apps.api.tasks.aggregation_tasks.aggregate_all_sites` | `crontab(minute="0")` | **SUPERSEDED** |
| `process-pending-visitors-hourly` | `apps.api.tasks.resolution_tasks.process_all_pending_visitors` | `crontab(minute="15")` | **DEAD — decision owed** |
| `check-segmentation-triggers` | `apps.api.tasks.segmentation_tasks.check_segmentation_triggers` | `crontab(minute="30")` | **DEAD — decision owed** |

### 1. `aggregate-visitors-hourly` — SUPERSEDED

Capacity-hardening Phase 3 adds an APScheduler `aggregation_sweep` job to
`apps/api/jobs/scheduler.py` that performs the same full-recompute across all sites, on a
configurable interval (`aggregation_sweep_interval_minutes`, default 60). It runs in the API
process, needs no worker, and participates in the `agg:debounce:{site_id}` Redis key.

**Consequence:** Celery beat must stay OFF. Running both would double-schedule the unbounded
full-history aggregation sweep — the single most expensive query in the system. This is enforced
as clause (ii) of the Phase 1 exit gate: the worker command carries no `-B`, and no separate
`celery beat` service may be created.

### 2. `process-pending-visitors-hourly` — dead, likely already covered

`apps/api/jobs/scheduler.py:214` registers `_resolution_sweep_job` →
`run_resolution_sweep()` on `resolution_sweep_interval_minutes` (default 30). That looks like a
functional superset of `process_all_pending_visitors`, but **equivalence is unproven** — nobody
has diffed the two code paths for eligibility rules, budget gating, or per-site isolation.

Decision owed: confirm equivalence and delete the beat entry, or port any missing behavior into
`run_resolution_sweep`.

### 3. `check-segmentation-triggers` — dead, no successor found

No APScheduler job calls `segmentation_tasks.check_segmentation_triggers` or any equivalent. This
cadence is genuinely absent from the running system.

Decision owed: either register an APScheduler equivalent (if periodic segmentation re-evaluation
is still wanted) or delete the beat entry and the task if the trigger model has moved on.

## Why the block was not deleted

Deleting entries whose successor status is unproven would destroy the only on-disk record of the
intended cadences (hourly / :15 / :30). The chosen disposition is documentation plus this NOTE.
`celery_app.py` carries a dormant-by-design comment above `beat_schedule` pointing here.

## Follow-up owner

Whoever next touches Celery or scheduling. Not blocking capacity-hardening.
