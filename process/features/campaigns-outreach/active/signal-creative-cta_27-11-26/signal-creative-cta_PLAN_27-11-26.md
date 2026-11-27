---
name: plan:signal-creative-cta
description: "Signal-aware creative variant selection + structured per-site CTA types with per-type click attribution (campaigns-outreach gaps #8/#9)"
date: 27-11-26
feature: campaigns-outreach
---
# PLAN (COMPLEX) — signal-creative-cta

Complexity: COMPLEX
Status: CODE DONE (merged on feat/inbound-playbook-gaps 27-11-26; decisions CONFIRMED)

## Overview
Closes inbound-playbook gaps #8 (one creative per signal) and #9 (only "Book a demo" CTA); verifies #10 (no auto-send gap found).

TL;DR: one pure selector module, a planner prompt/schema extension, a `sites.cta_config` JSONB + `click_events`-style `cta_type` column (one migration), click-redirect `ct=` param, a counts endpoint. Two default-OFF flags. #10 verified: no gap, nothing planned.

Spec: `signal-creative-cta_SPEC_27-11-26.md` (same folder).

## Decision Summary

### Chosen Approach
Deterministic server-side angle + CTA selection fed to the existing single Gemini call — the model writes copy for a fixed angle/CTA rather than inventing them.

### Why This Over Alternatives
| Alternative | Why Rejected |
|---|---|
| Generate N variants per touchpoint, human picks | 3-5x Gemini free-tier cost; review burden; not needed for v1 |
| Let LLM choose angle from raw signals | Non-deterministic, untestable, more visitor data in prompt |
| Hardcoded templates (no LLM) | Loses personalization already shipped |

### Risk Predictions
- Security: CTA URLs are owner-set, must pass same host check as `safe_dest` to avoid open redirect.
- Data: per-segment dominant signal can mis-target mixed segments — use majority share with `general` fallback below 40%.
- Ops: flag-OFF regression of planner prompt — guard with snapshot test.
- Product: `reply` CTA has no link → attribution via existing reply tracking only (known-gap).
- Migration: chain collision with 6 parallel gap plans — chain at EXECUTE time.

### Key Constraints Accepted
No variant A/B stats; attribution is click-level only, not conversion.

