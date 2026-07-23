# Beam - All Context

Last updated: 2026-07-21

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

This layered routing keeps context windows small. Never load the whole `process/context/` tree.

---

## Quick Start

For most substantial tasks:

1. read this file first
2. choose the smallest relevant root file or context group from the tables below
3. only then load deeper files

---

## Current Root Entry Points

<!-- The two tables below (Root Entry Points + Context Groups) are GENERATED from each
     context doc's frontmatter by `discover-context.mjs --emit-routing`. Do NOT hand-edit
     between the GENERATED markers — your edits will be overwritten on the next rebuild.
     To change a row, edit the owning doc's frontmatter (description / keywords) and re-emit.
     `--check-routing` fails lint if this block drifts from the frontmatter on disk. -->

<!-- GENERATED:routing -->
| File | Read when |
|---|---|
| `process/context/all-context.md` | any substantial planning, research, review, or implementation task |
| `process/context/planning/all-planning.md` | Plan-shape calibration (SIMPLE vs COMPLEX) and example plans — the planning group entrypoint/router |
| `process/context/tests/all-tests.md` | Test runners, commands, and debugging gotchas — the tests group entrypoint/router |

## Current Context Groups

| Group | Entry point | Scope |
|---|---|---|
| `planning/` | `process/context/planning/all-planning.md` | Plan-shape calibration (SIMPLE vs COMPLEX) and example plans — the planning group entrypoint/router |
| `tests/` | `process/context/tests/all-tests.md` | Test runners, commands, and debugging gotchas — the tests group entrypoint/router |
<!-- /GENERATED:routing -->

## Task Routing Table

| Task type | Load first | Then load |
|---|---|---|
| general repo research | `all-context.md` | the source dirs named by the task |
| implementation planning | `all-context.md`, `planning/all-planning.md` | the relevant example plan + active plan |
| test planning or verification | `all-context.md`, `tests/all-tests.md` | `TESTING.md` (repo root) for docker setup |
| debugging backend/tests | `all-context.md`, `tests/all-tests.md` | the failing service/router source |
| AI / agent-layer work | `all-context.md` (AI Layer section below) | `apps/api/services/gemini_client.py`, `apps/api/agents/` |
| visitor identity / enrichment | `all-context.md` | `process/features/visitors-identity/_GUIDE.md` |
| segments / campaigns / outreach | `all-context.md` | `process/features/campaigns-outreach/_GUIDE.md` |
| billing / quotas | `all-context.md` | `process/features/billing/_GUIDE.md` |
| blog / landing / SEO | `all-context.md` | `process/features/marketing-site/_GUIDE.md` |
| pixel / event ingest | `all-context.md` | `process/features/pixel/_GUIDE.md` |
| context maintenance | `all-context.md` | run the `vc-audit-context` skill after edits |

## Current Features

Feature-scoped plan folders under `process/features/` (each has `active/`, `completed/`, `backlog/` and a `_GUIDE.md` with scope + key files):

- `visitors-identity` — pixel visitors → identity resolution waterfall → enrichment → OSINT
- `campaigns-outreach` — AI segmentation, campaign planning, email + social outreach, drafts
- `billing` — Gumroad MoR billing, plans/quotas, BYOK keys
- `marketing-site` — public site: landing, blog, changelog, SEO (content sources in `marketing/`)
- `pixel` — tracking pixel, event ingest, consent, bot filtering
- `evallayer` — AI-agent traffic detection (agent_classifier, `/agents` API + dashboard tab, IP/rDNS
  verification, agent→company outreach-safe resolution, GEO/AEO analytics, outreach-exclusion
  guardrail); 8-phase program, code-complete 23-07-26, pending Docker-gate closure — see
  `process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md`

## Context Group Lifecycle

Context groups are durable knowledge domains, not feature folders.

Create a group when: a topic has 3+ durable docs; a single doc exceeds ~800 lines with separable subtopics; multiple agents repeatedly need only one slice of a large context file; the topic maps to a stable operational domain.

