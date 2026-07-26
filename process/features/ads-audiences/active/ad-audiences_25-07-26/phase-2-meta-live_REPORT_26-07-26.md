---
phase: phase-2-meta-live
date: 2026-07-26
status: COMPLETE_WITH_GAPS
feature: ads-audiences
plan: process/features/ads-audiences/active/ad-audiences_25-07-26/phase-2-meta-live_PLAN_25-07-26.md
---

# Phase 2 — Meta Live · EXECUTE report

**TL;DR** — All 20 of 21 checklist items done (E3 Hybrid sandbox smoke is env-blocked). Meta's
real Graph API path is implemented behind an unchanged mock short-circuit; 24 new unit tests and
4 new integration tests pass, frontend typechecks clean. Three env-gated known-gaps carry
forward: the Meta sandbox smoke (no developer app), the AC7 Playwright legs (Clerk auth harness),
and AC13's exact JSON error code/subcode. `ad_audiences_enabled` remains OFF. No migration was
needed and none was written.

## What Was Done

### Step A — real Meta OAuth (`services/ads/meta.py`)
- **A1** Graph API version pinned as a single module constant `GRAPH_API_VERSION = "v25.0"`, with
  an inline "recheck before ~2028-02" upgrade note. Re-confirmed live at EXECUTE time: Meta's own
  Custom Audience users reference page serves its example request with `&version=v25.0`.
- **A2** `get_oauth_url` builds the real dialog URL from the version constant, with
  `scope=ads_management,business_management` (comma-separated, asserted in a test) and the
  existing `oauth_state` token reused verbatim.
- **A3** `exchange_code` is a genuine TWO-STEP exchange: auth code → short-lived token → long-lived
  token via `grant_type=fb_exchange_token`. Only the LONG-lived expiry is persisted (a test
  asserts the stored expiry is >50 days, which fails if the 1h short-lived value leaks through).
  `/me/adaccounts` discovery is best-effort — a lookup failure degrades to a still-usable
  connection instead of failing the whole connect.
- **A3b** `refresh_tokens` added as a concrete method on `MetaAdsProvider` only. `services/ads/base.py`
  was NOT touched (frozen this phase). Docstring states explicitly that the parameter is the
  current not-yet-expired access token, not a refresh secret.
- **A3c** `fresh_access_token(db, conn)` added to `ads_push.py`, called immediately before
  `create_or_update_audience`. The refresher lookup is `getattr`-guarded, so Google/LinkedIn
  connections (no such method) are skipped rather than raising `AttributeError`. Refresh failure
  sets `status="error"` + sanitized `last_error` and falls back to the stale token.
- **A4** Every method keeps its `if settings.mock_external_apis:` short-circuit first.

### Step B — Custom Audience create + upload
- **B1** First push creates via `POST /act_{id}/customaudiences` (`subtype=CUSTOM`,
  `customer_file_source=USER_PROVIDED_ONLY`); a repeat push reuses `link.platform_audience_id`
  and skips creation entirely (asserted by call-count, not just by returned id).
- **B1b** See "B1b answer" below — resolved from primary docs.
- **B2** Member upload posts a single-key `EMAIL_SHA256` payload with `is_raw: true`. Only
  digests are sent; this module never hashes or sees plaintext.
- **B3** Fire-and-forget: Meta's synchronous ack (`num_received` / `num_invalid_entries`) is the
  terminal result. No polling task added. See Known Limitation below.
- **B4** No edit needed — Phase 1's `ads_tasks.push_segment_to_ads_task` already routes through
  `ads_push.push_segment_to_ads`, which now carries the real Meta logic. One fewer file touched
  than the plan anticipated.

### Step C — AC13 ToS-precondition surfacing
- Dedicated `MetaAudienceTermsError` raised when a Graph 400 matches the ToS signature. The
  message names the specific precondition and carries the per-account remediation URL.
  `ads_push.push_segment_to_ads` catches it in a branch ABOVE the generic sanitizer so the
  actionable copy survives to the user instead of collapsing into "Provider returned HTTP 400".
- The exact JSON `code`/`subcode` stays unconfirmed and is marked with a
  `# TODO Agent-Probe:` comment, exactly as the plan required.

