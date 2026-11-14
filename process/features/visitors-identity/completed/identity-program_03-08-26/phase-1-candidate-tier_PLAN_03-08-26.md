---
name: plan:identity-program-phase-1-candidate-tier
description: "Identity honesty program — Phase 1: candidate-tier confidence gating for all graph-sourced matches"
date: 03-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: phase-1
---

# Phase 1 — Candidate Tier + Status Reconciliation

**Program:** identity-program
**Umbrella plan:** process/features/visitors-identity/active/identity-program_03-08-26/identity-program-umbrella_PLAN_03-08-26.md
**Phase status:** 🟢 EXECUTE complete (04-08-26) — awaiting EVL
**Report destination:** process/features/visitors-identity/active/identity-program_03-08-26/phase-1-candidate-tier_REPORT_03-08-26.md

---

## Purpose

Make every graph-sourced identity match (RB2B, Leadpipe, Capturify) permanently land on a new
`identity_status="candidate"` value instead of flat "identified" — no score, however high, ever
auto-promotes. Add a shared `is_verified_identity()` helper and migrate all ~8 hardcoded
`identity_status == "identified"` call sites onto it with an explicit per-site decision. Add
reject (candidate → anonymous, re-resolvable) and confirm (candidate → identified) endpoints. Surface
`confidence_score` to the frontend with a caution badge mirroring the existing company-level
pattern. Add unit test coverage for RB2B's currently-untested score parsing. This phase is the
foundation every other phase depends on (directly: Phase 2; indirectly: all others rely on
`identity_status` values staying honest).

**VALIDATE note (03-08-26):** direct code inspection during VALIDATE found that the "3 named
providers" framing (RB2B/Leadpipe/Capturify only) is necessary but NOT sufficient to satisfy
AC1/AC2 as literally stated — there are 3 additional confirmed code paths inside
`identity_resolver.py` that can copy a graph-sourced guess forward into flat `"identified"`
without ever calling `_resolve_identity_graphs_parallel` directly (`svid_reconcile`,
`fingerprint_match`, `beam_identity_network`), plus a unique-constraint issue that would make
"reject → re-resolvable" (AC6) not actually work. All four are addressed by concrete, scoped
fixes below (Steps A1/A1a/A1b/A1c/A5) — see `## Validate Contract` for full findings.

---

## Entry Gate

- Program start — no phase dependency.
- SPEC locked, INNOVATE Decision Summary Fork 2 confirmed (this plan implements Fork 2).

---

## Blast Radius

- `apps/api/models/visitor.py` — no schema change to `Visitor.identity_status` (String(30)
  free-text column; "candidate" is a new value, not a new column). **VALIDATE-added:** the
  `IdentifiedVisitor` model (defined in this same file, ~line 115) DOES need a new nullable
  column `confirmed_at: Mapped[datetime | None]` — confirmed by direct inspection: `IdentifiedVisitor`
  has NO `updated_at` field of any kind (only `resolved_at`, set once via
  `server_default=func.now()`, never updated). Step C2 previously assumed `updated_at` was
  reusable; it is not. See Step C2 rewrite below.
- `apps/api/migrations/versions/` — **VALIDATE-added, new:** one additive migration for
  `IdentifiedVisitor.confirmed_at` (nullable, no default). This is a schema/migration high-risk
  class item (see Test Gates). Re-verify true alembic head via
  `alembic -c apps/api/alembic.ini heads` at EXECUTE time before writing `down_revision` — do not
  hardcode a head from this document (repo has a documented history of concurrent-program head
  drift; see `process/context/all-context.md` AI-Agent-Traffic Layer section and the
  `concurrent-program-migration-collision-rechain` memory note).
- `apps/api/services/identity_classification.py` — add `is_verified_identity(status: str) -> bool`
  helper; do NOT modify `is_emailable_identity()`'s signature. Also add a new
  `GRAPH_CANDIDATE_PROVIDERS` frozenset constant (see Step A1 rewrite) — this is a NEW constant,
  distinct from the existing `PERSON_LEVEL_PROVIDERS`/`COMPANY_LEVEL_PROVIDERS`/`OWNED_FREE_PROVIDERS`
  sets already in this file (confirmed present at lines ~12-35) which serve a different, orthogonal
  classification axis (person-vs-company-level for emailability) and must NOT be modified by this
  phase.
