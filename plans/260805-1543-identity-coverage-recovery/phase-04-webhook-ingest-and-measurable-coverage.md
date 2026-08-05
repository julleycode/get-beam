---
phase: 4
title: "Webhook ingest and measurable coverage"
status: pending
priority: P2
dependencies: [3]
---

# Phase 4: Webhook ingest and measurable coverage

## Overview

Chuyển Leadpipe từ **pull polling** sang **webhook push**, và dựng bộ đo coverage thật.

<!-- Updated: Validation Session 2 - điều kiện tiên quyết bám org mới -->

**Điều kiện tiên quyết cứng (Phase 3 phải xanh trước):** org free mới đã tạo, pixel mới đã thay
vào site lab, và `GET /v1/data` trả **200 kèm dữ liệu visitor thật**. Pixel nạp 200 **không phải**
tín hiệu đủ — pixel cũ vẫn nạp 200 trong khi org hết hạn. Đăng ký webhook cũng cần org còn hiệu
lực, nên phase này bị chặn cứng sau Phase 3.

Phase này kế thừa `phase-02-wire-candidate-ingest-from-vendor-callbacks.md` của program
`identity-coverage-pixel-fppro_02-08-26` (viết cho Customers.ai) và đổi vendor chính sang
Leadpipe theo bằng chứng đã thu được.

## Requirements

- Functional: identity từ vendor vào Beam dưới dạng `provider_candidate`, gắn đúng visitor.
- Functional: idempotent — cùng một sự kiện giao lại không tạo dòng trùng.
- Security: webhook có xác thực; payload vendor là **dữ liệu không tin cậy**.
- Không được thêm bất kỳ provider nào vào `EMAILABLE_PROVIDERS`.

## Architecture

### Vì sao webhook thay vì tiếp tục pull

Cách pull hiện tại phải **đoán** người nào ứng với visitor nào:

```
GET /v1/data?domain=X  →  50 record/trang  →  lọc local: IP trùng VÀ |Δt| ≤ 30 phút
```

Ba điểm yếu, tất cả biến mất khi dùng webhook:

| | Pull (hiện tại) | Webhook |
|---|---|---|
| Ghép người ↔ visitor | Đoán qua IP + cửa sổ 30 phút | Vendor báo ngay lúc nhận diện |
| Phụ thuộc tên field timestamp | Có — đang đoán 13 tên | Không |
| Phân trang 50 record | Có — site ít traffic bị chìm | Không |
| Độ trễ | Tới 1 giờ (chu kỳ sweep) | Tức thì |

Leadpipe hỗ trợ webhook với hai chế độ trigger: **First Match** (một lần/visitor) và
**Every Update** (mỗi pageview của người đã nhận diện). Chọn **First Match** — Beam chỉ cần
danh tính một lần, Every Update sẽ tạo nhiễu.

### Bài toán khó nhất: gắn identity vào đúng visitor

Webhook nói "người X đã được nhận diện trên domain Y". Beam phải biết X ứng với `visitor_id`
nào của mình. Xếp theo độ tin cậy giảm dần:

```
1. Vendor echo lại một id do Beam cung cấp   ← tốt nhất, cần vendor hỗ trợ custom param
2. Email trùng visitor_emails đã capture      ← deterministic
3. IP + cửa sổ thời gian                      ← chính là cách đoán đang dùng, kém nhất
```

**Phải kiểm tra Leadpipe có cho gắn custom param vào pixel không** (kiểu `custom_args` mà
SendGrid echo lại trong webhook — Beam đã dùng pattern này ở `identity_signals`). Nếu có, gắn
`visitor_id` của Beam vào pixel và bài toán ghép biến mất hoàn toàn. Nếu không, rơi về (2) rồi (3),
và phải ghi rõ giới hạn thay vì giả vờ là deterministic.

Đây là câu hỏi cần trả lời **trước** khi viết code webhook — nó quyết định toàn bộ thiết kế.

### Luồng

```
Leadpipe nhận diện
   → POST /api/v1/webhooks/identity/leadpipe   (xác thực bằng secret)
   → giải mã + sanitize payload
   → gắn vào visitor theo thứ tự tin cậy ở trên
   → qua các quality gate P0: privacy-relay, name_email_consistent
   → _save_identified(provider="leadpipe") → identity_status = provider_candidate
   → KHÔNG vào EMAILABLE_PROVIDERS
```

### Đo coverage thật

Sau khi có đường vào, mới đo được. Chỉ số cần theo dõi, tách bạch:

