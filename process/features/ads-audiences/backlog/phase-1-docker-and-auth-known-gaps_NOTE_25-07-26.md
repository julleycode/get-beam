---
name: plan:ads-audiences-phase-1-docker-and-auth-known-gaps
description: "Ad Audiences Phase 1+2+3 — env-only known-gaps and resolution paths (G1/G2 Phase 1; E3/AC7/AC13 Phase 2; G2/E4 sandbox smoke, live-ingest ack, enable HARD STOP Phase 3)"
date: 25-07-26
metadata:
  node_type: memory
  type: plan
  feature: ads-audiences
  phase: phase-1
---

# Phase 1 Foundation + Phase 2 Meta Live — Known-Gap Backlog Note

**Status:** open — both gaps are environment-only, not code defects. Neither blocks Phase 1
`✅ VERIFIED` classification (per the phase plan's own Phase Completion Rules: known gaps with a
named resolution path count as recorded evidence, not a blocker) and neither blocks Phase 2/3
from starting.

## G1 — Migration round-trip (A4/E4) not run

**What's missing:** `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` against
a disposable Postgres container. Docker daemon is not running in this sandbox (`docker ps` →
`dial unix .../docker.sock: no such file or directory`), confirmed independently at both PVL
(cycle 2) and EVL.

**What was done instead (not a substitute):** single alembic head confirmed
(`c8e4f2a6b1d9`); the two new tables (`ad_connections`, `ad_audience_links`) were created cleanly
by SQLAlchemy `create_all` against a live local dev Postgres during e2e server boot — proves
schema shape validity, not the upgrade/downgrade round-trip itself.

**Resolution path:** Docker-gate closure run, matching the `owned-data-layer` and `evallayer`
precedent (see `process/context/all-context.md` Owned Identity Data Layer section — that program's
round-trip was verified clean on a disposable Postgres container once Docker was available). Run
in any environment with a working Docker daemon:
```
docker compose -f infra/docker-compose.yml up -d postgres
.venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head
.venv/bin/python -m alembic -c apps/api/alembic.ini downgrade -1
.venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head
```
Record the result in a Phase 1 addendum or fold into whichever future Docker-gate closure pass
covers the ads-audiences program (may be batched with Phase 2/3's own live-provider Docker-gated
legs).

## G2 — Playwright e2e AC9/AC12 (and partial AC1) not fully run

**What's missing:** `cd apps/web && npx playwright test connectors` — 2/6 specs pass (including
AC1's core assertion: Ad Audiences tab renders, CSV download query params unchanged). The other 4
fail on the sign-in screen (`"Sign-in is temporarily unavailable (authentication is not
configured)"`), never on a missing/wrong element on the connectors page itself. Root cause is the
local e2e auth harness — blank Clerk keys + storage-state not persisting between specs — not the
Phase 1 UI.

**Flakiness caveat:** pass count was inconsistent across runs during EVL (1/6 vs 2/6 across two
runs), same root cause (auth harness), not a new defect.

**Also noted:** the Playwright config's own `webServer` command is broken on this host
(`source .venv/bin/activate` under `/bin/sh` → `python: command not found`); servers had to be
started manually for the runs that did produce results.

**Resolution path:** fix the local Clerk e2e auth harness — either provide real Clerk test-mode
keys + a working storage-state fixture, or wire a test-mode auth bypass consistent with however
other Playwright specs in `apps/web/e2e/` already handle auth (check `all-tests.md` routing first).
Also fix the `webServer` shell invocation (`/bin/sh` doesn't support `source`; use `.` or an
explicit `bash -c`). Re-run `npx playwright test connectors` after the harness fix and confirm all
6 specs (including AC9 LinkedIn-disabled and AC12 Exclude List regression) pass.

## Explicitly not duplicated here

**T1 — integration-lane conftest `platform` ENUM defect** (pre-existing, confirmed to also break
untouched CRM tests) is being fixed in a separate, parallel session right now. Do not touch
`tests/integration/conftest*` from this note or write a competing plan for it — this note only
references it for context. See the Phase 1 EXECUTE report
(`process/features/ads-audiences/active/ad-audiences_25-07-26/phase-1-foundation_REPORT_25-07-26.md`,
"Test Infra Gaps Found" section) for the original finding.

## Phase 2 (Meta Live) — added 26-07-26

