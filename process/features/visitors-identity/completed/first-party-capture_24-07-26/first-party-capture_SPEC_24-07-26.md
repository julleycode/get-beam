---
name: spec:first-party-capture
description: "Expand tracker.js CLEAN first-party email capture points to feed the owned identity graph — user-review requirements doc, no implementation"
date: 24-07-26
feature: visitors-identity
---

# First-Party Email Capture Expansion — SPEC

## Summary

Beam currently captures visitor emails on customer sites through five mechanisms in
`tracker.js` (form submit, blur, change, `window.beamIdentify()`, and a decorated-link
token) plus one server-side path (email-marketing click binding). Every capture point only
fires when a real person actively interacts with a field on their own site, respects the
visitor's opt-out choice, and is validated before it's stored. This SPEC proposes widening
that same clean capture surface to catch email addresses that today's pattern-matching
misses (for example, a login form whose email field is named `username`) and to close small
gaps in browser autofill handling and widget/iframe coverage — without ever loosening the
"the visitor must have actively engaged with this field, this session" rule. Every email
captured this way is first-party data Beam owns outright, and it is the raw material that
feeds Beam's owned company/identity graph (built in the sibling `owned-data-layer` plan) —
more clean capture points on more sites means that graph grows faster, which is the one lever
Beam can pull at small scale that a bought-co-op competitor like RB2B cannot easily copy.

## User Stories / Jobs To Be Done

1. **As a Beam customer**, I want Beam to recognize an email typed into *any* form field on
   my site — not just fields literally named or typed "email" — so that I stop losing
   identifiable leads on login/signup forms that use generic field names like `username` or
   `contact`.
2. **As a Beam customer**, I want Beam to recognize when a visitor clicks a `mailto:` link on
   my site, so that an email a visitor volunteers by clicking "email us" isn't silently
   dropped.
3. **As a Beam customer**, I want Beam to recognize an email that arrives as a URL parameter
   (e.g. a magic-link or unsubscribe page), the same way it already recognizes Beam's own
   `_bid` token links, so that legitimate first-party email links from my own site convert
   into an identified visitor.
4. **As a Beam customer**, I want capture to work reliably when a visitor uses their browser's
   autofill to fill in an email field, across Chrome, Safari, and Firefox — not just the
   browsers where today's implementation happens to work.
5. **As a Beam customer running a chat widget or embedded checkout**, I want email capture to
   also work inside same-origin widgets and shadow-DOM components on my page, so I'm not
   missing leads simply because of how a third-party (same-origin) widget is built into my
   page.
6. **As a Beam customer**, I want to control, per site, which of these capture points are
   active (e.g. turn off `mailto:` capture, or opt in to URL-param capture only for specific
   pages), because not every site wants every mechanism running by default.
7. **As Beam (product owner of the owned identity graph)**, I want every new capture point to
   feed the same `visitor_emails` → identity-resolution pipeline the existing five mechanisms
   already feed, so the owned-graph flywheel (documented in the `owned-data-layer` plan)
   benefits from broader capture without needing a second ingestion path.
8. **As a visitor on a Beam customer's site**, I want to be certain that Beam only ever
   captures an email address I typed, clicked, or that appeared in a link I followed myself —
   never a value that was already sitting in a field before I touched it, never a value
   hidden from me, and never anything from my browser's local storage — so that identity
   capture never crosses into reading data I didn't actively provide this visit.

## What The User Wants (Behavioral Outcomes)

- When a visitor submits, blurs, or edits any text-type input field on the page, and that
  field's *value* (not just its name or `type` attribute) looks like a valid email address,
  Beam recognizes it as a captured email — regardless of what the field is named.
- When a visitor clicks a `mailto:` link, Beam recognizes the email address in that link as a
  captured email, the same way it already recognizes email addresses in ordinary clicked
  links today.
- When a visitor lands on a page carrying a plaintext (or Beam-decorated) email address in the
  URL, Beam recognizes and captures it the same way it already does for the existing `_bid`
  token, and never writes the plaintext value anywhere (logs, storage) — it is hashed or
  encrypted immediately.
- When a visitor's browser autofills an email field, Beam recognizes the autofilled value
  consistently across Chromium-based browsers, Safari, and Firefox.
