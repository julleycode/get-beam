---
phase: phase-3-google-live
date: 2026-07-26
status: COMPLETE_WITH_GAPS
feature: ads-audiences
plan: process/features/ads-audiences/active/ad-audiences_25-07-26/phase-3-google-live_PLAN_25-07-26.md
---

# Phase 3 — Google Live: EXECUTE report

**TL;DR** — Google Customer Match is implemented end to end (real OAuth with refresh-token
support, Google Ads `userLists:mutate` create + Data Manager `audienceMembers:ingest` populate,
fail-closed EEA exclusion on the Google path only). A1b docs-gate closed with primary sources.
All Fully-Automated gates green: 574 unit + 23 ads-integration, zero CRM/csv_exporter drift.
One known-gap carried forward: G2/E4 Hybrid sandbox smoke (no Google test-app credentials in
this environment). One forced deviation: `tests/unit/test_ads_stub_501.py` asserted Google IS a
stub — the exact thing this phase removes.

## What Was Done

**A1b docs-gate (closed before any endpoint code — full findings + source URLs recorded in the
plan's A1b slot):**
- (a) **Google Ads API version = `v25`.** Live unauthenticated probe: v17–v19 → 404 (sunset),
  v20–v25 → 401 (exist), v26+ → 404. Pinned as the single constant `GOOGLE_ADS_API_VERSION`.
- (b) **UserList create body:** `POST /v25/customers/{cid}/userLists:mutate` with
  `{"operations":[{"create":{name, description, membershipLifeSpan, crmBasedUserList:{uploadKeyType:
  "CONTACT_INFO", dataSourceType:"FIRST_PARTY"}}}]}` → `{"results":[{"resourceName":
  "customers/{cid}/userLists/{id}"}]}`. Sources: rpc reference for `MutateUserListsRequest`,
  `UserListOperation`, `CrmBasedUserListInfo`, `MutateUserListsResponse`, `MutateUserListResult`.
- (c) **`login-customer-id` NOT required** for direct-customer access (manager→client only,
  verbatim from `developers.google.com/google-ads/api/rest/auth`). Deliberately omitted;
  `developer-token` is sent on every Google Ads call.

**Step B — OAuth:** `get_oauth_url` carries `access_type=offline` + `prompt=consent` (without both
Google never issues a refresh token) and the `datamanager` + `adwords` scope pair, space-separated.
`exchange_code` performs the `authorization_code` grant, persists BOTH tokens, and best-effort
discovers the customer id via `customers:listAccessibleCustomers` (degraded, never fatal).
`refresh_tokens(refresh_token)` implements the `grant_type=refresh_token` grant with a docstring
explicitly contrasting Meta's `fb_exchange_token(current_access_token)` shape. Mock branches
preserved on every method.

**Step C — audience create + upload:** two-API sequence per plan. First push calls the Google Ads
API to create the UserList and takes `platform_audience_id` from `results[].resourceName`; repeat
push skips creation entirely. Population goes through Data Manager `audienceMembers:ingest` with
camelCase `consent{adUserData,adPersonalization}=CONSENT_GRANTED`,
`termsOfService.customerMatchTermsOfServiceStatus=ACCEPTED`, `encoding=HEX` (matches
`csv_exporter._sha256`'s hex digest), batched at the documented 10000-member cap. The ingest
`requestId` is logged but is never a source of the audience id.

**Step D — EEA exclusion:** `EEA_COUNTRY_CODES` (EU-27 + IS/LI/NO; UK excluded post-Brexit) and
`exclude_eea_rows()` added to `ads_push.py`, wired at exactly ONE call site behind
`if provider == "google":`, running strictly after the shared safety-filter chain. **Fail-closed:**
null/blank/missing country is treated as EEA-ambiguous and dropped. Excluded rows fall out as
ordinary `skipped` — no response-shape change, no `routers/ads.py` edit needed.

**Step B6 — provider-aware refresh credential:** `fresh_access_token` now passes the decrypted
`conn.refresh_token` when `provider == "google"` and the decrypted access token otherwise. The
existing `getattr` refresher guard is unchanged; a Google connection with no stored refresh secret
returns the stale token instead of calling refresh.

**Step E — tests:** `tests/unit/test_ads_google.py` (24 cases incl. E1b both legs + a Meta-path
regression), `tests/unit/test_ads_eea_exclusion.py` (G4 + G5 fail-closed + provider-scope guard),
`tests/integration/test_ads_google_live.py` (G1 callback, G3 repeat-push id provenance, G4
end-to-end payload assertion).

## What Was Skipped or Deferred

- **E4 / G2 — Hybrid sandbox smoke:** not run. No Google Cloud test-app credentials or Google Ads
  test account in this environment. Pre-declared known-gap in the validate contract
  (gap-resolution D); must run once before the phase can be marked ✅ VERIFIED.
- **D3 — future-enhancement documentation:** recorded in Backlog below (options (a) pixel-consent
  mapping and (b) manual site-level attestation), explicitly out of scope for this phase.
- **`tasks/ads_tasks.py` / `routers/ads.py` extension points:** declared but NOT used — no
  Google-specific task leg or response-shape change turned out to be necessary. Zero edits, as the
  registry anticipated ("read-only awareness, not an edit, unless RESEARCH finds otherwise").
- **Frontend / Playwright:** zero `apps/web` files touched, so no `tsc --noEmit` or e2e run applies.

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| G1, G3, G4(int) | `pytest tests/integration/test_ads_google_live.py -m integration -q` | **3 passed** |
| G1/G3 + Meta regression | `pytest tests/integration -k ads -m integration -q` | **23 passed, 0 failed** |
| G4, G5, G7 | `pytest tests/unit -k "ads_google or ads_eea_exclusion" -m unit -q` | **30 passed** |
| Full unit lane | `pytest tests/unit -m unit -q` | **574 passed, 2 skipped, 1 warning** |
| G6 CRM/csv drift | `git diff --stat main -- <crm+csv_exporter paths>` | **empty output** (clean) |
| G2 (Hybrid) | Google sandbox manual smoke | **NOT RUN** — known-gap, no credentials |
| Agent-Probe (developer-token) | code review of `config.py` + `google.py` wiring | **Promoted to automated** — `test_developer_token_header_is_sent_on_google_ads_calls` asserts the header is sent and that `login-customer-id` is absent |

Note: the integration run emits a `RuntimeError: Event loop is closed` line during redis teardown.
Pre-existing harness noise (documented in the tests context), not a test failure — the run reports
3 passed / 23 passed.

## Plan Deviations

1. **`tests/unit/test_ads_stub_501.py` modified (not in Phase 3's registry entry).**
   Within-blast-radius, forced by this phase's own deliverable: the file asserted that `google`
   raises `NotImplementedError`, which is precisely what Phase 3 removes. Phase 2 hit the identical
   situation with `meta` and resolved it by narrowing the same file, appending a registry note at
   EXECUTE time — this follows that precedent exactly. Resolution keeps real coverage rather than
   deleting it: the router's 501 mapping is now proven against a SYNTHETIC stub provider (the
   mapping is still live code), and both providers' contract flips are asserted explicitly. No
   coverage lost; flag-off 501 remains covered by `test_ads_flag_off_501.py`.
2. **No `tasks/ads_tasks.py` / `routers/ads.py` edits** — declared extension points went unused
   (a narrowing, not an expansion).
3. **Observation, NOT a deviation:** the Data Manager discovery document (revision 20260722, read
   live this session) now exposes `accountTypes.accounts.userLists.create` — a capability absent at
   VALIDATE's 25-07-26 fetch, which is why the plan locked the two-API architecture. Implemented as
   planned (Google Ads API creates the list). A future phase could collapse this to a single API;
   changing it here would have been an unapproved architecture deviation.

## Test Infra Gaps Found

- No shared test double exists for Google's async `requestId` → `requestStatus:retrieve` polling
  shape. Not needed this phase (v1 is fire-and-forget on the ingest ack, matching Meta's stance),
  so none was built. If a later phase adds terminal-status polling, factor a shared two-step mock
  helper — the note already carried in the plan's Test Infra Improvement Notes still stands.
- `tests/integration` redis teardown noise (`Event loop is closed`) is pre-existing and unrelated.

## Backlog (D3 — future enhancements, deliberately out of scope)

- **(a) Pixel-consent mapping:** capture per-visitor `ad_user_data` / `ad_personalization` consent
  at the pixel and forward real per-member consent, replacing blanket EEA exclusion.
- **(b) Manual site-level attestation:** let an operator attest that their own consent collection
  covers Google's requirement, unlocking EEA rows per site.
Both would let EEA rows be pushed with a meaningful consent determination; neither is safe today.

## Closeout Packet

- **Selected plan:** `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-3-google-live_PLAN_25-07-26.md`
- **Finished:** A1b, A1, A2, B1–B6, C1–C2, D1–D3, E1, E1b, E2, E3.
- **Verified:** all Fully-Automated gates (G1, G3, G4, G5, G6, G7) plus the promoted developer-token
  probe. **Unverified:** G2/E4 Hybrid sandbox smoke.
- **Remaining cleanup:** registry status annotation, umbrella `## Current Execution State` update,
  commit.
- **Classification:** `Keep in active/testing` — code-complete and EVL-ready, but per the plan's own
  Phase Completion Rules it cannot be ✅ VERIFIED until the G2 Hybrid smoke is recorded.
- **Follow-up stubs created:** none as separate files; the G2/E4 gap is already a named
  gap-resolution-D residual in the validate contract, and D3's items are recorded above.
- **CONTEXT_PARTIAL:** none.
- **Safety posture unchanged:** `ad_audiences_enabled` still defaults `False`; no migration added,
  none needed; no new secret-handling mechanism (`google_ads_developer_token` follows the existing
  `*_client_secret` field + whitespace-strip-validator pattern).

## Forward Preview

**Test Infra Found:** unit lane `.venv/bin/python -m pytest tests/unit -m unit -q` (~15s, no deps);
integration needs local PG 5432 + Redis 6379, both up in this environment. `.venv/bin/pytest` is
broken (stale shebang) — always use `.venv/bin/python -m pytest`.

**Blast Radius Changes:** `apps/api/services/ads/google.py` (rewritten, Phase-3-owned),
`apps/api/services/ads_push.py` (2 granted extension points used), `apps/api/config.py` (+1 granted
field), `tests/unit/test_ads_stub_501.py` (forced flip, see Deviations), 3 new test files. Declared
extension points on `tasks/ads_tasks.py` and `routers/ads.py` were NOT used.

**Commands to Stay Green:**
```
.venv/bin/python -m pytest tests/unit -m unit -q
.venv/bin/python -m pytest tests/integration -k ads -m integration -q
git diff --stat main -- apps/api/services/csv_exporter.py apps/api/services/crm/   # expect empty
```

**Dependency Changes:** none. No new pip package — `httpx` + `tenacity` only, matching the repo's
no-SDK convention (deliberately no `google-ads` package).
