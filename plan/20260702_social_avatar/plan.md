# Kế hoạch: Ảnh đại diện thật từ mạng xã hội (Social Avatar)

**Ngày:** 2026-07-02
**Thư mục:** `plan/20260702_social_avatar/`
**Loại:** Tính năng nhỏ (SIMPLE), 5 phase
**Người viết plan:** vc-plan-agent (chỉ viết plan, KHÔNG code)

---

## 1. Mục tiêu (nói đơn giản)

Ở trang **chi tiết một visitor** (Visitor Detail), hiện tại chỗ ảnh đại diện chỉ là **ô vuông chữ cái viết tắt** (ví dụ "VK"). Ta muốn:

- Nếu đã tìm được **ảnh mạng xã hội thật** của người đó → hiện **ảnh thật** đó.
- Nếu **không có ảnh**, hoặc ảnh **bị lỗi không tải được** → **quay lại** hiện ô chữ cái viết tắt như cũ.

Nguồn ảnh (theo quyết định đã chốt):
1. **Twitter/X** (ưu tiên số 1)
2. **Ảnh từ OSINT scan** (ưu tiên số 2, dự phòng)
3. **LinkedIn KHÔNG dùng** — Proxycurl đã chết (bị LinkedIn kiện), không lấy được ảnh LinkedIn nữa. Đừng đụng vào LinkedIn.

Cách làm: thêm **1 cột mới trong database** tên `avatar_url`, ghi URL ảnh vào lúc enrichment, đưa ra qua API, rồi frontend hiển thị.

---

## 2. Bối cảnh kỹ thuật đã kiểm tra (file:dòng thật)

| Vị trí | File | Dòng | Ghi chú |
|---|---|---|---|
| Ô avatar (frontend) | `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` | 74-101 | Component `Avatar` — hiện `label` (chữ viết tắt) hoặc icon. Chưa có `<img>`. |
| Hàm chữ viết tắt | cùng file | 33-42 | `initials(name, email)` — giữ nguyên làm fallback. |
| Nơi render Avatar (header) | cùng file | 448-452 | `<Avatar name={...} email={...} variant={...} />` — sẽ truyền thêm `src`. |
| Type frontend | `apps/web/src/lib/api-types.ts` | 202-225 | interface `VisitorDetail` — thêm `avatar_url?: string \| null`. |
| Schema API (chi tiết) | `apps/api/schemas/visitors.py` | 45-68 | `VisitorDetailOut` — thêm `avatar_url`. |
| Schema API (list) | cùng file | 7-42 | `VisitorOut` — **KHÔNG** thêm ở MVP (xem mục 8). |
| Endpoint chi tiết | `apps/api/routers/visitors.py` | 458-546 | `get_visitor_detail`; block map enrichment ở 522-533. |
| Model DB | `apps/api/models/enrichment.py` | 12-60 | `EnrichmentProfile` — thêm cột `avatar_url`. |
| Enrich cascade | `apps/api/services/enricher.py` | 136-239 | `enrich_tier1`; twitter stage ở 210-220. |
| Apply twitter | cùng file | 92-100 | `_apply_twitter(profile, twitter_data)` — thêm ghi `avatar_url`. |
| Enrich twitter (HTTP) | cùng file | 476-564 | `_enrich_twitter` — thêm lấy `profile_image_url`. |
| Upsert profile | cùng file | 308-332 | `_upsert_profile` — không cần đổi (avatar không từ PDL). |
| Completeness fields | cùng file | 60-65 | `ENRICHMENT_FIELDS` — **KHÔNG** thêm avatar (nó không phải tín hiệu chất lượng, tránh làm lệch điểm). |
| Twitter profile_image_url | `apps/api/services/platforms/twitter.py` | 152, 171, 212, 288 | X API v2 field `profile_image_url` — URL có đuôi `_normal` (48px). |
| OSINT avatar | `apps/api/services/osint_scanner.py` | 218 | `extra` giữ key `"avatar"`. |
| Paid OSINT avatar | `apps/api/services/paid_osint.py` | 106-111 | `extra` giữ key `"profile_pic"`, `"picture"`, `"avatar"`. |
| Migration head | `apps/api/migrations/versions/` | — | **CÓ 4 HEAD** — xem mục 3 (quan trọng!). |
| next.config | `apps/web/next.config.mjs` | 1-18 | **Không có** block `images` → dùng `<Image>` của Next sẽ chặn host ngoài. Repo đã ưu tiên `<img>` thường (xem `apps/web/src/app/blog/[slug]/page.tsx:124`). → **Dùng `<img>` thường**. |
| Test twitter | `tests/unit/test_twitter_fallback.py` | toàn bộ | Mẫu để viết test enricher (mock httpx bằng `_SeqClient`). |

