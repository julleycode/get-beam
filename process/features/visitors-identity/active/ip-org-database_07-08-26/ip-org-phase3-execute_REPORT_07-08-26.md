---
phase: ip-org-phase-3-evidence-graph
date: 2026-08-07
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/ip-org-database_07-08-26/ip-org-phase-3-evidence-graph_PLAN_07-08-26.md
---

# IP-Org Phase 3 — EXECUTE report

**TL;DR** — WS1+WS2+WS3+WS4-fusion shipped and gate-green: 18 of 18 in-scope gates pass, the unit
lane is 1605 passed / 0 failed (baseline was 2 failed), and all three evidence sources are loaded
live on `localhost:5433` (967,261 CAIDA + 262,238 RIR + 755,538 ROAs). The WS4 domain leg was
skipped per E14 (Decision 2 = Option B). Two real defects were found by live gates and fixed; one
new finding (post-swap planner statistics) is recorded rather than silently fixed. All four flags
ship OFF.

## What Was Done

### Scope split (E14 — recorded as instructed)

Decision 2 resolved to **Option B**, so WS4 item 18 and its gates were skipped entirely:

| Skipped per E14 | Status |
|---|---|
| `ip_org_domain_map` table + model | not created |
| `apps/api/services/ip_org_domain_map.py` (`resolve_org_domain`, D14 slug, C-a) | not written |
| `ip_org_domain_mapping_enabled` / `ip_org_domain_lookup_daily_budget` / `ip_org_domain_max_attempts` | not added |
| G18 (DNS budget), G19 (coverage), G20 (false-positive floor) | not run |
| AC4.7, AC4.8, AC4.9, AC4.10, AC4.11, AC4.11b, AC4.12, AC4.13 | not applicable |
| E11, E12, E13 | moot — no domain code exists |

Verified mechanically: `grep -rn "ip_org_domain_map\|resolve_org_domain\|heuristic_uncorroborated" apps/ tests/ scripts/` → **0 matches**. No C-b code shipped (E11 satisfied vacuously and deliberately).
`OrgHypothesis.domain` is present in the TypedDict but always `None`, so the follow-on plan can fill it without a contract change.

### Files created (10)

| File | Lines | Purpose |
|---|---|---|
| `apps/api/migrations/versions/c4a8f13e07b6_add_ip_org_evidence_graph.py` | 138 | 3 evidence columns + asn NULLABLE + index + backfill + `rpki_roas` |
| `apps/api/models/rpki_roa.py` | 74 | `rpki_roas` model, own lock key |
| `apps/api/services/ip_org_rir_ingest.py` | 254 | RIR delegated-extended parse + refresh |
| `apps/api/services/rpki_ingest.py` | 233 | rpki.json streamed fetch + parse + swap |
| `apps/api/services/rpki_validate.py` | 76 | RFC 6811 three-state validation (pure) |
| `apps/api/services/ip_org_fusion.py` | 297 | weight table, clamp, D12 classification, corpus cache (pure) |
| `tests/unit/test_ip_org_fusion.py` | 293 | AC4.1-4.4, AC4.2a |
| `tests/unit/test_rpki_validate.py` | 81 | AC3.1 |
| `tests/unit/test_ip_org_rir_ingest.py` | 207 | AC2.1, AC2.2, AC2.5, AC2.6 |
| `tests/unit/test_rpki_ingest.py` | 245 | AC3.4 + 4-byte ASN regression |

### Files modified (10)

| File | +lines | Change |
|---|---|---|
| `apps/api/models/ip_org_prefix.py` | +59 | 3 columns, 4th index, `RELATIONSHIP_TYPES`, `IP_ORG_WRITE_LOCK_KEY`, asn nullable |
| `apps/api/services/ip_org_ingest.py` | +85 | shared lock, `carry_over`, evidence fields, 4th `_INDEX_TARGETS`, source-count log, cache invalidation |
| `apps/api/services/ip_org_lookup.py` | +108 | `lookup_ip_org_v2` (v1 untouched) |
| `apps/api/services/company_resolver.py` | +31 | fusion branch only |
| `apps/api/config.py` | +45 | 9 settings, all OFF/safe |
| `apps/api/jobs/scheduler.py` | +52 | 2 flag-gated jobs |
| `apps/api/models/__init__.py` | +4 | register `RpkiRoa` |
| `scripts/refresh_ip_org.py` | +35 | `--source {caida,rir,rpki,all}` |
| `tests/integration/test_ip_org_pipeline.py` | +266 | carry-over, lock serialization, index names, v2 end-to-end |
| `tests/unit/test_ip_org_lookup.py` | +264 | v2, org_kind isolation, fusion branch |
| `tests/unit/test_scheduler_job_config.py` | (arithmetic) | E20 re-derived 20/18/2 → 22/20/2 per that gate's own instruction |

