# IP-Org (IP → Company) — Bật & chạy ở LOCAL

Last updated: 2026-08-10

**BLUF:** IP-org in-house (tự host dữ liệu IP → công ty, không phụ thuộc provider trả phí) đã code xong
Phase 1–3 + quality pack; schema đã live trên prod nhưng **tất cả flag mặc định OFF**. Tài liệu này
ghi lại cách bật và chạy toàn bộ chuỗi ở **máy local** (`localhost:5433`) — đã làm được gì, còn thiếu gì,
và tuyệt đối **cấm gì trên prod**.

Dành cho người đọc sau: chỉ cần copy-paste theo checklist là dựng lại được môi trường local.

- Runbook prod (thao tác riêng, không nằm trong tài liệu này):
  `process/features/visitors-identity/active/ip-org-database_07-08-26/ip-org-prod-enable_RUNBOOK_07-08-26.md`
- Ghi chú tiếng Việt cạnh runbook:
  `process/features/visitors-identity/active/ip-org-database_07-08-26/LOCAL_ENABLE_NOTES_vi.md`
- Context tổng: `process/context/all-context.md` (mục `ip-org-database_07-08-26`).

---

## 1. IP-Org là gì (1 phút)

Beam tự dựng dữ liệu ánh xạ **IP → tổ chức/công ty** thay vì phải mua từ provider. Nguồn dữ liệu:

| Nguồn | Nội dung | Số dòng tham chiếu (local) | Bảng |
|-------|----------|----------------------------|------|
| CAIDA (pfx2as + AS2Org) | prefix → ASN → tên tổ chức | ~967k | `ip_org_prefixes` |
| RIR delegated-extended | phân bổ IP theo `registered_holder` | ~262k | `ip_org_prefixes` (evidence) |
| RPKI ROAs | chứng thực prefix ↔ ASN | ~756k IPv4 ROAs | `rpki_roas` |
| APNIC eyeball | dân số user theo AS (phân loại eyeball/org) | vài MB, refresh định kỳ | dữ liệu runtime |

Lookup đi theo **longest-prefix**, lọc theo `org_kind` (org / eyeball / datacenter / cdn), **fail-open**
(lỗi thì trả None, không chặn request). Khi bật `company_graph`, kết quả được ghi bền vào
`company_graph` với `source="rir_asn"`.

---

## 2. Biến môi trường LOCAL (chỉ tên, KHÔNG secret)

Bật 6 flag trong root `.env` (đặt `= true`):

```dotenv
IP_ORG_LOOKUP_ENABLED=true
IP_ORG_FUSION_ENABLED=true
IP_ORG_RIR_INGEST_ENABLED=true
IP_ORG_RPKI_INGEST_ENABLED=true
IP_ORG_APNIC_REFRESH_ENABLED=true
COMPANY_GRAPH_ENABLED=true
```

Tên biến khớp `apps/api/config.py` (mặc định tất cả `False`):

| Biến `.env` | Field config | Mặc định | Ý nghĩa |
|-------------|--------------|----------|---------|
| `IP_ORG_LOOKUP_ENABLED` | `ip_org_lookup_enabled` | False | Bật lookup IP→org trong resolver ladder |
| `IP_ORG_FUSION_ENABLED` | `ip_org_fusion_enabled` | False | Bật lookup v2 fusion đa nguồn (`org_kind='org'`) |
| `IP_ORG_RIR_INGEST_ENABLED` | `ip_org_rir_ingest_enabled` | False | Cho phép nạp nguồn RIR |
| `IP_ORG_RPKI_INGEST_ENABLED` | `ip_org_rpki_ingest_enabled` | False | Cho phép nạp nguồn RPKI |
| `IP_ORG_APNIC_REFRESH_ENABLED` | `ip_org_apnic_refresh_enabled` | False | Bật job APScheduler refresh APNIC eyeball (mặc định 168h) |
| `COMPANY_GRAPH_ENABLED` | `company_graph_enabled` | False | Ghi bền kết quả vào `company_graph` (`source="rir_asn"`) |

**DB local — bắt buộc:** `DATABASE_URL` phải trỏ `localhost:5433` (Docker Postgres), **không bao giờ** trỏ prod.

> ⚠️ **Cảnh báo an toàn:** `.env` trong repo này mặc định trỏ **Supabase PROD**. `.env` đã bị `.gitignore`
> nên không commit. Trước mọi lệnh alembic / script chạm DB, luôn **pin** `DATABASE_URL=localhost:5433`
> trong môi trường lệnh. `alembic` chưa có guard local-host — chỉ `scripts/refresh_ip_org.py` mới có.

---

## 3. Bật flag ≠ đã có data — phải INGEST

Bật flag chỉ mở đường code; bảng vẫn **rỗng** cho tới khi chạy ingest. `scripts/refresh_ip_org.py`
có **guard fail-closed**: `--apply` từ chối DSN non-local trừ khi thêm `--allow-remote` (DSN không đọc được = từ chối).

`--source` hợp lệ: `caida` (mặc định), `rir`, `rpki`, `all`.

