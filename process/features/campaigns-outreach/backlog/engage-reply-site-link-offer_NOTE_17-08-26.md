---
name: note:engage-reply-site-link-offer
description: "AC-4 real-path residual — offering the site link as human-approved candidate material at drafting time; NEW PLAN REQUIRED, no home phase. Includes the multi-site manual-draft NULL sub-case."
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: memory
  type: report
  feature: campaigns-outreach
  phase: phase-1
---

# AC-4 real-path residual — replies rarely contain a site-owned link

**Status:** open known-gap. `known-gap: documented as NEW PLAN REQUIRED` — **no home phase.**
**Origin:** engage-learning-agent Phase 1 (D-O2), recorded at EXECUTE 17-08-26.

## The gap in one sentence

Phase 1 mints the attribution tag server-side **only when the human-approved reply
already contains a site-owned link** — and generated replies essentially never do,
so in production the mint path will rarely fire.

## Why Phase 1 did not just fix it

`apps/api/services/ai_reply.py` never passes `Site.url` into the generation prompt,
so the model has no site link to include. The obvious "fix" — appending the link at
send time — was explicitly rejected:

> **A link is NEVER appended to human-approved content.** Appending would post
> something the human never read and never approved. That is a send-authorization
> change wearing an attribution costume, and this phase adds no new
> send-authorization path.

The correct fix therefore lives at DRAFTING time, not send time: offer the site link
as *candidate material* the human can accept or edit before approving. That is a
product/UX change with its own consent story, which is why it needs its own plan
rather than a Phase 1 checklist item.

## What IS proven today

- `test_send_path_mints_attribution_tag_server_side` — link-present path mints, tag
  lands in the posted content, `EngagementAttribution` row exists.
- `test_roi_nonzero_after_tagged_visit` — a tagged visit driven through the REAL
  ingest path yields non-zero `/engagement/roi` AND an `attributed_visit` outcome row.
- Boundary gates: no-link (byte-identical content), foreign host (no rewrite), at-cap
  (original posted, `skipped_length`), NULL site (fail-closed).

The wiring is proven. **Production VOLUME is not** — the mint rarely fires on the
real path. The SPEC's unqualified non-zero-ROI claim is demoted to this residual.

## Sub-case: multi-site manual draft never mints at all

`apps/api/routers/drafts.py` constructs drafts with **no `visitor_id`**, so site
derivation can only reach precedence step 2 ("the user owns exactly one site"). A
multi-site user's manual draft therefore resolves to `site_id = NULL` → A1c
fail-closed → no attribution mint on that path, ever.

This is stated deliberately, not discovered. It is the **safe** direction: the
alternative is attributing a draft to the wrong tenant's site. Covered by
`test_draft_site_id_derivation` (5 cases, both producers) and
`test_null_site_id_skips_attribution_mint`.

Note for Phase 3a (K6): `ix_engage_outcomes_site_strategy_created` leads on
`site_id`, which may be largely NULL on the manual-draft path — re-check that
index's selectivity once real data exists.

## What a future plan needs to decide

1. Whether drafting offers the site link as candidate material, behind its own flag,
   with human approval preserved (the human must still see and approve the final text).
2. Whether the multi-site manual path gets an explicit site PICKER rather than
   silently resolving to NULL. This is the higher-leverage half: it converts a
   permanently-unmintable path into a mintable one without touching send authorization.
3. Whether `attributed_visit` needs a run-twice dedupe gate — the current coverage
   proves dedupe for `reply_received` and `metrics_snapshot` but **not** for
   `attributed_visit`, so a duplicate visit reference is unverified.

Until a plan lands, AC-4 stays scoped to the link-present path and the phase gate
stays CONDITIONAL on this residual.
