# Phase 02 — (a) Nối vào enrichment: làm giàu persona

**Trạng thái:** ⬜ chưa làm
**Rủi ro:** 🟢 thấp
**Phụ thuộc:** P1

## Mục tiêu
Khi Beam đã biết handle YouTube/Reddit của 1 khách → hứng nội dung gần nhất, lưu vào `social_context` để hồ sơ giàu hơn.

## Vấn đề "lấy handle ở đâu" (quan trọng)
Beam **thường không có** handle YT/Reddit chính xác. Nguồn thực tế:
1. **PDL** đôi khi trả social profiles (hiếm với YT/Reddit).
2. **OSINT scanner** (`osint_scanner.py`) — check account tồn tại trên 100+ site; nếu ra username YT/Reddit thì dùng.
→ P2 chỉ chạy khi **đã có handle**. Không có handle = bỏ qua (coverage lẻ tẻ, chấp nhận). Tìm kênh chủ động = P4.

## Touchpoints
- **Sửa:** `apps/api/services/enricher.py` — thêm bước gọi `content_reader` khi có handle, ghi kết quả vào `social_context` (gộp cùng cơ chế `social_intelligence.py` đang dùng cho tweet).
- **Có thể sửa:** `apps/api/services/social_intelligence.py` nếu tái dùng chỗ ghi `social_context`.
- **Sửa (test):** test enrichment path có handle.

## Việc cụ thể
1. Trong luồng enrich (sau khi có social handle, gated `enable_content_reader` + intent cao):
   - Có `youtube_handle` → `fetch_youtube` → ghi `social_context["youtube"] = {...}`.
   - Có `reddit_handle` → `fetch_reddit` → ghi `social_context["reddit"] = {...}`.
   - Cập nhật `social_context_updated_at`.
2. Non-fatal: lỗi không làm hỏng enrich chính.
3. KHÔNG thêm cột DB (dùng `social_context` JSONB sẵn có → khỏi migration).

## Blast radius
Chỉ ảnh hưởng khi flag ON + có handle + intent cao. Mặc định OFF = luồng prod không đổi.

## Verification
- Test: visitor có `reddit_handle` giả → `social_context["reddit"]` được ghi.
- Test: không có handle → không gọi, không lỗi.
- Flag OFF → bước này bị skip hoàn toàn.
