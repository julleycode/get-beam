---
name: plan:cross-tenant-erasure-phase2-spec
description: "SPEC — cross-tenant erasure of pre-existing per-tenant IdentifiedVisitor/VisitorEmail rows (KG-6 follow-up)"
date: 07-08-26
feature: visitors-identity
---

# SPEC — Cross-Tenant Erasure Phase 2: Other Tenants' Pre-Existing Identity Rows

## Summary

Phase 1 (`graph-erasure-compliance_07-08-26`) makes a per-visitor deletion request reach the
shared `beam_identity_graph` and permanently block all *future* writes for that person on every
site. It does not, and by design cannot, reach a row that another tenant **already holds** in
their own `IdentifiedVisitor`/`VisitorEmail` tables from an earlier, independent identification —
that gap is recorded as Phase 1's KG-6 and is the entire reason this Phase 2 SPEC exists.

**The scenario, verbatim from Phase 1 KG-6:** Person P is identified on Site A. Independently,
Site B already holds an `IdentifiedVisitor` row for P from Site B's own paid-provider lookup
weeks earlier, currently in Site B's active outreach segment. P requests erasure at Site A.
Phase 1's sweep hard-deletes the `beam_identity_graph` rows and writes both tombstones — but
nothing sets `do_not_email`/`do_not_resolve` on Site B's existing row. **Site B keeps sending
campaign email to P and keeps resolving P on return visits, after P's erasure was accepted and
reported complete.**

This SPEC defines what must be true to close that gap — what "erasure reaches every tenant" means
as an observable outcome, for whom, proven how — without choosing a mechanism, without designing
schema, and without deciding whether the answer is suppression or deletion (see Open Questions).

**A load-bearing fact that changes the shape of this problem (verified this session, not assumed):**
Phase 1's Tension #1 (plaintext-vs-blind-index) framed this as an either/or. It is not, fully.
`IdentifiedVisitor.email_bidx` and `VisitorEmail.email_bidx` — the same HMAC blind index used by
`beam_identity_graph.email_bidx` (`apps/api/services/pii_crypto.py:email_hash()`) — already exist
as live, populated columns on **both** tables. `apps/api/services/pii_encryption_hooks.py`
registers a SQLAlchemy `before_insert`/`before_update` listener on `IdentifiedVisitor` that sets
`email_bidx = email_hash(email)` on every write; `VisitorEmail` gets the same treatment via its own
listener, plus explicit sets at `apps/api/routers/click.py:125` and `apps/api/routers/events.py:813`
(a core-table bulk-insert path that bypasses ORM events). **A blind-index-only match against other
tenants' existing rows is therefore structurally possible** — INNOVATE does not have to choose
between "keep the queue plaintext-free" and "reach existing rows"; it has to choose between two
plaintext-free candidate designs (or reject both and pick something else). This does not resolve
Tension #1 (see Open Questions) — it changes what INNOVATE is choosing between.

## Dependencies (read before anything else)

- **`graph-erasure-compliance_07-08-26` (Phase 1) must land first.** This SPEC assumes Phase 1's
  producer (enqueue-before-delete), sweep, `SuppressionEntry(scope="erased")` tombstone, and
  write-boundary guard exist and work. Phase 2 extends the sweep's reach; it does not replace or
  re-specify Phase 1's mechanism. Do not restate Phase 1's content here — read the SPEC and PLAN
  directly. Phase 1 status as of this SPEC: PVL supplement cycle 1 applied, `Gate: CONDITIONAL`,
  blocked on the user's KG-6 scoping decision before re-validate. This Phase 2 SPEC IS that
  scoping decision moving forward as a separate, deliberately out-of-band unit of work — the user
  asked for it to be scoped as its own SPEC rather than folded back into Phase 1's checklist.
