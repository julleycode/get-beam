---
phase: 6
title: "Canary Test Orchestration"
status: pending
priority: P1
dependencies: [2, 3, 5]
effort: ""
---

# Phase 6: Canary Test Orchestration

## Overview

Nguồn ground truth duy nhất của lab. Tạo test run có URL không đoán được + marker one-time-use,
phục vụ 5 page variant, đối chiếu request quan sát được với câu trả lời AI, và phân biệt
**AI thật sự fetch** với **AI trả lời từ cache**.

## Requirements

**Functional**
- Test run model: provider dự kiến, variant, observation window, canary URL, marker.
- 5 page variant đo 5 hành vi khác nhau.
- robots.txt policy theo từng run (nối vào phase 2).
- Soft takedown: canary path trả `410 Gone`, hostname vẫn sống.
- Outcome scoring qua `gate_outcome` của phase 3 — không có ngoại lệ.
- Marker hygiene: one-time-use, đánh dấu `burned`.

**Non-functional**
- Marker không bao giờ xuất hiện trong log, prompt template, commit, hay dashboard công khai.

## Architecture

### Canary URL

```
https://{hostname}/t/{test_run_id}/{token}
```

`token` = 16 byte random base32. Không đoán được, không liệt kê được.
`test_run_id` nhúng trong path → correlation key hoàn hảo, không cần sessionization xác suất.

### Marker

```
BEAM-CANARY-{8 ký tự base32}
```

Một marker dùng đúng một lần. Sau khi test run kết thúc → `burned=1`, không tái sử dụng.
Nếu marker lọt ra ngoài (chat log, screenshot, commit), AI có thể biết mà không cần fetch → test vô hiệu
và không ai phát hiện. Đây là lý do phải one-time-use.

**Prompt template chỉ chứa URL, tuyệt đối không chứa marker.**

```
Hãy mở chính xác URL dưới đây và trả lại mã BEAM-CANARY xuất hiện trong trang.
{canary_url}
```

### 5 page variant

| Variant | Nội dung | Đo cái gì |
|---|---|---|
| V1 `static` | marker trong HTML tĩnh | baseline fetch |
| V2 `js_only` | marker chỉ render bằng JS sau khi load | có execute JS không |
| V3 `robots_disallow` | marker trong HTML, path bị Disallow trong robots.txt (công bố trước ≥24h) | có tuân robots không |
| V4 `asset_required` | marker chỉ trả sau khi cả ảnh + CSS của run đã được load | resource profile thật |
| V5 `redirect` | 302 → trang chứa marker | xử lý redirect |

Kỳ vọng theo research đã có: không AI crawler nào (trừ Google) execute JS → V2 nên fail với hầu hết.
Nếu V2 pass với một agent, đó là phát hiện đáng giá — ghi nhận, không coi là bug.

### Soft takedown

Thay vì hạ site: giữ hostname sống, canary path của run đó trả `410 Gone` + không chứa marker.
Sau đó hỏi lại AI trong chat mới.

- Trả đúng marker khi path đã 410 và không có request nào tới → `content_served_after_takedown`.
- Đây là bằng chứng cứng về caching, theo phương pháp nghiên cứu Duke/Pitt/CMU.

### Test outcome

```
origin_fetch_observed
origin_fetch_not_observed(coverage=NN%)   -- chuỗi ghép chỉ ở tầng render; DB lưu outcome_code + coverage_pct riêng
marker_returned_without_observed_fetch
fetch_observed_but_marker_not_returned
content_served_after_takedown
multiple_agents_observed
unattributed_fetch_in_window
inconclusive_ingress_unverified
inconclusive_no_answer
```

`inconclusive_no_answer`: hết 2× window mà không có `test_run_answer` nào — run tự đóng (job ở
phase 8), tuyệt đối không được chấm thành `origin_fetch_not_observed` khi chưa có ai nhập kết quả.

`unattributed_fetch_in_window`: có request tới canary trong window nhưng không quy được về vendor nào
(agent chạy trong browser người dùng, qua proxy, hoặc IP cloud ngoài dải công bố). Bucket riêng,
không gộp vào `unknown`.

Mọi outcome đi qua `gate_outcome()` của phase 3.

### Schema

