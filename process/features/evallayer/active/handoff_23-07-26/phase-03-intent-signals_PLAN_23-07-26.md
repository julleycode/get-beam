---
name: plan:handoff-phase-03-intent-signals
description: "Handoff Detection — Phase 03: live on-demand alerts, spike detection, company correlation (H3)"
date: 24-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-03
---

# Phase 03 — Intent Signals (H3)

**Program:** handoff
**Umbrella plan:** process/features/evallayer/active/handoff_23-07-26/handoff-umbrella_PLAN_23-07-26.md
**SPEC:** process/features/evallayer/active/handoff_23-07-26/handoff_SPEC_23-07-26.md (AC-H3-1 through AC-H3-4)
**Phase status:** ✅ VALIDATED (Gate: CONDITIONAL — 0 FAILs, concerns fixed in plan text this pass; see Validate Contract)
**Report destination:** process/features/evallayer/active/handoff_23-07-26/phase-03-intent-signals_REPORT_23-07-26.md (flat in the program task folder)

---

## Purpose

Turn H1's on-demand fetch stream into live founder-facing intent signals: near-real-time alerts
when someone is actively asking an AI agent about a commercial page, rolling-window spike
detection, and read-only company-correlation surfaced on-read in the agent analytics response.
None of these signals may ever independently trigger outreach or make a person-level claim — they
are context, not action, and this phase adds **no new storage and no migration**.

---

## Entry Gate

- Phase 1 (H1) exit gate passed: `agent_fetch_events` table live, tiering correct
- Parallel-safe with Phase 2 per umbrella's Pre-PVL Conflict Resolution — this phase's
  `apps/api/jobs/scheduler.py` job registration is additive and registers AFTER Phase 2's
  `handoff_correlation_sweep` job (confirmed live at `apps/api/jobs/scheduler.py:233-236`,
  registering `handoff_correlation_sweep_interval_minutes` — re-verify this line range at
  EXECUTE time in case Phase 2 has since changed it)

---

## Locked Design (confirmed via code re-read — no open INNOVATE questions remain)

### New module `apps/api/services/agent_intent_signals.py`

- `COMMERCIAL_PAGE_PREFIXES = frozenset({"/pricing", "/demo", "/signup", "/compare", "/vs", "/plans", "/trial"})`
  — module-level constant, no per-site config this phase (backlog note below).
- `is_commercial_page(path: str) -> bool` — **pure**. Normalize: `path.rstrip("/").lower()`
  (empty string after rstrip => not commercial). Match rule: `normalized == prefix or
  normalized.startswith(prefix + "/")` for any `prefix` in `COMMERCIAL_PAGE_PREFIXES`. This
  correctly matches `/pricing`, `/pricing/enterprise`, but NOT `/pricing-blog` (no `/` boundary).
- `detect_spike(current_24h: int, trailing_7d_daily_avg: float) -> bool` — **pure**.
  `return current_24h >= 3 and current_24h >= 2.0 * trailing_7d_daily_avg`. Floor-then-multiplier:
  a zero/near-zero baseline still requires the `>= 3` floor before qualifying, so a single
  fetch against a zero baseline is NOT a spike.
- `async def run_intent_signal_sweep(db: AsyncSession) -> None` — the periodic sweep entrypoint
  called by the scheduler job. Iterates distinct `(site_id, page_path)` pairs from
  `agent_fetch_events` where `tier == "on-demand"` and `page_path` is commercial (per
  `is_commercial_page`), computing:
  - `current_24h` — count of on-demand fetches to that (site, page) in the last 24h
  - `trailing_7d_daily_avg` — average daily on-demand fetch count to that (site, page) over the
    preceding 7 days (excluding the current 24h window)
  Both counts query `AgentFetchEvent` filtered by `site_id`, `page_path`, `tier == "on-demand"`,
  and `created_at` window — the existing composite index
  `idx_agent_fetch_events_site_path_tier_created (site_id, page_path, tier, created_at)` covers
  both queries with no new index needed.
  For each qualifying pair: call `maybe_send_intent_alert(...)`; separately, if
  `detect_spike(current_24h, trailing_7d_daily_avg)` is True, also call
  `maybe_send_intent_alert(..., is_spike=True)` (spike uses the same delivery path with a
  different copy template — see below). **Fail-open**: wrap each (site, page) iteration's body
  in try/except so one site's failure never blocks the sweep for other sites; log and continue.

### `apps/api/services/hot_alert.py` — new sibling function, existing function untouched

- `async def maybe_send_intent_alert(db: AsyncSession, site: Site, page_path: str, hit_count: int, window_minutes: int, is_spike: bool = False) -> bool`
  — reuses the existing `Site`/`EmailSender`/`get_redis()` pattern from `maybe_send_hot_alert`
  (same file, lines ~46-100). Gate: `site.hot_alert_enabled` must be True (reuse the existing
  toggle — no new per-site flag this phase).
  - **Dedup key:** `f"intent_alert:{site.site_id}:{page_path}"`, Redis `SET NX EX` with
    `TTL = 86400` (24h — distinct from hot_alert's 7-day TTL, since intent alerts are meant to
    recur daily rather than dedupe for a week). Same fail-open-on-Redis-error pattern as
    `maybe_send_hot_alert` (log warning, send anyway if Redis unreachable).
  - **Copy template (verbatim, LOCKED):**
    `"{vendor} fetched {page_path} {hit_count}× in the last {window_minutes} minutes on {site.name}."`
    — `vendor` is derived from the qualifying fetch events' vendor label (if a single vendor
    dominates the window, use that vendor name; if mixed, use `"AI agents"` as the collective
    label). **Copy is SITE-level only** — never includes a person name, company name, or IP
    address. The spike variant appends: `" This is a {multiplier}x spike over your usual rate."`
  - **HTML-escaping (PVL correction):** `page_path` is attacker-influenceable (it is the request
    path from an inbound HTTP hit) and `vendor` is a classifier-derived label — before
    interpolating either into the HTML email body, run both through `html.escape()` exactly like
    `maybe_send_hot_alert` already does for `name`/`site.name` (same file, `from html import
    escape` is already imported). Never interpolate raw `page_path`/`vendor` into `body_html`.
  - Delivery mechanism, owner lookup, and email send call are identical to
    `maybe_send_hot_alert` — reuse `EmailSender`, no new notification channel.
  - **Delivery latency tier (confirmed):** next scheduled sweep tick (not same-request-cycle) —
    matches AC-H3-1's "near-real-time" bar via the 10-minute sweep interval below; avoids adding
    alert-trigger logic to the hot request path of fetch-event ingestion.
