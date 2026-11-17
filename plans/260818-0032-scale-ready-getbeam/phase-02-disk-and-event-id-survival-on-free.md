---
phase: 2
title: "Disk and event_id survival on Free"
status: pending
priority: P1
effort: M
dependencies: [1]
---

# Phase 2: Disk and event_id survival on Free

## Overview

Mua thời gian trên Free 500 MB (424 MB hôm 17-08) và bịt lỗ idempotency trước x20. **Không** nâng Pro trong phase này. Unique **đổi** thành `(site_id, event_id)` (F1). Thiếu id → **400** (F4).

## Requirements

- Functional: ingest mới **bắt buộc** `event_id` (400 nếu thiếu, F4); unique `(site_id, event_id)` (F1); 682 NULL cũ backfill.
- Non-functional: retention jobs thực sự chạy. Không ingest `rpki_roas`. `migrations/env.py` không trỏ prod khi `APP_ENV=development`.

## Architecture

Ingest: `event_id` required; một event thiếu id → **400 cả batch** (Validation S1). Parser `events.py:198-201`. Insert `ON CONFLICT DO NOTHING` trên `(site_id, event_id)` (F1). `created_at` = server now() (Validation S1).
<!-- Updated: Validation Session 1 - reject whole batch; server now() -->

Backfill: `UPDATE events SET event_id = gen_random_uuid()::text WHERE event_id IS NULL` trong migration additive, offline-validate, apply có backup.

Disk: verify `request_logs` 7d + `events` 90d jobs; **không** anonymous visitor purge ở phase này.

## Related Code Files

- Modify: `apps/api/schemas/events.py` (`event_id` required)
- Modify: `apps/api/routers/events.py` insert + conflict target `(site_id, event_id)` (F1); keep 400 on parse fail (F4)
- Modify: `apps/api/models/event.py` — unique `(site_id, event_id)`; drop/replace `uq_events_event_id`
- Modify: `tests/integration/test_events_ingest.py` (hiện **0** `event_id` — F4)
- Create: Alembic backfill NULL `event_id` + unique composite; head phải là live `b7e3c9a4f215` (verify lúc cook)
- Modify: `apps/api/migrations/env.py` — abort nếu `app_env` in non-prod **hoặc** DSN host ∉ `{localhost,127.0.0.1}` (F10)
- Modify: `apps/api/jobs/scheduler.py` retention `next_run_time` boot offset; log `deleted=0` (F10)
- Tests: thiếu `event_id` → 400; same id khác `site_id` cả hai insert; duplicate cùng site → 204 1 row; cross-tenant replay test (mirror agent-fetch)

## Implementation Steps

1. Confirm live: `event_id` NULL count; `pg_database_size`; request_logs size. (MCP SQL, không đoán)
2. Require `event_id`. AC: 400, 0 row. Cập nhật `test_events_ingest.py` và mọi fixture omit id.
3. Migration: backfill NULL → uuid; unique `(site_id, event_id)`; `ON CONFLICT` cùng constraint. Test replay id sang site khác không nuốt event.
4. F10: retention `next_run_time` sớm + log mỗi run kể `deleted=0`. AC = scheduler last-success, không phụ thuộc `deleted>0`.
5. F10: `env.py` abort mọi non-prod env + DSN không localhost. Backup trước backfill.
6. Operator (không code): pause Supabase project `buildtolaunch` nếu unused. Revoke Data API/anon — **không** bật RLS 56 bảng.
7. Operator deferred: nâng Pro. Ghi runbook 5 dòng trong Phase 3, không làm trong cook Phase 2.
8. Cấm: load `rpki_roas` (0 rows; local dump ~755k).

## Success Criteria

- [ ] Ingest thiếu `event_id` → 400, 0 row
- [ ] Retry cùng `(site_id, event_id)` → 204, không nhân pageview
- [ ] Cùng `event_id` khác `site_id` → cả hai row tồn tại
- [ ] Prod `event_id IS NULL` = 0 sau backfill (đếm live lúc cook, không hardcode 682)
- [ ] Unique `(site_id, event_id)`
- [ ] Retention: log mỗi 24h kể `deleted=0`; `next_run_time` lúc boot
- [ ] `APP_ENV=local|development|test|ci` + prod DSN → alembic abort
- [ ] Disk: không ingest RPKI; `buildtolaunch` paused hoặc ghi rõ lý do giữ

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Backfill uuid khác client uuid → mất idempotency cho retry cũ | Chỉ backfill NULL; retry cũ không có id anyway |
| NOT NULL ngay khi pixel extension cũ | Backfill trước; NOT NULL commit sau khi 24h 0 null inserts |
| Purge events 90d xóa forensic | Giữ 90d; không rút ngắn |

## Security Considerations

Data API: backend dùng `DATABASE_URL`. Revoke anon. Không enable RLS hàng loạt. Không log `event_id` gắn PII.
