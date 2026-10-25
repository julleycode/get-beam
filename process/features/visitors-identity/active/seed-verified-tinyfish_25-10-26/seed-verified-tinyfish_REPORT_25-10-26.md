---
phase: execute
date: 2026-10-25
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/seed-verified-tinyfish_25-10-26/seed-verified-tinyfish_PLAN_25-10-26.md
---

## What Was Done
Checklist items 1-7: config block; `tinyfish_client.py`; `tinyfish_reader.py`; enricher Step 4c; 3 unit test files; `scripts/seed_verified_visitors.py`.

## What Was Skipped or Deferred
G5/G6 (Docker daemon down) -> KG-1. G7 skipped by user decision -> KG-2.

## Test Gate Outcomes
- G1 test_tinyfish_client.py: 8 passed (after supplement)
- G2 test_tinyfish_reader.py: 11 passed
- G3 test_seed_verified_visitors.py: 15 passed
- G4 tests/unit: 3046 passed (after supplement) / 2 skipped / 0 failed
- Extra: prod-like DSN refused (exit 2); `--dry-run` with localhost DSN lists 5 ids (no DB access)

## Plan Deviations
- Venv: `.venv/bin/pytest` does not exist in the worktree; gates ran with `/Users/apple/.venvs/get-beam` via a temporary `.venv` symlink (removed after).
- Seed guard also refuses when `DATABASE_URL` is unset in the environment (stricter than plan; forces inline pin).
- RESOLVED (supplement 25-10-26): endpoints now the documented `GET https://api.search.tinyfish.ai` and `POST https://api.fetch.tinyfish.ai` (`format: markdown`, `X-API-Key`, JSON Content-Type); tests assert exact method/URL/headers with doc-shaped fixtures.
- Company for the query = profile.company_name, else non-free-mail email domain stem; skip if none.

## Test Infra Gaps Found
KG-1 G5/G6 Docker gates; KG-2 TinyFish response shape confirmed by docs only, not by a live call.

## Closeout Packet
Keep in active/testing until G5/G6 run on local Docker.

## Forward Preview
### Test Infra Found
Project venv lives at /Users/apple/.venvs/get-beam (not repo `.venv`).
### Blast Radius Changes
None beyond plan.
### Commands to Stay Green
`python -m pytest tests/unit -q` (with the venv above).
### Dependency Changes
None.

## Demo Supplement (25-10-26)

User-approved add-on so TinyFish is visible in the product. No commits.

- **UI:** `apps/web/src/lib/api-types.ts` — `social_context.web?: { summary?, sources?: string[], fetched_at? }` (sources are plain URL strings, per `tinyfish_reader.py:248`). `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` — "Web research" `Section` after Deep research, shown only when `social_context.web` exists: plain-text summary, http(s)-only source links (new tab, `noopener noreferrer`, hostname), "via TinyFish · Fetched {date}".
- **Seed:** `scripts/seed_verified_visitors.py --demo-company` adds a 6th row "Demo Visitor" (demo.visitor@example.com, Head of Partnerships, Stripe, San Francisco), no `web` key. No company-domain column exists on `EnrichmentProfile`, so none set. Default stays 5 rows; `--unseed` always removes the demo row. 5 new tests in `tests/unit/test_seed_verified_visitors.py`.
- **Gates:** seed+tinyfish tests 31 passed; full unit 3051 passed / 2 skipped. Web `tsc`/`lint` NOT run — `apps/web/node_modules` missing.
- **Trigger finding:** Step 4c runs only inside `Enricher.enrich_tier1`. The row "Enrich" button (`POST /enrich`) calls `deep_research` and does NOT run Step 4c. The detail page "Deep-dive research" button (`POST /resolve-social`, needs `ENABLE_OSINT_SCAN=true`) calls `enrich_tier1` first, so it does. Inside `enrich_tier1`, Step 4c is unreachable when `PEOPLE_DATA_LABS_API_KEY` is empty (early return, not mock-aware) Second blocker for this demo row: if PDL/Apollo miss, the Step-1c domain fallback derives company "Example" from example.com and `_upsert_profile` OVERWRITES the seeded "Stripe" (it sets any non-None field), so TinyFish searches "Demo Visitor Example". With MOCK_EXTERNAL_APIS=true the PDL/Apollo mocks may return their own fake company instead. Not redesigned.

