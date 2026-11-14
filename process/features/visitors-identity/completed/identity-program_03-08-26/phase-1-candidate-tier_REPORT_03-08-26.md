---
phase: phase-1-candidate-tier
date: 2026-08-04
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/identity-program_03-08-26/phase-1-candidate-tier_PLAN_03-08-26.md
---

# Phase 1 — Candidate Tier + Status Reconciliation — EXECUTE report

**TL;DR** — All 22 checklist items implemented. Every runnable gate is green (99 + 26 unit
tests, `tsc --noEmit` clean, migration renders clean offline both directions at the verified
live head `a7d419e6c052`). Full unit lane 833 passed / 0 failed. Two gaps, both pre-existing
environment limits, both already named in the validate-contract: the integration lane has no
Postgres (Docker absent) and AC4's visual check has no Playwright auth harness. One
implementation deviation on A5, forced by a real regression risk found during EXECUTE.

## What Was Done

**Step A — candidate tier at the source**

- `identity_classification.py`: new `GRAPH_CANDIDATE_PROVIDERS` frozenset
  (`rb2b`/`leadpipe`/`capturify`/`beam_identity_network`), `is_graph_candidate_provider()`,
  and `is_verified_identity(status)` (only `"identified"` is verified). `is_emailable_identity`
  untouched — still exactly 3 parameters (pinned by a signature test).
- `identity_resolver.py::_save_identified`: `identity_status` now branches —
  `"candidate"` for graph providers, `"identified"` otherwise. `confidence_score` still written
  unconditionally (A1a verified, constructor untouched).
- **A1b** svid_reconcile: new `_origin_is_verified()` helper reads the ORIGIN visitor's
  `identity_status`; a non-`identified` origin short-circuits the reconcile branch and falls
  through to Check 1.
- **A1c** fingerprint_match: added `Visitor.identity_status == "identified"` to the existing
  join's WHERE clause.
- **A1a/A4c** beam_identity_network reclassified into the candidate set (closes the
  cross-tenant laundering path).
- **A5** `_save_identified` conflict handler now UPSERTS (overwrites email/name/geo/provider/
  confidence and resets `do_not_email = False`) instead of returning the stale row. See
  Deviations.

**Step B — call-site reconciliation (4 real sites, per-site decision table below)**

| Site | Decision | Implementation |
|---|---|---|
| `services/kpi.py` | Candidates are their OWN funnel number. `identified` keeps meaning CONFIRMED. `high_intent`/`acted_high` stay confirmed-only (counting guesses there would reintroduce the overstatement this program removes). | new `candidates` count + response key |
| `services/timeseries.py` | Candidates get their own daily series point, never folded into `identified`. | new `candidate_case` SUM + `candidates` in `build_series`/response |
| `routers/dashboard.py` | Separate per-site conditional aggregate. | new `.filter(... == "candidate")` count → `VisitorStatsResponse.candidates` |
| `routers/visitors_helpers.py` | Separate count on the per-site stats payload. | new conditional aggregate + `candidates` key |
| `resolution_runner.py:130` (B1) | Candidates STAY sweep-eligible so a later deterministic signal can upgrade them, but their pass is `deterministic_only` — no graph, no paid waterfall. | `identity_status.in_(("anonymous","candidate"))` + `resolve(deterministic_only=...)` |
| `visitors.py` per-row Identify (B2) | **Candidate short-circuits** with a distinct message pointing at confirm/reject. Chosen over the plan's "carve-out and re-resolve" hedge because re-resolution can only produce another guess, which can never promote (A1) — so a Retry would spend provider budget for a status that cannot change. Reject→re-resolve is the correct flow and now works (A5). | new `elif` branch |
| `visitors.py` + `visitor_aggregator.py:353,410-412` revive SQL (B3) | **NO CHANGE** — confirmed targets `"unresolvable"` only. | none |
| `visitors.py` manual identify (B5) | **NO CHANGE** — human confirmation is deterministic. | none |

**Step C — endpoints**

- `POST /{site_id}/{visitor_id}/reject-candidate` → `anonymous` + `do_not_email=True` on the
  existing row (row kept for audit, not hard-deleted).
- `POST /{site_id}/{visitor_id}/confirm-candidate` → `identified` + stamps the new
  `IdentifiedVisitor.confirmed_at`.
- Both gated by `_verify_site_access` (Site.user_id == user.id) via a shared
  `_load_candidate_visitor()`; cross-tenant/unknown → 404, non-candidate → 400.
