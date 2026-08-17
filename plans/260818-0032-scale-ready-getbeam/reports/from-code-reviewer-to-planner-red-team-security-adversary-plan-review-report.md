# Plan review: Security Adversary (hostile)

- **Plan:** `plans/260818-0032-scale-ready-getbeam/`
- **Reviewer role:** Fact Checker + Contract Verifier
- **Perspective:** attacker (auth bypass, injection, data exposure, privilege escalation, supply chain, OWASP)
- **Scope:** plan documents only; claims grep/glob-verified against the codebase. No lint/build/test.

## Finding 1: Global unique `event_id` lets any origin poison another tenant's ingest
- **Severity:** Critical
- **Location:** Phase 2, section "Architecture" / "Implementation Steps" item 3; umbrella "Dependencies"
- **Flaw:** `/ingest` is public, CORS-open, and unauthenticated. Idempotency is a **global** unique index on `event_id` alone. The plan **forbids** changing it to `(site_id, event_id)`. The agent-fetch path already learned this lesson and scoped the digest by `site_id`. Human events did not.
- **Failure scenario:** Attacker knows or sniffs one victim `event_id` (pixel payload, shared CDN log, browser extension, MITM off-CF). They POST `/api/v1/events/ingest` from any origin with **their** `site_id` (or a throwaway site) and that same `event_id` **first**. `ON CONFLICT DO NOTHING` on `index_elements=["event_id"]` drops the victim's later insert and still returns **204**. Victim retries (same client uuid) keep colliding. Cross-tenant silent event suppression; pageviews never land; no 4xx. After Phase 2 makes `event_id` required, every row **must** occupy the global keyspace — the attack surface expands, it does not shrink.
- **Evidence:**
  - Plan: "Không đổi unique `(site_id, event_id)` — pixel mint UUID global"; "Unique vẫn `uq_events_event_id` global"
  - `apps/api/models/event.py:80` — `Index("uq_events_event_id", "event_id", unique=True)` **FAILED claim that global unique is "safe"**
  - `apps/api/routers/events.py:166-167` ingest is unauthenticated; `:470` `.on_conflict_do_nothing(index_elements=["event_id"])`
  - `apps/api/main.py:166-183` PixelCORSMiddleware allows any customer origin onto `/api/v1/events/ingest`
  - Contrast (same repo already fixed this class of bug for agent fetch): `apps/api/services/agent_visit_persistence.py:67-68` "site_id keeps the key space per-tenant, so a client-supplied event_id replayed against another site cannot occupy that site's key"; test `tests/unit/test_agent_fetch_events.py:209-211`
  - Pixel mint: `apps/pixel/src/tracker.js:290` `evt.event_id = uuid();` **VERIFIED** — UUID does not stop replay of a captured id
- **Suggested fix:** Unique + `ON CONFLICT` on `(site_id, event_id)` (partial unique if NULLs remain). Do not ship required `event_id` while the conflict target stays global. Add a cross-tenant replay test mirroring `test_distinct_fetches_stay_distinct`.

## Finding 2: Client-controlled `created_at` turns incremental merge into unbounded counter inflation
- **Severity:** Critical
- **Location:** Phase 1, sections "Architecture", "Implementation Steps" item 2, "Success Criteria" ("không double-count pageviews")
- **Flaw:** Watermark is server `SELECT now()`. Incremental window is `events.created_at > :since`. Ingest writes `created_at` from **attacker-supplied** `event.ts`. Schema has no future/past bound. Plan never mentions clock trust. Soak "compare total_pageviews vs count events 24h" is an honest-client check.
- **Failure scenario:** After flag ON + bootstrap stamp, attacker POSTs a pageview with `ts` = now+1 year and a unique `event_id`. Incremental SQL includes it (`created_at > watermark`). Merge is **additive**. Watermark advances to server now, **not** the event ts. Every later ingest debounce (60s) re-reads the same future-dated row and **adds again**. Counters inflate until wall clock passes the fake ts, or until the hourly full SET sweep runs — which Phase 3 may then kill with a 30s timeout. Backdated `ts` (1970 / yesterday) is the inverse: incremental never sees it; dashboards lie until sweep. `/ingest` does not require auth; `ts` is a required datetime with no validator.
- **Evidence:**
  - Plan: "Stamp = clock trước read, window nửa-mở `created_at > wm`"; "Prod soak: không double-count pageviews trên site canary"
  - `apps/api/routers/events.py:459` `created_at=event.ts.replace(tzinfo=None) if event.ts.tzinfo else event.ts` **VERIFIED**
  - `apps/api/schemas/events.py:39` `ts: datetime` — **FAILED** no max/min validator (no `field_validator("ts")`)
  - `apps/api/services/visitor_aggregator.py:349-351` lookback/window on `created_at`; `:488-492` `run_started_at = SELECT now()` only when `since is not None`; `:526-527` incremental `_bulk_upsert_visitors_incremental` (additive)
  - Open ingest: `apps/api/routers/events.py:166`
