---
name: plan:evallayer-blast-radius-registry
description: "EvalLayer program — single blast-radius coordination registry across all 8 phases"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: registry
---

# EvalLayer — Phase Blast-Radius Registry

One registry for the whole program. Each phase agent appends its own `## Phase N` section
before writing its full plan (or, if reconciled later, at VALIDATE time). Never overwrite —
append only. See `process/development-protocols/vc-system-behavior/11-phase-programs.md`
§Blast-radius registry for the write protocol and valid `status:` vocabulary.

---

## Phase 1

Plan: `process/features/evallayer/active/evallayer_22-07-26/phase-01-data-model-classifier_PLAN_22-07-26.md`

Blast radius (confirmed real, no collisions with any other phase at PVL time — verified
2026-07-22 against phase-00 (frontend-only, shipped) and phase-02 (events.py, bot_filter.py,
config.py) blast radii, which are disjoint from the files below):

- `apps/api/models/agent_visit.py` (new)
- `apps/api/migrations/versions/<hash>_add_agent_visits_table.py` (new; `down_revision = "b8f3c1d92a47"`, confirmed current head)
- `apps/api/services/agent_classifier.py` (new)
- `apps/api/main.py` (one new `# noqa: F401` import line — additive only)
- `tests/unit/test_agent_classifier.py` (new)
- `apps/api/services/bot_filter.py` — READ-ONLY reference, not modified this phase

status: DONE — EXECUTE + independent EVL both complete 2026-07-22; files created as claimed
(migration hash: d11b39a6c843); 3/4 gates GREEN (classifier 24/24, registration smoke, full
regression 716 passed/2 skipped/no regression); live-DB migration up/down/up cycle remains a
KNOWN-GAP (Docker unavailable in sandbox at both EXECUTE and EVL time) — close-the-gap command
recorded in the phase report. Phase classified 🔨 CODE DONE (not ✅ VERIFIED) in the umbrella
pending that gap.

---

## Phase 2

Plan: `process/features/evallayer/active/evallayer_22-07-26/phase-02-ingest-wiring_PLAN_22-07-26.md`

Blast radius (confirmed real, no collisions with any other phase — verified 2026-07-22 at PVL
against Phase 1's DONE entry above and Phase 3's planned blast radius, both disjoint from the
files below):

- `apps/api/routers/events.py` (modified — ingest hot path restructure)
- `apps/api/services/agent_visit_persistence.py` (new)
- `apps/api/config.py` (modified — new `agent_detection_enabled` flag)
- `tests/unit/test_agent_visit_persistence.py` (new)
- `tests/integration/test_events_ingest.py` (modified — extended)

No overlap with Phase 1 (`agent_visit.py`, migration, `agent_classifier.py`, `main.py`,
`test_agent_classifier.py` — all consumed read-only here) or Phase 3 (`agents.py`,
`schemas/agents.py`, `dashboard/agents/*`, `layout.tsx`, `api.ts`/`api-types.ts` — none touched
this phase).

status: DONE — EXECUTE + independent EVL both complete 2026-07-22. Gate: CONDITIONAL (accepted,
session/autonomous). EXECUTE shipped all 5 blast-radius files as claimed; EVL confirmed full unit
baseline GREEN (725 passed, 2 skipped — Phase 1 baseline was 716, +9, 0 regressions; classifier
24/24) and, in lieu of a live Docker run, a static safety review confirming all 3 declared safety
properties (agent branch hard-returns before the Event insert; flag-off is byte-identical to
pre-Phase-2 behavior; `persist_agent_visit` is fail-open — logs keys-only, rolls back, never
raises). Two Known-Gaps remain open and are NOT blockers to this DONE annotation (both
environment/tooling gaps, not design defects): (1) the 5 `TestAgentDetection` integration cases
(AC1-AC4 + flag-OFF) are collect-clean but unrun — no responsive Docker daemon in this sandbox at
either EXECUTE or EVL time; close command: `MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest
tests/integration/test_events_ingest.py -k "agent or datacenter" -m integration -q`; (2) AC5
(ingest latency benchmark) has no harness yet — backlog stub:
`process/features/evallayer/backlog/phase-02-latency-benchmark_NOTE_22-07-26.md`. Phase classified
🔨 CODE DONE (not ✅ VERIFIED) in the umbrella pending closure of both gaps. See phase plan's
Validate Contract and phase report for full findings.

