# Plan — Beam Outcomes: Conversion Attribution

**Ngày:** 2026-07-04
**Trạng thái tổng:** ✅ P1→P4 SHIPPED TRỌN BỘ (2026-07-04). Email tuần gated `OUTCOMES_DIGEST_ENABLED` default OFF — bật ở Railway khi muốn chạy.

## Vấn đề

Beam track được gửi → mở → click → quay lại site, nhưng không chứng minh được outcome cuối: bao nhiêu signup/đơn hàng/doanh thu do Beam đem về. Người mua làm growth cần con số này để báo cáo. Không có số = không giữ được khách trả tiền.

## Mục tiêu

Khách định nghĩa "conversion goal" (ví dụ: khách của họ vào trang `/thank-you`), Beam ghi nhận conversion qua pixel sẵn có, gắn (attribute) về đúng campaign theo lượt click, và luôn show outcome trên dashboard: "Beam drove X conversions ($Y)".

## Nguyên tắc

- Số liệu trung thực: chỉ attribute theo **click** (không theo open — Apple MPP thổi phồng open). Conversion không có click vẫn ghi nhận là `organic` làm baseline.
- Không làm chậm ingest: mọi xử lý conversion best-effort, bọc try/except, ingest luôn trả 204.
- No-code cho khách: goal theo URL chạy ngay vì pixel đã cài sẵn. JS API + webhook (P3) cho ai muốn gắn doanh thu.

## 4 phase

| Phase | Mục tiêu 1 dòng | Migration? | Effort | ROI | Status |
|---|---|---|---|---|---|
| **P1** — Nền tảng | Bảng goals + conversions + campaign_clicks (vá click↔visitor), match goal theo URL trong ingest | Có (`b7e3a9c4d1f6`) | TB | Rất cao | ✅ |
| **P2** — Báo cáo | Trang Outcomes + funnel sent→open→click→convert trên campaign | Không | TB | Rất cao | ✅ |
| **P3** — Doanh thu | `beamConvert()` JS API + webhook HMAC (Stripe/Zapier gửi conversion kèm $) | Có (`c4f8b2d6a9e1`) | TB | Cao | ✅ |
| **P4** — Chứng minh định kỳ | Email tuần "Beam tuần này đem về X, $Y" + widget Overview | Có (`d8f1c5a3b9e7`) | Nhỏ | Cao | ✅ (email gated OFF) |

## Mấu chốt kỹ thuật

Link email đã gắn `_tp=<touchpoint uuid>`; ingest hiện chỉ stamp `clicked_at`, KHÔNG lưu visitor_id của browser đáp xuống. P1 thêm bảng `campaign_clicks` ghi (touchpoint ↔ landing visitor) ngay lúc click — không có nó thì không attribute được conversion cross-device.

Attribution = last-click trong 30 ngày; fallback same-browser (touchpoint.visitor_id = visitor convert, có clicked_at). Dedupe bằng `dedupe_key` UNIQUE.

## Thứ tự làm

1. P1 backend (model → service → ingest hooks → CRUD → tests → migration cuối) → verify → commit
2. P2 API + UI → tsc/build/lint → commit
3. P3/P4 đợt sau (đã thiết kế chi tiết trong phase files)

## Rủi ro chung

- Alembic multi-head (dính 4 lần): `alembic heads` trước mỗi migration, 1 migration/phase. Head lúc plan = `f3d9b1c7a2e4`.
- Naive UTC: mọi datetime mới `.replace(tzinfo=None)`.
- Ingest hot path: goal match chỉ chạy khi có pageview; 1 query indexed/batch.
- Shared dirty tree + auto-commit watcher: stage surgical từng file, không stash/hard-reset.

## Cách chạy / test

- Backend: `PYTHONPATH=. .venv/bin/python -m pytest tests/... -v -m integration` (cần docker postgres+redis; Docker Desktop hay crash — check trước)
- Migration: `.venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head`
- Frontend: `cd apps/web && npx tsc --noEmit && npm run build && npm run lint`
