# PVL iteration 001 — reveal-display-policy

**Date:** 17-08-26
**Loop:** plan-validate (PVL), cycle 1
**Verdict in:** `Gate: BLOCKED` (4 FAIL / 4 CONCERN / 7 NOTE)
**Supplement out:** 8/8 gaps applied, validator 0 failures

## Cycle summary

First-pass validate found the design sound (all 7 locked user decisions correctly encoded, none re-litigated) but the checklist under-specified on 4 FAIL-class gaps:

| Gap | Class | Fix applied |
|---|---|---|
| F1 funnel's own `chooseRevealMode`/`hasUsableGeo` (`onboarding-steps.js:187-195`, `wantsMap` :461) unaddressed | client decider bypass | step 25a: funnel consumes `res.display_mode`, same precedence as step 22, fallback to old logic when absent |
| F2 `CanaryGeo` required `lat/lng/accuracy_km` absent in country mode; `canary-map.tsx` + `onboarding-flow.tsx:248` (NaN → posts `lat: null`) missing from blast radius | lying type contract | steps 20a-c: fields optional, lint-enumerated call sites, `CanaryMap` prop narrowed to required-coords; both files in Touchpoints |
| F3 D6 no-jargon scan bans "IP" while plan retained `formatConfidenceNote` ("two IP databases…") | self-contradictory gate | DELETE the function (verified dead: only caller is map-path `canary-reveal.tsx:47`, unreachable once `low` never maps); scan semantics normative (case-sensitive IP/ASN, case-insensitive the rest) |
| F4 AC-7 mis-tiered Agent-Probe on Clerk auth blocker that does not apply (funnel route public, `next.config.mjs:58`; `onboarding-canary.spec.ts` exists un-guarded) | wrong evidence tier | re-tiered Fully-Automated, step 31a public-funnel Playwright leg, backlog stub shrunk to real-network residual |

CONCERNs C5-C8 (crosscheck `:130` unpack, Design snippet `country_agreed`, `reason` precedence, AC-4 proving test) all applied — see supplement transcript in plan file.

## Empirically cleared by validate cycle 1 (no longer risks)

- Demo surface **is** flag-gated: `_require_location_reveal` (`demo.py:381`), `location_reveal_enabled=False` (`config.py:1375`) — nothing ships live on deploy.
- Mock mode already lands map row 1: `classify_org_kind("AS15169 Mock AS") = "eyeball"` → `kind="company"`. Step 19's fixture-mutation licence should NOT fire.
- Redis `geoipx:` stale-entry compat holds; vitest present; 33 crosscheck tests green; containers up (5433/6379) so no Hybrid deferral is legitimate.

## Open leftovers (deliberately NOT edited — scope fencing)

- N3: step 24 wording "remove wide-circle from `canary-reveal.tsx`" imprecise.
- E1: step 19 licence to mutate `_mock_geo` — should not fire per above.
Both covered by execute-agent instructions E-1/E-3; re-check at cycle 2.

## Next

Re-validate from V1 (cycle 2) + parallel external adversarial verifier (REFUTE-mission, fable) — the leg that historically finds the top defect this repo's single-pass validates miss (see memory: `validate-agent-no-agent-tool-needs-external-fanout`).
