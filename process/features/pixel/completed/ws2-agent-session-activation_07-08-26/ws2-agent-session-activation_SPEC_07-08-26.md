---
name: spec:ws2-agent-session-activation
description: "Requirements for closing Beam's agentic-browser blindspot — activate the dormant WS2 classifier by restoring bounded client-side signal collection and settling the emailability-tier decision"
date: 07-08-26
feature: pixel
---

# WS2 Agent-Session Activation — SPEC

## Summary

Right now, when someone (or something) visits a Beam customer's site using an automated browser
— Playwright, Selenium, Puppeteer, or the kind of automation stack that products like Browser Use
build on — one of two things happens, and both are bad. Either the pixel goes completely silent
(the tracker's very first line of code checks `navigator.webdriver` and exits before anything else
runs — no cookie, no consent check, no data at all), or, if the automation doesn't set that one
flag, the visit is recorded as an ordinary human. In the second case it's worse than invisible: the
session consumes the customer's paid identity-resolution and enrichment budget, and it can enter
their outreach/campaign targeting pool as if it were a real lead. A classifier that could catch the
second case (`ws2_session_classifier.py`) was already built, tested, and shipped to a branch — but
it was deliberately left non-functional, because the one thing it needs to work (a small client-side
signal called `agent_sig`) was pulled out of the pixel during a previous project for size-budget
reasons. This SPEC defines what it means to finish that work: put a small, budget-safe version of
that signal back in the pixel, store it, and decide — explicitly, as a product decision, not a
default — whether an agent-flagged session should be hidden from outreach or just labeled.

## User Stories / Jobs To Be Done

- As a **Beam customer (site owner)**, I want to know when a visitor on my dashboard was actually
  an automated browser, so that I don't spend my identity-resolution budget chasing a bot and don't
  mistake it for a real lead.
- As a **Beam customer**, I want my identity-resolution and enrichment budget spent on real people,
  so that automated/agentic traffic doesn't quietly eat into a metered, paid resource with a daily
  cap.
- As a **Beam customer**, I do NOT want a real human visitor — including one using accessibility
  tooling, a privacy-hardened browser, or a corporate testing proxy — to be silently deleted from my
  leads or outreach list because of a detection false positive. I want to understand, upfront, how
  confident this signal is before it affects who I can email.
- As the **Beam operator (founder)**, I want the pixel's automated-browser blindspot (the
  `navigator.webdriver` early-return) closed without breaking the existing 6KB gzip size gate, so
  that fixing this doesn't regress an already-tight, already-tested budget.
- As the **Beam operator**, I want the existing product stance — classify, don't silently drop — to
  be honored here the same way it is everywhere else in the codebase (EvalLayer, cadence-bot-flag),
  so that this fix doesn't quietly reintroduce a blocking/dropping behavior the product has
  deliberately avoided elsewhere.
- As the **Beam operator**, I want the emailability-tier question (hard-exclude vs. visibility-only)
  answered as an explicit, documented decision — not left to whoever implements this — because no
  existing code answers it and getting it wrong in either direction has a real cost (wasted budget
  vs. deleted real leads).

## What The User Wants (Behavioral Outcomes)

- **The pixel no longer goes completely dark for every automated browser.** Today, ANY session with
  `navigator.webdriver === true` produces zero tracking data — no visit is ever recorded, not even
  as an unlabeled or flagged one. After this work, such a session is recorded (subject to the same
  consent gate every other session goes through) and carries a signal that downstream classification
  can use.
- **A previously-invisible-and-uncounted agentic session is now visible to the site owner as
  "agent-operated"** on the same kind of surface the site owner already sees other traffic-quality
  signals on (e.g. the existing `ai_source` "Arrived via" pill, or the cadence-bot-flag precedent's
  visitor badge) — not a new page, not a support request.
- **The signal collection added to the pixel stays inside the existing, already-enforced size
  budget.** The tracker does not silently grow past its current tested gzip-size gate. Whatever
  signal is restored is deliberately smaller/trimmed compared to what was reverted before, because
  the budget is tighter than it was when the original signal was designed.
