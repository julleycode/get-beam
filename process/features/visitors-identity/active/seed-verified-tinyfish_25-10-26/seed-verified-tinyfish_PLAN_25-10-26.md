---
name: plan:seed-verified-tinyfish
description: "Seed 5 fake verified visitors into LOCAL Docker PG + flag-gated TinyFish Search+Fetch enrichment step (Step 4c)"
date: 25-10-26
feature: visitors-identity
---

# Seed Verified Visitors + TinyFish Enrichment — PLAN (COMPLEX, 2 workstreams)

**Status**: PLANNED — validated CONDITIONAL
**Complexity**: COMPLEX

TL;DR: (A) new idempotent `scripts/seed_verified_visitors.py`, fail-closed to a localhost DSN, 5 fake `example.com` people with emailable provider `form_capture`. (B) new `services/tinyfish_client.py` + `services/tinyfish_reader.py`, wired as enricher Step 4c after the GitHub reader, writing ONLY `social_context["web"]` + empty profile fields. Flag `tinyfish_enrichment_enabled` default OFF.

## Context / Research Findings
- `is_emailable_identity` -> `identity_level(provider)=="person"`; PERSON_LEVEL_PROVIDERS includes `form_capture`, `pdl_person_enrich`, `manual`. **`scripts/seed.py` uses `people_data_labs`, which is NOT emailable** — do not copy it.
- `IdentifiedVisitor` (apps/api/models/visitor.py): email, full_name, city, region, country, resolution_provider, confidence_score, email_ciphertext, email_bidx, full_name_ciphertext, resolved_at, confirmed_at. NO first_seen/last_seen. `Visitor` HAS first_seen/last_seen (NOT NULL), identity_status, enrichment_status.
- `Site` requires site_id, user_id (UUID, NOT NULL), name, url.
- `VisitorEmail`: site_id, visitor_id, email, source (`normalize_source` enum), email_ciphertext, email_bidx.
- `EnrichmentProfile` (models/enrichment.py): job_title, company_name, linkedin_url(+_ciphertext), personal_website, social_context JSONB, enrichment_completeness.
- pii_crypto: `normalize_email`, `email_hash`, `encrypt_pii`.
- Fail-closed DSN guard precedent: `scripts/refresh_ip_org.py:55` local host set `{localhost,127.0.0.1,::1,host.docker.internal}`.
- Enricher `enrich_tier1` Steps 1/1b/1c/2/3/4 (content_reader)/4b (`_fetch_and_store_github`, flag `enable_github_reader`). Step 4b is the template for 4c. tenacity + `_is_transient_http_error` + `log_api_call` already imported in enricher.py.
- Unit test pattern: `unittest.mock` AsyncMock/patch (tests/unit/test_content_enrich.py). respx is NOT a dependency — do not add it.
- Docker at research time: `lsof :5433/:6379` -> NO listeners (daemon down). Hybrid gates are conditional on it.

## Acceptance Criteria (SPEC locked inline)
Goals: G1 five identified, emailable, enriched fake visitors visible in the local dashboard; re-run = no dupes. G2 TinyFish enriches an identified visitor's profile from public web pages, OFF by default.
- AC-1 script refuses non-local DSN (exit non-zero, zero writes). No remote override flag — local only by design.
- AC-2 run twice -> exactly 5 Visitor / 5 IdentifiedVisitor / 5 VisitorEmail / 5 EnrichmentProfile rows for the seed site.
- AC-3 every seeded identity: `is_emailable_identity(provider)` True, confidence >= 0.9, email_bidx + ciphertext set, `example.com/.org/.net` domains only.
- AC-4 flag OFF -> zero TinyFish HTTP calls, profile unchanged.
- AC-5 MOCK_EXTERNAL_APIS -> deterministic fake search/fetch, no network.
- AC-6 fetched text reaches Gemini only via `prompt_safety.clean_text` + `wrap_untrusted`.
- AC-7 TinyFish never writes IdentifiedVisitor / identity fields; only EnrichmentProfile fill-if-empty + `social_context["web"]`.
- AC-8 per-URL `errors[]` inside a 200 handled; HTTP failure non-fatal to the waterfall.
- AC-9 Redis cache 7d per (name, company) key; daily cap `tinyfish_daily_fetch_cap`; `log_api_call` providers `tinyfish_search` / `tinyfish_fetch`; no PII in logs.
Out of scope: prod seeding, identity resolution via TinyFish, TinyFish Agent/Browser APIs, UI changes, migrations.

