# Phase 03 — Doanh thu: beamConvert() + webhook (BACKLOG — đã thiết kế)

**Status:** 📦 backlog
**Migration:** 1 (`sites.outcomes_webhook_secret_ciphertext/_hint`)

- Pixel: `window.beamConvert(goal, {value})` cạnh `beamIdentify` (tracker.js:309); dùng `pushEvent`/`flush`/`OPTOUT` sẵn có (đã verify tên); consent gating tự áp. Size budget: 4240/5120 gz, +~120B vừa. Rebuild `npm run build && npm run size` trong apps/pixel (pixel serve bản MINIFIED). Assert size vào test_pixel.py.
- Schema events: regex type thêm `|conversion`; field `goal`/`value` (không persist bảng events, không cần migration events).
- Tracker: match goal theo tên (case-insensitive), thêm goal_type `js_event`; value clamp [0, $1M]; dedupe `:{event_id}`.
- Webhook: `POST /api/v1/outcomes/{site_id}/webhook` không auth, HMAC-SHA256 `X-Beam-Signature` + `compare_digest` (pattern billing.py:282-306), 60/min; payload {goal, email|visitor_id, value, occurred_at, event_id}; email→visitor qua `email_bidx`, chưa có → mint `"ec"+email_hash[:30]` (= click.py:111). Secret qua key_vault (encrypt_key/make_key_hint), reveal 1 lần, endpoint rotate + config.
- UI: card snippet copy-paste + card webhook secret.
- Tests: js_event (value, default, unknown goal, disabled, event_id dedupe), webhook (HMAC đúng/sai/thiếu, 503 chưa config, 404 site lạ, email resolve/mint, attribution qua campaign_clicks).
