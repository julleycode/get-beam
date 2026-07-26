# Beam - All Context

Last updated: 2026-07-26

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

- `visitors-identity` — pixel visitors → identity resolution waterfall → enrichment → OSINT →
  first-party capture expansion (value-based field matching, mailto/URL-param, cross-browser
  autofill, shadow-DOM/same-origin-iframe) feeding the owned identity graph
- `campaigns-outreach` — AI segmentation, campaign planning, email + social outreach, drafts
- `billing` — Gumroad MoR billing, plans/quotas, BYOK keys
- `marketing-site` — public site: landing, blog, changelog, SEO (content sources in `marketing/`)
- `pixel` — tracking pixel, event ingest, consent, bot filtering; ingest-abuse-hardening
  (rotating-IP-flood defense: body-size cap, trusted-proxy IP resolution, per-site ceiling,
  write-time velocity flag, operator observability) shipped 25-07-26, archived 26-07-26 with 2
  known-gaps — see Ingest Abuse Hardening section below
- `evallayer` — AI-agent traffic detection (agent_classifier, `/agents` API + dashboard tab, IP/rDNS
  verification, agent→company outreach-safe resolution, GEO/AEO analytics, outreach-exclusion
  guardrail); 8-phase program, code-complete 23-07-26, pending Docker-gate closure — see
  `process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md`
- `ads-audiences` — OAuth-linked ad channels (Meta Custom Audiences, Google Data Manager API,
  LinkedIn deferred/CSV-only) with direct segment-audience push mirroring the CRM connector
  pattern; 3-phase program. Phase 1 Foundation (models, `services/ads/` registry, router, mock-mode
  parity, UI panel) shipped 25-07-26 — mock-mode complete, `ad_audiences_enabled` default OFF, 2
  env-only known-gaps (migration round-trip Docker-gated, Playwright auth harness). Phase 2 (Meta
  live — real OAuth, Custom Audience create/upload, ToS-precondition error surfacing, min-size
  warning) code-complete + EVL-green 26-07-26 (14 gates, no regression); 3 env-only known-gaps
  before `✅ VERIFIED`/production-enable: Meta sandbox Hybrid smoke (mandatory pre-enable operator
  step), AC7 Playwright UI legs (blocked on the same Clerk auth-harness gap as Phase 1), AC13 exact
  error code/subcode (Agent-Probe residual, fails safe). Phase 3 (Google live) in progress — see
  `process/features/ads-audiences/active/ad-audiences_25-07-26/ad-audiences-umbrella_PLAN_25-07-26.md`

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
    extension/            -- LinkedIn Outreach Connect browser extension (Chrome/Edge MV3, esbuild,
                             own Playwright e2e); "dumb pipe" to the dashboard tab, zero backend
                             surface — see campaigns-outreach feature folder
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
- 11 migrations pending live-apply, in order (Docker-gated, never run against a real Postgres in
  the sandbox that built this — chain verified by reading each file's `revision`/`down_revision`
  header; **TRUE current head re-confirmed LIVE 26-07-26 via `alembic -c apps/api/alembic.ini
  heads`: `d5b1f7c3a908` — single head, no branching**): `d11b39a6c843` (agent_visits
  table) → `a1c7e4f92b83` (Phase 5 visitor.is_agent_derived / IdentifiedVisitor.source_agent_visit_id)
  → `b3f9a1d2c7e5` (AI-referral, see below) → `c4e8f1a9d2b7` (Handoff Detection Phase H1,
  agent_fetch_events) → `f8a2c1d9b3e7` (company_graph, owned-data-layer Phase 1) →
  `a3e9f1c7d2b5` (identity_signals, owned-data-layer Phase 2) → `e2a4c7f81b93` (Handoff
  Detection Phase 2, agent_handoff_links) → `a9f2c1e7b4d6` (`ck_visitor_emails_source` CHECK
  constraint, first-party-capture Phase 3) → `c7d3b8e1f624` (ingest-abuse-hardening P4, see
  Ingest Abuse Hardening section below) → `b7d3e9f1a4c2` (add_ad_connections, ads-audiences) →
  `c8e4f2a6b1d9` (add_ad_audience_links, ads-audiences) → `d5b1f7c3a908`
  (add_site_last_aggregated_at, capacity-hardening — **current head**). Apply all eleven in order
  before enabling `agent_detection_enabled`, `company_graph_enabled`, `identity_signals_enabled`,
  `site_ingest_limit_enabled`, or `ingest_velocity_enabled` in any real environment. Re-confirm via
  `alembic heads` before applying — other work may advance the head further (it already has,
  repeatedly, from concurrent programs — see migration-collision memory note). Round-trip
  (`upgrade head` → `downgrade -1` → `upgrade head`) proven clean on a disposable Postgres container
  24-07-26 for the chain up to `a9f2c1e7b4d6` only, as part of owned-data-layer/first-party-capture
  closure. The 4 migrations added after that point (`c7d3b8e1f624`, `b7d3e9f1a4c2`, `c8e4f2a6b1d9`,
  `d5b1f7c3a908`) are offline `--sql`-validated only, NOT live-round-tripped — this is NOT a
  production live-apply, which remains a separate explicit operator action.
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