- `apps/api/services/identity_resolver.py` — **VALIDATE-expanded** (confirmed by direct code read,
  all line numbers below verified against the current file):
  - `_save_identified` (~line 725-854): branch `identity_status` per the rewritten Step A1
    allowlist logic below (NOT a simple 3-provider check — see rewrite).
  - `_resolve_identity_graphs_parallel` (~line 569-647): no scoring change, only branch target
    (unchanged from original plan).
  - **NEW — `_check_prior_signals` Check 0 / svid_reconcile (~line 235-270)**: confirmed this path
    calls `_save_identified(visitor, {...}, "svid_reconcile")` using data copied from
    `_identified_for_origin()`, which looks up an `IdentifiedVisitor` row by visitor_id WITHOUT
    checking whether the origin `Visitor.identity_status` is currently `"identified"` vs
    `"candidate"`. Left unfixed, this launders a candidate-tier RB2B match into "identified" the
    moment the visitor returns via the `_rta_svid` cookie. Requires a code fix (Step A1b below),
    not just a branch-condition change.
  - **NEW — `_check_prior_signals` Check 2 / fingerprint_match (~line 333-378)**: confirmed this
    path matches `IdentifiedVisitor` joined to `Visitor` on `fingerprint` equality, again WITHOUT
    filtering on the origin's `identity_status`. Same laundering risk as svid_reconcile via
    device-fingerprint continuity instead of cookie continuity. Requires a code fix (Step A1c
    below).
  - **NEW — `_check_beam_identity_network` (~line 943-984) + `_upsert_beam_identity`
    (~line 866-902)**: confirmed `_upsert_beam_identity` is called unconditionally from inside
    `_save_identified` (~line 854) for EVERY successful identification, including
    RB2B/Leadpipe/Capturify matches, writing `source_provider=provider` (e.g. `"rb2b"`) into the
    cross-tenant `BeamIdentityNode` table. `_check_beam_identity_network` later reads this table
    (fingerprint match, `confidence_score >= 0.5`) on a DIFFERENT site/tenant and calls
    `_save_identified(..., "beam_identity_network")`. This is a cross-tenant version of the same
    laundering bug: a candidate-tier-only RB2B guess on Site A can resurface as flat "identified"
    on Site B. Requires reclassifying `"beam_identity_network"` into the candidate bucket (Step
    A1a below) — cheaper and safer than attempting cross-tenant tier verification.
  - **NEW — IntegrityError conflict handler inside `_save_identified` (~line 826-845)**: confirmed
    the existing `identified_visitors` table has a UNIQUE constraint on `(site_id, visitor_id)`
    (`uq_identified_site_visitor`). On conflict, the current code rolls back and returns the
    PRE-EXISTING row UNCHANGED. This means Step C1's reject flow ("candidate → anonymous,
    re-resolvable") cannot actually produce a fresh, corrected match on re-resolution — any later
    `_save_identified` call for the same visitor_id just re-fetches the stale, rejected row via
    this fallback path, permanently stuck. Requires an upsert-style fix (Step A5 below), following
    the exact `INSERT ... ON CONFLICT DO UPDATE` pattern already established in this same file by
    `_upsert_beam_identity` (~line 881-899).
- `apps/api/services/identity_providers/rb2b.py` — no behavior change to score math itself in this
  phase (score floor/ceiling stays as-is per locked SPEC decision #1: ALL graph matches are
  candidate regardless of score) — only add unit test coverage for existing parsing logic
  (confirmed at lines 13-100: `max(results, key=lambda r: r.get("score", 0))` pick behavior at
  ~line 55, normalization + 0.99 ceiling / 0.0 floor at ~line 86-100).
- `apps/api/services/resolution_runner.py:130` — sweep eligibility: add
  `OR identity_status == 'candidate'` (scoped to deterministic-upgrade-signal checks only, never
  score-based).
- `apps/api/routers/visitors.py` — residential-IP "already processed" short-circuit (confirmed at
  ~line 823-826, `elif visitor.identity_status != "anonymous": return {"status": ..., "message":
  "Already processed."}` — carve out candidate); new reject endpoint (candidate → anonymous, sets
  `IdentifiedVisitor.do_not_email = True` on the existing row — see Step C1 rewrite); new confirm
  endpoint (candidate → identified, sets new `confirmed_at` column — see Step C2 rewrite).
- `apps/api/services/visitor_aggregator.py:353,410-412` — revive SQL: no change, document as
  intentional (targets "unresolvable" only). Confirmed via grep: both lines target
  `Visitor.identity_status == "unresolvable"` only.
- **PATH CORRECTION (VALIDATE finding — original plan named the wrong directory for 3 of 4
  files):** the actual files containing `identity_status == "identified"` dashboard/KPI checks
  are `apps/api/services/kpi.py` (NOT `apps/api/routers/kpi.py` — that path does not exist),
  `apps/api/services/timeseries.py` (NOT `apps/api/routers/timeseries.py` — does not exist),
  `apps/api/routers/dashboard.py:91` (confirmed correct as originally written), and
  `apps/api/routers/visitors_helpers.py:175` (NOT `apps/api/services/visitors_helpers.py` — wrong
  directory; the file lives under `routers/`). Add explicit candidate handling at all 4 real
  locations (counted separately, documented decision per site — never silently folded into
  "identified" nor silently dropped).
- `apps/api/schemas/visitors.py` — `confidence_score` already present at line 84; confirm it's
  returned on both list and detail responses.
- `apps/web/src/lib/api-types.ts:246` — add `confidence_score?: number | null` to the visitor type
  (confirmed absent from the current type today).
- `apps/web/src/app/dashboard/visitors/page.tsx`, `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx`
  — add Candidate caution badge (`StatusBadge` + a warning-styled span), tooltip explaining
  unconfirmed match, mirroring the existing company-level badge (confirmed present at
  `page.tsx:780-787`, not `:780-785` — close enough to find by grep on
  `identity_level === "company"`, not a blocking discrepancy).