### D13 12-touchpoint walk (all confirmed)

1 model ✅ · 2 migration ✅ · 3 row builder `asn=None` ✅ · 4 AC2.5 test ✅ · 5 `IpOrgMatch.asn`
NON-touchpoint ✅ (v1 filters `org_kind='org'`) · 6 `_LOOKUP_SQL` NON-touchpoint ✅ · 7 btree index
NON-touchpoint ✅ · 8 staging `LIKE` inherits nullability ✅ (proven by the live RIR load) ·
9 fusion never reads `rir_row["asn"]` ✅ (test asserts the key is absent entirely) · 10 v2 holder
query has no asn predicate ✅ · 11 integration `_rir_row` NULL-asn fixture added ✅ ·
12 `company_resolver` NON-touchpoint ✅.

## Test Gate Outcomes

| Gate | Result | Evidence |
|---|---|---|
| G1 fusion + rpki_validate | **PASS** | `210 passed` |
| G2 RIR + RPKI parsers | **PASS** | `55 passed` |
| G3 v1 parity + resolver | **PASS** | `116 passed`, exit 0 |
| G4 integration pipeline | **PASS** | `21 passed in 643.74s` |
| G5 migration up/down/up, single head | **PASS** | head `c4a8f13e07b6`, single, no branching |
| G6 live RIR dry-run | **PASS** | 5/5 RIRs, **262,225 allocations** (>200k), **skip ratio 0.0000%** (<5%); independently re-parsed with awk: 260,663 candidate lines → 262,225 CIDRs (delta = non-power-of-two decompositions) |
| G7 live RPKI dry-run | **PASS** | **755,656 IPv4 ROAs** (>400k), 0 fatal, 102,892,123 bytes |
| G8 query plans + round trip | **PASS** | covering-ROA **0.564 ms** (<10 ms); full v2 round trip over 25 real IPs hitting all 3 legs: **median 6.06 ms / p95 9.02 ms / max 11.22 ms** (<15 ms); GiST **Index Scan** on every leg, no seq scan |
| G9 full unit lane | **PASS** | **1605 passed / 0 failed / 2 skipped**, stable over 3 random orderings; baseline was 2 failed |
| G10 hypothesis plausibility | **PASS (judgment)** | see below |
| G11 org_kind isolation | **PASS** | `5 passed` unit + 5 integration legs vs real Postgres |
| G12 lock serialization | **PASS** | second refresh returns `{"status":"locked"}`, both source counts intact |
| G13 asn IS NULL | **PASS** | `1 passed` + live: `rir_delegated` rows all NULL, zero rows with `asn = 0` |
| G14 four canonical index names | **PASS** | incl. `idx_ip_org_prefixes_relationship_type`, exactly one `_pkey`, no `*_staging_*` |
| G15 downgrade with NULL-asn row seeded | **PASS** | DELETE-first ordering proven on real data |
| G16 rpki max-bytes | **PASS** | `4 passed` — aborts mid-stream, `json.loads` never reached |
| G17 zero-date keep | **PASS** | `12 passed` |
| G21 full-volume `--apply` | **PASS** | **967,261 rows, `duration_s=757.05` (12.6 min)** — under the 20-min tripwire (E8) |
| G18 / G19 / G20 | **SKIPPED (E14)** | domain leg split out |

### G9 baseline (E6)

Measured at EXECUTE start, before any change: **2 failed / 1324 passed / 2 skipped**. The 2
failures were `test_candidate_outreach_gate.py::test_excluded_sites_do_not_carry_the_wrapper`
[`hot_alert`, `outcome_digest`] — order-dependent, and they did not reproduce in any of the 4
end-of-phase runs. Note this differs from the pair named in the task prompt
(`TestBeamIdentityNetwork`), which did not fail in this tree. Final: **1605 passed / 0 failed** —
the failure set shrank, so the no-regression gate holds.

### G10 judgment (Agent-Probe — recorded, not proof)

The `org_kind='org'` filter (D11) is doing exactly its job on the highest-risk real IPs:
**Google 8.8.8.8, Cloudflare 1.1.1.1 and 104.16.0.1, AWS 52.95.110.1, Apple 17.253.144.10,
Microsoft 13.107.6.9 and 204.79.197.200, Fastly 151.101.1.69 → all `None`.** These are precisely
the prefixes that would fabricate an employer; the anti-`cdurham@fastly.com` guarantee is
demonstrated on live infrastructure, not only on fixtures.

