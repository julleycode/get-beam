---
name: note:enricher-updated-at-conflation
description: "enricher.py stamps social_context_updated_at at TWO non-deep-research sites, inflating the deep-research daily meter"
date: 07-08-26
feature: visitors-identity
---

# `enricher.py` `social_context_updated_at` conflation — TWO sites

**TL;DR** — Same bug class as BUG-2 of `social-context-merge_07-08-26`, twice over, in
`apps/api/services/enricher.py`. Both were explicitly OUT OF SCOPE (G3) of that plan.

## The defect

`apps/api/services/usage_limits.py:104-113` (`get_enrich_usage`) counts `EnrichmentProfile`
rows whose `social_context_updated_at >= today` to enforce the **deep-research 3/day**
budget. Two non-deep-research writers stamp that column, so each consumes a deep-research
quota slot the user never used:

| Site | Function | Path |
|---|---|---|
| `apps/api/services/enricher.py:825` | `_fetch_and_store_content` | content-reader |
| `apps/api/services/enricher.py:881` | `_fetch_and_store_github` | github-reader |

`apps/api/services/enricher.py:1070` (`deep_research`) is a **legitimate** stamp and must stay.
`apps/api/services/social_intelligence.py` was the fourth writer; its stamp was deleted by
`social-context-merge_07-08-26`.

Correct precedent for the fix: `apps/api/routers/visitors_helpers.py:349-353` — an explicit
docstring stating the job deliberately does not touch the column because it drives the meter.

## Why it was deferred

Fixing `:825` requires updating `tests/unit/test_content_enrich.py:151`, which currently
**asserts** that stamp is set. That is a deliberate, separate test change — not something to
fold into an unrelated plan.

## Resolution sketch

1. Delete the `social_context_updated_at` write at `enricher.py:825` and `enricher.py:881`.
2. Add the `visitors_helpers.py:349-353`-style comment at both sites.
3. Update `tests/unit/test_content_enrich.py:151` to assert the column is NOT stamped by the
   content-reader path (invert the assertion).
4. Leave `enricher.py:1070` untouched.
5. Gate: `.venv/bin/python3.11 -m pytest tests/unit -m unit -q`.

## Source

`process/features/visitors-identity/active/social-context-merge_07-08-26/social-context-merge_PLAN_07-08-26.md`
— G3, Non-Goals, Backlog Follow-Up #1.
