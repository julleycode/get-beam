# Phase 3 (P3) — Proactive nudge (in-app + email)

**Trạng thái:** ⬜ Chưa làm
**Effort:** TB · **Migration:** Có (`*.last_expiry_alert_sent_at`) · **ROI:** Cao — chặn churn âm thầm

## Mục tiêu

Chủ động cảnh báo user **trước** khi kết nối gãy: banner in-app + email "Action needed: reconnect your X account". Không để user phát hiện qua draft fail.

## Hạ tầng tái dùng (đã có)

- Email: `EmailSender` ([services/email_sender.py](apps/api/services/email_sender.py)) — SendGrid, suppression, unsubscribe. Pattern email giao dịch: [hot_alert.py](apps/api/services/hot_alert.py) (Redis dedup + user lookup).
- In-app: [today-actions.tsx](apps/web/src/components/today-actions.tsx) — card việc-cần-làm, dismiss bằng localStorage.
- Job nền: [jobs/scheduler.py](apps/api/jobs/scheduler.py) — APScheduler, đã có sweep/sync (dùng advisory lock single-flight qua replica).

## Migration

**Files:** `apps/api/models/social_account.py` (+ `crm_connection.py` nếu gộp CRM), migration mới

- Thêm `last_expiry_alert_sent_at: DateTime nullable` (chống spam nhắc mỗi giờ).
- Index `token_expires_at` (job quét nhanh khi scale).

## Backend

**Files mới:** `apps/api/services/token_expiry_detector.py`; **sửa:** `apps/api/jobs/scheduler.py`, `apps/api/routers/` (endpoint fetch cho banner)

- Job `_token_expiry_check_job()` chạy **mỗi giờ** (advisory-lock như sweep):
  - Query `SocialAccount` (+ optional CRM) có `token_expires_at` trong ≤ 7 ngày HOẶC đã hết hạn, và `last_expiry_alert_sent_at` cũ hơn X (vd 24h).
  - Với mỗi account: gửi email qua `EmailSender` (Redis dedup), set `last_expiry_alert_sent_at = now`.
  - Bỏ qua account `outreach_connection_id` (cookie, khác luồng).
  - Lỗi refresh/timeout giữa chừng → log, KHÔNG vỡ cả job.
- Endpoint **`GET /notifications/expiring-connections`** → trả list kết nối sắp/đã gãy cho banner in-app.

## Frontend

**Files mới:** `apps/web/src/components/expiring-connection-banner.tsx`; **sửa:** dashboard layout

- Banner dính (giống error-banner nhưng sticky) khi có kết nối 🟡/🔴: `Your X connection expires soon. Reconnect to keep replies flowing.` + nút **Reconnect** (dẫn P1).
- Dismiss reset theo ngày (như today-actions) — nhắc lại hôm sau nếu chưa sửa.

## Rủi ro

- **Alert fatigue:** `last_expiry_alert_sent_at` + Redis dedup bắt buộc, đừng nhắc mỗi giờ.
- Quét toàn bảng mỗi giờ chậm khi scale → cần index `token_expires_at`.
- Email cần db session cho suppression check — truyền session vào detector.
- Naive-UTC drift → dùng timezone-aware mọi nơi.

## Verify

- Seed account hết hạn trong 3 ngày → chạy job tay → nhận đúng 1 email (mock), `last_expiry_alert_sent_at` set; chạy lại trong 24h → KHÔNG gửi lại.
- Banner in-app hiện khi có kết nối 🟡/🔴, ẩn khi Connected.
- `pytest` detector + endpoint.

## Acceptance

Kết nối sắp gãy → user được nhắc trước (email + banner) + sửa 1 nút, không bao giờ "ngã ngửa" vì draft fail.