## Owned Identity Data Layer (v1, shipped 23-07-26 — VERIFIED 24-07-26)

Makes every paid/free identity+company lookup a permanent, cross-tenant asset instead of a
transient cache hit, and adds a strictly corroborating (never identity-creating) signal source
from existing outbound email engagement:

- `apps/api/models/company_graph.py` — `CompanyGraphNode`, durable cross-tenant company-from-IP
  store (ip/domain/company_name/source/confidence, unique on `(ip, source)`). Write-through on
  every successful free-rDNS resolve (and, when enabled, paid PDL/IPinfo hits) via
  `apps/api/services/company_resolver.py`; read-time staleness re-validation (default 75-day
  window), no cron. `_graph_node_by_email` in `identity_resolver.py` now returns full profile
  fields (was name-only). Same cross-tenant posture as `beam_identity_graph`.
- `apps/api/models/identity_signal.py` — `IdentitySignal`, one row per SendGrid open/click
  engagement event (PII ciphertext + blind index, same pattern as `beam_identity_graph` — never
  plaintext email). `apps/api/services/identity_signals.py`: `record_signal()` (4 write gates —
  datacenter IP, proxy/VPN, suppression list, `do_not_resolve` sticky), `decay_confidence()` (pure,
  computed at read time), `corroborate_identity()` (join-only helper — **structurally cannot**
  create or upgrade an `IdentifiedVisitor`; the module imports zero `IdentifiedVisitor` write path,
  only read-only SELECTs for the write gates). `apps/api/routers/webhooks.py` SendGrid handler
  gained a new `open`/`click` branch, structurally separate from the existing
  `_SUPPRESS_EVENTS` branch (bounce/dropped/spamreport unchanged, regression-tested).
  `apps/api/services/email_sender.py` gained an optional `custom_args` param (SendGrid echoes it
  back on webhook events so `webhooks.py` can attribute a signal to `site_id`/`visitor_id`) plus
  always-on explicit `tracking_settings`; `campaign_sender.py` passes `custom_args` at its
  identified-visitor send call site.
- Feature flags: `company_graph_enabled`, `identity_signals_enabled` in `apps/api/config.py` —
  both **default OFF** (`company_graph_staleness_days` default `75`); flipping either to `True` in
  a real environment is an explicit human, post-migration-live-apply operator action, matching the
  `agent_detection_enabled` precedent.
