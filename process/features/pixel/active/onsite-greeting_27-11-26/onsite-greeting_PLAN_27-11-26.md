---
name: plan:onsite-greeting
description: "COMPLEX plan — company-level on-site greeting: config, public cache-only endpoint, lazy pixel snippet, e2e"
date: 27-11-26
feature: pixel
---
# On-site Greeting — PLAN (COMPLEX)

Complexity: COMPLEX
Status: PLANNED (validate CONDITIONAL — supplement cycle 3 applied — revalidate)

## Overview
Gap #5 of inbound-playbook: today tracker.js only renders a consent banner. Add tasteful company-level greeting for org-resolved visitors.

## Acceptance Criteria
AC-1..AC-9 as defined in onsite-greeting_SPEC_27-11-26.md, with these PVL cycle-1 overrides (SPEC numbers were wrong vs the repo):
- AC-6 (override, Gap 4): `tracker.min.js` stays **< 6144 B gzipped** (binding asserts `tests/unit/test_pixel.py:202`, `tests/unit/test_pixel_fingerprint.py:368`; today 6,022 B). Projected size after change: 6,090–6,112 B, so a ≥6100 abort would self-trip (cycle-2 Gap 6). Lean-loader target: loader adds **≤ +70 B gzipped**. EXECUTE aborts and reports at **≥ 6130 B**, with a written reason in the phase report. Raw source `apps/pixel/src/tracker.js` stays **< 36000 B** (`test_pixel.py:174`; today 35,800). Raising the raw cap is allowed only with a written reason in the test comment + phase report.
- AC-5 (addition, Gap 5): responses carry `Cache-Control: no-store`; a request whose `Origin` host differs from the `Site.url` host returns `{"show":false}`.
- AC-1 (addition, Gap 3): a hit with a domain but no company name returns `{"show":false}`.

## Phase Completion Rules
CODE DONE = checklist complete + G1,G3,G6 green. VERIFIED = G2,G4,G5 green with flag ON + evidence pack.

TL;DR: new migration (site greeting cols) + `GET /api/v1/greeting` public cache-only endpoint + separate `greeting.min.js` lazy-loaded by tracker after consent; default OFF at two layers.

## Decision Summary
### Chosen Approach
Server-decides, lazy snippet — tracker loader (+68–90 B gzipped; lean target ≤ +70 B, budget < 6144 B gz) injects `greeting.js` only when `data-greeting="on"` AND consent granted AND !OPTOUT; snippet calls endpoint, renders textContent badge.
### Why This Over Alternatives
| Alternative | Why Rejected |
|---|---|
| Inline in tracker.js | Breaks the < 6144 B gz budget (today 6,022 B) |
| Piggyback on ingest response | Ingest is 204/hot-write path; couples latency + leaks on ingest |
| Client-side company lookup (ipinfo from browser) | Paid key exposure, no org_kind gate |
### Risk Predictions
- Security: endpoint becomes an IP→company oracle → return only owner-templated text, require enabled site, rate limit, only `org` kind.
- Privacy: consent bypass → load gated in tracker AND server rechecks do_not_resolve via `v` (visitor_id).
- Perf: DB lookups on page load → Redis caches ONLY the per-IP company lookup (`greeting_company:{ip}`, 1h); the show decision is never cached; ip_org GiST 3–15 ms acceptable.
- Product: creepy factor → dismissible, remembered 30 d in localStorage, owner copy.
- Ops: flag-OFF-only vacuity (prior lesson) → flag-ON gate mandatory.
### Key Constraints Accepted
Company display name only; no paid calls; two-layer default OFF.

