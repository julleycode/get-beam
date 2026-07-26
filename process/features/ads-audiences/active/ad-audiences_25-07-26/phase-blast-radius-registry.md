---
name: plan:ad-audiences-blast-radius-registry
description: "Ad Audiences — cross-phase blast-radius claim registry (append-only)"
date: 25-07-26
metadata:
  node_type: memory
  type: plan
  feature: ads-audiences
  phase: registry
---

# Ad Audiences — Phase Blast-Radius Registry

Append-only. Each phase's authoring agent appends its `## Phase N` section here at plan-creation
time and never overwrites a prior section. Purpose: prove disjoint (or explicitly-declared
extension-point) file ownership across the 3 phase plans before EXECUTE begins on any of them.

---

## Phase 1 — Foundation

**Owns (creates, and owns for all future structural edits unless an extension point is declared below):**

- `apps/api/models/ad_connection.py`
- `apps/api/models/ad_audience_link.py`
- `apps/api/migrations/versions/{new_rev}_add_ad_connections.py`
- `apps/api/migrations/versions/{new_rev2}_add_ad_audience_links.py`
- `apps/api/services/ads/base.py`
- `apps/api/services/ads/factory.py`
- `apps/api/services/ads/__init__.py`
- `apps/api/services/ads/meta.py` (creates as stub; Phase 2 owns the real-logic body — see Extension Points)
- `apps/api/services/ads/google.py` (creates as stub; Phase 3 owns the real-logic body — see Extension Points)
- `apps/api/services/ads/linkedin.py` (permanently stub; no future phase touches this file's logic)
- `apps/api/services/ads_push.py` (creates; Phase 3 gets a scoped Google-only extension point — see Extension Points)
- `apps/api/services/ads_rate_limiter.py`
- `apps/api/tasks/ads_tasks.py` (creates; Phase 2 and Phase 3 get scoped extension points — see Extension Points)
- `apps/api/routers/ads.py` (creates; Phase 2 and Phase 3 get scoped extension points — see Extension Points)
- `apps/api/schemas/ads.py`
- `apps/api/config.py` (append-only new block; no other phase edits config.py)
- `apps/web/src/components/ad-connect-panel.tsx` (creates; Phase 2 gets a scoped extension point — see Extension Points)
- `apps/web/src/app/dashboard/connectors/page.tsx` (edit — mount point only; no other phase touches this file)
- `apps/web/src/lib/api.ts` (append-only; no other phase edits this file)

**Read-only imports (never edited by any phase):** `apps/api/services/csv_exporter.py`,
`apps/api/services/encryption.py`, `apps/api/services/oauth_state.py`.

**Hard-forbidden for all phases:** `apps/api/models/crm_connection.py`,
`apps/api/routers/crm.py`, `apps/api/services/crm.py`, `apps/api/services/crm/*`,
`apps/api/services/crm_push.py`, `apps/api/services/crm_rate_limiter.py`,
`apps/api/tasks/crm_tasks.py`.

**Classification:** parallel-safe once Phase 1 is complete — Phase 2 and Phase 3 both depend on
Phase 1 finishing first, but have no ordering dependency on each other.

---

## Phase 2 — Meta Live

**Owns (creates — new files, no conflict with Phase 1 or Phase 3):**

- `tests/unit/test_ads_meta.py`
- `tests/integration/test_ads_meta_live.py`
- `apps/web/e2e/connectors-ads-push-warning.spec.ts`

**Extension points on Phase-1-owned files (declared, not a conflict — scoped edits only, no
structural changes to shared registry/factory/base):**

- `apps/api/services/ads/meta.py` — Phase 2 replaces the `# PHASE 2:`-marked stub bodies with
  real logic. Phase 1 never edits this file again after handoff.
- `apps/api/tasks/ads_tasks.py` — Phase 2 may add a Meta-specific async-upload leg inside the
  existing task function; no new task, no signature change to the shared task entry point.
- `apps/api/routers/ads.py` — Phase 2 adds `below_minimum`/`minimum_threshold` response fields
  to the existing `push` endpoint (additive only, no existing field renamed/removed).
- `apps/web/src/components/ad-connect-panel.tsx` — Phase 2 renders the AC13 error message and
  AC7 warning text returned by the push endpoint; no structural change to the panel's
  provider-list rendering logic (that stays Phase-1-owned).
- `apps/api/services/ads_push.py` — **(appended 26-07-26 at EXECUTE time per Execute-Agent
  Instruction E3 in the Phase 2 validate-contract; closes the registry-declaration gap the
  inner-PVL pass found.)** Phase 2 adds a scoped `fresh_access_token(db, conn)` helper
  (structurally identical to `crm_push.fresh_access_token`) and one guarded call site inside
  `push_segment_to_ads` immediately before `create_or_update_audience`, plus the additive
  `below_minimum`/`minimum_threshold` fields on `PushSegmentOutcome`. Additive only — no
  existing function signature changed, no restructure of the Phase-1 safety-filter/hash
  sequence. The refresh call is `getattr`-guarded so non-Meta providers (which have no
  `refresh_tokens` method) are skipped, keeping Phase 3's Google path untouched. Structurally
  isolated from Phase 3's declared `if provider == "google":` EEA-exclusion branch.
- `apps/api/schemas/ads.py` — **(appended 26-07-26 at EXECUTE time, same E3 rationale.)** Phase 2
  adds the two additive response fields `below_minimum: bool` / `minimum_threshold: int` to
  `PushAdSegmentResult` (the schema half of the already-declared `routers/ads.py` extension
  point above — the router cannot return the fields without them existing on the model). No
  existing field renamed or removed.
- `apps/web/src/lib/api-types.ts` — **(appended 26-07-26 at EXECUTE time, same E3 rationale.)**
  Phase 2 adds the two OPTIONAL fields `below_minimum?: boolean` / `minimum_threshold?: number`
  to the existing `AdPushResult` interface — the TypeScript mirror of the `schemas/ads.py`
  addition above, without which the panel cannot read the fields the push endpoint now returns.
  Optional-typed so no existing caller breaks. This file was not listed in any phase's Owns
  block at plan time (an omission, since Phase 1 created the interface); treated here as an
  append-only extension point on Phase-1-created code, matching the `apps/web/src/lib/api.ts`
  convention.
- `tests/unit/test_ads_stub_501.py` — **(appended 26-07-26 at EXECUTE time, same E3 rationale.)**
  Phase 2 narrows this Phase-1 test from `["meta", "google"]` to `["google"]` and flips the
  meta leg of `test_ads_stub_501_provider_really_raises_not_implemented` from
  "raises NotImplementedError" to "returns a real facebook.com OAuth URL". Forced by this
  phase's own deliverable: the test asserted meta IS a stub, which Phase 2 exists to stop being
  true. Google's stub-501 coverage is unchanged, and meta's flag-off 501 path stays covered by
  `tests/unit/test_ads_flag_off_501.py`. No Phase-3 surface touched.

**Hard-forbidden:** `apps/api/services/ads/google.py`, `apps/api/services/ads/linkedin.py`,
`apps/api/services/ads/base.py`, `apps/api/services/ads/factory.py` (Phase 3 / Phase 1 owned —
Phase 2 reads only). Same CRM/csv_exporter hard-forbidden list as Phase 1.

**Classification:** parallel-safe with Phase 3 — no shared file has both phases writing to the
same lines. `ads_tasks.py` and `routers/ads.py` are touched by both Phase 2 and Phase 3 as
extension points; see Potential Blast Radius Conflicts below for the resolution.

---

## Phase 3 — Google Live

**Owns (creates — new files, no conflict with Phase 1 or Phase 2):**

- `tests/unit/test_ads_google.py`
- `tests/integration/test_ads_google_live.py`
- `tests/unit/test_ads_eea_exclusion.py`

**Extension points on Phase-1-owned files (declared, not a conflict — scoped edits only):**

- `apps/api/services/ads/google.py` — Phase 3 replaces the `# PHASE 3:`-marked stub bodies with
  real logic. Phase 1 never edits this file again after handoff.
- `apps/api/services/ads_push.py` — Phase 3 adds a scoped `if provider == "google":` EEA-region
  exclusion branch. This branch is additive and structurally isolated from the shared
  `_get_segment_visitors`/`_sha256` call sequence Phase 1 built — it runs strictly after that
  shared sequence and only affects the Google code path. Meta's payload path (Phase 2) is
  untouched by this branch.
- `apps/api/tasks/ads_tasks.py` — Phase 3 may add a Google-specific leg inside the existing task
  function, same pattern as Phase 2's extension; no new task, no signature change.
- `apps/api/routers/ads.py` — Phase 3 makes no response-shape change (EEA-excluded rows count
  as ordinary "skipped" via the existing pushed/skipped counters Phase 1 already built) — this
  extension point is read-only awareness, not an edit, unless RESEARCH finds otherwise.

**Hard-forbidden:** `apps/api/services/ads/meta.py`, `apps/api/services/ads/linkedin.py`,
`apps/api/services/ads/base.py`, `apps/api/services/ads/factory.py` (Phase 2 / Phase 1 owned —
Phase 3 reads only). Same CRM/csv_exporter hard-forbidden list as Phase 1.

**Extension point on `apps/api/config.py` (added 25-07-26, PVL-supplement — reconciles the gap
flagged by Phase 3's Validate Contract Open Gaps):** `apps/api/config.py` is otherwise
Phase-1-owned/append-only (see Phase 1's Owns list above). Phase 3 is granted a narrow,
field-scoped extension point: it may append EXACTLY ONE new field group —
`google_ads_developer_token: str = ""` (plus adding that field name to the existing
`field_validator` whitespace-strip list, same precedent as every other OAuth credential field) —
required for the Google Ads API `developer-token` HTTP header used by
`GoogleAdsProvider.create_or_update_audience`'s UserList-creation sub-call (see Phase 3's Step C1
Validate Contract finding). This mirrors the `ads_tasks.py` / `routers/ads.py` extension-point
format above: additive-only, no existing field renamed/removed/restructured, and no other Phase
3 edit to `config.py` beyond this one field group is authorized under this grant.

**Registry append (26-07-26, PLAN-SUPPLEMENT, Phase 3 inner-loop RESEARCH fold-in):** `apps/api/services/ads_push.py` Phase-3 extension-point entry (above) is extended by one line: + provider-aware refresh-token selection in `fresh_access_token` (as-built `ads_push.py:146` passes the decrypted ACCESS token to `refresher(token)`; Google's refresh call needs the decrypted REFRESH token instead — see the phase plan's new Step B checklist item). This is a second, scoped `ads_push.py` touch beyond the existing EEA-branch extension point; same additive-only, no-other-edit constraint applies.

**Registry append (26-07-26, EXECUTE time — forced-by-deliverable test flip, same rationale and
precedent as Phase 2's own `tests/unit/test_ads_stub_501.py` entry above):**
`tests/unit/test_ads_stub_501.py` — Phase 3 flips the `google` leg from "raises
NotImplementedError" to "returns a real accounts.google.com OAuth URL", because this phase's
deliverable is exactly that Google stops being a stub. Since no READY provider raises
`NotImplementedError` any more, the router's 501 mapping is re-proven against a SYNTHETIC stub
provider inside the same test rather than deleted — coverage is preserved, not removed. Meta's
Phase-2 assertion is untouched; flag-off 501 stays covered by `tests/unit/test_ads_flag_off_501.py`.

**Not used (declared but unexercised):** Phase 3's `apps/api/tasks/ads_tasks.py` and
`apps/api/routers/ads.py` extension points were NOT edited — no Google-specific task leg or
response-shape change proved necessary (EEA-excluded rows fall out as ordinary `skipped`). This is
a narrowing of the declared blast radius, not an expansion.

**Classification:** parallel-safe with Phase 2 (see resolution below for the two shared
extension-point files).

---

## Potential Blast Radius Conflicts

**`apps/api/tasks/ads_tasks.py`** — both Phase 2 and Phase 3 declare a scoped extension point
(a provider-specific async-upload leg inside the existing task function). Resolution: each
phase's addition MUST be a clearly separated `if provider == "meta":` / `if provider ==
"google":` branch inside the same function body — never a shared/ambiguous code path. If Phase 2
and Phase 3 execute in parallel, the SECOND phase to land its EXECUTE step re-reads the file post
Phase-1-baseline and adds its branch alongside the first phase's branch (standard additive merge,
not a rewrite). No line-level conflict expected because the two branches are provider-keyed and
mutually exclusive at runtime.

**`apps/api/routers/ads.py`** — Phase 2 adds two additive response fields to the `push` endpoint;
Phase 3 declares awareness but expects zero edit. If Phase 3's RESEARCH step later finds it does
need a response-shape change here, it must first re-check this registry for Phase 2's landed
state and add fields additively (never restructure the endpoint), then append an update note to
this registry section (not silently edit and move on).

**Resolution owner:** whichever phase's orchestrator loop reaches Step 5 (EXECUTE) SECOND for a
shared file must re-read the current file state (not assume the Phase-1 baseline is still
current) before editing. This is standard practice for any shared-file extension point and is
not a blocker to running Phase 2 and Phase 3 in parallel.

---

## Registry Status Log

| Phase | Status |
|---|---|
| Phase 1 | DONE |
| Phase 2 | DONE — EVL green (14 gates), 3 env-only known-gaps (E3 sandbox smoke, AC7 Playwright legs, AC13 error shape); code-complete, not yet ✅ VERIFIED per plan's own Phase Completion Rules |
| Phase 3 | DONE — EXECUTE green (30 new unit + 3 new integration; full unit lane 574 passed, ads integration 23 passed, zero CRM/csv drift), 1 env-only known-gap (G2/E4 Hybrid Google sandbox smoke); code-complete, not yet ✅ VERIFIED per the plan's own Phase Completion Rules |

Valid status values (written by the orchestrator during execution, per
`process/development-protocols/orchestration.md` §BLOCKED Escalation Path): `BLOCKED-skipped /
DONE / SUPERSEDED / (no field)`.