**Status:** open — all 3 gaps are environment-only or a genuinely-unverifiable live-provider fact,
not code defects. None block Phase 2's code-complete/EVL-green classification; they DO block
`✅ VERIFIED` per the phase plan's own Phase Completion Rules (every Verification Evidence row
needs real recorded evidence, and the Hybrid/UI rows below don't have it yet).

### E3 — Meta sandbox Hybrid smoke not run

**What's missing:** the phase plan's "Operator Env-Prereq Checklist" manual smoke against a real
Meta developer app (LIVE mode) + verified Business Manager — neither exists in this sandbox.

**Resolution path:** this is a **mandatory operator step before any production enable**, not
optional cleanup. Run the plan's Operator Env-Prereq Checklist
(`phase-2-meta-live_PLAN_25-07-26.md` §Operator Env-Prereq Checklist) in an environment with a real
Meta app, then execute the plan's E3 Hybrid smoke procedure and record the result in a phase
addendum before flipping `ad_audiences_enabled` in any real environment.

### AC7 Playwright UI legs — skipped, not failed

**What's missing:** both legs of `apps/web/e2e/connectors-ads-push-warning.spec.ts` skip (not
fail) because the connectors page redirects to Clerk sign-in — the same G2 auth-harness gap from
Phase 1, not a Phase 2 defect. The spec is written to fail loudly (not pass vacuously) if the page
renders but the warning is missing.

**Resolution path:** unblock when G2 (Playwright/Clerk auth harness) is fixed — see G2 above. The
backend leg of AC7 (both pre-push and post-push warning wiring) is already fully proven by
`test_ads_meta_live.py`; only the UI-rendering assertion is unverified.

### AC13 — exact Meta error code/subcode unconfirmed (Agent-Probe residual)

**What's missing:** the real Meta Graph API `code`/`subcode` for an unaccepted Custom-Audience-ToS
ad account. Docs don't specify it; the message-substring match used in `_is_tos_error` is
best-effort and fails safe (degrades to the generic sanitized error, never a crash or wrong push).

