---
name: note:aggregation-multi-container-concurrency
description: "Known-gap: the Phase 3 Redis debounce + sweep yield-marker protocol is proven in one process only, never across N containers"
date: 25-07-26
---

# Aggregation multi-container concurrency — known-gap

**Status:** OPEN. Created at Phase 3 closeout (capacity-hardening plan, W1).

## What is unproven

Phase 3 replaced the per-process in-memory `_aggregating` set with three Redis keys
(`apps/api/services/aggregation_debounce.py`):

- `agg:debounce:{site_id}` — per-site run lock / min-interval debounce (D3)
- `agg:sweep_pending:{site_id}` — the repair sweep's yield marker (E16)
- `agg:resolve:{site_id}` — single-flight for dispatched company resolution

All three are shared across containers *by construction*. But every automated gate that
exercises them (`tests/integration/test_aggregation_debounce.py`,
`tests/integration/test_aggregation_sweep_priority.py`) runs inside **one pytest process**
against a real Redis. One process is not a deploy.

Specifically unproven:

1. **N-container debounce coalescing.** With N API containers each running their own
   `_background_aggregate`, exactly one should win `SET NX` per interval. Proven for
   two coroutines; not proven for two processes on separate hosts with clock skew.
2. **The yield-marker handshake under real contention.** E16's four-part protocol assumes
   that once `agg:sweep_pending:{site_id}` is set, *no new* per-ingest run takes the
   debounce key — so the key frees within one TTL. A container that read the marker as
   absent microseconds before it was set can still take the key, delaying the sweep by one
   more TTL. Bounded, not eliminated; unobserved in production.
3. **Sweep pile-up across containers.** Every container registers its own
   `aggregation_sweep` APScheduler job. The `next_run_time` boot offset (E18) plus Phase 4c
   `jitter` are supposed to spread them; with jitter not yet landed (Phase 4c), N containers
   booting together will attempt the sweep within ~seconds of one another and rely purely on
   the debounce key for mutual exclusion.
4. **Redis partial degradation.** `AC-V7` proves the flag-conditional fail direction when
   Redis *raises immediately*. A slow-but-alive Redis is a different failure and is not
   covered.

## Why it cannot be closed here

Requires 2+ live containers under real ingest load. No test lane in this repo runs more
than one API process.

## How it gets closed

- The plan's AC3 Agent-Probe: 24h single-site flag-ON soak after deploy. Observe
  `aggregation_debounced` / `aggregation_yielded_to_sweep` / `aggregation_sweep_deferred`
  counts and confirm exactly one `visitors_aggregated` per site per interval.
- Confirm `avg_time_on_page` / `intent_score` freshness stays inside
  `aggregation_sweep_interval_minutes` on the busiest site (the starvation case E16 exists
  for).
- Land Phase 4c jitter before enabling `aggregation_incremental_enabled` in a
  multi-container environment.

Until then Phase 3 stays **CONDITIONAL**, never `VERIFIED`.
