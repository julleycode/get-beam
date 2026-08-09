---
phase: ip-org-quality-pack-execute
date: 2026-08-08
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/ip-org-quality-pack_08-08-26/ip-org-quality-pack_PLAN_08-08-26.md
---

# IP-Org Quality Pack — EXECUTE Report

Executed in the mandated order A → C → D → E → B. Gate status entering EXECUTE:
CONDITIONAL, user-accepted (A2, carrying E1–E21).

## What Was Done (per workstream)

### WS-A — post-swap ANALYZE + skip-ratio guard — CODE DONE + G3 (scoped) run
- `apps/api/config.py`: +`ip_org_skip_warn_ratio` (0.25), `ip_org_skip_abort_ratio` (0.40), with baseline-rationale comment (+13 lines).
- `apps/api/services/ip_org_ingest.py`:
  - post-swap `ANALYZE "ip_org_prefixes"` in its OWN txn BETWEEN `db.commit()` (:437) and fusion-cache invalidation (E1), try/except-swallowed (+14 lines).
  - `skip_ratio = skipped/len(prefixes)` (1.0 when empty), added to `ip_org_ingest_parsed` log + summary; `ip_org_ingest_skip_ratio_high` warn; abort branch after `dry_run` return and before `if not rows`, before the advisory lock (A3/A4).
- `tests/unit/test_ip_org_ingest.py`: `TestSkipRatioGuard` 5-case matrix (0% / 13% / 30% warn / 45% abort-never-swaps / empty→1.0 abort).
- A5/KG-5: RIR leg has NO offered-row denominator — the guard is CAIDA-only, DESCOPED as a fact (no RIR counter invented). Backlog stub written.

### WS-C — retain as2org organizationId — CODE DONE + G11 round-trip
- `apps/api/models/ip_org_prefix.py`: +`as2org_org_id` String(64) nullable, unindexed (+9 lines).
- `apps/api/migrations/versions/d3f9a1c25e84_add_ip_org_as2org_org_id.py`: NEW additive migration; live head re-derived at EXECUTE = `c4a8f13e07b6` (E3, `DATABASE_URL` pinned localhost:5433 — NOT trusting the written hash); chains off it.
- `ip_org_ingest.py`: `parse_as2org` → `dict[int, tuple[str, str]]`; `build_org_family_kinds` (fold precedence cdn>datacenter>eyeball>org) + `resolve_row_kind` (inherit only when own=='org', R9); row loop writes `as2org_org_id` + org-family inheritance + `family_reclassified`; `multi_asn_families`/`multi_asn_family_fraction` counters (C4/C4a/C5); chunk-dict `"as2org_org_id": None` default BEFORE `**row` splat + INSERT column list (E2, shared with RIR job).
- Tests: updated existing `parse_as2org` assertions to tuple shape; `TestOrgFamilyClassification` (promote/no-demote/no-lateral/size-1/never-to-org, all fixture ASNs 64512–65534 per P2-10); `TestMultiAsnFamilyCounters`.

### WS-D — `_extract_domain` via Public Suffix List — CODE DONE
- `apps/api/data/public_suffix_list.dat`: vendored, 16409 lines, licence header intact. Source `https://publicsuffix.org/list/public_suffix_list.dat`, fetched 2026-08-08.
- `apps/api/services/public_suffix.py`: NEW pure module — `_load_rules` (`@lru_cache`, ICANN-section-only per Q10), `registrable_domain` (longest-suffix match, `*` wildcards, `!` exceptions, implicit `*`).
- `apps/api/services/company_resolver.py`: `_extract_domain` now calls `registrable_domain`; the early two-part-TLD `return` DELETED so every result flows through both filters (Q11); import added.
- Tests: `test_public_suffix.py` (group i incl. ICANN amazonaws proof, R12); `test_company_resolver.py` +group iii (newly-rejected: talktalk/virgin domain-filter subclass + `dhcp-1-2-3.acme.co.uk` hostname-filter-only subclass P2-12 + corrected gov.br/co.za) +group iv (newly-widened: google.co.uk/bbc.co.uk/acme.com.au/x.co.uk).
- D4 census (three tokens incl. `resolve_company_cached`): see below. No hard dependency → no BLOCK.

