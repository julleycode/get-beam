# Deployment Guide

Last updated: 2026-07-28

## Overview

Beam runs locally via Docker Compose (PostgreSQL + Redis) plus Python API and Next.js dev servers. Production API deploys to **Railway** via root `Dockerfile`. The tracking pixel can be served from the API static mount or a **Cloudflare Worker** edge proxy.

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.12+ (local); **3.11** in production Docker image |
| Node.js | 18+ |
| Docker & Docker Compose | For local PG + Redis |
| Git | Clone `get-beam` monorepo |

## Local Development

One-command:

```powershell
# Windows
.\scripts\dev-local.ps1
```

```bash
# macOS / Linux
chmod +x scripts/dev-local.sh && ./scripts/dev-local.sh
```

Env templates: root [`.env.example`](../.env.example) → `.env`; web [`apps/web/.env.example`](../apps/web/.env.example) → `apps/web/.env.local`.

Full Local → UAT → PROD: [local-uat-prod.md](./local-uat-prod.md). Branch workflow, Slack UAT notifications, and GitHub Issues: [dev-workflow-slack-issues.md](./dev-workflow-slack-issues.md).

### Windows local (verified)

**Verified run:** 2026-07-28 on Windows 10/11 with Docker Desktop.

| Item | Value |
|------|-------|
| Script | `scripts/dev-local.ps1` |
| API health | `GET http://localhost:8000/health` → `{"status":"ok"}` |
| Web | `http://localhost:3000` → HTTP 200 |
| Migrations | `alembic upgrade head` applied (including `request_logs`) |
| Demo (after seed) | `demo@retargetagent.com` / `password123` |

#### Script flags

| Flag | Effect |
|------|--------|
| *(none)* | Full setup: env copy, Docker, venv + pip, npm install, migrate, start API + Web in new PowerShell windows |
| `-SkipInstall` | Skip `pip install` and `npm install` — use when deps are already installed |
| `-MigrateOnly` | Run migrations only; do not start API/Web |
| `-NoBrowser` | Do not auto-open `http://localhost:3000` |

```powershell
.\scripts\dev-local.ps1
.\scripts\dev-local.ps1 -SkipInstall
.\scripts\dev-local.ps1 -MigrateOnly
.\scripts\dev-local.ps1 -NoBrowser
```

**First run:** allow full `npm install` in `apps/web`. If you use `-SkipInstall` and the web server fails to start, run `npm install` manually in `apps/web`, then re-run the script.

| Demo credentials | `demo@getbeam.fyi` / `password123` (created by `scripts/ensure_demo_user.py`) |
| Auth without Clerk | Leave `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` empty → use **`/login`** (JWT). `/sign-in` redirects to `/login`. |
| Auth with Clerk | Set Clerk publishable + secret keys → use `/sign-in` |

#### Local auth note (2026-07-28)

Prod retired the JWT `/login` UI (it only redirected to Clerk `/sign-in`). With empty Clerk keys that left local showing **"Sign-in is temporarily unavailable (authentication is not configured)"**. Restored: when Clerk is unset, `/login` and `/signup` use `/api/v1/auth/login|signup`; `dev-local.*` runs `ensure_demo_user` automatically.

#### Critical Windows gotcha: port 5433

Docker Compose maps Beam Postgres to **host port 5433** (container 5432). See `infra/docker-compose.yml`.

Many Windows machines run a native PostgreSQL service (e.g. `postgresql-x64-18`) on **`:5432`**. If `DATABASE_URL` points at `localhost:5432`, connections hit the **Windows Postgres instance**, not Docker Beam DB. Symptom: `InvalidPasswordError` for user `retarget` (that user exists only in the Docker container).

**Fix:** always use **`:5433`** for local Beam development:

```
postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent
```

This matches the default in `.env.example`. The dev script waits for Postgres on `:5433` before migrating.

To check what owns `:5432`:

```powershell
Get-Service -Name "*postgres*" -ErrorAction SilentlyContinue
Test-NetConnection localhost -Port 5432
Test-NetConnection localhost -Port 5433
```

#### Windows troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| `InvalidPasswordError` for `retarget` | `DATABASE_URL` uses `:5432` | Set port **5433** in `.env`; restart API |
| `docker compose failed` | Docker Desktop not running | Start Docker Desktop; retry |
| Postgres not reachable on `:5433` | Port conflict or slow start | `docker compose -f infra/docker-compose.yml ps`; wait or `docker compose ... up -d postgres redis` |
| Web won't start after `-SkipInstall` | Missing `node_modules` | `cd apps/web && npm install` |
| `ABORT: .env DATABASE_URL looks remote` | `.env` points at Railway/Supabase | Use localhost URLs for local dev |
| API window closes immediately | venv or pip failure | Re-run without `-SkipInstall`; check `.venv\Scripts\python.exe` |
| Alembic fails | Wrong DB or Docker down | Confirm `:5433` and `docker compose ps` shows postgres healthy |

Optional seed after stack is up:

```powershell
.\.venv\Scripts\python.exe -m scripts.seed
```

Stop API/Web: close the two PowerShell windows opened by the script. Stop Docker services:

```powershell
docker compose -f infra/docker-compose.yml stop
```

### 1. Infrastructure

```bash
cd infra
docker compose up -d
```

Services (`infra/docker-compose.yml`):

| Service | Image | Ports | Notes |
|---------|-------|-------|-------|
| postgres | postgres:16-alpine | **5433→5432** | DB `retarget_agent`, user `retarget` (host port **5433** — avoids native Postgres on 5432) |
| redis | redis:7-alpine | 6379 | Cache / broker |
| clickhouse | clickhouse-server:24 | 8123, 9000 | **Optional** — unused by live API |

