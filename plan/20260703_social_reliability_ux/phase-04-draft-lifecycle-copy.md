# Phase 4 (P4) — Draft lifecycle relabel (bản anh em)

**Trạng thái:** ⬜ Chưa làm
**Effort:** Thấp–TB · **Migration:** Có (`drafts.rejection_reason`) · **ROI:** TB — gỡ ĐÚNG confuse gốc ("draft chưa duyệt biến đâu")

## Mục tiêu

Khi user duyệt 1 draft, các bản anh em cùng post bị auto-reject. Hiện chúng gắn nhãn **"Rejected"** (nghe như bị chê) và lẫn vào tab Rejected với draft user tự từ chối. → Phân biệt + đổi nhãn thành **"Not used — you picked another reply"**.

## Vấn đề hiện tại

`_auto_reject_siblings` ([drafts.py](apps/api/routers/drafts.py)) set `status=rejected` cho bản anh em — **giống hệt** user bấm Reject. Không có field phân biệt.

## Migration + Model

**Files:** `apps/api/models/draft.py`, migration mới (off head hiện tại)

- Thêm `rejection_reason` (Enum hoặc String nullable): `user_rejected` | `auto_rejected_sibling`.
- Nullable, default None. **Không backfill** dữ liệu cũ (để None — lịch sử mơ hồ, không đoán được).

## Backend

**Files:** `apps/api/routers/drafts.py`, `apps/api/schemas/drafts.py`

- `reject_draft()` → set `rejection_reason = user_rejected`.
- `_auto_reject_siblings()` → set `rejection_reason = auto_rejected_sibling`.
- `DraftResponse` thêm `rejection_reason: Optional[str] = None`.

## Frontend

**Files:** `apps/web/src/components/draft-card.tsx`, `apps/web/src/components/ui/status-badge.tsx`, `apps/web/src/app/dashboard/drafts/page.tsx`

- `status-badge.tsx`: nếu `rejection_reason == auto_rejected_sibling` → nhãn **`Not used`** (tông trung tính/xám), tooltip `You picked another reply for this post.` Ngược lại giữ **`Rejected`**.
- (Tùy chọn) tab Rejected: mặc định **ẩn** bản auto-rejected, có toggle "Show not-used" để bật lại — hoặc đổi tên tab thành **"Not used"**. Chọn 1, đừng làm user bối rối vì draft "biến mất".

## Rủi ro

- Enum phải khớp Python ↔ DB (migration) — lệch type = lỗi runtime.
- Nếu ẩn bản auto-rejected mà không giải thích → user tưởng mất data. Nếu ẩn thì phải có toggle/nhãn tab rõ.
- Dữ liệu cũ `rejection_reason=None` → hiện như "Rejected" (chấp nhận, không đoán ngược).

## Verify

- Tạo post → generate 3 draft → duyệt 1 → 2 bản kia gắn `auto_rejected_sibling`, badge "Not used".
- User bấm Reject 1 draft khác → `user_rejected`, badge "Rejected".
- `pytest` drafts (assert rejection_reason set đúng ở cả 2 đường).

## Acceptance

User hiểu ngay: bản không dùng là do MÌNH chọn bản khác, không phải hệ thống chê. Hết câu hỏi "draft biến đâu".