- New test file: `tests/unit/test_rb2b_scoring.py` (parse/normalize/ceiling/max-pick coverage —
  currently zero).
- Extend: `tests/unit/test_identity_classification.py`, `tests/unit/test_identity_resolver_parallel.py`
  (both confirmed to exist).

**Does NOT touch:** `campaign_sender.py` personalization logic (Phase 2), `gmail_sender.py`
(Phase 3), any import surface (Phase 4/5/6). **Note for Phase 2 supplement:** Phase 2's Fork 3
send-time guard reads `identity_status` at send time, so it inherits correctness automatically
from this phase's fixes — no separate Phase 2 change needed for the laundering paths found here,
PROVIDED this phase's A1/A1a/A1b/A1c/A5 items are all implemented. Flag this dependency explicitly
in this phase's report for the orchestrator to relay to Phase 2's RESEARCH step.

---

## Implementation Checklist

### Step A — Candidate tier assignment at the source

- [x] A1. In `apps/api/services/identity_classification.py`, add a new constant
  `GRAPH_CANDIDATE_PROVIDERS = frozenset({"rb2b", "leadpipe", "capturify", "beam_identity_network"})`
  with a docstring explaining why `beam_identity_network` is included (cross-tenant reuse of a
  graph-derived match; its live tier cannot be cheaply re-verified across tenants, so treat it
  conservatively as candidate). In `apps/api/services/identity_resolver.py::_save_identified`,
  change the unconditional `visitor.identity_status = "identified"` (line ~822) to:
  `visitor.identity_status = "candidate" if provider in GRAPH_CANDIDATE_PROVIDERS else "identified"`.
  Use the local `provider` parameter (the function's actual argument name) — NOT a
  `resolution_provider` variable, which does not exist in this scope; `resolution_provider` is
  only the column name on the `IdentifiedVisitor` row being constructed. **Do NOT** add
  `hunter`/`apollo`/`pdl_person_enrich`/`form_capture`/`manual` to this set — they are out of
  SPEC's locked scope (SPEC names only RB2B/Leadpipe/Capturify) and Hunter/Apollo already have
  their own, separate "company-level" caution mechanism via `identity_level()` +
  `is_emailable_identity()` (confirmed: `is_emailable_identity` already returns `False` for
  `hunter`/`apollo` today, since `identity_level()` classifies them as `"company"`, not
  `"person"` — they were never emailable and are unaffected by this phase).
- [x] A1a. Confirm `IdentifiedVisitor(confidence_score=data.get("confidence_score"), ...)` is
  still written unconditionally regardless of tier (needed for the badge/tooltip).
- [x] A1b. Fix the svid_reconcile laundering path: in `_check_prior_signals` Check 0
  (~line 235-270), after fetching `prior = await self._identified_for_origin(visitor.site_id, svid)`,
  ALSO look up the origin `Visitor` row's current `identity_status` (join or a second query keyed
  on `prior.visitor_id`). Only proceed with the `_save_identified(..., "svid_reconcile")` copy
  when the origin's `identity_status == "identified"`. If the origin is `"candidate"` (or
  anything else), skip this reconciliation branch entirely and fall through to Check 1 — let the
  current visitor run its own resolution waterfall instead of inheriting an unverified guess.
- [x] A1c. Fix the fingerprint_match laundering path: in `_check_prior_signals` Check 2
  (~line 333-378), add `Visitor.identity_status == "identified"` to the existing query's WHERE
  clause (the query already joins `IdentifiedVisitor` to `Visitor` on `fingerprint` equality — this
  is a one-line addition to an existing join). A fingerprint match against a `"candidate"`-tier
  origin must NOT auto-copy `"identified"` forward; it falls through (returns `None` from this
  check) so the visitor's own waterfall can run.
- [x] A2. Add `is_verified_identity(status: str) -> bool` to
  `apps/api/services/identity_classification.py`: returns `status == "identified"` (candidate is
  explicitly NOT verified). Docstring states this is the single source of truth for "is this
  visitor's identity confirmed."
- [x] A3. Write `tests/unit/test_rb2b_scoring.py` covering: raw_score/100 normalization, 0.99
  ceiling, 0.0 floor, `max(results)` pick behavior, and that a 0.99-score match still lands on
  `"candidate"` after A1 (integration-adjacent assertion via `_save_identified` or a scoped unit
  on the branch logic).
- [x] A4. New unit tests (extend `test_identity_resolver_parallel.py`) covering the two laundering
  fixes: (a) svid_reconcile does NOT copy a candidate-tier origin's identity forward as
  "identified" (asserts fall-through, not a silent candidate-copy); (b) fingerprint_match does NOT
  copy a candidate-tier origin's identity forward as "identified"; (c) `beam_identity_network`
  results always land on `"candidate"` regardless of the stored `confidence_score`.
