---
name: spec:closed-won-lookalikes
description: "Requirements for CRM closed-won read-back, closed-won seed segment, and Meta/Google lookalike creation"
date: 27-11-26
feature: ads-audiences
---
# Closed-Won Lookalikes — SPEC

TL;DR: Read deal outcomes back from connected CRMs, build a "closed-won seed" from them (plus optional CSV), and turn that seed into a Meta Lookalike / Google Demand Gen lookalike. Default OFF, mock parity, no live calls in gates.

## Goals
- G1 Know which Beam-identified people/companies later closed-won (CRM read-back).
- G2 One-click seed segment of closed-won customers (Beam-matched + CSV upload).
- G3 Push seed to Meta Custom Audience then create a Lookalike; Google path that is real today; LinkedIn CSV export.

## Use cases
- UC1 Founder with HubSpot/Pipedrive/Salesforce connected sees "closed-won: N" after a poll.
- UC2 Founder without a CRM uploads a customer CSV (email, optional company domain) as the seed.
- UC3 Founder clicks "Create lookalike" on the seed: picks Meta (country + 1-10% ratio) or Google; sees min-size warnings.

## Acceptance criteria
- AC1 Poll task reads closed-won deals + associated contact emails for HubSpot, Pipedrive, Salesforce; generic_webhook gets an inbound `deal.closed_won` webhook (signed with existing per-connection secret).
- AC2 Read-back stored as blind-index + ciphertext only (no plaintext email at rest/logs), tenant-scoped.
- AC3 Seed segment = union(CRM closed-won matched to IdentifiedVisitor by email_bidx, CSV rows); dedup by bidx.
- AC4 Meta: seed pushed via existing create_or_update_audience, then lookalike created (subtype LOOKALIKE, origin_audience_id, lookalike_spec country+ratio); warning when seed < 100 matched.
- AC5 Google: no "similar audiences" (sunset 2023). Seed pushed as Customer Match list (existing path); lookalike = Demand Gen lookalike segment derived from that list — API shape is a known-gap until docs/sandbox confirm; if unconfirmed, ship Customer Match seed + UI note "attach as Demand Gen lookalike seed in Google Ads".
- AC6 LinkedIn: CSV export of seed (hashed per existing CSV pattern) only.
- AC7 Flag `closed_won_lookalikes_enabled` default OFF → all new routes 404; flag-ON path exercised by a gate.
- AC8 MOCK_EXTERNAL_APIS returns deterministic deals + lookalike ids.
- AC9 Foreign site/connection ids → 404.

## Out of scope
- Auto-sync lookalike refresh schedules; deal amount/revenue weighting; LinkedIn API audiences; per-account measurement (sibling plan may consume read-back table later); live provider calls in gates.

## Constraints
- HubSpot currently requests only contacts scopes → deals read requires scope add + user reconnect.
- Reuse services/ads registry, ad_connections OAuth, ad_audience_links, crm connectors.
- Migration chains off `alembic heads` at EXECUTE time; never run against `.env` DATABASE_URL (prod).