```sql
CREATE TABLE test_run (
  test_run_id       TEXT PRIMARY KEY,
  created_at        TEXT NOT NULL,
  variant           TEXT NOT NULL,      -- static|js_only|robots_disallow|asset_required|redirect
  expected_provider TEXT,
  driver            TEXT NOT NULL,      -- chatgpt|claude|perplexity|passive|control
  canary_token      TEXT NOT NULL,
  marker            TEXT NOT NULL,
  marker_burned     INTEGER NOT NULL DEFAULT 0,
  robots_policy     TEXT NOT NULL,      -- allow|disallow
  takedown_at       TEXT,               -- NULL = chưa takedown
  window_start      TEXT NOT NULL,
  window_end        TEXT NOT NULL,
  edge_config_snapshot_id TEXT NOT NULL,
  status            TEXT NOT NULL,      -- draft|active|observing|scored|closed
  outcome_code      TEXT,               -- chỉ ghi qua gate_outcome()
  coverage_pct      REAL,               -- NULL nếu outcome không cần coverage
  coverage_resolution_minutes INTEGER,
  outcome_scored_at TEXT
);

CREATE TABLE test_run_answer (        -- kết quả nhập tay, phase 7 cung cấp UI
  answer_id     TEXT PRIMARY KEY,
  test_run_id   TEXT NOT NULL REFERENCES test_run(test_run_id),
  submitted_at  TEXT NOT NULL,
  raw_answer    TEXT NOT NULL,        -- paste nguyên văn câu trả lời AI
  marker_found  INTEGER NOT NULL,
  is_post_takedown INTEGER NOT NULL DEFAULT 0,
  note          TEXT
);
```

## Related Code Files

- Create: `src/beam_lab/testrun/models.py`
- Create: `src/beam_lab/testrun/create.py` — sinh token, marker, window
- Create: `src/beam_lab/testrun/variants.py` — render 5 variant
- Create: `src/beam_lab/testrun/scoring.py` — chấm outcome, gọi gate_outcome
- Create: `src/beam_lab/routes/canary.py` — phục vụ `/t/{run}/{token}`
- Create: `src/beam_lab/templates/canary_static.html`
- Create: `src/beam_lab/templates/canary_js.html`
- Create: `src/beam_lab/templates/canary_asset.html`
- Create: `src/beam_lab/static/canary.css` — phục vụ tại `/t/{run}/{token}/a/canary.css`
- Create: `src/beam_lab/static/canary.png` — phục vụ tại `/t/{run}/{token}/a/canary.png`
- Modify: `src/beam_lab/routes/robots.py` — đọc `robots_policy` của run đang active
- Modify: `src/beam_lab/db/schema.sql`
- Create: `tests/test_canary_variants.py`
- Create: `tests/test_marker_hygiene.py`
- Create: `tests/test_outcome_scoring.py`

## Implementation Steps

1. `testrun/create.py`: sinh `test_run_id` (ulid), `canary_token` (16B base32), `marker` (8 ký tự base32, unique toàn bảng). Set window theo variant: live fetch 30 phút, index 7 ngày, training 14 ngày.
2. `routes/canary.py`: resolve run theo `test_run_id` + verify `token`. Token sai → 404 (không phải 403 — không tiết lộ run tồn tại). Run đã `takedown_at` → 410 Gone, body không chứa marker.
3. `testrun/variants.py`: render theo variant.
   - V2: marker đặt trong biến JS, chèn DOM sau `DOMContentLoaded`. HTML thô **không** chứa marker.
   - V4: HTML tham chiếu asset **theo path có run+token**: `/t/{run}/{token}/a/canary.css` và `.../a/canary.png` (file tĩnh toàn cục không correlate được về run vì không khớp pattern `/t/{run}/{token}` của middleware). HTML không chứa marker; trang JS gọi endpoint phụ `/t/{run}/{token}/marker` — endpoint chỉ trả marker khi server đã thấy cả 2 asset được request với cùng `(test_run_id, ip_prefix)` trong 120s gần nhất. Khoá `(run, ip_prefix)` là heuristic chống agent B hưởng khoá mở của agent A; ghi `unlock_key` vào evidence của response marker để audit. **Bắt buộc** đi kèm cache bypass (phase 2) — nếu không asset không bao giờ chạm origin và V4 đo sai.
   - V5: `/t/{run}/{token}` trả 302 → `/t/{run}/{token}/final` chứa marker.
