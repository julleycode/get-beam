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

## Phase 3: Prod demo seed (26-10-26)

**Status:** EXECUTED — code + unit tests only. No DB connection was opened; the prod run has NOT happened.

### What Was Done
- `scripts/seed_verified_visitors.py`: `--allow-remote` + `--owner-email` + `--yes`; `check_target()` (exit 2), `_resolve_owner_by_email` (exact, case-insensitive, 0/>1 → exit 3, never creates users), `remote_site_id()` = `beam_seed_verified_<sha256(owner)[:10]>`, other-owner site → exit 4, missing PII keys → exit 5, hostname-only `summarize()`; remote without `--yes` (or with `--dry-run`) = summary + exit 0, zero writes. Remote visitor ids are scoped to the site (`uuid5(..., f"seed-verified-{site_id}-{slug}")`); local ids unchanged. Both modes: `IdentifiedVisitor.do_not_email=True`; new site `hot_alert_enabled=False`, name "Beam Demo (fictional visitors)". Remote unseed deletes by `site_id` from enrichment_profiles, visitor_emails, identified_visitors, visitors, events, then the site (also filtered by owner). Docstring rewritten with opt-in rules.
- Shared delete-then-insert writer `_write_people` used by both modes (local behavior unchanged apart from D6 guard + site name).
- `_register_models()` — imports every `apps.api.models.*` module before ORM use. **Found during EXECUTE:** selecting `User` without this raises `InvalidRequestError` (`User` → `'SocialAccount'` unresolved). This was a latent bug in the existing local `_resolve_owner` too; the real prod run would have crashed on the owner lookup.
- `tests/unit/test_seed_verified_visitors.py`: +20 tests (P3-G1…G10), fake session, no DB.

### Test Gate Outcomes
| Gate | Result |
|---|---|
| `pytest tests/unit/test_seed_verified_visitors.py -q` | 40 passed |
| `pytest tests/unit -q -k "seed or identity_classification or web_research"` | 108 passed |
| `validate-plan-artifact.mjs <plan>` | 0 failures, 0 warnings |
| Every P3 test also run in isolation (catches import-order masking) | all pass |
| CLI smoke, localhost DSN, non-connecting paths | local `--dry-run` exit 0; `--allow-remote` alone exit 2; `--owner-email` alone exit 2; remote with empty PII keys exit 5 |

### Plan Deviations
- Item 1 (rebase onto `origin/main`) skipped — orchestrator said do not merge/rebase. No overlap with origin/main's 3 commits.
- E3 TDD red-first not followed literally: tests written right after the code. They did go red once (mapper bug above) before green.
- Added (within blast radius): `--owner-email` without `--allow-remote` → exit 2; `--dry-run` forces no writes in remote mode even with `--yes`; `_register_models()`.

### Operator Prod Run (needs explicit user yes — NOT run)
`railway run` executes **locally** with the Railway prod env injected, so use the local interpreter. The container route (`railway ssh`) does not work: the `Dockerfile` copies only `apps/api/` and `apps/pixel/`, not `scripts/`. Run from the repo/worktree root:

```bash
# 1. dry run (no writes) — check host, owner id, site id, counts 1/6/6/6/6
railway run --service retarget-agent --environment production -- \
  /Users/apple/.venvs/get-beam/bin/python -m scripts.seed_verified_visitors \
  --allow-remote --owner-email tranthai.work@gmail.com --demo-company
# 2. write
railway run --service retarget-agent --environment production -- \
  /Users/apple/.venvs/get-beam/bin/python -m scripts.seed_verified_visitors \
  --allow-remote --owner-email tranthai.work@gmail.com --demo-company --yes
# 3. cleanup (run without --yes first to see live counts)
railway run --service retarget-agent --environment production -- \
  /Users/apple/.venvs/get-beam/bin/python -m scripts.seed_verified_visitors \
  --allow-remote --owner-email tranthai.work@gmail.com --unseed --yes
```

DSN caveat: the engine uses `DATABASE_URL` verbatim (must be `postgresql+asyncpg://…`). Prod DB is Supabase (public pooler host), so the injected `DATABASE_URL` should be reachable from a laptop. If the service instead exposes a private host, swap in the public one, keeping the `+asyncpg` driver: `railway run ... -- sh -c 'DATABASE_URL="$DATABASE_PUBLIC_URL" /Users/apple/.venvs/get-beam/bin/python -m scripts.seed_verified_visitors ...'` (if that var is plain `postgresql://`, the script will fail to connect — rewrite the scheme inside the `sh -c`). Railway env vars override `.env` (pydantic-settings precedence), so the local `.env` does not leak in. The dry-run's `db host:` line is the check: it must be the retarget-agent Supabase host.

### Closeout Packet
- Classification: Keep in active/testing — EVL + operator P3-OP pending.
- Next: EVL (vc-tester reruns the 3 gates), then the user's explicit yes for the operator run.

### Forward Preview
- Commands to stay green: the 3 gates above.
- Blast radius: 2 files as planned. No migration/API/schema change.
- CONTEXT_PARTIAL: none.

- Quick fix 26-10-26: remote mode now requires only `PII_HMAC_KEY` (exit 5 if missing); empty `PII_ENCRYPTION_KEY` prints a stderr warning and seeds plaintext, matching `pii_crypto.encrypt_pii` passthrough on prod Railway. Unit file 41 passed.

### Phase 3 commit + PII-check restore (14-11-26)

- Phase 3 work moved from the uncommitted `visitor-seed-tinyfish-integration` worktree onto branch
  `feat/seed-verified-prod-demo` (on top of `origin/main` `6ef19f7`; applied clean, no conflicts) and committed.
- The 26-10-26 quick-fix relaxation is reverted: remote mode now exits 5 unless `PII_HMAC_KEY` is set
  AND the effective key (`PII_ENCRYPTION_KEY or ENCRYPTION_KEY`) is a valid Fernet key — the same key
  `pii_crypto._get_fernet()` uses. Prod shape (empty PII key, valid `ENCRYPTION_KEY`) passes.
  Prod verified 14-11-26: 0 non-Fernet values across all 11 `*_ciphertext` columns — see
  `backlog/prod-pii-encryption-key-empty_NOTE_26-10-26.md` (RESOLVED).
- Safety re-review of remote mode: `--allow-remote` + `--owner-email` required, `--user-id`
  rejected, writes need `--yes`, site id scoped per owner, other-owner site refused, every
  `IdentifiedVisitor` `do_not_email=True`, unseed scoped to the one demo site. No gap found.
- Tests: `tests/unit/test_seed_verified_visitors.py` 45 passed. Full unit lane: 3107 passed /
  2 skipped / 1 failed — the failure (`test_paid_x402.py::test_no_payment_returns_402_with_requirements`,
  `KeyError: 'accepts'`) is in the x402 routes from `cb3cf31`, outside this change.
- Still pending: EVL (independent vc-tester run) and the operator prod run (needs the site owner's explicit yes).
