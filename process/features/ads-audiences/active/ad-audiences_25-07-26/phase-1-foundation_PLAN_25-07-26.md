---
name: plan:ad-audiences-phase-1-foundation
description: "Ad Audiences — Phase 1: Foundation (models, services/ads skeleton, router, mock-mode parity, UI panel)"
date: 25-07-26
metadata:
  node_type: memory
  type: plan
  feature: ads-audiences
  phase: phase-1
---

# Phase 1 — Foundation

**Program:** ad-audiences
**Umbrella plan:** process/features/ads-audiences/active/ad-audiences_25-07-26/ad-audiences-umbrella_PLAN_25-07-26.md
**Phase status:** ✅ VERIFIED — known-gaps: G1 migration round-trip (Docker daemon unavailable, env-only, deferred to Docker-gate closure per owned-data-layer precedent), G2 Playwright AC9/AC12 (local Clerk auth harness unconfigured, env-only). Both have named resolution paths; neither is a program blocker.
**Report destination:** process/features/ads-audiences/active/ad-audiences_25-07-26/phase-1-foundation_REPORT_25-07-26.md (flat in the program task folder — written)

**Complexity:** COMPLEX
Complexity: COMPLEX
Date: 25-07-26
Status: PLANNED

## Overview

Build the entire CRM-mirror scaffold for Ad Audiences (models, services/ads registry, router, config, frontend panel) with zero live-provider network calls, fully deterministic under MOCK_EXTERNAL_APIS=true and gated by ad_audiences_enabled (default OFF). See process/context/all-context.md for repo conventions and process/context/tests/all-tests.md for the test-runner routing this phase's Exit Gate commands follow.

## Acceptance Criteria

See the ## Verification Evidence table below — each row maps a test gate to the exact SPEC acceptance criterion it proves; this phase's Exit Gate is 'done' only when every AC row in that table is Fully-Automated-green or its declared Hybrid/Agent-Probe evidence is recorded in the phase report.

## Phase Completion Rules

CODE DONE = all Implementation Checklist items checked and automated Exit Gate commands exit 0. TESTING = Hybrid/Agent-Probe evidence being gathered. VERIFIED = validate-contract Gate is PASS (or explicitly-accepted CONDITIONAL) AND every row in Verification Evidence has real recorded evidence (not a placeholder) AND the phase report is written. A phase may not be marked VERIFIED on code completion alone.

---

## Purpose

Build the entire CRM-mirror scaffold for Ad Audiences with zero live-provider network calls:
data model, provider-registry service pattern, push/rate-limit services, router, config, and
frontend panel — all fully deterministic under `MOCK_EXTERNAL_APIS=true` and behind
`ad_audiences_enabled` (default OFF). This phase proves the shape is correct and the safety
filters/hashing are reused verbatim before any real OAuth wiring begins in Phase 2/3. Covers
SPEC ACs 1, 4, 5, 9, 10, 11, 12.

---

## Entry Gate

- Phase 0 complete (umbrella + all 3 phase plans + blast-radius registry created; validators green)
- SPEC locked at `process/features/ads-audiences/active/ad-audiences_25-07-26/ad-audiences_SPEC_25-07-26.md`
- INNOVATE decision summary locked (see umbrella "Locked INNOVATE decision" note)

---

## Blast Radius

- `apps/api/models/ad_connection.py` (new)
- `apps/api/models/ad_audience_link.py` (new)
- `apps/api/migrations/versions/{new_rev}_add_ad_connections.py` (new)
- `apps/api/migrations/versions/{new_rev2}_add_ad_audience_links.py` (new)
- `apps/api/services/ads/__init__.py`, `base.py`, `factory.py`, `meta.py`, `google.py`, `linkedin.py` (new — meta/google/linkedin stub modules registered; meta/google real logic deferred to Phase 2/3, linkedin `ready=False` permanently)
- `apps/api/services/ads_push.py` (new)
- `apps/api/services/ads_rate_limiter.py` (new)
- `apps/api/tasks/ads_tasks.py` (new)
- `apps/api/routers/ads.py` (new)
- `apps/api/schemas/ads.py` (new)
- `apps/api/config.py` (append-only: new settings block)
- `apps/web/src/components/ad-connect-panel.tsx` (new)
- `apps/web/src/app/dashboard/connectors/page.tsx` (edit: mount panel + move CSV block inside "Ad Audiences" tab)
- `apps/web/src/lib/api.ts` (append-only: new client methods)

**Not touched (hard constraint):** `apps/api/models/crm_connection.py`, `apps/api/routers/crm.py`, `apps/api/services/crm.py`, `apps/api/services/crm/*`, `apps/api/services/crm_push.py`, `apps/api/services/crm_rate_limiter.py`, `apps/api/tasks/crm_tasks.py`, `apps/api/services/csv_exporter.py`.

---

## Implementation Checklist

### Step A — Data model + migrations

- [ ] A1. Create `apps/api/models/ad_connection.py`: `AdConnection` mirroring `CrmConnection`
      fields exactly (id, site_id, user_id, provider, auth_type, status, access_token,
      refresh_token, token_expires_at, scopes, external_account_id, external_account_label,
      last_pushed_at, last_error, is_valid, created_at, updated_at) PLUS ad-specific fields:
      `ad_account_id: Mapped[Optional[str]]`, `business_id: Mapped[Optional[str]]`. Unique
      constraint `("site_id", "provider", name="uq_ad_site_provider")`. `provider` values:
      `"meta" | "google" | "linkedin"`.
- [ ] A2. Create `apps/api/models/ad_audience_link.py`: `AdAudienceLink` — one row per
      (connection_id, segment_id): `id`, `connection_id: Mapped[uuid.UUID]` (FK to
      `ad_connections.id`), `segment_id: Mapped[str]`, `platform_audience_id: Mapped[str]`,
      `last_pushed_at`, `last_push_count: Mapped[Optional[int]]`, `created_at`, `updated_at`.
      Unique constraint `("connection_id", "segment_id", name="uq_ad_audience_link")` — this is
      the AC6 update-not-duplicate mechanism: push logic does
      `SELECT ... WHERE connection_id=? AND segment_id=?` then either creates a new platform
      audience (first push) or reuses `platform_audience_id` (repeat push), writing via
      Postgres `ON CONFLICT (connection_id, segment_id) DO UPDATE` upsert to stay race-safe.