- New model column `IdentifiedVisitor.confirmed_at` (nullable) + migration
  `b1c9e7f24d83_add_identified_visitor_confirmed_at.py`, chained off the **live-verified** head
  `a7d419e6c052` (single head, re-checked at EXECUTE start and again at gate time).

**Step D — frontend**

- `api-types.ts`: `confidence_score?: number | null` on `Visitor`.
- `status-badge.tsx`: `candidate → warning` tone (mirrors the company-level caution pill).
- List page: candidate branch in `renderIdentity()`.
  **D2 placement decision:** the badge lives in `renderIdentity()` (the status column), NOT as an
  extra pill in the name cluster, because "candidate" IS a status value rather than an orthogonal
  attribute like Known / Company-level. The confidence percentage lives in that badge's tooltip so
  the row stays scannable.
- Detail page: same badge + a caution panel with **Confirm this is them** / **Not them** buttons
  wired to new `api.confirmCandidate` / `api.rejectCandidate` client methods.
- **AC5 gap found and fixed beyond the checklist:** the LIST endpoint never selected
  `confidence_score` at all, so the badge would have had nothing to show. Added it to the
  `id_map` projection (and its 3 unpack sites).

## What Was Skipped or Deferred

- Nothing from the checklist. All 22 items implemented.
- The integration test file was WRITTEN but could not be RUN (no Postgres).

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| Exit Gate 1 | `pytest tests/unit/test_rb2b_scoring.py tests/unit/test_identity_classification.py tests/unit/test_identity_resolver_parallel.py -q` | **99 passed** |
| Exit Gate 1b (added) | `pytest tests/unit/test_candidate_call_sites.py tests/unit/test_agent_origin_exclusion.py -q` | **26 passed** (AC10 guardrail regression intact) |
| Full unit lane | `pytest tests/unit -m unit -q` | **833 passed, 2 skipped, 0 failed** |
| Exit Gate 2 (integration) | `pytest tests/integration -k "candidate or reject or confirm" -q` | **NOT RUN — known-gap.** Whole integration lane errors at collection with `Connect call failed 127.0.0.1:5433`; `docker` is not installed in this environment. Not a code failure. |
| Exit Gate 3 (frontend) | `cd apps/web && npx tsc --noEmit` | **0 errors** |
| Exit Gate 4 (migration) | `alembic heads` → `b1c9e7f24d83` single head; `upgrade a7d419e6c052:b1c9e7f24d83 --sql`; `downgrade b1c9e7f24d83:a7d419e6c052 --sql` | **both directions render clean.** Explicit `<from>:<to>` range used per the known `b7d3e9f1a4c2` offline-unsafe gotcha. **No live apply performed.** |
| AC4 Agent-Probe (badge visual) | Playwright / manual | **NOT RUN — repo-wide known-gap** (no Clerk auth harness). Pre-existing, not introduced here. |

New tests added: `tests/unit/test_rb2b_scoring.py` (12, first-ever RB2B coverage),
`tests/unit/test_candidate_call_sites.py` (8), +12 in
`test_identity_resolver_parallel.py`, +~20 in `test_identity_classification.py`,
`tests/integration/test_candidate_endpoints.py` (13, unrun).

## Plan Deviations

**A5 — ORM upsert instead of CORE `INSERT ... ON CONFLICT DO UPDATE`** (within-blast-radius,
same file, same semantics).

The plan specified copying `_upsert_beam_identity`'s CORE `pg_insert` pattern. Direct inspection
during EXECUTE found `identified_visitors` is registered with `before_insert`/`before_update`
PII-encryption listeners (`apps/api/services/pii_encryption_hooks.py:57`) that a CORE statement
bypasses — the exact caveat that file's own docstring calls out. Following the plan literally
would have silently stopped the `email_ciphertext` / `email_bidx` / `full_name_ciphertext`
dual-write on every identity row: a PII/security regression, not a style difference.

