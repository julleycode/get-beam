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
