---
name: context:all-context
description: "Root context entrypoint — architecture, API surface, conventions, env, feature routing"
keywords: architecture, api, visitors, privacy, do_not_resolve, clear-privacy-hold, identity, monorepo, env, conventions, routing
related: [context:all-tests, context:all-planning]
date: 10-08-26
---

# Beam - All Context

Last updated: 2026-08-10

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
| Beam Lab / edge AI detection | `docs/beam-lab-resume.md` | `docs/beam-lab-team-brief.md` (team talk), `docs/agent-detection-architecture.md` §5d, `docs/journals/260801-0051-beam-lab-soft-serve-bfm.md`, `infra/cloudflare/beam-lab/` |
| Supabase prod DB (`retarget-agent`) | `docs/supabase-retarget-agent.md` | MCP + IDE: project ref **`hylcleqxlkdblibpdhhm`**. Never use `buildtolaunch` / `supabase-fuchsia-book`. |
| Agent fetch beacon Worker (splittrip) | `infra/cloudflare/agent-beacon-worker/README.md` | Cloudflare account Worker **`beam-agent-beacon-splittrip`** (id `9e74d042…`); source `infra/cloudflare/agent-beacon-worker/`; deploy `npx wrangler deploy --env splittrip`. MCP get/build/push MUST use this Worker — not `quota-tracker`. |
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
  autofill, shadow-DOM/same-origin-iframe) feeding the owned identity graph. Active task folders
  (07-08-26 autopilot run reconciled the set; none pushed/merged):
  - `graph-erasure-compliance_07-08-26` — SPEC + COMPLEX PLAN, **planned, not yet VALIDATE'd**.
    Closes the gap where per-visitor GDPR erasure (`apps/api/routers/visitors.py:403-439`) never
    deletes cross-tenant `beam_identity_graph` rows, plus stale public legal copy.
    **Integration gates attempted 07-08-26 (Docker gate run): 7/14 pass, 8/14 blocked on
    test-FIXTURE bugs (NOT source bugs — `IdentifiedVisitor` has no `first_seen`/`last_seen`;
    `Site` has no `domain` col, needs `name`+`url`). Entry-gate for identity-coop still UNMET.
    Migration `d1a6c4e93f27` live round-trip IS closed (KG-5). See
    `backlog/docker-gate-run-findings_NOTE_07-08-26.md`.**
  - `github-reader_07-08-26` — **EXECUTED + EVL green 8/8 (07-08-26).** New
    `apps/api/services/github_reader.py` (flag `enable_github_reader` default OFF,
    `github_osint_token`, 7d cache, fail-closed rate limit, single-host SSRF guard, `clean_text`
    sanitization) + enricher call site `_fetch_and_store_github`; zero migrations, 1197-unit lane
    green. Known-gaps: live GitHub response shape unproven; CONCERN-2 sibling-clobber documented
    not fixed (`backlog/social-context-wholesale-overwrite-bug_NOTE_07-08-26.md` — its overwrite
    half is resolved by social-context-merge below).
  - `social-context-merge_07-08-26` — **EXECUTED + EVL green (07-08-26).** `store_social_context`
    (`apps/api/services/social_intelligence.py`) now merge-preserving (the 1 overwrite writer of 9
    fixed; census of 9 writers verified), deep-research meter stamp removed. PVL converged after 3
    passes; 4 backlog notes written. **✅ VERIFIED 07-08-26** — AC-7 Hybrid gate ran in the
    Docker gate run (`test_usage_limits.py` 3/3 vs real Postgres, both SQL residuals proven);
    archival pending user.
  - `identity-coop_07-08-26` — Phase 1 **Dependency-BLOCKED** on graph-erasure reaching LIVE
    (entry gate); plan converged via supplement (bool-return accrual gating,
    write-nothing-when-blocked privacy invariant, site_id-only ledger, partial-unique dedup).
    `backlog/identity-coop-entry-gate-spec-a-live_NOTE_07-08-26.md` tracks 4 clearing conditions;
    phases 2-3 skipped.
  - `identity-p1p2-status-observability_02-08-26` — audit verdict 07-08-26: ALL 3 phases
    DONE-ON-DISK (vocabulary since renamed by identity-vocab-reconcile); its own `plan.md` says
    `status: completed`. Archive-ready debt — RECOMMEND moving to `completed/` (not yet moved).
  - `identity-coverage-pixel-fppro_02-08-26` — audit verdict 07-08-26: Ph.01 done (manual gate
    transferred to recovery program); Ph.02 SUPERSEDED by `plans/260805-1543-identity-coverage-recovery/`
    on branch `dev_nhantc2` (outside `process/`, invisible to plan-discovery); Ph.03 backlog
    needs-live-provider (fp3 may obviate — measure first); Ph.04 docs half EXECUTED 07-08-26
    (`benchmark-template.csv` + `benchmark-runbook.md`; measurement half needs human panel +
    Leadpipe revival).
  - `ip-org-database_07-08-26` — **Pillar 1 (own IP-to-Company data): Phases 1-2 EXECUTED + EVL
    green 6/6 (1 fix cycle) + live-proven on local dev DB 07-08-26.** Self-hosted CAIDA
    pfx2as+AS2Org pipeline: `ip_org_prefixes` table (migration `a3e8d5c71f02`, cidr GiST),
    `services/ip_org_ingest.py` (staging-swap load, advisory lock), `services/ip_org_lookup.py`
    (longest-prefix, org-kind-filtered, fail-open), resolver-ladder insert in
    `company_resolver.py` (after rDNS, before paid; write-through `company_graph`
    `source="rir_asn"` conf 0.45 — first writer of `company_graph.company_name`),
    `scripts/refresh_ip_org.py` CLI with fail-closed local-host guard. Live-proven: full chain
    from EMPTY DB to head in 8s; live down/up round-trip `a3e8d5c71f02`↔`f2c81a6b4d09`;
    `--apply` loaded 967,079 rows twice (341s/158s, swap + index-rename proven); crash-safety
    accidentally proven (container killed mid-load → 0 rows leaked); GiST scan warm 2-6ms,
    cold 26-385ms. org_kind: org 63.8% / eyeball 26.9% / datacenter 7.9% / cdn 1.4%. EVL fix
    cycle: live as2org is camelCase `organizationId`; fixtures had invented snake_case, masking
    a 100%-skip bug — fixtures regenerated from real records.
    **Phase 3 (evidence graph v2): EXECUTED + EVL green + DEPLOYED TO PROD 07-08-26.** Scope was
    user-redefined from "domain mapping" to multi-source evidence graph: WS1 schema
    (`relationship_type`/`valid_from`/`valid_to`, asn nullable, union-aware swap, shared
    `IP_ORG_WRITE_LOCK_KEY`), WS2 RIR delegated-extended ingest
    (`services/ip_org_rir_ingest.py`, 262,238 allocations, 0% skip), WS3 RPKI ROAs
    (`rpki_roas` table, `services/rpki_ingest.py`+`rpki_validate.py`, 755,538 IPv4 ROAs,
    BigInteger asn — 4-byte ASN overflow found+fixed by live gate), WS4 fusion-only
    (`services/ip_org_fusion.py`, D12 classification table, confidence clamp 0.05–0.65,
    lookup v2 `org_kind='org'`, corpus-EXISTS TTL cache). **Domain leg SPLIT OUT** per accepted
    Decision 2 Option B — G18–G20 + `resolve_org_domain` NOT built; its own future phase gated on
    a G19 yield measurement. PVL: 5 validate + 4 supplement cycles, 37/37 gaps, converged
    CONDITIONAL accepted (A1–A8 + Option B); decisions D10–D14 locked. EVL: 18/18 in-scope gates
    by independent tester; latency warm median 2.97ms p95 9.64ms (budget 15ms, tail 14.85ms thin);
    anti-fabrication 8/8 None non-vacuous. Local dev DB: 967,261 CAIDA + 262,238 RIR rows in
    `ip_org_prefixes`, 755,538 `rpki_roas`. Commits `51b12e1`+`808ae19`+`ce3a4e5` merged
    fast-forward to `main` and PUSHED; Railway deployed from `ce3a4e5` — **prod alembic head is
    now `c4a8f13e07b6`**, `ip_org_prefixes`+`rpki_roas` exist on prod but are EMPTY (ingest not
    run), all evidence columns confirmed, `/health` 200, all 4 ip-org flags OFF (zero runtime
    behavior change). 2 contract defects recorded in the plan's `### Contract Errata (post-EVL)`
    (G3's nonexistent `test_ip_org_domain_map.py`; G8/G10 flag-off vacuity precondition).
    Remaining = 3 operator steps (prod ingest `--apply --allow-remote`, flag flips, source-mix
    monitoring): `active/ip-org-database_07-08-26/ip-org-prod-enable_RUNBOOK_07-08-26.md`.
    **Local dev enable (10-08-26):** 6 flags flipped in `.env`, CAIDA/RIR/RPKI/APNIC ingested on
    `localhost:5433`, probe PASS — step-by-step in `docs/ip-org-local-enable.md` +
    `active/ip-org-database_07-08-26/LOCAL_ENABLE_NOTES_vi.md`.
    Known-gaps + follow-ups: `backlog/ip-org-followups_NOTE_07-08-26.md` (extended 07-08-26:
    post-swap ANALYZE, G8 tail margin, eyeball token gaps); new source idea:
    `backlog/rb2b-ip-to-company-eyeball-source_NOTE_07-08-26.md`.
  - `identity-vocab-reconcile_07-08-26` — **EXECUTED and user-accepted, unpushed.** Reconciles
    `devjulley` onto `main`'s `identified`/`candidate` vocabulary; PVL closed `HALTED_ACCEPTED` at
    supplement cycle 9 of 10 (`Gate: CONDITIONAL`, accepted). `devjulley` is rebased onto `main` at
    `5293cbc`, working tree clean, but nothing is pushed to `origin/devjulley` (ahead 32, behind 5).
    Kept in `active/` — see the "Migration head status" note above for the still-pending
    Alembic re-chain this plan carries. Known-gap:
    `process/features/visitors-identity/backlog/resolver-privacy-relay-callsite-coverage_NOTE_07-08-26.md`.
  - `privacy-hold-clear_09-08-26` — **EXECUTED + EVL PASS + archived 10-08-26 (WITH_GAPS).**
    Option D: site-owner explicit Clear for sticky `do_not_resolve`. See
    `completed/privacy-hold-clear_09-08-26/` and §Privacy-Hold Clear below. Open residuals:
    `backlog/privacy-hold-clear-e2e-auth-harness_NOTE_09-08-26.md` (Clerk e2e AC-1/2/3/6),
    `backlog/privacy-copy-counsel-review_NOTE_07-08-26.md` (AC-13 counsel).
  - `roster-precision_07-08-26` — **SPLIT after PVL cycle 4; Part A SHIPPED + EVL-green,
    UNCOMMITTED.** Makes the Hunter/Apollo company-level pick *informed* instead of arbitrary
    (Hunter already returns and bills for 5 employees; `hunter.py:56` keeps `emails[0]` and discards
    4). **Part A** = `apps/api/services/roster_ranking.py` (392 lines, **zero imports**,
    AST-enforced pure deterministic scorer: page→role affinity, geo affinity, weighted score with
    a drop-from-both-numerator-and-denominator degradation rule, deterministic tie-break) +
    `tests/unit/test_roster_ranking.py` (44 tests). **Zero existing files modified.** Gates
    confirmed by three independent tester runs: unit **1324 passed / 2 skipped / 0 failed**,
    integration **537 passed** unchanged, `identity_classification.py` diff empty. The scorer is
    **not called by anything yet** — it is dead code until Part B lands.
  - `roster-precision-wiring_07-08-26` — **Part B, PLANNED, never validated.** The resolver wiring
    Part A does not include: roster retention, exclusion + suppression + the mandatory site-wide
    `email_bidx` merge-collision guard, redaction of all candidates, `IdentifiedVisitor.roster_selection`
    JSONB + migration, the `roster_excluded` ledger outcome, merge-preserving upsert, and the
    detail-endpoint surface. Inherits all four PVL cycles of findings (F-H1 predicate mismatch,
    F-H2-rev ledger taxonomy, F-H3 parse-vs-storage allow-lists, F3 hash-live-on-both-sides, F6
    merge-preserving upsert, the seven-site `identity_status` census, exact integration fixture
    shapes) rather than re-deriving them. **Needs its own PVL loop from V1** with a parallel
    adversarial verifier — that second leg found the top defect in all four prior cycles and
    overturned an orchestrator decision twice. `roster_precision_enabled` default OFF; nothing
    becomes emailable (`is_emailable_identity("hunter")` stays `False`, regression-gated).
- `onboarding-canary` — conversational onboarding rebuild in React + a canarytokens-style
  location reveal (Leaflet pin on the user's city, their network, and the pages they just read on
  getbeam.fyi). 4-phase plan; **Phase 1 (backend, flag OFF) EXECUTED 10-08-26.** Widened
  `services/geoip.py` (`resolve_geoip_full` + `GeoResult`; `resolve_geoip` is now a thin wrapper
  with a frozen 2-tuple signature so `routers/events.py` needed zero edits; NEW `geoip2:` JSON
  Redis prefix kept separate from the legacy pipe-joined `geoip:` key; added the missing
  `mock_external_apis` branch and 429/`X-Ttl` backoff), new
  `services/onboarding_canary.py` (journey query extracted from `demo_journey` and shared — the
  new path adds the `site_id == settings.beam_self_site_id` predicate that `/demo/journey` still
  lacks; ISP-vs-company ladder; Null-Island guard), new authed `routers/onboarding.py`
  (`POST /api/v1/onboarding/canary` 30/min + `/identity-feedback`; flag-off => 404; IP never in
  the response body), config `beam_self_site_id` + `location_reveal_enabled` (default OFF),
  migration `a1c7f4e082d5` (`idx_visitors_fingerprint` + `identity_feedback` table) —
  live up/down/up round-tripped on a disposable DB. Phases 2-4 (React chat shell, Leaflet canary,
  follow-ups) not started. Plan:
  `process/features/onboarding-canary/active/canary-onboarding_10-08-26/canary-onboarding_PLAN_10-08-26.md`
- `campaigns-outreach` — AI segmentation, campaign planning, email + social outreach, drafts
- `billing` — Gumroad MoR billing, plans/quotas, BYOK keys
- `marketing-site` — public site: landing, blog, changelog, SEO (content sources in `marketing/`)
- `pixel` — tracking pixel, event ingest, consent, bot filtering; ingest-abuse-hardening
  (rotating-IP-flood defense: body-size cap, trusted-proxy IP resolution, per-site ceiling,
  write-time velocity flag, operator observability) shipped 25-07-26, archived 26-07-26 with 2
  known-gaps — see Ingest Abuse Hardening section below. cadence-bot-flag v1 (behavioral,
  non-UA stealth-crawler detection: cadence-variance + engagement-mix conjunction, batch
  APScheduler sweep, visibility-only `is_bot_suspect` flag on Visitor/IdentifiedVisitor, default
  OFF) EXECUTE+EVL-green 26-07-26, plan stays active pending 4 known-gaps (migration live
  round-trip, AC-14 live-crawler validation, AC-8/AC-9 Agent-Probe manual render check,
  Playwright auth-harness leg) — see
  `process/features/pixel/backlog/cadence-bot-flag-deferred-gates_NOTE_26-07-26.md`
- `evallayer` — AI-agent traffic detection (agent_classifier, `/agents` API + dashboard tab, IP/rDNS
  verification, agent→company outreach-safe resolution, GEO/AEO analytics, outreach-exclusion
  guardrail); 8-phase program, code-complete 23-07-26, pending Docker-gate closure — see
  `process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md`.
  `GET /agents/{site_id}/stats` now returns additive `detection_enabled: bool`
  (`settings.agent_detection_enabled`), and the `/dashboard/agents` empty state branches on it
  (flag-off vs no-visits-yet copy) — shipped 04-08-26, PVL/EVL green, archived to
  `process/features/evallayer/completed/agents-flag-empty-state_04-08-26/`.
  **Beam Lab (31-07→01-08, reconciled 07-08-26):** soft-serve gate + edge `_bfm` marker live on
  `beamlab.nhantown.com`; resume at `docs/beam-lab-resume.md`. Plans archived to
  `process/features/evallayer/completed/agent-gate-soft-serve_31-07-26/` (status
  `shipped-with-known-gaps`) and `.../completed/agent-gate-lab_31-07-26/` (status `superseded` —
  the hard-403 predecessor, empirically rejected by real ChatGPT-User traffic). Open items tracked
  in `process/features/evallayer/backlog/beam-lab-soft-serve-known-gaps_NOTE_07-08-26.md`. Live
  deployment code was not independently re-verified against the repo in this reconciliation pass.
- `agent-gateway` — agent-readable site surface + agent-driven lead capture. Phase 1 (`AgentProfile`
  per-site data model, authed CRUD, dashboard editor) and Phase 2 (public
  `manifest.json`/`offers.json`/`llms.txt` + hand-written read-only JSON-RPC MCP server exposing
  `get_offers`/`get_pricing`/`check_availability`) are CODE DONE + EVL-green, mounted in
  `apps/api/main.py`; `agent_gateway_enabled` default OFF. **Phase 3/4 of this plan's own
  consent-link design are SUPERSEDED (07-08-26, user decision) — never implemented.** The chosen
  design is zero-click `AgentLead` (structurally isolated from `IdentifiedVisitor`/`Visitor`, no
  human consent click, accepted tradeoff: lead quality depends on agent truthfulness), built on
  unmerged branch `feat/ws3-agent-concierge` — not yet reconciled with sibling branch
  `feat/ws2-agent-session-classifier` or merged to `devjulley`/`main`. See
  `process/features/agent-gateway/active/agent-gateway_26-07-26/agent-gateway_PLAN_26-07-26.md`
  §Decision Record and §WS3 Merge Preconditions.
- `ads-audiences` — OAuth-linked ad channels (Meta Custom Audiences, Google Data Manager API,
  LinkedIn deferred/CSV-only) with direct segment-audience push mirroring the CRM connector
  pattern; 3-phase program. Phase 1 Foundation (models, `services/ads/` registry, router, mock-mode
  parity, UI panel) shipped 25-07-26 — mock-mode complete, `ad_audiences_enabled` default OFF, 2
  env-only known-gaps (migration round-trip Docker-gated, Playwright auth harness). Phase 2 (Meta
  live — real OAuth, Custom Audience create/upload, ToS-precondition error surfacing, min-size
  warning) code-complete + EVL-green 26-07-26 (14 gates, no regression); 3 env-only known-gaps
  before `✅ VERIFIED`/production-enable: Meta sandbox Hybrid smoke (mandatory pre-enable operator
  step), AC7 Playwright UI legs (blocked on the same Clerk auth-harness gap as Phase 1), AC13 exact
  error code/subcode (Agent-Probe residual, fails safe). Phase 3 (Google live — real OAuth with
  offline-consent refresh flow, two-API audience create/upload via Google Ads API
  `userLists:mutate` + Data Manager `audienceMembers:ingest`, EEA fail-closed exclusion)
  code-complete + EVL-green 26-07-26 (commit `e3adae3`, G1–G7 all PASS, no regression) — 🧪
  TESTING pending the operator sandbox gate: G2/E4 Hybrid Google sandbox smoke (needs Google Cloud
  OAuth test app + Google Ads test account + real developer_token) before `✅ VERIFIED`. Program is
  at the operator-gate boundary — 1 of 3 phases VERIFIED, no open agent-side work; remaining path
  is operator-side sandbox smokes + live migration apply before any `ad_audiences_enabled` flip.
  Known-gaps + procedures:
  `process/features/ads-audiences/backlog/phase-1-docker-and-auth-known-gaps_NOTE_25-07-26.md`; see
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
- **Supabase (prod Postgres, pinned 09-08-26):** project **`retarget-agent`**, ref/id **`hylcleqxlkdblibpdhhm`**, region `ap-southeast-1`, API `https://hylcleqxlkdblibpdhhm.supabase.co`, host `db.hylcleqxlkdblibpdhhm.supabase.co`. MCP `project_id` MUST be this ref. Local Docker PG remains `localhost:5433` for non-prod. IDE connect steps: `docs/supabase-retarget-agent.md`.
- **Cloudflare Worker (agent fetch beacon, pinned 09-08-26):** live script name **`beam-agent-beacon-splittrip`** (id `9e74d04215224c4ab2cecc3e65939d21`), source `infra/cloudflare/agent-beacon-worker/`, wrangler env `splittrip`, route `splittrip.nhantown.com/*`. Use this name for MCP Workers get/list/builds and for `wrangler deploy --env splittrip`. Do not target `quota-tracker`. Details: `infra/cloudflare/agent-beacon-worker/README.md`.

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

- **Edge beacon Worker (customer-site path):** Cloudflare Worker **`beam-agent-beacon-splittrip`** —
  source `infra/cloudflare/agent-beacon-worker/` (`wrangler.toml` base name `beam-agent-beacon` +
  `--env splittrip`). This is the account script to get/build/push for fetch-beacon data on
  `splittrip.nhantown.com`. Separate from Beam Lab Pages (`infra/cloudflare/beam-lab/`).
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
- **Migration head status, consolidated 07-08-26 (last reconciled at ip-org Phase 3 closeout —
  supersedes the identity-vocab-reconcile consolidation and its two-branch framing).**
  `main`, `devjulley`, and **prod** are now ALL on one unified chain with head **`c4a8f13e07b6`**
  (`add_ip_org_evidence_graph`), and prod has it applied live (Railway deploy 2026-08-07, see
  Live-apply status below). Always re-derive with `alembic -c apps/api/alembic.ini heads` per
  branch rather than trusting any hash recorded here — heads move as concurrent programs land
  migrations. Historical per-branch detail (kept for chain archaeology):
  - **`main` head: `c2f7a9d31b64`** (`add_resolution_deferral_watermark`), 56 revisions from the
    `cd811a8b1f32` baseline, single head, no branching (re-verified live 07-08-26 by walking every
    `revision`/`down_revision` header on disk). The pending-live-apply chain starting from the old
    `e6b2d4a1c837` (`add_cadence_bot_flag`) marker continues: `e6b2d4a1c837` → `a4f7c2e9d31b`
    (agent_profiles) → `b1e7f3c9d425` (sites.last_daily_digest_sent_at) → `f3a7c9e21b48`
    (outlier/internal damping) → `a2f8d61c9e37` (request_logs) → `c1e7a94f3d28`
    (agent_fetch_events.dedup_key) → `f3c8b2e91d47` (agent_fetch_events.link_marker) →
    `a7d419e6c052` (events.link_marker) → `b4c9a71e35d8` (sites.leadpipe_pixel_id) →
    `c2f7a9d31b64` (**main head**). Do not quote a "12 migrations pending" or "13 migrations"
    count — derive the pending list from `alembic history` at apply time; it changes as concurrent
    programs land migrations (see migration-collision memory note).
  - **`devjulley` head: `a3e8d5c71f02`** (`add_ip_org_prefixes`), 68 revisions, single head, no
    branching (re-derived live 07-08-26 via `alembic -c apps/api/alembic.ini heads` +
    down_revision walk after the ip-org-database closeout; supersedes the earlier
    `f1a7c3e05b92` head recorded in this note). The tail past the fp3 marker is:
    `f1a7c3e05b92` → `a4f2b8c15d70` (add_job_change_events) → `b8e3f6a2c904`
    (add_events_agent_sig) → `c9f4a7b31e85` (add_ws2_agent_operated_flag) → `d1a6c4e93f27`
    (add_erasure_requests) → `e7b3d5f19c46` (add_identity_coop_tables) → `f2c81a6b4d09`
    (add_site_contribution_enabled) → `a3e8d5c71f02` (add_ip_org_prefixes). `a3e8d5c71f02`
    chains off identity-coop's `f2c81a6b4d09` — both landed in the same commit batch
    (`d78b4f1` + `3215fb0`), so the "don't chain off uncommitted coop migrations" constraint
    was satisfied at commit time. **Superseded 07-08-26 (ip-org Phase 3):** the head has since
    moved past `a3e8d5c71f02` through `b6f4a2d90c13` to **`c4a8f13e07b6`**
    (`add_ip_org_evidence_graph`), which chained off the then-live head `b6f4a2d90c13` — NOT
    off `a3e8d5c71f02` directly, because the head had moved between plan-write and EXECUTE
    (E1 deviation, recorded in the Phase 3 plan). Derive the intermediate revisions from
    `alembic history` — do not trust a written-down chain tail here.
  - **Re-chain: APPLIED on disk (07-08-26).** The ONE-EDIT re-chain described by
    identity-vocab-reconcile (`b1c9e7f24d83.down_revision` retargeted to `main`'s head
    `c2f7a9d31b64`) is now live on `devjulley` — verified 07-08-26 by walking the on-disk
    headers: the chain runs unbroken `c2f7a9d31b64` → `b1c9e7f24d83` → … → `a3e8d5c71f02`,
    one head, every revision reachable. Earlier text here calling it "a plan artifact, not yet
    executed" is superseded.
  - **Live-apply status.** Forward apply of every `main`-side migration from an EMPTY database
    through `c2f7a9d31b64` was proven on a disposable `postgres:16-alpine` on 06-08-26; only
    `c2f7a9d31b64` itself has down→up round-trip evidence, earlier revisions do not. `devjulley`'s
    tail (`c7d3b8e1f624` onward through `f1a7c3e05b92`) was offline `--sql`-validated only at the
    time this paragraph was written — NOT live-round-tripped, then attributed to "Docker unavailable
    in every session that has touched this chain". **That attribution was FALSE** (see the Docker
    CLI note below); the two 07-08-26 updates that follow close it with real live round-trips. Note: an
    unscoped `alembic upgrade head --sql` fails mid-chain because `b7d3e9f1a4c2_add_ad_connections.py`
    calls `sa.inspect(bind)` (unsupported against alembic's offline `MockConnection`) — use an
    explicit `<from>:<to>` range instead; see `process/context/tests/all-tests.md` for the gotcha.
    **Update 07-08-26 (Docker gate run):** full-chain live round-trip from an EMPTY disposable
    `postgres:16-alpine` proven — all 64 revisions applied to head `d1a6c4e93f27`, then 17
    revisions downgraded to `e6b2d4a1c837` and re-upgraded clean. This closes the
    migration-round-trip known-gap items across ingest-abuse-hardening, cadence-bot-flag,
    site-id-lifecycle, job-change-detection, graph-erasure (KG-5), and identity-coop
    clearing condition 2.
    **Update 07-08-26 (ip-org closeout):** full chain live-applied again from an EMPTY local
    dev DB (`localhost:5433`) all the way to the new head `a3e8d5c71f02` in 8s, plus live
    down/up round-trip `a3e8d5c71f02`↔`f2c81a6b4d09` (GiST `inet_ops` restored clean).
  - **PRODUCTION LIVE-APPLY: DONE through `c4a8f13e07b6` (2026-08-07).** The earlier "none of
    this is a production live-apply" statement is superseded: the user merged
    `51b12e1`+`808ae19`+`ce3a4e5` fast-forward to `main` and pushed; Railway auto-deploy from
    `ce3a4e5` booted and applied exactly `b6f4a2d90c13 → c4a8f13e07b6` clean — prod was ALREADY
    at `b6f4a2d90c13`, meaning the earlier chain (including the re-chained devjulley tail) had
    reached prod in prior deploys. Prod alembic head is now `c4a8f13e07b6`; `ip_org_prefixes` +
    `rpki_roas` exist on prod but are EMPTY (ingest is a separate operator step); `/health` +
    `/health/ready` 200. **Schema-applied ≠ feature-enabled:** every gated flag
    (`agent_detection_enabled`, `company_graph_enabled`, `identity_signals_enabled`,
    `site_ingest_limit_enabled`, `ingest_velocity_enabled`, `cadence_bot_flag_enabled`,
    `candidate_outreach_enabled`, `ip_org_lookup_enabled` + the 3 Phase-3 ip-org flags) remains
    OFF in prod — flipping any of them is still a separate explicit operator action. For the
    ip-org set, follow
    `process/features/visitors-identity/active/ip-org-database_07-08-26/ip-org-prod-enable_RUNBOOK_07-08-26.md`.
    Before flipping any OTHER flag, verify its required revisions are ≤ `c4a8f13e07b6` in
    `alembic history` (they are, as of this writing) and re-check the prod head first.
- Docker/live-integration known-gaps consolidated in
  `process/features/evallayer/backlog/program-docker-verification-gaps_NOTE_23-07-26.md`
  — **but re-check their premise first: Docker IS available on this machine.** The CLI is simply off
  `PATH` (`/Applications/Docker.app/Contents/Resources/bin/docker`), so `which docker` returns
  nothing and agents have repeatedly concluded the runtime was absent. Detect via
  `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'` instead. Every gate deferred as
  "environment-blocked" / `needs-container` across `process/features/*/backlog/*deferred-gates*` and
  `*docker-verification*` rests on a false premise and is re-classifiable as RUNNABLE. Full gotcha:
  `process/context/tests/all-tests.md` §Debugging Quick Reference.

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

## Privacy-Hold Clear (Option D, shipped 09-08-26 — archived 10-08-26 WITH_GAPS)

Gives site owners a deliberate, audited way out of sticky GPC/DNT `do_not_resolve` without
loosening aggregator stickiness, suppression, or Identify gates:

- **API:** `POST /api/v1/visitors/{site_id}/{visitor_id}/clear-privacy-hold` in
  `apps/api/routers/visitors.py` — same site gate as `/resolve` / `set_internal_override`
  (`get_current_user` + `_verify_site_access` + `human_only_visitor_filter`); writes ONLY
  `Visitor.do_not_resolve = False`; returns `{visitor_id, do_not_resolve: false, cleared}`;
  audits `privacy_hold_cleared` (site_id, visitor_id[:8], user_id, was_held — no PII).
  Idempotent on non-held rows (`cleared: false`). Does **not** remove suppression-list entries
  and does **not** auto-Identify.
- **Schema:** `VisitorOut.do_not_resolve: bool = False` in `apps/api/schemas/visitors.py`
  (additive; `VisitorDetailOut` inherits). Web list type: `do_not_resolve?: boolean` on
  `Visitor` in `apps/web/src/lib/api-types.ts`; client method `api.clearPrivacyHold` in
  `apps/web/src/lib/api.ts`.
- **UI:** Visitors dashboard (`apps/web/src/app/dashboard/visitors/page.tsx`) — anonymous +
  `do_not_resolve` rows show a distinct "Privacy hold" state (policy block, not a usage limit)
  and a confirm dialog before Clear (deliberate / this-site-only / does-NOT-unsuppress).
- **Untouched by design:** sticky aggregator (`BOOL_OR`/`OR`), suppression list, `/resolve`
  short-circuit, pixel (`apps/pixel/src/tracker.js`).
- **Tests:** `tests/integration/test_privacy_hold_clear.py` (8 Fully-Automated). Hybrid e2e
  legs live in `apps/web/e2e/visitors.spec.ts` but stay CONDITIONAL (`E2E_PRIVACY_HOLD_VISITOR`
  skip-guard) until Clerk Playwright auth-harness lands.
- **Archive:** `process/features/visitors-identity/completed/privacy-hold-clear_09-08-26/`.

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

## Browser Fingerprint v3 (fp3 — fonts + audio, shipped 07-08-26)

Adds the two signals the v2 hash was missing, without disturbing v2:

- **Installed-font probe** (`fontFp` in `apps/pixel/src/tracker.js`) — renders a fixed string at
  72px per candidate font against the `monospace`/`sans-serif`/`serif` fallbacks; a metrics
  difference means the font resolved. 25 candidates → hit bitmask in base36. Needs
  `document.body`, so it runs behind the new `whenBody()` helper — a head-placed and a
  body-placed snippet must produce the same value.
- **Audio-stack probe** (`audioFp`) — fixed triangle oscillator through a `DynamicsCompressor`
  rendered in an `OfflineAudioContext`, summing the tail. `sampleRate` is pinned to 44100 so the
  value does not move with the machine's audio config. Async (hence a callback), 1s timeout, and
  every failure path yields `""` — unsupported/blocked is itself a stable per-browser constant.
- **`fp2_` is unchanged and still emitted on every event.** `fp3_` = `hash128(fp2 base | fonts |
  audio)` and rides along as a second field (`_fp3`). This is the whole point of the design:
  overwriting `fingerprint` with a new hash would make every already-known visitor look new,
  missing `fingerprint_match` AND the cross-tenant `beam_identity_graph`, and re-paying providers
  to re-identify people Beam already owns.
- **Storage is additive** — new nullable `visitors.fingerprint_v3` and
  `beam_identity_graph.fingerprint_v3` columns (+ indexes), migration `f1a7c3e05b92`. The graph's
  unique key stays `(fingerprint, email)`; fp3 is only an extra lookup path on the same row, and
  the upsert `coalesce`s so a NULL fp3 never blanks a stored one. Both visitor columns are
  write-once: fp3 resolves asynchronously on the client, so it routinely arrives on a LATER batch
  than fp2 (`_process_signal_events` scans for both independently).
- **Resolver prefers v3, falls back to v2** — `identity_resolver.py` Check 2 and
  `_check_beam_identity_network` both try the v3 column first (confidence 0.80, above v2's 0.75,
  still below the 0.90 deterministic svid path), then the v2 column for rows written before fp3
  existed and for older pixel builds. The P4 ingest-velocity diversity check deliberately still
  keys on fp2 — that signal is present on 100% of events, so abuse detection is unchanged.
- **Pixel size budget raised 5KB → 6KB gzipped** (`tracker.min.js` 4843B → 5692B). Enforced in
  `tests/unit/test_pixel_fingerprint.py` (`< 6000`) and `tests/unit/test_pixel.py` (`< 6144`).
- Browser-only behavior is covered by `apps/pixel/e2e/fingerprint-v3.spec.ts` (fp2-always,
  fp3-eventually, fp3 stable across reloads, no stray probe span) — green on chromium/webkit/firefox.
- **Still missing from Layer 2**: extension enumeration, and CPU clock skew (not reachable from
  JS at all — it needs TCP-stack timing at the edge, not the pixel).

**Alembic head note:** `f1a7c3e05b92` (`add_fingerprint_v3`) was the `devjulley` head when fp3
shipped; the head has since moved through `a3e8d5c71f02` to `c4a8f13e07b6`
(`add_ip_org_evidence_graph`, applied live on prod 2026-08-07) — see the consolidated
"Migration head status" note in the AI-Agent-Traffic Layer section above for the unified chain
and prod live-apply status. Always re-run `alembic heads` before chaining or applying;
concurrent programs move it repeatedly.

## Key Patterns and Conventions

**Python:** type hints on all functions; async for all I/O; `structlog` only (never `print()`); `httpx` async for external calls (never `requests`); every external call has timeout + retry/backoff + error handling; never swallow exceptions; Pydantic models for every API schema; config via `pydantic-settings` env only — no hardcoded secrets.

**TypeScript:** strict mode, no `any`; server components by default; API calls via shared client `apps/web/src/lib/api.ts` (POSTs get no client timeout — long AI calls are safe); TanStack Query for fetching; react-hook-form + zod for forms.

**Database:** tables snake_case plural; FK `{table_singular}_id`; every table has `id` (UUID), `created_at`, `updated_at`; Alembic for migrations.

**Mock mode:** every external API (providers, Gemini loop, SendGrid, CRM) must work with `MOCK_EXTERNAL_APIS=true` returning deterministic fakes — dev/tests/demo run keyless. Mock short-circuits live at the service layer (not in transport clients); `gemini_agent_loop` is the exception (mock branch inside, executes real handlers).

**Multi-tenancy:** every user-facing query filters through `Site.user_id == user.id`; unknown/foreign ids return 404 or "not found" data (never 403 — don't leak id existence).

## Business Guardrails (agents MUST respect)

1. **Email/outreach safety:** never auto-send; campaigns flow draft → approved → active with a human approval gate; unsubscribe link in every email; `do_not_email` after hard bounce; suppression list enforced; max 50 emails/hour/site.
2. **Quota/credit burn:** Gemini runs on free tier (RPM caps; `thinkingBudget: 0` on JSON calls — thinking adds 60-100s latency); identity resolution budget default 50/day/site, deep research 3/day; never retry failed identity resolution within 30 days; cache identity 30d / enrichment 7d in Redis; new external calls must have a mock path.
3. **PII/GDPR:** never log PII or prompt bodies (structlog events log keys/ids only); PII blind index + encryption keys required in prod (`validate_production`); raw events auto-purge at 90 days; GPC/DNT → `do_not_resolve` sticky; site owners may **explicitly** clear a hold via `POST /api/v1/visitors/{site_id}/{visitor_id}/clear-privacy-hold` (does not un-suppress, does not bypass Identify — still goes through `/resolve`); visitor data in prompts is hostile input (see AI Layer).
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
- Feature flags: `ENABLE_OSINT_SCAN`, `ENABLE_CONTENT_READER`, `CHANGELOG_SYNC_ENABLED`, `OUTCOMES_DIGEST_ENABLED`, `REFERRALS_ENABLED`, `CRM_*`, `CADENCE_BOT_FLAG_*`, `IP_ORG_LOOKUP_ENABLED` + `IP_ORG_DATASET_*_URL`/`IP_ORG_REFRESH_INTERVAL_HOURS` (default OFF)

## Open Questions / Outstanding Work

- **✅ RESOLVED — the P0 `GET /visitors` 500 is FIXED (`c92cc62`, ancestor of `devjulley` HEAD).**
  Both halves closed and re-verified on disk 07-08-26: `confidence_score` now lives on the
  **`VisitorOut` base** (`schemas/visitors.py:41`, so `VisitorDetailOut` inherits it), and the
  `canon_rows` select in `routers/visitors.py` includes `IdentifiedVisitor.confidence_score`, so the
  canonical-alias branch no longer raises `AttributeError`. Historical record: found by the
  07-08-26 Docker gate run (10 integration failures) — see
  `process/features/visitors-identity/backlog/docker-gate-run-findings_NOTE_07-08-26.md`. The
  standing lesson survives the fix: **do not add fields to the wrong schema class** — new
  detail-only fields go on `VisitorDetailOut`, never on `VisitorOut`.
- **⚠️ SAFETY — bare `alembic upgrade` from repo root applies to Supabase PROD.** `.env`
  `DATABASE_URL` points at production (`aws-1-ap-southeast-1.pooler.supabase.com`, project
  **`retarget-agent`** / `hylcleqxlkdblibpdhhm` — see `docs/supabase-retarget-agent.md`) and
  `apps/api/migrations/env.py` has NO local-host guard — any unpinned alembic command (or DB
  script reading `.env`) hits prod. Discovered + refused at gate during the 07-08-26 ip-org
  live-apply session. Remedy: ALWAYS pin `DATABASE_URL` to `localhost:5433` (or the disposable
  container's DSN) in the command environment before any alembic/DB-script invocation.
  `scripts/refresh_ip_org.py` now has a fail-closed local-host guard (`--apply` refuses non-local
  DSN unless `--allow-remote`, unparseable = refuse; 15 unit tests) — **alembic itself remains
  unguarded**; adding an equivalent guard to `migrations/env.py` is an open follow-up
  (`process/features/visitors-identity/backlog/ip-org-followups_NOTE_07-08-26.md`). See also
  memory note `getbeam-env-points-to-supabase-prod`.
- **GDPR backfill exposure — RESOLVED 07-08-26.** The pii-at-rest re-validation found that
  `graph_erasure.py`'s erasure sweep matches on blind index, so pre-backfill NULL-bidx rows would
  be silently missed. Operator ran `apps.api.scripts.backfill_pii_ciphertext` against prod same
  day: 22/22 rows backfilled (visitor_emails 4, identified_visitors 12, enrichment_profiles 6),
  `beam_identity_graph` had **0** pending (graph writes always used the pii pattern), re-dry-run
  verified 0 remaining across all 4 tables. Erasure sweep now reaches every row. The pii-at-rest
  plan itself stays validated-and-held CONDITIONAL — still NOT executing until: Docker for Hybrid
  gates, high-risk evidence pack, PVL refresh closing the READ-census G1 gap (prereq (a) backfill
  is ✅ done).
- `CAMPAIGN_PLANNER_TOOLS_ENABLED=true` (planner tool loop) needs live-model validation before prod enable
- Real-key Gemini smoke for `/ai/ask` agentic path not yet run (no key on dev machine) — check `gemini_tool_call` in structlog when run
- Legacy `plan/` folder (11 dated pre-harness plans) is read-only history — migrate still-relevant items into `process/features/*/backlog/` opportunistically
- e2e coverage gaps: billing + exports (see `tests/all-tests.md` Known Gaps)
- Docs drift: `PRODUCT_ROADMAP.md` + `README.md` still say Claude/`claude-sonnet-4` for segmentation — code runs Gemini (see AI Layer)
- EvalLayer + AI-referral + owned-data-layer + first-party-capture + ingest-abuse-hardening +
  cadence-bot-flag + identity-vocab-reconcile (candidate_outreach_enabled): `agent_detection_enabled`,
  `company_graph_enabled`, `identity_signals_enabled`, `site_ingest_limit_enabled`,
  `ingest_velocity_enabled`, `cadence_bot_flag_enabled`, `candidate_outreach_enabled`,
  `ip_org_lookup_enabled` all default
  OFF. The migration chain is now unified across `main`/`devjulley`/prod with head
  `c4a8f13e07b6` applied LIVE on prod (2026-08-07) — schema-applied ≠ feature-enabled; every
  flag above remains OFF and flipping each is a separate operator action. See the consolidated
  "Migration head status" note in the AI-Agent-Traffic Layer section above for the unified
  chain and prod live-apply detail — see
  `process/features/evallayer/backlog/program-docker-verification-gaps_NOTE_23-07-26.md`,
  `process/features/visitors-identity/backlog/owned-data-layer-docker-verification_NOTE_23-07-26.md`
  (RESOLVED), `process/features/visitors-identity/backlog/first-party-capture-deferred-gates_NOTE_24-07-26.md`
  (RESOLVED), `process/features/visitors-identity/backlog/post-docker-gate-followups_NOTE_24-07-26.md`
  (**SUPERSEDED 07-08-26 — the "478 passed / 23 failed / 17 errors" figure that note records is
  STALE.** The integration lane is now **537 passed / 0 failed / 0 errors**, measured twice
  independently on 07-08-26 (roster-precision PVL cycle 4 and the EVL confirmation run). Commits
  `81eb4e6` (repaired never-executed fixtures) and `c92cc62` (the `GET /visitors` P0) closed that
  failure set. Unit lane baseline for the same tree: **1280 passed / 2 skipped / 0 failed**, or
  **1324** with roster-precision Part A's 44 new tests present. conftest Redis-isolation hardening
  confirmed-twice),
  `process/features/pixel/backlog/ingest-abuse-hardening-deferred-gates_NOTE_25-07-26.md` (open:
  AC-4a mutation-kill re-verification; migration round-trip RESOLVED 07-08-26),
  `process/features/pixel/backlog/cadence-bot-flag-deferred-gates_NOTE_26-07-26.md` (open:
  AC-14 live-crawler validation; AC-8/AC-9 Agent-Probe manual render check; Playwright
  auth-harness leg; migration round-trip RESOLVED 07-08-26), and
  `process/features/visitors-identity/backlog/docker-gate-run-findings_NOTE_07-08-26.md`
  (07-08-26 run: P0 `GET /visitors` 500 in prod, graph-erasure/job-change test-fixture bugs,
  vocab-drift test, 7 untriaged failures, Redis-shadowing hazard round 2)
- "Handoff Detection" (human-behind-the-agent correlation) is **built, not planned** — this entry
  previously said "not yet scaffolded on disk", which was stale. Shipped on disk with tests:
  `agent_handoff_correlation.py` (fetch↔click sweep), `agent_fetch_beacon.py` (edge beacon),
  `agent_intent_signals.py` (H3 commercial-intent), `agent_gateway.py` + `agent_mcp.py` +
  `agent_profile.py` (agent-facing gateway), models `agent_fetch_event` / `agent_handoff_link` /
  `agent_profile`. Architecture assessment, open gaps, and what is deliberately NOT solved:
  `docs/agent-detection-architecture.md` (read this before touching the agents surface).
- Two correlation caveats worth knowing before reading any handoff number: the link is a
  probabilistic vendor+page+30-minute match with no identifying marker, and the agent-facing
  gateway records no visits of its own — so an AI calling the MCP server leaves no trace in the
  Agents tab. Both are open items in the doc above.

## Scan Metadata

- Generated: 21-07-26 (vc-setup STUDY phase, informed by full-repo audit + legacy CLAUDE.md migration)
- HEAD: 8880a91
- Mode: fresh setup (Flow A with legacy-content merge)
- Package manager: npm (`apps/web`), pip + `.venv` (Python, deps in root `requirements.txt`)
