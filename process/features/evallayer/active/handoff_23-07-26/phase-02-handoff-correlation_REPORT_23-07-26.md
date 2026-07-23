---
phase: phase-02-handoff-correlation
date: 2026-07-24
status: COMPLETE_WITH_GAPS
feature: evallayer
plan: process/features/evallayer/active/handoff_23-07-26/phase-02-handoff-correlation_PLAN_23-07-26.md
---

# Phase H2 — Handoff Correlation + Dashboard — EXECUTE Report

**TL;DR:** All checklist items A1–E8 shipped. Fetch↔click correlation now links on-demand
agent fetches to human AI-referral clicks, surfaced as a confidence-qualified dashboard badge.
AC-H2-3 (emailability separation — program hard gate) proven green. 899 unit tests pass (0
failures), FE builds clean. One Docker-gated Hybrid gap (live-DB sweep + migration cycle) remains
as an accepted known-gap — same precedent as H1. Not committed.

## What Was Done

- **A. Model + migration** — `apps/api/models/agent_handoff_link.py` (`AgentHandoffLink`, table
  `agent_handoff_links`; no FK; UNIQUE(agent_fetch_event_id); 2 indexes). Migration
  `e2a4c7f81b93_add_agent_handoff_links_table.py`, additive-only, `down_revision=a3e9f1c7d2b5`
  (re-verified live via `alembic heads` at EXECUTE — single head, unchanged since PVL). Registered
  in `apps/api/main.py`.
- **B. Sweep** — `apps/api/services/agent_handoff_correlation.py::run_handoff_correlation_sweep`.
  Unlinked on-demand fetch events (NOT EXISTS link, <60min, batch limit 20) → same-site pageviews
  in the 30-min window → `classify_ai_source` vendor-family match → best candidate (exact-page
  first, then smallest delta) → confidence (high/medium, Perplexity-capped, **no low writes**).
  Fail-open per row (own commit, keys-only logs). Config
  `handoff_correlation_sweep_interval_minutes=10`; own `scheduler.add_job` registered BEFORE
  Phase 3's future job slot.
- **C. Emailability separation** — confirmed by construction + absence-tripwire: neither new H2
  file references the agent-origin marker or the emailability guard. `identity_classification.py`
  untouched.
- **D. API + FE** — `VisitorDetailOut` +5 nullable handoff fields; detail endpoint data-merge
  (latest link, joined to fetch event). `AgentAnalyticsResponse.handoff_links_count` +
  `fetch_handoff_links_count` sibling DB fn (pure `aggregate_agent_analytics` contract preserved) +
  endpoint wiring. `api-types.ts` (`VisitorDetail`, `AgentAnalytics`, list `Visitor`). Visitor-detail
  hero badge + InfoRow (PROBABILISTIC copy, never certainty), visitor-list pill, agents-page count.
- **E. Tests** — `tests/unit/test_handoff_correlation.py` (24 cases: window/vendor/tie/confidence/
  Perplexity-cap/no-low-writes/cross-site/page-None), `tests/unit/test_handoff_emailability_separation.py`
  (AC-H2-3 both directions + real-row non-vacuity + absence-tripwire),
  `tests/unit/test_agent_aggregator.py` extended (count present + query-isolation),
  `tests/integration/test_handoff_correlation_integration.py` (Docker-gated, written + collect-clean).

## What Was Skipped or Deferred

- Live-DB sweep round-trip + Alembic up/down cycle — Docker daemon unresponsive in sandbox.
  Integration test written + collect-clean; commands recorded in the backlog note. Known-gap.

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| New H2 unit files | pytest test_handoff_correlation + emailability + aggregator | 35 passed |
| AC-H2-3 hard gate | pytest test_handoff_emailability_separation -v | PASS |
| Full unit regression | pytest tests/unit -q | 899 passed, 2 skipped, 0 failures |
| Registration smoke | agent_handoff_links in Base.metadata | True |
| FE build | cd apps/web && npm run build | PASS |
| Live DB + migration cycle | (Docker-gated) | KNOWN-GAP (collect-clean) |

## Plan Deviations

Two within-blast-radius deviations (same named files; additive; /goal auto-continue):
1. **List-pill data field** — the plan required a D6 list-row pill but scoped the handoff field
   only to `VisitorDetailOut`. Added one nullable `handoff_confidence` to `VisitorOut` + a single
   bulk query in `list_visitors` (no N+1) + the TS `Visitor` interface field to actually feed the
   pill. Additive/nullable public-API extension, consistent with the plan's own API-extension intent.
