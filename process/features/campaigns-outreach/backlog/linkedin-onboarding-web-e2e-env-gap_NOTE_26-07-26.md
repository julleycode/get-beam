---
name: note:linkedin-onboarding-web-e2e-env-gap
description: "Open gate residual: apps/web Playwright specs for the LinkedIn onboarding wizard could not run at EXECUTE (no Docker → no Postgres; playwright.config webServer also invokes a missing `python` binary). 10 specs written and enumerating, not yet executed."
date: 26-07-26
feature: campaigns-outreach
---

# Open gate: `apps/web && npm run test:e2e` not executed at EXECUTE time

Plan: `process/features/campaigns-outreach/active/linkedin-extension-onboarding_26-07-26/linkedin-extension-onboarding_PLAN_26-07-26.md`
(the plan's own `## Validate Contract` → Open gaps already predicted this exact residual).

## What is unproven

These validate-contract rows have their specs **written and enumerating** but **not executed**:

| Row | Spec |
|---|---|
| AC1, AC13 | `apps/web/e2e/linkedin-connect-wizard.spec.ts` |
| AC2, AC3, AC4 | same |
| AC7, AC8, AC10, AC11, AC12 | same |
| AC9 (Safari dead-end) | same (`test.use({ userAgent })` block) |
| D8 non-regression | `apps/web/e2e/linkedin-outreach-extension.spec.ts` (2 unmodified + 1 new assertion) |

`npx playwright test --list` confirms all 13 tests across the 3 files parse and enumerate, and
`npx tsc --noEmit` covers `e2e/**/*.ts` (tsconfig `include` is `**/*.ts`) — so this is an execution
gap, not a syntax/typing gap.

## Exact blockers observed

1. **`webServer` API leg cannot start:**
   ```
   [WebServer] /bin/sh: python: command not found
   Error: Process from config.webServer was not able to start. Exit code: 127
   ```
   `apps/web/playwright.config.ts` invokes `python -m uvicorn ...` on both the CI and non-CI
   branches; this machine only has `python3` / `.venv/bin/python3.11`. Pre-existing harness issue,
   not introduced by this plan.
2. **No Docker daemon** → no Postgres → even with the API started, `e2e/auth.setup.ts` cannot
   provision the test user, so no dashboard route renders authenticated.
   ```
   docker info → docker:DOWN
   ```
3. The dev stack described in the EXECUTE handoff (API :8000, web :3000, fake phantommm :9100) was
   **not running** at EXECUTE time — all three ports returned no response (`curl` exit 7).

## What WAS proven at EXECUTE

- `cd apps/extension && npm test` — 13/13 pass (includes 4 new AC5 probe key-presence tests).
- `cd apps/extension && npm run build` — clean.
- `cd apps/extension && npm run test:e2e` — 10/10 pass (7 pre-existing + 3 new
  `session-check.spec.ts`, covering AC5 + AC6 including the non-Beam-origin rejection).
- `cd apps/web && npx vitest run` — 45/45 pass (6 new `computeWizardStepIndex` /
  `isChromeOrEdgeUserAgent` branch tests).
- `cd apps/web && npx tsc --noEmit` — clean.
- `cd apps/web && npm run lint` — clean.
- `git diff apps/extension/manifest.json` — empty (zero new permissions).

## To close this gap

Run in an environment with Docker + a working `python` on PATH:

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis
cd apps/web && npm run test:e2e
```

Consider also fixing `playwright.config.ts` to use `python3` (or the venv interpreter) — that is a
separate, pre-existing harness fix and deliberately NOT bundled into this plan's changeset.
