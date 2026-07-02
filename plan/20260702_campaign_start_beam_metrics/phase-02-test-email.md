# Phase 2 — Gửi email test tới admin

**Trạng thái:** ✅ Xong (2026-07-02)

## Mục tiêu

Trước khi Start beam, admin nhập tay email của mình → nhận bản thử của email campaign → xem ổn rồi mới gửi thật.

## Backend

**File:** `apps/api/routers/campaigns.py` (+ schema mới trong `apps/api/schemas/`)

- Endpoint mới: `POST /{site_id}/{campaign_id}/test-send`
- Body: `{ "email": "admin@example.com" }` — validate format bằng Pydantic `EmailStr`.
- Logic:
  1. Cho phép ở MỌI trạng thái trừ khi campaign không có touchpoint email (400).
  2. Lấy touchpoint email đầu tiên từ `campaign.plan`, personalize bằng dữ liệu mẫu (`_personalize` với name giả "Alex Example" — không dùng PII thật).
  3. Subject prefix `[TEST] `.
  4. Gửi qua `EmailSender.send()` — vẫn qua suppression check + unsubscribe footer (giống email thật để xem đúng bản sẽ gửi).
  5. **Không** ghi CampaignTouchpoint, **không** đụng trạng thái campaign.
  6. Chống lạm dụng: đếm vào hourly cap site (`check_and_reserve_email`) — tránh biến test-send thành máy spam.
- Response: `{ "sent": true, "to": "a***@example.com" }` (mask email trong log).

## Frontend

**Files:** `apps/web/src/lib/api.ts`, `apps/web/src/app/dashboard/campaigns/page.tsx` (hoặc trang chi tiết)

- Nút phụ **"Send test"** trên row campaign email (mọi trạng thái) → dialog: input email + nút gửi.
- Nhớ email test lần trước bằng `localStorage` (`beam_test_email`) cho tiện.
- Toast kết quả thành công/lỗi.

## Verify

- Nhập email hợp lệ → nhận email có `[TEST]` prefix (mock mode: log ra).
- Email sai format → báo lỗi ngay trên form.
- Test-send không đổi status campaign, không tạo touchpoint.
- `pytest` cho endpoint mới.
