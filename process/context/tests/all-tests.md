# Testing Context

This file is the canonical testing context entrypoint for Beam.

## Quick Start

```bash
# Run all backend tests (unit + integration)
./scripts/test.sh all

# Run only unit tests (no DB required)
./scripts/test.sh unit

# Run only integration tests (requires local Postgres + Redis)
./scripts/test.sh integration

# Run Playwright E2E tests (requires both servers running)
./scripts/test.sh e2e

# Run pytest directly with verbose output
PYTHONPATH=. .venv/bin/python -m pytest tests/unit/ -v --tb=short
PYTHONPATH=. .venv/bin/python -m pytest tests/integration/ -v --tb=short -m integration

# Run specific E2E spec
cd apps/web && npx playwright test e2e/visitors.spec.ts
```

## Test Runners

### Backend: pytest 8+ with pytest-asyncio

**Config location:** `pyproject.toml`

- `asyncio_mode = "auto"` — no need for `@pytest.mark.asyncio` on every test
- `asyncio_default_fixture_loop_scope = "function"` — fresh event loop per test
- `testpaths = ["tests"]`
- Markers: `unit` (no DB/network), `integration` (requires Postgres + Redis)
- Dependencies: pytest, pytest-asyncio, httpx, fakeredis

### Frontend E2E: Playwright 1.60

**Config location:** `apps/web/playwright.config.ts`

- Test directory: `apps/web/e2e/`
- Sequential execution (`fullyParallel: false`, `workers: 1`)
- Timeout: 60 seconds per test
- Retries: 2 in CI, 0 locally
- Auth: shared `setup` project runs `auth.setup.ts` first, stores state in `e2e/.auth/user.json`
- Two web servers auto-started: FastAPI on :8000, Next.js on :3000
- CI note: `source .venv/bin/activate` fails in CI — config uses conditional command

## Test File Inventory

### Unit Tests (`tests/unit/`)

| File | What It Tests |
|------|---------------|
| `test_bot_filter.py` | Bot detection from User-Agent strings |
| `test_company_resolver.py` | IP-to-company resolution logic |
| `test_geoip.py` | GeoIP lookup service |
| `test_intent_score.py` | Visitor intent scoring algorithm |
| `test_pixel.py` | Pixel event parsing and validation |

### Integration Tests (`tests/integration/`)

| File | What It Tests |
|------|---------------|
| `test_events_ingest.py` | Event ingestion API endpoint with real DB |
| `test_visitor_aggregation.py` | Visitor aggregation job with real DB |

### E2E Tests (`apps/web/e2e/`)

| File | What It Tests |
|------|---------------|
| `auth.setup.ts` | Authentication setup (Clerk), stores session for other specs |
| `onboarding.spec.ts` | New user onboarding flow |
| `dashboard.spec.ts` | Main dashboard page |
| `visitors.spec.ts` | Visitor list and detail pages |
| `companies.spec.ts` | Company list and detail pages |
| `social.spec.ts` | Social account connection and feed |

## Test Fixtures (`tests/conftest.py`)

| Fixture | Scope | What It Provides |
|---------|-------|-----------------|
| `test_engine` | function | Async SQLAlchemy engine, creates ALL tables on setup, drops ALL on teardown |
| `test_db` | function | Transactional AsyncSession that rolls back after each test |
| `test_client` | function | httpx AsyncClient with ASGI transport (no real HTTP) |
| `auth_token` | function | Legacy HS256 JWT token for authenticated endpoint testing |

### Fixture Gotchas

- **`test_engine` imports all models explicitly** — required for SQLAlchemy relationship resolution. If you add a new model, add its import to `conftest.py`.
- **`ASGITransport` does NOT run ASGI lifespan** — the inline ALTER TABLE migrations in `main.py` don't run during tests. The `test_engine` fixture handles table creation instead.
- **`auth_token` uses legacy HS256 JWT** — production uses Clerk RS256 tokens. Tests bypass Clerk auth.

## Environment for Tests

Tests set these env vars automatically via `conftest.py`:

```
APP_ENV=test
MOCK_EXTERNAL_APIS=true
DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5432/retarget_agent_test
REDIS_URL=redis://localhost:6379/15
```

Note: integration tests use DB 15 in Redis (isolated from dev on DB 0).

## Infrastructure for Tests

Integration tests require local services:

```bash
# Start test infrastructure
docker compose -f infra/docker-compose.yml up -d postgres redis

# Verify postgres is ready
pg_isready -h localhost -p 5432
```

The test script (`scripts/test.sh`) auto-starts Docker services if Postgres isn't reachable.

## Known Test Gaps

- No tests for social account OAuth flows (Twitter, LinkedIn, TikTok, Facebook, Instagram)
- No tests for AI draft generation (OpenRouter / Anthropic integration)
- No tests for Celery task orchestration (enrichment pipeline, feed sync)
- No tests for Clerk RS256 auth path (tests use legacy HS256 JWT)
- No tests for the scheduler (`jobs/scheduler.py`)
- No tests for CSV export, email sending, or campaign execution
- Frontend has no unit/component tests (only E2E via Playwright)
- E2E auth setup depends on Clerk test environment being available

## Playwright Anti-Patterns (Learned from CI Failures)

These rules are documented in the root `CLAUDE.md` and enforced here:

1. **Never use `waitForTimeout()` + `isVisible()`** — use `expect(locator).toBeVisible({ timeout: 15_000 })` instead
2. **Always add `.first()` when using `.or()` with `toBeVisible()`** — Playwright strict mode requires exactly 1 element
3. **Use specific selectors** (e.g., `h2:has-text('Drafts')`) instead of generic `text=Draft`
4. **Always read actual source before writing tests** — never assume page content
5. **`is_bot("")` returns True** — requests without User-Agent get 204'd silently
6. **User model column is `hashed_password`** not `password_hash`

## Running Tests in CI

- All Python deps must be in `requirements.txt` (not just pyproject.toml optional deps)
- Playwright needs `npx playwright install chromium` before first run
- `source .venv/bin/activate` fails in CI — playwright.config.ts handles this with `process.env.CI` conditional
