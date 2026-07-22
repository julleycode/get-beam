---
name: plan:evallayer-spec
description: "Program-level product-discovery SPEC for EvalLayer — AI-agent traffic detection, dashboard surface, and outreach-safe company enrichment"
date: 22-07-26
feature: evallayer
---

# EvalLayer — Program SPEC

**Date:** 22-07-26
**Status:** Locked (governs all 8 phases — INNOVATE/PLAN may begin per phase)
**Feature:** evallayer (new)
**Governs:** phase-program inner loop (`R → I → P → PVL → E → EVL → UP` per phase, no per-phase SPEC)

**TL;DR:** Beam currently detects AI-agent traffic (ChatGPT, Claude, GPTBot, PerplexityBot, etc.) only to silently drop it before storage. EvalLayer keeps that traffic, classifies it by vendor and confidence, and gives the user two new things: (1) a separate "Agents" dashboard tab showing which AI agents visit their site and what they read, and (2) when an agent visit can be traced to a real company, that company (never the agent) is routed into Beam's existing human enrichment + email-outreach pipeline as a lead. Detection confidence is always tiered (UA-only / IP-verified / rDNS-verified) because none of it is fully trustworthy. Agents are never emailed — only human company contacts, through existing consent gates.

---

## Summary

Beam currently detects AI-agent traffic (ChatGPT, Claude, GPTBot, PerplexityBot, etc.) only to silently drop it before storage — treating an AI agent that browses or cites a user's site identically to a malicious bot. EvalLayer keeps that traffic, classifies it by vendor and confidence tier, and gives the user two new things: (1) a separate "Agents" dashboard tab showing which AI agents visit their site and what they read (a GEO/AEO insights capability), and (2) when an agent visit can be traced to a real company via IP, that company — never the agent — is routed into Beam's existing human enrichment + email-outreach pipeline as an ordinary lead. Detection confidence is always tiered (UA-only / IP-verified / rDNS-verified) because none of it is fully trustworthy, and agents are never emailed — only human company contacts, through Beam's existing consent and approval gates.

## Problem / Goal

Website owners using Beam today only see **human** visitor data — AI agents (ChatGPT browsing a page, Perplexity answering with a citation, GPTBot indexing content) are treated identically to malicious bots and thrown away at the front door. As AI agents increasingly browse and cite websites on users' behalf, site owners have no visibility into "which AI agents visit my site, what they read, and could this become a customer lead."

**Goal:** Give Beam users visibility into AI-agent traffic on their site (a GEO/AEO — Generative/Answer Engine Optimization — insights capability) without polluting existing human visitor data, and without ever compromising Beam's anti-bot, human-approves-outreach brand posture. When an agent visit can be traced to a real company, that company becomes an ordinary Beam lead through the existing human pipeline — the agent itself is never a contact.

---

## In-Scope

1. **Passive discoverability** (Phase 0) — making Beam's own site legible to AI agents/crawlers (structured data + plugin manifest). Already drafted; folded into this program as its outbound half.
2. **Detection** — server-side classification of AI-agent traffic at event ingest, tiered by verification method (UA-only / IP-range-verified / reverse-DNS-verified).
3. **Storage** — a dedicated, separate data surface for agent visits (not mixed into human Visitor/Event tables).
4. **Read surface** — a new `/agents`-style API and a new top-level "Agents" dashboard tab (list, detail, stats/widgets), modeled on the existing Visitors surface.
5. **GEO/AEO insights** — aggregated analytics: which vendors visit, what pages they read, trends over time.
6. **Company-resolution → outreach feed** — when an agent visit's IP resolves to a real company via the existing company-resolution logic, that company enters the existing human enrichment + email pipeline as a lead.
7. **Outreach-exclusion guardrail** — a hard, tested boundary ensuring agent-classified records themselves can never enter the campaign/email pipeline.
8. **Known-limitation disclosure** — documenting to the user (in-product or in docs) that agent detection is best-effort and tiered, not a certainty.

---

## Out-of-Scope

