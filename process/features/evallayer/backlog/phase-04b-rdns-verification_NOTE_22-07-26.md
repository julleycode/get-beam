---
name: plan:evallayer-phase-04b-rdns-verification-note
description: "Backlog: rdns-verified confidence tier via Forward-Confirmed rDNS (live DNS round-trip), separate mechanism from CIDR-based ip-verified"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: backlog
---

# Backlog — Phase 04b: rDNS Verification (Forward-Confirmed rDNS)

**Deferred from:** Phase 04 (IP-range verification)

## What this is

Phase 04 ships `ip-verified` confidence via static CIDR-range matching (no network I/O,
pure logic). A higher-confidence tier — `rdns-verified` — requires Forward-Confirmed
reverse DNS (FCrDNS): reverse-resolve the visitor IP, then forward-resolve the returned
hostname and confirm it matches the original IP and an expected vendor domain suffix
(e.g. `*.googlebot.com`, `*.search.msn.com`-style patterns for the AI-crawler vendors
that publish rDNS conventions).

## Why deferred

- Requires a live DNS round-trip per visit (2 lookups), which is a new external-call
  surface needing its own mock path, budget/rate considerations, and async/best-effort
  wiring — distinct enough from the static-file CIDR check to warrant its own phase.
- Not blocking for Phase 04 exit gate per SPEC AC8 (ip-verified is sufficient to prove
  the confidence-tier mechanism works end-to-end).

## Scope for a future phase

- New service function `verify_rdns(vendor: str, ip: str) -> str | None` doing the
  forward-confirm round trip, fail-open, with a mocked DNS resolver path under
  `MOCK_EXTERNAL_APIS=true`.
- Extend `verification_method` enum with `rdns-verified` (ranked above `ip-verified`).
- Async/best-effort sweep, same non-blocking pattern as Phase 04's `run_verification_sweep`.

## Not started — no code written for this yet.
