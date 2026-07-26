---
name: plan:ingest-abuse-hardening
description: "Harden POST /ingest against rotating-IP flood/DDoS abuse: streaming body-size cap, trusted-proxy IP resolution, per-site rate ceiling, write-time velocity flag, operator observability"
date: 25-07-26
feature: pixel
---

# Ingest Abuse Hardening — PLAN (COMPLEX)

**Date**: 25-07-26
**Status**: VALIDATE PASS — ready for EXECUTE
**Complexity**: COMPLEX

SPEC: `process/features/pixel/active/ingest-abuse-hardening_25-07-26/ingest-abuse-hardening_SPEC_25-07-26.md`
INNOVATE decisions: locked (see SPEC's Background section + the Q1–Q5 decisions carried into this
plan verbatim below). This plan does not re-open design choices — it is the executable checklist.

## Overview

Beam's `POST /ingest` pixel endpoint has per-IP rate limiting, bot/datacenter/proxy-VPN filtering,
but no defense against a rotating-IP flood (attacker spreads requests across many IPs, each getting
a fresh per-IP allowance). This plan adds 5 additive layers — oversized-body rejection, unspoofable
trusted-proxy IP resolution, a per-site request ceiling, write-time behavioral velocity detection,
and an operator observability surface — while never touching the existing paid-provider budget caps,
never weakening existing filters, and defaulting every new abuse-facing control to the safe/off
state until an operator explicitly enables it post-migration. See `process/context/all-context.md`
and `process/context/tests/all-tests.md` for repo/test context loaded during this PLAN pass.

## Phase Completion Rules

A phase is `CODE DONE` when its checklist items are implemented and its own test gates pass locally.
A phase is `VERIFIED` only after: (a) its test gates are green, (b) the CRITICAL P4 aggregator-exclusion
edit (item 5) has a passing regression test proving exclusion actually happens (not just that the
column exists), and (c) no phase before it has regressed (existing per-IP limiter, bot filter,
datacenter/proxy-VPN drop, and budget-gate tests all still pass). Do not mark a phase VERIFIED on
code-complete alone — Docker-gated integration tests must have actually run green, not be assumed
green from local unit-only runs.

## Acceptance Criteria

This plan implements SPEC AC-1 through AC-11 verbatim (see SPEC file for full text). Summary
pass/fail bar: every `proven by:` test named in SPEC (and the phase-mapped tests below) is green,
the aggregator raw-SQL exclusion edit is proven by a dedicated regression test, `is_emailable_identity`
is proven to reject abuse-flagged identities regardless of provider, and zero regressions in the
existing per-IP limiter / bot filter / datacenter-proxy drop / budget-gate test suites. See
§SPEC AC → Phase → Test Mapping below for the authoritative per-criterion mapping.

## TL;DR

5 phases, additive-only, no route added/removed. P1 streaming body-size ASGI middleware → P2
trusted-proxy IP resolution (replaces `_extract_ip`) → P3 second slowapi limiter keyed on
`request.state.site_id` → P4 write-time velocity flag on `Event` + aggregator/outreach exclusion →
P5 operator observability endpoint. One new Alembic migration (`Event.is_flagged_abuse` +
`site_ingest_events` index), chained from confirmed head `a9f2c1e7b4d6`. All new settings default to
the SAFE/permissive value and are `pydantic-settings`-driven. Every new Redis key gets an explicit
TTL. `visitor_aggregator.py`'s raw-SQL rollup query is the CRITICAL edit in P4 — the flag column
existing is not enough; the `WHERE` clause must exclude it or AC-4 is violated while looking done.

## Touchpoints

| File | Change |
|---|---|
| `apps/api/main.py` | Add new pure-ASGI `IngestBodySizeLimitMiddleware` (P1), registered alongside `PixelCORSMiddleware` |
| `apps/api/routers/events.py` | Replace `_extract_ip()` (P2); stash `request.state.site_id` before body is fully consumed for the site-ceiling `key_func` (P3); insert write-time velocity check + `is_flagged_abuse` on `Event` insert (P4) |
| `apps/api/services/rate_limiter.py` | Add a second `Limiter` instance (or second `@limiter.limit(...)` decorator with a site-scoped `key_func`) for the site ceiling (P3); no change to the existing per-IP limiter |
| `apps/api/services/ip_resolution.py` (NEW) | `resolve_client_ip(request, trusted_proxy_hops)` — trusted-proxy-aware IP extraction, fail-safe (P2) |
| `apps/api/services/ingest_velocity.py` (NEW) | Redis-backed per-site distinct-visitor + distinct-fingerprint counters, TTL'd, fail-open (P4) |
| `apps/api/config.py` | New settings: `ingest_body_max_bytes`, `trusted_proxy_hops`, `site_ingest_limit_per_minute`, `site_ingest_limit_enabled`, `ingest_velocity_window_seconds`, `ingest_velocity_visitor_threshold`, `ingest_velocity_min_fingerprint_diversity` (P1–P4) |
| `apps/api/models/event.py` | New column `is_flagged_abuse: bool` (default False, server_default "false", nullable False) + new index `ix_events_site_flagged` (P4) |
| `apps/api/services/visitor_aggregator.py` | **CRITICAL**: add `AND (is_flagged_abuse IS NOT TRUE)` (or equivalent) to the raw-SQL rollup `WHERE` clause in `aggregate_visitors_for_site` (P4) |
| `apps/api/models/visitor.py` | New column `IdentifiedVisitor`-adjacent or `Visitor`-level marker — see P4 design note below; reuse `source_agent_visit_id` precedent shape |
| `apps/api/services/identity_classification.py` | Extend `is_emailable_identity()` to also gate on the new abuse-origin marker (single shared helper — checklist item 5) (P4) |
| `apps/api/services/campaign_sender.py`, `apps/api/services/csv_exporter.py` | Update call sites to pass the new marker into `is_emailable_identity()` (P4) |
| `apps/api/migrations/versions/<new>_add_ingest_abuse_flag.py` (NEW) | `revision` chains from `a9f2c1e7b4d6` (re-confirm via `alembic heads` before writing) — adds `events.is_flagged_abuse` + index; adds the `Visitor`/`IdentifiedVisitor` abuse-origin marker column (P4) |
| `apps/api/routers/agents.py` or new `apps/api/routers/observability.py` (NEW, small) | Read-only operator endpoint: flood-vs-organic signal, `Site.user_id`-filtered (P5) |
| `tests/unit/test_ip_resolution.py` (NEW) | AC-3, AC-8 |
| `tests/unit/test_ingest_velocity.py` (NEW) | AC-6, AC-10 |
| `tests/integration/test_ingest_abuse_hardening.py` (NEW) | AC-1, AC-2, AC-4, AC-5, AC-6, AC-7 |
| `tests/unit/test_identity_classification.py` (existing — extend) | AC-4 exclusion helper regression |

## Public Contracts

- `POST /api/v1/events/ingest` — response shape unchanged for legitimate traffic (204). New failure
  mode: oversized body → reject (define exact status in P1 checklist; SPEC AC-2 requires "not
  200/204", does not mandate exact code — use `413 Payload Too Large`, the standard HTTP semantic,
  confirmed available via Starlette `Response(status_code=413)`).
  Velocity-flagged requests still return 204 (Option C — flag-but-store; SPEC AC-4 locked default).
  Site-ceiling-tripped requests: also flag-but-store 204 (consistent default; see P3 note — SPEC
  AC-4 allows a stronger reject for "high enough severity" but does not require it, and Option C is
  the default; this plan implements Option C uniformly for both site-ceiling and velocity trips
  unless PLAN VALIDATE surfaces a reason to diverge).
- New Redis keys (all namespaced `site_id`-scoped, per SPEC constraint):
  - `site_ingest:{site_id}` — slowapi's own internal key format for the second limiter (managed by
    slowapi/storage — TTL matches the limiter window, no manual TTL needed)
  - `ingest_velocity:visitors:{site_id}` — Redis `SET` (or `PFADD`/HyperLogLog) of visitor_ids seen
    in the current window. **TTL: `ingest_velocity_window_seconds` (default 60s), refreshed via
    `EXPIRE` on every write.**
  - `ingest_velocity:fingerprints:{site_id}` — same shape, fingerprint diversity. **Same TTL.**
- New settings (all in `apps/api/config.py`, all env-overridable, all default to the SAFE/permissive
  value matching the `agent_detection_enabled` precedent):
  - `ingest_body_max_bytes: int = 262_144` (256 KB — generous vs. a normal batch of ≤100 events)
  - `trusted_proxy_hops: int = 0` (0 = trust nothing; matches Q3 lock)
  - `site_ingest_limit_enabled: bool = False` (NEW control default OFF — matches
    `agent_detection_enabled` precedent; flipping to `True` is an explicit operator action)
  - `site_ingest_limit_per_minute: int = 3000` (only consulted when `site_ingest_limit_enabled=True`)
  - `ingest_velocity_enabled: bool = False` (default OFF, same precedent)
  - `ingest_velocity_window_seconds: int = 60`
  - `ingest_velocity_visitor_threshold: int = 200` (distinct visitor_ids/window that starts to look
    like a flood — calibration value, operator-tunable per SPEC Open Questions)
  - `ingest_velocity_min_fingerprint_diversity: float = 0.3` (fingerprint_count / visitor_count ratio
    below which traffic looks "one attacker, many fake identities" rather than "many real users")
