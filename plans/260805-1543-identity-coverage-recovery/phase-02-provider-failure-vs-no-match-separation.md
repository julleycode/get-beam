---
phase: 2
title: "Provider failure vs no-match separation"
status: complete
priority: P1
dependencies: [1]
---

# Phase 2: Provider failure vs no-match separation

## Overview

Phase có giá trị cao nhất trong plan, và **không phụ thuộc vendor nào**. Hiện tại hệ thống không
phân biệt được "provider hỏng" với "provider trả lời: không tìm thấy ai" — hai thứ này ghi ra
dòng log giống hệt nhau, và cả hai đều kích hoạt khoá retry 30 ngày.

Hậu quả đo được: `6/7` visitor US chưa định danh đang bị khoá 30 ngày vì những lần thử thất bại
trong lúc Leadpipe trả 403 (`docs/identity-us-current-handoff.md`). Kể cả khi provider được sửa
ngày mai, những visitor đó vẫn không được thử lại trong 30 ngày. **Đây là cái bẫy sẽ lặp lại sau
mỗi lần vendor gián đoạn nếu không sửa.**

## Requirements

- Functional: outage của provider không được tính là "đã thử" — không khoá 30 ngày, không đốt
  ngân sách ngày.
- Functional: outage vẫn phải quan sát được (không được im lặng nuốt).
- Non-functional: **không thêm migration** (12 migration đang chờ apply live).
- Không nới lỏng bất kỳ quality gate nào.

## Architecture

### Vấn đề gốc

`resolution_logs` phục vụ **hai mục đích xung đột nhau**:

