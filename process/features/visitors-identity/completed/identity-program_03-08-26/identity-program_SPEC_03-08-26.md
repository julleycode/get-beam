---
name: spec:identity-program
description: "Identity honesty program — Phase 0 (confidence-gated candidate tier) + Phase H (named-traffic factory via contact import + tokenized links)"
date: 03-08-26
feature: visitors-identity
metadata:
  node_type: memory
  type: spec
  feature: visitors-identity
  phase: "phase-0-and-h"
---

# Identity Program — SPEC (Phase 0 + Phase H)

## Summary

Beam currently tells customers a visitor is "Identified" even when the underlying match is a
probabilistic guess — this already produced a real wrong-person result (a US visitor labeled as
"Janet Valla"). This SPEC covers the first approved chunk of work to fix that: **Phase 0** makes
Beam honest about *how sure* it is before it calls someone by name, and **Phase H** gives customers
a second, much more reliable way to get named visitors in the first place — by importing contacts
they already own and tracking when those exact people click a link. Together these stop Beam from
asserting facts it doesn't have, and grow the share of visitors who are named with certainty instead
of guessed.

## User Stories / Jobs To Be Done

**Persona: indie SaaS founder** (small team, sends outreach personally, reputation-sensitive)

- As an indie SaaS founder, I want Beam to visibly distinguish "we're pretty sure this is Jane"
  from "we're guessing this might be Jane," so that I never email or reference the wrong person by
  name and damage a prospect relationship.
- As an indie SaaS founder, I want to import the list of leads/customers I already have (a CSV), so
  that when one of them visits my site or clicks my email link, Beam tells me *for certain* who it
  is — not a maybe.
- As an indie SaaS founder, I want a wrong "Identified" match to be correctable, so that Beam
  doesn't keep insisting on a name I've already told it is wrong.

**Persona: DTC founder** (higher visitor volume, outreach is more automated/batch)

- As a DTC founder, I want to see at a glance how many of my imported contacts are active on my
  site right now ("12 of your 500 contacts viewed pricing this week"), so that I know exactly who
  to follow up with instead of guessing from anonymous traffic.
- As a DTC founder, I want a guessed graph match to never be addressed by name in outreach copy, so
  that a batch send never calls someone "Hi Janet" when Beam isn't actually sure that's who it is.
- As a DTC founder, I want the same guardrails (unsubscribe, suppression, do-not-email, hourly cap)
  to apply to sends triggered by my imported list exactly as they do today for regular campaigns,
  so that I don't accidentally violate my own compliance posture just because the contact came from
  an import instead of organic traffic.

## What The User Wants (Behavioral Outcomes)

**Phase 0 — Confidence gating / candidate tier**

- A visitor matched by a provider graph lookup (RB2B, Leadpipe, or Capturify) is always shown as a
  **Candidate** — never as flat "Identified" — with a visible confidence indicator, mirroring the
  existing "Company-level guess, don't email them" caution pattern already in the product. This is
  permanent for graph-sourced matches: no score, however high, ever auto-promotes a graph match to
  "Identified."
- "Identified" (verified) status is reserved for deterministic paths only: the visitor
  self-declared (form capture), clicked their own tokenized link (`_bid`), or a human explicitly
  confirmed the match.
- Candidate-tier identities ARE emailable and exportable — they are not locked out of outreach —
  but any outreach sent to a Candidate must use generic, non-personalized copy: no guessed name, no
  guessed company/title pulled from the graph match anywhere in the subject or body. Verified
  identities keep full personalization as today.
- A customer can correct a wrong Candidate match. Once corrected (rejected), that visitor becomes
  eligible for a fresh resolution attempt instead of being permanently stuck on the wrong identity.
- A customer can also confirm a Candidate match is correct, promoting it to verified/"Identified" —
  this is the one human-driven path that can move a graph-sourced guess into the verified tier.
- Existing dashboard counts, KPIs, and "Identified" filters continue to mean what they say today —
  a Candidate never silently inflates or corrupts an "Identified" count.

**Phase H — Named-traffic factory**

- A customer can bring a list of contacts they already own (CSV: at minimum name + email) into
  Beam, up to 5,000 contacts per site.
