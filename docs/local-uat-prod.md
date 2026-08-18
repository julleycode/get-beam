# Local → UAT → PROD

Last updated: 2026-08-18

## Overview

Hướng dẫn dựng môi trường Beam phù hợp chuỗi **Local (dev) → UAT → PROD**, làm việc trên nhánh **`main`**. Topology phần mềm giống nhau ở mọi môi trường; khác nhau chỉ ở secrets, URLs, và provider thật/mock.

Diagrams:

- [beam-system-architecture.svg](./visuals/beam-system-architecture.svg) / [.png](./visuals/beam-system-architecture.png)
- [beam-env-promotion.svg](./visuals/beam-env-promotion.svg) / [.png](./visuals/beam-env-promotion.png)

Knowledge graph (AST): `apps/graphify-out/graph.html` + `GRAPH_REPORT.md`.

---

## Current state (repo today)

| Piece | Reality |
|-------|---------|
| API deploy | Railway via root `Dockerfile` + `railway.json` (alembic then uvicorn) |
| Web | **Vercel** project `retarget-agent` → `getbeam.fyi` (Git `julleycode/get-beam`, no `vercel.json` in repo) |
| Pixel CDN | Cloudflare Worker `beam-pixel` (`apps/pixel/wrangler.toml`) → `pixel.getbeam.fyi` |
| Agent beacon PROD | Vercel Edge middleware on `getbeam.fyi` → `api.getbeam.fyi/api/v1/agents/fetch-beacon` |
| Agent beacon lab | CF Worker `beam-agent-beacon-splittrip` on **`splittrip.nhantown.com` only** — not GetBeam PROD |
| CI | `.github/workflows/test.yml` on PR + push `main` (unit / integration / e2e) |
| Branch `UAT` | **`origin/UAT` exists** from `main` — intended for UAT deploy target |
| Feature branches | **`dev_<slug>`** (e.g. `dev_ads-meta`) — recommended; UAT deploy **not wired** |
| Auto-deploy UAT | **Not implemented** — wire Railway/Vercel deploy-on-branch first |
| Auto-deploy PROD | **Vercel `main` is live Git auto-deploy** (author `julleycode` READY; `nhantochi95` often BLOCKED). Railway also deploys from Git. Isolated UAT promote still not wired. |
| Slack UAT notify | **Not implemented** — proposed design in [dev-workflow-slack-issues.md](./dev-workflow-slack-issues.md) |
| Local infra | `infra/docker-compose.yml` (Postgres **5433→5432**, Redis 6379; ClickHouse optional/unused) |
| Local scripts | `scripts/dev-local.ps1` (Windows), `scripts/dev-local.sh` (macOS) — see [deployment-guide.md](./deployment-guide.md#windows-local-verified) |

---

## Critical: `APP_ENV` rules

From `apps/api/config.py`:

```text
_KNOWN_NONPROD_ENVS = {"development", "test", "local", "ci"}
```

| Value | Behavior |
|-------|----------|
| `development`, `local`, `test`, `ci` | Skip production secret checks |
| **Anything else** (`production`, `staging`, `uat`, typo…) | **Production-strict** — requires real `APP_SECRET_KEY`, `ENCRYPTION_KEY`, `TOKEN_ENCRYPTION_KEY` |

**Khuyến nghị UAT:** dùng `APP_ENV=production` với **DB/keys/Clerk riêng**, không dùng `APP_ENV=uat` trừ khi cố ý thêm `uat` vào allowlist (làm yếu safety).

---

## Recommended topology

| Component | LOCAL | UAT | PROD |
|-----------|-------|-----|------|
| Branch | `main` or `dev_<slug>` locally | `UAT` or `dev_*` when deploy wired | promote from UAT (tag or manual) |
| `APP_ENV` | `development` | `production` | `production` |
| API | `uvicorn` localhost:8000 | Railway **project riêng** (e.g. `beam-uat`) | Railway prod |
| Web | `npm run dev` :3000 | Vercel Preview / project `uat` | Vercel prod (`getbeam.fyi`) |
| Pixel | API `/pixel/tracker.js` | API UAT hoặc CF `pixel.uat.*` | CF `pixel.getbeam.fyi` |
| Postgres / Redis | Docker Compose | Managed, **isolated** | Managed prod |
| Clerk | Dev instance (optional) | **UAT Clerk app** | Prod Clerk |
| External APIs | `MOCK_EXTERNAL_APIS=true` hoặc empty keys | Sandbox / mock initially | Live (SendGrid, Gumroad, PDL…) |
| Feature flags | ON for local experiments | Flip flags under test | Flip **one at a time** after migrate |

```text
LOCAL (dev_*) ──PR/CI──► UAT deploy ──smoke──► Slack notify [proposed]
                              │
                         manual promote
                              ▼
                            PROD
```

Today: CI runs on `main`; **no auto UAT deploy or Slack**. See [dev-workflow-slack-issues.md](./dev-workflow-slack-issues.md).

---

## LOCAL — setup for daily dev

### Env files (what you need)

| File | From template | Used by |
|------|---------------|---------|
| Repo root `.env` | `.env.example` | FastAPI (`apps/api/config.py`) |
| `apps/web/.env.local` | `apps/web/.env.example` | Next.js (browser + server) |

**Minimum to boot:** `APP_ENV=development`, localhost `DATABASE_URL` / `REDIS_URL` / `FRONTEND_URL`, and web `NEXT_PUBLIC_API_URL=http://localhost:8000`. Keep `API_BASE_URL=http://localhost:8000` for local-only work, or use `https://beam-dev.nhantown.com` when an external website must load the local pixel. To reach the dashboard publicly as well, set `FRONTEND_URL=https://beam.nhantown.com` and web `NEXT_PUBLIC_API_URL=https://beam-api.nhantown.com`. Clerk keys optional (empty = legacy JWT login). Gemini/SendGrid optional.

### One-command scripts

```powershell
# Windows (PowerShell)
.\scripts\dev-local.ps1
# .\scripts\dev-local.ps1 -SkipInstall
# .\scripts\dev-local.ps1 -MigrateOnly
# .\scripts\dev-local.ps1 -NoTunnel
```

```bash
# macOS / Linux
chmod +x scripts/dev-local.sh
./scripts/dev-local.sh
# ./scripts/dev-local.sh --skip-install
# ./scripts/dev-local.sh --migrate-only
```

Scripts will: copy env templates if missing → docker postgres+redis → venv/npm install → alembic → start API :8000 + Web :3000. On Windows, a public `API_BASE_URL` also enables the matching named Cloudflare tunnel when `%USERPROFILE%\.cloudflared\config-beam.yml` exists.

### 1. Infra (manual alternative)

```bash
cd infra
docker compose up -d postgres redis
# clickhouse optional — live API does not use it
```

### 2. Env files (manual)

```bash
cp .env.example .env
cp apps/web/.env.example apps/web/.env.local
```

**Safety:** keep databases and Redis on localhost; never use prod Railway/Supabase data URLs (`scripts/e2e-local.sh` and `dev-local.*` guard this).

`API_BASE_URL` may use `https://beam-dev.nhantown.com` for public pixel tests. That tunnel host exposes only `/pixel/tracker.js`, `/api/v1/events/ingest`, and `/health/ready` — `dev-local.ps1` audits exactly that host and refuses to start the tunnel otherwise. Keep the real Cloudflare tunnel config and credential JSON outside Git.

**Tunnel-published UAT (2026-07-29).** `beam.nhantown.com` (dashboard, `:3000`) and `beam-api.nhantown.com` (full API, `:8000`) now ride the same named tunnel so sites can be added from any browser. This is a laptop-backed stand-in for UAT, not the Railway/Vercel UAT described below: it dies when the machine sleeps, shares the local Docker Postgres, and runs `APP_ENV=development` — so it does **not** exercise the production-strict secret checks a real UAT must prove. Use it to test flows; do not use it as the promotion gate to PROD. It also puts unrated-limit auth and open signup on the public internet — see the security note in [deployment-guide.md](./deployment-guide.md#public-hostnames-on-the-nhantown-beam-tunnel-updated-2026-07-29).

### 3. API + Web (manual)

```bash
# From repo root
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS: source .venv/bin/activate
pip install -r requirements.txt
alembic -c apps/api/alembic.ini upgrade head
PYTHONPATH=. uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

# Separate terminal
cd apps/web && npm install && npm run dev
```

Health: `GET http://localhost:8000/health`

### 4. Tests (local gate before push)

```bash
./scripts/test.sh unit
./scripts/test.sh integration   # needs docker PG+Redis
# e2e when UI changed: needs API + web running
```

APScheduler chạy **trong** process FastAPI — không cần Celery cho dev thường ngày.

---

## UAT — mirror of PROD with isolation

### Goals

- Same Docker image / same `main` commit as candidate for prod
- Separate Postgres, Redis, encryption keys, Clerk, webhook URLs
- Prove migrations + feature flags **before** prod enable

### Suggested hostnames

| Service | Example |
|---------|---------|
| Web | `https://uat.getbeam.fyi` |
| API | `https://api.uat.getbeam.fyi` |
| Pixel | `https://pixel.uat.getbeam.fyi` or API `/pixel/tracker.js` |

### Env matrix (UAT vs PROD)

| Variable | UAT | PROD |
|----------|-----|------|
| `APP_ENV` | `production` | `production` |
| `DATABASE_URL` | UAT PG | Prod PG |
| `REDIS_URL` | UAT Redis | Prod Redis |
| `APP_SECRET_KEY` / `ENCRYPTION_KEY` / `TOKEN_ENCRYPTION_KEY` | **unique Fernet keys** | **different unique keys** |
| `API_BASE_URL` / `FRONTEND_URL` | UAT URLs | Prod URLs |
| `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_SITE_URL` | UAT | Prod |
| `CLERK_*` | UAT Clerk application | Prod Clerk |
| `MOCK_EXTERNAL_APIS` | `true` until provider smoke | `false` |
| `GUMROAD_*` / `SENDGRID_*` | sandbox / test webhooks | live |
| `BEAM_FETCH_BEACON_SECRET` | shared UAT web+API | prod secret |

Generate Fernet keys:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Migration gate (UAT)

1. `alembic -c apps/api/alembic.ini heads` → exactly **one** head  
2. Deploy API image to UAT (Dockerfile runs `upgrade head` on boot)  
3. Smoke: `/health`, sign-in, pixel ingest to UAT API, one dashboard page  
4. Enable **one** feature flag; monitor logs  
5. Only then schedule PROD promote  

---

## PROD — promote from UAT

| Rule | Detail |
|------|--------|
| Source | Same git SHA that passed UAT smoke |
| Branch policy | Work on `main`; prod promote is **manual** (Railway redeploy / Vercel promote / tag) until automation exists |
| Migrations | Prefer already-applied on UAT; Dockerfile still runs `upgrade head` — **one deploy at a time** |
| Feature flags | Default OFF in code; enable after migrate + smoke on **that** env |
| Webhooks | Gumroad / SendGrid / OAuth redirect URIs must list **prod** URLs only on prod Clerk/providers |
| Keep-warm | `.github/workflows/keep-warm.yml` pings prod Railway — keep UAT out of that cron |

High-risk flags (enable only with checklist): `agent_detection_enabled`, `ad_audiences_enabled`, ingest abuse flags, `company_graph_enabled`, etc. See `process/context/all-context.md`.

---

## Branch / promotion notes (2026-07-28)

| Item | Status |
|------|--------|
| Branch `UAT` | **Exists** (`origin/UAT` from `main`) — UAT deploy target when wired |
| Feature branches `dev_*` | **Convention documented** — e.g. `dev_ads-meta`; optional `dev_<issue#>-slug` |
| Auto-deploy `dev_*` → UAT | **Not implemented** — requires Railway/Vercel branch deploy |
| Slack notify on UAT deploy | **Not implemented** — workspace **get-beam**; see [dev-workflow-slack-issues.md](./dev-workflow-slack-issues.md) |
| Promote PROD | **Not implemented** — manual Railway/Vercel for now |
| `.env.example` web | **`apps/web/.env.example`** → copy to `apps/web/.env.local` |
| Windows local verified | Port **5433** for Docker Postgres — [deployment-guide.md](./deployment-guide.md#windows-local-verified) |

Target workflow when automation lands: merge or push `dev_*` → CI green → deploy to UAT → Slack `#deploys-uat` → smoke → manual PROD promote.

---

## Gaps to close (implementation backlog)

Ordered by value for Local→UAT→PROD:

1. Expand root `.env.example` + `apps/web/.env.example` — **done 2026-07-28**  
2. Document Railway: two services/projects (`beam-uat`, `beam-prod`) + env var lists  
3. Vercel: Preview env → UAT API URL; Production → prod API  
4. Wire Railway/Vercel deploy from `dev_*` or `UAT` branch (**deferred**)  
5. Slack UAT webhook + GitHub Actions secret `SLACK_WEBHOOK_UAT` (**deferred** — [dev-workflow-slack-issues.md](./dev-workflow-slack-issues.md))  
6. Promote PROD automation (**deferred**)  
7. GitHub Issues templates + Project board states (**deferred** — same doc)  
8. Wrangler `[env.uat]` routes for pixel UAT hostname  
9. Parameterize static marketing snippets or document prod-only snippets  

---

## Quick checklist

### Local ready

- [ ] `docker compose up -d postgres redis`  
- [ ] `.env` with `APP_ENV=development` + local data URLs; `API_BASE_URL` local or `https://beam-dev.nhantown.com`
- [ ] Publishing the dashboard? `FRONTEND_URL=https://beam.nhantown.com`, web `NEXT_PUBLIC_API_URL=https://beam-api.nhantown.com`, and `BEAM_DEMO_PASSWORD` set
- [ ] `alembic upgrade head` + API `/health`  
- [ ] Web on :3000 talking to local API  
- [ ] `./scripts/test.sh unit` green  

### UAT ready

- [ ] Separate Railway + Vercel (or Preview) + DB/Redis  
- [ ] `APP_ENV=production` + three encryption secrets set  
- [ ] Clerk/OAuth redirect URIs for UAT hosts  
- [ ] Migrate + smoke after each `main` deploy  

### PROD ready

- [ ] Same SHA as UAT green  
- [ ] Prod secrets ≠ UAT secrets  
- [ ] Feature flags still OFF until post-migrate operator step  
- [ ] Gumroad/SendGrid webhooks point at prod API  

---

## References

- [deployment-guide.md](./deployment-guide.md)  
- [dev-workflow-slack-issues.md](./dev-workflow-slack-issues.md)  
- [system-architecture.md](./system-architecture.md)  
- `infra/docker-compose.yml`, `Dockerfile`, `railway.json`  
- `apps/api/config.py` (`_KNOWN_NONPROD_ENVS`, `validate_production`)  
- `TESTING.md`, `process/context/tests/all-tests.md`  
- `apps/graphify-out/GRAPH_REPORT.md`  