4. `routes/robots.py`: implementation `RobotsPolicyProvider` đọc DB — robots.txt là **hợp nhất (union) policy của mọi run active**, mỗi run `disallow` thêm `Disallow: /t/{run_id}/` riêng nên nhiều run không xung đột. Response kèm `Cache-Control: no-store`, hostname đã có cache bypass (phase 2). Lưu ý phía crawler: chúng tự cache robots.txt (Google ~24h) nên V3 chỉ có ý nghĩa với window index/training (ngày/tuần); với live fetch (30 phút) phải công bố robots.txt ≥24h trước window hoặc không áp dụng V3.
5. `testrun/scoring.py`: gom request theo `test_run_id` trong window, đọc `test_run_answer`, áp bảng quyết định `outcome_code`, **luôn** qua `gate_outcome()`; lưu `coverage_pct` cột riêng. Không có answer nào sau 2× window → `outcome_code = inconclusive_no_answer`, status `closed` (thống nhất với phase 8 — không được chấm `origin_fetch_not_observed` khi chưa có ai nhập kết quả).
6. Marker hygiene: `marker_burned=1` khi run chuyển `closed`. `create.py` từ chối tái dùng marker đã burned. Logger có filter loại marker khỏi mọi log line.
7. Soft takedown: endpoint `/_lab/testrun/{id}/takedown` set `takedown_at`. Sau đó nhập answer mới với `is_post_takedown=1`.
8. Test: marker không xuất hiện trong log output — capture log, grep marker, khẳng định không có.

## Success Criteria

- [ ] Canary URL không đoán được; token sai trả 404.
- [ ] V1 trả marker trong HTML thô. V2 **không** có marker trong HTML thô, chỉ hiện sau JS.
- [ ] V3 làm robots.txt chứa `Disallow` đúng path của run đó, hợp nhất đúng khi nhiều run active; response `no-store`; tài liệu run V3 ghi rõ yêu cầu lead time ≥24h hoặc window dài.
- [ ] V4 chỉ lộ marker sau khi cả CSS và ảnh (path có run+token) đã được request cùng `(test_run_id, ip_prefix)` trong 120s; response marker ghi `unlock_key` vào evidence.
- [ ] V5 redirect đúng, marker ở trang đích.
- [ ] Marker không xuất hiện trong bất kỳ log line nào — test grep khẳng định.
- [ ] Marker đã burned không thể tái sử dụng.
- [ ] Prompt template sinh ra chỉ chứa URL, không chứa marker.
- [ ] Takedown → path trả 410, body không chứa marker, hostname vẫn sống.
- [ ] Trả marker đúng sau takedown mà không có request → `content_served_after_takedown`.
- [ ] Mọi outcome đều đi qua `gate_outcome`; window có coverage thấp → outcome kèm `coverage=NN%`.
- [ ] Request tới canary từ IP không thuộc dải nào → `unattributed_fetch_in_window`, không phải `unknown`.

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| Marker lọt vào log/screenshot → test vô hiệu âm thầm | One-time-use + log filter + test grep. Prompt chỉ chứa URL |
| V4 phức tạp; heuristic `(run, ip_prefix)` sai khi nhiều agent cùng prefix song song | Ghi `unlock_key` vào evidence để audit; TTL 120s. Nếu không chấp nhận state này, hạ V4 xuống optional và ghi rõ AC #6 chỉ đạt 4/5 variant |
| Edge cache trả asset/robots.txt từ cache → V3/V4 đo sai | Cache bypass ở phase 2 là điều kiện tiên quyết của phase này; kiểm `CF-Cache-Status` trước khi mở run |
| AI mở URL qua proxy của vendor → IP không khớp | Đã có bucket `unattributed_fetch_in_window`. Không ép thành spoof |
| Window index/training dài, máy tắt nhiều → coverage thấp | Đã xử ở phase 3. Outcome luôn kèm coverage; coverage <50% nên coi là không kết luận được |
| Takedown quên bật lại làm run sau hỏng | `takedown_at` gắn theo run, không phải toàn cục. Run mới có path mới |
| Chấm outcome tự động sai vì thiếu answer nhập tay | Hết 2× window không có answer → tự `closed` với `inconclusive_no_answer`, tuyệt đối không chấm `origin_fetch_not_observed`. Trước đó giữ `observing` |
