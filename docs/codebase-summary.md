# Codebase Summary

Last updated: 2026-08-18

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
│   ├── docker-compose.yml   postgres:16, redis:7, clickhouse:24
│   └── cloudflare/
│       ├── beam-lab/              Cloudflare Pages — AI-agent detection lab
│       │                          (not GetBeam PROD; writes local Postgres)
│       └── agent-beacon-worker/   CF Worker on splittrip.nhantown.com only
│                                  (lab fetch-beacon; not getbeam.fyi)
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
| Events ingest | `routers/events.py`, `services/bot_filter.py`, `models/event.py`, `services/visitor_aggregator.py`, `services/aggregation_debounce.py` |
| Identity | `services/identity_resolver.py`, `services/identity_providers/` |
| AI | `services/gemini_client.py`, `agents/`, `routers/ai.py` |
| Campaigns | `routers/campaigns.py`, `services/campaign_sender.py` |
| Billing | `routers/billing.py`, Gumroad webhook |
| EvalLayer | `services/agent_classifier.py`, `services/agent_gateway.py`, `services/agent_marker.py`, `models/agent_visit.py`, `routers/agents.py` |
| Ads | `routers/ads.py`, `services/ads/` |
| Social / EasyEngage | `routers/drafts.py`, `feed.py`, `social_auth.py` |

**Scale-ready ingest (HEAD `73142d1`, flags still OFF):** P1 `8ffeb32` (watermark + Redis mutex); P2 `bbae139` (`event_id` required + unique `(site_id, event_id)`); P3 `73142d1` (hard 429 ceiling, CF peer lock, `SET LOCAL` timeout isolation). Defaults: `aggregation_incremental_enabled=False`, `site_ingest_limit_enabled=False`, `db_statement_timeout_ms=0`, ceiling **155** (7d p99=31×5). Missing `event_id` → 400 whole batch; `created_at` = server `utcnow()`. Operator order + leftovers: [deployment-guide.md §Scale-ready](./deployment-guide.md#scale-ready-x20x30). Behavior: [system-architecture.md](./system-architecture.md#request-flow-event-ingest). Cook: [journals/260818-1328-scale-ready-getbeam-cook.md](./journals/260818-1328-scale-ready-getbeam-cook.md).

**EvalLayer notes (Jul 2026):** F2 marker (`agent_marker.py`) mints Fernet `?_bam=` tokens on `offers.json` URLs; click decodes to `agent_handoff_links`. IP sweep (`agent_verification.py`) updates `agent_visits.verification_method` only — `agent_fetch_events.verification_method` stays `ua-only`. All agent flags default OFF.

**Beam Lab notes (31 Jul – 1 Aug 2026):** `infra/cloudflare/beam-lab/` validates the same detection chain live. Its edge middleware mints a *second*, unrelated marker `?_bfm=` (opaque hex, not Fernet — `agent_marker.py::edge_marker_from_url`) stamped onto every same-host link, joined via new `agent_fetch_events.link_marker` / `events.link_marker` columns (migrations `f3c8b2e91d47`, `a7d419e6c052` — **dev Postgres only, not yet applied to production**). The lab's original hard-403 agent gate was replaced by a soft-serve gate (always 200 + real HTML, invitation injected as an HTML comment) after real ChatGPT-User gave up on the 403 and served stale answers. See [agent-detection-architecture.md §5d](./agent-detection-architecture.md#5d-soft-serve-gate--marker-biên-_bfm-trên-beam-lab-31-07--01-08) and [beam-lab-resume.md](./beam-lab-resume.md).

**Shipped (7b1ed33):** `resolution_runner.py` now prioritizes `ai_attributable_human.desc()` (ai_source OR handoff) before intent_score — AI-attributed visitors resolve first.

**Recent fixes:** F10 dedup (`c1e7a94f3d28`): `agent_fetch_events.dedup_key` (sha256) + partial unique index; F12 IP/UA mismatch recorded (not blocking); F13 IP ranges refresh 24h → `runtime/` (outside git).

See [agent-detection-architecture.md](./agent-detection-architecture.md).

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
| getbeam.fyi hosted on Cloudflare Pages | **Vercel** project `retarget-agent`; CF is DNS/WAF |
| splittrip Worker = GetBeam PROD beacon | Lab only; PROD beacon is Vercel middleware |
| Resend email | **SendGrid** (Resend deprecated in config) |
| Auto-run campaigns | **Human approve/send** only |
| `packages/shared`, `packages/ai` | Not present in current tree |

See [system-architecture.md](./system-architecture.md) for runtime diagram and [deployment-guide.md](./deployment-guide.md) for infra truth.

## References

- [code-standards.md](./code-standards.md)
- [system-architecture.md](./system-architecture.md)
- [agent-detection-architecture.md](./agent-detection-architecture.md)
- [beam-lab-resume.md](./beam-lab-resume.md)
- `process/context/all-context.md`
- `TESTING.md`