- When a visitor interacts with a same-origin embedded widget (chat box, embedded checkout
  built with shadow DOM), Beam's existing capture logic also observes interactions inside that
  widget, the same way it observes the main page. Cross-origin embedded content (e.g. Stripe's
  own hosted iframe) is out of reach and stays out of scope.
- A site owner can turn individual new capture mechanisms on or off per site through the
  tracker install configuration, without needing a code change.
- Every existing safeguard continues to apply unchanged to every new capture point: visitor
  opt-out (GPC/DNT) blocks capture entirely; captured values are format/deliverability
  validated before being stored; the same email is never stored twice for the same visitor;
  and a visitor who has been marked "do not resolve" stays excluded.
- No capture point ever reads a field's value unless the visitor actively typed into it,
  clicked it, or arrived via a URL/link they followed — never a pre-filled, hidden, or
  storage-sourced value.

## Flow / State Diagram

```
Visitor on customer site
        │
        ▼
  [OPTOUT check: GPC/DNT?] ──yes──▶ no capture attempted (existing gate, unchanged)
        │ no
        ▼
  Visitor actively interacts
        │
   ┌────┴─────────────────────────────────────────────────────────────┐
   │ (existing, unchanged)              │ (this SPEC — new/extended)  │
   ▼                                    ▼
 form submit / blur / change      value-based match (any field, not just
 on a field literally named/      "email"-named) on submit/blur/change
 typed "email"                              │
   │                              mailto: link click
 window.beamIdentify()                      │
   │                              URL email param (hash/encrypt immediately)
 _bid decorated-link token                  │
   │                              browser-autofill event, cross-browser
 server-side ESP click bind                 │
 (click.py)                       same-origin iframe / shadow DOM listener
   │                                        │
   └────────────────┬───────────────────────┘
                     ▼
         looksEmail() format check
                     ▼
              pushEvent → flush (still OPTOUT-gated)
                     ▼
        server: validate_email() (format + disposable + MX)
                     ▼
     upsert visitor_emails (site_id, visitor_id, email) — dedup unique
                     ▼
        feeds identity resolution → owned company/identity graph
        (owned-data-layer plan — company_graph / identity_signals)
```

## Acceptance Criteria (Testable Outcomes)

1. **Value-based field matching**: submitting, blurring, or changing a text-type input whose
   *value* passes an email-format check is captured, even when the field's `name`/`id`/`type`
   contains no "email" substring (e.g. `name="username"` holding `jane@co.com`).
   `proven by:` Playwright tracker harness scenario — login-style form, non-email-named field.
   `strategy:` Fully-Automated
2. **Existing name/type-based matching still works** (regression guard) — fields literally
   typed `email` or named/id-containing "email" continue to be captured exactly as today.
   `proven by:` Playwright tracker harness scenario — existing form_email_capture flow.
   `strategy:` Fully-Automated
3. **mailto: click capture** — clicking an `<a href="mailto:...">` link results in a captured
   email matching the address in the href.
   `proven by:` Playwright tracker harness scenario — mailto link click.
   `strategy:` Fully-Automated
4. **URL email param capture** — a page loaded with a plaintext or encoded email query
   parameter results in a captured email, and the raw plaintext value is never written to logs
   or persisted storage unencrypted.
   `proven by:` Playwright tracker harness scenario (capture) + log-output assertion
   (no-plaintext-in-logs).
   `strategy:` Hybrid (automated capture test + a manual/automated log-scan check)
5. **Cross-browser autofill capture** — an email autofilled by the browser into a recognized
   field is captured in Chromium, Safari (WebKit), and Firefox test runs.
   `proven by:` Playwright cross-browser matrix run (chromium/webkit/firefox projects) against
   the tracker harness.
   `strategy:` Fully-Automated
6. **Same-origin widget/shadow-DOM capture** — an email submitted inside a same-origin
   shadow-DOM component is captured using the same listener logic as the main document.
   `proven by:` Playwright tracker harness scenario with a shadow-DOM test fixture.
   `strategy:` Fully-Automated
7. **Cross-origin iframe is explicitly NOT captured** — an email typed inside a cross-origin
   iframe fixture produces no capture event, confirming the stated technical/consent boundary
   holds.
   `proven by:` Playwright tracker harness scenario, cross-origin iframe fixture, assert
   zero capture events.
   `strategy:` Fully-Automated