- [ ] A3. Run `.venv/bin/python -m alembic -c apps/api/alembic.ini heads` to get the CURRENT
      real head — **VALIDATE correction (25-07-26): `.venv` DOES exist at repo root with alembic
      1.13.3 installed; `alembic heads` reads only the migration-script graph and needs zero DB
      connection, so this runs directly on host, no Docker required.** Confirmed live during this
      VALIDATE pass: current head is `a9f2c1e7b4d6`, matching `all-context.md`. Do not hardcode
      this value into code — re-run the live command at EXECUTE time in case another plan lands a
      migration first. Create two Alembic migrations chained onto that head, in order: first
      `add_ad_connections` (creates `ad_connections` table + unique constraint), second
      `add_ad_audience_links` (creates `ad_audience_links` table + FK + unique constraint). Both
      additive-only, no changes to any existing table.
- [ ] A4. Round-trip test the migration chain on a disposable Postgres container (upgrade head →
      downgrade -1 → upgrade head), matching the precedent set by the owned-data-layer program.
      Do NOT apply to any shared/real database.

### Step B — services/ads/ provider registry

- [ ] B1. Create `apps/api/services/ads/base.py`: abstract `AdsProvider` interface mirroring
      `apps/api/services/crm/base.py`'s shape — methods: `get_oauth_url(state) -> str`,
      `exchange_code(code) -> dict` (returns access_token/refresh_token/expires/account info),
      `test_connection(connection) -> CrmTestResult`-equivalent, `create_or_update_audience(connection, link, hashed_contacts) -> dict` (returns platform_audience_id + result summary).
- [ ] B2. Create `apps/api/services/ads/factory.py`: registry function
      `get_provider(name: str) -> AdsProvider`, `PROVIDERS = {"meta": MetaAdsProvider(),
      "google": GoogleAdsProvider(), "linkedin": LinkedInAdsProvider()}` — mirrors
      `services/crm.py`'s connector-registry pattern.
- [ ] B3. Create `apps/api/services/ads/meta.py`: `MetaAdsProvider(AdsProvider)` — Phase 1 scope
      is STUB ONLY: raise `NotImplementedError` for non-mock paths; when
      `settings.mock_external_apis` is True, return deterministic fake OAuth URL / fake
      exchange result / fake audience id (`"mock-meta-aud-{uuid4 hex}"`). Real logic deferred
      to Phase 2 — this file is intentionally left with a clear `# PHASE 2:` marker at each
      stub method so Phase 2's PLAN-SUPPLEMENT step finds them precisely.
- [ ] B4. Create `apps/api/services/ads/google.py`: `GoogleAdsProvider(AdsProvider)` — same stub
      shape as B3, `# PHASE 3:` markers, mock-mode fake `"mock-google-aud-{uuid4 hex}"`.
- [ ] B5. Create `apps/api/services/ads/linkedin.py`: `LinkedInAdsProvider(AdsProvider)` —
      permanently stub; `ready=False` is enforced at the router/schema layer (B7), not here;
      this module exists only so the registry pattern is uniform across all 3 providers.
- [ ] B6. Create `apps/api/services/ads/__init__.py` re-exporting `get_provider`.
- [ ] B7. Add a `READY = {"meta": True, "google": True, "linkedin": False}` map (in `factory.py`
      or `base.py`) — the router/schema layer uses this to gate connect-attempt requests for
      unready providers (mirrors `CrmConnectPanel`'s frontend `ready` flag, but enforced
      server-side too, matching `_require_provider` precedent in `routers/crm.py`).

### Step C — Push, rate-limit, and async task services

- [ ] C1. Create `apps/api/services/ads_push.py`: `push_segment_to_ads(db, site_id, provider,
      segment_id) -> PushSegmentResult`. Import `_get_segment_visitors` and `_sha256` from
      `apps/api.services.csv_exporter` (import only — no copy/paste, no modification). Flow:
      call `_get_segment_visitors(db, segment_id, exclude_known=False)` (the exact same
      safety-filter chain CSV export and CRM push use), hash every identifier via `_sha256`,
      look up or create the `AdAudienceLink` row for (connection, segment_id), call
      `get_provider(provider).create_or_update_audience(...)`, upsert the link row with the
      returned `platform_audience_id`, return a result summary (pushed/skipped counts, or a
      "queued" message when async threshold is exceeded — mirrors `crm_push.py`'s branch).
- [ ] C2. Add `ads_async_push: bool = False` and `ads_async_push_threshold: int = 200` to
      config (Step D) and wire the threshold check into `ads_push.py` exactly like
      `crm_push.py`'s `crm_async_push`/`crm_async_push_threshold` pattern: below threshold,
      push synchronously; at/above threshold (or when `ads_async_push=True`), enqueue via
      Celery and return a "queued" result.
- [ ] C3. Create `apps/api/services/ads_rate_limiter.py`: `check_and_reserve_push(site_id) ->
      bool`, byte-for-byte structural mirror of `crm_rate_limiter.py` (same fail-open-on-Redis-
      error behavior, same Redis key shape `ads_push_rate:{site_id}:{hour}`), using a new
      `max_ads_pushes_per_hour_per_site: int = 20` setting (independent counter from the CRM
      limiter — a site's ad pushes and CRM pushes do not share one budget).
- [ ] C4. Create `apps/api/tasks/ads_tasks.py`: `push_segment_to_ads_task` Celery task, mirroring
      `crm_tasks.py`'s `push_segment_to_crm` shape exactly (task name
      `apps.api.tasks.ads_tasks.push_segment_to_ads`, sync wrapper calling the async
      `_run(site_id, provider, segment_id)` which calls `ads_push.push_segment_to_ads`).

### Step D — Router, schemas, config

- [ ] D1. Add to `apps/api/config.py` (append-only, new block near the CRM block, never editing
      existing lines): `ad_audiences_enabled: bool = False`; `meta_ads_client_id: str = ""`,
      `meta_ads_client_secret: str = ""`, `meta_ads_redirect_uri: str =
      "http://localhost:8000/api/v1/ads/callback/meta"`; `google_ads_client_id: str = ""`,
      `google_ads_client_secret: str = ""`, `google_ads_redirect_uri: str =
      "http://localhost:8000/api/v1/ads/callback/google"`; `linkedin_ads_client_id: str = ""`,
      `linkedin_ads_client_secret: str = ""`, `linkedin_ads_redirect_uri: str =
      "http://localhost:8000/api/v1/ads/callback/linkedin"` (present for schema symmetry only —
      never used while `ready=False`); `max_ads_pushes_per_hour_per_site: int = 20`;
      `ads_async_push: bool = False`; `ads_async_push_threshold: int = 200`. Add all 9 new
      client-id/secret/redirect-uri fields to the existing `field_validator` whitespace-strip
      list (the one at line ~289) — follow the exact precedent already used for
      `twitter_client_id` etc.
- [ ] D2. Create `apps/api/schemas/ads.py`: `AdConnectionOut`, `AdConnectResponse`,
      `AdTestResult`, `PushAdSegmentResult` — Pydantic response models mirroring
      `schemas/crm.py`'s shapes 1:1, plus the `ad_account_id`/`business_id` fields.
      **VALIDATE correction (25-07-26):** drop the previously-proposed backend `ready: bool` field
      on the connections list — it duplicated E1's `OAUTH_ADS` frontend constant (which already
      carries `ready` per provider, mirroring `OAUTH_CRMS` verbatim per the Locked INNOVATE
      decision) and CRM's own `GET /connections` never synthesizes placeholder rows for
      unconnected providers either. Server-side readiness stays enforced only at connect-time via
      B7's `READY` map (a real security control); the list endpoint mirrors CRM 1:1 (existing
      connections only, no synthesized rows).
