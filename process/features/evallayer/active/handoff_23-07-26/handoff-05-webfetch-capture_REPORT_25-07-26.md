---
phase: handoff-05-webfetch-capture
date: 2026-07-25
status: COMPLETE_WITH_GAPS
feature: evallayer
plan: process/features/evallayer/active/handoff_23-07-26/handoff-05-webfetch-capture_PLAN_25-07-26.md
---

# Handoff Detection H5 — Server-Side AI-Fetch Capture — EXECUTE Report

**TL;DR:** All Sections A–E implemented exactly per plan + validate-contract E1–E7. Every
Fully-Automated gate is GREEN (beacon unit 15/15, classifier 24/24, Vitest matcher 39/39, web edge
build OK). The Hybrid integration test (AC-H5-1 + AC-H5-8 tripwire) is written and collect-clean but
could not run (Docker daemon unavailable) → KG-4. HIGH-RISK evidence pack written + validated
(approved-with-concerns). Gate stays CONDITIONAL on deploy/infra-gated KG-1..KG-4. No git commit
performed (per instruction).

## What Was Done

- **A1 config** (`apps/api/config.py`): added `agent_fetch_beacon_enabled: bool = False` +
  `beam_fetch_beacon_secret: str = ""` in the EvalLayer flag block.
- **A2 classifier** (`apps/api/services/agent_classifier.py`): added `"google"` vendor with the one
  documented token `google-cloudvertexbot`, kept **INDEX-tier** (E5/KG-3 conservative; NOT
  `google-extended`). Updated tier-completeness test `_EXPECTED_INDEX`.
- **B4 persistence** (`agent_visit_persistence.py`): E1 — added optional `event_time` param to
  `persist_agent_fetch_event`; writes `created_at=event_time` when provided, server-default otherwise.
- **B5 schema** (`schemas/agents.py`): added `FetchBeaconIn` + `FetchBeaconAck`.
- **B6 service** (NEW `services/agent_fetch_beacon.py`): `record_fetch_beacon` + `decode_token_mint_ts`.
  Imports ZERO identity module (E3); logs keys-only; on-demand-tier gate; public Site tenancy lookup
  (unknown → noop, never 403).
- **B7 router** (`routers/agents.py`): `_verify_beacon_secret` dep with E2 ordered guards
  (empty-configured-secret 401 FIRST, then empty header 401, then `hmac.compare_digest`) +
  `POST /fetch-beacon` (flag-off → 404 dormant; written → 202; noop → 204). Registered before GET catch-alls.
- **C9 Vitest**: added `vitest.config.ts` + `vitest@^2.1.9` devDep + `test`/`test:watch` scripts.
- **C10 web helper** (NEW `apps/web/src/lib/fetch-beacon.ts`): pure matcher (excludes /api,/trpc,
  _next,static,?_rsc) + `fireFetchBeacon` (AbortSignal.timeout 1500ms, swallow-all, dormant unless
  secret+apiBase set).
- **C11 middleware** (`apps/web/src/middleware.ts`): `ev.waitUntil(fireFetchBeacon(...))` guarded on
  secret env, OUTSIDE the Clerk callback, never alters the return.
- **D13/D14/D15 tests**: `tests/unit/test_agent_fetch_beacon.py` (15), `tests/integration/
  test_agent_fetch_beacon_integration.py` (3, non-vacuous AC-H5-8 tripwire), `fetch-beacon.test.ts` (39).
- **E17 registry**: Phase 5 marked DONE with confirmed-disjoint blast radius.
- **E7 evidence pack**: 5 artifacts in `handoff-05-webfetch-capture_25-07-26/harness/`, validator clean.

## What Was Skipped or Deferred

