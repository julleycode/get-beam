---
name: spec:agent-native-revenue
description: "Agent-Native Revenue — program-level product-discovery SPEC for WS0-WS3 (WS4 design-note only)"
date: 30-07-26
metadata:
  node_type: memory
  type: spec
  feature: agent-native-revenue
  phase: umbrella
---

# Agent-Native Revenue — Program SPEC

Date: 30-07-26
Status: LOCKED (pending Open Questions resolution — see below)

---

## Summary

Right now Beam can tell that an AI shopping agent (ChatGPT, Perplexity, Claude, etc.) visited a
site, but it treats that visit as a dead end — nothing links "an agent fetched this page" to "a
real buying company was evaluating us," and nothing lets the site owner actually talk back to
that agent. This program turns Beam from a passive detector into an active **reception desk**
for AI buying agents: when an agent (or the human it's acting for) shows up, Beam identifies the
real company behind the visit, shows the sales team a readable timeline of that company's AI
research activity, quietly labels agent-operated browser sessions without disrupting anyone's
experience, and — for one real pilot site — offers the agent a structured trade (a real answer in
exchange for basic qualification info) that produces an actual sales lead. The goal is to prove,
with real traffic (not lab tests), that this reception-desk model creates revenue-relevant signal
that today's "just detect the bot" approach does not.

## User Stories / Jobs To Be Done

**WS0 — Ops Gate (prerequisite plumbing, not user-facing but required for everything below)**

- As the Beam operator, I want the agent-handoff marker and resolution-priority code merged and
  live in production, so that every downstream workstream has real prod data to work with instead
  of a hypothetical.
- As the Beam operator, I want to know — with real evidence, not a guess — whether the handoff
  marker actually survives a round trip through each AI vendor's fetch-then-click flow, so I don't
  build WS1/WS3 sales promises on top of an assumption that silently fails in the wild.

**WS1 — AI Evaluation Timeline**

- As a salesperson using Beam, I want to open a company's profile and see a plain-language
  timeline of when and how an AI agent researched that company on our behalf (which pages, which
  AI vendor, when), so that I can open a sales conversation with real, specific context ("I saw
  your ChatGPT agent pulled our pricing page twice last week") instead of a cold pitch.
- As a salesperson, I want that timeline tied to a real, resolved company — not an anonymous
  "someone from OpenAI's IP range" — so the information is actually actionable.

**WS2 — Agent-driven Session Classifier**

- As the Beam operator, I want sessions that are technically "human" (real browser, real click
  events) but are actually being driven by an AI agent (Atlas, Comet, Claude-in-Chrome,
  Playwright-style automation) to be labeled as such, so that downstream product decisions (lead
  scoring, outreach eligibility, analytics) can account for them — without ever blocking or
  degrading the experience for that visitor.
- As a site owner, I want zero change to my site's behavior or speed because of this classifier —
  it should be invisible unless I go looking for the label.

**WS3 — Agent Concierge Kill Test**

- As an AI shopping agent evaluating a vendor on behalf of a real buyer, I want to ask a site's
  MCP concierge for a structured, real answer (pricing, comparison, security info) and get one —
  not a marketing wall — in exchange for telling it who I'm asking for (use case, company size,
  what I'm evaluating against).
- As the site owner, I want that exchange to produce a real lead in my inbox when the agent (or
  the human behind it) wants a quote or demo — a zero-click conversion path that doesn't require
  the human to fill out a form themselves.
- As the Beam operator, I want an honest, binary answer — based on >=20 real wild queries against
  one real site over one week — on whether AI agents actually use a tool like this, so we know
  whether to invest further in this direction or fall back to detection-only.

**WS4 — Network Intel (explicitly NOT a user story this program delivers)**

- Parked. No user-facing behavior is built. Only a privacy-scoped design note is produced, at
  program close, as a design artifact for a future program to pick up or discard.

## What The User Wants (Behavioral Outcomes)

- **WS0**: The marker/handoff code that already exists on the `dev_nhantc2` branch reaches
  production. Once live, at least one real AI-agent visit results in a real, resolvable company
  showing up in Beam's identified-visitors data — proven with production traffic, not a local test.
- **WS1**: A salesperson opens an existing company/visitor view in the dashboard and sees a new,
  readable section showing a sequence of AI-agent fetch events (what page, which AI vendor, when)
  tied to that company — without needing an explanation of what it means.
- **WS2**: A visitor's session is silently tagged as "likely agent-operated" when it exhibits a
  research-set combination of automation signals (webdriver artifacts, cadence, browser
  self-declaration). No visible or functional change happens for that visitor; the label is a
  backend/analytics-only signal, off by default.
- **WS3**: An AI agent querying a pilot site's MCP tools gets useful structured content (pricing,
  comparison, security answers) only after supplying required qualification fields, and can
  trigger a "request a quote / book a demo" action that creates a real lead with full context in
  the site owner's inbox — no human had to fill out a web form.
- **WS4**: Nothing user-facing. A design note only.

## Flow / State Diagram

### WS0 — Ops Gate → downstream unlock

```
[dev_nhantc2 branch, marker+resolution code]
        |
        | (a) user resolves GitHub Actions billing HARD STOP
        v
[branch off dev_nhantc2, fix CI if needed] --PR--> [main]
        |
        | (b) PR merged to main
        v
[prod env vars set: ENCRYPTION_KEY, marker flag, PDL/Proxycurl keys]  -- (c)
        |
        v
[AI agent fetches page] --marker stamped (_bam)--> [same agent-driven human click]
        |                                                    |
        | vendor survives marker? ---- NO ---> [try /r/<token> 302 fallback]
        | YES                                                |
        v                                                    v
[events.py decodes _bam] --> [agent_handoff_links row] --> [resolution_eligibility bypasses
                                                              intent floor] --> [identified_visitors row]
        |
        v
   (d) journal wild YES/NO per vendor  =>  exit metric: >=1 identified_visitors row on prod
```

### WS1 — AI Evaluation Timeline (dashboard read path)

```
[Salesperson opens visitor/company detail page]
        |
        v
[existing "Arrived via" pill]  +  [NEW: collapsible "AI Evaluation Timeline" section]
        |
        v
[new scoped read endpoint] --> [agent_fetch_events joined via agent_handoff_links -> company]
        |
        v
[rendered as ordered list: page | vendor | timestamp]  -- readable without explanation
```

### WS2 — Agent-driven Session Classifier (label-not-block)

```
[Visitor session in browser]
        |
        v
[tracker.js collects behavioral signals client-side: cadence, pointer entropy,
 form-fill timing, UA/brand self-declaration, webdriver/CDP artifacts]
        |
        v
[server-side agent_classifier-style batch job: dual-signal AND-gate over signals]
        |
        v
   THRESHOLD MET? --NO--> [no label, visitor proceeds exactly as before]
        | YES
        v
[visitor gets visibility-only "agent-operated" flag]  -- never blocks, never alters UX,
                                                           default OFF
```

### WS3 — Agent Concierge Kill Test (trade + lead)

```
[AI agent (ChatGPT/Claude) discovers pilot site's MCP tools via user-provided URL
 (Developer Mode) OR Apps Directory listing (gated, out of program's control)]
        |
        v
[agent calls get_offers/get_pricing/check_availability]
        |
        v
   required qualification params supplied (use_case, company_size, evaluating_against)?
        | NO                                  | YES
        v                                      v
[tool declines / requests params]    [tool returns structured real answer]
                                               |
                                               v
                          [agent calls request_quote / book_demo (zero-click lead tool)]
                                               |
                                               v
                          [lead event created with full context -> site owner inbox]
                                               |
                                               v
                     [WS0's identity-resolution path resolves a real company,
                      NOT just a tool-call log]
        |
        v
[1 week wild window, >=20 real queries via ChatGPT + Claude]
        |
        v
   tool-discovery rate / tool-call rate / param-fill rate / lead-event count
        |
        v
   signed GO / NO-GO
        NO CALLS -> STOP, journal, keep detection floor, promote WS2 to priority 1
        CALLS    -> this becomes the main product axis
```

## Acceptance Criteria (Testable Outcomes)

### WS0 — Ops Gate

**AC-WS0-1**: The `dev_nhantc2` branch's marker + resolution-priority code is merged to `main`
via PR (never pushed directly to `dev_nhantc2`), after the user has confirmed the GitHub Actions
billing HARD STOP is resolved.
- proven by: manual verification of PR merge state + CI green on `main` (Hybrid)
- strategy: Hybrid

**AC-WS0-2**: Production environment has `ENCRYPTION_KEY`, the marker feature flag, and
PDL/Proxycurl provider keys confirmed set and readable by the running service.
- proven by: operator-run prod env verification (Agent-Probe — requires live prod access)
- strategy: Agent-Probe

**AC-WS0-3**: For each AI vendor tested (at minimum: ChatGPT, Perplexity, Claude), a real wild
fetch-then-click round trip is attempted, and the marker's survival (or failure) through that
vendor's flow is documented with a YES/NO verdict and evidence. **This AC is satisfied only by
real prod/staging-tunnel traffic from the real vendor — a lab-only pass never satisfies it
(guardrail 3).**
- proven by: wild marker-survival journal, per vendor, with dated evidence (Agent-Probe,
  needs-live-provider)
- strategy: Agent-Probe

**AC-WS0-4**: When a vendor's marker does not survive, the `/r/<token>` path-token 302 fallback is
attempted before that vendor is declared dead, and the fallback's outcome is documented.
- proven by: same wild journal as AC-WS0-3, fallback row (Agent-Probe)
- strategy: Agent-Probe

**AC-WS0-5**: At least 1 real `identified_visitors` row exists on production that is attributable
to a handoff (`agent_handoff_links`) or `ai_source` visitor — this is the program's Tier-0 exit
metric and unlocks WS3's wild kill-test window. **Verified with wild prod data only.**
- proven by: direct prod DB query, documented with the query and result count (Agent-Probe,
  needs-live-provider)
- strategy: Agent-Probe

### WS1 — AI Evaluation Timeline

**AC-WS1-1**: A new, scoped backend read endpoint returns the ordered sequence of individual
`AgentFetchEvent` rows (timestamp, page, vendor) for a given resolved company/visitor — this
endpoint does not currently exist (confirmed gap) and must be added.
- proven by: integration test hitting the new endpoint with a seeded fetch-event sequence,
  asserting correct ordering and field shape (Fully-Automated)
- strategy: Fully-Automated

**AC-WS1-2**: The visitor detail page (`apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx`)
renders a new collapsible "AI Evaluation Timeline" section, positioned near the existing "Arrived
via" pill, showing at minimum page + vendor + time per fetch event.
- proven by: Playwright e2e test seeding a visitor with fetch events and asserting the section
  renders the expected rows (Fully-Automated, subject to the existing Clerk auth-harness gap
  noted in program context — if blocked, falls back to Agent-Probe manual UI check)
- strategy: Fully-Automated (Hybrid fallback if auth-harness gap blocks it)

**AC-WS1-3**: At least 1 real company's AI-evaluation timeline, built from real wild fetch/handoff
data (not seeded/mocked), is reviewed and confirmed by a human to be readable "without further
explanation." **Verified with wild data only — this is the workstream's kill-test gate.**
- proven by: manual review journal entry citing the real company/visitor id and screenshot/export
  (Agent-Probe)
- strategy: Agent-Probe

### WS2 — Agent-driven Session Classifier

**AC-WS2-1**: A research-set combination of client-collected behavioral signals (at minimum:
`navigator.webdriver`/CDP artifacts, UA-CH `HeadlessChrome`, pointer-entropy/cadence, dead-center
clicks, form-fill timing, agentic-browser self-declared UA) is classified server-side using a
dual-signal AND-gate (mirroring the shipped `cadence-bot-flag` pattern), producing a visibility-only
label. Threshold values are finalized during this workstream's own RESEARCH step, not pre-decided
here.
- proven by: unit tests over the classifier logic with a labeled fixture set (Fully-Automated)
- strategy: Fully-Automated

**AC-WS2-2**: A self-built corpus (Playwright/CDP sessions across multiple automation modes, via
`apps/pixel/e2e/`) is correctly labeled "agent-operated" at or above the workstream's research-set
TPR threshold.
- proven by: automated corpus-replay test suite, pass/fail against the threshold
  (Fully-Automated)
- strategy: Fully-Automated

**AC-WS2-3**: False-positive rate on real, unmodified human sessions (existing human e2e fixtures
+ filtered real human production traffic, excluding known self/heavy traffic) stays under the
workstream's research-set FPR ceiling (design guidance: <=1%, final number set at RESEARCH).
- proven by: automated FPR measurement against the filtered human corpus (Fully-Automated); a
  supplementary check against real WILD production traffic is required before the label is
  trusted for any downstream decision (Agent-Probe, needs live traffic sample)
- strategy: Hybrid

**AC-WS2-4**: Manually driven, real sessions from at least one agentic browser observed in the
wild (Comet and/or Claude-in-Chrome, since OpenAI Atlas is being folded into "ChatGPT Work" and
should not be the durable target) are correctly labeled. **This AC requires real sessions from a
real agentic browser, not a scripted stand-in — lab automation alone does not satisfy it.**
- proven by: manual driven-session journal with before/after label evidence (Agent-Probe)
- strategy: Agent-Probe

**AC-WS2-5**: Zero regression in the existing `apps/pixel/e2e/` Playwright suite after the
classifier's client-side signal collection is added.
- proven by: full pixel e2e suite run, 0 new failures (Fully-Automated)
- strategy: Fully-Automated

**AC-WS2-6**: `tracker.js` stays within its research-set size budget (design guidance: <=32KB raw
/ <=12KB gzip) after the change, enforced by a CI gate.
- proven by: `wc -c` CI check against the compiled bundle, zero-dependency, hard-fails the build
  on breach (Fully-Automated)
- strategy: Fully-Automated

**AC-WS2-7**: No new network call is added by the classifier beyond the existing pixel event call
(guardrail 6) — the classifier's signal collection piggybacks on the existing event payload.
- proven by: network-call diff test asserting call count is unchanged pre/post (Fully-Automated)
- strategy: Fully-Automated

**AC-WS2-8**: The classifier ships behind a feature flag, default OFF, matching program precedent
(`agent_detection_enabled`, `cadence_bot_flag_enabled`, etc.) — never blocks or alters the visible
UX for a flagged session at any point, flag on or off.
- proven by: unit test asserting classifier output never influences rendering/redirect/blocking
  code paths + flag-off-by-default config test (Fully-Automated)
- strategy: Fully-Automated

### WS3 — Agent Concierge Kill Test

**AC-WS3-1**: MCP tools (`get_offers`, `get_pricing`, `check_availability`, or their successors)
are gated to return a structured real answer only when the caller supplies the required
qualification params (`use_case`, `company_size`, `evaluating_against`); missing params produce a
clear request-for-params response, not a silent failure or a free answer.
- proven by: integration test calling the MCP tool with/without required params, asserting the
  gated behavior (Fully-Automated)
- strategy: Fully-Automated

**AC-WS3-2**: A new zero-click conversion tool (`request_quote` and/or `book_demo`) is callable by
an MCP client and, when called with sufficient context, creates a real lead event containing the
qualification context, delivered to the site owner's inbox.
- proven by: integration test asserting a lead record + notification/email dispatch on tool call
  (Fully-Automated for the write path; Hybrid for the email-delivery leg if it depends on live
  SendGrid)
- strategy: Hybrid

**AC-WS3-3**: Every lead produced through this path resolves through the existing identity path
(WS0) to a real company wherever possible — it is not merely a tool-call log entry with no
resolvable identity.
- proven by: integration test asserting the lead event links to a resolved
  company/`identified_visitors` record when the caller's IP is resolvable (Fully-Automated)
- strategy: Fully-Automated

**AC-WS3-4**: No lead or contact record created through this path is ever automatically merged
into, or made emailable through, the existing agent-exclusion-guarded identity graph without
passing through this explicit tool/form-submission consent path (guardrail 1). The existing
`source_agent_visit_id` exclusion is never weakened or bypassed by this workstream.
- proven by: regression run of the existing `tests/unit/test_agent_origin_exclusion.py` suite
  with zero new failures, plus a new unit test asserting WS3 leads set/require explicit
  agent-provided-contact provenance (Fully-Automated)
- strategy: Fully-Automated

**AC-WS3-5**: Over a 1-week wild window on exactly one real pilot site, at least 20 real queries
via ChatGPT and/or Claude against the live MCP concierge are logged, with measured
tool-discovery rate, tool-call rate, param-fill rate, and lead-event count. **This entire AC is
satisfied only by real wild AI-agent queries — lab/simulated queries do not count toward the
20-query threshold (guardrail 3, this workstream's binary kill test).**
- proven by: wild-query journal with per-query vendor/timestamp/outcome log (Agent-Probe,
  needs-live-provider)
- strategy: Agent-Probe

**AC-WS3-6**: A signed GO/NO-GO verdict is produced from the AC-WS3-5 data: NO CALLS => the
workstream stops, journals the result, keeps the existing detection layer as the floor, and
formally recommends promoting WS2 to program priority 1. ANY CALLS => the workstream is marked as
the program's primary next-investment axis. This verdict is binary and does not admit a "partial
success, needs more time" middle state within this program's timebox.
- proven by: written GO/NO-GO report citing the AC-WS3-5 journal (Agent-Probe)
- strategy: Agent-Probe

### Program-Wide Guardrail Acceptance Criteria

**AC-G-1 (Emailability separation)**: No code path introduced by WS0-WS3 allows an agent-derived
record (`source_agent_visit_id` not null) to become emailable independent of an explicit WS3
tool/form-submission consent event.
- proven by: `tests/unit/test_agent_origin_exclusion.py` full regression, zero new failures
  (Fully-Automated)
- strategy: Fully-Automated

**AC-G-2 (Branch discipline)**: No commit in this program is pushed directly to `dev_nhantc2`. All
work merges to `main` via PR after branching off `dev_nhantc2` (for the CI fix) or working
directly on fresh branches off `main` post-merge.
- proven by: git log audit of the branches touched during EXECUTE (Hybrid — manual audit of
  automated git history)
- strategy: Hybrid

**AC-G-3 (Wild-test discipline)**: No workstream is marked "VERIFIED" in any phase report or the
umbrella status table on lab evidence alone; every VERIFIED claim cites a dated wild-evidence
journal entry.
- proven by: manual audit of each phase's closeout report against this rule at UPDATE PROCESS
  (Agent-Probe / Hybrid — human-in-the-loop process check, not machine-testable)
- strategy: Hybrid

**AC-G-4 (WS2 label-not-block)**: See AC-WS2-8 above — restated here as a program-wide guardrail
because it is non-negotiable across the whole classifier surface, present and future extensions
included.
- proven by: AC-WS2-8's test (Fully-Automated)
- strategy: Fully-Automated

**AC-G-5 (VALIDATE gate, no shortcut)**: Every schema, auth, API-contract, or billing-surface
change proposed by any workstream passes through a written validate-contract (V1-V7) before
EXECUTE begins; no such change ships via the QUICK FIX or trivial-fix lane.
- proven by: presence of a non-placeholder `## Validate Contract` section in each relevant phase
  plan before its EXECUTE step (Hybrid — structural check + human confirmation)
- strategy: Hybrid

**AC-G-6 (tracker.js safety)**: See AC-WS2-5/6/7 above — restated here as a program-wide guardrail
since it binds any future tracker.js touch in this program, not only the initial WS2 change.
- proven by: AC-WS2-5/6/7's tests (Fully-Automated)
- strategy: Fully-Automated

## Out Of Scope

- **WS4 Network Intel** as a built feature — this program delivers only a privacy-scoped
  aggregate design-note page for WS4, written at program close, with zero code, zero exit gate,
  and no phase plan.
- **"Cookie for AI agents"** — server-side AI fetchers hold no per-user identity jar; this
  pattern is an explicit dead end and will not be attempted.
- **Person-level identity from inference** — person-level identity is only ever created from
  consented self-declaration through WS3's tool-call path; no workstream infers a named
  individual from behavioral or network signals.
- **Anti-bot / blocking product** — this program does not compete with or replicate
  Cloudflare/DataDome-style blocking; WS2 labels only, per guardrail 4.
- **Rebuild of the existing EvalLayer detection floor** (`agent_classifier.py` and related) — the
  existing detection layer is treated as sufficient infrastructure and is not re-architected by
  this program.
- **F14 Web Bot Auth work** — explicitly deferred until WS0-WS3 conclude.
- **Discovery/listing mechanics for WS3's MCP tool** (e.g. getting listed in an AI vendor's Apps
  Directory) — this program's WS3 kill test self-provisions the tool via Developer Mode (the only
  fully self-serve channel identified); broader organic discoverability is a go-to-market
  dependency tracked as a known bottleneck, not something this program builds or controls.