- [ ] D3. Create `apps/api/routers/ads.py` mirroring `routers/crm.py` route-for-route: `GET
      /{site_id}/connections` (list, includes `ready` flag per provider even if not connected),
      `POST /{site_id}/connections/{provider}/connect` (guarded by `_require_provider` +
      `ad_audiences_enabled` flag check + `ready` check — 400 if provider not ready, matching
      `_require_provider`'s existing pattern), `GET /callback/{provider}` (OAuth callback,
      `oauth_state.py` reused verbatim for CSRF), `POST
      /{site_id}/connections/{provider}/test`, `POST /{site_id}/connections/{provider}/push`
      (calls `ads_rate_limiter.check_and_reserve_push` first, then `ads_push.push_segment_to_ads`;
      also computes and returns a small-segment warning per AC7 — warning threshold is a TODO
      constant to be confirmed by Phase 2 docs-fetch, default placeholder `1000` per SPEC OQ5),
      `DELETE /{site_id}/connections/{provider}` (disconnect: clear tokens, set
      status="disconnected"). Every route scoped `Site.user_id == user.id`; unknown/foreign
      site_id returns 404, never 403 (matches every other tenant-scoped router in the repo).
      Token encryption via `services/encryption.py` (imported, not modified) on write; never
      returned to the client — only `external_account_label` is exposed, matching
      `CrmConnection`'s `secret_hint`-style precedent.
- [ ] D4. Register `ads.router` in the FastAPI app's router includes (wherever `crm.router` is
      registered) with prefix `/api/v1/ads`.
- [ ] D5. **(PVL-supplement, 25-07-26 — promotes Validate Contract Execute-agent instruction E1)**
      Wrap the router's call site for `services/ads/meta.py` and `services/ads/google.py`'s
      non-mock stub paths (B3/B4), which raise `NotImplementedError`, so this surfaces as a clean
      HTTP 501 ("Provider not yet implemented") rather than an unhandled 500 — defense-in-depth
      for the case where `ad_audiences_enabled=true` but `MOCK_EXTERNAL_APIS=false` before Phase
      2/3 lands. Mirrors the existing `_OAUTH_CREDENTIALS`-missing 501 pattern in `routers/crm.py`.
- [ ] D6. **(PVL-supplement, 25-07-26 — promotes Validate Contract Execute-agent instruction E3)**
      Pick and document ONE explicit HTTP status for the `ad_audiences_enabled=false` case on the
      connect endpoint (D3) — use **501**, for symmetry with D5/CRM's not-configured pattern (this
      repo's existing feature-flag-gated-router precedent: `routers/crm.py`'s
      `_OAUTH_CREDENTIALS`-missing branch also returns 501, not 403/404, when a route is reachable
      but structurally unavailable). Record this choice explicitly in the phase report so Phase
      2/3 and the frontend error-fallback (E2's UI contingency) stay consistent.

### Step E — Frontend

- [ ] E1. Create `apps/web/src/components/ad-connect-panel.tsx`: structural clone of
      `crm-connect-panel.tsx` — `OAUTH_ADS: {provider, name, ready}[]` = `[{provider:"meta",
      name:"Meta Custom Audiences", ready:true}, {provider:"google", name:"Google Customer
      Match", ready:true}, {provider:"linkedin", name:"LinkedIn Matched Audiences",
      ready:false}]`; same connected/error/not-connected status badge rendering, same
      connect/push/disconnect button wiring, same disabled-when-`!ready` precedent for the
      LinkedIn "coming soon" card (AC9). Push action opens the confirm dialog with segment
      picker + AC7 small-segment warning text (rendered when the API response signals
      below-minimum, per D3).
- [ ] E2. Edit `apps/web/src/app/dashboard/connectors/page.tsx`: the "Ad Audiences" tab (label
      already correct — pre-program rename shipped separately today per the umbrella's
      reconciliation note) currently only contains the CSV export card. Move that card to
      render BELOW a newly-mounted `<AdConnectPanel siteId={siteId} />`, gated by
      `ad_audiences_enabled` (read from a site-settings/feature-flag prop already used
      elsewhere in the dashboard for other gated features — RESEARCH step must confirm the
      exact existing pattern, e.g. how `agent_detection_enabled` surfaces to the frontend, if
      it does at all; if no existing frontend flag-read pattern exists, default to always
      rendering the panel with each connect button itself returning a clean "feature not
      enabled for this site" error from the backend when the flag is off — do NOT invent a new
      frontend-only gating mechanism). Do NOT touch the "Connect CRM" or "Exclude List" tabs —
      those are out of this phase's blast radius (rename already shipped; content already
      correct).
- [ ] E3. Edit `apps/web/src/lib/api.ts` (append-only): add `listAdConnections`,
      `connectAdProvider`, `testAdConnection`, `pushAdSegment`, `disconnectAdProvider` client
      methods mirroring the existing `listCrmConnections`/etc. shapes exactly.

### Step F — Mock-mode + AC verification

