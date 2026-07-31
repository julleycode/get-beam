# Deployment Guide

Last updated: 2026-08-01

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
| Demo (after seed) | `demo@getbeam.fyi` / `password123` |

#### Script flags

| Flag | Effect |
|------|--------|
| *(none)* | Full setup: env copy, Docker, venv + pip, npm install, migrate, start API + Web in new PowerShell windows |
| `-SkipInstall` | Skip `pip install` and `npm install` — use when deps are already installed |
| `-MigrateOnly` | Run migrations only; do not start API/Web |
| `-NoBrowser` | Do not auto-open `http://localhost:3000` |
| `-NoTunnel` | Do not start/check the named Cloudflare tunnel even when `API_BASE_URL` is public |

```powershell
.\scripts\dev-local.ps1
.\scripts\dev-local.ps1 -SkipInstall
.\scripts\dev-local.ps1 -MigrateOnly
.\scripts\dev-local.ps1 -NoBrowser
.\scripts\dev-local.ps1 -NoTunnel
```

**First run:** allow full `npm install` in `apps/web`. If you use `-SkipInstall` and the web server fails to start, run `npm install` manually in `apps/web`, then re-run the script.

#### Public hostnames on the `nhantown-beam` tunnel (updated 2026-07-29)

One named tunnel now serves three hostnames with deliberately different blast radii. They are not interchangeable — pick by what the caller needs to reach.

| Hostname | Origin | Surface | Use it for |
|----------|--------|---------|-----------|
| `beam-dev.nhantown.com` | API `:8000` | **3 paths only** (`/pixel/tracker.js`, `/api/v1/events/ingest`, `/health/ready`); everything else 404 | The value of `API_BASE_URL`, i.e. the host baked into every pixel snippet |
| `beam-api.nhantown.com` | API `:8000` | Full API, including auth | The dashboard's `NEXT_PUBLIC_API_URL` |
| `beam.nhantown.com` | Web `:3000` | Next.js dashboard | Signing in and adding sites from anywhere |

Before 2026-07-29, `beam.nhantown.com` *was* the pixel-only host. It was promoted to the dashboard so sites can be added without a laptop, and the locked-down surface moved to `beam-dev.nhantown.com`. If an older snippet still points at `beam.nhantown.com/pixel/tracker.js`, regenerate it.

For testing the local tracker from an external website, set root `.env`:

```dotenv
API_BASE_URL=https://beam-dev.nhantown.com
FRONTEND_URL=https://beam.nhantown.com
```

and `apps/web/.env.local`:

```dotenv
NEXT_PUBLIC_API_URL=https://beam-api.nhantown.com
NEXT_PUBLIC_SITE_URL=https://beam.nhantown.com
```

`NEXT_PUBLIC_*` is compiled into the browser bundle, so a `localhost` value there works on this machine and breaks for every other visitor. Restart `npm run dev` after changing it. Revert both files to `localhost` for offline work, or pass `-NoTunnel`.

**Publishing the dashboard changes the threat model.** `/api/v1/auth/login` has no rate limit, and `scripts/ensure_demo_user.py` resets the demo account on every `dev-local` run — so a password changed by hand in the database comes back as `password123` on the next start. Set `BEAM_DEMO_PASSWORD` in the root `.env` instead; the script reads it and stops echoing the value. Signup is also open on the public API: create the accounts you need, then treat the host as reachable by anyone who learns the name.

On Windows, `dev-local.ps1` looks for `%USERPROFILE%\.cloudflared\config-beam.yml`. It requires the host named by `API_BASE_URL` to carry exactly three path-scoped ingress rules — tracker, event ingest, readiness probe — plus its own 404 catch-all; other hostnames in the file are not its concern. The script restarts a matching `cloudflared` process when the config is newer, otherwise reuses it or starts one in the background. Before reporting success, it verifies both the allowed endpoints and a live 404 from `/api/v1/auth/login`.

- `https://beam-dev.nhantown.com/health/ready`
- `https://beam-dev.nhantown.com/pixel/tracker.js`

Example ingress boundary (order matters — cloudflared takes the first match, so the locked-down host must come first):

```yaml
ingress:
  - hostname: beam-dev.nhantown.com
    path: ^/pixel/tracker\.js$
    service: http://127.0.0.1:8000
  - hostname: beam-dev.nhantown.com
    path: ^/api/v1/events/ingest$
    service: http://127.0.0.1:8000
  - hostname: beam-dev.nhantown.com
    path: ^/health/ready$
    service: http://127.0.0.1:8000
  - hostname: beam-dev.nhantown.com      # per-host catch-all, not just the final rule
    service: http_status:404
  - hostname: beam-api.nhantown.com
    service: http://127.0.0.1:8000
  - hostname: beam.nhantown.com
    service: http://127.0.0.1:3000
  - service: http_status:404
```

The script's audit is scoped to the host named by `API_BASE_URL`: it requires exactly those three paths, each pointing at `127.0.0.1:8000`, plus a per-host 404 — and it refuses to start the tunnel if `API_BASE_URL` names the full-API or dashboard host instead. Authentication routes are intentionally not reachable through `beam-dev.nhantown.com`.

**Adding a DNS route: always pass `--config`.** `cloudflared tunnel route dns` without it reads the default `config.yml` and will happily CNAME the hostname to whichever tunnel that file names — silently pointing a Beam host at the studio tunnel. Use:

```powershell
cloudflared tunnel --config "$env:USERPROFILE\.cloudflared\config-beam.yml" route dns --overwrite-dns nhantown-beam <hostname>
```

**Keep hostnames ONE label deep.** Cloudflare Universal SSL issues a certificate for `nhantown.com` and `*.nhantown.com` only. A two-level name like `api.beam.nhantown.com` resolves and reaches the tunnel, but every HTTPS client fails first with `SSLV3_ALERT_HANDSHAKE_FAILURE` — no certificate covers it, and no amount of ingress config helps. That is why the hosts are `beam-api` / `beam-dev` rather than `api.beam` / `dev.beam`. Two-level names require Advanced Certificate Manager (paid).

The real tunnel config and credentials stay in `%USERPROFILE%\.cloudflared\` and must never be committed. Use `-NoTunnel` for local-only work.

The script's internal readiness probes use `127.0.0.1` deliberately. Windows PowerShell 5.1 can resolve `localhost` to IPv6 `::1`, while local Uvicorn listens on IPv4; that mismatch otherwise makes a healthy API wait through the full retry loop.

| Demo credentials | `demo@getbeam.fyi` / `password123`, or `BEAM_DEMO_PASSWORD` from the root `.env` when set (created by `scripts/ensure_demo_user.py`) |
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
| Public snippet still says `localhost:8000` | Root `.env` has local `API_BASE_URL`, or API was not restarted | Set `API_BASE_URL=https://beam-dev.nhantown.com`; restart with `dev-local.ps1` |
| Any `*.beam.nhantown.com` is unavailable | Named tunnel is stopped or config missing | Check `%TEMP%\beam-cloudflared.log` and `%USERPROFILE%\.cloudflared\config-beam.yml` |
| Dashboard loads but every API call fails CORS | `FRONTEND_URL` in root `.env` is not the dashboard origin | Set `FRONTEND_URL=https://beam.nhantown.com`; restart the API (it feeds `_cors_origins` in `main.py`) |
| Dashboard calls `localhost:8000` from a remote browser | `NEXT_PUBLIC_API_URL` is baked in at build/dev start | Set it to `https://beam-api.nhantown.com` and restart `npm run dev` |
| A Beam hostname resolves to the studio tunnel | `route dns` was run without `--config` | Re-run with `--config ...\config-beam.yml --overwrite-dns` |

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
| Email | `demo@getbeam.fyi` |
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

## Beam Lab (Cloudflare Pages experiment)

`infra/cloudflare/beam-lab/` is a **separate** deployable surface from the main API/web/pixel
stack: a static Cloudflare Pages project (`beam-lab`, live at `beamlab.nhantown.com`) plus a Pages
Functions middleware used to validate the AI-agent detection chain end-to-end. It writes to the
local Docker Postgres (`retarget_agent`), not production. Full findings and resume notes:
[beam-lab-resume.md](./beam-lab-resume.md); architecture detail:
[agent-detection-architecture.md §5d](./agent-detection-architecture.md#5d-soft-serve-gate--marker-biên-_bfm-trên-beam-lab-31-07--01-08).

```bash
cd infra/cloudflare/beam-lab
npx wrangler pages deploy public --project-name beam-lab
```

Tail live production logs (needed to read `beam_gate` / `beam_full_log` JSON lines):

```bash
npx wrangler pages deployment tail --project-name beam-lab
```

The latest noted production deployment UUID for that command is
`9a4d1f20-6bdd-46fc-bfc5-447c83e81cab` (confirm the current one with
`npx wrangler pages deployment list --project-name beam-lab` — deployments roll forward on each deploy).

| Var | Location | Purpose |
|-----|----------|---------|
| `BEAM_API_BASE` | `wrangler.toml [vars]` | Full API host the beacon POSTs to (`beam-api.nhantown.com`) |
| `BEAM_SITE_ID` | `wrangler.toml [vars]` | `site_16c46453546f` |
| `BEAM_AGENT_GATE` | `wrangler.toml [vars]` | Kill switch for the soft-serve agent gate. Only the literal `"0"` disables it — deleting the line leaves the gate ON |
| `BEAM_FULL_LOG` | `wrangler.toml [vars]` | `"1"` logs the complete request/response of every non-static visitor (human included). Deliberately temporary — **turn back off once the current debug window is analysed** |
| `BEAM_FETCH_BEACON_SECRET` | wrangler secret (`npx wrangler pages secret put BEAM_FETCH_BEACON_SECRET --project-name beam-lab`) | Must equal the API's own `BEAM_FETCH_BEACON_SECRET`, or every beacon 401s with no dashboard signal explaining why |

The gate is **fail-open by design**: any error in the gate/log logic falls back to serving the
original response untouched, and humans/index crawlers/static assets/`robots.txt`/`sitemap.xml`
always get byte-identical responses.

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
- [beam-lab-resume.md](./beam-lab-resume.md) — Beam Lab experiment findings + open items
- [agent-detection-architecture.md](./agent-detection-architecture.md) — AI-agent detection architecture, §5d for Beam Lab
- [system-architecture.md](./system-architecture.md)
- [visuals/beam-system-architecture.svg](./visuals/beam-system-architecture.svg)
- `infra/docker-compose.yml`
- `infra/cloudflare/beam-lab/` — Cloudflare Pages project + `wrangler.toml`
- `Dockerfile`, `railway.json`
- `TESTING.md`, `process/context/tests/all-tests.md`
