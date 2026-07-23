---
name: plan:handoff-phase-02-handoff-correlation
description: "Handoff Detection — Phase 02: fetch↔click handoff correlation + dashboard badge (H2)"
date: 23-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-02
---

# Phase 02 — Handoff Correlation + Dashboard (H2)

**Program:** handoff
**Umbrella plan:** process/features/evallayer/active/handoff_23-07-26/handoff-umbrella_PLAN_23-07-26.md
**SPEC:** process/features/evallayer/active/handoff_23-07-26/handoff_SPEC_23-07-26.md (AC-H2-1 through AC-H2-5)
**Phase status:** 🔨 CODE DONE (Docker gaps) — EVL confirmed GREEN
**Report destination:** process/features/evallayer/active/handoff_23-07-26/phase-02-handoff-correlation_REPORT_23-07-26.md (flat in the program task folder)

---

## Purpose

Turn H1's per-hit `agent_fetch_events` stream into Beam's headline differentiator: when an
on-demand fetch of page X by vendor V happens at time T, and a human's AI-referral click (via the
already-shipped `ai_source`/`first_touch_referrer` fields) lands on the same page X from the same
vendor family within a bounded window after T, link them. Surface the link on the visitor-detail
dashboard as a confidence-qualified, never-certain badge. AC-H2-3 (both-directions emailability
separation) is the single highest-priority gate in this entire program — it must pass before this
phase can be marked VERIFIED, mirroring the discipline of EvalLayer's AC10.

---

## Entry Gate

- Phase 1 (H1) exit gate passed: `agent_fetch_events` table live, tiering correct, tests green
- Parallel-safe with Phase 3 per umbrella's Pre-PVL Conflict Resolution — Phase 2 registers its
  `apps/api/jobs/scheduler.py` job entry FIRST (before Phase 3); Phase 3 must additively append
  after re-reading this phase's changes

---

## LOCKED Design Decisions (this supplement pass)

These decisions are now locked and encoded directly into the checklist below — INNOVATE's job at
Step 2 is reduced to confirming/re-verifying them against fresh code state, not re-deciding them.

1. **Module name/location:** `apps/api/services/agent_handoff_correlation.py` — mirrors the
   `agent_company_resolution.py` naming precedent (`apps/api/services/agent_{concept}.py`).
   Public entrypoint: `async def run_handoff_correlation_sweep(db: AsyncSession) -> None`.
2. **Model:** `apps/api/models/agent_handoff_link.py` — `class AgentHandoffLink(Base)`, table
   `agent_handoff_links`. `site_id`/`visitor_id` are **plain String columns, no
   `ForeignKey()`** — same "natural key, no FK" house convention as `AgentFetchEvent.site_id`
   (see `agent_fetch_event.py` docstring) and `AgentVisit.resolved_company_id`.
   `agent_fetch_event_id` is a `UUID` column referencing `agent_fetch_events.id` (also no FK
   constraint — same house convention, kept consistent across the join). Columns:
   `site_id: String(50)`, `visitor_id: String(100)`, `agent_fetch_event_id: UUID` (unique —
   one link per fetch event), `confidence: String(10)`, `method: String(30)` default
   `"temporal-page-match"`, `delta_seconds: Integer`, `matched_page: String(500) | None`.
   `id`/`created_at`/`updated_at` from `Base`. Table args:
   `UniqueConstraint("agent_fetch_event_id")`, `Index("idx_agent_handoff_links_site_visitor",
   "site_id", "visitor_id")`, `Index("idx_agent_handoff_links_site_created", "site_id",
   "created_at")`.
3. **Confidence schema keeps 3 tiers (`high`/`medium`/`low`, `String(10)`) but the sweep's
   WRITE POLICY is 2-tier: only `high` and `medium` links are ever inserted. `low`-confidence
   candidate matches are discarded, not written.** This is a deliberate precision-over-recall
   choice for a v1 differentiator feature — a badge is only worth showing when the sweep is
   fairly confident. The `low` value stays in the schema (not removed) so a future phase can
   loosen the write policy without a migration. Document this explicitly in the module
   docstring and in the phase report.
4. **Confidence formula:**
   - `high`: exact `page_path` match AND same vendor family AND `delta_seconds <= 300` (5 min).
   - `medium`: (exact `page_path` match AND vendor family AND `300 < delta_seconds <= 1800`)
     OR (vendor family match, same site, window-bound, but `page_path` mismatch — i.e. the
     agent fetched a different page than the human ultimately landed on).
   - **Perplexity cap:** any candidate whose fetch-side `vendor == "perplexity"` is capped at
     `medium` regardless of exact-page/delta — never `high` (undeclared-crawler trust discount
     per SPEC Constraint/Background).
   - Anything that would otherwise compute as `low` → discarded (see decision 3).
5. **Candidate selection tie-break (within one fetch event, multiple click candidates in
   window):** exact `page_path` match wins over any delta difference first; among exact-path
   candidates (or if none are exact-path), smallest `delta_seconds` wins.
6. **Vendor-family mapping — CONFIRMED AT VALIDATE (23-07-26), locked, no longer open:**
   `openai` ↔ `chatgpt`, `anthropic` ↔ `claude`, `perplexity` ↔ `perplexity`. Verified against
   `agent_classifier.py::_VENDOR_TOKENS` (fetch-side vendor values: `openai`, `anthropic`,
   `perplexity`, `bytespider`) and `ai_referral.py::AI_REFERRER_DOMAINS` (click-side labels).
   `bytespider` has no `ai_source` equivalent and needs no mapping entry — it is structurally
   moot: `_ON_DEMAND_TOKENS` never includes any bytespider token, so a bytespider fetch is never
   `tier=on-demand` and is therefore never eligible for the correlation sweep in the first place.
   Implement as a plain `dict[str, str]` with exactly the 3 entries above; a fetch `vendor` with
   no dict entry (i.e. `bytespider`, or any future unmapped vendor) must short-circuit to "no
   candidate match" rather than raise — use `.get(vendor)` and skip on `None`.