| Chỉ số | Nghĩa |
|---|---|
| Coverage | % visitor đủ điều kiện có được identity bất kỳ |
| Precision | % identity đó là **đúng người** (cần ground truth) |
| Owned vs paid | tỉ lệ identity đến từ dữ liệu của Beam ($0) |
| Cost per correct identity | tiền / identity **đúng**, không phải / identity |

Chỉ số cuối là chỉ số thật. Số liệu hiện tại: `$0.72` cho 1 identity, mà identity đó sai →
cost per correct identity thực tế là **∞**. Đây là baseline cần vượt qua.

Precision cần ground truth `N >= 30` — **đã hoãn chính thức (session 2)**, không phải điều kiện
đóng phase. Xem KNOWN-GAP ở §Implementation Steps.

## Related Code Files

- Create/Modify: `apps/api/routers/webhooks.py` — handler `identity/{vendor}`
- Modify: `apps/api/services/identity_classification.py` — giữ leadpipe trong
  `PAID_PERSON_GRAPH_PROVIDERS`, **không** thêm vào `EMAILABLE_PROVIDERS`
- Modify: `apps/api/config.py` — secret cho webhook
- Modify: `apps/pixel/src/tracker.js` — gắn custom param nếu vendor hỗ trợ
- Modify: `scripts/identity_resolution_audit.sql` — thêm truy vấn cost-per-correct-identity
- Tests: unit fixture webhook → candidate; idempotency; emailable vẫn False

## Implementation Steps

1. **Trả lời câu hỏi custom param trước tiên.** Đọc doc Leadpipe xem pixel có nhận tham số tuỳ
   biến và webhook có echo lại không. Kết quả quyết định thiết kế bước 3.
2. Đăng ký webhook trên dashboard Leadpipe, chế độ First Match.
3. Viết handler: xác thực secret → sanitize → gắn visitor → qua quality gate → lưu candidate.
4. Idempotency: dùng khoá tự nhiên từ payload vendor; giao lại không tạo dòng trùng.
5. Giữ pull `/v1/data` như đường dự phòng, hoặc gỡ nếu webhook chứng minh đủ. **Không chạy song
   song cả hai mà không dedup** — sẽ tạo identity trùng.
6. Thêm truy vấn cost-per-correct-identity vào audit script.
7. **Smoke 5 session US** — đây là ngưỡng đóng phase.

<!-- Updated: Validation Session 2 - benchmark N>=30 hoãn chính thức, tách thành known-gap -->

**KNOWN-GAP (hoãn chính thức, không phải success criteria):** benchmark precision `N>=30` ground
truth. Chưa có nguồn tester US cam kết → **không đóng được**. Phase này chỉ cam kết chứng minh
**đường ống chạy** (coverage đo được), không cam kết **kết quả đúng** (precision). Mọi identity giữ
`provider_candidate`. Không được suy diễn từ coverage đẹp ra chất lượng tốt — baseline RB2B đã cho
thấy 8 success → 1 identity → và identity đó sai.

## Success Criteria

- [ ] Đã trả lời được: Leadpipe có hỗ trợ custom param echo không (có/không, kèm nguồn)
- [ ] Webhook fixture tạo ra `provider_candidate`, không phải `verified`
- [ ] `is_emailable_identity("leadpipe")` vẫn `False`
- [ ] Payload giao lại 2 lần → chỉ 1 dòng identity
- [ ] Name/email mismatch vẫn bị từ chối qua đường webhook
- [ ] Audit script báo được cost-per-correct-identity
- [ ] Smoke 5 session US có ít nhất 1 candidate xác minh được bằng tay

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| Ghép sai người → gán danh tính nhầm cho visitor | Ưu tiên custom param > email > IP. Nếu chỉ còn IP+time thì ghi rõ là probabilistic và **giữ nguyên** trần confidence, không nâng |
| Payload vendor là dữ liệu không tin cậy | Sanitize như mọi input bên ngoài; không đưa thẳng vào prompt AI (`prompt_safety` đã có sẵn) |
| Chạy song song webhook + pull tạo identity trùng | Bước 5 buộc chọn một, hoặc dedup rõ ràng trước |
| Webhook endpoint bị giả mạo → bơm identity rác | Bắt buộc secret; tenant-scope theo domain; áp cùng quality gate như đường resolver |
| Đo coverage mà không có precision → tưởng tốt lên | Cost-per-**correct**-identity là chỉ số chính, không phải coverage thô. Baseline hiện tại là ∞ |
