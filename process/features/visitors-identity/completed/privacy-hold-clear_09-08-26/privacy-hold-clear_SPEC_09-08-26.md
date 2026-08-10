---
name: privacy-hold-clear_SPEC
description: "SPEC — Option D: Privacy-hold UX + explicit site-owner Clear for sticky do_not_resolve. Product-discovery requirements doc for user review."
date: 09-08-26
metadata:
  node_type: spec
  type: spec
  feature: visitors-identity
  phase: SPEC
  approach: "D (privacy-hold UX + explicit confirmed owner Clear)"
---

# SPEC — Privacy-Hold UX + Explicit Site-Owner Clear

## Summary

When a visitor's browser sent a privacy signal (GPC / Do-Not-Track, or a cascaded suppression
match), Beam sets a **sticky** `do_not_resolve` flag on that visitor. Sticky is intentional: once a
person opts out, a later "clean" recompute must never silently re-enable identifying them. But this
created a dead end — a real visitor who turned GPC **off** stayed permanently blocked, and the only
way to un-block them was a manual SQL `UPDATE` in the database (this actually happened to a Brave/GPC
visitor). This work gives the **site owner** a clear, honest in-product path: the dashboard plainly
explains *why* a visitor is on privacy hold, and offers a single, **confirmed** button to lift the
hold **for that one visitor on that one site**, with an audit record. It deliberately does **not**
auto-lift anything and does **not** remove anyone from the suppression list — lifting the hold stays
a deliberate human act, in keeping with Beam's "no silent reverse" compliance stance.

## User Stories / Jobs To Be Done

- **US-1 (understand the block).** As a site owner looking at an anonymous visitor, I want the
  dashboard to tell me plainly that this visitor is on a **privacy hold** (not a budget/limit
  problem), so that I stop wasting clicks on "Identify" and understand it is a policy block.

- **US-2 (intentional un-block).** As a site owner who knows a specific visitor's privacy signal no
  longer applies (e.g. they turned GPC off), I want a deliberate, confirmed action to clear that
  visitor's privacy hold **for my site only**, so that I can then try to identify them through the
  normal flow — without editing the database by hand.

- **US-3 (safe by default).** As a site owner (and as the person whose data it is), I want clearing
  a hold to be an obvious, confirmed, non-silent action that does **not** touch the suppression list,
  so that I can never accidentally re-enable processing for someone who is genuinely on a
  do-not-process list.

- **US-4 (JTBD).** *When* a visitor I care about is stuck on privacy hold after their privacy signal
  changed, *I want to* lift the hold myself from the dashboard with a clear confirmation, *so I can*
  resume normal identification without contacting support or running SQL.

## What The User Wants (Behavioral Outcomes)

From the outside, the owner experiences this:

1. On a visitor who is on privacy hold, the Visitors dashboard shows a distinct, readable **"Privacy
   hold"** state with copy explaining it is a privacy/opt-out block, *not* a usage limit — replacing
   the current behavior where the row just looks un-identifiable with a generic message.
2. For a held visitor, a **"Clear privacy hold"** action is offered. It is only offered for rows that
   are actually on privacy hold.
3. Clicking it opens a **confirmation dialog** that states, in plain language, that this is a
   deliberate action, that it lifts the hold only for this visitor on this site, and that it does
   **not** remove the person from any suppression list.
4. On confirm, the hold is lifted for that one visitor row. The "Privacy hold" state disappears and
   the normal **Identify** control becomes available again.
5. If the owner cancels the dialog, nothing changes.
6. Identifying after a clear goes through the **existing** identify/resolve path — there is no new
   "force" path that bypasses a hold while it is still in place.
7. If that same person's browser later sends another opt-out event, the visitor may go **back** onto
   privacy hold automatically. This is expected and is communicated, not treated as a bug.
8. Suppression-list protection is untouched: if the person's email is on the suppression list,
   identification still refuses even after the hold is cleared.

## Flow / State Diagram

