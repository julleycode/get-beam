---
name: plan:handoff-spec
description: "Handoff Detection — program-level SPEC: resolve the human behind AI-agent traffic (fetch↔click correlation + AI-mediated intent signals)"
date: 23-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: spec
---

# Handoff Detection — Program SPEC

**Date:** 23-07-26
**Feature:** evallayer (successor program to the 8-phase EvalLayer detection program, now
code-complete — see `evallayer-umbrella_PLAN_22-07-26.md` §Program-Level Closeout)
**Governs:** all 4 phases (H1–H4) of this program. Per protocol, the phase-program INNER loop
skips SPEC — this document is the one and only requirements doc for every phase.

---

## Summary (BLUF)

Beam can already tell you *that* ChatGPT visited a page (EvalLayer, shipped) and *that* a human
who clicked an AI-engine citation just landed on the site (AI-Referral Attribution v1, shipped).
This program connects those two facts: when the same page is fetched by an AI agent on behalf of
a live user and then clicked-through by a human shortly after, we link them — surfacing "this
identified visitor was behind a ChatGPT fetch at 14:32" on the dashboard — and separately, we alert
founders in near-real-time when someone is actively asking an AI agent about their product right
now. No competitor currently does agent-fetch-to-human-click correlation; this is white space.

**TL;DR:** 4 phases — H1 lays a per-hit event table + on-demand-vs-index tiering (also unblocks
the backlogged daily-timeseries chart); H2 correlates on-demand fetches with human AI-referral
clicks into a new, strictly-separate linkage table; H3 turns the same fetch stream into live
intent alerts; H4 is a manual-first feasibility probe for citation watermarking, gated before any
implementation. The Phase 7 outreach-exclusion guardrail is extended, never weakened: linked HUMAN
visitors stay fully emailable, linked records are never agent contacts.

---

## User Stories / Jobs To Be Done

**US1 (H1 — foundation).** As a Beam site owner, I want every individual AI-agent fetch recorded
with its own timestamp (not just a rolled-up "last seen"), so that later features can reason about
*when* a specific fetch happened, not just that a vendor visited at some point.

**US2 (H1).** As Beam's classifier, I want to distinguish an on-demand fetch (a human asked
ChatGPT/Claude/Perplexity about my page just now) from a routine indexing crawl (bot crawling my
site on its own schedule), so that only on-demand fetches are eligible for handoff correlation and
intent alerts — indexing crawls are noise for this purpose.

**US3 (H2 — handoff correlation).** As a site owner reviewing an identified visitor's timeline, I
want to see when their visit was likely preceded by an AI agent fetching the same page on their
behalf, so I understand the AI research → human decision journey instead of seeing two disconnected
facts.

**US4 (H2).** As a site owner, I want every handoff link to show its confidence and matching
method, never asserted as certain, so I don't over-trust an inherently probabilistic signal.

**US5 (H3 — intent signals).** As a site owner, I want a near-real-time alert when someone is
actively asking an AI agent about my pricing/product right now, so I can react while the interest
is still warm — the same way I'd want to know about a live pricing-page visit.

**US6 (H3).** As a site owner, I want to see when a company's on-demand AI-research activity
correlates with that company later appearing as a resolved lead, so I understand which of my leads
were "AI-assisted" before they ever visited directly.

**US7 (H4 — feasibility, gated).** As Beam's own team, I want an honest, low-risk, manual-first
answer to "do query-string identifiers survive into an AI engine's citation link back to my site?"
before committing to build any watermarking mechanism — because if the answer is no, building it
is wasted effort, and if the answer risks looking like cloaking, we must not ship it silently.

---

## What The User Wants (Behavioral Outcomes)

**H1 — Per-hit event capture + tiering (foundation, not directly user-visible on its own).**
- Every recognized AI-agent HTTP hit is recorded as its own timestamped event (page, vendor,
  raw UA token, IP), in addition to (not instead of) the existing rollup summary.