### WS-E — APNIC eyeball ASN list — CODE DONE + G18 shape observed
- `apps/api/config.py`: +`ip_org_eyeball_min_users` (50_000), `ip_org_apnic_refresh_enabled` (False), `ip_org_apnic_url`, `ip_org_apnic_refresh_interval_hours` (168), `ip_org_apnic_max_bytes` (32 MB).
- `apps/api/services/apnic_eyeball_refresh.py`: NEW — `parse_aspop` (tolerates keyed-object + bare-list, skips junk), `_fetch_capped` (streamed max-bytes cap), `refresh_apnic_eyeball_asns` (mock short-circuit, fail-open), `load_eyeball_asns` (`@lru_cache`, runtime-else-vendored, threshold filter).
- `apps/api/data/apnic_eyeball/eyeball_asns.json`: vendored initial snapshot (24403 ASNs at Users≥1000; 3330 at ≥50k), 393 KB.
- `ip_org_ingest.py`: `classify_ip_org_kind` APNIC numeric pre-check with direction guard (Q8/E3); +`telekom` token (E13/R11 — only genuinely-new stem; telkom/wireless/telecom/mobile already present).
- `apps/api/jobs/scheduler.py`: `_apnic_eyeball_refresh_job` wrapper + flag-guarded registration copied from the `:733-766` pattern (E4).
- Tests: `test_apnic_eyeball_refresh.py` (parser both shapes/junk, threshold boundary 49999/50001/50000, fail-open missing/corrupt, mock no-network, `cache_clear` per E6a); `TestApnicEyeballPreCheck` (in-set→eyeball, datacenter/cdn win, out-of-set unchanged, E6b discriminating AS-prefix case AS13335+"Example Holdings"→cdn).
- Scheduler count gate updated 22→23 / 20→21 interval per its own re-derive-the-arithmetic instruction.

### WS-B — benchmark corpus + precision measurement — CODE DONE; prod gates NEEDS-OPERATOR
- `scripts/build_ip_org_benchmark.py`: NEW read-only PROD extraction — explicit DSN required (never `settings.database_url`), `SET SESSION … READ ONLY` + `SET TIME ZONE 'UTC'`, two-column join (R3), agent-origin/human-only predicates hand-inlined (C-30/E17 option c, with sync pointer to `agent_visitor_filters.py:19`), B2b MATERIALIZED CTE + octet-strict IPv4 regex before any `::inet` cast (P1-5), events-derived IP via per-row COALESCE with the same strict/private/`<>''`/CF-cutoff predicates and last-seen fallback (C-22/E11/KG-8), explicit projection `split_part(email,'@',2)` — NEVER bare `email` (C-33/E15), `FREE_MAIL_EXCLUDE = _GENERIC_DOMAINS + addendum − {linkedin.com,x.com}` (B2a/C-26), `label_root`/`expected_org_for` via WS-D `registrable_domain` (P1-2), `DISTINCT ON (ip_address)` on the OUTER query, `stratum='pending'`, `--count-only` for B1.
- `scripts/measure_ip_org_precision.py`: NEW LOCAL-only measurement — refuses non-local DSN, in-process `settings.ip_org_lookup_enabled = True` (Q12; `ip_org_fusion_enabled` deliberately untouched), FAILED-INVALID non-vacuity precondition, own unfiltered stratum query with `, id` tie-break (Q14/P2-8), duplicate-prefix probe gating the `v1==v2` invariant (E19/C-28), single-arm precision + separate coverage (P1-3), 7-value calibration table (P1-1), accuracy by v2_classification over all FOUR values incl. `unclassified` (P2-9/C-34), per-arm None-rate (R6), C-17b limitations, scores `org_name`/`organization`, never `domain` (R2).
- `.gitignore`: corpus TSV path added.
- Tests: `test_ip_org_benchmark.py` — Q5 matcher matrix (G7), `label_root`, `FREE_MAIL_EXCLUDE`.

## Test Gate Outcomes (verbatim)

