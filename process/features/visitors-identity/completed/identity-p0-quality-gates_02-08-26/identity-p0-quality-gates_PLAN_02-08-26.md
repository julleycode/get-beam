# PLAN: Identity P0 quality gates

**Date:** 02-08-26  
**Feature:** visitors-identity  
**Mode:** `/cook` interactive — P0 quick wins  
**Status:** completed (archived 02-08-26; PM report `plans/reports/pm-260802-1818-identity-p0-quality-gates-complete-report.md`)  

## Goal

Giảm false-positive person-ID (case Janet/Danica + Private Relay) mà không đổi schema lớn, không thêm Fingerprint Pro / vendor pixel.

## Exact requirements (locked)

1. **Expected output**
   - Local Private Relay / known privacy-relay client IP → `identity_status=vpn_filtered`, không gọi paid person-graph, không tạo `IdentifiedVisitor`.
   - Paid graph result có `full_name` + `email` mâu thuẫn → không `_save_identified` (reject + log).
   - `is_emailable_identity("rb2b"|"leadpipe"|"capturify") is False`; owned/manual vẫn emailable.
   - Nhãn/skip copy không còn ám chỉ “RB2B identify bằng IP”; VPN message nêu Private Relay.

2. **Acceptance criteria**
   - `2a09:bac3::/32` (ví dụ `2a09:bac3:627a:3050::4d0:11`) → resolve stops with `vpn_filtered` **kể cả khi IPinfo thiếu/fail**.
   - Ingest **không** drop Private Relay (giữ `is_proxy_or_vpn` exclude `relay`).
   - Provider payload `{full_name: "Janet Valla", email: "danica_naluz@sftoyota.com"}` → save skipped.
   - `{full_name: "John Smith", email: "jsmith@acme.com"}` / `john.smith@…` → vẫn save được (heuristic không false-reject rõ ràng).
   - `is_emailable_identity("rb2b") is False`; `form_capture` / `svid_reconcile` / `fingerprint_match` / `manual` / `pdl_person_enrich` vẫn `True` (trừ agent/abuse flags).
   - Unit tests mới/updated xanh; không migration DB.

3. **Out of scope**
   - Fingerprint Pro, LiveRamp/UID2, vendor pixel PoC, bảng `identity_observations`.
   - Đổi enum status sang `provider_candidate` / `verified` (P1).
   - Backfill/xóa row Janet hiện có trên Lab (manual ops hoặc follow-up).
   - Luật 91 copy/UI consent rewrite.

4. **Constraints**
   - Không migration schema.
   - Fail-closed cho privacy-relay prefix local; IPinfo vẫn bổ sung.
   - Paid graphs vẫn có thể lưu `IdentifiedVisitor` để hiển thị candidate (status `identified`) nhưng **không emailable** — trừ khi name/email reject hoặc relay block chặn trước.
   - Leadpipe + Capturify cùng policy emailable với RB2B (cùng lớp probabilistic graph) — tránh lỗ hổng cùng kiểu.

5. **Touchpoints**
   - [`apps/api/services/company_resolver.py`](apps/api/services/company_resolver.py) — `is_privacy_relay_ip()` (prefix + optional ASN helpers)
   - [`apps/api/services/identity_resolver.py`](apps/api/services/identity_resolver.py) — gate trước paid graphs; name/email check trước `_save_identified` cho paid graphs
   - [`apps/api/services/identity_classification.py`](apps/api/services/identity_classification.py) — `EMAILABLE_PROVIDERS` / thu hẹp `is_emailable_identity`
   - [`apps/api/routers/visitors.py`](apps/api/routers/visitors.py) — skip message `vpn_filtered`
   - Tests: `tests/unit/test_identity_classification.py`, `tests/unit/test_company_resolver.py`, new `tests/unit/test_identity_quality_gates.py`

## Design

### A. Privacy-relay block (local, fail-closed)

```python
# company_resolver.py
_ICLOUD_PRIVATE_RELAY_V6_PREFIXES = ("2a09:bac3:",)  # CF egress for Apple Private Relay

def is_privacy_relay_ip(ip: str) -> bool:
    """True for known privacy-relay client IPs. Does NOT drop ingest."""
    ...
```

