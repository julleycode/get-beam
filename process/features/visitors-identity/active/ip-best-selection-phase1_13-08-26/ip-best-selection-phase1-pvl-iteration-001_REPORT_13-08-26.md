# PVL Iteration 001 — ip-best-selection-phase1

date: 2026-08-13
loop: pvl
plan: ip-best-selection-phase1_PLAN_13-08-26.md
verdict: Gate: BLOCKED
agents: vc-validate-agent (opus, fresh V1–V7) + external adversarial verifier (opus, default-REFUTED), parallel, hardened STOP blocks
consolidated_gaps: 21 (after dedup: validate 5 FAIL + 7 CONCERN; verifier 15 net-new — 3 P0, 9 P1, 3 P2; 4 overlaps)

## What held

- All 40 DR rows verified exact against live source at HEAD `372e00b` (alembic head `f4b9d2a71c68`, unit baseline 1764, scheduler 24/21/3, all identity_resolver + mixin anchors).
- CR-1..CR-3 clean — grep for loser-language found zero survivors.
- 21 verifier claims survived refutation (FK target, erasure cascade, caller census 5/5, reserve arithmetic, blast-radius count 38, cadence math).
- Validate-contract written into plan (`generated-by: inner-pvl: phase-1`, date 2026-08-13). Structural validator 0/0.

## Top defects (consolidated)

P0-class:
1. `override_ip` never reaches `_write_through_company_graph` (`identity_resolver.py:733-737`) — auto lane poisons cross-tenant `company_graph` with wrong IP→domain at conf 0.7 / 75d. Regression vs superseded plan's coverage.
2. Third unconditional slice: step 6.9 sets `deterministic_only=True` on promotion sweep, but the barrier sits BEFORE `_check_beam_identity_network` (`:534-536`) → silently kills cross-tenant graph promotions flag-OFF. AC-1/8.3/"exactly 2 slices" violated by construction; paid half near-vacuous (live `unexpected_paid` invariant already guards it).
3. `ResolutionAttemptResult.outcome` 3-value enum cannot express resolver's six no-provider `return None` exits (`:590 :599 :631 :635 :644 :653`) → sweep books them `no_match`, burns 1/4 lifetime attempts + blacklists the IP with zero provider contact — re-entry of the DR-18/DR-20 self-annihilation.
4. P1-AD-4 invariant false: attempted-unavailable providers DO write ResolutionLog rows (`:934-946`, `:1043-1066`); daily meter + `was_recently_attempted` have no outcome filter → outage consumes budget slot + arms 30-day lock; gate `::provider_unavailable_defers_through_ramp_and_repeats_cap` is a guaranteed EXECUTE failure.
5. Outage slice unbounded in full-outage direction (validate F2 + verifier F4): today 4-defer→terminal; plan = re-arm forever, deferred rows crowd out newer visitors in LIMIT batch (the write-off's own documented rationale, never engaged). "Only reduces dispatches" claim inverted.

P1-class (selected): claim placement P18 vs step 6.7 vs live `:914`/`:953` mechanically unsatisfiable + AC-13 falsified by `check_usage_allowed` internal commits; SN-1 increment_usage half charges human quota for non-emailable agent rows (adjudicated: split — check unconditional, increment NOT for agent-derived); D-7 auto lane loses BOTH dedup layers (write both cache keys on negative); mixin kwarg forwarding TypeErrors rb2b / drops `selected_ip_activity_at` (needs per-provider split); four-lane race gate unconstructible (predicates pairwise disjoint); DR-7 gate in wrong module (vacuous); DR-12 abstain must treat `""` as NULL; SiteOut bool needs None→False `mode="before"` validator; stale anchors re-imported that predecessor PVL had already corrected (meta-finding F11); R6 cold-start math 2× understated (spillover doubles NULL rows/tick); undisclosed flag-ON `vpn_filtered → unresolvable` transition half-ships D-1.

D-6 adjudicated SOUND (one wording fix: R11 downgrade to usability follow-up, keep Rollout Gate "or").

## Routing

First-pass BLOCKED → vc-plan-agent (PVL-supplement mode, single agent — gaps interlock through AC-1/AC-13/SN-1) with consolidated 21-gap SUPPLEMENT REQUEST. `PHASE_COMPLETE: VALIDATE` NOT emitted. Re-validate cycle 2 = vc-validate-agent + paired external adversarial verifier (the pairing found the top defect at predecessor cycles 2/6/7 and here).