Default Postgres URL (matches `config.py` default):

```
postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent
```

> **Windows note:** if you have PostgreSQL installed as a Windows service on `:5432`, Docker maps Beam DB to **`:5433`**. Do not point `DATABASE_URL` at `:5432` unless you intentionally use that native instance.
### 2. API

```bash
cd apps/api
python -m venv venv
# Windows: venv\Scripts\activate
# Unix: source venv/bin/activate
pip install -r ../../requirements.txt

# From repo root — apply migrations
alembic -c apps/api/alembic.ini upgrade head

# Optional seed (needs running Postgres)
python -m scripts.seed

# Start API (from repo root)
cd ../../
PYTHONPATH=. uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: `GET http://localhost:8000/health`

**Background jobs:** APScheduler starts inside the FastAPI process (`jobs/scheduler.py`). No separate worker required for feed sync, resolution sweep, or retention.

### 3. Web dashboard

```bash
cd apps/web
npm install
npm run dev
```

Default: `http://localhost:3000`

### 4. Celery (optional — dormant by default)

Celery is **not required** for normal development. `celery_worker_enabled=false` in config; Dockerfile CMD is alembic + uvicorn only.

If explicitly testing Celery:

```bash
cd apps/api
celery -A apps.api.services.celery_app worker -l info
celery -A apps.api.services.celery_app beat -l info
```

Set `CELERY_WORKER_ENABLED=true` only when a worker process is actually running.

### Demo credentials (seed)

| Field | Value |
|-------|-------|
| Email | `demo@retargetagent.com` |
| Password | `password123` |

## Environment Variables

Copy from `infra/.env.example` if present, or configure per `apps/api/config.py` and `apps/web` needs.

### API (representative)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Async Postgres URL |
| `REDIS_URL` | Redis connection |
| `APP_SECRET_KEY` | JWT / session signing |
| `GEMINI_API_KEY` | Primary AI |
| `SENDGRID_API_KEY` | Email send |
| `CLERK_*` / JWT settings | Auth |
| `GUMROAD_*` | Active billing webhooks + checkout URLs |
| `FRONTEND_URL` / `API_BASE_URL` | CORS + redirects |

Production: `APP_ENV` must not be `development|test|local|ci` without setting encryption keys (`validate_production()`).

### Web

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk (optional) |
| `NEXT_PUBLIC_API_URL` | API base (e.g. `http://localhost:8000`) |
| `NEXT_PUBLIC_SITE_URL` | Canonical site URL |
| `BEAM_FETCH_BEACON_SECRET` | Agent fetch beacon (EvalLayer) |

Never commit `.env` files or secrets to git.

## Pixel Deployment

### Tracker script

Source: `apps/pixel/src/tracker.js`

Install snippet pattern (attributes):

- `data-site` — site ID
- `data-api` — API origin (optional; defaults from script origin)

Endpoint: `POST {API_URL}/api/v1/events/ingest`

### Cloudflare Worker

`apps/pixel/src/worker.js` proxies ingest to the API from the edge. Deploy to Cloudflare Workers for global CDN delivery (original roadmap target).

Onboarding assets and copy-paste snippets also live under `apps/web/public/beam/`.

## Chrome Extension

Build and load unpacked from `apps/extension/` (MV3). Used for LinkedIn outreach connect—hands off to dashboard tab, no API credentials in extension.

E2E: `apps/extension/e2e/`

## Production (Railway)

`railway.json` at repo root:

| Setting | Value |
|---------|-------|
| Builder | Dockerfile |
| Health check | `/health` (300s timeout) |
| Restart | ON_FAILURE, max 10 retries |

Typical layout:

| Service | Role |
|---------|------|
| API | Dockerfile → uvicorn + alembic migrate on start |
| Web | Next.js (Vercel or separate Railway service—confirm operator setup) |
| Postgres | Managed Postgres 16 |
| Redis | Managed Redis 7 |

**Note:** Single Railway service config in repo targets API only. Frontend hosting may be Vercel (Analytics import in `layout.tsx` suggests Vercel for web).

Public marketing site: **getbeam.fyi**

## Database Migrations

```bash
alembic -c apps/api/alembic.ini upgrade head
alembic -c apps/api/alembic.ini heads   # confirm single head before prod apply
```

Several feature flags require migrations applied before enable in production. See `process/context/all-context.md` migration chain notes.

## Testing in CI-like setup

See [TESTING.md](../TESTING.md):

```bash
./scripts/test.sh unit
./scripts/test.sh integration   # needs postgres + redis
./scripts/test.sh e2e           # needs API + web running
```

Integration tests use Redis DB `15` for isolation.

## Operational Checklist (production enable)

1. Apply Alembic migrations to head.
2. Set production secrets (`APP_SECRET_KEY`, `ENCRYPTION_KEY`, `TOKEN_ENCRYPTION_KEY`).
3. Configure SendGrid, Gumroad webhook URL with token, Clerk keys.
4. Enable feature flags **only** after migration + smoke validation.
5. Monitor `/health` and structured logs (structlog).

## References

- [local-uat-prod.md](./local-uat-prod.md) — Local → UAT → PROD environments
- [dev-workflow-slack-issues.md](./dev-workflow-slack-issues.md) — Branch naming, Slack UAT notify (proposed), GitHub Issues
- [system-architecture.md](./system-architecture.md)
- [visuals/beam-system-architecture.svg](./visuals/beam-system-architecture.svg)
- `infra/docker-compose.yml`
- `Dockerfile`, `railway.json`
- `TESTING.md`, `process/context/tests/all-tests.md`
