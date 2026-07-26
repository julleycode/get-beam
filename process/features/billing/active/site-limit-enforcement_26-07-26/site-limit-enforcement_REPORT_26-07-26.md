---
phase: site-limit-enforcement
date: 2026-07-26
status: COMPLETE_WITH_GAPS
feature: billing
plan: process/features/billing/active/site-limit-enforcement_26-07-26/site-limit-enforcement_PLAN_26-07-26.md
---

# EXECUTE Report — Per-Plan Site Limit Enforcement

TL;DR: all 7 checklist items applied, 3 of 4 gates green (unit 10/10, unit lane 612 passed, web lint + tsc clean). The hybrid Postgres integration gate could not run — Docker daemon is down (E6 known-gap). No plan deviations.

## What Was Done

| File | Change |
|---|---|
| `apps/api/services/billing.py` | ADD `PLAN_SITE_LIMITS` (free 1 / pro 3 / max None) + `get_site_limit()` with fallback-to-free on unknown key; sync comment points at the pricing page |
| `apps/api/routers/sites.py` | `func` import + billing imports; limit check inserted after the dedup/409 short-circuits and above `site = Site(`; `>=` comparison; structlog `site_limit_blocked` (ids/keys only); `402` with structured detail |
| `apps/web/src/lib/api.ts` | object-`detail` branch in `!res.ok`: throws `Error(detail.message)` with the raw object attached via `Object.assign`. String-`detail` and 401 branches byte-identical |
| `apps/web/src/app/dashboard/onboarding/page.tsx` | `showUpgrade` state set when `detail.code === "site_limit_reached"`; renders a `/pricing` "View plans" link inline with the existing error `<p>`. No modal |
| `tests/unit/test_site_limit.py` | NEW, 10 tests |

## What Was Skipped or Deferred

- Hybrid integration gate (`tests/integration/test_site_delete.py`) — Docker daemon down, cannot start Postgres. Per E6 recorded as a known-gap, not silently skipped.
- Agent-Probe manual UI check (free user at limit → onboarding CTA) — requires a running stack; not run.

## Test Gate Outcomes

| Gate | Result |
|---|---|
| `.venv/bin/python3.11 -m pytest tests/unit/test_site_limit.py -q` | `10 passed in 3.04s` |
| `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` | `612 passed, 2 skipped, 571 deselected, 1 warning in 4.82s` (warning pre-existing, `test_identity_signals.py`) |
| `cd apps/web && npm run lint` | `✔ No ESLint warnings or errors` |
| `npx tsc --noEmit` (apps/web) | clean, no output |
| `pytest tests/integration/test_site_delete.py -q` | NOT RUN — `docker info` → DOCKER_DOWN |

Red-first (E5) confirmed: the three stubs failed (`3 failed in 0.05s`) before implementation.

## Plan Deviations

None material. One implementation detail worth recording: `tests/unit/test_site_limit.py` imports `apps.api.main` to register every ORM mapper (the same trick `apps/api/migrations/env.py` uses). Without it, instantiating `User()` raises `InvalidRequestError: ... 'SocialAccount' failed to locate a name`. This is within the plan's test-file scope, not a source change.

## Test Infra Gaps Found

- No unit-lane fixture exists for router functions with a stubbed `AsyncSession`. This file carries a local `_fake_db()` helper (~35 lines, over the plan's ~20-line threshold). Candidate for promotion to `tests/conftest.py` if a second router unit test needs it — not promoted now (single consumer, YAGNI).
- Unit-lane ORM-mapper registration is a repeated footgun; a shared `import apps.api.main` in the unit conftest would remove it from every future test.

## Closeout Packet

- **Selected plan:** `process/features/billing/active/site-limit-enforcement_26-07-26/site-limit-enforcement_PLAN_26-07-26.md`
- **Finished:** all 7 checklist items; AC1–AC5, AC8 proven by automated gates; AC6 proven by a statement-shape assertion (unit) but not against real Postgres.
- **Unverified:** AC6 end-to-end (Docker down), AC7 visually (Agent-Probe not run).
- **Classification:** `Keep in active/testing` — CODE DONE, not VERIFIED. Per the plan's Phase Completion Rules, VERIFIED requires the hybrid gate to have actually run.
- **Remaining cleanup:** run the two Docker/browser-gated checks when a daemon is available, then archive.

## Forward Preview

- **Test Infra Found:** unit lane needs no PG/Redis for this feature; `.venv/bin/pytest` shebang still broken — always use `.venv/bin/python3.11 -m pytest`.
- **Blast Radius Changes:** `apps/web/src/lib/api.ts` error path is now shared-surface-modified — any future error-handling work should be aware objects can now reach callers as `err.detail`.
- **Commands to Stay Green:** `.venv/bin/python3.11 -m pytest tests/unit -m unit -q`; `cd apps/web && npm run lint`.
- **Dependency Changes:** none. No migration, no env var, no new package.
