# Phase 5 — Tests + verify toàn bộ

**Trạng thái:** ✅ Xong (2026-07-02)

## Mục tiêu

Chốt chất lượng trước khi ship: full test suite + chạy tay end-to-end local.

## Việc cần làm

1. **Backend:** `pytest` toàn bộ (không chỉ file mới) — start/test-send/open/click/stats + regression các test campaign_sender cũ (chú ý gotcha: fixture phải seed `resolution_provider="form_capture"` mới qua gate emailable).
2. **Frontend:** `npx tsc --noEmit` + `npm run lint` (Vercel chạy lint khi build — lint fail là deploy fail).
3. **E2E (nếu Docker sống):** flow Playwright campaigns — cập nhật selector theo nút mới "Start beam" (test cũ đang tìm "Approve"/"Send emails" sẽ gãy). Theo rule: dùng `toBeVisible({timeout})`, không `waitForTimeout`.
4. **Chạy tay local (mock mode):** tạo campaign → Send test → Start beam → giả open/click qua curl → xem stats + danh sách quay lại trên UI.
5. Cập nhật status markers trong plan.md.

## Điều kiện xong

- Toàn bộ pytest xanh, tsc + lint sạch.
- Flow tay chạy đủ: test email → start → open/click ghi nhận → stats hiện đúng.
