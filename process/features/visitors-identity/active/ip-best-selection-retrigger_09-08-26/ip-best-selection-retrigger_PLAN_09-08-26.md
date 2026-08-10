---
name: plan:ip-best-selection-retrigger
description: "COMPLEX PLAN — best-IP ranking at resolve time + capped automatic re-identify sweep (4 lifetime attempts, 7-day cadence, every site, shared daily budget)"
date: 09-08-26
feature: visitors-identity
metadata:
  node_type: plan
  type: plan
  feature: visitors-identity
---

# Best-IP Selection + Capped Automatic Re-Identify

**Date**: 09-08-26
**Status**: ⏳ PLANNED
**Complexity**: COMPLEX (multi-workstream, single execution stream — one plan file, not a phase program)
**Feature**: visitors-identity
**SPEC**: `process/features/visitors-identity/active/ip-best-selection-retrigger_09-08-26/ip-best-selection-retrigger_SPEC_09-08-26.md`
**Context loaded**: `process/context/all-context.md`, `process/context/tests/all-tests.md`

---

## TL;DR

A visitor browses from several IPs; Beam stores only the newest one and spends its single paid
attempt on whatever was last. This plan (a) ranks the visitor's known IPs and resolves the *best*
untried one, and (b) gives every visitor **4 lifetime automatic attempts, one per 7 days**, each
spending one distinct IP. All of it sits behind a new default-OFF flag
(`auto_reidentify_enabled`), consumes the **existing** 50/site/day identify budget, and adds
**three additive columns** plus **two new modules** — the resolver and the rollup each take exactly
one surgical edit.

---

## Overview

### The miss (verified chain)

| Step | Anchor | What goes wrong |
|---|---|---|
| Ingest stamps one IP per batch | `apps/api/routers/events.py:224`, `:394` | — |
| Rollup overwrites with the NEWEST IP | `apps/api/services/visitor_aggregator.py:315`, incremental `:619` | "latest", never "best" |
| Sweep every 30 min, `intent_score DESC LIMIT 20`, floor 20 | `apps/api/services/resolution_runner.py:123-149`, `apps/api/models/visitor.py:258` | — |
| Resolver reads that one IP; `resolve()` takes no IP argument | `apps/api/services/identity_resolver.py:593` | No way to choose |
| Failure forks | `identity_resolver.py:602-622` (`vpn_filtered`) / `:747-753` (`unresolvable`) | `vpn_filtered` non-retryable at `apps/api/routers/visitors.py:930-931` |
| 30-day gate `was_recently_attempted(site_id, visitor_id)` | `identity_resolver.py:168-177`, enforced `:583-587` | **IP-blind** — `ResolutionLog` has no IP column (`apps/api/models/visitor.py:240-253`) |

Net effect: one home-Wi-Fi visit writes the person off. The customer never learns to press Retry,
so the lead dies silently. **`vpn_filtered` is a fact about an IP stored as a fact about a
VISITOR** — that is the design bug at the centre of this plan.

### Locked policy (user decisions — not re-litigated in EXECUTE)

| Policy | Value |
|---|---|
| Automatic attempts | **4 per visitor, LIFETIME.** The first identify counts as attempt #1. |
| Cadence | One attempt per **7 days**, automatic. |
| Per attempt | Selects **ONE** best IP, spends **ONE** resolve call. |
| Cycle with no new untried IP | **SKIPPED** — consumes no attempt. So 4 attempts ⇒ 4 **distinct** IPs. |
| After 4 | Visitor permanently done (columns only, no new status value). |
| Coverage | **EVERY site** — explicitly NOT gated on `auto_identify_enabled`. |
| Manual Retry | **Exempt** from the cap; **never** resets the counter. |
| UI | Counter visible ("tried 3/4") on the visitor list row AND the detail page. |
| Budget | The **existing** 50/site/day identify budget. **No** separate Redis allowance. |

### SPEC decision mapping (user picks supersede SPEC recommendations where they differ)

| SPEC decision | Pick |
|---|---|
| D1 — where IP history lives | **Hybrid** — events scan for "seen", a minimal `tried_ips` record for "tried" |
| D2 — what "best IP" means | **org-kind + relay-exclusion baseline**; fused confidence deferred |
| D3 — 30-day gate | **IP-scoped semantics via a distinct `auto_retry` bypass**; log-DELETE rejected |
| D4 — `vpn_filtered` | **Retryable only on a new non-relay IP** |
| D5 — one owner | **New flag-gated sweep owns it**; revive path subordinated |
| D6 — meter | **SUPERSEDED by user** — shared daily budget, no separate Redis allowance |

---

## Goals / Non-Goals

**Goals**
1. Resolve the visitor's *most resolvable* known IP, not the newest one.
2. Automatically re-open a failed visitor when a genuinely new untried IP appears — bounded to 4
   lifetime attempts at 7-day cadence, on every site.
3. Zero behavior change with the flag off; zero new `identity_status` vocabulary.
4. Keep the footprint in `identity_resolver.py` and `visitor_aggregator.py` **as small as
   correctness allows** (both files are contested by active plans).

> **SUPERSEDED — PVL cycle 1, decision D-A.** The original goal promised **one parameter** in
> `identity_resolver.py`. That promise is withdrawn. It depended on assigning `visitor.ip_address`
> in memory, which VALIDATE proved is a **committed write** corrupting a plaintext PII column (G1).
> The correct fix is a real `override_ip` parameter threaded to `resolve()` **and the five provider
> mixins** — **6 files instead of 1**, explicitly accepted. Reason: correctness on a PII column
> beats footprint minimisation. `visitor_aggregator.py` still takes exactly **one** flag guard.

**Non-Goals** (inherit SPEC §Out Of Scope)
- Provider selection/order/pricing changes.
- Non-IP waterfall checks (fingerprint, cross-tenant graph, email capture) — a retry must not
  re-run them as if they were new evidence.
- `ip_org_lookup_enabled` / fused-confidence dependency (D2-ii) — operator runbook, not this plan.
- Changing the `auto_identify_enabled` default or auto-enrolling sites.
- Per-IP identity-status re-model (D4-C).
- IP encryption / blind-indexing at rest (owned by the held pii-at-rest plan).

---

## Touchpoints

| # | Path | Change | Why |
|---|---|---|---|
| T1 | `apps/api/models/visitor.py` | **+3 columns** on `Visitor` | attempt state |
| T2 | `apps/api/migrations/versions/<new>.py` | **new** additive migration | schema |
| T3 | `apps/api/services/reidentify_ranker.py` | **new** pure module | IP ranking |
| T4 | `apps/api/services/reidentify_sweep_runner.py` | **new** owner module | the sweep |
| T5 | `apps/api/services/identity_resolver.py` | **+2 parameters** (`auto_retry: bool = False`, `override_ip: str \| None = None`) at `:502`; bypass at `:583`; override consumed at `:593`, `:602`, `:611`, `:652`, `:691`, `:695`, `:931` | gate bypass **+ non-persisting IP override** (G1 / D-A) |
| T5b | `apps/api/services/identity_providers/pdl.py:74`, `ipinfo.py:144`, `rb2b.py:182`, `capturify.py:82`, `leadpipe.py:175` | **+1 parameter each** — take `override_ip` instead of reading `visitor.ip_address` | each mixin reads the field itself; the accepted 6-file footprint (D-A) |
| T6 | `apps/api/services/visitor_aggregator.py` | **+1 flag guard** — early-return in `revive_returning_unresolvable` (`:365-431`) | one owner |
| T7 | `apps/api/config.py` | **+1 flag block** (`auto_reidentify_enabled` + interval/cap/cadence constants) | operator gate |
| T8 | `apps/api/jobs/scheduler.py` | **+1 job** registration | cadence |
| T9 | `apps/api/schemas/visitors.py` | expose `auto_reidentify_count` | UI |
| T10 | `apps/web/src/app/dashboard/visitors/page.tsx` | render "tried N/4" near `renderIdentity` (`:360-424`) | UI list |
| T11 | `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` | render "tried N/4" | UI detail |
| T12 | `tests/unit/test_scheduler_job_config.py` | **edit** arithmetic 23→24 / 21→22 + changelog paragraph (`:175-217`) | gate |
| T13 | `tests/unit/test_resolution_deferral_watermark.py` | **strengthen** sweep discovery (`:151-198`) | gate |
| T14 | `tests/integration/test_unresolvable_revive.py` | **flag-parametrise** (`:97-120`) | gate |
| T15 | 3 new test files (see §Verification Evidence) | new | coverage |
| T16 | `tests/unit/test_agent_company_resolution.py` | **edit** — append `apps/api/services/reidentify_sweep_runner.py` to `_AC2_FILES` (`:515-520`) | the AC-8 tripwire cannot discover a new module otherwise (G3) |
| T17 | `apps/api/routers/visitors.py` | **edit** `:911-931` — manual Retry becomes available for `vpn_filtered` when a non-relay untried IP exists | D-C, accepted scope increase (G7) |
| T18 | `apps/api/models/site.py` (+ the same migration as T2) | **+1 column** `auto_reidentify_opt_out Boolean NOT NULL server_default "false"` | per-site opt-out (D-D / G9) |
| T19 | site-settings surface in `apps/web/src/app/dashboard/` (**exact path re-derived at EXECUTE**) | **+1 toggle** bound to `auto_reidentify_opt_out` | D-D UI |
| T20 | `apps/web/src/app/dashboard/visitors/page.tsx:389-392` | render a Retry button on the `vpn_filtered` badge branch (today only `unresolvable` `:395-411` has one) | D-C (G7) |

**Read-only (consulted, never edited):** `apps/api/services/asn_lookup.py:61`,
`apps/api/services/ip_org_ingest.py:116` (`classify_ip_org_kind`),
`apps/api/services/company_resolver.py:233` (`is_privacy_relay_ip`) / `:455` (`_read_company_graph`),
`apps/api/services/resolution_eligibility.py:85-99`,
`apps/api/services/agent_visitor_filters.py:19-65`,
`apps/api/services/promotion_sweep_runner.py` (shape donor),
`apps/api/models/event.py:74` (`ix_events_site_visitor`).

> **EXECUTE rule:** every `path:line` above was verified at plan time on `devjulley`. Three active
> plans hold unexecuted edits to these files. **Re-derive every anchor before editing.**

---

## Public Contracts

| Contract | Change | Compatibility |
|---|---|---|
| `Visitor` ORM | +3 nullable/defaulted columns | additive; no reader breaks |
| DB schema | +3 columns on `visitors` | additive, no index, no constraint, no backfill |
| `IdentityResolver.resolve()` | +2 keyword-only-defaulted params `auto_retry: bool = False`, `override_ip: str \| None = None` | every existing caller unchanged (both default to today's behaviour) |
| 5 provider mixins (`pdl`, `ipinfo`, `rb2b`, `capturify`, `leadpipe`) | +1 defaulted `override_ip` param each | defaulted ⇒ existing callers unchanged |
| `visitors.ip_address` (DB column) | **NEVER written by this feature** | the override is a parameter, not an assignment — gated by `::sweep_does_not_persist_chosen_ip` |
| `identity_status` mutation by the new sweep | `unresolvable` → `vpn_filtered` is REACHABLE via the IPinfo privacy check (`identity_resolver.py:611-620`) when the chosen IP is a v4 relay | disclosed, not new vocabulary; the attempt is still counted and `tried_ips` still appended (G11) |
| `POST /visitors/{id}/retry` (manual) | now accepts `vpn_filtered` visitors when a non-relay untried IP exists (`routers/visitors.py:911-931`) | widened acceptance; no response-shape change (D-C / G7) |
| `Site` ORM + `sites` table | +1 column `auto_reidentify_opt_out` (default **false** ⇒ every-site coverage preserved) | additive; consent escape hatch (D-D / G9) |
| `revive_returning_unresolvable()` | early-return when flag on | flag off ⇒ byte-identical |
| `GET /visitors` + `GET /visitors/{id}` response | +`auto_reidentify_count: int` | additive field |
| `identity_status` vocabulary | **UNCHANGED — no new value** | see §7 below |
| New public functions | `rank_candidate_ips(...)`, `run_reidentify_sweep_once(db)`, `run_reidentify_sweep()` | new surface only |
| Settings | +`auto_reidentify_enabled` (default **False**) + interval/cap/cadence constants | inert by default |

---

## Blast Radius

| Dimension | Value |
|---|---|
| Files changed | **22** — 15 as originally scoped **+7 from PVL cycle 1**: 5 provider mixins (`override_ip`, D-A), `apps/api/routers/visitors.py` (manual `vpn_filtered` retry, D-C), `tests/unit/test_agent_company_resolution.py` (`_AC2_FILES`, G3). `apps/api/models/site.py` + the settings toggle (D-D) are absorbed into the existing model/migration/web touchpoints. |
| Packages | `apps/api` (models, services, migrations, config, jobs, schemas, routers-adjacent), `apps/web` (2 pages), `tests` |
| Risk classes | **schema/data migration**, **identity/PII surface**, **paid-provider spend**, **scheduler** |
| High-risk verdict | YES — schema + budget + identity status. Hybrid-tier gate minimum applies to every area. |
| Contested files | `identity_resolver.py` (**2 params** — see the D-A supersede), `visitor_aggregator.py` (1 guard) |
| PII columns touched | **none written.** `visitors.ip_address` is read-only to this feature by construction (G1) |
| Rollback | flag OFF restores today's behavior with no code revert; migration is additive and down-reversible |

---

## Architecture Decisions

### AD-1 — State lives in three additive columns on `Visitor` (T1/T2)

Follow migration `c2f7a9d31b64` exactly: additive, nullable-or-defaulted, **no index, no
constraint, no backfill** (its docstring `:19-25` justifies this posture).

| Column | Type | Purpose |
|---|---|---|
| `auto_reidentify_count` | `Integer NOT NULL server_default "0"` | lifetime attempts; **MONOTONIC** — no code path resets it |
| `auto_reidentify_next_at` | naive `DateTime NULL` | cadence watermark; NULL = evaluate now |
| `auto_reidentify_tried_ips` | `JSONB NULL` | IPs already spent; ≤4 entries by construction |

Naive datetimes to match `Visitor`'s convention (`resolution_deferred_until` is naive;
`ErasureRequest` is aware — **never mix the two in one comparison**).

