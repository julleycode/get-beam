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

**Đầu ra — đã sửa 29-07 (F2).** Trước đó link trong offers feed là URL trần, không mang mã nào để
nhận ra khi có người click. Nay mỗi URL cùng host mang `?_bam=<marker>` mã hoá id của chính lượt
fetch đã phát nó ra (chi tiết + 4 ràng buộc: mục 6). Cờ `agent_marker_enabled`, mặc định TẮT.

**Đầu vào — đã sửa 29-07 (F11).** Trước đó toàn bộ surface agent-facing không ghi lại một lượt
truy cập nào. Nay `record_gateway_visit()` trong `services/agent_gateway.py` ghi vào đúng hai bảng
agent-only, gắn nhãn theo surface:

| Route | Nhãn lưu vào `page_path` |
|---|---|
| `manifest.json` | `/agent/manifest.json` |
| `offers.json` | `/agent/offers.json` |
| `llms.txt` | `/agent/llms.txt` |
| MCP `tools/list` | `/agent/mcp/tools-list` |
| MCP gọi tool | `/agent/mcp/{tên_tool}` — biết được AI **hỏi gì** |

Ghi đặt **sau** cổng allowlist nên lệnh gọi bị từ chối không bao giờ lọt vào bảng, và nhãn luôn là
hằng số hoặc key đã kiểm trong `MCP_TOOLS` — không bao giờ là text do người gọi kiểm soát. Bọc
try/except toàn bộ vì đây là route đọc công khai không auth: lỗi ghi sổ không được biến một lượt
fetch manifest thành 500.

`routers/agent_profile.py` **không** nằm trong phạm vi này — nó là CRUD của chủ site
(`Depends(get_current_user)`), không phải surface cho agent.

**Giới hạn còn lại (known gap):** chỉ ghi khi UA khớp allowlist vendor. Một MCP client có UA
chung chung (phần lớn client MCP) vẫn vô hình — vì không có vendor nào để quy về, và bịa ra một
vendor sẽ làm hỏng thống kê vendor đang có. Đây là lựa chọn có ý thức, không phải bỏ sót.

---

## 5. Danh sách vấn đề còn mở

| Mã | Vấn đề | Mức | File |
|---|---|---|---|
| F12 | Không có trạng thái `spoofed` — chỉ nâng cấp, không phát hiện lệch | HIGH | `agent_verification.py` |
| F2 | Không có marker → "người sau AI" là suy đoán thời gian | HIGH | `services/agent_gateway.py` |
| F14 | Chưa có Web Bot Auth (RFC 9421) — chữ ký mã hoá, miễn phí, mạnh nhất hiện có | MEDIUM | — |

Còn lại một cái **chưa làm**:

| Mã | Vướng ở đâu |
|---|---|
| F14 | Implement RFC 9421 từ đầu: đọc header `Signature-Agent`, lấy public key tại `/.well-known/http-message-signatures-directory`, verify chữ ký + timestamp, cache key. Nhiều ngày, cần plan riêng |

**F14 đáng chú ý nhất về mặt cơ hội:** Web Bot Auth đã được Anthropic, OpenAI, Perplexity,
Common Crawl hỗ trợ. Nó là chữ ký mã hoá, tất định, miễn phí, không phụ thuộc tier Cloudflare —
và giải được đúng chỗ Anthropic đang bế tắc (không công bố dải IP nên vĩnh viễn kẹt ở `ua-only`,
nhưng **có** ký).

---

## 6. Đã sửa (28-07 → 29-07)

- **F2 — "người sau AI" nay tất định, không còn đoán theo thời gian.** Khi agent kéo
  `offers.json`, lượt fetch đó đã được ghi thành một dòng `agent_fetch_events`; id của nó được
  **mã hoá Fernet** thành marker và đóng vào từng `offer.url`. Người click link đó đáp xuống site
  có pixel kèm `?_bam=...`, server đọc marker từ URL pageview y như `_tp_from_url()` đang làm, giải
  mã ngược về **đúng** lượt fetch, ghi `agent_handoff_links` với `method="marker"`,
  `confidence="high"`. Không cần migration, **không sửa `tracker.js`**, cờ `agent_marker_enabled`
  mặc định TẮT. Bốn ràng buộc cố ý:
  1. **Bật cờ = đổi luôn posture cache của `offers.json`** sang `private, no-store`. Marker là
     theo-từng-lượt-fetch, mà `AGENT_CACHE_CONTROL` đang là `s-maxage=3600,
     stale-while-revalidate=86400` → shared cache sẽ phát marker của agent đầu cho mọi agent phía
     sau và **gán sai người** — tệ hơn hẳn cái đoán mà nó thay thế. `manifest.json` và `llms.txt`
     giữ nguyên cache vì không mang marker (có test chặn rò rỉ chéo — `llms.txt` render cùng
     `build_offers`).
  2. **Chỉ đóng dấu URL cùng host với site.** Link bên thứ ba không chạy pixel Beam nên marker ở
     đó không bao giờ đọc lại được.
  3. **Marker hết hạn sau 7 ngày** (TTL của Fernet, không cần lưu state). Link forward lại sau
     nhiều tuần giải mã ra rỗng thay vì bịa một attribution.
  4. **Marker định danh một LƯỢT FETCH, không phải một người.** Nó được mint trước khi có người
     nào, giống hệt nhau cho mọi người nhận câu trả lời của agent đó; unique constraint
     `uq_agent_handoff_links_fetch_event` khiến "click đầu thắng" thành ràng buộc cấu trúc.
  Marker **ghi đè** link tạm do sweep đoán ra (nó là sự thật mà sweep đang xấp xỉ), nhưng không
  bao giờ ghi đè một marker link khác.

