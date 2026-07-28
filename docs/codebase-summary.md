# Codebase Summary

Last updated: 2026-07-28

## Overview

Beam is a monorepo (~84k LOC in `apps/`, ~25k in `tests/`, ~32k in `process/` harness). Four deployable surfaces share one FastAPI backend and PostgreSQL database.

## LOC Snapshot (2026-07-28)

| Area | Files | LOC (approx) |
|------|-------|----------------|
| `apps/` (total) | 519 | ~84k |
| `apps/api` | 319 | ~41k |
| `apps/web` | 152 | ~25k |
| `apps/pixel` | 16 | ~0.9k |
| `apps/extension` | 12 | ~0.6k |
| `tests/` | 193 | ~25k |
| `process/` | 188 | ~32k |
| `marketing/` | 78 | ~3.9k |

## Top-Level Layout

```
get-beam/
├── apps/
│   ├── api/          FastAPI backend (~41 routers/services domains)
│   ├── web/          Next.js 14 dashboard + marketing
│   ├── pixel/        Vanilla JS tracker + CF Worker
│   └── extension/    Chrome MV3 LinkedIn connect (dumb pipe)
├── infra/
│   └── docker-compose.yml   postgres:16, redis:7, clickhouse:24
├── tests/            pytest unit + integration
├── process/          RIPER-5 harness (context, features, protocols)
├── marketing/        brand, launch, content references
├── docs/             human documentation (this folder)
├── requirements.txt  Python deps (repo root)
├── Dockerfile        API production image
├── railway.json      Railway deploy config
├── TESTING.md        test operator guide
└── PRODUCT_ROADMAP.md historical MVP roadmap
```

## `apps/api` Map

| Directory | Count (approx) | Role |
|-----------|----------------|------|
| `routers/` | 41 modules | HTTP handlers (`/api/v1/...`) |
| `services/` | 138 modules | Business logic |
| `models/` | 39 modules | SQLAlchemy ORM |
| `schemas/` | 25 modules | Pydantic I/O |
| `agents/` | 5 modules | Segmenter, campaign planner, prompt safety |
| `tasks/` | 6 modules | Celery tasks (dormant unless worker enabled) |
| `jobs/` | 5 modules | APScheduler live jobs |
| `migrations/versions/` | ~51 | Alembic revisions |

**Entrypoints:** `main.py`, `config.py`, `dependencies.py`, `jobs/scheduler.py`, `alembic.ini`

**Representative domains:**

| Domain | Key paths |
|--------|-----------|
| Events ingest | `routers/events.py`, `services/bot_filter.py`, `models/event.py` |
| Identity | `services/identity_resolver.py`, `services/identity_providers/` |
| AI | `services/gemini_client.py`, `agents/`, `routers/ai.py` |
| Campaigns | `routers/campaigns.py`, `services/campaign_sender.py` |
| Billing | `routers/billing.py`, Gumroad webhook |
| EvalLayer | `services/agent_classifier.py`, `models/agent_visit.py`, `routers/agents.py` |
| Ads | `routers/ads.py`, `services/ads/` |
| Social / EasyEngage | `routers/drafts.py`, `feed.py`, `social_auth.py` |

## `apps/web` Map

| Path | Role |
|------|------|
| `src/app/` | App Router (~40+ routes): dashboard, blog, auth, onboarding |
| `src/components/` | React UI (shadcn-based) |
| `src/lib/api.ts` | API client singleton (~1.7k lines), Clerk + JWT |
| `public/beam/` | Static marketing, onboarding JS, pixel snippets |
| `e2e/` | 11 Playwright specs + `auth.setup.ts` |

**Dashboard areas:** EasyTrack (visitors, agents, segments, campaigns, connectors), EasyEngage (feed, drafts, social accounts), billing, admin.

## `apps/pixel`

| File | Role |
|------|------|
| `src/tracker.js` | Main pixel (cookie `_rta_vid`, batch ingest) |
| `src/worker.js` | Cloudflare Worker edge proxy |
| `e2e/` | Playwright pixel tests |

## `apps/extension`

Chrome MV3 extension: reads LinkedIn `li_at` cookie, nonce channel to dashboard tab. No direct backend calls—"dumb pipe" for LinkedIn outreach connect flow.

## `tests/`

| Suite | Location | Needs |
|-------|----------|-------|
| Unit | `tests/unit/` | None (pure functions) |
| Integration | `tests/integration/` | PostgreSQL + Redis |
| Web E2E | `apps/web/e2e/` | API + web servers |
| Pixel E2E | `apps/pixel/e2e/` | Pixel fixtures |

Runner: `scripts/test.sh` (`unit`, `integration`, `e2e`, `all`).

## `process/`

RIPER-5 agent harness—not application runtime. Contains:

- `context/all-context.md` — agent router (authoritative for agents)
- `features/*/_GUIDE.md` — feature scopes and plan folders
- `development-protocols/` — orchestration rules

**Do not confuse** `process/` plans with `docs/` human docs.

## README / PRODUCT_ROADMAP Drift

The root `README.md` and `PRODUCT_ROADMAP.md` still describe early MVP assumptions. **Current reality overrides them:**

| Stale claim | Current reality |
|-------------|-----------------|
| Product name ReTargetAgent | **Beam** (getbeam.fyi) |
| ClickHouse for events | Events in **PostgreSQL**; ClickHouse client unused |
| Celery for background jobs | **APScheduler** in-process is live; Celery dormant |
| Anthropic Claude primary AI | **Google Gemini 2.5 Flash** via httpx |
| Resend email | **SendGrid** (Resend deprecated in config) |
| Auto-run campaigns | **Human approve/send** only |
| `packages/shared`, `packages/ai` | Not present in current tree |

See [system-architecture.md](./system-architecture.md) for runtime diagram and [deployment-guide.md](./deployment-guide.md) for infra truth.

## References

- [code-standards.md](./code-standards.md)
- [system-architecture.md](./system-architecture.md)
- `process/context/all-context.md`
- `TESTING.md`
