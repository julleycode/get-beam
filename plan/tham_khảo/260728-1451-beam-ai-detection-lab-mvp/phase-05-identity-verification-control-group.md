---
phase: 5
title: "Identity Verification & Control Group"
status: pending
priority: P1
dependencies: [4]
effort: ""
---

# Phase 5: Identity Verification & Control Group

## Overview

Trả lời câu hỏi có ROI cao nhất của cả lab: **request tự khai là ai, và có xác minh được không?**
Bốn tầng verify theo thứ tự tin cậy giảm dần, cộng control group synthetic để chứng minh pipeline đúng.

Thứ tự tin cậy: `signature (Web Bot Auth) > IP CIDR > rDNS > UA claim`.

## Requirements

**Functional**
- Agent registry versioned: UA pattern → provider, agent_name, purpose, loại (training/index/live).
- IP range verifier: mỗi agent một dải riêng, tải từ nguồn vendor, cache, có version hash.
- rDNS verifier: dùng `rdns_result` đã niêm phong trong bundle (phase 1), không resolve lại.
- Web Bot Auth verifier: RFC 9421 HTTP Message Signatures.
- Spoof detection: UA khai X nhưng IP không thuộc dải X → `spoofed_bot`.
- Control group: 11 kịch bản synthetic chạy bằng script, dùng làm ground truth cho detector.

**Non-functional**
- Tải IP range là công việc **ngoài detector** (INV-2). Detector chỉ đọc snapshot đã niêm phong.
- Tải range lỗi → giữ cache cũ, không được làm hỏng ingest hay verify sai.

## Architecture

### Nguồn IP range — không gộp vendor

OpenAI publish **3 file riêng biệt**: `gptbot.json`, `searchbot.json`, `chatgpt-user.json`.
Gộp thành "OpenAI ranges" sẽ mất khả năng phát hiện bất thường kiểu *GPTBot đến từ dải của ChatGPT-User*.
Mỗi `agent_name` map tới đúng một nguồn range.

```sql
CREATE TABLE ip_range_snapshot_set (
  set_id        TEXT PRIMARY KEY,  -- một lần refresh = một set
  created_at    TEXT NOT NULL
);

CREATE TABLE ip_range_snapshot (
  snapshot_id   TEXT PRIMARY KEY,
  set_id        TEXT NOT NULL REFERENCES ip_range_snapshot_set(set_id),
  fetched_at    TEXT NOT NULL,
  source_url    TEXT NOT NULL,
  agent_name    TEXT NOT NULL,
  cidrs_json    TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  fetch_status  TEXT NOT NULL     -- ok | stale_cache | error
);

CREATE TABLE agent_registry (
  agent_name    TEXT PRIMARY KEY,
  provider      TEXT NOT NULL,
  ua_pattern    TEXT NOT NULL,       -- regex
  purpose       TEXT NOT NULL,       -- model_training | search_indexing | user_fetch | link_preview
  behavior_class TEXT NOT NULL,      -- training_crawl | search_index | live_fetch
  range_source_url TEXT,             -- NULL nếu vendor không publish
  supports_rdns INTEGER NOT NULL DEFAULT 0,
  supports_signature INTEGER NOT NULL DEFAULT 0,
  registry_version INTEGER NOT NULL,
  updated_at    TEXT NOT NULL
);
```

`evidence_bundle.ip_range_snapshot_id` (đã có từ phase 1) trỏ tới **set** đang hiệu lực lúc request —
một set chứa ~15 hàng, một hàng/agent. Trỏ tới một hàng đơn lẻ là vô nghĩa vì mỗi lần refresh sinh
nhiều hàng. Replay dùng đúng set đó → provenance đầy đủ theo từng agent, kể cả khi vendor đã đổi dải.

### Web Bot Auth (RFC 9421)

Ba bước verify:

```
1. Đọc header Signature-Agent  → lấy domain của agent
2. GET https://{domain}/.well-known/http-message-signatures-directory  → lấy public key (JWK)
3. Verify Signature + Signature-Input với key đó; kiểm created/expires còn hạn
```

Bước 2 là **network call** → phải làm ở intake (phase 1 style), niêm phong kết quả vào bundle.
Detector chỉ đọc `bundle.signature_verification` đã có sẵn. Thêm cột:

```sql
ALTER TABLE evidence_bundle ADD COLUMN signature_agent TEXT;
ALTER TABLE evidence_bundle ADD COLUMN signature_verify_status TEXT;  -- valid|invalid|no_signature|directory_unreachable|expired
ALTER TABLE evidence_bundle ADD COLUMN signature_key_thumbprint TEXT;
```

Directory phải cache theo domain (TTL vài giờ) — không fetch mỗi request.

### Kết quả identity

