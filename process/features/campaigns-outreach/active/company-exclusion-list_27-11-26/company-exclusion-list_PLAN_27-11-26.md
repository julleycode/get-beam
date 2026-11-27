---
name: plan:company-exclusion-list
description: "Per-site company/domain exclusion list (customer/competitor) enforced at segmenter, send, export, ad push; badge in UI"
date: 27-11-26
feature: campaigns-outreach
---
# Company Exclusion List — PLAN (COMPLEX)

TL;DR: new `site_exclusions` table + pure matcher `services/company_exclusion.py`; one async helper `excluded_visitor_ids()` enforced at 4 chokepoints, flag `company_exclusion_enabled` default OFF; visitors badged, not hidden.

Date: 27-11-26
Complexity: COMPLEX
Status: EXECUTED 27-11-26 — CODE DONE pending independent EVL (vc-tester); G10 manual + prod migration apply outstanding

## Overview
Gap #4 (inbound-playbook): today only email-level suppression exists. Add company/domain exclusion so customers and competitors never get outreach, exports, or ad pushes.

## Decision Summary
### Chosen Approach
Separate exclusion guard (not a new `is_emailable_identity` param) applied at chokepoints, badge-not-hide. `is_emailable_identity` is a pure per-row predicate with regression-gated 3-param signature; exclusion needs a per-site set lookup, so we compute the excluded set once per batch and filter.
### Why This Over Alternatives
| Alternative | Why Rejected |
|---|---|
| Add 4th param to `is_emailable_identity` | Breaks frozen signature + regression tests; still needs set lookup at each caller |
| Hide excluded visitors | Owners lose visibility of competitor research traffic (a valuable signal) |
| Materialized `is_company_excluded` column on visitors | Staleness on list edit; needs backfill job; migration on hot table |
### Risk Predictions
- Security: tenant leak via list endpoints -> Site.user_id gate, 404.
- Data: freemail domain added excludes everyone -> reject freemail list.
- Perf: suffix match per visitor -> load site list once (<=5000), in-memory set w/ parent-domain walk.
- Correctness: missed chokepoint -> grep census gate of all `_get_segment_visitors`/send call sites.
- Product: flag-OFF vacuity -> flag-ON integration gates required.
### Key Constraints Accepted
Exclusion keyed on email domain + resolved company domain only; anonymous visitors without a domain are never excluded.

## Acceptance Criteria
AC-1..AC-11 as defined in `company-exclusion-list_SPEC_27-11-26.md` (same folder), with this PVL amendment:
- **SPEC overrides (PVL cycle 2, Gap 2 — these supersede SPEC text):**
  - AC-3 (override): a visitor is excluded when EITHER `Visitor.company_domain` OR any captured email domain matches an exclusion entry (after parent-domain walk). proven by: G1 + G3; strategy: Hybrid.
  - AC-6 (override): segmentation exclusion is enforced in `run_segmentation` (segmenter) by filtering the `visitors` argument at function entry — not at the AI prompt layer; `/ai/ask` profiles are unaffected. proven by: G3; strategy: Hybrid.
  - AC-7 (override): LinkedIn exclusion is enforced in `_resolve_linkedin_targets`. proven by: G3 + G7; strategy: Hybrid.
  - AC-11 (override): the exclusions UI is a panel on the connectors page (`components/exclusions-panel.tsx`), not a standalone settings page. proven by: G9 + G10; strategy: Agent-Probe.
  - AC-12 (new, Gap 3 — decided, brand protection): with flag ON, approving/sending a pending visitor-keyed draft whose visitor is company-excluded is blocked with a clear error (`company_excluded`). proven by: G3; strategy: Hybrid.
- AC-9 (amended, Gap 5): with flag OFF, every touched path is **behavior-identical and issues zero new queries**; the additive `excluded_reason: null` field on `VisitorOut` is allowed (not "byte-identical"). proven by: G4 + G7 census; strategy: Hybrid.

