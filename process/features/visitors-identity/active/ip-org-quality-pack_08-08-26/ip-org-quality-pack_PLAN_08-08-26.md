---
name: plan:ip-org-quality-pack
description: "Five small ip-org quality workstreams: post-swap ANALYZE + skip-ratio guard, derived-label benchmark corpus, as2org organizationId retention with org-family classification, Public-Suffix-List domain extraction, APNIC eyeball ASN list"
date: 08-08-26
feature: visitors-identity
---

# IP-Org Quality Pack — WS-A…WS-E

**Date**: 08-08-26
**Status**: PLANNED — PVL cycle 4 supplement applied (08-08-26), 7 CONCERNs (C-28…C-34) + the C-35 cosmetic bundle all closed in the plan body. Latest validate verdict: cycle 4 `Gate: CONDITIONAL`, 0 FAILs. User has pre-accepted (A1): the orchestrator records acceptance without a cycle-5 validate, after which EXECUTE proceeds in order A → C → D → E → B.
**Complexity**: COMPLEX (5 workstreams, 1 migration, 2 new scripts, 1 new service, 1 vendored data file)
**Feature**: visitors-identity
**Parent program**: `../ip-org-database_07-08-26/ip-org-database_PLAN_07-08-26.md` (Phases 1–3 shipped + prod-deployed)
**Upstream backlog**: `../../backlog/ip-org-followups_NOTE_07-08-26.md` items 2, 4, 5, 7 (+ new domain/eyeball work)

## TL;DR

Five independent, small workstreams that raise the quality and measurability of the shipped ip-org
stack without changing its architecture. WS-A closes two ops holes found by the Phase-3 EVL (cold
planner stats after swap; no alert on a silent join collapse). WS-B builds the first real
measurement instrument the program has ever had — a derived-label benchmark corpus — closing the
Phase-3 A7 gap where precision was asserted but never measured. WS-C stops discarding the CAIDA
`organizationId` and uses it for org-family classification consistency. WS-D replaces a hardcoded
8-entry two-part-TLD set with a vendored Public Suffix List. WS-E adds a numeric, data-driven
eyeball-ASN signal (APNIC per-AS user population) in front of the existing token heuristics.

SPEC and INNOVATE were skipped by the orchestrator: scope is mechanical and the research pass
already compared and locked the options. This plan specifies implementation exactly; EXECUTE must
not re-litigate the choices in "Locked Decisions".

## Context

Phases 1–3 of `ip-org-database` are EXECUTED, EVL-green, and deployed to prod (alembic head
`c4a8f13e07b6`, tables present but EMPTY, all four ip-org flags OFF). What shipped is a working
pipeline with two known quality blind spots:

1. **No measurement.** Phase 3's fusion changes confidence scoring, but the program has never
   compared a predicted org against a known-true org on real traffic. Every quality claim to date
   is a spot-check.
2. **Silent-degradation class.** The Phase-1/2 EVL fix cycle found a 100 % row-skip bug (live
   as2org is camelCase `organizationId`; fixtures had invented snake_case). It was caught only
   because a human read the numbers. The only automatic guard today is
   `if not rows: return {"status": "error"}` — a 99 %-skip run still swaps.

WS-A and WS-B attack those two directly. WS-C/D/E are three cheap precision improvements the
follow-ups note already itemized (items 4, 7, plus the `_extract_domain` TLD limitation).

Context routers consulted: `process/context/all-context.md`,
`process/context/tests/all-tests.md`, `process/features/visitors-identity/` task inventory,
`../ip-org-database_07-08-26/ip-org-phase-3-evidence-graph_PLAN_07-08-26.md` (conventions,
D1–D14, gate style).

## Locked Decisions (EXECUTE must not re-litigate)

**Q1 — ANALYZE runs AFTER the swap commit, in its own statement, not inside the swap transaction.**
Planner statistics written inside an uncommitted transaction are not visible to other backends;
the whole point of the fix is that the NEXT lookup (from a different connection) has stats. So the
`ANALYZE` is issued after `await db.commit()` inside `_load_staging_and_swap`, wrapped in
try/except that logs and swallows — a failed ANALYZE must never turn a good swap into an error.
*Rejected:* running it before the commit (invisible to readers, and holds the write lock longer);
running it from the caller (would need duplicating in both CAIDA and RIR jobs — putting it in the
shared function means both inherit it for free, which is exactly the ask).

**Q2 — Skip-ratio guard is two-tier: WARN then REFUSE, computed on `skipped / prefixes`.**
Denominator is `len(prefixes)` (rows the source offered), not `len(rows)` (rows that survived) —
using the survivor count makes the ratio undefined at total collapse, which is the case the guard
exists for. Above `ip_org_skip_warn_ratio` (0.25) → `logger.warning`, swap proceeds. Above
`ip_org_skip_abort_ratio` (0.40) → return `{"status": "error", "error": "skip ratio …"}` BEFORE
acquiring the advisory lock, keeping the old data. Both thresholds are settings so an operator can
raise them for a known snapshot-age mismatch without a deploy. The measured healthy baseline is
12.7 % (as2org snapshot lagging pfx2as), so 0.25 leaves ~2× headroom before noise, and the
camelCase defect (100 %) trips the ceiling by a wide margin.
*Rejected:* a single hard threshold (no ability to observe drift before it becomes an outage);
raising an exception (the whole ingest path is fail-open by contract — it returns status dicts).

**Q3 — WS-B corpus is a go/no-go: measure the population BEFORE building the instrument.**
Nobody has counted how many `identified_visitors` rows survive the exclusion filters. Step B1 is a
pure count query. The floor is NOT a single B1 count — B1 records THREE numbers (see B1's table:
SQL upper bound → headline-eligible count → **predicted-row count, stratum `org`**) and the
**operative go/no-go floor is on the third, the predicted-row count** (P1-4). `< 80` predicted rows
→ WS-B is descoped to a backlog note and the rest of the pack ships. Rationale for descoping at
`< 80`: the corpus is too small to produce a usable single-arm precision number — not the withdrawn
v1-vs-v2 comparison rationale, which Q14 abandons as degenerate by construction.

**Q4 — Corpus artifact stores NO raw emails and lives ONLY in the task folder, gitignored.**
Row shape is exactly `(ip, email_domain, expected_org_normalized, stratum)`. Email local-parts
never leave the database. Even the domain is PII-adjacent (a domain plus an IP is a
re-identification vector for a small company), so: the artifact is written to
`process/features/visitors-identity/active/ip-org-quality-pack_08-08-26/benchmark-corpus.tsv`,
that exact filename is added to `.gitignore`, and the plan's retention posture is **delete after
the measurement report is written** (the report carries aggregate numbers only and IS committed).
*Rejected:* committing the corpus (permanent PII-adjacent artifact in git history — unrecoverable);
storing it in a DB table (a new table for a one-shot measurement, and now the PII lives in two
places).

**Q5 — Domain↔org matcher is exact-first, token-overlap-fallback, with per-method reporting.**
This is the highest-risk part of WS-B: a sloppy matcher manufactures whatever precision number you
want. Mitigation is auditability, not cleverness. Both sides are put through the existing
`normalize_org_name`, then: (1) exact equality → `match_method="exact"`; (2) token-set overlap
where the smaller token set is a subset of the larger AND has ≥1 token of length ≥4 →
`match_method="token_subset"`; (3) otherwise no match. The report ALWAYS breaks precision down by
`match_method`, so a reader can discard the fuzzy tier and read the exact-only number. No
Levenshtein, no embeddings, no new dependency.

**Q6 — WS-C org-family classification is conservative-direction-only and runs at ingest time.**
A second in-memory pass over the parsed maps, before row-building: for each `organizationId`, if
ANY member ASN classifies `eyeball`/`datacenter`/`cdn` by the existing token/ASN heuristics, every
ASN in that family inherits that kind. `org → eyeball|datacenter|cdn` is allowed;
`eyeball|datacenter|cdn → org` is NEVER allowed. Rationale: the failure this fixes is
under-classification (a carrier's second ASN slipping through as `org` and becoming
emailable-path eligible). Promoting anything TO `org` would create the exact false-positive the
whole `org_kind` filter exists to prevent. Cost is one dict pass over ~102 k orgs — negligible
next to a 158 s load.
*Rejected:* a DB-side post-swap UPDATE (another write pass over 1 M rows for data we already have
in memory); doing it in fusion at read time (per-lookup cost on the hot path).

**Q7 — WS-D vendors the Public Suffix List; no runtime fetch, no new dependency.**
`apps/api/data/public_suffix_list.dat` (~240 KB) is committed, parsed once by a small pure module
`apps/api/services/public_suffix.py` (~40 lines: strip comments, build a set of rules plus a set
of `!` exceptions, longest-suffix match honoring `*` wildcards). PSL churn is slow (weeks), a
runtime fetch adds a failure mode and a moving-target test surface for a file that changes rarely,
and a vendored file is byte-reproducible in tests. Refresh cadence is a documented known-gap.
*Rejected:* `publicsuffix2`/`tldextract` (new Python dependency — repo constraint);
runtime fetch with vendored fallback (all the complexity of both, for a file that barely moves).

**Q8 — WS-E: APNIC is a numeric PRE-check, never a replacement for the token list.**
`classify_ip_org_kind` consults the APNIC eyeball ASN set FIRST (numeric, stable), and falls
through to the existing `classify_org_kind` + token path when the ASN is absent from the set. The
token list is NEVER deleted — it covers CAIDA ASNs that are absent from the APNIC dataset, which
is a real and sufficient justification. **Correction (C-18/R10):** the earlier justification "it is
the only signal for `registered_holder` rows that carry no ASN at all" is FALSE and is withdrawn.
`registered_holder` rows are built by `_allocation_to_row` (`ip_org_rir_ingest.py:147-166`), which
hardcodes `org_kind="registry"` and never calls `classify_ip_org_kind`; that function's only caller
is `ip_org_ingest.py:500`, on the CAIDA path. `classify_ip_org_kind(asn: int, …)` is also typed
non-optional, so the "asn is NULL" path does not exist as described. Direction guard is identical to Q6: APNIC can
only move a prefix `org → eyeball`. Threshold `ip_org_eyeball_min_users` defaults to **50 000**
estimated users: APNIC's per-AS population estimates are advertisement-sampled and noisy at the
tail (IMC 2024 "unboxing" critique), and 50 k is comfortably above the noise floor while still
capturing every consumer ISP that matters for false-positive suppression. Being conservative is
the correct direction of error here — a missed eyeball AS costs one wasted classification; a
wrongly-demoted org AS silently removes real companies from the emailable path.

**Q9 — No backfill of the 967 k already-loaded rows for WS-C or WS-E.**
Both change classification at ingest time; the ingest is a full wholesale refresh on a 24 h
cadence (`ip_org_refresh_interval_hours`). The next scheduled run re-classifies everything by
construction. A backfill migration would duplicate the classification logic in SQL and go stale
the moment the token list changes.

**Q10 — WS-D parses the PSL's ICANN section ONLY; the PRIVATE section is excluded (CONCERN-13).**
`public_suffix_list.dat` is split by `// ===BEGIN ICANN DOMAINS===` / `// ===END ICANN DOMAINS===`
and `// ===BEGIN PRIVATE DOMAINS===` / `// ===END PRIVATE DOMAINS===`. `_load_rules()` reads rules
only between the ICANN markers. Rationale: the PRIVATE section contains cloud-tenant suffixes
(`compute.amazonaws.com`, `cloudapp.azure.com`, `*.herokuapp.com`). Including it would make
`ec2-1-2-3-4.compute-1.amazonaws.com` produce a registrable domain like `ec2-1-2-3-4.compute-1.amazonaws.com`
instead of `amazonaws.com` — i.e. it would *bypass* `_build_domain_filter_regex`, which matches on
`amazonaws.com`. That is a false-positive generator on the exact surface `_extract_domain` exists to
filter. ICANN-only keeps every cloud host collapsing to its filterable apex.
*Rejected:* full-file parse (breaks cloud filtering as above); a PRIVATE-section allow-list
(hand-maintained exception set — the thing WS-D is removing).

**Q11 — WS-D's change is BIDIRECTIONAL, and the narrowing half is the point (FAIL-1).**
Today `_extract_domain`'s two-part-TLD branch (`company_resolver.py:105-110`) `return`s EARLY,
BEFORE `_build_domain_filter_regex()` (:115) and `_build_hostname_filter_regex()` (:119). Any host
under one of the 8 hardcoded suffixes therefore skips BOTH ISP/residential filters entirely — e.g.
`dsl-pool.host.talktalk.co.uk` returns `talktalk.co.uk` today. After D3 there is no early return, so
that host flows through the filters and returns `None`. WS-D is accepted WITH that narrowing: those
rows are consumer-ISP rDNS being written to `company_graph` as if they were employers, which is the
same fabrication class `lookup_ip_org_v2`'s eyeball filter exists to prevent. The narrowing is a
FIX, not a regression — but it must be gated (AC-D3/G21), not assumed.

**Q12 — WS-B enables the lookup flag IN-PROCESS via settings assignment; a "direct service call"
does NOT bypass it (FAIL-2).** Verified: `ip_org_lookup.py:66` (`lookup_ip_org`) and
`ip_org_lookup.py:153` (`lookup_ip_org_v2`) BOTH open with
`if not settings.ip_org_lookup_enabled or not ip: return None`. Calling the functions directly runs
that guard. With the default `False`, both arms return `None` for 100 % of corpus IPs and G8's own
non-vacuity assertion fails — the Phase-3 flag-off vacuity class exactly.
Mechanism: `apps/api/config.py:1187` sets `model_config = {"env_file": …, "extra": "ignore"}` with
**no `validate_assignment` and no `frozen`**, so the singleton is mutable. `measure_ip_org_precision.py`
therefore does, once at startup, before any lookup:

```
from apps.api.config import settings
settings.ip_org_lookup_enabled = True   # in-process only; never a deploy-level flip
```

and logs that it did so. This is a local measurement process, not a deployed environment — it is
explicitly permitted by the goal block's "Enabling a flag inside a local measurement process is
fine" clause.
*Correction to the plan's second bypass claim:* `lookup_ip_org_v2` never reads
`ip_org_fusion_enabled` at all. Verified: that flag's only production reader is
`company_resolver.py:610` (the resolver call site). No override for it is needed or possible inside
`lookup_ip_org_v2`; setting it would be a no-op and must NOT be written as if it mattered.
*Rejected:* env-var export before the run (`Settings` is instantiated at import, so an export must
precede the interpreter — brittle and easy to forget, and the failure mode is silent all-`None`);
monkeypatching the module-level guard (hides the real contract).

**Q13 — WS-B needs TWO DSNs, and they are different databases (CONCERN-4).**
- **Corpus extraction (B1, B3) reads PROD**: `identified_visitors` + `visitors` only exist with real
  data there. Read-only, explicit DSN required.
- **Measurement (B3 `stratum` derivation, B4 both lookup arms) reads LOCAL `localhost:5433`**:
  `ip_org_prefixes` and `rpki_roas` are EMPTY on prod (`all-context.md`), so a prod-side lookup would
  return `None` for every row — a second vacuity trap distinct from FAIL-2.
Concretely: `build_ip_org_benchmark.py` takes `--database-url` (prod, read-only) and emits the TSV
with `stratum` left as the literal `pending`; `measure_ip_org_precision.py` takes its own
`--database-url` (local) and fills `stratum` from the local corpus as it scores. This keeps the
pack-wide "pin `DATABASE_URL` to `localhost:5433`" constraint intact: the ONLY remote DSN in this
pack is the extraction script's explicit read-only argument, and it is never taken from the
environment's `DATABASE_URL`.

**Q14 — WS-B is NOT a two-arm precision comparison. The v1-vs-v2 McNemar framing is degenerate BY
CONSTRUCTION and is abandoned (R1; supersedes FAIL-4 and C-17).**
Verified against source: `_LOOKUP_SQL` (v1, `ip_org_lookup.py:52-56`) and `_V2_ROUTE_ORIGIN_SQL`
(`:94-100`) differ by exactly one predicate — `AND relationship_type = 'route_origin'`. The only
writers of `org_kind='org'` make those rows `route_origin` (`ip_org_ingest.py:500-503`), and RIR rows
carry `org_kind="registry"` (`ip_org_rir_ingest.py:162`) with `relationship_type="registered_holder"`
(`:163`) — **corrected citation (C-23/P2-7):** the earlier text credited `:162` with
`relationship_type='registry'`, conflating the two columns. The conclusion is unchanged and
independently correct: RIR rows are excluded from BOTH arms by the shared `org_kind='org'` predicate,
not by any `relationship_type` predicate. Both arms therefore select the
IDENTICAL row for every IP, and fusion's `organization` IS v1's `org_name`
(`ip_org_fusion.py:165`). The discordant McNemar cells (`v1✓v2✗`, `v1✗v2✓`) are provably zero except
on exceptions. A "v2 beats v1" number out of this design would be manufactured, not measured.

WS-B is restated as the three things it CAN honestly measure:

- **(a) Single-arm precision, with an explicitly defined denominator (P1-3).** ONE org prediction
  (both arms produce the same one) scored against the derived labels.
  **`precision = correct / (rows with a non-None prediction)`** — NOT over all headline rows. The
  `eyeball`/`none` strata sit inside the headline set but produce zero predictions by construction
  (both arms filter `org_kind='org'`), so dividing by headline rows would silently deflate the number
  with rows the pipeline never claimed. Reported ALONGSIDE it, never folded into it:
  **`coverage = non-None predictions / headline rows`**. `match_method` is a **numerator
  DECOMPOSITION** — the share of *correct* predictions attributable to `exact` vs `token_subset` —
  **not** a per-method precision: `match_method` only exists on rows that matched, so a "precision per
  match_method" is ill-posed (its denominator would be its own numerator). Per-stratum breakdown is
  reported the same way, with each stratum's own predicted-row count shown so an empty stratum is
  visible rather than implied.
- **(b) Calibration of v2's confidence, over the REACHABLE value set — not equal-width buckets
  (P1-1).** v2 additionally returns a confidence and a classification; v1 does not. The four
  equal-width buckets specified earlier are **degenerate and are withdrawn**: v2's confidence is not
  continuous. It is `base 0.45 + alloc ∈ {+0.15, 0, −0.05} + rpki ∈ {+0.15, 0, −0.20}`, then clamped
  to `[0.05, 0.65]`, so the reachable set is EXACTLY seven values:

  `{0.20, 0.25, 0.40, 0.45, 0.55, 0.60, 0.65}`

  The minimum reachable value is `0.20`, so the `0.05` floor is dead code and the bucket `[0.05,0.2)`
  is **provably empty**; the bucket `[0.2,0.35)` is reachable only via `rpki=invalid`, ≈1–2 rows at
  N≈200. A four-bucket table would therefore report two near-empty or empty buckets as if they were
  measurements.

  Replace it with a **per-reachable-value table — one row per confidence value, seven rows**:

  | v2 confidence | n (predicted rows) | correct | accuracy |
  |---|---|---|---|
  | 0.20 | | | |
  | 0.25 | | | |
  | 0.40 | | | |
  | 0.45 | | | |
  | 0.55 | | | |
  | 0.60 | | | |
  | 0.65 | | | |

  The report MUST state inline that the two `rpki=invalid`-derived values (`0.20`, `0.25`) are
  expected to be near-empty at N≈200 and carry no signal, and MUST NOT claim "four-bucket
  calibration" anywhere. Any value observed OUTSIDE the seven is itself a finding (the clamp or the
  adjustment table changed) and is reported as such.
- **(b2) Accuracy by `v2_classification` (P2-9).** `v2_classification` is already collected and is
  currently written to the row record and never consumed. Report accuracy broken down by its value —
  `registered_operator` / `likely_operational_customer` / `disputed_origin` / `unclassified` (C-34:
  `Classification` at `ip_org_fusion.py:64-69` is a FOUR-member Literal and `derive_classification`
  at `:289-297` is a total function whose fallback returns `unclassified` for any prefix the RIR
  corpus does not cover — common, given 262 k RIR allocations vs 967 k+ route rows) — with row
  counts. A three-key breakdown would drop rows or raise on the fourth key. This is
  free (no new data), and it is the one v2 output that is NOT a deterministic function of the
  confidence value, so it carries information the calibration table cannot.
- **(c) A `v1_pred == v2_pred` INVARIANT assertion, not a comparison.** Any divergence is a BUG
  report, not a precision win. This converts the degenerate comparison into a genuine regression gate.

**Stratum derivation** comes from a direct UNFILTERED query issued by the measurement script — never
read off a lookup return, because both arms filter to `org_kind='org'` and so can only ever yield
stratum `org` or nothing:

```sql
SELECT org_kind FROM ip_org_prefixes
WHERE prefix >>= CAST(:ip AS inet) AND relationship_type = 'route_origin'
ORDER BY masklen(prefix) DESC, id LIMIT 1
```

**Deterministic tie-break is mandatory in the measurement script's OWN queries (P2-8).** There is no
unique constraint on `prefix` and `parse_pfx2as` does not dedupe, so two equal-masklen rows for one
prefix make a bare `ORDER BY masklen(prefix) DESC LIMIT 1` return a nondeterministic row. Without
`, id` the same IP can score differently across runs. The `, id` tie-break applies to the stratum
query above and to any other query this pack's two scripts issue against `ip_org_prefixes`.

**But the `, id` tie-break on the script's own queries CANNOT make the Q14(c) `v1_pred == v2_pred`
invariant deterministic (C-28), because that invariant runs through the UNTOUCHED production SQL**
(`_LOOKUP_SQL` and `_V2_ROUTE_ORIGIN_SQL`, both non-total, KG-9) — the script does not control how
those pick among equal-masklen duplicates. So the invariant is only meaningful when no such
duplicates exist. **Mandate a duplicate-prefix probe as the invariant's precondition:** before
asserting the invariant, the measurement script runs
`SELECT prefix, count(*) FROM ip_org_prefixes WHERE relationship_type = 'route_origin' GROUP BY prefix HAVING count(*) > 1`
and requires a ZERO result. If the probe returns zero rows, the `v1_pred == v2_pred` invariant is
asserted and any divergence is a genuine BUG. If the probe returns ANY rows, the invariant is
**SKIPPED (recorded as not-run), not FAILED** — a divergence under duplicate prefixes is a data
property of the untouched production ordering, not a defect this pack introduced. The probe result
(zero → invariant ran; non-zero → invariant skipped, with the duplicate count) MUST be stated in the
report.

**The PRODUCTION SQL is NOT changed by this pack.** `_LOOKUP_SQL` (`ip_org_lookup.py:52-56`) and
`_V2_ROUTE_ORIGIN_SQL` (`:94-100`) both carry the same non-total `ORDER BY masklen(prefix) DESC
LIMIT 1`. Adding a tie-break there is a real improvement but touches the live lookup path and needs
its own gate — recorded as **KG-9**, not fixed here.

No match → stratum `none`, kept distinct from the not-yet-derived `pending`.
*Rejected:* keeping the McNemar framing with a caveat (a degenerate statistic with a footnote is
still degenerate, and the number would be quoted without the footnote).

**Q15 — WS-D's improvement does not reach the live read path for 30–75 days; that lag is ACCEPTED as
a named known-gap, not solved (R8).**
Two caches sit in front of `_extract_domain`'s output: the Redis `company_ip` cache (30-day TTL) and
`company_graph`'s staleness re-validation window (`company_graph_staleness_days`, default 75). Both
keep serving values produced by the OLD logic until they expire. Cache invalidation is explicitly
OUT of scope for this pack — a targeted invalidation needs its own gates and a decision about which
cache is authoritative. Recorded as KG-6 with a backlog stub, surfaced in D4's census answers and in
the Q11 posture. Already-written `company_graph` rows are likewise not rewritten (existing non-goal).

## Workstreams

### WS-A — Post-swap ANALYZE + skip-ratio guard (XS)

Closes follow-ups items 5 and 2.

**A1.** In `apps/api/services/ip_org_ingest.py::_load_staging_and_swap`, after the existing
`await db.commit()` (currently at the end of the swap block, before the fusion-cache
invalidation), add:

```
try:
    await db.execute(text(f'ANALYZE "{IP_ORG_TABLE}"'))
    await db.commit()
    logger.info("ip_org_post_swap_analyze_ok")
except Exception as exc:
    logger.warning("ip_org_post_swap_analyze_failed", error=str(exc))
```

Placement is load-bearing (Q1): AFTER the swap commit, in its own transaction. Both
`refresh_ip_org_dataset` (CAIDA) and `refresh_rir_allocations` (RIR) call this shared function and
inherit the behavior with no call-site change.

**A2.** New settings in `apps/api/config.py`, in the existing `ip_org_*` block (after
`ip_org_refresh_interval_hours`):

```
ip_org_skip_warn_ratio: float = 0.25
ip_org_skip_abort_ratio: float = 0.40
```

Both with an inline comment naming the measured 12.7 % healthy baseline and the camelCase
100 %-skip defect they exist to catch.

**A3.** In `refresh_ip_org_dataset`, immediately after the existing
`logger.info("ip_org_ingest_parsed", …)` call, compute
`skip_ratio = skipped / len(prefixes) if prefixes else 1.0` and add it to the `summary` dict as
`"skip_ratio"` (rounded to 4 dp). Emit `logger.warning("ip_org_ingest_skip_ratio_high", …)` when
`skip_ratio > settings.ip_org_skip_warn_ratio`.

**A4.** In the same function, AFTER the `if dry_run: return` branch and BEFORE the existing
`if not rows` check, add the abort:

```
if skip_ratio > settings.ip_org_skip_abort_ratio:
    logger.warning("ip_org_ingest_skip_ratio_abort", skip_ratio=skip_ratio)
    return {"status": "error", "error": f"skip ratio {skip_ratio:.3f} exceeds abort threshold", **summary}
```

