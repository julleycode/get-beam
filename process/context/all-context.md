# Beam — All Context

Last updated: 2026-05-28

This file is the root context entrypoint for the repo.

Use it for two things:

1. quick routing to the right context pack or root file
2. broad architecture and repository understanding

Start here before loading deeper context files.

---

## How This File Works (the `all-*.md` Convention)

Every `process/context/` directory has one `all-*.md` entrypoint that acts as an attachable quick router for that domain. This root file (`all-context.md`) is the top-level router. Context groups each have their own `all-{group}.md` entrypoint.

**How agents use it:**

1. Agent reads `all-context.md` first (this file)
2. Finds the relevant context group from the routing tables below
3. Reads that group's `all-{group}.md` entrypoint
4. Only then loads the specific deep doc needed

---

## Quick Start

For most substantial tasks:

1. read this file first
2. choose the smallest relevant root file or context group from the tables below
3. only then load deeper files

---

## Product Overview

**Beam** (getbeam.fyi) is a B2B SaaS that identifies anonymous website visitors, finds their social handles, and drafts personalized engagement. Users click send manually from their own social accounts.

Tagline: "see who's into you. say hi back."

Three core functions:
1. **Identify** — reverse IP + identity match + LLM fallback enrichment
2. **Find** — social handles across LinkedIn, X, Instagram, TikTok, Facebook, ranked by activity
3. **Engage** — AI-drafted personalized replies based on recent posts; user sends manually

**ICP:** B2B SaaS founders and growth marketers at Series A-B companies (500-2000 daily visitors).

**Internal codenames:** "EasyTrack" (visitor identification + enrichment pipeline), "EasyEngage" (social account management + feed + AI drafts).

**Status:** MVP functional end-to-end. Rename from "ReTargetAgent" to "Beam" planned before launch. 5-day launch countdown as of 2026-05-28.

---

## Current Root Entry Points

| File | Read when |
|---|---|
| `process/context/all-context.md` | any substantial planning, research, review, or implementation task |
| `process/context/tests/all-tests.md` | testing, verification, debugging test failures, execution planning |
| `process/context/planning/all-planning.md` | plan-shape calibration, planning examples, SIMPLE vs COMPLEX reference docs |

## Current Context Groups

| Group | Entry point | Scope |
|---|---|---|
| `planning/` | `process/context/planning/all-planning.md` | plan-shape calibration, planning examples, SIMPLE vs COMPLEX reference docs |
| `tests/` | `process/context/tests/all-tests.md` | test runners, commands, pytest config, Playwright setup, debugging |

## Task Routing Table

| If the task involves... | Start with |
|---|---|
| architecture or stack questions | this file |
| testing or verification | `process/context/tests/all-tests.md` |
| creating a new plan | `process/context/planning/all-planning.md` |
| database models or schema | this file → "Database Schema" section |
| API endpoints | this file → "API Routes" section |
| social platform integrations | this file → "Services" section |
| frontend pages | this file → "Frontend" section |
| environment / config | this file → "Environment and Configuration" section |

## Current Features

No feature folders created yet. Feature folders will be created when a feature cluster reaches 5+ artifacts.

---

## Repository Structure

