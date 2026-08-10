---
phase: canary-onboarding-phase-3-canary
date: 2026-08-10
status: COMPLETE_WITH_GAPS
feature: onboarding-canary
plan: process/features/onboarding-canary/active/canary-onboarding_10-08-26/canary-onboarding_PLAN_10-08-26.md
---

# Phase 3 — The canary (Leaflet reveal + feedback), flag ON locally only

Live step order is now `welcome → canary_go → canary_listen → canary_reveal →
confirm → site → install → done`. `CANARY_ENABLED` in
`src/lib/onboarding-flow.ts` is `true`; the backend's
`location_reveal_enabled` **stays `False` in the committed default**
(`apps/api/config.py:1308`, verified after the run) and was enabled only via an
env var for this session.

Two real defects were found by exercising the live endpoint, both of which the
existing test suites structurally could not catch. See §Plan Deviations.

## What Was Done

### Created — components

| File | Contents |
|---|---|
| `apps/web/src/components/onboarding/steps/canary-go-step.tsx` | `CANARY_URL = https://getbeam.fyi/?beam=canary`; computes fp2 **on the click**, `window.open(..., "noopener,noreferrer")`, ghost skip |
| `apps/web/src/components/onboarding/canary-listen.tsx` | Radar (`.ob-listen`/`.ob-radar`), escalating status on a 1s ticker, TanStack poll, escape hatch |
| `apps/web/src/components/onboarding/canary-map.tsx` | Leaflet, `divIcon` pin, accuracy circle, tile-failure detection |
| `apps/web/src/components/onboarding/canary-reveal.tsx` | `next/dynamic({ssr:false})` map + place + network + page list + honesty caption |
| `apps/web/src/components/onboarding/identity-feedback-form.tsx` | Native `<input type=checkbox>` + `.ob-check`, 4 reasons, 500-char note |
| `apps/web/src/components/onboarding/steps/confirm-step.tsx` | "is this you?" → yes / not quite |
| `apps/web/src/lib/canary-listen-status.ts` (+ `.test.ts`) | Pure deadline/cadence/copy module — see Deviation 1 |
| `apps/web/e2e/onboarding-canary.spec.ts` | 7 legs, all green |

### Modified

- `apps/web/src/lib/onboarding-flow.ts` — `CANARY_ENABLED = true`; `FlowState`
  gains `fingerprint` + `canary`; new `CANARY_START` event; `CANARY_RESULT`
  carries the payload; **`GOTO` is now literal** (see Deviation 2);
  `sanitizeResumeStep` also refuses to resume into `canary_reveal`/`confirm`.
- `apps/web/src/lib/onboarding-script.ts` — canary copy; `revealLines(landed)`
  so the not-landed opening is honest instead of "got you."
- `apps/web/src/lib/api.ts` — `onboardingCanary(fingerprint, signal)` and
  `submitIdentityFeedback(...)`.
- `apps/web/src/components/onboarding/onboarding-flow.tsx` — the four steps
  wired; optimistic feedback POST; honest handoff line into `site`.
- `apps/web/package.json` — `leaflet@^1.9.4`, `@types/leaflet@^1.9.22`. **No
  `react-leaflet`.**

### Leaflet specifics, all as specified

Two independent SSR guards (`next/dynamic({ssr:false})` **and**
`await import("leaflet")` inside `useEffect`); `L.divIcon` not `L.marker`;
`TILE_URL`/`TILE_ATTRIBUTION` exported constants with the CSP note;
`scrollWheelZoom:false`, `minZoom:9`, `maxZoom:13`, `dragging:true`;
translucent accuracy circle; tile-failure fallback (≥4 `tileerror` inside 2.5s,
or no `load` within 4s → `map.remove()` → text reveal), plus a catch on the
dynamic import itself.

## Test Gate Outcomes