## Decision Summary
### Chosen Approach
New standalone seed script + new TinyFish client/reader modelled on the github_reader Step 4b — smallest, safest, matches existing patterns.
### Why This Over Alternatives
| Alternative | Why Rejected |
|---|---|
| Extend seed.py | Random data, non-emailable provider, not idempotent |
| Extend seed_demo_getbeam.py | Real people + defaults to prod DSN; wrong safety posture |
| Replace Step 4 deep_research (Gemini grounding) with TinyFish | Changes existing behavior; user chose a new step |
| Extract fields with regex, no Gemini | Weak yield; Gemini JSON path already hardened |
### Risk Predictions
- Security: fetched pages are hostile prompt input -> mandatory fence (AC-6). LinkedIn may block fetch -> errors[] path.
- Privacy: name+company query is PII sent to a 3rd party -> identified visitors only, flag OFF, log ids only.
- Correctness: wrong-person pages for common names -> require company token in title/snippet before fetch; fill-if-empty only.
- Ops: seed hitting prod via the default env DSN -> guard + inline-pinned DATABASE_URL.
- Cost: free tiers; daily cap guards fetch quota.
### Key Constraints Accepted
Never overwrite non-empty profile fields; never create/upgrade identity; mock path mandatory.

## Touchpoints
- NEW `scripts/seed_verified_visitors.py`
- NEW `apps/api/services/tinyfish_client.py` — `search(query, *, domain_type="web")`, `fetch(urls) -> (results, errors)`; httpx async, timeout, tenacity 3x on transient, header `X-API-Key`, mock branch, `log_api_call`.
- NEW `apps/api/services/tinyfish_reader.py` — `enrich_from_web(visitor, identified, profile, db)`: query `"{full_name} {company}"`, filter results by company token + preferred hosts (linkedin.com, company domain), fetch top `tinyfish_max_fetch_urls` (default 3), `gemini_generate_json` over wrapped text -> {job_title, company_name, linkedin_url, personal_website, summary}, fill-if-empty, merge `social_context["web"]`.
- EDIT `apps/api/services/enricher.py` — Step 4c after 4b, non-fatal try/except.
- EDIT `apps/api/config.py` — `tinyfish_api_key: str | None = None`, `tinyfish_enrichment_enabled: bool = False`, `tinyfish_max_fetch_urls: int = 3`, `tinyfish_daily_fetch_cap: int = 200`, `tinyfish_timeout_s: float = 15.0`.
- NEW `tests/unit/test_tinyfish_client.py`, `tests/unit/test_tinyfish_reader.py`, `tests/unit/test_seed_verified_visitors.py`.

## Public Contracts
No API/schema change, no migration. New env vars (default OFF). New additive JSONB key `social_context["web"]` (must merge, not wholesale-overwrite — see backlog social-context-wholesale-overwrite note).

## Blast Radius
~8 files: apps/api (2 new services, 2 edits), scripts (1 new), tests (3 new). Risk class: external integration + PII to 3rd party (flag-gated) + DB writes (local only).

## Implementation Checklist
1. config.py settings block.
2. tinyfish_client.py per Touchpoints.
3. tinyfish_reader.py; Redis cache key `tinyfish:{sha256(name|company)}` TTL 7d; daily cap counter `tinyfish:cap:{yyyymmdd}`; skip when no full_name, flag off, or key missing (mock mode bypasses key).
4. enricher.py Step 4c.
5. Unit tests: client (mock fixtures, errors[] in 200, transient retry, log_api_call called), reader (flag-off no-op, fence present + `<>` stripped, fill-if-empty, no IdentifiedVisitor writes, cache hit skips HTTP, cap reached skips).
6. seed_verified_visitors.py: `_assert_local_dsn(url)` (pattern from refresh_ip_org.py); deterministic ids via uuid5("seed-verified-{slug}"); site `beam_seed_verified` (name+url) owned by `--user-id` or first local user; per-slug delete-then-insert in one transaction; provider `form_capture`, confidence 0.95, `confirmed_at=now`; VisitorEmail source `form`; Visitor identity_status `identified`, enrichment_status `enriched`; flags `--dry-run`, `--unseed`.
7. Unit test for the guard (supabase-like DSN rejected, localhost accepted) + emailable assertion over the seed roster.

