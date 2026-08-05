---
title: "Identity coverage recovery - unblock and measure"
description: >-
  Gỡ blocker đang chặn đường coverage định danh visitor, tách "provider hỏng"
  khỏi "không khớp", và đặt tiêu chí quyết định giữ/bỏ từng provider dựa trên
  dữ liệu đo được thay vì phỏng đoán.
status: in-progress
priority: P1
branch: "dev_nhantc2"
tags:
  - identity
  - coverage
  - provider-health
blockedBy: []
blocks: []
created: "2026-08-05T08:47:56.360Z"
createdBy: "ck:plan"
source: skill
---

# Identity coverage recovery - unblock and measure

## Overview

Đường coverage định danh **đang đứng yên vì hạ tầng provider hỏng, không phải vì thuật toán kém**.
Ba provider trong waterfall trả phí: một hết hạn tài khoản (Leadpipe), một gọi vào host không
tồn tại (Capturify), một tạo ra false-positive rồi ghi sổ sai (RB2B). Plan này gỡ theo thứ tự
phụ thuộc, và quan trọng hơn — dựng cơ chế để lần sau *biết* provider hỏng thay vì đoán.

**Nguyên tắc xuyên suốt:** không tối ưu thuật toán ghép người khi chưa chứng minh được provider
thực sự trả dữ liệu. Mọi thay đổi phải đo được trước và sau.

### Bối cảnh đã điều tra (05-08-26)

| Phát hiện | Bằng chứng | Nguồn |
|---|---|---|
| **Pixel Leadpipe ĐANG CHẠY trên site lab** — đảo ngược handoff doc | `leadpipe.aws53.cloud/p/3ead3e50-…js` → **HTTP 200**, payload ghi `"domain":"beamlab.nhantown.com"`; SDK chain → 200 | kiểm tra live 05-08-26 |
| Nhưng pixel **dán tay vào HTML**, không qua `data-stack` của Beam | thẻ tracker Beam trên site lab không có attribute `data-stack` nào | cùng trên |
| Pixel Leadpipe là **per-domain** → 1 UUID toàn cục không dùng chung được | payload pixel ghi cứng `"domain"` | cùng trên |
| **Beam không có code đăng ký domain / tạo pixel** — mắt xích chặn multi-tenant | grep toàn repo: 0 lần gọi `POST /v1/data/pixels`; docs Leadpipe yêu cầu tạo pixel per-domain rồi mới có dữ liệu | [docs Leadpipe](https://docs.leadpipe.com/api-reference/pixels/create-a-pixel-for-a-domain) + grep 05-08-26 |
| **API Leadpipe chặn cứng: `403 "Organization is expired"`** — cả `GET /v1/data` lẫn `POST /v1/data/pixels` | test bằng API key thật 05-08-26 09:30 UTC | user chạy curl |
| Pixel phục vụ được **nhưng** dữ liệu không đọc về được → Leadpipe thực chất **không dùng được** | pixel 200 (CDN không kiểm tra org) vs API 403 (gate ở tầng tài khoản) | tổng hợp 2 dòng trên |
| ~~Handoff doc: 0 pixel, URL 404~~ — **sai**; nhưng phần `org_status=expired` thì **đúng** | pixel rõ ràng tồn tại và phục vụ; số liệu account không đáng tin khi org hết hạn | `docs/identity-us-current-handoff.md` (đã sửa 05-08) |
| `api.capturify.io` **không có bản ghi DNS** | nslookup → NXDOMAIN | kiểm tra 05-08-26 |
| RB2B: 8 success log → 1 identity, và identity đó sai | audit SQL + handoff doc trùng khớp độc lập | `scripts/identity_resolution_audit.sql` |
| Retry-lock 30 ngày kích hoạt cả khi provider hỏng | `resolution_logs` ghi `success=False, cost=0.0` như nhau cho outage và no-match | `identity_resolver.py:123-132` |
| "2 plan Phase 2 cạnh tranh" là **xung đột giả** | `plans/260802-1854-cookie-fp-phase2/` đã xong hết acceptance, chính là commit `0ff8c9a` | xác minh 05-08-26 |

### Ràng buộc

- **Không bật `auto_identify_enabled`** cho tới khi provider health được xác minh (giữ nguyên
  ràng buộc từ handoff doc).
- **Không coi `Candidate` là `Verified`.** `EMAILABLE_PROVIDERS`, `is_privacy_relay_ip`,
  `name_email_consistent` không được nới lỏng.
- **Merge `dev_nhantc2` → `main` (PROD) đã được user hoãn lại** — không tự ý làm.
- Không thêm migration mới cho provider có thể bị bỏ (12 migration đang chờ apply live).

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Ground clearing and truth reconciliation](./phase-01-ground-clearing-and-truth-reconciliation.md) | **Complete** (05-08-26) |
| 2 | [Provider failure vs no-match separation](./phase-02-provider-failure-vs-no-match-separation.md) | **Complete** (05-08-26) — 1 known-gap |
| 3 | [Vendor decision and Leadpipe restoration](./phase-03-vendor-decision-and-leadpipe-restoration.md) | Pending — chặn ở thao tác tài khoản vendor (ngoài code) |
| 4 | [Webhook ingest and measurable coverage](./phase-04-webhook-ingest-and-measurable-coverage.md) | Pending — chặn cứng sau Phase 3 |
| 5 | [Outage deferral watermark](./phase-05-outage-deferral-watermark.md) | Pending — **cần migration**; đã thử ở session 3 và REVERT |

