# Beam AI Detection Lab — Brainstorm thu gọn + Validation

Ngày: 2026-07-28
Nguồn: [beam-ai-detection-lab-architecture.md](../../beam-ai-detection-lab-architecture.md)
Loại: analysis-only (không implement)

---

## 1. Ràng buộc đã chốt

| Câu hỏi | Trả lời | Hệ quả |
|---|---|---|
| Beam ở đâu | Dự án riêng, doc chỉ mô phỏng kiến trúc | Lab greenfield. Bỏ giai đoạn 2 ("chuẩn hóa 5 detector Beam") khỏi đường găng |
| Research hay product | Lab test-all-cases, bắt input/output để dựng solution | Hướng **research/instrument**. Detector phải là pure function của evidence đã lưu → bắt buộc có replay |
| Traffic | Tự sinh, lab-only | Velocity + Cadence **vô nghĩa** (không có baseline thật). Bỏ khỏi MVP |
| Cloudflare | Free | Không Bot Management, không bot score, không verified-bot metadata. Identity tự làm 100% |
| Chạy 1 lần hay định kỳ | Tự bật/tắt để theo dõi | Scheduler + **run-to-run diff** là thành phần bậc nhất |
| Lưu full response body | Có | Thêm bảng content snapshot bất biến. Mở khoá được takedown test |

Hệ quả suy ra: vì lab kiểm soát URL → `test_run_id` nhúng trong path là correlation key hoàn hảo.
Toàn bộ mục 5.7 (probabilistic sessionization, stitching không cookie, correlation qua NAT) **biến mất**.
Giữ lại phần rẻ: gom request theo `test_run_id` + time window để dựng resource graph.

---

## 2. Phát hiện từ research — thay đổi thiết kế

### 2.1 Web Bot Auth đã thành hiện thực → nâng lên MVP

RFC 9421 HTTP Message Signatures. Verify 3 bước: đọc `Signature-Agent` header → lấy public key tại
`/.well-known/http-message-signatures-directory` của domain đó → verify chữ ký + timestamp.

Đã hỗ trợ: Anthropic, OpenAI, Perplexity, Common Crawl, một số bot Google. AWS WAF / Vercel / Shopify / Akamai đã implement.

**Đây là identity signal mạnh nhất, deterministic, và miễn phí — không cần Cloudflare tier nào.**
Doc xếp nó ở giai đoạn 3. Sai. Phải nằm trong MVP cùng IP CIDR + rDNS.

Thứ tự tin cậy identity: `signature > IP CIDR > rDNS > UA claim`.

### 2.2 Không AI crawler nào chạy JavaScript (trừ Google)

Vercel + phân tích >500M GPTBot fetch: zero bằng chứng execute JS. GPTBot tải file .js ~11.5% request
nhưng không chạy; ClaudeBot tải ~23.84%, không chạy. Áp dụng cho GPTBot, OAI-SearchBot, ChatGPT-User,
ClaudeBot, Claude-SearchBot, PerplexityBot, Meta-ExternalAgent, Bytespider.
Ngoại lệ: Googlebot (WRS), Gemini dùng chung hạ tầng đó.

**Hệ quả:** biến "có chạy JS không" thành **test dimension chủ động** (trang có marker chỉ render bằng JS),
không phải signal thụ động. Đây là phép thử phân biệt crawler / browser / agentic browser rẻ và sắc nhất.

### 2.3 Có tiền lệ học thuật cho canary methodology

Nghiên cứu "Identifying AI Web Scrapers Using Canary Tokens" (Duke / Pittsburgh / CMU): 20 domain .com,
site theo template chung, gieo canary token.

Bổ sung quan trọng doc chưa có — **takedown test**: hạ site xuống, hỏi lại AI sau 1 tuần.
Nhiều chatbot vẫn đọc đúng nội dung đã gieo → chứng minh trả lời từ cache chứ không fetch live.

→ Thêm test outcome: `content_served_after_takedown` (bằng chứng cứng cho caching).
Full response body storage (bạn đã chốt) chính là thứ làm test này khả thi.

### 2.4 Cloudflare Tunnel phá header-order fingerprinting

HTTP normalization qua proxy: canonicalize header case, đổi header order, mất whitespace/line folding.
JA4-HTTP và fingerprintjs dựa chính xác vào order/case/structure.

→ Bỏ **"header order"** khỏi danh sách signal (mục 4.3.B). Nó sẽ cho dữ liệu sai chứ không phải thiếu.
JA3/JA4 (`cf-ja3-hash`, `cf-ja4`) là Managed Transform, không có ở free → bỏ TLS fingerprint khỏi MVP.