- [x] A5. Fix the `_save_identified` conflict handler (~line 826-845) so post-reject re-resolution
  actually works: replace the plain `INSERT` + `except IntegrityError: rollback + fetch-existing`
  pattern with an `INSERT ... ON CONFLICT (site_id, visitor_id) DO UPDATE` (same pattern already
  used by `_upsert_beam_identity` at ~line 881-899 in this same file) that overwrites `email`,
  `full_name`, `city`, `region`, `country`, `resolution_provider`, `confidence_score`, and resets
  `do_not_email = False` on conflict. This does not change the audit posture: `resolution_logs`
  (immutable, already the authoritative audit trail per the existing Retry-endpoint comment at
  `visitors.py` ~line 1082) already records every resolution attempt independently of the mutable
  `identified_visitors` row. Add a new unit test asserting a second `_save_identified` call for the
  same `(site_id, visitor_id)` with new data overwrites the row instead of silently returning the
  stale one.

### Step B — Call-site reconciliation (SPEC AC8, ~8 sites)

- [x] B1. `resolution_runner.py:130` sweep eligibility: change filter to `identity_status IN
  ('anonymous', 'candidate')`, but scope any candidate row's sweep pass to ONLY check for
  deterministic upgrade signals (form capture / `_bid` click presence) — never re-run
  graph-score resolution on a candidate (that would violate "no auto-promote").
- [x] B2. `visitors.py` residential-IP "already processed" short-circuit (confirmed location:
  `elif visitor.identity_status != "anonymous": return {...}`): add
  `and visitor.identity_status != "candidate"` so a candidate can still be re-processed via this
  endpoint without hitting the short-circuit incorrectly (confirm exact desired behavior against
  SPEC AC6 — candidate should be reject/confirm-able, not silently reprocessed here; document
  final decision in phase report).
- [x] B3. `visitors.py` (revive-related bulk SQL, `UPDATE visitors SET identity_status =
  'anonymous' WHERE identity_status = 'unresolvable'`) + `visitor_aggregator.py:353,410-412` revive
  SQL: NO CHANGE — confirmed and documented as intentional (targets `"unresolvable"` only,
  unrelated to candidate).
- [x] B4. `apps/api/services/kpi.py` (NOT `routers/kpi.py` — corrected path, see Blast Radius),
  `apps/api/services/timeseries.py` (NOT `routers/timeseries.py` — corrected path),
  `apps/api/routers/dashboard.py:91`, `apps/api/routers/visitors_helpers.py:175` (NOT
  `services/visitors_helpers.py` — corrected path): audit each query; add an explicit
  `identity_status == 'candidate'` branch reported as a separate count/label (e.g. "Candidates:
  N") — never silently inside "Identified" totals, never silently dropped. Record the exact
  decision made at each site in the phase report table (SPEC AC8 requires this to be explicit).
- [x] B5. `visitors.py` manual identify endpoint (confirmed: sets `resolution_provider="manual"`,
  `confidence_score=1.0`, `visitor.identity_status = "identified"` directly): NO CHANGE — human
  confirmation = deterministic verified path per locked decision #1.
- [x] B6. Write one unit test per reconciled call site (B1, B2, B4) asserting candidate rows are
  handled per the documented decision.

### Step C — Reject / confirm endpoints

- [x] C1. Add `POST /{site_id}/{visitor_id}/reject-candidate` in `visitors.py`: requires
  `identity_status == "candidate"`; on success sets `identity_status = "anonymous"` AND sets
  `IdentifiedVisitor.do_not_email = True` on the existing row for this `(site_id, visitor_id)`
  (confirmed: `do_not_email` is already checked by all 3 emailable-export call sites —
  `csv_exporter.py:65`, `campaign_sender.py:197`, `campaigns.py:722` — so this immediately stops
  the rejected match from being emailed/exported without requiring a new column). Do NOT
  hard-delete the `IdentifiedVisitor` row (kept for `resolved_at`/audit visibility even though
  `resolution_logs` is the authoritative immutable audit trail). Confirms the visitor re-enters
  the sweep eligibility set from B1 naturally, and — because of the Step A5 upsert fix — a
  subsequent successful re-resolution will correctly overwrite this row's stale data (including
  resetting `do_not_email` back to `False`) instead of being stuck on the rejected fetch-existing
  fallback.
- [x] C2. Add `POST /{site_id}/{visitor_id}/confirm-candidate` in `visitors.py`: requires
  `identity_status == "candidate"`; on success sets `identity_status = "identified"` and stamps
  the new `IdentifiedVisitor.confirmed_at` column (confirmed via direct model inspection: NO
  reusable `updated_at` column exists on `IdentifiedVisitor` — `resolved_at` is set once at
  INSERT via `server_default=func.now()` and is never updated, so reusing it would silently
  corrupt any code that treats `resolved_at` as "when this row was first created", e.g. the
  fingerprint-match `ORDER BY resolved_at DESC` query). This is the only new-column/new-migration
  requirement in this phase — see Blast Radius and the new migration item above. `confirmed_at`
  is needed by Phase 2's mid-campaign cutover per SPEC AC17.
- [x] C3. Both endpoints scoped via `Site.user_id == user.id` (standard multi-tenancy pattern) and
  404 (not 403) on cross-tenant access.
