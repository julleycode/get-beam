# Việc cần làm · Việc cần check · Việc đã bỏ qua

Ngày: 2026-07-28 23:15 · Branch: `dev_nhantc2`
Nối tiếp: [code-review-260728-2212-agents-visitors-ai-identification-report.md](./code-review-260728-2212-agents-visitors-ai-identification-report.md)
Trạng thái: **chưa sửa dòng code nào** — toàn bộ mới ở mức đánh giá + đo prod

---

## A. Kết quả tra doc vendor (đã xong)

Câu hỏi: `oai-searchbot` và `claude-searchbot` có phải on-demand không?
Trả lời: **Không. Cả hai là indexer.** Beam đang xếp sai.

| Token | Doc vendor | Beam xếp | Đúng? |
|---|---|---|---|
| `chatgpt-user` | *"When users ask ChatGPT… it may visit a web page"*; *"not used for crawling the web in an automatic fashion"* | on-demand | ✅ |
| `oai-searchbot` | *"used to surface websites in search results in ChatGPT's search features"* — crawler tự động | on-demand | ❌ → **index** |
| `claude-user` | Lấy trang khi user hỏi Claude | on-demand | ✅ |
| `claude-searchbot` | Crawl dựng **indexed corpus** cho search, không train model | on-demand | ❌ → **index** |
| `perplexity-user` | Kích bởi câu hỏi cụ thể, lấy nội dung theo yêu cầu | on-demand | ✅ |
| `perplexitybot` | Crawler index | (không có trong on-demand) | ✅ |

