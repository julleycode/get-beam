# Beam

AI-assisted visitor intelligence and outreach for indie founders and small teams. Paste a pixel, see who visits, draft personalized retargeting—**you approve and send** (never auto-send).

Public site: [getbeam.fyi](https://getbeam.fyi)

## Quick Start

**Fastest path:** one-command local stack.

```powershell
# Windows — also starts a configured named tunnel when API_BASE_URL is public
.\scripts\dev-local.ps1
```

> **Windows:** Docker Postgres is on host port **5433** (not 5432). See [docs/deployment-guide.md](./docs/deployment-guide.md#windows-local-verified).

```bash
# macOS / Linux
chmod +x scripts/dev-local.sh && ./scripts/dev-local.sh
```

### Manual setup (alternative)

### Prerequisites

- Python 3.12+
- Node.js 18+
- Docker & Docker Compose

### 1. Start infrastructure

```bash
cd infra
docker compose up -d
```

Starts PostgreSQL 16 and Redis 7 (ClickHouse is included but unused by the live API).

### 2. Start the API

```bash
cd apps/api
python -m venv venv
# Windows: venv\Scripts\activate
# Unix: source venv/bin/activate
pip install -r ../../requirements.txt

# From repo root
cd ../../
alembic -c apps/api/alembic.ini upgrade head
python -m scripts.seed   # optional test data

PYTHONPATH=. uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Start the dashboard

```bash
cd apps/web
npm install
npm run dev
```

Open `http://localhost:3000`.

### 4. Background jobs

**APScheduler runs inside the API process** (feed sync, identity resolution, retention). Celery workers are optional and dormant by default (`celery_worker_enabled=false`).

### Demo credentials

- Email: `demo@getbeam.fyi`
- Password: `password123`

## Architecture

```
Website Pixel → Event Ingest API → Identity Resolution → Enrichment
→ AI Segmentation (Gemini) → Campaign Drafts → Human Review → Send
```

EvalLayer separately tracks AI-agent traffic (not outreach targets).

See [docs/system-architecture.md](./docs/system-architecture.md) for diagrams and data flows.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 14 (App Router) + Tailwind + shadcn/ui |
| Backend | Python FastAPI, async SQLAlchemy + asyncpg |
| Pixel | Vanilla JS (&lt;5KB target) + optional Cloudflare Worker |
| Extension | Chrome MV3 (LinkedIn outreach connect) |
| Database | **PostgreSQL 16** (events + all app data) |
| Cache / queue | Redis 7 |
| Scheduler | **APScheduler** (in-process, live) |
| AI | **Google Gemini 2.5 Flash** (httpx); OpenRouter fallback for social |
| Email | SendGrid; optional Gmail OAuth send |
| Auth | Clerk RS256 + legacy JWT |
| Billing | Gumroad (active MoR); Stripe legacy |

**Not in active use:** ClickHouse event store (client vestigial), Celery workers (dormant), Anthropic as primary AI, Resend email.

## Documentation

| Doc | Description |
|-----|-------------|
| [docs/README.md](./docs/README.md) | Documentation index |
| [docs/project-overview-pdr.md](./docs/project-overview-pdr.md) | Product overview & PDR |
| [docs/codebase-summary.md](./docs/codebase-summary.md) | Repo map & LOC |
| [docs/code-standards.md](./docs/code-standards.md) | Coding conventions |
| [docs/system-architecture.md](./docs/system-architecture.md) | Architecture & flows |
| [docs/project-roadmap.md](./docs/project-roadmap.md) | Shipped vs pending |
| [docs/deployment-guide.md](./docs/deployment-guide.md) | Local & production deploy |
| [docs/local-uat-prod.md](./docs/local-uat-prod.md) | Local → UAT → PROD |
| [docs/dev-workflow-slack-issues.md](./docs/dev-workflow-slack-issues.md) | Branches, Slack UAT, GitHub Issues |
| [docs/design-guidelines.md](./docs/design-guidelines.md) | UI tokens & fonts |

**Agent / harness context:** `process/context/all-context.md`  
**Tests:** [TESTING.md](./TESTING.md)

## Testing

```bash
./scripts/test.sh unit          # no DB
./scripts/test.sh integration   # Postgres + Redis
./scripts/test.sh e2e           # API + web running
```

## Legacy names

Repo history uses **ReTargetAgent** / **EasyTrack** (dashboard labels). Product name is **Beam**.
