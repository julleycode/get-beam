# Plan: Cookie + Fingerprint Phase 2 (first-party hardening)

**Status:** approved (`approve --fast`) · **Date:** 2026-08-02  
**Scope:** local/UAT · **Out:** vendor pixel, RB2B API, schema migrations

## Changes

1. `apps/pixel/src/tracker.js` — `xhr.withCredentials = true`
2. `apps/api/main.py` — ingest CORS echo Origin + `Allow-Credentials`
3. `apps/api/routers/events.py` — visitor stub before FP/svid write-once stamp
4. Tests — pixel credentials assert + ingest CORS/FP/svid integration

## Acceptance

- [x] Credentialed CORS on ingest with Origin
- [x] FP persists on first ingest without waiting for aggregator
- [x] svid cookie ≠ client id stamps `server_visitor_id`
- [x] FP/svid survive full aggregation + pageviews filled (follow-up test)
- [x] 403 deleted-site clears svid with credentialed CORS headers

## Review follow-up ([code-reviewer](3bb47479-2bf1-46fa-9af0-ffd24c53f3e5))

- **Accepted risk:** open-pixel ingest echoes any `Origin` + credentials (CSRF/cookie attach trade-off); no allowlist this phase.
- **Fixed:** atomic stub+FP/svid upsert; `first_seen` from event `ts` + aggregator `LEAST`; tests for 403 CORS + post-aggregate survival.
