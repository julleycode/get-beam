---
name: plan:site-analysis-onboarding-spec
description: "Product-discovery SPEC for auto site analysis at onboarding Add-Site — Beam fetches the user's site, identifies the company, generates an ICP and competitor list, and shows it as an editable 'here's what Beam understood' surface that pre-seeds description/category and downstream AI"
date: 13-08-26
feature: onboarding-canary
metadata:
  node_type: plan
  type: spec
---

# SPEC — Auto Site Analysis at Add-Site (Onboarding)

> **TL;DR:** When a new user types their site URL during onboarding, Beam quickly reads the site, then (in the background, while they install the pixel) uses grounded AI to figure out what the company does, who its ideal customers are, and who its competitors are. The result appears as an editable "here's what Beam understood about your site" card. Confirmed fields auto-fill the site's description and category, which today sit empty and starve the AI segmenter and campaign planner. Analysis can fail or run late without ever blocking onboarding. Feature flag default OFF; strict budget, mock-mode, and prompt-injection guards apply.

## Summary

Today, adding a site to Beam asks the user to type a URL, a name, and an optional description — and Beam learns nothing about the business itself. The `Site.category` field is never filled in, and the AI features downstream (visitor segmentation, campaign planning) run on near-empty context. This feature makes the Add-Site step smart: Beam reads the site itself, tells the user in plain language what it understood — what the company does and sells, what industry it's in, who its ideal customers are, and who it competes with — and lets the user correct anything before it's saved. The heavy AI analysis runs in the background while the user is busy installing the tracking pixel, so onboarding never feels slower. The confirmed profile becomes durable data on the Site record that every downstream AI feature can use.

## User Stories / Jobs To Be Done

- **US-1 (instant recognition):** As a new user adding my site, I want Beam to recognize my site and platform the moment I enter my URL, so onboarding feels like Beam already "gets" my business instead of asking me to fill out forms.
- **US-2 (no waiting):** As a new user, I want the deeper AI analysis to happen while I'm doing the pixel install step, so I never sit on a spinner waiting for AI.
- **US-3 (review and correct):** As a new user, I want to see exactly what Beam understood about my company — summary, what I sell, industry, ideal customers, competitors — and edit anything that's wrong, so wrong guesses never silently pollute my account.
- **US-4 (pre-seeded AI):** As a user who later runs segmentation or campaign planning, I want those AI features to already know my business context from day one, so their output is relevant without me re-explaining my company.
- **US-5 (never blocked):** As a new user whose site is down, empty, or unusual, I want onboarding to complete normally even when analysis fails, so a background AI hiccup never costs Beam a signup.
- **US-6 (fix it later):** As a site owner whose analysis failed during onboarding (or whose business changed), I want to re-run the analysis later from my site's settings, so I'm not permanently stuck with a failed or stale profile.

## What The User Wants (Behavioral Outcomes)

Observable behavior, outside-in:

1. **At the site step:** entering a URL triggers a fast automatic check of the site (~~platform + basic content~~ **platform detection only — see `## Amendments` row A-1; the content read moved to the async post-creation analysis, N11**). This is quick and quiet — the Continue button is never held hostage by it. If the site can't be reached, the step behaves exactly as it does today.
2. **After Continue (site created):** the deeper AI analysis starts automatically in the background. The user moves on to the Install Pixel step as normal.
3. **While installing the pixel:** a small, non-blocking status is visible — "Analyzing your site…" (pending), then either the results or a gentle "We couldn't analyze your site — you can add details yourself" (failed). The user can finish onboarding in any of these three states.
4. **When results are ready:** an editable "Here's what Beam understood about your site" card appears, clearly labeled as AI-generated. It shows the company summary, what the company sells, industry/category, ideal customer profile, and competitors. Every field is editable.
5. **On confirm:** the user's (possibly edited) version is saved as the site's profile. The site's `description` and `category` fields are auto-filled from it — visibly, with the user able to see and change those values before or after saving. Nothing is silently overwritten.
6. **Downstream:** the AI segmenter's prompts now carry a real description and category for this site instead of blanks. (Same data becomes available to the campaign planner and any future consumer.)
7. **Later, in the dashboard:** the site owner can view the saved profile and trigger a fresh analysis from site settings (subject to the daily budget). Edits the user made are not silently clobbered by a re-run — a re-run shows its new results for review the same way onboarding did.
8. **Flag off (default):** none of the above exists. Onboarding, site creation, and the dashboard are byte-for-byte today's behavior. No fetch of the user's site beyond the existing platform detection, no AI calls, no new UI.

