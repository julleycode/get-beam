# Phase 4 — API thống kê + UI "ai quay lại"

**Trạng thái:** ✅ Xong (2026-07-02)

## Mục tiêu

Trang chi tiết campaign hiện: Sent / Opened / Clicked / Open rate / Click rate + danh sách **đích danh ai** đã quay lại website sau email.

## Backend

**File:** `apps/api/routers/campaigns.py` (+ schema)

- Endpoint mới: `GET /{site_id}/{campaign_id}/stats`
- Tính từ `campaign_touchpoints` (channel="email", status="sent"):
  - `sent` = count sent_at not null
  - `opened` = count opened_at not null → `open_rate = opened/sent`
  - `clicked` = count clicked_at not null → `click_rate = clicked/sent`
- **"Ai quay lại"**: với các visitor_id đã sent, query bảng events (site-scoped, `timestamp > sent_at` của touchpoint tương ứng) → lấy lần visit gần nhất. JOIN `identified_visitors` lấy tên/email hiển thị.
  - Giới hạn: chỉ query events của đúng list visitor_id (index theo visitor_id + site_id), limit 100 — không quét cả bảng.
- Response:
```json
{
  "sent": 12, "opened": 5, "clicked": 3,
  "open_rate": 0.42, "click_rate": 0.25,
  "returned_visitors": [
    { "visitor_id": "...", "full_name": "...", "email_masked": "d***@x.com",
      "opened_at": "...", "clicked_at": "...", "last_visit_at": "...", "pageviews_after": 4 }
  ]
}
```

## Frontend

**Files:** `apps/web/src/lib/api.ts`, `apps/web/src/lib/api-types.ts`, `apps/web/src/app/dashboard/campaigns/[campaignId]/page.tsx`

- `api.getCampaignStats(siteId, campaignId)` + react-query.
- Trang chi tiết campaign thêm:
  - Hàng StatTile: Sent / Opened / Clicked / Open rate / Click rate (dùng component StatTile có sẵn của design system).
  - InfoTooltip cạnh Open rate: "Open có thể đếm dư do Apple Mail tự tải ảnh".
  - Bảng **"Came back after email"**: tên (link sang trang visitor detail), opened/clicked, lần quay lại gần nhất, số pageview sau email. Empty state khi chưa ai quay lại.
- Trang list campaigns: hiện mini chỉ số (vd. "5 opens · 3 clicks") dưới tên campaign đã gửi — nhẹ, không thêm cột.

## Verify

- Seed mock: campaign sent + touchpoints có opened_at/clicked_at + events sau send → stats đúng số, đúng người.
- Campaign chưa gửi → stats toàn 0, UI không vỡ.
- `pytest` cho stats endpoint; chạy web local xem trang chi tiết.
