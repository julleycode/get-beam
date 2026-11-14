---
name: plan:graph-erasure-compliance-spec
description: "SPEC — close the cross-tenant beam_identity_graph erasure + disclosure compliance gap"
date: 07-08-26
feature: visitors-identity
---

# SPEC — Cross-Tenant Identity Graph: Erasure & Disclosure Compliance

## Summary

Beam pools identity data (email, name, city/region/country) across every customer site into one
shared table, `beam_identity_graph` — an identification made on Site A is immediately reused on
Site B for free. Today, when a customer honors one of their visitor's deletion requests, that
visitor's row in the shared graph is **never removed**. The person is still being served to every
other Beam customer as if nothing happened. Separately, Beam's public Privacy Policy and Terms say
"you own your data" and "we do not share visitor data with third parties" — both statements are
false with respect to this shared graph, and no page anywhere discloses that pooling exists. This
SPEC defines what must be true for erasure requests to actually reach the shared graph, for the
opt-out guard that keeps people out of the graph in the first place to be resistant to future
coding mistakes, and for what the public-facing legal copy needs to say instead. It does not decide
whether cross-tenant pooling should continue, expand, or become an opt-in "co-op" (that's a
separate SPEC) — it decides what "erasure" and "we don't share your data" must mean for this
already-existing table.

## User Stories / Jobs To Be Done

**US-1 — End visitor exercising their erasure right**
As a visitor who asked a Beam customer's site to delete my data (or who is protected by GPC/DNT),
I want my identity to be actually gone from every place Beam stores it — not just the one site I
interacted with — so that I am not silently re-identified for a different company the next time I
visit any other Beam customer's site.

**US-2 — Beam customer (site owner) answering their own visitor's request**
As a site owner who received a deletion request from my own visitor, I want clicking "delete this
visitor's data" to be a complete, truthful answer — including removing them from any shared
identity store — so that I am not unknowingly making a false compliance claim to my own visitor or
regulator on Beam's behalf.