### Known-contacts vs exclusion (Gap 7)
| Concept | Key | Existing surface | Effect |
|---|---|---|---|
| Known contacts | email hash (`is_known` / `exclude_known`) | connectors known-contacts import | per-person, optional segment filter |
| Company exclusion (new) | domain (email domain + `Visitor.company_domain`) | new Exclusions panel | per-company, hard guard at all outreach chokepoints when flag ON |
Badge priority on visitor rows: `Excluded (<reason>)` wins over `Known contact`; only one badge shown. The two lists are independent — neither writes the other.

## Touchpoints
- NEW `apps/api/models/site_exclusion.py` (`SiteExclusion`: id, site_id FK cascade, domain, company_name?, reason, note?, created_at, updated_at; unique(site_id, domain))
- NEW migration `add_site_exclusions` — **chain off `alembic -c apps/api/alembic.ini heads` at EXECUTE time; never hardcode down_revision**
- NEW `apps/api/services/company_exclusion.py`: `normalize_domain()`, `is_freemail()`, `match_excluded(domains, exclusion_set) -> reason|None` (pure), `async load_exclusions(db, site_id)`, `async excluded_visitor_ids(db, site_id, visitor_ids) -> dict[id, reason]` (resolves merged visitors via `canonical_visitor_id`; matches on email domain + `Visitor.company_domain`)
- NEW `apps/api/schemas/exclusions.py`, NEW `apps/api/routers/exclusions.py` (CRUD + `POST .../import` CSV), mount in `apps/api/main.py`
- `apps/api/config.py`: `company_exclusion_enabled: bool = False`
- **Guarded chokepoints (direct edits):**
  - `apps/api/services/campaign_sender.py`: load exclusion set once after `visitor_ids` built (~:261); per-row check immediately after the `is_email_suppressed` skip (~:385-387); counter `skipped_company_excluded`
  - `apps/api/services/csv_exporter.py` `_get_segment_visitors`: filter
  - `apps/api/agents/segmenter.py` `run_segmentation` (~:183): filter profiles there — NOT inside `build_visitor_profiles` (that would hide visitors from `/ai/ask`)
  - `apps/api/routers/campaigns.py:~125` (segments -> planner input): filter
  - `apps/api/routers/campaigns.py` `_resolve_linkedin_targets` (~:737; callers :870, :994): filter `visitor_ids` BEFORE the loop
  - `AutoDrafter.generate_for_visitor` (callers `tasks/resolution_tasks.py:158`, `services/job_change_detector.py:518`): early-return when excluded
- **Covered via `_get_segment_visitors` (no direct edit, census-asserted):** `services/ads_push.py`, `services/crm_push.py:90`, `services/crm/contact_mapper.py`, `routers/exports.py`
- **Ungated by design (provisional):** hot-lead alerts + outcome digest (owner-facing, not outreach)
- `apps/api/schemas/visitors.py` `VisitorOut.excluded_reason: str | None = None` (additive) + `routers/visitors.py` list populate
- Web: `apps/web/src/app/dashboard/settings/page.tsx` is a 16-line redirect stub — panel goes on `apps/web/src/app/dashboard/connectors/page.tsx` next to known-contacts import, as NEW `apps/web/src/components/exclusions-panel.tsx`; `lib/api.ts` + `lib/api-types.ts`; badge in `app/dashboard/visitors/page.tsx`
- Tests: NEW `tests/unit/test_company_exclusion.py`, NEW `tests/unit/test_company_exclusion_census.py`, NEW `tests/integration/test_company_exclusion.py`

## Public Contracts
- New REST: `GET/POST /api/v1/sites/{site_id}/exclusions`, `DELETE /api/v1/sites/{site_id}/exclusions/{id}`, `POST /api/v1/sites/{site_id}/exclusions/import` (multipart CSV). All `get_current_user` + site ownership, 404 on foreign.
- Additive response field `VisitorOut.excluded_reason`.
- Campaign send result gains counter `skipped_company_excluded`.

## Blast Radius
~20 files, api + web; risk classes: schema migration, public API (additive) -> **high-risk evidence pack required** (`vc-risk-evidence-pack`). No pixel, no external provider calls. No auth changes.
Sibling overlap: `signal-creative-cta_27-11-26` also edits `campaign_sender.py` and `campaigns.py` — keep edits additive and rebase on current head at EXECUTE.

