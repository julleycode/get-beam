# Phase 14 / 15 kickoff — tách god-file (cho session Claude Code mới)

> Dùng file này khi mở **session Claude Code mới** để làm P14/P15 an toàn.
> P1–P13 đã xong + push prod. P14/P15 là restructure thuần (KHÔNG đổi hành vi).

## Bối cảnh (1 phút)
- Audit + 15-phase plan: [plan.md](plan.md), bug thô: [references/](references/).
- Đã xong: P1–P4 dọn, P5–P12 toàn bộ bảo mật + đúng-đắn, P13 dedup ownership. Tất cả trên prod.
- Còn: **P14** tách `apps/api/services/identity_resolver.py` (1711 dòng) → module provider; **P15** tách `routers/visitors.py` (1390), `web/src/lib/api.ts` (1609), `platforms/twitter_browser.py`.
- Mục tiêu: **behavior-exact** — không sửa bug, không đổi hành vi, chỉ tách cấu trúc.

## Quy tắc bắt buộc (rủi ro cao)
1. **Nhánh riêng**, KHÔNG push thẳng `main`: `git checkout -b refactor/p14-identity-resolver`.
2. **Giữ public surface ổn định**: `class IdentityResolver`, `resolve()`, tên method công khai, route prefix, `api` singleton (frontend) phải giữ nguyên — chỉ di chuyển code nội bộ.
3. **Verify bằng e2e TRƯỚC khi merge** (không chỉ compile + unit). Xem mục dưới.
4. **Deploy PR Railway env** (cô lập, DB riêng) rồi smoke-test tay trước khi vào `main` ([[pr-64-railway-preview-env]]).
5. Sau khi xong: so output `resolve()` cho 1 visitor mẫu trước/sau (phải y hệt).

## Chạy e2e local an toàn
```bash
# Bật Docker Desktop trước, rồi:
./scripts/e2e-local.sh                 # tất cả spec, headless
./scripts/e2e-local.sh --headed        # xem trình duyệt chạy
./scripts/e2e-local.sh visitors.spec.ts
```
Script tự ép DB/Redis/API về **docker local** và **từ chối chạy nếu trỏ prod** (chống đụng Supabase prod). Docker hay crash trên máy này → nếu kẹt, dùng PR Railway env thay thế.

## Prompt mở màn (copy-paste vào session mới)
```
Tiếp tục refactor ReTargetAgent. Đọc plan/20260629_refactor_toan_bo/plan.md
+ phase-14-kickoff.md + memory refactor-audit-2026-06-29. Đã xong P1–P13 +
push prod. Giờ làm Phase 14: tách identity_resolver.py (1711 dòng) thành
module provider, BEHAVIOR-EXACT.

Bắt buộc:
- Giữ public surface ổn định (class IdentityResolver, resolve(), tên method).
- Làm trên nhánh refactor/p14, KHÔNG push main.
- Verify bằng e2e (./scripts/e2e-local.sh) TRƯỚC khi merge; e2e dùng DB local
  (script đã chặn prod), không đụng prod.
- Deploy PR Railway env + smoke-test tay trước khi vào main.

Bắt đầu bằng RESEARCH: map identity_resolver.py + mọi caller, đề xuất cách
tách an toàn theo từng provider, rồi CHỜ tôi duyệt trước khi ENTER EXECUTE MODE.
```

## Checklist trước khi merge mỗi phase
- [ ] `git branch` = nhánh refactor (KHÔNG phải main)
- [ ] `pytest tests/unit -q` xanh
- [ ] `./scripts/e2e-local.sh` xanh (hoặc smoke-test tay trên PR env)
- [ ] `cd apps/web && npm run build` xanh (cho P15 đụng api.ts/visitors page)
- [ ] So `resolve()`/route/`api` output trước-sau = y hệt
- [ ] Deploy PR Railway env OK → mới merge `main`
- [ ] Xóa PR env sau khi merge: `railway environment delete <tên>`

## Tái dùng cho P15
Đổi "Phase 14 / identity_resolver" thành "Phase 15 / visitors.py + api.ts +
twitter_browser" trong prompt. P15 đụng frontend → bắt buộc `npm run build` +
Playwright (đây là regression net cho trang visitors).
