---
name: plan:handoff-blast-radius-registry
description: "Handoff Detection program — single blast-radius coordination registry across all 4 phases"
date: 23-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: registry
---

# Handoff Detection — Phase Blast-Radius Registry

One registry for the whole program. Each phase agent appends its own `## Phase N` section
before writing its full plan (or, if reconciled later, at PVL time). Never overwrite — append
only. See `process/development-protocols/vc-system-behavior/11-phase-programs.md` §Blast-radius
registry for the write protocol and valid `status:` vocabulary.

The umbrella plan's `## Pre-PVL Conflict Resolution` section already identifies one shared file
(`apps/api/jobs/scheduler.py`, shared by Phase 2 and Phase 3, classified `reassign` — Phase 2
registers first) — this registry records each phase's confirmed blast radius as they execute so
that classification can be re-verified against real diffs, not just planned intent.

---

## Phase 1 (H1)

Plan: `process/features/evallayer/active/handoff_23-07-26/phase-01-fetch-events-tiering_PLAN_23-07-26.md`

Blast radius (planned, not yet executed):

- `apps/api/models/agent_fetch_event.py` (new)
- `apps/api/migrations/versions/<hash>_add_agent_fetch_events_table.py` (new)
- `apps/api/services/agent_classifier.py` (additive tier-lookup helper)
- `apps/api/services/agent_visit_persistence.py` (additive write function)
- `apps/api/routers/events.py` (one additive, fail-open call)
- `tests/unit/test_agent_fetch_events.py` (new)
- `tests/integration/test_retention_purge.py` (extended — VALIDATE-added, PVL 23-07-26)

status: DONE — EXECUTE complete 23-07-26; migration hash resolved to `c4e8f1a9d2b7`; also touched
(within blast radius) `config.py`, `retention.py`, `scheduler.py`, `main.py` per checklist Steps
A2/D1/D2. 6 fully-automated gates green; 2 Docker-gated Hybrid gaps pending live Postgres.

PVL confirmation (23-07-26): blast radius above re-verified against live source at VALIDATE time
(all listed files/lines confirmed to exist and match plan text, 1 line-reference fix applied to
`main.py` import + `events.py` call-site import style). Confirmed disjoint from Phase 2 (H2),
Phase 3 (H3), and Phase 4 (H4) — no file overlap. Gate: CONDITIONAL (Docker-gated Hybrid residuals
only — see `handoff-program-docker-verification-gaps_NOTE_23-07-26.md`).

EVL confirmation (23-07-26, UPDATE PROCESS): independent re-run of gate commands GREEN (15/15 +
24/24 regression). Migration `c4e8f1a9d2b7` (this phase) has two foreign migrations
(`f8a2c1d9b3e7`, `a3e9f1c7d2b5` — visitors-identity "owned-data-layer" program) chained onto it —
confirmed linear single-head, no conflict. Still disjoint from H2/H3/H4.

---

## Phase 2 (H2)

Plan: `process/features/evallayer/active/handoff_23-07-26/phase-02-handoff-correlation_PLAN_23-07-26.md`

Blast radius (PVL-confirmed 23-07-26, not yet executed):

- `apps/api/models/agent_handoff_link.py` (new)
- `apps/api/migrations/versions/<hash>_add_agent_handoff_links_table.py` (new; `down_revision`
  corrected at PVL from stale `c4e8f1a9d2b7` to VALIDATE-confirmed live head `a3e9f1c7d2b5` —
  re-verify with `alembic heads` again immediately before EXECUTE writes the file)
- `apps/api/services/agent_handoff_correlation.py` (new — locked name, confirmed)
- `apps/api/config.py` (1 new setting: `handoff_correlation_sweep_interval_minutes`)
- `apps/api/jobs/scheduler.py` — **shared with Phase 3; Phase 2 registers first (reassign
  classification, see umbrella Pre-PVL Conflict Resolution) — unchanged at PVL, still `reassign`**
- `apps/api/schemas/visitors.py` (5 new nullable fields on `VisitorDetailOut`)
- `apps/api/routers/visitors.py` (additive data-merge in `get_visitor_detail`, confirmed
  ~line 541-636 matches live source, no drift)
