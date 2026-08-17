---
name: note:engage-playbook-accrual-rate-cap
description: "E8b — per-playbook outcome accrual-rate sanity cap so an anomalous burst cannot fast-track the Phase 3b autonomy threshold. DEFERRED, defense-in-depth."
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: memory
  type: report
  feature: campaigns-outreach
  phase: phase-1
---

# E8b — Per-playbook outcome accrual-rate sanity cap

**Status:** DEFERRED. Explicitly **not** in Phase 1's scope; recorded so it is not lost.
**Origin:** engage-learning-agent Phase 1, checklist item E8b (peer-session finding).

## The idea

A defense-in-depth ceiling on how fast a single playbook (`Draft.strategy`) may
accrue positive outcome rows. Without one, an anomalous burst of `reply_received`
rows against one playbook could fast-track it past whatever threshold Phase 3b uses
to grant autonomy — the autonomy gate reads exactly this data.

## Why it is deferred rather than built

Phase 1's v1 defenses cover the realistic abuse shape already:

1. **Own-account exclusion (D2d, shipped).** A reply authored by the site's OWN
   connected posting account never produces a `reply_received` outcome. This closes
   the obvious self-inflation route: a site owner threading follow-ups onto their own
   replies. Compared on the immutable platform user id, not the mutable handle.
   Gated by `test_own_account_reply_produces_no_outcome` (with an in-test
   third-party control, so a wholly broken sweep fails rather than passes vacuously).
2. **Exact dedupe (shipped).** `reply_received` dedupes on the inbound reply's own
   platform id via a partial unique index, so the same reply can never be counted
   twice no matter how often the sweep runs
   (`test_sweep_is_idempotent_across_two_runs`).
3. **DISTINCT-contact counting (Phase 3a).** The positive-rate is planned to count
   distinct contacts, not raw rows — which structurally blunts a burst from one
   actor. Note this depends on `contact_bidx`, which is **Phase 2**, so it is not
   available yet.

A rate cap on top of those is a genuine improvement but it is speculative until
there is real outcome volume to calibrate against. Building it now means inventing
a threshold with no data — the same trap as shipping a per-site ingest ceiling of
3000 before observing real p99.

## Clearing conditions

1. `engage_outcome_capture_enabled` has been ON in a real environment long enough to
   observe a normal per-playbook accrual distribution.
2. Phase 2's `contact_bidx` has landed, so distinct-contact counting is actually
   possible and the cap can be expressed per distinct contact rather than per row.
3. Phase 3b's autonomy threshold is defined — the cap only means something relative
   to the threshold it is protecting.

**Right home:** Phase 3b (autonomy), or a follow-up plan alongside it. Not Phase 1,
and not Phase 2.