---

## 3. ⚠️ Cảnh báo quan trọng: database đang có 4 "head" migration

Khi kiểm tra, repo có **4 head migration cùng lúc** (chưa gộp):

- `c9d2f7b4e1a6` (add consent_mode) — memory nói **CHƯA commit/deploy**, nhưng file **đã tracked** trong git.
- `d5a2b7c1e9f3` (add suppression_list)
- `e7b4c2f9a1d8` (add pii_ciphertext_columns)
- `f1a9c4d7e2b8` (add x_handle_to_waitlist)

**Vì sao nguy hiểm:** Dockerfile chạy `alembic upgrade head` khi deploy. Khi có **nhiều head**, lệnh `upgrade head` sẽ **BÁO LỖI "Multiple head revisions"** và deploy fail. Nghĩa là database này **đang có nợ kỹ thuật** cần gộp head trước.

**Bắt buộc làm trước khi tạo migration mới:** người execute PHẢI chạy `alembic heads` để xác nhận head thật ở thời điểm đó (danh sách trên có thể đã đổi). Có 2 lựa chọn:

- **Lựa chọn A (khuyến nghị, an toàn):** Tạo **1 migration merge** gộp cả 4 head thành 1, rồi migration `avatar_url` mới nối tiếp sau merge đó. Kết quả: chỉ còn 1 head, deploy sạch.
- **Lựa chọn B (nếu execute xác nhận 3 head kia thực ra đã stamped/áp dụng ở prod và chỉ 1 head là "thật"):** nối `down_revision` của migration mới vào đúng head thật đó.

> Ghi chú cho người execute: KHÔNG đoán mò `down_revision`. Chạy `cd apps/api && alembic heads` (hoặc `alembic history`) để lấy sự thật tại thời điểm execute. Plan này ghi head *tại lúc viết plan* để tham chiếu, không phải để copy nguyên.

Chi tiết ở `phase-01`.

---

## 4. Các phase

- **phase-01** — DB: thêm cột `avatar_url` + migration (gồm xử lý multi-head)
- **phase-02** — Enrichment: bắt URL ảnh từ Twitter (+ helper lấy từ OSINT)
- **phase-03** — API: đưa `avatar_url` ra ngoài qua endpoint chi tiết
- **phase-04** — Frontend: hiện `<img>` + fallback về chữ viết tắt khi lỗi
- **phase-05** — Test: đảm bảo không vỡ, chứng minh chạy đúng

Làm **theo thứ tự** (backend trước, frontend sau). Mỗi phase test xong mới sang phase kế.

---

## 5. Touchpoints / Blast radius (đụng vào những gì)

**File sửa (6):**
1. `apps/api/models/enrichment.py` — +1 cột
2. `apps/api/migrations/versions/<new>_add_avatar_url.py` — file MỚI (+ có thể 1 file merge MỚI)
3. `apps/api/services/enricher.py` — `_apply_twitter`, `_enrich_twitter`, + helper `_avatar_from_social_context`, gọi trong `enrich_tier1`
4. `apps/api/schemas/visitors.py` — +1 field ở `VisitorDetailOut`
5. `apps/api/routers/visitors.py` — map thêm 1 field trong block enrichment
6. `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` — component `Avatar`
7. `apps/web/src/lib/api-types.ts` — +1 field type

