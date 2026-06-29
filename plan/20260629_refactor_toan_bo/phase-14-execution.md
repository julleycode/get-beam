# Phase 14 — Tách identity_resolver.py (execution plan)

> Behavior-exact. KHÔNG đổi hành vi, KHÔNG sửa bug. Chỉ di chuyển code.
> Nhánh: `refactor/p14-identity-resolver` (KHÔNG push main).

## Mục tiêu
`apps/api/services/identity_resolver.py` (1574 dòng) → package `identity_providers/` theo provider,
dùng **mixin** để giữ y nguyên `self.*` (tên method + chữ ký + thứ tự gọi không đổi).

## Ràng buộc bất biến (đã verify bằng grep)
- `IdentityResolver(db, redis_client=None)`, `.resolve()`, `.check_daily_budget()`, `.was_recently_attempted()` — giữ nguyên.
- `routers/demo.py` gọi thẳng 7 method private: `_call_leadpipe_api`, `_call_capturify_api`,
  `_call_rb2b_api`, `_call_pdl_ip_enrich`, `_call_ipinfo_api`, `_call_hunter_api`, `_call_apollo_api`
  → tất cả phải còn trên class (qua mixin).
- `tests/test_url_to_host.py` import module-level `_url_to_host` từ `identity_resolver` → re-export.
- `tests/unit/test_identity_resolver_parallel.py` patch `identity_resolver.settings` + `IdentityResolver._GRAPH_TIMEOUT == 5.0`
  → giữ `settings` + `_GRAPH_TIMEOUT` trong module/class chính. (Test này mock các `_call_*` nên provider tách ra không ảnh hưởng.)
- `tests/unit/test_identity_enrich_correctness.py` gọi `r._record_matches_visitor(...)` → MatchingMixin.

## Cấu trúc đích
```
apps/api/services/
  identity_resolver.py            # orchestrator + state + persistence + re-exports
  identity_providers/
    __init__.py
    base.py        # consts + _is_transient_http_error + _url_to_host + _http_retry + HttpRetryMixin(_raise_if_transient)
    matching.py    # MatchingMixin: _parse_record_timestamp/_visitor_activity_utc/_record_matches_visitor + consts
    leadpipe.py    # LeadpipeMixin
    capturify.py   # CapturifyMixin
    rb2b.py        # RB2BMixin
    pdl.py         # PDLMixin (_enrich_email_pdl + _call_pdl_ip_enrich)
    ipinfo.py      # IPinfoMixin (+ _ORG_DOMAIN_MAP/_ISP_KEYWORDS)
    hunter.py      # HunterMixin
    apollo.py      # ApolloMixin
```

`class IdentityResolver(Leadpipe, Capturify, RB2B, PDL, IPinfo, Hunter, Apollo, Matching, HttpRetry)`.

## Còn lại trong identity_resolver.py
`__init__`, `_site_domain`, `check_daily_budget`, `was_recently_attempted`, `_count_identified_for_domain`,
`_is_email_opted_out`, `_check_prior_signals`, `resolve`, `_resolve_identity_graphs_parallel`,
`_resolve_ip_company_parallel`, `_redis_has_key`, `_save_identified`, `_upsert_beam_identity`,
`_check_beam_identity_network`, `_log_resolution`, `_GRAPH_TIMEOUT`.

## Checkpoint
- [ ] `pytest tests/unit -q` xanh (đặc biệt test_identity_resolver_parallel, test_identity_enrich_correctness, test_optout, test_url_to_host)
- [ ] `pytest tests/integration -q` (resolution_budget, suppression_list, pii_dual_write, optout_flow, visitor_resolve_endpoint)
- [ ] import smoke: `python -c "from apps.api.services.identity_resolver import IdentityResolver, _url_to_host"`
- [ ] `./scripts/e2e-local.sh` (DB local) — trước khi merge
- [ ] So `resolve()` 1 visitor mẫu trước/sau = y hệt
- [ ] PR Railway env smoke-test → mới merge main
