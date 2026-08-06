---
name: plan:job-change-detection-spec
description: "SPEC — detect when a previously-identified visitor moves to a new company and surface it as a high-intent outreach trigger"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# Job-Change Detection — SPEC

**Date:** 07-08-26
**Feature:** visitors-identity
**Status:** SPEC — locked pending INNOVATE

---

## Summary

Beam already knows a person's company and job title the first time it identifies them — but it
never checks again. If that person later shows up at a Beam customer's site working somewhere
else, Beam has no idea; the old company name just sits there, quietly wrong, forever. This SPEC
adds **job-change detection**: when a person Beam has already identified turns up with a
different, confirmed company, Beam notices and turns it into a ready-to-review outreach trigger —
"this person you already know just moved to a new company, here's a drafted email." This is the
single highest-intent signal in B2B outreach (a job-changer is buying again, often at a bigger
budget, and remembers your product from their last job) and it is the natural next step on top of
the data Beam already owns. It ships **same-tenant only** in v1 — Beam only compares a site's own
visitor against that same site's own prior record of them, not against what any other Beam
customer knows. Cross-tenant job-change detection (using the shared identity graph) is a
deliberately separate, later decision that depends on the identity co-op's consent model, which
does not exist yet.

## User Stories / Jobs To Be Done

**US-1 — Site owner who wants to catch job-changers**
As a site owner running outbound, I want Beam to tell me when someone who already visited my site
has since changed companies, so I can reach out to them again at their new company while the
intent is fresh — instead of never finding out and losing the lead entirely.

**US-2 — Site owner reviewing outreach drafts**
As a site owner, I want a job-change trigger to show up as a normal draft I approve or reject —
never an email that sends itself — so I stay in control of who gets contacted and what gets said,
exactly like every other Beam-drafted email today.

**US-3 — End visitor whose job-change was detected**
As a person Beam has already identified once, I want Beam's re-check of my public professional
information to follow the same privacy rules as my first identification (opt-out respected, no
new kind of tracking), so being "found again" doesn't feel like being surveilled differently than
before.

**US-4 — Beam operator**
As Beam's operator, I want job-change re-checks to have their own budget line, not silently eat
the existing identity-resolution or enrichment budgets, and I want the feature off by default in
every environment until I turn it on deliberately, matching how every other data-layer flag in
this codebase ships.

## What The User Wants (Behavioral Outcomes)

- For a visitor Beam has already identified on a site (has a stored company/title from
  enrichment), Beam periodically re-checks whether that person's company has changed — using the
  same enrichment providers it already uses, not a new integration.
- Re-checking happens two ways: opportunistically when that same identified visitor returns to
  the site, and on a low-frequency scheduled sweep so a job-change is still caught even if the
  person never comes back. Both are budget-capped separately from existing identity-resolution and
  enrichment budgets.
