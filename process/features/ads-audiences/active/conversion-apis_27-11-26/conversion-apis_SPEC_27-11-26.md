---
name: spec:conversion-apis
description: "Server-side conversion sending (Meta CAPI, Google Ads click/enhanced conversions, LinkedIn deferred) from Beam outcome events"
date: 27-11-26
feature: ads-audiences
---
# Conversion APIs back to ads — SPEC

TL;DR: When a Beam visitor converts (identified lead, demo booked, reply, CRM stage), send a hashed, consent-gated, deduplicated conversion to the ad platform that drove the click. Default OFF, mock-parity, no pixel byte growth.

## Goals
- G1 Meta Conversions API sends for connected Meta accounts with a configured dataset (pixel) id.
- G2 Google Ads click conversions (gclid) + enhanced conversions for leads (hashed email) for connected Google accounts with a mapped conversion action.
- G3 LinkedIn: CSV export of conversions only in v1 (mirrors LinkedIn audiences `READY=False`); live CAPI = phase 2.
- G4 Durable delivery log: one row per (site, platform, conversion_type, dedup_id), status/attempts/last_error (sanitized, no PII).

## Use cases / acceptance criteria
- AC-1 Click ids captured server-side from `events.url` query (`fbclid`, `gclid`, `wbraid`, `gbraid`, `li_fat_id`) at ingest → stored first-touch on `visitors` (no tracker.js change; pixel stays <6000 B).
- AC-2 Conversion types: `identified_lead`, `demo_booked` (Phase-1 marketing-claims booking attribution / outcome goal), `reply`, `crm_stage` (only when CRM connection reports stage). Per-site per-platform mapping toggles which types send.
- AC-3 Dedup id = `sha256(site_id|visitor_id|conversion_type)` hex (stable; Meta `event_id`, Google `orderId`); unique index makes re-enqueue idempotent.
- AC-4 Hashing: SHA-256 of trimmed-lowercased email; E.164 digits-only phone; reuse `services/ads_push.build_hashed_contacts` normalizers.
- AC-5 Gates (all fail-closed): flag `ad_conversions_enabled` OFF → nothing; `do_not_resolve` or `do_not_email`/suppressed → skip; abuse/bot/agent-origin → skip; Google: EEA or unknown country → skip (reuse `exclude_eea_rows`); Meta: EEA requires per-site `eea_consent_attested` else skip.
- AC-6 Retry: transient (5xx/429/timeout) exponential backoff, max 5 attempts, then `failed`; permanent 4xx → `failed` immediately.
- AC-7 Mock mode: `MOCK_EXTERNAL_APIS=true` returns deterministic success without network.
- AC-8 Tenant scoping: config/log endpoints 404 for foreign site.
- AC-9 No PII in logs/delivery-log rows (hash prefixes only never stored either; ids + status only).

## Out of scope
- LinkedIn live Conversions API; offline value/revenue; auto-optimization; browser-side pixels; calling any live provider in this program.
- Changes to tracker.js.

## Constraints
- Live payload/scope shapes unverified → `needs-live-provider` known-gap. Meta scope `ads_management` assumed sufficient for dataset events; Google needs `conversionAction` resource + developer token (already present).
- Sibling plan ad-tests→SEO/AEO consumes `ad_conversion_deliveries` + `visitors.click_ids` — contract frozen in PLAN §Public Contracts.