```
beam/
├── apps/
│   ├── api/                        # Python FastAPI backend
│   │   ├── agents/                 # AI agents (segmenter, campaign_planner)
│   │   ├── jobs/                   # APScheduler background jobs (feed sync)
│   │   ├── models/                 # SQLAlchemy ORM models (15 files)
│   │   ├── routers/                # API endpoint routers (14 files)
│   │   ├── schemas/                # Pydantic request/response schemas (12 files)
│   │   ├── scripts/                # Platform login scripts (linkedin, tiktok)
│   │   ├── services/               # Business logic services (25+ files)
│   │   │   └── platforms/          # Social platform integrations (OAuth + browser)
│   │   ├── tasks/                  # Celery async tasks
│   │   ├── config.py               # pydantic-settings config (40+ env vars)
│   │   ├── dependencies.py         # Auth middleware (Clerk + legacy JWT)
│   │   └── main.py                 # FastAPI app entry + inline migrations
│   ├── web/                        # Next.js 14 dashboard
│   │   ├── src/app/                # App Router pages
│   │   ├── src/components/         # React components
│   │   ├── src/lib/                # API client, utilities
│   │   ├── e2e/                    # Playwright E2E tests
│   │   └── playwright.config.ts
│   └── pixel/                      # Tracking pixel (served via Docker)
├── packages/
│   ├── ai/                         # (empty — future AI package)
│   └── shared/                     # (empty — future shared code)
├── tests/                          # Python backend tests
│   ├── unit/                       # 5 unit test files
│   ├── integration/                # 2 integration test files
│   └── conftest.py                 # Shared fixtures (test_engine, test_db, test_client)
├── infra/
│   └── docker-compose.yml          # postgres:16, redis:7, clickhouse:24
├── scripts/
│   ├── seed.py                     # Test data seeder
│   └── test.sh                     # Test runner (unit/integration/e2e/all)
├── Dockerfile                      # Python 3.11-slim + Playwright Chromium
├── railway.json                    # Railway deployment config
├── pyproject.toml                  # pytest config
├── requirements.txt                # Python dependencies
├── PRODUCT_ROADMAP.md              # Full MVP specs and implementation order
├── CLAUDE.md                       # Agent harness config (managed)
└── AGENTS.md                       # Agent definitions (managed)
```

---

## Technology Stack

- **Backend:** Python 3.11 + FastAPI (async throughout)
- **Frontend:** Next.js 14.2.35 (App Router) + React 18
- **UI framework:** Tailwind CSS 3.4.1 + shadcn/ui (Radix primitives) + Lucide icons
- **Auth:** Clerk (@clerk/nextjs 5.7.6) with RS256 JWT verification; legacy HS256 fallback
- **Database:** PostgreSQL 16 via async SQLAlchemy + asyncpg (Supabase in production)
- **Analytics DB:** ClickHouse 24 (configured but events currently stored in PostgreSQL)
- **Cache:** Redis 7 (Upstash in production)
- **Task queue:** Celery with Redis broker (APScheduler for periodic sync)
- **AI:** OpenRouter API (default model: `deepseek/deepseek-v4-flash:free`) + Anthropic fallback
- **Email:** Resend API
- **Forms:** react-hook-form 7.76 + zod 4.4.3 validation
- **Data fetching:** TanStack Query 5.100
- **E2E testing:** Playwright 1.60
- **Backend testing:** pytest 8+ with pytest-asyncio
- **Logging:** structlog (never print())
- **HTTP client:** httpx (async)
- **Deployment:** Railway (Docker) for API; frontend deployment TBD
- **Package manager:** npm (frontend), pip (backend)
- **Rate limiting:** slowapi

---

## Key Patterns and Conventions

**Python conventions:**
- Type hints on all functions and variables
- Pydantic models for every API request/response
- Async functions for all I/O (database, HTTP, Redis)
- structlog for logging, never print()
- httpx (async) for external API calls
- Config via pydantic-settings (env vars loaded from .env)

**TypeScript conventions:**
- Strict mode, no `any` types
- Server components by default, client components only when needed
- API calls via shared `ApiClient` class in `lib/api.ts`
- react-hook-form + zod for form validation

**Database conventions:**
- Tables: snake_case, plural (visitors, campaigns, segments)
- Columns: snake_case
- Foreign keys: `{table_singular}_id`
- All tables have: `id` (UUID), `created_at`, `updated_at` (via Base class)
- Inline ALTER TABLE migrations in main.py lifespan (no Alembic yet)

