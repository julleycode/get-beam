---
name: note:handoff-phase-03-per-site-commercial-page-config
description: "H3 intent signals ships a fixed COMMERCIAL_PAGE_PREFIXES constant, not per-site configurable — backlog for a future config surface"
date: 24-07-26
metadata:
  node_type: memory
  type: backlog
  feature: evallayer
  phase: phase-03
---

# Backlog: per-site commercial-page configuration (H3)

Phase 03 (Intent Signals) of the Handoff Detection program ships a fixed module-level
`COMMERCIAL_PAGE_PREFIXES` constant in `apps/api/services/agent_intent_signals.py`:

```
{"/pricing", "/demo", "/signup", "/compare", "/vs", "/plans", "/trial"}
```

This is not configurable per site. Some sites may use different path conventions
(`/get-started`, `/book-a-demo`, localized paths, etc.) and would get zero alert coverage
until this is addressed.

## Deferred scope

- Add a per-site `commercial_page_patterns` field (Site model or JSON config column)
- Surface a settings UI for founders to customize their own commercial-page list
- Fall back to the current fixed default list when unset

## Why deferred

Out of scope for H3's initial ship — the fixed list covers the common SaaS convention and
unblocks the core alert/spike/correlation mechanics without a schema change. Revisit once
real usage data shows the fixed list is missing significant traffic for non-standard sites.
