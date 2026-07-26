---
name: plan:ad-audiences-phase-2-meta-live
description: "Ad Audiences — Phase 2: Meta live (real OAuth, Custom Audience create/upload, ToS error surfacing, min-size warning)"
date: 25-07-26
metadata:
  node_type: memory
  type: plan
  feature: ads-audiences
  phase: phase-2
---

# Phase 2 — Meta Live

**Program:** ad-audiences
**Umbrella plan:** process/features/ads-audiences/active/ad-audiences_25-07-26/ad-audiences-umbrella_PLAN_25-07-26.md
**Phase status:** 🧪 TESTING (code-complete + EVL-green; not VERIFIED — E3 Hybrid sandbox smoke and
AC7 Playwright UI legs have no recorded evidence yet; see backlog note)
**Report destination:** process/features/ads-audiences/active/ad-audiences_25-07-26/phase-2-meta-live_REPORT_26-07-26.md (written)

**Complexity:** COMPLEX
Complexity: COMPLEX
Date: 25-07-26
Status: TESTING

## Overview

Replace the Phase 1 Meta stub with real Meta Marketing API integration: Limited Access OAuth, Custom Audience create/upload, fire-and-forget status model, ToS-precondition error surfacing, and min-size warning wiring. See process/context/all-context.md for repo conventions and process/context/tests/all-tests.md for the test-runner routing this phase's Exit Gate commands follow.

## Acceptance Criteria

See the ## Verification Evidence table below — each row maps a test gate to the exact SPEC acceptance criterion it proves; this phase's Exit Gate is 'done' only when every AC row in that table is Fully-Automated-green or its declared Hybrid/Agent-Probe evidence is recorded in the phase report.

## Phase Completion Rules

CODE DONE = all Implementation Checklist items checked and automated Exit Gate commands exit 0. TESTING = Hybrid/Agent-Probe evidence being gathered. VERIFIED = validate-contract Gate is PASS (or explicitly-accepted CONDITIONAL) AND every row in Verification Evidence has real recorded evidence (not a placeholder) AND the phase report is written. A phase may not be marked VERIFIED on code completion alone.

---

## Purpose

Replace `services/ads/meta.py`'s Phase-1 mock stub with real Meta Marketing API integration:
Limited Access OAuth (ads_management + business_management scopes), Custom Audience creation
(`POST /act_{id}/customeraudiences`), member upload (`POST /{audience_id}/users`, async), the
fire-and-forget status model (v1 decision — no polling task), ToS-precondition error surfacing
(AC13), and min-size warning wiring (AC7). Covers SPEC ACs 2, 6, 7, 13.

---

## Entry Gate

- Phase 1 exit gate passed: ACs 1,4,5,9,10,11,12 provable in mock mode; `services/ads/` registry
  pattern stable and unchanged in shape
- `services/ads/meta.py`'s Phase-1 stub methods (marked `# PHASE 2:`) exist and are the sole
  edit target for this phase's service-layer work

---

## Blast Radius

- `apps/api/services/ads/meta.py` (edit — replace stub bodies with real logic; file already
  exists from Phase 1, owned by Phase 1 for creation, owned by Phase 2 for the real
  implementation — see blast-radius registry for the exact extension-point declaration)
- `apps/api/services/ads_push.py` (edit — add `fresh_access_token(db, conn)` helper, structurally
  identical to `crm_push.fresh_access_token`, called from `push_segment_to_ads` before
  `create_or_update_audience`; extension point, not a new file — see A3c)
  **Registry gap (found in inner-PVL, 26-07-26):** this file is NOT yet listed as a Phase 2
  extension point in `phase-blast-radius-registry.md`'s Phase 2 section (only Phase-1-creates /
  Phase-3-EEA-extension are declared there today). Per the registry's own declare-before-edit
  rule, execute-agent MUST append a Phase 2 extension-point line for `ads_push.py` to the
  registry BEFORE editing this file in A3c — see Execute-Agent Instruction E3 below. This is a
  coordination/paperwork gap, not a code-feasibility gap, and does not block PLAN→EXECUTE.
- `apps/api/tasks/ads_tasks.py` (edit — add the Celery async member-upload leg for Meta, if the
  synchronous request/response path proves too slow for large segments; extension point, not a
  new file)
- `apps/api/routers/ads.py` (edit — surface AC13's ToS-precondition error shape and AC7's
  min-size warning payload field on the `push` endpoint response)
- `apps/web/src/components/ad-connect-panel.tsx` (edit — render the AC13 error message and AC7
  warning text returned by the push endpoint; no new component)
- Test files: `tests/unit/test_ads_meta.py` (new), `tests/integration/test_ads_meta_live.py`
  (new — mocked-callback integration), `apps/web/e2e/connectors-ads-push-warning.spec.ts` (new
  — AC7 e2e)

**Not touched:** anything in `apps/api/services/ads/google.py`, `apps/api/services/ads/linkedin.py`,
`apps/api/services/ads/base.py`, `apps/api/services/ads/factory.py` (Phase 1-owned, shared —
Phase 2 may only READ these, never edit; if a shared-file change is genuinely required, declare
it explicitly per the blast-radius registry's extension-point rule and flag as a
Potential Blast Radius Conflict). Zero CRM/csv_exporter edits (program-wide hard constraint).

---

## Implementation Checklist

### Step A — Real Meta OAuth

- [x] A1. Docs-fetch (cheap, cost-class `docs-fetch`) to confirm the exact Meta OAuth
      authorization URL shape, scope string format (`ads_management,business_management`), and
      token-exchange endpoint/response shape. Confirm redirect_uri registration requirements.
      **Also confirm the CURRENT Meta Graph API version.** Do NOT copy the `v19.0` constant
      already used in `apps/api/services/platforms/facebook.py` / `instagram.py` (both files DO
      exist in this repo, confirmed live) verbatim — that version was pinned circa early 2024 and
      sunsets 21-05-2026, almost certainly already retired by execution time. Docs-confirmed
      **current version: v25.0** (Feb 2026 Graph API release). Pin `v25.0` as a single named
      module-level constant in `meta.py` (never an inline literal repeated across call sites) —
      re-confirm via a fresh docs-fetch at EXECUTE time in case a newer version has since
      released, and add a one-line upgrade note (e.g. `# Meta deprecates Graph API versions ~2yr
      after release — recheck before <today + ~2yr>`) so a future maintainer knows to re-verify
      before it goes stale again.
