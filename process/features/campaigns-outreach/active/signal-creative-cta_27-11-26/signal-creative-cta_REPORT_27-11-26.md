---
phase: signal-creative-cta-execute
date: 2026-11-27
status: COMPLETE_WITH_GAPS
feature: campaigns-outreach
plan: process/features/campaigns-outreach/active/signal-creative-cta_27-11-26/signal-creative-cta_PLAN_27-11-26.md
---
# signal-creative-cta — EXECUTE report (Lane A)

Note for the orchestrator: the plan file exists only in the main checkout, and this worktree agent cannot write there. Apply the plan edits below when you merge.

## Plan edits to apply
- **Open User Decisions:** the user CONFIRMED all three on 27-11-26:
  - 40% share rule
  - cross-domain CTA URL allowed for `book_demo` only (via `Site.booking_url`)
  - `reply` CTA left untracked (known-gap)

  Replace each "(pending user confirmation)" with "(CONFIRMED 27-11-26)".
- **Status:** CODE DONE. It becomes VERIFIED only after the independent vc-tester EVL run.

## What Was Done
Checklist items 1–11 are implemented. Migration `e9c4a7d2f318`, down_revision `d3f8a2c61b47`.

## Plan Deviations
1. The planner reads `Site.cta_config` and `booking_url` itself, only when a flag is ON. The plan had `routers/campaigns.py` passing them in; reading them in the planner avoids editing the create handler, which the parallel company-exclusion lane is also changing. Same blast radius, and the flag-OFF query sequence is unchanged.
2. `cta_type` is corrected (to an allowed type, else the site default) right after the model's JSON is parsed, not inside `_validate_plan`. The result is the same and deterministic.
3. `tests/unit/test_gmail_sender_decoration_parity.py` now also normalizes UUIDs. Assigning the touchpoint id before compose (C1) gives each run a random id, so the test's two-run comparison broke. The plan's C2 census missed this file's comparison logic.
4. Flag OFF: `{cta_link}` / `{{cta_link}}` always resolve to an empty string. Before, the single-brace form would have been left as literal text. This matches the plan's "empty when unset/flag OFF".
5. The evidence pack and this report sit in the worktree copy of the task folder. They are uncommitted and need to be copied to the main checkout.

## Test Gate Outcomes
See `harness/verification.json`.

## Test Infra Gaps Found
- `tests/unit/test_paid_x402.py`: 4 tests fail on the base tree with or without this change. This is pre-existing (it arrived with the x402 commit) and not in this plan's scope.
- The web `tsc` run used the main checkout's `node_modules`, which lacks `@sentry/nextjs`. That produced pre-existing errors only; none are in files I touched.

## Known Gaps
- Live Gemini quality (Agent-Probe).
- `reply` CTA is not click-attributed.
- Public `/c/` counts can be inflated.
- Clerk Playwright UI legs are not covered.

## Forward Preview
- **Commands to stay green:** the validate-contract gate table.
- **Dependency Changes:** none. `sentry-sdk` was pip-installed into the shared venv from `requirements.txt`.
- **Blast Radius Changes:** none beyond the plan.