- **Any live merge of `dev_nhantc2` -> `main`, any prod flag flip, any provider spend beyond free
  tier, or any public-site publish** without an explicit human pause — these are program hard
  stops, not autonomously executable actions, regardless of /goal autonomy.
- **Backfill of pre-existing handoff/`ai_source` visitors** — confirmed unnecessary by research
  (resolution eligibility computes fresh from current DB state every sweep); no backfill job is
  built.

## Constraints

- **The 6 locked guardrails** (verbatim from the umbrella Program Goal Charter) bind every
  workstream without exception:
  1. Emailability separation is absolute.
  2. Never push commits to `dev_nhantc2`; branch off it for CI fixes, PR to `main`.
  3. Wild-test discipline — lab pass alone never closes a phase or satisfies a survival/adoption
     claim.
  4. WS2 labels, never blocks, no UX degradation.
  5. Schema/auth/API-contract/billing changes stop at VALIDATE, no shortcut lane.
  6. `tracker.js` changes ship with e2e coverage + a bundle-size check; no new pixel network call.
- **WS0(a) is a user action, not a code task** — the GitHub Actions billing HARD STOP must be
  resolved by the user before any CI-dependent step in this program can proceed.
- **Join conditions** (from the umbrella plan, restated as hard sequencing constraints):
  - WS1 and WS2 must not begin implementation until WS0(b) (PR merge) is confirmed. WS1's own
    research/innovate/plan-supplement steps may proceed once WS0(b) is confirmed, even before
    WS0(d) (wild-survival test) completes.
  - WS2 has no dependency on WS0 or WS1 and may start its own RESEARCH step immediately, in
    parallel with WS0.
  - WS3 must not begin its wild kill-test week until WS0's exit metric (AC-WS0-5) is met.
