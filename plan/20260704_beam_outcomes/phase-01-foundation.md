# Phase 01 — Nền tảng: goals + campaign_clicks + conversion theo URL

**Status:** ✅ SHIPPED 2026-07-04
**Migration:** `b7e3a9c4d1f6_add_conversion_outcomes.py` (rebase lên `a9d4e7f2c1b8` avatar_url — head mới đáp giữa chừng; multi-head xử lý đúng playbook)
**Verify:** 17 unit + 18 integration pass; regression ingest/site-delete pass; alembic upgrade sạch trên docker local.

## Bảng mới (model `apps/api/models/outcome.py`)

- `conversion_goals`: id, site_id, name (UNIQUE/site), goal_type (`url_match`), match_type (`exact|prefix|contains`), pattern, value_cents NULL, repeatable bool, enabled bool, timestamps. Index `(site_id, enabled)`. Max 20/site.
- `campaign_clicks`: touchpoint_id FK CASCADE, campaign_id FK CASCADE (denorm), site_id, visitor_id (browser đáp xuống), clicked_at. UNIQUE `(touchpoint_id, visitor_id)`, index `(site_id, visitor_id, clicked_at)`.
- `conversions`: site_id, goal_id FK CASCADE, visitor_id, touchpoint_id/campaign_id FK SET NULL, channel, attribution (`campaign|organic`), matched_by (`click_link|same_visitor`), source (`url_match`), value_cents, url, dedupe_key UNIQUE String(250), occurred_at. Index `(site_id, occurred_at)`, `(goal_id)`, `(campaign_id)`, `(site_id, visitor_id)`.
- Thêm index `idx_campaign_touchpoints_visitor` trên `campaign_touchpoints(visitor_id)`.

## Service `apps/api/services/conversion_tracker.py`

`normalize_path` / `matches_goal` / `build_dedupe_key` (pure) + `attribute_visitor` (2 lookup: campaign_clicks → fallback same-visitor touchpoint, window 30d) + `record_conversion` (ON CONFLICT DO NOTHING) + `process_batch` (best-effort, không bao giờ raise).

Dedupe: non-repeatable `{goal}:{visitor}`; repeatable url_match `{goal}:{visitor}:{YYYYMMDD}`; (P3: `:{event_id}`).

## Hooks `apps/api/routers/events.py`

1. Block `_tp` (~line 376): insert `campaign_clicks` sau 2 UPDATE, chạy cả khi clicked_at đã set (thiết bị 2).
2. Sau `_process_signal_events` (~line 214): gọi `process_batch` bọc try/except.

## CRUD `apps/api/routers/outcomes.py` + `schemas/outcomes.py`

GET/POST `/api/v1/outcomes/{site_id}/goals`, PATCH/DELETE `.../goals/{goal_id}`. Auth `verify_site_access`. 409 trùng tên, 400 goal 21, 422 pattern sai. Đăng ký main.py. Thêm 3 bảng vào delete tuple sites.py.

## Tests

- unit `test_conversion_matching.py`: normalize/match matrix/dedupe keys
- integration `test_outcomes_goals.py`: CRUD + limit + auth
- integration `test_conversion_ingest.py` (UA browser bắt buộc): organic, click-link, fallback same_visitor, window 31d, dedupe, disabled goal, tracker raise → vẫn 204

## Verify

```bash
.venv/bin/python -m alembic -c apps/api/alembic.ini heads && ... upgrade head
PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_conversion_matching.py tests/integration/test_outcomes_goals.py tests/integration/test_conversion_ingest.py -v
# regression: test_events_ingest.py, test_site_delete.py
```