## Touchpoints
- NEW `apps/api/routers/greeting.py` — `GET /api/v1/greeting?site_id=&v=`
- NEW `apps/api/services/greeting.py` — eligibility + cache-only company read. Allowed reads ONLY: Redis `ip_privacy:{ip}` (direct GET, no helper), `lookup_ip_org` (org_kind='org'). FORBIDDEN: `resolve_company_cached`, `check_ip_privacy`, ipinfo, PDL, rDNS (they do live calls + writes — Gap 2).
- `apps/api/config.py` — `onsite_greeting_enabled: bool = False`
- `apps/api/models/site.py` — `greeting_enabled` bool default false, `greeting_templates` JSONB nullable
- NEW migration — chain off `alembic heads` at EXECUTE time (do NOT hardcode down_revision). **Coordinate with `pixel`-sibling task `campaigns-outreach/active/signal-creative-cta_27-11-26/`, which also adds `Site` columns:** run `alembic heads` (DSN pinned to localhost:5433/disposable) immediately before writing the file; if two heads appear, stop and report — never create a merge revision without orchestrator approval (Gap 7).
- `apps/api/main.py` — include router; add path to `PixelCORSMiddleware._PIXEL_PATHS` (wildcard origin, no credentials — U2) + `/pixel/greeting.js` static route mirroring `serve_pixel()` (`main.py:612`)
- `apps/api/routers/sites.py` + `apps/api/schemas/` — authed owner update of greeting fields (tenant-scoped `Site.user_id`); `cta_url` goes through a NEW https-only wrapper around `validate_booking_url` (`apps/api/schemas/sites.py:20`): call it, then reject any scheme other than `https` (it allows http today). Gap 7 cycle 2.
- `apps/pixel/src/tracker.js` — after consent block (~line 634) lazy-load when eligible; also on `decideConsent("g")`
- NEW `apps/pixel/src/greeting.js` + `apps/pixel/package.json` build step producing `greeting.min.js`
- Tests: NEW `tests/unit/test_greeting_service.py`, NEW `tests/integration/test_greeting_endpoint.py`, NEW `apps/pixel/e2e/greeting.spec.ts`; existing `tests/unit/test_pixel_fingerprint.py`, `tests/unit/test_pixel.py` (size); pixel e2e harness route for `**/pixel/greeting.js`
- Dashboard settings UI: OUT of v1 (U3) — backlog NOTE `process/features/pixel/backlog/onsite-greeting-settings-ui_NOTE_27-11-26.md` (written at EXECUTE/UPDATE PROCESS, not by this plan).

### Production enable preconditions (Gap 7 — operator steps, NOT executed by this plan)
1. KG-1: observe the real Railway proxy hop count and set `trusted_proxy_hops` accordingly (see Ingest Abuse Hardening rollout order in all-context.md); until then every request shares one client IP → wrong company + one global 30/min bucket.
2. KG-2: run `process/features/visitors-identity/active/ip-org-database_07-08-26/ip-org-prod-enable_RUNBOOK_07-08-26.md` (prod `ip_org_prefixes` ingest + `ip_org_lookup_enabled`); until then show is always false in prod.
3. Re-check after `cloudflare-migration` lands (proxy headers change → re-derive hop count).
4. Only then flip `onsite_greeting_enabled`, then per-site `greeting_enabled`.

