---
name: spec:cadence-bot-flag
description: "Requirements for behavioral (non-UA) detection of stealth crawlers that evade every existing UA-based bot layer, without silently un-emailing real contacts who also run bots"
date: 26-07-26
feature: pixel
---

# Cadence Bot Flag — SPEC

## Summary

A real site owner has an identified visitor in their dashboard — a real person, a real email, a
stable visitor id, marked "Returning" — who is actually a bot crawling the site once a day. Every
bot defense Beam has today (`tracker.js` webdriver check, `bot_filter.py` UA regex,
`agent_classifier.py` self-declaring vendor list, `ingest_velocity.py` flood detector) only catches
bots that either announce themselves or attack in bulk. A single polite daily crawl with a
convincing browser user-agent sails past all four, because none of them look at *behavior over
time* — they look at identity strings or short-window traffic shape. This SPEC defines a new,
behavior-based signal that catches that gap: it looks at how a visitor's visits are spaced and
whether they ever do anything a script wouldn't bother faking (scrolling, clicking, spending real
time on a page). Critically, this SPEC also settles a product tension the motivating case exposes
head-on: the visitor in question is a REAL, wanted contact who also happens to run a bot against the
site. The system must be able to say "this looks automated" for analytics purposes without
silently making that person un-emailable or invisible to outreach — that would be actively harmful
to the business, not protective.

## User Stories / Jobs To Be Done

- As a **site owner**, I want to see which of my "identified visitors" are actually behaving like a
  script (visiting on a rigid schedule, never scrolling or clicking), so that I can tell my real
  human traffic apart from automated noise when I'm deciding who to reach out to.
- As a **site owner**, I want a bot-suspect flag to be informational, not a silent gate, so that a
  real contact who happens to run a monitoring bot against my site doesn't get quietly dropped from
  my outreach list without my knowledge.
- As the **Beam operator (founder)**, I want a detection signal that works retroactively over
  existing event history, so that I don't have to wait weeks for a new client-side probe to
  accumulate data before the motivating case (a crawler active for weeks already) can be caught.
- As the **Beam operator**, I want this signal computed in a batch/background pass rather than on
  the write-hot ingest path, so that adding cadence analysis never slows down or destabilizes
  `POST /ingest`.
