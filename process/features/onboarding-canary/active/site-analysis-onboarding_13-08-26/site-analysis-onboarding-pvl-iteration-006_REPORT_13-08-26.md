# PVL Iteration 006 — site-analysis-onboarding

- **Date:** 2026-08-13
- **Loop:** PVL, cycle 4 = re-validate from V1 (single leg; verifier merged into validate scope)
- **Verdict:** Gate: CONDITIONAL — 0 FAILs, 4 new CONCERNs (C21–C24) + nits N13–N15; all 17 cycle-3 findings verified CLOSED vs live source

## Findings

- **C21 (highest):** derived-`message` rule ("non-failed ⇒ null") contradicts POST capped-response bullet (cap copy with status unchanged); `none`-state disabled Analyze has no copy. Fix: precedence rule over (allowed, status) cells. Residual (accepted price of D15 no-6th-column): failed-other + exhausted counter misattributes cause to cap.
- **C22:** `promote:false` dismiss of first-ever candidate ⇒ `status="ready"` with both slots empty → ready branch renders over absent data. Fix: slot-emptiness evaluated BEFORE status switch; render rule owns review UI, status contributes banner only.
- **C23:** POST fire path not bound to `_fire_site_analysis` — literal bare create_task breaks in-flight discard + gather await + strong ref. Fix: "fires via _fire_site_analysis, never bare create_task" + post-settle re-run assertion.
- **C24:** SPEC §Constraints C-1 + §Background still describe deleted sync extraction. Fix: strike with A-1 pointer, annotate Background, extend A-1 scope note.
- N13 stale VC6 rationale; N14 ~11 vs 13 backend files; N15 per-test mock-override unstated.
- Priority check (a) PASS: confirmed-profile + status pending handled coherently.
- E17–E20 added: execute-side mitigations so EXECUTE not blocked on plan-text wording for C21–C23.

## Orchestrator decision

C21 yields wrong behavior if implemented literally → supplement cycle 5 (all 6 gaps; sequential 1 agent — C21/C22 coupled, C23 shares POST bullet with C21), then final re-validate. Cycle count 4/10, gap trend 13→22→17→6, no plateau.

## Next

Supplement cycle 5 → validate cycle 5 (expected PASS or acceptably-thin CONDITIONAL).
