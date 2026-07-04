# Phase 02 — Trang báo cáo Outcomes

**Status:** ✅ SHIPPED 2026-07-04
**Migration:** không
**Verify:** 6 integration test report pass; `next build` + lint + `tsc --noEmit` sạch. UI sau login chưa click-through thủ công (cần Clerk session) — xem checklist manual trong plan.md.

## API

- `GET /api/v1/outcomes/{site_id}/report?days=30` (1-365) → totals {conversions, attributed, organic, revenue_cents, attributed_revenue_cents} + campaigns[] (sent/opened/clicked/converted/conversion_rate/revenue_cents; converted = DISTINCT visitor) + goals[] (goal 0-conversion vẫn hiện qua LEFT JOIN).
- Campaign stats (`campaigns.py:180`): thêm aggregate conversions → `CampaignStatsResponse` + `converted=0`, `conversion_rate=0.0`, `revenue_cents=0` (backward compatible).

## UI

- `api-types.ts` + `api.ts`: types + 5 methods (goals CRUD + report).
- Nav `layout.tsx`: thêm Outcomes (icon Target) sau Campaigns.
- Trang mới `dashboard/outcomes/page.tsx`: PageHeader + period toggle (7/30/90d) + 4 StatTile (Conversions / Beam-attributed / Revenue / Organic) + bảng campaign + quản lý goals tại chỗ (bảng + toggle enable bằng Button + delete có Dialog confirm + Dialog form New goal) + EmptyState "Prove what Beam converts".
- Campaign detail: grid `md:grid-cols-6`, StatTile Converted; Revenue tile chỉ hiện khi >0.
- Lưu ý: KHÔNG có component Switch — dùng Button pattern như `pauseMut` trong site-settings-dialog.tsx. Semantic tokens, không bg-white/hex.

## Tests + verify

- integration `test_outcomes_report.py`: totals, split organic/attributed, DISTINCT visitor, filter days, goal 0-conversion, 404 user khác, campaign stats field mới.
- `cd apps/web && npx tsc --noEmit && npm run build && npm run lint` (Vercel lint khi build).
- Manual: tạo goal → curl ingest pageview match → tiles nhảy.