- **No session is dropped, blocked, or CAPTCHA'd because of this classification.** Matching the rest
  of the codebase's stance (EvalLayer, cadence-bot-flag): label, never silently discard. A flagged
  session still produces a row; it is never turned into a 403, a dropped request, or a blocked pixel
  load.
- **The consent gate is respected.** Whatever new signal collection is added runs on the same side
  of the existing EU consent hold as every other piece of tracker data — it never fires before
  consent is resolved.
- **The emailability question has one clear, stated answer, not an implicit default.** Whichever
  tier is chosen (hard-exclude or visibility-only), the SPEC states it explicitly, states why, and
  states what a site owner should expect as a result. This is the single most consequential
  decision in this SPEC — see Acceptance Criteria AC-8 and the two-sided rationale under
  Constraints.

## Flow / State Diagram

```
                        Visitor's browser loads the pixel script
                                          |
                                          v
                    +------------------------------------------+
                    |  tracker.js bootstrap (BEFORE this work)   |
                    |  if (navigator.webdriver === true) return; |
                    |  <-- everything below this line never runs |
                    +------------------------------------------+
                                          |
                          (AFTER this work — see AC-1, AC-2)
                                          v
                    +------------------------------------------+
                    |  Bootstrap continues regardless of         |
                    |  navigator.webdriver — a bounded, trimmed  |
                    |  agent_sig collector runs alongside normal  |
                    |  fingerprint collection, AFTER the consent  |
                    |  gate (G7 — never before)                   |
                    +------------------------------------------+
                                          |
                                          v
                    +------------------------------------------+
                    |  Event payload includes agent_sig           |
                    |  (small, size-budgeted; webdriver flag +    |
                    |  UA-CH HeadlessChrome + trimmed behavioral   |
                    |  bits — exact shape is a PLAN decision)       |
                    +------------------------------------------+
                                          |
                                          v
                    +------------------------------------------+
                    |  Ingest (events.py) persists agent_sig       |
                    |  on the event row (additive column/field)    |
                    +------------------------------------------+
                                          |
                                          v
                    +------------------------------------------+
                    |  ws2_session_classifier.py sweep reads real  |
                    |  agent_sig (no longer always None)            |
                    |  Stage 1: deterministic (webdriver/UA-CH)     |
                    |  Stage 2: behavioral AND-gate                 |
                    +------------------------------------------+
                                          |
                              Session classified agent-operated?
                                          |
                    +---------------------+----------------------+
                    | NO                                          | YES
                    v                                              v
        +------------------------+          +----------------------------------------+
        | Visitor/session          |          | is_agent_operated flag set              |
        | unchanged — normal        |          | (or equivalent) — VISIBLE on dashboard   |
        | human traffic flow         |          |                                          |
        +------------------------+          | THIS SPEC FORCES A DECISION (AC-8):      |
                                                |  (a) Hard-exclude — behaves like         |
                                                |      source_agent_visit_id: never         |
                                                |      emailable, never in outreach pools    |
                                                |  OR                                        |
                                                |  (b) Visibility-only — behaves like        |
                                                |      is_bot_suspect: fully emailable,      |
                                                |      fully counted, badge only             |
                                                |                                            |
                                                | Session is NEVER dropped, blocked, or       |
                                                | CAPTCHA'd either way (see Behavioral        |
                                                | Outcomes)                                   |
                                                +----------------------------------------+
```

## Acceptance Criteria (Testable Outcomes)

**AC-1 — Automated browsers no longer produce zero tracking data.**
A session with `navigator.webdriver === true` no longer causes the tracker to exit before
`document.currentScript` is evaluated. Bootstrap continues (cookie/consent/event flow proceeds
normally, gated by the same consent logic every other session goes through).
`proven by:` unit test in the pixel test suite asserting the tracker's bootstrap does not
short-circuit purely on `navigator.webdriver === true`, and that consent gating (`GATED`/
`consentDecision`) still applies identically regardless of the webdriver flag.
`strategy:` Fully-Automated.