## Open User Decisions
All 5 defaults CONFIRMED by user 27-11-26 (accepted at ENTER EXECUTE MODE):
1. Badge excluded visitors (not hide). — CONFIRMED 27-11-26
2. No fuzzy company-name match in v1 (domain only). — CONFIRMED 27-11-26
3. CRM customer auto-sync deferred -> backlog NOTE `process/features/campaigns-outreach/backlog/crm-customer-auto-exclusion_NOTE_27-11-26.md` (written at EXECUTE step 9). — CONFIRMED 27-11-26
4. CSV import caps 5000 rows / 1MB. — CONFIRMED 27-11-26
5. Hot alerts + outcome digest ungated (owner-facing). — CONFIRMED 27-11-26

## Implementation Checklist
- [x] 1. Run `alembic heads` (DATABASE_URL pinned to localhost:5433); create model + migration chained to current head.
- [x] 2. `company_exclusion.py` pure helpers + loader; parent-domain walk (`a.b.acme.com` -> `b.acme.com` -> `acme.com`); reject entries with <2 labels and entries equal to a small built-in public-suffix list (`com, net, org, co.uk, com.au, co, io, ...`; no `tldextract`); own freemail set that is a superset of `enricher._FREE_MAIL_DOMAINS` (do NOT import from enricher; unit test asserts superset); merged visitors resolved via `canonical_visitor_id`.
- [x] 3. Router + schemas + CSV import (stdlib csv, 1MB/5000 caps, per-row errors, upsert on (site_id,domain)).
- [x] 4. Config flag.
- [x] 5. Wire every guarded chokepoint in Touchpoints, each `if settings.company_exclusion_enabled:` guarded (flag OFF = zero new queries); log `company_exclusion_applied` with site_id + excluded_count only.
- [x] 6. `excluded_reason` on visitor list (flag ON only, else None).
- [x] 7. Web `components/exclusions-panel.tsx` on connectors page + api client + visitors badge (priority per Known-contacts table).
- [x] 8. Tests per Verification Evidence incl. structural census test.
- [x] 8a. Segmentation (Gap 1): in `run_segmentation` (segmenter.py), filter the `visitors` argument at the TOP of the function (flag ON) so the allowed-member-id set built at segmenter.py:212 and :216-218 derives from the filtered list; if filtered list is empty return `[]`. Also guard the re-read at `tasks/segmentation_tasks.py:85` and the segment member read at `routers/segments.py:87` (or add both to the G7 covered-via allow-list with the reason "inputs already filtered by run_segmentation"); both are census-listed.
- [x] 8b. Draft approve guard (Gap 3, decided): in `routers/drafts.py` approve path (~:258, before `send_draft`) and in `send_draft` itself, when flag ON and the draft is visitor-keyed, resolve canonical visitor and reject with HTTP 409 `{"detail":"company_excluded"}` if excluded; draft stays pending; log `company_exclusion_applied` (site_id + count only). Add both call sites to G7 census.
- [x] 9. Write backlog NOTE `crm-customer-auto-exclusion_NOTE_27-11-26.md`; assemble high-risk evidence pack.

