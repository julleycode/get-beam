# QA Note — Smoke test dashboard sau khi pull nhánh khác về

- **QA by:** nhantc2 (agent-browser automation, session `beam-dash`)
- **Date:** 07-08-26
- **Branch local:** `dev_nhantc2`
- **URL test:** `http://localhost:3000/dashboard` (frontend local, gọi API thật `https://beam-api.nhantown.com`)
- **Account:** demo@getbeam.fyi (site `beamlab` + `Demo SaaS App`)
- **Coverage:** Overview, Visitors, Agents, Segments, Campaigns, Connectors, Social Accounts,
  Billing, Imported Contacts, Outcomes, Feed, Drafts, Feature Board, Referrals, Costs — 15 trang,
  đăng nhập qua UI thật (không mock), theo dõi console + network trong suốt phiên.

---

## ISSUE-001 — P0: Trang Billing gọi API vòng lặp vô hạn (~30 req/s)

**Severity:** P0 (tốn quota/API cost thật, có thể trigger rate-limit hoặc DoS chính server của mình)

### Triệu chứng

Mở `/dashboard/billing` (hoặc `/dashboard/settings` — route này redirect sang billing), 2 endpoint
sau bị gọi liên tục không dừng, mỗi request đều 200 OK (không phải lỗi retry):

- `GET https://beam-api.nhantown.com/api/v1/api-keys/`
- `GET https://beam-api.nhantown.com/api/v1/billing/status`

### Đo đạc (reproducible 100%)

| Mốc | Số request cộng dồn (api-keys + billing/status) |
|---|---|
| Vừa load xong trang Billing | 2162 |
| +5 giây đứng yên trên trang | 2310 (**+148 request / 5s ≈ 30 req/s**) |
| Rời sang `/dashboard` (Overview) | dừng ngay, đứng yên ở 2552 trong 4s tiếp theo |

→ Vòng lặp bị scope đúng vào lúc component Billing mount, dừng ngay khi unmount — gần như chắc
chắn là bug `useEffect` thiếu/sai dependency array (fetch → set state → re-render → fetch lại) chứ
không phải polling có chủ đích (30 req/s không hợp lý cho polling).

### Vì sao nghiêm trọng

- Tab đứng im trên Billing 1 phút = ~1800 request thật gửi lên `beam-api.nhantown.com`. Nhân với
  nhiều user/tab mở lâu → có thể ăn quota, đội chi phí, hoặc đụng rate-limit chung của backend.
- Đây đúng là loại lỗi "nghiêm trọng" thường bị bỏ sót khi review vì UI vẫn *nhìn* bình thường —
  trang Billing render đúng, không lỗi console, chỉ network tab mới thấy.

### Cách tái hiện

1. Login → vào `/dashboard/billing`
2. Mở DevTools → Network, lọc theo `api-keys` hoặc `billing/status`
3. Thấy request bắn liên tục dù không thao tác gì
4. Chuyển sang trang khác → request dừng ngay lập tức

### Đề xuất

Kiểm tra component Billing (`apps/web/src/app/dashboard/billing/page.tsx` hoặc hook nó dùng) — rất
có thể `useEffect(() => { fetchApiKeys(); fetchBillingStatus(); }, [someObjectOrFunctionRef])` với
dependency là 1 object/function được tạo mới mỗi render thay vì giá trị ổn định.

---

## ISSUE-002 — P2: Trang API Costs trắng trơn khi API trả 403, không có error/empty state

**Severity:** P2 (không mất dữ liệu, nhưng user không biết vì sao trang trống)

### Triệu chứng

`/dashboard/costs` (site `beamlab`) — filter bar "Last 30 days / beamlab" render đúng, nhưng toàn
bộ phần nội dung bên dưới **trắng trơn**, không có chart, không "No data", không thông báo lỗi.

### Nguyên nhân (network)

```
GET https://beam-api.nhantown.com/api/v1/costs/site_92e8f1f8a71c/summary?days=30 → 403 (x2, reproducible)
```

Frontend không xử lý case lỗi (403) — chỉ im lặng không render gì, thay vì show error message hoặc
"upgrade to see this" nếu đây là tính năng giới hạn theo plan.

### Đề xuất

- Nếu 403 là **đúng** (API Costs là tính năng trả phí, demo account đang Free plan) → cần thêm
  paywall/upsell UI thay vì trắng trang.
- Nếu 403 là **sai** (site `beamlab` thuộc chính account đang login, lẽ ra phải xem được cost của
  site mình sở hữu) → đây là bug authorization ở backend, cần check case owner xem cost site của
  chính mình.
- Screenshot: `screenshots/10-costs.png`

---

## Các phần đã test OK (không thấy lỗi)

- Login flow (email/password) → redirect `/dashboard` sạch, không lỗi console
- Overview: site cards, quick actions, "Beam Loop" render đúng
- **Visitors: không còn bug 500 `confidence_score`** (đã fix ở commit `c92cc62`) — load, filter,
  cột Intent/Identity/Enrichment hiển thị đúng
- Agents, Segments, Campaigns: empty state render sạch, không lỗi
- Connectors (tab Ad Audiences/CRM/Exclude List): render đúng, không lỗi
- Social Accounts: 5 platform connect buttons + LinkedIn outreach section OK
- Imported Contacts, Outcomes, Feed, Drafts, Feature Board, Referrals: load sạch, không lỗi console
- `/dashboard/exports` redirect sang `/dashboard/connectors` — có vẻ là redirect có chủ đích
  (Export segment giờ nằm trong tab Connectors), không phải lỗi — không đào sâu thêm.
- `/dashboard/settings` redirect sang `/dashboard/billing` — tương tự, không phải lỗi rõ ràng.

## Ghi chú môi trường (không phải bug code)

Trong lúc chuẩn bị login demo để test, phát hiện API server local (`:8000`) đang chạy bằng **Python
Store toàn cục** thay vì `.venv` của project (đúng cái bẫy đã ghi trong `scripts/dev-local.ps1`) —
đã restart lại bằng `.venv\Scripts\python.exe` cho đúng. Việc này **không liên quan** tới 2 bug
trên vì dashboard thật sự gọi `beam-api.nhantown.com` (remote), không phải `localhost:8000`.

## Screenshots

`QA/nhantc2/07-08-26/screenshots/01-overview.png` → `11-settings.png`

## TL;DR

2 bug thật tìm được: (1) **P0** — trang Billing gọi `api-keys`/`billing/status` lặp vô hạn ~30
req/s, dừng khi rời trang, nghi do `useEffect` deps sai; (2) **P2** — trang Costs trắng trơn khi
API trả 403, thiếu error/empty state. 15 trang còn lại test sạch, không lỗi console/network. Bug
`GET /visitors 500` cũ đã confirm fixed.

## Câu hỏi chưa giải quyết

- ISSUE-002: 403 trên `/costs` là do plan-gating (đúng thiết kế, thiếu UI) hay authorization bug
  thật (site thuộc chính user)? Cần người biết rõ business logic của costs feature xác nhận.
