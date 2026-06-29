# Refactor toàn bộ ReTargetAgent/Beam — Kế hoạch tổng (umbrella)

> Ngày tạo: 2026-06-29 · Trạng thái: ⏳ CHỜ DUYỆT (chưa đụng code)
> Nguồn: audit read-only 17 lát cắt khắp codebase (44k dòng). Dữ liệu thô: `references/`.

## 1. Tóm tắt cho người không rành kỹ thuật (VN)

App đang chạy thật, **mỗi lần sửa code là tự lên prod ngay**. Nên không refactor cả 44k dòng một lượt — quá rủi ro. Thay vào đó chia **15 đợt (phase)**, mỗi đợt:
- nhỏ, đọc-duyệt được,
- ship + test riêng,
- xếp **an toàn nhất + lợi nhất trước**, **rủi ro để sau**.

**Điểm sức khỏe code: 5/10.** Vỏ ngoài ổn (auth, HMAC webhook, react-query, migration Alembic, mã hóa PII đều đúng). Nhưng **lõi mục**: vài file khổng lồ copy-paste + một cụm **bug nguy hiểm ở mặt công khai** (ai cũng gọi được):

| # | Bug nặng nhất | Hậu quả |
|---|---|---|
| 1 | Email/CRM/alert gửi cho **nhân viên ngẫu nhiên** của công ty (đoán "company-level" nhưng không chặn ở chỗ gửi) | Spam người lạ chưa từng vào web → mất uy tín, vi phạm CAN-SPAM |
| 2 | **3 lỗ SSRF** (2 cái không cần đăng nhập) trên `/demo` | Server prod bị lừa gọi vào nội bộ / cloud-metadata → lộ credential |
| 3 | **Lộ PII chéo khách hàng** trên `/demo` công khai | Người lạ lấy được tên + email của người được nhận diện ở web khách khác |
| 4 | **Key HMAC fallback hardcode** + signup cũ bỏ qua invite-gate | Phá blind-index PII; tạo account vô tội vạ, mồ côi khỏi Clerk |
| 5 | Celery asyncpg hỏng + re-segmentation tính tiền 2 lần | Bật worker là hỏng; Gemini bị tính tiền lặp |

→ Đề xuất: duyệt **Phase 1–4 (dọn an toàn) theo cụm** để bạn quen với diff an toàn, rồi làm **Phase 5–9 (bug bảo mật/outbound) từng cái một**, canh prod sau mỗi lần deploy. Restructure file lớn (Phase 14–15) để **cuối cùng**, khi test đã xanh.

## 2. Số liệu audit

- 17 lát cắt đọc song song · **91 hotspot** (điểm rối) · **116 bug nghi ngờ** → verify đối kháng **83** → **57 bug thật** (11 cao, 31 vừa, 15 thấp).
- 4 file khổng lồ: `identity_resolver.py` (1711), `api.ts` (1609), `visitors.py` (1390), `twitter_browser.py` (675).
- Dead code cao bất thường (provider wrapper chết, mock builder chết, Cloudflare worker chết, schema/fixture chết).

## 3. Nguyên tắc thực thi

1. Mỗi phase = 1 commit/PR riêng, có **lệnh verify** cụ thể (test/build) trong bảng dưới.
2. **Không** đụng hạ tầng đang chạy tốt: auth JWT, HMAC webhook, react-query, token-gate.
3. Bug bảo mật: deploy xong **canh prod**; phase có migration → chạy `alembic upgrade head` trên DB nháp trước.
4. Restructure (P13–15) chỉ làm khi **pytest + Playwright xanh**; ưu tiên deploy qua **PR Railway env** trước.
5. Trạng thái mỗi phase: ⏳ chưa làm · 🔨 đang làm · ✅ xong+verify · ⏸ tạm dừng.

## 4. 15 Phase

Cột: kind (cleanup/bugfix/restructure) · risk · roi · effort (S/M/L/XL) · behavior (mức đổi hành vi) · deps (phụ thuộc phase nào).