## Touchpoints
- NEW `apps/api/services/signal_angle.py` — `dominant_signal(profiles) -> SignalAngle`, `ANGLE_GUIDANCE` dict, `CtaType` enum, `resolve_cta(site_cfg, requested)`.
- `apps/api/agents/campaign_planner.py` — when flags ON, append angle note + allowed CTA list to prompt; add `cta_type` to output schema; validate/coerce in the JSON validator.
- `apps/api/agents/segmenter.py` — READ ONLY; `build_visitor_profiles` (:105-135) is NOT modified (icp_fit is absent there and adding it would break flag-OFF byte-identity + shared segmenter input) [Gap 6].
- `apps/api/agents/campaign_planner.py` angle computation: `dominant_signal` runs on the RAW profile dicts BEFORE `sanitize_profiles`; `icp_fit` is supplied to it (read from `Visitor.icp_fit`, models/visitor.py:71, via a separate read-only select keyed by the segment's visitor ids) ONLY when `settings.icp_fit_enabled` AND `signal_creative_enabled` are ON; otherwise the `high_icp_fit` rung is skipped. Threshold imports `_STRONG_FIT_AT` from `services/icp_fit.py:112` — never a literal 70 [Gap 6].
- `apps/api/models/site.py` — `cta_config: JSONB nullable` (`{default: str, types: {type: {url, label}}}`).
- `apps/api/schemas/sites.py` + `apps/api/routers/sites.py` (update handler ~419) — validate cta_config.
- `apps/api/routers/click.py` — `build_click_url(..., cta_type=None, campaign_id=None)` adds `ct=` (+ optional `cid=`); `click_redirect` (:82-152): when `ct` is a valid `CtaType`, (a) INSERT one `cta_click_events` row on EVERY hit (with or without `t`; no dedupe), (b) redirect to the owner-STORED URL for that type (cta_config / `Site.booking_url` for book_demo), never a query-string URL; existing `t`→`visitor_emails` write unchanged. Without valid `ct`: byte-unchanged `safe_dest(u)` path [Gap 1, Gap 5]. [N1] `ct` honored ONLY when `settings.cta_types_enabled` (flag OFF = behavior-identical, `ct`/`cid`/`tp` ignored); `cid` UUID-parsed, dropped (stored NULL) if invalid, no FK; no stored URL for that type or `ct=reply` → fall back to `safe_dest(u)`; site-host types re-checked `safe_dest(stored, site.url)==stored` at redirect time, else fall back. [N2] optional `tp=` (touchpoint id): UUID-parsed; if the `CampaignTouchpoint` belongs to a campaign of THIS site_id, stamp `clicked_at` (first hit only) and append `_bid`/`_tp` to site-host redirect targets (same params `decorate_links` adds); foreign/invalid `tp` ignored silently.
- NEW model `apps/api/models/cta_click_event.py` — table `cta_click_events` (id UUID, site_id FK, cta_type String(30), campaign_id UUID nullable, created_at, updated_at). Append-only, NO PII/IP/email/visitor id. Do NOT add cta_type to `visitor_emails` [Gap 1].
- `apps/api/services/campaign_sender.py` — send path (:281-309): append `Site.cta_config` LAST to the `site_row` select (after booking_url); resolve the touchpoint's `cta_type` → stored URL; wrap it as `/c/{site_id}?ct=…&t=…&cid=…&tp=…` via `build_click_url` BEFORE `decorate_links` [C1: pre-assign `tp_id = uuid.uuid4()` BEFORE `_compose_for_recipient` (:427-437), build the `/c/…&tp=tp_id` link, pass it into compose (sentinel-resolved), then create `CampaignTouchpoint(id=tp_id, …)` at the flush (:453-458); an IntegrityError loser discards the id harmlessly — no dependence on DB-assigned ids] [N2 — wrapped site-host CTAs point at the API host so `decorate_links` skips them; `/c/` restores `_bid`/`_tp` + click stamp]; `_personalize`/`_compose_*` (:105-151) resolve `{{cta_link}}` AND `{cta_link}` via the same sentinel pattern as booking_link; empty string when unset/flag OFF. Flag OFF = zero change. [C2] Appending `cta_config` at site_row index 5 breaks 3 unit harnesses mocking a 5-item row — extend each mock to 6 items (`cta_config=None`): `tests/unit/test_campaign_send_booking_link.py:72-79`, `tests/unit/test_gmail_sender_decoration_parity.py:85-91`, `tests/unit/test_agent_origin_exclusion.py:119-127`. Sibling `company-exclusion-list_27-11-26` also edits this file — additive edits only, rebase on head and re-read before editing [Gap 2, Gap 3].
- `apps/api/routers/campaigns.py` — pass site CTA config to planner; test-send preview (~469) mirrors the sender helper (secondary, not the proof surface). NEW endpoint `GET /api/v1/campaigns/{site_id}/cta-clicks` declared ABOVE `GET /{site_id}/{campaign_id}` (:167) so it is not shadowed [Gap 3, Gap 4].
- `apps/api/config.py` — `signal_creative_enabled=False`, `cta_types_enabled=False`.
- NEW migration (cta_config + cta_type) — **chain off `alembic heads` at EXECUTE time; never hardcode down_revision.**
- Web: `apps/web/src/lib/api.ts`, `api-types.ts`, CTA editor in `apps/web/src/components/site-settings-dialog.tsx` (where booking_url lives — NOT dashboard/settings/page.tsx), campaign touchpoint CTA badge [Gap 7].
- Tests: NEW `tests/unit/test_signal_angle.py`, extend `tests/unit/test_campaign_planner_prompt.py`, `tests/unit/test_click_redirect.py`, existing campaign_sender `_personalize` unit tests (cta_link render + wrap), extend `tests/integration/test_click_redirect.py`, NEW `tests/integration/test_cta_attribution.py` [Gap 7], NEW `tests/unit/test_campaign_send_cta_link.py` mirroring `tests/unit/test_campaign_send_booking_link.py` (drives the real send loop) [N3].

## Dominant-signal precedence (pure)
Per visitor: `job_change` (job_changed_at ≤30d) > `pricing_intent` (any page matching /pricing|/plans) > `ai_referral` (ai_source set) > `high_icp_fit` (icp_fit ≥ `_STRONG_FIT_AT`, only when icp_fit flag ON) > `repeat_visit` (total_sessions ≥ 3) > `general`. Segment angle = most common non-general angle if share ≥ 40%, else `general`. Repeat visits already scored in `calculate_intent_score` — no aggregator change.

## Public Contracts
- Planner JSON touchpoint gains optional `cta_type` and top-level `signal_angle` (additive).
- `SiteUpdate.cta_config` optional (additive). Click URL gains optional `ct` (+`cid`, `tp`) query params, honored only when `cta_types_enabled`; invalid `cid`/`tp` dropped; unknown `ct` ignored (falls through to legacy `safe_dest(u)`).
- CTA URL rule (single, non-contradictory) [Gap 5]: every stored CTA URL passes `validate_booking_url` (schemas/sites.py:20-40) AND must be https; site-host types (`free_trial`, `pricing_page`, `resource`) additionally require `safe_dest(url, site.url) == url`; `book_demo` reuses `Site.booking_url` (no second copy; cross-domain allowed for book_demo only); `/c/` with valid `ct` redirects to the stored URL for that type, never a query-string URL.
- New read endpoint `GET /campaigns/{site_id}/cta-clicks` → `{counts: {cta_type: int}}` aggregated from `cta_click_events`, Site.user_id-scoped, 404 on foreign site; route declared above `/{site_id}/{campaign_id}` [Gap 4].
- New table `cta_click_events` (additive migration).

## Blast Radius
~18 files, packages `apps/api`, `apps/web`, `tests`. Risk classes: schema migration (additive: new table + nullable column), public API (additive), trust-boundary redirect, send-path render (`campaign_sender.py` — link wrap + placeholder resolve only; approve/send semantics untouched: drafts.py:281/:370, sender.py:209). Shared-file overlap: `campaign_sender.py` with company-exclusion-list; models/site.py/routers/sites.py with onsite-greeting. No auth/billing.

## Implementation Checklist
1. config flags (default OFF).
2. `signal_angle.py` + unit tests (precedence, 40% threshold, empty input).
3. Planner: flag-gated prompt section (angle guidance is server constant; no visitor text added; existing `sanitize_profiles`/`wrap_untrusted` path unchanged); `cta_type` validation + coercion to site default.
4. Migration: `sites.cta_config` JSONB nullable + NEW table `cta_click_events` + model `models/cta_click_event.py` (register in models `__init__`). Run `alembic heads` with pinned DSN (localhost:5433/disposable) immediately before writing; down_revision = that head.
5. Sites schema/router validation per the CTA URL rule in Public Contracts (validate_booking_url + https; site-host types `safe_dest(url, site.url)==url`; book_demo = Site.booking_url).
6. click.py: valid `ct` → insert `cta_click_events` row on every hit (with/without `t`) + redirect to stored URL for that type; invalid/absent `ct` → unchanged path. Flag-gate on `cta_types_enabled`; UUID-parse cid/tp; reply/no-stored-URL → safe_dest(u); redirect-time safe_dest re-check; tenant-checked `tp` → stamp `clicked_at` + append `_bid`/`_tp` [N1,N2]. Log `cta_type` + site_id only. Unit + integration (extend tests/integration/test_click_redirect.py).
7. campaign_sender.py: append cta_config LAST in site_row select; resolve CTA URL; wrap via build_click_url(`/c/` with ct, t, cid) before decorate_links; resolve `{{cta_link}}`/`{cta_link}` in `_personalize`/`_compose_*` with booking_link sentinel pattern; pre-assign `tp_id = uuid.uuid4()` before `_compose_for_recipient`, build link with `tp=tp_id`, pass into compose, create `CampaignTouchpoint(id=tp_id, …)` [C1]; extend the 3 positional site_row mocks to 6 items with `cta_config=None` (test_campaign_send_booking_link.py:72-79, test_gmail_sender_decoration_parity.py:85-91, test_agent_origin_exclusion.py:119-127) [C2]; unit gate `tests/unit/test_campaign_send_cta_link.py` asserts `tp` is a real UUID equal to the created touchpoint id (db.flush is mocked in the harness). campaigns.py preview mirrors it.
8. campaigns.py counts endpoint declared ABOVE :167, Site.user_id scoped; integration reachability test.
9. Planner angle: compute from raw profiles before sanitize_profiles; icp_fit only when flag ON; `_STRONG_FIT_AT`.
10. Web editor in components/site-settings-dialog.tsx + badge.
11. Mock mode: planner tests use existing Gemini patch seam; no new external calls.

## Acceptance Criteria
AC1–AC6 as defined in the SPEC (same folder).

## Phase Completion Rules
CODE DONE when checklist complete; VERIFIED only after flag-ON Hybrid integration gate + migration round-trip pass via independent vc-tester.

## Verification Evidence
Preconditions (every row): run from repo root with `.venv` present (`.venv/bin/pytest`); Hybrid rows need Docker PG+Redis (`lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`) and DSN pinned to `postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test` (never `.env` prod); migration row uses a disposable postgres:16 DSN; web row needs `apps/web/node_modules`.

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `.venv/bin/pytest tests/unit/test_signal_angle.py -q` | Fully-Automated | AC1 |
| `.venv/bin/pytest tests/unit/test_campaign_planner_prompt.py -q` (flag-OFF snapshot unchanged + flag-ON contains angle/CTA list + coercion) | Fully-Automated | AC2, AC3 |
| `.venv/bin/pytest tests/unit/test_click_redirect.py -q` (`ct` valid+flag ON → stored URL; flag OFF → identical legacy; reply/no URL → safe_dest(u); invalid cid dropped; foreign `u` never used) | Fully-Automated | AC5 (unit) |
| `.venv/bin/pytest tests/unit/test_campaign_send_cta_link.py -q` (NEW, mirrors test_campaign_send_booking_link.py; real send loop: both brace forms; empty when unset; wrapped `/c/…?ct=&tp=`; flag-OFF unchanged) | Fully-Automated | AC3 (send-path render) |
| `DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test .venv/bin/pytest tests/integration/test_cta_attribution.py tests/integration/test_click_redirect.py -q` with flags ON: tp stamps `clicked_at` + `_bid`/`_tp` appended, foreign-site tp ignored, config CRUD + URL rule, foreign site 404, `cta_click_events` row per hit with and without `t`, counts endpoint reachable (not shadowed by `/{site_id}/{campaign_id}`) | Hybrid (Docker PG, lsof precheck) | AC4, AC5, AC6 |
| Migration up/down/up on disposable postgres:16 pinned DSN | Hybrid | schema safety |
| `.venv/bin/pytest tests/unit -q` (incl. test_campaign_send_booking_link.py, test_gmail_sender_decoration_parity.py, test_agent_origin_exclusion.py with 6-item site_row mocks) + integration lane no regression | Fully-Automated/Hybrid | flag-OFF no regression [C2] |
| `cd apps/web && npx tsc --noEmit` | Fully-Automated | web types |
| Real Gemini honors angle/CTA | Agent-Probe (known-gap, needs key) | AC2 quality |

## #10 Verification Finding (no fix planned)
Send only via `send_draft`, which rejects non-approved; `approved` set only at routers/drafts.py:281 (human approve) and :370 (human retry of a failed draft). social_accounts.py:104-203 = LinkedIn connect/status; extension = session reader. Approved-draft→human-send holds everywhere.

## Open User Decisions
Decisions CONFIRMED 27-11-26:
- 40% share rule for segment angle: KEPT — CONFIRMED.
- Cross-domain CTA URL: allowed for `book_demo` only (via Site.booking_url) — CONFIRMED.
- `reply` CTA: untracked — recorded known-gap, no click attribution — CONFIRMED.

## Test Infra Improvement Notes
(none identified yet)

## Resume and Execution Handoff
1. Selected plan: `process/features/campaigns-outreach/active/signal-creative-cta_27-11-26/signal-creative-cta_PLAN_27-11-26.md`
2. Last completed: PLAN + inline VALIDATE (fast mode)
3. Validate-contract: written (below), CONDITIONAL; supplement cycle 3 applied (C1-C2 addressed) — revalidate
4. Context: `process/context/all-context.md`, campaigns-outreach/_GUIDE.md, tests/all-tests.md
5. Next: supplement cycle 3 applied — revalidate from V1, then ENTER EXECUTE MODE (sequential, opus). Run `alembic heads` with pinned DSN before writing migration.

## Validate Contract

Status: PASS
Date: 27-11-26
date: 2026-11-27
generated-by: outer-pvl
supersedes: 2026-11-27 (outer-pvl, pass 3 CONDITIONAL, 0 FAIL / 2 CONCERN C1-C2) — outer PVL pass 4 has current code-read evidence after supplement cycle 3

Parallel strategy: sequential (in-session; 4 Layer 1 dimensions + 7 Layer 2 sections run inline, read-only, cheap-local)
Rationale: 4/7 signals (S1 api+web+tests, S2 schema+public API, S6 trust-boundary redirect + migration, S7 ~18 files); dominant S6. EXECUTE recommendation: sequential, one vc-execute-agent (opus); vc-tester (opus) for EVL. Agent count: 1 execute + 1 tester = 2; cost guard not triggered.

Gate preconditions (environment, NOT blockers — absent on 27-11-26: no `.venv`, no :5433/:6379 listeners):
1. Python 3.11 venv: `python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt`; a 3.9 interpreter is not a valid gate run.
2. Docker: `/Applications/Docker.app/Contents/Resources/bin/docker compose -f infra/docker-compose.yml up -d`, then `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'` must show both listeners.
3. DB pin: `export DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test` in the command env. Never `.env` (Supabase PROD). Migration round-trip uses a disposable postgres:16 DSN.
4. Provisional user decisions (40% share, book_demo-only cross-domain, reply untracked) proceed on their defaults — recorded, not blocking.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1 | dominant-signal precedence, 40% share, empty input, icp rung skipped when flag OFF | Fully-Automated | `.venv/bin/pytest tests/unit/test_signal_angle.py -q` | B |
| AC2/AC3 | flag-OFF prompt + parsed plan byte-identical; flag-ON angle+CTA list; cta_type coercion to site default | Fully-Automated | `.venv/bin/pytest tests/unit/test_campaign_planner_prompt.py -q` | B |
| AC3-render | `{{cta_link}}`/`{cta_link}` resolve via sentinel; empty when unset/flag OFF | Fully-Automated | `.venv/bin/pytest tests/unit/test_personalize.py -q` | B |
| AC3-send | REAL `send_campaign_emails` body carries `/c/{site_id}?ct=…&tp=<uuid>`; `tp` equals the pre-assigned `CampaignTouchpoint.id` (never `None`, no dependence on mocked `db.flush`); flag-OFF body unchanged | Fully-Automated | `.venv/bin/pytest tests/unit/test_campaign_send_cta_link.py -q` (NEW, mirrors test_campaign_send_booking_link.py) | B |
| AC5-unit | valid `ct` + flag ON → stored URL; flag OFF / unknown `ct` / `reply` / no stored URL → legacy `safe_dest(u)`; foreign `u` never used; invalid `cid`/`tp` dropped | Fully-Automated | `.venv/bin/pytest tests/unit/test_click_redirect.py -q` | B |
| AC4/AC5/AC6 | flag-ON: cta_config CRUD + URL rule, foreign site 404, one `cta_click_events` row per hit with/without `t`, tp stamps `clicked_at` + `_bid`/`_tp` on site-host target, foreign-site tp ignored, counts endpoint not shadowed | Hybrid (preconditions 1-3) | `DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test .venv/bin/pytest tests/integration/test_cta_attribution.py tests/integration/test_click_redirect.py -q` | B |
| schema | migration up/down/up (cta_config column + cta_click_events table) | Hybrid (disposable postgres:16) | `DATABASE_URL=<disposable DSN> .venv/bin/alembic -c apps/api/alembic.ini upgrade head && … downgrade -1 && … upgrade head` | B |
| regression | flag-OFF no regression incl. the 3 send-loop harnesses extended to a 6-item site_row (`cta_config=None`) | Fully-Automated / Hybrid | `.venv/bin/pytest tests/unit/test_campaign_send_booking_link.py tests/unit/test_gmail_sender_decoration_parity.py tests/unit/test_agent_origin_exclusion.py -q` then `.venv/bin/pytest tests/unit -q` + pinned integration lane | B |
| web | types | Fully-Automated | `cd apps/web && npx tsc --noEmit` | B |
| AC2-quality | real Gemini honors angle/CTA | Agent-Probe | needs GEMINI key; structlog `gemini_*` events | D |

Failing stubs (Fully-Automated rows; red-first for EXECUTE):
test("should pick job_change over pricing_intent and fall back to general below 40% share", () => { throw new Error("NOT IMPLEMENTED — TDD stub: dominant-signal precedence") })
test("should leave flag-OFF planner prompt and parsed plan byte-identical", () => { throw new Error("NOT IMPLEMENTED — TDD stub: flag-OFF prompt snapshot") })
test("should resolve both brace forms of cta_link and render empty when unset", () => { throw new Error("NOT IMPLEMENTED — TDD stub: cta_link render") })
test("should deliver a /c/ ct-wrapped CTA link whose tp equals the pre-assigned touchpoint id", () => { throw new Error("NOT IMPLEMENTED — TDD stub: cta_link send path") })
test("should honor valid ct only when cta_types_enabled and never redirect to a foreign u", () => { throw new Error("NOT IMPLEMENTED — TDD stub: ct param") })
test("should keep the three send-loop harnesses green with a 6-item site_row", () => { throw new Error("NOT IMPLEMENTED — TDD stub: site_row regression") })

Legacy line form:
- selector/planner: Fully-automated: tests/unit/test_signal_angle.py, tests/unit/test_campaign_planner_prompt.py
- send render: Fully-automated: tests/unit/test_personalize.py, tests/unit/test_campaign_send_cta_link.py
- attribution: hybrid: tests/integration/test_cta_attribution.py + test_click_redirect.py, PG :5433 pinned
- quality: agent-probe: live Gemini | known-gap: reply CTA not click-attributed

Prior-gap closure (cycle 3, verified against code 27-11-26):
- C1 closed: campaign_sender.py compose `_compose_for_recipient` (:427-437) runs before `CampaignTouchpoint(...)` (:448) + `db.flush()` (:458) + `decorate_links(..., touchpoint_id=str(tp_row.id))` (:470). `CampaignTouchpoint.id` is `default=uuid.uuid4` (models/campaign.py:57), applied only at INSERT — so an explicit `id=tp_id` pre-assigned before compose is honored and makes the existing `_tp`/`/o/` uses real UUIDs in mocked harnesses too. Plan body (Touchpoints + checklist 7) now states pre-assign → compose → `CampaignTouchpoint(id=tp_id)`; the old "AFTER flush" text is gone.
- C2 closed: the 3 named harnesses are the only tests mocking the send-path `site_result.first` (grep over tests/ for `send_campaign_emails` + `first.return_value`); each is a 5-tuple at the cited lines; none asserts on a `None` touchpoint id. Plan extends each to 6 items and names them in the regression gate.
- Regression scan of earlier closures holds: click.py:82-91 is still one `Site.url` select + `safe_dest(u)` (flag-OFF byte-identical if new lookups gate on flag + valid `ct`, E8); tenant check pattern events.py (campaign_id IN site's campaigns, clicked_at IS NULL) present; `_STRONG_FIT_AT` (icp_fit.py:112), `icp_fit_enabled` (config.py:1475), campaigns.py `/{site_id}/{campaign_id}` at :167 all as cited.

Dimension findings:
- Infra fit: PASS — no new service; click + campaigns routers mounted; `api_base_url` exists; `build_click_url` extra kwargs additive (only other caller routers/sites.py).
- Test coverage: PASS — C1 (tp UUID pre-assigned, non-vacuous under mocked flush) and C2 (3 harnesses → 6-item rows, named in gate) closed; every developed behavior has a Fully-Automated or Hybrid gate; only Gemini quality is Agent-Probe.
- Breaking changes: PASS — all additive; counts route above campaigns.py:167; flag-OFF planner, send, and `/c/` paths gated.
- Security surface: PASS — `ct` enum + flag gate; redirects only to owner-stored URLs (validate_booking_url + https; site-host re-check at redirect time); `tp` tenant-checked; `cid` stored only; no PII/IP in `cta_click_events`; `_bid` never sent cross-domain. Residual count inflation is a named known-gap (D).
- Selector + planner: PASS — raw profile fields + `_STRONG_FIT_AT` + `icp_fit_enabled` exist.
- Schema/migration: PASS — new table + nullable column; chain off `alembic heads` at EXECUTE with pinned DSN.
- Click attribution (click.py): PASS — mechanically feasible; flag-OFF path unchanged.
- Send path (campaign_sender.py): PASS — C1 ordering resolved; mechanically feasible (E9/E10 below).
- Render path: PASS — booking sentinel pattern reusable for a second sentinel.
- Counts endpoint: PASS — declared above :167, Site.user_id-scoped.
- Web: PASS — editor in components/site-settings-dialog.tsx.

Open gaps: none (0 FAIL / 0 CONCERN). Named residuals (gap-resolution D, not blockers): live Gemini quality probe; `reply` CTA not click-attributed; public `/c/` counts inflatable by anyone holding a site_id (rate limit 120/min/IP) — click-level, not conversions; links sent while flag ON but clicked after flag OFF land on `safe_dest(u)`.
What This Coverage Does NOT Prove:
- Unit gates: real ESP/Gmail click-tracking rewrapping of `/c/` links; real browser cookie behavior of `_rta_svid` on the API host.
- AC3-send unit gate: real SendGrid delivery (EmailSender monkeypatched); a real-DB IntegrityError race with a pre-assigned id (covered only by the unchanged unique constraint).
- Regression gate: only the flag-OFF send loop; flag-ON send loop with cta_config is proven only by the AC3-send gate.
- Hybrid gate: production Supabase schema state; migration chain ordering against 6 sibling plans; concurrent click bursts.
- Agent-Probe: that Gemini actually writes copy matching the angle and uses `{{cta_link}}`.
Gate: PASS (0 FAIL, 0 CONCERN after 3 supplement cycles; env preconditions + provisional decisions are not blockers)
Accepted by: n/a — PASS, no concerns to accept (named D residuals recorded above).

High-risk evidence pack: REQUIRED at EXECUTE (trust-boundary redirect + migration + public API) — `harness/` in this task folder.

Execute-agent instructions (carry forward): E1 rebase on head and re-read models/site.py, routers/sites.py, schemas/sites.py, config.py, services/campaign_sender.py, routers/campaigns.py, routers/click.py right before editing (onsite-greeting + company-exclusion-list touch the same files); additive edits; new select columns appended LAST. E2 pin DATABASE_URL to localhost:5433 or a disposable DSN; never `.env` (Supabase PROD). E3 never change approve/send semantics (drafts.py:281/:370, sender.py:209). E4 the flag-ON integration gate must run on Python 3.11. E5 run `alembic heads` with the pinned DSN immediately before writing the migration. E6 register CtaClickEvent where models are imported so `create_all` builds the table. E7 build the CTA link per recipient (the `t` token is per-email) on both identified and generic compose paths; `generate_bid` raises without ENCRYPTION_KEY — catch and render empty like decorate_links. E8 in click.py run the extra cta_config/booking_url/touchpoint lookups ONLY on valid `ct` + flag ON, so the flag-OFF query sequence is unchanged. E9 campaign_sender.py has no `import uuid` today — add it. E10 `build_click_url` (click.py:43) needs an additive `touchpoint_id=None` kwarg alongside `cta_type`/`campaign_id` to emit `tp=`; keep the existing positional signature and output byte-identical when all new kwargs are None.

## Autonomous Goal Block

```
SESSION GOAL: signal-creative-cta — signal-aware angle + structured CTA types with per-type click counts (campaigns-outreach #8/#9)
Charter + umbrella plan: N/A — single plan
Autonomy: orchestrator self-decides reversible steps; no inline execution (subagents only)
Hard stops: never auto-send; never run alembic/DB scripts against the repo env DATABASE_URL (Supabase PROD); never redirect to a foreign host taken from the query string; flags default OFF and flag-OFF behavior identical (incl. /c/ and send path)
Next phase: EXECUTE: process/features/campaigns-outreach/active/signal-creative-cta_27-11-26/signal-creative-cta_PLAN_27-11-26.md (sequential, vc-execute-agent opus) -> EVL (vc-tester opus)
Validate contract: inline in plan (PASS, 27-11-26, outer PVL pass 4, after 3 supplement cycles)
Execute start: create py3.11 .venv; docker compose up; pytest tests/unit/test_signal_angle.py tests/unit/test_campaign_send_cta_link.py tests/unit/test_campaign_send_booking_link.py | tests/integration/test_cta_attribution.py (PG :5433 pinned) | Gemini probe | high-risk pack: yes
```