| Gate | Result |
|---|---|
| `npx vitest run` (apps/web) | **149 passed / 9 files / 0 failed** (was 141; +8, incl. 5 new in `canary-listen-status.test.ts`) |
| `npx tsc --noEmit` (apps/web) | **clean, exit 0** |
| `npm run build` (apps/web) | **✓ Compiled successfully.** `/dashboard/onboarding` 16.4 kB / 127 kB First Load. Shared First Load JS **88 kB** — see §Bundle |
| `e2e/onboarding-canary.spec.ts` | **8 passed / 0 failed** (7 legs + auth setup) |
| `e2e/onboarding.spec.ts` (regression) | **14 passed / 1 failed** — AC-9 cross-tenant disclosure **PASSES**; the 1 failure is the same pre-existing one Phase 2 documented |
| `tests/unit/test_geoip.py` + `test_location_reveal.py` | **32 passed** (was 30; +2 new) |
| `tests/integration/test_onboarding_canary_api.py` + `test_demo_journey.py` | **9 passed + 3 passed**, green on two consecutive runs |
| `tests/integration/test_events_ingest.py` | **21 passed / 0 failed** (Phase 1's 1 failure is gone — the concurrent session's `farbled` migration is now applied locally) |
| Full unit lane (`tests/unit`) | **2587 passed / 2 skipped / 0 failed** |
| Migration live round-trip | PASS on a disposable DB **and** on a full `base → head` rebuild (below) |

### The one e2e failure

`onboarding.spec.ts:366 › Site settings dialog shows pixel snippet + cookie
consent`. It navigates to `/dashboard/visitors` and its click is intercepted by
the tour dialog's `bg-foreground/60` overlay. Identical failure and identical
cause to Phase 2's report; it never loads `/dashboard/onboarding`. The only
uncommitted edits in that page's tree are the concurrent session's
`browser-capture-card.tsx` (+37) and `api-types.ts` (+11), both dirty before
this session and untouched by it.

### Bundle

Shared First Load JS reads **88 kB** where Phase 2 reported 87.6 kB. **Leaflet
is not the cause and is not in the shared bundle** — verified directly:

- `grep -c openstreetmap` → **0** in both shared chunks (`2117-…`, `fd9d1056-…`).
- Leaflet lives alone in `chunks/d0deef33.…js` (148 KB raw ≈ 42 KB gz),
  referenced by **no** page chunk — i.e. fetched only when the dynamic import
  runs.
- `grep -c identity-feedback` → **0** in both shared chunks, so this phase's
  `api.ts` additions are not in them either.
- Both builds this session produced **byte-identical shared chunk hashes**.

I could not attribute the 0.4 kB delta to any Phase 3 symbol. It is most likely
the concurrent session's edits or a reporting rounding difference; re-measuring
a clean baseline would need git operations, which were out of bounds.

## Live verification against the real endpoint

API run locally with `LOCATION_REVEAL_ENABLED=true`, `MOCK_EXTERNAL_APIS=true`,
`DATABASE_URL` pinned to `localhost:5433`, **no Playwright route mocks**, real
OSM tiles.

**Landed path (curl, real fingerprint join).** Ingested a real pageview batch
into a local site with `_fp=fp2_livecheck123`, then `POST /onboarding/canary`
returned `landed: true` with `/pricing` (42s, merged from its separate
`time_on_page` row) and `/blog`, plus geo and network. Response keys were
exactly `['geo','landed','network','pages']` — **no `ip`, `site_id`,
`visitor_id` or `fingerprint`**, the anti-regression the plan asks for.

**Degraded geo-only path (browser, end-to-end).** Clicking "catch me" opened
exactly `https://getbeam.fyi/?beam=canary`; the status line escalated
`listening…` → `still listening — did the tab actually load?` by 26s; **8 polls
in 26s** (the 2s→4s backoff, comfortably inside the 30/minute limit). Because
the headless browser's fp2 never reached the pixel, the flow correctly took the
not-landed branch and said so:

> didn't catch your visit — adblocker, DNT/GPC (we honor both), or the tab never
> loaded. … but here's what your IP alone says: ◎ Mountain View, California · US
> ⌁ looks like you're on Mock Org's network … that's an IP-level estimate —
> usually the right city, sometimes the wrong suburb.