- A detected change is not just "the enrichment field got overwritten" (today's silent behavior).
  It becomes a distinct, visible event: "this person was at Company A, is now at Company B,"
  timestamped and attributable, with enough context to explain itself to a site owner.
- Not every field flip counts as a real job change. Noise (a bad provider read, a subsidiary
  rename, a personal-email false corroboration) is filtered out before anything is surfaced —
  a site owner should never see a "job change" trigger that turns out to be a data glitch.
- A confirmed job-change event becomes a draft outreach trigger, flowing through the exact same
  draft → approved → active human-approval pipeline every other Beam campaign uses today. Nothing
  auto-sends. This also feeds the segmenter as a new signal, and surfaces on the dashboard
  alongside Beam's other hot-contact/high-intent surfaces.
- A visitor who is opted out (GPC/DNT/suppression list, `do_not_resolve`) is never re-checked —
  this is the same guard that already protects the visitor's first identification, applied again
  here, not a new or weaker rule.
- v1 detects job changes using only that same site's own historical record of the visitor. It does
  not compare against what any other Beam customer knows about that person, and it does not write
  anything new into the cross-tenant identity graph as part of detection.
- The whole feature ships behind a flag that defaults OFF everywhere, the same posture as every
  other data-layer flag in this codebase (`agent_detection_enabled`, `company_graph_enabled`,
  `identity_signals_enabled`).

## Flow / State Diagram

```
TODAY (silent overwrite, no detection)
========================================
 Visitor returns to Site A
        |
        v
 enrichment already ran once ever (resolution_tasks.py only
 enriches Visitor.identity_status == "anonymous")
        |
        v
 EnrichmentProfile.company_name / job_title
   -> NEVER RE-CHECKED, NEVER COMPARED, NO HISTORY KEPT


DESIRED STATE (job-change detection, same-tenant only)
========================================================
                     ┌───────────────────────────────┐
                     │ Site A's own identified visitor│
                     └───────────────┬─────────────────┘
                                     │
          ┌──────────────────────────┼──────────────────────────┐
          │ TRIGGER A: visitor       │ TRIGGER B: scheduled       │
          │ returns to Site A        │ low-frequency sweep         │
          │ (event-driven,           │ (batch, budget-capped,      │
          │  opportunistic)          │  catches non-returners)     │
          └──────────────┬────────────┴──────────────┬────────────┘
                          │                             │
                          ▼                             ▼
                 job_change_recheck_daily_cap (own budget line,
                 separate from resolution/enrichment budgets)
                          │
                          ▼
                 re-run existing provider tier (PDL / Proxycurl —
                 no new provider integration)
                          │
                          ▼
                 compare new company_name (normalized) vs the
                 site's OWN stored EnrichmentProfile baseline
                          │
              ┌────────────┴────────────┐
              │ no material change        │ company differs
              ▼                            ▼
        no event written           corroboration + confidence gate
                                    (work-email domain check,
                                     provider confidence threshold,
                                     personal-email alone does NOT
                                     corroborate)
                                            │
                              ┌──────────────┴──────────────┐
                              │ fails gate (noise)            │ passes gate
                              ▼                                ▼
                        no event written              job_change_events row
                                                        (site_id, visitor_id,
                                                         prior_company,
                                                         new_company, detected_at,
                                                         confidence) — MINIMAL
                                                         before/after pair, NOT
                                                         full longitudinal history
                                                                │
                                    ┌────────────────────────────┼────────────────────────────┐
                                    ▼                             ▼                             ▼
                          Dashboard / hot-contacts        Segmenter signal          Draft outreach trigger
                          surface (visible trigger)        (new attribute)          (draft -> approved ->
                                                                                      active, human approves,
                                                                                      NEVER auto-sends)

ERASURE COORDINATION (declared, not solved here)
==================================================
 DELETE /{site_id}/{visitor_id}/data
        │
        ▼
 job_change_events rows for that (site_id, visitor_id) MUST be included
 in the same cascade as EnrichmentProfile — new erasure surface, must be
 coordinated with graph-erasure-compliance_07-08-26 before EXECUTE.

CROSS-TENANT (explicitly deferred, not built in v1)
=====================================================
 beam_identity_graph (cross-tenant) ────X──── NOT read or written by
                                              job-change detection in v1.
                                              Deferred until identity-coop's
                                              consent model exists.
```

## Acceptance Criteria (Testable Outcomes)

**AC-1 — Feature flag defaults OFF everywhere.**
`job_change_detection_enabled` (or equivalent) defaults to `False` in every environment. With the
flag off, no re-check runs, no `job_change_events` row is ever written, and no existing behavior
(enrichment, resolution, campaign flows) changes at all.
- proven by: unit test asserting the default config value, plus an integration test asserting a
  returning identified visitor with the flag off produces zero re-check activity and zero
  `job_change_events` rows.
- strategy: Fully-Automated

**AC-2 — Event-driven re-check on a returning identified visitor.**
When a previously-identified visitor (has an `EnrichmentProfile` with a stored `company_name`)
returns to the same site and the flag is on, a re-check is scheduled/run using the site's existing
enrichment provider tier — not a new provider integration.
- proven by: integration test — seed an `EnrichmentProfile` with `company_name = "Acme"`, simulate
  a new visit event for the same identified visitor, assert a re-check call fires against the
  existing enrichment path (mocked provider).
- strategy: Fully-Automated

**AC-3 — Scheduled sweep catches non-returning visitors.**
A low-frequency batch sweep (reusing the existing celery beat / APScheduler sweep pattern) selects
previously-identified visitors who have not returned recently and re-checks a bounded, budgeted
subset of them, so a job-change is still eventually caught even if the person never revisits the
site.
- proven by: integration test — seed multiple identified visitors with stale `EnrichmentProfile`
  rows and no recent visit, run the sweep task directly, assert it selects and re-checks a subset
  bounded by the sweep's own cap.
- strategy: Fully-Automated

**AC-4 — Re-check has its own budget line, separate from existing budgets.**
Re-check calls are capped by a dedicated per-site daily limit (`job_change_recheck_daily_cap` or
equivalent) that is tracked independently of `Site.daily_resolution_budget` and the enrichment
7-day-cache budget. Exceeding the cap for a site on a given day stops further re-checks for that
site until the next window, without touching or consuming the site's identity-resolution or
enrichment budget.
- proven by: integration test — drive re-check volume for one site past the dedicated cap, assert
  further re-checks are refused for that site while `Site.daily_resolution_budget` consumption is
  unaffected (asserted directly on the resolution-budget counter).
- strategy: Fully-Automated

**AC-5 — A real company change is detected against the site's own stored baseline.**
When a re-check's provider result returns a `company_name` that differs (after normalization —
e.g. case, legal suffix like "Inc"/"LLC", whitespace) from the site's own currently-stored
`EnrichmentProfile.company_name` for that visitor, the system flags it as a candidate job change.
- proven by: unit test — feed a set of (stored, re-checked) company name pairs through the
  comparison function, assert true differences are flagged and normalization-equivalent pairs
  (e.g. "Acme Inc." vs "Acme, Inc") are not.
