# Phase 03 — Backend: gửi qua Gmail + routing (fallback Beam)

Trạng thái: ⬜ · Rủi ro: Trung bình · Phụ thuộc: Phase 02

## GmailSender (`apps/api/services/email_providers/gmail_sender.py`)
- `async def send(sender_row, to_email, subject, body_html, unsubscribe_url) -> dict`:
  1. Đảm bảo token còn hạn: nếu `token_expires_at` sắp/đã hết → `refresh()` → cập nhật row (encrypt lại).
  2. Dựng **MIME** (`email.mime.multipart` / `text`): From = `sender_row.email`, To, Subject, HTML body + link Unsubscribe + header `List-Unsubscribe`.
  3. Base64url-encode → POST `https://gmail.googleapis.com/gmail/v1/users/me/messages/send` với `Authorization: Bearer <access_token>`.
  4. Lỗi 401/invalid_grant (user gỡ quyền) → raise dạng riêng để caller fallback + đánh dấu sender cần reconnect.

## Router chọn kênh (dùng chung cho send thật + test-send)
Thêm helper, vd `resolve_email_channel(db, site) -> ("gmail", sender_row) | ("beam", None)`:
- Lấy `email_senders` active của `Site.user_id`, provider=google → nếu có: kênh **gmail**; nếu không: kênh **beam** (như hiện tại).

Áp vào:
- `apps/api/services/campaign_sender.py` → `send_campaign_emails`:
  - Trước vòng lặp: resolve kênh 1 lần.
  - Trong vòng lặp: nếu gmail → `GmailSender.send(...)`; nếu lỗi token/refresh → **fallback** `EmailSender().send(...)` (Beam) + log + (không làm hỏng cả campaign).
  - Giữ nguyên: suppression check, do_not_email, cap giờ, idempotency touchpoint, open pixel, decorate_links, unsubscribe.
- `apps/api/routers/campaigns.py` → `test_send_campaign`: cùng logic (gmail nếu có, else Beam). `[TEST]` prefix giữ nguyên.

## Guard giới hạn Gmail
- Thêm cap ngày mềm cho kênh gmail (vd counter Redis `gmail_send:{user_id}:{day}`, ngưỡng cấu hình mặc định ~450 để chừa margin dưới 500). Chạm ngưỡng → throttle (giống cap giờ hiện có), không gửi tiếp trong ngày.

## KHÔNG đụng
- Email hệ thống (waitlist/feature_requests/demo/hot_alert/dependencies) → luôn Beam/SendGrid.

## Verify
- Unit: routing chọn gmail khi có sender active, chọn beam khi không; MIME build đúng (From = user email, có List-Unsubscribe); fallback khi GmailSender raise.
- Integration: campaign send với sender gmail (mock Gmail API) → touchpoint status sent, không đụng suppression logic.
- Tay: connect Gmail → Start beam (segment 1 người test) → email tới, header "From: you@gmail.com", KHÔNG "via sendgrid".