- As the **Beam operator**, I want the new flag kept structurally distinct from `is_abuse_flagged`
  (the existing DDoS/flood flag) and from `agent_visits` (the existing self-declaring-AI-agent
  table), so that three different phenomena — "flood attack," "self-declaring AI crawler," and
  "stealth cadence bot" — don't get collapsed into one meaning and don't inherit each other's side
  effects (especially `is_abuse_flagged`'s hard exclusion from analytics and outreach).
- As a **site owner**, I want to see the flag on the visitor's profile the same way I already see
  "Arrived via ChatGPT," so that reviewing a suspicious visitor doesn't require a new page or a
  support request.

## What The User Wants (Behavioral Outcomes)

- **A visitor whose visit timing looks scripted (near-zero variance in the gap between visits) AND
  whose sessions never contain real engagement (no scroll, no click, no meaningful time-on-page —
  pageviews only) is flagged as bot-suspect.** Both conditions are required together — see Flow
  diagram and AC-3 — matching the existing dual-condition philosophy already used by
  `ingest_velocity.py` to avoid false positives.
- **The flag is visibility-only in v1.** It must NOT: set `is_abuse_flagged` or `do_not_resolve`; be
  read by `is_emailable_identity()`; exclude the visitor from any existing dashboard metric
  aggregate (the `FILTER (WHERE NOT is_flagged_abuse)` pattern in `visitor_aggregator.py`). A
  flagged visitor is exactly as emailable, exactly as counted, and exactly as visible in every
  existing view as before — the ONLY new thing is a badge saying "this looks automated."
- **Detection runs as a batch/background pass over existing event history**, not as a new check on
  the write-hot `POST /ingest` path. It must be able to catch a crawler that has already been active
  for weeks, using rows already in the `events` table today.
- **Thresholds are operator-tunable, not hardcoded** — matching the `ingest_velocity_*` /
  `site_ingest_limit_*` config precedent (env-driven, default OFF, explicit rollout note).
- **The flag is visible on the same visitor surfaces the `ai_source` "Arrived via" pill already
  uses** (visitor detail page + visitor list), so a site owner reviewing a visitor sees it without
  a new page or export.
- **Nothing here overlaps with `agent_visits` (EvalLayer) or `is_abuse_flagged` (ingest-abuse-hardening).**
  A self-declaring AI crawler (GPTBot, PerplexityBot) is already routed to `agent_visits` and
  structurally excluded from `Visitor`/`IdentifiedVisitor` entirely — this SPEC's target is a
  *stealth* crawler that never declares itself and therefore never reaches that path. A flood
  attacker is already caught (when detected) by `is_abuse_flagged` — this SPEC's target is the
  opposite traffic shape: one visitor, low volume, sustained over days/weeks.
- **No new client-side probe, no CAPTCHA, no blocking, no auto-suppression.** This SPEC only adds a
  read signal to existing data — it never changes what the pixel does or what happens to a request
  at ingest time.

## Flow / State Diagram

```
                    Existing events table (per visitor, per site)
                    pageview | utm_identify | form_email_capture |
                    conversion | click | time_on_page | scroll
                                     |
                                     v
                +---------------------------------------------+
                |  Batch pass (NOT on ingest path) — runs        |
                |  alongside/adjacent to the existing            |
                |  visitor_aggregator.py incremental sweep        |
                +---------------------------------------------+
                                     |
                     per visitor, per site, evaluate TWO signals
                                     |
        +----------------------------+----------------------------+
        |                                                          |
        v                                                          v
+---------------------------+                      +---------------------------------+
| Signal A: Cadence variance  |                      | Signal B: Engagement mix          |
| — gap between consecutive   |                      | — ratio of "real engagement"       |
|   visits, per visitor        |                      |   events (click/scroll/            |
| — near-zero variance =       |                      |   time_on_page/conversion) to      |
|   cron-like schedule         |                      |   total events                     |
+---------------------------+                      +---------------------------------+
        |                                                          |
        +----------------------------+----------------------------+
                                     |
                          BOTH signals trip their
                          operator-tunable threshold?
                                     |
                    +----------------+----------------+
                    | NO (either signal clean)          | YES (both trip)
                    v                                    v
        +----------------------+          +----------------------------------------+
        | No flag. Visitor is    |          | NEW: bot-suspect flag set (name TBD    |
        | unchanged in every      |          | in PLAN) — visibility-only:            |
        | existing view.           |          |  - does NOT set is_abuse_flagged        |
        +----------------------+          |  - does NOT set do_not_resolve          |
                                            |  - does NOT touch is_emailable_identity |
                                            |  - does NOT exclude from any metric      |
                                            |    aggregate FILTER clause               |
                                            +----------------------------------------+
                                                                |
                                                                v
                                            +----------------------------------------+
                                            |  Dashboard: badge shown on visitor        |
                                            |  detail + list (ai_source pill precedent) |
                                            |  API: new field on visitor response       |
                                            |  (confirmed NEW wire surface — not         |
                                            |   currently serialized anywhere)           |
                                            +----------------------------------------+
```

## Acceptance Criteria (Testable Outcomes)

**AC-1 — Cadence-variance signal is computable per visitor from existing event history.**
Given a visitor's `events.created_at` timestamps for a site, a pure function returns a
variance/regularity measure of inter-visit gaps, with no dependency on any new column or new
client-side data.
`proven by:` unit test with synthetic timestamp series (cron-like near-zero variance vs. organic
human variance) asserting the function distinguishes them. `strategy:` Fully-Automated.

**AC-2 — Engagement-mix signal is computable per visitor from existing event types.**
Given a visitor's event-type history for a site, a pure function returns the ratio of
"real-engagement" events (`click`, `scroll`, `time_on_page`, `conversion`) to total events, using
only event types the tracker already emits (`tracker.js:243,263,283,374,538,552,557`).
`proven by:` unit test with synthetic event-type sequences (pageview-only vs. mixed engagement)
asserting the function returns the expected ratio. `strategy:` Fully-Automated.

**AC-3 — A visitor is flagged only when BOTH signals trip together.**
Cadence variance alone (e.g. a real person with a rigid daily habit, like checking a pricing page
every morning) does not flag a visitor. Low engagement alone (e.g. a real visitor who bounces after
one pageview) does not flag a visitor. Only the conjunction — rigid cadence AND near-zero
engagement — sets the flag. This mirrors the existing dual-condition design in
`ingest_velocity.evaluate_velocity` (visitor-count precondition AND diversity-below-threshold),
applied here to a single-visitor, long-window context instead of a many-visitor, short-window one.
`proven by:` unit test matrix over the 4 quadrants (rigid+engaged, rigid+low-engagement,
irregular+engaged, irregular+low-engagement) asserting only the rigid+low-engagement quadrant
flags. `strategy:` Fully-Automated.

**AC-4 — Detection runs as a batch/background pass, never on the ingest write path.**
No new per-request check is added to `POST /ingest`; the signal is computed by a scheduled or
sweep-triggered background pass that reads already-stored `events` rows, consistent with the
existing `aggregation_sweep_interval_minutes` / `visitor_aggregator.py` batch-pass precedent (not
the write-time `ingest_velocity.py` precedent, which is structurally wrong for cross-day history —
see Background).
`proven by:` integration test asserting `POST /ingest` latency/behavior is unchanged when the new
detection code exists but has not yet run its batch pass. `strategy:` Fully-Automated.

**AC-5 — The bot-suspect flag is structurally distinct from `is_abuse_flagged` and from
`agent_visits`.**
The new flag is its own field, is never derived from and never sets `is_abuse_flagged`, and this
SPEC's detection logic never writes to or reads from the `agent_visits` table (that table is
self-declaring-AI-agent traffic, a categorically different phenomenon — see Background).
`proven by:` code-level check/unit test asserting the new detection module has zero import
references to `agent_visit.py` and zero write paths to `is_abuse_flagged`. `strategy:`
Fully-Automated.