**It never claimed a catch it did not make**, and the map still rendered —
6 real `.leaflet-tile` elements loaded from tile.openstreetmap.org with the
attribution control reading `Leaflet | © OpenStreetMap contributors`.

One measurement trap worth recording: reading `canary-map` immediately after the
reveal appears returns 0, because `next/dynamic`'s `loading:` skeleton is still
mounted. It is 1 after the chunk settles. A future test that asserts "no map"
without waiting will pass vacuously.

## Plan Deviations

1. **`statusFor` / deadline / cadence were moved into
   `src/lib/canary-listen-status.ts`** rather than living in the component. The
   plan's "logic lives in src/lib" constraint applies to them — the poll budget
   is now a unit test (`pollIntervalFor` walked across the full 90s window must
   stay ≤30 calls) instead of something only observable by getting 429'd.

2. **`GOTO` no longer sanitizes.** It previously routed through
   `sanitizeResumeStep`, which now rewrites `confirm` → `canary_go`. Since
   `confirm` is reached by `GOTO` from the reveal, leaving it would have bounced
   the user back to the start of the catch. `GOTO` is intra-session navigation
   and is now literal; `RESUME` still sanitizes. Three existing tests were
   updated and three added.

3. **`sanitizeResumeStep` also refuses `canary_reveal` and `confirm`.** Both
   render the reveal payload, which is deliberately never persisted (no
   coordinates are stored anywhere), so resuming into them showed an empty card.

4. **DEFECT FIX — `identity_feedback` was missing `updated_at`; every
   submission 500'd.** `models/database.py:81` puts `updated_at` on `Base`
   itself, so SQLAlchemy emitted it in `INSERT … RETURNING` while migration
   `a1c7f4e082d5` never created the column →
   `UndefinedColumnError: column identity_feedback.updated_at does not exist`.
   The integration tests stayed green because `tests/conftest.py` builds the
   schema with `create_all` from metadata, **not** from the migration — the
   suite structurally cannot see this class of drift. Fixed by adding the column
   to the migration, which is untracked, uncommitted and undeployed, so an
   in-place edit is safe. Proven twice: a disposable-DB `up → down → up`
   round-trip, and a full `base → head` rebuild. Feedback now returns 204 and
   the row lands with the unknown reason correctly dropped.
   **This is a schema-surface edit and is flagged accordingly**, though it adds
   the repo-mandated `Base` column the plan's table always implied rather than
   any new field.

5. **DEFECT FIX — mock mode could not produce a reveal locally.**
   `resolve_geoip_full` checked the loopback guard *before* the
   `mock_external_apis` branch, so on a dev machine (where the caller's IP *is*
   `127.0.0.1`) the reveal always returned `geo: null` — directly contradicting
   the plan's degraded-paths row ("`MOCK_EXTERNAL_APIS=true` returns a
   deterministic fake so it demos locally"). The two checks are now swapped.
   **The ingest hot path is unaffected**: `resolve_geoip` keeps its own loopback
   guard above the call, so it still returns `("", "")` for `127.0.0.1`
   regardless of mock mode — now asserted explicitly by a new test, because this
   is exactly the reorder that could start stamping fake countries onto real
   events.

6. **`test_geo_cache_reuse_makes_one_provider_call` was self-poisoning.** It
   cleared the two in-process caches but not Redis, so the first run wrote
   `geoip2:203.0.113.9` and every run afterwards saw zero provider calls. It now
   clears the L2 keys and pins `mock_external_apis = False` (otherwise the
   assertion is vacuous). Green on two consecutive runs, which it was not before.

## Test Infra Gaps Found

