---
phase: ad-insights-seo-aeo-execute
date: 2026-11-27
status: COMPLETE_WITH_GAPS
feature: ads-audiences
plan: process/features/ads-audiences/active/ad-insights-seo-aeo_27-11-26/ad-insights-seo-aeo_PLAN_27-11-26.md
---
# Ad insights -> SEO/AEO content opportunities — EXECUTE report

TL;DR: Sections A-C implemented; G1/G1b/G2/G3/G4/G5 green, G7 green for touched files, unit lane has 1 pre-existing unrelated failure. Flag OFF. KG-1 (live shapes) and G8 (Clerk harness) remain.

## What Was Done
- A: migration `b3e9c4d71a58` (off `a2d6e8f41c93`), models `ad_performance.py` / `content_opportunity.py`, delete_site cleanup, `AdsProvider.fetch_ad_performance` + `AdPerformanceRow`, Meta/Google parsing + mock, `services/ad_insights_ingest.py` (advisory lock, connected-only, status re-check).
- B: `ad_insights_rank.py` (pure), `ad_insights_signals.py`, `content_opportunities.py` (fenced prompt, re-validation, mock branch), `ad_insights_daily` cron job, config flags.
- C: `routers/ad_insights.py` + `schemas/ad_insights.py`, web types/methods, `/dashboard/content-opportunities` page + nav, Playwright spec.

## What Was Skipped or Deferred
- Integration regression lane (delegated to vc-tester EVL).
- KG-1 live provider shapes (needs-live-provider). G8 Playwright run (Clerk harness).

## Test Gate Outcomes
| Gate | Result |
|---|---|
| G1 rank | 8/8 |
| G2 parsing | 8/8 |
| G3 prompt safety | 15/15 |
| G1b scheduler | 14/14 |
| G4 integration flag-ON | 7/7 |
| G5 migration round-trip | PASS (`harness/g5-migration-roundtrip.log`) |
| G6 unit lane | 2408 pass / 1 fail pre-existing (`test_paid_x402`, fails on baseline) |
| G7 tsc | 0 errors in touched files; 12 pre-existing env errors |
| G8 Playwright | skip-guarded, known-gap |
| G9 evidence pack | validator: 0 failures, 0 warnings |

## Plan Deviations
See plan `## Deviations` (all within blast radius).

## Test Infra Gaps Found
- `apps/web` tsc baseline is red in this env (`@sentry/nextjs` missing from node_modules, stale `.next/types`).
- `tests/unit/test_paid_x402.py::test_replay_returns_cached_without_upstream_or_settle` fails on baseline.

## Closeout Packet
- Classification: Keep in active/testing (EVL re-run + human review of high-risk pack pending).
- Follow-up stubs: none created (KG-1 and G8 already tracked as named residuals).
- CONTEXT_PARTIAL: none.

## Forward Preview
### Test Infra Found
Integration test resets `redis_client._client` per test and patches `routers.ad_insights.async_session` for BackgroundTasks.
### Blast Radius Changes
New tables `ad_performance_daily`, `content_opportunities`; alembic head now `b3e9c4d71a58`.
### Commands to Stay Green
Gate commands in the plan's Validate Contract (DSN pinned to localhost:5433).
### Dependency Changes
None.
