# ReTargetAgent

## What This Project Is
AI agent that identifies anonymous website visitors, enriches their profiles (LinkedIn, Twitter, job info), and auto-generates retargeting campaigns across email, social, and paid ads.

Think "Clay.com meets Retention.com" but simpler, cheaper, built for indie makers and DTC founders.

## Read First
Before doing ANYTHING, read `PRODUCT_ROADMAP.md` in this repo root. It contains:
- Full architecture
- Database schemas
- API contracts
- Implementation order (follow it exactly)
- What is out of scope

## Tech Stack
- Frontend: Next.js 14 (App Router) + Tailwind CSS + shadcn/ui
- Backend: Python 3.12 + FastAPI
- Pixel: Vanilla JS (zero dependencies, under 5KB gzipped)
- Primary DB: PostgreSQL (via Supabase)
- Event DB: ClickHouse Cloud (or TimescaleDB as fallback)
- Cache: Redis via Upstash
- Queue: Celery with Redis broker
- AI: Anthropic Claude API (model: claude-sonnet-4-20250514)
- Email: Resend API
- Identity Resolution: People Data Labs API + FullContact API
- Enrichment: People Data Labs + Proxycurl (LinkedIn) + Twitter API
- Hosting: Railway
- Pixel CDN: Cloudflare Workers

## Project Structure
```
retarget-agent/
├── apps/
│   ├── web/                    # Next.js 14 dashboard
│   │   ├── app/                # App Router pages
│   │   ├── components/         # React components
│   │   ├── lib/                # Utilities, API client
│   │   └── package.json
│   ├── api/                    # Python FastAPI backend
│   │   ├── routers/            # API endpoints
│   │   ├── services/           # Business logic
│   │   ├── models/             # SQLAlchemy ORM models
│   │   ├── schemas/            # Pydantic request/response models
│   │   ├── tasks/              # Celery async tasks
│   │   ├── agents/             # AI agent prompts and logic
│   │   ├── config.py           # Settings via pydantic-settings
│   │   └── main.py             # FastAPI app entry
│   └── pixel/                  # Tracking pixel
│       ├── src/tracker.js      # Main pixel code
│       └── wrangler.toml       # Cloudflare Workers config
├── infra/
│   ├── docker-compose.yml      # Local dev: postgres, redis, clickhouse
│   └── .env.example
├── scripts/
│   └── seed.py                 # Seed test data
├── CLAUDE.md                   # This file
├── PRODUCT_ROADMAP.md          # Full specs (READ THIS)
└── README.md
```

## Coding Conventions

### Python (Backend)
- Type hints on ALL functions and variables
- Pydantic models for every API request/response schema
- Async functions for all I/O operations (database, HTTP calls, Redis)
- Use `structlog` for logging. Never print().
- Use `httpx` (async) for external API calls, not requests
- Error handling: never swallow exceptions. Log and re-raise or return proper HTTP error
- Config: all secrets via environment variables, loaded through pydantic-settings
- Tests: pytest + pytest-asyncio. Test critical paths.

### TypeScript (Frontend)
- Strict mode enabled
- No `any` types
- Use server components by default, client components only when needed
- API calls via a shared client in `lib/api.ts`
- Use react-query (TanStack Query) for data fetching and caching
- Forms: use react-hook-form + zod validation

### Database
- Tables: snake_case, plural (visitors, campaigns, segments)
- Columns: snake_case
- Foreign keys: {table_singular}_id
- All tables have: id (UUID), created_at (timestamp), updated_at (timestamp)
- Use database migrations (Alembic for Python)

### General
- Never hardcode API keys, URLs, or secrets
- Never store PII in logs
- Every external API call must have: timeout (10s default), retry logic (3 attempts with exponential backoff), error handling
- Prefer simple solutions over clever ones
- If something can fail, handle the failure case

## Implementation Order
Follow this EXACT order from PRODUCT_ROADMAP.md:
1. Project setup (monorepo, env, docker-compose)
2. PostgreSQL schema (all tables)
3. ClickHouse schema (events table)
4. Pixel JavaScript
5. Event ingestion API endpoint
6. Visitor aggregation job
7. Identity resolution service
8. Enrichment service
9. Celery task orchestration
10. AI segmentation agent
11. AI campaign planner agent
12. Email sending service
13. CSV export service
14. Auth
15. Dashboard pages (onboarding -> visitors -> detail -> segments -> campaigns -> exports -> settings)
16. Integration testing
17. Deploy

Do NOT skip steps. Test each step before moving to the next.

## Key Business Logic Rules
- Only resolve identity for visitors with intent_score >= 40
- Daily resolution budget cap per site (default: 50 lookups/day)
- Cache all API results in Redis (30 day TTL for identity, 7 day for enrichment)
- Never send emails without human approval
- Include unsubscribe link in every email
- Mark visitor as "do_not_email" after hard bounce
- Segmentation triggers when 10+ new enriched visitors accumulate
- Campaign status flow: draft -> approved -> active -> completed (or paused)
- Max 50 emails per hour per site
- Never retry identity resolution for same visitor within 30 days if it failed

## Mock/Test Mode
All external API services (People Data Labs, FullContact, Proxycurl, Resend) must have a mock mode that returns fake data. This allows:
- Development without burning API credits
- Automated testing
- Demo mode for potential customers

Toggle via env var: `MOCK_EXTERNAL_APIS=true`