- **I wiped the local dev DB and rebuilt it.** Running
  `DATABASE_URL=…/retarget_agent pytest tests/integration/…` pointed
  `tests/conftest.py` at the **dev** database instead of its default
  `retarget_agent_test`, and its teardown `drop_all` removed all 53 tables.
  Recovered with `alembic stamp base` + `upgrade head` (DATABASE_URL pinned to
  localhost throughout): **54 tables, head `e2b7c94a1f38`** — unchanged from
  before the wipe — and `demo@getbeam.fyi` / `password123` re-seeded with
  `plan='max'`. The full e2e suite was re-run afterwards and is green. Lesson
  for the next session: **never export `DATABASE_URL` pointing at
  `retarget_agent` when running integration tests** — let conftest use
  `retarget_agent_test`. The dev DB's pre-existing 4 "Test *" sites are gone;
  the specs recreate them.
- **Next dev-server cold-compile flake.** The first navigation after the dev
  server compiles `/dashboard/onboarding` can serve a partial chunk —
  `SyntaxError: Invalid or unexpected token`, empty transcript. A reload always
  fixes it and `npm run build` compiles cleanly, so it is a dev-server artifact,
  but `playwright.config.ts` runs the suite against `npm run dev`, so
  `openChat()` in the new spec reloads once if the transcript is empty.
- **Ingest silently 204s a curl-shaped UA.** The first live ingest attempt
  returned 204 and stored nothing (bot filter). A browser UA is required to seed
  a visit by hand.
- Two e2e legs wait out the real 90s deadline (~1.7 min each), so the canary
  spec takes ~4.3 min. `page.clock` could shrink this; not attempted.
- Phase 2's harness recipe still applies verbatim and is still needed: free port
  (3100 via a throwaway config, **deleted after the run**), pinned
  `NEXT_PUBLIC_API_URL`, `FRONTEND_URL=http://localhost:3100` on the API for
  CORS, local `DATABASE_URL`. Forgetting `FRONTEND_URL` once produced 15
  cross-origin failures that look nothing like a CORS problem.
- `CONTEXT_PARTIAL: apps/web/.env.local and .env` — still blocked by the privacy
  hook; `NEXT_PUBLIC_API_URL` was overridden, never read.

## Closeout Packet

- **Finished:** the plan's entire "the canary" phase — all four steps, Leaflet,
  the feedback form and its live POST, every degraded path in the table, the two
  API client methods, and the e2e spec.
- **Verified:** the gates above; the reveal exercised live against the real
  local endpoint on both the landed and geo-only paths, with real OSM tiles.
- **Unverified:** production `resolve_client_ip` behind Cloudflare; whether
  `maxmind_asn_db_path` is set in the deployed env (rung 1 dead when `""`);
  real ip-api geo (only the mock provider was exercised); the plan's manual QA
  matrix (corporate VPN, mobile hotspot, uBlock, Safari); the 24h `/ingest`
  geoip soak the rollout order requires.
- **Classification: Keep in active/testing.** The server flag is still `False`
  and Phase 4 (truncate the static funnel, MaxMind GeoLite2-City, surface
  feedback counts in ops) is unstarted.

## Forward Preview

**Test Infra Found** — the conftest/`DATABASE_URL` hazard above is the single
most important item to carry forward; it silently destroys the dev DB.

**Blast Radius Changes** — `apps/api/services/geoip.py` now short-circuits to
the mock before the loopback guard; any future edit must keep `resolve_geoip`'s
frozen `("", "")`-on-loopback contract (now test-guarded). Migration
`a1c7f4e082d5` changed while uncommitted — if it has been shared anywhere,
re-derive rather than assume.

**Commands to Stay Green**
```
cd apps/web && npx vitest run && npx tsc --noEmit && npm run build
cd apps/web && npx playwright test e2e/onboarding-canary.spec.ts e2e/onboarding.spec.ts
.venv/bin/python3.11 -m pytest tests/unit/test_geoip.py tests/unit/test_location_reveal.py -q
.venv/bin/python3.11 -m pytest tests/integration/test_onboarding_canary_api.py -q   # no DATABASE_URL override
```

**Dependency Changes** — `leaflet@^1.9.4` + `@types/leaflet@^1.9.22` (plus
transitive `@types/geojson`). Confined to the onboarding route's async chunk.
