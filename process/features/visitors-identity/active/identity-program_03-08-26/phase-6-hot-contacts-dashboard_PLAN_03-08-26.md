---
name: plan:identity-program-phase-6-hot-contacts-dashboard
description: "Identity honesty program — Phase 6: hot-contacts dashboard view ('N of your M contacts active this week')"
date: 03-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: phase-6
---

# Phase 6 — Hot-Contacts Dashboard

**Program:** identity-program
**Umbrella plan:** process/features/visitors-identity/active/identity-program_03-08-26/identity-program-umbrella_PLAN_03-08-26.md
**Phase status:** 🟩 EXECUTE COMPLETE (05-08-26) — EVL pending
**Report destination:** process/features/visitors-identity/active/identity-program_03-08-26/phase-6-hot-contacts-dashboard_REPORT_03-08-26.md

---

## Purpose

Give the customer a single view answering "how many of my imported contacts are active, and
which ones" — e.g. "12 of your 500 imported contacts viewed pricing this week" — without manually
cross-referencing their imported list against visitor traffic. This is the final phase of the
named-traffic factory: it surfaces the value created by Phases 4 (import) and 5 (promotion sweep)
by summarizing existing per-visitor rollup data (`visitor_aggregator.py`, `EnrichmentProfile`,
`CampaignTouchpoint` timestamps) into one dashboard feed.

**Naming note (VALIDATE finding, applied 03-08-26):** the SPEC's illustrative prose ("how many of
my known contacts are active") uses the word "known" colloquially, but this product already has a
distinct, shipped **"Known contacts"** feature (`apps/api/models/known_contact.py`,
`apps/api/routers/known_contacts.py`, `Settings → Known contacts`, the "Known" badge/filter on
`apps/web/src/app/dashboard/visitors/page.tsx`) — a CRM/customer-list blind-index EXCLUSION list,
unrelated to Phase 4's imported-contact-as-phantom-visitor mechanism. All UI copy, widget titles,
and API field/route naming for this phase MUST say **"imported contacts"**, never "known
contacts", to avoid colliding with that existing feature's terminology. This does not change the
underlying design — it is a naming-only correction, and it does not require editing the SPEC
(which is locked and only illustrative-prose here, not machine-checked terminology).

---

## Entry Gate

- Phase 4 exit gate passed: imported contacts (phantom Visitor rows) exist to count. **CONFIRMED at PLAN-SUPPLEMENT 05-08-26** — Phase 4 EXECUTE + EVL complete, `Visitor.is_imported_contact` live on disk.
- Phase 5 exit gate passed: promotion-sweep-verified contacts exist to distinguish "active" from merely-imported. **CONFIRMED at PLAN-SUPPLEMENT 05-08-26** — Phase 5 EXECUTE + EVL complete (code-complete; the 4 Hybrid integration gates remain Docker-gated known-gaps, same class as Phases 1-4 — this does not block Phase 6, whose activity data flows through the ordinary `_save_identified` merge path regardless of whether the sweep flag is ON).

---

## Blast Radius

