---
phase: phase-05-company-resolution
date: 2026-07-22
status: COMPLETE_WITH_GAPS
feature: evallayer
plan: process/features/evallayer/active/evallayer_22-07-26/phase-05-company-resolution_PLAN_22-07-26.md
---

# Phase 05 — Company Resolution → Outreach Feed — EXECUTE Report

**TL;DR:** Shipped agent→company resolution end-to-end per the validate-contract (Gate: PASS).
The agent-origin marker is written ATOMICALLY in the same INSERT as the IdentifiedVisitor row
(GUARD #1); all 7 human-data query sites exclude agent-derived rows via one shared predicate
(GUARD #2 / AC2); no agent-derived record can be emailed (AC10 real-row re-run green). All
Fully-Automated gates green — full regression 778 passed / 2 skipped, 0 regressions vs the 752/2
baseline. Two within-blast-radius deviations recorded; two Docker known-gaps + two safe-direction
backlog residuals carried forward. Not committed.

## What Was Done

- **Migration** `apps/api/migrations/versions/a1c7e4f92b83_add_company_resolution_fields.py`
  (down_revision `d11b39a6c843`, single head): `visitors.is_agent_derived` (bool NOT NULL
  server_default 'false'), `identified_visitors.source_agent_visit_id` (varchar null), FK
  `agent_visits.resolved_company_id → companies.id` ondelete SET NULL (house convention).
- **Models** `apps/api/models/visitor.py` (+`Visitor.is_agent_derived`,
  +`IdentifiedVisitor.source_agent_visit_id`), `apps/api/models/agent_visit.py` (stale "no FK in
  Phase 1" docstring replaced).
- **GUARD #1** `apps/api/services/identity_resolver.py`: `resolve()` + `_save_identified()` gain an
  optional `source_agent_visit_id: str | None = None` kwarg; the value is threaded via resolver
  instance state (`self._active_source_agent_visit_id`, set at the top of `resolve()`) and set
  directly on the `IdentifiedVisitor(...)` constructor — marker is part of the SAME INSERT+COMMIT
  (no deferred UPDATE, no window). Default None = byte-identical human behavior. (DEV-1 — see plan
  ## Deviations.)
- **Sweep** `apps/api/services/agent_company_resolution.py` (new):
  `run_company_resolution_sweep(db, limit=20)` — eligibility `resolved_company_id IS NULL AND
  ip_address IS NOT NULL`, per-row idempotent synthetic Visitor (`agent:{av.id}`,
  `is_agent_derived=True`, intent 0), `resolve(..., source_agent_visit_id=str(av.id))`,
  `_upsert_company`, set `resolved_company_id`; per-row fail-open try/except. No verification_method
  gate, no allowlist carve-out, no new budget bucket (all reused via `resolve()`).
- **Shared filter** `apps/api/services/agent_visitor_filters.py` (new): `human_only_visitor_filter()
  → Visitor.is_agent_derived.is_(False)`.
- **Scheduler** `apps/api/jobs/scheduler.py`: `run_company_resolution_sweep` wired as the 2nd step
  inside `_agent_verification_sweep_job` (same try block).
- **AC2 exclusion — all 7 sites** via the shared predicate: (1) `list_visitors` query+count and
  (6) country-facet via `_build_visitor_filters` (DEV-2, validate-sanctioned); (2)
  `_compute_visitor_stat_counts`; (3) `run_resolution_for_site`; (4) `segmentation_tasks` (both
  functions); (5) `visitor_aggregator._resolve_companies`; (6) `get_visitor_detail` (explicit);
  (7) `resolution_tasks._process_site` (D7, Celery-beat confirmed live).
- **Tests**: `tests/unit/test_agent_company_resolution.py` (new, 25 tests) + AC10 real-row re-run
  added to `tests/unit/test_agent_origin_exclusion.py`.
- **High-risk evidence pack**: `harness/{risk-gate,context-snippets,verification,review-decision,adversarial-validation}-phase5.json`.
- **Phase 7 D1-D6 contract — FULFILLED.** `IdentifiedVisitor.source_agent_visit_id` now EXISTS with
  the exact literal name Phase 7's guard expects; Phase 7's `getattr(identity, "source_agent_visit_id",
  None)` tripwire wiring is now live (proving a real value, not a no-op default). No agent-resolved row
  is ever assigned a `PERSON_LEVEL_PROVIDERS` value (Option B routes exclusively through the existing
  waterfall's non-person-level branches for agent-origin synthetic visitors). No 4th
  send/export bypass path was introduced. `test_ac10_real_sweep_created_row_is_non_emailable` re-runs
  `test_agent_origin_exclusion.py` (18/18 incl. the C5 literal-field-name tripwire) against a REAL
  Phase-5-created row — the binding D5/D6 obligation is discharged.

## What Was Skipped or Deferred

- Migration apply/rollback against a live Postgres — Docker known-gap (no disposable Postgres).
- Full sweep integration round-trip against a live Postgres — Docker known-gap.
- Identity-merge collision + AgentVisit rollup staleness — pre-existing backlog residuals
  (safe-direction, NEW PLAN REQUIRED), NOT touched this phase (plan E4 forbids it).

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| AC10 exclusion (D5/D6 BINDING) | `pytest tests/unit/test_agent_origin_exclusion.py -m unit -q` | 18 passed |
| Phase-5 new suite | `pytest tests/unit/test_agent_company_resolution.py -m unit -q` | 25 passed |
| Full regression | `pytest tests/unit -q` | **778 passed, 2 skipped** (0 regressions vs 752/2) |
| AC14 mock mode | `MOCK_EXTERNAL_APIS=true pytest tests/unit/test_agent_company_resolution.py -m unit -q` | 25 passed |
| Migration chain (offline) | `alembic heads` / `alembic history` | single head `a1c7e4f92b83`, correct chain |
| Migration apply/rollback (live PG) | `alembic upgrade head` / `downgrade -1` | SKIP — Docker known-gap |
| Full sweep integration (live PG) | integration sweep | SKIP — Docker known-gap |

## Plan Deviations

- **DEV-1** — GUARD #1 threaded via resolver instance state instead of kwarg-through-every-method.
  Keeps all changes inside `identity_resolver.py` (declared blast radius) AND covers the
  hunter/apollo/pdl mixins that kwarg-threading would have forced editing. Marker still atomic
  (asserted). Within-blast-radius.
- **DEV-2** — AC2 sites D1 + D6-facet implemented via the shared `_build_visitor_filters()` helper
  (both consume it) rather than at separate assembly points. Explicitly validate-contract-sanctioned.
  Within-blast-radius.

Full rationale: plan `## Deviations`. Both are within-blast-radius; no hard-stop class touched.

## Test Infra Gaps Found

- No disposable Postgres in this sandbox → migration apply/rollback + integration sweep unproven
  (same environment gap as Phases 1-4). Close-the-gap commands recorded in the validate-contract's
  Known gaps section.
- Statement-compilation tests require all ORM models registered; added `import apps.api.main` at the
  top of the two touched test files (mirrors `tests/conftest.py`'s model-import block) to configure
  mappers for real IdentifiedVisitor construction + SQL compilation.

## Closeout Packet

- **Selected plan:** `process/features/evallayer/active/evallayer_22-07-26/phase-05-company-resolution_PLAN_22-07-26.md`
- **Finished:** migration + 3 model attrs + GUARD #1 atomic marker + sweep service + scheduler wiring
  + all 7 AC2 sites + 26 new/extended tests + high-risk evidence pack.
- **Verified:** all Fully-Automated gates green (AC9, D2, AC2×7, OQ4, AC14, AC10 real-row, full
  regression 0-diff). Migration chain valid offline.
- **Unverified:** live-Postgres migration apply/rollback + integration sweep (Docker known-gaps).
- **Remaining:** independent EVL (vc-tester re-run of the gate commands), then commit
  (vc-git-manager), then UPDATE PROCESS (archive + umbrella `## Current Execution State`).
- **Classification:** Keep in active/testing — code-complete + self-verified, pending independent EVL
  confirmation run.
- **Follow-up stubs created:** none new (2 pre-existing backlog notes carried forward).
- **CONTEXT_PARTIAL:** none.

## Forward Preview

- **Test Infra Found:** compiled-SQL assertions are a robust, DB-free way to prove per-site query
  predicates; require `import apps.api.main` to register mappers. Reusable for future AC2-style
  exclusion phases.
- **Blast Radius Changes:** none beyond the declared set; the 3 provider mixin files
  (`identity_providers/hunter.py|apollo.py|pdl.py`) were deliberately NOT edited (DEV-1 avoids them).
- **Commands to Stay Green:** `pytest tests/unit -q` (expect 778/2); `pytest
  tests/unit/test_agent_origin_exclusion.py -m unit -q` (18); `pytest
  tests/unit/test_agent_company_resolution.py -m unit -q` (25).
- **Dependency Changes:** none. New nullable/defaulted columns are additive and backward-compatible;
  `resolve()`/`_save_identified()` gain one optional kwarg (default None).
