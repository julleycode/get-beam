---
name: plan:identity-coop-spec
description: "SPEC B — turn Beam's implicit cross-tenant identity graph into an explicit opt-in data co-operative with a spendable credit ledger"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# Identity Co-op — SPEC

**Date:** 07-08-26
**Feature:** visitors-identity
**Status:** SPEC — locked pending INNOVATE

---

## Summary

Today, every Beam customer's site already writes into and reads from one shared cross-tenant
identity graph (`beam_identity_graph`) with no opt-in, no visibility, and no benefit back to the
site that contributed the match. This SPEC turns that silent pooling into an explicit
**data co-operative**: a site owner flips a switch to contribute their site's identity matches to
the shared graph, Beam tracks what they put in and what they take out, and Beam pays them back in
**spendable credits** they can redeem against future identity resolution. Sites that don't opt in
contribute nothing new — no surprises, no silent participation. This makes an already-existing
practice honest and gives contributors a reason to say yes.

## User Stories / Jobs To Be Done

**US-1 — Prospective contributor site owner.**
As a site owner deciding whether to turn on graph contribution, I want to see plainly what I'm
agreeing to (my site's identity matches join a shared pool other Beam customers can benefit from)
and what I get in return (spendable credits I can track and redeem), so I can make an informed
opt-in decision instead of guessing.

**US-2 — Existing customer who discovers the graph exists.**
As a customer who learns, after the fact, that Beam already pools identity data across customers,
I want to understand that my site's past contributions are grandfathered (not retroactively
un-shared, not purged) and that going forward my participation is my own explicit choice, so I
trust Beam's data practices are honest from this point on.

**US-3 — The end visitor whose data is in the graph.**
As a visitor of Site B who gets identified using a match that originated from Site A, I want my
data to have been shared with a consent basis I could have exercised control over, so my identity
isn't traded between businesses I never interacted with, without any consent trail at all.

**US-4 — Operator/founder.**
As Beam's operator, I want measurable proof of who contributes and who consumes before I owe
anyone credits, and I want the credit mechanism to be fraud-resistant and legally defensible
enough to ship, so the co-op doesn't become a liability or a game-able piggy bank.

## What The User Wants (Behavioral Outcomes)

- A per-site toggle, defaulting OFF, that a site owner explicitly turns on to start contributing
  their site's identity matches to the shared cross-tenant graph.
- Turning the toggle on requires the owner to affirmatively accept a stated commitment: they will
  obtain their own visitors' consent to this sharing and offer those visitors an opt-out. Beam
  provides ready-to-use model privacy-policy language for the customer to adopt; Beam does not
  alter its own pixel-facing consent banner to disclose cross-tenant sharing on the customer's
  behalf.
- From the moment a site opts in, every new graph write it produces is counted as a contribution
  belonging to that site. Before opt-in, that site's resolver activity produces zero new graph
  writes attributable to it under this program.
- Every site — contributor or not — has a metered relationship to reading the graph, and the SPEC
  states explicitly what that relationship is (see AC-2) rather than leaving it as an accident of
  how the resolver waterfall already works.
- A site accrues spendable credits for verified contributions and spends them against future
  identity-resolution costs. Credits are trackable, expire per a stated policy, and every
  accrual/spend event is reconstructable after the fact (an audit trail, not just a running
  balance).
- A site owner can see their own site's contribution count, consumption count, and credit balance
  on a dashboard surface — never another tenant's data.
- Contribution can't be gamed by generating synthetic or bot traffic to farm credits; the credit
  mechanism only rewards real, bot-filtered, previously-unseen identity matches.
- Rows written to the graph before this program shipped keep their current behavior: no purge, no
  retroactive re-attribution, no retroactive credit. They are a stated, permanent known-gap in the
  program's consent story.

## Flow / State Diagram

