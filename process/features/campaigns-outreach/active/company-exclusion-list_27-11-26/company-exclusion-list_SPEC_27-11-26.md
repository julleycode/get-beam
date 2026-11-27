---
name: spec:company-exclusion-list
description: "Per-site company/domain exclusion list (customers, competitors) applied to segmenter, campaign send, CSV export, ad push"
date: 27-11-26
feature: campaigns-outreach
---
# Company Exclusion List — SPEC

TL;DR: site owners list domains (customer|competitor|other); matching visitors stay visible (badged) but never reach outreach, exports, ad audiences, or segmentation.

## Goals
- G1 Site owner manages a per-site list: domain (required, normalized), optional company name, reason enum `customer|competitor|other`, optional note.
- G2 Optional bulk CSV import (domain,company_name,reason), idempotent upsert, row-level error report.
- G3 Matching visitors are excluded from: segmenter input, campaign send, CSV export, ad-audience push.
- G4 Matching visitors remain visible in dashboard with an "Excluded: customer/competitor" badge.
- G5 Default-OFF flag `company_exclusion_enabled`.

## Acceptance Criteria
- AC-1 CRUD API `GET/POST/DELETE /api/v1/sites/{site_id}/exclusions`; foreign site -> 404.
- AC-2 Domain normalization: lowercase, strip scheme/`www.`/path; subdomains match parent (`eu.acme.com` matches `acme.com`).
- AC-3 Match source: visitor email domain OR resolved company domain (IdentifiedVisitor / company_graph domain).
- AC-4 Flag ON: campaign_sender skips excluded recipients (counted as skipped, reason `company_excluded`).
- AC-5 Flag ON: `_get_segment_visitors` drops excluded rows -> covers Meta/Google/LinkedIn CSV and ads push.
- AC-6 Flag ON: segmenter `build_visitor_profiles` omits excluded visitors.
- AC-7 Flag ON: routers/campaigns.py contactable count treats excluded as non-contactable.
- AC-8 CSV import: max 5000 rows / 1 MB; invalid rows reported, valid rows upserted.
- AC-9 Flag OFF: all paths byte-identical to today.
- AC-10 Logs contain site_id + counts only, never domains tied to visitors or emails.
- AC-11 Settings UI section lists/adds/deletes/imports; visitors list shows badge.

## Out of scope
- Auto-detecting customers from CRM/billing (future: CRM connector sync).
- Freemail domains (gmail.com etc.) are rejected at input — would exclude everyone.
- Cross-tenant sharing of lists. Hiding visitors entirely.
