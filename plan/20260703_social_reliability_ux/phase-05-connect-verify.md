# Phase 5 (P5) — Connect-time write-access verify

**Trạng thái:** ✅ SHIPPED main `e1878ca` + pushed (2026-07-03) — prod deploy
**Effort:** Cao · **Migration:** Có (`social_accounts.post_ready`, rev `e2f5b8c1d094`) · **ROI:** TB

> **Đã làm (scope thực tế):** probe THẬT cho Twitter (`x-access-level` qua `/2/users/me`); platform khác default `None` (không claim sai). `PlatformService.check_write_access` (base None, không raise) + TwitterService override; `oauth_callback` probe → lưu `post_ready` + đẩy vào redirect param; callback page hiện "✓ Ready to post" hoặc cảnh báo "needs write access". Bỏ badge ở list page (tránh collision session khác). **GỘP kèm fix has_refresh_token** (session khác, cùng file) — account có refresh token auto-renew nên health/banner/nudge KHÔNG cảnh báo. Verify: 577 unit pass (+write-probe test), tsc/lint sạch. **Multi-head Alembic (email_senders vs post_ready) đã tự resolve** — session khác rebase migration của họ lên `e2f5b8c1d094` → chain linear single-head `f3d9b1c7a2e4`, `alembic upgrade head` chạy sạch.

## Mục tiêu

Nối tài khoản xong → **kiểm ngay quyền đăng bài** → hiện `✅ Ready to post` hoặc `⚠️ Needs write access`. Bắt lỗi setup ngay lúc nối, không để tới lần gửi đầu mới lòi (đúng cái mình probe tay hôm nay: `x-access-level`).

## Vấn đề hiện tại

`oauth_callback` ([social_auth.py](apps/api/routers/social_auth.py)) chỉ đổi code → token → lưu, KHÔNG kiểm user có đăng được không. Scope được lưu nhưng chưa bao giờ validate. Callback chỉ hiện "Connected!" chung chung.

## Migration

**Files:** `apps/api/models/social_account.py`, migration mới

- Thêm `post_ready: Boolean nullable` (None = chưa kiểm/không kiểm được).
- Index để filter Ready vs Needs-write.

## Backend

**Files:** `apps/api/services/platforms/base.py` + từng platform service, `apps/api/routers/social_auth.py`, `apps/api/schemas/accounts.py`

- Thêm method abstract `async check_write_access(access_token) -> bool | None` vào `PlatformService`.
- Implement từng platform:
  - **Twitter**: `GET /2/users/me` đọc header **`x-access-level`** = `read-write`? (dùng lại call `_get_me`, +0 cost — đúng cách đã test hôm nay).
  - **LinkedIn**: kiểm scope `w_member_social` có mặt / call `/rest/posts?count=0` nhẹ.
  - **Facebook**: `GET /me/permissions` kiểm publish scope.
  - Instagram/TikTok: test scope ghi hoặc endpoint ghi nhẹ.
- `oauth_callback`: sau `exchange_code`, gọi `check_write_access()`, lưu `post_ready` vào row trước commit. Lỗi probe → `post_ready=None` (đừng chặn nối).
- `SocialAccountResponse` thêm `post_ready: bool | None`.

## Frontend

**Files:** `apps/web/src/app/dashboard/social-accounts/callback/page.tsx`, `.../social-accounts/page.tsx`, `apps/web/src/lib/api-types.ts`

- Callback page: nếu `post_ready=false` → hiện `⚠️ Connected, but this account can't post yet. Check app permissions.` + link hướng dẫn. `true` → `✅ Ready to post.`
- List account: icon/badge Ready-to-post cạnh username (bổ trợ badge health P1).

## Rủi ro

- **False negative:** platform cấp scope nhưng vẫn chặn (account chưa verify) → probe pass mà post thật fail. Chấp nhận, cập nhật `post_ready=false` khi gặp 403 lúc gửi thật.
- **Token drift:** user thu hồi quyền sau khi nối → `post_ready` chỉ phản ánh lúc nối. Job nền (P3) có thể re-probe khi `post_ready=false`.
- Rate limit khi signup nhiều (FB/LinkedIn probe tốn call riêng) → wrap try/except, `post_ready=None` nếu probe fail.
- Scope/endpoint platform đổi theo thời gian → version scope trong config, document logic probe.

## Verify

- Nối X account read-write → `post_ready=true`, callback hiện ✅.
- Nối account thiếu quyền ghi (test) → `post_ready=false`, callback hiện ⚠️.
- `pytest` từng `check_write_access` (mock HTTP header/response).

## Acceptance

Nối xong user biết ngay đăng được hay chưa, không phải thử gửi mới phát hiện thiếu quyền.