**Auth pattern:**
- Clerk JWT (RS256) is primary auth method
- Legacy self-issued JWT (HS256) as fallback
- `get_current_user` dependency validates token and auto-creates user on first Clerk API call
- Clerk middleware in Next.js protects all routes except /login, /sign-in, /sign-up

**API client pattern:**
- Frontend uses singleton `ApiClient` in `apps/web/src/lib/api.ts`
- Base URL from `NEXT_PUBLIC_API_URL` env var (default: `http://localhost:8000`)
- Clerk token preferred over legacy localStorage token
- All endpoints under `/api/v1/` prefix

**Feature flags:**
- `MOCK_EXTERNAL_APIS=true` — mock enrichment/identity APIs (PDL, IPinfo, etc.)
- `MOCK_SOCIAL_OAUTH=true` — mock social OAuth flows

**Import pattern:**
- Python: absolute imports from project root (`from apps.api.models.database import Base`)
- PYTHONPATH=/app (set in Dockerfile)

**External API convention:**
- Every external call must have: timeout (10s default), retry logic (3 attempts with exponential backoff), error handling
- All external API results cached in Redis (30-day TTL for identity, 7-day for enrichment)

---

## Database Schema

### Models (15 tables)

| Model | Table | Key purpose |
|---|---|---|
| `User` | `users` | App users with Clerk auth + tone preference |
| `Site` | `sites` | Tracked websites with pixel verification |
| `Event` | `events` | Raw pixel events (pageviews, clicks, scrolls) |
| `Visitor` | `visitors` | Aggregated visitor profiles with intent scores |
| `IdentifiedVisitor` | `identified_visitors` | Resolved visitor identities (email, name, phone) |
| `ResolutionLog` | `resolution_logs` | Identity resolution audit trail |
| `EnrichmentProfile` | `enrichment_profiles` | Social + professional enrichment data |
| `Company` | `companies` | Company-level data resolved from visitor IPs |
| `Segment` | `segments` | AI-generated visitor segments |
| `SegmentMember` | `segment_members` | Visitor-to-segment mapping |
| `Campaign` | `campaigns` | Retargeting campaigns (email, social, ads) |
| `CampaignTouchpoint` | `campaign_touchpoints` | Individual campaign delivery items |
| `SocialAccount` | `social_accounts` | Connected social platforms (OAuth tokens) |
| `Post` | `posts` | Synced social feed posts |
| `Message` | `messages` | Social DMs |
| `Draft` | `drafts` | AI-generated reply/comment drafts |
| `VoiceExample` | `voice_examples` | User feedback for AI voice learning |
| `UserApiKey` | `user_api_keys` | BYOK encrypted API keys |

### Key relationships

- `User` → has many `SocialAccount`, `Draft`, `VoiceExample`
- `SocialAccount` → has many `Post`, `Message`
- `Post` → has many `Draft`
- `Message` → has many `Draft`
- `Campaign` → belongs to `Segment`, has many `CampaignTouchpoint`
- `SegmentMember` → links `Segment` to visitor_id

### Key enums

- `Platform`: facebook, instagram, linkedin, twitter, tiktok
- `CampaignType`: email, social_reply, social_dm, paid_ads
- `DraftType`: reply, comment
- `DraftStatus`: pending, approved, rejected, sent, failed
- `FeedbackType`: approved, edited, rejected

---

## API Routes

All routes are mounted under `/api/v1/`.