- Beam generates individually tokenized links (reusing the existing link-tokenization mechanism)
  that a customer can send to their imported contacts through their own channels, or through
  Beam's outreach.
- When an imported contact clicks their tokenized link and lands on the customer's site, that
  visit is recognized as a **named, verified visitor** — not a guess — and is visible on the
  dashboard within 5 minutes of the click. This recognition happens via a batch/triggered process
  after ingest, not synchronously inside the visitor-facing `/ingest` request path.
- This works the same way regardless of which of Beam's send mechanisms delivered the link
  (SendGrid-backed sends and Gmail-Connect sends behave identically for tracking purposes).
- A dashboard view answers "how many of my known contacts are active, and which ones" — e.g. "12
  of your 500 contacts viewed pricing this week" — without the customer having to cross-reference
  lists manually.
- Every send that goes out to an imported contact — whether triggered by Beam automation or
  initiated by the customer — obeys the exact same safety rules as every other Beam email today:
  suppression list, do-not-email, hourly send cap, and a working unsubscribe link. There is no
  separate, lesser-guarded path for imported-list sends.

## Flow / State Diagram

**Phase 0 — Visitor identity status lifecycle**

```
                 ┌─────────────┐
                 │  anonymous  │◄────────────────────────────┐
                 └──────┬──────┘                              │
                        │ provider graph match found          │ customer rejects
                        ▼                                     │ a Candidate match
              ┌───────────────────┐                           │
              │  "candidate"       │───────────────────────────┘
              │  (ALWAYS — RB2B,   │
              │  Leadpipe,         │
              │  Capturify all     │
              │  land here,        │
              │  regardless of     │
              │  score; shown with │
              │  confidence badge; │
              │  emailable, but    │
              │  GENERIC copy only)│
              └─────────┬─────────┘
                        │ customer confirms match is correct
                        │   OR deterministic verification
                        │   (form capture / _bid click)
                        ▼
              ┌───────────────────┐
              │   "identified"     │
              │   (verified —      │
              │   full personal-   │
              │   ization allowed) │
              └───────────────────┘
```

**Phase H — Named-traffic factory flow**

```
Customer's owned    ┌──────────────┐     ┌───────────────────┐
contact list (CSV) ─►  Import      │────►│ Tokenized outbound │
(≤5,000/site)        │  (new)       │     │ link generated per │
                     └──────────────┘     │ contact (existing  │
                                           │ _bid mechanism)    │
                                           └─────────┬─────────┘
                                                      │ sent via SendGrid OR Gmail-Connect
                                                      ▼
                                           ┌─────────────────────┐
                                           │ Contact clicks link  │
                                           │ and lands on site    │
                                           └─────────┬───────────┘
                                                      │ ingest writes VisitorEmail;
                                                      │ batch/triggered resolve runs
                                                      │ AFTER the ingest hot path
                                                      ▼
                                           ┌─────────────────────┐
                                           │ Visitor recognized as │
                                           │ NAMED + VERIFIED       │
                                           │ within <=5 minutes      │
                                           └─────────┬───────────┘
                                                      │
                                                      ▼
                                           ┌─────────────────────┐
                                           │ Dashboard: "N of your │
                                           │ M contacts active"   │
                                           └─────────────────────┘

  All sends (import-triggered or not) ──► same guardrail chain:
  suppression list → do-not-email → hourly cap → unsubscribe footer
```

## Acceptance Criteria (Testable Outcomes)

**Phase 0**

1. Any provider-graph match (RB2B, Leadpipe, or Capturify), regardless of confidence score, results
   in the visitor being shown as "Candidate" — never as flat "Identified." No score threshold
   auto-promotes a graph match to verified.
   proven by: unit test on the resolver's status-assignment logic (mirrors
   `test_identity_classification.py` pattern) — new coverage required, asserting all three
   providers land on Candidate at any score including 0.99.
   strategy: Fully-Automated

2. "Identified" (verified) status is only reachable via a deterministic path: self-declared/form
   capture, a `_bid` tokenized-link click, or explicit human confirmation of a Candidate — never via
   an automatic graph-score threshold.
   proven by: `tests/unit/test_identity_resolver_parallel.py` regression run + new test asserting
   no code path auto-sets `identity_status = "identified"` from a graph-provider score alone.
   strategy: Fully-Automated