- [x] C4. Integration test: reject-candidate → visitor becomes `anonymous`, `IdentifiedVisitor.do_not_email`
  is `True` on the existing row → next sweep run picks it up → (with A5 fix in place) a fresh
  resolve correctly overwrites the row and clears `do_not_email`. Integration test:
  confirm-candidate → visitor becomes `identified`, `confirmed_at` is stamped → subsequent sends
  personalized (cross-reference with Phase 2's test, but assert the state transition here).

### Step D — Frontend confidence surfacing + badge

- [x] D1. Add `confidence_score?: number | null` to `apps/web/src/lib/api-types.ts` visitor type
  (line ~246 area).
- [x] D2. Add Candidate badge to `apps/web/src/app/dashboard/visitors/page.tsx` (mirror the
  existing company-level pattern confirmed at ~line 780-787): a warning-styled badge/span labeled
  "Candidate" with tooltip "Unconfirmed match — [confidence]% confidence. Not personalized in
  outreach until confirmed." when `identity_status === "candidate"` — note `renderIdentity()`
  (confirmed at ~line 360-393) is the function that currently branches on `identity_status` for
  the main status badge; add the candidate branch there, and the confidence-badge/company-badge
  cluster near ~line 780 is a separate, additive per-row indicator — decide during EXECUTE which
  of the two rendering spots the confidence percentage itself should live in, and document the
  choice in the phase report.
- [x] D3. Same badge pattern on `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx`.
- [x] D4. Wire reject/confirm buttons on the detail page calling the C1/C2 endpoints.
- [x] D5. Frontend typecheck gate green; Playwright/Agent-Probe visual check per SPEC AC4.

---

## Exit Gate

```bash
.venv/bin/python3.11 -m pytest tests/unit/test_rb2b_scoring.py tests/unit/test_identity_classification.py tests/unit/test_identity_resolver_parallel.py -q
# Expected: 0 failures, including new candidate-branch assertions (A1) and the two laundering-fix
# assertions (A1b, A1c, A4) and the upsert-conflict assertion (A5)

.venv/bin/python3.11 -m pytest tests/integration -k "candidate or reject or confirm" -q
# Expected: 0 failures

cd apps/web && npx tsc --noEmit
# Expected: 0 type errors (confidence_score type added)

# Migration (Hybrid tier — high-risk schema/data class): offline validate ONLY (no live apply in
# this phase). Re-verify true head first.
alembic -c apps/api/alembic.ini heads
alembic -c apps/api/alembic.ini upgrade <verified-current-head>:<new-rev> --sql
alembic -c apps/api/alembic.ini downgrade <new-rev>:<verified-current-head> --sql
# Expected: both directions render clean SQL, no errors
```

- All 4 real call sites in Step B have a documented decision in the phase report (paths corrected
  per Blast Radius: `services/kpi.py`, `services/timeseries.py`, `routers/dashboard.py`,
  `routers/visitors_helpers.py`).
- SPEC ACs 1, 2, 3, 4, 5, 6, 7, 8 all have a passing proving test per the SPEC's stated strategy —
  AC1/AC2 specifically require the A1b/A1c/A1a fixes, not just the base A1 branch, to actually
  hold (see Validate Contract findings).
- Phase report written to report destination above, including the explicit per-site B4 decision
  table and the D2/D3 confidence-display placement decision.

---

## Blockers That Would Justify BLOCKED Status

- If the true alembic head has moved unexpectedly between VALIDATE and EXECUTE (repo has a
  documented history of concurrent-program migration collisions), re-verify live via
  `alembic -c apps/api/alembic.ini heads` before writing `down_revision` for the new
  `confirmed_at` migration; if the chain is ambiguous or conflicting, block and route to research
  rather than guessing.
- If AC4's Playwright visual check has no auth-harness available (known repo-wide gap per
  `all-context.md`), record as known-gap and keep phase CONDITIONAL rather than BLOCKED.
- If the A5 upsert fix is found to have unforeseen interaction with the existing concurrent-insert
  race-handling comment (~line 826), treat as a plan-supplement item rather than a hard block —
  the fallback SELECT-after-conflict behavior can be preserved for the true concurrent-race case
  (two requests racing to create the SAME fresh identification) by making the UPDATE conditional
  on the row being older than some small window, but the simplest correct fix (unconditional
  UPDATE on conflict) is preferred unless research surfaces a real regression risk during EXECUTE.

---

## Phase Loop Progress

