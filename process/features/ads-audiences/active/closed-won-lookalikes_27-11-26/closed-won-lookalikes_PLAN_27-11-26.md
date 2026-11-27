---
name: plan:closed-won-lookalikes
description: "CRM closed-won read-back + closed-won seed segment + Meta lookalike / Google Customer-Match-seed lookalike; flag default OFF"
date: 27-11-26
feature: ads-audiences
---
# Closed-Won Lookalikes — PLAN (COMPLEX)

TL;DR: 4 sections (A read-back, B seed, C lookalike providers, D API/UI) behind `closed_won_lookalikes_enabled` (OFF). One new migration. High-risk: PII to third party, external providers, CRM data → evidence pack required.

Spec: `closed-won-lookalikes_SPEC_27-11-26.md`

Date: 27-11-26
Complexity: COMPLEX
Status: PLANNED (PVL supplement cycle 2 applied 27-11-26: N1–N6 addressed; re-validate from V1 pending)

## Overview
Gap #12 (inbound-playbook): no lookalike-from-customers path exists. CRM connectors push only. This plan adds read-back, a seed segment, and lookalike creation reusing services/ads and services/crm.

## Phase Completion Rules
Section is CODE DONE when its gates pass; VERIFIED only after EVL by vc-tester incl. flag-ON G3 and G4 round-trip. Live provider legs stay known-gap.

## Decision Summary
### Chosen Approach
Polling read-back (Celery/APScheduler, per connection, cursor = last modified) + inbound webhook only for generic_webhook — polling works for all 3 OAuth CRMs with one code path and no public webhook registration per CRM.
### Why This Over Alternatives
| Alternative | Why Rejected |
|---|---|
| Native CRM webhooks (HubSpot/Pipedrive/SF) | 3 registration flows, SF needs outbound messages/CDC; more trust-boundary surface |
| CSV-only seed | Misses the core "Beam identified → closed-won" loop |
| Google Similar Audiences | Sunset Aug 2023; not real |
### Risk Predictions
- Security: hashed PII leaves to Meta/Google — reuse existing HashedContact SHA-256 path, never plaintext.
- Ops: HubSpot scope change forces reconnect; old tokens get 403 → surface "reconnect for deals".
- Data: email match only vs IdentifiedVisitor email_bidx; company-level match deferred.
- Product: Meta lookalike needs >=100 matched seed; warn, do not block.
- API: Google Demand Gen lookalike API shape unverified → known-gap, fallback ships.
### Key Constraints Accepted
Polling latency (default 6h); Google lookalike may be manual step in Ads UI.

## Acceptance Criteria
AC1–AC9 from the SPEC (closed-won-lookalikes_SPEC_27-11-26.md), each mapped in Verification Evidence.

