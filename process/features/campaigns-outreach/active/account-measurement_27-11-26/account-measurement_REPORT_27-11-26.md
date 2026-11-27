---
phase: account-measurement-execute
date: 2026-11-27
status: COMPLETE_WITH_GAPS
feature: campaigns-outreach
plan: process/features/campaigns-outreach/active/account-measurement_27-11-26/account-measurement_PLAN_27-11-26.md
---
# account-measurement — EXECUTE report (Lane A, plan 2)

## Plan edits for the orchestrator to apply
This worktree agent cannot write to the main checkout, so these edits are listed here instead:
- **Open User Decisions:** U1, U2 and U3 were CONFIRMED by the user on 27-11-26. Replace each "(pending user confirmation)" with that.
- **Status:** CODE DONE. G1–G4 and G7/G8 are green and G2 ran flag-ON. VERIFIED still needs the independent vc-tester EVL run.

## What Was Done
- Checklist items 1–8 are done. There is no migration.
- New files:
  - `services/account_rollup.py`
  - `schemas/account_rollup.py`
  - `routers/accounts.py`, mounted at `/api/v1/accounts`
  - `dashboard/accounts/page.tsx`
  - `tests/unit/test_account_rollup.py`
  - `tests/integration/test_accounts_api.py`, including the `seed_10k` fixture and the perf probe
  - `apps/web/e2e/accounts.spec.ts`
- Edited files: `config.py` (`account_rollup_enabled` flag, default OFF), `main.py`, `api.ts`, `api-types.ts`, `dashboard/layout.tsx` (nav link).
- `schemas/accounts.py` is untouched.

## Test Gate Outcomes
| Gate | Result |
|---|---|
| G1 unit | 18/18 |
| G2 integration, flag ON, lane DB | 7 passed, 1 perf skipped. Covers: flag-OFF 404; foreign site / unknown domain / freemail 404; exact counts; agent + abuse rows excluded while bot-suspect is counted; merged alias counted as one person with its activity counted; full-URL pricing; Demo-booked conversions; 30 vs 60 day window boundary; cross-tenant zero bleed; detail campaigns; recursive no-PII key check; bad params return 422 |
| G3 unit lane (`-m unit`) | 2189 passed, 1 failed. The failure is `test_paid_x402.py`, which also fails on base without these changes |
| G4 | `tsc` clean apart from the `@sentry/nextjs` errors already on base (shared node_modules lacks it). `npm run lint` cannot start: `next.config.mjs` imports `@sentry/nextjs`. `eslint` run directly on every touched file is clean. Re-run on main once Sentry deps are installed |
| G5 Playwright | The spec is collected (`--list`). It is skip-guarded on `E2E_ACCOUNTS_SITE` plus the Clerk auth harness: known-gap D |
| G6 perf | seed_10k (10,000 visitors over 500 domains): p95 124 ms, median 74 ms, EXPLAIN execution 80 ms. No fallback fired |
| G7 PII grep + `schemas/accounts.py` unchanged | PASS |
| G8 route mount | PASS (`main.py:576`) |

## Plan Deviations
1. **G6 fixture runs `ANALYZE` after seeding.** Without it, fresh tables have no planner statistics. Every estimate was rows=1, the planner picked nested-loop plans, and p95 was about 3.9 s. Prod tables are analyzed by autovacuum. This is a fixture change only; no service change, index or fallback.
2. **Freemail filter uses `enricher._FREE_MAIL_DOMAINS` (U2).** `company_exclusion.is_freemail()` is not on this branch. **At merge:** swap the import in `services/account_rollup.py` (`_members`) to `is_freemail` / its domain set if the company-exclusion plan has landed.
3. **Demo bookings match on goal name.** A conversion counts when its `ConversionGoal.name == "Demo booked"` (the preset name, U1), not on the goal's URL pattern.
4. **The list returns domains with any metric above 0 in the window.** That includes domains with only clicks, emails or conversions and no in-window visitor. Domain membership is all-time; each metric is windowed on its own timestamp, as pinned in the plan.

## Known Gaps
- `replies` and `pipeline_value_cents` are always null.
- G5 needs the Clerk auth harness.
- G4 lint must be re-run on main.
- IP-derived `company_domain` attribution accuracy is not verified.

## Forward Preview
- **Commands to stay green:** G1–G8 as in the plan, using the lane DSN.
- **Dependency Changes:** none.
- **Blast Radius Changes:** none beyond the plan. The e2e spec is the planned `accounts.spec.ts`.