## Verification Evidence
All commands from repo root with `.venv/bin/python -m pytest`. All DB gates: `DATABASE_URL=postgresql+asyncpg://...@localhost:5433/...` (or disposable container). Never bare alembic.
| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| G1 `.venv/bin/python -m pytest tests/unit/test_company_exclusion.py -q` (normalize, subdomain walk, <2-label + public-suffix reject, freemail superset of enricher set, CSV parse/caps) | Fully-Automated | AC-2, AC-8 |
| G2 `.venv/bin/python -m pytest tests/integration/test_company_exclusion.py -q -k crud` CRUD + foreign-site 404 | Hybrid (PG+Redis) | AC-1 |
| G3 same file `-k flag_on`: send skips + `skipped_company_excluded`; export/ads-push/CRM-push rows drop; `run_segmentation` omits while `/ai/ask` profiles still include; planner input filtered; `_resolve_linkedin_targets` drops; `AutoDrafter.generate_for_visitor` no draft; merged visitor via canonical id excluded; segmentation membership omits excluded visitor (all-excluded input returns `[]`); Celery `segmentation_tasks` path and `GET` segments route (segments.py:87) omit excluded; approve of pending visitor-keyed draft for excluded visitor returns 409 `company_excluded` and draft is not sent | Hybrid | AC-3..AC-7, AC-12 |
| G4 same file `-k flag_off`: behavior-identical, zero new queries (statement-count assert), `excluded_reason` null | Hybrid | AC-9 |
| G5 caplog assert no domain/email strings in log events | Fully-Automated | AC-10 |
| G6 migration up/down/up on disposable postgres:16 (pinned DSN) | Hybrid | schema safety |
| G7 `.venv/bin/python -m pytest tests/unit/test_company_exclusion_census.py -q` — AST census modelled on `tests/unit/test_candidate_outreach_gate.py`: every caller of `_get_segment_visitors`, send loop, `_resolve_linkedin_targets`, `generate_for_visitor`, planner segment input is either guarded or in the covered-via allow-list | Fully-Automated | AC-5 completeness, AC-9 |
| G8 `.venv/bin/python -m pytest tests/unit -q` incl. `test_agent_origin_exclusion.py` | Fully-Automated | no regression |
| G9 `cd apps/web && npx tsc --noEmit` | Fully-Automated | AC-11 typecheck |
| G10 Manual: connectors-page panel add/import/delete + badge priority | Agent-Probe (Clerk harness gap) | AC-11 |

## Execution Notes (EXECUTE 27-11-26)
- Migration: `e8c4b2a7d913_add_site_exclusions`, down_revision `d3f8a2c61b47` (single live head observed via pinned-DSN `alembic heads`).
- E2: `skipped_company_excluded` is present in the send summary ONLY when the flag is ON (flag-OFF summary shape unchanged).
- E10: `POST /segments/{site_id}/run` still reports the pre-filter `visitors_analyzed` count (accepted per contract).
- Segmentation re-read (`segmentation_tasks.py`) and `routers/segments.py` covered via the `run_segmentation` entry filter (census allow-list, reason "inputs already filtered by run_segmentation").
- `routers/visitors.py list_visitors` is also census-asserted (badge lookup is flag-guarded).

## Deviations
- File/name (within blast radius): helper `filter_visitor_ids` + `draft_is_company_excluded` + `CompanyExcludedError` + `log_applied` added to `services/company_exclusion.py` beyond the named `excluded_visitor_ids` — thin wrappers, same semantics. Impact: none on contracts.
- G3 ads-push/CRM-push "rows drop" is proven at the shared chokepoint `_get_segment_visitors` (both callers census-asserted), not by invoking the provider push functions (they call live/mock providers). Impact: coverage equivalent for row selection.
- Env: installed `pytest`, `pytest-asyncio`, `fakeredis` into `.venv` (were missing; versions per pyproject `[test]` extras); created local DB `retarget_agent_test` on :5433.

## Phase Completion Rules
CODE DONE when G1-G9 green by independent vc-tester; VERIFIED only after G10 manual check, flag-ON evidence, and high-risk evidence pack.

## Test Infra Improvement Notes
(none identified yet) — Playwright UI leg blocked on known Clerk auth-harness gap.

## Resume and Execution Handoff
1. Plan: this file. 2. Last completed: PLAN + VALIDATE pass 1 + PVL supplement cycle 1 + VALIDATE pass 2 (CONDITIONAL, 3 new gaps N-1..N-3). 3. Validate-contract: below — PVL supplement cycle 2, then re-run PVL from V1. 4. Context: `process/context/all-context.md`, campaigns-outreach/_GUIDE.md, tests/all-tests.md. 5. Next: re-validate -> user confirms Open User Decisions -> ENTER EXECUTE MODE -> step 1.

## Validate Contract

Status: PASS
Date: 27-11-26
date: 2026-11-27
generated-by: outer-pvl
supersedes: 2026-11-27 (outer-pvl) — outer PVL re-run from V1 after PVL supplement cycle 2; N-1..N-3 re-checked against current code