- `is_emailable_identity(provider, source_agent_visit_id=None, is_abuse_flagged=False)` — new
  optional third param, same unconditional-False-first pattern as the existing
  `source_agent_visit_id` check (P4).

## Blast Radius

- Risk class: **DoS/abuse-hardening on a public unauthenticated endpoint** + **schema migration**
  (Event + Visitor/IdentifiedVisitor columns) + **outreach-eligibility exclusion logic** (high-risk:
  touches the emailability guardrail).
- ~14 files touched (7 new, 7 modified), 1 new Alembic migration, 4 new test files + 1 extended.
  Score matches HIGH on the 7-signal fan-out table (schema change + high-risk class + 5+ files) —
  VALIDATE should invoke `vc-agent-strategy-compare` accordingly.
- All new behavior defaults OFF or maximally permissive (`site_ingest_limit_enabled=False`,
  `ingest_velocity_enabled=False`, `trusted_proxy_hops=0`) — enabling in a real environment is an
  explicit post-migration operator action, matching `agent_detection_enabled` precedent. P1 (body
  size) and P2 (IP resolution correctness) are NOT flag-gated — they are safe-by-construction
  (256 KB is generous; IP resolution defaulting to `request.client.host` at `trusted_proxy_hops=0`
  is exactly today's untrusted-header-stripped behavior, strictly safer than the current spoofable
  `_extract_ip`).
- No paid external API calls added (Q5) — AC-10 is trivially satisfied; still write the unit test
  asserting zero new provider call sites.
- Budget system (`daily_resolution_budget`, `default_daily_enrichment_budget`, 30-day no-retry) is
  untouched — confirmed by touchpoint list above (no edits to `identity_resolver.py` budget logic).

## Confirmed Facts (from RESEARCH re-verification during this PLAN pass)

- `_extract_ip()` at `apps/api/routers/events.py:47-53` — confirmed present, confirmed spoofable
  (takes `X-Forwarded-For` first value verbatim, zero trust check).
- `_parse_event_batch()` at `apps/api/routers/events.py:56-64` already does `await request.body()` —
  confirmed the body is read exactly once today; P1's streaming byte-count guard must run in ASGI
  `receive()` BEFORE this parse, not duplicate the read.
- `rate_limiter.py` — confirmed single shared `Limiter` instance, `storage_uri` resolved once at
  import time via `_storage_uri()`, silent `memory://` fallback on Redis-unreachable (the "landmine"
  named in SPEC constraints — confirmed at `rate_limiter.py:15-27`).