**AC-6 — Flagging a visitor does NOT change outreach eligibility (the motivating-case fix).**
Setting the bot-suspect flag on a real, previously-emailable identified visitor does not set
`do_not_resolve`, and `is_emailable_identity()` continues to return the same result it would have
without the flag — a real contact who also runs a bot against the site stays exactly as
outreach-eligible as before.
`proven by:` integration/regression test constructing a real `IdentifiedVisitor` with the new flag
set, asserting `is_emailable_identity()` and the 3 existing call sites (`campaign_sender.py:202`,
`csv_exporter.py:79`, `routers/campaigns.py:725`) are unaffected — same signature, same 3rd-param
contract, new flag not wired in as a 4th guard. `strategy:` Fully-Automated.

**AC-7 — Flagging a visitor does NOT silently distort existing dashboard metrics.**
The new flag is NOT added to the `FILTER (WHERE NOT is_flagged_abuse)` exclusion pattern in
`visitor_aggregator.py`'s aggregation SQL. A flagged visitor's pageviews/sessions/scroll depth
continue to count exactly as before in every existing aggregate, unless and until an operator
explicitly opts into a stricter mode (out of scope for v1 — see Out Of Scope).
`proven by:` integration test asserting aggregation output for a flagged visitor is
bit-for-bit identical to the same visitor's aggregation output before the flag existed.
`strategy:` Fully-Automated.

