# PVL Iteration 003 — site-analysis-onboarding

- **Date:** 2026-08-13
- **Loop:** PVL, cycle 2 supplement applied (fix leg of cycle 2)
- **Fix agent:** vc-plan-agent (supplement mode, opus)
- **Result:** SUPPLEMENT_APPLIED — 22 gaps addressed; plan 1205→1481 lines; SPEC gained `## Amendments` (AC-1 v2); validator 0 failures

## Key structural changes

- **Two-slot storage (D4 rewritten):** new 5th column `site_profile_candidate` JSONB — task writes ONLY candidate; PUT promotes → `site_profile` + NULLs candidate; sole writer of confirmed slot. AC-8 gate: confirmed profile byte-identical across a re-run.
- **D11 budget ownership:** task owns single increment; POST check-only; `test_budget_counter_delta_is_one_per_post_cycle` (mock OFF, raw Redis delta==1); TOCTOU accepted as R11.
- **D12 in-flight guard:** `_analysis_inflight: set[str]` per events.py precedent; POST-while-pending ⇒ `already_running`, no side effects.
- **D13 fail-safe:** `apply_description` defaults False; absent currentDescription never overwrites.
- **D14 budget NOT BYOK-exempt** (system Gemini key, paid-OSINT precedent) — also enables N5 fix (plain Redis GET per poll, no DB roundtrip).
- **V5:** panel mounts on `done` step too; AC-7 gate = honest end-to-end (create→ready→confirm→segmenter prompt).
- V6 hostname validation + plain-text render; V8 `meta.v: 1`; C11 real 512KB posture (Content-Length pre-check + truncation, chunked residual accepted); C14 constants ordered 240s poll > 180s stale > ~120s latency; C15 terminal-on-denial; N1 401-accepted flag posture; N2 byte-identical scoped backend-only.

## Concerns flagged for cycle 3

1. Counter-delta gate must actually stay offline with mock OFF — verify patching instructions sufficient.
2. React unmount half of V5 rests on Clerk-blocked Playwright leg (structural gap, recorded).
3. Two-slot PUT promote/NULL semantics — needs adversarial pass.

## Next

Re-validate cycle 3 from V1 + parallel adversarial verifier focused on promote/NULL path + counter-delta gate offline-ness.