## Touchpoints
- apps/api/services/crm/base.py — add optional `fetch_closed_won(connection, since) -> list[ClosedWonDeal]` (default NotImplementedError)
- apps/api/services/crm/hubspot.py — (Gap 2) won stages resolved via pipelines API (`GET /crm/v3/pipelines/deals`: stage `metadata.isClosed == "true"` AND `probability == 1.0`), NEVER literal `closedwon`; deals search filters `dealstage IN <won stage ids>`; re-window by `hs_lastmodifieddate` (sort ASC, restart window from last seen timestamp) when results approach the 10k search cap; contact associations for emails; add `crm.objects.deals.read` scope; old tokens: check `CrmConnection.scopes` — missing deals scope → return `needs_reconnect` status (UI prompts reconnect), no fetch
- apps/api/services/crm/pipedrive.py — deals?status=won + person emails
- apps/api/services/crm/salesforce.py — SOQL Opportunity IsWon=true + OpportunityContactRole email
- apps/api/routers/crm.py — inbound `POST /crm/{site_id}/webhook/deal` (Gap 9): `@limiter.limit("60/minute")` (N3); flag check FIRST → 404; in-route body cap 256 KB checking BOTH declared `Content-Length` and actual bytes read (N3 — follow agent_mcp.py:131-143 pattern; NOT the main.py:294 ingest middleware, which is scoped to /events/ingest only); upsert is replay-idempotent on (site_id, external_deal_id, email_bidx); verify a `generic_webhook` CrmConnection exists for site (else 404); HMAC with that connection's existing per-connection webhook secret (UD5); pattern = routers/outcomes.py:512-551
- NEW apps/api/models/crm_closed_won.py — `crm_closed_won_contacts` (site_id, connection_id, external_deal_id, email_bidx, email_ciphertext, company_domain, closed_at, identified_visitor_id nullable, source crm|csv|webhook)
- NEW migration — chain off `alembic heads` at EXECUTE time (no hardcoded down_revision; this plan executes 2nd of 3 ads plans, after conversion-apis)
- NEW apps/api/services/closed_won_seed.py — (Gap 4) dedicated seed builder: load rows → apply exclusions (Gap 3) → decrypt ciphertext → normalize+SHA-256 → adapter `create_or_update_audience` with sentinel segment_id `closed_won_seed`, reserving the same per-site push rate-limit slot as `push_segment_to_ads`. Does NOT call `push_segment_to_ads` (requires Segment + IdentifiedVisitor; AdAudienceLink unique per segment)
- apps/api/jobs/scheduler.py — (Gap 1) `poll_closed_won` APScheduler job following the coop-expiry pattern; flag checked at registration AND at runtime; NOT Celery `tasks/crm_tasks.py`
- tests/unit/test_scheduler_job_config.py — add the new job id; file hard-asserts total job counts (currently 28/24/3) + docstring (N1): re-derive counts and docstring at EXECUTE from current registrations (sibling ads plans also add jobs); assert literal jitter/misfire_grace_time values; job registered with NO `next_run_time`
- apps/api/services/ads/base.py — (Gap 7) new `LookalikeResult` dataclass (audience_id, status, supported, warning, error); non-abstract `create_lookalike(connection, seed_audience_id, spec) -> LookalikeResult` default raises NotImplementedError (sibling plans add methods the same way)
- apps/api/services/ads/meta.py — (Gap 6) separate step after async seed processing: POST act_{id}/customaudiences subtype=LOOKALIKE, origin_audience_id, lookalike_spec{ratio, country only when pinned API version ≤ v26 — Beam pins v25}; seed-not-ready / provider errors surfaced verbatim via existing ToS-error path; mock branch
- apps/api/services/ads/google.py — (Gap 5) seed via existing userLists + Data Manager ingest; `create_lookalike` via `userLists:mutate` with `lookalike_user_list {seed_user_list_ids, expansion_level, country_codes}`; `DUPLICATE_LOOKALIKE` → treat as already-exists (return existing); warn seed <1,000; UI note "usable in Demand Gen campaigns only"; EEA fail-closed (UD3); mock branch
- apps/api/services/ads/linkedin.py — reuse CSV export
- apps/api/routers/ads.py — `POST /ads/{site_id}/closed-won/csv`, `GET /ads/{site_id}/closed-won/seed`, `POST /ads/{site_id}/closed-won/lookalike`
- apps/api/routers/sites.py — (Gap 8) site-delete cascade deletes `crm_closed_won_contacts`
- apps/api/services/graph_erasure.py — (Gap 8) erasure sweep deletes `crm_closed_won_contacts` rows by `email_bidx`. NOTE (N5): the sweep only runs when `graph_erasure_sweep_enabled` (scheduler.py:863) — so ingest (CRM poll, webhook, CSV) MUST also skip any bidx with an `erased` suppression tombstone, so erased people are never re-ingested between sweeps
- apps/api/models/ad_audience_link.py (read) + services/ads_push.py:312-330 (pattern) — (N2) upsert one `AdAudienceLink` per (site, connection) with sentinel segment_id `closed_won_seed` (seed audience id in `platform_audience_id`) and (N7) a SECOND sentinel row segment_id `closed_won_lookalike` (lookalike audience id in `platform_audience_id`). Rows read/written only — NO schema change to `ad_audience_links`
- apps/api/config.py — `closed_won_lookalikes_enabled=False`, `closed_won_poll_interval_hours=6`, `meta_lookalike_min_seed=100`, `google_lookalike_min_seed=1000`
- apps/api/schemas/ (ads schemas) + apps/web/src/lib/api.ts, api-types.ts, ads panel component
- tests: tests/unit/test_closed_won_readback.py, tests/unit/test_meta_lookalike.py, tests/unit/test_google_lookalike.py, tests/integration/test_closed_won_seed.py, tests/integration/test_closed_won_erasure.py

