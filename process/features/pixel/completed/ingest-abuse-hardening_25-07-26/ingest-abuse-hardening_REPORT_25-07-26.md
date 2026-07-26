---
phase: ingest-abuse-hardening
date: 2026-07-25
status: COMPLETE_WITH_GAPS
feature: pixel
plan: process/features/pixel/active/ingest-abuse-hardening_25-07-26/ingest-abuse-hardening_PLAN_25-07-26.md
---

# Ingest Abuse Hardening — EXECUTE Report

## Context Envelope

| # | Field | Value |
|---|---|---|
| 1 | feature | pixel |
| 2 | phase | EXECUTE |
| 3 | session-goal | Harden POST /ingest against rotating-IP flood/DDoS abuse (P1–P5, additive only) |
| 4 | branch | main |
| 5 | worktree | main |
| 6 | context-group | tests |
| 7 | blast-radius-packages | apps/api (config, main, routers/events, routers/campaigns, routers/ingest_health, models/event, models/visitor, services/{ip_resolution,ingest_velocity,rate_limiter,visitor_aggregator,identity_classification,identity_resolver,campaign_sender,csv_exporter}, migrations), tests/{unit,integration} |
| 8 | active-plan | ingest-abuse-hardening_PLAN_25-07-26.md |
| 9 | test-runner | pytest (unit lane \| integration lane) |
| 10 | validate-contract | inline in plan (`## Validate Contract`, Gate: PASS) |

## What Was Done

All 5 phases implemented strictly in order P1 → P2 → P3 → P4 → P5.

**P1 — streaming body-size guard.** `ingest_body_max_bytes = 262_144` added to
`config.py`. `IngestBodySizeLimitMiddleware` added to `main.py` as pure ASGI
(matching the `PixelCORSMiddleware` precedent, NOT `BaseHTTPMiddleware`), scoped to
`/api/v1/events/ingest` only. Two layers: a `Content-Length` fast path that rejects
without reading a byte, and a running byte counter inside a wrapped `receive()` that
catches chunked / forged-header cases. Rejects `413` with a body carrying zero user
data. Registered after `PixelCORSMiddleware` so it is outermost.

**P2 — trusted-proxy IP resolution.** `trusted_proxy_hops = 0` added.
New `services/ip_resolution.py` with `resolve_client_ip()` (hops<=0 → ignore XFF
entirely; hops>=N → `entries[-N]`; every misconfiguration/malformed/absent/exception
path falls back to `request.client.host`) and `client_ip_key_func()`. The spoofable
`_extract_ip()` was deleted outright (grep confirmed it was private and had exactly
one call site) and replaced. The per-IP limiter's `key_func` was switched from
slowapi's `get_remote_address` to `client_ip_key_func` — required by P2's stated goal
that the resolved IP be used "everywhere IP matters"; at the default hops=0 this is
behaviourally identical to before.

**P3 — per-site ingest ceiling.** `site_ingest_limit_enabled = False` (default OFF) +
`site_ingest_limit_per_minute = 3000`. A second `site_limiter` keyed on
`request.state.site_id`, sharing the single resolved `STORAGE_URI` (E4). Per E2 the
site_id stash is a genuine FastAPI `Depends(stash_site_id)` parameter in the route
signature — **empirically confirmed working** by
`test_site_ceiling_key_func_reads_site_id`, so the manual-`.hit()`-after-parse
fallback was NOT needed. Body is read once logically (Starlette caches `_body`).
Trip behaviour is Option C flag-but-store — P3 delivers *detection*, P4 delivers the
*storage effect*, exactly as the plan sequenced it.

