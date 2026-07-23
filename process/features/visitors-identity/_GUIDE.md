# visitors-identity

<!-- Part of Beam -->

## Scope

The core visitor pipeline: raw pixel events → visitor aggregation + intent scoring → identity resolution waterfall (person-level from IP/fingerprint) → profile enrichment (job, company, socials) → optional OSINT deep scan. Covers provider budgets/caps, the owned identity graph, and privacy gates (GPC/DNT, suppression, do_not_resolve).

## Key Source Files

- `apps/api/services/identity_resolver.py` — waterfall orchestration (RB2B → Leadpipe → Capturify → PDL → ipinfo/Hunter/Apollo), budget + 30-day-no-retry gates; `_graph_node_by_email` now returns full profile fields (owned-data-layer, 23-07-26)
- `apps/api/services/enricher.py` — tiered enrichment (PDL/Proxycurl/Twitter) + Gemini grounded deep research
- `apps/api/services/osint_scanner.py`, `apps/api/services/social_resolver.py` — OSINT engines (holehe/maigret/user-scanner), handle resolution
- `apps/api/services/company_resolver.py`, `apps/api/services/geoip*.py` — company-from-IP, ASN/datacenter filtering; write-through to `company_graph` + read-time staleness re-validation (owned-data-layer, 23-07-26, `company_graph_enabled` — default OFF)
- `apps/api/services/identity_signals.py` — SendGrid open/click corroborating signals: `record_signal()` (4 write gates), `decay_confidence()`, `corroborate_identity()` (join-only, zero `IdentifiedVisitor` write access) (owned-data-layer, 23-07-26, `identity_signals_enabled` — default OFF)
- `apps/api/models/company_graph.py` — `CompanyGraphNode`, durable cross-tenant company-from-IP store
- `apps/api/models/identity_signal.py` — `IdentitySignal`, one row per SendGrid open/click corroborating event (PII ciphertext + blind index, same pattern as `beam_identity_graph`)
- `apps/api/routers/visitors.py` (+ `visitors_helpers.py`) — list/stats/identify endpoints, `_compute_visitor_stat_counts`
- `apps/api/models/visitor.py` — `Visitor`, `IdentifiedVisitor`; `apps/api/models/enrichment.py` — `EnrichmentProfile`
- `apps/api/models/beam_identity.py` — `BeamIdentityNode` (cross-tenant identity graph); gained nullable `city`/`region`/`country` (owned-data-layer, 23-07-26)
- `apps/api/tasks/resolution_tasks.py`, `apps/api/tasks/aggregation_tasks.py` — sweeps

## Related Context

- `process/context/all-context.md` — Business Guardrails #2 (budgets) + #3 (PII) are load-bearing here; see "Owned Identity Data Layer" section for `company_graph`/`identity_signals`
- `process/context/tests/all-tests.md` — integration lane covers resolution/budget/aggregation

## Current Status

Status: stable — waterfall + budgets shipped; provider mix tuned via `*_ENABLED` env toggles.
Owned data layer (`company_graph` cross-tenant durable store + `identity_signals` SendGrid
open/click corroboration) shipped 23-07-26, code-complete + unit-verified, both flags default
OFF — pending Docker-gated integration/migration verification before archival. See
`active/owned-data-layer_23-07-26/` and `backlog/owned-data-layer-docker-verification_NOTE_23-07-26.md`.

## Folder Contents

```
process/features/visitors-identity/
  active/       -- in-progress plans (each task in a {slug}_{date}/ folder)
  completed/    -- archived completed plans
  backlog/      -- deferred/future plans
```

All artifacts colocate inside each `{slug}_{date}/` task folder. Do NOT create `reports/` or `references/` sibling dirs.
