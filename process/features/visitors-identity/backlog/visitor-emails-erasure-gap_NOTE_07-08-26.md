---
name: plan:visitor-emails-erasure-gap
description: "Backlog: DELETE /visitors/{site}/{visitor}/data never deletes visitor_emails, so first-party-captured plaintext survives a per-visitor erasure in the visitor's own tenant"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# visitor_emails Survives Per-Visitor Erasure

**Source:** `graph-erasure-compliance_07-08-26`, observation S4. Pre-existing, NOT introduced by
that plan and outside its SPEC scope (which covers the cross-tenant graph plus disclosure only).

## Gap

`DELETE /api/v1/visitors/{site_id}/{visitor_id}/data` deletes 7 tables: `resolution_logs`,
`identified_visitors`, `enrichment_profiles`, `events`, `segment_members`, `job_change_events`,
`visitors`. **`visitor_emails` is not among them** (model: `apps/api/models/visitor_email.py`).

A visitor's first-party-captured **plaintext** email therefore survives an otherwise-complete
per-visitor erasure — in the visitor's OWN tenant, which is the part the endpoint has always claimed
to handle fully.

Note the interaction: the graph-erasure producer READS `visitor_emails` to collect match keys, so
the row is used and then left in place.

## What closing it looks like

Almost certainly a one-line addition to the delete tuple. It is separated out rather than folded in
because it changes the semantics of an existing GDPR endpoint on a different axis (own-tenant
plaintext retention) than the plan that found it, and it deserves its own confirmation that nothing
depends on those rows outliving the visitor.