## Flow / State Diagram

```
ONBOARDING WIZARD
=================

  welcome → [canary steps] → SITE STEP ──────────────→ INSTALL STEP ──→ done
                              │                          │
                              │ user types URL           │
                              ▼                          │
                    ┌──────────────────┐                 │
                    │ fast sync fetch  │                 │
                    │ platform + basic │                 │
                    │ content extract  │                 │
                    └───────┬──────────┘                 │
                fail? ──────┤ (behave as today,          │
                            │  Continue never blocked)   │
                            ▼                            │
                     Continue pressed                    │
                     site created                        │
                            │                            │
                            ▼                            ▼
                 ┌────────────────────┐        ┌───────────────────────┐
                 │ ASYNC AI ANALYSIS  │        │ status visible:       │
                 │ (grounded: company │───────▶│  PENDING              │
                 │  profile, ICP,     │        │   │        │          │
                 │  competitors)      │        │   ▼        ▼          │
                 └────────────────────┘        │  READY    FAILED /    │
                                               │   │       TIMED OUT   │
                                               │   ▼        │          │
                                               │ editable   │ "add     │
                                               │ review     │  details │
                                               │ card ──┐   │  your-   │
                                               │        │   │  self"   │
                                               └────────┼───┴──────────┘
                                                        │        │
                                                        ▼        ▼
                                              user confirms   onboarding
                                              (edits kept)    completes
                                                        │     anyway —
                                                        ▼     NEVER blocked
                                          site profile saved +
                                          description/category
                                          auto-filled (visible)
                                                        │
                                                        ▼
                                        segmenter / campaign planner
                                        prompts now pre-seeded

LATER (dashboard site settings):
  view saved profile → "Re-run analysis" → same PENDING/READY/FAILED
  cycle → new results shown for review (user edits never silently lost)
  → budget-capped per day
```

## Acceptance Criteria (Testable Outcomes)

All test scenarios below are drawn from the repo's existing test surfaces identified in research: pytest `tests/unit/` + `tests/integration/` (Fully-Automated), Playwright `apps/web/e2e/` (Hybrid until the Clerk auth harness lands — the recurring repo-wide gap), and Agent-Probe for grounded-AI output quality (needs-live-provider tier, per existing deep-research precedent).

**Sync fetch at site step**

- **AC-1 — AMENDED 13-08-26, see `## Amendments`. v1 text (superseded):** Entering a site URL produces a fast platform + basic-content read of the site; the result (or its absence) never delays or disables the Continue button. An unreachable/erroring site leaves the step behaving exactly as today.
  - proven by: integration test on the site-step fetch/extract endpoint (success, timeout, 4xx/5xx site, non-HTML response); e2e leg asserting Continue stays enabled during fetch.
  - strategy: Fully-Automated (backend); Hybrid (e2e leg — Clerk auth-harness gap).
- **AC-1 v2 (authoritative):** Entering a site URL produces a fast **platform detect** of the site; the result (or its absence) never delays or disables the Continue button. An unreachable/erroring site leaves the step behaving exactly as today. **The content read happens asynchronously after site creation, as part of the analysis run — not at the site step.**
  - proven by: `git diff --stat apps/api/services/platform_detector.py apps/api/schemas/sites.py` empty (the sync path is provably unchanged) + e2e leg asserting Continue stays enabled during detect-platform + `tests/unit/test_site_content.py` extraction/failure tests covering the async content read.
  - strategy: Fully-Automated (both halves); Hybrid (e2e leg — Clerk auth-harness gap).

**Async analysis lifecycle**

- **AC-2:** After site creation with the flag ON, analysis starts automatically with no user action; the onboarding UI shows a visible PENDING state on the Install step.
  - proven by: integration test asserting analysis is enqueued/started on site creation (flag on) and status is queryable as pending; e2e leg for the visible pending indicator.
  - strategy: Fully-Automated (backend); Hybrid (UI leg).
- **AC-3:** When analysis completes, the results are persisted on the Site record (profile data + an analyzed-at timestamp) and the onboarding UI transitions from PENDING to READY, showing the review card.
  - proven by: integration test on the full mock-mode lifecycle (create → pending → ready → persisted profile readable via the sites API).
  - strategy: Fully-Automated.
- **AC-4:** If analysis fails or exceeds its time budget, the state becomes FAILED with a plain-language, non-alarming message; onboarding completes normally in PENDING, READY, or FAILED state — analysis can never block the wizard.
  - proven by: integration tests forcing failure and timeout paths; e2e leg completing onboarding while the analysis is still pending.
  - strategy: Fully-Automated (backend); Hybrid (e2e leg).

