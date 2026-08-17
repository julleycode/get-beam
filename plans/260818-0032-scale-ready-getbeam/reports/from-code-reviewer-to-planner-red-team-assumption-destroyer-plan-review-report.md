# Red-team plan review — Assumption Destroyer

- **Roles:** Fact Checker + Scope Auditor
- **Plan:** `plans/260818-0032-scale-ready-getbeam/`
- **Date:** 2026-08-18
- **Posture:** Hostile. No praise. Findings only.
- **Checks skipped by request:** lint, types, build, tests
- **Checks run:** grep/glob against the live codebase

---

## Finding 1: Engine-wide 30s timeout kills ingest bootstrap and retention; session SET leaks on :5432

- **Severity:** Critical
- **Location:** Phase 3, sections "Architecture", "Implementation Steps" step 3, "Related Code Files"
- **Flaw:** `db_statement_timeout_ms` is applied once at engine connect via asyncpg `server_settings`. There is a single `engine` / `async_session`. Phase 3 claims sweep/retention can escape 30s with a session `SET` or a second engine, but does not specify `SET LOCAL` vs `SET`, does not reset on pool checkout, and does not name retention.py as a touch file. Ingest `_background_aggregate` uses the same `async_session()`.
- **Failure scenario:** Operator sets Railway `DB_STATEMENT_TIMEOUT_MS=30000` after soak. A new site (or any site whose watermark is still NULL) takes the ingest full-recompute path. That run uses the request engine, hits 30s, dies. Retention `purge_events_older_than` also uses `async_session()` and holds an advisory lock across statements — the exact session-scoped pattern `config.py` says forbids a pooler change. If the implementer does `SET statement_timeout = '5min'` (session-level, not `SET LOCAL`) on the sweep connection and returns it to the pool, the next ingest checkout inherits 5 minutes (DoS) or, after recycle, 30s again (sweep randomly dies). A second engine doubles pool demand against `max_connections` with no pool-math update.
- **Evidence:**
  - Code: `apps/api/models/database.py:28-46` (`server_settings` on connect), `:59-76` (one engine), `:91-93` (`get_db` / same sessionmaker).
  - Code: `apps/api/routers/events.py:946-952` (`async with async_session()` for ingest agg).
  - Code: `apps/api/jobs/scheduler.py:495-500` (sweep uses `async_session()`, `since=None`).
  - Code: `apps/api/services/retention.py:120-123` (lock session + inner delete session from `async_session`).
  - Code: `apps/api/config.py:56-66` (timeout is server-side connect setting; comment already warns sweep is unbounded).
  - Code: `apps/api/config.py:79-86` (advisory locks across statements → stay on session `:5432`).
  - Plan quote: "`db_statement_timeout_ms=30000` trên engine request. Sweep/retention: session `SET statement_timeout` cao hơn hoặc engine riêng."
- **Suggested fix:** Second engine with `statement_timeout=0` (or ≥5min) used by `_aggregation_sweep_job` AND both retention lock/delete sessions. If using `SET`, require `SET LOCAL` inside the job transaction and a checkout hook that resets `statement_timeout` to the request value. Name `retention.py` in Related Code Files. Keep ingest bootstrap full on the unbounded engine until watermark is non-NULL.

---

## Finding 2: Watermark lifetime is ingest-only; stamp failures + sweep-must-not-stamp + 30s = permanent full-history

- **Severity:** Critical
- **Location:** Phase 1, sections "Architecture", "Implementation Steps" step 2–3; Phase 3 timeout; umbrella "Lỗ hổng phải sửa"
- **Flaw:** `sites.last_aggregated_at` is written in exactly one place: `_advance_watermark`. That helper swallows errors ("Never fails the run"). Full recompute (`since=None`) does not stamp — by contract, and Phase 1 forbids the sweep from stamping. The only planned bootstrap caller is ingest `_background_aggregate` (plus dead Celery `aggregation_tasks.py`). Model comment and ingest comment claim full "then stamps"; the aggregator does not. After Phase 3, a failed stamp leaves watermark NULL forever: ingest keeps attempting full on a 30s engine; sweep may complete full repair but is forbidden to stamp, so it cannot heal the watermark.
- **Failure scenario:** Flag ON. Site A gets first ingest, full commit succeeds, `_advance_watermark` hits a transient error and logs `aggregation_watermark_advance_failed`. Watermark stays NULL. Every later ingest on A does `since=None` again. Phase 3 enables 30s. Those fulls cancel. Sweep hourly still runs `since=None` and still does not stamp. Site A never enters incremental. Soak criterion `incremental=true` is false forever for that site. Rollback of the timeout flag is the only recovery — not documented.
- **Evidence:**
  - Code: `apps/api/services/visitor_aggregator.py:539-540` (stamp only `if since is not None`).
  - Code: `apps/api/services/visitor_aggregator.py:560-573` (`_advance_watermark` try/except, warning only).
  - Code: grep `last_aggregated_at\s*=` → only `_advance_watermark` writes the column.
  - Code: `apps/api/models/site.py:98-104` (comment: "NULL = never aggregated incrementally → the next run does a full recompute and then stamps this" — the "then stamps" half is false in aggregator).
  - Code: `apps/api/routers/events.py:947-951` (comment: "full recompute, which then stamps" — also false today).
  - Code: `apps/api/jobs/scheduler.py:496-500` (sweep `since=None` unconditionally).
  - Code: `apps/api/tasks/aggregation_tasks.py:19-25` (Celery task "NOT a live cadence"; no worker).
  - Plan quote: "Stamp thuộc **caller** (`events.py` / `aggregation_tasks.py`)" and "sweep … MUST NOT stamp".