**P4 — velocity flag, migration, exclusion, outreach gate.** Alembic head re-confirmed
live as `a9f2c1e7b4d6` before writing anything. 4 velocity settings added (all default
OFF/permissive). New `services/ingest_velocity.py`: `SADD` + **explicit `EXPIRE` on
every write** for both site-scoped keys, `SCARD`-based two-condition signal (high
distinct-visitor count AND low fingerprint diversity), missing fingerprint counted as
its own bucket rather than dropped from the denominator, fail-open on any Redis error,
inert when the flag is off. Migration `c7d3b8e1f624` adds
`events.is_flagged_abuse`, `ix_events_site_flagged`, `visitors.is_abuse_flagged`,
`identified_visitors.is_abuse_flagged` — all NOT NULL + `server_default 'false'`,
matching the `events.optout` precedent. The **CRITICAL** `visitor_aggregator.py`
raw-SQL edit was made (see Plan Deviations for the shape it took) and threaded through
`_upsert_visitor` with sticky `OR`-merge semantics mirroring `do_not_resolve`.
`_save_identified` copies the marker onto `IdentifiedVisitor` in the same atomic
INSERT as `source_agent_visit_id`. `is_emailable_identity()` gained
`is_abuse_flagged: bool = False`, checked in the same unconditional-first-return-False
block as the agent guard.

**P5 — operator observability.** New `routers/ingest_health.py`:
`GET /api/v1/sites/{site_id}/ingest-health`, tenant-scoped through the shared
`verify_site_access` (`Site.user_id`, 404-not-403). Returns windowed total/flagged/
clean event counts, distinct visitors, flagged ratio, a `flood_signal` verdict, and
limiter storage state. Counts and ids only — no PII.

## What Was Skipped or Deferred

- **Live migration round-trip on a disposable Postgres** — Docker is unavailable in
  this environment (`docker info` fails). Not worked around: the local Postgres on
  :5432 is a shared dev/test server, and the binding constraint forbids applying to a
  real/shared environment. Offline validation was run instead (see below). This is a
  **Known-Gap**, not a pass.
- `hot_alert.py:88` still does not pass either guard parameter — a **pre-existing**
  gap the plan explicitly scoped out. It now defaults `is_abuse_flagged=False` exactly
  as it already defaults `source_agent_visit_id=None`. Not worsened, not fixed.
- `routers/demo.py` has its own raw `x-forwarded-for` read. Out of scope (separate
  public demo endpoint, not the `/ingest` path). Noted, untouched.

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| P1 (AC-2) | `pytest tests/integration/test_ingest_abuse_hardening.py -k "oversized" -q` | **3 passed** |
| P2 unit (AC-3, AC-8) | `pytest tests/unit/test_ip_resolution.py -m unit -q` | **11 passed** |
| P2 integ (AC-3) | `pytest ... -k "spoofed_xff" -q` | **1 passed** |
| P3 (AC-1) | `pytest ... -k "site_ceiling" -q` | **2 passed** |
| P4 unit | `pytest tests/unit/test_identity_classification.py tests/unit/test_ingest_velocity.py -m unit -q` | **43 passed** |
| P4 integ (AC-4/5/6) | `pytest ... -k "flagged or organic or shared_nat or csv_replay or combined" -q` | **7 passed** |
| P5 (AC-7 + tenancy) | `pytest ... -k "ingest_health" -q` | **2 passed** |
| E1 / AC-9 PII | `pytest tests/unit/test_ingest_abuse_no_pii_logging.py -m unit -q` | **13 passed** |
| Whole new file | `pytest tests/integration/test_ingest_abuse_hardening.py -q` | **16 passed** (3 consecutive runs) |
| Full unit lane | `pytest tests/unit -m unit -q` | **465 passed, 2 failed** — both failures PRE-EXISTING (reproduced on a stashed clean tree) |
| Ingest regression | `pytest tests/integration/{test_events_ingest,test_consent_mode,test_conversion_ingest}.py -q` | **29 passed** |
| Visitor/aggregator regression | `pytest tests/integration/test_visitor_filters.py -q` | **21 passed** |
| Identity/PII regression | `pytest tests/integration/{test_pii_dual_write,test_visitor_resolve_endpoint}.py -q` | **11 passed** |
| AC-11 budget regression | `pytest tests/integration/{test_costs,test_crm_push,test_referrals}.py -q` | **23 passed** |
| Migration offline | `alembic upgrade a9f2c1e7b4d6:c7d3b8e1f624 --sql` + matching `downgrade --sql` | clean, both directions |
| Migration live round-trip | disposable Postgres container | **NOT RUN — Known-Gap (Docker unavailable)** |