- New: dashboard query/service — **REQUIRED (VALIDATE inner-PVL finding, applied 05-08-26):** a
  NEW dedicated file (e.g. `apps/api/services/hot_contacts.py`) and a NEW dedicated
  router/endpoint file — computes "N of M imported contacts with recent activity" using existing
  rollup data. This is no longer a hedged "prefer" — see the route-collision guardrail below for
  why.
  **Explicit guardrail (VALIDATE finding, applied 03-08-26):** do NOT implement this by editing
  `apps/api/routers/dashboard.py`'s `get_overview()` aggregate query (the block around line 91,
  `func.count().filter(Visitor.identity_status == "identified")`) — that region is Phase 1's
  owned reconciliation surface per the umbrella's shared-file partition
  (`dashboard.py:91` is explicitly listed as Phase 1's). Phase 6 must add a genuinely separate
  query/endpoint, not extend that shared aggregate, even though Phase 1 will have already landed
  by the time Phase 6 executes — this keeps the umbrella's blast-radius partition auditable and
  avoids growing an already-shared query with imported-contact-specific joins.
  **Route-collision guardrail (VALIDATE inner-PVL finding, applied 05-08-26 — mechanical, grep-verified):**
  `apps/api/routers/contacts.py` (Phase 4) already registers, in this order:
  `GET /{site_id}/contacts` → `GET /{site_id}/contacts/{visitor_id}` (line 143) →
  `GET /{site_id}/contacts-count`. If Phase 6's new endpoint is added to this SAME router as
  `GET /{site_id}/contacts/hot`, FastAPI matches routes in registration order — a route added
  AFTER `GET /{site_id}/contacts/{visitor_id}` will NEVER be reached; every request to
  `.../contacts/hot` will instead be swallowed by `get_imported_contact` with `visitor_id="hot"`
  and silently 404 (no import-time or unit-test error — this is a pure runtime routing bug). If
  execute-agent chooses to extend `contacts.py` rather than create a new dedicated router file,
  the new route MUST be registered BEFORE the `/{site_id}/contacts/{visitor_id}` route (line 143)
  in that file. The safer default remains the NEW dedicated router file named above, which avoids
  this class of bug entirely — that is now the required approach unless RESEARCH (Step A1)
  documents a concrete reason to extend `contacts.py` instead, in which case the ordering
  constraint above is mandatory and must be verified by a route-order-aware test or explicit
  manual check before EXECUTE closes this section.
- New: `GET /{site_id}/contacts/hot` (or an equivalently-named new dashboard endpoint — never a
  literal `/known-contacts/*` path, which is already owned by the existing Known Contacts feature)
  — returns count + list of active imported contacts. **Must use the same site-ownership
  verification dependency as sibling routers** (`verify_site_access` from `apps.api.dependencies`,
  the pattern used by `apps/api/routers/known_contacts.py`), not an ad-hoc
  `Site.user_id == user.id` filter alone — this keeps the "unknown/foreign site_id returns 404"
  multi-tenancy guardrail consistent with the rest of the API (per `process/context/all-context.md`
  Multi-tenancy convention). **Mechanically confirmed at inner-PVL 05-08-26:**
  `apps.api.dependencies.verify_site_access(db, site_id, user) -> Site` exists with exactly this
  signature (404-not-403, `Site.user_id == user.id` filter) — Step B4 is directly implementable
  as written, no further research needed on this point.
- Frontend: new dashboard view/widget (exact page location TBD by research — confirm whether
  `apps/web/src/app/dashboard/visitors/page.tsx` already has "hot"/recency sorting to reuse per
  Phase H research open question #3, or whether new UI is needed). CONFIRMED at VALIDATE: the page
  already has a general `last_seen` sort option (`sortBy` state, near the sort `<Select>` block)
  but no "N of M imported contacts active" summary widget — Step A1's research question is
  legitimately still open (whether to build a new widget vs. extend the existing sort/filter UI)
  and is correctly deferred to Phase 6's own RESEARCH step, not resolved here.
- Read-only reuse of `visitor_aggregator.py` rollups, `EnrichmentProfile`, `CampaignTouchpoint.opened_at`/`clicked_at` — no modification to Phase 1's or Phase 4's owned functions in `identity_resolver.py`/`visitor_aggregator.py`.
- New test: `tests/integration/test_hot_contacts.py`.
- **New test (VALIDATE inner-PVL, added 05-08-26):** `tests/unit/test_hot_contacts_query.py` —
  structural/compiled-SQL test (mirrors Phase 4's D8 pattern in
  `tests/unit/test_imported_contact_filter.py`) proving the query's JOIN/predicate shape without
  requiring a live database. See Step D1a and the Validate Contract test-gates table below.

**Does NOT touch:** any phase's core resolution/import/personalization logic, and does NOT touch
Phase 1's owned `dashboard.py:91` region — this phase is read-only aggregation on top of data
other phases already produce, added as a genuinely separate query/endpoint.

---

## Implementation Checklist

### Step A — Confirm existing dashboard capability

- [x] A1. **(RESOLVED at EXECUTE 05-08-26 — new widget on the existing `/dashboard/contacts` page, Phase 4's own surface; the Visitors page's `last_seen` sort is a general traffic sort, not an imported-contact summary, so it was not extended.)** Research: does `apps/web/src/app/dashboard/visitors/page.tsx` already have "hot"/recency sorting or filtering that can be reused (Phase H research open question #3, unresolved)? If yes, extend it; if no, build new. (VALIDATE confirmed: a general `last_seen` sort exists, but no dedicated "N of M" summary widget — this question is about the SUMMARY WIDGET, not the general sort, and remains open.)
- [x] A2. **(CONFIRMED at EXECUTE 05-08-26 — activity read from the merged child's `Visitor.last_seen`; phantom columns unused.)** Research: confirm exact `Visitor`/rollup column names available for "recent activity" (Phase H research open question #4, unresolved) — e.g. `last_seen` (CONFIRMED at VALIDATE: `Visitor.last_seen: Mapped[datetime]`, non-nullable, exists today at `apps/api/models/visitor.py:25`), page-visit counts.
- [x] A3. **(RESOLVED at PLAN-SUPPLEMENT 05-08-26)** Phase 4 and Phase 5 are now EXECUTED and EVL-green (`phase-4-contact-import_REPORT_03-08-26.md`, `phase-5-promotion-sweep_REPORT_03-08-26.md`). `Visitor.is_imported_contact` is live on disk (`apps/api/models/visitor.py:84`, non-nullable, default False). Entry Gate is satisfied — Step A no longer blocks.
- [x] A4. **(RE-CONFIRMED at EXECUTE 05-08-26 — no drift: `has_merged_child` predicate and `is_imported_contact` unchanged; `alembic heads` = `e9d2a4c71f68`, single head, no new migration.)** **(New, PLAN-SUPPLEMENT-added 05-08-26)** Confirm at RESEARCH time (cheap re-check, not a re-derivation) that no further drift has landed on `apps/api/models/visitor.py`, `apps/api/services/agent_visitor_filters.py`, or `apps/api/services/promotion_sweep_runner.py` since this supplement (05-08-26) — this program's worktree has repeatedly seen concurrent sessions land migrations/edits mid-phase (see Phase 4/5 reports). **CONFIRMED at inner-PVL 05-08-26: no drift found** — `agent_visitor_filters.py`'s `has_merged_child` EXISTS predicate and `visitor.py`'s `is_imported_contact` column both match the Phase 4/5 report descriptions exactly, byte-for-byte against the join predicate shape (canonical_visitor_id / site_id / identity_status == "merged").

### Step B — Query + endpoint

- [x] B1. **(DONE — `apps/api/services/hot_contacts.py::activity_last_seen_subquery`, correlated `MAX(child.last_seen)` scalar subquery, no JOIN fan-out possible.)** **(REWRITTEN at PLAN-SUPPLEMENT 05-08-26 — pointer-resolution query, supersedes the original single-table form)** The original `COUNT(*) WHERE Visitor.is_imported_contact AND Visitor.last_seen > ...` form is WRONG and must not be built: it reads `last_seen`/activity columns off the PHANTOM row, but Phase 4's confirmed merge semantics (see `phase-4-contact-import_REPORT_03-08-26.md` §"What Was Done — Step C" and `phase-5-promotion-sweep_REPORT_03-08-26.md` §A2/C1a) put all real activity (pageviews, `last_seen`, `pages_visited`) on a SEPARATE click-derived `Visitor` row with `identity_status="merged"` and `canonical_visitor_id` pointing AT the phantom — the phantom's own `last_seen`/`total_pageviews` never change after a merge. "Hot" must therefore be defined via a LEFT JOIN (or correlated EXISTS + subselect) from the phantom to its merged child, mirroring the exact join shape already proven correct and tested in `agent_visitor_filters.py::human_only_visitor_filter()`'s `has_merged_child` EXISTS (`merged_child.canonical_visitor_id == Visitor.visitor_id AND merged_child.site_id == Visitor.site_id AND merged_child.identity_status == "merged"`) — reuse that join predicate shape, do not invent a new one. Concretely: `SELECT phantom.*, merged_child.last_seen AS activity_last_seen FROM visitors phantom LEFT JOIN visitors merged_child ON merged_child.canonical_visitor_id = phantom.visitor_id AND merged_child.site_id = phantom.site_id AND merged_child.identity_status = 'merged' WHERE phantom.is_imported_contact AND phantom.site_id = :site_id`; "active this week" = `merged_child.last_seen IS NOT NULL AND merged_child.last_seen > now() - interval '7 days'` (or the confirmed activity-window definition). Denominator ("of M") = `COUNT(*) WHERE phantom.is_imported_contact AND phantom.site_id = :site_id` (no join needed — every imported contact counts toward M regardless of activity). Numerator ("N") = count of phantoms whose joined `merged_child` satisfies the activity-window condition above.
  **Multi-merged-child correctness fix (VALIDATE inner-PVL finding, applied 05-08-26, MANDATORY):**
  a single phantom can legitimately acquire MORE THAN ONE merged child over time — e.g. the same
  real contact visits from a work laptop and a phone before either session identifies by email;
  each distinct pre-identification `visitor_id` that later resolves to the phantom's email
  independently becomes its own `identity_status="merged"` row pointing at the SAME phantom (see
  `identity_resolver.py`'s `_save_identified` email-dedup branch, lines ~832-859 — nothing there
  prevents a second, third, etc. click-derived row from merging onto an already-canonical
  phantom). The literal SQL sketched above is a plain LEFT JOIN: if a phantom has 2+ matching
  merged children, that JOIN produces 2+ result rows for the SAME phantom, and a naive `COUNT(*)`
  or unindexed row iteration over the joined result will double- (or triple-) count that single
  contact in "N". The query MUST resolve to exactly one row per phantom before counting — use
  either (a) a correlated scalar subquery selecting `MAX(merged_child.last_seen)` per phantom
  (no JOIN fan-out possible), or (b) `GROUP BY phantom.visitor_id, phantom.site_id` with
  `MAX(merged_child.last_seen)` in the SELECT list, then filter/count on the aggregated value.
  Do NOT execute the literal ungrouped LEFT JOIN shown above as final production SQL — it is
  illustrative of the join predicate only, not the counting-safe form. See Step D1's added
  fixture scenario below, which is the proving test for this fix.
- [x] B2. **(DONE — `GET /{site_id}/contacts/hot` returns `active_count` / `total_count` / `window_days` / `contacts[]` with plaintext email+name to the owner.)** Endpoint returns both the count and the list of active contacts (name, email, last activity timestamp). **PII handling (VALIDATE-clarified, applied 03-08-26):** follow the existing convention used by `IdentifiedVisitor`-shaped dashboard responses (`apps/api/schemas/visitors.py:32-33`) — the site owner sees their own contact's real plaintext email/name in the dashboard response (this is the owner's own uploaded data, same as every other visitor list response today); do NOT mask the email in the API/UI response. `mask_email()` (`apps/api/services/pii.py`) is reserved for structlog log lines only (per `email_sender.py`'s usage pattern) — if this endpoint logs anything containing an email, mask it there, but the response payload itself stays plaintext, consistent with the rest of the Visitors dashboard.
- [x] B3. **(DONE — `activity.is_not(None)` + window predicate on the correlated value; a never-merged phantom is structurally excluded.)** **(REWRITTEN at PLAN-SUPPLEMENT 05-08-26)** Exclude rows still purely phantom (no merged child row at all, i.e. `merged_child.visitor_id IS NULL` in the B1 LEFT JOIN, or no row satisfying the activity-window predicate) from the "active" numerator — a phantom is only "active" through its resolved merged-child activity, never through its own dormant columns. This subsumes the original wording ("never clicked/visited") — it is now precisely "no merged child row with recent activity," matching the pointer semantics above. Apply the same GROUP-BY/correlated-subquery counting-safe form required by B1's multi-merged-child fix.
- [x] B4. **(DONE — `verify_site_access(db, site_id, user)` in `apps/api/routers/hot_contacts.py`.)** **(New, VALIDATE-added)** New endpoint must depend on `verify_site_access` (`apps.api.dependencies`) for the site-ownership check, matching the sibling pattern in `apps/api/routers/known_contacts.py` — not a bespoke `Site.user_id == user.id` filter written inline.

### Step C — Frontend view

- [x] C1. **(DONE — summary card on `apps/web/src/app/dashboard/contacts/page.tsx`, copy says "imported contacts".)** Add or extend a dashboard widget/page showing "N of your M **imported** contacts active this week" (see Naming note above — never say "known contacts" in UI copy) with a drill-down list.
- [ ] C2. **(KNOWN-GAP — Agent-Probe deferred: no running API/Postgres in this sandbox, same Docker-gated class as Phases 1/4/5.)** Agent-Probe visual check confirming the view renders correctly and the count matches the underlying data.

### Step D — Tests

- [x] D1. **(DONE — `tests/integration/test_hot_contacts.py`, incl. `test_count_multi_merged_child_phantom_exactly_once`; collects clean, unrun (Docker known-gap).)** Integration test on the underlying query: correct N/M counts given a fixture set of imported contacts with varying activity recency (SPEC AC13). **(VALIDATE inner-PVL addition, 05-08-26, MANDATORY):** must include a fixture scenario for a single phantom with TWO merged children (one recently active, one stale) and assert it is counted exactly ONCE in "N", using the most-recent qualifying activity timestamp — this is the proving test for the B1/B3 multi-merged-child counting-safe fix above.
- [x] D1a. **(DONE — `tests/unit/test_hot_contacts_query.py`, 9 tests, GREEN; mutation-checked against the naive LEFT JOIN form.)** **(New, VALIDATE inner-PVL addition, 05-08-26)** Add `tests/unit/test_hot_contacts_query.py` — a structural/compiled-SQL test asserting the hot-contacts query's JOIN/predicate shape (mirrors Phase 4's D8 pattern in `tests/unit/test_imported_contact_filter.py`: assert on `str(query.compile(...))` or the SQLAlchemy construct, not on live rows). This is required because `tests/integration/test_hot_contacts.py` needs a live Postgres (this program's established Docker-gated known-gap class, per Phases 1/4/5) and is not runnable in this sandbox — the structural test gives EXECUTE a real, Fully-Automated, sandbox-runnable gate proving the query's correlation/predicate shape (including the GROUP BY / correlated-subquery counting-safe form from B1) before the row-level Hybrid gate can even be attempted.
- [ ] D2. **(KNOWN-GAP — same deferral as C2.)** Agent-Probe check on the new dashboard view rendering correctly with real-shaped data (SPEC AC13).
- [x] D3. **(DONE — `TestHotContactsTenantIsolation`, 4 tests incl. 404-not-403 and a live route-shadowing proof; Docker known-gap, unrun.)** **(New, VALIDATE-added)** Integration test asserting cross-tenant isolation: a second site/user's imported contacts never appear in this site's "N of M" count or list (mirrors the existing `Site.user_id == user.id` scoping test pattern referenced by SPEC AC18 for Phase 4's import isolation) — SPEC AC13 does not name this explicitly, but the umbrella's hard safety constraint ("Every imported contact... remains scoped to Site.user_id == user.id — no cross-tenant visibility") applies to every phase touching imported-contact data, including this read-only dashboard.

---

## Exit Gate

```bash
.venv/bin/python3.11 -m pytest tests/unit/test_hot_contacts_query.py -q
.venv/bin/python3.11 -m pytest tests/integration/test_hot_contacts.py -q
# Expected: unit gate 0 failures (runs in this sandbox now); integration gate 0 failures,
# correct N/M counts across fixture scenarios (incl. multi-merged-child dedup), cross-tenant
# isolation proven — integration gate is Docker-gated (known-gap in this sandbox, see contract)
```

- SPEC AC13 has a passing proving test (Hybrid tier: integration query test + Agent-Probe visual check, per SPEC's stated strategy), backed by a new Fully-Automated structural companion test (D1a) that is actually runnable pre-Docker.
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Phase 4 and/or Phase 5 exit gates not yet passed (no data to summarize).
- If Step A finds the activity-window/rollup columns are materially different from assumed, block briefly to re-research rather than guessing at column names.

---

## Phase Loop Progress

- [x] 1. RESEARCH — research-agent: prior phase reports read (Phases 4, 5); confirm existing dashboard hot/recency capability; confirm rollup column names
- [x] 2. INNOVATE — innovate-agent: approach decided (AC13 already scoped in SPEC as Hybrid — confirm/refine query + UI approach)
- [x] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated (see Inner Loop Refresh Note, 05-08-26 — B1/B3 query-design rewrite)
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written (inner-pvl, 05-08-26 — see Validate Contract section below)
- [x] 5. EXECUTE — all checklist items done; per-section test gates run and green (or gaps documented)
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.**

---

## Touchpoints

- New hot-contacts query/service (exact file TBD by research; NOT `apps/api/routers/dashboard.py`'s `get_overview()` — see Blast Radius guardrail)
- New/extended dashboard endpoint — depends on `verify_site_access` (see Step B4); if extending `apps/api/routers/contacts.py`, MUST register before the `/{site_id}/contacts/{visitor_id}` route (see Blast Radius route-collision guardrail)
- Frontend dashboard view (exact page TBD by research)
- `apps/api/services/visitor_aggregator.py` (read-only reuse)

---

## Public Contracts

- No change to existing dashboard/KPI counts from earlier phases — this is purely additive.
- No change to `is_emailable_identity()` or any resolution/import logic.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Hot-contacts query JOIN/predicate + counting-safe (GROUP BY/correlated-subquery) shape is structurally correct | Fully-Automated (structural, no DB) | AC13 |
| Dashboard shows correct N of M active-contacts count from fixture data, including multi-merged-child dedup | Hybrid (precondition: local Postgres+Redis via docker compose) | AC13 |
| Dashboard view renders correctly with real-shaped data | Agent-Probe | AC13 |
| Cross-tenant isolation: other site's imported contacts never leak into this site's count/list | Hybrid (precondition: local Postgres+Redis via docker compose) | Umbrella hard safety constraint (no cross-tenant visibility) |

Failing stub (example, Fully-Automated tier — structural query shape):
```
test("should resolve hot-contacts activity via canonical_visitor_id pointer with counting-safe aggregation", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: hot-contacts query structural shape (D1a)")
})
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-program_03-08-26/phase-6-hot-contacts-dashboard_PLAN_03-08-26.md`
- Last completed step: PVL (inner-pvl, 05-08-26) — validate-contract written, Gate: PASS
- Validate-contract status: written (PASS, 05-08-26, `generated-by: inner-pvl: phase-6`) — see Validate Contract section below; supersedes the 03-08-26 outer-pvl CONDITIONAL contract
- Supporting context files loaded: umbrella plan, SPEC, Phase 4 + Phase 5 plans/reports, live source (`agent_visitor_filters.py`, `identity_resolver.py`, `visitor.py`, `dependencies.py`, `dashboard.py`, `known_contacts.py`, `contacts.py`, `schemas/visitors.py`), `results.tsv`
- Next step: Spawn vc-research-agent for RESEARCH (Step 1) / vc-execute-agent for EXECUTE once Steps A1/A2/C1's remaining open research questions are confirmed at the top of EXECUTE (they do not block PVL, per SPEC AC13's Agent-Probe accommodation)

---

## Validate Contract

Status: PASS
Date: 05-08-26
date: 2026-08-05
generated-by: inner-pvl: phase-6
supersedes: 2026-08-03 (outer-pvl) — inner PVL has current evidence (Phase 4 + Phase 5 are now
EXECUTED and EVL-green on disk; this pass re-validates against their real, landed code instead of
design intent, per the 05-08-26 Inner Loop Refresh Note)

Parallel strategy: sequential
Rationale: single-phase plan, read-only aggregation surface, 0 high-risk classes beyond standard
multi-tenant PII scoping (no auth/billing/migration/API-contract-break/container/secrets
touchpoints); score 0-1/7 (no schema/API/auth surface newly added by THIS phase — endpoint is
new-additive not contract-breaking; blast radius < 5 files; single investigation direction) — a
single vc-validate-agent pass was sufficient; no fan-out signal.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC13 | Hot-contacts query JOIN/predicate resolves activity via the phantom→merged-child canonical_visitor_id pointer, using a counting-safe (GROUP BY / correlated-subquery) aggregation that never double-counts a phantom with 2+ merged children | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_hot_contacts_query.py -q` | B |
| AC13 | Dashboard computes correct N of M imported-contacts-active count from fixture data (real Postgres rows), including a phantom-with-2-merged-children scenario counted exactly once | Hybrid — precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis` | `.venv/bin/python3.11 -m pytest tests/integration/test_hot_contacts.py -k count -q` | D |
| AC13 | Dashboard view renders correctly with real-shaped data | Agent-Probe | Manual/agent visual check on the new widget against a seeded fixture site (per Step C2) | A |
| (umbrella hard safety constraint) | Cross-tenant isolation: no leakage of another site's imported contacts into this site's N/M | Hybrid — precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis` | `.venv/bin/python3.11 -m pytest tests/integration/test_hot_contacts.py -k tenant -q` | D |

gap-resolution legend:
- A — proven now (gate passes in this cycle) — N/A pre-EXECUTE; these are the gates EXECUTE must turn green.
- B — fixed in this plan (gate added by this plan's checklist, Step D1a, added at this inner-PVL pass)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue) — Docker unavailable in this sandbox, same pre-named known-gap class as every prior phase in this program (Phases 1, 4, 5)

Legacy line form (retained so existing validate-contract consumers still parse):
- hot-contacts query structural shape: Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_hot_contacts_query.py -q` | hybrid: n/a | agent-probe: n/a | known-gap: none
- hot-contacts count query (row-level): Fully-automated: n/a | hybrid: `.venv/bin/python3.11 -m pytest tests/integration/test_hot_contacts.py -k count -q` (precondition: local Postgres+Redis) | agent-probe: visual check per Step C2 | known-gap: Docker unavailable in this sandbox
- cross-tenant isolation: Fully-automated: n/a | hybrid: `.venv/bin/python3.11 -m pytest tests/integration/test_hot_contacts.py -k tenant -q` (test added by Step D3) | agent-probe: n/a | known-gap: Docker unavailable in this sandbox

Failing stub (Fully-Automated — hot-contacts query structural shape, Step D1a):
```
test("should resolve hot-contacts activity via canonical_visitor_id pointer with counting-safe aggregation", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: hot-contacts query structural shape (D1a)")
})
```

Failing stub (Hybrid, Docker-gated — hot-contacts count query, row-level, Step D1):
```
test("should compute correct N of M active-contacts count, counting a multi-merged-child phantom exactly once", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: hot-contacts count query (row-level, needs Postgres)")
})
```

Failing stub (Hybrid, Docker-gated — cross-tenant isolation, Step D3):
```
test("should never leak another site's imported contacts into this site's N of M count/list", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: hot-contacts cross-tenant isolation (needs Postgres)")
})
```

Dimension findings:
- Infra fit: PASS — no container/infra/runtime surfaces touched; new query + endpoint + frontend widget only. Re-confirmed at inner-PVL: no drift on this dimension since 03-08-26.
- Test coverage: CONCERN (resolved at this inner-PVL pass) — the outer-pvl contract's test-gates table classified the AC13 count-query test as "Fully-Automated" even though its proving test lives in `tests/integration/test_hot_contacts.py`, which requires a live PostgreSQL/Redis per this repo's own test-runner routing (`process/context/tests/all-tests.md`) — every OTHER phase in this program (1, 4, 5) correctly classifies its `tests/integration/*.py` DB-dependent gates as Hybrid with a documented Docker precondition/known-gap, never Fully-Automated. Resolved by: (1) reclassifying both `tests/integration/test_hot_contacts.py` gates (count-query, cross-tenant isolation) to Hybrid tier with an explicit Docker precondition and known-gap, matching program-wide convention; (2) adding a NEW Fully-Automated structural/compiled-SQL companion test (Step D1a, `tests/unit/test_hot_contacts_query.py`, mirrors Phase 4's D8 pattern) so the query's join/predicate/counting-safe shape has a real, sandbox-runnable green gate before EXECUTE closes — this satisfies the net-gate rule that developed behavior must have at least one Fully-Automated or Hybrid proving gate, not Known-Gap alone.
- Breaking changes: PASS — purely additive; no schema change in this phase (reads Phase 4's column, now confirmed live on disk); no existing endpoint/contract modified; Public Contracts section confirmed accurate against `is_emailable_identity()` (re-verified unchanged, still 3 params, at `apps/api/services/identity_classification.py`).
- Security surface: PASS — re-confirmed at inner-PVL: `verify_site_access` dependency exists with the exact signature the plan assumes (`db, site_id, user -> Site`, 404-not-403, `Site.user_id == user.id` filter); PII response convention (plaintext to owner) matches `schemas/visitors.py`'s existing pattern; no new auth/secret/trust-boundary surface; all queries are parameterized SQLAlchemy ORM constructs (no injection surface). The two CONCERNs raised at the 03-08-26 outer-pvl pass (missing explicit `verify_site_access` requirement, ambiguous PII masking) remain resolved by the existing Step B2/B4 plan text — no regression found.

Section findings (Layer 2):
- Section A — Confirm existing dashboard capability: PASS. Step A3's entry-gate dependency is now
  CONFIRMED satisfied (Phase 4/5 landed and EVL-green). Step A4's drift re-check is CONFIRMED
  clean at this inner-PVL pass — `agent_visitor_filters.py`'s `has_merged_child` predicate and
  `visitor.py`'s `is_imported_contact` column match the Phase 4/5 report descriptions exactly.
  Step A1's UI-widget research question remains legitimately open (no regression, correctly
  deferred to RESEARCH).
- Section B — Query + endpoint: CONCERN (resolved at this inner-PVL pass). Mechanical
  feasibility: the B1 join predicate shape is mechanically verified correct against real code —
  `has_merged_child`'s EXISTS predicate in `agent_visitor_filters.py` and the merge-write path in
  `identity_resolver.py`'s `_save_identified` (canonical.visitor_id set to the PHANTOM's
  visitor_id, confirmed at the exact cited line range) match the join direction B1 describes
  exactly. New conflict found and fixed: (1) a phantom can acquire 2+ merged children (multi-device
  real visits), and the plan's literal LEFT JOIN sketch would double-count such a phantom in a
  naive `COUNT(*)` — fixed by requiring a GROUP BY/correlated-subquery counting-safe form (B1/B3
  amendment) plus a proving fixture scenario (D1 amendment); (2) if the new endpoint is added to
  the existing `apps/api/routers/contacts.py` (Phase 4) rather than a new dedicated router file,
  it will be silently shadowed by the pre-existing `/{site_id}/contacts/{visitor_id}` route
  (registered earlier, line 143) — grep-confirmed against the live file — fixed by strengthening
  the dedicated-new-router-file guidance from "prefer" to "required unless ordering constraint is
  explicitly satisfied", with the exact ordering rule spelled out. Highest-risk edit: the
  multi-merged-child counting bug, because it would silently inflate the customer-facing "N" count
  with no test failure signal unless the new D1 fixture scenario is present — mitigated by making
  that fixture scenario mandatory in this plan.
- Section C — Frontend view: PASS. No new findings this pass; naming guidance (imported contacts,
  never "known contacts") remains correctly applied; frontend page location remains legitimately
  TBD by RESEARCH, accommodated by SPEC AC13's Agent-Probe tier.
- Section D — Tests: CONCERN (resolved at this inner-PVL pass). Gap found: no test proving the
  multi-merged-child counting-safe fix — resolved by amending D1 with an explicit fixture
  scenario. Gap found: the AC13 count-query and cross-tenant-isolation gates had no
  sandbox-runnable Fully-Automated companion, unlike every prior phase's D8-style structural
  test — resolved by adding Step D1a.

Open gaps:
- **(Resolved 05-08-26)** Phase 4's `Visitor.is_imported_contact` column and Phase 5's
  promotion-sweep-verified data now exist on disk — Step A3/A4 confirm no drift.
- Exact frontend page location for the new widget remains "TBD by research" (Step A1) — this is a
  legitimate open research question, not a plan defect; SPEC AC13's Agent-Probe tier accommodates
  it.
- **Docker known-gap (pre-named, program-wide, not new to Phase 6):** the two
  `tests/integration/test_hot_contacts.py` Hybrid gates (row-level N/M count incl.
  multi-merged-child dedup; cross-tenant isolation) cannot run in this sandbox (no Docker) — same
  known-gap class documented at every prior phase in this program (Phases 1, 4, 5). Not blocking;
  EXECUTE must write these tests and confirm they collect clean (`--collect-only`), matching the
  established pattern.

What this coverage does NOT prove:
- The Fully-Automated structural test (D1a) proves the query's JOIN/predicate/aggregation SHAPE is
  correct against compiled SQL / SQLAlchemy construct inspection; it does NOT prove correct
  arithmetic against real row data — that requires the Hybrid row-level test (D1), which is
  Docker-gated and unrun in this sandbox.
- The Agent-Probe visual check proves the widget renders plausibly against one seeded scenario; it
  does NOT prove performance under a large imported-contact list (5,000/site cap scenario is not
  load-tested here) or exhaustive activity-window boundary conditions (e.g. exactly-7-days-ago edge
  case) — those are residual gaps not required by SPEC AC13's stated strategy and are not blocking.
- The cross-tenant isolation test (Step D3) proves the query/endpoint scopes correctly for the
  fixtures it constructs, once Docker is available to run it; it does NOT prove the frontend never
  displays cached cross-site data from a prior session (a client-side cache-key concern outside
  this phase's blast radius). It is currently unrun in this sandbox (Docker known-gap).
- Neither the structural nor the row-level test proves the route-collision guardrail is actually
  respected — that depends on execute-agent following the Blast Radius instruction (new dedicated
  router file, or correct registration order if extending `contacts.py`). No automated gate
  currently asserts FastAPI route resolution order; this remains an execute-agent-instruction-level
  mitigation, not a test-proven one.

Gate: PASS (0 FAILs; 2 CONCERNs found this pass — both resolved via plan-text fixes: multi-merged-child
counting-safe rewrite [B1/B3/D1] and route-collision guardrail [Blast Radius/Touchpoints], plus a new
Fully-Automated structural test gate [D1a] added to close the vacuous-green risk on the row-level Hybrid
gates. Remaining residuals are pre-named, program-wide Docker known-gaps [gap-resolution D], matching
every prior phase in this program — none left as unresolved CONCERNs.)
Accepted by: session (autonomous, inner-PVL pass run per orchestrator request; consistent with the
umbrella's Autonomous Execution Rules — "CONDITIONAL/PASS net gate: proceed autonomously, fixes applied
in-flight, gaps on record"; all concerns found this pass were fixed in-flight via plan-text edits and
new test-gate rows, not left as bare execute-agent-only instructions)

---

## Autonomous Goal Block

```
SESSION GOAL: identity-program Phase 6 — hot-contacts dashboard ("N of your M imported contacts active this week")
Charter + umbrella plan: process/features/visitors-identity/active/identity-program_03-08-26/identity-program-umbrella_PLAN_03-08-26.md
Autonomy: per umbrella's Autonomous Execution Rules — agent self-decides at V5 gates; CONDITIONAL proceeds with fixes applied in-flight and gaps on record; BLOCKED documents to backlog and continues.
Hard stop conditions / safety constraints:
- No auto-send; this phase sends no email at all (read-only dashboard) — N/A but inherited from umbrella.
- Every imported contact stays scoped to Site.user_id == user.id — no cross-tenant visibility (see Step D3 test gate).
- Do not extend apps/api/routers/dashboard.py's get_overview() shared aggregate (Phase 1's owned dashboard.py:91 region) — add a separate query/endpoint.
- Do not use "known contacts" in any UI copy or API naming for this phase — say "imported contacts" (naming collision with the existing Known Contacts feature).
- If extending apps/api/routers/contacts.py instead of a new dedicated router file, the new route MUST be registered before GET /{site_id}/contacts/{visitor_id} to avoid silent route shadowing.
- Entry Gate: Phases 4 and 5 exit gates must be confirmed passed (is_imported_contact column live) before EXECUTE begins — CONFIRMED satisfied as of 05-08-26.
Next phase: EXECUTE for this plan, after RESEARCH (Step 1) confirms Step A1 open question (frontend widget location).
Validate contract: inline in this plan file, section "## Validate Contract" above (Gate: PASS, generated-by: inner-pvl: phase-6, 05-08-26).
Execute start: fully-auto commands: `.venv/bin/python3.11 -m pytest tests/unit/test_hot_contacts_query.py -q` (once written) then `.venv/bin/python3.11 -m pytest tests/integration/test_hot_contacts.py -q` (Docker precondition) | e2e spec: none (Agent-Probe visual check per Step C2, no Playwright spec required by SPEC AC13) | probe scenario: seeded dashboard render check | high-risk pack: no
```

---

## Inner Loop Refresh Note

Date: 2026-08-05

**Trigger:** Phases 4 (contact import) and 5 (promotion sweep) are now EXECUTED and EVL-green.
This is the first PLAN-SUPPLEMENT pass for Phase 6 informed by their real implementation
(as opposed to the outer-PVL pass on 03-08-26, which validated against SPEC/design intent only,
before any of Phase 4/5's code existed).

**Findings baked into this plan:**

1. **Central query-design correction (Step B1/B3 rewritten).** The original single-table query
   (`COUNT(*) WHERE Visitor.is_imported_contact AND Visitor.last_seen > ...`) is structurally
   wrong. Confirmed by both Phase 4's and Phase 5's execution reports: a real visitor's later
   click does NOT update the phantom imported-contact row — it creates or resolves a SEPARATE
   click-derived `Visitor` row with `identity_status="merged"` and `canonical_visitor_id`
   pointing at the phantom; the phantom's own `last_seen`/`total_pageviews` never change. Phase 6
   must resolve activity through this pointer (phantom LEFT JOIN merged-child-by-canonical_visitor_id),
   reusing the exact join predicate shape already implemented and tested in
   `apps/api/services/agent_visitor_filters.py::human_only_visitor_filter()`'s `has_merged_child`
   EXISTS subquery (confirmed on disk 05-08-26).
2. **Entry Gate is now satisfied.** `Visitor.is_imported_contact` is live on disk
   (`apps/api/models/visitor.py:84`). Step A3 is resolved; a new lightweight Step A4 replaces it
   (cheap drift re-check at RESEARCH time, given this program's history of concurrent
   mid-session edits).
3. **Promotion-sweep flag state does not block this phase.** `promotion_sweep_enabled` defaults
   OFF (confirmed in Phase 5 report) — but activity accrual on the click-derived `merged` row
   happens through the ordinary `_save_identified` merge path regardless of the sweep flag; the
   sweep only accelerates identification of `utm`-sourced fresh rows. The dashboard query must
   not assume the sweep is running.
4. **Metric exclusion predicate confirmed reusable, not reinventable.** The EXISTS-subquery form
   in `agent_visitor_filters.py` (D8-tested, `has_merged_child`) is the canonical pattern for
   "does this phantom have a merged child" — Phase 6's B1 query reuses this join shape rather
   than inventing a new one.
5. **Environment facts refreshed:** full UNFILTERED unit lane baseline is 1629 passed / 0
   failed (per `results.tsv` row 8, EVL phase-5-fix-cycle-1, independent tester confirm).
   Alembic head is `e9d2a4c71f68` (single head, no drift since Phase 5 EXECUTE) — no new
   migration is expected for Phase 6 (read-only dashboard on existing columns); RESEARCH should
   re-confirm via `alembic -c apps/api/alembic.ini heads` before EXECUTE per this program's
   established concurrent-drift pattern. No Docker in this environment — the integration test
   (Step D1/D3) is written but unrun until a Docker-capable environment is available, matching
   the pre-named known-gap class carried by every prior phase in this program.

**PVL re-run required:** yes — the B1/B3 query-design rewrite is a material change to the plan's
core mechanism and must go through a fresh V1-V7 validate pass before EXECUTE. The existing
`## Validate Contract` (Status: CONDITIONAL, 03-08-26, `generated-by: outer-pvl`) is now stale
relative to this note's date and must not be treated as current for EXECUTE routing.

**PVL re-run completed 05-08-26 (inner-pvl: phase-6) — see `## Validate Contract` above.** Gate:
PASS. Two additional CONCERNs were found and resolved during this re-run beyond the query-design
rewrite already baked in above: (1) a multi-merged-child double-count risk in the B1/B3 query
(fixed via a mandatory GROUP BY/correlated-subquery counting-safe form + D1 fixture scenario),
and (2) a route-registration-order collision risk if the new endpoint is added to the existing
`apps/api/routers/contacts.py` (fixed via an explicit ordering guardrail, with a new dedicated
router file as the now-required default). The AC13 test-gates table was also corrected: the
`tests/integration/test_hot_contacts.py` gates were reclassified from Fully-Automated to Hybrid
(Docker precondition), matching every other phase in this program, and a new Fully-Automated
structural companion test (Step D1a) was added so a real sandbox-runnable gate exists before
EXECUTE closes this phase.
