---
name: context:all-tests
description: "Test runners, commands, and debugging gotchas — the tests group entrypoint/router"
keywords: tests, pytest, playwright, e2e, integration, unit, verify, flaky, coverage, debugging, CI
related: []
date: 21-07-26
---

# Beam - All Tests

Last updated: 21-07-26

Attach this file first when the task involves testing, verification, or test debugging.

This is the fast operator guide for the testing surface: which runner to use, what command to start with, how to quickly debug common failures, and which deeper file to read next.

---

## What This Covers

- test runner selection (pytest unit lane / pytest integration lane / Playwright e2e)
- quick commands
- fast debugging procedures + hard-won gotchas
- current testing gaps

## Read This When

- running tests after implementation
- deciding between test runners
- debugging failing tests or flaky e2e
- writing new tests (READ the Playwright rules below first for e2e)

## Quick Routing

| If you need... | Read next |
|---|---|
| docker-compose setup for integration tests | `TESTING.md` (repo root) |
| e2e spec inventory + auth setup | `apps/web/e2e/` (7 specs + `auth.setup.ts`), `apps/web/playwright.config.ts` |
| shared fixtures (test_client, test_db, env pinning) | `tests/conftest.py` |

## Quick Decision Guide

### Use pytest UNIT lane when

- the change is pure logic: services helpers, agents validators, prompt safety, scoring
- no DB or network needed — mocks/monkeypatch only
- fastest signal: ~1.5s for the whole lane

### Use pytest INTEGRATION lane when

- the change touches routers, DB models, auth flow, or the ASGI app end-to-end
- requires local PostgreSQL + Redis (`docker compose -f infra/docker-compose.yml up -d postgres redis`)
- full lane ~4 min; run the touched files first, full lane before closing

### Use Playwright when

- the behavior depends on real navigation, rendering, or dashboard flows
- needs the Next.js dev server; specs live in `apps/web/e2e/`

## Default Verification Order

1. run the narrowest existing automated test
2. unit/integration before browser tests
3. e2e only when the real UI is the thing being verified

## Commands

| Lane | Runner | Command |
|---|---|---|
| unit | pytest | `.venv/bin/python -m pytest tests/unit -m unit -q` |
| integration (all) | pytest | `.venv/bin/python -m pytest tests/ -m integration -q` |
| integration (one file) | pytest | `.venv/bin/python -m pytest tests/integration/test_ai_ask.py -q` |
| e2e | Playwright | `cd apps/web && npm run test:e2e` (`:ui` / `:headed` variants) |
| lint (web) | next lint | `cd apps/web && npm run lint` |

pytest config: `pyproject.toml` — `asyncio_mode=auto`, markers `unit` / `integration`.

## Debugging Quick Reference (learned the hard way — do not relearn)

**Backend/pytest:**
- `tests/conftest.py` pins `GEMINI_API_KEY=""` — the agentic `/ai/ask` loop fails fast to its single-shot fallback in tests; patch `apps.api.services.gemini_client._post_generate` (loop transport) or `apps.api.routers.ai.gemini_generate` (legacy seam) — patching only one path can leave real traffic untested
- `ASGITransport` (httpx) does NOT run ASGI lifespan — fixtures create tables themselves
- `is_bot("")` returns True — requests without a User-Agent get silently 204'd by ingest
- User model column is `hashed_password`, NOT `password_hash`
- All Python deps must be in root `requirements.txt` for CI — no ad-hoc pip installs
- `source .venv/bin/activate` fails in CI — `playwright.config.ts` uses a `process.env.CI` conditional
- Redis async GC prints "Event loop is closed" tracebacks at teardown — noise, not failure; check the pytest summary line
- Handlers passed to `gemini_agent_loop` share one AsyncSession: sequential only, never commit inside a tool handler
- Alembic offline `--sql` dry-run needs an EXPLICIT `<from-rev>:<to-rev>` range in this repo — the `upgrade head --sql` / `downgrade -1 --sql` shorthand fails partway through the chain because `b7d3e9f1a4c2_add_ad_connections.py` calls `sa.inspect(bind)`, unsupported against alembic's offline `MockConnection`; use e.g. `alembic upgrade d5b1f7c3a908:head --sql` scoped past that migration (confirmed at cadence-bot-flag EXECUTE, 26-07-26)

**Playwright rules (canonical — from repeated CI failures):**
1. NEVER `waitForTimeout()` + `isVisible()` — use `await expect(locator).toBeVisible({ timeout: 15_000 })` (auto-retry)
2. ALWAYS `.first()` when combining `.or()` with `toBeVisible()` (strict mode resolves to exactly 1 element)
3. Use specific selectors (`h2:has-text('Drafts')`) — bare `text=Draft` matches nav + heading + button
4. READ the actual component source before writing selectors — never assume rendered text
5. Stop the dev server port conflict before e2e runs

## Known Gaps

- `CAMPAIGN_PLANNER_TOOLS_ENABLED=true` path (planner tool loop) has no live-model test — validate before enabling in prod
- No automated test hits Gemini with a real key (deliberate — quota); real-key smoke is manual: ask `/ai/ask` a stats question, check `gemini_tool_call` in structlog
- e2e specs cover dashboard/blog/onboarding/social/visitors/companies — no e2e for billing or exports
- ClickHouse paths have no dedicated integration tests (events tested against the ingest API layer)
