---
name: plan:ads-audiences-phase-1-docker-and-auth-known-gaps
description: "Ad Audiences Phase 1 — G1 (migration round-trip) + G2 (Playwright auth harness) env-only known-gaps and resolution paths"
date: 25-07-26
metadata:
  node_type: memory
  type: plan
  feature: ads-audiences
  phase: phase-1
---

# Phase 1 Foundation — Known-Gap Backlog Note (G1, G2)

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

## Cross-references

- Phase 1 plan: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-1-foundation_PLAN_25-07-26.md`
- Phase 1 report: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-1-foundation_REPORT_25-07-26.md`
- Umbrella plan: `process/features/ads-audiences/active/ad-audiences_25-07-26/ad-audiences-umbrella_PLAN_25-07-26.md`
- `results.tsv` iteration 3 (EVL confirmation, HALTED_SUCCESS)