3. A Candidate-tier identity IS returned by the existing emailable-export call sites
   (`campaign_sender.py`, `csv_exporter.py`, `routers/campaigns.py`) as a sendable contact — Phase 0
   does not block Candidates from outreach — but every send to a Candidate uses generic copy (see
   AC15–17).
   proven by: new unit test confirming Candidate rows ARE included in the emailable set (positive
   assertion, opposite of the old "block by default" framing).
   strategy: Fully-Automated

4. The Candidate badge is visible on both the visitor list page and the visitor detail page, with a
   tooltip explaining the match is unconfirmed, mirroring the existing company-level caution badge.
   proven by: Playwright/Agent-Probe visual check on `dashboard/visitors` and
   `dashboard/visitors/[visitorId]` pages.
   strategy: Agent-Probe

5. The visitor detail/API response surfaces the underlying confidence value so the dashboard can
   render it (closing the gap where `confidence_score` reaches the API but is dropped by the
   frontend today).
   proven by: integration test asserting the API response payload; frontend type-check gate.
   strategy: Fully-Automated

6. A customer can mark a Candidate match as wrong; doing so returns that visitor to an
   `anonymous`-equivalent, re-resolvable state rather than leaving it permanently stuck.
   proven by: new integration test covering the "reject candidate → re-eligible for resolution
   sweep" path.
   strategy: Fully-Automated

7. A customer can mark a Candidate match as correct; doing so promotes that visitor to "identified"
   (verified), and only sends made after that promotion use personalized copy.
   proven by: new integration test covering the "confirm candidate → promoted to identified →
   subsequent sends personalized" path.
   strategy: Fully-Automated

8. Existing dashboard counts/KPIs that filter on `identity_status == "identified"` are audited and
   updated so a Candidate is never silently counted as "Identified" nor silently dropped from
   totals without an explicit product decision recorded for each site (sweep eligibility, revive
   logic, KPI/timeseries counts, dashboard summary — the ~8 call sites found in research).
   proven by: unit test per call site confirming Candidate rows are handled per the documented
   decision (included/excluded, stated explicitly).
   strategy: Fully-Automated

**Phase 0 — Outreach personalization gating (new)**

15. A campaign send to a Candidate-tier recipient uses a generic greeting (e.g. "Hey there") and
    contains no guessed-identity merge field (name, title, or company sourced from the graph match)
    anywhere in the subject line or body.
    proven by: new unit test on campaign draft/send composition asserting Candidate recipients
    never receive a populated name/title/company merge field from `resolution_provider` in
    {rb2b, leadpipe, capturify}-sourced data.
    strategy: Fully-Automated

16. A campaign send to a verified ("identified") recipient is personalized exactly as it is today —
    no regression to existing personalized send behavior.
    proven by: regression test on existing campaign personalization test coverage.
    strategy: Fully-Automated

17. When a Candidate is promoted to verified mid-campaign (see AC7), only sends that occur after the
    promotion timestamp use personalized copy; any send already queued/sent before promotion is not
    retroactively changed.
    proven by: new integration test simulating promotion mid-send-batch, asserting per-send
    personalization reflects the recipient's status at send time.
    strategy: Fully-Automated

**Phase H**

9. A customer can upload a CSV of contacts (minimum: name + email), up to 5,000 contacts per site,
   and each row becomes an identity Beam can recognize before any site visit occurs. An upload
   attempting to exceed 5,000 contacts for that site is rejected with a clear error identifying the
   limit.
   proven by: new integration test for the import endpoint (create → list → detail) plus a
   boundary test at exactly 5,000 and 5,001 contacts.
   strategy: Fully-Automated

10. Each imported contact gets a unique, working tokenized link using the existing link-decoration
    mechanism.
    proven by: unit test on link generation for imported contacts, reusing `link_decorator.py`
    round-trip test pattern.
    strategy: Fully-Automated

11. When an imported contact's tokenized link is clicked, the resulting visitor is marked as a
    named, verified identity and visible on the dashboard within 5 minutes of the click, via a
    batch or triggered resolve step that runs after the `/ingest` request completes — not inline in
    the ingest hot path.
    proven by: integration test simulating click → ingest → batch/trigger resolve, asserting the
    visitor's identity status and a timestamp delta of <=5 minutes, and asserting the `/ingest`
    request itself does not block on resolution.
    strategy: Fully-Automated