| # | Tên | kind | risk | roi | effort | behavior | deps | trạng thái |
|---|-----|------|------|-----|--------|----------|------|--------|
| 1 | Xóa dead code đã xác minh (0 đổi hành vi) | cleanup | low | high | M | none | — | ✅ 2026-06-29 (−418 dòng/8 file; 503 collect + 285 unit pass) |
| 2 | Sửa type hint sai/gãy | cleanup | low | high | S | none | — | ✅ 2026-06-29 (4 fix: waitlist.approved_at Mapped[None]→datetime; pages_visited/recommended_channels/twitter_recent_topics dict→list[str]; 285 unit pass) |
| 3 | Gộp copy-paste backend vào helper chung | cleanup | low | high | M | none | 1 | ✅ 2026-06-29 (−153 dòng; base.post_retry+_is_transient hoist ×5 platform; _budget_result ×3; _apply_proxycurl/_apply_twitter; sender _http_error_detail; sync _sync_accounts; 285 unit pass) |
| 4 | Gộp dup frontend + lộ lỗi đang bị nuốt | cleanup | low | high | M | low | — | ✅ 2026-06-29 (lộ lỗi: settings deleteKey/clipboard, segments trigger, kpi-strip cancel-flag, pixel-guide clipboard; `next build` pass. api.ts core-fetch dedup HOÃN sang P15 — cần e2e) |
| 5 | **BUG**: bịt 3 lỗ SSRF (2 cái public) | bugfix | med | high | M | med | — | ✅ 2026-06-29 commit d673175 (url_guard.safe_get manual redirect re-validate + is_safe_public_url gate trong detect_platform/verify_pixel, bỏ verify=False; 15 SSRF test, 300 unit pass). CHƯA push — behavior-changing, deploy+watch prod |
| 6 | **BUG**: chặn lộ PII chéo tenant + signup bỏ invite-gate | bugfix | med | high | L | med | — | ✅ part1 7e798ab (pushed: demo cross-site PII bỏ + signup 404 prod). part2 ✅ befe191 (pushed, MIGRATION cb697a56c928: posts composite-unique, scope feed/sync dedup). GDPR export over-match ✅ 135aedc (visitors.py export scope join SocialAccount.user_id). P6 XONG |
| 7 | **BUG**: cứng hóa kiểm tra secret/config + xóa jwt_secret chết | bugfix | med | high | M | med | 2 | ✅ 2026-06-29 commit 0ab2e11 (CHƯA push). pii_crypto + known_hash bỏ hardcoded fallback → raise; validate_production chạy cho prod + app_env lạ (allowlist {dev,test,local,ci}); xóa jwt_secret/jwt_algorithm/cors_origins chết. 7 unit test, 311 pass. PUSHED — deploy gate verified qua Railway dashboard: APP_ENV=production + ENCRYPTION_KEY set ✅ |
| 8 | **BUG**: đúng hóa identity resolution (false-positive person) | bugfix | med | high | L | med | 1,3 | ✅ 2026-06-29 commit 36ebe2f (CHƯA push). no-timestamp record → refused; enricher None không clobber + PDL 401≠404 (_PDLNonTransientError, không mark failed); social_intel _mock_tweets→[]. 7 test, 318 pass |
| 9 | **BUG**: enforce identity-level + suppression ở MỌI cổng outbound | bugfix | **high** | high | L | **high** | 8 | ✅ core 2026-06-29 commit 2e76004 (CHƯA push). is_emailable_identity gate ở campaign_sender + csv_exporter(=CRM) + hot_alert; email_sender check suppression-list; +fingerprint_match/beam_identity_network vào person-set; 17 gate test, 337 pass. remainder ✅ c9d408a (CHƯA push): webhooks→add_suppression (blind-index entry, đóng re-identify hole), auto_drafter mock gated on mock_external_apis, csv _csv_safe formula-injection. P9 XONG. |
| 10 | **BUG**: concurrency/async (Celery, race, re-segmentation) | bugfix | med | med | L | med | 8 | ✅ core 2026-06-29 commit e8079a4 (CHƯA push). asyncio.run ×4 (resolution+aggregation tasks); segmentation +segmented==False (hết double-bill); drafts ownership join (IDOR); 349 pass. HOÃN (low impact ở scale APScheduler đơn tiến trình): billing/usage_limits atomic, segmentation_trigger TOCTOU, events coalescing |
| 11 | **BUG**: pixel privacy + Cloudflare worker + dep manifest | bugfix | med | med | M | med | — | ✅ core 2026-06-29 commit 919dd1d (CHƯA push). pixel form-capture bail khi OPTOUT (GPC/DNT, vẫn <5KB=4995); events aggregation coalesce per-site. HOÃN: worker/wrangler chết (first-party-pixel?), dep-manifest (cần test build), events NULL-event_id |
| 12 | **BUG**: email-validation + retry-idempotency + còn lại | bugfix | med | med | M | med | 3,5,11 | ✅ 2026-06-29 commit ca93593 (CHƯA push). post_retry write-safe (hết double-post); twitter_browser raise thay synthetic id; pixel wrong_site=verified False; shopify callback redirect error; email MX thật (dnspython==2.8.0 thêm requirements). 4 test, 349+ pass |
| 13 | Dependency ownership chung + dedup router | restructure | med | med | M | low | 5,6 | ✅ core 2026-06-29 commit 4d645bf (CHƯA push). 5 helper ownership trùng → 1 `dependencies.verify_site_access`; behavior-exact; 353 pass. HOÃN: ~20 inline select + companies page_size cap |
| 14 | Tách god-file `identity_resolver.py` → module provider | restructure | **high** | med | XL | low | 1,3,8,9 | ✅ 2026-06-29 nhánh refactor/p14-identity-resolver (CHƯA merge main). 1574→776 dòng + 9 file `identity_providers/` (mixin, behavior-exact). Public surface giữ nguyên (resolve/check_daily_budget/was_recently_attempted + 7 `_call_*` demo.py + `_url_to_host` re-export + `_GRAPH_TIMEOUT`). 391 unit + integration resolver pass; e2e visitors 4/4 + IP-to-Company 2/2 + dashboard pass (blog fail = thiếu admin seed, không dính). CÒN: PR Railway env smoke → merge main |
| 15 | Tách god-file còn lại: `visitors.py`, `api.ts`, `twitter_browser.py` | restructure | **high** | low | XL | low | 3,4,13 | ✅ 2026-06-29 nhánh refactor/p15-god-files (CHƯA merge main). Bản AN TOÀN: (a) twitter_browser.py 671→package mixin `twitter_browser/` (session/posting/scraping); (b) visitors.py 1390→1052, rút 11 helper+bg-job ra `visitors_helpers.py` GIỮ route đúng thứ tự (re-export cho ai.py+test); (c) api.ts 1609→1143, rút 59 type ra `api-types.ts` GIỮ class+singleton `api`. behavior-exact. Sửa kèm 3 test-target theo symbol đã move (conftest async_session→visitors_helpers, osint+social patch). 353 unit + integration 153 pass (4 fail PRE-EXISTING, chứng minh trên baseline); `npm run build` pass; e2e visitors 4/4 + IP-to-Company 2/2 + dashboard pass. CÒN: PR Railway env smoke → merge main |

