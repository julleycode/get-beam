---
name: spec:browser-capture-trust-tier
description: "SPEC — de-privilege unauthenticated browser-asserted email captures: candidate tier + human confirmation required before emailability, cross-tenant graph write, or paid-provider spend"
date: 15-08-26
feature: visitors-identity
metadata:
  node_type: spec
  type: spec
  feature: visitors-identity
  cross_ref: "pixel (ingest endpoint apps/api/routers/events.py belongs to the pixel feature; the trust-tier change itself is an identity concern, so this task lives under visitors-identity)"
---

# SPEC — Browser-Capture Trust Tier

**TL;DR:** Anyone on the internet can read a customer's public site ID from their page source, POST a fake "the visitor typed this email" event to Beam's open tracking endpoint, and Beam will treat that email as a fully trusted, emailable, cross-tenant identity. The fix: browser-asserted email captures start as unconfirmed **candidates** — visible to the site owner, but not emailable, not shared to the cross-tenant graph, and not worth a paid lookup — until a human clicks confirm. The confirmation machinery already exists; this de-privileges the input, it does not delete the feature.

## Summary

Beam's tracking pixel sends events to an endpoint that, by necessity, accepts requests from any browser without a login. One of those events says "the visitor typed this email into a form." Today Beam treats that claim as proof: the email immediately becomes a fully identified visitor, becomes eligible for outreach and export, and is written into the shared identity graph that every other Beam customer benefits from.

The problem is that the claim is free to fake. The site ID needed to send events is printed in the customer's public page source. An attacker with `curl` can therefore plant any email address on any customer's dashboard, poison the shared graph for all customers, and potentially get the victim's own outreach tools to email a person who never visited the site.

This SPEC requires that a browser-asserted email capture starts life as an **unconfirmed candidate**. The site owner still sees it. But it cannot be emailed, exported, pushed to a CRM or ad audience, written to the shared graph, or used to justify spending money on a paid identity lookup — until a human being looks at it and confirms it. That human-confirmation machinery already shipped (the candidate tier with its confirm/reject review flow); this work routes browser captures through it.

**Accepted cost (user decision, locked):** genuine first-party captures also require one confirmation click and no longer become "identified" automatically. The feature is de-privileged, not deleted.

## User Stories / Jobs To Be Done

- **As a site owner**, I want an email that merely *claims* to come from my website's forms to be held for my review, so that a stranger cannot plant fake contacts in my dashboard, corrupt my visitor data, or trick my outreach drafts into emailing someone who never visited.
- **As a site owner**, I want to still see every captured email — including unconfirmed ones — with a clear "needs review" state, so that a real signup is never silently lost and one click promotes it to a full contact.
- **As a Beam customer on another site**, I want the shared cross-customer identity graph to contain only vetted identities, so that an attacker poisoning one site's data cannot make my dashboard mis-identify my visitors.
- **As Beam (the business)**, I want unvetted claims to never trigger a billed identity-provider call, so that an attacker cannot burn a customer's daily resolution budget or Beam's provider spend with a script.
- **Abuse case (to be defeated) — as an attacker**, I read a target's public page source for their site ID, POST a fabricated email-capture event (optionally with a fabricated fingerprint and a spoofed capture-source label), and expect the victim's dashboard to show my chosen email as a verified visitor, the shared graph to store it, and outreach to target it. **Every step of that expectation must fail** except one: the fake appears as an unconfirmed candidate that a human will look at — and a human is the one thing the attacker's script cannot satisfy.

## What The User Wants (Behavioral Outcomes)

1. **A browser-asserted email capture lands in a "needs review" state.** It shows on the visitors dashboard as an unconfirmed candidate — same review state the dashboard already uses for probabilistic graph guesses — not as a confirmed identified visitor.
2. **While unconfirmed, the capture has no outbound privileges.** It is excluded from campaign sending, CSV export, CRM push, and ad-audience upload. It does not appear anywhere an email address becomes an outreach target.
3. **While unconfirmed, the capture stays inside the one site.** Nothing is written to the shared cross-customer identity graph, and no cross-customer contribution credit accrues.
4. **While unconfirmed, the capture costs nothing.** No paid identity or enrichment provider is called because of it.
5. **The server decides what kind of capture it is.** A request cannot upgrade its own trust by labeling itself as an operator-entered or email-click-verified capture; those labels are only honored when the server itself produced them.
6. **One human click promotes it.** The site owner reviews the candidate and confirms it using the existing confirm flow; after confirmation it gains full privileges (emailable, exportable, graph-eligible). Rejecting works the same as rejecting any other candidate.
7. **Nothing else changes.** Ordinary analytics events keep flowing; already-deployed pixel snippets on customer pages keep working with zero customer action.

