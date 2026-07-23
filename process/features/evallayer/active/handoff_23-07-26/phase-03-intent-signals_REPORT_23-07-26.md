---
phase: phase-03-intent-signals
date: 2026-07-24
status: COMPLETE_WITH_GAPS
feature: evallayer
plan: process/features/evallayer/active/handoff_23-07-26/phase-03-intent-signals_PLAN_23-07-26.md
---

# Phase H3 — Intent Signals — Execution Report

**TL;DR:** All checklist items A1–E6 shipped exactly per the CONDITIONAL-accepted
validate-contract. Both PVL corrections applied (html.escape on alert copy;
company-correlation as a sibling DB-fetch preserving the pure aggregate). 24 new
unit tests + 1 updated aggregator shape test all green; full unit suite 924 passed,
0 failures; FE `npm run build` exit 0. One Docker-gated live-sweep gate stays a
known-gap (daemon unresponsive — matches H1/H2). Two within-blast-radius deviations
recorded below. No commit (per instructions).

## What Was Done

- **A — pure module `apps/api/services/agent_intent_signals.py` (new):**
  `COMMERCIAL_PAGE_PREFIXES` (locked 7-element frozenset), pure `is_commercial_page`
  (rstrip/lower normalize + `==`/`startswith(prefix+"/")` boundary rule — `/pricing-blog`
  correctly excluded), pure `detect_spike` (floor `>=3` gates before `>=2×` multiplier),
  and `run_intent_signal_sweep(db)` (distinct on-demand (site,page) pairs in the 24h
  window → commercial filter → per-pair alert + spike, fail-open per pair).
- **B — `hot_alert.maybe_send_intent_alert` sibling** (existing `maybe_send_hot_alert`
  untouched): `hot_alert_enabled` gate, Redis `SET NX EX` dedup (24h TTL), SITE-level
  copy, `html.escape()` on BOTH `page_path` and `vendor` before interpolation (E-B1),
  body built from escaped fragments (no raw f-string).
- **C — config + scheduler:** `intent_signal_sweep_interval_minutes: int = 10` in
  `config.py`; new `_intent_signal_sweep_job` + `scheduler.add_job(...)` registered
  additively immediately AFTER H2's `handoff_correlation_sweep` (re-verified live at
  lines 233-239 before insertion, zero drift — E-C4).
- **D — analytics + FE (additive):** new sibling DB-fetch
  `fetch_recent_ai_researched_companies(db, site_id)` in `agent_aggregator.py` using the
  `company_graph` join as the primary path (`CompanyGraphNode.ip == AgentFetchEvent.ip_address`,
  `CompanyGraphNode.domain == Company.domain`, `Company.site_id == site_id`, 48h window,
  commercial filter, cap 20 desc), empty-list fallback when `company_graph_enabled` is
  False (E-D1). `aggregate_agent_analytics` stays PURE — new field echoed via an optional
  param. Wired into the `/agents/{site_id}/analytics` endpoint. `RecentAiResearchEntry`
  schema + `AgentAnalyticsResponse` extension; `AgentAnalytics`/`RecentAiResearchEntry`
  TS interfaces; new "Appeared after AI research" card (read-only, no action affordances,
  EmptyState-safe).
- **E — tests:** `tests/unit/test_intent_alerts.py` (24 tests) + Docker-gated
  `tests/integration/test_intent_signal_integration.py` (2 tests, collect-clean).

## What Was Skipped or Deferred

- **Live scheduler-tick → sweep → email delivery (Docker-gated Hybrid):** known-gap —
  Docker daemon unresponsive in the sandbox (`docker ps` 30s timeout → backgrounded, same
  precedent as H1/H2). Integration test written + collect-clean; runs when infra is available.
- **`company_graph` join populated case:** contingent on `company_graph_enabled=true` +
  seeded `CompanyGraphNode` rows. Default deployment (flag off) degrades to an empty list
  by design — documented, not silently dropped.
- **Per-site commercial-page config:** out of scope; backlog note already exists
  (`phase-03-per-site-commercial-page-config_NOTE_24-07-26.md`).

## Test Gate Outcomes

| Gate | Result |
|---|---|
| `tests/unit/test_intent_alerts.py` (24 tests) | PASS |
| Full `tests/unit` suite | 924 passed, 2 skipped, 0 failures |
| `cd apps/web && npm run build` | exit 0 |
| Docker-gated live sweep e2e | KNOWN-GAP (daemon down); integration file collect-clean (2 tests) |

Every Fully-Automated validate-contract row is green. The only non-green gate is the
pre-documented Docker-gated Hybrid residual (gap-resolution D).

## Plan Deviations

Both within-blast-radius (documented per /goal deviation protocol; no hard-stop class touched):

1. **`maybe_send_intent_alert` signature** — added explicit `vendor` param (per the task-prompt
   signature) and an optional `multiplier` param for spike copy, rather than deriving vendor
   inside the function. Vendor derivation (single-vendor vs. collective "AI agents") moved into
   the sweep's `_dominant_vendor` helper. Semantically identical to the plan; cleaner separation.