**File test (thêm/sửa):**
- `tests/unit/test_twitter_fallback.py` hoặc file mới `tests/unit/test_avatar_enrich.py`
- (tuỳ chọn) `apps/web/e2e/visitors.spec.ts`

**Blast radius (nhỏ, an toàn):**
- Cột mới **nullable** → không ảnh hưởng dòng cũ, không ảnh hưởng query hiện có.
- `_apply_twitter` chỉ **thêm ghi**, không đổi logic cũ (giữ nguyên quy tắc "không ghi đè bằng null").
- API chỉ **thêm 1 field optional** → không phá client cũ.
- Frontend: nếu `avatar_url` không có → **hành vi y hệt hiện tại** (chữ viết tắt).
- **Rủi ro cao nhất KHÔNG phải code mà là migration multi-head** (mục 3).

---

## 6. Ưu / Nhược điểm & Rủi ro (nói thật)

**Ưu điểm:**
- Trang profile trông "thật người" hơn, thuyết phục hơn khi demo/bán hàng.
- Làm rất nhỏ, blast radius thấp, dễ revert (chỉ cần bỏ hiện `<img>`).
- Dùng dữ liệu đã có sẵn (Twitter enrichment + OSINT) — không tốn thêm gọi API.

**Nhược điểm / Rủi ro (thẳng thắn):**
1. **Hotlink CDN Twitter (`pbs.twimg.com`):** ta nhúng thẳng link ảnh của Twitter, không tự host. Twitter **có thể đổi/xoá/hết hạn URL** → ảnh chết. Đã có fallback về chữ viết tắt nên **không vỡ trang**, chỉ là mất ảnh. Chấp nhận được cho MVP.
2. **Ảnh có thể trả 403/hết hạn** theo thời gian (URL cũ lưu trong DB). Fallback lo phần này.
3. **Độ phủ thấp:** đa số visitor **không có Twitter** (theo memory: phần lớn không match được, VN/residential ~0%). Nên nhiều người vẫn hiện chữ viết tắt. Đây là **giới hạn thực tế**, không phải bug.
4. **Phải deploy migration:** vì Dockerfile auto `alembic upgrade head`, mà đang **multi-head** → nếu không gộp head trước thì **deploy fail**. Đây là rủi ro lớn nhất, phải xử ở phase-01.
5. **Railway credit gần hết (theo memory):** hạn chế thử deploy nhiều lần. Test kỹ ở local trước.
6. **Riêng tư/pháp lý:** hiện ảnh công khai của người thật. Đây là ảnh **public profile** (Twitter/OSINT) nên rủi ro thấp, nhưng ghi nhận: Beam đã tôn trọng GPC/consent/suppression ở tầng resolve.
7. **Không tự tải/lưu ảnh (no proxy/caching):** đơn giản nhưng phụ thuộc CDN bên thứ 3. Nếu sau này muốn bền, có thể tự tải ảnh về lưu (ngoài phạm vi MVP).

---

## 7. Backfill dữ liệu cũ (tuỳ chọn — khuyến nghị BỎ QUA ở MVP)

Các visitor **đã enrich trước đây** sẽ **chưa có** `avatar_url` cho tới khi được **re-enrich**. Nghĩa là ban đầu chỉ visitor enrich MỚI mới có ảnh.

- **Có nên viết script backfill không?** Cho MVP: **không cần**. Số visitor có Twitter vốn đã ít, và re-enrich họ sẽ tốn thêm gọi API (tốn tiền/credit). Cứ để tự nhiên: lần enrich kế họ sẽ có ảnh.
- Nếu về sau muốn: viết script quét `enrichment_profiles` có `twitter_handle` mà thiếu `avatar_url`, gọi lại `_enrich_twitter` (dùng cache 7 ngày nên rẻ). Ghi rõ đây là việc tách riêng, không nằm trong plan này.

