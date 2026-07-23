---
phase: phase-01-fetch-events-tiering
date: 2026-07-23
status: COMPLETE_WITH_GAPS
feature: evallayer
plan: process/features/evallayer/active/handoff_23-07-26/phase-01-fetch-events-tiering_PLAN_23-07-26.md
---

# Phase H1 — Per-Hit Fetch Events + Tiering — EXECUTE Report

**TL;DR:** All checklist items A1–E7 implemented per the CONDITIONAL-accepted validate-contract.
6 fully-automated gates green (39 relevant unit tests: 15 new + 24 classifier regression; full
suite 839 passed / 2 skipped, no regression vs 824 baseline). 2 Hybrid gates (Alembic
upgrade/downgrade cycle + E7 retention-purge integration test) remain Docker-gated known-gaps —
written, collect cleanly, pre-accepted at VALIDATE. No hot-path human code touched beyond the one
additive gated call. Fail-open isolation verified in both directions.

## What Was Done

- **B (tier fn):** `agent_classifier.py` — added `_ON_DEMAND_TOKENS` frozenset (5 tokens) +
  `classify_tier(raw_ua_token) -> str` (total function, else-branch = "index", conservative-asymmetry
  docstring). `_VENDOR_TOKENS` untouched.
- **A (model + registration):** new `apps/api/models/agent_fetch_event.py::AgentFetchEvent(Base)`,
  table `agent_fetch_events`, columns per contract (id/created_at/updated_at from Base; no ORM FK on
  site_id). Both indexes declared. Registered in `main.py` immediately after the `AgentVisit` line
  (line 33).
- **A3 (migration):** `c4e8f1a9d2b7_add_agent_fetch_events_table.py`, `down_revision="b3f9a1d2c7e5"`
  (single head re-confirmed via `python -m alembic heads` immediately before write — E1). create_table
  + both indexes; clean reversible downgrade. Additive-only.
- **C (write path + ingest):** `persist_agent_fetch_event(...)` in `agent_visit_persistence.py` —
  plain `insert()`, own try/except, own `db.commit()`, fail-open keys-only warning + rollback + return
  None. `events.py` — extended the two existing top-level import lines (15, 16), added the additive
  call after `persist_agent_visit` inside the existing `if classification is not None:` gate
  (reusing in-scope `ip_address` and `agent_path`).
- **D (retention):** `config.py` — `agent_fetch_event_retention_days: int = 90` (beside
  `event_retention_days`). `retention.py` — new sibling `purge_agent_fetch_events_older_than(...)`
  mirroring `purge_events_older_than` exactly (own advisory lock key, table-exists guard, dry-run
  count path, batched delete). Wired into `scheduler.py::_retention_purge_job` as an independent
  try/except block.
- **E (tests):** new `tests/unit/test_agent_fetch_events.py` (15 cases: E1 tier map all 10 tokens
  parametrized, E2 completeness tripwire, E3 per-hit insert columns, empty-ip coercion, E4 fail-open
  isolation + PII-free log, E5 retention config). E7 `tests/integration/test_retention_purge.py::
  TestAgentFetchEventRetentionPurge` (purge + dry-run, mirrors `patched_retention`/`test_db`).

## What Was Skipped or Deferred

- Alembic upgrade/downgrade cycle against live Postgres — Docker unavailable (`docker ps` hung).
- E7 live run (`test_purges_old_agent_fetch_events`) — same Docker precondition.
Both were pre-accepted Hybrid known-gaps in the validate-contract; both are written and collect clean.

## Test Gate Outcomes

| Gate | Strategy | Result |
|---|---|---|
| `test_agent_fetch_events.py` (15 cases) | Fully-Automated | PASS |
| `test_agent_classifier.py` (24) regression | Fully-Automated | PASS |
| Full unit suite | Fully-Automated | PASS (839 passed, 2 skipped; baseline 824 + 15 new) |
| Model registration smoke | Fully-Automated | PASS (table + 10 cols + 2 indexes on Base.metadata) |
| Alembic single-head re-check (E1) | manual | PASS (single head b3f9a1d2c7e5 at write) |
| Alembic upgrade/downgrade cycle | Hybrid | KNOWN-GAP (Docker unavailable) |
| E7 retention-purge integration | Hybrid | KNOWN-GAP (Docker unavailable); collects clean (2 cases) |
| Ingest hot-path latency spot-check | Agent-Probe | N/A this sandbox — additive DB-only write, no new external/sync call; code review confirms one extra local INSERT round-trip inside the already-gated agent branch, never on the human path |