- **No published callable API surface for agents.** EvalLayer does not add an OpenAPI spec, MCP server, or any authenticated machine-callable endpoint for external agents to call into Beam. (Consistent with the already-locked discoverability decision: `ai-plugin.json` deliberately omits an `api` section.)
- **Agents are never auto-emailed or otherwise contacted.** No email, no social outreach, no message of any kind is ever sent to an "agent" record. Only a human company contact — resolved through the existing pipeline — can enter outreach, and only after existing consent/suppression/approval gates.
- **No new bot-blocking behavior.** Generic scrapers/bots that are not on the recognized AI-agent vendor list continue to be dropped exactly as today. EvalLayer does not loosen or change the existing bot-drop policy for anything outside the recognized vendor set.
- **No guaranteed detection of all AI agents.** Vendors that don't publish a recognizable UA token or IP range, and any agent using a headless browser with `navigator.webdriver` unset to evade the pixel's own block, will not be caught in v1. This is a documented, accepted limitation, not a bug.
- **No fix to the pixel's `navigator.webdriver` block in this program.** The client-side pixel gap (headless agent browsers never fire the JS tracker) is a known constraint, not a deliverable — server-side UA detection on `/ingest` is the only surface this program builds. A pixel-side fix is explicitly deferred to backlog.
- **No live-model / production vendor IP-range integration decisions locked here.** This SPEC fixes the requirement ("verify IP where a vendor publishes ranges"); which specific library, cron schedule, or storage format is PLAN-time work for Phase 4.
- **No changes to existing human visitor/email/billing/quota logic beyond what's needed to (a) reconcile filter ordering and (b) wire the new company-resolution feed.** Existing Visitor, Event, Campaign, Segment models and their current behavior for human traffic are not restructured.
- **Google-Extended and Applebot-Extended are never shown as "visits."** These are robots.txt opt-out-only tokens that never appear in live request User-Agents; EvalLayer surfaces them (if at all) as derived robots.txt policy info, not detected traffic.

---

## User Stories (grouped by phase / scope tier)

### Phase 0 — Discoverability (Foundation, independent)
- **As a** site owner, **I want** my site's structured data and plugin manifest to be legible to AI agents/crawlers, **so that** agents can accurately discover and represent my product's pricing and identity.
  *(Already fully specified in the existing `evallayer-discoverability` plan; folded in unchanged.)*

### Phase 1 — Data model + classifier (Foundation)
- **As a** site owner, **I want** Beam to recognize known AI-agent vendors (OpenAI, Anthropic, Perplexity, etc.) as a distinct category from generic bots, **so that** their visits aren't silently destroyed at the door.
- **As the** system, **I need** a place to store agent-visit records that is structurally separate from human Visitor/Event data, **so that** human visitor stats are never polluted by agent traffic.

### Phase 2 — Ingest wiring (Foundation)
- **As a** site owner, **I want** legitimate AI-agent traffic to survive existing datacenter/proxy-VPN IP filters, **so that** real vendor visits (which are often cloud-hosted) aren't accidentally re-dropped by unrelated anti-bot logic.
- **As the** system, **I need** agent classification to add negligible latency to the event-ingest hot path, **so that** real human visitor tracking performance is unaffected.

### Phase 3 — Read API + dashboard tab (Foundation → Expansion boundary)
- **As a** site owner, **I want** a dedicated "Agents" tab in my dashboard, **so that** I can see AI-agent traffic without it being mixed into or confused with my human visitor data.
- **As a** site owner, **I want** to see individual agent visits (vendor, page paths, timestamps) and basic stats, **so that** I understand what's happening at a glance.

### Phase 4 — Verification / confidence (Expansion)
- **As a** site owner, **I want** to know HOW confident Beam is that a visit really came from the claimed AI agent (not just a spoofed User-Agent), **so that** I can trust or discount the data appropriately.
- **As the** system, **I need** to check a visit's IP against a vendor's published IP-range list when available (OpenAI, Perplexity), and treat vendors without published ranges (Anthropic/Claude) as permanently UA-only confidence, **so that** confidence labeling is honest rather than inflated.

### Phase 5 — Company-resolution → outreach feed (Expansion)
- **As a** site owner, **I want** an agent visit that resolves to a real company (via IP) to automatically become a lead in my existing pipeline, **so that** I don't miss a business opportunity just because the first "visitor" was an AI agent on that company's behalf.
- **As the** system, **I need** the company (never the agent) to be the thing that enters outreach, **so that** Beam's anti-bot / human-approves-outreach brand promise is never violated.