Trong `IdentityResolver.resolve()`, **trước** paid waterfall:

1. Nếu `is_privacy_relay_ip(ip)` → `vpn_filtered`, return (không cần IPinfo).
2. Else nếu IPinfo `is_ip_suspicious` (gồm `relay`) → như hiện tại.
3. IPinfo fail → vẫn an toàn nhờ bước 1 cho prefix đã biết.

### B. Name/email consistency reject

Helper `name_email_consistent(full_name, email) -> bool` trong `identity_classification.py` (hoặc module nhỏ cạnh đó):

- Normalize: lower, bỏ dấu nếu dễ, tách token name (len≥2), local-part email tách theo `[._+-]`.
- Consistent nếu: bất kỳ name token nào xuất hiện trong local-part **hoặc** bất kỳ local token (≥2) xuất hiện trong name (cover `jsmith` / `john.smith`).
- Nếu thiếu name hoặc thiếu email → không reject (provider có thể chỉ có một phía).
- Chỉ áp cho **paid graph providers**: `rb2b`, `leadpipe`, `capturify`. Không áp `form_capture` / owned (user tự gõ).

Trong `_save_identified` (hoặc ngay trước call từ graph path): nếu paid + both present + inconsistent → log `identity_rejected_name_email_mismatch`, return `None`, không set `identified`.

### C. RB2B (+ Leadpipe/Capturify) không emailable

```python
EMAILABLE_PROVIDERS = frozenset({
    "form_capture", "pdl_person_enrich", "manual",
    "fingerprint_match", "beam_identity_network", "svid_reconcile",
})
# rb2b / leadpipe / capturify remain PERSON_LEVEL for display/KPI level,
# but is_emailable_identity requires EMAILABLE_PROVIDERS.
```

`identity_level("rb2b")` vẫn `"person"` (dashboard “person-level candidate”); outreach/CRM/hot_alert dùng `is_emailable_identity` → False.

### D. Nhãn / copy

- `visitors.py` message: `"Skipped — visitor is behind a VPN, proxy, or privacy relay (e.g. iCloud Private Relay)."`
- Log keys: `resolution_skipped_privacy_relay` khi local prefix; giữ `resolution_skipped_vpn` cho IPinfo path.
- Không thêm string UI “IP path”. Comment trong `rb2b.py` nếu có: API branch = `rb2b_api` (ip_to_hem), không claim “identified by IP alone”.

## Phases

### Phase 1 — Relay + classification + reject helpers + tests
- [x] `is_privacy_relay_ip` + unit tests (IPv6 prefix; non-relay IPv4/IPv6 negative)
- [x] Wire gate in `identity_resolver.resolve`
- [x] `name_email_consistent` + reject in `_save_identified` for paid graphs
- [x] `EMAILABLE_PROVIDERS` + update `is_emailable_identity` + fix unit tests expecting `rb2b` emailable
- [x] Update vpn_filtered user-facing message
- [x] Unit tests for Janet/Danica reject + jsmith pass

### Phase 2 — Verify
- [x] Unit suite for identity gates: **172 passed**
- [x] Grep blast: callers of `is_emailable_identity` still correct
- [x] code-reviewer: PASS_WITH_CONCERNS (stale cadence test fixed; remaining concerns documented)

## Risks

| Risk | Mitigation |
|---|---|
| Prefix list thiếu range Private Relay khác | IPinfo `relay` vẫn cover khi token có; document follow-up |
| Heuristic name/email false-reject | Chỉ paid graphs; missing side = allow; unit cases jsmith/john.smith |
| KPI “identified” vẫn đếm RB2B | Chấp nhận P0; P1 tách provider_candidate |
| Existing Lab false-positive rows | Out of scope — manual clear hoặc script follow-up |

## Success metrics

- Case Private Relay không còn tạo person identity mới.
- Case name≠email local-part không còn save từ RB2B.
- Outreach/export không lấy RB2B-only identities.

## Next after P0 (not this cook)

P1 status model `provider_candidate` / `verified`; P2 Fingerprint Pro / vendor pixel benchmark.
