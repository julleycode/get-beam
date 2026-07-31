# Brainstorm — Phản biện phân tích kiến trúc của ChatGPT + gap giao marker tới AI

Ngày: 2026-07-31 | Nhánh: `dev_nhantc2` | Mode: brainstorm (không implement)
Site: Beam Lab `site_16c46453546f` — https://beamlab.nhantown.com

---

## 1. Bối cảnh

User dán một bản phân tích kiến trúc do ChatGPT viết (edge pixel vs JS pixel, đề xuất
per-fetch marker ID), yêu cầu đánh giá. Song song: quan sát "link ChatGPT cite vẫn chưa có
marker".

## 2. Bằng chứng live thu được trong phiên

Sau khi wipe data test và bật `HANDOFF_CORRELATION_SETTLE_SECONDS=60`:

```
11:34:33  FETCH on-demand  /            chatgpt-user
11:34:35  FETCH on-demand  /llms.txt    chatgpt-user
11:34:39  FETCH on-demand  /            chatgpt-user
11:37:10  CLICK pageview   /            referrer=https://chatgpt.com/
11:38:49  LINK  high   157s  /
11:38:49  LINK  medium 155s  /llms.txt
11:38:49  LINK  high   151s  /
```

Kết luận:
- Handoff detection **chạy đúng end-to-end**. Lần đầu ra `high` (2 link).
- `settle_seconds=60` hoạt động: link xuất hiện ~1.5 phút sau click (trước là ~31 phút).
- Marker **không cần thiết** để attribution hoạt động — referrer đủ dùng khi nó về được.

### Đính chính 2 nhận định sai của phiên trước

| Nhận định cũ | Thực tế |
|---|---|
| "`high` gần như không bao giờ xuất hiện, strong matches mãi = 0" | Sai. Ra 2 link `high` (151s, 157s). |
| "Data gợi ý nên nới `_HIGH_DELTA_SECONDS` 300 → 600" | **Rút lại.** Phân bố thật: 151/155/157/378/918s. Quá rộng để kết luận; ngưỡng hiện tại đang phân loại đúng. |

## 3. Đánh giá bản phân tích của ChatGPT

Phân bổ giá trị ước lượng: **~85% mô tả lại cái đã có, ~10% code mẫu kém hơn bản hiện tại,
~5% giá trị thật.**

### 3.1 Phần đúng nhưng là echo

ChatGPT đọc chính trang beamlab (trang tự mô tả kiến trúc 3 lớp) rồi trình bày lại như đề
xuất mới. Bảng "Edge tracker / JS pixel / Marker URL" trùng khớp cái đang chạy. Không có
quyền truy cập code nên mọi "đề xuất" đều suy ra từ marketing copy của chính user.

### 3.2 Code middleware mẫu — thiếu 3 thứ bản hiện tại đã có

Đối chiếu `infra/cloudflare/beam-lab/functions/_middleware.js` (79 dòng):

| Bản hiện tại | ChatGPT | Hậu quả nếu theo ChatGPT |
|---|---|---|
| `STATIC_EXT_RE` lọc css/js/ảnh/font | thiếu | 1 lượt AI đọc trang → cả tá dòng; `page_paths` thành rác |
| Tách `on-demand` vs `index` crawler (loại GPTBot/ClaudeBot/PerplexityBot khỏi beacon) | gộp chung | Tín hiệu "có người đang chờ" bị chôn dưới traffic robot |
| `next()` gọi trước, beacon sau | beacon trước, `next()` cuối | Chậm hơn (nhỏ) |
| Payload gửi: `site_id + user_agent + path` | thêm `ip/asn/colo/referrer` | Nhiều PII hơn — ngược với lời hứa privacy của sản phẩm |

### 3.3 Ý tưởng marker — đã build 29-07 (F2), và chặt hơn hẳn

| Khía cạnh | ChatGPT đề xuất (`/r/ai_01K1ABCXYZ`) | Beam đã làm (`?_bam=`) |
|---|---|---|
| Mã hoá | ID trần | Fernet |
| Hết hạn | không | TTL 7 ngày |
| Chống replay cross-tenant | không | Query kiểm tra fetch thuộc đúng site |
| **Cache posture** | **không nhắc tới** | Bật cờ → `offers.json` chuyển `private, no-store` |
| Trùng click | không | Unique constraint `uq_agent_handoff_links_fetch_event`, "click đầu thắng" |

