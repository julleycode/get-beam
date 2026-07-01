# Phase 03 — (b) Đưa nội dung vào prompt campaign

**Trạng thái:** ⬜ chưa làm
**Rủi ro:** 🟢 thấp
**Phụ thuộc:** P1 (P2 giúp có data nhưng không bắt buộc)

## Mục tiêu
Email campaign nhắc đúng nội dung thật khách/công ty vừa đăng → cá nhân hoá mạnh hơn.

## Bối cảnh (đã research)
Campaign planner hiện **KHÔNG đọc** `social_context` — chỉ ăn segment + field enrich cơ bản. `social_context` (tweet, deep_research, và YT/Reddit từ P2) **đã có sẵn nhưng bị bỏ quên**. P3 = nối nó vào.

## Touchpoints
- **Sửa:** `apps/api/agents/segmenter.py` `build_visitor_profiles()` (dòng 83-113) — thêm field `recent_content` đọc từ `enriched.social_context`.
- **Sửa:** `apps/api/routers/campaigns.py` (73-89) — path tương tác cũng thêm field tương tự.
- **Sửa:** `apps/api/agents/campaign_planner.py` `CAMPAIGN_PLANNING_PROMPT` (14-97) — thêm phần dùng `recent_content` để cá nhân hoá.

## Việc cụ thể
1. `build_visitor_profiles`: nếu `social_context` có `youtube`/`reddit`/`deep_research`/tweet → gộp thành `recent_content` (chuỗi ngắn, tóm tắt).
2. Prompt: thêm hướng dẫn "nếu có recent_content, tham chiếu tự nhiên trong email, không bịa".
3. Giới hạn độ dài `recent_content` (tránh phình prompt / lộ dữ liệu thừa).

## Blast radius
Chỉ đổi nội dung prompt (chất lượng email). Không đổi schema, không đổi luồng gửi. Nếu `social_context` rỗng → prompt như cũ.

## Verification
- Test: visitor có `social_context` → prompt chứa `recent_content`.
- Test: rỗng → prompt không có phần đó, không lỗi.
- Chạy thử 1 campaign (mock AI) → email nhắc đúng nội dung seed.