*(Flag: the underlying enrichment-waterfall research for this phase's specific provider mechanics did not complete during RESEARCH — see "Known Research Gap" below. Re-research required before Phase 5 PLAN.)*

### Phase 6 — Aggregation + GEO/AEO analytics (Expansion)
- **As a** site owner, **I want** to see trends over time (which agent vendors are visiting more, what content they favor), **so that** I can optimize my content for AI-driven discovery (GEO/AEO), the same way I'd optimize for SEO.

### Phase 7 — Outreach-exclusion guardrail (Expansion — elevated priority)
- **As a** site owner, **I want** an unbreakable guarantee that no AI-agent record can ever itself receive an email or social message, **so that** Beam's core brand promise (never auto-contact non-humans, human always approves) is never at risk.
- **As the** system, **I need** a regression test proving this guardrail holds, **so that** future code changes can't silently reintroduce the risk.

*(Note: this phase is a safety guardrail, not a "nice-to-have" feature. Its priority is elevated above its phase number — see Constraints.)*

---

## What The User Wants (Behavioral Outcomes)

- When a recognized AI agent (e.g. GPTBot, ClaudeBot, PerplexityBot) visits a tracked site, the visit is **kept and classified**, not silently dropped as today.
- The site owner sees these visits in a **separate "Agents" area** of the dashboard — never mixed into their human "Visitors" list, counts, or charts.
- Each agent visit shown to the user carries a **visible confidence/verification label** (e.g. "UA only," "IP-verified," "rDNS-verified") — the product never implies more certainty than the underlying signal supports.
- Generic scrapers/unrecognized bots continue to be dropped exactly as before — nothing about this behavior changes.
- When an agent visit can be traced (via IP) to a real company, that company shows up as an ordinary **lead/company record** in Beam's existing human pipeline — with the same enrichment, drafting, and human-approval steps as any other lead. The **agent is never the contact** — the human at that company is.
- The site owner can see **aggregate trends**: which AI vendors visit most, which pages they read, and how that changes over time — positioned as a GEO/AEO insights feature (the "SEO dashboard" equivalent for AI discovery).
- At no point does any agent-classified record receive an email, social message, or any outbound contact — this is enforced and regression-tested, not just assumed.
- Robots.txt-only tokens (Google-Extended, Applebot-Extended) are never shown as "visits" in the Agents tab — if shown at all, they appear as separate "crawl policy" info derived from the site's own robots.txt.

---

## Flow / State Diagram

```
                         ┌─────────────────────────────┐
                         │   Incoming /events/ingest    │
                         │   request (pixel or server)  │
                         └──────────────┬───────────────┘
                                        │
                          ┌─────────────▼──────────────┐
                          │  Classify User-Agent         │
                          │  (recognized AI-agent vendor │
                          │   token? e.g. GPTBot,        │
                          │   ClaudeBot, PerplexityBot)  │
                          └──────┬───────────────┬───────┘
                                 │NO              │YES
                    ┌────────────▼────┐   ┌───────▼─────────────────┐
                    │ Existing bot/    │   │ Reconciled filter order: │
                    │ generic-scraper  │   │ agent-vendor allowlist   │
                    │ path — unchanged │   │ evaluated so legit vendor│
                    │ (silently drop)  │   │ cloud IPs are NOT re-    │
                    └──────────────────┘   │ dropped by datacenter/   │
                                           │ proxy-VPN filters        │
                                           └───────┬──────────────────┘
                                                   │
                                     ┌─────────────▼──────────────┐
                                     │ Persist Agent Visit          │
                                     │ (separate table, NOT mixed   │
                                     │  into Visitor/Event)         │
                                     │ confidence = "ua-only" (fast)│
                                     └─────────────┬─────────────────┘
                                                   │
                              (async, best-effort, off hot path)
                                                   │
                                     ┌─────────────▼──────────────┐
                                     │ Verification pass:           │
                                     │ - IP in vendor's published   │
                                     │   range (OpenAI/Perplexity)? │
                                     │   → confidence "ip-verified" │
                                     │ - else stays "ua-only"       │
                                     │   (e.g. all Anthropic/Claude) │
                                     └─────────────┬─────────────────┘
                                                   │
                     ┌─────────────────────────────┼─────────────────────────────┐
                     │                             │                             │
        ┌────────────▼───────────┐   ┌─────────────▼─────────────┐  ┌───────────▼────────────┐
        │ Dashboard "Agents" tab  │   │ Aggregation / GEO-AEO      │  │ Company resolution      │
        │ (list, detail, badges) │   │ analytics (vendor trends,  │  │ via IP (existing logic) │
        │ — human Visitors tab   │   │ page-read trends)          │  └───────────┬─────────────┘
        │   is UNTOUCHED          │   │                            │              │
        └─────────────────────────┘   └────────────────────────────┘   resolves to real company?
                                                                            │YES         │NO
                                                                  ┌─────────▼───┐   (no lead created,
                                                                  │ Company/lead │    visit stays
                                                                  │ enters       │    Agents-tab-only)
                                                                  │ EXISTING     │
                                                                  │ human        │
                                                                  │ enrichment + │
                                                                  │ email        │
                                                                  │ pipeline     │
                                                                  │ (consent/    │
                                                                  │  approval    │
                                                                  │  gates       │
                                                                  │  unchanged)  │
                                                                  └───────┬──────┘
                                                                          │
                                                              ┌───────────▼────────────┐
                                                              │ OUTREACH-EXCLUSION       │
                                                              │ GUARDRAIL (Phase 7):     │
                                                              │ agent record ITSELF can  │
                                                              │ never enter this path —  │
                                                              │ only the resolved COMPANY│
                                                              │ / human contact can.     │
                                                              │ Regression-tested.       │
                                                              └──────────────────────────┘
```

---

## Acceptance Criteria (Testable Outcomes)

Scenarios are drawn from the RESEARCH test-gap analysis (`process/context/tests/all-tests.md` router chain) and the program's own Test Gap Analysis; strategy tags follow the 3-tier convention (Fully-Automated / Hybrid / Agent-Probe). Detailed per-phase gate commands are PLAN-time work — these are the requirement-level outcomes each phase's plan must satisfy.

1. **A recognized AI-agent visit is kept, not dropped.**
   Given a request to `/events/ingest` with a UA matching a recognized AI-agent vendor token (e.g. `GPTBot`), the event is persisted as an agent visit rather than silently discarded with a 204.
   `proven by:` unit test on the classifier + integration test on `/ingest` with a mock GPTBot UA — asserts a row exists in the new agent-visit surface.
   `strategy:` Fully-Automated

2. **Human visitor data is never polluted by agent traffic.**
   Given the same recognized-agent request, no row is written to the existing `Visitor` or human-side `Event` aggregation tables, and human visitor counts/stats are unaffected.
   `proven by:` integration test asserting Visitor/Event counts are unchanged before/after an agent-only ingest batch.
   `strategy:` Fully-Automated

3. **Generic bots continue to be dropped exactly as today.**
   Given a UA matching a non-agent bot pattern (e.g. `Googlebot`, `curl/`), the request is dropped (204, no persistence) — unchanged from current behavior.
   `proven by:` existing `is_bot`/ingest regression tests continue passing unmodified.
   `strategy:` Fully-Automated

4. **Legit AI-agent vendor traffic is not re-dropped by datacenter/proxy-VPN filters.**
   Given a recognized-agent UA whose IP is also flagged as datacenter/cloud infrastructure, the visit is still classified and persisted as an agent visit (filter-ordering requirement).
   `proven by:` integration test with a mocked datacenter-flagged IP + recognized agent UA — asserts visit persists.
   `strategy:` Fully-Automated (with mocked IP-reputation lookup)

5. **Agent classification adds no material latency to the ingest hot path.**
   Given the classification step runs synchronously (UA match only) while verification (IP-range/rDNS) runs async/best-effort afterward, `/ingest` response time for agent traffic is comparable to human traffic.
   `proven by:` latency assertion/benchmark comparing ingest response time with and without agent classification enabled.
   `strategy:` Hybrid (automated timing assertion; manual review of baseline acceptability)

6. **The Agents dashboard tab shows agent visits, never human ones.**
   Given agent-visit data exists for a site, the new "Agents" tab lists/details them; the existing "Visitors" tab shows no agent-classified records.
   `proven by:` frontend integration/E2E test asserting tab separation and correct data source per tab.
   `strategy:` Fully-Automated (Playwright)

7. **Every agent visit surfaces a verification-method / confidence label.**
   Given any persisted agent visit, the dashboard displays its verification method (ua-only / ip-verified / rdns-verified) — never presented as unconditional certainty.
   `proven by:` component/E2E test asserting the confidence badge renders and matches the underlying verification method field.
   `strategy:` Fully-Automated

8. **OpenAI/Perplexity IP-range verification works when configured; Anthropic/Claude remains UA-only.**
   Given a mocked vendor IP-range dataset (`MOCK_EXTERNAL_APIS=true`), a matching IP upgrades confidence to "ip-verified"; a ClaudeBot-UA visit (no published range) never exceeds "ua-only" confidence regardless of IP.
   `proven by:` unit test on the verification service with deterministic mock fixtures for OpenAI/Perplexity ranges.
   `strategy:` Fully-Automated (mock path); live-provider verification is Agent-Probe / Known-Gap until a real fixture is available (see Constraints).

9. **An agent visit that resolves to a real company creates a normal lead, not an "agent contact."**
   Given an agent visit whose IP resolves via existing company-resolution logic to a real company, a company/lead record is created (or updated) in the existing human enrichment pipeline; no "agent" identity is ever the contactable entity.
   `proven by:` integration test asserting a Company/lead record is created downstream of a qualifying agent visit, and that its contact-eligible identity is a resolved human/company — not the agent visit record.
   `strategy:` Hybrid (mocked company-resolution provider path; the underlying enrichment-waterfall mechanics require re-research at Phase 5 PLAN time — see Constraints)

10. **Agent-classified records can never enter the campaign/email pipeline directly.**
    Given any agent-visit record (resolved to a company or not), no code path allows it to be selected as an email/social outreach target; only company/human contact records that pass through the existing consent/suppression/approval gates can be contacted.
    `proven by:` a first-class regression test explicitly asserting an agent-visit record ID is rejected/excluded if passed into the campaign targeting or send-eligibility logic.
    `strategy:` Fully-Automated — this is the highest-priority test in the entire program; must exist before Phase 7 is considered done.

11. **GEO/AEO aggregate analytics reflect only classified agent-visit data.**
    Given multiple agent visits across vendors and pages, the aggregation surfaces correct vendor-breakdown and page-read trend numbers.
    `proven by:` unit test on the aggregation logic with a fixed set of synthetic agent-visit rows, asserting correct grouped counts.
    `strategy:` Fully-Automated

12. **Discoverability surfaces remain valid and anti-bot-compliant (Phase 0, carried over unchanged).**
    The homepage JSON-LD `offers` array and `/.well-known/ai-plugin.json` manifest continue to meet the 4 acceptance criteria already locked in the existing discoverability plan (valid JSON-LD, valid manifest with `auth.type: none`, no `api`/`openapi` reference, prices in sync).
    `proven by:` the existing discoverability plan's Verification Evidence gates (JSON-LD parse assertion, grep constraint check, Hybrid GET check).
    `strategy:` Fully-Automated / Hybrid (as already specified in that plan)

13. **Google-Extended / Applebot-Extended never appear as detected "visits."**
    Given these tokens never appear as live request UAs, no code path attempts to classify or persist them as agent visits from ingest traffic; if surfaced at all, they appear only as robots.txt-derived policy info.
    `proven by:` unit test asserting the classifier's recognized-vendor list does not include these as live-traffic match tokens.
    `strategy:` Fully-Automated

14. **Mock mode covers every new external call.**
    Given `MOCK_EXTERNAL_APIS=true`, vendor IP-range lookups and any rDNS verification calls return deterministic fakes with no live network access, for both Phase 4 verification and Phase 5 company-resolution reuse.
    `proven by:` unit tests running fully offline under mock mode for both new call sites.
    `strategy:` Fully-Automated

---

## Resolved Open Questions

Each of the 8 SPEC-blocking questions supplied is resolved below with a default. All are marked **assumption — confirm** for user review; none are left open at SPEC completion.

1. **Schema shape.** *Default (confirmed as D1):* a separate agent-visit data surface (not a `visitor_type` discriminator on existing tables). Conceptual fields required (WHAT, not migration HOW): `site_id`, `first_seen_at`, `last_seen_at`, `vendor` (e.g. "openai", "anthropic", "perplexity"), `product_or_ua_token` (e.g. "GPTBot", "ClaudeBot"), `verification_method` (`ua-only` / `ip-verified` / `rdns-verified`), `ip_address`, `page_paths` (list/count), `visit_count`, `resolved_company_id` (nullable, FK-shaped reference into existing company/lead data). — **assumption — confirm**

2. **Verification timing.** *Default:* verification (IP-range / rDNS) runs asynchronously / best-effort AFTER the UA-only classification that happens on the ingest hot path. No added latency is introduced to `/ingest` itself. — **assumption — confirm**

3. **Filter ordering.** *Default:* the recognized AI-agent vendor allowlist is evaluated BEFORE the datacenter/proxy-VPN drop checks, specifically for agent-classification purposes — so legitimate vendor cloud infrastructure is never silently re-dropped by filters designed to catch generic scrapers. The existing datacenter/proxy drop behavior for everything else is unchanged. — **assumption — confirm**

4. **Billing / quota.** *Default:* agent DETECTION itself is free/unmetered — it does not consume any existing per-site budget (identity resolution budget, deep-research budget, etc.). The company-resolution → outreach path (Phase 5) DOES consume the existing identity-resolution budget, because it reuses the same provider waterfall as human visitor resolution. — **assumption — confirm**

5. **Consent / DNT.** *Default:* GPC/DNT/`do_not_resolve` is human-subject-only logic and does NOT suppress agent DETECTION or classification (an AI agent is not a data subject in the GDPR sense). However, once an agent visit resolves to a real company and that company enters the human pipeline (Phase 5), the existing human consent/suppression/`do_not_email` logic applies in full, unchanged. — **assumption — confirm**

6. **Vendor-list maintenance.** *Default:* a static UA-token + IP-range JSON dataset checked into the repo, refreshed by a scheduled task specifically for OpenAI and Perplexity (the two vendors that publish ranges). New/unconfirmed vendors (Amazonbot, cohere-ai, Meta crawlers) are tracked as backlog items, not built in v1. — **assumption — confirm**

7. **Confidence UI.** *Default:* every agent visit shown in the dashboard carries a visible per-visit verification-method badge (ua-only / ip-verified / rdns-verified). — **assumption — confirm**

8. **Google-Extended / Applebot-Extended handling.** *Default:* these are surfaced (if at all) as derived robots.txt-policy information for the user's own site — never as detected "visits," since they structurally cannot appear as live request UAs. — **assumption — confirm**

**Two additional resolutions carried over from the research brief (not in the original 8, but required to lock scope):**

9. **Feature-folder decision.** *Default:* promote to `process/features/evallayer/` now (this SPEC), folding in the existing discoverability plan as Phase 0. — **resolved, not an open assumption** (this SPEC session performs the promotion).

10. **Outreach-exclusion guardrail priority.** *Default:* Phase 7 (outreach-exclusion guardrail) is treated as a **hard release gate for Phase 5**, not merely a late-numbered nice-to-have — i.e., PLAN for Phase 5 should not be considered complete/mergeable until Phase 7's regression test exists or is scheduled immediately alongside it. Phase numbering (0–7) reflects dependency order, not priority order. — **assumption — confirm**

**Nav placement (11th research question) resolution:** *Default:* a new top-level "Agents" tab (not a filter/facet on the existing Visitors page), per locked decision D1 (separate surface, not a discriminator). — **resolved by D1, not a new open assumption.**

---

## Constraints

(See also "Known Constraints / Risks" detail below — this section is the canonical Constraints anchor.)

## Known Constraints / Risks

- **Detection is never certain.** UA strings are spoofable in both directions — a scraper can claim to be GPTBot, and a real agent can omit its documented token. Confidence must always reflect verification METHOD, not be presented as ground truth.
- **Vendor asymmetry.** Only OpenAI and Perplexity publish IP ranges. Anthropic (Claude) does not — ClaudeBot/Claude-User/Claude-SearchBot traffic is permanently UA-only / lower-confidence by Anthropic's own design, not a Beam limitation.
- **robots.txt-only tokens are not detectable live.** Google-Extended and Applebot-Extended are opt-out declarations, never live request UAs — they cannot be "detected" server-side under any verification tier.
- **Existing filter interaction risk.** The current datacenter/proxy-VPN IP drops (`apps/api/routers/events.py:119-140`) run after the UA check today and would kill legitimate vendor cloud IPs if agent classification isn't reconciled with them (see Resolved Open Question 3).
- **Multi-tenancy unchanged.** All new agent-visit data, APIs, and dashboard views must respect existing `Site.user_id == user.id` scoping and 404-not-403 foreign-id behavior — no exceptions for the new surface.
- **Mock-mode requirement.** Every new external call (vendor IP-range JSON fetch, rDNS lookup) must ship a `MOCK_EXTERNAL_APIS=true` deterministic path, matching existing house convention.
- **Pixel blind spot (accepted, out of scope).** `tracker.js` blocks when `navigator.webdriver === true`, so headless agentic browsers never fire the client-side pixel. Server-side UA detection on `/ingest` is the only detection surface this program builds; this is a documented coverage limitation, not a defect to be fixed here.
- **Business guardrail (non-negotiable).** Agent-classified records must be hard-excluded from directly entering the email/campaign pipeline. Only an explicitly-created company/lead record (from Phase 5's resolution step) may enter outreach, and it must re-enter all existing human consent/suppression/approval gates unchanged.
- **Known Research Gap:** The `read:identity` research sub-agent for this program's RESEARCH fan-out returned placeholder/test output rather than real findings (see raw research brief — its result fields literally contain the string `"test"`). This means **the specific enrichment-waterfall mechanics for agent→company resolution (Phase 5) are under-researched.** This SPEC deliberately does not lock any provider-level mechanics for Phase 5 as a result. **Re-research is required at Phase 5 PLAN time** before that phase's plan is written — flagged explicitly so it is not silently skipped.
- **Test coverage gap.** No existing test asserts AI-vendor-specific classification behavior today (only generic bot-filter coverage is confirmed). Phase 1 should scaffold `tests/unit/test_agent_classifier.py` early, test-first, per the research brief's infra suggestion.
- **Context-doc drift (unrelated, noted for UPDATE PROCESS only):** `all-context.md` currently describes ClickHouse as the events store; `event.py`'s docstring says Postgres replaced it for MVP scale. Not part of EvalLayer scope — flagged so it isn't conflated with this program's blast radius.
- **Unrelated in-flight work (noted, not EvalLayer scope):** uncommitted changes to `apps/api/services/known_hash.py` and `tests/unit/test_known_hash.py` are PII email-hash refactor work from a separate task, confirmed unrelated to EvalLayer.

---

## Success Metrics

- **Coverage:** % of recognized AI-agent vendor visits (OpenAI, Anthropic, Perplexity, ByteSpider, etc.) that are classified and persisted instead of silently dropped — target: 100% of UA-matching traffic for the vendor list in scope (acknowledging the pixel/headless blind spot is out of scope for this metric).
- **Isolation:** 0 agent-classified records ever appear in human Visitor/Event tables or the Visitors dashboard tab (hard invariant, tested every release).
- **Confidence honesty:** 100% of displayed agent visits carry a verification-method label; 0% of UA-only visits are ever displayed as "verified" without a corroborating IP/rDNS check.
- **Guardrail integrity:** 0 agent-visit records ever appear as an outreach-eligible target in campaign/segment logic (regression-tested on every relevant code change, not just at ship time).
- **Lead generation value:** number of new company/lead records created via the agent→company resolution path per month (business-value signal for Phase 5, tracked post-launch, not a gating criterion for SPEC completion).
- **Latency:** `/ingest` p95 response time for agent traffic within existing tolerance for human traffic (no material regression from adding the classification step).

---

## Scope-Tier → Phase Mapping

| Phase | Scope tier | One-line scope | Depends on |
|---|---|---|---|
| 0 | Foundation (independent) | Discoverability fold-in (JSON-LD offers + `ai-plugin.json`) — already drafted, unchanged | None |
| 1 | Foundation | Data model + classifier service (new agent-visit data surface, vendor-token classification split from drop-only bot filter) | None |
| 2 | Foundation | Ingest wiring — hook classifier into `/ingest`, reconcile filter ordering vs. datacenter/proxy-VPN drops | Phase 1 |
| 3 | Foundation → Expansion boundary | Read API + dashboard "Agents" tab (list/detail/stats) | Phase 2 |
| 4 | Expansion | IP-range / rDNS verification + confidence tiering | Phase 2 (parallel-safe with Phase 3) |
| 5 | Expansion | Company-resolution → outreach feed (re-research required at PLAN time) | Phase 3, Phase 4 |
| 6 | Expansion | Aggregation + GEO/AEO analytics widgets | Phase 3, Phase 4 |
| 7 | Expansion (elevated priority — release-gate for Phase 5) | Outreach-exclusion guardrail + regression test | Phase 2 (can and should run in parallel with/ahead of Phase 5) |

---

## Open Questions

None remain open. All items originally flagged as open questions (the 8 SPEC-blocking questions plus the 2 additional program-shaping questions) are resolved with defaults in the "Resolved Open Questions" section above — each marked `assumption — confirm` for user review, not left unresolved. Two follow-ups are tracked for later phases, not blocking SPEC completion: (1) user confirmation of the 10 resolved-default assumptions, (2) mandatory fresh RESEARCH on agent→company enrichment mechanics before Phase 5 PLAN begins.

## Background / Research Findings

Condensed from the full RESEARCH synthesis brief (7-agent fan-out: ingest, identity, backend, frontend, discoverability, signals, synthesis):

- **Today's flow:** `tracker.js` (blocks if `navigator.webdriver===true`) → `POST /events/ingest` → `is_bot(request_ua)` short-circuit (silent 204, no DB row) → datacenter/proxy-VPN IP drops → Event row → `visitor_aggregator.py` → identity resolution waterfall → dashboard/campaigns. AI-agent traffic today is caught by the SAME `is_bot()` regex used for generic scrapers/bots (`_BOT_PATTERN` in `apps/api/services/bot_filter.py` already lists `claudebot|anthropic|openai|gptbot|chatgpt|bedrock-agentcore|agentcore|shap-user|perplexitybot|bytespider`) — it is discarded, never classified or stored.
- **Reusable precedent patterns identified:** `apps/api/services/identity_classification.py`'s frozenset-tiering shape (`PERSON_LEVEL_PROVIDERS`/`COMPANY_LEVEL_PROVIDERS` + `identity_level()`) is the direct template for a `VERIFIED_VENDOR` vs `UA_GUESS` classifier. `apps/api/services/company_resolver.py`'s async/cached/fail-open IP-classification pattern (`classify_org_kind`, `is_datacenter_ip`) is the reusable template for checking a request IP against a vendor's published IP-range JSON.
- **Detection signal tiers, ranked:** (1) UA substring match — trivially spoofable; (2) published IP-range/CIDR cross-check — only OpenAI (3 JSON files: gptbot/chatgpt-user/searchbot) and Perplexity (2 files) publish ranges; Anthropic explicitly does not; (3) Forward-Confirmed reverse DNS — vendor-agnostic, highest rigor, works even for Anthropic, but adds a live DNS round-trip to a hot path.
- **Category-confusion trap surfaced by research:** Google-Extended / Applebot-Extended are robots.txt-only opt-out tokens that never appear as live request UAs — "detecting" them as visits is a category error.
- **Ranked risks from research** (top 3 by severity): (1) no schema exists at all today — 100% net-new migration, triggers VALIDATE regardless of phase; (2) business-guardrail conflict risk — campaigns/segments/outreach is built entirely around human consent-gated email, so agent records must be explicitly excluded, not assumed-excluded; (3) filter-ordering conflict between UA-based agent-allowlisting and the existing datacenter/proxy-VPN drops.
- **Test gap analysis:** zero existing test coverage for AI-vendor-specific classification; the outreach-exclusion guardrail (now Phase 7) was explicitly flagged by research as "the highest-priority Known-Gap; must become a first-class regression test, not optional" — this SPEC elevates that flag into Resolved Open Question 10 and Acceptance Criterion 10.
- **Research quality caveat (load-bearing for Phase 5 planning):** the `read:identity` sub-agent in the RESEARCH fan-out returned placeholder ("test") output instead of real findings — the enrichment-waterfall specifics for agent→company resolution were not actually researched this pass. This is called out explicitly above under Known Constraints / Risks and must be re-researched before Phase 5 PLAN.
- **User's locked product decisions** (supplied directly, not re-litigated by this SPEC): D1 (separate Agents data surface + API + dashboard tab, never a discriminator on human tables), D2 (dual "both" outcome — GEO/AEO insights dashboard AND company-resolution→outreach feed, agent itself never emailed), D3 (discoverability is Phase 0, already drafted, runs independently), D4 (8-phase decomposition as listed above).

---

**Status:** DONE
**Summary:** Wrote the program-level EvalLayer SPEC (requirements only — no approach/implementation chosen) to `process/features/evallayer/active/evallayer_22-07-26/evallayer_SPEC_22-07-26.md`, promoting the feature to `process/features/evallayer/` and folding in the existing discoverability plan as Phase 0. Covers 8-phase scope-tier mapping, 14 acceptance criteria (each with proven-by/strategy), 10 resolved open questions (all marked assumption-confirm), and the enrichment-waterfall research gap for Phase 5.
**Concerns/Blockers:** None blocking — all open questions carry a proposed default for user review rather than being left unresolved. Two items need explicit user confirmation before Phase 5 PLAN: (1) the 8 resolved-default assumptions above, and (2) that Phase 5 PLAN must trigger fresh RESEARCH on agent→company enrichment mechanics before writing that phase's plan (the original research pass returned placeholder output for that sub-question).
