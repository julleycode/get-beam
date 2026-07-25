---
name: plan:ad-audiences-spec
description: "Product-discovery SPEC for Ad Audiences — OAuth-connect ad channels and push segments as audiences directly, replacing manual CSV upload for Meta and Google"
date: 25-07-26
feature: ads-audiences
---

# Ad Audiences — SPEC

## Summary

Today, turning an identified-visitor segment into an ad-platform audience means downloading a
CSV and manually uploading it inside Meta Ads Manager, Google Ads, or LinkedIn Campaign
Manager — a slow, easy-to-forget, and disconnected step. This feature lets a user connect
their ad accounts to Beam once (the same one-click OAuth flow already used for CRMs) and then
push a segment straight into a live ad audience with one click. The user still gets the CSV
fallback for anything not yet connected. The Connectors page is reorganized so "Ad Audiences" is
the surface for both the new direct-push flow and the existing CSV download, and the
mislabeled "Import from CRM" tab is renamed to "Exclude List" to match what it actually does
(a suppression list, not a CRM import).

## User Stories / Jobs To Be Done

1. **As a Beam user with a Meta ad account**, I want to connect my Meta Business account once, so
   that I can push any segment straight into a Meta Custom Audience without downloading and
   re-uploading a CSV.
2. **As a Beam user with a Google Ads account**, I want to connect my Google Ads account once, so
   that I can push a segment into Google Customer Match the same way.
3. **As a Beam user who hasn't connected an ad account yet**, I want to still download a CSV for
   any of the three platforms (Meta, Google, LinkedIn), so that I'm never blocked from using ads
   just because a live connection isn't set up.
4. **As a Beam user who already pushed a segment to an ad platform**, I want to push it again
   after the segment's membership changes, so that my ad audience stays reasonably current
   without needing to disconnect and reconnect.
5. **As a Beam user**, I want to see the status of each ad-platform connection (connected, error,
   not connected) and be able to disconnect it, so that I stay in control of what Beam is
   authorized to do on my ad accounts.
6. **As a Beam user interested in LinkedIn**, I want to see that LinkedIn is "coming soon" rather
   than a broken or missing option, so that I know the capability is planned and I'm not left
   guessing.
7. **As a Beam user going to the "Exclude List" tab**, I want the tab name to describe what it
   actually does (people to exclude from targeting), so that I don't confuse it with syncing data
   in from a CRM.

## What The User Wants (Behavioral Outcomes)

- The Connectors page's first tab is retitled to reflect its real job: preparing and sending
  audiences to ad platforms (CSV download stays inside this tab, unchanged).
- Inside that tab, each supported ad platform (Meta, Google, LinkedIn) shows a connection card:
  connect button, or — once connected — a status badge, a "push segment" action, and a
  disconnect action. This mirrors the existing "Connect CRM" experience the user already knows.
- Clicking "Connect" for Meta or Google sends the user through that platform's standard OAuth
  consent screen and returns them to Beam with a clear success or failure message.
- Clicking "Push segment" lets the user pick one of their segments and confirms before sending;
  the user sees a result summary (how many contacts were matched/queued, and if the segment
  is too small for the platform's minimum, a warning before they push).
- Re-pushing an already-pushed segment updates the same ad audience rather than creating a
  duplicate.
- Disconnecting an ad account revokes Beam's access to that platform for the site and clears the
  connection status.
- LinkedIn's card shows a disabled "coming soon" state — visible so the user knows it's on the
  roadmap, not clickable, and CSV export for LinkedIn keeps working exactly as it does today.
- Only visitors that are safe to contact by Beam's existing rules (opted out, agent-derived,
  do-not-sell, bounced, etc. all excluded) are ever included in a pushed audience — this is
  invisible to the user except that push counts will be lower than raw segment size, matching
  today's CRM-push and CSV-export behavior.
- The third tab is renamed "Exclude List" and its content and behavior (upload/clear a
  known-contacts CSV used to suppress overlap) do not change.
- This whole feature is invisible/off until Beam turns it on for a site — until then, the page
  looks and behaves exactly as it does today (CSV export, Connect CRM, and the renamed tab).

## Flow / State Diagram