Phase 1–2 **không phụ thuộc vendor** — chạy được ngay.
Phase 3 là **gate quyết định business**, chặn Phase 4.

```
Phase 1 ──► Phase 2 ──► [GATE: quyết định vendor] ──► Phase 3 ──► Phase 4
(dọn nền)   (đo đúng)         ↑ user quyết          (khôi phục)  (webhook + benchmark)
```

## Câu hỏi quyết định trung tâm

Chi phí không phải blocker (có API token free), nhưng **org hiện tại đã hết hạn** nên API bị chặn
hoàn toàn. Sau khi giải quyết tài khoản, câu hỏi còn lại là:

> **Đo được cái gì, và KHÔNG đo được cái gì?**

| Chỉ số | Đo được chưa? | Vì sao |
|---|---|---|
| Coverage (% visitor có identity) | **Chưa — chặn ở `/v1/data` 403**; đo được ngay sau khi org free mới thông (Phase 3) | không cần ground truth |
| Precision (% identity đúng người) | **CHƯA — hoãn chính thức (session 2)** | cần `N>=30` tester US, chưa có nguồn cam kết → KNOWN-GAP ở Phase 4 |
| Cost per correct identity | **CHƯA** | phụ thuộc precision → hoãn theo |

Hệ quả phải chấp nhận rõ ràng: giai đoạn này chỉ chứng minh được **đường ống hoạt động**, không
chứng minh được **kết quả đúng**. Baseline hiện tại đã cho thấy chênh lệch đó nguy hiểm thế nào —
RB2B báo 8 success, thực tế 1 identity, và identity đó sai. Coverage đẹp mà precision không đo
được thì lặp lại đúng cái bẫy ấy.

Vì vậy mọi identity từ person-graph giữ nguyên `provider_candidate`, không lên `verified`, cho
tới khi có ground truth.

## Dependencies

- **Thay thế/gộp:** `process/features/visitors-identity/active/identity-coverage-pixel-fppro_02-08-26/`
  — Phase 2 của program đó (`phase-02-wire-candidate-ingest-from-vendor-callbacks.md`) được
  Phase 4 của plan này kế thừa và mở rộng. Phase 3/4 (Fingerprint Pro, US benchmark) của program
  đó **giữ nguyên**, không đụng tới.
- **Đóng lại:** `plans/260802-1854-cookie-fp-phase2/` — đã hoàn thành, cần archive (Phase 1).
- **Đọc trước:** `docs/identity-us-current-handoff.md`, `docs/visitor-identity-flow-architecture.md`
- **Công cụ đo:** `scripts/identity_resolution_audit.sql`

## Validation Log

