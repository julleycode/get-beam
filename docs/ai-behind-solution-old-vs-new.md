# Giải pháp “người đứng sau AI” — cách cũ vs cách mới

Cập nhật: 2026-07-30  
Phạm vi: SA attribution / handoff (không phải outreach, không phải auto-send)  
Đọc kèm: [agent-detection-architecture.md](./agent-detection-architecture.md)

---

## 1. Bài toán thật sự là gì

Beam đã biết tách hai sự kiện:

1. **Một AI vừa fetch trang** (ChatGPT-User, ClaudeBot, Perplexity…) — lưu trong `agent_fetch_events` / `agent_visits`.
2. **Một người vừa vào site** từ referrer AI — lưu trong `visitors` với `ai_source`.

Hai sự kiện đó **không tự nối**. “Người đứng sau AI” trong SA của Beam nghĩa là:

> Nối đúng **một lượt fetch của AI** với **một visitor người** đã click vào site sau khi AI trả lời — rồi (bước sau) đưa visitor đó vào máy **identity resolution** sẵn có để ra công ty / (hiếm) người.

Kỳ vọng đúng của sản phẩm:

| Kỳ vọng | Thực tế SA hỗ trợ |
|---|---|
| “ChatGPT đang đọc pricing cho **công ty X**” | Có hướng tới (attribution + resolution) |
| “**John Smith** vừa hỏi ChatGPT về pricing” | Chỉ khi người đó để lại email / form — không suy ra từ UA bot |

Không click → không có “người” để nối. Đọc câu trả lời trong app ChatGPT mà không bấm link = `handoff_links = 0` (đúng thiết kế).

---

## 2. Kiến trúc tổng (cả cũ lẫn mới đều nằm trong đây)

```text
┌─────────────────────────────────────────────────────────────────┐
│  Tầng A — DETECT                                                │
│  classify_agent → verify_ip (F12/F13) → [F14 Web Bot Auth sau]  │
│  Ghi: agent_fetch_events, agent_visits                          │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│  Tầng B — ATTRACT + ATTRIBUTE                                   │
│  Gateway: llms.txt / offers.json / MCP                          │
│  Nối AI ↔ người:                                                │
│    • Cách CŨ  = temporal sweep (đoán theo thời gian)            │
│    • Cách MỚI = marker F2 ?_bam= (tất định theo fetch id)       │
│  Ghi: agent_handoff_links + Visitor.ai_source                   │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│  Tầng C — IDENTIFY (chưa nối từ B)                              │
│  resolution_runner → identity_resolver (PDL / Proxycurl…)       │
│  Ghi: identified_visitors                                       │
│  Hiện: xếp hàng theo intent_score, không ưu tiên handoff        │
└─────────────────────────────────────────────────────────────────┘
```

Cách cũ và cách mới **chỉ khác nhau ở tầng B** (cách nối fetch ↔ click).  
Tầng A và tầng C dùng chung. Marker **không** thay identity resolution — nó chỉ làm attribution chắc hơn trước khi resolution chạy.

Guardrail cố ý (cả hai cách): handoff là metadata attribution trên bảng riêng; **không** biến bản ghi agent thành emailable lead.

---

## 3. Cách cũ — Temporal correlation (suy đoán thời gian)

### Ý tưởng

Khi AI (on-demand) fetch trang X lúc T, và sau đó một người click vào cùng site với referrer thuộc “họ” vendor đó trong cửa sổ thời gian → coi như cùng một phiên hỏi đáp.

Module: `apps/api/services/agent_handoff_correlation.py`  
Bảng: `agent_handoff_links` với `method` kiểu temporal / confidence `high` | `medium`.

### Điều kiện khớp (v1)

1. Fetch **on-demand** (không dùng index-crawler để suy “người đứng sau”).
2. Click cùng `site_id`.
3. `ai_source` / referrer khớp họ vendor (`openai`↔`chatgpt`, `anthropic`↔`claude`, …).
4. Click xảy ra **sau** fetch, trong cửa sổ **30 phút** (`_WINDOW_SECONDS = 1800`).
5. Fetch chỉ được xét sau khi cửa sổ đóng (tránh chốt sớm một click yếu rồi khóa vĩnh viễn).
6. Lookback quét ~180 phút để một lần sweep miss không làm fetch “chết” im lặng.

Độ tin cậy:

| Confidence | Điều kiện đại khái |
|---|---|
| `high` | Đúng trang + cùng họ vendor + delta ≤ ~5 phút |
| `medium` | Cùng họ + trong 30 phút nhưng không đủ điều kiện high |
| `low` | Ngoài cửa sổ → **không ghi** (v1 ưu tiên precision) |

### Điểm mạnh