### Step D — AC7 min-size warning
- **D2** `PushSegmentOutcome`, `PushAdSegmentResult` (backend) and `AdPushResult` (frontend type)
  gained additive `below_minimum` / `minimum_threshold` fields; the router returns them. The
  panel's post-push message now derives its copy from `minimum_threshold` rather than a hardcoded
  literal. Warning copy names BOTH numbers (technical 100 via new `MIN_AUDIENCE_MATCHABLE`,
  practical 1000 via the existing `MIN_AUDIENCE_SIZE`).
- **D2b** New PRE-push warning in the confirm dialog, driven by the already-available
  `Segment.visitor_count`, rendered only when the selected segment is below the threshold. It is
  labelled approximate and does not block: both "Push now" and "Cancel" stay enabled.
- The panel's previously hardcoded "~1,000 matched contacts" dialog string is now built from the
  frontend threshold constants.

### Step E — tests
- **E1** `tests/unit/test_ads_meta.py` (new, 24 tests) — version pinning, OAuth URL shape,
  two-step exchange, long-lived-expiry storage, refresh semantics, create-vs-reuse branch,
  `EMAIL_SHA256` payload, invalid-entry accounting, ToS detector/message, retry policy, and the
  four `fresh_access_token` guard cases (including the no-`refresh_tokens` provider).
- **E2** `tests/integration/test_ads_meta_live.py` (new, 4 tests) — real OAuth callback handler
  driven with a real state token, connect → push → repeat-push audience reuse, the AC7 structured
  fields, and the AC13 actionable-message path. Every Meta call is mocked; nothing leaves the process.
- **E4** `apps/web/e2e/connectors-ads-push-warning.spec.ts` (new, 2 legs) — pre-push dialog warning
  + push-not-blocked, and post-push copy built from `minimum_threshold`. Written and typechecked;
  both legs currently SKIP in this environment (see Known Gaps).
- **E5** Agent-Probe judgment recorded below.

## What Was Skipped or Deferred

- **E3 — Hybrid Meta sandbox smoke.** Not run. Requires a real Meta developer app in LIVE mode + a
  verified test Business Manager, neither of which exists in this environment. This was named in
  the plan's own "Blockers That Would Justify BLOCKED Status" as an explicit non-blocker.
  Deferred to before-first-production-enable. Procedure to run it is the plan's
  "Operator Env-Prereq Checklist".
- **Zero migrations.** Confirmed none needed — this phase added no model or column. Per the
  instruction, no migration was written.

## Test Gate Outcomes

Verbatim, as run:

```
$ git diff --stat main -- apps/api/models/crm_connection.py apps/api/routers/crm.py \
    apps/api/services/crm.py apps/api/services/crm/ apps/api/services/crm_push.py \
    apps/api/services/crm_rate_limiter.py apps/api/tasks/crm_tasks.py apps/api/services/csv_exporter.py
 apps/api/routers/crm.py | 27 +++++++++++++++++++++++++--
 1 file changed, 25 insertions(+), 2 deletions(-)
```
**Verdict: PASS (zero drift attributable to this phase).** The single non-empty entry is the
concurrent `capacity-hardening` program's uncommitted `celery_worker_enabled` truth-table edit —
it was already present in `git status` before this session began, and its content
(`crm_async_push` / worker gating) is unrelated to Meta ads. Per the standing lesson about
concurrent-program drift, the diff CONTENT was inspected rather than treated as a bare
presence signal. `csv_exporter.py` appeared in an earlier run of this gate and has since been
committed by the concurrent session; it is likewise not this phase's change.

```
$ .venv/bin/python -m pytest tests/unit -k ads_meta -m unit -q
24 passed, 1080 deselected in 1.72s
```

```
$ .venv/bin/python -m pytest tests/integration -k ads_meta -m integration -q -p no:randomly
4 passed, 396 deselected in 4.83s
```

```
$ .venv/bin/python -m pytest tests/unit -k ads -m unit -q      # whole ads unit surface
48 passed, 1056 deselected in 8.84s

$ .venv/bin/python -m pytest tests/unit -m unit -q             # full unit regression
539 passed, 2 skipped, 563 deselected, 1 warning in 8.55s
```

