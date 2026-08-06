---
name: plan:cross-tenant-identified-visitor-erasure-gap
description: "Backlog: erasure never touches other tenants' pre-existing IdentifiedVisitor rows, so another site can keep emailing an erased person (KG-6) — Phase 2 candidate"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# Other Tenants' Existing IdentifiedVisitor Rows Survive Erasure (KG-6)

**Source:** `graph-erasure-compliance_07-08-26`, Known Gap KG-6. **The most consequential open gap
in that plan** — it is the exact harm the SPEC exists to close, only partially closed.

## The concrete harm

Person P is identified on Site A. Independently, Site B already holds its own `IdentifiedVisitor`
row for P from its own paid lookup weeks earlier, currently in an active outreach segment. P
requests erasure at Site A. The sweep hard-deletes the shared `beam_identity_graph` rows and writes
both tombstones — but nothing sets `do_not_email` / `do_not_resolve` on Site B's existing row.

**Site B keeps emailing P and keeps resolving P on return visits, after P's erasure was accepted and
reported complete.**

## What IS covered (so the claim stays honest)

- Hard deletion of the shared `beam_identity_graph` rows.
- A permanent block on all FUTURE graph writes for P on every site (`_upsert_beam_identity` is the
  sole write path, and its guard consults the `"erased"` tombstone).

## Why not closed here

Reaching those rows needs plaintext matching (`_cascade_suppress` matches
`lower(IdentifiedVisitor.email)`), and this plan's queue is deliberately plaintext-free. The
alternative is a blind-index column on `IdentifiedVisitor` / `VisitorEmail`, which those tables do
not have today. Either is a design decision, not an implementation detail.

## Scoping recommendation

A **Phase 2 / follow-up plan**, not an in-scope fix and not a SPEC out-of-scope item — the SPEC's
intent covers this harm. Any user-facing erasure confirmation must be read against this gap: Beam
cannot currently claim unqualified cross-tenant erasure.