- strategy: Fully-Automated

**AC-6 — Noise is filtered before anything is surfaced (corroboration gate).**
A candidate company change is only promoted to a confirmed `job_change_events` row when it passes
a corroboration/confidence gate: the new company must come from a provider result at or above a
defined confidence threshold, and a personal email domain (gmail/yahoo/outlook/etc.) alone is
never sufficient corroboration on its own — it must be paired with another provider-confirmed
signal (e.g. work-email domain match, LinkedIn company match) to count.
- proven by: unit test — construct scenarios: (a) high-confidence provider result with a matching
  work-email domain → passes; (b) low-confidence result → rejected; (c) company differs but the
  only supporting signal is a personal-email domain with no other corroboration → rejected.
- strategy: Fully-Automated

**AC-7 — A confirmed job-change event is recorded as a minimal before/after pair, not a full history log.**
A confirmed job change writes exactly one `job_change_events` row per detected transition
containing `site_id`, `visitor_id`, `prior_company`, `new_company`, `detected_at`, and a confidence
value. It does not create a growing longitudinal log of every re-check attempt — only confirmed
transitions are recorded, and the site's `EnrichmentProfile.company_name`/`job_title` are then
updated to the new values (the existing overwrite behavior continues for the "current" fields; the
new table exists only to capture the transition itself).
- proven by: integration test — trigger a confirmed job change, assert exactly one
  `job_change_events` row exists with the correct before/after values, and assert
  `EnrichmentProfile.company_name` is updated to the new value.
- strategy: Fully-Automated

**AC-8 — Confirmed job-change becomes a draft outreach trigger, never auto-sent.**
A confirmed `job_change_events` row produces a campaign draft in the existing `draft` status,
flowing through the same `draft → approved → active` pipeline as every other Beam-generated
outreach. No email is sent as a direct consequence of detection.
- proven by: integration test — trigger a confirmed job change, assert a campaign/draft record is
  created with `status == "draft"`, and assert no send action (SendGrid call) occurs as part of
  the same flow.
- strategy: Fully-Automated

**AC-9 — Job-change trigger is visible on a dashboard surface.**
A site owner can see confirmed job-change events for their own site on a dashboard surface (the
existing hot-contacts surface from identity-program Phase 6, a new dedicated panel, or both —
exact placement is an INNOVATE/PLAN decision), scoped to their own site only.
- proven by: Playwright smoke check asserting the job-change trigger element is present and
  visible for a site with a seeded confirmed event (Fully-Automated presence check); UX/content
  placement judgment is a supplementary Agent-Probe review, not a substitute for the automated
  presence check.
- strategy: Hybrid

**AC-10 — Job-change signal is available to the segmenter.**
A confirmed job-change event is exposed as a signal the segmenter can use when building segments
(e.g. "recently job-changed" as a filterable/scoreable attribute), consistent with how other
signals (AI-referral, identity-signals corroboration) already feed the segmenter.
- proven by: unit/integration test asserting a visitor with a confirmed job-change event is
  identifiable via the segmenter's signal-reading path (mocked segmenter input, not a live Gemini
  call).
- strategy: Fully-Automated

