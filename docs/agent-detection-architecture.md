# Lớp phát hiện AI-agent — kiến trúc & đánh giá

Cập nhật: 2026-08-18 · Phạm vi: tab **Agents** + **Visitors** + Beam Lab (edge) + **hai** đường beacon (GetBeam PROD vs splittrip lab)
Nguồn: đọc trực tiếp source + kiểm chứng live local (17/17 probe) + ChatGPT-User thật trên beamlab.nhantown.com (29-07 → 01-08)

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
| Beacon **GetBeam PROD** | Vercel Edge middleware `apps/web/src/middleware.ts` trên **`getbeam.fyi`** → POST `api.getbeam.fyi/api/v1/agents/fetch-beacon` | On-demand | Đây là beacon của marketing/dashboard Beam. Cloudflare trước `getbeam.fyi` chỉ DNS/WAF; origin là Vercel. |
| Beacon **lab splittrip** | Cloudflare Worker **`beam-agent-beacon-splittrip`** → POST `beam-api.nhantown.com` | On-demand tokens | Route **chỉ** `splittrip.nhantown.com/*`. Site test, **không** phải GetBeam PROD. Source `infra/cloudflare/agent-beacon-worker/`; deploy `--env splittrip`. MCP get/build/push lab Worker: tên này — không dùng `quota-tracker`. |

Hệ quả quan trọng: với site khách dùng pixel, **crawler index-tier về cơ bản vô hình**. Beacon chỉ
quan sát được khi có lớp edge (Worker/middleware) phía trước origin. Đây là giới hạn cấu trúc, không
phải bug.

Hai đường beacon **không thay thế nhau**:

```text
splittrip.nhantown.com  →  CF Worker splittrip  →  beam-api.nhantown.com   (lab)
getbeam.fyi             →  Vercel middleware    →  api.getbeam.fyi         (PROD)
```

---

## 3. Ba tầng độ tin cậy định danh

`VERIFICATION_METHODS = ("ua-only", "ip-verified", "rdns-verified")` — cộng thêm trạng thái
**ghi nhận** `ip-mismatch` (F12, không nằm trong tuple trên vì chỉ dùng nội bộ sweep).

`verify_ip()` trong `agent_verification.py` trả **ba** kết quả:

| Kết quả | Ý nghĩa |
|---|---|
| `ip-verified` | IP nằm trong dải vendor công bố cho token đó |
| `ip-mismatch` | Vendor **có** công bố dải IP nhưng traffic đến từ ngoài tất cả → hình dạng UA giả |
| `None` | **Không kết luận** — Anthropic không công bố dải IP, hoặc chưa có dữ liệu refresh |

Sweep IP (`sweep_verification_methods`) chỉ cập nhật `agent_visits.verification_method`, **không**
cập nhật `agent_fetch_events.verification_method` — lệch dữ liệu MEDIUM giữa hai bảng.

Dải IP không còn tĩnh trong repo: job F13 (`agent_ip_range_refresh.py`) fetch 24h/lần, ghi vào
`apps/api/data/agent_ip_ranges/runtime/` (ngoài git). File ship kèm repo để `ranges: []` — rỗng =
không phát verdict cho tới khi refresh thành công.

**Giới hạn còn lại:** beacon edge không ghi IP → ChatGPT-User trên site công khai không beacon vẫn
`ua-only`. Anthropic vĩnh viễn `ua-only` nếu không có F14 (Web Bot Auth). F14 chưa implement.

---

## 4. Ba câu hỏi sản phẩm — trả lời được tới đâu

### (1) Phân biệt đâu là AI — **phần lớn, có giới hạn**

Nhận diện được 11 token vendor tự khai báo. F12 phát hiện `ip-mismatch` cho vendor có dải IP
công bố (mục 3). F13 tách khoá theo **token từng agent** (GPTBot / OAI-SearchBot / ChatGPT-User
riêng) và tự làm mới dải IP. Vẫn không kết luận được: Anthropic (không có dải IP), MCP client
UA chung chung, beacon không ghi IP.

### (2) Ai đứng sau AI — **attribution công ty, không định danh cá nhân**

Hai khái niệm **tách bạch**:

| Khái niệm | Trạng thái | Cơ chế |
|---|---|---|
| **Attribution** (AI nào / công ty nào) | **Hoạt động** khi có click | `ai_source` trên visitor; marker F2 → `agent_handoff_links` method=`marker`, confidence=`high` |
| **Identity** (tên/email người cụ thể) | **Queue đã ưu tiên; kết quả identify còn OPS** | Marker **không** gọi write path identity (separation cố ý). Visitor có `ai_source`/handoff được qualify + rank trước trong `resolution_runner`. `identified_visitors` vẫn cần provider keys. |

Marker chỉ ghi attribution (`ai_source`, handoff link) — không ghi identity. `resolution_eligibility.py` + `resolution_runner.py` ưu tiên visitor AI-attributable (`ai_source` hoặc same-site handoff) trước `intent_score` (shipped `7b1ed33`). Provider keys (PDL/Proxycurl/FullContact) trống → resolution vẫn không identify được dù attribution đúng.

Kỳ vọng đúng: *"ChatGPT đọc pricing cho công ty X"* (cấp công ty), hiếm khi *"John Smith hỏi
ChatGPT"* trừ khi người đó tự submit email.

Sweep thời gian (`agent_handoff_correlation.py`) vẫn chạy song song: ba điều kiện mềm (cùng site +
referrer khớp vendor + click trong 30 phút). Marker **ghi đè** link sweep khi có click với `?_bam=`.
Không có click con người → `handoff_links = 0` (đúng, không phải bug).

### (3) Dẫn người dùng AI click vào và định danh — **xây xong mặt tiền, thiếu cả hai đầu**

Đã có: `llms.txt`, agent manifest, offers feed, MCP JSON-RPC server (3 tool đọc), agent profile do
khách tự soạn, chống dò `site_id` (5 trường hợp lỗi đều trả 404 giống nhau).