```
                         Visitor on a site
                               |
             pixel events include an opt-out (GPC/DNT/suppression cascade)
                               |
                               v
                 +-----------------------------+
                 | do_not_resolve = TRUE        |  <-- sticky (BOOL_OR / OR upsert)
                 | resolution_skip_reason =     |      set by aggregator, UNCHANGED
                 |   "privacy_opt_out"          |
                 +-----------------------------+
                               |
             Owner opens Visitors dashboard, sees this visitor
                               |
                               v
        [UI] "Privacy hold" state + explanation copy (US-1)
                               |
              Owner decides the signal no longer applies
                               |
                               v
          [UI] Owner clicks "Clear privacy hold" (offered only for held rows)
                               |
                               v
                 +-----------------------------+
                 |   Confirmation dialog        |
                 |  "deliberate, this site only,|
                 |   does NOT un-suppress"      |
                 +-----------------------------+
                   |                        |
              Cancel                     Confirm
                   |                        |
                   v                        v
         nothing changes        site-scoped auth check (same as resolve)
                                            |
                                foreign/unauthorized -> 404, no write
                                            |
                                        authorized
                                            |
                                            v
                        +-------------------------------------+
                        | do_not_resolve = FALSE (this row)    |
                        | audit record written (who/when/      |
                        |   site/visitor, no PII)              |
                        +-------------------------------------+
                                            |
                          +-----------------+------------------+
                          |                                    |
                          v                                    v
              banner gone; Identify shown          email on suppression list?
                          |                                    |
                          v                            yes -> resolve still REFUSES
                Owner clicks Identify                         (suppression gate)
                          |
                          v
                existing /resolve waterfall (no bypass)
                          |
             ... later, a new opt-out event arrives ...
                          |
                          v
             do_not_resolve may return to TRUE (expected; documented)
```

## Acceptance Criteria (Testable Outcomes)

> Strategy tags: **Fully-Automated** (E2E/integration/unit gate), **Hybrid** (automated logic gate +
> operator/visual confirm), **Agent-Probe** (manual/judgment residual where automation is genuinely
> impossible). Scenario names below are grounded in the existing test surfaces
> (`tests/unit/`, `tests/integration/`, `apps/web` component/e2e); PLAN/VALIDATE bind them to exact files.

- **AC-1 — Held visitors read as a privacy hold, not a limit.** A visitor whose
  `resolution_skip_reason === "privacy_opt_out"` / `do_not_resolve === true` shows a distinct
  "Privacy hold" state with copy that says it is a policy/opt-out block, not a usage cap.
  - proven by: `visitors-detail-privacy-hold-banner` (web component/e2e render assertion)
  - strategy: Hybrid

- **AC-2 — The clear action appears only for held rows.** A "Clear privacy hold" control is shown for
  privacy-held visitors and is absent for visitors that are not on privacy hold.
  - proven by: `clear-hold-button-visibility` (web component test — held vs not-held)
  - strategy: Fully-Automated

- **AC-3 — Clearing requires an explicit confirmation.** Activating "Clear privacy hold" opens a
  confirmation dialog; no write occurs unless the owner confirms; cancel leaves state unchanged.
  - proven by: `clear-hold-confirm-dialog` (web e2e — confirm path writes, cancel path no-op)
  - strategy: Hybrid

- **AC-4 — Confirm lifts the hold for exactly one visitor on one site.** A confirmed clear sets
  `do_not_resolve = false` for the target `(site_id, visitor_id)` row only, and no other visitor row
  is affected.
  - proven by: `integration_clear_hold_scoped_flip` (integration — asserts single-row flip)
  - strategy: Fully-Automated

- **AC-5 — Only an authorized site member may clear.** The clear endpoint uses the same site-scoped
  authorization as resolve; a caller without access to the site receives a not-found response and no
  write happens (no id-existence leak — 404, not 403, per multi-tenancy convention).
  - proven by: `integration_clear_hold_cross_tenant_404` (integration)
  - strategy: Fully-Automated

- **AC-6 — After clear, the UI returns to normal.** Once a clear succeeds, the "Privacy hold" state
  is gone and the standard **Identify** control is available for that visitor.
  - proven by: `clear-hold-post-clear-ui` (web e2e)
  - strategy: Hybrid

- **AC-7 — Identify after clear uses the existing resolve path; no bypass exists.** Identifying a
  cleared visitor runs the existing `/resolve` waterfall. There is no endpoint or option that
  resolves a visitor whose `do_not_resolve` is still `true` — a held visitor still short-circuits
  with `privacy_opt_out`.
  - proven by: `integration_no_hold_bypass` (integration — resolve on still-held row refuses;
    cleared row reaches waterfall)
  - strategy: Fully-Automated