Còn lại chắc chắn có: `CF-Connecting-IP`, `CF-IPCountry`, `CF-Ray`.

### 2.5 IP range feeds

OpenAI publish 3 file riêng: `gptbot.json`, `searchbot.json`, `chatgpt-user.json`.
Mỗi bot một dải khác nhau → **không được gộp chung thành "OpenAI ranges"**, sẽ mất khả năng phát hiện
agent A dùng dải của agent B.

Range thay đổi theo thời gian → phải lưu **version/hash của range file** vào evidence từng request,
nếu không replay sẽ cho kết quả khác lần chạy gốc.

---

## 3. Test matrix — tự tính

### 3.1 Trục agent identity (quan sát thụ động)

| Vendor | Agent | Loại |
|---|---|---|
| OpenAI | GPTBot / OAI-SearchBot / ChatGPT-User | training / index / live |
| Anthropic | ClaudeBot / Claude-SearchBot / Claude-User | training / index / live |
| Perplexity | PerplexityBot / Perplexity-User | index / live |
| Google | Googlebot / Google-Extended | index / training |
| Microsoft | Bingbot / Copilot fetcher | index / live |
| Meta | Meta-ExternalAgent / Meta-ExternalFetcher | training / preview |
| ByteDance | Bytespider | training |
| Amazon | Amazonbot | index |
| Common Crawl | CCBot | training |
| Apple | Applebot / Applebot-Extended | index / training |
| Khác | Mistral, DuckAssistant, You.com… | mixed |

≈ **20 identity** cần nhận diện thụ động.

### 3.2 Trục có thể chủ động kích (on-demand)

Chỉ ~6 driver thật sự bảo AI mở URL ngay: ChatGPT, Claude, Perplexity, Gemini, Copilot, Grok.
Chia 2 nhóm:

- **API-driven** (OpenAI Responses web_search, Anthropic web search tool…) → tự động hoá hợp lệ, có API key.
- **Consumer UI** → giữ **thủ công**. Tự động hoá login UI vừa dễ vỡ vừa rủi ro ToS.

### 3.3 Trục page variant — multiplier doc bỏ sót

| Variant | Đo cái gì |
|---|---|
| V1 static HTML + marker | baseline fetch |
| V2 marker chỉ render bằng JS | có execute JS không |
| V3 marker sau robots.txt disallow | có tuân robots không |
| V4 marker cần load ảnh/asset | resource profile |
| V5 marker sau redirect chain | xử lý redirect |

### 3.4 Kết luận runner

`6 driver × 5 variant = 30 run / chu kỳ` (on-demand) + observation liên tục cho ~20 identity.

30 lần / chu kỳ: quá nhiều để làm tay đều đặn, quá ít để justify automation UI.
→ **Semi-auto**: tự động hoá tạo test run, sinh canary URL/marker, correlate, chấm outcome, diff giữa các chu kỳ.
Giữ thủ công bước nhập prompt vào UI consumer. Nhóm API-driven thì chạy full auto.

### 3.5 Control group (synthetic, bắt buộc)

Chrome thật, mobile browser, in-app browser, headless Chrome, Playwright, Playwright-stealth, Puppeteer,
Selenium, curl, python-requests, UA spoof (UA=GPTBot từ IP local) ≈ 11 case.
Không có nhóm này thì không biết pipeline đúng hay sai.

---

## 4. Scope MVP thu gọn

```
A. Intake + Evidence Store       append-only, schema versioned, full response body snapshot
B. Replay Harness                detector = pure function(evidence); re-run detector v2 trên data cũ
C. Identity Verification         Web Bot Auth (RFC 9421) + IP CIDR per-agent + rDNS + UA registry
D. Canary Test Runner            test run, 5 page variant, takedown test, semi-auto driver
E. Scheduler + Run Diff          bật/tắt theo dõi, so sánh chu kỳ N vs N-1
F. Dashboard drill-down          evidence-first, không phải KPI dashboard
G. Request Shape detector        rẻ, tách crawler-đọc-HTML vs browser-render
```

**Bỏ khỏi MVP:** velocity, cadence, sessionization phức tạp, policy engine (lab luôn `store`),
11 feature flag, Cloudflare bot metadata, TLS/JA3, header-order signal, attribution layer.

---

## 5. Validation — lỗ hổng còn lại

Xếp theo mức nghiêm trọng.

### G1 — CRITICAL: negative result không phân biệt được nguyên nhân

