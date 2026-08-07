---
name: plan:ip-org-database
description: "Self-hosted IP-to-org database (CAIDA pfx2as + AS2Org) feeding the company-resolution ladder — Pillar 1 of the owned identity core"
date: 07-08-26
feature: visitors-identity
---

# Own IP-to-Company Database (Pillar 1) — CAIDA pfx2as + AS2Org pipeline

## Status (closeout 07-08-26)

- **Phase 1 — Schema + ingestion pipeline: ✅ COMPLETE.** Migration `a3e8d5c71f02`
  (chains off identity-coop's `f2c81a6b4d09`, landed same commit batch), model
  `ip_org_prefix.py`, `ip_org_ingest.py`, config (4 settings, flag OFF), scheduler wiring,
  CLI `scripts/refresh_ip_org.py` (+ fail-closed local-host guard, 15 tests). Evidence:
  `ip-org-database-evl-iteration-001_REPORT_07-08-26.md` (EVL 6/6 green after 1 fix cycle —
  camelCase `organizationId` defect, fixtures regenerated from real CAIDA records).
- **Phase 2 — Lookup integration: ✅ COMPLETE.** `ip_org_lookup.py` + resolver-ladder insert
  in `company_resolver.py` (write-through `company_graph` `source="rir_asn"` conf 0.45).
  Evidence: same EVL report + its **Addendum** — live dev-DB proof: full-chain apply from
  EMPTY DB (8s), live down/up round-trip `a3e8d5c71f02`↔`f2c81a6b4d09`, `--apply` loaded
  967,079 rows twice (341s/158s, swap + index-rename proven, crash-safety accidentally
  proven), GiST index scan warm 2-6ms / cold 26-385ms, longest-prefix at volume verified,
  org_kind: org 63.8% / eyeball 26.9% / datacenter 7.9% / cdn 1.4%.
- **Phase 3 — Domain mapping + quality: OPEN (next).** Not started. Until it ships,
  `resolve_company_cached` still returns None from the ip_org path for domain consumers;
  today's value is persisted `company_graph.company_name`.
- **Commits (devjulley, NOT pushed):** `3215fb0` (ip-org Phases 1-2) after `d78b4f1`
  (identity-coop phase 1, concurrent program — its `f2c81a6b4d09` is our migration parent).
- **Prod enable (operator gate, pending):** push → Railway auto-applies migrations → one real
  `--apply` ingest on prod → flip `ip_org_lookup_enabled`.
- **Follow-ups / known-gaps:** `../../backlog/ip-org-followups_NOTE_07-08-26.md` (single-
  transaction load optimization, skip-ratio alerting, alembic env.py guard gap, G6
  distribution audit, conftest enum-teardown race, 2 identity-coop-owned broken unit tests).
- Task folder stays in `active/` (Phase 3 open + operator gate pending).

## Context

Beam currently resolves company-from-IP via free rDNS (`socket.getfqdn`) then paid providers (PDL + IPinfo, ~$0.01/hit, budget-capped 50/day/site). Quality is inconsistent and every paid hit is rented data. Goal: own the IP→Company core by building a self-hosted reverse-IP database from public BGP/WHOIS-derived snapshots (CAIDA RouteViews `pfx2as` for prefix→ASN, CAIDA AS2Org for ASN→organization), joined, normalized, and served from Postgres with a `cidr` GiST index for <5ms lookups. Covers ~30-40% of B2B traffic (orgs with own IP allocations) with zero per-lookup cost.

Decisions already made by user: Pillar 3 (bidstream) deferred to backlog with a note; identity-coop Phase 1 (Pillar 2) stays untouched on its own program track.

## What already exists (reuse, don't rebuild)

- `apps/api/models/company_graph.py` — `CompanyGraphNode`, unique `(ip, source)`, read ordered by `confidence.desc()`. Already supports multiple coexisting sources per IP. New source value slots in with zero schema change.
- `apps/api/services/company_resolver.py:526` `resolve_company_cached` — the resolution ladder (graph-read → Redis → rDNS). New local lookup slots in here.
- `apps/api/services/company_resolver.py:343` `classify_org_kind` → `'datacenter'|'cdn'|'eyeball'` + `_DATACENTER_ASNS` / org-token frozensets — reuse as the ISP/eyeball filter instead of a GitHub blacklist.
- `apps/api/services/asn_lookup.py` — MaxMind GeoLite2-ASN mmdb already wired (lazy reader, fail-open). Useful cross-check, not replaced.
- Job patterns to copy exactly:
  - `apps/api/services/agent_ip_range_refresh.py` — fetch → normalize → fail-open, per-source try/except, httpx with timeout.
  - `apps/api/services/proxy_ptr_sweep.py:11-15` — trigger-agnostic core, own session, **Postgres advisory lock** (single-flight across replicas), `dry_run` support, status-dict return, thin CLI script + APScheduler wiring same function.
  - `apps/api/jobs/scheduler.py:497` — APScheduler is the live scheduler (Celery beat is dormant by design — do NOT use it).
  - `apps/api/jobs/backfill_enrichment.py` — CLI `--apply`/`--limit` dry-run-default precedent.
- `requirements.txt` already has `httpx`, `dnspython`, `geoip2` — **no new dependencies needed** (no Pandas/PySpark; files are line-parseable streaming).

## Deviations from the user's architecture spec (and why)

1. **No separate VPS worker / no standalone API layer.** Ingestion runs as an APScheduler job inside the existing Railway API process (same as agent_ip_range_refresh); lookup is an internal service call inside `company_resolver`, not a new HTTP service. Repo has one deploy target; a sidecar contradicts `orchestration.md` research-first rule and adds ops surface for zero gain at current scale.
2. **Streaming parse, not Pandas.** `pfx2as` is ~1M lines of `prefix\tlen\tasn`; AS2Org jsonl is ~100k lines. Plain-Python line streaming + dict join fits in <500MB RAM.
3. **Tag ISP/eyeball rows, don't drop them.** Store everything with an `org_kind` column; the lookup filters `org_kind = 'org'`. Keeps the dataset usable for abuse/datacenter detection (existing `is_datacenter_ip` consumers) and lets the filter policy change without re-ingesting.
4. **Wikidata domain mapping = Phase 3, not day one.** Full Wikidata dump is 100GB+ — impractical. Phase 3 uses targeted extraction (SPARQL paged query for org→official-website, or lazy per-org resolution cached in the table). Phases 1-2 ship org-name-only with `domain` nullable.
5. **Longest-prefix match required.** `WHERE ip_range >>= :ip` returns ALL containing prefixes (e.g. /8 and /24). Query must `ORDER BY masklen(ip_range) DESC LIMIT 1`. The user's spec query alone is incorrect without this.

## Risk to verify BEFORE building (Phase 1 step 0)

**CAIDA licensing.** CAIDA pfx2as and AS2Org datasets carry an Acceptable Use Policy; commercial use may require permission/registration. Verify before wiring downloads. Fallback stack if CAIDA commercial use is not cleanly permitted (functionally equivalent, fully open):
- prefix→ASN: build from RouteViews raw RIB dumps (public) via `pyasn`-style parse, or RIPE RIS dumps
- ASN→org: RIR delegated-extended stats (all 5 RIRs, open FTP) + RDAP for names
This changes only the fetch/parse step; schema, join, and lookup are identical.

## Phases

### Phase 1 — Schema + ingestion pipeline (flag OFF, no consumer)

**New migration** (chain off live head — re-run `alembic -c apps/api/alembic.ini heads` at write time; head moves daily):

Table `ip_org_prefixes` (+ repo conventions: UUID `id`, `created_at`, `updated_at`):
- `prefix` — `postgresql.CIDR`, indexed **GiST** (`postgresql_using='gist'`, opclass `inet_ops`)
- `asn` — Integer, indexed
- `org_name` — String(200) (normalized)
- `org_name_raw` — String(200) (as-published, for debugging joins)
- `domain` — String(253), nullable (Phase 3 fills)
- `org_kind` — String(20): `'org' | 'eyeball' | 'datacenter' | 'cdn'` (from `classify_org_kind` + AS2Org org fields)
- `source` — String(50) (`'caida_pfx2as'`), `dataset_date` — Date

**New service `apps/api/services/ip_org_ingest.py`** (mirror `proxy_ptr_sweep` shape):
- `refresh_ip_org_dataset(dry_run=False)` — advisory lock; download pfx2as (gzip) + AS2Org (jsonl) via httpx (timeout, per-source try/except, fail-open keeps old data); stream-parse; join on ASN; normalize org names (strip legal suffixes Inc/Corp/LLC/Ltd/GmbH…, lowercase, collapse whitespace — pure function, unit-testable); classify `org_kind`; bulk-load into `ip_org_prefixes_staging` then transactional swap (rename) so lookups never see a half-loaded table; return status dict (rows, skipped, dataset_date, duration).
- IPv4 first; IPv6 pfx2as variant is a follow-up flag.

**Config additions** (`apps/api/config.py`, all default-safe):
- `ip_org_lookup_enabled: bool = False` (operator-gated, matching `company_graph_enabled` posture)
- `ip_org_dataset_pfx2as_url`, `ip_org_dataset_as2org_url`
- `ip_org_refresh_interval_hours: int = 24`

**Wiring:** APScheduler `add_job` in `apps/api/jobs/scheduler.py` (interval + jitter, gated on flag) + thin CLI `scripts/refresh_ip_org.py` (dry-run default, `--apply`).

**Tests (unit):** parser fixtures with real-format snippets of pfx2as and AS2Org lines; normalization table-driven cases (MICROSOFT-CORP / Microsoft Corporation / Microsoft Ireland → same key); join correctness; eyeball tagging. **Tests (integration):** staging-swap atomicity; GiST longest-prefix query returns /24 over /8; ~10k-row load timing sanity.

### Phase 2 — Lookup integration into the resolver ladder

**New service `apps/api/services/ip_org_lookup.py`:**
- `lookup_ip_org(db, ip) -> {org_name, domain, asn, org_kind} | None`
- Query: `SELECT ... WHERE prefix >>= :ip AND org_kind = 'org' ORDER BY masklen(prefix) DESC LIMIT 1`
- Fail-open (`None` on any error), never raises into the resolver.

**Ladder change in `company_resolver.py` `resolve_company_cached`:** graph-read → Redis → rDNS → **NEW: local ip_org lookup (when `ip_org_lookup_enabled`)** → give up. rDNS stays first: a resolving PTR is more specific (yields real domain). On local hit: write-through to `company_graph` with `source="rir_asn"`, `confidence=0.45` (below rdns 0.5 and paid 0.7 — coarser signal; graph's `confidence.desc()` read means better sources naturally shadow it), and — first source ever to do so — populate `company_graph.company_name` (column exists, never written today).
- Paid-path effect: `identity_resolver.py` PDL/IPinfo IP-company calls now only fire when both rDNS AND local lookup miss → direct paid-call reduction, measurable.

**Tests:** unit (ladder ordering, flag-off inertness, fail-open); integration (end-to-end resolve with seeded prefixes, write-through row shape, longest-prefix vs shadow-confidence interplay).

### Phase 3 — Domain mapping + quality (separate follow-up plan, sketch only)

- Org-name→domain via targeted Wikidata SPARQL extraction (paged, orgs with `official website`), joined on normalized name; OR lazy per-org resolution using existing Hunter domain-search mixin, cached into `ip_org_prefixes.domain`.
- Quality metric job: % of real resolved visitors whose company came from `rir_asn` vs rdns vs paid (reads `company_graph.source`) — proves the paid-call reduction claim.
- IPv6 dataset.

### Backlog note (write during this work's UPDATE PROCESS)

`process/features/visitors-identity/backlog/bidstream-intent-data_NOTE_07-08-26.md` — Pillar 3 deferred: GDPR/consent-basis risk, million-QPS infra, brand conflict (anti-bot). Revisit conditions: legal counsel + scale.

## Files touched (summary)

| File | Change |
|---|---|
| `apps/api/migrations/versions/<new>_add_ip_org_prefixes.py` | new table + GiST index (staging twin created in-service, not migration) |
| `apps/api/models/ip_org_prefix.py` | new model |
| `apps/api/services/ip_org_ingest.py` | new — download/parse/join/normalize/swap |
| `apps/api/services/ip_org_lookup.py` | new — longest-prefix lookup |
| `apps/api/services/company_resolver.py` | ladder insert + write-through call (small diff) |
| `apps/api/config.py` | 4 new settings, default OFF |
| `apps/api/jobs/scheduler.py` | one `add_job` |
| `scripts/refresh_ip_org.py` | new CLI |
| `tests/unit/test_ip_org_ingest.py`, `tests/unit/test_ip_org_lookup.py` | new |
| `tests/integration/test_ip_org_pipeline.py` | new |
| `process/features/visitors-identity/backlog/bidstream-intent-data_NOTE_07-08-26.md` | new backlog note |

Feature routing: `process/features/visitors-identity/active/ip-org-database_07-08-26/` (task folder per plan-lifecycle convention).

## Verification

1. `.venv/bin/python3.11 -m pytest tests/unit/test_ip_org_ingest.py tests/unit/test_ip_org_lookup.py -x` (note broken pytest shebang — use `python3.11 -m pytest`).
2. Integration lane vs Docker Postgres: staging swap + GiST longest-prefix + resolver ladder tests.
3. Manual: `scripts/refresh_ip_org.py` dry-run against live CAIDA URLs (or fallback sources) — confirm parse counts (~1M prefixes, ~100k orgs) and RAM stays bounded.
4. `EXPLAIN ANALYZE` the lookup query on the loaded table — confirm GiST index scan, <5ms.
5. Offline `alembic --sql` both directions with explicit `<from>:<to>` range (repo gotcha: unscoped offline fails mid-chain).
6. Flag stays OFF; enabling in prod is a separate operator action after migration live-apply (matches `company_graph_enabled` precedent).

## Constraints

- Do not touch identity-coop files (uncommitted Phase 1 work in same worktree — `models/identity_coop.py`, `services/identity_coop.py`, its migrations/tests, and the modified `identity_resolver.py` hunks). New migration must NOT chain off identity-coop's uncommitted `e7b3d5f19c46`/`f2c81a6b4d09` unless they land first — re-derive head at write time and coordinate.
- No new Python dependencies.
- CAIDA license verification is step 0 — if unclear for commercial use, switch to RouteViews-raw + RIR delegated-stats fallback before writing the fetch code.
