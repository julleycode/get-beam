---
name: note:e2e-local-smoke-concerns
description: "Open concerns carried out of the 10-08-26 local E2E + smoke run (DONE_WITH_CONCERNS) when its task folder was archived by the 14-11-26 repo audit"
date: 14-11-26
metadata:
  node_type: memory
  type: report
  feature: general-plans
---

# Local E2E smoke (10-08-26) — open concerns

**Status:** open. Source report (archived 14-11-26):
`process/general-plans/completed/e2e-local-smoke_10-08-26/GETBEAM_E2E_SMOKE_REPORT_10-08-26.md`.
The run ended DONE_WITH_CONCERNS. None of the items below were re-tested by the 14-11-26 audit —
re-check each against current `main` before acting on it.

## Fixed during the run

- P0: CORS `127.0.0.1` vs `localhost` — fixed in `apps/api/main.py` in that session.

## Still open (as recorded on 10-08-26)

| Pri | Item |
|---|---|
| P1 | Agents `by_vendor` count does not match the expected aggregate |
| P1 | Sites path with trailing slash returns a 307 redirect (client/API path hygiene) |
| P1 | Social UI fails silently when provider keys are empty (no "not configured" message) |
| P1 | Pixel verify only covered the local beamlab path, not a remote production-like URL |
| P2 | Segments UI copy says "10+" while the API threshold is >= 3 |
| P2 | Connectors surface returns 501 — product decision needed (implement or hide) |
| P2 | Feed only partially verified — needs a stable seed dataset |

## Never tested (blocked by environment)

| Flow | Reason |
|---|---|
| Social OAuth end to end | provider keys empty |
| Campaigns create/send | needs an enriched segment |
| Billing / Gumroad checkout + webhook | Gumroad env unset |
| Connectors full CRUD | 501 |

## Suggested retest order

Seed an enriched segment, then Segments, Campaigns, Feed, Connectors, Billing.