Bỏ qua cache là **lỗi chí mạng**: `offers.json` mặc định `s-maxage=3600`. Marker theo-từng-lượt-fetch
mà để shared cache → CDN phát marker của agent A cho mọi agent sau → gán sai người, tệ hơn
cái đoán theo thời gian mà nó thay thế. Chi tiết: `docs/agent-detection-architecture.md` §7 ràng buộc 1.

### 3.4 Một điểm ChatGPT nói ĐÚNG mà Beam thiếu thật

> "referral từ ChatGPT Search hiện có thể mang `utm_source=chatgpt.com`"

Verify bằng grep: `apps/api/services/ai_referral.py` và `agent_handoff_correlation.py`
**không đọc `utm_source`** ở đâu cả — chỉ đọc `document.referrer`.

Gap thật. Chưa lộ vì hôm nay referrer về được, nhưng lần test sáng 31-07 (11:33) referrer
**rỗng** — đúng tình huống `utm_source` sẽ cứu.

### 3.5 Điểm đúng về sản phẩm, không phải kỹ thuật

Đề xuất tách tên gọi "Beam Edge Pixel" vs "Beam Browser Pixel". Kỹ thuật đã đúng, nhưng
naming trong code lẫn docs đang lộn xộn (pixel / middleware / beacon / tracker dùng lẫn).
Có giá trị bán hàng thật.

## 4. Root cause: vì sao link chưa có marker

Chuỗi nhân quả, đã verify từng mắt:

1. Marker `?_bam=` **chỉ** đóng vào URL trong `/api/v1/agent/{site_id}/offers.json`
2. `llms.txt` và `manifest.json` **cố ý** không mang marker (giữ cache — §7 ràng buộc 1)
3. `infra/cloudflare/beam-lab/public/llms.txt` (29 dòng) **không nhắc tới offers feed**
4. ChatGPT chỉ fetch `/robots.txt`, `/`, `/llms.txt` — xác nhận qua `agent_fetch_events`
5. → ChatGPT không có đường nào biết offers feed tồn tại → không thể nhận marker

**Không phải lỗi thiết kế marker. Là thiếu wiring ở llms.txt của beam-lab.**

Hệ quả: gap `Marker survival trên AI thật` (OPEN trong `docs/agent-detection-architecture.md` §5)
**vẫn chưa được kiểm chứng** — tưởng đã test nhưng marker chưa bao giờ tới tay ChatGPT.

## 5. Các hướng đã cân nhắc

| | Hướng | Ưu | Nhược |
|---|---|---|---|
| **A** | Quảng bá offers feed trong `llms.txt` | Rẻ, đảo ngược được, đóng được gap đang OPEN | Feed khác host; ChatGPT có thể không fetch |
| B | Đọc `utm_source` fallback khi referrer rỗng | Vá đúng ca hỏng thật; không phụ thuộc AI giữ marker | Vẫn xác suất; đụng đường ghi `first_touch_referrer` |
| C | Đóng marker vào chính HTML/`llms.txt` | Marker chắc chắn tới tay AI | Phải bỏ cache (`no-store`); cloaking → rủi ro SEO; đắt nhất |

**Chọn: A.** B là việc độc lập, giá trị riêng, làm sau. C chỉ bàn nếu A chứng minh ChatGPT
chịu fetch offers feed.

## 6. Blocker phát hiện khi thiết kế chi tiết A

```
agent_gateway_enabled = True   OK
agent_marker_enabled  = True   OK
agent_profiles        = 0 dòng BLOCKER
```

Route offers.json yêu cầu `AgentProfile.enabled`. Bảng rỗng → **404**. Thêm link vào llms.txt
lúc này = quảng bá URL hỏng, tệ hơn không làm gì.

Ghi chú: bảng này rỗng từ trước, KHÔNG do lệnh xoá data test trong phiên (lệnh đó chỉ đụng
`events`, `visitors`, `agent_visits`, `agent_fetch_events`, `agent_handoff_links`, `companies`).

→ **A không phải "2 dòng" như ước lượng ban đầu. Là 3 bước.**