## Phase Completion Rules
- CODE DONE: items 1-7 written, G1-G4 green.
- VERIFIED: G5-G6 green on local Docker (G7 optional, user opt-in).

## Verification Evidence
| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| G1 `.venv/bin/pytest tests/unit/test_tinyfish_client.py -q` | Fully-Automated | AC-5, AC-8, AC-9 |
| G2 `.venv/bin/pytest tests/unit/test_tinyfish_reader.py -q` | Fully-Automated | AC-4, AC-6, AC-7, AC-9 |
| G3 `.venv/bin/pytest tests/unit/test_seed_verified_visitors.py -q` | Fully-Automated | AC-1, AC-3 |
| G4 `.venv/bin/pytest tests/unit -q` (no regression vs 1324-pass baseline) | Fully-Automated | all |
| G5 seed run x2 vs localhost:5433 + count query + prod-DSN refusal | Hybrid (Docker) | AC-1, AC-2, AC-3 |
| G6 `.venv/bin/pytest tests/integration -q -k enrich` | Hybrid (Docker) | no regression |
| G7 live TinyFish smoke with real key | Agent-Probe (needs-live-provider) | real response shape |

## Test Infra Improvement Notes
(none identified yet)

## Resume and Execution Handoff
1. Plan: process/features/visitors-identity/active/seed-verified-tinyfish_25-10-26/seed-verified-tinyfish_PLAN_25-10-26.md
2. Last completed: PLAN + VALIDATE (outer)
3. Validate-contract: written below, Gate CONDITIONAL
4. Context: all-context.md, tests/all-tests.md, enricher.py, github_reader.py, refresh_ip_org.py, identity_classification.py
5. Next: on ENTER EXECUTE MODE, items 1-5 then 6-7; run G1-G4; start Docker then G5-G6.

## Validate Contract
generated-by: outer-pvl
date: 2026-10-25
Date: 25-10-26
Gate: CONDITIONAL

| Layer 1 | Status |
|---|---|
| Infra fit | CONCERN — Docker daemon down (no :5433 listener); G5/G6 blocked until started |
| Test coverage | PASS — unit gates via unittest.mock; respx absent, not added |
| Breaking changes | PASS — additive, flag OFF |
| Security | CONCERN — PII (name+company) sent to TinyFish; fetched text hostile (mitigated E3/E5, flag OFF) |

| Layer 2 | Status |
|---|---|
| A seed script | PASS — fields verified on disk; provider corrected to form_capture |
| B tinyfish client/reader | CONCERN — live response shape unprobed (G7) |
| B enricher wiring | PASS — Step 4b insertion point present |

Totals: 0 FAIL / 3 CONCERN / 4 PASS -> Gate CONDITIONAL. All 3 concerns are environment/known-gap, not plan defects; a supplement cycle cannot close them.

Execute-agent instructions:
- E1 Every DB command pins `DATABASE_URL` inline to the local docker DSN on `localhost:5433` (take user/password/db from infra/docker-compose.yml). Never rely on the default env file — it points at Supabase PROD.
- E2 Docker check `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`; start via `/Applications/Docker.app/Contents/Resources/bin/docker compose -f infra/docker-compose.yml up -d`. If unavailable, record G5/G6 as known-gap.
- E3 Fetched text enters prompts only as `wrap_untrusted(clean_text(text)[:8000])`; test asserts the `<untrusted_visitor_data>` fence and stripped `<>`.
- E4 social_context write merges key "web" (read-modify-write), never replaces the dict.
- E5 structlog logs visitor_id[:8], counts, status — never name, query, URL, or page text.
- E6 Do not add TinyFish to PERSON_LEVEL_PROVIDERS or edit identity_classification.py.

G5 commands (Hybrid):
```
DATABASE_URL=<local-5433-dsn> .venv/bin/python -m scripts.seed_verified_visitors
DATABASE_URL=<local-5433-dsn> .venv/bin/python -m scripts.seed_verified_visitors   # rerun, idempotency
psql <local-5433-dsn> -c "select count(*) from identified_visitors where site_id='beam_seed_verified'"  # expect 5
DATABASE_URL=postgresql+asyncpg://u:p@db.example.supabase.co/x .venv/bin/python -m scripts.seed_verified_visitors; echo $?  # expect non-zero, no writes
```
Known gaps: KG-1 Docker gates G5/G6 pending daemon; KG-2 live TinyFish shape G7 (needs-live-provider, user opt-in).