```powershell
# Chạy từ repo root, venv active. Pin DB local trước cho chắc chắn.
$env:DATABASE_URL = "postgresql+asyncpg://<user>:<pass>@localhost:5433/<db>"

# Dry-run (không ghi) — kiểm tra trước
python scripts/refresh_ip_org.py --source all

# Nạp thật + swap bảng (staging-swap + advisory lock, crash giữa chừng không rò dòng)
python scripts/refresh_ip_org.py --source caida --apply
python scripts/refresh_ip_org.py --source rir   --apply
python scripts/refresh_ip_org.py --source rpki  --apply
# hoặc gộp:
python scripts/refresh_ip_org.py --source all --apply
```

APNIC eyeball **không** chạy qua CLI này — nó là job APScheduler chạy trong process FastAPI khi
`IP_ORG_APNIC_REFRESH_ENABLED=true` (mỗi `ip_org_apnic_refresh_interval_hours`, mặc định 168h/tuần).
Dữ liệu tải về nằm ở `apps/api/data/apnic_eyeball/runtime/` (runtime, **không commit**).

---

## 4. Khởi động API local

```powershell
.\scripts\dev-local.ps1
```

Script dựng Docker Postgres+Redis → venv/npm → alembic → API `:8000` + Web `:3000`.

> **Gotcha đã gặp:** guard trong `dev-local.ps1` từng false-positive vì chữ **"Supabase"** nằm trong
> **comment** của `.env` (không phải giá trị thật). Đã sửa wording comment để guard không hiểu nhầm.
> Nếu guard lại kêu "trỏ prod" mà DSN thật đã là localhost, kiểm tra comment trong `.env`.

---

## 5. Kết quả test / probe của session này (đã đo)

| Hạng mục | Kết quả |
|----------|---------|
| Unit trước ingest | ~398 pass |
| Integration trước ingest | ~23 pass |
| Ingest local `localhost:5433` | CAIDA ~969k giữ; +RIR ~262k (`registered_holder`); RPKI ~756k ROAs; APNIC eyeball refresh OK |
| Fusion confidence sau ingest | ~0.55–0.65 |
| Probe tối thiểu local live | **PASS** — org hit chạm trần; CDN / datacenter / miss → trả None (đúng thiết kế fail-open) |

---

## 6. Checklist "đã làm / chưa làm / cấm làm (prod)"

### ✅ Đã làm (local)
- [x] Xác nhận code Phase 1–3 + quality pack; schema live, flag OFF.
- [x] Bật 6 flag local trong `.env`.
- [x] Ingest local: CAIDA + RIR + RPKI + APNIC eyeball refresh.
- [x] Chạy test (unit + integration) + probe fusion + probe live tối thiểu → PASS.
- [x] Start API qua `dev-local.ps1`; sửa comment `.env` để guard không false-positive.

### ⏳ Chưa làm / bổ sung khi cần
- [ ] **Domain enrichment** vẫn thiếu (`domain` NULL). Leg domain đã **tách ra phase riêng** (Decision 2 Option B);
      `resolve_org_domain` / G18–G20 **chưa build**, gated trên đo lường yield G19. Làm riêng nếu cần domain hit.
- [ ] Web gọi API local: nếu `apps/web/.env.local` đang trỏ `NEXT_PUBLIC_API_URL` remote, sửa về
      `http://localhost:8000` để web dùng API local.
- [ ] Follow-ups: post-swap `ANALYZE ip_org_prefixes;`, biên tail G8, khoảng trống token eyeball
      (xem `backlog/ip-org-followups_NOTE_07-08-26.md`).

### 🚫 Cấm làm (prod) — chỉ theo runbook, từng bước
- [ ] **Không** bật flag ip-org trên prod ở đây. Prod theo `ip-org-prod-enable_RUNBOOK_07-08-26.md`:
      ingest (`--apply --allow-remote`) → flip flag **từng cái** → monitor `company_graph.source`.
- [ ] **Không** set biến trên Railway vội.
- [ ] **Không** chạy `alembic upgrade` bare từ repo root (nó apply thẳng vào Supabase PROD — `.env` trỏ prod, alembic chưa có guard).
- [ ] **Không** commit `.env` (secrets/flag local) và **không** commit dataset runtime lớn (APNIC).

---

## 7. Tham chiếu

- `apps/api/config.py` — định nghĩa 6 flag (mặc định OFF).
- `scripts/refresh_ip_org.py` — CLI ingest, guard local-host, `--source caida|rir|rpki|all`.
- `apps/api/services/ip_org_ingest.py` / `ip_org_lookup.py` / `ip_org_rir_ingest.py` /
  `rpki_ingest.py` / `rpki_validate.py` / `ip_org_fusion.py` / `apnic_eyeball_refresh.py`.
- `apps/api/services/company_resolver.py` — write-through `company_graph` `source="rir_asn"`.
- `apps/api/jobs/scheduler.py` — job APNIC refresh (`ip_org_apnic_refresh`).
- Prod runbook + follow-ups + local note: xem đầu tài liệu này.
- Môi trường Local→UAT→PROD tổng quát: [local-uat-prod.md](./local-uat-prod.md).
