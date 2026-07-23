---
name: plan:handoff-program-docker-verification-gaps-note
description: "Backlog: consolidated Docker/live-environment verification gaps accumulated across the Handoff Detection program (H1-H4) — every close command needed to move each phase from CODE DONE to VERIFIED"
date: 23-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: program-closeout
---

# Handoff Detection Program — Consolidated Docker/Live-Verification Gap Backlog

**Why this note exists:** Same rationale as the predecessor EvalLayer program's
`program-docker-verification-gaps_NOTE_23-07-26.md` — any developed behavior whose only proving
gate is a Docker-gated integration test that has never actually run is a named residual (Hybrid
tier, unmet precondition), not a design defect, per the vacuous-green ban. This note tracks that
residual class across the Handoff Detection program (H1-H4), appended to as each phase's PVL runs.

**Not blocking:** these gaps do not block a phase's validate-contract from reaching `Gate: PASS`
(the umbrella charter explicitly allows Docker known-gaps at PVL). They block that phase's own
🔨 CODE DONE → ✅ VERIFIED promotion until closed.

## Close-all sequence (run once against a live Postgres, when infra is available)

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis

cd apps/api && .venv/bin/python -m alembic upgrade head
.venv/bin/python -m alembic downgrade -1
.venv/bin/python -m alembic upgrade head

# H1 — new agent_fetch_events table, live round-trip (structural check already passed offline
# via `python -m alembic heads`, confirmed single head b3f9a1d2c7e5, at VALIDATE 23-07-26)

# H1 — retention-purge extension for agent_fetch_events (mirrors existing purge test pattern)
.venv/bin/python -m pytest tests/integration/test_retention_purge.py -k agent_fetch_events -m integration -q

# H2 — new agent_handoff_links table, live round-trip (structural check already passed offline
# via `alembic heads`, confirmed single head a3e9f1c7d2b5, at VALIDATE 23-07-26)

# H2 — correlation sweep against real Postgres with real agent_fetch_events + events rows
.venv/bin/python -m pytest tests/integration -k handoff_correlation -m integration -q
```

## Per-phase gap inventory

| Phase | Gap | Proves | Close command |
|---|---|---|---|
| H1 | Alembic migration cycle (upgrade/downgrade against live Postgres) never run | Migration correctness (additive-only, new table) | `alembic upgrade head && downgrade -1 && upgrade head` |
| H1 | `test_purges_old_agent_fetch_events` (E7, mirrors `test_retention_purge.py`) never run | D2 retention-purge extension actually deletes old rows / keeps recent ones | `pytest tests/integration/test_retention_purge.py -k agent_fetch_events -m integration -q` |
| H2 | Alembic migration cycle (upgrade/downgrade against live Postgres) never run for `agent_handoff_links` | Migration correctness (additive-only, new table); `down_revision` corrected at PVL to `a3e9f1c7d2b5` | `alembic upgrade head && downgrade -1 && upgrade head` |
| H2 | Correlation sweep integration round-trip (E7) never run against a real DB | AC-H2-1 (live-integration confidence — the Fully-Automated unit suite proves logic correctness on synthetic fixtures, not real-Postgres query-planner behavior) | `pytest tests/integration/test_handoff_correlation_integration.py -m integration -q` (file written at EXECUTE, collect-clean) |

## SPEC criteria that ARE fully met (Fully-Automated gate green, no Docker dependency)

AC-H1-1 (per-hit capture), AC-H1-2 (tier classification, incl. completeness tripwire), AC-H1-3
(ingest hot-path fail-open isolation), and the retention config default (E5) are all green today
via `tests/unit/test_agent_fetch_events.py` — Docker-free.

AC-H2-1 (link creation + confidence formula + no-low-writes policy), AC-H2-2 (window/vendor
exclusion), AC-H2-3 (emailability separation — program's highest-priority gate), AC-H2-5
(cross-site exclusion), and AC-H2-4's API half are all green today via
`tests/unit/test_handoff_correlation.py`, `tests/unit/test_handoff_emailability_separation.py`,
and `tests/unit/test_agent_aggregator.py` — all Docker-free. Only the live-integration confidence
half of AC-H2-1 (real Postgres round-trip) and the migration cycle remain gated here.

## Next action

Not scheduled — requires a disposable Postgres instance not available in the current sandbox
(`docker ps` produced no output during both the H1 and H2 VALIDATE passes). When infra becomes
available, run the close commands above and mark H1 and H2 ✅ VERIFIED in the umbrella plan's
Program Status Table. H2's AC-H2-3 emailability regression is confirmed Fully-Automated /
Docker-free as predicted — it does NOT need this note; only H2's live-sweep integration and
migration cycle do. Append H3/H4 rows here as their own PVL passes surface further Docker-gated
gaps.
