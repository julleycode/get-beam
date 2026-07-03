# Plan: Gửi campaign email TỪ Gmail của user (Connect Gmail)

Ngày: 2026-07-03 · Trạng thái tổng: ⬜ Chưa bắt đầu

## Mục tiêu (nói đơn giản)

Hiện tại mọi email campaign gửi đi đều hiện **"Beam via sendgrid.info"** — không phải từ email của khách hàng (user của Beam). Khách nhận thấy Beam, không thấy bạn.

Muốn: user **bấm "Connect Google"** một lần, cho phép Beam gửi giúp qua Gmail của họ → email đi ra **đúng tên + đúng địa chỉ Gmail của user**, KHÔNG còn chữ "via". Người nhận reply là về thẳng hộp thư user.

## Tại sao lại là Gmail OAuth (không phải cách khác)

- Beam nhắm indie / DTC → đa số dùng `@gmail.com` (không có domain riêng để xác thực DNS).
- Gmail hiện "via sendgrid.info" vì DKIM là của getbeam.fyi. Chỉ **2 cách** xoá được "via":
  1. Gửi thật qua Gmail user (OAuth) ← **plan này**
  2. Xác thực domain riêng qua DNS (chỉ hợp user có domain — để dành làm sau, xem `references/`).
- "Verify 1 email" (SendGrid Single Sender) KHÔNG xoá được "via" với @gmail → loại.

## Nguyên tắc quan trọng (đừng phá cái đang chạy)

- **Chỉ CAMPAIGN email** đổi sang gửi qua Gmail user. Email hệ thống (waitlist, invite, hot-alert, admin) **giữ nguyên** gửi qua Beam/SendGrid.
- **Fallback an toàn:** user CHƯA connect Gmail → gửi y như cũ (Beam/SendGrid). Không connect = không đổi gì → zero regression.
- Giữ nguyên: link Unsubscribe, header `List-Unsubscribe`, check suppression/do_not_email, cap gửi theo giờ.

## Gotcha lớn (phải biết trước khi làm)

1. **Google bắt xác minh app** cho quyền `gmail.send` (scope nhạy cảm/restricted).
   - Trước khi Google duyệt: app chạy chế độ **"Testing"** → chỉ cho tối đa ~100 "test users" (email được add tay), hoặc user thấy màn hình cảnh báo "app chưa verify".
   - Xác minh mất **vài tuần** + có thể cần security review. → Nộp hồ sơ SONG SONG khi code (Phase 5), không chặn dev.
2. **Giới hạn gửi của Gmail:** ~500 mail/ngày (Gmail thường), ~2000 (Workspace). Không hợp blast lớn — nhưng đúng tầm indie. Phải guard.
3. **Token hết hạn / user gỡ quyền** → phải refresh token; refresh fail thì fallback Beam + báo user reconnect.
4. **Alembic:** trước khi viết migration, check head hiện tại (nhánh song song có thể đã thêm migration → tránh multi-head).

## Kiến trúc (mирror flow OAuth social sẵn có)

Đã có sẵn để nhân bản:
- `apps/api/routers/social_auth.py` — pattern `/connect/{platform}` (state CSRF) → `/callback/{platform}` (exchange_code → lưu account). Copy y hệt cho Google.
- `apps/api/services/platforms/base.py` — `PlatformService` (get_auth_url / exchange_code / refresh_tokens), dataclass `OAuthTokens`.
- Fernet `token_encryption_key` — mã hoá token lúc lưu.
- Chỗ gửi campaign: `apps/api/services/campaign_sender.py` (gửi thật) + `apps/api/routers/campaigns.py` (test-send). Cả 2 gọi `EmailSender().send(...)`.

Thiết kế mới:
- Bảng mới **`email_senders`** (per user): provider=google, email, access/refresh token (mã hoá), token_expires_at, scopes, is_active. (Không nhét vào `social_accounts` vì gửi email ≠ social — tách cho sạch.)
- Service **`GmailSender`**: gửi qua Gmail API `users.messages.send` (dựng MIME base64), tự refresh token.
- **Router chọn kênh** trong campaign send + test-send: site-owner có `email_senders` google active → gửi qua Gmail; không thì `EmailSender` (Beam) như cũ.
- UI: card "Send from your Gmail" trong `dashboard/connectors` (hoặc `settings`) — Connect / hiện email đã nối / Disconnect.

## Các Phase (làm tuần tự, mỗi phase ship được)

| Phase | Nội dung | Rủi ro | Trạng thái |
|---|---|---|---|
| 00 (tuỳ chọn, quick win) | Reply-To = email user + tên người gửi = tên site cho campaign email | Thấp | ⬜ |
| 01 | Google Cloud: tạo OAuth app + consent screen + scope `gmail.send` + config vars | Thấp (ops, ít code) | ⬜ |
| 02 | Backend: model `email_senders` + migration + `GmailService` (OAuth connect/callback/refresh) | Trung bình | ⬜ |
| 03 | Backend: `GmailSender` + routing gửi (Gmail nếu có, fallback Beam) + guard limit | Trung bình | ⬜ |
| 04 | Frontend: card Connect Gmail (connect / status / disconnect) | Thấp | ⬜ |
| 05 | Google app verification (nộp hồ sơ) + xử lý token fail + docs + đo | Ngoài tầm code (chờ Google) | ⬜ |

Chi tiết từng phase ở file `phase-00..05`.

## Quyết định (đã CHỐT với user 2026-07-03)

1. ✅ **UI để trong trang Campaigns** (không phải Connectors) — card/nút Connect Gmail ngay trong màn campaigns, gần chỗ Send. → Phase 04 cập nhật theo.
2. ✅ **Làm Phase 00 (Reply-To) ngay** — bản vá tạm trước khi Connect Gmail xong.
3. ✅ **Người gửi = chủ site** (Site.user_id), 1 site 1 Gmail.
4. ✅ **Chạy Testing mode trước**, nộp Google verify song song.

## Ngoài phạm vi (không làm trong plan này)

- Xác thực domain riêng (SendGrid Domain Auth) — plan riêng cho user có domain.
- Gửi từ Outlook/Microsoft 365 — sau, nếu có nhu cầu.
- Sequence/drip nhiều bước qua Gmail — plan này chỉ đổi kênh gửi, không đổi logic campaign.
