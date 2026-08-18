---
title: Plan scale-ready getBeam x20-x30 sau red-team
date: 2026-08-18 00:45
severity: medium
component: aggregation, ingest, railway, supabase
status: Phase 1 cook landed 01:36 — flag still OFF; Pro deferred
---

## Context

User muốn plan tối ưu kiến trúc cho x20–x30, nâng Supabase sau.

## What happened

**At 00:45 (pre-cook):** code incremental đã có, flag OFF. Red-team phát hiện flag ON là no-op (watermark không stamp), debounce 60s không khóa full run, `created_at` = client `ts`, unique `event_id` global, trần site flag-but-store.

User accept 10 finding. Plan cập nhật. Pro vẫn deferred.

**Cook 01:36:** F2/F6/F7/F8/F9 landed in code. Debounce is a mutex held until `finally` (not fire-and-forget 60s); `created_at` is server `utcnow()`; ingest stamps watermark after full `since=None`; sweep still does not stamp; `run_aggregation_watermark_bootstrap()` is operator-invoked, not in `start_scheduler`. Flag default still **False** — Railway flip is not done. See [260818-0136-phase-01-incremental-aggregation.md](./260818-0136-phase-01-incremental-aggregation.md).

## Decision

Không migrate DB. Không Queue. Không ClickHouse. Phase 1 cooked; Pro still deferred.