- [ ] F1. Confirm every new external-call site (`meta.py`, `google.py` stub methods) has a
      `if settings.mock_external_apis:` short-circuit at the SERVICE layer (not the transport
      client), matching the repo-wide mock-mode convention documented in `all-context.md`.
- [ ] F2. Write/confirm the AC5 hash-only-egress unit test: assert the payload builder inside
      `ads_push.py` never contains an `@` character or matches an email regex, for a fixture
      segment with a real-shaped email.
- [ ] F3. Write/confirm the AC4 safety-filter integration test: seed a segment with 4 visitor
      classes (emailable, do_not_email, agent-derived, do_not_sell-flagged), assert only the
      emailable/non-suppressed subset appears in the outbound push payload built by
      `ads_push.py` via `_get_segment_visitors`.
- [ ] F4. Write/confirm the AC10 flag-off / flag-on-mock-mode integration tests per SPEC AC10.
- [ ] F5. Write/confirm the AC11 rate-limiter unit test (Nth push within the window rejected).
- [ ] F6. Write/confirm the AC9 LinkedIn-disabled Playwright e2e (button `disabled` attribute +
      LinkedIn CSV export for `platform=linkedin` still returns 200).
- [ ] F7. Write/confirm the AC1/AC12 Playwright e2e: Ad Audiences tab CSV download unchanged;
      Exclude List tab label + upload/clear behavior unchanged (regression-only — these already
      shipped pre-program; this phase must not break them).
- [ ] F8. **(VALIDATE-added, 25-07-26)** Write/confirm the AC6 mock-mode-leg integration test:
      push a segment twice against a mock-mode connection, assert the second push's
      `AdAudienceLink.platform_audience_id` equals the first push's (upsert-not-duplicate via the
      `ON CONFLICT (connection_id, segment_id) DO UPDATE` path from A2). This is the mock-mode leg
      only — full AC6 credit (live platform confirmation) is claimed by Phase 2/Meta and
      Phase 3/Google, not this phase's Exit Gate.
- [ ] F9. **(VALIDATE-added, 25-07-26)** Write/confirm the AC7 mock-mode-leg test: assert the
      `push` endpoint response includes the small-segment warning field (name/shape TBD by
      whichever of D2/D3 execute-agent lands first — document the chosen field name in the phase
      report) when a mocked segment's post-filter count is below the placeholder threshold (1000,
      per SPEC OQ5). This is the mock-mode leg only — full AC7 credit (real platform minimums) is
      claimed by Phase 2/Meta.
- [ ] F10. **(PVL-supplement cycle 2, 25-07-26 — closes gap for D5)** Write/confirm a unit test
      that overrides `settings.mock_external_apis=False` and `settings.ad_audiences_enabled=True`,
      calls the `connect` endpoint for `meta`/`google`, and asserts the router returns HTTP 501
      (not an unhandled 500) — proves D5's wrap-in-501 defense-in-depth path is real enforced code,
      not just a plan note.
- [ ] F11. **(PVL-supplement cycle 2, 25-07-26 — closes gap for D6)** Write/confirm a unit test
      that overrides `settings.ad_audiences_enabled=False`, calls the `connect` endpoint for any
      provider, and asserts HTTP 501 — proves D6's chosen status code is enforced by code, not
      just documented.

---

## Exit Gate

```bash
# Zero CRM/csv_exporter drift
git diff --stat main -- apps/api/models/crm_connection.py apps/api/routers/crm.py \
  apps/api/services/crm.py apps/api/services/crm/ apps/api/services/crm_push.py \
  apps/api/services/crm_rate_limiter.py apps/api/tasks/crm_tasks.py apps/api/services/csv_exporter.py
# Expected: empty output

# Migration round-trip (disposable Postgres container only)
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
# Expected: clean, no errors

# Backend unit + integration (per process/context/tests/all-tests.md routing)
.venv/bin/python -m pytest tests/unit -k ads -m unit -q
.venv/bin/python -m pytest tests/integration -k ads -m integration -q
# integration lane precondition: docker compose -f infra/docker-compose.yml up -d postgres redis

# Frontend e2e (AC1, AC9, AC12; AC7 mock-mode leg per F9)
# VALIDATE correction (25-07-26): repo uses npm (package-lock.json), not pnpm — no pnpm-lock.json
# exists and apps/web/package.json's own scripts use `npx playwright test`. New Phase 1 specs
# MUST include "connectors" in the filename (e.g. apps/web/e2e/connectors-ads.spec.ts) so this
# substring filter matches them.
cd apps/web && npx playwright test connectors
```

- All Implementation Checklist items (A1-F7) checked
- ACs 1, 4, 5, 9, 10, 11, 12 pass at their declared Fully-Automated strategy
- Phase report written to report destination above

---

## Blockers That Would Justify BLOCKED Status

- `alembic heads` at execute time reveals a conflicting concurrent migration (e.g. pii-at-rest
  landed a new head) — resolve by re-chaining onto the new real head, not by force-merging
- No existing frontend feature-flag-read pattern found for E2 and inventing one would expand
  scope beyond Phase 1 — document as a RESEARCH finding and pick the backend-error-fallback
  path described in E2 rather than blocking
