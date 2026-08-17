# PVL Iteration 001 — site-analysis-onboarding

- **Date:** 2026-08-13
- **Loop:** PVL (plan-validate-fix)
- **Cycle:** 1
- **Verdict in:** Gate: BLOCKED (first-pass validate, 4 FAILs / 9 CONCERNs)
- **Fix agent:** vc-plan-agent (PVL supplement mode, opus)
- **Verdict out:** SUPPLEMENT_APPLIED — 13 gap(s) addressed; validator 0 failures / 0 warnings

## Orchestrator decisions this cycle

- **F1 → option (a):** no `platform_detector` refactor at all; `services/site_content.py` is new code only (pinned-client posture per `pixel_verifier.py:122-124`). Sync-path content extraction DROPPED from v1 scope — hybrid timing now = sync platform-detect (existing, unchanged) + async fetch+analysis. C1/C2/C3 resolved by deletion.

## Gaps addressed

| Gap | Resolution |
|---|---|
| F1 | Steps 1.6/1.12 removed; §Security precedent corrected; new empty-diff gate on platform_detector.py + schemas/sites.py |
| F2 | Canonical lane commands (`-m unit`/`-m integration`); baselines measured at EXECUTE start, gate = zero NEW failures |
| F3 | `currentDescription` plumbed onboarding-flow → InstallStep prop → panel; settings passes `site.description` |
| F4 | Mock short-circuit first statement of `run_site_analysis`; `fetch_site_content` own mock branch; AC-11 asserts zero outbound requests |
| C4 | `async_session` (real symbol) replaces nonexistent `async_session_maker` |
| C5 | `monkeypatch.setattr(settings, "mock_external_apis", True)` autouse fixture in step 1.15 |
| C6 | SSRF posture test → existing `tests/unit/test_ssrf_guard.py` |
| C7 | Recorded decision: separate module from content_reader.py (guard posture, no coupling) |
| C8 | Line refs refreshed + anchor-text-not-line-number instruction |
| C9 | Insertion point restated (after `detecting` ternary block) |

## Next

Re-validate from V1 (cycle 2) with independent adversarial verifier leg.