## Public Contracts
- `GET /api/v1/greeting?site_id=<string ≤50>&v=<optional, ≤100 chars>` (`Site.id` public id is `String(50)`, not a UUID — Gap 3) → `200 {"show":false}` or `{"show":true,"template_id":"default","text":"...","cta_url":"https://..."|null}`. Response key allow-list is exactly these keys.
- `v` (Gap 3 cycle 2): optional, ≤100 chars (longer → show:false); looked up by `(site_id, visitor_id)`; unknown/absent `v` → proceed with IP-only checks. `v` is client-controlled and ADVISORY: it can only suppress a greeting (do_not_resolve/bot/abuse), never unlock one.
- Origin compare (Gap 2 cycle 2): normalize both `Origin` and `Site.url` — add `https://` if `Site.url` is schemeless (`apps/api/schemas/sites.py:45` allows that), parse host, lowercase, drop port, drop one leading `www.`; exact string match only (no suffix/subdomain match). `Origin` missing or literal `null` → show:false.
- Status codes (Gap 8 cycle 2): 200 always, except 429 for rate limit only. `greeting.js` ignores any non-200 response (renders nothing).
- Always `Cache-Control: no-store` (Gap 5).
- `show:false` (never 4xx other than 429, never a reason code in body) when: unknown site, disabled site/flag, `Origin` header missing or host ≠ host of `Site.url` (anti-oracle, Gap 5), visitor `v` is do_not_resolve/bot-suspect/abuse-flagged (site-scoped), privacy-relay IP, cached `ip_privacy:{ip}` says VPN/proxy, org_kind ≠ 'org', or no company NAME (domain-only → show:false, Gap 3).
- Company name source (Gap 3; Gap 4 cycle 2): ONLY `lookup_ip_org(ip).org_name` with org_kind='org'. The `company_graph` name fallback is DROPPED (unreachable: when ip_org has no 'org' hit there is no gate, and when it has one it already carries the name). Redis `company_ip:` domain is never displayed. `lookup_ip_org` no-ops unless `ip_org_lookup_enabled` is ON (`apps/api/services/ip_org_lookup.py:66`).
- CORS: wildcard origin, no credentials, no cookies (U2 provisional).
- Site PATCH accepts `greeting_enabled`, `greeting_templates` ({default:{text,cta_url}}) — v1 default template only (U4 provisional; no `by_industry`), validated: text ≤200, only `{company}` placeholder, cta_url https only.
- Script attr `data-greeting="on"` on tracker tag.

## Blast Radius
~12 files, packages: apps/api, apps/pixel, tests. Risk class: HIGH (public API contract, trust boundary, schema migration).

## Implementation Checklist
(Supersedes the Risk Predictions line "cache result per (site, ip)" — see step 2b.)
1. config flag; model columns; migration (chain off live `alembic heads` with DATABASE_URL pinned localhost:5433/disposable; stop if 2 heads — signal-creative-cta coordination).
2. `services/greeting.py` `decide_greeting(db, redis, site, ip, origin, vid)` → (show, reason, payload):
   a. Per request, never cached: global flag, `site.greeting_enabled`, normalized Origin == normalized `Site.url` host (Public Contracts rule; missing/`null` → false), `v` ≤100 chars, visitor checks by `vid` scoped to site (do_not_resolve / is_bot_suspect / is_abuse_flagged), `is_privacy_relay_ip(ip)`.
   b. Cache ONLY the IP→company lookup at Redis `greeting_company:{ip}` (1h; value = name + org_kind or a negative marker). Never cache the show decision keyed by (site, ip) (Gap 1).
   c. Privacy: GET `ip_privacy:{ip}` directly, `json.loads` the value, evaluate with `is_proxy_or_vpn()` (`apps/api/services/company_resolver.py:253`); true → show:false; malformed JSON / wrong shape → treat as miss; miss → skip live check and rely on org_kind='org' (U1 provisional). Never call `check_ip_privacy` (Gap 2).
   d. Company: `lookup_ip_org(ip)` must return org_kind='org'; name = its org_name; no name → show:false (no company_graph fallback). Never call `resolve_company_cached`, ipinfo, PDL, rDNS (Gap 2).
   e. Render default template only; sanitize company via `clean_text`-style strip; text ≤200.
3. `routers/greeting.py`: limiter 30/min per IP + per-site; `resolve_client_ip`; set `Cache-Control: no-store`; structlog `greeting_decided site_id reason show` only.
4. CORS (wildcard, no credentials) + `/pixel/greeting.js` static route.
5. Sites PATCH schema + validation: `cta_url` via new https-only wrapper around `validate_booking_url` (`schemas/sites.py:20`).
6. `greeting.js`: `fetch` WITHOUT credentials, ignore any non-200, `?site_id=&v=<visitorId>`; fixed-position dismissible badge via textContent; dismiss → localStorage 30 d.
7. tracker.js loader: minified-style short names, no comments, append `<script>` to `document.head` with `?v=`; guarded `!OPTOUT && !consentBlocked() && consentDecision==="g"` and attr on; also fires from `decideConsent("g")`. Rebuild min; measure gzip before/after: target loader ≤ +70 B; must be < 6144, abort+report at ≥ 6130 with written reason; raw source < 36000 (raise only with written reason).
8. Pixel e2e harness: route `**/pixel/greeting.js` → `apps/pixel/src/greeting.js`, stub `**/api/v1/greeting`.
9. Tests (below). Mock mode: MOCK_EXTERNAL_APIS returns deterministic "Acme" for test IP.