`origin_fetch_not_observed` hiện gộp 4 khả năng: AI không fetch / edge chặn / tunnel chết / bug ingest.
Cộng báo cáo cộng đồng: AI crawler vẫn bị chặn **dù đã tắt** Bot Fight Mode và managed rule "Block AI bots".

→ Mỗi test run bắt buộc có **ingress heartbeat**: fetch canary từ host ngoài bằng curl mang UA=GPTBot
ngay trước và sau observation window. Không pass heartbeat → outcome ép về `inconclusive_ingress_unverified`,
không được ghi là "AI không fetch".

Đây là rủi ro silent-failure lớn nhất của cả dự án.

### G2 — HIGH: cấu hình edge là biến thí nghiệm chưa được version

Bot Fight Mode, managed rules, WAF, robots.txt đều ảnh hưởng kết quả. Chưa có chỗ lưu.
→ Snapshot edge config + robots.txt content + hash vào **từng test run**, không phải global setting.
Không có cái này thì chu kỳ tháng sau không so được với tháng này — mà so sánh chính là mục tiêu.

### G3 — HIGH: replay chưa có ràng buộc kiến trúc

Detector hiện được mô tả tự do đọc dữ liệu. Muốn replay thì cấm:
gọi DNS lúc chạy, đọc đồng hồ hệ thống, query "IP range hiện tại".
rDNS phải resolve **tại thời điểm request** rồi lưu kết quả. IP range phải lưu kèm version file.
→ Cần một `evidence_bundle` đóng kín; detector chỉ nhận đúng bundle đó.

### G4 — MEDIUM: marker hygiene

Canary marker lọt ra ngoài (chat log, screenshot, commit, issue) → AI có thể biết marker mà không cần fetch,
test vô hiệu và không ai phát hiện.
→ Marker one-time-use, không bao giờ commit, không paste vào prompt (prompt chỉ chứa URL),
đánh dấu `burned` sau mỗi lần dùng.

### G5 — MEDIUM: fetch không quy được về vendor

Agent có thể chạy trong browser người dùng, qua proxy, hoặc từ IP cloud không nằm trong dải công bố.
→ Cần bucket riêng `unattributed_fetch_in_window` thay vì ép vào `unknown` chung.

### G6 — MEDIUM: robots.txt là biến, không phải hằng

Nếu canary path bị disallow, crawler tuân thủ sẽ không đến → dễ đọc nhầm thành "AI không quan tâm".
→ robots policy phải là thuộc tính khai báo của từng test run (V3 variant), không phải config site.

### G7 — LOW: retention IP thô chưa có con số

Doc ghi "không lưu lâu dài". Cần số cụ thể (vd: raw IP giữ 24h phục vụ CIDR verify, sau đó chỉ còn
`ip_hash` + `ip_prefix`). Full response body là nội dung của chính mình → không vướng PII.

### G8 — LOW: IP range gộp vendor

Mỗi agent một file JSON riêng. Gộp thành "OpenAI ranges" sẽ mất khả năng phát hiện
GPTBot đến từ dải của ChatGPT-User (bất thường đáng ghi nhận).

---

## 6. Cần verify từ nguồn gốc trước khi chốt

Kết quả research phần lớn từ blog SEO, chất lượng không đồng đều. Phải xác minh primary source:

- Free plan thực sự có/không: `cf-ja3-hash`, `cf-ja4`, verified-bot metadata → dashboard + Cloudflare docs
- Trạng thái thật của Bot Fight Mode + managed rule "Block AI bots" trên zone đang dùng
- URL và schema hiện hành của các file IP range từng vendor (đọc trực tiếp, không qua bên thứ ba)
- Draft status hiện tại của Web Bot Auth (2 IETF draft, mốc IESG 04/2026, BCP 08/2026)
- Giới hạn Quick Tunnel vs named tunnel

---

## 7. Quyết định đã chốt

| Hạng mục | Quyết định | Hệ quả |
|---|---|---|
| Hạ tầng | **Mua domain + Cloudflare zone free + named tunnel** | Giữ đủ 3 lớp hành vi. Mở lại index test, training crawl, takedown test, run-to-run diff |
| Stack | **Python + FastAPI + SQLite** | 1 file DB, không cần server. Replay script viết bằng Python. Đổi sang PostgreSQL sau không phải viết lại nếu dùng SQLAlchemy Core / SQL thuần |
| Driver AI | **Chat UI thủ công** (ChatGPT, Claude, +Perplexity nếu có) | Không có nhóm full-auto. Dashboard bắt buộc có form nhập kết quả |
| Chu kỳ | Test case theo ngày, bật/tắt thủ công | Scheduler đơn giản: enable/disable per test-run template |
| Takedown | **Soft takedown** — giữ hostname sống, canary path trả `410 Gone` | Không cần hạ cả site, không cần domain thứ hai |