## Plan Deviations

All within blast radius (documented, autonomous /goal — no hard-stop class):

1. **Migration hash** `c4e8f1a9d2b7` (plan said `<hash>`) — expected placeholder resolution.
2. **tz-aware retention cutoff** — `agent_fetch_events.created_at` is tz-aware (from `Base`
   `server_default now()`), unlike the naive `events.created_at`. Used a separate
   `_AGENT_FETCH_CUTOFF_SQL = "now() - make_interval(days => :days)"` instead of reusing the naive
   `_CUTOFF_SQL`. Correctness necessity within D2's "mirror the shape" instruction; the shape
   (lock/table-exists/dry-run/batched delete) is mirrored exactly.
3. **Extra tests beyond minimum** — added `test_empty_ip_coerced_to_none` and an E7 dry-run variant.
   Additive coverage, within blast radius.
4. Parameterized `_try_acquire_lock`/`_release_lock` with a `key=` arg (default preserves existing
   behavior) so the new purge can use its own advisory-lock key. Backward-compatible.

## Test Infra Gaps Found

- No new gaps. Docker unavailability is the pre-existing, pre-accepted constraint (same class as the
  EvalLayer program). Recorded in `backlog/handoff-program-docker-verification-gaps_NOTE_23-07-26.md`.

## Closeout Packet

- **Selected plan:** `process/features/evallayer/active/handoff_23-07-26/phase-01-fetch-events-tiering_PLAN_23-07-26.md`
- **Finished:** all A1–E7 checklist items; 6 fully-automated gates green; schema-class evidence pack
  (`harness/context-snippets-phase-h1.json`, `harness/verification-phase-h1.json`) written.
- **Verified:** tiering, per-hit persistence, fail-open isolation (both directions), zero regression,
  table registration, single-head migration graph.
- **Still unverified:** live Alembic cycle + E7 live run (Docker-gated).
- **Classification:** Keep in active/testing — code-complete, 2 Docker-gated Hybrid gaps pending a
  live-Postgres environment before VERIFIED.

## Forward Preview

### Test Infra Found
- `tests/integration/test_retention_purge.py` uses `patched_retention` (swaps `retention.async_session`
  to `test_engine`) + `test_db` — reuse this for any future retention integration test.

### Blast Radius Changes
- New: `apps/api/models/agent_fetch_event.py`, migration `c4e8f1a9d2b7`, `tests/unit/test_agent_fetch_events.py`.
- Edited: `agent_classifier.py`, `agent_visit_persistence.py`, `events.py`, `config.py`,
  `retention.py`, `scheduler.py`, `main.py`, `tests/integration/test_retention_purge.py`.
- Migration chain is now linear: `b3f9a1d2c7e5 → c4e8f1a9d2b7 (this phase) → f8a2c1d9b3e7`
  (a parallel owned-data-layer agent chained company_graph onto this migration at 23:30 — no divergent
  head, no conflict).

### Commands to Stay Green
- `.venv/bin/python -m pytest tests/unit/test_agent_fetch_events.py -m unit -q`
- `.venv/bin/python -m pytest tests/unit -q`
- Before enabling `agent_detection_enabled` in any real env: apply migrations in order
  (`d11b39a6c843`, `a1c7e4f92b83`, `b3f9a1d2c7e5`, then `c4e8f1a9d2b7`) and run the two Docker-gated gates.

### Dependency Changes
- None (no new packages). H2 (fetch↔click correlation) reads `agent_fetch_events` — this phase is its
  foundation.

## Follow-up stubs created
- None new. Existing backlog note `handoff-program-docker-verification-gaps_NOTE_23-07-26.md` already
  tracks the two Docker-gated gaps (confirmed present).

## CONTEXT_PARTIAL items
- None.

## EVL — Independent Confirmation Run (UPDATE PROCESS, 23-07-26)

Re-ran the validate-contract gate commands independently (not relying on execute-agent's internal
green claim):

| Gate | Command | Result |
|---|---|---|
| New unit tests | `.venv/bin/python -m pytest tests/unit/test_agent_fetch_events.py -q` | 15/15 PASS |
| Classifier regression | `.venv/bin/python -m pytest tests/unit/test_agent_classifier.py -q` | 24/24 PASS |
| Migration chain | `grep -n "down_revision\|^revision" apps/api/migrations/versions/*.py` | linear single-head confirmed |
| Model registration | inspected `main.py` import block | `AgentFetchEvent` registered on `Base.metadata` |

