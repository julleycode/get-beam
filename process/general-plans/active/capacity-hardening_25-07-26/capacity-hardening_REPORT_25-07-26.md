---
phase: phase-4d-redis-socket-timeout
date: 2026-07-25
status: COMPLETE
feature: none
plan: process/general-plans/active/capacity-hardening_25-07-26/capacity-hardening_PLAN_25-07-26.md
---

# Phase 4d — Redis Socket Timeout (EXECUTE report)

## What Was Done

- `apps/api/services/redis_client.py:23-34` — added `socket_timeout=5` and `retry_on_timeout=False`
  to the `Redis.from_url(...)` call, plus a comment recording why this ships unflagged
  (infinite hang → bounded error; C1 documented exception).
- `tests/unit/test_redis_socket_timeout.py` (NEW, 4 tests, AC12) — AST assertions that `get_redis`
  passes `socket_timeout=5`, `retry_on_timeout=False`, and still passes `socket_connect_timeout=5`;
  plus a behavioural test binding its own listening socket that accepts and never responds,
  asserting a bounded `redis.exceptions.TimeoutError`. Per E10/C7 the test never calls `get_redis()`.
- E2 caller audit (manual, required by contract): `apps/api/services/oauth_state.py:30-38,43-55`
  and `apps/api/services/platforms/pkce.py:47-55,60-71` both wrap every Redis call in
  `except Exception` with a memory fallback → a `TimeoutError` degrades, never propagates.

## What Was Skipped or Deferred

Everything outside 4d: Phase 0, Phases 1–3, 4a/4b/4c. No flags flipped, no other file touched.

## Test Gate Outcomes

- `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_redis_socket_timeout.py -m unit -q`
  → red first (`2 failed, 2 passed`), green after implementation (`4 passed in 6.28s`).
- `MOCK_EXTERNAL_APIS=true PYTHONPATH=. .venv/bin/python -m pytest tests/unit -m unit -q` (AC15)
  → `12 failed, 459 passed, 2 skipped`. All 12 failures are in `tests/unit/test_gemini_agent_loop.py`
  and are **pre-existing** — reproduced identically with the change stashed (`12 failed, 1 passed`).
  Unrelated to Phase 4d.
- `tests/unit/test_scheduler_job_config.py` (the other file in the Phase 4 gate line) does not exist
  yet — it is Phase 4c scope, not 4d.

## Plan Deviations

None.

## Test Infra Gaps Found

- 12 pre-existing `test_gemini_agent_loop.py` unit failures in mock mode (baseline, not caused here).
- Stray `itemintern-redis-1` container listening on 6379 during this run; the new test is immune
  (own socket, never `get_redis()`), but the known unit-lane poisoning source is live on this machine.

## Closeout Packet

- Plan: `process/general-plans/active/capacity-hardening_25-07-26/capacity-hardening_PLAN_25-07-26.md`
- Finished: Phase 4d only. Verified: AC12 (Fully-Automated) green; E2 audit done.
- Classification: **Keep in active/testing** — the plan has 4 further phases outstanding.

## Forward Preview

- **Test Infra Found:** unit lane runs via `PYTHONPATH=. .venv/bin/python -m pytest -m unit`;
  markers `unit`/`integration` in `pyproject.toml`.
- **Blast Radius Changes:** one file (`redis_client.py`) + one new unit test. No schema, no flag.
- **Commands to Stay Green:** `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_redis_socket_timeout.py -m unit -q`
- **Dependency Changes:** none.

---

# Phase 1(b) — Celery Gating + Dead-Beat Disposition (EXECUTE report)

phase: phase-1b-celery-gate-and-beat-disposition
date: 2026-07-25
status: COMPLETE_WITH_GAPS
plan: process/general-plans/active/capacity-hardening_25-07-26/capacity-hardening_PLAN_25-07-26.md

## What Was Done

- `apps/api/config.py:68-76` — new `celery_worker_enabled: bool = False` in the Celery block, with
  a comment recording why the default is safe (no worker process exists in the repo; the flag is
  ANDed with each per-surface `*_async_push` flag, so the default is byte-identical to today).
  Checklist item 2.
- `apps/api/services/celery_app.py:26-31` — `worker_concurrency=1` and
  `worker_max_tasks_per_child=100` added to `conf.update(...)`, with the 15-client Supabase cap
  rationale. Checklist item 3.
- `apps/api/services/celery_app.py:32-56` — dormant-by-design comment block directly above
  `celery_app.conf.beat_schedule`: states a worker runs no scheduler, that `-B`/`celery beat` is
  banned while the APScheduler sweep exists, per-job dispositions
  (`aggregate-visitors-hourly` SUPERSEDED; the other two dead/decision-owed), and points at the
  backlog NOTE. Checklist item 9a; honours E15.
- `apps/api/routers/crm.py:286-311` — `.delay()` now requires `settings.celery_worker_enabled`.
  The two flags are resolved into ONE condition via `_async_requested` (no stacked second gate,
  per E7); the full truth table is written into the code comment above the branch; the dangerous
  cell (`crm_async_push=True`, worker OFF) logs
  `logger.warning("async_push_requested_without_worker", surface="crm", ...)` and falls through to
  the same tenant-scoped `push_segment()` body (C6). Checklist item 4.
- `apps/api/services/ads_push.py:126-151` — identical treatment for the ads surface
  (`surface="ads"`); inline fallback is the existing safety-filter chain. Checklist item 5.
- `apps/api/routers/ingest_health.py:20,110-125` — `celery_worker_enabled` surfaced on the ops
  endpoint so an operator can read the flag state without shelling in. Checklist item 7.