**Review-and-edit surface**

- **AC-5:** The review card presents every profile section (summary, what-they-sell, industry/category, ICP, competitors) as editable fields, visibly labeled as AI-generated, and the user's edits — not the raw AI output — are what gets saved.
  - proven by: integration test asserting an edited payload overwrites the AI values on save; e2e leg editing a field and confirming persistence.
  - strategy: Fully-Automated (backend); Hybrid (UI leg).
- **AC-6:** Confirming the review auto-fills `Site.description` and `Site.category` from the (possibly edited) profile, and the user can see those values before they land — no silent overwrite of anything the user already typed at the site step (user-entered description wins unless the user accepts the replacement).
  - proven by: integration tests for both branches (empty description → filled; user-typed description → preserved unless explicitly replaced).
  - strategy: Fully-Automated.
- **AC-7:** After confirmation, the segmenter's prompt context for that site contains the confirmed description and category (the existing `{site_description}`/`{site_category}` interpolation is non-empty).
  - proven by: unit test on segmenter prompt assembly with a profiled site fixture.
  - strategy: Fully-Automated.

**Re-run (v1: IN scope, minimal)**

- **AC-8:** A site owner can trigger a fresh analysis from the site's dashboard settings; the re-run follows the same pending/ready/failed lifecycle, presents new results for review the same way, and never silently discards the user's previous edits.
  - proven by: integration test on the re-run endpoint (lifecycle + prior-edits-preserved-until-confirm); UI leg deferred with the same auth-harness condition.
  - strategy: Fully-Automated (backend); Hybrid (UI leg).

**Safety, quota, and flag posture**

- **AC-9:** The feature flag defaults OFF. With the flag off, site creation, onboarding, and the sites API are behaviorally unchanged: no new fetch of the user's site, no AI calls, no new fields in responses that break existing clients, and any new endpoint returns 404 (matching the repo's flag-off convention).
  - proven by: integration regression tests with flag off (existing onboarding/site tests pass unchanged; new endpoint 404s).
  - strategy: Fully-Automated.
- **AC-10:** Analysis runs are budget-capped per site per day (default 3/day, matching the existing deep-research budget precedent). Exceeding the budget yields a graceful "try again tomorrow"-class response, never an error page, and never a partial/junk profile.
  - proven by: integration test exhausting the budget and asserting the capped response + no additional AI calls.
  - strategy: Fully-Automated.
- **AC-11:** With `MOCK_EXTERNAL_APIS=true`, the entire flow (fetch, analysis, review, save) works keylessly with deterministic fake output, short-circuited at the service layer per repo convention.
  - proven by: the mock-mode integration suite for the full lifecycle (this is the same suite backing AC-3).
  - strategy: Fully-Automated.