GitHub resolved correctly at 0.55 / 0.60 with RPKI-valid evidence. Confidence now spreads
**0.40–0.65** where Phase 2 emitted a flat 0.45, and the uncertainty text is honest — e.g.
`"the announced prefix is 4 bits more specific than its registered allocation — the announcing AS
may be a provider rather than the organization itself"`. Every hypothesis below 0.5 carried at
least one uncertainty string.

## Plan Deviations

| # | Deviation | Class | Rationale |
|---|---|---|---|
| D-1 | Migration chains off **`b6f4a2d90c13`**, not the expected `a3e8d5c71f02` | within blast radius — E1 anticipated it | The head moved (`b6f4a2d90c13 add_site_tombstones_timestamps`, itself chained off `a3e8d5c71f02`). Re-derived live and chained on top, exactly as E1 instructs. New head `c4a8f13e07b6`, single, no branching. |
| D-2 | `rpki_roas.asn` is **BigInteger**, not the planned `Integer` | within blast radius (new table, file already in Touchpoints) | **Required — the live load fails otherwise.** See "real defects" below. |
| D-3 | Pre-existing `test_the_swap_replaces_the_dataset_wholesale` re-scoped to seed `source='caida_pfx2as'` | within blast radius | Direct, intended consequence of D1's carry-over: rows of a *different* source are now legitimately preserved. The test's meaning ("replace, not append") is unchanged and is now asserted same-source; the cross-source half got its own new test. |
| D-4 | `test_scheduler_job_config` E20 arithmetic updated 20/18/2 → 22/20/2 | within blast radius | That gate's own docstring instructs re-deriving the arithmetic when a job is added and explicitly forbids relaxing the assertion. Two flag-gated jobs were added per WS2 item 9 / WS3 item 14. |
| D-5 | Gate selector names adjusted (`org_kind_isolation`, `max_bytes`, `zero_date` now appear in test names) | within blast radius | As first written, `pytest -k org_kind_isolation` / `-k max_bytes` / `-k zero_date` selected **zero** tests, so G11/G16/G17 would have reported a vacuous green. Renamed so the plan's literal gate commands actually select. |
| D-6 | The RPKI `--apply` load was performed from the already-downloaded `rpki.json` after a transient network fault | procedural, not a code change | The live network fetch is separately proven by G7. The fault itself is useful evidence: fail-open behaved correctly (`status: error`, nothing swapped, prior data intact). |

No hard-stop-class deviation occurred. No identity-coop, cross-tenant-erasure, roster-precision or
`yc-application-coach` file was touched (E4).

## Two Real Defects Found By Live Gates

**1. 4-byte ASNs overflow `Integer` (found by the first `--apply`, fixed).**
ASNs are 32-bit *unsigned* (RFC 6793). The live Cloudflare dump carries **17 ROAs out of 755,538**
with an ASN above int32, up to `4,294,967,294`. The planned `Integer` column rejected the entire
load with `value out of int32 range`. Fail-open worked correctly (nothing swapped), but the load
could never have succeeded in any environment.

Skipping those rows would have been *worse than* losing them, not merely lossy: `validate_origin`
returns INVALID when a covering ROA exists but none authorizes the announcement, so discarding the
one authorizing ROA converts a legitimate announcement into `disputed_origin` and costs it 0.20
confidence. Widened to `BigInteger` in both model and migration, with a regression test asserting
both the parse and the column type. `ip_org_prefixes.asn` was left alone — its max observed value
is 402,843 and the full 967k live load succeeds — but the same hazard theoretically applies there
(see gaps).

**2. My own hand-derived test fixtures were wrong twice — caught before they shipped.**
Both instances are the exact defect class E3/the plan's Test Infra note warns about:
- a CIDR decomposition list written by reasoning (`87.116.84.0/23 + /24`) instead of by running
  `summarize_address_range` (real answer: `/22 + /22`);
- an integration fixture using `10.0.0.0/16` as a "covering" allocation for `10.1.2.55`, which it
  does not contain at all (that /16 spans only 10.0.0.0–10.0.255.255).

The second was caught only because the integration lane runs against real Postgres containment
semantics — a stub would have happily agreed with the wrong fixture. Both are now computed values
with the derivation recorded in-test.

## Test Infra Gaps Found

- **NEW — post-swap planner statistics (recorded, deliberately NOT fixed).** Immediately after a
  bulk swap, before autovacuum ANALYZEs the renamed table, the planner picks a `BitmapAnd` that
  scans the entire low-cardinality `idx_ip_org_prefixes_relationship_type` bitmap (967,261 entries)
  instead of driving from the GiST index — measured at ~15.7 ms under EXPLAIN instrumentation
  versus 1.5 ms once statistics exist. Analogous to EVL-001's cold 26–385 ms window. Adding an
  `ANALYZE` at the end of the swap is the obvious fix, but it is not in the approved plan, so it is
  reported rather than applied. No production impact today (all flags OFF). Recommended follow-up
  stub: `ip-org-post-swap-analyze_NOTE_*`.
