---
name: note:social-context-no-purge-path
description: "EnrichmentProfile.social_context holds scraped PII with NO purge or erasure path anywhere — unaccounted for by the erasure program"
date: 07-08-26
feature: visitors-identity
---

# `social_context` has NO purge/erasure path — NEW PLAN REQUIRED

**TL;DR** — `EnrichmentProfile.social_context` stores scraped post content, OSINT account
findings, and derived topics. **Nothing in the codebase ever deletes or redacts it** — not
retention, not any GDPR/erasure route. This surface appears unaccounted for in the active
erasure program.

## 🚩 FLAG TO THE OWNER OF `graph-erasure-compliance_07-08-26/`

`process/features/visitors-identity/active/graph-erasure-compliance_07-08-26/` contains **zero**
references to `social_context` or `EnrichmentProfile`. Its SPEC and PLAN scope
`beam_identity_graph` cross-tenant rows and the per-visitor erasure route
(`apps/api/routers/visitors.py:403-439`). This column is a second, independent PII residency
surface with the same erasure obligation. **Please fold it into that program's scope or
explicitly declare it out of scope with a reason.**

## Evidence

- `apps/api/services/retention.py` purges only `events`, `agent_fetch_events`, `request_logs`.
  `EnrichmentProfile` is never touched.
- `do_not_resolve` gates whether enrichment *runs*; it does nothing to already-written
  `social_context`.
- No erasure/GDPR path anywhere writes, nulls, or redacts the column.
- Content is genuinely personal: `recent_posts` (verbatim scraped post text + URLs + author
  handles), `osint_scan.accounts` (site registrations found for the person's email),
  `deep_research` summaries, `youtube`/`reddit`/`company_content` scrape blobs.

## Made slightly worse by `social-context-merge_07-08-26`

That plan changed `store_social_context` from wholesale overwrite to merge. Written blobs are now
strict **supersets** of what the old code left behind — previously, a high-intent visitor's
`social_context` was periodically flattened to just the social-intelligence keys, incidentally
discarding older scraped content. That accidental pruning is gone. The security-surface CONCERN
accepted in that plan's validate contract rests on this note existing.

## Resolution sketch

1. Decide the owner: extend `graph-erasure-compliance_07-08-26/` or open a new plan.
2. Add `EnrichmentProfile.social_context` (and likely the whole row) to the per-visitor erasure
   path at `apps/api/routers/visitors.py:403-439`.
3. Decide a retention policy — the raw-events 90-day auto-purge has no analogue here.
4. Integration gate: erase a visitor, assert `social_context` is NULL / the profile row is gone.

## Source

`process/features/visitors-identity/active/social-context-merge_07-08-26/social-context-merge_PLAN_07-08-26.md`
— Backlog Follow-Up #4, Validate Contract Security-surface CONCERN.
