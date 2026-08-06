---
name: plan:merged-visitor-consumer-awareness
description: "Backlog: 5 consumer surfaces (kpi.py, timeseries.py, campaign_sender.py, segmenter.py, csv_exporter.py) have zero awareness of canonical_visitor_id/identity_status=='merged' and could double-count or double-send a merged-duplicate Visitor row — pre-existing gap, elevated by Phase 4 contact-import volume"
date: 04-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# Merged-Visitor Consumer Awareness — NEW PLAN REQUIRED

**Source:** Phase 4 (contact-import) inner-PVL, VALIDATE 04-08-26.

## Gap

`apps/api/services/identity_resolver.py`'s `_save_identified` (lines 832-859) already produces
`Visitor.identity_status == "merged"` + `Visitor.canonical_visitor_id` pointer rows for **every**
existing provider whenever two different `visitor_id`s resolve to the same lowercase email — this
is pre-existing generic behavior, not introduced by Phase 4.

VALIDATE grep-confirmed (04-08-26) that 5 of the 7 consumer surfaces named in Phase 4's own
"Cost tradeoff accepted" note have **zero** references to `canonical_visitor_id` or
`identity_status == "merged"` anywhere in their code:

- `apps/api/services/kpi.py`
- `apps/api/services/timeseries.py`
- `apps/api/services/campaign_sender.py`
- `apps/api/agents/segmenter.py`
- `apps/api/services/csv_exporter.py`

(The other 2 — `routers/dashboard.py`, `services/visitor_aggregator.py` — are among the 9 call
sites of `agent_visitor_filters.py`'s `human_only_visitor_filter()`, but that predicate governs
`is_agent_derived`/not-yet-visited-phantom exclusion only — an orthogonal axis — and does **not**
itself check `canonical_visitor_id`/`"merged"` either.)

**Risk:** once a "merged" duplicate row exists, these 5 consumers may double-count it in
metrics/segments/exports, or — worst case — `campaign_sender.py` may attempt to email/count the
duplicate as a second distinct emailable identity. `routers/visitors.py:185-206` already has a
working precedent for resolving `"merged"` rows via their `canonical_visitor_id` pointer — future
hardening should follow that pattern at the 5 named call sites.

## Why this is backlog, not Phase 4 scope

Phase 4's blast radius explicitly excludes `campaign_sender.py` (see umbrella "Blast Radius" and
Phase 4's own "Does NOT touch" line), and `kpi.py`/`timeseries.py`/`segmenter.py`/`csv_exporter.py`
are not in Phase 4's blast radius at all. Phase 4 does not create this gap — it increases how often
it triggers, since every imported contact is a live merge candidate. Fixing 5 files across
different subsystems is a cross-cutting hardening pass, not a one-phase fix.

## Suggested next plan

A short, focused plan: add a single shared helper (e.g. `resolve_canonical_visitor_id()` or a
query-time JOIN pattern) and wire it into the 5 named consumers, following the
`routers/visitors.py:185-206` precedent. Add a regression test proving a merged pair is counted/
sent exactly once, not twice, in at least `campaign_sender.py` and one metrics surface.

Status: NOT YET SCHEDULED. Raise when Phase 4 ships and real merge volume starts flowing, or
sooner if a name collision incident is suspected.
