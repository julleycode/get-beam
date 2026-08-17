---
name: plan:public-canary-funnel
description: Residual hardening of the already-shipped public unauthed canary endpoint + truncated static funnel — input caps, body-size guard, abuse observability, static-page e2e, rollout
date: 11-08-26
feature: onboarding-canary
---

# Public canary endpoint + truncated static funnel — residual hardening

**Date**: 11-08-26
**Status**: PLANNED (not validated, not executed)
**Complexity**: COMPLEX
**Feature**: onboarding-canary
**Branch baseline:** `devjulley`, clean. Alembic head `f4b9d2a71c68`.

**Unit-lane baseline — command and number are always stated together (F-2).** Two different
commands produce two different numbers; never quote a bare count:

| Command | Live result (11-08-26) |
|---|---|
| `.venv/bin/python3.11 -m pytest tests/unit -m unit` — **this is AC-13's regression gate** | **1750 passed / 2 skipped** (933+ deselected by the `-m unit` marker filter) |
| `.venv/bin/python3.11 -m pytest tests/unit` (full collection, no marker filter) | **2683 passed / 2 skipped** (2685 collected) |

The gate is PINNED to the `-m unit` variant. The full-collection number is recorded only so the two
can never be conflated again. Any baseline mention anywhere in this plan states command + number.

## TL;DR

The work this plan was asked to design **already shipped** in commit `a621edd`
("feat(onboarding): conversational rebuild + canarytoken location reveal"). The static funnel is
already truncated to 5 steps (928 → 501 + 184 lines) and already calls a public unauthed twin at
`POST /api/v1/demo/canary` that shares `services/onboarding_canary.py` with the authed route, with
11 integration tests. Re-building any of it would be a regression.

What is *not* done is the hostile-input half of the public surface. This plan closes eight residual
gaps — **unbounded `fingerprint` on FOUR unauthed routes** (not two), **unbounded `shown` JSONB**,
**no body-size guard on the public POSTs**, **no abuse counters**, **no e2e on the static page**,
**a shared global geo budget/backoff that lets a public flood blind `/ingest` geo for every
customer site**, **no retention purge on the public `identity_feedback` write path**, and **an
unrunnable Playwright gate** — plus the rollout that turns the flag on. Zero new endpoints. Zero
migrations. Zero React changes.

---

## Overview / Context

### What the parent plan asked for, and where it actually stands

The parent plan (`canary-onboarding_10-08-26/canary-onboarding_PLAN_10-08-26.md`, §Legacy static
funnel) named this follow-up:

> truncate it to welcome → canary_go → canary_listen → canary_reveal → "create your account" handing
> off to `/sign-up`, deleting install/detect/sample/paywall/account/dash — roughly 600 of its 928
> lines — and have it call a public unauthed twin of `/canary` sharing `onboarding_canary.py`.