## Phase 2: Web research button (25-10-26)

Status: COMPLETE_WITH_GAPS (P2-G7/G8 deferred, KG-1 Docker absent). No commits.

### What Was Done
- `apps/api/schemas/visitors.py` — `VisitorDetailOut.web_research_enabled: bool = False` (detail-only).
- `apps/api/routers/visitors.py` — detail sets `web_research_enabled`; new undecorated `_web_research` helper + `POST /{site_id}/{visitor_id}/web-research` (`@limiter.limit("10/minute")`). Gates: flag off 404 → site access → human visitor 404 → 409 `not_identified`/`no_profile` → 422 `missing_name`/`missing_company` → `enrich_from_web` → commit + `{status: updated, filled, web}` or `{status: no_results}` (no commit). Log `web_research_requested` (site_id, visitor_id[:8], status). No usage metering.
- `apps/api/services/tinyfish_reader.py` — pure `_mock_extract`; Gemini call replaced by it when `mock_external_apis`. Signature unchanged.
- `apps/web/src/lib/api-types.ts` — `VisitorDetail.web_research_enabled?`, `WebResearchResult`.
- `apps/web/src/lib/api.ts` — `webResearch(siteId, visitorId)`.
- `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` — "Web research (TinyFish)" outline button beside Deep-dive, spinner while running, refresh via `api.getVisitor`, inline "No matching public pages" / error text.
- Tests: new `tests/unit/test_web_research_endpoint.py` (11), +3 in `tests/unit/test_tinyfish_reader.py`, new `tests/integration/test_web_research_endpoint.py` (2, not run).

### Test Gate Outcomes
| Gate | Result |
|---|---|
| P2-G1/G2/G3 focused unit (4 files) | 53 passed |
| P2-G4 full unit lane | 3065 passed / 2 skipped |
| P2-G5 `git diff --stat main -- enricher.py identity_classification.py` | empty; `/enrich` body untouched (only the fastapi import line changed in visitors.py) |
| P2-G6 `tsc --noEmit` / `npm run lint` | exit 0 / no warnings (npm ci run by a separate helper) |
| P2-G7 integration | NOT RUN — KG-1 (file collects: 2 tests) |
| P2-G8 manual demo | NOT RUN — KG-1 |

### Plan Deviations
- E4: button gated on the page's existing `identified` const (status not anonymous/unresolvable/vpn_filtered) rather than literal `=== "identified"`; the backend 409s if no IdentifiedVisitor row exists.
- Unit test imports every `apps.api.models.*` module so `select(Visitor)` mapper config resolves `User -> "SocialAccount"`; without it the failure poisoned later tests in the same run.
- Integration test patches TinyFish search/fetch, cache and cap for determinism.

### Known Gaps
- KG-1 Docker: P2-G7, P2-G8.
- KG-2 live TinyFish/Gemini response shape (unchanged).

### Demo click path (once Docker/dev servers exist)
1. Local DB only (pin `DATABASE_URL` to localhost:5433). `python scripts/seed_verified_visitors.py --demo-company`.
2. API env: `TINYFISH_ENRICHMENT_ENABLED=true`, `MOCK_EXTERNAL_APIS=true`. Start API + web.
3. Dashboard → Visitors → "Demo Visitor" → detail page → click "Web research (TinyFish)".
4. The "Web research" card appears with summary "Demo Visitor works at Stripe (mock web research).", sources, "via TinyFish · Fetched {date}". Mock search titles contain the query, so the company filter passes; sources are a linkedin.com/in/... URL and an example.com/team/... URL. Requires Redis for the daily cap (fail-closed: Redis down -> "No matching public pages"). Caveat from Demo Supplement does NOT apply here: this button bypasses `enrich_tier1`, so the seeded "Stripe" is used.

### Forward Preview
- Commands to stay green: the four pytest/diff/tsc/lint gates above.
- Blast radius: as planned (6 source + 3 test files). No migration, flag default OFF.
