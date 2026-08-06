# Code review trước khi làm Phase 5 (outage deferral watermark)

**Ngày:** 06-08-26 · **Branch:** `dev_nhantc2` @ `191b919` · **Phạm vi:** đọc-only
**Plan:** `plans/260805-1543-identity-coverage-recovery/phase-05-outage-deferral-watermark.md`

---

## TL;DR

Nền sạch — code hỏng của session 3 **đã revert hết**, không còn tàn dư. Nhưng plan viết **trước**
Phase 2 và trước thay đổi hôm nay, nên nó **thiếu một cái bẫy thứ 5** do chính thay đổi hôm nay
tạo ra. Làm theo plan y nguyên sẽ dính bẫy đó.

---

## 1. Trạng thái 4 cái bẫy trong plan, đối chiếu code hiện tại

| Bẫy | Plan mô tả | Code hiện tại | Kết luận |
|---|---|---|---|
| **#1** gộp bộ đếm 2 tầng | `_providers_answered` / `_providers_unavailable` dùng chung 5 provider | **Không tồn tại.** Grep toàn `apps/api/services`: 0 hit cho cả 2 tên và `_finalize_unmatched`. [identity_resolver.py:602](apps/api/services/identity_resolver.py#L602) gán `unresolvable` **vô điều kiện** | ✅ đã revert sạch — làm lại từ nền trắng |
| **#2** Redis circuit breaker | `INCR`/`EXPIRE` không nguyên tử, đếm liên tiếp | Không còn breaker nào trong resolver | ✅ đã revert sạch |
| **#3** hoãn rồi vẫn tốn tiền | `check_ip_privacy` chạy trước mọi bộ đếm, không cache khi lỗi | **CÒN NGUYÊN** — [identity_resolver.py:505-518](apps/api/services/identity_resolver.py#L505-L518): gọi trước toàn bộ waterfall, `except Exception` chỉ log debug, không cache | ⚠️ vẫn phải xử |
| **#4** cache âm 24h nuốt lần thử sau | `__none__` TTL 24h ghi cả khi provider chết | **CÒN NGUYÊN** — [identity_resolver.py:551-562](apps/api/services/identity_resolver.py#L551-L562) ghi `__none__` TTL 86400 bất kể lý do; [`_resolve_ip_company_parallel`](apps/api/services/identity_resolver.py#L758) trả `str \| None`, người gọi **không thể** phân biệt "IP không có công ty" với "cả 2 provider chết" | ⚠️ vẫn phải xử, và đây là thay đổi chữ ký hàm |