- Each hit is tagged with a fetch tier: **on-demand** (a human is actively asking the agent right
  now — e.g. `ChatGPT-User`, `Claude-User`, `PerplexityBot`'s on-demand variant, `OAI-SearchBot`)
  vs **index** (routine crawling — `GPTBot`, `ClaudeBot`, `PerplexityBot` index variant,
  `Bytespider`). This tier is the gate for every downstream H2/H3 feature — only on-demand hits
  are eligible for handoff correlation or live intent alerts.
- This also unblocks the previously-backlogged "agent visits over time" daily chart (see
  `phase-06-daily-timeseries_NOTE_22-07-26.md`) since a per-hit table naturally supports daily
  bucketing — but building that chart itself is optional/backlog scope for this program, not a
  required deliverable (see Out of Scope).

**H2 — Handoff correlation.**
- When an on-demand fetch of page X by vendor V happens at time T, and a human's AI-referral click
  (via the shipped `ai_source`/`first_touch_referrer` fields) lands on the *same page X* from the
  *same vendor family* within a bounded time window after T, the system creates a handoff link
  between the agent-fetch event and the human visitor/identity record.
- The dashboard surfaces this on the visitor detail view: a badge or timeline entry reading
  something like "AI research detected: ChatGPT fetched this page at 14:32, 6 minutes before this
  visit" — worded as a probabilistic signal, never a certainty.
- A handoff-linked visitor is a completely ordinary, fully-emailable human record. Linking never
  changes emailability in either direction.

**H3 — Intent signals.**
- **Live on-demand alert:** when an on-demand fetch hits a commercial page (pricing, product,
  signup — configurable per site), the owner can see/receive a near-real-time notification: "Someone
  is asking ChatGPT about your pricing right now."
- **Spike detection:** a rise in on-demand AI-research hits to commercial pages over a rolling
  window surfaces as a dashboard signal (e.g. "3x more AI research on your pricing page this
  week").
- **Company-correlation signal:** when a company later resolves as a lead (via the existing
  company-resolution pipeline) and that company's IP/domain had prior on-demand AI-research
  activity, the lead record shows "AI-researched before first human visit" as contextual metadata
  — never a new outreach trigger on its own, and never person-level (see Constraints).

**H4 — Citation-watermark feasibility (gate, not a feature yet).**
- The founder manually asks a real AI agent (e.g. ChatGPT) to browse a controlled Beam-owned test
  page that carries a unique query-string marker, then inspects whatever citation link the agent
  returns, to see whether the marker survives.
- The probe produces a written VIABLE / NOT-VIABLE / INCONCLUSIVE verdict with an explicit design
  constraint (what it licenses, what it forbids, what remains uncertain).
- Implementation of an actual watermarking mechanism is IN SCOPE only if the verdict is VIABLE, and
  even then requires explicit user sign-off before any production rollout (never automatic).

---

## Flow / State Diagram

```
                         ┌─────────────────────────────────────────┐
                         │   H1: Ingest hit  (existing classifier)  │
                         │   apps/api/routers/events.py             │
                         └───────────────┬───────────────────────────┘
                                         │
                         classify vendor + UA token
                                         │
                     ┌───────────────────┴────────────────────┐
                     ▼                                        ▼
             tier = "index"                            tier = "on-demand"
       (GPTBot, ClaudeBot,                     (ChatGPT-User, Claude-User,
        PerplexityBot-index,                    Perplexity-User, OAI-SearchBot)
        Bytespider)                                            │
                     │                                        │
                     ▼                                        ▼
        write agent_fetch_events row              write agent_fetch_events row
        (rollup AgentVisit unchanged)             (rollup AgentVisit unchanged)
                     │                                        │
                     │                          ┌─────────────┴──────────────┐
                     │                          ▼                            ▼
                     │              H3: commercial-page?           H3: spike detector
                     │              → live alert (near-real-time)  (rolling window job)
                     │                          │
                     │                          ▼
                     │              H2: correlation sweep (periodic job)
                     │              same page + vendor family, window W
                     │                          │
                     │                          ▼
                     │              human AI-referral click found?
                     │                (ai_source + first_touch_referrer,
                     │                 within window after fetch T)
                     │                    │                │
                     │                   yes               no
                     │                    │                │
                     │                    ▼                ▼
                     │        write agent_handoff_links   (no link — fetch stays
                     │        row: confidence, method,      unlinked, still visible
                     │        delta_seconds, matched_page   in raw fetch events)
                     │        NEVER touches
                     │        source_agent_visit_id
                     │                    │
                     │                    ▼
                     │        dashboard: visitor detail badge
                     │        "AI research detected — [vendor]
                     │        fetched this page Xm before this visit"
                     │        (visitor stays fully emailable)
                     │
                     ▼
        (H1-only path — no downstream correlation;
         still feeds daily-timeseries backlog chart
         if that follow-on slice is later built)

H4 (independent, gated, manual):
  founder → asks live AI agent to browse watermarked
  test page → inspects returned citation link →
  vc-debugger writes VERDICT (VIABLE/NOT-VIABLE/INCONCLUSIVE)
  → only if VIABLE + user sign-off: implementation phase considered
```

---

## Acceptance Criteria (Testable Outcomes)

**AC-H1-1 (per-hit capture).** Every recognized AI-agent hit at ingest creates one
`agent_fetch_events` row with page path, vendor, raw UA token, tier, timestamp, and IP — in
addition to (not replacing) the existing `agent_visits` rollup upsert.
- proven by: `tests/unit/test_agent_fetch_events.py` (row created per hit, rollup unaffected)
- strategy: Fully-Automated

**AC-H1-2 (tier classification).** A fetch from a documented on-demand token
(`ChatGPT-User`, `Claude-User`, `OAI-SearchBot`, on-demand `PerplexityBot` variant) is tagged
`tier=on-demand`; a fetch from a documented index token (`GPTBot`, `ClaudeBot`, index-mode
`PerplexityBot`, `Bytespider`) is tagged `tier=index`. Google/Copilot/other vendors with no
documented on-demand token are tagged `tier=index` only (coverage limit, not a bug).
- proven by: `tests/unit/test_agent_fetch_events.py::test_tier_classification` (one case per
  documented token)
- strategy: Fully-Automated

**AC-H1-3 (ingest hot-path safety).** The new per-hit write is fail-open (never raises into the
ingest response) and adds no new synchronous external call.
- proven by: `tests/unit/test_agent_fetch_events.py::test_write_failure_isolated` (mocked
  AsyncSession raising on insert; ingest response still 2xx)
- strategy: Fully-Automated

**AC-H2-1 (handoff link creation).** Given an on-demand fetch of page X by vendor V at time T, and
a human AI-referral visit (`ai_source` matching V's vendor family) to the same page X at time
T+delta where delta ≤ the configured window, the correlation sweep creates exactly one
`agent_handoff_links` row referencing both records with `confidence`, `method`, `delta_seconds`,
and `matched_page`.
- proven by: `tests/unit/test_handoff_correlation.py::test_link_created_within_window` (synthetic
  fixture, deterministic clock)
- strategy: Fully-Automated

**AC-H2-2 (no link outside window or vendor mismatch).** A fetch and a click that fall outside the
configured window, or belong to different vendor families, produce no link.
- proven by: `tests/unit/test_handoff_correlation.py::test_no_link_outside_window` +
  `test_no_link_vendor_mismatch`
- strategy: Fully-Automated

**AC-H2-3 (emailability separation — the hard safety gate).** (a) A visitor/identity linked via
`agent_handoff_links` remains fully emailable — `is_emailable_identity` output is unchanged by the
presence of a handoff link. (b) The linked `agent_fetch_events` / `agent_visits` side of the link
is never itself made emailable and never gains a path into campaign/email/social targeting. Both
directions must be proven by one regression test.
- proven by: `tests/unit/test_handoff_emailability_separation.py` (asserts both directions in one
  test; extends the Phase 7 `test_agent_origin_exclusion.py` pattern)
- strategy: Fully-Automated (highest priority gate in this program, mirroring EvalLayer AC10)

**AC-H2-4 (confidence never presented as certainty).** Every handoff-link API/dashboard
representation includes a `confidence` field and renders qualifying language ("likely",
"detected") — never an unqualified assertion.
- proven by: `tests/unit/test_agents_api.py::test_handoff_confidence_present` (API contract) +
  manual UI copy review (Agent-Probe)
- strategy: Hybrid (API assertion automated; UI wording judgment is Agent-Probe)

**AC-H2-5 (multi-tenancy).** Handoff correlation and its API only ever match/report within a single
`site_id`; cross-site fetch/click pairs never link regardless of timing.
- proven by: `tests/unit/test_handoff_correlation.py::test_no_cross_site_link`
- strategy: Fully-Automated

**AC-H3-1 (live on-demand alert).** An on-demand fetch to a configured commercial page triggers a
near-real-time alert record (reusing the existing hot-alert delivery mechanism) within the same
request-cycle or next scheduled sweep tick, whichever the chosen design uses — INNOVATE decides
delivery latency tier.
- proven by: `tests/unit/test_intent_alerts.py::test_commercial_page_triggers_alert`
- strategy: Fully-Automated (alert creation); Agent-Probe (actual delivery channel UX, if new)

**AC-H3-2 (spike detection).** A synthetic fixture with an on-demand-hit rate increase over a
rolling window produces a spike signal; a flat/declining rate does not.
- proven by: `tests/unit/test_intent_alerts.py::test_spike_detection_threshold`
- strategy: Fully-Automated

**AC-H3-3 (company-correlation signal is metadata, not a new outreach trigger).** The
"AI-researched before first visit" signal attached to a resolved company/lead record never
independently creates, approves, or auto-sends any campaign — it is read-only contextual metadata
on an already-existing lead.
- proven by: `tests/unit/test_intent_alerts.py::test_company_correlation_is_metadata_only`
- strategy: Fully-Automated

**AC-H3-4 (person-level and multi-tenant safety).** Company-correlation signals are attached at
company/site level only — never construct or surface a person-level claim from on-demand fetch
data — and never cross `site_id` boundaries.
- proven by: `tests/unit/test_intent_alerts.py::test_no_person_level_claim` +
  `test_site_scoped`
- strategy: Fully-Automated

**AC-H4-1 (feasibility probe verdict recorded).** The citation-watermark hypothesis is tested via
one manual-first live probe against a real AI agent, and the result is written as a VERDICT
artifact with an explicit VIABLE/NOT-VIABLE/INCONCLUSIVE keyword and the 3-part design constraint
(licenses/forbids/uncertain).
- proven by: VERDICT file existence + keyword grep (`{task_folder}/{slug}_FEASIBILITY_{date}.md`)
- strategy: Agent-Probe (cost-class: needs-live-provider — requires explicit double opt-in per
  `orchestration.md` §VC-FEASIBILITY-PROBE-NEEDED Signal Routing)

**AC-H4-2 (no silent implementation on INCONCLUSIVE/NOT-VIABLE).** If the H4 verdict is anything
other than VIABLE, no watermarking mechanism is implemented in this program; the program treats H4
as complete once the VERDICT is written, regardless of outcome.
- proven by: manual review of program closeout — confirms no watermark-write code path exists
  unless a VIABLE verdict + explicit user sign-off is on record
- strategy: Agent-Probe

---

## Out Of Scope

- Google-Extended / Applebot-Extended / Microsoft Copilot handoff correlation — these vendors have
  no documented on-demand fetcher token as of this SPEC's research; only their (existing,
  EvalLayer-shipped) index-crawl classification applies. Revisit if a vendor publishes one.
- De-anonymizing or "resolving" a human identity purely from an index-crawl hit — index crawls are
  never eligible for handoff correlation or intent alerts (H1 tier gate is structural, not a
  future toggle).
- Emailing, contacting, or otherwise treating any agent-fetch record as an outreach target, at any
  confidence level — this SPEC never weakens the EvalLayer Phase 7 guardrail; AC-H2-3 is the
  regression proof.
- Building the full "agent visits over time" daily-chart dashboard card (backlogged in
  `phase-06-daily-timeseries_NOTE_22-07-26.md`) — H1's per-hit table unblocks it, but shipping the
  chart itself is a separate, optional follow-on slice, not a required deliverable of H1.
- Implementing any citation-watermarking mechanism before H4's probe returns a VIABLE verdict AND
  the user explicitly signs off on a production rollout.
- Any cloaking, UA-sniffing-based content variation, or other technique that would place Beam's
  posture at odds with vendor crawling guidelines, regardless of H4's outcome.
- Person-level identification derived solely from AI-mediated intent signals (H3) — those signals
  stay company/site-scoped metadata only.
- New identity-resolution provider integrations — this program correlates existing signals; it
  does not add new enrichment providers.
- Live (non-mocked) IP-range/rDNS vendor verification work — already covered by EvalLayer Phase 4;
  not reopened here.

---

## Constraints

**Hard safety constraints (non-negotiable, every phase):**
1. Handoff links live on a NEW, structurally separate surface (`agent_handoff_links` table, plus
   read-only `visitors`-side fields if needed) — never on `source_agent_visit_id` or any field the
   Phase 7 guardrail inspects. A handoff-linked human visitor is unconditionally fully emailable;
   an agent-fetch record is unconditionally never emailable. Both directions proven by one test
   (AC-H2-3).
2. Every correlation is probabilistic. Every stored link and every UI rendering of it carries a
   `confidence` + `method` field; the UI never asserts certainty.
3. Multi-tenancy unchanged: every new query filters by `site_id`; foreign/unknown ids return 404,
   never 403.
4. Ingest hot-path discipline: the H1 per-hit write must be fail-open and cheap — no new
   synchronous external calls added to the ingest request path. Correlation (H2) and intent
   detection (H3) run as periodic/async jobs, never inline in ingest.
5. No new PII is introduced. Handoff/intent logic uses only already-captured data (timestamps,
   paths, vendor tokens, referrers). `do_not_resolve` / GPC behavior is unchanged. Intent alerts
   are account/site-level signals, never person-level claims.
6. Every new external call (if H4 implementation ever proceeds) ships a
   `MOCK_EXTERNAL_APIS=true` deterministic path before being marked verified.
7. H4's live-provider probe requires explicit double opt-in (billed/live 3rd-party call) — never
   auto-run under `/goal`.

**Technical/research-grounded constraints:**
- Coverage limit: only OpenAI, Anthropic, and Perplexity publish distinct on-demand vs index UA
  tokens as of this SPEC. Google (AI Overviews) and Microsoft Copilot have no such distinction
  documented — handoff/intent features structurally cannot cover them yet.
- Perplexity is known to run undeclared crawlers alongside its documented tokens — UA-based trust
  for Perplexity fetches should be scored lower in the confidence model than for OpenAI/Anthropic.
- Mobile-app AI clients and no-referrer clicks lose the human-side referral signal entirely — this
  causes handoff correlation to UNDERCOUNT real handoffs, never overcount (a missed link is a
  false negative, not a false positive) — acceptable per the probabilistic framing in AC-H2-4.
- AI-referral click-through rates run low (~1%) but conversion on those that do click is high
  (7-16%) — H3's volume expectations should be calibrated as "rare but high-value", not
  high-frequency.
- The `utm_source=chatgpt.com` citation-link convention (confirmed shipping since June 2025) is
  already captured by the shipped `ai_source`/`first_touch_referrer` fields — H2 reuses this,
  it does not need to re-derive it.

---

## Resolved Open Questions (defaults — flagged assumption-confirm)

1. **Correlation window size.** Default: **30 minutes** between an on-demand fetch and a matching
   human AI-referral click, configurable per-site later if needed. *(assumption-confirm)*
2. **Confidence tiers.** Default: 3-tier model — `high` (exact page match + vendor family match +
   delta < 5 min), `medium` (exact page match + vendor family match + delta 5–30 min), `low`
   (same-domain-family match only, e.g. subpage vs exact page, within window). Perplexity fetches
   are capped at `medium` even when timing would otherwise qualify `high`, reflecting its
   undeclared-crawler trust discount. *(assumption-confirm)*
3. **Commercial-page definition (H3).** Default: a per-site configurable list defaulting to
   `/pricing`, `/signup`, `/product*` path patterns — reusing whatever page-classification
   convention (if any) already exists in `traffic-fit-card.tsx`/segmenter; INNOVATE confirms the
   exact mechanism. *(assumption-confirm)*
4. **Alert delivery channel (H3).** Default: reuse the existing hot-alert mechanism/table rather
   than building a new notification channel — INNOVATE confirms the exact integration point.
   *(assumption-confirm)*
5. **H2 sweep cadence.** Default: periodic scheduled job (mirrors the existing `scheduler.py` sweep
   pattern), not a synchronous ingest-time correlation — keeps the hot path clean per Constraint 4.
   *(assumption-confirm)*
6. **H4 test-page ownership.** Default: a Beam-owned, low-traffic test page created specifically
   for the probe (not a real customer page) — avoids any customer-facing risk during the probe.
   *(assumption-confirm)*

None of these block PLAN from proceeding — each carries a stated default. Confirm or override
during INNOVATE/PLAN if the defaults don't match intent; otherwise they stand as the answer.

---

## Success Metrics

- AC-H1-1/2/3 green — per-hit table live, tiering correct, ingest hot path unaffected (no latency
  regression vs EvalLayer Phase 2 baseline).
- AC-H2-3 (emailability separation) green — the single highest-priority gate in this program,
  mirroring EvalLayer's AC10 discipline; must pass before H2 is considered mergeable/VERIFIED.
- At least one synthetic end-to-end fixture demonstrates a full fetch→click→link→dashboard-badge
  path (H2) and a full fetch→commercial-page→alert path (H3).
- H4 VERDICT artifact exists with a recorded keyword, regardless of outcome — "done" for H4 means
  the probe ran and was recorded, not that watermarking shipped.
- Zero regressions in existing EvalLayer (agent-visit rollup) and AI-Referral (`ai_source`) test
  suites — both are read-only dependencies for this program, never modified.

---

## Background / Research Findings

- **EvalLayer program (shipped, code-complete 23-07-26):** delivered agent classification
  (`agent_classifier.py`, `_VENDOR_TOKENS` — openai/anthropic/perplexity/bytespider), an
  aggregate-only `agent_visits` rollup table (upsert-keyed, no per-hit timestamps — confirmed by
  reading `models/agent_visit.py` this session), an `/agents` dashboard, IP-range verification for
  OpenAI/Perplexity, company-resolution → outreach feed, GEO/AEO analytics, and the outreach-
  exclusion guardrail (`is_emailable_identity`'s `source_agent_visit_id` override — confirmed live
  in `identity_classification.py` this session, the exact mechanism AC-H2-3 must not touch).
- **AI-Referral Attribution v1 (shipped same session, bonus work outside EvalLayer's 8-phase
  scope):** `ai_referral.py`'s `classify_ai_source()` maps a human's `first_touch_referrer` host to
  a vendor label (chatgpt/perplexity/gemini/copilot/claude/you/grok/deepseek/mistral — deliberately
  excludes bare google.com/bing.com since those answer in-SERP). `Visitor.ai_source` +
  `Visitor.first_touch_referrer` are confirmed live columns (read this session). This is the
  human-side half of the H2 correlation — already shipped, reused not rebuilt.
- **Vendor on-demand vs index tokens (research verified this session, official docs):**
  OpenAI's `ChatGPT-User` fires "not from automatic crawling" — only when a human actively asks;
  Anthropic's `Claude-User` fires "when a user asks Claude a question"; Perplexity's
  `Perplexity-User` fires "in real time when a user asks a question." All three vendors document a
  SEPARATE index-crawl token (`GPTBot`, `ClaudeBot`, index-mode `PerplexityBot`). Google (AI
  Overviews) and Microsoft Copilot publish no equivalent on-demand token — a genuine, permanent
  coverage limit for this program, not a research gap to close later.
  `apps/api/services/agent_classifier.py::_VENDOR_TOKENS` already lists both tiers' tokens per
  vendor (confirmed: `chatgpt-user`, `claude-user`, `claude-searchbot`, `oai-searchbot`,
  `perplexity-user` alongside `gptbot`, `claudebot`, `perplexitybot`, `bytespider`) — H1 does not
  need new token discovery, only a tier-split read of the existing dict.
- **Citation UTM convention:** ChatGPT has appended `utm_source=chatgpt.com` to citation links
  since June 2025 — already captured on the click side by the shipped `ai_source` classifier; H2
  reuses this rather than re-deriving it.
- **Caveats surfaced by research (baked into Constraints above):** Perplexity runs undeclared
  crawlers alongside its documented UA tokens (lower UA trust); mobile-app/no-referrer AI clients
  lose the referral signal entirely (causes undercount, never overcount); AI-referral CTR is low
  (~1%) but conversion on those clicks is high (7-16%), setting realistic volume expectations for
  H3 alerts.
- **Watermark feasibility (H4 rationale):** query-string identifiers plausibly survive into AI
  citation links (the UTM-persistence precedent is suggestive) but this is UNPROVEN for a
  Beam-controlled custom marker — hence the mandatory manual-first live probe before any
  implementation commitment, per `orchestration.md` §VC-FEASIBILITY-PROBE-NEEDED Signal Routing.
- **Competitive white space:** no competitor product was found (during this session's research)
  that correlates an AI agent's on-demand fetch with a subsequent human click-through sourced from
  that same agent's answer — this handoff-correlation capability (H2) is a genuine differentiator,
  not parity work.
- **Backlog unblocked, not obligated:** `phase-06-daily-timeseries_NOTE_22-07-26.md` documents that
  the existing `agent_visits` rollup has no per-day history to chart from; H1's per-hit
  `agent_fetch_events` table structurally unblocks that chart, but building the chart itself
  remains optional/backlog (see Out of Scope) — H1 is graded on its own ACs, not on that follow-on.
