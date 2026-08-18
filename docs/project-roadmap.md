# Project Roadmap

Last updated: 2026-08-18

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
| `evallayer` | AI agent traffic detection | Code-complete 23 Jul; **live-validated 29 Jul – 1 Aug** (17/17 local probes + real ChatGPT-User on lab). Attribution chain works; soft-serve gate + edge `_bfm` marker shipped and live on `beamlab.nhantown.com` (lab only, not prod API); **person identity gap** documented — see [agent-detection-architecture](./agent-detection-architecture.md) §5, §5d |
| `campaigns-outreach` | Campaigns, LinkedIn extension | Extension + onboarding in active folders |
| `billing` | Gumroad MoR, quotas | Active folder for ongoing billing work |
| `marketing-site` | Landing, blog, changelog | Content in `marketing/` |

### In progress

| Feature | Phase | Status |
|---------|-------|--------|
| `visitors-identity` | Current US handoff | **Active / blocked**: see [identity-us-current-handoff.md](./identity-us-current-handoff.md) for the current plan selection conflict, Leadpipe health failure, and exact next TODOs |
| `ads-audiences` | Phase 1 Foundation | Shipped 25 Jul; flag default OFF |
| `ads-audiences` | Phase 2 Meta live | EVL-green 26 Jul; env smoke gaps before production enable |
| `ads-audiences` | Phase 3 Google live | In progress |
| `agent-gateway` | Agent MCP / gateway + F2 marker | **Shipped** (flags OFF): gateway surfaces, F2 marker handoff, F12/F13 verification, AI identity priority queue (7b1ed33). Live probe green; wild marker survival + F14 are next. Ops gate: provider keys (PDL/Proxycurl) for named person resolution |
| `evallayer` | Beam Lab soft-serve gate + edge `_bfm` marker | **Behaviourally shipped on lab** (`beamlab.nhantown.com`), plan files still `status: awaiting-execute-approval` — reconcile in next UPDATE PROCESS. `link_marker` migrations exist only in dev Postgres, not applied to prod API. See [beam-lab-resume.md](./beam-lab-resume.md) |
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
| Pixel ingest | Yes | `event_id` required (400 if missing) | [deployment-guide](./deployment-guide.md) |
| Incremental aggregation | Code-complete | `aggregation_incremental_enabled=OFF` | [deployment-guide](./deployment-guide.md#scale-ready-x20x30) |
| Site ingest ceiling | Code-complete | `site_ingest_limit_enabled=OFF` (155/min) | same |
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

1. **Agent marker wild survival — CONFIRMED for `_bam` (31 Jul), edge `_bfm` half-confirmed.** Real
   ChatGPT-User preserves `?_bam=` end-to-end on the offers-feed path (architecture doc §5b). The
   Beam Lab edge marker `?_bfm=` is verified from edge → agent → answer (AI reproduces the marked
   URL verbatim), but a real human click-through confirming the `events.link_marker` join has not
   yet been observed. Next: get that click, and retest the ChatGPT hop-to-link-page behavior with a
   natural prompt (see [beam-lab-resume.md](./beam-lab-resume.md)).
2. **Identity resolution priority** — **SHIPPED (7b1ed33):** `resolution_runner` now prioritizes `ai_attributable_human.desc()` (visitor has `ai_source` OR same-site `AgentHandoffLink`) before `intent_score.desc()`. Ops gate: provider keys (PDL/Proxycurl/FullContact) for named-person resolution.
3. **Web Bot Auth (F14)** — RFC 9421 for vendors without published IP ranges (Anthropic); no active plan yet.
4. **Beam Lab plan status reconcile** — both `agent-gate-lab_31-07-26` and `agent-gate-soft-serve_31-07-26` plans sit at `status: awaiting-execute-approval` while the soft-serve gate is already live on `beamlab.nhantown.com`; next UPDATE PROCESS pass should reconcile plan status with lab reality and decide whether/when to apply the `link_marker` migrations to the production API.
5. **ChatGPT browse intermittency** — homepage/canary-only fetches are reliable; hopping to a linked deep page is not (prompt-wording dependent, sometimes skipped even on direct URLs). Treated as an OpenAI browse-tool characteristic, not a Beam detection bug — see [agent-detection-architecture §5d](./agent-detection-architecture.md#5d-soft-serve-gate--marker-biên-_bfm-trên-beam-lab-31-07--01-08).
6. **Gemini/AWS-fetcher classification gap** — a Gemini-eval-window fetch used UA `got` on AWS ASN 14618, which the classifier does not recognize as an AI token, so no `agent_fetch_events` row is written for it. Optional product decision, not yet scheduled.
7. **Close Docker-gated validation** — migration round-trips, Playwright auth harness, Meta/Google sandbox smokes.
8. **Ads Phase 3 (Google)** — live OAuth + audience push.
9. **Capacity / scale-ready** — P1–P3 **code shipped** on `dev_nhantc2` (`8ffeb32` / `bbae139` / `73142d1`). Remaining is **operator**: migrate `c3f6a9d1e8b2` (`APP_ENV=production`) then deploy API; F9 watermark bootstrap + soak; then incremental flag; then ceiling/timeout. ~682 NULL `event_id` until migrate; `buildtolaunch` still active. Pro / Queue / ClickHouse still deferred. Runbook: [deployment-guide §Scale-ready](./deployment-guide.md#scale-ready-x20x30).
10. **LinkedIn extension onboarding** — reduce install friction (backlog remedy notes exist).

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
- [agent-detection-architecture.md](./agent-detection-architecture.md) — AI-agent detection, §5d for Beam Lab
- [beam-lab-resume.md](./beam-lab-resume.md) — Beam Lab experiment findings + open items