**Non-vacuousness check on the CRITICAL edit.** The AC-4a test was mutation-tested: the
`AND NOT is_flagged_abuse` filter was temporarily reverted on the pageview aggregate
and `test_flagged_events_excluded_from_aggregator_rollup` **failed**; restoring it made
it pass. The test genuinely exercises the SQL rather than asserting the column exists.

**Full integration lane caveat (important — do not misread).** A whole-lane run
(`pytest tests/ -m integration`) reported `22 failed, 292 passed, 55 errors`. That run
was executed CONCURRENTLY with a second pytest process against the same
`retarget_agent_test` database, so both were racing each other's `create_all`/
`drop_all`. **Every** reported-failing file was subsequently re-run in isolation and
passed clean: `test_visitor_filters.py` 21/21, `test_pii_dual_write.py` +
`test_visitor_resolve_endpoint.py` 11/11, `test_costs.py` + `test_crm_push.py` +
`test_referrals.py` 23/23. The whole-lane numbers are a harness contention artifact,
not a regression. A single clean whole-lane run was not obtained — the harness killed
the ~30-minute background runs (exit 144). **EVL should re-run the full lane serially
with no concurrent pytest process.**

**Pre-existing unit failures (not mine):**
`test_agent_company_resolution.py::test_ac2_resolution_runner_excludes_agent_rows` and
`::test_ac2_resolution_tasks_process_site_excludes_agent_rows` —
`AttributeError` at `apps/api/tasks/resolution_tasks.py:61`. Confirmed identical on
`git stash`ed clean tree.

## Plan Deviations

**D1 — aggregator exclusion implemented as per-aggregate `FILTER`, not a CTE `WHERE`
clause (within blast radius; correctness-forced).**
The plan (P4 item 5) says to add `AND is_flagged_abuse IS NOT TRUE` to the
`session_boundaries` CTE's `WHERE`. Doing that literally removes flagged rows from the
CTE entirely, which makes `BOOL_OR(is_flagged_abuse)` — required by the *same plan*
(P4 item 4) and asserted by its own load-bearing AC-4b test (item 8) — always
`FALSE`. The two instructions are mutually exclusive as written. Implemented instead:
rows stay in the CTE (so the flag can propagate and the visitor is still discovered),
and `AND NOT is_flagged_abuse` was added to **every metric aggregate's `FILTER`
clause** (pageviews, sessions, scroll, time, pages, referrers, utm, geo, device,
latest_ip, first/last seen). This satisfies both AC-4a (flagged rows contribute
nothing to the rollup) and AC-4b (flag reaches `Visitor` → `IdentifiedVisitor`).
Same file, same function, same semantic operation, no schema/API/auth change. Proven
by the mutation test above plus `test_abuse_flag_propagates_event_to_identified_visitor`.

**D2 — a third `is_emailable_identity()` call site was updated.**
The plan names two (`campaign_sender.py`, `csv_exporter.py`). Grep found a third with
an identical guard shape: `routers/campaigns.py:725` (LinkedIn outreach path). Leaving
it would have been a hole in the very guardrail this phase exists to close. Updated.
`outcome_digest.py:161` and `hot_alert.py:88` were left alone — they pass no guard
params today (pre-existing, plan-scoped-out).

**D3 — per-IP limiter `key_func` switched to the new resolver.**
Not called out as a numbered checklist item, but required by P2's stated goal
("used consistently everywhere IP matters (per-IP limiter, …)"). At the default
`trusted_proxy_hops = 0` this is byte-identical to slowapi's `get_remote_address`.

