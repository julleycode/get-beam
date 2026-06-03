# Beam — Backend Infrastructure

A short map of how the backend is built and runs.

## Stack at a glance

| Layer | Tech |
|---|---|
| API framework | Python 3.11 + FastAPI (async) |
| ORM / DB access | SQLAlchemy async + asyncpg |
| Primary DB | PostgreSQL (Supabase) |
| Event store | ClickHouse (high-volume pixel events) |
| Cache / rate limits | Redis (Upstash) |
| Background jobs | Celery (Redis broker) + APScheduler (periodic) |
| AI | OpenRouter (100+ models, default DeepSeek free tier) |
| Auth | Clerk (primary) + legacy HS256 JWT fallback |
| Hosting | Railway (Docker) |
| Config | `pydantic-settings` — all secrets via env vars |

## Process layout

The API is a single FastAPI app (`apps/api/main.py`) with three runtime pieces:

1. **Web app** — serves all `/api/v1/*` routers (the HTTP API).
2. **APScheduler** — started inside the FastAPI lifespan; runs the periodic social-feed sync (`sync_interval_minutes`, default 60).
3. **Celery workers** — separate process(es) for heavy/async work (visitor aggregation, identity resolution, segmentation), brokered through Redis.

On startup the lifespan also runs idempotent schema setup: `Base.metadata.create_all` + a list of `ALTER TABLE ... IF NOT EXISTS` migrations and a few backfills (so deploys are self-healing without a separate migration step).

## Request → data flow

```
Pixel (customer site)
   │  POST /api/v1/events/ingest   (open CORS, bot-filtered)
   ▼
ClickHouse (raw events)  ──►  Celery: visitor_aggregator  ──►  Postgres (visitors)
                                          │
                                 intent_score >= 40
                                          ▼
                          Celery: identity_resolver (waterfall)
                                          ▼
                              Enricher (job title, socials)
                                          ▼
                   Segmentation trigger (every 10+ enriched)  ──►  AI campaign drafts
```

## Routers (`apps/api/routers/`)

- `events` — pixel event ingest (open CORS, runs `bot_filter`).
- `sites` — site CRUD + **auth-gated** platform detection.
- `visitors`, `segments`, `campaigns`, `exports` — core EasyTrack surface.
- `social_auth`, `social_accounts`, `drafts`, `feed`, `companies` — EasyEngage (social) surface.
- `auth`, `api_keys` — auth + BYOK key management.
- `feature_requests` — public feedback intake.
- `demo` — **public, pre-auth** onboarding endpoints (`/identify`, `/detect-platform`) that reuse the real services without the auth gate.

## Key services (`apps/api/services/`)

- **`identity_resolver`** — the IP→person waterfall. Tries providers in order and stops at first hit:
  `pdl_ip_enrich → ipinfo → leadpipe / rb2b / capturify (pixel cookie graph) → hunter → apollo`.
  Residential IPs (consumer ISPs) generally don't resolve — corporate IPs do. This is an industry-wide limit, not a bug.
- **`enricher`** — email/profile → job title, company, LinkedIn/Twitter (PDL, Proxycurl).
- **`platform_detector`** — fetches a site's HTML and scores signatures to detect shopify/wordpress/wix/squarespace/webflow + GTM + a Shopify API probe.
- **`bot_filter`**, **`geoip`**, **`pixel_verifier`** — ingest hygiene.
- **`email_sender` / `sender`** (Resend), **`csv_exporter`**, **`ai_reply`** (OpenRouter), **`segmentation_trigger`**.
- **`encryption` / `key_vault`** — Fernet encryption for OAuth tokens and BYOK keys at rest.

## Background work

- **Celery** (`tasks/`): `aggregation_tasks` (visitor rollups), `resolution_tasks` (identity waterfall), `segmentation_tasks` (auto-segment when 10+ new enriched visitors accumulate). Broker/result backend on Redis DBs 1/2.
- **APScheduler** (`jobs/scheduler.py`): periodic `sync_all_accounts` for social feeds.

## Data stores

- **PostgreSQL** — all relational state (users, sites, visitors, segments, campaigns, drafts, social accounts, enrichment profiles, feature requests). UUID PKs, `created_at`/`updated_at` on every table.
- **ClickHouse** — append-only raw pixel events (high write volume, cheap aggregation).
- **Redis** — cache (identity results 30-day TTL, enrichment 7-day), Celery broker, and slowapi rate-limit counters.

## Auth

- **Clerk** is primary (`clerk_secret_key`). Legacy **HS256 JWT** (`jwt_secret`) is a fallback for the old email/password flow (`api.signup`/`api.login`).
- Production startup (`validate_production`) hard-fails if secrets are still defaults, mocks are on, or encryption keys are missing.

## Safety rails (business rules enforced in code)

- Resolve identity only when `intent_score >= 40`.
- Daily resolution budget cap per site (default 50/day); no retry for a failed visitor within 30 days.
- Max 50 emails/hour/site; never email without human approval; unsubscribe link always; `do_not_email` after hard bounce.
- **Mock mode** (`MOCK_EXTERNAL_APIS`, `MOCK_SOCIAL_OAUTH`) returns fake data so dev/CI/demo never burn API credits.

## Deploy

- **Railway**, Docker (`./Dockerfile`, pinned `python:3.11-slim-bookworm`). Deployed with `railway up` (does **not** auto-deploy on merge).
- `.railwayignore` excludes the agent harness, `node_modules`, `.venv`, etc. from the upload.
- Rough boundary: **Railway = backend/API**, **Vercel = Next.js frontend**.