Sweep query xác nhận đúng như plan mô tả:
[resolution_runner.py:130](apps/api/services/resolution_runner.py#L130) lọc
`identity_status == "anonymous"`, sắp theo `intent_score DESC`, `max_resolve=20`.

---

## 2. 🔴 Bẫy #5 — plan KHÔNG biết, do thay đổi hôm nay tạo ra

Commit `12d6059` hôm nay thêm `ProviderNotConfiguredError` → `_fetch` trả **`attempted=False`**
([identity_resolver.py:635-647](apps/api/services/identity_resolver.py#L635-L647)). Đây là
**trạng thái thứ ba**, không phải "đã trả lời" cũng không phải "chết":

| Nếu Phase 5 xếp `attempted=False` vào… | Hậu quả |
|---|---|
| **"unavailable"** | Site không có pixel Leadpipe → tầng person-graph **luôn** bị coi là chết → visitor hoãn **vĩnh viễn**, quay vòng sweep tới khi chạm trần backoff. Đúng cái vòng lặp plan muốn tránh |
| **"answered"** | Che mất outage thật của 2 provider còn lại — **cùng hình dạng với bẫy #1**, thất bại y hệt session 3 |
| **loại khỏi mẫu số** ✅ | Đúng |

**Quy tắc đúng:** một tầng bị coi là *chết* **chỉ khi** `≥1 provider attempted` **VÀ** *mọi*
provider attempted đều `unavailable`. Tầng có **0 provider attempted** là *không áp dụng* — không
chết, không trả lời, và **không được** kích hoạt hoãn.

Điều này khớp sẵn với Success Criteria #3 của plan ("không cấu hình provider nào → vẫn terminal"),
nhưng **cơ chế** (`attempted=False`) thì mới, plan chưa biết.

**Tin tốt:** `_fetch` đã trả sẵn tuple `(name, data, elapsed, attempted, unavailable_detail)` —
đủ thông tin cho việc đếm theo tầng, **không cần refactor**.

**Tin xấu:** tầng IP→company thì **chưa** —
[`_resolve_ip_company_parallel`](apps/api/services/identity_resolver.py#L758) chỉ trả `str | None`.
Phải mở rộng chữ ký để mang theo verdict của tầng. Đây cũng chính là thứ sửa được bẫy #4 (chặn
ghi cache âm khi outage) — **một thay đổi, hai bẫy**.

---

## 3. Thứ tự làm đề xuất

Đi từ thay đổi bắt buộc nhất tới ít nhất, mỗi bước tự kiểm được:

1. **Mở rộng `_resolve_ip_company_parallel`** trả `(domain, tier_verdict)` với verdict ∈
   {`answered`, `all_unavailable`, `not_applicable`}. → mở khoá bẫy #4 + đếm tầng IP.
2. **Thêm verdict tương tự cho tầng person-graph** từ tuple `_fetch` đã có. Áp quy tắc §2.
3. **Chặn ghi cache âm** khi verdict tầng IP là `all_unavailable`.
4. **Migration** `visitors.resolution_deferred_until` — chạy `alembic heads` ngay trước
   (**head hiện tại: `b4c9a71e35d8`**, đã đổi so với lúc viết plan).
5. **Nhánh trạng thái cuối** thay [line 602](apps/api/services/identity_resolver.py#L602):
   tầng-có-khả-năng-khớp chết → giữ `anonymous` + đặt mốc hoãn; ngược lại → `unresolvable` như cũ.
6. **Filter sweep** + skip reason `provider_outage` trong `visitors_helpers.py`.
7. **Bẫy #3** (`check_ip_privacy`): bỏ qua khi visitor đang trong cửa sổ hoãn.

---

## 4. Yêu cầu test — không thương lượng

Plan đã ghi và em xác nhận nó đúng: **cả 4 test cũ đều tự gán tay bộ đếm rồi gọi thẳng
`_finalize_unmatched`**, nên không test nào chạy `resolve()` thật — đó là lý do bẫy #1 lọt qua CI.

Test bắt buộc phải đi qua `resolve()` end-to-end cho **4 ca**:

| Ca | Kỳ vọng |
|---|---|
| 3 person-graph chết 403 + ipinfo trả lời no-match | **không** `unresolvable`, có mốc hoãn |
| Leadpipe `not_configured` + rb2b trả lời no-match | `unresolvable` như cũ (không hoãn) ← **ca của bẫy #5** |
| Không cấu hình provider nào | `unresolvable`, không vòng lặp |
| Mọi provider trả lời, không ai khớp | `unresolvable` như cũ |

Ca thứ 2 là ca mới, không có trong plan.

---

## 5. Rủi ro đã đổi so với lúc viết plan

| Plan ghi | Thực tế 06-08-26 |
|---|---|
| "Migration thứ 13 chồng lên 12 cái đang chờ" | Head thật là `b4c9a71e35d8`; chuỗi đã dài hơn. Phải chạy `alembic heads` lại, không tin số trong plan |
| "leadpipe/capturify/rb2b dùng CHUNG một tài khoản hỏng" (bẫy #1) | Không còn đúng: Capturify tắt mặc định (DNS chết), Leadpipe có org khoẻ riêng. Ca tái hiện bẫy #1 giờ phải dựng bằng mock, không quan sát được tự nhiên nữa |

---

## Unresolved Questions

1. Trần backoff bao nhiêu lần rồi mới chấp nhận `unresolvable`? Plan gợi ý 15p→1h→6h→24h nhưng
   không chốt số lần. Cần anh quyết — nó là đánh đổi giữa "mất visitor khi outage dài" và
   "visitor kẹt ở `anonymous` mãi".
2. Visitor đang hoãn có nên bị loại khỏi `daily_resolution_budget` không? Plan không nói. Nếu tính
   vào, một outage dài sẽ ăn hết budget mà không resolve được ai.
