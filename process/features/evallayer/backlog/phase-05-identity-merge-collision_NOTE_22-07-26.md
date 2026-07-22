---
name: plan:evallayer-phase-05-identity-merge-collision-note
description: "Backlog: real human visitor can inherit an agent-origin non-emailable marker via IdentifiedVisitor email-dedup merge collision — lead-loss data-quality bug, not a safety violation — NEW PLAN REQUIRED"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: backlog
---

# Backlog — Identity Merge Collision (Agent-Origin Marker Leaking to a Real Human Lead)

**Source:** Phase 5 (Company resolution → outreach feed) PVL, `vc-security` STRIDE pass, 22-07-26.

## Gap

`apps/api/services/identity_resolver.py::_save_identified` has a pre-existing email-dedup path
(lines 704-731, unmodified by Phase 5): if a resolved email already matches a DIFFERENT, existing
`IdentifiedVisitor` row (matched by `email`, not `visitor_id`), the function returns that existing
`canonical` row instead of creating a new one, and sets the CURRENT visitor's
`canonical_visitor_id` to point at it.

Company-level providers (Hunter/Apollo) return "an arbitrary employee" at a resolved domain — the
same employee email can legitimately recur across different visitors from the same company
network (this is explicitly expected/accepted behavior for human resolution too).

Phase 5's synthetic-visitor sweep (`agent_company_resolution.py`) creates agent-derived
`IdentifiedVisitor` rows carrying `source_agent_visit_id` (non-emailable, per Phase 7's guard). If:

1. The sweep resolves an agent visit FIRST, creating an agent-marked `IdentifiedVisitor` for
   `jane@company.com`.
2. LATER, a REAL human visitor from the same company network is independently resolved by the
   normal human pipeline (`resolution_runner`, `resolution_tasks`, or the manual Identify button),
   and Hunter/Apollo returns the SAME `jane@company.com` for that human visitor.

...then `_save_identified`'s email-dedup path merges the REAL human visitor into the
agent-marked canonical row. Since `is_emailable_identity` checks the canonical row's
`source_agent_visit_id`, the real human's identity is now (incorrectly) treated as non-emailable —
a legitimate lead is silently lost, forever (no re-resolution retry undoes this).

## Severity

Lead-loss / data-quality bug. **Not a safety violation** — the failure mode errs toward
over-exclusion (a real human never gets incorrectly emailed as a byproduct; the risk is the
opposite: a real human never gets emailed even though they should be). Accepted as a known,
non-blocking residual for Phase 5's own Gate.

## Suggested fix (future plan)

When a NON-agent-origin `resolve()` call merges into a canonical row that IS agent-marked
(`source_agent_visit_id is not None`), consider: (a) promoting/re-homing the canonical identity to
drop the agent marker once a genuine human visitor is confirmed at the same email, or (b) creating
a distinct `IdentifiedVisitor` row for the human visitor instead of merging into an agent-marked
canonical (breaks the existing email-dedup invariant — needs careful design). Needs a fresh
RESEARCH + INNOVATE pass; out of scope for Phase 5's locked blast radius.

## Status

Open. Not scheduled. Raise if lead-generation metrics show unexpected drop-off correlated with
agent-resolved company domains.