- `main.py` — confirmed `PixelCORSMiddleware` is pure-ASGI (not `BaseHTTPMiddleware`) specifically to
  avoid an asyncpg/event-loop conflict under `ASGITransport` (confirmed comment at
  `main.py:146-153`); confirmed middleware order rule ("last `add_middleware` = outermost = runs
  first") — the new body-size middleware must be added in the correct position (see P1 checklist).
- `Event` model (`apps/api/models/event.py`) — confirmed no existing abuse/flag column; confirmed
  existing indexes `ix_events_site_visitor`, `ix_events_site_created`, `ix_events_created`.
- `visitor_aggregator.py` `aggregate_visitors_for_site()` — **confirmed CRITICAL FINDING**: the
  rollup is a raw SQL `text()` query (`WHERE site_id = :site_id`, no other filter) reading directly
  from the `events` table, NOT the ORM `Event` model. Adding `Event.is_flagged_abuse` as a column
  does **nothing** to this rollup unless the raw SQL `WHERE` clause is edited. This confirms
  checklist item 4 from INNOVATE is load-bearing, not theoretical.
- `is_emailable_identity()` (`apps/api/services/identity_classification.py:56-81`) — confirmed
  existing single shared helper, already unconditional-first-check pattern for
  `source_agent_visit_id`. This IS the "one shared helper" checklist item 5 calls for — extend it,
  do not create a parallel one. Confirmed call sites: `campaign_sender.py:202-203`,
  `csv_exporter.py:79-81`, `hot_alert.py:88` (this one does NOT pass `source_agent_visit_id` today —
  note as pre-existing gap, out of this plan's scope to fix unless P4 touches `hot_alert.py`'s send
  path — it does not, so leave as-is and note in Known-Gap).
- Alembic head confirmed live via `grep` chain walk (down_revision cross-reference, `alembic` CLI not
  available in this environment's shell — **EXECUTE must re-run `alembic heads` as the first P4
  migration step**, since RESEARCH-time confirmation can go stale): `a9f2c1e7b4d6` has no migration
  file with `down_revision = "a9f2c1e7b4d6"`, confirming it is the current head.
- `EventBatch` schema (`apps/api/schemas/events.py`) — confirmed `site_id` and `visitor_id` are
  top-level batch fields (not per-event); `Event.fp` (aliased `_fp`) is the per-event browser
  fingerprint field — this is the field P4's fingerprint-diversity signal reads.
- Existing integration test fixture pattern confirmed in `tests/integration/test_events_ingest.py`
  (`test_client`, `test_db`, `test_site_id` fixture, realistic browser UA to bypass bot filter).

## Implementation Checklist (Phased Delivery Plan)

See Phase 1 through Phase 5 below — each phase's `### Checklist` subsection is this plan's atomic, numbered implementation checklist for that phase.

## Phase Ordering (dependency-verified against real blast radius)

```
P1 (body-size guard)          — no deps, additive middleware
     |
     v
P2 (trusted-proxy IP)         — no deps on P1, but P3/P4 need P2's corrected IP for consistent keying
     |
     v
P3 (site-ceiling limiter)     — needs P2's request.state.site_id stash + corrected IP for observability
     |
     v
P4 (velocity flag + Event     — needs P3's Redis key conventions + site_id stash;
    column + migration +         needs P2 for IP-based signals in the velocity computation
    aggregator exclusion +
    identity_classification)
     |
     v
P5 (operator observability)   — needs P3+P4 counters to exist
```

Ordering confirmed correct — no phase reads a later phase's output. P1 and P2 are mutually
independent (could run in parallel) but are sequenced for simplicity of review; no blocker either way.

---

## Phase 1 — Streaming Body-Size Guard

**Goal:** reject oversized `/ingest` request bodies before they are fully buffered/parsed, using a
running byte count during ASGI `receive()` (not a `Content-Length`-only check, which is forgeable
and absent on chunked transfer-encoding).

### Checklist

1. Add `ingest_body_max_bytes: int = 262_144` to `apps/api/config.py` `Settings` class (grouped near
   other pixel/ingest-related settings; comment explaining the 256 KB rationale — a 100-event batch
   of realistic event JSON is well under this).
2. Create `IngestBodySizeLimitMiddleware` in `apps/api/main.py`, modeled directly on the existing
   `PixelCORSMiddleware` pure-ASGI pattern (same file, same class-based `__call__(scope, receive,
   send)` shape — NOT `BaseHTTPMiddleware`, per the documented asyncpg/event-loop-conflict
   constraint at `main.py:146-153`).
   - Scope check: only intercept `scope["type"] == "http"` and `scope["path"] in {"/api/v1/events/ingest"}`
     (reuse or extend the existing `PixelCORSMiddleware._PIXEL_PATHS` set — narrowly scoped to
     `/ingest`, per Q2 lock; do not apply to other routes like blog image upload).
   - Fast-path: read `Content-Length` header from `scope["headers"]` — if present and already
     exceeds `ingest_body_max_bytes`, short-circuit reject immediately without touching `receive()`.
   - Always-on guard: wrap `receive` in a closure that accumulates a running byte count across
     `http.request` messages (`message.get("body", b"")`); if the running total exceeds
     `ingest_body_max_bytes` at any point (including for chunked bodies with no/forged
     `Content-Length`), stop consuming further body chunks and send a `413`-class ASGI response
     directly (`http.response.start` + `http.response.body`), then return without calling
     `self.app(...)`.
   - Reject response body: minimal — no PII, no request echo (matches AC-9's "no PII in new
     payloads" — a size-limit rejection carries zero user data).
3. Register the middleware in `apps/api/main.py` in the correct order relative to
   `PixelCORSMiddleware` and `CORSMiddleware`. Per the existing "last `add_middleware` = outermost =
   runs first" rule: `IngestBodySizeLimitMiddleware` must run BEFORE `PixelCORSMiddleware`'s CORS
   header injection is needed for the reject response? — confirm via `vc-docs-seeker`/Starlette
   semantics: CORS headers on a 413 response are not required for `sendBeacon` (no-cors mode doesn't
   read the response), so ordering is not safety-critical either way; place
   `add_middleware(IngestBodySizeLimitMiddleware)` immediately after
   `add_middleware(PixelCORSMiddleware)` (i.e., outermost of all, so oversized bodies are rejected
   before any other middleware work happens) — confirm this placement compiles and test-passes in
   EXECUTE; if Starlette's middleware stack ordering surprises here, adjust and document the
   deviation in the phase report.
4. Write `tests/integration/test_ingest_abuse_hardening.py::test_oversized_body_rejected` — proves
   AC-2: post a body > `ingest_body_max_bytes` (use `Content-Length`-present case first — fast
   path), assert non-200/204 response and assert zero `Event` rows created.
5. Write `tests/integration/test_ingest_abuse_hardening.py::test_oversized_chunked_body_rejected` —
   proves the SPEC's explicit chunked-transfer requirement: post with `Transfer-Encoding: chunked`
   and no `Content-Length`, oversized payload, assert same rejection behavior via the running-total
   path (this is the scenario the `Content-Length`-only design explicitly fails, per Q2 lock — must
   be a real regression-guard test, not skipped).

**Test gates (P1):**
```
.venv/bin/python -m pytest tests/integration/test_ingest_abuse_hardening.py -k "oversized" -q
```
(requires local Postgres + Redis — `docker compose -f infra/docker-compose.yml up -d postgres redis`)

**Proves:** AC-2 (Fully-Automated).

---

## Phase 2 — Trusted-Proxy-Aware Client IP Resolution

**Goal:** replace the spoofable `_extract_ip()` with a `trusted_proxy_hops`-driven resolver that
takes the XFF value N-from-the-right, fails safe (falls back to `request.client.host`) on any
misconfiguration, and is used consistently everywhere IP matters (per-IP limiter, datacenter/proxy
checks, new site-ceiling + velocity checks).

### Checklist

1. Add `trusted_proxy_hops: int = 0` to `apps/api/config.py` (comment: 0 = trust nothing, matches
   `request.client.host`; N = trust the Nth-from-the-right XFF entry, i.e. assumes N trusted
   proxies/load-balancers sit in front of the app).
2. Create `apps/api/services/ip_resolution.py`:
   - `resolve_client_ip(request: Request, trusted_proxy_hops: int | None = None) -> str` — pure
     function, `trusted_proxy_hops` param defaults to `settings.trusted_proxy_hops` when `None`
     (allows unit-testing without patching global settings).
   - `trusted_proxy_hops <= 0` → return `request.client.host or ""` (today's safe baseline; XFF
     header is IGNORED entirely — this is the Q3-locked default-trust-nothing behavior).
   - `trusted_proxy_hops >= 1` → parse `X-Forwarded-For` header, split on comma, strip whitespace;
     if the list has fewer than `trusted_proxy_hops` entries (misconfiguration — hops set higher
     than actual chain depth) → **fail safe**: fall back to `request.client.host` rather than
     indexing out of range or raising. If the header is absent entirely → fall back to
     `request.client.host`. Only index `entries[-trusted_proxy_hops]` when the list is long enough.
   - Wrap the entire header-parsing branch in `try/except Exception` → fall back to
     `request.client.host or ""` on any unexpected error (defense in depth — this function must
     NEVER raise into the request path, matching AC-3/AC-8's "never 500 the ingest endpoint"
     requirement carried from checklist item 3).
3. Replace `_extract_ip()` call sites in `apps/api/routers/events.py` (currently line ~133,
   `ip_address = _extract_ip(request)`) with `ip_address = resolve_client_ip(request)`. Delete the
   old `_extract_ip()` function body but keep a thin deprecated wrapper ONLY if any other module
   imports it directly — grep confirms `_extract_ip` is private (leading underscore) and only used
   within `events.py`, so a clean delete-and-replace is safe; re-confirm via
   `grep -rn "_extract_ip" apps/` before deleting in EXECUTE.
4. Grep for every other call site that reads `request.headers.get("x-forwarded-for")` or similar
   raw XFF access within the ingest-adjacent path (datacenter-IP check, proxy/VPN check — these are
   invoked downstream of `_extract_ip()`'s return value per the SPEC flow diagram, so they likely
   already consume the resolved `ip_address` variable rather than re-reading headers — confirm this
   in EXECUTE and do NOT duplicate resolution logic if so).
5. Write `tests/unit/test_ip_resolution.py`:
   - `test_zero_hops_ignores_xff_header` — `trusted_proxy_hops=0`, forged XFF present, asserts
     `request.client.host` is returned, XFF ignored entirely.
   - `test_one_hop_reads_rightmost_xff_entry` — `trusted_proxy_hops=1`, valid 2-entry XFF chain,
     asserts the correct entry is selected.
   - `test_misconfigured_hops_falls_back_safely` — `trusted_proxy_hops=5`, XFF has only 1 entry,
     asserts fallback to `request.client.host`, asserts NO exception raised.
   - `test_malformed_xff_header_falls_back_safely` — garbage/malformed header value, asserts
     fallback, no exception.
   - `test_missing_xff_with_hops_configured_falls_back` — `trusted_proxy_hops=1`, header entirely
     absent, asserts fallback.
6. Write `tests/integration/test_ingest_abuse_hardening.py::test_spoofed_xff_does_not_reset_rate_limit_bucket`
   — proves AC-3 end-to-end: `trusted_proxy_hops=0` (default), send N+1 requests from one real
   client each with a DIFFERENT forged `X-Forwarded-For` value, assert the (existing, unchanged)
   per-IP 100/min limiter still counts them against the same true bucket (triggers the limiter at
   the same threshold as if no XFF were sent at all).

**Test gates (P2):**
```
.venv/bin/python -m pytest tests/unit/test_ip_resolution.py -m unit -q
.venv/bin/python -m pytest tests/integration/test_ingest_abuse_hardening.py -k "spoofed_xff" -q
```

**Proves:** AC-3 (Fully-Automated), AC-8 (Fully-Automated).

---

## Phase 3 — Per-Site Ingest Ceiling

**Goal:** a second slowapi limiter keyed on `site_id` (read from the parsed request body, stashed on
`request.state` before the limiter's `key_func` runs), sharing the existing Redis `storage_uri` so
both limiters degrade together, fail-open on Redis-down.

### Checklist

1. Add to `apps/api/config.py`: `site_ingest_limit_enabled: bool = False`,
   `site_ingest_limit_per_minute: int = 3000` (both env-overridable; default OFF matches the
   `agent_detection_enabled` precedent — flipping ON in a real environment is a deliberate operator
   action taken only after this plan's Docker-gated tests are proven, consistent with the repo-wide
   pattern for every new abuse-facing flag).
2. **Resolve the body-parse-before-limit ordering question** (SPEC explicitly calls this out as a
   PLAN-level decision): `site_id` lives in the POST body (`EventBatch.site_id`), and slowapi's
   `@limiter.limit(...)` decorator's `key_func` runs BEFORE the route handler body, meaning
   `key_func` cannot simply call `await request.body()` a second time (body already consumed once
   inside the handler is fine — Starlette caches `request._body` after first read — but the *limiter
   decorator* fires before the handler's `_parse_event_batch()` call, so the body isn't cached yet
   at decorator-eval time). Two viable approaches, evaluate in EXECUTE and pick the one that keeps
   parsing exactly once:
   - **(a) Preferred — pre-parse via middleware/dependency ordering**: since
     `IngestBodySizeLimitMiddleware` (P1) already touches the raw body stream via ASGI `receive()`,
     it CANNOT cheaply extract `site_id` without JSON-decoding mid-stream (adds coupling). Do NOT
     do this — keep P1 pure size-counting, no JSON awareness.
   - **(b) Preferred — key_func reads `request.state.site_id`, populated by a lightweight
     dependency that runs before the rate-limit check**: FastAPI evaluates `Depends()` after
     route-matching but the slowapi decorator wraps the endpoint function itself, so ordering must
     be verified empirically — if slowapi's decorator fires before `Depends` resolution, this
     approach fails. **This is the concrete design risk flagged by the SPEC.** Resolution path:
     write `test_site_ceiling_key_func_reads_site_id` FIRST (red), then implement whichever
     mechanism makes it pass — either (i) a tiny `_stash_site_id` middleware/dependency that peeks
     the body with `await request.body()` (Starlette caches it, so `_parse_event_batch`'s later
     `await request.body()` inside the handler is a free cache hit, NOT a second parse) and sets
     `request.state.site_id` before slowapi's `key_func` runs, confirmed via a manual body-read
     ASGI-level hook registered ahead of the slowapi decorator, OR (ii) if slowapi's key_func can
     be given the raw ASGI `Request` and perform its own sync-unsafe body peek is infeasible,
     **fall back to a per-route manual check** (call the site-ceiling limiter's `.hit()` /
     equivalent slowapi primitive manually inside `ingest_events()` AFTER `_parse_event_batch()`
     resolves `batch.site_id`, rather than via the decorator). Either mechanism satisfies "reads the
     body once" — document which was chosen in the phase report; do not guess in this plan since it
     is exactly the kind of runtime-behavior fact `vc-docs-seeker`/empirical testing resolves, not
     design-time reasoning.
   - Body IS read once either way: `request.body()` is idempotent after the first read (Starlette
     caches the bytes on `request._body`), so whichever mechanism above wins, `_parse_event_batch`'s
     existing `await request.body()` call is unaffected and remains the single logical parse.
3. Implement the second limiter/key_func using whichever mechanism P3.2 confirms, sharing
   `rate_limiter.py`'s existing `_storage_uri()` (do NOT create a second Redis connection/URI logic
   — reuse the same resolved storage URI so both limiters degrade to `memory://` together on Redis
   failure, per Q1 lock).
4. Gate the check on `settings.site_ingest_limit_enabled` — when `False`, the site-ceiling check is
   a no-op (existing per-IP limiter behavior is completely unaffected either way).
5. Limit-tripped behavior: implement as **Option C (flag-but-store)** per AC-4's locked default —
   do NOT hard-reject at the site-ceiling layer (reserve hard-reject only for the body-size case in
   P1, which is a different failure class). A site-ceiling trip sets the same `is_flagged_abuse`
   marker P4 introduces (P3 and P4 share one flag column — do not invent two separate flags; P3's
   checklist item 5 below is intentionally sequenced after P4's schema exists — see note).
   **Sequencing note**: because `is_flagged_abuse` is defined in P4's migration, P3's "flag on
   ceiling trip" wiring is implemented in code during P3 but the column write only activates once
   P4's migration lands — EXECUTE should implement P3's ceiling-detection logic to set a local
   in-memory/request-scoped signal, and P4 wires that signal into the actual `Event.is_flagged_abuse`
   write at insert time (P4 is where the Event row is actually created). Restate P3's real scope:
   P3 delivers the *detection* (has this site tripped its ceiling in this window), P4 delivers the
   *storage effect* (writing the flag onto the Event row and excluding it downstream). This mirrors
   the SPEC's own flow diagram (site ceiling and velocity signal are parallel inputs into the same
   downstream "limit-tripped response" box).
6. Observability: emit a structured `structlog` warning line when
   `_storage_uri()` degrades to `memory://` (see P5 for the dashboard-facing version) — this
   satisfies checklist item 1 (Redis-degraded state must be surfaced, not just logged silently) at
   the log layer; P5 adds the operator-facing surface.
7. Write `tests/integration/test_ingest_abuse_hardening.py::test_site_ceiling_trips_on_ip_diverse_flood`
   — proves AC-1: simulate N distinct source IPs (mock/patch `resolve_client_ip` per-request or use
   `X-Forwarded-For` with `trusted_proxy_hops` configured for the test) against ONE `site_id`,
   exceeding `site_ingest_limit_per_minute`, assert the ceiling trips even though no single IP
   crosses the existing 100/min per-IP limit.

**Test gates (P3):**
```
.venv/bin/python -m pytest tests/integration/test_ingest_abuse_hardening.py -k "site_ceiling" -q
```

**Proves:** AC-1 (Fully-Automated).

---

## Phase 4 — Write-Time Velocity Flag + Event Column + Migration + Aggregator/Outreach Exclusion

**Goal:** inline, write-time (before `Event` insert) velocity detection combining distinct-visitor
count + distinct-fingerprint diversity per site per window; persist as `Event.is_flagged_abuse`;
propagate exclusion through `visitor_aggregator.py`'s rollup AND `is_emailable_identity()`.

### Checklist

1. **Re-confirm Alembic head is still `a9f2c1e7b4d6`** — run `alembic -c apps/api/alembic.ini
   heads` at the START of this phase (other work may have advanced it since PLAN was written; this
   plan's confirmation via `down_revision` grep-chain is a point-in-time snapshot, not a guarantee).
2. Add to `apps/api/config.py`: `ingest_velocity_enabled: bool = False`,
   `ingest_velocity_window_seconds: int = 60`, `ingest_velocity_visitor_threshold: int = 200`,
   `ingest_velocity_min_fingerprint_diversity: float = 0.3` (all env-overridable, default OFF).
3. Create `apps/api/services/ingest_velocity.py`:
   - `async def check_velocity(redis, site_id: str, visitor_id: str, fingerprint: str | None) -> bool`
     — returns `True` if this request should be flagged.
   - On each call: `SADD` `visitor_id` into `ingest_velocity:visitors:{site_id}`, `SADD`
     `fingerprint` (or a stable hash if empty/None — treat missing fingerprint as its own diversity
     bucket, do not silently drop it from the denominator) into
     `ingest_velocity:fingerprints:{site_id}`; `EXPIRE` both keys to
     `ingest_velocity_window_seconds` on every write (sliding-ish window — matches existing repo
     precedent of `EXPIRE`-on-write rather than exact sliding windows, e.g.
     `company_resolver.py`'s TTL discipline — **explicit TTL is checklist item 2, non-negotiable**).
   - Read `SCARD` for both sets; if `visitor_count >= ingest_velocity_visitor_threshold` AND
     `(fingerprint_count / visitor_count) < ingest_velocity_min_fingerprint_diversity` → flag.
     This is the Q4-locked "distinct-visitor-count + distinct-fingerprint-diversity combined"
     signal, explicitly NOT IP-entropy alone (SPEC's own reasoning: a rotating-IP flood has HIGH IP
     entropy by design, worthless as a sole signal against this exact threat).
   - Fail-open: wrap the whole function body in `try/except Exception` → return `False` (never flag,
     never block) on any Redis error, matching every other Redis-cached check in this codebase
     (datacenter-IP drop, proxy/VPN drop — both documented fail-open at RESEARCH time).
   - Gate on `settings.ingest_velocity_enabled` — when `False`, always return `False` (no-op).
4. Create the Alembic migration `apps/api/migrations/versions/<new-hash>_add_ingest_abuse_flag.py`:
   - `down_revision = "a9f2c1e7b4d6"` (re-confirmed live per checklist item 1 above).
   - `ALTER TABLE events ADD COLUMN is_flagged_abuse BOOLEAN NOT NULL DEFAULT FALSE` +
     `server_default='false'` (matches `Event.optout`'s existing pattern for a new non-nullable
     boolean column — same migration shape, copy that precedent).
   - New index: `ix_events_site_flagged` on `(site_id, is_flagged_abuse)` — supports the
     aggregator's exclusion filter and P5's observability query efficiently.
   - Second change in the SAME migration (or a second migration if EXECUTE decides mixing concerns
     is cleaner — prefer one migration per SPEC's "additive, don't touch unrelated tables" spirit,
     but a schema-adjacent single-purpose split is also acceptable): add the abuse-origin marker to
     the visitor/identity side. **Design choice (corrected at VALIDATE — SUPPLEMENT REQUEST S2):**
     do NOT mirror `source_agent_visit_id`'s placement — that field does NOT propagate through
     `Visitor` at all; it is threaded as an explicit call-parameter from the agent-sweep caller
     directly into `resolve()`/`_save_identified()` via `self._active_source_agent_visit_id`
     (confirmed: `apps/api/services/identity_resolver.py:389-418, 713-739`; no such column exists
     on `Visitor`). The CONFIRMED correct precedent to mirror instead is `Event.optout` →
     `BOOL_OR(optout) AS do_not_resolve` in `aggregate_visitors_for_site`'s raw-SQL
     `session_boundaries`/`SELECT` (`visitor_aggregator.py:267, 300`) → `_upsert_visitor(...,
     do_not_resolve=...)` sticky merge via `on_conflict_do_update`'s
     `"do_not_resolve": text("visitors.do_not_resolve OR EXCLUDED.do_not_resolve")`
     (`visitor_aggregator.py:151-238`, sticky-merge clause at line 234). Add
     `Visitor.is_abuse_flagged: bool` (non-nullable, default `False`, same shape as
     `Visitor.do_not_resolve`) via the aggregator CTE: select `BOOL_OR(is_flagged_abuse) AS
     abuse_flagged` alongside the existing `BOOL_OR(optout) AS do_not_resolve` column, thread it
     through `_upsert_visitor`'s params, and give it the same sticky-merge `OR`-semantics on
     conflict (`"is_abuse_flagged": text("visitors.is_abuse_flagged OR EXCLUDED.is_abuse_flagged")`)
     so a visitor once flagged stays flagged across recomputes. Then add
     `IdentifiedVisitor.is_abuse_flagged: bool` (non-nullable, default `False`) and set it directly
     from `visitor.is_abuse_flagged` inside `_save_identified()` (`identity_resolver.py:713-819`) —
     `visitor: Visitor` is already an in-scope constructor parameter there (confirmed:
     `identity_resolver.py:713-719`), so this is a same-atomic-INSERT read-and-set on the
     `IdentifiedVisitor(...)` constructor call (`identity_resolver.py:792-804`), exactly the same
     shape as the existing `source_agent_visit_id=agent_marker` line — no call-parameter threading
     needed. This propagation mechanism is now CONFIRMED via direct source read (not a Known-Gap —
     see the corrected test coverage in checklist item 8 below).
5. **CRITICAL — edit `visitor_aggregator.py::aggregate_visitors_for_site`'s raw SQL**: add
   `AND is_flagged_abuse IS NOT TRUE` (or `AND NOT is_flagged_abuse`) to both the
   `session_boundaries` CTE's `WHERE site_id = :site_id` clause. Confirmed via RESEARCH re-read: this
   query reads directly from the `events` table with raw SQL, bypassing the ORM — the column
   existing on the `Event` model does nothing here unless this exact `WHERE` clause is edited. This
   is the single most important edit in this plan per INNOVATE checklist item 4 — write a dedicated
   regression test (see item 8 below) that would fail if this edit is skipped or reverted.
6. In `apps/api/routers/events.py`'s `ingest_events()` handler: call `check_velocity(...)` for each
   event (or once per batch — EXECUTE decides based on `EventBatch.events` batching semantics;
   simplest correct behavior is once per batch using `batch.visitor_id` + the first event's `fp`,
   since velocity is a per-visitor-arrival signal, not a per-event-within-batch signal) BEFORE the
   `Event` row(s) are inserted, and set `is_flagged_abuse=True` on the inserted row(s) when either
   P3's site-ceiling trip signal OR P4's velocity check returns `True` (Q4 lock: write-time, at
   insert, matching the existing inline bot/datacenter/proxy pattern — NOT deferred to a background
   aggregator).
7. Extend `is_emailable_identity()` in `identity_classification.py`: add
   `is_abuse_flagged: bool = False` parameter, checked in the SAME unconditional-first-return-False
   block as the existing `source_agent_visit_id is not None` check (checklist item 5 — ONE shared
   helper, both markers gate through it, preventing the "two independent getattr guards scattered
   across the segmenter" drift risk named in INNOVATE). Update BOTH existing call sites
   (`campaign_sender.py:202-203`, `csv_exporter.py:79-81`) to pass the new flag through
   `getattr(iv, "is_abuse_flagged", False)`, matching the existing `getattr` defensive pattern
   already used for `source_agent_visit_id` at those exact call sites.
8. Write `tests/integration/test_ingest_abuse_hardening.py`:
   - `test_abuse_flag_propagates_event_to_identified_visitor` — **the load-bearing AC-4b test (added
     via SUPPLEMENT REQUEST S1)**: exercises the REAL end-to-end path, not a pre-flagged object.
     Insert flagged `Event` rows (`is_flagged_abuse=True`) directly via ORM for a visitor, run the
     real `aggregate_visitors_for_site(db, site_id)`, assert the resulting `Visitor.is_abuse_flagged`
     is `True` (proves the `BOOL_OR(is_flagged_abuse)` CTE column + `_upsert_visitor` sticky-merge
     thread correctly — see checklist item 4's corrected design). Then drive the identity-resolution
     path (call `IdentityResolver._save_identified(visitor, data, provider)` directly, or the full
     `resolve()` path if a provider mock is simpler) and assert the resulting
     `IdentifiedVisitor.is_abuse_flagged` is `True`. Finally assert
     `is_emailable_identity(provider, is_abuse_flagged=identified.is_abuse_flagged)` returns `False`.
     This test MUST fail if propagation breaks anywhere in the chain — it is the only test in this
     plan that proves AC-4b end-to-end rather than testing `is_emailable_identity()` in isolation.
     Docker-gated (requires Postgres — belongs in `tests/integration/`, matching every other test in
     this file per `process/context/tests/all-tests.md`'s integration-lane routing).
   - `test_flagged_events_excluded_from_aggregator_rollup` — proves the CRITICAL P4.5 edit: insert a
     mix of flagged and unflagged `Event` rows directly (bypass the API, write via ORM to isolate
     the aggregator logic), run `aggregate_visitors_for_site`, assert the flagged visitor's rows do
     NOT influence the resulting `Visitor` aggregate (pageviews/sessions counts exclude flagged
     rows). This is a NEGATIVE test that must fail if item 5's `WHERE` edit is reverted — write it
     to genuinely exercise the SQL, not just check the column exists.
   - `test_flagged_identity_never_emailable` — secondary, isolation-level test (NOT end-to-end —
     `test_abuse_flag_propagates_event_to_identified_visitor` above is the end-to-end proof):
     construct an `IdentifiedVisitor` with the abuse marker set directly, assert
     `is_emailable_identity(...)` returns `False` regardless of `provider` value (person-level
     provider included — mirrors the existing `source_agent_visit_id` unconditional-override test
     shape). Kept as a fast, targeted regression for the gating logic itself.
   - `test_organic_viral_spike_not_flagged` — proves AC-5: high volume, high fingerprint diversity
     (each simulated visitor has a distinct `_fp` value), asserts velocity check does NOT flag.
   - `test_shared_nat_high_volume_high_diversity_not_flagged` — proves AC-6 positive case: one IP,
     many distinct visitor_ids AND distinct fingerprints (simulates real users behind one NAT/CGNAT),
     asserts NOT flagged.
   - `test_shared_nat_low_diversity_flagged` — proves AC-6 contrast case: same IP volume, LOW
     fingerprint diversity (same/few fingerprints reused across many visitor_ids — simulates a
     single attacker spoofing identities from one IP), asserts flagged.
   - `test_csv_replay_burst_not_flagged` — **realistic scenario from INNOVATE checklist item 6a, not
     in SPEC's AC list**: a legit site resending old events (e.g. a batch retry/replay) has LOW
     visitor diversity per window (same small set of visitor_ids repeated), which is the OPPOSITE
     signature from a flood (flood = high visitor count). Asserts this shape does NOT trip the
     velocity flag — confirms the threshold logic correctly requires HIGH visitor count as a
     precondition, not just low diversity alone.
   - `test_combined_shared_nat_and_viral_spike_composes` — **INNOVATE checklist item 6b**: a single
     test scenario combining AC-5 (viral spike) and AC-6 (shared-NAT) shapes simultaneously — high
     volume from a mix of many distinct IPs (viral spike shape) AND a subset from one shared IP
     (NAT shape), both with high fingerprint diversity throughout, asserts neither sub-pattern
     triggers a false positive when composed (not just tested in isolation).
9. Write/extend `tests/unit/test_identity_classification.py` (or create if it doesn't exist —
   confirm via `find tests/unit -iname "*identity_classification*"` in EXECUTE) —
   `test_is_emailable_identity_abuse_flag_overrides_provider` — unit-level regression for the same
   AC-4 guarantee as item 8's integration test, at the pure-function level (fast, no DB).

**Test gates (P4):**
```
.venv/bin/python -m pytest tests/unit/test_identity_classification.py -m unit -q
.venv/bin/python -m pytest tests/integration/test_ingest_abuse_hardening.py -k "flagged or organic or shared_nat or csv_replay or combined" -q
```

**Migration round-trip (Docker-gated, standing repo constraint — see Constraints below):**
```
# NOT run against a real environment during EXECUTE — disposable Postgres only, mirrors the
# owned-data-layer/first-party-capture precedent:
alembic -c apps/api/alembic.ini upgrade head
alembic -c apps/api/alembic.ini downgrade -1
alembic -c apps/api/alembic.ini upgrade head
```

**Proves:** AC-4 (Fully-Automated), AC-5 (Hybrid — automated shape-generation is fully-automated per
this plan's tests; the numeric threshold's real-world tuning rationale is documented here rather
than empirically provable pre-launch, matching SPEC's own Hybrid classification), AC-6
(Fully-Automated).

**Resolved at VALIDATE (was a Known-Gap in the original PLAN draft, now closed by SUPPLEMENT
REQUEST S1 + S2):** the propagation mechanism `Event.is_flagged_abuse` → `Visitor.is_abuse_flagged`
→ `IdentifiedVisitor.is_abuse_flagged` was traced line-by-line via direct source read
(`visitor_aggregator.py:151-238, 262-336`, `identity_resolver.py:713-819`) and confirmed to mirror
the existing `Event.optout` → `Visitor.do_not_resolve` sticky-merge precedent, NOT
`source_agent_visit_id` (see checklist item 4's corrected design choice above). This is no longer a
PLAN→EXECUTE research gap — item 4 specifies the exact confirmed mechanism, and checklist item 8's
`test_abuse_flag_propagates_event_to_identified_visitor` proves the REQUIRED OUTCOME end-to-end.

---

## Phase 5 — Operator Observability Surface

**Goal:** a signal the operator can read (dashboard panel, alert, or documented query) that
distinguishes "flood" from "organic spike" without manual raw-event-table archaeology — AND makes
the Redis-degraded/per-replica-ceiling state visible, not silently absent (checklist item 1).

### Checklist

1. Add a new read-only endpoint (extend `apps/api/routers/agents.py`'s pattern — it already has a
   `/agents/{site_id}/analytics`-shaped precedent per `agent_aggregator.py`'s
   `GET /api/v1/agents/{site_id}/analytics` — OR create `apps/api/routers/ingest_health.py` if
   `agents.py` is too semantically distinct; EXECUTE decides based on reading `agents.py`'s current
   scope) — e.g. `GET /api/v1/sites/{site_id}/ingest-health`:
   - Filtered through `Site.user_id == user.id` (multi-tenancy guardrail, per SPEC constraint —
     unknown/foreign `site_id` → 404, never 403, matching repo-wide convention).
   - Returns: recent flagged-event count (windowed), recent site-ceiling trip count, current
     Redis-backend status for both limiters (`"redis"` or `"memory (degraded)"` — this directly
     satisfies checklist item 1: not just a log line, a structured API-visible state), and a simple
     computed "flood-likelihood" signal (e.g. flagged-ratio over the last N minutes vs. a baseline).
2. Add a `structlog` warning emitted once per `_storage_uri()` degraded-fallback detection at
   process level (P3 already added the log line — confirm here it fires exactly once per degraded
   period, not once per request, to avoid log-spam self-inflicted-DoS irony) AND surface the same
   state through the P5.1 endpoint so it's queryable, not just grep-able.
3. Write `tests/integration/test_ingest_abuse_hardening.py::test_ingest_health_endpoint_distinguishes_flood_from_organic`
   — proves AC-7: seed a simulated flood dataset (many flagged events) and a simulated organic-spike
   dataset (many unflagged, high-diversity events) for two different sites, call the endpoint for
   each, assert the returned signal differs meaningfully between the two.
4. Write `tests/integration/test_ingest_abuse_hardening.py::test_ingest_health_endpoint_tenant_scoped`
   — proves multi-tenancy constraint: a user cannot read another tenant's `site_id` ingest-health
   data (404, not 403, per repo convention).

**Test gates (P5):**
```
.venv/bin/python -m pytest tests/integration/test_ingest_abuse_hardening.py -k "ingest_health" -q
```

**Proves:** AC-7 (Hybrid — backend signal computation is Fully-Automated per the tests above; if
EXECUTE chooses a dashboard VISUAL surface rather than a pure API endpoint, the visual rendering
itself needs an Agent-Probe pass, which this plan does not mandate — the SPEC only requires the
signal be "surfaced somewhere the operator can see it," and a documented API endpoint alone
satisfies AC-7's `proven by:` clause as written).

---

## SPEC AC → Phase → Test Mapping

| AC | Phase | Test(s) | Tier | Docker-gated? |
|---|---|---|---|---|
| AC-1 | P3 | `test_site_ceiling_trips_on_ip_diverse_flood` | Fully-Automated | Yes (integration) |
| AC-2 | P1 | `test_oversized_body_rejected`, `test_oversized_chunked_body_rejected` | Fully-Automated | Yes (integration) |
| AC-3 | P2 | `test_ip_resolution.py` (unit, 5 cases) + `test_spoofed_xff_does_not_reset_rate_limit_bucket` | Fully-Automated | Unit: No. Integration: Yes |
| AC-4 | P4 | `test_abuse_flag_propagates_event_to_identified_visitor` (end-to-end, load-bearing), `test_flagged_events_excluded_from_aggregator_rollup`, `test_flagged_identity_never_emailable` (isolation-only), `test_is_emailable_identity_abuse_flag_overrides_provider` | Fully-Automated | Integration: Yes. Unit: No |
| AC-5 | P4 | `test_organic_viral_spike_not_flagged` | Hybrid (numeric threshold tuning documented, not provable pre-launch) | Yes |
| AC-6 | P4 | `test_shared_nat_high_volume_high_diversity_not_flagged`, `test_shared_nat_low_diversity_flagged` | Fully-Automated | Yes |
| AC-7 | P5 | `test_ingest_health_endpoint_distinguishes_flood_from_organic` | Hybrid (surfacing UX is out of this plan's mandatory scope) | Yes |
| AC-8 | P2 | `test_ip_resolution.py` (unit) | Fully-Automated | No |
| AC-9 | P1–P5 (cross-cutting) | see below — Known-Gap on automated enforcement | Known-Gap (see note) | N/A |
| AC-10 | P4 | code inspection: zero new external service call sites (Q5 confirmed at INNOVATE — no external calls added at all) | Fully-Automated (trivial — nothing to mock) | No |
| AC-11 | P1–P5 (regression) | existing `identity_resolver.py` budget tests, unchanged | Fully-Automated (regression) | Depends on existing test's tier |

**AC-9 Known-Gap note:** SPEC requires "code-level regression test/lint asserting new structlog call
sites do not pass raw PII fields, mirrors the existing guardrail enforcement pattern." RESEARCH did
not locate an existing automated PII-lint-on-structlog-calls mechanism in this codebase during this
PLAN pass (the guardrail is currently a code-review convention, not a machine-enforced lint per the
files read). This plan's new log/structlog call sites (P1 reject log, P3 degraded-fallback log, P4
velocity-flag log, P5 health-endpoint) are manually designed to carry only `site_id`, counts, IPs,
and timestamps — zero visitor PII fields (name/email) appear in any new call site by construction.
**Resolution**: EXECUTE should grep the repo for an existing PII-lint mechanism before treating this
as Known-Gap (SPEC's "mirrors the existing guardrail enforcement pattern" implies one may exist and
simply wasn't found in this PLAN pass); if none exists, EXECUTE writes a lightweight regression test
that greps this plan's new files for `structlog` call sites and asserts none of `["email", "name",
"visitor_email"]`-shaped kwargs appear — this is a Fully-Automated tier once written, not a
structural Known-Gap; flag as CONDITIONAL at VALIDATE if EXECUTE cannot confirm.

---

## Test Infra Improvement Notes

(none identified yet)

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_oversized_body_rejected` | Fully-Automated | AC-2 |
| `test_oversized_chunked_body_rejected` | Fully-Automated | AC-2 (chunked-transfer edge case) |
| `test_ip_resolution.py` (5 unit cases) | Fully-Automated | AC-3, AC-8 |
| `test_spoofed_xff_does_not_reset_rate_limit_bucket` | Fully-Automated | AC-3 |
| `test_site_ceiling_trips_on_ip_diverse_flood` | Fully-Automated | AC-1 |
| `test_flagged_events_excluded_from_aggregator_rollup` | Fully-Automated | AC-4 |
| `test_abuse_flag_propagates_event_to_identified_visitor` (end-to-end, load-bearing) | Fully-Automated | AC-4b |
| `test_flagged_identity_never_emailable` + unit variant (isolation-only) | Fully-Automated | AC-4 |
| `test_organic_viral_spike_not_flagged` | Hybrid | AC-5 |
| `test_shared_nat_high_volume_high_diversity_not_flagged` / `_low_diversity_flagged` | Fully-Automated | AC-6 |
| `test_csv_replay_burst_not_flagged` | Fully-Automated | Realistic scenario (INNOVATE 6a, not in SPEC AC list) |
| `test_combined_shared_nat_and_viral_spike_composes` | Fully-Automated | Realistic scenario (INNOVATE 6b, not in SPEC AC list) |
| `test_ingest_health_endpoint_distinguishes_flood_from_organic` | Hybrid | AC-7 |
| `test_ingest_health_endpoint_tenant_scoped` | Fully-Automated | Multi-tenancy constraint (SPEC Constraints) |
| Migration upgrade/downgrade/upgrade round-trip (disposable Postgres) | Hybrid (Docker-gated, not run in this plan's EXECUTE per repo constraint) | Schema safety, no direct AC |
| `identity_resolver.py` budget test regression run | Fully-Automated (regression) | AC-11 |
| AC-9 PII-lint (grep-based or existing mechanism) | Fully-Automated once written / CONDITIONAL if not found | AC-9 |
| AC-10 code-inspection (zero new external calls) | Fully-Automated (trivial) | AC-10 |

---

## Validate Contract

Status: PASS
Date: 25-07-26
date: 2026-07-25
generated-by: outer-pvl
supersedes: 2026-07-25 (outer-pvl) — pass 2 of the same outer-pvl cycle, run against the
plan-validate-fix supplement (S1 + S2) that closed pass 1's BLOCKED verdict

Parallel strategy: sequential deep-read (single validate pass; re-verification scoped to the
supplemented sections + a full regression scan of the unsupplemented ~90% of the plan)
Rationale: This is PVL pass 2, not a fresh validate — the prior pass already ran the expensive
cross-file investigation (slowapi/FastAPI dependency-resolution order, `visitor_aggregator.py`
raw-SQL CTE) and both came back CONFIRMED with no reason to re-derive them from scratch. This
pass targeted its re-reading at exactly the two supplemented items (S1's new test spec, S2's
corrected propagation-precedent citation) plus a line-by-line regression diff of every other
section against the pass-1 record, rather than a full fan-out. Signal count unchanged from pass 1
(3/7: S2 schema/auth-adjacent surface, S6 high-risk class, S7 5+ files) — a *fresh* validate of
this plan would still recommend parallel-subagents/workflow, but a supplement-verification pass is
correctly scoped narrower once the expensive cross-file facts are already on record.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | Site-level ingest ceiling trips on IP-diverse flood, independent of per-IP limiter | Fully-Automated | `test_site_ceiling_trips_on_ip_diverse_flood` | B |
| AC-2 | Oversized `/ingest` body rejected before parse (incl. chunked-transfer, no `Content-Length`) | Fully-Automated | `test_oversized_body_rejected`, `test_oversized_chunked_body_rejected` | B |
| AC-3 | Spoofed `X-Forwarded-For` does not reset the per-IP rate-limit bucket | Fully-Automated | `test_ip_resolution.py` (5 cases) + `test_spoofed_xff_does_not_reset_rate_limit_bucket` | B |
| AC-4a | Flagged events excluded from `aggregate_visitors_for_site` rollup (the CRITICAL raw-SQL edit) | Fully-Automated | `test_flagged_events_excluded_from_aggregator_rollup` | A — VERIFIED viable: raw-SQL bypass of ORM re-confirmed live in `visitor_aggregator.py:262-303`; the plan's `WHERE`-clause edit target and regression test are correctly scoped |
| AC-4b | Abuse-flagged identity is never `is_emailable_identity`, regardless of provider — END-TO-END (`Event` → `Visitor` → `IdentifiedVisitor`) | Fully-Automated | `test_abuse_flag_propagates_event_to_identified_visitor` (P4 checklist item 8, added by SUPPLEMENT S1) | A — VERIFIED sound: re-read the new test spec against the pass-1 FAIL standard. It (1) inserts flagged `Event` rows via ORM as SETUP only, (2) runs the REAL `aggregate_visitors_for_site` and asserts the resulting `Visitor.is_abuse_flagged` — which is only obtainable by re-querying the DB post-aggregation, since the raw-SQL upsert never mutates any in-memory ORM object, so the test cannot "cheat" this step without contradicting its own stated assertion — (3) drives the REAL `_save_identified` (or `resolve()`) with that DB-confirmed `visitor` object, and (4) asserts `is_emailable_identity(provider, is_abuse_flagged=identified.is_abuse_flagged)` is `False` using the value `_save_identified` itself produced. No step short-circuits by constructing a pre-flagged object — this is the fix pass-1 required. |
| AC-5 | Organic viral spike (high volume, high diversity) is NOT flagged | Hybrid | `test_organic_viral_spike_not_flagged` | B |
| AC-6 | Shared-NAT high-diversity NOT flagged; low-diversity same-IP-volume IS flagged | Fully-Automated | `test_shared_nat_high_volume_high_diversity_not_flagged`, `test_shared_nat_low_diversity_flagged` | B |
| AC-7 | Operator can distinguish flood vs. organic spike via a queryable signal | Hybrid | `test_ingest_health_endpoint_distinguishes_flood_from_organic` | B — see execute-agent instruction E3 on the "current" Redis-status wording (unchanged from pass 1, carried forward) |
| AC-8 | IP resolution correct behind a trusted proxy/CDN chain | Fully-Automated | `test_ip_resolution.py` (unit, 5 cases) | B |
| AC-9 | No PII in any new log/counter/alert payload | Fully-Automated (mandatory — see E1) | grep-based regression test over the 4 new call sites (P1/P3/P4/P5) | B — mandatory per E1 (carried forward from pass 1; confirmed still no PII-lint mechanism exists in this repo) |
| AC-10 | Zero new external service calls added | Fully-Automated (trivial) | code inspection / grep for new `httpx`/provider call sites | B |
| AC-11 | Paid-provider budget gates (`daily_resolution_budget`, `default_daily_enrichment_budget`, 30-day no-retry) unchanged | Fully-Automated (regression) | existing `identity_resolver.py` budget test suite, unmodified | B |
| Slowapi ordering | Second (site-ceiling) limiter's `key_func` can read `request.state.site_id` before the rate-limit check fires | Fully-Automated (mechanism CONFIRMED via source, not empirical) | `test_site_ceiling_key_func_reads_site_id` (already specified in P3 checklist item 2) | A — VERIFIED viable in pass 1; P3 was not touched by this supplement, no re-verification needed |
| Alembic head | Migration chains from the true current head | Fully-Automated | `alembic -c apps/api/alembic.ini heads` == `a9f2c1e7b4d6` | A — RE-VERIFIED live at this pass (`grep -rl "a9f2c1e7b4d6" apps/api/migrations/versions/` returns exactly the one file that declares it as its own `revision`, none as `down_revision` — still the head); EXECUTE must still re-confirm live per the plan's own instruction |
| Propagation mechanism (S2) | `Event.is_flagged_abuse` → `Visitor.is_abuse_flagged` → `IdentifiedVisitor.is_abuse_flagged` mirrors `Event.optout` → `do_not_resolve`, NOT `source_agent_visit_id` | Fully-Automated (mechanism CONFIRMED via source, cited lines re-verified) | proven jointly by AC-4a + AC-4b tests above | A — VERIFIED: `visitor_aggregator.py:267` (`optout` selected in the `session_boundaries` CTE), `:300` (`BOOL_OR(optout) AS do_not_resolve`), `:151-238` (`_upsert_visitor`), `:234` (sticky-merge `"do_not_resolve": text("visitors.do_not_resolve OR EXCLUDED.do_not_resolve")`) all match the plan's citations exactly, line-for-line. `identity_resolver.py:713` (`_save_identified` def), `:715` (`visitor: Visitor` in-scope param), `:792` (`identified = IdentifiedVisitor(`), `:803` (`source_agent_visit_id=agent_marker,`) also match exactly. Separately confirmed `source_agent_visit_id` lives on `IdentifiedVisitor` (`models/visitor.py:102`, inside the `IdentifiedVisitor` class starting at `:76`), never on `Visitor` (`:11-75`) — the plan's core corrective claim is TRUE. |

C-4 reconciliation: `strategy:` column carries only Fully-Automated / Hybrid / Agent-Probe.
No row uses Known-Gap as a strategy — every developed behavior in the blast radius now has a
proving Fully-Automated or Hybrid gate (the vacuous-green ban is satisfied).

Legacy line form (retained for existing consumers):
- ingest hardening (P1-P5): Fully-automated: `.venv/bin/python -m pytest tests/integration/test_ingest_abuse_hardening.py -q` (Docker-gated: requires `docker compose -f infra/docker-compose.yml up -d postgres redis`) | hybrid: AC-5/AC-7 numeric-threshold rationale documented in plan, not empirically provable pre-launch | agent-probe: none required | known-gap: none remaining — AC-4b's propagation test is now specified end-to-end (SUPPLEMENT S1)

Dimension findings:
- Infra fit: PASS — pass-1's sole gap (P5's "current Redis-backend status" wording) is resolved by
  making E3 a mandatory execute-agent instruction (EXECUTE must either relabel the field honestly
  or add a live `PING`); this is not a plan-text defect, so no further plan edit is needed. All
  other infra claims (PixelCORSMiddleware pattern, middleware-order rule, `_storage_uri()`
  shared-Redis-URI reuse, Alembic head) remain VERIFIED and were unaffected by the supplement.
- Test coverage: PASS — the FAIL-1 gap (AC-4b's aspirational tests) is closed: SUPPLEMENT S1 added
  `test_abuse_flag_propagates_event_to_identified_visitor`, a genuine end-to-end test that drives
  the real aggregator and the real save path rather than constructing pre-flagged objects (see the
  AC-4b test-gates row above for the full re-verification). Every AC now has a concrete,
  non-aspirational proving test or an explicitly-documented Hybrid rationale. AC-9's coverage is
  mandatory per E1 (unchanged from pass 1).
- Breaking changes: PASS — unaffected by the supplement (S1/S2 touched only P4 checklist items 4
  and 8 plus two tables); re-confirmed additive-only, `POST /ingest` response shape unchanged,
  all 3 existing `is_emailable_identity()` call sites correctly identified, `hot_alert.py:88`
  correctly identified as a pre-existing gap out of scope (re-confirmed via grep this pass: that
  call site still does not pass `source_agent_visit_id`, and will not pass the new `is_abuse_flagged`
  param either by default-`False` — this is the SAME pre-existing gap, not a new one introduced or
  worsened by this plan).
- Security surface: PASS — pass-1's gap (no PII-lint/CI mechanism exists in this repo) is resolved
  by making AC-9's grep-based regression test mandatory (E1), which is now baked into the Test
  Gates table as a required Fully-Automated gate rather than left as an execute-agent-discretion
  item. Fail-open defaults and OFF-by-default settings re-confirmed unchanged.

Layer 2 sections:
- P1 (body-size guard): PASS — unaffected by the supplement; re-confirmed unchanged from pass 1.
- P2 (trusted-proxy IP): PASS — unaffected by the supplement; re-confirmed unchanged from pass 1.
- P3 (site-ceiling limiter): PASS — unaffected by the supplement; the slowapi/FastAPI
  dependency-ordering finding stands as verified in pass 1, no re-derivation needed this pass.
- P4 (velocity flag + migration + exclusion): PASS — both pass-1 gaps closed. (1) The CRITICAL
  `visitor_aggregator.py` raw-SQL edit target remains VERIFIED TRUE (re-read this pass,
  `visitor_aggregator.py:262-303`). (2) The propagation-mechanism guidance (checklist item 4) now
  correctly cites `Event.optout` → `BOOL_OR(optout) AS do_not_resolve` → `_upsert_visitor` sticky
  merge as the precedent to mirror, not `source_agent_visit_id` — every line citation in that
  guidance was independently re-verified against the live source this pass (see the "Propagation
  mechanism (S2)" row above) and all match exactly. (3) Checklist item 8 now specifies a genuine
  end-to-end test (see AC-4b above). Regression check: confirmed via full read that no other part
  of P4 (or any other phase) was altered beyond checklist items 4 and 8, the Known-Gap paragraph,
  and the AC-mapping/Verification-Evidence tables — matches the iteration-001 report's claimed
  edit scope exactly.
- P5 (observability): PASS — the "current Redis-backend status" wording gap is resolved via
  mandatory execute-agent instruction E3 (carried forward unchanged); endpoint design,
  multi-tenancy (`Site.user_id`, 404-not-403), and test list remain sound.

Open gaps: none blocking. One non-blocking observation newly surfaced during this pass (not a
plan defect, not required to change before EXECUTE):
- **Resolution-budget spend on abuse-flagged visitors (observational, non-blocking).** Confirmed
  via `apps/api/tasks/resolution_tasks.py:62` that the periodic resolution sweep filters on
  `Visitor.do_not_resolve.is_(False)` but nothing analogous for `is_abuse_flagged` — this plan does
  not add `is_abuse_flagged` to that filter, so a flagged visitor's identity resolution attempt
  (and its paid-provider budget consumption) still runs; only the resulting identity's
  emailability is gated. This is consistent with SPEC's own explicit framing (Summary: "Because
  Beam's paid lookups... are already budget-capped, this kind of attack can't run up an API bill...
  this work is about data/DB/availability protection") and with AC-11's requirement to leave the
  budget system untouched — so this is a defensible, in-scope design choice, not a gap against any
  AC. Noted here for the record in case a future SPEC wants to extend `do_not_resolve`-style
  filtering to abuse-flagged visitors as a budget-conservation optimization.

What this coverage does NOT prove:
- AC-1 through AC-3, AC-5, AC-6, AC-8, AC-10, AC-11 gates prove exactly the scenario named in each
  test — they do NOT prove correctness across replica boundaries (multi-instance Redis-vs-memory
  split-brain is out of scope per SPEC's own framing, tracked only as a design constraint on
  `_storage_uri()` reuse).
- AC-4b's new end-to-end test proves the propagation chain works when driven directly
  (`_save_identified` or `resolve()` called in the same test flow immediately after aggregation);
  it does NOT prove the chain holds under the actual production timing where the periodic
  resolution Celery task (`resolution_tasks.py`) may run concurrently with, or before, the next
  `aggregate_visitors_for_site` pass for a given visitor — this ordering risk is structurally
  identical to the pre-existing `do_not_resolve` propagation (same architecture, same async
  scheduling), not a new risk this plan introduces.
- AC-9's mandatory grep-test proves the 4 *new* call sites named in this plan carry no PII kwargs;
  it does NOT retroactively audit any pre-existing structlog call site in the codebase.
- AC-5/AC-7's Hybrid tier proves the automated shape-generation and signal-computation logic; the
  actual numeric threshold values (200 visitors/window, 0.3 diversity ratio) are calibration
  decisions this plan documents rather than empirically proves correct for real traffic.
- The Alembic migration round-trip (P4) proves schema safety on a disposable Postgres; it does NOT
  constitute a production live-apply, which remains a separate explicit operator action per every
  prior migration in this repo (agent_detection_enabled/company_graph_enabled precedent).
- Resolution-budget spend on abuse-flagged visitors is NOT prevented by anything in this plan (see
  Open gaps observation above) — out of scope per SPEC, not a coverage gap against any AC.

Execute-Agent Instructions (unchanged from pass 1 — carried forward verbatim; still binding):
- E1: AC-9's grep-based regression test is MANDATORY, not optional. No PII-lint mechanism exists in
  this repo (re-confirmed at this pass), so the grep-test is the only enforcement and must be
  written.
- E2: Implement P3's site-ceiling `key_func` site_id stash as a genuine FastAPI `Depends()` parameter
  in the route signature (confirmed via `fastapi/routing.py` that `solve_dependencies()` runs before
  the endpoint — including a slowapi-wrapped endpoint — is ever called). Do not fall back to the
  manual-`.hit()`-after-parse alternative unless the `Depends()` approach is empirically shown to fail
  in EXECUTE's own test run; if it does fail, document why in the phase report since it contradicts
  this VALIDATE pass's source-level confirmation.
- E3: P5's observability endpoint must not claim "current" Redis-backend status without either (a) an
  explicit doc-comment/field name clarifying it reflects process-start resolution only, or (b) a live
  `PING`-based check. EXECUTE decides; state the choice in the phase report.
- E4: Resolve `_storage_uri()` once (e.g., a module-level cached value) and pass the same resolved
  URI string to both `Limiter()` constructions, rather than calling `_storage_uri()` a second time —
  avoids a duplicate Redis ping + duplicate warning log at boot. Cosmetic, not blocking.
- E5 (new this pass): the P4 checklist item 8 propagation test must fetch `Visitor` fresh from the
  DB after calling `aggregate_visitors_for_site` (not reuse a pre-aggregation in-memory ORM object)
  before passing it into `_save_identified`/`resolve()` — this is the only way the assertion on
  `Visitor.is_abuse_flagged` is meaningful, since the aggregator writes via raw SQL and never
  mutates an in-memory ORM instance. Document this explicitly in the test's arrange step so a future
  refactor doesn't accidentally silently defeat the test by reusing a stale object.

Gate: PASS
Accepted by: N/A — Gate is PASS (0 unresolved FAILs, 0 unresolved CONCERNs). Both pass-1 gaps (S1
FAIL, S2 CONCERN) verified closed by direct source re-read, not taken on faith from the supplement
agent's claims. Execute-Agent Instructions E1-E5 remain binding directives for EXECUTE to follow;
none of them block this PASS verdict.

---

## Autonomous Goal Block

SESSION GOAL: Harden POST /ingest against rotating-IP flood/DDoS abuse (5 additive phases:
body-size cap, trusted-proxy IP resolution, per-site rate ceiling, write-time velocity flag,
operator observability) without touching paid-provider budgets or weakening existing filters.
Charter + umbrella plan: N/A — single COMPLEX plan, not a phase program.
Autonomy: standard RIPER-5 gates apply; PVL (plan-validate-fix) loop governs this plan until Gate:
PASS or an accepted CONDITIONAL with ≥1 supplement cycle recorded.
Hard stop conditions / safety constraints:
- Must not weaken/bypass the existing per-IP limiter, bot filter, datacenter-IP drop, or
  proxy/VPN-IP drop (additive only).
- Must not touch `daily_resolution_budget`, `default_daily_enrichment_budget`, or the 30-day
  no-retry rule.
- Must not log PII in any new log line, counter, or alert payload.
- All new settings must default OFF/permissive; enabling in a real environment is a deliberate
  post-migration operator action.
- Migrations are Docker-gated — never applied to a real environment during EXECUTE.
- AC-4's outreach-exclusion guarantee (abuse-flagged identity is never emailable) has a real,
  non-aspirational end-to-end test (`test_abuse_flag_propagates_event_to_identified_visitor`,
  added in PVL cycle 1, re-verified in PVL pass 2) — this hard stop is now SATISFIED.
Next phase: EXECUTE — Gate is PASS (PVL pass 2, after 1 supplement cycle). Follow Execute-Agent
Instructions E1-E5 in `## Validate Contract` (E1 PII-lint test is mandatory; E5 governs the AC-4b
test's DB re-fetch requirement). Phases run strictly in order per `## Phase Ordering` (P1 -> P2 ->
P3 -> P4 -> P5) — do not skip ahead.
Validate contract: inline in this plan (see `## Validate Contract` above). Gate: PASS. 2 PVL
cycles recorded (see `results.tsv` in this task folder).
Execute start: `.venv/bin/python -m pytest tests/integration/test_ingest_abuse_hardening.py -q`
(Docker-gated: requires `docker compose -f infra/docker-compose.yml up -d postgres redis`) | e2e
spec: none (server-side only) | probe scenario: none required | high-risk pack: yes — this plan
touches auth-adjacent trust-boundary logic (IP resolution) + a public API surface change (413) + a
schema migration + the outreach-eligibility guardrail; a `vc-risk-evidence-pack` should be
produced before EXECUTE is treated as finalize-ready.

---

## Resume and Execution Handoff

1. **Selected plan file path**: `process/features/pixel/active/ingest-abuse-hardening_25-07-26/ingest-abuse-hardening_PLAN_25-07-26.md`
2. **Last completed phase or step**: PLAN written; no EXECUTE steps have started.
3. **Validate-contract status**: Gate: PASS (see `## Validate Contract` above) — written after PVL pass 2, 25-07-26. 1 supplement cycle recorded in `results.tsv`.
4. **Supporting context files loaded during this PLAN pass**:
   - `process/features/pixel/active/ingest-abuse-hardening_25-07-26/ingest-abuse-hardening_SPEC_25-07-26.md`
   - `process/context/all-context.md`
   - `process/context/tests/all-tests.md`
   - `apps/api/routers/events.py`, `apps/api/services/rate_limiter.py`, `apps/api/main.py`,
     `apps/api/models/event.py`, `apps/api/services/visitor_aggregator.py`,
     `apps/api/services/identity_classification.py`, `apps/api/models/visitor.py`,
     `apps/api/config.py`, `apps/api/schemas/events.py`,
     `tests/integration/test_events_ingest.py`, full Alembic migration chain
     (`apps/api/migrations/versions/*.py` — confirmed `a9f2c1e7b4d6` has no child migration)
5. **Next step for a fresh agent picking up mid-execution**:
   - If VALIDATE has not run: invoke `vc-validate-agent` on this plan file next.
   - If VALIDATE has run and gate is PASS/accepted-CONDITIONAL: run `ENTER EXECUTE MODE` for this
     plan, starting at Phase 1 (body-size guard) — phases are strictly ordered per §Phase Ordering,
     do not skip ahead.
   - **First action inside P4**: re-run `alembic -c apps/api/alembic.ini heads` to re-confirm
     `a9f2c1e7b4d6` is still the current head before writing the new migration's `down_revision`.
   - **Known-Gap requiring EXECUTE-time research** (not a blocker, but must be resolved before P4
     item 4/7 can be implemented correctly): read `visitor_aggregator.py::_upsert_visitor` in full
     and `identity_resolver.py`'s `IdentifiedVisitor`-creation call chain in full to confirm the
     exact propagation mechanism from `Event` → `Visitor` → `IdentifiedVisitor` before choosing where
     the abuse-origin marker column lives.

---

## Constraints Carried Forward From SPEC (do not re-litigate in EXECUTE)

- Must not weaken/bypass the existing per-IP limiter, bot filter, datacenter-IP drop, or
  proxy/VPN-IP drop — every phase above is additive only; confirmed no existing check is edited or
  removed anywhere in this plan.
- Must not touch `daily_resolution_budget`, `default_daily_enrichment_budget`, or the 30-day
  no-retry rule — confirmed zero touchpoints in `identity_resolver.py`'s budget logic.
- Must not log PII — see AC-9 note above.
- New external calls need mock-mode — N/A, zero new external calls (Q5).
- New counters/thresholds scoped to `Site`, filtered by `Site.user_id` on operator-facing reads —
  confirmed in P5's endpoint design.
- Redis vs. `memory://` per-replica hazard must be accounted for — P3 explicitly reuses the existing
  shared `_storage_uri()` rather than inventing a parallel storage mechanism, and P1/P3/P5 all
  surface the degraded state rather than silently accepting per-replica correctness loss.
- No pixel client-side visible/interactive element — confirmed zero `apps/pixel/` touchpoints in
  this plan; all hardening is server-side.
- New thresholds configurable via `pydantic-settings` — confirmed every new setting listed in
  §Public Contracts lives in `apps/api/config.py`.
- **Migrations are Docker-gated and NOT applied to any real environment as part of EXECUTE** — the
  round-trip test in P4 runs against a disposable Postgres only, matching the
  owned-data-layer/first-party-capture precedent noted in `process/context/all-context.md`.

## Next Step

Next: **ENTER VALIDATE MODE** to convert this plan into an executable V1–V7 contract before EXECUTE. After VALIDATE passes/is accepted, the following phase resumes with **ENTER EXECUTE MODE** for this plan, Phase 1 first.
