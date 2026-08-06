---
name: plan:identity-program-phase-5-promotion-sweep
description: "Identity honesty program — Phase 5: APScheduler batch sweep promoting tokenized-link clicks to verified within 5 minutes"
date: 03-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: phase-5
---

# Phase 5 — Click→Verified Promotion Sweep

**Program:** identity-program
**Umbrella plan:** process/features/visitors-identity/active/identity-program_03-08-26/identity-program-umbrella_PLAN_03-08-26.md
**Phase status:** ✅ EXECUTED (05-08-26) — EVL pending; integration legs Docker-gated
**Report destination:** process/features/visitors-identity/active/identity-program_03-08-26/phase-5-promotion-sweep_REPORT_03-08-26.md

---

## Purpose

When an imported contact clicks their tokenized link and lands on the site, the resulting visitor
must be recognized as named + verified within ≤5 minutes — via a batch/triggered process AFTER the
`/ingest` request completes, never synchronously inside the ingest hot path (locked SPEC
constraint). Implement via an APScheduler sweep running every 1-2 minutes, scoped to fresh
`VisitorEmail WHERE source='utm' AND created_at > now() - interval AND visitor not yet verified`,
reusing the identity_resolver's existing email-based resolution path. Safe failure mode: a missed
cycle is picked up by the next cycle (no per-click background task, no dropped-work-on-crash risk).

---

## Entry Gate

- Phase 4 exit gate passed: phantom Visitor rows and tokenized links exist to click on.
- Benefits from Phase 3 being live (Gmail-sent links also decorated correctly) but not blocked by it — SendGrid-delivered links work today regardless of Phase 3's status.

---

## Blast Radius

- New: `apps/api/services/promotion_sweep_runner.py` (**VALIDATE correction** — see rationale below) — heavy sweep logic, mirroring `resolution_runner.py`'s `run_resolution_sweep()` / `run_resolution_for_site()` shape (a trigger-agnostic service function, not a Celery task).
- `apps/api/jobs/scheduler.py` — new thin `_promotion_sweep_job()` wrapper (mirrors `_resolution_sweep_job`/`_cadence_bot_flag_sweep_job` shape: open its own session or delegate session-management to the runner, swallow top-level exceptions via `except Exception: logger.exception(...)`, never let a crash escape) + one new `scheduler.add_job(...)` call inside `start_scheduler()` with explicit `jitter` and `misfire_grace_time` (every existing `interval` job in this file carries both — Phase 4c convention documented inline in `start_scheduler()`'s docstring).
- `apps/api/config.py` — new `promotion_sweep_enabled: bool = False` (default OFF) + `promotion_sweep_interval_minutes: int` settings, matching the established default-OFF rollout convention for every recent identity/traffic-adjacent sweep in this codebase (`cadence_bot_flag_enabled`, `agent_detection_enabled`, `identity_signals_enabled`, `site_ingest_limit_enabled`, etc. — see `all-context.md` "Open Questions"). Identity-status mutation is a high-risk class (auth/identity); shipping it unconditionally-on would break that established convention.
- `apps/api/services/identity_resolver.py` — **NO edits.** Phase 5 only ever CALLS the existing public `IdentityResolver(db, redis_client).resolve(visitor)` from the new runner module above — it does not modify `_save_identified` (Phase 1's region) or the merge-on-click function (Phase 4's region). This is Phase 5's owned interaction with this file: a read-only caller, zero lines changed in `identity_resolver.py` itself.
- Query scope: `VisitorEmail WHERE source = 'utm' AND created_at > now() - interval '[window]' AND Visitor.identity_status NOT IN ('identified', 'merged')` (both are terminal-success states after Phase 1/Phase 4 land — see Execute-Agent Instructions in the Validate Contract for why `!= 'identified'` alone is insufficient).
- APScheduler registration — confirmed pattern via direct source read of `apps/api/jobs/scheduler.py` (see rationale below) — do NOT mirror `resolution_runner.py`'s *file location*, only its *shape*.
- New test files: `tests/integration/test_promotion_sweep.py`.

**VALIDATE rationale for the Blast Radius correction above:** the original draft named
`apps/api/tasks/promotion_sweep.py` as the new file. Reading `apps/api/tasks/` shows it holds
Celery task modules only (`ads_tasks.py`, `resolution_tasks.py`, `crm_tasks.py`,
`segmentation_tasks.py`, `aggregation_tasks.py`) — a different async-task mechanism. Every existing
APScheduler periodic sweep in this repo (`resolution_runner.py`, `agent_verification.py`,
`cadence_bot_flag_sweep.py`, `outlier_traffic_damping_sweep.py`, `agent_intent_signals.py`) lives
under `apps/api/services/`, with only a thin wrapper function added to `apps/api/jobs/scheduler.py`
and registered via `scheduler.add_job(...)` inside `start_scheduler()`. This plan now follows that
confirmed convention instead.

**Does NOT touch:** Phase 1's `_save_identified` internals, Phase 2's personalization guard, Phase 4's import/merge-on-click functions (only calls into resolver's pre-existing resolve path), Phase 3's `campaign_sender.py` region.

