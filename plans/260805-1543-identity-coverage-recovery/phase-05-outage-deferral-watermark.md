---
phase: 5
title: "Outage deferral watermark"
status: pending
priority: P2
dependencies: [2]
---

# Phase 5: Outage deferral watermark

> **Đã thử một lần và THẤT BẠI ở session 3 (05-08-26).** Code viết xong, test xanh, rồi bị code
> review bác bằng bằng chứng chạy thật và **revert toàn bộ**. §Năm cái bẫy là phần quan trọng
> nhất của file này — đọc trước khi viết dòng code đầu tiên.

<!-- Updated 06-08-26: chốt trần backoff = 4; thêm bẫy #5; đối chiếu lại code hiện tại. -->

## Trạng thái nền (xác minh 06-08-26 @ `191b919`)

Không cần khảo sát lại — đã kiểm và ghi ở đây:

| Thứ | Trạng thái |
|---|---|
| Code hỏng session 3 | **Đã revert sạch.** Grep `apps/api/services`: 0 hit cho `_providers_answered`, `_providers_unavailable`, `_finalize_unmatched`, và không còn circuit breaker nào |
| Điểm gán `unresolvable` | [identity_resolver.py:602](apps/api/services/identity_resolver.py#L602) — **vô điều kiện**, kèm comment KNOWN GAP trỏ về phase này |
| Sweep query | [resolution_runner.py:130](apps/api/services/resolution_runner.py#L130) — lọc `identity_status == "anonymous"`, sắp `intent_score DESC`, `max_resolve=20` |
| Alembic head | **`b4c9a71e35d8`** (đã đổi so với lúc viết plan). Chạy `alembic heads` lại ngay trước khi tạo migration |
| Budget hằng ngày | Đếm **visitor riêng biệt có dòng `ResolutionLog` hôm nay** ([usage_limits.py:69-83](apps/api/services/usage_limits.py#L69-L83)) |

**Budget không cần quyết định gì thêm** — Phase 2 đã làm outage không ghi `ResolutionLog`, nên
visitor bị hoãn hoàn toàn tự động không tốn budget. Outage một phần (graph chết, ipinfo trả lời)
vẫn tốn 1, và đó là đúng vì có gọi thật.

## Overview

Phase 2 gỡ khoá 30 ngày cho outage, nhưng **chưa gỡ được ai** vì còn một khoá thứ hai, mạnh hơn:

```
_resolve_full_waterfall  →  identity_status = 'unresolvable'   (kể cả khi MỌI provider đều chết)
resolution_runner.py     →  sweep CHỈ chọn identity_status = 'anonymous'
                            ⇒ visitor bị loại khỏi mọi lượt sweep về sau, vĩnh viễn
```

Đường quay lại duy nhất hiện nay: `revive_returning_unresolvable` (chỉ chạy khi **IP đổi**) hoặc
người bấm **Retry** tay.

## Requirements

- Functional: visitor mà **tầng provider có khả năng khớp nó** đều chết → không bị đánh
  `unresolvable`, và **được thử lại sau một khoảng chờ có giới hạn**.
- Functional: outage kéo dài **không được** làm visitor cũ chiếm hết slot sweep của visitor mới.
- Functional: provider **chưa cấu hình** cho site này không được coi là outage (bẫy #5).
- Non-functional: cần **1 migration** (cột mốc hoãn).

## Architecture

### Vì sao phải có cột DB, không dùng Redis được

Chốt chặn phải nằm **trong câu query của sweep**, không phải trong `resolve()`.

| Đặt chốt ở đâu | Chặn được gọi API? | Chặn được chiếm slot sweep? |
|---|---|---|
| Redis (circuit breaker) — đã thử, revert | ✅ | ❌ **Không** — row vẫn được SELECT, vẫn chạy `_check_prior_signals`, `check_ip_privacy`, vẫn ghi `api_usage_logs` |
| Cột `visitors.resolution_deferred_until` + filter trong sweep | ✅ | ✅ |

Sweep lấy `LIMIT 20`/site sắp theo `intent_score DESC`. Visitor bị hoãn giữ nguyên `anonymous` và
**vẫn tiếp tục tăng intent** khi họ quay lại → luôn nằm top. Có ≥20 visitor bị hoãn là visitor mới
không bao giờ lọt vào batch. Redis không cứu được vì nó chỉ bỏ qua lời gọi HTTP, không bỏ qua việc
chọn row.

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

## Năm cái bẫy — đọc kỹ trước khi làm lại

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

### Bẫy #3 — hoãn rồi vẫn tốn tiền  ⚠️ CÒN SỐNG TRONG CODE

[identity_resolver.py:505-518](apps/api/services/identity_resolver.py#L505-L518):
`check_ip_privacy` (ipinfo trả phí) chạy **trước** mọi bộ đếm, và `except Exception` chỉ log debug
— **không cache khi lỗi**. Visitor đang hoãn mà bị chọn trúng vẫn tốn tiền mỗi lượt.

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

## Related Code Files

- Modify: `apps/api/services/identity_resolver.py`
  - `_resolve_ip_company_parallel` (dòng ~758) — mở rộng trả `(domain, verdict)`
  - khối cache IP (dòng ~551-562) — chặn ghi `__none__` khi verdict là `all_unavailable`
  - `_resolve_identity_graphs_parallel` (dòng ~609) — trả thêm verdict tầng, dùng `attempted` sẵn có
  - `check_ip_privacy` (dòng ~505-518) — bỏ qua khi visitor đang trong cửa sổ hoãn
  - nhánh cuối (dòng ~602) — thay gán `unresolvable` vô điều kiện
- Modify: `apps/api/services/resolution_runner.py` (~dòng 130) — thêm điều kiện lọc mốc hoãn
- Modify: `apps/api/models/visitor.py` + migration mới — `resolution_deferred_until TIMESTAMP NULL`
  + `resolution_defer_count INT NOT NULL DEFAULT 0`
- Modify: `apps/api/routers/visitors_helpers.py` — skip reason `provider_outage` (hiện outage bị
  báo nhầm thành `recently_attempted`, known-gap Phase 2)
- Tests: `tests/unit/` — **bắt buộc có test chạy `resolve()` end-to-end**

## Implementation Steps

Thứ tự này đi từ thay đổi mở khoá nhiều nhất tới ít nhất; mỗi bước tự kiểm được.

1. **Mở rộng `_resolve_ip_company_parallel`** → trả `(domain, verdict)` với verdict ∈
   {`answered`, `all_unavailable`, `not_applicable`}. Mở khoá đồng thời bẫy #4 và việc đếm tầng IP.
2. **Verdict cho tầng person-graph** từ tuple `_fetch` đã có. Áp đúng §Quy tắc "tầng chết".
3. **Chặn ghi cache âm** khi verdict tầng IP là `all_unavailable`.
4. **Migration**: `resolution_deferred_until` + `resolution_defer_count`. Chạy `alembic heads`
   ngay trước (head lúc viết: `b4c9a71e35d8`), round-trip trên Postgres dùng-một-lần:
   `docker run -d --name pg-mig -e POSTGRES_USER=retarget -e POSTGRES_PASSWORD=retarget_dev -e POSTGRES_DB=retarget_agent -p 55432:5432 postgres:16-alpine`
5. **Nhánh trạng thái cuối** thay dòng 602: tầng-có-khả-năng-khớp `all_unavailable` → giữ
   `anonymous`, tăng `resolution_defer_count`, đặt `resolution_deferred_until` theo bậc backoff;
   chạm trần 4 → `unresolvable` như cũ.
6. **Filter sweep**: `(resolution_deferred_until IS NULL OR resolution_deferred_until <= now())`.
7. **Bẫy #3**: bỏ qua `check_ip_privacy` cho visitor đang trong cửa sổ hoãn.
8. **Skip reason** `provider_outage` trong `visitors_helpers.py`.

## Success Criteria

- [ ] Ca "3 person-graph chết 403 + ipinfo trả lời no-match" → visitor **không** `unresolvable`,
      có mốc hoãn (test end-to-end qua `resolve()`, **không** gán tay bộ đếm)
- [ ] Ca "Leadpipe `not_configured` + rb2b trả lời no-match" → `unresolvable`, **không** hoãn
      ← ca của bẫy #5, không có trong plan gốc
- [ ] Ca "provider trả lời, không ai khớp" → vẫn `unresolvable` như cũ
- [ ] Ca "không cấu hình provider nào" → vẫn terminal, không tạo vòng lặp sweep
- [ ] Outage kéo dài: có ≥20 visitor hoãn thì visitor mới **vẫn** vào được batch (kiểm bằng query)
- [ ] Backoff chạm trần 4 lần → dừng, không lặp vô hạn
- [ ] Outage **không** ghi cache âm `__none__` cho IP
- [ ] `check_ip_privacy` không bị gọi lại mỗi lượt cho visitor đang hoãn
- [ ] Migration round-trip sạch trên Postgres dùng-một-lần; `alembic heads` một head

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| Lặp lại bẫy #1 — fix không ăn ở ca thật | Test end-to-end qua `resolve()` là tiêu chí đóng phase, không phải test nhánh. 4 test cũ đều gán tay bộ đếm — đó là lý do bug lọt CI |
| Dính bẫy #5 — hoãn nhầm cho site chưa bật Leadpipe | Ca test riêng ở Success Criteria #2; `attempted=False` phải bị loại khỏi mẫu số, không được gộp vào `unavailable` |
| Hoãn quá lâu → coverage tụt mà không ai biết | Log `resolution_deferred_provider_outage` + đếm được trong audit script |
| Migration chồng lên chuỗi đang chờ | `alembic heads` ngay trước khi tạo; head đã đổi nhiều lần, **không tin số trong bất kỳ plan nào** |
| Ca tái hiện bẫy #1 không còn quan sát được tự nhiên | Capturify tắt mặc định (DNS chết), Leadpipe có org khoẻ riêng → phải dựng bằng mock, không chờ quan sát |