- **Suggested fix:** Treat stamp failure as a failed run (retry, do not claim success). Add a one-shot operator/SQL bootstrap that stamps after a known-good sweep, or allow sweep to stamp **once** when watermark is NULL (not on later repairs). Do not rely on Celery `aggregation_tasks.py`. Document dormant sites: no ingest ⇒ watermark stays NULL until first post-flag event.

---

## Finding 3: Phase 3 "ceiling → 429" contradicts the shipped flag-but-store contract

- **Severity:** High
- **Location:** Phase 3, "Success Criteria" (`có test 429`); "Risk Assessment" (`false 429 khách thật`); "Security Considerations" (`429 không leak…`)
- **Flaw:** Per-site ceiling is Option C: trip marks `is_flagged_abuse`, response stays **204**, rows are stored. Existing integration tests assert `429 not in statuses` for the ceiling. Hard 429 on ingest is the **per-IP** `@limiter.limit("100/minute")`, a different layer. The plan's AC and risk table describe the wrong mechanism. Implementing "test 429" as written either fails CI against current tests or silently changes abuse policy from flag-but-store to hard reject — a product/behavior change not in Architecture.
- **Failure scenario:** Execute agent adds a ceiling test expecting 429. It fails against `test_ingest_abuse_hardening.py` (204 + flagged rows). Or they "fix" the router to HTTP 429. Pixel XHR retries every non-2xx (`tracker.js` keeps queue). A viral site that trips a too-low ceiling then retries forever, amplifying load — the opposite of a ceiling. Flag-but-store exists specifically so that does not happen.
- **Evidence:**
  - Code: `apps/api/routers/events.py:351-362` (Option C; 204; `site_ingest_ceiling_tripped`).
  - Code: `apps/api/services/rate_limiter.py:70-86` ("Deliberately NOT a slowapi `@limit`"; "hard-rejects with 429" is the rejected design; `hit()` returns flag, not HTTP).
  - Code: `tests/integration/test_ingest_abuse_hardening.py:356` (`assert 429 not in statuses`) and `:309` (written with `is_flagged_abuse = True`).
  - Code: `apps/api/routers/events.py:167` (`@limiter.limit("100/minute")` — this is the 429 path).
  - Plan quote: "Site ceiling ON với số từ p99, có test 429" / "Ceiling thấp → false 429 khách thật".
- **Suggested fix:** AC must be: over-ceiling ingest still 204, rows `is_flagged_abuse=true`, excluded from rollup (copy existing test). If the product now wants hard 429, that is a spec change — call it out, update pixel retry behavior, and rewrite the abuse tests. Do not conflate site ceiling with the 100/min IP limiter.

---

## Finding 4: Required `event_id` is specified against the wrong status, the wrong insert, and incomplete entry points