**AC-2 — The `agent_sig` signal is collected client-side, after the consent gate, within the
existing pixel size budget.**
A trimmed `agent_sig` value (containing at minimum the `navigator.webdriver` boolean; UA-CH
`HeadlessChrome` detection and/or other deterministic markers as budget allows) is computed and
attached to outgoing event payloads. Collection code is placed strictly AFTER the existing
consent-gate block (tracker.js Hard Guardrail G7 — never bypass the EU consent hold), matching the
first-party-capture-expansion precedent's own VALIDATE-found ordering hazard fix.
`proven by:` (1) unit test asserting `agent_sig` collection code executes only after
`consentDecision`/`GATED` resolution; (2) the existing gzip-size gate
(`tests/unit/test_pixel_fingerprint.py::TestPixelSizeLimit::test_under_6kb_gzipped`, binding at
`< 6000` bytes, and the looser `< 6144` gate in `tests/unit/test_pixel.py`) continues to pass with
the new code included. `strategy:` Fully-Automated.

**AC-3 — The pixel size budget is never exceeded.**
`apps/pixel/src/tracker.min.js` gzip size after this change stays under both existing size gates.
The `agent_sig` collector is deliberately smaller than the previously-reverted implementation — the
available headroom (308B gzipped as of this SPEC session, measured against the binding `<6000`
gate) is the hard ceiling for the new code's contribution, not a target to fully consume.
`proven by:` `test_under_6kb_gzipped` and `test_pixel.py`'s size gate, both re-run and green after
the change; a stated actual gzip byte count recorded in the implementation's phase report.
`strategy:` Fully-Automated.

**AC-4 — `agent_sig` is persisted at ingest, not silently dropped.**
`events.py` accepts and stores the new `agent_sig` field on the event row (additive schema change:
new column/field, following the `is_agent_operated`/`is_bot_suspect` additive precedent). The field
survives a full ingest round-trip and is readable by downstream code.
`proven by:` integration test posting an ingest payload containing `agent_sig` and asserting the
persisted event row contains the same value. `strategy:` Fully-Automated (Docker-gated integration
tier, consistent with existing ingest integration tests).

**AC-5 — `ws2_session_classifier.py`'s sweep classifies real, non-null `agent_sig` data.**
`_extract_agent_sig()` (or its replacement) returns real signal data instead of unconditionally
`None`. Stage 1 (deterministic: webdriver/UA-CH) and Stage 2 (behavioral AND-gate) both operate on
real persisted values for sessions that submitted `agent_sig`.
`proven by:` unit test asserting the sweep extracts and classifies against a fixture event row with
a populated `agent_sig` field (not a `None` short-circuit). `strategy:` Fully-Automated (extends the
existing `test_ws2_session_classifier.py` quadrant-matrix suite).

**AC-6 — Classification is visible to the site owner, not silent.**
A session/visitor classified as agent-operated is surfaced on the dashboard (visitor detail and/or
list view), following the existing `ai_source`/cadence-bot-flag badge precedent — not a new page,
not an export-only field.
`proven by:` component test rendering a visitor/session fixture with the classification set,
asserting a badge/indicator is present; absent when unset. `strategy:` Hybrid (component render is
Fully-Automated; full Playwright auth-harness leg is Agent-Probe, matching the repo-wide Clerk
auth-harness gap already tracked for cadence-bot-flag AC-8/AC-9 and site-id-lifecycle AC-6).

**AC-7 — No session is dropped, blocked, or CAPTCHA'd as a result of this classification.**
Classifying a session as agent-operated never causes `POST /ingest` to reject the request, never
returns a non-2xx specifically because of the classification, and never triggers a CAPTCHA or block
at any layer this SPEC touches. Matches the repo-wide "classify, don't drop" stance
(`docs/agent-detection-architecture.md` §1).
`proven by:` integration test asserting ingest of a payload with agent-indicating `agent_sig` still
returns success and the event/visitor row is written. `strategy:` Fully-Automated.

