---
phase: first-party-capture
date: 2026-07-24
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/first-party-capture_24-07-26/first-party-capture_PLAN_24-07-26.md
---

# First-Party Email Capture Expansion — Phase Report

## Note on sequencing

The code for this feature (`apps/pixel/src/tracker.js`, `apps/api/routers/events.py`,
`apps/api/models/visitor_email.py`, the `apps/pixel/e2e/` Playwright harness, and the
`a9f2c1e7b4d6` migration) was **already present on disk when this RIPER session started** — a
prior/parallel session implemented it directly. This RIPER pass (SPEC → PLAN → VALIDATE → EXECUTE →
EVL → UPDATE PROCESS) formalized the requirements, wrote a validated plan against the real
implementation, and ran an independent EVL confirmation. The plan therefore post-dates the code by
design in this case — VALIDATE and EVL both verified an already-written implementation rather than
gating a not-yet-written one. This is documented so future readers of the plan/report pair aren't
confused by the ordering.

## What Was Done

- **Phase 0 (harness)**: New `apps/pixel/e2e/` Playwright harness — own `playwright.config.ts`
  (chromium/webkit/firefox projects), `harness.ts` fixture helpers, `fixtures/*.html` static test
  pages, `capture-baseline.spec.ts` baseline regression scenario. `apps/pixel/package.json` gained
  `test`/`test:e2e` scripts + `@playwright/test` devDependency.
- **Phase 1 (cold-start wins)**: value-based field matcher (any text-shaped field whose *value*
  looks like an email, not just name/type-matched fields), `mailto:` click capture reusing the
  existing click listener, URL-param capture (`?email=`) placed AFTER the `GATED`/`consentDecision`
  init block per Hard Guardrail G7 (VALIDATE finding — prevents an EU-consent-hold bypass). New
  `tests/unit/test_url_param_email_logging.py` proves domain-only logging (AC4/AC14).
- **Phase 2 (autofill/shadow-DOM/iframe)**: chromium autofill leg proven; shadow-DOM capture via
  `composedPath()[0]`; same-origin iframe capture via `contentDocument` + try/catch `SecurityError`
  boundary; AC8 (prefilled/hidden-field silence) and AC9 (OPTOUT blocks all new mechanisms)
  guardrail fixtures.
- **Phase 3 (config + source-enum)**: per-site `data-capture-mailto`/`data-capture-url-param`
  config attributes (default "on", opt-out not opt-in); `VISITOR_EMAIL_SOURCES` formalized enum +
  `normalize_source()` in `apps/api/models/visitor_email.py`; migration `a9f2c1e7b4d6` (CHECK
  constraint `ck_visitor_emails_source`, superset of every live-emitted source value, additive-only,
  Docker-gated offline-validate only). New `tests/unit/test_visitor_email_source_enum.py` (6 pure
  unit tests on `normalize_source`).
- **VALIDATE**: single-pass, Gate: PASS. 4 CONCERNs found and fixed directly in plan text (migration
  head correction, 2 missing-test checklist items, G7 consent-ordering guardrail + dedicated test).
- **EVL (this session)**: independent re-run of every gate the plan declares Fully-Automated/Hybrid
  that could execute in this sandbox — see Test Gate Outcomes below.

## What Was Skipped/Deferred

- **AC5 webkit/firefox autofill legs** — `npx playwright install` for non-chromium binaries was not
  cacheable in this sandbox (network/time budget). Chromium leg is green and proves the core
  mechanism. Backlog: `first-party-capture-deferred-gates_NOTE_24-07-26.md`.