```
Site owner (per-site toggle)
                                     ┌─────────────────────────────┐
   default: contribution_enabled=OFF│                               │
        │                            │                               │
        │  owner opts in             │                               │
        ▼                            │                               │
 ┌───────────────┐   accepts pass-  │                               │
 │ Opt-in prompt  │──through terms──▶│  contribution_enabled = ON   │
 │ + model policy │   (explicit)     │  (per-site flag, from now on)│
 │ language shown │                  └───────────────┬───────────────┘
 └───────────────┘                                    │
                                                        │ every new
                                                        │ graph-eligible
                                                        │ identification
                                                        ▼
                                          ┌─────────────────────────┐
                                          │ _upsert_beam_identity    │
                                          │ (existing write path)    │
                                          │  + contribution metric   │
                                          │    recorded, site-scoped │
                                          └────────────┬──────────────┘
                                                        │ passes fraud/
                                                        │ bot-filter gate
                                                        ▼
                                          ┌─────────────────────────┐
                                          │ Credit ledger: ACCRUE     │
                                          │ (site_id, +N credits,     │
                                          │  reason, timestamp)       │
                                          └────────────┬──────────────┘
                                                        │
                          ┌─────────────────────────────┴───────────────────────────┐
                          ▼                                                          ▼
             ┌─────────────────────────┐                              ┌───────────────────────────┐
             │ Any site's resolver hits │                              │ Credits sit in ledger,      │
             │ a graph-served match     │                              │ visible on dashboard,        │
             │ (existing read path,     │                              │ subject to expiry policy     │
             │ AC-2 governs eligibility)│                              └──────────────┬────────────────┘
             └────────────┬──────────────┘                                            │
                          │ consumption metric recorded, site-scoped                  │ owner redeems
                          ▼                                                          ▼
             ┌─────────────────────────┐                              ┌───────────────────────────┐
             │ Dashboard: contribution/ │                              │ Credit ledger: SPEND        │
             │ consumption/balance      │◀─────────────────────────────│ (site_id, -N credits,       │
             │ stats surfaced to owner  │                              │  reason, timestamp)          │
             └─────────────────────────┘                              └───────────────────────────┘

Grandfathered rows (written before program ships):
   [existing beam_identity_graph rows] ──── no consent trail, no purge, no retro credit ──── permanent known-gap
```

## Acceptance Criteria (Testable Outcomes)

**AC-1 — Opt-in flag defaults OFF, per site, and gates all NEW contribution.**
A site's `contribution_enabled` (or equivalent) flag defaults to OFF for every existing and new
site. While OFF, that site's identification activity produces zero new rows/writes attributable to
it in the cross-tenant graph contribution accounting. Turning it ON only affects identifications
that happen after the flag flips — it is not retroactive.
`proven by:` Fully-Automated integration test asserting a site with the flag OFF produces zero
counted contributions across a resolve cycle that would otherwise have written to the graph.
`strategy:` Fully-Automated.

**AC-2 — Non-contributor read access is explicitly decided, not left implicit.**
The SPEC requires INNOVATE/PLAN to pick one of two stated models and document the choice:
(a) **read access is unconditional** — any site, contributor or not, may still benefit from
graph-served matches, and the co-op's incentive is purely the credit reciprocity for contributing;
or (b) **read access is gated on contribution** — only sites with `contribution_enabled = ON` (or
with a positive credit balance) may consume graph-served matches, making contribution a
precondition of the benefit, not just a bonus on top of it. This SPEC does not choose between (a)
and (b) — it requires the choice be made explicitly and stated in the PLAN, because it is the core
economic question of the co-op (an all-take, no-give status quo vs. a strict pay-to-play system),
and today's code implements (a) as an unexamined accident, not a decision.
`proven by:` Fully-Automated test asserting the PLAN's documented choice is what ships — i.e. a
non-contributing site's resolver either does or does not receive graph-served identifications,
matching whichever model was chosen.
`strategy:` Fully-Automated.

**AC-3 — Contribution is countable per site and merge-aware.**
Every graph write attributable to an opted-in site is counted against that site, using
`source_site_id` (or an equivalent site-scoped attribution) as the unit of measurement. Counting
must be aware of the merged-visitor double-counting risk documented in
`backlog/merged-visitor-consumer-awareness_NOTE_04-08-26.md` — a single real-world person
resolved twice under `identity_status="merged"` duplicate rows must not inflate a site's counted
contribution.
`proven by:` Fully-Automated unit test with a synthetic merged-duplicate scenario asserting
contribution count reflects the deduplicated/canonical identity, not the raw row count.
`strategy:` Fully-Automated.

