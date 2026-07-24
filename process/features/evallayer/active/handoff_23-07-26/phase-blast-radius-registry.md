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

Blast radius (PVL-confirmed 24-07-26, not yet executed):

- `apps/api/services/agent_intent_signals.py` (new — locked name, confirmed at PVL)
- `apps/api/services/hot_alert.py` (add `maybe_send_intent_alert` sibling function; existing
  `maybe_send_hot_alert` untouched — confirmed via full re-read)
- `apps/api/services/agent_aggregator.py` (new sibling DB-fetch fn
  `fetch_recent_ai_researched_companies` + extended `aggregate_agent_analytics` echo param —
  corrected at PVL to preserve the function's pure/no-DB contract, mirrors H2's identical
  Section-D correction)
- `apps/api/schemas/agents.py` (add `RecentAiResearchEntry`, extend `AgentAnalyticsResponse`)
- `apps/api/config.py` (1 new setting: `intent_signal_sweep_interval_minutes`)
- `apps/api/jobs/scheduler.py` — **shared with Phase 2 (DONE); Phase 3 registers additively AFTER
  H2's `handoff_correlation_sweep` job — re-confirmed live at PVL: still exact lines 233-236, no
  drift since H2's EVL. Reassign classification unchanged.**
- `apps/web/src/lib/api-types.ts` (extend `AgentAnalytics`, add `RecentAiResearchEntry`)
- `apps/web/src/app/dashboard/agents/page.tsx` (new card/section: "Appeared after AI research")
- `tests/unit/test_intent_alerts.py` (new)
- No new migration, no new table, no schema change — on-read design only (confirmed at PVL).

status: DONE — executed 24-07-26; all 9 files modified within blast radius; unit gates green (924 passed incl. 24 new + 1 updated aggregator shape test), FE build exit 0; Docker-gated live sweep remains a known-gap (integration test written + collect-clean). Two within-blast-radius deviations recorded in the phase report (vendor+multiplier params on `maybe_send_intent_alert`; separate `intent_alert:spike:` dedup key).

PVL confirmation (24-07-26): blast radius above re-verified against live source at VALIDATE time
(all listed files/lines confirmed to exist and match plan text; `scheduler.py` insertion point
re-confirmed at exact lines 233-236, zero drift since H2's EVL). 2 CONCERNs found and fixed in
plan text this pass — HTML-escaping gap in alert copy (E-B1), pure-function contract violation in
company-correlation design (E-D1, corrected to a sibling DB-fetch function + named the
`company_graph` join as the primary candidate) — plus 1 Docker-gated Hybrid known-gap (live
scheduler sweep -> email delivery). Confirmed disjoint from Phase 1 (H1, DONE) and Phase 4 (H4,
not started); `scheduler.py` sharing with Phase 2 (H2, DONE) unchanged from umbrella's `reassign`
classification — H2 registered first, H3 appends after. Gate: CONDITIONAL (2 CONCERNs fixed in
plan text; 1 Docker-gated Hybrid residual — see
`handoff-program-docker-verification-gaps_NOTE_23-07-26.md`).

EVL confirmation (24-07-26, UPDATE PROCESS): independent re-run of gate commands GREEN on all
H3-owned gates (24/24 unit tests, FE build exit 0). `git diff --stat` on the 9-file blast radius
confirmed zero drift from the plan. One foreign, out-of-blast-radius failure found during the
full-suite re-run (`test_pixel.py::test_source_under_20kb`, caused by the concurrent
`first-party-capture_24-07-26` session's `apps/pixel/src/tracker.js` change) — not an H3 defect,
no action taken. Still disjoint from H1 (DONE) and H2 (DONE); `scheduler.py` sharing with H2
unchanged — H2's job registered first, H3 appended after, confirmed at both PVL and EVL. No
overlap with H4 (not started).

---

## Phase 4 (H4)

Plan: `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_PLAN_23-07-26.md`

Blast radius (PVL-confirmed 24-07-26, not yet executed):

- `apps/web/src/app/pricing-overview/[t]/route.ts` (new — tokenized probe page)
- `apps/web/src/app/pricing-overview/route.ts` (new — bare-path token mint + redirect)
- `apps/web/src/middleware.ts` (additive, 1 line — `isPublicRoute` exemption; **no other in-flight
  phase in this program or the concurrent `first-party-capture_24-07-26` / `pii-at-rest_22-07-26`
  sessions claims this file** — no shared-file coordination needed)
- `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_FEASIBILITY_{date}.md` (new VERDICT artifact, dispatch phase only)
- no shared-file overlap identified with Phase 1/2/3 — H4 is `apps/web`-only (PREP) +
  program-task-folder-only (VERDICT); H1/H2/H3 are `apps/api`-only plus a few shared
  `apps/web` dashboard files (`dashboard/agents/page.tsx`, `dashboard/visitors/**`) that H4 never
  touches

status: DONE — PREP design LOCKED and validated 24-07-26 (Gate: CONDITIONAL, 1 security
CONCERN found and fixed in plan text — reflected-XSS on the `[t]` token, mitigated via strict-format
validation + `notFound()`; 2 named accepted known-gaps, no high-risk-class gap). EXECUTE (Step A)
complete 24-07-26, all PREP gates green. Step B (dispatch) executed by the founder 24-07-26 with
explicit double opt-in — VERDICT = **INCONCLUSIVE** (fetch never reached the page; site's WAF
returns 403 domain-wide to bot user-agents; see
`phase-04-watermark-feasibility_FEASIBILITY_24-07-26.md`). Per AC-H4-2, phase COMPLETE — no
watermark-write code authorized or written.

PVL confirmation (24-07-26): blast radius above re-verified against live source at VALIDATE time —
confirmed `apps/web/src/app/pricing-overview/` does not yet exist (no collision), confirmed
`apps/web/src/middleware.ts` `isPublicRoute` array insertion point via direct read, confirmed
`apps/web/src/app/llms.txt/route.ts` as the shape precedent. Confirmed disjoint from Phase 1 (H1,
DONE), Phase 2 (H2, DONE), and Phase 3 (H3, DONE) — no file overlap.
