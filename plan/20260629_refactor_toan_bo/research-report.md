# Research report — Refactor audit toàn bộ ReTargetAgent/Beam

> Read-only audit · 2026-06-29 · 17 lát cắt · 91 hotspot · 57 bug đã verify thật
> Raw data: `references/confirmed-bugs.json`, `references/hotspots-and-deadcode.json`, `references/synthesized-plan.json`

## Health: 5/10

Vỏ ngoài ổn — HMAC webhook dùng `compare_digest` (timing-safe), auth chặn nhầm RS256/HS256, react-query toàn repo với token-gate ở layout, Alembic đã có, pixel tôn trọng phần lớn privacy signal, có mitigation prompt-injection, 503 test collect sạch, đã diệt hết anti-pattern Playwright.

Lõi mục — 4 god-file 1000–1700 dòng với surface provider gấp 3 + copy-paste nguyên văn; pipeline identity false-positive (lưu nhân viên ngẫu nhiên thành người thật) mà nhãn "company" **không được enforce ở bất kỳ cổng outbound nào** (finding nặng nhất); 3 SSRF (2 unauth public); 2 lộ PII chéo tenant trên `/demo`; key HMAC fallback hardcode; signup cũ bỏ qua invite-gate; Celery asyncpg hỏng; re-segmentation double-billing; datetime naive-UTC tràn lan.

## Top themes (mục theo cụm)

1. **God-file + copy-paste gấp 3 surface** — identity_resolver 1711, visitors 1390, api.ts 1609, twitter_browser 675, enricher, csv_exporter.
2. **Nhãn an toàn không được enforce** — đoán "company-level" + match yếu/không timestamp chảy thẳng vào cổng gửi email/CRM/alert.
3. **Lỗ bảo mật mặt công khai** — 3× SSRF (2 unauth), 2× lộ PII chéo tenant `/demo`, signup bỏ invite-gate, key HMAC hardcode.
4. **Dead code nhiều** — provider wrapper chết, AI mock builder chết, Cloudflare worker chết, dep manifest trùng, schema/fixture chết.
5. **Concurrency/async tiềm ẩn** — Celery asyncpg loop hỏng, check-then-increment budget/usage không atomic, re-segmentation double-bill.
6. **Datetime naive-UTC** + redeclare Base-column không nhất quán giữa models.
7. **Nuốt lỗi âm thầm / false success UI** — empty catch, "Copied!" giả, pixel "verified" giả, mock-draft khi LLM fail bị lưu thành thật.

---

## 11 BUG NẶNG (high) — đã verify thật

### H1 · campaign_sender.py — gửi email cho nhân viên ngẫu nhiên (nhãn company không enforce)
`send_campaign_emails` (dòng 77–90) chọn `IdentifiedVisitor` rồi email `iv.email` **không check** `resolution_provider`/`identity_level`. `identity_classification.py` gán hunter+apollo = "company" (nhân viên ngẫu nhiên ở domain công ty, `emails[0]`/`people[0]`), KHÔNG phải người thật. Nhãn hiện ở dashboard (`visitors.py:736`) nhưng không enforce trước khi gửi. Cùng lỗ ở `hot_alert.py` + CRM push.
**Fix:** gate tập trung dùng chung — `identity_level(provider)=="person"` (hoặc lưu cờ `is_company_level` lúc resolve), áp ở: (1) campaign send loop, (2) `csv_exporter._get_segment_visitors` (cover cả CRM + CSV), (3) `hot_alert.maybe_send_hot_alert`. Provider chưa phân loại (level None) phải **default chặn**. → **Phase 9**

### H2 · platform_detector.py — SSRF (verify=False, follow_redirects=True)
`detect_platform()` (140–146, 188–193) fetch URL người dùng nhập với `follow_redirects=True` + `verify=False`, không allow/deny-list, không chặn private/loopback/link-local/metadata (169.254.169.254...). Tới từ `sites.py:202` (auth nhưng không check ownership) và `demo.py:66` (**không auth**). → **Phase 5**

### H3 · twitter_browser.py — bịa ID reply giả khi không bắt được ID thật
`_click_reply_and_get_id()` (655–664): không bắt được rest_id thật thì trả `browser_reply_<timestamp>` như ID thật. `sender.py:123–129` rồi set `draft.status=sent`, `post.commented=True`. Reply có thể đã FAIL (rate-limit/duplicate/blocked). **Fix:** raise `TwitterBrowserError` khi không có rest_id thật, đừng tin toast/UI. → **Phase 12**