**Resolution path:** confirm via one live Meta sandbox call (can be batched with E3's smoke), then
upgrade the `# TODO Agent-Probe:` marker in `services/ads/meta.py` to a real fixture-backed
assertion in `test_ads_meta.py`. Non-blocking; backend behavior is already correct either way.

### Correction (UPDATE PROCESS, 26-07-26): T1 conftest fix IS already landed on `main`

The Phase 2 EVL handoff summary claimed "T1 conftest fix NOT yet landed on main (verified by
grep)" — this was stale at closeout time. Independently re-verified 26-07-26: `git log --oneline -1
-- tests/conftest.py` shows commit `c88444a` ("test(conftest): drop PG native ENUM types in
test_engine setup+teardown"), and `tests/conftest.py` lines 99-110 confirm the `DROP TYPE ...
CASCADE` loop runs at BOTH setup and teardown. See the existing memory note
`integration-conftest-enum-teardown-fixed.md` (2026-07-25, committed and pushed to origin). The
per-file schema-reset workaround this phase's own EXECUTE/EVL sessions used
(`DROP SCHEMA public CASCADE; CREATE SCHEMA public;` between integration files) may therefore be a
residual instability from a *different* cause than the original T1 defect — worth re-checking
without the workaround the next time this integration suite runs, rather than assuming T1 remains
open.

### Also carried (non-blocking, deferred to a future phase)

- Promoting a shared `AdsProvider.refresh_tokens` ABC-level default (mirroring
  `CRMConnector.refresh_tokens`) belongs to whichever phase next touches `services/ads/base.py`
  (hard-forbidden to Phase 2). Safe to defer — `fresh_access_token`'s `getattr` guard already makes
  today's omission harmless, and a unit test pins that behavior.

## Phase 3 (Google Live) — added 07-08-26

**Status:** open — all gaps are environment-only or operator-side, not code defects. None block
Phase 3's code-complete/EVL-green classification (26-07-26, commit `e3adae3`, results.tsv row 7:
G1–G7 all PASS, vc-tester independent, HALTED_SUCCESS); they DO block `✅ VERIFIED` per the phase
plan's own Phase Completion Rules.

### G2/E4 — Hybrid Google sandbox smoke not run

**What's missing:** the phase plan's E4/G2 Hybrid manual smoke against the zero-approval Google
test-account sandbox path. Requires a real Google Cloud OAuth test app (`google_ads_client_id`/
`_secret` set to real values), a Google Ads test account, and a real (test-tier)
`google_ads_developer_token` — none exist in this environment.

**Resolution path:** run the phase plan's Operator Checklist
(`phase-3-google-live_PLAN_25-07-26.md` §Operator Checklist): obtain the 22-char developer token
via the Google Ads UI API Center, confirm Test Account Access (zero-approval default), confirm
consent-screen publish status (Testing-status refresh tokens expire in 7 days — expect roughly
weekly re-mint while in Testing), then execute the E4 Hybrid smoke and record the result in a
phase addendum before Phase 3 can be marked `✅ VERIFIED`.

### Real OAuth offline-consent round-trip unproven

**What's missing:** the `access_type=offline` + `prompt=consent` → refresh-token issuance →
`refresh_tokens(refresh_token)` grant round-trip is unit-proven against mocked responses only
(E1b/G7 green); no live Google token endpoint has ever acked it.

**Resolution path:** proven implicitly by the G2/E4 sandbox smoke above (the connect flow mints a
real refresh token; a follow-up push exercises the refresh path). Batch with G2/E4 — no separate
operator step needed.

### `audienceMembers:ingest` acceptance shape doc-sourced, never live-acked

**What's missing:** the Data Manager API request shape (camelCase consent fields,
`termsOfService.customerMatchTermsOfServiceStatus: "ACCEPTED"`, `encoding: HEX`, 10000-member
batch cap, async `requestId` → `requestStatus:retrieve` polling) is sourced from the live
discovery doc (rev 20260722) but no real ingest call has ever been acknowledged. This includes the
Customer Match ToS **error** shape for an unaccepted account — the Google analogue of Phase 2's
AC13 Agent-Probe residual: unknown real error code/shape; current handling fails safe.

**Resolution path:** confirm via the G2/E4 sandbox smoke (one real ingest + one status-retrieve
call; deliberately trigger the ToS-unaccepted path on a fresh test account if feasible), then
back any observed error shape with a real fixture in `tests/unit/test_ads_google.py` — same
upgrade pattern as Phase 2 AC13.

### `ad_audiences_enabled` flip — operator HARD STOP

**What's missing / rule:** flipping `ad_audiences_enabled` in any real environment is an explicit
operator action gated on the **live migration apply** landing first. Re-run
`alembic -c apps/api/alembic.ini heads` immediately before applying — the head has moved since
this program's EVL (`d5b1f7c3a908` then; now past `f1a7c3e05b92` — see all-context.md Migration
head status for the per-branch truth and the one-edit re-chain). Never trust a hash recorded in
this note.

### AC7 Playwright legs — still blocked on Clerk auth-harness gap

**What's missing:** same pre-existing G2 (Phase 1) Clerk auth-harness gap — Phase 3's UI
assertions cannot run until it is fixed. Not a Phase 3 defect; resolution path unchanged (see G2
above).

### Backlog idea (future optimization, not a gap)

Data Manager discovery doc rev 20260722 now exposes `accountTypes.accounts.userLists.create` — a
capability that did not exist at VALIDATE's 25-07-26 fetch. It could collapse the current locked
two-API sequence (Google Ads API `userLists:mutate` creates the list → Data Manager
`audienceMembers:ingest` fills it) into a single Data Manager API flow, dropping the
`google_ads_developer_token` dependency for the create step. Record only — the as-built two-API
architecture was implemented as specified and is correct; revisit in whichever future phase next
touches `services/ads/google.py`.

## Cross-references

- Phase 1 plan: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-1-foundation_PLAN_25-07-26.md`
- Phase 1 report: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-1-foundation_REPORT_25-07-26.md`
- Phase 2 plan: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-2-meta-live_PLAN_25-07-26.md`
- Phase 2 report: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-2-meta-live_REPORT_26-07-26.md`
- Phase 3 plan: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-3-google-live_PLAN_25-07-26.md`
- Phase 3 report: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-3-google-live_REPORT_26-07-26.md`
- Umbrella plan: `process/features/ads-audiences/active/ad-audiences_25-07-26/ad-audiences-umbrella_PLAN_25-07-26.md`
- `results.tsv` iteration 3 (Phase 1 EVL confirmation, HALTED_SUCCESS); iteration 5 (Phase 2 EVL
  confirmation, HALTED_SUCCESS); rows 6–7 (Phase 3 inner-PVL Gate PASS + EVL G1–G7 confirmation,
  HALTED_SUCCESS)