- **Pre-existing conftest `platform` ENUM teardown race** — hit once mid-session (5 setup errors),
  cleared on re-run. Carried from EVL-001 known-gap 3; NOT a Phase 3 defect and was not "fixed" by
  weakening any gate.
- **Pre-existing `RuntimeError: Event loop is closed`** shutdown noise in
  `tests/unit/test_company_resolver.py`. Confirmed pre-existing by stashing the Phase 3 change and
  reproducing it identically; exit code is 0 and 61/61 tests pass. Not a failure.
- **Local dev DB had been wiped by a concurrent session** (stamped at head, zero tables). Rebuilt
  the entire chain from base — which incidentally re-proved the full forward apply.
- **`eyeball` classification gaps propagate into fused hypotheses.** G10 surfaced consumer ISPs
  classified `org` and therefore eligible for a hypothesis: `tpg internet`, `bharti airtel`,
  `mtn nigeria communication`, `telekom srbija`, `zayo bandwidth`. Cause is Phase 1's
  `_EYEBALL_ORG_TOKENS` list (it contains `deutsche telekom` but not bare `telekom`), not the D11
  filter, which faithfully honours whatever `org_kind` says. Pre-existing input-labelling quality,
  out of Phase 3 scope. Recommended stub: `ip-org-eyeball-token-coverage_NOTE_*`.

## Known-Gap residuals carried forward (unchanged by EXECUTE)

KG-1 live fused-confidence distribution (needs an operator flag flip) · KG-2 RIR opaque-id → org
NAME (needs RDAP) · KG-3 fused confidence staleness, bounded by the ≤0.65 clamp · KG-4 C-b
documented but not built. A7 also stands: **no gate proves fusion is more ACCURATE than Phase 2's
flat 0.45** — every fusion gate proves internal consistency only.

## Closeout Packet

- **Selected plan:** `process/features/visitors-identity/active/ip-org-database_07-08-26/ip-org-phase-3-evidence-graph_PLAN_07-08-26.md`
- **Finished:** WS1, WS2, WS3, WS4 (fusion + lookup v2 + resolver branch). 18/18 in-scope gates green.
- **Verified:** all Fully-Automated and Hybrid gates against `localhost:5433`; both Agent-Probe gates recorded as judgments.
- **Unverified:** anything requiring a flag ON in a real environment; production migration apply; fusion accuracy.
- **Flags — all OFF at merge:** `ip_org_rir_ingest_enabled`, `ip_org_rpki_ingest_enabled`, `ip_org_fusion_enabled` (plus pre-existing `ip_org_lookup_enabled`).
- **Uncommitted:** nothing committed by this session. 20 files in the Touchpoints set are dirty; the worktree also carries unrelated concurrent work (`.codex/agents/*`, `yc-application-coach`) which must NOT be committed with this phase (E4).
- **Classification:** `Keep in active/testing` — code-complete and gate-green, but the phase's own completion rules require User Confirmation before `✅ VERIFIED`, and 3 follow-up stubs are outstanding.

## Forward Preview

**Test Infra Found** — integration lane needs ~11 min for `test_ip_org_pipeline.py`; the ENUM race
means a single re-run may be needed (PASS-by-union). Unit lane is 4 s. Use
`.venv/bin/python3.11 -m pytest` (the `.venv/bin/pytest` shebang is broken).

**Blast Radius Changes** — `ip_org_prefixes` grew 3 columns and a 4th index and now holds two
sources; `rpki_roas` is new. Any future writer of `ip_org_prefixes` MUST import
`IP_ORG_WRITE_LOCK_KEY` and pass `carry_over=True`, and MUST add an `_INDEX_TARGETS` entry for any
new index or it will break every subsequent swap.

**Commands to Stay Green** (always prefix `DATABASE_URL='postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent'` for anything touching a DB — `.env` points at Supabase PROD and alembic has no guard):
```
.venv/bin/python3.11 -m pytest tests/unit -m unit -q
.venv/bin/python3.11 -m pytest tests/integration/test_ip_org_pipeline.py -q
```

**Dependency Changes** — none. No new Python package; `ipaddress`/`json` are stdlib and `httpx` was
already present. `dnspython` was NOT needed because the domain leg was split out.

**Next plan** — the follow-on domain-mapping plan gated on G19, which now needs its own measurement
harness since `resolve_org_domain` does not exist. `OrgHypothesis.domain` is already in the
contract and always `None`, so that plan fills a hole rather than changing a shape.