12. Clicking an imported contact's link produces the identical tracked outcome (attribution,
    click record, resulting identity) whether the link was delivered via SendGrid or via
    Gmail-Connect send. Link decoration is already shared across both channels (verified:
    `decorate_links()` runs unconditionally in `campaign_sender.py` before the SendGrid/Gmail
    channel fork) — the real remaining gap is narrower: `custom_args` (the SendGrid-webhook
    engagement-attribution echo) has no Gmail equivalent, because no Gmail-side webhook consumer
    exists to receive it.
    proven by: new integration test asserting both send channels produce equivalent click→identity
    outcomes; Gmail-Connect path is exempted from the `custom_args` assertion (documented gap, no
    Gmail webhook consumer exists).
    strategy: Fully-Automated

13. The dashboard shows a count and list of "active known contacts" (imported contacts with
    recent site activity) without requiring the customer to manually cross-reference their
    imported list against visitor traffic.
    proven by: Agent-Probe check on the new dashboard view + integration test on the underlying
    query.
    strategy: Hybrid

14. Every email sent to an imported contact — regardless of trigger — is blocked if that contact is
    on the suppression list or has `do_not_email` set, counts against the same hourly send cap, and
    includes a working unsubscribe link.
    proven by: integration test asserting an imported-contact send is rejected/allowed under the
    same conditions as an existing `test_send_campaign`-style regression test for suppression/cap/
    unsubscribe.
    strategy: Fully-Automated

18. Importing a contact list never creates a contact that bypasses multi-tenant scoping — an
    imported contact is only ever visible/sendable within the site/user that imported it.
    proven by: integration test asserting cross-tenant import isolation (mirrors existing
    `Site.user_id == user.id` scoping tests).
    strategy: Fully-Automated

## Out Of Scope

- **Phase F** (AI-timed self-identification widget on the site) — not designed or built in this
  SPEC. Mentioned only as a later phase.
- **Phase E** (agent-ready site config for AI-agent traffic) — not designed or built in this SPEC.
  Mentioned only as a later phase.
- Buying or scraping third-party contact lists (e.g. Apollo-sourced lists) as an import source —
  Phase H only covers lists the customer already owns and uploads themselves.
- LinkedIn scraping or LinkedIn-sourced contact enrichment as part of import.
- Meta Ads / ad-platform audience matching as an identity oracle.
- Redesigning or replacing the existing provider waterfall (RB2B/Leadpipe/Capturify) itself —
  Phase 0 makes all graph matches permanently Candidate-tier; it does not change how those
  providers are called or scored internally.
- A general-purpose import UI supporting arbitrary CRMs or live sync — Phase H v1 is a CSV upload,
  not an integration.
- Tiered billing/plan-based import limits — Phase H v1 uses a single flat 5,000-contacts-per-site
  hard cap for all sites, not a per-plan-tier quota system.
- Changing the SendGrid vs Gmail-Connect send routing/selection logic — Phase H only requires the
  two paths to behave identically for link decoration (already shared today) and, where feasible,
  attribution, not changes to how a customer chooses which one to use. Building a Gmail-side
  webhook consumer to receive a `custom_args`-equivalent signal is not required by this SPEC.

## Constraints

- No auto-send: outreach to imported contacts still requires the existing human draft → approve →
  send gate. Nothing in this program introduces an auto-send path.
- All imported-contact sends MUST pass through the same guardrail chain as existing campaign
  sends: suppression list, `do_not_email`, the 50-emails/hour/site cap, and unsubscribe link. No
  parallel/bespoke sender may be built for imported contacts.
- Multi-tenancy: every imported contact and every candidate-tier identity is scoped to
  `Site.user_id == user.id`, exactly like all other visitor/identity data.
- `identity_status` is a free-text field — introducing a "candidate" value must not silently break
  or miscount any of the existing hardcoded `== "identified"` call sites (sweep eligibility,
  revive logic, dashboard/KPI counts) documented in research; each must be explicitly reconciled.
