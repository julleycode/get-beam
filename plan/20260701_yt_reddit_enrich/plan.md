# Plan: Đọc YouTube + Reddit để làm giàu persona & cá nhân hoá email

**Ngày:** 2026-07-01
**Trạng thái:** 🟡 DRAFT — chờ duyệt
**Feature scope:** P1 → P4 (đã duyệt scope)

---

## 1. Mục tiêu (dễ hiểu)

Beam hiện **không có cách nào đọc nội dung YouTube / Reddit**. Thêm khả năng đó để:
- **(a)** Làm giàu hồ sơ khách (persona): nếu biết handle YT/Reddit của khách → hứng video/post gần đây vào hồ sơ.
- **(b)** Cá nhân hoá email campaign: email nhắc đúng nội dung thật khách/công ty vừa đăng → tỉ lệ phản hồi cao hơn.

## 2. Quyết định kỹ thuật quan trọng

**KHÔNG cài agent-reach-CLI.** Nó là vỏ bọc shell ra công cụ khác + kéo theo ~10 CLI thừa, không nhét sạch vào backend FastAPI. Thay vào đó dùng **thẳng ruột của nó**:
- **YouTube** → thư viện `yt-dlp` (import trực tiếp Python) — free, headless, chạy Railway OK.
- **Reddit** → endpoint public `.json` của reddit.com qua `httpx` — free, headless.

→ Cùng khả năng, ít điểm gãy hơn, chạy được trên prod (Railway). Xem lý do đầy đủ: memory [[proxycurl-dead-2026]] và phân tích agent-reach.

## 3. Bối cảnh code (đã research)

| Thứ | Vị trí | Ghi chú |
|---|---|---|
| Enrichment cascade | `apps/api/services/enricher.py` | PDL → (Proxycurl chết) → Twitter → deep_research |
| Nguồn handle social | PDL trả `linkedin_url`/`twitter_handle`; OSINT scan (`osint_scanner.py`) check account tồn tại | thường KHÔNG có handle YT/Reddit chính xác |
| Kho social context | `EnrichmentProfile.social_context` (JSONB) — `apps/api/models/enrichment.py:55` | **đã có sẵn, KHỎI migration** |
| Plug point campaign | `apps/api/agents/segmenter.py` `build_visitor_profiles()` (dòng 83-113) + `apps/api/routers/campaigns.py` (73-89) | nơi dựng dict đưa cho LLM |
| Prompt campaign | `apps/api/agents/campaign_planner.py:14-97` | thêm field nội dung vào đây |
| Gemini grounding (có sẵn) | `gemini_client.py` `grounding=True` | dùng cho P4 tìm kênh công ty |

## 4. Nguyên tắc (bắt buộc mọi phase)

- Feature-flag riêng, **default OFF** (giống các flag Beam khác: `enable_osint_scan`…).
- Chỉ chạy cho visitor **intent cao** (vd ≥60, như social_intelligence hiện tại).
- **Cache Redis** kết quả (TTL 7 ngày như enrichment) + **rate-limit** mỗi nguồn.
- **Mock mode**: tôn trọng `settings.mock_external_apis` → trả data giả (theo CLAUDE.md).
- Timeout 10s + retry 3 lần (theo convention `_http_retry`).
- **Không log nội dung thô/PII**; chỉ lưu snippet cần thiết vào `social_context`.
- Bọc `try/except` non-fatal: lỗi YT/Reddit **không được** làm hỏng enrichment/campaign.

## 5. Các phase (an toàn + ROI cao trước)

| Phase | Nội dung | Rủi ro | File |
|---|---|---|---|
| **P1** | Service `content_reader.py`: `fetch_youtube()` + `fetch_reddit()`, có cache/rate-limit/mock | 🟢 thấp | [phase-01.md](phase-01.md) |
| **P2** | (a) Nối vào enrichment: có handle → ghi vào `social_context` | 🟢 thấp | [phase-02.md](phase-02.md) |
| **P3** | (b) Đưa `social_context` vào prompt campaign | 🟢 thấp | [phase-03.md](phase-03.md) |
| **P4** | Tìm kênh công ty (subreddit/YouTube) khi thiếu handle | 🟡 vừa | [phase-04.md](phase-04.md) |

## 6. Ngoài phạm vi

- KHÔNG scrape LinkedIn/X bằng cookie account (rủi ro như [[proxycurl-dead-2026]]).
- KHÔNG cài agent-reach-CLI.
- Thay Proxycurl (LinkedIn) = plan riêng, không thuộc plan này.

## 7. Twitter/X enrichment (liên quan, quyết định riêng)

Prod `TWITTER_BEARER_TOKEN` **chưa set** → Twitter enrich đang tắt. App X ở **pay-per-use, còn $3.40**. Lựa chọn: (A) add token chính thức (~$0.01/lookup) hoặc (B) **TwitterAPI.io (~$0.00018/lookup, rẻ ~50×)**. → chờ user chốt; nếu (B) sẽ thêm thành phase phụ ở đây.
