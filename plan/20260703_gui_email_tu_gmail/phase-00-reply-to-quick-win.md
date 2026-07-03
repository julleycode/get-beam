# Phase 00 — Quick win: Reply-To + tên người gửi (TUỲ CHỌN)

Trạng thái: ⬜ · Rủi ro: Thấp · Thời gian: ~15–30 phút

## Ý tưởng
Chưa cần OAuth. Làm campaign email "cá nhân hơn" ngay:
- **From name** = tên site (vd "Acme") thay vì cứng "Beam".
- **Reply-To** = email của chủ site → khách bấm Reply là thư về hộp của user (không về Beam).
- "From address" VẪN là `hello@getbeam.fyi` (vẫn còn "via") — đây chỉ là bản vá tạm, không thay Phase 1–5.

## Touchpoints
- `apps/api/services/email_sender.py`
  - `EmailSender.send(...)` thêm tham số `reply_to: str | None = None`; nếu có → thêm `"reply_to": {"email": reply_to}` vào payload SendGrid.
- `apps/api/services/campaign_sender.py`
  - Trong `send_campaign_emails`: đã fetch site owner (`sender_name`) ở bản fix trước. Lấy thêm `User.email` (chủ site) + `Site.name`.
  - Gọi `sender.send(..., from_name=site_name or "Beam", reply_to=owner_email)`.
- `apps/api/routers/campaigns.py` (test-send)
  - Truyền `from_name=site_name`, `reply_to=user.email`.

## KHÔNG đụng
- Email hệ thống (waitlist/feature_requests/demo/hot_alert/dependencies) — giữ from mặc định.

## Verify
- Test-send → header "From: Acme <hello@getbeam.fyi>", "Reply-To: owner@email". Bấm Reply trên Gmail → tới owner@email.
- Unit/integration campaign send vẫn pass.

## Lưu ý
Đây là bản vá tạm để có giá trị ngay. Không thay thế Connect Gmail (Phase 1–5) vì "via" chỉ mất hẳn khi gửi thật qua Gmail user.