Chi tiết từng phase (goal, file, task, lệnh verify) → tạo file `phase-NN_*.md` khi bắt đầu phase đó. Chi tiết đầy đủ đã có trong `references/synthesized-plan.json`.

## 5. Lộ trình đề xuất (sequencing)

```
Cụm A (duyệt 1 lần, an toàn):   P1 → P2 → P3 → P4
Cụm B (từng cái, canh prod):    P5 → P6 → P7 → P8 → P9 → P10 → P11 → P12
Cụm C (chỉ khi test xanh):      P13 → P14 → P15
```

P9 là **rủi ro cao nhất nhưng quan trọng nhất về thương mại** (chặn email sai người) — làm sau P8 (đã có flag person/company) và canh prod kỹ.

## 6. Rủi ro toàn cục

- Auto-deploy: mọi commit lên prod → mỗi phase phải tự verify được, không gộp.
- P7 (secret): **trước khi deploy phải chắc Railway prod có `APP_ENV=production` + `ENCRYPTION_KEY`** kẻo app không boot.
- P14/P15 (tách file lớn): rủi ro regression UI/router → deploy qua PR Railway env + full Playwright trước khi vào main.
- Migration (P6, P10): chạy thử `alembic upgrade head` trên DB scratch; lưu ý multi-head với migration CRM chưa commit (xem memory).