**Audit of the live tree (re-derived by content on 11-08-26, not from the parent plan's prose):**

| Requested item | Status on disk | Evidence |
|---|---|---|
| Funnel truncated to 5 steps | **DONE** | `onboarding-app.js:12` — `STEP_ORDER = ['welcome','canary_go','canary_listen','canary_reveal','account']`; file is 184 lines |
| ~600 lines deleted from steps | **DONE** | `onboarding-steps.js` is 501 lines (was 928 combined ~1112); `install`/`detect`/`sample`/`paywall`/`account`(hand-rolled Clerk)/`dash` all gone; header comment documents the deletion |
| Ending = CTA → `/sign-up` | **DONE** | `onboarding-steps.js` `account(ob)` → `window.location.href = '/sign-up'` |
| Public unauthed twin of `/canary` | **DONE** | `apps/api/routers/demo.py` `@router.post("/canary")` → `demo_canary`, no `Depends(get_current_user)` |
| Shares `onboarding_canary.py` | **DONE** | `demo_canary` imports `build_geo`, `build_network`, `fetch_journey` from the service — no forked logic |
| Flag-gated, 404 when off | **DONE** | `_require_location_reveal()` → 404 on `location_reveal_enabled` false, both public routes |
| Site hard-pinned, no enumeration | **DONE** | `fetch_journey(db, fp, site_id=settings.beam_self_site_id)`; `CanaryPublicBody` has exactly one field |
| IP never in response | **DONE** | logged `ip[:8]`; asserted by `test_response_never_leaks_identifiers` |
| `resolve_client_ip` key func on the limiter | **DONE** | `rate_limiter.py` — `Limiter(key_func=client_ip_key_func, ...)`; `client_ip_key_func` wraps `resolve_client_ip`, which checks `CF-Connecting-IP` first |
| Per-IP rate limit | **DONE** | `_PUBLIC_CANARY_RATE = "40/minute"` (authed twin 30/min); `test_rate_limit_trips` |
| Response shape identical to authed twin | **DONE** | same 4-key dict + optional `reason`; static funnel reuses the same format rules as `src/lib/canary-format.ts` |
| Mock-mode deterministic geo | **DONE** | `geoip.py:_mock_geo` + MOCK-FIRST branch ahead of the loopback guard in `resolve_geoip_full` |
| Leaflet on a page with no React | **DONE** | unpkg CDN `leaflet@1.9.4` loaded lazily in `renderMap`, with a `tileerror`/deadline fallback to the text reveal |
| `src/app/onboarding/page.tsx` deleted | **DONE, VERIFIED** | directory does not exist; deleted in `a621edd`. `next.config.mjs:58` rewrite `/onboarding → /beam/onboarding.html` is intact and is now the *only* server for that path |

**Conclusion: the build is complete. This plan is a hardening pass, not a rebuild.**

### The residual gaps

| ID | Gap | Class | Why it matters |
|---|---|---|---|
| **G1** | `fingerprint` accepted with no length or charset bound on both public POSTs | hostile input | `CanaryPublicBody.fingerprint: str \| None` is unbounded. `fetch_journey` requires the `fp2_` prefix but caps nothing, so a 10 MB `"fp2_" + "A"*10_000_000` is parsed, bound into a parameterized `WHERE Visitor.fingerprint = $1`, and shipped to Postgres. The query is injection-safe; the *cost* is not bounded. |
| **G2** | `shown: dict` on the public feedback route is unbounded and unvalidated | hostile input + storage | `demo_identity_feedback` writes `body.shown` verbatim into a JSONB column, unauthed, at 12/min/IP. Arbitrary nested JSON of arbitrary size, permanently stored. `reasons` and `note` are both bounded already; `shown` is the one that is not. |
| **G3** | `IngestBodySizeLimitMiddleware._GUARDED_PATHS` is `{"/api/v1/events/ingest"}` only | DoS | All four unauthed, fingerprint-bearing demo POSTs (`/identify`, `/journey`, `/canary`, `/identity-feedback`) get no streaming body guard. Their schema caps run only *after* FastAPI has buffered and parsed the body, so they bound storage but not memory; a chunked request can otherwise force unbounded buffering before validation. |
| **G4** | No abuse counters on the public surface | observability | One `logger.info("demo_canary", ...)` per success. Nothing distinguishes a flood: no oversize-reject, no 429, no rejected-fingerprint, no per-minute rate signal. Rollback would be blind. |
| **G5** | No e2e on the truncated static page | test infra | `apps/web/e2e/onboarding-canary.spec.ts` covers the **dashboard** React beat (`/dashboard/onboarding`). `onboarding.spec.ts` also targets `/dashboard/onboarding`. Nothing loads `/onboarding` (the static funnel) at all. The 5-step vanilla flow — the only logged-out surface — has zero browser coverage. |
| **G6** | The public canary geo path shares ip-api's **global 45/min budget** and the **single global `geoip:backoff` Redis key** with the `/ingest` hot path | **DoS / blast-out to every customer site** | `geoip.py:49` `_BACKOFF_KEY = "geoip:backoff"` is one key for all callers. `demo.py:344-347` deliberately exempts the canary from `_enforce_demo_budget` ("a free geo lookup must not exhaust the identity-graph budget") — correct for the *identity* budget, but it leaves the *geo* call with no aggregate ceiling at all. A rotating-IP flood defeats the 40/min per-IP limit, drives ip-api to 429, and the 429 handler sets the **global** backoff for up to `X-Ttl` (≈300 s). For that whole window `resolve_geoip` returns `("","")` for **every customer site's ingest**. A public marketing funnel must not be able to degrade paying tenants' data. |
| **G7** | `identity_feedback` rows are written unauthenticated and **never purged** | retention / GDPR | `apps/api/services/retention.py` purges `events` (`event_retention_days`), `agent_fetch_events`, and `request_logs`. There is no `purge_identity_feedback_older_than`. The table stores a device `fingerprint` (`String(100)`), rendered city/region/org and a rounded lat-lng, written by an unauthed 12/min/IP route. The per-IP limit is **not a bound** — the key is caller-forgeable (see Risk 9) — so unbounded growth is the default, not the tail case. |
| **G8** | The AC-10 Playwright gate is not runnable and would produce a false green | test infra | `apps/web/playwright.config.ts` has exactly one non-setup project, which carries `storageState: "e2e/.auth/user.json"` and `dependencies: ["setup"]`. Any new spec in `e2e/` inherits both — so the "logged-out public funnel" spec would run **authenticated**, and a regression that walls `/onboarding` behind auth would still pass. |

### One live-state finding worth recording (not a gap to fix here)

`location_reveal_enabled` defaults **False** in prod. The static funnel's `canary_listen` breaks
after `MAX_CONSECUTIVE_ERRORS = 3` 404s (~6 s), then renders the honest "couldn't catch you"
branch. So `/onboarding` today is a working, honest, *demo-less* funnel: welcome → catch me → 6 s →
"couldn't catch you this time" → create your account. That is by design (dormant, not broken), but
it means **the flag flip in Phase 3 is what actually ships the feature to the public**, and until
then the public funnel's value proposition is unproven in the field.

### Context consulted

- `process/context/all-context.md` — business guardrails: PII/GDPR (never log PII; blind-index/
  encrypt at rest), mock-mode requirement (every external API must work under
  `MOCK_EXTERNAL_APIS=true`), multi-tenancy (404 not 403 on foreign ids).
- `process/context/tests/all-tests.md` (+ its routing chain: integration lane needs Postgres on
  `localhost:5433` and Redis DB 15 per `tests/conftest.py`; Docker IS available on this machine —
  the CLI is off `PATH` at `/Applications/Docker.app/Contents/Resources/bin/docker`).
- `process/context/planning/all-planning.md` — COMPLEX plan shape.
- Parent plan §Backend, §Frontend, §Degraded paths, §Risks (2 CF client-IP, 3 adblock, 6 ip-api
  terms, 7 OSM tile policy).
- `canary-onboarding-phase-3_REPORT_10-08-26.md`, `maxmind-and-feedback-ops_NOTE_11-08-26.md`.
- `apps/web/src/middleware.ts` — `geoRedirect` (C-7 in the supplement request / C-4 in the contract):
  `/onboarding` 302s to `/login` whenever `x-vercel-ip-country` is present and `!== "US"`. The public
  funnel is **US-only on any Vercel-fronted environment**. Locally the header is absent, so the
  Playwright legs pass; a non-US hand-tester in Phase 5 will see a redirect, not a broken funnel.
- `apps/api/services/retention.py` — the existing purge pattern (`purge_events_older_than`,
  `purge_agent_fetch_events_older_than`, `purge_request_logs_older_than`; advisory-lock + batched
  delete + `*_retention_purge_complete` log). `identity_feedback` has no equivalent — see Phase 2b.
- `apps/api/services/geoip.py:49` — `_BACKOFF_KEY = "geoip:backoff"` is a **single global key**
  shared by every caller of `resolve_geoip*`, including the `/ingest` hot path. See S1 below.
- `apps/api/services/ip_resolution.py:54-63` — `CF-Connecting-IP` is trusted unconditionally when
  `ingest_trust_cf_connecting_ip` is on, with no check that the peer is a Cloudflare edge.

---

## Goals

1. Bound every caller-controlled input on the two public POSTs, before it reaches the DB or the ORM.
2. Reject oversized public canary bodies before they are buffered, reusing the existing middleware.
3. Make an abuse event visible in structlog without logging PII.
4. Give the truncated static funnel its first browser-level regression net.
5. Turn the feature on, staging first, with a one-line rollback.

## Non-Goals (explicit)

- Rebuilding anything listed DONE in the audit table. If EXECUTE finds itself editing
  `STEP_ORDER`, deleting funnel steps, or writing a new `/canary` route, it has misread this plan —
  **stop**.
- Changing the authed `/api/v1/onboarding/canary` behaviour in any way.
- Any change to `/ingest`, the pixel, or the React dashboard onboarding.
- A separate `public_canary_enabled` flag. See Decision D1.
- Migrating off ip-api to MaxMind GeoLite2-City (parent risk 6) — already shipped dormant, activated
  by operator per `maxmind-and-feedback-ops_NOTE_11-08-26.md`. **Its activation is nonetheless a
  HARD precondition of the Phase 5 flag flip (D7 half i), not an optional improvement.**
- Per-subject GDPR **erasure** for `identity_feedback`. Phase 2b adds age-based **retention** only.
  Erasure needs its own plan — `process/features/onboarding-canary/backlog/identity-feedback-gdpr-erasure_NOTE_11-08-26.md`, marked
  NEW PLAN REQUIRED, and it is Phase 5 precondition P-d.
- Fixing `CF-Connecting-IP` forgeability (`ip_resolution.py:54-63`). Pre-existing, repo-wide, and
  larger than this plan; documented as a known-gap + backlog stub.
- Proxying OSM tiles (parent risk 7) — explicitly forbidden by the parent plan.

---

## Design Decisions

**D1 — Reuse `location_reveal_enabled`; do NOT add `public_canary_enabled`.**
*Rationale:* the public route is a *twin* of the authed route over identical shared builders. A
second flag creates four states, two of which are incoherent ("public reveal on, authed reveal off"
means the logged-out funnel shows a capability the dashboard denies). It also doubles the rollback
surface: an operator paging at 3am needs one switch, not a truth table. The rate limits are already
independent (40/min public vs 30/min authed), which is where the two surfaces genuinely differ.
*Rejected alternative:* a separate flag to kill the public surface while keeping the authed one.
Cheaper equivalent already exists — the public route can be starved by lowering
`_PUBLIC_CANARY_RATE`, and a true emergency kill is the same one flag.

**D2 — Cap the fingerprint at 64 chars and `[A-Za-z0-9_]` only, at the Pydantic boundary.**
*Rationale (corrected 11-08-26 — the earlier "= 20 chars" claim was wrong, C-1):* a real fp2 value
is `"fp2_"` + four base-36 words. `_h128`/`hash128` return `h[0..3].toString(36)`
(`onboarding-steps.js:45`, `tracker.js:93`, `beam-fingerprint.ts:29`); base-36 of a uint32 is
**1–7 chars**, so a real value is **8–32 chars and variable-length, never a fixed 20**. The observed
maximum is `4 + 4×7 = 32`. 64 is therefore ~2× headroom over the true worst case (not 3× over a
fictional 20), which is still ample for a future scheme without being a meaningful DB argument. Charset from the same generator — base-36 plus
the `fp2_`/`fp3_` prefix underscore. Enforcing at the schema, not inside `fetch_journey`, means a
reject costs zero DB round-trips and returns 422 before any handler code runs. Applying it to
`fetch_journey` **as well** (defence in depth, silent `[]`) protects the authed twin and
`/demo/journey` on the same edit.
*Rejected:* validating only inside `fetch_journey` — the value would still be buffered, bound, and
logged.

**D3 — Cap `shown` by serialized size (2 KB) and key count (16), and coerce non-dict to `{}`.**
*Rationale:* the client sends exactly 7 scalar keys (`city, region, country_code, lat, lng, org,
kind` — `onboarding-steps.js` feedback handler). 16 keys / 2 KB is generous headroom for one more
field while refusing a blob. Size is checked on `json.dumps` length because JSONB storage cost
tracks serialized bytes, not key count alone. Over-limit → store `{}` and count it (never 4xx: the
client is optimistic and fire-and-forget; rejecting would be invisible to the user and would only
lose the `reasons`, which are the valuable part).
*Rejected:* a strict Pydantic model for `shown` — it is deliberately a free-form record of *what we
rendered*, and pinning its schema couples the feedback table to today's reveal layout.

**D4 — Extend `IngestBodySizeLimitMiddleware._GUARDED_PATHS` rather than adding Content-Length
checks in the handlers.**
*Rationale:* the middleware already implements both layers the constraint asks for (Content-Length
fast path **and** a running byte counter that survives chunked transfer-encoding / a forged header).
A handler-level `Content-Length` check has neither property — a chunked request with no
`Content-Length` bypasses it entirely, which is exactly the case the middleware exists for. The
guard set is a `set` literal; adding all four unauthed, fingerprint-bearing demo POST paths is a
set-literal change with no new code path.
*Consequence to accept:* the 256 KB `ingest_body_max_bytes` cap is shared. That is ~1000× the real
canary body (~60 bytes) and the D2/D3 caps do the tight bounding; the middleware is the
memory-exhaustion backstop only. Guard `/identify`, `/journey`, `/canary`, and
`/identity-feedback`; do **not** introduce a second size setting for these tiny routes.
*Rejected:* a new `public_canary_body_max_bytes` setting — one more knob, no additional safety given
D2/D3.

**D5 — Static-page e2e stays fully network-mocked, targeting `/onboarding`.**
*Rationale:* the real endpoint 404s (flag off) and a real catch needs a live pixel hit from the same
fingerprint, which no CI runner can produce. Mock `**/api/v1/demo/canary` with `page.route`
answering OPTIONS with CORS headers (the funnel calls `api.getbeam.fyi` cross-origin — the
established pattern at `onboarding.spec.ts`), and route `**/unpkg.com/leaflet**` +
`**/tile.openstreetmap.org/**` so CI does zero third-party I/O.
*Rejected:* driving the real endpoint in CI — non-deterministic and requires the flag on in a test
env, which contradicts the dormant-by-default posture.

**D6 — Text-vs-map on the static page: keep the shipped CDN-Leaflet decision.**
The task framing suggested text-mode-only to avoid a CDN script include. That decision was already
made the other way and shipped, and it is the better one *given what is on disk*: `renderMap`
already has the honest failure ladder (4 `tileerror`s in 2.5 s **or** no `load` in 4 s → destroy the
map, fall back to text), so the text mode exists as the degraded path rather than as the only path.
There is no CSP anywhere in `apps/web` (verified: `next.config.mjs` `headers()` sets only
`Cache-Control`/`Vary` for `/blog`; no `middleware.ts` CSP; no `<meta>` CSP in `onboarding.html`), so
the CDN include is not blocked. **Action for this plan is a comment, not a rewrite:** note beside
`LEAFLET_JS` that a future CSP needs `unpkg.com` in `script-src`/`style-src` and the tile host in
`img-src`. Parent risk 7 (OSM tile policy) is unchanged — attribution is present and must not be
hidden; volume stays low.

**D7 — The public canary gets its own bounded aggregate geo budget AND its own backoff namespace;
MaxMind activation becomes a HARD precondition of the flag flip (S1, ORCHESTRATOR DECISION — both
halves are required, neither substitutes for the other).**
*Problem:* `geoip.py:49` defines `_BACKOFF_KEY = "geoip:backoff"` as one global key for every caller,
and ip-api's free tier is a single global 45/min budget. `demo.py:344-347` deliberately exempts the
canary from `_enforce_demo_budget`. Net effect: a rotating-IP flood on the public funnel (which
defeats the 40/min per-IP limiter by construction) drives ip-api to 429, and the 429 branch sets the
**global** backoff for up to the returned `X-Ttl` (≈300 s). During that window `resolve_geoip`
returns `("","")` for **every customer site's `/ingest`** — a public marketing page degrading paying
tenants' data. This is the single finding that blocks the flag flip.
*Decision, half (i) — MaxMind GeoLite2-City activation is a HARD precondition of setting
`location_reveal_enabled=true` in any real environment.* The local MaxMind path is already shipped
dormant; the operator steps are in `maxmind-and-feedback-ops_NOTE_11-08-26.md`. A local database has
no per-minute budget and no shared backoff, which removes the coupling at the root. "Scheduled" is
no longer sufficient (this supersedes the softer wording in Risk 6) — it must be **active** before
the flip.
*Decision, half (ii) — the canary path gets its own bounded aggregate geo budget and its own backoff
namespace, independent of half (i).* A Redis daily counter on a canary-scoped key
(`canary:geo:budget:{YYYY-MM-DD}`) caps total canary-originated geo lookups per day; a canary-scoped
backoff key (`canary:geoip:backoff`) means a canary-induced 429 can never set, read, or extend the
ingest path's `geoip:backoff`. On budget exhaustion, or while the canary backoff is set, the reveal
degrades gracefully down the **already-shipped** path: `geo_raw is None` → the existing text/skip
reveal with a `reason`, exactly as a provider-down response behaves today. No new user-visible state.
*Why both:* half (i) removes the shared dependency; half (ii) is the structural guarantee that holds
even if MaxMind is ever disabled, misconfigured, or falls through to the ip-api path. Shipping only
one leaves the ingest blast path reachable.
*Rejected:* applying `_enforce_demo_budget` to the canary — that is the identity-graph budget the
existing comment correctly protects; borrowing it would let a public funnel starve `/identify`.
*Rejected:* rate-limit tuning alone — a rotating-IP flood is precisely the case a per-IP limiter
cannot see (the same reasoning that produced the site-level ingest ceiling in P3).

**D8 — `identity_feedback` gets a 90-day purge mirroring the existing events purge (S2).**
*Rationale:* `apps/api/services/retention.py` already implements the pattern three times
(`purge_events_older_than`, `purge_agent_fetch_events_older_than`, `purge_request_logs_older_than`):
advisory lock, batched delete against a `make_interval(days => :days)` cutoff, dry-run branch, and a
`*_retention_purge_complete` log line. `identity_feedback` is the only table this plan's flag flip
puts on a public write path, and it has none of that. Extending the existing service is a fourth
copy of a proven shape — not new infrastructure.
*Critically:* the 12/min/IP limit is **NOT a real bound**. `client_ip_key_func` derives the key from
`CF-Connecting-IP`, which is caller-forgeable on a direct-to-origin request (see Risk 9). A caller
who rotates that header has no effective ceiling. The purge plus the `shown`/`note` caps are
therefore the *actual* defense; the rate limit is a speed bump. This must be stated plainly wherever
the rate limit is cited as a control.
*Rejected:* a migration-backed TTL or partitioning — this plan is zero-migration by construction and
a scheduled delete is sufficient at this volume.

**D9 — AC-10 gets a dedicated no-auth Playwright project, while retaining the existing API + web
web-server precondition (G8/F-3).**
*Rationale:* `apps/web/playwright.config.ts` declares exactly one non-setup project, carrying
`storageState: "e2e/.auth/user.json"` and `dependencies: ["setup"]`. A spec dropped into `e2e/`
inherits both, so the "logged-out public funnel" spec would run **authenticated** and against a
`setup` step that POSTs `/api/v1/auth/login` to `http://localhost:8000`. That is a false green: a
regression that walls `/onboarding` behind auth would still pass. The fix is a second project entry
with **no `storageState` and no `dependencies`**, `testMatch`-scoped to the static funnel spec only,
so the existing authenticated projects are untouched.
*Crucial configuration fact re-derived 11-08-26:* project dependencies control whether
`auth.setup.ts` and its saved auth state run, but they do **not** select entries in the top-level
`webServer` array. The checked-in config always starts the API on `:8000` and Next.js on `:3000`
for every Playwright invocation. The minimal safe direction is therefore **not** a conditional
`webServer` redesign: the `chromium-noauth` gate must truthfully require a bootable API on `:8000`
and the web server on `:3000`, while requiring **no seeded user, no saved `storageState`, and no
auth setup project**. This keeps the config change to project selection only and avoids changing
the shared test startup contract for the authenticated suite.
*Consequence:* `apps/web/playwright.config.ts` is now a Touchpoint and must be pre-authorised in
AC-13's diff review, or that review would flag the edit as unauthorised.
*Rejected:* per-test `test.use({ storageState: undefined })` — it does not remove the `setup`
dependency, so the gate would still require the auth setup and its seeded user even though the
top-level configuration would continue to start API :8000 for every project.

---

## Touchpoints

| File | Change | Why |
|---|---|---|
| `apps/api/routers/demo.py` | Add the shared `FINGERPRINT_MAX_LEN` bound to **all four** unauthed fingerprint-bearing bodies — `IdentifyBody` (`demo.py:47-49`, route `POST /api/v1/demo/identify` at `demo.py:112`), `CanaryPublicBody`, `CanaryFeedbackBody`, and the `/journey` body; add `shown` cap; add abuse counter log events | **F-1**, G1, G2, G4 |
| `apps/api/routers/onboarding.py` | Same fingerprint validator on `CanaryBody` (shared constant imported, not duplicated) | G1 defence in depth on the authed twin |
| `apps/api/services/onboarding_canary.py` | Home of the shared `FINGERPRINT_MAX_LEN` / `FINGERPRINT_RE` constants and `bounded_shown`; `fetch_journey` rejects over-long / bad-charset fp → `[]` (belt-and-braces; also covers `/demo/journey`) | G1, G2 |
| `apps/api/services/geoip.py` | **Was read-only; now modified.** Add an optional caller-scoped backoff-key + budget-key namespace so the canary path cannot set/read/extend the global `geoip:backoff` (`geoip.py:49`). Default namespace = today's behaviour, so `/ingest` is byte-identical | **G6 / D7(ii)** |
| `apps/api/services/onboarding_canary.py` (geo budget) | Canary-scoped daily geo budget counter (`canary:geo:budget:{date}`) + exhaustion → the existing `geo_raw is None` degrade path | **G6 / D7(ii)** |
| `apps/api/services/retention.py` | Add `purge_identity_feedback_older_than` mirroring `purge_events_older_than` (advisory lock, batched delete, dry-run branch, completion log) | **G7 / D8** |
| `apps/api/jobs/scheduler.py` | Import and call `purge_identity_feedback_older_than` from `_retention_purge_job`, isolated like the existing three retention calls | **G7 / D8** |
| `apps/api/config.py` (settings, not comment) | `identity_feedback_retention_days: int = 90`; immediately before `location_reveal_enabled`, `canary_geo_daily_budget: int = 0` plus a `@field_validator` accepting only `0..500` | G6, G7 |
| `apps/web/playwright.config.ts` | **New second project** — no `storageState`, no `dependencies`, `testMatch`-scoped to `static-onboarding-funnel.spec.ts` only. Existing authenticated projects untouched | **F-3 / G8 / D9** |
| `apps/api/main.py` | `IngestBodySizeLimitMiddleware._GUARDED_PATHS` becomes the exact set of `/api/v1/events/ingest` plus every unauthed fingerprint-bearing demo POST: `/api/v1/demo/identify`, `/api/v1/demo/journey`, `/api/v1/demo/canary`, `/api/v1/demo/identity-feedback`; preserve its running-byte counter for chunked bodies | G3 / AC-17 |
| `apps/web/public/beam/onboarding-steps.js` | Comment only: CSP note beside `LEAFLET_JS`/`TILE_URL`; clamp the fingerprint client-side to the same 64 chars so client and server agree | D6, G1 symmetry |
| `tests/unit/test_onboarding_canary_inputs.py` (new) | fp validator table, `shown` cap, counter emission, BaseSettings budget-default/ceiling assertion, and exact guarded-path-set assertion | G1, G2, G3, G4, G6 |
| `tests/integration/test_demo_canary_public.py` | Add: oversize body → 413; over-long fp → 422; oversize `shown` → 204 with `{}` stored | G1, G2, G3 |
| `tests/integration/test_retention_purge.py` | Extend the existing `patched_retention` fixture and retention-purge test pattern with an `IdentityFeedback` old/delete + fresh/survive + dry-run test | G7 / AC-16 |
| `apps/web/e2e/static-onboarding-funnel.spec.ts` (new) | 5-step static funnel legs | G5 |
| `apps/api/config.py` | Comment-only update to the `location_reveal_enabled` block: record the public surface + its rollout order | G5/rollout |

**Read-only for context (do not modify):** `apps/web/src/middleware.ts` (the US-only `geoRedirect`
in front of `/onboarding` — read it before writing any Leg-A assertion or any Phase 5 hand-test
instruction), `apps/api/services/graph_erasure.py`, `services/ip_resolution.py`,
`services/rate_limiter.py`, `models/identity_feedback.py`, `apps/web/public/beam/onboarding-app.js`,
`onboarding.html`, `onboarding-mascot.js`, `onboarding.css`, `next.config.mjs`.

## Public Contracts

| Contract | Before | After | Breaking? |
|---|---|---|---|
| `POST /api/v1/demo/canary` request | `{fingerprint?: str}` any length | `{fingerprint?: str}` ≤64 chars, `^[A-Za-z0-9_]*$` | **No** for real clients (real values are 20 chars). A malformed value that previously returned `{landed:false,...}` now returns 422. |
| `POST /api/v1/demo/canary` response | `{landed, pages, geo, network, reason?}` | unchanged | No |
| `POST /api/v1/demo/identity-feedback` | 204 always; `shown` any dict | 204 always; `shown` stored `{}` when >2 KB or >16 keys | No — status and client contract identical |
| `POST /api/v1/onboarding/canary` (authed) | as shipped | same fingerprint bound added | No — real values unaffected |
| Middleware 413 surface | `/api/v1/events/ingest` only | + all four unauthed fingerprint-bearing demo POST paths: `/identify`, `/journey`, `/canary`, `/identity-feedback`; the running byte counter rejects a chunked body above the shared cap before FastAPI parses/validates it | No — new rejection only above 256 KB |
| `POST /api/v1/demo/identify` (**unauthed, 6/min — F-1**) | `IdentifyBody.fingerprint: str \| None`, any length, fed straight into `select(Visitor.visitor_id, Visitor.ip_address).where(Visitor.fingerprint == body.fingerprint)` at `demo.py:139-147` | same shape, `≤ FINGERPRINT_MAX_LEN` (64) and `^[A-Za-z0-9_]*$`; over-long/bad-charset → 422 before the query | **No** for real clients (max real value is 32 chars). A malformed value that previously ran a DB query now 422s. |
| `POST /api/v1/demo/journey` (**unauthed — C-8 in the request / C-5 in the contract**) | unbounded fp → `[]` for a non-`fp2_` value | over-long / bad-charset fp → `[]`; **status and response shape unchanged**, silent by design (`fetch_journey`'s contract is "never raise") | No |
| Global geo backoff (`geoip:backoff`) | one key shared by `/ingest` and the public canary — a canary-induced ip-api 429 blinds ingest geo for every site for up to ~300 s | canary uses `canary:geoip:backoff` + a canary-scoped daily budget; `/ingest` keeps `geoip:backoff` unchanged | **No** — `/ingest` behaviour is byte-identical; the coupling is removed, not re-pointed |
| `Settings.canary_geo_daily_budget` | absent; a budget implementation would require an environment value at process boot or have no finite config ceiling | BaseSettings default is **0** (dormant-safe: all canary lookups degrade before provider I/O); a validator accepts only integers `0..500`; Phase 5 may set a non-zero value only after all flip preconditions are green | No — absent env is a valid boot configuration and leaves the dormant feature safely unable to spend the shared provider budget |
| `identity_feedback` rows | written unauthenticated, retained forever | retained `identity_feedback_retention_days` (90), purged by `retention.py` on the existing schedule | No — no read consumer depends on rows older than 90 d (`/identity-feedback/stats` aggregates current data) |
| `location_reveal_enabled` | gates authed + public canary | unchanged; **flipping it true now additionally requires MaxMind GeoLite2-City ACTIVE (D7 half i)** | No |

**Invariants that must still hold after this change** (each has a test):
- No `ip` / `site_id` / `visitor_id` / `fingerprint` key in any canary response body.
- The public journey is scoped to `settings.beam_self_site_id`; no `site_id` is accepted from input.
- Flag off → 404 on all four canary/feedback routes, and no provider call.
- The public canary never consumes `_enforce_demo_budget`.
- `resolve_geoip("8.8.8.8")` still returns exactly `("US", "California")` on the frozen signature.

## Blast Radius

| Dimension | Value |
|---|---|
| Files modified | 14 (8 backend source — `routers/demo.py`, `routers/onboarding.py`, `services/onboarding_canary.py`, `services/geoip.py`, `services/retention.py`, `jobs/scheduler.py`, `main.py`, `config.py`; 2 web files — static JS comment/clamp + `apps/web/playwright.config.ts`; 4 test files, including 2 new) |
| Files created | 2 (`tests/unit/test_onboarding_canary_inputs.py`, `apps/web/e2e/static-onboarding-funnel.spec.ts`) |
| Packages | `apps/api`, `apps/web` (static + e2e only) |
| Migrations | **none** |
| New dependencies | **none** |
| Risk class | **public unauthenticated API surface** + **trust-boundary/input validation** + **shared-resource exhaustion reaching a paying-tenant data path** (G6 — see the ingest-geo-degradation row below) + **data retention/GDPR** (G7). Not auth, not billing, not schema. |
| **Ingest-geo degradation (G6)** | The one path by which this public surface can affect **other tenants**: a canary-induced ip-api 429 currently sets the global `geoip:backoff`, and every customer site's `/ingest` then records empty `country_code`/`region` for the backoff window (~300 s). D7(ii) severs this; AC-14 proves the severance; Phase 1b must land **before** any flag flip. |
| Feature flag | `location_reveal_enabled`, default **False** — Phases 1–2 land entirely dormant |
| Rollback | flag → `False` (one env var, no redeploy of code needed if set via env) |
| NOT touched | `/api/v1/events/ingest` handler *behaviour* (its geo call keeps the default backoff namespace — byte-identical) · pixel `tracker.js` · React dashboard onboarding (`src/app/dashboard/onboarding/*`, `src/components/onboarding/*`, `src/lib/canary-*.ts`) · authed canary *behaviour* (only its input bound tightens) · `alembic` chain · `company_resolver` · `next.config.mjs` routing |

---

## Implementation Checklist

### Phase 1 — Input bounds (G1, G2)

1. In `apps/api/services/onboarding_canary.py`, add module constants
   `FINGERPRINT_MAX_LEN = 64` and `FINGERPRINT_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")` with a
   comment stating that a real fp2 value is **8–32 chars and variable-length** — `"fp2_"` + 4 ×
   `toString(36)` of a uint32, where base-36 of a uint32 is 1–7 chars, so the observed maximum is
   `4 + 4×7 = 32` (C-1: do **not** write "20 chars", that claim is false) — and that these constants
   are the single source of truth for **all four** unauthed fingerprint-bearing routes plus the
   authed twin.
2. In the same file, extend the guard at the top of `fetch_journey`: after the existing
   `startswith("fp2_")` check, also return `[]` when `len(fp) > FINGERPRINT_MAX_LEN` or
   `not FINGERPRINT_RE.match(fp)`. Keep it a silent `[]` — this path also serves `/demo/journey`,
   whose contract is "never raise".
3. In `apps/api/routers/demo.py`, change `CanaryPublicBody.fingerprint` to
   `str | None = Field(default=None, max_length=FINGERPRINT_MAX_LEN, pattern=r"^[A-Za-z0-9_]*$")`,
   importing the constant from the service. Keep the one-field-on-purpose docstring and extend it
   with the bound rationale.
4. In `apps/api/routers/onboarding.py`, apply the identical `Field(...)` to `CanaryBody.fingerprint`
   and to `IdentityFeedbackBody.fingerprint`. Import the same constant — do not re-type the literal.
5. In `apps/api/routers/demo.py`, apply the same bound to `CanaryFeedbackBody.fingerprint`.

5a. **(F-1 — required; this is the route the plan originally missed.)** In
    `apps/api/routers/demo.py`, apply the identical `Field(..., max_length=FINGERPRINT_MAX_LEN,
    pattern=r"^[A-Za-z0-9_]*$")` to `IdentifyBody.fingerprint` (`demo.py:47-49`). This is the
    unauthenticated `POST /api/v1/demo/identify` route (`demo.py:112`, 6/min), which at
    `demo.py:139-147` runs
    `select(Visitor.visitor_id, Visitor.ip_address).where(Visitor.fingerprint == body.fingerprint)`
    — the *exact* threat G1 exists to close, on a route that never touches `fetch_journey`, so
    step 2's defence-in-depth does not reach it. Import the same constant; do not re-type the
    literal. Without this step the vulnerability this plan exists to close is still live one route
    over after EXECUTE.

5b. Apply the same bound to the `/api/v1/demo/journey` request body's fingerprint field, so all
    four unauthed demo POSTs (`/identify`, `/journey`, `/canary`, `/identity-feedback`) carry an
    identical bound. `fetch_journey`'s silent-`[]` guard (step 2) stays as the second layer.
6. In `apps/api/services/onboarding_canary.py` (see the correction under step 8 — it lives in the
   service, not in a router), add module constants `SHOWN_MAX_BYTES = 2048`, `SHOWN_MAX_KEYS = 16`
   and a helper with this **exact signature (C-3 — do not improvise)**:

   ```
   bounded_shown(value) -> tuple[dict, bool]
   ```

   It returns `(value, False)` when `value` is a dict within both limits; `({}, True)` when the
   value is a dict that exceeded `SHOWN_MAX_KEYS` or whose `json.dumps(value, default=str)` exceeds
   `SHOWN_MAX_BYTES`; and `({}, False)` when the value is not a dict at all (including `None`) —
   because "the client sent nothing usable" is not a truncation event and must not be counted as
   abuse. The bool is the truncation flag step 10's counter needs; a bare `dict` return cannot
   distinguish "truncated", "absent", and "genuinely empty", which is exactly why the original
   signature could not satisfy step 10.
7. Call `shown, was_truncated = bounded_shown(body.shown)` in `demo_identity_feedback` in place of
   the current `body.shown if isinstance(body.shown, dict) else {}`; persist `shown`, and emit the
   step-10 counter when `was_truncated` is true.
8. Apply the same `bounded_shown` (same tuple unpacking, same counter) to
   `onboarding_identity_feedback` in `apps/api/routers/onboarding.py`.

   > Correction to steps 6–8: `bounded_shown` is defined in `services/onboarding_canary.py`
   > alongside the fingerprint constants. Both routers import from the service. No router imports
   > another router.

### Phase 1b — Canary geo budget + backoff namespace (G6 / D7 half ii) — **blocks the flag flip**

8a. In `apps/api/services/geoip.py`, parameterise the backoff key. Today `_BACKOFF_KEY =
    "geoip:backoff"` (`geoip.py:49`) is a single global key read and written by every caller. Add an
    optional caller namespace argument (default `""` → the existing literal key, so `/ingest` is
    byte-identical) that yields `canary:geoip:backoff` for the canary caller. **Both** the 429-write
    branch and the pre-call read branch must use the namespaced key — namespacing only the write
    would still let a canary flood be *blinded by* ingest's backoff, and namespacing only the read
    would leave the blast path open.

8b. In `apps/api/services/onboarding_canary.py`, add a bounded aggregate daily geo budget for the
    canary path: a Redis counter keyed `canary:geo:budget:{YYYY-MM-DD}` with a TTL past midnight,
    incremented once per canary-originated geo lookup, ceiling `settings.canary_geo_daily_budget`.
    This is deliberately an **aggregate** ceiling, not per-IP: the threat is a rotating-IP flood,
    which a per-IP limiter cannot see by construction (the same reasoning behind the P3 site-level
    ingest ceiling). Do **not** reuse `_enforce_demo_budget` — `demo.py:344-347` correctly protects
    the identity-graph budget from exactly this route.

8c. On budget exhaustion, or while `canary:geoip:backoff` is set, the canary geo lookup returns
    `None` and the handler takes the **already-shipped** `geo_raw is None` branch: the text/skip
    reveal with a `reason`, identical to a provider-down response. No new user-visible state, no new
    error path, no new copy. Degradation must be graceful and silent to the user.

8d. In `apps/api/config.py`, immediately before the existing `location_reveal_enabled` setting in
    the `# ─── Onboarding canary / location reveal ───` section, add
    `canary_geo_daily_budget: int = 0`. Add a class-level
    `@field_validator("canary_geo_daily_budget")` that accepts only integer values `0..500` and
    rejects negatives or values above **500** with `ValueError`. The default **0** is deliberate:
    it is dormant-safe, permits `Settings()` and production startup with no env var, and makes the
    canary degrade before provider I/O until an operator deliberately supplies a non-zero budget
    for the approved rollout. The comment must record that the public funnel shares ip-api's global
    45/min free-tier budget with `/ingest`, and without this ceiling a public flood can set the
    global backoff and blank `country_code`/`region` for every customer site for up to ~300 s.

    > **EXECUTE must not skip Phase 1b.** Phases 1, 2, 3, 4 are dormant behind the flag; Phase 1b is
    > the only agent-side work that is a *precondition of the flip*. If Phase 1b is not green,
    > Phase 5 does not start regardless of everything else being green.

### Phase 2 — Body-size guard + observability (G3, G4)

9. In `apps/api/main.py`, extend `IngestBodySizeLimitMiddleware._GUARDED_PATHS` to this exact set:
   `{"/api/v1/events/ingest", "/api/v1/demo/identify", "/api/v1/demo/journey",
   "/api/v1/demo/canary", "/api/v1/demo/identity-feedback"}`. **`/api/v1/demo/identify`
   is mandatory:** it is unauthenticated, fingerprint-bearing, and bypasses `fetch_journey`; without
   this entry its new schema bound still runs only after a chunked request is buffered. The existing
   running byte counter must remain the sole path for a missing, forged, or understating
   `Content-Length`: it must stop forwarding the body and synthesize 413 once accumulated bytes
   exceed `settings.ingest_body_max_bytes`, before FastAPI parsing or Pydantic validation. All four
   demo paths are guarded alongside `/ingest`. Also add a one-line comment recording that matching is **exact, not
   prefix** (`main.py:300` — `scope.get("path","") not in self._GUARDED_PATHS`), so a trailing-slash
   variant (`/api/v1/demo/canary/`) misses the guard and takes FastAPI's 307 instead; this is the
   same pre-existing property `/ingest` has, and the D2/D3 caps still bound the redirected retry. Update the
   class docstring's first line from "POST /ingest bodies" to name the guarded set generically, and
   add a comment recording that the shared 256 KB cap is a memory backstop, with the tight bounds
   living in the Pydantic schemas (D4).
10. In `apps/api/routers/demo.py` `demo_canary`, emit a structured counter on rejection paths:
    `logger.warning("public_canary_input_rejected", kind="fingerprint", ip=ip[:8])` is not reachable
    from the handler (Pydantic rejects first), so instead add an exception handler note — **do not**
    add one. Concretely: leave the 422 to FastAPI and count the *reachable* abuse signals only:
    - `logger.info("public_canary_no_geo", ip=ip[:8], reason=reason)` when `geo_raw is None`
      (distinguishes provider-down from flood-induced backoff).
    - `logger.warning("public_canary_shown_truncated", ip=ip[:8], keys=...)` in the caller, emitted
      **only when `bounded_shown`'s second tuple element is `True`** (C-3). A `({}, False)` return
      means "client sent nothing usable" and must not be counted as abuse.
    - `logger.warning("public_canary_geo_budget_exhausted", ...)` when the Phase 1b daily budget or
      the canary backoff short-circuits the lookup — no IP needed, this is an aggregate signal.
11. Add a rejected-request signal that *is* reachable: register a FastAPI
    `RequestValidationError` handler is out of scope (global surface). Instead, in
    `RequestResponseLogMiddleware`'s existing capture, verify 413/422/429 on the two canary paths
    are already recorded; if they are, add nothing and document that in the phase report. If they
    are not, add a single `logger.warning("public_canary_rejected", path=..., status=...)` inside
    the middleware guarded to the two paths only.

    > EXECUTE must read `RequestResponseLogMiddleware` first and choose one branch. Record which
    > branch was taken and why in the phase report. No PII: path + status + `ip[:8]` only.
12. In `apps/api/config.py`, extend the `location_reveal_enabled` comment block: name both the
    authed and the public surface it gates, state the rollout order (staging → prod), and record
    that rollback is this single flag.

### Phase 2b — `identity_feedback` retention purge (G7 / D8)

12a. In `apps/api/services/retention.py`, add `purge_identity_feedback_older_than(days=None, ...)`
     mirroring `purge_events_older_than` exactly: `settings.identity_feedback_retention_days`
     default, the shared `(now() AT TIME ZONE 'UTC') - make_interval(days => :days)` cutoff SQL, a
     table-exists guard, the advisory-lock acquire/release pattern, a dry-run branch that logs
     `identity_feedback_retention_purge_dry_run`, a batched delete loop, and a
     `identity_feedback_retention_purge_complete` completion log. Do not invent a new shape — copy
     the proven one.

12b. Add `identity_feedback_retention_days: int = 90` to `apps/api/config.py`, mirroring
     `event_retention_days` (raw events already auto-purge at 90 days per the repo's PII guardrail;
     this table stores a device fingerprint plus rendered location, so it belongs in the same class).

12c. Wire the new purge into the same scheduler entry point that already invokes
     `purge_events_older_than` / `purge_agent_fetch_events_older_than` / `purge_request_logs_older_than`.
     EXECUTE must read that entry point first and follow its existing registration shape.

12d. Extend the existing **integration** fixture and tests in
     `tests/integration/test_retention_purge.py` (there is no `tests/unit/test_retention.py`): use
     its `patched_retention` fixture, add an `IdentityFeedback` factory/count helper, and add
     `test_purges_old_identity_feedback_keeps_recent` plus the matching dry-run assertion. The test
     must seed one row older than 90 days and one fresh row, call
     `purge_identity_feedback_older_than(days=90)`, assert the old row is deleted and the fresh row
     survives, then assert dry-run reports without deleting. This remains a Hybrid gate because the
     existing fixture uses real PostgreSQL.

     > **Why this is not optional:** the 12/min/IP limiter on `/identity-feedback` is **not a real
     > bound** — its key comes from `CF-Connecting-IP`, which a direct-to-origin caller can forge
     > freely (Risk 9). The purge, plus the `shown` (2 KB / 16 keys) and `note` (500 chars) caps,
     > are the *actual* defenses. Any text citing the rate limit as the control is wrong.

### Phase 3 — Static-page comments + client clamp (D6, G1 symmetry)

13. In `apps/web/public/beam/onboarding-steps.js`, beside `LEAFLET_CSS`/`LEAFLET_JS`, add a comment:
    no CSP exists in `apps/web` today; a future CSP must allow `unpkg.com` in `script-src` +
    `style-src` and `*.tile.openstreetmap.org` in `img-src`, or this map silently degrades to the
    text reveal (which is the designed fallback, so it fails safe).
14. In the same file, clamp the generated fingerprint: `return ('fp2_' + _h128(...)).slice(0, 64);`
    with a comment that the server enforces the same 64-char / base-36 bound and a longer value
    would 422. (**C-1:** `_h128` output is **variable, 8–32 chars**, not "deterministic 20 chars" —
    base-36 of a uint32 is 1–7 chars, so the real maximum is `4 + 4×7 = 32`. Do not write "20" into
    this comment. The clamp is a guard against a future component change, not a live truncation.)

### Phase 4 — Tests (G1, G2, G3, G5)

15. New `tests/unit/test_onboarding_canary_inputs.py`:
    - Table-driven `FINGERPRINT_RE` cases: valid `fp2_abc123`, valid `fp3_...`, reject 65 chars,
      reject `fp2_a'b`, reject `fp2_<script>`, reject empty, reject whitespace.
    - `fetch_journey` returns `[]` for an over-long fp **without constructing a DB query** (assert
      via a session double whose `execute` raises `AssertionError`).
    - `bounded_shown` (tuple contract, C-3): `(payload, False)` for the real 7-key payload;
      `({}, True)` for 17 keys; `({}, True)` for a 3 KB string value; `({}, False)` for a list;
      `({}, False)` for `None`.
    - **F-1:** `IdentifyBody` rejects a 65-char fingerprint and a `fp2_a'b` value at the schema
      layer, and the constant it uses is imported from `services/onboarding_canary.py` (assert
      identity with `FINGERPRINT_MAX_LEN`, not a re-typed literal).
    - **G6:** the canary geo path uses `canary:geoip:backoff` and the ingest path uses
      `geoip:backoff` — assert the two key names are distinct and that the default namespace
      produces the exact pre-existing literal (proves `/ingest` is byte-identical).
    - **G6:** with the canary daily budget exhausted, the canary geo lookup returns `None` and
      **no** provider call is made; the global `geoip:backoff` key is never written by the canary
      path even when the canary provider call 429s.
    - **G6 configuration:** `Settings()` succeeds without `CANARY_GEO_DAILY_BUDGET` and yields
      `canary_geo_daily_budget == 0`; a supplied `501` or `-1` is rejected, proving the
      explicit finite `0..500` ceiling and the non-boot-required dormant default.
    - **G3 guard-set:** `IngestBodySizeLimitMiddleware._GUARDED_PATHS` equals the five-path set in
      step 9, including `/api/v1/demo/identify`.
16. Extend `tests/integration/test_demo_canary_public.py`:
    - `test_oversize_chunked_demo_bodies_are_rejected_before_parsing` — directly exercise the ASGI
      middleware with multiple `http.request` frames (`more_body=True` until the final frame) for
      each of `/api/v1/demo/identify`, `/api/v1/demo/journey`, `/api/v1/demo/canary`, and
      `/api/v1/demo/identity-feedback`. For every route, accumulated bytes above 256 KB must yield
      413 before the downstream app is called. This is the proof that the guarded-path set prevents
      unbounded chunked buffering **before** Pydantic validation; one normal httpx POST is not
      sufficient to cover the chunked counter.
    - `test_overlong_fingerprint_is_422` — 65-char fp → 422, body contains no echoed fingerprint.
    - `test_oversize_shown_is_stored_empty` — feedback with a 3 KB `shown` → 204, and the persisted
      row's `shown == {}` while `reasons` survived intact.
    - Re-assert the existing invariants still pass unchanged (no new assertions needed — they are
      the regression net).
16a. **(F-3 / D9 — do this BEFORE writing the spec, or the gate produces a false green.)** In
     `apps/web/playwright.config.ts`, add a second project alongside the existing `chromium` one:

     - name: `chromium-noauth`
     - `use`: `{ ...devices["Desktop Chrome"] }` — **no `storageState`**
     - **no `dependencies`** (so `e2e/auth.setup.ts` does not run)
     - `testMatch: /static-onboarding-funnel\.spec\.ts/`

     and add `testIgnore` for that same file on the existing authenticated `chromium` project so the
     spec runs exactly once, logged out. Leave every other property of the existing project alone.
     Without this, the new spec inherits `storageState: "e2e/.auth/user.json"` **and**
     `dependencies: ["setup"]`, so it (a) requires the API on :8000 plus a seeded
     `demo@getbeam.fyi` / `password123` user and a working auth DB just to start, and (b) runs
     **authenticated** — meaning a regression that walls `/onboarding` behind auth would still pass.
     `apps/web/playwright.config.ts` is a declared Touchpoint precisely so AC-13's diff review does
     not flag this edit as unauthorised. This project split does **not** suppress the file's global
     `webServer` array: its command remains API `:8000` + web `:3000`; it removes only the seeded
     user/auth-setup requirement.

17. New `apps/web/e2e/static-onboarding-funnel.spec.ts` (D5), run under the `chromium-noauth`
    project — **preconditions are the checked-in global Playwright `webServer` API on `:8000` and
    `apps/web` on `:3000`**. It needs no seeded user, saved auth state, or `auth.setup.ts`; the
    API server remains required solely because `playwright.config.ts` starts it for every project:
    - `page.route('**/api/v1/demo/canary', ...)` answering OPTIONS with CORS headers then POST with
      a LANDED fixture; `page.route('**/unpkg.com/leaflet**')` and
      `page.route('**/tile.openstreetmap.org/**')` → the 1×1 PNG / a stub.
    - Leg A: `goto('/onboarding')` → welcome bubble renders, progress shows **5** dots.
      **Scope boundary (C-7 in the supplement request / C-4 in the contract):**
      `apps/web/src/middleware.ts` `geoRedirect` 302s `/onboarding` → `/login` whenever
      `x-vercel-ip-country` is present and `!== "US"`. Locally that header is absent, so Leg A
      passes — but this leg proves nothing about non-US visitors, and no Playwright leg can. State
      that limit in the spec header comment.
    - Leg B: click "go on then" → "catch me" step; stub `window.open` via `addInitScript`, assert it
      was called with `https://getbeam.fyi/?beam=canary`.
    - Leg C: landed-on-2nd-poll → reveal shows the city and the page list; `#ob-map` exists.
    - Leg D: endpoint 404s (flag-off simulation) → after the 3-error break, the honest
      "couldn't catch you" copy appears and **no `#ob-map` node exists**.
    - Leg E: "not quite" → `waitForRequest` on `/api/v1/demo/identity-feedback` asserts the checked
      reasons are in the POST body.
    - Leg F: `account` step CTA navigates to `/sign-up`.
    - Leg G: `emulateMedia({ reducedMotion: 'reduce' })` → lines render immediately.
18. Run the full regression set (see Test Procedure).

### Phase 5 — Rollout (G5 operator half)

**Hard preconditions of the flip (all five must hold before step 20; none is a soft recommendation):**

- **P-a — MaxMind GeoLite2-City is ACTIVE** (D7 half i). Not "scheduled" — active. Operator steps:
  `process/features/onboarding-canary/active/canary-onboarding_10-08-26/maxmind-and-feedback-ops_NOTE_11-08-26.md`. This
  removes the shared ip-api budget at the root. Supersedes the softer wording in Risk 6.
- **P-b — Phase 1b is green** (D7 half ii): canary-scoped geo budget + `canary:geoip:backoff`
  namespace shipped and proven by AC-14. P-a and P-b are independent; neither substitutes for the
  other.
- **P-c — `REQUEST_LOG_ENABLED=true` in the soak environment (C-2).** The 413/422/429 half of AC-11
  is recorded **only** by `RequestResponseLogMiddleware` → `request_logger.should_log`, which returns
  `None` when `settings.request_log_enabled` is False (`config.py:1234`, **default False**).
  `classify` does map those statuses (429 → `rate_limited`, 413/422 → `http_error`) and neither
  `request_log_exclude_paths` nor `request_log_ignore_statuses` excludes the canary paths — so the
  counters exist but are switched off by default. Enable the flag for the soak; leave
  `request_log_exclude_paths` unchanged. **This is the chosen resolution of step 11 — take the
  "add nothing, enable the existing logger" branch, not the `logger.warning` branch.** Record the
  choice in the phase report as step 11 requires.
- **P-d — the `identity_feedback` GDPR-erasure gap has an owned follow-up plan** (see the Known-gaps
  table and `process/features/onboarding-canary/backlog/identity-feedback-gdpr-erasure_NOTE_11-08-26.md`, marked **NEW PLAN REQUIRED**).
  Phase 2b adds retention (age-based deletion); it does **not** add per-subject erasure. The flip is
  what puts this table on a public write path at scale.
- **P-e — `CANARY_GEO_DAILY_BUDGET` is explicitly set to a non-zero value in the inclusive
  `1..500` range.** Its code default remains 0 so an absent environment variable cannot stop API
  boot or accidentally consume provider quota; an operator must make the bounded spend decision
  only after P-a through P-d are green.

19. Deploy Phases 1–4 (and 1b, 2b) with `location_reveal_enabled` **False**. Confirm zero behaviour
    change: `/onboarding` still reaches the honest no-catch branch; `/ingest`
    `country_code`/`region` unchanged over a full 24 h geo cache cycle.
20. Confirm P-a…P-e, then enable in **staging** only. Hand-verify the reveal on a residential
    connection, a corporate VPN, and a mobile/CGNAT connection.
    - **Expect a redirect, not a bug, from any non-US tester** (C-7 in the request / C-4 in the
      contract): `apps/web/src/middleware.ts` `geoRedirect` sends `/onboarding` → `/login` whenever
      `x-vercel-ip-country` is present and `!== "US"`. A VPN exiting outside the US will therefore
      never reach the funnel. Test the funnel itself from US exits only; test the redirect
      deliberately from one non-US exit.
    - **Verify the limiter BUCKET, not just the pin (S3).** Parent risk 2 is usually framed as "does
      the pin land in a CF datacenter" — that is necessary but not sufficient. Also confirm that two
      requests from two genuinely different client IPs land in **two different rate-limit buckets**.
      If `CF-Connecting-IP` is absent (colo-collapse mode), `client_ip_key_func` falls back to the
      peer address, which is the Cloudflare edge IP — so every visitor behind one colo shares one
      40/min bucket and the funnel self-throttles under normal traffic. Symptom to look for: 429s at
      a request rate far below 40/min.
    - **Confirm whether the Railway origin is reachable off-CF during the soak.** If it is,
      `CF-Connecting-IP` is caller-forgeable end-to-end (`ip_resolution.py:54-63` trusts the header
      unconditionally when `ingest_trust_cf_connecting_ip` is on, with no check that the peer is a
      CF edge), which means the per-IP limiter on both public POSTs can be bypassed at will. Record
      the answer in the phase report either way — this is the same defect class as the already-
      backlogged ingest forge-risk.
21. Watch the counters for one staging soak day: `public_canary_no_geo` rate,
    `public_canary_shown_truncated` count, `public_canary_geo_budget_exhausted` count, and the
    413/422/429 counts on the three guarded demo paths (requires P-c).
22. Enable in prod. Re-check the same counters at 1 h and 24 h, **plus the ingest-geo health check**:
    `/ingest` `country_code`/`region` fill rate must be unchanged from the pre-flip baseline. A drop
    there is the G6 blast signature and is an immediate rollback trigger. **Rollback = set
    `LOCATION_REVEAL_ENABLED=false`.** No migration to unwind, no code revert.

---

## Acceptance Criteria

| ID | Criterion | proven by | strategy |
|---|---|---|---|
| AC-1 | A fingerprint longer than 64 chars or outside `[A-Za-z0-9_]` is rejected with 422 on both public and authed canary routes, before any DB or provider call | `test_overlong_fingerprint_is_422` + `test_fetch_journey_rejects_before_query` | Fully-Automated |
| AC-2 | `fetch_journey` returns `[]` for a bad-charset/over-long fingerprint without constructing a query | `test_fetch_journey_rejects_before_query` | Fully-Automated |
| AC-3 | A `shown` payload over 2 KB or 16 keys is stored as `{}` while `reasons` are preserved, and the route still returns 204 | `test_oversize_shown_is_stored_empty` | Hybrid (needs Postgres) |
| AC-4 | A >256 KB body delivered in chunks to each guarded unauthed demo route is rejected 413 before the downstream handler, FastAPI parser, or Pydantic validation runs | `test_oversize_chunked_demo_bodies_are_rejected_before_parsing` | Hybrid (ASGI app fixture) |
| AC-5 | `MOCK_EXTERNAL_APIS=true` yields deterministic geo and zero outbound HTTP on the public route | existing `test_geoip.py` mock-mode case + new `test_public_canary_mock_mode_no_http` | Fully-Automated |
| AC-6 | Flag off → 404 on all four routes, no provider call (unchanged) | existing `test_flag_off_returns_404_and_calls_no_provider` | Fully-Automated |
| AC-7 | Response body still contains no `ip`/`site_id`/`visitor_id`/`fingerprint` (unchanged) | existing `test_response_never_leaks_identifiers` | Fully-Automated |
| AC-8 | The public journey remains hard-pinned to `beam_self_site_id`; no site enumeration (unchanged) | existing `test_journey_is_scoped_to_beam_site` + `test_body_supplied_ip_is_ignored` | Fully-Automated |
| AC-9 | Per-IP rate limit still trips at the documented ceiling and keys on `resolve_client_ip` (unchanged) | existing `test_rate_limit_trips` + `test_x_forwarded_for_is_not_trusted` | Fully-Automated |
| AC-10 | The static funnel at `/onboarding` renders 5 progress dots, opens the right canary URL, reveals on a landed poll, degrades honestly with no map node when the endpoint 404s, posts feedback reasons, and CTAs to `/sign-up` | `static-onboarding-funnel.spec.ts` legs A–G, run under the new **`chromium-noauth`** project | Hybrid — **precondition: the existing global Playwright API server on :8000 and `apps/web` on :3000.** No seeded `demo@getbeam.fyi` user, saved storage state, or auth setup is required for this project. **Scope boundary:** proves US-visitor behaviour only; `middleware.ts` `geoRedirect` sends non-US visitors to `/login` and no Playwright leg covers that. |
| AC-11 | An abuse event (oversize `shown`, 413/422/429 on the canary paths) is visible in structlog with no PII beyond `ip[:8]` | `test_shown_truncation_is_counted` + manual log read during staging soak | Hybrid |
| AC-12 | `resolve_geoip("8.8.8.8")` still returns exactly `("US","California")` and `/ingest` is byte-identical | existing `test_geoip.py` backward-compat case + `tests/integration/test_events_ingest.py` green | Fully-Automated |
| AC-13 | Zero migrations, zero new deps, zero React/dashboard file changes in the diff; the unit regression gate `.venv/bin/python3.11 -m pytest tests/unit -m unit` shows **1750 passed / 2 skipped + N new** | `git diff --stat` review at EVL (`apps/web/playwright.config.ts` and `apps/api/services/{geoip,retention}.py` are **pre-authorised** Touchpoints); `alembic heads` still `f4b9d2a71c68` | Agent-Probe |
| AC-14 | A canary-originated ip-api 429 **never** writes or extends the global `geoip:backoff`; `/ingest` geo resolution is unaffected by any canary traffic volume; canary budget exhaustion degrades to the existing text/skip reveal with no new user-visible state | `test_canary_backoff_is_namespaced` + `test_canary_budget_exhaustion_degrades_gracefully` + `test_ingest_geo_key_is_unchanged` | Fully-Automated |
| AC-15 | `/api/v1/demo/identify` rejects an over-long / bad-charset fingerprint with 422 **before** its `Visitor.fingerprint ==` query runs, using the shared `FINGERPRINT_MAX_LEN` constant | `test_identify_rejects_overlong_fingerprint` (unit, schema layer) + integration 422 assertion | Fully-Automated |
| AC-16 | `identity_feedback` rows older than `identity_feedback_retention_days` (90) are deleted by `purge_identity_feedback_older_than`; fresher rows survive; the purge holds the advisory lock and logs completion | `tests/integration/test_retention_purge.py::TestIdentityFeedbackRetentionPurge` old/delete + fresh/survive + dry-run cases | Hybrid (Postgres) |
| AC-17 | All **four** unauthed demo POSTs (`/identify`, `/journey`, `/canary`, `/identity-feedback`) carry the identical fingerprint bound, and **all four**, plus `/ingest`, are inside `_GUARDED_PATHS`; fragmented bodies over the cap never reach parsing/validation | `test_all_demo_fingerprint_bodies_share_bound` + `test_guarded_paths_set_covers_all_public_demo_posts` + `test_oversize_chunked_demo_bodies_are_rejected_before_parsing` | Hybrid |
| AC-18 | `Settings()` boots with no `CANARY_GEO_DAILY_BUDGET` env var and defaults to 0; only the finite inclusive `0..500` range is accepted | `test_canary_geo_daily_budget_default_and_ceiling` | Fully-Automated |

## Phase Completion Rules

- A phase is **CODE DONE** when its checklist items are implemented and the phase's own test gates
  are green.
- A phase is **✅ VERIFIED** only when CODE DONE **and** the regression set (Test Procedure below)
  is green **and** the outcome is user-confirmed (User Confirmation is required — an agent may never self-confirm a VERIFIED status). Phase 5 additionally requires the staging
  soak evidence; it cannot be marked VERIFIED from agent-side work alone.
- Phase 5 is operator-gated by construction: an agent may not flip `location_reveal_enabled` in any
  real environment. That flip is a human action.
- No phase may mark itself VERIFIED on Known-Gap coverage alone. Any behaviour whose only gate is a
  known gap keeps the phase **CONDITIONAL** and requires a backlog stub.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `.venv/bin/python3.11 -m pytest tests/unit/test_onboarding_canary_inputs.py -q` | Fully-Automated | AC-1, AC-2, AC-11 |
| `.venv/bin/python3.11 -m pytest tests/unit/test_geoip.py tests/unit/test_geoip_city.py -q` | Fully-Automated | AC-5, AC-12 |
| `.venv/bin/python3.11 -m pytest tests/unit -m unit` (AC-13 regression gate; baseline **1750 passed / 2 skipped**, +N new) | Fully-Automated | AC-13 (no regression) |
| `.venv/bin/python3.11 -m pytest tests/unit` (full collection, informational; baseline **2683 passed / 2 skipped**) | Fully-Automated | AC-13 (cross-check only — not the pinned gate) |
| `.venv/bin/python3.11 -m pytest tests/integration/test_demo_canary_public.py -q` — precondition: Postgres `localhost:5433` + Redis reachable | Hybrid | AC-3, AC-4, AC-6, AC-7, AC-8, AC-9 |
| `.venv/bin/python3.11 -m pytest tests/integration/test_onboarding_canary_api.py -q` — same precondition | Hybrid | AC-6, AC-7 (authed twin unchanged) |
| `.venv/bin/python3.11 -m pytest tests/integration/test_events_ingest.py -q` — same precondition | Hybrid | AC-12 (ingest byte-identical) |
| `cd apps/web && npx playwright test --project=chromium-noauth e2e/static-onboarding-funnel.spec.ts` — precondition: the checked-in global Playwright web servers start API `:8000` and web `:3000`; no seeded user, saved storage state, or auth setup | Hybrid | AC-10 |
| `.venv/bin/python3.11 -m pytest tests/unit/test_onboarding_canary_inputs.py -k "backoff or budget or identify or guarded" -q` | Fully-Automated | AC-14, AC-15, AC-18 |
| `.venv/bin/python3.11 -m pytest tests/integration/test_demo_canary_public.py -q` — includes the fragmented-body guard scenario; precondition: Postgres `localhost:5433` + Redis `:6379` | Hybrid | AC-4, AC-17 |
| `.venv/bin/python3.11 -m pytest tests/integration/test_retention_purge.py -q` — precondition: Postgres `localhost:5433` + Redis `:6379` | Hybrid | AC-16 |
| Staging: two requests from two distinct real client IPs land in two distinct rate-limit buckets (not one CF-edge bucket); and a documented answer to "is the Railway origin reachable off-CF?" | Agent-Probe (operator) | AC-11, S3 (CF-Connecting-IP forgeability + colo collapse) |
| Prod post-flip: `/ingest` `country_code`/`region` fill rate unchanged vs the pre-flip baseline at 1 h and 24 h | Agent-Probe (operator) | AC-14 in production (the G6 blast signature) |
| `npx playwright test e2e/onboarding.spec.ts e2e/onboarding-canary.spec.ts` in `apps/web` | Hybrid | AC-13 (dashboard onboarding untouched; AC-9 cross-tenant-disclosure regression) |
| `git diff --stat` review: no file under `apps/api/migrations/`, `apps/web/src/`, `apps/pixel/`; `alembic -c apps/api/alembic.ini heads` still `f4b9d2a71c68` | Agent-Probe | AC-13 |
| Staging soak: flip flag, exercise from residential + VPN + CGNAT, read `public_canary_no_geo` / `public_canary_shown_truncated` / 413-422-429 counts, compare returned city vs known network | Agent-Probe (operator) | AC-10, AC-11, parent risk 2 |
| `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs <this plan>` | Fully-Automated | plan artifact structure |

**Known gaps carried (each keeps its gate CONDITIONAL, each has a backlog stub in Phase 5's report):**

| Gap | Why untestable here | Resolution |
|---|---|---|
| Real end-to-end catch (live pixel hit on getbeam.fyi joining to a fingerprint from a second tab) | No CI runner can produce it; needs the real pixel, real DB, and one browser identity across two origins-in-one-app tabs | Backlog: manual QA checklist in the Phase 5 report. Options: (A) write it as a `needs-live` Playwright project — ~2 h, still non-deterministic; (B) build a seeded-visitor fixture harness — ~4 h, proves the join but not the pixel; (C) accept as known-gap with a documented manual pass; (D) backlog artifact. **Chosen: C + D.** |
| Safari canvas-randomization effect on the fp2 join | Needs a real Safari and a real cross-tab run | Backlog note; parent risk 4 already records that the timeout branch is the Safari experience and must not look like a bug |
| Prod CF client-IP correctness (`resolve_client_ip` vs CF edge) | Only observable against the real CF-proxied origin | Phase 5 staging/prod check (AC-11 probe); parent risk 2 |
| ip-api terms + 45/min ceiling on a now user-facing path | Legal/ops question, not a test | **Upgraded from "mitigated" to a HARD precondition (D7 half i):** MaxMind GeoLite2-City must be **ACTIVE** before the flip, per `maxmind-and-feedback-ops_NOTE_11-08-26.md`. Phase 1b (half ii) is the structural guarantee that holds even if MaxMind is later disabled. |
| **`CF-Connecting-IP` is trusted unconditionally (S3)** | `ip_resolution.py:54-63` returns the header value as the client IP whenever `ingest_trust_cf_connecting_ip` is on, with **no check that the peer is a Cloudflare edge**. If the Railway origin is reachable off-CF, any caller can forge the header and choose their own rate-limit bucket — defeating the 40/min canary limiter and the 12/min feedback limiter at will. Same defect class as the already-backlogged ingest forge-risk. Not testable here: it depends on live network reachability. | Known-gap: documented. Phase 5 step 20 must record whether the origin is off-CF reachable. Backlog stub: `process/features/onboarding-canary/backlog/cf-connecting-ip-forgeability-canary_NOTE_11-08-26.md`. Keeps AC-9's gate **CONDITIONAL** — the per-IP limit is a speed bump, not a bound. |
| **Colo-collapse mode (S3)** | When `CF-Connecting-IP` is **absent**, `client_ip_key_func` falls back to the peer address = the Cloudflare edge IP. Every visitor behind one colo then shares a single 40/min bucket and the public funnel self-throttles under ordinary traffic. Only observable against the real CF-proxied origin. | Known-gap: documented. Phase 5 step 20 verifies the **bucket**, not just the pin. Symptom: 429s far below 40/min. Same backlog stub as above. |
| **`identity_feedback` is outside the GDPR erasure sweep (C-10 in the request / C-7 in the contract)** | `apps/api/services/graph_erasure.py` imports `BeamIdentityNode`, `IdentitySignal`, `SuppressionEntry`, `IdentifiedVisitor`, `Visitor`, `VisitorEmail` — **not** `IdentityFeedback`. That table stores a device fingerprint (`String(100)`) plus rendered city/region/org and a rounded lat-lng, written unauthenticated. Phase 2b adds **age-based retention**, which is not the same thing as **per-subject erasure**. Pre-existing, but this plan's flag flip is what opens the tap. | Known-gap: documented, **NEW PLAN REQUIRED**. Backlog stub: `process/features/onboarding-canary/backlog/identity-feedback-gdpr-erasure_NOTE_11-08-26.md`. This is Phase 5 precondition **P-d** — the follow-up plan must exist and be owned before the flip. Keeps Phase 5's gate **CONDITIONAL**. |

## Test Infra Improvement Notes

- The static funnel at `/onboarding` had **zero** browser coverage before this plan; the Playwright
  suite targeted only `/dashboard/onboarding`. Adding `static-onboarding-funnel.spec.ts` is itself
  the infra improvement — it establishes the pattern (CORS-answering `page.route` + stubbed
  unpkg/OSM) for any future work on the public logged-out surface.
- The integration lane requires Docker, and Docker on this machine IS running — the CLI is simply
  off `PATH` at `/Applications/Docker.app/Contents/Resources/bin/docker`. Detect via
  `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`, not `which docker`. Any agent that marks a
  hybrid gate "environment-blocked" on this repo is very likely acting on that false premise.
- **Playwright project split (F-3).** The suite had exactly one non-setup project, and it carried
  `storageState` + a `setup` dependency — so there was **no way to write a logged-out browser test**
  without a config change. Adding `chromium-noauth` is the reusable infra improvement: any future
  public/logged-out surface can run without inheriting an auth session or triggering a seeded-user
  setup. The checked-in global `webServer` array still starts API :8000 and web :3000 for every
  project; public-only test startup is not part of this minimal safe change.
- **Baseline reporting discipline (F-2).** `pytest tests/unit -m unit` (1750) and `pytest tests/unit`
  (2683) differ by 933 deselected tests. Quoting either number without its command has already cost
  one PVL cycle. Any future plan touching this repo should state command + number together.
- **Never export the repo `.env` `DATABASE_URL` for a test or alembic run** — it points at Supabase
  **production**. Pin `DATABASE_URL=postgresql://.../@localhost:5433/...` in the command
  environment first.

---

## Test Procedure (regression set)

Run in this order. Stop and fix at the first red.

```bash
# 1. Unit lane (no external deps). AC-13's PINNED gate is the -m unit variant.
.venv/bin/python3.11 -m pytest tests/unit -m unit    # baseline 1750 passed / 2 skipped (+N new)
.venv/bin/python3.11 -m pytest tests/unit            # full collection, informational: 2683 / 2

# 2. Integration — precondition: Postgres :5433 + Redis up; DATABASE_URL pinned to localhost
lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'
.venv/bin/python3.11 -m pytest tests/integration/test_demo_canary_public.py \
  tests/integration/test_onboarding_canary_api.py \
  tests/integration/test_events_ingest.py \
  tests/integration/test_retention_purge.py -q

# 3. Browser — precondition: Playwright's checked-in global webServer array starts API :8000
# and apps/web :3000. chromium-noauth skips only auth.setup/storageState; it does not skip API startup.
cd apps/web && npx playwright test --project=chromium-noauth e2e/static-onboarding-funnel.spec.ts
# the two dashboard specs stay on the authenticated project (API :8000 + seeded user required):
cd apps/web && npx playwright test e2e/onboarding.spec.ts e2e/onboarding-canary.spec.ts

# 4. Diff discipline
git diff --stat
alembic -c apps/api/alembic.ini heads     # must still be f4b9d2a71c68
```

Deeper routing for runners, fixtures, and debugging gotchas:
`process/context/tests/all-tests.md`. Repo architecture, guardrails, and feature inventory:
`process/context/all-context.md`.

---

## Risks

1. **The premise risk — re-building shipped code.** The highest-consequence failure of this plan is
   an EXECUTE agent reading the parent plan's follow-up sentence and re-truncating a funnel that is
   already truncated, or writing a second public endpoint. Mitigation: the audit table above, the
   explicit Non-Goals, and AC-13's diff review.
2. **Tightening an input bound on a live route.** If any real client sends a fingerprint outside
   `[A-Za-z0-9_]` or over 64 chars, it now gets 422 where it previously got a soft `{landed:false}`.
   Mitigation: the only clients are `onboarding-steps.js` (20-char output, now clamped) and the
   React `beam-fingerprint.ts` (same algorithm). Verify both before merging; the clamp in step 14
   makes the client's contract explicit.
3. **Shared 256 KB body cap.** `ingest_body_max_bytes` now governs four public demo routes as well
   as `/ingest`. Lowering it for
   ingest tuning would silently tighten the canary too. Mitigation: the comment in step 9 records
   the coupling; the D2/D3 caps are the real bound so a cap change cannot break the canary in
   practice.
4. **Parent risk 2 (CF client-IP) is unresolved and this plan does not resolve it.** It becomes
   observable only at Phase 5 staging. If pins land in a CF datacenter, the correct response is to
   leave the flag off and open a follow-up on `trusted_proxy_hops` /
   `ingest_trust_cf_connecting_ip`, not to ship.
5. **Public write path — and the rate limit is NOT the control (S2).** `demo_identity_feedback`
   remains an unauthenticated DB insert with a 500-char note. This plan bounds `shown` but does not
   remove the write. **Do not cite the 12/min/IP limit as the bound:** its key comes from
   `CF-Connecting-IP`, which a direct-to-origin caller can forge freely
   (`ip_resolution.py:54-63`, Risk 9), so a determined caller has no effective ceiling. The **actual**
   defenses are (a) the Phase 2b 90-day retention purge, (b) the `shown` 2 KB / 16-key cap, and
   (c) the 500-char `note` cap. The rate limit is a speed bump against unsophisticated traffic only.
   If abuse appears in the soak counters, the follow-up is an aggregate (not per-IP) daily ceiling.
6. **Parent risk 6 (ip-api terms) — upgraded from "at least scheduled" to a HARD precondition.**
   Flipping the flag widens a user-facing dependency on a service whose free tier restricts
   commercial use *and* whose 45/min global budget is shared with `/ingest` (Risk 8). MaxMind
   GeoLite2-City must be **ACTIVE**, not scheduled, before the flip — Phase 5 precondition P-a,
   operator steps in `maxmind-and-feedback-ops_NOTE_11-08-26.md`. This supersedes the softer earlier
   wording wherever it still appears.
7. **Parent risk 3 (adblockers).** Beam's audience is technical; a large share of the public funnel
   will hit the honest no-catch branch. That branch is already implemented and tested (Leg D), so
   this is a conversion risk, not a correctness risk — measure it in the soak.

8. **Ingest-geo degradation from a public flood (S1 / G6) — the highest-severity finding in this
   supplement, and the one that blocks the flag flip.** The public canary geo lookup shares ip-api's
   global 45/min budget **and** the single global `geoip:backoff` Redis key (`geoip.py:49`) with the
   `/ingest` hot path, and is deliberately exempt from `_enforce_demo_budget` (`demo.py:344-347`).
   A rotating-IP flood defeats the 40/min per-IP limiter by construction, drives ip-api to 429, and
   the 429 branch sets the **global** backoff for up to the returned `X-Ttl` (≈300 s). For that
   window `resolve_geoip` returns `("","")` for **every customer site's `/ingest`** — a public
   marketing funnel silently degrading paying tenants' data. Mitigations are both halves of D7:
   (i) MaxMind ACTIVE (removes the shared dependency) and (ii) Phase 1b's canary-scoped budget +
   `canary:geoip:backoff` namespace (the structural guarantee that survives MaxMind being disabled).
   AC-14 proves the severance; step 22's ingest fill-rate check is the production tripwire.
9. **`CF-Connecting-IP` is caller-forgeable when the origin is reachable off-CF (S3).**
   `ip_resolution.py:54-63` trusts the header unconditionally when `ingest_trust_cf_connecting_ip`
   is on, with no verification that the peer is a Cloudflare edge. If the Railway origin answers
   direct requests, every per-IP control on the two public POSTs — and on `/ingest` — is
   caller-selected. This is the same defect class as the already-backlogged ingest forge-risk and is
   not created by this plan, but this plan is what puts a public unauthenticated funnel on top of it.
   Phase 5 step 20 must record whether the origin is off-CF reachable.
10. **Colo-collapse (S3).** In the opposite failure — header **absent** — `client_ip_key_func` keys
    on the CF edge IP, so every visitor behind one Cloudflare colo shares a single 40/min bucket and
    the funnel self-throttles under ordinary traffic. Symptom: 429s far below 40/min. Phase 5 step 20
    verifies the limiter **bucket**, not merely that the pin is not a datacenter.
11. **Non-US visitors never see the funnel (C-7 in the request / C-4 in the contract).**
    `apps/web/src/middleware.ts` `geoRedirect` 302s `/onboarding` → `/login` whenever
    `x-vercel-ip-country` is present and `!== "US"`. This is a pre-existing product decision, not a
    defect, but it bounds AC-10's claim and will read as "the funnel is broken" to any non-US
    hand-tester in Phase 5 unless step 20's instruction is followed.

---

## Resume and Execution Handoff

1. **Selected plan file path:**
   `process/features/onboarding-canary/active/public-canary-funnel_11-08-26/public-canary-funnel_PLAN_11-08-26.md`
2. **Last completed phase or step:** none — plan written 11-08-26, nothing executed.
3. **Validate-contract status:** written 11-08-26 and **BLOCKED pending a fresh full V1**. Cycle 1
   retained and addressed the prior F-1/F-2/F-3 + 8-CONCERN audit, plus S1 shared geo
   budget/backoff, S2 feedback retention, and S3 CF trust-boundary disclosures. **PVL supplement
   cycle 2 applied 11-08-26** locks the four later revalidation corrections: /identify enters the
   streaming guard and chunked-body proof, the budget has a dormant-safe finite BaseSettings
   contract, retention uses the real integration suite, and Playwright states API :8000 + web :3000
   honestly. Neither supplement is an unblock. Do not enter EXECUTE before independent V1
   re-adjudication; this is a high-risk public unauthenticated API surface and no VALIDATE skip
   condition applies.
4. **Supporting context files loaded:** `process/context/all-context.md`;
   `process/context/tests/all-tests.md`; `process/context/planning/all-planning.md`;
   parent plan `canary-onboarding_10-08-26/canary-onboarding_PLAN_10-08-26.md`;
   `canary-onboarding-phase-3_REPORT_10-08-26.md`; `maxmind-and-feedback-ops_NOTE_11-08-26.md`.
   Source read: `apps/api/routers/demo.py`, `apps/api/routers/onboarding.py`,
   `apps/api/services/onboarding_canary.py`, `apps/api/services/ip_resolution.py`,
   `apps/api/services/rate_limiter.py`, `apps/api/services/geoip.py`, `apps/api/services/retention.py`,
   `apps/api/jobs/scheduler.py`, `apps/api/config.py`, `apps/api/main.py`,
   `apps/web/playwright.config.ts`, `tests/integration/test_retention_purge.py`,
   `apps/web/public/beam/onboarding-app.js`, `onboarding-steps.js`, `onboarding.html`,
   `apps/web/next.config.mjs`.
5. **Next step for a fresh agent picking up mid-execution:** read the audit table at the top of the
   Overview **before touching anything**. If it disagrees with the tree, re-derive by content
   (`grep -n "STEP_ORDER" apps/web/public/beam/onboarding-app.js`,
   `grep -n 'router.post("/canary")' apps/api/routers/demo.py`) and trust the tree. Then start at
   Phase 1 step 1. Phases 1, 1b, 2, 2b, 3, 4 are agent work; Phase 5 is operator work and must not be
   self-executed. **Phase 1b (canary geo budget + backoff namespace) is not optional and not
   deferrable** — it is the only agent-side precondition of the flag flip, and without it a public
   flood can blank `/ingest` geo for every customer site. **Step 16a (the `chromium-noauth`
   Playwright project) must land before the spec is written**, or AC-10 produces a false green.
6. **Baseline to compare against:** `.venv/bin/python3.11 -m pytest tests/unit -m unit` →
   **1750 passed / 2 skipped** (the pinned AC-13 gate); `.venv/bin/python3.11 -m pytest tests/unit`
   (full collection) → **2683 passed / 2 skipped**. Integration
   `test_demo_canary_public.py` 11 tests; alembic head `f4b9d2a71c68`; branch `devjulley` clean.

## Validate Contract

Status: BLOCKED
Date: 11-08-26
date: 2026-08-11
generated-by: outer-pvl

Parallel strategy: sequential
Rationale: 5/7 signals present (S2 API/auth surface, S3 3+ directions, S6 high-risk class — public
unauthenticated API + trust-boundary, S7 9 files in blast radius; S1 2 packages, S4 no phase program).
Score 4/7 → HIGH, which would normally recommend an agent team or parallel-subagent fan-out. **The
Agent tool is not available in this environment**, so Layer 1 (4 dimensions) and Layer 2 (5 sections)
were executed SEQUENTIALLY by a single validate-agent against the live tree. Every finding below is
backed by a file:line citation or a command that was actually run — none is inferred. Agent count:
1 (sequential). Cost guard: not triggered.

### Net gate derivation

| Layer 1 dimension | Status |
|---|---|
| Infra / setup fit | PASS |
| Test coverage | **FAIL** |
| Breaking changes | CONCERN |
| Security surface | **FAIL** |

| Layer 2 section | Status |
|---|---|
| A — Phase 1 Input bounds (steps 1–8) | CONCERN |
| B — Phase 2 Guard + observability (steps 9–12) | CONCERN |
| C — Phase 3 Static comments + clamp (steps 13–14) | CONCERN |
| D — Phase 4 Tests (steps 15–17) | **FAIL** |
| E — Phase 5 Rollout (steps 19–22) | CONCERN |

**Totals: 3 FAILs / 6 CONCERNs / 0 clean PASSes beyond Infra**

**→ Net Gate: BLOCKED** — return to PLAN (PVL supplement cycle). Do NOT route to EXECUTE.

### Premise audit (re-derived live against HEAD `ccb04fd`, branch `devjulley`)

Every row of the plan's "already shipped" audit table was re-derived by content. **All 13 rows are
correct.** Supporting evidence actually executed:

- `onboarding-app.js:12` — `STEP_ORDER = ['welcome','canary_go','canary_listen','canary_reveal','account']`; file is 184 lines ✓
- `onboarding-steps.js` is 501 lines ✓
- `demo.py:372` `@router.post("/canary")` → `demo_canary`, no `Depends(get_current_user)` ✓
- `demo.py:360` `_require_location_reveal()` → 404 when flag off ✓; `demo.py:357` `_PUBLIC_CANARY_RATE = "40/minute"` ✓
- `demo.py:394` `fetch_journey(db, fp, site_id=settings.beam_self_site_id)` ✓; `demo.py:413` logs `ip[:8]` ✓
- `apps/web/src/app/onboarding/` does not exist ✓
- `main.py:551` `include_router(demo.router, prefix="/api/v1/demo")` → the two guarded paths in step 9 are byte-exact ✓
- `tests/integration/test_demo_canary_public.py` — **11 tests, all PASS** (`.venv/bin/python3.11 -m pytest tests/integration/test_demo_canary_public.py -q` → `11 passed in 32.57s`, against the isolated `retarget_agent_test` DB; `DATABASE_URL` deliberately NOT exported) ✓
- `alembic -c apps/api/alembic.ini heads` → `f4b9d2a71c68 (head)` ✓ matches the plan
- Postgres :5433 + Redis :6379 confirmed listening via `lsof` ✓

**Baseline that does NOT match — see F-2.**

### Dimension findings

- **Infra fit: PASS** — mounted paths, middleware ordering, CORS, alembic head and both test services all verified live; one low-severity note (exact-match path semantics) recorded below.
- **Test coverage: FAIL** — the stated unit baseline is wrong by 933 tests (F-2) and the AC-10 Playwright gate is not runnable as written (F-3).
- **Breaking changes: CONCERN** — no real client breaks (max real fingerprint is 32 chars, not the 20 the plan asserts), but the plan's stated rationale is factually wrong and `/demo/journey` is missing from the Public Contracts table.
- **Security surface: FAIL** — G1's own threat model is live on a fifth unauthenticated route the plan never enumerates (F-1).
- **Section A feasibility: CONCERN** — mechanically feasible; empty-string handling is inconsistent between the two regex layers (harmless in practice).
- **Section B feasibility: CONCERN** — step 11's "add nothing" branch resolves the wrong way; `bounded_shown`'s signature cannot signal truncation to its caller.
- **Section C feasibility: CONCERN** — feasible; carries the false "deterministic 20 chars" claim into a source comment.
- **Section D feasibility: FAIL** — carries F-2 and F-3, plus an unmentioned `geoRedirect` in front of the exact URL the new spec targets.
- **Section E feasibility: CONCERN** — correctly operator-gated; step 21's counters are unreachable by default and the manual soak will hit the US-only geo redirect.

### FAILs (each blocks EXECUTE)

**F-1 — G1 misses a fifth unauthenticated fingerprint entry point (Security surface / Section A).**
`POST /api/v1/demo/identify` (`apps/api/routers/demo.py:112`) is unauthenticated (no
`Depends(get_current_user)`), rate-limited 6/min, and takes `IdentifyBody.fingerprint: str | None = None`
(`demo.py:47-49`) with **no length or charset bound**. At `demo.py:139-147` it runs
`select(Visitor.visitor_id, Visitor.ip_address).where(Visitor.fingerprint == body.fingerprint)`.
That is the *exact* threat G1 describes, on a public route. It does **not** go through
`fetch_journey`, so step 2's defence-in-depth does not reach it. The plan's Goal 1 says "bound every
caller-controlled input on the two public POSTs" — but `demo.py` has **four** unauthenticated
fingerprint-bearing POSTs (`/identify`, `/journey`, `/canary`, `/identity-feedback`) and the plan
bounds three. After EXECUTE as written, the vulnerability the plan exists to close is still live one
route over. **Fix required in plan:** add `/api/v1/demo/identify` (`IdentifyBody.fingerprint`) to
Touchpoints, Blast Radius, Public Contracts and an AC, or state an explicit, evidenced reason for
excluding it.

**F-2 — the stated unit-lane baseline is wrong by 933 tests (Test coverage / Section D).**
The plan asserts "Unit lane 1750 passed / 2 skipped" in three places (L14 Branch baseline, L399
Verification Evidence, L518 Resume handoff). Measured live on this HEAD:

```
.venv/bin/python3.11 -m pytest tests/unit -q   →  2683 passed, 2 skipped, 16 warnings in 16.10s
.venv/bin/python3.11 -m pytest tests/unit -q --collect-only  →  2685 tests collected
```

AC-13's regression gate is a comparison against that number. An EXECUTE agent following the plan
would see a 933-test unexplained delta and either mis-diagnose it as breakage or silently normalise
away a real regression. **Fix required in plan:** correct all three occurrences to
`2683 passed / 2 skipped`.

**F-3 — the AC-10 Playwright gate is not runnable as written, and would produce a false green
(Test coverage / Section D).** `apps/web/playwright.config.ts` declares exactly one non-setup
project:

```
{ name: "chromium", use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/user.json" },
  dependencies: ["setup"] }
```

Any new spec placed in `e2e/` inherits **both**. Consequences:

1. `npx playwright test e2e/static-onboarding-funnel.spec.ts` first runs `e2e/auth.setup.ts`, which
   POSTs `/api/v1/auth/login` with `demo@getbeam.fyi` / `password123` against `http://localhost:8000`
   and `expect(res.ok()).toBeTruthy()`. So the gate's real preconditions are: API on :8000 **and** a
   seeded demo user **and** a working auth DB. The plan lists only "dev server on :3000".
2. The spec would run with an **authenticated** `storageState` — so it cannot prove anything about
   the logged-out public funnel, which is the entire point of G5. A regression that walls
   `/onboarding` behind auth would still pass. This is the false-green failure mode.
3. Fixing it requires a new project entry in `apps/web/playwright.config.ts` (no `dependencies`, no
   `storageState`). **That file is absent from Touchpoints and Blast Radius**, and AC-13's diff
   discipline would then flag the edit as unauthorised.

**Fix required in plan:** add `apps/web/playwright.config.ts` to Touchpoints/Blast Radius with the
new logged-out project, and correct AC-10's precondition line.

### CONCERNs

| # | Finding | Severity | Proposed fix |
|---|---|---|---|
| C-1 | **The "20 chars" rationale is factually wrong.** `_h128`/`hash128` return `h[0..3].toString(36)` (`onboarding-steps.js:45`, `tracker.js:93`, `beam-fingerprint.ts:29`). Base-36 of a uint32 is 1–7 chars (36⁶=2,176,782,336 ≤ 2³²−1 < 36⁷), so a real value is **8–32 chars and NOT fixed-length**. D2 says "= 20 chars"; step 14 says "deterministic 20 chars". Steps 1 and 14 instruct writing that claim into source comments. | CONCERN | Correct D2 + steps 1/14 to "8–32 chars, variable; 64 is ~2× headroom". **The 64 cap itself is SAFE and is NOT a FAIL** — see the G1/fp3 verdict below. |
| C-2 | **AC-11's 413/422/429 half is unreachable by default.** Those statuses are recorded only by `RequestResponseLogMiddleware` → `request_logger.should_log`, which returns `None` when `settings.request_log_enabled` is False (`config.py:1234`, **default False**). `classify` does map them (429→`rate_limited`, 413/422→`http_error`), and neither `request_log_exclude_paths` (`"/health,/api/v1/admin/request-logs"`) nor `request_log_ignore_statuses` (`"401"`) excludes the canary paths — so step 11's "if they are recorded, add nothing" branch is *technically* true but operationally empty. Phase 5 step 21 tells the operator to watch those counts with no instruction to enable the flag. | CONCERN | Phase 5 must add `REQUEST_LOG_ENABLED=true` (scoped, with `request_log_exclude_paths` unchanged) as an explicit soak precondition, or step 11 must take the "add a `logger.warning`" branch instead. Record the chosen branch in the phase report as step 11 already requires. |
| C-3 | **`bounded_shown` cannot signal truncation to its caller.** Step 6 specifies `bounded_shown(value) -> dict` returning `{}` for over-limit, non-dict, **and** genuinely-empty input. Step 10 then asks for `logger.warning("public_canary_shown_truncated", ...)` "inside `bounded_shown`'s caller when the value was replaced" — the caller cannot distinguish the three cases from a bare `dict` return. | CONCERN | Change the signature to `bounded_shown(value) -> tuple[dict, bool]` (or log inside the helper). Pick one and write it into step 6 so EXECUTE does not improvise. |
| C-4 | **`/onboarding` sits behind an unmentioned US-only geo redirect.** `apps/web/src/middleware.ts:9-15` `geoRedirect` 302s `/onboarding` → `/login` whenever `x-vercel-ip-country` is present and `!== "US"`. Locally the header is absent so Leg A passes; on any Vercel-fronted environment a non-US visitor never sees the funnel. The plan never mentions this file, and Phase 5 step 20's "hand-verify on residential / corporate VPN / mobile CGNAT" will read as "the funnel is broken" for any non-US tester. | CONCERN | Add `apps/web/src/middleware.ts` to the read-only-for-context list; add the US-only fact to the audit table and to Phase 5 step 20's instructions; note it as an AC-10 scope boundary. |
| C-5 | **`/api/v1/demo/journey` is missing from Public Contracts.** Step 2 changes `fetch_journey`, which also serves `demo_journey` (`demo.py:288-311`, explicitly documented there as the unscoped legacy path). Behaviour change is benign (silent `[]` either way) but the contract table claims to enumerate every affected surface. | CONCERN | Add a `/api/v1/demo/journey` row: "unbounded fp → `[]`; over-long/bad-charset fp → `[]` (unchanged status, unchanged shape)". |
| C-6 | **`_GUARDED_PATHS` asymmetry.** Step 9 guards 2 of the 4 public fingerprint-bearing demo POSTs. `/api/v1/demo/journey` is equally unauthenticated and equally fingerprint-driven but gets no body-size guard. | CONCERN | Either extend step 9 to `/api/v1/demo/journey` (one more set literal entry, zero new code) or record the exclusion rationale in D4. |
| C-7 | **`identity_feedback` is outside the GDPR erasure sweep.** `apps/api/services/graph_erasure.py` imports `BeamIdentityNode`, `IdentitySignal`, `SuppressionEntry`, `IdentifiedVisitor`, `Visitor`, `VisitorEmail` — **not** `IdentityFeedback`. That table stores a `fingerprint` (device identifier, `String(100)`) plus rendered city/region/org and a rounded lat-lng, written **unauthenticated**. Phase 5's flag flip is what turns this write path on at public scale. Pre-existing, but this plan is the one that opens the tap. | CONCERN | Backlog stub + a named Phase 5 precondition. Not a blocker for Phases 1–4. |
| C-8 (low) | **`_GUARDED_PATHS` matching is exact, not prefix** (`main.py:300` — `scope.get("path","") not in self._GUARDED_PATHS`). A trailing-slash variant (`/api/v1/demo/canary/`) misses the guard and takes FastAPI's 307 instead. Same pre-existing property as `/ingest`; D2/D3 still bound the redirected retry. | CONCERN (low) | One-line note in step 9's comment. No code change. |

### Verified-clean findings (asked for explicitly, no defect found)

| Question | Verdict | Evidence |
|---|---|---|
| **Is 64 chars ≥ every legitimate fingerprint? Would an fp3-bearing client break?** | **YES / NO — the cap is safe.** Max real value = `"fp2_"` + 4 × ≤7 base-36 chars = **32 chars** ≤ 64. `onboarding-steps.js:88` and `beam-fingerprint.ts:121` emit `fp2_` only. `tracker.js:264` builds `fp3_` but attaches it as `evt._fp3` on the **ingest** path only (`tracker.js:281`) — no fp3 value is ever POSTed to `/demo/canary` or `/demo/identity-feedback`, and even if one were it is the same ≤32-char class. Charset is base-36 (lowercase alnum) plus the `fp2_`/`fp3_` underscore, fully inside `[A-Za-z0-9_]`. | source read + arithmetic |
| **Does anything downstream break on `{}` `shown`?** | **NO.** The only reader is `GET /api/v1/onboarding/identity-feedback/stats` (`onboarding.py:160`, admin-only). It aggregates `count()`, `count().filter(note.isnot(None))` and `unnest(reasons)` — it **never reads `shown`** and its docstring states `shown` "is never returned, not even sampled". Storing `{}` costs nothing any consumer depends on. | `onboarding.py:160-205`, `maxmind-and-feedback-ops_NOTE_11-08-26.md` §2 |
| **Does the 256 KB guard actually catch the two new routes?** | **YES.** `main.py:551` mounts the demo router at `/api/v1/demo`, so the runtime paths are byte-exact matches for step 9's literals. Nothing legitimate approaches the cap: a real canary body is ~60 bytes and a real feedback body is bounded by `NOTE_MAX_CHARS=500` + `_SHOWN_MAX_BYTES=2048` + 4 enum reasons — ~3 KB worst case vs a 262,144-byte cap. | `main.py:281,300,551` |
| **Is the 413 usable cross-origin?** | **YES.** `_reject` (`main.py:288-297`) emits `access-control-allow-origin: *`, and `apiPost` (`onboarding-steps.js:96-100`) sends no credentials, so `*` is accepted. `_cors_origins` (`main.py:132-140`) includes `https://getbeam.fyi`, so the preflight (no body → passes the guard untouched) still gets an origin-mirrored response from `CORSMiddleware`. | source read |
| **Does the outermost log middleware defeat AC-4's "before the handler runs"?** | **NO.** `RequestResponseLogMiddleware` is registered last (`main.py:494`) and *is* the true outermost — its own docstring at `main.py:405-407` acknowledges it sits OUTSIDE the body-size guard — but its pre-read breaks at `total > max_bytes` (`request_log_max_body_bytes = 16_384`, `config.py:1240`) and `request_log_enabled` defaults False. Worst case is a bounded 16 KB pre-read, never the full hostile body. AC-4 holds. | `main.py:405-420`, `config.py:1234,1240` |
| **Cross-plan conflict scan** | **NO COLLISION.** `b2a7eef` (re-engagement) touches `apps/api/config.py` (+17) and `tests/unit/test_scheduler_job_config.py`; `e0dcc43` (farbled-browser) touches `apps/api/config.py` (+60). Both are already committed, and this plan's only `config.py` edit is a comment inside a different block (`location_reveal_enabled`, `config.py:1351`) — textual overlap is nil. `reengagement.py:175` links to `/dashboard/onboarding` (React beat, explicitly in this plan's NOT-touched list), not `/onboarding`. `graph_erasure.py` shares no symbol with the canary surface (its only intersection is the C-7 omission, which is an absence, not a conflict). No touchpoint of the 5 gaps is contended. | `git show --stat`, grep |
| **Live re-derive** | alembic head `f4b9d2a71c68` ✓ **matches**. Unit baseline **2683/2 — does NOT match** the plan's 1750/2 (F-2). Integration `test_demo_canary_public.py` 11/11 pass ✓. | commands run above |
| **Bonus (strengthens G1)** | `IdentityFeedback.fingerprint` is `String(100)` (`models/identity_feedback.py:66`). Today a 101+ char fingerprint raises on insert and is swallowed by the blanket `except` at `demo.py:472` — the **entire feedback row is silently dropped**, reasons included. G1's 64-char cap incidentally closes that silent-data-loss path. The plan does not claim this; it is a real argument in its favour. | source read |

### Test Gates (C3)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | Over-long / bad-charset fingerprint → 422 on public + authed canary before any DB or provider call | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_onboarding_canary_inputs.py -q` | B |
| AC-2 | `fetch_journey` returns `[]` for a bad fingerprint without constructing a query | Fully-Automated | `test_fetch_journey_rejects_before_query` (session double whose `execute` raises) | B |
| AC-3 | `shown` >2 KB or >16 keys stored as `{}`, `reasons` preserved, still 204 | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_demo_canary_public.py::test_oversize_shown_is_stored_empty -q` — precondition: Postgres :5433 + Redis :6379 (both confirmed listening) | B |
| AC-4 | Fragmented >256 KB body to each guarded demo route → 413 before the downstream handler, FastAPI parser, or Pydantic validation | Hybrid | `test_oversize_chunked_demo_bodies_are_rejected_before_parsing`, same precondition | B |
| AC-5 | `MOCK_EXTERNAL_APIS=true` → deterministic geo, zero outbound HTTP | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_geoip.py tests/unit/test_geoip_city.py -q` + new `test_public_canary_mock_mode_no_http` | B |
| AC-6 | Flag off → 404 on all four routes, no provider call | Fully-Automated | `test_flag_off_returns_404_and_calls_no_provider` — **passing today** | A |
| AC-7 | No `ip`/`site_id`/`visitor_id`/`fingerprint` in any canary response | Fully-Automated | `test_response_never_leaks_identifiers` — **passing today** | A |
| AC-8 | Journey hard-pinned to `beam_self_site_id`; no site enumeration | Fully-Automated | `test_journey_is_scoped_to_beam_site` + `test_body_supplied_ip_is_ignored` — **passing today** | A |
| AC-9 | Per-IP rate limit trips and keys on `resolve_client_ip` | Fully-Automated | `test_rate_limit_trips` + `test_x_forwarded_for_is_not_trusted` — **passing today** | A |
| AC-10 | Static funnel legs A–G at `/onboarding` | Hybrid | `cd apps/web && npx playwright test --project=chromium-noauth e2e/static-onboarding-funnel.spec.ts` — global config requires API :8000 + web :3000; this project requires neither seeded user nor auth setup, and the US-only `geoRedirect` bounds Leg A | B |
| AC-11 | Abuse event visible in structlog, no PII beyond `ip[:8]` | Hybrid | `test_shown_truncation_is_counted` covers the `shown` half only; **the 413/422/429 half needs `REQUEST_LOG_ENABLED=true` (C-2)** | B (shown half) + D (413/422/429 half) |
| AC-12 | `resolve_geoip("8.8.8.8")` still `("US","California")`; `/ingest` byte-identical | Fully-Automated | `tests/unit/test_geoip.py` backward-compat case + `tests/integration/test_events_ingest.py` | A |
| AC-13 | Zero migrations, zero new deps, zero React/dashboard changes | Agent-Probe | `git diff --stat` at EVL + `alembic -c apps/api/alembic.ini heads` still `f4b9d2a71c68` (**re-derived live today: matches**) | A |
| AC-15 | `/api/v1/demo/identify` rejects an over-long / bad-charset fingerprint before its `Visitor.fingerprint ==` query | Fully-Automated | `test_identify_rejects_overlong_fingerprint` + integration 422 assertion | B |
| AC-16 | Old `identity_feedback` rows delete while fresh rows survive and dry-run is non-destructive | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_retention_purge.py -q` — Postgres :5433 + Redis :6379 | B |
| AC-17 | All four unauthed demo POSTs are fingerprint-capped and guarded; a fragmented oversize body never reaches parsing | Hybrid | exact guard-set assertion + `test_oversize_chunked_demo_bodies_are_rejected_before_parsing` | B |
| AC-18 | Canary budget config defaults dormant-safe and has a finite ceiling | Fully-Automated | `test_canary_geo_daily_budget_default_and_ceiling` | B |
| **NEW (required by F-2)** | Full unit lane shows no regression against the true baseline | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -q` → **2683 passed / 2 skipped** (measured 11-08-26) | A (baseline re-measured; plan text must be corrected) |

Legacy line form (for existing validate-contract consumers):
- input bounds: Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_onboarding_canary_inputs.py -q`
- persistence + body guard: hybrid: `.venv/bin/python3.11 -m pytest tests/integration/test_demo_canary_public.py -q` + precondition Postgres :5433 / Redis :6379
- regression lane: Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit -q` (baseline 2683 passed / 2 skipped)
- static funnel: Hybrid: `cd apps/web && npx playwright test --project=chromium-noauth e2e/static-onboarding-funnel.spec.ts` — API :8000 + web :3000, no seeded user/auth setup
- 413/422/429 abuse counters: known-gap: documented — unreachable without `REQUEST_LOG_ENABLED=true`
- diff discipline: agent-probe: `git diff --stat` + `alembic heads` == `f4b9d2a71c68`

**gap-resolution legend:** A = proven now · B = gate added by this plan's checklist · C = deferred to
a named later phase · D = backlog test-building stub (named residual).

### What this coverage does NOT prove

- `pytest tests/unit -q` (2683 tests) proves no Python-side regression. It does **not** prove any
  browser behaviour, any Postgres behaviour, any middleware ASGI behaviour, or that the static funnel
  renders at all.
- `test_demo_canary_public.py` (11 tests, green today) proves the response shape, site pinning,
  IP non-leakage, rate limiting and flag gating **against `httpx`/ASGITransport**. It does **not**
  prove behaviour behind a real Cloudflare edge — `resolve_client_ip` vs the CF edge IP (parent risk 2)
  is untested and untestable here, and it is exactly the failure that would put every pin in a CF
  datacenter.
- `test_oversize_body_is_rejected_before_parsing` proves the 413 under ASGITransport. It does **not**
  prove uvicorn/h11 socket-level behaviour on a genuinely chunked 100 MB upload, nor the trailing-slash
  variant (C-8).
- The Playwright legs, once runnable, would prove the funnel's DOM against a **mocked** endpoint. They
  do **not** prove a real end-to-end catch (a live pixel hit on getbeam.fyi joining to a fingerprint
  from a second tab), Safari canvas-randomisation effects on the fp2 join, or the US-only geo redirect
  path (C-4).
- No gate proves the GDPR erasure coverage of `identity_feedback` (C-7) — that table has no test and
  no sweep.
- Nothing here proves ip-api's terms-of-service position on a now user-facing path (parent risk 6);
  that is a legal question, not a test.

### Open gaps

- **Historical V1 F-1/F-2/F-3:** Cycle 1 supplied their required plan corrections; Cycle 2 corrects
  the remaining guard/config/retention/Playwright contradictions. None are self-cleared — the fresh
  V1 revalidation below remains required before any execution routing.
- 413/422/429 abuse counters: known-gap: documented — requires `REQUEST_LOG_ENABLED=true` as a Phase 5 precondition (C-2).
- `identity_feedback` outside the GDPR erasure sweep: known-gap: documented as NEW PLAN REQUIRED — backlog stub needed before Phase 5 flips the flag (C-7).
- US-only `geoRedirect` on `/onboarding`: known-gap: documented — bounds AC-10 and Phase 5 step 20 (C-4).
- Real end-to-end catch / Safari canvas randomisation / prod CF client-IP / ip-api terms: carried
  forward unchanged from the plan's own Known-gaps table (resolution C + D as the plan already chose).

### PVL Supplement Cycle 1 — applied 11-08-26 (plan-agent, PVL-supplement mode)

Gate left **BLOCKED deliberately** — the next validate pass re-adjudicates. This record is an audit
trail, not an unblock claim.

| Source finding | Where addressed |
|---|---|
| F-1 `/demo/identify` unbounded fp | Touchpoints; Public Contracts; checklist 5a + 5b; AC-15, AC-17; unit-test list |
| F-2 baseline ambiguity | Header baseline table (command + number, both variants); Verification Evidence (2 rows); Resume handoff §6; Test Procedure §1; AC-13 |
| F-3 Playwright project | Touchpoints (`apps/web/playwright.config.ts`); D9; checklist 16a; AC-10 precondition corrected; Verification Evidence; Test Infra notes |
| C-1 fp2 is 8–32 chars variable | D2 rationale; checklist steps 1 and 14 |
| C-2 `REQUEST_LOG_ENABLED=true` | Phase 5 precondition **P-c** (chosen over the `logger.warning` branch — step 11 takes the "enable the existing logger" branch) |
| C-3 `bounded_shown` signature | Checklist step 6 pinned to `-> tuple[dict, bool]`; steps 7, 8, 10 and the unit-test list follow it |
| C-7(req)/C-4 `middleware.ts` geoRedirect | Context-consulted list; read-only Touchpoints; Leg A scope boundary; Phase 5 step 20; Risk 11; AC-10 |
| C-8(req)/C-5 `/demo/journey` contract | Public Contracts row added |
| C-9(req)/C-6 `_GUARDED_PATHS` | Checklist step 9 originally reached three demo routes + `/ingest`; Cycle 2 adds the required fourth `/identify` path, an exact-set test, and the chunked-body proof in AC-17 |
| C-8(low) exact-match paths | Checklist step 9 comment |
| C-10(req)/C-7 `identity_feedback` GDPR | Known-gaps row (NEW PLAN REQUIRED); Phase 5 precondition **P-d**; backlog stub `identity-feedback-gdpr-erasure_NOTE_11-08-26.md` |
| **S1** shared geo budget + global backoff → ingest degradation | New gap **G6**; **D7** (both halves); **Phase 1b** (steps 8a–8d); Blast Radius ingest-geo-degradation row; Public Contracts; **AC-14**; Risk 8; Phase 5 P-a/P-b + step 22 tripwire |
| **S2** `identity_feedback` retention + rate limit is not a bound | New gap **G7**; **D8**; **Phase 2b** (steps 12a–12d); **AC-16**; Risk 5 rewritten |
| **S3** CF-Connecting-IP forgeability + colo collapse | Two Known-gaps rows; Risks 9 and 10; Phase 5 step 20 bucket + off-CF-reachability checks; backlog stub `cf-connecting-ip-forgeability-canary_NOTE_11-08-26.md` |

Historical V1 result: BLOCKED (the Cycle 1 finding text is retained as an audit record). It is not an
acceptance claim; Cycle 2 deliberately leaves the live gate BLOCKED pending the next full V1 run.
Accepted by: n/a — BLOCKED gates carry no acceptance. No CONDITIONAL was self-accepted by this agent.

### PVL Supplement Cycle 2 — applied 11-08-26 (plan-agent, PVL-supplement mode)

This is a plan-only correction of four revalidation blockers. It does **not** claim that the prior
historical V1 findings are cleared: Gate BLOCKED remains deliberate until an independent
vc-validate-agent re-runs V1 against this revised artifact.

| Revalidation blocker | Re-derived evidence | Locked plan correction |
|---|---|---|
| /api/v1/demo/identify was fingerprint-hardened but absent from the body guard | apps/api/main.py:281 currently lists only /api/v1/events/ingest; its exact path check is at main.py:300, and its multi-frame running counter is at main.py:304-337. apps/api/routers/demo.py:112 exposes unauthenticated /api/v1/demo/identify. | G3, D4, Touchpoints, Public Contracts, step 9, AC-4, and AC-17 now require /identify in the exact five-path guard set. Step 16 adds a fragmented ASGI-body test over all four demo routes, proving a >256 KB chunked body is rejected with 413 before FastAPI/Pydantic can buffer or validate it. |
| Canary geo budget had no safe, bounded BaseSettings contract | apps/api/config.py:11 defines Settings(BaseSettings); the onboarding section currently ends at location_reveal_enabled (config.py:1330-1351). The public path shares _BACKOFF_KEY = geoip:backoff (services/geoip.py:49), read at :324-330 and written at :334-345. | Step 8d adds canary_geo_daily_budget: int = 0 immediately before location_reveal_enabled, with a field validator accepting only 0..500. The absent env remains a valid boot and safely disables provider-spend; AC-18 and the unit assertion pin default 0 plus rejection of -1/501. Phase 5 P-e requires an explicit non-zero 1..500 value only after the other flip gates are green. |
| The plan named a nonexistent unit retention test | tests/unit/test_retention.py does not exist. tests/integration/test_retention_purge.py:24-38 supplies patched_retention; its event old/delete, fresh/survive, and dry-run patterns begin at :64-109. | Touchpoints, step 12d, AC-16, Verification Evidence, and Test Procedure now use tests/integration/test_retention_purge.py and an explicit Hybrid command: .venv/bin/python3.11 -m pytest tests/integration/test_retention_purge.py -q with Postgres :5433 + Redis :6379. |
| No-auth Playwright wording contradicted global server startup | apps/web/playwright.config.ts:19-33 isolates project auth state/dependencies, but its top-level webServer array at :36-59 always starts API :8000 and web :3000. | D9, steps 16a/17, AC-10, Verification Evidence, Test Procedure, and the validate test-gate table now state the minimal safe direction: add chromium-noauth without storageState/dependencies, but retain API :8000 + web :3000 as the actual command precondition. No seeded user or auth setup is required for that project. |

The pre-existing Cycle 1 disclosures remain in force and are deliberately not removed: all four
public fingerprint routes, pinned test baselines, MaxMind + geo-isolation flip preconditions,
feedback retention, CF trust-boundary known gaps, and the GDPR-erasure backlog stay part of the
plan. This cycle adds no source, migration, environment, flag, or commit action.

Gate: **BLOCKED pending a fresh full V1 validation**. Accepted by: n/a.

### Note on fan-out method

The Agent tool was not available in this environment. Layer 1 (4 dimensions) and Layer 2 (5 sections)
ran **sequentially** in one context rather than as the parallel fan-out `vc-validate-findings`
specifies. Mitigation applied: every finding is grounded in a file:line citation or a command that was
actually executed against the live tree — no verdict rests on inference. The known weakness of a
single-pass sequential validate (documented in this repo's own memory: silent auto-merge omissions
sitting outside the reviewed hunks) is partly addressed here by the route-enumeration sweep that found
F-1, but an independent adversarial verifier on the next PVL cycle would be the correct compensating
control.

## Autonomous Goal Block

```
SESSION GOAL: Residual hardening of the shipped public unauthenticated canary endpoint + truncated static funnel — bound hostile input (G1 fingerprint, G2 shown), extend the body-size guard (G3), add abuse observability (G4), give the static funnel its first browser coverage (G5), then roll out behind location_reveal_enabled.
Charter + umbrella plan: N/A — single plan (no umbrella with ## Stable Program Goal exists for onboarding-canary)
Autonomy: NOT granted at this gate. Gate is BLOCKED — 3 FAILs. The next action is a PVL supplement cycle (vc-plan-agent), never EXECUTE.
Hard stop conditions / safety constraints:
- Do not enter EXECUTE while the gate is BLOCKED. VALIDATE skip conditions do not apply: this is a public unauthenticated API surface.
- An agent may never flip location_reveal_enabled in any real environment. Phase 5 is operator work.
- Never export the repo .env DATABASE_URL for a test or alembic run — it points at Supabase production. Pin localhost:5433 first. (tests/conftest.py already defaults to the isolated retarget_agent_test DB — do not override it.)
- Do not rebuild anything the audit table marks DONE. If EXECUTE finds itself editing STEP_ORDER, deleting funnel steps, or writing a second /canary route, it has misread the plan — stop.
- Zero migrations. alembic head must remain f4b9d2a71c68.
- No phase may mark itself VERIFIED on Known-Gap coverage alone.
Next phase: PVL supplement cycle — vc-plan-agent (supplement mode) addressing F-1, F-2, F-3 and C-1..C-8, then re-spawn vc-validate-agent from V1.
Validate contract: inline in plan — process/features/onboarding-canary/active/public-canary-funnel_11-08-26/public-canary-funnel_PLAN_11-08-26.md §Validate Contract
Execute start: BLOCKED — no execute start authorised. When unblocked: fully-auto `.venv/bin/python3.11 -m pytest tests/unit -q` (baseline 2683 passed / 2 skipped) | hybrid `.venv/bin/python3.11 -m pytest tests/integration/test_demo_canary_public.py -q` | e2e `apps/web/e2e/static-onboarding-funnel.spec.ts` (needs the F-3 config fix first) | high-risk pack: yes — public unauthenticated API + trust-boundary/input-validation class.
```

---

## Next Step

Plan complete. Review carefully. Say **"ENTER VALIDATE MODE"** when ready to proceed to plan
validation (required before implementation — this touches a public unauthenticated API surface, so
the VALIDATE skip conditions do not apply). Do not say ENTER EXECUTE MODE before then.
