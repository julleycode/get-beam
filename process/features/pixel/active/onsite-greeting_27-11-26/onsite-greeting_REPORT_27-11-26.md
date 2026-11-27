---
phase: onsite-greeting-execute
date: 2026-11-27
status: COMPLETE_WITH_GAPS
feature: pixel
plan: process/features/pixel/active/onsite-greeting_27-11-26/onsite-greeting_PLAN_27-11-26.md
---
# On-site greeting — EXECUTE report

TL;DR: all 9 checklist items done; G1–G5 and G8 green; both flags default OFF; new alembic head `a2d6e8f41c93`. Full G7 lanes still need the independent EVL run.

## What Was Done
- Config `onsite_greeting_enabled=False`; `Site.greeting_enabled` + `greeting_templates`; migration `a2d6e8f41c93` (down_revision `f7d1b3c84e29`, the single live head).
- `services/greeting.py` `decide_greeting` (flag → site → Origin → visitor → relay → cached `ip_privacy` → ip_org `org` name; only `greeting_company:{ip}` cached, 1h).
- `routers/greeting.py` `GET /api/v1/greeting` (30/min per IP, 600/min per site under its own scope, `no-store`, logs site_id/show/reason only, fails closed).
- `main.py`: router, wildcard no-credential CORS for the endpoint and `/pixel/greeting.js`, static route.
- Sites PATCH: `greeting_enabled`, `greeting_templates` (default only, text ≤200, `{company}` only, https-only CTA via `validate_https_url`).
- Pixel: lazy loader `gL()` in tracker.js (+68 B gz → 6,090 B); new `greeting.js` / `greeting.min.js` (964 B gz); build script updated.
- Tests: `tests/unit/test_greeting_service.py` (43), `tests/integration/test_greeting_endpoint.py` (13), `apps/pixel/e2e/greeting.spec.ts` (9) + harness route + 3 fixtures.
- Evidence pack `harness/` (5 canonical files + migration log). Backlog NOTE `process/features/pixel/backlog/onsite-greeting-settings-ui_NOTE_27-11-26.md`.

## What Was Skipped or Deferred
- G7 full unit + integration lanes — left to the EVL tester (per orchestrator instruction); targeted subsets green.
- Dashboard settings UI (U3, backlog). Per-industry templates (U4).

## Test Gate Outcomes
| Gate | Result |
|---|---|
| G1 unit service | 43 passed |
| G2 integration (both flags ON, ≥1 show:true) | 13 passed |
| G3 pixel size | 88 passed (6,090 B gz, 35,958 B raw) |
| G4 pixel e2e | 9 passed (installed Chrome, scratch config) |
| G5 migration up/down/up | pass (throwaway DB, dropped) |
| G6 no-PII logs | inside G1 + G2, pass |
| G7 | targeted subset pass; full lanes pending EVL |
| G8 evidence pack | failures [] warnings [] |

## Plan Deviations
See plan `## Deviations` D1–D5 (comment shortened instead of raising raw cap; G4 via system Chrome; G5 throwaway DB; per-site limit 600/min; mock net TEST-NET-3).

## Test Infra Gaps Found
- No Playwright browsers cached; `apps/pixel` has no node_modules. G4 needs the scratch-config route or a browser install.
- KG-3 webkit/firefox legs not run.

## Closeout Packet
- Plan: `process/features/pixel/active/onsite-greeting_27-11-26/onsite-greeting_PLAN_27-11-26.md`
- Verified: G1–G5, G8. Unverified: full G7, KG-1/KG-2 prod preconditions, human review of the high-risk pack.
- Classification: Keep in active/testing (EVL + human review of `harness/review-decision.json`).
- Next: EVL via vc-tester.

## Forward Preview
### Test Infra Found
`apps/web/node_modules/.bin/playwright` + `channel: "chrome"` runs pixel e2e without a browser download.
### Blast Radius Changes
None beyond the plan touchpoints.
### Commands to Stay Green
G1/G2/G3 pytest commands in the plan contract (DATABASE_URL pinned to localhost:5433).
### Dependency Changes
Alembic head is now `a2d6e8f41c93`; later migrations must chain off it.
