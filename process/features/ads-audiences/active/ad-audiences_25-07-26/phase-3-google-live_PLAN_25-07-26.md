---
name: plan:ad-audiences-phase-3-google-live
description: "Ad Audiences — Phase 3: Google live (Data Manager API OAuth, audience create/upload, EEA-region exclusion)"
date: 25-07-26
metadata:
  node_type: memory
  type: plan
  feature: ads-audiences
  phase: phase-3
---

# Phase 3 — Google Live

**Program:** ad-audiences
**Umbrella plan:** process/features/ads-audiences/active/ad-audiences_25-07-26/ad-audiences-umbrella_PLAN_25-07-26.md
**Phase status:** 🧪 TESTING (code-complete + EVL-green 26-07-26, commit e3adae3; pending G2/E4 Hybrid Google sandbox smoke before ✅ VERIFIED)
**Report destination:** process/features/ads-audiences/active/ad-audiences_25-07-26/phase-3-google-live_REPORT_{dd-mm-yy}.md (flat in the program task folder)

**Complexity:** COMPLEX
Complexity: COMPLEX
Date: 25-07-26
Status: 🧪 TESTING (code-complete + EVL-green 26-07-26)

## Overview

Replace the Phase 1 Google stub with real Google Customer Match integration via the Data Manager API: real OAuth, audience create/upload, sandbox test-account dev path, and the locked v1 EEA-region exclusion decision. See process/context/all-context.md for repo conventions and process/context/tests/all-tests.md for the test-runner routing this phase's Exit Gate commands follow.

## Acceptance Criteria

See the ## Verification Evidence table below — each row maps a test gate to the exact SPEC acceptance criterion it proves; this phase's Exit Gate is 'done' only when every AC row in that table is Fully-Automated-green or its declared Hybrid/Agent-Probe evidence is recorded in the phase report.

## Phase Completion Rules

CODE DONE = all Implementation Checklist items checked and automated Exit Gate commands exit 0. TESTING = Hybrid/Agent-Probe evidence being gathered. VERIFIED = validate-contract Gate is PASS (or explicitly-accepted CONDITIONAL) AND every row in Verification Evidence has real recorded evidence (not a placeholder) AND the phase report is written. A phase may not be marked VERIFIED on code completion alone.

---

## Purpose

Replace `services/ads/google.py`'s Phase-1 mock stub with real Google Customer Match integration
via the Data Manager API (the OfflineUserDataJobService successor): real OAuth
(`datamanager` + legacy `adwords` scope pairing), audience create/upload, a sandbox
test-account dev path (available with zero approval), and the locked v1 EEA-consent decision —
blanket exclusion of EEA-region visitor rows from every Google push (SPEC Open Question 4,
decision option c). Covers SPEC AC3. This phase depends only on Phase 1, not on Phase 2, and may
run before, after, or concurrently with Phase 2.

---

## Entry Gate

- Phase 1 exit gate passed: `services/ads/` registry pattern stable; `AdConnection` model has
  the `ad_account_id`/`business_id` fields needed for Google's equivalent identifiers
