---
name: plan:evallayer-phase-05-rollup-staleness-note
description: "Backlog: AgentVisit is an aggregate rollup row, not a per-visit row — once resolved_company_id is set, later visits from a different company/IP rolling into the same (site,vendor,token) row never get re-resolved, causing stale/incorrect company attribution over time — NEW PLAN REQUIRED"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: backlog
---

# Backlog — AgentVisit Rollup Staleness (Company Attribution Can Go Stale)

**Source:** Phase 5 (Company resolution → outreach feed) PVL, 22-07-26.

## Gap

`apps/api/models/agent_visit.py::AgentVisit` is an aggregate ROLLUP row keyed on
`(site_id, vendor, product_or_ua_token)` — NOT one row per individual agent visit. Confirmed via
`apps/api/services/agent_visit_persistence.py::persist_agent_visit`'s `ON CONFLICT DO UPDATE`
clause: `ip_address`, `last_seen_at`, `page_paths`, and `visit_count` are all overwritten/incremented
on every subsequent visit from the same vendor+token combo for a site. A single `AgentVisit` row can
therefore represent many real-world visits over time, potentially from different underlying
companies/IPs (e.g. `ClaudeBot` visiting once from a residential IP, later from a different
company's corporate NAT egress).

Phase 5's sweep eligibility query is:

```python
select(AgentVisit).where(
    AgentVisit.resolved_company_id.is_(None),
    AgentVisit.ip_address.isnot(None),
).limit(limit)
```

Once `resolved_company_id` is set (non-null) for a row, this eligibility query PERMANENTLY excludes
it from any future resolution attempt — even though `ip_address` keeps changing underneath it as new
visits arrive. The company/lead created on first resolution can go stale (may no longer correspond
to whichever company is actually visiting via that vendor+token today).

## Severity

Data-quality / business-value gap (SPEC AC9's "lead generation value" metric), not a safety
violation. Does not affect the AC2 pollution guarantee or the AC10 outreach-exclusion guardrail.
Accepted as a known, non-blocking residual for Phase 5's own Gate.

## Suggested fix (future plan)

Options for a future phase: (a) re-attempt resolution when `ip_address` changes materially after
the first resolution (requires tracking a "last resolved IP" alongside `resolved_company_id`); (b)
switch `AgentVisit` to a per-visit-window model (e.g. resolve per calendar day or per distinct IP)
instead of one row per vendor+token forever; (c) accept the current one-shot-per-tuple semantics as
intentional and document it clearly as a product limitation ("the company shown is the first company
observed for this vendor, not necessarily the most recent"). Needs a fresh RESEARCH + INNOVATE pass
on the tradeoffs; out of scope for Phase 5's locked blast radius.

## Status

Open. Not scheduled. Revisit if user feedback or lead-quality metrics show stale/incorrect company
attributions for agent-derived leads.
