---
name: plan:site-id-lifecycle-spec
description: "SPEC — fix Beam site-identity lifecycle so delete/re-create never silently orphans an installed pixel"
date: 01-08-26
feature: pixel
---

# SPEC — Site Identity Lifecycle (Delete/Re-Create Pixel Orphaning)

## Summary

When a Beam user deletes a site and re-creates it for the same domain, the new site gets a
brand-new random `site_id` while the pixel snippet already installed on the live website still
sends the OLD id. Today that mismatch is invisible and destructive: every visitor hitting the
site gets rejected by the ingest API, and the installed tracker's own "unknown site" handling
wipes that visitor's durable identity (cookies, consent, queued events) — one real person at a
time, with no error surfaced to the site owner and no log line on Beam's side. This happened to
the founder himself on production. This SPEC defines what must change so that deleting and
re-adding a site either keeps the pixel working, or — if that's not possible — makes the breakage
loud, explainable, and fixable instead of silent and irreversible.

## User Stories / Jobs To Be Done

1. **As a Beam site owner who deletes and re-creates a site record**, I want my already-installed
   pixel to keep working (or to be clearly told it needs a specific fix), so that I don't
   silently lose weeks of visitor tracking without knowing why.
2. **As a Beam operator**, I want orphaned-pixel traffic (a site_id that doesn't resolve to any
   live site) to be observable in logs/metrics, so that I can detect this failure mode proactively
   instead of a customer discovering it by accident.
3. **As a Beam site owner running pixel verification** after something breaks, I want the verify
   flow to tell me specifically what's wrong (e.g. "this page has a different site id embedded")
   instead of a generic "reinstall the snippet" message, when Beam's own verification fetch
   already has that information in hand.
4. **As a Beam site owner about to delete a site**, I want to be told, before I confirm, that
   deleting is permanent AND that my live pixel will start failing, so I can make an informed
   choice (e.g. export data first, or not delete at all).
5. **As a Beam site owner whose site was deleted or is temporarily unreachable**, I want my
   installed tracker to behave sensibly (not permanently self-destruct on the very first bad
   response) so that a transient blip doesn't have the same destructive effect as a real deletion.

## What The User Wants (Behavioral Outcomes)

- Deleting a site and re-creating one for the *same domain* should, by default, result in a
  working pixel again without the user needing to manually find, copy, and re-paste a new
  snippet — OR, if immediate reinstall is unavoidable for security reasons, the product must make
  that requirement unmistakable at the moment of deletion and again at the moment of re-creation
  (not discovered days later as silent data loss).