```
Connectors page
 ┌─────────────────────────────────────────────────────────────┐
 │ [Ad Audiences] [Connect CRM] [Exclude List]                  │
 └─────────────────────────────────────────────────────────────┘

Ad Audiences tab
 ┌─────────────────────────────────────────────────────────────┐
 │  Meta Custom Audiences        [Connect]                      │
 │  Google Customer Match        [Connect]                      │
 │  LinkedIn Matched Audiences   [Coming soon] (disabled)        │
 │  ───────────────────────────────────────────────────────────│
 │  Or: download a CSV for any of the 3 platforms (unchanged)   │
 └─────────────────────────────────────────────────────────────┘

Connect flow (per provider, Meta/Google only):
  [Connect] click
      │
      ▼
  Beam redirects to provider OAuth consent screen
      │
      ├── user approves ──► redirected back to Beam
      │                         │
      │                         ▼
      │                    connection saved (status=connected)
      │                    card now shows: status badge, [Push segment], [Disconnect]
      │
      └── user cancels/denies ──► redirected back to Beam
                                     │
                                     ▼
                              error message shown, no connection saved

Push flow (once connected):
  [Push segment] click
      │
      ▼
  pick a segment ──► confirm dialog
      │                  │
      │      segment below platform minimum size?
      │                  │
      │        yes ──► warning shown, user may still confirm or cancel
      │                  │
      │                  ▼ (confirm)
      ▼
  Beam applies safety filters (do_not_email, agent-origin exclusion,
  do_not_sell suppression — same gate as CRM push / CSV export)
      │
      ▼
  Beam hashes remaining contacts and sends to the ad platform
  (create audience if first push, else update the existing one)
      │
      ▼
  result shown: pushed / skipped counts, or a queued-in-background message

Disconnect flow:
  [Disconnect] click ──► confirm ──► connection + tokens removed, status cleared

LinkedIn card:
  always shows "Coming soon", never clickable; CSV download still works for LinkedIn.
```

## Acceptance Criteria (Testable Outcomes)

1. **Ad Audiences tab exists and CSV download still works unchanged.**
   The first Connectors tab is labeled for ad-audience activation (not "Export"); selecting a
   segment and platform and downloading a CSV works exactly as it does today for Meta, Google,
   and LinkedIn.
   proven by: Fully-Automated Playwright e2e — tab renders, CSV download request fires with
   unchanged query params.
   strategy: Fully-Automated

2. **Meta connect flow completes and shows connected status.**
   A user with a mocked/sandboxed Meta OAuth flow can click Connect, complete consent, and see
   their connection show status "connected" with a real account label.
   proven by: Fully-Automated integration test against a mocked Meta OAuth callback (mirrors
   existing CRM OAuth callback test pattern) + Hybrid manual smoke against Meta's real sandbox
   app before first production enable.
   strategy: Hybrid

3. **Google connect flow completes and shows connected status.**
   Same as AC2, for Google Ads / Data Manager API OAuth.
   proven by: Fully-Automated integration test against a mocked Google OAuth callback + Hybrid
   manual smoke against a Google test-account sandbox (available with zero approval per
   research) before first production enable.
   strategy: Hybrid

4. **Pushing a segment only sends safety-cleared contacts.**
   A segment containing a mix of emailable, do-not-email, agent-derived, and do-not-sell-flagged
   visitors results in an ad-platform push that includes only the emailable, non-suppressed
   subset — identical filtering to today's `_get_segment_visitors` used by CSV export and CRM
   push.
   proven by: Fully-Automated integration test — seed a segment with all 4 visitor classes,
   assert only the emailable/non-suppressed subset appears in the outbound push payload.
   strategy: Fully-Automated

5. **Only SHA256-hashed identifiers ever leave Beam.**
   The outbound payload to any ad platform never contains a plaintext email or other raw PII —
   every identifier is lowercased, trimmed, and SHA256-hashed before being sent, matching the
   existing CSV-export hashing implementation.
   proven by: Fully-Automated unit test asserting the outbound payload builder never contains an
   `@` character or matches an email regex.
   strategy: Fully-Automated

6. **Re-pushing a segment updates rather than duplicates the audience.**
   Pushing the same segment to the same connected platform a second time (after membership
   changes) updates the existing ad-platform audience object rather than creating a second one.
   proven by: Fully-Automated integration test — push twice, assert the platform-side audience
   ID captured on the connection record is reused on the second call.
   strategy: Fully-Automated