- Status 24-07-26: **VERIFIED and archived**. Docker-gate closure (EVL final run, 24-07-26,
  independent): migration round-trip clean on a disposable Postgres (chain to head
  `a9f2c1e7b4d6`), `test_company_graph.py` 14/14, integration `company_graph`+`identity_signals`
  5/5, unit regression `test_agent_origin_exclusion.py` 18/18, donor `test_company_resolver.py`
  59/59. See `process/features/visitors-identity/completed/owned-data-layer_23-07-26/` and the
  resolved backlog note
  `process/features/visitors-identity/backlog/owned-data-layer-docker-verification_NOTE_23-07-26.md`.
- Known-gap (still open): SendGrid live open/click payload shape + `custom_args` echo shape
  unverified against a real payload (Agent-Probe tier); account-level SendGrid tracking-settings
  override behavior needs-live-provider, not probed per policy — see
  `process/features/visitors-identity/backlog/post-docker-gate-followups_NOTE_24-07-26.md`.

## First-Party Email Capture Expansion (v1, shipped 24-07-26 — VERIFIED 24-07-26)

Widens `apps/pixel/src/tracker.js`'s CLEAN first-party email capture surface — the raw seed feeding
`visitor_emails` → the owned identity graph above — without loosening the "visitor must have
actively engaged this session" rule:

- **Value-based field matcher**: on submit/blur/change, any text-shaped input whose *value* looks
  like an email is captured even when the field's name/id/type doesn't contain "email" (e.g.
  `name="username"` login fields) — additive to, not a replacement of, the existing name/type
  matcher.
- **mailto: click capture** — reuses the existing click listener, parses `href="mailto:..."`.
- **URL-param capture** (`?email=`) — reuses the Phase-05 `pii_crypto` dual-write + domain-only
  logging path unchanged (no new client-side crypto); placed AFTER the tracker's
  `GATED`/`consentDecision` init block specifically to avoid bypassing the EU consent-hold (a
  VALIDATE-found ordering hazard, now Hard Guardrail G7).
- **Cross-browser autofill hardening** + **same-origin shadow-DOM / same-origin-iframe** capture
  via `composedPath()[0]` and `contentDocument` (wrapped in try/catch on cross-origin
  `SecurityError` — the enforcement mechanism, not a workaround).
- **Per-site config**: `data-capture-mailto`/`data-capture-url-param` script-tag attributes
  (default "on", opt-out not opt-in).
- **`visitor_emails.source` formalized**: `VISITOR_EMAIL_SOURCES` enum + `normalize_source()` in
  `apps/api/models/visitor_email.py`, backed by migration `a9f2c1e7b4d6`
  (`ck_visitor_emails_source` CHECK constraint, additive/superset, offline-validated only).
- New test infra: `apps/pixel/e2e/` — the first automated Playwright harness `tracker.js` capture
  logic has ever had (own config, chromium/webkit/firefox projects).
- Status 24-07-26: **VERIFIED and archived**. Docker/browser-gate closure (EVL final run,
  independent): AC5 webkit/firefox autofill legs 2/2 passed, AC11 `do_not_resolve` integration
  re-confirm 1/1 passed (non-vacuous: real `Visitor(do_not_resolve=True)`, real `record_signal()`,
  asserts insert count==0), backend unit regression 19/19 passed. All 15/15 SPEC ACs now met. See
  `process/features/visitors-identity/backlog/first-party-capture-deferred-gates_NOTE_24-07-26.md`
  (RESOLVED) and `process/features/visitors-identity/completed/first-party-capture_24-07-26/`.

## Ingest Abuse Hardening (v1, shipped 25-07-26 — archived 26-07-26, 2 known-gaps)

Hardens `POST /ingest` against a rotating-IP flood/DDoS (spread across many IPs, each staying
under the per-IP allowance while one site absorbs the aggregate) with 5 additive layers, in order:

- **P1 — streaming body-size guard.** `IngestBodySizeLimitMiddleware` in `main.py`, pure ASGI
  (matches the `PixelCORSMiddleware` precedent), scoped to `/api/v1/events/ingest` only. Rejects
  `413` via a `Content-Length` fast path plus a running byte counter inside a wrapped `receive()`
  (catches chunked/forged-header cases) — never reads past the cap.