| Người đọc | Đọc để làm gì | Cần thấy outage không? |
|---|---|---|
| `was_recently_attempted` ([identity_resolver.py:123](apps/api/services/identity_resolver.py#L123)) | khoá retry 30 ngày | **KHÔNG** — outage không phải "đã thử" |
| `check_resolution_attempt_budget` ([usage_limits.py:86](apps/api/services/usage_limits.py#L86)) | ngân sách ngày | **KHÔNG** — outage không tiêu credit |
| Dashboard chi phí / audit | quan sát vận hành | **CÓ** |

Cả ba đang đọc chung một bảng, nên không thể vừa khoá đúng vừa quan sát đủ.

### Giải pháp: tách đường ghi, không tách schema

Đã có sẵn hai đích ghi — chỉ cần dùng đúng chỗ:

```
Provider trả lời thật (200 rỗng / 404 / 400)
   → ResolutionLog  (khoá + ngân sách)  ✓
   → api_usage_logs (quan sát)          ✓

Provider KHÔNG trả lời (401/403/5xx/timeout/DNS/connect)
   → ResolutionLog  ✗ BỎ QUA
   → api_usage_logs ✓ vẫn ghi, đánh dấu là lỗi hạ tầng
```

`log_api_call` đã ghi vào `api_usage_logs` với đủ trường (provider, success, cost, ms) và
`GET /costs/{site_id}/summary` đã đọc nó. Không cần cột mới, không cần migration.

### Điểm chạm code

<!-- Updated: Validation Session 1 - keyword-only outcome param; blast radius đã đếm chính xác -->

`_log_resolution` ([identity_resolver.py:1061](apps/api/services/identity_resolver.py#L1061)) hiện
ghi cả hai đích vô điều kiện.

**Blast radius thật (đếm bằng grep 05-08-26 — plan bản đầu ghi thiếu):**

| Loại | Số | Vị trí |
|---|---|---|
| Call site production | **7** trên 4 file | `identity_resolver.py:660,674,728,732`; `pdl.py:52`; `apollo.py:28`; `hunter.py:28` |
| Mock trong test | **13** trên 4 file | `test_identity_resolver_parallel.py` (9), `test_identity_quality_gates.py` (3), `test_provider_toggles.py` (2) |

⚠️ `test_identity_resolver_parallel.py:312` và `test_provider_toggles.py:79` assert theo **vị trí
tham số** (`call.args[1]`) → chèn tham số vào giữa sẽ làm vỡ test.

**Quyết định (validation session 1): thêm keyword-only có default.**

```python
async def _log_resolution(
    self, visitor, provider, success, cost, ms,
    *,
    outcome: str = "no_match",   # "match" | "no_match" | "provider_unavailable"
) -> None:
```

Vì là keyword-only và có default, **7 call site và 13 mock hiện tại không cần đổi** — hành vi giữ
nguyên byte-identical. Chỉ những chỗ thực sự phân biệt được lỗi hạ tầng mới truyền `outcome=`.
Đây cũng là lý do chọn phương án này thay vì sửa hết call site.

Người gọi cần truyền outcome:
- `_resolve_identity_graphs_parallel._fetch` — hiện nuốt mọi exception thành `data=None`
  ([identity_resolver.py:619-626](apps/api/services/identity_resolver.py#L619)). Phải giữ lại
  loại lỗi để phân biệt timeout/exception (unavailable) với "gọi xong, không có ai" (no_match).
- Các mixin trả `None` ở cả hai tình huống — cần đường báo hiệu. Nhẹ nhất: mixin ném exception
  đã phân loại cho lỗi hạ tầng, `None` chỉ còn nghĩa "không khớp". RB2B đang `return None` cho
  403 ([rb2b.py:187-189](apps/api/services/identity_providers/rb2b.py#L187)) — chỗ này phải đổi.

### Giữ khả năng quan sát outage trên UI visitor

<!-- Updated: Validation Session 1 - visitors.py phải đọc thêm api_usage_logs -->

Ngừng ghi `ResolutionLog` khi outage sẽ làm mất một thứ mà bản plan đầu không nhận ra:
[visitors.py:630-637](apps/api/routers/visitors.py#L630) đọc **`ResolutionLog`** (không phải
`api_usage_logs`) để dựng `last_resolution_attempt` và `resolution_providers_tried` trên trang chi
tiết visitor. Nếu chỉ ghi outage vào `api_usage_logs`, trang đó không còn thấy "đã thử Leadpipe
nhưng nó chết".

**Quyết định: cho `visitors.py` đọc thêm `api_usage_logs`** (category `identity`) để hiện các lần
thử bị outage, tách khỏi các lần thử thật. Không cần migration — `api_usage_logs` đã có đủ
`provider`, `success`, `created_at`, và cột `meta: JSONB` để chứa lý do.

Lưu ý ngữ nghĩa cần giữ đúng: `_resolution_skip_reason`
([visitors_helpers.py:234](apps/api/routers/visitors_helpers.py#L234)) dùng `last_attempt` để tính
cooldown 30 ngày — chỗ này **vẫn phải chỉ đọc `ResolutionLog`**, vì đó chính là bug đang sửa. Chỉ
phần hiển thị mới đọc thêm `api_usage_logs`.

### Preflight health (tuỳ chọn trong phase này)

Trước mỗi sweep, gọi endpoint health/account của provider một lần cho cả batch. Nếu provider chết
→ bỏ qua provider đó cho cả lượt, không thử từng visitor. Rẻ hơn 20 lần timeout, và biến trạng
thái "provider chết" thành một dòng log rõ ràng thay vì 20 dòng lỗi rải rác.

## Related Code Files

- Modify: `apps/api/services/identity_resolver.py` — `_log_resolution` (thêm keyword-only `outcome`), `_resolve_identity_graphs_parallel`, `_resolve_ip_company_parallel`
- Modify: `apps/api/services/identity_providers/rb2b.py`, `leadpipe.py`, `capturify.py`, `pdl.py`, `ipinfo.py` — phân biệt lỗi hạ tầng vs no-match
- Modify: `apps/api/services/identity_providers/matching.py` — counter `no_timestamp` + `outside_window`
- Modify: `apps/api/services/identity_providers/leadpipe.py` — counter `ip_mismatch` (bộ lọc IP nằm
  ở đây, không phải `matching.py` — xác minh session 2)
- Modify: `apps/api/routers/visitors.py` — đọc thêm `api_usage_logs` cho phần hiển thị lần thử bị outage
- **Không đổi (nhờ keyword-only + default):** `pdl.py:52`, `apollo.py:28`, `hunter.py:28` và 13 mock trong `test_identity_resolver_parallel.py`, `test_identity_quality_gates.py`, `test_provider_toggles.py`
- Tests: unit cho từng nhánh outcome; integration khẳng định outage không tạo `ResolutionLog`; regression khẳng định 13 mock cũ vẫn xanh

## Implementation Steps

1. **Định nghĩa ranh giới phân loại** (viết vào docstring, đây là hợp đồng):
   - `provider_unavailable`: 401, 403, 429 sau khi hết retry, 5xx, timeout, DNS/connect error
   - `no_match`: 200 nhưng không có kết quả, 404, 400 (IP không phân giải được)
   - `match`: có payload dùng được
2. Thêm `outcome` **keyword-only, default `"no_match"`** vào `_log_resolution`; chỉ ghi
   `ResolutionLog` khi `!= "provider_unavailable"`. `log_api_call` vẫn ghi mọi trường hợp —
   đã verify `price_for()` trả `0.0` khi `success=False`
   ([api_pricing.py:46](apps/api/services/api_pricing.py#L46)) nên ghi outage **không làm sai sổ
   chi phí**. Ghi lý do outage vào cột `meta` (JSONB, đã có sẵn).
3. Sửa từng mixin để phát tín hiệu đúng loại. RB2B 403 là ca rõ nhất — hiện trả `None` như thể
   không tìm thấy ai.
<!-- Updated: Validation Session 2 - counter ip_mismatch nằm ở leadpipe.py, không phải matching.py -->

4. **Thêm counter cho 3 lý do loại bỏ record — nằm trên 2 file, không phải 1** (grep 05-08-26):

   | Lý do | File | Trạng thái hiện tại |
   |---|---|---|
   | `no_timestamp` | [matching.py:110](apps/api/services/identity_providers/matching.py#L110) | `logger.info`, không đếm được |
   | `outside_window` | [matching.py:120](apps/api/services/identity_providers/matching.py#L120) | `logger.info`, không đếm được |
   | `ip_mismatch` | [leadpipe.py:71](apps/api/services/identity_providers/leadpipe.py#L71) | lọc bằng `continue`, log `debug` ở dòng 87 — **kém hơn cả 2 cái trên** |

   `matching.py` **không chứa logic IP nào** — bộ lọc IP nằm ở phía caller. Plan bản đầu ghi cả 3
   counter vào `matching.py` là sai; và ghi "hiện chỉ log mức `info`" cũng sai với ca `ip_mismatch`
   (mức `debug`, mặc định không xuất hiện trong log production).

   **Quyết định (validation session 2): thêm counter đúng chỗ nó xảy ra** — 2 ở `matching.py`,
   1 ở `leadpipe.py`. **Không** chuyển logic lọc IP vào `matching.py` (đó là refactor đổi hành vi,
   ngoài phạm vi phase này). `capturify.py` có cùng bộ lọc nhưng đã bị vô hiệu ở Phase 1 → không sửa.
5. **Dọn dữ liệu lịch sử — READ-ONLY trong phase này (chốt session 2).** Những `ResolutionLog`
   sinh ra trong giai đoạn Leadpipe 403 đang khoá oan 6/7 visitor US. Viết script **chỉ liệt kê**.
   **Không xoá, không đánh dấu, không ghi đè.** Lý do hoãn: chưa xác định được chính xác cửa sổ
   thời gian 403, nên chưa phân biệt được dòng nào thật sự là outage. Quyết định xử lý để sau khi
   Phase 3 xác minh provider sống.
6. Preflight health cho mỗi provider ở đầu sweep (nếu vào được trong phase này; nếu không, tách
   ra thành việc riêng).
7. Chạy lại `scripts/identity_resolution_audit.sql`, so với baseline Phase 1.

## Success Criteria

- [x] Provider trả 403 → **không** tạo `ResolutionLog`, **có** dòng trong `api_usage_logs`
- [x] Provider trả 200 rỗng → **có** `ResolutionLog` (khoá 30 ngày đúng như thiết kế)
- [x] Outage không tiêu ngân sách ngày (`check_resolution_attempt_budget` đếm `resolution_logs`,
      mà outage không còn ghi vào đó)
- [x] **13 mock `_log_resolution` hiện có vẫn xanh, không sửa dòng nào** — `git diff` xác nhận 3
      file test không bị đụng
- [x] Trang chi tiết visitor vẫn hiện được lần thử bị outage (đọc từ `api_usage_logs`) — **ở mức
      API**; UI chưa render (known-gap, giống `resolution_providers_tried` vốn cũng chưa render)
- [x] `_resolution_skip_reason` **không** còn báo "recent attempt" cho visitor chỉ dính outage —
      `visitors_helpers.py` giữ nguyên, vẫn chỉ đọc `ResolutionLog`
- [x] Lý do loại bỏ đếm được — **4, không phải 3**: `no_timestamp` + `outside_window`
      (`matching.py`), `ip_mismatch` + `no_email` (`leadpipe.py`). Không còn ca nào ở mức `debug`;
      log summary một dòng/lượt quét kèm `scanned` và `rejected` để đối chiếu
- [x] Không có migration mới
- [x] Danh sách visitor đang bị khoá oan đã liệt kê được — `scripts/identity_locked_visitors_audit.sql`,
      **read-only, không xoá, không đánh dấu**. Chạy thật trên Postgres: trả về 8 visitor

### Ghi chú thực thi (05-08-26)

**Bộ lọc trạng thái của script audit bản đầu sai và trả 0 dòng.** Lọc
`identity_status = 'anonymous'` là mù với 100% nhóm cần tìm: `_resolve_full_waterfall` đặt
`unresolvable` ở cuối mọi lượt không thành công, nên visitor đã đi qua waterfall không bao giờ còn
`anonymous`. Handoff doc cũng viết "6/7 US-**unresolvable**". Sửa thành
`IN ('anonymous','unresolvable')` → trả 8 visitor.

**Thủ phạm khoá không phải Leadpipe.** Audit chạy thật: `ipinfo` 9 lần/0 thành công,
`pdl_ip_enrich` 9 lần/0 thành công, `rb2b` 14 lần/8 thành công. `leadpipe` **0 dòng** (khớp
`docs/identity-us-current-handoff.md`). Chữ ký 9-lần-0-thành-công của ipinfo/pdl_ip dẫn tới H-1
dưới đây. Các comment/test viện dẫn "Leadpipe khoá 6/7 visitor" đã bỏ vì không có bằng chứng.

**H-1 (mở rộng phạm vi, user duyệt):** `_resolve_ip_company_parallel` ghi ledger chỉ dựa trên cờ
`*_enabled` (mặc định `True`), trong khi mixin trả `None` ngay khi thiếu key → provider **chưa
từng được gọi** vẫn ghi "đã thử, thất bại", khoá 30 ngày + tốn slot ngân sách. Sửa: `attempted =
enabled AND có key`, đúng pattern `_resolve_identity_graphs_parallel` đã dùng sẵn.

**Đã sửa sau code review (lỗi tự gây ra):** `meta.detail` bản đầu nội suy `str(exc)` → ghi
**token ipinfo sống + IP visitor** vĩnh viễn vào `api_usage_logs` (xác minh bằng chạy thật);
thay bằng `safe_failure_detail()` chỉ giữ tên exception + mã HTTP. Nhánh `except Exception` bản
đầu xếp mọi lỗi lạ thành outage — ngược mitigation của chính phase này ("nghiêng về `no_match` khi
không chắc"); nay lỗi parser của Beam rơi về `no_match` và vẫn khoá.

### Known-gap: khoá thật vẫn chưa gỡ

`identity_status='unresolvable'` được đặt **kể cả khi mọi provider đều chết**, và sweep chỉ chọn
`anonymous`. <!-- Updated: Validation Session 3 (06-08-26) — sweep nằm ở HAI file, không phải một:
`resolution_runner.py:130` (LIMIT 20) và `resolution_tasks.py:79` (LIMIT 50, task Celery beat).
Dòng gốc chỉ ghi `resolution_tasks.py`. Xem Phase 5 §bẫy #6. -->
Nên gỡ khoá 30 ngày **chưa unlock ai**: từ nay
outage không tạo khoá mới, nhưng 8 visitor đang kẹt vẫn kẹt.
<!-- Updated 06-08-26 — Phase 5 đã cook: nguồn tạo khoá mới ĐÃ BỊT (outage không còn ghi
`unresolvable`, nó giữ `anonymous` + đặt `resolution_deferred_until`), và cả HAI sweep đều lọc
mốc hoãn. Phần CHƯA giải quyết: 8 visitor kẹt từ trước vẫn kẹt — Phase 5 không backfill row cũ.
Muốn gỡ phải chạy tay hoặc chờ `revive_returning_unresolvable` khi IP đổi. -->
 Cần một quyết định riêng (đổi thời
điểm đánh `unresolvable` → đổi tập visitor được sweep → ảnh hưởng chi phí). Đã ghi trong header
`scripts/identity_locked_visitors_audit.sql`.

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| Phân loại sai → outage bị coi là no_match, hoặc ngược lại: no_match thật bị bỏ qua nên thử lại vô hạn | Ranh giới viết thành hợp đồng ở bước 1 + test cho từng mã trạng thái. Nghiêng về "no_match" khi không chắc — thà khoá nhầm còn hơn gọi provider vô hạn |
| Không còn khoá khi outage → sweep thử lại liên tục một visitor không thể giải | Ngân sách ngày và giới hạn `SWEEP_MAX_RESOLVE_PER_SITE=20` vẫn chặn. Preflight health (bước 6) chặn tận gốc |
| Sửa 5 mixin cùng lúc dễ gây regression | Mỗi mixin một commit, chạy test giữa các bước; RB2B trước vì nó là provider duy nhất đang thực sự chạy |
| Xoá log lịch sử làm hỏng sổ chi phí | Bước 5 chỉ liệt kê, không xoá. Quyết định thuộc về user |