- **Suggested fix:** Persist server `now()` (or `LEAST(event.ts, now())` with a bounded skew, e.g. ±5 min). Gate incremental on that column. Add an adversarial test: future `ts` must not increment `total_pageviews` on a second incremental run. Soak against a hostile payload, not only canary pixel traffic.

## Finding 3: Phase 3 "ceiling + 429" does not stop disk fill; CF-Connecting-IP is spoofable
- **Severity:** Critical
- **Location:** Phase 3, sections "Architecture", "Success Criteria", "Security Considerations"; umbrella Dependencies
- **Flaw:** Two independent lies stacked. (1) `SITE_INGEST_LIMIT_ENABLED` does **not** 429 — `site_ceiling_tripped` is Option C flag-but-store; rows still INSERT. The only hard 429 on ingest is per-IP `100/minute`. (2) Per-IP keying trusts `CF-Connecting-IP` with **no** CF-range check; config already documents origin bypass. Plan claims site ceiling "không phụ thuộc `trusted_proxy_hops`" and success requires "có test 429". Related Code Files do not change `site_ceiling_tripped` into a hard reject. Disk (Phase 2's actual threat) is unchanged.
- **Failure scenario:** Attacker hits Railway origin directly (not CF), forges a fresh `CF-Connecting-IP` per request → per-IP 100/min never trips. They POST 100 unique `event_id`s per batch at a known public `site_id` (snippet `data-site`). Site ceiling, once ON, marks `is_flagged_abuse` and still commits. Free 424/500 MB fills. Phase 2 required `event_id` makes every flood row occupy unique index slots instead of collapsing. Flagged rows are excluded from rollup SQL — analytics look "clean" while Postgres disk dies. 429 tests against slowapi will pass without ever exercising the site ceiling.
- **Evidence:**
  - Plan: "`ingest_trust_cf_connecting_ip=True` → site ceiling **không** phụ thuộc `trusted_proxy_hops`"; "Site ceiling ON với số từ p99, có test 429"; "429 không leak site nội bộ"
  - `apps/api/services/rate_limiter.py:67-74` "Deliberately NOT a slowapi `@limit` decorator: a decorator hard-rejects with 429, while the locked design … is Option C (flag-but-store)"; `:79-86` `.hit()` only returns a bool
  - `apps/api/routers/events.py:351-362` ceiling trip logs then continues; `:449-452` `is_flagged_abuse=abuse_flagged` on the **same INSERT**; `:166-167` `@limiter.limit("100/minute")` is the only ingest decorator
  - `apps/api/services/ip_resolution.py:55-61` if flag on, any syntactically valid `cf-connecting-ip` is returned — **no** peer-in-CF-range check
  - `apps/api/config.py:270-274` "a caller that reaches the Railway origin DIRECTLY (bypassing CF) can forge this header — acceptable until the origin is locked to CF IP ranges (backlogged)" **VERIFIED**
  - `apps/api/config.py:293-295` `site_ingest_limit_enabled: bool = False`, placeholder `3000` still the code default
- **Suggested fix:** Hard-reject over-ceiling (429) **or** drop the row, not flag-but-store, if the goal is disk survival. Lock origin to CF IP ranges (or require authentic CF headers) before trusting `CF-Connecting-IP`. Write the 429 test against the **site** limiter, not the IP limiter. Do not claim ceiling is independent of hop/CF trust until origin is locked.

## Finding 4: Required `event_id` contract is internally contradictory and will 400 (not 422) the whole existing ingest suite
- **Severity:** High
- **Location:** Phase 2 "Requirements" / "Success Criteria"; umbrella Red Team "Reject NULL event_id" (says 400); Phase 2 Related Code Files
- **Flaw:** Umbrella: "400 + log". Phase 2: "422 nếu thiếu" / "Ingest thiếu `event_id` → 422, 0 row". Live parser never uses FastAPI's 422 path: `_parse_event_batch` + bare `except Exception` returns **400**. Making `Event.event_id` required will ValidationError every current ingest fixture that omits it. `tests/integration/test_events_ingest.py` has **zero** `event_id` strings; happy path `test_valid_batch_returns_204` has no id. That file is not in Related Code Files. Pixel CORS + sendBeacon: a 400 vs 422 split also changes client retry behavior with no pixel change planned.
- **Failure scenario:** Cook makes Field required, adds one new 422 test, ships. CI: `test_valid_batch_returns_204` and the rest of `test_events_ingest.py` fail (400). If they "fix" tests to 422, production still returns 400 — false green. Old cached `tracker.js` without `event_id` (plan: "không đổi pixel trừ khi test fail") gets 400 forever; queue retries hammer ingest; events never stored. Umbrella's accepted red-team note ("400 + log") and Phase 2 AC cannot both be true.
- **Evidence:**
  - Plan Phase 2: "schema `event_id` required → 422 nếu thiếu"; AC "Ingest thiếu `event_id` → 422, 0 row"
  - Plan umbrella: "Reject NULL `event_id` phá pixel cũ" disposition "**400** + log"
  - `apps/api/schemas/events.py:24` `event_id: str | None = Field(None, max_length=64)` **VERIFIED** currently optional
  - `apps/api/routers/events.py:114-125` `EventBatch(**data)`; `:198-201` `except Exception: return Response(status_code=400)` **FAILED** 422 claim
  - `tests/integration/test_events_ingest.py` — grep `event_id` → **no matches**; `:47-68` valid batch omits `event_id`
  - `apps/pixel/src/tracker.js:290` **VERIFIED** current pixel mints uuid; no cache-bust / version pin in this plan
- **Suggested fix:** Pick one status (match the live 400 parser, or stop swallowing `ValidationError`). List every ingest caller/test that omits `event_id` (`test_events_ingest.py` at minimum). Pin pixel cache headers or accept old pixels dropping. Do not write an AC that the request path cannot satisfy.

## Finding 5: `DB_STATEMENT_TIMEOUT_MS` is process-wide; sweep and retention share the one engine
- **Severity:** High
- **Location:** Phase 3 "Architecture", "Implementation Steps" item 3, "Related Code Files"
- **Flaw:** There is a **single** `create_async_engine` + `async_session`. Timeout is applied in `connect_args` `server_settings` at engine construction. Sweep (`_sweep_one_site`) and ingest both `async with async_session()`. Plan says "session SET … hoặc engine riêng" but lists `database.py / sweep job session` as a vague slash, with no second engine, no caller list, and an operator step that can set Railway `DB_STATEMENT_TIMEOUT_MS=30000` independently of the code override. Config already warns: size any non-zero value against the unbounded sweep, not request SQL.
- **Failure scenario:** Operator follows Phase 3 runbook and sets `DB_STATEMENT_TIMEOUT_MS=30000` after soak. Next hourly `_aggregation_sweep_job` full-scans 25 sites (or one fat site at x20). Postgres kills the repair query at 30s. `intent_score` / `avg_time_on_page` freeze (D7: sweep is the **only** writer under flag ON). Retention purge holding an advisory lock across statements (`config.py:75-77`) also dies mid-delete. Incremental path looks "fast"; forensic/intent dashboards rot. Plan's own AC "sweep full 1 site 25-site hiện tại không timeout" has no implementation hook that exists today.
- **Evidence:**
  - Plan: "`db_statement_timeout_ms=30000` trên engine request. Sweep/retention: session SET statement_timeout cao hơn hoặc engine riêng — **không** dùng 30s cho `_aggregation_sweep_job`"; Operator Railway `DB_STATEMENT_TIMEOUT_MS`
  - `apps/api/models/database.py:59-78` **one** `engine`, `connect_args=build_connect_args(..., settings.db_statement_timeout_ms)`; `:45-46` timeout in `server_settings` **VERIFIED**
  - Sweep uses that session factory: `apps/api/jobs/scheduler.py:495-500` `async with async_session() as db: ... aggregate_visitors_for_site(..., since=None)`
  - Ingest agg uses the same: `apps/api/routers/events.py:946-952`
  - `apps/api/config.py:60-65` "the full-recompute repair sweep still runs an unbounded query by design — size any non-zero value against THAT query"
  - `apps/api/config.py:66` default `db_statement_timeout_ms: int = 0` **VERIFIED**
- **Suggested fix:** Name a second engine **or** a mandatory `SET LOCAL statement_timeout` in `_sweep_one_site` / `retention.py` **before** any operator flag. Gate the Railway var behind a code check that sweep sessions override. Count engines: today **1**. Do not ship timeout and override in different PRs.

## Finding 6: Bootstrap stamp "callers" are the wrong set — live sweep vs dead Celery
- **Severity:** High
- **Location:** Phase 1 "Architecture", "Related Code Files", "Implementation Steps" items 2–4
- **Flaw:** Plan says stamp belongs to the **caller** (`events.py` / `aggregation_tasks.py`), do not stamp inside `since=None`. Contract verification: `aggregate_visitors_for_site` has **3 production invoke sites**, not 2. The third is the live APScheduler sweep and **must not** stamp — it is omitted from Related Code Files. `aggregation_tasks._aggregate_all` is documented dead (no worker, Beat banned). `_advance_watermark` has **exactly 1** call site today (inside the aggregator, incremental-only). Execute agent "update callers" will either stamp the sweep (intent_score path writes a watermark from a full SET, then ingest goes incremental and **skips** the events the sweep already SET — or worse, double-merge if they also stamp from ingest) or waste the change on Celery that never runs.
- **Failure scenario:** Flag ON. Sweep runs `since=None` (required). If cook copies the new "after full, stamp" helper into `_sweep_one_site`, every hourly repair overwrites `last_aggregated_at` with "now before read". Ingest then incremental-merges only post-stamp events. That is intended **if and only if** sweep remains SET-idempotent and ingest stays additive — but then ingest bootstrap is redundant and the "sweep MUST NOT stamp" architecture paragraph is violated, so tests that assert full-must-not-stamp (`test_incremental_run_stamps_the_watermark`) still pass **inside** the aggregator while production watermarks jump every hour from a caller the plan told the agent not to list. Conversely, if only Celery is patched, **ingest** (`_background_aggregate`) is the only live bootstrap path — Celery change is dead code; comment at `events.py:949-951` already **falsely** claims full recompute stamps.
- **Evidence:**
  - Plan: "Modify: `apps/api/routers/events.py` (`_background_aggregate` ~906-952)"; "Modify: `apps/api/tasks/aggregation_tasks.py` (~31-42) — cùng bootstrap"; "Sweep path: assert vẫn `since=None`, không gọi stamp"
  - Production `aggregate_visitors_for_site` invokes (**count = 3**):
    1. `apps/api/routers/events.py:952` — live ingest
    2. `apps/api/tasks/aggregation_tasks.py:43` — Celery; `aggregation_tasks.py:22-25` "NOT a live cadence … no worker, no beat"; `apps/api/services/celery_app.py:41-47` Beat **BANNED**
    3. `apps/api/jobs/scheduler.py:500` — live repair, `since=None` unconditional
  - `_advance_watermark` callers (**count = 1**): `apps/api/services/visitor_aggregator.py:540` only (guard `:539` `if since is not None`)
  - `get_aggregation_watermark` production callers (**count = 2**): `events.py:951`, `aggregation_tasks.py:42`
  - `_background_aggregate` production callers (**count = 1** spawn): `events.py:562` `asyncio.create_task(_background_aggregate(site_id))`
  - Comment lie: `events.py:949-951` "full recompute, which then stamps the watermark" **FAILED** vs aggregator `:539-540`
  - Test cited: `tests/integration/test_visitor_aggregation_incremental.py:331` `assert ... is None, "full recompute must not stamp"` **VERIFIED** (plan said `:331`)
- **Suggested fix:** Enumerate the three invoke sites in the plan. Patch **only** `_background_aggregate`. Add an explicit "do not edit `scheduler.py:500`" + a test that `_sweep_one_site` never calls `_advance_watermark`. Delete or defer the Celery file from the touch list.

## Finding 7: Redis-degraded ingest still fail-opens into concurrent incremental merges
- **Severity:** High
- **Location:** Phase 1 "Success Criteria" item "Redis degraded + flag ON: sweep skip site"; "Risk Assessment" ("25 site full cùng lúc")
- **Flaw:** The fail-open **direction** is flag-conditional **only on the sweep**. Ingest `_background_aggregate` still fail-opens when Redis `try_acquire` returns `None` and runs aggregation. After Phase 1 bootstrap, that run is **incremental (additive)**. Two replicas (or one replica + overlapping tasks if `_aggregating` is bypassed) merge the same window → G1 counter inflation — the exact race capacity-hardening E17 exists to prevent. Phase 1 AC only reuses `test_aggregation_sweep_failopen.py` (sweep skip). Debounce 60s is Redis NX; when Redis is down it does not exist.
- **Failure scenario:** Flag ON, watermarks stamped, Railway Redis blip. Sweep skips (stale-but-correct). Both API replicas ingest for the same site, both pass `acquired is None`, both `aggregate_visitors_for_site(..., since=watermark)`, both ADD pageviews. Soak canary "no double-count" is green until the first Redis incident. Rollback (`flag false`) SET-heals; the plan treats Redis as already solved ("Redis timeout đã ship").
- **Evidence:**
  - Plan: "Redis degraded + flag ON: sweep skip site (test failopen hiện có)"; "25 site full cùng lúc lúc flip → Sequential sweep sẵn; bootstrap per-ingest; debounce 60s"
  - Sweep skip **VERIFIED**: `apps/api/jobs/scheduler.py:472-475` `if acquired is None` + flag ON → skip
  - Ingest fail-open **VERIFIED**: `apps/api/routers/events.py:922-923` "If Redis is degraded we FAIL OPEN"; `:944` "acquired is None → Redis degraded → fall through"; `:946-952` still aggregates
  - In-memory coalescer is per-process only: `events.py:75` `_aggregating: set[str]`; `:556-562`
  - `apps/api/jobs/scheduler.py:444-450` documents that full-vs-incremental race inflates `total_pageviews` — plan does not extend that rule to ingest
- **Suggested fix:** When flag ON and Redis `acquired is None`, ingest must **skip** (same as sweep), not fail-open. Add a unit test parallel to `test_aggregation_sweep_failopen.py` on `_background_aggregate`. Do not treat debounce TTL as a lock if the lock store is down.

## Finding 8: "Revoke anon / no RLS" and `env.py` guard as specified do not bound data or migrations
- **Severity:** High
- **Location:** Phase 2 "Implementation Steps" items 5–6, "Security Considerations", Success Criteria "`APP_ENV=development` + prod URL → alembic abort"
- **Flaw:** Grep finds **zero** RLS enablement in the repo. Supabase Data API with RLS off means the `anon` key is a full-table credential, not a tenant sandbox. "Revoke anon" without disabling PostgREST / rotating **service_role** / enabling RLS leaves: leaked anon JWT until expiry, any newly minted anon key, and `DATABASE_URL` on the API box. The Alembic guard is specified only for `APP_ENV=development`. Settings treat `local` / `test` / `ci` as non-prod too (`_KNOWN_NONPROD_ENVS`). `env.py` today has **no** URL check at all — the backfill `UPDATE events SET event_id = gen_random_uuid()` is an additive live rewrite the plan will run from this same unguarded file. Default `app_env` is `"development"`, which helps only if the developer did not set `APP_ENV=local` while pointing `DATABASE_URL` at prod.
- **Failure scenario:** Operator "revokes anon" in the dashboard, leaves Data API on, RLS still off. A second anon key, a leaked JWT, or Table Editor still dumps `events` (PII: `ip_address`, `user_agent`, emails via other tables). Parallel: engineer runs `alembic upgrade` with `APP_ENV=local` + prod DSN — planned abort does not fire; backfill rewrites 682 (UNVERIFIED count) `event_id`s on live traffic; unique collisions with in-flight pixel uuids silently drop inserts (`ON CONFLICT DO NOTHING`). Disk/idempotency goals of Phase 2 invert into data loss.
- **Evidence:**
  - Plan: "Revoke Data API/anon — **không** bật RLS 56 bảng"; "Không enable RLS hàng loạt"; "`migrations/env.py` — refuse non-localhost URL when `APP_ENV=development`"
  - RLS: grep `ENABLE ROW LEVEL` / `enable_rls` over `*.py,*.sql` → **no matches** **VERIFIED**
  - `apps/api/migrations/env.py:72-86` `run_migrations_online` uses `settings.database_url` with **no** APP_ENV/localhost guard **FAILED** (control does not exist; planned control is narrower than non-prod envs)
  - `apps/api/config.py:8` `_KNOWN_NONPROD_ENVS = {"development", "test", "local", "ci"}`; `:12` `app_env: str = "development"`
  - Ingest PII columns: `apps/api/models/event.py:37-38` `ip_address`, `user_agent`; email capture on same public POST (`schemas/events.py:41`)
- **Suggested fix:** Disable Data API (or enable RLS on `events`/`visitors` at minimum) as a named control, not "revoke anon". Expand the Alembic abort to every non-prod `app_env` + any DSN host not in `{localhost,127.0.0.1}`. Take a backup **and** a table lock / `SET lock_timeout` around the backfill. Confirm the 682 NULL count live before writing it into AC.

---

## Fact Checker ledger

| Claim | Verdict | Evidence |
|---|---|---|
| `visitor_aggregator.py:539-540` full does not stamp | **VERIFIED** | `if since is not None and run_started_at is not None: await _advance_watermark(...)` |
| `events.py:947-952` NULL watermark → `since=None` | **VERIFIED** | `events.py:947-952` |
| `test_visitor_aggregation_incremental.py:331` full must not stamp | **VERIFIED** | assertion on line 331 |
| `tracker.js:290` pixel `uuid()` | **VERIFIED** | `evt.event_id = uuid();` |
| `aggregation_incremental_enabled` default False | **VERIFIED** | `config.py:127` |
| `ingest_trust_cf_connecting_ip=True` | **VERIFIED** | `config.py:274` |
| `db_statement_timeout_ms` default 0 | **VERIFIED** | `config.py:66` |
| `trusted_proxy_hops` default 0 | **VERIFIED** | `config.py:264` |
| `event_id` optional in schema | **VERIFIED** | `schemas/events.py:24` |
| Unique is global `uq_events_event_id` | **VERIFIED** | `models/event.py:80`; baseline migration `cd811a8b1f32` |
| Redis timeout already shipped | **UNVERIFIED** (not disproven; not re-audited here) | — |
| 682 NULL `event_id` rows live | **UNVERIFIED** | live SQL not run |
| Disk 424/500 MB | **UNVERIFIED** | live SQL not run |
| `max_connections=60` live | **UNVERIFIED** in this review (research doc only) | `config.py:62-69` still comments **15-client cap** — Phase 3 comment-fix is at least locally **VERIFIED** as stale |
| Railway leftovers `pr-64` / `function-bun` deleted | **UNVERIFIED** | not grepped in this pass |
| Phase 2 ingest missing `event_id` → 422 | **FAILED** | parser returns 400 |
| Flag ON stamps watermark today | **FAILED** | stamp only when `since is not None` |
| Site ceiling 429 | **FAILED** | flag-but-store |
| `env.py` refuses prod URL in development | **FAILED** | no guard in `env.py` |
| `aggregation_tasks.py` is a live bootstrap caller | **FAILED** | no worker; Beat banned |

## Contract Verifier — caller counts (do not "update all callers")

| Symbol | Production invoke sites | Count | Plan listed? |
|---|---|---|---|
| `aggregate_visitors_for_site` | `events.py:952`, `aggregation_tasks.py:43`, `scheduler.py:500` | **3** | 2 of 3 (`events.py`, `aggregation_tasks.py`). Live sweep omitted from Related Code Files. Plus 10+ test files (not production). |
| `_advance_watermark` | `visitor_aggregator.py:540` only | **1** | Plan wants new caller-side calls; does not name the helper's current single site. |
| `get_aggregation_watermark` | `events.py:951`, `aggregation_tasks.py:42` | **2** | listed |
| `_background_aggregate` | spawned `events.py:562` | **1** | listed |
| Event insert conflict | `events.py:470` `index_elements=["event_id"]` | **1** | listed; **must** change if unique becomes composite — plan says do not |
| `site_ceiling_tripped` | `events.py:356` | **1** | Phase 3 does not list this function; enabling the flag is not a 429 |
| `build_connect_args` / engine | `database.py:59-76` | **1 engine** | Phase 3 implies 2 |

Test-only `aggregate_visitors_for_site` files (do not treat as "all callers" to patch for stamp): `test_visitor_aggregation_incremental.py` (24 refs), `test_visitor_aggregation.py` (14), `test_optout_flow.py` (7), `test_ingest_abuse_hardening.py` (6), `test_cadence_bot_flag.py` (3), plus debounce/sweep/privacy/unresolvable/events_ingest/sql_shape/failopen (mock or single call).

---

## Verdict

Do not flip `AGGREGATION_INCREMENTAL_ENABLED` or require `event_id` on this plan as written. Three Critical items (global idempotency key, client `ts` vs watermark, flag-but-store ceiling + spoofable CF IP) each independently defeat the x20 disk/correctness goal. Rewrite Phase 1 clock trust + ingest Redis fail-closed; rewrite Phase 2 unique scope + HTTP status + caller/test list; rewrite Phase 3 to a real reject path and a second DB engine **before** the operator timeout flag.