Per-file ads integration sweep (clean schema between files — see Test Infra Gaps):
```
test_ads_meta_live     4 passed in 12.34s
test_ads_flag          7 passed in 14.20s
test_ads_warning       3 passed in 3.40s
test_ads_safety_filter 2 passed in 2.02s
test_ads_upsert        2 passed in 3.64s
```

```
$ cd apps/web && npx tsc --noEmit
(no output — clean)
```

```
$ cd apps/web && npx playwright test connectors-ads-push-warning
  ✓  1 [setup] › e2e/auth.setup.ts:11:6 › authenticate (13.3s)
  -  2 [chromium] › connectors-ads-push-warning.spec.ts › small segment shows an approximate warning before the push is confirmed
  -  3 [chromium] › connectors-ads-push-warning.spec.ts › post-push message uses the backend's minimum_threshold, not a hardcoded number
  2 skipped
  1 passed (55.4s)
```
**Verdict: env-gated, NOT green.** Both assertion legs skipped. Root cause diagnosed, not
assumed: a throwaway debug spec showed the connectors page redirects to
`https://sweet-goat-71.accounts.dev/sign-in` — Clerk middleware does not accept the legacy
`auth_token` localStorage seed the e2e harness plants. This is the G2 auth-harness gap already
recorded in Phase 1's known-gaps, not a defect in this phase's code. The spec is written so that
it SKIPS only when the panel fails to render at all; if the page renders and the warning is
missing, it fails loudly rather than passing vacuously.

## B1b answer + source

**Question:** does `POST /{audience_id}/users` expect `EMAIL` or `EMAIL_SHA256` in `schema`?

**Answer: `EMAIL_SHA256`** for the single-key hashed-email upload Beam performs. The short
`EMAIL` spelling is valid only inside the MULTI-key array form (`["EMAIL","LN","FN","ZIP"]`),
which Beam does not use. Both forms are described in the same parameters table, which is why
secondary sources conflict.

**Source — PRIMARY Meta docs**, `POST /{custom_audience_id}/users` Parameters table:
`https://developers.facebook.com/docs/marketing-api/reference/custom-audience/users/`

> `schema` _string_ — `EMAIL_SHA256`, `PHONE_SHA256`, `MOBILE_ADVERTISER_ID`. One can also pass
> an array of multiple keys for multi-key match… The multi-key array is of the form
> `["EMAIL", "LN", "FN", "ZIP"]`

**Fetch note (residual uncertainty: none, but method disclosed):** `developers.facebook.com`
returns HTTP 400 to plain curl in this environment, and no WebFetch/WebSearch tool was available.
The page was retrieved through the `r.jina.ai` text-extraction proxy pointed at that exact primary
URL — the same primary document rendered to text, not a third-party summary or blog. Two
independent corroborations came from the same fetch: the page's live example request carries
`&version=v25.0` (re-confirming A1), and the DELETE `/users` section repeats the identical schema
table.

Two further values were confirmed the same way and used in the implementation:
- `customer_file_source: "USER_PROVIDED_ONLY"` and `subtype: "CUSTOM"` — from the Custom Audience
  reference page's response example and the ToS page's eligible-types table.
- ToS remediation URL — the docs give
  `https://business.facebook.com/ads/manage/customaudiences/tos/?act=<AD_ACCOUNT_ID>`, i.e. an
  `?act=` query param. The plan had written `?{ACCOUNT_ID}` (no param name); the docs-confirmed
  form is what shipped. Minor correction, recorded here rather than silently applied.

## Plan Deviations

All within blast radius; none touched a hard-forbidden file.