### H4 · resolution_tasks.py — Celery asyncpg loop hỏng
`process_all_pending_visitors`, `process_single_site`, `enrich_visitor_tier2`, `aggregate_all_sites` dùng `asyncio.get_event_loop().run_until_complete()`. `segmentation_tasks`/`crm_tasks` đã migrate sang `asyncio.run()` ("reusing loop breaks asyncpg"). 4 task này còn pattern hỏng → task thứ 2 mỗi worker raise "Future attached to a different loop". Hiện ẩn vì prod chạy APScheduler không Celery. **Fix:** đổi sang `asyncio.run()`. → **Phase 10**

### H5 · segmentation_tasks.py — re-segment người đã segment (double-bill Gemini)
`_run_segmentation_for_site` (54–61) chọn `enrichment_status=='enriched'` KHÔNG có `segmented==False`, limit 50 theo intent desc, rồi mark 50 đó segmented. Trigger lại đếm chỉ `segmented==False`. Site >50 enriched → mỗi trigger kéo lại đúng top-50 cũ, chạy lại Gemini, tạo Segment/Campaign trùng; người mới intent thấp bị bỏ đói. **Fix:** thêm `Visitor.segmented==False` vào select. → **Phase 10**

### H6 · demo.py — SSRF public unauth (detect-platform)
`POST /api/v1/demo/detect-platform` nhận `url` tùy ý → `detect_platform` (`follow_redirects=True, verify=False`), chỉ chặn 12/min theo `X-Forwarded-For` (giả mạo được). Target metadata/localhost/internal Railway. **Fix:** dùng `url_guard.is_safe_public_url` trước khi fetch + `follow_redirects=False` (chống 302→internal & DNS-rebinding). → **Phase 5**

### H7 · demo.py — lộ identity chéo tenant (demo_identify)
`demo_identify` (unauth, 6/min) nhận `fingerprint` client-supplied → query `BeamIdentityNode` **across ALL sites** lấy node có email → trả `full_name`+`email`+PDL enrichment cho người gọi ẩn danh. Fingerprint `fp2_` lộ trong network traffic của bất kỳ site nào. **Fix:** path public không bao giờ đọc từ graph cross-site; chỉ trả identity khi fingerprint khớp Visitor thuộc account onboarding đang auth, hoặc đưa sau auth. → **Phase 6**

### H8 · auth.py — legacy signup bỏ qua invite-gate + orphan Clerk
`POST /api/v1/auth/signup` (28–44) tạo User + trả token **không** check invite/waitlist. Mounted live (`main.py:160`), gọi từ onboarding fallback. Bypass hệ invite + tạo account mồ côi khỏi Clerk. Lưu ý: `invite_only` default False (chỉ cắn khi operator bật `INVITE_ONLY=true`), nhưng orphan-from-Clerk là vô điều kiện; frontend chỉ gọi khi Clerk unavailable. **Fix:** xóa endpoint legacy signup (giữ login/get_current_user cho token cũ), hoặc gate cùng check như Clerk path. → **Phase 6**

### H9 · pii_crypto.py — key HMAC blind-index fallback hardcode
`_hmac_key` (35–37) fallback literal `'beam-pii-fallback-key'` khi cả `pii_hmac_key` và `encryption_key` rỗng. Prod chặn empty key CHỈ khi `app_env=='production'` — nếu app_env cấu hình sai HOẶC non-prod giữ PII thật (staging clone) → `email_hash()` dùng key hằng công khai → membership oracle. **Twin cùng lỗi** ở `known_hash.py` (`"beam-known-contacts-fallback-key"`). **Fix:** bỏ fallback, raise nếu thiếu key; sửa cả twin; cứng hóa `validate_production` fail khi app_env lạ. → **Phase 7**