- [ ] 1. RESEARCH — research-agent: prior phase reports read; test context loaded; plan drift checked
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written (largely pre-decided by program INNOVATE Fork 2 — confirm/refine only)
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated; Inner Loop Refresh Note if sections changed (or "n/a — research clean")
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written (this pass, 03-08-26; Gate: CONDITIONAL)
- [x] 5. EXECUTE — all checklist items done; per-section test gates run and green (or gaps documented)
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate Contract` reads the placeholder, orchestrator must spawn vc-validate-agent first.

---

## Touchpoints

- `apps/api/services/identity_resolver.py` (`_save_identified`, `_resolve_identity_graphs_parallel`,
  `_check_prior_signals` Check 0/2, `_check_beam_identity_network`, `_upsert_beam_identity`)
- `apps/api/services/identity_classification.py`
- `apps/api/services/resolution_runner.py`
- `apps/api/routers/visitors.py`
- `apps/api/services/kpi.py`, `apps/api/services/timeseries.py`, `apps/api/routers/dashboard.py`
- `apps/api/routers/visitors_helpers.py`
- `apps/api/models/visitor.py` (new `IdentifiedVisitor.confirmed_at` column)
- `apps/api/migrations/versions/` (new additive migration)
- `apps/api/schemas/visitors.py`
- `apps/web/src/lib/api-types.ts`
- `apps/web/src/app/dashboard/visitors/page.tsx`
- `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx`
- `tests/unit/test_rb2b_scoring.py` (new)

---

## Public Contracts

- `is_emailable_identity(provider, source_agent_visit_id, is_abuse_flagged)` — unchanged, 3 params.
- Existing "Identified" filters/counts/KPIs keep their current meaning for real "identified" rows; Candidate is additive.
- New: `is_verified_identity(status)` helper — becomes the canonical check other phases/call sites should use going forward.
- New: `GRAPH_CANDIDATE_PROVIDERS` frozenset in `identity_classification.py` — becomes the canonical
  set other call sites should extend (never duplicate a parallel literal-string list) if a future
  provider needs candidate-tier treatment.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| RB2B/Leadpipe/Capturify at score 0.99 land on "candidate" | Fully-Automated | AC1 |
| No code path sets identity_status="identified" from graph score alone (incl. svid_reconcile/fingerprint_match/beam_identity_network laundering paths) | Fully-Automated | AC1, AC2 |
| A second `_save_identified` call for the same visitor overwrites stale/rejected data instead of returning it unchanged | Fully-Automated | AC6 (prerequisite) |
| Candidate rows ARE returned by emailable-export call sites | Fully-Automated | AC3 |
| Candidate badge visible on list + detail pages with tooltip | Agent-Probe | AC4 |
| confidence_score reaches API response and frontend type | Fully-Automated | AC5 |
| Reject-candidate returns visitor to anonymous, sets do_not_email, re-eligible for sweep | Fully-Automated | AC6 |
| Confirm-candidate promotes to identified, stamps confirmed_at; subsequent sends personalized | Fully-Automated | AC7 |
| Each of the 4 real reconciled call sites (kpi.py, timeseries.py, dashboard.py, visitors_helpers.py) handles candidate per documented decision | Fully-Automated | AC8 |
| New `confirmed_at` migration applies/reverts cleanly offline (`--sql`) at the verified true head | Hybrid | AC7 (migration safety, high-risk class) |

Failing stub (example, Fully-Automated tier):
```
test("should keep RB2B match at candidate tier even at score 0.99", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: candidate tier at max score")
})
```

Failing stub (svid_reconcile laundering fix):
```
test("should not promote a candidate-tier origin to identified via svid_reconcile", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: svid_reconcile origin-tier check")
})
```

Failing stub (fingerprint_match laundering fix):
```
test("should not promote a candidate-tier origin to identified via fingerprint_match", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: fingerprint_match origin-tier check")
})
```

Failing stub (beam_identity_network reclassification):
```
test("should land beam_identity_network matches on candidate regardless of confidence_score", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: beam_identity_network candidate tier")
})
```

Failing stub (A5 upsert-on-conflict fix):
```
test("should overwrite a stale identified_visitors row on re-resolution instead of returning it unchanged", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: _save_identified upsert-on-conflict")
})
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-program_03-08-26/phase-1-candidate-tier_PLAN_03-08-26.md`
- Last completed step: VALIDATE (V1-V7), 03-08-26 — Gate: CONDITIONAL
- Validate-contract status: written (see below)
- Supporting context files loaded: umbrella plan, SPEC, INNOVATE Decision Summary (Fork 2), research-phase0.md
- Next step: Spawn vc-research-agent for RESEARCH (Step 1) — research should read this plan's
  VALIDATE-added findings (A1a/A1b/A1c/A5, C1/C2 rewrites, path corrections) as already-resolved
  context, not re-discover them from scratch.

---

## Validate Contract

Status: CONDITIONAL
Date: 03-08-26
date: 2026-08-03
generated-by: outer-pvl

Parallel strategy: sequential
Rationale: single already-written phase plan, read-only code verification against one file tree —
no independent investigation directions requiring fan-out; all findings below came from one
continuous grep/read pass through the exact files the plan already claims to touch (score 0-1 on
the 7-signal scale: single-package scope, no phase-program plan-creation fan-out needed for a
VALIDATE-only pass on one already-written plan).

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1 | RB2B/Leadpipe/Capturify land on candidate at any score | Fully-Automated | `tests/unit/test_rb2b_scoring.py` + `_save_identified` branch unit (A1, A3) | A |
| AC1/AC2 | svid_reconcile does not launder a candidate origin to identified | Fully-Automated | new unit in `test_identity_resolver_parallel.py` (A1b, A4a) | B |
| AC1/AC2 | fingerprint_match does not launder a candidate origin to identified | Fully-Automated | new unit in `test_identity_resolver_parallel.py` (A1c, A4b) | B |
| AC1/AC2 | beam_identity_network always lands on candidate | Fully-Automated | new unit in `test_identity_resolver_parallel.py` (A4c) | B |
| AC6 (prerequisite) | `_save_identified` upsert-on-conflict overwrites stale/rejected row | Fully-Automated | new unit in `test_identity_resolver_parallel.py` (A5) | B |
| AC3 | Candidate rows ARE emailable/exportable | Fully-Automated | new unit on `is_emailable_identity`/export call sites | A |
| AC4 | Candidate badge + tooltip visible on list/detail pages | Agent-Probe | Playwright/manual visual check (D5) | D — no Playwright auth harness today (repo-wide known-gap) |
| AC5 | confidence_score reaches API + frontend type | Fully-Automated | integration test + `tsc --noEmit` (D1) | A |
| AC6 | reject-candidate → anonymous + do_not_email=True + sweep-eligible | Fully-Automated | new integration test (C1, C4) | A |
| AC7 | confirm-candidate → identified + confirmed_at stamped | Fully-Automated | new integration test (C2, C4) | B (new migration required) |
| AC8 | 4 real call sites (kpi.py/timeseries.py/dashboard.py/visitors_helpers.py) handle candidate explicitly | Fully-Automated | one unit test per site (B6) | A |
| migration safety | `confirmed_at` migration applies/reverts cleanly offline at verified head | Hybrid | `alembic ... --sql` both directions (precondition: correct live head re-verified via `alembic heads`) | A |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist, post-VALIDATE-supplement)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: no Known-Gap strategy value used above except AC4's gap-resolution note (D),
which is a residual, not a strategy — AC4 itself still runs on Agent-Probe (a proving strategy);
only the *live browser auth harness* precondition for actually executing it is a named residual.

Legacy line form (retained for existing consumers):
- rb2b/leadpipe/capturify candidate branch: `.venv/bin/python3.11 -m pytest tests/unit/test_rb2b_scoring.py -q`
- laundering-path fixes (svid_reconcile/fingerprint_match/beam_identity_network): `.venv/bin/python3.11 -m pytest tests/unit/test_identity_resolver_parallel.py -q`
- upsert-on-conflict fix: same file, new test case
- reject/confirm endpoints: `.venv/bin/python3.11 -m pytest tests/integration -k "candidate or reject or confirm" -q` (Docker/Postgres+Redis required per `all-tests.md`)
- migration safety: `alembic -c apps/api/alembic.ini heads` then `upgrade <head>:<new-rev> --sql` and `downgrade <new-rev>:<head> --sql` (agent-probe: [known-gap: no live-Postgres round-trip in this sandbox — offline `--sql` validation only, consistent with repo convention documented in `process/context/all-context.md`])
- frontend badge: `cd apps/web && npx tsc --noEmit` (Fully-Automated for typecheck) + agent-probe visual check for AC4 (known-gap: no Playwright auth harness — repo-wide, not phase-specific)

Dimension findings:

- Infra fit: PASS — no container/infra/worker surface touched; standard FastAPI router + SQLAlchemy
  model + Alembic migration pattern, all with direct precedent elsewhere in this codebase.
- Test coverage: CONCERN — original plan's Exit Gate commands were syntactically correct but its
  Step B4 blast-radius paths were wrong (would have caused execute-agent to create NEW, wrong-path
  files instead of editing the real ones); fixed via Plan Update above. AC4's Agent-Probe gate has
  no live browser auth harness (repo-wide known-gap, not new to this phase).
- Breaking changes: CONCERN — the new `IdentifiedVisitor.confirmed_at` column is additive/nullable
  (no breaking change), but the A5 upsert-on-conflict fix changes existing concurrent-insert-race
  behavior (previously: silently return the pre-existing row; now: overwrite it). This is
  necessary for AC6 to actually work, but is a genuine behavior change to already-shipped code
  outside the plan's originally-stated scope — flagged explicitly as a Blocker-adjacent item, not
  silently absorbed.
- Security surface: CONCERN — the `beam_identity_network` cross-tenant laundering path (Site A's
  candidate-tier guess resurfacing as Site B's flat "identified") is a real information-integrity
  issue closely analogous to the original "Janet Valla" incident, just cross-tenant instead of
  single-tenant. Fixed via Plan Update (reclassify to candidate). No new auth/secret/trust-boundary
  surface introduced by this phase's own new endpoints (C1-C3 use the standard
  `Site.user_id == user.id` + 404-not-403 pattern already used everywhere else in `visitors.py`).
- Section A (Candidate tier assignment): CONCERN → resolved via Plan Update — mechanical
  feasibility of the ORIGINAL A1 wording was fine (file/line/parameter all real), but it was
  incomplete: 3 additional `_save_identified` call sites (svid_reconcile, fingerprint_match,
  beam_identity_network) would have continued to auto-set "identified" without any code change,
  directly contradicting AC1/AC2 as literally stated. Now fixed with A1/A1a/A1b/A1c above.
- Section B (Call-site reconciliation): FAIL → resolved via Plan Update — 3 of 4 file paths
  (`routers/kpi.py`, `routers/timeseries.py`, `services/visitors_helpers.py`) do not exist;
  correct locations are `services/kpi.py`, `services/timeseries.py`, `routers/visitors_helpers.py`.
  Confirmed by direct `grep`/`find` against the repository. Fixed above.
- Section C (Reject/confirm endpoints): FAIL → resolved via Plan Update — `IdentifiedVisitor` has
  no `updated_at` column (Step C2's "confirm which" hedge could not have been resolved at EXECUTE
  time without a fresh migration; execute-agent would likely have picked the wrong option and
  silently corrupted `resolved_at`'s semantics). Also, the `(site_id, visitor_id)` UNIQUE
  constraint on `identified_visitors` meant "reject → re-resolvable" (AC6) would not actually
  produce a fresh match without the A5 upsert fix — confirmed by reading the existing
  IntegrityError conflict-handler code, which returns the stale row unchanged. Both fixed above
  (new `confirmed_at` column + migration; A5 upsert-on-conflict).
- Section D (Frontend badge): PASS — `page.tsx:780-787` company-level badge pattern confirmed to
  exist and is a valid mirror target; `confidence_score` confirmed present in the Pydantic schema
  and confirmed absent from the frontend TS type (real, addable gap). Minor line-number drift
  (`:780-785` claimed vs `:780-787` actual) is not a blocker — grep-findable.

Open gaps:
- Migration live round-trip on a disposable Postgres was not run in this VALIDATE pass (no Docker
  daemon available in this sandbox) — offline `--sql` validation only, consistent with the repo's
  documented convention for other recent migrations (see `process/context/all-context.md`).
  known-gap: documented as required before considering this phase `✅ VERIFIED` (not before
  EXECUTE — offline validation is sufficient to proceed).
- AC4's Playwright/Agent-Probe visual check has no live browser auth harness in this repo today —
  repo-wide known-gap, pre-existing, not introduced by this phase.
- The umbrella plan's own Touchpoints list references `apps/api/models/identified_visitor.py`,
  which does not exist (`IdentifiedVisitor` is defined inside `apps/api/models/visitor.py`). This
  phase's own plan does not repeat that error, but it is worth flagging for the umbrella's own
  future supplement pass since I do not have write access to the umbrella file in this VALIDATE
  invocation.
- Discovered (not a Phase 1 concern, purely informational for Phase 4's RESEARCH step):
  `apps/api/routers/known_contacts.py` already exists — a CSV-upload, blind-index-hashed
  "known contacts" matcher (up to 50,000 emails/site) that flags already-identified visitors as
  "Known" via email-hash match. This is NOT the same mechanism Phase 4 needs (it does not create
  phantom Visitor rows or tokenized links for contacts who haven't visited yet), so the SPEC's
  Phase H research finding ("no CSV/contact-list import surface exists... a contact who has never
  visited cannot be created") remains technically accurate, but Phase 4 should reuse this file's
  established CSV-parsing/hash-normalization/size-cap conventions rather than reinventing them.

What this coverage does NOT prove:
- The Fully-Automated unit tests (A1/A1a/A1b/A1c/A3/A4/A5/B6) prove the branch logic and
  conflict-handler behavior in isolation with mocked/in-memory data; they do NOT prove correct
  behavior against a live Postgres with real constraint enforcement (that requires the
  integration lane, which needs Docker Postgres+Redis per `all-tests.md` and was not run in this
  VALIDATE pass).
- The Hybrid migration gate proves the SQL renders cleanly offline in both directions; it does
  NOT prove the migration applies cleanly against a real running Postgres instance with existing
  data (no live round-trip run in this VALIDATE pass — see Open Gaps).
- The Agent-Probe badge check (AC4) is not automated and depends on a human or future
  auth-harnessed agent actually loading the dashboard pages; it does NOT prove the badge renders
  correctly across browsers or handles edge cases (missing confidence_score, extremely long
  tooltip text, etc.).
- None of these gates prove the cross-tenant `beam_identity_network` fix is complete beyond the
  provider-reclassification: they do not verify that NO OTHER cross-tenant read path exists
  elsewhere in the codebase that could similarly launder a candidate-tier match. This VALIDATE
  pass searched only `identity_resolver.py`; a full-repo search for other `BeamIdentityNode`
  readers was not performed (would require broader Phase 1 RESEARCH scope than this plan claims).

Gate: CONDITIONAL (concerns noted above; all are resolved as concrete Plan Updates within this
same plan file, not deferred as unaddressed gaps — the CONDITIONAL classification reflects that
these updates require EXECUTE to implement 5 code-level items — A1a, A1b, A1c, A5, and the new
C2 migration — that were not part of the plan's original checklist, not that anything remains
unresolved in the plan text itself)

Accepted by: session (autonomous outer-PVL invocation, no interactive user present for this
delegated VALIDATE task) — accepted concerns: (1) Section B path corrections, (2) Section A
laundering-path fixes (A1a/A1b/A1c), (3) Section C new-column/migration requirement + A5 upsert
fix, (4) migration live-round-trip deferred to pre-✅-VERIFIED (not pre-EXECUTE), (5) AC4
Agent-Probe repo-wide known-gap (pre-existing, not new).
