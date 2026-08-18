---
name: plan:capacity-hardening
description: "Production capacity hardening of the Beam API — fix aggregation cost blowup, rate-limiter key collapse, missing Celery worker, and pool/timeout gaps"
date: 25-07-26
feature: none
complexity: COMPLEX
---

# Capacity Hardening — Beam API

**Date**: 25-07-26
**Status**: ACTIVE — code W1/W4d landed; remaining **operator flag flips** owned by `plans/260818-0032-scale-ready-getbeam/` (2026-08-18). Do not start a second EXECUTE of W1.
**Complexity**: COMPLEX (5 phases: Phase 0 pre-conditions + 4 workstreams)

## Phase Completion Rules

- A phase is `CODE DONE` when its checklist items are implemented and its Fully-Automated gates pass.
- A phase is `VERIFIED` only when its Fully-Automated **and** Hybrid gates pass and its Agent-Probe
  observations are recorded in the handoff section. Code-only completion is never `VERIFIED`.
- A phase whose only remaining coverage is a Known-Gap row stays `CONDITIONAL`, never `VERIFIED`.
- Phase 0 must be `VERIFIED` before Phases 1, 2, and 3 may start. Phase 4d is exempt.
- Flag flips to `True`, Railway service creation, migration live-apply, and `DATABASE_URL` port
  changes are operator actions and are never part of a phase's completion.

**TL;DR** — Four independent workstreams fix the things that break Beam when real traffic arrives:
(1) background aggregation rescans a site's entire event history on every ingest batch, (2) the
per-IP rate limiter probably collapses every visitor into one bucket behind Railway's edge,
(3) Celery tasks are queued but no worker is deployed so they never run, and (4) the DB pool has
no statement timeout and Redis has no read timeout. Ship in order W3 → W2 → W1 → W4. Everything
new sits behind a config flag defaulting to today's behavior.

---

## Overview

A 3-agent capacity audit found four production bottlenecks, all verified at file:line. None are
theoretical: workstream 3 is an outright correctness bug (user-visible "success" for work that
never happens), and workstream 1 is superlinear — a traffic spike inflates both the cost per
aggregation run *and* the number of runs.

This plan is COMPLEX: four independently shippable phases, each with its own test gates, plus a
Phase 0 of live verifications that must resolve before Phases 1–3 can be correctly sized.

## Goals

| # | Goal | Measured by |
|---|---|---|
| G1 | A single ingest batch never triggers a full-history rescan of a site's events | Aggregation SQL is time-bounded/watermarked; per-site debounce enforced |
| G2 | Every visitor gets their own rate-limit bucket in production | Resolved limiter key varies per visitor in prod logs |
| G3 | Queued Celery tasks either execute or are never queued | No `.delay()` call reaches a broker with no consumer |
| G4 | A single slow query or hung Redis cannot exhaust a container | Server-side `statement_timeout` set; Redis `socket_timeout` set |

## Non-Goals

- No schema migration is expected. If Phase 1 concludes a watermark column is required, it is an
  additive nullable column, offline-validated only (per repo migration convention) and NOT applied
  to any real environment as part of this plan.
- No changes to outreach safety, quota/credit burn rules, or PII logging rules.
- Adjacent quick wins (appendix) are explicitly out of scope.

---

## Acceptance Criteria

| ID | Criterion | proven by | strategy |
|---|---|---|---|
| AC1 | With `aggregation_incremental_enabled=False`, aggregation output is byte-identical to pre-change code | Flag-OFF parity run of the three existing Docker-gated aggregation integration files (`tests/integration/test_visitor_aggregation.py`, `test_optout_flow.py`, `test_ingest_abuse_hardening.py`) | Hybrid |
| AC2 | With the flag ON, running aggregation twice over unchanged events leaves all counters unchanged | Aggregation idempotency integration test (Docker-gated) | Hybrid |
| AC3 | With the flag ON, an incremental run scans rows proportional to new events only, not full history | 24h prod soak comparing duration + scanned rows to baseline | Agent-Probe |
| AC4 | Session boundaries are correct at the window edge (30-min lookback applied) | NEW `tests/integration/test_visitor_aggregation_incremental.py::test_boundary_lookback_30min` (Docker-gated: PG) | Hybrid |
| AC5 | Two concurrent aggregation triggers for one site within `min_interval` produce exactly one run | Redis debounce integration test (Docker-gated) | Hybrid |
| AC6 | `resolve_client_ip` returns the correct entry for hops 0/1/2, short chain, and malformed XFF | Five-case ip-resolution unit test | Fully-Automated |
| AC7 | In production, distinct limiter keys track distinct visitors rather than collapsing to one | P0.1 resolved-key observation in prod logs | Agent-Probe |
| AC8 | With `celery_worker_enabled=False`, no code path calls `.delay()`; work runs inline or reports a deferred state | Celery worker gate unit test | Fully-Automated |
| AC9 | With `celery_worker_enabled=True`, `.delay()` is called and no inline duplicate runs | Celery worker gate unit test | Fully-Automated |
| AC10 | The CRM push endpoint performs real work end-to-end with the worker flag OFF | CRM push integration test (Docker-gated) | Hybrid |
| AC11 | A query exceeding `db_statement_timeout_ms` is killed server-side; `0` disables the timeout | `pg_sleep` statement-timeout integration test (Docker-gated) | Hybrid |
| AC12 | A stalled Redis raises a bounded timeout instead of hanging indefinitely | Redis socket-timeout unit test (monkeypatched socket) | Fully-Automated |
| AC13 | Every `scheduler.add_job` interval call carries explicit `misfire_grace_time` and `jitter` | Scheduler AST/grep assertion test | Fully-Automated |
| AC14 | The new migration's `down_revision` matches the live head and round-trips cleanly | `alembic heads` check + upgrade/downgrade/upgrade on a disposable Postgres | Hybrid |
| AC15 | `MOCK_EXTERNAL_APIS=true` keeps every touched path working keyless | Full unit lane in mock mode | Fully-Automated |

Each Verification Evidence row below back-references the AC id it proves.

**Tier note (supplement cycle 1).** AC1 and AC4 were originally Fully-Automated with a proposed
`tests/unit/test_visitor_aggregator_parity.py`. That file cannot exist: `aggregate_visitors_for_site`
is raw Postgres SQL (`LAG`, `ARRAY_AGG ... FILTER`, `BOOL_OR`, `pg_insert().on_conflict_do_update`),
so every existing test of it is `pytest.mark.integration` (constraint documented at
`tests/integration/test_ingest_abuse_hardening.py:383`). Both are now Hybrid, Docker-gated.


## Phase Ordering and Rationale

```
Phase 0 — Live pre-conditions (blocking, read-only)
   │
   ├──► Phase 1 (W3) Celery worker decision      ← FIRST: correctness bug, cheapest, unblocks nothing else but is user-visible-wrong today
   │
   ├──► Phase 2 (W2) Rate limiter keying         ← SECOND: gated on Phase 0 finding #1; a mass-429 outage is the fastest way to lose real traffic
   │
   ├──► Phase 3 (W1) Aggregation cost            ← THIRD: largest blast radius + only behavior-contract change; wants Phase 0 finding #4 for sizing
   │
   └──► Phase 4 (W4) Pool + timeout hardening    ← LAST: safety net that makes the other three fail gracefully; several items depend on Phase 0 finding #3
```

**Why this order:**

1. **W3 first** — it is the only *correctness* bug (not a capacity limit). CRM push and ads push
   report success to the user while doing nothing. It is also the smallest diff and touches no
   request-path code.
2. **W2 second** — if `trusted_proxy_hops=0` is collapsing all traffic into one 100/min bucket,
   Beam is already dropping real visitor events today. Cheap to fix once Phase 0 proves the key.