Ordering is deliberate: a dry run still REPORTS the ratio (that is how an operator diagnoses a
snapshot mismatch) but never aborts, since it writes nothing anyway. The abort happens before the
advisory lock is acquired, so a bad snapshot never blocks a good concurrent refresh.

**A5 — the RIR leg is OUT of scope, as a verified fact, not a conditional (CONCERN-10).**
Inspection resolves the earlier "if it already tracks a skipped count" branch to FALSE:
`refresh_rir_allocations` does **not** track a skipped count and has **no offered-row denominator** —
its summary is `sources_ok / sources_failed / allocations / rows`
(`ip_org_rir_ingest.py:210-215`), and `parse_delegated_extended` silently `continue`s on
unparseable records. Therefore: **the skip-ratio guard covers the CAIDA leg ONLY.** Do not invent a
counter for the RIR job in this pack. Record the limitation in the phase report and in the
known-gaps list (KG-5). Measured RIR skip rate at Phase-3 EVL was 0 %, so the exposure is currently
nil — but it is unguarded, and that is the honest statement.

**A6.** Unit tests in `tests/unit/test_ip_org_ingest.py` (existing file): skip-ratio computation at
0 %, 12.7 %, 30 % (warn, no abort), 45 % (abort, status error, `_load_staging_and_swap` never
called), and `prefixes == []` → ratio 1.0 → abort. ANALYZE is covered by the integration gate, not
a unit test (it needs a real planner).

### WS-B — Benchmark corpus v1, derived labels (S)

Closes the Phase-3 A7 measurement gap. **Gated on B1.**

**B1 — population count (go/no-go, do this first). The number is an UPPER BOUND, not the final
floor (C-14).** A read-only query, run by an operator against the prod DSN, counting
`IdentifiedVisitor` rows joined to `Visitor` (join key per B2, R3) that satisfy every **SQL-expressible**
inclusion rule in B2. It necessarily OVER-counts, because the datacenter/CDN exclusion is not a SQL
predicate — it is derived later from the local corpus (Q14). Therefore:

- Record the B1 upper bound in the phase report.
- `< 80` at the upper bound → infeasible outright, descope now.
- `≥ 80` → proceed, but **deliberately over-sample** (target ~300 extracted rows for a ~200-row
  headline set) and apply the REAL floor AFTER stratum derivation.

**The operative floor is on PREDICTED rows, not headline rows (P1-4).** The earlier
"headline-eligible (non-`datacenter`/`cdn`) count" is the WRONG population: the `eyeball` and `none`
strata sit inside the headline set but produce **zero** predictions, because both lookup arms filter
`org_kind='org'`. A headline set of 200 rows that is 60 % eyeball/none yields ~80 scored rows, and a
floor applied to the 200 would wave through a measurement resting on far fewer. Therefore record
THREE numbers and gate on the third:

| # | Number | Role |
|---|---|---|
| 1 | B1 SQL upper bound | feasibility screen only; `< 80` → descope now |
| 2 | headline-eligible count (strata excluding `datacenter`/`cdn`) | reported, for shrinkage transparency |
| 3 | **rows with a non-None prediction (stratum `org`)** | **the go/no-go floor: `< 80` → descope** |

Record all three plus the observed shrinkage at each step.

`< 80` at either check → write
`../../backlog/ip-org-benchmark-corpus-infeasible_NOTE_08-08-26.md` explaining the shortfall and
skip B2–B5; the rest of the pack proceeds unaffected.

**B2 — inclusion / exclusion rules** (all mandatory; the `Where` column is load-bearing — **exactly
one of the nine rules is NOT expressible in SQL** and is applied in Python by the measurement script,
correcting both the earlier "all applied in SQL" claim (CONCERN-5) and the cycle-1 supplement's own
"two of the six" miscount (C-15)).

**Join key (R3, mandatory).** `IdentifiedVisitor` has NO foreign key to `Visitor`, so a single-column
join is cross-tenant unsafe — one visitor_id could match rows belonging to another site. Every query
in B1/B3 MUST join on BOTH columns:

```sql
FROM identified_visitors iv
JOIN visitors v ON iv.site_id = v.site_id AND iv.visitor_id = v.visitor_id
```

| Rule | Where | Predicate |
|---|---|---|
| has an email | SQL (prod) | `identified_visitors.email IS NOT NULL` |
| has a usable IP | SQL (prod) | See **B2b** below — the cast-guard is NOT expressible as a single `AND`-chained predicate and the loose regex is not cast-safe (P1-5) |
| post-CF-fix only | SQL (prod) | `identified_visitors.resolved_at > '2026-07-26 09:13:43'` (commit `e4c1db8`) — earlier rows may carry Cloudflare edge IPs, which would score the CDN not the visitor. **The literal is NAIVE UTC (R13):** `resolved_at` is `timestamp WITHOUT time zone`, so the cycle-1 tz-aware literal `'2026-07-26 16:13:43+07'` would be compared against a naive column and silently reinterpreted under the session `TimeZone`. The value above is the same instant converted to UTC. State the assumption explicitly in the script: it issues `SET TIME ZONE 'UTC'` on connect and stores naive-UTC comparisons only |
| not free-mail | SQL (prod) | `split_part(email, '@', 2) NOT IN (:free_mail_domains)` — the set from B2a is passed as a bound parameter; see CONCERN-6, the local-part is never selected |
| not bot/abuse/opted-out | SQL (prod) | `visitors.do_not_resolve = false AND visitors.is_abuse_flagged = false AND visitors.is_bot_suspect = false` |
| **not agent-origin (R4)** | SQL (prod) | `identified_visitors.source_agent_visit_id IS NULL` — **mandatory.** An agent-origin row pairs a bot's IP with a company, which is exactly the poisoned label class the repo's top guardrail (`is_emailable_identity`'s hard exclusion) exists to prevent; letting it into ground truth would teach the benchmark that datacenter IPs "correctly" map to companies. **Both optional columns DO exist — the hedge is resolved to fact (C-25):** `visitors.is_agent_operated` (`models/visitor.py:117`) and `visitors.is_internal_suspect` (`:132`). Apply both; no EXECUTE-time presence check. **Bridge decision (C-30): hand-inline the equivalent WHERE predicates — option (a), do NOT call `human_only_visitor_filter()` from the extraction SQL.** `human_only_visitor_filter()` (`apps/api/services/agent_visitor_filters.py`) is a SQLAlchemy predicate builder — it calls `aliased(Visitor)` and constructs a correlated `EXISTS` over the ORM entity — so it CANNOT be interpolated into B3's raw asyncpg SQL string (and even compiled it would emit `visitors.…`, not the `v` alias the B2b CTE uses). B3 uses a raw read-only asyncpg connection by design, so the fix is to hand-inline the equivalent predicates directly in the CTE `WHERE`: `v.is_agent_operated = false AND v.is_internal_suspect = false AND v.is_bot_suspect = false AND v.is_abuse_flagged = false AND v.do_not_resolve = false AND iv.source_agent_visit_id IS NULL` (the columns the canonical helper covers, minus the phantom-contact `EXISTS` which `source_agent_visit_id IS NULL` already subsumes from the IdentifiedVisitor side). The measurement script MUST record in the phase report that the canonical `human_only_visitor_filter()` was **deliberately NOT reused** (raw-asyncpg read-only script; a SQLAlchemy Core predicate cannot compose into a hand-written SQL string) and MUST carry a pointer to `agent_visitor_filters.py:19` so the two stay in sync if the canonical list changes. `is_agent_operated` (`models/visitor.py:117`) and `is_internal_suspect` (`:132`) both exist — no EXECUTE-time presence check. This is the same "reuse the one existing list" intent B2a applies to free-mail domains, satisfied here by inlining-with-a-sync-pointer rather than importing, because the driver is raw SQL |
| **IP is LAST-SEEN, not IP-at-identification (R5)** | SQL (prod) + disclosure | `visitors.ip_address` is overwritten by the aggregator on every rollup (`visitor_aggregator.py:315`, `:677`), so it is the visitor's most recent IP — NOT necessarily the IP they had when `resolved_at` fired. `resolved_at` constrains the LABEL, not the IP. Preferred fix: derive the IP from the `events` table at/near `resolved_at`. **The events-derived value MUST pass the SAME validity predicates as `visitors.ip_address` (C-22) AND carry a lower time bound (P1-6):** `events.ip_address` is `Column(String(45), default="")` (`models/event.py:37`) — it defaults to an empty string, not NULL, so an unguarded pick can return `''` which then raises on `CAST(:ip AS inet)` downstream. And without a lower bound the derivation **reopens the CF-edge hole the `resolved_at` cutoff exists to close**: an identification made after the fix can still select a pre-fix event carrying a Cloudflare edge IP. Query shape: `SELECT ip_address FROM events WHERE site_id=iv.site_id AND visitor_id=iv.visitor_id AND created_at <= iv.resolved_at AND created_at > '2026-07-26 09:13:43' AND ip_address <> '' AND ip_address ~ <the strict IPv4 regex of B2b> ORDER BY created_at DESC LIMIT 1` — the `created_at` literal is the SAME naive-UTC literal as the `resolved_at` cutoff (R13), and the private-range exclusion of B2b is applied to the result exactly as it is to `visitors.ip_address` (mirroring the aggregator's own `FILTER (WHERE ip_address != '')` at `visitor_aggregator.py:315`). If that query proves impractical at EXECUTE time (events retention is 90 days and older identifications will have no row), fall back to `visitors.ip_address` and record it as an explicit stratum plus KG-8, worded honestly: *"the IP may postdate the identification; a visitor who changed networks contributes a mismatched (ip, org) pair."* Do not describe the fallback as ground truth |
| **not datacenter/CDN** | **Python, in the MEASUREMENT script, not SQL** — the ONE non-SQL rule | `classify_org_kind(org: str \| None)` (`company_resolver.py:343`) takes an **ipinfo-style org STRING, not an IP**, and returns only `datacenter\|cdn\|eyeball` — so it cannot be a prod SQL predicate. Implemented instead as: `measure_ip_org_precision.py` derives each IP's `stratum` with its OWN **unfiltered** query against the LOCAL `ip_org_prefixes` (the Q14 SQL — `relationship_type='route_origin'`, NO `org_kind` filter, longest-prefix first), then **excludes `datacenter`/`cdn` strata from the headline numbers while still reporting them in the per-stratum breakdown**. Deriving the stratum from `lookup_ip_org_v2`'s return is FORBIDDEN (FAIL-4): both arms filter to `org_kind='org'`, so a lookup-derived stratum can only ever be `org` or nothing and the exclusion would be inoperative AND invisible |
| one row per IP | SQL (prod) | `DISTINCT ON (visitors.ip_address) … ORDER BY visitors.ip_address, identified_visitors.resolved_at DESC` — an IP appearing 40 times must not dominate the score |

**B2b — cast-safe IP validity (P1-5, supersedes the inline "has a usable IP" predicate).**
Two defects in the earlier one-line rule, both fatal in practice:

1. **Postgres `AND` does not short-circuit.** The planner may evaluate `ip_address::inet <<= …`
   before the regex guard in the same `WHERE` clause, so a single malformed `ip_address` row kills
   the whole query with `invalid input syntax for type inet`. A regex "before" a cast in written
   order buys nothing.
2. **The loose regex `^(\d{1,3}\.){3}\d{1,3}$` is not cast-safe.** `999.1.2.3` matches it and
   still raises on `::inet`.

Both are fixed together. Use the **octet-range-strict** regex:

```
^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$
```

and place the cast behind an **optimization barrier** so it cannot be hoisted above the filter:

```sql
WITH candidates AS MATERIALIZED (
    SELECT iv.site_id,
           iv.visitor_id,
           iv.resolved_at,
           split_part(iv.email, '@', 2) AS email_domain,   -- NEVER iv.* / iv.email (C-33, Q4 privacy invariant)
           v.ip_address
    FROM identified_visitors iv
    JOIN visitors v ON iv.site_id = v.site_id AND iv.visitor_id = v.visitor_id
    WHERE v.ip_address IS NOT NULL
      AND v.ip_address ~ '^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
      -- … all other SQL-expressible B2 predicates …
)
SELECT DISTINCT ON (ip_address)
       ip_address, email_domain, site_id, visitor_id, resolved_at
FROM candidates
WHERE NOT (ip_address::inet <<= ANY (ARRAY[
    '10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8','169.254.0.0/16'
]::inet[]))
ORDER BY ip_address, resolved_at DESC   -- B2 "one row per IP" rule attaches HERE, on the outer query, after the private-range filter
```

**Explicit projection is mandatory (C-33).** The CTE MUST NOT `SELECT iv.*` — `iv.*` pulls
`identified_visitors.email` (the plaintext local-part) into the wire and into process memory, which
directly violates B3's "Never SELECTs `email`" and Q4's "email local-parts never leave the database".
Only `split_part(iv.email, '@', 2) AS email_domain` is selected; the bare `email` column appears
nowhere in any SELECT list. This is the one place an execute-agent copies SQL verbatim, so it is
fixed in the text rather than left to G5 (which greps the written TSV, not the wire, and so cannot
catch a wire leak). `AS MATERIALIZED` is load-bearing — it forbids the planner from inlining the CTE
and re-ordering the cast above the regex. A `CASE WHEN <strict regex> THEN ip_address::inet ELSE NULL END`
wrapper is an acceptable equivalent; a bare `AND`-chain is NOT. The strict regex alone makes every
value reaching the cast castable, so the two mechanisms are belt-and-braces by design. The `DISTINCT
ON (ip_address) … ORDER BY ip_address, resolved_at DESC` (B2 "one row per IP" rule) attaches to the
OUTER query, after the private-range filter — never inside the CTE.

This same pair (strict regex + barrier, plus `ip_address <> ''`) applies to the events-derived IP of
the R5 rule above — see C-22/P1-6.

**B2a — free-mail list: reuse the existing set, PLUS a sanctioned benchmark-specific addendum, MINUS
two real employers (C-26).** The repo has ONE existing list:
`apps/api/services/content_reader.py::_GENERIC_DOMAINS` (line 607) — a plain `set`, not a
`frozenset` (C-27b). Reuse it by import — do not copy it and do not invent a *replacement* list. If
the extraction script cannot import it without pulling heavy transitive imports, promote the set to a
small shared module and update the one existing consumer (`content_reader.py:740`) in the same
commit; that is the only sanctioned alternative.

**But the reused set is unfit for this purpose as-is, and the earlier "do not extend it" instruction
is withdrawn.** `_GENERIC_DOMAINS` (14 entries) was built for a different job — "never treat a match
here as a domain-confidence signal" — and as a benchmark free-mail exclusion it fails in BOTH
directions. The sanctioned fix is a **benchmark-specific addendum layered ON TOP of the imported
set**, defined in `build_ip_org_benchmark.py` and never written back into `content_reader`:

```
FREE_MAIL_EXCLUDE = (
    (_GENERIC_DOMAINS | BENCHMARK_FREE_MAIL_ADDENDUM) - BENCHMARK_REAL_EMPLOYERS
)
```

- **ADD (omissions that silently DEPRESS precision** — an `@live.com` visitor enters the corpus
  carrying the fabricated expected-org `live`, which can never match): `live.com`, `msn.com`,
  `me.com`, `googlemail.com`, `mail.com`, `gmx.com`, `yandex.ru`, `qq.com`, `163.com`, `naver.com`,
  `zoho.com`, `proton.me`.
- **REMOVE for this purpose only** (`BENCHMARK_REAL_EMPLOYERS`): `linkedin.com` and `x.com`. They are
  in `_GENERIC_DOMAINS` because they are not domain-confidence signals, but they ARE real employers —
  their staff are correctly-labelled rows and excluding them silently removes valid ground truth.
  They stay excluded in `content_reader`'s own use; only the benchmark drops them.

**Rationale is folded into KG-3 and the report's limitations paragraph:** the exclusion set is a
judgment list, not an exhaustive one, and any residual free-mail domain still leaking through biases
the headline number DOWNWARD (fabricated expected-orgs that cannot match). State that direction
explicitly so the baseline is read correctly by the next phase.

**B3 — extraction script `scripts/build_ip_org_benchmark.py`.**
- SELECT-only. Enforced structurally: open the connection with
  `asyncpg.connect(...)` then `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` before any
  query, so any accidental write raises `ReadOnlySQLTransactionError` at the server, not at review
  time. Do NOT reuse `async_session` (it is a read-write factory).