8. **Consent/privacy guardrail (all capture points)** — no capture point fires for a field the
   visitor did not actively type into, click, or arrive via, this session: a field
   pre-populated by site JavaScript before any visitor interaction, and a `type="hidden"`
   field carrying an email value, produce zero capture events even though their values would
   otherwise pass the email-format check.
   `proven by:` Playwright tracker harness scenario — prefilled-untouched field + hidden field,
   assert zero capture events.
   `strategy:` Fully-Automated
9. **OPTOUT respected on every new capture point** — with GPC/DNT signaled, none of the new
   capture points (value-based match, mailto, URL param, autofill, shadow-DOM) produce a
   captured email or network call.
   `proven by:` Playwright tracker harness scenario, OPTOUT flag set, assert zero capture
   events/network calls across all new mechanisms.
   `strategy:` Fully-Automated
10. **Server-side validation and dedup unchanged** — every new capture path is validated
    server-side by the existing `validate_email` check (format + disposable + MX) and honors
    the existing `(site_id, visitor_id, email)` unique constraint; an invalid or duplicate
    email from a new capture point is rejected/dropped the same way an invalid email from the
    existing form-submit path is today.
    `proven by:` backend integration test — new capture event types through
    `_process_signal_events`, invalid-email and duplicate-email cases.
    `strategy:` Fully-Automated
11. **`do_not_resolve` sticky flag still excludes captured visitors** — a visitor previously
    marked `do_not_resolve` produces no new identity-resolution work even if a new capture
    point fires an email event for them.
    `proven by:` backend integration test — do_not_resolve visitor + new-mechanism capture
    event.
    `strategy:` Fully-Automated
12. **Per-site capture configuration** — a site owner can disable an individual new capture
    mechanism (e.g. `data-capture-mailto="off"`) and that mechanism produces no capture events
    on that site's install, while other mechanisms remain active.
    `proven by:` Playwright tracker harness scenario — config attribute toggled off, assert
    that mechanism alone is silent.
    `strategy:` Fully-Automated
13. **`source` enum values are validated, not silently accepted** — every event `source` value
    emitted by the tracker (including any new source strings introduced by this work) maps to
    a known, documented value; an unrecognized source value is rejected or normalized rather
    than stored as free text.
    `proven by:` backend unit test — known sources accepted, unknown source rejected/normalized.
    `strategy:` Fully-Automated
14. **PII-safe logging on every new path** — structlog log lines for new capture points log
    only keys/domains/booleans (matching the existing `email_domain` pattern), never the full
    email address or raw URL-param plaintext.
    `proven by:` unit test asserting log call arguments contain no `@`-containing full email
    string.
    `strategy:` Fully-Automated
