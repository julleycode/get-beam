---
name: plan:ip-org-phase-3-evidence-graph
description: "Phase 3 of ip-org-database, redefined: turn the flat prefix→org table into a multi-source evidence graph (route_origin + registered_holder + rpki_authorizer) with confidence fusion, lookup v2, and domain mapping"
date: 07-08-26
feature: visitors-identity
---

# IP-Org Phase 3 — Evidence Graph v2 (scope redefined from "domain mapping only")

**Date**: 07-08-26
**Status**: PLANNED — needs PVL (validate) before EXECUTE
**Complexity**: COMPLEX (4 workstreams, 1 migration, 2 new tables, 3 new services, changes a live resolver seam)
**Feature**: visitors-identity
**Parent plan**: `ip-org-database_PLAN_07-08-26.md` (Phases 1–2 ✅ COMPLETE)

## TL;DR

Phase 3 was scoped as "org-name → domain mapping". User approved redefining it to **evidence graph v2**:
`ip_org_prefixes` stops being a flat `prefix → company` table and becomes time-aware evidence rows carrying
`relationship_type`, fed by three independent open sources (CAIDA BGP, RIR delegated-extended, RPKI ROAs),
fused by one pure scoring function into an organization *hypothesis* with per-evidence breakdown and stated
uncertainty. Domain mapping stays, as WS4's last item. Every flag defaults OFF; the existing v1 lookup path
is preserved byte-identical until `ip_org_fusion_enabled` is flipped.

## Context

Phases 1–2 shipped and are proven on real data (967,079 rows loaded live, GiST longest-prefix verified,
`company_graph` write-through as `source="rir_asn"` conf 0.45). Evidence:
`ip-org-database-evl-iteration-001_REPORT_07-08-26.md` + its Addendum.

The research reference (`evidence-graph-research_REFERENCE_07-08-26.md`, §1.1–§2.3) identifies a
**correctness defect, not a missing feature**, in what shipped: CAIDA pfx2as is BGP-derived, so today's
`org_name` is the **announcing AS's organization**, which is frequently a transit provider or hosting
company announcing on behalf of a customer — not the registrant and not the end organization.
`org_kind` tagging catches the obvious datacenter/CDN/eyeball cases; it cannot catch "Company A's /24
announced by mid-tier ISP B". The fix is not a better single source. It is to record *which relationship*
each row asserts and to score agreement across independent sources.

The fusion seam already half-exists: `company_graph` has `UniqueConstraint(ip, source)` with a
`confidence.desc()` read, i.e. primitive multi-source evidence competition. Phase 3 makes the fusion
explicit and moves it upstream of that write.

Repo context routers consulted: `process/context/all-context.md`,
`process/context/tests/all-tests.md`, `process/features/visitors-identity/` task-folder inventory.

## Scope Redefinition Record (user-approved)

| | Original Phase 3 | Redefined Phase 3 |
|---|---|---|
| Goal | fill `ip_org_prefixes.domain` | multi-source evidence graph + fusion + domain |
| Sources | 1 (CAIDA) | 3 (CAIDA BGP, RIR delegated-extended, RPKI ROA) |
| Output | `str \| None` domain | org hypothesis: org + classification + confidence + evidence[] + uncertainty[] |
| Schema | none | `relationship_type`, `valid_from`, `valid_to` + 2 small tables |

Domain mapping is retained (WS4, item 4) — descoped from "the phase" to "one workstream item".

## Design Decisions (locked — EXECUTE must not re-litigate)

**D1 — Refresh model: union-aware staging swap (keep the proven swap, make it multi-source).**
Today `_load_staging_and_swap` replaces the *whole* table. With three sources refreshing on independent
cadences, a whole-table swap would delete the other two sources' rows. Fix: before the swap, copy
carry-over rows server-side into staging — `INSERT INTO staging SELECT … FROM live WHERE source <> :source`
— then DROP/RENAME exactly as today.
*Rejected:* per-source `DELETE … WHERE source = :s` + `INSERT` — holds a delete of ~1M rows in one
transaction, bloats the table, and abandons the DROP/RENAME path whose crash-safety was accidentally but
genuinely proven when the Postgres container was killed mid-load (EVL Addendum).

**D2 — Temporal validity: snapshot semantics, not row history.**
`valid_from` = the source snapshot's `dataset_date`; `valid_to` = `NULL` meaning "asserted by the current
snapshot". A swap replaces a source's rows wholesale, so superseded assertions are dropped, not closed.
Rationale: fusion (WS4) only ever reads currently-valid evidence; no Phase 3 consumer reads history, and an
append-only history table would multiply a 1M-row-per-refresh table by every refresh for zero present value.
The upgrade path is kept open and costed in Out of Scope (archive-on-swap into `ip_org_prefix_history`).
`valid_to` is added now, always NULL, precisely so that upgrade is additive rather than another migration
of the hot table.

**D3 — Backfill in-migration, not at next ingest.**
`relationship_type` is added `NOT NULL DEFAULT 'route_origin'` (Postgres 11+ adds a defaulted NOT NULL
column without a table rewrite) and `valid_from` is backfilled with a single
`UPDATE … SET valid_from = dataset_date`. Doing it at next ingest would leave the table with a NULL/absent
relationship for up to `ip_org_refresh_interval_hours` (24h) while the live v1 lookup is reading it.
Backfill value `route_origin` is correct by construction: every existing row came from pfx2as, which *is*
BGP origin data.

**D4 — No unique constraint on evidence rows; dedup in the parser.**
Multi-origin prefixes legitimately produce several `(prefix, asn)` pairs, and each source rebuilds its own
row set wholesale, so a DB-level uniqueness guarantee buys nothing and would abort a 1M-row load on a data
quirk. Parsers dedup in-memory (already true for pfx2as). Documented, not enforced.

**D5 — RPKI lives in its own table, not as evidence rows.**
An ROA authorizes an **ASN**, not an organization, and carries `maxLength`, which has no home in an
org-keyed evidence row. Forcing it in would require a fabricated `org_name`. New small table `rpki_roas`
(`prefix` CIDR + GiST, `asn`, `max_length`). `relationship_type='rpki_authorizer'` remains in the
vocabulary for future name-bearing RPKI-derived evidence, but WS3 writes no such rows.

**D6 — One fused `company_graph` row, not one per source; fused confidence clamped to ≤ 0.65.**
`company_graph`'s `(ip, source)` unique key + `confidence.desc()` read means multiple ip_org-derived rows
would compete with *each other*, and the highest would win regardless of fusion — defeating the point.
So: fusion happens in the service, one row is written, `source` stays `"rir_asn"` (no consumer change),
`confidence` becomes the fused score. Clamp `[0.05, 0.65]` keeps the paid path (0.7) authoritative and
prevents a strongly-corroborated free hit from silently outranking data we paid for. Note this DOES let a
fused score exceed rDNS (0.5) — intended, and the reason the whole behavior sits behind
`ip_org_fusion_enabled`.

**D7 — Domain mapping: DNS-heuristic ONLY (Hunter leg DROPPED), into a SEPARATE table.**
*(REWRITTEN by PVL-1 supplement — resolves F2.)*
Domains must NOT be written into `ip_org_prefixes.domain` — the next source swap would wipe them. New
`ip_org_domain_map` keyed on normalized `org_name`, with negative caching (`attempts`, `last_attempt_at`)
so a failing org is not re-queried daily.

**The Hunter leg is DROPPED from Phase 3.** The pre-supplement D7 claimed reuse of "the existing Hunter
domain-search mixin". That claim was FALSE and is retracted:
`apps/api/services/identity_providers/hunter.py:34-73` is `_call_hunter_api(self, domain, offset) -> contact`
— it takes a DOMAIN and returns a PERSON, the inverse of what WS4 needs — and it is a class mixin bound to
`self._log_resolution` / `self._save_identified` / `self._count_identified_for_domain`, so it is not
callable from a standalone service. No org-name → domain call exists anywhere in the repo.

Rather than write a NEW Hunter integration, Phase 3 drops the leg entirely. Justification:
`apps/api/config.py:774` records the Hunter free tier as **25 calls/month**, and `hunter_api_key` /
`hunter_enabled` are SHARED with the identity-resolution waterfall. Against the measured 102,624-org
corpus, 25 calls/month resolves ~0.02% of orgs while consuming quota the waterfall uses to resolve real
people — a net product regression bought for a rounding error of coverage. Phase 3 ships the **DNS
heuristic only**. Paid domain enrichment is named in Out of Scope as future work behind its own budget.
*Rejected:* targeted Wikidata SPARQL — the public endpoint rate-limits and times out on paged
organization+official-website queries, adds an external dependency with no SLA, and its coverage skews to
large public companies, i.e. exactly the orgs whose domain the heuristic already gets right.
*Rejected:* a NEW Hunter `/v2/domain-search?company=` integration parsing `data.domain` — quota reasoning
above; it would also require inventing a response contract and a cross-program budget negotiation that no
Phase 3 gate can prove.

**D10 — ONE shared advisory-lock key for every writer of `ip_org_prefixes`.**
*(NEW — resolves F1.)*
`refresh_ip_org_dataset` (CAIDA, 24h) and `refresh_rir_allocations` (RIR, weekly) both end in
`DROP TABLE ip_org_prefixes` + `RENAME`. With separate lock keys, D1's carry-over
(`INSERT INTO staging SELECT … WHERE source <> :source`) reads a snapshot that goes stale while the other
job's swap commits; the RENAME then silently discards the other source's freshly-loaded rows. The
schedules DO collide (weekly ∩ daily) and the CAIDA job is gated on the same `ip_org_lookup_enabled` flag
the lookup needs, so the collision is reachable, not theoretical.

Locked rule: `_INGEST_LOCK_KEY = "beam_ip_org_ingest"` (`ip_org_ingest.py:50`) is promoted to the single
**table-scoped** lock for `ip_org_prefixes`. EXECUTE moves it to
`apps/api/models/ip_org_prefix.py` as `IP_ORG_WRITE_LOCK_KEY` (co-located with `IP_ORG_TABLE`, so the
lock and the table it protects are declared together) and both ingest services import it.
`ip_org_rir_ingest.py` MUST NOT define its own key. The loser of the race returns `{"status": "locked"}`
and no-ops, exactly as today. `rpki_roas` is a SEPARATE table with a SEPARATE writer and keeps its OWN key
(`beam_rpki_ingest`) — it never touches `ip_org_prefixes`, so serializing it would cost throughput for no
safety gain.

