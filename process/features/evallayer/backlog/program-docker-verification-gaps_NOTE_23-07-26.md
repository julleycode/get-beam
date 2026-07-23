---
name: plan:evallayer-program-docker-verification-gaps-note
description: "Backlog: consolidated Docker/live-environment verification gaps accumulated across EvalLayer Phases 1-6 — every close command needed to move each phase from CODE DONE to VERIFIED"
date: 23-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: program-closeout
---

# EvalLayer Program — Consolidated Docker/Live-Verification Gap Backlog

**Why this note exists:** Per the vacuous-green ban, any SPEC acceptance criterion whose only
proving gate is a Docker-gated integration test that has never actually run is scored **unmet**
at program closeout, even though the code is written and unit/regression/static-review coverage
is green. This note is the single backlog artifact tracking every such residual across the whole
8-phase program, with the exact close command for each. None of these are design defects — every
one is "no responsive Docker daemon in this sandbox," a documented environment gap, not a
behavioral gap.

**Not blocking:** these Known-Gaps do not block the program from being code-complete. They block
each phase's own 🔨 CODE DONE → ✅ VERIFIED promotion until closed.

## Close-all sequence (run once against a live Postgres + Redis)

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis

# Migrations (Phase 1, Phase 5, AI-referral — 3 pending heads to apply in order)
cd apps/api && .venv/bin/python -m alembic upgrade head
.venv/bin/python -m alembic downgrade -1
.venv/bin/python -m alembic upgrade head

# Phase 1 — agent_visits table structural check already passed offline; this is the live round-trip
# Phase 2 — ingest integration (AC1-AC4 + flag-OFF)
.venv/bin/python -m pytest tests/integration/test_events_ingest.py -k "agent or datacenter" -m integration -q

# Phase 3 — /agents API integration (10 cases)
.venv/bin/python -m pytest tests/integration/test_agents_api.py -q

# Phase 3 — Playwright e2e (needs dev server)
cd ../.. && npm run --prefix apps/web dev &
npx playwright test apps/web/e2e/agents.spec.ts --config=apps/web/playwright.config.ts

# Phase 4 — IP-range verification sweep integration
cd apps/api && .venv/bin/python -m pytest tests/integration/test_agent_verification_sweep.py -m integration -q

# Phase 5 — company-resolution integration sweep (test file name TBD if not yet authored — see
# phase-05-company-resolution_REPORT_22-07-26.md)
.venv/bin/python -m pytest tests/integration -k agent_company_resolution -m integration -q

# Phase 6 — /analytics endpoint integration
.venv/bin/python -m pytest tests/integration/test_agents_api.py -k analytics -m integration -q

# Phase 6 — dashboard card e2e (needs dev server, already started above)
npx playwright test apps/web/e2e/agents.spec.ts --config=apps/web/playwright.config.ts
```

## Per-phase gap inventory (from phase reports / registry)

| Phase | Gap | AC affected | Close command (see above for full sequence) |
|---|---|---|---|
| 1 | `agent_visits` migration never applied to a real Postgres | AC13 (structural, low risk) | `alembic upgrade head && downgrade -1 && upgrade head` |
| 2 | 5 `TestAgentDetection` integration cases unrun | AC1, AC2, AC3, AC4 | `pytest tests/integration/test_events_ingest.py -k "agent or datacenter" -m integration -q` |
| 2 | AC5 ingest-latency benchmark has no harness | AC5 | see `phase-02-latency-benchmark_NOTE_22-07-26.md` (separate backlog item, NEW PLAN REQUIRED) |
| 3 | 10 `test_agents_api.py` integration cases unrun | AC6 | `pytest tests/integration/test_agents_api.py -q` |
| 3 | Playwright e2e unrun (needs dev server) | AC6, AC7 | `npx playwright test apps/web/e2e/agents.spec.ts ...` |
| 4 | `test_agent_verification_sweep.py` integration unrun | AC8 | `pytest tests/integration/test_agent_verification_sweep.py -m integration -q` |
| 5 | Migration apply/rollback against live Postgres unrun | AC9 (schema risk) | `alembic upgrade head && downgrade -1` |
| 5 | Full sweep integration round-trip unrun | AC9, AC14 | `pytest tests/integration -k agent_company_resolution -m integration -q` |
| 6 | `/analytics` endpoint integration unrun | AC11, AC2 | `pytest tests/integration/test_agents_api.py -k analytics -m integration -q` |
| 6 | Dashboard card Playwright e2e unrun | AC11 | `npx playwright test apps/web/e2e/agents.spec.ts ...` |
| AI-referral (bonus, outside 8-phase scope) | `first_touch_referrer`/`ai_source` migration (`b3f9a1d2c7e5`) unrun against live Postgres; integration suites unrun | N/A (not an EvalLayer SPEC AC) | `alembic upgrade head && downgrade -1 && upgrade head` then relevant integration suite |

## SPEC criteria that ARE fully met (Fully-Automated gate green, no Docker dependency)

AC10 (outreach-exclusion — highest priority, Phase 7, zero Docker gap), AC11's unit-level
correctness (Phase 6 `test_agent_aggregator.py`, 11/11), AC2's isolation assertion (compiled-SQL
check, Docker-free), AC3, AC12 (Phase 0), AC13 (classifier unit-level), AC14's mock-mode coverage
(Fully-Automated, Docker-free) are all green today without needing this backlog closed.

## Next action

Not scheduled — requires a disposable Postgres+Redis instance not available in the current
sandbox. When infra becomes available, run the close-all sequence above in one sitting and mark
each phase ✅ VERIFIED in the umbrella plan's Program Status Table.
