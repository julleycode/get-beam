---
name: plan:ws1-ai-evaluation-timeline
description: "WS1 — dedicated read endpoint + dashboard collapsible section rendering a visitor's AI-agent fetch timeline"
date: 30-07-26
feature: agent-native-revenue
phase: "WS1"
---

# WS1 — AI Evaluation Timeline — Plan

Date: 30-07-26
Status: VALIDATED — Gate: PASS (see Validate Contract section) — ready for ENTER EXECUTE MODE
Complexity: SIMPLE (2 files touched: `apps/api/routers/visitors.py`, `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` + 2 supporting client files; no schema/migration/auth surface)

Context loaded: `process/context/all-context.md` (root router — see AI-Agent-Traffic Layer /
Owned Identity Data Layer sections for the handoff-link precedent this plan widens) and
`process/context/tests/all-tests.md` (integration test runner + Playwright e2e conventions used
in the Verification Evidence gates below).

---

## Overview

Give a salesperson a readable, chronological list of every AI-agent fetch event tied to a
resolved company/visitor, so they can open a warm conversation ("I saw your ChatGPT agent pull
our pricing page twice last week") instead of a cold pitch. This clones the existing single-latest
handoff join already live in `get_visitor_detail` (Handoff Detection H2), widens it to the full
chronological list, and adds a lazy-loaded collapsible section on the dashboard.

No new table, no migration, no new auth surface — this is a read-only join over data that already
exists (`agent_fetch_events`, `agent_handoff_links`), gated by the same tenant check the rest of
the visitor-detail surface already uses.

## Goals

1. New endpoint: `GET /{site_id}/{visitor_id}/agent-timeline` returning the visitor's confirmed
   handoff-linked fetch events, ordered chronologically, thin shape (`page`, `vendor`, `timestamp`,
   `confidence`).
2. New collapsible "AI Evaluation Timeline" dashboard section, lazy-loaded on expand, rendered near
   the existing "Arrived via"/handoff pill.
3. Zero schema change, zero new write path, zero effect on emailability.

## Scope

**In scope:** backend endpoint + schema, frontend client method + type, new UI section, empty-state
guard, confidence tooltip copy.

**Out of scope (explicitly deferred):** "highlight pages the human hasn't opened yet" (nice-to-have
from RESEARCH — no cheap computation found; not required by any AC — see Deferred Items below).
Any change to the correlation sweep itself (`agent_handoff_correlation.py`) — WS1 is a pure
consumer of already-written `high`/`medium` confidence rows, never a recompute.

---

## Touchpoints

| File | Change |
|---|---|
| `apps/api/routers/visitors.py` | New `GET /{site_id}/{visitor_id}/agent-timeline` endpoint, placed as a sibling right after `get_visitor_detail` (~line 728). Reuses `_verify_site_access` verbatim. |
| `apps/api/schemas/visitor.py` (or wherever `VisitorDetailOut` lives — confirm exact schema file at EXECUTE time via grep; do not assume a new file) | New thin response schema: `AgentTimelineEntry` (`page: str | None`, `vendor: str`, `timestamp: datetime`, `confidence: str`) + `AgentTimelineOut` (`entries: list[AgentTimelineEntry]`). |
| `apps/web/src/lib/api.ts` | New client method `getAgentTimeline(siteId, visitorId)` near `getAgentAnalytics` (~line 578), same request pattern. |
| `apps/web/src/lib/api-types.ts` (or co-located type export in `api.ts` if that's the house pattern — confirm at EXECUTE time) | New `AgentTimelineEntry` / `AgentTimelineOut` (or equivalent) types matching the backend schema. |
| `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` | New `CollapsibleSection` ("AI Evaluation Timeline"), placed near the existing handoff pill (~line 532) / in the main content column (existing `CollapsibleSection` pattern ~line 144). Lazy fetch triggered on first expand (`<details>` `onToggle` or equivalent), using the `defaultOpen={false}` convention already used by other optional sections. Empty-state guard: render nothing (no section at all) when the timeline has 0 entries — clone the `visitor.ai_source &&` optional-section guard pattern. |

## Public Contracts

- **New API surface**: `GET /api/v1/visitors/{site_id}/{visitor_id}/agent-timeline` — additive,
  read-only, tenant-scoped exactly like `get_visitor_detail`. No existing contract changes.
- **No schema/migration.** Query reads existing `agent_fetch_events` + `agent_handoff_links` tables
  only (both already exist, both already indexed for this join per `idx_agent_handoff_links_site_visitor`
  and `idx_agent_fetch_events_site_created`).
- **No new auth surface.** Reuses `Depends(get_current_user)` + `_verify_site_access` verbatim — no
  new permission model.

## Blast Radius

- Risk class: **none of the 6 high-risk classes** (no auth/identity change, no billing, no
  schema/migration, no public API *contract* break — this is a net-new additive GET route, no
  destructive mutation, no container/proxy/gateway change, no secrets/trust-boundary logic).
- Files touched: 4 (2 backend, 2 frontend) — LOW blast radius.
- Read-only. Cannot create, upgrade, or mutate any `IdentifiedVisitor`/emailability state — the
  query is a SELECT join, full stop.

## Sequencing Note (read before EXECUTE)

Per the program SPEC and umbrella join conditions: WS1 must not begin implementation until
**WS0(b) (PR merge to `main`) is confirmed** — WS1's own research/plan-supplement steps may
proceed before WS0(d) (wild-survival test) completes, but the code in this plan reads
`agent_handoff_links`/`agent_fetch_events`, which only get populated in production after WS0's
marker code is live. Confirm WS0(b) status before ENTER EXECUTE MODE for this plan; if not yet
merged, this plan's code can still be written and tested against seeded fixtures, but AC-WS1-3
(the wild kill-test AC) cannot close regardless.

**AC-WS1-3 (≥1 real company timeline, wild data, human-readable "without further explanation")
CANNOT close until WS0 runs live on production and produces handoff-linked visitors in volume.**
This is a **known-gap, not a plan defect** — it is gated on WS0's exit metric (AC-WS0-5), not on
anything in this plan's scope. AC-WS1-1 and AC-WS1-2 are closeable now via seeded-fixture tests.

---

## Implementation Checklist

1. **Backend schema.** Add `AgentTimelineEntry` (`page: str | None`, `vendor: str`,
   `timestamp: datetime`, `confidence: str`) and `AgentTimelineOut` (`entries: list[AgentTimelineEntry]`)
   to the schemas module where `VisitorDetailOut` is defined. Follow existing Pydantic schema
   conventions in that file (field naming, `ConfigDict`/`from_attributes` if used elsewhere).
2. **Backend endpoint.** In `apps/api/routers/visitors.py`, add
   `GET /{site_id}/{visitor_id}/agent-timeline` immediately after `get_visitor_detail`:
   - Call `_verify_site_access(db, site_id, user)` first, exactly as `get_visitor_detail` does.
   - Query: `select(AgentHandoffLink, AgentFetchEvent).join(AgentFetchEvent, AgentFetchEvent.id == AgentHandoffLink.agent_fetch_event_id).where(AgentHandoffLink.site_id == site_id, AgentHandoffLink.visitor_id == visitor_id, AgentFetchEvent.site_id == site_id).order_by(AgentHandoffLink.created_at.asc())` — the SAME join `get_visitor_detail` already uses at lines ~698-717, minus `.limit(1)`, ordered ASC (chronological) instead of DESC-latest-only. **[VALIDATE P1 — defense-in-depth]** the explicit `AgentFetchEvent.site_id == site_id` clause is ADDED beyond what `get_visitor_detail` does today (that precedent only filters `AgentHandoffLink.site_id`) — belt-and-suspenders tenant scoping on both joined tables, cheap to add now, no behavior change for correctly-scoped data since the sweep only ever links same-site rows.
   - Map each `(link, fetch_event)` row to `AgentTimelineEntry(page=fetch_event.page_path, vendor=fetch_event.vendor, timestamp=fetch_event.created_at, confidence=link.confidence)`.
   - If the visitor doesn't exist or isn't in this tenant's site, return the SAME not-found behavior as `get_visitor_detail` (never 403 — don't leak id existence). Confirm whether an empty timeline (0 rows, valid visitor) should return `200` with `entries: []` (yes — a visitor with no handoff data is a normal state, not a 404).
   - No `Visitor` existence check needed beyond what `_verify_site_access` covers (tenant scoping) — the query itself naturally returns empty for a visitor with no records; confirm at EXECUTE time whether the plan needs an explicit `Visitor` row existence check to distinguish "wrong tenant" from "no data" — default to NOT adding one (matches "don't leak id existence" — a foreign visitor_id and a visitor with zero fetch events should look identical: 200, empty list). No `human_only_visitor_filter()` check needed either: `AgentHandoffLink.visitor_id` is structurally always a human visitor id by construction (H2 write policy links agent fetch events only to the human whose AI-referral click matched — an agent-derived visitor id never appears as this column's value), so there is no path for an agent-origin record to surface via this endpoint.
3. **Frontend client method.** In `apps/web/src/lib/api.ts`, add `getAgentTimeline(siteId: string, visitorId: string)` calling `/api/v1/visitors/${siteId}/${visitorId}/agent-timeline` (confirm exact route prefix by checking how `visitors.py`'s router is mounted — likely `/api/v1/visitors` given the sibling `get_visitor_detail` route shape), returning the typed response.
4. **Frontend types.** Add `AgentTimelineEntry` / `AgentTimelineOut` (or the file's established naming pattern) matching the backend schema field-for-field.
5. **Frontend UI section.** In `page.tsx`:
   - Add local state: `agentTimeline: AgentTimelineEntry[] | null`, `agentTimelineLoading: boolean`.
   - Add a new `CollapsibleSection` titled "AI Evaluation Timeline" with `defaultOpen={false}`, positioned near the existing handoff-pill block (~line 532) in the main content column.
   - On first expand (native `<details onToggle>` or a controlled open-state handler — follow whatever pattern nearby `CollapsibleSection` usages already use for lazy content, or add a simple "fetch once, cache in state" guard if no existing lazy pattern exists), call `api.getAgentTimeline(siteId, visitorId)`.
   - Render rows ordered as returned (chronological): page | vendor label (reuse existing `handoffVendorLabel()` map ~line 606) | formatted timestamp | confidence badge (reuse the existing tooltip-badge convention from the handoff pill, hedged language per AC-H2-4 precedent: "likely", "confidence", never certainty language).
   - **Empty-state guard**: if `agentTimeline !== null && agentTimeline.length === 0`, render nothing (no section at all) — clone the `visitor.ai_source &&` guard pattern used elsewhere on this page. Do not render an empty "no data" section; the section itself should not exist when there's nothing to show, matching the file's existing convention for optional sections.
6. **Confidence tooltip copy.** Reuse the hedged phrasing pattern from `handoffCopy()` (~line 545) — "high/medium confidence this fetch preceded this visit," never asserting certainty. Can be done in the same pass as step 5 (parallel-safe, same file).

## Deferred Items (not in this plan's scope)

- "Highlight pages the human hasn't opened yet" — no cheap computation found during PLAN; AC-WS1-2
  needs only page+vendor+time, so this is deferred to a follow-up backlog note rather than gating
  this plan. If picked up later: would need a join against the visitor's own pageview `Event` rows
  by `page_path`, filtered to the same site — moderate complexity, not a 1-line addition.

---

## Acceptance Criteria

Direct mapping from the program SPEC's WS1 section (`agent-native-revenue_SPEC_30-07-26.md`):

1. **AC-WS1-1** — the new `GET /{site_id}/{visitor_id}/agent-timeline` endpoint returns the
   ordered sequence of `AgentFetchEvent` rows (timestamp, page, vendor) for a resolved
   company/visitor. Testable: integration test with a seeded fetch-event sequence asserting
   ordering + field shape.
2. **AC-WS1-2** — the visitor detail page renders a new collapsible "AI Evaluation Timeline"
   section near the "Arrived via" pill, showing page + vendor + time per fetch event. Testable:
   Playwright e2e seeding a visitor with fetch events, asserting the section renders the expected
   rows.
3. **AC-WS1-3** — at least 1 real company's AI-evaluation timeline, built from real wild data (not
   seeded/mocked), is reviewed and confirmed readable "without further explanation." Testable only
   with wild data — **known-gap until WS0(d)/AC-WS0-5 lands on production** (see Sequencing Note
   above). Code is buildable and testable now; this specific AC cannot close until then.

Plan is considered complete for EXECUTE purposes when AC-WS1-1 and AC-WS1-2 are green and
AC-WS1-3 is recorded as an explicit, dated known-gap (not silently dropped).

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Integration test: seed a handoff+fetch-event sequence (2+ rows, mixed vendors, mixed confidence), call the new endpoint, assert response ordering (chronological ASC) and field shape (`page`, `vendor`, `timestamp`, `confidence`) | Fully-Automated | AC-WS1-1 |
| Integration test: call the endpoint with a foreign/wrong-tenant `visitor_id` or `site_id`, assert not-found behavior matches `get_visitor_detail`'s existing pattern (never 403) | Fully-Automated | Tenant-scoping constraint (SPEC Constraints) |
| Integration test: call the endpoint for a visitor with 0 handoff-linked fetch events, assert `200` + `entries: []` (not 404) | Fully-Automated | Empty-state correctness, backs AC-WS1-2's empty-state guard |
| Playwright e2e: seed a visitor with 2+ fetch events, load the visitor detail page, expand the "AI Evaluation Timeline" section, assert the expected rows render in order | Fully-Automated (Hybrid fallback: known Clerk auth-harness gap may block this — see program context; if blocked, downgrade to Agent-Probe manual UI check with a screenshot) | AC-WS1-2 |
| Regression: `tests/unit/test_agent_origin_exclusion.py` full suite, zero new failures (confirms this read-only addition does not touch/weaken emailability) | Fully-Automated | AC-G-1 |
| Manual review: ≥1 real company's timeline built from real wild handoff/fetch data, confirmed by a human to be readable "without further explanation," citing the visitor id and a screenshot/export | Agent-Probe (needs-live-provider — gated on WS0(d)/AC-WS0-5) | AC-WS1-3 (known-gap until WS0 live) |

## Test Infra Improvement Notes

(none identified yet)

---

## Validate Contract

Status: PASS
Date: 30-07-26
date: 2026-07-30
generated-by: inner-pvl: WS1

Parallel strategy: sequential
Rationale: 7-signal score 0/7 (no multi-package, no schema/auth/API-break, no 3+ directions, no
5+ files — 4 touched, no high-risk class) — LOW band, single sequential validate pass, no
fan-out justified. Scope was kept tight per explicit instruction: only the 3 named risk areas
(tenant scoping, emailability, test coverage) were investigated in depth; infra-fit and
breaking-changes dimensions were confirmed quickly against the cloned precedent.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-WS1-1 | New `GET /{site_id}/{visitor_id}/agent-timeline` returns ordered `AgentFetchEvent` rows (page/vendor/timestamp/confidence) for a resolved visitor | Fully-Automated | integration test seeding 2+ handoff+fetch rows (mixed vendor/confidence), calling the endpoint, asserting chronological ASC order + field shape (pattern: `tests/integration/test_handoff_correlation_integration.py` seeding + `tests/integration/test_visitor_resolve_endpoint.py` router/auth/test_client convention) | A |
| AC-WS1-1 (tenant isolation) | Foreign/wrong-tenant `site_id` or `visitor_id` returns the same not-found-equivalent shape as `get_visitor_detail` — never a 403, never distinguishable from "valid visitor, no data" | Fully-Automated | integration test: call endpoint with a foreign site_id/visitor_id combination, assert response matches the existing not-found pattern (via `_verify_site_access` 404 for foreign site_id; empty `entries: []` for a foreign-but-syntactically-valid visitor_id under the caller's own site) | A |
| AC-WS1-1 (empty state) | Valid visitor with 0 handoff-linked fetch events returns `200` + `entries: []`, not `404` | Fully-Automated | integration test: visitor with zero AgentHandoffLink rows, assert 200, empty list | A |
| AC-WS1-2 | Dashboard renders a new collapsible "AI Evaluation Timeline" section near the handoff pill, showing page/vendor/time per row, lazy-loaded on expand | Hybrid | Playwright e2e seeding a visitor with fetch events, expanding the section, asserting rendered rows; precondition: Clerk auth-harness fixture (known program-level gap — pre-approved Agent-Probe manual UI + screenshot fallback if the harness blocks the run) | B |
| AC-G-1 (regression) | This addition introduces zero new emailability path and zero weakening of agent-origin exclusion (pure read-only SELECT join, no IdentifiedVisitor write) | Fully-Automated | `tests/unit/test_agent_origin_exclusion.py` full suite, 0 new failures | A |
| AC-WS1-3 | At least 1 real company's AI-evaluation timeline, built from real wild handoff/fetch data, reviewed and confirmed human-readable "without further explanation" | Agent-Probe (needs-live-provider) | Manual review citing the real visitor_id + screenshot/export, performed after WS0(d) lands live in production and produces handoff-linked visitors in volume | C |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: `strategy` column carries only the 3 proving strategies (Fully-Automated /
Hybrid / Agent-Probe). AC-WS1-3 is Agent-Probe (a real proving strategy), not Known-Gap — the
probe itself is fully specified; it is simply gated (resolution C) on WS0(d)/AC-WS0-5 landing in
production first, per this plan's own Sequencing Note. The plan's actual developed behavior (the
endpoint + UI section) is proven now by Fully-Automated/Hybrid gates above — the net-gate
vacuous-green ban does not apply here, since no developed behavior rests on Known-Gap alone.

Legacy line form:
- Backend endpoint + tenant/empty-state behavior: Fully-automated: `.venv/bin/python -m pytest tests/integration/test_agent_timeline_endpoint.py -m integration -q` (new file, name TBD at EXECUTE)
- Dashboard section: Hybrid: `cd apps/web && npm run test:e2e` — precondition: Clerk auth-harness fixture; Agent-Probe fallback: manual expand + screenshot if harness blocks
- Emailability regression: Fully-automated: `.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q`
- Wild-data readability: known-gap: documented — gated on WS0(d)/AC-WS0-5 landing in production; see Sequencing Note in this plan

Failing stub (AC-WS1-1, Fully-Automated):
```
test("should return chronologically ordered agent-timeline entries for a resolved visitor", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: seed 2+ handoff+fetch rows, call GET /{site_id}/{visitor_id}/agent-timeline, assert ASC order + field shape")
})
```

Failing stub (AC-WS1-1 tenant isolation, Fully-Automated):
```
test("should return not-found-equivalent for a foreign site_id or visitor_id, never 403", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: call endpoint with foreign site_id/visitor_id, assert same not-found shape as get_visitor_detail")
})
```

Failing stub (AC-WS1-1 empty state, Fully-Automated):
```
test("should return 200 with empty entries for a visitor with zero handoff-linked fetch events", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: valid visitor, zero AgentHandoffLink rows, assert 200 + entries: []")
})
```

Failing stub (AC-G-1 regression, Fully-Automated):
```
test("should keep test_agent_origin_exclusion.py fully green after this addition", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: run full regression suite, assert 0 new failures")
})
```

(AC-WS1-2 is Hybrid and AC-WS1-3 is Agent-Probe — no stubs per policy.)

Dimension findings:
- Infra fit: PASS — additive route slots in as a sibling of `get_visitor_detail` in the same
  router file; both source tables (`agent_handoff_links`, `agent_fetch_events`) and their
  covering indexes (`idx_agent_handoff_links_site_visitor`, `idx_agent_fetch_events_site_created`)
  already exist; no new deploy/runtime/container surface.
- Test coverage: PASS — confirmed real precedents exist for both halves of the new test:
  `tests/integration/test_handoff_correlation_integration.py` (seeding pattern for
  AgentHandoffLink+AgentFetchEvent) and `tests/integration/test_visitor_resolve_endpoint.py`
  (test_client + auth + tenant-scoped router pattern). AC-WS1-3 correctly recorded as a named,
  dated, gated deferral (not silently dropped) — does not block EXECUTE readiness per the plan's
  own Phase Completion Rules.
- Breaking changes: PASS — net-new additive GET route; no existing endpoint, schema, or contract
  is modified. `apps/api/main.py` mounts `visitors.router` at `/api/v1/visitors` (confirmed) —
  route path in the plan (`/{site_id}/{visitor_id}/agent-timeline`) is consistent.
- Security surface: PASS (after Plan Update P1 applied) — `_verify_site_access` reused verbatim
  (404-not-403, matches multi-tenancy guardrail); confirmed `AgentHandoffLink.visitor_id` is
  structurally always a human-origin id (H2 write policy), so no `human_only_visitor_filter()`
  gap exists; confirmed zero write path — cannot create/upgrade/mutate `IdentifiedVisitor` or
  affect emailability. One defense-in-depth gap found and FIXED IN PLAN (P1 below): the join as
  originally drafted filtered `AgentHandoffLink.site_id` but not `AgentFetchEvent.site_id`
  (mirroring, not improving on, the existing `get_visitor_detail` precedent). Added the explicit
  second-table filter; not a live exploit path today (the correlation sweep only ever links
  same-site rows), but cheap and correct to close given a 1:1 unique join.
- Section — Implementation Checklist: PASS — mechanical feasibility HIGH confidence (field names
  `page_path`/`vendor`/`confidence`/`created_at` verified against `AgentFetchEvent`/
  `AgentHandoffLink` model source; router prefix `/api/v1/visitors` verified in `main.py`;
  `_verify_site_access` import path verified). No gaps or conflicts found beyond P1 (applied).
  Highest-risk edit: the WHERE-clause tenant scoping on the join — mitigated by P1 (applied) and
  by the dedicated cross-tenant integration test already specified in Verification Evidence.

Open gaps:
- AC-WS1-3: known-gap: documented — gated on WS0(d)/AC-WS0-5 landing live in production (see
  this plan's Sequencing Note). This plan reaches CODE DONE without it; does not reach VERIFIED
  until then. Not counted toward CONDITIONAL/BLOCKED — explicitly named, dated, and cross-referenced.
- AC-WS1-2 Playwright leg: contingent on the known program-level Clerk auth-harness gap; if it
  blocks, downgrades to the pre-approved Agent-Probe manual-UI-check fallback already specified
  in Verification Evidence — not a new gap, inherited from prior program context.

What this coverage does NOT prove:
- The Fully-Automated integration tests prove endpoint shape, ordering, tenant isolation, and
  empty-state correctness against seeded fixture data — they do not prove the feature is useful
  or readable against real wild data (that is AC-WS1-3, deliberately deferred).
- The Hybrid/Agent-Probe Playwright leg proves the section renders with seeded data in a
  Playwright-driven browser session — it does not prove real end-user dashboard performance,
  cross-browser rendering beyond the configured Playwright projects, or accessibility.
- The `test_agent_origin_exclusion.py` regression proves this addition does not weaken existing
  emailability exclusion — it does not independently re-verify the exclusion logic itself (that
  is that suite's own existing scope, unchanged here).
- None of the above gates touch production data, migration behavior, or WS0's live-crawler
  marker code — this plan reads tables that are already populated by prior shipped work; there is
  no new write path to verify.

Gate: PASS (no FAILs, plan updated)
Accepted by: session (VALIDATE — no CONCERNs raised requiring user acceptance; one finding was
resolved via a plan update (P1) rather than left open)

---

## Phase Completion Rules

- **PLAN → VALIDATE**: complete — Gate: PASS, see Validate Contract section above.
- **PLAN → EXECUTE**: requires explicit "ENTER EXECUTE MODE" regardless of VALIDATE outcome.
- **EXECUTE → done**: complete when AC-WS1-1 and AC-WS1-2's test gates are green (Fully-Automated,
  Hybrid fallback for the Playwright leg if the known Clerk auth-harness gap blocks it) and the
  `test_agent_origin_exclusion.py` regression suite still passes with zero new failures.
- **Not VERIFIED until AC-WS1-3 closes** — per the program's wild-test discipline (guardrail 3),
  this plan can reach `CODE DONE` (implemented, lab-tested) but not `VERIFIED` until a real
  company's timeline is reviewed against wild production data. Do not mark this plan `✅ VERIFIED`
  in any phase report or the umbrella status table until then — record `CODE DONE` and cite the
  known-gap explicitly.
- **Known-gap handling**: AC-WS1-3's known-gap status must be written into the phase report at
  UPDATE PROCESS, not silently dropped, and must reference this plan's Sequencing Note.

## Resume and Execution Handoff

1. **Selected plan file path:** `process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/ws1-ai-evaluation-timeline_PLAN_30-07-26.md`
2. **Last completed phase/step:** VALIDATE (this document) — Gate: PASS, validate-contract written. Not yet executed.
3. **Validate-contract status:** written, Gate: PASS (see Validate Contract section above, `generated-by: inner-pvl: WS1`).
4. **Supporting context files loaded:** `agent-native-revenue_SPEC_30-07-26.md` (WS1 ACs + constraints), `agent-native-revenue-umbrella_PLAN_30-07-26.md` (WS1 stub, join conditions, Program Goal Charter), `apps/api/routers/visitors.py` (`get_visitor_detail` precedent, lines ~603-728), `apps/api/models/agent_fetch_event.py`, `apps/api/models/agent_handoff_link.py`, `apps/api/services/agent_handoff_correlation.py` (confidence-tier write policy), `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` (CollapsibleSection/InfoRow/handoff-pill patterns), `apps/web/src/lib/api.ts` (`getAgentAnalytics` client-method pattern), `tests/integration/test_handoff_correlation_integration.py` + `tests/integration/test_visitor_resolve_endpoint.py` (test precedents confirmed during VALIDATE).
5. **Next step for a fresh agent:** confirm WS0(b) merge status (see Sequencing Note); on "ENTER EXECUTE MODE", implement per the Implementation Checklist above in order (backend schema → backend endpoint → frontend client/types → frontend UI section → empty-state + tooltip copy), running the per-section test gates from Verification Evidence / Validate Contract as each section completes. AC-WS1-3 stays a documented known-gap until WS0 is live on prod.

---

PHASE_COMPLETE: VALIDATE — validate-contract written. Proceed to EXECUTE.