All GREEN. The two Docker-gated Hybrid gates (Alembic upgrade/downgrade cycle, E7 retention-purge
live run) remain known-gaps — Docker unavailable in this sandbox, same pre-accepted constraint as
the rest of the EvalLayer program. No new gaps found during EVL.

### Foreign-Migration Observation (Program-Level, Not H1's Concern)

Since this report was first written, a **parallel session** (visitors-identity "owned-data-layer"
program) chained two more migrations directly onto H1's revision:

```
b3f9a1d2c7e5 (AI-referral, pre-existing)
  → c4e8f1a9d2b7  (H1 — this phase — agent_fetch_events table)
    → f8a2c1d9b3e7  (foreign — owned-data-layer — company_graph table)
      → a3e9f1c7d2b5  (foreign — owned-data-layer — identity_signals table)
```

This is confirmed **linear** — a single head, no branch, no conflict. It is recorded here purely as
an important cross-program dependency fact: **the parallel owned-data-layer program's live-apply is
now blocked on H1's migration (`c4e8f1a9d2b7`) being committed first**, since Alembic requires the
full chain to apply in order. This is not a defect in H1 — it is a reason to prioritize committing
H1's migration promptly (see commit-checkpoint recommendation below) so the other program is not
stalled.

## Closeout Packet (Full 9-Item Schema — UPDATE PROCESS)

1. **Selected plan path:** `process/features/evallayer/active/handoff_23-07-26/phase-01-fetch-events-tiering_PLAN_23-07-26.md`
2. **Closeout classification:** Ready for UPDATE PROCESS archival is NOT applicable here — phase
   programs archive at program closeout, not per-phase. Correct classification: phase is
   **🔨 CODE DONE (Docker gaps)** — code-complete, EVL-confirmed green on all fully-automated gates,
   2 Docker-gated Hybrid gates remain known-gaps pending a live-Postgres environment.
3. **What was finished:** see "What Was Done" above — full A1-E7 checklist, EVL-confirmed.
4. **Verified vs unverified:** Verified — tiering, per-hit persistence, fail-open isolation both
   directions, zero regression, table registration, linear single-head migration chain (now 2 links
   longer, still linear). Unverified — live Alembic upgrade/downgrade cycle, E7 live retention purge
   (both Docker-gated).
4b. **Validate-contract compliance:** VALIDATE was run; `## Validate Contract` section present in
   the phase plan; Gate: CONDITIONAL, pre-accepted (Docker-gated Hybrid residuals only).
5. **Cleanup done vs still needed:** Done — phase report augmented (this section), umbrella
   `## Current Execution State` + Program Status Table to be updated, blast-radius registry already
   `DONE`. Still needed — commit (deferred to vc-git-manager per user instruction), eventual Docker
   live-apply of the 4-migration chain before `agent_detection_enabled`/handoff features go live.
6. **Single best next valid state:** `Invoke vc-git-manager for a logical execution commit
   (H1's source + migration + tests), then proceed to Phase 2 (H2) research —
   process/features/evallayer/active/handoff_23-07-26/phase-02-handoff-correlation_PLAN_23-07-26.md`
7. **Commit-checkpoint recommendation:** Execution commit recommended before further UPDATE PROCESS
   work — H1's source/migration/test changes are well-tested (EVL-confirmed) and, per the
   foreign-migration observation above, committing promptly unblocks the parallel owned-data-layer
   program. Process-only changes (this report, umbrella state, plan checkboxes) should be committed
   separately after.
8. **Regression status:** No prior phases exist in this program (H1 is the program's first phase) —
   regression checkpoint against previously verified overlapping surfaces is N/A. Cross-checked
   against the shipped EvalLayer suite (`test_agent_classifier.py` 24/24) — no drift.
9. **SPEC achievement:** SPEC AC-H1-1/2/3 (per-hit row, correct tier, ingest hot-path unaffected) —
   all **met** by fully-automated gates (15 new unit tests + code-review confirmation of the
   additive-only ingest call). No unmet criteria for H1's scope this phase.

Drift score: MEDIUM (2 signals: 10+ files touched across models/services/config/tests; feature-folder
structural work — task folder `handoff_23-07-26/` already created, report augmented). Recommend
UPDATE PROCESS -- significant changes detected.