**AC-8 — The flag is visible on the visitor detail page.**
A flagged visitor's detail page (`apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx`) shows
a badge/pill indicating bot-suspect status, following the same visual precedent as the existing
`ai_source` "Arrived via" pill (lines 472-477, 830).
`proven by:` Playwright/component test rendering a visitor fixture with the flag set and asserting
the badge is present; asserting it is absent when the flag is unset. `strategy:` Hybrid (component
render is Fully-Automated; full Playwright auth-harness leg is Agent-Probe, matching the existing
Clerk auth-harness gap noted for other pixel/ads-audiences UI ACs).

**AC-9 — The flag is visible on the visitor list page.**
The visitor list (`apps/web/src/app/dashboard/visitors/page.tsx`) shows the same badge inline per
row for flagged visitors, following the existing list-facet pattern used for `ai_source` (lines
81, 139, 183-185, 562-563, 670-675).
`proven by:` component test asserting the badge renders per-row for flagged visitor fixtures.
`strategy:` Fully-Automated (component-level; no auth harness needed for a list-render unit test).

**AC-10 — The flag is exposed as a new field on the visitor API response (confirmed new wire
surface).**
A new field is added to the visitor schema/response in `apps/api/schemas/` and serialized by
`apps/api/routers/visitors.py`. This is confirmed NEW surface, not an extension of an existing one
— neither `is_abuse_flagged` nor any equivalent flag is currently serialized anywhere in
`apps/api/schemas/` or `routers/visitors.py` (verified by grep during this SPEC session).
`proven by:` integration test asserting a `GET` visitor endpoint response includes the new field
with the correct boolean value for a flagged vs. unflagged visitor fixture. `strategy:`
Fully-Automated.

**AC-11 — Thresholds are operator-tunable via config, default OFF.**
The feature ships behind a new feature flag defaulting to `False` (matching
`agent_detection_enabled` / `ingest_velocity_enabled` precedent), with cadence-variance and
engagement-ratio thresholds as separate `pydantic-settings` env vars — no hardcoded magic numbers.
`proven by:` unit test asserting detection is a no-op when the flag is `False`, and asserting
threshold values are read from `settings` rather than literals in the detection module.
`strategy:` Fully-Automated.

**AC-12 — No PII in any new log line.**
Any new log line emitted when a visitor is flagged contains only `site_id`, `visitor_id` (already
treated as a non-PII identifier elsewhere in the codebase), counts, and computed signal values —
never visitor email, name, or other PII fields.
`proven by:` code-level regression test asserting new structlog call sites in the detection module
pass no raw PII fields, mirroring the existing guardrail-enforcement pattern (`ingest_velocity.py`
AC-9 precedent). `strategy:` Fully-Automated.

**AC-13 — False-positive protection: a real, habitual but engaged visitor is never flagged.**
A visitor who checks the same page daily at a similar time (moderate-to-low cadence variance) but
regularly scrolls, clicks, or spends real time on the page is never flagged, because AC-3's
conjunction requires BOTH low variance AND low engagement.
`proven by:` unit test with a synthetic "power user" event series (rigid schedule, high engagement)
asserting no flag is set. `strategy:` Fully-Automated.

**AC-14 — Known-gap: live stealth-crawler validation is not proven by this SPEC's automated tests
alone.**
The detection logic is proven correct against synthetic/documented event shapes (AC-1 through
AC-13). Whether real-world stealth crawlers (including the motivating-case crawler itself) actually
exhibit low-enough engagement-mix ratios to trip the flag in production is not something unit/
integration tests alone can prove — this is explicitly tracked as a Known-Gap requiring a
post-deploy operator check against the motivating case's real historical event data once the
feature ships.
`proven by:` a documented operator verification step run once against the motivating case's real
`site_id`/`visitor_id`, comparing the flag's verdict to the operator's own confirmation that this
specific visitor is a bot. `strategy:` Agent-Probe / Known-Gap (cannot be fully automated —
requires real historical production data, not synthetic fixtures).

## Out Of Scope

- **Crawl-shape signal (same page sequence, uniform gaps) as a v1 detection input.** Candidate for a
  future iteration; not required for the motivating case, which the cadence + engagement-mix pair
  already catches. Deferred, not rejected.