**AC-11 — v1 detection is same-tenant only.**
The re-check and comparison logic reads and writes only that site's own `EnrichmentProfile`
baseline. It does not read from or write to `beam_identity_graph` (the cross-tenant store) as part
of detecting or recording a job change.
- proven by: integration test asserting a job-change detection run makes zero
  `beam_identity_graph` reads or writes (verified via a spy/mock on the graph access functions),
  even when a cross-tenant graph row exists for the same person.
- strategy: Fully-Automated

**AC-12 — Erasure cascade includes the new table.**
When `DELETE /{site_id}/{visitor_id}/data` is called for a visitor, any `job_change_events` rows
for that `(site_id, visitor_id)` are deleted in the same request, matching how `EnrichmentProfile`
is already handled by that endpoint.
- proven by: integration test — seed a `job_change_events` row for a visitor, call the delete
  endpoint, assert the row is gone after commit.
- strategy: Fully-Automated

**AC-13 — Opted-out visitors are never re-checked.**
A visitor with `do_not_resolve = True` or an email on the suppression list is never selected for
either the event-driven or scheduled re-check path, using the same guard already enforced for
first-time identification.
- proven by: unit test — construct a `do_not_resolve=True` visitor with a stored
  `EnrichmentProfile`, assert the re-check selection query/function excludes them.
- strategy: Fully-Automated

**AC-14 — No plaintext PII in the new table(s).**
`job_change_events` (and any new lookup index it needs) stores no plaintext email; it references
the existing `visitor_id`/`site_id` and stores company/title strings only (business data, not
personal contact data), consistent with the ciphertext/blind-index pattern used elsewhere for
actual PII fields.
- proven by: static/schema review — no `String` column named or shaped like a plaintext email
  field on the new table; existing `visitor_emails`/`EnrichmentProfile` remain the sole holders of
  contact PII, referenced by ID only.
- strategy: Fully-Automated (schema assertion test) supplemented by Agent-Probe schema review.

## Out Of Scope

- Cross-tenant job-change detection using `beam_identity_graph` — deferred until the identity
  co-op's consent model (`identity-coop_07-08-26`) exists and is live. v1 is same-tenant only.
- Full longitudinal job history (every company a person has ever had on file, or every re-check
  attempt ever made). Only confirmed transitions are recorded, as a minimal before/after pair.
- Any new enrichment provider integration. This SPEC re-uses the existing PDL/Proxycurl tier the
  waterfall already has; no new vendor is added.
- Auto-sending outreach as a direct result of a detected job change. Every trigger is a draft
  requiring human approval, matching Business Guardrail #1.
- Choosing the exact re-check cadence, confidence threshold numbers, corroboration rule specifics,
  daily budget cap value, or dashboard placement (hot-contacts panel vs. new panel vs. both) —
  these are INNOVATE/PLAN decisions, not locked here.
- Retroactively reconstructing company history for `EnrichmentProfile` rows that were already
  overwritten before this feature ships — that data is already gone; this feature only detects
  changes going forward.
- Enabling `job_change_detection_enabled` (or any related flag) in production. Shipping with the
  flag OFF is the deliverable; flipping it on is a later, explicit, separate operator action,
  matching every other data-layer flag precedent in this codebase.
- Any change to `identity_resolver.py` §3.2 provider-candidate vocabulary/gating logic — that
  belongs to `identity-vocab-reconcile_07-08-26`, not this SPEC.
- Any change to the erasure/deletion mechanics of `beam_identity_graph` itself, or to the
  cross-tenant graph's own erasure model — that is `graph-erasure-compliance_07-08-26`'s scope.
  This SPEC only requires the new same-tenant table to be included in the existing per-visitor
  erasure cascade (AC-12).
- Building a brand-new outreach template/copy specifically for job-change triggers — copy/template
  design is downstream campaign-drafting territory, not specified here.

## Constraints

- **Erasure blast-radius declaration (hard requirement).** `job_change_events` is a NEW table that
  stores per-visitor history data. It MUST be declared in the erasure blast radius before EXECUTE
  begins — either by extending `DELETE /{site_id}/{visitor_id}/data`'s existing cascade (AC-12) or
  by explicit coordination with `graph-erasure-compliance_07-08-26` if that program's erasure
  queue mechanism is chosen as the shared pattern instead. EXECUTE for this SPEC's downstream plan
  MUST NOT begin until this coordination is confirmed — do not ship a new PII-adjacent history
  table with no erasure story, given the erasure gap that program exists specifically to close.