- Không cần đổi URL / offers / tracker.
- Chạy được ngay khi đã có pixel + `ai_source` + fetch events.
- Phù hợp traffic “người hỏi AI rồi bấm link thường” (không qua offers feed).

### Điểm yếu (lý do có cách mới)

- **Không tất định.** Hai người hỏi ChatGPT cùng trang trong 30 phút → có thể gán nhầm; hệ thống không biết mình sai.
- **Phụ thuộc referrer.** Nhiều trình duyệt / in-app browser cắt referrer → mất ứng viên.
- **Phụ thuộc cửa sổ thời gian.** Click chậm / đọc lâu / mở tab sau → dễ rơi khỏi cửa sổ hoặc chỉ còn medium.
- **Race với sweep.** Trước khi sửa F5, click sớm yếu có thể “chiếm chỗ” trước click đúng trang.
- **Không chứng minh được** click xuất phát từ đúng lượt fetch cụ thể — chỉ chứng minh “có vẻ cùng phiên”.

Trên prod từng đo: nhiều fetch, gần như **0 link** — thường vì không thỏa cửa sổ / referrer, không phải vì code “hỏng”.

---

## 4. Cách mới — Marker F2 (`?_bam=`) tất định

### Ý tưởng

Beam kiểm soát đầu ra `offers.json`. Khi AI kéo offers, lượt fetch đã có id trong `agent_fetch_events`. Id đó được **mã hoá Fernet** thành marker, đóng vào URL cùng host dạng:

```text
https://customer.example/pricing?_bam=<token>
```

Người click link đó → pixel gửi pageview URL như mọi lần → server đọc `_bam` (giống `_tp` campaign) → giải mã về **đúng** `fetch_event_id` → ghi `agent_handoff_links` với:

- `method = "marker"`
- `confidence = "high"`

Module: `apps/api/services/agent_marker.py` (+ stamp trong `agent_gateway` khi phục vụ offers).  
Cờ: `agent_marker_enabled` (mặc định TẮT) + cần `ENCRYPTION_KEY`.

### Chuỗi end-to-end

```text
AI GET /agent/offers.json
  → record_gateway_visit / persist_agent_fetch_event  (có fetch_event_id)
  → mint_marker(fetch_event_id)
  → stamp_marker() chỉ lên URL cùng host
  → Cache-Control: private, no-store   (bắt buộc khi có marker)

AI đưa link có ?_bam= cho người dùng
Người click trong TTL (7 ngày Fernet)

Pixel pageview URL chứa _bam
  → record_marker_handoff()
  → decode → kiểm tra fetch thuộc đúng site (chống replay chéo tenant)
  → INSERT/upgrade agent_handoff_links (marker thắng temporal)
```

### Ràng buộc cố ý

1. **Chỉ stamp URL cùng host** — link bên thứ ba không có pixel Beam → marker vô dụng.
2. **TTL 7 ngày** — link forward/bookmark cũ giải mã ra rỗng, không bịa attribution.
3. **Marker định danh FETCH, không định danh người** — mint trước khi có người; mọi người nhận cùng câu trả lời AI mang cùng marker; unique trên fetch → **click đầu thắng**.
4. **Bật marker = đổi cache offers** sang `private, no-store` — shared cache phát marker của agent A cho agent B sẽ gán sai người (tệ hơn đoán).
5. **Tenancy check** — decode thành công chỉ chứng minh token do deployment mint; phải chứng minh fetch thuộc đúng site đang báo click (AC-H2-5).

### Điểm mạnh

- Tất định: biết **đúng** lượt fetch, không đoán cửa sổ.
- Không sửa `tracker.js`.
- Marker ghi đè link temporal yếu hơn khi cùng fetch đã có đoán.
- Dashboard có thể chẩn đoán 0 link (`expired` vs `invalid` vs `absent`).

### Điểm yếu / giả định mở