**AC-4 — Consumption is countable per site and distinguishes graph-served from provider-purchased.**
Every time a site's resolver waterfall serves an identification from the shared graph
(`_graph_node_by_email` or equivalent graph-read branch) rather than from a paid provider call, it
is counted as a graph consumption event attributable to the consuming site, structurally separate
from provider-purchased resolutions (which already have their own budget-tracking).
`proven by:` Fully-Automated integration test asserting a graph-hit resolve increments the
graph-consumption counter and does NOT increment the provider-spend counter, and vice versa for a
provider-purchased resolve.
`strategy:` Fully-Automated.

**AC-5 — Credits accrue on verified contribution.**
A contributing site earns a defined, non-zero credit amount per qualifying contribution event
(subject to AC-7's fraud gate). The accrual event is written to a ledger, not just added to a
running total, so it can be individually inspected later.
`proven by:` Fully-Automated integration test asserting one qualifying contribution produces one
ledger accrual row with a positive amount, site_id, reason, and timestamp.
`strategy:` Fully-Automated.

**AC-6 — Credits are spendable against identity-resolution cost.**
A site with a positive credit balance can have that balance decremented to offset (in full or in
part) the cost of a real identity-resolution action, and the spend event is written to the ledger
the same way an accrual is.
`proven by:` Fully-Automated integration test asserting a spend event decrements the balance and
writes a ledger row with a negative (or spend-typed) amount, site_id, reason, and timestamp.
`strategy:` Fully-Automated.

**AC-7 — Credits expire per a stated policy.**
Unspent credits expire after a defined window (the exact window is an INNOVATE/PLAN decision, not
locked here). Expiry is enforced by ledger accounting (an expiry event/row), not silently dropped
from a balance with no trace.
`proven by:` Fully-Automated unit test asserting a credit past its expiry window is excluded from
spendable balance and an expiry ledger entry exists explaining why.
`strategy:` Fully-Automated.

**AC-8 — Ledger is auditable and reconcilable.**
For any site, the sum of all ledger events (accrue, spend, expire) reconstructs the current
spendable balance exactly — the balance is never a value that can drift from its ledger history.
`proven by:` Fully-Automated test asserting `sum(ledger events for site) == current balance` holds
after a randomized sequence of accrue/spend/expire operations.
`strategy:` Fully-Automated.

**AC-9 — Fraud resistance: no credit from synthetic/bot traffic.**
A contribution only counts toward credit accrual if the underlying identification passed Beam's
existing bot/abuse filtering (referencing the same shape of gate used by
`apps/api/services/referral_activation.py`'s anti-fraud check — real, bot-filtered ingested
activity, not merely "an event arrived"). A site cannot manufacture credit by feeding synthetic or
bot-flagged fingerprints through the resolver.
`proven by:` Fully-Automated integration test asserting a resolve driven by traffic flagged
`is_abuse_flagged` / `is_bot_suspect` (or equivalent) produces zero credit accrual even though a
graph write may still occur.
`strategy:` Fully-Automated.

**AC-10 — Opt-in requires explicit acceptance of the contractual pass-through.**
The opt-in action is not a bare toggle flip — it requires the site owner to explicitly acknowledge
a stated commitment (they are responsible for obtaining their own visitors' consent to cross-tenant
sharing and for offering those visitors an opt-out), before the flag can be set to ON. Beam
supplies ready-to-use model privacy-policy language the customer can adopt, but does not modify its
own pixel-facing consent banner to add cross-tenant disclosure on the customer's behalf.
`proven by:` Hybrid (automated: the flag cannot be set ON via API without the acceptance flag/field
also being set in the same request; Agent-Probe: a human/legal reviewer confirms the model policy
language and acceptance UX copy match the intended contractual meaning).
`strategy:` Hybrid.

**AC-11 — Contributor-facing stats surface is self-scoped only.**
A site owner can view their own site's contribution count, consumption count, and credit ledger
balance/history. They cannot see any other tenant's contribution/consumption counts, ledger
entries, or any PII belonging to another tenant's visitors.
`proven by:` Fully-Automated integration test asserting the stats endpoint, called with Site A's
auth, returns only Site A's numbers even when Site B has ledger activity, and returns 404/empty
(never leaking existence) for a foreign site_id.
`strategy:` Fully-Automated.

**AC-12 — Grandfathered rows are explicitly excluded from the new accounting.**
Graph rows written before this program ships are not retroactively attributed to any site's
contribution count, do not generate retroactive credit, and are not purged or re-consented. This
is a stated, permanent behavior, not a bug to later fix.
`proven by:` Fully-Automated test asserting a pre-existing `beam_identity_graph` row with no
program-attribution marker contributes 0 to any site's ledger when the program's accounting job
runs.
`strategy:` Fully-Automated.

## Out Of Scope

- Choosing the credit accrual rate, the redemption exchange rate, or the expiry window (numeric
  values) — these are INNOVATE/PLAN decisions.
- Choosing the concrete schema/table design for the ledger, contribution counters, or opt-in flag
  — PLAN territory.
- Retroactively purging, re-consenting, or attributing credit to pre-existing graph rows (see
  AC-12 — explicitly out, not deferred).
- Adding cross-tenant-sharing disclosure to Beam's own pixel-facing consent banner. The contractual
  pass-through places that obligation on the contributing site owner, not on Beam's banner.
- Any change to the erasure/deletion mechanics of the graph — that is SPEC A's scope
  (`graph-erasure-compliance_07-08-26`), not this SPEC's.
- Any change to `identity_resolver.py` §3.2 provider-candidate vocabulary/gating logic — that is
  `identity-vocab-reconcile_07-08-26`'s scope, not this SPEC's.
- Fixing the 5-file merged-visitor double-counting gap end-to-end — this SPEC only requires AC-3's
  contribution-counting logic to be merge-aware; it does not require fixing `kpi.py`,
  `timeseries.py`, `campaign_sender.py`, `segmenter.py`, or `csv_exporter.py` themselves.
- A cash payout, discount, or any non-credit reciprocity mechanism (locked decision #1 — credit
  ledger only).
- Enabling any of this program's flags in production. Like every precedent flag in this codebase
  (`agent_detection_enabled`, `company_graph_enabled`, `identity_signals_enabled`), shipping code
  with the flag OFF is the deliverable; flipping it on is a separate, explicit, later operator
  action.
- Formal legal sign-off on the pass-through contract language — flagged as a hard prerequisite in
  Risks below, not something this SPEC or its downstream PLAN can satisfy itself.

## Constraints

- **Sequencing constraint — three workstreams converge on `identity_resolver.py`.** This program's
  contribution-write instrumentation touches `_save_identified` / `_upsert_beam_identity`, the same
  functions `identity-program_03-08-26` Phase 1 has explicitly claimed (status: PLANNED, not yet
  executed) and the same file `identity-vocab-reconcile_07-08-26` (currently PVL cycle 2, `Gate:
  BLOCKED`) is actively rewriting at §3.2, including `GRAPH_CANDIDATE_PROVIDERS` /
  `is_graph_candidate_provider()` (which already includes `beam_identity_network` as a named
  provider). EXECUTE for this program MUST NOT begin until both of those in-flight
  workstreams have either completed their own EXECUTE against `identity_resolver.py` or have
  explicitly coordinated blast radius with this program at PLAN time. This is a hard sequencing
  requirement, not a nice-to-have.
- **Dependency on SPEC A (`graph-erasure-compliance_07-08-26`).** SPEC A is fixing the erasure gap
  and stale legal copy for the same graph this SPEC adds consent/reciprocity to. This SPEC does
  not restate or duplicate SPEC A's content. Sequencing requirement: the consent-and-credit
  mechanics in this SPEC should not ship as "the privacy story is now complete" messaging until
  SPEC A's erasure fixes are also live — a co-op with paid-for contribution but no working erasure
  path is a worse position than today's silent status quo, not a better one. INNOVATE/PLAN must
  state explicit relative sequencing (which ships first, or that they ship together) rather than
  treating the two programs as unrelated.
- **Migration chain currency.** Any new migration this program requires must chain onto the true
  current alembic head at execute time (`alembic -c apps/api/alembic.ini heads`), never a
  hardcoded value — the chain has moved repeatedly under concurrent work (see
  `process/context/all-context.md`, currently 13 pending migrations, head `e6b2d4a1c837` as of
  this writing but expected to move again before this program executes).
- **Flag-default precedent.** The opt-in flag must default OFF and follow the exact operator-gated
  rollout posture of `agent_detection_enabled` / `company_graph_enabled` / `identity_signals_enabled`
  — PLAN must not deviate from this precedent.
- **Fraud-resistance shape.** The credit-accrual anti-fraud gate must draw on the same idempotency
  + bot-filter shape already proven in `apps/api/services/referral_activation.py` (reward only
  after real, bot-filtered engagement) — not a new, unproven fraud model.
- **Business guardrail #3 (PII/GDPR)** from `process/context/all-context.md` applies in full: no
  PII in logs, encryption at rest for any new PII surface, GPC/DNT `do_not_resolve` respected.
- **Not legal advice.** This SPEC is a product-requirements document, not a legal opinion. The
  contractual pass-through mechanism (AC-10) requires review by qualified privacy counsel before
  the opt-in flow ships to any real customer — this is a hard prerequisite for production
  enablement, not merely recommended.

## Open Questions

None — all four foundational product decisions are locked per this task's instructions (credit
ledger reciprocity; default-OFF opt-in; tenant opt-in with contractual pass-through; grandfathered
rows unchanged). The one genuinely open design question — non-contributor read access model
(AC-2's choice (a) vs (b)) — is deliberately deferred to INNOVATE/PLAN as a modeled decision point,
not left as an unresolved SPEC gap; AC-2 requires PLAN to record whichever choice is made. Owner:
INNOVATE/PLAN phase.

## Risks / Known Gaps

- **Grandfathered rows have no consent trail.** Every row already in `beam_identity_graph` was
  written with zero contribution/consent signal of any kind. This program does not and cannot
  retroactively fix that (see AC-12, Out of Scope). It is a permanent known-gap, not a bug to
  schedule later.
- **Credit-as-consideration strengthens the CPRA "sale"/"share" characterization.** CPRA
  §1798.140 defines "sell"/"share" broadly, including non-monetary "valuable consideration."
  Paying a site owner in spendable credits for their contribution makes the consideration
  explicit and monetary-adjacent — this is a direct, structural consequence of locked decision #1
  (credit ledger over a free quota bump) and should be treated as elevated regulatory exposure,
  not a neutral implementation detail. Flagged for legal review per the Constraints section above.
- **No public vendor precedent for credit-style compensation.** Bombora's co-op, LiveRamp ATS, and
  Beam's own upstream providers (RB2B, Capturify, Opensend) all frame contributor benefit as
  monetization-enablement or better match rates — none were found publicly documenting cash or
  credit compensation to contributors. Beam's chosen mechanism is a genuine product
  differentiator, but it is also an unvalidated assumption about what the market/regulators will
  accept; there is no external playbook to lean on if something goes wrong.
- **Merged-visitor double-counting could corrupt contribution accounting if left unaddressed.**
  `backlog/merged-visitor-consumer-awareness_NOTE_04-08-26.md` documents that
  `_save_identified` already produces duplicate `identity_status="merged"` rows for any email
  resolved under two different `visitor_id`s, and 5 of 7 downstream consumers have zero awareness
  of this. AC-3 requires this program's contribution counter specifically to be merge-aware, but
  the broader 5-file gap remains open and unrelated consumers (segmenter, campaign_sender, etc.)
  could still double-count/double-send independently of this program.
- **Joint-controllership exposure under GDPR Art. 26.** A shared pool where each opted-in tenant's
  contribution becomes readable by other tenants is a plausible joint-controllership arrangement,
  which requires a transparent, documented allocation of responsibilities whose "essence" is made
  available to data subjects — a heavier compliance bar than a simple processor relationship. Not
  resolved by this SPEC; flagged for the same legal review as AC-10.
- **Not legal advice.** Restated for emphasis: nothing in this document constitutes legal advice,
  and the AC-10 contractual pass-through mechanism must not ship to production without qualified
  privacy counsel review of the model policy language and the acceptance flow.

## Background / Research Findings

**Current write path.** `apps/api/services/identity_resolver.py::_upsert_beam_identity` (~line
995), called unconditionally from `_save_identified` (~line 968), writes every successful
identification into `beam_identity_graph` with no per-site opt-in gate today — confirmed by direct
code read, no `settings.*_enabled` check anywhere in this call path. `source_site_id` is written on
every row (`apps/api/models/beam_identity.py`, `String`, `NOT NULL`) but has exactly one reader
repo-wide: the site-deletion cascade at `apps/api/routers/sites.py:281-286`
(`DELETE FROM beam_identity_graph WHERE source_site_id = :sid`), confirmed live. There is zero
existing instrumentation distinguishing "who contributed this row" from "who benefited from a
graph-served match" — this program cannot build a credit ledger on top of nothing; measurement is
foundational, not incidental.

**Current read path.** `_graph_node_by_email` (~lines 1034-1083) and the "Beam Identity Network"
check branch (~line 423) read cross-tenant with no `site_id` filter — any site's resolver can hit
any other site's contributed row today. Graph-derived identifications land at ~0.80 confidence
(~0.85 when corroborated).

**Engineering precedents surfaced by research (shape reference only, not the chosen mechanism):**
- `Site.auto_identify_enabled` (`apps/api/models/site.py:28`) — full 7-layer per-site boolean
  wiring: model → migration → schema → router → service → dashboard toggle → API types. The shape
  to imitate for the opt-in flag.
- `agent_detection_enabled` / `company_graph_enabled` / `identity_signals_enabled` in
  `apps/api/config.py` — default-OFF, operator-gated global flag precedent.
- `apps/api/services/referral_activation.py` + `REFERRAL_BONUS_PER_ACTIVATION` /
  `REFERRAL_BONUS_CAP` (`apps/api/services/billing.py:36-37`) + `User.bonus_monthly_quota`
  (`apps/api/models/user.py:61-63`) — idempotent reward-sweep shape (single conditional UPDATE +
  advisory lock + hourly job) with an anti-fraud gate (reward only after the referee's pixel
  records real, bot-filtered ingested events). This is the fraud-resistance and idempotency shape
  to reference for AC-9 — explicitly NOT the reward mechanism itself, since decision #1 requires a
  real ledger instead of an additive quota bump like `bonus_monthly_quota`.
- `Site.daily_resolution_budget` (default 50) and plan `monthly_limit`
  (`apps/api/routers/billing.py:75`) — existing quota surface a credit-spend mechanism will likely
  need to interact with (an INNOVATE/PLAN decision, not locked here).

**External vendor research (cited as external, not code-verified):**
- Bombora Data Co-op (bombora.com/co-op) — publishers contribute behavioral data; contractually
  responsible for visitor consent + opt-out. Source of the locked consent-model pattern (decision
  #3).
- LiveRamp ATS — per-user consent gates the SDK; benefit framed as cookieless targeting capability.
- RB2B / Capturify / Opensend (Beam's own upstream providers/competitors) — no published
  contributor/co-op mechanics found at all.
- No vendor in this class was found publicly documenting cash/credit compensation to contributors
  — see Risks.

**Regulatory survey (external, factual only, not legal advice):** CPRA §1798.140 broad
"sell"/"share" definition including non-monetary "valuable consideration"; GDPR Art. 26 joint
controllers; GDPR Art. 14 third-party-source notice duties; EDPB Guidelines 1/2024 on legitimate
interest (3-step test, cross-context sharing typically fails the "reasonable expectations" limb);
enforcement precedent — CA AG v. Sephora ($1.2M, GPC non-honoring), CPPA multi-state GPC sweep
(2025-09-09), Belgian DPA v. IAB Europe TCF (€250k upheld 2025-05-15, shared identity/consent
infrastructure operators held directly liable); growing private CIPA litigation risk aimed at the
website operator (i.e. Beam's own customers), statutory $5k/violation.

**Related in-flight work confirmed by direct file listing:**
`process/features/visitors-identity/active/` currently holds three task folders:
`graph-erasure-compliance_07-08-26` (SPEC A, parallel), `identity-program_03-08-26` (umbrella,
Phase 1 claims `_save_identified`, status PLANNED), and `identity-vocab-reconcile_07-08-26`
(currently PVL cycle 2, `Gate: BLOCKED`, rewriting `identity_resolver.py` §3.2 including
`GRAPH_CANDIDATE_PROVIDERS` / `is_graph_candidate_provider()`, which names
`beam_identity_network` as a provider). All three converge on `identity_resolver.py` — see
Constraints for the sequencing requirement this creates.

**Merged-visitor gap confirmed by direct read:**
`process/features/visitors-identity/backlog/merged-visitor-consumer-awareness_NOTE_04-08-26.md` —
`_save_identified` (lines 832-859) produces `identity_status="merged"` duplicate rows for every
email resolved under two different `visitor_id`s; 5 of 7 named consumer surfaces
(`kpi.py`, `timeseries.py`, `campaign_sender.py`, `segmenter.py`, `csv_exporter.py`) have zero
awareness of `canonical_visitor_id`/`"merged"` today.