7. **Small-segment warning shown before push.**
   When the visitor count of a segment (after safety filtering) is below the platform's stated
   minimum audience size, the user sees a warning before confirming the push, but is not
   blocked from proceeding.
   proven by: Fully-Automated Playwright e2e — mock a small segment, assert warning text renders
   in the confirm dialog before the push button is enabled/clicked.
   strategy: Fully-Automated

8. **Disconnect revokes access and clears status.**
   Clicking Disconnect on a connected ad platform removes the stored connection/tokens and the
   card reverts to the unconnected "Connect" state.
   proven by: Fully-Automated integration test — disconnect endpoint call, assert connection row
   status/tokens cleared and a subsequent list call shows no active connection.
   strategy: Fully-Automated

9. **LinkedIn is visibly disabled, not broken or missing.**
   The LinkedIn card renders in a disabled "coming soon" state; no click handler fires; CSV
   export for LinkedIn is unaffected.
   proven by: Fully-Automated Playwright e2e — assert LinkedIn button has `disabled` attribute
   and CSV download for `platform=linkedin` still returns 200.
   strategy: Fully-Automated

10. **Feature is off by default and fully mock-mode capable.**
    With the feature flag off, the Connectors page renders exactly as it does today (three tabs:
    Export/Connect CRM/Import — pre-rename baseline). With the flag on and `MOCK_EXTERNAL_APIS=true`,
    every OAuth connect and push flow completes deterministically with no live network calls.
    proven by: Fully-Automated — one integration test with flag off asserting old route/behavior
    unchanged; one integration test suite with flag on + mock mode asserting deterministic
    connect/push outcomes.
    strategy: Fully-Automated

11. **Per-site push rate limit is enforced.**
    Ad-audience pushes are capped per site per hour, matching the existing CRM push rate-limiter
    pattern; exceeding the cap returns a clear rate-limited response instead of silently queuing
    forever or erroring opaquely.
    proven by: Fully-Automated unit test on the ads rate limiter — Nth push within the window is
    rejected with a rate-limit error.
    strategy: Fully-Automated

12. **Exclude List tab rename is cosmetic only.**
    The third tab's label changes from "Import from CRM" to "Exclude List"; upload, count
    display, and clear-all behavior for the known-contacts list are unchanged.
    proven by: Fully-Automated Playwright e2e — tab label assertion + existing known-contacts
    upload/clear test cases pass unmodified.
    strategy: Fully-Automated

13. **Meta ToS acceptance / EEA-consent gaps surface as an explicit, visible state — not a silent failure.**
    If a push fails because of an unmet platform precondition (e.g. Custom Audience ToS not yet
    accepted on the ad account, or Google EEA consent fields not gathered), the user sees a
    specific, actionable error message rather than a generic failure or a silent drop.
    proven by: Agent-Probe — this depends on unverified live-provider error response shapes
    (see Open Questions); once the real error shape is confirmed, promote to Fully-Automated
    with a fixture of the real error payload.
    strategy: Agent-Probe

## Out Of Scope

- **LinkedIn Matched Audiences API push.** LinkedIn stays CSV-export-only in this version; the
  UI shows a disabled "coming soon" state. (Research: two sequential manual platform approvals,
  4wk–6mo timeline, no sandbox — not viable for this scope.)
- **Automatic / scheduled re-push (auto-sync).** The CRM connector has an `auto_push` precedent,
  but ad-audience pushes in this version are always a manual, user-initiated click. Scheduled
  sync is a future version.
- **Ads performance reporting** (spend, reach, conversion data pulled back from ad platforms).
  This feature only pushes audiences out; it does not read anything back.
- **Audience deletion propagation guarantees.** Disconnecting Beam's access does not guarantee
  the ad platform deletes the audience object on its side — Beam only revokes its own stored
  tokens/connection.
- **PII-at-rest encryption changes.** `IdentifiedVisitor.email` plaintext-at-rest status is
  unchanged by this feature; that is tracked separately in the active `pii-at-rest` plan.