- **Integration run (KG-4)**: Docker daemon unavailable in sandbox — test written + collect-clean, NOT run. Not faked.
- **Umbrella reconciliation (checklist #18)**: "Google-Extended out of scope" bullet + WAF-403 language — left for UPDATE PROCESS (documentation task).
- **Rate-limiting (R-1)**: deferred to backlog stub.

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| Beacon unit (AC-H5-1..7) | `pytest tests/unit/test_agent_fetch_beacon.py` | PASS 15/15 |
| Classifier additive (AC-H5-9) | `pytest tests/unit -k agent_classifier` | PASS 24/24 |
| Web matcher (AC-H5-10) | `npx vitest run apps/web/src/lib/fetch-beacon.test.ts` | PASS 39/39 |
| Web edge build | `cd apps/web && npm run build` | PASS (Middleware 92.4 kB) |
| Integration both-row + tripwire (AC-H5-1/8) | `pytest tests/integration/test_agent_fetch_beacon_integration.py` | KG-4 (Docker unavailable; written + collect-clean) |
| Full unit regression | `pytest tests/unit -m unit` | 465 passed; 2 pre-existing HEAD-level failures OUTSIDE blast radius |

## Plan Deviations

- **E5 google token**: plan said "add google vendor conservatively." I chose the concrete token
  `google-cloudvertexbot` (index-tier) because existing tests (`TestAC13ExclusionRobotsTxtOnlyTokens`)
  pin `google-extended`/`applebot-extended` as never-classified. Within-blast-radius, honors E5/KG-3.
- No other deviations. All E1–E7 followed to the letter.

## Test Infra Gaps Found

- **KG-4**: integration tier requires Postgres+Redis; Docker daemon down in sandbox. Run on a
  disposable Postgres: `docker compose -f infra/docker-compose.yml up -d postgres redis && .venv/bin/python -m pytest tests/integration/test_agent_fetch_beacon_integration.py -q`. NEVER a shared dev DB.
- **Pre-existing (foreign)**: `tests/unit/test_agent_company_resolution.py` 2 failures — committed
  `resolution_runner.py:63` uses `site.url`, test mock is a `SimpleNamespace` without `.url`. Outside
  H5 blast radius; working tree for those files == HEAD; not introduced by this phase.

## Closeout Packet

- **Selected plan:** `.../handoff-05-webfetch-capture_PLAN_25-07-26.md`
- **Finished:** Sections A–E; all Fully-Automated gates green; evidence pack validated.
- **Verified vs unverified:** unit + matcher + edge-build verified; real-DB persistence + tripwire
  UNVERIFIED (KG-4, Docker); live edge capture UNVERIFIED (KG-2, deploy).
- **Cleanup remaining:** UPDATE PROCESS — umbrella reconciliation (D-A/WAF language), archive, commit.
- **Classification:** `Keep in active/testing` — CONDITIONAL until KG-4 integration run + operator confirms live capture.

## Follow-up stubs created

- `process/features/evallayer/backlog/handoff-05-cfpages-waituntil-verification_NOTE_25-07-26.md` (KG-2)
- `process/features/evallayer/backlog/handoff-05-gemini-ua-token-unverified_NOTE_25-07-26.md` (KG-3)
- `process/features/evallayer/backlog/handoff-05-fetch-beacon-rate-limit_NOTE_25-07-26.md` (R-1)

## Operator Handoff (post-merge USER actions — Claude cannot do these)

**CORRECTED 25-07-26 (live verification):** the web app is hosted on **Vercel** (project
`retarget-agent`), not Cloudflare Pages as originally assumed here — Cloudflare only proxies
DNS/WAF. Set the beacon env vars on Vercel, not Cloudflare.

1. Generate a strong random secret; set it as `BEAM_FETCH_BEACON_SECRET` on **Vercel → project
   `retarget-agent` → Settings → Environment Variables (Production)** AND as
   `beam_fetch_beacon_secret` on Railway (API) — identical value, server-only.
2. Also set on Vercel: `BEAM_API_BASE` (`https://api.getbeam.fyi`) + `BEAM_SITE_ID`
   (`beam_getbeam_fyi`, the getbeam.fyi Beam site_id).
3. **Redeploy** the Vercel project after setting the env vars.
4. Live-apply the 8 pending EvalLayer/handoff migrations before flipping any flag.
5. Flip `agent_fetch_beacon_enabled = true` on the API.
6. Run the KG-4 integration test on a disposable Postgres before relying on prod capture.
7. After redeploy, trigger a real ChatGPT/Perplexity/Gemini browse of getbeam.fyi and confirm a new
   Agents-dashboard row (closes KG-2 — downgraded: Vercel Edge Middleware supports `waitUntil`
   natively, so this just confirms live delivery). Capture the real Gemini fetch UA to close KG-3.

## Forward Preview

- **Test Infra Found:** `apps/web` now has Vitest (first JS unit runner) — reusable for future web unit tests.
- **Blast Radius Changes:** H5 additive-only over H1–H4; new files `agent_fetch_beacon.py`,
  `fetch-beacon.ts`, `vitest.config.ts`. No migration.
- **Commands to Stay Green:** `pytest tests/unit/test_agent_fetch_beacon.py`; `pytest tests/unit -k agent_classifier`;
  `npx vitest run apps/web/src/lib/fetch-beacon.test.ts`; `cd apps/web && npm run build`.
- **Dependency Changes:** `apps/web` devDep `vitest@^2.1.9` (+ transitive) added to `package.json`/`package-lock.json`.