- **UA byte-stability signal (same UA string across weeks) as a v1 detection input.** Same
  reasoning — candidate v2 signal, not required for v1.
- **Datacenter-ASN signal as a hard requirement.** `BLOCK_DATACENTER_TRAFFIC` exists but its
  implementation mechanics were not traced in RESEARCH; this SPEC does not require it as an input
  signal. Left as an open question for INNOVATE to resolve whether it's worth adding as a secondary
  signal.
- **Any change to `is_abuse_flagged` semantics, `visitor_aggregator.py`'s existing FILTER
  exclusions, or `is_emailable_identity()`'s guard parameters.** This SPEC adds a new, independent
  flag alongside these — it does not modify their existing behavior (see AC-5, AC-6, AC-7).
- **Any change to `agent_visits` / EvalLayer's self-declaring-agent classification.** Stealth
  crawlers are, by definition, traffic that never reaches `agent_classifier.py`'s allowlist path —
  this SPEC does not touch that table or its exclusion guarantees.
- **Blocking, dropping, rate-limiting, or CAPTCHA-ing a flagged visitor.** The flag is
  visibility-only in v1 (see Behavioral Outcomes). Any future "operator opts into stricter handling"
  mode (e.g. excluding flagged visitors from metrics on request) is a separate future SPEC, not
  this one.
- **Auto-unsubscribe or auto-suppression of a flagged visitor's email.** Explicitly rejected by
  AC-6 — this is the core product-tension fix the motivating case demands.
- **New client-side detection probes in the pixel (`tracker.js`).** All v1 signals are computed
  server-side from data the tracker already emits today; no new client-side instrumentation is
  required or requested.
- **A dedicated new operator-facing analytics endpoint (e.g. a bot-cadence dashboard panel beyond
  the per-visitor badge).** `GET /{site_id}/ingest-health` is site-level counts/ratios and is a
  structural mismatch for a per-visitor verdict (confirmed in RESEARCH); a per-visitor badge on the
  existing visitor surfaces is the chosen minimal v1 surface. A dedicated aggregate view is a
  candidate future SPEC if operators want site-wide "how many suspected bots" rollups.
- **Retroactive relabeling or backfill correction of historical dashboard metrics.** This SPEC adds
  a forward-visible flag; it does not attempt to "fix" any prior period's visitor counts.

## Constraints

- Must not modify `is_abuse_flagged`, `do_not_resolve`, or `is_emailable_identity()`'s existing
  guard-parameter contract — the new flag is additive and independent (AC-5, AC-6, AC-7).
- Must not add any new check to the `POST /ingest` write path — detection is batch/background only
  (AC-4), following the `visitor_aggregator.py` incremental-sweep precedent rather than the
  `ingest_velocity.py` write-time precedent (they solve structurally different problems — a
  short-window flood vs. cross-day cadence history).
- New feature flag(s) must default OFF and follow the existing operator-gated rollout posture
  (`agent_detection_enabled`, `ingest_velocity_enabled` precedent) — enabling in a real environment
  is an explicit human operator action, not an automatic consequence of this work shipping.
- Any new column requires a new Alembic migration chained on the live-reconfirmed current head
  (`d5b1f7c3a908` as of 26-07-26) — re-verify `alembic heads` immediately before any live apply,
  since concurrent programs may have advanced it further by the time this ships.
- No PII in any new log line, counter, or dashboard payload beyond what the codebase already treats
  as non-PII (`site_id`, `visitor_id`, counts, computed signal values) — matches the repo-wide
  guardrail (AC-12).
- Thresholds must be configurable via `pydantic-settings` env vars, not hardcoded (AC-11).
- Detection logic (the pure cadence/engagement functions) must be independently unit-testable
  without a database, matching the `ingest_velocity.evaluate_velocity` precedent — the
  business-logic core stays a pure function even though the caller needs a DB read.
- Must not require any new external paid provider or API call — every v1 signal is derived from
  data already stored in `events`/`visitors`; no mock-mode path is needed for v1 signals themselves
  (no external call exists to mock).