- **Meta "Full Access" tier (managing other people's ad accounts).** This version only supports
  users connecting their own ad account under Meta's self-serve "Limited Access" tier.
- **Google production dev-token approval as a blocking dependency for the whole feature.**
  Google connect ships gated so that sandbox/test-account use works immediately; wider
  production rollout for a given site is a separate operational step (see Open Questions).

## Constraints

- Reuse `_get_segment_visitors`'s exact safety filter chain (do_not_email, agent-origin
  exclusion via `is_emailable_identity`, do_not_sell suppression) verbatim for every ad-platform
  push — no new or divergent filtering logic.
- Reuse the existing SHA256 lowercase+trim hashing implementation (`csv_exporter._sha256`) for
  every identifier sent to an ad platform.
- Every new external call (Meta, Google) must have a deterministic mock path gated by
  `MOCK_EXTERNAL_APIS=true`, matching every other external integration in the codebase.
- The feature ships behind a feature flag defaulting OFF (`ad_audiences_enabled` or equivalent),
  matching the `agent_detection_enabled` / `company_graph_enabled` precedent — enabling it in any
  real environment is a deliberate, separate operator action.
- Per-site push rate limiting is required, matching the existing `crm_rate_limiter.py` pattern.
- OAuth token storage must use the existing Fernet encryption service (`encryption.py`) — no new
  token storage mechanism.
- Multi-tenancy: every connection and push must be scoped through `Site.user_id == user.id`,
  matching every other tenant-scoped query in the codebase.
- UI must reuse the existing `CrmConnectPanel` interaction pattern (status badge, connect/push/
  disconnect actions, `ready: false` disabled-but-discoverable precedent for LinkedIn) rather
  than inventing a new interaction model.
- CSV export behavior for all three platforms must remain fully functional and unchanged
  regardless of ad-audience connection state.

## Open Questions

1. **Data Manager API request/response contract (Google).** The classic OfflineUserDataJobService
   is closed for new tokens; the replacement Data Manager API's exact endpoint shapes are
   unverified from source alone.
   Owner: next-phase (INNOVATE/PLAN research spike or feasibility probe).
   cost-class: needs-live-provider or docs-fetch (try docs-fetch first).

2. **Meta Custom Audience payload schema + per-ad-account ToS acceptance flow.** `POST
   /act_{id}/customeraudiences` + `/{id}/users` shapes are documented but the ToS-acceptance
   precondition/error flow (AC13) is unverified.
   Owner: next-phase.
   cost-class: needs-live-provider.

3. **Google OAuth token lifetime and refresh behavior** for the Data Manager API scope pairing.
   Owner: next-phase.
   cost-class: docs-fetch, escalate to needs-live-provider if docs are ambiguous.

4. **EEA consent sourcing for Google Customer Match.** Google requires both `ad_user_data` and
   `ad_personalization` consent fields GRANTED per upload, or EEA rows are silently dropped.
   Beam needs a decision on how it determines/attests a visitor's consent status before sending
   a push (e.g., derive from Beam's own pixel consent record, or require a manual site-level
   attestation from the user). This is a product/legal decision, not just a technical one.
   Owner: user (product decision) + next-phase (technical wiring).

5. **Minimum-audience-size exact thresholds per platform for the AC7 warning.** Meta ~1000
   practical (100 min technical), Google ~1000 approximate/secondary-sourced, LinkedIn N/A
   (out of scope). Confirm exact numbers to surface in the UI warning copy.
   Owner: next-phase (docs-fetch, low cost).

All open questions above are carried forward as backlog/next-phase research items, not blockers
to writing this SPEC — none require the user's product intent to be re-clarified; they are
implementation-facing unknowns appropriately deferred past SPEC into INNOVATE/PLAN research or a
feasibility probe.

## Background / Research Findings