Parallel strategy: sequential
Rationale: 5/7 signals (S1 api+web+tests, S2 schema+API, S5 depth requested, S6 schema-migration + public-API, S7 ~20 files). Dominant signal: one shared helper across every chokepoint, and sibling `signal-creative-cta_27-11-26` edits the same campaign_sender.py / routers/campaigns.py, so one opus vc-execute-agent working sequentially avoids edit collisions.

Fan-out note: Layer 1 (4 dimensions) and Layer 2 (sections) ran inline by reading code; no Agent tool was available in this subagent. Caller census re-run with grep over `apps/api`: `run_segmentation` (segmentation_tasks.py:75, segments.py:87), `_get_segment_visitors` (csv_exporter.py:142/164/180, crm_push.py:90, ads_push.py:272), `_resolve_linkedin_targets` (campaigns.py:870/994), `generate_for_visitor` (resolution_tasks.py:158, job_change_detector.py:518), `send_draft` (drafts.py:294 approve, drafts.py:375 retry). No new caller since cycle 2.

PVL cycle 3 — cycle-2 gaps (3/3 closed, verified against code):
- N-1 CLOSED — step 8a filters `visitors` at the top of `run_segmentation` (segmenter.py:175; profiles built :183; `input_ids` :209; membership :217), so the allowed-member set derives from the filtered list, with an empty short-circuit before the Gemini call. `segmentation_tasks.py:85` re-reads profiles for all visitors but keeps only rows whose id is a `SegmentMember` of a segment that `run_segmentation` already filtered, so the allow-list reason "inputs already filtered by run_segmentation" holds. `segments.py:87` is a direct `run_segmentation` call and is covered by the entry filter.
- N-2 CLOSED — the plan's Acceptance Criteria now carry explicit overrides for AC-3 (Visitor.company_domain + email domain), AC-6 (run_segmentation entry), AC-7 (`_resolve_linkedin_targets`), AC-11 (connectors-page panel), plus AC-9 (amended) and new AC-12. Each has a gate and a strategy. The overrides state that they supersede the SPEC text.
- N-3 CLOSED — decided: 409 `company_excluded` at approve and inside `send_draft` (step 8b, AC-12). Code fact: AutoDrafter drafts are created with `post_id=None` (auto_drafter.py:128-138), and `send_draft` fails those at `send_draft_no_target` (sender.py:356). So no visitor-keyed draft can actually be posted today, and the guard is defense-in-depth. Placement precision is in E7-E9.
- Regression: flag-OFF keeps zero new queries (steps 5, 6, 8a, 8b are each flag-guarded; G4 asserts statement count). Census complete per the list above.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-2, AC-8 | normalize, parent-domain walk, <2-label + public-suffix reject, freemail superset of enricher set, CSV caps/row errors | Fully-Automated | G1 `.venv/bin/python -m pytest tests/unit/test_company_exclusion.py -q` | B |
| AC-10 | log events carry site_id + counts only | Fully-Automated | G5 same unit file, caplog case | B |
| AC-5 completeness, AC-9 | every outreach chokepoint (incl. run_segmentation entry, approve_draft, retry_draft, send_draft) carries the flag-guarded check; owner-facing sites allow-listed | Fully-Automated | G7 `.venv/bin/python -m pytest tests/unit/test_company_exclusion_census.py -q` | B |
| no regression | gate tests unchanged, incl. `is_emailable_identity` 3-param signature | Fully-Automated | G8 `.venv/bin/python -m pytest tests/unit -q` | A |
| AC-1 | CRUD + import, foreign site 404, site delete removes exclusions | Hybrid | G2 `.venv/bin/python -m pytest tests/integration/test_company_exclusion.py -q -k crud` — precondition: PG :5433 + Redis :6379 up (lsof check), DATABASE_URL pinned to `postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test` | B |
| AC-3..AC-7, AC-12 | flag ON: send skip + counter; export/ads/CRM drop; LinkedIn drop; segmentation membership excludes (incl. all-excluded -> `[]` with no Gemini call; Celery task path and `POST /segments/{site_id}/run`); planner input filtered; AutoDrafter no draft; merged visitor excluded; approve and retry of an excluded visitor-keyed draft -> 409 `company_excluded`, draft status unchanged (still pending / still failed), no sibling auto-reject, no voice example | Hybrid | G3 same file `-k flag_on` (mandatory; flag-OFF-only evidence is vacuous), same precondition | B |
| AC-9 | flag OFF: behavior-identical, zero new queries, `excluded_reason` null | Hybrid | G4 same file `-k flag_off` with statement-count assert | B |
| schema | migration up/down/up | Hybrid | G6 alembic on a disposable postgres:16, DATABASE_URL pinned to the container DSN | B |
| AC-11 typecheck | web client/types/panel/badge compile | Fully-Automated | G9 `cd apps/web && npx tsc --noEmit` | B |
| AC-11 UI | panel add/import/delete + badge priority | Agent-Probe | G10 manual dev-server walk | D |