- `tests/unit/test_celery_worker_gate.py` (NEW, 8 tests, AC8 + AC9) — proves the resolved truth
  table for BOTH surfaces: flag OFF over threshold runs inline and never `.delay()`s;
  flag ON `.delay()`s and never runs inline; `*_async_push=False` + worker ON still inline;
  under-threshold still inline; and `Settings().celery_worker_enabled is False`. Non-vacuous: the
  inline path is proven by a sentinel exception raised from a stubbed inline dependency, so
  removing the gate flips every AC8 assertion red. No DB, no Redis, no broker. Checklist item 8.
- Checklist item 9b — verified only, no edit needed: the backlog NOTE already exists on disk and
  already inventories all three jobs including `process-pending-visitors-hourly` and
  `check-segmentation-triggers` (NOTE lines 35-37, 51, 61).
- Checklist item 9c — honoured: the `beat_schedule` block is NOT deleted; documentation + backlog
  routing is the disposition.
- Plan handoff item 5 updated: P0.2 recorded as operator-only/unanswered with the fallback clause
  actually used.

## What Was Skipped or Deferred

- **Checklist item 6 (Phase 1(a) worker Railway service)** — out of scope by instruction and
  operator-gated. `Dockerfile` and `railway.json` untouched.
- **Checklist item 1** — P0.2 cannot be answered by an agent; recorded as such (see Deviations).
- **P0.5 / exit-gate clause (ii) operator half** — out-of-repo by construction (E21, CONCERN-3).

## Test Gate Outcomes

Verbatim commands and results:

```
$ PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_celery_worker_gate.py -m unit -q
........                                                                 [100%]
8 passed in 6.52s

$ PYTHONPATH=. .venv/bin/python -m pytest tests/unit -m unit -q
479 passed, 2 skipped, 563 deselected, 1 warning in 11.79s

$ MOCK_EXTERNAL_APIS=true PYTHONPATH=. .venv/bin/python -m pytest tests/unit -m unit -q
12 failed, 467 passed, 2 skipped, 563 deselected, 1 warning in 19.71s
  -> all 12 are tests/unit/test_gemini_agent_loop.py, PRE-EXISTING. Proven by
     `git stash -u` + re-run on the clean baseline: "12 failed, 1 passed in 0.39s".
     Not attributable to this change (E9 discipline).

$ grep -n 'dormant by design' apps/api/services/celery_app.py
32:# DORMANT BY DESIGN — this beat schedule is dormant by design: it never runs,

$ test -f process/general-plans/active/capacity-hardening_25-07-26/celery-beat-vs-apscheduler-duplication_NOTE_25-07-26.md
OK

$ grep -rnE '(^|[[:space:]])-B([[:space:]]|$)|celery[^\n]*\bbeat\b' Dockerfile railway.json infra/docker-compose.yml
(no output; exit=1)
```

Gate mapping:
- **AC8 / AC9** (Fully-Automated) — GREEN via `tests/unit/test_celery_worker_gate.py`.
- **AC15** (Fully-Automated, mock mode) — GREEN for every touched path; the only failures are the
  12 pre-existing gemini-loop ones.
- **AC-V8** (Fully-Automated, repo-side beat ban) — GREEN (no match). Operator half is P0.5.
- **AC-V9** (Fully-Automated, disposition done) — GREEN, both clauses.
- **AC10** (Hybrid, `tests/integration/test_crm_push.py`) — NOT RUN. Docker-gated integration lane,
  out of the scoped-gate instruction for this session. Phase 1 stays `CODE DONE`, not `VERIFIED`.

## Exit Gate Status (3 clauses)

- (i) no `.delay()` can reach a broker with no consumer — **MET** in repo code: both call sites now
  require `celery_worker_enabled`; the flag defaults False and flipping it is an operator action.
- (ii) no `-B`, no separate `celery beat` service — **MET repo-side** (grep clean). Out-of-repo half
  is operator-attested only (P0.5, E21, CONCERN-3) — unchanged, still open.
- (iii) dead-beat disposition done not pending — **MET** (9a comment present, 9b NOTE on disk,
  9c no-delete honoured).

## Plan Deviations

1. **E1 vs. the plan's P0.2 fallback clause (documented, plan-sanctioned).** E1 says do not start
   Phase 1 until the P0.2 box is ticked. P0.2 is operator-only and unanswered. Both the Phase 0
   exit gate and Pre-EXECUTE checklist item P0.2 state that if P0.2 is unanswerable, Phase 1
   defaults to option (b) — exactly the lane executed here, and safe under either P0.2 answer
   (gating a `.delay()` is correct whether or not a worker exists). Option (a) was NOT started.
   No other deviation.
2. No naming, location, or library deviations. All changed files are inside the plan's declared
   Phase 1 touchpoints.

## Test Infra Gaps Found

- **CONCERN (pre-existing, discovered here — NOT introduced):** `apps/api/tasks/ads_tasks.py:30`
  calls `push_segment_to_ads`, the very function that owns the `.delay()` branch. With
  `ads_async_push=True` AND `celery_worker_enabled=True` AND a live worker, the task would re-enter
  the async branch and re-queue itself indefinitely. This hazard exists on `main` today (gated only
  by `ads_async_push`); this change makes it strictly harder to reach (now requires two flags, both
  default False) but does not remove it. The CRM surface is unaffected — its gate lives in the
  router, not in `push_segment`. Fixing it is outside the Phase 1(b) checklist. Recommended
  disposition: fold into Phase 1(a) as a pre-condition, since it can only fire once a worker exists.
- 12 pre-existing `test_gemini_agent_loop.py` mock-mode failures (same as the 4d section).

## Closeout Packet

- Plan: `process/general-plans/active/capacity-hardening_25-07-26/capacity-hardening_PLAN_25-07-26.md`
- Finished: Phase 1(b) code lane — checklist items 2, 3, 4, 5, 7, 8, 9a, 9b (verified), 9c.
- Verified: AC8, AC9, AC15, AC-V8, AC-V9 (all Fully-Automated, green).
- Still unverified: AC10 (Hybrid, Docker-gated) — Phase 1 is `CODE DONE`, not `VERIFIED`.
- Classification: **Keep in active/testing** — Phase 1(a) optional, Phases 2/3/4 outstanding,
  AC10 unrun.