- **F10 — `agent_fetch_events` nay chống ghi trùng.** Cột `dedup_key` (sha256, nullable) +
  **partial** unique index `WHERE dedup_key IS NOT NULL`, migration `c1e7a94f3d28`.
  Hai điều chỉnh so với hình dung ban đầu:
  1. **Không cần dọn dữ liệu prod trước.** Trong Postgres NULL không xung đột với nhau, mà mọi
     dòng cũ đều có key NULL → index không thể fail khi tạo. Thứ tự "dọn rồi mới khoá" không còn
     áp dụng.
  2. **Khoá tổ hợp trên cột sẵn có sẽ vô dụng.** `created_at` mặc định `now()` ở mức micro-giây,
     nên bản ghi bị replay rơi vào timestamp khác và lọt qua mọi constraint chứa nó. Khoá phải
     lấy từ token retry-ổn định của chính đường ghi.
  Ba đường ghi, hai đường có khoá tự nhiên: pixel ingest dùng `event_id` do pixel mint (pixel giữ
  queue và gửi lại nguyên batch khi gặp non-2xx — đây mới là nguồn trùng lớn nhất, không phải
  beacon); beacon dùng mint token. Gateway surface không có khoá → để NULL, ghi vô điều kiện như cũ.
  Digest gộp cả `site_id` + `vendor` + `raw_ua_token`: một page render bị cache phát **cùng một**
  token cho mọi fetcher, nên nếu chỉ khoá theo token thì lượt fetch của ClaudeBot sẽ bị nuốt như
  bản replay của GPTBot.

- **F11 — surface agent-facing nay có ghi lại** (xem mục 4.3). Manifest, offers, llms.txt và MCP
  đều ghi vào `agent_visits` + `agent_fetch_events`; nhãn MCP mang theo tên tool.
- **F3 — phân loại nay tất định.** `_VENDOR_TOKENS` đổi từ `frozenset` sang tuple có thứ tự
  (dài nhất trước). Thứ tự duyệt set phụ thuộc hash chuỗi mà Python random hoá mỗi process, nên
  UA đa token từng trả token khác nhau giữa các lần restart → tier lật → sweep chạy hay không
  cũng lật. Chứng minh: chạy với `PYTHONHASHSEED` = 0/1/42/12345/99999 đều ra cùng kết quả.
- **F4 — khớp token chính xác.** Bỏ URL tự mô tả trong UA trước khi khớp, và yêu cầu token phải
  đứng trọn vẹn (không phải mảnh của chuỗi dài hơn). Trước đây một scanner có UA chứa
  `+http://example.com/gptbot-detector` bị nhận nhầm là GPTBot.
- **F5 — chờ cửa sổ đóng mới nối link.** Fetch chỉ được xét sau khi đủ 30 phút. Trước đó sweep
  chốt bản khớp đang có tại thời điểm chạy rồi khoá vĩnh viễn (`~link_exists`), nên một click yếu
  ở T+3′ ghi `medium` sẽ chặn mất click đúng trang ở T+12′ lẽ ra phải là `high`. Lookback nới từ
  60 lên 180 phút để một lần sweep lỗi không làm fetch hết hạn.
- **F6 — chặn khối lượng query ứng viên.** Lọc `referrer` rỗng ngay trong SQL (phần lớn pageview
  không có referrer, và ứng viên không có referrer chắc chắn bị loại ở bước sau) + cap 500 dòng,
  sắp xếp cũ trước nên click gần fetch nhất luôn nằm trong cap.
