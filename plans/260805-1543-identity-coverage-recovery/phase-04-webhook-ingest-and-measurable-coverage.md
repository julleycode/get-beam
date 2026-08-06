---
phase: 4
title: "Webhook ingest and measurable coverage"
status: code-complete
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

## Implementation Detail — chốt 06-08-26 trước khi cook bước 3–6

<!-- Added 06-08-26: phase plan gốc dừng ở mức ý định; mục này là mức file/dòng. -->

**Nguyên tắc chi phối:** không viết lại quality gate. Đường webhook đi qua đúng
`IdentityResolver._save_identified()` mà đường pull đang dùng, nên mọi gate P0 (validate email →
`name_email_consistent` cho paid graph → dedup/merge theo email → `identity_status_for_provider`
⇒ `provider_candidate`) áp dụng nguyên vẹn, không có bản sao thứ hai để trôi lệch.

### Files

| File | Việc | Bước |
|---|---|---|
| `apps/api/config.py` | `leadpipe_webhook_secret: str = ""`, `leadpipe_pull_enabled: bool = True` | 3, 5 |
| `apps/api/services/leadpipe_webhook.py` **(mới)** | resolve site → gắn visitor 3 tầng → gọi `_save_identified` | 3, 4 |
| `apps/api/routers/webhooks.py` | `POST /webhooks/identity/leadpipe`, auth `?token=` | 3 |
| `apps/api/services/identity_resolver.py:706` | thêm `and settings.leadpipe_pull_enabled` vào key gate | 5 |
| `apps/pixel/src/tracker.js` | inject `globalParams.beam_visitor_id`, **chỉ trong nhánh leadpipe** | tier 1 |
| `scripts/identity_resolution_audit.sql` | Q mới: cost per identity chia theo bounce/engagement | 6 |
| `tests/unit/test_leadpipe_webhook.py` **(mới)** | 8 ca — xem §Test | 3–6 |

### Ghép site — dùng `Site.leadpipe_pixel_id`, không so chuỗi domain

Payload có `pixel_id` (và/hoặc `domain`). Tra `Site.leadpipe_pixel_id == pixel_id` trước; không có
thì mới rơi về so hostname của `Site.url`. Pixel id là khoá 1-1 do chính Beam cấp phát ở Phase 3 →
tenant-scope chặt. Không tra được site ⇒ bỏ qua, **không** đoán, **không** ghi. Đây là chốt chặn
chống bơm identity chéo tenant.

### Ghép visitor — waterfall 3 tầng, ghi lại tầng nào trúng

| Tầng | Khoá | Ghi chú |
|---|---|---|
| 1 | `beam_visitor_id` trong payload (kể cả lồng trong `static_params`) | deterministic — chỉ có dữ liệu nếu A4 xác nhận server echo |
| 2 | email → `VisitorEmail.email_bidx == email_hash(email)`, scope theo `site_id` | deterministic; dùng blind index đã có sẵn |
| 3 | `ip_address` bằng nhau + `last_seen` trong `_IDENTITY_MATCH_WINDOW` (30 phút) | probabilistic — **cap `confidence_score` ở `_WEAK_MATCH_MAX_CONFIDENCE` (0.6)** |

Tầng 1 rỗng thì tự rơi xuống tầng 2 — hành vi degrade đã thiết kế, không phải nhánh lỗi.

**Privacy-relay chỉ chặn tầng 3.** `is_privacy_relay_ip` là gate đúng khi danh tính suy ra TỪ IP.
Tầng 1/2 không đọc IP nên chặn theo relay ở đó là chặn nhầm. Tầng 3 gặp relay IP ⇒ bỏ, không hạ
xuống đoán bừa.

### Idempotency — không thêm bảng, không thêm migration

`uq_identified_site_visitor` UNIQUE `(site_id, visitor_id)` đã tồn tại, và `_save_identified` đã bắt
`IntegrityError` rồi trả về dòng có sẵn. Giao lại lần 2 ⇒ vẫn 1 dòng. Khoá tự nhiên chính là
`(site_id, visitor_id)` sau khi ghép — không cần khoá dedup riêng từ payload vendor, không cần
migration (đúng ràng buộc "không thêm migration cho provider có thể bị bỏ").

### Bước 5 — pull và webhook sống chung

Thêm `leadpipe_pull_enabled` (default `True`), gắn vào `identity_resolver.py:706`: key `None` ⇒
provider bị bỏ qua sạch sẽ qua đúng đường đã có cho key thiếu. Chạy song song **không** đẻ dòng
trùng (unique constraint ở trên), chỉ tốn một lượt gọi API thừa. Tắt pull = đổi env var, không cần
deploy code — đảo ngược được khi webhook bị Leadpipe auto-disable.