---

## Phase 3

Plan: `process/features/evallayer/active/evallayer_22-07-26/phase-03-read-api-dashboard_PLAN_22-07-26.md`

Blast radius (confirmed real at PVL 2026-07-22, no collisions with Phase 1 or Phase 2's DONE
entries above — Phase 1 owns `agent_visit.py`/migration/`agent_classifier.py`/one `main.py`
import line; Phase 2 owns `events.py`/`agent_visit_persistence.py`/`config.py`; neither touches
any file below):

- `apps/api/routers/agents.py` (new)
- `apps/api/schemas/agents.py` (new)
- `apps/api/main.py` (one new router-registration line + one new import — additive only,
  confirmed disjoint from Phase 1's own additive import line in the same file)
- `apps/web/src/app/dashboard/agents/*` (new — list + detail pages)
- `apps/web/src/app/dashboard/layout.tsx` (new nav item)
- `apps/web/src/lib/api.ts`, `apps/web/src/lib/api-types.ts` (new typed methods/types)
- `apps/web/src/components/ui/status-badge.tsx` (3 new STATUS_TONE entries)
- `tests/integration/test_agents_api.py` (new)
- `apps/web/e2e/agents.spec.ts` (new)

status: DONE — EXECUTE + independent EVL both complete 2026-07-22. EVL confirmation run (vc-tester)
GREEN on all runnable gates: FE compile (`npm run build`), unit regression (725 passed/2 skipped,
== baseline, 0 regressions), and static safety review confirming all 5 declared properties
(`verify_site_access` first-line-of-every-handler; `AgentVisit`-only queries, no Visitor/Event join
= AC6; `/stats` registered before `/{agent_visit_id}` catch-all; UUID-parse-then-404 on the detail
route; 3 distinct `STATUS_TONE` badge entries = AC7). FE↔BE contract type-verified transitively by
the FE build. 2 KNOWN-GAPS remain open (env-gated, not design defects, not blockers): (1) Docker
integration run (10 cases in `tests/integration/test_agents_api.py`, collect-clean, unrun — no
responsive Docker in this sandbox at EXECUTE or EVL time; close command: `docker compose -f
infra/docker-compose.yml up -d postgres redis && .venv/bin/python -m pytest
tests/integration/test_agents_api.py -q`); (2) Playwright e2e (`apps/web/e2e/agents.spec.ts`) needs
a running dev server, not started this run; close command: `npm run --prefix apps/web dev & npx
playwright test apps/web/e2e/agents.spec.ts --config=apps/web/playwright.config.ts`. Badge
Agent-Probe judgment (AC7 visual/text check) is a backlog test-building stub, not scriptable, not
a blocker. Phase classified 🔨 CODE DONE (not ✅ VERIFIED) pending closure of both Docker/e2e gaps
— same environment-gap pattern as Phase 1/Phase 2. See phase report's `## EVL Confirmation` section
for full detail.

status (prior): PVL PASS (2026-07-22) — validate-contract written, `generated-by: inner-pvl: phase-3`.
Gate: PASS with documented environment known-gaps (Docker PG+Redis unavailable in this sandbox
for the Hybrid backend integration tests; Playwright e2e needs a dev server not started during
VALIDATE) — same environment condition already logged for Phase 1/Phase 2, not phase-3-specific.
2 mechanical plan gaps found and fixed in-plan during VALIDATE: (1) missing test-authoring
checklist step (Step D added with exact test-function names), (2) `AgentVisit` has no
`agent_visit_id` column — detail route must query by the inherited `id` PK with UUID
parse-then-404, not a nonexistent business-id field (A2 amended).

---

## Phase 4

Plan: `process/features/evallayer/active/evallayer_22-07-26/phase-04-ip-verification_PLAN_22-07-26.md`

Blast radius (confirmed real at PVL 2026-07-22, no collisions with Phase 1, Phase 2, or Phase 3's
entries above — Phase 4 EXTENDS two Phase-2-owned files, which is expected: Phase 4 depends on
Phase 2's output and no file is claimed "new/owned" by two phases):

- `apps/api/services/agent_verification.py` (new)
- `apps/api/services/agent_visit_persistence.py` (extend — Phase 2 owns creation, Phase 4 adds
  `upgrade_verification_method`)
- `apps/api/jobs/scheduler.py` (extend — new `_agent_verification_sweep_job`, job id
  `agent_verification_sweep`, confirmed non-colliding with 8 existing job ids)
- `apps/api/config.py` (extend — Phase 2 owns creation of `agent_detection_enabled`, Phase 4 adds
  `agent_verification_sweep_interval_minutes`)
- `apps/api/data/agent_ip_ranges/openai.json`, `perplexity.json` (new; no `anthropic.json` —
  structural ceiling)
- `apps/api/data/agent_ip_ranges/mock/openai.json`, `mock/perplexity.json` (new)
- `tests/unit/test_agent_verification.py` (new, 7 scenarios)
- `tests/integration/test_agent_verification_sweep.py` (new, Docker known-gap)

No overlap with Phase 1 (`agent_visit.py`, migration, `agent_classifier.py`, `main.py`,
`test_agent_classifier.py`) or Phase 3 (`agents.py`, `schemas/agents.py`, `dashboard/agents/*`,
`layout.tsx`, `api.ts`/`api-types.ts`, `status-badge.tsx`) — none touched this phase.

status: PVL PASS (2026-07-22) — validate-contract written, `generated-by: inner-pvl: phase-4`.
Gate: PASS. 2 mechanical/test-coverage gaps found and fixed in-plan during VALIDATE (not deferred,
not accepted-as-CONCERN): (1) `run_verification_sweep`'s per-row fail-open isolation was proven
ONLY by the Docker-gated Hybrid integration test — a vacuous-green risk; added a Fully-Automated
unit test using a mocked `AsyncSession` (no Docker needed) so this property now has real automated
coverage; (2) `load_ip_ranges()`'s "module-level in-process cache is acceptable" language risked
test-isolation bugs (a cached result from one unit test's `mock_external_apis` value leaking into
another) — resolved by removing caching entirely (Resolved Design Decision 11: read fresh every
call; files are tiny, sweep runs at most every 15 min). One environment Known-Gap remains, same
pattern as Phase 1/2/3: the Docker-gated sweep-vs-real-DB integration test is collect-clean but
unrun in this sandbox (no Docker) — does not block VERIFIED per SPEC AC8 note. Phase classified
ready for EXECUTE; not yet CODE DONE or VERIFIED (no code written yet — PVL only).

status: DONE — EXECUTE + independent EVL both complete 2026-07-22. All checklist Steps A–F
implemented as specified, no deviation. EVL confirmation run (independent of execute-agent's
internal claim) re-verified: unit 10/10 pass; hot-path import check `events.py`=0 (AC5/OQ2 hot
path untouched); Anthropic structural ceiling confirmed (no `anthropic.json` on disk anywhere
under `apps/api/data`); full unit regression 735 passed / 2 skipped (baseline 725/2 → +10, no
drop); both backlog notes confirmed present on disk. 1 Known-Gap remains open (environment/tooling,
not a design defect, same pattern as Phase 1/2/3): Docker-gated `test_agent_verification_sweep.py`
integration test is collect-clean but unrun (no Docker in this sandbox) — does not block VERIFIED
per SPEC AC8 note; close command: `docker compose -f infra/docker-compose.yml up -d postgres redis
&& .venv/bin/python -m pytest tests/integration/test_agent_verification_sweep.py -m integration -q`.
Files created: `agent_verification.py`, 4 data JSONs, `test_agent_verification.py`,
`test_agent_verification_sweep.py`; edited: `agent_visit_persistence.py`, `scheduler.py`,
`config.py`. Phase classified 🔨 CODE DONE (not ✅ VERIFIED) pending closure of the one Docker gap.
Not committed this session (vc-git-manager next).

---

## Phase 7

Plan: `process/features/evallayer/active/evallayer_22-07-26/phase-07-outreach-exclusion_PLAN_22-07-26.md`

Blast radius (confirmed real at PVL 2026-07-22 via fresh `grep -n` against real code — no
collisions with Phase 1, Phase 2, Phase 3, or Phase 4's entries above; none of those phases touch
any file below):

- `apps/api/services/identity_classification.py` (modify — extend `is_emailable_identity`)
- `apps/api/services/campaign_sender.py` (modify — line 202 call-site wiring)
- `apps/api/routers/campaigns.py` (modify — line 725, `_resolve_linkedin_targets` call-site wiring)
- `apps/api/services/csv_exporter.py` (modify — line 79 call-site wiring)
- `tests/unit/test_agent_origin_exclusion.py` (new — regression test file, C1–C5, no Docker)

No schema/migration file in this phase's blast radius. No overlap with Phase 5's declared blast
radius either — Phase 5 has not run RESEARCH yet (its own blast radius is still `TBD`, candidates
only: `company_resolver.py` + an unconfirmed enrichment/lead-creation service). **Intentional
concern-level (not file-level) overlap flagged with Phase 5:** the instant Phase 5 adds
`IdentifiedVisitor.source_agent_visit_id` (its own job, not this phase's), this phase's guard
activates automatically via the `getattr(..., "source_agent_visit_id", None)` wiring landed here.
This is a forward-binding dependency captured as a written contract (D1–D6 in the Phase 7 plan),
not a shared-file collision — Phase 5's exit gate is required to re-run
`tests/unit/test_agent_origin_exclusion.py` (including the new C5 literal-field-name tripwire)
against real Phase-5-created rows before Phase 5 may be marked ✅ VERIFIED.

status: PVL PASS (2026-07-22) — validate-contract written, `generated-by: inner-pvl: phase-7`. Gate:
PASS. 1 plan update applied during VALIDATE (not deferred, not accepted-as-CONCERN): a `vc-security`
STRIDE scan found the guard is fail-open-by-rename (a future field-name rename anywhere would
silently reopen the outreach hole since `getattr` just returns `None` again) — closed by adding
Step C5, a Fully-Automated literal-string tripwire test with zero Docker/import dependency, plus a
new D6 forward-contract line requiring Phase 5 to keep C5 green. AC10's core test
(`test_agent_origin_overrides_person_level`) was confirmed genuinely non-vacuous at PVL time: the
current unmodified `is_emailable_identity` signature accepts only one positional argument, so
calling the planned 2-arg form today raises `TypeError` — a real red state, not just a documented
one. 3 Known-Gaps accepted as non-blocking, none touching the AC10 core proof: (1) skip-counter
miscategorization (agent-origin skips share a counter with company-level skips — cosmetic,
observability-only); (2) D4 "no future 4th bypass path" remains a written contract, not a centrally
code-enforced chokepoint (accepted as an intentional scope-limited residual); (3) real-row
re-verification against actual Phase-5 data is inherently deferred until Phase 5 exists (already a
binding requirement on Phase 5's own exit gate, D5/D6 — not an open gap in this phase's own proof).
status: DONE — EXECUTE + independent EVL both complete 2026-07-22. All checklist Steps A→B→C
(C1-C5)→Phase-5-Contract implemented exactly per validate-contract, no deviation. EVL confirmation
run (independent `vc-tester` re-run, not relying on execute-agent's internal claim) GREEN: AC10 gate
`test_agent_origin_exclusion.py` 17/17; full unit regression 752 passed/2 skipped (baseline 735 +
17, 0 regressions); adjacent `test_outbound_identity_gate.py` 18/18 (no breakage); non-vacuity
confirmed by independent code inspection (override is the first, unconditional statement — deletion
would flip C1 red for every `PERSON_LEVEL_PROVIDERS` value). No Docker known-gap in this phase
(unlike Phases 1-4) — all gates Fully-Automated. Phase classified **✅ VERIFIED**. The only residual
(D5, real-Phase-5-row re-verification) is a forward dependency on Phase 5's own exit gate, not a gap
in this phase's own proof — Phase 5 Contract (D1-D6) is now BINDING and must be honored/re-verified
before Phase 5 may be marked VERIFIED. Not committed this session (vc-git-manager next). Report:
`phase-07-outreach-exclusion_REPORT_22-07-26.md`.

---

## Phase 5

Plan: `process/features/evallayer/active/evallayer_22-07-26/phase-05-company-resolution_PLAN_22-07-26.md`

Blast radius (confirmed real at PVL 2026-07-22 via fresh reads of live code — no collisions with
Phase 1, 2, 3, 4, or 7's entries above; none of those phases touch any file below):

- `apps/api/migrations/versions/` (new migration, `down_revision = "d11b39a6c843"` — Phase 1's head,
  confirmed via `alembic heads`)
- `apps/api/models/visitor.py` (modify — add `Visitor.is_agent_derived`, `IdentifiedVisitor.source_agent_visit_id`)
- `apps/api/models/agent_visit.py` (modify — FK constraint on `resolved_company_id`, stale-docstring update)
- `apps/api/services/agent_company_resolution.py` (new)
- `apps/api/services/agent_visitor_filters.py` (new)
- `apps/api/services/identity_resolver.py` (modify — VALIDATE amendment, closes GUARD #1 atomicity
  gap: optional `source_agent_visit_id` kwarg on `resolve()`/`_save_identified()`, default `None`)
- `apps/api/jobs/scheduler.py` (modify — extend `_agent_verification_sweep_job`, 2nd step in the same
  try block Phase 4 already owns; no new job id)
- `apps/api/routers/visitors.py` (modify — 3 of the 7 AC2 exclusion sites: `list_visitors`,
  country-facet, `get_visitor_detail`)
- `apps/api/routers/visitors_helpers.py` (modify — `_compute_visitor_stat_counts`)
- `apps/api/services/resolution_runner.py` (modify — `run_resolution_for_site` eligibility query)
- `apps/api/tasks/segmentation_tasks.py` (modify — `_check_triggers`, `_run_segmentation_for_site`)
- `apps/api/services/visitor_aggregator.py` (modify — `_resolve_companies`)
- `apps/api/tasks/resolution_tasks.py` (modify — VALIDATE-added 7th AC2 exclusion site,
  `_process_site` eligibility query)
- `tests/unit/test_agent_company_resolution.py` (new)
- `tests/unit/test_agent_origin_exclusion.py` (extend — AC10 real-row re-run, Phase 7 D5/D6 BINDING obligation)

No overlap with Phase 1 (`agent_visit.py` schema fields only — Phase 5 adds a FK on an
already-existing column, not a new column; `agent_classifier.py`, `main.py` import line,
`test_agent_classifier.py`), Phase 2 (`events.py`, `agent_visit_persistence.py`, `config.py`), Phase
3 (`agents.py`, `schemas/agents.py`, `dashboard/agents/*`, `layout.tsx`, `api.ts`/`api-types.ts`,
`status-badge.tsx`), or Phase 4 (`agent_verification.py`, `agent_ip_ranges/*` data files) — none of
those phases touch any file this phase modifies. **Intentional Phase-7-contract fulfillment (not a
collision):** Phase 5 adds `IdentifiedVisitor.source_agent_visit_id` — exactly the forward-binding
dependency Phase 7's D1-D6 contract named. Phase 7's own files
(`identity_classification.py`, `campaign_sender.py`, `campaigns.py`, `csv_exporter.py`,
`test_agent_origin_exclusion.py`) are NOT touched by Phase 5 except the one explicitly-anticipated
extension: `tests/unit/test_agent_origin_exclusion.py` gains the AC10 real-row re-run test, which is
Phase 7's own D5/D6 obligation being fulfilled by Phase 5, not an unplanned edit.

status: PVL PASS (2026-07-22) — validate-contract written, `generated-by: inner-pvl: phase-5`.
Gate: PASS. 2 mandatory FAILs found via `vc-security`
STRIDE scan and resolved in-plan this same PVL cycle (not deferred, not accepted-as-CONCERN): (1) GUARD #1 atomicity —
the original design ("call `resolve()` UNMODIFIED, set the marker via a separate UPDATE after
`resolve()` returns") left a real, mechanically-confirmed window where a freshly committed,
un-marked, potentially person-level `IdentifiedVisitor` row was durable and visible to any other DB
connection — the "deferred/2nd-batch marker" failure mode. Fixed by threading an optional
`source_agent_visit_id` kwarg through `resolve()`/`_save_identified()` in `identity_resolver.py`,
set at INSERT time (zero behavior change for existing human callers). (2) GUARD #2 completeness —
found a 7th, previously unenumerated AC2 exclusion site (`apps/api/tasks/resolution_tasks.py::_process_site`,
a live Celery-beat-scheduled task with the same eligibility shape as the already-fixed
`resolution_runner.py`); added `human_only_visitor_filter()` there too. 2 non-blocking Known Gaps
accepted, both safe-direction (never an outreach leak): (a) identity-merge collision via
`_save_identified`'s pre-existing email-dedup path (a real human lead could inherit an agent-origin
marker via email collision — lead-loss, not a safety violation); (b) `AgentVisit` rollup staleness
(the model is confirmed to be an aggregate rollup per `(site_id, vendor, product_or_ua_token)`, not
per-visit — `resolved_company_id` sticks forever once set even as the underlying IP changes on later
visits). Both backlog-noted (excluded from the CONCERN/FAIL count per the Known-Gap exclusion rule):
`process/features/evallayer/backlog/phase-05-identity-merge-collision_NOTE_22-07-26.md`,
`process/features/evallayer/backlog/phase-05-rollup-staleness_NOTE_22-07-26.md`. Phase classified
ready for EXECUTE (validate-contract Gate: PASS); not yet CODE DONE or VERIFIED (no
code written yet — PVL only).

status: DONE — EXECUTE complete 2026-07-22. All checklist Steps B→C→D→E implemented; migration
a1c7e4f92b83 created (single head, down_revision d11b39a6c843, valid offline). Exit gates green:
AC10 suite 18 passed (incl. new real-row re-run test_ac10_real_sweep_created_row_is_non_emailable),
Phase-5 suite 25 passed, full regression 778 passed/2 skipped (0 regressions vs 752/2 baseline),
AC14 mock-mode 25 passed. GUARD #1 marker atomic (set in the same INSERT as the IdentifiedVisitor
row); GUARD #2 all 7 AC2 sites wired via the shared `human_only_visitor_filter()`. 2 within-blast-radius
deviations recorded in the plan's ## Deviations (DEV-1 instance-state marker threading keeps changes
inside identity_resolver.py and also covers the hunter/apollo/pdl mixins; DEV-2 AC2 D1+D6-facet via the
shared `_build_visitor_filters` helper — validate-contract-sanctioned). Docker known-gaps (migration
apply/rollback + integration sweep round-trip) unrun — no disposable Postgres in sandbox. High-risk
evidence pack written (harness/*-phase5.json, incl. adversarial-validation-phase5.json). Independent
EVL (vc-tester re-run) + commit still pending. Not committed this session.

status: DONE — independent EVL confirmation run (vc-tester, not relying on execute-agent's internal
claim) GREEN on all Fully-Automated gates: AC10 suite 18/18 (incl. real-row re-run
`test_ac10_real_sweep_created_row_is_non_emailable`), Phase-5 suite 25/25, full regression 778
passed/2 skipped (baseline 752/2, +26, 0 regressions), AC14 mock-mode 25/25. Static review confirmed:
GUARD #1 marker atomic with NO instance-state leak across calls (`self._active_source_agent_visit_id`
reset unconditionally at the top of every `resolve()` — human callers get a cleared value); GUARD #2
all 7 AC2 sites wired via `human_only_visitor_filter()`; no agent-email path exists. **Phase 7 D1-D6
contract FULFILLED**: `IdentifiedVisitor.source_agent_visit_id` exists with the exact literal name,
Phase 7's `getattr(...)` tripwire is now live (not a no-op); no PERSON_LEVEL provider ever assigned to
an agent-resolved row; no 4th bypass path introduced; `test_agent_origin_exclusion.py` re-run against
a real Phase-5-created row is green. 2 Docker known-gaps (migration apply/rollback, integration sweep)
remain open — no disposable Postgres in this sandbox; close commands documented in the phase report.
2 pre-existing safe-direction backlog residuals carried forward unchanged (identity-merge collision,
rollup staleness — both NEW PLAN REQUIRED, neither touched this phase per plan E4). Phase classified
🔨 CODE DONE (not ✅ VERIFIED — the two Docker known-gaps are real, undischarged gaps on this phase's
own highest-risk-class surface: schema migration + live sweep). Report:
`phase-05-company-resolution_REPORT_22-07-26.md`. Not committed this session (`vc-git-manager` next).

---

## Phase 6

Plan: `process/features/evallayer/active/evallayer_22-07-26/phase-06-aggregation-analytics_PLAN_22-07-26.md`

Blast radius (confirmed real at PVL 2026-07-22 via fresh reads of live code — no collisions with
Phase 1, 2, 3, 4, 5, or 7's entries above):

- `apps/api/services/agent_aggregator.py` (new)
- `apps/api/routers/agents.py` (extend — Phase 3 owns file, Phase 6 adds one additive endpoint;
  confirmed real insertion point directly after the existing `/stats` handler at line 100, before
  the `/{agent_visit_id}` catch-all at line 102)
- `apps/api/schemas/agents.py` (extend — Phase 3 owns file, Phase 6 appends 2 new schema classes;
  confirmed no name collision with existing `AgentOut`/`AgentDetailOut`/`AgentListResponse`/
  `AgentStatsResponse`)
- `apps/web/src/lib/api-types.ts` (extend — Phase 3 owns file, Phase 6 appends 2 new interfaces)
- `apps/web/src/lib/api.ts` (extend — Phase 3 owns file, Phase 6 appends 1 new client method
  mirroring the existing `getAgentStats` pattern at line 476)
- `apps/web/src/app/dashboard/agents/page.tsx` (extend — Phase 3 owns file, Phase 6 appends 3
  fixed cards below the existing KPI row; existing `stats` query/table untouched)
- `tests/unit/test_agent_aggregator.py` (new)
- `process/features/evallayer/backlog/phase-06-daily-timeseries_NOTE_22-07-26.md` (already created
  during PLAN-SUPPLEMENT — confirmed present on disk)

No overlap with Phase 1 (`agent_visit.py` MODEL is read-only reference here, never modified —
Phase 6 only reads `vendor`/`visit_count`/`page_paths`/`verification_method` columns that already
exist), Phase 2 (`events.py`, `agent_visit_persistence.py`, `config.py` — none touched), Phase 4
(`agent_verification.py`, IP-range data files, `scheduler.py` extension — none touched; Phase 6
only reads the `verification_method` field Phase 4 populates), Phase 5 (`visitor.py`,
`agent_company_resolution.py`, `identity_resolver.py`, `routers/visitors.py` and friends — none
touched), or Phase 7 (`identity_classification.py`, `campaign_sender.py`, `campaigns.py`,
`csv_exporter.py`, `test_agent_origin_exclusion.py` — none touched). Phase 6 extends 4 files
Phase 3 created (`agents.py`, `schemas/agents.py`, `api.ts`, `api-types.ts`, `page.tsx`) purely
additively — same accepted "extend, don't collide" pattern already used by Phase 4/5 extending
Phase 2's files. No new table, no migration, no Celery/scheduler task — computed on-the-fly per
request.

status: PVL PASS (2026-07-22) — validate-contract written, `generated-by: inner-pvl: phase-6`.
Gate: PASS. 1 plan update applied in-plan during VALIDATE (not deferred, not accepted-as-CONCERN):
route-registration order (the Step B2 trap — `/analytics` must be registered before the
`/{agent_visit_id}` catch-all) previously had ONLY Hybrid (Docker-gated) proof; added Step C3, a
Fully-Automated import-time route-list-order assertion with zero Docker/DB dependency, closing the
single highest-named risk in this phase with a real automated gate instead of a Hybrid-only
inference. AC2 isolation (compiled-SQL substring check, Step C2) and AC11 correctness (Step C1)
confirmed mechanically feasible against the real `AgentVisit` model and existing `timeseries.py`
pure-split precedent — no design gaps found. No schema/migration/Celery scope creep confirmed —
matches the plan's on-the-fly, additive-only claim. Known environment gaps (Docker Postgres,
Playwright dev server unavailable in this sandbox) carried forward for the 2 Hybrid gates
(`/analytics` endpoint e2e, dashboard card render e2e) — same pattern as every prior phase in this
program (1/2/3/4/5), does not block PASS, does not block VERIFIED per program precedent. This is
the FINAL phase of the evallayer program; whole-program AC2/AC10 regression posture reconfirmed
intact (Phase 6 reads Phase 1/2/4's data structurally, never writes to Visitor/Event, never touches
Phase 5/7's outreach-exclusion surfaces).