## Verification Evidence
| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| G1 `pytest tests/unit/test_greeting_service.py -q` — eligibility matrix; same IP: visitor A shows, then do_not_resolve visitor B on same IP → show:false (cache-key proof); domain-only → show:false; Origin normalization cases (schemeless Site.url, uppercase, port, `www.`, subdomain mismatch, `null`, missing); `v` >100 chars, unknown `v` proceeds; `ip_privacy:` JSON VPN → false, malformed → miss; `resolve_company_cached`/`check_ip_privacy`/ipinfo/PDL/rDNS monkeypatched to raise | Fully-Automated | AC-1,3,4,7 |
| G2 `DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test pytest tests/integration/test_greeting_endpoint.py -q` — flag-ON run sets BOTH `onsite_greeting_enabled` AND `ip_org_lookup_enabled` (else `lookup_ip_org` no-ops, `ip_org_lookup.py:66`, and the gate is vacuous); seed an `ip_org_prefixes` row org_kind='org', inject a PUBLIC client IP (ASGITransport default is private), flag-ON asserts `show:true` at least once (non-vacuous); flag-OFF; key allow-list; `Cache-Control: no-store`; Origin mismatch/missing → show:false; unknown site → show:false; 429 on rate limit only | Hybrid (PG+Redis) | AC-1,2,5,8 |
| G3 `pytest tests/unit/test_pixel_fingerprint.py tests/unit/test_pixel.py -q` (< 6144 gz, < 36000 raw) | Fully-Automated | AC-6 |
| G4 `cd apps/pixel && npx playwright test e2e/greeting.spec.ts --project=chromium` — harness routes `**/pixel/greeting.js` → src/greeting.js; shown; consent-pending/declined/GPC/flag-off none; greeting.js never requested when off | Hybrid (browser) | AC-3,6,9 |
| G5 migration up/down/up on disposable postgres:16 | Hybrid | schema safety |
| G6 caplog assert no company/IP/domain/vid in logs | Fully-Automated | AC-8 |
| G7 full unit + integration regression | Hybrid | no regression |
| G8 `node .claude/skills/vc-risk-evidence-pack/scripts/validate-risk-artifacts.mjs process/features/pixel/active/onsite-greeting_27-11-26/harness` — zero failures, 5 canonical artifacts present | Fully-Automated | evidence pack (VERIFIED rule) |

## Open User Decisions
All PROVISIONAL defaults below are **pending user confirmation**; EXECUTE uses them unless the user overrides.
- U1 (pending user confirmation): `ip_privacy:` cache miss → skip live privacy check, rely on org_kind='org'.
- U2 (pending user confirmation): no cookies/credentials; tracker sends first-party visitor id as `?v=`; wildcard CORS.
- U3 (pending user confirmation): API-only settings in v1; backlog NOTE `process/features/pixel/backlog/onsite-greeting-settings-ui_NOTE_27-11-26.md`.
- U4 (pending user confirmation): no per-industry templates in v1; default template only.

## High-Risk Evidence Pack (vc-risk-evidence-pack)
Required before closeout, written to the task folder's `harness/`. Canonical artifacts (names read by `.claude/skills/vc-risk-evidence-pack/scripts/validate-risk-artifacts.mjs:34-51`):
| # | Canonical artifact | Required fields |
|---|---|---|
| 1 | `harness/risk-gate.json` | task, planPath, riskLevel=`high`, riskClasses=[public-api, schema-migration, privacy/trust-boundary], mustStopBeforeFinalize=true, humanApprovalRequired=true, why |
| 2 | `harness/context-snippets.json` | task (+ cited plan/contract excerpts) |
| 3 | `harness/verification.json` | task, commands (G1–G7 exact commands + exit codes), manualChecks, result |
| 4 | `harness/review-decision.json` | task, decision ∈ approved/approved-with-concerns/rejected (auto-stop human review home), blockingFindings, nonBlockingFindings, notes |
| 5 | `harness/adversarial-validation.json` | adversarial scenarios + rollback note (both flags OFF = zero behavior; downgrade drops 2 cols) |

