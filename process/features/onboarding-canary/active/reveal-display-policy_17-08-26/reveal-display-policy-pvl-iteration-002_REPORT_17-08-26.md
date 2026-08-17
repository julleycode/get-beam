# PVL iteration 002 — reveal-display-policy

**Date:** 17-08-26
**Loop:** plan-validate (PVL), cycle 2 — re-validate from V1 + parallel external adversarial verifier (fable, REFUTE-mission)
**Verdict in:** `Gate: BLOCKED` (validate: 2 FAIL G1-G2 + 4 CONCERN G3-G6; verifier: 2 FAIL-eq + 7 CONCERN + 6 NOTE, 10 CONFIRMED coverage groups)
**Supplement out:** merged single supplement (cycle 2) — see gap list below

## Cycle-1 gap closure (verified against source)

6/8 closed clean (F1 funnel decider 25a, F2 coords optional + touchpoints, C1-C4). F3/F4 partial — replaced by new gaps below.

## Merged gap list for supplement cycle 2 (validate ∩ verifier, deduped)

| ID | Source | Defect |
|---|---|---|
| A | G3/G4/G5 + verifier-1 | P7/P8 DECLARED-APPLIED-BUT-NOT: step 19 `_mock_geo` licence still live (contradicts goal-block hard stop); step 24 targets circle in wrong file (circle = `canary-map.tsx:167-168`, REQUIRED in map mode, delete nothing there); step 30/Risk#2/Contract§2 still claim "33 equality assertions" (actual: 1, green); anchor drift (onboarding.py 106/108/109; demo.py :408; wantsMap :459; hasUsableGeo :179-185) |
| B | G1 + verifier-3 | AC-7 e2e baseline RED TODAY: `onboarding-canary.spec.ts:214` asserts "IP-level estimate", deleted from product at `3e2dd5b`. Add baseline-run step; DELETE stale assertion (never restore an IP caption); re-tier Hybrid (uvicorn+PG/Redis+auth.setup+storageState) |
| C | G2 + verifier-6 | F3 deletion premise false + ranges wrong: render `canary-reveal.tsx:107-111` is NOT mode-gated; country ships `confidence` → deletion is load-bearing. Exact sites: canary-format.ts fn+test+import; canary-reveal.tsx:107-111 JSX; funnel `:144-154` ONLY (`:155-160` = `formatNetwork` head incl. fabrication guard — DO NOT TOUCH); funnel `:450` call + `:467` interpolation |
| D | verifier-2 | AC-12 vacuous: 3 surviving user-facing "IP" strings outside scan scope — `onboarding-steps.js:446`, `onboarding-script.ts` REVEAL_GEO_ONLY, `onboarding-flow.tsx:269`. Reword all three jargon-free (user rule D6); add `onboarding-script.ts` to Touchpoints; widen AC-12 scan scope or record explicit exceptions |
| E | verifier-4/5 | Decision table: drop "exhaustive 9-row" (row 7 collapses at build_geo boundary → 8 testable rows); precedence rule 2 marked "implemented in build_geo; router discriminates reason"; mobile note only distinguishable client-side at confidence=high — copy table reconciled (mobile copy = high×mobile row only) |
| F | verifier-7 | React "none"-mode no-claim parity: add Section-F step rendering the D6 no-claim line on React text/skip paths (or document accepted divergence — parity D7 preferred) |
| G | verifier-8 | Country mode double country claim: legacy place row ("◎ US") renders beside new country card in both clients — suppress in country mode, assert in 31a/32 |
| H | verifier-9 | Funnel legacy-fallback (display_mode-less payload) has zero coverage: add third Playwright leg asserting legacy behavior |
| I | verifier-10..15 (NOTEs) | canary-listen.tsx:89 consumer → Touchpoints + Risk#7 sweep; step 35 migration gate scoped to plan's own delta (shared worktree, sibling sessions dirty migrations dir); Risk#5 stub pointer fix; label-less-relay-reaches-map recorded as accepted gap in row 9 note; AC-9 diff-gate committable-around note; mobile regex brand-token list explicit + fixture "FPT Telecom" fixed-line → NOT mobile |

## Verifier CONFIRMED highlights (keep — they save re-derivation)

Old-JS+new-API deploy skew structurally safe (server strips coords → old funnel falls to text card; city never sent). NOT_THE_USER 5-member client set has no server gap (server emits only relay/datacenter/isp/network/company). `reason: country_disagreement` has zero existing client readers. `ip_family` instrumentation survives all planned paths. Mock fixture E1 re-derived: AS15169 → eyeball → company → map row 1 (step 19 licence = pure hazard). Blast-radius arithmetic 12 files / 7 test files correct.

## Loop health

Cycle-over-cycle: design + 7 locked decisions untouched 2 cycles running; defect class narrowed to plan-text precision (anchors, deletion ranges, gate scoping). New mechanism this supplement: per-gap grep-proof required in the supplement report (anti "declared-applied-but-not").

## Next

Supplement cycle 2 (single plan-agent, opus — all gaps interdependent in one file) → re-validate cycle 3 from V1.