15. **Playwright tracker.js test harness exists as a prerequisite** — before any new capture
    point ships, a working Playwright harness exercises `tracker.js` capture logic in a real
    browser context (today's harness coverage for `tracker.js` capture logic is empty).
    `proven by:` the harness itself, plus at least one passing baseline scenario covering an
    existing (pre-SPEC) capture mechanism.
    `strategy:` Fully-Automated

## Out Of Scope

- **Prefilled/hydrated email fields the visitor never touched this session** — capturing a
  value the site injected into a field before any visitor interaction reads data the visitor
  didn't provide this visit; this is session-replay territory, not first-party capture, and is
  explicitly excluded (see Acceptance Criterion 8).
- **Hidden fields** — a `type="hidden"` field's value was placed there by site code, not typed
  by the visitor; treating it as "captured" would be indistinguishable from scraping
  site-injected data (see Acceptance Criterion 8).
- **localStorage / sessionStorage / `dataLayer` scraping** — reading another system's client
  storage to find an email is not an interaction Beam observed the visitor perform; it's
  reading a different system's data store, which sits in gray/red territory for consent
  purposes and is excluded entirely.
- **Cross-origin iframe capture** (e.g. Stripe Elements, other third-party hosted payment
  fields) — both a technical boundary (same-origin policy blocks DOM access) and a consent
  boundary (that content belongs to a different first party); explicitly out of reach (see
  Acceptance Criterion 7).
- **Keystroke-before-submit logging** — logging characters as they're typed, before a field is
  submitted/blurred/changed, is exactly the pattern that creates CIPA (California wiretap
  statute) exposure; never implemented, at any point.
- **Buying or renting hashed-email datasets from third parties** — this SPEC is about
  first-party capture Beam observes directly on a customer's own site; acquiring third-party
  hashed-email inventory is a different, separate product/legal decision and is not addressed
  here.
- **Backend graph/schema changes to `company_graph` / `identity_signals`** — those tables and
  their resolution logic were built in the `owned-data-layer` plan (already shipped); this
  SPEC only widens what feeds into `visitor_emails`, it does not modify how that data is
  resolved into companies or identities downstream.
- **Choosing the actual implementation approach** (how the value-based matcher is coded, which
  DOM APIs are used for shadow-DOM traversal, exact config attribute names) — that is
  INNOVATE/PLAN's job, not this SPEC's.

## Constraints

- Every new capture point MUST be gated by the existing OPTOUT (GPC/DNT) check before any
  event is queued or sent — no new code path may bypass `flush()`'s consent gate.
- Every captured email MUST pass the existing server-side `validate_email` check (format +
  disposable-domain + MX) before being stored; no new capture point stores an unvalidated
  email.
- Every captured email MUST continue to respect the `(site_id, visitor_id, email)` unique
  constraint on `visitor_emails` — no new capture point may write a duplicate row for an
  already-captured email.
- A visitor with `do_not_resolve` set MUST NOT trigger new identity-resolution work as a
  result of any new capture point, exactly as today.
- No new capture point may read a field value the visitor did not actively provide this
  session (typed, clicked, or arrived via) — this is a hard product/legal boundary, not a
  preference (see Out Of Scope: prefilled fields, hidden fields, storage scraping).
- No plaintext email value from a URL parameter may be logged or persisted unencrypted; it
  must be hashed or encrypted at the point of capture, mirroring the existing `_bid` Fernet
  pattern.
- All structlog log lines touching captured email data must log only keys, domains, or
  booleans — never the full email address — matching the existing `email_domain` pattern in
  `apps/api/routers/events.py`.
- A Playwright test harness for `tracker.js` capture logic is a hard prerequisite: no new
  capture point may ship without an automated test proving its behavior, because none exists
  today.
- New capture mechanisms must be configurable per-site (able to be turned off) where they are
  more consent-sensitive than the existing baseline (e.g. mailto capture, URL-param capture).
- This work must not change or duplicate the `owned-data-layer` plan's `company_graph` /
  `identity_signals` schema or resolution logic — it is strictly an upstream feed into the
  existing `visitor_emails` table.

## Open Questions

1. **Safari/Firefox autofill event behavior** — today's `change` event handling is known to
   work reliably in Chromium but is unconfirmed in Safari and Firefox for autofilled (as
   opposed to manually typed) values. Needs an empirical browser probe before PLAN can commit
   to a specific event-listening strategy for Acceptance Criterion 5.
   Owner: next phase (INNOVATE/PLAN, via `vc-feasibility-test` probe if source inspection is
   insufficient).
2. **Multi-source provenance** — `visitor_emails` currently keeps only the first-writer
   `source` value per `(site_id, visitor_id, email)` due to the unique constraint; if the same
   email is later captured by a second, different mechanism, that second source is silently
   dropped rather than recorded. Should the SPEC's new capture points change this (e.g. track
   all sources an email was captured through), or is first-writer-wins acceptable to carry
   forward unchanged?
   Owner: PLAN (product decision — does provenance depth matter enough to justify a schema
   change, or is it out of scope for this program too).
3. **Formal CLEAN/RED capture-technique classification** — this SPEC's Out Of Scope section
   draws a line by example (prefilled fields, hidden fields, storage scraping, cross-origin
   iframes = excluded), but there is no single formally documented CLEAN/RED policy in
   `PRODUCT_ROADMAP.md` or a PII policy doc that future capture-point proposals can be checked
   against without re-litigating the reasoning each time.
   Owner: backlog — recommend a follow-up documentation task (not blocking this SPEC), tracked
   separately from PLAN/EXECUTE for this feature.

*(None of the above block PLAN from proceeding — Q1 is resolvable via a feasibility probe
during INNOVATE/PLAN; Q2 and Q3 are product-scope decisions PLAN can make explicitly and
document, not intent ambiguities.)*