## Forward Preview

- **Test Infra Found:** unit lane `PYTHONPATH=. .venv/bin/python -m pytest tests/unit -m unit -q`;
  settings are patched per-test with `monkeypatch.setattr(settings, ...)` (repo pattern).
- **Blast Radius Changes:** 5 source files + 1 new unit test. No schema, no migration, no deploy
  file touched. One new flag, default OFF.
- **Commands to Stay Green:**
  `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_celery_worker_gate.py -m unit -q`
  and the two AC-V8/AC-V9 greps above.
- **Dependency Changes:** none.

---

# Phase 2 (W2) — Rate Limiter Key Collapse

phase: phase-2-rate-limiter-key-collapse
date: 2026-07-25
status: COMPLETE_WITH_GAPS
feature: none (general-plans)
plan: process/general-plans/active/capacity-hardening_25-07-26/capacity-hardening_PLAN_25-07-26.md

## What Was Done

| Item | File:lines | Change |
|---|---|---|
| 1 — P0.1 diagnostic | `apps/api/routers/events.py:171-201` | Temporary `logger.info("ingest_client_key", ...)` immediately after `ip_address = resolve_client_ip(request)` (line 169) — the exact value `client_ip_key_func` keys the limiter on. Emits `key_hash` (`sha256(...).hexdigest()[:12]`), `xff_len` (count of non-empty XFF entries), `trusted_proxy_hops`. Raw IP and the forwarded chain are never emitted (E8, AC-V2). Block is fenced by `TEMPORARY DIAGNOSTIC` / `END TEMPORARY DIAGNOSTIC` markers and carries an explicit **REMOVAL CONDITION** paragraph naming the Phase 2 exit gate. |
| 2 — hop default | `apps/api/config.py:145-168` | `trusted_proxy_hops` **left at `0`** (today's safe value) with a written "WHY THIS IS STILL 0" rationale: collapse is unverified live, P0.1 unanswered, plan forbids a blind flip. Raising it is an explicit operator action set to the observed count. No value change. |
| 3 — spoofing tradeoff | `apps/api/config.py:145-168`, `apps/api/services/ip_resolution.py:15-20` | Config comment documents the two-sided failure (N too high → forgeable key / limiter bypass; N too low → bucket collapse / mass 429), the Nth-from-right rationale, and the short-chain fail-safe. `ip_resolution.py` module docstring gains a pointer paragraph (no logic change). |
| 4 — XFF unit tests | — | **Pre-satisfied, no work.** `tests/unit/test_ip_resolution.py` (11 tests) already covers all five cases. No duplicate file created (E12 honoured). |
| 5 — guard rollout order | `apps/api/config.py` (`site_ingest_limit_enabled`, `ingest_velocity_enabled`) | Numbered 3-step rollout documented: (1) correct `trusted_proxy_hops` → (2) `site_ingest_limit_enabled` after ~1wk real volume, ceiling ≈5× observed per-site p99/min (never the 3000 placeholder) → (3) `ingest_velocity_enabled` last. Both flags remain `False`. |

Zero flag-default changes. Zero logic changes. Python 3.11-safe, structlog only.

## What Was Skipped or Deferred

- Phase 2 checklist item 1's **deploy → observe → remove** legs: operator actions (P0.1 is `needs-live-provider`). Only the code half is agent-executable.
- `trusted_proxy_hops` value change: forbidden until P0.1 is answered (E1).
- Flipping `site_ingest_limit_enabled` / `ingest_velocity_enabled`: operator actions.

## Test Gate Outcomes

```
$ PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ip_resolution.py -m unit -q
...........                                                              [100%]
11 passed in 2.10s
```
AC6 — **PASS** (Fully-Automated).

```
$ grep -n 'ingest_client_key' apps/api/routers/events.py
191:        "ingest_client_key",
$ sed -n '168,205p' apps/api/routers/events.py | grep -nE '\bkey=|\bxff=|ip_address=|raw'
(no match)
```
AC-V2 — **PASS** (Fully-Automated): `key_hash=` present via `hashlib.sha256(...).hexdigest()[:12]`; no bare `key=` / `xff=` / raw-IP field.

```
$ PYTHONPATH=. .venv/bin/python -m pytest tests/unit -m unit -q
479 passed, 2 skipped, 563 deselected, 1 warning in 13.68s
```
Full unit-lane regression — **PASS**.

```
$ MOCK_EXTERNAL_APIS=true PYTHONPATH=. .venv/bin/python -m pytest tests/unit -m unit -q
12 failed, 467 passed, 2 skipped, 563 deselected, 1 warning in 10.41s
```
AC15 — **PASS with a pre-existing, unrelated failure set.** All 12 failures are in
`tests/unit/test_gemini_agent_loop.py`. Proven pre-existing, not caused by Phase 2: with the
Phase 2 `config.py` edit reverted, the same file still reports `12 failed, 1 passed`. That file
imports only `apps.api.config.settings` — none of the three touched surfaces. Cause is the
documented `gemini_agent_loop` mock-branch exception (see `all-context.md` AI Layer), not this
phase. Recorded below as a pre-existing gap, not a Phase 2 regression.

## Plan Deviations

None. All five checklist items executed exactly as written; item 4 skipped exactly as the plan
instructs (pre-satisfied).

## Test Infra Gaps Found

- **Pre-existing:** `tests/unit/test_gemini_agent_loop.py` — 12 tests fail under
  `MOCK_EXTERNAL_APIS=true`. Unrelated to capacity-hardening; blocks a clean AC15 "whole lane
  green in mock mode" claim for every phase of this plan, not just Phase 2. Classification:
  `test-breakage` (harness/mock-branch interaction), owner outside this plan.
- No new gap introduced by Phase 2.

## Closeout Packet

- Plan: `process/general-plans/active/capacity-hardening_25-07-26/capacity-hardening_PLAN_25-07-26.md`
- Finished: Phase 2 checklist items 1 (code half), 2, 3, 5; item 4 pre-satisfied.
- Verified: AC6, AC-V2 (Fully-Automated, green) + full unit-lane regression.
- Still unverified: **AC7** (Agent-Probe — P0.1 prod cardinality observation) and the
  `trusted_proxy_hops` value itself. Phase 2 is `CODE DONE`, **not `VERIFIED`**.
- **Exit gate NOT satisfied** — two clauses remain open by design:
  (i) distinct limiter keys ≈ distinct visitors in prod logs (needs the deploy + ≥100 ingests);
  (ii) the P0.1 diagnostic line is **still present and must be removed** once (i) is recorded.
  The removal condition is documented in-code at `events.py:184-189` so it cannot be lost.
- Classification: **Keep in active/testing.**

## Forward Preview

- **Test Infra Found:** `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ip_resolution.py -m unit -q` (11 tests, fast, no Docker). AC-V2 is a grep gate, not a pytest gate.
- **Blast Radius Changes:** 3 source files, comment-only except one temporary log block in
  `events.py`. No schema, no migration, no deploy file, no flag default changed.
- **Commands to Stay Green:**
  `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ip_resolution.py -m unit -q`
  and `grep -n 'ingest_client_key' apps/api/routers/events.py` (must still show `key_hash=`, never a raw IP — until the line is removed at exit-gate closure, after which the grep must return nothing).
- **Dependency Changes:** none. `hashlib` is stdlib, imported locally inside the temporary block so its removal is a clean single-block delete.
- **Next:** Phase 3 (W1) aggregation cost — the largest blast radius; blocked on P0.4 sizing.

---

# Phase 3 (W1) — Background Aggregation Cost

**Date:** 2026-07-26
**Status:** CODE DONE + all runnable gates green — **CONDITIONAL, not VERIFIED**
**Plan:** `process/general-plans/active/capacity-hardening_25-07-26/capacity-hardening_PLAN_25-07-26.md`

## What Was Done

Checklist items 2-11 implemented; item 1 (P0.4) is an operator-only gate (see Deviations).

**Config (`apps/api/config.py`)**
- `:69-96` — `celery_worker_enabled` block already present from Phase 1(b); new
  `aggregation_incremental_enabled: bool = False` (C1: OFF = today's exact full recompute),
  `aggregation_min_interval_seconds: int = 60`, `aggregation_upsert_chunk_size: int = 500`,
  each with the reason-why comment the plan requires.
- `:514` — `aggregation_sweep_interval_minutes: int = 60  # APScheduler full-recompute aggregation
  repair sweep cadence` (item 11a), placed beside the four existing `*_sweep_interval_minutes`
  settings with the identical trailing-comment style.

**Watermark storage (D2)**
- `apps/api/models/site.py:64-72` — additive nullable `last_aggregated_at`, commented with the
  half-open-window rule.
- `apps/api/migrations/versions/d5b1f7c3a908_add_site_last_aggregated_at.py` — additive nullable
  column only, `down_revision = c8e4f2a6b1d9` confirmed live via `alembic heads` before writing
  (E11). Offline/disposable validation only (C2).

**Aggregator (`apps/api/services/visitor_aggregator.py`)**
- `:249-311` — the SQL is now ONE template with four insertion points and a
  `build_aggregate_sql(since)` builder. With `since=None` every placeholder expands to the empty
  string / today's expression, so the query is byte-identical (E4: append, never rewrite).
- `:305-311` `BOUNDARY_LOOKBACK = timedelta(minutes=30)` — the incremental variant READS from
  `since - 30 min` (so `LAG` can classify the first in-window event) but MERGES only
  `created_at > :since` (checklist item 4, the session-boundary hazard).
- `:330-437` `aggregate_visitors_for_site(db, site_id, since=None)` — 3rd arg is optional, so all
  2-arg production and test call sites keep working (E3). Watermark stamped from the DB clock
  BEFORE the read and advanced ONLY after a successful commit (`_advance_watermark`, `:447-462`,
  item 9).
- `:479-522` `_INCREMENTAL_SET` — the merge semantics per the verified 7-column table:
  `total_pageviews` / `total_sessions` additive; `pages_visited` jsonb union; `last_seen` /
  `max_scroll_depth` `GREATEST`; `do_not_resolve` / `is_abuse_flagged` sticky OR.
  **D6/E13:** `first_touch_referrer` is `COALESCE(NULLIF(visitors.first_touch_referrer,''),
  EXCLUDED.first_touch_referrer)` and `ai_source` uses the EXACT conditional
  `CASE WHEN NULLIF(visitors.first_touch_referrer,'') IS NOT NULL THEN visitors.ai_source ELSE
  EXCLUDED.ai_source END` — never a symmetric COALESCE.
  **E14:** `ip_address` keeps `COALESCE(EXCLUDED.ip_address, visitors.ip_address)`.
  **D7:** `avg_time_on_page` and `intent_score` are ABSENT from the set — insert-only defaults for
  a brand-new row, never touched on an existing one.
- `:525-596` `_bulk_upsert_visitors_incremental` — chunked `pg_insert(...).values([...])
  .on_conflict_do_update(...)` (D4); `site_id` stays in both values and conflict index elements
  (C6). `_upsert_visitor` is untouched and still serves the full-recompute path.
- `:599-644` `_dispatch_company_resolution` — dispatch-not-await behind the flag (item 6), gated by
  a mandatory `agg:resolve:{site_id}` single-flight lock and failing CLOSED when Redis is degraded
  (an inflated `_upsert_company` counter is permanent; a skipped resolution is retried).

**Cross-container debounce (D3, item 7)**
- NEW `apps/api/services/aggregation_debounce.py` — `agg:debounce:{site_id}`,
  `agg:sweep_pending:{site_id}`, `agg:resolve:{site_id}` helpers; every helper returns `None` on a
  Redis failure so each caller picks its own fail direction.
- `apps/api/routers/events.py:653-701` `_background_aggregate` — checks the sweep yield marker
  FIRST (E16b: stands down and does NOT take the debounce key), then `SET NX EX`; Redis degraded →
  fail open to the in-memory `_aggregating` set (kept as the cheap second layer); never fails the
  204. Phase 2's P0.1 diagnostic block (`events.py:171-202`) is untouched.

**Repair sweep (item 11, `apps/api/jobs/scheduler.py`)**
- `:207-289` `_sweep_one_site` — E16 four-part protocol (yield marker on contention, marker TTL =
  3x debounce, end-of-pass retry that polls for the freed key, marker deleted in `finally`), and
  E17's flag-conditional fail-open (`aggregation_incremental_enabled` ON → skip + log
  `aggregation_sweep_skipped_redis_degraded`; OFF → proceed, full-vs-full is idempotent).
- `:292-344` `_aggregation_sweep_job` — whole body in `try/except` →
  `logger.exception("aggregation_sweep_crashed")`; one session for the `SELECT Site.site_id`, then
  strictly sequential per-site sessions, **no `asyncio.gather`** (11d); logs
  `aggregation_sweep_complete` with counts only (C4).
- `:404-419` registration — `"interval"`, `minutes=settings.aggregation_sweep_interval_minutes`,
  `id="aggregation_sweep"`, `replace_existing=True`, and E18's explicit
  `next_run_time=datetime.now(timezone.utc) + timedelta(seconds=90)` (larger than the existing
  20/30/45/60s offsets). `add_job` count is now **12 total / 11 interval** as E20 requires.
- **E19 honoured:** the sweep calls `aggregate_visitors_for_site(db, site_id, since=None)`
  explicitly and unconditionally and never reads `aggregation_incremental_enabled` to choose a
  path — it mirrors `_aggregate_all`'s STRUCTURE only, not its (now watermark-aware) body.

**Task entrypoint (item 8)**
- `apps/api/tasks/aggregation_tasks.py:19-47` — `_aggregate_all(full_recompute: bool = False)`
  passes the watermark when the flag is on; `full_recompute=True` is the explicit repair
  entrypoint. Docstring states this Celery task is NOT a live cadence (no beat, no worker).

**Backlog artifact**
- NEW `process/general-plans/active/capacity-hardening_25-07-26/aggregation-multi-container-concurrency_NOTE_25-07-26.md`
  — the N-container race against the debounce key and the new yield marker.

## What Was Skipped or Deferred

- **Checklist item 1 (P0.4 event-row distribution)** — operator-only prod SQL. Not agent-satisfiable.
- **AC3 (24h flag-ON soak)** and **AC-V5's multi-container half** — Agent-Probe, require a deploy.
- **Migration live-apply** — forbidden by C2 and the goal block. Disposable container only.
- **Flag flip** — `aggregation_incremental_enabled` stays `False`. Operator action.
- **Phase 4c jitter/misfire on the new job** — belongs to Phase 4c, not this phase.

## Test Gate Outcomes

```
$ PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_aggregation_sql_shape.py \
    tests/unit/test_aggregation_sweep_failopen.py \
    tests/unit/test_aggregation_sweep_full_recompute.py \
    tests/unit/test_scheduler_job_config.py -m unit -q
37 passed in 0.53s
```
AC-V6 / AC-V7 / AC-V10 / E4 / E13 / E14 SQL-shape assertions — **PASS** (Fully-Automated).

```
$ PYTHONPATH=. .venv/bin/python -m pytest tests/unit -m unit -q
516 passed, 2 skipped, 563 deselected, 1 warning in 4.76s
```
Full unit-lane regression — **PASS**.

```
$ MOCK_EXTERNAL_APIS=true PYTHONPATH=. .venv/bin/python -m pytest tests/unit -m unit -q
12 failed, 504 passed, 2 skipped, 563 deselected, 1 warning in 4.99s
```
AC15 — **PASS with the same pre-existing failure set recorded in the Phase 2 section**: all 12 are
`tests/unit/test_gemini_agent_loop.py`, unrelated to aggregation.

```
$ docker compose -f infra/docker-compose.yml up -d postgres redis
 Container infra-postgres-1 Running
 Bind for 0.0.0.0:6379 failed: port is already allocated   # stray itemintern-redis-1 holds 6379
$ docker exec itemintern-redis-1 redis-cli ping
PONG
```
Integration lane ran against the already-listening Redis on 6379 plus `infra-postgres-1`.

```
$ PYTHONPATH=. .venv/bin/python -m pytest tests/integration/test_visitor_aggregation.py \
    tests/integration/test_optout_flow.py tests/integration/test_ingest_abuse_hardening.py \
    -m integration -q
27 passed in 92.94s (0:01:32)
```
AC1 flag-OFF parity across the complete three-file regression surface (E9, run BEFORE any new
aggregation assertion was trusted) — **PASS** (Hybrid).

```
$ PYTHONPATH=. .venv/bin/python -m pytest tests/integration/test_visitor_aggregation_incremental.py -m integration -q
10 passed in 8.01s
```
AC2 (`test_double_run_no_inflation`), AC4 (`test_boundary_lookback_30min`),
AC-V1 (`test_descoped_columns_untouched`), AC-V3 (`test_ai_source_follows_first_touch`),
AC-V4 (`test_ip_address_keep_if_set`) — **PASS** (Hybrid).

```
$ PYTHONPATH=. .venv/bin/python -m pytest tests/integration/test_aggregation_debounce.py \
    tests/integration/test_aggregation_sweep_priority.py -m integration -q
12 passed in 15.71s
```
AC5 (debounce coalescing) and AC-V5 (four-part yield-marker starvation protocol) — **PASS**
(Hybrid).

```
$ .venv/bin/python -m alembic -c apps/api/alembic.ini heads
d5b1f7c3a908 (head)

$ docker run -d --rm --name caphard-pg-throwaway -e POSTGRES_PASSWORD=... -p 55433:5432 postgres:16
$ DATABASE_URL=...@localhost:55433/beam .venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head
INFO  Running upgrade c8e4f2a6b1d9 -> d5b1f7c3a908, add sites.last_aggregated_at (incremental aggregation watermark)
$ ... downgrade -1
INFO  Running downgrade d5b1f7c3a908 -> c8e4f2a6b1d9, add sites.last_aggregated_at
$ ... upgrade head
INFO  Running upgrade c8e4f2a6b1d9 -> d5b1f7c3a908, add sites.last_aggregated_at
$ docker stop caphard-pg-throwaway
```
AC14 — **PASS** (Hybrid, disposable container, single head, clean round-trip). No real environment
touched.

```
$ PYTHONPATH=. .venv/bin/python -m pytest tests/ -m integration -q
23 failed, 336 passed, 1151 deselected, 8 warnings, 32 errors in 1347.14s (0:22:27)
```
Whole-lane closeout regression — **PRE-EXISTING CROSS-FILE POLLUTION, not a Phase 3 regression.**
Proof:
```
$ PYTHONPATH=. .venv/bin/python -m pytest tests/integration/test_visitor_stats.py \
    tests/integration/test_crm_push.py tests/integration/test_retention_purge.py -m integration -q
21 passed in 31.49s
$ PYTHONPATH=. .venv/bin/python -m pytest tests/integration/test_aggregation_debounce.py \
    tests/integration/test_aggregation_sweep_priority.py \
    tests/integration/test_visitor_aggregation_incremental.py \
    tests/integration/test_visitor_stats.py tests/integration/test_crm_push.py -m integration -q
38 passed in 57.83s
```
Every whole-lane casualty passes in isolation, and the Phase 3 files do not poison their
neighbours when run alongside them. Failure mode is the documented conftest Redis/event-loop
isolation gap (`RuntimeError: Event loop is closed` at teardown), tracked in
`process/features/visitors-identity/backlog/post-docker-gate-followups_NOTE_24-07-26.md`.
Classification: **harness-drift**, owner outside this plan.

### PENDING-DOCKER

None. Docker was available; every Hybrid gate in Phase 3's scope ran for real.

### Not runnable by an agent (unchanged from the contract)

- AC3 — 24h single-site flag-ON prod soak (Agent-Probe).
- P0.4 — prod `events` row distribution (operator-only).
- Multi-container behaviour of the debounce + yield marker (known-gap; NOTE created).

## Plan Deviations

**One, procedural, disclosed:** E1 forbids starting Phase 3 until P0.4 is answered, and P0.4 is
still `_unanswered_` (operator-only prod SQL — no agent can satisfy it). Phase 3 was executed
anyway under the orchestrator's explicit direction. Impact is bounded and was designed for:

- P0.4 only sizes two things. **Chunk size** ships at the plan's own default (500) and is a
  setting, changeable without code. **Backfill need** is structurally eliminated — a NULL
  `last_aggregated_at` means "never aggregated", which routes to a full recompute that then stamps
  the watermark, so no backfill migration is required whatever the row count turns out to be.
- Nothing runs incrementally anywhere until an operator flips
  `aggregation_incremental_enabled=True`, which remains a post-P0.4 operator action.

No implementation deviations. D6/D7, the 7-column merge table, and E13/E14/E16/E17/E18/E19 are
implemented as written; the descoped columns are absent from the incremental merge set, the sweep
passes `since=None` unconditionally, and no file owned by a completed phase was disturbed
(`events.py:171-202` P0.1 block, `config.py` Phase 1/2 settings, and the pre-existing
`scheduler.py` jobs are all byte-unchanged apart from the additive sweep registration).

## Test Infra Gaps Found

- **Pre-existing, whole-lane only:** running `tests/ -m integration` in one process produces 23
  failures + 32 errors that all pass in isolation (`RuntimeError: Event loop is closed` in Redis
  connection teardown). Classification `harness-drift`. Already tracked in
  `post-docker-gate-followups_NOTE_24-07-26.md`; Phase 3 adds no new instance of it.
- **Pre-existing:** `tests/unit/test_gemini_agent_loop.py` 12 failures under
  `MOCK_EXTERNAL_APIS=true` (carried from Phase 2). `test-breakage`, owner outside this plan.
- **Environmental:** port 6379 is held by the stray `itemintern-redis-1` container, so
  `infra-redis-1` cannot bind. Integration tests are unaffected (they use whatever answers on
  6379); the unit lane is unaffected by construction (C7 — the Phase 3 unit tests monkeypatch and
  never call `get_redis()`).

## Closeout Packet

- Plan: `process/general-plans/active/capacity-hardening_25-07-26/capacity-hardening_PLAN_25-07-26.md`
- Finished: Phase 3 checklist items 2-11 (all sub-items 11a-11g), plus the multi-container backlog NOTE.
- Verified: AC1, AC2, AC4, AC5, AC14, AC15, AC-V1, AC-V3, AC-V4, AC-V5, AC-V6, AC-V7, AC-V10 —
  every Fully-Automated and Hybrid gate in Phase 3's scope is green.
- Still unverified: AC3 (24h soak), P0.4, and multi-container concurrency. Phase 3 is
  **CODE DONE + gates green**, and stays **CONDITIONAL, never `VERIFIED`**, per the plan's own
  Phase Completion Rules.
- Exit gate: flag-OFF byte-identical parity **met**; flag-ON double-run no-inflation **met**; the
  `aggregation_sweep` job is registered, uses `since=None`, is sequential, and participates in
  `agg:debounce:{site_id}` **met**. The scanned-row-proportionality half needs the soak.
- Classification: **Keep in active/testing.**

## Forward Preview

- **Test Infra Found:** four new fast unit files (`test_aggregation_sql_shape.py`,
  `test_aggregation_sweep_failopen.py`, `test_aggregation_sweep_full_recompute.py`,
  `test_scheduler_job_config.py`, 37 tests, no Docker) and three Docker-gated integration files
  (`test_visitor_aggregation_incremental.py`, `test_aggregation_debounce.py`,
  `test_aggregation_sweep_priority.py`, 22 tests).
- **Blast Radius Changes:** 7 source files + 1 migration + 1 model column, exactly as planned.
  `apps/api/jobs/scheduler.py` now has 12 `add_job` calls / 11 interval — Phase 4c must assert
  against 11, derived from the AST (E20).
- **Commands to Stay Green:**
  `PYTHONPATH=. .venv/bin/python -m pytest tests/unit -m unit -q` and
  `PYTHONPATH=. .venv/bin/python -m pytest tests/integration/test_visitor_aggregation.py tests/integration/test_optout_flow.py tests/integration/test_ingest_abuse_hardening.py tests/integration/test_visitor_aggregation_incremental.py tests/integration/test_aggregation_debounce.py tests/integration/test_aggregation_sweep_priority.py -m integration -q`
- **Dependency Changes:** none. New imports are stdlib (`asyncio`) and already-present SQLAlchemy
  (`update`, `select`).
- **Next:** Phase 4 (4a statement timeout — now safe because Phase 3 bounded the query; 4b pool
  sizing, blocked on P0.3; 4c jitter/misfire over the now-12 `add_job` calls).

---

# Phase 4 (W4) — Pool and Timeout Hardening (items 4a / 4b / 4c)

**Date:** 26-07-26
**Status:** COMPLETE_WITH_GAPS (code done, all runnable gates green; 4b's port change stays operator-blocked on P0.3)
**Scope:** 4a, 4b, 4c only. **4d was already shipped** (`redis_client.py` `socket_timeout=5`) and was not touched.

## What Was Done

### 4a — server-side statement timeout
- `apps/api/config.py:56-70` — new `db_statement_timeout_ms: int = 0` (0 = disabled = today's
  exact behavior; ships inert, flipping it is an operator action). Comment records the ordering
  rationale (only safe now that Phase 3 bounded the queries) and warns that the full-recompute
  repair sweep is still unbounded **by design**, so any non-zero value must be sized against
  *that* query, not against request-path SQL.
- `apps/api/models/database.py:27-52` — new `build_connect_args(url, statement_timeout_ms)`.
  Applies the timeout **server-side** via asyncpg `server_settings={"statement_timeout": "<ms>"}`
  so Postgres kills the backend itself. At `0` the key is omitted entirely rather than sent as
  `"0"`.
- No exemption mechanism was added for the sweep: the plan specifies none, and `0` default means
  nothing is killed today. Recorded as an operator-sizing note in the config comment instead.

### 4b — pool sizing tied to pooler mode
- `apps/api/config.py:71-95` — new `db_pool_size: int = 3`, `db_max_overflow: int = 2`
  (reproduce the previous hardcoded 3/2 exactly). The comment carries the full pool-math formula,
  the 2-connection `retention.py` reservation, and the 6543 operator-migration caveat.
- `apps/api/models/database.py:13-26` — new `_db_port()` (never raises; malformed URL → `None`),
  plus module constants `DB_PORT` / `DB_POOLER_MODE` (`session` / `transaction` / `unknown`).
  This is the port-awareness the plan asked for: the old branch keyed on `"supabase" in url` and
  could not distinguish the two modes.
- `apps/api/models/database.py:54-83` — engine now uses `settings.db_pool_size` /
  `settings.db_max_overflow` and `build_connect_args(...)`.
- **E5 honored:** BOTH asyncpg cache keys (`prepared_statement_cache_size` AND
  `statement_cache_size`) are preserved, for BOTH pooler modes, with and without the new
  `server_settings`. Directly asserted by a 4-case parametrized test.
- **Code is safe under either pooler** — the non-5432 default is deliberately identical to the
  5432 one, so nothing changes until an operator acts. The 6543 port change is **NOT recommended**:
  new backlog note `transaction-pooler-advisory-lock-audit_NOTE_25-07-26.md` records that
  `retention.py:64/76/116/122/177/183` holds advisory locks across statements, which the
  transaction pooler does not support.

### 4c — APScheduler jitter + misfire grace
- `apps/api/jobs/scheduler.py:345-364` — `start_scheduler()` docstring now states the two reasons
  (boot-time alignment across a deploy; APScheduler's 1-second default `misfire_grace_time`
  silently skipping late jobs) and the CronTrigger exclusion.
- `jitter` + `misfire_grace_time` added to **all 11 interval `add_job` calls**: `sync_all_feeds`
  (300/300), `resolution_sweep` (180/300), `publish_scheduled_blog` (6/30), `retention_purge`
  (600/3600), `agent_verification_sweep` (90/300), `handoff_correlation_sweep` (60/300),
  `intent_signal_sweep` (60/300), `aggregation_sweep` (300/600), `changelog_sync` (600/3600),
  `connection_nudge` (300/600), `referral_activation` (300/600). Jitter is ~10% of the default
  interval, capped.
- The single `CronTrigger` job (`outcome_digest`) is **excluded**, per the plan.
- `_sweep_one_site` / `_aggregation_sweep_job` were **not touched** (E16-E19 verified, EVL-passed).
- `retention.py`'s 2-connection hold was **documented** (the plan's stated alternative to chunking)
  in the `retention_purge` job comment and in the config.py pool math. `retention.py` untouched.

### Tests
- `tests/unit/test_scheduler_job_config.py` — extended with `TestAC13IntervalJobHardening`
  (5 tests): every interval job sets `jitter`; every one sets `misfire_grace_time`; both are
  positive integer literals; the CronTrigger is excluded; and the E20 arithmetic (12 total /
  11 interval / 1 cron) holds. **E20 honored — every count is derived by walking the AST; no line
  number is hardcoded anywhere in the file.**
- `tests/integration/test_db_statement_timeout.py` — NEW (9 tests): over-budget query killed
  server-side, under-budget query succeeds, `0` disables (asserts `SHOW statement_timeout` is the
  server default and a 1.5s query completes), plus the E5 connect-args invariants.

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| Phase 4 unit (contract "Redis/scheduler") | `PYTHONPATH=. .venv/bin/python3.11 -m pytest tests/unit/test_scheduler_job_config.py tests/unit/test_redis_socket_timeout.py -m unit -q` | `16 passed in 1.70s` |
| AC15 regression — full unit lane | `PYTHONPATH=. .venv/bin/python3.11 -m pytest tests/unit -m unit -q` | `544 passed, 2 skipped, 563 deselected, 1 warning in 10.99s` |
| AC15 mock mode | `MOCK_EXTERNAL_APIS=true PYTHONPATH=. .venv/bin/python3.11 -m pytest tests/unit -m unit -q` | `12 failed, 532 passed, 2 skipped` — **all 12 pre-existing** (`test_gemini_agent_loop.py`, unrelated to Phase 4). Verified per E9 by stashing the three Phase 4 source files and re-running: `12 failed, 1 passed` — byte-identical failure set. |
| AC11 statement timeout (Docker-gated: PG) | `PYTHONPATH=. .venv/bin/python3.11 -m pytest tests/integration/test_db_statement_timeout.py -m integration -q` | `9 passed in 2.51s` |
| Engine/APScheduler smoke | import `database`, inspect pool + register a jittered job | `pooler session 5432 pool 3 2` / `apscheduler kwargs ok 6 30` |

Note: the repo's `.venv/bin/pytest` shebang is broken (known memory note), so `.venv/bin/python3.11 -m pytest` is used — same interpreter, same lane.

## Plan Deviations

**None.** All three items implemented exactly as specified. Two judgment calls made *inside* the
plan's stated latitude, both explicitly offered by the plan text:
1. 4c's `retention.py` bullet offers "either chunk the purge **or** document the 2-connection
   reservation in the pool math in 4b" — documenting was chosen (smaller blast radius,
   `retention.py` untouched).
