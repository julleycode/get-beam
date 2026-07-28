# Code Standards

Last updated: 2026-07-28

## Overview

Conventions observed across the Beam monorepo. Prefer matching existing patterns over introducing new ones.

## Repository Conventions

| Topic | Convention |
|-------|------------|
| Monorepo apps | `apps/{api,web,pixel,extension}` |
| Python package root | Repo root (`PYTHONPATH=.`); imports like `from apps.api...` |
| Python deps | `requirements.txt` at repo root (not under `apps/api/`) |
| Plans / agent context | `process/` (not `docs/` or `plans/`) |
| Human docs | `docs/` (this folder) |

## Python (`apps/api`)

### Style

- Type hints on public functions and service methods
- Pydantic v2 models for all API request/response schemas (`schemas/`)
- SQLAlchemy 2.0 async style (`async_session`, `select()`)
- Structured logging via **structlog** (no secret locals in tracebacks—`plain_traceback` formatter)
- Settings via **pydantic-settings** in `config.py` (env vars, never hardcoded secrets)

### Layout

```
apps/api/
├── routers/     Thin HTTP layer — validate, call service, return schema
├── services/    Business logic (no FastAPI imports in pure helpers)
├── models/      SQLAlchemy ORM
├── schemas/     Pydantic I/O
├── agents/      AI prompts, segmentation, planner logic
├── tasks/       Celery task definitions
├── jobs/        APScheduler job wrappers
└── migrations/  Alembic versions
```

### Database naming

| Element | Pattern | Example |
|---------|---------|---------|
| Tables | snake_case, plural | `visitors`, `campaigns` |
| Columns | snake_case | `site_id`, `created_at` |
| Foreign keys | `{entity}_id` | `visitor_id` |
| Indexes | `idx_{table}_{column}` | (where used) |

### API design

- REST under `/api/v1/{resource}`
- JSON responses; proper HTTP status codes
- Router registration in `main.py` with tags
- Rate limiting via **slowapi** on hot paths
- Feature flags in `Settings` — most new capabilities default `False`

### Error handling

- Never swallow exceptions in jobs/schedulers without `logger.exception`
- External API calls assume failure—retry or degrade explicitly
- Production config validation in `Settings.validate_production()` blocks unsafe defaults

### AI layer rules

- All Gemini calls through `services/gemini_client.py`
- Visitor-derived prompt text must pass `agents/prompt_safety.py` (`clean_text`, `wrap_untrusted`)
- Tool handlers in agent loops: read-only, tenant-scoped, no commit/flush on shared session

### Async work

| Mechanism | Status | Use |
|-----------|--------|-----|
| APScheduler (`jobs/scheduler.py`) | **Live** | Feed sync, resolution sweep, retention, digests |
| Celery (`tasks/`, `celery_app.py`) | **Dormant** | Gated by `celery_worker_enabled=false` |
| `asyncio.create_task` | Select paths | Inline background work when Celery off |

## TypeScript / React (`apps/web`)

### Style

- **Strict TypeScript** — avoid `any`
- Next.js 14 **App Router** (`src/app/`)
- Client API access centralized in `src/lib/api.ts`
- Forms: **react-hook-form** + **zod**
- Server state: **TanStack Query** where used
- UI: **shadcn/ui** + Radix primitives + Tailwind

### Layout

```
apps/web/src/
├── app/           Routes, layouts, globals.css
├── components/    Feature + ui/ components
└── lib/           api.ts, hooks, utils (cn from tailwind-merge)
```

### Auth

- **Clerk** when `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` set
- Legacy JWT login/signup still supported via API
- `ClerkTokenSync` bridges Clerk session to API client

### Testing

- **Vitest** for unit tests (limited coverage)
- **Playwright** for E2E (`e2e/`, shared `auth.setup.ts`)

## Pixel (`apps/pixel`)

- Vanilla IIFE, no bundler dependencies in tracker
- Strict mode, early exit on `navigator.webdriver`
- First-party cookie `_rta_vid` + localStorage fallback
- Batch POST to `/api/v1/events/ingest`

## Extension (`apps/extension`)

- MV3, esbuild build
- No backend surface—dashboard handoff only

## Tests (`tests/`)

| Marker | Location | Rule |
|--------|----------|------|
| (default) | `tests/unit/` | No DB, no network |
| `@pytest.mark.integration` | `tests/integration/` | Requires PG + Redis |

Config: `pyproject.toml` (asyncio mode, markers).

## Git & commits

- Conventional commits encouraged (`feat`, `fix`, `docs`, `test`, `chore`, etc.)
- Working branch: `main` (per harness policy)
- Do not commit secrets or `.env` contents

## Security practices (observed)

- PII columns encrypted; blind indexes for lookup
- BYOK API keys encrypted with `ENCRYPTION_KEY`
- Webhook auth: URL tokens (Gumroad), Stripe signature (legacy)
- CORS configured in `main.py` for frontend origin
- Prompt injection defenses mandatory for AI features

## References

- [codebase-summary.md](./codebase-summary.md)
- `process/development-protocols/implementation-standards.md` (harness)
- `apps/api/config.py` — full env surface
- `TESTING.md`
