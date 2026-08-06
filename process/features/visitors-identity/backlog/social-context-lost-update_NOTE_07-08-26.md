---
name: note:social-context-lost-update
description: "No row-locking or OCC anywhere in the EnrichmentProfile.social_context call graph — concurrent merge writers can lose each other's keys"
date: 07-08-26
feature: visitors-identity
---

# `social_context` concurrency lost-update — pre-existing known-gap

**TL;DR** — All **nine** writers to `EnrichmentProfile.social_context` do a Python-level
read-modify-write with **no row lock, no `SELECT … FOR UPDATE`, and no optimistic
concurrency control**. Two writers racing in independent sessions can lose the loser's keys.
Pre-existing; `social-context-merge_07-08-26` neither introduced nor worsened it (G4).

## Exposure

Concurrent write paths that can overlap on the same profile row:

- the Celery-beat resolution sweep (`apps/api/tasks/resolution_tasks.py:130-142`)
- API-triggered background jobs (`apps/api/routers/visitors_helpers.py:346` `_run_osint_scan_job`,
  `:437` `_run_social_resolution_job`) — each opens its own `async_session()`
- the enricher paths (`apps/api/services/enricher.py:822-824`, `:878-880`, `:1063-1069`)
- `apps/api/services/social_resolver.py:292-295` (`resolve_social` Stage D)
- `apps/api/routers/visitors.py:1429-1432`, `:1511-1514` (the "scanning" seeds)
- `apps/api/services/social_intelligence.py::store_social_context` (writer #9 — moved from
  "always destroys" to "usually preserves" by `social-context-merge_07-08-26`)

All nine use the safe `dict(profile.social_context or {})` → mutate copy → **reassign** pattern
(required so SQLAlchemy marks the JSONB attribute dirty — `apps/api/models/enrichment.py:59`
has no `MutableDict.as_mutable()`). None has a latent in-place-mutation bug. The gap is purely
cross-session interleaving, not in-process aliasing.

## Why not fixed here

Fixing it is a design change affecting all nine writers uniformly (row lock at read, or a
`jsonb ||` server-side merge — the latter has **zero precedent** in this repo per G1). Out of
scope for a two-line bug fix.

## Resolution options

- **A.** `SELECT … FOR UPDATE` on the `EnrichmentProfile` row before each read-modify-write.
  Simplest; serializes per-profile writes. Needs an audit that no writer holds the lock across
  an external HTTP call (the enricher and social paths do — this is the real obstacle).
- **B.** Server-side `jsonb ||` merge in a single `UPDATE`. Atomic, no lock held over I/O, but
  introduces a new infrastructure pattern (G1 rejected it for the narrow fix).
- **C.** Accept permanently and document. Current state.

## Additional related gap

No automated gate enforces the reassign-not-mutate pattern across the writers. The census was
proven by full source read; a future writer could introduce an in-place `.update()` with nothing
to catch it. A lint rule or a shared helper (`merge_social_context(profile, blob)`) would fix both
this and option B's rollout surface.

## Source

`process/features/visitors-identity/active/social-context-merge_07-08-26/social-context-merge_PLAN_07-08-26.md`
— G4, Backlog Follow-Up #2, Validate Contract open gaps.