- **OpenAI Atlas is being shut down 2026-08-09** (folded into "ChatGPT Work") — WS2's classifier
  design must not be tuned specifically to Atlas as a durable target; Comet and Claude-in-Chrome
  are the more durable references.
- **Classic automation tells decay** (navigator.webdriver, headless brand, CDP artifacts) because
  agentic browsers run real Chromium — WS2 must lean on behavioral signals (cadence, timing,
  action density) as the durable detection channel, not solely on browser-identity tells.
- **MCP discovery channels are constrained**: `/.well-known/ai-plugin.json` + OpenAPI is dead
  (deprecated April 2024) and must not be the discovery mechanism WS3 is built around; ChatGPT
  Developer Mode (user pastes a remote MCP URL) is the only fully self-serve channel available
  for this program's kill test; the Apps Directory requires opaque, multi-month OpenAI review and
  is a tracked dependency/bottleneck, not something WS3 can unblock; `llms.txt` has near-zero
  measured AI-crawler pickup as of mid-2026 and is not a credible discovery lever for this
  program.
- **Path-token `/r/<token>` 302 fallback (WS0's marker-survival fallback) must stay SEO-safe**:
  token URLs must never appear in site navigation, internal links, or the sitemap; the redirector
  must carry `rel=nofollow`/`X-Robots noindex`; the redirect must be a single fast hop (no
  chains); any long-lived token URL must be monitored for 302-to-301 drift.
- **No dedicated `/mcp/*` HTTP route was confirmed during research** — the exact MCP transport
  wiring is an open item WS3's own RESEARCH step must resolve before implementation; this SPEC
  does not assume a specific transport.
- **No per-visitor AgentFetchEvent read endpoint currently exists** — WS1 must add one; this is a
  confirmed gap, not an assumption.
- Every survival/adoption/detection acceptance criterion in this SPEC is phrased to require WILD
  prod or staging-tunnel evidence; a lab-only pass (mocked UA, synthetic corpus alone, local curl)
  is necessary supporting evidence but never sufficient to close that criterion.

## Open Questions

None remaining that block SPEC completion. The following items are **explicitly deferred to each
workstream's own RESEARCH step** (per the umbrella plan's `OPEN — research-pending` list) and are
NOT SPEC-blocking — they are implementation-detail questions, not requirements-level ambiguity:

- WS0: whether pre-merge handoff visitors need a backfill sweep (research finding above says NO,
  but each workstream's RESEARCH step re-confirms before EXECUTE).
- WS1: exact dashboard IA anchor point beyond the identified `visitors/[visitorId]/page.tsx`
  location, and the exact shape of the new read endpoint.
- WS2: final TPR/FPR thresholds, exact signal weighting, and corpus composition details.
- WS3: the exact MCP transport route/wiring, and whether the path-token redirect used by WS0's
  fallback has any SEO impact worth guarding against in WS3's context specifically.

Owner for all of the above: the respective workstream's RESEARCH step (per the umbrella plan's
7-step inner loop). No owner is "the user" for these — they are technical-discovery items.

## Background / Research Findings

**Code state (verified on `origin/dev_nhantc2`, unmerged, 30 commits ahead of `main`):**
`apps/api/services/agent_marker.py` implements a Fernet-encrypted, 7-day-TTL handoff marker
(reuses `ENCRYPTION_KEY`) with a typed fail-safe decode (absent/no_key/expired/invalid/malformed/
ok), stamped only on same-host URLs. `apps/api/routers/events.py:433-451` decodes the marker
(behind `settings.agent_marker_enabled`) and records a handoff link — this is a **separate write
path** from `ai_source` attribution, joined only at read time in `resolution_eligibility.py`,
which now bypasses the intent-score floor entirely for any AI-attributable visitor (`ai_source`
set OR handoff-linked), and orders such visitors first in the resolution queue. WS1's backend
groundwork (`agent_aggregator.py`'s `fetch_recent_ai_researched_companies()`) and models
(`agent_fetch_events`, `agent_handoff_links`) already exist; there is no per-visitor read endpoint
yet — confirmed gap. WS3's backend groundwork (`agent_gateway.py`'s 3 free GET endpoints,
`MCP_TOOLS` registry of 3 free no-param tools) exists but has no param-gated or
conversion/lead tool yet, and no confirmed dedicated `/mcp/*` HTTP route. WS2's surface
(`apps/pixel/src/tracker.js`, `agent_classifier.py`) has not been touched on the branch — the
classifier today is a deterministic UA-substring allowlist with no TPR/FPR concept; no
agent-operated label column exists yet on `Visitor`.