```
verified            ≥1 tầng cứng pass (signature hoặc IP CIDR), không tầng nào mâu thuẫn
partially_verified  rDNS pass nhưng không có signature/CIDR để đối chiếu
claimed_only        chỉ có UA, vendor không publish cách verify
verification_failed UA khai X, có nguồn verify của X, nhưng không khớp  → spoofed_bot
not_applicable      UA không khớp agent nào trong registry
```

### Control group — 11 kịch bản

| # | Kịch bản | Kỳ vọng |
|---|---|---|
| 1 | Chrome thật (headful) | no automation signal, full_browser_assets |
| 2 | Mobile browser | như trên |
| 3 | In-app browser UA | không bị coi là bot |
| 4 | Headless Chrome | automation signal |
| 5 | Playwright | automation signal |
| 6 | Playwright + stealth | automation signal yếu hoặc không có — ghi nhận, không kỳ vọng bắt được |
| 7 | Puppeteer | automation signal |
| 8 | Selenium | automation signal |
| 9 | curl | html_only, not_applicable |
| 10 | python-requests | html_only, ua bot match |
| 11 | **UA spoof: GPTBot từ IP local** | **verification_failed → spoofed_bot** |

Kịch bản 11 là phép thử quan trọng nhất — nó chứng minh tầng IP verify hoạt động.

## Related Code Files

- Create: `src/beam_lab/identity/registry.py` — agent registry loader, versioned
- Create: `src/beam_lab/identity/registry_data.yaml` — dữ liệu agent, có `registry_version`
- Create: `src/beam_lab/identity/ip_ranges.py` — fetch, cache, snapshot
- Create: `src/beam_lab/identity/webbotauth.py` — RFC 9421 verify + directory cache
- Create: `src/beam_lab/detectors/identity_verify.py` — detector pure, đọc snapshot từ bundle
- Create: `scripts/refresh_ip_ranges.py`
- Create: `scripts/control_group/` — 11 script kịch bản
- Create: `scripts/control_group/run_all.py`
- Modify: `src/beam_lab/intake/middleware.py` — gắn signature verify + range snapshot id
- Modify: `src/beam_lab/db/schema.sql`
- Create: `tests/test_ip_range_verify.py`
- Create: `tests/test_webbotauth_verify.py`
- Create: `tests/test_spoof_detection.py`

## Implementation Steps

1. `registry_data.yaml`: khai báo agent cho OpenAI (GPTBot, OAI-SearchBot, ChatGPT-User), Anthropic (ClaudeBot, Claude-SearchBot, Claude-User), Perplexity (PerplexityBot, Perplexity-User), Google, Bing, Meta, ByteDance, Amazon, CCBot, Applebot. **Mỗi agent một `range_source_url` riêng.**
2. `identity/ip_ranges.py`: fetch từng URL, parse CIDR, lưu một `ip_range_snapshot_set` mới gồm một hàng/agent kèm sha256. Lỗi fetch → giữ hàng cũ của agent đó trong set mới, ghi `fetch_status='stale_cache'`, không xoá cache. Compile toàn bộ CIDR thành network object giữ trong app state (nạp lại khi set đổi); middleware tra cứu in-memory, không parse `cidrs_json` từ DB mỗi request.
3. `scripts/refresh_ip_ranges.py`: chạy tay hoặc theo scheduler phase 8. Log rõ dải nào đổi.
4. `identity/webbotauth.py`: parse `Signature`, `Signature-Input`; parse `Signature-Agent` cả hai dạng — item chuỗi (`"https://bot.example"`) và dictionary có label khớp nhãn signature (Google ký với label riêng, vd `g="https://agent.bot.goog"`). Fetch directory với cache TTL; verify Ed25519/RSA theo RFC 9421; kiểm `created`/`expires`.
5. Middleware: gọi webbotauth verify (directory đã cache, timeout 1s, lỗi → `directory_unreachable`) song song với route handler, gán `ip_range_snapshot_id` (set mới nhất) vào bundle. Tổng độ trễ thêm vào request path (rDNS + signature) phải dưới ~1s — công cụ đo không được làm agent bỏ cuộc (xem risk W9 ở phase 1).
6. **Niêm phong kết quả CIDR lúc request** — `ip_raw` bị xoá sau 24h (phase 1), nên detector không được phụ thuộc vào nó khi replay. Middleware tính sẵn và lưu:

   ```sql
   ALTER TABLE evidence_bundle ADD COLUMN ip_range_match_json TEXT;
   -- {"GPTBot": false, "ChatGPT-User": true, "ClaudeBot": false, ...}
   ```

   Tính cho mọi agent trong registry có `range_source_url`, không chỉ agent khớp UA — nếu chỉ tính agent khớp UA thì không phát hiện được trường hợp UA khai X nhưng IP thuộc dải Y.