- Data Manager API docs-fetch (this phase's Step 1 RESEARCH) confirms the endpoint contract
  well enough to implement against, OR a feasibility-probe escalation has resolved the
  ambiguity (see SPEC Open Question 1/3 and the umbrella's "Phase 3 research-step special case")
  — **substantially pre-resolved by VALIDATE's own docs-fetch on 25-07-26; see Step A1's
  VALIDATE finding below. Step 1 RESEARCH should confirm/repeat this fetch rather than treat it
  as still-open, and additionally close SPEC OQ3 (token lifetime/refresh) which VALIDATE did
  NOT resolve.**

---

## Blast Radius

- `apps/api/services/ads/google.py` (edit — replace stub bodies with real logic; file already
  exists from Phase 1, Phase-1-owned for creation, Phase-3-owned for the real implementation —
  see blast-radius registry for the extension-point declaration)
- `apps/api/services/ads_push.py` (edit — add the EEA-region exclusion filter step for Google
  pushes specifically; extension point on a Phase-1-owned file, scoped to a clearly separated
  `if provider == "google":` branch so Meta's payload path is untouched)
- `apps/api/tasks/ads_tasks.py` (edit — extension point only, same pattern as Phase 2)
- `apps/api/routers/ads.py` (edit — extension point only, no new routes)
- Test files: `tests/unit/test_ads_google.py` (new), `tests/integration/test_ads_google_live.py`
  (new — mocked-callback integration), `tests/unit/test_ads_eea_exclusion.py` (new — EEA
  filter test)

**Not touched:** `apps/api/services/ads/meta.py`, `apps/api/services/ads/linkedin.py`,
`apps/api/services/ads/base.py`, `apps/api/services/ads/factory.py` (Phase 1-owned / Phase
2-owned respectively — Phase 3 may only READ these). Zero CRM/csv_exporter edits (program-wide
hard constraint).

**VALIDATE-added note (25-07-26; registry reconciled 25-07-26 via PVL-supplement — see
`phase-blast-radius-registry.md` §Phase 3, "Extension point on `apps/api/config.py`"):**
implementing Step C1's Google Ads API UserList-creation sub-call (see Step C1's VALIDATE finding)
requires ONE new field on `apps/api/config.py`: `google_ads_developer_token: str = ""`.
`config.py` is Phase-1-owned/append-only per the blast-radius registry; Phase 3 now has an
explicit, field-scoped extension-point grant for exactly this one field group (plus its
`field_validator` whitespace-strip entry) — no other `config.py` edit is authorized under this
grant. This item is therefore closed as a coordination gap; execute-agent may add the field
directly per the registry grant.

---

## Implementation Checklist

### Step A — Data Manager API contract confirmation (research-gated)

- [x] A1. Docs-fetch the Data Manager API's exact endpoint shapes: audience/product-audience
      creation, member upload, required scope pairing (`datamanager` + `adwords`), and consent
      field requirements (`ad_user_data`, `ad_personalization`). This is SPEC Open Question 1 —
      "the classic OfflineUserDataJobService is closed for new tokens... the replacement Data
      Manager API's exact endpoint shapes are unverified from source alone." If docs-fetch
      resolves the contract, proceed to Step B. If genuinely ambiguous after a real fetch
      attempt, emit `VC-FEASIBILITY-PROBE-NEEDED: [Data Manager API endpoint contract] —
      cost-class: docs-fetch` (escalating to `needs-live-provider` only if inconclusive,
      requiring explicit double opt-in per orchestration.md).

  **VALIDATE finding (25-07-26 — confirmed via direct fetch of the live API discovery document
  at `https://datamanager.googleapis.com/$discovery/rest?version=v1`; the devsite HTML reference
  pages are JS-rendered and returned 404s for guessed URLs, so this discovery-doc endpoint is
  the recommended primary source going forward — NOT genuinely ambiguous, no feasibility-probe
  escalation needed):**
  - The Data Manager API (`datamanager:v1`) exposes exactly 5 resource groups: `events.ingest`,
    `adEvents.ingest`, `audienceMembers.ingest` / `audienceMembers.remove`,
    `requestStatus.retrieve`, and `accountTypes.accounts.partnerLinks.search`.
    **There is NO audience/UserList-creation endpoint in the Data Manager API.**
    `audienceMembers.ingest`/`remove` upload/remove members against an ALREADY EXISTING
    `Destination.productDestinationId` ("Required. The object within the product account to
    ingest into. For example, a Google Ads audience ID...") — i.e. a Google Ads Customer Match
    "User List" resource id that must already exist. Creating that User List is a **separate
    Google Ads API call** (different host `googleads.googleapis.com`, scope
    `https://www.googleapis.com/auth/adwords` — confirms why the plan already anticipated the
    legacy `adwords` scope pairing). See Step C1's VALIDATE finding for how this splits the
    implementation.
  - OAuth scopes confirmed from the discovery doc's `auth.oauth2.scopes` block:
    `https://www.googleapis.com/auth/datamanager` ("See, edit, create, import, or delete your
    customer data in Google Ads...") and `https://www.googleapis.com/auth/datamanager.partnerlink`
    (not needed for this phase — partner-link flows are data-partner-only).
  - Consent fields confirmed: `IngestAudienceMembersRequest.consent` (request-level, applies to
    all members in the request) or per-`AudienceMember.consent` (member-level override) — shape
    `{adUserData: CONSENT_STATUS_UNSPECIFIED|CONSENT_GRANTED|CONSENT_DENIED, adPersonalization:
    same enum}`. **Note: these are camelCase JSON keys** (`adUserData`/`adPersonalization`) —
    SPEC's `ad_user_data`/`ad_personalization` were the conceptual/snake_case names; execute-agent
    must use camelCase in the actual REST payload.
  - `IngestAudienceMembersRequest.termsOfService.customerMatchTermsOfServiceStatus` must be set
    to `"ACCEPTED"` on any ingest call that carries `UserData` — a **required field not
    previously called out anywhere in this plan or the SPEC**. Added to Step C2 below.
  - `IngestAudienceMembersResponse` returns ONLY a `requestId` string — no synchronous
    per-member success/failure. Real processing status requires a follow-up
    `GET requestStatus:retrieve?requestId=...` call. E2's mocked-callback integration test must
    mock this two-step shape (ingest → `requestId` → status retrieve), not assume a single
    synchronous success response.
  - `UserIdentifier.emailAddress` / `.phoneNumber` are documented as "Hashed ... using SHA-256
    hash function after normalization" — confirms reusing `csv_exporter._sha256` verbatim is
    correct and no different hashing scheme is needed for Google specifically.

- [x] A2. Docs-fetch Google OAuth token lifetime/refresh behavior for the `datamanager` scope
      pairing (SPEC Open Question 3) — cheap, low-risk; escalate to `needs-live-provider` only
      if genuinely blocking. **Not resolved by VALIDATE's docs-fetch above — the discovery
      document does not describe OAuth token TTL/refresh semantics; standard Google OAuth2
      refresh-token behavior likely applies but this remains open for Step 1 RESEARCH.**
      **Known-gap / research item (PVL-supplement, 25-07-26 — explicit tag closing the Validate
      Contract's cross-file gap):** SPEC OQ3 is a documented open research item for this step,
      already carried in this plan's Validate Contract "Open gaps" list — Step 1 RESEARCH must
      resolve or re-confirm it before Step B (Real Google OAuth) implements the token
      exchange/refresh path; it is not silently dropped and does not block A1/Step B mock-mode
      work.

      **RESEARCH FINDING (26-07-26) — OQ3 RESOLVED:** standard OAuth2 semantics apply; no
      Google/Data-Manager-specific deviation. Under a **Testing**-status OAuth consent screen
      (the status of a newly-created Google Cloud project, e.g. the sandbox dev path used in
      this phase), issued refresh tokens expire after **7 days** and must be re-minted by
      re-running the consent flow. Under a **Published** consent screen, refresh tokens are
      indefinite subject to standard revocation rules and a 6-month unused-token expiry. This
      closes SPEC Open Question 3 — no further research needed; the only residual is an
      operator-checklist item (see the new Operator Checklist section below).

### Step A — Data Manager API contract confirmation (research-gated) (cont.)

- [x] A1b. **RESEARCH-added (26-07-26) micro-gate — runs before any Step B/C endpoint code.**
      Direct primary-source docs-fetch to pin: (a) the current Google Ads API version for
      `customers/{id}/userLists:mutate` (search snippets during RESEARCH conflicted on
      v18/v23/v24 — fetch `https://googleads.googleapis.com/$discovery/rest` or the live REST
      reference directly; if blocked, use the r.jina.ai proxy fallback documented in project
      memory), and (b) the UserList `mutate` request body shape plus whether a
      `login-customer-id` header is required or optional for DIRECT-customer-account access
      (Beam's connection model is direct-customer, not manager-account — confirm this, don't
      assume MCC semantics apply). Cost-class: docs-fetch. Any Step B/C item touching the Google
      Ads API `userLists:mutate` endpoint is BLOCKED on A1b closing.

  **EXECUTE finding (26-07-26 — A1b CLOSED, all three questions answered):**
  - (a) **Current version = `v25`.** Live unauthenticated probe of
    `POST https://googleads.googleapis.com/{v}/customers/1234567890/userLists:mutate`:
    v17–v19 → 404 (sunset), v20–v25 → 401 (exist), v26+ → 404 (unreleased). Corroborated by the
    version sidebar on `https://developers.google.com/google-ads/api/reference/rpc/v25/MutateUserListsRequest`
    (lists v21–v25, v25 first). Pinned as the single constant `GOOGLE_ADS_API_VERSION` in `google.py`.
  - (b) **UserList mutate body** (source: `https://developers.google.com/google-ads/api/reference/rpc/v25/MutateUserListsRequest`,
    `.../UserListOperation`, `.../CrmBasedUserListInfo`, `.../MutateUserListsResponse`,
    `.../MutateUserListResult`): `POST /v25/customers/{customerId}/userLists:mutate` with
    `{"operations":[{"create":{...UserList}}], "partialFailure":bool, "validateOnly":bool}`; the
    Customer Match list needs `crmBasedUserList.uploadKeyType` (required for ADD) +
    `dataSourceType` (default FIRST_PARTY). Response is `{"results":[{"resourceName":
    "customers/{cid}/userLists/{id}"}]}` — `resourceName` is the ONLY source of
    `platform_audience_id`. REST uses camelCase for these proto fields.
  - (c) **`login-customer-id` is NOT required for direct-customer access** (source:
    `https://developers.google.com/google-ads/api/rest/auth`, verbatim: "For Google Ads API calls
    made by a manager to a client account ... you also need to supply the `login-customer-id` HTTP
    header"). Beam's model is direct-customer, so the header is deliberately omitted; MCC semantics
    do not apply. `developer-token` IS required on every call and is sent.
  - Data Manager side re-confirmed live from `https://datamanager.googleapis.com/$discovery/rest?version=v1`
    (revision 20260722): `audienceMembers:ingest` request takes `destinations[]`, `audienceMembers[]`,
    `encoding` (`HEX`|`BASE64` — `HEX` chosen, `csv_exporter._sha256` emits a hex digest),
    `consent{adUserData,adPersonalization}`, `termsOfService.customerMatchTermsOfServiceStatus`;
    response is `{requestId}` only. Batch cap 10000 members/request (implemented).
  - **Observation (no plan deviation):** that same discovery revision now also exposes
    `accountTypes.accounts.userLists.create` on the Data Manager API — a capability that did not
    exist at VALIDATE's 25-07-26 fetch. The plan's locked two-API architecture (Google Ads API
    creates the list) was implemented as specified; a future phase could collapse this to one API.

### Step B — Real Google OAuth

- [x] B1. Implement `GoogleAdsProvider.get_oauth_url(state)` for real (non-mock) mode using the
      confirmed scope pairing from A1/A2 (`https://www.googleapis.com/auth/datamanager` +
      `https://www.googleapis.com/auth/adwords`) and `oauth_state.py` (reused verbatim) for CSRF.
- [x] B2. Implement `GoogleAdsProvider.exchange_code(code)` for real mode: token exchange +
      capture of the Google Ads customer/manager account id needed for subsequent Data Manager
      API calls. Encrypt and store via `services/encryption.py` (imported, not modified) — same
      callback-handler extension pattern as Phase 2 Step A3, applied to the `google` branch
      inside `routers/ads.py`'s already-existing callback handler.
- [x] B3. Preserve the Phase-1 mock branch unchanged for every method touched.
- [x] B4. Confirm the sandbox test-account path (available with zero approval per SPEC research)
      is the dev/demo path used for E2's automated + Hybrid tests — do NOT depend on a
      production dev-token (Basic tier) approval for any gate in this phase; that approval is
      explicitly out of scope as a program blocker (SPEC "Out Of Scope" item). Sandbox/test-account
      calls use a Google-issued *test* developer token, consistent with this stance (see Step
      C1's VALIDATE finding on the new `google_ads_developer_token` config field).

- [x] B5. **RESEARCH-added (26-07-26).** Implement
      `GoogleAdsProvider.refresh_tokens(refresh_token: str) -> AdOAuthTokens` — uses
      `grant_type=refresh_token` with the STORED refresh secret. This is **structurally
      different** from Meta's `fb_exchange_token(current_access_token)`, which exchanges the
      current access token for a new one; Google's flow instead consumes a long-lived refresh
      secret that is never itself replaced by the refresh call. The method's docstring MUST
      state this difference explicitly so a future maintainer does not assume the Meta shape
      applies. Fold into B1: the OAuth URL built by `get_oauth_url` must carry
      `access_type=offline` AND `prompt=consent` — Google will NOT issue a `refresh_token` on
      the token-exchange response otherwise (a one-time/first-consent-only issuance quirk).
      `AdOAuthTokens.refresh_token` field already exists as-built from Phase 1 — no dataclass
      change needed here.
- [x] B6. **RESEARCH-added (26-07-26) — provider-aware token selection at the `fresh_access_token`
      call site.** As-built, `ads_push.py:146` calls `refresher(token)` passing the decrypted
      ACCESS token (correct for Meta's shape). Add a provider-aware branch: when
      `conn.provider == "google"`, pass the decrypted `conn.refresh_token` instead of the
      decrypted access token — the getattr-based refresher-lookup guard already in place is
      unchanged, only the argument selected before the call differs. This is a SECOND
      `ads_push.py` touch beyond the already-declared EEA-exclusion branch (Step D); the
      blast-radius registry's Phase 3 `ads_push.py` extension-point entry has been extended by
      one line to cover it (see `phase-blast-radius-registry.md` §Phase 3, appended 26-07-26).

### Step C — Audience create + upload

- [x] C1. Implement `GoogleAdsProvider.create_or_update_audience(connection, link,
      hashed_contacts)` against the confirmed Data Manager API contract from Step A: if
      `link.platform_audience_id` is None (first push), create; if already set (repeat push —
      AC6, shared mechanism with Meta via the same `AdAudienceLink` upsert pattern from Phase
      1), update the existing audience. Same `ad_audience_links` unique-constraint upsert
      mechanism as Phase 2 — no new duplication-prevention logic needed, this is a straight
      reuse of the Phase-1-built mechanism.

  **VALIDATE finding:** because the Data Manager API cannot create an audience (see Step A1's
  finding), `GoogleAdsProvider.create_or_update_audience` must internally make **two calls**
  when `link.platform_audience_id` is None:
  1. A **Google Ads API** call (raw httpx REST, matching this repo's established no-SDK
     convention for external calls — e.g. `gemini_client.py` — no `google-ads` pip package
     exists in `requirements.txt` today and none should be added) that creates a Customer Match
     `UserList` under the connected `ad_account_id`, capturing its resource id/name as the value
     to persist into `AdAudienceLink.platform_audience_id`.
  2. The Data Manager API `audienceMembers.ingest` call referencing that id via
     `Destination.productDestinationId`.

  When `platform_audience_id` is already set, skip step 1 and only call step 2 (update path).
  The shared `AdsProvider.create_or_update_audience(...) -> dict` interface (Phase-1-built,
  `services/ads/base.py`) does NOT need to change — this two-call sequence is an internal detail
  of Google's implementation only, same as Meta's own two-call `POST .../customeraudiences` +
  `POST .../users` sequence already assumed in Phase 2.

  **New config dependency:** the Google Ads API requires a `developer-token` HTTP header on
  every call. This needs one new config field, `google_ads_developer_token: str = ""` —
  **RESOLVED (PVL-supplement cycle 1, 25-07-26):** the blast-radius registry now grants Phase 3
  a field-scoped extension point on `apps/api/config.py` for exactly this field group (see
  Blast Radius section note above and `phase-blast-radius-registry.md` §Phase 3). Execute-agent
  may add the field directly per the registry grant — no further coordination step required
  before implementing this sub-call.

- [x] C2. Wire the required `ad_user_data` and `ad_personalization` consent fields on every
      upload call, set GRANTED — but ONLY for the EEA-excluded, already-filtered contact set
      produced by Step D (Google silently drops EEA rows missing these fields per SPEC
      research; since this v1 excludes EEA rows entirely, the consent fields are set GRANTED
      unconditionally for the non-EEA rows that remain, which is correct per the locked
      decision).

  **VALIDATE finding:** use the confirmed camelCase field names `adUserData`/`adPersonalization`
  (see Step A1) set to `"CONSENT_GRANTED"`. Also set
  `termsOfService.customerMatchTermsOfServiceStatus = "ACCEPTED"` on every ingest call that
  carries `UserData` — a required field surfaced by VALIDATE's docs-fetch, not previously listed
  here or in the SPEC.

### Step D — EEA-region exclusion (locked decision c)

- [x] D1. In `ads_push.py`'s Google-specific branch (extension point declared in Blast Radius),
      after the standard `_get_segment_visitors` safety-filter chain runs (unchanged, shared
      with Meta and CSV export), add a Google-only filter step: exclude any visitor row whose
      region/country field indicates an EEA member state. Confirm the exact
      region/country field already available on `IdentifiedVisitor`/`Visitor` (per
      `all-context.md`, region/country is "already on IdentifiedVisitor" — RESEARCH step
      confirms the exact field name and EEA country-code list source, e.g. a static ISO-3166
      EEA member list constant defined in this file, not invented ad hoc elsewhere).

  **VALIDATE finding:** confirmed mechanically feasible without any schema change —
  `IdentifiedVisitor.country` (`String(5)`, `apps/api/models/visitor.py:90`) already exists and
  already flows through `csv_exporter._get_segment_visitors`'s returned dict as `"country":
  identified.country or ""` (`apps/api/services/csv_exporter.py:109`). No existing EEA
  country-code constant exists anywhere in the codebase (checked: no `EEA`/`EU_COUNTR*` list in
  `apps/api/`) — defining a static ISO-3166 EEA member list constant locally in `ads_push.py`, as
  this step already proposes, is correct and there is nothing to reuse instead.

  **Fail-closed requirement:** when a visitor's `country` value is null/empty (the resolution
  provider did not return country data for that visitor — a real, observed possibility per
  `identity_resolver.py`'s `country=data.get("country")` pattern, which has no guaranteed
  non-null source), the filter MUST treat this as EEA-ambiguous and **EXCLUDE the row (fail
  closed)**, not fail open. Failing open on missing country data would risk sending a real EEA
  visitor's hashed PII to Google without the required consent fields being meaningfully
  determined — the opposite of the SPEC's "blanket exclusion" intent. An unknown country must
  never be treated as "safe to push."
- [x] D2. This filter applies ONLY to the Google push path — Meta pushes (Phase 2) have no
      such consent-field requirement in the SPEC and must NOT be affected by this change. Add
      an explicit regression test proving a synthetic EEA visitor is excluded from a Google
      payload but INCLUDED in an equivalent Meta payload (same segment, two different provider
      pushes) — this is the AC coverage item requested by the umbrella's reconciliation notes.
- [x] D3. Document options (a) pixel-consent mapping and (b) manual site-level attestation as
      future enhancements in the phase report's backlog section, per the locked decision —
      these are explicitly out of scope for this phase, not silently dropped.

### Step E — Test coverage

- [x] E1. `tests/unit/test_ads_google.py`: unit tests for `GoogleAdsProvider` methods in mock
      mode (Fully-Automated) — OAuth URL shape, exchange response parsing, audience
      create/update branch logic.
- [x] E1b. **RESEARCH-added (26-07-26).** `tests/unit/test_ads_google.py` (same file, additional
      cases, Fully-Automated): unit test for `GoogleAdsProvider.refresh_tokens` — (a) the
      stored-refresh-token exchange path (`grant_type=refresh_token` using the stored refresh
      secret, asserting the request never reuses the access token as the refresh credential),
      and (b) the `fresh_access_token` call-site branch selection (Step B6) — assert that when
      `conn.provider == "google"`, the decrypted `refresh_token` is passed to `refresher(...)`,
      and when `conn.provider == "meta"`, the existing access-token behavior is unchanged
      (regression coverage for the shared call site).
- [x] E2. `tests/integration/test_ads_google_live.py`: integration test against a MOCKED Google
      OAuth callback (Fully-Automated) — full connect → push → repeat-push flow, asserting
      `platform_audience_id` reuse (AC6, Google leg).

  **VALIDATE finding:** per Step C1's finding, the mocked-callback test must mock the two-call
  sequence — assert `platform_audience_id` is captured from the (mocked) **Google Ads API**
  UserList-creation response, NOT from the Data Manager `audienceMembers.ingest` response (which
  only ever returns a `requestId`, never an audience/list id).

- [x] E3. `tests/unit/test_ads_eea_exclusion.py`: unit/integration test (Fully-Automated) — seed
      a segment containing an EEA-region visitor and a non-EEA visitor; assert the Google push
      payload excludes the EEA visitor while an equivalent Meta push payload (same segment)
      includes both (per D2).

  **VALIDATE finding:** also add a case for a visitor with null/empty `country` — assert it is
  EXCLUDED from the Google payload (fail-closed default per Step D1's finding) while still
  INCLUDED in the equivalent Meta payload (Meta has no country-based filter).

- [ ] E4. Hybrid manual smoke against a Google test-account sandbox (documented procedure in the
      phase report, zero-approval path per SPEC research) — run once before this phase can be
      marked VERIFIED.

---

## Exit Gate

```bash
# Zero CRM/csv_exporter drift (program-wide constraint, re-checked every phase)
git diff --stat main -- apps/api/models/crm_connection.py apps/api/routers/crm.py \
  apps/api/services/crm.py apps/api/services/crm/ apps/api/services/crm_push.py \
  apps/api/services/crm_rate_limiter.py apps/api/tasks/crm_tasks.py apps/api/services/csv_exporter.py
# Expected: empty output

pytest tests/unit -k ads_google -m unit
pytest tests/unit -k ads_eea_exclusion -m unit
pytest tests/integration -k ads_google -m integration
# Expected: all green
```

- AC3 passes at Fully-Automated (mocked callback) tier; Hybrid sandbox-account smoke (E4)
  recorded in phase report
- EEA-exclusion test (E3) passes, proving Google-only scope of the filter, including the
  fail-closed null-country case
- Data Manager API contract confirmed via docs-fetch (A1) or feasibility-probe escalation
  resolved — **substantially confirmed by VALIDATE 25-07-26; Step 1 RESEARCH should verify/
  repeat**
- Phase report written to report destination above

---

## Blockers That Would Justify BLOCKED Status

- Data Manager API docs-fetch (A1) is genuinely inconclusive AND a live-provider probe is
  refused/unavailable — do NOT silently guess at the contract; escalate per A1's instructions,
  and if still unresolved, mark this phase BLOCKED with a backlog note rather than shipping an
  unverified implementation against a public API surface (high-risk class). **Largely
  de-risked by VALIDATE's 25-07-26 docs-fetch — this blocker is now unlikely to trigger.**
- Google test-account sandbox for the Hybrid smoke (E4) is not available in this environment —
  record as a known-gap, do not block the whole phase; automated tiers (E1, E2, E3) can still
  reach green
- The exact `IdentifiedVisitor`/`Visitor` region/country field name is ambiguous after RESEARCH
  — resolve via a targeted codebase read before implementing D1, not via assumption.
  **Resolved by VALIDATE 25-07-26: `IdentifiedVisitor.country` — see Step D1's finding.**
- ~~The `google_ads_developer_token` config field (Step C1's VALIDATE finding) is not yet
  granted a blast-radius-registry extension point on `apps/api/config.py`~~ — **RESOLVED
  (PVL-supplement cycle 1, 25-07-26):** the registry now grants Phase 3 a field-scoped
  extension point on `apps/api/config.py` (see Blast Radius section note and
  `phase-blast-radius-registry.md` §Phase 3, "Extension point on `apps/api/config.py`"). No
  longer a blocker candidate — execute-agent may add the field directly per the grant.

---

## Operator Checklist (RESEARCH-added, 26-07-26)

Non-blocking operational steps an operator must complete before/around this phase's Hybrid smoke
(E4/G2) and before any real (non-Testing) consent screen use:

- **Developer token:** obtain the 22-character Google Ads developer token via the Google Ads UI
  API Center, under the connected manager account. This is the value that populates the new
  `google_ads_developer_token` config field (Step C1).
- **Test Account Access:** the zero-approval dev path this phase's E4 Hybrid smoke depends on —
  confirm this is enabled and is the correct default; it requires no Google review.
- **Basic access approval:** a SEPARATE, later, out-of-scope operator action (production dev-token
  tier) — do not block on it, do not request it as part of this phase.
- **Consent-screen publish status:** confirm the Cloud project's OAuth consent-screen publish
  status (Testing vs Published) before running the E4 Hybrid smoke — Testing-status refresh
  tokens expire in 7 days (see A2's RESEARCH finding above), so expect to re-mint the sandbox
  connection roughly weekly while the project remains in Testing.
- **Brand verification:** completing Google's brand-verification step on the Cloud project can
  speed up any future review (2026 policy note) — optional, not required for this phase's gates.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — research-agent: Phase 1 report read in full; test context loaded; Data Manager API docs-fetch (A1/A2) — A1 substantially pre-resolved by VALIDATE 25-07-26, A2 (token lifetime/refresh) still open; confirm EEA region/country field on IdentifiedVisitor/Visitor — pre-resolved by VALIDATE 25-07-26 (`IdentifiedVisitor.country`)
- [x] 2. INNOVATE — SKIPPED (mechanical): Google's refresh-token flow and OAuth-URL params are platform-dictated by the Data Manager/Google Ads API contract, not a design choice — no viable-approach comparison exists to decide between. No Decision Summary produced.
- [x] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated with docs-fetch findings; Inner Loop Refresh Note if sections changed (or "n/a — research clean")
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md` — Gate: PASS (outer PVL, 25-07-26, re-confirm pass after PVL-supplement cycle 1 closed the config.py registry gap and OQ3 known-gap tagging); see Validate Contract below
- [x] 5. EXECUTE — all checklist items done; per-section test gates run and green (or gaps documented)
- [x] 6. EVL — all EVL gates green (results.tsv row 7, 26-07-26: vc-tester independent confirmation, G1–G7 all PASS — 574 unit + 30 google/eea + 23 ads integration incl. Meta regression + guardrail 18 + tsc + frozen zero-diff + no-live-call grep + single head `d5b1f7c3a908`; dev-token Agent-Probe promoted to automated test; only G2/E4 sandbox smoke open, env-only; HALTED_SUCCESS, no regression P1/P2/P3)
- [x] 7. UPDATE PROCESS — this session (07-08-26): umbrella `## Current Execution State` rewritten, Phase 3 known-gaps appended to backlog note, all-context.md feature entry updated. **Process commit pending user** (user declined commits this run — commit the process artifacts when ready). Plan stays in `active/` — 🧪 TESTING pending G2/E4 operator sandbox gate; not archive-ready.

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate Contract`
reads "(placeholder — vc-validate-agent writes this section before EXECUTE)", orchestrator must
spawn vc-validate-agent first. A partial contract missing Plan updates applied / Execute-agent
instructions / Test gates sections is treated as a placeholder.

---

## Touchpoints

`apps/api/services/ads/google.py` (edit, Phase-3-owned real logic), `apps/api/services/ads_push.py`
(edit — Google-only extension point), `apps/api/tasks/ads_tasks.py` (edit — extension point
only), `apps/api/routers/ads.py` (edit — extension point only), plus new test files listed in
Blast Radius. **VALIDATE-added:** `apps/api/config.py` (append-only, one new field — registry
reconciliation CLOSED 25-07-26, see Blast Radius note above).

---

## Public Contracts

- No new routes. `POST /api/v1/ads/{site_id}/connections/google/push` behavior gains the EEA
  exclusion as an internal filtering change — no response shape change beyond the existing
  pushed/skipped counts already returned by the Phase-1-built endpoint (EEA-excluded rows count
  as "skipped", same field, no new field required).
- No change to any CRM or CSV export public contract.

---

## Verification Evidence

| ID | Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|---|
| G1 | Integration test: mocked Google OAuth callback completes, connection shows status=connected | Fully-Automated | AC3 (automated leg) |
| G2 | Hybrid manual smoke: Google test-account sandbox connect flow | Hybrid | AC3 (live leg, zero-approval sandbox path) |
| G3 | Integration test: push twice, `platform_audience_id` reused on second call (sourced from the mocked Google Ads API UserList-creation response, not the Data Manager ingest response) | Fully-Automated | AC6 (Google leg) |
| G4 | Unit test: EEA visitor excluded from Google payload, included in equivalent Meta payload | Fully-Automated | SPEC Open Question 4 decision (c) — EEA exclusion |
| G5 | Unit test: visitor with null/empty `country` excluded from Google payload (fail-closed), included in equivalent Meta payload | Fully-Automated | SPEC Open Question 4 decision (c) — EEA exclusion, fail-closed edge case (VALIDATE-added) |
| G6 | `git diff --stat` on CRM/csv_exporter files empty | Fully-Automated | Hard safety constraint |

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-3-google-live_PLAN_25-07-26.md`
- Last completed step: PVL (outer, 25-07-26, re-confirm pass after PVL-supplement cycle 1) — Gate: PASS
- Validate-contract status: written (25-07-26) — PASS. The two PVL-supplement-cycle-1 target gaps
  are both CLOSED: (1) `google_ads_developer_token` config.py registry extension point — granted;
  (2) SPEC OQ3 known-gap tagging — explicitly tagged on Step A2. Remaining items are non-blocking
  named residuals carried via Test Gates gap-resolution C/D (not open CONCERNs): SPEC OQ3 token
  lifetime/refresh itself (still open for Step 1 RESEARCH to resolve/confirm), G2/E4 Hybrid
  sandbox smoke (backlog test-building stub, run once before VERIFIED), developer-token
  secret-storage pattern (Agent-Probe, confirm at EXECUTE — mirrors the existing `*_client_secret`
  field pattern already present in `config.py`). See Validate Contract below.
- Next step: Spawn vc-research-agent for RESEARCH (Step 1) — Data Manager API contract (A1) and
  EEA field (D1) are substantially pre-resolved by this VALIDATE pass; RESEARCH should verify/
  repeat A1's fetch, close A2 (OAuth token lifetime/refresh, SPEC OQ3), and read the Phase 1
  report in full once Phase 1 has executed.

---

## Test Infra Improvement Notes

- The Data Manager API's async `requestId` → `requestStatus.retrieve` polling shape (confirmed
  by VALIDATE 25-07-26) has no existing test-double pattern in this codebase — E2's mocked
  integration test will need a small new fixture/helper for a two-step mocked response sequence
  (ingest returns `requestId`, then a status-retrieve call returns a terminal status). Worth
  factoring into a shared test helper if Phase 2 (Meta) or future phases need a similar
  async-polling mock shape.

---

## Validate Contract

Status: PASS
Date: 26-07-26
date: 2026-07-26
generated-by: inner-pvl: phase-3
supersedes: 2026-07-25 (outer-pvl) — inner-loop RESEARCH (Step 1, partial) + PLAN-SUPPLEMENT
(Step 3) folded in B5/B6 (Google refresh-token flow), A1b (Google Ads API version/UserList-body/
login-customer-id docs-fetch micro-gate), OAuth `access_type=offline`+`prompt=consent`, E1b
(refresh-flow unit coverage), OQ3 closure (7-day Testing-status token expiry), and an
INNOVATE-skip record; inner PVL has current evidence.

Parallel strategy: sequential
Rationale: single-agent re-run, narrowly scoped to verifying the 7 supplement changes named in
the Inner Loop Refresh Note plus a full-plan contradiction sweep (score 2/7 unchanged — S6
high-risk class present, S2 schema/API/auth surface touched). This VALIDATE pass again ran with
no subagent-spawn capability in its runtime context (Read/Bash/Write only); sequential
single-agent verification, backed by direct source-file reads (not inference), was sufficient
given the narrow, already-scoped confirmation task. A future EXECUTE-strategy recommendation
should still default to parallel subagents per the 2/7 score.

Test gates (C3 5-column table — ADDITIVE; existing consumers still parse the legacy line form below it):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| G1 | Mocked Google OAuth callback completes; connection shows status=connected | Fully-Automated | `pytest tests/integration -k ads_google -m integration` | A |
| G2 | Live Google test-account sandbox connect flow succeeds | Hybrid | Manual smoke against Google sandbox, documented in phase report (precondition: `google_ads_client_id`/`secret` set to a real Google Cloud test app + Google Ads test-account credentials) | D |
| G3 | Repeat push reuses `platform_audience_id`, sourced from the (mocked) Google Ads API UserList-creation response, not from Data Manager `audienceMembers.ingest`'s `requestId`-only response | Fully-Automated | `pytest tests/integration -k ads_google -m integration` (E2, updated per VALIDATE finding) | B |
| G4 | EEA-region visitor excluded from Google push payload; included in equivalent Meta push payload | Fully-Automated | `pytest tests/unit -k ads_eea_exclusion -m unit` | A |
| G5 | Visitor with null/empty `country` excluded from Google push payload (fail-closed default); included in equivalent Meta push payload | Fully-Automated | `pytest tests/unit -k ads_eea_exclusion -m unit` (new case, VALIDATE-added) | B |
| G6 | Zero CRM/csv_exporter file drift | Fully-Automated | `git diff --stat main -- apps/api/models/crm_connection.py apps/api/routers/crm.py apps/api/services/crm.py apps/api/services/crm/ apps/api/services/crm_push.py apps/api/services/crm_rate_limiter.py apps/api/tasks/crm_tasks.py apps/api/services/csv_exporter.py` (expect empty output) | A |
| G7 | `GoogleAdsProvider.refresh_tokens(refresh_token)` uses the stored refresh secret (never the access token); `fresh_access_token`'s call site passes the decrypted `refresh_token` when `provider == "google"` and leaves the Meta path (decrypted access token) unchanged (regression) | Fully-Automated | `pytest tests/unit -k ads_google -m unit` (E1b, RESEARCH-added 26-07-26) | B |
| — | Google Ads API `developer-token` config field (`google_ads_developer_token`) exists and is wired into the UserList-creation call | Agent-Probe | Code review of `apps/api/config.py` + `services/ads/google.py` at EXECUTE time — no automated gate possible until the field exists; registry extension point is granted (CLOSED, PVL-supplement cycle 1), field itself is added by execute-agent per the grant | C |

gap-resolution legend:
- A — proven now (gate passes in this cycle) — N/A here, these are prospective (Phase 3 has not
  yet executed, so no Phase-3-owned test currently runs); marked A because the test design itself
  is fully specified and unblocked once this phase reaches EXECUTE.
- B — fixed in this plan (gate added by this plan's checklist: E2/E3 VALIDATE-updated in the prior
  pass; G7/E1b added this pass, mapping the RESEARCH-added B5/B6 refresh-flow behavior to its
  proving test)
- C — deferred to a named later phase/plan (config.py `google_ads_developer_token` field itself —
  registry extension point that gated this is granted; only the field addition, a normal
  execute-time step, remains)
- D — backlog test-building stub (named residual; Hybrid sandbox smoke E4/G2, zero-approval sandbox path, run once before VERIFIED per the Blockers section's existing known-gap precedent)

C-4 reconciliation: the `strategy:` column carries ONLY the 3 proving strategies (Fully-Automated / Hybrid / Agent-Probe). Known-Gap is NEVER a `strategy:` value — it is a named residual row carried via gap-resolution D, never a strategy that proves a behavior.

Legacy line form (retained so existing validate-contract consumers still parse):
- Google OAuth + push (AC3, AC6 Google leg): Fully-automated: `pytest tests/integration -k ads_google -m integration` | Hybrid: manual Google test-account sandbox smoke (documented in phase report) + precondition real test-app credentials | Agent-probe: code review of `google_ads_developer_token` wiring once added | known-gap: none currently — G2 sandbox smoke is Hybrid, tracked, not silently dropped
- Google refresh-token flow (B5/B6, RESEARCH-added 26-07-26): Fully-automated: `pytest tests/unit -k ads_google -m unit` (E1b — both the stored-refresh-secret exchange path and the provider-aware `fresh_access_token` call-site branch, including a Meta-path regression case)
- EEA exclusion (SPEC OQ4 decision c): Fully-automated: `pytest tests/unit -k ads_eea_exclusion -m unit` (covers both the direct EEA-country case and the VALIDATE-added null-country fail-closed case)
- Zero CRM/csv_exporter drift: Fully-automated: `git diff --stat main -- apps/api/models/crm_connection.py apps/api/routers/crm.py apps/api/services/crm.py apps/api/services/crm/ apps/api/services/crm_push.py apps/api/services/crm_rate_limiter.py apps/api/tasks/crm_tasks.py apps/api/services/csv_exporter.py`

Dimension findings:
- Infra fit: PASS — direct re-read of `apps/api/config.py` confirms `google_ads_client_id`/
  `_secret`/`_redirect_uri` already exist (lines 399-401) with the `field_validator`
  whitespace-strip entry (line 486); the `google_ads_developer_token` registry extension point
  (granted PVL-supplement cycle 1) is unchanged and still the only authorized new field.
  `AdConnection.refresh_token` (Text, nullable, encrypted) already exists on the as-built model
  (`apps/api/models/ad_connection.py:39`) and is already written/read by the shared OAuth callback
  (`routers/ads.py:177`) and by `fresh_access_token` (`ads_push.py:156-157`) — B5/B6 need ZERO
  schema change, only a new provider method plus a call-site branch. `AdsProvider` ABC
  (`services/ads/base.py`) confirmed to declare no `refresh_tokens` method (frozen, matches Meta's
  own docstring precedent) — B5's plan to declare `refresh_tokens` only on `GoogleAdsProvider` is
  mechanically consistent with the existing pattern, not a new one. `LinkedInAdsProvider` has no
  `refresh_tokens` method either, and the `getattr(provider_impl, "refresh_tokens", None)` guard at
  `ads_push.py:141` already handles its absence safely (returns the unrefreshed token, no
  `AttributeError`) — confirmed by direct read of `linkedin.py`.
- Test coverage: PASS — E1b (new RESEARCH-added item) correctly targets
  `tests/unit/test_ads_google.py`, the same file as E1, so no new pytest `-k` selector is needed
  for the Exit Gate's existing `pytest tests/unit -k ads_google -m unit` command — it will
  automatically pick up E1b's cases once written. Added Test Gates row G7 (this pass) so the
  refresh-token behavior (B5/B6) has an explicit criterion-to-test mapping — the C3 table
  previously had no row for it (a documentation gap from the outer-pvl pass predating the
  supplement, not a missing test: E1b was always the intended test, just not yet reflected in the
  table). No developed behavior in this plan now lacks a named proving test or an explicit
  gap-resolution row (net-gate vacuous-green check: PASS).
- Breaking changes: PASS — B6's `fresh_access_token` change is a call-site branch only; the
  function signature (`fresh_access_token(db, conn) -> str`) is unchanged, and E1b's Meta-path
  regression case is explicitly scoped to prove the existing Meta behavior is untouched. No public
  contract, schema, or route change. Zero CRM/csv_exporter edits, unchanged from prior pass.
- Security surface: PASS — the refresh-token storage path is not new:
  `conn.refresh_token = encrypt_token(tokens.refresh_token)` already exists at two call sites
  (`routers/ads.py:177` on initial exchange, `ads_push.py:157` on refresh) using the same
  `encryption.py` mechanism as every other OAuth secret in this codebase — B5/B6 introduce no new
  secret-handling mechanism, only a new provider method returning an `AdOAuthTokens` shape already
  fully supported by the persistence layer. `access_type=offline`+`prompt=consent` are standard,
  publicly documented Google OAuth query parameters (no security novelty). EEA fail-closed
  requirement (Step D1) and its test (G5) re-verified unchanged, no regression from the supplement
  edits.
- Section A — Data Manager API contract confirmation: PASS — A1 unchanged from prior pass
  (re-read, verbatim). A1b (new RESEARCH-added micro-gate) is correctly scoped as
  blocking-before-code for Step B/C's Google Ads API `userLists:mutate` call, cost-class
  docs-fetch, consistent with A1's own escalation pattern — no design/mechanical issue. A2/OQ3
  finding is internally consistent with the new Operator Checklist section's 7-day
  Testing-status re-mint note.
- Section B — Real Google OAuth: PASS — B5's docstring requirement (must state the structural
  difference from Meta's `fb_exchange_token` shape) is mechanically satisfiable — Meta's own
  `refresh_tokens` docstring (`services/ads/meta.py:267-280`, directly re-read this pass) already
  models exactly this kind of explanatory docstring, giving B5 a concrete in-repo precedent to
  follow. B6's call-site branch (`conn.provider == "google"` → pass decrypted
  `conn.refresh_token`) is a single `if`/branch inside `fresh_access_token`, confirmed by direct
  re-read of the current (pre-B6) function body (`ads_push.py:115-161`) to be a minimal, additive
  change with no restructuring of the existing `getattr`-guard or error-handling path. No conflict
  with the already-declared EEA-exclusion extension point in the same file (different function,
  `push_segment_to_ads`, not `fresh_access_token`).
- Section C — Audience create + upload: PASS — unchanged from prior pass; registry grant
  re-confirmed present.
- Section D — EEA-region exclusion: PASS — unchanged from prior pass; mechanical feasibility and
  fail-closed requirement re-verified via direct re-read of `IdentifiedVisitor.country`
  (`models/visitor.py:97`) and its flow through `csv_exporter._get_segment_visitors`
  (`csv_exporter.py:110`); no EEA constant exists elsewhere in `apps/api/` (re-confirmed via
  repo-wide grep this pass) — defining it locally in `ads_push.py` remains correct.
- Section E — Test coverage: PASS — E1b's two sub-cases (stored-refresh-secret exchange path;
  provider-aware call-site branch with Meta regression) are each independently assertable against
  the current, unmodified `fresh_access_token` and `MetaAdsProvider.refresh_tokens`
  implementations (both re-read this pass) — no test-design ambiguity.
- INNOVATE-skip record: PASS — the recorded reason (Google's refresh-token grant type and
  required OAuth-URL params are platform-dictated, not a design choice) is factually consistent
  with A1/A2's own docs-fetch findings and with Meta's parallel (Phase 2, INNOVATE-decided) case
  being a genuine design choice by contrast — the skip is appropriately scoped and does not
  silently skip a decision that actually had viable alternatives.

Open gaps:
- CLOSED (prior cycle) — `google_ads_developer_token` config field blast-radius-registry
  extension point: granted 25-07-26 (PVL-supplement cycle 1) on `apps/api/config.py`. Re-confirmed
  present this pass.
- CLOSED (prior cycle) — SPEC OQ3 known-gap tagging: Step A2 explicitly tags SPEC Open Question 3
  as a known-gap/research item.
- CLOSED (this cycle) — SPEC OQ3 itself: RESEARCH (26-07-26) resolved it — standard OAuth2
  semantics apply; Testing-status refresh tokens expire in 7 days, Published-status tokens are
  indefinite subject to standard revocation/6-month-unused-expiry. Carried forward into the new
  Operator Checklist section. No further research needed on this question.
- Still open (non-blocking named residual, unchanged) — A1b (Google Ads API version + UserList
  `mutate` body + `login-customer-id` header docs-fetch): correctly gates Step B/C endpoint code,
  to be closed by Step 1 RESEARCH before those items proceed.
- Still open (non-blocking named residual, unchanged) — G2/E4 Hybrid Google test-account sandbox
  smoke: no live Google Cloud test-app credentials available in this VALIDATE session's
  environment; documented known-gap, run once before VERIFIED.
- Still open (non-blocking named residual, unchanged) — developer-token secret storage mechanism:
  mirrors the existing `*_client_secret` pattern already present in `apps/api/config.py`; confirm
  at EXECUTE time.

What this coverage does NOT prove:
- G1/G3 (mocked-callback integration tests) do NOT prove the REAL Google Ads API / Data Manager
  API accept the request shapes exactly as mocked — only that the codebase's own internal
  sequencing and data flow (OAuth exchange → UserList create → member ingest → link upsert) is
  internally self-consistent. Real-shape confirmation is the job of G2 (Hybrid sandbox smoke).
- G4/G5 (EEA/fail-closed unit tests) do NOT prove Google's own server-side behavior when
  consent-required rows are actually submitted — they prove Beam's own pre-submission filtering
  logic is correct, per the SPEC's decision (c): never submit EEA rows at all.
- G6 (CRM/csv_exporter drift check) does NOT prove behavioral correctness of any Google-specific
  code — only that no CRM/csv_exporter file was touched.
- G7/E1b (refresh-token unit tests) do NOT prove Google's real OAuth token endpoint actually
  behaves per A2's RESEARCH finding (7-day Testing-status expiry, indefinite Published-status) —
  that is an operational/observational fact from Google's documentation, not something a unit
  test can verify; it proves only that Beam's own code calls the refresh endpoint with the correct
  grant type and stores the result correctly.
- No automated gate proves the `google_ads_developer_token` field is wired correctly (Agent-Probe
  row) — manual code-review item until execute-agent adds it.
- No test in this plan proves the actual runtime behavior of Google's OAuth consent screen expiry
  policy (SPEC OQ3) — RESEARCH resolved this via docs-fetch, not a runtime probe; treated as
  authoritative per standard Google OAuth2 documentation, consistent with this plan's established
  docs-fetch verification pattern for external API contracts (same standard applied to A1's Data
  Manager API findings).

Gate: PASS (0 FAILs, 0 unresolved CONCERNs. All 7 supplement items named in the Inner Loop Refresh
Note — A1b micro-gate, B5/B6 refresh-token implementation, OAuth `access_type=offline`+
`prompt=consent`, OQ3 RESOLVED, E1b test coverage, the INNOVATE-skip record, and the registry's
second `ads_push.py` extension-point line — are each mechanically consistent with as-built code
(confirmed via direct file reads of `ads/base.py`, `ads/meta.py`, `ads/google.py`,
`ads/linkedin.py`, `ads_push.py`, `ad_connection.py`, `config.py`, `routers/ads.py`, `visitor.py`,
`csv_exporter.py`, and the blast-radius registry) and with the rest of the plan. Added Test Gates
row G7 to close a table-completeness gap (E1b's proving test now has an explicit criterion-id row
— the net-gate vacuous-green check passes: no developed behavior in this plan lacks a named
proving test or an explicit gap-resolution). The three remaining named residuals [A1b docs-fetch
itself, G2/E4 Hybrid sandbox smoke, developer-token secret-storage confirmation] are non-blocking,
carried via Test Gates gap-resolution B/C/D, not open CONCERNs requiring return-to-PLAN or further
user acceptance. No contradiction found between the PLAN-SUPPLEMENT edits and the rest of the
plan.)
Accepted by: N/A — Gate is PASS; no unresolved CONCERNs required session/user acceptance this
cycle. (Residuals carried forward from the prior CONDITIONAL/PASS cycles — A1b, G2/E4 Hybrid
smoke, developer-token secret-storage pattern — remain on record above as named gap-resolution
B/C/D items, not re-litigated.)

---

## Inner Loop Refresh Note

**Date:** 2026-07-26
**Trigger:** Phase 3 inner-loop Step 3 (PLAN-SUPPLEMENT) — RESEARCH findings folded in. INNOVATE
(Step 2) skipped with reason: mechanical/platform-dictated — Google's refresh-token grant type and
required OAuth-URL params (`access_type=offline`, `prompt=consent`) are fixed by the Data
Manager/Google Ads API contract, not a design choice among viable alternatives; no Decision
Summary was produced.

Sections changed this pass:
- Step A: new micro-gate A1b added (Google Ads API version + UserList `mutate` request-body/
  `login-customer-id`-header docs-fetch, blocking Step B/C endpoint code). A2 updated with the
  RESEARCH finding closing SPEC OQ3 (OAuth token lifetime/refresh — 7-day Testing-status expiry
  vs indefinite Published-status, standard OAuth2 semantics; no Google-specific deviation).
- Step B: new items B5 (`GoogleAdsProvider.refresh_tokens(refresh_token) -> AdOAuthTokens` —
  stored-refresh-token grant, docstring must state the structural difference from Meta's
  `fb_exchange_token(current_access_token)`; OAuth-URL `access_type=offline` + `prompt=consent`
  folded into B1) and B6 (provider-aware token selection at the `fresh_access_token` call site —
  `ads_push.py:146` must branch on `conn.provider == "google"` to pass the decrypted
  refresh_token instead of the access token) added.
- Step E: new item E1b added — unit coverage for the B5 refresh flow and the B6 call-site branch
  selection, including a Meta-path regression case.
- Blast Radius / registry: `ads_push.py`'s Phase-3 extension-point entry (already covering the
  EEA-exclusion branch) is extended by one line in `phase-blast-radius-registry.md` §Phase 3 to
  cover the B6 provider-aware refresh-token selection — a second, scoped touch to the same file.
  No other registry section changed.
- New `## Operator Checklist` section added: developer-token acquisition (Google Ads UI API
  Center), Test Account Access as the correct zero-approval default, Basic-approval as a separate
  later action, consent-screen publish-status confirmation before E4 Hybrid smoke (with the
  7-day Testing-status re-mint cycle noted), and optional brand-verification.
- All previously VALIDATE-confirmed facts (two-API architecture, EEA fail-closed filter,
  camelCase consent fields, ToS `ACCEPTED` field, async `requestId` shape) re-confirmed unchanged
  on this pass — no edits made to those sections.

This note triggers a fresh inner-PVL pass for this plan before EXECUTE (the existing
`## Validate Contract` above is `generated-by: outer-pvl`, dated 25-07-26 — older than this
note's 26-07-26 date, so per the orchestrator's Phase Program Pre-Routing Check Step 4b, "inner
R+I has run" = TRUE and PVL must re-run from V1). The outer-pvl contract above is retained for
audit trail only; it is superseded once the inner-pvl pass completes and writes its own contract.