## Open Questions

None blocking this SPEC's lock. Two implementation-shape questions are explicitly deferred to
INNOVATE (they affect *how*, not *what*, and do not change any acceptance criterion above):

- **Datacenter-ASN helper location/mechanics** — whether `BLOCK_DATACENTER_TRAFFIC`'s existing
  implementation can be reused as a secondary (non-blocking, v2-candidate) input signal, and where
  that helper actually lives. Not required for v1 per Out Of Scope.
- **Exact APScheduler job-registration site and incremental-vs-repair-sweep hosting choice** —
  whether cadence detection rides alongside the existing `aggregation_sweep_interval_minutes` sweep
  in `apps/api/tasks/aggregation_tasks.py` or registers its own independent job. Either choice
  satisfies AC-4 ("batch, not write-path"); the specific wiring is an INNOVATE/PLAN decision.

## Background / Research Findings

Verified file:line evidence (treated as ground truth for this SPEC):

- **The gap:** every existing bot layer is UA-honesty-based. `tracker.js:4` only checks
  `navigator.webdriver === true` (client can lie). `bot_filter.py` is a drop-only UA regex (a
  spoofed Chrome UA passes cleanly). `agent_classifier.py` only classifies AI vendors that
  self-declare via UA string (`agent_detection_enabled` default OFF regardless). `ingest_velocity.py`
  requires a HIGH visitor count *precondition* before it even evaluates diversity
  (`evaluate_velocity`, `visitor_count < visitor_threshold` short-circuits to `False`) — a single
  polite visitor/day never reaches the threshold and is structurally invisible to this check by
  design, not by bug.
- **Candidate signals verified computable from existing `events` rows, no schema change needed for
  detection itself:** inter-visit cadence variance from `events.created_at` per visitor; engagement-
  less sessions from the tracker's own emitted event types (`pageview` `:243`, `utm_identify` `:263`,
  `form_email_capture` `:283`, `conversion` `:374`, `click` `:538`, `time_on_page` `:552`, `scroll`
  `:557` — bot sessions are pageviews-only); crawl shape and UA-byte-stability were identified as
  candidate v2 signals (Out Of Scope for v1); datacenter ASN noted as a secondary candidate with
  unconfirmed implementation mechanics (Open Questions).
- **Execution surface:** write-time detection (the `ingest_velocity.py` Redis-window pattern) is
  structurally wrong for this problem — it cannot see cross-day history. The batch/incremental
  aggregation pass in `visitor_aggregator.py` (`aggregate_visitors_for_site` :342,
  `_bulk_upsert_visitors_incremental` :525, watermark via `sites.last_aggregated_at`, APScheduler
  sweep at `aggregation_sweep_interval_minutes=60`, `apps/api/tasks/aggregation_tasks.py`) already
  loops per-site, per-visitor, on a schedule — the natural home for this signal.
- **Critical flag-semantics tension (resolved by this SPEC as explicit ACs):** the existing
  `events.is_flagged_abuse -> visitors.is_abuse_flagged -> identified_visitors.is_abuse_flagged`
  propagation (sticky `BOOL_OR`/`OR`-merge, `visitor_aggregator.py:299-314` FILTER excludes flagged
  rows from ALL metric aggregates) plus `is_emailable_identity(provider, source_agent_visit_id,
  is_abuse_flagged)` (`identity_classification.py:56-80`; call sites `campaign_sender.py:202`,
  `csv_exporter.py:79`, `routers/campaigns.py:725`) together form a HARD exclusion from both
  analytics and outreach. The motivating case is a real, wanted contact who ALSO runs a bot — no
  existing mechanism supports "bot-flagged for visibility, still outreach-eligible." This SPEC takes
  the explicit product position that the new flag must NOT reuse or extend `is_abuse_flagged`'s
  semantics (AC-5, AC-6, AC-7) — this is the single most important design constraint in the whole
  SPEC and is why it is called out repeatedly across Behavioral Outcomes, Flow diagram, and
  Acceptance Criteria rather than stated once.