**Why JSONB on the visitor row, not a new table:** it inherits the visitor row's EXISTING GDPR
erasure and retention for free — no new erasure target, no new retention rule, no join. The 4-cap
bounds it to four entries. Plaintext adds no new exposure class because `visitors.ip_address` on
the same row already holds a plaintext IP. **This is a reviewable call — flagged for VALIDATE.**

**Retention rule (SPEC AC-13, G12):** the new store's retention **equals the visitor row's own
lifetime — there is no independent retention rule and none is needed.** `auto_reidentify_tried_ips`
is a column on `visitors`, and visitor erasure is a full `DELETE FROM visitors`
(`apps/api/routers/visitors.py:448-474`, verified), so the column cannot outlive its purpose or its
subject. The same holds for the 90-day raw-event purge: the column is bounded to ≤4 entries by the
cap and is never read after exhaustion.

**REJECTED — an `ip_address` column on `ResolutionLog`:** revive DELETEs failed rows, logs are
billing-immutable (`apps/api/routers/visitors.py:1297-1303`), and outage attempts deliberately
write no log row at all (`tests/unit/test_resolution_outcome_taxonomy.py:72`).

### AD-2 — New pure ranker module (T3)

Split like `fuse_org_hypothesis` (`apps/api/services/ip_org_fusion.py:146`): a **PURE** scoring
core over pre-fetched evidence, plus a thin async gatherer living in the sweep runner. **No
DB/network imports at module scope.** Clock injected via optional `now: datetime | None = None`
per the repo idiom (`company_resolver.py:440`, `identity_signals.py:48`,
`job_change_detector.py:533`) — there is no freezegun/time-machine in this repo.

```python
def rank_candidate_ips(
    candidates: list[IpEvidence],
    *,
    tried_ips: frozenset[str],
    now: datetime | None = None,
    weights: Weights = DEFAULT_WEIGHTS,
) -> RankResult:   # {"ranked": [...], "chosen": str | None, "excluded": [...], "evidence": [...]}
```

Returns the FULL ordering plus a chosen index (the recovered `roster_ranking` contract — that file
was **never committed**, only a stale `.pyc` survives, so this is a pattern to **re-derive**, not
code to reuse), so attempt N takes the Nth-ranked untried IP and the decision is auditable.

**Evidence gathering (in the sweep runner, not the ranker):** ONE `GROUP BY ip_address` over
events for the visitor — index-supported by `ix_events_site_visitor`
(`apps/api/models/event.py:74`); index scan then in-memory aggregate. **There is NO index on
`ip_address`, so never write a cross-visitor query keyed on IP alone.** Filter
`NOT is_flagged_abuse`.

Engagement lives on its OWN event rows: `scroll_depth` is non-zero only on `event_type='scroll'`,
`time_on_page` only on `time_on_page` rows (`apps/api/routers/events.py:390-391`). Therefore
aggregate `MAX(scroll_depth)` and `AVG(time_on_page) FILTER (WHERE time_on_page > 0)`, mirroring
`visitor_aggregator.py:306` (`MAX(scroll_depth)`) and `:307` (`AVG(time_on_page)`). **Citation
corrected in PVL cycle 1** — `:313` is `MAX(country_code)`, not the engagement aggregates.

Plus sync `lookup_asn` per IP (`apps/api/services/asn_lookup.py:61` — returns `(asn, org)`, never
raises) → `classify_ip_org_kind` (`apps/api/services/ip_org_ingest.py:116` — returns exactly
`org|eyeball|datacenter|cdn`).

**MANDATORY short-circuit (G8):** when `lookup_asn` returns `asn is None`, the ranker assigns tier
`"unknown"` **directly and never calls `classify_ip_org_kind`**. Without this short-circuit the
ladder silently collapses — see AD-3 for the traced proof. `classify_ip_org_kind` has no `unknown`
branch, so `unknown` exists **only** as a ranker-local tier produced by this short-circuit.

**Blocking-call note (C5):** `lookup_asn` is synchronous. Harmless today (no mmdb ⇒ immediate
return) but it will block the event loop once an mmdb is installed — the exact configuration AD-3's
ladder is designed for. Memoise per tick and wrap in `asyncio.to_thread` if an mmdb ever ships. Plus flag-gated `_read_company_graph`
(`apps/api/services/company_resolver.py:455`) when `company_graph_enabled`.

### AD-3 — Tier ladder: `org` → **`unknown`** → `eyeball` → `cdn` → `datacenter`

`unknown` ranks **SECOND, not last** — but only because of the AD-2 short-circuit. **Rewritten in
PVL cycle 1 (G8); the original rationale argued about a value the pipeline could not produce.**

**Traced proof that the ladder collapses WITHOUT the short-circuit.** With no mmdb:
`asn_lookup.py:68-70` returns `(None, None)` → `classify_ip_org_kind(None, None)`
(`ip_org_ingest.py:116`) builds `f"AS{asn} {org_raw or ''}".strip()` = `"ASNone"` →
`classify_org_kind("ASNone")` (`company_resolver.py:340-353`) finds no digits and no CDN/datacenter
token → returns `"eyeball"` → back in `classify_ip_org_kind`, `"eyeball"` is not in
`("datacenter","cdn")`, `asn` is None so the eyeball-ASN set is skipped, `org_raw` is empty so no
token matches → **`return "org"`**.

So with no mmdb **every IP classifies as `org` — the TOP tier** — the ladder degenerates to a
constant, and only tiebreak keys 2–8 do any work. `classify_ip_org_kind` has **no `unknown` branch
at all**; `unknown` is a ranker-local tier that exists only when the ranker refuses to call it.

**Therefore the short-circuit is load-bearing, not defensive:** `asn is None → "unknown"`, decided
in `reidentify_ranker.py`, before any call into `classify_ip_org_kind`. With the short-circuit in
place the MaxMind `.mmdb` being absent from the repo and CI (`settings.maxmind_asn_db_path` defaults
`""`, `apps/api/config.py:852`) means **every IP is genuinely `unknown`**, and the
`unknown`-ranks-second conclusion becomes real: it encodes "no evidence against it", so the ranker
never prefers a *confirmed* `eyeball` over an unclassified IP that may well be corporate. Ranking
`unknown` last would make the ranker actively WORSE than today's "newest wins" in the CI-default
configuration.

**SPEC supersede (G13/C4):** SPEC Constraint 6 says `org_kind` has **five** values including
`registry`. That is **STALE**. `classify_ip_org_kind` (`ip_org_ingest.py:116-138`) returns exactly
four (`org|eyeball|datacenter|cdn`); `registry` is written only by `ip_org_rir_ingest.py:162`, which
is not on this path. **Do not add a phantom `registry` tier.**

**Nothing is filtered by tier.** With 4 attempts this is a **PRIORITY QUEUE, not a filter** —
`eyeball` still gets its turn. rb2b/leadpipe/capturify query BY IP and *do* resolve residential
addresses to people (landing in the `candidate` tier); PDL IP-Enrich/IPinfo need a corporate IP.

**Note on realism:** datacenter and proxy/VPN IPs are DROPPED AT INGEST
(`block_datacenter_traffic` / `block_proxy_vpn_traffic`, both default True,
`apps/api/config.py:311`/`:320`, enforced `apps/api/routers/events.py:296`/`:307`), so the
realistic tie is org-vs-org or eyeball-vs-eyeball. **Keep the tier cases anyway** — flags can be
flipped and historical rows predate the guard.

### AD-4 — Hard exclusions (never chosen at any rank)

1. already in `tried_ips`
2. `is_privacy_relay_ip(ip)` (`apps/api/services/company_resolver.py:233` — pure; **note it checks
   only ONE prefix `2a09:bac3:`, iCloud v6 only, no v4 coverage**)
3. empty / malformed / private / reserved / loopback
4. all of the IP's events flagged `is_flagged_abuse` or `optout`

### AD-5 — Tiebreak chain (total order; ties impossible)

| # | Key | Direction | Rationale |
|---|---|---|---|
| 1 | tier rank | AD-3 ladder | primary discriminator |
| 2 | prior `company_graph` hit | `source` (`paid_ip` 0.7 > `rdns` 0.5 > `rir_asn` 0.45), then confidence desc; `needs_revalidation` demotes | free prior knowledge |
| 3 | `distinct_days` | desc | an IP seen across many separate days is a **stable location** (office/home), not a one-off cafe. Deliberately AHEAD of raw event count, which a single long session inflates |
| 4 | business-hours ratio | desc | share of events Mon–Fri 08:00–18:00 in the IP's own `country_code` local time. **ABSTAINS** (dropped from numerator AND denominator, the roster_ranking pattern) when `country_code` is NULL/unmappable. This is the key that rescues a small company on a business DSL line the ASN calls `eyeball`. `country_code` is denormalised on the event row at ingest — **never call `resolve_geoip` in a ranker** |
| 5 | engagement | `has_conversion` > `has_click` > `MAX(scroll_depth)` desc > `AVG(time_on_page) FILTER (>0)` desc | intent |
| 6 | `pageview_count` | desc | volume |
| 7 | `last_seen` | desc | recency as a **LATE** key: a stale office IP identifies the company better than a fresh mobile IP |
| 8 | lexical `ip` | asc | final key — guarantees totality |

**Ordering is RECOMPUTED every cycle, not frozen.** Evidence changes as events arrive and age out
of the 90-day window, so attempt 3 should use current evidence. `tried_ips` is monotonic, so an IP
passed over at attempt 2 can win at attempt 3 if its evidence improved. **Intended behaviour.**

### AD-6 — New sweep owner (T4)

Shaped on `apps/api/services/promotion_sweep_runner.py`: own `_SWEEP_LOCK_KEY`,
`pg_try_advisory_lock(hashtext(:key))` returning True/False/None-when-unsupported → **FAIL OPEN**
(`:152-174`); the `run_X_once(db)` (injected session, returns counters dict) + `run_X()` (own
session, re-checks the flag, takes the lock, releases in `finally`) split (`:177-201`); per-row
`try/except/continue` (`:114-124`).

```
-- PER-SITE PRE-CHECK, before this query runs at all (D-B / G4):
--   skip the whole site this tick when
--   get_resolution_attempts_today(db, site_id) >= 0.70 * get_site_daily_budget(db, site_id)

WHERE site_id = :site
  AND identity_status IN ('unresolvable', 'vpn_filtered')   -- invisible to both existing sweeps
  AND auto_reidentify_count < 4                             -- exhaustion gate, IN-QUERY
  AND auto_reidentify_skip_count < 8                         -- perpetual-skipper retirement (G5)
  AND resolution_defer_count = 0                             -- makes outage detection exact (G2)
  AND (auto_reidentify_next_at IS NULL OR auto_reidentify_next_at <= :now)
  AND do_not_resolve IS false
  AND <site.auto_reidentify_opt_out IS false>                -- per-site opt-out (D-D / G9)
  AND <resolution_not_deferred_filter()>
  AND <human_only_visitor_filter()>
  AND <resolution_candidate_filter(...)>                    -- intent floor, reuse verbatim
ORDER BY auto_reidentify_next_at ASC NULLS LAST, intent_score DESC
LIMIT 20
```

**`resolution_defer_count = 0` is MANDATORY (G2).** It is what makes the AD-8 outage test exact.
Without it, a visitor whose defer counter has reached `len(RESOLUTION_DEFER_BACKOFF)` (4) takes the
exhaustion path at `identity_resolver.py:722` — the increment at `:723` is skipped and `:750`
**resets the counter to 0** — so `after(0) > before(4)` is False and a pure outage is recorded as a
real consumed attempt, permanently blacklisting an IP no provider ever saw. Reachable after ~31h of
outage. The same predicate also removes the second, undecidable case: `before > 0, after == 0` is
produced by BOTH exhaustion-outage AND a genuine no-match, and no single-integer comparison can
separate them. Pinning `before = 0` collapses both.

**ORDER BY rewritten (G4/G5).** The original "never-attempted first" ordering is **DELETED as
vacuous**: the main sweep selects `('anonymous','candidate')`
(`apps/api/services/resolution_runner.py:135`) and this sweep selects `('unresolvable',
'vpn_filtered')` — **provably disjoint**, so ordering inside this sweep could never protect
first-time identifies, and `count = 0` at the front of the queue is exactly the perpetual-skipper
cohort (G5). The replacement key is due-time ASC: oldest-due first, which is starvation-free within
the sweep and does not privilege never-attempted rows.

**The real contention is the shared 50/site/day budget** — `check_daily_budget`
(`identity_resolver.py:589`) → `usage_limits.py:86-89`, a per-site distinct-visitor counter consumed
first-come-first-served by BOTH sweeps. The per-site pre-check above is the mechanism: this sweep
**refuses to run for a site once 70% of the day's budget is already used**, reserving the remainder
for first-time identifies.

> **70% is an explicitly-labelled PLACEHOLDER, to be tuned from measured per-site data before any
> prod flag flip** — exactly the posture the repo already uses for `job_change_recheck_daily_cap`.
> Do not treat it as a validated threshold.

**Perpetual-skipper retirement (G5).** The exhaustion gate is `auto_reidentify_count < 4` and the
skip path leaves `count` unchanged, so a visitor with exactly **one** IP forever (the majority of
terminally-failed visitors) would never leave the WHERE clause — re-evaluated every 7 days for the
life of the site, each evaluation costing a per-visitor `GROUP BY ip_address` scan, N `lookup_asn`
calls and a `_read_company_graph` read. Fix: a fourth additive column
`auto_reidentify_skip_count Integer NOT NULL server_default "0"`, incremented on every SKIP, with
its own bound (`< 8`, i.e. ~56 days of futile evaluation) as a WHERE term. Interaction with the
budget reserve: a retired skipper consumes neither a budget slot nor a sweep row, so retirement
**increases** the headroom the D-B reserve protects.

