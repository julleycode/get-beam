---
name: identity-vocab-reconcile-pvl-iteration-003
description: PVL supplement cycle 3 — reverts the in-helper confirm-gate, re-sites it as a call-site wrapper at 3 of 5 sites (2 excluded as non-outreach), recomputes blast radius
date: 2026-08-07
iteration: 3
metadata:
  node_type: report
  type: pvl-iteration
  domain: plan
  feature: visitors-identity
  loop_status: CONTINUE
---

# PVL Iteration 003 — identity-vocab-reconcile

**Plan:** `process/features/visitors-identity/active/identity-vocab-reconcile_07-08-26/identity-vocab-reconcile_PLAN_07-08-26.md`
**Cycle:** 3 of max 10
**Trigger:** `Gate: BLOCKED` at cycle 2 (2 FAIL / 1 CONCERN) → supplement
**Result:** 6/6 applied, plan validator 0 failures / 0 warnings

## Applied

- **S6 — helper restored.** Every plan edit touching `is_emailable_identity()` reverted. It keeps devjulley's existing 3-parameter signature and body, unchanged by this reconciliation. Stated as a hard constraint in §3.1 / Public Contracts / D3+D10, citing `test_is_emailable_identity_still_takes_exactly_three_params` as the enforcing test.
- **S7 — wrapper re-sited, verified per site by reading devjulley code.** This is where the cycle earned its keep — the "5 call sites" premise turned out to be wrong:

  | Site | Fit | Detail |
  |---|---|---|
  | `services/campaign_sender.py` | fits, free | An `identity_status` query already exists; reorder it to before the gate. Net zero new queries |
  | `routers/campaigns.py` (`_resolve_linkedin_targets`) | fits, costs a query | Needs a genuinely new `Visitor.identity_status` query |
  | `services/csv_exporter.py` | fits, costs a query + import | Needs a new query and a new `Visitor` import (confirmed not currently imported) |
  | `services/hot_alert.py` | **excluded** | Uses the helper for owner-facing name-reveal, not outreach-to-candidate |
  | `services/outcome_digest.py` | **excluded** | Uses the helper for owner-facing ranking, not outreach-to-candidate |

  The 2 exclusions are stated with reasoning in the plan rather than silently dropped.
- **S8 — blast radius recomputed** via fresh `git grep`, not arithmetic on the old figure. The 35 is relabeled as a *must-stay-green regression count* (those tests must keep passing, they no longer break). Real new footprint: **3 production call sites + 1 new test file** (`tests/unit/test_candidate_outreach_gate.py`).
- **S9 — Hard Stop made accurate.** The "zero production behavior change with the flag OFF" promise now carves out the confirm-candidate exception explicitly: a human-confirmed identity becomes emailable regardless of the flag, by design. Applied to both the Hard Stop text and the `## Autonomous Goal Block`.
- **S10 — D10 rewritten** as the wrapper-based decision. The rejected in-helper formulation is kept struck-through with its rejection reason, so the audit trail survives.
- **S11 — suspension markers cleared.** §3.1 / §3.7 / §4 / §6 coherent again; grep-verified that no dangling "BLOCKED — see finding N" pointer remains outside historical context.

## Why the site count dropped 5 → 3

Prior cycles treated "callers of `is_emailable_identity()`" as interchangeable. Reading them showed two distinct uses: **outreach gating** (who gets mailed) and **owner-facing display/ranking** (what the site owner sees in their own dashboard). Only the former is in scope for a candidate-outreach flag. Wrapping the latter would have hidden already-resolved identities from the owner's own view — a UX regression with no safety benefit.

## Known carry-forward

`## Next Instruction` at the bottom of the plan still reads stale ("Do NOT enter EXECUTE… PVL cycle 2"). Expected — it is validate-agent-owned and refreshes on the next VALIDATE run. Left untouched per the do-not-modify-the-contract constraint.

## Loop state

`CONTINUE` — re-validate from V1 (cycle 4). Docker still unavailable; migration live round-trip remains a documented known-gap, not blocking.