**AC-8 — The emailability tier is an explicit, stated product decision — not a default.**
The classification's effect on `is_emailable_identity()` is EITHER (a) hard-exclude, matching the
`source_agent_visit_id` pattern (session/visitor structurally excluded from outreach, same as
EvalLayer agent visits), OR (b) visibility-only, matching the `is_bot_suspect` pattern (flag set,
`is_emailable_identity()` unaffected, session remains fully emailable and fully counted). This
SPEC does not pre-select the tier — that decision is deferred to INNOVATE/PLAN as an explicit,
named decision point, informed by the two-sided rationale below (see Constraints). Whichever tier
is chosen, it must be implemented consistently: if hard-exclude, `is_emailable_identity()` and its
3 known call sites must treat the new signal the same way `source_agent_visit_id` is treated today;
if visibility-only, none of `is_emailable_identity()`'s guard parameters may read the new flag.
`proven by:` a new regression test — mirroring `tests/unit/test_agent_origin_exclusion.py` (if
hard-exclude is chosen) or mirroring cadence-bot-flag's AC-6 pattern (if visibility-only is chosen)
— asserting `is_emailable_identity()` behaves exactly as the chosen tier specifies for a
WS2-classified visitor, at all 3 existing call sites (`campaign_sender.py`, `csv_exporter.py`,
`routers/campaigns.py`). `strategy:` Fully-Automated.

**AC-9 — Absence-of-negative-test gap closed: existing visibility-only flags do not leak into
emailability.**
Regardless of which tier AC-8 selects for the NEW WS2 flag, add the previously-missing regression
test asserting the two EXISTING visibility-only flags (`Visitor.is_bot_suspect` /
`IdentifiedVisitor.is_bot_suspect` from cadence-bot-flag, and WS2's own `is_agent_operated` flag as
defined on the unmerged branch) do NOT trip `is_emailable_identity()`. This closes a gap identified
during this SPEC's research: no such test currently exists.
`proven by:` unit test constructing an `IdentifiedVisitor` with `is_bot_suspect=True` and/or
`is_agent_operated=True` and asserting `is_emailable_identity()` returns the same result as an
otherwise-identical visitor without those flags set. `strategy:` Fully-Automated.

**AC-10 — Migration re-chains cleanly onto the live current head.**
Any new column/migration this work introduces (the `agent_sig` event column, and WS2's own
`f4c1a9e2d3b8_add_ws2_agent_operated_flag.py` currently orphaned on the unmerged branch) is
re-chained onto the TRUE live `alembic heads` output at merge/implementation time — not the stale
`f1a7c3e05b92` referenced in this SPEC session, which will itself be superseded by concurrent work
before this ships.
`proven by:` `alembic -c apps/api/alembic.ini heads` returns a single head immediately before any
migration is authored or merged; offline `--sql` validation of the new migration(s) passes.
`strategy:` Fully-Automated (offline validation) with a Known-Gap for live round-trip (see AC-12).

**AC-11 — Mock mode works end-to-end.**
With `MOCK_EXTERNAL_APIS=true`, the full path (client-side signal → ingest → classification sweep)
runs deterministically without any live external dependency. (This AC exists for consistency with
repo-wide mock-mode policy; WS2's classification logic has no external provider calls today, so
this is expected to be a no-op confirmation, not new mock-branch code.)
`proven by:` unit/integration tests pass with `MOCK_EXTERNAL_APIS=true` set, no test skips due to
missing external credentials. `strategy:` Fully-Automated.

**AC-12 — Known-Gap: live Playwright/CDP corpus true-positive rate.**
Whether real Playwright/Selenium/Puppeteer/CDP-driven sessions actually trip the restored
`agent_sig` signal and get classified correctly cannot be proven by synthetic unit fixtures alone.
`proven by:` a documented post-implementation verification step driving a real Playwright (or
equivalent) browser against a test site and confirming the resulting session is classified
agent-operated. `strategy:` Agent-Probe / Known-Gap — this was blocked pre-activation per the WS2
backlog note and remains blocked on `agent_sig` actually existing; only provable after this SPEC's
work ships.