7. **Window:** 30 minutes (`fetch_at` to `fetch_at + 30min`), matches SPEC default.
8. **Sweep query source — batch size CONFIRMED AT VALIDATE:** unlinked on-demand
   `agent_fetch_events` rows (`tier == 'on-demand'`, `created_at > now() - 60min`, no existing
   `agent_handoff_links` row for that `agent_fetch_event_id`), batched via a `limit: int = 20`
   function parameter default — mirrors `agent_company_resolution.py::run_company_resolution_sweep`'s
   exact convention (a parameter default, NOT `agent_verification.py`'s module-level
   `_SWEEP_BATCH_LIMIT` constant style — use the parameter-default shape). For each candidate
   fetch event, query `events` table for `event_type='pageview'` rows with matching `site_id`,
   `created_at` between `fetch_at` and `fetch_at + 30min`, whose `referrer` classifies via
   `classify_ai_source()` to the matching vendor family. **Edge case (confirmed at VALIDATE):**
   when the fetch event's `page_path` is `None`, an exact-page match is impossible by definition —
   treat as a page_path mismatch (falls to the `medium` branch of Decision 4, never `high`), and
   write `matched_page` as whatever the fetch event's `page_path` value is (`None` is a valid
   stored value).
9. **Fail-open per-row processing:** mirror `agent_company_resolution.py`'s
   `run_company_resolution_sweep` pattern exactly — each candidate fetch event processed in its
   own `try/except`, own `await db.commit()` per successful link insert, `except Exception:
   logger.exception(...)` (structlog, keys-only, no PII) on failure, continue to next row. One
   bad row never aborts the sweep.
10. **Scheduler wiring:** new config `handoff_correlation_sweep_interval_minutes: int = 10` in
    `apps/api/config.py` (near `agent_verification_sweep_interval_minutes`). New
    `async def _handoff_correlation_sweep_job() -> None` in `apps/api/jobs/scheduler.py`,
    registered via its own `scheduler.add_job(...)` call — **own job, NOT chained into
    `_agent_verification_sweep_job`**. Per umbrella Pre-PVL Conflict Resolution, this phase
    registers its job entry BEFORE Phase 3's spike-detector job.
11. **API surface (additive only):**
    - `apps/api/schemas/visitors.py::VisitorDetailOut` — add 5 nullable fields:
      `handoff_vendor: str | None = None`, `handoff_confidence: str | None = None`,
      `handoff_delta_seconds: int | None = None`, `handoff_matched_page: str | None = None`,
      `handoff_fetch_at: datetime | None = None`.
    - `apps/api/routers/visitors.py::get_visitor_detail` (line ~541-636) — in the existing
      data-merge block before `return VisitorDetailOut(**data)`, query the latest
      `AgentHandoffLink` row for this `(site_id, visitor_id)` (if any), join to its
      `AgentFetchEvent` for `vendor`/`created_at`, and populate the 5 new fields. Read-only
      addition; no change to existing fields or query shape.
    - `apps/api/schemas/agents.py::AgentAnalyticsResponse` — add
      `handoff_links_count: int`.
    - `apps/api/services/agent_aggregator.py` — **RESOLVED AT VALIDATE, locked, no longer an
      open question.** Mirrors the existing `fetch_agent_visit_rows` (DB) / `aggregate_agent_analytics`
      (pure) split exactly: add a new sibling DB-fetch function
      `async def fetch_handoff_links_count(db: AsyncSession, site_id: str) -> int` (SELECT
      `count(*)` from `agent_handoff_links` filtered by `site_id` — no join, no `Visitor`/`Event`
      reference, mirrors the AC2-boundary comment style of `fetch_agent_visit_rows`). Change
      `aggregate_agent_analytics`'s signature to
      `aggregate_agent_analytics(rows: list[dict], handoff_links_count: int, top_n: int = 10) -> dict`
      — add `"handoff_links_count": handoff_links_count` to the returned dict. This keeps the
      pure/no-DB contract on `aggregate_agent_analytics` itself fully intact (the DB read stays in
      the new sibling fetch function, exactly as it already does for `rows`). The router calling
      this function passes both `fetch_agent_visit_rows(...)` and `fetch_handoff_links_count(...)`
      results.
12. **Dashboard FE (additive, mirrors the ai_source badge pattern):**
    - `apps/web/src/lib/api-types.ts` — extend the **`VisitorDetail`** interface (~line 205,
      confirmed at VALIDATE — this IS the `VisitorDetailOut`-equivalent TS type) with the 5 new
      optional fields; extend the **`AgentAnalytics`** interface (~line 345, confirmed at
      VALIDATE — this IS the `AgentAnalyticsResponse`-equivalent) with `handoff_links_count: number`.
    - `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` (~line 448 hero area, ~line
      797 InfoRow list — confirm exact lines at RESEARCH, file may have drifted) — add a
      badge/InfoRow rendering PROBABILISTIC copy only, e.g. "ChatGPT fetched this page 6 min
      earlier — medium confidence" — never an unqualified/certain assertion (AC-H2-4). Mirror
      the existing `ai_source` badge's visual pattern (same component family).
    - `apps/web/src/app/dashboard/visitors/page.tsx` (~line 650 — confirm at RESEARCH) — add a
      small pill/indicator on the visitor-list row when a handoff link exists.
    - `apps/web/src/app/dashboard/agents/page.tsx` — surface `handoff_links_count` on the
      existing analytics cards (mirrors how `by_vendor`/`top_pages`/`by_verification` are
      already rendered — confirm exact card at RESEARCH).

---

## Blast Radius