### Bước 6 — audit query

"Correct" chưa đo được (ground truth `N>=30` đã hoãn), nhưng "**sai**" thì đo được ngay: email
hard-bounce là bằng chứng identity sai, và `suppression_list` đã ghi `reason='sendgrid_bounce'`.
Query mới chia mẫu số: tổng identity / chưa-bounce / có-engagement (`identity_signals` open+click),
kèm cost tương ứng. Đây là cận trên của precision, ghi rõ trong comment là **proxy phủ định**,
không phải precision thật.

### Test (bước 3–6)

1. webhook fixture → `identity_status == provider_candidate` (KHÔNG `verified`)
2. `is_emailable_identity("leadpipe")` vẫn `False`
3. giao lại payload 2 lần → đúng 1 dòng `IdentifiedVisitor`
4. name/email mismatch → bị từ chối qua đường webhook (gate paid-graph)
5. thứ tự tầng: có marker thì không dùng email; có email thì không dùng IP
6. tầng 3 → `confidence_score <= 0.6`
7. token sai / chưa cấu hình secret → 403
8. pixel_id lạ → không ghi gì (chống chéo tenant)

Mọi test cấp Redis giả **riêng từng test** — không bao giờ `IdentityResolver(db, redis_client=None)`
(bẫy #7, phase-05).

## Execution — bước 3–6 cook xong 06-08-26

Bước 1 (probe marker) và bước 2 (đăng ký webhook) là thao tác tay, chưa làm. Bước 7 (smoke 5
session US) chờ bước 2 + traffic thật.

### Đã ghi

| File | Thay đổi |
|---|---|
| `apps/api/services/leadpipe_webhook.py` | mới — resolve site → waterfall 3 tầng → `_save_identified` |
| `apps/api/routers/webhooks.py` | `POST /webhooks/identity/leadpipe`, auth `?token=` |
| `apps/api/config.py` | `leadpipe_webhook_secret`, `leadpipe_pull_enabled=True` |
| `apps/api/services/identity_resolver.py` | 2 chỗ — cổng pull ở dòng ~706; sửa bug ở `_save_identified` (xem dưới) |
| `apps/pixel/src/tracker.js` | inject `beam_visitor_id`, chỉ trong nhánh leadpipe |
| `scripts/identity_resolution_audit.sql` | Q10 |
| `tests/unit/test_leadpipe_webhook.py` | mới, 31 ca |
| `tests/integration/test_leadpipe_webhook_persistence.py` | mới, 5 ca |

### Kết quả test

- unit mới 40/40; unit toàn bộ **1662 pass, 2 skip**
- integration mới 7/7; integration lọc `identity|resolution|visitor|beam` **122/122**
- Q10 chạy thật trên Postgres với dữ liệu giả: `saved=3 / not_disproven=2 / corroborated=1`,
  `$4.00` chi phí ⇒ `cost_per_saved $1.33` vs `cost_per_corroborated $4.00`. Đúng mục đích —
  con số ngây thơ đẹp gấp 3 lần con số trung thực.
- `node --check apps/pixel/src/tracker.js` sạch

### Bug có sẵn, tìm ra khi test — đã sửa

`_save_identified` bắt `IntegrityError` rồi gọi `db.rollback()`, sau đó đọc `visitor.visitor_id`
để ghi log. `rollback()` **luôn** expire mọi instance trong session (cờ `expire_on_commit=False`
chỉ chi phối commit, không chi phối rollback), nên dòng log đó kích hoạt lazy-load đồng bộ và ném
`MissingGreenlet` — **toàn bộ nhánh phục hồi xung đột chưa bao giờ chạy được**, kể cả trên đường
pull cũ. Triệu chứng che mất nguyên nhân: lỗi hiện ra là MissingGreenlet chứ không phải xung đột
khoá trùng.

Sửa tối thiểu: đọc `visitor_id`/`site_id` ra biến cục bộ **trước** khi thử commit. Không đổi hành
vi đường thành công. Cùng lỗi đó lặp lại một lần nữa trong `leadpipe_webhook.py` (đọc `site.site_id`
sau khi `_save_identified` rollback) — sửa cùng kiểu.

Đường pull hiếm khi chạm nhánh này (chỉ khi hai sweep đua nhau); đường webhook thì chạm **mọi lần
Leadpipe giao lại**, nên bug tồn tại lâu mà không ai thấy.

### Code review — 3 lỗ hổng tìm ra, đã sửa hết

| # | Lỗ hổng | Sửa |
|---|---|---|
| 1 | **Payload `email` không phải chuỗi ⇒ sập 500.** `{"email": {...}}` / `[...]` / số / bool đều truthy nên lọt qua kiểm rỗng, rồi `.strip()` ném `AttributeError`. Không ai bắt — router không có try/except, app không có handler chung | thêm `email` vào `_MAX_LEN` để `_clean` xử lý (không phải chuỗi ⇒ `None`); parse `person` **một lần** ở `ingest_identification` rồi truyền xuống `_attach_visitor` (bỏ luôn chỗ parse trùng) |
| 2 | **Phong bì `{"data": [...]}` bị nuốt cả lô.** Router chỉ mở gói mảng ở cấp cao nhất; feed REST của vendor lại dùng `data` là mảng. Sai hình dạng ⇒ mất sạch lô, **im lặng**, vẫn trả 200 | router nhận cả 3 hình dạng: bản ghi trần / mảng / `{"data": [...]}` |
| 3 | **`domain: "%"` gây quét toàn bảng.** `ILIKE '%%%'` khớp mọi site. Không rò dữ liệu (vòng so hostname chính xác chặn lại — đã truy ngược xác nhận) nhưng nạp mọi site vào bộ nhớ mỗi request | escape `%` `_` `\` trước khi ghép pattern, kèm `escape="\\"` |

Lỗ #1 nghiêm trọng nhất vì nó **chạm mọi payload thật hôm nay**: tầng 1 đang rỗng (known-gap dưới)
nên mọi bản ghi đều rơi xuống đúng dòng sập đó. Mà endpoint tự hứa "luôn 2xx" chính là để Leadpipe
không tự tắt webhook — lỗi này tái tạo đúng cái nó phòng.

Lỗ #4 review nêu là **thiếu test**, không phải lỗi code: ô "name/email mismatch bị từ chối" được
tick nhưng chỉ chứng minh qua mock. Đã thêm 2 ca integration chạy qua `_save_identified` **thật**
(1 ca mismatch bị từ chối + 1 ca đối chứng name/email khớp thì vẫn lưu, để chứng minh gate không
từ chối tất cả).

### KNOWN-GAP — `tracker.min.js` chưa build lại (user quyết 06-08-26)

API phục vụ `apps/pixel/src/tracker.min.js`, chỉ dùng `tracker.js` khi thiếu bản nén
([main.py:579](apps/api/main.py#L579)). Bản nén đang commit build từ `b37656a` (26-07), trong khi
source đã đổi ở `0ff8c9a` (02-08) — xác minh bằng cách stash thay đổi mới, build lại từ source ở
HEAD, diff ra khác.

Hệ quả: **marker `beam_visitor_id` chưa chạy trên site nào**, nên tầng 1 của waterfall tạm thời
luôn rỗng và tự rơi xuống tầng 2. Đây là hành vi đã thiết kế, không phải hỏng.

Không build lại ở phase này vì làm vậy sẽ đẩy luôn thay đổi pixel ngày 02-08 lên site khách thật —
thay đổi của người khác, chưa rõ bị bỏ quên hay cố ý giữ. Việc phải làm sau: xem lại diff 02-08,
rồi mới `npm run build` trong `apps/pixel` và kiểm ngân sách <5KB gzip.

## Success Criteria

- [x] Phía client trả lời xong: SDK spread-merge, không whitelist key (đọc SDK thật 06-08-26).
      Phía server (có echo lại trong webhook không) vẫn chờ probe tay A4
- [x] Webhook fixture tạo ra `provider_candidate`, không phải `verified`
- [x] `is_emailable_identity("leadpipe")` vẫn `False`
- [x] Payload giao lại 2 lần → chỉ 1 dòng identity (chứng minh trên Postgres thật, bằng chính
      unique index — không có khoá dedup riêng)
- [x] Name/email mismatch vẫn bị từ chối qua đường webhook
- [x] Audit script báo được cost-per-correct-identity — Q10, dạng proxy phủ định
- [ ] Smoke 5 session US có ít nhất 1 candidate xác minh được bằng tay — chờ A5 + traffic thật

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| Ghép sai người → gán danh tính nhầm cho visitor | Ưu tiên custom param > email > IP. Nếu chỉ còn IP+time thì ghi rõ là probabilistic và **giữ nguyên** trần confidence, không nâng |
| Payload vendor là dữ liệu không tin cậy | Sanitize như mọi input bên ngoài; không đưa thẳng vào prompt AI (`prompt_safety` đã có sẵn) |
| Chạy song song webhook + pull tạo identity trùng | Bước 5 buộc chọn một, hoặc dedup rõ ràng trước |
| Webhook endpoint bị giả mạo → bơm identity rác | Bắt buộc secret; tenant-scope theo domain; áp cùng quality gate như đường resolver |
| Đo coverage mà không có precision → tưởng tốt lên | Cost-per-**correct**-identity là chỉ số chính, không phải coverage thô. Baseline hiện tại là ∞ |
