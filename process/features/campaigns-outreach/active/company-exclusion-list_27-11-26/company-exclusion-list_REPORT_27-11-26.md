---
phase: company-exclusion-list-execute
date: 2026-11-27
status: COMPLETE_WITH_GAPS
feature: campaigns-outreach
plan: process/features/campaigns-outreach/active/company-exclusion-list_27-11-26/company-exclusion-list_PLAN_27-11-26.md
---
# Company Exclusion List — EXECUTE report

TL;DR: all checklist items done; G1–G9 green (G8 has 1 pre-existing unrelated failure); G10 manual and the full integration regression run are open. Flag stays OFF.

## What Was Done
- New: `models/site_exclusion.py`, migration `e8c4b2a7d913` (down `d3f8a2c61b47`), `services/company_exclusion.py`, `schemas/exclusions.py`, `routers/exclusions.py` (mounted in `main.py`), web `components/exclusions-panel.tsx`.
- Flag `company_exclusion_enabled=False` in `config.py`.
- Guards (each flag-guarded): `campaign_sender.send_campaign_emails`, `csv_exporter._get_segment_visitors`, `segmenter.run_segmentation` (entry), `campaigns.create_campaign_from_segment` (planner), `campaigns._resolve_linkedin_targets`, `AutoDrafter.generate_for_visitor` (first statement), `drafts.approve_draft`/`retry_draft` (409 before mutation), `sender.send_draft` (typed `CompanyExcludedError`), `visitors.list_visitors` (badge).
- `VisitorOut.excluded_reason`; web api client/types, connectors panel, visitors badge (Excluded wins over Known).
- Backlog NOTE `backlog/crm-customer-auto-exclusion_NOTE_27-11-26.md`; evidence pack in `harness/` (validator: 0 failures).
- E2: `skipped_company_excluded` present only when flag ON. E10: `/segments/{site_id}/run` reports pre-filter `visitors_analyzed`.

## What Was Skipped or Deferred
- G10 manual UI walk (Clerk harness gap).
- Full `tests/integration` regression: interrupted when local :5433 dropped (colima disk I/O errors); not restarted (shared env).

## Test Gate Outcomes
| Gate | Result |
|---|---|
| G1+G5 unit | 26 passed |
| G7 census | 6 passed |
| G2 crud | 7 passed |
| G3 flag_on | 14 passed |
| G4 flag_off | 1 passed |
| G6 migration up/down/up (disposable pg16) | pass |
| G8 unit suite | 3114 passed, 1 failed pre-existing (`test_paid_x402`, fails with change stashed) |
| G9 tsc | 0 errors in src (4 stale `.next/types` errors, pre-existing) |
| G10 | not run (known-gap D) |

## Plan Deviations
See plan `## Deviations`: extra thin helpers in company_exclusion.py; ads/CRM push row-drop proven at the shared `_get_segment_visitors`; test deps installed into `.venv`, `retarget_agent_test` DB created.

## Test Infra Gaps Found
- `.venv` lacked pytest/pytest-asyncio/fakeredis (installed).
- `retarget_agent_test` DB did not exist on :5433 (created).
- `test_paid_x402::test_no_payment_returns_402_with_requirements` red on main (KeyError 'accepts') — classify: product-or-test-breakage, owner agent-gateway.
- `test_demo_canary_public::test_returns_full_shape` failed ('Hanoi' geo) — likely external/geo, unrelated.
- colima VM storage I/O errors kill Postgres forwarding mid-run.

## Closeout Packet
- Plan: path above. Classification: `Keep in active/testing`.
- Verified: G1–G9. Unverified: G10, full integration regression, prod migration.
- Next: orchestrator EVL (vc-tester re-run of G1–G9 + full integration lane once Docker healthy) -> G10 manual -> UPDATE PROCESS.

## Forward Preview
### Test Infra Found
`tests/integration/test_company_exclusion.py` seeds a 4-member audience (email-domain, company_domain, merged-canonical, kept) reusable by sibling plans.
### Blast Radius Changes
Additive edits in campaign_sender.py, campaigns.py, segmenter.py, drafts.py, sender.py, csv_exporter.py, auto_drafter.py, visitors.py, config.py, main.py, web connectors/visitors/api.ts — siblings (signal-creative-cta) rebase on these.
### Commands to Stay Green
`DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test .venv/bin/python -m pytest tests/unit/test_company_exclusion*.py tests/integration/test_company_exclusion.py -q`
### Dependency Changes
Alembic head now `e8c4b2a7d913`. No new runtime deps.
