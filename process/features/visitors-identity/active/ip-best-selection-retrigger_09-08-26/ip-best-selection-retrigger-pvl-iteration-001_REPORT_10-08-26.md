# PVL iteration 001 — ip-best-selection-retrigger

**Date:** 2026-08-10
**Loop:** pvl (plan-validate-fix)
**Plan:** `ip-best-selection-retrigger_PLAN_09-08-26.md`
**Cycle result:** supplement applied, re-validation from V1 pending

---

## What this cycle did

Baseline validation returned `Gate: BLOCKED`. A supplement cycle closed 14 gaps.
The plan grew 762 → 1340 lines; blast radius grew 15 → 22 files.

## Two-leg validation — why both legs were needed

`vc-validate-agent` has no Agent tool in this environment, so its designed Layer 1 /
Layer 2 parallel fan-out could not run; it executed every dimension sequentially in a
single pass. An independent adversarial verifier ran in parallel under the orchestrator,
prompted to refute rather than review.

**Each leg found blocking defects the other missed.** This is the second time in this
repo that the external adversarial leg has been the one to find the top defect.

| Found only by vc-validate-agent | Found only by the adversarial leg |
|---|---|
| The real AC-8 tripwire is `tests/unit/test_agent_company_resolution.py:515-540` (`_AC2_FILES`) — both the orchestrator's prompt and the adversarial leg named the wrong file | Rollback `flag → False` is itself a paid-provider re-burn event (G6) |
| The two sweeps are **disjoint by status**, so the starvation ORDER BY solved a non-problem while the real budget contention had no mechanism at all (G4) | Perpetual-skipper leak: a single-IP visitor never increments, never leaves the WHERE clause, and sorts **first** forever (G5) |
| Defer-exhaustion precision: `:722` *skips* the increment when `before == 4`, `:750` resets to 0, so `0 > 4` is False (G2a) | `vpn_filtered` visitors have zero recovery once exhausted (G7) |
| | With no mmdb, `classify_ip_org_kind` returns **`"org"`**, not `"unknown"` — the tier ladder collapses to a constant (G8) |

Convergent finding (both legs, independently): assigning `visitor.ip_address` before
`resolve()` is a **committed write**, not an in-memory override, and permanently
corrupts the column (G1).

## Gaps closed

| # | Severity | Gap | Resolution |
|---|---|---|---|
| G1 | CRITICAL | `visitor.ip_address = chosen` is session-attached and flushed by `resolve()`'s commits at `identity_resolver.py:596,609,621,735,752` | `override_ip` parameter threaded to `resolve()` + 5 provider mixins (decision D-A; the earlier "one parameter only" promise is explicitly superseded) |
| G2a | CRITICAL | Defer-exhaustion misread as a successful attempt | `resolution_defer_count = 0` added to the sweep WHERE, making `before` always 0 and the test exact |
| G2b | CRITICAL | Budget exhaustion at `:589-591` touches no deferral column → counted as a real attempt with **zero provider calls**; four cycles blacklist four IPs having never reached a provider | Sweep pre-checks budget / `do_not_resolve` / suppression before an attempt is consumed or `tried_ips` appended |
| G3 | FAIL | AC-8 gate cited the wrong file and a hardcoded list that cannot discover a new module | `test_agent_company_resolution.py` added to Touchpoints; new module appended to `_AC2_FILES`; behavioural integration gate added |
| G4 | FAIL | Real contention is the shared per-site daily budget, not intra-sweep ordering | Per-site 70% reserve (decision D-B, labelled PLACEHOLDER); vacuous gate replaced |
| G5 | MAJOR | Skip path never increments → perpetual re-evaluation, front-of-queue forever | New `auto_reidentify_skip_count < 8` bound; ORDER BY re-keyed to `next_at ASC NULLS LAST` |
| G6 | MAJOR | Rollback un-gates revive, which sees corrupted IP ≠ real IP → mass flip + failed-log DELETE | Dissolves once G1 is fixed; the dependency is now recorded in Rollback rather than left implicit |
| G7 | MAJOR | Exhausted `vpn_filtered` visitors have no auto path and no manual path | Manual endpoint + UI extended (decision D-C) |
| G8 | MAJOR | `classify_ip_org_kind(None, None)` returns `"org"`; the `unknown` tier does not exist in the described pipeline and its gate was vacuous | Explicit `asn is None → "unknown"` short-circuit specified; AD-3 rationale rewritten |
| G9 | — | Every-site coverage spends budget on sites that opted out of auto-identify | Per-site opt-out column + UI toggle (decision D-D); every-site remains the default |
| G10–G14 | CONCERN | exception-path `next_at`; unlisted `unresolvable → vpn_filtered` transition; missing retention rule; stale SPEC Constraint 6 (`registry`); dropped SPEC Constraint 5 (dormant Celery twin) | All closed in-place |
| — | — | 6 wrong or stale path:line citations | Corrected verbatim |

## Claims that survived and were left untouched

- AD-1's GDPR inheritance claim is **true** — `routers/visitors.py:448-474` issues a full
  `DELETE FROM visitors`, so a JSONB column on the row genuinely inherits erasure.
- The sweep is structurally satisfiable; terminal rows keep accruing `intent_score`.
- AD-10 (no new `identity_status` value) — all five named readers verified.
- The AST tripwire strengthening is safe and does not break the existing two sweeps.
- Scheduler 24/22 arithmetic; `revive_returning_unresolvable`'s discarded return value;
  R2 (the JSONB column is in no predicate); `force_retry`'s single-branch footprint.
- Hybrid gates are **runnable** — the Docker CLI exists at
  `/Applications/Docker.app/Contents/Resources/bin/docker`; nothing was recorded as
  environment-blocked.

## Decisions taken this cycle

| id | Decision |
|---|---|
| D-A | `override_ip` parameter, accepting the 6-file footprint |
| D-B | Per-site budget reserve at 70%, explicitly a placeholder |
| D-C | Extend manual retry to `vpn_filtered` (accepted scope increase) |
| D-D | Add a per-site opt-out column; every-site coverage stays the default |

## Carried forward

Two numbers have no measured basis and are recorded as open risks in the plan:
the **70% budget reserve** and the **`skip_count < 8`** bound. Both need the
distinct-IPs-per-visitor and per-site budget-consumption measurements named in the
plan's Measurement Gap before a production flag flip.

## Next

Re-spawn `vc-validate-agent` from V1 against the supplemented plan, with a second
independent adversarial verifier in parallel. `PHASE_COMPLETE: VALIDATE` is not legal
until `Gate: PASS`, or until an explicitly accepted CONDITIONAL after this cycle.