| # | Deviation | Why | Impact |
|---|---|---|---|
| 1 | `apps/api/tasks/ads_tasks.py` NOT edited (plan listed it as an edit target for B4) | Phase 1's task already delegates to `ads_push.push_segment_to_ads`, which now holds the real Meta logic. Adding a Meta-specific leg would have been dead code. | Strictly smaller blast radius than planned. |
| 2 | Two files edited that the plan's Blast Radius did not name: `apps/api/schemas/ads.py` and `apps/web/src/lib/api-types.ts` | The router cannot return `below_minimum`/`minimum_threshold` without the Pydantic model carrying them, and the panel cannot read them without the TS interface. Both are the mechanical other half of already-declared extension points. | Additive fields only; TS fields optional so no caller breaks. Both declared in the registry before/alongside the edit. |
| 3 | `tests/unit/test_ads_stub_501.py` narrowed from `["meta","google"]` to `["google"]`, and its meta leg flipped from "raises NotImplementedError" to "returns a real facebook.com URL" | The test asserted meta IS a stub — precisely what this phase exists to stop being true. It went red the moment A2 landed. | Google's stub-501 coverage unchanged; meta's flag-off 501 still covered by `test_ads_flag_off_501.py`. The flip is asserted positively so a regression back to stub fails loudly. Declared in the registry. |
| 4 | ToS URL uses `?act=<id>` rather than the plan's `?{ACCOUNT_ID}` | Docs-confirmed form (see B1b section). | More correct than planned. |

**E3 registry instruction — honoured in order.** The Phase 2 extension-point declaration for
`ads_push.py` was appended to `phase-blast-radius-registry.md` BEFORE any edit to that file, and
`git diff HEAD -- apps/api/services/ads_push.py` was re-run immediately beforehand to confirm the
concurrent capacity-hardening hunks were present; those hunks were built on top of, never
reverted.

## Test Infra Gaps Found

1. **Integration harness DB residue (T1-class, pre-existing, `harness-drift`).** The
   session's integration lane is unstable in this environment: `conftest.test_engine`'s teardown
   `drop_all` can fail on `DROP TABLE engagement_attributions` (already removed by a CASCADE),
   which aborts teardown BEFORE the `DROP TYPE` loop, leaving the `platform` enum behind and
   poisoning the next run with `duplicate key … pg_type_typname_nsp_index`. Confirmed
   pre-existing, not caused by this phase: untouched donor files (`test_ads_upsert.py`,
   `test_ads_safety_filter.py`) fail identically. **Every observed failure in this phase's own
   integration file was one of these two harness errors — never an assertion failure.** Workaround
   used: `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` between files, after which all 18 ads
   integration tests pass. Recommend hardening the teardown to be exception-tolerant per table.
2. **Playwright auth harness (G2, pre-existing).** Clerk rejects the localStorage JWT seed, so any
   e2e leg needing an authenticated dashboard page cannot run. Blocks both AC7 e2e legs.
3. **No DOM test runner in `apps/web`.** `vitest` exists but is node-environment only, with no
   jsdom/testing-library. There is therefore no non-Playwright way to prove the panel's warning
   logic. Deliberately NOT fixed here — adding a test dependency is out of this phase's scope.

## Known Limitations (product-level, by design)

- **Fire-and-forget push status (B3, locked v1 decision).** Meta's synchronous ack is treated as
  terminal. Counts surfaced to the user are Beam-side "matched/queued", never platform-confirmed
  audience size. No polling task exists; reconciliation is opportunistic only.

## Agent-Probe judgment — AC13 (E5)

**Scenario exercised:** a Graph 400 carrying `{"error": {"message": "Custom Audience Terms not yet
accepted"}}` driven through `_is_tos_error` → `MetaAudienceTermsError` → `push_segment_to_ads` →
`PushSegmentOutcome.errors[0]` and `conn.last_error`, asserted end-to-end in
`test_tos_precondition_failure_surfaces_the_actionable_message`.

**Message produced:**
> Meta rejected this push because this ad account hasn't accepted the Custom Audience Terms of
> Service yet. Accept them here, then try again:
> https://business.facebook.com/ads/manage/customaudiences/tos/?act=123

**Verdict: SPECIFIC and ACTIONABLE — meets the SPEC wording.** It names the exact precondition
(not "push failed"), attributes it to the ad account rather than to Beam, and gives a one-click
next step with the real account id interpolated. It is verifiably distinct from the generic branch
(the test asserts `"Provider returned HTTP" not in message`). It contains no PII.

**Residual, honestly stated:** this proves the mapping and the copy, NOT that Meta's real
unaccepted-ToS response actually carries this message text. The message-substring match is
best-effort; if Meta's live body differs, the error silently degrades to the generic sanitized
branch (fails safe — an unhelpful message, never a crash or a wrong push). Confirming the real
`code`/`subcode` needs one live sandbox call and remains the named Agent-Probe residual.

