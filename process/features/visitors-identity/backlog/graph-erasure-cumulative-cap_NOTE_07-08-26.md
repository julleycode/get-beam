---
name: plan:graph-erasure-cumulative-cap
description: "Backlog: there is no erasure abuse control of any kind — graph_erasure_max_per_minute is a forensic marker that enforces nothing and has no cumulative cap (KG-8)"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
status: resolved
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

## Resolution (14-11-26)

Resolved by branch `fix/gdpr-erasure-gaps` (PR into `main`, 14-11-26). New ENFORCED cap `graph_erasure_max_per_day` (default 1000, 0 = off): `graph_erasure.daily_cap_exceeded` counts the site's own `erasure_requests` in the trailing 24h; at/over the cap `DELETE /visitors/{site}/{vid}/data` returns 429 + `Retry-After: 3600` BEFORE anything runs (no enqueue, no local delete). Chosen on-trip behaviour: an explicit, retryable refusal — not a silent hold — which avoids the 'held = dropped' liability this note describes. The per-minute forensic marker is unchanged. Still open (human decisions): the anomaly-review surface and whether 1000/day is the right threshold. KG-6/KG-7 untouched.
