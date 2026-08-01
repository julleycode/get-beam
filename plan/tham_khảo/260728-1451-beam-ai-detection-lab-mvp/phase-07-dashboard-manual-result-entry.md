---
phase: 7
title: "Dashboard & Manual Result Entry"
status: pending
priority: P2
dependencies: [6]
effort: ""
---

# Phase 7: Dashboard & Manual Result Entry

## Overview

Dashboard là công cụ thăm dò, không phải bảng KPI. Yêu cầu cốt lõi: drill-down từ kết luận xuống
evidence gốc. Và vì driver AI là chat UI thủ công, dashboard **phải ghi được** — form nhập câu trả lời
của AI là nguồn duy nhất của cột `marker_returned`.

## Requirements

**Functional**
- Overview: phân bố actor class, provider, verified vs unverified, coverage, tỉ lệ unknown.
- Test run view: prompt template (copy được), canary URL, request quan sát được, outcome, evidence.
- **Form nhập kết quả**: paste nguyên văn câu trả lời AI → tự dò marker → lưu.
- Detection matrix: từng detector, kết quả, confidence cho một request.
- Evidence drill-down: click classification → xem bundle gốc + content snapshot.
- Review queue: conflict giữa detector, unattributed fetch, coverage thấp.

**Non-functional**
- Chỉ bind localhost (đã cưỡng chế ở phase 2).
- Server-rendered Jinja2, không build step. YAGNI — không SPA.

## Architecture

```
/_lab/                     overview
/_lab/testruns             danh sách
/_lab/testrun/{id}         chi tiết + form nhập kết quả + nút takedown
/_lab/request/{id}         evidence drill-down + detection matrix
/_lab/health               uptime timeline, coverage theo ngày
/_lab/review               review queue
```

### Form nhập kết quả — luồng

```
1. Người dùng dán URL vào ChatGPT/Claude, đợi trả lời
2. Copy nguyên văn câu trả lời
3. Mở /_lab/testrun/{id}, paste vào ô "AI answer"
4. Server tự dò marker trong text → set marker_found
5. Người dùng xác nhận hoặc override, thêm note
6. Lưu → trigger scoring
```

Tự dò marker rồi cho override, không bắt tick tay — giảm sai sót người nhập.

Ô "post-takedown" tick khi nhập câu trả lời sau khi đã takedown.

### Hiển thị coverage — không được giấu

Tầng render ghép `outcome_code` + `coverage_pct` (2 cột riêng trong DB) thành chuỗi
`origin_fetch_not_observed(coverage=NN%)`. Mọi chỗ hiện outcome âm phải hiện coverage cùng dòng, cùng cỡ chữ.
Coverage < 80% → badge cảnh báo. Coverage < 50% → outcome hiển thị gạch mờ kèm "không kết luận được".

Trạng thái `unknown` của edge config (phase 2) hiển thị nổi bật, không ẩn.

## Related Code Files

- Create: `src/beam_lab/routes/dashboard.py`
- Create: `src/beam_lab/templates/lab_base.html`
- Create: `src/beam_lab/templates/lab_overview.html`
- Create: `src/beam_lab/templates/lab_testrun_list.html`
- Create: `src/beam_lab/templates/lab_testrun_detail.html`
- Create: `src/beam_lab/templates/lab_request_detail.html`
- Create: `src/beam_lab/templates/lab_health.html`
- Create: `src/beam_lab/templates/lab_review.html`
- Create: `src/beam_lab/static/lab.css`
- Create: `src/beam_lab/queries/aggregates.py` — truy vấn tổng hợp, tách khỏi route
- Create: `tests/test_dashboard_localhost_only.py`
- Create: `tests/test_answer_entry.py`

## Implementation Steps

1. `lab_base.html`: layout tối giản, không framework CSS ngoài. Không tải asset từ CDN.
2. `queries/aggregates.py`: gom SQL tổng hợp. Không viết SQL trong template.
3. Overview: đếm theo actor class, provider, verification status; coverage 7 ngày gần nhất.
4. Test run detail: hiện prompt template với nút copy, canary URL, bảng request quan sát được (thời gian, UA, IP prefix, identity status), outcome hiện tại, nút takedown.
5. Form nhập kết quả: POST `/_lab/testrun/{id}/answer`. Server dò **marker đầy đủ** của run trong `raw_answer` (không dò tiền tố `BEAM-CANARY` — prompt template chứa tiền tố này nên AI có thể bịa `BEAM-CANARY-XXXXXXXX` mà không fetch; dò tiền tố = dương tính giả), prefill checkbox, cho override. Lưu `test_run_answer` rồi gọi `scoring.score(run_id)`.
6. Request detail: bảng detection matrix (detector, status, score, evidence), bên dưới là evidence bundle raw JSON và content snapshot (render an toàn, escape HTML). Content snapshot của run chưa `burned` phải **mask marker** (thay bằng `BEAM-CANARY-••••••••`) — chỉ bỏ mask khi bấm nút reveal, nhất quán với rule "không hiển thị marker trừ khi reveal".
7. Health: timeline uptime theo ngày, coverage %, danh sách khoảng down dài nhất.
8. Review queue: liệt kê run có `unattributed_fetch_in_window`, run coverage <80%, request có detector mâu thuẫn (identity nói verified nhưng request_shape nói full_browser_assets…).
9. Test tách app: public app (:8000) trả 404 cho mọi path `/_lab`; request kèm header `CF-Ray` giả vẫn 404. (Không test bằng `request.client.host` — qua tunnel nó luôn là loopback, test kiểu đó pass ảo trong khi production hở.)

## Success Criteria

- [ ] Dashboard chỉ tồn tại trên app `127.0.0.1:8001`; public app (:8000) trả 404 cho mọi path `/_lab`, kể cả request mang header `CF-*` giả; qua hostname public cũng 404 (ingress rule).
- [ ] Overview hiện đủ: actor class, provider, verified/unverified, coverage, tỉ lệ unknown.
- [ ] Test run detail hiện prompt template copy được, và prompt **không chứa marker**.
- [ ] Paste câu trả lời chứa marker → checkbox tự tick; paste không chứa → không tick.
- [ ] Override checkbox hoạt động và được lưu kèm note.
- [ ] Lưu answer → outcome được tính lại ngay.
- [ ] Tick post-takedown → outcome thành `content_served_after_takedown` khi không có request nào.
- [ ] Click classification → xem được evidence bundle gốc và content snapshot của đúng request đó.
- [ ] Outcome âm luôn hiện coverage cùng dòng; coverage <50% hiển thị "không kết luận được".
- [ ] Edge config `unknown` hiển thị nổi bật, không bị ẩn.
- [ ] Content snapshot render escape HTML, không thực thi script trong đó; marker của run chưa burned bị mask cho tới khi bấm reveal.

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| Render content snapshot gây XSS trong dashboard | Escape toàn bộ, hiển thị dạng `<pre>`. Không dùng `\|safe` |
| Người nhập quên tick post-takedown → outcome sai | Nếu run có `takedown_at` và answer nhập sau mốc đó, mặc định tick sẵn |
| Coverage bị bỏ qua khi đọc nhanh | Nhúng coverage vào chuỗi outcome (phase 3) + badge màu. Hai lớp |
| Dashboard phình thành SPA | YAGNI. Jinja2 server-rendered, không JS framework. Chỉ JS thuần cho nút copy |
| Marker lộ qua dashboard | Test run detail không hiển thị marker trừ khi bấm nút "reveal"; prompt template không chứa marker |