| Prefix | Tag | Key endpoints |
|---|---|---|
| `/api/v1/auth` | auth | `POST /signup`, `POST /login`, `GET /me` |
| `/api/v1/events` | events | `POST /ingest` (pixel event ingestion) |
| `/api/v1/sites` | sites | CRUD sites, `GET /{id}/pixel`, `POST /detect-platform`, `POST /{id}/verify-pixel`, `GET /{id}/wordpress-plugin`, `POST /{id}/shopify/connect` |
| `/api/v1/visitors` | visitors | `GET /{site_id}` (list), `GET /{site_id}/stats`, `GET /{site_id}/{visitor_id}` (detail), `POST /{site_id}/{visitor_id}/enrich`, `POST /{site_id}/resolve` |
| `/api/v1/segments` | segments | `GET /{site_id}`, `POST /{site_id}/run` (trigger AI segmentation) |
| `/api/v1/campaigns` | campaigns | `GET /{site_id}`, `POST /{site_id}/create/{segment_id}`, `GET /{site_id}/{campaign_id}`, `PATCH /{site_id}/{campaign_id}/status` |
| `/api/v1/exports` | exports | `GET /{site_id}/{segment_id}` (CSV export) |
| `/api/v1/api-keys` | api-keys | CRUD BYOK keys, `POST /{provider}/test` |
| `/api/v1/social` | social-auth | `POST /register`, `POST /login`, `GET /me`, `GET /connect/{platform}`, `GET /callback/{platform}` |
| `/api/v1/social` | social-accounts | `GET /accounts/`, `DELETE /accounts/{id}`, `POST /accounts/twitter/browser-login`, `POST /accounts/linkedin/browser-login`, `POST /accounts/tiktok/browser-login` |
| `/api/v1/drafts` | drafts | `GET /`, `POST /generate`, `PUT /{id}/edit`, `POST /{id}/approve`, `POST /{id}/reject` |
| `/api/v1/feed` | feed | `GET /` (paginated feed), `POST /sync`, `POST /import` |
| `/api/v1/companies` | companies | `GET /{site_id}` (list companies) |

---

## Services

### EasyTrack (visitor identification pipeline)

| Service | Purpose |
|---|---|
| `bot_filter.py` | Filter bot/crawler traffic from real visitors |
| `visitor_aggregator.py` | Aggregate raw events into visitor profiles with intent scores |
| `identity_resolver.py` | Resolve anonymous visitors to real identities (waterfall: IPinfo → Hunter → Apollo) |
| `enricher.py` | Enrich identified visitors with professional + social data |
| `company_resolver.py` | Resolve visitor IPs to company data |
| `geoip.py` | IP geolocation |
| `segmentation_trigger.py` | Trigger AI segmentation when 10+ new enriched visitors accumulate |
| `pixel_verifier.py` | Verify pixel installation on target site |
| `platform_detector.py` | Detect website platform (Webflow, Shopify, WordPress, Next.js) |
| `clickhouse_client.py` | ClickHouse event storage client (optional, events now in PostgreSQL) |
| `csv_exporter.py` | Export segments as CSV |
| `email_sender.py` | Send emails via Resend API |

### EasyEngage (social engagement)

| Service | Purpose |
|---|---|
| `sync.py` | Sync all connected social accounts' feeds |
| `ai_reply.py` | Generate AI draft replies/comments using OpenRouter |
| `sender.py` | Send approved drafts via platform APIs |
| `oauth_state.py` | Manage OAuth state for social connections |
| `platforms/base.py` | Abstract base class for platform integrations |
| `platforms/twitter.py` | Twitter/X OAuth + API integration |
| `platforms/twitter_browser.py` | Twitter browser-based scraping |
| `platforms/twitter_scraper.py` | Twitter syndication scraper (no auth needed) |
| `platforms/linkedin.py` | LinkedIn OAuth + API integration |
| `platforms/linkedin_browser.py` | LinkedIn browser-based actions |
| `platforms/tiktok.py` | TikTok OAuth + API integration |
| `platforms/tiktok_browser.py` | TikTok browser-based actions |
| `platforms/facebook.py` | Facebook OAuth + API integration |
| `platforms/instagram.py` | Instagram (via Facebook) integration |
| `platforms/pkce.py` | PKCE helper for OAuth flows |

### Shared

