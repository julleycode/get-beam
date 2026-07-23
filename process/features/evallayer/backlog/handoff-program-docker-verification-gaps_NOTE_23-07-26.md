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
```

## Per-phase gap inventory

| Phase | Gap | Proves | Close command |
|---|---|---|---|
| H1 | Alembic migration cycle (upgrade/downgrade against live Postgres) never run | Migration correctness (additive-only, new table) | `alembic upgrade head && downgrade -1 && upgrade head` |
| H1 | `test_purges_old_agent_fetch_events` (E7, mirrors `test_retention_purge.py`) never run | D2 retention-purge extension actually deletes old rows / keeps recent ones | `pytest tests/integration/test_retention_purge.py -k agent_fetch_events -m integration -q` |

## SPEC criteria that ARE fully met (Fully-Automated gate green, no Docker dependency)

AC-H1-1 (per-hit capture), AC-H1-2 (tier classification, incl. completeness tripwire), AC-H1-3
(ingest hot-path fail-open isolation), and the retention config default (E5) are all green today
via `tests/unit/test_agent_fetch_events.py` — Docker-free.

## Next action

Not scheduled — requires a disposable Postgres instance not available in the current sandbox
(`docker ps` timed out during this VALIDATE pass). When infra becomes available, run the two
close commands above and mark H1 ✅ VERIFIED in the umbrella plan's Program Status Table. Append
H2/H3/H4 rows here as their own PVL passes surface further Docker-gated gaps (H2's AC-H2-3
emailability regression is expected to be Fully-Automated / Docker-free per its own plan — verify
at H2 PVL time and do not assume it needs this note).
