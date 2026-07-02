# Phase 3 — Ghi nhận open + click

**Trạng thái:** ✅ Xong (2026-07-02)

## Mục tiêu

Ghi `opened_at` (pixel 1x1 trong email) và `clicked_at` (nối vào redirect click có sẵn) vào bảng `campaign_touchpoints`. Cột đã có sẵn, chỉ thiếu người ghi.

## 3a. Open tracking — pixel 1x1

**Files:** `apps/api/routers/click.py` (hoặc router mới `open.py`), `apps/api/services/campaign_sender.py`

- Endpoint mới: `GET /o/{touchpoint_id}` — trả GIF 1x1 trong suốt, header `Cache-Control: no-store`.
  - `touchpoint_id` = UUID của CampaignTouchpoint (random, không lộ PII).
  - Tìm touchpoint → nếu `opened_at` null thì set now. Sai/không tồn tại → vẫn trả GIF 200 (không lộ thông tin dò ID).
- `campaign_sender.py`: sau khi tạo touchpoint row (cần flush lấy id TRƯỚC khi gửi — đổi thứ tự: tạo row status="pending" → gửi → update status="sent"), chèn `<img src="{API_URL}/o/{tp.id}" width="1" height="1" alt="">` vào cuối body_html.
- Lưu ý thật: Apple Mail proxy tự tải pixel → open bị đếm dư. Chấp nhận, ghi chú trên UI (Phase 4).

## 3b. Click tracking — nối vào redirect có sẵn

**Files:** `apps/api/services/link_decorator.py`, `apps/api/routers/click.py`, `apps/api/services/campaign_sender.py`

- `decorate_links()` thêm tham số `touchpoint_id`, gắn thêm `&tp={touchpoint_id}` cạnh `_bid` trong link redirect.
- `click.py` GET `/c/{site_id}`: đọc `tp` param → nếu hợp lệ set `clicked_at` (nếu null). Click cũng chứng minh đã mở → set luôn `opened_at` nếu null.
- Logic cookie + VisitorEmail giữ nguyên (đang chạy tốt).

## Migration

Không cần — cột `opened_at`, `clicked_at` đã tồn tại.

## Verify

- Mock send → body có pixel + link có `tp=`.
- GET `/o/{id}` → GIF trả về, `opened_at` set, gọi lần 2 không đổi timestamp.
- Click redirect với `tp=` → `clicked_at` + `opened_at` set, vẫn redirect đúng đích, cookie vẫn set.
- ID bậy → vẫn 200 GIF / vẫn redirect, không 500.
- `pytest` cho cả 2 đường.