Do not create a group for temporary reports, plans/execution artifacts, or feature-specific content (that belongs in `process/features/...`).

Move or split one group at a time. Use `all-{group}.md` entrypoints. Run the `vc-audit-context` skill after every context organization change.

## Naming Convention

No `README.md` files inside `process/context/`. Canonical entrypoints use `all-*.md`: root is `process/context/all-context.md`, groups are `process/context/{group}/all-{group}.md`.

## Context Update Protocol

When durable project knowledge changes:

1. update the smallest relevant context file
2. update this file if routing, ownership, naming, or groups changed
3. update the owning `all-{group}.md` entrypoint when a group exists
4. run the `vc-audit-context` skill

---

## What Beam Is

AI agent that identifies anonymous website visitors, enriches their profiles (LinkedIn, Twitter, job info), and drafts retargeting outreach across email and social. "Clay.com meets Retention.com" but simpler and cheaper, built for indie makers and DTC founders. Product name: **Beam** (repo/legacy name: ReTargetAgent / EasyTrack). Solo-founder project.

Brand stance is deliberately **anti-bot**: AI drafts, the human approves and sends. Never build auto-send.

Full product spec: `PRODUCT_ROADMAP.md` (repo root).

## Repository Structure

```
getbeam/
  apps/
    web/                  -- Next.js 14 dashboard + public site
      src/app/            -- App Router pages (dashboard, blog, onboarding, sign-in/up)
      src/components/     -- React components (shadcn/ui based)
      src/lib/            -- api.ts client, hooks, utils
      e2e/                -- Playwright specs (7 files)
      public/beam/        -- onboarding assets, pixel snippets
    api/                  -- Python FastAPI backend
      routers/            -- API endpoints (visitors, campaigns, ai, events, billing, ...)
      services/           -- business logic (identity_resolver, enricher, gemini_client, ...)
      agents/             -- AI layer (segmenter, campaign_planner, workspace_tools, prompt_safety)
      models/             -- SQLAlchemy ORM models
      schemas/            -- Pydantic request/response models
      tasks/              -- Celery tasks (segmentation, aggregation, resolution, crm)
      config.py           -- pydantic-settings (all env vars)
    pixel/                -- vanilla JS tracking pixel (src/tracker.js)
  infra/docker-compose.yml -- local postgres:16 + redis:7 + clickhouse:24
  tests/                  -- pytest: unit/ (no deps) + integration/ (needs PG+Redis)
  marketing/              -- brand/launch/strategy/assets + content-writer references
  process/                -- this harness (context, plans, features, protocols)
  plan/                   -- LEGACY dated plan folders (pre-harness; read-only history)
  requirements.txt        -- Python deps (repo root, NOT apps/api/)
  pyproject.toml          -- pytest config only (markers unit/integration, asyncio auto)
  TESTING.md              -- docker-compose test setup guide
```

## Technology Stack

- **Frontend:** Next.js 14.2 (App Router) + React 18, Tailwind CSS + shadcn/ui + Radix, TanStack Query 5, react-hook-form + zod, Recharts, Clerk 5 (auth) + legacy JWT signup/login endpoints
- **Backend:** Python 3.11 (Dockerfile `python:3.11-slim`; type hints use 3.11-safe syntax only), FastAPI, SQLAlchemy 2 async + asyncpg, Alembic migrations, Celery 5 (redis broker) + APScheduler, structlog
- **Data:** PostgreSQL 16 (primary — events ingest also lands in Postgres, e.g. `agent_visits`), Redis 7 (cache/queue/rate limits). `apps/api/services/clickhouse_client.py` + `CLICKHOUSE_*` config exist but have zero callers anywhere in `apps/api` (confirmed 23-07-26) — vestigial/unused, not the live events store.
- **AI:** Google Gemini 2.5 Flash via raw httpx REST (`apps/api/services/gemini_client.py`). NOT Anthropic — `anthropic_api_key` is legacy; the only Claude call left is the public demo draft fallback in `routers/demo.py`. OpenRouter is the paid fallback for social replies.
- **Email:** SendGrid (Resend deprecated) + optional Connect-Gmail OAuth send
- **Identity/enrichment providers:** RB2B, Leadpipe, Capturify, People Data Labs, ipinfo, Hunter, Apollo, Proxycurl, TwitterAPI.io — all waterfall-gated, budget-capped, toggleable via env
- **Billing:** Gumroad (active MoR, URL-token webhook), Stripe + Lemon Squeezy legacy
- **Hosting:** Railway (api), pixel via CDN; browser automation via Playwright (scraping + e2e)

