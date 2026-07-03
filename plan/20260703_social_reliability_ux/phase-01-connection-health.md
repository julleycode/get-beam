# Phase 1 (P1) — Connection health badge + Reconnect

**Trạng thái:** ✅ Code xong + verify local (2026-07-03) — CHƯA commit/deploy
**Effort:** TB · **Migration:** Không · **ROI:** Cao — làm ĐẦU TIÊN (dữ liệu đã có sẵn)

> **Đã làm gọn hơn plan gốc:** KHÔNG cần endpoint reconnect mới / sửa oauth_callback. Reconnect = tái dùng `connectPlatform` (OAuth upsert theo `platform_user_id` → update đúng row cũ, không trùng). Backend chỉ thêm `is_outreach` vào response (ẩn badge/reconnect cho LinkedIn cookie). Không migration.
>
> **Files đã sửa:** `apps/api/schemas/accounts.py` (+`is_outreach`), `apps/api/routers/social_accounts.py` (populate), `apps/web/src/lib/api-types.ts` (+`is_outreach`), `apps/web/src/components/connection-health.tsx` (MỚI — `connectionHealth()` + `ConnectionHealthBadge`), `apps/web/src/app/dashboard/social-accounts/page.tsx` (badge + nút Reconnect).
>
> **Verify:** backend import OK, `tsc` 0 lỗi, `next lint` sạch, logic 7/7 case (gồm guard naive-UTC), route dev-server compile sạch (404 = Clerk gate signed-out, đúng). Badge thật chưa xem trong browser vì tường Clerk.

## Mục tiêu

Trên trang Social Accounts, mỗi tài khoản hiện **huy hiệu tình trạng** + **1 nút Reconnect**, để user thấy kết nối sắp/đã gãy TRƯỚC khi gửi fail.

- 🟢 **Connected** — token còn hạn (> 7 ngày, hoặc không rõ hạn nhưng `is_active`).
- 🟡 **Expiring soon** — hết hạn trong ≤ 7 ngày.
- 🔴 **Reconnect needed** — đã hết hạn, hoặc `is_active=false`.

## Dữ liệu (đã có, KHÔNG cần migration)

`token_expires_at` + `is_active` đã trả về trong `SocialAccountResponse` ([schemas/accounts.py](apps/api/schemas/accounts.py)) và có trong TS type `SocialAccount` ([api-types.ts](apps/web/src/lib/api-types.ts)). → Frontend tự tính status.

## Backend

**File:** `apps/api/routers/social_accounts.py`, `apps/api/routers/social_auth.py`

- Thêm endpoint **`POST /accounts/{account_id}/reconnect`** → khởi động lại OAuth cho đúng account đó, trả `{auth_url}`.
- Sửa `oauth_callback` nhận optional `account_id` (nhét vào OAuth `state`): nếu có → **update đúng row cũ** (reset `refresh_token`, set token mới, `is_active=true`) thay vì tạo account mới → tránh nhân đôi.
- Ẩn/từ chối reconnect cho account có `outreach_connection_id` (LinkedIn outreach dùng cookie, không OAuth).

## Frontend

**Files:** `apps/web/src/app/dashboard/social-accounts/page.tsx`, `apps/web/src/lib/api.ts`, `apps/web/src/lib/api-types.ts`

- Hàm tính status (client): so `token_expires_at` với `now` (quy giờ local), ngưỡng 7 ngày. Trả `'connected' | 'expiring' | 'reconnect'`.
- Component badge nhỏ cạnh username (dùng token màu sẵn: success / warning / destructive — KHÔNG hardcode hex, theo [[dashboard-warm-design-system]]).
- Nút **Reconnect** cạnh Disconnect → `api.reconnectPlatform(platform, accountId)` → mở `auth_url`. Loading state như connect.
- Copy: badge = `Connected` / `Expiring soon` / `Reconnect needed`. Nút = `Reconnect`. Tooltip 🟡 = `This connection expires soon — reconnect to keep sending.`

## Rủi ro

- Timezone: tính ngưỡng theo giờ local, đừng so naive-UTC.
- Reconnect giữa chừng mất session → callback fail; nhét `account_id` vào `state` hash để bám đúng row + user.
- Account outreach (cookie) không reconnect OAuth → ẩn nút.

## Verify

- Account token hết hạn → badge 🔴 + nút Reconnect hiện.
- Bấm Reconnect → OAuth → về, badge 🟢, KHÔNG tạo account trùng (verify DB 1 row).
- Account expiring trong 7 ngày → 🟡.
- `pytest` router social_accounts/social_auth; `tsc` + chạy web local.

## Acceptance

User nhìn Social Accounts là biết ngay kết nối nào cần sửa, sửa bằng 1 nút, không phải chờ tới lúc gửi fail.