2. **`fetch_site_id` param** — added site-id filtering into the pure `correlate_fetch_to_clicks`
   as AC-H2-5 defense-in-depth (belt-and-suspenders with the SQL site filter) so cross-site
   exclusion is provable in a DB-free unit test.

Migration filename hash `e2a4c7f81b93` invented per Alembic convention. No hard-stop-class deviations.

## Test Infra Gaps Found

- No SQLite-compatible unit path for the sweep's DB layer (postgresql.UUID) — correlation logic is
  fully covered via pure functions instead; live-DB behavior stays Docker-gated (consistent with the
  whole EvalLayer/Handoff program).

## EVL Confirmation (Independent Re-Run)

Orchestrator-driven EVL re-ran the validate-contract gate commands independently of EXECUTE's own
claims — all GREEN, no fix cycles needed:

| Gate | Result |
|---|---|
| Target unit files (correlation + emailability + aggregator extension) | 21/21 passed |
| Full unit regression | 899 passed, 0 failures |
| FE build (`cd apps/web && npm run build`) | PASS |
| `agent_handoff_links` registration + indexes | confirmed present in `Base.metadata` |
| Migration head | single head `e2a4c7f81b93`, linear chain, no fork |
| AC-H2-3 (emailability separation, hard gate) | PASS — zero-diff structural check (no new code path into `is_emailable_identity()`), zero literal references to `source_agent_visit_id` in either new H2 file (tripwire), zero joins from `agent_handoff_links`/`agent_fetch_events` into any outreach/campaign table |
| Dashboard badge copy | confirmed probabilistic ("X fetched this page N min earlier — [confidence] confidence"), no unqualified-certainty language found |

Known-gap unchanged: live-DB sweep round-trip + Alembic up/down cycle — Docker-gated, tracked in
`handoff-program-docker-verification-gaps_NOTE_23-07-26.md` (H2 rows).

## Capability Statement

**H2 makes the program's core differentiator code-complete: an on-demand AI fetch (a human
actively asking an AI agent about the product right now) links to that human's own click-through
— resolving "the human behind the agent" at high/medium confidence, with the linked human's
emailable status completely untouched and the linked agent-fetch record permanently unemailable.**
This is the shippable v1 of the "human behind the agent" story, gated only on Docker-gated live
verification (H1's identical precedent), not on any remaining design or code work.

## Closeout Packet

- **Selected plan:** `process/features/evallayer/active/handoff_23-07-26/phase-02-handoff-correlation_PLAN_23-07-26.md`
- **Finished:** all A1–E8; AC-H2-3 green; emailability guard untouched (tripwire green); no-low-writes
  enforced; probabilistic badge copy; head used `a3e9f1c7d2b5`.
- **Verified:** 899 unit pass, FE build, registration smoke. **Unverified:** live-DB sweep + migration
  cycle (Docker-gated known-gap).
- **Remaining cleanup:** UPDATE PROCESS (archive-state update, commit next via vc-git-manager).
  High-risk evidence pack already present at `harness/*-phase-h2.json`.
- **Classification:** 🔨 CODE DONE (Docker gaps) — EVL confirmed GREEN on all Fully-Automated/Hybrid-non-Docker
  gates; 1 Docker-gated Hybrid known-gap remains (tracked in backlog note), consistent with H1's
  precedent for `VERIFIED`-adjacent status.
- **Best next state:** UPDATE PROCESS closeout (this document), then Phase 3 (H3) Step 0 —
  RESEARCH.

## Forward Preview

- **Test Infra Found:** pure-function correlation testing pattern (SimpleNamespace fixtures +
  deterministic clock) reusable for H3 intent-signal logic.
- **Blast Radius Changes:** new `agent_handoff_links` table + migration `e2a4c7f81b93`. `scheduler.py`
  now has the H2 job registered — **H3 must additively append its spike-detector job AFTER re-reading
  this diff** (umbrella Pre-PVL Conflict Resolution; H2 registered first, as planned).
- **Commands to Stay Green:** `pytest tests/unit -q`; `cd apps/web && npm run build`.
- **Dependency Changes:** none. New pending migration `e2a4c7f81b93` (4th in the shared chain:
  `c4e8f1a9d2b7` → `f8a2c1d9b3e7` → `a3e9f1c7d2b5` → `e2a4c7f81b93`) — apply before enabling in any
  real environment.