- `apps/api/models/agent_handoff_link.py` (new)
- `apps/api/migrations/versions/<hash>_add_agent_handoff_links_table.py` (new; additive-only).
  **Migration head — RE-VERIFIED AT VALIDATE (23-07-26):** `cd apps/api &&
  .venv/bin/python -m alembic heads` returns a SINGLE head: `a3e9f1c7d2b5` (visitors-identity
  "owned-data-layer" program's `add_identity_signals` migration). The plan's original provisional
  value (`c4e8f1a9d2b7`, H1's own migration) is now STALE — two foreign migrations landed on top
  of it since H1 finished: `f8a2c1d9b3e7` (`add_company_graph`) then `a3e9f1c7d2b5`
  (`add_identity_signals`), confirmed linear (single head, no fork — not a merge-decision FAIL).
  **This migration's `down_revision` MUST be `a3e9f1c7d2b5`.** Re-run `alembic heads` immediately
  before EXECUTE writes the migration file — this chain is still shared with an actively-developing
  parallel program and may have moved again since VALIDATE time.
- `apps/api/services/agent_handoff_correlation.py` (new — locked name, see Decision 1)
- `apps/api/config.py` — one new setting: `handoff_correlation_sweep_interval_minutes: int = 10`
- `apps/api/jobs/scheduler.py` — ONE new periodic job registration (additive function
  `_handoff_correlation_sweep_job` + one new `add_job(...)` call); do not touch any existing job
  registration
- `apps/api/services/identity_classification.py` — READ-ONLY reference only, confirming
  `is_emailable_identity()`'s existing `source_agent_visit_id` mechanism is untouched; never
  modified by this phase
- `apps/api/schemas/visitors.py` — 5 new nullable fields on `VisitorDetailOut`
- `apps/api/routers/visitors.py` — additive data-merge in `get_visitor_detail` (~line 541-636)
- `apps/api/schemas/agents.py` — 1 new field on `AgentAnalyticsResponse`
- `apps/api/services/agent_aggregator.py` — 1 new aggregation in `aggregate_agent_analytics`
- `apps/web/src/lib/api-types.ts` — TS type extensions (mirrors the 2 schema additions)
- `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` — badge/InfoRow addition
- `apps/web/src/app/dashboard/visitors/page.tsx` — list-row pill addition
- `apps/web/src/app/dashboard/agents/page.tsx` — analytics card addition
- `tests/unit/test_handoff_correlation.py` (new)
- `tests/unit/test_handoff_emailability_separation.py` (new — extends the Phase 7
  `test_agent_origin_exclusion.py` pattern; READ that existing test file during RESEARCH, do not
  reinvent its structure — it is already read and confirmed present at
  `tests/unit/test_agent_origin_exclusion.py`)
- `apps/api/schemas/visitors.py` / `apps/api/schemas/agents.py` API-contract test extensions
  (extend existing test files covering these schemas — confirm exact file names at RESEARCH)

---

## Implementation Checklist

### Step A — Data model + migration

- [ ] A1. Define `AgentHandoffLink` model per LOCKED Decision 2 exactly: `site_id String(50)`
      (no FK), `visitor_id String(100)` (no FK), `agent_fetch_event_id UUID` (no FK, unique),
      `confidence String(10)` (schema keeps `high`/`medium`/`low` even though the sweep only
      ever writes `high`/`medium` — see Decision 3), `method String(30)` default
      `"temporal-page-match"`, `delta_seconds Integer`, `matched_page String(500) | None`. This
      table NEVER references or writes `source_agent_visit_id` — it is a structurally separate
      surface per SPEC Constraint 1.
- [ ] A2. Generate additive-only migration for `agent_handoff_links`. **Re-verify the current
      migration head before setting `down_revision`** — do not assume `c4e8f1a9d2b7` without
      re-checking (see Blast Radius note above); this program's chain is a moving target shared
      with a parallel visitors-identity effort.
- [ ] A3. Register `AgentHandoffLink` in `apps/api/main.py`'s model-import block (mirrors how
      `AgentFetchEvent`/`AgentHandoffLink`'s siblings are already registered — confirm the exact
      import list at RESEARCH).

### Step B — Correlation sweep

- [ ] B1. Add `handoff_correlation_sweep_interval_minutes: int = 10` to `apps/api/config.py`
      (near `agent_verification_sweep_interval_minutes`, same style/comment convention).
- [ ] B2. Implement `apps/api/services/agent_handoff_correlation.py::run_handoff_correlation_sweep`
      per LOCKED Decisions 4-9: query unlinked on-demand `agent_fetch_events` (batched, reuse
      `agent_company_resolution.py`'s batch-size convention), for each find candidate `events`
      pageviews via `classify_ai_source()` vendor-family match within the 30-minute window,
      select best candidate per Decision 5's tie-break, compute confidence per Decision 4
      (including the Perplexity cap), and **only INSERT `high`/`medium` links — never write
      `low`** (Decision 3). Module docstring must state this write-policy explicitly.
- [ ] B3. Enforce `site_id` scoping on every query — no cross-site fetch/click pairs may link
      regardless of timing (AC-H2-5).
- [ ] B4. Fail-open per-row processing exactly per Decision 9 (own try/except, own commit,
      `logger.exception` keys-only on failure, continue).
- [ ] B5. Add `async def _handoff_correlation_sweep_job()` + its own
      `scheduler.add_job(...)` registration to `apps/api/jobs/scheduler.py`, additive only,
      registered BEFORE Phase 3's future job entry per umbrella Pre-PVL Conflict Resolution.

### Step C — Emailability separation (hard gate)

- [ ] C1. Confirm via code read (not assumption) that `AgentHandoffLink` creation never calls,
      imports, or references `source_agent_visit_id` or `is_emailable_identity()`'s internals.
- [ ] C2. Confirm the human-side `Visitor`/identity record's `is_emailable_identity` output is
      computed identically whether or not a handoff link exists for that visitor — no new
      conditional branch is introduced into that function by this phase.
- [ ] C3. Confirm the agent-fetch-event side of the link has no code path into
      campaign/email/social targeting — grep for any new join from `agent_fetch_events` or
      `agent_handoff_links` into outreach/campaign tables and confirm none exists.

### Step D — API + dashboard surfacing

- [ ] D1. Add the 5 nullable fields to `apps/api/schemas/visitors.py::VisitorDetailOut` per
      LOCKED Decision 11.
- [ ] D2. Extend `apps/api/routers/visitors.py::get_visitor_detail` (~line 541-636) to query the
      latest `AgentHandoffLink` for `(site_id, visitor_id)`, join `AgentFetchEvent` for
      `vendor`/`created_at`, and populate the 5 fields before `return VisitorDetailOut(**data)`.
      Read-only addition — no change to existing query shape or fields.
- [ ] D3. Add `handoff_links_count: int` to `apps/api/schemas/agents.py::AgentAnalyticsResponse`.
      In `apps/api/services/agent_aggregator.py`, add `fetch_handoff_links_count(db, site_id) ->
      int` (new sibling DB-fetch function, same pattern as `fetch_agent_visit_rows`) and extend
      `aggregate_agent_analytics(rows, handoff_links_count, top_n=10)` to include it in the
      returned dict — exact resolved shape locked at VALIDATE, see LOCKED Decision 11.
- [ ] D4. Extend `apps/web/src/lib/api-types.ts`'s **`VisitorDetail`** interface (~line 205)
      and **`AgentAnalytics`** interface (~line 345) — confirmed exact names at VALIDATE — with
      the matching TS fields (visitor detail + analytics).
- [ ] D5. Add visitor-detail dashboard badge/InfoRow entry in
      `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` rendering qualifying language
      (e.g. "AI research detected: ChatGPT fetched this page at 14:32, 6 minutes before this
      visit") — never an unqualified assertion (AC-H2-4). Mirror the existing `ai_source`
      badge's component pattern.
- [ ] D6. Add a small pill/indicator on the visitor-list row in
      `apps/web/src/app/dashboard/visitors/page.tsx` when a handoff link exists.
- [ ] D7. Add `handoff_links_count` surfacing to the existing analytics cards in
      `apps/web/src/app/dashboard/agents/page.tsx`.

### Step E — Tests

- [ ] E1. `tests/unit/test_handoff_correlation.py::test_link_created_within_window` — synthetic
      fixture, deterministic clock (proves AC-H2-1).
- [ ] E2. `tests/unit/test_handoff_correlation.py::test_no_link_outside_window` +
      `test_no_link_vendor_mismatch` (proves AC-H2-2).
- [ ] E3. `tests/unit/test_handoff_correlation.py::test_confidence_high_exact_page_fast` +
      `test_confidence_medium_slow_delta` + `test_confidence_medium_page_mismatch` +
      `test_perplexity_capped_medium` + `test_low_confidence_discarded_not_written` — proves the
      full confidence formula and the no-low-writes policy (LOCKED Decisions 3-4).
- [ ] E4. `tests/unit/test_handoff_emailability_separation.py` — asserts BOTH directions in one
      test: (a) linked visitor's `is_emailable_identity` output unchanged, (b) linked
      agent-fetch-event/agent-visit side never gains an emailability/outreach path (proves
      AC-H2-3 — the program's highest-priority gate). Also asserts (c) a tripwire: grep for
      `"source_agent_visit_id"` absence in `agent_handoff_link.py` and
      `agent_handoff_correlation.py` (mirrors Phase 7's C5 literal-field-name tripwire pattern).
- [ ] E5. API-contract test — extend the existing test file covering
      `apps/api/schemas/agents.py` (confirm exact file at RESEARCH) to assert `confidence` and
      `handoff_links_count` fields are always present on any handoff-link representation (proves
      AC-H2-4, Fully-Automated half); manual UI copy review for qualifying language (Agent-Probe
      half).
- [ ] E6. `tests/unit/test_handoff_correlation.py::test_no_cross_site_link` (proves AC-H2-5).
- [ ] E7. Integration (Docker-gated known-gap): sweep against a real DB with real
      `agent_fetch_events` + `events` rows; migration up/down cycle. Record exact commands in
      the phase report; do not attempt to run in the sandbox.
- [ ] E8. FE build gate: `npm run build` (or `pnpm --filter web build` — confirm exact command
      at RESEARCH from `apps/web/package.json`) passes with the new TS types and components.

---

## Exit Gate

```bash
cd /Users/apple/getbeam && python -m pytest tests/unit/test_handoff_correlation.py -v
# Expected: all pass (link creation, confidence formula incl. Perplexity cap + no-low-writes,
# window/vendor exclusion, cross-site exclusion)

cd /Users/apple/getbeam && python -m pytest tests/unit/test_handoff_emailability_separation.py -v
# Expected: pass — THIS IS THE PROGRAM'S HARD GATE. Phase cannot be VERIFIED without this green.

cd /Users/apple/getbeam && python -m pytest tests/unit/ -q
# Expected: full regression green — baseline note: last EVL confirmation run
# (phase-01 EVL) reported 853 passed / 2 unrelated foreign-program failures; expect
# current-baseline-count + new Phase 2 tests, 0 new failures attributable to this phase

cd /Users/apple/getbeam/apps/web && npm run build
# Expected: build succeeds with new TS types + components
```

- All checklist items (A1-E8) checked
- AC-H2-3 regression green (both directions asserted in one test, plus tripwire)
- Dashboard badge renders confidence-qualified copy (manual/Agent-Probe review recorded)
- Docker-gated integration known-gap (E7) recorded, not silently dropped
- Phase report written to report destination above

---

## Blockers That Would Justify BLOCKED Status

- Phase 1 (H1) exit gate not yet passed — this phase structurally cannot start without
  `agent_fetch_events`
- `apps/api/jobs/scheduler.py` conflict with Phase 3's in-flight edits — resolve per umbrella's
  Pre-PVL Conflict Resolution (Phase 2 registers first; re-verify no overlap before EXECUTE)
- Any code path found during Step C that would touch `source_agent_visit_id` or
  `is_emailable_identity()` internals — this is a hard stop requiring plan revision, not a
  fix-in-place
- Migration head has diverged further than the VALIDATE-confirmed `a3e9f1c7d2b5` leaf —
  re-verify with `alembic heads` immediately before generating the migration file; do not
  silently pick a stale head (this chain is shared with an actively-developing parallel program)

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — research-agent: read Phase 1 report; read existing
      `test_agent_origin_exclusion.py` (Phase 7 pattern) in full; confirm exact visitor-detail
      endpoint/component to extend; test context loaded. **(Folded into this supplement pass —
      module names, model shape, confidence formula, scheduler/config wiring, and exact API/FE
      insertion points were confirmed directly against current code: `agent_fetch_event.py`,
      `ai_referral.py::classify_ai_source`, `agent_company_resolution.py`'s sweep pattern,
      `scheduler.py`'s job-registration pattern, `schemas/visitors.py::VisitorDetailOut`,
      `schemas/agents.py::AgentAnalyticsResponse`, `agent_aggregator.py`,
      `routers/visitors.py::get_visitor_detail`, `test_agent_origin_exclusion.py`, and the live
      migration chain leaf `c4e8f1a9d2b7`.)**
- [x] 2. INNOVATE — innovate-agent: sweep cadence, confidence model, and dashboard integration
      points are now LOCKED (see "LOCKED Design Decisions" section above) rather than left open;
      remaining INNOVATE work at execution time is re-verification only (exact vendor-label
      strings, exact FE line numbers, exact batch-size constant, exact migration head) — not
      re-deciding architecture. **Decision Summary:** chosen approach = dedicated
      `agent_handoff_correlation.py` sweep service mirroring the `agent_company_resolution.py`
      precedent, with a 2-tier write policy (high/medium only) inside a 3-tier schema, over the
      rejected alternatives of (a) inlining correlation into the ingest hot path (rejected — SPEC
      Constraint 4 forbids new synchronous ingest-path work) and (b) writing all 3 confidence
      tiers including `low` (rejected — precision-over-recall for a v1 differentiator badge;
      `low` stays in the schema for future loosening without a migration).
- [x] 3. PLAN-SUPPLEMENT — plan-agent: this supplement pass. Checklist rewritten with exact
      module names, model fields, confidence formula, config keys, and API/FE touch points
      encoded directly (was previously deferred to INNOVATE). Inner Loop Refresh Note below.
- [x] 4. PVL — vc-validate-agent: full V1-V7 complete 23-07-26; validate-contract written
      below. **Emailability separation (AC-H2-3) confirmed structurally sound by direct code
      read: `AgentHandoffLink` has no `source_agent_visit_id` field, `is_emailable_identity()`
      never queries `agent_handoff_links`, and no campaign/export call site joins it.** Migration
      head corrected to `a3e9f1c7d2b5` (was stale `c4e8f1a9d2b7`); vendor-mapping, aggregator
      DB/pure split, and TS interface names locked. Gate: CONDITIONAL (Docker-gated Hybrid
      residuals only, consistent with H1's precedent).
- [x] 5. EXECUTE — all checklist items (A1-E8) done 24-07-26; per-section test gates green (35
      new/affected unit gates; full unit suite 899 passed / 0 failures; FE build green). 2
      within-blast-radius deviations documented in phase report `## Plan Deviations`. 1 Docker-gated
      Hybrid gap (live sweep + migration cycle) recorded, not silently dropped.
- [x] 6. EVL — independent re-run GREEN: 21/21 target unit gates, 899/0 full regression, FE build,
      `agent_handoff_links` registration + indexes confirmed, single migration head `e2a4c7f81b93`,
      AC-H2-3 confirmed via zero-diff structural check + zero-reference tripwire + zero outreach
      joins, dashboard badge copy confirmed probabilistic. Docker-gated live-sweep/migration-cycle
      known-gap unchanged, tracked in backlog note. No fix cycles needed.
- [x] 7. UPDATE PROCESS — phase report augmented (EVL results + capability statement + known-gaps),
      umbrella `## Current Execution State` rewritten to Phase 3, blast-radius registry EVL note
      added, validators run. Commit deferred to vc-git-manager (next step, not this session).

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate
Contract` reads "(placeholder — vc-validate-agent writes this section before EXECUTE)",
orchestrator must spawn vc-validate-agent first.

---

## Inner Loop Refresh Note

**Date:** 23-07-26
**Trigger:** Autonomous /goal PLAN-SUPPLEMENT pass (Step 3 of the 7-step inner loop), folding
RESEARCH (Step 1) and INNOVATE (Step 2) directly into this same pass since no prior contract
existed to invalidate and the design surface was small enough to lock in one session.

**Sections changed:**
- Added `## LOCKED Design Decisions` (new section) — 12 numbered decisions covering module
  naming, model shape, confidence formula, tie-break rules, vendor mapping, sweep query shape,
  fail-open pattern, scheduler wiring, and API/FE surfacing.
- `## Blast Radius` — added exact new files (`config.py` setting, schema fields, aggregator
  change, FE type/page touch points) and the moving-migration-head caveat with the
  provisionally-confirmed leaf (`c4e8f1a9d2b7`).
- `## Implementation Checklist` — every step (A1-E8) rewritten from open/INNOVATE-deferred
  language to exact, executable instructions referencing real function/field/file names.
- `## Exit Gate` — added full-regression command with a real baseline count reference (from
  Phase 1's EVL run) and an explicit FE build gate.
- `## Blockers That Would Justify BLOCKED Status` — added the migration-head-divergence blocker.
- `## Phase Loop Progress` — Steps 1-3 ticked with inline notes; Step 4 (PVL) left unchecked.

**Why PVL must re-run (or run for the first time here):** no validate-contract exists yet for
this plan — this is Step 4's first pass, not a re-validation. Orchestrator should proceed
directly to spawning vc-validate-agent.

---

## Touchpoints

- `apps/api/models/agent_handoff_link.py` (new)
- `apps/api/migrations/versions/` (new migration file; re-verify head at EXECUTE)
- `apps/api/services/agent_handoff_correlation.py` (new — locked name)
- `apps/api/config.py` (1 new setting)
- `apps/api/jobs/scheduler.py` (one new job registration, additive)
- `apps/api/schemas/visitors.py` (5 new nullable fields on `VisitorDetailOut`)
- `apps/api/routers/visitors.py` (additive data-merge in `get_visitor_detail`)
- `apps/api/schemas/agents.py` (1 new field on `AgentAnalyticsResponse`)
- `apps/api/services/agent_aggregator.py` (1 new aggregation)
- `apps/web/src/lib/api-types.ts` (TS type extensions)
- `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` (badge component)
- `apps/web/src/app/dashboard/visitors/page.tsx` (list-row pill)
- `apps/web/src/app/dashboard/agents/page.tsx` (analytics card surfacing)
- `tests/unit/test_handoff_correlation.py`, `tests/unit/test_handoff_emailability_separation.py` (new)

---

## Public Contracts

- `is_emailable_identity()`'s existing signature and `source_agent_visit_id` mechanism are
  unchanged — this phase never modifies `identity_classification.py`.
- Existing visitor-detail API response shape is extended additively (5 new optional fields),
  never breaking existing consumers.
- `AgentAnalyticsResponse` is extended additively (1 new field); `aggregate_agent_analytics`'s
  pure, no-DB contract is preserved (INNOVATE/RESEARCH at EXECUTE confirms exact param shape for
  the 4th aggregation without introducing a DB call into this function).

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_link_created_within_window` | Fully-Automated | AC-H2-1 |
| `test_no_link_outside_window` + `test_no_link_vendor_mismatch` | Fully-Automated | AC-H2-2 |
| `test_confidence_high_exact_page_fast` + `test_confidence_medium_slow_delta` + `test_confidence_medium_page_mismatch` + `test_perplexity_capped_medium` + `test_low_confidence_discarded_not_written` | Fully-Automated | AC-H2-1/AC-H2-2 (confidence formula + no-low-writes policy) |
| `test_handoff_emailability_separation` (both directions + tripwire, one test) | Fully-Automated | AC-H2-3 (program's hard gate) |
| API-contract assertion — `confidence`/`handoff_links_count` always present | Fully-Automated | AC-H2-4 (API half) |
| Manual UI copy review — badge never asserts certainty | Agent-Probe | AC-H2-4 (UI wording half) |
| `test_no_cross_site_link` | Fully-Automated | AC-H2-5 |
| Sweep against real DB, migration up/down cycle | Hybrid (Docker-gated known-gap) | AC-H2-1 (live-integration confidence) |
| `npm run build` | Fully-Automated | AC-H2-4 (FE build correctness) |

```bash
cd /Users/apple/getbeam && python -m pytest tests/unit/test_handoff_correlation.py tests/unit/test_handoff_emailability_separation.py -v
# Expected: all pass

cd /Users/apple/getbeam/apps/web && npm run build
# Expected: build succeeds
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/handoff_23-07-26/phase-02-handoff-correlation_PLAN_23-07-26.md`
- Last completed step: Step 4 (PVL) — validate-contract written, Gate: CONDITIONAL
- Validate-contract status: written 23-07-26 (see `## Validate Contract` below)
- Supporting context loaded this pass: Phase 1 report/model (`agent_fetch_event.py`),
  `ai_referral.py`, `agent_company_resolution.py`, `scheduler.py`, `config.py`,
  `schemas/visitors.py`, `schemas/agents.py`, `agent_aggregator.py`, `routers/visitors.py`,
  `test_agent_origin_exclusion.py`, `identity_classification.py`, `event.py`, `visitor.py`,
  `main.py` (model registration block), `api-types.ts`, visitor-detail/list/agents FE pages,
  live migration chain (`alembic heads` — confirmed single head `a3e9f1c7d2b5`),
  `tests/unit/test_agent_aggregator.py`, `handoff-program-docker-verification-gaps_NOTE_23-07-26.md`
- Next step: Spawn vc-execute-agent for Step 5 (EXECUTE) with this plan + the validate-contract
  below. Execute in the order: Step A (model+migration) → Step B (sweep service+config+scheduler)
  → Step C (emailability confirmation re-checks) → Step D (API/schemas/aggregator/FE) → Step E
  (tests).

---

## Test Infra Improvement Notes

(none identified yet)

---

## Validate Contract

Status: CONDITIONAL
Date: 23-07-26
date: 2026-07-23
generated-by: inner-pvl: phase-h2

Parallel strategy: sequential
Rationale: single phase plan, single validator pass, no independent sub-investigations needed —
2/7 signals present (S2 schema surface, S6 high-risk-adjacent emailability class); below the
MEDIUM parallel-subagent threshold (2-3). Layer 1/Layer 2 fan-out for this VALIDATE pass itself
was run sequentially in one session (small, well-scoped blast radius, all context loaded upfront).

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-H2-1 | handoff link created within window (synthetic fixture, deterministic clock) | Fully-Automated | `tests/unit/test_handoff_correlation.py::test_link_created_within_window` | A |
| AC-H2-2 | no link outside window / vendor mismatch | Fully-Automated | `test_no_link_outside_window` + `test_no_link_vendor_mismatch` | A |
| AC-H2-1/2 (confidence formula) | high/medium tiers, Perplexity cap, no-low-writes policy | Fully-Automated | `test_confidence_high_exact_page_fast` + `test_confidence_medium_slow_delta` + `test_confidence_medium_page_mismatch` + `test_perplexity_capped_medium` + `test_low_confidence_discarded_not_written` | A |
| AC-H2-3 (program's hard gate) | both-directions emailability separation + literal-field tripwire | Fully-Automated | `tests/unit/test_handoff_emailability_separation.py` | A |
| AC-H2-4 (API half) | `confidence`/`handoff_links_count` always present on API representation | Fully-Automated | `tests/unit/test_agent_aggregator.py` (extend — this is the REAL Docker-free file for this assertion; SPEC's citation of `tests/unit/test_agents_api.py` is imprecise — that file doesn't exist as a unit test, only `tests/integration/test_agents_api.py` exists and is Docker-gated) | A |
| AC-H2-4 (UI half) | badge/InfoRow copy never asserts certainty | Agent-Probe | manual review of `visitors/[visitorId]/page.tsx` + `visitors/page.tsx` rendered copy against AC-H2-4 wording rule | A |
| AC-H2-5 | no cross-site fetch/click linking | Fully-Automated | `test_no_cross_site_link` | A |
| AC-H2-4 (FE build) | new TS types + components compile | Fully-Automated | `cd apps/web && npm run build` | A |
| AC-H2-1 (live-integration confidence) | sweep against real Postgres with real `agent_fetch_events`+`events` rows; migration up/down cycle | Hybrid | Docker-gated — `alembic upgrade head && downgrade -1 && upgrade head`, then `pytest tests/integration -k handoff_correlation -m integration -q` (test file name TBD at EXECUTE) | D |

gap-resolution legend: A — proven now. D — backlog test-building stub (named residual; Docker
daemon unresponsive in this sandbox, `docker ps` produced no output; matches H1's identical
precedent — see `handoff-program-docker-verification-gaps_NOTE_23-07-26.md`, H2 row appended).

Legacy line form:
- Correlation logic + confidence formula + write-policy: Fully-automated: `pytest tests/unit/test_handoff_correlation.py -v`
- Emailability separation (hard gate): Fully-automated: `pytest tests/unit/test_handoff_emailability_separation.py -v`
- API contract presence: Fully-automated: extend `tests/unit/test_agent_aggregator.py`
- UI copy wording: agent-probe: manual review, no unqualified certainty language
- FE build: Fully-automated: `cd apps/web && npm run build`
- Live DB round-trip + migration cycle: hybrid: known-gap, Docker daemon unavailable this session

Structural Plan Validators (V1 Step 3b, mandatory):
- `node .claude/skills/vc-generate-phase-program/scripts/validate-phase-stub.mjs <this file>` —
  **0 failures, 0 warnings** (correct validator for this file's shape — a phase-program per-phase
  stub, matching H1's identical precedent).
- `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs <this file>` — 6 FAILs
  / 4 warnings reported (missing Date/Status/Complexity metadata, overview/context section, Phase
  Completion Rules, Acceptance Criteria as literal headings). **Expected shape mismatches, not
  real defects** — same precedent as H1 (see H1 plan's own `## Structural Plan Validators` note):
  this validator checks the standalone SIMPLE/COMPLEX plan template, which phase-stub files
  deliberately don't use (they use `## Purpose`/`## LOCKED Design Decisions`/`## Phase Loop
  Progress` instead, per `phase-programs.md`'s phase-stub template). Reported per protocol as
  mandatory, not treated as blocking.

Dimension findings:
- Infra fit: PASS — no new container/runtime/proxy surface; new periodic job follows the exact
  existing `scheduler.py` `add_job("interval", minutes=..., id=..., replace_existing=True)`
  pattern; correlation query fits existing indexes (`agent_fetch_events`'s
  `idx_agent_fetch_events_site_path_tier_created` and `events`'s `ix_events_site_created` both
  cover the sweep's `site_id`+time-range access pattern — no new index required).
- Test coverage: CONCERN found, fixed in plan — SPEC's AC-H2-4 API-half citation
  (`tests/unit/test_agents_api.py`) points at a file that doesn't exist as a unit test (only a
  Docker-gated integration file with that name exists); corrected to `tests/unit/test_agent_aggregator.py`
  (confirmed real, Fully-Automated, Docker-free — see Test Gates table). E5's "confirm exact file
  at RESEARCH" hedge in the plan was correct to hedge; now resolved.
- Breaking changes: PASS — all API/schema changes are additive/nullable (5 new `None`-default
  fields on `VisitorDetailOut`, 1 new field on `AgentAnalyticsResponse`); TS interfaces confirmed
  by name (`VisitorDetail` ~line 205, `AgentAnalytics` ~line 345 in `api-types.ts`) so execute-agent
  extends the right types on the first pass; `aggregate_agent_analytics`'s pure/no-DB contract is
  preserved by the locked sibling-fetch-function design (Decision 11, corrected in plan text).
- Security surface: PASS — AC-H2-3 (program's highest-priority gate) verified structurally sound
  by direct code read, not assumption: `AgentHandoffLink`'s locked field list (Decision 2) has NO
  `source_agent_visit_id` column — structurally impossible to write it. `is_emailable_identity()`
  (`identity_classification.py`) takes only `provider`/`source_agent_visit_id` args and never
  queries `agent_handoff_links` — a handoff link's existence is invisible to it. The 3 real
  outreach call sites guarded by `test_agent_origin_exclusion.py`'s `_GUARDED_FILES`
  (`campaign_sender.py`, `routers/campaigns.py`, `csv_exporter.py`) never reference
  `agent_handoff_links` or `AgentFetchEvent` — confirmed by the existing test file's structure,
  which this phase's E4 test extends rather than replaces. `AgentHandoffLink.visitor_id` links to
  the ordinary `Visitor.visitor_id` namespace, completely disjoint from `IdentifiedVisitor`'s
  agent-origin marker system — two structurally separate tables, exactly per SPEC Constraint 1.
- Section A (Data model + migration): CONCERN found, FIXED IN PLAN — migration `down_revision`
  was stale (`c4e8f1a9d2b7`, H1's own migration); re-verified via `alembic heads` this VALIDATE
  pass, confirmed a SINGLE live head `a3e9f1c7d2b5` (two foreign visitors-identity-program
  migrations chained on since H1 finished: `f8a2c1d9b3e7`, `a3e9f1c7d2b5`). Not a fork/FAIL — a
  single linear chain, just longer than the plan's provisional value. Plan text corrected in
  Blast Radius, LOCKED Decision, and Blockers section. `main.py`'s model-import block confirmed
  (lines 32-33 register `AgentVisit`/`AgentFetchEvent`) as the exact insertion point for
  `AgentHandoffLink` (A3).
- Section B (Correlation sweep): CONCERN found, FIXED IN PLAN — two open sub-decisions the plan
  had deferred to RESEARCH are now locked: (1) vendor-family mapping is exactly
  `{"openai": "chatgpt", "anthropic": "claude", "perplexity": "perplexity"}` (verified against
  `agent_classifier.py::_VENDOR_TOKENS` and `ai_referral.py::AI_REFERRER_DOMAINS`; `bytespider` is
  moot — never `tier=on-demand`); (2) batch size follows `agent_company_resolution.py`'s
  `limit: int = 20` parameter-default convention (not `agent_verification.py`'s module-constant
  style). Also added an execute-agent instruction for the `page_path is None` edge case
  (falls to `medium`, never `high`).
- Section C (Emailability separation, hard gate): PASS — see Security surface finding above. E4's
  planned test structure (both directions + literal-field tripwire, mirroring
  `test_agent_origin_exclusion.py`'s C5 pattern) is the right shape; execute-agent must construct
  or exercise a REAL `Visitor`+`AgentHandoffLink` pair (not just a mock) for at least one
  assertion, mirroring `test_agent_origin_exclusion.py`'s `test_ac10_real_sweep_created_row_is_non_emailable`
  non-vacuity precedent — recorded as execute-agent instruction E-C4.
- Section D (API + dashboard surfacing): CONCERN found, FIXED IN PLAN — the aggregator's
  DB-fetch/pure-aggregation split was an explicitly open design question in the plan; resolved by
  mirroring the existing `fetch_agent_visit_rows` (DB) / `aggregate_agent_analytics` (pure) split
  exactly (new sibling `fetch_handoff_links_count(db, site_id) -> int`, extend
  `aggregate_agent_analytics(rows, handoff_links_count, top_n=10)`). FE line-number estimates
  (~448, ~797, ~650 for badge/InfoRow/pill; `by_vendor`/`top_pages`/`by_verification` rendering at
  ~70-139 in `agents/page.tsx`) confirmed accurate against live source — no drift found, execute
  as planned.
- Section E (Tests): PASS — all planned unit test files are new and correctly scoped;
  `tests/unit/test_agent_aggregator.py` confirmed as the real existing file to extend for the
  API-contract assertion (corrects the SPEC's imprecise citation, see Test coverage finding); FE
  build command confirmed (`npm run build` in `apps/web/package.json`).

Execute-agent instructions:
- E-A1: Before writing the migration file, re-run `cd apps/api && .venv/bin/python -m alembic heads`
  one more time — if it still returns single head `a3e9f1c7d2b5`, use it as `down_revision`. If a
  new head has appeared, use that instead and note the change in the phase report; do NOT silently
  pick a value without re-checking.
- E-B1: Implement the vendor-family map as a module-level `dict[str, str]` constant in
  `agent_handoff_correlation.py` with exactly the 3 locked entries; use `.get(vendor)` and skip
  gracefully (no candidate match) on a `None` result.
- E-C4: The AC-H2-3 emailability test (E4) must include at least one assertion against a REAL
  constructed `Visitor`/`AgentHandoffLink` pair (not purely mocks), mirroring
  `test_agent_origin_exclusion.py::test_ac10_real_sweep_created_row_is_non_emailable`'s
  non-vacuity discipline — this proves the test would actually fail red if the separation were
  broken, not just that a mock was configured correctly.
- E-D3: Follow the locked `fetch_handoff_links_count` / `aggregate_agent_analytics` signature
  exactly per corrected LOCKED Decision 11 and checklist D3 — do not reintroduce a DB call inside
  `aggregate_agent_analytics` itself.
- E-E5: Extend `tests/unit/test_agent_aggregator.py` (NOT `tests/unit/test_agents_api.py`, which
  does not exist as a unit test) for the AC-H2-4 API-contract assertion.

High-risk pack: yes — schema (new table + migration) and emailability-adjacent (AC-H2-3 hard
gate) both qualify as high-risk classes per `orchestration.md` §High-Risk Execution Handoff. Per
`vc-risk-evidence-pack`, the manual-first evidence pack (`risk-gate.json`, `context-snippets.json`,
`verification.json`, `review-decision.json`) should be produced during/after EXECUTE, colocated at
`process/features/evallayer/active/handoff_23-07-26/harness/` (matching the existing
`harness/context-snippets-phase-h1.json` / `harness/verification-phase-h1.json` pattern already in
this task folder). The AC-H2-3 separation test itself IS the adversarial-validation control this
phase's evidence pack should cite — no `adversarial-validation.json` scenario beyond "can a
handoff link ever make an agent-fetch record emailable, or a linked human non-emailable" is needed
since that scenario is exhaustively covered by the Fully-Automated regression.

Backlog artifacts:
- `process/features/evallayer/backlog/handoff-program-docker-verification-gaps_NOTE_23-07-26.md`
  — H2 rows appended this VALIDATE pass (migration cycle + live sweep integration).

Known gaps:
- Live DB round-trip (real Postgres, real `agent_fetch_events`+`events` rows) and the Alembic
  migration up/down cycle — Docker daemon unresponsive in this sandbox (`docker ps` produced no
  output). Named residual, Hybrid tier, gap-resolution D — tracked in the backlog note above,
  consistent with H1's identical treatment (H1 shipped Gate: CONDITIONAL with the same class of
  residual, later EVL-confirmed green on all Fully-Automated gates).

What this coverage does NOT prove:
- The Fully-Automated correlation/confidence/emailability/cross-site tests prove correctness
  against synthetic in-memory fixtures with a deterministic clock — they do NOT prove the sweep
  performs acceptably at real production data volumes, nor that the `ix_events_site_created` /
  `idx_agent_fetch_events_site_path_tier_created` indexes are sufficient under real query planner
  behavior with real table statistics (only inspected structurally, never EXPLAIN-ANALYZEd).
- The Agent-Probe UI copy review proves the copy as written at review time is qualifying language;
  it does not prove no future edit reintroduces an unqualified-certainty string (only the C5-style
  literal-tripwire pattern used for AC-H2-3 would catch that mechanically, and no such tripwire is
  planned for AC-H2-4's UI wording).
- The FE build gate proves TypeScript compiles; it does not prove the badge/pill/card render
  correctly in a live browser (no Playwright e2e planned for this phase; Playwright coverage for
  the sibling `/agents` dashboard tab is itself still Docker/dev-server-gated per the existing
  EvalLayer backlog note).
- The Docker-gated Hybrid gate (live sweep + migration cycle), when eventually run, is the only
  gate that would catch a real Postgres-specific behavior difference (e.g. an actual index scan
  vs. seq scan decision, or a real UniqueConstraint collision under concurrent sweep runs) — until
  it runs, that residual risk class stays open exactly as it did for H1.

Gate: CONDITIONAL (0 FAILs; concerns found were fixed in plan text this pass; 1 Docker-gated
Hybrid known-gap remains, consistent with the umbrella charter's explicit allowance for
Docker-gated residuals at PVL)
Accepted by: session (autonomous, /goal execution) — accepted concern: "Live DB round-trip +
migration up/down cycle unverified in this sandbox (Docker daemon unresponsive)" — matches the
umbrella's Autonomous Execution Rules ("CONDITIONAL net gate: proceed autonomously, fixes applied
in-flight, gaps on record") and the identical precedent already accepted for Phase 1 (H1).
