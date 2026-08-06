---
phase: job-change-detection
date: 2026-08-07
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/job-change-detection_07-08-26/job-change-detection_PLAN_07-08-26.md
---

# Job-Change Detection v1 — EXECUTE Report

**TL;DR** — All 3 phases implemented, backend code-complete and flag-OFF. 1093/1093 unit
tests green including all 3 named regression suites. Migration `a4f2b8c15d70` chained on the
confirmed single head `f1a7c3e05b92`, offline `--sql` clean both directions. **Two gates could
not run in this environment: the integration lane (Docker daemon unavailable) and AC-9
(no dashboard UI exists — the plan's own blast radius excludes `apps/web`).** Not archivable
until those two close.

## What Was Done

### Phase 1 — model, migration, config, safety gates
- **NEW** `apps/api/models/job_change_event.py` — `JobChangeEvent`. No email/name column
  (AC-14), `(site_id, visitor_id)` string pair, no FK (matches `EnrichmentProfile` /
  `IdentitySignal` / `CompanyGraphNode`), non-unique `(site_id, visitor_id)` index so a
  visitor can change jobs more than once (AC-7).
- **NEW** `apps/api/migrations/versions/a4f2b8c15d70_add_job_change_events.py` — chained on
  `f1a7c3e05b92`. `alembic heads` run LIVE first and reported **exactly one head**, so E-2's
  merge-migration branch did not apply.
- **MOD** `apps/api/config.py` — new `## ─── Job-change detection (v1, same-tenant) ───` block:
  `job_change_detection_enabled: bool = False`, `job_change_recheck_daily_cap: int = 200`,
  `job_change_staleness_days: int = 75`, `job_change_min_confidence: float = 0.5`.
- **MOD** `apps/api/main.py` — register `JobChangeEvent` for `create_all`.
- **NEW** `apps/api/services/job_change_detector.py` — 4 safety gates (`_passes_recheck_gates`),
  Redis budget counter, `compare_company`, `corroborate`, `run_recheck`, `record_job_change`,
  `select_stale_visitors_query`.

### Phase 2 — pipeline + triggers
- **NEW** `apps/api/tasks/job_change_tasks.py` — Trigger A `recheck_returning_visitor`,
  Trigger B `sweep_stale_profiles` (per-visitor session/commit, bounded by the daily cap).
- **MOD** `apps/api/services/celery_app.py` — `sweep-job-change-stale-profiles` beat entry at
  `crontab(hour=3, minute=0)`, deliberately off the `:15` cadence of
  `process-pending-visitors-hourly` (both touch `EnrichmentProfile`).
- **MOD** `apps/api/routers/events.py` — flag-gated fire-and-forget `.delay()` after the
  `events_ingested` log.

### Phase 3 — surfacing, erasure, regression
- **MOD** `apps/api/services/auto_drafter.py` — additive optional `trigger_reason` param
  (pre-authorized by the plan's touchpoint note). Omitted → byte-identical prior behavior.
- **MOD** `apps/api/agents/segmenter.py` — batched `job_changed_at` signal beside `ai_source`.
- **MOD** `apps/api/services/hot_contacts.py` — `get_job_change_events()`, with an inline
  comment stating why it is NOT unified with the phantom-pointer query family.
- **MOD** `apps/api/routers/hot_contacts.py` — `GET /api/v1/sites/{site_id}/job-changes`.
- **MOD** `apps/api/routers/visitors.py` — `"job_change_events"` appended to the
  `delete_visitor_data` tuple (AC-12).

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| Detector unit | `pytest tests/unit/test_job_change_detector.py -q` | **36 passed** |
| Config unit | `pytest tests/unit/test_job_change_config.py -q` | **5 passed** |
| Regression (enrich) | `pytest tests/unit/test_content_enrich.py -q` | **PASS** (in combined run) |
| Regression (agent exclusion) | `pytest tests/unit/test_agent_origin_exclusion.py -q` | **PASS** |
| Regression (4-gate template) | `pytest tests/unit/test_identity_signals.py -q` | **PASS** (92 combined) |
| Full unit lane | `pytest tests/unit -m unit -q` | **1093 passed, 2 skipped, 0 failed** |
| Migration offline | `alembic upgrade f1a7c3e05b92:head --sql` | **clean** |
| Migration offline (down) | `alembic downgrade a4f2b8c15d70:f1a7c3e05b92 --sql` | **clean** |
| Route-shadowing (E-4) | live route-index check | **PASS** — job-changes idx 33 < contacts/{visitor_id} idx 36 |
| **Integration lane** | `pytest tests/integration/test_job_change_detection.py -m integration -q` | **NOT RUN — env-blocked** (15 tests collect cleanly) |
| **AC-9 Playwright** | `apps/web/e2e/job-change-dashboard.spec.ts` | **NOT WRITTEN — no UI exists** |

## What Was Skipped or Deferred

1. **Integration lane (AC-2/3/4/7/8/11/12 runtime proof).** Docker daemon unavailable:
   `docker` not on PATH, `open -a Docker` did not bring the daemon up within ~12 min, and
   `/usr/local/bin/docker` subsequently disappeared. Postgres 5433 closed. The 15 integration
   tests are **written and collect cleanly** — they are unexecuted, not absent.
   Classification: `harness-drift` (environment), not product breakage.
2. **AC-9 dashboard surface.** The plan's Blast Radius states *"Packages: `apps/api` only. No
   `apps/web`"* and lists zero `apps/web` touchpoints — yet the validate-contract assigns AC-9 a
   Hybrid Playwright gate marked gap-resolution `B` (fixed in this plan). **This is an internal
   plan contradiction.** Building a dashboard UI would be a hard-stop-class expansion beyond the
   declared blast radius, so I did not do it. The API side of AC-9 IS delivered and tested
   (`GET /{site_id}/job-changes`, site-scoped, PII-free). Surfaced for EVL Step-3 classification.

## Plan Deviations

**D-1 — Trigger A identity check moved from the call site into the task.** Plan step 13 puts
`visitor.identity_status indicates identified` at the ingest call site. The ingest handler holds
no `Visitor` ORM row (visitor rows are built by the aggregator), so checking there would add a DB
round-trip to the hot ingest path for a check the task must repeat anyway. Call site now gates on
the flag only (zero cost); `_recheck_one` does the identity check. Same observable behavior;
AC-2 asserts the outcome, not the line. *Within-blast-radius — implementation detail.*

**D-2 — Budget reserved AFTER the baseline lookup, not before the gates.** Plan step 9 orders
budget → gates → baseline. Implemented as gates → baseline → budget → provider, so a gated-out or
baseline-less visitor does not consume a re-check credit. Strictly more conservative with spend;
AC-4's cap semantics are unchanged and tested. *Within-blast-radius.*

**D-3 — `AutoDrafter.generate_for_visitor` gained `trigger_reason`.** Explicitly pre-authorized
by the plan touchpoint ("additive optional param only"). Required because the existing method
returns `None` without a recent social post, which would have made AC-8 unsatisfiable. Default
`None` preserves prior behavior exactly.

**D-4 — Budget counter fails CLOSED on Redis error**, whereas the `usage_limits.py` OSINT
counter named by E-1 fails OPEN. The INCR+EXPIRE idiom is copied as instructed; only the error
branch differs, because OSINT scans are free while every re-check here spends a paid provider
credit. Failing open would turn a Redis outage into uncapped spend.

**D-5 — `tests/unit/test_content_campaign.py` mock extended.** Its `side_effect=[id_result,
enrich_result]` list was exhausted by the segmenter's new third batch query. Added a third
empty-result element. Test-fixture update forced by an intended additive change; no assertion
weakened.

## Test Infra Gaps Found

- **Docker unavailable in this environment** — blocks the whole integration lane and the
  migration live round-trip. Same posture as every prior migration in this program.
- **`delete_visitor_data` had zero automated coverage** (VALIDATE-confirmed). Closed per E-3:
  `test_erasure_cascade_deletes_job_change_events` asserts the pre-existing tuple tables delete
  too, and pre-asserts each table was actually seeded so the post-delete assertion cannot pass
  vacuously. **Written but unexecuted** — the gap is closed in code, not yet in evidence.
- **Concurrent WS2 program partial state** — `tests/unit/test_ws2_session_classifier.py`
  (untracked) failed mid-session on a missing `Settings.ws2_classifier_enabled`, then went green
  once that program's `config.py` block landed. Outside this plan's blast radius; no action taken.

## Known-Gaps

| # | Gap | Status |
|---|---|---|
| 1 | Migration live round-trip Docker-gated | **still open** — offline `--sql` only |
| 2 | Confidence table (PDL 0.8 / Apollo 0.7 / domain 0.2) uncalibrated | accepted design tradeoff, documented in code |
| 3 | `company_graph` coverage sparse → recall tradeoff | accepted; false negatives are the safe mode |
| 4 | `identity_status` vocabulary in flux | **re-verified live**: `"anonymous"` still current (`events.py:614`, `models/visitor.py`) |
| 5 | **NEW** — integration lane unexecuted (Docker down) | open; 15 tests written + collecting |
| 6 | **NEW** — AC-9 has no dashboard UI to test (plan blast-radius contradiction) | open; needs orchestrator scope decision |

## Closeout Packet

- **Selected plan:** `process/features/visitors-identity/active/job-change-detection_07-08-26/job-change-detection_PLAN_07-08-26.md`
- **Finished:** all 21 checklist items across Phases 1–3, backend-complete, flag-OFF.
- **Verified:** 1093 unit tests, 3 named regression suites, migration both directions offline,
  route-shadowing check, live alembic head check, live `identity_status` re-check.
- **Unverified:** integration lane (env), migration live apply (env), AC-9 dashboard (no UI).
- **Classification:** `Keep in active/testing` — **NOT ready for archival.** Two ACs lack a green
  proving gate; per the vacuous-green ban this plan is not-archivable until Gaps #5 and #6 close.
- **Best next state:** run the integration lane on a machine with Docker, then resolve Gap #6
  (either descope AC-9's Playwright row to the API gate already delivered, or open a follow-up
  plan for the `apps/web` dashboard surface).

## Forward Preview

**Test infra found:** integration lane needs `docker compose -f infra/docker-compose.yml up -d
postgres redis`; unit lane needs nothing. Use `.venv/bin/python3.11 -m pytest` (the `.venv/bin/pytest`
shebang is broken). ORM-constructing unit tests need `import apps.api.main` first.

**Blast radius changes:** `apps/api` only — models, services, tasks, routers, agents, config,
migrations. No `apps/web`, no `apps/pixel`.

**Commands to stay green:**
```
.venv/bin/python3.11 -m pytest tests/unit -m unit -q
.venv/bin/python3.11 -m pytest tests/integration/test_job_change_detection.py -m integration -q
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade f1a7c3e05b92:head --sql
```

**Dependency changes:** none — no new packages.

**Alembic head moved:** `f1a7c3e05b92` → **`a4f2b8c15d70`** (new head). Re-run `alembic heads`
before chaining anything else; concurrent programs move it repeatedly. NOT applied to any real
environment. Note `apps/api/Dockerfile`'s CMD runs `alembic upgrade head` on boot — pushing to
`main` applies this migration in production.