## Flow / State Diagram

```
                       (public internet — no login possible here)
  Real visitor types email          Attacker with curl + public site ID
            │                                     │
            └────────────┬────────────────────────┘
                         ▼
             Beam ingest endpoint (open by design)
                         │  email-capture event
                         ▼
        ┌──────────────────────────────────────┐
        │  TODAY (defect)                      │
        │  capture ──► "identified"            │
        │   ├── emailable / exportable  ✗ BAD  │
        │   ├── writes cross-tenant graph ✗    │
        │   └── can trigger paid lookup   ✗    │
        └──────────────────────────────────────┘

        ┌──────────────────────────────────────┐
        │  REQUIRED (this SPEC)                │
        │  capture ──► CANDIDATE (unconfirmed) │
        │   ├── visible to site owner    ✓     │
        │   ├── NOT emailable/exportable ✓     │
        │   ├── NO cross-tenant graph    ✓     │
        │   └── NO paid provider spend   ✓     │
        └───────────────┬──────────────────────┘
                        │
            site owner reviews (human gate —
            the step an attacker cannot script)
                ┌───────┴────────┐
                ▼                ▼
            CONFIRM           REJECT
                │                │
                ▼                ▼
          IDENTIFIED         back to anonymous
          (full privileges:  (existing reject
           emailable, graph,  behavior)
           export)
```

## Acceptance Criteria (Testable Outcomes)

Strategies: **Fully-Automated** (unit/integration test, no human), **Hybrid** (automated with an operator-run leg), **Agent-Probe** (agent manually exercises it once), **needs-live-provider** (requires a billed third-party call).

**AC-1 — An injected capture is not emailable.** An email-capture event POSTed to the open ingest endpoint by a party that is not the pixel (plain HTTP client, valid public site ID) produces an identity that the shared emailability check refuses.
   proven by: integration test — synthetic ingest POST → resolver runs → emailability helper returns False for the resulting identity; plus unit tests on the classification helper for the browser-capture provider class.
   strategy: Fully-Automated

**AC-2 — An injected capture reaches no outbound sink.** The injected identity is absent from campaign-send selection, CSV export output, CRM push payloads, and ad-audience upload membership.
   proven by: integration tests per sink asserting the candidate row is excluded (mirroring the existing agent-origin exclusion regression suite). Precondition: the sink census in Known Unknowns #1 must be completed first so no sink is missed.
   strategy: Fully-Automated

**AC-3 — An injected capture does not write the cross-tenant graph and does not accrue co-op credit.** After the injected capture resolves, the shared identity-graph table has no new row for that email/fingerprint, and no cross-customer contribution is recorded.
   proven by: integration test — ingest POST → resolve → assert zero graph rows and zero contribution ledger rows (non-vacuous: the same flow with a confirmed identity must produce the row).
   strategy: Fully-Automated

**AC-4 — An injected capture triggers no billed provider call.** The unconfirmed capture never causes a paid identity/enrichment provider request and never decrements the site's daily resolution budget on its behalf.
   proven by: integration test in mock-external-APIs mode asserting zero provider-client invocations attributable to the candidate capture; budget counter unchanged.
   strategy: Fully-Automated

**AC-5 — The server, not the client, determines the capture channel.** An ingest-path event that labels itself with a server-only capture source (operator-entered, email-click-verified, or link-token) is not honored at that trust level: the stored capture is still treated as browser-asserted, and its review state is the same as any other browser capture. Server-side writers of those labels (the click-bind route, operator actions) keep their existing trust.
   proven by: unit tests on the source-normalization path for spoofed values + integration test asserting a spoofed `email_click`-labeled ingest capture still lands unconfirmed while a genuine server-side click-bind row keeps its current behavior.
   strategy: Fully-Automated

**AC-6 — Self-corroboration by a second request does not promote.** A second POST re-asserting the same email (same or different fabricated fingerprint, from the attacker-controlled client) does not raise the capture's trust, confirm it, or unlock any privilege from AC-1..AC-4.
   proven by: integration test — two sequential injected batches for the same email → still candidate, still zero graph rows, still not emailable.
   strategy: Fully-Automated