---

## 8. Có nên thêm `avatar_url` vào list schema (`VisitorOut`) không?

**Khuyến nghị MVP: CHỈ thêm vào `VisitorDetailOut` (trang chi tiết).**

- Lý do: `VisitorOut` (list) hiện **không** join `EnrichmentProfile` cho từng dòng theo cách lấy avatar — thêm vào list cần thay đổi query list (join thêm) → blast radius lớn hơn, không đáng cho MVP.
- Ghi chú tương lai: nếu muốn hiện avatar ở **danh sách visitor**, ở bước đó mới thêm `avatar_url` vào `VisitorOut` và cập nhật query list để lấy kèm. Để dành.

---

## 9. Checklist nghiệm thu (bằng chứng chạy đúng)

Chạy tất cả ở **local** (docker-compose stack, KHÔNG dùng prod DB — theo memory "local-dev-prod-wiring"):

1. **Migration lên/xuống được:**
   - `cd apps/api && alembic heads` → chỉ còn **1 head** sau khi gộp.
   - `alembic upgrade head` chạy không lỗi; cột `avatar_url` xuất hiện trong bảng `enrichment_profiles`.
   - `alembic downgrade -1` bỏ được cột (kiểm tra `downgrade()` đúng).
2. **Enrichment ghi được avatar (mock mode):**
   - Bật `MOCK_EXTERNAL_APIS=true`, chạy test enricher: `_enrich_twitter` trả về có key ảnh; `_apply_twitter` set `profile.avatar_url`.
   - Kiểm tra URL Twitter đã **đổi `_normal.` → `_400x400.`** (ảnh nét).
3. **API trả field:**
   - Gọi `GET /api/v1/visitors/{site_id}/{visitor_id}` cho 1 visitor có avatar → JSON có `"avatar_url": "https://..."`.
   - Visitor không có avatar → `"avatar_url": null` (không lỗi).
4. **Frontend hiện `<img>`:**
   - Mở trang chi tiết visitor có avatar → thấy **ảnh thật** thay ô chữ viết tắt.
   - Visitor không có avatar → thấy **chữ viết tắt** như cũ.
5. **Fallback khi ảnh lỗi:**
   - Sửa tạm `avatar_url` thành URL rác (hoặc chặn network) → `<img onError>` chuyển về **chữ viết tắt**, KHÔNG hiện icon ảnh vỡ.
6. **Không vỡ cái cũ:**
   - `pytest tests/unit -q` xanh (đặc biệt `test_twitter_fallback.py`).
   - `cd apps/web && npx tsc --noEmit` không lỗi type (vì Vercel build sẽ fail nếu lint/type lỗi — theo memory).
   - `npm run lint` (web) sạch.

---

## 10. Ghi chú resume / handoff (cho người tiếp tục sau)

- **Trạng thái:** PLAN xong, CHƯA code.
- **Bước kế:** chờ user duyệt → "ENTER EXECUTE MODE" với đúng file plan này.
- **Việc RỦI RO NHẤT (làm trước):** `phase-01` — xử lý multi-head migration. Nếu không, deploy sẽ fail.
- **Nhớ:** chỉ thêm field ở `VisitorDetailOut` (không đụng list). Không thêm avatar vào `ENRICHMENT_FIELDS`. Dùng `<img>` thường (không `next/image`). Không đụng LinkedIn.
- **Local trước, prod sau** (Railway credit gần hết). Test ở docker-compose, không dùng prod Supabase.
- **Nguồn ưu tiên:** Twitter trước, OSINT sau. Frontend fallback: img lỗi/không có → chữ viết tắt.

---

Xem các file phase để biết chi tiết từng bước.