**Honest restatement of the "4 attempts ⇒ 4 DISTINCT IPs" promise (G5, second-order).** That promise
holds **only when new IPs arrive at ≥7-day intervals**. A visitor who accumulates three new IPs
inside one 7-day window gets exactly one tried; the other two are deferred to later cycles, and
because the ranking is recomputed every cycle (AD-5) the recomputed order may pass them over
entirely. The guarantee is therefore "≤4 attempts, each on a distinct IP", **not** "the 4 best IPs
are all tried".

**Dormant second sweep (G14).** SPEC Constraint 5 names a dormant Celery-beat twin
(`apps/api/tasks/resolution_tasks.py:78-99`, LIMIT 50). It needs **no query-semantics change**: its
status set is disjoint from this sweep's. It does, however, share the same 50/site/day budget, so if
it is ever revived it must be counted in the D-B reserve.

**All new gates are COLUMNS IN THE WHERE CLAUSE. Mandatory, not stylistic.** Sweep starvation is
a PROVEN, already-reverted trap: both sweeps order `intent_score DESC` under a LIMIT and
retry-eligible visitors keep gaining intent, so they park at the top of every batch and crowd out
new visitors. A Redis circuit-breaker was written, tested green, and **REVERTED ON LIVE EVIDENCE**
for exactly this (`plans/260805-1543-identity-coverage-recovery/phase-05-outage-deferral-watermark.md`).
The `resolution_not_deferred_filter()` docstring (`apps/api/services/resolution_eligibility.py:85-99`)
says it plainly: *"otherwise 'retryable' degrades into 'retried on every single sweep'."*

**Mandatory PRE-CHECKS before an attempt is consumed (G2b).** `resolve()` returns `None` on five
paths that touch **neither** deferral column: `do_not_resolve` (`:548-550`), suppression
(`:557-559`), **budget** (`:589-591`), privacy relay (`:602-610`), IPinfo VPN (`:611-622`). The
budget one is the dangerous one and it is the **common** case, not the rare one:

> The main sweep exhausts a site's 50/day by 09:00. The retry sweep runs at 09:30, picks IP `B`,
> `resolve()` returns `None` at `:591` with **zero provider calls** — and the naive accounting counts
> a real attempt and blacklists `B`. Repeat on days 7/14/21 → `count = 4`, all four IPs permanently
> blacklisted, **no provider ever contacted.** The feature annihilates itself on exactly the busy
> sites that need it.

Therefore the sweep **pre-checks `check_daily_budget`, `do_not_resolve`, and the suppression list
itself, BEFORE calling `resolve()`**. An attempt is consumed and `tried_ips` appended **only when the
chosen IP was actually sent to a provider.** A pre-check miss is a SKIP (see AD-8).

**No `auto_identify_enabled` site gate** (user chose every-site coverage). **Stated consequence:**
sites that deliberately left auto-identify OFF (`apps/api/models/site.py:28-30`, default False)
would begin spending their daily identify budget automatically. **Mitigated in PVL cycle 1 by D-D:**
a per-site `auto_reidentify_opt_out` column + settings toggle, **default false** — so every-site
coverage remains the default and the column is the consent escape hatch, not an opt-in gate.
Remaining controls unchanged: the feature's own default-OFF global flag, the per-site 50/day budget
(now with the D-B reserve), `do_not_resolve` per visitor.

Including `vpn_filtered` in the status set **IS** the D4-B behaviour — the ranker already refuses
privacy-relay IPs, so such a visitor is only picked up when a non-relay untried IP exists. No extra
query logic. **The manual endpoint is NO LONGER left unchanged (D-C / G7) — see AD-11.**

### AD-7 — Two new parameters on `resolve()` (T5, T5b)

**Parameter 2, `override_ip: str | None = None`, was added in PVL cycle 1 (D-A) — see AD-8.**

`auto_retry: bool = False` on `IdentityResolver.resolve()`
(`apps/api/services/identity_resolver.py:502`), bypassing **exactly the same line** as
`force_retry` (`:583`) and **nothing else**. A separate flag, not a reuse, so the automatic and
human lanes stay independently auditable — which "manual Retry is exempt from the cap" requires.

`force_retry` was verified to affect EXACTLY ONE branch (defined `:506`, docstring `:532-537`,
single use `:583`). It does **NOT** bypass `do_not_resolve` (`:550`), suppression (`:559`), budget
(`:589`), no-IP (`:593`), privacy relay (`:602`), IPinfo VPN (`:612`), or the Redis IP cache
(`:651-664`).

**The outage hazard is closed by the SWEEP QUERY, not the parameter:**
`resolution_not_deferred_filter()` means a deferred visitor is never selected, so automated
attempts cannot drive `resolution_defer_count` to exhaustion. Without that filter, automated
retries during a provider outage would push visitors to defer-exhaustion → `unresolvable`,
re-introducing the exact bug the watermark exists to fix.

One parameter is also the smallest possible footprint on a file that has been rewritten three
times in one week.

### AD-8 — Attempt accounting

**Restated in PVL cycle 1 (G2, G10).**

| Situation | `count` | `skip_count` | `next_at` | `tried_ips` |
|---|---|---|---|---|
| Ranker found a new untried IP → `resolve()` actually issued to a provider | **+1** | unchanged | `now + 7d` | append the IP |
| No new untried IP (evaluated, skipped) | unchanged | **+1** | `now + 7d` | unchanged |
| **PRE-CHECK miss** — budget exhausted / `do_not_resolve` / suppressed (no provider call made) | unchanged | **+1** | `now + 7d` | **unchanged** |
| `resolve()` returned None because of an OUTAGE DEFER | unchanged | unchanged | unchanged | unchanged |
| The call raised | unchanged | unchanged | **`now + backoff`** (G10) | unchanged |

**Outage detection is now EXACT, not heuristic.** Because AD-6's WHERE clause pins
`resolution_defer_count = 0` at selection time, `before` is **always 0**, so "the deferral branch
fired" is simply `after > 0`. The two defects that killed the old before/after comparison are gone
by construction: the exhaustion path (`identity_resolver.py:722` False → `:750` resets to 0) cannot
be entered from this sweep, and the undecidable `before > 0, after == 0` state cannot occur.
**Writer census (complete, verified): exactly two writers — `identity_resolver.py:721-723`
(increment) and `:750` (reset).**

**Exception path (G10):** an exception is our fault, not evidence about the IP, so it consumes no
attempt and appends no IP — but it **must advance `next_at` by a backoff**, otherwise a
deterministic exception (malformed evidence, provider client bug) re-selects the same visitor on
every sweep tick forever, re-running the evidence `GROUP BY` and the ranker each time. Gate:
`::exception_advances_next_at`.

Setting `next_at` on the **SKIP** path too means each visitor is evaluated at most once per 7 days
— precisely the stated policy, bounded work, no magic number.

**The chosen IP reaches the providers via an explicit `override_ip` PARAMETER. `visitor.ip_address`
is NEVER assigned.** (Rewritten in PVL cycle 1 — decision D-A, closing G1.)

**Why the old design was wrong.** `IdentityResolver(db)` shares the sweep's `AsyncSession`, so
`visitor` is a **session-attached** ORM object; `visitor.ip_address = chosen` marks the attribute
dirty and the next `commit()` flushes `UPDATE visitors SET ip_address = …`. `resolve()` commits on
**every** exit path — `identity_resolver.py:596`, `:609`, `:621`, `:735`, `:752`. Proof by analogy
from the same file: `:595-596` assigns `identity_status` then commits, and `:686-687` assigns
`company_domain` then commits — both persist by exactly this mechanism. So the "in-memory override"
was a **committed write silently corrupting a plaintext PII column**.

**And the corruption is PERMANENT for the target population.** With
`aggregation_incremental_enabled=False` (`config.py:127`) a full recompute would rewrite
`ip_address` (`visitor_aggregator.py:315`) — but a terminally-failed visitor who stops visiting is
never recomputed. With the incremental flag ON, `_INCREMENTAL_SET["ip_address"]` is
`COALESCE(EXCLUDED.ip_address, visitors.ip_address)` (`:619`) and a visitor with no events in the
window is not in the result set at all.

Corrupted-state blast radius (recorded so the severity is not re-litigated):
`visitor_aggregator.py:756-774` (`_resolve_companies` would resolve the WRONG IP into
`company_domain`), `routers/visitors_helpers.py:263` (customer-facing skip reason),
manual Retry (`routers/visitors.py:912-914` → `resolve(force_retry=True)` would resolve the sweep's
stale IP), and `identity_resolver.py:652` (the Redis key `beam:resolution:{ip}`).

**The fix (accepted 6-file footprint):** thread `override_ip` to `resolve()` and to the five provider
mixins that read the field themselves — `identity_providers/pdl.py:74`, `ipinfo.py:144`,
`rb2b.py:182`, `capturify.py:82`, `leadpipe.py:175`. Inside `resolve()` the effective IP
(`override_ip or visitor.ip_address`) is used at `:593`, `:602`, `:611`, `:652`, `:691`, `:695` and
passed through `_resolve_ip_company_parallel` (`:931`). **No assignment to `visitor.ip_address`
anywhere.** Gated by `::sweep_does_not_persist_chosen_ip`, which asserts the DB row is unchanged on
the success, outage **and** exception paths.

### AD-9 — Subordinating the incumbent (T6)

`revive_returning_unresolvable` (`apps/api/services/visitor_aggregator.py:365-431`, snapshot
`:345-362`, read `:467`, invoked `:521`) becomes a **NO-OP EARLY-RETURN when the flag is on**.
Flag off → today's behaviour byte-for-byte. Flag on → exactly one owner, and its failed-log DELETE
at `:417-423` stops firing, which is what lets `tried_ips` mean anything.

Context to record: revive today triggers on `pre_snapshot.get(vid) != new_ip` (`:402`, plain
Python `!=`, fires in BOTH directions including real→NULL), is scoped to
`identity_status == "unresolvable"` only (`:356`), has NO counter and NO cadence, fires on EVERY
rollup (far more often than 30 min), commits in a SEPARATE transaction from the rollup (rollup
commits `:517`, revive commits `:424`). **Citation corrected (PVL cycle 1):** `:389-390` is the
**empty-snapshot early return**, not a fail-open; the only fail-open is `:428-431`.

### AD-10 — Terminal marker: COLUMNS ONLY, no new `identity_status` value

Exhaustion is `auto_reidentify_count >= 4` in the sweep's WHERE. **No new status value**, because
two existing readers fail OPEN in the wrong direction:

| Reader | Anchor | Breakage if a new value existed |
|---|---|---|
| Visitor detail page | `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx:466-469` | `identified = status !== "anonymous" && !== "unresolvable" && !== "vpn_filtered"` → new value makes `identified === true`, **ENABLING OSINT** (`canOsint` `:483`) and switching the whole page layout |
| Browser breakdown | `apps/api/services/browser_breakdown.py:125` | counts `not in ("anonymous","")` as IDENTIFIED → inflates the chart |
| Traffic fit | `apps/api/services/traffic_fit.py:116` | same → inflates the chart |
| Promotion sweep | `apps/api/services/promotion_sweep_runner.py:95` (`not_in(_TERMINAL_STATUSES)`; the tuple literal `("identified","merged")` is at **`:49`**) | would re-sweep it forever |
| Job-change detector | `apps/api/services/job_change_detector.py:555` | `!= "anonymous"` would pull it into the staleness sweep |

**Zero vocabulary blast radius by using columns.**

### AD-11 — UI (T9/T10/T11)

Expose `auto_reidentify_count` on the visitor schema and render **"tried N/4"** on the list row
(`apps/web/src/app/dashboard/visitors/page.tsx`, near the `renderIdentity` if-chain at `:360-424`)
and the detail page. Manual Retry stays available on an exhausted visitor and **neither consumes
nor resets** the counter.

**Manual Retry extended to `vpn_filtered` (D-C, closing G7) — accepted scope increase.** Today
`routers/visitors.py:911-931` sets `is_retry` only for `unresolvable`; `vpn_filtered` falls through
to `:930-931` ("Already processed."), and the UI renders a bare badge at
`apps/web/src/app/dashboard/visitors/page.tsx:389-392` with no Retry button (only the `unresolvable`
branch at `:395-411` has one). So an exhausted `vpn_filtered` visitor has **no auto path**
(`count < 4` fails) **and no manual path** — precisely the population this feature exists for.
Change: a `vpn_filtered` visitor is manually retryable **when a non-relay untried IP exists**
(same predicate the ranker already computes), and the UI renders the Retry button on that branch.
Manual Retry remains exempt from the cap and still never resets the counter.

`?reset=true` (`apps/api/routers/visitors.py:1296-1308`) is **LEFT ALONE**: it flips rows to
`anonymous`, which removes them from this sweep's status set and returns them to the main sweep as
fresh — pre-existing behaviour, and the counter is not bypassed because this sweep only owns the
terminal statuses.

### AD-14 — Per-site opt-out (T18/T19, D-D, closing G9)

`sites.auto_reidentify_opt_out Boolean NOT NULL server_default "false"`, added in the **same
additive migration** as the visitor columns (T2), plus a settings toggle (T19) and a WHERE-clause
term in AD-6.

**Default false ⇒ every-site coverage is preserved exactly as the user locked it.** This column is
the *consent escape hatch* for a site that deliberately runs with `auto_identify_enabled=False`, not
an opt-in gate. Gate: `::opt_out_site_never_selected`.

### AD-12 — Flag + scheduler (T7/T8)

