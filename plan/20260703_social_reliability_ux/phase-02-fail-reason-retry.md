# Phase 2 (P2) — Draft fail reason + Retry

**Trạng thái:** ⬜ Chưa làm
**Effort:** TB · **Migration:** Có (`drafts.failure_reason`) · **ROI:** Cao

## Mục tiêu

Draft ở tab **Failed** hiện **lý do bằng tiếng người** + nút **Retry**, thay vì chữ "Failed" trơ. Nối tiếp lỗi 401 "reconnect" backend vừa ship.

## Migration + Model

**Files:** `apps/api/models/draft.py`, migration mới Alembic (off head hiện tại, tránh multi-head)

- Thêm cột `failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)`.
- `ALTER TABLE drafts ADD COLUMN failure_reason TEXT NULL;`

## Backend

**Files:** `apps/api/services/sender.py`, `apps/api/routers/drafts.py`, `apps/api/schemas/drafts.py`

- `send_draft`: khi fail, **lưu lý do** vào `draft.failure_reason` trước khi commit. Phân loại rõ:
  - Token hết hạn → `"Your X session for @{username} expired. Reconnect and retry."` (từ `SocialTokenExpiredError`).
  - X 403 reply-forbidden → `"X wouldn't allow this reply (the post may restrict replies)."`
  - Rate limit / timeout → `"X is busy or rate-limited. Try again shortly."`
  - Khác → thông điệp ngắn từ `_http_error_detail`.
- Endpoint mới **`POST /drafts/{id}/retry`**: chỉ với draft `failed`; chạy lại đúng luồng gửi (`send_draft`), xoá `failure_reason` khi thành công. Tận dụng FOR UPDATE + refresh đã có.
- `DraftResponse` thêm `failure_reason: Optional[str] = None`.

## Frontend

**Files:** `apps/web/src/lib/api-types.ts`, `apps/web/src/lib/api.ts`, `apps/web/src/components/draft-card.tsx`, `apps/web/src/app/dashboard/drafts/page.tsx`

- Type `SocialDraft` thêm `failure_reason: string | null`.
- `api.retryDraft(draftId)`.
- `draft-card.tsx`: khi `status=failed` → hiện `failure_reason` (dùng [error-banner.tsx](apps/web/src/components/error-banner.tsx) inline) + nút hành động **theo loại lỗi**:
  - Token → nút **Reconnect** (link tới Social Accounts, dẫn tới P1).
  - Transient (rate/timeout) → nút **Retry**.
- Mutation retry → invalidate `["drafts"]`.

## Rủi ro

- **Đừng cho Retry lỗi không hồi phục được** (post bị xoá, reply-forbidden) → chỉ hiện Reconnect/nothing, tránh user bấm Retry vô ích.
- Giữ phân biệt 401 (reconnect) vs 502 (generic) — đừng gộp hết vào 1 `failure_reason` mờ.
- Retry phải refresh token lại (đã có trong `_refresh_if_expired` + FOR UPDATE).

## Verify

- Force 1 draft fail (token hết hạn) → tab Failed hiện lý do + nút Reconnect.
- Reconnect xong → Retry → gửi thành công, `failure_reason` mất, draft sang Sent.
- `pytest` sender + drafts (thêm test retry endpoint + failure_reason persist).

## Acceptance

Mọi draft failed đều nói được vì sao + có đúng 1 hành động sửa. Không còn "Failed" câm.