**Nguồn:**
- [OpenAI — Bots docs](https://developers.openai.com/api/docs/bots) (primary, doc chính chủ)
- [Search Engine Land — Anthropic clarifies how Claude bots crawl](https://searchengineland.com/anthropic-claude-bots-470171)
- [Search Engine Journal — Anthropic's Claude Bots](https://www.searchenginejournal.com/anthropics-claude-bots-make-robots-txt-decisions-more-granular/568253/)
- [xSeek — Perplexity user agents](https://www.xseek.io/docs/perplexity-user-agents)

Khớp bảng 3.1 của `plan/tham_khảo`. Kết luận: **2/5 token sai**, đủ căn cứ sửa.

⚠️ Anthropic: chưa đọc được trang doc chính chủ (`support.anthropic.com`), mới qua 2 nguồn thứ cấp **nhất quán với nhau**. Đủ tin để sửa, nhưng nếu muốn tuyệt đối thì đọc trực tiếp trang Anthropic.

---

## B. Việc cần làm

### P0-1 · Sửa tier 2 searchbot — ✅ ĐÃ LÀM (28-07 23:40, chưa commit)

Thực tế phải sửa **4 file**, không phải 2 dòng như dự kiến ban đầu:

| File | Đổi gì |
|---|---|
| `apps/api/services/agent_classifier.py` | Bỏ `oai-searchbot` + `claude-searchbot` khỏi `_ON_DEMAND_TOKENS` (còn 3 token `*-user`); viết lại comment kèm căn cứ doc vendor |
| `apps/api/services/agent_fetch_beacon.py` | Bỏ cổng `noop` cho index-tier → index-tier vẫn được ghi; cập nhật docstring module + hàm |
| `tests/unit/test_agent_fetch_events.py` | Chuyển 2 token sang `_EXPECTED_INDEX` |
| `tests/unit/test_agent_fetch_beacon.py` | Đổi 2 test `*_noop` thành assert "được ghi, tier=index"; thêm test mới cho `oai-searchbot` |

**Vì sao phải đụng beacon:** crawler không chạy JS nên pixel không bao giờ bắn cho chúng — beacon là đường **duy nhất** thấy được index-tier. Nếu chỉ đổi tier, beacon sẽ `noop` và `oai-searchbot` biến mất hoàn toàn khỏi tab Agents. Đổi bug này lấy bug khác.

**Đã đảo ngược một AC có chủ đích:** `AC-H5-2` (index-tier → noop). Lý do gốc của AC là *"đừng bịa tín hiệu handoff"* — việc đó do cột `tier` + bộ lọc `tier == 'on-demand'` trong sweep lo, `noop` chỉ là lớp thừa. Endpoint có auth shared-secret nên không mở rộng bề mặt tấn công.

**Kiểm chứng:** `1425 passed, 2 skipped` trên `tests/unit/`. 3 fail ở `test_enrichment_fallback.py` **đã chứng minh có sẵn từ trước** bằng cách stash thay đổi rồi chạy lại — vẫn fail y hệt. Không liên quan agent.

**Lưu ý môi trường:** `.venv` thiếu test deps (khai trong `pyproject.toml [project.optional-dependencies] test` nhưng chưa cài). Đã cài `pytest`, `pytest-asyncio`, `fakeredis` vào `.venv`.

**Còn lại:** 7 dòng `oai-searchbot` cũ trên prod vẫn mang `tier='on-demand'` — xem C2.

<details><summary>Mô tả gốc trước khi làm</summary>
- **Ở đâu:** `apps/api/services/agent_classifier.py:57-59` — `_ON_DEMAND_TOKENS`
- **Làm gì:** bỏ `oai-searchbot` và `claude-searchbot` khỏi set
- **Vì sao:** doc vendor nói đó là indexer. Hiện 7/22 (32%) lượng "on-demand" là crawler → sweep bịa tín hiệu "người thật đứng sau AI". Vi phạm chính nguyên tắc file đó tuyên bố ở dòng 50-53
- **Verify:** `tests/unit/test_agent_classifier.py` — có sẵn test completeness `test_tier_map_covers_all_vendor_tokens`; cần thêm case khẳng định 2 token này = `index`
- **Rủi ro:** thấp. Không đụng schema/auth/API. Sau sửa: on-demand còn 15 (11 chatgpt-user + 4 claude-user)
- **Lưu ý:** dữ liệu 7 dòng `oai-searchbot` cũ trong prod vẫn mang `tier='on-demand'` — cần quyết định có backfill lại không

</details>

### P0-2 · Làm cho "0" có nghĩa
- **Ở đâu:** `agent_handoff_correlation.py` (đã có sẵn counters `processed`/`linked` ở return, chưa ai đọc) + `apps/web/src/app/dashboard/agents/page.tsx:171-173`
- **Làm gì:** (a) đưa `processed`/`linked` ra chỗ quan sát được; (b) tách `high`/`medium` trên UI thay vì một số trần
- **Vì sao:** hiện `0` không phân biệt được "chạy đúng, chưa có data" với "hỏng". Đã phải chạy SQL tay lên prod **2 lần** chỉ để trả lời câu đó
- **Verify:** dựng 1 cặp fetch↔click giả trong test, xác nhận UI hiện đúng phân tách

### P1-1 · Dedup `agent_fetch_events`
- **Ở đâu:** `apps/api/models/agent_fetch_event.py:29-35`
- **Vấn đề:** 2 `Index` thường, **không cái nào `unique`**. Prod có 3 dòng `chatgpt-user` trùng hệt timestamp `26-07 04:17:47`
- **Cần migration** → không đi lối quick-fix, phải qua plan

### P1-2 · Có traffic AI thật
- Hiện 22 fetch đều là tự test beacon (2 burst bắn 3 UA trong ~2 giây). **Tính năng chưa từng chạy trên traffic thật**
- Mượn phương pháp canary + prompt thủ công của `plan/tham_khảo`, chạy thẳng trên Beam

### P2 · Nhóm còn lại (thật nhưng chưa cắn ở lưu lượng này)
| Mã | Vấn đề | File |
|---|---|---|
| F3 | `frozenset` + hash randomize → phân loại không tất định giữa các lần restart | `agent_classifier.py:23-39, 88-96` |
| F4 | Match substring không biên từ → UA chứa URL `.../gptbot-...` bị nhận nhầm | `agent_classifier.py:90` |
| F5 | Ghi link quá sớm, khoá mất bản khớp tốt hơn (sweep 10′, cửa sổ 30′) | `agent_handoff_correlation.py:177-190` |
| F6 | Query ứng viên không `LIMIT`, full ORM, trong vòng lặp 20 lần | `agent_handoff_correlation.py:209-217` |

### Hoãn
- **F2 marker** — referrer vẫn sống (`ai_source=chatgpt:1`, có referrer google/linkedin), nên không gấp về đúng/sai. Là chuyện độ chính xác + sản lượng. Xem lại sau khi có traffic thật
- **F1 hardening naive/aware** — không hỏng (prod UTC, skew 0). Gộp vào lần sửa khác cho rẻ

---

## C. Việc cần check

| # | Cần check | Vì sao quan trọng |
|---|---|---|
| C1 | Doc chính chủ Anthropic về `Claude-SearchBot` | Mới có 2 nguồn thứ cấp |
| C2 | 7 dòng `oai-searchbot` cũ trong prod: backfill `tier` hay để nguyên? | Ảnh hưởng số liệu lịch sử dashboard |
| C3 | API prod restart bao lâu/lần? | APScheduler `interval` fire ở +interval **tính từ boot**. Restart <10′/lần thì sweep **không bao giờ chạy**. Railway scale-to-zero là rủi ro thật, chưa loại trừ |
| C4 | Vì sao chỉ **1** visitor có `ai_source` trên toàn prod? | Ít bất thường. Có thể do lưu lượng thấp, hoặc `first_touch_referrer` không được set đúng đường |
| C5 | 2 burst 3-UA-trong-2-giây là tự test hay có thật? | Nếu có thật thì là pattern đáng nghi, cần detector riêng |
| C6 | `google-cloudvertexbot` đã bao giờ xuất hiện chưa? | Đang allowlist nhưng prod chưa thấy dòng nào |

---

## D. Việc đã BỎ QUA (chưa đụng tới)

Ghi rõ để không ai tưởng đã review hết.

### Code chưa đọc dòng nào
| File | LOC | Ghi chú |
|---|---|---|
| `services/agent_intent_signals.py` | 222 | Lớp tính intent, chưa xem |
| `services/agent_verification.py` | ? | IP/rDNS verification — lõi của "phân biệt AI thật/giả", **chưa xem** |
| `services/agent_aggregator.py` | ? | Analytics tab Agents |
| `services/agent_company_resolution.py` | ? | Agent → company |
| `services/agent_visitor_filters.py` | ? | |
| `services/cadence_bot_flag.py` + `_sweep.py` | ? | Detector hành vi |
| `services/bot_filter.py` | ? | Lớp drop |
| `services/referral_activation.py` | 196 | |
| `routers/agent_gateway.py` | 100 | Mới đọc docstring của service, chưa đọc router |
| `routers/agent_mcp.py` | 180 | Chưa đọc thân |
| `routers/agent_profile.py` | 92 | |
| `apps/pixel/src/tracker.js` | ? | Lớp thu thập gốc |

### Đọc nông
- `routers/visitors.py` (1314 LOC) — chỉ soát phần giao với agent, **không review từng dòng**
- `dashboard/visitors/page.tsx` (851 LOC) — chỉ grep, chưa đọc
- `dashboard/agents/page.tsx` (361 LOC) — chỉ grep, chưa đọc

### Loại kiểm tra chưa làm
- **Chưa chạy test suite nào.** Không finding nào được chứng minh bằng test đỏ
- **Chưa review bảo mật** (STRIDE/OWASP) dù đây là bề mặt tracking + PII
- **Chưa đo hiệu năng** — F6 suy từ đọc code, chưa benchmark
- **Chưa review DDL migration** (do scope tự chọn) — chỉ kiểm chuỗi + head
- **F3 và F5 chưa chứng minh bằng thực nghiệm** — suy từ đọc code

### Chỗ tôi đã sai trong quá trình (giữ lại để đối chiếu)
| Nhận định ban đầu | Thực tế |
|---|---|
| F1 timezone là lỗi HIGH đang chạy | **Sai** — prod UTC, skew 0 |
| Query `aware_max vs naive_max` chứng minh lệch múi giờ | **Query thiết kế sai** — so max() 2 bảng khác nhịp |
| `Event` có thể thiếu cột `referrer` | **Sai** — có ở dòng 24 |
| Beacon hardcode `tier='on-demand'` (giả thuyết user) | **Sai chỗ** — beacon gọi `classify_tier()` đúng; gốc ở classifier |

---

## Câu hỏi chưa giải quyết

1. **C3 — API prod restart bao lâu/lần?** Chưa loại trừ được khả năng sweep không bao giờ chạy do interval reset theo boot. Đây là giả thuyết duy nhất còn sống có thể giải thích `0 link` bằng lỗi kỹ thuật thay vì thiếu data.
2. **C2 — backfill tier cũ hay không?** Cần quyết định trước khi sửa P0-1, vì sau khi sửa thì 7 dòng cũ thành không nhất quán với logic mới.
3. **C4 — chỉ 1 `ai_source` trên toàn prod có bình thường không?** Nếu đường ghi `first_touch_referrer` có vấn đề thì F2 đổi hẳn kết luận (referrer không "sống" như tôi kết luận).
4. Có muốn tôi review nốt nhóm file ở mục D không, hay chốt scope ở đây và chuyển sang sửa?
