# Phase 15 — Tách 3 god-file còn lại (execution plan)

> Behavior-exact. Nhánh `refactor/p15-god-files` (KHÔNG push main trực tiếp; PR + Railway smoke).
> Bản AN TOÀN cho cả 3 (tránh 2 rủi ro hành vi đã nêu trong research).

## 1. twitter_browser.py (671) → package mixin
- `apps/api/services/platforms/twitter_browser/` package.
- `class TwitterBrowserPoster(SessionMixin, PostingMixin, ScrapingMixin)` — `self.*` nguyên.
- Giữ module-level `_browser_lock`, `logger`; `__init__` set `self._cookie_path` (demo.py đụng thẳng `poster._cookie_path`).
- `__init__.py` re-export `TwitterBrowserPoster`, `TwitterBrowserError`, `TwitterSessionExpiredError`.
- 5 importer không đổi: config.py (chỉ settings), social_accounts.py, demo.py, sync.py, platforms/twitter.py.
- Verify: `pytest tests/unit -q` + import smoke 5 caller.

## 2. visitors.py (1390) → rút helper, GIỮ route đúng thứ tự
- ⚠️ KHÔNG tách sub-router (đảo thứ tự → `/{site_id}/countries` bị nuốt bởi `/{site_id}/{visitor_id}`).
- Rút ra `apps/api/routers/visitors_helpers.py` (hoặc package `_helpers`): `_row_to_dict`, `_known_visitor_ids`, `_build_visitor_filters`, `_compute_visitor_stat_counts`, `_resolution_skip_reason`, `_coverage_note`, `_SKIP_REASON_MESSAGES`, 3 bg job (`_run_resolution_job`, `_run_osint_scan_job`, `_run_social_resolution_job`), constants `_EXPORT_EVENT_CAP`.
- visitors.py import lại + re-export những gì external cần: `ai.py` dùng `_compute_visitor_stat_counts`; `tests/test_resolve_skip_messages.py` dùng `_SKIP_REASON_MESSAGES`+`_coverage_note`; `tests/integration/test_visitor_stats.py` dùng `_compute_visitor_stat_counts`.
- main.py KHÔNG đổi (vẫn `visitors.router`).
- Verify: `pytest tests/unit tests/integration -q` (route order, skip-messages, stats).

## 3. api.ts (1609) → rút types, GIỮ class
- ⚠️ KHÔNG factory/Object.assign (đổi instance→object, rủi ro this/token).
- Tách 50+ type/interface (dòng ~1037–1609) ra `apps/web/src/lib/api/types.ts`.
- `lib/api.ts` giữ nguyên `class ApiClient` + `export const api`; thêm `export type { ... } from "./api/types"` (hoặc re-export *).
- `@/lib/api` vẫn resolve `api` + mọi type cho 43 importer.
- Note: core-fetch/401-retry dedup = ĐỔI HÀNH VI → KHÔNG làm ở pass này.
- Verify: `cd apps/web && npm run build` + Playwright e2e.

## Checkpoint cuối (trước merge)
- [ ] `pytest tests/unit tests/integration -q` xanh
- [ ] `cd apps/web && npm run build` xanh
- [ ] `./scripts/e2e-local.sh` xanh (visitors spec = lưới chính)
- [ ] PR + Railway PR-env smoke (`/health`, `/openapi.json` route count y hệt, `/demo/identify`)
- [ ] merge main → xóa PR env
