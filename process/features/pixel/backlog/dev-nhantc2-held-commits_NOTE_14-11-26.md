---
name: note:dev-nhantc2-held-commits
description: "Commits from origin/dev_nhantc2 (scale-ready ingest) held back from main, with reasons and what a safe version needs"
date: 14-11-26
feature: pixel
---

# Held commits from `origin/dev_nhantc2` (Nhan To, 18-08-26)

**Bottom line:** only `8ffeb32` (incremental-aggregation watermark bootstrap + Redis mutex) was taken,
via PR branch `feat/aggregation-watermark-bootstrap`. The three items below are held. Each one is a good
idea that needs reworking before it can safely reach production.

## 1. `bbae139` — `event_id` required + unique migration

**Why held**
- The migration backfills `event_id` over the whole `events` table in one statement and then builds a
  unique index without `CONCURRENTLY`. On the production `events` table, both steps take long locks and
  would block ingest writes for the duration.
- Its `down_revision` points at an old head. It no longer chains onto main's single current head.

**What a safe version needs**
- Re-chain onto the current single head (check with `alembic heads`; expect exactly one head).
- Backfill in batches (for example 10k rows per batch, each batch committed on its own). Make it
  resumable and idempotent, run as a separate operator script or a non-transactional migration step.
- `CREATE UNIQUE INDEX CONCURRENTLY` inside an `autocommit_block()`. Add the `NOT NULL` constraint only
  after the backfill is verified (use `NOT VALID` then `VALIDATE`).
- Roll out the ingest-side requirement only after the index exists. Older pixel builds that send no
  `event_id` must still be accepted, or get a server-generated id.
- Live round-trip on a disposable Postgres with a production-sized row count, and record the lock
  duration.

## 2. `73142d1` — server-time `created_at`, Cloudflare peer check, site ceiling becomes a hard 429

Three separate changes in one commit. All three are held.

**a. Server-time `created_at`**
- Why held: the cadence-bot detector (`cadence_bot_flag`) measures the variance between client
  timestamps. Server receive-time collapses batched events onto near-identical stamps, which skews the
  variance and produces false bot flags.
- Safe version: store server time in `created_at` for ordering and retention, but keep a separate
  `client_ts` column. Behavioral consumers (cadence variance, engagement mix, session timing) must keep
  reading `client_ts`. Add tests that pin each consumer to the column it should read.

**b. Cloudflare peer check**
- Why held: the commit checks `request.client` against Cloudflare IP ranges. Behind Railway's proxy,
  `request.client` is Railway's edge, not Cloudflare, so the check rejects or misattributes every request.
- Safe version: run the check on the trusted XFF hop (the last hop as resolved by
  `services/ip_resolution.py` with `trusted_proxy_hops`), not on `request.client`. Keep it behind a flag,
  default OFF, and enable it only after the real hop chain has been observed in production.

**c. Per-site ceiling becomes a hard 429**
- Why held: this reverses the documented ingest-abuse-hardening decision (flag-but-store: flagged
  events are kept and excluded from aggregates, never dropped).
- Safe version: this needs an **owner decision** between flag-but-store and 429. If 429 is chosen, it
  should be a separate flag, and the abuse-hardening context docs should be updated in the same change.

## 3. Alembic DSN guard

Not taken here. It is being reimplemented in a separate PR.