## AI Layer (agentic-lite, shipped 20-07-26)

All AI flows through `apps/api/services/gemini_client.py`:

- `gemini_generate(prompt, grounding=, response_json=)` — single-shot; `grounding=True` = provider-side Google Search (deep research, handle finding)
- `gemini_generate_json(prompt, validate=)` — single-shot + parse/validate + repair re-prompt (max 2 retries; exhaustion preserves legacy caller behavior)
- `gemini_agent_loop(prompt, tools=[ToolSpec...])` — bounded client-side tool loop: iteration cap 5, token budget 60k, wall-clock 60s, forced-final termination, sequential handler execution
- `ToolSpec` handlers MUST be read-only (shared AsyncSession — never commit/flush), tenant-scoped via closure, and sanitize output; the loop strips `<>` and fences untrusted payloads

Consumers: `agents/segmenter.py` + `agents/campaign_planner.py` (JSON repair), `routers/ai.py` `/ai/ask` (tool loop, falls back to single-shot; flag `AI_ASK_TOOLS_ENABLED`), `agents/workspace_tools.py` (tool registry). Planner tool loop exists but is OFF (`CAMPAIGN_PLANNER_TOOLS_ENABLED=false`, path untested with live model).

**Prompt-injection defense is mandatory:** any visitor-derived text entering a prompt goes through `agents/prompt_safety.py` (`sanitize_profiles` / `clean_text` / `wrap_untrusted`). `clean_text` strips `<>` so the `<untrusted_visitor_data>` fence is unforgeable. Never bypass it.

## AI-Agent-Traffic Layer (EvalLayer, shipped 23-07-26 — code-complete, see `process/features/evallayer/`)

Detects AI-agent visits (GPTBot, PerplexityBot, ClaudeBot, etc.) at ingest and keeps them
structurally separate from human Visitor/Event data, never as a targetable outreach contact:

- `apps/api/services/agent_classifier.py` — UA-pattern classifier, drop-vs-classify token split
- `apps/api/models/agent_visit.py` — dedicated `agent_visits` rollup table (one row per
  site/vendor/token tuple), never joined with `Visitor`/`Event`
- `apps/api/services/agent_verification.py` — OpenAI/Perplexity published IP-range confidence
  upgrade (ua-only → ip-verified); Anthropic stays UA-only by structural design (no published
  ranges)
- `apps/api/services/agent_company_resolution.py` — resolves a qualifying agent visit's IP to a
  real company via the existing `identity_resolver.py` waterfall, creating an ordinary human/company
  lead — the agent record itself is never contactable (`IdentifiedVisitor.source_agent_visit_id`
  hard-excludes it from `is_emailable_identity` — this is the program's highest-priority guardrail,
  regression-tested in `tests/unit/test_agent_origin_exclusion.py`)
- `apps/api/services/agent_aggregator.py` — read-only vendor/page/verification-method analytics,
  `GET /api/v1/agents/{site_id}/analytics`
- Feature flag: `agent_detection_enabled` in `apps/api/config.py` — **defaults OFF**
- 3 migrations pending live-apply (Docker-gated, never run against a real Postgres in the sandbox
  that built this): `d11b39a6c843` (agent_visits table), `a1c7e4f92b83` (Phase 5
  visitor.is_agent_derived / IdentifiedVisitor.source_agent_visit_id), and the AI-referral
  migration below (`b3f9a1d2c7e5`) — apply all three in order before enabling
  `agent_detection_enabled` in any real environment
