---
phase: 8
title: "Scheduler & Run Diff"
status: pending
priority: P2
dependencies: [7]
effort: ""
---

# Phase 8: Scheduler & Run Diff

## Overview

Biến lab từ "chạy một lần" thành "theo dõi được thay đổi theo thời gian". Test template bật/tắt được,
sinh run theo lịch, và so sánh chu kỳ N với N-1. So sánh chính là giá trị dài hạn của lab —
hành vi AI vendor đổi liên tục, một lần đo không nói lên gì.

## Requirements

**Functional**
- Test template: định nghĩa một loại test, bật/tắt độc lập.
- Scheduler sinh test run từ template đang bật, theo ngày.
- Run diff: so kết quả run N vs N-1 cùng template.
- Job refresh IP range + retention `ip_raw` chạy theo lịch.

**Non-functional**
- Máy tắt qua đêm → scheduler bỏ lỡ lịch. Phải catch-up khi khởi động lại, không im lặng bỏ qua.

## Architecture

```sql
CREATE TABLE test_template (
  template_id     TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  variant         TEXT NOT NULL,
  driver          TEXT NOT NULL,
  expected_provider TEXT,
  robots_policy   TEXT NOT NULL,
  window_minutes  INTEGER NOT NULL,
  enabled         INTEGER NOT NULL DEFAULT 0,
  interval_hours  INTEGER,            -- NULL = chỉ chạy tay; khoảng cách giữa 2 run
  last_run_at     TEXT,
  created_at      TEXT NOT NULL
);

ALTER TABLE test_run ADD COLUMN template_id TEXT REFERENCES test_template(template_id);
ALTER TABLE test_run ADD COLUMN is_catchup INTEGER NOT NULL DEFAULT 0;
```

### Scheduler — chống bỏ lỡ

Máy bật/tắt theo ngày nên lịch theo giờ đồng hồ sẽ mất âm thầm. Dùng **khoảng cách** thay cron
expression — cron không có "chu kỳ" đơn để so `now - last_run_at` (đúng tinh thần YAGNI: template
theo ngày, bật/tắt thủ công):

```
Lúc startup:
  với mỗi template enabled:
    nếu interval_hours NOT NULL và (now - last_run_at) > interval_hours:
      tạo run catch-up, đánh dấu is_catchup=1
      ghi log rõ đã trễ bao lâu
```

Catch-up run được đánh dấu để khi diff không nhầm với run đúng lịch.

### Run diff

So run N và N-1 cùng `template_id`. So trên `outcome_code`, **không** so chuỗi đã ghép coverage —
nếu không "coverage nhích 87%→84%" sẽ báo nhầm là "outcome đổi":

| Trường so | Ý nghĩa khi đổi |
|---|---|
| outcome_code | AI đổi hành vi fetch |
| agent quan sát được | vendor đổi UA hoặc thêm agent mới |
| identity verification status | vendor đổi dải IP, hoặc bắt đầu ký request |
| request shape profile | vendor đổi cách tải trang |
| coverage | chất lượng phép đo, không phải hành vi AI |

Quan trọng: **coverage đổi không phải phát hiện về AI**. Diff phải tách rõ "AI đổi" với "phép đo đổi",
nếu không sẽ kết luận sai. Coverage của cả 2 run <80% → diff hiển thị cảnh báo không đáng tin.

## Related Code Files

- Create: `src/beam_lab/scheduler/templates.py`
- Create: `src/beam_lab/scheduler/runner.py` — sinh run, catch-up logic
- Create: `src/beam_lab/scheduler/jobs.py` — refresh IP range, retention ip_raw
- Create: `src/beam_lab/diff/run_diff.py`
- Create: `src/beam_lab/routes/dashboard_diff.py`
- Create: `src/beam_lab/templates/lab_templates.html`
- Create: `src/beam_lab/templates/lab_diff.html`
- Modify: `src/beam_lab/app.py` — chạy catch-up lúc lifespan startup
- Modify: `src/beam_lab/db/schema.sql`
- Create: `tests/test_scheduler_catchup.py`
- Create: `tests/test_run_diff.py`

## Implementation Steps

1. `scheduler/templates.py`: CRUD template. Seed sẵn 5 template ứng với 5 variant × driver `chatgpt`, và 5 template driver `passive` cho quan sát crawler.
2. `scheduler/runner.py`: hàm `ensure_runs()` — với mỗi template enabled, kiểm `last_run_at`, sinh run mới nếu tới hạn. Đánh dấu `is_catchup` khi trễ.
3. Gọi `ensure_runs()` ở lifespan startup và mỗi giờ bằng background task.
4. `scheduler/jobs.py`: job refresh IP range (gọi `scripts/refresh_ip_ranges.py` logic), job xoá `ip_raw` quá 24h, job auto-close run hết 2× window không có answer → `closed` + `outcome_code=inconclusive_no_answer` (qua `gate_outcome`, thống nhất với phase 6). Cả ba idempotent.
5. `diff/run_diff.py`: nhận `template_id`, lấy 2 run gần nhất đã `scored`, so từng trường, xuất danh sách thay đổi phân loại "AI đổi" vs "phép đo đổi".
6. `routes/dashboard_diff.py` + `lab_diff.html`: hiển thị diff, cảnh báo khi coverage thấp.
7. `lab_templates.html`: bảng template với toggle enable/disable.
8. Test catch-up: giả lập `last_run_at` cũ 3 ngày → startup sinh run catch-up có cờ đúng.

## Success Criteria

- [ ] Template bật/tắt được từ dashboard, tắt rồi thì không sinh run mới.
- [ ] Máy tắt 2 ngày rồi bật lại → run catch-up được sinh, `is_catchup=1`, log ghi rõ trễ bao lâu.
- [ ] `ensure_runs()` idempotent — gọi 2 lần liên tiếp không sinh trùng run.
- [ ] Job refresh IP range chạy được, lỗi mạng → giữ cache cũ (`stale_cache`), không crash scheduler.
- [ ] Retention job xoá đúng `ip_raw` quá 24h, không đụng `ip_hash`.
- [ ] Diff so được 2 run cùng template, liệt kê trường đã đổi; coverage khác nhau giữa 2 run **không** được báo là outcome đổi.
- [ ] Diff tách rõ "AI đổi hành vi" với "coverage đổi"; cả 2 run coverage <80% → hiện cảnh báo không đáng tin.
- [ ] Run catch-up được đánh dấu trong diff, không lẫn với run đúng lịch.

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| Scheduler bỏ lỡ lịch âm thầm khi máy tắt | Catch-up lúc startup + log rõ độ trễ. Dashboard hiện lần chạy gần nhất của mỗi template |
| Catch-up sinh hàng loạt run sau khi tắt máy dài | Giới hạn tối đa 1 catch-up run mỗi template mỗi lần startup |
| Diff kết luận "AI đổi hành vi" trong khi thật ra coverage tụt | Tách 2 nhóm thay đổi + cảnh báo coverage. Đây là lỗi diễn giải nguy hiểm nhất của phase này |
| Marker cạn do sinh run tự động liên tục | Marker 8 ký tự base32 = 10^12 tổ hợp, đủ. Kiểm unique lúc sinh |
| Template enabled quên tắt → sinh run vô ích khi không ai nhập kết quả | Run không có answer sau 2× window → tự `closed` với `inconclusive_no_answer` (không bao giờ là `origin_fetch_not_observed`), và cảnh báo trên dashboard |