**AC-7 — Human confirmation promotes to full privilege.** The site owner confirming the candidate through the existing confirm-candidate flow promotes it to identified with a confirmation timestamp; after confirmation it is emailable, exportable, and eligible for the cross-tenant graph under the existing rules. Reject returns it to anonymous per existing reject behavior.
   proven by: integration test — inject → confirm via the confirm endpoint → emailability True, sink inclusion, graph-write path now permitted; reject leg asserted separately. UI leg (badge + confirm button renders for this capture class): Playwright, currently gated on the known Clerk auth-harness gap — until that harness lands, the UI leg is an operator/agent manual check.
   strategy: Hybrid (API legs Fully-Automated; dashboard UI leg Agent-Probe until the e2e auth harness exists)

**AC-8 — Genuine captures still appear.** A legitimate email capture from the pixel still creates a visible visitor-email record and a reviewable candidate on the dashboard — the capture pipeline is de-privileged, not disabled. The count of captures shown to the owner is unchanged from today for the same input.
   proven by: integration test — pixel-shaped ingest batch → visitor-email row exists with its capture source, candidate visible via the visitors API.
   strategy: Fully-Automated

**AC-9 — Non-identity events are untouched.** The six non-PII event types accepted at ingest today keep working byte-identically: same acceptance, same storage, same analytics rollups, no new review state.
   proven by: existing integration ingest suite stays green (regression gate — the current 537-passing integration lane must not lose an ingest test), plus a targeted no-behavior-change assertion per event type.
   strategy: Fully-Automated

**AC-10 — Deployed pixels keep working with no snippet change.** The already-published snippet attributes are untouched; only server behavior (and at most the globally-served script body) changes. An existing customer page continues to send and have accepted every event type with zero re-paste.
   proven by: pixel e2e harness (existing Playwright projects) — page with the current snippet shape sends capture + non-capture events successfully; plus a check that no new required snippet attribute was introduced.
   strategy: Fully-Automated (browser e2e)

**AC-11 — Existing candidate-tier behavior for graph guesses is unchanged.** RB2B/Leadpipe/Capturify/network-graph candidates keep their current, previously-locked semantics (including their emailability posture) — this SPEC changes only the browser-asserted capture class.
   proven by: existing identity-honesty Phase 1 regression tests stay green; new unit test pinning that the graph-candidate provider set and its emailability outcome are unaffected.
   strategy: Fully-Automated

## Out Of Scope

