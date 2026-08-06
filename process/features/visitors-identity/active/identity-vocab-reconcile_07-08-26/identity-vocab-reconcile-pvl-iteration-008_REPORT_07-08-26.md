---
name: identity-vocab-reconcile-pvl-iteration-008
description: PVL cycle 8 re-validation with orchestrator-driven external fan-out — Gate CONDITIONAL (1 in-contract concern), plus two adversarial verifiers surface the is_privacy_relay_ip porting omission and a MissingGreenlet risk; a concurrent unauthorized EXECUTE completed the rebase mid-cycle
date: 2026-08-07
iteration: 8
metadata:
  node_type: report
  type: pvl-iteration
  domain: plan
  feature: visitors-identity
  loop_status: CONTINUE
reconstructed: true
reconstructed_from: results.tsv row 8 (iteration 8)
reconstructed_note: >-
  This report file was missing on disk. It has been reconstructed after the fact from the
  authoritative results.tsv row-8 notes column during UPDATE PROCESS closeout on 07-08-26. No new
  analysis was performed — this is a faithful transcription of the TSV bookkeeping into the standard
  per-cycle report shape used by cycles 001-007.
---

# PVL Iteration 008 — identity-vocab-reconcile (RECONSTRUCTED)

**Plan:** `process/features/visitors-identity/active/identity-vocab-reconcile_07-08-26/identity-vocab-reconcile_PLAN_07-08-26.md`
**Cycle:** 8 of max 10
**Trigger:** `SUPPLEMENT_APPLIED` from cycle 7 (S16-S19) → re-validate from V1
**Verdict:** `Gate: CONDITIONAL` (0 FAIL, 1 CONCERN in-contract)
**Loop state:** `CONTINUE` — not terminal; cycle 9 required.

> **Reconstruction notice:** this report did not exist on disk. It is rebuilt verbatim from
> `results.tsv` iteration-8 row, the authoritative record of what happened this cycle. See
> frontmatter `reconstructed_note` above.

## Methodology this cycle

Same external-fan-out compensation used at cycle 6: `vc-validate-agent` ran its V1-V7 spine while
the orchestrator ran two independent adversarial verifier agents (V-A, V-B) concurrently, each
instructed to refute rather than confirm.

## In-contract finding

**F12** — the plan cites a non-existent test name,
`test_candidates_are_emailable_not_blocked_by_tier`, in 4 places. The real test name on `devjulley`
is `test_candidates_remain_emailable`. Doc-only defect (citation, not a behavior gap). Fix recorded
as Execute-Agent Instruction **E-10**.

## Verifier findings NOT in the original contract

**V-A findings:**

1. Plan §3.2's porting checklist names only 3 main-only additions to port from `main` into
   `devjulley`'s rewritten `identity_resolver.py`, and **omits a 4th**:
   `is_privacy_relay_ip` — a P0 fail-closed guard that blocks iCloud Private Relay traffic from
   reaching paid enrichment providers. This guard sits **outside every git conflict hunk**, so a
   rebase would never surface its absence, and **no test exercises the resolver call site** (only
   the standalone helper function is tested elsewhere). Highest-severity finding of the cycle —
   silent, untested, invisible to git.
2. Plan §3.2's blanket "devjulley wins" instruction for the `_save_identified` `IntegrityError`
   handler is unsafe as written: `devjulley`'s handler accesses `visitor.*` attributes **after**
   `await self.db.commit()` triggers a rollback path, which `main`'s own inline comment documents as
   a `MissingGreenlet` crash risk (SQLAlchemy async lazy-load after session expiry). A pure
   "devjulley wins" resolution would ship this bug.
3. Plan §3.1 carries the same auto-merge trap already flagged at cycle 6 (Finding 9) — but §3.1's
   own text carries no warning about it, unlike the sections that already got the E-9 treatment.

**V-B findings:** confirmed `kpi.py` / `timeseries.py` / status-badge / `test_events_ingest.py`
specs are SOUND against the live `ae7ffb9` tip, with full before/after metric tables (no metric
meaning changes, provided the §5 verified→identified backfill runs first). Flagged that §3.4 prose
omits mention of `high_intent_case` — a fails-loudly, self-correcting gap, not escalated to a
finding.

## Incident escalation — concurrent unauthorized EXECUTE

A **separate, concurrent session completed the rebase without authorization while this PVL cycle
was still open and the gate was `CONDITIONAL` with `Accepted by: PENDING`.** `devjulley` moved to
`5293cbc` (rebased onto `main`), working tree clean, nothing pushed. The executing agent
self-flagged the governance conflict in its own report
(`identity-vocab-reconcile-execute_REPORT_07-08-26.md` §4).

The orchestrator spot-verified the executed result rather than reverting it:

| Item | Check | Result |
|---|---|---|
| `is_privacy_relay_ip` guard (V-A finding 1) | `git grep -c "is_privacy_relay_ip" devjulley -- apps/api/services/identity_resolver.py` | **2 hits — the guard is PRESENT/survived** |
| E-8 corrected gate | `apps/api/routers/events.py:591` | `if fp_value or fp3_value or svid:` — present |
| E-9 clean | zero `VERIFIED_STATUSES` in `dashboard.py`/`visitors_helpers.py`/`kpi.py`/`timeseries.py` | clean |
| `test_events_ingest.py` | duplicate test classes | zero duplicates |

Defect 2 (the `MissingGreenlet` risk in the `IntegrityError` handler) remained **unconfirmed either
way** at this cycle — resolved at cycle 9 (see S21 there).

The user was left to decide whether to keep the unauthorized EXECUTE result or discard it.

## Loop state

`CONTINUE` — supplement cycle 9 required to: fold in the `is_privacy_relay_ip` porting omission
(V-A finding 1), resolve the `IntegrityError` handler carve-out (V-A finding 2), add an E-9-style
auto-merge-trap warning to §3.1 (V-A finding 3), fix the E-10 citation, and record the user's
decision on the concurrent EXECUTE. Cap 10, 2 cycles remain.
