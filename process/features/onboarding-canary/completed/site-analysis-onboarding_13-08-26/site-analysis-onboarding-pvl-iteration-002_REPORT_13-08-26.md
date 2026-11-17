# PVL Iteration 002 — site-analysis-onboarding

- **Date:** 2026-08-13
- **Loop:** PVL (plan-validate-fix), cycle 2 = re-validate from V1 + independent adversarial verifier (parallel legs)
- **Verdict:** Gate: BLOCKED (converging: 4 cycle-1 FAILs all verified CLOSED against live source; 2 new validate FAILs + 5 verifier fail-equivalents)

## Validate leg (contract rewritten in plan)

- F1–F4 closure verified against source (platform_detector bare-client confirmed, canonical lane commands, F3 anchors real, mock-first ordering confirmed; `gemini_generate` has NO mock branch — F4 short-circuit is load-bearing).
- NEW **F5**: budget double-increment on POST re-run path (endpoint + task both increment); both AC-10 gates blind (mock returns before task increment).
- NEW **F6**: SPEC AC-1 (site-step content read) deleted by F1 option (a) but AC row silently re-pointed — needs explicit SPEC amendment.
- C10–C15: orphan PlatformDetectResponse line, 512KB cap unachievable via safe_get (fully buffered), BROWSER_HEADERS import source unnamed, step 3.5 targets wrong component (SiteSettingsBody not Dialog), stale=180s vs poll-cap 160s incoherent, budget-denial-in-task leaves pending 3min.

## Adversarial verifier leg (read-only, default-REFUTE)

10 findings (5 fail-equivalent, 5 concern) + 5 nits:
- **V1** AC-8 unimplementable: one-slot schema vs promised "prior profile intact until confirm".
- **V2** = F5 (independent confirmation of budget double-increment + check-then-increment TOCTOU).
- **V3** F3 fix destroyed by resume path: `useState` description lost on reload → silent overwrite returns (PersistedFlow has no description field).
- **V4** POST has no server-side in-flight guard (re-arms started_at, overlapping tasks; events.py precedent HAS `_aggregating` set which plan dropped).
- **V5** results surface lost when pixel verifies before ~120s analysis: InstallStep unmounts on VERIFIED → AC-3→AC-7 chain no-ops; AC-7 gate built on pre-confirmed fixture cannot see it.
- V6 competitor domain = LLM-controlled string, no validation, `strip_url` unused; V7 BYOK uncaps system-key Gemini budget (wrong neighbour copied — osint_paid is the right precedent); V8 no JSONB schema version; V9 stale PlatformDetectResponse text ×2; V10 SiteAnalysisOut missing `message`/`is_byok`.
- N1 flag-check-before-DB impossible (Depends resolves first; 401-vs-404 note); N2 web not byte-identical flag-off (panel fires GET regardless); N3 BROWSER_HEADERS coupling; N4 blast count off by one (e2e spec); N5 4s poll → DB roundtrip per poll via is_full_byok.

## Orchestrator decisions for cycle-2 supplement

- **V1 → option (a):** add `site_profile_candidate` JSONB column; async run writes candidate, GET surfaces for review, PUT promotes to `site_profile`.
- **F5/V2 → task owns the single increment;** POST endpoint only checks (no increment, no re-stamp); add Redis-counter-delta==1 gate across full POST→task cycle + explicit mock-mode counter statement.
- **V3 → fail-safe default:** absent `currentDescription` ⇒ UNKNOWN ⇒ `apply_description=false`; settings passes `site.description` from `SiteSettingsBody`; onboarding useState plumbing stays as enhancement only.
- **V4 → server-side guard:** POST while derived-pending returns current state + `already_running`, no increment/re-stamp/fire; mirror `events.py` `_aggregating` set.
- **V5 → panel also mounts on `done` step** (one extra mount point) + honest end-to-end AC-7 integration leg (create→ready→confirm→segmenter prompt).
- **V6 → hostname validation** for competitor domains (null on fail), render plain text never anchors. **V7 → budget NOT BYOK-exempt** (system key, osint_paid precedent). **V8 → `meta.v: 1`.** **F6 → SPEC AC-1 amendment** written into SPEC + Plan Deviations. C10–C15, V9, V10, N1–N5 as specified.

## Next

Supplement cycle 2 (vc-plan-agent, opus) → re-validate cycle 3.