- Every time the ingest endpoint rejects an unrecognized `site_id`, that event is recorded
  somewhere Beam can see in aggregate (count, rate, distinguishing "used to be valid" vs "never
  valid" where feasible) — never a silent 403 with zero trace.
- The dashboard pixel-verification flow, when it detects "this page has a pixel, but it's tagged
  with a different site id than the one I'm checking," tells the user what id it found and offers
  a concrete next step (e.g. "this looks like site X you previously deleted — reconnect it" or
  "copy the currently-installed snippet's id to match"), instead of only saying "verification
  failed, reinstall the snippet."
- Any surfacing of a "found" foreign site_id must not let one tenant discover or attach to another
  tenant's site — the found id can only ever be treated as evidence about the CURRENTLY-FETCHED
  domain (which the requesting user has already proven ownership of by successfully verifying that
  domain), never as a general lookup capability.
- The site deletion confirmation dialog explicitly states, in plain language: this deletes all
  historical data permanently, AND stops the live pixel from working, before the user can confirm.
- An installed tracker, when its site_id stops resolving, does not have to treat every 403 as
  "delete everything forever" — the behavior must distinguish (to the extent the frozen, unchangeable
  format of already-deployed trackers allows) a real permanent condition from something recoverable,
  and any NEW tracker behavior shipped going forward should degrade more gracefully.

## Flow / State Diagram

Current (broken) behavior:

```
[User deletes Site A]
        |
        v
Site A row + all data HARD-DELETED (no soft-delete)
        |
[User re-creates site for same domain]
        |
        v
Site B created — _generate_site_id() -> NEW RANDOM id
        |
        v
Website HTML still has old <script data-site="site_A_id">
        |
        v
Visitor loads page --> tracker.js sends events with site_A_id
        |
        v
POST /ingest --> site_A_id not found in DB --> 403
        |                                         |
        |                                         v
        |                              tracker.js: clear _rta_vid,
        |                              clear consent cookie, drop queue,
        |                              STOP sending forever
        |
        v
[NO LOG LINE, NO METRIC — completely silent]
        |
        v
Dashboard shows Site B "not verified" -> user clicks Verify
        |
        v
pixel_verifier fetches page, sees site_A_id in HTML (foreign to Site B)
        |
        v
Returns "wrong_site" + generic "reinstall snippet" message
(the found id is in scope but never surfaced or acted upon)
```

Target (this SPEC's required) behavior — high level, HOW is left to INNOVATE:

```
[User deletes Site A]
        |
        v
Confirmation dialog explicitly warns:
  "This is permanent. Your live pixel will also stop working." (Req D)
        |
        v
Deletion proceeds (still permanent per current guardrails — no scope
change to historical-data recovery, see Out of Scope)
        |
        v
[User re-creates site for same domain]
        |
   ,----+-------------------------------------------.
   |                                                 |
   v                                                 v
Same-domain re-create is recognized               New site created,
as a lifecycle event for Site A (survivability     no relationship
path) -- exact mechanism decided in INNOVATE        to Site A (explicit
   |                                                 reinstall path)
   v                                                 |
Existing installed pixel resumes working             v
without a new snippet                          Dashboard clearly tells
                                                user: "you must update
                                                your installed snippet"
                                                with the new id shown
                                                prominently
        |
        v
Meanwhile, ANY ingest hit with an unresolvable site_id:
  --> logged/metric-tracked (Req B), never silent
        |
        v
User runs Verify on the new/existing site:
  pixel_verifier finds a DIFFERENT site id embedded in the fetched HTML
        |
        v
Verify response surfaces the found id + an actionable message
(e.g. "this domain currently has site {found_id} installed — reconnect
or update your snippet") -- ownership-safe: only usable in the context
of a domain the requesting user already owns/has just re-verified (Req C)
```

## Acceptance Criteria (Testable Outcomes)

1. **Deleting a site and re-creating a site record for the identical normalized domain results in
   the pixel resuming ingestion without requiring the user to manually edit the live page's
   snippet**, OR the product explicitly and immediately (at delete time and at re-create time)
   tells the user reinstall is required and shows the exact new id to install.
   proven by: new backend integration test — delete-then-recreate-same-domain scenario (extends
   `tests/integration/test_events_ingest.py` unknown-site coverage)
   strategy: Fully-Automated

2. **Every POST /ingest request rejected for an unrecognized `site_id` produces a structured log
   event** (at minimum: site_id value, timestamp, that it was rejected as unknown) — replacing the
   current silent 403 branch in `apps/api/routers/events.py`.
   proven by: unit/integration test asserting a structlog event is emitted on the unknown-site 403
   path (new test alongside `tests/integration/test_events_ingest.py:95-138`)
   strategy: Fully-Automated

3. **Orphaned-ingest volume is queryable/aggregatable by Beam operators** (count of rejected-unknown
   events over a window; distinguishing this from normal traffic).
   proven by: new unit test on the aggregation/metrics surface introduced to satisfy AC2 (exact
   surface — log-based query vs dedicated counter table — decided in INNOVATE/PLAN)
   strategy: Fully-Automated

4. **The pixel-verify `wrong_site` response includes the foreign site_id it found in the fetched
   HTML** when the verifier's fetch (`apps/api/services/pixel_verifier.py` wrong_site branch)
   already captured that HTML, instead of discarding it.
   proven by: extends `tests/unit/test_pixel_verifier.py:89` wrong_site case to assert the found id
   is present in the response payload
   strategy: Fully-Automated

5. **Surfacing a found foreign site_id never allows a user to discover, view, or act on a site they
   do not own.** The found id may only be used in the context of the domain the requesting user's
   own site record points to (the fetch that found it is scoped to that domain, not an arbitrary
   lookup).
   proven by: new unit test asserting the wrong_site response never resolves/exposes info about a
   site owned by a different `user_id` beyond the bare id string already visible in that domain's
   public HTML
   strategy: Fully-Automated

6. **The site deletion confirmation UI states, before the user can confirm, that deletion is
   permanent AND that the live installed pixel will stop working / start rejecting events.**
   proven by: Playwright e2e assertion on the delete-dialog copy (extends dashboard delete-flow
   coverage in `apps/web/e2e/`)
   strategy: Hybrid (component/text assertion automatable; full auth-gated e2e run may be
   Agent-Probe if the existing Playwright auth-harness gap referenced elsewhere in this repo's
   context blocks a live run — see Constraints)

7. **A newly-issued site_id is never guessable or derivable from the site's domain/URL** (this
   constraint must hold for whatever mechanism resolves AC1 — no design may weaken the current
   random 48-bit-class id posture).
   proven by: unit test asserting no deterministic function exists from `Site.url` to any valid
   `site_id` (regression guard on the chosen INNOVATE mechanism)
   strategy: Fully-Automated

8. **Unknown/foreign site_id handling on user-facing endpoints continues to return 404 /
   "not found"-shaped responses** (never 403-leaking-existence patterns) for anything a
   non-owning user could probe, consistent with the repo's existing multi-tenancy guardrail.
   proven by: regression test confirming existing 404-on-foreign-id behavior is unchanged
   (`tests/integration/test_sites.py` or equivalent — exact file confirmed in PLAN)
   strategy: Fully-Automated

9. **Whatever new tracker behavior is introduced for handling an unresolvable site_id must not
   change the wire contract that OLD/already-deployed trackers rely on** — i.e. the backend cannot
   assume any installed tracker will ever be updated.
   proven by: contract test asserting `apps/api/routers/events.py`'s response shape/status code for
   unknown site_id is unchanged for un-updated trackers (backward-compatibility regression test)
   strategy: Fully-Automated

## Out Of Scope

- Restoring historical data (events, visitors, identified_visitors, etc.) from a previously
  hard-deleted site. This SPEC does not introduce soft-delete/undo for already-deleted data — it
  only addresses future delete/re-create cycles going forward from the moment this ships.
- DNS-TXT-record or file-upload domain ownership verification infrastructure. The existing
  "our own fetch of your page" verification mechanism remains the sole ownership proof method;
  any lifecycle/reclaim design must work within that constraint (per repo guardrail: prefer the
  smallest durable mechanism).
- Billing/plan changes (e.g. changing per-plan site limits, credits, or how a
  deleted-then-recreated site counts against a user's site quota).
- Multi-site-per-domain as a general product feature (e.g. letting one user run two independent
  Beam site records against the same domain simultaneously). Only what's needed to resolve the
  delete/re-create case is in scope.
- Retroactively fixing already-deployed trackers currently installed on customer sites that are
  ALREADY in a wiped/self-destructed state from a past occurrence of this bug — this SPEC prevents
  future occurrences and improves observability/UX, it does not include a remediation campaign for
  past damage.
- Changing the underlying hard-cascade-delete transaction mechanics (the 17-table delete list,
  the ordering, or moving off a single-transaction cascade) except to the extent required to add
  the confirmation warning copy (AC6).

## Constraints

- `site_id` is embedded in public page HTML and is the sole unauthenticated write credential for
  `POST /ingest`. No solution may make ids guessable or derivable from the domain/URL (AC7) — this
  would turn ingest into a forgeable-key surface.
- `sites.site_id` has a DB-level `unique=True` constraint (`apps/api/models/site.py:15`). Any
  design that reuses, tombstones, or reclaims an id must respect this constraint or explicitly plan
  a migration that changes it.
- Trackers already deployed on live customer pages cannot be updated by Beam — they are frozen at
  whatever version was installed. The current 403-triggers-self-destruct contract in `tracker.js`
  is effectively permanent for those installs (AC9). Any backend behavior change must reason
  explicitly about what an un-updatable old tracker will do in response.
- Multi-tenancy posture must hold: unknown/foreign ids stay 404/"not found" on user-facing
  endpoints — never a response shape that lets one user learn whether a given id/site exists for
  another tenant (AC8), except the single existing deliberate exception (409 domain-already-taken
  on create).
- Schema changes deploy as live prod DDL on push (Railway auto-applies Alembic migrations on
  boot). Current alembic head must be re-confirmed live (`alembic heads`) immediately before any
  migration authored for this fix is applied — do not assume the head recorded in
  `process/context/all-context.md` is still current at execute time.
- This is a solo-founder repo — prefer the smallest durable mechanism (e.g. a lookup/claim field,
  a grace-period soft-delete window) over building general-purpose domain-verification
  infrastructure.
- The pixel-verifier's "found a foreign id" capability must not become a way to enumerate other
  tenants' site ids — it can only report on the id embedded in the HTML of the domain the
  requesting user's own site record already points to.

## Open Questions

None — all clarifying questions were resolvable from the RESEARCH findings and repo constraints
provided; the "survive vs explicit reinstall" mechanism choice is intentionally left to INNOVATE
per SPEC's phase-lock (approach selection is not a SPEC decision).

## Background / Research Findings

- Root cause: `_generate_site_id()` (`apps/api/routers/sites.py:35-36`) issues a fresh random id on
  every `create_site` call with no relationship to a prior site for the same domain. `Site.url`
  normalization (`_normalize_url`, `apps/api/routers/sites.py:42-48`) strips `www.` and trailing
  slash but treats `http://` vs `https://` as different — meaning "same domain" detection is
  already inconsistent even for dedup purposes today.
- `apps/api/routers/events.py:163-195`: unknown site_id -> 403 with the tracker's `_rta_vid`/consent
  cookies expired client-side, and NO log line at all. A paused (but still-known) site returns a
  silent 204 instead — non-destructive, structurally different code path from unknown-site.
- `apps/pixel/src/tracker.js`: on receiving that 403, the deployed tracker treats it as terminal —
  clears cookies, drops the queue, and stops flushing permanently, for every visitor who happens to
  hit the page after the mismatch begins.
- `apps/api/services/pixel_verifier.py:180-187`: the `wrong_site` branch already has the fetched
  `html` variable in scope when it determines the page carries a different site id, but the code
  today does not extract or return that id — it just returns a generic status.
- `apps/api/models/site.py:15`: `site_id` is the only column with `unique=True` in the whole table;
  there is no `deleted_at` anywhere in any model in this codebase — no soft-delete precedent to
  build on.
- Delete endpoint (`apps/api/routers/sites.py:153-239`) is a genuinely permanent, 17-table,
  single-transaction hard cascade (including cross-tenant `beam_identity_graph` rows keyed by
  `source_site_id`) with no undo — confirmed via direct code read, not assumption.
  Confirmation-dialog code (`apps/web/src/app/dashboard/page.tsx:240-267`) does not currently warn
  about pixel-orphaning.
- Existing tests pin today's (buggy) contract: unknown-site 403 + cookie-expiry
  (`tests/integration/test_events_ingest.py:95-138`) and the generic `wrong_site` status
  (`tests/unit/test_pixel_verifier.py:89`). There are zero tests today for the delete→recreate
  sequence itself — this is a genuine coverage gap this SPEC's acceptance criteria are meant to
  close.
- This bug was confirmed live in production, hit by the founder's own account, not a hypothetical.
  Any prod customer who deletes and re-adds a site for the same domain hits the identical trap.
  Snippet install surfaces that could carry a stale id include: raw HTML the customer pasted, the
  generated WordPress plugin zip, a Shopify ScriptTag, click-URLs already sent in past onboarding
  emails, and the onboarding LLM-prompt flow — none of these are Beam-controlled once installed.
