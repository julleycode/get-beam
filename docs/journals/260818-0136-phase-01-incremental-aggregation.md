---
title: Cook Phase 1 — incremental aggregation hết dead code
date: 2026-08-18 01:36
severity: high
component: visitor_aggregator, ingest _background_aggregate, scheduler bootstrap, Redis mutex
status: code-complete — flag OFF; chưa prod soak
---

# Cook Phase 1 scale-ready GetBeam: incremental aggregation

**Date**: 2026-08-18 01:36
**Severity**: High
**Component**: aggregation / ingest / scheduler
**Status**: Resolved in code; blocked on operator bootstrap + flag

## What Happened

Phase 1 cook của `plans/260818-0032-scale-ready-getbeam`. Incremental path đã nằm trong repo nhưng **dead**: full recompute không stamp `sites.last_aggregated_at`, nên `since` luôn `None` và mọi lần chạy vẫn full. Flag ON sẽ là no-op.

Cook đóng 5 finding đã accept:

| ID | Fix |
|----|-----|
| F2 | `events.created_at` = server `utcnow`, không còn ghi `event.ts` client |
| F6 | `_background_aggregate` gọi `advance_watermark` **sau** full (`since=None`); clock `SELECT now()` trước read. Sweep vẫn không stamp |
| F7 | Redis down + `AGGREGATION_INCREMENTAL_ENABLED=true` → ingest skip agg (không fail-open additive) |
| F8 | `aggregation_debounce.RunLock` giữ mutex tới `finally`, không còn cooldown NX 60s giả mutex |
| F9 | `scheduler.run_aggregation_watermark_bootstrap` — sequential full+stamp site có events và watermark NULL. **Không** đăng ký `start_scheduler` (job-count AST gate). Không flip flag |

## The Brutal Truth

Ta ship incremental rồi tự tin flag-off "sẵn sàng flip". Red-team chỉ ra stamp không bao giờ chạy — cả comment ingest còn nói dối. Debounce 60s không khóa full run. Flip Railway lúc đó là double-count hoặc full-recompute forever trên pool 5. Painful vì bug nằm đúng chỗ plan gọi là "đã có sẵn".

## Technical Details

- Tester lần 1: unit 31/31; integration **26/27**. `TestFutureEventTs` POST thiếu header `User-Agent` → `is_bot("")` True (`bot_filter.py`) → ingest 204 drop, `NoResultFound` trên `evt-future-ts-1`.
- Fix fixture: `"User-Agent": _BROWSER_UA`. Production bot logic không đổi. Integration **27/27**.
- Review: **PASS_WITH_WARNINGS**. F9 cố ý ngoài scheduler; **không flip Railway** cho đến khi mọi site có events đã stamp watermark.

## Root Cause

Stamp chỉ sống trong nhánh incremental (`since is not None`). Full bootstrap — đúng lúc watermark NULL — không gọi `advance_watermark`. Caller ingest comment claim stamp; aggregator không làm. Celery `aggregation_tasks.py` không phải live cadence.

## Lessons Learned

Full path phải stamp **một lần** khi watermark NULL, hoặc có job operator sequential trước flag ON. HTTP ingest tests phải gửi `User-Agent` — body field không qua `is_bot`. Mutex = hold-until-finally, không phải SET NX EX 60s.

## Next Steps

1. Operator: `asyncio.run(run_aggregation_watermark_bootstrap())` trên prod/staging đến khi mọi site có events có `last_aggregated_at`.
2. **Không** set Railway `AGGREGATION_INCREMENTAL_ENABLED=true` trước bước 1.
3. Prod soak canary. Phase 2/3 chưa cook.
4. Flag default vẫn `False`.
