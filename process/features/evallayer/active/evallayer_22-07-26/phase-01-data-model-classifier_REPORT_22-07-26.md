---
phase: phase-01-data-model-classifier
date: 2026-07-22
status: COMPLETE_WITH_GAPS
feature: evallayer
plan: process/features/evallayer/active/evallayer_22-07-26/phase-01-data-model-classifier_PLAN_22-07-26.md
---

# Phase 01 — Data Model + Classifier — EXECUTE Report

TL;DR: All 5 checklist steps (A–E) implemented exactly per the validate-contract. Two
Fully-Automated gates GREEN (classifier 24/24, registration smoke). Full unit suite GREEN
(716 passed, no regression). The Hybrid live-DB migration up/down/up cycle is a recorded
Known-Gap — Docker unavailable in this environment; verified structurally offline instead.
No deviations from the plan.

## What Was Done

- **A — Classifier** (`apps/api/services/agent_classifier.py`, new): `_VENDOR_TOKENS` dict
  (openai/anthropic/perplexity/bytespider), `VERIFICATION_METHODS` constant, `AgentClassification`
  NamedTuple, `classify_agent()` — case-insensitive substring match, `"ua-only"`, `None` for
  unrecognized/empty/None. Drop-only vendors noted in comment (SPEC Resolved Q6). Does not import
  `bot_filter.py`.
- **B — Model** (`apps/api/models/agent_visit.py`, new): `AgentVisit(Base)` table `agent_visits`;
  inherits id/created_at/updated_at; `page_paths: Mapped[list[str]]` JSONB mirroring visitor.py:29 /
  segment.py:22 (VALIDATE-corrected type); unique constraint (site_id, vendor, product_or_ua_token)
  + composite index (site_id, last_seen_at); resolved_company_id nullable, no FK.
- **C — Migration** (`apps/api/migrations/versions/d11b39a6c843_add_agent_visits_table.py`, new):
  `down_revision = "b8f3c1d92a47"` (re-confirmed as current head at EXECUTE — `alembic heads` shows
  single head, no fork). upgrade() creates table + 2 indexes + unique constraint; downgrade() drops
  in dependency-safe order. Docstring cross-references the phase-01 plan.
- **D — Registration** (`apps/api/main.py`): one `# noqa: F401` import added after the outcome
  import (line 32), mirroring the existing newest entry exactly.
- **E — Tests** (`tests/unit/test_agent_classifier.py`, new): parametrized, class-grouped,
  `@pytest.mark.unit`, pure — recognized vendors, drop-only tokens, AC13 exclusion, empty/None UA.

## What Was Skipped or Deferred

- Live-DB migration apply/rollback cycle — deferred to EVL vc-tester run (Docker unavailable here).
  Not faked. Exact commands recorded in `harness/verification.json`.

## Test Gate Outcomes

| Gate | Tier | Result | Evidence |
|---|---|---|---|
| `pytest tests/unit/test_agent_classifier.py -m unit -q` | Fully-Automated | GREEN | 24 passed in 0.02s |
| Registration smoke (`agent_visits in Base.metadata.tables`) | Fully-Automated | GREEN | "OK: agent_visits registered" |
| Migration up/down/up vs live Postgres | Hybrid | KNOWN-GAP | Docker unavailable (`docker info` timed out); verified single head + script load offline |
| Full unit suite `pytest tests/unit/ -q` | Regression | GREEN | 716 passed, 2 skipped, 1 pre-existing warning |

## Plan Deviations

None. Implemented exactly per the validate-contract, including the VALIDATE-corrected
`Mapped[list[str]]` type and the re-confirmed Alembic head.

## Test Infra Gaps Found

- **KNOWN-GAP (confirmed by independent EVL run, not just EXECUTE's own claim):** the Hybrid
  migration apply/rollback/re-apply cycle (`docker compose -f infra/docker-compose.yml up -d
  postgres` → `alembic upgrade head` → `downgrade -1` → `upgrade head`) could not be run — no
  responsive Docker daemon in this sandbox (`docker info` timed out). Offline structural
  substitute passed: `alembic heads` shows a single head (`d11b39a6c843`, chained after
  `b8f3c1d92a47`), confirming the script loads, imports resolve, and there is no branch/fork.
  **Close-the-gap command** (run once a docker-compose Postgres is available per `TESTING.md`):
  ```bash
  docker compose -f infra/docker-compose.yml up -d postgres
  PYTHONPATH=. .venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head
  PYTHONPATH=. .venv/bin/python -m alembic -c apps/api/alembic.ini downgrade -1
  PYTHONPATH=. .venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head
  ```
  This is a residual Known-Gap only — per the program's vacuous-green ban, it is NOT treated as a
  passing gate. Phase 1 is classified `🔨 CODE DONE` (not `✅ VERIFIED`) in the umbrella Program
  Status Table specifically because of this open gate.

## EVL Confirmation (independent vc-tester re-run)

| Gate | Tier | Result |
|---|---|---|
| `pytest tests/unit/test_agent_classifier.py -m unit -q` | Fully-Automated | GREEN — 24/24 |
| Registration smoke (`agent_visits` in `Base.metadata.tables`) | Fully-Automated | GREEN |
| `pytest tests/unit/ -q` (full regression) | Regression | GREEN — 716 passed, 2 skipped, no regression |
| Migration up/down/up vs live Postgres | Hybrid | KNOWN-GAP (same reason as EXECUTE — no responsive Docker in sandbox) |

EVL independently re-ran the exact validate-contract gate commands (not just trusted
EXECUTE's internal claim) — 3/4 gates confirmed green, 1 Known-Gap carried forward unchanged.
No new deviations found.

## Closeout Packet

- Selected plan: `phase-01-data-model-classifier_PLAN_22-07-26.md`
- Finished: Steps A–E, all Fully-Automated gates + regression green; high-risk evidence pack written
  to `harness/` (risk-gate, verification, context-snippets, review-decision; adversarial-validation
  not required per contract).
- Verified vs unverified: classifier + registration + no-regression VERIFIED; live migration cycle
  UNVERIFIED (Known-Gap, EVL to confirm).
- Remaining: EVL vc-tester independent gate re-run (incl. live migration cycle if Postgres available);
  then UPDATE PROCESS archival + commit (orchestrator handles commit/push).
- Best next state: Keep in active/testing until EVL confirms the Hybrid migration gate.

## Forward Preview

### Test Infra Found
- New `tests/unit/test_agent_classifier.py` (24 cases). Migration cycle needs `docker compose -f
  infra/docker-compose.yml up -d postgres` per TESTING.md.

### Blast Radius Changes
- New: agent_visit.py model, agent_classifier.py service, migration d11b39a6c843,
  test_agent_classifier.py. Edited: main.py (one import line). Disjoint from Phase 0 and Phase 2.

### Commands to Stay Green
- `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_agent_classifier.py -m unit -q`
- `PYTHONPATH=. .venv/bin/python -c "import apps.api.main; from apps.api.models.database import Base; assert 'agent_visits' in Base.metadata.tables"`
- Live migration (EVL): `docker compose -f infra/docker-compose.yml up -d postgres` then
  `alembic -c apps/api/alembic.ini upgrade head` / `downgrade -1` / `upgrade head`

### Dependency Changes
- None. No new packages. Phase 2 (ingest wiring) depends on B (model) + A (classifier); both shipped.
