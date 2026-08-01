# Code Review — Tab Agents + Visitors: bài toán phân biệt AI / người sau AI / định danh

Ngày: 2026-07-28 · Branch: `dev_nhantc2` · Loại: **analysis-only, không sửa code**
Scope chốt: Backend + Frontend + UX/GEO · migration chỉ check rủi ro prod · 1 report Beam + phụ lục đối chiếu Lab

---

## TL;DR

Code **tốt hơn nhiều** so với mô tả trong `process/context/all-context.md`: toàn bộ lớp Handoff Detection + agent-gateway + MCP đã build xong và có test. Doc context ghi "not yet scaffolded on disk" là **sai**.

Nhưng: **tín hiệu chủ lực "ai là người đứng sau AI" đang đứng trên một heuristic thời gian, không có marker định danh.** Đây là rủi ro thiết kế lớn nhất, và đúng là thứ mà Lab trong `tham_khảo` đã chủ động loại bỏ bằng one-time-use marker.

Kèm 1 lỗi tiềm ẩn im lặng (F1) có thể làm tính năng **trả về 0 link mà không báo lỗi** trên production.

| Mức | Số finding |
|---|---|
| HIGH | 2 (F1 timezone, F2 thiếu marker) |
| MEDIUM | 5 |
| LOW | 1 |

> **CẬP NHẬT 28-07 23:10 — đã đo trên prod.** F1 **bị bác bỏ** (prod TZ=UTC, skew=0). Phát sinh 2 finding mới nặng hơn (F9 tier sai, F10 thiếu dedup). Xem `## Cập nhật sau khi đo prod` ở cuối file — phần đó thay thế phần đánh giá mức độ ở trên.

---

## Findings

### F1 — ~~HIGH~~ → **BÁC BỎ**, hạ xuống LOW (phòng ngừa) · Lệch naive/aware datetime

> **Đo trên prod 28-07:** `SHOW timezone`=UTC, `skew`=`00:00:00`. **Không lệch.** Giả thuyết sai.
> Phần còn đúng: sự mong manh naive-vs-aware là thật, nhưng chỉ là hardening phòng ngừa, không phải bug đang chạy. Nguyên văn phân tích ban đầu giữ lại bên dưới để đối chiếu.