- **Inline SPEC-session grep confirmed:** `is_abuse_flagged` is not serialized anywhere in
  `apps/api/schemas/` or `apps/api/routers/visitors.py` (only one unrelated internal reference to
  `do_not_resolve` at `visitors.py:788`). No web dashboard file references `is_abuse_flagged`. The
  only existing precedent for a per-visitor flag reaching the frontend is `ai_source` (the "Arrived
  via" pill, `visitors/[visitorId]/page.tsx:472-477,830` + list facet
  `visitors/page.tsx:81,139,183-185,562-563,670-675`). This confirms AC-10's "new wire surface" claim
  is not new-column-only — it is a genuinely new response field and a genuinely new dashboard
  surface, following the `ai_source` pattern as the closest working precedent.
- **Postures inherited from repo guardrails:** flag-but-store, never drop rows (matches
  ingest-abuse-hardening's P4 precedent); feature flag default OFF, operator-gated enable (matches
  `agent_detection_enabled` / `ingest_velocity_enabled` inline rollout-order comments in
  `config.py`); no PII in logs — counts/ids only; tenant scoping via `Site.user_id`, 404-not-403 on
  unknown ids.
- **Migration state:** Alembic single head `d5b1f7c3a908`, re-verified live 26-07-26. Any new column
  this work introduces chains onto that head; live-apply remains a separate explicit operator
  action, matching every other pending-migration precedent in this codebase.
- **Test infrastructure:** unit-lane pure-function precedent is `tests/unit/test_ingest_velocity.py`
  (the same dual-condition pure-function pattern this SPEC's AC-1/AC-2/AC-3 follow); integration
  tests are Docker-gated per `tests/integration/test_ingest_abuse_hardening.py`; the runner is
  `.venv/bin/python3.11 -m pytest` (the repo's `.venv/bin/pytest` shebang is broken — always invoke
  via the `-m pytest` form).

---

## Strategy Recommendation for INNOVATE

**Recommended: Sequential, single `vc-innovate-agent` (sonnet).** This SPEC has two design
decisions that matter (signal-combination mechanics and the sweep-hosting choice), but they are
tightly coupled to one existing file (`visitor_aggregator.py`) and one existing pure-function
pattern (`ingest_velocity.py`) — there is no independent-scope fan-out benefit here. A single
INNOVATE pass comparing "ride the existing incremental sweep" vs. "register an independent
APScheduler job" is sufficient; parallel or team-based INNOVATE would add coordination overhead
without a corresponding benefit, since both candidate approaches touch the same one or two files.

Alternatives considered: **parallel subagents** (rejected — no independent investigation branches;
the two open questions deferred to INNOVATE are small enough for one agent to resolve together);
**vc-team** (rejected — no adversarial debate or cross-file coordination need; this is a
single-cohesive-decision INNOVATE, not a multi-owner one); **workflow/dynamic agent()** (rejected —
no repeated sub-task shape to template).

---

**Status:** DONE
**Summary:** Cadence Bot Flag SPEC written at `process/features/pixel/active/cadence-bot-flag_26-07-26/cadence-bot-flag_SPEC_26-07-26.md` — 14 numbered ACs (all `proven by:`/`strategy:` tagged, grounded in verified file:line evidence and the repo's existing test-tier precedents), explicit product position resolving the motivating case's flag-semantics tension (new flag is visibility-only, structurally independent of `is_abuse_flagged`/outreach eligibility), inline open question resolved via grep (new flag = confirmed new wire surface, not an extension), 2 non-blocking implementation-shape questions deferred to INNOVATE, Out Of Scope and Constraints locked, strategy recommendation (sequential single sonnet agent) included.
**Concerns/Blockers:** None. AC-14 is an explicit Known-Gap (live stealth-crawler validation against the motivating case's real production data) — flagged as Agent-Probe tier, not blocking SPEC lock; carry it into PLAN/EXECUTE closeout tracking.
