---
name: plan:graph-erasure-cumulative-cap
description: "Backlog: there is no erasure abuse control of any kind — graph_erasure_max_per_minute is a forensic marker that enforces nothing and has no cumulative cap (KG-8)"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# No Erasure Abuse Control At All (KG-8)

**Source:** `graph-erasure-compliance_07-08-26`, Known Gap KG-8 (§4b option (b)).

## Gap

`graph_erasure_max_per_minute` is a **forensic volume marker, not a cap**, despite its name. On a
trip it sets `throttle_flagged=True` and emits a warning log. It changes no execution path: the
request is never rejected, the tenant's own local deletion always runs, and the flagged row is
claimed and processed by the sweep identically to an unflagged one (pinned by T-I10 and by the unit
gate asserting the claim query never references the column).

Consequently:

- a **patient** attacker staying under 60/min can enqueue tens of thousands of irreversible
  cross-tenant erasures per day, entirely unmarked;
- an **impatient** one who trips the marker is merely recorded, not stopped.

There is no cumulative daily or lifetime cap and no anomaly-review surface. Compounds KG-7.

## Why the marker deliberately does NOT enforce

Real exclusion (holding flagged rows back pending operator release) was considered and rejected: on
a GDPR clock in a solo-founder codebase, "held pending manual release" is functionally
indistinguishable from "dropped", which is the exact liability the feature exists to close — and it
would still not stop the named attack (KG-7 is a single precision request a burst limiter cannot
see). Enforcing would trade a real irreversible-inaction failure for no security gain.

## What closing it looks like

A cumulative daily/lifetime cap plus an anomaly-review surface. Requires three product decisions
that were not made here: what threshold, what happens on trip, and who reviews.
