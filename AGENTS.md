# ReTargetAgent - Agent Instructions

## Project Overview
AI agent that identifies anonymous website visitors, enriches their profiles (LinkedIn, Twitter, job info), and auto-generates retargeting campaigns across email, social, and paid ads.

## Tech Stack
- **Frontend:** Next.js 14 (App Router) + Tailwind CSS + shadcn/ui — `apps/web/`
- **Backend:** Python 3.12 + FastAPI (async) — `apps/api/`
- **Pixel:** Vanilla JS, Cloudflare Workers — `apps/pixel/`
- **Primary DB:** PostgreSQL (Supabase)
- **Event DB:** ClickHouse Cloud
- **Cache/Queue:** Redis (Upstash) + Celery
- **AI:** Anthropic Claude API (claude-sonnet-4-20250514)
- **Email:** Resend API
- **Identity:** People Data Labs + FullContact
- **Enrichment:** Proxycurl (LinkedIn) + Twitter API

## Project Structure
```
apps/api/          → FastAPI backend (Python)
  routers/         → API endpoints (auth, events, visitors, segments, campaigns, sites, exports)
  services/        → Business logic (auth, celery, visitor_aggregator, pixel_verifier, platform_detector)
  models/          → SQLAlchemy ORM (user, site, visitor, segment, campaign, enrichment, database)
  schemas/         → Pydantic request/response models
  tasks/           → Celery async tasks (resolution, aggregation, segmentation)
  agents/          → AI agent logic (segmenter, campaign_planner)
apps/web/          → Next.js 14 dashboard
  src/app/         → App Router pages (login, dashboard/*, onboarding)
  src/components/  → React + shadcn/ui components
apps/pixel/        → Tracking pixel (tracker.js + worker.js)
infra/             → Docker compose, env config
scripts/           → Seed scripts
```

## Coding Conventions

### Python (apps/api/)
- Type hints on ALL functions and variables
- Pydantic models for every API request/response
- Async functions for all I/O (database, HTTP, Redis)
- Use `structlog` for logging, never print()
- Use `httpx` (async) for HTTP calls, not requests
- Never swallow exceptions — log and re-raise
- Config via pydantic-settings, secrets via env vars
- Tests: pytest + pytest-asyncio

### TypeScript (apps/web/)
- Strict mode, no `any` types
- Server components by default, client only when needed
- API calls via shared client in `lib/api.ts`
- TanStack Query for data fetching
- react-hook-form + zod for forms

### Database
- Tables: snake_case, plural
- Columns: snake_case
- Foreign keys: {table_singular}_id
- All tables: id (UUID), created_at, updated_at
- Migrations via Alembic

## Key Business Rules
- Only resolve identity for visitors with intent_score >= 40
- Daily resolution budget cap: 50 lookups/day per site
- Cache API results in Redis (30d TTL identity, 7d enrichment)
- Never send emails without human approval
- Unsubscribe link in every email
- Mark visitor "do_not_email" after hard bounce
- Segmentation triggers at 10+ new enriched visitors
- Campaign flow: draft -> approved -> active -> completed (or paused)
- Max 50 emails/hour/site
- Never retry failed identity resolution within 30 days

## Mock Mode
All external APIs have mock mode (env: `MOCK_EXTERNAL_APIS=true`).

## Security
- Never hardcode API keys or secrets
- Never log PII
- Every external API call: 10s timeout, 3 retries with exponential backoff