3. **W1 third** — biggest win but biggest risk: it is the only workstream that changes a
   documented behavioral contract (full idempotent recompute → bounded/incremental). It benefits
   from knowing real per-site event volumes (Phase 0 finding #4).
4. **W4 last** — a statement timeout added *before* W1 lands would start killing the very
   aggregation queries W1 is about to fix, converting a slow path into an error path. Ordering
   W4 last means the timeout is set against already-bounded queries.

**Ordering constraint CORRECTED (supplement cycle 3, gap 10) — the original hazard does not
exist as stated.** Cycle 1 claimed "deploying a worker activates the dormant `beat_schedule`
`aggregate-visitors-hourly` job." **That is factually false.** Verified against source:

- `celery_app.py:27-40` defines `beat_schedule`, but a schedule is only *executed* by a Celery
  **beat** process — `celery ... beat` or `celery ... worker -B`. A plain `celery ... worker`
  (the exact CMD Phase 1 item 6 specifies) consumes queued tasks and runs **no scheduler**.
- No beat process exists anywhere: not in `Dockerfile` (CMD is `alembic upgrade head && uvicorn`),
  not in `railway.json` (one service, no `startCommand`), not in `infra/docker-compose.yml`.

So deploying the Phase 1(a) worker does **not** activate the hourly sweep, and the cycle-1
justification for hard-ordering 1(a) last is withdrawn.

**Re-derived ordering.** Phase 1(a) is now purely *optional capacity* for the two opt-in async
push surfaces (`crm_async_push`, `ads_async_push`, both default `False`). Nothing in Phases 2–4
gates on it, and it gates nothing. It is therefore ordered **last by preference, not by
constraint** — it is the only item requiring a new Railway service (an operator action with a
deploy-topology and DB-connection cost), so it is cheapest to defer until the code-only phases
have landed and the pool math from Phase 4b is settled.

**Hard guard that DOES survive (new, cycle 3): beat is banned.** Phase 1(a), if and when
executed, MUST use a plain `celery ... worker` with **no `-B` flag**, and no separate
`celery ... beat` service may be created. Reason: Phase 3 adds an APScheduler full-recompute
sweep inside the API process (Phase 3 checklist item 11). Enabling Celery beat would run
`aggregate-visitors-hourly` → `aggregate_all_sites` (the unbounded full-history sweep across
every site) **concurrently with** the APScheduler sweep — double-scheduling the single most
expensive query in the system. While the APScheduler sweep exists, beat stays off. This guard is
an exit-gate item on Phase 1, not a preference.

Effective order: **Phase 1(b) → Phase 2 → Phase 3 → Phase 4 → Phase 1(a) worker deploy
(optional).**

Phases 1(b), 2, 4 are independently shippable in any order after Phase 0 if scheduling demands it.
Phase 3 should not ship before Phase 4's statement-timeout item is at least *planned*, so the
new bounded query has a known ceiling.

---

## Phase 0 — Live Pre-Conditions (blocking, read-only)

No code changes. Four facts must be established before Phases 1–3 are correctly sized. All four
are Agent-Probe / operator-verification tier — they cannot be proven from the repo.

| # | Question | How to verify | Blocks |
|---|---|---|---|
| P0.1 | What is `request.client.host` in production? | Add a temporary `logger.info("ingest_client_key", key_hash=hashlib.sha256(key.encode()).hexdigest()[:12], xff_len=len(request.headers.get("x-forwarded-for","").split(",")))` in `apps/api/routers/events.py` ingest handler. **The resolved key IS the raw client IP — it must never be logged.** Log only the truncated SHA-256 (`key_hash`) plus the chain length (`xff_len`); never the raw IP, never the forwarded chain. The hash preserves cardinality (distinct-key counting still works) while satisfying the repo PII rule (every existing IP log truncates: `company_resolver.py:153,157,160,216,394,404`; `demo.py:222,241,280`). Deploy, observe ≥100 real ingests, count distinct keys vs distinct `visitor_id`. If distinct keys ≪ distinct visitors → collapse confirmed. Remove the log line before Phase 2 ships. | Phase 2 |
| P0.2 | Does an out-of-repo Celery worker exist? | Human step: open the Railway project dashboard, list all services. Confirm whether any service runs `celery -A apps.api.services.celery_app worker`. Also check Redis `LLEN celery` (via Railway Redis console) — a large, non-draining list proves no consumer. | Phase 1 |
| P0.3 | Is `DATABASE_URL` on port 5432 (session pooler) or 6543 (transaction pooler)? | Human step: read `DATABASE_URL` in Railway env vars, note the port. Do NOT paste the value anywhere. Record only `5432` or `6543` and the client cap shown in the Supabase dashboard. | Phase 4 |
| P0.4 | How many `events` rows exist, and what is the per-site distribution? | Read-only SQL against prod (or a recent dump): `SELECT site_id, count(*), min(created_at), max(created_at) FROM events GROUP BY site_id ORDER BY 2 DESC LIMIT 20;` and `SELECT count(*) FROM events;` | Phase 3 |

**Phase 0 exit gate:** all four answers recorded in this plan's `Resume and Execution Handoff`
section. If P0.2 cannot be answered, Phase 1 defaults to option (b) — gate the `.delay()` paths —
which is safe under either answer.

---

## Phase 1 (W3) — Celery Worker: Deploy or Gate

**Problem (restated after source verification — supplement cycle 1).** `Dockerfile` CMD runs only
`alembic upgrade head && uvicorn`. `railway.json` defines one service. No worker process exists
anywhere in the repo. The original framing ("`.delay()` returns false success") was **overstated**:

- `apps/api/routers/crm.py:290` `.delay()` is already gated by `settings.crm_async_push`
  (`config.py:296`, default `False`) **and** `member_count > crm_async_push_threshold`, and it
  already returns an honest deferred state (`pushed=0, queued=True`) — not a false success.
- `apps/api/services/ads_push.py:130` `.delay()` — identical shape, gated by
  `settings.ads_async_push` (`config.py:288`, default `False`) + threshold, returns
  `PushSegmentOutcome(found=True, queued=True)`.
- **The genuinely dead surface is the Celery `beat_schedule`** (`celery_app.py:27-40`): three
  recurring jobs — `aggregate-visitors-hourly` (`crontab(minute="0")`),
  `process-pending-visitors-hourly` (`minute="15"`), `check-segmentation-triggers`
  (`minute="30"`). These are unconditional: they have no flag, no threshold, and no consumer.
  They never fire today. This — not the two guarded `.delay()` sites — is the correctness gap.
- Residual `.delay()` risk is real but conditional: it only materialises if an operator flips
  `crm_async_push`/`ads_async_push` to `True` while no worker runs. That is exactly what the new
  flag must prevent.

**Flag interaction truth table (must be written into the code comment before editing).** Do NOT
stack a second independent gate; resolve the two flags into ONE explicit condition per call site:

| `crm_async_push` / `ads_async_push` | `celery_worker_enabled` | Behavior | Rationale |
|---|---|---|---|
| `False` (default) | `False` (default) | Run inline (today's exact behavior — the `.delay()` branch is never entered) | Byte-identical to today |
| `False` | `True` | Run inline | Operator has a worker but has not opted this path into it; async is opt-in per surface |
| `True` | `False` | **Run inline** and `logger.warning("async_push_requested_without_worker", ...)` | The dangerous cell. Never `.delay()` into a broker with no consumer. Inline is correct because the >threshold size is the only reason async was wanted; if inline is too slow for the request, return the existing `queued=False`-shaped honest error rather than a silent drop |
| `True` | `True` | `.delay()` (today's async branch), return `queued=True` | The intended async path, now provably consumable |

Effective condition at each call site: `if settings.<surface>_async_push and
settings.celery_worker_enabled and member_count > threshold:` → `.delay()`; else inline.

Note: `celery_app.py:23-24` already sets `task_acks_late=True` and `worker_prefetch_multiplier=1`
(correct), but there is **no `worker_concurrency`** — a worker would default to CPU count, and
each worker process opens its own SQLAlchemy pool (3+2), so N_cpu × 5 connections blows the
15-client Supabase cap instantly.

**Decision (to be locked by Phase 0 P0.2):**

- **If no worker exists (expected)** → implement **option (b) first, option (a) second**:
  - (b) Add `celery_worker_enabled: bool = False` to `apps/api/config.py`. Every `.delay()` call
    site checks it: flag OFF → run the work **inline** (awaited) where the work is short and
    correct to do inline, or return an explicit "queued work unavailable" state where it is not.
    This makes today's silent-nothing become either real work or an honest error.
  - (a) Then add a second Railway service running the worker, with `--concurrency=1` and its own
    reduced pool (see Phase 4 pool math). Flip `celery_worker_enabled=True` as an explicit
    operator action once the service is live.
- **If a worker does exist out-of-repo** → skip (b); go straight to (a): pin `--concurrency`,
  document the service in `railway.json`/deploy docs, and size its pool.

**Checklist**

1. Record P0.2 answer in this plan's handoff section.
2. Add `celery_worker_enabled: bool = False` to `apps/api/config.py` beside the existing
   `*_enabled` flags, with a comment stating the default preserves nothing-runs-today only in the
   sense that queueing stops; inline execution is the new default behavior.
3. Add `worker_concurrency = 1` and an explicit `worker_max_tasks_per_child` to
   `apps/api/services/celery_app.py` `conf.update(...)`.
4. `apps/api/routers/crm.py:280-300` — wrap the `.delay()` in
   `if settings.celery_worker_enabled: task.delay(...)` / `else: await <inline coroutine>`.
   The inline path must respect `MOCK_EXTERNAL_APIS` exactly as the task body does.
5. `apps/api/services/ads_push.py:120-140` — same treatment. If the ads push is too long to run
   inline in a request, return an explicit 503/"deferred" state instead of a false success.
6. Add worker service definition: a second Railway service using the same image with
   `CMD celery -A apps.api.services.celery_app worker --concurrency=1 --loglevel=info`.
   Document as an operator step (Railway service creation is a dashboard action, not a repo
   change that auto-applies).
7. Add `apps/api/routers/ingest_health.py` (or an existing ops surface) field reporting
   `celery_worker_enabled` so the operator can see the flag state without shelling in.
8. Unit test: with `celery_worker_enabled=False`, the CRM push path performs the work inline and
   does not call `.delay()`. With `True`, it calls `.delay()` and does not run inline.
9. **Dispose of the three dead `beat_schedule` jobs (gap 12 — the correctness gap must not be
   ticked while still open).** Verified inventory of `celery_app.py:27-40`:

   | Beat job key | Task | Schedule | Disposition |
   |---|---|---|---|
   | `aggregate-visitors-hourly` | `apps.api.tasks.aggregation_tasks.aggregate_all_sites` | `crontab(minute="0")` | **SUPERSEDED** by the Phase 3 APScheduler sweep (Phase 3 checklist item 11). Never revive. |
   | `process-pending-visitors-hourly` | `apps.api.tasks.resolution_tasks.process_all_pending_visitors` | `crontab(minute="15")` | **ROUTE TO BACKLOG NOTE** — likely already superseded by the live APScheduler `resolution_sweep` job (`scheduler.py:214`, `_resolution_sweep_job` → `run_resolution_sweep`), but equivalence is unproven and out of scope here. |
   | `check-segmentation-triggers` | `apps.api.tasks.segmentation_tasks.check_segmentation_triggers` | `crontab(minute="30")` | **ROUTE TO BACKLOG NOTE** — no APScheduler equivalent found; genuinely dead with no successor. Decision deferred. |

   Concrete work items:
   - 9a. Add a code comment directly above `celery_app.conf.beat_schedule` stating that this
     schedule is **dormant by design** (no beat process is deployed, and `-B` is banned — see the
     Phase 1 exit gate), that `aggregate-visitors-hourly` is superseded by the APScheduler sweep in
     `apps/api/jobs/scheduler.py`, and pointing at the backlog NOTE below for the other two.
   - 9b. Write the backlog NOTE at
     `process/general-plans/active/capacity-hardening_25-07-26/celery-beat-vs-apscheduler-duplication_NOTE_25-07-26.md`
     — inventory of the three jobs, which is superseded, which are still dead, and the decision
     owed later (revive under APScheduler vs delete the beat entries entirely).
   - 9c. Do **not** delete the `beat_schedule` block in this plan. Deleting entries whose successor
     status is unproven (`process-pending-visitors-hourly`, `check-segmentation-triggers`) would
     destroy the only record of intended cadences. Documentation + backlog routing is the disposition.

**Exit gate:** (i) no `.delay()` call can reach a broker that has no consumer — every path either
executes or reports honestly; (ii) the worker command contains **no `-B` flag** and no separate
`celery beat` service exists; (iii) the dead-`beat_schedule` disposition is **done, not pending** —
the dormant-by-design code comment (9a) is present and the backlog NOTE (9b) exists on disk. This
gate cannot be ticked while any of the three is outstanding.

---

## Phase 2 (W2) — Rate Limiter Key Collapse

**Problem.** `apps/api/services/rate_limiter.py:49-53` keys the per-IP limiter on
`client_ip_key_func` → `apps/api/services/ip_resolution.py:76-84` → `resolve_client_ip`, which at
`trusted_proxy_hops = 0` (`apps/api/config.py:139`) **ignores `X-Forwarded-For` entirely** and
returns `request.client.host`. Behind Railway's edge that is likely the proxy's address, meaning
every visitor on the platform shares one 100/min bucket → mass 429 under real traffic.

**This is UNVERIFIED live.** Phase 0 P0.1 must run first. Do not flip `trusted_proxy_hops`
blind.

**Spoofing tradeoff (must be documented in the config comment):** trusting N XFF hops means the
client can forge every entry to the *left* of the trusted hops. `resolve_client_ip` already takes
the Nth-from-the-right entry and fails safe when the chain is shorter than N — so the correct
value of N is exactly the number of proxies Beam actually controls, never more. Setting N too
high lets a caller inject an arbitrary key and evade the limiter; too low collapses buckets.

**Checklist**

1. Ship the P0.1 temporary key-logging line (key only, no full chain) — deploy, observe, remove.
2. Set `trusted_proxy_hops` to the observed Railway hop count (expected `1`). Change the default
   in `apps/api/config.py` **only if** P0.1 proves collapse; otherwise leave at 0 and record why.
3. Update the `trusted_proxy_hops` docstring/comment with the spoofing tradeoff above and the
   observed Railway topology.
4. ~~Unit test covering the five XFF cases.~~ **ALREADY SATISFIED — no new work.**
   `tests/unit/test_ip_resolution.py` already contains 11 passing tests covering all five required
   cases (hops=0 ignores XFF; hops=1 last entry; hops=2 second-from-right; short chain falls back
   to `request.client.host`; malformed/empty XFF falls back) plus four more. **Do NOT create
   `tests/unit/test_ip_resolution*.py` or any parallel file.** Extend the existing file ONLY if
   Phase 2 changes `resolve_client_ip` behavior — a default-value change alone does not.
   Gate command: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ip_resolution.py -m unit -q`.
5. **Rollout order for the two OFF-by-default ingest guards** — enable only *after* the per-IP
   key is correct, because both were designed to compensate for a blind per-IP limiter:
   - `site_ingest_limit_enabled` (`config.py:147-149`, 3000/min): enable once per-IP keying is
     correct and a week of real per-site volume is observed. Set the ceiling to ~5× observed p99
     per-site per-minute, never to the audit's placeholder.
   - `ingest_velocity_enabled` (`config.py:158`): enable last. It is the rotating-IP-flood
     detector; with per-IP keying fixed it becomes a second layer, not the primary one.
   Both remain default OFF in code; flipping them is an explicit operator action.

**Exit gate:** distinct limiter keys ≈ distinct visitors in production logs; the existing 11-test
`tests/unit/test_ip_resolution.py` stays green; and the P0.1 temporary diagnostic log line is
**removed** (removal is an exit-gate item, not optional cleanup).

---

## Phase 3 (W1) — Background Aggregation Cost

**Problem (highest risk; all three audit agents converged).**

- `apps/api/services/visitor_aggregator.py:270-312` — `FROM events WHERE site_id = :site_id`
  with **no time bound and no LIMIT**, running two stacked window functions
  (`LAG(created_at) OVER (PARTITION BY visitor_id ORDER BY created_at)` then
  `SUM(is_new_session) OVER (...)`) plus multiple `ARRAY_AGG`s over the site's entire history.
- `visitor_aggregator.py:315-338` — a Python loop issuing **one `_upsert_visitor` round-trip per
  visitor**, all inside one transaction, so every visitor row of the site is locked for the
  duration.
- `visitor_aggregator.py:349-387` `_resolve_companies` — up to 20 `resolve_company_cached` calls
  (potentially external) while still holding the pooled DB connection.
- `apps/api/routers/events.py:338-349` — re-triggered after **every** ingest batch the moment the
  previous run finishes. `_aggregating` (`events.py:30`) is an in-memory per-process set, so it
  dedups only while running and **only within one container**: N containers = N concurrent
  aggregations of the same site.
- The same unbounded query runs again in `apps/api/tasks/aggregation_tasks.py:19-30`, sequentially
  across all sites, also with no LIMIT.

Cost is superlinear under a spike: more events per run *and* more runs.

**Behavioral contract change — state explicitly.** The current docstring
(`visitor_aggregator.py:250-257`) says the full recompute is *intentional*: totals are SET (not
incremented) on conflict, so a re-run is idempotent and self-healing. Bounding the window breaks
that: a bounded recompute can only SET values derived from the window it saw. The plan therefore
requires:

**Verified merge-semantic column table** (source of truth: `_upsert_visitor` `set_` block,
`visitor_aggregator.py:219-244`). Seven columns are window-unsafe, not four. `first_seen` is NOT
one of them — it is insert-only (absent from `set_`) and therefore already safe.

| Column | current `set_` semantic | window-safe? | incremental-path action |
|---|---|---|---|
| `first_seen` | not in `set_` (insert-only) | **already safe** | none |
| `last_seen` | SET | safe (window holds newest) | none |
| `max_scroll_depth` | `GREATEST(...)` | already merged | none |
| `do_not_resolve` | `OR` (sticky) | already merged | none |
| `is_abuse_flagged` | `OR` (sticky) | already merged | none |
| `total_pageviews` | SET | BREAKS | increment / additive merge |
| `total_sessions` | SET | BREAKS | increment; note `session_num` restarts at 1 inside the window |
| `pages_visited` | SET | BREAKS | array union |
| `first_touch_referrer` | SET | BREAKS | **keep-existing-if-set** (see D6) |
| `ai_source` | SET (derived, line 194) | BREAKS | follows `first_touch_referrer` (see D6) |
| `avg_time_on_page` | SET | BREAKS | **DESCOPED from the incremental path** (see D7) |
| `intent_score` | SET (computed in Python, lines 176-186 from all-time inputs) | BREAKS | **DESCOPED from the incremental path** (see D7) |

- The four "BREAKS → merge" columns (`total_pageviews`, `total_sessions`, `pages_visited`, plus
  `first_touch_referrer`/`ai_source` under D6) move from SET-on-conflict to the merge semantic
  named above, or the bounded path is additive against the existing row.
- The two DESCOPED columns are NOT written by an incremental run at all (D7).
- **Risk:** if a bounded run merges the same events twice, counters inflate — the exact failure
  the current full-recompute design avoids. Mitigation: the watermark must be advanced only
  after a successful commit, and the bounded window must be selected by `created_at >
  last_aggregated_at` (a half-open interval), never by a rolling "last N hours" that can overlap.
- A **full-recompute escape hatch** must remain: keep the existing unbounded path callable
  (operator/manual/backfill) so a drifted site can be repaired.

**Design decisions to lock (INNOVATE-level choices already narrowed):**

| Decision | Chosen | Why |
|---|---|---|
| D1 | **Watermark-incremental** as the flagged new path; full recompute retained as the fallback and repair path | Bounded-window recompute still rescans a fixed large window every time; a watermark makes steady-state cost proportional to *new* events |
| D2 | Watermark stored per `(site_id)` — reuse an existing site-level column if one fits; otherwise an additive nullable `last_aggregated_at` column | Avoids a per-visitor watermark table; site granularity matches the trigger granularity |
| D3 | Per-site **debounce / min-interval** (`aggregation_min_interval_seconds`, default 60) enforced in **Redis**, not the in-memory `_aggregating` set | Redis key is shared across containers; the in-memory set is per-process and cannot dedup N containers |
| D4 | Replace the per-visitor loop with a **single bulk upsert** (`pg_insert(...).values([...]).on_conflict_do_update(...)`, chunked) | One round-trip per chunk instead of per visitor; shortens the lock window proportionally |
| D5 | Move `_resolve_companies` **off the request path** — it already runs after `db.commit()` (lines 340→343), so the remaining change is dispatch-not-await | External calls must never block the ingest response |
| D6 | `first_touch_referrer` (and its derived `ai_source`) use **keep-existing-if-set**: an incremental run may only populate them when the stored value is NULL/empty, never overwrite | A window-only recompute would overwrite the true chronological first touch and regress `tests/integration/test_visitor_aggregation.py::test_first_touch_beats_lexicographic_max`, which guards a fixed prior bug. Expressed in the upsert as `COALESCE(NULLIF(visitors.first_touch_referrer,''), EXCLUDED.first_touch_referrer)`. **Fallback:** if keep-existing-if-set proves infeasible in the bulk upsert, these two columns are DESCOPED to full-recompute-only under D7 instead — never left as SET |
| D7 | `avg_time_on_page` and `intent_score` are **DESCOPED from the incremental path**. Incremental runs update only the additive/mergeable columns and leave these two untouched; they are refreshed exclusively by the retained full-recompute (repair/self-heal) path | A correct weighted merge for `avg_time_on_page` would need a stored contributing-event count — that is a second schema change, which this plan explicitly refuses (**no new event-count column, no additional migration**). `intent_score` is computed in Python from all-time inputs (lines 176-186); a window-only recompute would collapse the score that drives segmentation and outreach. Leaving both stale-but-correct-at-last-repair is strictly safer than writing a wrong value every batch |

**D7 staleness tradeoff (explicit) — repair cadence CORRECTED (supplement cycle 3, gap 11).**
After Phase 3 ships flag-ON, the freshness of `avg_time_on_page` and `intent_score` equals the
**repair-path cadence**, not per-ingest-batch.

Cycle 1 named the Celery `beat_schedule` `aggregate-visitors-hourly` job as that cadence. **That
mechanism does not run** — no beat process is deployed anywhere (see Phase Ordering, gap 10), so
no plan item was actually delivering a repair sweep, and the D7 staleness bound was unbacked.

**Mechanism now chosen and delivered by this plan: an APScheduler job.** `apps/api/jobs/scheduler.py`
is the only live scheduler in the system (11 registered jobs, runs in-process under the FastAPI
app). Phase 3 checklist item 11 adds a full-recompute sweep job there, mirroring
`aggregation_tasks.aggregate_all_sites` (sequential per site). Consequences:

- Repair cadence = `aggregation_sweep_interval_minutes` (new setting, **default 60**) — the same
  worst-case 1-hour staleness the original bound assumed, now actually delivered.
- **No worker dependency.** The sweep runs in the API process. Phase 3 flag-ON is therefore no
  longer gated on Phase 1(a) or on any Celery deployment. The cycle-1 gating sentence ("MUST NOT
  ship flag-ON until an equivalent scheduled full recompute exists") is satisfied *by this plan*,
  not deferred.
- Celery beat remains banned while this job exists (Phase 1 exit gate) — two schedulers running
  the same unbounded sweep is the failure this guard prevents.

Segmentation and outreach consume `intent_score`, so this bound is the user-visible contract
change and is recorded in Public Contracts.

**Checklist**

1. Record P0.4 (row count + per-site distribution) — it sizes the chunk size and proves whether a
   backfill of the watermark is even needed.
2. Add to `apps/api/config.py`: `aggregation_incremental_enabled: bool = False`,
   `aggregation_min_interval_seconds: int = 60`, `aggregation_upsert_chunk_size: int = 500`.
   Flag OFF = today's exact full-recompute behavior, byte-for-byte.
3. If D2 needs a column: add an additive nullable `last_aggregated_at` to the sites table via a
   new Alembic revision. **Offline-validated only** — chain-check the `down_revision` against the
   current head (`a9f2c1e7b4d6` as of 24-07-26; re-confirm with `alembic heads`) and prove a clean
   `upgrade → downgrade -1 → upgrade` round-trip on a **disposable** Postgres container. Never
   apply to a real environment as part of this plan.
4. `visitor_aggregator.py` — extract the SQL into a function taking an optional
   `since: datetime | None`. `since=None` reproduces today's query verbatim; `since` set adds
   `AND created_at > :since` to the `session_boundaries` CTE. **Session-boundary caveat:** the
   `LAG` window must see at least one event *before* the window start to decide whether the first
   in-window event opens a new session — so the incremental query reads
   `created_at > since - INTERVAL '30 minutes'` for boundary detection while only *merging* rows
   after `since`.
5. `visitor_aggregator.py:315-338` — replace the per-row loop with a chunked bulk upsert. Keep
   `_upsert_visitor` for the single-row/full-recompute path so behavior under the flag-off path is
   unchanged.
6. `visitor_aggregator.py:349-387` — **`_resolve_companies` already runs after `db.commit()`**
   (commit at line 340, call at line 343), so "move it after commit" is a no-op and is deleted.
   The remaining change is the dispatch half only: behind the flag, **dispatch** the resolution
   rather than awaiting it inline on the ingest path.
   **Double-increment risk to guard:** `_upsert_company` (`visitor_aggregator.py:414-416`) merges
   with `companies.total_visitors + 1`, `companies.total_sessions + EXCLUDED.total_sessions`, and
   `companies.total_pageviews + EXCLUDED.total_pageviews` — all unconditional increments. If a
   dispatched resolution and an inline/second run process the same visitor concurrently, company
   counters inflate. Mitigation required before dispatch ships: either keep resolution
   single-flighted per site (reuse the Phase 3 Redis debounce key namespace, e.g.
   `agg:resolve:{site_id}`), or make the company merge idempotent. Do not enable dispatch without
   one of the two.
7. `apps/api/routers/events.py:338-349` — replace the in-memory `_aggregating` guard with a Redis
   `SET NX EX aggregation_min_interval_seconds` debounce keyed `agg:debounce:{site_id}`. Keep the
   in-memory set as a cheap second layer. If Redis is degraded, fall back to today's behavior
   (fail-open to the existing guard) — never fail the 204.
8. `apps/api/tasks/aggregation_tasks.py:19-30` — pass the watermark through so the hourly sweep
   uses the same incremental path when the flag is on; keep the unbounded call as the explicit
   repair entrypoint.
9. Advance the watermark **only after** a successful commit of that run's upserts.
10. Ensure `MOCK_EXTERNAL_APIS=true` still short-circuits `resolve_company_cached` on the new
    post-commit path.
11. **Add the full-recompute repair sweep to `apps/api/jobs/scheduler.py` (gap 11 — this is what
    makes D7's staleness bound real).** This is the chosen mechanism; Celery beat / `worker -B` /
    a separate beat service were all rejected (see Phase Ordering).
    - 11a. Add `aggregation_sweep_interval_minutes: int = 60` to `apps/api/config.py`, beside the
      existing `*_sweep_interval_minutes` settings (`config.py:441-444`), with the same trailing
      comment style: `# APScheduler full-recompute aggregation repair sweep cadence`.
    - 11b. Add `async def _aggregation_sweep_job()` to `scheduler.py`, following the existing job
      convention exactly: `logger`-instrumented, whole body wrapped in `try/except` with
      `logger.exception("aggregation_sweep_crashed")` so one failure never kills the scheduler.
    - 11c. Job body mirrors `apps/api/tasks/aggregation_tasks.py::_aggregate_all` verbatim in
      shape: open one `async_session()` to `SELECT Site.site_id`, then loop sites **sequentially**,
      opening a fresh `async_session()` per site and calling
      `aggregate_visitors_for_site(db, site_id)` with the **unbounded / full-recompute** path
      (`since=None`) — this job is the repair path, so it must never take the incremental branch.
      Log a single `aggregation_sweep_complete` summary (sites, visitors) — counts only, no PII.
    - 11d. **Pool-awareness (mandatory, not advisory).** The API container's pool is
      `pool_size=3, max_overflow=2` = 5 connections total, shared with request traffic and the
      other 10 scheduler jobs. The sweep therefore processes sites **strictly sequentially, one
      open session at a time** — no `asyncio.gather` over sites, no parallel per-site fan-out, no
      long-lived outer session held across the loop. This is the same constraint that makes
      `_aggregate_all` safe today; do not "optimise" it.
    - 11e. Register via `scheduler.add_job(_aggregation_sweep_job, "interval",
      minutes=settings.aggregation_sweep_interval_minutes, id="aggregation_sweep",
      replace_existing=True, ...)` in `start_scheduler()`. It is an **interval** trigger, so it is
      in scope for Phase 4c: it must carry explicit `jitter` and `misfire_grace_time` like every
      other interval job. This raises the Phase 4c AST-asserted interval-job count from **10 to
      11** (12 `add_job` calls total, 1 still excluded as a `CronTrigger`) — Phase 4c's assertion
      must be updated accordingly if Phase 3 lands first (it does, per the phase order).
    - 11f. **Debounce interaction (must not double with per-ingest runs).** The sweep participates
      in the same Phase 3 Redis debounce introduced in item 7: before aggregating a site it must
      acquire `agg:debounce:{site_id}` via `SET NX EX aggregation_min_interval_seconds`, and skip
      that site (log and continue — never abort the whole sweep) when the key is already held by an
      in-flight per-ingest run. Conversely a per-ingest trigger must not preempt an in-flight sweep
      for the same site. If Redis is degraded, fall back to today's behavior and let the sweep run
      (fail-open, matching item 7) — a duplicate full recompute is idempotent by construction and
      therefore safe; only the *incremental* path is inflation-prone.
    - 11g. The sweep runs regardless of `aggregation_incremental_enabled`. With the flag OFF it is
      redundant-but-harmless (idempotent full recompute); with the flag ON it is the sole writer of
      `avg_time_on_page` and `intent_score` (D7).

**Exit gate:** with the flag OFF, aggregation output is byte-identical to today. With the flag ON,
a second consecutive run over unchanged data produces identical counters (no inflation), and the
scanned-row count is proportional to new events only. **Additionally (gap 11): the
`aggregation_sweep` APScheduler job is registered, uses the full-recompute (`since=None`) path,
processes sites sequentially, and participates in the `agg:debounce:{site_id}` key** — without it
the D7 staleness bound in Public Contracts is unbacked and the flag must not be turned ON.

---

## Phase 4 (W4) — Pool and Timeout Hardening

Four independently shippable items.

**4a — Server-side statement timeout.** `apps/api/models/database.py:11-29` sets no statement
timeout, so a single slow query holds 1 of the container's 5 connections indefinitely. Add via
asyncpg `connect_args`: `{"server_settings": {"statement_timeout": "<ms>"}}`, driven by a new
`db_statement_timeout_ms: int = 0` setting where `0` = disabled = today's behavior. Ship only
*after* Phase 3, so the timeout is set against bounded queries. Suggested first value once
Phase 3 lands: 30_000 ms.

**4b — Pool sizing tied to pooler mode.** Current `pool_size=3, max_overflow=2` (5/container) is
correct for the session pooler (port 5432, 15-client cap). The existing branch keys on
`"supabase" in url`, not on the port, so it cannot distinguish session from transaction mode. Fix:

- Parse the port from `DATABASE_URL`. `database.py:27` sets **two** asyncpg keys, not one:
  `connect_args={"prepared_statement_cache_size": 0, "statement_cache_size": 0}`. **Both must be
  preserved for both pooler modes** when `server_settings` is added — dropping
  `statement_cache_size` regresses the Supabase pooler fix.
- Add `db_pool_size` / `db_max_overflow` settings whose defaults reproduce 3/2 exactly.
- Document the operator migration to the **6543 transaction pooler**: it lifts the client cap and
  is what unlocks larger pools; it forbids session-scoped state (advisory locks held across
  statements, `SET`-based session settings). `apps/api/services/retention.py` uses an advisory
  lock — audit it against transaction-pooler semantics **before** recommending the port change.
  Record the finding; the port change itself is an operator action, not a code change.
- Pool math to document: `containers × (pool_size + max_overflow) + celery_workers ×
  (worker_pool_size + worker_overflow) ≤ client_cap`, with headroom for one deploy overlap
  (old + new container both live).

**4c — Scheduler jitter and misfire grace.** `apps/api/jobs/scheduler.py:207-299` registers
**11** `add_job` calls (verified), not 10, sharing one pool. Caveats:
- **4 are inside conditional blocks** (~:265, :274, :283, :294) — they register only when their
  feature flag/condition is true, so a naive "all jobs" assertion must still find them in the AST
  even though they may not register at runtime.
- **1 is a `CronTrigger`, not an interval** (~:294, `CronTrigger(day_of_week="mon", hour=15,
  timezone="UTC")`). `jitter` semantics differ for cron; **exclude it from the jitter assertion**.
- Therefore, **before** Phase 3 lands: 10 interval calls. **After** Phase 3 item 11e adds the
  `aggregation_sweep` job (which it does — Phase 3 ships first per the phase order): **11 interval
  calls out of 12 total.** Add `jitter` + `misfire_grace_time` to every interval call and exclude
  only the single `CronTrigger` call from the assertion. The AST test must derive the count by
  walking `scheduler.py`, never by hardcoding line numbers (validate-contract E20).
- **Count update (supplement cycle 3, gap 11):** Phase 3 item 11e adds a twelfth `add_job` — the
  `aggregation_sweep` interval job. Phase 3 ships before Phase 4, so 4c's asserted set is **11
  interval calls out of 12 total**, still excluding the single `CronTrigger`. The new sweep job
  must carry `jitter` + `misfire_grace_time` like the rest.

- *Audit correction:* these are `interval` triggers, not cron — they do not tick-align to wall
  clock `:00`. They align to **boot time**, which is worse in one respect: every container in a
  deploy boots within seconds of the others, so the same job fires simultaneously across all
  containers, and the 1-minute `publish_scheduled_blog` job coincides with the longer intervals
  periodically. Jitter is still the correct fix.
- Add `jitter=<seconds>` to each `add_job` interval trigger (APScheduler supports `jitter` on
  `IntervalTrigger`), scaled to the interval (e.g. 10% of the interval, capped).
- Add `misfire_grace_time` explicitly to each job — the default is 1 second, so any job that is
  late (event-loop busy, container under load) is silently skipped rather than run.
- `retention.py` holds two connections for the whole purge (an outer advisory-lock session plus an
  inner delete session). Either bound the purge into chunked batches that release between chunks,
  or document the 2-connection reservation in the pool math in 4b.

**4d — Redis socket timeout.** `apps/api/services/redis_client.py:21-27` sets
`socket_connect_timeout=5` but **no `socket_timeout`**, so a Redis that accepts the connection and
then hangs blocks every awaited call forever. Add `socket_timeout=5` and
`retry_on_timeout=False`. Every caller must already tolerate a Redis exception (the limiter
already degrades to `memory://`); verify the OAuth/PKCE state store callers do too.

**4d ordering note (supplement cycle 1):** 4d is **independently shippable and may be ordered
FIRST within EXECUTE**. It has no Phase 0 dependency, no flag, no schema touch, and no FAIL
against it — it is the only item shippable while the gate is BLOCKED.

**Exit gate:** each of 4a–4d is separately revertable; defaults reproduce current behavior except
4d (which converts an infinite hang into a bounded error — the intended change).

---

## Touchpoints

| File | Lines | Phase | Change |
|---|---|---|---|
| `apps/api/config.py` | ~139, ~147-149, ~158, + new | 1,2,3,4 | New flags: `celery_worker_enabled`, `aggregation_incremental_enabled`, `aggregation_min_interval_seconds`, `aggregation_upsert_chunk_size`, `aggregation_sweep_interval_minutes`, `db_statement_timeout_ms`, `db_pool_size`, `db_max_overflow`; `trusted_proxy_hops` default + comment |
| `apps/api/services/celery_app.py` | 15-24, 27-40 | 1 | `worker_concurrency`, `worker_max_tasks_per_child`; dormant-by-design comment above `beat_schedule` (Phase 1 item 9a) |
| `apps/api/routers/crm.py` | 280-300 | 1 | Flag-gate `.delay()`, inline fallback |
| `apps/api/services/ads_push.py` | 120-140 | 1 | Flag-gate `.delay()`, honest deferred state |
| `Dockerfile` / `railway.json` | CMD / deploy | 1 | Worker service definition (operator-applied) |
| `apps/api/services/ip_resolution.py` | 40-84 | 2 | No logic change; tests + doc of hop semantics |
| `apps/api/routers/events.py` | ~250 (temp log), 338-349 | 0,2,3 | P0.1 temporary key log (added then removed); Redis debounce replaces in-memory `_aggregating` |
| `apps/api/services/visitor_aggregator.py` | 250-257, 270-312, 315-338, 349-387 | 3 | `since` param + boundary lookback; bulk upsert; company resolution moved post-commit |
| `apps/api/tasks/aggregation_tasks.py` | 19-30 | 3 | Pass watermark; keep unbounded repair entrypoint |
| `apps/api/migrations/versions/` | new file | 3 | Additive nullable `last_aggregated_at` (offline-validated only) |
| `apps/api/models/database.py` | 11-29 | 4a,4b | `statement_timeout` via `server_settings`; port-aware pool sizing |
| `apps/api/jobs/scheduler.py` | 207-299 (+ new `_aggregation_sweep_job`) | 3,4c | **Phase 3:** new `_aggregation_sweep_job` + `add_job("aggregation_sweep", interval)` — the full-recompute repair sweep backing D7. **Phase 4c:** `jitter` + `misfire_grace_time` on all interval jobs (count becomes 11 interval jobs after Phase 3) |
| `apps/api/services/retention.py` | purge path | 4c | Chunk the purge or document the 2-connection hold |
| `apps/api/services/redis_client.py` | 21-27 | 4d | `socket_timeout=5` |
| `apps/api/routers/ingest_health.py` | ops surface | 1 | Surface `celery_worker_enabled` |
| `tests/unit/`, `tests/integration/` | new + extended | all | See Verification Evidence |

## Public Contracts

| Contract | Phase | Change | Compatibility |
|---|---|---|---|
| Ingest endpoint response (204) | 2,3 | Unchanged shape. Fewer spurious 429s once keying is fixed. | Backwards compatible |
| CRM push endpoint (`crm.py`) | 1 | With worker disabled, behavior changes from *false success* to either real inline work or an explicit deferred/error state | **Breaking-ish**: callers relying on the (incorrect) immediate 2xx may now see a deferred state. This is the bug being fixed. |
| Ads push (`ads_push.py`) | 1 | Same as above | Same |
| `Visitor` row counters (`total_pageviews`, `total_sessions`, `pages_visited`) | 3 | Semantics move from SET-on-full-recompute to merge-on-incremental **when the flag is on**. `first_seen` is unchanged (insert-only). | Flag OFF = byte-identical. Flag ON = new contract, documented in the D-table above. |
| `Visitor.first_touch_referrer` / `Visitor.ai_source` | 3 | Keep-existing-if-set on the incremental path (D6) — an incremental run may populate but never overwrite | Preserves true chronological first touch; guarded by `test_first_touch_beats_lexicographic_max` |
| `Visitor.avg_time_on_page` / `Visitor.intent_score` | 3 | **Freshness contract changes**: written only by the full-recompute repair path (D7), not per ingest batch. Worst-case staleness = `aggregation_sweep_interval_minutes`, **default 60 minutes**, delivered by the new APScheduler sweep job in `apps/api/jobs/scheduler.py` running **in the API process — no Celery worker and no beat process required** (corrected supplement cycle 3, gap 11). | Values stay correct-as-of-last-repair rather than wrong-every-batch. Segmentation/outreach consume `intent_score` — this bound is user-visible. Operators may tighten/loosen the bound by changing one setting. |
| Celery task queue | 1 | Tasks either execute or are never enqueued | Fixes silent-drop |
| `/health` + ingest-health ops surface | 1 | New `celery_worker_enabled` field | Additive |
| DB schema | 3 | Additive nullable column only | Backwards compatible; offline-validated only |

## Blast Radius

| Phase | Files | Packages | Risk class |
|---|---|---|---|
| Phase 0 | 1 (temporary log line) | `apps/api` | **Low** — read-only + one temporary log; PII rule requires key-only logging |
| Phase 1 (W3) | 7 (adds the `celery_app.py` beat_schedule comment) | `apps/api` + deploy config | **Medium-high** — deploy/runtime topology change; changes a user-visible success/failure contract |
| Phase 2 (W2) | 3 | `apps/api` | **Medium** — trust-boundary logic (XFF spoofing surface); wrong value = either limiter bypass or continued collapse |
| Phase 3 (W1) | 7 + 1 migration (adds `apps/api/jobs/scheduler.py`) | `apps/api` | **High** — largest diff; changes a documented idempotency contract; counter-inflation is the failure mode; schema touch |
| Phase 4 (W4) | 5 | `apps/api` | **Medium** — DB/runtime config; a wrong statement timeout converts slow paths into errors |

High-risk classes present across the plan: **schema/migration** (Phase 3), **deploy/runtime**
(Phase 1, 4), **trust-boundary/permission** (Phase 2). Each therefore requires at least a hybrid
test gate — no known-gap-only coverage is acceptable for these.

## Security Notes

- **Phase 2 is a trust-boundary change.** Raising `trusted_proxy_hops` above the true number of
  controlled proxies lets a caller forge their limiter key and bypass rate limiting entirely
  (spoofing). `resolve_client_ip` already fails safe on a short chain; the remaining risk is
  purely a wrong configured N. Mitigation: N is derived from P0.1 observation, documented in the
  config comment, and covered by the five-case unit test.
- **Phase 0 logging must not log PII.** The resolved key *is* the client IP. Log only
  `key_hash` (truncated SHA-256, 12 hex chars) and the XFF chain *length* — never the raw key,
  never the full forwarded chain (repo rule: structlog events log keys/ids only).
- **Phase 1 inline fallback** must not bypass any existing auth/tenancy check in the task body.
  The inline path must run the same tenant-scoped code, not a shortcut.
- No change to encryption keys, secrets handling, or the `is_emailable_identity` guardrail.

---

## Implementation Checklist

The numbered checklist is delivered phase by phase — see the per-phase **Checklist** blocks in
Phase 0 through Phase 4 above. Execution order is Phase 0 → 1 → 2 → 3 → 4 per the ordering
rationale. Each phase's checklist items are atomic, file-scoped, and individually verifiable.

## Verification Evidence

Test tiers per `vc-test-coverage-plan`. Commands are the repo's exact lanes from
`process/context/tests/all-tests.md`. Integration lane requires
`docker compose -f infra/docker-compose.yml up -d postgres redis` (Docker-gated — flagged
explicitly below per `TESTING.md`).

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| P0.1 resolved-key observation: distinct keys ≈ distinct visitors in prod | Agent-Probe (operator, prod logs) | G2 pre-condition — proves whether collapse is real |
| P0.2 Railway service list + Redis `LLEN celery` | Agent-Probe (operator, dashboard) | G3 pre-condition — proves no consumer exists |
| P0.3 `DATABASE_URL` port read from Railway env | Agent-Probe (operator) | G4 pre-condition — sizes pool math |
| P0.4 `SELECT site_id, count(*) FROM events GROUP BY site_id` | Hybrid (read-only prod/dump SQL) | G1 pre-condition — sizes chunk + backfill need |
| `.venv/bin/python -m pytest tests/unit/test_celery_worker_gate.py -m unit -q` — flag OFF runs inline and never calls `.delay()`; flag ON calls `.delay()` and never runs inline | Fully-Automated | G3 |
| `.venv/bin/python -m pytest tests/unit -m unit -q` — full unit lane green (regression) | Fully-Automated | G1,G2,G3,G4 |
| **Phase 3 regression surface (complete list)** — all three existing integration files that call `aggregate_visitors_for_site` must stay green: `tests/integration/test_visitor_aggregation.py` (incl. `test_first_touch_beats_lexicographic_max`), `tests/integration/test_optout_flow.py` (sticky `do_not_resolve`), `tests/integration/test_ingest_abuse_hardening.py` (sticky `is_abuse_flagged`). Docker-gated: PG+Redis | Hybrid | AC1 / G1 |
| `.venv/bin/python -m pytest tests/unit/test_ip_resolution*.py -m unit -q` — five XFF cases (hops 0/1/2, short chain, malformed) | Fully-Automated | G2 |
| `.venv/bin/python -m pytest tests/integration/test_crm_push.py -q` — CRM push with worker flag OFF completes real work (Docker-gated: needs PG+Redis) | Hybrid | G3 |
| Aggregation parity: flag OFF — `PYTHONPATH=. .venv/bin/python -m pytest tests/integration/test_visitor_aggregation.py tests/integration/test_optout_flow.py tests/integration/test_ingest_abuse_hardening.py -m integration -q` all green (Docker-gated: PG+Redis). **No unit-tier parity file may be created** — the function is raw Postgres SQL | Hybrid | AC1 / G1 (no-regression) |
| Aggregation idempotency: flag ON, run twice over unchanged events → counters unchanged (no inflation) | Hybrid — Docker-gated integration, needs PG | G1 (the primary risk) |
| Aggregation boundary: an event 20 min before the watermark correctly does NOT open a new session for the first in-window event — NEW `tests/integration/test_visitor_aggregation_incremental.py::test_boundary_lookback_30min` (Docker-gated: PG) | Hybrid | AC4 / G1 |
| Redis debounce: two concurrent aggregation triggers for one site within `min_interval` result in exactly one run | Hybrid — Docker-gated, needs Redis | G1 (multi-container dedup) |
| Migration round-trip `upgrade head → downgrade -1 → upgrade head` on a **disposable** Postgres container | Hybrid — Docker-gated | G1 (schema safety) |
| `alembic heads` confirms the new revision's `down_revision` matches the live head before writing it | Fully-Automated | G1 (chain integrity) |
| Statement timeout: a deliberately slow query (`SELECT pg_sleep(...)`) is killed at the configured ms, and `db_statement_timeout_ms=0` disables it | Hybrid — Docker-gated | G4 |
| Redis socket timeout: a stalled Redis raises a bounded timeout error instead of hanging (simulated via a socket that accepts and never responds) | Fully-Automated (unit, monkeypatched) | G4 |
| Scheduler: every `add_job` interval call carries an explicit `misfire_grace_time` and `jitter` (11 interval calls of 12 after Phase 3; CronTrigger excluded) | Fully-Automated (grep/AST assertion test over `scheduler.py`) | G4 |
| Repair sweep registered: AST assertion that `scheduler.py` registers an `add_job(..., id="aggregation_sweep", "interval", minutes=settings.aggregation_sweep_interval_minutes)` and that `_aggregation_sweep_job` contains no `asyncio.gather` (pool-awareness / sequential-per-site guard) | Fully-Automated | G1 / D7 staleness bound |
| Repair sweep uses the full-recompute path: unit test asserts `_aggregation_sweep_job` calls `aggregate_visitors_for_site` with `since=None` (never the incremental branch) regardless of `aggregation_incremental_enabled` | Fully-Automated | G1 / D7 |
| Repair sweep debounce: with `agg:debounce:{site_id}` already held, the sweep skips that site and continues to the next (does not abort the sweep, does not double-run) | Hybrid — Docker-gated, needs Redis | G1 (no double-scheduling) |
| Beat stays off: grep asserts no `-B` flag and no `celery ... beat` invocation in `Dockerfile`, `railway.json`, or `infra/docker-compose.yml` | Fully-Automated | G3 (Phase 1 exit gate ii) |
| Dead-beat disposition done: grep asserts a dormant-by-design comment above `beat_schedule` in `celery_app.py`, and that `process/general-plans/active/capacity-hardening_25-07-26/celery-beat-vs-apscheduler-duplication_NOTE_25-07-26.md` exists | Fully-Automated | G3 (Phase 1 exit gate iii) |
| Mock mode: `MOCK_EXTERNAL_APIS=true` — full unit lane green with every new path exercised | Fully-Automated | All (repo convention) |
| `.venv/bin/python -m pytest tests/ -m integration -q` — full integration lane green before closeout (Docker-gated) | Hybrid | All |
| Prod soak: after Phase 3 ships flag-ON for one site, observe aggregation duration + scanned rows vs baseline for 24h | Agent-Probe (operator) | G1 (real proof) |

**Known gaps (residual — each keeps its phase gate CONDITIONAL until closed):**

| Gap | Why untestable in this plan | Resolution chosen |
|---|---|---|
| True production concurrency behavior (N containers racing the Redis debounce) | Requires 2+ live containers under real load | Backlog artifact + the 24h prod soak probe above; the phase gate stays CONDITIONAL until the soak reports |
| Supabase transaction-pooler (6543) compatibility with `retention.py` advisory locks | Requires a real 6543 endpoint | Backlog note: `transaction-pooler-advisory-lock-audit_NOTE_25-07-26.md`; Phase 4b ships the port-aware code but does NOT recommend the port change until this is closed |
| Real Railway XFF hop count | Cannot be derived from the repo | Closed by Phase 0 P0.1 — this is a blocking pre-condition, not an accepted gap |

## Test Infra Improvement Notes

- No unit-tier harness exists for `aggregate_visitors_for_site` (raw Postgres SQL). Every parity
  and boundary assertion must be Docker-gated integration. A future improvement would be a
  lightweight seeded-Postgres fixture that makes aggregation assertions cheap enough to run in the
  default lane; not in scope for this plan.
- No test captures the emitted SQL string, so "byte-identical SQL under `since=None`" is enforced
  only by construction (append-to-WHERE, never rewrite), not by a gate.

## Supplement Log

| Cycle | Date | Gaps addressed | Notes |
|---|---|---|---|
| 3 | 2026-07-25 | 3 (PVL cycle-2 SUPPLEMENT REQUEST, gaps 10-12) | **Gap 10** — the cycle-1 claim "deploying a worker activates the dormant `beat_schedule` job" is factually FALSE and is withdrawn: a plain `celery ... worker` runs no scheduler; only `celery beat` / `worker -B` does, and neither exists in `Dockerfile`, `railway.json`, or `infra/docker-compose.yml`. Ordering re-derived — Phase 1(a) is now optional capacity (nothing gates on it), ordered last by preference not constraint. New HARD guard added in its place: `-B`/beat is **banned** while the Phase 3 APScheduler sweep exists (double-scheduling the unbounded sweep). **Gap 11** — mechanism chosen and locked by user: **APScheduler job**. Phase 3 checklist item 11 (a-g) adds `_aggregation_sweep_job` to `apps/api/jobs/scheduler.py`, mirroring `aggregate_all_sites` (sequential per site, `since=None` full recompute), new `aggregation_sweep_interval_minutes` (default 60) following the `config.py:441-444` convention, interval trigger in scope for Phase 4c jitter/misfire (count 10→11 interval jobs of 12), pool-awareness mandatory (5-conn pool, no `asyncio.gather`), and participation in the `agg:debounce:{site_id}` Redis key so the sweep never doubles with per-ingest incremental runs. D7 staleness paragraph rewritten; Public Contracts freshness row now reads "sweep interval, default 60 min, APScheduler in-API-process, **no worker dependency**". `scheduler.py` added to Phase 3 touchpoints + blast radius (6→7 files). **Gap 12** — the three `beat_schedule` jobs enumerated from verified source (`celery_app.py:27-40`): `aggregate-visitors-hourly` → SUPERSEDED by the new APScheduler sweep; `process-pending-visitors-hourly` and `check-segmentation-triggers` → routed to backlog NOTE `celery-beat-vs-apscheduler-duplication_NOTE_25-07-26.md` (created). Phase 1 gains checklist item 9 (9a dormant-by-design code comment, 9b the NOTE, 9c explicit no-delete rationale) and its exit gate is rewritten into three clauses so it **cannot be ticked while the disposition is undone**. |
| 1 | 2026-07-25 | 9 (PVL SUPPLEMENT REQUEST, gaps 1-9 / plan updates P1-P9) | Gap 1: verified 7-column merge table replaces the 4-column list; `first_seen` removed (insert-only); D6 keep-existing-if-set for `first_touch_referrer`/`ai_source`; D7 descopes `avg_time_on_page` + `intent_score` to full-recompute-only with an explicit hourly repair-path staleness bound and **no new column / no extra migration**. Gap 2: AC1 + AC4 re-tiered Fully-Automated → Hybrid. Gap 3: parity/boundary gates retargeted to `tests/integration/`; `test_optout_flow.py` + `test_ingest_abuse_hardening.py` added to the regression surface. Gap 4: P0.1 now logs `key_hash` (truncated SHA-256) + `xff_len`, never the raw IP. Gap 5: Phase 1 problem restated around the dead `beat_schedule`; `*_async_push` × `celery_worker_enabled` truth table added. Gap 6: worker deploy (option a) hard-ordered after Phase 3's debounce. Gap 7: the no-op "move after commit" deleted; `_upsert_company` double-increment risk added. Gap 8: Phase 2 item 4 marked already-satisfied (11 existing tests). Gap 9: both asyncpg cache keys preserved; job count corrected to 11 with conditional + CronTrigger caveats. Phase 4d confirmed independently shippable and orderable first. |

---

## Risks and Mitigations

| Risk | Phase | Mitigation |
|---|---|---|
| Incremental aggregation double-counts → inflated visitor counters | 3 | Half-open `created_at > watermark` interval; watermark advanced only post-commit; idempotency test runs the same window twice; full-recompute repair path retained |
| Bounded window mis-detects session boundaries at the window edge | 3 | 30-minute lookback for `LAG` while merging only in-window rows; dedicated boundary test |
| `trusted_proxy_hops` set too high → limiter bypass | 2 | Value derived from observed P0.1 topology only; documented spoofing tradeoff; five-case unit test |
| Statement timeout starts killing legitimate long queries | 4a | Default `0` (disabled); ship after Phase 3 bounds the queries; tune from observed p99 |
| Celery worker service doubles DB connection demand and blows the 15-client cap | 1,4b | `--concurrency=1`; worker gets its own reduced pool; pool math documented and checked against the P0.3 cap |
| Phase 1 inline fallback makes a request path slow enough to time out | 1 | Only paths that are genuinely short run inline; long ones return an explicit deferred state rather than blocking |
| Redis unavailable breaks the new aggregation debounce | 3 | Fail open to the existing in-memory guard; never fail the 204 (matches the limiter's existing degrade-to-memory precedent) |
| Migration applied to prod prematurely | 3 | Offline-validated only; explicit non-goal; the repo already carries 8 migrations pending live-apply and this one joins that queue |

## Dependencies and Blockers

- **Blocking:** Phase 0 findings P0.1 (→ Phase 2), P0.2 (→ Phase 1), P0.3 (→ Phase 4b),
  P0.4 (→ Phase 3 sizing).
- **Operator actions required (not code):** Railway worker service creation (Phase 1), any flag
  flip to `True`, any `DATABASE_URL` port change, any migration live-apply.
- **Interacts with existing pending work:** 8 migrations are already pending live-apply (head
  `a9f2c1e7b4d6` as of 24-07-26). Phase 3's migration appends to that chain — re-confirm with
  `alembic heads` immediately before writing the revision.

## Rollback

| Phase | Rollback |
|---|---|
| 1 | Set `celery_worker_enabled=False` and delete the Railway worker service. Code revert is a single-commit revert; no data written. |
| 2 | Set `trusted_proxy_hops` back to `0` — restores byte-identical prior behavior. Env-var-only, no deploy needed if configured as env. |
| 3 | Set `aggregation_incremental_enabled=False` → full recompute resumes and **self-heals any drifted counters** (this is why the full path must be retained). The additive column is left in place, unused. |
| 4 | Each item independently revertable: `db_statement_timeout_ms=0`; restore prior pool constants; remove `jitter`/`misfire_grace_time`; remove `socket_timeout`. |

---

## Appendix — Adjacent Quick Wins (NOT in scope)

One line each. Do not implement as part of this plan; route to backlog.

- `apps/api/routers/demo.py:330` — query appears to be missing a `site_id` filter (tenancy check).
- `apps/api/routers/events.py:58` and `:80` — statement-level double JSON decode of the same body.
- `apps/api/services/company_resolver.py` + `geoip.py` — create a new `httpx` client per call
  instead of reusing a module-level one.
- `apps/api/dependencies.py:87-89` — JWKS `kid` miss triggers an unbounded outbound fetch; needs a
  cap/negative-cache.
- `apps/api/dependencies.py:188-226` — welcome email is sent inline inside an auth dependency,
  putting an email provider call on the auth hot path.

---

## Validate Contract

Status: CONDITIONAL
Date: 25-07-26
date: 2026-07-25
generated-by: outer-pvl
supersedes: 2026-07-25 (outer-pvl) — PVL cycle 3 re-validation after supplement cycle 3 (3/3 gaps applied, mechanism locked by user); this contract has current evidence

Parallel strategy: sequential (forced)
Rationale: 7-signal score 6/7 (S1 multi-package, S2 schema/API surface, S3 5 independent sections, S5 depth requested, S6 high-risk classes, S7 15+ files) → HIGH → parallel-subagents recommended (4 Layer-1 + 5 Layer-2 = 9 agents, sonnet). This session's tool grant is Read/Bash/Write with no Agent tool, so the identical Layer-1 + Layer-2 role specs were executed sequentially in-thread. Execution-method deviation only — no dimension or section was skipped. Cost guard: not triggered (9 < 30).

### Cycle 3 supplement verification (gaps 10-12 re-checked against source, not trusted)

| Gap | Claim in supplement | Verified? | Evidence |
|---|---|---|---|
| 10 | The cycle-1 premise "deploying a worker activates `beat_schedule`" is false and is withdrawn | **YES** | `grep -rn celery Dockerfile railway.json infra/docker-compose.yml` → zero matches. `railway.json` has no `startCommand` (build+deploy blocks only). `Dockerfile` CMD is alembic+uvicorn. A plain `celery worker` runs no scheduler; only `celery beat` / `worker -B` does. The withdrawal is correct. |
| 10 | New hard guard: `-B` / beat banned while the APScheduler sweep exists | **YES, with a coverage limit** | The stated reason (double-scheduling the unbounded sweep) is sound. The repo-side grep gate is practical and currently clean (tested: no `-B`, no `celery ... beat` in any of the three files). **Limit:** the Phase 1(a) worker service command is created in the Railway dashboard, not in the repo — no repo-side gate can observe it. See CONCERN-3 / E21 / P0.5. |
| 10 | Ordering re-derived: 1(a) is optional capacity, last by preference not constraint | **YES** | Both `.delay()` sites are gated by default-`False` flags plus a threshold (`crm.py:287` / `crm_async_push` `config.py:296`; `ads_push.py:126` / `ads_async_push` `config.py:288`). Nothing in Phases 2-4 references the worker. The re-derivation holds. |
| 11 | `apps/api/jobs/scheduler.py` is the only live scheduler; item 11 adds `_aggregation_sweep_job` there | **YES** | `scheduler.py:205-307` `start_scheduler()` registers 11 `add_job` calls (207/214/229/236/243/250/257/265/274/283/294). No aggregation job exists today. The file is now in Phase 3 touchpoints and blast radius (7 files). |
| 11 | `aggregation_sweep_interval_minutes` follows the `config.py:441-444` convention | **YES** | `config.py:441-444` holds `resolution_sweep_interval_minutes=30`, `agent_verification_sweep_interval_minutes=15`, `handoff_correlation_sweep_interval_minutes=10`, `intent_signal_sweep_interval_minutes=10`, each with a trailing `# APScheduler ... sweep cadence` comment. Item 11a's placement and comment style are exact. |
| 11 | Job body mirrors `aggregation_tasks._aggregate_all` (sequential per site, `since=None`) | **YES, with a conflict** | `aggregation_tasks.py:19-30` `_aggregate_all` is exactly as described: one session to `SELECT Site.site_id`, then a sequential per-site loop with a fresh `async_session()` each. **Conflict:** Phase 3 checklist item 8 instructs an edit to that same function to pass the watermark through, so "mirror `_aggregate_all`" and "always use `since=None`" diverge once item 8 lands. See CONCERN-5 / E19. |
| 11 | Pool-awareness: 5-connection pool, sequential, no `asyncio.gather` | **YES** | `database.py` pool is `pool_size=3, max_overflow=2`. `_aggregate_all` is already strictly sequential for this reason. 11d restates a real constraint. |
| 11 | Interval trigger, in scope for Phase 4c jitter/misfire; count 10→11 of 12 | **YES (count), NO (propagation)** | Verified 11 `add_job` today = 10 interval + 1 `CronTrigger` (`scheduler.py:294-296`, `day_of_week="mon", hour=15`). After Phase 3 the correct figures are 12 total / 11 interval. The cycle-3 count-update paragraph in Phase 4c is right, but three downstream places still carried the pre-cycle-3 numbers (AC13 row, its failing stub, E6) and one Phase 4c bullet still said "the 10 interval calls". All four are corrected in this contract; the plan-body bullet was corrected in place. See CONCERN-4 / E20. |
| 11 | Sweep participates in `agg:debounce:{site_id}`; skips a held site; fail-open lets the sweep run | **NO — two defects** | (i) **Starvation:** the per-ingest path (item 7) re-acquires the key on every expiry, so on a continuously-ingesting site the key is held ~100% of the time and the sweep's single `SET NX` always loses — the site is never repaired and the 60-minute Public Contract bound is unsatisfiable on exactly the hot sites that matter. (ii) **Fail-open direction is wrong:** 11f justifies "let the sweep run" with "a duplicate full recompute is idempotent by construction". True for full-vs-full; **false for full-vs-incremental** — a `since=None` SET racing an additive incremental merge can inflate `total_pageviews`/`total_sessions`, the exact G1 failure mode. See CONCERN-1 / E16 and CONCERN-2 / E17. |
| 11 | The sweep actually delivers a 60-minute repair cadence | **NO — third defect** | Item 11e specifies no `next_run_time`. `scheduler.py:216-227` carries a first-hand repo comment on `resolution_sweep`: "The API process restarts on every deploy, resetting that 30-min timer before it ever elapses — so the sweep effectively never ran and backlogs piled up." A 60-minute interval job on a frequently-deploying service repeats that documented failure and again voids the bound. See CONCERN-1 / E18. |
| 12 | Three beat jobs enumerated from verified source | **YES** | `celery_app.py:27-40` contains exactly `aggregate-visitors-hourly` (`crontab(minute="0")`), `process-pending-visitors-hourly` (`minute="15"`), `check-segmentation-triggers` (`minute="30"`), matching the plan's table task paths. |
| 12 | Backlog NOTE created | **YES — already on disk** | `process/general-plans/active/capacity-hardening_25-07-26/celery-beat-vs-apscheduler-duplication_NOTE_25-07-26.md` exists (3969 bytes, frontmatter present, all three jobs inventoried with dispositions). Exit-gate clause (iii) is therefore half pre-satisfied; only the 9a code comment remains. |
| 12 | Phase 1 exit gate rewritten into three clauses that cannot be ticked while the disposition is undone | **YES** | Exit gate clauses (i)/(ii)/(iii) are explicit and each is grep-checkable (subject to the out-of-repo limit in CONCERN-3). |

**Both cycle-2 FAILs are resolved.** FAIL-A.1 (false mechanism claim) is withdrawn and replaced with verified fact. FAIL-A.2 (unsatisfiable D7 bound) now has a real deliverable. FAIL-A.3 (unresolved dead beat jobs) is closed by item 9a/9b/9c plus the 3-clause exit gate. The residual findings this cycle are all *delivery holes in the newly-chosen mechanism*, each with a single mechanically-determined remedy, and are therefore recorded as CONCERNs with binding execute-agent instructions rather than as blockers.

### Test Gates

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1 | Flag OFF → aggregation output byte-identical to pre-change code | Hybrid | `docker compose -f infra/docker-compose.yml up -d postgres redis` then `PYTHONPATH=. .venv/bin/python -m pytest tests/integration/test_visitor_aggregation.py tests/integration/test_optout_flow.py tests/integration/test_ingest_abuse_hardening.py -m integration -q` | B |
| AC2 | Flag ON → two runs over unchanged events leave counters unchanged | Hybrid | NEW `tests/integration/test_visitor_aggregation_incremental.py::test_double_run_no_inflation` (Docker-gated: PG) | B |
| AC3 | Incremental run scans rows proportional to new events only | Agent-Probe | 24h prod soak, ONE site flag-ON; compare run duration + rows-scanned against the flag-OFF baseline captured the prior 24h | C |
| AC4 | Session boundaries correct at the window edge (30-min lookback) | Hybrid | NEW `tests/integration/test_visitor_aggregation_incremental.py::test_boundary_lookback_30min` (Docker-gated: PG) | B |
| AC5 | Two concurrent triggers for one site within `min_interval` → exactly one run | Hybrid | NEW `tests/integration/test_aggregation_debounce.py` (Docker-gated: Redis) | B |
| AC6 | `resolve_client_ip` correct for hops 0/1/2, short chain, malformed XFF | Fully-Automated | `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ip_resolution.py -m unit -q` — **already exists and passes (11 tests, re-verified cycle 3)** | A |
| AC7 | Distinct limiter keys track distinct visitors in production | Agent-Probe | P0.1 hashed-key observation over >=100 real ingests: count distinct `key_hash` vs distinct `visitor_id` | C |
| AC8 | `celery_worker_enabled=False` → no `.delay()`; work inline or explicit deferred state | Fully-Automated | NEW `tests/unit/test_celery_worker_gate.py` | B |
| AC9 | `celery_worker_enabled=True` → `.delay()` called, no inline duplicate | Fully-Automated | NEW `tests/unit/test_celery_worker_gate.py` | B |
| AC10 | CRM push performs real work end-to-end with the worker flag OFF | Hybrid | `PYTHONPATH=. .venv/bin/python -m pytest tests/integration/test_crm_push.py -m integration -q` (Docker-gated: PG+Redis) | A |
| AC11 | Query over `db_statement_timeout_ms` killed server-side; `0` disables | Hybrid | NEW `tests/integration/test_db_statement_timeout.py` using `SELECT pg_sleep(...)` (Docker-gated: PG) | B |
| AC12 | Stalled Redis raises a bounded timeout instead of hanging | Fully-Automated | NEW `tests/unit/test_redis_socket_timeout.py` — bind a local listening socket that accepts and never responds; MUST NOT call `get_redis()` (conftest pins `REDIS_URL=redis://localhost:6379/15`) | B |
| AC13 **(count corrected, cycle 3)** | Every `add_job` **interval** call carries explicit `misfire_grace_time` and `jitter` | Fully-Automated | NEW `tests/unit/test_scheduler_job_config.py` — AST walk over `apps/api/jobs/scheduler.py`. **After Phase 3 lands: 12 `add_job` calls total, 11 asserted interval calls, 1 excluded `CronTrigger`.** Pre-Phase-3 line map (11 calls): 207/214/229/236/243/250/257/265/274/283/294; conditionals at 264/273/282/291; the excluded `CronTrigger` is the call at 294-296. The 12th call is the new `id="aggregation_sweep"` interval job. The test MUST derive the count from the AST, not hardcode line numbers | B |
| AC14 | New migration's `down_revision` matches live head and round-trips cleanly | Hybrid | `.venv/bin/alembic heads` then `upgrade head` -> `downgrade -1` -> `upgrade head` on a **disposable** Postgres container | B |
| AC15 | `MOCK_EXTERNAL_APIS=true` keeps every touched path working keyless | Fully-Automated | `MOCK_EXTERNAL_APIS=true PYTHONPATH=. .venv/bin/python -m pytest tests/unit -m unit -q` | B |
| AC-V1 (cycle 1) | Under flag ON, the DESCOPED columns are left untouched and the MERGED columns match a full recompute | Hybrid | NEW `tests/integration/test_visitor_aggregation_incremental.py::test_descoped_columns_untouched` — seed, full-recompute, snapshot `avg_time_on_page` + `intent_score`, append new events, run incremental, assert those two are **byte-identical to the snapshot** while `total_pageviews`/`total_sessions`/`pages_visited` match a fresh full recompute | B |
| AC-V2 (cycle 1) | P0.1 diagnostic log emits no raw client IP | Fully-Automated | `grep -n 'ingest_client_key' apps/api/routers/events.py` shows a `key_hash=` field derived via `hashlib.sha256(...).hexdigest()[:12]` and NO bare `key=` / `xff=` field | B |
| AC-V3 (cycle 2) | Under D6 keep-existing-if-set, `ai_source` never desyncs from `first_touch_referrer` | Hybrid | NEW `tests/integration/test_visitor_aggregation_incremental.py::test_ai_source_follows_first_touch` — seed a visitor whose stored `first_touch_referrer='https://www.google.com/'` and `ai_source IS NULL`, append an event referred from `chat.openai.com`, run incremental, assert `first_touch_referrer` is UNCHANGED **and** `ai_source` is still `NULL` (see CONCERN-6: a naive `COALESCE` on `ai_source` fails this) | B |
| AC-V4 (cycle 2) | `ip_address` keeps its existing keep-if-set semantic on the incremental path | Hybrid | Same file, `::test_ip_address_keep_if_set` — `set_["ip_address"]` is `ip_address or Visitor.ip_address` (`visitor_aggregator.py:232`); assert an incremental run with a NULL window IP does not blank a stored IP | B |
| AC-V5 (validate-added, cycle 3) | The repair sweep cannot be starved by a continuously-ingesting site — it aggregates a hot site within one debounce TTL of deferring it | Hybrid | NEW `tests/integration/test_aggregation_sweep_priority.py` (Docker-gated: Redis) — hold `agg:debounce:{site_id}` and renew it on every expiry the way a hot per-ingest path would; assert (1) the sweep sets `agg:sweep_pending:{site_id}` instead of silently skipping, (2) the per-ingest trigger yields while that marker is set and does NOT re-take the debounce key, (3) the sweep's end-of-pass retry acquires the key and runs a full recompute for that site, (4) the marker is deleted afterwards. Gates E16 | B |
| AC-V6 (validate-added, cycle 3) | The repair sweep actually fires on a service that redeploys more often than its interval | Fully-Automated | Extend `tests/unit/test_scheduler_job_config.py` — AST assertion that the `id="aggregation_sweep"` `add_job` call carries an explicit `next_run_time` boot offset, matching the `resolution_sweep` precedent at `scheduler.py:216-227`. Gates E18 | B |
| AC-V7 (validate-added, cycle 3) | Redis-degraded fail-open never lets a full recompute race an incremental run | Fully-Automated | NEW `tests/unit/test_aggregation_sweep_failopen.py` — monkeypatch the sweep's Redis call to raise; assert that with `aggregation_incremental_enabled=True` the sweep SKIPS the site (`aggregate_visitors_for_site` is not called) and logs `aggregation_sweep_skipped_redis_degraded`, and that with the flag `False` it proceeds (full-vs-full is idempotent). Gates E17 | B |
| AC-V8 (validate-added, cycle 3) | No repo-declared command enables Celery beat | Fully-Automated | `grep -rnE '(^\|[[:space:]])-B([[:space:]]\|$)\|celery[^\n]*\bbeat\b' Dockerfile railway.json infra/docker-compose.yml` returns nothing (verified clean at contract time). **Repo-side only** — see CONCERN-3, E21, P0.5 for the out-of-repo half | A |
| AC-V9 (validate-added, cycle 3) | The dead-`beat_schedule` disposition is done, not pending | Fully-Automated | `grep -n 'dormant by design' apps/api/services/celery_app.py` finds the 9a comment above `beat_schedule`, AND `test -f process/general-plans/active/capacity-hardening_25-07-26/celery-beat-vs-apscheduler-duplication_NOTE_25-07-26.md` succeeds (the NOTE already exists — verified on disk at contract time; only the code comment remains) | B |
| AC-V10 (validate-added, cycle 3) | The repair sweep never takes the incremental branch | Fully-Automated | NEW `tests/unit/test_aggregation_sweep_full_recompute.py` — assert `_aggregation_sweep_job` calls `aggregate_visitors_for_site` with `since=None` explicitly, for both values of `aggregation_incremental_enabled`, and that it contains no `asyncio.gather`. Gates E19 + 11d | B |

**Failing stubs (Fully-Automated rows only):**

```
test("should return correct IP for hops 0/1/2, short chain, and malformed XFF", () => {
  throw new Error("NOT IMPLEMENTED - TDD stub: resolve_client_ip five-case coverage")
})
# AC6 NOTE: already implemented and green in tests/unit/test_ip_resolution.py (11 tests) - do NOT create a duplicate file.

test("should not call .delay() when celery_worker_enabled is False", () => {
  throw new Error("NOT IMPLEMENTED - TDD stub: flag OFF runs inline or returns deferred, never .delay()")
})

test("should call .delay() and skip inline work when celery_worker_enabled is True", () => {
  throw new Error("NOT IMPLEMENTED - TDD stub: flag ON queues and does not duplicate inline")
})

test("should raise a bounded timeout when Redis accepts then hangs", () => {
  throw new Error("NOT IMPLEMENTED - TDD stub: socket_timeout=5 converts infinite hang into an error")
})

test("should assert every interval add_job carries misfire_grace_time and jitter", () => {
  throw new Error("NOT IMPLEMENTED - TDD stub: AST assertion over scheduler.py - 12 add_job total after Phase 3, 11 interval asserted, CronTrigger excluded, count derived from AST not hardcoded")
})

test("should keep every touched path working with MOCK_EXTERNAL_APIS=true", () => {
  throw new Error("NOT IMPLEMENTED - TDD stub: full unit lane green in mock mode")
})

test("should emit no raw client IP in the P0.1 diagnostic log", () => {
  throw new Error("NOT IMPLEMENTED - TDD stub: key_hash only, never the resolved IP")
})

test("should register the aggregation_sweep job with an explicit next_run_time boot offset", () => {
  throw new Error("NOT IMPLEMENTED - TDD stub: AC-V6 - a 60-min interval job on a redeploying service never fires without it")
})

test("should skip the site when Redis is degraded and the incremental flag is ON", () => {
  throw new Error("NOT IMPLEMENTED - TDD stub: AC-V7 - full-vs-incremental race inflates counters; stale beats wrong")
})

test("should call aggregate_visitors_for_site with since=None for both flag values", () => {
  throw new Error("NOT IMPLEMENTED - TDD stub: AC-V10 - the sweep is the repair path and must never take the incremental branch")
})

test("should find no -B flag and no celery beat invocation in any deploy file", () => {
  throw new Error("NOT IMPLEMENTED - TDD stub: AC-V8 - repo-side beat ban; the Railway dashboard command is out of scope and is covered by P0.5")
})

test("should find a dormant-by-design comment above beat_schedule and the backlog NOTE on disk", () => {
  throw new Error("NOT IMPLEMENTED - TDD stub: AC-V9 - Phase 1 exit-gate clause (iii)")
})
```

Legacy line form (retained for existing validate-contract consumers):

- Aggregation (Phase 3): `[hybrid: PYTHONPATH=. .venv/bin/python -m pytest tests/integration/test_visitor_aggregation.py tests/integration/test_optout_flow.py tests/integration/test_ingest_abuse_hardening.py -m integration -q + precondition: docker compose -f infra/docker-compose.yml up -d postgres redis]`
- Repair sweep (Phase 3): `[Fully-automated: PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_scheduler_job_config.py tests/unit/test_aggregation_sweep_failopen.py tests/unit/test_aggregation_sweep_full_recompute.py -m unit -q]` and `[hybrid: PYTHONPATH=. .venv/bin/python -m pytest tests/integration/test_aggregation_sweep_priority.py -m integration -q + precondition: redis up]`
- Rate limiter (Phase 2): `[Fully-automated: PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ip_resolution.py -m unit -q]`
- Celery gate (Phase 1): `[Fully-automated: PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_celery_worker_gate.py -m unit -q]`
- Beat ban + disposition (Phase 1): `[Fully-automated: grep -rnE '(^|[[:space:]])-B([[:space:]]|$)|celery[^\n]*\bbeat\b' Dockerfile railway.json infra/docker-compose.yml (expect no match) + grep -n 'dormant by design' apps/api/services/celery_app.py]`
- CRM push (Phase 1): `[hybrid: PYTHONPATH=. .venv/bin/python -m pytest tests/integration/test_crm_push.py -m integration -q + precondition: postgres+redis up]`
- Pool/timeout (Phase 4): `[hybrid: PYTHONPATH=. .venv/bin/python -m pytest tests/integration/test_db_statement_timeout.py -m integration -q + precondition: postgres up]`
- Redis/scheduler (Phase 4): `[Fully-automated: PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_redis_socket_timeout.py tests/unit/test_scheduler_job_config.py -m unit -q]`
- Migration (Phase 3): `[hybrid: .venv/bin/alembic heads + upgrade/downgrade/upgrade on a disposable Postgres container]`
- Regression (all phases): `[Fully-automated: PYTHONPATH=. .venv/bin/python -m pytest tests/unit -m unit -q]` and `[hybrid: PYTHONPATH=. .venv/bin/python -m pytest tests/ -m integration -q]`
- Prod behaviour (Phase 2, 3): `[agent-probe: P0.1 hashed-key cardinality observation; 24h single-site flag-ON aggregation soak]`
- Operator pre-conditions (Phase 0): `[known-gap: P0.2 Railway service list, P0.3 DATABASE_URL port, P0.5 worker start command are operator-only, documented as a pre-EXECUTE human checklist below]`

gap-resolution legend: A = proven now; B = gate added by this plan; C = deferred to a named later phase/probe; D = backlog stub (named residual).

C-4 reconciliation: the `strategy` column carries only the 3 proving strategies (Fully-Automated / Hybrid / Agent-Probe). Known-Gap is never a strategy — it is a named residual, carried in Open Gaps below.

### Pre-EXECUTE Human Checklist (operator-only — NOT agent-executable)

These are human gates, cost-class `needs-live-provider` equivalent (live production/dashboard access). No agent may probe, guess, or satisfy them. EXECUTE of Phases 1, 2, and 3 is illegal until the matching box is ticked and the answer is written into `Resume and Execution Handoff` item 5.

- [ ] **P0.1 — resolved client-IP cardinality (blocks Phase 2).** Ship the diagnostic log, deploy, observe >=100 real ingests, count distinct `key_hash` vs distinct `visitor_id`, then REMOVE the log line. Must log `key_hash` (truncated SHA-256) and `xff_len` only — never the raw IP or the forwarded chain.
- [ ] **P0.2 — Celery worker existence (blocks Phase 1).** OPERATOR-ONLY: open the Railway project dashboard, list services, confirm whether any runs `celery -A apps.api.services.celery_app worker`; check Redis `LLEN celery`. If unanswerable, Phase 1 defaults to option (b) only.
- [ ] **P0.3 — `DATABASE_URL` pooler port + client cap (blocks Phase 4b).** OPERATOR-ONLY: read the Railway env var, record `5432` or `6543` and the Supabase client cap. Never paste the value anywhere.
- [ ] **P0.4 — `events` row count + per-site distribution (blocks Phase 3 sizing).** Read-only SQL against prod or a recent dump.
- [ ] **P0.5 — worker start command verbatim (blocks Phase 1(a) only; NEW cycle 3).** OPERATOR-ONLY: if any Celery service exists or is created, record its start command verbatim into handoff item 5 and confirm it contains **no `-B`** and is not `celery ... beat`. `railway.json` declares no `startCommand`, so the command lives only in the Railway dashboard and **no repo-side gate can see it** — AC-V8 covers the repo half only. This is the enforcement half of the Phase 1 exit-gate clause (ii).

### Repo Convention Gates (enforced for every phase)

| # | Convention | Enforcement |
|---|---|---|
| C1 | New behaviour behind a flag defaulting to today's behaviour | Every new `config.py` setting defaults to the current-behaviour value: `celery_worker_enabled=False`, `aggregation_incremental_enabled=False`, `db_statement_timeout_ms=0`, `db_pool_size=3`, `db_max_overflow=2`. Two deliberate, documented exceptions: 4d `socket_timeout=5` converts an infinite hang into a bounded error and ships unflagged; `aggregation_sweep_interval_minutes=60` adds a *new* idempotent repair sweep that has no current-behaviour equivalent (item 11g — it runs regardless of the incremental flag and is redundant-but-harmless while the flag is OFF). |
| C2 | No live migration application | The Phase 3 revision is offline-validated ONLY: `alembic heads` chain check + `upgrade/downgrade/upgrade` on a **disposable** container. Never `alembic upgrade` against a real environment. It joins the 8 already-pending migrations (head `a9f2c1e7b4d6` as of 24-07-26 — re-confirm before writing). |
| C3 | `MOCK_EXTERNAL_APIS=true` keeps working keyless | AC15. Specifically: the Phase 1 inline CRM/ads path must respect mock mode exactly as the task body does, and the Phase 3 post-commit `resolve_company_cached` path must still short-circuit. |
| C4 | structlog only | No `print()`. The P0.1 diagnostic is a `logger.info` with hashed fields (AC-V2). The new sweep logs `aggregation_sweep_complete` / `aggregation_sweep_crashed` / `aggregation_sweep_skipped_*` with counts and site ids only — no PII. |
| C5 | Python 3.11-safe syntax | Dockerfile is `python:3.11-slim`. No 3.12+ syntax. `X \| None` unions are fine (already used in `ip_resolution.py`). |
| C6 | Multi-tenancy scoping preserved | The Phase 1 inline fallback must call the same tenant-scoped `push_segment` / `push_segment_to_ads` body, not a shortcut. The Phase 3 bulk upsert must keep `site_id` in both the values and the `on_conflict` index elements. The sweep iterates `Site.site_id` and opens one session per site — never a cross-site query. |
| C7 | Unit lane assumes no local Redis on 6379 | `tests/unit/test_redis_socket_timeout.py` (E10) and `tests/unit/test_aggregation_sweep_failopen.py` (AC-V7) must monkeypatch or bind their own socket — never call `get_redis()`. A stray local Redis container is a known cross-run poisoning source. |

### Dimension findings

- Infra fit: **CONCERN** (was FAIL in cycle 2 — resolved) — the false celery-worker/beat premise is withdrawn and replaced with verified fact (no `celery` string in `Dockerfile`, `railway.json`, or `infra/docker-compose.yml`; `railway.json` has no `startCommand`). The chosen mechanism is real and correctly sited: `scheduler.py` is the only live scheduler, `config.py:441-444` is the right home for the new interval setting, and `_aggregate_all` is the right shape to mirror. Residual: three delivery holes in the new sweep — hot-site starvation against the shared debounce key (CONCERN-1), a wrong fail-open direction that permits a full-vs-incremental race (CONCERN-2), and a missing `next_run_time` boot offset that the repo has already been bitten by on `resolution_sweep` (CONCERN-1, part c). Each has one mechanically-determined remedy inside files the plan already owns; all three are bound by E16/E17/E18 and gated by AC-V5/AC-V6/AC-V7.
- Test coverage: **PASS** — AC1/AC4 remain correctly Hybrid against real Docker-gated files; the three-file regression surface is verified; AC-V1/V3/V4 remain assertable. Cycle 3's new sweep is not left ungated: six new Fully-Automated/Hybrid gates (AC-V5..AC-V10) cover registration, boot-offset, full-recompute-only, pool-awareness, fail-open direction, starvation, and the beat ban. The stale interval-job counts that cycle 3 left in AC13, its stub, and E6 are corrected in this contract, and the plan-body Phase 4c bullet was corrected in place. No developed behaviour rests on a Known-Gap alone.
- Breaking changes: **CONCERN** — the Public Contracts freshness row now names a real, delivered mechanism (APScheduler, in-API-process, no worker dependency), which was the cycle-2 defect. Residual: the stated 60-minute bound is only honoured once E16 (starvation) and E18 (boot offset) are implemented; as written, item 11e/11f can produce an unbounded staleness on exactly the busiest sites. Binding instructions restore the bound; no contract text is left un-honourable. The CRM/ads deferred-state contract change and the D6/D7 column semantics are unchanged from cycle 2 and remain correctly documented.
- Security surface: **PASS** — no new surface from cycle 3. The sweep is read-mostly, tenant-iterating, logs counts and site ids only. P0.1 still logs `key_hash` + `xff_len` only (AC-V2). Phase 2's trust-boundary reasoning and `resolve_client_ip`'s fail-safe are unchanged and test-covered by the existing 11 tests. No change to encryption keys, secrets, or the `is_emailable_identity` guardrail.
- Phase 0 (Live pre-conditions): **PASS** — mechanically feasible; PII defect fixed; P0.2/P0.3 correctly quarantined as operator-only; log-line removal is an explicit Phase 2 exit-gate item. New P0.5 added for the out-of-repo worker command. Highest-risk edit: the temporary diagnostic log — its removal is gated, not left to cleanup.
- Phase 1 (Celery worker): **CONCERN** (was FAIL in cycle 2 — resolved) — the phase's own stated correctness gap is now closed: item 9 enumerates all three beat jobs with verified dispositions, 9a/9b/9c are concrete work items, the backlog NOTE already exists on disk, and the 3-clause exit gate cannot be ticked while any part is outstanding. Residual: clause (ii) ("the worker command contains no `-B`") is only mechanically checkable for repo-declared commands; the Railway service command is a dashboard artefact no gate can read (CONCERN-3, E21, P0.5). Highest-risk edit: checklist item 6 (the worker service definition) — it is the one item that must be transcribed correctly by a human.
- Phase 2 (Rate limiter): **PASS** — untouched by cycle 3. Item 4 correctly marked pre-satisfied (11 tests re-verified); the duplicate-file ban is explicit; the gate command is exact. Highest-risk edit: the `trusted_proxy_hops` default — derive from P0.1 observation only.
- Phase 3 (Aggregation): **CONCERN** — item 11(a-g) is a genuine, correctly-sited deliverable and D7's bound now has a mechanism. Residual: (i) 11f starves the sweep on hot sites (CONCERN-1); (ii) 11f's fail-open justification is valid only for full-vs-full and permits a full-vs-incremental inflation race (CONCERN-2); (iii) 11e omits `next_run_time`, repeating a documented repo failure (CONCERN-1c); (iv) checklist items 8 and 11c conflict once item 8 makes `_aggregate_all` watermark-aware while 11c says to mirror it (CONCERN-5); (v) cycle-2's CONCERN-1/2 on `ai_source` and `ip_address` carry forward as CONCERN-6/CONCERN-7, already bound by E13/E14 and gated by AC-V3/AC-V4. Highest-risk edit: `visitor_aggregator.py:219-244` (the `set_` block) — unchanged from cycle 2.
- Phase 4 (Pool/timeout): **CONCERN** (was PASS in cycle 2 — a cycle-3 regression) — 4a/4b/4d are unchanged and clean; both asyncpg cache keys re-verified at `database.py:27`. Regression: Phase 3's new twelfth job changed 4c's arithmetic, and while cycle 3 added an explicit "Count update" paragraph, the bullet two lines above it still instructed "the 10 interval calls", and AC13/its stub/E6 still carried pre-cycle-3 numbers. Corrected in this contract (E20) and in the plan body. Highest-risk edit: `database.py:27` — do not drop `statement_cache_size`.

### Net gate derivation

| Layer 1 dimensions | Status |
|---|---|
| Infra fit | CONCERN |
| Test coverage | PASS |
| Breaking changes | CONCERN |
| Security surface | PASS |

| Layer 2 sections | Status |
|---|---|
| Phase 0 — Live pre-conditions | PASS |
| Phase 1 (W3) — Celery worker | CONCERN |
| Phase 2 (W2) — Rate limiter | PASS |
| Phase 3 (W1) — Aggregation cost | CONCERN |
| Phase 4 (W4) — Pool/timeout | CONCERN |

**Totals: 0 FAILs / 5 CONCERNs / 4 PASSes**

**-> Net Gate: CONDITIONAL**

Cycle-over-cycle: cycle 1 = 2 FAILs / 6 CONCERNs / 1 PASS; cycle 2 = 2 FAILs / 2 CONCERNs / 5 PASSes; cycle 3 = 0 FAILs / 5 CONCERNs / 4 PASSes. Both cycle-2 FAILs are resolved and independently re-verified against source. Every cycle-3 CONCERN is a delivery hole in the newly-chosen mechanism whose remedy is determined by invariants the plan already states (mutual exclusion required; stale-but-correct strictly preferred over wrong; the stated 60-minute bound must be honourable) and lands in files already inside the Phase 3 / Phase 4 blast radius. No CONCERN requires a mechanism choice, so none is escalated to FAIL and none is bounced to a fourth supplement cycle — each is fully specified in-contract below (the E13/E14 precedent from cycle 2).

### CONCERNs (contract-fixable — recorded as binding execute-agent instructions, not blockers)

**CONCERN-1 — the repair sweep can be starved, and may never fire at all, so the 60-minute Public Contract bound is not yet honourable.** Three parts, one consequence.
(a) *Starvation.* Item 11f tells the sweep to skip a site whose `agg:debounce:{site_id}` key is held. Item 7 has the per-ingest path take that key with `SET NX EX aggregation_min_interval_seconds` (default 60s) on every batch. On a continuously-ingesting site the key is re-acquired the instant it expires, so it is held ~100% of the time and the sweep's single attempt always loses. The hottest sites — the ones this capacity-hardening plan exists for — would never have `avg_time_on_page` / `intent_score` repaired, and `intent_score` drives segmentation and outreach.
(b) *No end-of-pass retry.* The sweep makes one attempt per site per pass, so even transient contention costs a full interval.
(c) *No boot offset.* Item 11e specifies no `next_run_time`. `scheduler.py:216-227` documents this exact failure for `resolution_sweep`: "The API process restarts on every deploy, resetting that 30-min timer before it ever elapses — so the sweep effectively never ran and backlogs piled up." A 60-minute job on a service that redeploys hourly never fires.
Mitigation: E16 (starvation protocol, fully specified) + E18 (boot offset) + gates AC-V5, AC-V6. Acceptance rationale: the remedy is forced by the plan's own stated bound and lands only in `scheduler.py` + `events.py`, both already Phase 3 touchpoints — no new mechanism choice, no blast-radius expansion.

**CONCERN-2 — item 11f's fail-open justification is valid only for full-vs-full and permits a counter-inflation race.** 11f says that when Redis is degraded the sweep should run anyway because "a duplicate full recompute is idempotent by construction and therefore safe". That is true of two full recomputes. It is false of a full recompute racing an *incremental* run: the sweep SETs `total_pageviews` from its own snapshot while a concurrent incremental run adds to the same row, so the merged result can double-count — the exact G1 failure the whole phase is built to prevent. Mitigation: E17 — the fail-open direction is flag-conditional (skip when `aggregation_incremental_enabled` is True; proceed only when it is False), gated by AC-V7. Acceptance rationale: the direction is determined by D7's own hierarchy — "stale-but-correct is strictly safer than wrong" — so no design choice remains.

**CONCERN-3 — the beat ban is only enforceable for repo-declared commands.** Phase 1 exit-gate clause (ii) requires that the worker command carries no `-B` and no separate `celery beat` service exists. The repo-side grep is real and currently clean (verified: no `celery` string at all in `Dockerfile`, `railway.json`, `infra/docker-compose.yml`), but `railway.json` declares no `startCommand`, so a Railway worker service's command exists only in the dashboard and no automated gate can observe it. As written the clause reads as fully gated when half of it is not. Mitigation: AC-V8 restated as repo-side only, plus operator checklist item P0.5 and E21. Acceptance rationale: the un-gated half is inherently out-of-repo (operator surface), correctly quarantined rather than falsely claimed.

**CONCERN-4 — cycle 3 changed Phase 4c's arithmetic and left four stale counts behind (regression into a previously-PASS section).** Verified today: `scheduler.py` has 11 `add_job` calls = 10 interval + 1 `CronTrigger`. Phase 3 item 11e adds a twelfth, making 12 total / 11 interval. Cycle 3 added a correct "Count update" paragraph but left the bullet two lines above it saying "add ... to the **10 interval** calls; the AST test asserts over exactly those 10", and left AC13, the AC13 failing stub, and E6 on the pre-cycle-3 numbers. Mitigation: AC13 + its stub corrected in this contract, E20 added, and the Phase 4c plan-body bullet corrected in place (accepted-concern mitigation applied at V6). Acceptance rationale: pure arithmetic consistency; the authoritative count is now stated once per surface and the AST test is required to derive the count rather than hardcode it.

**CONCERN-5 — Phase 3 checklist items 8 and 11c conflict.** Item 8 edits `aggregation_tasks.py:19-30` so `_aggregate_all` "uses the same incremental path when the flag is on". Item 11c tells the new `_aggregation_sweep_job` to mirror `_aggregate_all` "verbatim in shape" while always using `since=None`. Once item 8 lands, an execute-agent mirroring the edited function inherits the watermark branch and the repair path silently becomes incremental — which would leave `avg_time_on_page` / `intent_score` frozen forever, re-creating cycle-2's FAIL-A by a different route. (Item 8 also still calls `_aggregate_all` "the hourly sweep"; cycle 3 established that this Celery task never runs at all, since there is no beat and no worker.) Mitigation: E19 + gate AC-V10. Acceptance rationale: mirroring is a structural instruction only; the `since=None` requirement is already explicit in 11c and in the exit gate, so the fix is a clarification, not a decision.

**CONCERN-6 (carried from cycle 2) — D6's `ai_source` merge expression desyncs under the obvious implementation.** The plan gives `COALESCE(NULLIF(visitors.first_touch_referrer,''), EXCLUDED.first_touch_referrer)` for the referrer and says `ai_source` "follows" it. The symmetric expression is wrong: `classify_ai_source` returns `None` for ordinary referrers (`ai_referral.py:63-78`), so a stored pair of (`first_touch_referrer='https://www.google.com/'`, `ai_source=NULL`) plus a window referred from `chat.openai.com` yields kept-referrer + new AI label. Mitigation: E13 (exact CASE expression) + AC-V3. Acceptance rationale: fully specified in-contract; no design choice remains.

**CONCERN-7 (carried from cycle 2) — `ip_address` is a `set_` column absent from the plan's merge table.** `visitor_aggregator.py:232` uses `ip_address or Visitor.ip_address` (keep-if-set). Window-safe in practice, but undocumented, so a bulk-upsert rewrite could silently drop the keep-if-set half and blank stored IPs. Mitigation: E14 + AC-V4. Acceptance rationale: behaviour-preserving requirement, mechanically assertable.

### Execute-Agent Instructions

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Do NOT start Phases 1, 2, or 3 until the matching Pre-EXECUTE Human Checklist box is ticked and the answer is written into `Resume and Execution Handoff` item 5. P0.2, P0.3, and P0.5 are operator-only — never probe, guess, or synthesise them. | Any Phase 1/2/3 entry |
| E2 | Phase 4d (`redis_client.py` `socket_timeout=5`, `retry_on_timeout=False`) has no Phase 0 dependency and no FAIL or CONCERN against it — it remains the safest first item. Verify the OAuth/PKCE callers of `get_redis()` tolerate a `redis.TimeoutError`. | Phase 4d entry |
| E3 | `aggregate_visitors_for_site` must keep its current 2-arg call signature working: add `since: datetime \| None = None`. 2 production callers (`apps/api/routers/events.py:623` inside `_background_aggregate`, `apps/api/tasks/aggregation_tasks.py:26` inside `_aggregate_all`) and ~15 test call sites pass 2 args. | Phase 3 entry |
| E4 | With `since=None` the emitted SQL must be byte-identical to today's `text(...)` block at `visitor_aggregator.py:270-312`. Build the `since` clause by string-appending to the `session_boundaries` WHERE, not by rewriting the query. | Phase 3 entry |
| E5 | `database.py:27` — the `connect_args` dict contains TWO keys (`prepared_statement_cache_size`, `statement_cache_size`). Preserve both when adding `server_settings`. Dropping `statement_cache_size` regresses the Supabase pooler fix. | Phase 4a/4b entry |
| E6 **(count corrected, cycle 3)** | `scheduler.py` currently has 11 `add_job` calls (207/214/229/236/243/250/257/265/274/283/294); those at 265/274/283/294 are inside `if settings.*` blocks and the one at 294 uses `CronTrigger`. **After Phase 3 item 11e there are 12 calls: add `jitter` + `misfire_grace_time` to all 11 interval calls (the 10 existing + the new `aggregation_sweep`) and exclude only the `CronTrigger` call.** See E20. | Phase 4c entry |
| E7 | Phase 1: `crm.py:287` and `ads_push.py:126` already gate `.delay()` on `crm_async_push` / `ads_async_push` (both default False) plus a member threshold. Resolve the two flags into ONE explicit condition and write the truth table into the code comment before editing. Do not stack a second independent gate. | Phase 1 entry |
| E8 | Phase 0 diagnostic log: `key_hash` (truncated SHA-256) + `xff_len` only. Never the raw IP, never the forwarded chain. Removal of the log line is a Phase 2 exit-gate item, not optional cleanup. | Phase 0 entry |
| E9 | Run the three existing aggregation integration files as the flag-OFF parity gate BEFORE writing any new aggregation test. If any is already red on `main`, stop and report — do not attribute a pre-existing failure to this change. | Phase 3 entry |
| E10 | `tests/unit/test_redis_socket_timeout.py` must bind its own local listening socket. Do not call `get_redis()` — conftest pins `REDIS_URL=redis://localhost:6379/15`, and a stray local Redis container is a known cross-run poisoning source. Same rule for `tests/unit/test_aggregation_sweep_failopen.py` (C7). | Phase 4d / Phase 3 entry |
| E11 | Migration (Phase 3): re-run `.venv/bin/alembic heads` immediately before writing the revision. Offline validation only — never `alembic upgrade` against a real environment. | Phase 3 entry, if D2 needs a column |
| E12 | Do NOT create `tests/unit/test_ip_resolution*.py`. `tests/unit/test_ip_resolution.py` already covers all five required XFF cases plus four more (11 tests). Extend it only if Phase 2 changes behaviour. | Phase 2 entry |
| E13 **(cycle 2)** | D6: `ai_source` must be conditioned on whether `first_touch_referrer` was kept, NOT COALESCEd independently. Use `CASE WHEN NULLIF(visitors.first_touch_referrer,'') IS NOT NULL THEN visitors.ai_source ELSE EXCLUDED.ai_source END`. A symmetric `COALESCE` on `ai_source` is wrong because `classify_ai_source` returns NULL for every non-AI referrer, so the pair desyncs on the common case. Gated by AC-V3. | Phase 3 entry |
| E14 **(cycle 2)** | The bulk upsert must preserve `ip_address`'s existing keep-if-set semantic (`visitor_aggregator.py:232`, `ip_address or Visitor.ip_address`) — a NULL window IP must not blank a stored IP. This column is absent from the plan's merge table; do not infer it is a plain SET. Gated by AC-V4. | Phase 3 entry |
| E15 **(cycle 2)** | A Celery **worker** does not run `beat_schedule`. Do not document, deploy, or describe the Phase 1 worker service as reviving `aggregate-visitors-hourly`. Item 9a's comment must say the schedule is dormant by design. | Phase 1 entry |
| E16 **(cycle 3 — MANDATORY, supersedes item 11f's skip-only wording)** | The repair sweep MUST NOT be indefinitely starvable. Implement all four parts: **(a)** when `agg:debounce:{site_id}` is already held, the sweep sets a yield marker `agg:sweep_pending:{site_id}` (TTL = 3 x `aggregation_min_interval_seconds`) and defers that site instead of silently dropping it; **(b)** the per-ingest trigger from item 7 checks `agg:sweep_pending:{site_id}` BEFORE attempting `SET NX` on the debounce key, and when the marker is present skips its own run and does NOT take the key (it is about to be superseded by a full recompute, which is a strict superset of its work); **(c)** the sweep collects deferred sites and retries them once at the end of the pass — because the debounce key TTL is `aggregation_min_interval_seconds` and no new per-ingest run may take it while the marker is set, the key frees within one TTL; **(d)** the sweep deletes `agg:sweep_pending:{site_id}` when it finishes or fails that site. Do NOT instead let the sweep proceed without the key — see E17. Gated by AC-V5. | Phase 3 item 11f |
| E17 **(cycle 3 — MANDATORY, corrects item 11f's fail-open direction)** | When Redis is unavailable, the sweep's fail-open direction is **flag-conditional**: with `aggregation_incremental_enabled=True` it must SKIP the site (log `aggregation_sweep_skipped_redis_degraded` with the site id, continue to the next site, never abort the pass); with the flag `False` it may proceed, because full-vs-full is genuinely idempotent. Item 11f's blanket "let the sweep run" is unsafe under the flag-ON path: a `since=None` SET racing an additive incremental merge can inflate `total_pageviews` / `total_sessions`. Stale-but-correct beats wrong — this is D7's own hierarchy. Gated by AC-V7. | Phase 3 item 11f |
| E18 **(cycle 3 — MANDATORY)** | Register the sweep with an explicit `next_run_time` boot offset, e.g. `next_run_time=datetime.now(timezone.utc) + timedelta(seconds=90)`, following the `resolution_sweep` precedent and the comment at `scheduler.py:216-227`. Without it, a 60-minute interval job on a service that redeploys more often than hourly never fires, and the Public Contracts staleness bound is void. Choose an offset larger than the existing 20/30/45/60s offsets so the sweep does not pile onto the boot burst; Phase 4c's `jitter` then spreads it across containers. Gated by AC-V6. | Phase 3 item 11e |
| E19 **(cycle 3 — MANDATORY, resolves the item 8 / item 11c conflict)** | Item 11c's "mirror `_aggregate_all`" means mirror its **structure only** (one session for the site-id SELECT, then a sequential per-site loop with a fresh session each). `_aggregation_sweep_job` MUST pass `since=None` explicitly and unconditionally, and MUST NOT read `aggregation_incremental_enabled` to choose a path. Do not copy `_aggregate_all` after item 8 has made it watermark-aware — that would silently turn the repair path incremental and freeze `avg_time_on_page` / `intent_score` permanently. Also note item 8's prose calls `_aggregate_all` "the hourly sweep": that Celery task never runs (no beat, no worker), so item 8 is forward-looking only and must not be treated as a live cadence. Gated by AC-V10. | Phase 3 items 8 + 11c |
| E20 **(cycle 3 — count authority)** | The authoritative scheduler arithmetic after Phase 3 is: **12 `add_job` calls total, 11 interval (all get `jitter` + `misfire_grace_time`), 1 `CronTrigger` excluded.** The Phase 4c bullet that said "the 10 interval calls" was written before item 11e existed and has been corrected in the plan body; if any stale "10" survives anywhere, this instruction wins. `tests/unit/test_scheduler_job_config.py` must derive the counts by walking the AST, not by hardcoding line numbers — line numbers shift the moment the new job is inserted. | Phase 4c entry |
| E21 **(cycle 3)** | The beat ban is enforceable in the repo only. AC-V8's grep covers `Dockerfile`, `railway.json`, and `infra/docker-compose.yml` (all currently free of any `celery` string). `railway.json` declares no `startCommand`, so a Railway worker service's command is a dashboard artefact no gate can read. Do not describe Phase 1 exit-gate clause (ii) as fully automated; it is repo-gated plus operator-attested via P0.5. If Phase 1(a) is ever written up, state this split explicitly in the deploy note. | Phase 1 entry / any deploy-doc edit |

### Backlog Artifacts

| Artifact | Location | Status | What it tracks |
|---|---|---|---|
| `celery-beat-vs-apscheduler-duplication_NOTE_25-07-26.md` | `process/general-plans/active/capacity-hardening_25-07-26/` (colocated in the task folder — this is the correct location; the cycle-2 contract listed `process/general-plans/backlog/` in error) | **EXISTS — verified on disk at contract time** | Inventory of the three dormant `beat_schedule` jobs: `aggregate-visitors-hourly` SUPERSEDED by the Phase 3 APScheduler sweep; `process-pending-visitors-hourly` and `check-segmentation-triggers` dead with decisions owed. Satisfies half of Phase 1 exit-gate clause (iii) |
| `transaction-pooler-advisory-lock-audit_NOTE_25-07-26.md` | `process/general-plans/active/capacity-hardening_25-07-26/` | TO CREATE (Phase 4b) | Whether `retention.py`'s `pg_try_advisory_lock` (`:64`/`:76`) is safe under the Supabase 6543 transaction pooler; blocks the port-change recommendation in 4b |
| `aggregation-multi-container-concurrency_NOTE_25-07-26.md` | `process/general-plans/active/capacity-hardening_25-07-26/` | TO CREATE (Phase 3) | N-container race against the Redis debounce and against the new `agg:sweep_pending` marker; only observable under real load |

Open gaps:
- Multi-container concurrency against the Redis debounce **and the new `agg:sweep_pending` yield marker**: known-gap — requires 2+ live containers under real load; covered by AC3's 24h soak (gap-resolution C) plus the backlog note above. AC-V5 proves the protocol in one process, not across N.
- Supabase 6543 transaction-pooler compatibility with `retention.py` advisory locks: known-gap — requires a real 6543 endpoint; backlog note above; 4b ships port-aware code but must NOT recommend the port change.
- Railway worker service start command (`-B` presence): known-gap for automation — the command lives in the Railway dashboard, not the repo. Closed only by operator attestation P0.5. Blocks Phase 1(a) alone, not Phases 1(b)/2/3/4.
- Real Railway XFF hop count: NOT a gap — closed by the blocking P0.1 pre-condition.
- P0.2 / P0.3 / P0.5: operator-only human gates, cost-class `needs-live-provider` equivalent. Documented as a pre-EXECUTE checklist, never agent-satisfiable.
- Scheduled full-recompute mechanism for D7: **CLOSED this cycle** — APScheduler `aggregation_sweep` (Phase 3 item 11), delivered by this plan, gated by AC-V5/V6/V7/V10.
- The three dead `beat_schedule` jobs: **CLOSED this cycle** — item 9a/9b/9c + 3-clause exit gate; the NOTE exists on disk.

What this coverage does NOT prove:
- The AC1 flag-OFF parity suite proves the three existing integration files still pass; it does NOT prove byte-identical SQL output, because no test captures the emitted SQL string. E4 is the only control on that.
- AC2's double-run idempotency proves no inflation for the merged columns; it does NOT prove the DESCOPED columns are ever refreshed — AC-V10 proves the sweep uses the full-recompute path and AC-V5/AC-V6 prove it can actually run, but no automated gate observes a real 60-minute cadence in production. Only the AC3 soak can.
- AC-V5 proves the yield-marker protocol works within one pytest process against a real Redis; it does NOT prove it across N containers — one process is not a deploy.
- AC-V6 proves a `next_run_time` argument is present; it does NOT prove the chosen offset avoids the boot burst on a real deploy.
- AC-V7 proves the fail-open direction is flag-conditional in a monkeypatched unit test; it does NOT prove Redis degradation behaves the same way under a real partial outage (slow-but-alive Redis is a different failure than raise-immediately).
- AC-V8 proves no repo-declared command enables beat; it does NOT prove the Railway service command lacks `-B`. Only P0.5 can (CONCERN-3).
- AC-V9 proves the disposition artefacts exist; it does NOT prove the two still-dead beat jobs were the right call to defer.
- AC-V3 proves the referrer/`ai_source` pair stays consistent for the seeded case; it does NOT prove every AI-referrer domain in `AI_REFERRER_DOMAINS` behaves identically.
- AC5's debounce test proves single-process coalescing against a real Redis; it does NOT prove multi-container behaviour.
- AC6 proves `resolve_client_ip`'s arithmetic; it does NOT prove the correct value of `trusted_proxy_hops` for Railway. Only P0.1 can.
- AC10 proves the CRM push completes with the worker flag OFF; it does NOT prove any Celery task body executes, because no worker runs in the test lane and none exists in any environment.
- AC11 proves Postgres honours `statement_timeout` on a disposable container; it does NOT prove the chosen millisecond value is safe against production query latency.
- AC12 proves a bounded timeout is raised; it does NOT prove every caller of `get_redis()` handles it — only the OAuth/PKCE audit in E2 covers that, and that audit is manual.
- AC13 proves the arguments are present; it does NOT prove the chosen `jitter` / `misfire_grace_time` values prevent real thundering-herd behaviour across a deploy.
- AC14 proves the migration round-trips on a disposable Postgres; it does NOT prove it applies cleanly to production — that remains an unperformed operator action, queued behind 8 already-pending migrations.
- AC15 proves the unit lane is green in mock mode; it does NOT prove real-provider behaviour on any touched path.
- No gate proves the production capacity outcome. G1-G4 are only observable via the AC3 and AC7 Agent-Probe rows, which require a deploy.

Gate: CONDITIONAL (0 FAILs; 5 CONCERNs, all fully specified in-contract as binding execute-agent instructions E16-E21 plus carried E13/E14, each with a new or corrected gate; both cycle-2 FAILs resolved and independently re-verified against source)
Accepted by: session (autonomous, /goal execution) — accepted concerns: CONCERN-1 (sweep starvation + missing boot offset → E16, E18, AC-V5, AC-V6), CONCERN-2 (fail-open direction permits a full-vs-incremental inflation race → E17, AC-V7), CONCERN-3 (beat ban is repo-side only; operator-attested via P0.5 → E21, AC-V8), CONCERN-4 (stale Phase 4c interval-job counts → E20, AC13 corrected, plan body corrected in place), CONCERN-5 (item 8 / item 11c mirroring conflict → E19, AC-V10), CONCERN-6 (`ai_source` merge expression → E13, AC-V3), CONCERN-7 (`ip_address` keep-if-set → E14, AC-V4). Three PVL fix cycles are recorded in `results.tsv`; no CONCERN requires a mechanism choice, so no fourth supplement cycle is warranted.

---

## Autonomous Goal Block

```
SESSION GOAL: Capacity-harden the Beam API — fix aggregation cost blowup, rate-limiter key collapse, dead Celery queueing, and pool/timeout gaps.
Charter + umbrella plan: N/A — single plan (process/general-plans/active/capacity-hardening_25-07-26/capacity-hardening_PLAN_25-07-26.md)
Autonomy: self-decide at reversible gates; write reports/plan updates without approval; BLOCKED items go to backlog and the run continues. Hard stop on any irreversible or outward-facing action not named in the validate-contract.
Hard stop conditions / safety constraints:
- Never apply a database migration to a real environment. Offline validation on a disposable container only.
- Never flip a feature flag to True in a real environment. Flag flips are operator actions.
- Never change DATABASE_URL, create a Railway service, or alter deploy topology. Operator actions.
- Never log a raw client IP or a full X-Forwarded-For chain. Truncated hash plus chain length only.
- Never start Phase 1, 2, or 3 while its Phase 0 pre-condition is unanswered. P0.2, P0.3, P0.5 are human-only.
- Never enable Celery beat: no `-B` flag, no separate `celery beat` service, while the Phase 3 APScheduler sweep exists. Two schedulers running the same unbounded full-history sweep is the failure this guard prevents.
- Never let the repair sweep run a full recompute concurrently with an incremental run (E17). Stale beats wrong.
Next phase: EXECUTE. Gate is CONDITIONAL after 3 PVL fix cycles; 7 accepted concerns are bound as execute-agent instructions E13, E14, E16-E21 and gated by AC-V3..AC-V10.
Validate contract: inline in plan (## Validate Contract) — Gate: CONDITIONAL, 0 FAILs / 5 CONCERNs / 4 PASSes (cycle 3; both cycle-2 FAILs resolved and re-verified against source)
Execute start: Phase 4d first (apps/api/services/redis_client.py — socket_timeout=5, retry_on_timeout=False; no Phase 0 dependency, no concern against it). Then Phase 1(b) -> 2 -> 3 -> 4 as each Phase 0 box is ticked; Phase 1(a) worker deploy is optional capacity, last, operator-gated.
Fully-auto gates: PYTHONPATH=. .venv/bin/python -m pytest tests/unit -m unit -q ; MOCK_EXTERNAL_APIS=true PYTHONPATH=. .venv/bin/python -m pytest tests/unit -m unit -q ; grep -rnE '(^|[[:space:]])-B([[:space:]]|$)|celery[^\n]*\bbeat\b' Dockerfile railway.json infra/docker-compose.yml
Hybrid gates (Docker-gated): docker compose -f infra/docker-compose.yml up -d postgres redis ; PYTHONPATH=. .venv/bin/python -m pytest tests/ -m integration -q
Probe scenarios: P0.1 hashed-key cardinality observation; 24h single-site flag-ON aggregation soak. High-risk pack: yes — schema/migration (Phase 3), deploy/runtime (Phases 1, 4), trust-boundary (Phase 2).
```

---

## Resume and Execution Handoff

1. **Selected plan file:**
   `process/general-plans/active/capacity-hardening_25-07-26/capacity-hardening_PLAN_25-07-26.md`
2. **Last completed phase/step:** PLAN written (25-07-26); PVL cycle 1 supplement applied (9/9 gaps); PVL cycle 2 re-validation; PVL cycle 3 supplement applied (3/3 gaps, APScheduler mechanism locked by user); PVL cycle 3 re-validation complete — Gate: CONDITIONAL. No phase started. Phase 0 pre-conditions are all UNANSWERED.
3. **Validate-contract status:** written 25-07-26 (outer-pvl, PVL cycle 3) — Gate: **CONDITIONAL**. 0 FAILs / 5 CONCERNs / 4 PASSes. Both cycle-2 FAILs resolved and independently re-verified against source. All 7 accepted concerns are bound as execute-agent instructions (E13, E14, E16-E21) and gated by AC-V3..AC-V10. EXECUTE is unblocked, subject to the Pre-EXECUTE Human Checklist (P0.1-P0.5). Phase 4d is the recommended first item.
4. **Supporting context loaded:** `process/context/all-context.md` (architecture, guardrails,
   flag/mock conventions, migration chain state), `process/context/tests/all-tests.md` (test lanes
   and commands). Audit findings verified at file:line against `visitor_aggregator.py`,
   `events.py`, `rate_limiter.py`, `ip_resolution.py`, `config.py`, `database.py`,
   `redis_client.py`, `celery_app.py`, `aggregation_tasks.py`, `scheduler.py`, `Dockerfile`,
   `railway.json`.
5. **Phase 0 answers (fill these in before Phases 1–3):**
   - P0.1 resolved client IP behind Railway: _unanswered_
   - P0.2 out-of-repo Celery worker exists: _unanswered — operator-only, not agent-satisfiable._
     Phase 1(b) executed 25-07-26 under the plan's own fallback clause ("If P0.2 cannot be
     answered, Phase 1 defaults to option (b) — gate the `.delay()` paths — which is safe under
     either answer"; Pre-EXECUTE checklist P0.2: "If unanswerable, Phase 1 defaults to option (b)
     only"). Option (a) — the worker Railway service (checklist item 6) — remains NOT started and
     still requires P0.2 + P0.5.
   - P0.3 `DATABASE_URL` pooler port (5432 / 6543) + client cap: _unanswered_
   - P0.4 `events` total rows + per-site distribution: _unanswered_
6. **Next step for a fresh agent:** ENTER EXECUTE MODE against this plan (validate-contract is written, Gate CONDITIONAL). Execute Phase 4d first (no Phase 0 dependency), then Phase 0 (read-only + one temporary log line) before touching Phases 1–3.
   Phase 4d (Redis `socket_timeout`) is the only item with no Phase 0 dependency and can ship
   independently at any time.

---

**Next phase: EXECUTE.** The validate-contract is written and the gate is CONDITIONAL after three
PVL fix cycles. Say `ENTER EXECUTE MODE` to begin, honouring the Pre-EXECUTE Human Checklist and
execute-agent instructions E1-E21.
