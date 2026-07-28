# Lớp phát hiện AI-agent — kiến trúc & đánh giá

Cập nhật: 2026-07-29 · Phạm vi: tab **Agents** + **Visitors**
Nguồn: đọc trực tiếp source (không suy đoán) + 9 query đọc trên Postgres production

Mục đích: trả lời ba câu hỏi sản phẩm — (1) phân biệt đâu là AI, (2) ai là người đứng sau AI,
(3) làm sao dẫn người dùng AI click vào site và định danh được họ.

---

## 1. Bức tranh tổng thể

Beam có **năm lớp** nhận diện phi-người, độc lập nhau:

| Lớp | Module | Cơ chế | Trạng thái |
|---|---|---|---|
| 1 | `tracker.js` | Kiểm tra `webdriver` phía client | Đang chạy |
| 2 | `bot_filter.py` | Regex User-Agent, drop thẳng | Đang chạy |
| 3 | `agent_classifier.py` | Allowlist token vendor AI → phân loại thay vì drop | Cờ `agent_detection_enabled`, **mặc định TẮT** |
| 4 | `ingest_velocity.py` | Hình dạng traffic trong cửa sổ ngắn (flood) | Cờ, mặc định TẮT |
| 5 | `cadence_bot_flag.py` | **Hành vi theo thời gian** — độ đều nhịp + tỉ lệ tương tác | Cờ, mặc định TẮT |