## 7. Giải pháp chốt — Option A (3 bước)

**Bước 1 — Tạo Agent Profile** (user tự làm, việc nhập liệu không phải code)
- UI có sẵn: `/dashboard/agent` → `apps/web/src/app/dashboard/agent/page.tsx`
- Bật `enabled`
- Thêm ≥1 offer, URL **cùng host**: `https://beamlab.nhantown.com/...`
- Ràng buộc same-host: `docs/agent-detection-architecture.md` §7 ràng buộc 2 — link bên thứ ba
  không chạy pixel Beam nên marker ở đó không đọc lại được

**Bước 2 — Trỏ feed trong llms.txt**
- File: `infra/cloudflare/beam-lab/public/llms.txt`, mục `## Liên kết`
- Thêm: `https://beam-api.nhantown.com/api/v1/agent/site_16c46453546f/offers.json`
- Deploy lại Pages

**Bước 3 — Test + đo**

## 8. Rủi ro

| Rủi ro | Mức | Ghi chú |
|---|---|---|
| Feed khác host (`beam-api` ≠ `beamlab`) → ChatGPT không fetch cross-domain | **Cao** | Điểm dễ chết nhất của A |
| ChatGPT fetch offers nhưng vẫn cite URL canonical trần | Trung bình | Hành vi quan sát được hôm nay |
| `site_id` lộ trong llms.txt công khai | Thấp | Đã nằm sẵn trong snippet pixel trên trang |
| Bẫy shared-cache phát marker chéo | **Đã tránh** | `agent_marker_enabled=True` → `offers.json` đã `no-store` |

## 9. Tiêu chí nghiệm thu

1. `GET /api/v1/agent/site_16c46453546f/offers.json` trả 200 (không phải 404)
2. Sau khi hỏi ChatGPT: `agent_fetch_events` có dòng `page_path` chứa `offers.json`
3. Nếu (2) đạt: link ChatGPT cite mang `?_bam=`
4. Nếu (3) đạt: `agent_handoff_links` có dòng `method='marker'`, `confidence='high'`

**Kết quả âm ở bước 2 hoặc 3 vẫn là kết quả có giá trị** — đóng gap `Marker survival trên AI thật`
bằng câu trả lời dứt khoát thay vì để treo.

## 10. Việc còn lại / phụ thuộc

- [ ] **User**: tạo Agent Profile qua `/dashboard/agent` (chặn bước 2)
- [ ] Sửa `llms.txt` + deploy Pages
- [ ] Chạy test, ghi kết quả vào `docs/agent-detection-architecture.md` §5
- [ ] (Riêng, chưa lên lịch) Option B — `utm_source` fallback trong `ai_referral.py`
- [ ] (Riêng) Dọn `.env`: xoá `HANDOFF_CORRELATION_SWEEP_INTERVAL_MINUTES=1` và
      `HANDOFF_CORRELATION_SETTLE_SECONDS=60` trước khi lên production

## 11. Thay đổi code đã thực hiện trong phiên (ngoài phạm vi brainstorm)

| File | Nội dung |
|---|---|
| `apps/api/config.py` | thêm `handoff_correlation_settle_seconds: int = 1800` |
| `apps/api/services/agent_handoff_correlation.py` | tách thời gian chờ khỏi cửa sổ tương quan + clamp chống sweep chết âm thầm |
| `tests/unit/test_agent_verification.py` | fixture `empty_runtime_dir` — cô lập 2 test khỏi output của job refresh IP-range |

Test: `tests/unit` → 1512 passed, 2 skipped, 0 failed. Chưa commit.

---

## Câu hỏi chưa giải quyết

1. ChatGPT có chịu fetch URL khác host từ llms.txt không? Chỉ đo được, không suy luận được.
2. Nếu ChatGPT fetch offers feed nhưng vẫn rewrite link về canonical — marker có còn đường
   nào tới người dùng không, hay phải chấp nhận attribution mãi là xác suất?
3. Option B (`utm_source`) nên đặt ở đâu: `ai_referral.classify_ai_source()` nhận thêm tham số,
   hay một hàm riêng? Ảnh hưởng `first_touch_referrer` cần thiết kế trước khi làm.