**Agent browser landscape (medium confidence — no primary UA/Sec-CH-UA strings captured, needs
live probe during WS2 RESEARCH):** OpenAI Atlas is being folded into "ChatGPT Work" and shut down
2026-08-09 — not a durable WS2 target. Perplexity Comet self-declares "Perplexity" in its UA but
runs full Chromium and likely does not trip `navigator.webdriver`; industry treats its UA as
non-authoritative and falls back to behavioral detection. Claude-in-Chrome is a browser extension,
not an agentic browser, and is detectable via a `web_accessible_resources` fetch probe. Across all
of these, classic automation tells decay because agents run real Chromium — behavioral detection
(cadence, timing, action density) is the durable channel.

**MCP discovery landscape (high confidence on structure):** `/.well-known/ai-plugin.json` +
OpenAPI is dead (deprecated April 2024). ChatGPT Developer Mode (paste a remote MCP URL) is the
only fully self-serve discovery channel and requires the user already knowing the URL — it is
marketing/word-of-mouth driven, not organic. The Apps Directory requires OpenAI review with an
opaque, multi-month timeline and is a tracked dependency, not something WS3 controls. `llms.txt`
has near-zero measured AI-crawler pickup as of mid-2026. The Agentic Commerce Protocol gained MCP
support 2026-04-17 and is only relevant if WS3 later pivots toward commerce/checkout (out of
current scope).