Failing stubs (Fully-Automated rows):
- G1: `def test_should_normalize_and_match_parent_domain(): raise NotImplementedError("TDD stub: normalize + parent-domain walk")`
- G1: `def test_should_reject_freemail_and_public_suffix(): raise NotImplementedError("TDD stub: freemail + public-suffix reject")`
- G5: `def test_should_log_counts_only(): raise NotImplementedError("TDD stub: no domain/email in logs")`
- G7: `def test_should_wire_exclusion_at_every_outreach_chokepoint(): raise NotImplementedError("TDD stub: structural census")`
- G8: none (existing suite)
- G9: none (typecheck command, not a test)

Legacy line form:
- unit: Fully-automated: `.venv/bin/python -m pytest tests/unit -q`
- integration: hybrid: `.venv/bin/python -m pytest tests/integration/test_company_exclusion.py -q` + PG/Redis up, pinned test DSN
- migration: hybrid: disposable postgres:16, pinned DSN
- web: Fully-automated: `cd apps/web && npx tsc --noEmit`
- UI: agent-probe: manual panel + badge walk
- UI e2e: known-gap: Clerk auth harness (gap-resolution D)

Dimension findings:
- Infra fit: PASS — UI target, FK precedent (`models/agent_profile.py:34`), and mount precedent (`main.py:517`) unchanged since cycle 2. Hybrid gates are precondition-only (PG/Redis/.venv must be up at EXECUTE); this is an environment precondition, not a plan gap.
- Test coverage: PASS — G3 now names segmentation membership, both segmentation entry paths, and the draft approve/retry 409 with the status-unchanged assertion. G7 census covers every caller found by grep.
- Breaking changes: PASS — SPEC/plan drift resolved by explicit AC overrides. The REST surface is new, `VisitorOut.excluded_reason` is additive, the 409 only fires with the flag ON, and `is_emailable_identity` is untouched.
- Security surface: PASS — tenant gate via `verify_site_access` (404), Draft lookup already scoped by `Draft.user_id`, PII-free logs, freemail + public-suffix guard, no auth change. High-risk evidence pack (schema migration + public API) is required at EXECUTE step 9, before VERIFIED.
- Model/migration: PASS — chain off live `alembic heads` at EXECUTE; `ondelete="CASCADE"` (E4).
- Service/matcher: PASS — email domain + `Visitor.company_domain`, walk stopped at 2 labels, canonical resolution.
- Chokepoints: PASS — census complete (see fan-out note); owner-facing sites stay ungated per provisional decision 5.
- Segmenter placement: PASS — entry filter on `visitors` fixes `input_ids` (:209) and membership (:217).
- Drafts lifecycle: PASS — guarded at approve + send_draft; placement pinned in E7-E9.
- UI: PASS — badge priority table present; precedent `visitors/page.tsx:870`, `schemas/visitors.py:44`.