- **AC-8 — Aggregator stickiness is unchanged.** The aggregator continues to set `do_not_resolve`
  via `BOOL_OR(optout)` + the sticky `OR` upsert. Existing aggregator sticky tests still pass, and a
  new opt-out event arriving after a clear may re-set `do_not_resolve = true` (documented as
  expected).
  - proven by: existing `test_visitor_aggregator` sticky suite stays green +
    `integration_clear_then_reoptout_resticks` (integration)
  - strategy: Fully-Automated

- **AC-9 — The clear is audited.** Each successful clear produces an audit record capturing the
  actor, site, visitor, and timestamp, containing no PII, reusing an existing audit/logging pattern
  rather than inventing a new bespoke table where avoidable.
  - proven by: `clear-hold-audit-record` (unit/integration — asserts audit event fields, no PII)
  - strategy: Fully-Automated

- **AC-10 — Clearing never touches the suppression list.** A clear does not remove any suppression
  entry; if the visitor's email is suppressed, identification still refuses after the hold is
  cleared.
  - proven by: `integration_clear_does_not_unsuppress` (integration — suppressed email still
    blocked post-clear)
  - strategy: Fully-Automated

- **AC-11 — Clear is safe/idempotent on a non-held row.** Clearing a visitor that is already
  `do_not_resolve = false` (or was never held) succeeds as a no-op and raises no error.
  - proven by: `integration_clear_idempotent_noop` (integration)
  - strategy: Fully-Automated

- **AC-12 — The pixel is untouched.** No change to `apps/pixel/src/tracker.js` capture surface or
  size budget; existing pixel regression gates remain green.
  - proven by: existing `test_pixel*` size/capture suite (regression, unchanged)
  - strategy: Fully-Automated

- **AC-13 — Copy communicates the intentional, non-silent, non-un-suppressing nature.** The
  confirmation copy states that clearing is a deliberate owner action scoped to this site and does
  not un-suppress the person. Legal adequacy of the wording is a judgment gate (counsel review),
  not a presence check.
  - proven by: `clear-hold-copy-presence` (web e2e presence/marker check) +
    counsel-review judgment gate (Known-Gap; see `privacy-copy-counsel-review_NOTE_07-08-26.md`)
  - strategy: Agent-Probe

## Out Of Scope

- **Auto-clear (rejected Approach A).** Beam will NOT automatically lift `do_not_resolve` when a
  later event lacks the opt-out flag or when GPC turns off. Sticky stays sticky until a human acts.
- **Identify bypass (rejected Approach B).** No new "force identify" path that resolves a visitor
  while `do_not_resolve` is still `true`. Identification always goes through the existing gate.
- **Dual fields (rejected Approach C).** No new schema that splits GPC-origin vs manual-origin
  opt-out into separate flags. Phase 1 keeps the single sticky flag.
- **Removing suppression-list entries.** This action never edits the suppression list; un-suppression
  remains a separate admin action that (by existing policy) still does not reverse flags.
- **Bulk / site-wide clear.** No "clear all holds" operation — this is a per-visitor, per-site action
  only.
- **Cross-tenant clearing.** Clearing one site's visitor row never touches another site's rows or the
  cross-tenant `beam_identity_graph`.
- **Pixel / tracker changes.** No changes to first-party capture, consent handling, or `tracker.js`.
- **Changing sticky aggregation semantics.** `BOOL_OR` + `OR` upsert behavior is preserved as-is.
- **New audit infrastructure beyond what's needed.** Prefer reusing existing audit/log patterns; a
  new lightweight log surface is in scope only if an existing pattern doesn't fit (PLAN decides).

## Constraints

- **Compliance — no silent reverse.** Clearing must be an intentional, confirmed owner action, aligned
  with the existing `privacy.py` stance that un-suppressing does not reverse already-applied
  `do_not_email` / `do_not_resolve` flags. There is no automatic or implicit un-block.
- **Suppression gate untouched.** The IdentityResolver suppression gate must still refuse a suppressed
  email after a clear; clearing the hold is not clearing suppression.
- **Site-scoped authorization.** Only a site owner/member who can already call resolve for the site may
  clear; unauthorized access returns not-found (404), never 403 (no id-existence leak).
- **Confirmation dialog required.** The UI must gate the clear behind an explicit confirm step.
- **Sticky aggregation preserved.** The aggregator's `BOOL_OR(optout)` + sticky `OR` upsert stays
  exactly as-is; aggregator sticky tests must remain green. After a clear, a later opt-out event may
  legitimately re-set the flag — this is expected and must be documented.