`auto_reidentify_enabled: bool = False` in `apps/api/config.py`, following the house block style
(`:622-647` promotion sweep, `:722-731` ip-org): a `# ─── Title (program) ───` section header,
multi-paragraph rationale, default-OFF posture stated with precedents named ("identity-status
mutation is a high-risk class, so enabling it is an explicit operator act"). Plus
`auto_reidentify_interval_minutes` and the cadence/cap constants.

Scheduler: thin wrapper in `apps/api/jobs/scheduler.py` (lazy import inside, try/except →
`logger.exception`, pattern at `:326-339`), registered inside `if settings.auto_reidentify_enabled:`
(pattern at `:724-735`), with explicit `id`, literal positive `jitter` and `misfire_grace_time`,
and a **boot offset that must stay SMALLER than `aggregation_sweep`'s 90s**
(`tests/unit/test_scheduler_job_config.py:80-100`).

### AD-13 — Migration (T2)

Additive, no backfill, following `c2f7a9d31b64`. **Re-derive the LIVE head at EXECUTE** with
`DATABASE_URL` pinned to `localhost:5433` — the repo `.env` points at Supabase PROD and
`apps/api/migrations/env.py` has **NO local-host guard**. Prod head is `c4a8f13e07b6`; `devjulley`
has moved past it (a file-level parse suggests `d3f9a1c25e84` but was **NOT conclusive** across
the 70 version files — **DERIVE IT LIVE, do not hardcode**). Prove a down/up round-trip on a
disposable Postgres.

---

## High-level Data Flow

```
APScheduler (every N min, flag ON)
   └─► run_reidentify_sweep()                       [new module, own advisory lock, fail-open]
         └─► run_reidentify_sweep_once(db)
               ├─ SELECT ≤20 visitors  (status IN unresolvable|vpn_filtered
               │                        AND count < 4 AND next_at due
               │                        AND not deferred AND human-only AND intent floor)
               │                        ORDER BY never-attempted first, intent DESC
               ├─ PER-SITE RESERVE PRE-CHECK (D-B):
               │    attempts_today >= 0.70 * site_daily_budget ──► SKIP THE WHOLE SITE this tick
               └─ per visitor (try/except/continue):
                    ├─ PRE-CHECKS (consume nothing): check_daily_budget / do_not_resolve /
                    │    suppression ──► SKIP: next_at=now+7d, skip_count+=1, count + tried_ips unchanged
                    ├─ GROUP BY ip_address over events   [ix_events_site_visitor, NOT is_flagged_abuse]
                    ├─ asn is None ──► tier "unknown"     [SHORT-CIRCUIT; classify_ip_org_kind NOT called]
                    ├─ lookup_asn → classify_ip_org_kind  [sync, never raises]
                    ├─ _read_company_graph                [only if company_graph_enabled]
                    ├─ rank_candidate_ips(...)            [PURE — tiers, exclusions, 8-key tiebreak]
                    ├─ chosen is None ──► SKIP: next_at=now+7d, skip_count+=1, count unchanged
                    └─ chosen ────────► await resolver.resolve(..., auto_retry=True,
                                                               override_ip=chosen)
                                        (visitor.ip_address is NEVER assigned — G1)
                                        defer_count went 0 → >0 ──► OUTAGE: nothing changes
                                        raised ──────────────────► next_at = now + backoff only
                                        else ────────────────────► count += 1
                                                                   next_at  = now + 7d
                                                                   tried_ips.append(chosen)
```

Flag OFF ⇒ the job is never registered, `revive_returning_unresolvable` behaves exactly as today,
`resolve()` is called with `auto_retry` defaulted False, and the three columns sit unread.

---

## Phase Completion Rules

A phase is complete ONLY when all five hold:

1. **Integration test** — works end-to-end with the pieces around it.
2. **Manual test** — a human (or agent probe) can observe the intended behavior.
3. **Database/state check** — the three columns actually hold the values the accounting table says.
4. **Error handling** — outage, exception, missing mmdb, missing `country_code`, empty candidate
   set all behave as specified (fail-safe, no attempt consumed).
5. **User confirmation** — the user confirms it works before any `✅ VERIFIED` marker is written.

Status markers: ⏳ PLANNED · 🔨 CODE DONE · 🧪 TESTING · ✅ VERIFIED · 🚧 BLOCKED.
**Never** mark ✅ VERIFIED on "build succeeds" / "no type errors" / "files created".

---

## Implementation Checklist

### Phase-01 — Schema (T1, T2) — ⏳ PLANNED

- [ ] 1.1 Add the **4** columns to `Visitor` in `apps/api/models/visitor.py` (types per AD-1 +
      `auto_reidentify_skip_count Integer NOT NULL server_default "0"` per AD-6/G5; naive
      datetimes; no index, no constraint).
- [ ] 1.1b Add `auto_reidentify_opt_out Boolean NOT NULL server_default "false"` to `Site`
      (`apps/api/models/site.py`) per AD-14 / D-D.
- [ ] 1.2 Derive the live alembic head: `DATABASE_URL=postgresql+asyncpg://…localhost:5433/…
      .venv/bin/python -m alembic -c apps/api/alembic.ini heads`. **Do not hardcode a head.**
- [ ] 1.3 Write the additive migration chained off that head, docstring modelled on
      `c2f7a9d31b64:19-25` (why no index / no backfill).
- [ ] 1.4 Prove down/up round-trip on a **disposable** Postgres (never the shared dev container).
- [ ] **Test gate 1:** `.venv/bin/python -m pytest tests/unit -m unit -q` green;
      migration up→down→up clean.

### Phase-02 — Pure ranker (T3, new unit test) — ⏳ PLANNED

- [ ] 2.1 Create `apps/api/services/reidentify_ranker.py`: `IpEvidence`, `Weights`,
      `DEFAULT_WEIGHTS`, `RankResult`, `rank_candidate_ips`. **No DB/network imports at module
      scope.** Clock via `now: datetime | None = None`.
- [ ] 2.2 Implement hard exclusions (AD-4) — tried, privacy relay, malformed/private/reserved/
      loopback, all-events-flagged.
- [ ] 2.3 Implement the tier ladder (AD-3) with `unknown` **second**, and the **mandatory
      `asn is None → "unknown"` SHORT-CIRCUIT — never call `classify_ip_org_kind` with `asn=None`**
      (G8: it returns `"org"` for `(None, None)`, collapsing the ladder to a constant). Add an
      inline comment carrying the traced proof so it survives future edits.
- [ ] 2.4 Implement the 8-key tiebreak chain (AD-5), including the business-hours **abstain** rule
      (drop from numerator AND denominator on NULL/unmappable `country_code`).
- [ ] 2.5 Write `tests/unit/test_reidentify_ranker.py` — table-driven, **no DB and no mmdb** (so the
      `unknown`-tier default is the case actually exercised). Assert total ordering by
      **PERMUTING the input list and requiring identical output**.
- [ ] **Test gate 2:** `.venv/bin/python -m pytest tests/unit/test_reidentify_ranker.py -q` green.

### Phase-03 — Resolver parameter (T5) — ⏳ PLANNED

- [ ] 3.1 Re-derive anchors `:502`, `:506`, `:532-537`, `:583` (file contested — three active plans).
- [ ] 3.2 Add `auto_retry: bool = False` to `resolve()`; bypass `was_recently_attempted` at the
      **same single line** as `force_retry`; extend the docstring stating it bypasses that line and
      **nothing else**.
- [ ] 3.3 Add `override_ip: str | None = None` to `resolve()` (D-A / G1). Use
      `override_ip or visitor.ip_address` at `:593`, `:602`, `:611`, `:652`, `:691`, `:695` and pass
      it through `_resolve_ip_company_parallel` (`:931`). **Assert by review that no code path
      assigns `visitor.ip_address`.**
- [ ] 3.4 Thread `override_ip` into the five provider mixins — `identity_providers/pdl.py:74`,
      `ipinfo.py:144`, `rb2b.py:182`, `capturify.py:82`, `leadpipe.py:175` — defaulted so every
      existing caller is unchanged.
- [ ] **Test gate 3:** `.venv/bin/python -m pytest tests/unit/test_identity_resolver_parallel.py -q`
      green (incl. the `deterministic_only` invariant at `:745-759`).

### Phase-04 — Sweep runner (T4, 2 new tests) — ⏳ PLANNED

- [ ] 4.1 Create `apps/api/services/reidentify_sweep_runner.py` on the
      `promotion_sweep_runner.py` shape: `_SWEEP_LOCK_KEY`, advisory lock fail-open,
      `run_reidentify_sweep_once(db)` + `run_reidentify_sweep()`, per-row try/except/continue.
- [ ] 4.2 Write the selection query per AD-6. **Both new gates as columns in the WHERE clause.**
      Reuse `resolution_not_deferred_filter()`, `human_only_visitor_filter()`,
      `resolution_candidate_filter(...)` verbatim.
- [ ] 4.3 Write the `ORDER BY` as `auto_reidentify_next_at ASC NULLS LAST, intent_score DESC`
      (G4/G5 — the old "never-attempted first" ordering is DELETED as vacuous and actively harmful).
      **Never introduce `jsonb_array_length(auto_reidentify_tried_ips)` into any ORDER BY** — that
      would turn R2's harmless unindexed JSONB read into a computed sort over the whole filtered
      candidate set before LIMIT (execute-agent instruction E4).
- [ ] 4.3b Add `resolution_defer_count = 0`, `auto_reidentify_skip_count < 8`, and the
      `site.auto_reidentify_opt_out IS false` join term to the WHERE clause (G2 / G5 / G9).
- [ ] 4.3c Implement the **per-site budget reserve** (D-B / G4): skip the whole site this tick when
      `get_resolution_attempts_today(db, site_id) >= 0.70 * get_site_daily_budget(db, site_id)`.
      **Label the 0.70 as a PLACEHOLDER in code, to be tuned from measured data** — mirror the
      wording used for `job_change_recheck_daily_cap`.
- [ ] 4.3d Implement the **pre-checks** (G2b): `check_daily_budget`, `do_not_resolve`, and the
      suppression list are evaluated BEFORE `resolve()` is called. A miss is a SKIP — no attempt
      consumed, **no `tried_ips` append**.
- [ ] 4.4 Implement the async evidence gatherer: one `GROUP BY ip_address` (`NOT is_flagged_abuse`),
      `MAX(scroll_depth)`, `AVG(time_on_page) FILTER (WHERE time_on_page > 0)`, `distinct_days`,
      `pageview_count`, `last_seen`, `country_code`; then `lookup_asn` → `classify_ip_org_kind`;
      then flag-gated `_read_company_graph`.
- [ ] 4.5 Implement attempt accounting per AD-8: exact outage check (`before` is 0 by WHERE-clause
      construction ⇒ outage is `after > 0`), `override_ip=chosen` passed to `resolve()`,
      **no assignment to `visitor.ip_address` anywhere**, `skip_count` increment on every SKIP, and
      a `next_at` backoff advance on the exception path (G10).
- [ ] 4.6 Log keys/ids/counts only — **never an IP, never an email** (SPEC AC-10).
- [ ] 4.7 Write `tests/unit/test_reidentify_sweep.py` — counter accounting incl. the outage
      non-increment, exception non-increment, skip path setting `next_at` without incrementing.
- [ ] 4.8 Write `tests/integration/test_reidentify_sweep.py` — full cycle, cap enforcement, 7-day
      gate, skip-no-new-IP, `vpn_filtered` pickup, **agent-origin exclusion in the new status set**,
      `do_not_resolve`, `::opt_out_site_never_selected`, `::retries_do_not_exhaust_first_identify_budget`,
      `::sweep_does_not_persist_chosen_ip` (DB `ip_address` unchanged on success / outage / exception),
      `::erasure_removes_tried_ips`.
- [ ] 4.9 **EDIT** `tests/unit/test_agent_company_resolution.py:515-520` — append
      `apps/api/services/reidentify_sweep_runner.py` to `_AC2_FILES` (G3). The plan previously cited
      `tests/unit/test_agent_origin_exclusion.py:236-247`, which asserts a **different literal**
      (`source_agent_visit_id`) and would never have covered this module.
- [ ] **Test gate 4:** both new files green; `.venv/bin/python -m pytest tests/unit -m unit -q` green.

### Phase-05 — Flag, scheduler, revive subordination (T6, T7, T8, T12, T13, T14) — ⏳ PLANNED

- [ ] 5.1 Add the config block (AD-12) with a `# ─── … ───` header and multi-paragraph rationale.
- [ ] 5.2 Add the early-return flag guard at the top of `revive_returning_unresolvable`
      (`visitor_aggregator.py:365`). **One guard, nothing else in this file.**
- [ ] 5.3 Register the scheduler job inside `if settings.auto_reidentify_enabled:` with explicit
      `id`, positive literal `jitter`/`misfire_grace_time`, and a boot offset **< 90s**.
- [ ] 5.4 **EDIT** `tests/unit/test_scheduler_job_config.py:213-217` → 24 add_job / 22 interval,
      and append a provenance paragraph to the running changelog docstring at `:175-210`.
      **Do not relax the gate.**
- [ ] 5.5 **STRENGTHEN** `tests/unit/test_resolution_deferral_watermark.py:151-198`: extend
      `_sweeps()` discovery to cover `unresolvable`/`vpn_filtered` status literals so the new sweep
      cannot skate under the `identity_status == "anonymous"` string match, then assert the new
      sweep contains `resolution_not_deferred_filter()`.
- [ ] 5.6 **FLAG-PARAMETRISE** `tests/integration/test_unresolvable_revive.py:97-120`: flag OFF ⇒
      today's assertions unchanged; flag ON ⇒ revive inert and the new sweep owns the behavior.
- [ ] **Test gate 5:** `.venv/bin/python -m pytest tests/unit -m unit -q` and
      `.venv/bin/python -m pytest tests/ -m integration -q` both green.

### Phase-06 — UI counter (T9, T10, T11) — ⏳ PLANNED

- [ ] 6.1 Add `auto_reidentify_count: int` to the visitor list/detail schema. **Put it on the class
      the endpoint actually serialises** — the `VisitorOut` vs `VisitorDetailOut` mistake caused a
      P0 500 (see `all-context.md` §Open Questions). List + detail both need it ⇒ base class.
- [ ] 6.2 Render "tried N/4" on the list row near `renderIdentity` (`page.tsx:360-424`).
- [ ] 6.3 Render "tried N/4" on the detail page.
- [ ] 6.4 Confirm Manual Retry is still offered on an exhausted visitor and neither consumes nor
      resets the counter.
- [ ] 6.5 (D-C / G7) Extend the manual retry endpoint (`apps/api/routers/visitors.py:911-931`) to
      accept `vpn_filtered` when a non-relay untried IP exists, and render the Retry button on the
      `vpn_filtered` badge branch (`apps/web/src/app/dashboard/visitors/page.tsx:389-392`).
- [ ] 6.6 (D-D / G9) Add the `auto_reidentify_opt_out` toggle to the site-settings surface
      (re-derive the exact path at EXECUTE) and confirm the default is OFF (⇒ coverage preserved).
- [ ] **Test gate 6:** `.venv/bin/python -m pytest tests/ -m integration -q` green (the
      `GET /visitors` shape regression is covered here); manual browser check of both surfaces.

### Phase-07 — Full regression + rollout gate — ⏳ PLANNED

- [ ] 7.1 Full unit lane green with the flag **unset** (flag-off byte-identical, SPEC AC-12).
- [ ] 7.2 Full integration lane green with the flag unset, then again with the flag on.
- [ ] 7.3 **Rollout gate (see §Measurement Gap):** run the read-only distinct-IPs-per-visitor
      measurement against real data BEFORE any prod flag flip.

---

## Verification Evidence

Commands (repo-verified):
- unit — `.venv/bin/python -m pytest tests/unit -m unit -q`
- integration — `.venv/bin/python -m pytest tests/ -m integration -q`
- integration precondition — `docker compose -f infra/docker-compose.yml up -d postgres redis`
  (Postgres **5433**, Redis **6379**)
- **`which docker` LIES on this machine** — the CLI is at
  `/Applications/Docker.app/Contents/Resources/bin/docker`; detect by port with
  `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`
- **Never bare `pytest`** — always `.venv/bin/python -m pytest`

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_reidentify_ranker.py::org_over_eyeball` — org-tier IP outranks eyeball | Fully-Automated | AC-1 (best IP wins) |
| `tests/integration/test_reidentify_sweep.py::best_ip_selection` — seeded events, attempted IP is the office IP | Hybrid (needs PG) | AC-1 |
| `test_reidentify_ranker.py::relay_excluded` — relay IP never chosen when a non-relay exists | Fully-Automated | AC-2 (relays never chosen) |
| `test_reidentify_ranker.py::unknown_ranks_second` — with the AD-2 short-circuit in place, `unknown` outranks `eyeball` | Fully-Automated | AC-1 (**non-vacuous only because of the short-circuit — see G8**) |
| `test_reidentify_ranker.py::total_order_under_permutation` — permuted input ⇒ identical output | Fully-Automated | AC-1/AC-2 (determinism) |
| `tests/integration/test_reidentify_sweep.py::new_ip_revives` — untried IP B re-opens a failed visitor with no manual action | Hybrid (needs PG) | AC-3 (new untried IP re-opens) |
| `tests/integration/test_reidentify_sweep.py::tried_ip_not_looped` — an IP in `tried_ips` is never re-attempted | Hybrid (needs PG) | AC-4 (tried IPs not looped) |
| `tests/integration/test_reidentify_sweep.py::vpn_filtered_pickup` — picked up only on a new non-relay IP; never for a new relay | Hybrid (needs PG) | AC-5 (D4-B behaviour) |
| `tests/integration/test_resolution_budget.py::TestResolutionAttemptCounting::test_counts_distinct_visitors_not_rows` (`:59-67`) **must stay green** | Fully-Automated | AC-6 (budget non-regression) |
| `tests/unit/test_identity_resolver_parallel.py:745-759` — `deterministic_only=True` ⇒ `check_daily_budget.assert_not_called()` + `_resolve_identity_graphs_parallel.assert_not_called()` **must stay green** | Fully-Automated | AC-6 |
| `tests/integration/test_reidentify_sweep.py::cap_enforced` — a 4-attempt visitor is never selected again | Hybrid (needs PG) | AC-7 (bounded spend; user-superseded D6 — cap replaces the Redis allowance) |
| `tests/unit/test_reidentify_sweep.py::outage_defer_does_not_consume_attempt` — `resolution_defer_count` increase ⇒ count/next_at/tried_ips unchanged | Fully-Automated | AC-7 (fail-safe direction) |
| `tests/unit/test_reidentify_sweep.py::exception_does_not_consume_attempt` | Fully-Automated | AC-7 |
| `tests/unit/test_agent_company_resolution.py` `_AC2_FILES` tripwire (`:515-540`) **after appending `apps/api/services/reidentify_sweep_runner.py` to the hardcoded list at `:515-520`** | Fully-Automated | AC-8 (agent-origin exclusion) — **REPLACES the plan's original citation of `test_agent_origin_exclusion.py:236-247`, which asserts `source_agent_visit_id`, a different literal, and could never cover the new module (G3)** |
| `tests/integration/test_reidentify_sweep.py::agent_origin_never_selected` — seed an agent-derived visitor in the new status set; assert it is never selected | Hybrid (needs PG) | AC-8 (behavioural, not text-match) |
| `tests/integration/test_reidentify_sweep.py::do_not_resolve_never_retried` | Hybrid (needs PG) | AC-9 (do_not_resolve honored) |
| `tests/unit/test_reidentify_sweep.py::no_pii_in_logs` — log-capture assertion, no IP/email in structlog output | Fully-Automated | AC-10 (no PII in logs) |
| `tests/integration/test_reidentify_sweep.py::retries_do_not_exhaust_first_identify_budget` — run the new sweep up to the reserve threshold, then assert the main sweep still resolves ≥1 `anonymous` visitor | Hybrid (needs PG) | AC-11 (**REPLACES the vacuous `starvation_never_attempted_still_selected` row — the two sweeps are provably disjoint (`resolution_runner.py:135`), so intra-sweep ordering could never fail; the real contention is the shared 50/day budget, G4**) |
| `tests/unit/test_reidentify_sweep.py::defer_exhaustion_does_not_consume_attempt` — seed `resolution_defer_count = len(RESOLUTION_DEFER_BACKOFF)`; assert no attempt consumed and no `tried_ips` append | Fully-Automated | AC-7 (G2a) |
| `tests/unit/test_reidentify_sweep.py::budget_exhausted_site_consumes_nothing` — budget-exhausted site ⇒ **no** attempt consumed and **no** `tried_ips` entry appended | Fully-Automated | AC-7 (G2b) |
| `tests/unit/test_reidentify_sweep.py::exception_advances_next_at` — a raising call advances `next_at` by a backoff without consuming an attempt | Fully-Automated | AC-7 (G10 — prevents an unbounded per-tick hot loop) |
| `tests/integration/test_reidentify_sweep.py::sweep_does_not_persist_chosen_ip` — re-read the row from a fresh session after `expire_all()`; `visitors.ip_address` unchanged on the **success**, **outage** and **exception** paths | Hybrid (needs PG) | AC-7/AC-13 (G1 — the plan's central override must not be a committed write) |
| `tests/integration/test_reidentify_sweep.py::opt_out_site_never_selected` — a site with `auto_reidentify_opt_out = true` is never swept; default-false sites still are | Hybrid (needs PG) | D-D / G9 (consent escape hatch; coverage default preserved) |
| `tests/unit/test_reidentify_ranker.py::asn_none_short_circuits_to_unknown` — `lookup_asn` returning `(None, None)` yields tier `unknown` and `classify_ip_org_kind` is **never called** | Fully-Automated | AC-1 (G8 — without this, `classify_ip_org_kind(None, None)` returns `"org"` and the ladder collapses) |
| `tests/unit/test_reidentify_sweep.py::vpn_flip_still_counts_attempt` — an `unresolvable` → `vpn_filtered` flip via the IPinfo check still counts the attempt and appends `tried_ips` | Fully-Automated | G11 (unlisted status transition, now in Public Contracts) |
| Manual retry on a `vpn_filtered` visitor with a non-relay untried IP succeeds; with only relay IPs it does not | Hybrid (needs PG) | D-C / G7 (`routers/visitors.py:911-931`) |
| `tests/unit/test_resolution_deferral_watermark.py:151-198` **strengthened** to discover the new sweep's status literals, then assert `resolution_not_deferred_filter()` present | Fully-Automated | AC-11 |
| `tests/integration/test_unresolvable_revive.py:97-120` flag-parametrised — flag OFF assertions byte-unchanged; flag ON ⇒ revive inert | Hybrid (needs PG) | AC-12 (flag-off byte-identical) + D5 single-owner |
| Full unit + integration lanes with the flag unset | Fully-Automated | AC-12 |
| `tests/unit/test_scheduler_job_config.py:213-217` updated to 24/22 + changelog paragraph | Fully-Automated | AC-12 (scheduler registration correctness) |
| Migration up→down→up on a disposable Postgres, head re-derived live with `DATABASE_URL` pinned to `localhost:5433` | Hybrid (needs disposable container) | AC-13 (new store carried by the visitor row ⇒ inherits erasure/retention) |
| Erasure check — deleting the visitor row removes `auto_reidentify_tried_ips` with it (no separate erasure target) | Hybrid (needs PG) | AC-13 |
| Manual browser check — "tried N/4" renders on the list row and the detail page; Manual Retry still offered on an exhausted visitor and does not change the counter | Agent-Probe | User-locked UI policy (visible counter; manual exempt) |
| Whether a given corporate IP actually resolves via paid providers | Agent-Probe (residual — live-provider double-opt-in policy applies) | AC-14 (explicitly-justified residual) |
| Distinct-IPs-per-visitor distribution on real data | **Known-Gap → rollout gate** (backlog stub required; keeps the rollout gate CONDITIONAL, see §Measurement Gap) | Quantifies the value of attempts #2–#4 |

**Vacuous-green note:** exactly one row is Known-Gap (the measurement), it is a *rollout* gate not
a *behavior* gate, and it carries a required backlog stub — see §Measurement Gap. Every developed
behavior above is proven by a Fully-Automated, Hybrid, or Agent-Probe row.

---

## Test Infra Improvement Notes

- The repo has **no freezegun/time-machine**; the ranker therefore takes `now` as a parameter. If
  time-freezing is later added, the 7-day cadence tests could be simplified.
- **No mmdb in the repo or CI** — every ranker unit test exercises the `unknown` tier. A fixture
  `.mmdb` (or a `lookup_asn` monkeypatch helper) would let the org/eyeball ladder be tested for
  real; today only monkeypatched classification covers it.
- `tests/unit/test_resolution_deferral_watermark.py`'s `_sweeps()` discovery is a **string-match
  heuristic** — it silently misses any sweep that does not contain the literal
  `identity_status == "anonymous"`. This plan strengthens it once; a structural (AST/registry)
  discovery would end the recurring drift.
- No harness exists for asserting "this SQL puts group A before group B under a LIMIT". This is now
  moot for starvation (the ordering claim was deleted as vacuous, G4) but the same absence applies to
  the budget-reserve gate, which will be constructed ad hoc.
- `_AC2_FILES` in `tests/unit/test_agent_company_resolution.py:515-520` is a **hardcoded list** — it
  cannot discover a new module, and nothing warns when a new sweep is added. A registry/AST-based
  discovery would end this class of silent miss (it caused G3).

---

## Open Risks (call these out for VALIDATE)

| # | Risk | Why it is thin |
|---|---|---|
| **R1** | ~~Outage detection via before/after `resolution_defer_count`~~ | **RESOLVED (G2).** The census is complete (exactly two writers: `identity_resolver.py:721-723` increment, `:750` reset) and the heuristic is replaced by an exact test: AD-6 pins `resolution_defer_count = 0` at selection, so outage is simply `after > 0`. Budget/`do_not_resolve`/suppression are pre-checked so a no-provider-call can never be counted as an attempt. |
| **R2** | `auto_reidentify_tried_ips` JSONB has **no index** | **PASS, with a standing guard.** It appears in no predicate and no ORDER BY; it is read per-row on ≤20 already-materialised rows. Guard (execute instruction E4): **never** put `jsonb_array_length(auto_reidentify_tried_ips)` in an ORDER BY — that would make it a computed sort over the whole filtered set before LIMIT. |
| **R3** | ~~The starvation `ORDER BY`~~ | **RESOLVED AS A NON-PROBLEM (G4).** The two sweeps are provably disjoint (`resolution_runner.py:135` vs AD-6), so intra-sweep ordering cannot protect first-time identifies and the old gate was vacuously green. Replaced by the **D-B per-site budget reserve** (70%, explicitly a placeholder) plus `::retries_do_not_exhaust_first_identify_budget`. |
| **R4** | The 70% reserve threshold is unmeasured | It is an explicitly-labelled **PLACEHOLDER**, tuned before any prod flag flip, same posture as `job_change_recheck_daily_cap`. Too high starves retries; too low starves first-time identifies. |
| **R5** | The `skip_count < 8` retirement bound is likewise unmeasured | ~56 days of futile 7-day evaluation before retirement. A retired single-IP visitor is never re-evaluated even if a new IP arrives later — accepted, disclosed. |
| **R6** | `is_privacy_relay_ip` (`company_resolver.py:230-243`) checks only `("2a09:bac3:",)` | **iCloud IPv6 only — no v4 coverage.** The AD-4 exclusion is therefore weaker than its name suggests, which is exactly why the `unresolvable` → `vpn_filtered` flip (G11) is reachable and now disclosed in Public Contracts. |

Additional reviewable calls (lower severity, still worth a VALIDATE look):
- Plaintext IPs in `auto_reidentify_tried_ips` on the visitor row (AD-1 rationale: same row already
  holds a plaintext `ip_address`; inherits erasure for free).
- `is_privacy_relay_ip` covers only `2a09:bac3:` (iCloud v6) — **no v4 coverage**. The exclusion is
  therefore weaker than its name suggests.
- Every-site coverage means auto-identify-OFF sites start spending their daily budget. A per-site
  opt-out column is a named follow-up.

---

## Measurement Gap (named rollout gate)

Nothing in this repo measures the **distinct-IPs-per-visitor distribution**, so the real value of
attempts #2–#4 is **UNQUANTIFIED**. The local dev database is empty (0 rows), so it cannot be
measured here.

**This is a rollout prerequisite, not a build blocker** — build behind the flag, measure before
flipping it in prod. Register a backlog stub for the measurement so the Known-Gap is recorded
rather than silently dropped.

**Rollout order (mandatory):**
1. Migration live-applied (head re-derived live, `DATABASE_URL` pinned to `localhost:5433`).
2. Flag ON in dev.
3. **Measure** the distinct-IPs-per-visitor distribution on real data (read-only): p50/p95/max
   distinct IPs per visitor per 30/90 days; rate of "new IP after failed resolution"; org-kind mix.
4. Flag ON in prod.

---

## Sequencing / Collision

| Plan | State | Constraint on this change |
|---|---|---|
| `graph-erasure-compliance_07-08-26` | unexecuted, contract-bound edits to `identity_resolver.py` | do not widen the resolver footprint beyond the one parameter |
| `cross-tenant-erasure-phase2_07-08-26` | unexecuted; its own plan warns the resolver "has been rewritten three times in the last week" | re-derive every resolver anchor at EXECUTE |
| `ip-org-quality-pack_08-08-26` | code-committed on `devjulley` (`ad34632` + `9f97c54`), plan still active; deliberately kept BOTH `identity_resolver.py` and `visitor_aggregator.py` **READ-ONLY** | keep this change's footprint in those two files to the ONE parameter and the ONE flag guard; land in a tight commit |

---

## Acceptance Criteria

The plan is done when all of the following hold (mapped to SPEC AC-1…AC-14 in §Verification Evidence):

1. With the flag **OFF**, every existing unit and integration test passes unchanged and no new
   behavior is observable anywhere.
2. With the flag ON, a visitor seen from an office-classified and a residential-classified IP is
   attempted on the **office** IP.
3. A privacy-relay IP is never the attempted IP when a non-relay IP is known.
4. A previously-failed (`unresolvable` **or** `vpn_filtered`) visitor who later appears from a
   never-tried non-relay IP is automatically re-attempted, with no dashboard click.
5. An IP already in `tried_ips` is never re-attempted.
6. A visitor is evaluated at most once per 7 days; a cycle with no new untried IP consumes **no**
   attempt; after **4** consumed attempts the visitor is never selected again. **Qualified (G5):**
   "4 attempts ⇒ 4 distinct IPs" holds only when new IPs arrive at ≥7-day intervals — a visitor
   accumulating several new IPs inside one window gets one tried and the rest may be passed over by
   the recomputed ranking. A perpetual skipper retires after 8 skips.
7. An outage defer, a pre-check miss (budget / `do_not_resolve` / suppression), or an exception
   consumes **no** attempt and appends **no** `tried_ips` entry. An exception additionally advances
   `next_at` by a backoff. **`visitors.ip_address` is never written by this feature on any path.**
8. Agent-origin and `do_not_resolve` visitors are never selected.
9. No IP and no email appears in structlog output from the new paths.
10. **(Rewritten, G4)** Auto-retries never exhaust a site's daily identify budget ahead of
    first-time identifies: the sweep refuses to run for a site past the reserve threshold, and the
    main sweep still resolves at least one `anonymous` visitor after retries have run first.
11. The existing budget invariants stay green (distinct-visitor meter; deterministic-only never
    consults the budget).
12. `identity_status` gains **no new value**; the two front-end/analytics readers listed in AD-10
    are provably unaffected.
13. "tried N/4" renders on the visitor list row and the detail page; Manual Retry works on an
    exhausted visitor and neither consumes nor resets the counter; **Manual Retry is also offered
    for `vpn_filtered` visitors that have a non-relay untried IP (D-C)**.
13b. A site with `auto_reidentify_opt_out = true` is never swept; the column defaults to **false**,
    so every-site coverage is unchanged for everyone who does nothing (D-D).
14. The migration round-trips down/up on a disposable Postgres, chained off a **live-derived** head.
15. **User confirms** the observable behavior before any phase is marked ✅ VERIFIED.

---

## Rollback

| Situation | Action |
|---|---|
| Behavior wrong in dev/prod | Flip `auto_reidentify_enabled` to **False**. Job unregisters at next boot; revive path resumes; `resolve()` receives the defaults (`auto_retry=False`, `override_ip=None`); the new columns become inert data. **No code revert needed.** |
| Schema must go | The migration is additive and reversible — `alembic downgrade -1` with `DATABASE_URL` pinned local. Dropping the columns loses only attempt bookkeeping. |
| Budget burn observed | Flag OFF is the immediate lever; the existing 50/site/day cap plus the D-B per-site reserve are the standing backstops. Per-site: set `auto_reidentify_opt_out = true` (D-D) without touching the global flag. |

**Rollback is zero-cost ONLY because G1 is fixed — this dependency is load-bearing, not incidental.**
Under the original (broken) design, flipping the flag OFF un-gated `revive_returning_unresolvable`,
whose snapshot (`visitor_aggregator.py:345-359`) would have captured the **corrupted** IP while the
upsert wrote the real `latest_ip` (`:315`) — so `pre_snapshot.get(vid) != new_ip` (`:402`) would be
True for every touched visitor, causing a mass flip to `anonymous` (`:415`) plus a DELETE of failed
`ResolutionLog` rows (`:417-423`), defeating both the 30-day gate and the daily meter. That is the
exact re-burn loop named at `routers/visitors.py:1297-1303`. **With `override_ip` (D-A) no
corruption ever occurs, so no snapshot divergence is introduced and the rollback is genuinely
costless.** Verified by `::sweep_does_not_persist_chosen_ip`, which is therefore a rollback gate as
well as a correctness gate.

---

## Resume and Execution Handoff

1. **Selected plan file path:**
   `process/features/visitors-identity/active/ip-best-selection-retrigger_09-08-26/ip-best-selection-retrigger_PLAN_09-08-26.md`
2. **Last completed phase or step:** none — plan written 10-08-26; all phases ⏳ PLANNED.
3. **Validate-contract status:** **WRITTEN — `Gate: BLOCKED` (first pass, 10-08-26).** PVL
   supplement cycle 1 applied 10-08-26 closing G1–G14 (decisions D-A `override_ip`, D-B 70% budget
   reserve, D-C `vpn_filtered` manual retry, D-D per-site opt-out). **`vc-validate-agent` must
   re-run from V1.** EXECUTE is not authorised until the gate clears.
4. **Supporting context files loaded:**
   - `process/features/visitors-identity/active/ip-best-selection-retrigger_09-08-26/ip-best-selection-retrigger_SPEC_09-08-26.md`
   - `process/context/all-context.md`
   - `process/context/tests/all-tests.md`
   - `process/development-protocols/communication-standards.md`
5. **Next step for a fresh agent picking up mid-execution:**
   - Run `vc-context-discovery` + `vc-plan-discovery` (feature `visitors-identity`) first.
   - **Re-derive every `path:line` anchor in §Touchpoints** — three active plans hold unexecuted
     edits to `identity_resolver.py` and `visitor_aggregator.py`.
   - **Re-derive the alembic head live** with `DATABASE_URL` pinned to `localhost:5433`. The repo
     `.env` points at **Supabase PROD** and `apps/api/migrations/env.py` has no local-host guard.
   - Start at the first unchecked box in Phase-01 and run that phase's test gate before advancing.
   - Detect Docker by port (`lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`), not by
     `which docker`.

---

## Validate Contract

Status: BLOCKED
Date: 10-08-26
date: 2026-08-10
generated-by: outer-pvl

**Fan-out method: SEQUENTIAL, single agent.** The Agent tool is not available in this
environment, so the designed Layer 1 / Layer 2 parallel fan-out could not run. All four Layer 1
dimensions and all seven Layer 2 sections were investigated sequentially by one agent. An
independent adversarial verifier ran in parallel under the orchestrator; nothing below assumes
its coverage.

Parallel strategy: sequential (forced — no Agent tool)
Rationale: 7/7 signals present (multi-package, schema/API/identity surface, 3+ directions,
high-risk class, 15 files, user-requested depth on R1–R3, phase-shaped plan). Score says
agent-team; environment permits only sequential. Recorded as a coverage limitation, not a choice.

---

### Net Gate Derivation

| Layer 1 dimension | Status |
|---|---|
| Infra fit | CONCERN |
| Test coverage | **FAIL** |
| Breaking changes | **FAIL** |
| Security surface | **FAIL** |

| Layer 2 section | Status |
|---|---|
| Phase-01 — Schema (T1, T2) | PASS |
| Phase-02 — Pure ranker (T3) | PASS |
| Phase-03 — Resolver parameter (T5) | CONCERN |
| Phase-04 — Sweep runner (T4) | **FAIL** |
| Phase-05 — Flag / scheduler / revive (T6–T8, T12–T14) | CONCERN |
| Phase-06 — UI counter (T9–T11) | PASS |
| Phase-07 — Regression + rollout gate | CONCERN |

**Totals: 4 FAILs / 5 CONCERNs / 3 PASSes**

**→ Net Gate: BLOCKED**

---

### Adjudication of the plan's three named Open Risks

#### R1 — defer-count writer census — **FAIL (the mechanism is provably wrong on a reachable path)**

**Census is exhaustive and complete.** Every reference to `resolution_defer_count` in the repo:

| Path:line | Kind |
|---|---|
| `apps/api/models/visitor.py:162` | column declaration |
| `apps/api/migrations/versions/c2f7a9d31b64_add_resolution_deferral_watermark.py:49,58` | DDL |
| `apps/api/services/identity_resolver.py:721` | read (`(x or 0) + 1`) |
| `apps/api/services/identity_resolver.py:723` | **WRITE — increment** |
| `apps/api/services/identity_resolver.py:750` | **WRITE — reset to 0** |
| `tests/**` (10 sites) | assertions/fixtures only |

So the plan is right that `:723` is the only increment. **But the census was the wrong question.**
The defect is at `:722`:

```python
attempt = (visitor.resolution_defer_count or 0) + 1        # :721
if attempt <= len(RESOLUTION_DEFER_BACKOFF):               # :722  ← 4 steps, :91-96
    visitor.resolution_defer_count = attempt               # :723
    ...
    return None
# falls through on exhaustion
visitor.resolution_deferred_until = None                   # :749
visitor.resolution_defer_count = 0                         # :750
visitor.identity_status = "unresolvable"                   # :751
```

**Defect R1-a — defer-exhaustion reads as a successful attempt.** When `before == 4`
(`len(RESOLUTION_DEFER_BACKOFF)`, `identity_resolver.py:91-96`), the increment branch is SKIPPED and
`:750` resets the counter to **0**. The plan's test is `after > before`; here `after (0) > before (4)`
is **False**, so the sweep records a consumed lifetime attempt AND appends the chosen IP to
`tried_ips` — **permanently blacklisting an IP that no provider ever answered about.** This directly
violates the plan's own AD-8 accounting row 3 and Acceptance Criterion 7, in the **fail-unsafe**
direction.

**Defect R1-b — the heuristic is structurally undecidable whenever `before > 0`.** Two different
outcomes both produce `before > 0, after == 0`:
- exhaustion outage (`:722` False → `:750`), and
- a genuine no-match after earlier deferrals cleared (`:720` False → straight to `:749-751`).

No before/after comparison of a single integer can separate them. The mechanism is not merely
"manual", it is insufficient.

**Reachability is real, not theoretical.** The backoff totals ~31h (15m + 1h + 6h + 24h). A visitor
already `unresolvable` is selected by the new sweep; `resolve()` defers (status is NOT changed by the
deferral branch, so it stays `unresolvable` and stays in the new sweep's status set);
`resolution_not_deferred_filter()` (`apps/api/services/resolution_eligibility.py:84-106`) re-admits it
each time the watermark passes; four cycles later it exhausts. **One sustained ~31h provider outage
therefore burns one lifetime attempt and permanently destroys the best-ranked IP.**

**Cheapest correct fix (consistent with the plan's own "gates as columns in the WHERE clause"
doctrine):** add `AND auto-selected rows have resolution_defer_count = 0` to the AD-6 selection query.
Then `before` is always 0 at call time, `:722` can never be False from this sweep, and
`after > before` becomes an exact outage test. This must be written into AD-6/AD-8 and gated by a unit
test that seeds `resolution_defer_count = len(RESOLUTION_DEFER_BACKOFF)`.

#### R2 — unindexed JSONB — **PASS**

Confirmed from AD-6: the selection predicate is `site_id`, `identity_status`,
`auto_reidentify_count`, `auto_reidentify_next_at`, `do_not_resolve`, plus
`resolution_not_deferred_filter()` / `human_only_visitor_filter()` / `resolution_candidate_filter()`.
`auto_reidentify_tried_ips` appears in **no** predicate and in **no** ORDER BY — it is read per-row
only after the ≤20-row batch is materialised, then passed to the pure ranker as `tried_ips`. An
unindexed JSONB read on ≤20 already-fetched rows costs nothing. No FAIL.

**Guard required:** checklist 4.3 defers the ORDER BY to EXECUTE. If that expression is written as
`jsonb_array_length(auto_reidentify_tried_ips)`, it becomes a computed sort over the whole filtered
candidate set before LIMIT and R2 flips to a real cost. Pinned as an execute-agent instruction (E4).

#### R3 — the starvation ORDER BY — **CONCERN: the plan is solving a non-problem and has no mechanism for the real one**

**The two sweeps are provably disjoint.** The main sweep selects
`Visitor.identity_status.in_(("anonymous", "candidate"))` (`apps/api/services/resolution_runner.py:135`);
the Celery-beat twin does the same (`apps/api/tasks/resolution_tasks.py:95` region). The new sweep
selects `('unresolvable','vpn_filtered')` (AD-6). **They can never share a batch.**

Therefore "never-attempted first" inside the new sweep orders *auto-retry virgins* ahead of
*auto-retry repeats* — and both groups are, by definition, already-failed visitors. It cannot affect
first-time identifies at all. **Plan Acceptance Criterion 10 ("Never-attempted visitors are still
selected when retry-eligible visitors exceed the sweep LIMIT") is trivially true by disjointness, and
its named gate `starvation_never_attempted_still_selected` is therefore a vacuous green.**

**The real contention is the shared daily budget, and nothing addresses it.**
`resolve()` calls `check_daily_budget` at `identity_resolver.py:589` →
`check_resolution_attempt_budget` (`apps/api/services/usage_limits.py:86-89`) → `used <
get_site_daily_budget(...)`, a **distinct-visitor count against a per-site cap (default 50)**. The
auto-retry population is a *different* set of visitors from the main sweep's, so **every auto-retry
consumes one distinct-visitor slot**. The two sweeps race first-come-first-served on one 50/day
counter. Ordering inside one sweep cannot influence a counter consumed by the other.

**Consequence:** on a site where auto-retries fire before the main sweep's interval, retries can
consume the entire day's budget and first-time identifies get zero. That is the *actual* AC-11
regression the SPEC's Constraint 4 warns about, and the plan has **no mechanism** for it — the user's
D6 supersede removed the separate allowance without replacing it with a reservation.

**In-scope fix that needs no new Redis key and no new meter:** have the sweep read the *existing*
meter and refuse to run for a site once today's usage exceeds a reserve threshold (e.g. skip the site
when `get_resolution_attempts_today(db, site_id)` is already ≥ 60% of `get_site_daily_budget(db,
site_id)`), leaving the remainder for first-time identifies. This is a read of functions that already
exist (`apps/api/services/usage_limits.py`), keeps D6's "no separate allowance" intact, and is
testable without Redis.

---

### Findings

| # | Dimension | Severity | Finding | Evidence (path:line) | Resolution |
|---|---|---|---|---|---|
| F1 | Security surface / Breaking changes | **FAIL** | **`visitor.ip_address = chosen` is NOT an in-memory override — it is a committed write that silently corrupts a PII column.** The sweep passes the same `AsyncSession` to the resolver (`resolver = IdentityResolver(db)`, the shape donor's own pattern), so `visitor` is a session-attached ORM object and the assignment marks the attribute dirty. `resolve()` then commits on **every** exit path: `:596` (no IP), `:609` (relay), `:621` (IPinfo VPN), `:735` (outage defer), `:752` (terminal). Any one of them flushes the dirty attribute, permanently overwriting `visitors.ip_address` with a historical ranked IP. The plan asserts the opposite in AD-8 and lists no mitigation anywhere. | `apps/api/services/identity_resolver.py:596,609,621,735,752`; `apps/api/services/resolution_runner.py:154`; plan AD-8 | Plan change required. Either (a) add a real `override_ip` parameter to `resolve()` (structurally correct; the plan rejected it on footprint grounds), or (b) specify an explicit `try/finally` that restores `visitor.ip_address = original_ip` **and re-commits** after `resolve()` returns/raises — restoring in memory alone does not undo an already-committed write. Add a gate that asserts `visitors.ip_address` is unchanged in the DB after a sweep cycle. |
| F2 | Breaking changes | **FAIL** | R1 above: outage detection misreads defer-exhaustion as a real attempt and is undecidable whenever `before > 0`. Burns a lifetime attempt and permanently blacklists an untested IP. Violates plan AC-7. | `apps/api/services/identity_resolver.py:721-723,749-751,91-96` | Plan change required. Add `resolution_defer_count = 0` to the AD-6 WHERE clause and restate AD-8's outage rule against that precondition. |
| F3 | Test coverage | **FAIL** | **The named gate for the SPEC's declared highest-priority invariant (AC-8, agent-origin exclusion) does not exist and would not fire.** The plan cites "`tests/unit/test_agent_origin_exclusion.py` incl. the literal-text tripwire at `:236-247` — `human_only_visitor_filter()` MUST appear in the new selection query". Two errors: (1) that tripwire asserts the literal `source_agent_visit_id`, not `human_only_visitor_filter`; (2) the `human_only_visitor_filter` tripwire lives in a **different file** and iterates a **hardcoded** `_AC2_FILES` list that does not and cannot discover a new module. Running either file "unchanged" proves nothing about the new sweep. Touchpoints has no entry for the file that would need editing. | `tests/unit/test_agent_origin_exclusion.py:235-247` (wrong literal); `tests/unit/test_agent_company_resolution.py:515-540` (`_AC2_FILES`, hardcoded) | Plan change required. Add `tests/unit/test_agent_company_resolution.py` to Touchpoints, append `apps/api/services/reidentify_sweep_runner.py` to `_AC2_FILES`, and add a behavioural integration case seeding an agent-derived visitor in the new sweep's status set. |
| F4 | Test coverage | **FAIL** | AC-11's gate is vacuously green (R3 above): the two sweeps are disjoint, so "never-attempted still selected under LIMIT" cannot fail. The real cross-sweep budget contention has no gate at all. | `apps/api/services/resolution_runner.py:135`; `apps/api/services/usage_limits.py:86-89` | Plan change required. Replace/augment with a gate that proves first-time-identify budget is preserved when auto-retries run first on the same site. |
| C1 | Infra fit | CONCERN | **Exception path is an unbounded hot loop.** AD-8 row 4 leaves `next_at` unchanged on an exception, and the per-row handler is `except/continue`. A deterministic exception (malformed evidence, provider client bug) re-selects the same visitor on every sweep tick forever, re-running the evidence `GROUP BY` and the ranker each time. | plan AD-8 row 4, AD-6 per-row `try/except/continue` | Advance `next_at` by a short backoff on the exception path (or by the full 7d), still without consuming an attempt. |
| C2 | Breaking changes | CONCERN | **Unlisted status transition.** With the chosen IP assigned, `resolve()` may flip an `unresolvable` visitor to `vpn_filtered` via the IPinfo privacy check (`:611-620`) — the ranker's relay exclusion only covers `is_privacy_relay_ip`, which matches the single prefix `2a09:bac3:` (iCloud v6, **no v4**). The plan's Public Contracts table does not list `identity_status` mutation by the new sweep. Also spends an unbudgeted IPinfo call (no `ResolutionLog` row ⇒ invisible to the daily meter). | `apps/api/services/identity_resolver.py:602-622`; `apps/api/services/company_resolver.py:233-242` | Record the transition in Public Contracts; add a gate asserting the attempt is still counted and `tried_ips` still appended on this path. |
| C3 | Test coverage | CONCERN | SPEC AC-13 requires the new store to have "a stated retention rule not exceeding its purpose". The plan states erasure inheritance but states **no** retention rule. | SPEC AC-13; plan AD-1 | State it explicitly: retention = the visitor row's own lifetime; no independent rule needed. One sentence in AD-1. |
| C4 | Infra fit | CONCERN | SPEC Constraint 6 asserts org_kind has **five** on-disk values including `registry`; the plan's AD-3 ladder has four. **The plan is correct** — `classify_ip_org_kind` returns exactly `org`/`eyeball`/`datacenter`/`cdn` and no `registry` literal exists in that module. The divergence is unrecorded, so a future reader may "fix" the ranker by adding a phantom tier. | `apps/api/services/ip_org_ingest.py:116-138` | Record the SPEC-supersede in AD-3 in one line. |
| C5 | Infra fit | CONCERN | `lookup_asn` is a **synchronous, blocking** MaxMind reader call made per-IP inside an async sweep (up to 20 visitors × N IPs per tick). Harmless today (no mmdb ⇒ immediate `(None, None)`), but becomes event-loop blocking the moment the file is installed — which is exactly the configuration AD-3's ladder is designed for. | `apps/api/services/asn_lookup.py:61-76` | Note in AD-2; consider `asyncio.to_thread` or per-tick memoisation. Not a blocker. |
| C6 | Security surface | CONCERN | Every-site coverage means sites that deliberately left `auto_identify_enabled=False` begin spending their identify budget. The plan discloses this and names a per-site opt-out as a follow-up, but ships with no opt-out. Combined with F4 this is the operator-facing risk of the change. | plan AD-6 | Accept with disclosure, or add the opt-out column now. Do not leave it implicit in the rollout runbook. |
| P1 | Test coverage | ✅ PASS | **The proposed tripwire strengthening is safe and effective.** Simulated the strengthened `_sweeps()` discovery over `apps/api/**`: matching on `unresolvable` or `vpn_filtered` + `await …resolve(` yields only `apps/api/routers/visitors.py`, which **already contains** `resolution_not_deferred_filter()` and is **already discovered** by today's `anonymous` literal. So the strengthening adds zero newly-failing files. `test_both_known_sweeps_are_discovered` uses a subset (`<=`) assertion, so a third discovered file does not break it. The new module's source will contain the literal `unresolvable` inside `.in_(("unresolvable", "vpn_filtered"))`, so a plain substring match discovers it. | `tests/unit/test_resolution_deferral_watermark.py:171-196`; simulation over `apps/api/**` | — (re-run the simulation at EXECUTE; files move) |
| P2 | Infra fit | ✅ PASS | **Scheduler arithmetic and every sibling gate check out.** Current assertions are 23 add_job / 21 interval (`:213-217`) ⇒ 24/22 for one new interval job is correct. Sibling gates all addressed by the plan: explicit `id` (`:104-106`), `jitter` + `misfire_grace_time` present (`:133-147`) and positive literals (`:149`), cron set pinned to exactly `{outcome_digest, daily_digest}` (`:108-121`) ⇒ the new job **must** be interval, and the boot offset must be **strictly** `< 90s` because `test_the_boot_offset_is_larger_than_the_existing_offsets` (`:80-101`) asserts `aggregation_sweep > max(others)`. | `tests/unit/test_scheduler_job_config.py:80-121,133-160,175-217` | — |
| P3 | Security surface | ✅ PASS | **The GDPR "for free" claim is TRUE.** `DELETE /{site_id}/{visitor_id}/data` executes a real `DELETE FROM visitors WHERE site_id = :sid AND visitor_id = :vid` — a full **row** delete, not a column-nulling — so `auto_reidentify_tried_ips` is destroyed with the row. `graph_erasure` operates on `beam_identity_graph` (blind-index matched) and never touches `visitors`, so no new erasure target is created. | `apps/api/routers/visitors.py:448-474` | — (still state the retention rule per C3) |
| P4 | Breaking changes | ✅ PASS | **`revive_returning_unresolvable`'s flag-off path can be byte-identical and no caller reads its return value.** The sole invocation is `await revive_returning_unresolvable(db, site_id, unresolvable_pre)` — the `int` return is **discarded**, so an early `return 0` is safe. A guard placed at the top of the function (before the `if not pre_snapshot` check) leaves every other line untouched. | `apps/api/services/visitor_aggregator.py:365-431,521` | — |
| P5 | Breaking changes | ✅ PASS | `auto_retry` bypassing `identity_resolver.py:583` and nothing else is correct: the gate is a single compound conditional, and `do_not_resolve` (`:548`), suppression (`:557`), budget (`:589`), no-IP (`:593`), relay (`:602`), IPinfo VPN (`:611`) all sit on separate statements downstream. | `apps/api/services/identity_resolver.py:548-622` | — |

---

### III. Test Coverage Plan

Runner/commands sourced from `process/context/tests/all-tests.md` (routing chain loaded) and from the
existing blast-radius test files, which were read directly. No command below is inferred.

**Hybrid precondition (RUNNABLE — not an environment block).** Ports 5433/6379 were checked and are
not listening, and the Docker daemon socket is absent, but the CLI exists at
`/Applications/Docker.app/Contents/Resources/bin/docker`. Per `all-tests.md:89-102`,
"environment-blocked" is **not** a valid known-gap category in this repo. Start it first:

```
open -a Docker
/Applications/Docker.app/Contents/Resources/bin/docker compose -f infra/docker-compose.yml up -d postgres redis
lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'    # must print both before running Hybrid gates
```

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | best IP (org tier) outranks eyeball | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_reidentify_ranker.py -q` (`::org_over_eyeball`) | B |
| AC-1 | with no mmdb, `unknown` outranks `eyeball` (the CI-default path) | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_reidentify_ranker.py -q` (`::unknown_ranks_second`) | B |
| AC-1/AC-2 | ranking is a total order (permuted input ⇒ identical output) | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_reidentify_ranker.py -q` (`::total_order_under_permutation`) | B |
| AC-1 | seeded events ⇒ the attempted IP is the office IP | Hybrid | `.venv/bin/python -m pytest tests/integration/test_reidentify_sweep.py -q` (`::best_ip_selection`) — precondition above | B |
| AC-2 | relay IP never chosen when a non-relay exists | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_reidentify_ranker.py -q` (`::relay_excluded`) | B |
| AC-3 | untried IP B re-opens a failed visitor, no manual action | Hybrid | `.venv/bin/python -m pytest tests/integration/test_reidentify_sweep.py -q` (`::new_ip_revives`) | B |
| AC-4 | an IP in `tried_ips` is never re-attempted | Hybrid | `.venv/bin/python -m pytest tests/integration/test_reidentify_sweep.py -q` (`::tried_ip_not_looped`) | B |
| AC-5 | `vpn_filtered` picked up only on a new non-relay IP | Hybrid | `.venv/bin/python -m pytest tests/integration/test_reidentify_sweep.py -q` (`::vpn_filtered_pickup`) | B |
| AC-6 | daily meter still counts distinct visitors, not rows | Fully-Automated | `.venv/bin/python -m pytest tests/integration/test_resolution_budget.py -q` (`::TestResolutionAttemptCounting::test_counts_distinct_visitors_not_rows`) | A |
| AC-6 | `deterministic_only=True` never consults the budget | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_identity_resolver_parallel.py -q` (invariant at `:745-759`) | A |
| AC-7 | a 4-attempt visitor is never selected again | Hybrid | `.venv/bin/python -m pytest tests/integration/test_reidentify_sweep.py -q` (`::cap_enforced`) | B |
| AC-7 | outage defer consumes no attempt | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_reidentify_sweep.py -q` (`::outage_defer_does_not_consume_attempt`) | B |
| **AC-7 (NEW — F2)** | **defer-EXHAUSTION consumes no attempt and does not append to `tried_ips`** — seed `resolution_defer_count = len(RESOLUTION_DEFER_BACKOFF)` | Fully-Automated | new case in `tests/unit/test_reidentify_sweep.py` (`::defer_exhaustion_does_not_consume_attempt`) | **B — gate does not exist in the plan; must be added** |
| AC-7 | an exception consumes no attempt | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_reidentify_sweep.py -q` (`::exception_does_not_consume_attempt`) | B |
| **AC-7 (NEW — C1)** | **an exception advances `next_at` so the visitor is not re-selected every tick** | Fully-Automated | new case in `tests/unit/test_reidentify_sweep.py` (`::exception_advances_next_at`) | **B — gate does not exist in the plan; must be added** |
| **AC-8 (REPLACES the plan's vacuous row — F3)** | the new sweep module is covered by the AC2 filter tripwire | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_agent_company_resolution.py -q` **after** appending `apps/api/services/reidentify_sweep_runner.py` to `_AC2_FILES` (`:515-520`) | **B — plan cites the wrong file and a hardcoded list; must be edited** |
| AC-8 | an agent-derived visitor in the new status set is never selected | Hybrid | `.venv/bin/python -m pytest tests/integration/test_reidentify_sweep.py -q` (`::agent_origin_never_selected`) | B |
| AC-9 | `do_not_resolve` visitor never retried | Hybrid | `.venv/bin/python -m pytest tests/integration/test_reidentify_sweep.py -q` (`::do_not_resolve_never_retried`) | B |
| AC-10 | no IP / no email in structlog from new paths | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_reidentify_sweep.py -q` (`::no_pii_in_logs`) | B |
| AC-11 | every sweep that selects a terminal status carries `resolution_not_deferred_filter()` | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_resolution_deferral_watermark.py -q` (strengthened `_sweeps()` at `:171-179`) | B |
| **AC-11 (REPLACES the plan's vacuous row — F4)** | **first-time-identify budget survives auto-retries running first on the same site** | Hybrid | new case in `tests/integration/test_reidentify_sweep.py` (`::retries_do_not_exhaust_first_identify_budget`): run the new sweep to the reserve threshold, then assert the main sweep still resolves ≥1 `anonymous` visitor | **B — gate does not exist in the plan; must be added** |
| AC-12 | flag OFF ⇒ revive behaviour byte-identical; flag ON ⇒ revive inert | Hybrid | `.venv/bin/python -m pytest tests/integration/test_unresolvable_revive.py -q` (flag-parametrised `:96-120`) | B |
| AC-12 | full lanes green with the flag unset | Fully-Automated | `.venv/bin/python -m pytest tests/unit -m unit -q` **and** `.venv/bin/python -m pytest tests/ -m integration -q` | A |
| AC-12 | scheduler registration correctness (24/22, id, jitter, misfire, boot offset < 90s, interval-not-cron) | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_scheduler_job_config.py -q` | B |
| AC-13 | migration round-trips down/up on a **disposable** Postgres, head derived live | Hybrid | `DATABASE_URL=postgresql+asyncpg://…@localhost:5433/… .venv/bin/python -m alembic -c apps/api/alembic.ini heads` then `upgrade head` / `downgrade -1` / `upgrade head` against a **throwaway** container | B |
| AC-13 | deleting the visitor row removes `auto_reidentify_tried_ips` with it | Hybrid | `.venv/bin/python -m pytest tests/integration/test_reidentify_sweep.py -q` (`::erasure_removes_tried_ips`) | B |
| **NEW (F1)** | **`visitors.ip_address` in the DB is unchanged after a sweep cycle** (re-read from a fresh session after `expire_all()`, on the success, outage, and exception paths) | Hybrid | new case in `tests/integration/test_reidentify_sweep.py` (`::sweep_does_not_persist_chosen_ip`) | **B — gate does not exist in the plan; must be added** |
| UI policy | "tried N/4" renders on list + detail; Manual Retry on an exhausted visitor neither consumes nor resets | Agent-Probe | browser check of `/dashboard/visitors` and `/dashboard/visitors/[visitorId]` | A |
| AC-14 | whether a given corporate IP actually resolves via paid providers | Agent-Probe | live-provider double-opt-in required; explicitly-justified residual | C |
| Rollout | distinct-IPs-per-visitor distribution on real data | — (named residual) | none — rollout gate, backlog stub required | **D** |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: the `strategy:` column carries ONLY the 3 proving strategies
(Fully-Automated / Hybrid / Agent-Probe). Known-Gap is never a `strategy:` value — the one residual
(distinct-IPs measurement) is carried as gap-resolution **D**.

Legacy line form (retained so existing validate-contract consumers still parse):
- ranker: `Fully-automated: .venv/bin/python -m pytest tests/unit/test_reidentify_ranker.py -q`
- sweep accounting: `Fully-automated: .venv/bin/python -m pytest tests/unit/test_reidentify_sweep.py -q`
- sweep behaviour: `hybrid: .venv/bin/python -m pytest tests/integration/test_reidentify_sweep.py -q + precondition: docker compose -f infra/docker-compose.yml up -d postgres redis (ports 5433/6379 listening)`
- regression lanes: `Fully-automated: .venv/bin/python -m pytest tests/unit -m unit -q; .venv/bin/python -m pytest tests/ -m integration -q`
- migration: `hybrid: alembic heads/upgrade/downgrade + precondition: disposable Postgres, DATABASE_URL pinned to localhost:5433`
- UI counter: `agent-probe: browser check of visitor list row + detail page`
- provider resolvability: `agent-probe: live-provider double-opt-in`
- IP-distribution measurement: `known-gap: documented as rollout gate — backlog stub required`

TDD failing stubs for the four NEW Fully-Automated rows (red-first starting points for EXECUTE):

```
Failing stub:
test("should not consume an attempt on defer exhaustion", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: defer-EXHAUSTION consumes no attempt and does not append to tried_ips")
})

Failing stub:
test("should advance next_at on exception", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: an exception advances next_at so the visitor is not re-selected every tick")
})

Failing stub:
test("should cover the new sweep module in the AC2 filter tripwire", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: the new sweep module is covered by the AC2 filter tripwire")
})
```

(The two Hybrid additions — `::retries_do_not_exhaust_first_identify_budget` and
`::sweep_does_not_persist_chosen_ip` — deliberately receive no stub; Hybrid tiers are stub-exempt.)

---

Dimension findings:
- Infra fit: CONCERN — scheduler arithmetic and every sibling gate verified correct (P2); Docker is startable so no Hybrid gate is environment-blocked; but the exception path is an unbounded re-selection loop (C1), `lookup_asn` blocks the event loop once an mmdb exists (C5), and the SPEC-vs-plan org_kind divergence is unrecorded (C4).
- Test coverage: FAIL — AC-8's named gate is in the wrong file and is a hardcoded list that cannot cover the new module (F3); AC-11's gate is vacuously green because the two sweeps are disjoint (F4); no gate exists for defer-exhaustion, for the exception `next_at` advance, or for IP-persistence.
- Breaking changes: FAIL — the plan's central override mechanism silently persists (F1); the outage detector is wrong on a reachable path (F2); an unlisted `unresolvable → vpn_filtered` transition is missing from Public Contracts (C2). PASSes: the `auto_retry` single-line bypass is correct (P5) and the revive flag-guard is safe with no return-value consumer (P4).
- Security surface: FAIL — F1 corrupts a plaintext PII column (`visitors.ip_address`) with no mitigation specified; every-site coverage spends budget on sites that opted out of auto-identify with no opt-out available (C6). PASS: the GDPR erasure-inheritance claim is TRUE — visitor erasure is a full row DELETE (P3).
- Phase-01 Schema: PASS — additive/no-index/no-backfill posture matches `c2f7a9d31b64`; naive datetimes are the right convention; live-head derivation and the pinned local `DATABASE_URL` are correctly mandated.
- Phase-02 Pure ranker: PASS — pure/no-module-scope-IO split is sound, injected clock matches the repo idiom (no freezegun), `unknown`-second is correctly justified by the absent mmdb, and `classify_ip_org_kind`'s four return values are accurate. Highest-risk edit: the business-hours abstain rule; mitigate with the permutation test.
- Phase-03 Resolver parameter: CONCERN — mechanically feasible and minimal (P5), but it is the delivery vehicle for F1/F2 and the file is contested by three unexecuted plans; every anchor must be re-derived.
- Phase-04 Sweep runner: FAIL — carries F1, F2, F4 and C1. Highest-risk edit: the block between `visitor.ip_address = chosen` and the accounting write; sequence it last and gate it with `::sweep_does_not_persist_chosen_ip`.
- Phase-05 Flag/scheduler/revive: CONCERN — the tripwire strengthening is empirically safe (P1) and the scheduler arithmetic is right (P2), but F3's missing `_AC2_FILES` edit belongs here and is absent from Touchpoints.
- Phase-06 UI counter: PASS — the `VisitorOut` base-class instruction correctly encodes the prior P0 lesson; additive response field breaks no reader.
- Phase-07 Regression + rollout: CONCERN — the rollout order is right, but the measurement residual keeps the rollout gate CONDITIONAL and its backlog stub is required, not optional.

Open gaps:
- Distinct-IPs-per-visitor distribution on real data: known-gap: documented as rollout gate — a backlog stub MUST be written before EXECUTE closes (`process/features/visitors-identity/backlog/`). Not a build blocker; blocks the prod flag flip only.
- AC-14 (real-world resolvability of a specific corporate IP): Agent-Probe residual, live-provider double-opt-in policy applies. Explicitly justified.
- Per-site opt-out from every-site auto-retry coverage: named follow-up, not built (C6).

What this coverage does NOT prove:
- `tests/unit/test_reidentify_ranker.py` runs with **no mmdb**, so every IP classifies as `unknown`. It proves the tier-ladder *ordering logic* and the `unknown`-second decision, but it does **not** prove that a real corporate IP actually classifies as `org` in production — only monkeypatched classification covers the org/eyeball ladder.
- `tests/integration/test_reidentify_sweep.py` runs against seeded rows with mocked providers. It does not prove any provider actually returns a match for the chosen IP, does not prove real-world latency of the per-visitor `GROUP BY ip_address` at production row counts, and does not prove the sweep's behaviour under concurrent execution on two API replicas beyond the advisory lock's own semantics.
- `tests/unit/test_scheduler_job_config.py` is an AST scan of the registration source. It proves the job is *declared* correctly; it does not prove APScheduler actually fires it, that the advisory lock is acquired at runtime, or that the boot offset behaves as intended on a real deploy.
- `tests/unit/test_resolution_deferral_watermark.py`'s `_sweeps()` is a **substring heuristic**, even strengthened. It proves the literal `resolution_not_deferred_filter()` appears in the file; it does not prove the filter is applied to the right query, in the right position, or at all at runtime.
- `tests/unit/test_agent_company_resolution.py`'s `_AC2_FILES` tripwire is a **text search over a hardcoded list**. It proves the literal `human_only_visitor_filter` appears in the file; it does not prove the filter is in the selection query rather than a comment, and it silently covers nothing for any file not manually added to the list.
- The migration round-trip on a disposable Postgres does not prove the migration applies cleanly against **production** data volumes or against the live prod head (currently `c4a8f13e07b6`), and it proves nothing about lock duration on a large `visitors` table.
- The full unit + integration lanes with the flag unset prove no *observable* behaviour changed. They do not prove the three new columns, the new modules, or the new job are free of latent defects, because with the flag off none of that code executes.
- The Agent-Probe UI check proves the counter renders and Manual Retry is offered. It does not prove the counter is *correct* against the DB — only the integration accounting gates do.
- No gate anywhere proves the cost model: nothing measures actual provider spend produced by auto-retries, because failed attempts are priced $0.00 and the daily meter counts distinct visitors.

Gate: BLOCKED (4 unresolved FAILs: F1 committed IP corruption, F2 defer-exhaustion misdetection, F3 vacuous AC-8 gate, F4 vacuous AC-11 gate)
Accepted by: none — BLOCKED verdicts cannot be self-accepted. No user acceptance was given in this session; the validate-agent does not accept its own gate.

---

## Autonomous Goal Block

```
SESSION GOAL: Best-IP selection + capped automatic re-identify (4 lifetime attempts, 7-day cadence, every site, shared 50/day budget), behind default-OFF flag auto_reidentify_enabled.
Charter + umbrella plan: N/A — single plan
Autonomy: Standard RIPER-5. This plan is currently BLOCKED at VALIDATE — autonomy does NOT extend to starting EXECUTE. The only autonomous next action is the PVL supplement cycle (vc-plan-agent, supplement mode).
Hard stop conditions / safety constraints:
- Do NOT run alembic without DATABASE_URL pinned to localhost:5433 — the repo .env points at Supabase PRODUCTION and apps/api/migrations/env.py has no local-host guard.
- Do NOT run migrations against the shared dev container; use a disposable Postgres for the down/up round-trip.
- Do NOT flip auto_reidentify_enabled in prod before the distinct-IPs-per-visitor measurement is run read-only against real data.
- Never log an IP or an email from any new code path.
- Agent-origin exclusion (human_only_visitor_filter) and do_not_resolve are non-negotiable in every new selection query.
- Keep the footprint in identity_resolver.py to ONE parameter and visitor_aggregator.py to ONE flag guard — three active plans hold unexecuted edits to both.
Next phase: RETURN TO PLAN — vc-plan-agent supplement cycle addressing F1, F2, F3, F4 (+ C1, C2, C3, C4). EXECUTE is not authorised while Gate: BLOCKED.
Validate contract: inline in plan (process/features/visitors-identity/active/ip-best-selection-retrigger_09-08-26/ip-best-selection-retrigger_PLAN_09-08-26.md § Validate Contract)
Execute start: BLOCKED — not authorised. After the supplement cycle re-validates to PASS, start is: .venv/bin/python -m pytest tests/unit -m unit -q | integration spec: tests/integration/test_reidentify_sweep.py | probe scenario: browser check of "tried N/4" on list + detail | high-risk pack: yes (schema migration + identity status + paid-provider spend)
```

---

## Next Step

Plan complete. Review carefully. Say **"ENTER VALIDATE MODE"** when ready to proceed to plan
validation (required before EXECUTE). Do not say "ENTER EXECUTE MODE" until the validate-contract
exists — this plan touches schema, identity status, and paid-provider spend.