### Session 1 — 05-08-26

#### Verification Results

- **Tier:** Standard (4 phases → Fact Checker + Contract Verifier)
- **Claims checked:** 30
- **Verified:** 27 | **Failed:** 3 | **Unverified:** 0

##### Failures

1. **[Contract Verifier]** `_log_resolution` — plan ghi "modify 1 file"; grep thấy **7 call site
   production trên 4 file** (`identity_resolver.py:660,674,728,732`, `pdl.py:52`, `apollo.py:28`,
   `hunter.py:28`) **+ 13 mock trên 4 file test**, trong đó `test_identity_resolver_parallel.py:312`
   và `test_provider_toggles.py:79` assert theo vị trí tham số.
2. **[Fact Checker]** Claim "outage vẫn quan sát được qua `api_usage_logs`" chỉ đúng với dashboard
   chi phí. `visitors.py:630-637` đọc **`ResolutionLog`** để dựng `resolution_providers_tried` —
   trang chi tiết visitor sẽ mất khả năng thấy outage.
3. **[Fact Checker]** `_is_transient_http_error` **không tập trung** — nhân bản ở 6 module
   (`identity_providers/base.py`, `crm/base.py`, `ads/meta.py`, `ads/google.py`, `enricher.py`,
   `phantommm_client.py`). Sửa 1 chỗ không phải sửa toàn hệ thống.

##### Phát hiện phụ (tích cực, ngoài dự kiến)