Supporting inputs (raw evidence, referenced from `verification.json` commands/manualChecks — not substitutes for canonical files): `harness/contract-evidence.json` (allow-list + no-store output), `harness/consent-matrix.json` (consent/GPC/do_not_resolve e2e log), `harness/no-paid-call.json` (provider mocks raising), `harness/migration-roundtrip.json` (up/down/up log).

Adversarial scenarios in `adversarial-validation.json` (each: attack, expected, observed, gate): Origin spoof (forged/mismatched/`null` Origin → show:false; note: Origin is browser-enforced only, curl can forge it — accepted, output is owner copy only); `v` spoof (forged `v` can only suppress, never unlock); IP→company oracle probing (only owner template text returned, rate limit 429, org_kind gate); cross-visitor cache (only per-IP company cached, show decision recomputed — G1 visitor A/B test); consent bypass (loader gated client-side; server rechecks `v` do_not_resolve).

## Test Infra Improvement Notes
(none identified yet) — note: pixel e2e harness must stub `/api/v1/greeting`; Clerk auth harness gap means owner-settings UI untested (UI out of scope).

## Resume and Execution Handoff
1. Plan: this file. 2. Last step: PVL supplement cycle 3 applied; re-validation pending (VALIDATE is NOT done). 3. Validate-contract: written below, CONDITIONAL, generated-by outer-pvl — stale until re-run. 4. Context: `process/context/all-context.md`, `process/context/tests/all-tests.md`, `process/features/pixel/_GUIDE.md`. 5. Next: re-spawn vc-validate-agent from V1; EXECUTE only after a PASS verdict or accepted CONDITIONAL.

## Validate Contract

Status: PASS
Date: 27-11-26
date: 2026-11-27
generated-by: outer-pvl
supersedes: 2026-11-27 (outer-pvl) — outer PVL has current evidence (re-run from V1 after PVL supplement cycle 3)

Parallel strategy: sequential (dimensions run INLINE — validate subagent had no Agent tool; deviation recorded)
Rationale: signal score 4/7 (S1 multi-package, S2 schema/API, S6 high-risk class, S7 ~12 files). EXECUTE: one opus vc-execute-agent, order migration → service → router/CORS → Site PATCH → pixel; loader + greeting.js share the byte budget, never split across agents.