- Graph-sourced matches (RB2B, Leadpipe, Capturify) are permanently Candidate-tier — no score
  threshold, however high, may auto-promote a graph match to "Identified." Promotion to verified
  happens only via explicit human confirmation or an independent deterministic signal (form
  capture, `_bid` click).
- Candidate-tier identities remain emailable/exportable, but the draft/send pipeline (campaign
  drafting + `campaign_sender.py`) must enforce generic, non-personalized copy for Candidate
  recipients — no guessed name/title/company merge field may appear in subject or body for a
  Candidate-tier send.
- The click-to-verified resolution for Phase H must complete within 5 minutes of the click, but
  must NOT run synchronously inside the `/ingest` request path — it runs as a batch or triggered
  step after ingest returns, to avoid adding latency/risk to the visitor-facing hot path.
- Contact import is capped at 5,000 contacts per site (hard limit); an upload exceeding this limit
  is rejected with a clear, explicit error rather than partially imported or silently truncated.
- PII handling for imported contact lists follows the same rules as everywhere else in Beam: no
  plaintext email in logs, ciphertext + blind index storage pattern consistent with
  `VisitorEmail`/`beam_identity_graph`.
- Existing test patterns (`test_identity_classification.py`, `test_agent_origin_exclusion.py`,
  `test_outbound_identity_gate.py`) must be extended, not duplicated, for the new tier/import
  behaviors.

## Open Questions

None. All 5 decisions were resolved by the user on 03-08-26 — see "Locked Decisions" below.

## Locked Decisions

Resolved by the user on 03-08-26. These supersede the "Open decisions for user review" section
from the prior SPEC draft.

1. **Tier assignment:** ALL identity-graph matches (RB2B, Leadpipe, Capturify) are permanently
   Candidate tier — never auto-promoted to Identified/Verified regardless of confidence score.
   Verified status is reachable only via deterministic paths: self-declared/form capture, a `_bid`
   token click, or explicit human confirmation. This also resolves the prior "should Leadpipe and
   Capturify join the Candidate tier" question — yes, all three graph providers are in scope
   identically.
2. **Candidate emailability:** Candidates ARE emailable and exportable — Phase 0 does not lock them
   out of outreach. Instead, outreach copy sent to a Candidate-tier recipient must be generic: no
   guessed personal name, no guessed company/title personalization sourced from the graph match
   (e.g. "Hey there" instead of "Hi Janet"; no name/title/company merge field anywhere in
   subject/body). Verified-tier recipients keep full personalization as today. This is a new
   requirement on the campaign drafting and `campaign_sender.py` send pipeline.
3. **Import quota (v1):** 5,000 contacts per site, hard cap. An upload exceeding this limit is
   rejected with a clear error; no partial import, no silent truncation.
4. **Resolver timing:** A tokenized-link click must result in a named (verified) visitor visible on
   the dashboard within <=5 minutes of the click. This resolution runs as a batch/triggered step
   after ingest completes — it is explicitly NOT synchronous inside the `/ingest` hot path.

## Background / Research Findings

**Incident context (user-supplied, not on-disk):** RB2B returned a wrong person ("Janet Valla")
for a real US visitor; Beam displayed a flat green "Identified" badge with no confidence signal
and no way to correct it. No on-disk record of this exact incident exists — it is the anecdotal
trigger for this program, not a code-verifiable regression.

**Phase 0 research (full findings: `research-phase0.md`, RESEARCH session 03-08-26):**
- `IdentifiedVisitor.confidence_score` is already computed and stored but **nothing downstream
  reads it** — no floor exists from provider parsing through save, emailability, or the UI.
- RB2B's `ip_to_hem` returns a ranked `results[]` list; current code takes only `max(score)` and
  discards runner-up matches and ambiguity signal entirely (`rb2b.py:52-100`).
- `Visitor.identity_status` is a plain `String(30)`, not an enum — adding a `"candidate"` string
  value needs no migration. A new column would need one.
- A reusable UI/classification "caution badge" pattern already exists for company-level guesses
  (`identity_level`, `StatusBadge tone="warning"`) — a Candidate badge should mirror it.
- `confidence_score` is already in the Pydantic API schema but is missing from the frontend
  TypeScript type (`api-types.ts`) — it reaches the API but is dropped client-side today.