Thứ tự trong ingest **đúng**: `classify_agent()` chạy **trước** `is_bot()`
([events.py:137-144](../apps/api/routers/events.py#L137-L144)), nên agent đã nhận diện không bị
drop nhầm. Nhưng khi `agent_detection_enabled` tắt, `classification = None` → agent rơi xuống
`is_bot()` → **bị drop im lặng**. Cờ tắt = không có dữ liệu agent nào từ đường pixel.

Lớp 5 (`cadence_bot_flag`) là thiết kế tốt nhất trong nhóm: trực giao với 4 lớp kia (không đọc
chuỗi định danh nào), yêu cầu **đồng thời** hai điều kiện (nhịp đều + tương tác thấp) nên
"người dùng chăm chỉ vào site mỗi sáng 9h" không bị bắt nhầm, và chỉ mang tính hiển thị —
không bao giờ chạm `is_emailable_identity`.

---

## 2. Hai đường ghi dữ liệu agent

| Đường | Nguồn | Ghi index-tier? | Ghi chú |
|---|---|---|---|
| Pixel ingest (`routers/events.py`) | JS trên site khách | Có | **Crawler không chạy JS** → đường này gần như không bao giờ thấy crawler |
| Beacon edge (`agent_fetch_beacon.py`) | Middleware getbeam.fyi, auth shared-secret | Có (từ 28-07) | Đường **duy nhất** quan sát được crawler |

Hệ quả quan trọng: với site khách dùng pixel, **crawler index-tier về cơ bản vô hình**. Beacon chỉ
chạy trên chính getbeam.fyi. Đây là giới hạn cấu trúc, không phải bug.

---

## 3. Ba tầng độ tin cậy định danh

`VERIFICATION_METHODS = ("ua-only", "ip-verified", "rdns-verified")`

`agent_verification.py` nâng `ua-only` → `ip-verified` bằng cách đối chiếu IP với dải CIDR tĩnh.

**Thiếu sót cấu trúc:** hàm chỉ biết **NÂNG**, không bao giờ **HẠ hay gắn cờ lệch**. Một UA giả
mạo GPTBot đến từ IP bất kỳ sẽ nằm nguyên ở `ua-only` — **không phân biệt được** với:

- Anthropic (không công bố dải IP → vĩnh viễn `ua-only` theo thiết kế)
- Agent thật nhưng chưa tới lượt sweep quét

Nghĩa là **Beam không phát hiện được UA giả mạo.** Không có trạng thái `spoofed`.

---

## 4. Ba câu hỏi sản phẩm — trả lời được tới đâu

### (1) Phân biệt đâu là AI — **một phần**

Nhận diện được 11 token vendor tự khai báo. Không phát hiện được giả mạo (mục 3). Dải IP để
xác minh chỉ có 5 CIDR OpenAI + 5 IP Perplexity, là file tĩnh commit trong repo, **không có cơ
chế làm mới**. OpenAI thực tế công bố **3 file riêng** cho GPTBot / OAI-SearchBot / ChatGPT-User;
Beam gộp thành một vendor `openai` duy nhất → mất khả năng phát hiện bất thường kiểu "GPTBot đến
từ dải của ChatGPT-User".

### (2) Ai đứng sau AI — **suy đoán, không định danh**

`agent_handoff_correlation.py` nối lượt fetch của agent với click của người theo **ba điều kiện
mềm**: cùng site + `referrer` khớp họ vendor + click trong 30 phút sau fetch. Không có mã định
danh nào. Hai người cùng hỏi ChatGPT về cùng trang trong 30 phút → gán nhầm, không phát hiện được.

Đã đo trên prod: 22 lượt fetch, 1 visitor có `ai_source`, **0 link** — và `0` là **đúng**, vì
không cặp nào từng thoả điều kiện.

### (3) Dẫn người dùng AI click vào và định danh — **xây xong mặt tiền, thiếu cả hai đầu**

Đã có: `llms.txt`, agent manifest, offers feed, MCP JSON-RPC server (3 tool đọc), agent profile do
khách tự soạn, chống dò `site_id` (5 trường hợp lỗi đều trả 404 giống nhau).

**Thiếu đầu ra:** link trong offers feed là URL trần — không mang mã nào để nhận ra khi có người
click vào.

**Thiếu đầu vào:** toàn bộ surface agent-facing (`agent_gateway.py`, `agent_mcp.py`,
`agent_profile.py`) **không ghi lại một lượt truy cập nào** — không có bất kỳ lời gọi
`persist_agent_visit` / `persist_agent_fetch_event` nào. Một AI gọi MCP server — tín hiệu chủ động
và rõ ràng nhất có thể về việc "một AI đang nghiên cứu doanh nghiệp này" — **không để lại dấu vết
nào trên tab Agents**.

---

## 5. Danh sách vấn đề còn mở

| Mã | Vấn đề | Mức | File |
|---|---|---|---|
| F11 | Surface agent-facing không ghi lại lượt truy cập nào | HIGH | `routers/agent_{gateway,mcp,profile}.py` |
| F12 | Không có trạng thái `spoofed` — chỉ nâng cấp, không phát hiện lệch | HIGH | `agent_verification.py` |
| F2 | Không có marker → "người sau AI" là suy đoán thời gian | HIGH | `services/agent_gateway.py` |
| F13 | Dải IP nhỏ, gộp vendor, tĩnh, không làm mới | MEDIUM | `data/agent_ip_ranges/` |
| F14 | Chưa có Web Bot Auth (RFC 9421) — chữ ký mã hoá, miễn phí, mạnh nhất hiện có | MEDIUM | — |
| F10 | `agent_fetch_events` không có ràng buộc chống trùng | MEDIUM | `models/agent_fetch_event.py` |
| F3 | Phân loại không tất định (`frozenset` + hash ngẫu nhiên mỗi process) | MEDIUM | `agent_classifier.py` |
| F4 | Khớp chuỗi con không có biên từ | MEDIUM | `agent_classifier.py:90` |
| F5 | Sweep ghi link quá sớm, khoá mất bản khớp tốt hơn | MEDIUM | `agent_handoff_correlation.py` |
| F6 | Query ứng viên không `LIMIT`, trong vòng lặp 20 lần | MEDIUM | `agent_handoff_correlation.py` |
| F8 | `_VENDOR_FAMILY_MAP` thiếu key `google` — bẫy ngầm khi mở rộng | LOW |

**F14 đáng chú ý nhất về mặt cơ hội:** Web Bot Auth đã được Anthropic, OpenAI, Perplexity,
Common Crawl hỗ trợ. Nó là chữ ký mã hoá, tất định, miễn phí, không phụ thuộc tier Cloudflare —
và giải được đúng chỗ Anthropic đang bế tắc (không công bố dải IP nên vĩnh viễn kẹt ở `ua-only`,
nhưng **có** ký).

---

## 6. Đã sửa (28-07)

- **Tier searchbot** — `oai-searchbot` và `claude-searchbot` từng bị xếp `on-demand` ("có người
  thật đứng sau"). Doc vendor nói cả hai là crawler index. 32% lượng on-demand trên prod là
  crawler. Đã chuyển sang `index`, và beacon nay ghi cả index-tier (trước đó bỏ qua hoàn toàn).
- **Số `0` đọc hiểu được** — dashboard hiện `N of M live agent fetches` kèm phân tách
  strong/likely và câu giải thích cho trường hợp 0.
- **Job sweep khởi động sớm** — job store nằm trong bộ nhớ nên mỗi lần restart tính lại lần bắn
  đầu là boot + 10 phút; process restart nhanh hơn thế thì sweep không bao giờ chạy. Đã thêm
  `next_run_time` +30 giây.

---

## 7. Điểm làm tốt (không nên đụng vào)

- **Guardrail loại trừ agent khỏi outreach** thực thi nhất quán: `agent_handoff_correlation.py`
  không import bất kỳ đường ghi identity nào, có test tripwire riêng
  (`test_handoff_emailability_separation.py`).
- **`agent_visitor_filters.py`** — một choke point duy nhất loại visitor tổng hợp khỏi mọi truy
  vấn dữ liệu người. Đúng DRY.
- **`agent_mcp.py`** — 4 lớp guard (rate limit, cap body kiểm 2 lần, allowlist method nghiêm,
  không phản chiếu input). Viết chắc.
- **`agent_intent_signals.py`** — tín hiệu chỉ ở mức site, không bao giờ khẳng định cấp cá nhân.
- **Đa tenant** — site lạ/không tồn tại đều trả 404 giống nhau, không rò rỉ sự tồn tại của id.

---

## 8. Cờ tính năng — tất cả mặc định TẮT

`agent_detection_enabled`, `agent_gateway_enabled`, `cadence_bot_flag_enabled`,
`site_ingest_limit_enabled`, `ingest_velocity_enabled`, `company_graph_enabled`,
`identity_signals_enabled`.

Bật cờ **trước khi** apply migration lên production sẽ crash. Không có guard nào ở code chặn
việc này — đây là quy trình vận hành thủ công.

---

## Câu hỏi chưa giải quyết

1. **F11 và F2 nên gộp làm một không?** Cả hai đều là chuyện "surface agent-facing chưa khép vòng":
   một đầu không ghi lại, một đầu không định danh được. Sửa rời sẽ chạm cùng file.
2. **Có làm Web Bot Auth (F14) không?** Đây là thay đổi lớn nhất về năng lực nhưng cũng là việc
   mới hoàn toàn, không phải sửa lỗi.
3. **Dải IP tĩnh làm mới thế nào?** Hiện commit trong repo. Cron kéo về, hay chấp nhận cũ?
4. `routers/visitors.py` (1314 dòng) và 2 trang dashboard mới đọc phần giao với agent, **chưa
   review từng dòng**. Đánh giá trên chưa phủ tab Visitors ở mức chi tiết.