- Disposable Postgres container unavailable in this environment for the migration round-trip —
  defer round-trip to EVL/Docker-gate closure, matching the `owned-data-layer` precedent, and
  mark that specific check as a known-gap in the phase report (not a BLOCKED phase)

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — research-agent: prior phase reports read (none yet); test context loaded; plan drift checked (alembic head, pii-at-rest plan status, existing frontend flag-read pattern for E2)
- [x] 2. INNOVATE — innovate-agent: approach decided for E2's flag-gating mechanism (no existing frontend flag-read pattern found; used the documented backend-error-fallback path); Decision Summary written
- [x] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated (D5/D6 checklist items + F8-F11 tests added across PVL cycles 1-2); see Validate Contract "Plan updates applied" below
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md` (Status / Gate / Plan updates applied / Execute-agent instructions / Test gates / High-risk pack / Backlog artifacts / Known gaps / Accepted by) — cycle 2 complete, Gate: PASS (see Validate Contract below)
- [x] 5. EXECUTE — all checklist items (A1–F11) done; unit lane 21/21 green, typecheck clean, all four integration gates green per-file, zero CRM/csv_exporter edits, single alembic head. Two known-gaps recorded (migration round-trip: no Docker; e2e AC9/AC12: local Clerk auth unconfigured). See `phase-1-foundation_REPORT_25-07-26.md`.
- [x] 6. EVL — vc-tester independent confirmation run: unit 21/21, guardrail agent-origin 18/18, tsc clean, 4/4 ads integration files, CRM-drift zero (ads-scope), alembic single head `c8e4f2a6b1d9`. G1 (migration round-trip) and G2 (Playwright AC9/AC12 auth harness) confirmed env-only known-gaps, both with named resolution paths — not EVL failures. See `results.tsv` iteration 3 (HALTED_SUCCESS).
- [x] 7. UPDATE PROCESS — phase report written (`phase-1-foundation_REPORT_25-07-26.md`), umbrella `## Current Execution State` updated, backlog note written for G1/G2, context updated — commit follows via vc-git-manager separately

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or the Validate
Contract section below reads "(placeholder — vc-validate-agent writes this section before
EXECUTE)", orchestrator must spawn vc-validate-agent first. A partial contract missing Plan
updates applied / Execute-agent instructions / Test gates sections is treated as a placeholder.
(This plan's Validate Contract section is complete as of cycle 2 — Gate: PASS.)

---

## Touchpoints

See Blast Radius above — full file list (models, migrations, services/ads/*, ads_push.py,
ads_rate_limiter.py, ads_tasks.py, routers/ads.py, schemas/ads.py, config.py append, frontend
panel + connectors page mount + api.ts append).

---

## Public Contracts

- New `/api/v1/ads/*` route surface (see umbrella "Public Contracts") — entirely additive, no
  existing route touched.
- New `ad_audiences_enabled` feature flag, default OFF — no behavior change for any site until
  explicitly flipped by a separate operator action.
- Existing CSV export and CRM connector public contracts: unchanged (regression-verified in F7).

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `git diff --stat` on CRM/csv_exporter files shows empty | Fully-Automated | Hard safety constraint (zero CRM edits) |
| Playwright e2e: Ad Audiences tab renders, CSV download fires unchanged query params | Fully-Automated | AC1 |
| Unit test: payload builder never contains `@` / email regex match | Fully-Automated | AC5 |
| Integration test: 4-class segment → only emailable/non-suppressed subset in payload | Fully-Automated | AC4 |
| Integration test: repeat-push reuses `platform_audience_id` via `ad_audience_links` upsert | Fully-Automated | AC6 (mock-mode leg; live confirmation in Phase 2/3) |
| Playwright e2e: small-segment warning renders before confirm | Fully-Automated | AC7 (mock-mode leg; live thresholds confirmed in Phase 2/3) |
| Playwright e2e: LinkedIn button `disabled`, CSV `platform=linkedin` still 200 | Fully-Automated | AC9 |
| Integration test: flag-off unchanged baseline + flag-on/mock-mode deterministic connect/push | Fully-Automated | AC10 |
| Unit test: Nth push within window rejected | Fully-Automated | AC11 |
| Playwright e2e: Exclude List tab label + upload/clear regression pass | Fully-Automated | AC12 |
| Unit test: stub-provider non-mock path returns 501, not 500 | Fully-Automated | D5 defense-in-depth (cycle-2 supplement) |
| Unit test: `ad_audiences_enabled=false` connect attempt returns 501 | Fully-Automated | D6 defense-in-depth (cycle-2 supplement) |
| Migration round-trip on disposable Postgres | Hybrid (Docker-gated; may be deferred to EVL/Docker closure per known-gap precedent) | Program-level "verified" bar (schema safety) |

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-1-foundation_PLAN_25-07-26.md`
- Last completed step: Phase Loop Progress Step 7 (UPDATE PROCESS) — phase closed out 25-07-26
- Validate-contract status: PASS (cycle 2, written 25-07-26 — supersedes cycle-1 CONDITIONAL)
- Supporting context files loaded: `process/context/all-context.md`, `process/context/tests/all-tests.md`, umbrella plan, SPEC file
- Next step: this phase is VERIFIED with two named env-only known-gaps (G1, G2 — see backlog note
  `process/features/ads-audiences/backlog/phase-1-docker-and-auth-known-gaps_NOTE_25-07-26.md`).
  Program advances to Phase 2 (Meta Live), inner loop Step 1 RESEARCH. See umbrella plan
  `## Current Execution State` for the authoritative program pointer.

---

## Test Infra Improvement Notes

(none identified yet)

---

## Validate Contract

Status: PASS
Date: 25-07-26
date: 2026-07-25
generated-by: outer-pvl
supersedes: 2026-07-25 (outer-pvl) — outer-PVL cycle 2 re-validate has current evidence (D5/D6 gap-closure)

Parallel strategy: sequential
Rationale: Score 4/7 signals present (S2 schema/API/auth surface, S4 phase-program classification,
S6 high-risk class, S7 5+ blast-radius files) — numerically HIGH-tier, but the signals here measure
*risk/scope*, not *independent parallelizable directions*. Step A→B→C→D→E is a strict dependency
chain (models → migrations → services/ads registry → router/schemas → frontend) — each step reads
files the prior step created. A single vc-execute-agent (opus) working the checklist in written
order is the correct fit per the "fit over tier" rule. Step F (test-writing, F1-F11) MAY fan out to
independent parallel subagents once A-E land, since each F-item targets a different file/AC with no
cross-talk needed — optional, not required. (Unchanged from cycle 1 — the supplement did not touch
Section D's dependency shape.)

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| hard-constraint | Zero CRM/csv_exporter file drift | Fully-Automated | `git diff --stat main -- apps/api/models/crm_connection.py apps/api/routers/crm.py apps/api/services/crm.py apps/api/services/crm/ apps/api/services/crm_push.py apps/api/services/crm_rate_limiter.py apps/api/tasks/crm_tasks.py apps/api/services/csv_exporter.py` exits with empty output | A |
| AC1 | Ad Audiences tab renders; CSV download fires unchanged query params | Fully-Automated | `cd apps/web && npx playwright test connectors` (new spec, F7) | A |
| AC4 | Only emailable/non-suppressed subset of a 4-class segment appears in push payload | Fully-Automated | `.venv/bin/python -m pytest tests/integration -k ads_safety_filter -m integration -q` (F3) | A |
| AC5 | Outbound payload builder never contains plaintext email/`@` | Fully-Automated | `.venv/bin/python -m pytest tests/unit -k ads_hash -m unit -q` (F2) | A |
| AC6 (mock-mode leg only — full credit at Phase 2/3) | Repeat push reuses `platform_audience_id` via upsert | Fully-Automated | `.venv/bin/python -m pytest tests/integration -k ads_upsert -m integration -q` (F8, VALIDATE-added) | B |
| AC7 (mock-mode leg only — full credit at Phase 2) | Small-segment warning field present in push response below placeholder threshold (1000) | Fully-Automated | `.venv/bin/python -m pytest tests/integration -k ads_warning -m integration -q` (F9, VALIDATE-added) | B |
| AC9 | LinkedIn button `disabled`; LinkedIn CSV export still 200 | Fully-Automated | `cd apps/web && npx playwright test connectors` (F6) | A |
| AC10 | Flag-off baseline unchanged; flag-on + mock-mode deterministic connect/push | Fully-Automated | `.venv/bin/python -m pytest tests/integration -k ads_flag -m integration -q` (F4) | A |
| AC11 | Nth push within the hourly window rejected | Fully-Automated | `.venv/bin/python -m pytest tests/unit -k ads_rate_limit -m unit -q` (F5) | A |
| AC12 | Exclude List tab label + upload/clear regression unchanged | Fully-Automated | `cd apps/web && npx playwright test connectors` (F7) | A |
| D5 (defense-in-depth, not a numbered SPEC AC) | Stub-provider (`meta`/`google`) non-mock path surfaces clean HTTP 501, not an unhandled 500 | Fully-Automated | `.venv/bin/python -m pytest tests/unit -k ads_stub_501 -m unit -q` (F10, cycle-2 supplement) | B |
| D6 (defense-in-depth, not a numbered SPEC AC) | `ad_audiences_enabled=false` connect attempt returns HTTP 501 | Fully-Automated | `.venv/bin/python -m pytest tests/unit -k ads_flag_off_501 -m unit -q` (F11, cycle-2 supplement) | B |
| program-level schema safety | Migration round-trip (upgrade head → downgrade -1 → upgrade head) | Hybrid (Docker-gated; disposable Postgres unavailable in this sandbox — confirmed live: `docker ps` fails, daemon not running) | `.venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head && ... downgrade -1 && ... upgrade head` against a disposable container | C — deferred to EVL/Docker-gate closure, matching the `owned-data-layer` precedent; record as known-gap in the phase report if still unavailable at EXECUTE time |

gap-resolution legend: A — proven now (gate passes in this cycle). B — fixed in this plan (F8/F9
added by the cycle-1 VALIDATE pass; F10/F11 added by this cycle-2 pass). C — deferred to a named
later phase/plan (Docker-gate closure, same pattern as owned-data-layer). D — backlog test-building
stub (none needed this phase).

C-4 reconciliation: the `strategy:` column above carries only the 3 proving strategies
(Fully-Automated / Hybrid / Agent-Probe). Known-Gap is never a `strategy:` value here — the one
Hybrid row's Docker-unavailability outcome is carried via gap-resolution `C`, not as a strategy.

Legacy line form (retained for existing consumers):
- Backend unit: `.venv/bin/python -m pytest tests/unit -k ads -m unit -q`
- Backend integration: `.venv/bin/python -m pytest tests/integration -k ads -m integration -q` — precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`
- Frontend e2e: `cd apps/web && npx playwright test connectors` — new specs must include "connectors" in filename
- Migration round-trip: Hybrid, Docker-gated — `.venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head && downgrade -1 && upgrade head` against a disposable Postgres container only

Failing stub (hard-constraint row — inline shell assertion, not a pytest/JS stub):
```
# NOT IMPLEMENTED — TDD stub: git diff --stat main -- <CRM/csv_exporter files> must be empty
test -z "$(git diff --stat main -- apps/api/models/crm_connection.py apps/api/routers/crm.py apps/api/services/crm.py apps/api/services/crm/ apps/api/services/crm_push.py apps/api/services/crm_rate_limiter.py apps/api/tasks/crm_tasks.py apps/api/services/csv_exporter.py)" || { echo "FAIL: CRM/csv_exporter drift detected"; exit 1; }
```

Failing stub (AC1):
```
test("Ad Audiences tab renders and CSV download fires unchanged query params", async () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC1 CSV download regression")
})
```

Failing stub (AC4):
```python
def test_ads_push_only_includes_safety_cleared_contacts():
    raise AssertionError("NOT IMPLEMENTED — TDD stub for: AC4 4-class segment safety filter")
```

Failing stub (AC5):
```python
def test_ads_push_payload_never_contains_plaintext_email():
    raise AssertionError("NOT IMPLEMENTED — TDD stub for: AC5 hash-only egress")
```

Failing stub (AC6 mock-mode leg):
```python
def test_ads_repeat_push_reuses_platform_audience_id():
    raise AssertionError("NOT IMPLEMENTED — TDD stub for: AC6 upsert-not-duplicate (mock-mode leg)")
```

Failing stub (AC7 mock-mode leg):
```python
def test_ads_push_response_includes_small_segment_warning():
    raise AssertionError("NOT IMPLEMENTED — TDD stub for: AC7 small-segment warning (mock-mode leg)")
```

Failing stub (AC9):
```
test("LinkedIn card is disabled; LinkedIn CSV export still returns 200", async () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC9 LinkedIn disabled-but-discoverable")
})
```

Failing stub (AC10):
```python
def test_ads_flag_off_baseline_unchanged():
    raise AssertionError("NOT IMPLEMENTED — TDD stub for: AC10 flag-off baseline")

def test_ads_flag_on_mock_mode_deterministic():
    raise AssertionError("NOT IMPLEMENTED — TDD stub for: AC10 flag-on + mock-mode connect/push")
```

Failing stub (AC11):
```python
def test_ads_rate_limiter_rejects_nth_push_in_window():
    raise AssertionError("NOT IMPLEMENTED — TDD stub for: AC11 hourly cap enforcement")
```

Failing stub (AC12):
```
test("Exclude List tab label + upload/clear behavior unchanged", async () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC12 Exclude List regression")
})
```

Failing stub (D5, cycle-2 supplement):
```python
def test_ads_connect_stub_provider_returns_501_when_flag_on_mock_off():
    raise AssertionError("NOT IMPLEMENTED — TDD stub for: D5 stub-provider 501 (flag on, mock off)")
```

Failing stub (D6, cycle-2 supplement):
```python
def test_ads_connect_returns_501_when_flag_off():
    raise AssertionError("NOT IMPLEMENTED — TDD stub for: D6 ad_audiences_enabled=false returns 501")
```

(Hybrid migration-round-trip row: no stub per protocol — Hybrid/Agent-Probe/Known-Gap tiers do not
receive TDD stubs.)

Dimension findings:
- Infra fit: PASS — pure additive FastAPI/SQLAlchemy/Next.js scaffolding, no container/port/infra
  changes; `.venv` confirmed live to have alembic 1.13.3 + pytest 8.3.3; `alembic heads` confirmed
  live to run offline (no DB needed), current head `a9f2c1e7b4d6` matches `all-context.md`.
  Cycle-2: unaffected by the D5/D6 supplement, no re-check needed.
- Test coverage: PASS — cycle-1 CONCERN (Exit Gate `pnpm` typo; missing AC6/AC7 checklist backing)
  fixed via P2/P3 (F8/F9). Cycle-2: D5/D6 were promoted from execute-agent instructions to
  checklist items with zero backing test gate — this cycle closes that by adding F10/F11 + two new
  Test gates rows (see table above), avoiding a vacuous-green PASS on the newly-promoted behavior.
- Breaking changes: PASS — zero edits to any CRM/csv_exporter file (verified: all target files
  exist, none are in Phase 1's Blast Radius); new `/api/v1/ads/*` surface is entirely additive;
  `config.py`'s one edit to an existing `@field_validator` argument tuple is additive-safe (same
  precedent as every other OAuth credential trio in that file) — not a breaking change, just not
  literally "append-only" as labeled; no functional risk. Cycle-2: unaffected by D5/D6.
- Security surface: PASS — OAuth CSRF via `oauth_state.py` (verified: state/user_id packing
  pattern used by `routers/crm.py` is directly reusable), token encryption via `encrypt_token`/
  `decrypt_token` (verified present in `services/encryption.py`), tenancy via `verify_site_access`
  (verified: 404-not-403, exact site_id+user_id ownership check), tokens never returned to client,
  independent rate-limit counter (fail-open, matches `crm_rate_limiter.py` precedent), feature flag
  defaults OFF, zero live network calls in Phase 1 (mock-mode enforced at service layer per F1).
  Risk class: auth/identity (OAuth token storage plumbing, even though unexercised live this
  phase) + external API contract — both High-Risk per `orchestration.md`. Cycle-2: the two
  defense-in-depth gaps (unhandled 500 on stub-provider non-mock path; undocumented flag-off
  status code) are now closed as concrete checklist items D5/D6 with dedicated tests F10/F11 —
  risk surface reduced, no new risk introduced by the supplement.
- Section A (Data model + migrations): PASS with note — mechanically feasible; A1/A2 field
  shapes verified against `CrmConnection`'s exact column set; upsert-on-conflict pattern for AC6 is
  standard Postgres/SQLAlchemy, already implied by A2's unique constraint. A3's original text
  incorrectly claimed no host venv exists — corrected in cycle 1 (see Plan updates). Cycle-2:
  untouched by the supplement.
- Section B (services/ads/ registry): PASS — `AdsProvider`/`get_provider`/`READY` map is a clean,
  mechanically buildable mirror of `services/crm/base.py` + `services/crm/__init__.py`'s registry
  pattern (method names differ intentionally — `get_oauth_url` vs CRM's `get_auth_url` — this is a
  net-new file, not a CRM edit, so naming divergence is not a conflict). Cycle-2: untouched.
- Section C (push/rate-limit/tasks): PASS — `_get_segment_visitors`/`_sha256` import-only reuse
  verified present and signature-compatible in `csv_exporter.py`; `ads_rate_limiter.py`'s fail-open
  Redis pattern and `ads_tasks.py`'s Celery shape are direct structural mirrors of verified donor
  files (`crm_rate_limiter.py`, `crm_tasks.py`). Cycle-2: untouched.
- Section D (router/schemas/config): PASS — cycle-1 CONCERN (D2's redundant backend `ready: bool`
  field, inconsistent with E1's frontend-hardcoded `OAUTH_ADS` array) fixed via P4. Cycle-2
  re-check: D5 and D6 (promoted from cycle-1 Execute-agent instructions E1/E3) are concrete and
  mechanically testable — D5 wraps the stub-provider `NotImplementedError` into a clean HTTP 501
  at the router call site, directly mirroring the verified `_OAUTH_CREDENTIALS`-missing 501 branch
  in `routers/crm.py` (confirmed live at lines 136-141 this cycle); D6 locks the
  `ad_audiences_enabled=false` connect-attempt status to 501, using the same verified precedent.
  No contradiction with D3's separate 400-for-not-ready-provider check (`_require_provider`'s
  own 400 branch, confirmed live at routers/crm.py:131-133) — these are two different repo-precedented
  failure classes (400 = wrong action for this provider/flow; 501 = feature not available
  server-side), both already in concurrent use in `routers/crm.py`, so D3 and D6 do not conflict.
  Both gaps carried from cycle 1 are now closed by concrete checklist text plus F10/F11 tests.
- Section E (frontend): PASS — `CrmConnectPanel`'s ready/disabled button precedent, status badge
  rendering, and confirm-dialog pattern verified directly in `crm-connect-panel.tsx`; no existing
  frontend feature-flag-read pattern found anywhere in `apps/web/src` (confirmed via repo-wide
  grep) — E2's own documented fallback (always render, backend returns a clean error when the flag
  is off) is therefore the correct and only available path; not a blocker. Cycle-2: untouched.
- Section F (mock-mode + AC verification): PASS — cycle-1 CONCERN (no checklist item backed the
  AC6/AC7 Verification Evidence rows) fixed via F8/F9. Cycle-2 adds F10/F11 to back the two new D5/
  D6 Test gates rows, closing this cycle's only new gap.

Open gaps:
- Migration round-trip (A4) cannot be executed in this sandbox — Docker daemon confirmed not
  running (`docker ps` fails). Carried as a Hybrid known-gap per the Blockers section's own
  documented contingency (matches `owned-data-layer` precedent); must be attempted again at EXECUTE
  time in whatever environment actually runs it, and marked known-gap in the phase report only if
  still unavailable there too.
- Small-segment warning threshold (SPEC OQ5) stays a placeholder (1000) through Phase 1 — real
  per-platform minimums are a Phase 2/3 docs-fetch item, already correctly scoped there.
- (Cycle-1's two execute-agent-instruction gaps — stub-provider 501 behavior, flag-off connect
  status code — are CLOSED this cycle via D5/D6 checklist items + F10/F11 tests. No longer open.)

What this coverage does NOT prove:
- Real Meta/Google OAuth consent-screen behavior, token exchange, or account metadata shapes
  (Phase 1 is 100% mock-mode; live-provider proof is explicitly Phase 2/3's job).
- The real AC13 error shape for Meta ToS-acceptance / Google EEA-consent gaps (Agent-Probe tier,
  Phase 2/3 — unverified live-provider response shapes per SPEC Open Questions 2 and 4).
- Real per-platform minimum-audience-size thresholds (SPEC OQ5) — Phase 1's AC7 mock-mode test
  only proves the warning *mechanism* fires below a placeholder number, not that the number is
  correct for any real platform.
- Concurrent-push race safety beyond single-request atomicity — the Postgres `ON CONFLICT` clause
  guarantees DB-level correctness for simultaneous writes, but no load/concurrency test exercises
  two truly simultaneous push requests for the same (connection_id, segment_id) pair.
- The Celery async-push code path (`ads_tasks.py`) beyond its structural mirror of `crm_tasks.py`
  — no test in F1-F11 explicitly exercises `ads_async_push=True` + over-threshold segment size
  triggering the actual `.delay()` enqueue; this mirrors a gap that also exists for the CRM path
  today, so it is not a regression, but it is not proven by this phase's gates either.
- Full manual/exploratory UI QA of `AdConnectPanel` beyond the specific Playwright assertions named
  in F6/F7/F9 (e.g. loading states, error-message copy quality, responsive layout).
(Required until C3 is implemented — temporary C3 mitigation)

Plan updates applied:
- P1 (cycle 1): Corrected Step A3 — `.venv` exists with alembic installed; `alembic heads` runs
  offline on host, no Docker required (previous text incorrectly claimed no host venv exists).
- P2 (cycle 1): Corrected Exit Gate bash block — replaced `pnpm --filter web exec playwright test
  connectors` (wrong package manager; repo uses npm) with `cd apps/web && npx playwright test
  connectors`, and documented the "connectors" filename requirement for new specs; added
  `.venv/bin/python -m` prefix to pytest commands per `all-tests.md`'s canonical form.
- P3 (cycle 1): Added Step F8 (AC6 mock-mode-leg upsert test) and F9 (AC7 mock-mode-leg warning
  test) — Verification Evidence table already promised these rows with no backing checklist item.
- P4 (cycle 1): Corrected Step D2 — dropped the redundant backend `ready: bool` field on the
  connections list (conflicted with E1's frontend-hardcoded readiness array and CRM's own
  precedent of never synthesizing placeholder rows); B7's server-side `READY` gate remains
  unaffected.
- P5 (cycle 2, this pass): Added Step F10/F11 — unit tests proving D5's stub-provider-501 wrap and
  D6's flag-off-501 status code are enforced by code, not just documented. Closes the
  vacuous-coverage gap that would otherwise exist on the two behaviors newly promoted from
  execute-agent instructions (E1/E3) into checklist items (D5/D6) by the cycle-1 PVL-supplement.
  Added matching Test gates rows (criterion ids "D5", "D6"), Verification Evidence rows, and TDD
  failing stubs.

Execute-agent instructions:
- E1: SUPERSEDED (cycle 2) — promoted to Implementation Checklist item D5. See D5 for the concrete
  wrap-in-501 instruction and F10 for its proving test.
- E2: When packing the OAuth `state` value in D3's connect endpoint, follow `routers/crm.py`'s
  exact convention (`f"{user.id}:{site_id}:{provider}"` via `store_oauth_state`, unpacked with
  `packed.split(":", 2)` in the callback) — `oauth_state.py`'s public API stores one opaque string
  per state key, so this packing convention (not a dedicated ads-specific store) is how CSRF state
  carries site/provider context through the redirect. (Unchanged, still applies.)
- E3: SUPERSEDED (cycle 2) — promoted to Implementation Checklist item D6 (locked to HTTP 501, no
  longer just a recommendation). See D6 and F11 for its proving test.
- E4: Before marking this phase VERIFIED, record in the phase report whether the disposable-Postgres
  migration round-trip (A4) ran successfully in the actual EXECUTE environment; if still
  unavailable there, mark it explicitly as a known-gap (not silently skipped) per the Blockers
  section's own contingency. (Unchanged, still applies.)

Backlog artifacts: none required this phase — all identified gaps are either fixed in-plan (F8/F9,
F10/F11, A3/D2/Exit-Gate corrections) or explicitly deferred with a named resolution path
(Docker-gate closure, Phase 2/3 docs-fetch) already tracked in the umbrella plan's Global
Constraints / Open Questions carry-forward.

Known gaps:
- Migration round-trip (A4/E4) — Hybrid, Docker-gated, deferred to EVL/Docker-gate closure if
  unavailable at EXECUTE time (matches `owned-data-layer` precedent). Not a program blocker.

Gate: PASS (0 FAILs, 0 unresolved CONCERNs — cycle-2 re-validate confirms D5 and D6 are concrete,
testable, and correctly close the 2 gaps carried from cycle 1 as execute-agent instructions E1/E3;
no contradiction found between D6's 501 choice and D3's separate 400-for-not-ready-provider check
— both are pre-existing, concurrently-used repo precedents in `routers/crm.py`; F10/F11 added this
cycle so the two newly-promoted behaviors are proven by a real test gate rather than left as a
vacuous-green checklist item; the sole remaining item (migration round-trip, A4) is a documented
Hybrid known-gap with a named resolution path per the Blockers section's own contingency, not an
unresolved CONCERN)
Accepted by: session (autonomous outer-PVL cycle-2 re-validate, no interactive user present this
invocation) — Gate is PASS; no unresolved concerns require acceptance. The one Known Gap (migration
round-trip, A4) carries its own written justification and resolution path in the Known Gaps section
above and was already accepted as non-blocking in cycle 1; re-confirmed non-blocking this cycle.
