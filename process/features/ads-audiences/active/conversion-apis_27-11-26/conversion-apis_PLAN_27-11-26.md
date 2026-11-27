---
name: plan:conversion-apis
description: "COMPLEX plan — server-side conversions to Meta CAPI + Google Ads click/enhanced conversions, LinkedIn CSV; delivery log, consent gating"
date: 27-11-26
feature: ads-audiences
---
# Conversion APIs back to ads — PLAN (COMPLEX, single plan, 3 sections)

TL;DR: Parse click ids server-side from event URLs, enqueue conversions from 4 Beam outcome triggers into a new delivery-log table, and a flag-gated sweep sends them via new `send_conversions()` on the existing Meta/Google providers. Default OFF, mock parity, no pixel change.

Complexity: COMPLEX
Status: PLANNED (validate CONDITIONAL; PVL supplement cycle 2 applied, re-validate pending)

## Overview
Gap #11 of the inbound-playbook analysis: no server-side conversion feedback to ad platforms exists today (0 hits for CAPI/offline/enhanced conversions; tracker.js captures UTMs only, no click ids). This plan adds it on top of the ad-audiences infrastructure.

## Acceptance Criteria
AC-1…AC-9 as defined in the SPEC; all must map to a gate in Verification Evidence.

PVL cycle 1 refinements (Gap 3):
- Dedup id: `lead` → `IdentifiedVisitor.id`; `goal` → `Conversion.id` (row from `conversion_tracker.record_conversion`, `apps/api/services/conversion_tracker.py:174`). Stable across retries/re-sweeps → UNIQUE(site_id, platform, dedup_id). proven by: G2; strategy: Fully-Automated.
- Conversion types v1: `lead` + generic `goal` (per D1). `demo_booked` is NOT a hardcoded type — it is a user-named goal; `AdConversionConfig.goal_event_map` JSONB maps `goal_id → platform event` (Meta: Lead/Schedule/Contact/CompleteRegistration; Google: Data Manager destination conversion action). Unmapped goal → `skipped_unmapped`. proven by: G2, G4; strategy: Fully-Automated / Hybrid.
- Phone: NEW `normalize_phone_e164(raw, default_country)` in `services/ad_conversions.py` (strip non-digits, prepend country code, reject <8 or >15 digits → omit ph) then SHA-256; `build_hashed_contacts` is NOT reused for phone. proven by: G3; strategy: Fully-Automated.
- Identity source (D2): only first-party identities (`identified`, first-party capture sources); never `candidate` or third-party graph matches. proven by: G2; strategy: Fully-Automated.

## Phase Completion Rules
Section done = code + its gates green; CODE DONE until G4/G5 pass with flag ON; VERIFIED only after operator live smoke (KG-1).

SPEC: `conversion-apis_SPEC_27-11-26.md` (same folder).

## Decision Summary
### Chosen Approach
Outbox table + APScheduler sweep (mirrors `ads_push`/CRM pattern) — durable retries, idempotent dedup, decoupled from request path.
### Why This Over Alternatives
| Alternative | Why Rejected |
|---|---|
| Inline send at trigger time | No retries, couples ingest/webhook latency to provider uptime |
| Celery task per conversion | Works, but no durable status for audit; outbox gives both — Celery may wrap the sweep later |
| tracker.js click-id capture | Costs pixel bytes; `events.url` already carries the query string |
### Risk Predictions (vc-predict, 5 personas)
- Security: hashed PII leaves Beam → consent gates must be fail-closed and unit-proven per gate.
- Privacy/legal: Meta EEA needs consent attestation; Google EEA blanket-excluded (precedent).
- Ops: flag-ON path silently no-op (marketing-claims icp_fit lesson) → flag-ON integration gate mandatory.
- Product: Google requires an operator-created conversion action; absent mapping → `skipped_unmapped`, not error.
- Data: duplicate conversions inflate ad metrics → unique dedup index + platform dedup ids.
### Key Constraints Accepted
Live shapes unproven (`needs-live-provider`); LinkedIn CSV-only; no revenue values v1.