### H10 · email_sender.py — suppression chỉ check do_not_email flag, bỏ suppression_list
`_is_suppressed` (20–34) chỉ query `IdentifiedVisitor.do_not_email`, không gọi `suppression.is_email_suppressed`. Export/CRM check cả hai; send path thì không. Email opt-out (`scope='do_not_email'`) được nhận diện LẦN ĐẦU sau khi opt-out → vẫn gửi được. Vi phạm GDPR/CCPA. **Fix:** thêm `is_email_suppressed(db, iv.email, 'do_not_email')` vào campaign send loop. → **Phase 9**

### H11 · drafts.py — IDOR + LLM cost vô hạn (generate draft)
`generate_new_draft` (126–156) load `Post` theo `body.post_id` **không check ownership** (không join `SocialAccount.user_id`). User bất kỳ truyền `post_id` bất kỳ → trigger `generate_multi_drafts` (1–3 LLM call/request) không rate-limit → burn OpenRouter credit + đọc post người khác. **Fix:** join Post→SocialAccount require `user_id==current_user.id` (else 404) + per-user daily cap (reuse `check_usage_allowed`). → **Phase 10**

---

## 31 bug VỪA (medium) — tóm tắt theo phase

- **P5 (SSRF):** `pixel_verifier.py` fetch `site.url` với `verify=False`; pixel_verifier báo "verified" sai khi data-site không khớp.
- **P6 (public surface):** `feed.py` collision `platform_post_id` unique chéo user; `visitors.py` GDPR export over-match social posts chéo tenant.
- **P7 (config):** `main.py` validate prod chạy sau khi route đã mount; `config.py` jwt_secret check vô nghĩa.
- **P8 (identity):** `identity_resolver.py` accept record không timestamp trên IP-equality; `enricher.py` PDL 404 vs 401 lẫn lộn + cascade overwrite field populated thành None; `social_intelligence.py` `_mock_tweets` không tồn tại → AttributeError.
- **P9 (outbound):** `auto_drafter.py` LLM fail → lưu mock draft thành thật; `webhooks.py` hard-bounce chỉ set do_not_email trên IdentifiedVisitor (không vào suppression_list); `campaign_sender.py` over-send window.
- **P10 (concurrency):** `billing.py` + `usage_limits.py` + `social_resolver.py` + `segmentation_trigger.py` check-then-increment/TOCTOU không atomic; `events.py` aggregation `create_task` unbounded + idempotency chỉ với client event_id.
- **P11 (pixel/infra):** `worker.js` ref `TRACKER_JS` chưa bind; `csv_exporter.py` CSV formula-injection; `email_validator.py` "MX check" thực ra getaddrinfo port 25.
- **P12 (correctness):** `twitter.py` tenacity retry POST không idempotency key → double-post; `sites.py` OAuth callback nuốt fail vẫn báo `?shopify=connected`.
- **Frontend:** `kpi-strip.tsx` fetch effect không cancel flag; `segments/page.tsx` empty catch; `social-accounts/page.tsx` window.open thiếu noopener; `api.ts` 2 blob download raw fetch; `feature_requests.py` HTML email chưa escape user input.
- **Tests:** `test_beam_identity.py` + `test_events_ingest.py` không assert hành vi production thật.

15 bug THẤP (low): PII trong log (`visitors.py`), token unsubscribe không TTL, JSON-LD XSS qua dangerouslySetInnerHTML (`blog/[slug]`), clipboard không try/catch, empty catch nuốt lỗi onboarding/settings, type hint `Mapped[None]`, wrangler bucket upload thừa, v.v. Chi tiết: `references/confirmed-bugs.json`.

---

## Hotspot refactor (91) — file rối nhất

| File | Dòng | Vấn đề | effort |
|------|------|--------|--------|
| `identity_resolver.py` | 1711 | god-file 6 concern; provider pair `_try_*`(chết)+`_call_*`+`_parse_*` gấp 3 surface | L |
| `api.ts` | 1609 | god-file client, any types, fetch logic lặp | L |
| `visitors.py` | 1390 | router béo, N+1, ownership check copy-paste ~12 chỗ | L |
| `twitter_browser.py` | 675 | browser scrape, selector brittle, swallowed exceptions | L |
| `social_resolver.py` | resolve_social 146–317 | 1 hàm 170 dòng chạy cả pipeline A–F | M |
| `enricher.py`, `csv_exporter.py`, platforms/* | — | copy-paste parser/exporter | M |

Chi tiết 91 hotspot: `references/hotspots-and-deadcode.json`.