- **Minimal-history design is required unless explicitly overridden.** Per repo precedent (no
  table in this codebase currently keeps unlimited per-visitor history — `EnrichmentProfile`
  overwrites in place, `beam_identity_graph` is a single current-state row), this SPEC requires the
  minimal before/after design (AC-7) as the default. A full longitudinal history table would
  multiply the erasure surface and is explicitly out of scope unless a future SPEC argues for it.
- **Cross-tenant consent boundary.** Detecting a job change by comparing sightings of the same
  person across two different tenant sites raises the same unresolved cross-tenant consent
  question the identity co-op program is built to answer. This SPEC takes the position that v1
  MUST NOT do this (AC-11) — same-tenant-only detection uses data the site already lawfully holds
  about its own visitor, avoiding the open consent question entirely. Cross-tenant job-change
  detection is a distinct, later SPEC once `identity-coop_07-08-26` ships a consent model to build
  on.
- **Sequencing — shared surface with two other in-flight programs.** `identity-program_03-08-26`
  Phase 6 already owns a "hot-contacts" dashboard surface this feature likely wants to extend or
  sit beside; `graph-erasure-compliance_07-08-26` and `identity-vocab-reconcile_07-08-26` both
  touch `identity_resolver.py`. Any downstream plan for this SPEC must check the current state of
  all three before claiming blast radius on shared files/surfaces, per the same sequencing
  discipline those SPECs already apply to each other.
- **Budget guardrail #2 applies in full.** Re-check activity must have its own dedicated,
  separately-tracked budget line (AC-4) — it must never silently consume `Site.daily_resolution
  _budget` or the identity/enrichment 7-day cache windows, per `all-context.md` Business
  Guardrail #2.
- **Business guardrail #1 (no auto-send) applies in full.** Every job-change trigger is a draft
  requiring human approval (AC-8) — there is no exception for how "hot" or time-sensitive the
  signal is.
- **PII/GDPR guardrail #3 applies in full.** No plaintext PII in the new table (AC-14), and the
  existing `do_not_resolve`/suppression guard must gate re-checks exactly as it gates first-time
  identification (AC-13) — this is an extension of an existing protection, not a new one invented
  from scratch.
- **Flag-default precedent.** The feature flag must default OFF and follow the exact
  operator-gated rollout posture of `agent_detection_enabled` / `company_graph_enabled` /
  `identity_signals_enabled` — no deviation.
- **Migration chain currency.** Any new migration this SPEC's plan requires must chain onto the
  true current alembic head at execute time (`alembic -c apps/api/alembic.ini heads`), never a
  hardcoded value — the chain moves under concurrent work (see `all-context.md`).

## Open Questions

1. **Exact re-check cadence for the "returning visitor" trigger.** What counts as "returning" for
   the event-driven path (any new session? only after N days since last check? only on a new,
   distinct visit)? Owner: INNOVATE/PLAN — does not block SPEC lock, since AC-2 specifies the
   observable behavior (a re-check fires on a qualifying return), not the exact windowing rule.
2. **Exact confidence threshold and corroboration rule values.** AC-6 requires a corroboration
   gate to exist and specifies the personal-email exclusion rule; the exact numeric confidence
   cutoff and the full list of qualifying corroboration signals are an INNOVATE/PLAN decision.
3. **Dashboard placement.** Whether job-change triggers extend the existing Phase 6 hot-contacts
   surface, get a dedicated new panel, or both — AC-9 requires visibility, not a specific surface.
   Owner: INNOVATE/PLAN, coordinate with `identity-program_03-08-26` Phase 6 if still active.
4. **Scheduled sweep cadence and cap values.** How often the batch sweep runs and how many
   visitors per site it re-checks per run — AC-3/AC-4 require the mechanism and the budget
   separation; the numeric cadence/cap is INNOVATE/PLAN's call, matching how the existing
   promotion-sweep and company_graph staleness precedents were sized (75-day staleness window,
   5-minute promotion sweep) — this feature's numbers do not need to match those, just be
   deliberately chosen and documented.
5. **Erasure mechanism choice.** Whether `job_change_events` is deleted directly by extending the
   per-visitor `DELETE` endpoint's existing cascade, or via whatever erasure-queue mechanism
   `graph-erasure-compliance_07-08-26` ultimately builds — Constraints requires coordination before
   EXECUTE; the specific mechanism is not locked here.

None of the above block advancing to INNOVATE — each is a deliberately deferred design decision
with a named owner, not an unresolved intent gap. The four decisions the task specifically asked
this SPEC to resolve (trigger model, storage shape, surfacing destinations, noise-filtering rule)
are locked above (hybrid event+scheduled trigger; minimal before/after storage; dashboard +
segmenter + draft-campaign surfacing; corroboration-gated confirmation).