- **Authenticating the pixel request (HMAC signing, API keys, nonces).** Structurally impossible: the tracker script is public with wildcard cross-origin access, any secret shipped to a browser is public, and the unload-path transport cannot carry custom headers. No amount of client-side signing makes a browser assertion trustworthy.
- **Turnstile / edge bot attestation.** Void while the hosting origin is directly reachable, bypassing the CDN edge entirely (a documented, accepted gap with its own backlog item).
- **Fixing the forgeable proxy-IP header.** Real defect, orthogonal to this one; it has its own accepted-tradeoff record and backlog.
- **Hardening the UTM identify token against replay** (TTL / site binding). Separate problem: that token cannot be minted by an attacker, only replayed; different threat, different fix.
- **Signing the durable server-cookie visitor ID.** Separate change touching a live 365-day cookie on every deployed install; not needed to close this defect.
- **Changing the emailability posture of existing graph-guess candidates** (RB2B, Leadpipe, Capturify, cross-customer network). Their "candidates ARE emailable" decision was locked in the identity-honesty program and is not re-opened here (see Constraints).
- **Bulk rate-limiting or anomaly-scoring of capture events.** The ingest-abuse-hardening layers already exist and are complementary; this SPEC is about trust level, not volume.
- **Retroactive cleanup of graph rows already seeded by past browser captures.** Depends on the unmeasured share of such rows (Known Unknowns #4); decide after measurement, likely its own task.

## Constraints

1. **The ingest endpoint stays open.** It must keep accepting anonymous browser traffic — that is what a tracking pixel is. The fix is trust-tiering, not authentication.
2. **No snippet attribute changes.** Customer HTML is frozen at the attributes generated once at install; server-side and served-script-body changes are free, new snippet attributes are not.
3. **Client-supplied fields can never be the trust discriminator.** The capture-source label, the fingerprint, and the client visitor ID are all attacker-controlled or attacker-forgeable. Trust must derive from facts the server established itself.
4. **Reuse the existing promotion machinery.** Promotion is the shipped candidate confirm/reject review flow with its confirmation timestamp — no new promotion system may be invented.
5. **Deliberate divergence from the identity-honesty Phase 0 lock, by explicit user decision:** Phase 0 locked that graph-guess candidates ARE emailable/exportable. Browser-asserted captures get a STRICTER posture — not emailable, not exportable, no graph write, no paid spend, until confirmed. Both postures coexist; downstream phases must not "harmonize" one onto the other in either direction.
6. **Existing hard guardrails stay intact:** agent-origin exclusion, abuse-flag exclusion, privacy holds, suppression, consent gating, and the EU consent-hold ordering in the pixel are all untouched.
7. **Pixel size budget:** if any served-script change is needed, the minified pixel must stay under its enforced gzipped ceiling (about 100 bytes of headroom remain).
8. **The corroboration helper that exists today cannot substitute for confirmation.** It has zero callers, structurally cannot upgrade an identity, and requires Beam to have already emailed the address — circular for a new capture.
9. **Mock-mode parity:** every new behavior must work with external APIs mocked, per repo convention.
10. **Verification environment:** integration gates run against the local Docker Postgres/Redis; nothing in this work may run against the production database (the repo's default env points at production — a standing safety rule).

## Open Questions

None. The tier decision, the promotion mechanism, and the accepted cost are locked user decisions. Genuinely unresolved items are recorded as Known Unknowns below — they are research/measurement tasks for the next phases, not intent ambiguities.

## Background / Research Findings

Two research workflow runs partially failed on environment errors; the orchestrator then independently re-verified every load-bearing claim by reading source, and this SPEC's author re-verified each citation below on 15-08-26. Line numbers drift; symbols are the stable anchors.

### Root cause (the spine)

The defect is NOT "the endpoint lacks authentication." It is a **falsified trust premise**: `apps/api/services/identity_classification.py` excludes `form_capture` from `GRAPH_CANDIDATE_PROVIDERS` (lines ~50-55) on the written ground that it is a "deterministic first-party" signal — a premise only true if the ingest endpoint authenticated its caller. It does not: `@router.post("/ingest")` (`apps/api/routers/events.py:167`) depends only on `get_db` and `stash_site_id`. `form_capture` sits in `PERSON_LEVEL_PROVIDERS` (`identity_classification.py:16`), so `is_emailable_identity()` (lines 119-154) returns True for it; the only overrides are `source_agent_visit_id` and `is_abuse_flagged`, neither set on an injected capture.

### Verified attack path

1. `events.py:167-172` — `/ingest` has no auth dependency, signature, or nonce.
2. `events.py:~205-247` — the only caller checks: site exists, `tracking_enabled` is True. The `site_id` is public (printed into the snippet in every customer's page source; `apps/api/routers/sites.py:499-502`).
3. `events.py:750-769` — attacker-supplied `event.email` on a `form_email_capture` event becomes a `visitor_emails` row (only an email-validity check applies).
4. `identity_resolver.py:~376-386` (prior-signal check) — selects `VisitorEmail.email` only, filtered on site/visitor, newest-first; it never reads `source`.
5. `identity_resolver.py:~404-421` — `_save_identified(..., "form_capture")`, provider hardcoded as a string literal; confidence 0.80-0.85.
6. `identity_resolver.py:~1381-1409` — `_upsert_beam_identity` writes `BeamIdentityNode` on conflict key `(fingerprint, email)` — the cross-tenant table every other customer's resolver reads.
7. `identity_resolver.py:~1308-1313` — identity-coop contribution accrues `if wrote_graph`.

### Verified constraints that kill the obvious fixes

- **A browser cannot hold a secret.** `tracker.min.js` served at `/pixel/tracker.js` with `Access-Control-Allow-Origin: "*"` (`apps/api/main.py:597-612`).
- **Snippet attributes are frozen.** `<script src=... data-site=... data-api=... defer>` generated once (`sites.py:499-504`); script BODY updates globally on deploy, a new ATTRIBUTE requires every customer to re-paste.
- **Pixel headroom:** ~101 bytes gzipped (measured 6043 vs the 6144 ceiling asserted in `tests/unit/test_pixel_fingerprint.py::test_under_6kb_gzipped`).
- **`sendBeacon` cannot set custom headers** (`apps/pixel/src/tracker.js:~334-341`, `text/plain` Blob) — header-based signatures would break the unload path.
- **`event.source` is attacker-controlled.** `schemas/events.py:44` — free label, max 20 chars. `normalize_source` (`models/visitor_email.py:~33-42`) returns any value in `VISITOR_EMAIL_SOURCES` verbatim — including `manual` and `email_click`, otherwise written only server-side (`routers/click.py`). A spoofed `source:"email_click"` row is byte-identical to a genuine ESP click-bind. **`source` can never be the trust discriminator.**
- **No working corroboration signal.** `corroborate_identity()` (`services/identity_signals.py`) has zero call sites in `apps/api` (re-verified by grep 15-08-26: only a comment in `config.py:918` and its own module docstring reference it). It also structurally cannot upgrade an identity, and needs a SendGrid open/click — which needs Beam to have already emailed the address.
- **`_rta_svid` is not server-authenticated.** Its value is the client-supplied `batch.visitor_id`, unsigned (`events.py:~570-590`); `httponly` stops page JS, not `curl`.
- **`_fp` validation is prefix + length only** (`events.py:~616-626`: `fp_`/`fp2_` prefix, ≤64 chars) — the attacker controls both halves of the graph conflict key and can attempt self-corroboration with a second POST.
- **Turnstile/edge attestation is void** while the Railway origin is directly reachable (`config.py:~268-275`, the `ingest_trust_cf_connecting_ip` accepted tradeoff notes direct-origin reachability; origin lock to CF ranges is backlogged).

### Existing machinery to reuse (verified on disk)

- Candidate tier: `Visitor.identity_status = "candidate"`, shipped by identity-honesty Phase 1 (`process/features/visitors-identity/active/identity-program_03-08-26/`, Phase 0/1 artifacts). `is_verified_identity()` treats only `"identified"` as confirmed.
- Promotion: `POST /{site_id}/{visitor_id}/confirm-candidate` (`routers/visitors.py:1290-1323`) promotes to `identified` and stamps `IdentifiedVisitor.confirmed_at` (`models/visitor.py:258`); its docstring already states human confirmation is the only promotion path besides deterministic first-party signals — this SPEC removes browser-asserted captures from the "deterministic first-party" side of that sentence.
- Reject: reject-candidate returns the visitor to anonymous and re-enables normal resolution (`routers/visitors.py:~1261`, and the `/resolve` endpoint's explicit candidate branch at `~915-930`).
- Exclusion-regression pattern to copy: `tests/unit/test_agent_origin_exclusion.py` (the agent-origin guardrail suite).
- Prior locked decision this diverges from (Constraint 5): identity-program SPEC 03-08-26, "Candidate-tier identities ARE emailable and exportable" — governs graph-guess candidates only, unchanged by this SPEC.

### Test-context grounding

Per `process/context/tests/all-tests.md`: unit lane (no deps) `1324 passed / 2 skipped`; integration lane (Docker PG :5433 + Redis) `537 passed / 0 failed` as of 07-08-26 — these are the regression baselines behind AC-9/AC-11. Docker IS available on this machine (CLI off PATH — detect via `lsof` on 5433/6379, never conclude "environment-blocked"). Pixel behavior has a Playwright harness (`apps/pixel/e2e/`, chromium/webkit/firefox) behind AC-10. Dashboard UI e2e is blocked on the known Clerk auth-harness gap (`backlog/privacy-hold-clear-e2e-auth-harness_NOTE_09-08-26.md`) — hence AC-7's Hybrid label.

### Known Unknowns (research gaps — recorded honestly, not papered over)

Three adversarial review lenses never completed (the workflow agents died on environment failures, not on findings):

1. **`harm-still-lands` — outbound sink census incomplete.** CSV export, CRM push, and ad-audience upload internals were NOT traced to confirm every one routes through `is_emailable_identity`. AC-2's test enumeration depends on completing this census; a sink that bypasses the shared helper would silently defeat AC-1/AC-2. Must be closed in the next RESEARCH/PLAN pass.
2. **`implementation-blast-radius` unknown.** Which existing tests assert that a form capture DOES produce an identified visitor or DOES write the graph is unknown (those tests will need deliberate inversion, not deletion). Whether a migration is needed is unknown.
3. **`better-alternative` never evaluated.** No competing design was scored against the chosen candidate-tier approach. The product decision is locked; INNOVATE may still compare mechanisms *within* it.
4. **Unmeasured:** whether `site_id` is enumerable in bulk from any public surface (affects attack scale, not validity — one target's page source suffices); and the real share of `beam_identity_graph` rows currently seeded by `form_capture` (determines the graph-growth cost of this change and whether retroactive cleanup is worth a follow-up task).