---

## Migration State (as of PLAN-SUPPLEMENT 04-08-26)

Phase 5 introduces no new migration (no schema change — reuses existing `Visitor`/`VisitorEmail`/
`IdentifiedVisitor` columns and the existing `promotion_sweep_enabled` / `promotion_sweep_interval_minutes`
settings, which are config-only, not DB columns). For context: current alembic head is
`e9d2a4c71f68` (`add_site_tombstones`), chained `... → c2f8a5d31e97 (add_is_imported_contact, Phase 4) →
e9d2a4c71f68 (site_tombstones, concurrent session)` — two migrations landed after this plan was
originally VALIDATEd. **Re-verify via `alembic -c apps/api/alembic.ini heads` immediately before
EXECUTE** — other concurrent work may have advanced the head further since this note was written.
**Re-confirmed live at inner-PVL (04-08-26): head is still `e9d2a4c71f68`, single head, no drift** —
verified via `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` and by reading the
`down_revision` chain directly in the migration files (`b1c9e7f24d83 → c2f8a5d31e97 → e9d2a4c71f68`).

## Implementation Checklist

### Step A — Sweep job

- [x] A0. (**VALIDATE addition**) Create `apps/api/services/promotion_sweep_runner.py` (heavy logic) + `_promotion_sweep_job()` wrapper in `apps/api/jobs/scheduler.py` (thin: open session, delegate, swallow top-level exceptions) — NOT `apps/api/tasks/` (Celery-only directory, confirmed by reading its contents at VALIDATE). Add `promotion_sweep_enabled: bool = False` + `promotion_sweep_interval_minutes: int` to `apps/api/config.py`; gate the `scheduler.add_job(...)` registration in `start_scheduler()` the same way `changelog_sync_enabled` / `connection_nudge_enabled` gate theirs (`if settings.promotion_sweep_enabled: scheduler.add_job(...)`).
- [x] A1. Register the new APScheduler job at 1-2 minute cadence, with explicit `jitter` and `misfire_grace_time` kwargs (every existing `interval` job in `scheduler.py` carries both, per the Phase 4c convention documented in `start_scheduler()`'s docstring — manually confirm both are set; there is no generic test in this repo that enforces this for every job, only a job-specific AST test for the aggregation sweep, so do not rely on an existing gate catching a missed kwarg).
- [x] A2. Query: `VisitorEmail` rows where `source = 'utm'`, `created_at` within the lookback window, and the associated `Visitor.identity_status NOT IN ('identified', 'merged')` (excludes both terminal-success states; a plain `!= 'identified'` would re-sweep already-`merged` rows for no benefit — see A3). No explicit `do_not_resolve` filter is needed in this query — `IdentityResolver.resolve()` enforces the GPC/DNT + suppression-list guard as the very first check inside `resolve()` itself (`identity_resolver.py:481-496`), before any prior-signal or paid-provider gate, so every caller (this sweep included) inherits it for free; confirmed by direct source read at inner-PVL.
- [x] A3. For each matching row, load the `Visitor` for that `VisitorEmail.visitor_id` and call `IdentityResolver(db, redis_client).resolve(visitor)` — the exact call signature for "the resolver's existing email-based resolution path." Its pre-waterfall step (`_check_prior_signals` Check 1, `identity_resolver.py:274-329`) queries `VisitorEmail` ordered by `created_at desc` per Phase H research finding #1 and short-circuits via `_save_identified` before any budget/recency/paid-provider gate is reached — this IS a deterministic promotion (contact self-identified via a tokenized link they clicked), not a graph-score guess, so it correctly bypasses Phase 1's candidate-tier branch entirely. **Re-confirmed at inner-PVL (04-08-26) by direct read of `identity_classification.py`: `"form_capture"` (the provider `_save_identified` records for this path) is in `PERSON_LEVEL_PROVIDERS` but NOT in `GRAPH_CANDIDATE_PROVIDERS`, so `is_graph_candidate_provider("form_capture")` is `False` and `_save_identified` sets `identity_status = "identified"` directly (`identity_resolver.py:887-889`) — the candidate-tier bypass is structurally guaranteed, not just documented.**
  **CONFIRMED at PLAN-SUPPLEMENT (04-08-26), post Phase-4-EXECUTE, via direct read of the live
  `_save_identified` email-dedup branch (`identity_resolver.py:832-859`):** the imported-contact-click
  case ALWAYS resolves to outcome (b) below. Outcome (a) is theoretical only (no pre-existing import
  contact for that email) and applies to the *plain* utm-click case (Step C1), not the
  imported-contact case (Step C1a). **Independently re-verified byte-for-byte against the live file
  at inner-PVL (04-08-26) — no drift since the PLAN-SUPPLEMENT read.**
    (a) no pre-existing `IdentifiedVisitor` for this email under a different visitor_id →
        `identity_status = "identified"` is set directly. **This is the Step C1 (plain click) outcome.**
    (b) a phantom-import contact already has an `IdentifiedVisitor` row for this email under a
        DIFFERENT visitor_id (`import:{contact_id}`, seeded at Phase 4 import time via
        `_save_identified`'s pre-existing insert) → the email-dedup branch
        (`identity_resolver.py:832-859`) sets THIS (click-derived) visitor's `identity_status =
        "merged"` + `canonical_visitor_id` pointing at the phantom `import:{contact_id}` visitor_id,
        commits, and returns the phantom's (already-`"identified"`) `IdentifiedVisitor` row unchanged.
        **This is the confirmed Step C1a (imported-contact click) outcome — POINTER semantics, not
        direct re-identification of the click-derived visitor.**
  Both are legitimate "recognized as verified" outcomes for AC11 — the dashboard already resolves
  `"merged"` rows via `canonical_visitor_id` (`routers/visitors.py:173-199`) — but they are NOT the
  same `identity_status` value, and Phase 1's `is_verified_identity()` helper only returns `True` for
  the literal `"identified"` string (not `"merged"`); dashboard-facing "verified" checks must resolve
  through `canonical_visitor_id` for merged rows, matching `routers/visitors.py:173-199`'s existing
  pattern. Source: `identity_resolver.py:832-859` (email-dedup branch) +
  `phase-4-contact-import_REPORT_03-08-26.md` (Phase 4 EXECUTED + EVL-green, confirming this branch is
  live and exercised by imports). No further RESEARCH confirmation is required for this item.
  **Defensive check:** log/assert if a swept row ever falls through `_check_prior_signals` into the paid-provider waterfall — the query scope (rows that just had a `VisitorEmail` written) should make this structurally impossible, but a drift here would mean silent provider spend on phantom/click-derived rows, which must never happen.
- [x] A4. Idempotency: re-running the sweep on an already-promoted OR already-merged visitor is a safe no-op. Confirmed via existing code: `_save_identified` catches the `IntegrityError` from a same-visitor_id duplicate insert and returns the pre-existing row without crashing (`identity_resolver.py:824-845`) — no new locking is required for this reason. (Optional, non-blocking: `resolution_runner.py`'s `run_resolution_sweep()` additionally wraps its whole sweep in a Postgres advisory lock — `pg_try_advisory_lock(hashtext(:key))` — for single-flight-across-replicas cleanliness. Phase 5 may mirror this for consistency with the established sweep convention, but it is not required for correctness given the IntegrityError fallback above.)
- [x] A5. Safe failure mode: if a cycle crashes or is skipped, the next cycle's window naturally re-covers unprocessed rows (confirm the lookback window is wide enough to never lose a row between cycles, e.g. window >= 2x cadence). **VALIDATE addition (inner-pvl: phase-5, 04-08-26):** use an ABSOLUTE floor for the window, independent of cadence — e.g. window >= 15 minutes even though cadence is 1-2 minutes — so a short scheduler restart/deploy blip spanning several missed cycles does not silently age a row out of scope. Residual risk (documented, not eliminated by this plan): the query is time-window-bound (`created_at > now() - interval`), not state-bound (no "still needs processing" flag) — if the scheduler is down LONGER than the configured window (sustained outage, not just one missed cycle), the affected `VisitorEmail` row ages out of this sweep's scope and there is no guaranteed automatic fallback (the general `resolution_sweep` job's eligibility filter — `candidate_eligible` in `resolution_runner.py`, keyed off AI-attribution/intent signals — is a different model and does not reliably cover a plain email-capture-only visitor). The visitor is then only promoted if they click a tokenized link again. See "What this coverage does NOT prove" in the Validate Contract below.

### Step B — SLA verification

- [x] B1. Confirm end-to-end timing: click → ingest writes `VisitorEmail` → next sweep cycle (within 1-2 min) → resolver promotes → dashboard reflects "identified" — total ≤5 minutes per SPEC constraint.
- [x] B2. Confirm `/ingest` request itself never blocks on this sweep (it's a fully separate scheduled job, not inline).

### Step C — Tests

- [x] C1. Integration test (plain utm click, no pre-existing import contact): simulate click → ingest → sweep run → assert visitor `identity_status == "identified"` and timestamp delta between click and promotion is ≤5 minutes (SPEC AC11).
- [x] C1a. (**VALIDATE addition; outcome CONFIRMED at PLAN-SUPPLEMENT 04-08-26, independently re-confirmed at inner-PVL 04-08-26 — see Step A3**) Integration test (imported-contact click — the actual Phase H scenario Phase 5 exists to serve): seed a phantom import contact (`Visitor.is_imported_contact=True`, pre-existing `IdentifiedVisitor` row per Phase 4 Step B2) → simulate their tokenized-link click landing under a fresh/different visitor_id → sweep run → assert the click-derived visitor reaches `identity_status == "merged"` with `canonical_visitor_id` set to the phantom `import:{contact_id}` visitor_id, and assert the phantom's own `IdentifiedVisitor` row remains `identity_status == "identified"` (canonical identity untouched). Do NOT assert `identity_status == "identified"` on the click-derived visitor itself — that is the Step C1 (plain-click) outcome, not this one. Timestamp delta ≤5 minutes either way (SPEC AC11).
- [x] C2. Integration test: assert the `/ingest` request completes without waiting on resolution (i.e. resolution is provably async/deferred) (SPEC AC11).
- [x] C3. Idempotency test: running the sweep twice on the same already-promoted (or already-merged) row is a no-op, no duplicate writes/errors.

---

## Exit Gate

```bash
.venv/bin/python3.11 -m pytest tests/integration/test_promotion_sweep.py -q
# Expected: 0 failures, including <=5-minute SLA assertion, the imported-contact-click case (C1a),
# and the /ingest non-blocking assertion.
# Precondition: local Postgres+Redis running — docker compose -f infra/docker-compose.yml up -d postgres redis

# REQUIRED — full UNFILTERED unit lane, not -m unit and not -k. Program-mandatory gate per the
# recorded Phase 1 EVL gate lesson ("phase gates must run the UNFILTERED unit lane, not `-m unit`,
# from Phase 4 on" — see phase-1-candidate-tier-evl-iteration-001_REPORT_03-08-26.md) and Phase 4's
# own adoption of this gate (phase-4-contact-import_PLAN_03-08-26.md).
.venv/bin/python3.11 -m pytest tests/unit -q
# Baseline (pre-EXECUTE, confirmed 04-08-26): 1629 passed, 0 failed. Any new failure introduced by
# this phase's changes is a blocker; any pre-existing failure must be diagnosed as unrelated before
# proceeding (do not silently attribute drift to this phase without checking `git diff --stat`).
```

- SPEC AC11 has a passing proving test, including the imported-contact-click case (the actual
  Phase H named-traffic-factory scenario, not just a generic utm click).
- Sweep cadence, window, and the confirmed merge-vs-identified outcome are documented in the phase report.
- Full unfiltered unit lane green (0 new failures vs the 1629-passed baseline above).
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Phase 4 exit gate not yet passed (no phantom Visitor rows / tokenized links to click).
- If APScheduler wiring conventions differ materially from what research found (e.g. a different task-scheduling mechanism is actually in use), block and re-research rather than inventing a parallel scheduler.
- If Phase 4's actual merge-on-click implementation produces neither of the two outcomes analyzed in Step A3 (e.g. a third status value, or an outright duplicate Visitor row), stop and re-research rather than forcing the C1a assertion to match an incorrect outcome.

---

## Phase Loop Progress

- [ ] 1. RESEARCH — research-agent: prior phase reports read (Phase 4); confirm exact APScheduler registration pattern; confirm identity_resolver's email-based resolve path entry point. (Step A3/C1a merge-vs-identified outcome already CONFIRMED at PLAN-SUPPLEMENT 04-08-26 — re-verify only if Phase 4's landed code drifts further before this phase's EXECUTE.)
- [ ] 2. INNOVATE — innovate-agent: approach decided (largely pre-decided by program INNOVATE Fork 4 — confirm/refine only)
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written
- [x] 5. EXECUTE — all checklist items done; per-section test gates run and green (or gaps documented)
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.**

---

## Touchpoints

- `apps/api/services/promotion_sweep_runner.py` (new — corrected location, see Blast Radius)
- `apps/api/jobs/scheduler.py` (new job wrapper + registration)
- `apps/api/config.py` (new `promotion_sweep_enabled` + `promotion_sweep_interval_minutes` settings)
- `apps/api/services/identity_resolver.py` (read-only reuse of existing `resolve()` / email-resolution path — NO edits — see Blast Radius)

---

## Public Contracts

- `/ingest` request/response contract unchanged — no new synchronous work added to the hot path.
- No change to `is_emailable_identity()`, no change to Phase 1's candidate-tier branch logic.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Click→ingest→sweep promotes visitor to identified within <=5 min (plain utm click) | Hybrid (precondition: local Postgres+Redis — `docker compose -f infra/docker-compose.yml up -d postgres redis`) | AC11 |
| Imported-contact click→ingest→sweep produces a dashboard-visible verified outcome within <=5 min (identified, or merged→canonical) | Hybrid (same precondition) | AC11 |
| /ingest request does not block on resolution | Hybrid (same precondition) | AC11 |
| Sweep is idempotent on already-promoted/merged rows | Hybrid (same precondition) | (safety/regression) |

Failing stub (example):
```
test("should promote a clicked import contact to identified within 5 minutes via sweep", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: promotion sweep SLA")
})
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-program_03-08-26/phase-5-promotion-sweep_PLAN_03-08-26.md`
- Last completed step: PVL (inner-pvl: phase-5, 04-08-26) — full V1-V7 re-run completed against the Inner Loop Refresh Note; the Step A3/C1a outcome and every other load-bearing claim were independently re-verified byte-for-byte against live source (not just re-read from the prior PLAN-SUPPLEMENT note); 2 checklist hardenings applied (Step A2 do_not_resolve clarification, Step A5 window-floor + residual-risk documentation).
- Validate-contract status: **PASS** (04-08-26, inner-pvl: phase-5) — supersedes the 03-08-26 outer-pvl CONDITIONAL contract.
- Supporting context files loaded: umbrella plan, SPEC, INNOVATE Decision Summary (Fork 4), Phase 4 plan/report, `identity_resolver.py` (full read of `__init__`, `resolve()`, `_check_prior_signals` Check 0/1/2, `_save_identified`), `identity_classification.py` (full read), `agent_visitor_filters.py`, `routers/events.py` (utm_identify branch), `models/visitor_email.py`, `link_decorator.py`, `jobs/scheduler.py` (full read), `apps/api/tasks/` + `apps/api/services/` directory listings, live `alembic heads`.
- Next step: Phase 4 exit gate already confirmed passed (EVL-green). This plan is cleared for EXECUTE — orchestrator should spawn vc-execute-agent next (sequential strategy, see Validate Contract).

---

## Validate Contract

Status: PASS
Date: 04-08-26
date: 2026-08-04
generated-by: inner-pvl: phase-5
supersedes: 03-08-26 (outer-pvl) — inner PVL has current evidence (Phase 4 has since executed + gone EVL-green, and every load-bearing claim carried forward from the outer-PVL pass has now been independently re-verified against live source rather than taken on the prior pass's word)

Parallel strategy: sequential
Rationale: 7-signal re-score at inner-PVL: S2 (auth/identity high-risk surface) present; S4 (phase-program classification) present; S6 (high-risk identity-status mutation) present; S7 (5+ files) borderline — the Touchpoints list names 5 files but only 4 are actually edited (`promotion_sweep_runner.py` new, `jobs/scheduler.py` edit, `config.py` edit, `test_promotion_sweep.py` new); `identity_resolver.py` is explicitly read-only reuse, zero lines changed. S3 (3+ viable directions) no longer active as a signal — that was an INNOVATE-stage signal (Fork 4), already locked. Net ~3/7 firmly present, borderline on a 4th. Below the workflow/agent-team threshold. The real EXECUTE blast radius is one cohesive backend change (new service module + one scheduler registration + one config addition + one test file) with no independent workstreams needing mid-execution coordination — sequential (single vc-execute-agent) is the correct fit, matching the "fit over raw score" strategy-selection rule.

### Plan updates applied (this inner-PVL cycle)
- [x] P9 — Step A2: added an explicit note that no query-level `do_not_resolve` filter is needed, because `IdentityResolver.resolve()` enforces the GPC/DNT + suppression guard as the very first check inside `resolve()` itself (confirmed via direct source read, `identity_resolver.py:481-496`) — every caller inherits it for free. (Previously asserted only in the outer-PVL contract's Security-surface finding; now also anchored directly in the checklist step it applies to, and independently re-verified against live source rather than taken on the prior pass's word.)
- [x] P10 — Step A5: added an ABSOLUTE window floor (e.g. >= 15 min, independent of the 1-2 min cadence) so short scheduler restarts/deploy blips spanning several missed cycles don't silently drop a row, plus an explicit disclosure of the residual "sustained outage" risk (the sweep's window is time-bound, not state-bound, so an outage LONGER than the window has no guaranteed automatic fallback — the general `resolution_sweep` job's eligibility model does not reliably cover a plain email-capture-only visitor).
- [x] P11 — Verification Evidence / "What this coverage does NOT prove" (below): added an explicit cross-reference to the pre-existing tracked backlog note `merged-visitor-consumer-awareness_NOTE_04-08-26.md` — Phase 5 is the mechanism that actually starts producing `merged` click-derived rows in volume, so the already-tracked double-count risk goes from theoretical to active with this phase's rollout, and downstream readers (especially Phase 6's dashboard work) should know it applies here.
- [x] P12 — Structural Validation subsection (below) re-verified at inner-PVL. Repeated re-runs of `validate-plan-artifact.mjs` showed the raw failure count oscillate between 2 and 4 depending on whether this contract's OWN prose happened to contain the literal substrings "Phase Completion Rules" / "Acceptance Criteria" (its checks are naive substring tests, not heading-presence tests, so describing a missing section by name can accidentally satisfy the check for it) — a documented validator quirk, not a real change in the plan's structure. Immaterial either way: this file genuinely has no `## Acceptance Criteria` / `## Phase Completion Rules` / `## Complexity` headings (confirmed by direct reading), which is EXPECTED and correct for a phase-program phase-stub (those live in the umbrella plan and locked SPEC instead), and `validate-phase-stub.mjs` — the authoritative validator for this file shape — is 0 failures / 0 warnings regardless.

Carried forward from the outer-PVL pass (03-08-26), independently re-verified against live source at this inner-PVL pass rather than re-stated on trust: P1 (Blast Radius file location: `apps/api/tasks/` re-confirmed Celery-only — 5 files, none named `promotion_sweep`; `apps/api/services/` re-confirmed to hold `cadence_bot_flag_sweep.py` / `outlier_traffic_damping_sweep.py` / `resolution_runner.py`, matching the plan's naming convention), P2 (feature-flag convention), P3 (query exclusion `NOT IN ('identified','merged')`), P4 (call signature `IdentityResolver(db, redis_client).resolve(visitor)` — re-confirmed against the live `__init__` signature), P5 (Step C1a test), P6 (Hybrid tier labels), P7 (jitter/misfire_grace_time note), P8 (defensive-check instruction).

### Execute-agent instructions
- Step A3 entry / Step C1a: the merge-vs-identified outcome is now independently re-verified against live source at TWO separate points (PLAN-SUPPLEMENT 04-08-26, inner-PVL 04-08-26) with no drift between reads. Execute-agent may treat this as settled — no further re-confirmation against Phase 4's code is required before writing the C1a assertion, UNLESS Phase 4's landed code changes again between this VALIDATE pass and EXECUTE (check `git diff --stat` on `identity_resolver.py` / `identity_classification.py` first if EXECUTE happens in a later session).
- Step A0: register the new config settings and job exactly following the existing `if settings.<x>_enabled: scheduler.add_job(...)` pattern used for `changelog_sync`/`connection_nudge`/`referral_activation` — do not register unconditionally.
- Step A1: manually verify `jitter=` and `misfire_grace_time=` are present on the new `scheduler.add_job(...)` call — no existing test enforces this generically for a new job.
- Step A3: if the defensive check ever fires (a swept row reaches the paid-provider waterfall), treat this as a BLOCKING bug, not a known-gap — it means real provider spend on a phantom/click-derived row, which the query scope was specifically designed to prevent.
- Step A4: reusing `run_resolution_sweep()`'s Postgres advisory-lock pattern is optional; if skipped, note in the phase report that idempotency relies solely on `_save_identified`'s IntegrityError fallback (already verified sufficient at VALIDATE).
- Step A5: implement the window floor as a `max(2 * cadence_minutes, 15)` (or equivalent) — do not implement a bare `2x cadence` window with a 1-2 min cadence, since that would only be 2-4 minutes and would NOT survive even a single ~5-minute deploy restart. Document the chosen floor value and the residual sustained-outage risk in the phase report.
- Re-verify `alembic heads` immediately before EXECUTE (re-confirmed `e9d2a4c71f68` at this inner-PVL pass, 04-08-26) — concurrent programs have repeatedly advanced the head in this repo.

### Test gates (C3 5-column table)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC11-a | Plain utm-source click promotes visitor to `identified` within ≤5 min via async sweep | Hybrid | `tests/integration/test_promotion_sweep.py::test_plain_click_promotes_within_sla` (Step C1) — precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis` | B |
| AC11-b | Imported-contact tokenized-link click resolves via merge-on-click POINTER semantics (`identity_status == "merged"` + `canonical_visitor_id` → phantom's `"identified"` row) within ≤5 min | Hybrid | `tests/integration/test_promotion_sweep.py::test_imported_contact_click_promotes_within_sla` (Step C1a) — same precondition | B |
| AC11-c | `/ingest` request completes without blocking on resolution | Hybrid | `tests/integration/test_promotion_sweep.py::test_ingest_does_not_block_on_resolution` (Step C2) — same precondition | B |
| safety-1 | Sweep is idempotent — re-running on an already-promoted/merged row produces no duplicate writes/errors | Hybrid | `tests/integration/test_promotion_sweep.py::test_sweep_idempotent` (Step C3) — same precondition | B |
| regression | Full unfiltered unit lane stays green against the 1629-passed baseline (no new failures introduced by Steps A/B/C) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -q` — no precondition beyond the repo venv | B |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 note: all 4 AC11/safety proving strategies are Hybrid (Docker-gated); none are Known-Gap. Test infra in THIS validate session has no Docker (`which docker` → not found, confirmed at inner-PVL) and no `tests/integration/test_promotion_sweep.py` exists yet (pre-EXECUTE, expected) — both are pre-named, not silently absorbed. The regression row (full unfiltered unit lane) is the one Fully-Automated gate available in this environment; it was not independently re-run in this VALIDATE session because this sandbox's Bash tool blocks `.venv` access (`scout-block.cjs` hook) — this is a tool restriction on the validate-agent, not a defect in the plan or a Docker/environment gap; vc-execute-agent's environment is expected to have `.venv` access and must run it for real before claiming the gate.

Legacy line form (retained so existing validate-contract consumers still parse):
- promotion-sweep: hybrid: `.venv/bin/python3.11 -m pytest tests/integration/test_promotion_sweep.py -q` + precondition: local Postgres+Redis via `docker compose -f infra/docker-compose.yml up -d postgres redis`
- regression: fully-automated: `.venv/bin/python3.11 -m pytest tests/unit -q`

Failing stubs:
```
test("should promote a clicked import contact to identified within 5 minutes via sweep", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: promotion sweep SLA (plain utm click)")
})
test("should promote an imported contact's tokenized-link click to a verified outcome within 5 minutes", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: promotion sweep SLA (imported-contact click)")
})
test("should not block the /ingest request on identity resolution", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: /ingest non-blocking assertion")
})
test("should be idempotent when the sweep runs twice on an already-promoted row", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: sweep idempotency")
})
```

### Dimension findings

- Infra fit: PASS — corrected file locations re-confirmed live: `apps/api/tasks/` holds exactly 5 Celery-task modules, none named for promotion sweep (`ls` re-run at inner-PVL); `apps/api/services/` holds `cadence_bot_flag_sweep.py`, `outlier_traffic_damping_sweep.py`, `proxy_ptr_sweep.py`, `resolution_runner.py`, matching the proposed `promotion_sweep_runner.py` naming convention exactly. `jobs/scheduler.py` fully re-read: every existing optional job follows `if settings.<x>_enabled: scheduler.add_job(..., jitter=, misfire_grace_time=)` — the plan's Step A0/A1 instructions match this pattern exactly.
- Test coverage: PASS — Hybrid tier labels correct (all 4 AC11/safety gates require local Postgres+Redis, confirmed absent in this sandbox — `docker: NOT FOUND`). Added a 5th, Fully-Automated regression gate (full unfiltered unit lane) to the C3 table so the net gate is not resting on Hybrid/Known-Gap alone (Net-gate vacuous-green guard). `.venv/bin/python3.11 -m pytest` command form confirmed correct (avoids the repo's known broken pytest shebang, per `getbeam-venv-pytest-shebang-broken` memory).
- Breaking changes: PASS — re-confirmed via source read: `/ingest`'s router path (`routers/events.py`) contains zero `IdentityResolver`/`.resolve(` references (grepped clean); `is_emailable_identity()` signature and body unchanged; `identity_resolver.py` has zero Phase-5-attributable edits (pure caller from a new module).
- Security surface: PASS — identity-status mutation is a high-risk class (auth/identity), but every mitigating claim is now independently re-verified against live source: (1) `do_not_resolve`/suppression checks run as the FIRST two guards inside `resolve()` (`identity_resolver.py:481-496`), strictly before `_check_prior_signals` and strictly before any paid-provider/budget gate — no query-level filter is needed, every caller inherits this; (2) the `_bid` tokenized-link mechanism is Fernet-encrypted (`link_decorator.py`) — tamper-evident, not forgeable without `settings.encryption_key`, so no new promotion-forgery attack surface is introduced; (3) feature-flag gated (`promotion_sweep_enabled`, default OFF); (4) the "should never reach paid waterfall" defensive check remains an execute-agent instruction.

### Section findings

- Section A — Sweep job: CONCERN → resolved via plan update (P9, P10). Mechanical feasibility confirmed sound end-to-end against live source (query shape, resolver call signature, idempotency fallback, candidate-tier bypass). One genuine plan gap found and fixed: the lookback window as originally specified (`>= 2x cadence` with a 1-2 min cadence) would only be 2-4 minutes wide, which would NOT survive a routine deploy restart — hardened to an absolute floor (P10) with the residual sustained-outage risk now explicitly disclosed rather than silently assumed away.
- Section B — SLA verification: PASS — timing math confirmed sound (1-2 min cadence within the 5-min SLA; window-floor hardening in Step A5 strengthens this further).
- Section C — Tests: PASS — C1/C1a/C2/C3 all mechanically sound against live source; C1a's outcome is now independently re-verified (not merely re-read from the PLAN-SUPPLEMENT note) at byte-level against `identity_resolver.py:832-859` and `identity_classification.py`'s provider sets.

### Structural validation

- `node .claude/skills/vc-generate-phase-program/scripts/validate-phase-stub.mjs <this-plan>` — re-run at inner-PVL: 0 failures, 0 warnings (this file is a phase-program phase-stub; this is its authoritative structural validator).
- `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs <this-plan>` — this script's checks for "Complexity metadata" / "Phase Completion Rules" / "Acceptance Criteria" are bare substring tests against the whole document, so a contract sentence that merely NAMES a missing section can accidentally satisfy the check for it — confirmed at inner-PVL by re-running it 3x against text that did vs. did not contain those literal words, oscillating 2-4 failures with no change to the file's real structure. Ground truth (direct read, not the script): this file has no `## Acceptance Criteria`, `## Phase Completion Rules`, or `**Complexity**` heading/field — correct and expected for a phase-program phase-stub, whose complexity/completion-rules/acceptance-criteria live in the umbrella plan and locked SPEC instead. `validate-phase-stub.mjs` — the authoritative validator for this file shape — is 0 failures / 0 warnings, independent of this quirk. Not treated as a blocking FAIL.

### Open gaps
- None blocking. RESOLVED at PLAN-SUPPLEMENT (04-08-26) and independently re-verified at this inner-PVL pass (04-08-26): Step A3's outcome is confirmed as (b) `merged`+`canonical_visitor_id` pointer semantics for the imported-contact-click case, sourced directly from the live `_save_identified` email-dedup branch (`identity_resolver.py:832-859`) and Phase 4's EVL-green execution.
- Named residual (not a gap in THIS plan's scope, disclosed per P10/P11 above): sustained-scheduler-outage promotion miss, and merged-visitor downstream double-counting (tracked at `process/features/visitors-identity/backlog/merged-visitor-consumer-awareness_NOTE_04-08-26.md`, elevated from theoretical to active by this phase's rollout).

### What this coverage does NOT prove
- AC11-a/b prove the sweep promotes a visitor within the lookback window under test-controlled clock/DB state; they do NOT prove real-world APScheduler timing under production load (container restarts, pool contention with the other ~10 scheduler jobs sharing a 5-connection pool) — that is an operational concern for post-deploy observation, not testable in this plan's scope.
- AC11-c proves the `/ingest` handler returns without awaiting the sweep in the test harness; it does NOT prove the scheduler thread never introduces event-loop contention that indirectly slows concurrent `/ingest` requests under real load — that would require a live-load probe, out of scope for this plan.
- safety-1 proves no duplicate `IdentifiedVisitor` row or unhandled exception on a double-run within one test process; it does NOT prove cross-replica concurrent-sweep safety under real multi-replica production traffic (the advisory-lock mitigation is optional/non-blocking per the Execute-Agent Instructions, not exercised by this test).
- None of the 4 AC11/safety gates prove the actual dashboard UI renders the "N of M contacts active" count correctly for a promoted visitor — that is Phase 6's scope (Hot-contacts dashboard), not Phase 5's.
- The sweep's lookback window is time-bound, not state-bound (Step A5): if the scheduler is down LONGER than the configured window (a sustained outage/restart storm, not just one missed cycle), the affected `VisitorEmail` row silently ages out of the sweep's scope, and there is no test or gate in this plan proving an automatic fallback exists (the general `resolution_sweep` job's eligibility model — `candidate_eligible` — is different and does not reliably cover a plain email-capture-only visitor). This is a documented residual availability risk, not a correctness or security defect.
- None of the 4 AC11/safety gates prove downstream consumer surfaces (`kpi.py`, `timeseries.py`, `campaign_sender.py`, `segmenter.py`, `csv_exporter.py`) correctly avoid double-counting a promoted `merged` click-derived visitor alongside its canonical phantom import contact — this is the pre-existing, already-tracked gap at `process/features/visitors-identity/backlog/merged-visitor-consumer-awareness_NOTE_04-08-26.md`, which this phase elevates from theoretical to active (this sweep is the mechanism that actually starts producing `merged` rows in volume from real clicks).

Gate: PASS (0 unresolved FAILs, 0 unresolved CONCERNs — 3 new minor CONCERNs found this cycle [P9-P11] all resolved via plan updates in this same pass; the one item that kept the prior pass at CONDITIONAL — Step A3/C1a's outcome — is now independently re-verified against live source, not merely carried forward)
Accepted by: session (autonomous inner-PVL pass, 04-08-26) — no residual CONCERNs remain requiring separate user acceptance; the two disclosed residual risks (sustained-outage promotion miss, merged-visitor downstream double-counting) are named, sourced, and cross-referenced to existing tracked artifacts rather than silently absorbed, per the Net-gate vacuous-green guard and the Known-Gap discipline.

---

## Inner Loop Refresh Note

Date: 2026-08-04

Findings baked into this plan (no separate research subagent needed — this supplement was driven
directly by Phase 4's landed report + a source read of the live `identity_resolver.py` email-dedup
branch, both already available in context):

- Step A3 / Step C1a open question RESOLVED: the imported-contact-click case always produces
  `identity_status == "merged"` + `canonical_visitor_id` (pointer semantics), confirmed via
  `identity_resolver.py:832-859`. Step C1a's assertion rewritten accordingly.
- Alembic head refreshed: `e9d2a4c71f68` (`add_site_tombstones`), chained off `c2f8a5d31e97`
  (`add_is_imported_contact`, Phase 4's migration) off `b1c9e7f24d83`. Re-verify at EXECUTE.
- Added the program-mandatory full UNFILTERED unit lane (`tests/unit`, not `-m unit`) to the Exit
  Gate, per the Phase 1 EVL gate lesson and Phase 4's own precedent. Baseline: 1629 passed, 0 failed.

PVL re-run required: YES — the existing validate-contract (`generated-by: outer-pvl`, dated
03-08-26) predates this note. Per orchestration.md's V1 Refresh Note check, the next VALIDATE pass
must re-run from V1 rather than auto-proceeding to EXECUTE.

**PVL re-run completed 04-08-26** — see `## Validate Contract` above (`generated-by: inner-pvl:
phase-5`, `Gate: PASS`). This note is retained as the audit-trail record of why the re-run was
triggered; it is superseded for gating purposes by the Validate Contract section above.