- ~8 call sites hardcode `identity_status == "identified"` (sweep eligibility in
  `resolution_runner.py`, revive logic, KPI/timeseries/dashboard counts) — each needs explicit
  reconciliation so Candidates aren't silently miscounted.
- `is_emailable_identity()` is called at exactly 3 sites (`campaign_sender.py`, `csv_exporter.py`,
  `routers/campaigns.py`) and has a documented "exactly 3 parameters" contract from a prior
  migration comment; none of the 3 call sites currently check `confidence_score`. Since the locked
  decision keeps Candidates emailable, this contract is not violated by a blocking gate — instead,
  the new personalization-gating requirement lands in the campaign draft/send composition layer,
  not in `is_emailable_identity()` itself.
- No demote/re-open path exists today; the manual-identify endpoint is the only human-driven
  mutator of `identity_status` post-resolution.
- Zero test coverage exists today for RB2B's score-normalization/ceiling logic.

**Phase H research (full findings: `research-phaseH.md`, RESEARCH session 03-08-26):**
- The `_bid` tokenized-link round trip (generate → click → decode → store into `VisitorEmail`) is
  fully implemented end-to-end and works today for campaign-generated links — this was previously
  assumed broken but research found no gap in the decode→store leg.
- Whether ingest synchronously triggers identity resolution right after a `utm_identify`-driven
  `VisitorEmail` write, versus deferring to a later resolve pass, was untraced at RESEARCH time;
  the locked decision resolves this explicitly — resolution must run as a batch/triggered step
  after ingest, not synchronously in the `/ingest` hot path, within a 5-minute bound.
- **No CSV/contact-list import surface exists anywhere in the codebase.** Manual identify and
  segment membership both require a pre-existing `Visitor` row; a contact who has never visited
  the site cannot be created via any existing path today. Phase H requires genuinely new import
  infrastructure.
- **Corrected 03-08-26 (outer-PVL finding):** link decoration is NOT a gap — `decorate_links()`
  runs unconditionally in `campaign_sender.py` (~line 284) BEFORE the SendGrid/Gmail channel fork
  (~line 291), so both channels already send decorated links. The real, narrower gap is
  `custom_args` only: it is passed exclusively at the SendGrid `sender.send()` call site (no
  Gmail-Connect equivalent), and no Gmail-side webhook exists to consume such a signal even if one
  were added.
- SendGrid open/click ingestion (`webhooks.py`) already exists as a *corroborating* signal source
  (`IdentitySignal`), gated behind `identity_signals_enabled` (default OFF) — it is structurally
  incapable of creating/upgrading an `IdentifiedVisitor` by design, and is separate from the
  always-on `_bid` identification mechanism.
- All required guardrails (suppression list, `do_not_email`, 50/hour/site cap, unsubscribe footer)
  live centrally in `campaign_sender.py` / `suppression.py` / `email_rate_limiter.py` and must be
  reused by any new imported-contact send path, not duplicated.
- No existing quota concept caps "how many contacts can a site import" — today's quotas are
  per-user monthly identity-*resolution* limits, a different concept. The locked decision sets a
  flat 5,000/site v1 cap rather than reusing or extending the resolution-quota system.
- Per-visitor rollup data needed to power a "hot known contacts" dashboard view appears to already
  exist (`visitor_aggregator.py`, `EnrichmentProfile`, `CampaignTouchpoint` timestamps), but whether
  the dashboard already has "hot"/recency sorting to reuse was not confirmed in this research pass.

**Later phases (explicitly deferred, not designed here):**
- **Phase F** — AI-timed self-identification widget on the customer's site.
- **Phase E** — agent-ready site config for AI-agent traffic.

## Amendments

- **2026-08-03** — corrected by outer-PVL finding: the SPEC previously claimed `gmail_sender.py` ships raw/undecorated links. Direct source read of `campaign_sender.py` disproved this — `decorate_links()` already runs unconditionally before the SendGrid/Gmail channel fork, so link decoration is already shared across both channels. The real remaining gap is narrower: `custom_args` (SendGrid-webhook attribution echo) has no Gmail equivalent. AC12, the relevant Out Of Scope bullet, and the Phase H research finding were corrected accordingly.