Implemented instead as an ORM update inside the existing `IntegrityError` handler — identical
observable semantics (same conflict key, overwrite-on-conflict, `do_not_email` reset, same
return value), with the encryption hooks preserved. The plan's Blockers section explicitly
licenses this ("the simplest correct fix … is preferred **unless research surfaces a real
regression risk during EXECUTE**"). Proven by two new unit tests.

**B2 — short-circuit rather than carve-out.** The plan left this open and required a documented
decision; see the Step B table above for the choice and rationale.

**Scope addition (not a deviation from intent):** `confidence_score` was missing from the LIST
endpoint's projection. AC5 could not have passed without adding it.

No hard-stop-class deviations. Hard constraints all honoured: `is_emailable_identity` still
takes exactly 3 params (signature-pinned by test); no score auto-promotes; no auto-send surface
touched; `campaign_sender.py` personalization untouched (Phase 2); decoration/`custom_args`
untouched (Phase 3).

## Test Infra Gaps Found

1. **No Docker / no Postgres on :5433** — the ENTIRE integration lane is uncollectable in this
   environment (32 collection errors, all `ConnectionRefused`, most in files unrelated to this
   phase). Blocks Exit Gate 2 and the live migration round-trip.
   Classification: `harness-drift` (environment), not `product-breakage`.
2. **No Playwright auth harness** — repo-wide, pre-existing, blocks AC4.
3. `tests/unit/test_agent_company_resolution.py::test_ac2_stat_counts_excludes_agent_rows` used a
   hand-built `SimpleNamespace` row that broke when a column was added to the aggregate. Fixture
   updated. Worth noting as a brittleness pattern: these fake-row fixtures must be updated
   whenever a conditional aggregate gains a label.

## Closeout Packet

- **Selected plan:** `process/features/visitors-identity/active/identity-program_03-08-26/phase-1-candidate-tier_PLAN_03-08-26.md`
- **Finished:** all 22 checklist items (A1–A5, B1–B6, C1–C4, D1–D5).
- **Verified:** candidate-tier assignment, all 3 laundering paths, A5 upsert, all 4 B4 call
  sites, the B1 deterministic-only sweep, frontend types, migration SQL both directions,
  AC10 agent-exclusion regression, full unit lane.
- **Still unverified:** endpoint runtime behaviour (C1–C4 integration), migration live
  round-trip, AC4 badge visual.
- **Classification: `Keep in active/testing`.** Code-complete and EVL-ready, but not
  `✅ VERIFIED` until the Docker-gated integration lane + migration round-trip run.
- **Follow-up stubs created:** none as separate files — the two gaps are already named in this
  plan's own validate-contract Open Gaps. Recommend UPDATE PROCESS register them in
  `process/features/visitors-identity/backlog/` alongside the existing deferred-gate notes.
- `CONTEXT_PARTIAL`: none.

## Forward Preview

**Test Infra Found**
- Unit lane: `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` (833 tests, ~4s). Shebang on
  `.venv/bin/pytest` is broken — always use `-m pytest`.
- Integration lane needs Postgres+Redis via `infra/docker-compose.yml`; unavailable here.
- Alembic offline validation MUST use an explicit `<from>:<to>` range.

**Blast Radius Changes**
- New alembic head: **`b1c9e7f24d83`** (was `a7d419e6c052`). Re-run `alembic heads` before any
  later migration — this repo has a documented history of concurrent head drift.
- New public helpers other phases should use: `is_verified_identity(status)` and
  `GRAPH_CANDIDATE_PROVIDERS` / `is_graph_candidate_provider(provider)`. Never duplicate a
  parallel literal-string provider list.
- New resolver kwarg: `IdentityResolver.resolve(..., deterministic_only=False)` and
  `_check_prior_signals(..., deterministic_only=False)`.
- Response shape additions (all additive, all defaulted): `candidates` on the KPI funnel,
  timeseries points, `VisitorStatsResponse`, and the per-site stats dict; `confidence_score` on
  the visitor LIST rows.
- **Any test that hand-builds a fake row for `_compute_visitor_stat_counts` or
  `compute_timeseries` must now include `candidates`.**

**Commands to Stay Green**
```
.venv/bin/python3.11 -m pytest tests/unit -m unit -q
cd apps/web && npx tsc --noEmit
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads
```

**Dependency Changes**
- None. No new packages.

**Explicit dependency flag for Phase 2's RESEARCH step (as the plan requires):** Phase 2's Fork 3
send-time guard reads `identity_status` at send time and therefore inherits correctness
automatically from this phase — **A1, A1a, A1b, A1c and A5 are ALL implemented**, so no separate
Phase 2 change is needed for the laundering paths. Phase 2 can also rely on
`IdentifiedVisitor.confirmed_at` existing (migration written, NOT yet applied to any real
database) for the SPEC AC17 mid-campaign cutover.