| Service | Purpose |
|---|---|
| `auth.py` | Password hashing + JWT token creation (legacy) |
| `redis_client.py` | Redis connection management |
| `encryption.py` | Fernet encryption for BYOK API keys and OAuth tokens |
| `key_vault.py` | BYOK key storage and retrieval |
| `shopify_integration.py` | Shopify pixel installation (unplanned, may remove) |
| `wordpress_plugin_generator.py` | WordPress plugin ZIP generation (unplanned, may remove) |

### AI Agents

| Agent | Purpose |
|---|---|
| `agents/segmenter.py` | AI-powered visitor segmentation using Anthropic/OpenRouter |
| `agents/campaign_planner.py` | AI campaign planning based on segments |

### Background Jobs

| Job | Schedule | Purpose |
|---|---|---|
| `sync_all_feeds` | Every `sync_interval_minutes` (default 60) | Sync all connected social account feeds via APScheduler |

---

## Frontend

### Dashboard Pages

| Route | Purpose |
|---|---|
| `/` | Landing / redirect |
| `/login` | Clerk login |
| `/signup` | Clerk signup |
| `/dashboard` | Main dashboard overview |
| `/dashboard/onboarding` | Site setup wizard (paste URL → detect platform → install pixel → verify) |
| `/dashboard/visitors` | Visitor list with filters (intent, identity status) |
| `/dashboard/visitors/[visitorId]` | Visitor detail with enrichment data |
| `/dashboard/companies` | Company-level visitor aggregation |
| `/dashboard/segments` | AI-generated segments |
| `/dashboard/campaigns` | Campaign management |
| `/dashboard/campaigns/[campaignId]` | Campaign detail |
| `/dashboard/social-accounts` | Connect/manage social platforms |
| `/dashboard/feed` | Social feed from connected accounts |
| `/dashboard/drafts` | AI-drafted replies/comments |
| `/dashboard/exports` | CSV exports |
| `/dashboard/settings` | Account settings, API keys |

### Key Components

| Component | Purpose |
|---|---|
| `clerk-token-sync.tsx` | Syncs Clerk JWT to the API client |
| `site-selector.tsx` | Site switcher in dashboard header |
| `pixel-install-guide.tsx` | Platform-specific pixel installation instructions |
| `post-card.tsx` | Social post display card |
| `draft-card.tsx` | AI draft display with edit/approve/reject actions |
| `draft-picker.tsx` | Draft strategy selector |
| `platform-badge.tsx` | Platform icon/label badge |

### UI Library

shadcn/ui components in `src/components/ui/`: button, card, label, badge, table, separator, select, textarea, input.

---

## Environment and Configuration

All config is in `apps/api/config.py` via pydantic-settings. Env files: `../../.env` and `.env` (relative to api/).

### Core

| Var | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | Environment (development/production) |
| `APP_SECRET_KEY` | `change-me-in-production` | Legacy JWT signing key |
| `API_BASE_URL` | `http://localhost:8000` | API server URL |
| `FRONTEND_URL` | `http://localhost:3000` | Frontend URL |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated CORS origins |

### Database

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://retarget:retarget_dev@localhost:5432/retarget_agent` | PostgreSQL connection |
| `CLICKHOUSE_HOST/PORT/USER/PASSWORD/DB` | localhost defaults | ClickHouse connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis cache |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | Celery results |

### Auth

| Var | Default | Purpose |
|---|---|---|
| `CLERK_SECRET_KEY` | `""` | Clerk backend secret |
| `CLERK_PUBLISHABLE_KEY` | `""` | Clerk frontend key |
| `JWT_SECRET` | `change-me-in-production` | Legacy JWT secret |

### Enrichment APIs (EasyTrack)

| Var | Purpose |
|---|---|
| `PEOPLE_DATA_LABS_API_KEY` | PDL enrichment |
| `IPINFO_TOKEN` | IP → company/geolocation (50K free/month) |
| `HUNTER_API_KEY` | Domain → employee emails (25 free/month) |
| `APOLLO_API_KEY` | Contact database + email finder (10K free/month) |
| `PROXYCURL_API_KEY` | LinkedIn profile scraping |
| `ANTHROPIC_API_KEY` | Legacy AI (use OpenRouter instead) |
| `OPENROUTER_API_KEY` | Primary AI — single key for 100+ models |
| `DEFAULT_AI_MODEL` | Default: `deepseek/deepseek-v4-flash:free` |
| `RESEND_API_KEY` | Email sending |