- Requires an explicit `--database-url` argument OR an explicit `IP_ORG_BENCHMARK_DSN` env var.
  It must NOT silently read `settings.database_url` — that is the exact footgun documented in
  `all-context.md` (`.env` → Supabase prod). Remote DSNs ARE allowed here (this is the inverse of
  `refresh_ip_org.py`'s guard: read-only, so remote is the point), but must be explicit. This is the
  PROD DSN of the Q13 split — the local `localhost:5433` DSN belongs to the measurement script.
- **Never SELECTs `email`.** The query selects `split_part(email, '@', 2) AS email_domain`, so the
  local-part is never transmitted over the wire and never exists in process memory (CONCERN-6). This
  is what makes Q4's "email local-parts never leave the database" literally true rather than
  aspirational.
- Joins on BOTH `site_id` AND `visitor_id` (R3) — never a single-column join.
- Applies the agent-origin exclusion (R4) and the IP-provenance rule (R5) exactly as B2 states, and
  records in the phase report which optional columns (`is_agent_operated`, `is_internal_suspect`)
  actually exist on this branch and were applied.
- Issues `SET TIME ZONE 'UTC'` on connect so the naive `resolved_at` comparison is unambiguous (R13).
- Writes `benchmark-corpus.tsv` into this task folder with header
  `ip\temail_domain\texpected_org\tstratum`.

  **`expected_org` derivation — specified as an implementable helper (P1-2).** The earlier phrase
  "`normalize_org_name(email_domain minus its public suffix)`" had **no implementing function in the
  repo**: `registrable_domain()` returns suffix-plus-label (`deloitte.co.uk`, not `deloitte`), and
  `normalize_org_name("acme.com")` returns `"acme com"` (it only strips LEGAL suffixes, and `.`
  becomes whitespace via `_PUNCT_RE`). `content_reader._domain_root` does do this, but it is named
  Out of Scope. So the script defines its own three-line helper INSIDE
  `build_ip_org_benchmark.py`, reusing the **same vendored PSL module WS-D ships**:

  ```
  from apps.api.services.public_suffix import registrable_domain

  def label_root(email_domain: str) -> str | None:
      reg = registrable_domain(email_domain)          # e.g. "deloitte.co.uk"
      if not reg:
          return None
      suffix = reg.split(".", 1)[1]                   # the public suffix: "co.uk"
      return reg[: -(len(suffix) + 1)]                # leftmost label: "deloitte"

  expected_org = normalize_org_name(label_root(email_domain))
  ```

  i.e. take the registrable domain via the PSL parser, strip its public suffix (the registrable
  domain is by construction `suffix + one label`, so the leftmost label IS the root), THEN normalize.
  Worked example, now consistent end-to-end: `deloitte.co.uk` → registrable `deloitte.co.uk` → strip
  `.co.uk` → `deloitte` → normalize → `deloitte`. And `acme.com` → `acme.com` → `acme` → `acme`.
  A `None` from `label_root` (bare public suffix, unparseable) excludes the row.

  **This is an IN-PACK dependency: WS-B depends on WS-D's `public_suffix.py`.** The existing
  A → C → D → E → B sequencing already satisfies it — do not reorder B ahead of D.

  `stratum` is written as the literal `pending` by this
  script and filled in by the measurement script from the LOCAL corpus (Q13), because
  `ip_org_prefixes` is EMPTY on prod and a prod-side stratum derivation would label every row
  `none`.
- Adds `process/features/visitors-identity/active/ip-org-quality-pack_08-08-26/benchmark-corpus.tsv`
  to `.gitignore` as part of the same change.
- **Target size ~500-600 EXTRACTED rows (C-31), not ~300.** The ~200 figure is the post-stratum
  HEADLINE target; the predicted-row floor (stratum `org`) is the actual go/no-go at ≥80 (P1-4).
  Rationale for raising the extraction target: the chain ~300 extracted → ~200 headline → ~80
  predicted lands EXACTLY on the `< 80` descope floor with ZERO headroom, and the 60 % eyeball
  assumption behind it is optimistic — prefix-share ≠ visitor-share, and real visitor IPs skew
  consumer (higher eyeball share → fewer stratum-`org` predicted rows than 40 %). Extracting ~500-600
  gives roughly a 2× predicted-row cushion above the floor, so a worse-than-assumed eyeball ratio does
  not silently sink the measurement below 80 predicted rows after a prod read has already been spent.
  If B1's upper bound is below ~500-600, extract everything B1 offers; if it is above, sample randomly
  with a fixed seed and record the seed. (Alternative considered and rejected: keep ~300 and make the
  floor recoverable by re-extracting with a larger LIMIT on a shortfall — that spends a SECOND prod
  read on data already knowable up-front, and prod reads are the constrained resource here.)

**B4 — measurement script `scripts/measure_ip_org_precision.py`.**
- Takes its own explicit `--database-url`, which MUST be the LOCAL `localhost:5433` DSN (Q13); a
  non-local DSN is refused with a non-zero exit, since prod's `ip_org_prefixes` is empty and would
  silently produce an all-`None` run.
- **Enables the lookup flag in-process before any lookup** (Q12): `settings.ip_org_lookup_enabled =
  True`, logged. Calling the services "directly" does NOT bypass the guard — both
  `lookup_ip_org` (`ip_org_lookup.py:66`) and `lookup_ip_org_v2` (`:153`) check it. `ip_org_fusion_enabled`
  is deliberately NOT touched: `lookup_ip_org_v2` never reads it (its only reader is
  `company_resolver.py:610`), so setting it would be a misleading no-op.
- **Non-vacuity precondition, checked FIRST and fatal.** Before scoring, the script asserts
  (a) `settings.ip_org_lookup_enabled is True`, and (b) `SELECT count(*) FROM ip_org_prefixes > 0`
  on the connected DB. If either fails it exits non-zero with
  `FAILED-INVALID: measurement environment cannot produce a non-None prediction` and writes **no**
  report. A run that produces zero non-`None` predictions on BOTH arms is likewise recorded as
  `FAILED-INVALID`, never as "v1 and v2 tie at 0 %". An invalid run does not satisfy G8.
- **Derives `stratum` with its own unfiltered query** (Q14 SQL above), never from a lookup return
  (FAIL-4). No-match → `none`, kept distinct from `pending`.
- For each IP calls BOTH `lookup_ip_org(db, ip)` (v1, flat) and `lookup_ip_org_v2(db, ip)` (fused).
- **Names the scored FIELD explicitly (R2).** v1 scores `match["org_name"]`; v2 scores
  `hypothesis["organization"]`. **`domain` is NEVER scored** — it is NULL by construction in this
  pack (the domain leg was split out of Phase 3 per Decision 2 Option B and `resolve_org_domain` was
  never built). Any report line implying a domain-level precision number is a defect.
- Scores each prediction with the Q5 matcher; records `(ip, expected, v1_pred, v1_match,
  v1_method, v2_pred, v2_match, v2_method, v2_confidence, v2_classification, stratum)`.
- **Reports the three Q14 measurements, and NOT a two-arm precision comparison (R1):**
  - **(a) Single-arm precision** on the headline set (strata excluding `datacenter`/`cdn`), with the
    denominator defined as **rows carrying a non-None prediction** and **coverage reported separately**
    (P1-3). `match_method` appears as a **numerator decomposition** (share of *correct* predictions by
    method, exact vs token_subset) — never as a per-method precision. Per-stratum breakdown shows each
    stratum's predicted-row count so a zero-prediction stratum is visible rather than implied.
  - **(b) Per-reachable-value calibration table** — one row per reachable `v2_confidence` value
    (`0.20, 0.25, 0.40, 0.45, 0.55, 0.60, 0.65`) with n and accuracy, and the inline note that the two
    values reachable ONLY via `rpki=invalid` (`0.20` and `0.25`; note `0.40` is ALSO reachable via
    `rpki=invalid` but reachable by other paths too, so it is not exclusive) are expected near-empty
    at N≈200 (P1-1, C-35). The four-equal-width-bucket framing is withdrawn and must not appear.
  - **(b2) Accuracy by `v2_classification`** (`registered_operator` / `likely_operational_customer` /
    `disputed_origin` / `unclassified` — all FOUR reachable values, C-34; `unclassified` is the total-
    function fallback at `ip_org_fusion.py:289-297` and will be common) with row counts (P2-9) — the
    collected-but-unconsumed field.
  - **(c) `v1_pred == v2_pred` invariant** — asserted for every row ONLY when its precondition holds;
    any divergence is reported as a BUG list with the offending IPs' strata, never as a precision
    delta. **Precondition (P2-8/C-28): a duplicate-prefix probe must return ZERO rows.** Because the
    invariant runs through the UNTOUCHED production SQL (`_LOOKUP_SQL`, `_V2_ROUTE_ORIGIN_SQL` — both
    non-total, KG-9), the script's own `, id` tie-break cannot make it deterministic; the invariant is
    meaningful only when no equal-masklen duplicate prefixes exist. Before asserting, run
    `SELECT prefix, count(*) FROM ip_org_prefixes WHERE relationship_type='route_origin' GROUP BY prefix HAVING count(*) > 1`:
    zero rows → assert the invariant, divergence is a real BUG; non-zero rows → **SKIP the invariant
    (record as not-run with the duplicate count), do NOT FAIL it** (a divergence there is a data
    property of production ordering, not a defect). The `, id` tie-break still applies to every query
    THIS script issues against `ip_org_prefixes` (stratum derivation etc.), for run-to-run stability.
    State the probe result in the report.
- **Coverage / None-rate (R6), mandatory.** This pack ships two org-bucket NARROWING changes (C4's
  family inheritance and E3's APNIC pre-check) and then measures precision only — recall falls by
  construction and would otherwise go unmeasured. The report MUST carry the per-arm `None`-rate
  (share of corpus IPs with no prediction) and the corpus coverage percentage. Honest limitation to
  state alongside it: **no pre-C/E baseline exists** (the measurement runs after C and E land, per
  the A → C → D → E → B sequencing), so the coverage number is a forward baseline for the NEXT
  phase, not a before/after delta. Recorded as KG-7.
- **Limitations section (C-17b) must name:** the exclusion criterion is produced by the system under
  test — a row leaves the headline set because *this pipeline* called its prefix `datacenter` —
  which systematically removes a class of the pipeline's own misclassifications from the headline
  number. State it next to KG-3 rather than leaving it implicit.
- Writes `ip-org-precision_REPORT_08-08-26.md` into this task folder. Aggregates only — no IPs, no
  domains — so the report IS committed.

**B5 — gate.** The gate asserts a measurement was **produced and is non-vacuous**: report exists;
row count matches corpus size; **≥ 80 rows carry a non-`None` prediction** (the P1-4 floor — not
"≥ 1", because a single prediction is not a measurement and the eyeball/none strata contribute
none); the stratum column holds **at least one value in {`eyeball`, `datacenter`, `cdn`}
specifically** (C-20 — the earlier "other than `org`/`pending`" clause is satisfied by `none`, which
is trivially reachable for any IP absent from `ip_org_prefixes` and therefore proves nothing about
whether the datacenter/CDN headline exclusion is operative; eyeball prefixes are ~26.9 % of the
loaded corpus so a real visitor-IP sample will contain them); and the per-reachable-value
calibration, `v2_classification`, coverage/None-rate and invariant sections are all present. It asserts **no
precision threshold** — following the Phase-3 AC4.12 precedent: this is the first measurement, so
there is no prior to threshold against, and a fabricated threshold would either be trivially met or
block the pack on a number nobody has justified. The number this produces becomes the baseline for
the NEXT phase.

### WS-C — Retain as2org `organizationId` (XS)

Closes follow-ups item 4's sizing question and adds classification consistency.

**C1.** `apps/api/models/ip_org_prefix.py`: new column
`as2org_org_id: Mapped[str | None] = mapped_column(String(64), nullable=True)` with a comment
stating it is CAIDA's opaque org handle (e.g. `LPL-141-ARIN`), populated only for
`source="caida_pfx2as"` rows, and NULL for every other evidence class by construction.

**C2.** Migration, additive, nullable, no index (no query filters on it yet — an index on a 1 M-row
table for zero readers is pure write cost). **Chain off the LIVE head re-derived at EXECUTE time**
via `.venv/bin/python -m alembic -c apps/api/alembic.ini heads` with `DATABASE_URL` pinned to
`localhost:5433` — `c4a8f13e07b6` was head at plan-write time but concurrent programs move it (see
the migration-collision memory note).

**C3.** `parse_as2org` currently builds `asn_to_org_id` and `org_id_to_name` and then **discards
the org_id** in its final comprehension (`ip_org_ingest.py:225-230`). Change its return type to
`dict[int, tuple[str, str]]` mapping `asn → (org_name_raw, org_id)`. Update the one caller
(`refresh_ip_org_dataset`'s row loop) and every existing fixture-based unit test. This is a
breaking signature change to a public-ish parse function — grep for all callers before editing.

**C4 — org-family classification pass (Q6, with the R9 lateral-move guard).** In
`refresh_ip_org_dataset`, after parsing and before the row loop, build `org_id → kind` by running
`classify_ip_org_kind` over every ASN and folding per family with the precedence
`cdn > datacenter > eyeball > org` (i.e. any non-`org` member makes the family non-`org`; if two
different non-`org` kinds appear, the leftmost in that precedence wins — deterministic, and the CDN
bucket has the strongest keep-but-never-resolve semantics).

**Inheritance applies ONLY to rows whose OWN per-ASN kind is `org` (R9).** Pseudocode:

```
own = classify_ip_org_kind(asn, org_raw)
kind = family_kind if (own == "org" and family_kind != "org") else own
```

Without that guard the fold permits LATERAL moves — an ASN the token path already classified
`eyeball` could be overwritten to `cdn` (or `datacenter`) by a sibling, changing a classification
that was already correct and non-`org`. Q6's stated intent is one-directional (`org → non-org`) and
the guard is what makes the code match the intent. Never the reverse direction (Q6).

**C4a — shared-INSERT safety (CONCERN-3).** `_load_staging_and_swap`'s `insert_sql`
(`ip_org_ingest.py:388-395`) is SHARED with `refresh_rir_allocations`. When `as2org_org_id` is added
to the column list, an explicit `"as2org_org_id": None` MUST be added to the chunk dict alongside the
existing `relationship_type` / `valid_from` / `valid_to` defaults and **BEFORE** the `**row` splat,
so CAIDA rows override it and RIR rows (which never carry the key) still bind. Omitting the default
breaks the RIR job on its next run with a missing-bind-parameter error. A unit test asserts an
RIR-shaped row (no `as2org_org_id` key) still builds a complete chunk dict.

**C5.** Add to the ingest summary + `ip_org_ingest_parsed` log:
`multi_asn_families` (families with ≥2 member ASNs) and `multi_asn_family_fraction`
(their share of all ASNs). Add `family_reclassified` = count of rows whose kind changed because of
C4.

**C6 — fixture ASNs MUST come from the documentation/private reserved range (P2-10).** WS-C's
fixtures are written BEFORE WS-E's E3 rewrites `classify_ip_org_kind` to consult the APNIC eyeball
set. If a C6 fixture reuses a real-world ASN that later appears in the vendored
`eyeball_asns.json`, that ASN silently flips to `eyeball` when E3 lands and a green G10 turns red —
a composition failure between two workstreams in the same pack, with the blame landing on E.
**Therefore every C6 fixture ASN is drawn from the private-use range `64512–65534`**, which is
guaranteed absent from any APNIC per-AS population list (reserved ASNs announce no routes and have
no user population). State the constraint in a comment in the fixture so a future editor does not
substitute a "realistic" ASN. The same constraint applies to any new G10/G12 fixture.

Unit tests in `tests/unit/test_ip_org_ingest.py`: `parse_as2org` returns the org_id;
a family where one ASN is `telekom`-shaped promotes its `org` sibling to `eyeball`; a family where
one ASN is `org` does NOT demote a sibling `cdn` to `org` (the downward guard); **a family
containing both an `eyeball` ASN and a `cdn` ASN leaves BOTH unchanged — no lateral move (R9)**;
families of size 1 are unchanged; the multi-ASN counters are correct on a fixture with a known
family layout.

### WS-D — `_extract_domain` via Public Suffix List (XS–S)

**D1.** Vendor `apps/api/data/public_suffix_list.dat` from `https://publicsuffix.org/list/`.
Committed as-is, with the fetch date and source URL recorded in the phase report (the file itself
carries its own licence header — do not strip it).

**D2.** New pure module `apps/api/services/public_suffix.py`:
- `_load_rules()` — `@lru_cache(maxsize=1)`, reads the vendored file, skips blank lines and `//`
  comments, returns `(rules: frozenset[str], exceptions: frozenset[str])` where exception rules are
  the `!`-prefixed ones with the `!` stripped. **ICANN section ONLY (Q10)**: track the
  `// ===BEGIN ICANN DOMAINS===` / `// ===END ICANN DOMAINS===` markers while scanning and ignore
  every rule outside them, so no PRIVATE-section (cloud-tenant) suffix ever enters the rule set.
- `registrable_domain(hostname: str) -> str | None` — lowercase, strip trailing dot; walk the
  labels right-to-left finding the longest matching rule (literal match, then `*.<parent>`
  wildcard); an exception rule shortens the match by one label; the registrable domain is the
  matching public suffix plus one more label. Returns `None` when the hostname IS a public suffix
  with nothing in front of it, or has fewer labels than the rule requires.
- No I/O beyond the one cached file read, no network, no new dependency.

**D3.** `apps/api/services/company_resolver.py::_extract_domain` (lines 87–122): delete the
hardcoded `two_part_tlds` set, its **early `return`** (:109-110), and the manual
`parts[-2].parts[-1]` slicing; call `registrable_domain(hostname)` instead. The digit-only IP check,
`_build_domain_filter_regex`, and `_build_hostname_filter_regex` all remain, and **every** result
now flows through them — including two-part-TLD hosts, which bypass both filters today.

The resulting behavior change is **bidirectional** (Q11), not pure widening:

| Class | Hostname | Today | After D3 | Direction |
|---|---|---|---|---|
| Two-part-TLD ISP host (filters bypassed today) | `dsl-pool.host.talktalk.co.uk` | `talktalk.co.uk` | `None` (`_build_domain_filter_regex` at `:115` fires first — `talktalk` is a `_DOMAIN_PATTERNS` entry, C-19) | **NARROWS** |
| Two-part-TLD ISP host | `c-1-2-3.hsd1.virgin.co.uk` | `virgin.co.uk` | `None` (same domain-filter path; `virgin` is also a `_DOMAIN_PATTERNS` entry) | **NARROWS** |
| **Two-part-TLD host caught by the HOSTNAME filter only — a REAL corporate domain (P2-12)** | `dhcp-1-2-3.acme.co.uk` | `acme.co.uk` | `None` (`acme` is NOT in `_DOMAIN_PATTERNS`, so `:115` passes; `_build_hostname_filter_regex` at `:119` fires on the `dhcp` token — `_HOSTNAME_PATTERNS` at `company_resolver.py:65-70` holds `dsl`/`dial`/`dhcp`/`pool`/`dynamic`/`hsd1`/`residential`/…) | **NARROWS** |
| Unknown multi-part suffix | `foo.bar.gov.br` | `gov.br` (a public suffix returned as a "company domain") | `bar.gov.br` | **CORRECTS** |
| Unknown two-part suffix, 3 labels | `x.co.za` | `co.za` (public suffix) | `x.co.za` (suffix `co.za` + one label — the PSL rule, D2 spec) | **CORRECTS** |
| **3-label host under one of the 8 old hardcoded TLDs** | `x.co.uk`, `google.co.uk`, `bbc.co.uk`, `acme.com.au` | `None` (3-label host falls to the bare `return None` at `:110`) | `x.co.uk` / `google.co.uk` / `bbc.co.uk` / `acme.com.au` | **WIDENS** |
| Ordinary | `mail.google.com` | `google.com` | `google.com` | unchanged |

**The NARROWS class has TWO distinct subclasses, and the second is the higher-impact one (P2-12).**
Subclass (i) is domain-filter-caught (`talktalk`, `virgin` — known ISP brands); subclass (ii) is
**hostname-filter-only**, where the registrable domain is a genuine corporate domain and only the
HOSTNAME looks residential (`dhcp-…`, `pool-…`, `dsl-…` prefixes on a company's own two-part-TLD
domain). Subclass (ii) removes a real employer from `company_graph` where subclass (i) removes a
consumer ISP — so it is the more consequential half of the narrowing, and it was invisible in the
table until now. It is still the RIGHT behavior (a DHCP-pool hostname is weak evidence of employment
and every other TLD's hosts already get filtered this way), but it must be gated explicitly, not
discovered in prod. Covered by G21 and named in D4's census answer (a).

Two further corrections carried by the table above, both found by later PVL cycles:

1. `foo.bar.gov.br` and `x.co.za` do NOT return `None` today — they return the public suffix itself,
   i.e. a fabricated company domain written into `company_graph`.
2. **The change has a THIRD class, `WIDENS`, and it is almost certainly the highest-volume of the
   three (FAIL-3).** Every 3-label host under the eight hardcoded suffixes (`co.uk`, `com.au`,
   `co.jp`, `com.br`, `co.in`, `com.sg`, `co.kr`, `com.vn`) returns `None` today because the
   two-part branch requires ≥3 labels *plus* something in front; `google.co.uk`, `bbc.co.uk` and
   `acme.com.au` currently resolve to nothing and will start resolving to a real domain that is
   written through to `company_graph`. Cycle 1 mislabelled a narrowing as widening; cycle 2 found a
   widening mislabelled "unchanged" in the same table. Both are now explicit.

This sits on the live rDNS path (`resolve_company_from_ip` → `company_graph` write-through), which is
why AC-D2, AC-D3 **and** AC-D4 all gate it. Note (Q15/KG-6): the improvement does not reach live
reads for 30–75 days because of the Redis `company_ip` and `company_graph`-staleness caches.

**D4 — caller census (do before editing), re-aimed at the real exposure.** Run
`grep -rn "_extract_domain\|resolve_company_from_ip\|resolve_company_cached" apps/api tests scripts`.
**The `resolve_company_cached` token is mandatory (R7):** the largest consumer of this surface is
`visitor_aggregator.py:749` / `:774`, which calls `resolve_company_cached` — neither of the two
original grep tokens appears there — and writes `visitors.company_domain` plus rows in the
`companies` table. A census without that token misses the biggest downstream writer entirely.

The question is NOT "who depends on the old `None`" (the old `None` set barely moves). The three
questions that matter, all derived from the D3 table:

- **(a) Who consumes a domain that D3 will stop producing?** i.e. any caller/consumer that today
  receives `talktalk.co.uk`-class values from a two-part-TLD ISP host and treats them as a company.
  Concretely: `resolve_company_from_ip` → the `company_graph` write-through
  (`source="rdns"`), and anything reading `company_graph.domain`/`company_name`. Confirm no consumer
  *requires* those rows to keep appearing. **Answer BOTH narrowing subclasses separately (P2-12):**
  (i) the domain-filter-caught ISP class (`talktalk.co.uk`), and (ii) the **hostname-filter-only
  class where the lost domain is a REAL corporate domain** (`dhcp-1-2-3.acme.co.uk` → `acme.co.uk`
  today → `None`). Subclass (ii) is the one that costs real employers, and a census that reports only
  an aggregate "fewer domains resolved" number hides it.
- **(b) Who consumes a domain that D3 will CHANGE?** i.e. hosts whose value moves from a bare public
  suffix (`gov.br`, `co.za`) to a real registrable domain. Confirm no caller keys, caches, or
  dedupes on the old string.

- **(c) Who NEWLY receives a domain that D3 starts producing (FAIL-3, the WIDENS class)?** Every
  3-label host under the eight old hardcoded TLDs goes `None` → a real domain. Confirm the new
  write-through volume is acceptable on `company_graph` (`source="rdns"`), on
  `visitors.company_domain`, and on the `companies` table via `resolve_company_cached`. This is the
  highest-volume half of the change and the census originally did not ask about it at all.

Record all three answers in the phase report with the grep output. Two explicit non-goals to state
alongside them:

- **Already-written `company_graph` rows produced by the old logic are NOT rewritten**; a cleanup
  sweep for public-suffix-shaped `company_graph.domain` values is named in Out of Scope. The same
  applies to historical `visitors.company_domain` and `companies` rows (R7).
- **The caches are NOT invalidated (Q15/KG-6)**: Redis `company_ip` (30d TTL) and
  `company_graph` staleness (75d default) keep serving old-logic values on the live read path for up
  to that long after deploy. Record the accepted lag in the census answers.

STOP and surface only if (a), (b) or (c) finds a hard dependency — a *count* changing is expected and
is not a stop condition.

**D5 — tests, three groups.**

*(i) `tests/unit/test_public_suffix.py` (NEW) — pure `registrable_domain` matrix:*
`mail.google.com` → `google.com`; `vpn-us.apple.com` → `apple.com`; `a.b.co.uk` → `b.co.uk`;
`foo.bar.gov.br` → `bar.gov.br`; **`x.co.za` → `x.co.za`** (suffix + exactly one label — the D2 spec;
the earlier `None` was wrong, FAIL-3); **`x.co.uk` → `x.co.uk`** (the WIDENS class at the PSL layer);
`co.uk` alone → `None`; a `*` wildcard rule (`*.ck`: `a.b.ck` → `b.ck`); an exception rule
(`!www.ck`: `www.ck` → `www.ck`); unknown TLD `host.invalidtld` → implicit `*` rule →
`host.invalidtld`; empty and single-label input → `None`;
**ICANN-section scoping (Q10): `ec2-1-2-3-4.compute-1.amazonaws.com` → `amazonaws.com`**, proving no
PRIVATE-section rule was loaded.

**Two-layer distinction — the amazonaws proof case lives HERE and only here (R12).**
`test_company_resolver.py:71` already asserts `_extract_domain` returns `None` for an
`amazonaws`-shaped host, because `amazonaws` is a `_DOMAIN_PATTERNS` entry and the domain filter
rejects it. Asserting `amazonaws.com` at the resolver layer would directly contradict that existing
test. So: the **registrable-domain layer** (`test_public_suffix.py`) proves
`ec2-…compute-1.amazonaws.com` → `amazonaws.com`; the **resolver layer**
(`test_company_resolver.py`) proves the FILTERED outcome `None`. Both are correct; they are
different layers, and no gate may assert the PSL value at the resolver layer.

*(ii) `tests/unit/test_company_resolver.py` — OLD rejections still reject (AC-D2 / G14):*
the existing ISP/VPN/residential/cloud cases stay green, unchanged.

*(iii) `tests/unit/test_company_resolver.py` — NEWLY-rejected set (AC-D3 / G21, closes CONCERN-11):*
explicit cases asserting `_extract_domain` now returns `None` where it returns a domain today —
`dsl-pool.host.talktalk.co.uk`, `c-1-2-3.hsd1.virgin.co.uk`, **and the hostname-filter-only subclass
`dhcp-1-2-3.acme.co.uk` → `None` (P2-12), whose comment must state that the lost value
`acme.co.uk` was a REAL corporate domain, not an ISP** — plus the corrected case
`foo.bar.gov.br` → `bar.gov.br` and **`x.co.za` → `x.co.za`** (FAIL-3: the earlier `None` was wrong).
Each case carries a one-line comment naming the old return value, so a future reader sees the
intentional behavior change rather than mistaking it for a bug. Per R12 this group asserts
resolver-layer outcomes ONLY — the ICANN/`amazonaws.com` proof stays in group (i).

*(iv) `tests/unit/test_company_resolver.py` — NEWLY-WIDENED set (AC-D4 / G22, closes FAIL-3):*
the class that has never had a gate. Cases asserting `_extract_domain` now returns a domain where it
returns `None` today: `google.co.uk` → `google.co.uk`, `bbc.co.uk` → `bbc.co.uk`,
`acme.com.au` → `acme.com.au`, `x.co.uk` → `x.co.uk`. Each carries a comment naming the old `None`.
This is the highest-volume half of the WS-D change and the half a regression-only gate cannot see.

### WS-E — APNIC eyeball ASN list (S–M)

**E1.** New service `apps/api/services/apnic_eyeball_refresh.py`, modeled directly on
`apps/api/services/agent_ip_range_refresh.py`:
- `_DATA_DIR = apps/api/data/apnic_eyeball/`, `_RUNTIME_DIR = _DATA_DIR / "runtime"`, same
  vendored-fallback-plus-runtime-override layout.
- `refresh_apnic_eyeball_asns() -> dict[str, int]` — httpx async fetch with an explicit timeout
  **and an explicit maximum-response-size cap** (CONCERN-9): stream the response and abort once
  `settings.ip_org_apnic_max_bytes` is exceeded, following the existing
  `ip_org_rpki_max_bytes: int = 209_715_200` precedent at `config.py:777`. Default
  `ip_org_apnic_max_bytes: int = 33_554_432` (32 MB — the aspop dataset is ~100 k records, orders of
  magnitude under this, so the cap only fires on a hostile or corrupt response). Exceeding the cap is
  a fail-open outcome: log, keep the existing file, return.
  `settings.mock_external_apis` short-circuit returning a deterministic fake, fail-open on any
  exception (log + keep the existing file), writes `eyeball_asns.json`.
- Source: the APNIC per-AS population dataset behind `stats.labs.apnic.net/aspop/`. The exact
  machine-readable URL and response shape MUST be confirmed at EXECUTE time by fetching it once
  and recording the observed shape in the phase report — this is the same discipline that caught
  the camelCase as2org defect. Parser must tolerate both a list-of-objects and a
  keyed-object shape, and skip unparseable records rather than aborting.
- `load_eyeball_asns() -> frozenset[int]` — `@lru_cache(maxsize=1)`, reads the runtime file if
  present else the vendored one, filters to ASNs whose estimated user count ≥
  `settings.ip_org_eyeball_min_users`.

**E2.** New settings: `ip_org_eyeball_min_users: int = 50_000`,
`ip_org_apnic_refresh_enabled: bool = False`, `ip_org_apnic_url: str = <confirmed URL>`,
`ip_org_apnic_refresh_interval_hours: int = 168`, `ip_org_apnic_max_bytes: int = 33_554_432`. The refresh job is registered in
`apps/api/jobs/scheduler.py` alongside the existing ip_org jobs, guarded by the enable flag,
following the flag-guarded `add_job` registration pattern at **`scheduler.py:733-766`** — NOT
`:362-400`, which is the job-wrapper coroutines, not the registration site (CONCERN-12).

**E3.** `classify_ip_org_kind(asn, org_raw)` gains the numeric pre-check:

```
if asn and asn in load_eyeball_asns():
    kind = classify_org_kind(...)          # still computed
    if kind in ("datacenter", "cdn"):
        return kind                        # infra beats population data
    return "eyeball"
```

Direction guard (Q8): APNIC can only produce `eyeball`; it can never turn an `eyeball`/`datacenter`
/`cdn` into `org`. The existing token path is unchanged and runs whenever the ASN is absent from the
set. **It does NOT run for `registered_holder` rows (C-18):** those never reach
`classify_ip_org_kind` at all — `_allocation_to_row` hardcodes `org_kind="registry"`
(`ip_org_rir_ingest.py:162`). The CAIDA-ASNs-absent-from-APNIC ground is the token list's real and
sufficient justification.

**E4.** Extend `_EYEBALL_ORG_TOKENS` with the carrier stems named in follow-ups item 7 — but
**only the genuinely NEW ones (R11)**. Verified already present and therefore excluded:
`telecom` (`ip_org_ingest.py:81`) and `deutsche telekom` (`:87`). Adding a fixture for a token that
already matches produces a green test that proves nothing.

**The earlier illustrative candidate list is WITHDRAWN — it reintroduced the exact defect (C-24).**
It named `telkom`, `telcom`, `mobil`, `wireless`; of those, **`telkom` is already present on
`ip_org_ingest.py:81`** (the same line cited for `telecom`) and **`wireless` is already present on `:82`**. Two of four candidates were the very "green test that proves nothing" case. No replacement
list is given, deliberately: **the grep is the specification.** At EXECUTE time, grep
`_EYEBALL_ORG_TOKENS` and add only stems with no existing match — note the existing entries are
substrings matched with `in`, so a candidate is "already present" whenever any existing token is a
substring of it or matches the same org strings. Add one fixture per genuinely-new token, and record
BOTH the added list and the excluded-because-already-present list in the phase report. This is the token-side half of
item 7 and stays valuable even where APNIC has no data.

**E5.** No backfill (Q9): the next scheduled full refresh re-classifies all 967 k rows. State this
explicitly in the phase report so nobody looks for a missing migration.

**E6.** Unit tests in `tests/unit/test_ip_org_ingest.py` + a new
`tests/unit/test_apnic_eyeball_refresh.py`: parser tolerates both shapes and skips junk records;
threshold filtering (an AS at 49 999 users is excluded, 50 001 included); `classify_ip_org_kind`
returns `eyeball` for an in-set ASN, still returns `cdn`/`datacenter` for an in-set ASN whose org
is Cloudflare-shaped (direction guard), and is unchanged for an out-of-set ASN; fail-open when the
runtime file is missing/corrupt; `mock_external_apis=True` never makes a network call.

**E6a — every test touching either loader MUST call `cache_clear()` first (P2-10).** Both
`public_suffix._load_rules()` and `apnic_eyeball_refresh.load_eyeball_asns()` are
`@lru_cache(maxsize=1)`. A fail-open test that swaps in a missing/corrupt runtime file after another
test has already populated the cache asserts against the FIRST test's data and passes vacuously.
Every test that varies the underlying file (fail-open, threshold-boundary, runtime-override) calls
`load_eyeball_asns.cache_clear()` — and `_load_rules.cache_clear()` for the PSL equivalents — in
setup. State this in the test file's module docstring so it is not dropped by a later editor.

**E6b — G17 needs a fixture that can actually FAIL if the `AS{asn} ` prefix is mis-built (P2-11).**
`classify_ip_org_kind` calls `classify_org_kind(f"AS{asn} {org_raw or ''}".strip())`, and
`classify_org_kind` matches on BOTH `_CDN_RELAY_ASNS` (parsed out of the `AS<num>` prefix,
`company_resolver.py:323`, used at `:352`) AND `_CDN_RELAY_ORG_TOKENS`. A Cloudflare-shaped fixture
therefore classifies `cdn` via the ORG TOKEN whether or not the ASN prefix was constructed correctly
— so the existing direction-guard case cannot detect a broken prefix. **Add a discriminating case:**
an org string containing **no** cdn/datacenter token at all (e.g. `"Example Holdings"`) whose ASN IS
a member of `_CDN_RELAY_ASNS`, asserted to classify `cdn`. That case passes ONLY if the `AS{asn} `
prefix is built and parsed correctly, and it is the only fixture in the matrix with that property.

## Acceptance Criteria

Every criterion names its proving gate and strategy. `Gate:` values refer to the Verification
Evidence table below (criterion ↔ gate is bidirectional).

| ID | Criterion (testable) | proven by | strategy |
|---|---|---|---|
| AC-A1 | After a staging→live swap, the live table has fresh planner statistics before the next lookup from another connection; the ~15.7 ms post-swap window is closed | G3 | Hybrid |
| AC-A2 | A refresh whose skip ratio exceeds `ip_org_skip_abort_ratio` returns `status="error"`, never calls `_load_staging_and_swap`, and leaves the existing table intact; a ratio above the warn threshold logs `ip_org_ingest_skip_ratio_high` and still proceeds | G1, G2 | Fully-Automated |
| AC-B1 | The corpus population is measured at THREE points — B1's SQL-only UPPER BOUND, the post-stratum headline-eligible count, and the **PREDICTED-row count (stratum `org`)** — all three recorded with the shrinkage between them. The operative `< 80` floor is on the PREDICTED count (P1-4), not on headline rows, because the `eyeball`/`none` strata sit inside the headline set and produce zero predictions; `< 80` at the upper bound or at the predicted count produces a backlog note and descopes WS-B (C-14) | G4 | Hybrid |
| AC-B2 | The corpus artifact contains no email local-parts (zero `@`), lives only in this task folder, and is gitignored; AND the extraction script's SOURCE contains no SELECT of a bare `email` column — every reference is `split_part(... '@', 2)` (C-33 static check, so a wire leak is caught at build time, not only in the written TSV) | G5 | Fully-Automated |
| AC-B3 | The extraction script cannot write: its session is server-side READ ONLY and it refuses to run without an explicitly supplied DSN | G6 | Hybrid |
| AC-B4 | The domain↔org matcher's fuzzy tier is bounded (subset + ≥1 token of length ≥4) and every result carries its `match_method` | G7 | Fully-Automated |
| AC-B5 | A measurement is produced and non-vacuous: the environment precondition passed (`ip_org_lookup_enabled` True in-process AND `ip_org_prefixes` non-empty), report exists, row count equals corpus size, **≥80 rows carry a non-None prediction on each arm** (P1-4 — not "≥1"), the stratum column holds **≥1 value in {`eyeball`,`datacenter`,`cdn`} specifically** (C-20 — `none` no longer satisfies it), and the **single-arm precision with its predicted-row denominator + separate coverage (P1-3), the per-reachable-value confidence table (P1-1), accuracy by `v2_classification` over all FOUR reachable values (`registered_operator` / `likely_operational_customer` / `disputed_origin` / `unclassified`, C-34) (P2-9), coverage/None-rate and the `v1==v2` invariant with its deterministic-tie-break precondition (P2-8, incl. the mandatory duplicate-prefix probe)** sections are all present (Q14/R1/R6 — the McNemar two-arm framing is withdrawn as degenerate). A zero-non-None run is `FAILED-INVALID`, never a passing tie. **No precision threshold is asserted** (AC4.12 precedent) | G8 | Hybrid |
| AC-C1 | CAIDA's `organizationId` survives parsing and reaches the row builder and the new column; no caller or fixture still expects the old `dict[int, str]` shape | G9 | Fully-Automated |
| AC-C2 | Org-family classification only moves a prefix `org → eyeball\|datacenter\|cdn`, never the reverse; single-ASN families are unchanged | G10 | Fully-Automated |
| AC-C3 | The `as2org_org_id` migration applies and reverses cleanly against a live Postgres, chained off the head derived at EXECUTE time | G11 | Hybrid |
| AC-C4 | The ingest summary reports `multi_asn_families`, `multi_asn_family_fraction`, and `family_reclassified` with values correct on a known fixture | G12 | Fully-Automated |
| AC-D1 | `_extract_domain` returns the correct registrable domain for multi-part public suffixes the old hardcoded 8-entry set got wrong (e.g. `foo.bar.gov.br`), and returns `None` for a bare public suffix | G13 | Fully-Automated |
| AC-D2 | Every hostname class the old code rejected is still rejected, and D4's three-question census (who loses a domain / whose domain changes / who newly receives one) is recorded with grep output covering `_extract_domain`, `resolve_company_from_ip` AND `resolve_company_cached` (R7) | G14 | Fully-Automated + Agent-Probe |
| AC-D3 | The NEWLY-rejected set is gated in BOTH its subclasses (P2-12): the domain-filter-caught ISP hosts (`dsl-pool.host.talktalk.co.uk`, `c-1-2-3.hsd1.virgin.co.uk`) AND the hostname-filter-only host whose lost value is a REAL corporate domain (`dhcp-1-2-3.acme.co.uk` → `acme.co.uk` today → `None`) all return `None` at the RESOLVER layer, and the corrected cases (`foo.bar.gov.br` → `bar.gov.br`, `x.co.za` → `x.co.za`) hold. The ICANN-section proof (`ec2-…compute-1.amazonaws.com` → `amazonaws.com`) is asserted at the PSL layer only, in `test_public_suffix.py`; the resolver layer asserts the FILTERED `None` (R12) | G21 | Fully-Automated |
| AC-D4 | The NEWLY-WIDENED class is gated: 3-label hosts under the eight old hardcoded TLDs return a real registrable domain where they return `None` today (`google.co.uk`, `bbc.co.uk`, `acme.com.au`, `x.co.uk`), and D4's third census question (who newly receives a domain) is answered with grep output including `resolve_company_cached` | G22 | Fully-Automated + Agent-Probe |
| AC-E1 | The APNIC refresh job is fail-open: any fetch/parse failure logs and keeps the existing file; junk records are skipped, not fatal | G15 | Fully-Automated |
| AC-E2 | Only ASNs at or above `ip_org_eyeball_min_users` enter the eyeball set, and `mock_external_apis=True` makes no network call | G16 | Fully-Automated |
| AC-E3 | The APNIC set can only produce `eyeball`; `datacenter`/`cdn` classifications win over it, and out-of-set ASNs follow the unchanged token path. **The matrix includes a discriminating ASN-prefix case (P2-11):** an org string with NO cdn/datacenter token whose ASN is in `_CDN_RELAY_ASNS` must still classify `cdn` — the only fixture that fails if the `AS{asn} ` prefix is mis-constructed | G17 | Fully-Automated |
| AC-E4 | The live APNIC response shape is observed once and recorded verbatim before any parser field name is committed | G18 | Agent-Probe |
| AC-Z1 | No regression: the unit lane matches or exceeds its pre-change baseline, and the integration lane is green | G19, G20 | Fully-Automated + Hybrid |

## Implementation Checklist

Ordered for execution. Each item is atomic and independently verifiable.

**WS-A**
1. Add `ip_org_skip_warn_ratio` (0.25) and `ip_org_skip_abort_ratio` (0.40) to the `ip_org_*` block in `apps/api/config.py` with the baseline-rationale comment.
2. Add the post-commit `ANALYZE "ip_org_prefixes"` + try/except + structlog events at the end of `_load_staging_and_swap` in `apps/api/services/ip_org_ingest.py`.
3. In `refresh_ip_org_dataset`, compute `skip_ratio`, add it to `summary`, and emit `ip_org_ingest_skip_ratio_high` above the warn threshold.
4. In `refresh_ip_org_dataset`, add the abort branch after the `dry_run` return and before the `if not rows` check.
5. Record the RIR non-goal as a FACT in the phase report (A5/CONCERN-10: `refresh_rir_allocations` has no skipped counter and no offered-row denominator — the guard is CAIDA-only) and write the KG-5 backlog stub. Do NOT add a counter to the RIR job in this pack.
6. Extend `tests/unit/test_ip_org_ingest.py` with the 5-case skip-ratio matrix + the "abort never calls swap" mock assertion. Run G1, G2.

**WS-C**
7. Add `as2org_org_id` (String(64), nullable) to `apps/api/models/ip_org_prefix.py` with its comment.
8. Re-derive the live alembic head (`DATABASE_URL` pinned to `localhost:5433`) and generate the additive migration in `apps/api/migrations/versions/`.
9. Change `parse_as2org` to return `dict[int, tuple[str, str]]`; grep every caller and fixture and update them in the same commit.
10. Add the `org_id → kind` family pass to `refresh_ip_org_dataset` with the `cdn > datacenter > eyeball > org` precedence and the direction guard.
11. Extend the row builder to write `as2org_org_id`, and the staging `INSERT` column list + chunk dict to carry it. **Add `"as2org_org_id": None` to the chunk-dict defaults BEFORE the `**row` splat** (C4a/CONCERN-3) so the shared `refresh_rir_allocations` path keeps binding; add the RIR-shaped-row unit test.
12. Add `multi_asn_families`, `multi_asn_family_fraction`, `family_reclassified` to the summary and the `ip_org_ingest_parsed` log.
13. Extend `tests/unit/test_ip_org_ingest.py` for C6, **drawing every fixture ASN from the reserved `64512–65534` range (P2-10)** so WS-E's APNIC set cannot later flip a fixture. Run G9, G10, G12; run the migration round-trip for G11.

**WS-D**
14. Run D4's re-aimed caller census (`grep -rn "_extract_domain\|resolve_company_from_ip\|resolve_company_cached" apps/api tests scripts` — the third token is mandatory, R7); record the grep output and ALL THREE answers (who loses a domain / whose domain changes / who newly receives one) plus the accepted cache-lag posture (Q15/KG-6) in the phase report; STOP and surface only on a hard dependency per the re-keyed BLOCK condition.
15. Vendor `apps/api/data/public_suffix_list.dat`; record source URL + fetch date.
16. Write `apps/api/services/public_suffix.py` (`_load_rules` cached + **ICANN-section-only scoping per Q10**, `registrable_domain`).
17. Replace the hardcoded `two_part_tlds` logic in `company_resolver._extract_domain` with `registrable_domain`, **deleting the early `return` at :109-110** so every result flows through both filters (Q11).
18. Write `tests/unit/test_public_suffix.py` (D5 group i — incl. the corrected `x.co.za` → `x.co.za`, `x.co.uk` → `x.co.uk`, and the ICANN `amazonaws.com` proof which lives HERE only, R12) + the OLD-rejection regressions (group ii) + the NEWLY-rejected matrix (group iii — **including the hostname-filter-only subclass `dhcp-1-2-3.acme.co.uk` → `None`, P2-12**) + **the NEWLY-WIDENED matrix (group iv)** in `tests/unit/test_company_resolver.py`. Run G13, G14, G21, G22.

**WS-E**
19. Fetch the APNIC per-AS population dataset ONCE; record the URL and the observed response shape verbatim in the phase report (G18) before writing any field name.
20. Add `ip_org_eyeball_min_users` (50 000), `ip_org_apnic_refresh_enabled` (False), `ip_org_apnic_url`, `ip_org_apnic_refresh_interval_hours` (168), `ip_org_apnic_max_bytes` (33 554 432) to `apps/api/config.py`.
21. Write `apps/api/services/apnic_eyeball_refresh.py` (`refresh_apnic_eyeball_asns` with the streamed max-bytes cap, `load_eyeball_asns`) on the `agent_ip_range_refresh` pattern; vendor the initial `apps/api/data/apnic_eyeball/eyeball_asns.json`.
22. Register the guarded refresh job in `apps/api/jobs/scheduler.py`, copying the flag-guarded `add_job` pattern at **`scheduler.py:733-766`** (not :362-400 — CONCERN-12).
23. Add the APNIC numeric pre-check to `classify_ip_org_kind` with the direction guard.
24. Grep `_EYEBALL_ORG_TOKENS` first; extend it with ONLY the genuinely-new carrier stems (`telecom` and `deutsche telekom` already exist at `:81`/`:87` — R11) and add a fixture per genuinely-new token; record the excluded-already-present list in the phase report.
25. Write `tests/unit/test_apnic_eyeball_refresh.py` + the `classify_ip_org_kind` cases, **including `cache_clear()` in setup for every test that varies the underlying file (E6a/P2-10) and the discriminating AS-prefix case — no cdn/datacenter org token + ASN ∈ `_CDN_RELAY_ASNS` → `cdn` (E6b/P2-11)**. Run G15, G16, G17.

**WS-B** (last — measures the improved pipeline)
26. Run the B1 SQL upper-bound count against a read-only **prod** DSN (Q13), joining on BOTH `site_id` AND `visitor_id` (R3) with the agent-origin exclusion applied (R4); record the number as an UPPER BOUND (C-14). If `< 80`, write the infeasibility backlog note and skip 27–31. Otherwise over-sample (**~500-600 extracted, C-31** — ~300 lands the ~80 predicted count EXACTLY on the floor with zero headroom and the 60 % eyeball assumption is optimistic) and defer the **real floor — `< 80` PREDICTED rows, stratum `org` (P1-4), not headline rows** — to step 31.
27. Resolve the free-mail list import path (reuse `content_reader._GENERIC_DOMAINS`, or promote it to a shared module and update its one consumer).
28. Write `scripts/build_ip_org_benchmark.py`: READ ONLY session, explicit **prod** DSN, `SET TIME ZONE 'UTC'` + naive `resolved_at` literal (R13), two-column join (R3), agent-origin exclusion HAND-INLINED in the raw SQL (C-30: `human_only_visitor_filter()` is a SQLAlchemy predicate builder and cannot compose into an asyncpg string) — `v.is_agent_operated=false AND v.is_internal_suspect=false AND v.is_bot_suspect=false AND v.is_abuse_flagged=false AND v.do_not_resolve=false AND iv.source_agent_visit_id IS NULL` (R4/C-25 — all columns exist, no presence check), with a phase-report note that the canonical helper (`agent_visitor_filters.py:19`) was deliberately not reused and a sync pointer to it, **cast-safe IP validity per B2b: octet-range-strict regex + `WITH … AS MATERIALIZED` barrier before any `::inet` cast (P1-5)**, **events-derived IP with the SAME validity predicates plus `ip_address <> ''` and the `created_at > '2026-07-26 09:13:43'` lower bound (C-22/P1-6)** or the documented KG-8 fallback, `split_part(email,'@',2)` so no local-part is selected, **the B2a free-mail set = `_GENERIC_DOMAINS` + benchmark addendum − {`linkedin.com`,`x.com`} (C-26)**, **`expected_org` via the in-script `label_root()` helper built on WS-D's `registrable_domain` (P1-2 — so WS-D MUST land first)**, `DISTINCT ON` per IP (attached to the OUTER query after the private-range filter, NOT inside the CTE, and the CTE projects columns explicitly — never `iv.*`/bare `email` — C-33), target **~500-600** extracted rows (C-31), `stratum` written as `pending`. Add the corpus filename to `.gitignore`.
29. Generate the corpus; verify zero `@` characters and `git check-ignore` (G5); verify the READ ONLY session with a probe write (G6).
30. Write `scripts/measure_ip_org_precision.py`: explicit **local** `localhost:5433` DSN (refuses non-local), in-process `settings.ip_org_lookup_enabled = True` (Q12 — do NOT touch `ip_org_fusion_enabled`), the FAILED-INVALID non-vacuity precondition, **`stratum` filled by its OWN unfiltered `ip_org_prefixes` query (Q14 SQL) — never from a lookup return (FAIL-4)**, datacenter/CDN strata excluded from headline numbers but reported, Q5 matcher scoring `org_name`/`organization` and never `domain` (R2), **single-arm precision with a predicted-row denominator + separate coverage (P1-3), the per-reachable-value confidence table over the 7 reachable values (P1-1), accuracy by `v2_classification` over ALL FOUR reachable values incl. `unclassified` (P2-9/C-34), coverage/None-rate, and the `v1==v2` invariant assertion GATED ON a zero-result duplicate-prefix probe (`GROUP BY prefix HAVING count(*)>1`; non-zero → SKIP the invariant, do not FAIL it — the invariant runs through untouched production SQL, C-28) — instead of the withdrawn McNemar comparison (Q14/R1/R6)**, `match_method` as a numerator decomposition, per-stratum breakdowns with per-stratum predicted counts, **`, id` deterministic tie-break on every query this script issues against `ip_org_prefixes` (P2-8)**, and the C-17b limitation paragraph. Plus matcher unit tests (G7).
31. Run the measurement; apply the REAL `< 80` floor to the **PREDICTED-row count (stratum `org`)**, recording all three population numbers and the shrinkage between them (P1-4/C-14), and descope if it fails; write `ip-org-precision_REPORT_08-08-26.md` (aggregates only), verify non-vacuity (G8), then delete `benchmark-corpus.tsv`.

**Closeout**
32. Run the full unit lane and the integration lane; compare against the pre-change baseline (G19, G20).
33. Write the known-gap backlog stubs: KG-1, KG-2, KG-3, KG-5, KG-6, KG-7, KG-8, **KG-9 (production lookup tie-break, new this cycle — P2-8)**; KG-4 already tracked by the parent program's runbook.

## Phase Completion Rules

- A workstream is **CODE DONE** when its checklist items are applied and its Fully-Automated gates
  are green. It is **✅ VERIFIED** only when its Hybrid gates have also been run and recorded with
  their exact command and outcome. Code-only completion is never VERIFIED.
- **WS-B is the exception in one direction only**: it reaches VERIFIED on "measurement produced and
  non-vacuous" (G8). It does not need a precision number to clear a bar, because no bar exists yet.
- No workstream may be marked complete while any of its acceptance criteria is proven ONLY by a
  Known-Gap. Every KG in this plan has a backlog stub and leaves its gate CONDITIONAL, not PASS.
- The pack as a whole is complete when WS-A, WS-C, WS-D, WS-E are VERIFIED, WS-B is either VERIFIED
  or formally descoped by the B1 go/no-go, AC-Z1 holds, and all backlog stubs are written.
- A `✅ VERIFIED` mark requires explicit user confirmation of the recorded Hybrid-gate evidence.
  An agent may mark CODE DONE on its own; it may never self-award VERIFIED.
- **WS-D BLOCK condition, re-keyed to the real exposure (FAIL-1).** The old condition ("a consumer
  depends on the old `None`") could not fire, because the `None` set barely moves. WS-D is
  **BLOCKED** — surfaced, not worked around — if D4's census finds either: (a) a consumer that
  *requires* the two-part-TLD domains D3 will stop producing (the `talktalk.co.uk` class), or
  (b) a consumer that keys, caches, or dedupes on a value D3 changes (the `gov.br` → `bar.gov.br`
  class). A change in the *count* of resolved domains is expected and is NOT a block condition.
- WS-D may not be marked CODE DONE while G21 **or G22** is unwritten: the narrowing half (G21) and
  the widening half (G22) are both invisible to a regression-only gate, and the widening half is the
  larger of the two (FAIL-3).
- **WS-D expected-value precedence (FAIL-3):** the D2 `registrable_domain` spec (public suffix +
  exactly one more label) is authoritative. If any table cell, test case or gate in this plan states
  an expected value that contradicts the D2 spec, the D2 spec wins and the discrepancy must be
  surfaced, never silently resolved.

## Touchpoints

| Path | WS | Change |
|---|---|---|
| `apps/api/services/ip_org_ingest.py` | A, C, E | ANALYZE in swap; skip-ratio compute/warn/abort; `parse_as2org` signature; org-family pass; `classify_ip_org_kind` APNIC pre-check; token list; summary fields |
| `apps/api/services/ip_org_rir_ingest.py` | — | **READ-ONLY — DO NOT EDIT (C-16).** A5/KG-5 descoped the RIR skip-ratio guard entirely; this file has no offered-row denominator and no skipped counter. Listed here only so a census reader knows it was considered and excluded |
| `apps/api/services/visitor_aggregator.py` | D | **READ-ONLY (R7)** — largest consumer of the `_extract_domain` surface via `resolve_company_cached` (`:749`, `:774`); writes `visitors.company_domain` and `companies`. Behavior changes underneath it; no edit in this pack |
| `apps/api/config.py` | A, E | 6 new settings in the `ip_org_*` block |
| `apps/api/models/ip_org_prefix.py` | C | `as2org_org_id` column |
| `apps/api/migrations/versions/<new>.py` | C | additive nullable column |
| `apps/api/services/company_resolver.py` | D | `_extract_domain` body |
| `apps/api/services/public_suffix.py` | D | NEW pure module |
| `apps/api/data/public_suffix_list.dat` | D | NEW vendored data |
| `apps/api/services/apnic_eyeball_refresh.py` | E | NEW service |
| `apps/api/data/apnic_eyeball/` | E | NEW vendored data dir |
| `apps/api/jobs/scheduler.py` | E | one new guarded job registration |
| `scripts/build_ip_org_benchmark.py` | B | NEW, read-only |
| `scripts/measure_ip_org_precision.py` | B | NEW, read-only |
| `.gitignore` | B | corpus TSV exclusion |
| `tests/unit/test_ip_org_ingest.py` | A, C, E | extended |
| `tests/unit/test_public_suffix.py` | D | NEW |
| `tests/unit/test_company_resolver.py` | D | regression additions |
| `tests/unit/test_apnic_eyeball_refresh.py` | E | NEW |
| `tests/integration/test_ip_org_pipeline.py` | A, C | ANALYZE + new column round-trip |
| `apps/api/services/content_reader.py` | B | READ (free-mail list); edited only under the B2a promotion path |

Read-only for context: `apps/api/services/ip_org_fusion.py`, `apps/api/services/ip_org_lookup.py`,
`apps/api/models/visitor.py`, `scripts/refresh_ip_org.py`.

## Public Contracts

| Contract | Change | Compatibility |
|---|---|---|
| `refresh_ip_org_dataset()` return dict | ADDS `skip_ratio`, `multi_asn_families`, `multi_asn_family_fraction`, `family_reclassified`; a new `status="error"` cause | Additive keys; the new error is a fail-open refusal that preserves existing data — same shape as the existing `"join produced zero rows"` refusal |
| `parse_as2org(payload)` | **BREAKING**: `dict[int, str]` → `dict[int, tuple[str, str]]` | Internal to `ip_org_ingest`; one production caller + fixtures. Must be updated in the same commit |
| `classify_ip_org_kind(asn, org_raw)` | Same signature; may now return `eyeball` where it returned `org` | Strictly narrows the `org` bucket, which is the bucket `lookup_ip_org` serves — fewer, better rows |
| `_extract_domain(hostname)` | Same signature; **THREE-CLASS behavior change (Q11 / FAIL-1 / FAIL-3)** — (a) **NARROWS**: two-part-TLD hosts under the old 8-entry set returned EARLY, bypassing `_build_domain_filter_regex` and `_build_hostname_filter_regex`; they now flow through both, so `dsl-pool.host.talktalk.co.uk` goes `talktalk.co.uk` → `None`. (b) **CORRECTS**: hosts under other multi-part suffixes returned the public suffix itself as a "company domain" (`foo.bar.gov.br` → `gov.br`, `x.co.za` → `co.za`); they now return `bar.gov.br` / `x.co.za`. (c) **WIDENS — the highest-volume class**: every 3-label host under the eight hardcoded suffixes returns `None` today and will return a real registrable domain (`google.co.uk`, `bbc.co.uk`, `acme.com.au`) | **Neither pure widening nor merely bidirectional.** Live rDNS path (`resolve_company_from_ip` → `company_graph` write-through) and, via `resolve_company_cached`, `visitors.company_domain` + `companies` (`visitor_aggregator.py:749`/`:774` — R7). Gated by D4's three-question census + AC-D2/G14 + AC-D3/G21 + AC-D4/G22. Already-written `company_graph` / `visitors.company_domain` / `companies` rows are NOT rewritten — explicit non-goal, cleanup named in Out of Scope. Live reads keep old values for 30–75 days (Q15/KG-6) |
| `ip_org_prefixes` schema | `+ as2org_org_id` nullable | Additive; no reader today |
| Config surface | 6 new settings | All default-safe: thresholds match observed-healthy behavior; `ip_org_apnic_refresh_enabled` defaults OFF |
| `content_reader._GENERIC_DOMAINS` | READ; promoted to a shared module only under B2a's alternative | If promoted, the single existing consumer is updated in the same commit |

## Blast Radius

- **Files changed**: ~18 (5 new source/data files, 4 new test files, 1 migration, ~8 edited).
  Recount after the C-16 descope: `ip_org_rir_ingest.py` is READ-ONLY, not edited;
  `visitor_aggregator.py` is READ-ONLY (R7).
- **Packages**: `apps/api` only. Zero frontend, zero pixel, zero identity-resolver-core files.
- **Risk classes present**: schema/migration (WS-C, additive nullable); prod data READ from scripts
  (WS-B); scheduled-job addition (WS-E). **Absent**: auth, billing, public API contract, destructive
  writes, secrets.
- **Highest-risk item**: WS-D's `_extract_domain`, because it sits on the live rDNS resolution path
  used by `company_resolver` today (unlike everything else in this pack, which is behind an OFF
  flag or in the ingest path) **and its change is THREE-directional, not additive** (Q11 / FAIL-1 /
  FAIL-3): some hosts that resolve to a domain today will resolve to `None` (NARROWS), some return a
  different value (CORRECTS), and — the highest-volume class — **every 3-label host under the eight
  old hardcoded TLDs goes from `None` to a live domain written through to `company_graph`,
  `visitors.company_domain` and `companies` (WIDENS)**. Mitigated by D4's three-question census +
  AC-D2/G14 (old rejections hold) + AC-D3/G21 (new rejections asserted) + AC-D4/G22 (new widening
  asserted). Historical `company_graph`, `visitors.company_domain` and `companies` rows written by
  the old logic are left as-is by design (R7), and the live read path keeps serving old-logic values
  for 30–75 days because the Redis `company_ip` and `company_graph`-staleness caches are NOT
  invalidated (Q15/KG-6).
- **Second-highest**: WS-C's `parse_as2org` signature change — a missed caller is a silent
  100 %-skip regression, exactly the defect class WS-A's guard now catches. The two are
  complementary: land WS-A before WS-C so the guard is in place when the parser changes.
- **Explicitly untouched**: `identity_resolver.py`, `enricher.py`, `roster_ranking.py`, anything
  under other programs' active task folders, and all agent/pixel surfaces.

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| G1 — skip-ratio unit matrix (0 %, 12.7 %, 30 % warn, 45 % abort, empty→abort) | Fully-Automated | AC-A2: a silent join collapse refuses the swap |
| G2 — abort path never calls `_load_staging_and_swap` (mock assertion) | Fully-Automated | AC-A2: old data is preserved on refusal |
| G3 — `EXPLAIN` on a post-swap lookup shows a GiST index scan with fresh stats; warm p95 re-measured | Hybrid (needs `localhost:5433` Postgres + a loaded corpus) | AC-A1: post-swap latency window closed |
| G4 — B1 SQL upper-bound count executed AND the post-stratum headline-eligible count AND the predicted-row count (stratum `org`) all recorded, plus the shrinkage between each pair; go/no-go taken against the **predicted-row count** (P1-4), not the headline count (C-14) | Hybrid (operator, prod read-only DSN + local stratum pass) | AC-B1: corpus feasibility is measured on the right population, not assumed |
| G5 — corpus TSV contains zero `@` characters and zero email local-parts; file is gitignored; **AND a static source check on `build_ip_org_benchmark.py` finds no bare `email` in any SELECT list** — e.g. `grep -nE 'SELECT[^;]*\biv?\.email\b|SELECT[^;]*(^|[ ,])email( |,|$)' scripts/build_ip_org_benchmark.py` returns nothing, and every email reference is `split_part(..., '@', 2)` (C-33 — catches the `iv.*`/bare-`email` wire leak the TSV grep cannot see) | Fully-Automated (grep + `git check-ignore`) | AC-B2: privacy constraint holds |
| G6 — extraction script's connection is server-side READ ONLY (a probe `INSERT` raises) | Hybrid (needs a real Postgres) | AC-B3: SELECT-only is structurally enforced |
| G7 — matcher unit matrix: exact, token-subset hit, token-subset near-miss rejected, short-token rejected | Fully-Automated | AC-B4: fuzzy matches are bounded and auditable |
| G8 — report exists; row count == corpus size; **≥80 non-None predictions per arm** (P1-4); stratum column holds **≥1 value in {`eyeball`,`datacenter`,`cdn`}** (C-20 — `none` alone is insufficient; proves the unfiltered stratum query ran AND that the datacenter/CDN exclusion is operative, FAIL-4); single-arm precision **with predicted-row denominator + separate coverage** (P1-3), `match_method` as a numerator decomposition, per-stratum with per-stratum predicted counts, **per-reachable-value confidence table over the 7 reachable values** (P1-1), **accuracy by `v2_classification`** over all FOUR reachable values (`registered_operator` / `likely_operational_customer` / `disputed_origin` / `unclassified`, C-34) (P2-9), coverage/None-rate and `v1==v2` invariant (with the `, id` tie-break precondition AND the duplicate-prefix probe stated, P2-8/C-28) sections all present; scored field named (`org_name` / `organization`, `domain` never scored — R2) | Hybrid (needs a loaded ip_org corpus) | AC-B5: measurement produced and non-vacuous (no threshold — AC4.12 precedent) |
| G9 — `parse_as2org` returns `(name, org_id)`; every caller and fixture updated (grep clean) | Fully-Automated | AC-C1: org_id retained end-to-end |
| G10 — org-family pass: sibling promoted to `eyeball`; `cdn` sibling NOT demoted to `org`; size-1 families unchanged. **Every fixture ASN drawn from the reserved `64512–65534` range (P2-10)** so WS-E's later APNIC set cannot flip a fixture and turn this gate red | Fully-Automated | AC-C2: conservative-direction-only guard holds |
| G11 — migration live down/up round-trip against `localhost:5433`; `as2org_org_id` present and nullable | Hybrid (needs disposable Postgres) | AC-C3: schema change is reversible |
| G12 — `multi_asn_families` / `family_reclassified` counters correct on a known fixture | Fully-Automated | AC-C4: sizing question answered with real numbers |
| G13 — PSL unit matrix incl. `foo.bar.gov.br` → `bar.gov.br`, **`x.co.za` → `x.co.za`**, **`x.co.uk` → `x.co.uk`** (FAIL-3 corrections), `co.uk` alone → `None`, wildcard, exception, unknown TLD, and the ICANN-only `amazonaws.com` proof (PSL layer only — R12) | Fully-Automated | AC-D1: multi-part TLDs resolve correctly |
| G14 — D4's THREE-question caller census recorded with grep output (pattern MUST include `resolve_company_cached` — R7); existing ISP/VPN/residential filter tests still green | Fully-Automated (tests) + Agent-Probe (census judgment) | AC-D2: the OLD rejections still hold and no consumer has a hard dependency |
| G21 — newly-REJECTED set matrix in `tests/unit/test_company_resolver.py` covering BOTH narrowing subclasses (P2-12): domain-filter-caught (`dsl-pool.host.talktalk.co.uk` → `None`, `c-1-2-3.hsd1.virgin.co.uk` → `None`) AND hostname-filter-only on a REAL corporate domain (`dhcp-1-2-3.acme.co.uk` → `None`, comment naming the lost `acme.co.uk`) + corrected cases (`foo.bar.gov.br` → `bar.gov.br`, **`x.co.za` → `x.co.za`**). The ICANN-section `amazonaws.com` proof lives in `test_public_suffix.py` (G13), NOT here — `test_company_resolver.py:71` already asserts `None` for that host and the two must not contradict (R12) | Fully-Automated | AC-D3: the narrowing half is intentional and gated |
| G22 — newly-WIDENED set matrix in `tests/unit/test_company_resolver.py` (`google.co.uk`, `bbc.co.uk`, `acme.com.au`, `x.co.uk` all go `None` → their own registrable domain) + D4 census question (c) answered | Fully-Automated + Agent-Probe | AC-D4: the highest-volume half of the change is asserted, not discovered in prod (FAIL-3) |
| G15 — APNIC parser tolerates both shapes, skips junk, fails open on missing/corrupt file | Fully-Automated | AC-E1: fetch job is fail-open |
| G16 — threshold boundary (49 999 out / 50 001 in); `mock_external_apis=True` makes no network call | Fully-Automated | AC-E2: threshold and mock-mode contract |
| G17 — `classify_ip_org_kind` direction guard: in-set ASN → `eyeball`; in-set + Cloudflare-shaped → `cdn`; out-of-set unchanged; **plus the discriminating AS-prefix case (P2-11): org with NO cdn/datacenter token + ASN ∈ `_CDN_RELAY_ASNS` → `cdn`**, which is the only case that fails if the `AS{asn} ` prefix is built wrong | Fully-Automated | AC-E3: APNIC can only move org→eyeball |
| G18 — observed APNIC response shape recorded verbatim in the phase report | Agent-Probe (one live fetch) | AC-E4: no invented field names (camelCase-defect prevention) |
| G19 — full unit lane green vs a baseline **measured by running the lane before the first edit**. Reference measurement for `.venv/bin/python -m pytest tests/unit -m unit -q`: **1605 passed / 2 skipped / 877 deselected** (the earlier "1324" was from a different command — CONCERN-8). `-m unit` deselects 877 of 2484 collected; the new ip_org tests ARE selected (31 collected, verified), so the lane is not vacuous | Fully-Automated | Program-wide: no collateral damage |
| G20 — integration lane green vs `localhost:5433` (note the conftest enum-teardown race) | Hybrid | Program-wide: DB-touching paths intact |

**Commands** (from `process/context/tests/all-tests.md`):

- unit: `.venv/bin/python -m pytest tests/unit -m unit -q`
- targeted unit: `.venv/bin/python -m pytest tests/unit/test_ip_org_ingest.py tests/unit/test_public_suffix.py tests/unit/test_apnic_eyeball_refresh.py tests/unit/test_company_resolver.py -q`
- integration: `docker compose -f infra/docker-compose.yml up -d postgres redis` then
  `DATABASE_URL=postgresql+asyncpg://…@localhost:5433/… .venv/bin/python -m pytest tests/integration/test_ip_org_pipeline.py -q`
- migration round-trip: `DATABASE_URL=<localhost:5433 DSN> .venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head` then `downgrade -1` then `upgrade head`

**Known-gaps (each carries a backlog stub; the owning gate stays CONDITIONAL until closed):**

- **KG-1 — PSL refresh cadence.** The vendored list goes stale. Backlog stub:
  `ip-org-psl-refresh-cadence_NOTE_08-08-26.md`. Gate G13 proves correctness against the vendored
  snapshot only, not against a current PSL.
- **KG-2 — APNIC methodology limits.** Population estimates are advertisement-sampled and noisy at
  the tail (IMC 2024). The 50 k threshold is a judgment, not a measured optimum. Backlog stub:
  `ip-org-apnic-threshold-tuning_NOTE_08-08-26.md`. Gate G16 proves the threshold is *applied*, not
  that it is *right*.
- **KG-3 — WS-B corpus is derived-label, not ground truth.** A corporate email domain is strong but
  not perfect evidence of the employer behind an IP (contractors, personal-domain founders, shared
  offices). **Extended (C-26):** the free-mail exclusion set is a judgment list, not an exhaustive
  one — it is `content_reader._GENERIC_DOMAINS` plus a benchmark addendum minus two real employers
  (`linkedin.com`, `x.com`). Any consumer-mail domain still leaking through carries a fabricated
  `expected_org` that can never match, biasing the headline number **downward**; any real employer
  wrongly excluded removes a valid row. The report must state that direction explicitly. Backlog
  stub: `ip-org-benchmark-label-quality_NOTE_08-08-26.md`. Gate G8 proves the measurement ran, not
  that its labels are perfect.
- **KG-5 — the RIR ingest leg has no skip-ratio guard.** Verified in A5/CONCERN-10:
  `refresh_rir_allocations` tracks no skipped count and has no offered-row denominator, so the
  silent-collapse guard covers the CAIDA leg only. Backlog stub:
  `ip-org-rir-skip-ratio-guard_NOTE_08-08-26.md`. Gates G1/G2 prove the CAIDA guard; nothing in this
  pack proves anything about the RIR leg.
- **KG-6 — WS-D's fix does not reach live reads for 30–75 days (R8).** The Redis `company_ip` cache
  (30d TTL) and `company_graph` staleness re-validation (75d default) keep serving old-logic values.
  Invalidation is out of scope. Backlog stub: `ip-org-domain-cache-invalidation_NOTE_08-08-26.md`.
  No gate in this pack proves anything about live-path behavior before those caches expire.
- **KG-7 — no pre-C/E coverage baseline exists (R6).** WS-C's family inheritance and WS-E's APNIC
  pre-check both NARROW the `org` bucket; WS-B runs last and therefore measures only the post-change
  world. The report records coverage %/`None`-rate as a forward baseline; the recall DELTA caused by
  C and E is unmeasured. Backlog stub: `ip-org-org-bucket-recall-delta_NOTE_08-08-26.md`.
- **KG-8 — corpus IP provenance is last-seen, not identification-time (R5), if the events-table
  derivation proves impractical.** Backlog stub: `ip-org-benchmark-ip-provenance_NOTE_08-08-26.md`.
  Only applies on the documented fallback path; the preferred events-table derivation closes it.
- **KG-9 — production lookup SQL has a non-total row order (P2-8).** `_LOOKUP_SQL`
  (`ip_org_lookup.py:52-56`) and `_V2_ROUTE_ORIGIN_SQL` (`:94-100`) both `ORDER BY masklen(prefix)
  DESC LIMIT 1` with no tie-break, and `prefix` carries no unique constraint while `parse_pfx2as`
  does not dedupe — so duplicate equal-length prefixes make the production row choice
  nondeterministic. This pack fixes it ONLY in the measurement script's own queries (`, id`); the
  live lookup path is untouched because it needs its own gate. Backlog stub:
  `ip-org-lookup-nondeterministic-tiebreak_NOTE_08-08-26.md`. No gate here proves anything about the
  production ordering.
- **KG-4 — prod ingest still not run.** Every Hybrid gate that needs a loaded corpus runs against
  the local dev DB, not prod. Tracked by the existing
  `../ip-org-database_07-08-26/ip-org-prod-enable_RUNBOOK_07-08-26.md`.

No developed behavior in this pack is left with Known-Gap as its ONLY proving strategy — every
acceptance criterion above has at least one Fully-Automated or Hybrid gate.

## Test Infra Improvement Notes

- The integration lane's conftest enum-teardown race (stale `platform` ENUM,
  `engagement_attributions` teardown) is pre-existing infra debt that makes
  `test_ip_org_pipeline.py` pass "by union" across attempts. Do not attribute a failure here to
  this pack without re-running against a fresh DB. Tracked in
  `../../backlog/ip-org-followups_NOTE_07-08-26.md` (cross-program flags).
- **CORRECTED (CONCERN-7): there are NO known pre-existing unit failures.** The earlier claim that
  `tests/unit/test_identity_resolver_parallel.py::TestBeamIdentityNetwork` carries 2 pre-existing
  failures is STALE — that class was renamed to `TestBeamNetworkIsAlwaysCandidate` by
  identity-vocab-reconcile, and the file measures **33 passed / 0 failed**. `all-context.md` also
  records `0 failed`. The execute-agent must therefore **baseline by RUNNING the lane before the
  first edit** and treat *any* failure as a real regression. Do not wave anything through.
- G3 (post-swap `EXPLAIN` + latency) is the first gate in this program that needs a *loaded* local
  corpus. If that setup proves painful, a seeded 10 k-row fixture loader would be a reusable
  addition — record the decision in the phase report.

## Sequencing and Dependencies

```
WS-A ──► WS-C          (A's skip guard must exist before C changes the parser)
WS-B (B1 gate) ──► WS-B rest
WS-D ──► WS-B          (B's build_ip_org_benchmark.py imports WS-D's public_suffix.registrable_domain — hard in-pack dependency, P1-2 / B3 / checklist 28)
WS-E ──► needs WS-A only for the shared summary/log conventions
```

Recommended order: **A → C → D → E → B**. WS-B goes last so its measurement runs against the
improved classifier (C, E) and the improved domain extraction (D) — measuring the pre-improvement
pipeline would produce a baseline nobody wants. If B1 says go, budget an extra half-day.

## Constraints

- No new Python dependencies.
- All new settings default-safe: thresholds set at observed-healthy values; `ip_org_apnic_refresh_enabled` OFF.
- structlog only (never `print`), type hints on every function, async for all I/O, explicit httpx timeouts.
- Migration chains off the LIVE head re-derived at EXECUTE time.
- **Every alembic/DB command must pin `DATABASE_URL` to `localhost:5433`** — the repo `.env` points
  at Supabase PROD and `migrations/env.py` has no guard (follow-ups item 3, still open).
- Do not touch identity-side files or other programs' active task folders.
- WS-B scripts read PROD: SELECT-only, explicit DSN required, operator-adjacent Hybrid gates.

## Out of Scope (named future work, one line each)

- **`company_graph` cleanup sweep for public-suffix-shaped domains** — rows written by the old
  `_extract_domain` (e.g. `domain='gov.br'`, `domain='co.za'`, ISP domains that bypassed the filters).
  WS-D fixes the producer, not the history; a sweep needs its own gates and a delete/retain decision.
- **`content_reader.py`'s THIRD hardcoded suffix set** — `_SECOND_LEVEL_TLDS` + `_domain_root`
  (`content_reader.py:616` — C-35, correcting BOTH the cycle-2 `:615` and the cycle-3 `:618`), below
  the `_GENERIC_DOMAINS` **`set`** (a plain `set`, not a `frozenset` — C-27b) that WS-B imports. It is a
  third independent copy of the same two-part-TLD idea that WS-D removes from `company_resolver`.
  Deliberately NOT refactored in this pack (different call path, different consumers, needs its own
  gates) — named here so a future reader knows it exists and was seen.
- **Historical `visitors.company_domain` / `companies` rows** written by the old `_extract_domain`
  logic via `resolve_company_cached` — untouched, same posture as `company_graph` history (R7).
- **Domain-cache invalidation** (Redis `company_ip` 30d TTL, `company_graph` 75d staleness) — KG-6.
- **RB2B eyeball IP-to-company source** — separate phase, see `../../backlog/rb2b-ip-to-company-eyeball-source_NOTE_07-08-26.md`.
- **PeeringDB org→domain seeder** — the split-out WS4 domain leg, gated on a yield measurement in the style of the **parent program's** G19 (C-27a: that G19 is `ip-org-database`'s domain-yield gate; THIS plan's own G19 is the full unit lane — the labels collide and must not be conflated).
- **IPv6 prefixes** — `parse_pfx2as` drops them today; a whole separate corpus and index decision.
- **Temporal history (`ip_org_prefix_history`)** — Phase 3 D2 kept `valid_to` for exactly this, additive later.
- **identity-coop contribution ledger** — blocked on graph-erasure reaching LIVE; unrelated to this pack.
- **alembic `env.py` local-host guard** — follow-ups item 3, P1 safety, deliberately not bundled here (it touches the Railway deploy boot path and deserves its own gates).
- **Load-transaction optimization (index-after-load / chunked COPY)** — follow-ups item 1, P2 perf; independent of quality.

## Phase Loop Progress

- [ ] Step 1 — RESEARCH: ✅ complete (findings supplied by orchestrator; SPEC + INNOVATE explicitly skipped — mechanical scope, options pre-compared)
- [ ] Step 2 — INNOVATE: n/a — skipped by orchestrator decision
- [ ] Step 3 — PLAN-SUPPLEMENT: this document (initial authoring, 08-08-26)
- [x] Step 4 — PVL: cycle 4 `Gate: CONDITIONAL`, user-accepted (A2, carrying E1–E21)
- [x] Step 5 — EXECUTE: ✅ WS-A/C/D/E CODE DONE (all Fully-Automated gates green; G3/G11/G20 Hybrid run local; G18 observed). WS-B CODE DONE, prod-read gates (B1/G4, B3 extraction, B5/G8) NEEDS-OPERATOR (prod PII read). Report: `ip-org-quality-pack_REPORT_08-08-26.md`. Deviations (all within blast radius): D5 `*.ck` cell vs D2 spec (D2 wins per FAIL-3); G12 counter fixture uses AS14061; WS-B prod read not auto-run; G3 scoped; events-IP per-row COALESCE.
- [ ] Step 6 — EVL: pending orchestrator (independent gate re-run)
- [ ] Step 7 — UPDATE PROCESS

## Resume and Execution Handoff

1. **Selected plan file**: `process/features/visitors-identity/active/ip-org-quality-pack_08-08-26/ip-org-quality-pack_PLAN_08-08-26.md`
2. **Last completed step**: PLAN written (08-08-26) → PVL cycle 1 (`Gate: BLOCKED`) → supplement cycle 1 → PVL cycle 2 (`Gate: BLOCKED`) → supplement cycle 2 (20 gaps) → PVL cycle 3 (`Gate: CONDITIONAL`, C-20…C-27) + adversarial round 2 (P1-1…P1-6, P2-7…P2-12) → **supplement cycle 3 applied — 18 unique gaps closed (see `## PVL Supplement Log` → Cycle 3)**. Historical detail below. Cycle 3 re-derived all 20 cycle-2 dispositions from source (not from the supplement log): both FAILs are CLOSED and all 6 cycle-2 CONCERNs are closed. 8 new/residual CONCERNs remain, 4 of them single-sentence mechanical corrections. No code written. No migration created.
3. **Validate-contract status**: WRITTEN, cycle 3, `Gate: CONDITIONAL` (supersedes cycle 2's contract in place). Zero FAILs. Open: C-20 (G8 non-vacuity clause satisfiable by `none`), C-21 (B3 sample size contradicts B1), C-22 (events-derived IP escapes B2's IP-validity filters), C-23 (Q14 cites the wrong column), C-24 (E4 candidate stems already present), C-25 (existing exclusion helper not reused), C-26 (mandated free-mail list unfit), C-27 (citation nits). EXECUTE is authorized only once an explicit acceptance of these CONCERNs — or a supplement cycle 3 closing them — is recorded in this file.
4. **Supporting context loaded**: `process/context/all-context.md`; `process/context/tests/all-tests.md`; `../ip-org-database_07-08-26/ip-org-phase-3-evidence-graph_PLAN_07-08-26.md`; `../../backlog/ip-org-followups_NOTE_07-08-26.md`; sources `ip_org_ingest.py`, `ip_org_rir_ingest.py`, `ip_org_fusion.py`, `ip_org_lookup.py`, `company_resolver.py`, `models/ip_org_prefix.py`, `models/visitor.py`, `services/agent_ip_range_refresh.py`, `jobs/scheduler.py`, `scripts/refresh_ip_org.py`.
5. **Next step for a fresh agent**: supplement cycle 3 is DONE (Option A of the acceptance menu was taken). All eight validator CONCERNs and all twelve adversarial findings are dispositioned in the plan body — see the Cycle 3 table in `## PVL Supplement Log`. The remaining action is an explicit acceptance line (user/orchestrator) or one confirming PVL pass, after which EXECUTE proceeds in the order **A → C → D → E → B** (WS-D before WS-B is now a hard in-pack dependency, P1-2). Historical instructions below. ~~choose from the acceptance menu in the `## Validate Contract` section — **Option A (supplement cycle 3, then accept)** is recommended: close C-20/C-21/C-22/C-23 as one-line plan edits and disposition C-24/C-25/C-26/C-27, then proceed to EXECUTE without a cycle-4 validate. Option B accepts now and carries E10–E14 as execute-agent instructions. Do NOT choose Option C.~~ A fourth adversarial leg (Option D) has low expected yield: cycle 1 → 2 FAILs, cycle 2 → 0 FAILs. Historical instructions retained below. ~~run **supplement cycle 2** — route to `vc-plan-agent` (PVL-supplement mode) with the SUPPLEMENT REQUEST block emitted alongside this contract, then re-spawn `vc-validate-agent` from V1. Because both cycle-2 FAILs were *created by* cycle 1's supplement, the orchestrator should also spawn one external adversarial verifier told to REFUTE the next contract, targeting the WS-D behavior table and the WS-B measurement mechanics. After a PASS/accepted-CONDITIONAL contract, EXECUTE in the order A → C → D → E → B, re-deriving the alembic head before writing WS-C's migration and pinning `DATABASE_URL` to `localhost:5433` for every DB command.~~

## Validate Contract

Status: CONDITIONAL
Date: 08-08-26
date: 2026-08-08
generated-by: inner-pvl: quality-pack
supersedes: 2026-08-08 (inner-pvl: quality-pack) — PVL cycle 3 (`Gate: CONDITIONAL`, 0 FAILs, 8 CONCERNs). Cycle 4 re-derived all 18 cycle-3 dispositions from source rather than from the supplement log. All 18 land. Zero FAILs. Seven new residual CONCERNs, every one carriable as a one-line execute-agent instruction.

Parallel strategy: sequential (forced)
Rationale: signal score 5/7 (S1, S2, S3, S6, S7) would normally recommend parallel-subagents or an agent team for the Layer-1 + Layer-2 fan-out. The Agent tool is NOT available to this agent, so all four Layer-1 dimensions and all six Layer-2 section checks ran SEQUENTIALLY in one pass (memory note `validate-agent-no-agent-tool-needs-external-fanout`). Cycles 2 and 3 each paired this validator with an external adversarial refuter; those legs produced 13 of 20 and 12 of 18 gaps respectively. The refuter yield curve is now 2 FAILs → 0 FAILs → 0 FAILs, and every cycle-3 finding was a *precision* defect inside already-correct reasoning. A fifth leg is not recommended.

### Cycle-3 disposition audit (re-derived from source, not from the supplement log)

| Cycle-3 gap | Log claim | Verified this cycle | Verdict |
|---|---|---|---|
| P1-1 (7-value calibration) | FIXED — 4 equal-width buckets withdrawn; per-reachable-value table | **Independently re-derived from `ip_org_fusion.py`, not read off the plan.** base `BASE_ROUTE_ORIGIN = 0.45` (`:41`); allocation term ∈ {`W_ALLOCATION_EXACT` +0.15 `:43`, `W_ALLOCATION_NEUTRAL` 0.00 `:46`, `W_ALLOCATION_SUBDELEGATED` −0.05 `:48`, `W_ALLOCATION_UNCOVERED` −0.05 `:50`, `W_NO_CORPUS` 0.00 `:52`} = 3 distinct values {+0.15, 0.00, −0.05}; RPKI term ∈ {+0.15, 0.00, −0.20} (`:53-55`); clamp `[0.05, 0.65]` (`:57-58`) applied at `:242`. The 3×3 Cartesian product yields exactly **{0.20, 0.25, 0.40, 0.45, 0.55, 0.60, 0.65}** — 7 values, matching the plan character for character. Minimum 0.20 > floor 0.05, so the floor IS dead code and `[0.05,0.2)` IS provably empty, as claimed. `round(confidence, 4)` at `:256` makes each value exact in float, so a report keyed on equality is safe. Confirmed there is no second confidence path: `lookup_ip_org_v2` returns `fuse_org_hypothesis(...)` verbatim (`ip_org_lookup.py:186`) with no fallback | **FIXED — re-derived independently** |
| P1-2 (`label_root` helper) | FIXED — 3-line helper on WS-D's PSL; worked example consistent; in-pack B→D dependency declared | **Traced end to end.** `deloitte.co.uk` → `registrable_domain` (D2 spec: suffix + exactly one label) → `deloitte.co.uk` → `.split(".", 1)[1]` → `co.uk` → `reg[: -(5+1)]` → `deloitte` → `normalize_org_name("deloitte")` → `deloitte`. `acme.com` → `acme.com` → `com` → `acme` → `acme`. The helper is arithmetically correct because a registrable domain is by construction `suffix + one label`, so the leftmost label is always the root. `normalize_org_name` verified at `ip_org_ingest.py:91-107`: `_PUNCT_RE` maps `.` to space, so the plan's claim that `normalize_org_name("acme.com")` → `"acme com"` (i.e. the naive one-call version is broken) is correct, and `"deloitte"` is not a `_LEGAL_SUFFIX_SET` member so it survives. `None` on a bare suffix correctly excludes the row. **Residual: the dependency is declared in B3 but the `## Sequencing and Dependencies` diagram still says "WS-D independent" — see C-29** | **FIXED, one stale diagram — C-29** |
| P1-3 (precision/coverage/match_method) | FIXED — precision denominator = predicted rows; coverage separate; match_method demoted to numerator decomposition | Internally consistent across Q14(a), B4, AC-B5, G8 and checklist 30 — all five state the same denominator. The "precision per `match_method` is ill-posed" argument is correct (its denominator would be its own numerator). **Residual nit: `None`-rate is defined over "corpus IPs" while coverage is defined over "headline rows", so they are not complements; the report must print both denominators — folded into C-35** | **FIXED** |
| P1-4 (floor on predicted rows) | FIXED — three population numbers; floor moves to predicted count; G8 ≥80 not ≥1 | Wired consistently in B1 (three-row table), B5, AC-B1, AC-B5, G4, G8 and checklist 26/31. The arithmetic in B1's justification checks out (200 headline × 40 % = ~80). **Two residuals: `Q3` — a Locked Decision — still states the single B1 floor and still justifies it by the WITHDRAWN v1-vs-v2 comparison (C-32); and the ~300 extraction target lands the expected predicted count exactly ON the floor with zero headroom (C-31)** | **FIXED, two residuals — C-31, C-32** |
| P1-5 (cast-safe IP validity, B2b) | FIXED — octet-strict regex + `WITH … AS MATERIALIZED` barrier; bare `AND`-chain forbidden | Both mechanisms are sound. Postgres genuinely does not short-circuit `AND`, `AS MATERIALIZED` genuinely fences the CTE (PG12+; this repo is PG16), and the octet-range regex genuinely makes every surviving value castable, so the two guards are correctly described as belt-and-braces rather than redundant. `NOT (ip_address::inet <<= ANY(ARRAY[…]::inet[]))` is valid inet syntax. **Residual: the CTE's `SELECT iv.*` selects `identified_visitors.email`, which directly contradicts B3's "Never SELECTs `email`" and Q4's "local-parts never leave the database" — see C-33** | **FIXED, privacy contradiction in its own SQL — C-33** |
| P1-6 + C-22 (events IP: lower bound + validity) | FIXED — `created_at > '2026-07-26 09:13:43'`, `ip_address <> ''`, strict regex, private-range | The CF-edge reopening is real and the lower bound closes it; `events.ip_address` is `Column(String(45), default="")` (`models/event.py:37`) so the `<> ''` guard is necessary, and `created_at` at `:70` confirms the ordering column. The naive-UTC literal matches `resolved_at`'s `DateTime` with no `timezone=True` (`models/visitor.py:229`). Composition with B2b is derivable (correlated subquery inside the CTE, private-range filter outside) though not spelled out. **Nit: the IPv4-only strict regex silently drops IPv6-only visitors — correct behavior, since `parse_pfx2as` drops IPv6, but it is an unstated selection effect (C-35)** | **FIXED** |
| P2-7 == C-23 (Q14 column citation) | FIXED — `:162` is `org_kind`, `:163` is `relationship_type` | Verified exactly: `_allocation_to_row` (`ip_org_rir_ingest.py:147-166`) has `"org_kind": "registry"` on `:162` and `"relationship_type": "registered_holder"` on `:163`. The corrected citation now supports the stated claim, and the conclusion (RIR rows excluded by `org_kind='org'`, not by any relationship_type predicate) is independently correct | **FIXED** |
| P2-8 (deterministic tie-break + KG-9) | FIXED — `, id` in the pack's own scripts; production recorded as KG-9 | The underlying defect is real: `_LOOKUP_SQL` (`ip_org_lookup.py:52-56`) and `_V2_ROUTE_ORIGIN_SQL` (`:94-100`) both `ORDER BY masklen(prefix) DESC LIMIT 1` with no tie-break, `prefix` carries no unique constraint (`models/ip_org_prefix.py`), and `parse_pfx2as` does not dedupe. KG-9 is correctly scoped and its backlog stub is in checklist 33. **But the mitigation does not cover the failure mode it names: the `v1_pred == v2_pred` invariant runs through the PRODUCTION queries, which this pack explicitly leaves untouched, so adding `, id` to the script's own stratum query cannot make that invariant deterministic — see C-28** | **PARTIAL — mitigation misses the named failure — C-28** |
| P2-9 (accuracy by `v2_classification`) | FIXED — new report section (b2) with row counts | The field is genuinely collected-and-unconsumed and the breakdown is genuinely free. **But the enumerated value set is incomplete: `Classification` (`ip_org_fusion.py:64-69`) has FOUR members and `derive_classification` (`:289-297`) is a total function whose fallback row 5 returns `unclassified` for every prefix the RIR corpus does not cover. The plan lists only three values in all four places it enumerates them — see C-34** | **FIXED, incomplete value set — C-34** |
| P2-10 (reserved fixture ASNs + `cache_clear`) | FIXED — C6 fixtures from `64512–65534`; new E6a mandates `cache_clear()` | Both halves correct. `64512–65534` is the RFC 6996 16-bit private-use range; reserved ASNs announce no routes and cannot appear in an APNIC per-AS population list, so the C6/G10 composition hazard is genuinely closed. Verified those ASNs are absent from `_CDN_RELAY_ASNS` and `_DATACENTER_ASNS`, so a reserved-range fixture still exercises the token path as intended. E6a's `lru_cache` hazard is real for both new loaders (D2 and E1 both specify `@lru_cache(maxsize=1)`) | **FIXED** |
| P2-11 (discriminating AS-prefix case, E6b) | FIXED — org with no cdn token + ASN ∈ `_CDN_RELAY_ASNS` → `cdn` | Verified from source: `classify_org_kind` (`company_resolver.py:344-356`) returns `cdn` on `asn in _CDN_RELAY_ASNS` **or** an org-token match, and `_parse_asn` (`:334-339`) reads the ASN out of the `AS<num>` prefix that `classify_ip_org_kind` constructs at `ip_org_ingest.py:120`. So a Cloudflare-shaped org fixture really does classify `cdn` via the token regardless of the prefix, and the new no-token + in-set-ASN case really is the only one that fails when the prefix is mis-built. Also checked the reverse composition: if AS13335 were ever present in `eyeball_asns.json`, E3's pre-check still returns `cdn` (its `if kind in ("datacenter","cdn"): return kind` arm fires first), so E6b does not become flaky when WS-E lands | **FIXED — and composition-safe** |
| P2-12 (hostname-filter NARROWS subclass) | FIXED — subclass (ii) added to the D3 table, G21 case, D4(a) census | **Re-derived by hand-executing `_extract_domain` (`company_resolver.py:85-122`) rather than reading the plan.** `dhcp-1-2-3.acme.co.uk` → `parts` has 4 labels → `tld_candidate = "co.uk"` ∈ `two_part_tlds` → `len(parts) >= 4` → returns `acme.co.uk` TODAY via the early `return` at `:109`, bypassing both filters. After D3: `registrable_domain` → `acme.co.uk`; `_build_domain_filter_regex` at `:115` does NOT fire (`acme` is absent from `_DOMAIN_PATTERNS`, `:42-63`); `_build_hostname_filter_regex` at `:119` DOES fire on `dhcp` (`_HOSTNAME_PATTERNS`, `:65-70`, contains `dhcp`, `pool`, `dsl`) → `None`. The subclass row is exactly right, and the claim that it is the more consequential half (a real corporate domain lost, versus subclass (i)'s consumer ISP) holds. All seven D3 rows were re-derived the same way and every cell is correct | **FIXED — re-derived independently** |
| C-20 (G8 stratum non-vacuity) | FIXED — tightened to ≥1 value in {`eyeball`,`datacenter`,`cdn`} | Applied consistently in B5, AC-B5 and G8; the weaker "outside {`org`,`pending`}" wording is gone everywhere. Achievability rationale (eyeball ≈ 26.9 % of the loaded corpus) is sound and if anything conservative for a visitor-IP sample | **FIXED** |
| C-21 (B3 sample size) | FIXED — B3 now says ~300 extracted, ~200 labelled the headline target | Grep-confirmed: the only remaining "~200" occurrences are the explicitly-labelled HEADLINE target (B1 `:389`, B3 `:570`), the worked example (`:395`) and the `N≈200` calibration note. No stale extraction target survives. **Residual: the number itself gives no headroom — C-31** | **FIXED, number is tight — C-31** |
| C-24 (E4 candidate stems) | FIXED — illustrative list withdrawn entirely; grep is the specification | Verified live: `_EYEBALL_ORG_TOKENS` has `telkom` on `ip_org_ingest.py:81` and `wireless` on `:82`, exactly as the disposition claims. Deleting the list rather than correcting it is the right call — a corrected list goes stale the same way, and the substring-match note (`in` semantics) is the part that actually makes the grep instruction usable | **FIXED** |
| C-25 (canonical exclusion helper) | FIXED — both columns confirmed to exist; `human_only_visitor_filter()` mandated | Column half verified: `visitors.is_agent_operated` (`models/visitor.py:117`) and `visitors.is_internal_suspect` (`:132`) both exist on `Visitor`; the hedge is correctly resolved to fact. `human_only_visitor_filter` exists at `agent_visitor_filters.py:19`. **But the helper is a SQLAlchemy Core/ORM predicate builder (it calls `aliased(Visitor)` and builds a correlated `EXISTS`), and B3 mandates a raw `asyncpg.connect(...)` connection with hand-written SQL — the two cannot compose as written. See C-30** | **FIXED, mechanism incompatible — C-30** |
| C-26 (free-mail set unfit) | FIXED — `FREE_MAIL_EXCLUDE = (_GENERIC_DOMAINS ∪ addendum) − {linkedin.com, x.com}` | Verified the base set: `content_reader._GENERIC_DOMAINS` (`:607`) is a plain `set` of 14 entries and does contain `linkedin.com` and `x.com` and does NOT contain any of the 12 addendum domains. The judgment call (extend rather than only document) is defensible and the bias direction is stated honestly in KG-3 | **FIXED** |
| C-27 (citation nits) | FIXED — parent-program G19 qualified; `_SECOND_LEVEL_TLDS` line; `set` not `frozenset` | (a) and the `set`/`frozenset` half are correct. **(b) is still wrong: `_SECOND_LEVEL_TLDS` is at `content_reader.py:616`, not `:618`. Cycle 2 said `:615`, cycle 3 "corrected" it to `:618`; the real line is `:616`. Folded into C-35** | **FIXED, correction is still off — C-35** |

Score: **18 of 18 cycle-3 dispositions land.** Zero FAILs. The two flagship reframes (P1-1's reachable-value set and P2-12's hostname-filter subclass) were re-derived independently from source and both are correct to the character. Seven residual CONCERNs, none of which changes a design decision: three are one-line plan-text edits (C-29, C-32, C-34), two are one-line execute-agent instructions (C-30, C-33), one is a number to pick (C-31), one is a report-wording precondition (C-28), plus a cosmetic bundle (C-35).

### Numbering integrity (checked mechanically this cycle)

| Set | Defined | Referenced | Dangling |
|---|---|---|---|
| AC ids | 20 (AC-A1…AC-Z1) | 20 | none |
| Gates | 22 (G1…G22) | 22 | none |
| Known-gaps | **9** (KG-1…KG-9, incl. new KG-9) | 9 | none |
| Locked decisions | 15 (Q1…Q15) | 15 | none |
| New cycle-3 sub-labels | B2b, E6a, E6b, Q14(a)/(b)/(b2)/(c) — all defined and all referenced from ≥1 checklist item or gate | — | none |
| Adversarial refs | R1…R13, P1-1…P1-6, P2-7…P2-12 all resolve to a supplement-log row | — | none |

AC ↔ gate mapping is bidirectional and complete. **Two counts in the previous contract are now stale and are corrected here: known-gaps is 9, not 8 (KG-9 was added by P2-8), and the previous contract's `Known Gaps` line enumerated only KG-1…KG-8.**

### Test gates (C3 5-column)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-A1 | post-swap planner stats fresh before next lookup | Hybrid | G3 — `refresh_ip_org --apply` against `localhost:5433`, then `EXPLAIN (ANALYZE)` a `prefix >>= inet` lookup from a NEW connection; assert GiST index scan and warm p95 < 15 ms. Insert point re-verified this cycle: `await db.commit()` at `ip_org_ingest.py:437`, fusion-cache invalidation immediately after | B |
| AC-A2 | skip-ratio warn/abort; abort never swaps | Fully-Automated | G1+G2 — `.venv/bin/python -m pytest tests/unit/test_ip_org_ingest.py -q`; 5-case ratio matrix + `_load_staging_and_swap` mock never called. Control-flow re-verified: `if dry_run` `:527`, `if not rows` `:530`, `_try_acquire_lock` `:536`, so the abort lands before the advisory lock as A4 claims | B |
| AC-B1 | corpus population measured at three points; floor on the predicted count | Hybrid | G4 — operator SELECT count against a read-only prod DSN, then the post-stratum headline count, then the predicted count. **Extraction target gives zero headroom over the floor — see C-31** | B |
| AC-B2 | corpus artifact holds no email local-parts, is gitignored | Fully-Automated | G5 — `grep -c '@' benchmark-corpus.tsv` == 0 AND `git check-ignore -v <path>` exits 0. **B2b's own illustrative SQL contradicts this (C-33); the gate itself is sound** | B |
| AC-B3 | extraction script is server-side READ ONLY, refuses implicit DSN | Hybrid | G6 — probe `INSERT` raises `ReadOnlySQLTransactionError`; no-DSN run exits non-zero | B |
| AC-B4 | matcher fuzzy tier bounded, every result carries match_method | Fully-Automated | G7 — matcher unit matrix (exact, token-subset hit, near-miss rejected, <4-char token rejected) | B |
| AC-B5 | measurement produced and NON-VACUOUS | Hybrid | G8 — flag-vacuity half closed (Q12; `config.py:1187` re-verified to carry neither `validate_assignment` nor `frozen`, so the singleton is mutable). Stratum half tightened to {`eyeball`,`datacenter`,`cdn`}. Predicted-row floor ≥80 per arm. **The `v1==v2` invariant's determinism precondition is not attainable as specified (C-28) and the (b2) classification enumeration is missing `unclassified` (C-34)** | B |
| AC-C1 | `organizationId` survives parse → row builder → column | Fully-Automated | G9 — `pytest tests/unit/test_ip_org_ingest.py -q` + `grep -rn "parse_as2org"`. Sole production consumer re-confirmed: `org_raw = asn_orgs.get(asn)` in the `refresh_ip_org_dataset` row loop | B |
| AC-C2 | family classification only moves org → non-org | Fully-Automated | G10 — family matrix incl. cdn-sibling-not-demoted, the R9 lateral case, size-1 families, all fixtures from `64512–65534` | B |
| AC-C3 | `as2org_org_id` migration applies and reverses | Hybrid | G11 — `DATABASE_URL=<localhost:5433> .venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head && downgrade -1 && upgrade head` | B |
| AC-C4 | multi-ASN family counters correct | Fully-Automated | G12 — fixture with a known family layout | B |
| AC-D1 | registrable domain correct for multi-part public suffixes | Fully-Automated | G13 — `pytest tests/unit/test_public_suffix.py -q`. Expected values re-derived correct again this cycle | B |
| AC-D2 | no consumer breaks on the `_extract_domain` change | Fully-Automated + Agent-Probe | G14 — D4's THREE-question census incl. the mandatory `resolve_company_cached` token + existing filter tests green | B |
| AC-D3 | newly-REJECTED set is gated, BOTH subclasses | Fully-Automated | G21 — `dsl-pool.host.talktalk.co.uk` → `None`, `c-1-2-3.hsd1.virgin.co.uk` → `None` (domain-filter subclass), `dhcp-1-2-3.acme.co.uk` → `None` (hostname-filter-only subclass, P2-12 — re-derived correct this cycle), plus `foo.bar.gov.br` → `bar.gov.br` and `x.co.za` → `x.co.za` | B |
| AC-D4 | newly-WIDENED set is gated | Fully-Automated + Agent-Probe | G22 — `google.co.uk`, `bbc.co.uk`, `acme.com.au`, `x.co.uk` all go `None` → their own registrable domain. Re-derived correct: all four hit the bare `return None` at `company_resolver.py:110` today | B |
| AC-E1 | APNIC refresh fail-open, junk records skipped | Fully-Automated | G15 — `pytest tests/unit/test_apnic_eyeball_refresh.py -q`, with `cache_clear()` in setup (E6a) | B |
| AC-E2 | user-count threshold applied; mock mode makes no network call | Fully-Automated | G16 — boundary 49 999 / 50 001 + `mock_external_apis=True` transport assertion | B |
| AC-E3 | APNIC set can only produce `eyeball` | Fully-Automated | G17 — direction-guard matrix + the E6b discriminating AS-prefix case (verified this cycle to be the only case in the matrix that can fail on a mis-built prefix) | B |
| AC-E4 | live APNIC response shape observed before any field name is committed | Agent-Probe | G18 — one live fetch, shape recorded verbatim | B |
| AC-Z1 | no unit/integration regression | Fully-Automated + Hybrid | G19 — `.venv/bin/python -m pytest tests/unit -m unit -q` (baseline 1605 passed / 2 skipped / 877 deselected, RUN again before first edit). G20 — `docker compose -f infra/docker-compose.yml up -d postgres redis` then `.venv/bin/python -m pytest tests/integration/test_ip_org_pipeline.py -q` | B |

gap-resolution legend: A — proven now; B — gate added/fixed by this plan's checklist; C — deferred to a named later phase; D — backlog test-building stub (named residual).

Legacy line form:
- ip_org_ingest (WS-A/WS-C/WS-E): Fully-automated: `.venv/bin/python -m pytest tests/unit/test_ip_org_ingest.py -q`
- public_suffix (WS-D): Fully-automated: `.venv/bin/python -m pytest tests/unit/test_public_suffix.py tests/unit/test_company_resolver.py -q`
- apnic (WS-E): Fully-automated: `.venv/bin/python -m pytest tests/unit/test_apnic_eyeball_refresh.py -q`
- migration (WS-C): hybrid: alembic up/down/up + precondition `DATABASE_URL` pinned to `localhost:5433`
- post-swap ANALYZE (WS-A): hybrid: `EXPLAIN` after a real `--apply` swap + precondition loaded local corpus
- precision measurement (WS-B): hybrid: unfiltered stratum query + both lookup arms against a loaded local corpus
- APNIC live shape (WS-E): agent-probe: one live fetch, shape recorded verbatim

**Environment note:** unchanged. Structural validator run this cycle: `validate-plan-artifact.mjs` → **0 failures, 0 warnings, 1622 lines**. Docker was NOT re-probed this cycle (no gate here depends on it); the cycle-3 finding that `5433`/`6379` are LISTEN stands, and no gate may be recorded as environment-blocked.

**Fan-out disclosure:** no Agent tool available; all Layer-1 and Layer-2 checks were performed sequentially by this single agent. No database was queried and no git command was run this cycle — every claim above comes from reading source files. Files re-read this cycle: `ip_org_fusion.py` (in full), `ip_org_lookup.py` (in full), `ip_org_ingest.py` (`:60-130`, `:385-442`, `:470-545`), `company_resolver.py` (`:40-130`, `:315-365`), `ip_org_rir_ingest.py` (`:147-168`), `models/ip_org_prefix.py`, `models/event.py`, `models/visitor.py`, `agent_visitor_filters.py`, `content_reader.py` (`:605-622`), `config.py` (model_config). The 7-value confidence set and the 7-row WS-D behavior table were both re-derived by hand rather than checked against the plan's own reasoning. Nothing here proves the absence of a defect an independent adversarial refuter would find — but three legs have now produced 2 → 0 → 0 FAILs and every finding this cycle is a precision defect, so a fifth leg has low expected yield.

Dimension findings:
- Infra fit: PASS — every line anchor cited by the cycle-3 edits was re-verified exact: `ip_org_fusion.py` `:41`/`:43`/`:46`/`:48`/`:50`/`:52-55`/`:57-58`/`:64-69`/`:165`/`:242`/`:256`/`:289-297`; `ip_org_lookup.py` `:52-56`/`:66`/`:94-100`/`:102-108`/`:153`/`:186`; `ip_org_ingest.py` `:81`/`:82`/`:91-107`/`:110-125`/`:388-395`/`:399-402`/`:437`; `ip_org_rir_ingest.py` `:162`/`:163`; `company_resolver.py` `:42-63`/`:65-70`/`:109-110`/`:115`/`:119`/`:323`/`:334-339`/`:344-356`; `models/event.py` `:37`/`:70`; `models/visitor.py` `:117`/`:132`/`:229`; `agent_visitor_filters.py:19`; `config.py:1187`; `content_reader.py:607`. Two anchors are off by a line or two and are cosmetic (C-35). No infra defect.
- Test coverage: CONCERN — every AC has ≥1 Fully-Automated or Hybrid gate and no behavior rests on Known-Gap alone. Two gates are narrower than their stated intent: G8's `v1==v2` invariant carries a determinism precondition that cannot be satisfied by the fix this pack ships (C-28), and G8's (b2) classification breakdown enumerates 3 of the 4 reachable values (C-34).
- Breaking changes: PASS — the `_extract_domain` three-class enumeration was re-derived cell by cell and is exhaustive: a host with ≥4 labels under one of the eight hardcoded suffixes that trips no filter is genuinely unchanged, and no fourth class exists. `parse_as2org`'s breaking signature change is correctly scoped to one production consumer plus fixtures. The `classify_ip_org_kind` narrowing is correctly characterized, and the new E3 pre-check cannot widen the `org` bucket.
- Security surface: CONCERN — the READ-ONLY session, the explicit-DSN requirement, the two-DSN split, and the streamed max-bytes cap are all sound, and the in-process flag assignment is correctly confined to a local measurement process. But the plan states a hard privacy invariant ("email local-parts never leave the database … literally true rather than aspirational") and B2b's own illustrative SQL breaks it with `SELECT iv.*` (C-33). No new secrets, no auth surface, no destructive write; no other security defect.
- WS-A feasibility: PASS — clean for three cycles. Every ordering claim re-verified against real control flow.
- WS-B feasibility: CONCERN — the Q14 reframe survives a third independent re-derivation and P1-1/P1-3/P1-4 are all correct. Residuals C-28 (invariant precondition unattainable), C-30 (helper/driver mismatch), C-31 (no headroom over the floor), C-32 (stale Locked Decision), C-33 (privacy contradiction in the CTE), C-34 (missing `unclassified`). All six are WS-B; none touches a design decision.
- WS-C feasibility: PASS — clean for three cycles. C4a's chunk-dict placement instruction re-verified mechanically exact against `:399-402`.
- WS-D feasibility: PASS — the three-class table survives a second hand re-derivation, both narrowing subclasses are correct, R12's two-layer split resolves the test contradiction. Residual C-29 is a stale dependency diagram, not a WS-D defect.
- WS-E feasibility: PASS — C-24's deletion of the candidate list is the right call, E6a's `cache_clear()` requirement is real, and E6b's discriminating case was verified to be the only fixture with the property it claims. WS-E moves from CONCERN to PASS this cycle.

Open gaps:

- **C-28 — WS-B / P2-8: the tie-break fix does not cover the failure mode it names.** P2-8's stated hazard is that a duplicate equal-masklen prefix makes the Q14(c) `v1_pred == v2_pred` invariant report a FALSE bug. But that invariant compares the outputs of `_LOOKUP_SQL` and `_V2_ROUTE_ORIGIN_SQL` — PRODUCTION queries this pack explicitly does not change (KG-9). Adding `, id` to the measurement script's OWN stratum query makes the STRATUM deterministic; it cannot make the invariant deterministic. So the stated precondition ("the invariant assertion is only meaningful under a deterministic row choice") is asserted but not attained. Fix (one clause, no design change): before reporting any divergence as a bug, the script runs a duplicate probe — `SELECT prefix, masklen(prefix), count(*) FROM ip_org_prefixes WHERE relationship_type='route_origin' AND org_kind='org' GROUP BY 1,2 HAVING count(*) > 1` — and reports the count; a zero count is what makes the invariant meaningful, and a non-zero count downgrades every divergence to "possible data property, see KG-9".
- **C-29 — WS-B/WS-D: the in-pack dependency is declared in one place and denied in another.** B3 states "**This is an IN-PACK dependency: WS-B depends on WS-D's `public_suffix.py`** … do not reorder B ahead of D" and checklist 28 repeats it. The `## Sequencing and Dependencies` block — the section whose entire job is recording dependencies — still reads `WS-D  independent` and has no `WS-D ──► WS-B` edge. An agent that reads only that block sees WS-D as free-floating and WS-B as gated only by B1. The execution order A → C → D → E → B happens to satisfy it, so nothing breaks today; the risk is a future reorder. Fix: add the edge, drop the word "independent".
- **C-30 — WS-B / C-25: the mandated helper cannot be called from the mandated driver.** B3 specifies a raw `asyncpg.connect(...)` connection with `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` and hand-written SQL (the B2b CTE is written as a SQL string), and explicitly forbids reusing `async_session`. B2 and checklist 28 then require importing `human_only_visitor_filter()` — which is a SQLAlchemy predicate builder: it calls `aliased(Visitor)` and constructs a correlated `EXISTS` over the ORM entity (`agent_visitor_filters.py:19` onward). A SQLAlchemy Core expression object cannot be interpolated into an asyncpg SQL string, and even compiled it would emit `visitors.…` rather than the `v` alias the CTE uses. The plan states no bridge. Fix (pick one and say which): (a) build the whole extraction query with SQLAlchemy Core over an asyncpg-backed engine so the predicate composes natively; (b) compile the predicate once — `str(select(Visitor).where(human_only_visitor_filter()).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))` — and lift the `WHERE` fragment, aliasing carefully; or (c) hand-inline `is_agent_derived = false AND is_agent_operated = false AND is_internal_suspect = false` plus the phantom-contact EXISTS, and record in the phase report that the canonical helper was deliberately NOT reused and why. (c) is the cheapest and is defensible given `source_agent_visit_id IS NULL` already covers the agent-derived class from the IdentifiedVisitor side.
- **C-31 — WS-B / P1-4: the extraction target lands exactly ON the floor, with zero headroom.** The plan's own worked example is "a headline set of 200 rows that is 60 % eyeball/none yields ~80 scored rows", and the extraction target is ~300 for a ~200-row headline set. So the EXPECTED predicted count is ~80 and the descope floor is `< 80` — a coin flip, after a prod read that P1-4/C-14 exist specifically to avoid wasting. And the 60 % assumption is probably optimistic: the org-kind mix quoted for the loaded corpus (org 63.8 % / eyeball 26.9 %) is a PREFIX-population share, whereas visitor IPs skew heavily toward consumer ISPs, so the eyeball share of a real visitor sample should be materially higher than 26.9 %. The IPv4-only regex (correct, since `parse_pfx2as` drops IPv6) removes another slice that is never counted. Fix (pick a number, or make it adaptive): either raise the extraction target to ~500–600, or — better — make the floor recoverable: if the predicted count lands under 80, re-run the extraction with a larger `LIMIT` before descoping, rather than descoping on the first pass. State whichever is chosen in B1, B3 and checklist 26.
- **C-32 — WS-B / Q3: a Locked Decision still carries the pre-P1-4 floor and a withdrawn rationale.** Q3 reads "Step B1 is a pure count query. `< 80` usable rows → WS-B is descoped … the corpus is not worth building against a sample too small to distinguish v1 from v2." Both halves are superseded: P1-4 moved the operative floor off B1's count onto the predicted-row count, and Q14/R1 abandoned the v1-vs-v2 comparison as degenerate by construction. Locked Decisions is the section the plan tells EXECUTE not to re-litigate, so a stale decision there outranks the corrected body text in an execute-agent's reading order. Fix: two sentences in Q3 pointing at B1's three-number table and replacing the v1-vs-v2 rationale with "too small to produce a usable single-arm precision number".
- **C-33 — WS-B / B2b: the plan's own SQL selects the column the plan promises never to select.** B2b's CTE is written `SELECT iv.*, v.ip_address FROM identified_visitors iv JOIN visitors v …` and the outer query is `SELECT * FROM candidates`. `iv.*` includes `identified_visitors.email`. That directly contradicts B3 ("**Never SELECTs `email`.** … so the local-part is never transmitted over the wire and never exists in process memory") and Q4's stated posture, and it is the one place in the plan an execute-agent will copy SQL from verbatim. G5 would still pass (it greps the written TSV, not the wire), so the gate cannot catch it — which is exactly why it needs fixing in text. Fix: replace `iv.*` with the explicit projection — `iv.site_id, iv.visitor_id, iv.resolved_at, split_part(iv.email, '@', 2) AS email_domain` — and show where B2's `DISTINCT ON (ip_address) … ORDER BY ip_address, resolved_at DESC` attaches (outer query, after the private-range filter).
- **C-34 — WS-B / P2-9: the classification breakdown enumerates 3 of 4 reachable values.** `Classification` (`ip_org_fusion.py:64-69`) is a 4-member Literal and `derive_classification` (`:289-297`) is documented as a total function whose fallback row returns **`unclassified`** whenever the RIR corpus is absent OR present-but-not-covering. The plan lists only `registered_operator` / `likely_operational_customer` / `disputed_origin` in all four places it enumerates the values (Q14(b2), B4, AC-B5, G8). `unclassified` is not an edge case: the local corpus has 262,238 RIR allocations against 967 k+ route rows, so uncovered prefixes — and therefore `unclassified` hypotheses — should be common. A breakdown that omits it either drops rows silently or crashes on an unexpected key. Fix: add `unclassified` to all four enumerations.
- **C-35 — citation and wording nits (cosmetic, no behavioral consequence).** (a) `content_reader._SECOND_LEVEL_TLDS` is at `:616` — cycle 2 said `:615`, cycle 3 "corrected" it to `:618`, and both are wrong; `_GENERIC_DOMAINS` at `:607` and the plain-`set` observation are correct. (b) `is_agent_derived` is at `models/visitor.py:75`, not `:74`. (c) Q14(b) calls `0.20` and `0.25` "the two `rpki=invalid`-derived values" — `0.40` is also reachable via `rpki=invalid`; the precise statement is "the two values reachable ONLY via `rpki=invalid`". (d) `None`-rate is defined over corpus IPs while coverage is defined over headline rows, so they are not complements — the report should print both denominators next to each other. (e) KG-9 names `_LOOKUP_SQL` and `_V2_ROUTE_ORIGIN_SQL` but not `_V2_REGISTERED_HOLDER_SQL` (`ip_org_lookup.py:102-108`), which carries the same non-total `ORDER BY`; verified inconsequential (fusion reads only `prefix` from holder rows, via `_most_specific_covering`, so an equal-masklen tie cannot change the score) — worth one clause so a future reader does not re-derive it. (f) The IPv4-only strict regex silently excludes IPv6-only visitors; correct behavior, but state it in the report limitations. (g) The plan's `**Status**` header (line 11) and the `## Autonomous Goal Block` both still say "awaiting … supplement cycle 3", which has since been applied — stale, and the goal block is what a resumed session reads first.

Known Gaps (pre-classified, excluded from the CONCERN/FAIL count): KG-1 PSL refresh cadence, KG-2 APNIC threshold tuning, KG-3 derived-label quality, KG-4 prod ingest not run, KG-5 RIR leg has no skip-ratio guard, KG-6 domain-cache 30–75 day lag, KG-7 no pre-C/E coverage baseline, KG-8 corpus IP provenance fallback, **KG-9 production lookup non-total row order**. All nine carry backlog stubs in the plan (checklist 33; KG-4 is tracked by the parent program's runbook) and are correctly scoped.

What this coverage does NOT prove:
- G1/G2 prove the skip-ratio arithmetic and the abort branch in isolation; they do NOT prove the guard fires on a real degraded CAIDA snapshot, and they do NOT cover the RIR leg at all (KG-5).
- G3 proves fresh planner statistics exist after one swap on a local corpus; it does NOT prove the p95 holds at prod scale or on Supabase, and it does NOT exercise the ANALYZE try/except swallow path.
- G4 proves all three population numbers were recorded; it does NOT prove the extraction sample is large enough to clear the floor it is measured against (C-31).
- G5 proves the written artifact has no `@` characters; it does NOT prove the extraction query avoided selecting `email` over the wire (C-33), and it does NOT prove the artifact was deleted after measurement.
- G6 proves accidental writes are refused; it does NOT prevent a superuser session from issuing `SET TRANSACTION READ WRITE`.
- G8 proves a measurement RAN with a real unfiltered stratum query behind it and that ≥80 rows carried a prediction. It does NOT prove the `v1==v2` invariant is meaningful (C-28 — production row choice is non-total, KG-9), does NOT cover the `unclassified` classification bucket (C-34), does NOT prove the derived labels are correct (KG-3), does NOT prove the free-mail exclusion is complete (KG-3), does NOT prove the corpus IPs are contemporaneous with their labels (KG-8), and asserts NO precision threshold by design (AC4.12 precedent).
- G9-G12 prove parser/family behavior on fixtures; they do NOT bound `family_reclassified`, so nothing proves the family pass leaves org coverage acceptable at population scale (KG-7).
- G11 proves the migration round-trips on `localhost:5433`; it does NOT prove a prod apply, and the head must be re-derived at EXECUTE time.
- G13 proves correctness against the vendored PSL snapshot only, ICANN section only (KG-1).
- G14 proves the OLD rejections still hold and covers all three census questions; it proves nothing about already-written `company_graph` / `visitors.company_domain` / `companies` rows, and nothing about live-path behavior before the caches expire (KG-6).
- G21 proves the narrowing half in both subclasses; G22 proves the widening half. Together they cover both directions at the resolver layer — but only on the enumerated hostnames, not on the real rDNS distribution, so the production VOLUME of the WIDENS class remains unmeasured.
- G15-G17 prove parser, threshold and direction-guard behavior against fixtures; they do NOT prove the vendored ASN set is accurate or current, nor that 50 000 is the right threshold (KG-2).
- G18 proves one response shape at one moment; it does NOT prove shape stability.
- G19/G20 prove no regression in the selected lanes; `-m unit` deselects 877 collected tests, and the integration lane is known to pass "by union" across attempts because of the conftest enum-teardown race. Neither number was re-measured this cycle — both must be RUN before the first edit (E5).
- **Fan-out gap:** all checks in this cycle were run sequentially by ONE agent with no database access. Cycles 2 and 3 were each followed by findings a single pass had missed. With 0 FAILs and 7 precision-class CONCERNs remaining, the expected yield of a fifth leg is materially lower than the previous three — but it is not zero.

Gate: CONDITIONAL

Accepted by: PENDING — this agent may not accept its own verdict. The gate is CONDITIONAL (0 FAILs, 7 CONCERNs) and this plan has 3 recorded PVL fix cycles, so EXECUTE becomes legal on either (a) an explicit user/orchestrator acceptance of the seven CONCERNs recorded above, or (b) a supplement cycle 4 closing them. Until one of those is recorded here, EXECUTE is NOT authorized.

### Convergence judgment (V5 — read this first)

**The residual set is NOT judgment-only, but it IS accept-or-not.** Stating both halves precisely:

- **Not judgment-only:** five of the seven (C-29, C-30, C-32, C-33, C-34) are objective plan-text defects with a single correct fix each, verified against source. C-31 is a number to choose. C-28 is a report-wording precondition.
- **But accept-or-not:** **all seven are fully carriable as execute-agent instructions** (E15–E21 below), and **none of them changes a design decision, a gate, an acceptance criterion, or the blast radius.** Nothing in this set can alter what gets built — only how precisely the plan describes it. That is the definition of a plan that has converged.

The yield curve supports stopping: cycle 1 → 2 FAILs; cycle 2 → 0 FAILs, 8 CONCERNs; cycle 3 → 0 FAILs, 7 CONCERNs, and every single one is a precision defect inside reasoning that is already correct. Three consecutive cycles have failed to overturn a conclusion. The remaining defects are the kind that a competent execute-agent handles from an instruction line.

**Recommendation: Option A2 — accept CONDITIONAL now, carrying E15–E21.** Option A1 (one more cheap supplement) is defensible if plan-text fidelity matters more than a cycle, since all five text fixes are single-sentence edits with named locations. Do not choose A3.

### Acceptance menu (V5 — numbered A-items for the user / orchestrator)

| # | Option | What it means | Cost | When it is right |
|---|---|---|---|---|
| **A1** | Supplement cycle 4, then accept without re-validating | Apply C-29, C-32, C-33, C-34 and the C-35 nits as single-sentence edits at the named locations; pick a number for C-31 and a mechanism for C-30; add C-28's duplicate probe to B4. Then accept — no cycle-5 validate. | one short supplement pass, no adversarial leg | Plan-text fidelity matters; the plan will be read by more than one agent, or resumed after a gap |
| **A2** | **Accept CONDITIONAL now, carry E15–E21 (recommended)** | Record acceptance of all seven CONCERNs; the execute-agent applies each correction in place as it reaches the relevant checklist item. | zero extra cycles | Cycle count matters more than plan-text fidelity; one execute-agent will do the whole pack in one pass. All seven fixes are unambiguous and none changes the design |
| **A3** | Accept as-is, all seven as known-gaps, no instructions | No fixes, no execute-agent instructions. | zero | **NOT recommended** — C-33 would ship a query that selects `email` against production, and C-34 would crash or silently drop rows in the report. Neither is a "gap"; both are defects with a known one-line fix |
| **A4** | One more adversarial refuter leg before deciding | Spawn an external refuter against this contract. | one extra cycle | Lowest yield yet: 2 FAILs → 0 → 0, and three cycles have not overturned a conclusion. Only worth it if WS-B's prod read is considered high-stakes enough to justify a fourth opinion on C-31 specifically |

### Execute-agent instructions (apply only after a PASS or explicitly-accepted CONDITIONAL contract exists)

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Insert the ANALYZE block BETWEEN `await db.commit()` (`ip_org_ingest.py:437`) and the fusion-cache invalidation — not after the invalidation. | WS-A item 2 |
| E2 | When extending the staging INSERT column list, add `"as2org_org_id": None` to the chunk-dict defaults at `ip_org_ingest.py:399-401`, BEFORE the `**row` splat at `:402`, so `refresh_rir_allocations` (which shares this function) keeps binding. | WS-C item 11 |
| E3 | Re-derive the live alembic head with `DATABASE_URL` pinned to `localhost:5433` immediately before generating the migration. Do not trust `c4a8f13e07b6`. | WS-C item 8 |
| E4 | Copy the scheduler registration pattern from `scheduler.py:733` onward (flag-guarded `add_job`), not from `:362-400` (job wrappers). | WS-E item 22 |
| E5 | Baseline the unit lane by RUNNING it before any edit; do not assume a number and do not tolerate any pre-existing failure. | WS-A item 6, before first edit |
| E6 | Docker is running (`5433`/`6379` LISTEN). No gate may be recorded as environment-blocked. | every Hybrid gate |
| E7 | Do NOT edit `apps/api/services/ip_org_rir_ingest.py` or `apps/api/services/visitor_aggregator.py`. Both are READ-ONLY in this pack. | any time |
| E8 | Implement `registrable_domain` to the D2 spec (public suffix + exactly one more label), not to any individual table cell. If a plan-stated expected value conflicts with the D2 spec, STOP and surface — do not silently pick one. | WS-D items 16-18 |
| E9 | The measurement script must derive `stratum` from its OWN query against `ip_org_prefixes` (no `org_kind` filter), NOT from `lookup_ip_org_v2`'s return. | WS-B item 30 |
| E10 | **(C-21)** Extract ~**300** rows minimum, not ~200 — see E18, which raises this. The ~200 figure is the post-stratum HEADLINE target, never the extraction target. | WS-B item 28 |
| E11 | **(C-22/P1-6)** Apply the same IPv4 strict regex, private-range exclusion and `ip_address <> ''` predicates to the events-derived IP that B2b applies to `visitors.ip_address`, plus the `created_at > '2026-07-26 09:13:43'` lower bound. `events.ip_address` defaults to `""` (`models/event.py:37`). | WS-B item 28 |
| E12 | **(C-20)** When writing G8, assert ≥1 stratum value in {`eyeball`, `datacenter`, `cdn`} — not merely "outside {`org`,`pending`}". | WS-B item 31 |
| E13 | **(C-24)** Grep `_EYEBALL_ORG_TOKENS` BEFORE adding any stem. `telkom` (`ip_org_ingest.py:81`) and `wireless` (`:82`) are already present — add neither. Tokens match by substring. | WS-E item 24 |
| E14 | **(C-25)** Both `visitors.is_agent_operated` (`models/visitor.py:117`) and `visitors.is_internal_suspect` (`:132`) DO exist — apply both, no presence check. See E17 for how to source the predicate. | WS-B items 26/28 |
| E15 | **(C-33)** In the B2b extraction CTE, do NOT write `SELECT iv.*`. Project explicitly: `iv.site_id, iv.visitor_id, iv.resolved_at, split_part(iv.email, '@', 2) AS email_domain` plus the IP column. `identified_visitors.email` must never appear in a select list — B3 and Q4 state this as a hard invariant and `iv.*` violates it. Attach `DISTINCT ON (ip_address) … ORDER BY ip_address, resolved_at DESC` to the OUTER query, after the private-range filter. | WS-B item 28 |
| E16 | **(C-34)** `v2_classification` has FOUR reachable values, not three. Add **`unclassified`** to the (b2) breakdown alongside `registered_operator` / `likely_operational_customer` / `disputed_origin`. `derive_classification` (`ip_org_fusion.py:289-297`) returns it whenever the RIR corpus does not cover the prefix, which will be common. A three-key breakdown will drop rows or raise. | WS-B items 30/31 |
| E17 | **(C-30)** `human_only_visitor_filter()` (`agent_visitor_filters.py:19`) is a SQLAlchemy predicate builder using `aliased(Visitor)` and a correlated EXISTS; it CANNOT be interpolated into B3's raw asyncpg SQL. Choose one and record the choice in the phase report: (a) build the extraction query with SQLAlchemy Core over an asyncpg engine; (b) compile the predicate and lift the WHERE fragment, fixing the alias; or (c) hand-inline `is_agent_derived = false AND is_agent_operated = false AND is_internal_suspect = false` plus the phantom-contact EXISTS and state that the canonical helper was deliberately not reused. (c) is acceptable — `source_agent_visit_id IS NULL` already covers the agent-derived class from the IdentifiedVisitor side. | WS-B item 28 |
| E18 | **(C-31)** The ~300 extraction target lands the EXPECTED predicted count exactly on the `< 80` descope floor, and the 60 % eyeball/none assumption is likely optimistic for visitor IPs. Either extract ~500-600, or make the floor recoverable: if the predicted count lands under 80, re-run the extraction with a larger LIMIT BEFORE descoping. Do not descope WS-B on a first-pass shortfall. Record the choice and all three population numbers. | WS-B items 26/28/31 |
| E19 | **(C-28)** Before reporting any `v1_pred != v2_pred` divergence as a BUG, run the duplicate probe: `SELECT prefix, masklen(prefix), count(*) FROM ip_org_prefixes WHERE relationship_type='route_origin' AND org_kind='org' GROUP BY 1,2 HAVING count(*) > 1`. Report its count. A zero count is what makes the invariant meaningful; a non-zero count downgrades every divergence to "possible data property — see KG-9". The `, id` tie-break in the script's own queries does NOT make this invariant deterministic, because the invariant runs through the untouched production SQL. | WS-B items 30/31 |
| E20 | **(C-32)** Q3 is a stale Locked Decision: its single-B1-count floor is superseded by B1's three-number table (P1-4) and its "distinguish v1 from v2" rationale is superseded by Q14/R1. Follow B1 and AC-B1, not Q3, and note the supersession in the phase report. | WS-B item 26 |
| E21 | **(C-29 / C-35)** WS-B depends on WS-D — build `public_suffix.py` before `build_ip_org_benchmark.py`, regardless of what `## Sequencing and Dependencies` says ("WS-D independent" is stale). Corrected citations for the phase report: `content_reader._SECOND_LEVEL_TLDS` is at `:616`; `is_agent_derived` is at `models/visitor.py:75`. In the report, print the `None`-rate and coverage denominators next to each other, note that IPv6-only visitors are excluded by the IPv4 regex, and describe `0.20`/`0.25` as the values reachable ONLY via `rpki=invalid`. | WS-D items 16-18, WS-B items 28/31 |


## PVL Supplement Log

### Cycle 1 — applied 08-08-26 (vc-plan-agent, PVL-supplement mode)

Source: the `## Validate Contract` section's cycle-1 verdict (`Gate: BLOCKED`, FAIL-1, FAIL-2,
CONCERN-3…13). That section is left untouched by design — it is cycle 1's record. Every disposition
below is a change to the plan BODY.

| Gap | Disposition | Where in the plan |
|---|---|---|
| FAIL-1 | FIXED — added Q11 (bidirectional change, stated as intentional); rewrote D3 with a 6-row before/after table correcting BOTH wrong examples (`foo.bar.gov.br` → `gov.br` today, `x.co.za` → `co.za` today, not `None`); re-aimed D4's census onto the two real questions (who loses a domain / whose domain changes); rewrote the `_extract_domain` Public Contracts row from "Widening" to "BIDIRECTIONAL"; re-keyed the WS-D BLOCK completion rule to a condition that can actually fire; added AC-D3 + gate G21 for the newly-rejected set; updated Blast Radius | Q11, D3, D4, D5, Public Contracts, Blast Radius, Phase Completion Rules, AC-D3, G21, checklist 14/17/18 |
| FAIL-2 | FIXED — added Q12 specifying the in-process flag-override mechanism (`settings.ip_org_lookup_enabled = True`; verified mutable — `config.py:1187` sets no `validate_assignment`/`frozen`), applied to BOTH arms (verified guards at `ip_org_lookup.py:66` and `:153`); corrected the false `ip_org_fusion_enabled` bypass claim (its only reader is `company_resolver.py:610`; `lookup_ip_org_v2` never reads it); added a fatal `FAILED-INVALID` non-vacuity precondition (flag True AND `ip_org_prefixes` non-empty; a zero-non-None run is invalid, never a passing tie) | Q12, B4, AC-B5, checklist 30 |
| CONCERN-3 | FIXED — new item C4a mandates `"as2org_org_id": None` in the chunk-dict defaults before the `**row` splat, plus an RIR-shaped-row unit test | C4a, checklist 11 |
| CONCERN-4 | FIXED — Q13 states the two-DSN split explicitly (extraction reads PROD; stratum + measurement read LOCAL `localhost:5433` because prod's `ip_org_prefixes` is empty) and reconciles it with the pack-wide pin constraint | Q13, B3, B4, checklist 26/28/30 |
| CONCERN-5 | FIXED — B2 table gained a `Where` column; the `classify_org_kind` rule moved out of SQL into the measurement script (it takes an org STRING, not an IP) and became a visible per-stratum exclusion; an IPv4 regex pre-filter now precedes every `::inet` cast (`visitors.ip_address` is `String(45)`) | B2 |
| CONCERN-6 | FIXED — B3 now selects `split_part(email, '@', 2)`; the local-part never crosses the wire or enters process memory, making Q4's claim literally true | B3, B2 |
| CONCERN-7 | FIXED — the stale "2 pre-existing failures" note is replaced with the measured fact (class renamed by identity-vocab-reconcile; 33 passed / 0 failed) and an instruction to treat ANY failure as a real regression | Test Infra Improvement Notes |
| CONCERN-8 | FIXED — G19 now carries the measured 1605 passed / 2 skipped / 877 deselected figure for its own command, notes the 877 deselection, and requires the baseline be RUN before the first edit rather than quoted | G19 |
| CONCERN-9 | FIXED — E1 gains a streamed max-response-size cap; new setting `ip_org_apnic_max_bytes` (32 MB) following the `ip_org_rpki_max_bytes` precedent; exceeding it is fail-open | E1, E2, checklist 20/21 |
| CONCERN-10 | FIXED — A5 restated as a verified FACT (the guard is CAIDA-only; `refresh_rir_allocations` has no skipped counter and no offered-row denominator) rather than a conditional. **DESCOPED, not added**: no RIR counter is invented in this pack. New known-gap KG-5 with a backlog stub records the residual | A5, KG-5, checklist 5/33 |
| CONCERN-11 | FIXED — new AC-D3 + gate G21 assert the newly-REJECTED set (`dsl-pool.host.talktalk.co.uk`, `c-1-2-3.hsd1.virgin.co.uk` → `None`) plus the corrected cases; WS-D cannot reach CODE DONE without G21 | AC-D3, G21, D5 group iii, Phase Completion Rules |
| CONCERN-12 | FIXED — scheduler reference corrected to `scheduler.py:733-766` (flag-guarded `add_job`) in both the WS-E body and the checklist | E2, checklist 22 |
| CONCERN-13 | FIXED — Q10 locks PSL parsing to the **ICANN section only**, with the rationale that PRIVATE-section cloud suffixes would bypass `_build_domain_filter_regex`; D2 implements the marker scoping; D5 group (i) gains an `amazonaws.com` proof case | Q10, D2, D5, AC-D3 |

**C-10 restated as fact + descope decision:** `refresh_rir_allocations` does not and will not gain a
skip-ratio guard in this pack. The A5 conditional is dead; the limitation is now a first-class
known-gap (KG-5) with a backlog stub, and the CAIDA-only scope is stated in the plan body, the
known-gaps list, and the checklist.

**Scope note:** all edits are confined to this plan file. No source file, test file, `results.tsv`,
or git state was touched. The `## Validate Contract` section was not modified.

**Next:** vc-validate-agent re-runs PVL from V1 against the supplemented plan.

### Cycle 2 — applied 08-08-26 (vc-plan-agent, PVL-supplement mode)

Two binding inputs this cycle: the `## Validate Contract` section's cycle-2 SUPPLEMENT REQUEST
(FAIL-3, FAIL-4, C-14…C-19) **and** an external adversarial verifier's findings (R1–R13 + BONUS),
which are not recorded in the contract section but are equally binding. The `## Validate Contract`
section is left untouched by design. Dedupe applied: C-18 == R10 (one fix); FAIL-4 is subsumed by
R1's reframe and adopts the validator's stratum query inside it; R12 was applied together with
FAIL-3's G21 edits.

| Gap | Source | Disposition | Where in the plan |
|---|---|---|---|
| FAIL-3 | validator | FIXED — D3 rows 4 and 6 corrected (`x.co.za` → `x.co.za`; `x.co.uk` → `x.co.uk`); the missing **WIDENS** class added as its own table row and named in the prose, Public Contracts, Blast Radius, D4 census question (c), a new AC-D4, and a new gate G22 (test group iv) | D3 table + prose, D4, D5(iii)(iv), Public Contracts, Blast Radius, AC-D3/AC-D4, G13/G21/G22, checklist 14/18, Phase Completion Rules |
| FAIL-4 | validator | SUBSUMED BY R1 — the unsatisfiable "stratum from the v2 return" instruction is replaced by the validator's own suggested fix: an unfiltered `ip_org_prefixes` query issued by the measurement script (Q14), with `none` distinct from `pending`. G8 now asserts ≥1 stratum outside {`org`,`pending`} so the fix cannot be silently skipped | Q14, B2, B4, B5, AC-B5, G8, checklist 30 |
| C-14 | validator | FIXED — B1 restated as an UPPER BOUND; the real `< 80` floor moves to the post-stratum headline count; deliberate over-sampling (~300 → ~200) with recorded shrinkage | B1, AC-B1, G4, checklist 26/31 |
| C-15 | validator | FIXED — the miscounted preamble ("two of the six") is replaced with "exactly one of the nine rules is not SQL-expressible", matching the table after the R3/R4/R5 additions | B2 preamble |
| C-16 | validator | FIXED — the stale `ip_org_rir_ingest.py` Touchpoints row is restated as READ-ONLY / DO-NOT-EDIT with the A5/KG-5 rationale; Blast Radius file count recut to ~18 | Touchpoints, Blast Radius |
| C-17 | validator | SUPERSEDED BY R1 for (a) — there is no defensible McNemar computation set because the statistic itself is degenerate; the framing is withdrawn. (b) FIXED as specified: the "exclusion criterion is produced by the system under test" self-exclusion bias is now a mandatory report limitation next to KG-3 | Q14, B4 |
| C-18 / R10 | validator + adversarial (deduped) | FIXED — the false "only signal for `registered_holder` rows" justification is withdrawn in BOTH Q8 and E3, with the source evidence (`_allocation_to_row` hardcodes `org_kind="registry"`; sole `classify_ip_org_kind` caller is the CAIDA path); the CAIDA-ASNs-absent-from-APNIC ground is stated as the real and sufficient justification | Q8, E3 |
| C-19 | validator | FIXED — D3 row 1's parenthetical now credits `_build_domain_filter_regex` at `:115` (talktalk/virgin are `_DOMAIN_PATTERNS` entries), not the hostname filter | D3 table |
| R1 | adversarial | FIXED (reframes WS-B) — the v1/v2 McNemar comparison is proven degenerate by construction and ABANDONED. New Q14 replaces it with (a) single-arm precision, (b) v2 confidence-calibration bucketing, (c) a `v1_pred == v2_pred` invariant assertion whose divergence is a bug report. Stratum comes from the validator's unfiltered query | Q14, B4, B5, AC-B5, G8, checklist 30 |
| R2 | adversarial | FIXED — B4 now names the scored FIELD explicitly: v1 scores `match["org_name"]`, v2 scores `hypothesis["organization"]`, and `domain` is NEVER scored (NULL by construction, domain leg split out of Phase 3). G8 asserts the naming | B4, G8 |
| R3 | adversarial | FIXED — the two-column join `ON iv.site_id = v.site_id AND iv.visitor_id = v.visitor_id` is now mandatory in B1/B2/B3, with the cross-tenant rationale (no FK from `IdentifiedVisitor` to `Visitor`) | B2 preamble, B3, checklist 26/28 |
| R4 | adversarial | FIXED — new mandatory B2 rule `identified_visitors.source_agent_visit_id IS NULL` plus `is_agent_operated` / `is_internal_suspect` where present, with the poisoned-label rationale tied to the repo's top guardrail class | B2, B3, checklist 26/28 |
| R5 | adversarial | FIXED — new B2 row records that `visitors.ip_address` is LAST-SEEN (overwritten at `visitor_aggregator.py:315`/`:677`); preferred fix is an events-table derivation at/near `resolved_at`, with an honestly-worded stratum + KG-8 fallback if that proves impractical | B2, B3, KG-8, checklist 28 |
| R6 | adversarial | FIXED — B4 now requires a per-arm `None`-rate / corpus-coverage metric, and states plainly that no pre-C/E baseline exists (B runs last); recorded as KG-7 so the unmeasured recall delta is a named residual rather than an omission | B4, KG-7, AC-B5, G8 |
| R7 | adversarial | FIXED — D4's census pattern gains `resolve_company_cached` (the `visitor_aggregator.py:749`/`:774` consumer neither original token matched); `visitors.company_domain` + `companies` named as untouched-history surfaces in Out of Scope and as a READ-ONLY Touchpoints row | D4, Touchpoints, Public Contracts, Blast Radius, Out of Scope, AC-D2, G14, checklist 14 |
| R8 | adversarial | FIXED (accepted, not solved) — new Q15 states the 30–75 day cache-lag posture (Redis `company_ip`, `company_graph` staleness) as an accepted named known-gap KG-6 with a backlog stub; surfaced in D4's answers and Q11's prose | Q15, D3 prose, D4, KG-6, checklist 14/33 |
| R9 | adversarial | FIXED — C4's family fold now inherits ONLY into rows whose own per-ASN kind is `org`, blocking lateral moves (an `eyeball` ASN can no longer be overwritten to `cdn` by a sibling); C6 gains the lateral case | C4, C6 |
| R11 | adversarial | FIXED — E4 no longer names `telecom` (`:81`) or `deutsche telekom` (`:87`); only genuinely-new stems get fixtures, and the excluded-already-present list is recorded in the phase report | E4, checklist 24 |
| R12 | adversarial | FIXED (with FAIL-3) — the two-layer distinction is explicit: the `amazonaws.com` ICANN proof lives in `test_public_suffix.py` ONLY (registrable-domain layer); `test_company_resolver.py` asserts the FILTERED `None`, matching its existing `:71` case. G21 no longer carries the contradictory pair | D5(i), D5(iii), AC-D3, G13, G21 |
| R13 | adversarial | FIXED — the CF cutoff literal is now naive UTC `'2026-07-26 09:13:43'` (matching `resolved_at`'s `timestamp WITHOUT time zone`), and the script issues `SET TIME ZONE 'UTC'` with the assumption stated | B2, B3, checklist 28 |
| BONUS | adversarial | FIXED — `content_reader.py:615`'s `_SECOND_LEVEL_TLDS` + `_domain_root` named as a THIRD hardcoded suffix set in Out of Scope, explicitly not refactored in this pack | Out of Scope |

**Scope note:** all edits are confined to this plan file. No source file, test file, `results.tsv`,
or git state was touched. The `## Validate Contract` section was not modified.

**Next:** vc-validate-agent re-runs PVL from V1 against the supplemented plan; the orchestrator
should again pair it with an external adversarial verifier, since both cycle-2 FAILs and eleven of
the thirteen findings above came from legs the single-pass validator did not cover.

### Cycle 3 — applied 08-08-26 (vc-plan-agent, PVL-supplement mode)

Two binding inputs, as in cycle 2: the `## Validate Contract` section's cycle-3 SUPPLEMENT REQUEST
(C-20…C-27) **and** an external adversarial verifier's round-2 findings (P1-1…P1-6, P2-7…P2-12),
which are not recorded in the contract section but are equally binding. The `## Validate Contract`
section is left untouched by design. Dedupe applied: **P2-7 == validator C-23** (one fix);
**validator gap 3 (events-derived IP predicates) is subsumed by the P1-5 + P1-6 composition** and
was applied as one edit. 20 raw items → **18 unique gaps addressed**.

| Gap | Source | Disposition | Where in the plan |
|---|---|---|---|
| P1-1 | adversarial | FIXED — the 4 equal-width confidence buckets are WITHDRAWN as degenerate. The reachable set is proved to be exactly `{0.20,0.25,0.40,0.45,0.55,0.60,0.65}` (base 0.45 + alloc {+0.15,0,−0.05} + rpki {+0.15,0,−0.20}, clamped), so the 0.05 floor is dead code and `[0.05,0.2)` is provably empty. Replaced with a **per-reachable-value table (7 rows)**, with a mandatory inline note that the two rpki-invalid values are near-empty at N≈200, and a ban on the phrase "four-bucket calibration" | Q14(b), B4, AC-B5, G8, checklist 30 |
| P1-2 | adversarial | FIXED — `expected_org` was unimplementable (`registrable_domain` returns suffix+label; `normalize_org_name("acme.com")` → `"acme com"`; `content_reader._domain_root` is Out of Scope). Specified a 3-line `label_root()` helper INSIDE `build_ip_org_benchmark.py` reusing **WS-D's vendored PSL module**, with the worked example made consistent (`deloitte.co.uk` → `deloitte`). Declared an **in-pack WS-B → WS-D dependency**; the existing A→C→D→E→B order already satisfies it | B3, checklist 28, Resume handoff |
| P1-3 | adversarial | FIXED — headline precision had no denominator and "precision per `match_method`" was ill-posed. Now: `precision = correct / rows with a non-None prediction`; `coverage = non-None / headline rows` reported separately; `match_method` demoted to a **numerator decomposition** (share of correct by method) | Q14(a), B4, G8, checklist 30 |
| P1-4 | adversarial | FIXED — the go/no-go floor sat on the wrong population (eyeball/none strata are inside the headline set but produce zero predictions). The operative floor is now **≥80 rows WITH a non-None prediction (stratum `org`)**; three population numbers are recorded with shrinkage; G8's non-vacuity becomes "≥80 predicted rows", not "≥1" | B1, B5, AC-B1, AC-B5, G4, G8, checklist 26/31 |
| P1-5 + validator gap 3 | adversarial + validator (composed) | FIXED — the IPv4-regex-before-cast guard was inoperative (Postgres `AND` does not short-circuit) and the loose regex admitted `999.x`. Replaced with new **B2b**: octet-range-strict regex + `WITH … AS MATERIALIZED` optimization barrier (or an equivalent `CASE` wrapper); a bare `AND`-chain is explicitly forbidden. The B2 "has a usable IP" row now points at B2b | B2 table, new B2b, checklist 28 |
| P1-6 + C-22 | adversarial + validator (composed) | FIXED — the R5 events derivation reopened the CF-edge hole and could return `''` (`events.ip_address` defaults to `""`, `models/event.py:37`). The events query now carries `created_at > '2026-07-26 09:13:43'` (same naive-UTC literal as the `resolved_at` cutoff), `ip_address <> ''`, the strict regex and the private-range exclusion — i.e. exactly the B2b predicates | B2 R5 row, checklist 28 |
| P2-7 == C-23 | adversarial + validator (deduped) | FIXED — Q14 credited `ip_org_rir_ingest.py:162` with `relationship_type='registry'`; `:162` is `org_kind="registry"` and `relationship_type="registered_holder"` is `:163`. Citation corrected, conclusion explicitly reaffirmed (RIR rows are excluded by `org_kind='org'`, not by any relationship_type predicate) | Q14 |
| P2-8 | adversarial | FIXED — the `v1==v2` invariant and the stratum query rested on a non-total `ORDER BY masklen(prefix) DESC LIMIT 1` (no unique constraint on `prefix`, no dedupe in `parse_pfx2as`), so a duplicate prefix could manufacture a FALSE bug report. Added `, id` to the measurement script's OWN queries + a stated precondition. **Production SQL deliberately NOT changed** — recorded as new **KG-9** with a backlog stub | Q14 stratum SQL, B4(c), KG-9, checklist 30/33 |
| P2-9 | adversarial | FIXED — `v2_classification` was collected and never consumed. Added report section **(b2): accuracy by classification value** (`registered_operator` / `likely_operational_customer` / `disputed_origin`) with row counts — free, and the one v2 output not determined by the confidence value | Q14(b2), B4, AC-B5, G8, checklist 30 |
| P2-10 | adversarial | FIXED — two composition hazards. (a) C6 fixture ASNs could collide with WS-E's vendored `eyeball_asns.json` and flip G10 red after E3 lands: **all fixture ASNs now drawn from the reserved `64512–65534` range**. (b) both new loaders are `@lru_cache(maxsize=1)`: **new E6a mandates `cache_clear()` in setup for every test that varies the underlying file**, or the fail-open test asserts against a previous test's cached data and passes vacuously | C6, E6a, G10, checklist 13/25 |
| P2-11 | adversarial | FIXED — G17 could not detect a mis-built `AS{asn} ` prefix, because a Cloudflare-shaped fixture matches via the ORG TOKEN either way. Added **E6b**: a discriminating case with NO cdn/datacenter token in the org string whose ASN IS in `_CDN_RELAY_ASNS` (`company_resolver.py:323`, used at `:352`) → must classify `cdn`. It is the only fixture in the matrix that fails when the prefix is wrong | E6b, AC-E3, G17, checklist 25 |
| P2-12 | adversarial | FIXED — the NARROWS class had an unrepresented and higher-impact subclass: **hostname-filter-only** hosts whose registrable domain is a REAL corporate domain (`dhcp-1-2-3.acme.co.uk` → `acme.co.uk` today → `None` after; `acme` is not a `_DOMAIN_PATTERNS` entry, so `:115` passes and `_build_hostname_filter_regex` at `:119` fires on the `dhcp` token). Added as a D3 table row + prose splitting NARROWS into subclasses (i)/(ii), a G21 test case with a comment naming the lost real domain, and a D4 census requirement to answer both subclasses separately | D3 table + prose, D4(a), D5(iii), AC-D3, G21, checklist 18 |
| C-20 | validator | FIXED — G8's stratum non-vacuity clause ("≥1 value other than `org`/`pending`") was satisfiable by `none`, which is trivially reachable and proves nothing about the datacenter/CDN exclusion being operative. Tightened to **≥1 value in {`eyeball`,`datacenter`,`cdn`} specifically**; achievable since eyeball prefixes are ~26.9 % of the loaded corpus | B5, AC-B5, G8 |
| C-21 | validator | FIXED — B3 still carried the pre-C-14 "Target size ~200 rows" while B1 and checklist 26 said ~300. B3 now says **~300 extracted**, with the ~200 explicitly labelled the post-stratum HEADLINE target | B3 |
| C-24 | validator | FIXED — E4's replacement candidate list reintroduced the R11 defect: `telkom` is already on `ip_org_ingest.py:81` and `wireless` on `:82` (verified live this cycle). The illustrative list is **withdrawn entirely** rather than corrected — the grep-first instruction IS the specification — with a note that tokens match by substring, and both the added and excluded-already-present lists must be recorded | E4 |
| C-25 | validator | FIXED — (a) the "where those columns exist" hedge is resolved to fact: `visitors.is_agent_operated` (`models/visitor.py:117`) and `is_internal_suspect` (`:132`) both exist; no EXECUTE-time presence check. (b) B2 now mandates importing the canonical **`human_only_visitor_filter()`** (`apps/api/services/agent_visitor_filters.py`) instead of hand-rolling a partial subset — same "reuse the one existing list" principle B2a applies to free-mail domains; it also catches `is_agent_derived` and `is_imported_contact` | B2 agent-origin row, checklist 28 |
| C-26 | validator | FIXED (judgment call taken: **sanction an addendum**) — `content_reader._GENERIC_DOMAINS` (14 entries, a plain `set`) is unfit as a free-mail exclusion in both directions. B2a now specifies `FREE_MAIL_EXCLUDE = (_GENERIC_DOMAINS | BENCHMARK_FREE_MAIL_ADDENDUM) − BENCHMARK_REAL_EMPLOYERS`: **ADD** `live.com`, `msn.com`, `me.com`, `googlemail.com`, `mail.com`, `gmx.com`, `yandex.ru`, `qq.com`, `163.com`, `naver.com`, `zoho.com`, `proton.me`; **REMOVE for this purpose only** `linkedin.com`, `x.com` (real employers). The addendum is benchmark-local and is never written back into `content_reader`. Rationale + bias direction folded into KG-3 and the report limitations | B2a, KG-3, checklist 28 |
| C-27 | validator | FIXED — (a) Out of Scope's "G19-style yield measurement" now says **the parent program's G19**, since this plan's own G19 is the unit lane; (b) `_SECOND_LEVEL_TLDS` is at `content_reader.py:618`, not `:615`, and `_GENERIC_DOMAINS` is a `set`, not a `frozenset` — both corrected; (c) the tie-break nit is superseded by the stronger P2-8 fix (measurement-script `, id` + KG-9 for production) | Out of Scope, B2a, Q14/B4 |

**Judgment calls recorded (these were the four non-mechanical items):**

- **C-26** — chose "sanction a benchmark-specific addendum" over "fold the incompleteness into KG-3
  only". Both were offered by the validator; the addendum is cheap, the bias it removes is
  bidirectional, and KG-3 still carries the residual honestly.
- **C-24** — chose to DELETE the illustrative stem list rather than correct it. A corrected list would
  go stale the same way; the grep instruction is the durable specification.
- **P2-8** — chose to fix the tie-break ONLY in this pack's scripts and record production as KG-9,
  rather than widen the blast radius onto the live lookup path mid-pack.
- **P1-4** — chose to keep all three population numbers (upper bound / headline / predicted) rather
  than replace the earlier two; the shrinkage between them is itself a reportable finding.

**Scope note:** all edits are confined to this plan file. No source file, test file, `results.tsv`,
or git state was touched. The `## Validate Contract` section was not modified. Source facts newly
verified read-only this cycle: `_EYEBALL_ORG_TOKENS` (`ip_org_ingest.py:80-89` — `telkom` on `:81`,
`wireless` on `:82`), `classify_ip_org_kind` (`:110-125`, the `f"AS{asn} {org_raw}"` shape),
`_CDN_RELAY_ASNS` (`company_resolver.py:323`, consumed at `:352`), `_HOSTNAME_PATTERNS`
(`company_resolver.py:65-70`, contains `dhcp`/`pool`/`dsl`).

**Next:** the orchestrator records an acceptance line, or re-spawns `vc-validate-agent` from V1. A
fourth adversarial leg is optional — the yield curve is 2 FAILs → 0 FAILs + 8 CONCERNs → 0 FAILs +
12 findings, and every cycle-3 finding was a *precision* defect in already-correct reasoning rather
than a wrong conclusion.

### Cycle 4 — applied 08-08-26 (vc-plan-agent, PVL-supplement mode)

Source: the `## Validate Contract` section's cycle-4 verdict (`Gate: CONDITIONAL`, 0 FAILs, 7
CONCERNs C-28…C-34 + the C-35 cosmetic bundle). That section is left untouched by design — it is
cycle 4's record. Every disposition below is a change to the plan BODY. Two of the seven (C-33
privacy leak, C-34 missing `unclassified`) are correctness fixes; the rest are one-line consistency
or wording corrections.

| Gap | Disposition | Where in the plan |
|---|---|---|
| C-28 (invariant precondition unattainable) | FIXED — the `v1==v2` invariant is GATED on a mandatory duplicate-prefix probe (`GROUP BY prefix HAVING count(*)>1`). Zero rows → assert (divergence is a real BUG); non-zero → SKIP (record not-run + duplicate count), never FAIL — the invariant runs through UNTOUCHED production SQL (KG-9), so the script's own `, id` tie-break cannot make it deterministic. Probe result stated in the report | Q14(c) / P2-8 block, B4 (c), AC-B5, G8, checklist 30 |
| C-29 (sequencing denies the WS-D→WS-B dependency) | FIXED — `## Sequencing and Dependencies` diagram now carries `WS-D ──► WS-B` and the word "independent" is deleted; matches B3 + checklist 28 | Sequencing and Dependencies |
| C-30 (mandated helper cannot be called from raw-SQL driver) | FIXED — bridge decision (a): hand-inline `is_agent_operated / is_internal_suspect / is_bot_suspect / is_abuse_flagged / do_not_resolve = false AND source_agent_visit_id IS NULL` in the CTE `WHERE`; do NOT import `human_only_visitor_filter()` (SQLAlchemy predicate builder, cannot compose into an asyncpg string). Phase report records the non-reuse + a sync pointer to `agent_visitor_filters.py:19` | B2 agent-origin row, checklist 28 |
| C-31 (no headroom over the floor) | FIXED — extraction target raised ~300 → **~500-600** (option: raise target). Rationale: ~300→~200 headline→~80 predicted lands EXACTLY on the `<80` floor with zero headroom and the 60 % eyeball assumption is optimistic (prefix-share ≠ visitor-share; real visitor IPs skew consumer). Rejected the re-extract-on-shortfall alternative (spends a second prod read) | B3 target line, B1/Q3, checklist 26/28 |
| C-32 (stale Locked Decision Q3) | FIXED — Q3 now points at B1's THREE-number table and names the predicted-row count as the operative floor; the single-B1-count floor and the withdrawn v1-vs-v2 rationale are replaced with "corpus too small for a usable single-arm precision number" | Q3 |
| C-33 (PRIVACY — CTE `SELECT iv.*` leaks `email`) | FIXED — B2b CTE rewritten with explicit projection (`iv.site_id, iv.visitor_id, iv.resolved_at, split_part(iv.email,'@',2) AS email_domain, v.ip_address`); `DISTINCT ON (ip_address) … ORDER BY ip_address, resolved_at DESC` shown on the OUTER query after the private-range filter. Added a static-source-check clause to G5/AC-B2 asserting no bare `email` appears in any SELECT list of `build_ip_org_benchmark.py` (the TSV grep cannot catch a wire leak) | B2b CTE, G5, AC-B2, checklist 28 |
| C-34 (classification enum omits `unclassified`) | FIXED — `unclassified` added to ALL FOUR enumerations of `v2_classification` (Q14(b2), B4 (b2), AC-B5, G8) + checklist 30. `derive_classification` (`ip_org_fusion.py:289-297`) is a total function returning it for any prefix the RIR corpus does not cover (common: 262 k RIR vs 967 k+ route rows); a three-key breakdown would drop rows or raise | Q14(b2), B4 (b2), AC-B5, G8, checklist 30 |
| C-35 (cosmetic bundle) | FIXED — (a) `_SECOND_LEVEL_TLDS` citation corrected to `content_reader.py:616` (both `:615` and `:618` were wrong); (b) `is_agent_derived :74`→`:75` already carried by the C-30 rewrite of the B2 row; (c) `**Status**` header + `## Autonomous Goal Block` updated from "awaiting supplement cycle 3" to the current cycle-4-applied / A1-pre-accepted state; (d) B4 (b) note now states `0.20`/`0.25` are the values reachable ONLY via `rpki=invalid` (`0.40` is reachable by other paths too) | Out of Scope, Status header, Autonomous Goal Block, B4 (b) |

**Scope note:** all edits are confined to this plan file. No source file, test file, `results.tsv`,
or git state was touched. The `## Validate Contract` section was not modified.

**Next:** the user has pre-accepted (A1). The orchestrator records the acceptance line and proceeds
to EXECUTE in order **A → C → D → E → B** — no cycle-5 validate. All seven cycle-4 CONCERNs and the
C-35 bundle are dispositioned above and self-consistent across Q3/Q14/B1/B2/B2b/B3/B4, the AC table,
the gate table, the checklist, the Sequencing diagram, the Status header and the Autonomous Goal
Block.

## Autonomous Goal Block

```
SESSION GOAL: ip-org quality pack WS-A..WS-E — post-swap ANALYZE + skip-ratio guard, derived-label
benchmark corpus, as2org organizationId retention, Public-Suffix-List domain extraction, APNIC
eyeball ASN list.
Charter + umbrella plan: N/A — single plan (no umbrella with a Stable Program Goal governs this
pack; parent program ip-org-database_07-08-26 Phases 1-3 are shipped and prod-deployed).
Autonomy: PVL supplement cycles run without a user gate. Supplement cycle 4 is APPLIED (C-28…C-34
+ C-35 bundle closed in the plan body). User has pre-accepted (A1) — the orchestrator records
acceptance without a cycle-5 validate; route to vc-execute-agent once that acceptance line lands.
Hard stop conditions / safety constraints:
- Never run an alembic or DB command without pinning DATABASE_URL to localhost:5433. The repo
  dotenv file points at Supabase PRODUCTION and migrations/env.py has no local-host guard.
- The WS-B scripts read production data. They must be SELECT-only and must refuse to run without an
  explicitly supplied DSN.
- Do not flip any ip_org_* feature flag in any deployed environment. Enabling a flag inside a local
  measurement process is fine; a deploy-level flip is an operator action, not an agent action.
- Do not touch identity-side files or another program's active task folder.
- No new Python dependencies.
Next phase: supplement cycle 4 is COMPLETE — the seven cycle-4 CONCERNs (C-28 invariant precondition
/ duplicate-prefix probe, C-29 sequencing edge, C-30 helper-vs-raw-SQL bridge, C-31 extraction
headroom, C-32 stale Q3, C-33 privacy projection, C-34 `unclassified`) plus the C-35 cosmetic bundle
are all closed in the plan body. Gate: cycle 4 CONDITIONAL, zero FAILs. User pre-accepted (A1);
orchestrator records acceptance and EXECUTE proceeds A → C → D → E → B — no cycle-5 validate.
Validate contract: inline in this plan file (## Validate Contract) — latest verdict cycle 4, Gate: CONDITIONAL.
Execute start: authorized on the acceptance line. The fully-auto start
is `.venv/bin/python -m pytest tests/unit -m unit -q` (baseline 1605 passed / 2 skipped) plus the
targeted ip_org/public_suffix/apnic/company_resolver unit files; Hybrid gates need
`docker compose -f infra/docker-compose.yml up -d postgres redis` (already running).
high-risk pack: no — schema change is additive and nullable; no auth, billing, public API or
destructive writes in the blast radius.
```

## Next Step

Say **"ENTER VALIDATE MODE"** to run PVL on this plan. Do not enter EXECUTE first.
