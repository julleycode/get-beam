# Plan: Sửa logic chặn gói trả tiền (tier guard)

**Ngày:** 29-06-2026
**Nguồn:** audit `paid-tier-guard-gaps.md` (16 lỗi confirmed). Plan này gom **5 lỗi chính**.
**Quyết định đã chốt với user:**
- Lỗ #1 → **chặn thật ở backend** (không chỉ sửa câu chữ).
- Phạm vi → làm **cả 5** lỗ.

**Style:** mỗi phase 1 file `phase-NN-*.md`. Trạng thái: ⬜ chưa làm · 🟡 đang làm · ✅ xong.
**Nguyên tắc:** phase AN TOÀN (không đổi hành vi user) làm trước; phase CẮT tính năng làm sau, mỗi cái có công tắc env bật/tắt để bạn xem rồi mới bật.

> **KHÔNG cần migration DB** — mọi fix dùng cột sẵn có (`plan`, `current_period_end`, `subscription_status`, `trial_ends_at`, `monthly_identified_count`). #5 chỉ đổi hình dạng câu query.

---

## Bảng quyền theo gói (ENTITLEMENT MATRIX) — nguồn DUY NHẤT

Sẽ đặt trong file mới `apps/api/services/entitlements.py`. Mọi chỗ check gói đọc từ đây (hết hardcode rải rác).

| Quyền | Free | Pro | Max | Enforce được giờ? |
|---|---|---|---|---|
| Số visitor identify / tháng | 10 | 50 | ∞ | ✅ đã có (`PLAN_LIMITS`) |
| Số website | 1 | 3 | ∞ | ✅ Phase 5b |
| AI reply drafts | ❌ | ✅ | ✅ | ✅ Phase 5c |
| Social enrichment | ❌ | ✅ | ✅ | ✅ Phase 5c |
| API access | ❌ | ❌ | ✅ | ⚠️ **cần làm rõ** "API access" là gì (xem Quyết định #3) |
| Team seats | ❌ | ❌ | ✅ | 🚫 **HOÃN** — chưa có hệ team trong code; chỉ sửa câu chữ |
| Priority identification | ❌ | ❌ | ✅ | 🚫 **HOÃN** — mơ hồ, chưa có cơ chế ưu tiên; chỉ sửa câu chữ |

---

## Các phase (làm theo thứ tự)

| # | File | Lỗ | Đổi hành vi? | Rủi ro | Trạng thái |
|---|---|---|---|---|---|
| 1 | `phase-01-variant-env.md` | #4 env variant gán nhầm gói | Không | Thấp | ⬜ |
| 2 | `phase-02-atomic-increment.md` | #5 race TOCTOU vượt cap | Không (chỉ chặt hơn) | Thấp | ⬜ |
| 3 | `phase-03-effective-plan.md` | #3 mất webhook = trả tiền mãi | Chỉ hạ user ĐÁNG hạ | Thấp-Vừa | ⬜ |
| 4 | `phase-04-byok-monthly.md` | #2 BYOK không mở cap tháng | Nới lỏng (tốt cho user) | Thấp | ⬜ |
| 5 | `phase-05-feature-gating.md` | #1 chặn tính năng theo gói | **CÓ — cắt user free** | **Cao** | ⬜ |
| 6 | `phase-06-frontend-copy.md` | đồng bộ giá + bỏ hardcode | Không | Thấp | ⬜ |

**Lý do thứ tự:** 1–4 sửa đúng/an toàn, gần như không ai bị ảnh hưởng xấu → ship trước, lấy thắng nhanh. Phase 5 mới là cái cắt tính năng user beta → để cuối, có công tắc, bạn xem kỹ rồi bật.

---

## ⚠️ Quyết định CÒN CẦN ở bạn (trước khi làm Phase 5)

1. **Grandfather user cũ?** User free hiện đang có >1 site / đang dùng AI–CRM thì có giữ nguyên cho họ không?
   → **Đề xuất: CÓ.** Chỉ chặn HÀNH ĐỘNG MỚI (tạo site thứ 2, gọi AI lần mới). Site/đồ cũ vẫn chạy. Tránh làm user beta khó chịu + mất lòng tin.
2. **BYOK = không giới hạn tháng thật?** (Phase 4)
   → **Đề xuất: CÓ** — vì BYOK chạy bằng key của chính user, mình không tốn tiền. Khớp lời hứa trên UI.
3. **"API access" (gói Max) nghĩa là gì?** Hiện code chỉ có "BYOK" (user nhập key của họ) ở `api_keys.py` — đó KHÁC với bán "API access" như một tính năng. Có cổng API công khai nào để bán không?
   → Nếu CHƯA có → **hoãn** "API access" giống team seats (chỉ sửa câu chữ), không gate giả.
4. **Bật gate bằng công tắc env, mặc định TẮT?** Phase 5 ship code ở trạng thái tắt; bạn xem prod ổn rồi bật `ENFORCE_PLAN_FEATURES=true`.
   → **Đề xuất: CÓ.** An toàn, rollback tức thì.

---

## Kiểm thử (mỗi phase tự ghi rõ)
- Stack local: docker-compose (KHÔNG dùng prod DB — xem memory `local-dev-prod-wiring`).
- `MOCK_EXTERNAL_APIS=true` để khỏi đốt credit.
- Test: `pytest` cho path đụng tới; `tests/all-tests.md` để chọn runner.
- Phase 5/6: build `npm run build` (Vercel chạy lint khi build — lỗi lint = fail deploy).

## Resume / handoff
- Làm 1 phase / lần: research (nếu cần) → bạn duyệt → execute → test → cập nhật trạng thái ở bảng trên.
- Plan này KHÔNG cần migration. Nếu sau phát sinh cột mới → verify Alembic head trước (memory `alembic-migrations`).
- Sau khi xong: archive sang `plan/` completed + cập nhật memory `paid-tier-guard-gaps.md` (đánh dấu cái nào đã fix).
