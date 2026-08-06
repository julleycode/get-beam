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

<!-- Updated: 06-08-26 — điều kiện tiên quyết cũ SAI, thay bằng điều kiện thật. -->

**Điều kiện tiên quyết — đã ĐẠT 06-08-26.** Bản trước ghi "phải có `GET /v1/data` trả dữ liệu
visitor thật". Sai: feed rỗng trên một đường ống đúng là trạng thái hợp lệ, và số bản ghi trong
feed chính là **chỉ số coverage mà phase NÀY sinh ra để đo** — lấy nó làm điều kiện vào phase là
lập luận vòng tròn.

Điều kiện thật chỉ có hai, và cả hai đã đạt:

| Điều kiện | Vì sao cần | Trạng thái 06-08-26 |
|---|---|---|
| Org còn hiệu lực | Đăng ký webhook làm **trên dashboard**, org hết hạn thì không vào được | ✅ `To's workspace`, `status: trial`, `healthy: true` |
| Pixel active cho domain | Không có pixel thì không có sự kiện nào để webhook bắn | ✅ `3ead3e50-f6c0-…`, `status: active` |

Pixel nạp HTTP 200 vẫn **không phải** tín hiệu đủ (pixel cũ nạp 200 trong khi org hết hạn) — dùng
`GET /v1/data/account` + `GET /v1/data/pixels` để kiểm, không dùng URL pixel.

**Không có API đăng ký webhook.** Toàn bộ 40 endpoint trong `llms.txt` không có endpoint webhook
nào; `guides/set-up-webhooks` chỉ mô tả cấu hình trên dashboard (URL, segment, pixel, trigger,
status; auto-disable khi lỗi liên tiếp). Nên bước 2 là **thao tác tay**, không code được.

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

<!-- Updated: 06-08-26 — câu hỏi custom param ĐÃ trả lời được một nửa, bằng cách đọc SDK thật. -->

**✅ Phía client: CÓ.** Đọc SDK thật (`cdn.pixel.leadpipe.com/pixels/50eb9810-…/p.js`, 06-08-26):

```js
// SDK đọc <script type="application/json" id="pixelsdk-config-<pid>-config">
preInitialize: globalParams = {...globalParams, ...scriptAttrs.globalParams}   // spread-merge
// rồi khi gửi:
const r = {...t.event_data};
if (Object.keys(e).length) r.static_params = e;          // e = globalParams đã merge
fetch(endpoint, {body: JSON.stringify({...t, event_data: r, pixel_id, organization_id})})
// endpoint: https://api.sitelytics.tech/pixel/core/api/send-event
```

Spread-merge, **không whitelist key** → key tuỳ ý (vd `beam_visitor_id`) đi tới server Leadpipe,
mang trong `event_data.static_params`.

**❓ Phía server: CHƯA biết** — Leadpipe có echo `static_params` lại trong webhook payload không
thì SDK không trả lời được. Cách kiểm rẻ nhất: gắn một marker vào `globalParams` trên site lab,
tạo một lượt truy cập, rồi đọc `/v1/data` xem marker có xuất hiện. Làm **trước** bước 3.

Nếu server có echo → gắn `visitor_id` của Beam, bài toán ghép biến mất. Nếu không → rơi về (2) rồi
(3), và phải ghi rõ giới hạn thay vì giả vờ deterministic.

**⚠️ Phát hiện kèm theo, cần cân nhắc trước khi bật rộng:** SDK còn có `sendHemEnrichment()` (gửi
email đã hash sha1/md5/sha256 tới `/hem/enrichment`) và `inject444Script()` — nó **nạp thêm script
bên thứ ba nữa**. Nghĩa là nhúng pixel Leadpipe qua `data-stack` sẽ kéo theo một chuỗi vendor mà
Beam không kiểm soát. Ảnh hưởng trực tiếp tới `consent_mode` và tuyên bố quyền riêng tư — phải
xử lý trước khi bật cho site khách thật, không phải việc của riêng phase này nhưng không được quên.

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