- **G1+G2** (skip-ratio matrix + abort-never-swaps): `TestSkipRatioGuard` 5 passed.
- **G3** (post-swap ANALYZE): SCOPED run — `ANALYZE "ip_org_prefixes"` clean; `EXPLAIN (ANALYZE)` on `prefix >>= inet '8.8.8.8' AND org_kind='org'` uses `Index Scan using idx_ip_org_prefixes_prefix_gist` with fresh stats; warm timing 3.28/3.51/3.64/4.67/6.95 ms (p95 ≈ 6.95 ms < 15 ms budget). NOT a full `--apply` swap (avoided to not wipe the local corpus WS-B needs and a multi-minute CAIDA re-download); the ANALYZE statement run IS the exact one `_load_staging_and_swap` issues.
- **G4** (B1 population count): NEEDS-OPERATOR (prod read-only DSN; PII surface).
- **G5** (corpus privacy static check): `grep -nE 'SELECT…email'` returns NONE; every email ref is `split_part`. PASS. (TSV `@`-count + `git check-ignore` run at extraction time.)
- **G6** (read-only session): PASS — probe `CREATE TEMP TABLE` raised `ReadOnlySQLTransactionError` against localhost:5433; extract/count SQL parsed valid (prepare reached name-resolution).
- **G7** (matcher matrix): `test_ip_org_benchmark.py` 13 passed.
- **G8** (measurement non-vacuous): NEEDS-OPERATOR (depends on the prod extraction corpus).
- **G9/G10/G12** (parse_as2org / family / counters): passed within `test_ip_org_ingest.py` 42 passed.
- **G11** (migration up/down/up): PASS against localhost:5433; `as2org_org_id` present, nullable, varchar(64).
- **G13** (PSL matrix): `test_public_suffix.py` 15 passed.
- **G14** (D4 census + old-rejections): census recorded (below); old ISP/VPN/residential/cloud tests still green.
- **G21** (newly-rejected both subclasses): passed in `test_company_resolver.py` 70 passed.
- **G22** (newly-widened): passed in `test_company_resolver.py`.
- **G15/G16/G17** (APNIC parser/threshold/direction-guard + discriminating prefix): `test_apnic_eyeball_refresh.py` + `TestApnicEyeballPreCheck` 13 passed.
- **G18** (APNIC live shape): observed 2026-08-08 (verbatim below).
- **G19** (full unit lane): baseline 1605 passed / 2 skipped (run before first edit). After: **1657 passed / 2 skipped / 886 deselected, 0 failed**.
- **G20** (integration lane): `test_ip_org_pipeline.py` 21 passed against localhost:5433.

## AGENT-PROBE — APNIC response shape (G18, recorded before any field name)

Endpoint: `https://stats.labs.apnic.net/cgi-bin/aspop?f=j` (2026-08-08). Top-level
object: `{copyright, description, Date, Window, Data:[…]}`. Each `Data` record:
`{rank:int, AS:int, Description:str, CC:str, Users:int, "Percent of CC Pop":float,
"Percent of Internet":float, Samples:int}`. Load-bearing field names committed to code:
`AS` and `Users`. Total records observed: 44999.

## D4 caller census (three tokens)

`grep -rn "_extract_domain\|resolve_company_from_ip\|resolve_company_cached" apps/api tests scripts`:
- (a) domains D3 STOPS producing: `resolve_company_from_ip` → `company_graph` (source="rdns"); via `resolve_company_cached` (`visitor_aggregator.py:774`) → `visitors.company_domain` + `companies`. Both narrowing subclasses (i) ISP brands and (ii) hostname-filter-only real corporate domains. No consumer REQUIRES those rows to keep appearing.
- (b) domains D3 CHANGES (gov.br→bar.gov.br): same consumers; none keys/caches/dedupes on the old public-suffix string.
- (c) domains D3 NEWLY produces (WIDENS, highest volume): same write-through paths; additive volume accepted on `company_graph`/`visitors.company_domain`/`companies`.
- Accepted cache lag (Q15/KG-6): Redis `company_ip` 30d + `company_graph` 75d keep serving old-logic values on live reads. No hard dependency → WS-D not BLOCKED.

## Plan Deviations (all within blast radius)