**Bằng chứng:**
- [event.py:51](apps/api/models/event.py#L51) — `created_at: Column(DateTime, default=func.now())` → **naive**
- Base model — `DateTime(timezone=True), server_default=func.now()` → **aware**; `agent_fetch_events` dùng Base
- [agent_handoff_correlation.py:199-216](apps/api/services/agent_handoff_correlation.py#L199-L216) — ép `fetch_at` về naive rồi so với `Event.created_at`

Postgres ghi `now()` (timestamptz) vào cột `timestamp without time zone` → giá trị bị quy đổi theo **session TimeZone**, không bắt buộc UTC.

**Kiểm chứng thực tế trên máy này:** `SHOW timezone` → `UTC`; `now()::timestamp` == `now() AT TIME ZONE 'UTC'` → **hiện đang đúng**.

Nhưng đúng vì môi trường, **không phải vì code đảm bảo**. Nếu Postgres prod đặt `Asia/Ho_Chi_Minh`, cửa sổ correlation 30 phút lệch **7 tiếng** → không bao giờ có link nào được ghi, **không exception, không log lỗi**.

**Đây đúng lớp lỗi G1 của Lab**: kết luận âm không phân biệt được với pipeline chết. Beam hiện **không có** tín hiệu nào để phân biệt "không có handoff" vs "correlation hỏng".

---

### F2 — HIGH (kiến trúc) · "Người sau AI" là suy đoán thời gian, không có marker

Link mà AI nhìn thấy và trả cho người dùng là **URL trần**:
- [agent_gateway.py:99,133](apps/api/services/agent_gateway.py#L99) — `url=site.url`, `url=raw.get("url")`
- [agent_gateway.py:186-192](apps/api/services/agent_gateway.py#L186-L192) — links block cũng URL trần

Không có correlation token, không có per-fetch marker. Nên toàn bộ khả năng quy "human X đứng sau agent Y" dựa vào **3 điều kiện mềm** trong [agent_handoff_correlation.py](apps/api/services/agent_handoff_correlation.py):

1. cùng site
2. `classify_ai_source(referrer)` khớp vendor family (map 3 dòng, [L42-46](apps/api/services/agent_handoff_correlation.py#L42-L46))
3. click rơi trong 30 phút sau fetch

Cả 3 đều **không định danh**. Hai người dùng khác nhau hỏi cùng ChatGPT về cùng trang trong cùng 30 phút → gán nhầm, không cách nào phát hiện.

Điều kiện (2) còn phụ thuộc `document.referrer` — mà ChatGPT/Perplexity ngày càng dùng redirect trung gian hoặc `noreferrer`. Referrer mất → link không bao giờ được tạo.

**Đối chiếu Lab:** brainstorm report mục 1 gọi `test_run_id` nhúng trong path là *"correlation key hoàn hảo"*, và G4 bắt marker phải one-time-use. Lab **chọn deterministic vì biết heuristic không đủ tin**. Beam đang ở đúng chỗ Lab đã bỏ.

Có mầm mống marker rồi: [agent_fetch_beacon.py:34](apps/api/services/agent_fetch_beacon.py#L34) — token `"p" + base36(unix-seconds)` do `pricing-overview/route.ts` mint. Nhưng chỉ 1 trang, và mã hoá **thời gian**, không phải danh tính/run.

---

### F3 — MEDIUM · Phân loại không tất định → phá replay

[agent_classifier.py:23-39](apps/api/services/agent_classifier.py#L23-L39) dùng `frozenset` cho token, [L88-96](apps/api/services/agent_classifier.py#L88-L96) duyệt `for token in tokens`.

Thứ tự duyệt `frozenset` phụ thuộc hash chuỗi — mà Python **randomize hash mỗi process** (`PYTHONHASHSEED`). UA chứa **nhiều token cùng vendor** (ví dụ UA giả `"GPTBot ChatGPT-User"`) → `product_or_ua_token` trả về **khác nhau giữa các lần restart server**.

Hệ quả dây chuyền: `classify_tier()` đọc chính token đó; `chatgpt-user` là on-demand còn `gptbot` là index → **tier lật ngẫu nhiên** → sweep handoff có chạy hay không cũng ngẫu nhiên.

Vi phạm trực tiếp **INV-2 của Lab** (detector = pure function, replay được). Hàm *pure* nhưng **không tất định** — đủ để mất khả năng chạy lại.

UA giả không phải giả định xa: control group của Lab (mục 3.5) có sẵn case `UA spoof (UA=GPTBot từ IP local)`.

---

### F4 — MEDIUM · Match substring không có biên từ

[agent_classifier.py:90](apps/api/services/agent_classifier.py#L90) — `if token in ua`.

UA bot thường mang URL tự giới thiệu (`+https://...`). Một scanner có UA chứa `+https://example.com/gptbot-detector` → **bị phân loại thành OpenAI GPTBot**. Ghi nhầm vào `agent_visits`, làm bẩn cả dashboard lẫn analytics.

---

### F5 — MEDIUM · Ghi link quá sớm, khoá mất bản khớp tốt hơn

Sweep chạy mỗi **10 phút** ([config.py:720](apps/api/config.py#L720)), loại bỏ fetch đã có link bằng `~link_exists` ([L177-190](apps/api/services/agent_handoff_correlation.py#L177-L190)).

Mỗi lần sweep chỉ thấy click **đã tồn tại tại thời điểm đó**, nhưng cửa sổ là 30 phút. Kịch bản:

- T+3′ có click lệch trang → `medium`
- sweep T+10′ ghi `medium`, fetch bị loại vĩnh viễn
- T+12′ có click **đúng trang** → lẽ ra `high` → **không bao giờ được xét**

→ Hệ thống **hạ điểm tin cậy một cách có hệ thống** khi click yếu đến trước click mạnh.

---

### F6 — MEDIUM · Query ứng viên không giới hạn

[agent_handoff_correlation.py:209-217](apps/api/services/agent_handoff_correlation.py#L209-L217) — `select(Event)` lọc site + pageview + khoảng 30 phút, **không `LIMIT`**, load full ORM object, và nằm **trong vòng lặp** tới 20 fetch event.

Site lưu lượng cao: 20 query, mỗi query có thể kéo hàng chục nghìn row vào RAM. Index `ix_events_site_created` có ([event.py:56](apps/api/models/event.py#L56)) nên không quét bảng, nhưng **khối lượng trả về vẫn không bị chặn**.

---

### F7 — MEDIUM · UI trình bày suy đoán như sự thật

[agents/page.tsx:171-173](apps/web/src/app/dashboard/agents/page.tsx#L171-L173) — `Human handoffs detected: {data.handoff_links_count}`.

Backend ghi **cả `high` lẫn `medium`** ([L61-83](apps/api/services/agent_handoff_correlation.py#L61-L83)). UI gộp thành **một con số trần**, chữ "detected" hàm ý chắc chắn.

Vi phạm **INV-3 của Lab**: kết luận phải luôn kèm độ phủ / độ tin cậy. Người dùng không có cách nào biết con số đó là 5 khớp chắc hay 5 phỏng đoán 30 phút.

---

### F8 — LOW · Bẫy ngầm khi mở rộng Google

[agent_classifier.py:38](apps/api/services/agent_classifier.py#L38) đã allowlist vendor `google`, kèm chú thích KG-3 "promote to on-demand sau khi xác nhận UA thật".

Nhưng [`_VENDOR_FAMILY_MAP`](apps/api/services/agent_handoff_correlation.py#L42-L46) **không có key `google`** → nếu ai đó promote theo đúng hướng dẫn backlog, correlation `return None` **im lặng**, không ai biết.

---

## Rủi ro migration trên prod (theo scope đã chốt)

Không đọc DDL. Chỉ soát rủi ro thật:

| Hạng mục | Kết quả |
|---|---|
| DB dev local | `alembic current` → `a2f8d61c9e37 (head)` — **đã apply hết 51 migration** |
| Head doc ghi | `e6b2d4a1c837` → **stale 4 migration** |
| Chuỗi pending thật | 17 ID (doc ghi "12", liệt kê 13) |
| Toàn bộ tab Agents | Phụ thuộc bảng/cột trong chuỗi chưa apply prod |

**Biện pháp bảo vệ hiện có là đủ:** mọi surface đều bị chặn bởi flag mặc định OFF — `agent_detection_enabled` ([config.py:320](apps/api/config.py#L320)), `agent_gateway_enabled` ([L336](apps/api/config.py#L336)), `cadence_bot_flag_enabled` ([L359](apps/api/config.py#L359)). Code không thể đọc cột chưa tồn tại khi flag còn tắt.

**Rủi ro còn lại = thứ tự bật flag**, không phải bản thân migration. Bật flag trước khi apply migration → crash ngay. Không có guard nào ở code chặn việc này.

---

## Đánh giá lớp UX/GEO (câu hỏi #3)

Phần này Beam làm **tốt và đi trước** so với kỳ vọng:

| Thành phần | Trạng thái |
|---|---|
| `llms.txt` route (web) | Có |
| Agent manifest + offers feed | Có, một nguồn sự thật ([agent_gateway.py](apps/api/services/agent_gateway.py)) |
| MCP JSON-RPC server | Có ([agent_mcp.py](apps/api/routers/agent_mcp.py), 180 LOC) |
| Nội dung do khách tự soạn | Có (`agent_profiles`) |
| Chống dò site_id | Tốt — 5 trường hợp lỗi đều trả 404 đồng nhất |

Nghĩa là: **phần "làm cho AI tìm thấy và trả link về site" đã xong.** Phần thiếu đúng một mắt xích cuối — **link đó không mang gì để định danh khi người ta click vào** (F2).

Đây là kết luận quan trọng nhất của review: vấn đề không nằm ở chỗ dụ AI trả link, mà ở chỗ **thiếu marker trên chính cái link đó**.

---

## Phụ lục — Đối chiếu Lab (`plan/tham_khảo`)

Lab là dự án riêng, greenfield, không dùng chung code. Dùng 3 bất biến của nó làm thước đo cho Beam:

| Bất biến Lab | Beam đạt? | Ghi chú |
|---|---|---|
| **INV-1** Evidence-first, ghi trước phân loại | **Đạt một phần** | `agent_fetch_events` là append-only ✓. Nhưng không niêm phong snapshot IP-range/rDNS vào bundle → không tái lập được |
| **INV-2** Detector = pure function, replay được | **Không đạt** | Pure ✓ nhưng **không tất định** (F3). Thiếu version của tập token/IP-range trong evidence |
| **INV-3** Kết luận âm phải kèm coverage | **Không đạt** | F1 + F7. Không phân biệt "không có handoff" với "correlation hỏng" |

Ba lỗ hổng Lab tự nêu, chiếu sang Beam:

| Lab | Áp vào Beam |
|---|---|
| G1 negative result mơ hồ | **Trúng** — F1, không có ingress/health cho sweep |
| G4 marker hygiene | **Trúng nặng** — Beam chưa có marker (F2) |
| G5 fetch không quy được vendor | **Trúng** — không có bucket `unattributed`, rơi hết vào "không link" |

**Điểm Beam hơn Lab:** đã có surface agent-facing thật (manifest/MCP/llms.txt) chạy trên traffic thật — Lab mới ở mức plan. Guardrail tách emailability của Beam ([agent_handoff_correlation.py:14-18](apps/api/services/agent_handoff_correlation.py#L14-L18)) chặt và có tripwire test, Lab không có khái niệm tương đương.

---

## Định hướng test / kiểm chứng

Xếp theo tỉ lệ giá trị/chi phí:

| # | Kiểm chứng | Cách làm | Chứng minh điều gì |
|---|---|---|---|
| T1 | Timezone prod | Chạy `SHOW timezone` trên **Postgres prod**, so `now()::timestamp` vs `now() AT TIME ZONE 'UTC'` | Đóng/mở F1 ngay lập tức. Rẻ nhất, giá trị cao nhất |
| T2 | Tính tất định của classifier | Chạy `classify_agent` trên UA đa-token với `PYTHONHASHSEED` khác nhau, assert kết quả không đổi | F3 — điều kiện cần cho replay |
| T3 | Biên từ trong UA | Fixture: UA chứa `+https://x.com/gptbot-detector`, assert **không** classify | F4 |
| T4 | Sweep ghi sớm | Fixture: click yếu T+3′, sweep T+10′, click mạnh T+12′, sweep T+20′ → assert confidence cuối là `high` | F5 — hiện sẽ **fail** |
| T5 | Chặn khối lượng query | Sinh 50k pageview trong cửa sổ, đo RAM + thời gian sweep | F6 |
| T6 | Health cho kết luận âm | Thêm counter `processed` vs `linked` vào log/dashboard, cảnh báo khi `processed>0, linked==0` kéo dài | Bịt lớp G1 — biến lỗi im lặng thành lỗi ồn |
| T7 | Marker end-to-end | Gắn token 1 lần dùng vào URL trong offers feed → hỏi ChatGPT/Perplexity → xem token có về không | Kiểm chứng F2 bằng thực nghiệm, đúng phương pháp Lab |

T1 và T6 nên làm trước — cả hai đều biến rủi ro im lặng thành quan sát được, không cần đổi kiến trúc.

T7 chính là chỗ **Lab và Beam gặp nhau**: có thể chạy thí nghiệm marker của Lab ngay trên surface agent-gateway thật của Beam, không cần dựng site canary riêng.

---

## Việc KHÔNG làm trong review này

- Không sửa code (scope: analysis-only)
- Không đọc 51 file DDL (scope đã chốt)
- Không chạy test suite — findings đến từ đọc code + kiểm chứng DB trực tiếp, chưa có finding nào được xác nhận bằng test đỏ
- Chưa review `routers/visitors.py` (1314 LOC) và `visitors/page.tsx` (851 LOC) ở mức dòng — mới soát phần giao với bài toán agent

---

## Cập nhật sau khi đo prod (28-07 23:10)

Chạy 9 query đọc trên Postgres prod. Kết quả **đảo lại đáng kể** phần đánh giá ban đầu.

### Đã đóng

| Finding | Kết luận | Bằng chứng |
|---|---|---|
| F1 timezone | **Bác bỏ** | `SHOW timezone`=UTC, `skew`=`00:00:00`. Dòng `aware_max vs naive_max` lệch 2h37m là **query thiết kế sai** (so max() 2 bảng khác nhịp), không phải bằng chứng — offset múi giờ phải ra đúng `07:00:00` |
| `handoff_links=0` do job hỏng | **Bác bỏ** | Job đăng ký vô điều kiện, 10′/lần, không flag chặn ([scheduler.py:495-503](apps/api/jobs/scheduler.py#L495-L503)). 0 link là **đúng với data** |
| F2 nhánh "referrer bị bỏ" | **Bác bỏ** | Referrer sống: `ai_source=chatgpt:1`, và có referrer `google.com`/`linkedin.com`/`getbeam.fyi` trong events |

### Trạng thái dữ liệu thật

```
22 fetch on-demand · 1 visitor ai_source · 0 handoff link · 8 "match" đều là nhiễu
```

8 dòng match khi mô phỏng correlation bằng SQL, **không dòng nào là handoff thật**:
- 2 dòng: owner tự login (`getbeam.fyi/sign-in/sso-callback`) — self-traffic
- 1 dòng: referrer `linkedin.com` trùng cửa sổ 30′ — trùng giờ ngẫu nhiên
- 5 dòng: **cùng 1 pageview** (referrer `google.com`) nhân bản qua JOIN với burst 5 fetch

Visitor `ai_source=chatgpt` duy nhất **không nằm trong** cặp nào.

22 fetch chia: `chatgpt-user` 11 · `oai-searchbot` 7 · `claude-user` 4. Hai burst 28-07 `07:14:27-29` và `07:21:04-06` bắn cả 3 UA trong ~2 giây → **pattern tự test beacon, không phải organic**.

**Kết luận: tính năng chưa từng chạy trên traffic thật.** Không thể kết luận đúng/sai từ dữ liệu này.

### F9 — HIGH (mới) · Hai searchbot bị xếp sai tier → sweep chạy trên traffic crawler

[agent_classifier.py:57-59](apps/api/services/agent_classifier.py#L57-L59) xếp `oai-searchbot` và `claude-searchbot` vào `_ON_DEMAND_TOKENS`.

Cả hai là **indexer**, không phải live-fetch-theo-truy-vấn. **Đã tra doc vendor 28-07, xác nhận dứt điểm:**

| Token | Doc vendor nói | Beam xếp | Đúng? |
|---|---|---|---|
| `chatgpt-user` | *"When users ask ChatGPT… it may visit a web page"* — không crawl tự động | on-demand | ✅ |
| `oai-searchbot` | *"used to surface websites in search results in ChatGPT's search features"* — crawler tự động | on-demand | ❌ **phải là index** |
| `claude-user` | Lấy trang khi user hỏi Claude | on-demand | ✅ |
| `claude-searchbot` | Crawl để dựng **indexed corpus** cho search | on-demand | ❌ **phải là index** |
| `perplexity-user` | Kích bởi câu hỏi cụ thể, lấy nội dung theo yêu cầu | on-demand | ✅ |

Nguồn: [OpenAI bots docs](https://developers.openai.com/api/docs/bots) (primary) · [Search Engine Land — Anthropic](https://searchengineland.com/anthropic-claude-bots-470171) · [Search Engine Journal — Anthropic](https://www.searchenginejournal.com/anthropics-claude-bots-make-robots-txt-decisions-more-granular/568253/) · [xSeek — Perplexity](https://www.xseek.io/docs/perplexity-user-agents). Khớp luôn bảng 3.1 của `plan/tham_khảo`.

**2/5 token sai.** Không phải chuyện mặc định an toàn nữa — là sai so với doc vendor.

Code **vi phạm nguyên tắc do chính nó tuyên bố** ở [L50-53](apps/api/services/agent_classifier.py#L50-L53): *"Mislabeling a crawler as on-demand would fabricate a human-intent signal, so the safe default is index."*

Tác động đo được: **7/22 = 32%** lượng on-demand thật ra là crawler → sweep cố quy crawler về "người thật đứng sau" → đúng 5 dòng nhiễu trong dữ liệu.

Beacon **không** liên quan — [agent_fetch_beacon.py:78-80](apps/api/services/agent_fetch_beacon.py#L78-L80) gọi `classify_tier()` và lọc index-tier đúng.

### F10 — MEDIUM (mới) · `agent_fetch_events` không có dedup

[agent_fetch_event.py:29-35](apps/api/models/agent_fetch_event.py#L29-L35) — hai `Index` thường, **không cái nào `unique`**. Prod có 3 dòng `chatgpt-user` trùng hệt timestamp `26-07 04:17:47` → ghi trùng thật. Làm phồng số liệu dashboard và nhân bản ứng viên correlation.

### Xếp lại ưu tiên

| # | Việc | Mức | Lý do |
|---|---|---|---|
| 1 | F9 sửa tier 2 searchbot → `index` | P0 | Sai đúng nghĩa, rẻ, có 3 nguồn xác nhận |
| 2 | F7+ counter `processed`/`linked` + tách confidence trên UI | P0 | Bịt lỗ "0 không phân biệt được đúng/hỏng" — đã phải chạy SQL tay 2 lần vì thiếu nó |
| 3 | F10 dedup | P1 | Số liệu đang phồng |
| 4 | Có traffic AI thật | P1 | Không có thì mọi thứ trên chỉ là suy đoán |
| 5 | F3 tất định · F4 biên từ · F5 ghi sớm · F6 query không chặn | P2 | Thật nhưng chưa cắn ở lưu lượng này |
| 6 | F2 marker | Hoãn | Referrer vẫn sống → không gấp về mặt đúng/sai; là chuyện độ chính xác + sản lượng |
| 7 | F1 hardening naive/aware | Hoãn | Không hỏng; gộp vào lần sửa khác cho rẻ |

---

## Câu hỏi chưa giải quyết

1. **Postgres prod đặt timezone gì?** Chưa truy cập được. Đây là biến quyết định F1 là lý thuyết hay đang hỏng thật.
2. **Đã có traffic agent thật trên prod chưa**, hay mọi thứ mới chạy mock? Nếu chưa có traffic, F1/F5 vẫn còn thời gian sửa trước khi bật flag.
3. **`document.referrer` từ ChatGPT/Perplexity thực tế còn giữ không?** Toàn bộ nhánh (2) của F2 phụ thuộc câu này — cần đo thật, không suy đoán.
4. **Có chấp nhận đổi từ heuristic sang marker không?** Đây là quyết định sản phẩm, không phải kỹ thuật: marker chính xác hơn nhưng phải sửa URL trong offers feed và chấp nhận link dài hơn.
5. Beam và Lab **cuối cùng gộp hay tách**? Nếu gộp, phần lớn phase 4–6 của Lab đã có sẵn hạ tầng trong Beam; nếu tách, Lab nên tránh viết lại `agent_classifier`.
