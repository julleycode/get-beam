---
name: plan:ads-audiences-phase-1-docker-and-auth-known-gaps
description: "Ad Audiences Phase 1+2 — env-only known-gaps and resolution paths (G1/G2 Phase 1; E3/AC7/AC13 Phase 2)"
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

## Cross-references

- Phase 1 plan: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-1-foundation_PLAN_25-07-26.md`
- Phase 1 report: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-1-foundation_REPORT_25-07-26.md`
- Phase 2 plan: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-2-meta-live_PLAN_25-07-26.md`
- Phase 2 report: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-2-meta-live_REPORT_26-07-26.md`
- Umbrella plan: `process/features/ads-audiences/active/ad-audiences_25-07-26/ad-audiences-umbrella_PLAN_25-07-26.md`
- `results.tsv` iteration 3 (Phase 1 EVL confirmation, HALTED_SUCCESS); iteration 5 (Phase 2 EVL
  confirmation, HALTED_SUCCESS)