- `site_id` scoping is inherent — every call is already site-scoped via the `site` parameter;
  no cross-tenant query path exists in this design.

### Scheduler + config

- `apps/api/config.py`: add `intent_signal_sweep_interval_minutes: int = 10` (new setting,
  same pattern/placement as `handoff_correlation_sweep_interval_minutes` at line 359).
- `apps/api/jobs/scheduler.py`: add ONE new `scheduler.add_job(...)` call for
  `run_intent_signal_sweep`, using `"interval"` trigger and
  `minutes=settings.intent_signal_sweep_interval_minutes`, inserted immediately AFTER the
  existing H2 `handoff_correlation_sweep` job registration (current line ~233-236) and BEFORE
  the changelog-sync block (current line ~241). Purely additive — no existing job registration
  is modified or reordered.

### Analytics (on-read correlation — NO new storage, NO migration this phase)

- Add a new sibling DB-fetch function `fetch_recent_ai_researched_companies(db, site_id) ->
  list[dict]` to `apps/api/services/agent_aggregator.py` (**PVL correction** — mirrors the
  existing `fetch_agent_visit_rows`/`fetch_handoff_links_count` DB-fetch split; do NOT put a query
  inside `aggregate_agent_analytics` itself — that function's docstring and existing tests
  document it as pure/no-DB/unit-testable-without-a-DB, and a query inside it would break that
  contract). The router calls this new function and passes its result into
  `aggregate_agent_analytics` as an additional parameter that the pure function only echoes into
  the response dict — the same pattern `handoff_links_count` already uses.
  - `recent_ai_researched_companies: list[dict]` — for the requesting `site_id`, find `Company`
    rows whose `first_seen` falls within 48h AFTER an `AgentFetchEvent` row at the same site
    where: `tier == "on-demand"`, `is_commercial_page(page_path)` is True. **No direct IP join
    exists between `Company` and `AgentFetchEvent`** (Company has no `ip_address` column —
    confirmed via model read). **Primary candidate join (PVL finding):** the durable
    `company_graph` table (`CompanyGraphNode`, gated by `settings.company_graph_enabled` from the
    visitors-identity "owned-data-layer" program) stores `ip` → `domain`. Try this join first:
    `AgentFetchEvent.ip_address == CompanyGraphNode.ip AND CompanyGraphNode.domain ==
    Company.domain AND Company.site_id == site_id`. Re-confirm `CompanyGraphNode`'s exact column
    names during EXECUTE by re-reading `apps/api/models/company_graph.py` (`ip`, `domain`,
    `confidence`, `last_verified` confirmed present at PVL). A fetch event with no matching
    `CompanyGraphNode` row is simply excluded from the result (not a failure). If
    `company_graph_enabled` is False deployment-wide, this sub-feature is a **known-gap for this
    phase** — degrade `recent_ai_researched_companies` to an empty list and document the gap
    rather than inventing a new stored join.
  - Response shape per entry: `{company_name: str, domain: str, matched_page: str, researched_at: datetime}`
  - Cap: top 20, ordered by `researched_at` descending.
- `apps/api/schemas/agents.py`: add `recent_ai_researched_companies: list[RecentAiResearchEntry]`
  field to `AgentAnalyticsResponse` (new `RecentAiResearchEntry` BaseModel, sibling to
  `TopPageEntry`), matching the field-for-field snake_case wire-format precedent H2 already
  established for `handoff_links_count`.
- `apps/web/src/lib/api-types.ts`: extend `AgentAnalytics` interface with
  `recent_ai_researched_companies: RecentAiResearchEntry[]` (new interface, mirrors
  `TopPageEntry` pattern at line 351-354).