- **P2 — trusted-proxy IP resolution.** New `apps/api/services/ip_resolution.py`
  (`resolve_client_ip()`, `client_ip_key_func()`) replaces the old spoofable `_extract_ip()`.
  Takes the Nth-from-the-right `X-Forwarded-For` entry (discarding the forgeable prefix);
  misconfiguration/absence always falls back to `request.client.host`. The per-IP slowapi limiter's
  `key_func` now uses this resolver everywhere IP matters.
- **P3 — per-site ingest ceiling.** A second slowapi limiter keyed on `request.state.site_id`
  (stashed via a genuine `Depends()`, inert unless the flag below is on) — the layer the per-IP
  limiter structurally cannot see (a flood spread across 500 IPs never trips any single bucket).
- **P4 — write-time velocity flag.** New `apps/api/services/ingest_velocity.py`: flags a site's
  events when BOTH distinct-visitor count is high AND fingerprint diversity is low within a window
  (an organic viral spike has many visitors but many *real* fingerprints, so it never trips).
  New columns `events.is_flagged_abuse`, `visitors.is_abuse_flagged`,
  `identified_visitors.is_abuse_flagged` (migration `c7d3b8e1f624`) — flag-but-store, never drops
  the row. `visitor_aggregator.py`'s rollup SQL excludes flagged rows from every metric aggregate
  via `FILTER (WHERE NOT is_flagged_abuse)` (NOT a CTE-level `WHERE` — see Deviation below) while the
  flag still propagates `Event → Visitor → IdentifiedVisitor` via `BOOL_OR`/sticky-`OR` merge.
  `is_emailable_identity()` gained a third guard parameter `is_abuse_flagged`, wired at all 3 call
  sites (`campaign_sender.py`, `csv_exporter.py`, and `routers/campaigns.py:725` — a 3rd site found
  by grep, not named in the original plan).
- **P5 — operator observability.** `GET /api/v1/sites/{site_id}/ingest-health`
  (`apps/api/routers/ingest_health.py`) — tenant-scoped, counts/ratios/flood-verdict only, no PII.

**New feature flags/settings in `apps/api/config.py`** (`## ─── Ingest abuse hardening (P1–P5) ───`
block) — all default OFF/permissive, same operator-gated posture as `agent_detection_enabled`:
  - `ingest_body_max_bytes: int = 262_144` (256 KB; always-on, not a toggle — this is the P1 cap itself)
  - `trusted_proxy_hops: int = 0` (0 = trust nothing, XFF ignored entirely; raising this is a
    deliberate operator action set to an OBSERVED hop count, never guessed — see inline config.py
    comment for the collapse/bypass tradeoff)
  - `site_ingest_limit_enabled: bool = False` + `site_ingest_limit_per_minute: int = 3000`
    (placeholder threshold — tune from OBSERVED per-site p99 before enabling, never ship the 3000
    default live)
  - `ingest_velocity_enabled: bool = False` + `ingest_velocity_window_seconds: int = 60` +
    `ingest_velocity_visitor_threshold: int = 200` +
    `ingest_velocity_min_fingerprint_diversity: float = 0.3`
  - **Required rollout order** (documented inline in config.py): `trusted_proxy_hops` (once the
    real hop count is observed) → THEN `site_ingest_limit_enabled` (after ~1 week of real per-site
    volume) → THEN `ingest_velocity_enabled` last. Enabling velocity/site-ceiling before
    `trusted_proxy_hops` is correct would tune both against already-collapsed per-IP traffic.
  - Note: inline comments on these two settings also reference a concurrent, separate
    `general-plans/active/capacity-hardening_25-07-26/` program (Phase 2) that refined the
    same settings' rollout guidance — the settings are shared/co-owned across both plans, not a
    conflict, but worth knowing if either plan is revisited.
