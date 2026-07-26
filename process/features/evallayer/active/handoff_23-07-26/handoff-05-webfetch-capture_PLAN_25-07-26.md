---
name: plan:handoff-05-webfetch-capture
description: "Handoff Detection Phase H5 — server-side AI-fetch capture: getbeam.fyi middleware detects on-demand AI fetcher UAs and beacons an authenticated POST to a new Beam API endpoint that classifies + writes agent_visit + agent_fetch_event (no new migration; lights up existing Agents dashboard)"
date: 25-07-26
feature: evallayer
phase: "H5"
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: H5
---

# Handoff Detection Phase H5 — Server-Side AI-Fetch Capture

**Date**: 25-07-26
**Complexity**: COMPLEX (single phase; new trust boundary + cross-runtime web↔API wiring)
**Status**: ⏳ PLANNED
**Program:** Handoff Detection (`handoff_23-07-26`) — new phase added after H1–H4 (all DONE)
**Umbrella:** `process/features/evallayer/active/handoff_23-07-26/handoff-umbrella_PLAN_23-07-26.md`
**SPEC (governs all phases; INNER loop skips SPEC):** `process/features/evallayer/active/handoff_23-07-26/handoff_SPEC_23-07-26.md`

---

## Context Envelope

| # | Field | Value |
|---|---|---|
| 1 | feature | evallayer |
| 2 | phase | PLAN (producing H5 phase plan) |
| 3 | session-goal | Wire server-side AI-fetch capture so on-demand fetchers record agent_visits + agent_fetch_events on the existing Agents dashboard |
| 4 | branch | main |
| 5 | worktree | main |
| 6 | context-group | tests, planning |
| 7 | blast-radius-packages | apps/web (middleware + new helper), apps/api (new endpoint/router, config, classifier), tests |
| 8 | active-plan | this file |
| 9 | test-runner | pytest (unit + integration) \| (apps/web: Vitest for the pure matcher — added this phase) |
| 10 | validate-contract | written (25-07-26, CONDITIONAL — see below) |

---

## TL;DR

Today the ONLY writer of `agent_visits` / `agent_fetch_events` is the pixel ingest path (`POST /api/v1/events/ingest`), which classifies the **caller's** UA. On-demand AI fetchers (ChatGPT-User, OAI-SearchBot, Claude-User, Claude-SearchBot, Perplexity-User, and — new — Gemini/Google) fetch the page as raw HTTP, never run the pixel JS, so they are never captured — the pipeline is structurally blind to the fetchers it was built to detect. This phase closes that gap: `apps/web/src/middleware.ts` detects an on-demand fetcher UA on any getbeam.fyi request, fires a **fire-and-forget authenticated POST** (`event.waitUntil`) to a new API endpoint `POST /api/v1/agents/fetch-beacon`, which authenticates via a shared secret, classifies via the existing `classify_agent`/`classify_tier`, and writes BOTH an `agent_visit` and an `agent_fetch_event` — reusing the existing persistence functions. No new migration, no frontend change (the Agents dashboard reads these tables already). The 10-min handoff-correlation sweep (already scheduled, ungated) finally gets fetch rows to correlate.

**Highest-priority guardrail:** the beacon path imports ZERO identity write path — it must NEVER create/touch a Visitor/IdentifiedVisitor. Proven by a tripwire test.

**Top risk (trust boundary):** a new internet-reachable endpoint that WRITES to the DB, gated by a shared secret — a leaked secret or an empty-secret misconfiguration lets forged POSTs poison the dashboard + correlation. Mitigated by constant-time compare, an explicit empty-secret 401 guard, default-OFF flag, and dormant-when-secret-absent. (See VALIDATE finding on `hmac.compare_digest('','') == True`.)

