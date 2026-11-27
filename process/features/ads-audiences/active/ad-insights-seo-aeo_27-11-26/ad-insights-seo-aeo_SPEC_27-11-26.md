---
name: spec:ad-insights-seo-aeo
description: "Ad-performance ingest (Meta/Google read-only) -> winning-message insights paired with AEO signals -> Content opportunities suggestions"
date: 27-11-26
feature: ads-audiences
---
# Ad Insights -> SEO/AEO Content Opportunities — SPEC

TL;DR: pull per-ad performance from already-connected Meta/Google accounts, rank winning headlines/angles, pair them with what AI agents fetch and which AI sources refer humans, and show Gemini-drafted SEO/AEO content suggestions. Suggestions only.

## Goals
1. Ingest per ad/creative/headline daily metrics (impressions, clicks, CTR, platform-reported conversions) from connected `ad_connections` (meta, google). Mock-mode parity.
2. Nightly insight job ranks winning messages (min-impression floor, CTR + conv rate) and joins on-site/AEO signals (`agent_visits` top pages by vendor, `Visitor.ai_source` counts, landing page of the ad URL).
3. Dashboard "Content opportunities" card list: suggested page titles, FAQ entries, llms.txt lines, each citing source ad + signal. Human copies; nothing published.

## Acceptance criteria
- AC-1 Flag `ad_insights_enabled` default OFF; flag-off => endpoints 404, job no-op.
- AC-2 Mock mode returns deterministic report rows for meta + google; no network.
- AC-3 Ingest upserts idempotently on (connection_id, platform_ad_id, date).
- AC-4 Ranking deterministic; ads below impression floor excluded.
- AC-5 Gemini call via `gemini_generate_json` (thinkingBudget 0) with ad copy + page paths passed through `prompt_safety.wrap_untrusted`/`clean_text`; schema-validated; failure => no suggestions, no crash.
- AC-6 Tenant scoping: foreign site/suggestion id => 404.
- AC-7 No PII/prompt bodies logged; ad copy is not PII but is not logged either.
- AC-8 No write path to agent_gateway profiles / llms.txt; suggestion status only `new|dismissed|copied`.
- AC-9 Flag-ON path exercised end-to-end by an integration gate.
- AC-10 Quota: per-site suggestion generation <=1/day.

## Out of scope (phase-2/backlog)
- Live-provider confirmation of report shapes (needs-live-provider known-gap).
- LinkedIn reporting; TikTok.
- Auto-publish to llms.txt / AgentProfile / blog; one-click apply.
- Ad-copy A/B launching, budget recommendations, image creative analysis.
- Backfill > 30 days; ClickHouse.
- Dependency on conversion-apis plan code (conversions come from platform reports).

## Constraints
- Sequencing: EXECUTE after `conversion-apis_27-11-26` lands (shared files: services/ads/*, config.py, routers/ads.py, alembic head).
- Meta scope `ads_management` already implies read of insights; Google `adwords` scope covers GAQL reporting — no re-consent expected (verify live).