## Follow-up stubs created

None written to disk as new plan files. Three residuals should be folded into the existing
backlog note `process/features/ads-audiences/backlog/phase-1-docker-and-auth-known-gaps_NOTE_25-07-26.md`
at UPDATE PROCESS (it already tracks the same two env gaps from Phase 1):
1. E3 Meta sandbox smoke — before first production enable.
2. AC7 e2e legs — unblock when the Clerk Playwright auth harness is fixed (G2).
3. AC13 exact error `code`/`subcode` — upgrade to Fully-Automated once probed.

Plus one carried from the validate-contract, unchanged: promoting a shared
`AdsProvider.refresh_tokens` default (mirroring `CRMConnector`) belongs to whichever phase next
touches `services/ads/base.py`. Safe to defer — the `getattr` guard makes today's omission
harmless, and there is now a unit test pinning that behaviour.

## CONTEXT_PARTIAL items

`CONTEXT_PARTIAL: web docs tooling` — no WebFetch/WebSearch tool was available in this session and
`developers.facebook.com` blocks plain curl. All Meta docs facts were obtained via the `r.jina.ai`
text proxy against primary URLs. Facts are primary-sourced, but the retrieval channel is
non-standard and worth noting for reproducibility.

## Closeout Packet

- **Selected plan:** `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-2-meta-live_PLAN_25-07-26.md`
- **Finished:** 20 of 21 checklist items (A1–A4, B1–B4, C1–C2, D1–D2b, E1, E2, E4, E5).
- **Verified:** 24 unit + 4 integration tests green; full 539-test unit suite green; frontend
  typecheck clean; CRM/csv_exporter and frozen-ads-file drift gates both clean.
- **Still unverified:** Meta's real OAuth/token/upload behaviour (E3, needs sandbox); AC7 UI legs
  (needs auth harness); AC13 real error shape (needs live probe).
- **Cleanup remaining:** fold the three residuals into the backlog note; update
  `process/context/all-context.md`'s ads-audiences entry to reflect Phase 2 shipping; commit.
- **Classification: `Keep in active/testing`.** Code-complete and automated-tier green, but the
  plan's own Phase Completion Rules require every Verification Evidence row to have real recorded
  evidence before VERIFIED — the Hybrid (E3) and AC7-e2e rows do not. Not archivable yet.

## Forward Preview

**Test Infra Found.** Integration lane needs a clean `public` schema between files in this
environment (`DROP SCHEMA public CASCADE; CREATE SCHEMA public;` against `infra-postgres-1`,
db `retarget_agent_test`); the venv interpreter (`.venv/bin/python -m pytest`) is required, as the
`.venv/bin/pytest` shebang is broken. Playwright specs needing an authed dashboard page cannot run.

**Blast Radius Changes.** Phase 2 claimed three extra files beyond its original plan
(`schemas/ads.py`, `apps/web/src/lib/api-types.ts`, `tests/unit/test_ads_stub_501.py`) and released
one (`tasks/ads_tasks.py`, untouched). All four facts are recorded in
`phase-blast-radius-registry.md`. **Phase 3 note:** `ads_push.py` now contains a
`fresh_access_token` helper and a `MetaAudienceTermsError` catch branch immediately before the
provider call — Phase 3's declared `if provider == "google":` EEA-exclusion branch is still
structurally isolated from these, but Phase 3 must re-read the file rather than assume the Phase-1
baseline. `services/ads/base.py` remains untouched and is still the right place for the deferred
shared `refresh_tokens` default.

**Commands to Stay Green.**
```
.venv/bin/python -m pytest tests/unit -k ads -m unit -q
.venv/bin/python -m pytest tests/integration/test_ads_meta_live.py -m integration -q -p no:randomly
cd apps/web && npx tsc --noEmit
```

**Dependency Changes.** None. No package was added to `requirements.txt` or `apps/web/package.json`;
`httpx`, `tenacity`, and `structlog` were already present and are used per existing repo patterns.
No migration was added — the alembic head is unchanged by this phase.
