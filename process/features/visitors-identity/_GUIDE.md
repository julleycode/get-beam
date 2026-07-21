# visitors-identity

<!-- Part of Beam -->

## Scope

The core visitor pipeline: raw pixel events → visitor aggregation + intent scoring → identity resolution waterfall (person-level from IP/fingerprint) → profile enrichment (job, company, socials) → optional OSINT deep scan. Covers provider budgets/caps, the owned identity graph, and privacy gates (GPC/DNT, suppression, do_not_resolve).

## Key Source Files

- `apps/api/services/identity_resolver.py` — waterfall orchestration (RB2B → Leadpipe → Capturify → PDL → ipinfo/Hunter/Apollo), budget + 30-day-no-retry gates
- `apps/api/services/enricher.py` — tiered enrichment (PDL/Proxycurl/Twitter) + Gemini grounded deep research
- `apps/api/services/osint_scanner.py`, `apps/api/services/social_resolver.py` — OSINT engines (holehe/maigret/user-scanner), handle resolution
- `apps/api/services/company_resolver.py`, `apps/api/services/geoip*.py` — company-from-IP, ASN/datacenter filtering
- `apps/api/routers/visitors.py` (+ `visitors_helpers.py`) — list/stats/identify endpoints, `_compute_visitor_stat_counts`
- `apps/api/models/visitor.py` — `Visitor`, `IdentifiedVisitor`; `apps/api/models/enrichment.py` — `EnrichmentProfile`
- `apps/api/tasks/resolution_tasks.py`, `apps/api/tasks/aggregation_tasks.py` — sweeps

## Related Context

- `process/context/all-context.md` — Business Guardrails #2 (budgets) + #3 (PII) are load-bearing here
- `process/context/tests/all-tests.md` — integration lane covers resolution/budget/aggregation

## Current Status

Status: stable — waterfall + budgets shipped; provider mix tuned via `*_ENABLED` env toggles.

## Folder Contents

```
process/features/visitors-identity/
  active/       -- in-progress plans (each task in a {slug}_{date}/ folder)
  completed/    -- archived completed plans
  backlog/      -- deferred/future plans
```

All artifacts colocate inside each `{slug}_{date}/` task folder. Do NOT create `reports/` or `references/` sibling dirs.