### Cycle-3 gap closure (verified against code, 27-11-26, HEAD 6ef19f7)
- R1 stale lines — CLOSED: header Status now reads "supplement cycle 3 applied — revalidate"; Risk Predictions says "rechecks do_not_resolve via `v` (visitor_id)" (no "svid" left above this contract); the literal gate-pass token appears 0 times above this contract; Resume line now says "EXECUTE only after a PASS verdict or accepted CONDITIONAL".
- R2 evidence pack — CLOSED: plan table names exactly the files `validate-risk-artifacts.mjs` reads (`:34-38`: risk-gate, context-snippets, verification, review-decision, adversarial-validation) with every required field (`:40-51`: risk-gate task/planPath/riskLevel/riskClasses/mustStopBeforeFinalize/humanApprovalRequired/why; context-snippets task; verification task/commands/manualChecks/result; review-decision task/decision/blockingFindings/nonBlockingFindings/notes). Value checks match: riskLevel `high` (`:53`), riskClasses array (`:57`), commands/manualChecks arrays (`:61,65`), decision enum (`:69`). Auto-stop review home = `review-decision.json`. G8 now runs the validator. The 4 raw files are explicitly supporting inputs, not substitutes.
- Regression scan of N2–N8 anchors — PASS: `Site.url` String(500) (`models/site.py:18`); `visitor_id` String(100) (`visitor.py:27`); `validate_booking_url` (`schemas/sites.py:20`); `lookup_ip_org` inert when flag off (`ip_org_lookup.py:65-66`); `is_proxy_or_vpn` (`company_resolver.py:253`), `is_privacy_relay_ip` (`:233`); `_PIXEL_PATHS` (`main.py:192`); `serve_pixel` decorator `main.py:612`; size asserts `test_pixel.py:174,202`, `test_pixel_fingerprint.py:368`; re-measured `tracker.min.js` 6,022 B gz, `tracker.js` 35,800 B raw. No source drift since cycle 2 (HEAD unchanged, no tracked diffs in apps/ or tests/). Plan validator: 0 FAIL, 0 WARN.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1,3,4,7 | eligibility matrix incl. Origin null/missing/mismatch/normalization (schemeless, case, port, `www.`, subdomain), `v` missing/unknown/over-length, privacy JSON (vpn/tor/hosting → false, relay alone → no block, malformed → miss), org-only name, domain-only → false, same-IP visitor A/B cache proof, zero provider calls, template sanitize | Fully-Automated | G1 `.venv/bin/pytest tests/unit/test_greeting_service.py -q` (precondition: Python 3.11 venv from root `requirements.txt` — none in this shell) | B |
| AC-1,2,5,8 | endpoint flag-OFF + flag-ON (both `onsite_greeting_enabled` AND `ip_org_lookup_enabled` ON, `mock_external_apis` False, seeded `ip_org_prefixes` org row, ASGITransport `client=("203.0.113.5", 1234)`, ≥1 observed `show:true`), key allow-list, no-store, Origin missing/null/mismatch, unknown site, 429 | Hybrid | G2 `DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test .venv/bin/pytest tests/integration/test_greeting_endpoint.py -q` — precondition: PG :5433 + Redis :6379 up (`lsof -nP -iTCP -sTCP:LISTEN \| grep -E '5433\|6379'`); never the repo env-file DSN (Supabase prod) | B |
| AC-6 | tracker.min.js < 6144 B gz, source < 36000 B, min fresh | Fully-Automated | G3 `.venv/bin/pytest tests/unit/test_pixel_fingerprint.py tests/unit/test_pixel.py -q` | B |
| AC-3,6,9 | shown / consent-pending / declined / GPC / attr off (greeting.js never requested) / non-200 ignored / dismiss persisted | Hybrid | G4 `cd apps/pixel && npx playwright test e2e/greeting.spec.ts --project=chromium` — precondition: harness routes `**/pixel/greeting.js` and stubs `**/api/v1/greeting` | B |
| schema | migration up/down/up on empty disposable postgres:16 | Hybrid | G5 `scripts/e2e-disposable.sh` lane or throwaway `postgres:16-alpine`, DSN pinned to it | B |
| AC-8 | no company/IP/domain/vid in logs | Fully-Automated | G6 caplog assertion inside G1 + G2 | B |
| regression | unit + integration lanes unchanged | Hybrid | G7 `.venv/bin/pytest tests/unit -q` + `.venv/bin/pytest tests/integration -q` (same PG/Redis precondition) | A |
| high-risk pack | canonical 5-artifact pack valid | Fully-Automated | G8 (run from repo root) `node .claude/skills/vc-risk-evidence-pack/scripts/validate-risk-artifacts.mjs process/features/pixel/active/onsite-greeting_27-11-26/harness` — exit 0 AND `failures` [] AND `warnings` [] | B |