2. **Spike dedup key** — the spike variant uses a separate `intent_alert:spike:{site_id}:{page_path}`
   key so a baseline alert and a spike alert for the same page can both fire in a day (the plan's
   intent that "spike also sends"). The baseline alert keeps the plan-locked
   `intent_alert:{site_id}:{page_path}` key verbatim. Correctness improvement within blast radius.

## Test Infra Gaps Found

None new. The Docker-daemon-unavailable constraint is the same program-wide gap already tracked in
`process/features/evallayer/backlog/handoff-program-docker-verification-gaps_NOTE_23-07-26.md`
(H3 rows pre-authored at PVL; no new note needed).

## Closeout Packet

- **Selected plan:** `process/features/evallayer/active/handoff_23-07-26/phase-03-intent-signals_PLAN_23-07-26.md`
- **Finished:** A1–E6 complete; 9 source files modified within blast radius + 2 test files.
- **Verified:** all Fully-Automated gates green (unit + FE build). **Unverified:** live
  scheduler→email round-trip and the populated `company_graph` join case (Docker-gated).
- **Cleanup remaining:** EVL confirmation run (orchestrator spawns vc-tester), then UPDATE PROCESS
  archival. No commit performed (per instructions).
- **Classification:** Keep in active/testing — code-complete, EVL confirmation + Docker-gated
  verification pending.
- **Registry:** H3 entry annotated `status: DONE`.

## Forward Preview

### Test Infra Found
- Unit-level Redis/EmailSender mocking via monkeypatch (no DB) works cleanly for alert-path tests.
- `test_db` integration fixture available for the Docker-gated round-trip when infra returns.

### Blast Radius Changes
- No expansion beyond the PVL-confirmed 9 files, plus the additive test files and the one
  pre-existing aggregator shape test updated for the additive `recent_ai_researched_companies` field.

### Commands to Stay Green
```bash
.venv/bin/python -m pytest tests/unit/test_intent_alerts.py -q
.venv/bin/python -m pytest tests/unit -q
cd apps/web && npm run build
```

### Dependency Changes
- None. No new package, no migration, no schema change. New runtime surface = one additive
  APScheduler interval job (`intent_signal_sweep`, 10-min cadence) gated by the existing
  `hot_alert_enabled` per-site toggle.

## Follow-up Stubs Created
- Docker-gated integration test `tests/integration/test_intent_signal_integration.py` (collect-clean;
  close command tracked in the program Docker-verification backlog note).

## CONTEXT_PARTIAL items
- None.

## EVL Confirmation (UPDATE PROCESS, 24-07-26)

Independent re-run of the gate commands, not just execute-agent's self-report:

| Gate | Result |
|---|---|
| `tests/unit/test_intent_alerts.py` (24 tests) | PASS (re-confirmed) |
| Full `tests/unit` suite | **922 passed, 1 failed, 2 skipped** (see count note below) |
| `cd apps/web && npm run build` | exit 0 (re-confirmed) |
| `git diff --stat` on the 9-file H3 blast radius | matches plan exactly — no drift, no scope creep |

**923-vs-924 count note:** the test count is not stable session-to-session because this repo
has concurrent in-flight sessions touching foreign test files. At EXECUTE time the H3 report
recorded "924 passed, 2 skipped, 0 failures". At this EVL confirmation pass the same command
now reports 922 passed, 1 failed, 2 skipped. **All of H3's own 24 tests still pass unchanged.**
The shift and the new failure are both attributable to a **foreign, concurrent session**, not
to H3:

- `tests/unit/test_pixel.py::TestPixelSize::test_source_under_20kb` now FAILS — root cause
  confirmed via `git diff --stat -- apps/pixel/`: `apps/pixel/src/tracker.js` was modified
  (+59/-2 lines, pixel source now 22760 bytes, budget is 20000) by the parallel
  `first-party-capture_24-07-26` session (visible in `git status` as untracked
  `process/features/visitors-identity/active/first-party-capture_24-07-26/` +
  `apps/pixel/e2e/`, `apps/pixel/playwright.config.ts`). H3 touched zero files under
  `apps/pixel/`.
- **This failure is out of H3's blast radius and does not block H3 closeout.** It is the
  first-party-capture session's responsibility to fix before its own EVL. Flagging here only
  for visibility — no action taken on `apps/pixel/` from this UPDATE PROCESS session.

**Net H3 verdict: unchanged from the phase report — every Fully-Automated gate in H3's own
scope is green.** The Docker-gated live-sweep gate remains the only H3-owned known-gap.

## Known Gaps (Resolved via Backlog)

- Live scheduler tick → sweep → alert email delivery (Docker-gated Hybrid) — tracked in
  `process/features/evallayer/backlog/handoff-program-docker-verification-gaps_NOTE_23-07-26.md`
  (H3 rows already present, pre-authored at PVL; no new note needed).
- `company_graph` join (D1) unexercised against real `CompanyGraphNode` rows — same backlog
  note, H3 row already present.
- Per-site commercial-page configuration — tracked in
  `process/features/evallayer/backlog/phase-03-per-site-commercial-page-config_NOTE_24-07-26.md`.
- (Foreign, non-blocking) `apps/pixel` bundle-size regression (`test_source_under_20kb`) —
  not an H3 gap; owned by the concurrent `first-party-capture_24-07-26` session.
