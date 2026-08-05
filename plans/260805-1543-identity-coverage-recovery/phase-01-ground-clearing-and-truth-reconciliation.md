---
phase: 1
title: "Ground clearing and truth reconciliation"
status: complete
priority: P1
dependencies: []
---

# Phase 1: Ground clearing and truth reconciliation

## Overview

Dọn ba thứ đang làm nhiễu bức tranh: một plan đã xong nhưng chưa archive (tạo ra "xung đột
2 plan" giả), một provider gọi vào host không tồn tại, và một cơ chế retry lãng phí 5 giây mỗi
visitor cho host đó. Không đụng tới vendor nào còn sống — thuần dọn nợ.

## Requirements

- Functional: waterfall không còn gọi provider không thể hoạt động; trạng thái plan phản ánh
  đúng thực tế trên disk.
- Non-functional: không đổi hành vi của RB2B/PDL/IPinfo; không thêm migration; test hiện có
  phải xanh nguyên.

## Architecture

Ba việc độc lập, không có thứ tự bắt buộc giữa chúng:

```
A. Archive plan đã xong          → plans/260802-1854-cookie-fp-phase2/
B. Vô hiệu Capturify an toàn     → config default OFF + guard rõ lý do
C. Không retry lỗi DNS vĩnh viễn → base.py _is_transient_http_error
```

**Về (B) — vì sao vô hiệu chứ không xoá:** `api.capturify.io` không tồn tại, nhưng
`app.capturify.io` (host pixel trong `tracker.js`) thì có thật. Nghĩa là sản phẩm Capturify tồn
tại, chỉ base URL trong code là sai/đoán. Xoá hẳn provider sẽ mất luôn phần parse đã viết; vô
hiệu + ghi rõ lý do giữ được đường quay lại nếu lấy được doc thật (Phase 3).

**Về (C) — vì sao quan trọng:** `httpx.ConnectError` hiện bị xếp là lỗi tạm thời
([base.py:27-31](apps/api/services/identity_providers/base.py#L27-L31)) → tenacity retry 3 lần,
backoff 1→2s. Với host không phân giải được, cả 3 lần đều chắc chắn hỏng. Vì
`_resolve_identity_graphs_parallel` dùng `asyncio.gather` (chờ TẤT CẢ), bước identity-graph sẽ
**luôn mất trọn 5s timeout** cho mọi visitor. DNS NXDOMAIN là lỗi vĩnh viễn, không phải tạm thời.

Phân biệt cần thiết:
- `httpx.ConnectError` do **DNS không phân giải** → vĩnh viễn, KHÔNG retry
- `httpx.ConnectError` do **connection refused / mạng chập** → tạm thời, GIỮ retry

<!-- Updated: Validation Session 1 - phạm vi fix giới hạn ở base.py; ghi nhận 5 bản sao khác -->

⚠️ **`_is_transient_http_error` KHÔNG tập trung — bị nhân bản 6 chỗ** (grep 05-08-26):

| File | Ghi chú |
|---|---|
| `identity_providers/base.py:23` | ← **phạm vi sửa của phase này** |
| `services/crm/base.py:30` | không sửa |
| `services/ads/meta.py:79` | comment ghi rõ "replicated locally" |
| `services/ads/google.py:85` | comment ghi rõ "replicated locally" |
| `services/enricher.py:47` | không sửa — nhưng cũng gọi external API kiểu waterfall, dính cùng bẫy |
| `services/phantommm_client.py:54` | không sửa |

**Quyết định (validation session 1): chỉ sửa `identity_providers/base.py`.** Đúng phạm vi vấn đề
đang gặp (Capturify), theo YAGNI. Việc nhân bản là **có chủ đích** (comment trong `ads/meta.py`
và `ads/google.py` nói rõ), nên gộp lại là refactor riêng, không thuộc phase này.

**Ghi nhận nợ kỹ thuật:** 5 bản sao còn lại vẫn xếp lỗi DNS là tạm thời. `enricher.py` đáng chú ý
nhất vì nó cũng chạy waterfall gọi provider ngoài — nếu có host chết ở đó, sẽ lặp lại đúng hiện
tượng tốn thời gian retry vô ích.

## Related Code Files

- Modify: `apps/api/services/identity_providers/base.py` — `_is_transient_http_error`
- Modify: `apps/api/config.py` — `capturify_enabled` default `True` → `False` + comment lý do
- Modify: `apps/api/services/identity_providers/capturify.py` — docstring ghi rõ base URL chưa
  xác minh, không đổi logic
- Move: `plans/260802-1854-cookie-fp-phase2/` → archive theo quy ước repo
- Tests: thêm unit test cho phân loại DNS-vs-transient

## Implementation Steps

1. **Archive plan đã hoàn thành.** `plans/260802-1854-cookie-fp-phase2/plan.md` có đủ 5/5
   acceptance đã tick, và 4 thay đổi của nó đã nằm trong `dev_nhantc2` (commit `0ff8c9a`):
   `withCredentials` ([tracker.js:238](apps/pixel/src/tracker.js#L238)), CORS echo
   ([main.py:137,212](apps/api/main.py#L137)), visitor stub upsert
   ([events.py](apps/api/routers/events.py)). Archive nó và ghi một dòng vào
   `docs/identity-us-current-handoff.md` nói rõ **không có xung đột 2 plan** — chỉ trùng nhãn
   "Phase 2" giữa hai phạm vi khác nhau (first-party cookie/FP vs vendor webhook ingest).

2. **Phân loại lỗi DNS là vĩnh viễn.** Trong `_is_transient_http_error`, tách
   `httpx.ConnectError` do DNS: kiểm tra `isinstance(exc.__cause__, socket.gaierror)` (httpx bọc
   lỗi phân giải tên vào đây) → trả `False`. Mọi `ConnectError` khác giữ nguyên `True`.

3. **Đặt `capturify_enabled` mặc định `False`** kèm comment nêu bằng chứng: host
   `api.capturify.io` không có bản ghi DNS tính đến 05-08-26; bật lại chỉ sau khi có base URL
   xác minh được từ doc chính thức.

4. **Test:** unit test cho (a) `gaierror` → không retry, (b) `ConnectError` thường → vẫn retry,
   (c) waterfall bỏ qua Capturify khi flag off mà không ghi dòng `resolution_logs` nào.

5. **Chạy audit lại** (`scripts/identity_resolution_audit.sql`) để chụp baseline sau khi dọn.

## Success Criteria

- [x] `plans/260802-1854-cookie-fp-phase2/` đã archive (`git mv` → `plans/completed/`); handoff doc
      ghi rõ xung đột plan là giả, và 4 khẳng định lỗi thời trong đó đã sửa
- [x] `gaierror` không còn bị retry; `ConnectError` khác vẫn retry 3 lần
- [x] Chỉ sửa `identity_providers/base.py`; 5 bản sao khác **không đụng tới**, đã ghi nhận nợ kỹ thuật
- [x] `capturify_enabled` mặc định `False`, có comment nêu bằng chứng DNS (+ test khoá lại default)
- [x] Bật `CAPTURIFY_API_KEY` không còn làm bước identity-graph mất 5s/visitor
- [x] Toàn bộ test unit identity xanh (1591 passed, 2 skipped); không có migration mới

### Ghi chú thực thi (05-08-26)

Cách bắt lỗi DNS mà plan đề xuất — `isinstance(exc.__cause__, socket.gaierror)` — **không chạy**
trên `httpx==0.27.2`. Probe thật cho thấy chuỗi là `httpx.ConnectError` → `__cause__`
`httpcore.ConnectError`, và `gaierror` nằm trong **`args`** của mắt xích đó chứ không phải
`__cause__`. Bản cài đặt duyệt cả `__cause__` lẫn `args` ở mỗi mắt xích, có chặn độ sâu để không
treo khi chuỗi tự trỏ vòng. Đã xác minh: NXDOMAIN → `True`, connection-refused → `False`. Đây
đúng là rủi ro plan đã lường trước ở bảng Risk Assessment — và nó xảy ra thật.

Test dùng host `.invalid` (RFC 2606, không bao giờ phân giải) để dựng chuỗi lỗi **thật** thay vì
chỉ tin vào exception ghép tay — nếu httpx đổi cách bọc lỗi ở version sau, test sẽ đỏ thay vì âm
thầm quay lại hành vi retry host chết. Chạy 3 lần, không flake, không cần mạng.

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| Cách httpx bọc lỗi DNS khác nhau giữa các version → check `__cause__` không bắt được | Viết test trực tiếp trên version httpx đang pin trong `requirements.txt`; nếu không bắt được thì fallback: match message, và ghi known-gap thay vì đoán |
| Tắt Capturify che mất khả năng nó từng chạy được ở đâu đó | Audit đã cho thấy Capturify **chưa từng** xuất hiện trong `resolution_logs` — không có gì để mất |
| Archive plan làm mất dấu vết lịch sử | Archive theo quy ước repo (giữ file, đổi vị trí), không xoá |