**WAF status (CORRECTED 25-07-26 — supersedes the earlier KG-1 "403 domain-wide" claim):** Named on-demand AI fetchers REACH the getbeam.fyi origin. Proven live 25-07-26 (Claude-in-Chrome on the user's own browser): ChatGPT AND Gemini both fetched `https://getbeam.fyi/pricing-overview/{token}` → HTTP 200 + real content + cited the exact token; the Cloudflare dashboard showed `ChatGPT-User = Allowed`. The earlier 403 was a **generic/unnamed** bot UA, not a named fetcher UA. Capture is therefore **NOT** infra-gated behind a WAF allowlist for named fetchers. Residual (minor): per-vendor WAF allow-status for `Perplexity-User` / `Claude-User` specifically is unverified (only ChatGPT/OAI + Gemini/Google proven reaching origin) — a CONDITIONAL note, not a blocker.

**Post-ship correction (25-07-26, live verification):** the earlier assumption that getbeam.fyi's web app runs on **Cloudflare Pages** was WRONG. Live verification (Claude-in-Chrome, response headers `x-vercel-id`/`x-vercel-cache`) confirmed the web app is hosted on **Vercel** (project `retarget-agent`, org `tranthaiwork-droid`, repo `julleycode/retarget-agent`, auto-deploys `main`). Cloudflare only proxies DNS/WAF in front (hence the `cf-ray`/`server: cloudflare` headers alongside the Vercel ones) — it does not host the app. This plan's Operator Handoff, Touchpoints, and KG-2 below are corrected accordingly. Vercel Edge Middleware supports `event.waitUntil` natively, so the original KG-2 runtime-support risk is downgraded — the only residual is confirming live beacon delivery once the env vars are set correctly on Vercel and redeployed. (Root cause of the observed 0-capture during verification: the 3 beacon env vars were mistakenly set on Cloudflare Pages instead of Vercel, so `process.env.BEAM_FETCH_BEACON_SECRET` was undefined on the live host — the middleware code itself is correctly deployed, commits `9f4a8a7`/`e26c0f6`.)

---

## Goals

1. Record on-demand AI fetcher hits to getbeam.fyi as `agent_visit` + `agent_fetch_event` rows via a server-side beacon, with zero frontend change to the Agents dashboard.
2. Establish a secure, spoof-resistant trust boundary (shared-secret header, constant-time compare) between the Vercel web layer and the Railway API.
3. Keep the ingest hot path, Clerk auth flow, and `isPublicRoute` logic untouched; the beacon is additive, fire-and-forget, and fully dormant behind a default-OFF flag + absent-secret skip.
4. Preserve the program's highest-priority guardrail: agent records stay structurally non-emailable; the beacon touches no identity surface.

## Non-Goals / Out of Scope

- No new migration (tables already exist on `main`).
- No dashboard/frontend rendering change — writing the rows is sufficient to light up the tab.
- No new identity resolution, no company-graph write from the beacon (the existing async sweeps own that).
- No WAF/Cloudflare edge config change (infra, founder-executed — documented in Operator Handoff). NOTE: WAF allowlisting is NO LONGER a precondition for capture of named fetchers (see corrected WAF status).
- No change to the existing pixel-driven `classification` branch in `events.py`.
- No attempt to log/store unmatched raw UAs to discover unknown fetchers (PII/scope).

---

## Locked Design Decisions (user-approved — do NOT re-litigate)

1. **Scope = site-wide.** Detect on-demand fetcher UA on every getbeam.fyi request in `apps/web/src/middleware.ts`, not only the probe page. Filter to real top-level document GETs from recognized on-demand fetcher UAs ONLY — never fire on static assets, API/`trpc` calls, prefetches, or non-fetcher traffic. Must not disturb Clerk auth or `isPublicRoute`.
2. **Auth = shared secret.** `POST /api/v1/agents/fetch-beacon` requires header `X-Beam-Fetch-Secret`, whose value is a server-only env var present on BOTH Vercel (`BEAM_FETCH_BEACON_SECRET`) and the Railway API. Constant-time compare; 401 without/with wrong secret; never shipped to the browser. This is the trust boundary — HIGH-RISK (spoofed POSTs poison the dashboard + correlation).
3. **Write BOTH** `agent_visit` AND `agent_fetch_event` (reuse `persist_agent_visit` + `persist_agent_fetch_event`; `persist_agent_fetch_event` gets a small additive optional `event_time` param — see VALIDATE E1).
4. **Include Google/Gemini (VALIDATE-locked, D-A resolved).** This phase brings Google-Extended/Gemini IN even though the umbrella listed it out-of-scope. The umbrella reconciliation is a required EXECUTE/UPDATE-PROCESS follow-up.
5. **Fetch-event timestamp (VALIDATE-locked).** Use the decoded mint-time from the token when the path is `/pricing-overview/{token}`; fall back to server-receive time for site-wide (non-token) paths.
6. **Web unit runner (VALIDATE-locked).** Add **Vitest** to `apps/web` for the pure matcher (Test Infra decision A).
7. **New flag** `agent_fetch_beacon_enabled` default `False`; endpoint + middleware beacon both gated by it; middleware also skips when the secret env is absent. No new migration.

## Decisions Requiring VALIDATE Scrutiny (RESOLVED)

- **D-A (Gemini/Google support vs umbrella out-of-scope) — RESOLVED: include Google/Gemini.** Additively add a conservative `"google"` vendor to `_VENDOR_TOKENS`. VALIDATE constraint: the exact live Gemini/Google on-demand fetch UA token is UNVERIFIED (KG-3) — allowlist conservatively and default the token to **index** tier unless a specific token is confirmed user-driven, so a crawler is never mislabeled on-demand. `Google-Extended` is the AI-control token; the actual browsing/fetch UA may differ. EXECUTE confirms the real UA string from live fetch logs post-deploy. UPDATE PROCESS reconciles the umbrella "out of scope" bullet for the capture path.

---

## Touchpoints (file:line anchors — verify at EXECUTE, do not trust blindly)

### apps/api (Railway) — the endpoint + classification + write

| File | Change | Anchor / note |
|---|---|---|
| `apps/api/routers/agents.py` | ADD `POST /fetch-beacon` route (before the GET `/{site_id}` / `/{site_id}/{agent_visit_id}` catch-alls; different HTTP method so no real collision, but register early for clarity). No Clerk `get_current_user`; auth via shared-secret dependency. | router mounted at `/api/v1/agents` (`apps/api/main.py:281`); existing catch-alls at `agents.py` GET `/{site_id}` (line 31) and GET `/{site_id}/{agent_visit_id}` (line 133) |
| `apps/api/config.py` | ADD `agent_fetch_beacon_enabled: bool = False` and `beam_fetch_beacon_secret: str = ""`. | mirror `agent_detection_enabled` (`config.py:188`); place in the EvalLayer flag block (188/197/208) |
| `apps/api/services/agent_classifier.py` | ADD `"google"` vendor to `_VENDOR_TOKENS`; add its token(s) to `_ON_DEMAND_TOKENS` **only if confirmed user-driven** (else leave index-tier). Purely additive; keep `classify_tier` total + completeness test green. | `_VENDOR_TOKENS` (line 23), `_ON_DEMAND_TOKENS` (line 46), `classify_tier` (line 51) |
| `apps/api/services/agent_visit_persistence.py` | `persist_agent_visit` REUSED unchanged. `persist_agent_fetch_event` gets a **small additive** optional param `event_time: datetime \| None = None` → when provided, pass `created_at=event_time` into the insert values; when None, keep `server_default=func.now()` behavior. Fail-open preserved. (See VALIDATE E1 — the original "no edit" claim was wrong; `created_at` is `Base.server_default=func.now()` and cannot be set to mint-time without this edit.) | `persist_agent_fetch_event` (line 119); `Base.created_at` is `server_default=func.now()` (`models/database.py:36`) |
| `apps/api/schemas/agents.py` | ADD `FetchBeaconIn` request schema (site_id, user_agent, path, optional token) + optional `FetchBeaconAck` OR return bare 204/202. | existing schemas imported by `agents.py` |
| `apps/api/models/site.py` | READ only — resolve `Site.site_id` for tenancy (public, no Clerk). | `Site` class; mirror `events.py:126` `select(Site.tracking_enabled).where(Site.site_id == ...)` |
| `apps/api/services/agent_fetch_beacon.py` (NEW) | Extract beacon business logic (classify → gate on on-demand tier → resolve site → decode token to mint ts → write both rows) into a testable service function, keeping the router thin. Import ZERO identity/Visitor module (guardrail). | new file; DB-session-injected |

### apps/web (Vercel) — the detector + fire-and-forget beacon

| File | Change | Anchor / note |
|---|---|---|
| `apps/web/src/middleware.ts` | ADD a fire-and-forget beacon call using `ev.waitUntil(...)` when `shouldFireFetchBeacon(req)` is true. Must run WITHOUT altering the existing `geoRedirect` → Clerk handler return path; beacon is a side-effect, never changes the response. Skip entirely when flag/secret env absent. Keep the beacon in the exported `middleware`, NOT inside the `clerkMiddleware` callback. | current `middleware(req, ev)` returns `geoRedirect(req) ?? handler(req, ev)` (line 46-48); `ev` (NextFetchEvent) already in scope |
| `apps/web/src/lib/fetch-beacon.ts` (NEW) | Pure helper: `shouldFireFetchBeacon(req)` (UA allowlist + top-level-document GET filter + `_next`/static/`?_rsc` prefetch/`api`/`trpc` exclusion) and `fireFetchBeacon(payload)` (the `fetch()` POST with the secret header, short `AbortSignal.timeout(~1500ms)`, all errors swallowed). | new file. NOTE: `config.matcher` runs middleware for `/(api\|trpc)(.*)` too, so the matcher MUST exclude api/trpc itself. |
| `apps/web/vitest.config.ts` + `package.json` (NEW dev dep) | Add Vitest to `apps/web` (Test Infra decision A) so `fetch-beacon.test.ts` is Fully-Automated. | apps/web has no JS unit runner today (confirmed: no vitest/vite config, no test script) |

### tests

| File | Change |
|---|---|
| `tests/unit/test_agent_fetch_beacon.py` (NEW) | classify gating, auth (incl. empty-secret 401), flag-off dormancy, token decode. |
| `tests/integration/test_agent_fetch_beacon_integration.py` (NEW) | endpoint writes both rows + non-emailability tripwire (non-vacuous, real DB). |
| `apps/web/src/lib/fetch-beacon.test.ts` (NEW) | pure UA/path matcher truth table — Vitest. |
| `apps/web/e2e/agents.spec.ts` (EXTEND, optional) | assert normal traffic is unaffected. |

---

## Public Contracts

### New endpoint: `POST /api/v1/agents/fetch-beacon`

**Auth:** header `X-Beam-Fetch-Secret: <shared secret>`. **Explicit empty-secret guard FIRST:** if `settings.beam_fetch_beacon_secret` is empty → `401` immediately, BEFORE any `hmac.compare_digest` call (VALIDATE confirmed `hmac.compare_digest('','') == True` — comparing against an empty configured secret would otherwise ACCEPT an empty header, an auth bypass). Then constant-time compare via `hmac.compare_digest`. Missing or mismatched → `401`. Never accept when `agent_fetch_beacon_enabled` is False → `404` dormant.

**Request body (`FetchBeaconIn`):**
```
{
  "site_id":    string,        // required — the getbeam.fyi Beam site id
  "user_agent": string,        // required — the raw fetcher User-Agent
  "path":       string,        // required — request path (e.g. "/pricing-overview/p1abc")
  "token":      string | null  // optional — present only when path matches /pricing-overview/{token}
}
```

**Behavior / responses:**

| Condition | Status | Side effect |
|---|---|---|
| `agent_fetch_beacon_enabled` False | `404` (dormant; do not reveal endpoint) | none |
| Empty configured secret (misconfig) | `401` (guard BEFORE compare_digest) | none |
| Missing/wrong secret | `401` | none |
| `classify_agent(user_agent)` is None (junk/unknown UA) | `204` | none |
| Classified but `classify_tier(token) == "index"` (crawler, e.g. GPTBot) | `204` | none — on-demand only |
| Classified on-demand + `site_id` unknown | `204` (not-found no-op) | none (never 403 — no id-existence leak) |
| Classified on-demand + `site_id` valid | `202`/`204` | write `agent_visit` (upsert) + `agent_fetch_event` (append) |

- **Multi-tenancy:** resolve `site_id` via `Site.site_id` lookup (public, no Clerk). Unknown/foreign → not-found no-op (204), never 403.
- **Token → mint timestamp:** when `token` matches `^p[0-9a-z]+$`, decode `parseInt(token.slice(1), 36) * 1000` → mint datetime, and pass it as `event_time` to `persist_agent_fetch_event` (which sets `created_at` explicitly). Invalid/absent token → server-receive time (default `func.now()`), still write.
- **PII/GDPR:** never log the raw UA or IP — keys/vendor/site_id only (matches the existing persistence-layer logging discipline).
- **Mock mode:** endpoint deterministic without live deps; `MOCK_EXTERNAL_APIS=true` exercises the full write path with the in-process DB.
- **Fail-open:** persistence reuses the fail-open functions; a write failure never 500s the beacon.

### Web middleware beacon contract (non-blocking)

- Fires via `ev.waitUntil(fireFetchBeacon(...))` — NEVER awaited in the request path.
- `shouldFireFetchBeacon` returns non-null ONLY for: method GET + recognized on-demand fetcher UA + top-level document path (exclude `_next`, static asset extensions, `/api`, `/trpc`, `?_rsc`/prefetch markers).
- All beacon errors swallowed (try/catch inside `fireFetchBeacon`; `AbortSignal.timeout(~1500ms)`); never breaks `geoRedirect` or Clerk.
- Dormant when `process.env.BEAM_FETCH_BEACON_SECRET` is absent OR the web-side enable flag is off.

---

## Blast Radius

- **Files:** ~7 changed/new source (`agents.py`, `config.py`, `agent_classifier.py`, `agent_visit_persistence.py` [+event_time param], `schemas/agents.py`, `middleware.ts`, new `fetch-beacon.ts`) + new `agent_fetch_beacon.py` service + `vitest.config.ts` + 3–4 test files.
- **Packages:** `apps/api` (endpoint, classifier, config, persistence), `apps/web` (middleware, helper, vitest).
- **Risk class:** HIGH — NEW public-internet-reachable API endpoint that WRITES to the DB, gated only by a shared secret (trust-boundary / auth surface); also touches Edge middleware on the request path of every getbeam.fyi request (perf/availability). No schema/migration change.
- **Cross-phase overlap:** `middleware.ts` touched by H4 (DONE), `agent_classifier.py` by H1 (DONE), `agents.py` by H2/H3 (DONE), `agent_visit_persistence.py` by H1 (DONE). All prior claimants DONE → no live coordination conflict expected; re-confirm via registry at EXECUTE.

---

## Implementation Checklist (atomic, ordered)

### Section A — API config + classifier (foundation)
1. `apps/api/config.py`: add `agent_fetch_beacon_enabled: bool = False` and `beam_fetch_beacon_secret: str = ""` in the EvalLayer flag block, comment mirroring `agent_detection_enabled`.
2. `apps/api/services/agent_classifier.py`: additively add `"google": frozenset({...conservative token(s)...})` to `_VENDOR_TOKENS`. Add to `_ON_DEMAND_TOKENS` ONLY a token confirmed user-driven; otherwise leave google index-tier (D-A / KG-3). Keep `classify_tier` total (update/confirm `test_tier_map_covers_all_vendor_tokens`).
3. Run `pytest tests/unit -k agent_classifier` → confirm additive change green.

### Section B — API endpoint + service
4. `apps/api/services/agent_visit_persistence.py`: add optional `event_time: datetime | None = None` to `persist_agent_fetch_event`; when set, include `created_at=event_time` in the insert values. No other behavior change; fail-open preserved.
5. `apps/api/schemas/agents.py`: add `FetchBeaconIn` (site_id, user_agent, path, token: `str | None = None`). Optional `FetchBeaconAck`.
6. `apps/api/services/agent_fetch_beacon.py` (new): `async def record_fetch_beacon(db, payload) -> str` — classify → if None or tier != on-demand return "noop" sentinel → resolve `Site.site_id` (noop if unknown) → decode token to mint ts if present/valid → `persist_agent_visit` + `persist_agent_fetch_event(..., event_time=mint_ts_or_None)`. Import ZERO identity/Visitor module (guardrail). Log keys-only.
7. `apps/api/routers/agents.py`: shared-secret dependency `_verify_beacon_secret` — **empty-secret 401 guard FIRST** (`if not settings.beam_fetch_beacon_secret: raise 401` — configured secret empty/None → 401 dormant, evaluated BEFORE any `hmac.compare_digest` call because `hmac.compare_digest('','') == True`), then require a non-empty provided `X-Beam-Fetch-Secret` header (empty/absent header → 401), then `hmac.compare_digest(provided, configured)` for the constant-time match (mismatch → 401). `POST /fetch-beacon`: gate on `settings.agent_fetch_beacon_enabled` (404 dormant) → auth dep → `record_fetch_beacon` → map sentinel/no-op to 204, success to 202/204. Register before GET catch-alls.
8. Confirm route ordering does not shadow existing GET routes (route-list check; POST vs GET).

### Section C — Web middleware detector + beacon
9. `apps/web/vitest.config.ts` + add Vitest dev dep + `"test": "vitest"` script to `apps/web/package.json` (Test Infra decision A).
10. `apps/web/src/lib/fetch-beacon.ts` (new): `ON_DEMAND_UA_TOKENS` constant (mirror API on-demand set), `shouldFireFetchBeacon(req)` (GET + UA match + top-level-doc + `_next`/static/`?_rsc`/`api`/`trpc` exclusion), `fireFetchBeacon(payload)` (POST with `X-Beam-Fetch-Secret`, `AbortSignal.timeout(~1500ms)`, try/catch swallow). Read secret/site-id/api-base from `process.env` (server-only).
11. `apps/web/src/middleware.ts`: in `middleware(req, ev)`, `const beacon = shouldFireFetchBeacon(req); if (beacon && process.env.BEAM_FETCH_BEACON_SECRET) ev.waitUntil(fireFetchBeacon(beacon));` BEFORE returning `geoRedirect(req) ?? handler(req, ev)`. Beacon must not change the response and must stay OUT of the Clerk callback.
12. Verify no change to `isPublicRoute`, `config.matcher`, or the Clerk `auth().protect()` path.

### Section D — Tests
13. `tests/unit/test_agent_fetch_beacon.py`: (a) on-demand UA → both rows; (b) index-crawler (`gptbot`) → 204 no write; (c) junk UA → 204; (d) missing/wrong secret → 401; (e) **empty configured secret → 401** (regression against the `compare_digest('','')` hazard); (f) flag off → 404; (g) unknown site_id → 204; (h) token → decoded mint ts on `created_at`; (i) invalid token → server-receive time.
14. `tests/integration/test_agent_fetch_beacon_integration.py`: endpoint writes exactly one `agent_visit` (upsert) + one `agent_fetch_event`; **tripwire**: assert zero `Visitor`/`IdentifiedVisitor` rows + `is_emailable_identity` untouched (non-vacuous — real DB, real POST).
15. `apps/web/src/lib/fetch-beacon.test.ts`: Vitest matcher truth table (GET+UA+top-level only; excludes static/prefetch/api/trpc).
16. (Optional) extend `apps/web/e2e/agents.spec.ts`: normal auth/render unaffected.

### Section E — Docs + registry + closeout
17. Append a `## Phase 5 (H5)` blast-radius claim to `phase-blast-radius-registry.md`.
18. Update the handoff umbrella: note H5 added; reconcile the "Google-Extended out of scope" bullet for the capture path (UPDATE PROCESS). Also correct any lingering "WAF 403 domain-wide blocker" language program-wide per the corrected WAF status.
19. Write the Operator Handoff actions into the phase report at closeout.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves criterion |
|---|---|---|
| `pytest tests/unit/test_agent_fetch_beacon.py` on-demand UA → both rows | Fully-Automated | AC-H5-1 core capture |
| index-crawler (`gptbot`) → 204 no write | Fully-Automated | AC-H5-2 on-demand-only gating |
| junk/unknown UA → 204 no write | Fully-Automated | AC-H5-3 None-path safety |
| missing/wrong secret → 401 | Fully-Automated | AC-H5-4 trust boundary |
| empty configured secret → 401 | Fully-Automated | AC-H5-4 (empty-secret bypass guard) |
| flag off → 404 dormant | Fully-Automated | AC-H5-5 default-OFF dormancy |
| unknown site_id → 204 no-op (never 403) | Fully-Automated | AC-H5-6 multi-tenancy no-leak |
| token → decoded mint ts on created_at; invalid → receive time | Fully-Automated | AC-H5-7 mint-time decode |
| Integration: endpoint writes both rows | Hybrid (needs PG) | end-to-end persistence |
| Integration tripwire: zero Visitor/IdentifiedVisitor; is_emailable_identity untouched | Hybrid (needs PG) | AC-H5-8 highest-priority guardrail |
| classifier additive: `tests/unit -k agent_classifier` green + tier completeness | Fully-Automated | AC-H5-9 google token additive |
| `fetch-beacon.ts` Vitest matcher truth table | Fully-Automated | AC-H5-10 middleware fires only on real on-demand doc GETs |
| Web e2e: normal traffic auth/render unaffected | Agent-Probe | AC-H5-10 no Clerk/isPublicRoute regression |
| Live: fetcher → Vercel middleware → `waitUntil` → row post-deploy | Known-Gap (deploy-gated) | real capture end-to-end (KG-2, downgraded) |

---

## Test Matrix

| Layer | Runner | Tier | Scope |
|---|---|---|---|
| API endpoint unit | pytest (`tests/unit`) | Fully-Automated | classify gating, auth (incl. empty-secret), flag, token decode, tenancy |
| API endpoint integration | pytest (`tests/integration`, needs PG+Redis) | Hybrid | both-row writes + non-emailability tripwire |
| classifier additive | pytest (`tests/unit`) | Fully-Automated | google vendor added; existing tokens intact |
| web matcher | Vitest (`apps/web`, added this phase) | Fully-Automated | pure UA/path truth table |
| web e2e | Playwright (`apps/web/e2e`) | Agent-Probe | no regression to auth/render |
| live capture | manual, post-deploy | Known-Gap | fetcher → middleware → beacon → row |

---

## Risks

| ID | Risk | Severity | Mitigation |
|---|---|---|---|
| R-1 | **Trust boundary — spoofed/forged POSTs poison dashboard + correlation.** | HIGH | Shared-secret header, `hmac.compare_digest` constant-time, **empty-secret 401 guard**, secret server-only, flag default OFF. Rate-limiting is a backlog follow-up (see Open Gaps). Blast radius of poisoning is bounded — agent_visits/agent_fetch_events only, never identity/emailable. |
| R-2 | Middleware beacon degrades every getbeam.fyi request. | MED | Fire-and-forget `ev.waitUntil`; short `AbortSignal.timeout`; errors swallowed; skip when flag/secret absent; matcher excludes static/prefetch/api. |
| R-3 | Beacon reaches an identity write path. | HIGH | Beacon service imports ZERO identity module; integration tripwire asserts no Visitor/IdentifiedVisitor + is_emailable_identity untouched. |
| R-4 | Route ordering: `/fetch-beacon` shadowed by GET `/{site_id}`. | LOW | Different HTTP method; register before catch-alls; route-list check + literal-path unit test. |
| R-5 | Gemini/Google token mislabels a crawler as on-demand → fabricated human-intent signal downstream. | MED | Conservative: google token defaults to **index** tier unless confirmed user-driven; VALIDATE reviewed; KG-3 tracks UA uncertainty; EXECUTE confirms from live logs. |

### Known-Gaps (deploy/infra-gated — carried, keep gate CONDITIONAL; excluded from CONCERN count)

- **KG-1 (DOWNGRADED — no longer a blocker):** per-vendor WAF allow-status for `Perplexity-User` / `Claude-User` is unverified. ChatGPT/OAI + Gemini/Google are PROVEN to reach the origin (live 25-07-26). The earlier "403 domain-wide" claim was a generic-bot-UA artifact, not a named-fetcher block. → residual note only; refine after real capture.
- **KG-2 (DOWNGRADED 25-07-26 — host correction):** the web app is hosted on **Vercel**, not Cloudflare Pages as originally assumed. Vercel Edge Middleware supports `event.waitUntil` natively, so runtime support is no longer in question. Residual: confirm live beacon delivery once the 3 env vars are set on Vercel (not CF Pages) and the app is redeployed. → backlog stub `handoff-05-cfpages-waituntil-verification_NOTE` (reframed as Vercel verification).
- **KG-3:** the exact live Gemini/Google on-demand fetch UA token is unverified (no documented token). Ship best-known conservative token defaulted to index tier; refine after real capture. → backlog stub `handoff-05-gemini-ua-token-unverified_NOTE`.
- **KG-4:** integration tests are Docker/PG-gated in this sandbox — run on a disposable Postgres, never against shared dev DB.

---

## Dependencies

- Tables `agent_visits` (`d11b39a6c843`) + `agent_fetch_events` (`c4e8f1a9d2b7`) — already on `main`; **NO new migration.**
- The 8 pending EvalLayer/handoff migrations must be live-applied before enabling the flag in prod (existing operator gate).
- Reused: `persist_agent_visit` (unchanged), `persist_agent_fetch_event` (+ optional `event_time`), `classify_agent`, `classify_tier`, `Site` lookup pattern.
- Handoff correlation sweep (`apps/api/jobs/scheduler.py` / `agent_handoff_correlation.py`, ungated, 10-min) — already scheduled; consumes the fetch rows. No change needed.

---

## Operator Handoff (post-merge USER actions — Claude cannot do these)

1. Generate a strong random secret; set it as `BEAM_FETCH_BEACON_SECRET` on **Vercel → project `retarget-agent` → Settings → Environment Variables (Production)**, AND as `beam_fetch_beacon_secret` on **Railway** (API) — identical value. (CORRECTED 25-07-26: the web app is hosted on Vercel, not Cloudflare Pages — do not set these vars on Cloudflare.)
2. Also set on Vercel (same location): `BEAM_SITE_ID = beam_getbeam_fyi` and `BEAM_API_BASE = https://api.getbeam.fyi` (the getbeam.fyi Beam site_id + the beacon's API target).
3. **Redeploy** the Vercel project after setting the env vars (env var changes require a redeploy to take effect).
4. Live-apply the 8 pending migrations before flipping any flag.
5. Flip `agent_fetch_beacon_enabled = true` on the API.
6. (Optional, no longer a precondition) A Cloudflare WAF allowlist for on-demand AI fetchers only matters for vendors NOT yet proven reaching origin (Perplexity/Claude — KG-1). ChatGPT/Gemini already reach origin. (Cloudflare still fronts DNS/WAF in front of Vercel — this step is unrelated to the Vercel hosting correction.)
7. After redeploy, verify `event.waitUntil` beacon delivery on **Vercel** (KG-2, downgraded — Vercel Edge Middleware supports `waitUntil` natively; this step just confirms live delivery) by triggering a real ChatGPT/Perplexity/Gemini browse and checking the Agents dashboard.

---

## Acceptance Criteria

- **AC-H5-1:** On-demand fetcher UA POST (valid secret, valid site, flag on) writes exactly one `agent_visit` (upsert) + one `agent_fetch_event`.
- **AC-H5-2:** Index-crawler UA (`gptbot`) writes nothing → 204.
- **AC-H5-3:** Junk/unknown UA writes nothing → 204.
- **AC-H5-4:** Missing / wrong / **empty-configured** secret → 401 (constant-time compare + empty-secret guard).
- **AC-H5-5:** `agent_fetch_beacon_enabled=False` → 404 dormant; no write, endpoint not revealed.
- **AC-H5-6:** Unknown/foreign `site_id` → 204 no-op, never 403.
- **AC-H5-7:** Valid `/pricing-overview/{token}` token → decoded mint timestamp on the fetch event `created_at`; invalid token → server-receive time, still writes.
- **AC-H5-8 (HIGHEST PRIORITY):** Beacon path creates/touches ZERO `Visitor`/`IdentifiedVisitor`/identity rows; `is_emailable_identity` untouched — proven by a non-vacuous integration tripwire.
- **AC-H5-9:** Additive `google` vendor token change leaves all existing classifier tests green and `classify_tier` total.
- **AC-H5-10:** `apps/web` middleware fires the beacon ONLY on GET + recognized on-demand fetcher UA + top-level document path (never static/prefetch/api/trpc); never alters the response; never disturbs Clerk/`isPublicRoute`.

## Phase Completion Rules

- **CODE DONE** when Sections A–E are implemented and all Fully-Automated + Hybrid gates are green.
- **CONDITIONAL** (not VERIFIED) while KG-2 (Vercel `waitUntil` live-delivery confirmation pending — downgraded 25-07-26, host corrected from Cloudflare Pages to Vercel), KG-3 (Gemini UA token unverified), and KG-1 residual (Perplexity/Claude per-vendor WAF allow-status) remain open — deploy/infra-gated, each has a backlog stub; the gate stays CONDITIONAL, never a silent PASS.
- **✅ VERIFIED** only after: (a) all in-blast-radius Fully-Automated + Hybrid gates green (incl. the AC-H5-8 tripwire), (b) regression check confirms no drift in shipped EvalLayer/handoff suites, (c) validate-contract exists, (d) operator completed the Operator Handoff and confirmed a real fetch was captured (user-confirmed working).
- Autonomous program phase: commit + push EXECUTE changes (separate from process/plan commits) after EVL.

## Test Infra Improvement Notes

- **RESOLVED (decision A):** Add Vitest to `apps/web` for the pure `fetch-beacon.ts` matcher. `apps/web` has no JS unit runner today (confirmed — no vitest/vite config, no test script). This unlocks future web unit tests.

---

## Resume and Execution Handoff

1. **Selected plan file path:** `process/features/evallayer/active/handoff_23-07-26/handoff-05-webfetch-capture_PLAN_25-07-26.md`
2. **Last completed step:** VALIDATE (contract written below). No EXECUTE yet.
3. **Validate-contract status:** CONDITIONAL (written 25-07-26; see below).
4. **Next step for a fresh agent:** EXECUTE Sections A→E in order, per-section test gates, honoring the Execute-Agent Instructions in the contract. HIGH-RISK trust-boundary change → produce the manual-first evidence pack (contract §Evidence Pack) before finalize. Autonomous program phase: commit + push after EXECUTE+EVL.

---

## Validate Contract

Status: CONDITIONAL
Date: 25-07-26
date: 2026-07-25
generated-by: outer-pvl
Re-validated: 25-07-26 (PVL cycle-1) — supplement confirmed; 3 actionable concerns resolved (persist event_time param E1, empty-secret 401-before-compare_digest E2 w/ 3 ordered branches, Vitest added #9). No new FAIL/actionable-CONCERN. Terminal gate.

Parallel strategy: sequential (single vc-execute-agent, opus) for EXECUTE
Rationale: signal score 4/7 (S2 API/auth surface, S4 phase-program, S6 high-risk trust boundary, S7 5+ files) = HIGH, but the ~7 source files are strictly ordered and interdependent (config → classifier → persistence → service → router → web → tests) around ONE trust boundary; fragmenting into parallel agents would split the security-critical review. Single sequential opus execute-agent is the correct fit.

Test gates (C3 5-column table — additive; legacy line form retained below):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-H5-1 | on-demand UA writes both rows | Fully-Automated | `pytest tests/unit/test_agent_fetch_beacon.py -k on_demand_writes_both` exits 0 | A |
| AC-H5-2 | index crawler (gptbot) → 204, no write | Fully-Automated | `pytest tests/unit/test_agent_fetch_beacon.py -k index_crawler_noop` | A |
| AC-H5-3 | junk/unknown UA → 204, no write | Fully-Automated | `pytest tests/unit/test_agent_fetch_beacon.py -k junk_ua_noop` | A |
| AC-H5-4 | missing/wrong/empty-configured secret → 401 | Fully-Automated | `pytest tests/unit/test_agent_fetch_beacon.py -k "secret_401 or empty_secret_401"` | B (empty-secret guard added by checklist #7/#13e) |
| AC-H5-5 | flag off → 404 dormant | Fully-Automated | `pytest tests/unit/test_agent_fetch_beacon.py -k flag_off_404` | A |
| AC-H5-6 | unknown site_id → 204, never 403 | Fully-Automated | `pytest tests/unit/test_agent_fetch_beacon.py -k unknown_site_noop` | A |
| AC-H5-7 | token → decoded mint ts on created_at; invalid → receive time | Fully-Automated | `pytest tests/unit/test_agent_fetch_beacon.py -k "token_mint_ts or invalid_token"` | B (requires persist_agent_fetch_event event_time param, checklist #4) |
| AC-H5-8 | zero identity writes; is_emailable_identity untouched | Hybrid | `pytest tests/integration/test_agent_fetch_beacon_integration.py -k tripwire` — precondition: disposable Postgres+Redis up | A |
| AC-H5-9 | google token additive; classifier tests green + tier total | Fully-Automated | `pytest tests/unit -k agent_classifier` | A |
| AC-H5-10 | middleware fires only GET + on-demand UA + top-level doc | Fully-Automated | `apps/web` Vitest: `pnpm --filter web test -- fetch-beacon` (or `npx vitest run apps/web/src/lib/fetch-beacon.test.ts`) | B (Vitest added by checklist #9) |
| live-capture | real fetcher → middleware → waitUntil → row | Agent-Probe / Known-Gap | post-deploy manual probe (ChatGPT/Gemini browse → Agents dashboard) | D (deploy-gated; backlog KG-2) |

gap-resolution legend: A — proven now · B — fixed in this plan (gate added by this plan's checklist) · C — deferred to a named later phase · D — backlog test-building stub (named residual; keep-active; continue).

C-4 reconciliation: the `strategy` column carries ONLY the 3 proving strategies (Fully-Automated / Hybrid / Agent-Probe). Known-Gap is a named residual (gap-resolution D), never a strategy.

Legacy line form (retained for existing validate-contract consumers):
- API endpoint unit: Fully-automated: `pytest tests/unit/test_agent_fetch_beacon.py`
- classifier additive: Fully-automated: `pytest tests/unit -k agent_classifier`
- API endpoint integration: hybrid: `pytest tests/integration/test_agent_fetch_beacon_integration.py` + precondition: disposable Postgres+Redis up
- web matcher: Fully-automated: `npx vitest run apps/web/src/lib/fetch-beacon.test.ts` (Vitest added this phase)
- web e2e: agent-probe: extend `apps/web/e2e/agents.spec.ts`, assert normal auth/render unaffected
- live capture: known-gap: documented — deploy-gated (KG-2), post-deploy manual probe

Failing stub (AC-H5-1):
```
def test_on_demand_ua_writes_both_rows():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: on-demand fetcher UA writes one agent_visit + one agent_fetch_event")
```
Failing stub (AC-H5-4 empty-secret):
```
def test_empty_configured_secret_returns_401():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: empty configured secret must 401 BEFORE hmac.compare_digest (compare_digest('','')==True bypass)")
```
Failing stub (AC-H5-6):
```
def test_unknown_site_id_returns_204_never_403():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: unknown/foreign site_id → 204 no-op, never 403 (no id-existence leak)")
```
Failing stub (AC-H5-7):
```
def test_token_decodes_to_mint_timestamp_on_created_at():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: valid /pricing-overview/{token} → decoded mint ts on agent_fetch_event.created_at; invalid token → server-receive time")
```
Failing stub (AC-H5-9):
```
def test_google_vendor_additive_keeps_classify_tier_total():
    raise NotImplementedError("NOT IMPLEMENTED — TDD stub: additive google vendor leaves classify_tier total over all tokens; existing classifier tests green")
```

Dimension findings:
- Infra fit: CONCERN — endpoint mounts cleanly at `/api/v1/agents` (main.py:281); config EvalLayer flag block + tables already exist (no migration); `ev.waitUntil` available in `middleware(req, ev)`. BUT `apps/web` has no JS unit runner today → Vitest must be added (decision A, checklist #9); web app host CORRECTED 25-07-26 to Vercel (not Cloudflare Pages) — Vercel Edge Middleware supports `waitUntil` natively, so KG-2 is downgraded to a live-delivery confirmation residual only.
- Test coverage: CONCERN — strong Fully-Automated unit tier + Hybrid integration incl. the AC-H5-8 identity tripwire (correct min tier for an identity-adjacent surface); web matcher gate depends on the Vitest add; integration is Docker/PG-gated (KG-4). No developed behavior rests on Known-Gap alone → net gate not vacuously green.
- Breaking changes: CONCERN — new endpoint + classifier edits are purely additive (no existing contract changed), BUT the plan's original Touchpoints "reuse `persist_agent_fetch_event` unchanged / no edit" was FALSE: `created_at` is `Base.server_default=func.now()`, so AC-H5-7 mint-time REQUIRES a small additive `event_time` param on that function (now corrected in the plan). Umbrella "Google-Extended out of scope" needs UP reconciliation.
- Security surface: CONCERN — trust-boundary primitive is correct (shared secret + `hmac.compare_digest` + default-OFF + dormant-when-secret-absent + 404-not-revealed + 204-not-403 tenancy). VALIDATE CONFIRMED `hmac.compare_digest('','') == True` → an empty configured secret would ACCEPT an empty header (auth bypass) unless guarded — mandatory explicit empty-secret 401 BEFORE the compare (E2). No endpoint rate-limiting (poisoning bounded to non-identity dashboard rows) → backlog follow-up. Keys-only logging must be enforced in the new service (no raw UA/IP).
- Section A (config + classifier): PASS — anchors accurate (`_VENDOR_TOKENS` L23, `_ON_DEMAND_TOKENS` L46, `classify_tier` L51); additive google vendor safe; conservative default-index resolves R-5/KG-3.
- Section B (endpoint + service): CONCERN — mechanically feasible (Site-lookup pattern reusable from events.py:126); highest-risk edits = empty-secret guard (E2) + the persist `event_time` edit (E1); route-order POST-vs-GET safe.
- Section C (web middleware + beacon): CONCERN — feasible; matcher MUST exclude api/trpc (middleware runs for them per `config.matcher`); beacon must stay outside the Clerk callback; host CORRECTED to Vercel — deploy-gated KG-2 (downgraded: Vercel supports waitUntil natively, residual is live-delivery confirmation only).
- Section D (tests): CONCERN — feasible once Vitest added; AC-H5-8 tripwire must be non-vacuous (real DB, real POST, assert zero identity rows).
- Section E (docs/registry/closeout): PASS — registry claim + umbrella reconciliation + operator handoff are documentation tasks.

Execute-Agent Instructions (follow during EXECUTE):
- E1: `persist_agent_fetch_event` MUST gain an optional `event_time: datetime | None = None` param and set `created_at=event_time` when provided (the plan's original "no edit" claim was wrong). Do NOT skip — AC-H5-7 is unsatisfiable otherwise. Add a unit assertion that a provided mint-time lands on `created_at`.
- E2: In `_verify_beacon_secret`, guard `if not settings.beam_fetch_beacon_secret: raise 401` BEFORE any `hmac.compare_digest` call. Confirmed hazard: `hmac.compare_digest('','') == True`. Add the empty-secret 401 regression test (checklist #13e).
- E3: The new `agent_fetch_beacon.py` service MUST import ZERO identity/Visitor module. Log keys/vendor/site_id only — never the raw UA or IP (PII/GDPR). The AC-H5-8 integration tripwire must be non-vacuous.
- E4: The web matcher MUST exclude `/api`, `/trpc`, `_next`, static extensions, and `?_rsc` prefetch markers (middleware runs for api/trpc per `config.matcher`). Keep the beacon side-effect OUT of the `clerkMiddleware` callback and never let it alter the returned response.
- E5: Google/Gemini token is conservative — add the `google` vendor but keep its token index-tier unless a specific token is CONFIRMED user-driven from live logs. Never mislabel a crawler as on-demand.
- E6: Confirm cross-phase blast-radius disjointness via `phase-blast-radius-registry.md` before editing `middleware.ts` / `agent_classifier.py` / `agents.py` / `agent_visit_persistence.py` (all prior claimants H1–H4 are DONE).
- E7 (HIGH-RISK trust boundary — manual-first evidence pack): before reporting DONE, produce the 5-artifact evidence pack in `{task_folder}/harness/` — `risk-gate.json` (riskClass: "permission, secret, or trust-boundary logic"), `context-snippets.json` (the auth dep + empty-secret guard + persist edit), `verification.json` (401 happy + empty-secret + wrong-secret boundary cases), `review-decision.json` (explicit APPROVE/REJECT), `adversarial-validation.json` (forged POST, empty-secret bypass, replayed secret, on-demand mislabel scenarios ruled out). Do not treat the work as finalize-ready until the pack exists and the reviewer decision is recorded.

Open gaps:
- Endpoint rate-limiting is a follow-up (R-1): known-gap: documented — see backlog/handoff-05-fetch-beacon-rate-limit_NOTE (create at EXECUTE/UP). Poisoning blast radius is bounded to non-identity agent_visits/agent_fetch_events rows.

Known Gaps (pre-classified — excluded from CONCERN/FAIL count; carried as residuals):
- KG-1 residual: per-vendor WAF allow-status for Perplexity-User / Claude-User unverified (ChatGPT/OAI + Gemini/Google PROVEN reaching origin live 25-07-26). known-gap: documented.
- KG-2 (DOWNGRADED 25-07-26 — host correction): web app is Vercel, not Cloudflare Pages; Vercel Edge Middleware supports `event.waitUntil` natively. known-gap: documented — residual is confirming live beacon delivery post-config/redeploy — backlog stub handoff-05-cfpages-waituntil-verification_NOTE (reframed for Vercel).
- KG-3: exact live Gemini/Google on-demand fetch UA token unverified. known-gap: documented — backlog stub handoff-05-gemini-ua-token-unverified_NOTE.
- KG-4: integration tests Docker/PG-gated (disposable Postgres only). known-gap: documented.

What this coverage does NOT prove:
- Fully-Automated unit gates prove request/response contract + classify gating + auth + tenancy + token decode in-process; they do NOT prove real DB persistence (that is AC-H5-8 Hybrid) nor real edge-runtime delivery.
- The AC-H5-8 Hybrid tripwire proves no identity rows are written against a real Postgres; it does NOT prove behavior on the production DB, nor under concurrent load.
- The Vitest matcher truth table proves the pure UA/path decision; it does NOT prove the middleware actually fires under the live Vercel Edge runtime (KG-2, downgraded — Vercel supports `waitUntil` natively) nor that a real fetcher UA reaches the origin for every vendor (KG-1 residual for Perplexity/Claude).
- No gate proves end-to-end live capture (fetcher → Vercel middleware → waitUntil beacon → row) — that is the deploy-gated Known-Gap requiring the operator's post-deploy manual probe.

Gate: CONDITIONAL (TERMINAL, cycle-1 accepted; no FAILs; 3 actionable concerns resolved; developed behavior proven by Fully-Automated + Hybrid gates; only pre-accepted deploy/infra-gated known-gaps KG-1..KG-4 remain — deliberately CONDITIONAL per Phase Completion Rules, never a silent PASS)
Accepted by: session (autonomous, /goal execution) — accepted concerns: [web-runner-Vitest-add (resolved in-plan, checklist #9), persist-event_time-edit (E1), empty-secret-401-guard (E2), endpoint-rate-limit-deferred (backlog), gemini-UA-conservative-token (E5/KG-3)]

### Evidence Pack (HIGH-RISK — required before EXECUTE reports DONE)
Location: `process/features/evallayer/active/handoff_23-07-26/handoff-05-webfetch-capture_25-07-26/harness/` (create at EXECUTE). 5 artifacts per vc-risk-evidence-pack (risk class: permission/secret/trust-boundary). Auto-stop: do not finalize until the pack exists and review-decision.json records APPROVE.