**AC-13 — Known-Gap: false-positive rate on real human fixtures (accessibility tooling, privacy
browsers, corporate testing proxies).**
Whether legitimate non-agent tooling (screen readers, automated QA proxies run by real companies
against their own sites, privacy-hardened browsers that may report unusual UA-CH values) trips a
false positive cannot be fully proven synthetically.
`proven by:` a documented lab-corpus check (real human browser fixtures, including at least one
accessibility-tooling and one privacy-browser sample) run against the classifier post-activation,
asserting no false-positive flags. `strategy:` Agent-Probe / Known-Gap.

**AC-14 — Known-Gap: live wild-session validation (Comet / Claude-in-Chrome / similar agentic
browser products).**
Whether a real agentic-browser product session (not a raw Playwright/Selenium script) is correctly
classified is not scriptable in CI and depends on an assumption — that such products set
`navigator.webdriver=true` by default — that this SPEC's research could not independently verify
(sourced from WS2's own design docs, never re-probed live).
`proven by:` a documented live wild-session check (before/after evidence) run manually against a
real automated-browser-product session once this work ships. `strategy:` Agent-Probe — needs a live
automated-browser session, not scriptable in CI.

## Out Of Scope

- **Merging the WS2 branch's billing/prod-env WS0 ops-gate runbook** (commit `c2f9bad` on
  `feat/ws2-agent-session-classifier`, content unread during this SPEC's research). Deliberately
  deferred — separate concern from closing the detection blindspot.
- **F14 Web Bot Auth / RFC 9421.** A separate, larger opportunity identified during research;
  explicitly not part of this activation work.
- **MCP `initialize`/`clientInfo` protocol-shape identification.** A different detection surface
  (agent-facing gateway self-identification) from the browser-session detection this SPEC covers.
- **Agent session tracing** (correlating a classified session across multiple page loads into a
  narrative trace). Not required to close the blindspot or activate WS2's existing classifier.
- **Cloudflare bot-score piggybacking** (using CF's own bot-management score as an additional
  signal). A candidate future signal source, not required for this activation.
- **Restoring the FULL previously-reverted client-side signal set.** The prior signal was pulled
  for size-budget reasons; this SPEC requires a deliberately TRIMMED subset that fits the current
  (tighter) budget — restoring everything that existed before is explicitly not the goal.
- **Any new blocking, dropping, rate-limiting, or CAPTCHA behavior triggered by classification.**
  Matches the cadence-bot-flag precedent's Out Of Scope — labeling only.
- **Datacenter-ASN or crawl-shape signals as new inputs to WS2.** Out of scope for this activation;
  WS2's existing two-stage design (deterministic + behavioral AND-gate) is unchanged by this SPEC.
- **Changing `is_abuse_flagged` semantics or `visitor_aggregator.py`'s existing FILTER exclusions.**
  This SPEC's classification is independent of the flood/abuse detection layer.
- **A dedicated new operator-facing analytics endpoint or dashboard panel beyond the per-session/
  per-visitor badge.** Matches the cadence-bot-flag precedent — a badge on existing visitor surfaces
  is the minimal v1 surface; a dedicated aggregate rollup view is a candidate future SPEC.

## Constraints

- **Pixel size budget is hard.** Binding gate: `tests/unit/test_pixel_fingerprint.py`
  `test_under_6kb_gzipped` (`< 6000` bytes gzip). Secondary gate: `tests/unit/test_pixel.py`
  (`< 6144`). Current `tracker.min.js` = 5692B gzip / 13378B raw — **308B of headroom**. This number
  is a measured snapshot from this SPEC session and may shift slightly by implementation time;
  re-measure before committing to a signal shape in PLAN.
- **Consent ordering (Hard Guardrail G7) is non-negotiable.** New signal collection must be placed
  strictly after the existing `GATED`/`consentDecision` block (tracker.js:501-504) — this is a
  previously VALIDATE-found hazard (see inline comment tracker.js:517-520) and must not be
  reintroduced. GPC/DNT → `do_not_resolve` sticky behavior must be preserved unchanged.
- **Migration chain is a moving target.** Live single head at SPEC time is `f1a7c3e05b92`
  (add_fingerprint_v3), but this codebase has a documented history of concurrent-program migration
  collisions. Any new migration MUST re-verify `alembic heads` live immediately before authoring —
  never hardcode a planned head. WS2's own orphaned migration
  (`f4c1a9e2d3b8_add_ws2_agent_operated_flag.py`) needs re-chaining at merge time, not assumed to
  chain onto its original parent.
- **The emailability-tier decision (AC-8) has two legitimate sides — both must be weighed, not
  defaulted:**
  - **Argument for hard-exclude:** agentic-browser sessions currently burn paid identity-resolution
    and enrichment budget and can pollute campaign-targeting pools with non-human "leads." Excluding
    them protects the customer's budget and outreach quality, matching the precedent already set for
    EvalLayer's `source_agent_visit_id` (self-declaring AI agents are structurally never
    outreach-eligible).
  - **Argument for visibility-only:** the detection signal (client-reported `navigator.webdriver` /
    UA-CH + a trimmed behavioral heuristic) is inherently less certain than EvalLayer's UA-string
    self-declaration — it can false-positive on real humans using accessibility tools, privacy
    browsers, or legitimate automated QA run by the customer's own team against their own site.
    Silently deleting those from outreach is an irreversible, invisible harm to the customer's real
    pipeline, matching the exact rationale cadence-bot-flag used to reject hard-exclusion for its
    own (also heuristic, also imperfect) signal.
  - This SPEC does not resolve the tension — it requires INNOVATE/PLAN to pick one tier explicitly,
    document the choice and its rationale in the Decision Summary, and implement it consistently
    (AC-8).
