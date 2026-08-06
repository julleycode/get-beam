---
name: plan:graph-erasure-historical-reconciliation
description: "Backlog: pre-existing graph rows were never reconciled against historical deletion requests — verified not actionable, no log with sufficient detail exists (KG-2)"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# Graph Erasure — Historical Reconciliation (KG-2)

**Source:** `graph-erasure-compliance_07-08-26`, Known Gap KG-2. SPEC Open Q4.

## Gap

Every deletion request honored BEFORE this feature shipped deleted only the requesting tenant's own
rows. Those people may still be present in `beam_identity_graph`, and nothing has been done to find
them.

## Why deferred — verified NOT actionable, not merely unscheduled

There is no historical deletion-request log carrying enough detail (the match keys — fingerprint or
email blind index) to cross-reference against the graph. The old endpoint logged only
`site_id` + a truncated `visitor_id`, and the rows those keys pointed at were themselves deleted.
A one-time reconciliation therefore has no input to run against.

## What closing it looks like

Only reachable if a source of historical match keys is found (e.g. a backup predating the deletions,
or provider-side records). Absent that, the honest position is that pre-feature erasures are
incomplete in the shared graph and cannot be retroactively identified.
