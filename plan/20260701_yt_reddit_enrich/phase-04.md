# Phase 04 — Tìm kênh công ty khi thiếu handle

**Trạng thái:** ⬜ chưa làm
**Rủi ro:** 🟡 vừa (thêm bước search, dễ ra kết quả sai)
**Phụ thuộc:** P1, P3

## Mục tiêu
Khi không có handle cá nhân, vẫn cá nhân hoá được bằng nội dung **công ty**: tìm subreddit / kênh YouTube của công ty theo tên/domain rồi đọc.

## Vì sao tách riêng
Đây là phần "vừa rủi ro" vì search dễ match nhầm công ty (đặc biệt tên chung). Làm sau cùng, sau khi P1-P3 đã ổn định.

## Touchpoints
- **Sửa:** `apps/api/services/content_reader.py` — thêm `find_company_channels(company_name, domain)`:
  - Reddit: `httpx.get("https://www.reddit.com/search.json?q=...")` lọc subreddit khớp domain/tên.
  - YouTube: dùng `yt-dlp` search hoặc **Gemini grounding sẵn có** (`gemini_client.grounding=True`) để tìm URL kênh chính chủ.
- **Sửa:** chỗ dựng profile (P3) — nếu thiếu handle cá nhân, thử kênh công ty.

## Việc cụ thể
1. `find_company_channels` trả ứng viên + điểm tin cậy; **chỉ dùng khi tin cậy cao** (khớp domain), tránh match nhầm.
2. Cache mạnh (theo domain, TTL dài) vì công ty ít đổi kênh.
3. Gated flag; non-fatal.

## Blast radius
Chỉ thêm bước tìm-rồi-đọc cho campaign công ty. Sai thì bỏ (confidence gate), không ghi bậy vào hồ sơ.

## Verification
- Test: công ty có subreddit rõ ràng → tìm đúng.
- Test: tên chung/mơ hồ → confidence thấp → bỏ qua (không match nhầm).
- Đo tay vài công ty thật trước khi bật rộng.