- **Scope limited to API endpoint + web Visitors UI.** Backend clear endpoint + dashboard
  banner/button/copy. Pixel unchanged.
- **Schema-migration-averse.** Prefer NO new migration. Audit may be structlog plus, only if an
  existing audit pattern already exists to reuse (e.g. `request_log` / `api_usage` patterns exist in
  the codebase), a lightweight log row — never a newly-invented bespoke table when a reuse path fits.
- **Copy legal adequacy is a judgment gate.** Presence of the required copy is automatable; whether
  the wording is legally adequate requires qualified counsel review (existing Known-Gap).

## Open Questions

None blocking intent. The approach (Option D) and all behavioral requirements are locked by the
orchestrator's decision record. One non-blocking dependency is tracked as an existing backlog item,
not a new open question: the confirmation/hold copy needs qualified privacy-counsel review for legal
adequacy (owner: privacy counsel; tracked in
`process/features/visitors-identity/backlog/privacy-copy-counsel-review_NOTE_07-08-26.md`). Publishing
clear, honest placeholder copy now is strictly better than the current dead-end state and does not
block PLAN.

## Background / Research Findings

**Why now (user evidence).** A Brave/GPC visitor (`05f5b9bd-…`) turned GPC off but stayed permanently
blocked because `do_not_resolve` is sticky. The site owner had to run a manual SQL `UPDATE` to
un-block them. The user wants an intentional in-product path with clear copy instead.

**Locked decision.** Approach **D** — privacy-hold UX + explicit, confirmed site-owner Clear.
Rejected for phase 1 (backlog only): A (auto-clear), B (Identify bypass), C (dual GPC/manual fields).

**Current behavior confirmed in source (RESEARCH):**

- The sticky flag is set by the aggregator: `apps/api/services/visitor_aggregator.py` uses
  `BOOL_OR(optout) AS do_not_resolve` in the rollup and the sticky upsert
  `"do_not_resolve": text("visitors.do_not_resolve OR EXCLUDED.do_not_resolve")` in both the
  full-recompute and incremental paths. This is the behavior Option D preserves unchanged.
- The skip reason surfaces today via `apps/api/routers/visitors_helpers.py::_resolution_skip_reason`
  (returns `"privacy_opt_out"` first, as a policy block) and `_SKIP_REASON_MESSAGES` copy
  ("This visitor opted out of identification … Policy block — not a usage limit."). The visitor
  detail endpoint (`routers/visitors.py::get_visitor_detail`) attaches
  `resolution_skip_reason` for the UI.
- The per-row and site-wide resolve paths both short-circuit on `do_not_resolve`
  (`routers/visitors.py::resolve_one_visitor` returns `privacy_opt_out`; `resolve_site_visitors`
  and the sweep filter `Visitor.do_not_resolve.is_(False)`). AC-7's "no bypass" requirement means
  these gates stay.
- **Existing precedent for the new endpoint.** `routers/visitors.py::set_internal_override`
  (`POST /{site_id}/{visitor_id}/internal-override`) is a per-visitor, site-scoped human-override
  write using `_verify_site_access` — the same shape the clear endpoint should follow.
- **Auth pattern.** Per-visitor endpoints use `get_current_user` + `_verify_site_access(db, site_id,
  user)`; multi-tenancy convention returns 404 (not 403) for foreign ids.
- **Audit reuse candidates exist:** `apps/api/models/request_log.py` and
  `apps/api/models/api_usage.py`, plus repo-wide `structlog` (never log PII — event keys/ids only,
  per Business Guardrail #3). PLAN should evaluate reuse before any new table.
- **UI location.** `apps/web/src/app/dashboard/visitors/page.tsx` holds the Identify control
  (`resolveMut` → `api.resolveVisitor`) and the `limit_kind`-based outcome handling; the privacy-hold
  banner/button/confirm live here and in the visitor detail surface.
- **Compliance anchor.** `apps/api/routers/privacy.py::delete_suppression` documents the "no silent
  reverse" rule: un-suppressing "already-applied do_not_email / do_not_resolve flags are NOT
  reversed." Option D's clear is the *deliberate, confirmed* exception the owner takes for a single
  row — consistent with that rule because it is explicit, not silent.