Execute-agent instructions:
- E1: The census allow-list (ungated, owner-facing) names `hot_alert.py`, `outcome_digest.py`, `daily_digest.py` and campaign test-send.
- E2: `skipped_company_excluded`: either always present as 0 or present only with the flag ON. Pick one and state it in the phase report.
- E3: CSV import reads at most 1MB+1 bytes (`await file.read(MAX + 1)`).
- E4: Migration DDL carries `ondelete="CASCADE"` on `site_id -> sites.site_id`; G2 adds a site-delete case.
- E5: AutoDrafter early return is the first statement, before any LLM call.
- E6: Rebase on current head at EXECUTE; sibling `signal-creative-cta_27-11-26` touches the same files.
- E7: In `approve_draft` the exclusion check goes right after the pending-status check and BEFORE `draft.status = DraftStatus.approved` / commit (drafts.py:280-281), `_auto_reject_siblings`, and `_save_voice_example`. Putting it just before `send_draft` (:294) would leave the draft approved and siblings rejected, which breaks "draft stays pending".
- E8: Inside `send_draft` (sender.py:209), raise a typed `CompanyExcludedError` before any status mutation; do not return False. Returning False would surface the misleading 502 "Reconnect your account" message. Map the error to 409 `{"detail":"company_excluded"}` in BOTH `approve_draft` and `retry_draft` (drafts.py:375), and add `retry_draft` to the G7 census next to approve and send_draft.
- E9: Resolve the site for the check from `draft.site_id`. If it is NULL, fail open (no lookup) and log the count-only event; a NULL-site visitor draft cannot be posted anyway (sender.py:356).
- E10: The G3 "segments route" case is `POST /api/v1/segments/{site_id}/run` (`trigger_segmentation`, segments.py:65-87), not a GET. Its `visitors_analyzed` count may still report the pre-filter number; that is acceptable, so state it in the phase report.

Open gaps:
- Known-gap (D): Playwright UI leg blocked on the Clerk auth harness; G10 is manual only.
- Not blockers (per caller): Hybrid gate environment preconditions (PG/Redis/.venv) and the 5 provisional Open User Decisions, which still need user confirmation before EXECUTE.
What this coverage does NOT prove:
- G1/G5/G7 unit: real Postgres query plans at 5000 entries x large segments; real prod `Visitor.company_domain` value shapes (rDNS/ISP domains); census completeness for callers added after this plan.
- G2/G3/G4 integration: Celery/APScheduler scheduling end to end; live Gemini segmentation output; live LinkedIn/phantommm, Meta/Google, CRM provider calls; a real social post send.
- G6 migration: prod apply and lock behavior (operator step).
- G8: behavior outside unit-tested modules.
- G9 tsc: rendering, copy, import-error display.
- G10 probe: automated regression of panel/badge.
Gate: PASS (0 FAIL, 0 CONCERN; cycle-2 gaps N-1..N-3 closed; placement precision recorded as E7-E10)
Accepted by: n/a — Gate PASS; no CONDITIONAL concerns to accept (provisional Open User Decisions 1-5 still need user confirmation before EXECUTE)

## Autonomous Goal Block

```
SESSION GOAL: Company exclusion list (customers/competitors) enforced at send, export/ads/CRM, LinkedIn outreach, segmentation membership, planner input, auto-drafts, draft approve/retry (409 company_excluded); badge-not-hide; flag company_exclusion_enabled default OFF
Charter + umbrella plan: N/A — single plan
Autonomy: reversible steps auto-proceed; follow feedback_autonomous_phase_execution.md
Hard stop conditions / safety constraints:
- Never run alembic or any DB script without DATABASE_URL pinned to localhost:5433 or a disposable container (repo env file = Supabase PROD)
- Chain migration off live `alembic heads` at EXECUTE time; sibling 27-11-26 plans run sequentially
- is_emailable_identity keeps its 3-param signature
- No auto-send; no domains/emails in logs; flag stays OFF
- Flag-ON integration gates mandatory (flag-OFF-only evidence is vacuous)
- Confirm provisional Open User Decisions 1-5 before EXECUTE
Next phase: EXECUTE: process/features/campaigns-outreach/active/company-exclusion-list_27-11-26/company-exclusion-list_PLAN_27-11-26.md
Validate contract: inline in plan (Gate: PASS, outer-pvl, 2026-11-27; execute-agent instructions E1-E10)
Execute start: .venv/bin/python -m pytest tests/unit -q | tests/integration/test_company_exclusion.py (PG+Redis, DSN postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test) | probe: connectors panel + badge | high-risk pack: yes (schema migration + public API)
```