**US-3 — Beam operator/founder handling a regulator or customer inquiry**
As the person who has to answer "does Beam ever share visitor data with other companies," I want
the platform's actual behavior, the deletion endpoints' actual behavior, and the words on
privacy.html/terms.html to all say the same true thing, and I want to be able to look up, for any
given deleted visitor, whether their data is still resolvable through the shared graph — so that I
can answer honestly and quickly under time pressure (e.g. a CPPA/AG inquiry, a DPA request, a
customer's own legal team asking).

## What The User Wants (Behavioral Outcomes)

- When a per-visitor deletion request is honored (`DELETE /{site_id}/{visitor_id}/data`), the
  visitor's corresponding row(s) in the cross-tenant graph are also removed or rendered
  permanently unresolvable — not just left in place.
- This holds true even in the hard case: the graph row for this visitor may have been **written by
  a different site** than the one now requesting deletion (the row's `source_site_id` points to
  another tenant). The visitor doesn't know or care which site "owns" the row in Beam's schema —
  they asked one site to forget them, and expect that to mean something everywhere.
- A visitor who is opted out (GPC/DNT/suppression list) never reaches the graph in the first place,
  and this protection does not depend on every future call site remembering to check a flag before
  writing — it holds even if a new code path is added later that calls the write function
  carelessly.
- After erasure, revisiting any Beam customer's site does not silently re-populate the same
  identity into the graph from a stale cache or an in-flight resolution that started before the
  deletion.
- The public Privacy Policy and Terms of Service no longer contain a sentence that is directly
  contradicted by what the code does. Wherever cross-tenant pooling happens, it is disclosed in
  plain language, in a place a visitor or customer would actually find it (not just implied).
  Customers are told about it in a place they'd see before or during pixel install, not buried.
- An operator, given a visitor's email or fingerprint, can determine whether that person still has
  a live row in the shared graph and, if so, which site(s) contributed it — without writing ad-hoc
  SQL under time pressure during a live inquiry.

## Flow / State Diagram

```
CURRENT (broken) STATE
=======================
 Visitor -- "delete me" --> Site A dashboard
                                 |
                                 v
                  DELETE /{site_id}/{visitor_id}/data
                                 |
              +------------------+------------------+
              |         |          |        |        |
              v         v          v        v        v
        resolution_ identified_ enrichment_ events  visitors
        logs        visitors    profiles
              |
              X   <-- beam_identity_graph row: NEVER TOUCHED
                       (still readable by every other site)

DESIRED STATE
=======================
 Visitor -- "delete me" --> Site A dashboard
                                 |
                                 v
                  DELETE /{site_id}/{visitor_id}/data
                                 |
    +---------+---------+---------+---------+------------------+
    |         |         |         |         |                  |
    v         v         v         v         v                  v
 resolution_ identified_ enrichment_ events visitors   beam_identity_graph
 logs       visitors    profiles                        row(s) for this
                                                          visitor's identity
                                                          -> erased/tombstoned
                                                          REGARDLESS of which
                                                          source_site_id wrote it
                                                                |
                                                                v
                                                    future resolve() calls for
                                                    this identity get NO hit
                                                    (any site, any fingerprint
                                                    alias, any re-write attempt)

GUARD HARDENING (structural, not incidental)
=======================
 resolve()                         _upsert_beam_identity()  (any future caller)
    |                                        |
    | do_not_resolve? ---X (blocks today)    | <-- TODAY: no guard here.
    | suppressed?     ---X (blocks today)    |     A new/refactored call site
    |                                        |     that skips resolve() writes
    v                                        |     to the graph unguarded.
 _upsert_beam_identity()  -------------------+
    |
    v
 DESIRED: guard re-checked AT the write boundary itself, not only upstream.

DISCLOSURE
=======================
 privacy.html / terms.html   -->  TODAY: "we don't share your data" (false)
                              -->  DESIRED: plain-language disclosure of
                                   cross-tenant pooling + link to
                                   subprocessor/DPA surface (requirement,
                                   not drafted text — counsel review)
 onboarding / pixel install  -->  DESIRED: customer sees the disclosure
                                   before/during pixel install, not after
```

## Acceptance Criteria (Testable Outcomes)

**AC-1 — Per-visitor erasure reaches the shared graph**
When a site owner calls `DELETE /{site_id}/{visitor_id}/data` for a visitor who has a
`beam_identity_graph` row keyed to that visitor's fingerprint/email, the row is removed or
tombstoned as part of the same request, not left behind.
- proven by: integration test — seed a `BeamIdentityNode` row for a visitor's fingerprint, call
  the delete endpoint, assert the row is gone (or tombstoned per AC-3/Open Questions) after commit.
- strategy: Fully-Automated

**AC-2 — Erasure works when the graph row belongs to a different tenant**
When Site A's visitor requests erasure, and the matching `beam_identity_graph` row has
`source_site_id` pointing to Site B (i.e. Site B, not Site A, originally wrote that identity), the
erasure still succeeds in making the person's identity unresolvable — Site A is not blocked from
protecting its own visitor just because Beam's internal bookkeeping attributes the row to another
tenant.
- proven by: integration test — seed a graph row with `source_site_id = site_B`, request deletion
  from `site_A`'s visitor endpoint for a visitor whose fingerprint matches that row, assert the
  identity is no longer resolvable.
- strategy: Fully-Automated
- Note: the *authorization model* for this case (should Site A be able to trigger removal of a row
  it doesn't "own"?) is a deliberate open question — see Open Questions. This AC specifies the
  observable outcome required (person becomes unresolvable), not the mechanism.

**AC-3 — Erasure is idempotent**
Calling the deletion endpoint twice for the same visitor (or once after the graph row is already
gone) does not error and produces the same end state: no live, resolvable graph entry for that
identity.
- proven by: integration test — call delete endpoint twice in sequence, assert second call
  succeeds (200) with no exception and the graph state is unchanged from after the first call.
- strategy: Fully-Automated

**AC-4 — Deletion does not silently re-create the identity**
A resolution attempt that was already in flight when the deletion request was made (or a resolve()
call that runs immediately after) does not re-write the just-deleted identity back into the graph.
- proven by: integration test — trigger delete, then immediately call `resolve()` for the same
  visitor/fingerprint under conditions that would normally produce a graph write, assert no graph
  row reappears for that identity within the test's scope.
- strategy: Fully-Automated
- Note: full protection against a resolution that started microseconds before the delete
  transaction committed is a known-gap for true race conditions — see Risk/Known-Gap section. This
  AC covers the sequential (non-racing) case, which is the actual observed risk (re-visit after
  deletion, not concurrent in-flight collision).

**AC-5 — GPC/DNT/suppression guard is structurally enforced at the write boundary**
`_upsert_beam_identity` (or its replacement) refuses to write a row for a visitor whose
`do_not_resolve` flag is set or whose email is on the suppression list, even if called directly
without going through `resolve()`'s upstream checks.
- proven by: unit test — construct a `Visitor` with `do_not_resolve=True`, call the graph-write
  function directly (bypassing `resolve()`), assert no row is written and no exception leaks PII.
- strategy: Fully-Automated

**AC-6 — Existing GPC/DNT/suppression behavior is not regressed**
The current guard behavior (opted-out visitors never reach the graph via the normal `resolve()`
path) continues to work exactly as it does today after the structural hardening in AC-5.
- proven by: existing regression suite (`test_agent_origin_exclusion.py`-style pattern) plus a new
  assertion that `resolve()` still short-circuits before any graph write for `do_not_resolve=True`
  and suppressed-email visitors.
- strategy: Fully-Automated

**AC-7 — Privacy Policy no longer contradicts code**
`apps/web/public/beam/privacy.html` no longer contains the unqualified claim "we do not share
visitor data with third parties except the enrichment providers..." without also disclosing
cross-tenant identity pooling with other Beam customers, in plain language a visitor can
understand.
- proven by: manual content review against a written requirements checklist (this SPEC's
  disclosure requirements) by a human reviewer; automatable only as a "keyword must appear" smoke
  check, not as a substitute for legal review.
- strategy: Agent-Probe (content correctness is a legal/product judgment call, not a mechanically
  verifiable property — see note below on legal review)

**AC-8 — Terms of Service no longer contradicts code**
`apps/web/public/beam/terms.html`'s "you own the data you bring to Beam" claim is qualified or
clarified so it does not contradict the existence of a cross-tenant shared identity store that
other customers benefit from.
- proven by: manual content review against the same requirements checklist as AC-7.
- strategy: Agent-Probe

**AC-9 — Customer-facing disclosure exists before/during pixel install**
A Beam customer setting up a new site sees a plain-language notice that identifications made on
their site may be reused by (and reuse identifications from) other Beam customers, before or during
the pixel install / onboarding step — not only buried in a policy page they may never open.
- proven by: manual UX review of onboarding flow content against the requirement; a Playwright
  smoke check that the disclosure element is present and visible on the onboarding page is a
  Fully-Automated supplement, not a substitute for the content judgment call.
- strategy: Hybrid (Fully-Automated presence check + Agent-Probe content review)

**AC-10 — Operator lookup: "is this person still in the graph"**
Given a visitor's email or fingerprint, an operator (not necessarily an engineer with SQL access)
can determine (a) whether a live `beam_identity_graph` row exists for that identity, and (b) which
site(s) contributed to it, without writing ad-hoc SQL during a live inquiry.
- proven by: integration test exercising the lookup surface end-to-end (exact surface —
  admin endpoint, CLI script, or dashboard panel — is an INNOVATE/PLAN decision, not specified
  here) against a seeded graph row, asserting correct existence + attribution is returned.
- strategy: Fully-Automated

## Out Of Scope

- The co-op opt-in flag, contribution/consumption measurement, credit ledger, and reciprocity
  mechanics (SPEC B, being written in parallel). This SPEC does not decide whether pooling
  continues, expands, or becomes opt-in — only what erasure and disclosure must mean for the
  pooling that already exists today.
- Deciding whether `CompanyGraphNode` (company-level, no person PII) needs its own erasure path —
  flagged as an open question, not resolved here (see Open Questions).
- Drafting final legal copy for `privacy.html`/`terms.html`/any new DPA or subprocessor page.
  This SPEC states requirements for what must be true; the actual sentences require qualified
  privacy counsel review before publishing (see note at the end of this document).
- Building a self-serve visitor-facing erasure request form (the erasure trigger today is a site
  owner using the existing dashboard/API; a public-facing "forget me" form for end visitors is a
  separate, larger product decision).
- Retroactive one-time audit/cleanup of every existing row already in `beam_identity_graph` today —
  flagged as an open question (see below), not committed to as a requirement of this SPEC.
- Changing `retention.py`'s 90-day raw-event purge scope, or any table other than the
  cross-tenant graph(s) and the legal/disclosure surfaces named above.
- Resolving the CPRA "sale"/"share" legal classification question definitively — that determination
  belongs to counsel, not to this engineering SPEC. This SPEC treats the regulatory context as
  motivation for urgency, not as a legal conclusion to implement against.

## Constraints

- **Plan collision (must be sequenced, not ignored):** two active plans touch
  `apps/api/services/identity_resolver.py`:
  - `process/features/visitors-identity/active/identity-program_03-08-26/` Phase 1 explicitly
    claims `_save_identified` in this file (status: PLANNED, not yet executed).
  - `process/features/visitors-identity/active/identity-vocab-reconcile_07-08-26/` is rewriting
    `identity_resolver.py` §3.2 and is currently at PVL cycle 2 with `Gate: BLOCKED`.
  Any implementation plan produced from this SPEC must be sequenced against both — either wait for
  them to land, coordinate a shared blast-radius claim, or scope the erasure/guard-hardening work
  to touch `_upsert_beam_identity` narrowly enough to avoid conflict. This is a PLAN-phase decision,
  noted here so it isn't discovered late.
- Multi-tenancy must be preserved: erasure of a cross-tenant row triggered by Site A must never
  leak Site B's other, unrelated data to Site A, and must never give Site A visibility into Site
  B's identity beyond "this graph row is now gone."
- Must not break the existing free-identity-reuse mechanism for every visitor who has NOT
  requested erasure and is NOT opted out — the graph continues to function normally otherwise.
- Must not weaken or bypass the existing `do_not_resolve` / suppression-list guard behavior
  (AC-6) — hardening it must be additive/structural, not a rewrite that risks regression.
- PII handling constraints from `all-context.md` Business Guardrail #3 apply: no plaintext PII in
  logs, ciphertext/blind-index pattern (`email_ciphertext`/`email_bidx`) must be respected by any
  new erasure or lookup code path.
- Legal copy changes must not be published without qualified privacy counsel review — this is a
  hard constraint stated explicitly at the end of this document.

## Open Questions

1. **Cross-tenant erasure authorization model.** When Site A's visitor triggers erasure and the
   matching graph row's `source_site_id` is Site B, what is the authorization boundary? Does Site
   A's request alone suffice to erase a row Site B contributed (current proposal in AC-2 says yes,
   because the row represents the SAME visitor regardless of who wrote it) — or does this need a
   different mechanism (e.g. a platform-level erasure queue, independent of any single tenant's
   delete button)? Owner: product/legal decision, needed before PLAN. This is the single most
   important unresolved design question in this SPEC.
2. **`CompanyGraphNode` deletion path.** No deletion or tombstone mechanism was found for
   `company_graph` anywhere in the codebase. Company-graph rows hold no person-level PII (ip →
   company only), which may mean no per-visitor erasure obligation applies — but this has not been
   confirmed with counsel. Owner: needs a legal read on whether IP→company mappings carry any
   erasure obligation, then an engineering decision on whether to add a matching deletion path.
3. **Tombstone vs. hard-delete.** Should an erased graph row be hard-deleted (row disappears
   entirely, and a future re-identification of the same real person at the same site would create
   a brand-new row from scratch) or tombstoned (a marker row prevents any future write for that
   identity, similar to the existing `SiteTombstone` pattern for site_id reuse)? Hard-delete risks
   the person being silently re-added to the graph on their next visit if they're re-identified
   normally; tombstoning prevents that but adds a new marker table/column and its own retention
   question ("how long does a tombstone live"). Owner: PLAN/INNOVATE decision — this SPEC requires
   only that AC-4's outcome (no silent re-creation) holds; it does not mandate the mechanism.
4. **One-time audit of existing graph rows.** Rows already in `beam_identity_graph` today were
   written before this compliance gap was identified — some may correspond to people who already
   filed a deletion request under the old (broken) endpoint behavior, meaning they should already
   be gone but aren't. Should there be a one-time backfill job to reconcile existing graph rows
   against historical deletion requests? Owner: needs a decision on whether historical deletion
   requests are even auditable (are they logged anywhere with enough detail to cross-reference?) —
   flagged as unresolved, not committed to as an AC.
5. **Disclosure surface scope.** Beyond editing `privacy.html`/`terms.html`, does Beam need a
   dedicated subprocessor list or DPA page, or is inline disclosure in the existing policy pages
   sufficient? Owner: product/legal — AC-9 requires SOME onboarding-time disclosure exists but
   does not mandate a new page.
6. **CompanyGraphNode disclosure.** Does the "we don't share visitor data" claim also need to
   cover the company-level IP→company graph, or only the person-level identity graph? Owner:
   legal, feeds into AC-7/AC-8 content.

## Risk / Known-Gap Section

- **Race condition on in-flight resolution.** AC-4 covers the sequential case (delete, then a
  later resolve() call). A resolution that is mid-flight in another request at the exact moment a
  delete transaction commits is a true race condition; closing it completely likely requires a
  distributed lock or a re-check-after-write pattern that adds real complexity. Flagged as a
  known-gap for PLAN to size, not assumed solved by this SPEC.
- **Authorization model risk (see Open Question 1).** If cross-tenant erasure is implemented
  naively (any site can erase any row matching a fingerprint it sees), there is a theoretical abuse
  vector: a malicious or careless site owner could trigger erasure of another tenant's
  contributed identity data via a fingerprint collision or a crafted request, degrading Site B's
  free-reuse benefit without Site B's knowledge. This must be explicitly designed against in PLAN,
  not left implicit.
- **Legal classification risk.** Whether reciprocal cross-tenant graph access constitutes a "sale"
  or "share" under CPRA is unresolved and outside this SPEC's authority to decide. The regulatory
  survey in Background is informational context for urgency, not a compliance conclusion.
- **Blast-radius collision risk.** As stated in Constraints, two other active plans touch
  `identity_resolver.py`. Implementing this SPEC without explicit sequencing against
  `identity-program_03-08-26` Phase 1 and `identity-vocab-reconcile_07-08-26` risks merge
  conflicts or one plan silently undoing another's guard hardening.
- **Retroactive data risk (see Open Question 4).** Rows written before this SPEC may already
  represent people who believe they were erased. This is a real, if unquantified, current-state
  liability that pre-dates this SPEC and is not created by it — but it is not resolved by
  implementing only the ACs above (which are forward-looking).

## Background / Research Findings

Research (code-verified, all citations opened and confirmed against source during this SPEC
session):

- `apps/api/models/beam_identity.py` — `BeamIdentityNode` / table `beam_identity_graph`: every
  successful identification on any customer's site writes a
  `(fingerprint, email, full_name, city, region, country, confidence_score, source_site_id,
  source_provider)` row, unique on `(fingerprint, email)`, readable by every other tenant. Docstring
  confirms intent: "if the same fingerprint was identified on ANY Beam customer's site, we reuse
  that identity instantly." Sibling `apps/api/models/company_graph.py` (`CompanyGraphNode`) is the
  same pattern at the IP→company level, no person PII.
- `apps/api/routers/visitors.py:403-439` — `DELETE /{site_id}/{visitor_id}/data` deletes
  `resolution_logs`, `identified_visitors`, `enrichment_profiles`, `events`, `segment_members`,
  `visitors` (all scoped `WHERE site_id = :sid AND visitor_id = :vid`). Confirmed: no
  `beam_identity_graph` statement anywhere in this function.
- `apps/api/routers/sites.py:281-286` — `DELETE /sites/{site_id}` (whole-site deletion) DOES
  include `DELETE FROM beam_identity_graph WHERE source_site_id = :sid`, immediately followed by
  writing a `SiteTombstone` marker in the same transaction. Confirms the team has already built and
  used a graph-deletion pattern — it just isn't wired to the per-visitor endpoint.
- `apps/api/services/retention.py` — confirmed scope is raw-event/log purging only
  (`events`, `agent_fetch_events`, `request_logs`), explicitly documented in its module docstring
  as NOT touching aggregated visitor/profile data ("Aggregated `visitors` and enriched profiles are
  kept... this enforces the policy's 90-day event-retention promise"). Confirmed no
  `beam_identity_graph` reference anywhere in this file.
- `apps/api/services/identity_resolver.py:497` (`do_not_resolve` check) and `:506`
  (`_is_email_opted_out`) — confirmed both checks run and `return None` before
  `_upsert_beam_identity` is reachable, inside `resolve()`. `_upsert_beam_identity` itself
  (`:968-1030` region, method starting "Write (fingerprint, email) to cross-customer identity
  graph") has no guard of its own — it trusts every caller to have already checked. Confirmed the
  production code has exactly one call site for this method (inside `resolve()`), so today there is
  no live bypass — but the guard's placement is structurally fragile for future changes.
- `apps/web/public/beam/terms.html:130-131` and `apps/web/public/beam/privacy.html:128` — both
  files exist and were located; exact claimed text matches what was provided in the task brief.
  Confirmed no DPA, subprocessor list, or GDPR-specific page exists in `apps/web/public/beam/`,
  `apps/web/src/app/`, or `marketing/` (directory scan, not exhaustive line-by-line read of every
  file, but no such page name or route was found).
- Regulatory survey (external, factual only, not legal advice, not re-verified in this session
  beyond what was supplied): CPRA §1798.140 broad "sell"/"share" definitions including non-monetary
  "valuable consideration"; GDPR Art. 26 (joint controllers) and Art. 14 (notice for data not
  collected directly from the subject) as the operative articles for a case where Site B never met
  the visitor; CA AG v. Sephora ($1.2M, 2022, GPC non-compliance); CPPA + CA/CO/CT AG multi-state
  GPC enforcement sweep opened 2025-09-09; Belgian DPA v. IAB Europe (TCF), €250k penalty upheld by
  the Belgian Market Court 2025-05-15, establishing that shared consent/identity infrastructure
  operators can be held directly liable, not just the sites using them.
- Feature-scope context: `process/features/visitors-identity/_GUIDE.md` confirms
  `beam_identity_graph` and `company_graph` are both documented "owned identity data layer" assets,
  and confirms Business Guardrail #3 (PII) and the GPC/DNT/`do_not_resolve` pattern are the
  established privacy posture this SPEC must extend, not replace.
- Plan-discovery scan (`process/features/visitors-identity/active/`) surfaced the two colliding
  active plans cited in Constraints — both confirmed present and touching
  `identity_resolver.py` at the time of this SPEC.

**Note — not legal advice.** Every AC in this document that touches `privacy.html`, `terms.html`,
onboarding disclosure copy, or the classification of Beam's data practices under CPRA/GDPR is a
REQUIREMENT for what must be reviewed and approved by qualified privacy counsel before publishing —
it is not itself legal advice, and no acceptance criterion here should be read as a legal
conclusion. The regulatory survey in Background is included only to establish why this work is
time-sensitive, not as a substitute for counsel's judgment on Beam's actual exposure.
