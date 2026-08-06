---
name: note:social-context-wholesale-overwrite-bug
description: "Pre-existing bug — social_intelligence.store_social_context() wholesale-overwrites EnrichmentProfile.social_context, destroying sibling keys written earlier in the same resolution pass"
date: 07-08-26
feature: visitors-identity
metadata:
  node_type: memory
  type: note
  status: open
  severity: HIGH
  source: VALIDATE CONCERN-2 of github-reader_PLAN_07-08-26
---

# `store_social_context()` wholesale-overwrites `social_context` (pre-existing, HIGH)

**TL;DR** — `apps/api/services/social_intelligence.py::store_social_context` assigns
`enrichment_profile.social_context = context` outright instead of merging. Every other writer
of that column merges. In the primary Celery-beat resolution sweep it fires in the *same loop
iteration*, moments after enrichment has just written its own sub-keys — silently deleting
them. Recommended fix: convert it to the same read-modify-write pattern used everywhere else.

## The bug

`apps/api/services/social_intelligence.py:100`:

```python
enrichment_profile.social_context = context   # bare overwrite — no merge
```

Contrast every other writer of the same column, all of which merge:

| Call site | Pattern |
|---|---|
| `apps/api/services/social_resolver.py:292-295` | read-modify-write ✅ |
| `apps/api/services/enricher.py` `_fetch_and_store_content` | read-modify-write ✅ |
| `apps/api/services/enricher.py` `_fetch_and_store_github` (new, 07-08-26) | read-modify-write ✅ |
| `apps/api/services/enricher.py` deep_research call site | read-modify-write ✅ |
| `apps/api/routers/visitors_helpers.py:383, :427` | read-modify-write ✅ |
| **`apps/api/services/social_intelligence.py:100`** | **wholesale overwrite ❌** |

This is already implicitly acknowledged in-tree — `apps/api/routers/visitors_helpers.py:338`
carries the comment "social_context is otherwise overwritten wholesale elsewhere". *This* is
the "elsewhere".

## Why it actually bites (same-pass data loss)

`apps/api/tasks/resolution_tasks.py` (the Celery-beat resolution sweep):

- line ~130 — `enricher.enrich_tier1(visitor, identified)`, which internally runs
  `_fetch_and_store_content` and (as of 07-08-26) `_fetch_and_store_github`, both writing
  merged sub-keys into `social_context`.
- lines ~135-142 — for the **same** high-intent visitor (`intent_score >= 60`), conditionally
  calls `social_intel.store_social_context()` when Twitter/posts content was found.

When that second branch fires, everything the first step just wrote is destroyed: `github`,
`youtube`, `reddit`, `company_content`, `osint_scan`, `social_resolution`, `deep_research`.

## Recommended fix (own plan — do NOT bundle)

1. Convert `store_social_context()` to read-modify-write:
   ```python
   merged = dict(enrichment_profile.social_context or {})
   merged.update(context)
   enrichment_profile.social_context = merged
   ```
2. **Verify the auto-draft read path is unaffected** — `resolution_tasks.py:144-149` reads
   `social_context` right after the overwrite today, so it currently sees *only* the Twitter
   keys. After a merge fix it will additionally see enrichment keys. Confirm the draft
   generator tolerates (or benefits from) the extra keys before shipping.
3. Add a regression test asserting a pre-existing sibling key survives a
   `store_social_context()` call.

## Why it was NOT fixed in the github-reader plan

Different service, larger blast radius (the auto-draft read path above), and it affects
pre-existing keys equally — not a regression introduced by that plan. Scoped out explicitly;
the github-reader plan only *documents* the exposure (G9 / checklist item 16), via code
comments in `apps/api/services/github_reader.py` (module docstring) and
`apps/api/services/enricher.py::_fetch_and_store_github`.

## Evidence trail

- `apps/api/services/social_intelligence.py:100`
- `apps/api/tasks/resolution_tasks.py:130-149`
- `apps/api/routers/visitors_helpers.py:338`
- VALIDATE CONCERN-2 in
  `process/features/visitors-identity/active/github-reader_07-08-26/github-reader_PLAN_07-08-26.md`
