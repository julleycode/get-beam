# visitors-identity

<!-- Part of Beam -->

## Scope

The core visitor pipeline: raw pixel events → visitor aggregation + intent scoring → identity resolution waterfall (person-level from IP/fingerprint) → profile enrichment (job, company, socials) → optional OSINT deep scan. Covers provider budgets/caps, the owned identity graph, and privacy gates (GPC/DNT, suppression, sticky `do_not_resolve`, and site-owner explicit Clear via `POST …/clear-privacy-hold`).

## Key Source Files

- `apps/api/services/identity_resolver.py` — waterfall orchestration (RB2B → Leadpipe → Capturify → PDL → ipinfo/Hunter/Apollo), budget + 30-day-no-retry gates; `_graph_node_by_email` now returns full profile fields (owned-data-layer, 23-07-26)
- `apps/api/services/enricher.py` — tiered enrichment (PDL/Proxycurl/Twitter) + Gemini grounded deep research
- `apps/api/services/osint_scanner.py`, `apps/api/services/social_resolver.py` — OSINT engines (holehe/maigret/user-scanner), handle resolution
- `apps/api/services/company_resolver.py`, `apps/api/services/geoip*.py` — company-from-IP, ASN/datacenter filtering; write-through to `company_graph` + read-time staleness re-validation (owned-data-layer, 23-07-26, `company_graph_enabled` — default OFF)
- `apps/api/services/identity_signals.py` — SendGrid open/click corroborating signals: `record_signal()` (4 write gates), `decay_confidence()`, `corroborate_identity()` (join-only, zero `IdentifiedVisitor` write access) (owned-data-layer, 23-07-26, `identity_signals_enabled` — default OFF)
- `apps/api/models/company_graph.py` — `CompanyGraphNode`, durable cross-tenant company-from-IP store
- `apps/api/models/identity_signal.py` — `IdentitySignal`, one row per SendGrid open/click corroborating event (PII ciphertext + blind index, same pattern as `beam_identity_graph`)
- `apps/api/routers/visitors.py` (+ `visitors_helpers.py`) — list/stats/identify endpoints,
  `_compute_visitor_stat_counts`, `POST /{site_id}/{visitor_id}/clear-privacy-hold` (Option D,
  09-08-26 — flips sticky `do_not_resolve` only; audited; no un-suppress / no Identify bypass)
- `apps/api/schemas/visitors.py` — `VisitorOut.do_not_resolve: bool = False` (list/detail)
- `apps/web/src/app/dashboard/visitors/page.tsx` — Privacy hold UI + confirm Clear
- `apps/web/src/lib/api.ts` / `api-types.ts` — `clearPrivacyHold`, `Visitor.do_not_resolve?`
- `tests/integration/test_privacy_hold_clear.py` — 8 Fully-Automated clear/auth/audit/no-unsuppress gates
- `apps/api/models/visitor.py` — `Visitor`, `IdentifiedVisitor`; `apps/api/models/enrichment.py` — `EnrichmentProfile`
- `apps/api/models/beam_identity.py` — `BeamIdentityNode` (cross-tenant identity graph); gained nullable `city`/`region`/`country` (owned-data-layer, 23-07-26)
- `apps/api/tasks/resolution_tasks.py`, `apps/api/tasks/aggregation_tasks.py` — sweeps
- `apps/pixel/src/tracker.js` — first-party capture surface: value-based field matcher, mailto
  click, URL-param, cross-browser autofill, shadow-DOM/same-origin-iframe listeners, per-site
  `data-capture-*` config (first-party-capture, 24-07-26)
- `apps/pixel/e2e/` — Playwright harness for `tracker.js` capture logic (own config,
  chromium/webkit/firefox projects; first automated coverage this file has ever had)
- `apps/api/models/visitor_email.py` — `VISITOR_EMAIL_SOURCES` enum + `normalize_source()`,
  backed by migration `a9f2c1e7b4d6` (`ck_visitor_emails_source` CHECK constraint)

## Related Context

- `process/context/all-context.md` — Business Guardrails #2 (budgets) + #3 (PII) are load-bearing here; see "Owned Identity Data Layer" section for `company_graph`/`identity_signals`
- `process/context/tests/all-tests.md` — integration lane covers resolution/budget/aggregation

## Current Status

Status: stable — waterfall + budgets shipped; provider mix tuned via `*_ENABLED` env toggles.

Owned data layer (`company_graph` cross-tenant durable store + `identity_signals` SendGrid
open/click corroboration), shipped 23-07-26, **VERIFIED 24-07-26** (Docker-gate closure: migration
round-trip clean, integration + unit regression green). Both flags (`company_graph_enabled`,
`identity_signals_enabled`) still default OFF — flipping either in a real environment remains a
separate explicit operator action. Archived: `completed/owned-data-layer_23-07-26/`. Resolved
backlog note: `backlog/owned-data-layer-docker-verification_NOTE_23-07-26.md`.

First-party capture expansion (value-based field matching, mailto/URL-param, cross-browser
autofill, shadow-DOM/same-origin-iframe capture feeding `visitor_emails`), shipped 24-07-26,
**VERIFIED 24-07-26** (Docker/browser-gate closure: webkit/firefox autofill legs green,
`do_not_resolve` integration re-confirm green — all 15/15 SPEC ACs now met). Archived:
`completed/first-party-capture_24-07-26/`. Resolved backlog note:
`backlog/first-party-capture-deferred-gates_NOTE_24-07-26.md`.

Privacy-hold Clear (Option D): archived
`completed/privacy-hold-clear_09-08-26/` (10-08-26, WITH_GAPS). Backend EVL green; Hybrid e2e
+ counsel copy still open — see
`backlog/privacy-hold-clear-e2e-auth-harness_NOTE_09-08-26.md` and
`backlog/privacy-copy-counsel-review_NOTE_07-08-26.md`.

Open followups (not blocking archived plans): 5 unrelated pre-existing integration test
failures (evallayer/handoff-detection, intent-signals, ai-referral — cross-feature triage needed)
and a conftest Redis-isolation hardening recommendation. See
`backlog/post-docker-gate-followups_NOTE_24-07-26.md`.

## Folder Contents

```
process/features/visitors-identity/
  active/       -- in-progress plans (each task in a {slug}_{date}/ folder)
  completed/    -- archived completed plans
  backlog/      -- deferred/future plans
```

All artifacts colocate inside each `{slug}_{date}/` task folder. Do NOT create `reports/` or `references/` sibling dirs.