1. **WS-D `*.ck` D5 cell vs D2 spec (E8/FAIL-3).** D5 cell states `a.b.ck → b.ck`; the D2 spec ("public suffix + exactly one more label") and the real eTLD+1 yield `a.b.ck`. Per FAIL-3 precedence the D2 spec wins; implemented and tested as `a.b.ck → a.b.ck`, surfaced here (not silently resolved).
2. **WS-C multi-ASN counter fixture (G12) uses one real datacenter ASN (14061).** Through `parse_as2org` all ASNs in a family share ONE org NAME, so token classification is identical family-wide — a genuine reclassification requires an ASN-SET difference. Fixture uses AS14061 (DigitalOcean, `_DATACENTER_ASNS`) + a reserved-range org sibling. Immune to WS-E's APNIC flip (P2-10) via the E3 direction guard. The pure `resolve_row_kind`/family tests (G10) remain reserved-ASN-only.
3. **WS-B prod-read gates NEEDS-OPERATOR.** B1/G4 count, B3 extraction, B5/G8 measurement read production customer PII via the `.env` Supabase-prod DSN. Per the task's explicit hard constraint and the high-risk execution-handoff protocol, the scripts are built and all non-prod gates run, but the prod read was NOT executed autonomously. No data faked.
4. **G3 scoped** (ANALYZE + EXPLAIN on the loaded local corpus, not a full destructive `--apply` swap) — see Test Gate Outcomes.
5. **WS-B events-derived IP** implemented as a per-row COALESCE (events-preferred, `visitors.ip_address` last-seen fallback) rather than a wholesale one-or-other; honest per-row provenance, KG-8 documents the fallback path.

## Test Infra Gaps Found

- Docker Desktop went DOWN mid-session (containers on 5433/6379 dropped); restarted via `open -a Docker`, daemon back in ~10s, corpus volume persisted. Not a code issue.
- Local dev DB has ip_org tables + corpus (1.23M rows / 616,896 route_origin org) but NOT the full app schema (`identified_visitors` absent locally) — so WS-B extraction SQL is prod-only, validated to parse but not run locally.

## WS-B population count + go/no-go outcome

NOT DETERMINED — B1 count requires the prod read (NEEDS-OPERATOR). Go/no-go floor
(≥80 PREDICTED rows, stratum `org`, P1-4) deferred to the operator run of
`build_ip_org_benchmark.py --count-only` then `--limit 600` then
`measure_ip_org_precision.py`. WS-B code is complete and its non-prod gates (G5/G6/G7) pass.

## Closeout Packet

- Selected plan: `process/features/visitors-identity/active/ip-org-quality-pack_08-08-26/ip-org-quality-pack_PLAN_08-08-26.md`
- Finished: WS-A/C/D/E CODE DONE, all Fully-Automated gates green, G3/G11/G20 Hybrid run locally, G18 observed.
- Verified vs unverified: unit 1657/0, integration 21/0, migration round-trip, GiST warm p95 6.95 ms. UNVERIFIED: WS-B prod extraction + precision measurement (NEEDS-OPERATOR); full post-`--apply` swap ANALYZE (KG-4).
- Remaining: operator runs the WS-B prod-read trio; VERIFIED marks on WS-A/C/D/E await user confirmation of Hybrid evidence (plan Phase Completion Rules).
- Best next state: keep plan ACTIVE (WS-B measurement + `✅ VERIFIED` confirmations pending); then ENTER UPDATE PROCESS to archive.

## Forward Preview

- **Test Infra Found:** APNIC vendored set (393 KB) + PSL (240 KB) now in `apps/api/data/`; WS-B scripts are reusable measurement instruments.
- **Blast Radius Changes:** `apps/api` only — `ip_org_ingest.py`, `company_resolver.py`, `config.py`, `models/ip_org_prefix.py`, `jobs/scheduler.py`, 2 new services, 2 new data files, 1 migration, 2 new scripts, 5 test files. `ip_org_rir_ingest.py` + `visitor_aggregator.py` untouched (READ-ONLY, E7).
- **Commands to Stay Green:** `.venv/bin/python -m pytest tests/unit/test_ip_org_ingest.py tests/unit/test_public_suffix.py tests/unit/test_apnic_eyeball_refresh.py tests/unit/test_company_resolver.py tests/unit/test_ip_org_benchmark.py -q`; integration `DATABASE_URL=<localhost:5433> .venv/bin/python -m pytest tests/integration/test_ip_org_pipeline.py -q`.
- **Dependency Changes:** none — no new Python deps.
</content>
