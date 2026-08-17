---
phase: 1
title: "Incremental aggregation soak and prod flag"
status: in-progress
priority: P1
effort: M
dependencies: []
---

# Phase 1: Incremental aggregation soak and prod flag

## Overview

Biến aggregation incremental từ "code chết" thành "chạy production". Không viết lại SQL. Sửa **bootstrap watermark** rồi soak, rồi flip Railway flag.

Context: `plans/reports/research-260817-2335-production-architecture-verdict.md` §3 P0, §6 item 3.

## Requirements

- Functional: ingest sau soak chỉ merge events mới hơn watermark + 30 phút lookback. Sweep hourly vẫn full SET (repair + `avg_time_on_page` / `intent_score`).
- Non-functional: first ingest sau flag ON không full-scan mãi. Rollback = `AGGREGATION_INCREMENTAL_ENABLED=false`.

## Architecture

```
BEFORE prod flag: sequential job full+stamp mọi site có events (F9)
ingest 204 → Redis mutex (hold until finally, not 60s cooldown) (F8)
  Redis None + flag ON → SKIP agg (F7)
  else incremental since=watermark
sweep → always since=None → MUST NOT stamp (F6)
created_at window = server `now()` always (Validation S1; F2)
```

Stamp **chỉ** `_background_aggregate` (`events.py`). Không sửa `aggregation_tasks.py` (Celery không chạy). Không stamp trong aggregator khi `since=None`.

## Related Code Files

- Modify: `apps/api/routers/events.py` (`_background_aggregate` ~906-952) — **only** live stamp caller (F6); Redis skip (F7); mutex (F8)
- Modify: `apps/api/services/aggregation_debounce.py` — lock until `release` in `finally`; sweep shares same lock
- Modify: `apps/api/jobs/scheduler.py` `_sweep_one_site` — cùng mutex; **không** stamp
- Modify: `apps/api/routers/events.py` ingest insert — `created_at = datetime.utcnow()` (Validation S1). `event.ts` không ghi cửa sổ agg.
<!-- Updated: Validation Session 1 - server now() only -->
- Do not modify: `apps/api/tasks/aggregation_tasks.py`
- Create: `tests/integration/test_aggregation_watermark_bootstrap.py`
- Create: unit ingest fail-open skip khi Redis None + flag ON
- Create: soak/synthetic: full recompute duration > 2× old TTL, no double-count
- Keep: `test_incremental_run_stamps_the_watermark` (full must not stamp inside aggregator)
- Keep: test `_sweep_one_site` never calls `_advance_watermark`

## Implementation Steps

1. Re-run existing gates (không đổi hành vi flag OFF):
   - `pytest tests/integration/test_visitor_aggregation_incremental.py tests/integration/test_aggregation_debounce.py tests/unit/test_aggregation_sweep_failopen.py tests/unit/test_aggregation_sweep_full_recompute.py -q`
2. F2: ingest ghi `created_at` từ server `now()` **luôn**. Không clamp, không `event.ts`. Test: `ts` = now+1 năm không inflate `total_pageviews` lần incremental 2.
<!-- Updated: Validation Session 1 - server now() only -->
3. F8: debounce = mutex (extend TTL / lock token + `release` `finally`). Sweep cùng key. Không dùng cooldown 60s làm khóa full run.
4. F7: `acquired is None` + flag ON → ingest **skip** agg (log), giống sweep. Test mới.
5. F6: stamp chỉ sau full bootstrap trong `_background_aggregate`. Sweep `since=None` không stamp. Không đụng Celery task file.
6. F9: job sequential: với mọi `site_id` có events và `last_aggregated_at IS NULL`, full + stamp. **Cấm** flip Railway flag khi còn NULL.
7. Soak: 1 site canary **và** synthetic full > 2× TTL cũ. Không dùng 3.3k/ngày làm chứng x20.
8. Operator: `AGGREGATION_INCREMENTAL_ENABLED=true` chỉ sau F9 xanh. Default `config.py` vẫn `False`.
9. Rollback: flag false. Full SET tự heal.

## Success Criteria

- [x] Flag OFF parity (tests pass)
- [ ] Flag ON + NULL watermark F9 stamp hết site **trước flip** — operator leftover (code exists; not run on prod)
- [x] Sweep không stamp (integration proven)
- [x] Redis degraded + flag ON skip (unit proven)
- [x] Mutex > 60s synthetic (integration proven)
- [x] Future event.ts không ADD lặp (integration proven after UA fix)
- [ ] Prod soak canary
- [x] Default config.py False

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Stamp sớm → miss events mid-run | Stamp = clock trước read, window nửa-mở `created_at > wm` |
| 25 site full cùng lúc lúc flip | Sequential sweep sẵn; bootstrap per-ingest; debounce 60s |
| `intent_score` stale đến 60 phút | Đúng D7; sweep interval giữ 60 |

## Security Considerations

Không đổi auth. Aggregation vẫn tenant `site_id`. Không log PII trong `visitors_aggregated`.