- **Brand/product stance: classify, never drop.** `classify_agent()` runs before `is_bot()`
  repo-wide; this work must not introduce a new blocking or dropping path (AC-7).
- **Mock mode required** for the full pipeline under `MOCK_EXTERNAL_APIS=true` (AC-11) — though no
  new external provider call is anticipated for WS2's own classification logic.
- **Feature flag default OFF**, matching `agent_detection_enabled` / `cadence_bot_flag_enabled` /
  WS2's own existing flag precedent. Enabling in a real environment is an explicit human operator
  action, not an automatic consequence of shipping this work.
- **No PII in any new log line** — counts, ids, and computed signal values only, matching the
  repo-wide guardrail already enforced for `ingest_velocity.py` and `cadence_bot_flag`.

## Open Questions

None blocking this SPEC's lock. The following are explicitly deferred to INNOVATE/PLAN because they
affect *how*, not *what*, or because this SPEC's job is to force the decision to be made
explicitly rather than to make it itself:

- **Which emailability tier (AC-8) is chosen: hard-exclude or visibility-only?** This SPEC requires
  the decision be explicit and documented — see Constraints above for the two-sided rationale — but
  deliberately does not pre-select it. INNOVATE must resolve this as a named Decision Summary item
  before PLAN begins.
- **Exact `agent_sig` field shape/serialization** (which specific bits fit inside the 308B
  headroom — e.g. webdriver boolean + UA-CH HeadlessChrome only, vs. also including a minimal
  pointer-entropy or click-pattern proxy for Stage 2). A PLAN-level trade-off between signal
  richness and byte budget, not a requirements question.
- **Whether the WS2 branch is merged wholesale or its classifier/migration are cherry-picked/
  re-authored against current main.** An INNOVATE-level implementation-path question; either
  approach satisfies this SPEC's acceptance criteria.
- **`navigator.webdriver=true`-by-default assumption for agentic-browser products (Comet,
  Claude-in-Chrome, etc.)** is unverified (see AC-14) and carried forward as a Known-Gap rather than
  resolved here — this SPEC does not require the assumption to be confirmed before PLAN/EXECUTE,
  only that it be tracked and probed post-ship.

## Background / Research Findings

Verified findings from this session's RESEARCH phase (treated as ground truth):

