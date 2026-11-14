# PVL Iteration 004 — site-analysis-onboarding

- **Date:** 2026-08-13
- **Loop:** PVL, cycle 3 = re-validate from V1 + adversarial verifier (parallel legs)
- **Verdict:** validate `Gate: CONDITIONAL` (0 FAILs, C16–C20); verifier 12 new findings (3 fail-equivalent, 6 concern, 3 nit) → NOT terminal, supplement cycle 3 required

## Validate leg

- F5/F6 + C10–C15 + all 15 cycle-2 adversarial findings verified CLOSED against live source. Two-slot single-writer structurally guaranteed; all precedents exact.
- New CONCERNs: **C16** AC-7/AC-10 rows point at superseded gates; **C17** mock-OFF delta gate lacks named patch targets + zero-outbound backstop + terminal-state assertion; **C18** PUT unconditionally sets status="ready" (erases pending; candidate=NULL PUT undefined; analyzed_at two-writer ambiguity); **C19** three stale "4 columns" strings; **C20** `test_budget_incremented_once_per_run` vacuous under mock (same F5 mechanism).
- EXECUTE strategy rec (when gate clears): agent team 3 members Backend/Frontend/Tester (opus), ≤2 rounds; alternative sequential Block 1→2→3.

## Verifier leg (fail-equivalents beyond contract)

- **VF1** `message` has no storage — 5-column migration can't hold budget-denial reason; 2 named gates unimplementable. Fix: 6th column OR read-time derivation.
- **VF2** ≈C17 amplified: patch must target `site_analysis` module bindings (from-import), window must open after create-time task settles, await handle unnamed.
- **VF3** panel lacks `none` state — AC-8 re-run unreachable for every pre-existing site (status NULL→"none", re-run button only on `failed` branch).
- VC4 ≈C18 (PUT erases pending → reopens double-run); VC5 status/analyzed_at overloaded across slots (failed re-run hides confirmed profile); VC6 `_analysis_inflight` placement = router↔service import cycle + done-callback vs finally cleanup; VC7 D13 case table omits `null` (settings passes `site.description: string|null` — auto-fill dead on the reliable path) + explicit-replace contradiction; VC8 `strip_url` is not a validator (`javascript:` passes — no netloc ⇒ returns input); VC9 candidate shadows confirmed profile, no dismiss path; N10 ≈C19; N11 SPEC narrative §item-1 not amended; N12 dead params in `check_site_analysis_budget` + is_byok projection.

## Orchestrator decisions for supplement cycle 3

- **VF1 → read-time derivation** (no 6th column): `message` derived at GET (`status=="failed"` + budget.allowed False ⇒ cap copy); 1.9 stops persisting message; both gates re-pointed. Smallest schema.
- **VF3 → add `none` panel state** with Analyze button (budget-gated) + evidence row.
- **C18/VC4 → PUT preserves in-flight pending** (writes profile + NULLs candidate, leaves status/started_at); PUT with no candidate allowed (edits-from-scratch on confirmed slot) but must be stated; `analyzed_at` = candidate-analysis-completion time only (PUT does not stamp it; add nothing new).
- **VC5 → render rule:** panel shows review UI whenever `candidate ?? profile` non-null; `failed` renders as banner above, never instead.
- **VC6 → `_analysis_inflight` lives in `services/site_analysis.py`**, discard in done-callback (mirror events.py exactly).
- **VC7 → `null` ⇒ known-empty** (server-asserted); reconcile explicit-replace: user choice "replace" may set true — table + contracts same direction.
- **VC8 → positive check:** scheme in {"", http, https} AND hostname regex; drop "survives strip_url" wording.
- **VC9 → PUT gains `promote: bool` (default true); `promote: false` ⇒ NULL candidate only (dismiss).**
- C16, C17+VF2 (full patch-target naming + E12 extension + delta-window + await via `_analysis_tasks` gather), C19/N10, C20 (mock OFF + same targets), N11 SPEC narrative pointer, N12 signature `(site_id)` only — as specified.

## Next

Supplement cycle 3 → re-validate cycle 4 (validate + verifier legs). Trend: 4F → 2F → 0F validate-side; verifier finding rate also declining (5→3 fail-eq).