## Demo Supplement (25-10-26)

User-approved add-on so TinyFish is visible in the product. No commits.

- **UI:** `apps/web/src/lib/api-types.ts` — `social_context.web?: { summary?, sources?: string[], fetched_at? }` (sources are plain URL strings, per `tinyfish_reader.py:248`). `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` — "Web research" `Section` after Deep research, shown only when `social_context.web` exists: plain-text summary, http(s)-only source links (new tab, `noopener noreferrer`, hostname), "via TinyFish · Fetched {date}".
- **Seed:** `scripts/seed_verified_visitors.py --demo-company` adds a 6th row "Demo Visitor" (demo.visitor@example.com, Head of Partnerships, Stripe, San Francisco), no `web` key. No company-domain column exists on `EnrichmentProfile`, so none set. Default stays 5 rows; `--unseed` always removes the demo row. 5 new tests in `tests/unit/test_seed_verified_visitors.py`.
- **Gates:** seed+tinyfish tests 31 passed; full unit 3051 passed / 2 skipped. Web `tsc`/`lint` NOT run — `apps/web/node_modules` missing.
- **Trigger finding:** Step 4c runs only inside `Enricher.enrich_tier1`. The row "Enrich" button (`POST /enrich`) calls `deep_research` and does NOT run Step 4c. The detail page "Deep-dive research" button (`POST /resolve-social`, needs `ENABLE_OSINT_SCAN=true`) calls `enrich_tier1` first, so it does. Inside `enrich_tier1`, Step 4c is unreachable when `PEOPLE_DATA_LABS_API_KEY` is empty (early return, not mock-aware) Second blocker for this demo row: if PDL/Apollo miss, the Step-1c domain fallback derives company "Example" from example.com and `_upsert_profile` OVERWRITES the seeded "Stripe" (it sets any non-None field), so TinyFish searches "Demo Visitor Example". With MOCK_EXTERNAL_APIS=true the PDL/Apollo mocks may return their own fake company instead. Not redesigned.

## Phase 2: Web research button (25-10-26)

TL;DR: new flag-gated `POST /api/v1/visitors/{site_id}/{visitor_id}/web-research` that calls `enrich_from_web` directly (same gate as `/resolve`), an additive `web_research_enabled` bool on `VisitorDetailOut`, a mock-mode Gemini extraction branch in `tinyfish_reader` (today mock mode cannot complete Step 4c), and a "Web research (TinyFish)" button on the visitor detail page. `/enrich`, `Enricher.enrich_tier1` and `enricher.py` are untouched.

### Status
EXECUTED 25-10-26 — P2-G1..G6 green; P2-G7/G8 deferred (KG-1). Validated PASS (inner PVL). Builds on uncommitted Demo Supplement (web card, `social_context.web` type, `--demo-company`).

### Research findings (verified on disk)
- `enrich_from_web(visitor, identified, profile, db)` (`tinyfish_reader.py:203`) returns `bool`, never raises, does NOT commit (mutates `profile` only; caller commits). Silent `False` for: flag off, no key (non-mock), empty `full_name`, empty company (profile.company_name, else non-free-mail email domain stem), no matching results, daily cap hit (`_claim_cap`, Redis down = fail closed), no pages, any exception. Cache: Redis `tinyfish:{sha256(name|company)}` 7d; a cache hit skips search, fetch AND the cap.
- **Mock gap:** `tinyfish_client` search/fetch have mock branches, but `gemini_generate_json` -> `gemini_generate` has NO mock branch (`gemini_client.py:99`; only `gemini_agent_loop` mocks). With `MOCK_EXTERNAL_APIS=true` and no `GEMINI_API_KEY` it raises `GeminiError` -> swallowed -> `False`. With a key set it would make a LIVE Gemini call in mock mode. Must fix for a keyless demo.
- `/resolve` gate (`visitors.py:883-905`): `get_current_user` + `_verify_site_access` (foreign site -> 404) + select `Visitor` with `human_only_visitor_filter()` -> 404. `/enrich` (825-880) is the load template for IdentifiedVisitor/EnrichmentProfile.
- No `@limiter.limit` exists on the visitors router yet; precedent `routers/onboarding.py:56,74` (`from apps.api.services.rate_limiter import limiter`, `@limiter.limit("30/minute")`, needs `request: Request`). Flag-off precedent: onboarding raises `HTTPException(404, "Not Found")`.
- `check_usage_allowed`/`increment_usage` meter monthly identity resolutions (plan quota). TinyFish is not identity resolution.
- Detail page (`apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx`) does NOT use TanStack Query: it holds `visitor` in `useState` and refreshes via `api.getVisitor` (see `handleResolveSocial`, ~line 436). Errors render inline via a status/message state, not a toast library.
- `apps/web/node_modules` missing; Docker absent (KG-1).

