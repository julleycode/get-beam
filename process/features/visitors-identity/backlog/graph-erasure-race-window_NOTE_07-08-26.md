---
name: plan:graph-erasure-race-window
description: "Backlog: a resolve() in flight at the exact instant the erasure sweep commits could re-write a graph row (KG-1)"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# Graph Erasure — True Race Window (KG-1)

**Source:** `graph-erasure-compliance_07-08-26`, Known Gap KG-1.

## Gap

The write-boundary guard in `_upsert_beam_identity` reads the suppression tombstone and then
inserts. A `resolve()` already past that read at the instant the sweep commits its DELETE could
re-write the row it just erased.

## Why deferred

The observed, realistic risk is re-visit-after-deletion — a strictly sequential ordering, which the
guard DOES cover. Closing the true concurrent race needs either a distributed lock around the graph
write or a re-check-after-write compensating pass; both are heavier than the residual justifies
today.

## What closing it looks like

Either (a) a re-check-after-write: immediately after the upsert, re-read the tombstone and delete
the row if one now exists, or (b) the deferred self-healing reconciliation pass noted in the plan's
§4a (compare `status='done'` erasure requests against current graph presence — the request row
retains its match keys after reaching `done`, so this is cheap and needs no new state).