**D5 — `stash_site_id` is inert when the site ceiling is disabled.**
As first written, the E2 `Depends()` stash buffered and JSON-parsed the body on EVERY
ingest request — including bot traffic that the bot filter drops without ever reading
the body today. That is a (bounded, 256 KB-capped) behaviour change on the hot path in
the default OFF configuration, contrary to the plan's "flag off == byte-identical"
principle. The stash now returns immediately unless `site_ingest_limit_enabled` is
True. The E2 mechanism is unchanged — still a genuine `Depends()` in the route
signature — and `test_site_ceiling_key_func_reads_site_id` now enables the flag and
asserts on `request.state.site_id` via `app.dependency_overrides`, so it proves the
real mechanism rather than a disabled path. (Note for future work: FastAPI binds
`Depends()` targets at route registration, so monkeypatching the module attribute does
NOT override the dependency — the override hook is required.)

**D4 — velocity Redis client construction gated behind the feature flag.**
First implementation called `get_redis()` before `check_velocity()`, which built and
cached a module-global Redis client bound to the creating event loop even with the
feature OFF. This caused a real test failure (`RuntimeError: Event loop is closed`)
and meant flag-off behaviour was NOT byte-identical to pre-hardening. Fixed by moving
the `settings.ingest_velocity_enabled` gate ahead of the client construction.

## E1 Manual PII Review Result

**Performed. Result: PASS — no PII in any new log line, counter, or payload.**

First, the search for an existing mechanism (as E1 requires before treating this as a
gap): no ruff/flake8/pylint config exists in `pyproject.toml`/`setup.cfg`, there is no
`.pre-commit-config.yaml`, the two GitHub workflows contain no structlog lint, and no
test in `tests/unit/` inspects structlog call sites. **Confirmed: this repo has no
automated PII-lint. The grep test was therefore mandatory and has been written.**

Manual review of every new call site:

| Site | Keys logged | Verdict |
|---|---|---|
| P1 `main.py` middleware | *(none — the 413 path logs nothing; the response body is a fixed literal with no request echo)* | clean |
| P3 `rate_limiter.py` `rate_limiter_redis_unavailable` | `fallback` | clean |
| P3 `rate_limiter.py` `site_ceiling_check_failed` | `error` | clean |
| P3 `events.py` `site_ingest_ceiling_tripped` | `site_id`, `limit_per_minute` | clean |
| P4 `ingest_velocity.py` `ingest_velocity_flagged` | `site_id`, `distinct_visitors`, `distinct_fingerprints`, `window_seconds` | clean (counts only) |
| P4 `ingest_velocity.py` `ingest_velocity_check_failed` | `site_id`, `error` | clean |
| P4 `events.py` `ingest_velocity_unavailable` | `error` | clean |
| P5 `ingest_health.py` response | counts, ids, ratios | clean |

No new call site logs a `visitor_id` at all, so the `visitor_id[:8]` truncation
convention did not need to be applied. Redis key templates are built from `site_id`
only. The machine enforcement is `tests/unit/test_ingest_abuse_no_pii_logging.py`
(13 tests): an **AST-based** check (not regex, so reformatted/multi-line calls cannot
slip past) that asserts (a) no forbidden PII-shaped kwarg on any touched file's logger
calls, and (b) an allowlist over the newly-created modules so a future edit inventing
`visitor_name=` fails loudly rather than silently escaping coverage. That allowlist
test proved itself during development by correctly flagging an unlisted key.

## Alembic Head Confirmation

`alembic -c apps/api/alembic.ini heads` at the start of P4 returned **`a9f2c1e7b4d6`** —
matching the plan. The new migration `c7d3b8e1f624` chains from it.

