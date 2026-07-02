# Phase 1 — 1 nút "Start beam"

**Trạng thái:** ✅ Xong (2026-07-02)

## Mục tiêu

Gộp Approve + Start + Send emails thành 1 nút **"Start beam"**. Bấm → dialog xác nhận → backend tự chạy: approve (nếu draft) → activate → gửi email.

## Backend

**File:** `apps/api/routers/campaigns.py`

- Endpoint mới: `POST /{site_id}/{campaign_id}/start`
- Logic:
  1. Nhận campaign ở trạng thái `draft`, `approved`, hoặc `paused`. Từ chối `completed` (409). `active` thì bỏ qua bước chuyển trạng thái, chỉ gửi tiếp (send có sẵn idempotent — không gửi trùng người đã nhận).
  2. Chuyển trạng thái tuần tự, set timestamp như PATCH status đang làm: `approved_at` (nếu từ draft), `started_at` (nếu chưa có).
  3. Nếu `campaign_type == "email"`: gọi `send_campaign_emails(db, campaign)` (tái dùng nguyên hàm, đủ mọi gate an toàn).
  4. Nếu campaign social: chỉ activate, trả summary rỗng.
  5. Response: giống `CampaignSendResponse` hiện có (sent/skipped/throttled/failed) + status mới.
- Giữ nguyên endpoint PATCH status + POST send cũ (không phá API cũ, xoá sau nếu muốn).

## Frontend

**Files:** `apps/web/src/lib/api.ts`, `apps/web/src/app/dashboard/campaigns/page.tsx`

- `api.startCampaign(siteId, campaignId)` → POST `/start`.
- Actions column mới:
  - `draft` / `approved` / `paused` → nút chính **"Start beam"** (mở dialog xác nhận: tên campaign + cảnh báo "email sẽ gửi thật tới segment").
  - `active` → nút phụ **"Pause"** + nút "Start beam" đổi label thành **"Send new"** (gửi cho thành viên segment mới, idempotent).
  - `completed` → không nút.
- Sau khi start: hiện summary sent/skipped như handleSend hiện tại, invalidate query.
- Xoá handler Approve/Start rời (`handleStatusChange` giữ lại cho Pause).

## Verify

- Campaign draft → bấm Start beam → status `active`, email gửi (mock mode), summary hiện đúng.
- Campaign social draft → Start beam → active, không gửi email.
- Completed → không có nút.
- `pytest` router campaigns + chạy web local bấm thử.
