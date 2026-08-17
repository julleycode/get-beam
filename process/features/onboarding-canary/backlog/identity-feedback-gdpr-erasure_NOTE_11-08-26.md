---
name: report:identity-feedback-gdpr-erasure
description: NEW PLAN REQUIRED — identity_feedback is outside the graph_erasure GDPR sweep; blocks the location_reveal_enabled flag flip (Phase 5 precondition P-d)
date: 11-08-26
metadata:
  node_type: memory
  type: report
  feature: onboarding-canary
  phase: backlog
---

# `identity_feedback` is outside the GDPR erasure sweep — **NEW PLAN REQUIRED**

**Status:** open · **Severity:** blocks a flag flip, not a deploy · **Raised by:** PVL cycle 1 on
`public-canary-funnel_11-08-26` (contract finding C-7 / supplement-request C-10).

## TL;DR

`apps/api/services/graph_erasure.py` sweeps `BeamIdentityNode`, `IdentitySignal`,
`SuppressionEntry`, `IdentifiedVisitor`, `Visitor`, `VisitorEmail`. It does **not** import or touch
`IdentityFeedback`. That table holds a device `fingerprint` (`String(100)`), rendered city / region /
org, and a rounded lat-lng — written by an **unauthenticated** route. A per-subject erasure request
therefore leaves those rows in place. Age-based retention (added by the parent plan's Phase 2b) is a
different control and does **not** close this.

## Why it is being raised now

The row existed before this plan. What changes is scale and exposure: flipping
`location_reveal_enabled` turns `POST /api/v1/demo/identity-feedback` into a public, logged-out
write path on the marketing funnel. This plan opens the tap; it should not open it onto a table with
no erasure path.

## Facts (verified 11-08-26)

- `apps/api/services/graph_erasure.py` — model import list does not include `IdentityFeedback`.
- `apps/api/models/identity_feedback.py:66` — `fingerprint` is `String(100)`.
- The only reader is `GET /api/v1/onboarding/identity-feedback/stats` (admin-only); it aggregates
  counts and `unnest(reasons)` and never reads `shown`.
- Parent plan Phase 2b adds `purge_identity_feedback_older_than` (90 d retention). Retention ≠ erasure.

## Why this needs its own plan (not a checklist item)

Erasure requires deciding the **subject key**. `graph_erasure` matches on a blind index over email;
`identity_feedback` has no email — it has a device fingerprint. Answering "which rows belong to this
data subject" for a fingerprint-keyed, unauthenticated table is a design question with privacy
consequences (over-deletion vs under-deletion, and whether a fingerprint is even a reliable subject
key). That is a plan, not a one-line extension.

Open questions the new plan must answer:

1. What is the subject key — fingerprint alone, or fingerprint joined through `Visitor`?
2. Does joining through `Visitor` to reach an erasure request re-introduce the cross-tenant class of
   bug commit `7e798ab` had to fix on `/demo`?
3. Should unmatched rows be deleted, anonymised (drop the fingerprint, keep the aggregate), or left?
4. Does the existing erasure API surface need a new input shape to accept a fingerprint?

## Gate impact

This is **Phase 5 precondition P-d** of
`process/features/onboarding-canary/active/public-canary-funnel_11-08-26/public-canary-funnel_PLAN_11-08-26.md`.
The follow-up plan must exist and be owned before `location_reveal_enabled` is flipped in any real
environment. Until then, Phase 5's gate stays **CONDITIONAL** — this is a named residual, never a
PASS.

## Resolution options

- **A —** New plan: fingerprint-keyed erasure for `identity_feedback` (recommended; ~half a day of
  design + a small implementation).
- **B —** Anonymise-on-write: never store the raw fingerprint, store a salted one-way derivative and
  accept that erasure becomes best-effort. Cheaper, but changes what the table can be used for.
- **C —** Accept as known-gap with retention-only coverage and a documented DPA position. Requires an
  explicit human decision — an agent may not choose this.
- **D —** This stub (chosen for now): record the residual, keep the gate CONDITIONAL, block the flip.