- `apps/api/schemas/agents.py` (1 new field on `AgentAnalyticsResponse`)
- `apps/api/services/agent_aggregator.py` (new sibling DB-fetch fn + extended pure-aggregation
  signature — locked at PVL, see plan LOCKED Decision 11)
- `apps/web/src/lib/api-types.ts` (extend `VisitorDetail` + `AgentAnalytics` interfaces — exact
  names confirmed at PVL)
- `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` (badge, confirmed ~line 448/797)
- `apps/web/src/app/dashboard/visitors/page.tsx` (list-row pill, confirmed ~line 650)
- `apps/web/src/app/dashboard/agents/page.tsx` (analytics card, confirmed ~line 70-139 region)
- `tests/unit/test_handoff_correlation.py`, `tests/unit/test_handoff_emailability_separation.py` (new)
- `tests/unit/test_agent_aggregator.py` (extended — corrects SPEC's imprecise citation of a
  non-existent `tests/unit/test_agents_api.py`)

status: DONE — EXECUTE complete 24-07-26; migration hash resolved to `e2a4c7f81b93`,
down_revision re-verified live as `a3e9f1c7d2b5` (single head at EXECUTE, unchanged since PVL).
Within-blast-radius additions (documented in phase report ## Plan Deviations): (1) one extra
nullable `handoff_confidence` field on `VisitorOut` (list schema) + a single bulk list-query in
`list_visitors` + TS `Visitor` interface field, to wire the D6 list-row pill (the plan required the
pill but scoped the field only to VisitorDetailOut); (2) added `fetch_site_id` param + site check to
`correlate_fetch_to_clicks` as AC-H2-5 defense-in-depth (makes cross-site exclusion unit-testable
without a DB). 35 new/affected unit gates green; full unit suite 899 passed / 0 failures; FE build
green; 1 Docker-gated Hybrid gap (live sweep + migration cycle) remains as known-gap.

PVL confirmation (23-07-26): blast radius re-verified against live source at VALIDATE time (all
listed files/lines confirmed to exist and match plan text). Migration head corrected
(`a3e9f1c7d2b5`, single head, no fork). Confirmed disjoint from Phase 1 (H1, DONE) and Phase 4
(H4, not started); `scheduler.py` sharing with Phase 3 (H3) unchanged from umbrella's `reassign`
classification — Phase 2 still registers first. Gate: CONDITIONAL (1 Docker-gated Hybrid residual
only — live sweep + migration cycle — see `handoff-program-docker-verification-gaps_NOTE_23-07-26.md`).

EVL confirmation (24-07-26, UPDATE PROCESS): independent re-run of gate commands GREEN (21/21
target + 899/0 full regression + FE build). `agent_handoff_links` registration + indexes confirmed
present. Migration head confirmed single (`e2a4c7f81b93`, unchanged since EXECUTE). AC-H2-3
confirmed via zero-diff structural check + zero-reference tripwire + zero outreach-table joins.
Dashboard badge copy confirmed probabilistic. Still disjoint from H1 (DONE) and H4 (not started);
`scheduler.py` sharing with H3 unchanged — H2's job registered first, H3 must additively append
after re-reading H2's diff (per umbrella Pre-PVL Conflict Resolution).

---

## Phase 3 (H3)

Plan: `process/features/evallayer/active/handoff_23-07-26/phase-03-intent-signals_PLAN_23-07-26.md`

Blast radius (planned, not yet executed):

- new intent-signal service (location TBD by INNOVATE)
- `apps/api/jobs/scheduler.py` — **shared with Phase 2; Phase 3 must additively append after
  re-reading Phase 2's actual diff (reassign classification, see umbrella Pre-PVL Conflict
  Resolution)**
- `apps/api/services/hot_alert.py` (reused, not modified)
- `apps/api/routers/` (new or extended endpoint)
- `apps/web/src/app/dashboard/` (widget additions)
- `tests/unit/test_intent_alerts.py` (new)

status: (no field — not yet executed)

---

## Phase 4 (H4)

Plan: `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_PLAN_23-07-26.md`

Blast radius (planned, not yet executed):

- `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_FEASIBILITY_{date}.md` (new VERDICT artifact)
- a Beam-owned test page (location TBD by INNOVATE)
- no shared-file overlap identified with Phase 1/2/3

status: (no field — not yet executed)