**Note:** the head advanced mid-session. Unrelated ad-connection work (`b7d3e9f1a4c2`,
`c8e4f2a6b1d9`) landed in the working tree from concurrent activity and chained
**on top of** `c7d3b8e1f624`. Verified this produced no branch: `alembic heads` returns
a single head (`c8e4f2a6b1d9`) and the chain is linear
`a9f2c1e7b4d6 → c7d3b8e1f624 → b7d3e9f1a4c2 → c8e4f2a6b1d9`.

## Test Infra Gaps Found

- **Docker unavailable** in this environment — the entire Docker-gated tier (migration
  round-trip) cannot run here. Postgres and Redis happen to be reachable natively on
  :5432/:6379, which is what allowed the integration lane to run at all.
- **Local Redis on :6379 is live.** Per the standing repo note, unit tests assume port
  6379 is closed; a live Redis can let some unit tests self-poison db15. The full unit
  lane's only 2 failures were confirmed pre-existing and unrelated, but this remains an
  environmental hazard.
- **Teardown flakiness in the new integration file.** Occasional
  `DeadlockDetectedError` / `relation ... does not exist` *errors* (not failures) at
  `drop_all`, caused by `/ingest`'s background aggregation task racing table teardown.
  This is the pre-existing pattern in `test_events_ingest.py`, amplified by the
  site-ceiling test issuing 12 ingest calls. Assertions pass; teardown is noisy. Not
  fixed here (out of plan scope).

## Closeout Packet

- **Selected plan**: `process/features/pixel/active/ingest-abuse-hardening_25-07-26/ingest-abuse-hardening_PLAN_25-07-26.md`
- **Finished**: P1–P5 all code-complete; 16/16 new integration tests + 24 new unit
  tests green; E1 PII gate written and green; migration written and offline-validated.
- **Verified**: AC-1 … AC-11 all have a green proving gate except the migration
  round-trip tier.
- **Still unverified**: live migration round-trip (Docker); real-traffic calibration of
  the numeric thresholds (Hybrid tier by design, documented not proven).
- **Remaining cleanup**: EVL confirmation run by `vc-tester`; then UPDATE PROCESS
  (context doc needs the new flags + the 9th pending migration recorded).
- **Closeout classification**: `Keep in active/testing` — code-complete, but the
  Docker-gated migration round-trip is unclosed in this environment.

## Forward Preview

**Test Infra Found.** `tests/integration/test_ingest_abuse_hardening.py` (16 tests) is
the new home for `/ingest` hardening coverage. `tests/unit/test_ingest_abuse_no_pii_logging.py`
is the repo's **first** automated PII-lint over structlog call sites — future work that
adds log lines to the listed modules must extend `_ALLOWED_LOG_KEYS`.

**Blast Radius Changes.** `is_emailable_identity()` now takes a third parameter. Any
NEW outreach call site must pass all three guards. `visitor_aggregator.py`'s rollup SQL
now filters every metric aggregate on `NOT is_flagged_abuse` — any new aggregate column
added there must carry the same filter or it will silently re-admit flood data.

**Commands to Stay Green.**
```
.venv/bin/python -m pytest tests/unit -m unit -q
.venv/bin/python -m pytest tests/integration/test_ingest_abuse_hardening.py -q
.venv/bin/python -m pytest tests/integration/test_events_ingest.py -q
```

**Dependency Changes.** None. Zero new packages, zero new external service calls
(AC-10 asserted by test). `limits.RateLimitItemPerMinute` is imported from the already-
present slowapi dependency chain.

## Follow-up Stubs Created

None on disk. Two items for the backlog at UPDATE PROCESS:
1. Live migration round-trip for `c7d3b8e1f624` on a disposable Postgres (Docker-gated).
2. `hot_alert.py:88` + `outcome_digest.py:161` do not pass the emailability guard
   params — pre-existing, now applies to two markers instead of one.

## CONTEXT_PARTIAL Items

None. All routed context files were available and read.