## Public Contracts
- 3 new authed routes + 1 webhook route. Flag `closed_won_lookalikes_enabled` OFF → 404 (UD4). If closed-won flag ON but `ad_audiences_enabled` OFF → lookalike/seed-push routes keep existing 501. Foreign ids 404.
- New table `crm_closed_won_contacts`. Additive only.
- HubSpot OAuth scope string changes (new connects); existing connections without deals scope report `needs_reconnect`.
- `LookalikeResult` + `create_lookalike` added to ads base (non-abstract; additive).

## Blast Radius
~23 files, packages apps/api + apps/web. Risk classes: PII/third-party, external provider, CRM OAuth scope, schema migration, public API, GDPR erasure.

## Open User Decisions
All PROVISIONAL defaults — pending user confirmation:
- UD1: build Google lookalike now (Gap 5) — pending user confirmation
- UD2: Meta country is a required UI field, sent in lookalike_spec only when API version ≤ v26 — pending user confirmation
- UD3: Google EEA fail-closed; optional CSV `country` column — pending user confirmation
- UD4: 404 when closed-won flag off; keep 501 for `ad_audiences_enabled` off — pending user confirmation
- UD5: webhook reuses per-connection generic_webhook secret — pending user confirmation
- UD6: seed includes unmatched CRM closed-won emails; UI shows matched count separately — pending user confirmation