## Background / Research Findings

**Owned-graph relationship (why this SPEC exists):** the `owned-data-layer` plan
(`process/features/visitors-identity/active/owned-data-layer_23-07-26/owned-data-layer_PLAN_23-07-26.md`,
shipped 23-07-26) built the durable `company_graph` and `identity_signals` tables that make
Beam's identity data reusable across tenants instead of re-bought from providers each time.
That graph's growth is bottlenecked by how much first-party seed PII (emails Beam captured
directly, not rented) flows in. This SPEC does not touch that graph or its schema — it widens
the upstream feed (`visitor_emails`) so more of that seed PII is captured per site.

**Current capture surface (verified in `apps/pixel/src/tracker.js`, confirmed live 24-07-26):**
- Form submit: capture-phase listener finds `input[type='email'], input[name*='email'],
  input[name*='Email']` within the submitted form (tracker.js ~296-301).
- Field blur/change: same name/type-based `isEmailField()` check fires on blur (capture phase,
  since blur doesn't bubble) and change (tracker.js ~285-306).
- `window.beamIdentify(email)` — manual JS API for site code to explicitly identify a visitor.
- `_bid` URL param — a Fernet-encrypted token, decoded server-side (`decode_bid`), used for
  Beam-decorated links (e.g. from email campaigns).
- Server-side: SendGrid click-tracking bind in `click.py` links opens/clicks back to a known
  recipient email (separate from tracker.js).
- All of the above funnel into `_process_signal_events()` in `apps/api/routers/events.py`,
  which validates via `validate_email()` (format + disposable-domain + MX), sanitizes/caps the
  `source` string, and upserts into `visitor_emails` with a `(site_id, visitor_id, email)`
  unique constraint (`apps/api/models/visitor_email.py`). Logging uses `email_domain` only
  (never full address) — the existing pattern this SPEC's new paths must match.
- Every capture path is gated by the pixel's `OPTOUT` flag (GPC/DNT honored, `tracker.js`
  consent logic ~324-347), and `do_not_resolve` is a sticky visitor-level flag aggregated from
  event-level optout signals.

**Gaps identified by research (the "approved proposal" driving this SPEC):**
- The name/type-based `isEmailField()` matcher misses any field holding a valid email whose
  name/id doesn't contain "email" — e.g. `name="username"` on a login form. A value-based
  matcher (check the *value*, not the field name) is the highest-yield gap to close.
- `mailto:` links are already observed generically by the existing click handler
  (tracker.js ~421-435: pushes `element_href`), but the href isn't parsed for a `mailto:`
  email today — low-risk to add since it only observes a click the visitor already initiated.
- URL email params beyond the existing `_bid` token pattern (e.g. magic-link or unsubscribe
  `?email=` plaintext params) are not captured; if added, they carry a hard requirement to
  hash/encrypt immediately given URL-embedded plaintext email is a known privacy anti-pattern.
- Cross-browser autofill behavior for `change` events is inconsistently documented/tested
  across Chromium, Safari, and Firefox — flagged as Open Question 1 above.
- Shadow DOM and same-origin iframe content (e.g. embedded chat widgets) are not currently
  reached by the document-level event listeners; cross-origin iframes (e.g. Stripe Elements)
  are a hard technical + consent boundary and stay out of scope.
- `tracker.js` has zero existing automated test coverage for its capture logic — any new
  capture point requires this harness as a prerequisite, not an afterthought.
- Capture today is all-or-nothing per site install; site owners have no way to opt specific
  points in/out, which matters more once more consent-sensitive mechanisms (mailto, URL-param)
  are added.
- The `source` column's docstring (`apps/api/models/visitor_email.py`) documents only
  `form`/`utm`/`manual`, but the pixel already emits `login`/`checkout`/`newsletter`/`input`/
  `identify` — a drift between documented and actual values that this SPEC's Acceptance
  Criterion 13 requires be resolved (formalized enum + validation) rather than carried forward
  silently.

**Existing safety gates every new capture point must reuse (not reinvent):** OPTOUT (GPC/DNT),
`validate_email` (format + disposable + MX), `visitor_emails` unique constraint (dedup),
`do_not_resolve` sticky exclusion, and the domain-only logging pattern.
