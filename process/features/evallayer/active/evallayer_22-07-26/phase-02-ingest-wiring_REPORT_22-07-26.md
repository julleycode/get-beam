---
phase: phase-02-ingest-wiring
date: 2026-07-22
status: COMPLETE_WITH_GAPS
feature: evallayer
plan: process/features/evallayer/active/evallayer_22-07-26/phase-02-ingest-wiring_PLAN_22-07-26.md
---

## KNOWN GAPS (read this first)

1. **Docker integration tests unrun** (`TestAgentDetection`, 5 cases — AC1/AC2/AC3/AC4 + flag-OFF) —
   collect cleanly, cannot run in this sandbox (no responsive Docker daemon). Close command:
   ```bash
   MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest tests/integration/test_events_ingest.py -k "agent or datacenter" -m integration -q
   ```
2. **AC5 latency benchmark** — no benchmark harness exists yet. Backlog stub already written:
   `process/features/evallayer/backlog/phase-02-latency-benchmark_NOTE_22-07-26.md`.
3. Carried forward from Phase 1: `agent_visits` migration never applied to a real Postgres instance
   (Docker-gated, same environment limitation).

Neither gap is a design defect — both are environment/tooling gaps in an otherwise fully specified
and testable design (see Validate Contract's vacuous-green reasoning in the phase plan).

# Phase 02 — Ingest Wiring — EXECUTE Report

## What Was Done

Wired Phase 1's agent classifier into the live `/events/ingest` hot path behind a
default-OFF `agent_detection_enabled` flag. All 5 blast-radius files landed exactly per the
Gate-CONDITIONAL (accepted) validate-contract, in checklist order A → B → C → D.

- **A (config)** — `apps/api/config.py`: added `agent_detection_enabled: bool = False` beside
  `block_datacenter_traffic`/`block_proxy_vpn_traffic`, same multi-line-comment convention.
  Comment documents that it gates classify+persist and stays OFF until the `agent_visits`
  migration is confirmed applied in prod.
- **B (new module)** — `apps/api/services/agent_visit_persistence.py`:
  - `_append_capped_path(paths, new_path, cap=50)` — pure: no-op on None/empty; moves a
    re-seen path to the end (most-recent-last); truncates to last `cap`.
  - `persist_agent_visit(...)` — atomic `pg_insert(...).on_conflict_do_update(...)` on
    `(site_id, vendor, product_or_ua_token)`, SQL-level `visit_count + 1`, unconditional
    `last_seen_at`. Fully fail-open: whole body wrapped in `try/except Exception` →
    `logger.warning("agent_visit_persist_failed", site_id=, vendor=, error=)` (NO UA, NO IP in
    the log body), `await db.rollback()`, `return None`. Never raises.
- **C (events.py restructure)** — single consolidated `from apps.api.config import settings as
  _settings` local import at the top of `ingest_events` (removed the later duplicate — E2 done);
  `classification = classify_agent(request_ua) if _settings.agent_detection_enabled else None`;
  bot drop changed to `if classification is None and is_bot(request_ua)`; agent branch inserted
  immediately after `ip_address = _extract_ip(request)` as a **hard return** (persist + 204)
  BEFORE the datacenter/proxy drops and all human-path code. Human path (`classification is
  None`) is byte-identical to before.
- **D (tests)** — new `tests/unit/test_agent_visit_persistence.py` (9 cases for the cap
  function); new `TestAgentDetection` class in `tests/integration/test_events_ingest.py`
  (AC1, AC2, AC3, AC4 with inline `is_datacenter_ip` monkeypatch, flag-OFF).

## What Was Skipped or Deferred

- **AC5 (ingest latency benchmark)** — no benchmark harness exists; backlog stub already
  written at `process/features/evallayer/backlog/phase-02-latency-benchmark_NOTE_22-07-26.md`.
  Pre-accepted known-gap; keeps the phase gate CONDITIONAL per the vacuous-green ban.

## Test Gate Outcomes

**EXECUTE self-report (in-progress subset, at implementation time):**

| Gate | Command | Result |
|---|---|---|
| `_append_capped_path` unit | `.venv/bin/python -m pytest tests/unit/test_agent_visit_persistence.py -m unit -q` | GREEN — 9 passed |
| Unit regression (subset run at EXECUTE time) | `.venv/bin/python -m pytest tests/unit -m unit -q` | GREEN — 171 passed, 2 skipped, 0 failures (incl. 9 new) |
| AC1/AC2/AC3/AC4 + flag-OFF integration | `MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest tests/integration/test_events_ingest.py -k "agent or datacenter_flagged" -m integration -q` | KNOWN-GAP — Docker daemon unavailable in sandbox (`docker ps` non-responsive). Tests collect clean (syntax + imports valid, verified via `--collect-only`). |

**EVL confirmation run (independent vc-tester, authoritative full-baseline numbers):**

| Gate | Command | Result |
|---|---|---|
| `_append_capped_path` unit (9 cases) | `.venv/bin/python -m pytest tests/unit/test_agent_visit_persistence.py -m unit -q` | GREEN — 9/9 passed |
| Full unit baseline | `.venv/bin/python -m pytest tests/unit -m unit -q` | GREEN — **725 passed, 2 skipped** (Phase 1 baseline was 716 → +9, 0 regressions) |
| Classifier regression (Phase 1 surface, read-only this phase) | `.venv/bin/python -m pytest tests/unit/test_agent_classifier.py -m unit -q` | GREEN — 24/24 passed |
| AC1/AC2/AC3/AC4 + flag-OFF integration (`TestAgentDetection`, 5 cases) | `MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest tests/integration/test_events_ingest.py -k "agent or datacenter" -m integration -q` | KNOWN-GAP — no Docker in sandbox; collect-clean, unrun. See Known Gaps section above for close command. |

**Static safety review (independent vc-tester, in lieu of live Docker integration run) — confirmed
all 3 declared safety properties by direct code read:**

1. **Agent branch hard-returns before the `Event` insert (AC2)** — confirmed: `events.py`'s
   `if classification is not None:` block calls `persist_agent_visit(...)` then
   `return Response(status_code=204)` unconditionally, structurally before the datacenter/proxy-VPN
   drops, Client Hints, GeoIP, and the `Event` insert/`_process_signal_events`/aggregation trigger.
   No code path exists from the agent branch back into the human path.
2. **Flag-off is byte-identical to pre-Phase-2 behavior (AC3/regression-safe)** — confirmed:
   with `agent_detection_enabled=False` (the default), `classification` is always `None`, so the
   restructured bot-drop condition `if classification is None and is_bot(request_ua)` reduces to the
   original `if is_bot(request_ua)`, and the new agent branch is never entered. No line in the
   human/generic-bot path changed behavior when the flag is off.
3. **`persist_agent_visit` is fail-open** — confirmed: the entire function body is wrapped in
   `try/except Exception as exc`, which logs `agent_visit_persist_failed` with `site_id`/`vendor`/
   `error` keys only (no raw UA, no IP — matches the PII/GDPR no-PII-in-logs guardrail), calls
   `await db.rollback()`, and returns `None` — it never raises, so a persistence failure can never
   surface as an ingest-endpoint error.

Module import smoke: `import apps.api.routers.events; import apps.api.services.agent_visit_persistence` → OK.

## Plan Deviations

None against the validate-contract. `page_paths` cap approach: chose the plan's documented
SELECT-then-Python-compute design (via `_append_capped_path`) applied through the atomic
`on_conflict_do_update` — counters/timestamps race-free (SQL `+1`), page_paths carries the narrow,
accepted, fail-open-safe first-ever-visit cosmetic race documented in the module docstring. This is
the contract's accepted residual, not a deviation. All changes within the declared blast radius.

## Test Infra Gaps Found

- No responsive Docker daemon in this build environment → all integration-tier gates un-runnable
  here (environment gap, not a coverage gap — tests are Fully-Automated by design).
- AC4 required a net-new inline `monkeypatch.setattr("apps.api.services.company_resolver.is_datacenter_ip", ...)`
  fixture (none pre-existed in the integration file) — added.

## Closeout Packet

1. Selected plan: `process/features/evallayer/active/evallayer_22-07-26/phase-02-ingest-wiring_PLAN_22-07-26.md`
2. Closeout classification: **Keep in active/testing** — code-complete (EXECUTE + EVL both done),
   but Docker integration tests and AC5 latency remain unrun Known-Gaps; not yet ✅ VERIFIED.
3. What was finished: all A–D checklist items shipped exactly per the CONDITIONAL (accepted)
   validate-contract; 5 blast-radius files landed with zero deviations.
4. Verified: unit tier fully (725/725 unit baseline incl. 9 new + 2 skipped, 0 regressions; 24/24
   classifier). Static safety review confirms all 3 declared safety properties by direct code read.
   Unverified: integration tier (5 `TestAgentDetection` cases — Docker-gated, unrun); AC5 latency
   (no harness exists).
4b. Validate-contract: present, inline in plan (`generated-by: inner-pvl: phase-2`), Gate:
   CONDITIONAL — accepted this session under the active AUTOPILOT decision policy.
5. Cleanup done: phase report written and augmented with EVL results + known-gaps; blast-radius
   registry Phase 2 entry ready to finalize to `status: DONE`. Still needed: umbrella Program Status
   Table + Current Execution State update; Phase Loop Progress ticks 6-7; validator run; commit
   (deferred to vc-git-manager per this UPDATE PROCESS session's instruction — not committed here).
6. Single best next valid state: `ENTER UPDATE PROCESS MODE complete for Phase 2 — continue with
   process/features/evallayer/active/evallayer_22-07-26/phase-03-read-api-dashboard_PLAN_22-07-26.md`
   (Phase 3, loop step RESEARCH).
7. Commit-checkpoint recommendation: **Execution commit recommended before UPDATE PROCESS commit** —
   the 5 implementation/test files (events.py, config.py, agent_visit_persistence.py, the 2 test
   files) are well-tested and ready for a logical execution commit; this UPDATE PROCESS session's
   own changes (report, plan ticks, registry, umbrella) belong in a separate process commit after.
   Both deferred to vc-git-manager per this session's explicit instruction not to commit here.
8. Regression status: Phase 1 surface (`agent_classifier.py`, `agent_visit.py`) checked via
   `test_agent_classifier.py` — 24/24 PASS, no regression; Phase 1 and Phase 2 blast radii confirmed
   disjoint (registry cross-check).
9. Fail-open guarantee: confirmed — persistence errors log keys-only, roll back, return None, never raise.
   Flag-OFF guarantee: confirmed — with `agent_detection_enabled=False`, `classification` is None and
   the ingest path is byte-identical to pre-Phase-2 (recognized agent UAs fall through to is_bot()).

**Drift score:** MEDIUM (2 signals: feature-folder structural change — backlog NOTE written +
task-folder report finalized; validate-contract CONDITIONAL-accepted deviation from a clean PASS).
Recommend UPDATE PROCESS -- significant changes detected.

## Forward Preview

- **Test Infra Found:** integration gates need docker-compose PG+Redis (`infra/docker-compose.yml`,
  `TESTING.md`); no latency-benchmark harness exists (backlog stub named).
- **Blast Radius Changes:** none beyond the 5 declared files; Phase 3 (`agents.py`, dashboard) still disjoint.
- **Commands to Stay Green:** `.venv/bin/python -m pytest tests/unit -m unit -q`; with Docker:
  `MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest tests/integration/test_events_ingest.py -k "agent or datacenter_flagged" -m integration -q`.
- **Dependency Changes:** none — no new deps; consumes Phase-1 `agent_classifier`/`agent_visit` read-only.