- `apps/web/src/app/dashboard/agents/page.tsx`: add a card/section "Appeared after AI research"
  (metadata label, matches H2's non-outreach-triggering framing) listing the correlated
  companies — read-only display, no action buttons, no link into campaign/outreach UI.

---

## Blast Radius

- `apps/api/services/agent_intent_signals.py` (new)
- `apps/api/services/hot_alert.py` (add `maybe_send_intent_alert`, existing `maybe_send_hot_alert` untouched)
- `apps/api/services/agent_aggregator.py` (extend `aggregate_agent_analytics` with correlation query)
- `apps/api/schemas/agents.py` (add `RecentAiResearchEntry`, extend `AgentAnalyticsResponse`)
- `apps/api/config.py` (add `intent_signal_sweep_interval_minutes`)
- `apps/api/jobs/scheduler.py` (one new additive job registration, after H2's)
- `apps/web/src/lib/api-types.ts` (extend `AgentAnalytics`, add `RecentAiResearchEntry`)
- `apps/web/src/app/dashboard/agents/page.tsx` (new card: "Appeared after AI research")
- `tests/unit/test_intent_alerts.py` (new)
- **No new migration, no new table, no schema change** — on-read design only.

---

## Implementation Checklist

### Step A — Commercial-page classification

- [ ] A1. Add `COMMERCIAL_PAGE_PREFIXES` + `is_commercial_page(path)` to new
      `apps/api/services/agent_intent_signals.py` per Locked Design above. Pure function, no I/O.

### Step B — Live on-demand alert

- [ ] B1. Add `maybe_send_intent_alert(...)` to `apps/api/services/hot_alert.py` per Locked
      Design (dedup key, TTL, LOCKED copy template, `hot_alert_enabled` gate). HTML-escape
      `page_path` and `vendor` via `html.escape()` before interpolating into `body_html` (PVL
      correction — mirrors `maybe_send_hot_alert`'s existing `escape(name)`/`escape(site.name)`
      calls; `page_path` is attacker-influenceable request-path data).
- [ ] B2. Add `run_intent_signal_sweep(db)` to `agent_intent_signals.py`: query qualifying
      (site, page) pairs, compute `current_24h`, call `maybe_send_intent_alert` for each
      qualifying pair. Fail-open per (site, page) iteration.
- [ ] B3. Confirm `site_id` scoping is inherent to every query added (no cross-tenant read path).

### Step C — Spike detection

- [ ] C1. Add `detect_spike(current_24h, trailing_7d_daily_avg)` to `agent_intent_signals.py`
      per Locked Design (floor `>= 3` AND `>= 2.0x` trailing avg).
- [ ] C2. Wire spike detection into `run_intent_signal_sweep`: compute `trailing_7d_daily_avg`
      per (site, page) pair, call `maybe_send_intent_alert(..., is_spike=True)` when
      `detect_spike` is True.
- [ ] C3. Add `intent_signal_sweep_interval_minutes: int = 10` to `apps/api/config.py`.
- [ ] C4. Re-read live `apps/api/jobs/scheduler.py` to confirm current line range of H2's
      `handoff_correlation_sweep` registration (baseline: lines 233-236), then register
      `run_intent_signal_sweep` as a new `"interval"` job immediately after it — additive only.

### Step D — Company-correlation signal (on-read, no migration)

- [ ] D1. Re-read `apps/api/models/company_graph.py` to re-confirm `CompanyGraphNode`'s exact
      column names, and check `settings.company_graph_enabled`. Implement
      `fetch_recent_ai_researched_companies(db, site_id)` as a new sibling DB-fetch function in
      `agent_aggregator.py` (per PVL-corrected Locked Design) using the `company_graph` join as
      the primary path (48h window, `is_commercial_page` filter, top-20 desc by
      `researched_at`); pass its result into `aggregate_agent_analytics` as an additional
      parameter that is only echoed, never queried inside the pure function. If
      `company_graph_enabled` is False deployment-wide, degrade to an empty list and record the
      finding as a known-gap in the phase report (do NOT add a new stored join column — that
      would require a migration, out of scope this phase).
- [ ] D2. Add `RecentAiResearchEntry` schema + extend `AgentAnalyticsResponse` in
      `apps/api/schemas/agents.py`.
- [ ] D3. Confirm this signal NEVER independently creates, approves, or auto-sends any campaign
      — grep for any new write path from this signal into campaign/outreach tables and confirm
      none exists; it is read-only, computed on-read, never persisted.
- [ ] D4. Confirm the signal is attached at company/site level only — never construct or surface
      a person-level claim from on-demand fetch data (no visitor/person identifier is ever
      included in `RecentAiResearchEntry`).
- [ ] D5. Enforce `site_id` scoping on the company-correlation query.
- [ ] D6. Extend `apps/web/src/lib/api-types.ts` (`AgentAnalytics` interface +
      `RecentAiResearchEntry`) and `apps/web/src/app/dashboard/agents/page.tsx` ("Appeared
      after AI research" card, metadata label only, no action affordances).

### Step E — Tests

- [ ] E1. `tests/unit/test_intent_alerts.py::test_is_commercial_page` — exact match, sub-path
      match, false-positive guard (`/pricing-blog` must NOT match `/pricing`) (proves AC-H3-1
      pre-condition).
- [ ] E2. `tests/unit/test_intent_alerts.py::test_commercial_page_triggers_alert` (proves
      AC-H3-1, Fully-Automated for alert creation/dedup/copy gating; Agent-Probe not needed —
      delivery reuses existing `EmailSender`, no new UX).
- [ ] E3. `tests/unit/test_intent_alerts.py::test_detect_spike` — floor case (2 hits, 0 baseline
      => no spike), multiplier case (3 hits, 1.0 avg => spike), zero-baseline case (3 hits, 0.0
      avg => spike, since floor satisfied) (proves AC-H3-2).
- [ ] E4. `tests/unit/test_intent_alerts.py::test_intent_alert_copy_is_site_level_only` —
      asserts rendered copy contains no email address, no person name, no visitor/company
      identifier token (proves AC-H3-4 for alert copy).
- [ ] E5. `tests/unit/test_intent_alerts.py::test_company_correlation_is_metadata_only` — mirrors
      H2's `test_handoff_emailability_separation.py` pattern: asserts no write path from this
      signal into campaign/segment/outreach tables (grep-style or mock-assertion test), and that
      `RecentAiResearchEntry` is never persisted to a table (proves AC-H3-3).
- [ ] E6. `tests/unit/test_intent_alerts.py::test_correlation_is_site_scoped` — proves AC-H3-4
      site-scoping for the correlation query.

---

## Exit Gate

```bash
cd /Users/apple/getbeam && python -m pytest tests/unit/test_intent_alerts.py -v
# Expected: all pass (is_commercial_page, alert trigger+dedup+copy, spike detection,
# correlation metadata-only, site-scoped, no-person-level-claim)
```

```bash
cd /Users/apple/getbeam/apps/web && npm run build
# Expected: exit 0 — confirms new AgentAnalytics/RecentAiResearchEntry types + agents page card compile
```

- All checklist items (A1-E6) checked
- Company-correlation signal confirmed read-only, on-read only (no new table, no migration)
- No person-level claim constructed anywhere in this phase's code
- Phase report written to report destination above, including the D1 known-gap finding either way
  (join exists and was used, OR join does not exist and correlation degrades to empty list)

---

## Known Gaps / Backlog

- **Per-site commercial-page configuration** — this phase ships a fixed module-level
  `COMMERCIAL_PAGE_PREFIXES` constant, not a per-site configurable list. Write a backlog note
  to `process/features/evallayer/backlog/` if one does not already exist for this item.
- **Company-correlation IP join** — contingent on D1's finding; if no queryable IP-to-company
  linkage exists at read time, this is a known-gap documented in the phase report (not silently
  dropped).
- **Docker-gated integration** — live sweep end-to-end (scheduler tick → alert email actually
  sent via SendGrid in mock mode) is a known-gap consistent with the program's existing
  Docker-verification backlog (`process/features/evallayer/backlog/program-docker-verification-gaps_NOTE_23-07-26.md`).

---

## Blockers That Would Justify BLOCKED Status

- Phase 1 (H1) exit gate not yet passed
- `apps/api/jobs/scheduler.py` overlap with Phase 2's registration not yet resolved — re-verify
  per umbrella's Pre-PVL Conflict Resolution before EXECUTE, do not proceed on a stale read
- Any discovered code path where the company-correlation signal could trigger outreach
  automatically — hard stop requiring plan revision, not a fix-in-place

---

## Inner Loop Refresh Note

**Date:** 24-07-26
**Trigger:** Autonomous /goal Phase H3 plan-supplement — encoded locked design decisions
(module names, pure-function signatures, copy template, dedup TTL, scheduler insertion point,
config field, correlation join strategy and its known-gap fallback) directly into the
Implementation Checklist and Locked Design section, resolving all previously-open INNOVATE
questions (commercial-page mechanism, delivery integration point, delivery latency tier).
**Sections changed:** Purpose, Locked Design (new), Blast Radius, Implementation Checklist
(A-E fully rewritten with concrete steps), Exit Gate (added FE build gate), Known Gaps /
Backlog (new), Verification Evidence, Resume and Execution Handoff.
**Net effect:** Phase 4 (PVL) should be re-run — validate-contract is still a placeholder, so
this triggers the normal placeholder-contract routing regardless.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — confirmed via direct code re-read this session: H2 scheduler registration
      location, hot_alert.py's existing pattern, agent_aggregator.py's pure-function style,
      Company model schema (no ip_address column), AgentFetchEvent schema/indexes,
      AgentAnalyticsResponse/api-types.ts current shape.
- [x] 2. INNOVATE — all previously-open questions resolved and locked in this supplement (see
      Inner Loop Refresh Note).
- [x] 3. PLAN-SUPPLEMENT — this update.
- [x] 4. PVL — vc-validate-agent: full V1-V7 complete 24-07-26; validate-contract written.
      Person-level claim exclusion, outreach-trigger exclusion, and the D1 known-gap fallback path
      were re-verified against live source; two CONCERNs found (email HTML-escaping gap, pure-fn
      contract violation in Locked Design D) — both FIXED IN PLAN TEXT this pass, not deferred.
- [x] 5. EXECUTE — all checklist items (A1-E6) done 24-07-26; unit gates green (24 new tests in
      `test_intent_alerts.py` + updated aggregator shape test; full suite 924 passed, 0 failures),
      FE `npm run build` exit 0. Docker-gated live sweep = known-gap (integration test written +
      collect-clean). Report: `phase-03-intent-signals_REPORT_23-07-26.md`.
- [x] 6. EVL — independent re-run confirms all H3-owned Fully-Automated gates green (24/24 unit
      tests, FE build exit 0, blast-radius diff matches plan). One foreign, out-of-blast-radius
      failure (`test_pixel.py::test_source_under_20kb`) found and attributed to the concurrent
      `first-party-capture_24-07-26` session — not an H3 gap. Docker-gated live-sweep gate stays
      the sole H3-owned known-gap. See `phase-03-intent-signals_REPORT_23-07-26.md` §EVL
      Confirmation.
- [x] 7. UPDATE PROCESS — phase report augmented with EVL confirmation; umbrella
      `## Current Execution State` updated to Phase H4; blast-radius registry EVL note appended.
      No commit performed (per instructions — vc-git-manager next).

**Validate-contract required before execute.** Written 24-07-26 — Gate: CONDITIONAL. Step 5
(EXECUTE) may proceed. Execute-agent instructions E-B1 and E-D1 (see Validate Contract) carry the
two PVL-corrected design points forward — both are already reflected in Locked Design +
Implementation Checklist above, so EXECUTE should not need to re-derive them.

---

## Touchpoints

- `apps/api/services/agent_intent_signals.py` (new)
- `apps/api/services/hot_alert.py` (add `maybe_send_intent_alert`, existing function untouched)
- `apps/api/services/agent_aggregator.py` (extend `aggregate_agent_analytics`)
- `apps/api/schemas/agents.py` (add `RecentAiResearchEntry`, extend `AgentAnalyticsResponse`)
- `apps/api/config.py` (add `intent_signal_sweep_interval_minutes`)
- `apps/api/jobs/scheduler.py` (one new additive job registration, after Phase 2's)
- `apps/web/src/lib/api-types.ts` (extend `AgentAnalytics`, add `RecentAiResearchEntry`)
- `apps/web/src/app/dashboard/agents/page.tsx` (widget: "Appeared after AI research")
- `tests/unit/test_intent_alerts.py` (new)

---

## Public Contracts

- `hot_alert.py`'s existing `maybe_send_hot_alert` contract is reused, not altered; new sibling
  function `maybe_send_intent_alert` added alongside it.
- `AgentAnalyticsResponse` schema is extended additively (new `recent_ai_researched_companies`
  field), never modifying `by_vendor`/`top_pages`/`by_verification`/`handoff_links_count`.
- No new database schema, no new migration, no new table this phase.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_is_commercial_page` | Fully-Automated | AC-H3-1 (precondition) |
| `test_commercial_page_triggers_alert` | Fully-Automated | AC-H3-1 |
| `test_detect_spike` | Fully-Automated | AC-H3-2 |
| `test_intent_alert_copy_is_site_level_only` | Fully-Automated | AC-H3-4 |
| `test_company_correlation_is_metadata_only` | Fully-Automated | AC-H3-3 |
| `test_correlation_is_site_scoped` | Fully-Automated | AC-H3-4 |
| `npm run build` (apps/web) | Fully-Automated | AC-H3-3 / AC-H3-4 (FE surface compiles, no action affordances added) |
| Live sweep → email delivery (Docker-gated) | Hybrid — known-gap this phase | AC-H3-1 (end-to-end) |

```bash
cd /Users/apple/getbeam && python -m pytest tests/unit/test_intent_alerts.py -v
cd /Users/apple/getbeam/apps/web && npm run build
# Expected: both exit 0
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/handoff_23-07-26/phase-03-intent-signals_PLAN_23-07-26.md`
- Last completed step: Step 4 (PVL) — validate-contract written 24-07-26, Gate: CONDITIONAL
- Validate-contract status: written — see `## Validate Contract` below
- Context files loaded this session (RESEARCH + PVL combined): `apps/api/services/hot_alert.py`,
  `apps/api/jobs/scheduler.py`, `apps/api/schemas/agents.py`, `apps/api/models/agent_fetch_event.py`,
  `apps/api/models/company.py`, `apps/api/models/company_graph.py`, `apps/api/models/site.py`,
  `apps/api/config.py`, `apps/api/services/agent_aggregator.py`, `apps/api/services/identity_resolver.py`,
  `apps/api/services/visitor_aggregator.py`, `apps/api/services/company_resolver.py`,
  `apps/api/routers/agents.py`, `apps/api/agents/segmenter.py`, `apps/api/agents/campaign_planner.py`,
  `tests/unit/test_handoff_emailability_separation.py`, `apps/web/src/lib/api-types.ts`,
  `apps/web/src/app/dashboard/agents/page.tsx`
- Next step: Spawn vc-execute-agent for this plan — implement checklist A1-E6 in order (pure
  module A/C -> hot_alert.py sibling B -> config+scheduler C3-C4 -> analytics/FE D -> tests E),
  following execute-agent instructions E-B1 and E-D1 in the Validate Contract

---

## Test Infra Improvement Notes

(none identified yet)

---

## Validate Contract

Status: CONDITIONAL
Date: 24-07-26
date: 2026-07-24
generated-by: inner-pvl: phase-h3

Parallel strategy: sequential
Rationale: single phase plan, single validator pass — 2/7 signals present (S2 schema-adjacent
read-only correlation surface classified as no-schema; more precisely S6 outreach-adjacent/
alert-adjacent surface, S7 not met at <9 files). Below the MEDIUM parallel-subagent threshold
(2-3). Layer 1/Layer 2 fan-out for this VALIDATE pass was run sequentially in one session — small,
well-scoped blast radius (9 files, no migration), all context loaded upfront via direct code
re-reads (hot_alert.py, scheduler.py, agent_aggregator.py, company.py, company_graph.py,
identity_resolver.py, visitor_aggregator.py, agents.py router, segmenter.py, campaign_planner.py,
test_handoff_emailability_separation.py).

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-H3-1 (precondition) | `is_commercial_page` exact match, sub-path match, false-positive guard (`/pricing-blog` must NOT match `/pricing`) | Fully-Automated | `tests/unit/test_intent_alerts.py::test_is_commercial_page` | A |
| AC-H3-1 | commercial-page on-demand fetch triggers alert with dedup + LOCKED copy gating | Fully-Automated | `tests/unit/test_intent_alerts.py::test_commercial_page_triggers_alert` | A |
| AC-H3-1 (delivery UX) | delivery reuses existing `EmailSender`/`hot_alert_enabled` gate — no new UX surface | Agent-Probe (folded into Fully-Automated per Locked Design — no new channel, no probe needed) | n/a — delivery mechanism identical to `maybe_send_hot_alert`, already proven by that function's existing coverage | A |
| AC-H3-2 | spike detection: floor case (2 hits, 0 baseline => no spike), multiplier case (3 hits, 1.0 avg => spike), zero-baseline floor case (3 hits, 0.0 avg => spike) | Fully-Automated | `tests/unit/test_intent_alerts.py::test_detect_spike` | A |
| AC-H3-4 (alert copy safety) | rendered alert copy contains no email/person/company/visitor identifier token | Fully-Automated | `tests/unit/test_intent_alerts.py::test_intent_alert_copy_is_site_level_only` | A |
| AC-H3-4 (copy PVL correction) | `page_path`/`vendor` are HTML-escaped before interpolation into `body_html` (attacker-influenceable request-path data) | Fully-Automated | `tests/unit/test_intent_alerts.py::test_intent_alert_copy_is_site_level_only` (extend to assert escaped output for a page_path containing `<`/`>`/`"`) | B |
| AC-H3-3 | company-correlation signal is read-only metadata: no write path into campaign/segment/outreach tables; `RecentAiResearchEntry` never persisted | Fully-Automated | `tests/unit/test_intent_alerts.py::test_company_correlation_is_metadata_only` | A |
| AC-H3-4 (site-scoping) | correlation query is site-scoped; no cross-tenant read path | Fully-Automated | `tests/unit/test_intent_alerts.py::test_correlation_is_site_scoped` | A |
| AC-H3-3/4 (FE build) | new `AgentAnalytics`/`RecentAiResearchEntry` TS types + agents-page card compile | Fully-Automated | `cd apps/web && npm run build` | A |
| AC-H3-1 (live-integration) | scheduler tick -> sweep -> alert email actually sent via SendGrid mock mode, real Postgres round-trip | Hybrid — known-gap this phase | Docker-gated — Docker daemon unresponsive in this sandbox (`docker ps` produced no output, 120s timeout), matches H1/H2's identical precedent | D |

gap-resolution legend: A — proven now (gate passes once EXECUTE writes the test file). B — fixed
in this plan (the two PVL-found design corrections — HTML-escaping in Locked Design B, pure-fn
contract fix in Locked Design D — are already written into the plan's Locked Design and
Implementation Checklist above, and E4's proving test is extended in-checklist to assert the
escaped-output case). D — backlog test-building stub (named residual; Docker daemon unresponsive
in this sandbox — matches H1/H2's identical treatment).

Failing stubs (Fully-Automated rows):

```
test("should classify /pricing, /pricing/enterprise as commercial but not /pricing-blog", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: test_is_commercial_page")
})
test("should trigger and dedup an intent alert for a qualifying commercial-page fetch", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: test_commercial_page_triggers_alert")
})
test("should detect spike only when floor(>=3) AND >=2x trailing avg both hold", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: test_detect_spike")
})
test("should render alert copy with no person/company/visitor identifier, HTML-escaped page_path/vendor", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: test_intent_alert_copy_is_site_level_only")
})
test("should never write recent_ai_researched_companies into campaign/segment/outreach tables or persist it", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: test_company_correlation_is_metadata_only")
})
test("should scope the correlation query to site_id with no cross-tenant read path", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: test_correlation_is_site_scoped")
})
```

(Note: these are illustrative Python `pytest`-shaped scenarios rendered in the stub-skeleton
format the skill specifies; execute-agent implements them as real `pytest` functions in
`tests/unit/test_intent_alerts.py`, not literal JS `test()` blocks.)

Legacy line form:
- Commercial-page classification + alert trigger/dedup/copy: Fully-automated: `pytest tests/unit/test_intent_alerts.py -v`
- Spike detection: Fully-automated: same file, `test_detect_spike`
- Copy safety (site-level-only + HTML-escaping): Fully-automated: same file, `test_intent_alert_copy_is_site_level_only`
- Correlation metadata-only + site-scoping: Fully-automated: same file, `test_company_correlation_is_metadata_only` + `test_correlation_is_site_scoped`
- FE build: Fully-automated: `cd apps/web && npm run build`
- Live sweep -> email delivery: hybrid: known-gap, Docker daemon unavailable this session

Structural Plan Validators (V1 Step 3b, mandatory):
- `node .claude/skills/vc-generate-phase-program/scripts/validate-phase-stub.mjs <this file>` —
  **0 failures, 0 warnings** — correct validator for this file's shape (phase-program per-phase
  stub), matching H1/H2's identical precedent.
- `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs <this file>` — 3 FAILs
  / 4 warnings reported (missing overview/context section, Complexity metadata, Phase Completion
  Rules as literal headings). **Expected shape mismatches, not real defects** — same precedent as
  H1/H2: this validator checks the standalone SIMPLE/COMPLEX plan template, which phase-stub files
  deliberately don't use (they use `## Purpose`/`## Locked Design`/`## Phase Loop Progress`
  instead, per `phase-programs.md`'s phase-stub template). Reported per protocol as mandatory, not
  treated as blocking.

Dependency-BLOCKED guard: checked `phase-blast-radius-registry.md` — Phase 1 (H1) status DONE,
Phase 2 (H2) status DONE. Neither is `BLOCKED-skipped`. Proceeds.

Dimension findings:
- Infra fit: PASS — no new container/runtime/proxy surface; the one new periodic job follows the
  exact existing `scheduler.add_job("interval", minutes=..., id=..., replace_existing=True)`
  pattern; insertion point re-confirmed live at `apps/api/jobs/scheduler.py` lines 233-236
  (H2's `handoff_correlation_sweep` registration) — matches the plan's baseline exactly, no drift.
  Sweep query fits the existing `idx_agent_fetch_events_site_path_tier_created` composite index —
  no new index required.
- Test coverage: PASS — every developed behavior (classification, alert trigger/dedup/copy,
  spike, correlation metadata-only, site-scoping, FE compile) has a Fully-Automated gate; only the
  live end-to-end delivery path is Known-Gap, and it is a pre-documented, backlog-tracked residual
  consistent with H1/H2 — not a vacuously-green net gate.
- Breaking changes: PASS — `AgentAnalyticsResponse`/`AgentAnalytics` TS interface extensions are
  additive-only (new field, no existing field renamed/removed), matching H2's identical precedent;
  `maybe_send_hot_alert` is untouched, `maybe_send_intent_alert` is a new sibling; no new
  migration, no schema change.
- Security surface: CONCERN found, FIXED IN PLAN — alert copy interpolates `page_path` (attacker-
  influenceable request-path data) and `vendor` (classifier-derived) into an HTML email body
  without an explicit escaping step in the original Locked Design text, unlike the existing
  `maybe_send_hot_alert`'s `escape(name)`/`escape(site.name)` pattern in the same file. Corrected
  in Locked Design B + checklist B1 to require `html.escape()` on both values before
  interpolation, mirroring the existing pattern exactly (`from html import escape` already
  imported in `hot_alert.py`). No other security findings: dedup key uses only `site_id`+
  `page_path` (no PII); `vendor` values come from a controlled classifier vocabulary, not raw
  request headers; no new external call, no new secret, no new trust-boundary; company-correlation
  signal confirmed read-only via direct grep of `segmenter.py`/`campaign_planner.py` (neither
  references `Company` at all today, so there is no existing wiring this signal could be
  accidentally pulled into).
- Section A (Commercial-page classification): PASS — pure function, no I/O, mechanically
  feasible, no gaps or conflicts found.
- Section B (Live on-demand alert): CONCERN found, FIXED IN PLAN — see Security surface finding
  above (HTML-escaping). Otherwise mechanically feasible: `Site`/`EmailSender`/`get_redis()` reuse
  confirmed against live `hot_alert.py` (lines 1-108 re-read in full), `hot_alert_enabled` field
  confirmed present on `Site` model. Highest-risk edit: the email body construction — mitigated by
  the escaping fix above; execute-agent should build `body_html` the same way `maybe_send_hot_alert`
  does (list of escaped `<p>` fragments joined), not an f-string with raw interpolation.
- Section C (Spike detection + scheduler): PASS — `detect_spike`'s floor-then-multiplier formula
  is pure and correctly handles the zero-baseline edge case (floor `>=3` gates before the
  multiplier applies). Scheduler insertion point re-verified live (exact line match, no drift);
  purely additive, no existing job reordered.
- Section D (Company-correlation): CONCERN found, FIXED IN PLAN — two issues: (1) the original
  Locked Design text said to put a DB query directly inside `aggregate_agent_analytics`, which
  contradicts that function's documented pure/no-DB/unit-testable-without-a-DB contract (confirmed
  via docstring + existing `fetch_agent_visit_rows`/`fetch_handoff_links_count` DB-fetch/pure-
  aggregation split precedent); corrected to a new sibling `fetch_recent_ai_researched_companies`
  DB-fetch function, mirroring H2's identical Section-D correction verbatim. (2) the plan treated
  the IP-to-company join as fully open ("re-read identity_resolver.py... if a usable join exists");
  direct code read found a concrete real candidate: the durable `company_graph` table
  (`CompanyGraphNode.ip` -> `domain`, gated by `settings.company_graph_enabled`) from the
  visitors-identity "owned-data-layer" program. Corrected Locked Design + checklist D1 to name this
  as the primary join to try, while preserving the plan's original known-gap fallback (empty list)
  for when the flag is off or no row matches — the fallback logic itself was already correct, it
  just needed a concrete primary path named instead of an open-ended re-read task.
- Section E (Tests): PASS — all planned scenarios in `tests/unit/test_intent_alerts.py` are new,
  correctly scoped, and mirror H2's `test_handoff_emailability_separation.py` metadata-only-proof
  discipline (E5). `npm run build` command confirmed present in `apps/web/package.json` usage
  (same command H1/H2 already use as their FE gate).

Execute-agent instructions:
- E-B1: HTML-escape `page_path` and `vendor` via `html.escape()` before interpolating into
  `body_html` in `maybe_send_intent_alert` — do not use a raw f-string; build `body_html` as a
  list of escaped fragments joined, mirroring `maybe_send_hot_alert`'s existing pattern in the
  same file.
- E-D1: Implement `fetch_recent_ai_researched_companies(db, site_id)` as a NEW sibling DB-fetch
  function in `agent_aggregator.py` — do NOT put a query inside `aggregate_agent_analytics`
  itself. Try the `company_graph` join first (`CompanyGraphNode.ip == AgentFetchEvent.ip_address`,
  `CompanyGraphNode.domain == Company.domain`, `Company.site_id == site_id`); re-confirm exact
  `CompanyGraphNode` column names by re-reading `apps/api/models/company_graph.py` immediately
  before writing the query. If `company_graph_enabled` is False deployment-wide, degrade to an
  empty list and record the finding as a known-gap in the phase report either way (join used, or
  flag off / no match — both outcomes must be documented, not silently absorbed).
- E-D3/D4: Before marking Section D complete, grep `apps/api/agents/segmenter.py` and
  `apps/api/agents/campaign_planner.py` for any new reference to `Company`/`recent_ai_researched`
  introduced during EXECUTE — confirm the count is still zero (matches this VALIDATE pass's
  finding) so the metadata-only guarantee (AC-H3-3) has not silently regressed mid-EXECUTE.
- E-C4: Re-run `alembic heads`-equivalent confirmation is not applicable this phase (no
  migration) — instead, immediately before writing the scheduler job registration (checklist C4),
  re-read the live `apps/api/jobs/scheduler.py` one more time to confirm H2's
  `handoff_correlation_sweep` registration is still at (or near) lines 233-236; if it has moved,
  register `run_intent_signal_sweep` immediately after wherever it now is — never before it.

High-risk pack: not required under the 6 formal high-risk classes in `orchestration.md` §High-Risk
Execution Handoff / `vc-risk-evidence-pack` (this phase touches none of: auth/identity,
billing/credits, schema/migration, public-API-breaking change, deploy/runtime/container/proxy/
gateway, or permission/secret/trust-boundary logic — no migration, no schema change, additive-only
API extension). Flagged by the task as "alert/outreach-adjacent" regardless — the concrete
mitigating controls already in the plan/contract are: (1) LOCKED site-level-only copy template
with no person/company/IP tokens, proven by `test_intent_alert_copy_is_site_level_only`; (2)
HTML-escaping fix (E-B1) closing the one real injection vector found; (3)
`test_company_correlation_is_metadata_only` as the tripwire proving zero write path into
campaign/segment/outreach tables, mirroring H2's AC-H2-3 tripwire discipline; (4) reuse of the
existing `hot_alert_enabled` per-site opt-in toggle (no new consent surface introduced). No
`risk-gate.json`/`review-decision.json` artifact set is produced this phase; if a future phase
adds a NEW notification channel or a write path into outreach, re-evaluate against the 6 classes.

Backlog artifacts:
- `process/features/evallayer/backlog/phase-03-per-site-commercial-page-config_NOTE_24-07-26.md`
  — already exists (referenced in plan's Known Gaps section); no new note needed this pass.
- `process/features/evallayer/backlog/program-docker-verification-gaps_NOTE_23-07-26.md` — H3 row
  to be appended (live sweep + email delivery Docker-gated known-gap), consistent with H1/H2's
  identical treatment.

Known gaps:
- Live scheduler tick -> sweep -> alert email delivery (real Postgres, SendGrid mock mode) —
  Docker daemon unresponsive in this sandbox (`docker ps` produced no output, 120s timeout).
  Named residual, Hybrid tier, gap-resolution D — tracked in the backlog note above, consistent
  with H1/H2's identical treatment (both shipped Gate: CONDITIONAL with the same class of
  residual, later EVL-confirmed green on all Fully-Automated gates).
- Company-correlation join (D1) — contingent on `company_graph_enabled` being True in the target
  deployment and on `CompanyGraphNode` rows actually existing for a given fetch event's IP;
  degrades gracefully to an empty list when either condition fails, per Locked Design.
- Per-site commercial-page configuration — fixed module-level constant this phase, not
  configurable; already tracked in the existing backlog note referenced above.

What this coverage does NOT prove:
- The Fully-Automated classification/alert/spike/copy/correlation tests prove correctness against
  synthetic in-memory fixtures with controlled inputs — they do NOT prove the sweep performs
  acceptably at real production fetch-event volumes, nor that
  `idx_agent_fetch_events_site_path_tier_created` is sufficient under real query-planner behavior
  with real table statistics (only inspected structurally, never EXPLAIN-ANALYZEd).
- `test_company_correlation_is_metadata_only` proves no write path exists in `segmenter.py`/
  `campaign_planner.py` as of this VALIDATE pass; it does not prove a future edit can't
  reintroduce one — only a literal-string tripwire (as this test is designed to be, mirroring
  H2's AC-H2-3 discipline) catches that mechanically going forward, and only if this exact test
  keeps running in CI.
- `test_intent_alert_copy_is_site_level_only`'s escaping assertion proves the specific HTML
  metacharacters tested are escaped; it does not exhaustively fuzz all possible `page_path`
  encodings an attacker might craft (e.g. Unicode homoglyph or double-encoding tricks) — email
  client HTML rendering behavior beyond basic `<>"'&` escaping is out of scope for this gate.
- The FE build gate proves TypeScript compiles; it does not prove the new "Appeared after AI
  research" card renders correctly in a live browser (no Playwright e2e planned for this phase,
  consistent with H2's identical scope decision).
- The Docker-gated Hybrid gate, when eventually run, is the only gate that would catch a real
  Postgres-specific behavior difference in the correlation query (e.g. an actual index scan vs.
  seq scan decision on the `company_graph` join) or confirm SendGrid mock-mode delivery actually
  fires from a live scheduler tick — until it runs, that residual risk class stays open exactly as
  it did for H1 and H2.

Gate: CONDITIONAL (0 FAILs; 2 CONCERNs found and fixed in plan text this pass — HTML-escaping gap,
pure-function contract violation in company-correlation design; 1 Docker-gated Hybrid known-gap
remains, consistent with the umbrella charter's explicit allowance for Docker-gated residuals at
PVL)
Accepted by: session (autonomous, /goal execution) — accepted concern: "Live scheduler sweep ->
alert email delivery unverified in this sandbox (Docker daemon unresponsive)" — matches the
umbrella's Autonomous Execution Rules ("CONDITIONAL net gate: proceed autonomously, fixes applied
in-flight, gaps on record") and the identical precedent already accepted for Phase 1 (H1) and
Phase 2 (H2). No person-level claim, no outreach-trigger path, and no schema/migration surface
were found anywhere in this phase — the three items flagged as highest-priority in the task
prompt are all clean.
