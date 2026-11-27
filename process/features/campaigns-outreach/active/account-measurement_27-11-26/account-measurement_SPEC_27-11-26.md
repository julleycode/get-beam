---
name: spec:account-measurement
description: "Account-level (per company domain) measurement rollup — API + dashboard Accounts view (gap #14)"
date: 27-11-26
feature: campaigns-outreach
---
# Account Measurement — SPEC

TL;DR: one read-only rollup per company domain for a site, served by a new authed endpoint and an "Accounts" dashboard page. No schema change. Flag `account_rollup_enabled` default OFF.

## Goals
- G1 Measure per account, not per click: one row per `company_domain` per site.
- G2 Founder sees which accounts are warming and which campaigns touched them.

## Metrics per account (window `days`, default 30)
| Metric | Source (existing table) |
|---|---|
| visitors | `visitors` where `company_domain=d`, `human_only_visitor_filter()`, not abuse-flagged |
| identified people | `identified_visitors` joined on visitor_id, `identity_status='identified'` (count only, no PII) |
| sessions / pageviews | `SUM(visitors.total_sessions/total_pageviews)` |
| pricing-page hits | visitors whose `pages_visited` JSONB contains a path matching `/pricing` prefix rule (reuse `agent_intent_signals` prefix semantics) |
| campaigns touched | `COUNT(DISTINCT campaign_touchpoints.campaign_id)` where `status='sent'` for account visitors |
| CTA clicks | `campaign_clicks` for account visitors |
| conversions / demo bookings / value | `conversions` for account visitors (count, `SUM(value_cents)`); "demo bookings" = conversions on goals the owner marks (goal name/pattern match `Site.booking_url`) |
| intent score, name, industry | `companies` row when present |
| replies | KNOWN-GAP: no visitor-linked email reply tracking exists (`messages`/`engage_outcomes` are social, not visitor-keyed) → returned as `null` |
| CRM pipeline / deal value | KNOWN-GAP: `routers/crm.py` is push-only (HubSpot read scope unused). Returned `null`; owned by the separate closed-won read-back plan |

## Use cases
- UC1 `GET /api/v1/accounts/{site_id}?days=30&sort=intent|visitors|conversions&page=` → paged list.
- UC2 `GET /api/v1/accounts/{site_id}/{domain}` → single account + per-campaign breakdown.
- UC3 Dashboard `/dashboard/accounts` table + detail drawer; empty/flag-off states.

## Out of scope
CRM read-back, new tables/migrations, reply ingestion, cross-tenant aggregates, any send/outreach action, consumer-ISP domains as accounts (filtered via existing org_kind/freemail list if present; else known-gap).

## Constraints
Tenant scope via `verify_site_access` (404 on foreign). Read-only (no commit/flush). No PII in logs/response (counts only). Flag OFF ⇒ 404. Python 3.11 syntax. Bot/agent/abuse rows excluded.

## Acceptance criteria
AC1 flag OFF → 404 both endpoints. AC2 foreign site → 404. AC3 seeded fixture: counts exact per metric. AC4 bot/abuse visitors excluded. AC5 replies & pipeline are `null` with `known_gap` reason fields. AC6 no visitor email/name in response. AC7 dashboard renders list + empty state (typecheck + Playwright smoke, auth-harness-gated). AC8 p95 query < 500ms on 10k-visitor fixture (agent-probe).