- **Three other workstreams are in flight in this feature folder** and may touch files this Phase 2
  work will eventually touch (noted for PLAN/INNOVATE sequencing, not resolved here):
  - `identity-coop_07-08-26` — PLAN'd, not validated. Consumes the `SuppressionEntry(scope="erased")`
    tombstone Phase 1 publishes (see Phase 1 PLAN §7) for co-op ledger exclusion.
  - `identity-vocab-reconcile_07-08-26` — EXECUTED, user-accepted (`Gate: CONDITIONAL, accepted`),
    unpushed. Rewrote `identity_resolver.py` §3.2 and `routers/visitors.py`; both files Phase 1 and
    plausibly Phase 2 will touch.
  - `graph-erasure-compliance_07-08-26` itself, per above.
  Any implementation plan built from this SPEC must re-check the live state of all three before
  claiming blast radius — do not trust this snapshot by the time PLAN runs.

## User Stories / Jobs To Be Done

**US-1 — The erased person (P in the scenario above)**
As a visitor who asked one company to forget me, I want that request to actually mean I stop being
emailed and stop being silently re-identified by *every* Beam customer who happens to already have
me on file — not just the one company I contacted — so that "I asked to be forgotten" is true in
fact, not just true for the one relationship I remembered to manage.

**US-2 — The Site A owner who accepted the request**
As the site owner who told my visitor "done, you're erased," I want that promise to be
substantially true across the platform I'm using, not just true for my own tables — so that I'm not
unknowingly making a false compliance claim to my own visitor or regulator because of a gap in a
platform feature I didn't build and can't see into.

**US-3 — The Site B owner whose data gets mutated by someone else's request (the novel one)**
As a site owner who independently identified and is legitimately using a contact — paid for the
lookup, put them in an active outreach segment, never received any request from that person myself —
I want to understand: will another company's customer's erasure request silently flip a flag on
*my* data, or delete *my* record, without my knowledge or action? I want to know what happens to my
segment, my campaign send list, and my own reporting when this fires — and I want to know whether I
get any notice, either in advance or after the fact, that this has happened to a contact I'm actively
using. If my legitimate business use of a lead I paid to acquire can be unilaterally overridden by a
request I never saw, I need to understand the rules of that before I trust the platform with more of
my outreach.

**US-4 — The operator answering a regulator or customer inquiry**
As the person who has to answer "when someone asks any Beam customer to erase them, does that
actually reach everyone who has them on file," I want to be able to answer that question honestly
and specifically — which tenants were reached, when, and how — for any given erasure request, so
that I can respond under time pressure without reconstructing the answer from raw tables.

## What The User Wants (Behavioral Outcomes)

- When a visitor's erasure request is accepted anywhere on the platform, every tenant who
  independently holds an `IdentifiedVisitor`/`VisitorEmail` row matching that same person is
  reached by the erasure's effect — not only the requesting tenant's own rows and not only the
  shared graph.