**Internal (vc-research-agent, DONE):**
- The CRM connector stack is a fully reusable pattern for this feature: `oauth_state.py` (CSRF
  protection), `encryption.py` (Fernet token encryption), `crm_rate_limiter.py` (per-site hourly
  cap), `services/crm.py` (connector registry), Celery async push via `tasks/crm_tasks.py`,
  per-method `MOCK_EXTERNAL_APIS` short-circuit, and the `crm-connect-panel.tsx` UI pattern
  (provider list with a `ready` flag giving a disabled-but-discoverable button for
  not-yet-wired providers — this is the exact precedent for LinkedIn's "coming soon" state).
- The safety choke point all pushes/exports must go through is
  `csv_exporter._get_segment_visitors()`: filters `do_not_email` (line ~65), `is_emailable_identity`
  including agent-origin exclusion (~79-83), `do_not_sell` suppression (~87), and optional
  known-contacts exclusion. Both CSV export and CRM push already funnel through this — ad
  push must too.
- `csv_exporter._sha256()` already implements the exact customer-match hashing spec
  (lowercase + trim + SHA256), currently used for Meta CSV export — directly reusable.
- `IdentifiedVisitor.email` is plaintext-readable today; PII-at-rest encryption is a separate,
  already-active plan (`pii-at-rest_22-07-26`) — noted as a dependency risk, not something this
  feature blocks on or changes.
- Net-new work identified: an `AdConnection` model (needs `ad_account_id`, `audience_id`,
  `business_id` beyond what the CRM connection shape carries), `services/ads/{meta,google,
  linkedin}.py`, an `ads_push.py` service, `ads_rate_limiter.py`, `tasks/ads_tasks.py`, a new
  router, frontend panel + tab, three env credential trios, and a feature flag defaulting OFF.
  (These are implementation nouns surfaced by research for downstream INNOVATE/PLAN awareness —
  not decisions made in this SPEC.)
- No prior plans or backlog items exist anywhere in the repo for this feature — confirmed clean
  slate.

**External (vc-research-agent, DONE_WITH_CONCERNS):**
- **Meta Custom Audiences**: self-serve "Limited Access" tier is reachable with a verified
  Business Manager + live app — sufficient for users connecting their own ad account. Requires
  `ads_management` + `business_management` scopes. Audience creation is
  `POST /act_{id}/customeraudiences` (subtype CUSTOM), member upload is
  `POST /{audience_id}/users` (SHA256, async — requires polling). Practical minimum audience
  size ~1000 (100 technical minimum). "Full Access" tier (managing other people's accounts)
  needs 500 calls over 15 days of history plus App Review — not needed for this version.
- **Google Customer Match**: the classic OfflineUserDataJobService is closed for new tokens as
  of 01-04-2026 — the **Data Manager API** (new `datamanager` scope + legacy `adwords` scope) is
  the only path forward, and its endpoint-level contract is unverified pending a direct docs
  fetch. A production dev-token (Basic tier) approval is required for live use, but a
  test-account sandbox works immediately with zero approval — this is the natural place to
  build and demo against first. EEA rows require both `ad_user_data` and `ad_personalization`
  consent fields GRANTED per upload or they are silently dropped. Rate limits: 100k requests/day,
  10k members/request. Minimum serving size ~1000 (secondary-sourced, needs confirmation).
- **LinkedIn Matched Audiences**: hardest path — two sequential manual approvals (Marketing
  Developer Platform, typically 4 weeks to 4 months, frequently rejected without disclosed
  reason; then DMP Segments access on top, up to 60 more days). No sandbox exists. Tokens are
  60-day-lived with no refresh token until fully approved. Minimum audience size 300 members.
  → Decision reflected in this SPEC: LinkedIn stays CSV-export-only for v1, with a disabled
  "coming soon" connect button using the existing `ready: false` CRM-panel precedent.
- All three platforms officially support manual CSV upload as a fallback, and Beam's existing
  exporters (`export_meta_csv`, `export_google_csv`, `export_linkedin_csv`) already match each
  platform's expected format — this fallback path is preserved unchanged by this feature.
- Unverified items carried into Open Questions: Data Manager API endpoint contract, Meta
  audience-creation payload schema + ToS-acceptance error flow, Google OAuth token lifetime,
  LinkedIn rate limits (N/A — out of scope), and how Beam sources/attests EEA consent status for
  Google pushes.

**User intent captured this session:**
- Rename the "Export" tab into the ad-audience activation surface (CSV stays inside it).
- Add OAuth-link for ad channels with a direct audience-push flow, mirroring the existing
  "Connect CRM" panel UX exactly.
- Also approved as an adjacent, low-risk rename: the mislabeled "Import from CRM" tab (which is
  actually a suppression/known-contacts list) becomes "Exclude List". Noted here as in-scope but
  intentionally small/cosmetic relative to the ad-audiences work.