**Path-token `/r/<token>` 302 principles (high confidence on principles, inference on exact
pattern):** identical redirects for all requesters are not cloaking. SEO-safe when token URLs
never appear in nav/sitemap/internal links, the redirector carries `rel=nofollow`/`X-Robots
noindex`, the redirect is a single fast hop, and long-lived tokens are monitored for 302-to-301
drift. No 2026 case study was found citing this exact pattern — treat as informed inference, not
confirmed precedent.

**WS1 dashboard IA (verified from code):** the anchor point is the existing visitor detail page
`apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` (new collapsible section near line
867, beside the existing "Arrived via" pill) — deliberately NOT the Agents tab, which is
structurally forbidden from joining human/company data under the emailability guardrail. No
company-level route exists; `IdentifiedVisitor` is the closest available "company row." No
per-visitor endpoint returning an individual `AgentFetchEvent` sequence exists today — WS1 must
add one.

**Backfill (verified FALSE):** no backfill is needed. `resolution_eligibility` computes freshly
from current DB state on every sweep (no creation-time stamping, no seen-since cursor), so
pre-existing `ai_source`/handoff visitors are picked up automatically on the next sweep once the
merge lands. (The pre-existing 30-day no-retry cooldown is a separate, unrelated mechanism — not
something to backfill around.)