## Touchpoints
- NEW `apps/api/models/ad_conversion.py` — `AdConversionDelivery` (id, site_id FK, visitor_id, platform, conversion_type, dedup_id, status[pending|sent|failed|skipped_*], attempts, next_attempt_at, last_error, sent_at, created_at, updated_at; UNIQUE(site_id, platform, dedup_id)); `AdConversionConfig` (id, site_id FK, platform, UNIQUE(site_id, platform); `goal_event_map` JSONB `{goal_id: platform_event}` (supersedes the dropped `enabled_types`; `lead` enabled via key `"lead"`); Meta: `meta_dataset_id`, `meta_test_event_code` nullable; Google: `google_operating_account_id` + `google_product_destination_id` (same destination shape `services/ads/google.py` already uses for audience ingest), `validate_only` bool default true; `eea_consent_attested` bool; watermarks `goal_watermark_at` + `lead_watermark_at` timestamptz nullable; created_at, updated_at). Both tables are added to `apps/api/models/__init__.py`.
- EDIT `apps/api/models/visitor.py` — add nullable `click_ids` JSONB (first-ad-click `{fbclid, fbc_ts, gclid, wbraid, gbraid, li_fat_id}`; only keys present are written; NULL — never `{}` — when no click id ever seen). `fbc_ts` = epoch-ms `created_at` of the click-id event (N1); there is no separate `first_seen_ms`.
- NEW migration — chain off `alembic -c apps/api/alembic.ini heads` at EXECUTE time (never hardcode down_revision); additive only; live up/down/up on disposable PG.
- NEW `apps/api/services/click_ids.py` — pure `extract_click_ids(url) -> dict`.
- EDIT `apps/api/services/visitor_aggregator.py` — compute `click_ids` from the FIRST non-abuse event (ORDER BY created_at) whose URL carries a click-id param (`fbclid|gclid|wbraid|gbraid|li_fat_id`) — NOT the first pageview, so organic-first-then-ad-click visitors are captured (N1); parse via `extract_click_ids`; empty result → NULL. Written via `COALESCE(visitors.click_ids, EXCLUDED.click_ids)` (write-once) in BOTH the full and the incremental upsert, alongside the `first_touch_referrer` expression (~:319). `routers/events.py` (pixel ingest) is NOT touched — no enqueue in ingest path.
- NEW `apps/api/services/ad_conversions.py` — `enqueue_conversion(db, site_id, visitor_id, type)` (gates AC-5, dedup AC-3), `run_conversion_sweep_once()`.
- EDIT `apps/api/services/ads/base.py` — `ConversionEvent` dataclass + NON-abstract `send_conversions()` whose default body raises `NotImplementedError` (sibling ads plans add methods the same way; existing providers keep instantiating).
- EDIT `services/ads/meta.py` — POST `/{dataset_id}/events` (`event_name` Lead/Schedule/Contact, `event_id`=dedup, `action_source=website` + `event_source_url` (URL of the visitor's latest non-abuse `events` row at/before conversion time) + `user_data{em,ph,fbc,client_user_agent}` where `client_user_agent` = `events.user_agent` (`models/event.py:38`) of that same latest event (Visitor has no UA column; events purge at 90d). UA missing → row `skipped_no_user_agent` for Meta only (Google unaffected), reason in `last_error`; never sent without UA (N4) (no raw IP v1, D4); `event_time` from conversion ts), mock branch. Before batching: rows whose event_time is >6 days old → `skipped_stale` (Meta rejects the WHOLE batch if one event is >7d).
- EDIT `services/ads/google.py` — Data Manager API `POST https://datamanager.googleapis.com/v1/events:ingest` via existing `_dm_post` helper + existing `datamanager` OAuth scope (NOT `uploadClickConversions` — closed to new integrations since 15-06-2026). Per event: `transactionId`=dedup, `eventTimestamp` (RFC3339), `userData` (hashed email/phone identifiers), `consent`, `adIdentifiers` with exactly one click id chosen by priority gclid > wbraid > gbraid; ≤2000 events per request (chunk); `validateOnly` true when config test-mode flag set; destination = `{operatingAccount: config.google_operating_account_id, productDestinationId: config.google_product_destination_id}` (same shape as existing audience ingest in google.py); `validateOnly` = `config.validate_only`; userData identifiers `encoding: HEX`. Mock branch; EEA filter reused.
- EDIT `services/ads/linkedin.py` — CSV export helper only.
- No trigger hooks in request paths (Gap 4). The sweep discovers work itself: scans new `Conversion` rows (goal) and newly identified visitors (lead) past a per-site watermark, enqueues deliveries, then sends. reply/crm_stage deferred (D1) → backlog NOTE `process/features/ads-audiences/backlog/conversion-apis-reply-crm-stage_NOTE_27-11-26.md` (write at EXECUTE).
- NEW `apps/api/routers/ad_conversions.py` — GET/PUT config, GET deliveries (paged), GET LinkedIn CSV; tenant 404; mount in `main.py`.
- EDIT `apps/api/config.py` — `ad_conversions_enabled=False`, `ad_conversions_sweep_interval_s=300`, `ad_conversions_max_attempts=5`; scheduler registration gated at registration AND runtime.
- Web (minimal): conversion mapping panel in ad-connect settings; deliveries table. Optional — may defer.
- EDIT `apps/api/jobs/scheduler.py` — register the conversion sweep job, gated on `ad_conversions_enabled` at registration AND re-checked at runtime (N6).
- EDIT `apps/api/models/__init__.py` — import/register `AdConversionDelivery` + `AdConversionConfig` (N6).
- EDIT `apps/api/routers/visitors.py` (~:449 per-visitor erasure table tuple) — add `ad_conversion_deliveries` (by visitor_id) (N3).
- EDIT `apps/api/routers/sites.py` (site delete explicit table list) — add `ad_conversion_deliveries` + `ad_conversion_configs` (by site_id) (N3).
- NEW tests: `tests/unit/test_click_ids.py`, `tests/unit/test_ad_conversions_gates.py`, `tests/unit/test_ads_conversion_payloads.py`, `tests/integration/test_ad_conversions.py`.

## Public Contracts (frozen for sibling ad-tests→SEO/AEO plan)
- Table `ad_conversion_deliveries` columns above; table `ad_conversion_configs` columns above (`goal_event_map`, Google `operatingAccount`/`productDestinationId`, `validate_only`, `meta_test_event_code`, watermarks; no `enabled_types`); `visitors.click_ids` JSONB keys above (NULL when none).
- Delivery status vocabulary adds `skipped_no_user_agent` (Meta) alongside `skipped_stale`, `skipped_unmapped`, `skipped_<gate>`.
- API: `GET/PUT /api/v1/ad-conversions/{site_id}/config/{platform}`, `GET /api/v1/ad-conversions/{site_id}/deliveries`, `GET /api/v1/ad-conversions/{site_id}/linkedin.csv`.
- Provider method `send_conversions(connection, config, events: list[ConversionEvent]) -> list[ConversionResult]`.

## Blast Radius
~16 files, apps/api (+ optional apps/web). High-risk: PII to third party, external provider, schema migration, public API. No auth change; reuses ad_connections OAuth scopes (re-consent risk if scopes insufficient — known-gap).

## Implementation Checklist
A. Data + capture
1. Models + migration (chain off live heads); register models.
2. `click_ids.py` + write-once wiring; Meta `fbc` = `fb.1.{click_ids.fbc_ts}.{fbclid}` (fbc_ts = epoch-ms created_at of the first click-id event; one source of truth).
B. Engine
3. `ConversionEvent`/base method; `ad_conversions.enqueue_conversion` with all AC-5 gates + dedup ON CONFLICT DO NOTHING.
4. Meta + Google `send_conversions` + mock branches; LinkedIn CSV.
5. Sweep discovery (watermarks on `AdConversionConfig`): goal = `Conversion` rows with `created_at > goal_watermark_at`; lead = `IdentifiedVisitor` rows with `COALESCE(confirmed_at, resolved_at) > lead_watermark_at` (confirmed_at covers promoted candidates) whose `Visitor.identity_status = 'identified'` (field lives on `Visitor`, joined), `resolution_provider` IN the D2 first-party allow-list constant `FIRST_PARTY_PROVIDERS` in `services/ad_conversions.py` (pixel/form capture values — enumerate from the existing provider vocabulary at EXECUTE, unit-tested), and `is_emailable_identity(...)` true → `enqueue_conversion` (ON CONFLICT DO NOTHING); advance watermark to max scanned ts in the same transaction.
5a. Send-time re-check (immediately before each batch, per row): consent, `do_not_resolve`, abuse (`is_abuse_flagged`), bot (`is_bot_suspect`), agent origin (`source_agent_visit_id` not null), internal-traffic flag, suppression list, EEA + unknown-country (both platforms, D3), erased/deleted visitor or site, D2 first-party source. Failing row → `skipped_<gate>`, never sent.
5b. Meta stale guard: event_time > 6 days → `skipped_stale` before batching. Google: chunk ≤2000.
5c. Sweep: select pending due rows FOR UPDATE SKIP LOCKED, batch per (site, platform), backoff `min(2^attempts*60, 3600)s`, permanent vs transient classification reusing `_is_transient_http_error`; `skipped_unmapped` when no dataset/action.
6. Aggregator `click_ids` write-once (full + incremental upsert, COALESCE). No ingest-path enqueue.
C. Surface
7. Router + config flags + scheduler gating.
8. (Optional) web panel.
9. Tests per Verification Evidence.

## Verification Evidence
| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
Gate preconditions: Python 3.11 `.venv` must exist (`python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt`); Postgres :5433 + Redis :6379 up (check `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`). Test DSN: `postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test` (tests/conftest.py:26). Order: EXECUTE this plan FIRST of the three ads plans.

| G1 `.venv/bin/pytest tests/unit/test_click_ids.py -q` | Fully-Automated | AC-1 |
| G2 `.venv/bin/pytest tests/unit/test_ad_conversions_gates.py -q` (each gate skip, dedup stable) | Fully-Automated | AC-3, AC-5 |
| G3 `.venv/bin/pytest tests/unit/test_ads_conversion_payloads.py -q` (hash normalization, Meta/Google payload shape vs documented shape, mock deterministic, no plaintext; Meta UA from latest event + `event_source_url`; missing UA → `skipped_no_user_agent` with zero Meta calls) | Fully-Automated | AC-4, AC-7, AC-9 |
| G4 `DATABASE_URL=postgresql+asyncpg://...@localhost:5433/... .venv/bin/pytest tests/integration/test_ad_conversions.py -q` — flag-ON goal discovery (`Conversion.created_at` > watermark) AND lead discovery (identified + first-party provider + emailable; non-first-party and candidate rows NOT enqueued) → enqueue→sweep→sent (mock), watermark advances, retry→failed, idempotent re-enqueue, foreign site 404 | Hybrid (needs PG+Redis) | AC-2,3,6,7,8 + flag-ON non-vacuous |
| G5 Migration up/down/up on disposable `postgres:16-alpine` with pinned DSN | Hybrid | schema safety |
| G6 Regression: `.venv/bin/pytest tests/unit -q` + `tests/integration -q` (pinned DSN) | Fully-Automated/Hybrid | no regression |
| G7 Pixel size unchanged (`tests/unit/test_pixel.py`) | Fully-Automated | AC-1 constraint |
| G8 `.venv/bin/pytest tests/unit/test_ad_conversions_gates.py -q -k stale` — >6d row → skipped_stale, batch of remaining sends | Fully-Automated | AC-7 |
| G9 `.venv/bin/pytest tests/integration/test_ad_conversions.py -q -k recheck` — gate flips (suppress/do_not_resolve/erase/EEA/abuse/bot/agent-origin/internal) between enqueue and send → skipped, zero provider calls | Hybrid (PG) | AC-5 |
| G10 `.venv/bin/pytest tests/integration/test_ad_conversions.py -q -k click_ids` — aggregator full + incremental: first value persists, later events don't overwrite, abuse-flagged events ignored, organic-first-then-ad-click visitor gets click_ids from the later click event (fbc_ts = that event's created_at), no-click visitor stays NULL |
| G13 `.venv/bin/pytest tests/integration/test_ad_conversions.py -q -k erasure` — per-visitor erasure removes that visitor's `ad_conversion_deliveries`; site delete removes the site's deliveries + configs | Hybrid (PG) | privacy (N3) | Hybrid (PG) | AC-1 |
| G11 `.venv/bin/pytest tests/integration/test_ad_conversions.py -q -k ingest_survives` — provider/sweep exception does not affect `POST /ingest` or aggregation | Hybrid (PG) | AC-6 |
| G12 `.venv/bin/pytest tests/unit/test_ads_conversion_payloads.py -q -k data_manager` — events:ingest shape (transactionId, eventTimestamp, userData, consent, adIdentifiers priority, ≤2000 chunk, validateOnly from config, destination `operatingAccount`+`productDestinationId`, asserts `encoding: HEX`) | Fully-Automated | AC-4, AC-9 |
| E7 `harness/*.json` 5-file risk pack present (data-flow, consent matrix, PII grep, flag-OFF, rollback) | Agent-Probe | high-risk handoff |
| KG Live Meta test-event / Google sandbox upload | needs-live-provider (operator) | live shapes |

## Risk Evidence Pack (vc-risk-evidence-pack, manual-first)
1. Data-flow diagram: fields leaving Beam per platform (hashed em/ph, fbc, gclid, ts, dedup) — in phase report.
2. Consent gate matrix with unit-test ids per row.
3. Grep proof: no plaintext email/phone in structlog calls of new modules.
4. Flag-OFF proof: zero rows enqueued, scheduler job absent.
5. Rollback: flag OFF + migration downgrade verified (G5).

## Test Infra Improvement Notes
(none identified yet)

## Operator Prerequisites
Meta: dataset/pixel id + Events Manager test_event_code; Google: Data Manager destination (conversion action linked as a Data Manager destination, customer data terms accepted) + `datamanager` scope consent on the ad connection — no UPLOAD_CLICKS / developer token needed; LinkedIn: none v1.

## Open User Decisions
PROVISIONAL defaults — pending user confirmation:
- D1: v1 = `lead` + `goal` only; reply/crm_stage deferred → backlog NOTE `conversion-apis-reply-crm-stage_NOTE_27-11-26.md`. (pending user confirmation)
- D2: send only first-party identities; never candidate/third-party graph matches. (pending user confirmation)
- D3: exclude EEA + unknown-country for Meta as well as Google. (pending user confirmation)
- D4: Meta `website` events with client_user_agent; no raw IP in v1. (pending user confirmation)

## Resume and Execution Handoff
1. Selected plan: this file. 2. Last completed: PLAN (fast-mode) + outer PVL validate pass 27-11-26. 3. Validate-contract: written below, Gate BLOCKED (1 FAIL, missing-detail class). 4. Context: `process/context/all-context.md`, `process/context/tests/all-tests.md`, ad-audiences umbrella + phase-2/3 plans. 5. PVL supplement cycle 1 APPLIED 27-11-26 (Gaps 1-5). Next: re-validate from V1; earlier note: PVL supplement cycle 1 (vc-plan-agent, SUPPLEMENT REQUEST in the validate report), then re-validate from V1, then ENTER EXECUTE MODE.

## Validate Contract

Status: PASS
Date: 27-11-26
date: 2026-11-27
generated-by: outer-pvl
supersedes: 2026-11-27 (outer-pvl, pass 2, Gate CONDITIONAL N1–N6) — outer PVL re-run after supplement cycle 2 has current, code-checked evidence

Parallel strategy: sequential (validate fan-out ran inline in one validate agent; no Agent tool in-session). EXECUTE recommendation: sequential — one opus vc-execute-agent running sections A→B→C, then an opus vc-tester EVL run. Alternatives: parallel subagents / workflow / agent team rejected — sections chain (models → engine → surface), so parallel legs would collide on `ad_conversions.py` and `models/`.
Rationale: 3/7 signals (S2 schema/API, S6 high-risk, S7 ~18 files); dominant signal S6 (PII egress to third parties).

Net gate derivation: 0 FAIL / 0 CONCERN / 9 PASS → PASS (after 2 PVL cycles). The FIRST_PARTY_PROVIDERS residual is resolved by execute instruction E8 (the vocabulary in code is unambiguous). KG-1, KG-2, env preconditions and provisional D1–D4 are named residuals, not blockers.

Cycle-2 gap closure (checked against code 27-11-26):
- N1 click-id semantics: CLOSED. Touchpoints take the FIRST non-abuse event carrying a click-id param (not the first pageview). The `first_touch_referrer` ARRAY_AGG sits at `services/visitor_aggregator.py:319`; the incremental path is the no-overwrite contract at :464/:740. `fbc_ts` = that event's `created_at` (epoch-ms) in both Touchpoints and checklist A2; `first_seen_ms` removed; NULL default. G10 covers organic-first-then-ad-click.
- N2 watermark + lead predicate: CLOSED. `goal_watermark_at` / `lead_watermark_at` on `AdConversionConfig`. Goal scan uses `Conversion.created_at` (`models/outcome.py:129`). Lead scan uses `COALESCE(confirmed_at, resolved_at)` (`models/visitor.py:265`, `:257`) joined to `Visitor.identity_status` (`models/visitor.py:72`). The allow-list values are fixed by E8.
- N3 erasure/site-delete: CLOSED. Per-visitor erasure tuple at `routers/visitors.py:450-459`; site-delete explicit list at `routers/sites.py:320-345`. Both are edit targets; G13 covers them.
- N4 Meta UA: CLOSED. `events.user_agent` (`models/event.py:38`) taken from the latest non-abuse event, which also supplies `event_source_url`. A missing UA gives `skipped_no_user_agent` for Meta only (G3).
- N5 config contract: CLOSED. `enabled_types` now appears only as "dropped". `goal_event_map`, `meta_test_event_code`, `google_operating_account_id` / `google_product_destination_id`, `validate_only`, watermarks and `encoding: HEX` (G12) agree across Touchpoints and Public Contracts.
- N6 touchpoints: CLOSED. `jobs/scheduler.py` and `models/__init__.py` exist and are listed; the scheduler is gated at registration and at runtime.

Cycle-1 regression scan: no regression. `_dm_post` still at `services/ads/google.py:172`; `datamanager` scope in `_SCOPES` (`google.py:70-71`); `uploadClickConversions` named only as rejected. Meta `_post` with `@_http_retry` at `meta.py:153/160`; `_is_transient_http_error` at `meta.py:79` / `google.py:85`. `exclude_eea_rows` at `ads_push.py:63`; `is_email_suppressed_any` at `suppression.py:28`. No enqueue in the ingest path (`routers/events.py` untouched). The send-time recheck (5a) is unchanged and now also re-checks the flag.

Dimension findings:
- Infra fit: PASS — outbox + APScheduler fits the `jobs/scheduler.py` registration-gate pattern. Env 27-11-26 (`.venv` missing, :5433/:6379 down) is an EVL precondition, not a blocker.
- Test coverage: PASS — G1–G13 cover every developed behavior with a Fully-Automated or Hybrid gate (lead discovery G4, erasure G13, organic-then-click G10, recheck G9). The only Known-Gap is live provider acceptance (KG-1, named residual D).
- Breaking changes: PASS — additive only (new tables, nullable `visitors.click_ids`, non-abstract `send_conversions`, new router). Public Contracts are internally consistent, so they are safe to freeze for siblings.
- Security surface: PASS — gates fail closed at enqueue and again at send time; erasure and site delete now remove delivery and config rows; D2 is tied to concrete provider values (E8); no PII in logs or `last_error` (E4); risk pack required (E7).
- A — Data + capture: PASS — the click-id event is selected explicitly; write-once COALESCE on both upserts; pixel untouched (G7).
- B — Engine (Google Data Manager): PASS — feasible on the existing helper, scope, destination shape and EEA filter. E6 (retry stacking) still applies.
- B — Engine (Meta): PASS — UA/URL source named; stale and missing-UA skips are specified.
- B — Sweep discovery: PASS — watermark columns and scan timestamps are named; the allow-list is enumerated in E8; the internal-traffic gate semantics are fixed in E9.
- C — Surface/contracts: PASS — router, flags, scheduler gating and tenant 404 are specified. Cosmetic only: the G10/G13 rows of the Verification Evidence table have shifted columns; E10 gives the correct mapping.
- Plan artifact validator: PASS — `validate-plan-artifact.mjs` 27-11-26: 0 failures, 0 warnings.
- Risk evidence pack: PASS — high-risk (PII to third parties, external providers, schema migration, new public API). Canonical pack names are fixed in E7; the pack is required before DONE.

Test gates (C3 5-column table — ADDITIVE; legacy line form below):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | click ids parsed from the event URL (fbclid/gclid/wbraid/gbraid/li_fat_id) | Fully-Automated | `.venv/bin/pytest tests/unit/test_click_ids.py -q` (G1) | B |

Failing stub:
test("should parse fbclid/gclid/wbraid/gbraid/li_fat_id from event url", () => { throw new Error("NOT IMPLEMENTED — TDD stub: click id extraction") })

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-3, AC-5, D2 | each fail-closed gate skips (flag, do_not_resolve, suppressed/do_not_email, abuse/bot/agent/internal, non-first-party provider, EEA/unknown country); dedup id stable; FIRST_PARTY_PROVIDERS exact membership; >6d Meta row skipped_stale | Fully-Automated | `.venv/bin/pytest tests/unit/test_ad_conversions_gates.py -q` (G2; G8 `-k stale`) | B |

Failing stub:
test("should skip conversion for each fail-closed gate, keep dedup id stable, and pin FIRST_PARTY_PROVIDERS", () => { throw new Error("NOT IMPLEMENTED — TDD stub: consent gate matrix + dedup + allow-list") })

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-4, AC-7, AC-9 | Meta website payload (em/ph E.164 hash, fbc, UA + event_source_url from latest event, missing UA → skipped_no_user_agent with zero Meta calls) + Data Manager events:ingest payload (transactionId, eventTimestamp, userData encoding HEX, consent, adIdentifiers gclid>wbraid>gbraid, destination operatingAccount+productDestinationId, ≤2000 chunk, validateOnly from config); mock deterministic; no plaintext | Fully-Automated | `.venv/bin/pytest tests/unit/test_ads_conversion_payloads.py -q` (G3; G12 `-k data_manager`) | B |

Failing stub:
test("should build documented Meta CAPI and Data Manager events payloads with hashed identifiers only", () => { throw new Error("NOT IMPLEMENTED — TDD stub: provider payload shape") })

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-2, 3, 6, 7, 8 | flag-ON goal discovery + lead discovery (identified + allow-listed provider + emailable; candidate / non-allow-listed NOT enqueued) → enqueue → sweep → sent (mock); watermark advances; retry → failed; idempotent re-enqueue; foreign site 404 | Hybrid | `DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test .venv/bin/pytest tests/integration/test_ad_conversions.py -q` (G4; precondition: PG :5433 + Redis :6379 up, flag ON) | B |
| AC-5 | send-time recheck flips (suppress/do_not_resolve/erase/EEA/abuse/bot/agent-origin/internal/flag OFF) between enqueue and send → skipped, zero provider calls | Hybrid | same file `-k recheck` (G9) | B |
| AC-6 | provider/sweep exception does not affect `POST /ingest` or aggregation | Hybrid | same file `-k ingest_survives` (G11) | B |
| AC-1 | aggregator click_ids write-once on full + incremental paths; abuse-flagged ignored; organic-first-then-ad-click gets click ids from the later event; no-click stays NULL | Hybrid | same file `-k click_ids` (G10) | B |
| privacy | per-visitor erasure removes `ad_conversion_deliveries`; site delete removes deliveries + configs | Hybrid | same file `-k erasure` (G13) | B |
| schema | migration up/down/up | Hybrid | alembic up/down/up on a disposable `postgres:16-alpine` with the DSN pinned (never the repo dotenv DSN) (G5) | B |
| regression | no unit/integration regression; pixel size unchanged | Fully-Automated | `.venv/bin/pytest tests/unit -q`; `.venv/bin/pytest tests/unit/test_pixel.py -q` (G6, G7); integration lane with pinned DSN | A |
| high-risk | 5-file risk pack present and reviewed | Agent-Probe | `harness/{risk-gate,context-snippets,verification,review-decision,adversarial-validation}.json` in this task folder (E7) | B |
| live shapes | real Meta test event / Data Manager validateOnly upload accepted | Agent-Probe | operator-run with `meta_test_event_code` / `validate_only=true` (KG-1, double opt-in) | D |

C-4 reconciliation: the strategy column carries only proving strategies. Known-Gap is never a strategy value; it appears only as a named residual (gap-resolution D).

Legacy line form:
- click ids: [Fully-automated: .venv/bin/pytest tests/unit/test_click_ids.py -q]
- gates/dedup/stale/allow-list: [Fully-automated: .venv/bin/pytest tests/unit/test_ad_conversions_gates.py -q]
- payloads: [Fully-automated: .venv/bin/pytest tests/unit/test_ads_conversion_payloads.py -q]
- engine e2e + recheck + ingest_survives + click_ids + erasure: [hybrid: .venv/bin/pytest tests/integration/test_ad_conversions.py -q + PG :5433/Redis :6379, pinned DSN, flag ON]
- migration: [hybrid: alembic up/down/up + disposable postgres:16-alpine, pinned DSN]
- risk pack: [agent-probe: harness/*.json 5 files reviewed]
- live provider: [known-gap: documented KG-1, operator double opt-in]

What This Coverage Does NOT Prove:
- G3/G12 prove payload shape against the docs as read on 27-11-26. They do not prove provider acceptance, match rate or attribution.
- A G4 mock "sent" proves the outbox state machine only. A live Data Manager success is only a `requestId` ("accepted for processing").
- G2/G9 do not prove the EEA policy or owner attestation is legally sufficient.
- The G5 empty-DB round-trip does not prove behaviour at prod volume or under locks.
- G10 does not prove click-window expiry. A write-once first gclid older than Google's click window will be rejected live (KG-1).
- FOR UPDATE SKIP LOCKED is proven single-host only; multi-worker concurrency is unproven.
- The E8 allow-list proves membership only. It does not prove that every future provider value is classified correctly; a new provider is excluded by default.
- No gate covers the optional web panel (KG-2, Clerk e2e harness).

Open gaps:
- none in scope. Named residuals: KG-1 live provider shapes/permissions (needs-live-provider, operator, double opt-in); KG-2 Clerk e2e for the optional web panel.
- reply + crm_stage triggers are deferred (D1). Write the backlog NOTE at EXECUTE.
- Cross-plan: company-exclusion-list_27-11-26 does not reference `ad_conversions` (grep 27-11-26). Whichever plan lands second must add the company-exclusion check to the 5a send-time recheck. closed-won-lookalikes still claims conversion-apis edits `tasks/crm` + `routers/outcomes.py`; that is stale, and this plan edits neither.
- Env preconditions (not blockers): `.venv` missing; :5433/:6379 down at validate time. D1–D4 remain provisional (not blockers).

Execute-agent instructions:
- E1 Before writing the migration, run `alembic -c apps/api/alembic.ini heads` with DATABASE_URL pinned to localhost or a disposable DB. Never use the repo dotenv DSN (Supabase PROD). Chain off the live head.
- E2 G4/G9/G10/G11/G13 must run flag-ON; flag-OFF-only evidence is vacuous.
- E3 Never call live providers; mock only.
- E4 No PII (email, phone, IP, UA, click ids) in logs or `last_error`. Use reason codes only.
- E5 `send_conversions` is non-abstract with a default NotImplementedError. Edits to `base.py` are additive only.
- E6 `_dm_post` and Meta `_post` carry `@_http_retry` (3 tries). Either count one outbox attempt as up to 3 HTTP tries or bypass the decorator for conversions. Do not stack backoffs silently.
- E7 Before reporting DONE, write `harness/risk-gate.json`, `harness/context-snippets.json`, `harness/verification.json`, `harness/review-decision.json` and `harness/adversarial-validation.json` in this task folder, using the vc-risk-evidence-pack schemas. Cover the plan's 5 items (data flow, consent matrix with test ids, PII grep, flag-OFF proof, rollback). Set `riskClass` to PII egress / schema migration / public API and `mustStopBeforeFinalize: true`.
- E8 Define `FIRST_PARTY_PROVIDERS = frozenset({"form_capture", "pdl_person_enrich"})` in `services/ad_conversions.py`. Source vocabulary: `services/identity_classification.py:15-31`. `form_capture` is written at `identity_resolver.py:420`. `pdl_person_enrich` is only ever an enrich of an already-captured email (`identity_resolver.py:393-397`, `identity_providers/pdl.py:55-58`), so the uploaded email is first-party. EXCLUDE all of these: `rb2b`, `leadpipe`, `capturify`, `beam_identity_network` (GRAPH_CANDIDATE_PROVIDERS); `hunter`, `apollo` (company-level); `fingerprint_match`, `svid_reconcile`, `fingerprint`, `email_click` (they inherit an origin tier that may be third-party); `manual`, `contact_import` (not visitor-supplied on-site; no ad-click journey). The lead predicate is the AND of `provider in FIRST_PARTY_PROVIDERS`, `Visitor.identity_status == "identified"` and `is_emailable_identity(provider, source_agent_visit_id, is_abuse_flagged)`. The G2 unit test pins exact set equality plus a non-member sample. Any widening is a D2 user decision, not an EXECUTE choice.
- E9 Internal-traffic gate (5a/AC-5): skip when `Visitor.internal_override == "internal"` OR (`Visitor.is_internal_suspect` AND `internal_override != "not_internal"`). See `models/visitor.py:160-172`.
- E10 Verification Evidence G10/G13 rows have shifted columns. Correct mapping: G10 = Hybrid (PG), AC-1; G13 = Hybrid (PG), privacy (N3). Fix the table rows in the phase report and treat this contract's gate table as canonical.
- E11 The lead dedup id is `IdentifiedVisitor.id` and the goal dedup id is `Conversion.id`. This supersedes SPEC AC-3's sha256 recipe and Google `orderId`; Google uses `transactionId`.

Gate: PASS (0 FAIL, 0 CONCERN; 2 PVL supplement cycles applied; residuals KG-1/KG-2/env/D1–D4 named, not blocking)
Accepted by: session (outer-pvl re-validate 27-11-26) — no concerns to accept; named residuals KG-1 live provider, KG-2 Clerk e2e, env preconditions (.venv, PG/Redis), provisional D1–D4 recorded as non-blocking per orchestrator instruction

## Autonomous Goal Block

```
SESSION GOAL: conversion-apis v1 — server-side conversions to Meta CAPI + Google Data Manager events:ingest, LinkedIn CSV, flag OFF by default
Charter + umbrella plan: N/A — single plan (process/features/ads-audiences/active/conversion-apis_27-11-26/conversion-apis_PLAN_27-11-26.md)
Autonomy: per feedback_autonomous_phase_execution.md — reversible decisions auto-proceed; hard stops surface
Validate: PASS gate, outer-pvl 2026-11-27, after 2 PVL supplement cycles. Ready for ENTER EXECUTE MODE (opus vc-execute-agent, sequential A->B->C, then opus vc-tester EVL).
Hard stops:
- Never run alembic or DB scripts against the repo dotenv DATABASE_URL (Supabase PROD); pin localhost/disposable
- Never call live Meta/Google/LinkedIn APIs; mock only (live = operator, double opt-in)
- No plaintext PII (email/phone/IP/UA/click ids) in logs or delivery rows
- ad_conversions_enabled stays OFF; flipping it is an operator action
- FIRST_PARTY_PROVIDERS = {form_capture, pdl_person_enrich} exactly (E8); widening = D2 user decision
- EXECUTE order: conversion-apis -> closed-won-lookalikes -> ad-insights-seo-aeo; base.py edits additive only
- harness/ 5-file risk pack (risk-gate, context-snippets, verification, review-decision, adversarial-validation) before DONE
Next phase: EXECUTE: process/features/ads-audiences/active/conversion-apis_27-11-26/conversion-apis_PLAN_27-11-26.md
Validate contract: inline in plan
Execute start: .venv/bin/pytest tests/unit/test_click_ids.py tests/unit/test_ad_conversions_gates.py tests/unit/test_ads_conversion_payloads.py -q | DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test .venv/bin/pytest tests/integration/test_ad_conversions.py -q (flag ON) | probe: operator Meta test_event_code + Data Manager validateOnly (KG-1) | high-risk pack: yes
```
