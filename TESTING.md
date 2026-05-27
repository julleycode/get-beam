# Testing Guide

## Quick Start

```bash
# Run all unit tests (no DB needed)
./scripts/test.sh unit

# Run integration tests (needs PostgreSQL + Redis)
./scripts/test.sh integration

# Run Playwright E2E tests (needs API + frontend running)
./scripts/test.sh e2e

# Run everything
./scripts/test.sh all
```

## Test Structure

```
tests/
├── unit/                          # No DB, no network — pure function tests
│   ├── test_bot_filter.py         # Bot detection (81 test cases)
│   ├── test_company_resolver.py   # rDNS domain extraction
│   ├── test_intent_score.py       # Visitor intent scoring
│   ├── test_geoip.py             # GeoIP resolution (mocked)
│   └── test_pixel.py             # Pixel JS content verification
├── integration/                   # Requires PostgreSQL + Redis
│   ├── test_events_ingest.py     # Event ingestion API
│   └── test_visitor_aggregation.py # Session counting + IP propagation
└── conftest.py                    # Shared fixtures

apps/web/e2e/                      # Playwright E2E tests
├── auth.setup.ts                  # Login and save auth state
├── onboarding.spec.ts            # Onboarding + pixel installation flow
├── dashboard.spec.ts             # Dashboard page, stats cards
├── visitors.spec.ts              # Visitors list + detail
├── companies.spec.ts             # Company identification (new)
└── social.spec.ts                # EasyEngage: social accounts, drafts, feed
```

## Running Tests Manually

### Backend Unit Tests

```bash
# No setup needed — runs against pure functions
cd /path/to/retarget-agent
PYTHONPATH=. .venv/bin/python -m pytest tests/unit/ -v
```

### Backend Integration Tests

```bash
# Start local services
docker compose -f infra/docker-compose.yml up -d postgres redis

# Run integration tests
PYTHONPATH=. .venv/bin/python -m pytest tests/integration/ -v -m integration
```

### Playwright E2E Tests

```bash
# Start both API and frontend (in separate terminals, or use the webServer config)
cd apps/web
npx playwright test              # headless
npx playwright test --headed     # see the browser
npx playwright test --ui         # interactive Playwright UI
```

## Adding New Tests

### Backend Unit Test

1. Create `tests/unit/test_<feature>.py`
2. Import the function you want to test
3. Write tests with `pytest` — no special setup needed
4. Run: `pytest tests/unit/test_<feature>.py -v`

### Playwright E2E Test

1. Create `apps/web/e2e/<feature>.spec.ts`
2. Use `test` and `expect` from `@playwright/test`
3. Auth state is automatically loaded (see `auth.setup.ts`)
4. Run: `cd apps/web && npx playwright test <feature>.spec.ts`

## CI Pipeline

Tests run automatically on every PR via GitHub Actions (`.github/workflows/test.yml`):

| Job | What it runs | Services needed |
|-----|-------------|----------------|
| `backend-unit` | `pytest tests/unit/` | None |
| `backend-integration` | `pytest tests/integration/` | PostgreSQL, Redis |
| `e2e` | `npx playwright test` | PostgreSQL, Redis, API, Frontend |

Failed E2E runs upload screenshots + traces as artifacts for debugging.

## Environment Variables for Tests

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_ENV` | `test` | Identifies test environment |
| `MOCK_EXTERNAL_APIS` | `true` | Prevents calling real APIs |
| `DATABASE_URL` | `...localhost:5432/retarget_agent_test` | Test database |
| `REDIS_URL` | `redis://localhost:6379/15` | Redis DB 15 for test isolation |