### Decision note (approach chosen by user; sub-decisions)
| Decision | Choice | Why |
|---|---|---|
| Flag off | `404 Not Found` | Matches onboarding-canary precedent; dormant feature not revealed. 409 would leak existence. |
| Anonymous / no profile | `409` with `detail` code `not_identified` / `no_profile` | Clear, actionable 4xx; resource exists but state is wrong. Visitor existence already confirmed to this tenant, so no leak. |
| No name / no company | `422` `detail: "missing_name"` / `"missing_company"` (pre-checked via `_company_for`) | `enrich_from_web` returns bare `False`; pre-checks give the UI a real reason. |
| Other `False` (no results / cap / fetch fail) | `200 {"status": "no_results"}` | Not a client error; cap is an operator quota. |
| `force` param | **Not added** | 7d cache is the quota guard; force would bypass it and burn the global fetch cap. Revisit if users ask. |
| Rate limit | `@limiter.limit("10/minute")` per IP | Sibling precedent; endpoint triggers outbound fetch + Gemini. |
| Usage accounting | Do NOT call `check_usage_allowed`/`increment_usage` | Those meter identity resolutions; counting web research would mis-bill. Global `tinyfish_daily_fetch_cap` + per-IP limit + 7d cache bound spend. |
| UI flag | Additive `web_research_enabled: bool = False` on `VisitorDetailOut` only (not `VisitorOut`) | Repo lesson: detail-only fields on the detail schema; no extra call. |
| Mock Gemini | Mock branch in `tinyfish_reader.enrich_from_web`: when `settings.mock_external_apis`, build `data` via new pure `_mock_extract(full_name, company, pages)` instead of calling Gemini | Service-layer mock convention; makes demo keyless and prevents a live Gemini call in mock mode. Does not touch `enricher.py`. |
| Web refresh | Follow page's local pattern (`api.getVisitor` -> `setVisitor`), not TanStack invalidation | Page has no query cache; adding one is scope creep. |

### Touchpoints (Phase 2)
- `apps/api/routers/visitors.py` — new endpoint + undecorated helper `_web_research(db, site_id, visitor_id, user) -> dict`; add `"web_research_enabled"` to detail `data` dict (near line 694).
- `apps/api/schemas/visitors.py` — `VisitorDetailOut.web_research_enabled: bool = False`.
- `apps/api/services/tinyfish_reader.py` — `_mock_extract` + mock branch.
- `apps/web/src/lib/api.ts` — `webResearch(siteId, visitorId)`.
- `apps/web/src/lib/api-types.ts` — `VisitorDetail.web_research_enabled?: boolean`.
- `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` — button + handler + inline result.
- New tests: `tests/unit/test_web_research_endpoint.py`; extend `tests/unit/test_tinyfish_reader.py`; new `tests/integration/test_web_research_endpoint.py` (KG-1).

### Public Contracts (Phase 2)
- `POST /api/v1/visitors/{site_id}/{visitor_id}/web-research` (auth). Responses: `200 {"status": "updated", "filled": [field names], "web": {summary, sources, fetched_at}}`; `200 {"status": "no_results"}`; `404` flag off / foreign site / unknown or bot visitor; `409 not_identified|no_profile`; `422 missing_name|missing_company`; `429` rate limit. Body never includes IP, email, or name.
- `GET /api/v1/visitors/{site_id}/{visitor_id}` gains additive `web_research_enabled: bool`.

