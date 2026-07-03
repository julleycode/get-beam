# Phase 01 — Google Cloud OAuth app + config

Trạng thái: ⬜ · Rủi ro: Thấp (chủ yếu ops, ít code) · Phụ thuộc: không

## Việc ở Google Cloud Console (thao tác tay, user hoặc operator làm)
1. Tạo (hoặc dùng) 1 Google Cloud project cho Beam.
2. **OAuth consent screen**: External, điền app name "Beam", logo, domain `getbeam.fyi`, privacy policy + terms URL (Google bắt buộc để verify sau).
3. Thêm scope: `https://www.googleapis.com/auth/gmail.send` (chỉ xin quyền GỬI, không đọc — giảm rủi ro + dễ verify hơn).
4. Tạo **OAuth client ID** (Web application):
   - Authorized redirect URI (prod): `https://api.getbeam.fyi/api/v1/email/callback/google`
   - Redirect URI (local): `http://localhost:8000/api/v1/email/callback/google`
5. Lấy **Client ID** + **Client Secret**.
6. Thêm 1–2 email test (chính user) vào "Test users" để dùng ngay khi chưa verify.

## Việc code (nhỏ)
- `apps/api/config.py` — thêm:
  ```python
  google_client_id: str = ""
  google_client_secret: str = ""
  google_redirect_uri: str = "http://localhost:8000/api/v1/email/callback/google"
  ```
- Đặt biến env thật lên Railway (prod) + `.env` (local): `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`.

## Verify
- Config load được, không crash khi để trống (giống các OAuth khác — graceful).
- Chưa cần test gì thêm; Phase 2 mới dùng.

## Ghi chú verify Google (quan trọng)
- Xin `gmail.send` = **restricted scope** → cần Google verify app trước khi mở cho public (Phase 5).
- Trong lúc chờ: chế độ **Testing** cho phép các "Test users" đã add gửi bình thường → đủ để demo + early users.