- **F12 — nay phát hiện được UA giả mạo.** `verify_ip()` trả **ba** kết quả thay vì hai:
  `ip-verified` / `ip-mismatch` / `None`. `ip-mismatch` = agent có công bố dải IP nhưng traffic đến
  từ ngoài tất cả → đúng hình dạng của UA giả. `None` = **không kết luận được** (Anthropic không
  công bố gì, hoặc chưa fetch dữ liệu). Hai cái này **cố ý tách bạch**: không công bố dải IP không
  phải bằng chứng giả mạo, gộp lại là bịa ra bằng chứng.
  **Chỉ ghi nhận, không hành động** — không chặn, không xoá, không đụng emailability, không loại
  khỏi correlation. Lý do trong mục dưới.
- **F13 — dải IP tự làm mới, tách theo từng agent.** Phát hiện lúc làm: dữ liệu commit trong repo
  **sai hẳn**, không chỉ cũ — GPTBot thật công bố `132.196.86.0/24` còn repo ghi `23.98.142.176/28`.
  Nghĩa là nếu chỉ thêm F12 mà không có F13, GPTBot **thật** sẽ bị gắn `ip-mismatch`. Job chạy 24h/lần
  fetch lại từng document vendor, fail-open (fetch lỗi → giữ nguyên dữ liệu cũ).
  Khoá theo **token từng agent**, không gộp vendor: OpenAI công bố 3 file riêng cho GPTBot /
  OAI-SearchBot / ChatGPT-User. Gộp lại sẽ trả lời "ừ, đó là OpenAI" cho trường hợp GPTBot đến từ
  dải của ChatGPT-User — mất luôn một bất thường đáng thấy. File ship kèm repo để **rỗng**: rỗng =
  không kết luận, an toàn hơn là kết luận sai.
- **F8 — thêm `google` vào `_VENDOR_FAMILY_MAP`.** Chưa dùng tới (google toàn index-tier), nhưng
  nếu sau này promote lên on-demand thì thiếu key sẽ khiến sweep trả 0 link **im lặng**.

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

`agent_detection_enabled`, `agent_gateway_enabled`, `agent_marker_enabled`,
`cadence_bot_flag_enabled`, `site_ingest_limit_enabled`, `ingest_velocity_enabled`,
`company_graph_enabled`, `identity_signals_enabled`.

`agent_marker_enabled` khác các cờ còn lại ở một điểm: bật nó **đổi header cache** của
`offers.json` (sang `private, no-store`), không chỉ bật thêm đường ghi. Nó cũng cần
`ENCRYPTION_KEY` — thiếu key thì feed vẫn phục vụ bình thường nhưng không có marker nào.

Bật cờ **trước khi** apply migration lên production sẽ crash. Không có guard nào ở code chặn
việc này — đây là quy trình vận hành thủ công.

---

## Câu hỏi chưa giải quyết

1. **AI có giữ nguyên query param khi hiển thị link cho người dùng không?** Đây là giả định F2
   đang đứng trên và **không kiểm chứng được bằng code** — một số surface có thể strip param hoặc
   viết lại URL. Cần test thật với agent thật. Nếu bị strip, F2 âm thầm về mức 0 link (không sai,
   chỉ là không có), sweep thời gian vẫn chạy như cũ.
2. **Có làm Web Bot Auth (F14) không?** Đây là thay đổi lớn nhất về năng lực nhưng cũng là việc
   mới hoàn toàn, không phải sửa lỗi.
3. **Dải IP tĩnh làm mới thế nào?** Hiện commit trong repo — xem mục 5 dưới đây.
4. `routers/visitors.py` (1314 dòng) và 2 trang dashboard mới đọc phần giao với agent, **chưa
   review từng dòng**. Đánh giá trên chưa phủ tab Visitors ở mức chi tiết.
5. **Dải IP ship kèm repo đang có dữ liệu thật, trái với thiết kế đã ghi.** Mục F13 nói file ship
   để rỗng ("rỗng = không kết luận"), nhưng commit `889013b` commit luôn dải thật vào
   `apps/api/data/agent_ip_ranges/*.json`. Test `test_load_ip_ranges_real_branch_is_empty_until_refreshed`
   đang **fail** vì đúng lý do đó. Hệ quả: F12 armed sẵn bằng một snapshot sẽ cũ dần thay vì chờ
   job refresh — đúng kiểu hỏng mà F13 sinh ra để tránh. Cần chọn: (a) xoá rỗng file cho khớp
   thiết kế, hay (b) đổi ý sang "ship seed snapshot" rồi sửa test + doc. Rủi ro hiện thấp
   (chỉ ghi nhận, `agent_detection_enabled` mặc định TẮT).