- Docker/live-integration known-gaps consolidated in
  `process/features/evallayer/backlog/program-docker-verification-gaps_NOTE_23-07-26.md`

## AI-Referral Attribution (v1, shipped 23-07-26)

Classifies human visitors who arrived via a link from an AI answer/chat surface (ChatGPT,
Perplexity, Gemini, Copilot, Claude, You.com, Grok, DeepSeek, Mistral — explicitly excludes
in-SERP Google/Bing, a known coverage limit): `apps/api/services/ai_referral.py`
(`classify_ai_source`, pure). Adds `Visitor.first_touch_referrer` (fixed a pre-existing
lexicographic-MAX bug — now true chronological first touch) and `Visitor.ai_source` (migration
`b3f9a1d2c7e5`, pending live-apply). Surfaced as an "Arrived via" badge/pill/facet on the Visitors
dashboard; fed into the segmenter as a signal (not a bypass). Safety: `ai_source` is attribution
metadata on a separate write path from `source_agent_visit_id` — `is_emailable_identity` never
reads it, and AI-referred humans stay fully emailable (the opposite guarantee from EvalLayer's
agent-exclusion guardrail — these are real humans, not agents).

## Key Patterns and Conventions

**Python:** type hints on all functions; async for all I/O; `structlog` only (never `print()`); `httpx` async for external calls (never `requests`); every external call has timeout + retry/backoff + error handling; never swallow exceptions; Pydantic models for every API schema; config via `pydantic-settings` env only — no hardcoded secrets.

**TypeScript:** strict mode, no `any`; server components by default; API calls via shared client `apps/web/src/lib/api.ts` (POSTs get no client timeout — long AI calls are safe); TanStack Query for fetching; react-hook-form + zod for forms.

**Database:** tables snake_case plural; FK `{table_singular}_id`; every table has `id` (UUID), `created_at`, `updated_at`; Alembic for migrations.

**Mock mode:** every external API (providers, Gemini loop, SendGrid, CRM) must work with `MOCK_EXTERNAL_APIS=true` returning deterministic fakes — dev/tests/demo run keyless. Mock short-circuits live at the service layer (not in transport clients); `gemini_agent_loop` is the exception (mock branch inside, executes real handlers).