**Đầu ra — đã sửa 29-07 (F2).** Trước đó link trong offers feed là URL trần, không mang mã nào để
nhận ra khi có người click. Nay mỗi URL cùng host mang `?_bam=<marker>` mã hoá id của chính lượt
fetch đã phát nó ra (chi tiết + 4 ràng buộc: mục 7). Cờ `agent_marker_enabled`, mặc định TẮT.
Riêng môi trường thử nghiệm **Beam Lab** dùng một marker biên khác tên (`?_bfm=`), không mã hoá,
không đi qua cờ này — xem [§5d](#5d-soft-serve-gate--marker-biên-_bfm-trên-beam-lab-31-07--01-08).

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

## 5. Kiểm chứng live (2026-07-29/30)

Phiên kiểm chứng trên môi trường lab (`beamlab.nhantown.com`) với ChatGPT-User thật (tier=on-demand).

### Kết quả đã chứng minh

| Hạng mục | Kết quả |
|---|---|
| API probe local | **17/17 pass** — gateway surfaces, F2 mint/decode, cache posture, cross-tenant replay block, F4/F12/F13, multi-tenant 404 |
| ChatGPT-User thật | `/` → `/llms.txt` → `/` trong ~7s; ghi nhận fetch gateway |
| Marker handoff (probe) | Click `?_bam=` → `agent_handoff_links` method=`marker`, confidence=`high` |
| Không có click người | `handoff_links = 0` — **đúng**, đọc câu trả lời AI không tạo person link |
| Harness test suite | 1503 pass / 5 fail trước fix; 3 commit harness (53fc573, 486b47a, b5f4311) — không phải lỗi product |

### Khoảng trống còn lại (product/ops, không phải bug detection)

| Gap | Mức | Ghi chú |
|---|---|---|
| Marker survival trên AI thật | **ĐÃ KIỂM CHỨNG (31-07)** | ChatGPT giữ nguyên `?_bam=` trong câu trả lời; chuỗi đóng end-to-end — chi tiết mục 5b |
| Marker được AI **tự** trích dẫn | OPEN | Lần đo dùng prompt có câu "giữ nguyên URL đầy đủ" — mới chứng minh *có thể giữ*, chưa phải *tự giữ* khi dẫn link tự nhiên |
| AI **tự tìm ra** offers feed | OPEN | ChatGPT đọc `llms.txt` (có link tuyệt đối tới offers) rồi bỏ qua; chỉ fetch khi được đưa URL thẳng |
| Link marker render thành `code` thay vì link | OPEN (hẹp) | Phụ thuộc VAI TRÒ của URL trong câu trả lời, **không** phụ thuộc độ dài — xem 5c. Xử lý bằng cách làm offers feed đọc như lời chào hàng, không phải bảng dữ liệu trống |
| Identity resolution queue | DONE / OPS | **DONE (`7b1ed33`):** ưu tiên `ai_source`/handoff trước intent. OPEN ops: provider keys → `identified_visitors` |
| `agent_fetch_events.verification_method` | MEDIUM | Sweep IP chỉ cập nhật `agent_visits`, không `agent_fetch_events` |
| Beacon không có IP | MEDIUM | Public site không beacon → ChatGPT-User ua-only |
| Provider keys trống | OPS | PDL/Proxycurl/FullContact chưa cấu hình |
| F14 Web Bot Auth | — | Chưa implement, không có active plan |
| `pytest -n` parallel | LOW | Shared DB `drop_all` fixture — không an toàn chạy song song |
| `ENCRYPTION_KEY` trùng trong `.env` | LOW | Vệ sinh ops |

---

## 5b. Marker end-to-end với ChatGPT thật (2026-07-31)

Lần đầu chuỗi marker chạy thông với một AI thật, không phải probe. Điều kiện: `agent_marker_enabled=True`,
AgentProfile của `site_16c46453546f` bật với 1 offer trỏ `https://beamlab.nhantown.com/`, và
`beamlab` được deploy kèm `<link rel="alternate">` → manifest + 2 dòng offers/manifest trong `llms.txt`.

| Giờ (VN) | Sự kiện | Bằng chứng |
|---|---|---|
| 12:28:08 | ChatGPT fetch `/agent/offers.json` | `agent_fetch_events` id `53528fb5-…` tier=on-demand |
| 12:28:xx | ChatGPT in `?_bam=gAAAAABqbDJo…` nguyên vẹn ra câu trả lời | không cắt, không rewrite |
| 12:30:29 | Người dán URL vào thanh địa chỉ | `events.pageview` mang `_bam=`, **referrer rỗng** |
| 12:30:31 | Link tất định được ghi | `agent_handoff_links` method=`marker`, confidence=`high`, delta=0 |

Ba điều lần đo này xác lập:

1. **Marker không phụ thuộc referrer.** Lượt click trên có referrer rỗng — đường temporal sẽ không
   tìm được ứng viên nào (`classify_ai_source(None)` → `None`). Đây đúng là kịch bản đã làm hỏng
   một lần đo trước đó trong ngày; marker vá đúng chỗ đó.
2. **Marker ghi đồng bộ tại ingest, không qua sweep.** Click → link cách nhau 2 giây
   (`routers/events.py` đọc `_bam` ngay trong batch). Mọi tham số của sweep — cửa sổ 30 phút,
   settle delay, chu kỳ APScheduler — **không áp dụng cho đường marker**.
3. **`delta_seconds=0` là đúng.** Marker giải mã thẳng ra lượt fetch, không có khoảng thời gian nào
   để đo; con số đó không so sánh được với 151–157s của các link `temporal-page-match`.

Đối chứng cùng ngày: lúc 12:22 ChatGPT fetch `/` → `/llms.txt` → `/` rồi **dừng**, không mở offers
feed dù `llms.txt` đã có link tuyệt đối. Nó chỉ fetch khi được đưa URL trực tiếp. Nên câu hỏi
"AI có tự tìm tới feed không" vẫn mở, và không đo được trên `beamlab` — trang này tự khai
"Không phải sản phẩm thương mại", mâu thuẫn với chính offers feed của nó, nên không có câu hỏi
người dùng nào tự nhiên dẫn AI tới đó. Cần một site thương mại thật để đo.

---

## 5c. Vì sao marker lúc render thành `code`, lúc thành link (31-07)

Cùng một URL marker, hai cách hỏi, hai kết quả:

| Câu hỏi | ChatGPT render |
|---|---|
| "Đọc file JSON này và liệt kê các link trong đó" | `code` — không bấm được |
| "Liệt kê 2 link này cho tôi" | link bấm được |

Đối chứng loại trừ độ dài: hỏi cùng lúc một URL ngắn (`?x=abc`) và URL marker ~180 ký tự —
**cả hai đều linkify**. Nên giả thuyết "URL quá dài nên không linkify" là SAI, và rút ngắn marker
không giải quyết được gì. Fernet giữ nguyên.

Yếu tố quyết định là VAI TRÒ của URL trong câu trả lời: trích xuất giá trị từ một document thì
format như dữ liệu; giới thiệu một đường dẫn thì format như link.

Hệ quả thiết kế: ca dùng thật (AI giới thiệu sản phẩm rồi đưa link đăng ký) rơi vào vai trò
"link", nên nhiều khả năng linkify. Nhưng link vẫn đến TỪ một feed JSON, nên vẫn có đường rơi lại
vào vai trò "dữ liệu". Đòn bẩy nằm ở nội dung feed — một offer có tên/giá/mô tả đọc như lời chào
hàng, còn offer rỗng như của `beamlab` (không giá, mô tả trống, url trỏ về chính trang đang đọc)
đọc như một bảng dữ liệu. Chỉ đo dứt điểm được trên site thương mại thật.

---

## 5d. Soft-serve gate + marker biên `_bfm` trên Beam Lab (31-07 → 01-08)

Môi trường lab riêng biệt với `apps/api` đa tenant: **Beam Lab**
(`https://beamlab.nhantown.com/`, Cloudflare Pages project `beam-lab`, `site_id
site_16c46453546f`) là trang tĩnh do chính Beam vận hành để kiểm chứng chuỗi phát hiện agent trên
một tên miền kiểm soát hoàn toàn. Pixel gửi về `beam-dev.nhantown.com`; beacon fetch gửi về
`beam-api.nhantown.com`; dữ liệu ghi vào Postgres Docker local (`retarget_agent`), **không phải**
database production. Canary nội dung `FUCHSIA-0731` trên trang chủ dùng để phân biệt AI đọc bản mới
hay trả lời từ cache/chỉ mục cũ. Deployment production gần nhất đã ghi nhận:
`9a4d1f20-6bdd-46fc-bfc5-447c83e81cab` (dùng với `wrangler pages deployment tail`).

### Gate cứng (403) bị thực tế bác bỏ

Kế hoạch đầu tiên (`process/features/evallayer/active/agent-gate-lab_31-07-26/`) chặn 5 UA
on-demand bằng **403 HTML interstitial** cho tới khi agent tự khai vendor + mục đích (header retry
hoặc check-in token HMAC). Triển khai xong, ChatGPT-User thật (ASN 8075) đụng 403 **hai lần**,
không gửi header nào, không gọi check-in, và báo cho người dùng là trang **không đọc được** — model
quay sang trả lời bằng bản trả lời cũ/cache thay vì đọc trang mới. Gate đo được đúng một điều: agent
bỏ cuộc.

Vá bằng kế hoạch thứ hai (**thay thế về hành vi, không xoá plan cũ**):
`process/features/evallayer/active/agent-gate-soft-serve_31-07-26/`. Nguyên tắc đảo ngược: **luôn
trả 200 + HTML thật** cho agent on-demand; câu hỏi "bạn là ai" được nhét **vào trong** trang (HTML
comment qua `HTMLRewriter`), không còn đứng chắn trước trang. Không header `x-agent-gate` nào được
gắn — chính header đó, cùng khối `<section>` hiển thị của bản 403, là thứ khiến công cụ browse của
ChatGPT từng báo lỗi trên một response 200 đầy đủ nội dung.

Code: `infra/cloudflare/beam-lab/functions/_middleware.js`, `infra/cloudflare/beam-lab/wrangler.toml`.

| Biến env | Vai trò | Trạng thái hiện tại |
|---|---|---|
| `BEAM_AGENT_GATE` | Kill switch. Chỉ đúng giá trị `"0"` mới tắt — xoá dòng vẫn để gate BẬT | `"1"` (bật) |
| `BEAM_FULL_LOG` | Ghi log toàn bộ request/response (kể cả người) để đọc lại từng header | `"1"` — **cố ý tạm thời, cần tắt sau khi hết cửa sổ debug** |

Cả hai đều **fail-open tuyệt đối**: bất kỳ throw nào trong logic gate/log đều rơi về phục vụ trang y
nguyên. Không áp dụng cho người, index crawler (GPTBot/ClaudeBot/PerplexityBot), static asset,
`/robots.txt`, `/sitemap.xml` — response byte-identical.

### Marker biên `_bfm` — khác `_bam`, cố ý không trùng tên

Middleware trên Cloudflare Pages **không có** hàng `agent_fetch_events` và **không có** khoá mã hoá
của API, nên nó không thể mint `_bam` (marker Fernet của F2, mục 7). Nó tự mint marker riêng:

| | `_bam` (API, đã có từ F2) | `_bfm` (edge, mới 31-07) |
|---|---|---|
| Nơi mint | `apps/api/services/agent_marker.py` (`mint_marker`) | `_middleware.js` (`mintFetchMarker`) |
| Định dạng | Token Fernet — mã hoá, tự chứng minh TTL 7 ngày | 12 ký tự hex (`crypto.randomUUID()` cắt ngắn) |
| Giải mã | Giải mã ngược ra `agent_fetch_events.id` | **Không giải mã được gì** — chỉ là khoá tra cứu, đối chiếu bằng so khớp chuỗi |
| Đọc lại tại ingest | `agent_marker.py::decode_marker` qua `MARKER_PARAM = "_bam"` | `agent_marker.py::edge_marker_from_url` qua `EDGE_MARKER_PARAM = "_bfm"` |
| Phạm vi dùng | Offers feed đa tenant (site khách bật `agent_marker_enabled`) | Riêng thử nghiệm Beam Lab (mọi `a[href]` cùng host trên trang tĩnh) |

Cố ý tách tên: nếu edge tái dùng `_bam`, decoder Fernet của API sẽ nhận một giá trị nó **không thể
giải mã**, và một thử nghiệm lab dễ bị đọc nhầm thành attribution production thật.

Chuỗi ghi nhận, mỗi lượt fetch on-demand:

```text
Agent on-demand GET / (không mang credential)
  → middleware mint marker 12-hex (_bfm)
  → HTMLRewriter stamp _bfm= lên MỌI a[href] cùng host (không đổi header response)
  → beacon POST /api/v1/agents/fetch-beacon kèm {..., marker: _bfm}
    → record_fetch_beacon() → persist_agent_fetch_event(..., link_marker=_bfm)
       ghi agent_fetch_events.link_marker (migration f3c8b2e91d47)

Người click link mang _bfm= trong câu trả lời AI
  → pixel gửi pageview URL còn nguyên _bfm=
  → routers/events.py đọc edge_marker_from_url(event.url)
       ghi events.link_marker (migration a7d419e6c052)

Join: events.link_marker = agent_fetch_events.link_marker  (cả hai cột đều index PARTIAL)
```

Hai migration này **chỉ áp cho Postgres dev/local** kiểm chứng lab — **chưa apply lên API
production**. Đây là một trong các việc còn mở (bảng dưới).

`edge_marker_from_url()` có shape-check `[0-9a-f]{1,32}` vì `_bfm` là giá trị **ai cũng append được**
vào URL (không mã hoá) — khác `_bam`, giải mã sai thì tự loại; `_bfm` phải tự kiểm hình dạng ở phía
ingest để không nuốt rác vào cột index.

**Lưu ý về trang sâu:** `/tac-nhan/` và `/kiem-chung/{openai,anthropic,perplexity,khac}/` ban đầu
KHÔNG có snippet pixel — chỉ trang chủ `/` có. Chuỗi handoff cho các trang này im lặng thiếu một nửa
(edge stamp marker nhưng không trang nào chạy pixel để đọc lại `_bfm` khi người click landing ở đó).
Đã thêm snippet pixel vào các trang sâu; chưa kiểm chứng lại end-to-end trên các trang này.

### Ba tầng định danh — không đổi kết luận, chỉ thêm bằng chứng

Không có gì trong phiên này thay đổi ba câu hỏi ở mục 4, nhưng làm rõ thêm bằng chứng cho từng tầng:

1. **AI nào** — vẫn có: classifier + beacon + log CF (ASN, tổ chức, UA) đủ để nói "đây là
   ChatGPT-User thật" hay "đây là AI khác đội lốt".
2. **Click ↔ fetch** — cơ chế + join DB **có**, khi có người thật bấm link đã đánh dấu (`_bam` hoặc
   `_bfm` tuỳ đường). Chưa có bằng chứng con người bấm marker `_bfm` trên lab (bảng dưới).
3. **Người đó là ai** — vẫn **không**. IP nhà/di động dân cư không định danh cá nhân; muốn có tên
   người vẫn cần identity resolution (provider keys) hoặc chính người đó tự để lại email/form.

**IP không phải khoá phiên.** Quan sát trực tiếp: IP của Azure/OpenAI đổi **giữa** các lượt fetch
trong cùng MỘT câu trả lời ChatGPT (cùng ASN 8075 Microsoft, IP khác nhau theo từng request) — nên
không thể dùng IP để nối hai lượt fetch của cùng một phiên hỏi đáp; chỉ marker mới nối được tất định.

### Hành vi browse thật của ChatGPT (kiểm chứng 01-08)

| Quan sát | Chi tiết |
|---|---|
| UA + ASN khi browse hoạt động | `ChatGPT-User/1.0`, ASN **8075**, header như `x-envoy-expected-rq-timeout-ms`, `x-request-id` (đổi mỗi request, **không** dùng được làm khoá phiên hội thoại) |
| Fetch canary-only / trang chủ | Thường thành công; câu trả lời trích đúng `FUCHSIA-0731` — chứng minh đọc bản mới, không phải cache |
| Prompt "chỉ dựa trên trang đã tải" | **Chặn hẳn** việc model tự hop sang `/tac-nhan/`, dù link nằm ngay trong trang đã tải |
| Hop tự nhiên (không chặn) | Từng thành công kiểu E2b ở lần đo trước; các lần đo sau: fetch trang chủ xong **không** GET `/tac-nhan/` dù được yêu cầu mở link — model báo "không thấy href" |
| Fetch thẳng URL sâu `.../tac-nhan/?ref=deep-0801` | Trang public trả 200 bình thường; ChatGPT **đôi lúc không fetch luôn**, bịa lý do, có lần trích dẫn sai domain (`amlab.vn` thay vì `beamlab.nhantown.com`) |
| Dán thẳng HTML/text của `/tac-nhan/` vào chat | ChatGPT liệt kê đúng cả 13 token UA (11 nhận diện được + 2 cố ý không nhận diện: `google-extended`, `applebot-extended`) — chứng minh model đọc hiểu nội dung tốt, chỉ hành vi **browse chủ động** là không ổn định |

Kết luận thực dụng: đừng coi "AI có tự hop sang link không" là bug của Beam — đó là hành vi
browse-tool phía OpenAI, ngoài tầm kiểm soát của lớp phát hiện. Câu hỏi mở #1 ở cuối tài liệu này
(marker có tự được AI giữ khi dẫn link tự nhiên) chưa có thêm bằng chứng quyết định từ phiên này.

### Gemini — vẫn ngoài classifier

Một lượt fetch khớp thời điểm Gemini eval mang UA `got (https://github.com/sindresorhus/got)`, ASN
**14618 Amazon** (Ashburn) — **không phải** `Googlebot` hay `google-cloudvertexbot`. Classifier
hiện tại **không** coi `got` là token AI nên **không ghi** `agent_fetch_events` cho lượt này — gap
sản phẩm nếu cần theo dõi traffic dạng Gemini/AWS-hosted fetcher. Gemini vẫn trích đúng canary từ
HTML dù đôi khi đọc sai meta/schema.

### Schema.org trên trang chủ lab

`@graph` gồm `Organization`, `WebSite`, `SoftwareApplication`, `WebPage`, `FAQPage`. Đã thử thêm rồi
bỏ `TechRetail`/`TechArticle` (Rich Results coi là noise, không giúp gì). Cổng agent-facing vẫn giữ
nguyên ở `<link rel="alternate">` — **không** đặt URL manifest vào `Organization.url` (từng làm tổ
chức trông như một file JSON).

### Việc còn mở (ưu tiên resume)

| # | Việc | Ghi chú |
|---|---|---|
| 1 | Retest hop ChatGPT với prompt tự nhiên (không cấm rời trang) | Hoặc chấp nhận browse không ổn định là kết luận cuối |
| 2 | Người thật bấm link mang `_bfm=` → xác nhận join `events.link_marker` | Chưa có bằng chứng end-to-end cho đường edge marker (khác với `_bam` đã kiểm chứng ở §5b) |
| 3 | Phân loại fetcher dạng Gemini/`got`/AWS | Sản phẩm optional |
| 4 | Áp migration `link_marker` (cả hai) lên API production | Hiện chỉ có ở Postgres dev |
| 5 | Chính sách TTL cho `_bfm`; test on-demand Perplexity/Claude | `_bfm` chưa có TTL như Fernet 7 ngày của `_bam` |
| 6 | Tắt `BEAM_FULL_LOG` sau cửa sổ debug | Đang `"1"`, log MỌI khách kể cả người |
| 7 | F14 Web Bot Auth | Vẫn mở, không đổi so với mục 6 của tài liệu này |
| 8 | Đối chiếu trạng thái plan | Cả hai plan feature vẫn mang `status: awaiting-execute-approval`, nhưng hành vi soft-serve **đã sống trên lab thật**. Cần UPDATE PROCESS đối chiếu trạng thái |

Tham chiếu vận hành + resume nhanh: [beam-lab-resume.md](./beam-lab-resume.md).

---

## 6. Danh sách vấn đề còn mở

Chỉ còn **một** hạng mục chưa implement:

| Mã | Vấn đề | Mức | Ghi chú |
|---|---|---|---|
| F14 | Chưa có Web Bot Auth (RFC 9421) — chữ ký mã hoá, miễn phí | MEDIUM | Implement từ đầu: header `Signature-Agent`, public key tại `/.well-known/http-message-signatures-directory`, verify + cache. Nhiều ngày, cần plan riêng |

**F2 và F12 đã ship** (mục 7). F14 đáng chú ý nhất về mặt cơ hội: Web Bot Auth đã được Anthropic,
OpenAI, Perplexity, Common Crawl hỗ trợ. Giải đúng chỗ Anthropic bế tắc (không công bố dải IP →
vĩnh viễn `ua-only`, nhưng **có** ký).

---

## 7. Đã sửa (28-07 → 30-07)

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
  5. **Fetch phải thuộc đúng site báo click** — kiểm tra bằng query, không suy đoán. Giải mã được
     chỉ chứng minh marker do deployment này mint, KHÔNG chứng minh mint cho tenant này. Thiếu
     kiểm tra, marker lấy từ offers feed công khai của site A rồi replay trên trang site B sẽ ghi
     link dưới site B trỏ vào fetch của site A — và vì mỗi fetch chỉ giữ được một link, nó còn
     **chiếm luôn chỗ** mà click hợp lệ của site A cần, không click nào sau đó gỡ được. Cùng luật
     `AC-H2-5` mà sweep đã thực thi. Lỗi này do integration test bắt được; unit test mock session
     nên về cấu trúc không thể phát hiện.
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
  **Đã verify trên Postgres thật (29-07)**, không chỉ offline `--sql`: full chain apply sạch tới
  head, round-trip `head → -1 → head` sạch, và ba luận điểm thiết kế được chứng minh bằng dữ liệu —
  nhiều dòng `dedup_key IS NULL` cùng tồn tại (nên dòng cũ không thể vi phạm → **không cần dọn
  prod**), replay có `ON CONFLICT` bị chặn (`INSERT 0`), và cùng key mà bỏ `ON CONFLICT` thì lỗi
  cứng (chứng minh index thực sự enforce, không phải inert).

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

## 8. Điểm làm tốt (không nên đụng vào)

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

## 9. Cờ tính năng — tất cả mặc định TẮT

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
   đang đứng trên. Lab probe chứng minh decode khi param còn nguyên; **chưa kiểm chứng trên
   ChatGPT thật** — một số surface có thể strip param hoặc viết lại URL. Nếu bị strip, F2 âm
   thầm về mức 0 link (không sai, chỉ là không có), sweep thời gian vẫn chạy như cũ.
2. **Có làm Web Bot Auth (F14) không?** Thay đổi lớn nhất về năng lực nhưng việc mới hoàn toàn,
   không phải sửa lỗi. Không có active plan.
3. ~~**Dải IP tĩnh làm mới thế nào?**~~ — **đã xử lý 29-07 (F13).** Job refresh ghi vào
   `data/agent_ip_ranges/runtime/` ngoài git; file ship kèm repo để `ranges: []`.
4. `routers/visitors.py` (1314 dòng) và 2 trang dashboard mới đọc phần giao với agent, **chưa
   review từng dòng**. Đánh giá trên chưa phủ tab Visitors ở mức chi tiết.
5. ~~**Identity priority trong resolution queue**~~ — **DONE (`7b1ed33`).** AI-attributable
   (`ai_source` hoặc handoff) qualify + rank trước intent. OPEN còn lại: điền provider keys và
   đo `identified_visitors` trên traffic thật.