Failing stub (G1):
test("should return show:false when Origin is null or host differs from normalized Site.url host", () => { throw new Error("NOT IMPLEMENTED — TDD stub: Origin edge cases") })
test("should return show:false for visitor B on the same IP after visitor A was shown", () => { throw new Error("NOT IMPLEMENTED — TDD stub: per-IP-only cache") })
test("should return show:false and make zero provider calls when visitor do_not_resolve", () => { throw new Error("NOT IMPLEMENTED — TDD stub: eligibility matrix + zero provider calls") })
Failing stub (G3):
test("should keep tracker.min.js under 6144 B gzipped after the greeting loader", () => { throw new Error("NOT IMPLEMENTED — TDD stub: pixel budget with loader") })
Failing stub (G6):
test("should log only site_id, show and reason for greeting_decided", () => { throw new Error("NOT IMPLEMENTED — TDD stub: no PII in greeting logs") })
Failing stub (G8):
test("should pass validate-risk-artifacts on harness/ with zero failures and zero warnings", () => { throw new Error("NOT IMPLEMENTED — TDD stub: canonical evidence pack") })

Known-Gap residual rows (named, NOT proving strategies; not blockers):
- KG-1 prod client-IP correctness (`trusted_proxy_hops` = 0) — D: production enable precondition.
- KG-2 prod `ip_org_prefixes` empty + `ip_org_lookup_enabled` OFF — D: production enable precondition.
- KG-3 webkit/firefox G4 legs if binaries not cached — C.

Legacy line form:
- greeting service: Fully-automated: `.venv/bin/pytest tests/unit/test_greeting_service.py -q`
- greeting endpoint: hybrid: `.venv/bin/pytest tests/integration/test_greeting_endpoint.py -q` + local PG/Redis, both flags ON
- pixel size: Fully-automated: `.venv/bin/pytest tests/unit/test_pixel_fingerprint.py tests/unit/test_pixel.py -q`
- pixel e2e: hybrid: `cd apps/pixel && npx playwright test e2e/greeting.spec.ts` + harness routes
- migration: hybrid: up/down/up on disposable postgres:16
- evidence pack: Fully-automated: `node .claude/skills/vc-risk-evidence-pack/scripts/validate-risk-artifacts.mjs process/features/pixel/active/onsite-greeting_27-11-26/harness`
- prod IP + prod data: known-gap: documented (KG-1, KG-2)

Dimension findings:
- Infra fit: PASS — serving path, CORS, limiter, ip_org model re-verified; KG-1/KG-2 are production enable preconditions; env preconditions (no .venv / Python 3.11, PG/Redis may be down) documented.
- Test coverage: PASS — G1/G2 cover Origin, `v`, privacy JSON, both flags, non-vacuous show:true; G8 runs the canonical pack validator.
- Breaking changes: PASS — additive columns/fields/route; sibling migration coordination recorded (no hardcoded down_revision).
- Security surface: PASS — gates sound; evidence pack mapped 1:1 to the canonical validator (R2 closed).
- Section A — Backend service + router: PASS — anchors unchanged since cycle 2.
- Section B — Pixel loader + greeting.js: PASS — 6,022 B gz / 35,800 B raw re-measured; consent gating matches tracker.
- Section C — Migration + Site settings: PASS — https wrapper planned; validator anchor correct.
- Section D — High-Risk Evidence Pack: PASS — names + required fields + value checks match `validate-risk-artifacts.mjs:34-71`.
- Plan hygiene: PASS — R1 closed; gate-pass literal absent above this contract.

Open gaps: none blocking. Named residuals KG-1, KG-2, KG-3 (production/env preconditions). User decisions U1–U4 remain provisional defaults (pending user confirmation; EXECUTE uses them unless overridden) — not blockers.
What This Coverage Does NOT Prove:
- G1: real Redis/DB behavior; display quality of raw RIR org names (e.g. "AMAZON-02").
- G2: prod XFF/proxy behavior (KG-1), prod data (KG-2), multi-instance rate-limit sharing.
- G3: loader runtime correctness (bytes + freshness only).
- G4: real customer CSP/z-index, CMPs other than `window.beamConsent`, webkit/firefox if not cached.
- G5: prod data volume during the Railway auto-applied migration.
- G6: logs from code outside the greeting service/router.
- G7: behavior of paths no existing test covers.
- G8: artifact shape only — not that the recorded evidence is true.
- Nobody proves "not creepy" — product judgment at owner dogfood.
Gate: PASS (no FAILs, no CONCERNs; plan updated through supplement cycle 3)
Accepted by: session (outer-pvl re-run after cycle 3) — PASS, no concerns to accept; KG-1/KG-2/KG-3 and provisional U1–U4 recorded as non-blocking preconditions.