- [x] A2. Implement `MetaAdsProvider.get_oauth_url(state)` for real (non-mock) mode: build the
      `https://www.facebook.com/v{version}/dialog/oauth` URL (using the A1-confirmed version
      constant) with `client_id`, `redirect_uri`, `state` (from `oauth_state.py`, reused
      verbatim), `scope`.
- [x] A3. Implement `MetaAdsProvider.exchange_code(code)` for real mode as a TWO-STEP exchange
      (INNOVATE-decided, option a — token strategy locked): (1) `GET /oauth/access_token` (or
      `POST`, per confirmed docs) to exchange the auth `code` for a SHORT-LIVED token
      (1-2h expiry); (2) immediately follow with the long-lived exchange call
      (`GET /oauth/access_token?grant_type=fb_exchange_token&fb_exchange_token={short_lived}`)
      to obtain the LONG-LIVED token (~60d expiry). Store the LONG-LIVED token's expiry in
      `token_expires_at` — never the short-lived 1-2h value. Extract ad-account/business info via
      a follow-up `/me/adaccounts` call. Encrypt and store via `services/encryption.py` (imported,
      not modified).
      **Router note (corrects a plan-drafting ambiguity found in VALIDATE):** `routers/ads.py`'s
      OAuth callback handler is provider-AGNOSTIC — it mirrors `routers/crm.py`'s
      `oauth_callback`, which resolves the connector polymorphically via
      `get_provider(provider)` and calls `.exchange_code(...)` on it; it does **not** branch on
      `if provider == "meta":` inside the router. Do NOT add provider-specific branching logic
      to the callback handler — it should need ZERO structural changes from what Phase 1 built.
      The mock-vs-real branch lives entirely inside `MetaAdsProvider.exchange_code()` itself (see
      A4), matching every `services/crm/*.py` connector's own `if settings.mock_external_apis:`
      check. The callback handler is NOT a declared Phase 2 extension point in the blast-radius
      registry (only the `push` endpoint's additive fields are — see C2/D2 below); if RESEARCH
      later finds the callback handler genuinely needs a structural change, stop and update the
      registry first rather than silently expanding scope.
- [x] A3b. Implement `MetaAdsProvider.refresh_tokens(current_access_token) -> AdOAuthTokens`
      (INNOVATE-decided, ABC parity with the crm pattern): re-invokes the SAME
      `fb_exchange_token` call from A3, using the caller-supplied still-valid stored access token
      as input (Meta has no separate refresh-token secret — the long-lived token itself is the
      refresh input). Docstring MUST state the parameter is the current (not-yet-expired) access
      token, not a refresh secret, to avoid confusion with OAuth providers that use a distinct
      refresh token.
      **ABC-scope note (found in inner-PVL, 26-07-26):** `refresh_tokens` is added ONLY as a
      concrete method on `MetaAdsProvider` — it is NOT added to the shared `AdsProvider` ABC in
      `services/ads/base.py`, because that file is Phase-2 read-only/hard-forbidden per the
      blast-radius registry. This is an intentional divergence from the CRM donor pattern, where
      `CRMConnector.refresh_tokens` is a concrete ABC-level default (raises `NotImplementedError`)
      so every connector inherits a safe fallback — `AdsProvider` has no such default today, and
      Phase 2 cannot add one. See A3c for the caller-side guard this asymmetry requires.
- [x] A3c. Add `fresh_access_token(db, conn)` helper in `apps/api/services/ads_push.py`,
      structurally identical to `crm_push.fresh_access_token`: check `token_expires_at` against
      now, call `provider.refresh_tokens(current_token)` when near/past expiry, re-encrypt via
      `services/encryption.py`, update `token_expires_at` on the connection row. Call this helper
      in `push_segment_to_ads` immediately BEFORE `create_or_update_audience` (B1). On refresh
      failure: set `conn.status="error"` + `last_error` (existing pattern — the panel's Reconnect
      affordance already surfaces this; no new UI needed).
      **Safe-guard required (found in inner-PVL, 26-07-26):** because `refresh_tokens` exists
      only on `MetaAdsProvider` (see A3b) and NOT on the shared `AdsProvider` ABC, an unguarded
      generic call to `provider_impl.refresh_tokens(...)` would raise `AttributeError` (not a
      graceful `NotImplementedError`) for Google/LinkedIn connections — `push_segment_to_ads` is
      the SAME shared, provider-agnostic function all three providers call through. Guard the
      call: `refresher = getattr(provider_impl, "refresh_tokens", None)`; if `refresher` is
      `None`, skip the refresh attempt and proceed straight to the push call unchanged (Google/
      LinkedIn token lifecycle isn't managed by this phase); if present, await it. Do not let an
      unguarded call crash `push_segment_to_ads` for a non-Meta provider. Track the deeper fix
      (promoting a shared ABC-level default matching the CRM pattern) as a backlog item for
      whichever phase next touches `services/ads/base.py` — out of Phase 2's edit scope.
- [x] A4. Preserve the Phase-1 mock branch unchanged — `if settings.mock_external_apis:` must
      still short-circuit to the deterministic fake path for every method touched in this phase.

### Step B — Custom Audience create + upload

- [x] B1. Implement `MetaAdsProvider.create_or_update_audience(connection, link, hashed_contacts)`:
      if `link` is `None` (no `AdAudienceLink` row exists yet for this connection/segment pair —
      first push; `_get_link` returns `None` for the whole row since `platform_audience_id` is
      non-nullable and cannot itself be `None` on an existing row), `POST
      /act_{ad_account_id}/customeraudiences` with `subtype=CUSTOM`, `customer_file_source` set
      per Meta's documented enum, capture the returned audience id. If a `link` row already exists
      (repeat push — AC6), skip creation and go straight to member upload against the existing
      `link.platform_audience_id`.
- [x] B1b. Docs-fetch (cheap, cost-class `docs-fetch`) against Meta's PRIMARY Custom Audiences
      API docs page to resolve the exact schema-key naming Meta expects in the `POST
      /{audience_id}/users` payload's `schema` array — `EMAIL` vs `EMAIL_SHA256` (secondary/
      third-party sources conflict on this). B2 is blocked on this one-line answer; do not guess.
      **ANSWER (EXECUTE, 26-07-26):** for a SINGLE-key hashed-email upload the value is the
      string `"EMAIL_SHA256"` (the short `"EMAIL"` form is only valid inside the MULTI-key array
      form, e.g. `["EMAIL","LN","FN","ZIP"]`, where `is_raw` semantics differ). Beam pushes
      single-key hashed email, so `schema: "EMAIL_SHA256"` is correct. Source (primary Meta
      docs, `POST /{custom_audience_id}/users` Parameters table):
      https://developers.facebook.com/docs/marketing-api/reference/custom-audience/users/ —
      verbatim: "`schema` _string_ `EMAIL_SHA256`, `PHONE_SHA256`, `MOBILE_ADVERTISER_ID`. One
      can also pass an array of multiple keys for multi-key match… The multi-key array is of the
      form `["EMAIL", "LN", "FN", "ZIP"]`". The same page's live example request URL carries
      `&version=v25.0`, independently re-confirming A1's v25.0 pin at EXECUTE time.
      (Fetch note: developers.facebook.com returns HTTP 400 to plain curl; retrieved via the
      `r.jina.ai` text-extraction proxy of that exact primary URL — same primary document, not a
      third-party summary.)
- [x] B2. Implement the member-upload leg: `POST /{audience_id}/users` with the SHA256-hashed
      `hashed_contacts` (already hashed by `ads_push.py` in Phase 1 via `_sha256` — this method
      never re-hashes, never receives plaintext), using the schema key confirmed in B1b. This call
      is asynchronous on Meta's side.
- [x] B3. **Fire-and-forget status model (locked INNOVATE decision, v1):** treat Meta's sync
      acknowledgment (the upload call returning 200 with a `num_received`/`num_invalid_entries`
      style body) as the terminal result for this push. Do NOT add a polling task. Reconcile
      opportunistically: the NEXT time the user views this connection or pushes again, if Meta's
      API exposes an approximate-audience-size field on a lightweight `GET
      /{audience_id}` call, surface it — but this is best-effort, not a guarantee, and must be
      explicitly labeled in the UI (Step D) as "Beam-side matched/queued", never
      "platform-confirmed". Document this as a named known-limitation in the phase report.
- [x] B4. Wire `push_segment_to_ads`'s async threshold branch (Phase-1-built,
      `ads_async_push_threshold`) so Meta pushes above the threshold enqueue via
      `ads_tasks.push_segment_to_ads_task` — no new Celery task needed, Phase 1's task already
      calls into `ads_push.py` which now has real Meta logic.

