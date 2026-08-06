---
name: plan:company-graph-erasure-legal-read
description: "Backlog: CompanyGraphNode is excluded from erasure fan-out pending a legal read on whether company-from-IP rows are personal data (KG-3)"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# CompanyGraphNode Erasure — Legal Read Needed (KG-3)

**Source:** `graph-erasure-compliance_07-08-26`, Known Gap KG-3. SPEC Open Q2.

## Gap

The erasure sweep fans out only to `beam_identity_graph`. `company_graph` (durable cross-tenant
company-from-IP rows) is untouched by an erasure request.

## Why deferred

Whether a company-from-IP row is personal data under GDPR is a legal judgment, not an engineering
one. For a large employer it is plainly not; for a one-person company operating from a home IP it
plausibly is.

## What closing it looks like

Engineering cost is already near zero by design: `ERASURE_TARGETS` in
`apps/api/models/erasure_request.py` is an extensible tuple, and `_process_claimed` already loops
over it. Adding `"company_graph"` plus one delete-statement branch is the whole change — no schema
migration. The blocker is the decision, not the code.