**WS2 corpus/threshold design recommendation:** reuse the shipped `cadence-bot-flag` pattern —
dual-signal AND-gate, batch-computed, visibility-only, operator-tunable threshold, default OFF.
Corpus is self-built since production agentic true-positive traffic is currently near zero (per
prior measurement): true positives from Playwright/CDP sessions across automation modes via
`apps/pixel/e2e/`; true negatives from existing human e2e fixtures plus filtered real human
production events (excluding self/heavy traffic, per prior memory finding that self-traffic
dominates several customer sites). Design guidance: FPR ceiling <=1% (looser bar is acceptable
since this is visibility-only, not a blocker); `tracker.js` size budget <=32KB raw / <=12KB gzip
enforced by a zero-dependency CI `wc -c` gate; zero pixel e2e regression required.

**Program context from `process/context/all-context.md`** (AI-Agent-Traffic Layer / AI-Referral /
Owned Identity Data Layer / Handoff Detection sections): the agent-origin exclusion guardrail
(`source_agent_visit_id` hard-excludes a record from `is_emailable_identity`) is regression-tested
in `tests/unit/test_agent_origin_exclusion.py` and is the program's highest-priority guardrail to
never weaken. `ai_source` and handoff-linking are structurally separate write paths that only join
at read time. All of `agent_detection_enabled`, `company_graph_enabled`, `identity_signals_enabled`
etc. default OFF in this codebase's established pattern, which this program's new flags (marker
flag, WS2 classifier flag, WS3 gating flags) must follow. 12 migrations are already pending live
production apply from prior work — this program's own schema changes (if any survive VALIDATE)
would extend that same pending chain and require re-confirming `alembic heads` immediately before
any live apply, per the documented migration-collision precedent.