Execute-agent instructions:
- E1 Measure gz with `gzip.compress` before/after; binding < 6144; abort + report at ≥ 6130; raw < 36000 (raise only with written reason).
- E2 `alembic heads` only with DATABASE_URL pinned to localhost:5433/disposable; stop on two heads.
- E3 Never call ipinfo, PDL, rDNS, `resolve_company_cached`, `check_ip_privacy`; read `ip_privacy:{ip}` directly and judge with `is_proxy_or_vpn()`.
- E4 Flag-ON G2 mandatory with both flags ON, `mock_external_apis` False, and ≥1 observed `show:true`.
- E5 Cache only `greeting_company:{ip}`; site/Origin/visitor checks per request.
- E6 Never `docker exec` shared containers; G5 disposable only.
- E7 Per-site limit: `site_limiter.limiter.hit(item, "site_greeting", site_id)` with its own scope (`rate_limiter.py:60-86`), not the ingest scope and not gated on `site_ingest_limit_enabled`.
- E8 Any MOCK_EXTERNAL_APIS "Acme" branch may only replace step 2d (company lookup), AFTER all 2a–2c gates; it must never short-circuit eligibility.
- E9 `tests/conftest.py:178` sets `limiter.enabled = False`; the G2 429 case must enable + reset it locally (precedent `tests/integration/test_demo_canary_public.py:269-281`) and reset the `site_greeting` bucket between tests.
- E10 G8: run from repo root (the validator resolves the path against cwd); it exits 0 on warnings, so also require `warnings` [] (a missing `adversarial-validation.json` is only a warning). A missing `harness/` dir fails it (non-vacuous).
- E11 After EXECUTE, refresh the plan header Status line and Resume step 3 (both still describe the pre-cycle-4 CONDITIONAL state — this validate pass may only edit the contract).

## Autonomous Goal Block

SESSION GOAL: On-site greeting (company-level, opt-in, default OFF) — EXECUTE onsite-greeting plan against its PASS validate-contract, then EVL.
Charter + umbrella plan: N/A — single plan.
Autonomy: per feedback_autonomous_phase_execution.md — reversible decisions auto-proceed; subagents do the editing; hard stops below.
Hard stop conditions / safety constraints:
- Never run alembic or any DB script against the repo env-file DATABASE_URL (Supabase prod); pin localhost:5433 or a disposable container.
- Never push/merge (Railway auto-applies migrations to prod) without explicit user instruction.
- Never flip onsite_greeting_enabled, ip_org_lookup_enabled or any site greeting_enabled in a real environment.
- Greeting path makes zero paid or live provider calls; never person-level text.
- tracker.min.js must stay < 6144 B gzipped (abort + report at >= 6130).
- Stop on two alembic heads (signal-creative-cta sibling); no merge revision without orchestrator approval.
Next phase: EXECUTE: process/features/pixel/active/onsite-greeting_27-11-26/onsite-greeting_PLAN_27-11-26.md (one opus vc-execute-agent) → EVL via spawned vc-tester.
Validate contract: inline in plan
Execute start: G1 .venv/bin/pytest tests/unit/test_greeting_service.py -q; G3 .venv/bin/pytest tests/unit/test_pixel_fingerprint.py tests/unit/test_pixel.py -q | G4 apps/pixel e2e/greeting.spec.ts | G2 both-flags-ON show:true probe | G8 validate-risk-artifacts.mjs (failures+warnings empty) | high-risk pack: yes
Next Step: ENTER EXECUTE MODE for process/features/pixel/active/onsite-greeting_27-11-26/onsite-greeting_PLAN_27-11-26.md
