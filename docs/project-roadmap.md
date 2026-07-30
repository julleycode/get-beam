# Project Roadmap

Last updated: 2026-07-30

## Overview

This roadmap merges **historical MVP phases** (`PRODUCT_ROADMAP.md`) with **current `process/features/` reality**. Treat shipped code + feature folders as source of truth; the original roadmap is partially stale.

## Original MVP Phases (PRODUCT_ROADMAP.md)

| Phase | Topic | Roadmap intent | Current status |
|-------|-------|----------------|----------------|
| 0 | Monorepo setup | Scaffold apps | **Shipped** (evolved beyond original tree) |
| 1 | Pixel + events | Ingest pipeline | **Shipped** (+ abuse hardening, bot flags) |
| 2 | Identity resolution | Waterfall enrich | **Shipped** (ongoing provider tuning) |
| 3 | Segmentation + AI | Claude segments | **Shipped** (Gemini, not Claude) |
| 4 | Campaigns | Email outreach | **Shipped** (human approve/send) |
| 5 | Dashboard | Operator UI | **Shipped** (EasyTrack + EasyEngage) |
| 6 | Billing | Stripe subscriptions | **Partial** — Gumroad MoR active; Stripe legacy |
| 7 | Polish + launch | Production deploy | **Ongoing** |

**Roadmap drift highlights:** ClickHouse events, Celery workers, Resend email, Anthropic primary AI, auto-send—all superseded. See [codebase-summary.md](./codebase-summary.md#readme--product_roadmap-drift).

## Feature Programs (`process/features/`)

### Shipped / code-complete

| Feature | Scope | Notes |
|---------|-------|-------|
| `visitors-identity` | Pixel → resolution → enrichment | `first-party-capture`, `owned-data-layer` completed |
| `pixel` | Ingest abuse hardening | Completed 25–26 Jul; cadence-bot-flag v1 EXECUTE+EVL green |
| `evallayer` | AI agent traffic detection | Code-complete 23 Jul; **live-validated 29–30 Jul** (17/17 local probes + real ChatGPT-User on lab). Attribution chain works; **person identity gap** documented — see [agent-detection-architecture](./agent-detection-architecture.md) §5 |
| `campaigns-outreach` | Campaigns, LinkedIn extension | Extension + onboarding in active folders |
| `billing` | Gumroad MoR, quotas | Active folder for ongoing billing work |
| `marketing-site` | Landing, blog, changelog | Content in `marketing/` |

### In progress

| Feature | Phase | Status |
|---------|-------|--------|
| `ads-audiences` | Phase 1 Foundation | Shipped 25 Jul; flag default OFF |
| `ads-audiences` | Phase 2 Meta live | EVL-green 26 Jul; env smoke gaps before production enable |
| `ads-audiences` | Phase 3 Google live | In progress |
| `agent-gateway` | Agent MCP / gateway + F2 marker | **Shipped** (flags OFF): gateway surfaces, F2 marker handoff, F12/F13 verification. Live probe green; wild marker survival + identity priority + F14 are next |
| `pixel` | cadence-bot-flag | Active; deferred gates (migration round-trip, live crawler validation) |
| `campaigns-outreach` | LinkedIn extension onboarding | Feasibility + active plans |

### Backlog (selected)

| Item | Feature | Note |
|------|---------|------|
| GDPR / EU mode | product | Explicitly v2 in original roadmap |
| Celery worker deployment | infra | Gated; APScheduler handles live jobs today |
| ClickHouse migration | data | Client vestigial; events in Postgres |
| Playwright Clerk auth harness | tests | Blocks several AC UI legs across programs |
| Docker migration round-trips | infra | Several tails offline-validated only |

## Product Capability Matrix

| Capability | Shipped | Flag / gate | Human docs |
|------------|---------|-------------|------------|
| Pixel ingest | Yes | — | [deployment-guide](./deployment-guide.md) |
| Visitor dashboard | Yes | — | — |
| AI segmentation | Yes | — | Gemini |
| Campaign email send | Yes | SendGrid / Gmail OAuth | Human approve |
| Social drafts (EasyEngage) | Yes | — | OpenRouter fallback |
| EvalLayer `/agents` | Yes | `agent_detection_enabled=OFF` | [agent-detection-architecture](./agent-detection-architecture.md) |
| Agent gateway / MCP | Yes | `agent_gateway_enabled=OFF` | Live-validated 29–30 Jul |
| Agent marker handoff (F2) | Yes | `agent_marker_enabled=OFF` | Needs `ENCRYPTION_KEY`; changes `offers.json` cache |
| Owned identity graph | Yes | `company_graph_enabled=OFF` | — |
| Identity signals (SendGrid) | Yes | `identity_signals_enabled=OFF` | — |
| Ad audiences Meta | Code-complete | `ad_audiences_enabled=OFF` | Sandbox smoke pending |
| Ad audiences Google | In progress | same flag | Phase 3 plan |
| Cadence bot flag | Code-complete | `cadence_bot_flag_enabled=OFF` | Deferred validation |
| Stripe billing | Legacy | env keys | Gumroad primary |
| Celery async tasks | Dormant | `celery_worker_enabled=OFF` | — |

## Near-Term Engineering Themes

1. **Agent marker wild survival test** — confirm real ChatGPT/Claude preserve `?_bam=` when surfacing links to humans (lab probe only so far).
2. **Identity resolution priority** — marker/handoff attribution does not feed `resolution_runner`; decide product policy before boosting `ai_source` visitors.
3. **Web Bot Auth (F14)** — RFC 9421 for vendors without published IP ranges (Anthropic); no active plan yet.
4. **Close Docker-gated validation** — migration round-trips, Playwright auth harness, Meta/Google sandbox smokes.
5. **Ads Phase 3 (Google)** — live OAuth + audience push.
6. **Capacity hardening** — incremental aggregation, pool sizing (see `capacity-hardening` plans in `process/general-plans/`).
7. **LinkedIn extension onboarding** — reduce install friction (backlog remedy notes exist).

## Out of Scope (explicit)

- Auto-send outreach without human approval
- Targeting AI agent records as emailable leads (EvalLayer guardrail)
- EU GDPR product mode (planned v2)
- Re-enabling ClickHouse without a dedicated migration program

## References

- `PRODUCT_ROADMAP.md` — historical MVP detail (968+ lines)
- `process/features/*/_GUIDE.md` — per-feature scope
- `process/context/all-context.md` — feature list + migration head notes
- [project-overview-pdr.md](./project-overview-pdr.md)