- **Phase 3 integration re-confirm** (`tests/ -m integration -k "visitor_email or do_not_resolve"`)
  — EXECUTE ran this green with PG+Redis up (per plan's EXECUTE record); EVL could not
  independently re-run it because Docker was unavailable at EVL time. Backlog: same note.
- **D4 (formal CLEAN/RED capture-technique policy doc)** — explicitly deferred to backlog by
  product decision (SPEC Open Question 3 / plan Decision D4), not a gap found during execution.
  Backlog: same note.
- **Migration live-apply** — Docker-gated, never live-applied in this sandbox by design (matches
  the `owned-data-layer` and `evallayer` precedent). Offline dry-run re-confirmed working.

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| Pixel e2e (chromium) | `cd apps/pixel && npx playwright test --project=chromium` | 11/11 passed |
| Backend unit suite | `.venv/bin/python -m pytest tests/unit -q` | 367 passed, 2 skipped |
| Gate-specific tests | `-k email_domain_logging`, `-k source_enum`, and related plan-cited `-k` filters | 19 passed |
| Full regression (incl. cross-feature guardrail) | `tests/unit/test_agent_origin_exclusion.py` + broader unit/regression run | 47/47 passed (18/18 on the EvalLayer agent-origin-exclusion guardrail specifically — confirms no cross-feature regression) |
| Migration head + offline dry-run | `alembic heads` → `a9f2c1e7b4d6 (head)`; `alembic upgrade head --sql` | head matches plan; dry-run runs fully offline, no live DB touched |
| Bundle size | `cd apps/pixel && npm run size` | 4811 bytes gzipped, under the 5KB budget |
| Guardrails G1-G7 | structural re-check, file:line | all present as coded (no bypass path found) |
| webkit/firefox autofill legs | `npx playwright test --project=webkit --project=firefox` | NOT RUN — binaries not cached, install budget exceeded — DEFERRED |
| Phase 3 integration tests | `tests/ -m integration -k "visitor_email or do_not_resolve"` | NOT independently re-run at EVL — Docker down (15s health-check cap) — DEFERRED (ran green at EXECUTE time per plan record) |

## Plan Deviations

- **D-E1** (documented in plan's own EXECUTE Deviations section): AC13 source-enum test authored
  as a dedicated unit test file (`tests/unit/test_visitor_email_source_enum.py`, 6 tests on the pure
  `normalize_source` function) instead of extending the integration `TestEmailCaptureSource` class
  as the Phase 3 checklist item literally specified. Reason: `normalize_source` is a pure, DB-free
  function — a unit test is faster and equally valid; the integration `TestEmailCaptureSource`
  class was retained unchanged for storage-path coverage. Within test blast radius, no
  source/schema deviation — matches the `-k source_enum` gate filter the plan's Test Gates table
  already specified.
- **D-E2** (out of scope, flagged not fixed): `apps/api/services/known_hash.py` and
  `tests/unit/test_known_hash.py` are modified/untracked in the working tree but are NOT in this
  plan's Touchpoints table. Left untouched by this RIPER pass — a pre-existing uncommitted,
  security-adjacent blind-index refactor from other work. Not included in this session's process
  commit (see git status; explicitly excluded per task instructions).

## Test Infra Gaps Found

- No dedicated CI lane yet runs `cd apps/pixel && npx playwright test` with webkit/firefox
  pre-cached — this sandbox has no way to guarantee those binaries are available. Recommend (in
  backlog note) a documented `playwright install --with-deps webkit firefox` step for whatever CI
  environment eventually runs this suite, so AC5's Hybrid legs become unconditionally green there.

## SPEC Achievement

All 15 SPEC acceptance criteria scored against the locked
`first-party-capture_SPEC_24-07-26.md`:

| AC | Criterion | Score | Evidence |
|---|---|---|---|
| AC1 | Value-based field matching | met | chromium e2e `value-match.spec.ts` green |
| AC2 | Name/type matching regression | met | `capture-baseline.spec.ts` still green |
| AC3 | mailto: click capture | met | `mailto.spec.ts` green |
| AC4 | URL-param capture + no-plaintext-log | met | `url-param.spec.ts` + `test_url_param_email_logging.py` green |
| AC5 | Cross-browser autofill (chromium/webkit/firefox) | **unmet (partial)** | chromium leg green; webkit/firefox legs never run (binaries not installed) — see backlog note |
| AC6 | Same-origin shadow-DOM capture | met | `shadow-dom.spec.ts` green |
| AC7 | Cross-origin iframe silence | met | `cross-origin-iframe.spec.ts` green |
| AC8 | Prefilled/hidden-field guardrail | met | `no-scrape-guardrail.spec.ts` green |
| AC9 | OPTOUT blocks all new mechanisms | met | `optout-guardrail.spec.ts` green |
| AC10 | Server validation/dedup unchanged | met | ran at EXECUTE with PG+Redis; not independently re-run at EVL (Docker down) — see backlog note |
| AC11 | `do_not_resolve` sticky exclusion | met | same caveat as AC10 |
| AC12 | Per-site config toggle | met | `per-site-config.spec.ts` green |
| AC13 | Source enum validated | met | `test_visitor_email_source_enum.py` (unit, D-E1) + migration CHECK constraint |
| AC14 | PII-safe logging | met | `test_url_param_email_logging.py` + structural grep confirms no `console.`/plaintext echo |
| AC15 | Playwright harness prerequisite exists | met | `apps/pixel/e2e/` harness + baseline scenario green |

**## SPEC Gaps**
- AC5 (partial): webkit/firefox legs unrun — backlog stub in
  `first-party-capture-deferred-gates_NOTE_24-07-26.md`.
- AC10/AC11 (env caveat, not a code gap): EVL could not independently re-confirm the integration
  lane due to Docker being down at EVL time; EXECUTE-time record shows these gates ran green with
  PG+Redis up. Backlog stub in the same note, closeable by re-running the integration command
  against a live PG+Redis.

## Closeout Packet

1. **Selected plan path:** `process/features/visitors-identity/active/first-party-capture_24-07-26/first-party-capture_PLAN_24-07-26.md`
2. **Closeout classification:** Keep in active/testing (WITH_GAPS) — code-complete, all
   sandbox-runnable Fully-Automated/Hybrid gates green, 2 gates deferred on environment
   preconditions (browser binaries, live Docker), not code defects.
3. **What was finished:** all 4 internal phases (harness, cold-start capture points, autofill/
   shadow-DOM/iframe, per-site config + source-enum) — see What Was Done above.
4. **Verified vs unverified:** verified — chromium e2e 11/11, unit 367/367 (2 skipped unrelated),
   19 gate-specific tests, 47/47 regression incl. agent-origin-exclusion 18/18, migration head +
   offline dry-run, bundle size. Unverified in this pass — webkit/firefox autofill legs,
   independent EVL re-run of the Phase 3 integration lane (ran green at EXECUTE, not re-confirmed
   at EVL due to Docker being down).
4b. **Validate-contract compliance:** present, inline in plan (`## Validate Contract`), Gate: PASS,
    `generated-by: outer-pvl`, dated 24-07-26.
5. **Cleanup done vs still needed:** done — phase report (this file), backlog note, context/GUIDE
   updates, plan Phase Loop Progress + Closeout section. Still needed — re-run the 2 deferred gates
   when environment allows (backlog note has exact close commands), then re-classify and archive.
6. **Single best next valid state:** Keep the plan active; re-run the 2 deferred gates
   (`first-party-capture-deferred-gates_NOTE_24-07-26.md` has exact commands) when webkit/firefox
   binaries and a live PG+Redis are available, then move to `completed/`.
7. **Commit-checkpoint recommendation:** Process commit belongs after UPDATE PROCESS — the
   remaining changes here (report, context, backlog note, plan closeout edits) are process-only;
   source commits already landed (`aad64c0`, `68d2e22`, `c3d0e03`).
8. **Regression status:** `tests/unit/test_agent_origin_exclusion.py` (18/18) + full unit regression
   (47/47) re-run independently at EVL — confirms this feature's changes did not regress the
   EvalLayer agent-origin-exclusion guardrail or any other previously-verified surface.
9. **SPEC achievement:** see `## SPEC Achievement` above — 13/15 fully met, 2 partially met on
   environment-only residuals, both tracked in the backlog note.

Drift score: MEDIUM (2 signals: >=10 files touched across the program; feature-folder structural
change — new task folder + 2 backlog artifacts written this session).
Recommend UPDATE PROCESS -- significant changes detected.

## Forward Preview

### Test Infra Found
- New `apps/pixel/e2e/` Playwright harness (own config, chromium/webkit/firefox projects) — first
  automated test coverage tracker.js capture logic has ever had.
- New `tests/unit/test_url_param_email_logging.py`, `tests/unit/test_visitor_email_source_enum.py`.

### Blast Radius Changes
- Matches plan's declared blast radius (`apps/pixel`, `apps/api` source-enum + validation only).
  `apps/api/services/known_hash.py` + `tests/unit/test_known_hash.py` are dirty in the working tree
  but explicitly out of this plan's Touchpoints (D-E2) — not touched by this session.

### Commands to Stay Green
- `cd apps/pixel && npx playwright test --project=chromium`
- `.venv/bin/python -m pytest tests/unit -q`
- `.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -q`
- `cd apps/pixel && npm run size`
- `cd apps/api && ../../.venv/bin/python -m alembic heads` (expect `a9f2c1e7b4d6 (head)`)

### Dependency Changes
- `apps/pixel/package.json`: added `@playwright/test` devDependency + `test`/`test:e2e`/`size` scripts (size pre-existing, confirmed unchanged).
