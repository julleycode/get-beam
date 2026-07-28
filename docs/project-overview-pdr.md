# Beam — Product Overview & PDR

Last updated: 2026-07-28

## Overview

**Beam** (public site: [getbeam.fyi](https://getbeam.fyi)) is an AI-assisted visitor intelligence and outreach product for indie founders, DTC operators, and small SaaS teams. A lightweight tracking pixel collects first-party behavioral data; the backend resolves anonymous visitors, enriches profiles, and drafts personalized outreach across email and social channels.

Legacy names in the repo: **ReTargetAgent**, **EasyTrack**. The dashboard still uses EasyTrack/EasyEngage product labels in some routes.

**Core stance (non-negotiable):** anti-bot automation. AI drafts; humans approve and send. Never auto-send outreach.

## Product Vision

Paste one script tag (or install via onboarding). Beam identifies who visited, enriches social/professional context, segments visitors with AI, and helps operators run retargeting campaigns—with human review at every send step.

Positioning: simpler and cheaper than enterprise CDPs (Klaviyo, HubSpot) for teams that want retargeting without a full growth org.

## Target Users

| Segment | Needs |
|---------|--------|
| Indie SaaS founders | Traffic but weak identity capture; want outreach without heavy tooling |
| DTC / vibe-coded web apps | Meaningful traffic, reluctant to force email gates |
| Small operators | Budget-conscious; cannot staff dedicated growth |

## Value Proposition

| Capability | User outcome |
|------------|--------------|
| Pixel + ingest | First-party events without breaking page load |
| Identity resolution | Anonymous → known profile (realistic 5–15% on low/international traffic) |
| AI segmentation | Gemini-powered segments from visitor behavior |
| Campaign drafts | Email + social copy drafted for review |
| EasyEngage | Social feed sync, draft generation, optional Gmail OAuth send |
| EvalLayer | Separate analytics for AI-agent traffic (not outreach targets) |

## Functional Requirements (current product)

### FR-1 Tracking & ingest
- Vanilla JS pixel (`apps/pixel`) posts batched events to `POST /api/v1/events/ingest`
- Consent modes, bot filtering, optional ingest abuse hardening (velocity caps, trusted-proxy IP)
- Events stored in **PostgreSQL** (`events` table), not ClickHouse

### FR-2 Visitor intelligence (EasyTrack)
- Visitor list, detail, intent scoring, company identification
- Identity resolution waterfall (RB2B, Leadpipe, PDL, ipinfo, etc.—env-gated)
- Segments with AI-assisted creation
- Known contacts, exports, CRM connectors (async push optional)

### FR-3 Campaigns & outreach
- Campaign planner, touchpoints, SendGrid send (or Gmail OAuth when connected)
- LinkedIn outreach via Chrome MV3 extension (cookie handoff to dashboard—no backend in extension)
- Outcomes / conversion goals (feature-flagged digests)

### FR-4 EasyEngage (social)
- OAuth for social platforms, feed sync (APScheduler job)
- Draft generation (Gemini primary; OpenRouter fallback for social replies)
- Human approval before publish/send

### FR-5 Billing & access
- Clerk RS256 + legacy JWT auth
- Gumroad Merchant-of-Record (active); Stripe/Lemon Squeezy legacy paths
- Plans, quotas, BYOK API keys (encrypted)

### FR-6 EvalLayer (AI agent traffic)
- Classify agent bots at ingest; `agent_visits` rollup separate from human visitors
- Dashboard `/agents` tab; strict guardrail: agent records never emailable
- Feature flag `agent_detection_enabled` defaults **OFF**

### FR-7 Ads audiences (in progress)
- Meta Custom Audiences live (flag-off default); Google Phase 3 in progress
- Pattern mirrors CRM connector push

## Non-Functional Requirements

| Area | Requirement |
|------|-------------|
| Privacy | PII encryption at rest; structured logging without secrets/locals |
| Compliance | MVP US-first; EU exclusion patterns in roadmap; GDPR deferred |
| Cost | Target API spend &lt; 40% of per-customer revenue ($49–199/mo tiers) |
| Accuracy UX | Do not promise 25–35% identity match on low traffic |
| Availability | Railway-deployed API; health check `/health` |
| Security | slowapi rate limits; webhook token auth (Gumroad URL token); Clerk JWT |

## Out of Scope (current)

- Fully automated send without human approval
- ClickHouse as live event store (client exists, unused)
- Celery worker fleet by default (`celery_worker_enabled=false`)
- EU GDPR product mode (v2 roadmap item)

## Success Metrics (MVP)

| Metric | Target direction |
|--------|------------------|
| Pixel install → first event | &lt; 5 minutes onboarding |
| Identity resolution rate | Honest UX for 5–15% realistic band |
| Draft → human send rate | Primary engagement KPI |
| Churn vs API cost | Stay within budget envelope per plan |

## Technical Constraints

- Monorepo: `apps/web`, `apps/api`, `apps/pixel`, `apps/extension`
- Python 3.11 in Docker; FastAPI async SQLAlchemy + asyncpg
- Next.js 14 App Router dashboard + static marketing under `public/beam/`
- Redis 7: cache, Celery broker (dormant), rate limiting
- PostgreSQL 16: all persistent data including events

## Acceptance Criteria (product-level)

1. Operator can sign up, create site, install pixel, see visitors within one session.
2. AI can propose a segment and campaign draft; operator must explicitly send.
3. Agent-classified traffic never appears as emailable visitor identity.
4. Billing checkout completes via Gumroad; plan gates enforced server-side.
5. Feature flags default OFF for new capabilities until operator enables post-migration.

## References

- [codebase-summary.md](./codebase-summary.md) — repo map
- [system-architecture.md](./system-architecture.md) — flows
- [project-roadmap.md](./project-roadmap.md) — shipped vs pending
- `process/context/all-context.md` — authoritative agent context
- `PRODUCT_ROADMAP.md` — original MVP phases (historical; see drift notes)