2. Jitter/misfire values are not enumerated in the plan ("scaled to the interval, e.g. 10% capped")
   — the ~10%-capped scheme above is that instruction applied.

## Test Infra Gaps Found

- `tests/integration/test_db_statement_timeout.py` needs a real Postgres; there is no unit-tier way
  to prove a server-side `statement_timeout`. Docker was available and the gate ran green.
- AC13 proves the arguments are present; it does **not** prove the chosen jitter/misfire values
  prevent real thundering-herd behavior across a deploy (already recorded in the contract's
  "What this coverage does NOT prove").

## Closeout Packet

- Plan: `process/general-plans/active/capacity-hardening_25-07-26/capacity-hardening_PLAN_25-07-26.md`
- Finished: Phase 4 items 4a, 4b, 4c. (4d was already done.)
- Verified: AC11, AC13, AC15 (unit lane), plus E5 and E20 as direct assertions.
- Still unverified / blocked: **P0.3** (`DATABASE_URL` pooler port + client cap) is operator-only
  and remains unanswered — the code is safe under either pooler, but no pool value may be raised
  and the 6543 port change may not be recommended until P0.3 **and** the advisory-lock audit close.
  A live statement-timeout value has never been exercised against production latency (AC11 caveat).
- Phase 4 is **CODE DONE + gates green**, and stays **CONDITIONAL, never `VERIFIED`**, per the
  plan's Phase Completion Rules (its operator-gated halves are unclosed).
