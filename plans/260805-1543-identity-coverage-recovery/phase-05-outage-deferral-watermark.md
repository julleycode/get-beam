---
phase: 5
title: "Outage deferral watermark"
status: complete
priority: P2
dependencies: [2]
---

# Phase 5: Outage deferral watermark

> **Đã thử một lần và THẤT BẠI ở session 3 (05-08-26).** Code viết xong, test xanh, rồi bị code
> review bác bằng bằng chứng chạy thật và **revert toàn bộ**. §Sáu cái bẫy là phần quan trọng
> nhất của file này — đọc trước khi viết dòng code đầu tiên.

<!-- Updated 06-08-26: chốt trần backoff = 4; thêm bẫy #5; đối chiếu lại code hiện tại. -->
<!-- Updated: Validation Session 3 (06-08-26) — thêm bẫy #6 (sweep nằm ở 2 file); liệt kê đủ
     7 call site của _resolve_ip_company_parallel; bỏ bước 7 (check_ip_privacy) vì bước 6 đã
     phủ; chốt Retry tay bỏ qua mốc hoãn, đường agent để ngoài phạm vi. -->

## Trạng thái nền (xác minh 06-08-26 @ `191b919`)

Không cần khảo sát lại — đã kiểm và ghi ở đây:

| Thứ | Trạng thái |
|---|---|
| Code hỏng session 3 | **Đã revert sạch.** Grep `apps/api/services`: 0 hit cho `_providers_answered`, `_providers_unavailable`, `_finalize_unmatched`, và không còn circuit breaker nào |
| Điểm gán `unresolvable` | [identity_resolver.py:602](apps/api/services/identity_resolver.py#L602) — **vô điều kiện**, kèm comment KNOWN GAP trỏ về phase này |
| Sweep query — **CÓ HAI CHỖ** | (a) [resolution_runner.py:130](apps/api/services/resolution_runner.py#L130) — `identity_status == "anonymous"`, sắp `intent_score DESC`, `max_resolve=20`; (b) [resolution_tasks.py:79](apps/api/tasks/resolution_tasks.py#L79) — task Celery beat `process_all_pending_visitors` ([celery_app.py:61](apps/api/services/celery_app.py#L61)), **cùng bộ lọc, `LIMIT 50`**, gọi `resolve()` ở [:123](apps/api/tasks/resolution_tasks.py#L123). Xem bẫy #6 |
| Alembic head | **`b4c9a71e35d8`** (đã đổi so với lúc viết plan). Chạy `alembic heads` lại ngay trước khi tạo migration |
| Budget hằng ngày | Đếm **visitor riêng biệt có dòng `ResolutionLog` hôm nay** ([usage_limits.py:69-83](apps/api/services/usage_limits.py#L69-L83)) |

**Budget không cần quyết định gì thêm** — Phase 2 đã làm outage không ghi `ResolutionLog`, nên
visitor bị hoãn hoàn toàn tự động không tốn budget. Outage một phần (graph chết, ipinfo trả lời)
vẫn tốn 1, và đó là đúng vì có gọi thật.

## Overview

Phase 2 gỡ khoá 30 ngày cho outage, nhưng **chưa gỡ được ai** vì còn một khoá thứ hai, mạnh hơn:

```
_resolve_full_waterfall  →  identity_status = 'unresolvable'   (kể cả khi MỌI provider đều chết)
resolution_runner.py:130 →  sweep CHỈ chọn identity_status = 'anonymous'
resolution_tasks.py:79   →  sweep thứ hai, CÙNG bộ lọc  ← bẫy #6
                            ⇒ visitor bị loại khỏi mọi lượt sweep về sau, vĩnh viễn
```

Đường quay lại duy nhất hiện nay: `revive_returning_unresolvable` (chỉ chạy khi **IP đổi**) hoặc
người bấm **Retry** tay.

## Requirements

- Functional: visitor mà **tầng provider có khả năng khớp nó** đều chết → không bị đánh
  `unresolvable`, và **được thử lại sau một khoảng chờ có giới hạn**.
- Functional: outage kéo dài **không được** làm visitor cũ chiếm hết slot sweep của visitor mới.
- Functional: provider **chưa cấu hình** cho site này không được coi là outage (bẫy #5).
- Functional: **mọi** đường sweep phải tôn trọng mốc hoãn — hiện có 2 đường, không phải 1 (bẫy #6).
- Non-functional: cần **1 migration** (cột mốc hoãn).

## Architecture

### Vì sao phải có cột DB, không dùng Redis được

Chốt chặn phải nằm **trong câu query của CẢ HAI sweep**, không phải trong `resolve()`.

| Đặt chốt ở đâu | Chặn được gọi API? | Chặn được chiếm slot sweep? |
|---|---|---|
| Redis (circuit breaker) — đã thử, revert | ✅ | ❌ **Không** — row vẫn được SELECT, vẫn chạy `_check_prior_signals`, `check_ip_privacy`, vẫn ghi `api_usage_logs` |
| Cột `visitors.resolution_deferred_until` + filter trong sweep | ✅ | ✅ (chỉ khi vá đủ 2 chỗ — bẫy #6) |

Sweep lấy `LIMIT 20`/site (runner) và `LIMIT 50`/site (task Celery), sắp theo `intent_score DESC`.
Visitor bị hoãn giữ nguyên `anonymous` và **vẫn tiếp tục tăng intent** khi họ quay lại → luôn nằm
top. Có ≥20 (hoặc ≥50) visitor bị hoãn là visitor mới không bao giờ lọt vào batch. Redis không cứu
được vì nó chỉ bỏ qua lời gọi HTTP, không bỏ qua việc chọn row.

Đặt chốt trong `resolve()` cũng không được vì cùng lý do: row đã bị SELECT rồi thì slot đã mất.

### Quy tắc "tầng chết" — trung tâm của phase này

Đếm outage **theo tầng**, và **loại provider chưa cấu hình khỏi mẫu số**:

```
tầng person-graph:  leadpipe, capturify, rb2b
tầng IP→company:    pdl_ip, ipinfo

verdict(tầng) =
    not_applicable    nếu attempted == 0
    all_unavailable   nếu attempted >= 1 và mọi provider attempted đều unavailable
    answered          ngược lại  (≥1 provider trả lời, dù là no-match)
```

Chỉ `all_unavailable` mới kích hoạt hoãn. `not_applicable` và `answered` đều đi tiếp tới
`unresolvable` như cũ.

### Backoff — CHỐT: 4 lần

```
lần 1 → +15 phút
lần 2 → +1 giờ
lần 3 → +6 giờ
lần 4 → +24 giờ
lần 5 → thôi, gán `unresolvable`
```

Tổng ~31 giờ. Lý do chọn 4 (quyết định user 06-08-26): 31 giờ phủ trọn một ngày sự cố, dư cho mọi
outage vendor thật (thường vài phút tới vài giờ). Quá mốc đó gần như chắc chắn là **vấn đề tài
khoản/credential** — ca org `Beam ai` `status: expired` với `credits.used: 0` là bằng chứng sống:
hỏng từ lâu, chờ bao lâu cũng không tự hết, phải người vào đổi key. Chờ tiếp chỉ đổi lấy visitor
treo + đốt tiền `check_ip_privacy` mỗi lượt.

Đếm số lần đã hoãn: suy ra từ `resolution_deferred_until` không được (nó chỉ là mốc thời gian).
Dùng thêm một cột đếm, HOẶC mã hoá bậc vào chính mốc. **Chọn cột đếm** — rẻ hơn, đọc được, và
migration đằng nào cũng phải chạy.

## Sáu cái bẫy — đọc kỹ trước khi làm lại

### Bẫy #1 — gộp bộ đếm 2 tầng làm fix không bao giờ chạy

Bản đầu dùng **một** cặp biến đếm cho cả 5 provider. Chỉ cần **một** provider bất kỳ trả lời là
`answered > 0` → vẫn đánh `unresolvable`. Ca thực tế phổ biến nhất lại đúng là ca đó:

```
leadpipe/capturify/rb2b  → 403  (dùng CHUNG một tài khoản hỏng)
ipinfo                   → trả lời bình thường: không thấy công ty
⇒ answered=1, unavailable=3  →  identity_status = 'unresolvable'
```

Fix **không ăn ở đúng ca nó sinh ra để sửa**. Bài học: nhánh code được test không đồng nghĩa hệ
thống được test — cả 4 test trạng thái cuối đều **tự gán tay** biến đếm rồi gọi thẳng
`_finalize_unmatched`, không lần nào chạy `resolve()` thật.

### Bẫy #2 — Redis circuit breaker chặn nhầm chỗ

Breaker bỏ qua được lời gọi HTTP nhưng **không** ngăn row bị SELECT. Kèm 2 lỗi riêng: `INCR` rồi
`EXPIRE` **không nguyên tử** (chết giữa 2 lệnh → key không TTL → provider tắt vĩnh viễn, im lặng);
và đếm theo *liên tiếp* nên provider hỏng ngắt quãng 50% không bao giờ đạt ngưỡng.

### Bẫy #3 — hoãn rồi vẫn tốn tiền  ✅ ĐÃ ĐƯỢC BƯỚC 6 PHỦ (validate session 3)

[identity_resolver.py:504-518](apps/api/services/identity_resolver.py#L504-L518):
`check_ip_privacy` (ipinfo trả phí) chạy **trước** mọi bộ đếm, và `except Exception` chỉ log debug
— **không cache khi lỗi**. Visitor đang hoãn mà bị chọn trúng vẫn tốn tiền mỗi lượt.

**Nhưng:** một khi bộ lọc ở bước 6 chạy đúng (cả 2 sweep), visitor đang hoãn **không bao giờ được
SELECT** → `resolve()` không vào → `check_ip_privacy` không chạy. Bước 6 chính là cái chặn tiền;
không cần bước riêng. Đường duy nhất còn chạm tới là Retry tay
([visitors.py:879](apps/api/routers/visitors.py#L879), `force_retry=True`) — ở đó **phải** chạy
kiểm VPN vì đó là bộ lọc an toàn (đặt `vpn_filtered`), không phải tối ưu chi phí.

Nợ kỹ thuật còn lại (KHÔNG sửa ở phase này): nhánh `except Exception` không cache âm nên mọi
đường gọi đều trả tiền lại cho ipinfo khi lỗi.

### Bẫy #4 — cache âm 24h nuốt mất lần thử sau  ⚠️ CÒN SỐNG TRONG CODE

[identity_resolver.py:551-562](apps/api/services/identity_resolver.py#L551-L562) ghi `__none__`
TTL 86400 **bất kể lý do**. Gốc rễ: [`_resolve_ip_company_parallel`](apps/api/services/identity_resolver.py#L758)
trả `str | None`, người gọi **không thể** phân biệt "IP này không có công ty" với "cả 2 provider
đều chết". Outage → ghi cache âm 24h → lượt sweep sau bỏ qua hẳn bước IP→company dù provider đã hồi.

### Bẫy #5 — `attempted=False` là trạng thái THỨ BA  🔴 MỚI, plan cũ không biết

Commit `12d6059` (06-08-26) thêm `ProviderNotConfiguredError` → `_fetch` trả **`attempted=False`**
([identity_resolver.py:635-647](apps/api/services/identity_resolver.py#L635-L647)) cho provider
chưa cấu hình cho site này (vd Leadpipe chưa có pixel cho domain đó).

| Nếu xếp `attempted=False` vào… | Hậu quả |
|---|---|
| "unavailable" | Site không có pixel Leadpipe → tầng person-graph **luôn** bị coi là chết → visitor hoãn tới khi chạm trần rồi mới `unresolvable`. Tốn 4 lượt sweep vô ích cho **mọi** visitor của **mọi** site chưa bật Leadpipe |
| "answered" | Che outage thật của 2 provider còn lại — **cùng hình dạng bẫy #1**, hỏng y hệt session 3 |
| **loại khỏi mẫu số** ✅ | Đúng — xem §Quy tắc "tầng chết" |

Tin tốt: `_fetch` đã trả sẵn tuple `(name, data, elapsed, attempted, unavailable_detail)` → tầng
person-graph **không cần refactor**. Tin xấu: tầng IP→company chưa có gì tương đương.

### Bẫy #6 — sweep có HAI chỗ, plan cũ chỉ ghi một  🔴 MỚI (validate session 3, 06-08-26)

Đây là **bẫy #1 lặp lại ở tầng khác**: fix đúng, nhưng đặt ở chỗ ca thật không đi qua.

| File | Bộ lọc | Limit | Ai chạy |
|---|---|---|---|
| [resolution_runner.py:130](apps/api/services/resolution_runner.py#L130) | `identity_status == "anonymous"` | 20 | `run_resolution_sweep` (APScheduler / cron) + Retry-cả-site qua [visitors_helpers.py:326](apps/api/routers/visitors_helpers.py#L326) |
| [resolution_tasks.py:79](apps/api/tasks/resolution_tasks.py#L79) | **y hệt** | **50** | task Celery beat `process_all_pending_visitors`, đăng ký ở [celery_app.py:61](apps/api/services/celery_app.py#L61) — **đang chạy thật, không phải code chết** |

Chỉ vá `resolution_runner.py` thì đường Celery vẫn SELECT visitor đang hoãn mỗi lượt → gọi
`resolve()` → tốn `check_ip_privacy` (bẫy #3 sống lại), tăng `resolution_defer_count` oan, và
chạm trần 4 rất nhanh vì hai sweep cùng đẩy bậc. Mốc hoãn khi đó **coi như không tồn tại**.

Quyết định (validate session 3): **vá cả 2 chỗ**. Ghi chú: `plan.md` §Execution Log gọi tên
`resolution_tasks.py` là sweep, còn phase file bản cũ gọi tên `resolution_runner.py` — hai chỗ mâu
thuẫn nhau, và cả hai đều đúng một nửa. Đó chính là cách cái bẫy này lọt qua hai vòng review.

## Đường gọi `resolve()` ngoài sweep (chốt validate session 3)

| Đường | Có áp mốc hoãn không | Lý do |
|---|---|---|
| Retry tay — [visitors.py:879](apps/api/routers/visitors.py#L879), `force_retry=True` | **KHÔNG** — bỏ qua mốc hoãn | `force_retry` vốn đã bỏ qua khoá 30 ngày ([identity_resolver.py:477](apps/api/services/identity_resolver.py#L477)); người bấm Retry nghĩa là "thử ngay". Không cần code mới — bộ lọc nằm trong câu query sweep, đường này không đi qua đó |
| Retry-cả-site — [visitors_helpers.py:326](apps/api/routers/visitors_helpers.py#L326) | **CÓ** — tự động | Gọi `run_resolution_for_site`, dùng chung câu query đã vá |
| agent→company — [agent_company_resolution.py:130](apps/api/services/agent_company_resolution.py#L130) | **KHÔNG** — ngoài phạm vi phase | Đường riêng cho row agent-derived, `human_only_visitor_filter()` đã loại khỏi mọi sweep. Đụng vào là chạm surface guardrail EvalLayer (`source_agent_visit_id`). **Known-gap có chủ đích**, xem Risk Assessment |

Hệ quả phải chấp nhận: Retry tay trong lúc outage **vẫn** chạy nhánh hoãn ở dòng 602 → vẫn tăng
`resolution_defer_count`. Bấm Retry 4 lần liên tiếp giữa outage sẽ đẩy visitor chạm trần sớm. Chấp
nhận được (người dùng chủ động), nhưng phải ghi log để không bị coi là bug.

## Related Code Files

- Modify: `apps/api/services/identity_resolver.py`
  - `_resolve_ip_company_parallel` (dòng 758) — đổi `str | None` → `(domain, verdict)`
  - khối cache IP (dòng 551-562) — chặn ghi `__none__` khi verdict là `all_unavailable`
  - `_resolve_identity_graphs_parallel` (dòng 610) — trả thêm verdict tầng, dùng `attempted` sẵn có
  - nhánh cuối (dòng 602) — thay gán `unresolvable` vô điều kiện
  - ~~`check_ip_privacy`~~ — **KHÔNG sửa** (bước 6 đã phủ, xem bẫy #3)
- Modify: **cả hai** sweep — thêm điều kiện lọc mốc hoãn:
  - `apps/api/services/resolution_runner.py:130`
  - `apps/api/tasks/resolution_tasks.py:79`  ← bẫy #6, plan cũ bỏ sót
- Modify: `apps/api/models/visitor.py` + migration mới — `resolution_deferred_until TIMESTAMP NULL`
  + `resolution_defer_count INT NOT NULL DEFAULT 0`
- Modify: `apps/api/routers/visitors_helpers.py` — skip reason `provider_outage` (hiện outage bị
  báo nhầm thành `recently_attempted` — [:261](apps/api/routers/visitors_helpers.py#L261) và
  [:279](apps/api/routers/visitors_helpers.py#L279), known-gap Phase 2)

**KHÔNG sửa (chốt tường minh):** `apps/api/routers/visitors.py:879` (Retry tay — cố ý bỏ qua mốc
hoãn), `apps/api/services/agent_company_resolution.py:130` (known-gap có chủ đích).

### Call site của `_resolve_ip_company_parallel` — đủ 7, phải sửa hết

Đổi kiểu trả là breaking change. Bài học session 1 + session 2: plan gọi tên 1 file, thay đổi thật
trải trên N file. Lần này liệt kê đủ:

| # | Vị trí | Loại | Vỡ không |
|---|---|---|---|
| 1 | [identity_resolver.py:552](apps/api/services/identity_resolver.py#L552) | production, chỉ 1 chỗ | có — phải unpack |
| 2 | `tests/unit/test_identity_resolver_parallel.py:239` | test | không assert giá trị trả |
| 3 | `tests/unit/test_identity_resolver_parallel.py:263` | test | **VỠ** — `assert result == "pdl-company.com"` |
| 4 | `tests/unit/test_identity_resolver_parallel.py:286` | test | **VỠ** — `assert result == "fallback.com"` |
| 5 | `tests/unit/test_identity_resolver_parallel.py:309` | test | không assert giá trị trả |
| 6 | `tests/unit/test_resolution_outcome_taxonomy.py:267` | test | **VỠ** — `assert domain is None` |
| 7 | `tests/unit/test_resolution_outcome_taxonomy.py:289` | test | không assert giá trị trả |

- Tests: 2 file trên **phải sửa**, cộng test mới — **bắt buộc có test chạy `resolve()` end-to-end**

## Implementation Steps

Thứ tự này đi từ thay đổi mở khoá nhiều nhất tới ít nhất; mỗi bước tự kiểm được.

1. **Mở rộng `_resolve_ip_company_parallel`** → trả `(domain, verdict)` với verdict ∈
   {`answered`, `all_unavailable`, `not_applicable`}. Mở khoá đồng thời bẫy #4 và việc đếm tầng IP.
   **Sửa đủ 7 call site** theo bảng ở §Related Code Files — 3 test đang assert giá trị trả sẽ vỡ.
2. **Verdict cho tầng person-graph** từ tuple `_fetch` đã có. Áp đúng §Quy tắc "tầng chết".
3. **Chặn ghi cache âm** khi verdict tầng IP là `all_unavailable`.
4. **Migration**: `resolution_deferred_until` + `resolution_defer_count`. Chạy `alembic heads`
   ngay trước (head lúc viết: `b4c9a71e35d8`), round-trip trên Postgres dùng-một-lần:
   `docker run -d --name pg-mig -e POSTGRES_USER=retarget -e POSTGRES_PASSWORD=retarget_dev -e POSTGRES_DB=retarget_agent -p 55432:5432 postgres:16-alpine`
5. **Nhánh trạng thái cuối** thay dòng 602: tầng-có-khả-năng-khớp `all_unavailable` → giữ
   `anonymous`, tăng `resolution_defer_count`, đặt `resolution_deferred_until` theo bậc backoff;
   chạm trần 4 → `unresolvable` như cũ.
6. **Filter CẢ HAI sweep** — `(resolution_deferred_until IS NULL OR resolution_deferred_until <= now())`:
   - `resolution_runner.py:130`
   - `resolution_tasks.py:79` ← **không được quên; bỏ chỗ này là mốc hoãn vô tác dụng (bẫy #6)**
7. **Skip reason** `provider_outage` trong `visitors_helpers.py`.

~~Bước cũ "bỏ qua `check_ip_privacy`"~~ — **đã bỏ (validate session 3)**: bước 6 loại visitor hoãn
khỏi SELECT nên `resolve()` không vào, `check_ip_privacy` không chạy. Bước đó là code chết. Xem bẫy #3.

## Success Criteria

- [x] Ca "3 person-graph chết 403 + ipinfo trả lời no-match" → visitor **không** `unresolvable`,
      có mốc hoãn (test end-to-end qua `resolve()`, **không** gán tay bộ đếm)
      → `test_dead_graphs_plus_healthy_ipinfo_defers`
- [x] Ca "Leadpipe `not_configured` + rb2b trả lời no-match" → `unresolvable`, **không** hoãn
      ← ca của bẫy #5, không có trong plan gốc → `test_unconfigured_provider_is_not_an_outage`
- [x] Ca "provider trả lời, không ai khớp" → vẫn `unresolvable` như cũ
- [x] Ca "không cấu hình provider nào" → vẫn terminal, không tạo vòng lặp sweep
- [x] Outage kéo dài: có ≥20 visitor hoãn thì visitor mới **vẫn** vào được batch qua
      `resolution_runner.py` (kiểm bằng query) → integration, 60 visitor hoãn intent 90 vs 1
      visitor mới intent 30; batch trả **đúng 1 dòng** là visitor mới
- [x] **Y hệt cho `resolution_tasks.py`**: có ≥50 visitor hoãn thì visitor mới **vẫn** vào được
      batch của task Celery ← ca của bẫy #6 → cùng fixture, LIMIT 50
- [x] ~~`grep -rn` mọi hit `identity_status == "anonymous"`~~ → **thay bằng test tự dò**, xem
      §Lệch so với plan #2. `TestEverySweepHonoursTheWatermark` quét `apps/api/`, coi file là sweep
      khi có `anonymous` **và** `await ….resolve(`, và bắt buộc file đó chứa bộ lọc
- [x] Backoff chạm trần 4 lần → dừng, không lặp vô hạn → `test_past_the_last_step_writes_off_and_resets`
- [x] Outage **không** ghi cache âm `__none__` cho IP → `test_ip_outage_writes_no_none_marker`
      (+ test ngược lại: no-match thật **vẫn** cache, để cache âm không bị vô hiệu hoá cả cụm)
- [x] 3 test đang assert giá trị trả của `_resolve_ip_company_parallel` đã sửa và xanh
- [x] Retry tay (`force_retry=True`) trên visitor đang hoãn **vẫn chạy** — không bị mốc hoãn chặn
      → `test_deferred_visitor_still_runs_the_waterfall` (mốc hoãn nằm trong câu query sweep,
      không nằm trong `resolve()`). **Ngoại lệ ghi ở §Known-gap mới #2.**
- [x] Migration round-trip sạch trên Postgres dùng-một-lần; `alembic heads` một head
      → `c2f7a9d31b64`, up→down→up sạch, cột xác nhận bằng `\d visitors` cả 3 lần

## Execution — 06-08-26

**Kết quả test:** unit `1622 passed, 2 skipped, 0 failed` (16 test mới trong
`tests/unit/test_resolution_deferral_watermark.py`); integration deferral `3/3`
(`tests/integration/test_resolution_deferral_sweep.py`). Migration `c2f7a9d31b64` round-trip sạch
trên container `postgres:16-alpine` dùng-một-lần; `alembic heads` → một head duy nhất.

### Lệch so với plan (có chủ đích)

| # | Plan | Đã làm | Lý do |
|---|---|---|---|
| 1 | "`_resolve_identity_graphs_parallel` trả thêm verdict tầng" — **không liệt kê call site nào** | Giữ nguyên kiểu trả, thêm keyword out-param `tier_verdicts` | Hàm này có **1 production + 9 test** call site, tất cả 9 đều assert thẳng giá trị trả. Đây **đúng là bẫy "plan ghi 1 file, thật ra N file"** đã làm hỏng session 1, 2 và 3 — lần này nó ẩn ở hàm mà plan không kiểm. Dùng lại precedent user đã duyệt ở session 1 cho `_log_resolution` (keyword có default ⇒ 0 call site phải đổi). `_resolve_ip_company_parallel` **vẫn đổi thành tuple** đúng như quyết định session 3 #2, vì người gọi cần verdict ngay tại chỗ để quyết định cache |
| 2 | Tiêu chí `grep` thủ công cho mọi hit `anonymous` | Test tự dò sweep + phạm vi chốt lại theo quyết định user | `grep` cho **5 hit**, chỉ 2 là sweep. 3 hit còn lại là câu **đếm**: `visitors.py:1133` (gate endpoint resolve-all) → **có vá** vì nó đếm rồi chạy đúng cái sweep đó, báo "N eligible" xong resolve 0 là sai; `dashboard.py:108` + `visitors_helpers.py:195` (số `eligible_for_resolution` trên UI) → **không vá**, giữ nguyên số hiển thị |
| 3 | — | Sửa rò rỉ state giữa test trong file test mới | Xem §Bẫy #7 |

### Bẫy #7 — test dùng chung một Redis THẬT  🔴 MỚI, tìm ra lúc chạy

`IdentityResolver(db, redis_client=None)` **không** chạy không-Redis: nó tự dựng client thật
([identity_resolver.py:126-132](apps/api/services/identity_resolver.py#L126-L132)). Cache key là
`prefix + visitor.ip_address`, và các test dùng chung một IP mẫu → test trước ghi `__none__` vào
Redis local, test sau đọc trúng, **bỏ qua hẳn tầng IP** ⇒ `ip_verdict` không bao giờ được tính ⇒
ca "tầng IP chết" trả `unresolvable` và **fail sai lý do**. Mất vài phút mới thấy vì triệu chứng
(`assert 'unresolvable' == 'anonymous'`) trỏ vào logic, không trỏ vào cache.

Đã sửa trong phạm vi file test: `_fake_redis()` cấp một Redis giả **riêng cho mỗi test**, không
bao giờ truyền `None`. Cùng họ với known-gap "conftest Redis-isolation hardening" đang mở ở
`process/features/visitors-identity/backlog/post-docker-gate-followups_NOTE_24-07-26.md` — **không**
sửa conftest ở phase này (ngoài phạm vi, đụng mọi test khác).

### Known-gap mới (KHÔNG sửa ở phase này)

1. **Tầng Hunter/Apollo không có verdict.** Khi `company_domain` tìm được nhưng Hunter **và**
   Apollo đều chết, visitor vẫn rơi thẳng xuống `unresolvable` — đúng loại bug phase này sửa, chỉ
   khác tầng. Plan chỉ định nghĩa 2 tầng nên để ngoài phạm vi có chủ đích. Mở rộng được bằng cách
   thêm khoá thứ ba vào `tier_verdicts`.
2. **Retry tay vẫn có thể bị chặn bởi cổng 30 ngày trong ca outage MỘT PHẦN.** Mốc hoãn không
   chặn Retry (đã test), nhưng nếu outage chỉ giết một tầng thì tầng còn lại **có** ghi
   `ResolutionLog` → `was_recently_attempted` = True → `resolve()` thoát sớm vì
   `force_retry` chỉ được bật khi visitor đang ở trạng thái `unresolvable`
   ([visitors.py:846-850](apps/api/routers/visitors.py#L846)), mà visitor bị hoãn thì đang
   `anonymous`. Hành vi có sẵn từ trước, phase này không tạo ra và không sửa.
3. `resolution_deferred_until` / `resolution_defer_count` mới có ở DB + log, **chưa render trên UI**
   (cùng tình trạng với `outage_providers`/`last_outage_at` của Phase 2).

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| Lặp lại bẫy #1 — fix không ăn ở ca thật | Test end-to-end qua `resolve()` là tiêu chí đóng phase, không phải test nhánh. 4 test cũ đều gán tay bộ đếm — đó là lý do bug lọt CI |
| Dính bẫy #5 — hoãn nhầm cho site chưa bật Leadpipe | Ca test riêng ở Success Criteria #2; `attempted=False` phải bị loại khỏi mẫu số, không được gộp vào `unavailable` |
| Hoãn quá lâu → coverage tụt mà không ai biết | Log `resolution_deferred_provider_outage` + đếm được trong audit script |
| Migration chồng lên chuỗi đang chờ | `alembic heads` ngay trước khi tạo; head đã đổi nhiều lần, **không tin số trong bất kỳ plan nào** |
| Ca tái hiện bẫy #1 không còn quan sát được tự nhiên | Capturify tắt mặc định (DNS chết), Leadpipe có org khoẻ riêng → phải dựng bằng mock, không chờ quan sát |
| **Dính bẫy #6 — chỉ vá 1 trong 2 sweep** | Tiêu chí `grep` cơ học ở Success Criteria: mọi hit `identity_status == "anonymous"` phải kèm điều kiện lọc mốc hoãn. Đây là bẫy #1 ở tầng khác — fix đúng, đặt sai chỗ |
| Đổi kiểu trả `_resolve_ip_company_parallel` làm vỡ test âm thầm | Bảng 7 call site ở §Related Code Files; 3 test vỡ đã gọi tên. Session 1 + 2 đều thất bại đúng kiểu "plan ghi 1 file, thật ra N file" |
| Retry tay giữa outage đẩy visitor chạm trần sớm | Chấp nhận có chủ đích (người dùng chủ động bấm). Bắt buộc log để không bị chẩn đoán nhầm thành bug backoff |
| **Known-gap có chủ đích**: đường agent→company không có mốc hoãn | [agent_company_resolution.py:130](apps/api/services/agent_company_resolution.py#L130) gọi `resolve()` ngoài mọi sweep. Để ngoài phạm vi phase vì đụng surface guardrail EvalLayer (`source_agent_visit_id`). Ghi lại để phase sau không tưởng là đã phủ |