### Step C — AC13: ToS-precondition error surfacing

- [x] C1. Docs-fetch + best-effort research on the actual Meta error response shape for an
      ad-account that has not accepted the Custom Audience Terms of Service. **Confirmed this
      supplement pass:** the error surface is an HTTP 400 with message "Custom Audience Terms
      not yet accepted"; the resolution URL to surface to the user is
      `https://business.facebook.com/ads/manage/customaudiences/tos/?{ACCOUNT_ID}`. The exact
      JSON error `code`/`subcode` fields remain unconfirmed (docs don't specify) — this stays
      Agent-Probe tier per SPEC's own declared strategy for AC13; do not fabricate a fixture for
      the code/subcode.
      Escalate `VC-FEASIBILITY-PROBE-NEEDED: [Meta Custom Audience ToS-acceptance error shape] —
      cost-class: needs-live-provider` ONLY if a sandbox/live probe is genuinely required to make
      a design decision (e.g. whether the error is distinguishable from other 400s) — otherwise
      proceed with best-effort mapping and record the gap.
- [x] C2. Implement a specific, actionable error message path in `MetaAdsProvider` (and
      surfaced through `routers/ads.py`'s push endpoint) for any Graph API error response that
      matches the ToS-precondition signature identified in C1 (HTTP 400 + "Custom Audience Terms
      not yet accepted"), distinct from a generic failure message. The surfaced error copy MUST
      include the confirmed resolution URL
      (`https://business.facebook.com/ads/manage/customaudiences/tos/?{ACCOUNT_ID}`, with the
      real ad account id interpolated) so the user has an actionable next step, not just an error
      message. The exact JSON error code/subcode remains unconfirmed — leave a
      `# TODO Agent-Probe: confirm real error code/subcode against live sandbox` marker for that
      part only.

### Step D — AC7: min-size warning wiring

- [x] D1. Confirm Meta's practical minimum audience size threshold via the SPEC's already-
      researched figure (~1000 practical, 100 technical minimum) — **confirmed this supplement
      pass: MIN_AUDIENCE_SIZE=1000 constant already exists in `apps/api/services/ads_push.py`
      (line 36) and stands as-is; no change needed.** Warning copy should mention BOTH numbers
      (technical minimum 100, practical recommended ~1000) so the user understands the push will
      still succeed below 1000 but Meta's matching/targeting quality degrades.
- [x] D2. **Real gap confirmed this supplement pass:** `PushSegmentOutcome`/`PushAdSegmentResult`
      currently carry only a free-text `warning` string — the structured `below_minimum: bool` /
      `minimum_threshold: int` fields do NOT exist yet and must be added. Wire the push endpoint's
      response to include these two additive fields when the post-safety-filter contact count is
      below `MIN_AUDIENCE_SIZE`. **Frontend gap confirmed:** `ad-connect-panel.tsx` currently
      HARDCODES the "~1,000 matched contacts" copy as a static string — this must become dynamic,
      reading `minimum_threshold` from the response instead of a hardcoded literal, and mentioning
      both the technical (100) and practical (1000) numbers per D1.
      **Correction (found in inner-PVL, 26-07-26):** the response fields above are only known
      AFTER the push executes server-side — they cannot power a pre-push warning inside the
      confirm dialog on their own (the earlier wording "the confirm dialog renders the warning"
      was imprecise). Use these fields to render the EXACT post-push warning message, replacing
      today's hardcoded panel copy in the existing post-push result banner (the `setMsg(...)`
      call in `handlePush`, which already appends `r.warning` — confirmed at
      `ad-connect-panel.tsx`). The confirm dialog itself does not block the push either way
      (SPEC: "warned... not blocked"). See D2b for the separate PRE-push warning SPEC AC7
      literally requires.
- [x] D2b. **New pre-push warning gate (found in inner-PVL, 26-07-26 — SPEC AC7 requires a
      warning shown BEFORE the user confirms, with the explicit option to still confirm or
      cancel; D2 alone only wires a POST-push message and does not satisfy this).** `Segment`
      objects already carry a `visitor_count` field (`apps/api/schemas/segments.py`) that reaches
      the frontend via `listSegments` and is passed into `AdConnectPanel` as the `segments` prop —
      reuse this as an APPROXIMATE pre-safety-filter estimate (explicitly NOT the exact
      hashed-contact count D2's response fields report, since `visitor_count` predates the
      do-not-email/agent-derived/do-not-sell safety filter chain). In the push confirm `Dialog`,
      when the selected segment's `visitor_count` is below the existing frontend threshold
      (today a hardcoded `1,000` literal — kept in sync with backend `MIN_AUDIENCE_SIZE`; no new
      config endpoint needed for v1), render an inline warning in the dialog body stating the
      segment looks small and the push may still proceed if confirmed. Label this estimate as
      approximate, distinct from D2's exact post-push number. This is additive to the existing
      static dialog copy (`ad-connect-panel.tsx` lines ~262-274), not a replacement of the whole
      dialog, and satisfies SPEC's literal "warning shown before push... may still confirm or
      cancel" flow.

### Step E — Test coverage

- [x] E1. `tests/unit/test_ads_meta.py`: unit tests for `MetaAdsProvider` methods in mock mode
      (Fully-Automated) — OAuth URL shape, exchange response parsing, audience create/update
      branch logic (first push vs repeat push via `link.platform_audience_id`), AND (added in
      inner-PVL) a `fresh_access_token` guard test asserting a provider without `refresh_tokens`
      (e.g. a stubbed Google/LinkedIn double) is skipped gracefully — no `AttributeError` raised
      — per A3c's safe-guard.
- [x] E2. `tests/integration/test_ads_meta_live.py`: integration test against a MOCKED Meta OAuth
      callback (Fully-Automated, same pattern as the existing CRM OAuth callback test
      `test_hubspot_oauth_roundtrip` in `tests/integration/test_crm_push.py`) — full connect →
      push → repeat-push flow, asserting `platform_audience_id` reuse (AC6).
- [ ] E3. Hybrid manual smoke against Meta's real sandbox app (documented procedure in the phase
      report, run once before this phase can be marked VERIFIED — not part of the automated
      suite; requires a real Meta developer app + test Business Manager, which is a one-time
      manual setup step outside this plan's scope to provision).
- [x] E4. `apps/web/e2e/connectors-ads-push-warning.spec.ts`: Playwright e2e (Fully-Automated) —
      **(corrected in inner-PVL, 26-07-26, to cover both legs of AC7):** (a) mock a small segment
      (`visitor_count` below the 1,000 threshold) and assert the D2b PRE-push approximate warning
      renders inside the confirm dialog BEFORE the push button is clicked, and that the push
      button remains clickable/not blocked; (b) complete the push and assert the POST-push result
      message contains the D2 exact `below_minimum`/`minimum_threshold`-driven copy.
- [x] E5. Agent-Probe: manually exercise the AC13 error path against whatever real-or-simulated
      error shape was confirmed in Step C, record judgment on whether the surfaced message is
      "specific and actionable" per the SPEC wording.

---

## Concurrent-Drift Note (supplement, 26-07-26)

The `capacity-hardening` program (`process/general-plans/active/capacity-hardening_25-07-26/`,
uncommitted at supplement time) is editing `apps/api/services/ads_push.py` and
`apps/api/config.py` additively (`celery_worker_enabled` gating). No conflict with this phase's
planned edits today. **Before finalizing E1/E2 (timeout+retry wiring) at EXECUTE time, re-run
`git diff` on `ads_push.py` to check for merge surprises if capacity-hardening lands mid-phase.**
(Re-confirmed live in inner-PVL, 26-07-26: `git diff --stat main -- apps/api/services/ads_push.py
apps/api/config.py` shows the capacity-hardening changes already present in the working tree —
additive `celery_worker_enabled`/async-threshold truth-table logic, no structural conflict with
this phase's planned `fresh_access_token` addition.)

## Operator Env-Prereq Checklist (pre-live-smoke, from RESEARCH)

Before E3's Hybrid sandbox smoke — and before any production enable — the following must be true
in the target environment (none of these are available in this sandbox; all are one-time manual
operator setup outside this plan's scope):

- [ ] Meta app is in LIVE mode (not development mode) — `meta_ads_client_id`/`meta_ads_client_secret` set
- [ ] A verified Business Manager exists and is linked to the app
- [ ] The redirect URI is registered in the Meta app config and matches `meta_ads_redirect_uri`
      exactly (as-built default is `localhost` — must be updated to the real prod URL before
      any non-local smoke)
- [ ] `ads_management` + `business_management` scopes are approved for this app (no App Review
      needed for own-Business-Manager use per Limited Access tier)
- [ ] Custom Audience ToS has been accepted for the specific ad account being tested, BEFORE the
      first push attempt (see AC13/Step C — this is the precondition that error path guards)
- [ ] `ad_audiences_enabled` stays OFF until this phase is fully VERIFIED (umbrella hard stop —
      do not flip in any real environment before the phase gate passes)

## Exit Gate

```bash
# Zero CRM/csv_exporter drift (program-wide constraint, re-checked every phase)
git diff --stat main -- apps/api/models/crm_connection.py apps/api/routers/crm.py \
  apps/api/services/crm.py apps/api/services/crm/ apps/api/services/crm_push.py \
  apps/api/services/crm_rate_limiter.py apps/api/tasks/crm_tasks.py apps/api/services/csv_exporter.py
# Expected: empty output

# Backend (VALIDATE-corrected: use the venv interpreter per process/context/tests/all-tests.md —
# bare `pytest` is not guaranteed on PATH, and CI does not source .venv/bin/activate)
.venv/bin/python -m pytest tests/unit -k ads_meta -m unit -q
.venv/bin/python -m pytest tests/integration -k ads_meta -m integration -q

# Frontend e2e (VALIDATE-corrected: this repo has no pnpm workspace at the root — apps/web is a
# standalone npm package, confirmed via absence of any pnpm-lock.yaml/root package.json and the
# `test:e2e` script in apps/web/package.json using `npx playwright test`)
cd apps/web && npx playwright test connectors-ads-push-warning
# Expected: all green
```

- ACs 2, 6, 7 pass at Fully-Automated tier; Hybrid sandbox smoke (E3) recorded in phase report
- AC13 Agent-Probe judgment recorded in phase report
- Phase report written to report destination above

---

## Blockers That Would Justify BLOCKED Status

- Meta developer app / test Business Manager for the Hybrid sandbox smoke (E3) is not available
  in this environment — record as a known-gap, do not block the whole phase; automated tiers
  (E1, E2, E4) can still reach green and the phase can proceed to CONDITIONAL/PASS with E3
  documented as pending manual execution before first production enable
- C1's docs-fetch is genuinely inconclusive AND a live-provider probe is refused/unavailable —
  proceed with best-effort mapping (per C2) rather than blocking; AC13 stays Agent-Probe as SPEC
  already anticipates

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — research-agent: Phase 1 report read in full; test context loaded; Meta
      docs-fetch for OAuth shape (two-step token exchange), EMAIL/EMAIL_SHA256 schema key, ToS
      error shape, and min-size threshold — complete (26-07-26)
- [x] 2. INNOVATE — innovate-agent: token-refresh strategy (option a, two-step exchange +
      `refresh_tokens`) decided; Decision Summary folded into the plan-supplement — complete
      (26-07-26)
- [x] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated with docs-fetch + INNOVATE
      findings; `## Inner Loop Refresh Note` added, triggering this inner-PVL re-run — complete
      (26-07-26)
- [x] 4. PVL — vc-validate-agent: inner-PVL re-run complete (26-07-26); validate-contract
      rewritten per `.claude/skills/vc-validate-findings/references/example-validate-output.md`,
      superseding the 25-07-26 outer-pvl contract (retained below for audit history). Gate: PASS.
- [x] 5. EXECUTE — all checklist items done except E3 (Hybrid Meta sandbox smoke — no Meta
      developer app in this environment; carried as a documented known-gap); per-section test
      gates run and green — complete (26-07-26)
- [x] 6. EVL — independent vc-tester confirmation run: 14 gates green (unit 539 + ads-scope 48,
      guardrail agent-origin 18, 5 integration files fresh-schema, frontend typecheck, frozen-file
      drift, no-raw-token-logging grep, no-live-Meta-calls grep, alembic single head
      `d5b1f7c3a908`); no regression against Phase 1 surfaces; known-gaps unchanged (E3 sandbox
      smoke, AC7 Playwright legs, AC13 error shape, T1 conftest not yet landed) — `results.tsv`
      iteration 5, HALTED_SUCCESS — complete (26-07-26)
- [x] 7. UPDATE PROCESS — phase report written, registry updated, umbrella state updated, backlog
      note extended, context updated — complete (26-07-26)

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate Contract`
reads "(placeholder — vc-validate-agent writes this section before EXECUTE)", orchestrator must
spawn vc-validate-agent first. A partial contract missing Plan updates applied / Execute-agent
instructions / Test gates sections is treated as a placeholder.

---

## Touchpoints

`apps/api/services/ads/meta.py` (edit, Phase-2-owned real logic), `apps/api/services/ads_push.py`
(edit — extension point, registry declaration pending, see Execute-Agent Instruction E3),
`apps/api/tasks/ads_tasks.py` (edit — extension point only), `apps/api/routers/ads.py` (edit —
extension point only), frontend `ad-connect-panel.tsx` (edit — extension point only), plus new
test files listed in Blast Radius.

---

## Public Contracts

- `POST /api/v1/ads/{site_id}/connections/meta/push` response gains two additive fields:
  `below_minimum: bool`, `minimum_threshold: int` — no existing field removed or renamed.
- No change to any CRM or CSV export public contract.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Integration test: mocked Meta OAuth callback completes, connection shows status=connected | Fully-Automated | AC2 (automated leg) |
| Hybrid manual smoke: real Meta sandbox app connect flow | Hybrid | AC2 (live leg, before first production enable) |
| Integration test: push twice, `platform_audience_id` reused on second call | Fully-Automated | AC6 |
| Playwright e2e: small-segment approximate warning renders in confirm dialog before push is clicked, AND exact post-push warning copy renders after | Fully-Automated | AC7 (both pre-push and post-push legs) |
| Agent-Probe: ToS-precondition error message judged specific/actionable | Agent-Probe | AC13 |
| Unit test: `fresh_access_token` skips gracefully (no crash) for a provider without `refresh_tokens` | Fully-Automated | Structural safety (A3c guard) |
| `git diff --stat` on CRM/csv_exporter files empty | Fully-Automated | Hard safety constraint |

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-2-meta-live_PLAN_25-07-26.md`
- Last completed step: PVL (inner-PVL re-run, 26-07-26) — Gate: PASS
- Validate-contract status: PASS (inner-pvl: phase-2, 26-07-26) — supersedes the 25-07-26
  outer-pvl PASS contract; see `## Validate Contract` below
- Next step: This phase cannot EXECUTE until Phase 1's exit gate passes (registry dependency —
  Phase 1 registry status is DONE, so this is satisfied). Spawn vc-execute-agent for Step 5
  EXECUTE next. Before A3c edits `ads_push.py`, execute-agent must first append the Phase 2
  extension-point declaration for that file to `phase-blast-radius-registry.md` (Execute-Agent
  Instruction E3).

---

## Test Infra Improvement Notes

- Both this phase's Exit Gate and Phase 1's Exit Gate originally specified
  `pnpm --filter web exec playwright test ...` — this repo has no pnpm workspace (no root
  `package.json`, no `pnpm-lock.yaml`; `apps/web` is a standalone npm package). Corrected here to
  `cd apps/web && npx playwright test ...`. Phase 1's plan carries the same bug and should be
  corrected the next time its validate-contract is written (out of this phase's edit scope).

---

## Validate Contract

Status: PASS
Date: 26-07-26
date: 2026-07-26
generated-by: inner-pvl: phase-2
supersedes: 25-07-26 (outer-pvl) — inner PVL has current evidence (RESEARCH + INNOVATE +
PLAN-SUPPLEMENT ran since the outer contract was written; this re-run confirms the supplemented
plan and closes 3 additional findings the outer pass did not catch)

Parallel strategy: sequential (single-agent direct analysis this pass)
Rationale: 7-signal score 4/7 (S1 multi-package, S2 auth/API surface, S6 high-risk class, S7 5+
blast-radius files) → HIGH tier nominally recommends parallel-subagents/agent-team fan-out; this
inner-PVL pass ran as a single sequential agent (no Agent-tool fan-out available in this session)
but achieved equivalent depth via direct source reads of every changed area (`services/ads/meta.py`,
`services/ads/base.py`, `services/ads/google.py`, `services/ads/linkedin.py`, `services/ads_push.py`,
`services/crm/base.py` + `crm_push.py` as donor-parity check, `models/ad_connection.py`,
`schemas/ads.py`, `routers/ads.py`, `ad-connect-panel.tsx`, `ad-audiences_SPEC_25-07-26.md`,
the blast-radius registry, and `results.tsv`), live `git diff --stat` checks, and the structural
plan-artifact validator. This pass targeted the 7 supplement-changed areas the caller flagged
plus a fresh Layer-1 sweep across the whole plan for contradictions.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC2 | Meta OAuth connect completes, connection shows status=connected (mocked callback leg) | Fully-Automated | `.venv/bin/python -m pytest tests/integration -k ads_meta_live -m integration -q` (mirrors `test_hubspot_oauth_roundtrip`) | A |
| AC2 | Meta OAuth connect completes against Meta's real sandbox app | Hybrid | Manual smoke procedure recorded in phase report; precondition: real Meta developer app + test Business Manager (not available in this environment) | D |
| AC6 | Re-pushing a segment reuses `platform_audience_id` instead of creating a duplicate | Fully-Automated | `.venv/bin/python -m pytest tests/integration -k ads_meta_live -m integration -q` (push twice, assert `AdAudienceLink.platform_audience_id` reused) | A |
| AC7 (pre-push leg) | Small-segment approximate warning (from `visitor_count`) renders in confirm dialog before push is clicked; push not blocked | Fully-Automated | `cd apps/web && npx playwright test connectors-ads-push-warning` (D2b leg) | B |
| AC7 (post-push leg) | Exact `below_minimum`/`minimum_threshold` copy renders in the post-push result message | Fully-Automated | `cd apps/web && npx playwright test connectors-ads-push-warning` (D2 leg) | A |
| AC13 | ToS-precondition push failure surfaces a specific, actionable error (not generic/silent) | Agent-Probe | Manual scenario: exercise the confirmed-or-best-effort error path from Step C; judge message specificity per SPEC wording; record verdict in phase report | A (best-effort mapping proven now; upgrade to Fully-Automated once a real fixture is confirmed — non-blocking backlog item, tracked via the `# TODO Agent-Probe:` marker at C2) |
| Structural safety | `fresh_access_token` does not crash with `AttributeError` when the provider has no `refresh_tokens` method (Google/LinkedIn today) | Fully-Automated | `.venv/bin/python -m pytest tests/unit -k ads_meta -m unit -q` (new guard test, E1) | B |
| Hard safety constraint | Zero CRM/csv_exporter file drift | Fully-Automated | `git diff --stat main -- apps/api/models/crm_connection.py apps/api/routers/crm.py apps/api/services/crm.py apps/api/services/crm/ apps/api/services/crm_push.py apps/api/services/crm_rate_limiter.py apps/api/tasks/crm_tasks.py apps/api/services/csv_exporter.py` (expect empty) | A |
| Unit coverage | `MetaAdsProvider` method-level logic in mock mode (OAuth URL shape, exchange parsing, create-vs-reuse branch) | Fully-Automated | `.venv/bin/python -m pytest tests/unit -k ads_meta -m unit -q` | A |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: `strategy:` carries only Fully-Automated / Hybrid / Agent-Probe. No row uses
Known-Gap as a strategy — the two deferred items (E3 Hybrid smoke, AC13 exact code/subcode) are
carried as Hybrid/Agent-Probe with a documented residual, not silently passed on a Known-Gap.

Legacy line form (retained so existing validate-contract consumers still parse):
- Meta OAuth + Custom Audience push (AC2/AC6/AC7): Fully-automated: `.venv/bin/python -m pytest tests/integration -k ads_meta_live -m integration -q` | hybrid: manual sandbox smoke, precondition: real Meta dev app + test Business Manager | agent-probe: AC13 ToS-error judgment | known-gap: none blocking
- Hard safety constraint: Fully-automated: `git diff --stat` on the 7 CRM/csv_exporter files, expect empty

Dimension findings:
- Infra fit: PASS — registry/factory pattern (Phase-1-owned) is respected; no new
  ports/containers/runtime surfaces introduced. One coordination gap found and closed
  (see Section A below): the new `ads_push.py` edit target isn't yet a declared registry
  extension point — resolved via Execute-Agent Instruction E3, not a design/feasibility problem.
- Test coverage: CONCERN → resolved via plan-text fixes this cycle (see Plan updates applied
  P4-P6) — E4's original wording ("warning renders in the confirm dialog before push") didn't
  match the as-built panel, which only shows a warning in the POST-push result toast; corrected
  to a two-leg spec (D2b pre-push approximate + D2 post-push exact) matching SPEC AC7's literal
  flow diagram ("warning shown before push... may still confirm or cancel"). Added a new unit
  test criterion for the A3c safe-guard (fresh_access_token must not crash for non-Meta
  providers).
- Breaking changes: PASS — `below_minimum`/`minimum_threshold` remain additive-only fields on
  the push endpoint response; zero existing route removed/renamed; CRM/csv_exporter non-edit is
  a hard automated gate, not advisory. Re-confirmed live via `git diff --stat` — no CRM/
  csv_exporter drift.
- Security surface: PASS — E1/E2 execute-agent instructions from the outer-pvl pass (no raw
  token/code logging; timeout+retry on every new Meta httpx call) remain valid and unaffected by
  the supplement; re-confirmed no new logging or network call site was introduced by the
  supplement text that would bypass them.
- Section A feasibility (Real Meta OAuth): CONCERN → resolved via plan-text fixes this cycle
  (P4-P5, see Plan updates applied): (1) confirmed the `AdsProvider` ABC in `services/ads/base.py`
  does NOT declare `refresh_tokens` (abstract or concrete) — unlike `CRMConnector.refresh_tokens`,
  which IS a concrete ABC-level default in `services/crm/base.py:108` that raises
  `NotImplementedError`. A3b as originally worded ("ABC parity with the crm pattern") implied
  Google/LinkedIn would inherit a safe fallback; they do not, because Phase 2 cannot edit
  `services/ads/base.py` (Phase-2 read-only/hard-forbidden per the registry). Confirmed live:
  `GoogleAdsProvider`/`LinkedInAdsProvider` (both read) define no `refresh_tokens` method. (2)
  Confirmed `fresh_access_token` (A3c) is called from `push_segment_to_ads`, a SHARED
  provider-agnostic function serving all three providers — an unguarded generic
  `provider.refresh_tokens(...)` call would raise `AttributeError` for Google/LinkedIn, not the
  graceful `NotImplementedError` the CRM donor pattern gets from its ABC default. Both closed via
  plan-text fixes: A3b now documents the ABC-scope divergence explicitly; A3c now requires a
  `getattr(provider_impl, "refresh_tokens", None)` guard before calling. (3) Confirmed the
  `ads_push.py` edit this phase introduces is not yet a declared Phase 2 extension point in
  `phase-blast-radius-registry.md` — closed via Execute-Agent Instruction E3 (registry append
  required before A3c starts editing the file), since this validate-agent cannot itself edit the
  registry file (out of its single-file edit scope for this pass).
- Section B feasibility (Custom Audience create/upload): PASS — unchanged from the outer pass;
  re-confirmed B1's `link is None` wording matches `_get_link`'s actual return semantics
  (`ads_push.py`'s `_get_link` returns `None` when no `AdAudienceLink` row exists, confirmed live)
  and B1b's docs-fetch correctly gates B2 as a blocking micro-gate with `docs-fetch` cost-class.
- Section C feasibility (AC13 ToS error): PASS — unchanged from the outer pass; the confirmed
  HTTP 400 + message text + resolution URL are internally consistent between C1 and C2; JSON
  code/subcode correctly stays Agent-Probe per SPEC's own declared strategy.
- Section D feasibility (AC7 min-size warning): CONCERN → resolved via plan-text fix this cycle
  (P6, new item D2b): confirmed SPEC's own flow diagram literally requires "warning shown before
  push... user may still confirm or cancel" (`ad-audiences_SPEC_25-07-26.md` lines 184-188 and
  the ASCII flow around line 112-114), but D2 as drafted only wires the push endpoint's RESPONSE
  fields, which are only known AFTER the push already executed server-side — nothing is left to
  "cancel" at that point, and the as-built `ad-connect-panel.tsx` confirm dialog has no pre-push
  size check today (confirmed live: the dialog's description text at lines ~262-274 is a static,
  segment-size-agnostic string; the only warning render site is the post-push `setMsg(...)` call
  in `handlePush`, which appends `r.warning`). Confirmed a cheap, in-scope fix exists: `Segment`
  already carries `visitor_count` (`apps/api/schemas/segments.py:16`), reaching the frontend via
  `listSegments` and already passed into `AdConnectPanel` as the `segments` prop — added D2b to
  wire an approximate pre-push warning from this existing field, distinct from D2's exact
  post-push number, satisfying SPEC's literal flow without a new backend endpoint.
- Section E feasibility (Test coverage / Exit Gate): CONCERN → resolved via plan-text fix (see
  Test coverage dimension above and D2b/E4 corrections). E1-E3, E5 remain correctly tiered and
  mechanically feasible; E1 gains one new guard-test criterion (A3c); E4 is corrected to a
  two-leg spec matching the corrected D2/D2b design.

Plan updates applied (this inner-PVL cycle, 26-07-26):
| # | What changed | Where | Why |
|---|---|---|---|
| P4 | Added ABC-scope note: `refresh_tokens` lives only on `MetaAdsProvider`, not the shared `AdsProvider` ABC (Phase-2 cannot edit `services/ads/base.py`) | Step A, item A3b | Confirmed live: `AdsProvider` ABC declares no `refresh_tokens` method (abstract or concrete), unlike the CRM donor's `CRMConnector.refresh_tokens` concrete default; A3b's original "ABC parity" wording overstated what Phase 2 can actually deliver |
| P5 | Added safe-guard requirement: `fresh_access_token` must `getattr(..., "refresh_tokens", None)`-guard before calling, skipping gracefully for providers without the method | Step A, item A3c | Confirmed `fresh_access_token` is called from the shared, provider-agnostic `push_segment_to_ads` — an unguarded call would raise `AttributeError` for Google/LinkedIn connections, not a graceful `NotImplementedError` |
| P6 | Corrected D2's "confirm dialog renders the warning" claim to describe a POST-push message only; added new item D2b wiring a PRE-push approximate warning from the already-available `Segment.visitor_count` field; corrected E4's Playwright scenario to a two-leg (pre-push + post-push) spec; updated the AC7 Verification Evidence row and added a split AC7 test-gate row | Step D (D2, new D2b), Step E (E4), Verification Evidence, Test gates table | Confirmed SPEC AC7 literally requires a warning shown BEFORE the push with a cancel option; D2 alone only wires a post-push response field, which cannot satisfy a pre-push/cancelable flow since the push has already executed by the time the response arrives |
| P7 | Added a registry-gap note to the Blast Radius section's `ads_push.py` bullet and a new Execute-Agent Instruction (E3) requiring the registry extension-point declaration before A3c edits the file | Blast Radius, Execute-agent instructions | Confirmed `phase-blast-radius-registry.md`'s Phase 2 section does not list `ads_push.py` as a declared extension point, though the phase plan's Blast Radius section (added in the prior supplement) does edit it — a coordination gap between the two documents that this validate-agent cannot close itself (registry file is out of its single-file edit scope) |

Execute-agent instructions:
| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Never log raw `access_token`, `refresh_token`, or the OAuth `code` param in any structlog call added in this phase — log only outcome/status/provider/site_id, matching the repo-wide "never log PII/secrets" convention already applied to every other external integration | Any structlog call added inside `MetaAdsProvider` or the callback handler's new logging (if any) |
| E2 | Every new httpx call to Meta's Graph API (A2/A3/B1/B2) must use an explicit timeout and retry/backoff wrapper, matching `apps/api/services/crm/base.py`'s `HTTP_TIMEOUT=10.0` + `_http_retry` pattern (reuse `services/ads/base.py` if Phase 1 already centralized an equivalent there; otherwise replicate the pattern locally in `meta.py`) | Every new `httpx.AsyncClient` call site added in Step A/B |
| E3 | Before making ANY edit to `apps/api/services/ads_push.py` (A3c), append a Phase 2 extension-point declaration line to `phase-blast-radius-registry.md`'s `## Phase 2 — Meta Live` section (append-only, matching the format already used for Phase 3's `ads_push.py` EEA-branch extension point) — do not silently edit the shared file without first registering the claim | Before starting A3c |

Open gaps:
- E3 Hybrid Meta sandbox smoke requires a real Meta developer app + test Business Manager — not
  available in this environment; deferred to before-first-production-enable, matching the
  program's `needs-live-provider` double-opt-in policy. Non-blocking known-gap (unchanged from
  outer-pvl pass).
- AC13's real Meta ToS-acceptance error shape remains unconfirmed pending either a successful
  docs-fetch or an explicitly-opted-in live-provider probe; Agent-Probe/best-effort mapping
  proceeds now per SPEC's own declared strategy. Non-blocking known-gap; upgrade-to-
  Fully-Automated tracked via the `# TODO Agent-Probe:` marker at C2 (unchanged from outer-pvl
  pass).
- The deeper structural fix for A3b/A3c's ABC asymmetry (promoting a shared `AdsProvider`-level
  `refresh_tokens` default, matching the CRM pattern) is out of Phase 2's edit scope
  (`services/ads/base.py` is hard-forbidden). Tracked as a backlog item for whichever phase next
  touches that file — non-blocking, since A3c's `getattr` guard makes the current omission safe.
What this coverage does NOT prove:
- AC2 Fully-Automated (mocked callback) does NOT prove Meta's real OAuth consent screen, real
  token exchange, or the real `/me/adaccounts` response shape — only the Hybrid sandbox smoke
  (E3, deferred known-gap) would prove that.
- AC6 Fully-Automated does NOT prove Meta's real member-upload endpoint treats a reused
  `audience_id` as expected server-side — it only proves Beam's own DB-side reuse logic
  (`AdAudienceLink.platform_audience_id`), not Meta's live behavior.
- AC7's pre-push leg (D2b) does NOT prove the numeric threshold (1000) matches Meta's real
  current documented minimum, and its `visitor_count`-based estimate does NOT prove it equals
  the exact post-safety-filter hashed-contact count — it is an intentionally approximate
  pre-flight signal, not the authoritative number (which only D2's post-push fields provide).
- AC13 Agent-Probe does NOT prove the real Meta error code/shape for an unaccepted-ToS ad
  account — genuinely unverified without a live sandbox call; this is the named residual, not a
  silent gap.
- The new structural-safety unit test (`fresh_access_token` guard) does NOT prove Google's or
  LinkedIn's eventual real `refresh_tokens` implementation (if Phase 3 or a future phase adds
  one) will behave correctly — it only proves today's absence-of-the-method case is handled
  without crashing.
- The hard safety constraint gate (`git diff --stat` on 8 named files) does NOT prove no OTHER
  unlisted file gained CRM-like logic — it only proves those specific files are untouched;
  broader enforcement relies on the blast-radius registry's Hard-forbidden list plus review.
- The unit coverage gate does NOT exercise real Meta Graph API error responses, real rate
  limiting, or real network failure/timeout behavior — those paths are mocked/synthetic only.
(Required until C3 is implemented — temporary C3 mitigation)
Gate: PASS (no FAILs; all CONCERNs found this inner-PVL cycle — refresh_tokens ABC-scope gap,
ads_push.py registry-declaration gap, and AC7 pre-push/post-push architecture gap — resolved via
plan-text fixes P4-P6 or execute-agent instruction E3 in this same cycle; the two carried-forward
known-gaps from the outer-pvl pass, E3 sandbox smoke and AC13 exact error shape, remain
non-blocking Hybrid/Agent-Probe residuals, not vacuous Known-Gap-only coverage)
Accepted by: session (inner-PVL VALIDATE pass, 26-07-26) — no user-facing CONDITIONAL
concessions were needed; every finding was closed in-cycle via plan-text fix or execute-agent
instruction.

---

## Inner Loop Refresh Note

**Date:** 2026-07-26
**Trigger:** Phase 2 inner-loop Step 3 (PLAN-SUPPLEMENT) — RESEARCH + INNOVATE findings folded in.

Sections changed this pass:
- Step A: A3 rewritten for the two-step token exchange (INNOVATE-decided token strategy, option
  a); new items A3b (`refresh_tokens`) and A3c (`fresh_access_token` helper + call site) added.
  A1's Graph API version guidance updated to pin `v25.0` (docs-confirmed) instead of an
  unqualified "current version" instruction.
- Step B: B1 wording corrected to the as-built `link is None` condition (was
  `link.platform_audience_id is None`, which cannot occur since the field is non-nullable on an
  existing row). New item B1b added (EMAIL vs EMAIL_SHA256 schema-key docs-fetch, blocking B2).
- Step C: C1/C2 updated with the confirmed ToS error surface (HTTP 400 + message text) and
  resolution URL; JSON error code/subcode remains the only unconfirmed part (stays Agent-Probe).
- Step D: D1 confirmed `MIN_AUDIENCE_SIZE=1000` already exists as-built (no change needed); D2
  clarified as a REAL gap requiring new structured response fields plus a frontend fix to
  `ad-connect-panel.tsx`'s hardcoded warning copy.
- Blast Radius: added `apps/api/services/ads_push.py` as an explicit edit target for the new
  `fresh_access_token` helper.
- New sections added: `## Concurrent-Drift Note` (capacity-hardening program awareness) and
  `## Operator Env-Prereq Checklist` (pre-live-smoke/pre-production-enable requirements).

This note triggered a fresh inner-PVL pass for this plan before EXECUTE — completed 26-07-26 (see
`## Validate Contract` above, `generated-by: inner-pvl: phase-2`). The inner-PVL pass found and
closed 3 additional gaps the outer-pvl pass did not catch (refresh_tokens ABC-scope/guard,
ads_push.py registry-declaration, AC7 pre-push architecture) — see that contract's "Plan updates
applied" table (P4-P7) for details. The 25-07-26 outer-pvl contract is retained above (superseded)
for audit trail only; the inner-pvl contract is now authoritative.