### Blast Radius (Phase 2)
6 source files + 3 test files, 2 packages (`apps/api`, `apps/web`). Risk class: new authed endpoint (public API, additive) + outbound PII (name+company to TinyFish, already accepted in Phase 1). No schema/migration, no billing change, flag default OFF. `/enrich`, `enricher.py`, `identity_classification.py` must have empty diffs.

### Implementation Checklist (Phase 2)
1. `schemas/visitors.py`: add `web_research_enabled: bool = False` to `VisitorDetailOut` (NOT `VisitorOut`).
2. `routers/visitors.py` detail endpoint: `data["web_research_enabled"] = bool(settings.tinyfish_enrichment_enabled)`.
3. `tinyfish_reader.py`: add pure `_mock_extract(full_name, company, pages) -> dict` returning deterministic `{job_title: "Head of Growth", company_name: company, linkedin_url: <first linkedin.com page url or None>, personal_website: None, summary: f"{full_name} works at {company} (mock web research)."}`; in `enrich_from_web` replace the Gemini call with `data = _mock_extract(...) if settings.mock_external_apis else await gemini_generate_json(...)`. Pass result through existing `_normalize`. Name/company enter only the returned dict, never logs.
4. `routers/visitors.py`: import `Request`, `limiter` (`apps.api.services.rate_limiter`), `enrich_from_web`, `_company_for`. Helper `_web_research`: flag off -> 404; `_verify_site_access`; load Visitor with `human_only_visitor_filter()` -> 404; load IdentifiedVisitor -> 409 `not_identified`; load EnrichmentProfile -> 409 `no_profile`; empty `full_name` -> 422 `missing_name`; `_company_for` empty -> 422 `missing_company`; `ok = await enrich_from_web(...)`; if ok `await db.commit()` and return `updated` + `filled` + `profile.social_context["web"]`; else `no_results`. Log `web_research_requested` with `site_id`, `visitor_id[:8]`, `status` only. Endpoint `@router.post("/{site_id}/{visitor_id}/web-research")` + `@limiter.limit("10/minute")`, signature `(request: Request, site_id, visitor_id, user=Depends(get_current_user), db=Depends(get_db))`, delegates to helper. Return `filled` by diffing `_FILLABLE` attrs before/after (do not change `enrich_from_web` signature).
5. `api-types.ts`: `web_research_enabled?: boolean` on `VisitorDetail`; response type `WebResearchResult = { status: "updated" | "no_results"; filled?: string[]; web?: {...} }`.
6. `api.ts`: `async webResearch(siteId, visitorId)` POST to the new path, typed `WebResearchResult`.
7. `page.tsx`: `webResearching` + `webResearchResult` state; `handleWebResearch()` calls `api.webResearch`, then `setVisitor(await api.getVisitor(...))`; on error set inline message from `err.message`. Render `Button` "Web research (TinyFish)" (Loader2 spinner while running, disabled while running) only when `visitor.web_research_enabled && visitor.identity_status === "identified"` (confirm exact identified check used elsewhere on page). Show inline result line ("No matching public pages" / error). No `any`.
8. Tests (below). Do not edit `enricher.py`, `/enrich`, `identity_classification.py`.

### Verification Evidence (Phase 2)
| Gate / Scenario | Strategy | Proves |
|---|---|---|
| P2-G1 helper: flag off -> 404; foreign site (`_verify_site_access` raising 404) -> 404; visitor missing/bot -> 404; no IdentifiedVisitor -> 409; no profile -> 409; no name/company -> 422; happy path calls `enrich_from_web` once, commits, returns `updated` + `web`; `False` -> `no_results`, no commit | Fully-Automated (unit, AsyncMock db, patched `enrich_from_web`/`_verify_site_access`) | endpoint contract + gate mirror |
| P2-G2 `_mock_extract` deterministic + mock branch never calls `gemini_generate_json`; non-mock still does | Fully-Automated | keyless demo |
| P2-G3 detail schema: `VisitorDetailOut` has `web_research_enabled`, `VisitorOut` does not | Fully-Automated | repo schema lesson |
| P2-G4 regression: existing tinyfish/seed/enricher unit tests + full unit lane | Fully-Automated | enrich chain untouched |
| P2-G5 `git diff --stat main -- apps/api/services/enricher.py apps/api/services/identity_classification.py` empty; `/enrich` body unchanged | Fully-Automated | no chain edits |
| P2-G6 web `npm ci` then `tsc --noEmit` + `lint` | Fully-Automated (prereq install) | strict TS |
| P2-G7 integration: real PG, real route via httpx, flag on + mock, identified seed row -> 200 `updated`, profile persisted; foreign user -> 404 | Hybrid (KG-1 Docker) | DB commit + auth wiring |
| P2-G8 manual: seed `--demo-company`, flag+mock on, click button, Web research card fills | Agent-Probe (needs Docker + dev servers) | end-to-end demo |