### Social OAuth (EasyEngage)

Each platform has: `{PLATFORM}_CLIENT_ID`, `{PLATFORM}_CLIENT_SECRET`, `{PLATFORM}_REDIRECT_URI`.
Platforms: TWITTER, FACEBOOK, LINKEDIN, TIKTOK.
Browser-based variants add: `{PLATFORM}_BROWSER_COOKIE_PATH`, `{PLATFORM}_BROWSER_HEADLESS`, `{PLATFORM}_BROWSER_COOKIES_B64`.

### Encryption

| Var | Purpose |
|---|---|
| `ENCRYPTION_KEY` | Fernet key for BYOK API keys (strict) |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for OAuth tokens (graceful) |

### Feature Flags

| Var | Default | Purpose |
|---|---|---|
| `MOCK_EXTERNAL_APIS` | `true` | Mock enrichment/identity APIs |
| `MOCK_SOCIAL_OAUTH` | `true` | Mock social OAuth flows |
| `SYNC_INTERVAL_MINUTES` | `60` | Feed sync interval |

### Rate Limits

| Var | Default | Purpose |
|---|---|---|
| `DEFAULT_DAILY_RESOLUTION_BUDGET` | `50` | Max identity lookups per site per day |
| `MAX_EMAILS_PER_HOUR_PER_SITE` | `50` | Email rate limit |

### Frontend Env

| Var | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | API base URL (default: `http://localhost:8000`) |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk frontend key (optional — routes are public without it) |

---

## Infrastructure

### Docker Compose (local dev)

| Service | Image | Ports |
|---|---|---|
| `postgres` | postgres:16-alpine | 5432 |
| `redis` | redis:7-alpine | 6379 |
| `clickhouse` | clickhouse/clickhouse-server:24-alpine | 8123, 9000 |

### Dockerfile (production)

- Base: `python:3.11-slim`
- Installs Playwright Chromium (for browser-based social platform actions)
- PYTHONPATH=/app
- CMD: `uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000}`

### Railway

- Builder: DOCKERFILE
- Restart policy: ON_FAILURE (max 10 retries)

---

## Business Rules

- Only resolve identity for visitors with `intent_score >= 40`
- Daily resolution budget cap per site (default: 50 lookups/day)
- Cache all API results in Redis (30-day TTL for identity, 7-day for enrichment)
- Never send emails without human approval
- Include unsubscribe link in every email
- Mark visitor as `do_not_email` after hard bounce
- Segmentation triggers when 10+ new enriched visitors accumulate
- Campaign status flow: `draft → approved → active → completed` (or paused)
- Max 50 emails per hour per site
- Never retry identity resolution for same visitor within 30 days if it failed
- All social engagement requires user to click send manually — zero automation on user accounts

---

## Known Technical Debt

- Inline ALTER TABLE migrations in `main.py` instead of Alembic (30+ statements run on every startup)
- `packages/ai/` and `packages/shared/` are empty placeholder directories
- Shopify integration and WordPress plugin generator exist in code but were unplanned — assess whether to keep
- Codebase still uses "retarget" naming internally — rename to "beam" planned before launch
- ClickHouse configured but events currently stored in PostgreSQL (MVP simplification)
- No root-level monorepo tooling (no turborepo, no pnpm workspaces)

---

## Scan Metadata

- Generated: 2026-05-28
- HEAD: 5993c48 (Auto-refresh expired OAuth tokens during feed sync)
- Mode: fresh (new project setup)
- Package manager: npm (frontend), pip (backend)
