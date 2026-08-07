---
name: report:bidstream-intent-data
description: "Pillar 3 (bidstream/RTB intent data) deferred — legal, cost and brand reasons; revisit conditions recorded"
date: 07-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: backlog
---

# Pillar 3 — Bidstream intent data (DEFERRED)

**Decision (07-08-26): not building this now.** Recorded during the
`ip-org-database` (Pillar 1) work so the reasoning survives the session.

## What it would have been

Buying or subscribing to real-time-bidding (RTB) bidstream feeds — the
request-level exhaust of ad exchanges — to infer purchase intent from the pages a
device is seen requesting ads on, then joining that to Beam's visitor graph.

## Why it is deferred

1. **Consent basis is the blocker, not the plumbing.** Bidstream data is
   collected under a lawful basis for *serving an ad on that request*. Repurposing
   it for identity enrichment and outbound outreach is a different purpose, and
   under GDPR a purpose change needs its own basis. Beam cannot inherit the
   exchange's consent, and the exchange's own consent strings do not cover
   Beam's use. This is the kind of exposure that only a lawyer can clear.
2. **Infrastructure cost is structural, not incremental.** A usable bidstream
   feed is millions of QPS. Filtering it down to the tiny slice relevant to a
   handful of customer sites means paying to ingest and discard essentially all
   of it. That is a different company's cost base, not a feature.
3. **It contradicts the brand.** Beam's stance is explicitly anti-bot and
   privacy-forward: a human approves and sends, data comes from first-party
   capture and public sources. Sourcing behavioral data from ad-exchange exhaust
   is exactly the surveillance-adtech posture the product positions against, and
   that contradiction would be the story if it were ever noticed.

## Revisit conditions

Reopen only when BOTH hold:

- **Legal counsel has cleared the purpose change in writing** for the target
  jurisdictions (at minimum EU/UK and California), including how consent strings
  are honored and how erasure requests propagate into ingested bidstream data.
- **Material scale exists** to amortize the ingest cost — enough paying customers
  that a dedicated filtering pipeline is cheaper than the paid-provider calls it
  would replace.

Until then, intent signal comes from what Beam already owns: first-party capture,
on-site engagement, AI-referral attribution, and the self-hosted IP→org database
(Pillar 1, `ip-org-database_07-08-26`).