- **Migration `c7d3b8e1f624`** (`add_ingest_abuse_flag`) chains directly off the prior chain's head
  `a9f2c1e7b4d6`. **TRUE current alembic head, re-verified live 26-07-26 via
  `alembic -c apps/api/alembic.ini heads`: `d5b1f7c3a908` — single head, no branching.** Two
  unrelated `ads-audiences` migrations landed concurrently during EXECUTE and chained cleanly on
  top: full chain is now `a9f2c1e7b4d6 → c7d3b8e1f624 (this migration) → b7d3e9f1a4c2
  (add_ad_connections) → c8e4f2a6b1d9 (add_ad_audience_links) → d5b1f7c3a908
  (add_site_last_aggregated_at, current head)`. Offline `--sql` validated clean both directions;
  **live round-trip on a disposable Postgres NOT run** (Docker daemon down in the EXECUTE
  environment) — Known-Gap, see backlog note below. Re-run `alembic heads` immediately before any
  live apply; other concurrent work may extend the chain further.
- Status 26-07-26: **archived with 2 known-gaps** (EVL-PASS: 24 unit + 16 integration tests, 0
  failures, 0 EVL fix cycles). See
  `process/features/pixel/completed/ingest-abuse-hardening_25-07-26/` and
  `process/features/pixel/backlog/ingest-abuse-hardening-deferred-gates_NOTE_25-07-26.md` (open:
  migration live round-trip; AC-4a mutation-kill re-verification).

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
- EvalLayer + AI-referral + owned-data-layer + first-party-capture + ingest-abuse-hardening:
  `agent_detection_enabled`, `company_graph_enabled`, `identity_signals_enabled`,
  `site_ingest_limit_enabled`, `ingest_velocity_enabled` all default OFF; 11 migrations pending
  PRODUCTION live-apply (`d11b39a6c843` → `a1c7e4f92b83` → `b3f9a1d2c7e5` → `c4e8f1a9d2b7` →
  `f8a2c1d9b3e7` → `a3e9f1c7d2b5` → `e2a4c7f81b93` → `a9f2c1e7b4d6` → `c7d3b8e1f624` →
  `b7d3e9f1a4c2` → `c8e4f2a6b1d9` → `d5b1f7c3a908` — **current head, single head, confirmed LIVE
  via `alembic heads` on 26-07-26**; round-trip verified clean on a disposable dev Postgres only up
  to `a9f2c1e7b4d6` (24-07-26) — the 4 migrations after that point are offline `--sql`-validated
  only, NOT yet live-round-tripped, and NONE of the 11 are applied to any real environment) — see
  AI-Agent-Traffic Layer + Owned Identity Data Layer + First-Party Email Capture Expansion + Ingest
  Abuse Hardening sections above,
  `process/features/evallayer/backlog/program-docker-verification-gaps_NOTE_23-07-26.md`,
  `process/features/visitors-identity/backlog/owned-data-layer-docker-verification_NOTE_23-07-26.md`
  (RESOLVED), `process/features/visitors-identity/backlog/first-party-capture-deferred-gates_NOTE_24-07-26.md`
  (RESOLVED), `process/features/visitors-identity/backlog/post-docker-gate-followups_NOTE_24-07-26.md`
  (open: 5 unrelated integration failures + conftest Redis-isolation hardening), and
  `process/features/pixel/backlog/ingest-abuse-hardening-deferred-gates_NOTE_25-07-26.md` (open:
  migration live round-trip; AC-4a mutation-kill re-verification)
- Successor program planned: "Handoff Detection" (human-behind-the-agent correlation) — not yet
  scaffolded on disk; see `evallayer-umbrella_PLAN_22-07-26.md` §Program-Level Closeout

## Scan Metadata

- Generated: 21-07-26 (vc-setup STUDY phase, informed by full-repo audit + legacy CLAUDE.md migration)
- HEAD: 8880a91
- Mode: fresh setup (Flow A with legacy-content merge)
- Package manager: npm (`apps/web`), pip + `.venv` (Python, deps in root `requirements.txt`)
