# Phase 02 — Backend: model + OAuth connect/callback cho Gmail

Trạng thái: ⬜ · Rủi ro: Trung bình · Phụ thuộc: Phase 01

## Model + migration
- Bảng mới `email_senders` (`apps/api/models/email_sender.py`):
  ```
  id UUID pk
  user_id UUID  FK users.id ON DELETE CASCADE   # chủ site = người gửi
  provider str  # "google" (để dành mở rộng outlook sau)
  email str     # địa chỉ Gmail đã nối (dùng làm From)
  access_token Text   # Fernet-encrypted
  refresh_token Text  # Fernet-encrypted
  token_expires_at datetime | null
  scopes ARRAY(str)
  is_active bool default true
  created_at / updated_at
  unique (user_id, provider)
  ```
- Alembic migration:
  - **TRƯỚC KHI VIẾT**: chạy `alembic heads`, chain `down_revision` off head hiện tại. Nếu nhánh song song vừa thêm migration → rebase để tránh multi-head (xem memory [[visitor-widgets-plan]] gotcha).
- Mã hoá token: dùng helper Fernet `token_encryption_key` (giống social OAuth). Tìm helper hiện có (`services/...` mà social_auth dùng để encrypt `access_token`) và tái dùng.

## Service GmailService (`apps/api/services/email_providers/gmail.py`)
Mирror `PlatformService`:
- `get_auth_url(state) -> str`:
  - `https://accounts.google.com/o/oauth2/v2/auth?client_id=..&redirect_uri=..&response_type=code&scope=gmail.send&access_type=offline&prompt=consent&state=..`
  - `access_type=offline` + `prompt=consent` để CHẮC CHẮN nhận refresh_token.
- `exchange_code(code) -> OAuthTokens`: POST `https://oauth2.googleapis.com/token` → access/refresh/expires_in. Lấy email: gọi `https://www.googleapis.com/oauth2/v2/userinfo` (hoặc decode id_token) → `email`.
- `refresh(refresh_token) -> OAuthTokens`: POST token endpoint `grant_type=refresh_token`.

## Router (`apps/api/routers/email_sender_oauth.py`, mount `/api/v1/email`)
Copy y hệt `social_auth.py`:
- `GET /connect/google` → tạo state (lưu user_id cho CSRF, giống social) → trả `auth_url`.
- `GET /callback/google?code&state` → validate state → `exchange_code` → upsert `email_senders` (encrypt token) → redirect `{frontend}/dashboard/connectors?gmail=connected` (hoặc trang callback riêng).
- `GET /status` → trả `{connected: bool, email: str|null}` cho UI.
- `POST /disconnect` → set is_active=false (hoặc xoá row) + (nên) gọi Google revoke endpoint.

## Bảo mật
- State CSRF như social (đừng bỏ).
- Token luôn Fernet-encrypted ở rest.
- Chỉ chủ site nối được sender của chính mình (scope theo `user_id` = caller).

## Verify
- Unit: `get_auth_url` chứa `gmail.send` + `access_type=offline`; `exchange_code` parse token (mock httpx); refresh parse đúng.
- Chạy tay local: bấm connect → Google consent (test user) → callback lưu row, token giải mã được, email đúng.