### 7.1 Ba lớp hành vi và cách chạm tới

| Lớp | Agent tiêu biểu | Cách kích | Observation window |
|---|---|---|---|
| Live user-triggered fetch | ChatGPT-User, Claude-User, Perplexity-User | Dán URL vào chat, thủ công | phút |
| Search indexing | OAI-SearchBot, Claude-SearchBot, PerplexityBot | Thụ động, cần URL ổn định + sitemap | ngày |
| Training crawl | GPTBot, ClaudeBot, CCBot, Bytespider | Thụ động, cần URL ổn định + thời gian | tuần |

Có domain ổn định → cả 3 lớp khả thi. Nhưng lớp 2 và 3 **không thể ép nhanh** — phải chấp nhận
canary URL sống lâu và kiên nhẫn. Thiết kế phải tách "test run có kích" khỏi "observation liên tục".

### 7.2 Matrix thực tế

- **On-demand (tay):** 2–3 driver × 5 page variant = 10–15 run/phiên, ~30 phút.
- **Thụ động (tự động):** mọi request tới canary URL đều được ghi, không cần thao tác.
- **Control group (script):** 11 case synthetic, chạy bằng script Python, dùng để verify pipeline.

### 7.3 Yêu cầu mới phát sinh từ workflow thủ công

Dashboard **không phải read-only**. Cần form nhập:
`test_run_id` → câu trả lời AI (paste nguyên văn) → marker có/không → ghi chú.
Đây là nguồn duy nhất của cột `marker_returned`. Không có nó thì không chấm được outcome.

---

## 8. Câu hỏi chưa có lời giải

1. Domain sẽ mua ở đâu và tên gì? Tên miền **không được gợi ý đây là lab/test/bot** — nếu AI đoán ra mục đích, hành vi quan sát được có thể bị lệch.
2. Site canary hiển thị nội dung gì? Cần đủ "giống site thật" để crawler coi là đáng index, nhưng không được chứa dữ liệu thật/nhạy cảm. Nghiên cứu Duke/CMU dùng template portfolio hoặc company site.
3. Có submit sitemap vào Search Console / Bing Webmaster không? Ảnh hưởng lớn tới tốc độ lớp 2 và 3 ghé thăm — nhưng cũng làm nhiễu (traffic đến vì được submit, không phải vì tự phát hiện).
---

## 9. Hosting: local, bật/tắt theo ngày — đã chốt

Không dùng VPS. Origin chạy trên máy cá nhân, bật/tắt theo ngày. Kèm 4 biện pháp bù:

### 9.1 Uptime ledger — bắt buộc

Heartbeat 60s ghi trạng thái ingress. Mọi kết luận âm phải kèm độ phủ:

```
origin_fetch_not_observed (coverage 34% / 14d)
```

Không có ledger → không phân biệt được "AI không đến" với "AI đến lúc máy tắt" → kết luận lớp 2/3 vô giá trị.
Chi phí: 1 bảng 2 cột + 1 cron 60s.

### 9.2 Uptime là thuộc tính của test run, không phải của hệ thống

- Lớp 1: cần vài phút uptime.
- Lớp 2/3: test run khai báo `observation_window`, giữ máy chạy trong đúng window đó rồi tắt.

Khớp với workflow bật/tắt theo ngày. Không cần 24/7 vĩnh viễn.

### 9.3 Mã lỗi khi origin down

Named tunnel + `cloudflared` không chạy → Cloudflare trả 5xx (1033/530), không phải 404.
Crawler coi 5xx là lỗi tạm, retry; ít phạt hơn 404. Máy tắt không bị hiểu là trang đã chết.

### 9.4 Windows: chống sleep

Sleep/hibernate giết tunnel âm thầm. Chạy `cloudflared` như Windows service + tắt sleep
(`powercfg`) trong observation window. Heartbeat sẽ lộ ra nếu quên.

### 9.5 Kỳ vọng đã điều chỉnh

| Lớp | Với local on/off |
|---|---|
| Live fetch | đầy đủ, không ảnh hưởng |
| Search index | được, chậm, phải đọc kèm coverage |
| Training crawl | được, rất chậm, cần window dài + coverage cao |

Không mất lớp nào vĩnh viễn. Domain ổn định mới là yếu tố quyết định, không phải uptime 100%.