**D11 — `lookup_ip_org_v2` KEEPS the `org_kind = 'org'` filter at read time.**
*(NEW — resolves F3. D9's safety property restated as an explicit, non-negotiable decision.)*
v2's route_origin selection uses the SAME predicate as v1: `WHERE prefix >>= :ip AND org_kind = 'org'`.
A `datacenter`, `cdn`, or `eyeball` prefix yields `None` from v2 — no hypothesis, no `company_graph`
write, at any confidence. `eyeball` is 26.9% of loaded rows (EVL-001 Addendum) and is the single largest
fabrication risk: resolving a Comcast prefix to "Comcast" as a visitor's employer is the
`cdurham@fastly.com` defect class.

Consequence: the fusion weight table's `shared-hosting penalty −0.15 for org_kind ∈ {datacenter, cdn}`
is **DELETED** (see the corrected table in WS4 item 15). It was dead code that only made sense if v2
dropped the filter, and keeping it would document an intent the code must never have. Filtering is
strictly safer than penalizing — a −0.15 penalty still writes a row. `registry` rows are excluded by the
same predicate, which is correct: they are corroborating evidence, never the hypothesis subject.

**D12 — `classification` derivation table (total and deterministic).**
*(NEW — resolves F4.)*
`classification` is derived by the FIRST matching row, top to bottom. **Row 1 deliberately OVERLAPS rows
2–5** — an RPKI-invalid prefix also has an allocation state — and that is why the rule is first-match
rather than a partition: overlap plus ordering is what makes the function total. Rows **2–5 are mutually
exclusive and exhaustive** among themselves (the same partition as C7 rule 2), and row 5 is the
total-function fallback. So every input SELECTS exactly one row, while more than one row may MATCH.
(Corrected in supplement cycle 2 — N2: the cycle-1 prose claimed both "first matching row" and
"mutually exclusive by construction", which cannot both hold for row 1.)

| # | Condition | `classification` |
|---|---|---|
| 1 | RPKI state == `invalid` | `disputed_origin` |
| 2 | announced prefix ≥ 4 bits more specific than its most-specific covering allocation | `likely_operational_customer` |
| 3 | announced prefix == its most-specific covering allocation prefix | `registered_operator` |
| 4 | 1–3 bits more specific than the most-specific covering allocation (the neutral band, C7) | `likely_operational_customer` |
| 5 | no RIR corpus loaded, OR corpus loaded but prefix uncovered | `unclassified` |

Vocabulary is exactly `disputed_origin` | `likely_operational_customer` | `registered_operator` |
`unclassified`. Two pre-supplement values are DELETED as unreachable by construction: `registry_only`
(fusion returns `None` without a `route_origin` row, so a registry-only prefix never yields a hypothesis)
and `likely_infrastructure` (under D11 no datacenter/cdn/eyeball prefix ever reaches fusion).

**D13 — `ip_org_prefixes.asn` becomes NULLABLE (no `0` sentinel).**
*(NEW — orchestrator-mandated override of the pre-supplement `asn = 0` sentinel.)*
RIR delegated-extended data carries no ASN. A `0` sentinel is a lie every future reader must know to
special-case; `NULL` is the type system stating the same fact checkably. The full 12-touchpoint ripple —
including the four VERIFIED NON-touchpoints, recorded so they read as checked rather than missed — is
enumerated in WS1 item 2a. The one real cost is the migration DOWNGRADE, which must delete NULL-asn rows
before re-adding `NOT NULL` (see WS1 item 2 and gate G5).

**D8 — Registered-holder evidence carries no org NAME in v1.**
RIR delegated-extended files publish `registry|cc|type|start|value|date|status|opaque-id` — an opaque
handle, not a name. Names require RDAP (one request per handle, ~100k handles, rate-limited) — deferred and
costed in Out of Scope. v1 stores registry/cc/opaque-id and derives the **allocation-specificity** signal
(WS4/S2), which needs no name.

**D9 — `org_kind` isolates new sources from the live v1 query.**
RIR rows get `org_kind='registry'`. The v1 lookup SQL filters `org_kind = 'org'`, so WS1–WS3 can land and
ingest without any possibility of changing what the currently-enabled path returns. This is the phase's
main safety property and must not be weakened.

**D14 — DNS-heuristic slug transform is fixed, and a resolving domain is NOT accepted without
corroboration.**
*(NEW in supplement cycle 2 — resolves N6, the highest-severity remaining item.)*

Two separate defects were open. Both are closed here.

**(1) The slug transform is now specified exactly.** `normalize_org_name` (`ip_org_ingest.py:90-106`)
emits SPACE-SEPARATED tokens (`"1 800 contacts"`, `"deloitte touche tohmatsu"`), so the join rule
materially changes both hit rate and correctness. Locked algorithm:

```
tokens = normalize_org_name(org_name).split()
if not tokens:                      -> no candidates
if len(tokens) == 1:                -> candidates = [f"{tokens[0]}.com"]
else:                               -> candidates = [f"{''.join(tokens)}.com", f"{'-'.join(tokens)}.com"]
```

At most **2 candidates per org**, evaluated in order, first CORROBORATED candidate wins. Only `.com` is
tried in Phase 3 — multi-TLD expansion multiplies both the DNS budget and the false-positive surface for
a coverage gain nobody has measured yet (see N7/G19).

**(2) A DNS answer is necessary but NOT sufficient.** This is the actual fix. The dangerous mode is not
"slug fails to resolve" — it is "slug RESOLVES, to the wrong company": org `delta` → `delta.com` is the
airline, not Delta Electronics. That domain would flow into `resolve_company_cached` and onward into
domain-keyed enrichment, which is the `cdurham@fastly.com` fabrication mechanism one layer up from where
D11 closed it on the prefix side.

Locked rule: a candidate is ACCEPTED only when it resolves in DNS **AND** at least one corroboration
holds. Both corroborations are pure local DB reads — zero external cost, no new dependency:

| # | Corroboration | Status in Phase 3 | Why it is real evidence |
|---|---|---|---|
| C-a (primary) | An existing `company_graph` row whose `ip` falls inside ANY prefix belonging to this same `org_name` in `ip_org_prefixes` carries `domain == candidate` | **LIVE — the only implemented path** | rDNS already tied that domain to an IP this org announces — independent of the name guess entirely |
| C-b | An existing `company_graph` row has `domain == candidate` AND its `company_name` normalizes (via `normalize_org_name`) to this same `org_name` | **DOCUMENTED-FUTURE — NOT implemented in Phase 3 (PVL-3 P1, PVL-4 Q2)** | a previously resolved name↔domain pair would agree with the guess |

**C-a query safety (PVL-3 / P3) — part of the locked rule, not an implementation detail.** The
containment join casts a STORED column: `company_graph.ip` is `String(45)` and explicitly nullable
("nullable if resolved by domain only"). `CAST(cg.ip AS inet)` tolerates NULL but raises
`invalid input syntax for type inet` on an empty or malformed string, which ABORTS the surrounding
transaction — and this runs on the live resolver path. v1 only ever casts the caller-supplied `:ip`
bind parameter, never stored free text, so this is a NEW hazard class for this code. Required:

- guard the cast: `WHERE cg.ip IS NOT NULL AND cg.ip <> ''` before any `CAST(cg.ip AS inet)`;
- treat a cast failure as a NORMAL fail-open outcome — `rollback()` then return `None` from
  `resolve_org_domain` (the same posture as `lookup_ip_org`), never a raise into the resolver;
- the guard reduces but does not eliminate the risk (a non-empty malformed string still throws), which
  is exactly why the fail-open path is mandatory rather than defensive decoration.

**Why C-b is documented but NOT built (PVL-3 P1 → PVL-4 Q2).** It is unsatisfiable against real data.
Verified by enumerating every `company_graph` writer in the repo:

| Writer | `company_name` written | `domain` written |
|---|---|---|
| `company_resolver.py:568` (rDNS) | `None` | real domain |
| `company_resolver.py:578` (rDNS, no-Redis path) | `None` | real domain |
| `identity_resolver.py:694` (paid_ip) | `None` | real domain |
| `company_resolver.py:615` (ip_org) | real org name | `match["domain"]` — NULL throughout Phase 3 |

No writer produces a row with BOTH a non-NULL `domain` and a non-NULL `company_name`, which is exactly
what C-b requires. **So C-a is the ONLY corroboration path in Phase 3, and EXECUTE ships NO C-b code.**

Cycle 3 kept the branch as dead code; cycle 4 removes it (Q2). Shipping an unreachable branch that no
gate can exercise is exactly the YAGNI failure — and it contradicted AC4.11b, which correctly says
activation would need its own gate PLUS the feedback-loop guard below (i.e. it is NOT "no design
change"). The rule is preserved as documentation + **KG-4** + AC4.11b's canary assertion, so a future
writer that emits name+domain together trips the canary and forces a deliberate design pass instead of
silently activating untested code.

*Rejected:* making C-b satisfiable by having the ip_org write-through populate `company_graph.domain`
once D14 accepts a domain. That closes a **feedback loop**: D14 accepts via C-a → the acceptance is
written to `company_graph` → C-b later reads Beam's own inference back and treats it as independent
corroboration. Evidence laundering, on the exact path whose fabrication risk D14 exists to close. It
could be guarded (exclude `source='rir_asn'` rows from C-b) but it buys zero Phase-3 coverage — C-a
already covers every case C-b would — while adding a subtle rule to the highest-risk path in the phase.

No corroboration → the candidate is **REJECTED**: the map row is written with `domain = NULL` and
`source = 'heuristic_uncorroborated'` (recorded so the attempt is visible and negative-cached, never
served). `resolve_org_domain` returns `None`.

**Accepted consequence, stated honestly:** with C-b unbuilt, **C-a is the entire corroboration
surface**, so Phase-3 domain coverage is bounded by the set of orgs for which rDNS has ALREADY resolved
a domain on an IP inside one of that org's own prefixes. The hit rate will be low — likely single-digit
percent of the 102,624-org corpus. That is the correct trade: an unmeasured, uncorroborated domain guess
feeding enrichment is worse than no domain. G19 measures the real number **against a deliberately seeded
corpus (see its precondition — an unseeded run measures nothing)**; if it is too low to be useful, the
honest next step is a paid leg with its own budget (Out of Scope), not a relaxed guard.
*Rejected:* accepting any resolving `{slug}.com` — that is precisely the fabrication mode N6 identified.
*Rejected:* MX-record or HTTP-title checks as corroboration — both prove the domain EXISTS and is
live-ish, not that it belongs to this organization; they would add cost and latency while closing nothing.

## Workstreams

Execution order is WS1 → WS2 → WS3 → WS4. WS2 and WS3 are independent of each other and may be
parallelized; both depend on WS1's schema; WS4 depends on all three.

### WS1 — Schema evolution to evidence rows

**Implementation Checklist**

1. Re-derive the live head: `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads`.
   Expected `a3e8d5c71f02`; if it moved, chain off the actual head and record the deviation.
2. Create `apps/api/migrations/versions/<rev>_add_ip_org_evidence_graph.py` (ONE revision for the whole
   phase — WS1 columns + WS3 `rpki_roas` + WS4 `ip_org_domain_map`):
   - `ip_org_prefixes.relationship_type` — `String(32)`, `nullable=False`, `server_default='route_origin'`
   - `ip_org_prefixes.valid_from` — `Date`, nullable
   - `ip_org_prefixes.valid_to` — `Date`, nullable
   - `op.alter_column("ip_org_prefixes", "asn", existing_type=sa.Integer(), nullable=True)` (D13)
   - index `idx_ip_org_prefixes_relationship_type` on `(relationship_type)`
   - backfill: `UPDATE ip_org_prefixes SET valid_from = dataset_date WHERE valid_from IS NULL`
   - **downgrade order is load-bearing:** `DELETE FROM ip_org_prefixes WHERE asn IS NULL` FIRST (equivalently
     `WHERE source = 'rir_delegated'`), THEN `alter_column(asn, nullable=False)`, THEN drop the index, THEN
     drop the three columns, THEN drop `rpki_roas` and `ip_org_domain_map`. Without the DELETE the downgrade
     fails on any database that has ingested RIR rows — the one downgrade path that can fail on real data
     (C10). Put this reasoning in a comment in the migration body, not only here.
   - **Lock-duration note (C5):** the `valid_from` backfill rewrites ~967k rows and the `CREATE INDEX` takes
     ACCESS EXCLUSIVE. Expected: tens of seconds on the measured local corpus. **Accepted, not optimized** —
     `ip_org_lookup_enabled` is OFF in every environment this migration will reach, so there is no concurrent
     reader to block. If that ever stops being true, switch to `CREATE INDEX CONCURRENTLY` in a separate
     non-transactional revision. Do NOT add `CONCURRENTLY` now: it cannot run inside alembic's transaction.

2a. **D13 asn-NULLABLE ripple — all 12 touchpoints (4 of them verified NON-touchpoints).** EXECUTE must
   walk this list explicitly and confirm each:

   | # | Location | Action |
   |---|---|---|
   | 1 | `apps/api/models/ip_org_prefix.py:61` | `Mapped[int]`/`nullable=False` → `Mapped[int \| None]`/`nullable=True`; docstring says "NULL means this evidence class carries no ASN (RIR `registered_holder`)" — do NOT document a sentinel |
   | 2 | migration | `ALTER COLUMN asn DROP NOT NULL` + the DELETE-first downgrade above |
   | 3 | WS2 item 7 row builder | `asn = None` (never `0`) |
   | 4 | WS2 acceptance | new AC2.5: RIR rows land `asn IS NULL`; zero rows have `asn = 0` |
   | 5 | `IpOrgMatch.asn: int` (`ip_org_lookup.py:40`) | **NON-touchpoint — verified.** v1 filters `org_kind='org'`; RIR rows are `org_kind='registry'`, so v1 never observes NULL |
   | 6 | `_LOOKUP_SQL` (`ip_org_lookup.py:44-48`) | **NON-touchpoint — verified.** No `asn` predicate |
   | 7 | `idx_ip_org_prefixes_asn` | **NON-touchpoint — verified.** btree indexes NULLs fine |
   | 8 | `_load_staging_and_swap` INSERT (`ip_org_ingest.py:358-363`) | No code change (`None` binds cleanly), BUT the staging `LIKE … INCLUDING ALL` must be created AFTER this migration so staging inherits the nullable constraint |
   | 9 | `fuse_org_hypothesis` | Reads asn ONLY from the `route_origin` row (always non-NULL). The allocation-specificity leg is prefix-only. MUST NOT read `rir_row["asn"]` |
   | 10 | `lookup_ip_org_v2` covering-`registered_holder` query | MUST NOT filter, join, or ORDER BY `asn` |
   | 11 | `tests/integration/test_ip_org_pipeline.py:28-44` `_row`/INSERT helper | asn is positional in the explicit column list — add a NULL-asn RIR fixture row |
   | 12 | `apps/api/services/company_resolver.py:584-618` | **NON-touchpoint — verified.** Reads only `match["domain"]` / `match["org_name"]` |
3. `apps/api/models/ip_org_prefix.py`: add the three mapped columns + the index; add module constant
   `RELATIONSHIP_TYPES: frozenset[str] = frozenset({"route_origin", "registered_holder", "rpki_authorizer"})`
   plus `IP_ORG_WRITE_LOCK_KEY = "beam_ip_org_ingest"` (D10 — the shared table-scoped lock constant,
   moved here from `ip_org_ingest.py:50` so lock and table are declared together),
   with a docstring stating the vocabulary is **extensible** (values from the research taxonomy —
   `network_operator`, `infrastructure_provider`, `likely_customer`, `reverse_dns_owner` — are reserved,
   not implemented) and that it is deliberately NOT a DB enum (adding a value must not need a migration).
4. `apps/api/services/ip_org_ingest.py`: every row dict built in `refresh_ip_org_dataset` gains
   `relationship_type="route_origin"`, `valid_from=dataset_date`, `valid_to=None`; extend the staging
   `INSERT` column list accordingly.
5. Rework `_load_staging_and_swap(db, rows, source, dataset_date)` → add a `carry_over: bool = True` path:
   after `CREATE TABLE staging (LIKE … INCLUDING ALL)` and before the chunked inserts, execute
   `INSERT INTO staging SELECT * FROM live WHERE source <> :source`. Keep the DROP/RENAME sequence
   unchanged.

5a. **`_rename_indexes_to_canonical` MUST change (C2 — the pre-supplement "keep unchanged" instruction
   was wrong and would have written a bug).** `_INDEX_TARGETS` (`ip_org_ingest.py:310-314`) holds 3
   markers (`gist`, `(asn`, `(org_name`) with an unconditional `else → "{table}_pkey"` fallback. The new
   `idx_ip_org_prefixes_relationship_type` matches no marker, falls through, and BOTH it and the real
   primary-key index get renamed to `ip_org_prefixes_pkey` → `relation already exists` → the swap
   transaction aborts on **every** refresh after WS1 lands. Add a 4th entry:
   `("(relationship_type", "idx_ip_org_prefixes_relationship_type")`.
   Add it to the tuple in the same commit as the model index — the two are one change, not two.

5b. **Shared lock (D10).** `_load_staging_and_swap` and both its callers acquire
   `IP_ORG_WRITE_LOCK_KEY`. `ip_org_rir_ingest.py` imports the constant; it must not define its own.

5c. **Expected duration + accept-or-optimize decision (C5).** Measured baseline (EVL-001 Addendum):
   967k rows = 158–341s in ONE transaction with 4 indexes maintained. WS1 adds a 5th index; WS2 adds an
   estimated 400k–800k rows; D1 adds a server-side carry-over copy of up to ~1M rows. Expected worst-case
   swap: **8–15 minutes in a single transaction.** Decision: **ACCEPT for Phase 3, do not optimize.** The
   job is a background APScheduler task with no user-facing latency budget, the fail-open contract means a
   timeout costs a refresh and never the data, and the alternative (post-load index build) changes the
   crash-safety properties that were empirically proven in EVL-001. EXECUTE must state the observed
   duration in the phase report; if any single swap exceeds 20 minutes, raise it as a new finding rather
   than silently accepting it. **The 8–15 minute figure is an EXTRAPOLATION, not a measurement
   (supplement cycle 2 — N8):** it scales EVL-001's real 967k-row/158–341s numbers by the added rows,
   index, and carry-over copy. Gate **G21** turns it into a real measurement with a real full-volume
   `--apply` against `localhost:5433` — without it the tripwire could only fire during an operator's
   live run, i.e. after Phase 3 closed. Do NOT set a `statement_timeout` on this path — a timeout mid-swap is
   exactly the failure the single transaction exists to prevent.
6. Extract the swap's post-condition assertion: after RENAME, `SELECT source, count(*) … GROUP BY source`
   is logged (`ip_org_swap_source_counts`) so a carry-over regression is visible in structlog, not silent.

**Acceptance Criteria — WS1**

- AC1.1 Migration applies and reverses cleanly against a live local Postgres (`localhost:5433`), single head.
- AC1.2 Pre-existing rows read back with `relationship_type='route_origin'` and non-NULL `valid_from`
  equal to their `dataset_date`; zero rows have `relationship_type IS NULL`.
- AC1.3 A CAIDA refresh with rows of a second source present in the live table leaves that second
  source's row count unchanged after the swap.
- AC1.4 v1 `lookup_ip_org` returns byte-identical results before and after WS1 for the same seeded data.
- AC1.5 (D10/F1) CAIDA and RIR refreshes SERIALIZE: while the shared `IP_ORG_WRITE_LOCK_KEY` is held, the
  second refresh returns `{"status": "locked"}`, writes nothing, and both sources' row counts are intact
  afterwards. Plus a mechanical single-owner assertion, **corrected in supplement cycle 2 (N1)** — the
  cycle-1 wording grepped for `_INGEST_LOCK_KEY`, a substring the renamed `IP_ORG_WRITE_LOCK_KEY` does
  not contain, so it could never match; it also mixed up scope ("both ingest modules") with expected
  location (the model module), and would have false-matched `rpki_ingest.py`, which legitimately keeps
  its own key. The assertion that actually holds, scoped to the ONE module the rule constrains:

  ```bash
  # the shared key is DEFINED exactly once, in the model module
  grep -cE 'IP_ORG_WRITE_LOCK_KEY[[:space:]]*=' apps/api/models/ip_org_prefix.py  # == 1
  # the RIR service defines NO advisory-lock key of its own and imports the shared one
  grep -cE '^[A-Z_]*LOCK_KEY[A-Z_]*[[:space:]]*=' apps/api/services/ip_org_rir_ingest.py  # == 0
  grep -c 'IP_ORG_WRITE_LOCK_KEY' apps/api/services/ip_org_rir_ingest.py       # >= 1 (the import)
  ```

  `rpki_ingest.py` is deliberately OUT of scope for this assertion — D10 grants it its own
  `beam_rpki_ingest` key because it writes a different table.
- AC1.6 (C2) A SECOND consecutive swap after WS1 succeeds, and all FOUR canonical index names exist
  afterwards, including `idx_ip_org_prefixes_relationship_type`. No index is named `*_staging_*`, and
  exactly one index is named `ip_org_prefixes_pkey`.
- AC1.7 (C5/N8) A REAL full-volume `--apply` swap against `localhost:5433` completes, reports its
  `duration_s`, and that duration is recorded in the phase report. The 8–15 minute figure in WS1 item 5c
  is an EXTRAPOLATION from EVL-001's 967k-row/158–341s measurement until this gate produces a real
  number; the 20-minute tripwire is only meaningful once it can actually be tripped.

### WS2 — Second evidence source: RIR delegated-extended (`registered_holder`)

Source: the 5 RIR delegated-extended files (open HTTP, no licence constraint — unlike CAIDA's AUA):
ARIN, RIPE NCC, APNIC, LACNIC, AFRINIC. Format is pipe-delimited
`registry|cc|type|start|value|date|status|opaque-id[|extensions]`.

**Two format traps EXECUTE must handle (they are the whole parsing risk):**
- for `type=ipv4`, `value` is a **count of addresses, not a prefix length**, and the count is not
  necessarily a power of two — a range must be decomposed into one or more CIDR blocks
  (`ipaddress.summarize_address_range`, stdlib);
- header/summary lines (`2|arin|…`, `…|summary`) and `status` values other than `allocated`/`assigned`
  (`reserved`, `available`) must be skipped.

**Implementation Checklist**

7. New `apps/api/services/ip_org_rir_ingest.py`, shaped exactly like `ip_org_ingest.py`
   (httpx timeout, per-source try/except, dry-run default, status dict, never raises) — **but it MUST
   import the SHARED `IP_ORG_WRITE_LOCK_KEY` from `apps/api/models/ip_org_prefix.py` (D10) and MUST NOT
   define an advisory-lock key of its own**; a private key reintroduces F1:
   - `parse_delegated_extended(payload: bytes) -> list[RirAllocation]` — pure, total, unit-testable.
     `RirAllocation = TypedDict(prefix, registry, cc, opaque_id, allocated_on)`. IPv4 only
     (`type=ipv4`); `ipv6`/`asn` lines skipped. Uses `ipaddress.summarize_address_range` for the
     count→CIDR decomposition. A malformed line is skipped, never fatal.
     - **`date` field rule (C4):** legacy/ERX records publish `00000000`, and some records publish a
       non-8-digit value. A strict `strptime` would either raise or push the line down the
       "malformed → skip" path, silently DROPPING legitimate allocations and inflating the skip ratio that
       AC2.3 gates at <5%. Locked rule: an unparseable or zero date yields `allocated_on = None` and the
       row is **KEPT** (`valid_from` is nullable by D2, so NULL is already a legal value). Only a bad
       `start`/`value`/`type` field makes a line malformed.
   - `refresh_rir_allocations(dry_run: bool = True) -> dict` — fetches all 5 URLs; **partial success is
     allowed** (a failing RIR is logged and skipped) but the swap is refused if fewer than 3 of 5
     succeeded or if total rows is 0 — same "a refresh that cannot improve the data must not destroy it"
     contract as `ip_org_ingest`.
   - Rows written with `source="rir_delegated"`, `relationship_type="registered_holder"`,
     `org_kind="registry"`, `org_name = opaque_id.lower()[:200]`,
     `org_name_raw = f"{registry}:{cc}:{opaque_id}"[:200]`, **`asn = None`** (D13 — this evidence class
     carries no ASN; NEVER write `0`), `valid_from = allocated_on` (may be `None` per the C4 rule above).
   - Calls `_load_staging_and_swap(..., source="rir_delegated", carry_over=True)`.
8. Config (`apps/api/config.py`, new block `## ─── IP-org evidence graph (Phase 3) ───`):
   `ip_org_rir_ingest_enabled: bool = False`, `ip_org_rir_delegated_urls: str` (comma-separated, 5
   defaults), `ip_org_rir_refresh_interval_hours: int = 168`.
9. `apps/api/jobs/scheduler.py`: one `add_job` gated on the flag, weekly interval + jitter, mirroring the
   existing ip_org job.
10. `scripts/refresh_ip_org.py`: add `--source {caida,rir,rpki,all}` (default `caida`, preserving today's
    behavior); the existing fail-closed local-host guard applies unchanged to every source.

**Acceptance Criteria — WS2**

- AC2.1 `parse_delegated_extended` decomposes a non-power-of-two range into the exact minimal CIDR set.
  **Corrected expected value (C3 — the pre-supplement `/24 + /23` was WRONG; `8.8.9.0/23` is not even a
  valid network).** Verified by execution of
  `ipaddress.summarize_address_range(IPv4Address('8.8.8.0'), IPv4Address('8.8.10.255'))`:

  | Fixture line | Expected output (exact, ordered) |
  |---|---|
  | `arin\|US\|ipv4\|8.8.8.0\|768\|20200101\|allocated\|XX-1-ARIN` | `['8.8.8.0/23', '8.8.10.0/24']` |

  The test asserts this list verbatim. This AC is itself an instance of the Test Infra note below: the
  pre-supplement value was an invented, unexecuted fixture — exactly the defect class that produced the
  Phase 1 `organizationId` bug.
- AC2.2 Header, summary, `reserved` and `available` lines produce zero rows.
- AC2.3 A live dry-run against all 5 RIRs parses > 200,000 allocations with a skip ratio < 5%, and the
  counts are independently reproducible by re-parsing the raw files.
- AC2.4 With `ip_org_fusion_enabled=False`, v1 `lookup_ip_org` results are unchanged after RIR rows land
  (proves the `org_kind='registry'` isolation of D9).
- AC2.5 (D13) RIR rows land with `asn IS NULL`; `SELECT count(*) FROM ip_org_prefixes WHERE asn = 0`
  returns 0; the v1 lookup path never observes a NULL asn (it filters `org_kind='org'`).
- AC2.6 (C4) A fixture batch containing `00000000` and a short/garbage date yields rows with
  `allocated_on IS None` — KEPT, not skipped — and those lines do not count toward the skip ratio.

### WS3 — RPKI ROA cross-check (`rpki_authorizer`)

Source: `https://rpki.cloudflare.com/rpki.json` (open, no auth), shape
`{"roas": [{"prefix": "1.0.0.0/24", "maxLength": 24, "asn": "AS13335"}, …]}`. RIPE's validated-ROA JSON is
the documented fallback URL if Cloudflare's is unavailable.

**Implementation Checklist**

11. Migration (same revision as WS1 — one migration for the phase): new table `rpki_roas` —
    `prefix` CIDR NOT NULL + GiST `inet_ops` index, `asn` Integer NOT NULL, `max_length` Integer NOT NULL,
    plus `Base`'s `id`/`created_at`/`updated_at`. New model `apps/api/models/rpki_roa.py`.
12. New `apps/api/services/rpki_ingest.py`:
    - `parse_rpki_json(payload: bytes) -> list[Roa]` — pure; tolerates both `"AS13335"` and `13335` ASN
      spellings; skips IPv6 and malformed entries.
    - `refresh_rpki_roas(dry_run=True) -> dict` — same fail-open + staging-swap shape. This table has one
      source, so its swap is the simple whole-table form (no carry-over), and per D10 it uses its OWN
      advisory-lock key `beam_rpki_ingest` (it never writes `ip_org_prefixes`).
    - **Max-bytes guard (C8) — required, not optional.** `rpki.json` is expected at **~50–100 MB
      uncompressed** (roughly 400k–700k ROAs), materially larger than the gzipped CAIDA files, and the
      existing `_get` helper returns `resp.content` unbounded before `json.loads` roughly doubles peak
      RSS (~500 MB). Add `ip_org_rpki_max_bytes: int = 209_715_200` (200 MB) and stream the response
      (`client.stream("GET", url)` + `aiter_bytes`), aborting as soon as the accumulated byte count
      exceeds the cap. Exceeding the cap is a normal fail-open outcome:
      `{"status": "error", "error": "rpki payload exceeded max bytes"}` — old ROA data is kept, nothing is
      swapped. Do NOT raise, and do NOT read the whole body first and check its length afterwards; that
      defeats the purpose of the guard.
13. New pure function in `apps/api/services/rpki_validate.py`:
    `validate_origin(prefix: str, asn: int, roas: Sequence[Roa]) -> Literal["valid","invalid","notfound"]`
    implementing RFC 6811 route-origin validation — VALID when a covering ROA exists whose `asn` matches
    and `masklen(prefix) <= max_length`; INVALID when a covering ROA exists but none matches; NOTFOUND
    when no covering ROA exists. **The three-state distinction is load-bearing**: NOTFOUND must never be
    scored as INVALID — most of the routing table is simply unsigned, and penalizing that would down-rank
    the majority of legitimate corporate prefixes.
14. Config: `ip_org_rpki_ingest_enabled: bool = False`, `ip_org_rpki_json_url: str`,
    `ip_org_rpki_refresh_interval_hours: int = 24`. Scheduler `add_job` + CLI `--source rpki`.

**Acceptance Criteria — WS3**

- AC3.1 `validate_origin` returns exactly the RFC 6811 verdict across a table-driven fixture set including:
  exact match, more-specific-within-maxLength, more-specific-beyond-maxLength (INVALID), wrong-ASN
  (INVALID), and uncovered prefix (NOTFOUND).
- AC3.2 A live dry-run parses > 400,000 ROAs from the real endpoint with 0 fatal errors.
- AC3.3 **(EXTENDED in supplement cycle 2 — N4.)** Two measurements, not one:
  (a) the `rpki_roas` GiST covering-prefix query returns all covering ROAs for a test IP in < 10ms warm;
  (b) the **FULL `lookup_ip_org_v2` round trip** (all 3 warm-cache queries + fusion) completes in < 15ms
  warm on the loaded corpus, with an index scan — not a sequential scan — on every leg. Measuring only
  (a) would have left the 3-4× query amplification on the live resolver path entirely unmeasured.
- AC3.4 (C8) A simulated oversize response aborts the fetch once the cap is passed, returns
  `{"status": "error", …}`, never calls `json.loads`, and leaves any previously loaded `rpki_roas` rows
  untouched.

### WS4 — Confidence fusion + lookup v2 + domain mapping

**Implementation Checklist**

15. New `apps/api/services/ip_org_fusion.py` — **pure, no I/O, fully unit-testable**:

    ```
    OrgHypothesis = TypedDict:
      organization: str            # normalized org_name from the route_origin row
      organization_raw: str | None
      domain: str | None
      classification: str          # D12 vocabulary, EXACTLY: 'disputed_origin'
                                   # | 'likely_operational_customer' | 'registered_operator'
                                   # | 'unclassified'   (see the D12 derivation table)
      confidence: float            # clamped [0.05, 0.65]
      relationship_types: list[str]
      evidence: list[str]          # human-readable, per research §2.3
      uncertainty: list[str]
    ```

    `fuse_org_hypothesis(route_row, rir_rows, rpki_state) -> OrgHypothesis | None`. Additive weights, no ML:

    **Corrected weight table** (PVL-1 supplement: shared-hosting penalty DELETED per D11/F3; the
    no-coverage signal SPLIT per C6; "covering allocation" disambiguated per C7):

    | Signal | Δ | Condition |
    |---|---|---|
    | base `route_origin` | **0.45** | a `route_origin` row exists (matches today's constant → parity at single evidence) |
    | allocation specificity, exact | +0.15 | announced prefix == its **most-specific covering** RIR allocation prefix (holder announces its own space) |
    | allocation specificity, neutral band | 0.00 | announced prefix is **1–3 bits** more specific than its most-specific covering allocation (C7 — too small to distinguish sub-delegation from ordinary subnetting) |
    | allocation specificity, sub-delegated | −0.05 | announced prefix is **≥ 4 bits** more specific than its most-specific covering allocation |
    | RPKI `valid` | +0.15 | `validate_origin` == valid |
    | RPKI `invalid` | −0.20 | `validate_origin` == invalid |
    | RPKI `notfound` | 0.00 | explicitly neutral — most of the routing table is unsigned (WS3 item 13) |
    | RIR corpus ABSENT | 0.00 | **zero `registered_holder` rows exist in the table at all** → neutral + `uncertainty` entry (C6) |
    | RIR corpus present, prefix uncovered | −0.05 | corpus loaded, but no allocation covers this prefix (a real, evidenced anomaly) |

    **Determinism rules (C7 — all three are part of the locked contract):**
    1. "Covering allocation" ALWAYS means the **most-specific** covering `registered_holder` row
       (`ORDER BY masklen(prefix) DESC LIMIT 1`), never an arbitrary one — a /8 and a /16 can both cover.
    2. The four allocation-specificity rows (exact / neutral band / sub-delegated / uncovered) are
       **mutually exclusive and exhaustive**; exactly one fires per call.
    3. The corpus-absent test is `SELECT EXISTS(SELECT 1 FROM ip_org_prefixes WHERE relationship_type =
       'registered_holder')`, passed into the pure function as a boolean — `fuse_org_hypothesis` performs
       no I/O (AC4.1). **It is NOT re-evaluated per lookup (corrected in supplement cycle 2 — N4).** The
       value changes only when an ingest swap runs, so it is memoized in a module-level cache with a
       300-second TTL, plus an invalidation call at the end of every successful swap
       (`_load_staging_and_swap`, both callers). Cold/expired cache = one extra cheap query; warm = zero.
       **The 300s TTL is the REAL staleness bound; the invalidation is a same-process optimization only
       (PVL-3 / P4).** The swap runs in the APScheduler job process or the one-shot CLI, while
       `lookup_ip_org_v2` reads in the API web process and across replicas — so for every actual reader
       the invalidation NEVER fires and the TTL is the only thing bounding staleness. The outcome is
       still correct (staleness ≤ 300s, and a stale `False` costs only a neutral 0.00 plus an
       uncertainty string instead of the evidenced −0.05). This is recorded so a later refactor does not
       delete the TTL believing invalidation covers it — it does not.
    4. **The `−0.15 org_kind ∈ {datacenter, cdn}` penalty is DELETED.** Under D11, v2 filters
       `org_kind = 'org'`, so no datacenter/cdn/eyeball prefix ever reaches fusion. The penalty was dead
       code whose presence implied v2 might drop the filter.

    `classification` is derived from the **D12 decision table** (first matching row wins; total and
    deterministic). Every applied signal appends a string to `evidence`; every relevant non-applied one
    appends to `uncertainty` (e.g. `"prefix is sub-delegated from a larger allocation — the announcing AS
    may be a provider"`, `"no RIR allocation corpus is loaded — registration was not cross-checked"`).
    Final `confidence = clamp(sum, 0.05, 0.65)`.

16. `apps/api/services/ip_org_lookup.py`: add
    `lookup_ip_org_v2(db, ip) -> OrgHypothesis | None`:
    - **route_origin selection uses the SAME predicate as v1 (D11 — non-negotiable):**
      `WHERE prefix >>= CAST(:ip AS inet) AND org_kind = 'org' AND relationship_type = 'route_origin'
       ORDER BY masklen(prefix) DESC LIMIT 1`.
      A `datacenter` / `cdn` / `eyeball` / `registry` prefix therefore returns `None` — no hypothesis, no
      `company_graph` write, at any confidence. This is the phase's main safety property; a gate proves it
      (G11) precisely so a future refactor cannot quietly relax it.
    - most-specific covering `registered_holder` row (`ORDER BY masklen DESC LIMIT 1`, no `asn` predicate
      per D13 touchpoint 10), plus the corpus-present boolean (C7 rule 3), plus the covering `rpki_roas`
      query → `validate_origin` → all fed into `fuse_org_hypothesis`.
    - Same fail-open contract as v1 (`None` on any error, `rollback()` first).
    - **Query budget (N4).** v1 issued ONE query; v2 issues **three** on a warm corpus-probe cache
      (route_origin, covering `registered_holder`, covering `rpki_roas`) and four on a cold one. This sits
      on the live resolver path whose stated heritage is a sub-5ms index scan, so the budget is explicit:
      **the full `lookup_ip_org_v2` round trip must stay under 15ms warm** on the loaded local corpus.
      All three queries are GiST/btree index lookups against tables that are already indexed for exactly
      this access pattern; if the measured total exceeds 15ms, EXECUTE raises it as a new finding rather
      than absorbing it. Gate: G8 (extended per N4) measures the FULL round trip, not one query.
    **`lookup_ip_org` (v1) is kept unchanged** as the flag-off path.
17. `apps/api/services/company_resolver.py` `_resolve_via_local_ip_org`: branch on
    `settings.ip_org_fusion_enabled` — when on, call v2 and write through with
    `confidence=hypothesis["confidence"]` (source still `"rir_asn"`), and log
    `ip_org_fusion_scored` with the evidence-count and confidence (no PII). When off, the existing v1
    code path is untouched. The function's return contract (`str | None` domain) is unchanged.
18. Domain mapping — migration adds `ip_org_domain_map` (`org_name` String(200) PK/unique, `domain`
    String(253) nullable, `source` String(20) — Phase 3 writes exactly two values, `heuristic`
    (accepted, corroborated) and `heuristic_uncorroborated` (rejected, `domain` NULL; the `hunter` value
    is dropped with the leg per D7), `attempts` Integer default 0, `last_attempt_at` DateTime, plus
    `Base` columns). New `apps/api/services/ip_org_domain_map.py`:
    - `resolve_org_domain(db, org_name) -> str | None` — read the map first; on miss, generate at most
      2 candidates by the **D14 locked slug algorithm** (never an ad-hoc join), probe DNS A/AAAA via the
      already-present `dnspython`, and accept a resolving candidate ONLY if **D14 corroboration C-a**
      holds. **Implement C-a ONLY — C-b is documented-future and MUST NOT be coded in Phase 3**
      (D14 / PVL-4 Q2); it is unreachable against every current `company_graph` writer. **There is no Hunter leg and no other paid leg (D7/F2).** The result —
      accepted, rejected-uncorroborated (`source='heuristic_uncorroborated'`, `domain=NULL`), or
      no-DNS-answer — is written to the map; `attempts` increments so a repeatedly-failing org is skipped
      after `ip_org_domain_max_attempts` (default 3).
    - **Test hermeticity (P2) — mandatory.** `tests/unit` is the no-external-deps lane
      (`process/context/tests/all-tests.md`), so the `dnspython` probe MUST be monkeypatched in EVERY
      unit-lane test that touches `resolve_org_domain` (AC4.8, AC4.9, AC4.10, AC4.11, gates G3/G18).
      EXECUTE injects the resolver through a single seam (module-level function or constructor arg) so
      one `monkeypatch.setattr` covers every case. **`G19` (Hybrid) is the ONLY gate that issues real DNS
      queries.** Unpatched, the `delta` fixture would depend on a third party continuing to host
      `delta.com` — a flaky, network-dependent "unit" test and a violation of the lane's contract.
    - **The daily budget governs the DNS leg (C13), which is now the only leg.** The corpus is 102,624
      orgs; an unbudgeted per-lookup DNS probe is an unbounded outbound fan-out from the resolver path.
      `ip_org_domain_lookup_daily_budget` (default 200) caps *live DNS probes per day*, counted in Redis
      under a day-stamped key with the same fail-open posture as the rest of this phase (Redis
      unavailable → treat the budget as EXHAUSTED, i.e. skip the probe and return the cached/None value —
      fail CLOSED on spend, fail OPEN on resolution).
    - Map READS are never budgeted — only live probes are. A negative-cached org costs nothing.
    - **Coverage depends on a populated `company_graph` (Q1).** C-a can only corroborate against rows
      that exist. `company_graph_enabled` defaults `False`, so in an environment where it has never been
      on, `resolve_org_domain` correctly returns `None` for EVERY org — the feature is inert by
      construction, not broken. This is why G19 seeds the surface before measuring, and why enabling
      `ip_org_domain_mapping_enabled` without `company_graph_enabled` is pointless rather than harmful.
    - Wired into `lookup_ip_org_v2` to populate `OrgHypothesis.domain`; a domain hit is what finally makes
      `resolve_company_cached` return a real domain from the ip_org rung.
    - Config: `ip_org_domain_mapping_enabled: bool = False`,
      `ip_org_domain_lookup_daily_budget: int = 200` (live DNS probes/day),
      `ip_org_domain_max_attempts: int = 3`.

**Acceptance Criteria — WS4**

- AC4.1 `fuse_org_hypothesis` is pure (no DB/network import at module scope) and table-driven tests cover
  every weight row above plus both clamp boundaries.
- AC4.2 **(RESTATED per C6 — the pre-supplement version encoded the bug as the expectation.)** The
  no-evidence baseline must not silently downgrade every hit merely because the RIR corpus was never
  ingested (the flags are independent and both default OFF, so this is the DEFAULT state, not an edge
  case). Two distinct cases, both asserted:

  | Input | Expected `confidence` | Expected side-effect |
  |---|---|---|
  | route_origin only, RPKI `notfound`, **RIR corpus ABSENT** | **0.45** (exact Phase-2 parity) | ≥1 `uncertainty` entry naming the missing corpus; `classification == 'unclassified'` |
  | route_origin only, RPKI `notfound`, **RIR corpus PRESENT but prefix uncovered** | **0.40** (0.45 − 0.05) | ≥1 `uncertainty` entry naming the uncovered prefix; `classification == 'unclassified'` |

  Fusion therefore never *raises* confidence over Phase 2 on the same evidence, and never *lowers* it for
  a reason unrelated to evidence.
- AC4.2a (D12/F4) **(RESTATED in supplement cycle 2 — N2.)** `classification` is total and
  deterministic under FIRST-MATCH ordering. A table-driven test exercises **every one of the five D12
  rows** and asserts the returned value. The property test asserts that **exactly one row is SELECTED
  under first-match ordering** for every input, and that the returned value always lies inside the
  4-value vocabulary — `registry_only` and `likely_infrastructure` must never be returned.

  The cycle-1 wording ("exactly one condition matches per input") specified a test that must FAIL on a
  legitimate input: D12 row 1 (`RPKI invalid`) deliberately overlaps rows 2–5, because an RPKI-invalid
  prefix also has an allocation state. Overlap is the intended design — first-match is what makes the
  function total — so the assertion is about SELECTION, not about matching. Mutual exclusivity is
  claimed ONLY for rows 2–5, which genuinely partition the allocation-specificity space (this is the
  same partition as C7 determinism rule 2); a separate assertion covers that narrower claim.
- AC4.3 Fused confidence never exceeds 0.65 nor drops below 0.05, for any input.
- AC4.4 `OrgHypothesis` always carries at least one `evidence` string and, when confidence < 0.5, at least
  one `uncertainty` string.
- AC4.4a (D11/F3) **With `ip_org_fusion_enabled=ON`, `lookup_ip_org_v2` returns `None` and
  `_resolve_via_local_ip_org` writes ZERO `company_graph` rows for every prefix whose `org_kind` is
  `datacenter`, `cdn`, `eyeball`, or `registry`.** Asserted per org_kind, at the fusion-ON path, on both
  the lookup return value and the absence of a `company_graph` row. This is the anti-`cdurham@fastly.com`
  gate; it must fail loudly if anyone relaxes the v2 predicate.
- AC4.5 With `ip_org_fusion_enabled=False`, `resolve_company_cached` behavior and the written
  `company_graph` row (`source="rir_asn"`, `confidence=0.45`) are byte-identical to Phase 2.
- AC4.6 With fusion on, exactly ONE `company_graph` row per IP originates from the ip_org path
  (no second source value introduced).
- AC4.7 A source swap (`refresh_ip_org_dataset --apply`) does not clear any `ip_org_domain_map` row.
- AC4.8 **(RESTATED in supplement cycle 2 — N6.)** The domain heuristic never fabricates, in EITHER
  failure mode:
  (a) no DNS answer → returns `None`, writes a negative map row (the original, weaker assertion); and
  (b) **DNS answer present but NO D14 corroboration → still returns `None`**, and writes
  `source='heuristic_uncorroborated'` with `domain IS NULL`. Asserted with the `delta` fixture: org
  `delta`, candidate `delta.com` resolving, zero corroborating `company_graph` rows → result `None`, and
  no `company_graph` row is written by the ip_org path.
- AC4.9 (C13) With the daily DNS budget exhausted (or Redis unavailable), `resolve_org_domain` issues
  ZERO live DNS queries and still returns any map-cached value.
- AC4.10 (D14) The slug transform is exactly the D14 algorithm, table-driven:
  `"deloitte touche tohmatsu"` → `['deloittetouchetohmatsu.com', 'deloitte-touche-tohmatsu.com']`;
  `"microsoft"` → `['microsoft.com']`; `""` → `[]`. Never more than 2 candidates; `.com` only.
- AC4.11 (D14) A corroborated candidate IS accepted **via C-a** (the only live path): seeded with a `company_graph` row whose `ip` lies
  inside one of the org's own prefixes and whose `domain` equals the candidate (C-a), `resolve_org_domain`
  returns the domain and writes `source='heuristic'`. **The C-b half of this AC is deleted** — see
  AC4.11b; asserting it would be a vacuous green (PVL-3 / P1).
- AC4.11b (D14/P1/Q2) **C-b is NOT implemented, and the canary proves the precondition still holds.**
  Phase 3 ships no C-b code (Q2 — an unreachable branch no gate can exercise is dead weight); the rule
  survives as D14 documentation + **KG-4**. The only assertion is a **negative canary**: over the real
  `company_graph` writer set, zero rows satisfy C-b's predicate
  (`domain IS NOT NULL AND company_name IS NOT NULL`). Its job is to FAIL LOUDLY the day a future writer
  emits name+domain together — at which point C-b needs a deliberate design pass: its own gate PLUS the
  feedback-loop guard named in D14. The canary must never be read as "C-b works".
- AC4.12 (N7, **RESTATED per Q1**) The domain heuristic's coverage is MEASURED against a NON-EMPTY
  corroboration surface. G19 reports four counts over the 500-org sample (candidates generated /
  DNS-resolving / corroborated-accepted / rejected-uncorroborated) **plus the corroboration-surface
  size** — how many sampled orgs have ≥1 `company_graph` row after the mandatory seeding step.
  There is no pass/fail threshold on the hit rate itself — Phase 3 does not know the right number and
  inventing one would be theater. But two outcomes are **INVALID measurements, not passes**:
  (a) the seeding step was skipped or `company_graph_enabled` was left `False`;
  (b) the corroboration-surface size is 0 — every org had an empty surface, so 0 accepted proves
  nothing about the heuristic.
  In either case G19 is recorded FAILED-INVALID and re-run after seeding. A 0% hit rate is only a real
  result when the surface was non-empty. This closes the cycle-4 hole where the pre-Q1 wording counted
  "0 accepted, nothing seeded" as a valid green measurement of nothing.
- AC4.13 (P6, **EXTENDED per Q1**) G20's floor is a BLOCKING condition, not an observation: ≥1
  clearly-wrong org↔domain pair in the `min(30, |accepted|)` sample means D14's corroboration is
  insufficient and `ip_org_domain_mapping_enabled` must NOT be enabled until the rule is strengthened
  and G20 re-runs clean. **An empty accepted set does NOT satisfy this AC** — with nothing to sample the
  floor is UNPROVEN, G20 is `UNRUN`, and the flag stays blocked. "No false positives found because there
  was nothing to look at" is not evidence of safety. Recorded in the phase report either way.

## Touchpoints

| File | Change |
|---|---|
| `apps/api/migrations/versions/<rev>_add_ip_org_evidence_graph.py` | NEW — 3 columns + backfill + `rpki_roas` + `ip_org_domain_map` |
| `apps/api/models/ip_org_prefix.py` | 3 new columns + `relationship_type` index + `RELATIONSHIP_TYPES`; `asn` → **nullable** with a docstring that says NULL and **never** the word "sentinel" (D13); `IP_ORG_WRITE_LOCK_KEY` relocated here (D10). *(Two prior rows were merged here in supplement cycle 2 — N3; they disagreed, and the older one carried docstring wording D13 forbids. D13 wins on any Touchpoints-vs-decision conflict, per execute instruction E7.)* |
| `apps/api/models/rpki_roa.py` | NEW |
| `apps/api/models/ip_org_domain_map.py` | NEW |
| `apps/api/services/ip_org_ingest.py` | evidence fields on rows; `carry_over` swap; source-count log |
| `apps/api/services/ip_org_rir_ingest.py` | NEW |
| `apps/api/services/rpki_ingest.py` | NEW |
| `apps/api/services/rpki_validate.py` | NEW (pure) |
| `apps/api/services/ip_org_fusion.py` | NEW (pure) |
| `apps/api/services/ip_org_domain_map.py` | NEW — D14 slug algorithm + corroboration reads against `company_graph` and `ip_org_prefixes` (read-only) |
| `apps/api/services/ip_org_lookup.py` | add v2; v1 untouched |
| `apps/api/services/company_resolver.py` | `_resolve_via_local_ip_org` flag branch only (~15 lines) |
| `apps/api/config.py` | ~10 new settings, all default OFF/safe |
| `apps/api/jobs/scheduler.py` | 2 new `add_job` calls, flag-gated |
| `scripts/refresh_ip_org.py` | `--source` argument |
| `tests/unit/test_ip_org_rir_ingest.py`, `test_rpki_ingest.py`, `test_rpki_validate.py`, `test_ip_org_fusion.py`, `test_ip_org_domain_map.py` | NEW |
| `tests/unit/test_ip_org_ingest.py`, `test_ip_org_lookup.py` | extended |
| `tests/integration/test_ip_org_pipeline.py` | extended (carry-over swap, v2 end-to-end) |

Read-only for context: `apps/api/models/company_graph.py`, `apps/api/services/identity_resolver.py`,
`apps/api/services/asn_lookup.py`.

## Public Contracts

| Contract | Before | After | Compatibility |
|---|---|---|---|
| `lookup_ip_org(db, ip)` | `IpOrgMatch \| None` | unchanged | additive — v1 preserved verbatim |
| `lookup_ip_org_v2(db, ip)` | — | `OrgHypothesis \| None` | NEW |
| `resolve_company_cached(ip, db)` | `str \| None` | `str \| None` | unchanged; may now return a domain where it returned None (WS4 item 18) |
| `company_graph` row from ip_org | `source="rir_asn"`, conf `0.45` | same source, conf = fused ∈ [0.05, 0.65] | flag-gated; one row, no new source value |
| `ip_org_prefixes` columns | 8 | 11 | additive, defaulted |
| `ip_org_prefixes.asn` | `Integer NOT NULL` | `Integer NULL` (D13) | widening — no existing reader breaks; downgrade requires deleting NULL-asn rows first |
| `IpOrgMatch.asn: int` | `int` | unchanged | verified NON-touchpoint: v1's `org_kind='org'` filter means it never observes a NULL |
| CLI `scripts/refresh_ip_org.py` | dry-run default, `--apply` | `+ --source` (defaults to today's behavior) | backwards-compatible |

No HTTP route, no schema visible to `apps/web`, no change to any identity-side contract.

## Blast Radius

- **Scale:** ~18 files (10 new source, 6 new/extended test, 2 modified core), 1 migration, 3 new tables/columns sets.
- **Packages:** `apps/api` only (models, services, jobs, config, scripts) + `tests/`.
- **Risk class:** *schema/data migration* (additive, defaulted, reversible) and *scheduled-job/runtime*
  (two new APScheduler jobs, both flag-OFF). **No auth, no billing, no public API, no PII.** No
  identity-side surface (`beam_identity_graph`, fingerprint candidate/identified policy) is read or
  written — see Out of Scope.
- **Highest-risk single change:** the `carry_over` rework of `_load_staging_and_swap` (WS1 item 5). It sits
  in the only code path that can destroy 967k rows of loaded data. Mitigations: fail-open contract kept,
  post-swap per-source count logging (WS1 item 6), and a dedicated integration gate (G4 below).
- **Second-highest:** the `_resolve_via_local_ip_org` branch — it is inside the live resolver. Mitigated by
  keeping v1 the flag-off path, by AC4.5's byte-identical assertion, and by D11's `org_kind='org'` filter
  in v2 (gate G11) which is what prevents a datacenter/CDN/eyeball prefix from ever being written to
  `company_graph` as a company.
- **Fabrication risk (added by PVL-2):** the domain-mapping leg can attach a WRONG company domain to an
  org (`delta` → `delta.com`, the airline) which then feeds domain-keyed enrichment. Closed by D14's
  mandatory corroboration (AC4.8 part (b), G20) and bounded by `ip_org_domain_mapping_enabled`
  defaulting OFF.
- **Concurrency risk (added by PVL-1):** two scheduled jobs now write `ip_org_prefixes`. D10's single
  shared advisory lock is the only thing making the D1 carry-over correct; gate G12 exists solely to
  prove that serialization holds.
- **Rollback:** flags OFF restores Phase 2 behavior with no deploy; the migration downgrade is clean and
  drops only additive objects.

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| G1 `.venv/bin/python3.11 -m pytest tests/unit/test_ip_org_fusion.py tests/unit/test_rpki_validate.py -q` | Fully-Automated | AC4.1, AC4.2, AC4.2a, AC4.3, AC4.4, AC3.1 *(criterion column restated in supplement cycle 2 — N10: it predated AC4.2a, which was claimed by no gate)* |
| G2 `.venv/bin/python3.11 -m pytest tests/unit/test_ip_org_rir_ingest.py tests/unit/test_rpki_ingest.py -q` | Fully-Automated | AC2.1, AC2.2 |
| G3 `.venv/bin/python3.11 -m pytest tests/unit/test_ip_org_ingest.py tests/unit/test_ip_org_lookup.py tests/unit/test_company_resolver.py tests/unit/test_ip_org_domain_map.py -q` | Fully-Automated | AC1.4, AC4.5, AC4.6, AC4.8 |
| G4 `.venv/bin/python3.11 -m pytest tests/integration/test_ip_org_pipeline.py -q` (needs local PG 5433) | Hybrid | AC1.2, AC1.3, AC2.4, AC4.7 |
| G5 alembic single head + live up/down round-trip vs `localhost:5433` | Hybrid | AC1.1 |
| G6 `python scripts/refresh_ip_org.py --source rir` (dry-run, live 5 RIRs) + independent re-parse of the raw files | Hybrid | AC2.3 |
| G7 `python scripts/refresh_ip_org.py --source rpki` (dry-run, live endpoint) | Hybrid | AC3.2 |
| G8 `EXPLAIN ANALYZE` **the covering-ROA query AND the full `lookup_ip_org_v2` round trip** (3 warm-cache queries + fusion) on loaded tables; judge index-scan presence on every leg and the <15ms warm total | Agent-Probe | AC3.3 (both parts (a) and (b)) |
| G9 full unit lane `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` — **baseline RE-MEASURED at EXECUTE start and recorded in the phase report (C9); do NOT assert a remembered number.** Gate = the failure SET does not grow beyond that measured baseline | Fully-Automated | no-regression |
| G10 spot-review 20 fused hypotheses against known corporate/hosting prefixes for plausibility of `classification` + `uncertainty` text | Agent-Probe | AC4.4 (judgment: is the stated uncertainty honest?) |
| G11 **NEW (F3/C12d)** `.venv/bin/python3.11 -m pytest tests/unit/test_ip_org_lookup.py -k org_kind_isolation -q` — fusion ON, one prefix per `org_kind`; assert v2 returns `None` and zero `company_graph` rows written for `datacenter` / `cdn` / `eyeball` / `registry` | Fully-Automated | AC4.4a |
| G12 **NEW (F1/C12a)** `.venv/bin/python3.11 -m pytest tests/integration/test_ip_org_pipeline.py -k lock_serialization -q` — hold `IP_ORG_WRITE_LOCK_KEY` in one session, run the other refresh, assert `{"status": "locked"}`, zero writes, and both sources' row counts intact | Hybrid (needs PG 5433) | AC1.5 |
| G13 **NEW (C1/C12c)** `.venv/bin/python3.11 -m pytest tests/unit/test_ip_org_rir_ingest.py -k asn_is_null -q` + integration assertion on loaded rows | Fully-Automated + Hybrid | AC2.5 |
| G14 **NEW (C2/C12b)** existing `tests/integration/test_ip_org_pipeline.py::test_index_names_are_restored_so_a_second_swap_works`, EXTENDED to assert all 4 canonical index names incl. `idx_ip_org_prefixes_relationship_type` and exactly one `ip_org_prefixes_pkey` — must run POST-migration | Hybrid | AC1.6 |
| G15 **NEW (C10)** migration down/up round-trip **with a NULL-asn `rir_delegated` row seeded first** — proves the DELETE-before-NOT-NULL downgrade order on real data | Hybrid | AC1.1 (extended), AC2.5 |
| G16 **NEW (C8)** `.venv/bin/python3.11 -m pytest tests/unit/test_rpki_ingest.py -k max_bytes -q` — oversize response aborts mid-stream, returns `status=error`, never calls `json.loads` | Fully-Automated | AC3.4 |
| G17 **NEW (C4)** `.venv/bin/python3.11 -m pytest tests/unit/test_ip_org_rir_ingest.py -k zero_date -q` — `00000000`/garbage date → row KEPT with `allocated_on=None`, not counted as skipped | Fully-Automated | AC2.6 |
| G18 **NEW (C13)** `.venv/bin/python3.11 -m pytest tests/unit/test_ip_org_domain_map.py -k budget -q` — budget exhausted or Redis down → zero live DNS queries, map-cached value still returned | Fully-Automated | AC4.9 |
| G19 **NEW (N7), PRECONDITION HARDENED (Q1)** Domain-heuristic COVERAGE measurement over a 500-org random sample of the already-loaded 102,624-org local corpus. **MANDATORY SEEDING STEP FIRST** — C-a reads `company_graph`, but `company_graph_enabled` defaults `False` (`config.py:717`) and the local DB has no resolver-run history, so an unseeded run measures an EMPTY corroboration surface and trivially reports 0 accepted. Required sequence: (1) collect the sampled orgs' prefixes from `ip_org_prefixes`; (2) with `company_graph_enabled=True`, run the existing rDNS resolver over representative IPs drawn from those prefixes so `company_graph` accumulates real rDNS rows; (3) record how many of the 500 orgs ended up with ≥1 `company_graph` row — this is the **corroboration-surface size** and must be reported alongside the hit rate; (4) only then run `resolve_org_domain` over the sample within a raised one-off budget, recording candidates generated / DNS-resolving / corroborated-accepted / rejected-uncorroborated | Hybrid (PG 5433 + network) | AC4.12 |
| G20 **NEW (N6/N7), SAMPLING DEFINED (Q1)** False-positive eyeball over `min(30, |accepted|)` drawn from G19's ACCEPTED set — judge whether each domain plausibly belongs to that organization. **If `|accepted| == 0` the gate is UNRUN, not passed**: it is recorded as `G20: UNRUN — empty accepted set`, AC4.13's floor is UNPROVEN, and `ip_org_domain_mapping_enabled` stays blocked exactly as if the floor had been breached. A sample smaller than 30 is valid but its reduced power must be stated in the phase report. **Explicit floor (P6): ≥1 clearly-wrong pair (the `delta.com` class) in the 30-sample means D14's corroboration is INSUFFICIENT — it must be revisited and strengthened BEFORE `ip_org_domain_mapping_enabled` is flipped in any environment. Not merely recorded: it blocks the flag.** The finding must name the corroboration path that let it through | Agent-Probe | AC4.12 (judgment half), AC4.13 |
| G21 **NEW (N8)** Full-volume swap duration: real `--apply` run against `localhost:5433` with `DATABASE_URL` pinned, at production row volume, recording `duration_s` from the existing `ip_org_ingest_complete` log. Precedent exists — EVL-001 Addendum ran `--apply` three times on this exact DB | Hybrid (PG 5433) | AC1.7 |

Note on `.venv/bin/pytest`: the shebang is broken in this repo — always invoke via
`.venv/bin/python3.11 -m pytest` (see `process/context/tests/all-tests.md` and the venv memory note).

**Known-Gap residuals (each keeps its gate CONDITIONAL and gets a backlog stub at UPDATE PROCESS):**

- KG-1 Live production behavior of the fused confidence against real traffic distribution is unmeasurable
  before the operator flag flip. Backlog stub: `ip-org-fusion-live-distribution_NOTE_*`.

- KG-2 RIR opaque-id → organization NAME agreement is not proven (D8 — needs RDAP). Backlog stub:
  `ip-org-rdap-name-resolution_NOTE_*`.
- KG-3 **(C11) Fused confidence persisted into `company_graph` goes stale.** A later RIR/RPKI refresh can
  change the fusion result, but the written row keeps its old confidence until the existing staleness
  window expires (`company_graph_staleness_days = 75`). Phase 3 adds no recompute path. Accepted as a
  named known-gap rather than solved: the stale value is bounded (clamped ≤ 0.65, so it can never
  outrank a paid resolution), the existing staleness machinery already forces re-validation, and a
  recompute sweep is a new scheduled job whose blast radius belongs in its own phase. Backlog stub:
  `ip-org-fused-confidence-recompute_NOTE_*`. This keeps AC4.6's gate CONDITIONAL.
- KG-4 **(P1/Q2) D14 corroboration C-b is documented but NOT built.** No `company_graph` writer
  produces a row with both a non-NULL `domain` and a non-NULL `company_name` (writer census in D14), so
  C-b is unsatisfiable in Phase 3 — cycle 4 therefore removes the code path entirely rather than shipping
  an unreachable branch no gate can exercise. The rule survives as D14 documentation plus AC4.11b's
  negative canary. It does NOT activate automatically: the day a future writer (a paid enrichment leg)
  emits name+domain together, the canary fails and forces a deliberate design pass — its own gate AND the
  feedback-loop guard D14 names. Backlog stub: `ip-org-corroboration-cb-activation_NOTE_*`. AC4.11's gate
  stays scoped to C-a only.

## Test Infra Improvement Notes

- The integration lane is degraded by a pre-existing conftest enum-teardown race (stale `platform` ENUM,
  `engagement_attributions` teardown) — carried from EVL-001 known-gap 3. G4 will show the same
  PASS-by-union pattern until that infra debt is fixed; it is NOT a Phase 3 defect and must not be
  "fixed" by weakening G4.
- Phase 1's parser bug was masked by fixtures that *invented* the wire format
  (`organization_id` vs live `organizationId`). WS2/WS3 fixtures MUST be excerpted from a real downloaded
  file and the file's provenance recorded in the test docstring. This is the single most valuable test-infra
  rule this program has learned; treat a hand-written fixture for an external format as a defect.
- **The same defect recurred inside this plan and was caught at PVL, not at EXECUTE (C3).** The
  pre-supplement AC2.1 asserted `8.8.8.0/768 → /24 + /23`, which is not merely wrong but not even a valid
  network decomposition (`8.8.9.0/23` does not exist). It was written from reasoning, never executed.
  Corrected to the executed value `['8.8.8.0/23', '8.8.10.0/24']`. Rule for EXECUTE: **any expected value
  in a test that comes from a stdlib or external computation must be produced by RUNNING that
  computation and pasting the output**, not derived by hand. This applies to
  `summarize_address_range` output, RFC 6811 verdicts, and every fusion arithmetic expectation.
- No new test-infra debt was introduced by this supplement; the pre-existing conftest enum-teardown race
  remains the only known integration-lane degradation.

## Out of Scope (named future work, one line each)

- **ASINT-style org-family resolution** (parent/subsidiary/rebrand clustering) — needs an entity-resolution
  pipeline and unstructured web evidence; a separate program, not a workstream.
- **PSI / clean-room CRM matching** — customer-side cryptographic matching; belongs to the identity
  program, and the existing CRM connectors are its natural mount point.
- **TLS-certificate evidence** (`observed_with → domain/certificate`) — requires a certificate-transparency
  ingest, a materially larger data problem than the three sources here.
- **PeeringDB** (`network_operator` / `infrastructure_provider` relationships) — high value, but its
  facility/IX model needs its own schema; add as a 4th source after fusion is proven with three.
- **Benchmark corpus** (manually verified enterprise networks to measure fusion accuracy) — the honest
  way to prove fusion beats Phase 2; deferred because it needs human-labelled ground truth, not code.
- **RDAP name resolution** for RIR opaque-ids (D8) — ~100k rate-limited requests; needs its own budgeted,
  cached crawl job.
- **Paid org-name → domain enrichment** (Hunter `/v2/domain-search?company=`, Clearbit, or similar) —
  dropped from WS4 by D7/F2: Hunter's free tier is 25 calls/month and is shared with the identity
  waterfall, so wiring it here would consume identity-resolution quota to cover 0.02% of the org corpus.
  Revisit only with a dedicated paid key and its own budget, separate from `hunter_api_key`.
- **Fused-confidence recompute sweep** (KG-3/C11) — a scheduled job that re-fuses and re-writes
  `company_graph` rows after a RIR/RPKI refresh; new job surface, own phase.
- **Row-level temporal history** (`ip_org_prefix_history`, archive-on-swap) — D2; upgrade path kept open by
  shipping `valid_to` now.
- **IPv6** across all three sources — parsers are IPv4-only by explicit guard; the `cidr` column already
  supports v6.
- **Identity side** (`beam_identity_graph`, the fp-only-match → `candidate` demotion question raised in the
  research reference §3.2) — explicitly a different program; Phase 3 must not touch it.

## Phase Loop Progress

- [x] Step 0 — Phase entry (scope redefinition approved by user)
- [x] Step 1 — RESEARCH (`evidence-graph-research_REFERENCE_07-08-26.md` + repo mapping)
- [x] Step 2 — INNOVATE (design decisions D1–D9 locked above)
- [x] Step 3 — PLAN (this file)
- [x] Step 4 — PVL — **CONVERGED at cycle 5: `Gate: CONDITIONAL`, 0 FAILs, 0 plan-text defects.**
      Four supplement cycles closed 37/37 gaps; discovery decayed 17 → 8 → 6 → 3 → 0. Two USER
      decisions gate EXECUTE: accept the residual-risk menu (A1–A8), and choose whether the WS4
      domain half stays in Phase 3 or splits behind G19. History: cycle 1
      `Gate: BLOCKED` (4 FAILs / 13 CONCERNs). Supplement cycle 1 APPLIED
      (17/17 gaps addressed). Cycle 2: `Gate: CONDITIONAL` — all 4 FAILs verified resolved in plan
      text; 8 NEW concerns found in the supplement material (N1, N2, N3, N4, N6, N7, N8, N10).
      Supplement cycle 2 APPLIED (8/8 addressed; 25/25 cumulative). Cycle 3 re-ran from V1 and verified
      all 8 landed, finding 6 NEW concerns (P1-P6) in the cycle-2 material — all mechanically closable.
      Supplement cycle 3 APPLIED (6/6 plus all 4 nits). Cycle 4: `Gate: CONDITIONAL` (0 FAILs, 3
      CONCERNs Q1-Q3) → supplement cycle 4 APPLIED (3/3; 34/34 cumulative). **PVL must now
      RE-RUN from V1.** **EXECUTE remains NOT authorized** until that pass records `Gate: PASS` or an
      explicitly accepted CONDITIONAL.
- [x] Step 5 — EXECUTE — **COMPLETE_WITH_GAPS (07-08-26).** WS1+WS2+WS3+WS4-fusion shipped;
      WS4 item 18 (domain leg) SKIPPED per E14 / Decision 2 = Option B. 18/18 in-scope gates PASS
      (G18–G20 skipped). Unit lane 1605 passed / 0 failed (baseline 2 failed). Migration
      `c4a8f13e07b6` chained off the live head `b6f4a2d90c13` (not `a3e8d5c71f02` — head had moved;
      E1 deviation recorded). Two real defects found by live gates: 4-byte ASN overflow
      (`rpki_roas.asn` → BigInteger, fixed) and two wrong hand-derived fixtures (fixed). One new
      finding recorded not fixed: post-swap planner statistics. All four flags OFF.
      Report: `ip-org-phase3-execute_REPORT_07-08-26.md`.
- [ ] Step 6 — EVL
- [ ] Step 7 — UPDATE PROCESS

## Phase Completion Rules

- A workstream is `CODE DONE` when its checklist items are implemented and its Fully-Automated gates pass.
- A workstream is `🧪 TESTING` when Fully-Automated gates pass but a Hybrid gate is unrun (e.g. no Docker).
- A workstream reaches `✅ VERIFIED` only when every Fully-Automated AND Hybrid gate mapped to its ACs has
  passed AND User Confirmation is recorded (the user confirmed it works). Agent-Probe gates are recorded as judgments, never as proof of an AC
  on their own.
- The phase is not complete while any AC has only Known-Gap coverage — KG-1 and KG-2 above keep their
  gates CONDITIONAL by design and require backlog stubs at UPDATE PROCESS.
- `ip_org_fusion_enabled` / `ip_org_rir_ingest_enabled` / `ip_org_rpki_ingest_enabled` /
  `ip_org_domain_mapping_enabled` stay OFF at merge. Flipping any of them in a real environment is a
  separate operator action after live migration apply — same posture as `company_graph_enabled`.

## Constraints

- **No new Python dependencies.** `ipaddress`, `gzip`, `json`, `re` are stdlib; `httpx`, `dnspython` are
  already in `requirements.txt`.
- **Migration chains off the live head** — re-derive with `alembic … heads` at write time (expected
  `a3e8d5c71f02`; heads move daily in this repo, and `main` and `devjulley` currently differ).
- **`.env` points at Supabase PRODUCTION.** Pin `DATABASE_URL=localhost:5433` before any alembic or
  `--apply` command. `scripts/refresh_ip_org.py`'s fail-closed local-host guard already enforces this for
  ingest; alembic has NO such guard.
- **Do not touch identity-side files** (`beam_identity_graph`, `identity_resolver.py` fp/candidate policy,
  `models/identity_coop.py`, `services/identity_coop.py`) — concurrent program, separate track.
- Offline alembic `--sql` needs an explicit `<from>:<to>` range in this repo (unscoped fails mid-chain at
  `b7d3e9f1a4c2`).
- All human-facing logs remain PII-free (keys/ids/counts only), per repo convention.

## Resume and Execution Handoff

1. **Selected plan file:** `process/features/visitors-identity/active/ip-org-database_07-08-26/ip-org-phase-3-evidence-graph_PLAN_07-08-26.md`
2. **Last completed step:** Step 4 — PVL cycles 1 (BLOCKED) through 5 (CONDITIONAL, **CONVERGED**),
   with four plan-supplement cycles between them. Nothing implemented; no source file touched.
3. **Validate-contract status:** WRITTEN, verdict `Gate: CONDITIONAL` (cycle 5, supersedes the cycle-4
   contract). **CONVERGED — 0 FAILs and 0 plan-text defects.** Discovery decayed 17 (c1, incl. 4 FAILs)
   → 8 (c2) → 6 + 4 nits (c3) → 3 (c4) → 0 (c5); 37/37 gaps addressed across four supplement cycles.
   Cycle 5 verified all 3 cycle-4 dispositions landed, swept the C-b deletion for orphans (clean), and
   re-audited numbering (G1-G21, 33 AC ids, zero duplicates, zero dangling). **Nothing remains for the
   plan agent.** EXECUTE is gated on two USER decisions only: accept the residual-risk menu (A1-A8),
   and choose whether the WS4 domain half stays in Phase 3 or splits into a follow-on plan gated on
   G19's measurement. Read D14's coverage-tradeoff block first: C-b is documented but NOT built
   (KG-4), so domain coverage rests entirely on C-a.
4. **Supporting context loaded:** `process/context/all-context.md`, `process/context/tests/all-tests.md`,
   `evidence-graph-research_REFERENCE_07-08-26.md`, `ip-org-database_PLAN_07-08-26.md`,
   `ip-org-database-evl-iteration-001_REPORT_07-08-26.md`, and the five current implementation files
   (`models/ip_org_prefix.py`, `services/ip_org_ingest.py`, `services/ip_org_lookup.py`,
   `models/company_graph.py`, `services/company_resolver.py`).
5. **Next step for a fresh agent:** none of validation type — the plan has no open defects. Record the
   user's acceptance of A1-A8 and their Decision 2 answer in the contract's `Accepted by:` line. After
   that, EXECUTE starts at WS1 item 1 (re-derive the alembic head) and proceeds strictly
   WS1 → WS2 → WS3 → WS4, running that workstream's gates at the end of each workstream rather than
   batching all gates to the end. Branch: `devjulley`. Worktree: repo root, currently dirty with
   concurrent identity-coop work — do not commit files outside the Touchpoints table.

## Validate Contract

Status: CONDITIONAL
Date: 07-08-26
date: 2026-08-07
generated-by: inner-pvl: phase-3
supersedes: 2026-08-07 (inner-pvl: phase-3, cycle 4 — Gate: CONDITIONAL, 3 CONCERNs) — cycle 5 has current evidence
Validated by: vc-validate-agent, PVL cycle 5 — CONVERGENCE PASS (sequential single-pass; no Agent tool in
this environment, so Layer 1 / Layer 2 ran as sequential self-checks against real source files, NOT as
parallel subagents)

Parallel strategy: sequential
Rationale: 3/7 signals (S2 schema surface, S4 phase program, S7 5+ blast-radius files); sequential forced
by the absence of the Agent tool.

### ✅ CONVERGED — zero plan-text defects remain

| Cycle | Gate | Found | Closed by |
|---|---|---|---|
| 1 | BLOCKED | 4 FAILs + 13 CONCERNs | supplement 1 (verified at cycle 2) |
| 2 | CONDITIONAL | 8 CONCERNs (N-series) | supplement 2 (verified at cycle 3) |
| 3 | CONDITIONAL | 6 CONCERNs + 4 nits (P-series) | supplement 3 (verified at cycle 4) |
| 4 | CONDITIONAL | 3 CONCERNs (Q-series) | supplement 4 (verified below) |
| 5 | **CONDITIONAL** | **0 plan-text defects** | — nothing left to fix in the plan |

37/37 gaps addressed cumulatively. Discovery decayed 17 → 8 → 6 → 3 → 0; severity decayed FAILs →
design gaps → assertion defects → wording/methodology → none.

**Everything below this line is a DECISION for the user, not a defect for the plan agent.** The gate stays
CONDITIONAL only because this agent cannot accept its own verdict and because two product-level choices
are outstanding. There is no supplement work left to do.

### Net gate derivation — cycle 5

| Layer 1 dimension | Status |
|---|---|
| Infra fit | **PASS** |
| Test coverage | **PASS** — Q1's seeding precondition + FAILED-INVALID outcomes close the last hole |
| Breaking changes | **PASS** |
| Security surface | **PASS** — C-a is the sole path, guarded, fail-open; C-b unbuilt with a canary |

| Layer 2 section | Status |
|---|---|
| WS1 — Schema evolution | **PASS** |
| WS2 — RIR delegated-extended | **PASS** |
| WS3 — RPKI ROA cross-check | **PASS** |
| WS4 — Fusion + v2 + domain mapping | **PASS** (plan text); the domain half carries an open product decision, not a defect |
| V1 structural completeness | **PASS** — validator 0 failures / 0 warnings, 1448 lines |

Totals: **0 FAILs / 0 CONCERNs / 9 PASSes**

**→ Net Gate: CONDITIONAL** — 0 FAILs and 0 plan-text defects. CONDITIONAL rather than PASS because
(a) this agent may not accept its own verdict, and (b) the acceptance menu below carries real residual
risk plus two product choices the user owns. Per the orchestrator's rule: **only judgment items remain →
surface to the user.**

### Cycle-4 disposition verification (3/3 landed)

| Gap | Verified where | Verdict |
|---|---|---|
| Q1 coverage gate could measure nothing | G19 row (mandatory 4-step seeding sequence), G20 row (`min(30,\|accepted\|)`, UNRUN semantics), AC4.12 (FAILED-INVALID outcomes), AC4.13 (empty set ≠ satisfied) | **LANDED, better than requested.** I asked for a precondition and an under-30 rule; the supplement added a metric I did not think of — the **corroboration-surface size** (how many of the 500 sampled orgs ended up with ≥1 `company_graph` row). That separates "the heuristic doesn't work" from "there was nothing to corroborate against", which is exactly the ambiguity that made a 0% result uninterpretable. AC4.13's "no false positives found because there was nothing to look at is not evidence of safety" is the right instinct stated plainly |
| Q2 D14 vs AC4.11b contradiction | D14 L266-271, AC4.11b L726-732, KG-4, WS4 item L639 | **LANDED — resolved by DELETING the code path**, which was the stronger of the two options I offered. The "no design change" claim is explicitly retracted; the plan now says shipping an unreachable branch no gate can exercise is "exactly the YAGNI failure". The rule survives as documentation + KG-4 + the negative canary, so a future name+domain writer trips the canary and forces a deliberate design pass instead of silently activating untested code |
| Q3 broken corroboration table | D14 L235-238 | **LANDED** — table is contiguous and gained a `Status in Phase 3` column (`LIVE — the only implemented path` / `DOCUMENTED-FUTURE — NOT implemented`), which conveys more than the original two-column form. The C-a query-safety prose now sits below the complete table |

**C-b deletion orphan sweep (explicitly requested):** clean. WS4 item 18 says "Implement C-a ONLY — C-b
is documented-future and MUST NOT be coded in Phase 3"; AC4.11 is scoped to C-a with its C-b half deleted;
AC4.11b is the negative canary; KG-4 updated to "documented but NOT built"; Touchpoints describes
`ip_org_domain_map.py` generically as "corroboration reads … (read-only)", which stays correct; Blast
Radius cites "AC4.8 part (b)". No gate, AC, or checklist item references C-b as implementable.

**Numbering and mapping integrity (audited on the plan body, excluding the contract):** G1–G21 present,
no gaps, no duplicates. **33 AC ids declared, zero duplicates, zero dangling referents.** KG-1..KG-4 in
sequence. Nothing broke across four supplement cycles.

Sub-nit (not a defect, no action needed): D14's lead-in still reads "Both corroborations are pure local DB
reads" — true of both documented rules, and the table's Status column immediately disambiguates which one
ships.

---

### ⚠ TWO DECISIONS FOR THE USER (this agent records them; it does not make them)

### Decision 1 — accept the residual risk (the acceptance menu)

| # | What is being accepted | If it bites |
|---|---|---|
| A1 | **D14 trades most domain coverage for safety.** C-a is the entire corroboration surface | Low domain yield. Recoverable — G19 quantifies it; the named next step is a paid leg with its own budget (Out of Scope), not a relaxed guard |
| A2 | **G20's floor is a subjective 30-sample judgment** with "clearly-wrong" undefined | Asymmetric in the safe direction — it can only BLOCK the flag, never authorize it. At a true 5% FP rate, P(zero FPs in 30) ≈ 21%, so a clean G20 is a floor test ("no obvious disasters"), not a rate estimate |
| A3 | **KG-1** live fused-confidence distribution is unmeasurable before an operator flag flip | Known and bounded; backlog stub exists |
| A4 | **KG-2** RIR opaque-id → org NAME unproven (needs RDAP) | Registration evidence stays name-free in v1 by design (D8) |
| A5 | **KG-3** fused confidence goes stale in `company_graph` until the 75-day window | Bounded by the ≤0.65 clamp — a stale fused value can never outrank a paid resolution |
| A6 | **KG-4** C-b documented but not built | Canary (AC4.11b) fails loudly if the precondition ever changes |
| A7 | **No gate proves fusion is more ACCURATE than Phase 2's flat 0.45.** Every fusion gate proves internal consistency | The honest instrument — a human-labelled benchmark corpus — is named in Out of Scope. Mitigated by the ≤0.65 clamp and all four flags defaulting OFF |
| A8 | **All Hybrid gates run against `localhost:5433`.** Nothing exercises production; nothing proves behavior with any flag ON in a real environment | By design — flag flips are a separate operator action after a live migration apply |

### Decision 2 — keep the WS4 domain half in Phase 3, or split it behind G19?

**Why this is being raised now.** The domain leg narrowed on three consecutive cycles, each change correct
in isolation:

| Cycle | Change | Effect on yield |
|---|---|---|
| 1 (F2) | Hunter leg dropped | removed the paid path (which covered ~0.02% anyway) |
| 2 (N6→D14) | corroboration required | resolving-but-unverified domains now rejected |
| 3 (P1→Q2) | C-b deleted | corroboration surface halved to C-a alone |
| 4 (Q1) | measurement seeding-gated | the yield number itself now requires a deliberate seeding step to exist |

**Cumulative yield is unknown and plausibly small.** The honest case for BOTH readings:

- *Argument that marginal yield is near-zero:* C-a fires only when rDNS has already produced this exact
  domain for an IP inside the org's own prefixes. But the rDNS rung runs BEFORE ip_org in the resolution
  ladder — so for that same IP, rDNS would have returned the domain already, without the domain leg.
- *Argument that marginal yield is real:* rDNS resolves **per IP**, while the domain map is keyed **per
  org**. A domain learned from IP A inside org X's prefixes is then served for IP B in the same org's
  prefixes where rDNS fails. That generalization across an org's prefix set is genuine, non-zero value
  that the rDNS rung alone cannot provide.

Which effect dominates is exactly what G19's accepted-rate plus corroboration-surface-size will show.
Nobody knows it today.

**Option A — keep the domain half in Phase 3 (plan as written).**
Cost: ~4 additional files (`ip_org_domain_map.py`, its model, the migration table, its tests), the G19
seeding step, and two Hybrid/Agent-Probe gates. Benefit: the measurement gets produced inside this phase,
and if the yield is decent the feature ships without a second cycle. Risk: ships a table, a service and a
flag whose value is unmeasured until after they exist.

**Option B — split the domain half into a follow-on plan gated on G19.**
Phase 3 ships WS1–WS3 plus fusion and lookup v2 — the evidence-graph core, whose value (relationship
typing, multi-source corroboration, honest confidence) does not depend on domains at all. Domain mapping
becomes a small follow-on plan that starts only if G19's number justifies it. Risk / wrinkle worth
knowing: **G19 measures `resolve_org_domain`, so measuring first means either building it anyway or
writing a throwaway measurement script.** Option B is not free — it trades shipped surface for a
disposable measurement harness.

**This agent does not choose.** Both are defensible; the choice depends on how much the user values
shipping the domain surface now versus keeping Phase 3's blast radius to the evidence graph.

---

### Test gates

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC4.1, AC4.2, AC4.2a, AC4.3, AC4.4, AC3.1 | fusion weights, clamp bounds, D12 first-match totality, RFC 6811 three-state | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_ip_org_fusion.py tests/unit/test_rpki_validate.py -q` (G1) | B |
| AC2.1, AC2.2 | RIR range→CIDR decomposition; header/summary/reserved skip | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_ip_org_rir_ingest.py tests/unit/test_rpki_ingest.py -q` (G2) | B |
| AC1.4, AC4.5, AC4.6, AC4.8, AC4.10, AC4.11, AC4.11b | v1 parity flags-off; one fused row; no fabrication in either failure mode; slug algorithm; C-a acceptance; C-b canary | Fully-Automated | `… test_ip_org_ingest.py test_ip_org_lookup.py test_company_resolver.py test_ip_org_domain_map.py -q` (G3) — DNS probe monkeypatched | B |
| AC1.2, AC1.3, AC2.4, AC4.7 | backfill; carry-over swap; org_kind isolation; domain-map survives swap | Hybrid | `… tests/integration/test_ip_org_pipeline.py -q` (G4) — PG `localhost:5433` CONFIRMED LISTEN | B |
| AC1.1 | migration applies and reverses cleanly, single head | Hybrid | alembic heads + up/down/up vs `localhost:5433` (G5) | B |
| AC1.1 (ext), AC2.5 | downgrade with a NULL-asn `rir_delegated` row seeded | Hybrid | G15 | B |
| AC1.5 | CAIDA/RIR serialize on the shared lock + single-owner greps | Hybrid | `… -k lock_serialization -q` (G12) | B |
| AC1.6 | second consecutive swap keeps 4 canonical index names | Hybrid | extended second-swap test (G14) | B |
| AC1.7 | REAL full-volume `--apply` completes and reports `duration_s` | Hybrid | G21 vs `localhost:5433` | B |
| AC2.3 | live RIR dry-run >200k allocations, skip <5%, independently reproducible | Hybrid | G6 | B |
| AC2.6 | zero/garbage date → row KEPT with `allocated_on=None` | Fully-Automated | G17 | B |
| AC3.2 | live rpki.json dry-run >400k ROAs, 0 fatal | Hybrid | G7 | B |
| AC3.3 | covering-ROA query AND full v2 round trip < 15ms warm | Agent-Probe | `EXPLAIN ANALYZE` both legs (G8) | C (warm-only; cold 26–385ms per EVL-001) |
| AC3.4 | oversize rpki response aborts mid-stream, never calls `json.loads` | Fully-Automated | G16 | B |
| AC4.4a | fusion ON writes zero `company_graph` rows for datacenter/cdn/eyeball/registry | Fully-Automated | G11 | B |
| AC4.9 | budget exhausted or Redis down → zero live DNS queries | Fully-Automated | G18 | B |
| AC4.12 | domain-heuristic coverage measured against a NON-EMPTY corroboration surface; 4 counts + surface size; unseeded or surface-0 = FAILED-INVALID, not a pass | Hybrid | G19 with its mandatory 4-step seeding sequence | B |
| AC4.13 | ≥1 clearly-wrong pair in `min(30,\|accepted\|)` BLOCKS the flag; empty accepted set = UNRUN, floor UNPROVEN, flag stays blocked | Agent-Probe | G20 | B |
| no-regression | unit-lane failure set does not grow beyond a baseline re-measured at EXECUTE start | Fully-Automated | G9 | B |
| AC4.4 | stated uncertainty is honest for 20 known prefixes | Agent-Probe | G10 | C |

gap-resolution legend: A — proven now; B — fixed in this plan; C — deferred to a named later phase;
D — backlog test-building stub.

Legacy line form (retained for existing validate-contract consumers):
- fusion + rpki validate: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_ip_org_fusion.py tests/unit/test_rpki_validate.py -q`
- RIR + RPKI parsers: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_ip_org_rir_ingest.py tests/unit/test_rpki_ingest.py -q`
- v1/v2 parity + slug + C-a acceptance + C-b canary: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_ip_org_ingest.py tests/unit/test_ip_org_lookup.py tests/unit/test_company_resolver.py tests/unit/test_ip_org_domain_map.py -q`
- org_kind isolation: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_ip_org_lookup.py -k org_kind_isolation -q`
- rpki size cap: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_rpki_ingest.py -k max_bytes -q`
- zero-date keep: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_ip_org_rir_ingest.py -k zero_date -q`
- NULL-asn: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_ip_org_rir_ingest.py -k asn_is_null -q`
- DNS budget: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_ip_org_domain_map.py -k budget -q`
- full unit lane: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit -m unit -q`
- pipeline integration: `hybrid: .venv/bin/python3.11 -m pytest tests/integration/test_ip_org_pipeline.py -q + precondition local PG 5433, DATABASE_URL pinned`
- lock serialization: `hybrid: .venv/bin/python3.11 -m pytest tests/integration/test_ip_org_pipeline.py -k lock_serialization -q + precondition local PG 5433`
- migration round-trip: `hybrid: alembic heads + up/down/up vs localhost:5433 + precondition NULL-asn RIR row seeded`
- full-volume swap duration: `hybrid: real --apply vs localhost:5433 at production volume, record duration_s`
- live RIR dry-run: `hybrid: python scripts/refresh_ip_org.py --source rir + precondition network + DATABASE_URL pinned local`
- live RPKI dry-run: `hybrid: python scripts/refresh_ip_org.py --source rpki + precondition network + DATABASE_URL pinned local`
- domain-heuristic coverage: `hybrid: 500-org sample + MANDATORY company_graph seeding; unseeded or surface-size 0 = FAILED-INVALID`
- query plans: `agent-probe: EXPLAIN ANALYZE covering-ROA + FULL v2 round trip (<15ms warm)`
- domain false-positive floor: `agent-probe: min(30, |accepted|) pairs; >=1 wrong pair BLOCKS the flag; empty set = UNRUN, flag stays blocked`
- hypothesis plausibility: `agent-probe: spot-review 20 fused hypotheses`
- C-b name-agreement corroboration: `known-gap: documented, NOT built (KG-4); canary only`
- live fused-confidence distribution: `known-gap: documented (KG-1)`
- RIR opaque-id → org NAME agreement: `known-gap: documented (KG-2)`
- fused-confidence staleness: `known-gap: documented (KG-3)`

### What this coverage does NOT prove

- The unit gates prove fusion arithmetic, the slug algorithm, and parser behavior against FIXTURES. They
  do not prove the RIR delegated-extended or rpki.json wire format matches those fixtures. Only G6/G7
  touch the real format, and they validate COUNTS, not per-field semantics — the blind spot that produced
  the Phase 1 `organizationId` defect and, inside this plan, the AC2.1 error caught at PVL cycle 1.
- **Nothing compares the ip_org domain rung against the rDNS rung that runs before it.** G19 measures the
  domain leg's absolute hit rate, not its MARGINAL contribution over the existing ladder — which is the
  actual question behind Decision 2.
- AC4.11b proves C-b's precondition still holds. It proves nothing about whether C-b would work if live.
- G12 proves serialization when the test holds the lock deliberately. It does not prove the two SCHEDULED
  jobs serialize in a real APScheduler fleet with jitter.
- G21 measures ONE full-volume swap on one local machine — not production hardware or concurrent load.
- The migration round-trip does not prove the backfill's lock duration or the `CREATE INDEX` ACCESS
  EXCLUSIVE window under concurrent read load.
- No gate proves the fused confidence is more ACCURATE than Phase 2's flat 0.45 (A7).
- The <15ms v2 budget is judged WARM only; EVL-001 measured cold 26–385ms after a swap.
- G20 at a 30-sample is a floor test, not a false-positive rate estimate (A2).
- All Hybrid gates run against `localhost:5433`. Nothing exercises production, and nothing proves
  behavior with any of the four new flags ON in a real environment.

Open gaps: **none of plan-text type.** Remaining items are the acceptance menu (A1–A8) and Decision 2,
both of which are user choices, plus the four documented known-gaps:
- KG-1 live fused-confidence distribution — needs an operator flag flip.
- KG-2 RIR opaque-id → organization NAME (D8, needs RDAP).
- KG-3 fused confidence staleness — bounded by the ≤0.65 clamp.
- KG-4 C-b documented but not built — canary only.

Plan updates applied: NONE by this pass beyond this contract section, the goal block, and the Phase Loop
Progress / Resume state fields.

Execute-agent instructions:

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Re-derive the alembic head live before writing the migration; `a3e8d5c71f02` confirmed at all five PVL cycles, but heads move daily here. | WS1 item 1 |
| E2 | Pin `DATABASE_URL` to `localhost:5433/retarget_agent` before ANY alembic or `--apply` command. The repo's environment file points at Supabase PRODUCTION and alembic has no local-host guard. | any DB command |
| E3 | External-format fixtures must be excerpted from a really-downloaded file with provenance in the docstring; computed expectations must be produced by RUNNING the computation. | WS2, WS3 test authoring |
| E4 | Do not touch identity-side files. Commit only files in the Touchpoints table. | all WS |
| E5 | Run each workstream's gates at the END of that workstream, not batched. | all WS |
| E6 | Re-measure the full-unit-lane failure-set baseline before WS1 and record it in the phase report. | before WS1 |
| E7 | When the Touchpoints table and a D-decision disagree, the D-decision wins. | any conflict |
| E8 | Report observed swap duration for every `--apply`. Over 20 minutes is a NEW FINDING. | any `--apply` |
| E9 | Monkeypatch the `dnspython` probe in every `tests/unit` test; only G19 issues real DNS. | WS4 test authoring |
| E10 | Guard the C-a query with `cg.ip IS NOT NULL AND cg.ip <> ''` before the `inet` cast; treat any cast failure as fail-open. | WS4 item 18 |
| E11 | Write NO C-b code. Implement C-a only; C-b survives as D14 documentation plus the AC4.11b canary. | WS4 item 18 |
| E12 | Run G19's seeding sequence before measuring. An unseeded run, or a corroboration-surface size of 0, is FAILED-INVALID — re-run after seeding; never report it as a hit rate. | G19 |
| E13 | If G19's accepted set is empty, record `G20: UNRUN — empty accepted set`; AC4.13's floor is UNPROVEN and `ip_org_domain_mapping_enabled` stays blocked. | G20 |
| E14 | If Decision 2 resolves to Option B (split), skip WS4 item 18 and its gates entirely; ship WS1–WS3 + fusion + lookup v2, and record the split in the phase report. | WS4 entry |

Gate: CONDITIONAL (0 FAILs; 0 plan-text defects; acceptance menu A1–A8 + Decision 2 outstanding)
Accepted by: USER, 2026-08-07, in-session verbatim: "Chấp nhận A1-A8, tách domain leg, ENTER EXECUTE MODE".
A1–A8 accepted in full. Decision 2 = Option B (split domain leg out behind the G19 measurement) —
E14 applies: skip WS4 item 18 and its gates (G18–G20, AC4.8–AC4.13 domain items); ship WS1–WS3 +
fusion + lookup v2; record the split in the phase report. (Superseded text: this line previously read
acceptance (who, when, and the Decision 2 answer).

## PVL Supplement Log

*(Written by vc-plan-agent in PVL-supplement mode. The `## Validate Contract` section above is the
validator's artifact and was NOT modified by this supplement.)*

**Cycle 1 — 07-08-26 — 17/17 gaps addressed (4 FAILs, 13 CONCERNs).**

| Gap | Disposition | Where |
|---|---|---|
| F1 shared advisory lock | FIXED — new **D10**: one table-scoped `IP_ORG_WRITE_LOCK_KEY` for every writer of `ip_org_prefixes`, relocated to the model module; `rpki_roas` keeps its own key | D10; WS1 items 3, 5b; WS2 item 7; AC1.5; G12 |
| F2 Hunter mixin fiction | FIXED by **DROPPING the leg** — D7 rewritten to DNS-heuristic-only. Justification: Hunter free tier is 25 calls/month (`config.py:774`) and SHARED with the identity waterfall → 0.02% corpus coverage bought with identity-resolution quota. Paid enrichment moved to Out of Scope | D7; WS4 item 18; Out of Scope |
| F3 v2 `org_kind` filter | FIXED — new **D11**: v2 keeps `org_kind='org'`; the contradictory `−0.15 datacenter/cdn` weight DELETED; `eyeball` (26.9% of rows) explicitly excluded, not weighted | D11; WS4 items 15, 16; AC4.4a; G11 |
| F4 `classification` underspecified | FIXED — new **D12** 5-row first-match decision table; `registry_only` and `likely_infrastructure` DELETED as unreachable; vocabulary now 4 values | D12; WS4 item 15; AC4.2a |
| C1 asn NULLABLE override | APPLIED — new **D13** + the full 12-touchpoint table incl. the 4 verified NON-touchpoints | D13; WS1 item 2a; AC2.5; G13 |
| C2 `_INDEX_TARGETS` 4th entry | FIXED — the "keep unchanged" instruction is retracted; 4th marker `("(relationship_type", …)` required in the same commit as the index | WS1 item 5a; AC1.6; G14 |
| C3 AC2.1 wrong expected value | FIXED — corrected to the EXECUTED value `['8.8.8.0/23', '8.8.10.0/24']`; rule added that computed expectations must be run, not reasoned | AC2.1; Test Infra Notes |
| C4 RIR `00000000` date | FIXED — unparseable/zero date → `allocated_on=None`, row KEPT, not counted as skipped | WS2 item 7; AC2.6; G17 |
| C5 volume/duration bound | ADDRESSED — expected worst case 8–15 min single-transaction stated; **ACCEPT, do not optimize** (background job, fail-open, flag OFF so no concurrent reader); >20 min = new finding; no `statement_timeout` | WS1 item 5c |
| C6 no-coverage signal fires universally | FIXED — signal SPLIT: corpus ABSENT = 0.00 + uncertainty; corpus present but prefix uncovered = −0.05. AC4.2 restated as a 2-row table (parity 0.45 / evidenced 0.40) | WS4 item 15; AC4.2 |
| C7 covering-allocation ambiguity | FIXED — 3 determinism rules: most-specific covering only; 4 specificity outcomes mutually exclusive+exhaustive; 1–3-bit neutral band named explicitly | WS4 item 15 |
| C8 rpki.json size cap | FIXED — `ip_org_rpki_max_bytes=200MB`, streamed with abort-on-exceed (not read-then-check); expected 50–100 MB stated | WS3 item 12; AC3.4; G16 |
| C9 stale G9 baseline | FIXED — G9 now RE-MEASURES the baseline at EXECUTE start and records it in the phase report; no number asserted | G9 |
| C10 downgrade with RIR rows | FIXED — downgrade order locked (DELETE NULL-asn rows → re-add NOT NULL → drop index → drop columns → drop tables), with the reasoning required in the migration body | WS1 item 2; G15 |
| C11 stale fused confidence | ACCEPTED as named **KG-3** with rationale (bounded ≤0.65 so it cannot outrank paid; existing staleness window already forces re-validation); recompute sweep moved to Out of Scope; keeps AC4.6 CONDITIONAL | KG-3; Out of Scope |
| C12 gate coverage holes (a–d) | FIXED — 4 new gates added: G12 (lock serialization), G14 (index names), G13 (NULL-asn), G11 (org_kind filter) | Verification Evidence |
| C13 unbudgeted DNS fan-out | FIXED — the daily budget now governs the DNS leg (the only remaining leg); Redis-down → treat budget EXHAUSTED (fail closed on spend, open on resolution); map reads never budgeted | WS4 item 18; AC4.9; G18 |

Net effect on the plan: 4 new locked decisions (D10–D13), 2 decisions rewritten (D7, and D9 restated as
D11), 8 new gates (G11–G18), 9 new/restated acceptance criteria (AC1.5, AC1.6, AC2.5, AC2.6, AC3.4,
AC4.2 restated, AC4.2a, AC4.4a, AC4.9), 1 new known-gap (KG-3), 3 new Out-of-Scope entries.

Scope note: this supplement stayed inside the plan file. No source file, no test file, and no other
process artifact was modified. No blast-radius expansion: every change is a tightening of an existing
Touchpoints entry, except `apps/api/models/ip_org_prefix.py` which was already a touchpoint and now
carries two changes instead of one.

**Cycle 2 — 07-08-26 — 8/8 gaps addressed (0 FAILs, 8 CONCERNs — all in cycle-1's own new material).**

| Gap | Disposition | Where |
|---|---|---|
| N1 AC1.5 grep cannot pass | FIXED — replaced with 3 assertions that actually hold: the shared key is defined exactly once in the model module; `ip_org_rir_ingest.py` defines zero lock-key literals and imports the shared one. `rpki_ingest.py` explicitly scoped OUT (D10 grants it its own key) | AC1.5 |
| N2 AC4.2a vs D12 first-match | FIXED — AC restated as "exactly one row is SELECTED under first-match ordering"; mutual-exclusivity scoped to rows 2–5. D12's own contradictory prose corrected: row 1 OVERLAPS rows 2–5 **by design**, which is precisely why the rule is first-match | AC4.2a, D12 |
| N3 stale Touchpoints row | FIXED — the two `ip_org_prefix.py` rows MERGED; the forbidden "sentinel-asn docstring" text is gone, replaced with "says NULL and never the word sentinel" | Touchpoints |
| N4 v2 4-query hot path ungated | FIXED — corpus-EXISTS probe hoisted to a module-level 300s-TTL cache invalidated at every swap (4 queries → 3 warm); explicit **<15ms warm** round-trip budget; AC3.3 + G8 extended from one query to the FULL v2 round trip | C7 rule 3, WS4 16, AC3.3, G8 |
| N6 slug undefined + FP unguarded | FIXED — new **D14**. (1) Slug algorithm locked exactly (≤2 candidates, `''.join` then `'-'.join`, `.com` only, single-token case explicit). (2) **A DNS answer is necessary but NOT sufficient** — acceptance requires a corroboration from local DB reads: C-a a `company_graph` row whose IP lies inside one of the org's OWN prefixes carries the candidate domain, or C-b an existing name↔domain pair agrees. Uncorroborated → `domain=NULL`, `source='heuristic_uncorroborated'`, return `None`. AC4.8 restated to cover the resolving-but-wrong mode with a `delta` fixture | D14, WS4 18, AC4.8, AC4.10, AC4.11 |
| N7 no coverage number for the kept leg | FIXED — **G19** (Hybrid) measures coverage over a 500-org sample of the already-loaded local corpus; **G20** (Agent-Probe) eyeballs 30 accepted pairs for false positives. AC4.12 deliberately sets NO pass threshold — Phase 3 does not know the right number and inventing one would be theater; the gate fails only if the measurement is not produced | G19, G20, AC4.12 |
| N8 tripwire unreachable | FIXED — **G21** runs a REAL full-volume `--apply` against `localhost:5433` (precedent: EVL-001 ran it three times on this DB; PG confirmed up), producing a measured `duration_s`. The 8–15 min figure is now labelled an EXTRAPOLATION in item 5c until G21 replaces it | AC1.7, G21, WS1 5c |
| N10 AC4.2a unmapped | FIXED — G1's criterion column restated to `AC4.1, AC4.2, AC4.2a, AC4.3, AC4.4, AC3.1` | G1 |
| *(nit)* AC4.9 / KG-3 ordering | FIXED opportunistically — AC4.9 moved into numeric sequence; KG-3 moved after KG-2 | AC list, KG list |

Net effect of cycle 2: 1 new locked decision (**D14**), 3 gates added (G19–G21), 5 new/restated
acceptance criteria (AC1.7, AC4.8 restated, AC4.10, AC4.11, AC4.12), 1 decision corrected internally
(D12 first-match prose), 1 performance budget added (v2 <15ms warm, corpus probe cached).

**The honest headline of cycle 2:** D14's corroboration requirement will REDUCE domain coverage —
plausibly to single-digit percent — because it only accepts domains Beam has ALREADY seen via rDNS.
That is deliberate. An uncorroborated `{slug}.com` guess feeding domain-keyed enrichment is the
`cdurham@fastly.com` fabrication class one layer up from where D11 closed it, and a low MEASURED number
(G19) is a better input to the next decision than a high unmeasured one. If G19 shows the rate is too
low to be useful, the honest next move is a paid leg with its own budget (Out of Scope) — not a
relaxed guard.

Scope note: cycle 2, like cycle 1, stayed inside the plan file. No source file, no test file, and no
other process artifact was modified. No blast-radius expansion — `ip_org_domain_map.py` was already a
touchpoint and now additionally performs read-only corroboration queries against `company_graph` and
`ip_org_prefixes`, both already in the plan's read surface.

**Cycle 3 — 07-08-26 — 6/6 gaps addressed (0 FAILs, 6 CONCERNs), plus all 4 nits.**

| Gap | Disposition | Where |
|---|---|---|
| P1 C-b unsatisfiable (vacuous green) | FIXED — **option 1 chosen: C-b declared FORWARD-LOOKING and INERT.** I re-ran the writer census independently and confirmed it: rDNS (`company_resolver.py:568`, `:578`) and paid_ip (`identity_resolver.py:694`) write `company_name=None`; ip_org (`:615`) is the only `company_name` writer and passes `domain=match["domain"]`, NULL all phase — so no row can satisfy C-b. D14 now carries the census table, the honest-consequence paragraph says **C-a is the only live path**, AC4.11 is scoped to C-a, and the C-b half is DELETED and replaced by AC4.11b (a NEGATIVE assertion: zero rows satisfy the predicate) + **KG-4** with a backlog stub. **Option 2 explicitly rejected in-plan**: having ip_org write `domain` back would let C-b read Beam's own inference as independent corroboration — evidence laundering on the exact path D14 exists to protect — for zero Phase-3 coverage gain, since C-a already covers every case | D14, AC4.11, AC4.11b, KG-4 |
| P2 DNS probe not hermetic | FIXED — mandatory rule added: the `dnspython` probe is monkeypatched in EVERY unit-lane test touching `resolve_org_domain` (AC4.8/4.9/4.10/4.11, G3/G18), injected through a single seam so one `monkeypatch.setattr` covers all; **G19 (Hybrid) is the only gate issuing real DNS**. Unpatched, the `delta` fixture would depend on a third party hosting `delta.com` | WS4 18 |
| P3 `inet` cast on stored free text | FIXED — promoted to part of the locked C-a rule: `WHERE cg.ip IS NOT NULL AND cg.ip <> ''` before any `CAST(cg.ip AS inet)`, cast failure = normal fail-open (`rollback()` → `None`), and an explicit note that the guard REDUCES but does not eliminate the risk (a non-empty malformed string still throws) — which is why fail-open is mandatory, not decorative. Also flagged as a NEW hazard class: v1 only ever cast the bind parameter, never a stored column | D14 C-a |
| P4 cache invalidation is process-local | FIXED — restated: **the 300s TTL is the REAL staleness bound; invalidation is a same-process optimization only.** The swap runs in the scheduler/CLI process, reads happen in the API process and across replicas, so for real readers invalidation never fires. Recorded explicitly so a later refactor does not delete the TTL believing invalidation covers it | C7 rule 3 |
| P5 dangling `AC4.8b` | FIXED — cite changed to "AC4.8 part (b)" (AC4.8 has prose sub-parts, not a separate id) | Blast Radius |
| P6 G20 floor unwritten | FIXED — floor made explicit and **BLOCKING**: ≥1 clearly-wrong pair in the 30-sample means D14's corroboration is insufficient and `ip_org_domain_mapping_enabled` must NOT be flipped until the rule is strengthened and G20 re-runs clean. New **AC4.13** states it as a gating condition, not an observation | G20, AC4.13 |
| *(nits i–iv)* | ALL FIXED — AC1.6 now precedes AC1.7; G8's row text synced to the extended full-v2-round-trip scope; `\s` replaced with POSIX `[[:space:]]` in both AC1.5 greps (BSD/macOS-safe); KG list reordered to 1, 2, 3, 4 | AC list, G8, AC1.5, KG list |

Net effect of cycle 3: 0 new decisions (D14 tightened in place), 0 new gates, 3 new acceptance criteria
(AC4.11b, AC4.13, plus AC4.11 rescoped), 1 new known-gap (**KG-4**), 2 new mandatory implementation
rules (DNS monkeypatching, `inet` cast guard), 1 misleading mechanism description corrected (P4).

**The honest headline of cycle 3:** P1 was a real vacuous-green catch, and the fix REMOVES a
corroboration path rather than adding one — Phase-3 domain coverage now rests entirely on C-a. That
makes G19's measured number more important, not less: it is now measuring a single-path funnel. The
temptation to "fix" C-b by writing our own accepted domains back into `company_graph` is precisely the
wrong move and is now rejected in the plan text so a future cycle does not rediscover it as a good idea.

Scope note: cycle 3, like cycles 1 and 2, stayed inside the plan file. No source file, no test file, and
no other process artifact was modified. No blast-radius expansion.

**Cycle 4 — 07-08-26 — 3/3 gaps addressed (0 FAILs, 3 CONCERNs).**

| Gap | Disposition | Where |
|---|---|---|
| Q1 G19 measures an empty corroboration surface | FIXED — **both halves of the validator's suggestion applied, not one.** (1) G19 gains a MANDATORY seeding precondition: collect the sampled orgs' prefixes → run the existing rDNS resolver over representative IPs with `company_graph_enabled=True` (verified default `False` at `config.py:717`) → record the **corroboration-surface size** → only then measure. (2) AC4.12 declares two INVALID-measurement outcomes that are explicitly NOT passes: seeding skipped/flag left off, or surface size 0. A 0% hit rate counts only when the surface was non-empty. (3) G20 sampling defined as `min(30, \|accepted\|)`; `\|accepted\| == 0` → **G20 UNRUN, not passed**, AC4.13's floor UNPROVEN, and the flag stays blocked — "no false positives because there was nothing to look at" is not evidence of safety | G19, G20, AC4.12, AC4.13, WS4 18 |
| Q2 D14/AC4.11b contradiction | FIXED — **C-b code path DELETED (my call).** D14 said "becomes real with no design change" while AC4.11b said activation needs its own gate + the feedback-loop guard; both cannot be true. Resolved toward YAGNI: Phase 3 ships NO C-b code. The rule survives as a `DOCUMENTED-FUTURE` row in D14's table, KG-4, and AC4.11b's negative canary whose job is to fail loudly if a future writer emits name+domain together. Rationale: an unreachable branch no gate can exercise is dead weight, and keeping it invited exactly the "just make it satisfiable" fix D14 already rejects as evidence laundering | D14, WS4 18, AC4.11b, KG-4 |
| Q3 D14 table split by prose | FIXED — the corroboration table is now a contiguous 3-column, 2-row table (added a `Status in Phase 3` column so LIVE vs DOCUMENTED-FUTURE is visible in the table itself); the P3 query-safety prose and the C-b census both moved BELOW the complete table. The C-b row no longer renders as literal pipes | D14 |

Net effect of cycle 4: 0 new decisions, 0 new gates, 0 new ACs (two restated: AC4.12, AC4.13; one
rewritten: AC4.11b), 1 code path REMOVED from scope (C-b), 1 gate precondition added (G19 seeding), 1
gate sampling rule defined (G20).

**The honest headline of cycle 4:** Q1 was the same class of defect as cycle 3's P1 — a gate that would
have gone green while proving nothing. Cycle 3 removed a vacuous *corroboration path*; cycle 4 removes a
vacuous *measurement*. Both fixes make Phase 3 prove less but claim less. The domain-mapping leg now has
an explicit, honest shape: it is inert wherever `company_graph_enabled` has never been on, its coverage
is measurable only against a deliberately seeded surface, and its safety floor cannot be satisfied by an
empty sample.

Scope note: cycle 4, like cycles 1–3, stayed inside the plan file. No source file, no test file, and no
other process artifact was modified. Blast radius NARROWED by one code path (C-b).

## Autonomous Goal Block

```
SESSION GOAL: IP-Org Phase 3 - evidence graph v2 (relationship_type + 3 sources + confidence fusion +
corroborated DNS-heuristic domain mapping) for the visitors-identity feature.
Charter + umbrella plan: N/A - single plan. The parent ip-org-database_PLAN_07-08-26.md carries no
program-goal charter section, so no umbrella governs this phase.
Autonomy: /goal autonomous execution rules apply. CONDITIONAL findings -> apply fixes and proceed;
BLOCKED items -> backlog note and continue; irreversible or outward-facing actions without an explicit
contract instruction -> HARD STOP.
Hard stop conditions / safety constraints:
- Never run alembic or an --apply ingest without DATABASE_URL pinned to localhost:5433. The repo's
  environment file points at the Supabase PRODUCTION database and alembic has no local-host guard;
  only scripts/refresh_ip_org.py guards itself.
- Never enable ip_org_fusion_enabled / ip_org_rir_ingest_enabled / ip_org_rpki_ingest_enabled /
  ip_org_domain_mapping_enabled in any real environment. Flag flips are a separate operator action
  after a live migration apply.
- Never flip ip_org_domain_mapping_enabled while G20 has an unresolved clearly-wrong pair, or while
  G20 is UNRUN because G19's accepted set was empty (AC4.13 blocks in both cases).
- Never report G19 as a hit rate when the seeding step was skipped or the corroboration-surface size
  is 0 - that is FAILED-INVALID, not a measurement.
- Never write C-b code. C-a only; C-b is documentation + the AC4.11b canary (KG-4).
- Never edit identity-side files (beam_identity_graph, identity_resolver fp/candidate policy,
  models/identity_coop.py, services/identity_coop.py) - concurrent program, separate track.
- Never commit files outside this plan's Touchpoints table; the worktree is dirty with concurrent work.
- Never weaken the org_kind='org' filter in lookup_ip_org_v2 (D11). Gate G11 makes that failure loud.
- Any single swap over 20 minutes is a new finding to surface, not a number to absorb (C5/G21).
- Monkeypatch the DNS probe in every tests/unit test; only G19 issues real DNS.
PVL state: CONVERGED at cycle 5 -> Gate: CONDITIONAL, 0 FAILs, 0 plan-text defects.
History: c1 BLOCKED (4 FAILs + 13 CONCERNs) -> c2 (8) -> c3 (6 + 4 nits) -> c4 (3) -> c5 (0), with four
supplement cycles between. 37/37 gaps addressed. Nothing left for the plan agent to fix.
TWO USER DECISIONS OUTSTANDING (see the Validate Contract):
  1. Accept the residual-risk menu A1-A8 (D14's coverage trade, G20's 30-sample floor, KG-1..KG-4,
     no accuracy proof for fusion, local-only Hybrid gates).
  2. Keep the WS4 domain half in Phase 3, or split it into a follow-on plan gated on G19's number?
     Yield narrowed three cycles running and is unknown - plausibly small, but not provably zero
     (rDNS resolves per IP; the domain map generalizes per ORG). Option B is not free: measuring
     first still needs resolve_org_domain to exist, or a throwaway measurement script.
Next phase: user accepts A1-A8 and answers Decision 2 -> EXECUTE authorized. No further PVL cycle is
warranted; the plan has no open defects.
Validate contract: inline in
process/features/visitors-identity/active/ip-org-database_07-08-26/ip-org-phase-3-evidence-graph_PLAN_07-08-26.md
Execute start (once authorized): WS1 item 1 (re-derive the alembic head), then strictly WS1 -> WS2 ->
WS3 -> WS4, running each workstream's gates at the end of that workstream. If Decision 2 = Option B,
skip WS4 item 18 and its gates (E14).
Fully-auto gates: .venv/bin/python3.11 -m pytest tests/unit/test_ip_org_fusion.py
tests/unit/test_rpki_validate.py tests/unit/test_ip_org_rir_ingest.py tests/unit/test_rpki_ingest.py
tests/unit/test_ip_org_ingest.py tests/unit/test_ip_org_lookup.py tests/unit/test_company_resolver.py
tests/unit/test_ip_org_domain_map.py -q ; then .venv/bin/python3.11 -m pytest tests/unit -m unit -q
Hybrid gates: tests/integration/test_ip_org_pipeline.py (incl. -k lock_serialization) + alembic
round-trip with a NULL-asn RIR row seeded + full-volume --apply (G21) + live RIR/RPKI dry-runs +
domain-coverage measurement (G19, seeding step MANDATORY). Needs PG 5433 (confirmed LISTEN) + network.
Probe scenarios: EXPLAIN ANALYZE full v2 round trip (<15ms warm) + covering-ROA; min(30, |accepted|)
domain pairs judged for delta.com-class false positives (blocking floor); 20 fused hypotheses.
High-risk pack: no - risk class is schema/data-migration (additive, reversible) and scheduled-job
runtime; no auth, billing, public API or PII surface.
```

## Next Step

**PVL CONVERGED at cycle 5: `Gate: CONDITIONAL`, 0 FAILs, 0 plan-text defects.** Four supplement cycles
closed 37/37 gaps; nothing remains for the plan agent. Two USER decisions gate EXECUTE: accept the
residual-risk menu (A1–A8), and choose whether the WS4 domain half stays in Phase 3 or splits into a
follow-on plan gated on G19's measurement. On acceptance, record it in the Validate Contract's
`Accepted by:` line and say **'ENTER EXECUTE MODE'**.