- `api_usage_logs` đã có cột `meta: JSONB` → ghi lý do outage **không cần migration**.
- `price_for()` trả `0.0` khi `success=False` ([api_pricing.py:46](apps/api/services/api_pricing.py#L46))
  → ghi outage vào ledger **không làm sai sổ chi phí**.
- Toàn bộ claim Phase 3 và Phase 4 VERIFIED, kể cả pattern `custom_args` mà Phase 4 viện dẫn
  (`email_sender.py:56`, `campaign_sender.py:324`, `webhooks.py:81`).

#### Quyết định

| # | Câu hỏi | Quyết định | Ảnh hưởng |
|---|---|---|---|
| 1 | Xử lý blast radius `_log_resolution` | **Thêm `outcome` keyword-only có default** | 7 call site + 13 mock không cần đổi; chỉ mixin phân biệt được lỗi hạ tầng mới truyền |
| 2 | UI visitor mất khả năng thấy outage | **Cho `visitors.py` đọc thêm `api_usage_logs`** | Phase 2 thêm 1 file sửa; không migration |
| 3 | Phạm vi fix DNS-retry | **Chỉ `identity_providers/base.py`** | 5 bản sao khác ghi nhận là nợ kỹ thuật, không sửa |

#### Whole-Plan Consistency Sweep

- **Files reread:** `plan.md`, `phase-01-…`, `phase-02-…`, `phase-03-…`, `phase-04-…`
- **Decision deltas checked:** 4 (keyword-only param; đọc thêm api_usage_logs; giới hạn phạm vi
  fix; chi phí không còn là blocker nhưng org hết hạn thì có)
- **Reconciled stale references:** 7
  - `plan.md` — (a) bảng bối cảnh còn ghi `/v1/data` "chưa test lại" trong khi đã test và trả 403;
    (b) mục Câu hỏi trung tâm còn nói "pixel đã chứng minh chạy" mà không nêu API bị chặn;
    (c) bảng chỉ số ghi Coverage "Được" trong khi đang bị 403 chặn.
  - `phase-03` — (d) Overview còn đóng khung vấn đề là "có trả tiền không" và nhắc "sửa URL" (giả
    thuyết đã bị bác bỏ); (e) Requirements còn yêu cầu verify pixel đang chạy — pixel đã verify
    rồi, nút thắt chuyển sang API; (f) tiêu chí "Chi phí gia hạn" thay bằng "Tài khoản còn hiệu lực".
  - `phase-04` — (g) Overview còn ghi điều kiện tiên quyết là "pixel đã verify xanh"; điều kiện
    thật là tài khoản hết bị chặn.
- **Unresolved contradictions:** 0

Ghi chú trung thực: lần sweep đầu tôi ghi "reconciled 3 / unresolved 0" sau khi mới đọc lại
`plan.md`. Đọc tiếp `phase-03` thì thấy thêm 3 chỗ lỗi thời — con số đã sửa lại ở trên. Bài học:
sweep chỉ hợp lệ khi đã đọc lại ĐỦ mọi phase file, không suy ra từ file vừa sửa.

### Session 2 — 05-08-26

#### Verification Results

- **Tier:** Standard (4 phases → Fact Checker + Contract Verifier)
- **Claims checked:** 18 (spot-check các claim dẫn tới quyết định còn mở, không lặp lại 30 claim
  của session 1)
- **Verified:** 15 | **Failed:** 2 | **Unverified:** 1

##### Failures

1. **[Contract Verifier]** Phase 2 bước 4 ghi 3 counter (`no_timestamp` / `outside_window` /
   `ip_mismatch`) đều nằm ở `matching.py`. Grep: `matching.py` **không có logic IP nào** — bộ lọc
   IP nằm ở [leadpipe.py:71](apps/api/services/identity_providers/leadpipe.py#L71), và log ở mức
   `debug` ([leadpipe.py:87](apps/api/services/identity_providers/leadpipe.py#L87)), không phải
   `info` như plan ghi. Cùng loại lỗi với failure #1 của session 1: plan gọi tên 1 file, thay đổi
   thật trải trên 2.
2. **[Fact Checker]** **Sweep session 1 khai `Unresolved contradictions: 0` là SAI.** `phase-03`
   còn **7 chỗ lỗi thời**, phần lớn mâu thuẫn với chính kết luận nằm phía trên trong cùng file:
   (a) §Bối cảnh mục 3 "`/v1/data` chưa test lại được vì cần API key" ↔ §KẾT LUẬN ngay trên đã
   test, 403 cả hai; (b) "403 có thể do sai method, phải test lại bằng POST" ↔ POST đã test, vẫn
   403; (c) Step 3 + Success Criteria chọn "A hoặc B" ↔ §Architecture nói B sai bản chất;
   (d) Success Criteria 1 "test lại với token hiện tại" ↔ đã xong, thành tiêu chí rỗng; (e) Risk
   "sửa URL pixel dựa trên giả định sai" ↔ plan.md đã chốt không cần sửa `tracker.js:624`;
   (f) Risk "chỉ bật sau khi pixel verify 200" ↔ pixel đã 200, gate thật là API 2xx;
   (g) Related Code Files liệt kê sửa `tracker.js — vendorUrls.leadpipe` ↔ pattern URL đã verify đúng.

##### Unverified

- Leadpipe có hỗ trợ custom param echo trong webhook không (open question 4) — doc công khai không
  đề cập. Vẫn là câu hỏi chặn thiết kế ghép người ở Phase 4.

##### Đã verify đúng (không phải lỗi)

`_log_resolution` 7 call site / 4 file + 13 mock; `api_usage_logs.meta` là `JSONB`
([api_usage.py:46](apps/api/models/api_usage.py#L46)); [visitors.py:629-637](apps/api/routers/visitors.py#L629)
đọc `ResolutionLog`; [rb2b.py:188](apps/api/services/identity_providers/rb2b.py#L188) trả `None`
cho 403; 6 bản sao `_is_transient_http_error`; `EMAILABLE_PROVIDERS` không chứa leadpipe
([identity_classification.py:51](apps/api/services/identity_classification.py#L51));
[sites.py:284](apps/api/routers/sites.py#L284) comment xác nhận "global pixel id only, `Site` has
no leadpipe_pixel_id column" → phê phán đường B trong plan là **đúng**.

#### Quyết định

| # | Câu hỏi | Quyết định | Ảnh hưởng |
|---|---|---|---|
| 1 | Org Leadpipe hết hạn | **Tạo org free mới** | Phase 3 bước 1–3 viết lại theo trình tự tạo pixel → thay thẻ script → verify `/v1/data`. Pixel id cũ `3ead3e50-…` thành vô dụng |
| 2 | Đường nạp pixel | **Giữ A (dán tay), gỡ B khỏi plan** | B không còn là lựa chọn hợp lệ ở bất kỳ chỗ nào; C đẩy sang plan sau (cần migration) |
| 3 | Capturify | **Vô hiệu, giữ code, không liên hệ vendor** | Phase 3 bước 6 bỏ hành động "liên hệ lấy doc" — việc ngoài code không thời hạn, sẽ treo plan |
| 4 | Benchmark precision US | **Hoãn chính thức** | Phase 4 `N>=30` chuyển từ success criteria → KNOWN-GAP; ngưỡng đóng phase là smoke 5 session |
| 5 | Phạm vi counter `ip_mismatch` | **2 counter `matching.py` + 1 `leadpipe.py`** | Phase 2 Related Code Files thêm `leadpipe.py`; không chuyển logic lọc IP (refactor đổi hành vi, ngoài phạm vi) |
| 6 | Dọn `ResolutionLog` khoá oan | **Giữ read-only, quyết định sau** | Phase 2 bước 5 siết lại: chỉ liệt kê, không xoá/đánh dấu. Lý do: chưa xác định được cửa sổ thời gian 403 |

#### Whole-Plan Consistency Sweep

- **Files reread:** `plan.md`, `phase-01-…`, `phase-02-…`, `phase-03-…`, `phase-04-…` (đọc đủ 5
  trước khi kết luận — đúng bài học ghi ở cuối session 1)
- **Decision deltas checked:** 6
- **Reconciled stale references:** 11
  - `phase-03` — 7 chỗ ở failure #2 trên, tất cả đã sửa: bảng 3 lựa chọn đánh dấu ĐÃ CHỌN; §Bối
    cảnh mục 3 viết lại thành "đúng một nửa"; giả thuyết sai-method gạch bỏ; bảng A/B/C gạch B;
    Trình tự còn lại viết lại 5 bước theo org mới; Related Code Files đảo thành danh sách
    KHÔNG-sửa tường minh; Success Criteria + Risk Assessment thay bằng tiêu chí/rủi ro của đường
    org mới (thêm rủi ro "quên thay thẻ script" — cái bẫy đã mắc một lần)
  - `phase-02` — (h) bước 4 counter scope; (i) Related Code Files thêm `leadpipe.py`; (j) bước 5
    siết read-only
  - `phase-04` — (k) Overview: điều kiện tiên quyết đổi từ "tài khoản hết bị chặn" sang "org mới +
    `/v1/data` trả dữ liệu thật", nêu rõ pixel 200 KHÔNG phải tín hiệu đủ
- **Unresolved contradictions:** 0

Ghi chú trung thực: con số "0 unresolved" của session 1 không đúng — `phase-03` khi đó còn 7 chỗ
lỗi thời, nhiều chỗ tự mâu thuẫn trong cùng một file. Bài học session 1 ("phải đọc lại đủ mọi
phase file") là đúng nhưng chưa đủ: đọc lại rồi vẫn có thể bỏ sót nếu chỉ soát phần vừa sửa mà
không soát Success Criteria / Risk Assessment / Related Code Files — ba mục hay ôm giả định cũ nhất
vì chúng nằm cuối file.

## Execution Log

### Session 3 — 05-08-26 — EXECUTE Phase 1 + 2

Phase 3–4 không chạy: bước đầu Phase 3 là thao tác tài khoản trên dashboard Leadpipe (tạo org
free mới), không phải việc code. Phase 4 chặn cứng sau Phase 3.

**Kết quả test:** unit `1591 passed, 2 skipped` (thêm 43 test mới, 0 flake qua 3 lần chạy);
integration `13/13 passed` (`test_beam_identity.py`, `test_resolution_budget.py`);
`scripts/identity_locked_visitors_audit.sql` chạy thật trên Postgres local, 4 SELECT, 0 ghi.
Không có migration mới.

#### Ba giả định của plan bị dữ liệu thật bác bỏ

| Plan viết | Thực tế đo được | Hệ quả |
|---|---|---|
| `isinstance(exc.__cause__, socket.gaierror)` bắt được lỗi DNS | **SAI với httpx 0.27.2.** Chuỗi thật: `httpx.ConnectError` → `__cause__` `httpcore.ConnectError`, và `gaierror` nằm trong **`args`** của nó, không phải `__cause__` | Phải duyệt cả chuỗi `__cause__` **và** `args`. Rủi ro plan đã lường trước ("cách httpx bọc lỗi khác nhau giữa các version") — đúng là có thật |
| Leadpipe 403 khoá oan 6/7 visitor US | **Không có bằng chứng.** `docs/identity-us-current-handoff.md` ghi `leadpipe logs = 0`; audit chạy thật cho thấy **`ipinfo` 9 lần/0 thành công** và **`pdl_ip_enrich` 9 lần/0 thành công** mới là bên ghi các dòng khoá | Đổi mục tiêu sửa. Xem H-1 dưới. Ảnh hưởng cả khung quyết định vendor ở Phase 3 |
| Visitor bị khoá có `identity_status = 'anonymous'` | **SAI.** `_resolve_full_waterfall` đặt `unresolvable` ở cuối mọi lượt không thành công → visitor đi qua waterfall **không bao giờ** còn là `anonymous`. Handoff doc cũng ghi "6/7 US-**unresolvable**" | Script audit bản đầu lọc `anonymous` → trả **0 dòng**, mù hoàn toàn với đúng nhóm cần tìm. Đã sửa thành `IN ('anonymous','unresolvable')` → trả 8 visitor |

#### Lệch so với plan (có chủ đích)

| # | Plan | Đã làm | Lý do |
|---|---|---|---|
| 1 | `outcome` default `"no_match"` | default `None` → suy ra từ `success` | Vẫn keyword-only + có default nên 7 call site + 13 mock không đổi (tiêu chí gốc giữ nguyên), nhưng `meta.outcome` ghi đúng `match`/`no_match` thay vì luôn `no_match` |
| 2 | 3 counter loại bỏ | **4** — thêm `no_email` | `leadpipe.py` có một `continue` không đếm; `scanned` và tổng counter không khớp nhau, tức là vẫn còn chỗ mù |
| 3 | — | Thêm `safe_failure_detail()` | Xem C-2 dưới |
| 4 | — | Chặn ghi ledger khi provider thiếu key | Xem H-1 dưới |

#### Lỗi tự gây ra, phát hiện ở code review, đã sửa

- **C-2 — rò rỉ secret (nghiêm trọng).** Bản đầu ghi `detail = f"{type(exc).__name__}: {exc}"` vào
  `api_usage_logs.meta`. httpx nhét **nguyên URL request** vào `HTTPStatusError.__str__`, mà
  `ipinfo` truyền token qua query param (`?token=`) và IP visitor trong path. Đã xác minh bằng
  chạy thật: chuỗi 200 ký tự chứa **cả token sống lẫn IP**, ghi vĩnh viễn vào DB và nằm ngoài
  đường xoá GDPR. Sửa: `safe_failure_detail()` chỉ lấy tên exception + mã HTTP; bỏ luôn
  `resp.text[:120]` khỏi mọi `ProviderUnavailableError`.
- **Bắt exception quá rộng.** Bản đầu xếp *mọi* exception lạ thành `provider_unavailable` —
  ngược đúng với mitigation plan tự ghi ("nghiêng về `no_match` khi không chắc"). Một `KeyError`
  trong parser của Beam sẽ thành "không khoá" → sweep thử lại vô hạn. Sửa: chỉ
  `httpx.TransportError`/`HTTPStatusError`/timeout/`ProviderUnavailableError` là outage; lỗi lạ
  rơi về `no_match` (vẫn khoá).
- **Tên log động.** `logger.warning(f"{label}_timeout")` phá grep và alert theo event name → đổi
  thành event tĩnh + `provider=label`.
- **`RESOLUTION_OUTCOMES` khai báo nhưng không dùng** → giờ validate `outcome`, sai chính tả ném
  `ValueError` thay vì âm thầm rơi vào nhánh "không phải outage" và khoá oan trở lại.

#### H-1 — mở rộng phạm vi (user duyệt session 3)

`_resolve_ip_company_parallel` chỉ kiểm cờ `*_enabled` (mặc định `True`) trước khi ghi ledger,
trong khi `_call_pdl_ip_enrich`/`_call_ipinfo_api` trả `None` ngay khi **thiếu key**. Kết quả:
provider **chưa từng được gọi** vẫn bị ghi "đã thử, thất bại" → khoá 30 ngày + tốn slot ngân sách
vì một khoảng trống cấu hình. Đây đúng loại bug Phase 2 đang sửa, nằm cách một hàm, và chính là
chữ ký của `ipinfo`/`pdl_ip` 9 lần/0 thành công trong audit. Đã sửa: `attempted = enabled AND
có key`, đúng pattern `_resolve_identity_graphs_parallel` vốn đã dùng.

#### Known-gap còn mở (KHÔNG sửa — user hoãn)

- **Khoá `unresolvable` mới là khoá ràng buộc thật.** `_resolve_full_waterfall` đặt
  `identity_status='unresolvable'` **kể cả khi mọi provider đều chết**, mà
  `apps/api/tasks/resolution_tasks.py` chỉ chọn `anonymous`. Nghĩa là gỡ khoá 30 ngày **chưa
  unlock ai cả** — mục tiêu business của Phase 2 mới đạt một nửa: từ nay outage không tạo khoá
  mới, nhưng 8 visitor đang kẹt vẫn kẹt. Ghi rõ trong header script audit.
- Hunter, Apollo, `_enrich_email_pdl`, RB2B bước 2–3 vẫn biến 401/403 thành no-match (plan ghi
  "Không đổi"; hợp đồng trong `base.py` hiện chưa phủ hết các đường này).
- `api_usage_logs` không nằm trong `delete_visitor_data`/`export_visitor_data` (DSAR). Trước đây
  outage ghi cả 2 bảng nên xoá vẫn sạch; giờ outage **chỉ** còn ở `api_usage_logs`.
- Truy vấn JSONB mới ở `visitors.py` chưa có index (`(site_id, visitor_id, created_at DESC)`) —
  cần migration nên hoãn theo ràng buộc plan.
- `outage_providers`/`last_outage_at` mới có ở API, chưa render trên UI.

## Open questions

1. ~~Chi phí gia hạn Leadpipe?~~ — **ĐÃ TRẢ LỜI 05-08-26:** có API token free dùng được.
2. ~~`/v1/data` còn 403 không?~~ — **ĐÃ TRẢ LỜI 05-08-26:** cả `GET /v1/data` lẫn
   `POST /v1/data/pixels` đều **403 `"Organization is expired"`**.
   → ~~tạo org free mới, gia hạn, hay bỏ?~~ **ĐÃ QUYẾT (session 2): tạo org free mới.**
3. ~~Nạp pixel theo đường nào?~~ — **ĐÃ QUYẾT (session 2): đường A (dán tay).** B bị loại hẳn
   (pixel gắn cứng 1 domain); C hoãn sang plan sau vì cần migration.
4. **Leadpipe có cho gắn custom param vào pixel rồi echo lại trong webhook không?** — **CÒN MỞ.**
   Quyết định toàn bộ thiết kế ghép người ở Phase 4. Doc công khai không đề cập; phải kiểm tra trên
   dashboard org mới sau khi tạo (Phase 3 bước 1). Nếu không có → rơi về ghép theo email rồi IP+time,
   và phải ghi rõ là probabilistic.
5. ~~Capturify có base URL thật không?~~ — **ĐÃ QUYẾT (session 2): vô hiệu, giữ code, không liên
   hệ vendor.** Bật lại chỉ khi tình cờ có doc thật.
6. ~~Traffic US cho benchmark `N>=30`?~~ — **ĐÃ QUYẾT (session 2): hoãn chính thức.** Chuyển thành
   KNOWN-GAP ở Phase 4. Precision không đo được cho tới khi có nguồn tester cam kết.