- **Severity:** High
- **Location:** Phase 2, "Architecture", "Related Code Files", "Success Criteria"; umbrella Red Team row "Reject NULL `event_id` phá pixel cũ"
- **Flaw:** (1) Umbrella says 400; Phase 2 AC says 422. Live parse path catches **all** exceptions from `EventBatch(**data)` and returns **400**, not FastAPI 422. (2) Router still does `event_id=(event.event_id or None)` — `Field(...)` still accepts `""`, which becomes NULL. (3) HTTP ingest is only `/ingest`, but that schema is shared with the **agent** early-return (parse happens before `persist_agent_visit`). (4) `tests/integration/test_events_ingest.py` and `test_ingest_abuse_hardening.py` contain **zero** `event_id` keys — every current 204 fixture becomes a reject. (5) sendBeacon confirms send without reading status; a 400/422 is a silent client-side drop, not a retry.
- **Failure scenario:** Schema set to required. Execute writes a 422 test. It fails because `_parse_event_batch` returns 400. They change the test to 400; umbrella/phase docs still disagree. An old cached pixel (or any payload with `event_id: ""`) still inserts NULL via `or None`, so `event_id IS NULL = 0` after backfill is immediately false. Agent UA batches without `event_id` never reach `persist_agent_visit` — agent visits disappear. First-flush XHR retries forever on 400 (queue storm); later sendBeacon path `confirmSent()` anyway — events lost with no server row.
- **Evidence:**
  - Code: `apps/api/schemas/events.py:24` (`event_id: str | None = Field(None, max_length=64)`).
  - Code: `apps/api/routers/events.py:114-125` (`EventBatch(**data)`), `:199-201` (`except Exception: return Response(status_code=400)`).
  - Code: `apps/api/routers/events.py:414-416` (`event_id=(event.event_id or None)`), `:466-470` (`on_conflict_do_nothing(index_elements=["event_id"])`).
  - Code: `apps/api/routers/events.py:198` then `:305-329` (parse first; agent path uses `first_agent_event.event_id`; "Older pixel builds send no event_id").
  - Code: `apps/pixel/src/tracker.js:290` (`evt.event_id = uuid()`), `:339-342` (sendBeacon `confirmSent` with no status), `:361-362` (XHR non-2xx keeps queue).
  - Code: grep `event_id` in `tests/integration/test_events_ingest.py` and `test_ingest_abuse_hardening.py` → no matches; payloads e.g. `test_events_ingest.py:53-60`.
  - Code: `tests/unit/test_farbled_ingest_boundary.py:53-59` (EventBatch without `event_id` — will start raising).
  - Plan quote: "ingest thiếu `event_id` → 422, 0 row" vs umbrella "400 + log".
- **Suggested fix:** Pick one status and implement it in `_parse_event_batch` (do not assume FastAPI 422). Reject `""` / whitespace, and remove `or None`. List every `/ingest` test file as Modify. Preserve agent parse: missing `event_id` must not skip `persist_agent_visit` unless that is an explicit product decision. Document sendBeacon as fire-and-forget (400 ≠ retry).

---

## Finding 5: Flag-ON bootstrap thundering herd — debounce is per-site, pool is 5

- **Severity:** High
- **Location:** Phase 1, "Risk Assessment" row "25 site full cùng lúc lúc flip"
- **Flaw:** Mitigation claims "Sequential sweep sẵn; bootstrap per-ingest; debounce 60s". Sweep is sequential. Ingest bootstrap is **not**. `agg:debounce:{site_id}` is per site. 25 sites ingesting after the Railway flip each pass `watermark NULL → since=None`. Each full path also `await _resolve_companies` (up to 20 provider calls) **before** returning to the caller that would stamp. Pool is `db_pool_size=3 + db_max_overflow=2 = 5`.
- **Failure scenario:** Operator sets `AGGREGATION_INCREMENTAL_ENABLED=true` at 10:00. All 25 customer sites have NULL `last_aggregated_at`. Organic traffic in the next minute schedules 25 concurrent `_background_aggregate` fulls. They contend for 5 connections, queue, and overlap the hourly sweep (also full, also one session at a time but competing for the same pool). Soak "duration/site giảm" is measured after the herd, not during it. First-ingest 204s succeed (agg is background) while aggregations fail/timeout; watermarks stay NULL (Finding 2). After Phase 3, the same herd is 30s-capped.
- **Evidence:**
  - Code: `apps/api/routers/events.py:938-952` (debounce then per-site watermark).
  - Code: `apps/api/config.py:128-131` (`aggregation_min_interval_seconds: int = 60`, key documented as `agg:debounce:{site_id}`).
  - Code: `apps/api/jobs/scheduler.py:520-524` (sweep sequential; pool 3+2=5 shared with request traffic).
  - Code: `apps/api/config.py:67-71` (defaults 3/2).
  - Code: `apps/api/services/visitor_aggregator.py:546-549` (full path awaits `_resolve_companies`), `:763-782` (limit 20 lookups per run).
  - Plan quote: "25 site full cùng lúc lúc flip | Sequential sweep sẵn; bootstrap per-ingest; debounce 60s".
- **Suggested fix:** Global bootstrap lock or a one-shot sequential stamp job before flipping the Railway flag (walk `site_id`, full + stamp one at a time). Do not flip the flag under live traffic and hope per-site debounce serializes a fleet. Dispatch company resolution on the full bootstrap path the same way incremental already does (`_dispatch_company_resolution`).