## Implementation Checklist
A. Read-back
1. ClosedWonDeal dataclass + base method; mock branch returns 3 deterministic deals.
2. HubSpot fetcher: pipelines API won-stage resolution (isClosed + probability 1.0), `hs_lastmodifieddate` re-windowing past 10k cap, scope check via `CrmConnection.scopes` → `needs_reconnect`. Pipedrive/Salesforce fetchers. All httpx, timeout+retry, sanitize_error, no PII logs.
3. Webhook receiver in routers/crm.py: flag-first 404 → body size cap 413 → generic_webhook connection exists else 404 → HMAC verify (per-connection secret) → upsert.
3a. (N5) Every ingest path (steps 2/3/6) skips rows whose email_bidx has an `erased` suppression tombstone (skipped count logged, no PII).
4. Model + migration (blind index + ciphertext via existing pii_crypto; unique (site_id, external_deal_id, email_bidx)); chain off `alembic heads` at EXECUTE.
5. APScheduler job `poll_closed_won` in apps/api/jobs/scheduler.py (coop-expiry pattern; flag at registration + runtime; literal jitter + misfire_grace_time; no next_run_time); update tests/unit/test_scheduler_job_config.py: add id, re-derive the hard-asserted 28/24/3 counts + docstring at EXECUTE time from live registrations (N1).
B. Seed
6. CSV upload (max 10k rows, email required, optional country, hashed on ingest, plaintext dropped).
7. Match to IdentifiedVisitor by email_bidx (matched count reported; unmatched CRM rows still seeded per UD6). (N6) EVERY `IdentifiedVisitor.email_bidx` read (here and in 7b) is scoped `IdentifiedVisitor.site_id == site_id` — bidx is cross-tenant-equal, never match across sites.
7a. Exclusions (Gap 3) applied to BOTH matched visitors and unmatched CRM/CSV rows: suppression scopes `do_not_sell`/`all`/`erased`, `do_not_email`, `do_not_resolve`, agent-origin (`source_agent_visit_id`), abuse-flagged, non-person-level providers; suppression check also runs on CSV rows; (N4) company exclusion: call sibling `load_exclusions(db, site_id)` + `match_excluded(...)` keyed on the row's company_domain (NOT visitor-keyed `excluded_visitor_ids`), for every reason EXCEPT `customer`; guarded by the sibling's flag and skipped entirely (import-guarded) if the sibling module is absent at EXECUTE; `do_not_resolve` read via join to `Visitor` (it lives on Visitor, not IdentifiedVisitor).
7b. Dedicated seed builder in services/closed_won_seed.py (decrypt → SHA-256 → `create_or_update_audience`, sentinel segment_id `closed_won_seed`, same rate-limit slot reservation). (N2) upsert the `closed_won_seed` AdAudienceLink (ads_push.py:312-330 pattern) — re-push updates the same seed audience. Seed link never stores the lookalike id.
C. Lookalike
8. ads/base.py `LookalikeResult` + non-abstract `create_lookalike` (NotImplementedError default).
8a. Meta create_lookalike as a separate step after seed processing; (N7) persist lookalike id on a separate `closed_won_lookalike` AdAudienceLink row (same connection; `ad_audience_links` has no params column, so the stored lookalike's country+ratio are read back from the provider via a new adapter `get_lookalike_spec(audience_id)` (Meta GET lookalike_spec; Google userList lookalike info; deterministic mock branch) — no new column); repeat call with SAME country+ratio returns the stored lookalike (idempotent, no provider call); DIFFERENT country/ratio creates a new provider lookalike, updates the `closed_won_lookalike` row to the new id, leaves the old provider audience in place, and returns `previous_lookalike_id` in the response so the UI tells the owner; country only when version ≤ v26; <100 seed warning; surface provider error.
9. Google create_lookalike via userLists:mutate lookalike_user_list; (N7) same `closed_won_lookalike` row + same repeat semantics as 8a (same params → stored; different → new id, old kept, `previous_lookalike_id` returned); DUPLICATE_LOOKALIKE = already-exists; <1,000 warning; Demand Gen-only note; EEA fail-closed.
10. LinkedIn CSV.
D. API/UI + data lifecycle
11. Routes + schemas + flag gating (404 closed-won off; 501 ad_audiences off).
11a. routers/sites.py delete cascade + graph_erasure.py sweep by email_bidx for `crm_closed_won_contacts`.
12. Web panel: closed-won count (matched vs total), reconnect prompt, CSV upload, Create lookalike dialog (country required, ratio).
E. Tests (red-first stubs from Verification Evidence).

## Verification Evidence
Preconditions: `.venv` present (`.venv/bin/python`); Docker daemon up and :5433 listening (`lsof -nP -iTCP -sTCP:LISTEN | grep 5433`); integration DSN pinned, never `.env` (prod).
| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| G1 `.venv/bin/python -m pytest -m unit tests/unit/test_closed_won_readback.py -q` (mock deals per CRM, HubSpot won-stage via pipelines, re-window, needs_reconnect, scope string, no-PII caplog) | Fully-Automated | AC1, AC2, AC8 |
| G2 `.venv/bin/python -m pytest -m unit tests/unit/test_meta_lookalike.py -q` (subtype/origin/spec, country only ≤v26, <100 warning, provider error surfaced) | Fully-Automated | AC4, AC8 |
| G2b `.venv/bin/python -m pytest -m unit tests/unit/test_google_lookalike.py tests/unit/test_scheduler_job_config.py -q` (lookalike_user_list payload, DUPLICATE_LOOKALIKE, <1,000 warning, EEA fail-closed; scheduler job id) | Fully-Automated | AC5, AC1 |
| G3 `DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test .venv/bin/python -m pytest tests/integration/test_closed_won_seed.py -q` flag ON: sync→match→exclusions→seed→lookalike (mock); closed-won off 404; ad_audiences off 501; foreign site 404; webhook flag-first 404, oversize 413 (declared AND actual-body), no connection 404, bad HMAC reject, replay same payload → 1 row (N3); erased-tombstone bidx not ingested (N5); same email_bidx IdentifiedVisitor on another site NOT matched (N6); (N7) after seed+lookalike exactly 1 `closed_won_seed` link + 1 `closed_won_lookalike` link; repeat same country+ratio returns stored id, no new provider call; repeat different ratio returns new id + `previous_lookalike_id`=old, still 1 lookalike link | Hybrid (needs :5433) | AC3, AC7, AC9, AC1 |
| G4 Migration up/down/up on disposable postgres:16 with pinned DATABASE_URL | Hybrid | schema |
| G5 `.venv/bin/python -m pytest -m unit -q` + integration lane regression (pinned DSN) | Fully-Automated/Hybrid | no regression |
| G6 `cd apps/web && npx tsc --noEmit` | Fully-Automated | UI types |
| G7 `DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test .venv/bin/python -m pytest tests/integration/test_closed_won_erasure.py -q` (site delete removes rows; graph erasure by email_bidx removes rows) | Hybrid | AC7, GDPR |
| G8 exclusion matrix in tests/integration/test_closed_won_seed.py (each suppression scope, do_not_email, do_not_resolve, agent-origin, abuse, non-person provider, company-exclusion non-`customer` excluded / `customer` kept (domain-keyed via load_exclusions/match_excluded; skipped when sibling absent), unmatched CRM row seeded) | Hybrid | AC3, AC9 |
| KG-L Live Meta lookalike / HubSpot deals / Google Demand Gen | known-gap residual (needs-live-provider; backlog stub, gate CONDITIONAL) | AC4/AC5 live |

## Risk Evidence Pack (vc-risk-evidence-pack — manual-first)
Required before closeout: (1) PII flow diagram (CRM→bidx/ciphertext→SHA-256→Meta/Google), (2) caplog no-PII proof from G1/G3, (3) tenant-isolation 404 test output, (4) migration round-trip log, (5) flag-OFF/ON behavior diff + operator rollback (flag off; table additive), (6) G7 erasure output.

## Test Infra Improvement Notes
(none identified yet)

## Resume and Execution Handoff
1. Plan: process/features/ads-audiences/active/closed-won-lookalikes_27-11-26/closed-won-lookalikes_PLAN_27-11-26.md
2. Last completed: PVL supplement cycle 2 (N1–N6 applied)
3. Validate-contract: written below (CONDITIONAL, first pass) — re-run PVL from V1
4. Context: all-context.md, tests/all-tests.md, ads-audiences umbrella plan
5. Next: re-validate; confirm UD1–UD6; ENTER EXECUTE MODE after conversion-apis lands

## Validate Contract

Status: PASS
Date: 27-11-26
date: 2026-11-27
generated-by: outer-pvl
supersedes: 2026-11-27 (outer-pvl) — cycle-3 contract (CONDITIONAL, N7); this re-validate after supplement cycle 3 has current code evidence

Context loaded: process/context/all-context.md, process/context/tests/all-tests.md, SPEC, iteration reports 001-003, results.tsv (header + baseline + 3 cycle rows), sibling active ads plans (none touch `ad_audience_links`). Plan validator: 0 FAIL / 0 WARN. Frontmatter `name: plan:closed-won-lookalikes` confirmed.

Parallel strategy: sequential (inline fallback)
Rationale: signal score 3/7 (S2 schema/API/auth, S6 high-risk class, S7 ~23 files) -> MEDIUM -> recommended parallel subagents (fable dimension agents, opus contract write); no Agent tool in this run, so 4 Layer-1 dimensions + 4 Layer-2 sections ran inline with the same role specs (process deviation recorded). EXECUTE recommendation: sequential, one opus vc-execute-agent (sections A-D share config.py, routers/ads.py, services/ads/base.py, jobs/scheduler.py). Alternatives: parallel subagents (rejected: shared files), workflow (overkill, 1 plan), agent team (no live coordination need).

### Cycle-3 gap closure (verified against code, 27-11-26)
- N7 CLOSED — second sentinel `AdAudienceLink` row (`closed_won_lookalike`) needs no schema change: `segment_id` is String(50) with no FK and `uq_ad_audience_link` (connection_id, segment_id) gives one row per connection (models/ad_audience_link.py:24-34). Repeat-call semantics stated (same spec -> stored id, no provider call; different spec -> new provider lookalike, row updated, `previous_lookalike_id` returned). G3 asserts 1 seed link + 1 lookalike link. Site delete removes both sentinel rows: routers/sites.py:340 deletes `ad_connections`, and the link FK is `ondelete="CASCADE"`. Only caller reading links is ads_push.py:142-146 (exact segment_id match), so sentinel rows cannot collide with real segments.
- Unrequested addition `get_lookalike_spec(audience_id)` — NOT NEEDED; replaced by E7. It adds a new method on 2 adapters + mocks + 2 unverified live response shapes, and it contradicts the plan's own "same spec -> no provider call" rule (a read is still a provider call). No JSON/settings column exists on `AdAudienceLink` or `AdConnection` (models/ad_connection.py:30-53), and `crm_closed_won_contacts` is per-contact, so neither is a fit. Smallest option: encode the spec in the sentinel row's `segment_id` (E7). No schema change, no provider read, G3 assertions unchanged. Not a CONCERN.

### N1-N6 + cycle-1 regression scan — no regressions
test_scheduler_job_config.py:246 `len(calls) == 28` (N1); ads_push.py:312-330 upsert (N2); outcomes.py:513 `60/minute` + agent_mcp.py:131-143 declared+actual 413 (N3); company-exclusion module still absent (import guard stands, N4); suppression.py:23 `erased` + scheduler.py:863 sweep gate (N5); visitor.py:205 site_id + :255 email_bidx (N6); hubspot.py:26 `_SCOPES` contacts-only, ads.py:66 501, meta.py:47 v25.0, base.py:57 AudienceResult + 4 abstract methods, routers/crm.py still lacks `limiter`/`Request` imports (add both). All anchors match.

Test gates (C3 5-column table — ADDITIVE; legacy line form below):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1/AC2/AC8 | 3 CRM fetchers parse mock deals; HubSpot won stage via pipelines metadata; re-window; needs_reconnect from stored scopes; scope string has deals.read; no plaintext email in caplog | Fully-Automated | G1 `.venv/bin/python -m pytest -m unit tests/unit/test_closed_won_readback.py -q` | B |
| AC4/AC8 | Meta LOOKALIKE payload (subtype, origin_audience_id, ratio), country only while GRAPH_API_VERSION <= v26, <100 warning, provider error surfaced | Fully-Automated | G2 `.venv/bin/python -m pytest -m unit tests/unit/test_meta_lookalike.py -q` | B |
| AC5/AC1 | Google lookalike_user_list payload; DUPLICATE_LOOKALIKE -> existing; <1,000 warning; EEA fail-closed; scheduler job with literal jitter/misfire and re-derived count | Fully-Automated | G2b `.venv/bin/python -m pytest -m unit tests/unit/test_google_lookalike.py tests/unit/test_scheduler_job_config.py -q` | B |
| AC1/AC3/AC7/AC9 | Flag ON sync->match->exclusions->seed->lookalike (mock); closed-won OFF 404; ad_audiences OFF 501; foreign site 404; webhook flag-first 404, oversize 413 (declared + actual), no connection 404, bad HMAC 400, replay idempotent, rate-limited; cross-tenant bidx not matched; erased bidx not ingested; 1 seed link + 1 lookalike link; same spec -> stored id and zero adapter calls; different spec -> new id + previous_lookalike_id, still 1 lookalike link (E7) | Hybrid (needs :5433 + :6379; lsof check first) | G3 `DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test .venv/bin/python -m pytest tests/integration/test_closed_won_seed.py -q` | B |
| AC3/AC9 | Exclusion matrix: each suppression scope, do_not_email, do_not_resolve (Visitor join), agent-origin, abuse, non-person provider, company-exclusion non-customer excluded / customer kept, unmatched CRM row seeded | Hybrid (needs :5433) | G8 `DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test .venv/bin/python -m pytest tests/integration/test_closed_won_seed.py -k exclusion -q` | B |
| GDPR | Site delete removes crm_closed_won_contacts and both sentinel links (ad_connections cascade); erasure sweep deletes by email_bidx | Hybrid (needs :5433) | G7 `DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test .venv/bin/python -m pytest tests/integration/test_closed_won_erasure.py -q` | B |
| schema | Migration up/down/up chained off live heads (crm_closed_won_contacts only) | Hybrid (disposable postgres:16-alpine, DSN pinned, never the repo env file) | G4 `DATABASE_URL=<disposable DSN> .venv/bin/alembic -c apps/api/alembic.ini upgrade head && ... downgrade -1 && ... upgrade head` | B |
| regression | Existing ads/crm/agent-origin/scheduler guards unchanged | Fully-Automated + Hybrid | G5 `.venv/bin/python -m pytest -m unit -q` + integration lane with the pinned DSN | A |
| UI | web types compile | Fully-Automated | G6 `cd apps/web && npx tsc --noEmit` | B |

Failing stub (G1):
test("should parse mock closed-won deals for hubspot/pipedrive/salesforce without logging plaintext email", () => { throw new Error("NOT IMPLEMENTED — TDD stub: closed-won read-back") })
Failing stub (G2):
test("should build Meta LOOKALIKE payload with country only while GRAPH_API_VERSION <= v26", () => { throw new Error("NOT IMPLEMENTED — TDD stub: meta lookalike payload") })
Failing stub (G2b):
test("should build Google lookalike_user_list payload and treat DUPLICATE_LOOKALIKE as idempotent", () => { throw new Error("NOT IMPLEMENTED — TDD stub: google lookalike payload") })
Failing stub (G5):
test("should keep existing unit lane green", () => { throw new Error("NOT IMPLEMENTED — TDD stub: regression") })
Failing stub (G6):
test("should compile web types", () => { throw new Error("NOT IMPLEMENTED — TDD stub: tsc") })

Named residuals (Known-Gap, gap-resolution D — never a proving strategy): KG-L live Meta / Google / HubSpot / Pipedrive / Salesforce legs (needs-live-provider, double opt-in only); KG-SF Salesforce orgs without contact roles; KG-HS `hs_is_closed_won` internal name (pipelines path primary). Backlog stub: `process/features/ads-audiences/backlog/closed-won-lookalikes-live-provider-gates_NOTE_27-11-26.md` (create at EXECUTE closeout). Not blockers: env preconditions (:5433/:6379), provisional UD1-UD6.

Legacy line form:
- read-back: Fully-automated: G1 | hybrid: G3 (needs :5433)
- lookalike payloads: Fully-automated: G2, G2b | known-gap: KG-L documented
- seed safety + lookalike storage: hybrid: G8, G3
- GDPR cascade: hybrid: G7 (needs :5433)
- schema: hybrid: G4 (disposable PG)
- UI: Fully-automated: G6

Dimension findings:
- Infra fit: PASS — APScheduler (not Celery), 501 convention, limiter + in-route body cap, sentinel-link upsert all match code.
- Test coverage: PASS — G3 now proves 1+1 sentinel links, stored-id reuse with zero adapter calls, new-spec swap; every developed behavior has an FA or Hybrid gate; live legs are named residuals only.
- Breaking changes: PASS — N7 closed with zero schema change to `ad_audience_links`; one additive table; additive non-abstract adapter method; get_lookalike_spec dropped (E7) so no new adapter surface.
- Security surface: PASS — site-scoped bidx (N6), rate limit + body cap + HMAC order (N3), erased-person ingest skip (N5), sentinel links removed on site delete. UD5 trade-off stands: generic_webhook secret holder can forge inbound deals (record in adversarial-validation.json).
- Section A (read-back): PASS — anchors unchanged.
- Section B (seed): PASS — seed-link upsert matches ads_push.py:312-330; seed link never stores the lookalike id.
- Section C (lookalike): PASS — lookalike row + repeat semantics defined; spec stored locally per E7.
- Section D (API/UI + lifecycle): PASS — site-delete cascade verified (sites.py:340 + FK CASCADE); previous_lookalike_id surfaced in response/UI.

Open gaps: none in scope. Known residuals KG-L, KG-SF, KG-HS. Cross-plan: EXECUTE order conversion-apis -> closed-won-lookalikes -> ad-insights-seo-aeo.

What This Coverage Does NOT Prove:
- G1: real CRM response shapes, pagination past page 1, real rate limits, reconnect UX for old HubSpot tokens.
- G2/G2b: provider acceptance of payloads, actual lookalike size, Demand Gen attachment, async origin readiness.
- G3/G8: real APScheduler timing, multi-host contention, real Zapier/Make signatures, the sibling company-exclusion matcher's own correctness, slowapi limit under multiple replicas; that a stored lookalike id still exists provider-side (owner deleting it in Ads Manager leaves a stale id until a new-spec create).
- G7: deletion of hashes already sent to Meta/Google (provider-side, out of scope).
- G4: production apply (operator step; re-derive prod head).
- G5: behavior with flags ON at prod data volume.
- G6: runtime UI behavior (no Playwright leg; Clerk auth-harness gap persists).

Risk evidence pack (vc-risk-evidence-pack, manual-first; mustStopBeforeFinalize true): write to `closed-won-lookalikes_27-11-26/harness/` — `risk-gate.json` (riskClass "PII egress + trust-boundary + schema/migration + public API + CRM OAuth scope"), `context-snippets.json` (file:line for seed builder, webhook, erasure, cascade, link storage), `verification.json` (G1-G8 incl. failure cases), `review-decision.json` (explicit APPROVE/REJECT + rationale), `adversarial-validation.json` (webhook forgery by secret holder, replay, oversize, cross-tenant bidx, suppressed/erased egress, competitor seeding, duplicate lookalike, segment_id injection via country/ratio). Missing pack = not finalizable.

Execute-agent instructions:
- E1 Run `alembic -c apps/api/alembic.ini heads` with DATABASE_URL pinned to localhost:5433 or the disposable DSN before writing the migration. Never unpinned (repo env file = Supabase PROD).
- E2 Never call live providers. Mock path only; docs only for shapes.
- E3 G3/G8 must run flag ON; flag-OFF-only evidence is vacuous.
- E4 No plaintext email in logs or columns; decrypt only in-process for the SHA-256 egress (ads_push.py:98-127 path).
- E5 Re-read services/ads/base.py, meta.py, google.py, config.py, jobs/scheduler.py, tests/unit/test_scheduler_job_config.py after conversion-apis lands; append, never overwrite; re-derive scheduler counts.
- E6 Webhook order: `@limiter.limit("60/minute")`; flag -> 404; declared+actual body cap -> 413; generic_webhook connection -> 404; HMAC (`decrypt_key`, `hmac.compare_digest`) -> 400; never log the body. Add `limiter` and `Request` imports to routers/crm.py.
- E7 (overrides steps 8a/9 text on get_lookalike_spec) Do NOT add `get_lookalike_spec` to any adapter. Store the spec in the lookalike sentinel's `segment_id` as `closed_won_lookalike:{COUNTRY}:{ratio_or_expansion}` (e.g. `closed_won_lookalike:US:0.05`, `closed_won_lookalike:US:BALANCED`; max ~32 of 50 chars). Validate country `^[A-Z]{2}$` and ratio/expansion against a fixed allow-list BEFORE building the string (422 otherwise). Find the row with `segment_id LIKE 'closed_won_lookalike:%'` for the connection, inside a transaction holding `SELECT ... FOR UPDATE` on the `closed_won_seed` link row (always exists before a lookalike). Same string -> return stored `platform_audience_id`, zero adapter calls. Different -> call `create_lookalike`, then UPDATE the same row's `segment_id` + `platform_audience_id` (or INSERT if none), return `previous_lookalike_id`. Keep exactly one lookalike row per connection.
- E8 Plan steps 8a/9 + Touchpoints still mention `get_lookalike_spec`; record the E7 deviation in the phase report rather than editing the plan mid-EXECUTE.

Gate: PASS (0 FAIL, 0 CONCERN after 3 PVL supplement cycles; N7 closed; get_lookalike_spec replaced by E7 local spec storage)
Accepted by: n/a — PASS. Named residuals KG-L/KG-SF/KG-HS are needs-live-provider known-gaps; UD1-UD6 remain provisional pending user confirmation (not blockers).

## Autonomous Goal Block

```
SESSION GOAL: Closed-won lookalikes — CRM closed-won read-back + seed + Meta/Google lookalike, flag closed_won_lookalikes_enabled OFF
Charter + umbrella plan: N/A — single plan (process/features/ads-audiences/active/closed-won-lookalikes_27-11-26/closed-won-lookalikes_PLAN_27-11-26.md)
Autonomy: per feedback_autonomous_phase_execution.md — reversible decisions auto; subagent delegation mandatory (opus execute/tester)
Hard stop conditions / safety constraints:
- Never run alembic or any DB script against the repo env DATABASE_URL (Supabase PROD); pin localhost:5433 or a disposable DSN
- No live provider calls (Meta/Google/HubSpot/Pipedrive/Salesforce); mock only
- No plaintext email at rest or in logs; only SHA-256 hashes leave Beam
- Seed reads are site-scoped; global email_bidx never matched across tenants
- Suppressed, erased, do_not_resolve, agent-origin, abuse-flagged, and competitor-excluded people never enter a seed
- No get_lookalike_spec adapter method; lookalike spec lives in the sentinel segment_id (contract E7); no schema change to ad_audience_links
- EXECUTE order: conversion-apis -> closed-won-lookalikes -> ad-insights-seo-aeo
Next phase: EXECUTE: closed-won-lookalikes_PLAN_27-11-26.md (after conversion-apis lands; confirm UD1-UD6)
Validate contract: inline in plan
Execute start: G1 G2 G2b G5 G6 (fully-auto) | G3 G8 G7 G4 (hybrid, :5433/disposable PG) | probe: none | high-risk pack: yes
```