- **Problem 1 — total blindspot.** `apps/pixel/src/tracker.js:4` — `if (navigator.webdriver ===
  true) return;` — is the tracker's first executable statement, before `document.currentScript`
  (line 5). It aborts the entire bootstrap: no cookie read, no consent gate
  (`GATED`/`consentDecision`, tracker.js:501-504), no `pagehide` beacon listener (tracker.js:238,
  :702), no flush. There is no other exit path. Every agentic browser that sets
  `navigator.webdriver=true` (the Playwright/Selenium/Puppeteer/CDP default) is erased silently.
- **Problem 2 — silent miscounting, worse than blindness.** An agentic session that does NOT set
  `navigator.webdriver` and carries a normal Chrome UA has no UA-string tell.
  `apps/api/services/bot_filter.py`'s `_BOT_PATTERN` (L9-25) only matches literal
  `playwright|webdriver|cypress|selenium|puppeteer|headless` tokens, so such a session passes both
  `classify_agent()` and `is_bot()` and is persisted as an ordinary unlabeled human — consuming
  identity-resolution/enrichment budget and entering campaign targeting pools.
- **Problem 3 — WS2 solves 0% of this today.** `apps/api/services/ws2_session_classifier.py`
  exists on unmerged branch `feat/ws2-agent-session-classifier` (commits `5d4cf02`, `560fe53`,
  `24448cd`, `c2f9bad`), EVL-green and unit-tested (`tests/unit/test_ws2_session_classifier.py`,
  349-line quadrant matrix; `tests/unit/test_ws2_zero_import.py` structural rule), framed as "the
  sixth, orthogonal detection layer." Stage 1 = deterministic fast-path
  (`navigator.webdriver`/UA-CH `HeadlessChrome`). Stage 2 = behavioral AND-gate (low pointer
  entropy AND high dead-center-click rate), mirroring `cadence_bot_flag.py`'s
  precondition-before-ratio pattern. It is inert because — quoting the phase report verbatim —
  "the client-side signal collection that would feed the classifier (`agent_sig`) was reverted
  during EXECUTE for size-budget and non-persistence reasons — so the sweep currently flags
  nobody." `_extract_agent_sig()` unconditionally returns `None`. WS2's own docstring notes Stage 1
  can never fire in production because `tracker.js:4` already early-returns first — Stage 1 is
  defense-in-depth proven only at unit tier; Stage 2 is the only stage that can close the gap.
- **The 3 activation items** (verbatim from
  `process/features/agent-native-revenue/backlog/ws2-activation-persistence_NOTE_30-07-26.md` on
  the WS2 branch): (1) restore client-side signal collection under the real budget, trimming the
  signal set; (2) add an `events.agent_sig` column + migration, additive-only, mirroring
  `is_agent_operated`; (3) persist `agent_sig` at ingest in `events.py`, wiring the schema field
  through so the sweep's `_extract_agent_sig()` reads real data.