- "Reached by the erasure's effect" means at minimum: that tenant stops emailing the person and
  stops resolving the person on return visits. Whether it additionally means the row is deleted
  outright is an open question this SPEC does not resolve (see Open Questions #3).
- The mechanism works without depending on the requesting site knowing anything about the other
  tenant, without exposing the other tenant's identity or existence to the requesting site, and
  without exposing the requesting site's identity or existence to the other tenant beyond whatever
  the resolved notification model decides (Open Questions #4).
- The mechanism is idempotent: firing it twice, or firing it after some tenants have already been
  reached, produces the same end state with no error and no double-processing artifact.
- The mechanism is auditable after the fact: given an erasure request, an operator can determine
  which tenants were reached, when, and what action was taken on their data — without ad-hoc SQL.
- A tenant who creates a matching row **after** the erasure request already ran is still blocked —
  this is not "sweep once and forget," it is a standing guarantee for the erased identity, matching
  Phase 1's write-boundary guard pattern for the shared graph.
- The mechanism inherits Phase 1's abuse posture: rate-limited per requesting site, and does not
  become a new way for one tenant to probe or mutate another tenant's data at will.

## Flow / State Diagram

```
PHASE 1 (existing — do not re-spec here)
==========================================
 Visitor -- "erase me" --> Site A --> enqueue --> sweep --> beam_identity_graph
                                                              row gone + tombstone
                                                              (blocks FUTURE graph
                                                               writes, every site)
                                                                     |
                                                                     X  <-- STOPS HERE.
                                                                          Other tenants'
                                                                          EXISTING rows
                                                                          never touched.
                                                                          (Phase 1 KG-6)

PHASE 2 (this SPEC — the gap being closed)
==========================================
 Visitor -- "erase me" --> Site A --> [Phase 1 producer, unchanged]
                                            |
                                            v
                              +-------------+-------------+
                              |                           |
                              v                           v
                    beam_identity_graph          [NEW] cross-tenant reach
                    (Phase 1, unchanged)         mechanism — unspecified here
                                                            |
                              +-----------------------------+-----------------------------+
                              |                              |                             |
                              v                              v                             v
                    Site B's IdentifiedVisitor      Site C's IdentifiedVisitor      Site N's VisitorEmail
                    row for the SAME person          row for the SAME person         row for the SAME person
                    (independently acquired,          (independently acquired)        (independently acquired)
                     weeks/months earlier)
                              |
                              v
                    do_not_email / do_not_resolve
                    set (suppression outcome) --- OR ---
                    row deleted (deletion outcome)
                    <-- MECHANISM CHOICE: Open Question #3, not decided here

 NEW-ROW-AFTER-SWEEP CASE
==========================================
 Erasure request accepted, sweep/reach already ran
                              |
                              v
 Site Z independently identifies the SAME person for the first time, days later
                              |
                              v
 DESIRED: Site Z's write is blocked/suppressed at write time (standing guard,
          same shape as Phase 1's write-boundary guard) -- NOT a silent
          re-creation of a "forgotten" identity somewhere new.

 AUDIT LOOKUP (operator-facing)
==========================================
 Operator: "for erasure request #X, which tenants were reached, and how?"
                              |
                              v
 DESIRED: answerable without ad-hoc SQL (extends Phase 1 AC-10's lookup
          surface or adds a sibling one -- mechanism is PLAN's decision).
```

## Acceptance Criteria (Testable Outcomes)

**AC-1 — Every tenant holding the erased person is reached**
For a person who has matching identity rows at 2+ independent tenants (not just the requesting
tenant and not just the shared graph), an accepted erasure request results in every one of those
tenants' rows being reached by the erasure's effect (suppressed and/or deleted, per Open Question
#3's eventual resolution).
- proven by: integration test — seed `IdentifiedVisitor`/`VisitorEmail` rows for the same person's
  identity at Site A, Site B, and Site C (via matching blind index / matching key, mechanism TBD),
  request erasure from Site A, assert Site B's and Site C's rows show the erasure's effect.
- strategy: Fully-Automated

**AC-2 — The requesting tenant cannot see or learn anything about the reached tenants beyond what
the notification model (Open Question #4) explicitly allows**
The erasure response returned to Site A does not reveal whether any other tenant held the person,
which tenant(s) they were, or how many — beyond whatever the resolved notification model
explicitly permits.
- proven by: integration test — assert the erasure endpoint's response shape is identical whether
  0, 1, or N other tenants held a matching row (existence-oracle protection, same shape as Phase 1's
  C1 rule).
- strategy: Fully-Automated

**AC-3 — Idempotent across repeated and partial runs**
Triggering the cross-tenant reach mechanism twice for the same erasure request, or once after some
but not all tenants have already been reached, produces the same end state with no error and no
double-processing artifact (e.g. no duplicate suppression rows, no re-triggered notification if
Open Question #4 resolves to "notify").
- proven by: integration test — run the mechanism twice in sequence, assert second run is a no-op
  against already-reached tenants and completes cleanly against any newly-matching tenant.
- strategy: Fully-Automated

**AC-4 — Auditability: which tenants were reached, and how**
Given an erasure request, an operator can determine which tenants were reached by its cross-tenant
effect, when, and what action was taken (suppressed vs. deleted) — without ad-hoc SQL.
- proven by: integration test exercising the lookup/audit surface end-to-end against a seeded
  multi-tenant erasure, asserting the correct tenant list, timestamps, and action type are returned.
  Exact surface (extend Phase 1's AC-10 lookup, a new endpoint, or a CLI script) is a PLAN decision.
- strategy: Fully-Automated

**AC-5 — Standing guard for rows created after the sweep already ran**
A tenant who creates a new matching identity row for the erased person *after* the cross-tenant
reach mechanism has already executed for that person is still blocked at write time — the erased
person is never silently re-added to a newly-identifying tenant's table as if the erasure had never
happened.
- proven by: integration test — run the erasure/reach mechanism, then have a different (not-yet-
  reached) tenant independently identify the same person for the first time; assert the write is
  blocked or immediately suppressed, matching the outcome chosen for Open Question #3.
- strategy: Fully-Automated

**AC-6 — Existing per-tenant guard behavior is not regressed**
`_cascade_suppress` and the existing `do_not_email`/`do_not_resolve` suppression pathway continue to
work exactly as they do today for suppression entries created through the normal
(non-cross-tenant-erasure) path.
- proven by: existing regression suite plus a new assertion that ordinary single-tenant suppression
  flows (`add_suppression()` → `_cascade_suppress()`) are unaffected by whatever new mechanism this
  SPEC's PLAN introduces.
- strategy: Fully-Automated

**AC-7 — Rate-limit and abuse posture inherited from Phase 1**
The cross-tenant reach mechanism does not become a new way for one tenant to trigger unlimited
mutation attempts against other tenants' data; it is rate-limited per requesting site consistent
with Phase 1's `graph_erasure_max_per_minute` posture (or an explicitly justified equivalent).
- proven by: integration test — exceed the rate limit from a single requesting site, assert `429`
  and no partial cross-tenant mutation occurs for the rejected request.
- strategy: Fully-Automated

**AC-8 — Matching does not require persisting plaintext email in any new durable queue**
Whatever matching mechanism PLAN selects to find other tenants' rows, it does not require writing a
plaintext email into a new durable table — either by reusing the blind-index columns confirmed to
already exist on `IdentifiedVisitor.email_bidx`/`VisitorEmail.email_bidx`, or by another
plaintext-free approach.
- proven by: code review + a unit test asserting no plaintext email string appears in any new table
  or queue row written by the mechanism (mirrors Phase 1's T-P2 log-inspection probe pattern).
- strategy: Hybrid (Fully-Automated schema/write assertion + Agent-Probe review that no code path
  was missed)

**AC-9 — No PII in logs**
The cross-tenant reach mechanism's logging follows the existing PII-safety pattern (visitor id
prefix / site id / counts only, never plaintext email, name, or ciphertext).
- proven by: log-inspection probe — run the full flow at DEBUG, assert no structlog record contains
  plaintext PII.
- strategy: Agent-Probe

## Out Of Scope

- **Phase 1's own scope** — the shared `beam_identity_graph` erasure sweep, the write-boundary
  guard on `_upsert_beam_identity`, the operator lookup for the shared graph, and the disclosure
  copy work are all Phase 1's territory. This SPEC does not restate or re-litigate them.
- **`visitor_emails` non-deletion within the visitor's own tenant** — Phase 1 recorded (S4
  observation, `visitor-emails-erasure-gap_NOTE_07-08-26.md`) that `visitor_emails` rows are not
  deleted by the existing per-visitor DELETE endpoint even for the requesting tenant's own data.
  That is a *same-tenant* completeness gap, separate from this SPEC's *cross-tenant* scope. Not
  addressed here.
- **Public legal copy** (privacy.html / terms.html / onboarding disclosure) — owned by Phase 1's
  AC-7/AC-8/AC-9, pending qualified privacy counsel review. This SPEC does not add new disclosure
  requirements beyond noting that whatever notification model Open Question #4 resolves to may
  itself need disclosure — flagged, not specified.
- **`CompanyGraphNode` erasure** — Phase 1's KG-3, unchanged: no person-level PII, needs its own
  legal read, not reopened here.
- **Deciding whether cross-tenant identity pooling should continue, expand, or become opt-in** —
  that is `identity-coop_07-08-26`'s territory, not this SPEC's.
- **One-time retroactive audit of every existing `IdentifiedVisitor` row against historical
  deletion requests that predate this feature** — same posture as Phase 1's KG-2 (no historical
  deletion-request log with sufficient detail exists to cross-reference); not committed to here.
- **Building a self-serve, visitor-facing "forget me" request form** — same as Phase 1's Out Of
  Scope; the trigger remains a site owner's existing dashboard/API action.
- **Choosing the specific matching mechanism, schema, or code path** — that is INNOVATE/PLAN's job.
  This SPEC establishes only the observable outcomes required.

## Constraints

- Depends on Phase 1 landing first (see Dependencies).
- Must preserve multi-tenancy: reaching Site B's data because of Site A's request must never leak
  Site B's other, unrelated data to Site A, and must never give Site A visibility into Site B's
  identity beyond whatever the notification model explicitly permits (Open Question #4).
- Must not weaken or bypass the existing `do_not_resolve`/suppression-list guard behavior for the
  ordinary (non-cross-tenant) suppression path (AC-6).
- PII handling constraints from `all-context.md` Business Guardrail #3 apply: no plaintext PII in
  logs; any new matching/write code path must respect the ciphertext/blind-index pattern.
- Must not introduce a new existence-oracle: no response surface may let one tenant infer whether
  another tenant holds a specific person, beyond what the resolved notification model explicitly
  allows (mirrors Phase 1's C1 existence-oracle rule).
- Legal/notification copy, if the resolved design requires any, must not be published without
  qualified privacy counsel review — same hard constraint as Phase 1.
- Any implementation plan must re-verify the live state of the three in-flight workstreams named
  in Dependencies before claiming blast radius on shared files (`identity_resolver.py`,
  `routers/visitors.py`, `suppression.py`).

## Open Questions

1. **Cross-tenant authority for mutating another tenant's own data.** Phase 1 resolved the
   analogous question for the *shared* graph via a platform-level erasure queue — a decision that
   was easier because `beam_identity_graph` is explicitly platform-owned data, not any single
   tenant's. `IdentifiedVisitor`/`VisitorEmail` rows are unambiguously **Site B's own data** —
   Site B paid for the lookup, decided to act on it, and owns the business relationship with that
   contact independent of Beam. Does Site A's erasure request alone suffice to mutate Site B's own
   table row, the same way it can reach the shared graph? Or does mutating another tenant's owned
   data require a different, higher bar (e.g. platform-operator review, a different authorization
   model, or Site B's own consent/notice before or after)? **This is the single most important
   unresolved question in this SPEC — everything else is downstream of the answer.** Owner:
   product/legal decision, needed before PLAN.
2. **Privacy-vs-completeness re-examined.** The blind-index columns confirmed to exist on
   `IdentifiedVisitor`/`VisitorEmail` (see Summary) mean a plaintext-free match is structurally
   possible for the *matching* step. It does not resolve whether the *mutation* itself (flipping a
   flag or deleting a row on data Beam does not own) is the right tradeoff to make automatically,
   platform-wide, without Site B's involvement. Owner: product/legal, informed by the answer to #1.
3. **Suppression vs. deletion.** Is the correct outcome for a reached tenant's row (a) suppression
   — set `do_not_email`/`do_not_resolve`, same shape as `_cascade_suppress`, row stays in Site B's
   table but stops being actioned — or (b) actual deletion of Site B's row? These are materially
   different products with materially different consequences for Site B: suppression preserves
   Site B's historical record and lets them see *why* a contact went dark; deletion removes data
   Site B may consider theirs to keep (e.g. for their own compliance/audit trail) without their
   consent. Owner: product/legal decision, needed before PLAN — this SPEC's ACs are written to
   accept either outcome ("reached by the erasure's effect") without prescribing which.
4. **Notification.** Does Site B learn that one of its contacts was suppressed or deleted by
   someone else's erasure request? Three shapes are plausible and none is chosen here: (a) silent
   — Site B discovers it only if/when they notice the contact stopped responding or the row is
   gone; (b) after-the-fact notice to Site B ("a contact was removed/suppressed due to a privacy
   request," with no detail about who requested it or from where); (c) no notification ever, by
   design, treated the same as any other suppression-list entry today. Silence is operationally
   simple but surprising to Site B (US-3). Notification risks leaking that a *specific* named
   person filed an erasure request, which is itself sensitive information about that person's
   privacy choices, disclosed to a company that may not otherwise have known the person wanted to
   be forgotten. Owner: product/legal decision, needed before PLAN.
5. **Matching mechanism/schema.** Given the blind-index columns already exist, is the mechanism a
   sweep query joining on `email_bidx`/`fingerprint` across `IdentifiedVisitor`/`VisitorEmail`
   platform-wide (mirroring Phase 1's sweep shape), a synchronous check, or something else? Not
   decided here — INNOVATE's job, informed by the answer to #1–#3.
6. **Does this extend to `enrichment_profiles` too?** `EnrichmentProfile` rows (LinkedIn/Twitter/
   job data) are enriched per-tenant and also carry PII. Are they in scope for "reached by the
   erasure's effect," or does the scenario/harm this SPEC targets (KG-6) only concern
   `IdentifiedVisitor`/`VisitorEmail` (the outreach-actionable surface)? Owner: needs a decision
   before PLAN scopes touchpoints — flagged because `EnrichmentProfile` was not named in Phase 1's
   KG-6 scenario but plausibly carries the same harm (an enriched profile of an erased person
   persisting at another tenant).

## Risk / Known-Gap Section

- **Authorization risk (Open Question #1) is the load-bearing risk of this entire SPEC.** If this
  is implemented before that question is resolved, or resolved incorrectly, the result is either
  (a) Site A unilaterally mutating Site B's owned business data without any authorization model,
  which is a new and arguably worse trust-boundary problem than the one being solved, or (b) a
  design that never ships because the authorization question was punted indefinitely. PLAN must
  not proceed past this SPEC without an explicit answer.
- **Notification risk (Open Question #4) cuts both ways.** Silence protects the erased person's
  privacy about *who* they asked to forget them, but is surprising and potentially trust-eroding
  for Site B. Notification protects Site B's trust but risks disclosing sensitive information about
  the erased person's choices to a company they may not want to know. There is no notification
  design that is risk-free; PLAN must pick a side deliberately, not by default.
  Notification, if it happens, also needs privacy counsel review for content — same hard
  constraint as Phase 1's legal-copy work — because it is disclosing that a privacy action
  occurred, which is itself a category of disclosure with its own legal considerations.
- **Retroactive data risk, inherited.** Same as Phase 1's KG-2/Open Question 4: rows already
  existing today across tenants for people who already asked (through some other channel) to be
  forgotten are not addressed by a forward-looking mechanism. Not resolved by this SPEC.
- **Dependency risk.** This SPEC is blocked on Phase 1 landing, and Phase 1 itself is blocked on
  the user's KG-6 scoping decision (which this SPEC IS the answer to, in the sense that it takes
  KG-6 and turns it into its own unit of work rather than folding it back into Phase 1). If Phase 1
  changes shape materially during its own PVL cycles (e.g. the tombstone mechanism changes), this
  SPEC's assumptions about what Phase 1 provides must be re-checked before PLAN.
- **Scope-creep risk (Open Question #6).** If `EnrichmentProfile` turns out to be in scope, the
  blast radius and matching-key surface both grow — flagged now so PLAN doesn't discover it late.

## Note — Not Legal Advice

Every acceptance criterion and open question in this document that touches authorization to mutate
another tenant's data, notification content, or the suppression-vs-deletion choice is a
**requirement for what must be reviewed and approved by qualified privacy counsel** before any
implementation ships to production — this SPEC is engineering requirements gathering, not a legal
conclusion. In particular, Open Question #1 (cross-tenant authorization for mutating another
tenant's own data) is exactly the kind of decision that should not be made by an engineering team
alone; it has real legal and contractual dimensions (what does Beam's terms of service with Site B
promise about the integrity of Site B's own data?) that are outside this SPEC's authority to
resolve.

## Background / Research Findings

- Source: Phase 1 SPEC (`graph-erasure-compliance_SPEC_07-08-26.md`) and PLAN
  (`graph-erasure-compliance_PLAN_07-08-26.md`), especially KG-6 (verbatim scenario reused above),
  §0 (hard sequencing constraint / blast-radius claims on `identity_resolver.py`), §2 ("Matching
  key" — Phase 1's queue is deliberately plaintext-free, keyed on `email_bidx` + fingerprint), and
  checklist items C-08 (tombstone writes via raw insert, no `_cascade_suppress` call) / C-15
  (write-boundary guard hunk).
- `results.tsv` rows 0–1: Phase 1 is at PVL supplement cycle 1, `Gate: CONDITIONAL`, `BLOCKED ON
  USER: KG-6 scoping decision required before re-validate` — this SPEC is that scoping decision,
  spun out as its own task per the user's direction.
- `apps/api/services/suppression.py:1-11` (module docstring) and `:43-` (`_cascade_suppress`):
  confirmed `_cascade_suppress(db, email: str, scope: str)` requires plaintext throughout — it
  computes `normalize_email(email)` and matches `func.lower(IdentifiedVisitor.email) == norm` /
  `VisitorEmail.email == norm`; `VALID_SCOPES = {"all", "do_not_sell", "do_not_process",
  "do_not_email"}`; sole caller is `add_suppression()`. No ORM event listener triggers it. This
  confirms Phase 1's finding that the sweep structurally cannot call it, and that closing KG-6
  cannot simply "reuse" this function without solving the plaintext problem some other way.
- `apps/api/services/pii_crypto.py:66-70` — `email_hash()`, HMAC-SHA256 over
  `normalize_email(email)`, keyed by `PII_HMAC_KEY`/`ENCRYPTION_KEY`, deterministic, one
  implementation, 16 call sites all routed through it (per Phase 1's Correction 2, independently
  re-confirmed here).
- **New finding this session (not present in Phase 1's docs): `IdentifiedVisitor.email_bidx`
  (`apps/api/models/visitor.py:227`) and `VisitorEmail.email_bidx`
  (`apps/api/models/visitor_email.py:68`) are live, populated blind-index columns**, kept in sync
  by `apps/api/services/pii_encryption_hooks.py` — a SQLAlchemy `before_insert`/`before_update`
  mapper-event listener registered for `IdentifiedVisitor` and `VisitorEmail` (and `BeamIdentityNode`
  and `EnrichmentProfile`) that sets `email_bidx = email_hash(email)` on every write. Two additional
  explicit-write sites exist for `VisitorEmail.email_bidx` where core-table bulk inserts bypass ORM
  events: `apps/api/routers/click.py:125` and `apps/api/routers/events.py:813`. This means a
  blind-index join across tenants (`IdentifiedVisitor.email_bidx = :target_bidx` /
  `VisitorEmail.email_bidx = :target_bidx`) is a live, queryable possibility today — the "verify
  whether a usable blind index exists" instruction for this SPEC session resolves to **yes, on both
  tables that matter for KG-6's scenario.** This is Background context for INNOVATE, not a
  mechanism choice made by this SPEC.
- `process/features/visitors-identity/_GUIDE.md` — confirms Business Guardrail #3 (PII) and the
  GPC/DNT/`do_not_resolve` pattern are the established privacy posture this SPEC extends.
- Three in-flight workstream statuses (`identity-coop_07-08-26` PLAN'd/not validated,
  `identity-vocab-reconcile_07-08-26` EXECUTED/accepted/unpushed) confirmed via
  `process/features/visitors-identity/active/` directory listing at SPEC time — re-verify at PLAN
  time, these change quickly in this feature folder (9 active task folders as of this session).