**Multi-tenancy:** every user-facing query filters through `Site.user_id == user.id`; unknown/foreign ids return 404 or "not found" data (never 403 — don't leak id existence).

## Business Guardrails (agents MUST respect)

1. **Email/outreach safety:** never auto-send; campaigns flow draft → approved → active with a human approval gate; unsubscribe link in every email; `do_not_email` after hard bounce; suppression list enforced; max 50 emails/hour/site.
2. **Quota/credit burn:** Gemini runs on free tier (RPM caps; `thinkingBudget: 0` on JSON calls — thinking adds 60-100s latency); identity resolution budget default 50/day/site, deep research 3/day; never retry failed identity resolution within 30 days; cache identity 30d / enrichment 7d in Redis; new external calls must have a mock path.
3. **PII/GDPR:** never log PII or prompt bodies (structlog events log keys/ids only); PII blind index + encryption keys required in prod (`validate_production`); raw events auto-purge at 90 days; GPC/DNT → `do_not_resolve` sticky; visitor data in prompts is hostile input (see AI Layer).
4. **Flaky e2e:** Playwright rules learned from CI failures are canonical — see `tests/all-tests.md` Debugging section before writing/modifying any e2e test.

## Environment and Configuration

**Config files:** `apps/api/config.py` (single Settings class, reads `.env`), `infra/docker-compose.yml`, `apps/web/playwright.config.ts`, `.claude/launch.json` (dev servers).

**Env var groups (names only, never values):**
- Core: `APP_ENV`, `APP_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, ClickHouse `CLICKHOUSE_*`
- Auth: `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`, `INVITE_ONLY`
- AI: `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_JSON_REPAIR_ATTEMPTS`, `GEMINI_TOOL_LOOP_*` (max_iterations/token_budget/timeout_s/output_max_chars), `AI_ASK_TOOLS_ENABLED`, `CAMPAIGN_PLANNER_TOOLS_ENABLED`, `OPENROUTER_API_KEY`, `MOCK_EXTERNAL_APIS`
- Identity graph: `RB2B_API_KEY`, `LEADPIPE_*`, `CAPTURIFY_*`, `FULLCONTACT_PIXEL_ID`, `CUSTOMERS_AI_PIXEL_ID` (+ `*_ENABLED` toggles)
- Enrichment waterfall: `PEOPLE_DATA_LABS_API_KEY`, `PROXYCURL_API_KEY`, `IPINFO_TOKEN`, `HUNTER_API_KEY`, `APOLLO_API_KEY`, `TWITTERAPI_IO_API_KEY`, `MAXMIND_*`
- Email: `SENDGRID_API_KEY`, `SENDGRID_WEBHOOK_SECRET`, `GOOGLE_CLIENT_*` (Gmail send)
- Social OAuth: `TWITTER_*`, `FACEBOOK_*`, `INSTAGRAM_*`, `LINKEDIN_*`, `TIKTOK_*`, `PHANTOMMM_*` (LinkedIn sidecar)
- Billing: `GUMROAD_*` (active), `STRIPE_*`, `LEMONSQUEEZY_*` (legacy)
- Encryption: `ENCRYPTION_KEY`, `TOKEN_ENCRYPTION_KEY`, `PII_HMAC_KEY`, `PII_ENCRYPTION_KEY` — prod startup fails fast if missing
- Traffic hygiene: `BLOCK_DATACENTER_TRAFFIC`, `BLOCK_PROXY_VPN_TRAFFIC`
- Feature flags: `ENABLE_OSINT_SCAN`, `ENABLE_CONTENT_READER`, `CHANGELOG_SYNC_ENABLED`, `OUTCOMES_DIGEST_ENABLED`, `REFERRALS_ENABLED`, `CRM_*`

## Open Questions / Outstanding Work

- `CAMPAIGN_PLANNER_TOOLS_ENABLED=true` (planner tool loop) needs live-model validation before prod enable
- Real-key Gemini smoke for `/ai/ask` agentic path not yet run (no key on dev machine) — check `gemini_tool_call` in structlog when run
- Legacy `plan/` folder (11 dated pre-harness plans) is read-only history — migrate still-relevant items into `process/features/*/backlog/` opportunistically
- e2e coverage gaps: billing + exports (see `tests/all-tests.md` Known Gaps)
- Docs drift: `PRODUCT_ROADMAP.md` + `README.md` still say Claude/`claude-sonnet-4` for segmentation — code runs Gemini (see AI Layer)
- EvalLayer + AI-referral: `agent_detection_enabled` defaults OFF; 3 migrations pending live-apply
  (`d11b39a6c843`, `a1c7e4f92b83`, `b3f9a1d2c7e5`) — see AI-Agent-Traffic Layer section above and
  `process/features/evallayer/backlog/program-docker-verification-gaps_NOTE_23-07-26.md`
- Successor program planned: "Handoff Detection" (human-behind-the-agent correlation) — not yet
  scaffolded on disk; see `evallayer-umbrella_PLAN_22-07-26.md` §Program-Level Closeout

## Scan Metadata

- Generated: 21-07-26 (vc-setup STUDY phase, informed by full-repo audit + legacy CLAUDE.md migration)
- HEAD: 8880a91
- Mode: fresh setup (Flow A with legacy-content merge)
- Package manager: npm (`apps/web`), pip + `.venv` (Python, deps in root `requirements.txt`)