---

## Finding 6: Phase 2 Alembic `down_revision` is unnamed; context "current head" is stale

- **Severity:** High
- **Location:** Phase 2, "Related Code Files" / "Implementation Steps" step 3; Fact Checker: migration heads
- **Flaw:** Plan says "Create: Alembic backfill NULL `event_id`" with no `down_revision`. `process/context/all-context.md` still tells agents the live head is `d5b1f7c3a908`. That revision is **not** the head: `e6b2d4a1c837` already revises it, and the chain continues to `b7e3c9a4f215` (`add_identity_feedback_actual_city`), which nothing else lists as `down_revision`.
- **Failure scenario:** Execute agent (or a human following all-context) sets `down_revision = "d5b1f7c3a908"`. `alembic upgrade` creates a second head. Prod apply stops or merges blindly. Backfill either does not run, or runs twice. Unique index already allows multiple NULLs; a branched migration is how you get a subset of rows still NULL while AC says `event_id IS NULL = 0`.
- **Evidence:**
  - Code: `apps/api/migrations/versions/d5b1f7c3a908_add_site_last_aggregated_at.py` (revision `d5b1f7c3a908`).
  - Code: `apps/api/migrations/versions/e6b2d4a1c837_add_cadence_bot_flag.py:30` (`down_revision = "d5b1f7c3a908"`).
  - Code: `apps/api/migrations/versions/b7e3c9a4f215_add_identity_feedback_actual_city.py:17-18` (`revision = "b7e3c9a4f215"`, `down_revision = "f4b9d2a71c68"`); grep of `down_revision.*b7e3c9a4f215` → no children.
  - Code: `process/context/all-context.md:656-660` ("TRUE current alembic head … `d5b1f7c3a908`").
  - Plan quote: "Create: Alembic backfill NULL `event_id` rồi (optional follow-up) `nullable=False`" — no revision pin.
- **Suggested fix:** Pin `down_revision` to the result of `alembic -c apps/api/alembic.ini heads` at EXECUTE time (today that is `b7e3c9a4f215` unless another migration lands). Treat a second head as a hard stop. Update all-context in UPDATE PROCESS, not as a hidden execute surprise.

---

## Finding 7: Incremental window is client `event.ts`, watermark is server `now()` — the bootstrap stamp inherits a clock bug

- **Severity:** High
- **Location:** Phase 1, "Architecture" (`stamp last_aggregated_at = now() taken BEFORE read`); "Implementation Steps" step 2 (`created_at > watermark`)
- **Flaw:** Plan treats `created_at` as "events that landed during the run". Ingest overwrites `created_at` with the pixel's `event.ts`, not DB `now()`. Watermark stamp is `SELECT now()` (incremental) or caller `now()` (planned bootstrap). Filter is `WHERE created_at > :since`. Client clocks behind server → events arrive after stamp but `created_at < watermark` → skipped until the hourly full sweep. Client clocks ahead → already-counted rows have `created_at > stamp` → incremental **adds** them again (double pageviews until sweep SET). Phase 1 soak "không double-count" / "sai số lookback OK" does not detect undercount and mis-attributes lookback (lookback is LAG-only; merge is the `window_clause`).
- **Failure scenario:** Canary site, flag ON, bootstrap stamps server 12:00:00. A visitor's laptop is 2 minutes slow. Pageview `ts=11:59:10` inserts after the full read. Incremental `created_at > 12:00:00` misses it. Soak compares `total_pageviews` to `count(*)` over 24h wall clock and sees a deficit, or waits for sweep and calls it "lookback error". A laptop 2 minutes fast double-counts until sweep. The soak AC has no bound, no per-visitor check, and no clock-skew fixture.
- **Evidence:**
  - Code: `apps/api/routers/events.py:459` (`created_at=event.ts.replace(tzinfo=None) if event.ts.tzinfo else event.ts`).
  - Code: `apps/api/models/event.py:77` (column default `func.now()` is unused on this path).
  - Code: `apps/api/services/visitor_aggregator.py:348-351` (lookback on read; `window_clause` `created_at > :since` on the aggregate SELECT).
  - Code: `apps/api/services/visitor_aggregator.py:488-492` (watermark = `SELECT now()` only when `since is not None`).
  - Code: `apps/pixel/src/tracker.js` pageview `ts: now()` (client clock).
  - Plan quote: "Events giữa read và stamp vào lần incremental sau (`created_at > watermark`)."
- **Suggested fix:** Stamp and filter on a server-side ingest timestamp, or set `created_at` from DB `now()` at insert (keep `event.ts` as a separate column if needed). Soak must assert both no double-add **and** no missing events vs `count(pageview)` for the canary, including a skewed-`ts` fixture. Do not hand-wave deficits as "lookback".

