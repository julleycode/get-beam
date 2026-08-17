# PVL Iteration 005 — site-analysis-onboarding

- **Date:** 2026-08-13
- **Loop:** PVL, cycle 3 supplement applied (fix leg; interrupted by machine sleep, resumed, audit confirmed 14/17 landed pre-interruption, 3 coherence items completed on resume)
- **Result:** SUPPLEMENT_APPLIED — 17 gaps; plan 1734 lines; validator 0 failures (1 known false-positive warning)

## Key changes

- **D15** `message` derived at read time, never persisted (no 6th column).
- **D16** PUT preserves in-flight `pending` (status/started_at untouched); PUT with NULL candidate allowed; `analyzed_at` single-writer (task only).
- **D17** fourth panel state `none` + budget-gated Analyze button (AC-8 reachable for pre-existing sites).
- C17+VF2: mock-OFF delta gate hardened — consumer-binding patch targets, E12 transport guard extended, delta window after create-task settles, await via `asyncio.gather(*_analysis_tasks)`, terminal-ready assertion. C20 same treatment for unit gate.
- VC5 render rule (`candidate ?? profile`; failed = banner above); VC6 `_analysis_inflight` → service module, done-callback discard; VC7 D13 4-case table, null=known-empty; VC8 positive scheme+hostname check (javascript: case gated); VC9 `promote: bool` dismiss path; C19 five-column strings; N11 SPEC narrative pointer; N12 `(site_id)` signature + explicit projection.

## Open item for cycle-4 verifier

- GET can now return confirmed profile with `status: "pending"` (PUT-during-pending decided behavior) — check no panel branch mis-reads that combination.
- Cycle-2 deviations table keeps superseded "survives strip_url" wording as history (deliberate).

## Next

Re-validate cycle 4 (validate from V1 + verifier spot-check). Trend: FAILs 4→2→0; verifier fail-eq 5→3→?