7. `detectors/identity_verify.py`: **pure**, `kind='per_request'`, khai báo `min_schema_version = 3` — bundle ghi trước khi có `ip_range_match_json` (schema_version 1-2) phải trả `insufficient_data`, tuyệt đối không suy ra `verification_failed` từ cột NULL (NULL ≠ false). Đọc `bundle.user_agent` + `bundle.ip_range_match_json` + `bundle.rdns_result` + `bundle.signature_verify_status`. **Không đọc `ip_raw`** — bảo đảm replay chạy được trên bundle đã hết retention. Trả một trong 5 trạng thái identity. IO guard test phải pass.
8. Logic spoof: UA khớp agent X **và** registry có `range_source_url` cho X **và** `ip_range_match_json[X]` là false → `verification_failed`, claims thêm `spoofed=true`.
9. `scripts/control_group/`: 11 script. Kịch bản 11 gửi UA `GPTBot/1.0` từ máy local qua hostname public.
10. `run_all.py`: chạy tuần tự, gắn `test_run_id` riêng cho control group, xuất bảng kỳ vọng vs thực tế.

## Success Criteria

- [ ] Registry load được, có `registry_version`; đổi file → version tăng, ghi nhận trong snapshot.
- [ ] Mỗi agent map tới đúng file range riêng — test khẳng định GPTBot và ChatGPT-User dùng 2 nguồn khác nhau.
- [ ] Fetch range lỗi → giữ cache cũ, `fetch_status='stale_cache'`, verify vẫn chạy bằng dải cũ.
- [ ] Web Bot Auth verifier đúng spec: chứng minh bằng fixture ký bằng key test + vector lấy từ directory thật của vendor. Parser xử lý được cả dạng dictionary của `Signature-Agent`. (Chữ ký thật quan sát được là **observation item**, không phải acceptance — vendor có ký hay không nằm ngoài tầm kiểm soát của lab.)
- [ ] Chữ ký hết hạn → `expired`, không phải `valid`.
- [ ] Kịch bản control group 11 (GPTBot UA từ IP local) cho `verification_failed` + `spoofed_bot`.
- [ ] Control group chạy kịch bản verify cho cả 3 vendor OpenAI/Anthropic/Perplexity: IP đúng dải → `verified`; UA thuần không nguồn verify → `claimed_only`; sai dải → `spoofed_bot`.
- [ ] Kịch bản 9, 10 (curl, python-requests) không bị gán provider nào.
- [ ] `identity_verify` pass IO guard test của phase 4.
- [ ] Replay trên bundle cũ dùng đúng snapshot **set** gốc, không dùng dải hiện tại; truy ngược được từng agent thuộc set đó.
- [ ] Replay `identity_verify` trên bundle `schema_version=1` trả `insufficient_data`, không trả `spoofed_bot`.
- [ ] Replay chạy đúng trên bundle đã bị xoá `ip_raw` — test xoá `ip_raw` rồi replay, kết quả không đổi.
- [ ] `ip_range_match_json` chứa kết quả cho mọi agent có range source, không chỉ agent khớp UA.
- [ ] Bảng kỳ vọng vs thực tế của control group xuất được, mọi lệch đều có giải thích.

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| URL/schema file IP range vendor đổi | Parser khoan dung, fail → `stale_cache` không phải crash. Log cảnh báo. Verify URL từ nguồn gốc vendor, không từ blog bên thứ ba |
| Web Bot Auth còn là IETF draft, spec có thể đổi; vendor có ký hay không nằm ngoài tầm kiểm soát | Cô lập trong `webbotauth.py`, version hoá `signature_verify_status`. Acceptance chỉ đòi verifier đúng spec (fixture + vector thật); chữ ký thật là observation item |
| Bundle cũ thiếu cột mới (schema_version thấp) bị đọc nhầm NULL thành false → kết luận spoof sai | `min_schema_version` trên detector; bundle cũ hơn → `insufficient_data`. Test replay trên bundle v1 |
| Directory fetch mỗi request làm chậm | Cache theo domain, TTL vài giờ. Timeout ngắn, fail-open ghi `directory_unreachable` |
| Playwright-stealth không bị bắt → tưởng detector hỏng | Kịch bản 6 ghi rõ **không kỳ vọng** bắt được. Đây là giới hạn đã biết, không phải bug |
| IP verify sai do NAT/proxy | Lab traffic là AI vendor và script tự chạy, ít NAT. Ghi nhận `unattributed_fetch` cho IP không thuộc dải nào thay vì ép `spoofed` |
| `ip_raw` bị xoá sau 24h làm replay verify CIDR hỏng | Bước 6: `ip_range_match_json` niêm phong lúc request cho **mọi** agent có range source. Detector không đọc `ip_raw`. Test khẳng định replay chạy đúng trên bundle đã xoá `ip_raw` |