- Chỉ mạnh trên đường **offers / link Beam kiểm soát**. Link trần trong HTML không stamp vẫn chỉ còn cách cũ.
- **Phụ thuộc AI giữ nguyên query param** khi show link cho người — chưa chứng minh ngoài lab (câu hỏi mở #1).
- Cần bật cờ + `ENCRYPTION_KEY` + agent profile / offers có nội dung đáng click.
- Không click → vẫn 0 handoff (giống cách cũ).

---

## 5. So sánh trực diện

| Tiêu chí | Cách cũ (temporal) | Cách mới (marker F2) |
|---|---|---|
| Câu hỏi trả lời | “Có vẻ cùng phiên AI không?” | “Click này từ **đúng** lượt fetch nào?” |
| Bằng chứng | Thời gian + referrer + trang | Token mã hoá id fetch trên URL |
| Độ tin cậy | medium / high (suy đoán) | high (tất định) khi decode + tenancy OK |
| Phụ thuộc referrer | Có | Không (miễn pixel gửi URL có `_bam`) |
| Phụ thuộc cửa sổ 30′ | Có | Không (TTL 7 ngày riêng) |
| Phụ thuộc offers feed | Không | Có (đường mint chính) |
| Phụ thuộc AI giữ `?_bam=` | Không | Có — **rủi ro sản phẩm lớn nhất** |
| Sửa tracker | Không | Không |
| Đụng cache | Không | Có — `offers.json` → `private, no-store` |
| Sai gán khi 2 người cùng hỏi | Có thể | Cùng marker → click đầu thắng (rõ ràng hơn, vẫn không ra 2 người) |
| Chống replay chéo tenant | Luật sweep | Decode + query ownership fetch |
| Trạng thái | Đã ship, luôn chạy nền | Đã ship, **cờ mặc định TẮT** |
| “Xác định tên người”? | Không | Không — chỉ attribution |

**Quan hệ giữa hai cách:** không thay thế loại trừ. Temporal vẫn là lưới an toàn cho click không qua offers. Marker là đường ưu tiên khi Beam kiểm soát được URL. Khi cả hai cùng trỏ một fetch, **marker thắng**.

---

## 6. Phần còn thiếu sau cả hai cách (tầng C)

Cả cách cũ lẫn cách mới **dừng ở attribution**:

```text
agent_handoff_links  ✓
Visitor.ai_source    ✓
identified_visitors  ✗  (probe live = 0)
```

Lý do kiến trúc:

1. Marker / sweep **cố ý không** gọi identity write path (emailability separation).
2. `resolution_runner` xếp hàng theo `intent_score` — **không** ưu tiên visitor có handoff / `ai_source`.
3. Provider keys (PDL / Proxycurl / …) trống trên nhiều môi trường → waterfall không có gì để resolve.

Vì vậy: “bắt được AI” và “biết click đến từ AI nào” **đã có hướng**; “biết đó là công ty / người nào” là **bước kế tiếp**, không nằm trong diff old vs new của handoff.

---

## 7. Mặt tiền khiến cách mới có việc để làm

Không có gì để AI đọc / click thì marker không bao giờ được mint trong thực tế:

| Surface | Vai trò |
|---|---|
| `llms.txt` | Hướng AI tới nội dung / offers |
| `manifest.json` | Khai báo agent-facing |
| `offers.json` | **Nơi mint `?_bam=`** |
| MCP tools | AI hỏi có chủ đích; ghi sổ theo tên tool |
| Agent profile (CRUD chủ site) | Nội dung offers do khách soạn |

Đã kiểm chứng: ChatGPT-User on-demand thật đọc `/` → `/llms.txt` → `/`. Chuỗi attract đang sống; chuỗi marker→click→identity vẫn cần wild test + tầng C.

---

## 8. Nên làm gì (theo đúng SA, không lan man)

1. **Wild marker survival** — bật gateway + marker trên lab/prod, hỏi ChatGPT/Claude về trang có offers, xem link còn `?_bam=` khi người nhìn thấy / click. Nếu strip → F2 âm thầm về 0; quay lại temporal + đổi hướng attract.
2. **Đảm bảo có click** — CTA rõ trong offers; đọc in-app không tạo handoff.
3. **Nối tầng C** — ưu tiên visitor có handoff/`ai_source` trong budget resolution; điền provider keys. Kỳ vọng: công ty trước, người sau.
4. **F14 Web Bot Auth** — sau (1); chứng minh AI thật (đặc biệt Anthropic), không thay bước identity.
5. Giữ temporal chạy song song — lưới cho traffic không qua offers.

---

## 9. Tóm một câu

**Cách cũ** đoán “cùng phiên” bằng đồng hồ và referrer.  
**Cách mới** đóng mã lượt fetch vào link Beam kiểm soát rồi đọc lại khi người click.  
Cả hai chỉ trả lời “AI nào dẫn người nào tới site”; bước “người/công ty đó là ai” vẫn là identity resolution tách biệt — và đó là đoạn source đang **chưa ưu tiên nối** sau handoff.

---

## Tham chiếu code

| Vai trò | Path |
|---|---|
| Temporal sweep | `apps/api/services/agent_handoff_correlation.py` |
| Marker mint/decode | `apps/api/services/agent_marker.py` |
| Gateway / offers | `apps/api/services/agent_gateway.py` |
| Pixel decode hook | `apps/api/routers/events.py` (đọc `_bam` trên URL pageview) |
| AI referrer label | `apps/api/services/ai_referral.py` |
| Resolution queue | `apps/api/services/resolution_runner.py` |
| Đánh giá kiến trúc | [agent-detection-architecture.md](./agent-detection-architecture.md) |
| Journal kiểm chứng live | [journals/260730-1126-ai-detection-live-validation.md](./journals/260730-1126-ai-detection-live-validation.md) |
