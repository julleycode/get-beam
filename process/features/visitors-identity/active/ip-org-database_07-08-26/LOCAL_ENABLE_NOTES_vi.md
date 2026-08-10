---
name: report:ip-org-local-enable-notes-vi
description: "Ghi chú tiếng Việt: bật ip-org in-house ở LOCAL (6 flag, ingest CAIDA/RIR/RPKI/APNIC, test/probe, gotcha guard .env) — bổ sung cho runbook prod cùng thư mục"
date: 10-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: ip-org-database-local-enable
---

# ip-org — Ghi chú bật LOCAL (tiếng Việt, 10-08-26)

**BLUF:** Bổ sung cho `ip-org-prod-enable_RUNBOOK_07-08-26.md`. File runbook đó chỉ dành cho **prod**;
file này ghi lại **làm ở LOCAL** (`localhost:5433`). Hướng dẫn chi tiết + copy-paste: `docs/ip-org-local-enable.md`.

## Đã làm trong session (đúng sự thật)
- Xác nhận ip-org đã code Phase 1–3 + quality pack; schema live nhưng flag mặc định OFF.
- Bật 6 flag local trong `.env` (`= true`):
  `IP_ORG_LOOKUP_ENABLED`, `IP_ORG_FUSION_ENABLED`, `IP_ORG_RIR_INGEST_ENABLED`,
  `IP_ORG_RPKI_INGEST_ENABLED`, `IP_ORG_APNIC_REFRESH_ENABLED`, `COMPANY_GRAPH_ENABLED`.
- Ingest local trên `localhost:5433`: giữ CAIDA ~969k; thêm RIR ~262k (`registered_holder`);
  RPKI ~756k ROAs; APNIC eyeball refresh.
- Test: unit ~398 + integration ~23 pass trước đó; sau ingest probe fusion conf 0.55–0.65;
  probe tối thiểu local live PASS (org hit chạm trần; CDN/DC/miss → None).
- Start API qua `.\scripts\dev-local.ps1`.

## Gotcha
- Guard trong `dev-local.ps1` từng false-positive vì chữ **"Supabase"** nằm trong **comment** của `.env`
  (không phải giá trị). Đã đổi wording comment để guard hết hiểu nhầm.

## Ingest — nhắc nhanh
- Bật flag ≠ có data. Phải chạy `scripts/refresh_ip_org.py --source caida|rir|rpki|all --apply` (guard local-host).
- APNIC eyeball chạy bằng job APScheduler trong process API (không qua CLI); data runtime ở
  `apps/api/data/apnic_eyeball/runtime/` — **không commit**.

## Chưa làm / cấm làm
- Domain enrichment (`domain` NULL) đã tách phase riêng (Decision 2 Option B) — chưa build.
- Web gọi API local: sửa `apps/web/.env.local` → `NEXT_PUBLIC_API_URL=http://localhost:8000` nếu đang trỏ remote.
- **Prod:** chưa bật; đi theo runbook cùng thư mục — ingest → flip flag từng bước → monitor. Không set Railway vội.
- Không commit `.env`; không `alembic upgrade` bare từ repo root (trỏ Supabase PROD, chưa có guard).

## Liên quan
- Runbook prod: `ip-org-prod-enable_RUNBOOK_07-08-26.md` (cùng thư mục).
- Follow-ups: `../../backlog/ip-org-followups_NOTE_07-08-26.md`.
- Docs: `docs/ip-org-local-enable.md`.