### Test Infra Improvement Notes (Phase 2)
- Visitors router has no unit-test harness for endpoints; the undecorated-helper pattern (`_web_research`) avoids needing a real `Request` for slowapi in unit tests. Reusable for future routes.

### Resume and Execution Handoff (Phase 2)
1. Plan: this file, section "Phase 2: Web research button (25-10-26)".
2. Last completed: Phase 2 PLAN + inner PVL.
3. Validate-contract: written below (Phase 2 Validate Contract), Gate PASS.
4. Context: all-context.md, tests/all-tests.md, tinyfish_reader.py, visitors.py 671-960, onboarding.py, rate_limiter.py, page.tsx 300-470/880+.
5. Next: ENTER EXECUTE MODE -> checklist 1-8 in order, run P2-G1..G6; G7/G8 when Docker exists.

### Phase 2 Validate Contract
generated-by: inner-pvl: phase-2
date: 2026-10-25
Date: 25-10-26
Gate: PASS
Environment-deferred gates (not plan defects): P2-G7, P2-G8 (KG-1 Docker absent).

| Layer 1 | Status |
|---|---|
| Infra fit | PASS — limiter import path + Request param verified (onboarding precedent); no migration |
| Test coverage | PASS — helper pattern makes all contract branches unit-testable now; DB path deferred to KG-1 |
| Breaking changes | PASS — additive endpoint + additive detail field with default |
| Security | PASS — same tenant gate as /resolve, 404 not 403, flag-off 404, per-IP limit, global cap, no PII in body/logs, hostile-text path unchanged |

| Layer 2 | Status |
|---|---|
| Backend endpoint | PASS — load template and gate verified at visitors.py:825-905 |
| Mock Gemini branch | PASS — gap confirmed (gemini_generate has no mock); fix is local to tinyfish_reader |
| Schema field | PASS — VisitorDetailOut at schemas/visitors.py:83 |
| Web | PASS — page uses useState + api.getVisitor; plan follows it |

Cycle 1 findings fixed in plan before gate: (a) "TanStack invalidation" replaced with page-local refresh (page has no query cache); (b) mock Gemini gap added as item 3; (c) slowapi direct-call problem solved by undecorated helper; (d) `filled` computed in router to keep `enrich_from_web` signature stable. Totals: 0 FAIL / 0 CONCERN / 8 PASS.

Execute-agent instructions:
- E1 Do not change `enrich_from_web`'s signature or return type; only add the mock branch.
- E2 Integration test must pin `DATABASE_URL` to a localhost DSN (`.env` points at Supabase PROD).
- E3 Never put name, email, company, query or URLs in structlog events.
- E4 Use the page's existing identified-visitor check; if none, gate on `visitor.identity_status === "identified"`.

Test gates (run from work context):
```
/Users/apple/.venvs/get-beam/bin/python -m pytest tests/unit/test_web_research_endpoint.py tests/unit/test_tinyfish_reader.py tests/unit/test_tinyfish_client.py tests/unit/test_seed_verified_visitors.py -q
/Users/apple/.venvs/get-beam/bin/python -m pytest tests/unit -q
git diff --stat main -- apps/api/services/enricher.py apps/api/services/identity_classification.py   # expect empty
(cd apps/web && npm ci && npx tsc --noEmit && npm run lint)
# KG-1 (Docker): DATABASE_URL=<localhost:5433 dsn> /Users/apple/.venvs/get-beam/bin/python -m pytest tests/integration/test_web_research_endpoint.py -q
```
Known gaps: KG-1 Docker (P2-G7, P2-G8); KG-2 live TinyFish/Gemini shape (Phase 1, unchanged).