## Background / Research Findings

Research (verified against source during this SPEC session, per the task's Prior Research block):

- `apps/api/models/enrichment.py` — `EnrichmentProfile.company_name`/`job_title` is a single
  overwritable field pair, unique on `(site_id, visitor_id)`. `apps/api/services/enricher.py`'s
  `_upsert_profile` overwrites in place on every enrichment call — confirmed zero history kept
  anywhere today.
- `apps/api/tasks/resolution_tasks.py` — `_process_site` selects only
  `Visitor.identity_status == "anonymous"` for enrichment. Enrichment fires exactly once per
  visitor ever; there is no existing re-enrichment loop for returning identified visitors. This is
  the gap job-change detection's re-check mechanism (AC-2/AC-3) must fill — it is new
  infrastructure, not a reuse of an existing loop.
- `apps/api/models/beam_identity.py` (`BeamIdentityNode`, table `beam_identity_graph`) has no
  company field at all — only fingerprint/fingerprint_v3, email, full_name, city/region/country.
  `CompanyGraphNode` (`apps/api/models/company_graph.py`) is IP-keyed, not person-keyed. Neither
  table can currently answer "has this person's company changed" — confirming this SPEC requires
  new storage, not a read against existing cross-tenant tables.
- `apps/api/models/visitor.py` (`IdentifiedVisitor`) has no company field of its own; company data
  lives only in `EnrichmentProfile`, joined by `(site_id, visitor_id)` — confirms the comparison
  baseline for AC-5 is scoped per-site by construction, supporting the same-tenant-only decision
  (AC-11) as the natural default, not an arbitrary restriction.
- Providers already returning job data: PDL and Proxycurl both return
  `job_title`/`company_name`/`company_size`/`industry`/`seniority` today
  (`apps/api/services/enricher.py:410,511-516,607-608`) — confirming AC-2/AC-3's "no new provider
  integration" requirement is achievable with existing wiring.
- Reusable infra precedents: the celery `beat_schedule` crontab pattern, the identity-program
  Phase 5 promotion-sweep (APScheduler batch sweep, `phase-5-promotion-sweep_PLAN_03-08-26.md`),
  and `company_resolver.py`'s `_company_graph_is_stale` 75-day read-time staleness re-validation
  are the direct architectural precedents for AC-3's scheduled sweep design — cited as shape
  reference, not as the locked mechanism.
- Budget guardrails from `all-context.md` Business Guardrail #2 (identity resolution 50/day/site,
  deep research 3/day, 30-day no-retry-failed cache, 7-day enrichment cache) establish the pattern
  AC-4 requires this feature to follow: a new re-check activity needs its own budget line, not a
  silent draw against existing budgets.
- `graph-erasure-compliance_07-08-26` SPEC (read in full for this session) is actively fixing the
  fact that `beam_identity_graph` rows are never erased on per-visitor deletion today, and
  explicitly has not decided `CompanyGraphNode`'s erasure obligations (its own Open Question 2).
  This directly motivates this SPEC's Constraints requirement to declare `job_change_events` in
  the erasure blast radius up front rather than repeat that same mistake with a new table.
- `identity-coop_07-08-26` SPEC (read in full for this session) is building the only consent
  mechanism this codebase has for cross-tenant identity sharing, and is itself not yet built or
  shipped. This directly motivates this SPEC's decision to keep v1 same-tenant-only (AC-11,
  Constraints) rather than build a second unconsented cross-tenant use case while the first one
  (the existing `beam_identity_graph` pooling) is still being made honest.
- `process/features/visitors-identity/_GUIDE.md` and `identity-program_03-08-26/phase-6-hot-
  contacts-dashboard_PLAN_03-08-26.md` confirm a "hot contacts" dashboard surface already exists
  or is in-flight in this feature area — cited as a candidate surfacing destination for AC-9, not
  a locked decision (see Open Question 3).
- `process/context/tests/all-tests.md` confirms the unit/integration/Playwright test-lane split
  this SPEC's `proven by:` annotations are grounded in — pytest unit for pure comparison/gate
  logic (AC-5, AC-6, AC-13), pytest integration for DB-backed flows (AC-2–AC-4, AC-7–AC-8, AC-10–
  AC-12), Playwright only where real dashboard rendering is the thing being verified (AC-9).