---

## Finding 8: Phase 2 retention "evidence in 48h" looks at the wrong log, and zero-delete is silent

- **Severity:** Medium
- **Location:** Phase 2, "Success Criteria" (`Retention: evidence log 7d request_logs / 90d events trong 48h`); "Implementation Steps" step 4
- **Flaw:** Plan tells operators to grep `retention_purge_complete` / `request_log_retention_purge_complete`. The scheduler wrappers log `retention_purge_job_complete` / `request_log_retention_purge_job_complete` **only when `deleted` is truthy**. A healthy run that deletes 0 rows emits neither scheduler line. The inner `retention_purge_complete` in `retention.py` does fire on success, but only after the delete loop — and only if the operator tails the API service, not a "job_complete" search copied from the plan. Misfire/last-success is not a field the scheduler currently logs.
- **Failure scenario:** Jobs are registered and run. Disk is still 424 MB because nothing is older than 90d yet. Operator greps Railway for the plan's event names, sees nothing in 48h, "fixes registration" that is already correct, or worse, writes a second purge. Alternatively they grep `retention_purge_complete`, find a historical inner log, and mark AC pass while `request_log_retention_purge_job_complete` never appeared because 7d logs are empty.
- **Evidence:**
  - Code: `apps/api/jobs/scheduler.py:61-85` (`retention_purge_job_complete` iff `result.get("deleted")`; same for request logs).
  - Code: `apps/api/jobs/scheduler.py:631-634` (job id `retention_purge`, interval hours).
  - Code: `apps/api/services/retention.py:156` (`logger.info("retention_purge_complete", …)` inside success path).
  - Code: `apps/api/services/retention.py:306` (`request_log_retention_purge_complete`).
  - Plan quote: "prod log `retention_purge_complete` / `request_log_retention_purge_complete`" and "evidence log 7d … / 90d … trong 48h".
- **Suggested fix:** Always log a structured `{job}_ran` with `deleted`, `status`, `cutoff`. Point the runbook at those names. Do not treat "0 deleted" as "job not running". Add last-success timestamp if the 48h AC needs a heartbeat.

---

## Finding 9: Env var names match pydantic fields — no defect (negative fact-check)

Railway names in the plan map to `Settings` fields with no `env_prefix`:

| Plan Railway name | pydantic field | Default |
|---|---|---|
| `AGGREGATION_INCREMENTAL_ENABLED` | `aggregation_incremental_enabled` | `False` (`config.py:127`) |
| `SITE_INGEST_LIMIT_ENABLED` | `site_ingest_limit_enabled` | `False` (`config.py:293`) |
| `SITE_INGEST_LIMIT_PER_MINUTE` | `site_ingest_limit_per_minute` | `3000` (`config.py:295`) |
| `DB_STATEMENT_TIMEOUT_MS` | `db_statement_timeout_ms` | `0` (`config.py:66`) |

`model_config` is only `env_file` + `extra=ignore` (`config.py:1455`). This is **not** a finding. It is recorded so Fact Checker cannot be accused of skipping the assigned check.

`ingest_trust_cf_connecting_ip=True` **does** bypass `trusted_proxy_hops` when `CF-Connecting-IP` is a valid IP (`ip_resolution.py:55-61`). Site ceiling keys on `site_id`, not IP (`rate_limiter.py:86`). Umbrella claim that the ceiling can turn on before hop-count is fixed is true **for the site layer** — but see Finding 3: that layer does not 429.

---

## Scope map (auditor)

| Claim | Actual surface | Gap |
|---|---|---|
| Stamp `sites.last_aggregated_at` | Write site: `_advance_watermark` only; NULL forever if unused | Finding 2 |
| Ingest callers | Live: `events.py` `_background_aggregate`. Dead: `aggregation_tasks.py`. Sweep: must not stamp | Finding 2, 5 |
| `statement_timeout` | Engine `server_settings`, one pool | Finding 1 |
| Require `event_id` | Schema + `/ingest` parse + agent early-return + tests + seed ORM inserts | Finding 4 |
| Site ceiling 429 | Flag-but-store 204 | Finding 3 |
| Alembic head | Plan unnamed; docs say `d5b1f7c3a908`; code head `b7e3c9a4f215` | Finding 6 |

---

## Verdict

Do not EXECUTE as written. Findings 1–2 are sequencing landmines between Phase 1 stamp design and Phase 3 engine timeout. Finding 3 is a false AC that will either fail tests or change abuse semantics. Findings 4–7 will fail soak or migrate prod into a branched Alembic graph.
