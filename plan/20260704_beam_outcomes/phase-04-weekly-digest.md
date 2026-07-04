# Phase 04 — Email tuần + widget Overview

**Status:** ✅ SHIPPED 2026-07-04 — **email GATED sau flag `OUTCOMES_DIGEST_ENABLED` (default OFF)**; bật ở Railway để chạy thứ 2 hàng tuần 15:00 UTC
**Migration:** `d8f1c5a3b9e7_add_last_outcome_digest_sent_at.py` (chain `c4f8b2d6a9e1`)
**Verify:** 3 unit (build email + escape) + 2 integration (send+stamp+throttle, fail→rollback không stamp); regression full suite outcomes 94 pass; tsc+build sạch.

- Config: `outcomes_digest_enabled` default **OFF** (config.py:96, pattern connection_nudge).
- Scheduler: APScheduler CronTrigger thứ 2 hàng tuần (scheduler.py:93-104 pattern), job thin gọi service.
- Service `outcome_digest.py`: trigger-agnostic + advisory lock (copy retention.py:55-75); throttle 6 ngày qua cột mới; skip site 0 hoạt động; gửi qua `EmailSender().send(..., db=db)` (suppression tôn trọng); `build_digest_email` pure + html.escape.
- Nội dung: "Beam this week: X emails sent, Y clicks, Z conversions ($R attributed)" + link /dashboard/outcomes.
- Overview: `GET /overview` thêm `conversions_30d` + `attributed_revenue_cents_30d`; StatTile trên dashboard/page.tsx.
- Tests: unit build_digest_email/escape/skip-gate; integration monkeypatch EmailSender.send → 1 send, throttle chạy 2 → 0.