- **AC-12:** Site HTML and AI output are treated as hostile input: every visitor-of-the-web-derived string entering a prompt is sanitized/fenced per field (per the `prompt_safety` pattern — noting `sanitize_profiles`' fixed-field-table limitation means per-field `clean_text`, not blanket reuse). A site whose content contains prompt-injection text ("ignore previous instructions…") cannot alter the output structure, escape the fence, or surface instructions in the saved profile.
  - proven by: unit tests feeding adversarial HTML fixtures through the extraction→prompt path asserting fencing/stripping; injection-shaped strings never appear unsanitized in the stored profile.
  - strategy: Fully-Automated.
- **AC-13:** No PII and no prompt bodies are logged: structlog events for this feature carry keys/ids/counts only (repo guardrail).
  - proven by: unit test capturing log output during an analysis run and asserting no site body content or prompt text appears.
  - strategy: Fully-Automated.
- **AC-14:** Grounded (live-model) analysis output for a small panel of real sites is coherent and honest: no fabricated competitors for obviously tiny/unknown sites, "unknown/low-confidence" degrades to fewer fields rather than invented ones, and the profile reads sensibly to a human.
  - proven by: manual Agent-Probe run against a documented panel of real sites (live Gemini grounding cannot be asserted deterministically — same tier as the existing deep-research and `find_company_channels` precedents). Residual by necessity, not by choice.
  - strategy: Agent-Probe (needs-live-provider).

## Out Of Scope

- **No auto-outreach or auto-send of anything** derived from this data — Beam's anti-bot stance is untouched; this is context data only.
- **No visitor-side changes:** no pixel changes, no visitor/event ingest changes, no identity-resolution changes.
- **No AgentProfile coupling:** the agent-gateway's `AgentProfile` surface (gated behind `agent_gateway_enabled`) is not read, written, or extended. This profile lives on `Site` (locked decision — new JSONB, no new table).
- **No billing/quota-plan changes:** the analysis budget is an internal cost guard, not a billable/plan-tiered feature; no credits, no plan gating, no pricing-page changes.
- **No competitor monitoring/tracking:** competitors are a one-shot informational list, not a watched or refreshed dataset.
- **No campaign-planner wiring in v1:** the data is *available* to it, but changing the campaign planner's prompts/behavior is a follow-up, not part of this scope. (Segmenter benefits automatically via the already-existing `{site_description}`/`{site_category}` interpolation — that is pre-existing wiring, not new consumer work.)
- **No backfill for existing sites:** v1 targets the onboarding flow plus the manual re-run button; no batch job analyzing the existing site inventory.
- **No non-English/site-language special handling** beyond whatever the model does naturally.

## Constraints

Locked user decisions (requirements, not open for redesign):

- **C-1 (timing = hybrid) — AMENDED 13-08-26, see `## Amendments` row A-1:** fast synchronous ~~fetch (platform + basic content extraction)~~ **platform detect only — the content read moved to the async post-creation analysis** at the site step; grounded AI analysis runs asynchronously after site creation, surfacing results while the user is on the Install step.
- **C-2 (storage = JSONB on Site):** one new JSONB column plus an analyzed-at timestamp on `sites` (exact naming is PLAN's call). One small migration. No new table. No AgentProfile reuse.
- **C-3 (UX = show + editable):** results are always shown for review with editable fields; `description`/`category` auto-fill is user-confirmable. Silent-store is rejected.

System/process constraints:

- **C-4:** Feature flag, default OFF (repo convention); flipping it in any real environment is a separate operator action after the migration is live.
- **C-5:** Gemini 2.5 Flash free tier: grounded calls are slow and rate-capped. The async design absorbs the latency; the per-site daily budget (default 3, mirroring the deep-research 3/day precedent) caps the spend. No per-signup global budget exists today — this feature must not create unbounded new grounded-call volume.
- **C-6:** `MOCK_EXTERNAL_APIS=true` deterministic mock path is mandatory, short-circuiting at the service layer.
- **C-7:** Site HTML and AI output are untrusted input — per-field sanitization via the `prompt_safety` pattern; the `<untrusted…>` fence must stay unforgeable.
- **C-8:** No PII / no prompt bodies in logs (structlog keys/ids only).
- **C-9:** Migration hygiene: alembic head must be re-derived live at plan/execute time, and `DATABASE_URL` must be pinned to `localhost:5433` for any alembic command — repo `.env` points at Supabase PROD (standing safety rule).
- **C-10:** Multi-tenancy: all new endpoints filter through the site-ownership check; foreign site ids read as not-found, never 403.
- **C-11:** Known test-infra gaps inherited, not created here: Clerk Playwright auth harness missing (authed e2e legs are Hybrid/CONDITIONAL until it lands); grounded output quality is Agent-Probe tier by nature.

Data captured — what "good" looks like (field shape is product-level; exact JSON naming is PLAN's call):

| Section | Contents | "Good" bar |
|---|---|---|
| Company summary | 2–3 plain sentences: what the company is and does | A stranger could describe the business after reading it; no marketing fluff, no hallucinated scale claims |
| What they sell | Short list of products/services/offer types | Matches what the site actually offers; empty is acceptable, invented is not |
| Industry / category | One category value suitable for `Site.category` (≤100 chars) + optional sub-industry | Usable directly as the category field; specific ("DTC skincare") beats generic ("e-commerce") |
| ICP | Structured: 1–3 personas (role/title + core pain point) and firmographics (company size band, industries, geography) — B2C sites may express personas as consumer segments instead | Personas a founder would nod at; explicitly sparse when the site gives little signal |
| Competitors | Up to 5 entries: name + domain + one-liner on how they compete | Real, verifiable companies (grounded search helps here); fewer-but-real beats five-with-fakes |
| Meta | Analyzed-at timestamp, model/mode used, per-section confidence or "unknown" markers, user-edited flags | Honest uncertainty: low-signal sites yield sparse profiles with unknowns, never confident inventions |

## Open Questions

None — all product-level decisions are resolved (the three locked decisions plus: re-run is IN scope v1 as a minimal settings button per US-6/AC-8; budget default 3/day per the deep-research precedent; campaign-planner wiring deferred out of scope). Remaining choices (column naming, exact endpoint shapes, sync-fetch time budget number, task-queue mechanism) are implementation decisions that belong to INNOVATE/PLAN, not unresolved intent.

## Background / Research Findings

Key facts that shaped this SPEC (file:line verified 13-08-26 by RESEARCH):

- **Wizard + hook points:** onboarding steps are `welcome → [canary steps] → site → install → done` (`apps/web/src/lib/onboarding-flow.ts:12-36`); the Add-Site screen collects only url/name/description (`site-step.tsx:16-104`). On Continue, `api.createSite → markOnboarded → getPixelSnippet → Install` (`onboarding-flow.tsx:140-168`). A separate effect already calls `POST /sites/detect-platform` → `services/platform_detector.py:159` — today the ONLY fetch of the user's own site, and it discards the HTML body after sniffing the platform. That discarded body is exactly the "basic content extraction" raw material for the sync half. **(Pre-amendment research context, retained for audit: the "sync half" described here was removed by `## Amendments` A-1 — the content read is performed once, asynchronously, in the analysis fetch. `platform_detector.py` is not touched and still discards the body.)**
- **Natural backend hook:** `create_site` (`apps/api/routers/sites.py:56-192`) performs zero analysis today.
- **Empty semantic fields:** `Site` has only `description(1000)` + `category(100)` as semantic fields (`models/site.py:14-113`), and `category` is never populated by any UI — while `agents/segmenter.py:19-25` already interpolates `{site_description}`/`{site_category}` into its prompt. The pre-seeding win requires zero new segmenter code.
- **Reusable AI machinery:** `gemini_generate(grounding=True)` (provider-side Google Search), `gemini_generate_json` with repair re-prompting, and two anti-fabrication precedents: `enricher.py:1036 deep_research` (budget 3/day/site) and `content_reader.py:691-723 find_company_channels` (grounded, confidence-gated, 30-day domain cache).
- **Genuinely new ground:** ICP generation and competitor identification have zero existing product code — this is new product surface, not a refactor.
- **Cost reality:** Gemini free tier; grounded calls are slow/expensive; no per-signup budget exists yet — hence the async design + hard per-site budget.
- **Safety reality:** site HTML and AI output are hostile input; `sanitize_profiles` only covers a fixed field table, so this feature needs per-field `clean_text` (C-7/AC-12).
- **Home + adjacency:** `process/features/onboarding-canary/` is the home feature; the active `canary-onboarding_10-08-26` plan (Phase 1 backend shipped, flag OFF; phases 2–4 pending) rebuilds the same wizard in React — PLAN must coordinate touchpoints on `onboarding-flow.tsx`/steps with that program, but this SPEC's scope is independent of the canary reveal.
- **User's brainstorm intent (captured):** make onboarding feel like Beam already understands the business ("smoother"), and stop running the downstream AI on empty context — with explicit rejection of silent-store (the user wants the "here's what we understood" moment) and explicit rejection of AgentProfile coupling (scope mixing with a gated feature).

---

## Amendments

| # | Date | Criterion | Amendment | Why |
|---|---|---|---|---|
| A-1 | 13-08-26 | **AC-1** (scope also covers **§Constraints C-1** and the §Background "sync half" sentence — extended cycle 5, C24) | The sync site-step is **platform-detect only** — unchanged from today's behavior and NOT a new capability. The **basic-content read moves to the async analysis fetch** that runs after site creation. AC-1 v2 (above) is authoritative; v1 is retained struck-through-in-place for audit. | Raised as **F6** in PVL cycle 2. PLAN's PVL cycle 1 took **F1 option (a)**: `apps/api/services/platform_detector.py` is not refactored and not touched, because its live fetch uses a bare `httpx.AsyncClient` (`:174`, `:223`) while the plan mandates the DNS-pinned `url_guard` posture (`pixel_verifier.py:122-124`). Delegating the sync path to the new helper would have silently upgraded `detect_platform` bare→pinned — a real, untested behavior change against a module with **zero** behavioral test coverage, breaking AC-9's byte-identical guarantee. The content read is therefore performed **once**, asynchronously, where the pinned posture is required anyway. No user-visible outcome is lost: the site step already never blocked on the read, and results still surface on the install/done step. |

**Amendment discipline:** an acceptance criterion is amended here, in the SPEC, when scope changes make it unsatisfiable as written. It is never silently re-pointed at a gate that proves different behavior — that is the exact failure F6 caught. The plan's §Acceptance Criteria carries a pointer to this section.