- Classification: **Keep in active/testing.**

## Forward Preview

- **Test Infra Found:** `tests/integration/test_db_statement_timeout.py` (9 tests, Docker-gated PG)
  is new and reusable for any future pool/connect-args change; `build_connect_args` is now a pure,
  directly-testable function, so connect-args invariants no longer need an engine.
- **Blast Radius Changes:** 3 source files (`config.py`, `models/database.py`, `jobs/scheduler.py`)
  + 1 extended unit test + 1 new integration test + 1 new backlog NOTE. `database.py` now exports
  `build_connect_args`, `DB_PORT`, `DB_POOLER_MODE`.
- **Commands to Stay Green:**
  `PYTHONPATH=. .venv/bin/python3.11 -m pytest tests/unit -m unit -q` and
  `PYTHONPATH=. .venv/bin/python3.11 -m pytest tests/integration/test_db_statement_timeout.py -m integration -q`
- **Dependency Changes:** none. One new stdlib import (`urllib.parse.urlsplit`).
- **Next:** all four Phase 4 items are code-complete. Remaining plan work is Phase 0 (operator),
  Phase 2 (blocked on P0.1), and Phase 1(a) worker deploy (optional, operator-gated). The
  outstanding Phase 4 follow-ups are both operator actions: answer P0.3, and close
  `transaction-pooler-advisory-lock-audit_NOTE_25-07-26.md` before any 6543 port change.