- **Hard constraints, re-measured live this session (supersede the stale WS2 backlog note
  figures):** pixel size budget = 308B gzipped headroom remaining against the binding `<6000` gate
  (current `tracker.min.js` = 5692B gzip / 13378B raw; the WS2 note's "5000B ceiling / 135B
  headroom" is stale — fingerprint-v3 work raised it). Consent ordering (G7) — tracker.js:501-504
  sets `GATED`/`consentDecision`; any new signal placed before it bypasses the EU consent hold.
  Migration chain — live single head `f1a7c3e05b92` (add_fingerprint_v3) at SPEC time, chaining off
  `e9d2a4c71f68`; WS2's own migration will need re-chaining at merge.
- **Emailability guardrail precedent.** `is_emailable_identity()` in
  `apps/api/services/identity_resolver.py` hard-excludes on `source_agent_visit_id is not None`
  (regression-tested `tests/unit/test_agent_origin_exclusion.py`). Two existing visibility-only
  flags — `Visitor.is_bot_suspect`/`IdentifiedVisitor.is_bot_suspect` (cadence-bot-flag,
  `apps/api/models/visitor.py:105,175`) and WS2's `is_agent_operated` — are deliberately NOT wired
  into that exclusion today. No existing code decides which tier a WS2-classified session belongs
  to; this SPEC forces that decision (AC-8).
- **Brand stance.** `docs/agent-detection-architecture.md` §1: `classify_agent()` runs before
  `is_bot()` — label, don't block, across the whole codebase. A fix that widens dropping would be a
  regression of product thesis.
- **Structural precedent used for this SPEC's shape:** `process/features/pixel/active/
  cadence-bot-flag_26-07-26/cadence-bot-flag_SPEC_26-07-26.md` — closest prior art for a
  behavioral, visibility-first, flag-default-OFF detection layer that explicitly had to resolve the
  same "flag vs. outreach eligibility" tension this SPEC re-raises for a different signal source.
- **Test tiers carried forward as Known-Gaps:** AC-WS2-2 (Playwright/CDP corpus true-positive
  rate) and AC-WS2-3 lab leg (false-positive rate on human fixtures) are blocked until `agent_sig`
  persistence lands — captured here as AC-12 and AC-13. AC-WS2-4 (real Comet/Claude-in-Chrome wild
  session, before/after evidence) is Agent-Probe tier — captured as AC-14. The absence of a test
  asserting `is_bot_suspect`/`is_agent_operated` do not trip `is_emailable_identity()` is closed as
  AC-9.
- **Unverified assumption, explicitly flagged (not re-probed this session):** whether Comet /
  Claude-in-Chrome actually set `navigator.webdriver=true` by default. Sourced from WS2's own design
  docs only. Carried forward as part of AC-14's Known-Gap framing, not treated as confirmed fact.

---

## Strategy Recommendation for INNOVATE

**Recommended: Sequential, single `vc-innovate-agent` (sonnet).** The two real design decisions
here — the emailability tier (AC-8) and the exact `agent_sig` byte-budget shape — are tightly
coupled (the tier choice affects how much confidence the signal needs to carry, which affects how
many bits are worth spending) and touch a small, well-bounded set of files
(`tracker.js`, `events.py`, `identity_resolver.py`, `ws2_session_classifier.py`, one migration). A
single INNOVATE pass comparing "cherry-pick/re-author WS2's classifier against current main" vs.
"merge the WS2 branch wholesale," and resolving the tier + signal-shape questions together, is
sufficient. No independent investigation branches exist that would benefit from parallel fan-out.

Alternatives considered: **parallel subagents** (rejected — the emailability-tier decision and the
signal-shape decision are interdependent, not independent investigation branches, so splitting them
across agents risks incoherent output); **vc-team** (rejected — no adversarial debate or
cross-file coordination need beyond what a single agent can reason through; this mirrors
cadence-bot-flag's own INNOVATE recommendation); **workflow/dynamic agent()** (rejected — no
repeated sub-task shape to template).

---

**Status:** DONE
**Summary:** WS2 Agent-Session Activation SPEC written at
`process/features/pixel/active/ws2-agent-session-activation_07-08-26/ws2-agent-session-activation_SPEC_07-08-26.md`
— 14 numbered ACs (all `proven by:`/`strategy:` tagged; AC-12/13/14 explicit Known-Gap/Agent-Probe
tiers carried forward verbatim from the task brief), problem statement framed in customer/business
terms, the emailability-tier decision forced as AC-8 with both sides of the rationale stated under
Constraints and deliberately left unresolved for INNOVATE, 5 named Out-Of-Scope exclusions from the
task brief plus 5 additional exclusions matching repo precedent, migration/size-budget/consent-order
constraints carried forward with the live-measured 308B figure, strategy recommendation (sequential
single sonnet agent) included.
**Concerns/Blockers:** None blocking SPEC lock. All Open Questions are explicitly deferred
implementation-shape or Known-Gap items, not blockers — the one requirement this SPEC insists on is
that AC-8's tier choice be made explicitly in INNOVATE's Decision Summary, not defaulted silently.

PHASE_COMPLETE: SPEC — process/features/pixel/active/ws2-agent-session-activation_07-08-26/ws2-agent-session-activation_SPEC_07-08-26.md written. Proceed to INNOVATE.
