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
**four additive columns on `visitors` plus one on `sites`**, an ephemeral per-visitor claim table,
and **four new modules** (claim model/helper, ranker, sweep) — the rollup
takes exactly one flag guard; the resolver takes two defaulted parameters (D-A).

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
| T1 | `apps/api/models/visitor.py` | **+4 columns** on `Visitor` (incl. `auto_reidentify_skip_count`, G5) | attempt state |
| T2 | `apps/api/migrations/versions/<new>.py` | **new** additive migration: five columns plus the TTL claim table with composite FK/cascade | schema |
| T3 | `apps/api/services/reidentify_ranker.py` | **new** pure module | IP ranking |
| T4 | `apps/api/services/reidentify_sweep_runner.py` | **new** owner module: two-pool selection, claim-before-provider, result-aware accounting | the sweep |
| T5 | `apps/api/services/identity_resolver.py:544-795` | defaulted IP-only automatic mode (`auto_retry: bool = False`, `override_ip: str \| None = None`, `selected_ip_activity_at: datetime \| None = None`) plus private result core / public `resolve_auto_retry(...)` | skip prior signals, non-persisting IP override, exact activity provenance for a historical chosen IP, explicit outage outcome |
| T5b | `apps/api/services/identity_providers/pdl.py:74`, `ipinfo.py:144`, `rb2b.py:182`, `capturify.py:82`, `leadpipe.py:175` | **+1 defaulted `override_ip` parameter each**; Leadpipe and Capturify additionally receive defaulted selected-IP activity for `MatchingMixin` recency | each mixin reads the effective IP itself; ordinary callers remain unchanged |
| T6 | `apps/api/services/visitor_aggregator.py` | **+1 flag guard** — early-return in `revive_returning_unresolvable` (`:365-431`) | one owner |
| T7 | `apps/api/config.py` | **+1 flag block** (`auto_reidentify_enabled` + interval/cap/cadence constants) | operator gate |
| T8 | `apps/api/jobs/scheduler.py` | **+1 job** registration | cadence |
| T9 | `apps/api/schemas/visitors.py` | expose `auto_reidentify_count` | UI |
| T10 | `apps/web/src/app/dashboard/visitors/page.tsx` | render "tried N/4" near `renderIdentity` (`:360-424`) | UI list |
| T11 | `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx` | render "tried N/4" | UI detail |
| T12 | `tests/unit/test_scheduler_job_config.py` | **edit** current 24 add-job / 21 interval / 3 cron assertions to **25 / 22 / 3**, plus provenance paragraph (`:176-223`) | scheduler gate |
| T13 | `tests/unit/test_resolution_deferral_watermark.py` | **strengthen** sweep discovery (`:151-198`) | gate |
| T14 | `tests/integration/test_unresolvable_revive.py` | **flag-parametrise** (`:97-120`) | gate |
| T15 | 4 new test files (ranker, unit sweep, integration sweep, integration site settings; see §Verification Evidence) | new | coverage |
| T16 | `tests/unit/test_agent_company_resolution.py` | **edit** — append `apps/api/services/reidentify_sweep_runner.py` to `_AC2_FILES` (`:515-520`) | the AC-8 tripwire cannot discover a new module otherwise (G3) |
| T17 | `apps/api/routers/visitors.py:877-980` | **edit** manual retry endpoint — claim before terminal-state mutation, attempt immediately even during a defer window, and accept `vpn_filtered` only under the existing non-relay policy | D-C plus S7 four-human-lane lease coordination |
| T18 | `apps/api/models/site.py` (+ the same migration as T2) | **+1 column** `auto_reidentify_opt_out Boolean NOT NULL server_default "false"` | per-site opt-out (D-D / G9) |
| T19 | `apps/web/src/lib/api-types.ts:151-183` **and** `apps/web/src/components/site-settings-dialog.tsx:97-104,279-307` | add `Site.auto_reidentify_opt_out`, `SiteUpdate.auto_reidentify_opt_out`, and a deliberately inverse-labelled site setting toggle | D-D UI contract |
| T20 | `apps/web/src/app/dashboard/visitors/page.tsx:389-392` | render a Retry button on the `vpn_filtered` badge branch (today only `unresolvable` `:395-411` has one) | D-C (G7) |
| T21 | `apps/api/schemas/sites.py` | **+1 field each** on `SiteUpdate` (`auto_reidentify_opt_out: bool \| None = None`, `:48-62`) and `SiteOut` (`auto_reidentify_opt_out: bool`, `:16-28`) | the D-D toggle is unreachable without them (ND-4, PVL cycle 2) |
| T22 | `apps/api/routers/sites.py` | **+1 explicit copy** in `update_site` (`:330-389`), following the existing one-field-at-a-time `if body.X is not None:` style | ND-4 — `update_site` copies fields ONE BY ONE; a schema field with no handler line is silently ignored |
| T23 | `apps/api/models/reidentify_resolution_claim.py` + `apps/api/services/reidentify_claims.py` | **new** mapped PostgreSQL TTL lease model and its atomic helper | metadata registration, FK/cascade erasure, one provider-capable top-level dispatch per visitor |
| T24 | `apps/api/services/resolution_runner.py` | acquire/release the shared lease around every APScheduler `IdentityResolver.resolve()` provider path | S7 — scheduler is one of four human same-key claim lanes |
| T25 | `tests/integration/test_reidentify_resolution_leases.py` | **new human-domain lease/race owner** — manual, APScheduler, registered Celery, and new reidentify sweep; `identified` and `no_match` outcomes | S7 Hybrid proof; agent-company cannot same-key contend with these human-only lanes |
| T26 | `tests/integration/test_visitor_resolve_endpoint.py` | retain only endpoint-local `live_claim_returns_retry_in_progress_without_state_write` coverage | endpoint 409 contract; no cross-lane race ownership |
| T27 | `apps/api/tasks/resolution_tasks.py` | acquire/release the same lease in registered Celery `_process_site()` before each provider-capable `resolve()` | closes the dormant second sweep / Celery lane |
| T28 | `apps/api/services/promotion_sweep_runner.py` | call `resolve(..., deterministic_only=True)` and retain the defensive counter | enforce deterministic-only promotion; it is not a provider-capable lane |
| T29 | `apps/api/main.py` | import `ReidentifyResolutionClaim` with the create-all model imports | `Base.metadata.create_all()` must create the lease table in Hybrid tests and local fresh DBs |
| T30 | `tests/integration/test_promotion_sweep.py` | add the deterministic-only promotion condition gate | proves promotion cannot cross into paid providers |
| T31 | `tests/conftest.py` (read-only fixture contract) | no code change; its existing `import apps.api.main` before `Base.metadata.create_all()` is the required registration path | exact Hybrid fixture proof for T29 |
| T32 | `apps/api/services/agent_company_resolution.py::run_company_resolution_sweep` | materialize/reuse the agent-derived synthetic visitor; apply automatic defer eligibility; use the canonical monthly-usage check; then acquire the shared claim immediately before `IdentityResolver.resolve`; whenever that call returns non-`None`, invoke the canonical usage increment **once before** `_upsert_company`/link work; a resolver exception increments zero, while a later upsert/link exception retains that one increment; release its exact token in `finally` | S8 extends S7 agent-domain safety to the same paid-provider monthly-plan semantics as other automatic paths |
| T33 | `tests/unit/test_resolution_deferral_watermark.py` | add the source-census static guard with two domains: four human same-key lanes and one agent-company reentrancy lane | prevents a future resolver caller from silently escaping the claim/deterministic-only boundary (S7) |
| T34 | `apps/api/services/identity_providers/matching.py` | add default-compatible selected-IP activity input to the matching recency decision | a historical override uses the historical IP's event time, never global `Visitor.last_seen` |
| T35 | `tests/unit/test_identity_enrich_correctness.py` | add pure matching precedence/fallback coverage | selected activity supersedes global visitor activity only when supplied |
| T36 | `tests/integration/test_reidentify_sweep.py` | add PostgreSQL historical-IP graph-feed adversarial coverage | shared historical IP cannot attach a current stranger outside its own event window |
| T37 | `tests/integration/test_agent_company_resolution.py` | add real-PostgreSQL synthetic defer/outage-capped-repeat coverage | agent lane uses the same automatic defer semantics after materialization/reuse |
| T38 | `tests/unit/test_agent_company_resolution.py` | add monthly-plan blocked, success-metering, and split exception-accounting assertions; add the same-synthetic-key reentrancy assertion | S8 regression owner: blocked means no provider/claim/downstream work; resolver exception meters zero and exactly releases its token; a downstream upsert/link exception retains one prior increment, exactly releases its token, and retry cannot duplicate the increment |

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
| `Visitor` ORM | **+4** nullable/defaulted columns (`auto_reidentify_count`, `auto_reidentify_next_at`, `auto_reidentify_tried_ips`, `auto_reidentify_skip_count`) | additive; no reader breaks |
| DB schema | **+4** columns on `visitors`, +1 on `sites`, and `reidentify_resolution_claims` with inherited UUID `id`, `UNIQUE(site_id, visitor_id)`, opaque `owner_token`, and `expires_at`; `ForeignKeyConstraint((site_id, visitor_id) → visitors(site_id, visitor_id), ON DELETE CASCADE)` | additive; matches the repo's mapped-`Base` convention, is identifier-only, expires, and is erased with its visitor |
| `IdentityResolver.resolve()` / `resolve_auto_retry()` | `resolve()` retains its old `IdentifiedVisitor \| None` result for all existing callers. It adds defaulted `auto_retry=False`, `override_ip=None`, and `selected_ip_activity_at=None`; only `resolve_auto_retry(…, override_ip, selected_ip_activity_at)` returns `ResolutionAttemptResult`. | Default callers retain result and global-activity behavior; the retry sweep receives an explicit result plus the selected IP's event-time provenance. |
| 5 provider mixins | All five get defaulted `override_ip`; only Leadpipe and Capturify additionally receive defaulted `selected_ip_activity_at` and forward it to `MatchingMixin._record_matches_visitor`. | Defaulted ⇒ existing callers unchanged; PDL/IPinfo/RB2B/Hunter/Apollo semantics do not gain an unused time argument. |
| `MatchingMixin._record_matches_visitor()` | Add keyword-only `activity_at: datetime \| None = None`. When non-null, normalize this event timestamp by the existing naive/aware UTC rule and compare the record timestamp to it; when null, retain `_visitor_activity_utc(visitor)` exactly. | Internal additive contract; no caller or global `Visitor.last_seen` mutation is required. |
| `visitors.ip_address` (DB column) | **NEVER written by this feature** | the override is a parameter, not an assignment — gated by `::sweep_does_not_persist_chosen_ip` |
| `identity_status` mutation by the new sweep | `unresolvable` → `vpn_filtered` is REACHABLE via the IPinfo privacy check (`identity_resolver.py:611-620`) when the chosen IP is a v4 relay | disclosed, not new vocabulary; the attempt is still counted and `tried_ips` still appended (G11) |
| `POST /{site_id}/{visitor_id}/resolve` (manual) | now accepts `vpn_filtered` visitors when a non-relay untried IP exists (`routers/visitors.py:911-931`), returns 409 `retry_in_progress` on a live claim, and during an active outage defer still performs one immediate claimed retry; an unavailable result returns the existing HTTP 200 `{status: "anonymous", skip_reason: "provider_outage"}` outcome | widened acceptance; manual remains deliberately exempt from the scheduler/sweep defer filter (D-C / G7 / S7) |
| Shared claim service | `try_claim_resolution(...) -> ResolutionClaim | None`, `release_resolution_claim(...) -> None`; the owner token is compared on release | The **four human lanes** (manual retry, APScheduler `resolution_runner`, registered Celery `resolution_tasks`, reidentify sweep) same-key contend and share their race/meter proof. Agent-company holds the same kind of claim only against another agent-company execution for its synthetic key; it is structurally not a human-race competitor. |
| Agent-company automatic monthly-plan gate and metering | After synthetic materialization and automatic defer eligibility, load the owning `Site`; a missing site/owner or `check_usage_allowed(db, site.user_id) is False` is a fail-closed skip before claim and provider work. For a claimed winner, whenever `IdentityResolver.resolve(...)` returns a non-`None` result, call existing `increment_usage(db, site.user_id)` **exactly once** immediately before `_upsert_company` / `AgentVisit.resolved_company_id` work. | This deliberately matches `resolution_runner.py` and `resolution_tasks.py`: a resolver exception before a result meters zero and releases the exact owner token; a later upsert/link exception retains the one already-recorded increment, releases that exact token, and a retry must not add a second increment. It introduces neither a provider price nor a new entitlement rule. |
| Promotion sweep contract | `run_promotion_sweep_once()` calls `IdentityResolver.resolve(visitor, deterministic_only=True)` | deterministic pre-waterfall signals may promote; paid-provider work is structurally unreachable, so promotion neither acquires this lease nor participates in the four-human-lane race |
| `Site` ORM + `sites` table | +1 column `auto_reidentify_opt_out` (default **false** ⇒ every-site coverage preserved) | additive; consent escape hatch (D-D / G9) |
| `SiteUpdate` / `SiteOut` schemas + `PATCH /sites/{id}` | +1 optional request field, +1 response field `auto_reidentify_opt_out` | additive; both defaulted ⇒ existing clients unchanged (ND-4) |
| New sweep site selection | now ALSO requires `Site.tracking_enabled IS true` | a paused site is never swept (F6) — matches `resolution_runner.py:252-261`, commit `b2a7eef` |
| `revive_returning_unresolvable()` | early-return when flag on | flag off ⇒ byte-identical |
| `GET /visitors` + `GET /visitors/{id}` response | +`auto_reidentify_count: int` | additive field |
| `identity_status` vocabulary | **UNCHANGED — no new value** | see §7 below |
| New public functions | `rank_candidate_ips(...)`, `resolve_auto_retry(...)`, `run_reidentify_sweep_once(db)`, `run_reidentify_sweep()`, `try_claim_resolution(...)` | new surface only |
| Settings | +`auto_reidentify_enabled` (default **False**) + interval/cap/cadence constants | inert by default |

---

## Blast Radius

| Dimension | Value |
|---|---|
| Files changed | **47 planned source/test paths** — current T1–T38 ledger, counting the five override mixins and the task-local test owners; includes S7 agent-domain reentrancy/defer and S8 monthly-plan/metering coverage. |
| Packages | `apps/api` (models, services, migrations, config, jobs, schemas, routers), `apps/web` (4 typed/UI files), `tests` |
| Risk classes | **schema/data migration**, **identity/PII surface**, **paid-provider spend**, **scheduler** |
| High-risk verdict | YES — schema + budget + identity status. Hybrid-tier gate minimum applies to every area. |
| Contested files | `identity_resolver.py` (**2 params** — see the D-A supersede), `visitor_aggregator.py` (1 guard) |
| PII columns touched | **none written.** `visitors.ip_address` is read-only to this feature by construction (G1) |
| Rollback | flag OFF restores today's behavior with no code revert; migration is additive and down-reversible |

---

## Architecture Decisions

### AD-1 — State lives in FOUR additive columns on `Visitor` (T1/T2)

Follow migration `c2f7a9d31b64` exactly: additive, nullable-or-defaulted, **no index, no
constraint, no backfill** (its docstring `:19-25` justifies this posture).

| Column | Type | Purpose |
|---|---|---|
| `auto_reidentify_count` | `Integer NOT NULL server_default "0"` | lifetime attempts; **MONOTONIC** — no code path resets it |
| `auto_reidentify_next_at` | naive `DateTime NULL` | cadence watermark; **NULL = evaluate now** — which is why AD-6 puts NULL rows first, **with the NULL pool bounded to half the batch (C9, cycle 3)** |
| `auto_reidentify_tried_ips` | `JSONB NULL` | IPs already spent; ≤4 entries by construction |
| `auto_reidentify_skip_count` | `Integer NOT NULL server_default "0"` | futile-evaluation counter; retirement bound `< 8` (G5). **Added in PVL cycle 1; the "three columns" wording elsewhere was stale and is corrected in cycle 2 (C8/ND-5)** |

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
-- AUTHORITATIVE SELECTION ALGORITHM (PVL supplement 3 — replaces every older
-- single ORDER BY ... LIMIT 20 / NULLS FIRST|LAST description in this plan).
-- Shared base predicate in EVERY pool:
--   site_id = :site
--   AND identity_status IN ('unresolvable', 'vpn_filtered')
--   AND auto_reidentify_count < 4
--   AND auto_reidentify_skip_count < 8
--   AND do_not_resolve IS false
--   AND <site.auto_reidentify_opt_out IS false>
--   AND <site.tracking_enabled IS true>
--   AND <resolution_not_deferred_filter()>       -- retain resolver backoff state
--   AND <human_only_visitor_filter()>
--   AND <resolution_candidate_filter(...)>
--   AND NOT EXISTS active reidentify_resolution_claims row for this visitor

null_base = base AND auto_reidentify_next_at IS NULL
  ORDER BY intent_score DESC, visitor_id ASC
  LIMIT 10

due_base = base AND auto_reidentify_next_at <= :now
  ORDER BY auto_reidentify_next_at ASC, intent_score DESC, visitor_id ASC
  LIMIT 10

spillover = base AND visitor NOT IN (null_base UNION due_base)
  ORDER BY CASE WHEN auto_reidentify_next_at IS NULL THEN 0 ELSE 1 END,
           auto_reidentify_next_at ASC NULLS FIRST, intent_score DESC, visitor_id ASC
  LIMIT (20 - count(null_base) - count(due_base))

batch = null_base UNION ALL due_base UNION ALL spillover
```

This is the **only** two-pool shape. Each pool receives its first ten slots before spillover, so a
large NULL backlog cannot crowd out already-due rows. If either base pool has fewer than ten rows,
the other population refills the remaining capacity through `spillover`; no row can appear twice
because spillover excludes both base sets. There is no within-tick refill after claims are found
busy: a busy row is skipped without a stamp and the next tick runs the same algorithm. With twelve
NULL and twelve due rows, the first tick selects exactly ten from each pool; after those rows receive
their next watermark, the next tick selects the remaining two NULL and two due rows. This replaces
the contradictory 10/10 descriptions elsewhere.

**Resolver deferral is retained, never restored.** The base predicate intentionally has no
`resolution_defer_count = 0` term. `resolution_not_deferred_filter()` already excludes a row until
`resolution_deferred_until` passes (see `apps/api/services/resolution_eligibility.py:85-106`); the
resolver remains the sole writer of its count and timestamp (`identity_resolver.py:761-794`). The
sweep does not infer outage from a before/after counter and never clears that state.

**The real contention is the shared 50/site/day budget** — `check_daily_budget`
(`identity_resolver.py:589`) → `usage_limits.py:86-89`, a per-site distinct-visitor counter consumed
first-come-first-served by BOTH sweeps. The reserve check above is the mechanism: this sweep
**refuses to issue any further `resolve()` once 70% of the day's budget is already used**, reserving
the remainder for first-time identifies.

**The check is PER-VISITOR, not once per tick (C13, decided in PVL cycle 2).** A once-per-tick check
sitting in front of a `LIMIT 20` batch delivers only *"retries stop **starting** past 70%"*: on a
default 50/day budget a tick beginning at 0 used consumes 20 (40%), the next tick begins at 20
(< 35) and consumes 20 more (**80%**) before the third is refused. That is a real reservation but it
over-runs the stated ceiling, and the plan's prose read as a hard 70%. Therefore
`get_resolution_attempts_today(db, site_id) < ceil(0.70 * get_site_daily_budget(db, site_id))` is
re-evaluated **immediately before each `resolve()` inside the per-visitor loop**, and the remaining
rows in the batch are refused the same way. **Threshold formula, pinned in PVL cycle 3 (ND-3a):**
refuse when `attempts_today >= ceil(0.70 * budget)` — with the default budget of 50 the threshold is
the integer **35** (34 attempts ⇒ still allowed; 35 ⇒ refused). The site-level counter is still read
once at the top of the site's turn as a cheap early-out; it is the per-visitor re-read that is
load-bearing.

**A budget refusal STAMPS NOTHING — it is NOT a SKIP (ND-3b, PVL cycle 3, FINAL).** The earlier
mapping of a reserve refusal onto AD-8's skip row (`skip_count += 1`, `next_at = now + 7d`) was a
**self-annihilation bug on exactly the sites this feature targets**: on a chronically-busy site the
reserve refuses every tick, so every candidate accumulates 8 budget-skips over 8 weeks and is
**permanently retired by the `skip_count < 8` gate with zero IPs ever evaluated** — the same
"annihilates itself on the busy sites that need it" failure the G2b pre-check narrative already
names, re-entered through the retirement counter and previously undisclosed. Therefore:

- a budget refusal (site-level early-out **and** in-loop re-check, identical behaviour) writes
  **no `skip_count`, no `next_at`, no `tried_ips`, no attempt**;
- the row simply remains selectable on the next tick, and will be evaluated as soon as budget frees;
- **`skip_count` is strictly reserved for futile-IP evaluations** — a row that WAS evaluated and had
  no new untried IP. That is its G5 purpose and its only meaning. `do_not_resolve` / suppression
  pre-check misses keep the skip semantics (they are terminal properties of the visitor, not
  transient site conditions).

**Accepted N+1 cost (C13 residual, disclosed).** The per-visitor re-read costs up to ~21
`COUNT(DISTINCT …)` queries per site per tick (1 early-out + ≤20 in-loop). Accepted deliberately —
it is the same site-scoped daily meter the main sweep already runs, and any cached alternative
re-opens the leak this check exists to close.

**Residual TOCTOU against the concurrent main sweep (C13 residual, disclosed and accepted).** The
reserve is read-then-act with no lock, and the main sweep consumes the same meter concurrently, so
the day's total can land a few resolves past the 70% line in the worst interleave (~82% measured as
the bound in cycle 2's analysis). The honest guarantee is therefore: **auto-retries never
*start* past 70% of the daily budget**; concurrent main-sweep interleaving can land the day total a
few resolves past it. Tightening this would need a lock or a reservation table — deliberately out of
scope for a placeholder threshold.

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

**Dormant second sweep (G14 / S5).** SPEC Constraint 5 names the registered Celery-beat twin
(`apps/api/tasks/resolution_tasks.py::_process_site`, LIMIT 50). Its selection-status set remains
disjoint from the new retry sweep, so it needs no new reidentify selection query; it **does** require
the S5 shared per-visitor lease before its normal `resolve()` call. It already shares the same
50/site/day budget and remains counted by the existing meter.

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

**Site enumeration query shape (F6 residual, pinned in cycle 3).** This sweep is a **per-site loop**,
not a global visitor scan. Enumerate sites the way `apps/api/services/resolution_runner.py` does —
`select(Site).where(Site.tracking_enabled.is_(True))` (plus the `auto_reidentify_opt_out` term) — then
run the candidate query above once per site with `site_id` bound. **Donor divergence, named
explicitly:** `promotion_sweep_runner.py` is the donor for the *module shape* (lock, `run_X_once(db)`
/ `run_X()` split, per-row try/except) but **NOT** for the query — it issues one GLOBAL visitor query
with no per-site loop. Copying that shape here would make the per-site budget reserve, the per-site
`LIMIT 20`, and the two site gates unimplementable. Take the module skeleton from
`promotion_sweep_runner.py` and the enumeration from `resolution_runner.py`.

**`Site.tracking_enabled IS true` IS REQUIRED (F6, PVL cycle 2) — a different axis from the
`auto_identify_enabled` decision below.** Commit `b2a7eef` added a second, independent site gate to
the main sweep (`apps/api/services/resolution_runner.py:252-261`) with this rationale, quoted
verbatim:
>     # `tracking_enabled` is a second, independent gate: a paused site
>     # (manual toggle OR the inactivity auto-pause) must not burn
>     # resolver/enrichment/Gemini credits draining its existing backlog.
>     # Ingest already 204s for these sites, so the backlog is frozen —
>     # this is what makes a pause actually stop spend.

The two gates answer different questions: `auto_identify_enabled` is an **every-site policy** choice
(deliberately dropped here, see below), while `tracking_enabled` is a **pause** gate. Both are
honored — dropping the policy gate does not license spending on a paused site. D-D's
`auto_reidentify_opt_out` does **not** cover this: it is a manual column, whereas the inactivity
auto-pause (`Site.auto_paused_at`, `apps/api/models/site.py:60-68`) is automatic and silent, so a
customer who paused Beam would otherwise still be billed provider spend on historical IPs.
Gate: `::paused_site_never_swept` (Hybrid).

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


### AD-8 — Attempt accounting

**Restated in PVL cycle 1 (G2, G10).**

| Situation | `count` | `skip_count` | `next_at` | `tried_ips` |
|---|---|---|---|---|
| Ranker found a new untried IP → `resolve()` actually issued to a provider | **+1** | unchanged | `now + 7d` | append the IP |
| No new untried IP (evaluated, skipped) | unchanged | **+1** | `now + 7d` | unchanged |
| **PRE-CHECK miss — `do_not_resolve` / suppressed** (no provider call made) | unchanged | **+1** | `now + 7d` | **unchanged** |
| **BUDGET REFUSAL** — the D-B reserve or `check_daily_budget` refuses (no provider call made) | unchanged | **unchanged** | **unchanged** | **unchanged** — **stamps NOTHING (ND-3b); the row stays selectable next tick** |
| `ResolutionAttemptResult.outcome == "provider_unavailable"` at stages 1–4 | unchanged | unchanged | unchanged | unchanged — retain the resolver's committed `resolution_defer_count` / `resolution_deferred_until`; release only the claim |
| `ResolutionAttemptResult.outcome == "provider_unavailable"` after stage 4 | unchanged | unchanged | unchanged | unchanged — keep `resolution_defer_count` capped at `len(RESOLUTION_DEFER_BACKOFF)`, write a fresh `resolution_deferred_until = now + RESOLUTION_DEFER_BACKOFF[-1]`, retain the visitor status, and release only the claim |
| The call raised | unchanged | unchanged | **`now + backoff`** (G10) | unchanged |

**PVL supplement 3 supersession — no state inference.** The older paragraphs below that describe a
compare-and-set restore are historical rejected design, not implementation instructions. The exact
signal is `ResolutionAttemptResult.outcome == "provider_unavailable"`, sourced from the existing
`RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE` taxonomy in
`apps/api/services/identity_providers/base.py:19-45`. The resolver alone owns its backoff writes at
`apps/api/services/identity_resolver.py:761-794`; no sweep or manual endpoint may reset, restore, or
otherwise write `resolution_defer_count` / `resolution_deferred_until`.

**Historical correction.** Earlier cycles proposed detecting an outage from mutated visitor fields
and clearing them with a compare-and-set restore. That proposal is deleted, including its race gate:
it destroys the resolver's watermark and can turn sustained provider failure into a hot loop. The
sole executable outage flow is S4-2: the resolver returns explicit
`provider_unavailable`, keeps its committed defer state, and the caller releases its claim without
attempt accounting. After the finite 15m/1h/6h/24h ramp, it repeats the capped 24-hour outage
watermark rather than clearing state and terminalising the visitor. The existing eligibility predicate
prevents another provider call until that watermark is due; the Hybrid outage gate proves every ramp
stage plus one capped-repeat outage, not every tick.

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
**Predicate NARROWED in PVL cycle 2 (ND-3, decided): the visitor's CURRENT `visitor.ip_address`
must itself be non-relay.** The original "a non-relay untried IP exists *anywhere in the visitor's
history*" predicate would have shipped a **dead button**. Traced kill chain, verified live:

1. `routers/visitors.py:960` calls `IdentityResolver(db).resolve(visitor, force_retry=is_retry)` —
   **no `override_ip` argument.** The manual lane is not threaded with D-A's override; only the
   sweep passes it.
2. `resolve()` therefore evaluates the relay guard against `visitor.ip_address`:
   `if is_privacy_relay_ip(visitor.ip_address):` (live `identity_resolver.py:644`) →
   sets `identity_status = "vpn_filtered"`, commits, `return None`.
3. So for a visitor whose *stored* IP is the relay, clicking Retry re-runs the exact guard that
   produced the status and returns to the same badge — zero provider calls, zero state change, a
   button that visibly does nothing.

Narrowing the predicate to the **current** IP makes the button render **only when the click can
actually reach a provider**. Concretely: enable manual retry for `vpn_filtered` when
`visitor.ip_address` is non-empty and `is_privacy_relay_ip(visitor.ip_address)` is False — the same
pure, network-free check (`company_resolver.py:233-243`), evaluated in the endpoint before setting
`is_retry`. The UI branch (T20) renders the button on exactly that condition. Manual Retry remains
exempt from the cap and still never resets the counter.

**Deferred to backlog (future scope, NOT this plan):** letting a human retry a *historical* non-relay
IP requires threading `override_ip` through the manual lane too — a **7th** consumption site plus a
`routers/visitors.py` endpoint change (choose-the-IP UI or server-side ranker call). Stub:
`process/features/visitors-identity/backlog/manual-retry-override-ip_NOTE_11-08-26.md`. Until that
lands, a `vpn_filtered` visitor whose current IP is a relay is served by the **automatic** sweep
only — which is the lane that does have `override_ip`.

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

**API surface required (T21/T22, ND-4 — PVL cycle 2).** The column alone does not make the toggle
work. `update_site` (`apps/api/routers/sites.py:330-389`) copies fields **one by one**
(`if body.description is not None: … if body.tracking_enabled is not None: …`), so a `SiteUpdate`
field with no matching handler line is accepted by validation and then silently dropped. Therefore
this plan must add: the field to `SiteUpdate` **and** `SiteOut` (`apps/api/schemas/sites.py`), and
one `if body.auto_reidentify_opt_out is not None: site.auto_reidentify_opt_out = …` line in
`update_site`.

> **WARNING (execute-agent).** The `tracking_enabled` branch in that same handler (`:347-353`,
> commit `b2a7eef`) ALSO clears `site.auto_paused_at` as a deliberate side effect ("any explicit
> owner write clears the auto-pause stamp, in both directions"). The new
> `auto_reidentify_opt_out` branch must be a **separate, independent `if`** that touches
> `auto_paused_at` in **neither** direction. Toggling re-identify opt-out is not a pause decision.

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

### AD-15 — Provider-capable caller census, two claim-safety domains, and selected-IP provenance (S7)

The global concurrency guarantee is deliberately scoped to **provider-capable top-level resolver
dispatch**, not to every call that happens to share the `IdentityResolver` class. The complete live
caller inventory is:

| Classification | Exact current source entry point | Can reach paid providers after this plan? | Required action / reason |
|---|---|---|---|
| Shared claim | **Manual** — `apps/api/routers/visitors.py::resolve_one_visitor` | Yes | Acquire after existing ownership/privacy/candidate/monthly-plan checks and before any retryable terminal-state mutation or `resolve(force_retry=True)`; release its exact token in `finally`. A busy claim returns 409 `retry_in_progress` with no visitor-state write. |
| Shared claim | **APScheduler** — `apps/api/services/resolution_runner.py::run_resolution_for_site` | Yes | Acquire/release per selected visitor after the monthly-plan gate and immediately before `processed += 1` / `resolve()`; a busy claim increments only `claim_busy`. |
| Shared claim | **Registered Celery** — `apps/api/tasks/resolution_tasks.py::_process_site`, reached by `process_all_pending_visitors` and `process_single_site` | Yes | Acquire/release after the monthly billing gate and immediately before `resolve()`; a busy claim has no resolver, billing, enrichment, social-intelligence, auto-draft, or segmentation side effect. |
| Agent-domain claim, not a human-race lane | **Agent-company sweep** — `apps/api/services/agent_company_resolution.py::run_company_resolution_sweep`, registered through `apps/api/jobs/scheduler.py::_agent_verification_sweep_job` | Yes | `_get_or_create_synthetic_visitor()` makes `visitor_id = "agent:{AgentVisit.id}"` and `is_agent_derived=True`; the four human lanes select with `human_only_visitor_filter()`, so they can never same-key contend. After materialization/reuse, evaluate the same defer deadline as automatic lanes (`resolution_deferred_until is NULL or <= now`) before taking the claim; then acquire immediately before `resolver.resolve(visitor, source_agent_visit_id=...)`, and release the exact token in `finally` around resolver plus company/link side effects. A busy claim increments only non-PII `claim_busy`, then continues: no resolver/provider work, `_upsert_company`, `AgentVisit.resolved_company_id` change, billing/enrichment/defer/retry mutation, or downstream effect. |
| Shared claim (new) | **New retry sweep** — `apps/api/services/reidentify_sweep_runner.py::run_reidentify_sweep_once` (not present in current source; created by T4) | Yes | Acquire/release after rank/pre-check/reserve and immediately before `resolve_auto_retry()`. |
| Deterministic-only | `apps/api/services/promotion_sweep_runner.py::run_promotion_sweep_once` | **No — enforced by this plan** | Change its direct call to `resolve(visitor, deterministic_only=True)`. That return occurs before paid-provider gates; it takes no lease. The condition test must fail if a paid provider or claim helper becomes reachable. |
| Out of scope — distinct public demo wrapper | `apps/api/routers/demo.py::demo_identify` | Yes, through private `_call_*` mixin helpers, **not** `IdentityResolver.resolve()` | It operates on a `SimpleNamespace`, has no persisted `Visitor` identity/status/claim key, and uses the demo budget rather than the visitor-resolution meter. Do not fold it into this lease; any future unification must be a separately scoped public-demo contract change. |
| Out of scope — inbound provider result | `apps/api/services/leadpipe_webhook.py` calling `IdentityResolver._save_identified(...)` | No | The provider request has already occurred upstream; this is persistence/quality-gate reuse, not a provider dispatcher. No claim or deterministic-only action. |
| Out of scope — trigger-only wrappers | `apps/api/jobs/scheduler.py::_resolution_sweep_job`, `apps/api/jobs/run_sweep_once.py`, `apps/api/routers/visitors.py::resolve_site_visitors`, `apps/api/routers/visitors_helpers.py::_run_resolution_job`, and `apps/api/services/celery_app.py` beat configuration | No direct resolver/provider call | These delegate only to the named APScheduler/Celery/agent-company shared-claim lanes. They must not take a second claim; tests trace through their target lane. |

The same census also records the temporal-provenance path. `reidentify_sweep_runner` groups unflagged
`Event` rows by `ip_address` and must include `MAX(Event.created_at)` as `IpEvidence.last_activity_at`.
The pure ranker preserves that value on the chosen evidence. The sweep passes it to
`resolve_auto_retry(..., override_ip=chosen.ip, selected_ip_activity_at=chosen.last_activity_at)`;
the resolver forwards it only to Leadpipe/Capturify graph-feed matching. Their calls compare a record
timestamp to this selected-IP event time, not to the unrelated current global `Visitor.last_seen`.
When no selected timestamp is supplied, `MatchingMixin` continues to use visitor activity exactly as
today. Never assign `Visitor.last_seen` or `Visitor.ip_address` to simulate this context.

`reidentify_resolution_claims` is a mapped `ReidentifyResolutionClaim(Base)` model in
`apps/api/models/reidentify_resolution_claim.py`. It uses Base's normal UUID primary key plus a
unique `(site_id, visitor_id)` conflict key — not a second composite primary key — and a composite
`ForeignKeyConstraint` to the existing `visitors(site_id, visitor_id)` unique key with
`ondelete="CASCADE"`. `apps/api/main.py` must import the model alongside its existing create-all
imports. This is mandatory because `tests/conftest.py` imports `apps.api.main` immediately before
`Base.metadata.create_all()`; importing the model only in an on-demand service would make Hybrid
fixtures omit the table.

The migration creates the empty child table with this FK in the same DDL operation; there is no
pre-existing claim data and no backfill, so an orphan-data preflight is neither meaningful nor
permitted. Its proof is the Hybrid metadata/create-all/cascade test in S5-4: create a visitor and
claim, delete the visitor through the normal ORM path, then query a fresh session and require zero
claims. Downgrade drops the child table before removing the new visitor/site columns.

---

## High-level Data Flow

```
APScheduler (every N min, flag ON)
   └─► run_reidentify_sweep()                       [new module, own advisory lock, fail-open]
         └─► run_reidentify_sweep_once(db)
               ├─ SELECT ≤20 visitors using the AD-6 authoritative two-pool query
               │                        (first 10 NULL `next_at`, first 10 due `next_at`,
               │                        then deterministic spillover; shared not-deferred,
               │                        human, candidate, tracking, opt-out and no-live-claim terms)
               ├─ SITE EARLY-OUT (cheap): attempts_today >= 0.70 * budget ──► skip the site this tick
               └─ per visitor (try/except/continue):
                    ├─ RESERVE RE-CHECK (D-B, per-visitor — C13):
                    │    attempts_today >= 0.70 * site_daily_budget ──► SKIP (no resolve())
                    ├─ TRY SHARED CLAIM before provider work; live lease ──► BUSY: no stamp
                    ├─ PRE-CHECKS (consume nothing): check_daily_budget / do_not_resolve /
                    │    suppression ──► SKIP: next_at=now+7d, skip_count+=1, count + tried_ips unchanged
                    ├─ GROUP BY ip_address over events   [ix_events_site_visitor, NOT is_flagged_abuse]
                    ├─ asn is None ──► tier "unknown"     [SHORT-CIRCUIT; classify_ip_org_kind NOT called]
                    ├─ lookup_asn → classify_ip_org_kind  [sync, never raises]
                    ├─ _read_company_graph                [only if company_graph_enabled]
                    ├─ rank_candidate_ips(...)            [PURE — tiers, exclusions, 8-key tiebreak]
                    ├─ chosen is None ──► SKIP: next_at=now+7d, skip_count+=1, count unchanged
                    └─ chosen ────────► await resolver.resolve_auto_retry(..., override_ip=chosen)
                                        (IP-only; visitor.ip_address is NEVER assigned — G1)
                                        provider_unavailable ────► retain resolver defer watermark;
                                                                     no accounting; release claim
                                        raised ──────────────────► next_at = now + backoff only
                                        otherwise provider work ─► count += 1; next_at = now + 7d;
                                                                     tried_ips.append(chosen)
                                        finally ─────────────────► release claim
```

Flag OFF ⇒ the job is never registered, `revive_returning_unresolvable` behaves exactly as today,
`resolve()` is called with `auto_retry` / `override_ip` defaulted, and the four new columns sit
unread.

---

## Phase Completion Rules

A phase is complete ONLY when all five hold:

1. **Integration test** — works end-to-end with the pieces around it.
2. **Manual test** — a human (or agent probe) can observe the intended behavior.
3. **Database/state check** — the **four** new `Visitor` columns (`auto_reidentify_count`,
   `auto_reidentify_next_at`, `auto_reidentify_tried_ips`, `auto_reidentify_skip_count`) actually
   hold the values the AD-8 accounting table says (L1 — the stale "three columns" wording is
   corrected here in cycle 3; the fourth was added in cycle 1 by G5).
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
- [ ] 1.3 Create `apps/api/models/reidentify_resolution_claim.py` as
      `ReidentifyResolutionClaim(Base)` with Base's inherited UUID primary key, an explicit unique
      `(site_id, visitor_id)` key for the atomic claim conflict, opaque UUID `owner_token`, naïve-UTC
      `expires_at`, and `ForeignKeyConstraint([site_id, visitor_id], [visitors.site_id,
      visitors.visitor_id], ondelete="CASCADE")`. Import that model in `apps/api/main.py` beside its
      existing create-all imports; do not rely on `apps/api/models/__init__.py`, which `main.py` does
      not import.
- [ ] 1.4 Write the additive migration chained off the live head: four Visitor columns, Site opt-out,
      and the empty cascade-erased `reidentify_resolution_claims` table with the exact mapped FK/UQ
      shape from AD-15. No backfill and no orphan preflight: the child table is new and empty. Its
      downgrade drops the child table before dropping the new parent columns; its docstring follows
      `c2f7a9d31b64:19-25` for the additive/no-backfill rationale.
- [ ] 1.5 Prove down/up round-trip on a **disposable** Postgres (never the shared dev container) and
      run the create-all registration/cascade gate from S5-4 through the existing `test_engine`
      fixture.
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
- [ ] 3.3 Add `override_ip: str | None = None` and `selected_ip_activity_at: datetime | None = None`
      to `resolve()` (D-A / S7). Use
      `override_ip or visitor.ip_address` at `:593`, `:602`, `:611`, `:652`, `:691`, `:695` and pass
      it through the existing provider flow. Forward `selected_ip_activity_at` only to Leadpipe and
      Capturify graph-feed matching; default `None` retains visitor-global activity for every ordinary
      caller. **Assert by review that no code path assigns `visitor.ip_address` or `visitor.last_seen`.**
- [ ] 3.4 Thread `override_ip` into the five provider mixins — `identity_providers/pdl.py:74`,
      `ipinfo.py:144`, `rb2b.py:182`, `capturify.py:82`, `leadpipe.py:175` — defaulted so every
      existing caller is unchanged. In `identity_providers/matching.py`, add only a defaulted
      keyword-only activity override to `_record_matches_visitor`; normalize it like existing visitor
      activity and prefer it only when provided. Leadpipe/Capturify must pass their effective override
      IP for equality and this activity value for recency; no other mixin receives a gratuitous time
      parameter.
- [ ] **Test gate 3:** `.venv/bin/python -m pytest tests/unit/test_identity_resolver_parallel.py -q`
      green (incl. the `deterministic_only` invariant at `:745-759`).

### Phase-04 — Sweep runner + shared lease (T4, T23–T26) — ⏳ PLANNED

- [ ] 4.1 Create `apps/api/services/reidentify_sweep_runner.py` on the
      `promotion_sweep_runner.py` shape: `_SWEEP_LOCK_KEY`, advisory lock fail-open,
      `run_reidentify_sweep_once(db)` + `run_reidentify_sweep()`, per-row try/except/continue.
- [ ] 4.1a Create `apps/api/services/reidentify_claims.py` against the mapped model in AD-15. Its
      only claim SQL entry points are `try_claim_resolution(...)` and
      `release_resolution_claim(...)`; no caller may open-code insert/expiry-replace/delete. Manual,
      APScheduler, registered Celery, and `run_reidentify_sweep_once` form the four-human same-key
      contention domain. Agent-company uses the same helper only against its own synthetic key after
      candidate materialization and defer eligibility; it is not a fifth human competitor. Every
      winner releases its exact token in `finally`.
- [ ] 4.1b Update `apps/api/services/resolution_runner.py`: after the monthly-plan check and before
      incrementing `processed` or calling `IdentityResolver.resolve`, acquire the shared claim; on a
      busy claim increment only `claim_busy` and continue. Add `claim_busy` to site and aggregate
      counters; provider/billing/enrichment/retry accounting remains untouched on the losing lane.
- [ ] 4.1c Update `apps/api/tasks/resolution_tasks.py::_process_site`: after its existing per-visitor
      `check_usage_allowed` gate and before `IdentityResolver.resolve(visitor)`, acquire the same
      lease. A busy claim continues without calling resolver, `increment_usage`, `enrich_tier1`,
      social intelligence, auto-draft, or segmentation. A winning token is released in `finally`
      around the resolver-owned work; add an internal `claim_busy` counter to its returned/logged
      per-site result without exposing visitor IDs, IPs, or tokens.
- [ ] 4.1d Update `apps/api/services/promotion_sweep_runner.py` to call
      `IdentityResolver.resolve(visitor, deterministic_only=True)`. Do **not** acquire this lease in
      promotion: the deterministic barrier is the enforceable reason it cannot race a paid dispatch.
      Retain `unexpected_paid` as a defensive invariant counter, but it must stay zero because the
      paid waterfall is unreachable rather than merely detected after spend.
- [ ] 4.1e Update `apps/api/services/agent_company_resolution.py::run_company_resolution_sweep` as
      an **agent-domain reentrancy** claimant, not a fifth human-race lane. Preserve AgentVisit
      eligibility and synthetic-visitor materialization/reuse; before claim, apply automatic defer
      semantics to that synthetic visitor: if `resolution_deferred_until` is future, increment only
      non-PII `deferred` and continue without resolver/provider/company/link work. If eligible, acquire
      immediately before `resolver.resolve(...)`. A busy claim increments only `claim_busy` and
      continues — no resolver, `_upsert_company`, `AgentVisit.resolved_company_id`, billing,
      enrichment, resolver-defer/retry write, or downstream side effect. Release the exact owner token
      in `finally` around resolver and dependent company work for identified, no-match,
      provider-unavailable, and exception paths.
- [ ] 4.1f **(S8 — monthly plan parity, required)** In the same agent-company per-row sequence,
      after materialization/reuse and the S7 automatic-defer check but **before**
      `try_claim_resolution(...)`, load the `Site` by `AgentVisit.site_id`. If the site or its
      `user_id` is unavailable, or `await check_usage_allowed(db, site.user_id)` is false, increment
      only `skipped_plan_limit` (or `billing_unavailable` for absent ownership) and continue. Do not
      call the claim helper, resolver, provider mixin, `_upsert_company`, set
      `AgentVisit.resolved_company_id`, enrich, or increment usage. Log only the stable non-PII
      `site_id`, AgentVisit id, and reason/counters — never IP, email, domain, provider payload, or
      owner identifier.

      For the claimed owner only, retain the existing resolver call. Whenever it returns a non-`None`
      row, call the existing `increment_usage(db, site.user_id)` **exactly once**, immediately before
      `_upsert_company` and AgentVisit linking, matching the current automatic paths' success-side
      placement. A resolver exception before that non-`None` result meters **zero** and its `finally`
      releases the exact owner token. If `_upsert_company`, the company lookup, or AgentVisit linking
      then raises, retain the already-recorded **one** increment, release that exact token, and ensure
      the next retry cannot call `increment_usage` again for that resolved attempt. Do not meter a
      busy claim, defer, plan block, no-match, provider-unavailable result, or pre-provider resolver
      skip. A losing reentrant agent worker never meters and never releases the winning token. Do not
      add pricing, a new quota, or a second billing helper.
- [ ] 4.2 Write the selection query per AD-6. **Both new gates as columns in the WHERE clause.**
      Reuse `resolution_not_deferred_filter()`, `human_only_visitor_filter()`,
      `resolution_candidate_filter(...)` verbatim.
- [ ] 4.3 Implement **exactly** the AD-6/S3-3 CTE (or equivalent single-statement) shape: first ten
      NULL rows and first ten due rows, then deterministic spillover limited to the unused capacity.
      Do not use a single `NULLS FIRST/LAST` order and do not re-query either primary pool for refill;
      spillover excludes both primary result sets, so every selected visitor is unique.

      **Why:** AD-1 defines NULL as "evaluate now", so a never-evaluated visitor is genuinely
      maximally overdue — but a plain `NULLS FIRST` on a large cold-start backlog lets the NULL pool
      monopolise every batch until it drains, starving due rows entirely. The split **bounds
      due-row starvation to 50% throughput worst case** while the NULL pool drains, and it costs
      nothing once the backlog is gone (the NULL pool returns 0 and the due pool takes all 20). The
      NULL pool is finite and self-draining: each evaluation stamps a `next_at`. Cold-start drain
      math and the operator-visible gate are in §Open Risks R9 and §Measurement Gap.
      (G4/G5 — the old "never-attempted first" ordering is DELETED as vacuous and actively harmful).
      **Never introduce `jsonb_array_length(auto_reidentify_tried_ips)` into any ORDER BY** — that
      would turn R2's harmless unindexed JSONB read into a computed sort over the whole filtered
      candidate set before LIMIT (execute-agent instruction E4).
- [ ] 4.3b Add `auto_reidentify_skip_count < 8`, the `site.auto_reidentify_opt_out IS false` join
      term (G2 / G5 / G9), **no live claim** exclusion, `resolution_not_deferred_filter()`, and
      `Site.tracking_enabled.is_(True)` (F6)** to the WHERE clause. Mirror the comment block at
      `apps/api/services/resolution_runner.py:252-261` (commit `b2a7eef`) so the pause rationale
      travels with the code. Do not add `resolution_defer_count = 0`: the resolver's defer watermark
      is retained until `resolution_not_deferred_filter()` makes it due again.
- [ ] 4.3c Implement the **budget reserve** (D-B / G4) as a **PER-VISITOR check inside the loop**
      (C13): immediately before each `resolve()`, refuse when
      `get_resolution_attempts_today(db, site_id) >= ceil(0.70 * get_site_daily_budget(db, site_id))`
      (**ND-3a**: integer threshold, `ceil`, `>=`; budget 50 ⇒ threshold 35). Keep the same check
      once at the top of the site's turn as a cheap early-out. **Do not implement it as a
      once-per-tick check only** — that leaks to ~80% of a 50/day budget across two `LIMIT 20` ticks.
      **A budget refusal STAMPS NOTHING (ND-3b, FINAL).** No `skip_count` increment, no `next_at`
      advance, no `tried_ips` append, no attempt. The row simply remains selectable on the next tick.
      This holds identically for BOTH detection points (the site-level early-out and the in-loop
      re-check). `skip_count` is strictly reserved for **futile-IP evaluations** — its G5 purpose.
      **Accepted N+1 cost (C13 residual):** the per-visitor re-read means up to ~21
      `COUNT(DISTINCT …)` queries per site per tick (1 early-out + ≤20 in-loop). Accepted
      deliberately: the query is the site-scoped daily meter already run by the main sweep, and the
      alternative (a cached count) re-opens the leak this check exists to close.
      **Label the 0.70 as a PLACEHOLDER in code, to be tuned from measured data** — mirror the
      wording used for `job_change_recheck_daily_cap`.
- [ ] 4.3d Implement the **pre-checks** (G2b): `check_daily_budget`, `do_not_resolve`, and the
      suppression list are evaluated BEFORE `resolve()` is called. A miss is a SKIP — no attempt
      consumed, **no `tried_ips` append**.
- [ ] 4.4 Implement the async evidence gatherer: one `GROUP BY ip_address` (`NOT is_flagged_abuse`),
      `MAX(scroll_depth)`, `AVG(time_on_page) FILTER (WHERE time_on_page > 0)`, `distinct_days`,
      `pageview_count`, `MAX(Event.created_at) AS last_activity_at`, `last_seen`, `country_code`; then
      `lookup_asn` → `classify_ip_org_kind`; then flag-gated `_read_company_graph`. Add
      `last_activity_at` to `IpEvidence` and preserve the selected evidence, not only its string IP.
      Pass that exact event timestamp into `resolve_auto_retry`; never overwrite `Visitor.last_seen`.
- [ ] 4.5 Implement attempt accounting per AD-8/S4-2: `override_ip=chosen` passed only to
      `resolve_auto_retry()`, conditional success/no-match accounting only after `provider_work_started`,
      and explicit `provider_unavailable` retaining the resolver defer state with no ledger stamp;
      **no assignment to `visitor.ip_address` anywhere**, `skip_count` increment on every SKIP, and
      a `next_at` backoff advance on the exception path (G10).
- [ ] 4.5b On every outcome, the **four human same-key lanes** release the held lease in `finally`;
      agent-company separately releases the held synthetic-key lease in its own `finally`;
      promotion is deliberately absent because `deterministic_only=True` makes paid work unreachable.
      A claim conflict
      does not call a provider and does not write retry, resolver-defer, billing, or enrichment
      state. The manual lane returns its documented 409 conflict and leaves the terminal-state
      transition untouched; APScheduler/Celery conflicts increment only their local `claim_busy`.
- [ ] 4.6 Log keys/ids/counts only — **never an IP, never an email** (SPEC AC-10).
- [ ] 4.7 Write unit coverage for explicit resolver outcomes, IP-only auto retry (including the
      negative prior-signal spies), exception non-increment, skip stamping, and
      **`::reserve_blocks_second_batch_at_70pct`**. **Threshold formula, FINAL:** the reserve refuses when
      `attempts_today >= ceil(0.70 * budget)`. With the default budget of 50 the threshold is
      **35**. The gate seeds `attempts_today = 34` (an explicit integer, not "69% of budget"): the
      NEXT `resolve()` is **ALLOWED** (34 < 35), and the one after it is **REFUSED** (35 >= 35).
      Assert exactly that two-step sequence — one allowed, then refused, with no attempt consumed and
      no ledger stamp on the refusal (ND-3b). Hybrid integration owns outage re-entry, claim races,
      and the two-pool query because they need transactional Postgres behavior.
- [ ] 4.8 Write `tests/integration/test_reidentify_sweep.py` — full cycle, cap enforcement, 7-day
      gate, skip-no-new-IP, `vpn_filtered` pickup, **agent-origin exclusion in the new status set**,
      `do_not_resolve`, `::opt_out_site_never_selected`, `::retries_do_not_exhaust_first_identify_budget`,
      `::sweep_does_not_persist_chosen_ip` (DB `ip_address` unchanged on success / outage / exception),
      `::erasure_removes_tried_ips`, **`::paused_site_never_swept`** (F6 — `tracking_enabled=false`
      by manual toggle AND by inactivity auto-pause; assert zero `resolve()` calls and zero budget
      consumption), `::test_provider_unavailable_defers_through_ramp_and_repeats_cap`, and the
      sole allocation proof `::test_two_pool_ten_each_and_spillover`.
- [ ] 4.8a Create `tests/integration/test_reidentify_resolution_leases.py` with exactly
      `test_four_human_lane_lease_race_identified_once`,
      `test_four_human_lane_lease_race_no_match_one_distinct_daily_meter_visitor`, and
      `test_claim_model_registered_by_create_all_and_cascades`. It alone owns human-domain cross-lane
      races and mapped-table fixture proof. In `tests/unit/test_agent_company_resolution.py`, add
      `test_agent_company_held_claim_is_side_effect_free_and_releases_exact_token`: a Fully-Automated
      mock holds a synthetic-key claim and proves no resolve/_upsert/link/downstream work. Create
      `tests/integration/test_agent_company_resolution.py::test_agent_company_honors_defer_before_claim_with_outage_capped_repeat`: its real-PostgreSQL fixture proves a materialized/reused synthetic
      visitor with future defer is skipped before claim, while all-provider outage retains/advances the
      capped watermark and later eligibility resumes exactly once. Keep
      `test_visitor_resolve_endpoint.py` to endpoint-local 409 plus immediate-defer manual outcome
      proof.
- [ ] 4.8b Extend `tests/integration/test_visitor_resolve_endpoint.py` with
      `test_manual_retry_runs_during_active_defer_and_reports_provider_outage`: a future
      `resolution_deferred_until` must not suppress a claimed manual call; after configured providers
      are forced unavailable, assert HTTP 200, `status == "anonymous"`,
      `skip_reason == "provider_outage"`, no `ResolutionLog`/distinct-meter increment, retained or
      capped defer state, and exact-token release.
- [ ] 4.8c Extend `tests/integration/test_promotion_sweep.py` with
      `test_promotion_sweep_is_deterministic_only_and_never_claims_lease`: seed a UTM click and use
      spies that fail if paid-provider work or claim acquisition is reached; assert the resolver was
      called with `deterministic_only=True`, deterministic promotion still succeeds, and
      `unexpected_paid == 0`.
- [ ] 4.8d Extend `tests/unit/test_resolution_deferral_watermark.py` with
      `TestProviderCapableResolverCallerCensus`. It must scan live `apps/api/**/*.py` source for (a)
      imports/construction of `IdentityResolver`, (b) awaited direct and receiver-variable
      `.resolve(...)` calls, and (c) direct private provider-mixin wrapper calls. Compare every
      discovered runtime source file to one explicit manifest classification: four-human shared-claim
      lanes, agent-domain reentrancy claimant, promotion deterministic-only, public demo out-of-scope,
      Leadpipe webhook out-of-scope, or a
      trigger-only delegate. The guard fails for an unclassified discovery, a missing expected source,
      a human shared lane without both claim helper names plus `finally`, an agent caller without
      synthetic/defer-before-claim/finally markers, a promotion caller without
      `deterministic_only=True`, or an out-of-scope entry whose stated structural reason disappears.
      It must include the new reidentify file only after T4 creates it; no test fixture may hide that
      path from source discovery.
- [ ] 4.8e Add selected-IP temporal provenance tests. Unit:
      `tests/unit/test_identity_enrich_correctness.py::test_selected_ip_activity_precedes_global_last_seen`
      proves the optional matching argument wins, and `::test_no_selected_activity_keeps_global_last_seen`
      proves old callers retain existing behavior. Hybrid PostgreSQL:
      `tests/integration/test_reidentify_sweep.py::test_historical_selected_ip_rejects_current_graph_record_outside_event_window`
      seeds visitor A's past event on IP X and current global activity on IP Y, then a current
      Leadpipe/Capturify-style person B record at X; it must be rejected because B is outside X's
      30-minute event window. The paired `::test_historical_selected_ip_allows_graph_record_inside_event_window`
      puts B within X's window and permits matching. Both assert the persisted `Visitor.last_seen`
      remains Y throughout.
- [ ] 4.8f **(S8 regression gates)** Extend `tests/unit/test_agent_company_resolution.py` with
      `test_agent_company_plan_limit_skips_provider_claim_and_downstream`,
      `test_agent_company_success_increments_usage_once_before_downstream`,
      `test_agent_company_resolver_exception_does_not_meter_and_releases_exact_token`, and
      `test_agent_company_downstream_exception_meters_once_releases_exact_token_and_retry_does_not_duplicate`.
      The plan-limit gate stubs the canonical check false and asserts zero resolver, claim, provider,
      upsert/link, and increment calls plus only safe observability. The success gate stubs one
      non-`None` resolver result and asserts exactly one `increment_usage` await ordered before
      upsert/link. The **pre-success resolver-exception** gate raises from `resolver.resolve`, asserts
      zero `increment_usage` awaits and one exact owner-token release. The **post-success downstream-
      exception** gate returns non-`None`, raises from `_upsert_company` or link work, asserts the
      increment occurs exactly once before the failure and one exact owner-token release, then retries
      the same resolved attempt and asserts no duplicate increment. Run the existing held-claim
      exact-token test to prove a busy contender meters zero times. Extend the Hybrid
      `tests/integration/test_agent_company_resolution.py` owner with
      `test_agent_company_same_synthetic_claim_race_meters_once`: two concurrent sweeps for the same
      AgentVisit/synthetic key produce one provider-capable dispatch and one monthly-usage increment;
      the non-owner performs no downstream work. This test is the race oracle — do not use global
      `ResolutionLog` rows as an accounting proxy.
- [ ] 4.9 **EDIT** `tests/unit/test_agent_company_resolution.py:515-520` — append
      `apps/api/services/reidentify_sweep_runner.py` to `_AC2_FILES` (G3). The plan previously cited
      `tests/unit/test_agent_origin_exclusion.py:236-247`, which asserts a **different literal**
      (`source_agent_visit_id`) and would never have covered this module.
- [ ] **Test gate 4:** `.venv/bin/python -m pytest tests/integration/test_reidentify_sweep.py -q`,
      `.venv/bin/python -m pytest tests/integration/test_reidentify_resolution_leases.py -q`,
      `.venv/bin/python -m pytest tests/integration/test_visitor_resolve_endpoint.py -q`, and
      `.venv/bin/python -m pytest tests/integration/test_promotion_sweep.py -q`, then
      `.venv/bin/python -m pytest tests/unit/test_resolution_deferral_watermark.py -q` and
      `.venv/bin/python -m pytest tests/unit/test_identity_enrich_correctness.py -q` green;
      then `.venv/bin/python -m pytest tests/unit -m unit -q` green.

### Phase-05 — Flag, scheduler, revive subordination (T6, T7, T8, T12, T13, T14) — ⏳ PLANNED

- [ ] 5.1 Add the config block (AD-12) with a `# ─── … ───` header and multi-paragraph rationale.
- [ ] 5.2 Add the early-return flag guard at the top of `revive_returning_unresolvable`
      (`visitor_aggregator.py:365`). **One guard, nothing else in this file.**
- [ ] 5.3 Register the scheduler job inside `if settings.auto_reidentify_enabled:` with explicit
      `id`, positive literal `jitter`/`misfire_grace_time`, and a boot offset **< 90s**.
- [ ] 5.4 **EDIT** the arithmetic assertions in `tests/unit/test_scheduler_job_config.py`
      (live `:219-221`, drifted from the plan-time `:213-217`) and append a provenance paragraph to
      the running changelog docstring (live `:177-224`). **Do NOT hardcode "23/21 → 24/22"** — that
      target is already stale (C7): live is **24 add_job / 21 interval / 3 cron**, so this feature's
      one added interval job makes the target **25 / 22 / 3**. Procedure: **re-derive the counts from
      the live AST first** (run the test, read its actual assertion values), then add exactly +1
      add_job and +1 interval. Also re-confirm the boot-offset `< aggregation_sweep` (90s) constraint
      against the jobs added by commit `b2a7eef`. **Do not relax the gate.**
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
- [ ] 6.5 (D-C / G7, **narrowed by ND-3**) Extend the manual retry endpoint
      (`apps/api/routers/visitors.py`, live `:905-931`) to accept `vpn_filtered` **only when the
      visitor's CURRENT `visitor.ip_address` is non-empty and `is_privacy_relay_ip(...)` is False**,
      and render the Retry button on the `vpn_filtered` badge branch
      (`apps/web/src/app/dashboard/visitors/page.tsx:389-392`) under the same condition. The manual
      lane passes **no** `override_ip` (live `:960`), so a relay-stored IP would be killed again by
      the guard at `identity_resolver.py:644` — a button that provably does nothing. Do **not**
      predicate this on "some historical non-relay IP exists".
- [ ] 6.6 (D-D / G9 / T19) Add the deliberately inverse-labeled `auto_reidentify_opt_out` setting to
      `apps/web/src/components/site-settings-dialog.tsx` and both `Site` / `SiteUpdate` declarations
      in `apps/web/src/lib/api-types.ts`; default false means "Automatic identity retries" enabled,
      true means disabled. The control changes only this opt-out, not `tracking_enabled`,
      `auto_paused_at`, erasure, or manual Retry.
- [ ] 6.6b **(ND-4 — the toggle is inert without this)** Add `auto_reidentify_opt_out` to
      `SiteUpdate` (`bool | None = None`) and `SiteOut` (`bool`) in `apps/api/schemas/sites.py`, and
      add one `if body.auto_reidentify_opt_out is not None: site.auto_reidentify_opt_out = ...`
      branch to `update_site` (`apps/api/routers/sites.py`, live `:330-389`) — that handler copies
      fields **one by one**, so an unhandled field is silently dropped. **The new branch must NOT
      touch `site.auto_paused_at`**; only the `tracking_enabled` branch (`:347-353`, commit
      `b2a7eef`) clears it, deliberately, and that logic must be left exactly as-is.
- [ ] **Test gate 6:** `.venv/bin/python -m pytest tests/ -m integration -q`, `cd apps/web && npm run
      lint`, and `cd apps/web && npm run build` green; browser check covers the visitor counter and
      the opt-out state round trip.

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
| `tests/integration/test_reidentify_sweep.py::test_provider_unavailable_defers_through_ramp_and_repeats_cap` — force all providers unavailable through all four defer stages plus one additional outage; assert capped 24h repeat, zero attempt/count accounting, and no dispatch before each due watermark | Hybrid (needs PG) | AC-3/AC-7 (F2: outage backoff without terminal stranding or hot loop) |
| `tests/unit/test_reidentify_sweep.py::exception_does_not_consume_attempt` | Fully-Automated | AC-7 |
| `tests/unit/test_agent_company_resolution.py` `_AC2_FILES` tripwire (`:515-540`) **after appending `apps/api/services/reidentify_sweep_runner.py` to the hardcoded list at `:515-520`** | Fully-Automated | AC-8 (agent-origin exclusion) — **REPLACES the plan's original citation of `test_agent_origin_exclusion.py:236-247`, which asserts `source_agent_visit_id`, a different literal, and could never cover the new module (G3)** |
| `tests/integration/test_reidentify_sweep.py::agent_origin_never_selected` — seed an agent-derived visitor in the new status set; assert it is never selected | Hybrid (needs PG) | AC-8 (behavioural, not text-match) |
| `tests/integration/test_reidentify_sweep.py::do_not_resolve_never_retried` | Hybrid (needs PG) | AC-9 (do_not_resolve honored) |
| `tests/unit/test_reidentify_sweep.py::no_pii_in_logs` — log-capture assertion, no IP/email in structlog output | Fully-Automated | AC-10 (no PII in logs) |
| `tests/integration/test_reidentify_sweep.py::retries_do_not_exhaust_first_identify_budget` — run the new sweep up to the reserve threshold, then assert the main sweep still resolves ≥1 `anonymous` visitor | Hybrid (needs PG) | AC-11 (**REPLACES the vacuous `starvation_never_attempted_still_selected` row — the two sweeps are provably disjoint (`resolution_runner.py:135`), so intra-sweep ordering could never fail; the real contention is the shared 50/day budget, G4**) |
| `tests/unit/test_reidentify_sweep.py::budget_exhausted_site_consumes_nothing` — budget-exhausted site ⇒ **no** attempt consumed, **no** `tried_ips` entry appended, and (ND-3b) **no `skip_count` increment and no `next_at` advance** | Fully-Automated | AC-7 (G2b + ND-3b) |
| `tests/unit/test_reidentify_sweep.py::exception_advances_next_at` — a raising call advances `next_at` by a backoff without consuming an attempt | Fully-Automated | AC-7 (G10 — prevents an unbounded per-tick hot loop) |
| `tests/integration/test_reidentify_sweep.py::sweep_does_not_persist_chosen_ip` — re-read the row from a fresh session after `expire_all()`; `visitors.ip_address` unchanged on the **success**, **outage** and **exception** paths | Hybrid (needs PG) | AC-7/AC-13 (G1 — the plan's central override must not be a committed write) |
| `tests/integration/test_reidentify_sweep.py::opt_out_site_never_selected` — a site with `auto_reidentify_opt_out = true` is never swept; default-false sites still are | Hybrid (needs PG) | D-D / G9 (consent escape hatch; coverage default preserved) |
| `tests/integration/test_reidentify_resolution_leases.py::test_four_human_lane_lease_race_identified_once` — manual Retry, APScheduler, registered Celery, and new reidentify sweep barrier-race the same **human** visitor; exactly one lease winner and top-level provider-capable dispatch, one `IdentifiedVisitor`, and only the winner's lane-specific success effects | Hybrid (needs PG) | AC-4/AC-7 (S7: atomic human-domain lease safety) |
| `tests/integration/test_reidentify_resolution_leases.py::test_four_human_lane_lease_race_no_match_one_distinct_daily_meter_visitor` — same four-human-lane race under one enabled provider; assert one winning top-level dispatch and `get_resolution_attempts_today(...) == 1`, not a false global raw-`ResolutionLog` row-count promise | Hybrid (needs PG) | AC-4/AC-7 (S7: no duplicate distinct-visitor daily-meter accounting) |
| `tests/unit/test_agent_company_resolution.py::test_agent_company_held_claim_is_side_effect_free_and_releases_exact_token` — a held claim for a synthetic visitor proves only an agent-company concurrent execution can contend; the busy path calls neither resolver nor `_upsert_company`, creates no AgentVisit link, and releases no non-owner token | Hybrid | AC-8/AC-7 (S7: agent-derived domain isolation and exact release) |
| `tests/unit/test_agent_company_resolution.py::test_agent_company_plan_limit_skips_provider_claim_and_downstream` — after synthetic materialization and defer eligibility, a false canonical `check_usage_allowed` result skips before claim/provider work; assert no resolver, provider, upsert/link, or usage increment and capture only safe ids/counters | Fully-Automated | AC-8a (S8: agent automatic path observes the existing monthly plan limit) |
| `tests/unit/test_agent_company_resolution.py::test_agent_company_success_increments_usage_once_before_downstream` — a claimed non-`None` resolver result calls canonical `increment_usage` exactly once before company upsert/link | Fully-Automated | AC-8a (S8: standard success-only metering) |
| `tests/unit/test_agent_company_resolution.py::test_agent_company_resolver_exception_does_not_meter_and_releases_exact_token` — a pre-success `resolver.resolve` exception calls `increment_usage` zero times and releases exactly its owned token | Fully-Automated | AC-8a / AC-7 (S8: no meter before a resolver result; exact-token cleanup) |
| `tests/unit/test_agent_company_resolution.py::test_agent_company_downstream_exception_meters_once_releases_exact_token_and_retry_does_not_duplicate` — after a non-`None` resolver result, an `_upsert_company`/link exception retains exactly one prior increment, releases exactly its owned token, and a retry performs no duplicate increment | Fully-Automated | AC-8a / AC-7 (S8: canonical success meter survives downstream failure without double billing) |
| `tests/integration/test_agent_company_resolution.py::test_agent_company_same_synthetic_claim_race_meters_once` — two concurrent agent-company runs for one AgentVisit/synthetic key have one provider-capable owner, one usage increment, and no loser downstream side effects | Hybrid | AC-8a (S8: reentrancy/lease race cannot double-meter) |
| `tests/integration/test_reidentify_sweep.py::test_historical_selected_ip_rejects_current_graph_record_outside_event_window` + `::test_historical_selected_ip_allows_graph_record_inside_event_window` — PG-seeded historical X/current Y proves graph matching uses X's event time, permits only in-window records, and never writes `Visitor.last_seen` | Hybrid (needs PG) | AC-1/AC-3/AC-7 (S7: historical override provenance) |
| `tests/integration/test_visitor_resolve_endpoint.py::test_live_claim_returns_retry_in_progress_without_state_write` — manual endpoint returns 409 against a held claim and does no state write | Hybrid (needs PG) | AC-4/AC-7 (manual API conflict contract) |
| `tests/integration/test_visitor_resolve_endpoint.py::test_manual_retry_runs_during_active_defer_and_reports_provider_outage` — manual lane still dispatches during a future defer deadline, then returns HTTP 200 `anonymous/provider_outage` with no meter/log stamp and retained defer state | Hybrid (needs PG) | AC-3/AC-7 (manual retry product policy; scheduler/sweeps alone honor the defer filter) |
| `tests/integration/test_reidentify_resolution_leases.py::test_claim_model_registered_by_create_all_and_cascades` — existing `test_engine` imports `apps.api.main`, runs `Base.metadata.create_all()`, inserts a claim, deletes its parent visitor, and a fresh session observes no claim row | Hybrid (needs PG) | AC-13 (mapped-table availability plus cascade erasure) |
| `tests/integration/test_promotion_sweep.py::test_promotion_sweep_is_deterministic_only_and_never_claims_lease` — spies fail if a paid provider or claim helper is reached; deterministic click promotion remains successful | Hybrid (needs PG) | AC-6/AC-7 (promotion condition gate; it cannot enter the provider-capable race) |
| `tests/unit/test_resolution_deferral_watermark.py::TestProviderCapableResolverCallerCensus::test_provider_capable_resolver_census_is_exhaustive` — source scanner/manifest classifies every live `IdentityResolver.resolve` and private-provider wrapper source as four-human shared claim, agent-domain claimant, deterministic-only, or out-of-scope with its checked reason | Fully-Automated | AC-4/AC-7 (S7 census completeness; a new paid-provider path cannot silently evade its correct claim boundary) |
| `tests/integration/test_reidentify_sweep.py::paused_site_never_swept` — a site with `tracking_enabled = false` (manual toggle AND inactivity auto-pause) is never selected and consumes zero budget | Hybrid (needs PG) | AC-10b (**F6** — matches `resolution_runner.py:252-261`, commit `b2a7eef`; a paused site must not burn provider credits) |
| `tests/integration/test_reidentify_sweep.py::reserve_blocks_second_batch_at_70pct` — threshold `ceil(0.70 * budget)` = **35** on the default budget of 50; seed `attempts_today = 34` (explicit integer); assert the NEXT `resolve()` is **allowed** (34 < 35) and the one after is **refused** (35 >= 35), with a first-time identify still succeeding | Hybrid (needs PG) | AC-10 (**C13 + ND-3a** — proves the per-visitor reserve, which the once-per-tick version leaked to ~80%. **Re-laned unit → integration (L4): it asserts a selection-query outcome; the unit lane has no Postgres and the WHERE clause involves a `Site` join + JSONB**) |
| `tests/integration/test_reidentify_sweep.py::budget_refusal_stamps_nothing` — a reserve-refused visitor ends the tick with `skip_count`, `next_at`, `tried_ips` and `count` ALL unchanged, and is selected again on the very next tick | Hybrid (needs PG) | AC-10 (**ND-3b** — a budget refusal must not feed the `skip_count < 8` retirement ledger; otherwise a chronically-busy site retires its whole candidate set in 8 weeks with zero IPs evaluated) |
| Manual retry button renders on a `vpn_filtered` visitor **only when the CURRENT `visitor.ip_address` is non-relay**; a relay-stored visitor shows no button | Hybrid (needs PG) | AC-13 (**ND-3** — the manual lane passes no `override_ip` (`routers/visitors.py:960`), so the guard at `identity_resolver.py:644` would make a wider button dead) |
| `PATCH /sites/{id}` with `auto_reidentify_opt_out: true` round-trips through `SiteUpdate` → `update_site` → `SiteOut`, and `auto_paused_at` is unchanged by that write | Hybrid (needs PG) | AC-13b (**ND-4** — `update_site` copies fields one-by-one; an unhandled field is silently dropped, and the `tracking_enabled` branch's `auto_paused_at` clearing must not be disturbed) |
| `tests/unit/test_reidentify_ranker.py::asn_none_short_circuits_to_unknown` — `lookup_asn` returning `(None, None)` yields tier `unknown` and `classify_ip_org_kind` is **never called** | Fully-Automated | AC-1 (G8 — without this, `classify_ip_org_kind(None, None)` returns `"org"` and the ladder collapses) |
| `tests/unit/test_reidentify_sweep.py::vpn_flip_still_counts_attempt` — an `unresolvable` → `vpn_filtered` flip via the IPinfo check still counts the attempt and appends `tried_ips` | Fully-Automated | G11 (unlisted status transition, now in Public Contracts) |
| Manual retry on a `vpn_filtered` visitor with a non-relay untried IP succeeds; with only relay IPs it does not | Hybrid (needs PG) | D-C / G7 (`routers/visitors.py:911-931`) |
| `tests/unit/test_resolution_deferral_watermark.py:151-198` **strengthened** to discover the new sweep's status literals, then assert `resolution_not_deferred_filter()` present | Fully-Automated | AC-11 |
| `tests/integration/test_unresolvable_revive.py:97-120` flag-parametrised — flag OFF assertions byte-unchanged; flag ON ⇒ revive inert | Hybrid (needs PG) | AC-12 (flag-off byte-identical) + D5 single-owner |
| Full unit + integration lanes with the flag unset | Fully-Automated | AC-12 |
| `tests/unit/test_scheduler_job_config.py:176-223` updated from current 24 add-job / 21 interval / 3 cron assertions to 25 / 22 / 3, with provenance paragraph | Fully-Automated | AC-12 (scheduler registration correctness) |
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
- No harness asserts that a *site-level* gate is honored by a sweep. `::paused_site_never_swept`
  (F6) and `::opt_out_site_never_selected` (D-D) will each be constructed ad hoc; a shared
  "site-gate matrix" fixture would cover both plus the two gates `resolution_runner.py` already has.
- `apps/api/routers/sites.py::update_site` copies fields **one by one**, so a `SiteUpdate` field with
  no handler line is silently dropped and no test catches it (this is exactly ND-4). A
  schema-field-vs-handler parity test over `SiteUpdate` would end the class.
- `_AC2_FILES` in `tests/unit/test_agent_company_resolution.py:515-520` is a **hardcoded list** — it
  cannot discover a new module, and nothing warns when a new sweep is added. A registry/AST-based
  discovery would end this class of silent miss (it caused G3).
- `Base.metadata.create_all()` depends on `apps/api/main.py`'s explicit import list; a new mapped
  table referenced only by a lazily imported service is silently absent from the Hybrid fixture. The
  S5 registration/cascade gate is mandatory until the repo replaces this import-list convention with
  automatic model discovery.
- The provider fan-out can write multiple `ResolutionLog` rows for one top-level no-match. Cross-lane
  tests therefore prove one top-level resolver winner and one **distinct-meter visitor**, and enable
  only one provider when a controlled raw-row assertion is useful; they must never turn a fixture
  artifact into a false global "one ResolutionLog" invariant.
- Existing matching tests are unit-only and exercise `Visitor.last_seen`; S7 adds an injected
  selected-IP activity argument plus a PostgreSQL fixture that materializes events. The fixture must
  seed historical X and current Y on the same visitor so the false global-recency match is actually
  reachable; a direct matcher-only test cannot prove ranker/sweep provenance or non-mutation.
- Agent-company's existing mocked unit surface is adequate for a held-claim busy-path/no-side-effect
  assertion. It is not adequate for retained defer state across commits, so the capped all-provider
  outage/re-entry scenario belongs in new `tests/integration/test_agent_company_resolution.py`.

---

## Open Risks (call these out for VALIDATE)

| # | Risk | Why it is thin |
|---|---|---|
| **R1** | ~~Outage detection via before/after `resolution_defer_count`~~ | **RESOLVED by S3-1.** The resolver returns its existing provider-unavailable taxonomy as an explicit result. The sweep does not inspect, reset, or infer from defer columns; resolver-owned eligibility blocks provider work until the retained watermark is due. |
| **R2** | `auto_reidentify_tried_ips` JSONB has **no index** | **PASS, with a standing guard.** It appears in no predicate and no ORDER BY; it is read per-row on ≤20 already-materialised rows. Guard (execute instruction E4): **never** put `jsonb_array_length(auto_reidentify_tried_ips)` in an ORDER BY — that would make it a computed sort over the whole filtered set before LIMIT. |
| **R3** | ~~The starvation `ORDER BY`~~ | **RESOLVED AS A NON-PROBLEM (G4).** The two sweeps are provably disjoint (`resolution_runner.py:135` vs AD-6), so intra-sweep ordering cannot protect first-time identifies and the old gate was vacuously green. Replaced by the **D-B per-site budget reserve** (70%, explicitly a placeholder) plus `::retries_do_not_exhaust_first_identify_budget`. |
| **R4** | The 70% reserve threshold is unmeasured | It is an explicitly-labelled **PLACEHOLDER**, tuned before any prod flag flip, same posture as `job_change_recheck_daily_cap`. Too high starves retries; too low starves first-time identifies. |
| **R5** | The `skip_count < 8` retirement bound is likewise unmeasured | ~56 days of futile 7-day evaluation before retirement. A retired single-IP visitor is never re-evaluated even if a new IP arrives later — accepted, disclosed. **Scope narrowed in cycle 3 (ND-3b): `skip_count` counts ONLY futile-IP evaluations.** Budget refusals stamp nothing, so a chronically-busy site can no longer retire its whole candidate set without evaluating a single IP — the self-annihilation path this bound previously opened. |
| **R6** | `is_privacy_relay_ip` (`company_resolver.py:230-243`) checks only `("2a09:bac3:",)` | **iCloud IPv6 only — no v4 coverage.** The AD-4 exclusion is therefore weaker than its name suggests, which is exactly why the `unresolvable` → `vpn_filtered` flip (G11) is reachable and now disclosed in Public Contracts. |

| **R7** | Pre-existing population deferred while `anonymous` and later flipped to a terminal status | Not created by this plan. The common `resolution_not_deferred_filter()` makes it eligible when its existing watermark is due; this plan does no backfill and never alters resolver defer fields. |
| **R9** | **Cold-start backlog throughput (C9, disclosed in cycle 3).** At flag-flip every eligible visitor has `auto_reidentify_next_at IS NULL`, so the entire historical backlog is "due now" at once | Bounded, not eliminated. The 4.3 batch split caps the NULL pool at **10 rows per site per tick**, so due rows lose at most 50% of throughput while the backlog drains, and the backlog itself drains in roughly `backlog_size / (10 × ticks_per_day)` days per site. Example: a 5,000-row backlog at 24 ticks/day drains in ~21 days; at 4 ticks/day, ~125 days. **The eligible-backlog COUNT is a named rollout-gate measurement** (see §Measurement Gap) so the operator sees the number BEFORE the flag flip rather than discovering the drain time in prod. |
| **R8** | Manual Retry for `vpn_filtered` only helps visitors whose CURRENT IP is non-relay (ND-3) | Accepted. Widening it needs `override_ip` on the manual lane (a 7th consumption site + endpoint change) — backlogged as `manual-retry-override-ip_NOTE_11-08-26.md`. The automatic sweep, which does have `override_ip`, covers the historical-IP case. |

Additional reviewable calls (lower severity, still worth a VALIDATE look):
- Plaintext IPs in `auto_reidentify_tried_ips` on the visitor row (AD-1 rationale: same row already
  holds a plaintext `ip_address`; inherits erasure for free).
- `is_privacy_relay_ip` covers only `2a09:bac3:` (iCloud v6) — **no v4 coverage**. The exclusion is
  therefore weaker than its name suggests.
- Every-site coverage means auto-identify-OFF sites start spending their daily budget. A per-site
  opt-out column is a named follow-up.

---

## Execute-Agent Instructions (E-series)

| # | Instruction |
|---|---|
| E1 | Re-derive **every** `path:line` anchor before editing. PVL cycle 2 measured a uniform **+42-line drift** in `identity_resolver.py` (`:502→:544`, `:583→:625`, `:589→:631`, `:593→:635`, `:602→:644`, `:611→:655`, `:652→:694`, `:691→:733`, `:695→:737`, `:721-723→:763-765`, `:750→:792`, `:931→:973`), `visitor_aggregator.py:365→:375`, `_AC2_FILES :515→:512`. **All content anchors verified stable** — this is line drift, not semantic drift, but never trust a recorded line number. |
| E2 | Re-derive the alembic head **live** with `DATABASE_URL` pinned to `localhost:5433`. Cycle-2 live head was `f4b9d2a71c68`; prod is `c4a8f13e07b6`. Do not hardcode either. |
| E3 | Re-derive the scheduler arithmetic from the live AST before editing `test_scheduler_job_config.py` (C7). |
| E4 | **Never** put `jsonb_array_length(auto_reidentify_tried_ips)` in any `ORDER BY` — it would turn R2's harmless unindexed per-row JSONB read into a computed sort over the whole filtered candidate set before `LIMIT`. |
| E5 | **(C12)** Every log line on the retry path must print the **effective** IP (`override_ip or visitor.ip_address`) or omit the IP entirely — never bare `visitor.ip_address`, which would attribute the outcome to the WRONG IP and mislead the first person debugging this feature. Sites (~13, re-derive live): `identity_resolver.py:648` (`ip_prefix`), `:700`, `:703`; `identity_providers/pdl.py:97,104,106,109`; `rb2b.py:189,213,226,247,269,281`; `capturify.py:98`. Prefix-truncation and the no-PII rule (SPEC AC-10) still apply — this instruction changes *which* IP is referenced, never whether a full IP may be logged. |
| E6 | **(S7)** No caller lane writes `resolution_defer_count` or `resolution_deferred_until`. One shared lease serializes same-key provider work across manual Retry, APScheduler `resolution_runner`, registered Celery `resolution_tasks`, and the new human retry sweep. Agent-company uses the identical helper only for its synthetic key after materialization and automatic defer eligibility, never as a fifth human-race competitor. Promotion is `deterministic_only=True`, so it is not provider-capable. Manual Retry ignores a future defer; automatic scheduler/sweep lanes honor it. Provider-unavailable retains the resolver watermark, and all-provider outage after stage 4 repeats capped 24h rather than clearing it. |
| E7 | **(S7 temporal provenance)** The ranker must carry `MAX(Event.created_at)` for the selected IP to `resolve_auto_retry`, then only Leadpipe/Capturify matching. Do not use global `Visitor.last_seen` when selected-IP activity exists, and never assign either `Visitor.last_seen` or `Visitor.ip_address` as a workaround. |

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
3b. **Measure the eligible-backlog COUNT per site (C9 / R9, added cycle 3)** — a read-only
   `COUNT(*)` over AD-6's WHERE clause per site, i.e. how many rows will enter the NULL pool at
   flag-flip. Report it alongside the drain estimate
   `backlog_size / (10 × ticks_per_day)` days. **The operator must see this number before the flip**;
   a backlog large enough to make the drain unacceptable is a reason to raise tick frequency or stage
   the rollout per site, not a reason to discover it live.
4. Flag ON in prod.

---

## Sequencing / Collision

| Plan | State | Constraint on this change |
|---|---|---|
| `graph-erasure-compliance_07-08-26` | unexecuted, contract-bound edits to `identity_resolver.py` | do not widen the resolver footprint beyond **3 defaulted parameters (`auto_retry`, `override_ip`, `selected_ip_activity_at`) + five defaulted override mixin params + two matching-only activity params** — see S7 |
| `cross-tenant-erasure-phase2_07-08-26` | unexecuted; its own plan warns the resolver "has been rewritten three times in the last week" | re-derive every resolver anchor at EXECUTE |
| `ip-org-quality-pack_08-08-26` | code-committed on `devjulley` (`ad34632` + `9f97c54`), plan still active; deliberately kept BOTH `identity_resolver.py` and `visitor_aggregator.py` **READ-ONLY** | keep this change's resolver footprint to the S7 default-compatible selected-IP contract and the ONE flag guard in the aggregator; land in a tight commit |

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
7. An explicit `provider_unavailable` outcome, a pre-check miss (budget / `do_not_resolve` /
   suppression), or an exception consumes **no** attempt and appends **no** `tried_ips` entry. On
   provider unavailable, the resolver retains its defer watermark and the sweep re-enters only when
   that watermark is due; it never restores or clears it. An exception additionally advances
   `next_at` by a backoff. **`visitors.ip_address` is never written by this feature on any path.**
8. Agent-origin and `do_not_resolve` visitors are never selected.
8a. An agent-company row passes the canonical monthly plan check after synthetic/defer eligibility and
    before claim/provider work. A blocked, missing-site, or missing-owner row performs no resolver,
    provider, claim, company upsert, AgentVisit link, or usage-increment side effect; it emits only
    non-PII counters/log fields. A claimed non-`None` resolver result increments the existing monthly
    usage counter exactly once before downstream company/link work. A **pre-success resolver
    exception** increments zero and releases its exact token; a **post-success downstream upsert/link
    exception** keeps that one increment, releases its exact token, and retry creates no duplicate
    increment. Busy/reentrant contenders increment zero times.
9. No IP and no email appears in structlog output from the new paths.
10. **(Rewritten G4; tightened C13; bounded honestly in cycle 3)** Auto-retries **stop STARTING**
    once a site reaches **70% of its daily identify budget** — refuse when
    `attempts_today >= ceil(0.70 * budget)` (budget 50 ⇒ threshold 35, ND-3a). The reserve is
    re-evaluated **before every individual `resolve()`**, not once per tick, so the ceiling holds
    within a batch as well as across batches. **Disclosed accepted bound:** concurrent main-sweep
    interleaving on the same unlocked meter can land the day total a few resolves past 70%
    (~82% worst case) — the guarantee is on when retries *start*, not on the final day total.
    **A budget refusal stamps nothing** (no `skip_count`, no `next_at`) — ND-3b. The main sweep still
    resolves at least one `anonymous` visitor after retries have run first.
10b. **(F6)** A site with `tracking_enabled = false` — manually paused **or** inactivity
    auto-paused — is never selected by the new sweep and consumes no identify budget.
11. The existing budget invariants stay green (distinct-visitor meter; deterministic-only never
    consults the budget).
12. `identity_status` gains **no new value**; the two front-end/analytics readers listed in AD-10
    are provably unaffected.
13. "tried N/4" renders on the visitor list row and the detail page; Manual Retry works on an
    exhausted visitor and neither consumes nor resets the counter; **Manual Retry is also offered
    for `vpn_filtered` visitors whose CURRENT `visitor.ip_address` is non-relay (D-C, narrowed by
    ND-3) — and is NOT offered when the stored IP is a relay, because the manual lane passes no
    `override_ip` and would be killed by the guard at `identity_resolver.py:644`**.
13b. A site with `auto_reidentify_opt_out = true` is never swept; the column defaults to **false**,
    so every-site coverage is unchanged for everyone who does nothing (D-D). The toggle is
    reachable end-to-end: `SiteUpdate` → `update_site` → `SiteOut` (ND-4), and setting it leaves
    `site.auto_paused_at` untouched.
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
3. **Validate-contract status:** **WRITTEN — `Gate: BLOCKED` (cycle 6, 11-08-26; S8 applied).** PVL supplement
   cycle 1 (10-08-26) closed G1–G14 (D-A `override_ip`, D-B budget reserve, D-C `vpn_filtered`
   manual retry, D-D per-site opt-out) — cycle 2 verified all four FAILs genuinely closed. **PVL
   supplement cycle 2 applied 11-08-26**, closing the two new FAILs (F5 outage-defer permanent
   stranding → outage-path restore, AD-8 + 4.5b + E6; F6 missing `Site.tracking_enabled` gate →
   AD-6 + 4.3b), the two verifier-only defects (ND-3 narrowed `vpn_filtered` retry predicate +
   backlog stub; ND-4 `schemas/sites.py` + `routers/sites.py` touchpoints), and C7–C13. **The
   `Gate: BLOCKED` verdict below is UNCHANGED by these supplements — **S7 corrects S6 to four human
   same-key lanes plus an isolated agent-domain claimant; it adds agent defer-before-claim, selected-IP
   event-time provenance through Leadpipe/Capturify matching, and the required race/reentrancy/PG
   adversarial census gates. S8 then adds the agent automatic monthly-plan check before claim/provider
   work, immediate non-`None` success-only canonical usage increment before company/link work, split
   resolver-exception zero-meter/exact-release and downstream-exception one-meter/exact-release/no-
   duplicate-retry gates, same-synthetic-key one-meter proof, and its expanded source census.** `vc-validate-agent`
   must re-run from V1 and re-adjudicate. EXECUTE is not
   authorised until the gate clears.
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
   - Read §Execute-Agent Instructions (E1–E6) BEFORE touching any file — E6 in particular pairs two
     checklist items that are unsafe alone.
   - Start at the first unchecked box in Phase-01 and run that phase's test gate before advancing.
   - Detect Docker by port (`lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`), not by
     `which docker`.

---

## Validate Contract

Status: BLOCKED
Date: 13-08-26
date: 2026-08-13
generated-by: outer-pvl
supersedes: 2026-08-11 (outer-pvl) — PVL cycle 6; cycle 7 is a fresh V1 pass re-adjudicating S7 + S8 against live source on `main`

**Fan-out method: SEQUENTIAL, single agent.** The Agent tool is not available in this environment,
so the designed Layer 1 / Layer 2 parallel fan-out could not run. All four Layer 1 dimensions and
all nine Layer 2 sections were investigated sequentially by one agent, with live source reads and
one empirical container probe. Recorded as a coverage limitation, not a choice.

Parallel strategy: sequential (forced — no Agent tool)
Rationale: 7/7 signals present. Score says agent-team; environment permits only sequential.

### Cycle-7 fresh V1 — what was re-derived (not inherited)

Branch `main`. Structural validator: **0 failures / 0 warnings / 2527 lines**.
Unit lane baseline re-measured: **1762 passed / 2 skipped / 0 failed** (26.7s).
Scoped Hybrid lane re-measured: **11 passed / 0 failed** across
`test_visitor_resolve_endpoint.py` + `test_promotion_sweep.py` + `test_unresolvable_revive.py` (48s).
Docker CLI resolved at `/Applications/Docker.app/Contents/Resources/bin/docker`; PG 5433 + Redis 6379
listening. **No gate in this plan is environment-blocked.**

| S7/S8 claim under adjudication | Verdict | Live evidence |
|---|---|---|
| `agent_company_resolution` uses synthetic `agent:{AgentVisit.id}` + `is_agent_derived`, structurally cannot same-key contend with human lanes | **CONFIRMED** | `agent_company_resolution.py:69` (`visitor_id = f"agent:{agent_visit.id}"`), `:76-81` (`is_agent_derived=True`); human lanes select via `human_only_visitor_filter()` at `resolution_runner.py:145`, `resolution_tasks.py:95`, `routers/visitors.py` manual endpoint |
| Agent-company has neither `check_usage_allowed` nor `increment_usage` (the S8 gap) | **CONFIRMED** | S8-3 census cmd 1 run live: hits are `billing.py:94/140` (defs), `resolution_runner.py:161/178`, `resolution_tasks.py:120/135`, `routers/visitors.py:953/963`, `routers/billing.py:317`, `visitors_helpers.py:280`. `agent_company_resolution.py`: **zero hits** |
| S8 donor anchors exact | **CONFIRMED** | `resolution_runner.py:161` check → `:172` resolve → `:178` increment; `resolution_tasks.py:120` check → `:130` resolve → `:135` increment; `agent_company_resolution.py:130` resolve → `:141` `_upsert_company` → `:150` link |
| Cross-AgentVisit atomic reservation is an inherited billing boundary, NOT claimed | **CONFIRMED, correctly disclaimed** | `billing.py:94/140` is check-then-increment, not a reservation. S8-2 states the limitation explicitly instead of passing by omission |
| `auto_retry` bypasses EXACTLY ONE line | **CONFIRMED** | `identity_resolver.py:625` `if not force_retry and await self.was_recently_attempted(`. All other gates are separate downstream statements: `do_not_resolve` `:590`, suppression `:600`, daily budget `:631`, no-IP `:635`, privacy relay `:644`, IPinfo VPN `:653-666` |
| `Site.tracking_enabled` gate exists (b2a7eef auto-pause) | **CONFIRMED** | `resolution_runner.py:260` `Site.tracking_enabled.is_(True)` |
| `resolution_deferred_until` filter is exclusive to automated selection | **CONFIRMED** | `resolution_not_deferred_filter()` (`resolution_eligibility.py:84`) used only at `resolution_runner.py:142` and `resolution_tasks.py:91`. `IdentityResolver.resolve` never READS it (writes only at `:766`/`:791`); `routers/visitors.py` never filters on it |
| Manual retry can return HTTP 200 `anonymous/provider_outage` today | **CONFIRMED** | `visitors_helpers.py:270-273` returns `provider_outage` when `resolution_deferred_until > now`; imported by `visitors.py:20-32`. No new endpoint API needed |
| Selected-IP provenance surfaces exist | **CONFIRMED** | `matching.py:126` `_visitor_activity_utc`, `:138` `_record_matches_visitor`, `:175` comparison; called only from `leadpipe.py:179` and `capturify.py:85` |
| Promotion is not provider-capable today | **CONFIRMED (change needed)** | `promotion_sweep_runner.py:117` calls `resolver.resolve(visitor)` with NO `deterministic_only=True`; the defensive `unexpected_paid` counter exists at `:107`/`:137`. T28 is a real, correct edit |
| `main.py` create-all import convention exists for T29 | **CONFIRMED** | `main.py:16-51` explicit `# noqa: F401 — register for create_all` block; `Base.metadata.create_all` at `:98` |
| Composite FK `(site_id, visitor_id) → visitors` ON DELETE CASCADE is viable against a plain UNIQUE **INDEX** | **CONFIRMED — EMPIRICAL PROBE** | `visitors.__table_args__` has `Index("uq_visitors_site_visitor", ..., unique=True)`, **not** a `UniqueConstraint`. Probed on a disposable `postgres:16-alpine`: FK creation succeeded; deleting the parent visitor cascaded the claim row (1 → 0); `UNIQUE(site_id, visitor_id)` on the claim table rejected a duplicate. **This closes the highest structural risk in S5-2.** Container removed |
| Provider-capable resolver caller census (S7-4/T33) is exhaustive | **CONFIRMED** | Every live `IdentityResolver` use maps to a manifest class: `routers/visitors.py:960` (human), `resolution_runner.py:172` (human), `resolution_tasks.py:130` (human), new sweep (human), `agent_company_resolution.py:130` (agent-domain), `promotion_sweep_runner.py:117` (deterministic-only), `demo.py:131` (demo private wrapper), `leadpipe_webhook.py:288` (`_save_identified` persistence). **No unclassified caller exists** |
| `test_scheduler_job_config.py` arithmetic target 24/21/3 → 25/22/3 | **CONFIRMED** | `:219-221` asserts `len(calls) == 24` / `len(interval) == 21`; live `scheduler.py` has 24 `add_job`. (The module docstring's "12 add_job / 11 interval" at `:7` is stale historical provenance, not the live assertion) |
| `_AC2_FILES` tripwire is real and cannot discover a new module | **CONFIRMED** | `tests/unit/test_agent_company_resolution.py:512-520`, 7 entries, asserted by `::test_ac2_filter_referenced_at_every_site` `:532-538` |

**Cycle-6's single remaining S8 gap is CLOSED.** Every S8-1 anchor, the mandatory 8-step order, the
split exception-accounting semantics, and the deliberate non-claim of cross-AgentVisit reservation
survive live adjudication.

### NEW FAIL (cycle 7) — F-S4X: PVL Supplement 4's resolver change was never integrated into the plan body

S4-2 (plan `:2096-2120`) requires changing `identity_resolver.py`'s all-provider-unavailable branch
so it **"never falls through to the terminal reset"**. Live source `identity_resolver.py:762-795`
today does exactly the opposite: once `RESOLUTION_DEFER_BACKOFF` (4 stages) is exhausted it falls
through to `resolution_deferred_until = None`, `resolution_defer_count = 0`,
`identity_status = "unresolvable"`, commit.

S4-4 item 1 (`:2145-2148`) assigns that change to Phase-03 and requires replacing the existing
assertion `tests/unit/test_resolution_deferral_watermark.py::test_past_the_last_step_writes_off_and_resets`
(**verified live at `:340`**). That instruction exists **only in supplement prose**. It never reached
the plan body. Five surfaces are inconsistent:

1. **Phase-03 checklist (`:910-930`)** — steps 3.1–3.4 cover `auto_retry`, `override_ip`,
   `selected_ip_activity_at`, and the five mixins. **No step implements S4-2.** An execute-agent
   working the checklist ships none of it, while the Hybrid gate
   `::test_provider_unavailable_defers_through_ramp_and_repeats_cap` (`:1237`, `:1795`) asserts the
   capped repeat — a guaranteed EXECUTE failure.
2. **T13 (`:125`)** — says only "**strengthen** sweep discovery (`:151-198`)". It does not carry the
   `test_past_the_last_step_writes_off_and_resets` replacement.
3. **Public Contracts (`:165-188`)** — the `resolve()` row discloses signature and return type only.
   The outage **state-machine** change is undisclosed. It is a behavioral break for the four
   remaining live callers.
4. **AC-1 (`:1405-1406`)** — "With the flag **OFF**, every existing unit and integration test passes
   unchanged and no new behavior is observable anywhere." **Unsatisfiable.** Nothing in the plan
   gates S4-2 on `auto_reidentify_enabled` (searching the plan for `capped` / `24h` /
   `RESOLUTION_DEFER_BACKOFF` finds no flag condition anywhere), and S4-4 explicitly orders an
   existing assertion to be rewritten. Flag-OFF observable consequences:
   `revive_returning_unresolvable` (`visitor_aggregator.py:366`, `:423`) never receives these
   visitors; the manual Retry `is_retry` branch (`routers/visitors.py:912`) never fires for them, so
   Retry silently degrades to `force_retry=False` and re-hits the `:625` gate; the detail/coverage
   copy at `:730`/`:1008` changes; and an unbounded permanently-deferred population becomes a new
   steady state.
5. **Rollback (`:1466`)** — "Flip `auto_reidentify_enabled` to **False** … **No code revert
   needed.**" **False** for this change: flag-OFF does not restore the terminal write-off.

Severity FAIL, not CONCERN: it is a guaranteed EXECUTE failure (1) plus an acceptance criterion the
plan can never satisfy (4). Root cause is single — one supplement's resolver decision was never
propagated — so one coherent supplement (S9) closes all five surfaces.

### Cycle-7 Net Gate Derivation

| Layer 1 dimension | Cycle 6 | Cycle 7 |
|---|---|---|
| Infra fit | CONCERN | **PASS** |
| Test coverage | CONCERN | **CONCERN** |
| Breaking changes | CONCERN | **FAIL** |
| Security surface | PASS | **PASS** |

| Layer 2 section | Cycle 7 |
|---|---|
| §Touchpoints (T1–T38) | CONCERN |
| §Public Contracts | **FAIL** |
| §Architecture Decisions (AD-1…AD-15) | PASS |
| Phase-01 — Schema (T1, T2, T23) | PASS |
| Phase-02 — Pure ranker (T3) | PASS |
| Phase-03 — Resolver parameters (T5, T5b, T34) | **FAIL** |
| Phase-04 — Sweep runner + lease (T4, T23–T33) | PASS |
| Phase-05/06/07 — flag, UI, regression | PASS |
| §Acceptance Criteria + §Rollback | **FAIL** |
| §S7 supplement | PASS |
| §S8 supplement | PASS |

**Totals: 4 FAILs / 2 CONCERNs / 9 PASSes**

**→ Net Gate: BLOCKED** (all 4 FAILs share one root cause, F-S4X)

Net-gate vacuous-green check: every developed behavior retains a Fully-Automated, Hybrid, or
Agent-Probe gate; the single Known-Gap (distinct-IPs measurement) is a *rollout* gate carrying a
required backlog stub. **F-S4X has no gate** — the flag-OFF byte-identical claim is unprovable while
AC-1 and S4-2 contradict each other. That absence is part of why the gate is BLOCKED, not a
tolerated known-gap.

### Test gates (cycle-7 delta)

The full C3 5-column table is §III below and §Verification Evidence above (40+ rows, re-verified this
cycle). Cycle-7 adds one row and re-classifies none:

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 (flag-off) | after `RESOLUTION_DEFER_BACKOFF` exhaustion the resolver's terminal-vs-capped-repeat behavior matches the plan's declared, flag-scoped contract | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_resolution_deferral_watermark.py -q` (replaces `::test_past_the_last_step_writes_off_and_resets` per S4-4 item 1) | **B — blocked on S9; the plan currently declares two contradictory behaviors** |

Failing stub:
```
test("should keep identity_status unchanged and re-defer 24h after backoff exhaustion", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: after RESOLUTION_DEFER_BACKOFF exhaustion the resolver's terminal-vs-capped-repeat behavior matches the plan's declared, flag-scoped contract")
})
```

Legacy line form:
- resolver outage terminal branch: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_resolution_deferral_watermark.py -q`]
- claim table registration + cascade: [hybrid: `.venv/bin/python3.11 -m pytest tests/integration/test_reidentify_resolution_leases.py -q` + precondition: PG 5433 and Redis 6379 up]
- agent-company monthly parity + metering: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_agent_company_resolution.py -q`]
- distinct-IPs-per-visitor distribution: [known-gap: documented as rollout gate, backlog stub required]

### Dimension findings

- Infra fit: PASS — every non-new path in T1–T38 exists; anchors drifted (~+42 in `identity_resolver.py`, ~+35 in the web files) but E1 already mandates live re-derivation and the drift is recorded, not silent. Docker/PG/Redis all live; no gate is environment-blocked.
- Test coverage: CONCERN — the evidence table is exhaustive and non-vacuous, and both lanes are green today, but `tests/integration/test_agent_company_resolution.py` is assigned two Hybrid gates while its "new file" status appears only in §Test Infra Improvement Notes.
- Breaking changes: FAIL — F-S4X. The resolver outage state-machine change is undisclosed in Public Contracts and unflagged, breaking four live callers with `auto_reidentify_enabled` OFF.
- Security surface: PASS — no new PII write (`visitors.ip_address` never written, gated by `::sweep_does_not_persist_chosen_ip`); composite FK cascade empirically proven so the claim table inherits GDPR erasure; E5 covers the ~13 wrong-IP log sites; S8-2 confines observability to non-PII counters and honestly disclaims cross-AgentVisit reservation.
- Phase-03 feasibility: FAIL — checklist steps 3.1–3.4 do not implement S4-2; highest-risk edit is the `identity_resolver.py:762-795` outage branch, which must be sequenced before any Hybrid outage gate is written.
- §Public Contracts feasibility: FAIL — mechanically fine, but the contract inventory is incomplete against the plan's own supplements.
- §Acceptance Criteria / §Rollback feasibility: FAIL — AC-1 and the Rollback "no code revert needed" row are both falsified by S4-2.
- §S7 / §S8 / §AD-15 feasibility: PASS — census exhaustive, claim domains correct, agent quota parity anchored exactly.

### Open gaps

- F-S4X-1: Phase-03 checklist has no step implementing S4-2's resolver outage change.
- F-S4X-2: T13 does not carry the `test_past_the_last_step_writes_off_and_resets` replacement.
- F-S4X-3: Public Contracts omits the resolver outage terminal-state change.
- F-S4X-4: AC-1 and §Rollback are falsified by the unflagged S4-2 change.
- C7-1: `tests/integration/test_agent_company_resolution.py` new-file status is not declared in T37 or the T15 four-new-files inventory.
- Known-gap (unchanged, accepted): distinct-IPs-per-visitor distribution on real data — rollout gate, backlog stub required (§Measurement Gap).

### What this coverage does NOT prove

- `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` (1762 passed) proves the current tree is green. It does NOT prove any of this plan's behavior — every ranker, sweep, lease, and agent-parity gate is still unwritten (gap-resolution B).
- The 11-test scoped Hybrid run proves the integration lane is executable and the three touched files are green today. It does NOT prove the full integration lane, the new sweep, the lease races, or the migration round-trip.
- The disposable-container FK probe proves PostgreSQL 16 accepts a composite FK against a plain unique index and cascades on parent delete. It does NOT prove the alembic migration authors it correctly, that the head is live-derived, or that `Base.metadata.create_all()` registers the model — those remain T2/T29/AC-14 gates.
- The live census proves no unclassified resolver caller exists **today**. It does NOT prove the T33 static guard is written such that a future caller fails it — that gate is still unwritten.
- Nothing here proves flag-OFF byte-identical behavior. That claim is currently unprovable by construction (F-S4X-4).
- No paid provider was called. Whether a given corporate IP actually resolves stays an explicitly-justified Agent-Probe residual (AC-14, live-provider double-opt-in policy).

Gate: BLOCKED (4 unresolved FAILs, one root cause — F-S4X)
Accepted by: NOT ACCEPTED — a BLOCKED gate cannot be self-accepted by the validate-agent. Returns to PLAN for supplement cycle S9.

---

### Historical record — cycle 2 (retained for audit; NOT execution instructions)

The cycle-2 findings below explain why supplements S3–S8 exist. Where retained cycle-2 text
conflicts with S3–S8, the supplements control. F5 identified that the then-proposed defer-count
predicate would strand an outage row; F6 identified the missing tracking gate.

---

### Live re-derivation (cycle 2 — every number below re-measured, not inherited)

| Fact | Cycle-1 value | Live value (11-08-26) | Impact |
|---|---|---|---|
| Alembic head (`DATABASE_URL` pinned `localhost:5433`) | `d3f9a1c25e84` (non-conclusive, plan refuses to hardcode) | **`f4b9d2a71c68`** | none — AD-13 correctly mandates live derivation |
| Unit lane baseline | (not cited) | **1750 passed / 2 skipped** (32.99s) | none — plan cites "green", not a count |
| `identity_resolver.py` anchors | plan-time | **all +42 lines**; content anchors stable | C11 |
| `visitor_aggregator.revive_returning_unresolvable` | `:365` | **`:375`** (+10) | C11 |
| `_AC2_FILES` | `:515-520` | **`:512-520`** (−3) | C11 |
| `tests/unit/test_scheduler_job_config.py` arithmetic | 23 add_job / 21 interval | **24 / 21 / 3 cron** (`:219-221`, 12/12 green) | **C7 — plan's "→24/22" is now wrong; correct target is 25 / 22 / 3** |
| `resolution_runner.py` site selection | `auto_identify_enabled` only | **`auto_identify_enabled` AND `tracking_enabled`** (`:260`, commit `b2aa7ef`) | **F6** |

---

### Net Gate Derivation

| Layer 1 dimension | Cycle 1 | Cycle 2 |
|---|---|---|
| Infra fit | CONCERN | **FAIL** |
| Test coverage | FAIL | CONCERN |
| Breaking changes | FAIL | **FAIL** |
| Security surface | FAIL | CONCERN |

| Layer 2 section | Cycle 1 | Cycle 2 |
|---|---|---|
| Phase-01 — Schema (T1, T2) | PASS | CONCERN |
| Phase-02 — Pure ranker (T3) | PASS | PASS |
| Phase-03 — Resolver parameters (T5, T5b) | CONCERN | CONCERN |
| Phase-04 — Sweep runner (T4) | FAIL | **FAIL** |
| Phase-05 — Flag / scheduler / revive | CONCERN | CONCERN |
| Phase-06 — UI counter (T9–T11, T17, T19, T20) | PASS | PASS |
| Phase-07 — Regression + rollout gate | CONCERN | CONCERN |

**Totals: 2 FAILs / 7 CONCERNs / 2 PASSes**

**→ Net Gate: BLOCKED**

Net-gate vacuous-green check: every developed behavior still has a Fully-Automated, Hybrid, or
Agent-Probe gate; the one Known-Gap (distinct-IPs measurement) is a *rollout* gate carrying a
required backlog stub. **F5 and F6 have NO gate at all** — that absence is part of why the gate
is BLOCKED, not a tolerated known-gap.

---

### Cycle-1 FAIL closure audit (did the supplement actually work?)

#### F1 — committed `visitor.ip_address` write → **CLOSED ✅**

The `override_ip` parameter (D-A) is the structurally correct fix and the plan's consumption list
is **exhaustive**, which cycle 1 could not confirm. Verified by mapping each cited anchor at the
live +42 offset:

| Plan anchor | Live line | What it is | Covered? |
|---|---|---|---|
| `:593` | `:635` | `if not getattr(visitor, "ip_address", None)` — no-IP guard | ✅ |
| `:602` | `:644` | `is_privacy_relay_ip(visitor.ip_address)` | ✅ |
| `:611` | `:655` | `check_ip_privacy(visitor.ip_address)` | ✅ |
| `:652` | `:694` | Redis cache key `beam:resolution:{ip}` | ✅ |
| `:691` | `:733` | `if settings.company_graph_enabled and visitor.ip_address` | ✅ |
| `:695` | `:737` | **`_write_through_company_graph(db, visitor.ip_address, …, "paid_ip", 0.7)`** | ✅ |
| `:931` | `:973` | `_resolve_ip_company_parallel` | ✅ |

The `:695`/`:737` entry is the one that matters most and the plan does cover it: without the
override there, a retry resolving IP **B** would write a **cross-tenant** `company_graph` row keyed
on IP **A** at `source="paid_ip"`, confidence 0.7 — the top of the very tiebreak ladder this
plan's own AD-5 key 2 consumes. Poisoning that table is worse than corrupting one visitor row.
Gate `::sweep_does_not_persist_chosen_ip` (success / outage / exception) is adequate.

Residual → **C12** (log lines, below).

#### F2 — defer-exhaustion misdetection → **CLOSED ✅ for R1-a and R1-b, but the fix created F5**

Verified against live source (`identity_resolver.py:763-795`, `RESOLUTION_DEFER_BACKOFF` at `:92-97`):

- **R1-a closed.** With `resolution_defer_count = 0` pinned in the WHERE, `attempt = 0 + 1 = 1`,
  and `1 <= len(RESOLUTION_DEFER_BACKOFF)` (4) is always True — so `:764`'s False branch (the
  exhaustion fall-through to the `:792` reset) is **unreachable from this sweep**. `after > 0` is
  now an exact outage test.
- **R1-b closed.** The undecidable `before > 0, after == 0` state cannot be constructed when
  `before` is pinned to 0.
- **Writer census re-verified live and still complete:** exactly two writers,
  `identity_resolver.py:765` (increment) and `:792` (reset). No third writer anywhere in the repo.

**But see F5** — the predicate that makes the test exact also makes the exclusion permanent.

#### F3 — AC-8 tripwire → **CLOSED ✅**

`_AC2_FILES` is real (`tests/unit/test_agent_company_resolution.py:512-520`, seven entries) and
`test_ac2_filter_referenced_at_every_site` (`:532-538`) asserts the literal
`human_only_visitor_filter` is present in each listed file. Appending
`apps/api/services/reidentify_sweep_runner.py` therefore does create real coverage for the new
module. T16 is in Touchpoints, checklist 4.9 carries the edit, and the behavioural integration
gate `::agent_origin_never_selected` backs the text tripwire. Cycle 1's wrong-file citation
(`test_agent_origin_exclusion.py:236-247`, which asserts `source_agent_visit_id`) is corrected
in-place. Only drift: the plan says `:515-520`, live is `:512-520` (C11).

#### F4 — vacuous AC-11 / budget contention → **CLOSED ✅ as a mechanism, with a leak (C13)**

Both functions the D-B reserve depends on exist with exactly the cited signatures:
`get_site_daily_budget(db, site_id) -> int` (`usage_limits.py:55`) and
`get_resolution_attempts_today(db, site_id) -> int` (`:69`, DISTINCT-visitor count over
`ResolutionLog`). The reserve is implementable with **no new Redis key and no new meter**, exactly
as D6 requires, and the replacement gate `::retries_do_not_exhaust_first_identify_budget` is
non-vacuous (it can fail).

**Leak (C13):** the reserve is checked **once per site per tick**, before a `LIMIT 20` batch. On a
default 50/day budget a tick starting at 0 used consumes 20 (40%); the next tick starts at 20
(< 35) and consumes 20 more (80%) before the third tick is refused. So the guarantee delivered is
*"retries stop **starting** past 70%"*, not *"retries never exceed 70%"* — real reservation, but
up to 80% consumable. The named gate still passes with 10 slots left, so it is not vacuous, but
the plan's prose over-claims.

---

### NEW FAILs (cycle 2)

#### F5 — **HISTORICAL FAIL, RESOLVED BY S3-1** — one provider outage would have permanently retired the visitor

**AD-8 row 4 ("`resolve()` returned None because of an OUTAGE DEFER → count / skip_count /
next_at / tried_ips all unchanged") is factually incomplete: `resolve()` writes and COMMITS two
other columns on that path.**

Live proof (`identity_resolver.py:763-778`):

```python
attempt = (visitor.resolution_defer_count or 0) + 1     # :763  → 1 (pinned by the new WHERE)
if attempt <= len(RESOLUTION_DEFER_BACKOFF):            # :764  → True, always
    visitor.resolution_defer_count = attempt            # :765  → 1   ← COMMITTED
    visitor.resolution_deferred_until = now + 15m       # :766-768    ← COMMITTED
    await self.db.commit()                              # :777
    return None
```

`identity_status` is **not** changed by this branch, so the visitor stays `unresolvable` /
`vpn_filtered` — still inside the new sweep's status set. On the next tick:

- `resolution_not_deferred_filter()` (`resolution_eligibility.py:84-106`) re-admits it once the
  15-minute watermark passes — as designed.
- The new **`resolution_defer_count = 0`** term (AD-6) **excludes it forever.**

Nothing resets the counter. The only reset is `:792`, on the terminal fall-through, which requires
a `resolve()` call the sweep will never make again. The escape hatches are all closed by design:
`revive_returning_unresolvable` is a flag-gated no-op (AD-9), and manual Retry is exactly the click
this feature exists because customers never make.

**Net effect: the first transient provider outage a visitor encounters silently and permanently
removes them from auto re-identify — no attempt consumed, `count < 4` still true, invisible in the
"tried N/4" UI, and no log line says so.** This is the same class of silent permanent write-off the
plan's own Overview calls "the design bug at the centre of this plan", re-created by the cycle-1
fix. It defeats AC-3 and AC-4 for the deferred subset.

Second entry path (pre-existing population): a visitor deferred while `anonymous`
(`resolution_defer_count` 1–3) that later flips to `vpn_filtered` at `:650`/`:662` — which returns
before the defer block and never resets the counter — is excluded from the sweep **from day one**.

**Reachability:** requires `TIER_ALL_UNAVAILABLE` for `person_graph` or `ip_company`. Not constant,
but this feature's entire population is visitors on already-failing provider paths, and the cadence
runs for months.

**Superseding resolution:** neither historical option is authorized. S3-1 removes the defer-count
predicate, preserves resolver backoff, and uses explicit `provider_unavailable`; S3-6 specifies the
Hybrid integration gate that proves retained-watermark re-entry when due.

#### F6 — **FAIL** — the sweep would burn budget on PAUSED sites (`Site.tracking_enabled` missing)

Commit **`b2aa7ef`** (today, two commits before HEAD — after this plan was written) added a second
site gate to the main sweep, with an explicit rationale (`resolution_runner.py:252-261`):

```python
# `tracking_enabled` is a second, independent gate: a paused site
# (manual toggle OR the inactivity auto-pause) must not burn
# resolver/enrichment/Gemini credits draining its existing backlog.
# Ingest already 204s for these sites, so the backlog is frozen —
# this is what makes a pause actually stop spend.
select(Site).where(
    Site.auto_identify_enabled.is_(True),
    Site.tracking_enabled.is_(True),
)
```

The plan contains **zero** occurrences of `tracking_enabled`. AD-6 deliberately drops the
`auto_identify_enabled` gate (user-locked every-site coverage) and names that as the *only* removed
site gate. A paused site — manually paused, or auto-paused by the inactivity sweep that landed in
the same commit (`Site.auto_paused_at`, `models/site.py:60-68`) — would therefore have its terminal
visitors swept and its 50/day identify budget spent on historical IPs.

**D-D's `auto_reidentify_opt_out` does not cover this:** it is a manual column, and the auto-pause
is automatic and silent. A customer who paused Beam would still be billed provider spend.

**Required fix:** add `Site.tracking_enabled.is_(True)` to the new sweep's site selection
(alongside the `auto_reidentify_opt_out IS false` term), state it in AD-6 next to the
"no `auto_identify_enabled` gate" paragraph, and gate it with
`::paused_site_never_swept` (Hybrid).

---

### CONCERNs (cycle 2)

| # | Dimension | Finding | Evidence | Resolution |
|---|---|---|---|---|
| C7 | Infra fit | **Scheduler arithmetic is stale.** Checklist 5.4 formerly said 23/21 → 24/22. Live is **24 add_job / 21 interval / 3 cron** (`:219-221`; 12/12 green). Correct target after one interval registration is **25 / 22 / 3**, and the docstring/assert anchors moved to `:177-224`. | `tests/unit/test_scheduler_job_config.py:177-224`; live run 12 passed | Update 5.4 to re-derive from live AST, then add exactly one add-job and one interval assertion; retain three cron assertions. |
| C8 | Breaking changes | **Column count is inconsistent — 3 vs 4.** G5 added `auto_reidentify_skip_count` and the WHERE clause depends on it, but TL;DR (`:30`), T1 (`:111`), Public Contracts (`:150`, `:151`) and AD-1's heading + table (`:182-191`) all still say **three**. Only checklist 1.1 says four. A migration written from AD-1 omits the column the sweep query needs. | plan `:30,:111,:150,:151,:182-191` vs `:664-666` | Update all five sites to four columns; add the row to AD-1's table. |
| C9 | Infra fit | **Stale data-flow diagram.** `:617` still shows `ORDER BY never-attempted first, intent DESC` — the ordering AD-6 and checklist 4.3 explicitly DELETE as vacuous. The adjacent lines (`:618-622`) *were* updated for the reserve and pre-checks, so the block is half-supplemented and an execute-agent reading the diagram implements the deleted ordering. | plan `:617` vs `:350`, `:363-369`, `:719-720` | Rewrite `:617` to `ORDER BY next_at ASC NULLS LAST, intent DESC`. |
| C10 | Breaking changes | **Stale footprint constraints contradict D-A.** Sequencing (`:920`, `:922`) and the Autonomous Goal Block hard-stop (`:1327`) still say "keep `identity_resolver.py` to **ONE parameter**". D-A supersedes that with 2 params + 5 mixin files. An execute-agent obeying the goal block would treat the plan's own design as a violation. | plan `:920`, `:922`, `:1327` vs `:89-94` | Restate all three as "2 parameters + 5 defaulted mixin params (D-A); nothing beyond". |
| C11 | Infra fit | **Every path:line anchor is stale.** `identity_resolver.py` **+42** uniformly (`:502→:544`, `:583→:625`, `:589→:631`, `:593→:635`, `:602→:644`, `:611→:655`, `:652→:694`, `:691→:733`, `:695→:737`, `:721-723→:763-765`, `:750→:792`, `:931→:973`); `visitor_aggregator.py:365→:375`; `_AC2_FILES :515→:512`. **All content anchors verified stable** — this is pure line drift. | live greps | Handled by the plan's standing "re-derive every anchor" rule; recorded so cycle-1's "verified at plan time" claims are not re-trusted as current. |
| C12 | Security surface | **~13 log lines still print `visitor.ip_address` while the query used `override_ip`** — `identity_resolver.py:648` (`ip_prefix`), `:700`, `:703`; `pdl.py:97,104,106,109`; `rb2b.py:189,213,226,247,269,281`; `capturify.py:98`. Not a correctness defect (the functional path is fully covered — see F1), but every retry log attributes the outcome to the WRONG IP, which will actively mislead the first person debugging this feature. | live grep `visitor.ip_address` in `identity_providers/*.py` | Execute-agent instruction E5: use the effective IP in the mixins' log statements too, or drop the IP from them. |
| C13 | Test coverage | **The 70% reserve is checkable-but-leaky** (see F4 above): checked once per site per tick before a `LIMIT 20` batch, so retries can reach ~80% of a 50/day budget. The plan's prose reads as a hard 70% ceiling. | `resolution_runner`-shaped batch + `usage_limits.py:69` | Either re-check the reserve inside the per-visitor loop, or restate the guarantee honestly as "retries stop starting past 70%; worst case consumption is 70% + LIMIT". |
| C14 | Test coverage | **R4/R5 constants remain unmeasured** (70% reserve, `skip_count < 8`). Unchanged from cycle 1, correctly disclosed as placeholders and bound to the Measurement Gap rollout order. | plan `:883-884`, `:897-913` | Accept as disclosed open risks. |

### Retained PASSes (re-verified live this cycle)

| # | Finding | Live evidence |
|---|---|---|
| P3 | GDPR erasure inheritance is TRUE — visitor erasure is a full row DELETE, so `auto_reidentify_tried_ips` dies with the row and no new erasure target is created. | `apps/api/routers/visitors.py` erasure handler |
| P4 | `revive_returning_unresolvable`'s return value is discarded at its single call site, so an early `return 0` guard is safe and flag-off is byte-identical. | `visitor_aggregator.py:375`, single invocation |
| P5 | `auto_retry` bypassing exactly one line is correct — `if not force_retry and await self.was_recently_attempted(` is a single compound conditional at `:625`, and `do_not_resolve` / suppression / budget / no-IP / relay / IPinfo-VPN all sit on separate downstream statements. | `identity_resolver.py:625-662` |
| P6 (new) | `is_privacy_relay_ip` is pure, network-free, and covers **iCloud IPv6 only** (`_ICLOUD_PRIVATE_RELAY_V6_PREFIXES`) — the plan's AD-4 caveat and R6 are accurate, not overstated. | `company_resolver.py:233-243` |
| P7 (new) | The D-B reserve is implementable exactly as written — both helper functions exist with the cited async `(db, site_id)` signatures and the meter counts DISTINCT visitors, so retries and first-identifies share one honest counter. | `usage_limits.py:55-89` |

---

### III. Test Coverage Plan

Runner/commands sourced from `process/context/tests/all-tests.md` and from the blast-radius test
files, read directly. No command is inferred. Unit-lane baseline re-measured this cycle:
**1750 passed / 2 skipped**.

**Hybrid precondition (RUNNABLE — never "environment-blocked"):**

```
open -a Docker
/Applications/Docker.app/Contents/Resources/bin/docker compose -f infra/docker-compose.yml up -d postgres redis
lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'    # must print both before running Hybrid gates
```

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | org-tier IP outranks eyeball | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_reidentify_ranker.py -q` (`::org_over_eyeball`) | B |
| AC-1 | with no mmdb, `unknown` outranks `eyeball` | Fully-Automated | same file (`::unknown_ranks_second`) | B |
| AC-1 | `lookup_asn` → `(None, None)` yields tier `unknown` and `classify_ip_org_kind` is never called | Fully-Automated | same file (`::asn_none_short_circuits_to_unknown`) | B |
| AC-1/AC-2 | total order (permuted input ⇒ identical output) | Fully-Automated | same file (`::total_order_under_permutation`) | B |
| AC-2 | relay IP never chosen when a non-relay exists | Fully-Automated | same file (`::relay_excluded`) | B |
| AC-1 | seeded events ⇒ the attempted IP is the office IP | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_reidentify_sweep.py -q` (`::best_ip_selection`) | B |
| AC-3 | untried IP B re-opens a failed visitor, no manual action | Hybrid | same file (`::new_ip_revives`) | B |
| **AC-3 (F2)** | **all-provider outage traverses 15m/1h/6h/24h then repeats capped 24h without terminalising or accounting** | Hybrid | `tests/integration/test_reidentify_sweep.py::test_provider_unavailable_defers_through_ramp_and_repeats_cap` | **B — transactional gate must be added** |
| AC-4 | an IP in `tried_ips` is never re-attempted | Hybrid | `::tried_ip_not_looped` | B |
| AC-5 | `vpn_filtered` picked up only on a new non-relay IP | Hybrid | `::vpn_filtered_pickup` | B |
| AC-6 | daily meter counts distinct visitors, not rows | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_resolution_budget.py -q` (`::TestResolutionAttemptCounting::test_counts_distinct_visitors_not_rows`) | A |
| AC-6 | `deterministic_only=True` never consults the budget | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_identity_resolver_parallel.py -q` | A |
| AC-7 | a 4-attempt visitor is never selected again | Hybrid | `::cap_enforced` | B |
| AC-7 | provider unavailable at every defer stage and capped repeat consumes no attempt, no tried IP, no retry watermark, and no daily-count/log accounting | Hybrid | `::test_provider_unavailable_defers_through_ramp_and_repeats_cap` | B |
| AC-7 | budget-exhausted site consumes nothing and appends no `tried_ips` | Fully-Automated | `::budget_exhausted_site_consumes_nothing` | B |
| AC-7 | an exception consumes no attempt | Fully-Automated | `::exception_does_not_consume_attempt` | B |
| AC-7 | an exception advances `next_at` (no per-tick hot loop) | Fully-Automated | `::exception_advances_next_at` | B |
| AC-8 | the new sweep module is covered by the AC2 filter tripwire | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_agent_company_resolution.py -q` after appending the module to `_AC2_FILES` (**live `:512-520`**) | B |
| AC-8 | an agent-derived visitor in the new status set is never selected | Hybrid | `::agent_origin_never_selected` | B |
| AC-9 | `do_not_resolve` visitor never retried | Hybrid | `::do_not_resolve_never_retried` | B |
| AC-10 | no IP / no email in structlog from new paths | Fully-Automated | `::no_pii_in_logs` | B |
| AC-11 | every sweep selecting a terminal status carries `resolution_not_deferred_filter()` | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_resolution_deferral_watermark.py -q` (strengthened `_sweeps()`) | B |
| AC-11 | first-time-identify budget survives auto-retries running first on the same site | Hybrid | `::retries_do_not_exhaust_first_identify_budget` | B |
| **AC-11 (NEW — F6)** | **a site with `tracking_enabled = false` (manual pause OR inactivity auto-pause) is never swept and spends nothing** | Hybrid | new case `tests/integration/test_reidentify_sweep.py::paused_site_never_swept` | **B — gate does not exist; must be added** |
| AC-12 | flag OFF ⇒ revive byte-identical; flag ON ⇒ revive inert | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_unresolvable_revive.py -q` (flag-parametrised) | B |
| AC-12 | full lanes green with the flag unset | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` (baseline 1750/2) **and** `.venv/bin/python3.11 -m pytest tests/ -m integration -q` | A |
| AC-12 | scheduler registration correctness (**25/22 — re-derive live, see C7**) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_scheduler_job_config.py -q` | B |
| AC-13 | migration round-trips down/up on a **disposable** Postgres, head derived live (**live head `f4b9d2a71c68`**) | Hybrid | `DATABASE_URL=postgresql+asyncpg://…@localhost:5433/… .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` then `upgrade head` / `downgrade -1` / `upgrade head` | B |
| AC-13 | deleting the visitor row removes `auto_reidentify_tried_ips` with it | Hybrid | `::erasure_removes_tried_ips` | B |
| AC-7/AC-13 | `visitors.ip_address` unchanged in the DB after a sweep cycle (success / outage / exception) | Hybrid | `::sweep_does_not_persist_chosen_ip` | B |
| D-D / G9 | an `auto_reidentify_opt_out = true` site is never swept; default-false sites still are | Hybrid | `::opt_out_site_never_selected` | B |
| D-D / T19 | settings dialog round-trips opt-out without changing tracking / pause state; TypeScript declarations compile | Fully-Automated | `cd apps/web && npm run lint && npm run build` | B |
| S7 / F1 | manual Retry, APScheduler, Celery, and new reidentify sweep same-key race: exactly one winning top-level provider-capable dispatch, identified outcome, and winner-only success effects | Hybrid | `tests/integration/test_reidentify_resolution_leases.py::test_four_human_lane_lease_race_identified_once` | B |
| S7 / F1 | same four human lanes with provider no-match: exactly one winning top-level dispatch and one distinct daily-meter visitor; raw `ResolutionLog` rows are provider-fan-out dependent | Hybrid | `tests/integration/test_reidentify_resolution_leases.py::test_four_human_lane_lease_race_no_match_one_distinct_daily_meter_visitor` | B |
| S7 / agent domain | held synthetic-agent claim: exactly one agent-company winner; busy path makes no `resolve`, `_upsert_company`, AgentVisit link, billing/enrichment/defer/retry, or downstream side effect and releases only the owner token | Fully-Automated | `tests/unit/test_agent_company_resolution.py::test_agent_company_held_claim_is_side_effect_free_and_releases_exact_token` | B |
| S7 / agent defer | materialized/reused synthetic agent visitor honors automatic defer before claim; all-provider outage preserves/advances capped defer and becomes eligible only when due | Hybrid | `tests/integration/test_agent_company_resolution.py::test_agent_company_honors_defer_before_claim_with_outage_capped_repeat` | B |
| S8 / pre-success resolver exception | a claimed `resolver.resolve` exception occurs before any non-`None` result: zero usage increment and exactly one release of the owner token | Fully-Automated | `tests/unit/test_agent_company_resolution.py::test_agent_company_resolver_exception_does_not_meter_and_releases_exact_token` | B |
| S8 / post-success downstream exception | after a non-`None` resolver result, an upsert/link exception leaves exactly one prior usage increment, exactly releases the owner token, and retry adds no duplicate increment | Fully-Automated | `tests/unit/test_agent_company_resolution.py::test_agent_company_downstream_exception_meters_once_releases_exact_token_and_retry_does_not_duplicate` | B |
| S7 / temporal provenance | current person B at historical shared IP X is rejected when outside X's event-time window even if A's global `last_seen` is current for Y; B inside X's window remains matchable and `Visitor.last_seen` stays Y | Hybrid | `tests/integration/test_reidentify_sweep.py::test_historical_selected_ip_rejects_current_graph_record_outside_event_window` + `::test_historical_selected_ip_allows_graph_record_inside_event_window` | B |
| S7 / census | every production resolver/private-provider-wrapper source is explicitly classified as four-human claim, agent-domain claimant, deterministic-only, or out-of-scope with checked reason | Fully-Automated | `tests/unit/test_resolution_deferral_watermark.py::TestProviderCapableResolverCallerCensus::test_provider_capable_resolver_census_is_exhaustive` | B |
| S4-3 / C1 | 12 NULL + 12 due yields 10+10 then 2+2 next tick; 3 NULL + 18 due yields 3+10+7 with no duplicate visitor | Hybrid | `tests/integration/test_reidentify_sweep.py::test_two_pool_ten_each_and_spillover` | B |
| G11 | `unresolvable` → `vpn_filtered` flip still counts the attempt and appends `tried_ips` | Fully-Automated | `::vpn_flip_still_counts_attempt` | B |
| D-C / G7 | manual retry succeeds on a `vpn_filtered` visitor with a non-relay untried IP; fails with only relay IPs | Hybrid | integration case over `routers/visitors.py:905-931` | B |
| UI policy | "tried N/4" renders on list + detail; Manual Retry neither consumes nor resets | Agent-Probe | browser check of `/dashboard/visitors` and `/dashboard/visitors/[visitorId]` | A |
| AC-14 | whether a given corporate IP actually resolves via paid providers | Agent-Probe | live-provider double-opt-in required; explicitly-justified residual | C |
| Rollout | distinct-IPs-per-visitor distribution on real data | — (named residual) | rollout gate; backlog stub required | **D** |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: the `strategy:` column carries ONLY the 3 proving strategies
(Fully-Automated / Hybrid / Agent-Probe). Known-Gap is never a `strategy:` value — the one residual
(distinct-IPs measurement) is carried as gap-resolution **D**.

Legacy line form (retained so existing validate-contract consumers still parse):
- ranker: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_reidentify_ranker.py -q`
- sweep accounting: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_reidentify_sweep.py -q`
- sweep behaviour: `hybrid: .venv/bin/python3.11 -m pytest tests/integration/test_reidentify_sweep.py -q + precondition: docker compose -f infra/docker-compose.yml up -d postgres redis (ports 5433/6379 listening)`
- regression lanes: `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit -m unit -q (baseline 1750 passed / 2 skipped); .venv/bin/python3.11 -m pytest tests/ -m integration -q`
- migration: `hybrid: alembic heads/upgrade/downgrade + precondition: disposable Postgres, DATABASE_URL pinned to localhost:5433 (live head f4b9d2a71c68)`
- UI counter: `agent-probe: browser check of visitor list row + detail page`
- provider resolvability: `agent-probe: live-provider double-opt-in`
- IP-distribution measurement: `known-gap: documented as rollout gate — backlog stub required`

TDD note: the F5 outage and shared-claim races are Hybrid PostgreSQL gates and therefore have no
unit-test stub. The IP-only resolver gate remains Fully-Automated; its test must spy on
`_check_prior_signals`, captured-email lookup, fingerprint lookup, and identity-graph lookup and
assert none is invoked when `auto_retry=True`.

---

Dimension findings:
- Infra fit: **FAIL** — the new sweep has no `Site.tracking_enabled` gate, so a manually-paused or auto-paused site would still burn identify budget (F6, `resolution_runner.py:260`, commit `b2aa7ef`). Also: the scheduler arithmetic the plan hardcodes is already stale (C7 — live 24/21, target 25/22), the data-flow diagram still shows the deleted ORDER BY (C9), and every anchor has drifted ~+42 lines though all content anchors verified stable (C11).
- Test coverage: CONCERN — both cycle-1 test FAILs are genuinely closed (F3's `_AC2_FILES` tripwire is real and the append works; F4's reserve gate is non-vacuous and its two helper functions exist with the cited signatures). Remaining: no gate exists for F5 or F6, the 70% reserve is leaky to ~80% (C13), and R4/R5 stay unmeasured (C14).
- Breaking changes: **HISTORICAL FAIL, superseded by S3-1/S3-2** — the former design inferred an
  outage from defer mutations and would have cleared that state. The current contract uses an
  explicit outcome, retains the watermark, and serializes manual/sweep provider work with a shared
  claim; fresh V1 must verify the new contract before the gate can pass.
- Security surface: CONCERN — F1 is genuinely closed and the override list is exhaustive, including the cross-tenant `_write_through_company_graph` write at `:737` that would otherwise have poisoned `company_graph` at `source="paid_ip"` conf 0.7. C6 is closed by D-D's opt-out. Remaining: ~13 log lines attribute retry outcomes to the wrong IP (C12).
- Phase-01 Schema: CONCERN — additive/no-index/no-backfill posture is right and the live-head mandate is correct (head is now `f4b9d2a71c68`), but the plan says three columns in five places and four in one (C8).
- Phase-02 Pure ranker: PASS — the mandatory `asn is None → "unknown"` short-circuit makes the `unknown`-second decision non-vacuous, the pure/gatherer split and injected clock match repo idiom, and `classify_ip_org_kind`'s four return values are accurate. Highest-risk edit: the business-hours abstain rule; mitigated by the permutation test.
- Phase-03 Resolver parameters: CONCERN — mechanically feasible and now *complete* (all 7 override sites verified, including the company-graph write-through), but the file is contested by three unexecuted plans and every anchor moved (C11); log lines need the effective IP too (C12).
- Phase-04 Sweep runner: **FAIL** — carries F5 and F6, plus the stale ORDER BY in the diagram (C9) and the leaky reserve (C13). Highest-risk edit: the outage branch — sequence it last and gate it with both `::sweep_does_not_persist_chosen_ip` and the new `::deferred_visitor_re_enters_sweep_after_outage_clears`.
- Phase-05 Flag/scheduler/revive: CONCERN — the tripwire strengthening and the revive early-return are sound (P1/P4), but 5.4 hardcodes an arithmetic that today's commits already invalidated (C7).
- Phase-06 UI counter: PASS — the `VisitorOut` base-class instruction correctly encodes the prior P0 lesson; D-C/D-D surfaces are additive and the retry-endpoint anchors (`:905-931`, `:960`) verified stable.
- Phase-07 Regression + rollout: CONCERN — rollout order is right; the measurement residual keeps the rollout gate CONDITIONAL and its backlog stub is required, not optional.

Open gaps:
- Distinct-IPs-per-visitor distribution on real data: known-gap: documented as rollout gate — a backlog stub MUST be written before EXECUTE closes (`process/features/visitors-identity/backlog/`). Not a build blocker; blocks the prod flag flip only.
- AC-14 (real-world resolvability of a specific corporate IP): Agent-Probe residual, live-provider double-opt-in policy applies. Explicitly justified.
- 70% reserve threshold and `skip_count < 8` bound (R4/R5): unmeasured placeholders, bound to the Measurement Gap rollout order.

What this coverage does NOT prove:
- `tests/unit/test_reidentify_ranker.py` runs with **no mmdb**, so every IP classifies as `unknown`. It proves the ordering logic and the short-circuit; it does not prove a real corporate IP classifies as `org` in production.
- `tests/integration/test_reidentify_sweep.py` runs against seeded rows with mocked providers. It does not prove any provider returns a match for the chosen IP, does not prove the per-visitor `GROUP BY ip_address` latency at production row counts, and does not prove behaviour under concurrent execution on two API replicas beyond the advisory lock's own semantics.
- `::sweep_does_not_persist_chosen_ip` proves `visitors.ip_address` is unchanged. It does **not** prove the *other* columns `resolve()` commits are unchanged — that hole is exactly F5, and it stays unproven until the new `::deferred_visitor_re_enters_sweep_after_outage_clears` gate exists.
- `tests/unit/test_scheduler_job_config.py` is an AST scan of the registration source. It proves the job is *declared* correctly; it does not prove APScheduler fires it, that the advisory lock is acquired at runtime, or that the boot offset behaves on a real deploy.
- `tests/unit/test_resolution_deferral_watermark.py`'s `_sweeps()` is a substring heuristic even strengthened; it proves the literal appears in the file, not that the filter is applied to the right query at runtime.
- `_AC2_FILES` is a text search over a hardcoded list; it proves the literal `human_only_visitor_filter` is present, not that the filter sits in the selection query rather than a comment.
- The migration round-trip on a disposable Postgres does not prove the migration applies against production volumes or lock duration on a large `visitors` table (prod head is `c4a8f13e07b6`; local head is `f4b9d2a71c68`).
- Full lanes with the flag unset prove no *observable* behaviour changed; with the flag off none of the new code executes, so latent defects in the new modules are untested by them.
- The Agent-Probe UI check proves the counter renders, not that it is correct against the DB.
- Nothing measures actual provider spend produced by auto-retries — failed attempts are priced $0.00 and the meter counts distinct visitors.

Gate: BLOCKED — historical PVL findings are addressed by Supplement 3 below; a new VALIDATE V1 is
required to adjudicate the changed contract. This plan does not self-pass its own supplement.
Accepted by: none — BLOCKED verdicts cannot be self-accepted. No user acceptance was given in this session; the validate-agent does not accept its own gate.

---

## PVL Supplement 3 — authoritative blocker resolution (11-08-26)

**Status:** `Gate: BLOCKED` pending a fresh VALIDATE V1 pass. This supplement replaces only the
rejected outage-restore, single-order selection, incomplete opt-out UI, and insufficient
manual/sweep-concurrency parts of the plan. Threshold **35**, no-stamp budget refusal,
`tracking_enabled` selection gate, the four Visitor attempt columns, and the already-planned backend
`SiteUpdate`/`SiteOut`/router work remain locked.

### S3-1 — Resolver result and retained outage backoff

`IdentityResolver.resolve()` keeps its existing return type for every current caller. Refactor its
body into one private result-producing core, and add exactly one sweep-facing method:
`resolve_auto_retry(visitor, *, override_ip: str) -> ResolutionAttemptResult`.

`ResolutionAttemptResult` has exactly three fields: `identified` (`IdentifiedVisitor | None`),
`outcome` (`identified | no_match | provider_unavailable | skipped`), and
`provider_work_started` (`bool`). Its `provider_unavailable` value must be derived from the existing
`RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE` taxonomy, not reconstructed from ORM fields. Its
`provider_work_started` is false for privacy, suppression, budget, missing-IP, relay/VPN, and
pre-provider exits; it is true only after the resolver dispatches a provider tier.

The defaulted automatic mode is `auto_retry=False`; when true it is **IP-only**: it bypasses only
the 30-day recent-attempt gate and skips `_check_prior_signals` completely. Therefore it never calls
the captured-email, fingerprint, or Beam identity-graph paths currently entered at
`identity_resolver.py:603-620`. It still runs the sticky `do_not_resolve` and suppression guards at
`:586-601`, the daily budget guard at `:631-633`, and the IP relay/VPN guards at `:641-666`.
Manual retry remains `force_retry=True`, is not IP-only, and does not use the automatic result
method.

When the core reaches the existing all-unavailable branch at `identity_resolver.py:761-778`, it
commits the resolver's own defer count and deadline, returns `provider_unavailable`, and does not
write a terminal status. The sweep releases its lease and changes no count, skip count, next-at, or
tried-IP field. Its next selection is naturally controlled by
`resolution_not_deferred_filter()`; after the retained deadline is due, the row may enter the due
pool. **No sweep path, manual retry path, or claim helper writes either defer field.** The prior CAS
restore and `resolution_defer_count = 0` predicate are rejected permanently.

### S3-2 — Shared manual/sweep per-visitor claim

Add `reidentify_resolution_claims`, a small non-PII table with Base's normal UUID primary key plus a
unique `(site_id, visitor_id)` conflict key, opaque UUID `owner_token`, and naive-UTC `expires_at`.
Its composite foreign key is the existing unique `visitors(site_id, visitor_id)` key with `ON DELETE
CASCADE`; the table adds no
IP, email, provider payload, or durable outcome. The migration must preflight for orphaned keys
before adding the FK, add the table without a backfill, and prove parent-row deletion cascades the
claim.

`reidentify_claims.py` owns two functions and no caller may open-code their SQL:

- `try_claim_resolution(db, site_id, visitor_id, now)`: atomically insert a fresh token or replace
  only an expired claim, returning the token and expiry to its winner; a live conflict returns
  `None`. The lease duration is the new defaulted config value
  `auto_reidentify_claim_lease_seconds = 300`, chosen to exceed the resolver's documented provider
  timeout/retry envelope.
- `release_resolution_claim(db, claim)`: delete only where both visitor key and owner token match;
  a zero-row delete is safe because the lease either expired or a later owner reclaimed it.

The sweep obtains the claim after ranking and the no-stamp reserve pre-check, but before creating a
resolver or dispatching provider work. A live claim is excluded by the candidate predicate when
possible and, if raced after selection, increments only a `claim_busy` counter. It never consumes a
batch attempt, adds a tried IP, changes `next_at`, changes a defer field, or increments the skip
counter.

The manual endpoint verifies ownership and all pre-provider policy gates first, then claims before
it flips a retryable terminal row or calls the resolver. If another actor holds the claim, it returns
HTTP 409 with `{status: "retry_in_progress"}` and makes no visitor-state write. Both paths release
their exact token in `finally`, after their own resolver work finishes. This closes the gap that the
sweep-wide advisory lock cannot cover: an HTTP request does not hold that sweep lock.

### S3-3 — One selection algorithm and refill rule

AD-6's `null_base`, `due_base`, and `spillover` construction is the sole selection algorithm.
Implementation must use CTEs or an equivalent single transaction with the same disjoint sets and
sort keys; it must not issue the formerly described single sorted `LIMIT 20` query or independently
re-query a pool. Base pool quotas are 10 NULL + 10 due. Spillover fills only unused capacity after
both bases have been measured, excludes both base result sets, and can use either population.

The sweep returns counters `selected_null_base`, `selected_due_base`, `selected_spillover`,
`claim_busy`, and `processed`; these make both the allocation and the race visible without logging
IPs. With more than ten candidates in each pool, one tick processes at most ten from each. With a
short base pool, the other population supplies all remaining slots. Rows selected but claim-busy are
not backfilled in the same tick; the next scheduled run refills safely. These rules are complete and
replace all former NULLS FIRST/LAST statements, diagrams, and refill prose.

### S3-4 — Opt-out frontend contract

Add `auto_reidentify_opt_out: boolean` to `Site` and
`auto_reidentify_opt_out?: boolean` to `SiteUpdate` in `apps/web/src/lib/api-types.ts`; this mirrors
the additive backend `SiteOut` and nullable `SiteUpdate` fields. In
`apps/web/src/components/site-settings-dialog.tsx`, add a dedicated mutation using
`api.updateSite(siteId, { auto_reidentify_opt_out: value })`, invalidate the site query on settle,
and render the setting adjacent to the existing Pause-tracking section.

Its visible control is labelled **“Automatic identity retries”**, displays **Enabled** when the
stored opt-out is false and **Disabled for this site** when true, and sends the inverse value on the
button action. Its explanatory text must say that disabling prevents only this site's automatic
new-IP retry sweep; it does not pause tracking, alter `auto_identify_enabled`, erase data, or block
the manual Retry action. The control must not write `tracking_enabled` or `auto_paused_at`.

### S3-5 — Exact checklist deltas

1. Update T2's migration to add the cascade-erased claim table; retain exactly the existing four
   Visitor attempt columns and Site opt-out column. Add its upgrade, downgrade, orphan-preflight,
   and cascade proof to Phase-01.
2. Create `reidentify_claims.py` with the lease contract above and use it from exactly the new sweep
   and the manual retry endpoint; do not rely on the sweep advisory lock for request coordination.
3. Refactor `identity_resolver.py` through the private result core; preserve `resolve()` behavior,
   route the new automatic path through `resolve_auto_retry()`, and enforce IP-only prior-signal
   skipping.
4. Replace Phase-04's selection implementation with the authoritative two-base-plus-spillover
   algorithm, retain the `tracking_enabled` and 35-attempt gates, remove all defer restore logic,
   and account only a `no_match`/`identified` result with `provider_work_started=true`.
5. Update the manual retry endpoint to use the shared lease and return `retry_in_progress` on a live
   claim before it changes status; preserve its current non-relay `vpn_filtered` predicate.
6. Correct T19/Phase-06 to change both frontend type declarations and the exact settings dialog;
   add the frontend lint and production build gates.
7. Update scheduler expectations from current **24 add-job / 21 interval / 3 cron** to **25 / 22 /
   3** after the new interval registration, with the source-derived changelog prose.

### S3-6 — Required verification evidence (fresh gates)

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `tests/unit/test_identity_resolver_parallel.py::auto_retry_skips_captured_email_fingerprint_and_graph` — spies make each prior-signal branch fail if invoked, then prove paid IP work can proceed | Fully-Automated | AC-3 / Out-of-scope non-IP waterfall rule |
| `tests/integration/test_reidentify_sweep.py::test_provider_unavailable_defers_through_ramp_and_repeats_cap` — real PG; force every provider tier unavailable through stages 1–4 and one more due retry, assert the 24h capped repeat, preserved watermark, no pre-due dispatch, and zero attempted-IP/count/log accounting | Hybrid | AC-3, AC-7 (F2: outage is neither consumed nor terminally stranded) |
| **Superseded by S7** | `test_four_human_lane_lease_race_identified_once` and `test_four_human_lane_lease_race_no_match_one_distinct_daily_meter_visitor` replace this former three-lane scope; agent-company is separately reentrancy-gated; see S7-4 | Hybrid | AC-4, AC-7 |
| `tests/integration/test_visitor_resolve_endpoint.py::test_live_claim_returns_retry_in_progress_without_state_write` — endpoint-only held-claim contract: 409 and unchanged terminal state/counters | Hybrid | AC-4, AC-7 (manual API conflict behavior) |
| `tests/integration/test_reidentify_sweep.py::test_two_pool_ten_each_and_spillover` — the sole allocation test: 12 NULL + 12 due proves 10+10 then 2+2 next tick; 3 NULL + 18 due proves 3+10+7, no duplicate visitor | Hybrid | AC-3, AC-11 (C1 authoritative allocation/refill) |
| `tests/integration/test_site_settings.py::auto_reidentify_opt_out_round_trip_preserves_auto_pause` — PATCH response and fresh read both expose the value, and `auto_paused_at` is unchanged | Hybrid | AC-12 / D-D opt-out contract |
| `cd apps/web && npm run lint` and `cd apps/web && npm run build` after the typed setting is wired | Fully-Automated | AC-12 / D-D frontend type and production-build compatibility |
| `tests/unit/test_scheduler_job_config.py` with 25 / 22 / 3 assertions | Fully-Automated | AC-12 scheduler registration |

The first two rows replace the earlier F5/CAS rows. They are **Hybrid**, not unit tests: they assert
committed database state, time-based eligibility, and an inter-session race. The rejected
`restore_skipped_when_row_moved_concurrently` gate is removed; the new claim race gate proves the
actual concurrency boundary.

### S3-7 — Security and failure-mode disposition

STRIDE review: spoofing is contained by owner-scoped manual access before claim; tampering is
contained by token-matched release and no client-controlled token; repudiation is contained by
claim-busy and outcome counters without IP logs; information disclosure is contained because the
claim table stores only identifiers and leases cascade on erasure; denial-of-service is bounded by
one 300-second claim per visitor plus the existing 35-attempt reserve; privilege escalation is
unchanged because the existing site-owner access check precedes the claim. A stuck process self-heals
after the lease expiry, and an expired owner cannot delete a later owner's claim.

Failure policy: a claim SQL failure fails closed for automatic retry (no provider work and no
accounting); manual retry returns a retry-unavailable 503 without changing state. A resolver
`provider_unavailable` result retains its watermark; a no-match/identified result performs normal
attempt accounting; a local exception advances only `next_at`; a budget refusal still stamps
nothing. None of these paths logs an IP, email, lease token, or raw provider error.

### S3-8 — validate handoff

The old cycle-2 validation narrative is historical evidence only. Re-run VALIDATE from V1 against
this plan, including the new Hybrid race and two-pool gates. Gate remains **BLOCKED** until that run
produces a fresh verdict; EXECUTE is not authorised.

---

## PVL Supplement 4 — capped outage repeat and former three-lane lease record (11-08-26)

**Status:** `Gate: BLOCKED` pending a fresh VALIDATE V1 pass. Its outage/retry material remains
authoritative; **its S4-1, S4-3, S4-4 lane inventory and race names are superseded by S7**. Do not
execute the three-lane statements below; S7 is the complete provider-capable census and test contract.

### S4-1 — One atomic lease protocol across all provider-dispatch lanes (F1)

The shared `reidentify_resolution_claims` lease is mandatory for all three lanes that can invoke
paid-provider work for the same `(site_id, visitor_id)`:

1. manual `POST /visitors/{site_id}/{visitor_id}/resolve`;
2. incumbent scheduler `apps/api/services/resolution_runner.py::run_resolution_for_site`; and
3. new `reidentify_sweep_runner`.

The lease is not a sweep-only feature and the incumbent advisory lock is not a substitute: the
advisory lock serializes scheduler replicas, but does not cover HTTP manual retry or the separately
scheduled reidentify sweep. Every lane must call only `try_claim_resolution(...)` and
`release_resolution_claim(...)`; no lane may open-code an insert, an expiry replacement, or a
delete.

`run_resolution_for_site` must keep its monthly-plan check first, then acquire the shared claim
immediately before its per-visitor `IdentityResolver.resolve(...)` call and before it increments its
`processed` counter. On busy claim it increments a new internal `claim_busy` counter and continues:
it makes no resolver/provider call, no billing/enrichment call, no `ResolutionLog`/daily-meter
write, and no retry-state/defer write. Add `claim_busy` to the per-site return dict and scheduler
aggregate so the skipped conflict is observable without logging IDs, IPs, or lease tokens. On a
winning claim it releases the exact token in `finally`, including resolver failure.

Manual retry retains its existing policy checks and its 409 `{status: "retry_in_progress"}` response
on a busy claim. The new sweep retains its no-stamp busy behavior. Thus a claim winner is
lane-neutral: exactly one lane can reach a provider; the losing lanes may report their local busy
outcome but cannot mutate resolver, billing, or auto-retry accounting.

### S4-2 — Provider-unavailable after finite defer exhaustion (F2)

`RESOLUTION_DEFER_BACKOFF` remains the finite ramp `(15m, 1h, 6h, 24h)`, but it is no longer a
terminal-outage limit. In the all-provider-unavailable branch, calculate the next delay with
`min(current_defer_count, len(RESOLUTION_DEFER_BACKOFF) - 1)` and cap the persisted count at
`len(RESOLUTION_DEFER_BACKOFF)`. Stages 1–4 therefore use each configured delay once. Every later
all-provider outage keeps `resolution_defer_count == len(RESOLUTION_DEFER_BACKOFF)` and writes a
new `resolution_deferred_until = now + RESOLUTION_DEFER_BACKOFF[-1]` (24 hours).

The all-provider-unavailable branch returns the explicit `provider_unavailable` result, retains the
visitor's current `identity_status`, and never falls through to the terminal reset
(`identity_status = "unresolvable"`, defer count `0`, defer deadline `None`). Only a real provider
answer/no-match follows the existing terminal path. No caller or claim helper writes the defer
fields. **Superseded manual-filter wording:** `resolution_not_deferred_filter()` belongs only in
automatic selection (APScheduler, Celery, agent-company where applicable, and the new retry sweep).
Manual Retry deliberately ignores a future defer deadline, claims, and calls
`resolve(force_retry=True)` immediately; on an unavailable result its existing endpoint
`_resolution_skip_reason(...)` path returns HTTP 200 `anonymous/provider_outage`. It does not gain a
new resolver result-return API.

At *every* outage stage, including the fifth capped-repeat call, the following are invariant:
`auto_reidentify_count`, `auto_reidentify_tried_ips`, `auto_reidentify_next_at`, and
`auto_reidentify_skip_count` are unchanged; no `ResolutionLog` exists for that outage; and the
distinct-visitor daily meter is unchanged. Before each recorded watermark is due there is zero
provider dispatch; once due, the next selected invocation may dispatch exactly once under S4-1.

### S4-3 — Canonical test ownership and exact Hybrid gates (C1)

The former names `manual_and_sweep_share_one_resolution_claim`,
`two_pool_quota_and_spillover`, `two_pool_ten_each_then_refill_next_tick`, and
`two_pool_short_null_refills_from_due` are retired. No checklist, evidence table, or validate
contract row may cite them. Canonical ownership is:

| Owner file | Exact test name | Deterministic setup and required assertions |
|---|---|---|
| `tests/integration/test_reidentify_resolution_leases.py` | **Superseded by S5** | S5-4 replaces the three-lane cases with four-lane tests that include Celery and prove one top-level winner plus one distinct daily-meter visitor, not a global one-log promise. |
| `tests/integration/test_visitor_resolve_endpoint.py` | `test_live_claim_returns_retry_in_progress_without_state_write` | Endpoint-only 409 contract against a pre-held live claim; assert terminal status and all retry fields unchanged. This file does not own the cross-lane race. |
| `tests/integration/test_reidentify_sweep.py` | `test_provider_unavailable_defers_through_ramp_and_repeats_cap` | Force every eligible provider tier unavailable for five due invocations. Assert exact 15m/1h/6h/24h defer stages, then a fresh capped 24h deadline at count 4; assert no pre-deadline dispatch and zero attempted-IP/count/log/daily-meter accounting at all five stages. |
| same file | `test_two_pool_ten_each_and_spillover` | One canonical allocation test with two subcases: 12 NULL + 12 due yields 10 NULL + 10 due, then 2 + 2 on the next tick; 3 NULL + 18 due yields 3 + 10 + 7 spillover. Assert no visitor is duplicated. |

All five tests are **Hybrid** because they require real PostgreSQL transaction isolation, committed
ORM state, or the production query shape. The commands are exactly:
`.venv/bin/python3.11 -m pytest tests/integration/test_reidentify_resolution_leases.py -q`,
`.venv/bin/python3.11 -m pytest tests/integration/test_reidentify_sweep.py -q`, and
`.venv/bin/python3.11 -m pytest tests/integration/test_visitor_resolve_endpoint.py -q`, after the
loaded Docker/ports precondition in `process/context/tests/all-tests.md`.

### S4-4 — Exact checklist and handoff deltas

1. Phase-03 / resolver work must change the all-provider-unavailable terminal branch per S4-2 and
   update `tests/unit/test_resolution_deferral_watermark.py` so its former
   `test_past_the_last_step_writes_off_and_resets` assertion is replaced by the capped-repeat
   contract; the five-stage real-Postgres proof remains the canonical Hybrid test above.
2. Phase-04 must use the lease in the new sweep and the incumbent scheduler. Create
   `tests/integration/test_reidentify_resolution_leases.py`; do not add the race cases to either
   `test_reidentify_sweep.py` or `test_visitor_resolve_endpoint.py`.
3. Phase-04's allocation proof is only
   `tests/integration/test_reidentify_sweep.py::test_two_pool_ten_each_and_spillover`; it owns both
   10/10 and spillover subcases.
4. Re-derive live anchors before execution: `resolution_runner.py::run_resolution_for_site`,
   `identity_resolver.py` all-provider-unavailable branch, and
   `tests/unit/test_resolution_deferral_watermark.py::TestBackoff`. Never trust the recorded line
   numbers after this supplement.

### S4-5 — historical validate handoff (superseded for lease scope)

Re-run VALIDATE from V1 with F1/F2/C1 as changed surfaces. S7 supersedes this lease-scope handoff:
V1 must verify four-human and agent-domain acquisition/release ordering, the deterministic promotion barrier,
metadata/create-all/cascade proof, immediate manual-during-defer policy, all-provider capped-repeat
behavior, and the bidirectional AC-3/AC-4/AC-7/AC-13 evidence links. EXECUTE remains unauthorised
until that fresh verdict clears `Gate: BLOCKED`.

---

## PVL Supplement 5 — complete provider-lane lease, mapped claim table, and manual outage policy (11-08-26)

**Status:** `Gate: BLOCKED` pending a fresh VALIDATE V1 pass. This historical four-lane supplement
preserves its IP-only automatic mode, capped outage repeat, selection/reserve/opt-out fixes, and
default-OFF rollout posture; **S7 is authoritative for census, claim domains, race-test names, and
historical-IP provenance.**

### S5-1 — Exact lane boundary and lease ordering

The shared `reidentify_resolution_claims` lease covers every currently provider-capable top-level resolver lane: manual endpoint, APScheduler `resolution_runner`, registered Celery `resolution_tasks`, and the new reidentify sweep. The advisory locks in scheduler wrappers are not a substitute because they neither serialize HTTP nor coordinate different runner processes.

For every covered lane, preserve its ownership/privacy/candidate/budget checks, then call `try_claim_resolution(db, site_id, visitor_id, now)` immediately before the first provider-capable top-level resolver entry and release that returned owner token in `finally`.

1. **Manual:** authorization → visitor/human lookup → privacy/eligibility/monthly gates → claim → only then reset a retryable terminal state / call `resolve(force_retry=True)`.
2. **APScheduler:** selection + monthly-plan check → claim → only then increment `processed` / call `resolve(...)` → release.
3. **Celery:** `_process_site` selection + monthly billing check → claim → only then call `resolve(...)`, then success-only usage/enrichment/side effects → release.
4. **New sweep:** ranking + no-stamp prechecks + per-visitor reserve → claim → only then call `resolve_auto_retry(...)`, then result-aware retry accounting → release.

A busy claim never starts provider-capable resolver work. It makes no `ResolutionLog` or distinct-meter change, no billing/enrichment/segmentation state change, no retry/defer write, and no terminal-status flip. Manual returns HTTP 409 `{status: "retry_in_progress"}`; APScheduler, Celery, and the new sweep increment only their non-PII `claim_busy` counter and continue. Claim SQL failure fails closed for automatic lanes and returns the existing planned 503 manual-unavailable outcome without a visitor-state write.

`promotion_sweep_runner` is not a fifth provider lane only because execution must change it to call `resolve(visitor, deterministic_only=True)`. That is an enforceable barrier: `IdentityResolver.resolve` returns after deterministic prior signals and before paid-provider gates. Its `unexpected_paid` counter becomes a defense-in-depth alarm, not proof after spend. Any future bypass of this argument makes promotion provider-capable and must add the shared lease plus a new race gate before execution.

### S5-2 — Claim model, migration, and Hybrid fixture availability

Create `apps/api/models/reidentify_resolution_claim.py` with `ReidentifyResolutionClaim(Base)`. Base supplies its ordinary UUID `id`; define a named unique constraint on `(site_id, visitor_id)`, UUID `owner_token`, and nullable-free naïve-UTC `expires_at`. Define one named composite foreign key on `(site_id, visitor_id)` to already-unique `visitors(site_id, visitor_id)`, `ON DELETE CASCADE`. The lease helper owns insert-or-expired-replace and token-matched delete; the table model owns no policy logic.

Add `from apps.api.models.reidentify_resolution_claim import ReidentifyResolutionClaim  # noqa: F401` to `apps/api/main.py`'s create-all import block. Do not merely add it to the models package initializer: both Alembic `env.py` and `tests/conftest.py` import `apps.api.main`, and the Hybrid fixture calls `Base.metadata.create_all()` after that import. This exact path makes the table exist in a fresh test database and makes migration autogenerate see it. The additive migration creates the empty table with the FK/UQ directly, has no child backfill/orphan preflight, and downgrades by dropping the child table before its parent columns.

### S5-3 — Manual retry during outage defer

The product policy is **immediate manual retry**: a site owner intentionally clicking Retry may dispatch once even when `resolution_deferred_until` is in the future. The defer filter is exclusive to automated scheduler/sweep selection queries; it must not be inserted into the manual endpoint or `IdentityResolver.resolve`. A manual winner calls `resolve(force_retry=True)` after claiming, so it bypasses only the existing 30-day recency gate and retains privacy, suppression, daily-budget, VPN, and monthly-plan gates.

If configured providers are unavailable, the resolver retains/advances its bounded defer watermark, releases the claim, and the endpoint returns HTTP 200 with the existing observable outcome `{status: "anonymous", skip_reason: "provider_outage"}`. It does not write a `ResolutionLog`, increment the distinct daily meter, or consume automatic retry count/tried-IP state. This resolves the former contradiction: a manual action is not silently queued behind a scheduled outage watermark, while automated loops remain backoff-safe.

### S5-4 — Canonical verification ownership and accounting semantics

All scenarios below are Hybrid: they require the repository's real PostgreSQL fixture, committed state, or independent sessions. Preconditions and commands are those loaded from `process/context/tests/all-tests.md`: local Postgres/Redis listening on 5433/6379, then `.venv/bin/python -m pytest <file> -q`.

| Owner file | Exact gate | Required setup and assertion |
|---|---|---|
| `tests/integration/test_reidentify_resolution_leases.py` | `test_four_lane_lease_race_identified_once` | Barrier-race manual API, `run_resolution_for_site`, Celery `_process_site`, and `run_reidentify_sweep_once` just before claim. Stub one enabled provider to identify. Assert one lease winner, exactly one top-level provider-capable resolver dispatch, one `IdentifiedVisitor`, and only winner success-side effects. |
| same file | `test_four_lane_lease_race_no_match_one_distinct_daily_meter_visitor` | Same race with one enabled provider returning no-match. Assert exactly one top-level winner and `get_resolution_attempts_today(site_id) == 1`; losing lanes make no accounting or retry mutation. Do **not** assert a global raw `ResolutionLog` row count. |
| same file | `test_claim_model_registered_by_create_all_and_cascades` | Use normal `test_engine` (`apps.api.main` import then `Base.metadata.create_all()`), assert table present, create visitor + claim, delete visitor, commit, then a fresh session observes no claim row. |
| `tests/integration/test_visitor_resolve_endpoint.py` | `test_live_claim_returns_retry_in_progress_without_state_write` | Held live claim returns HTTP 409 and leaves terminal/retry state unchanged. |
| same file | `test_manual_retry_runs_during_active_defer_and_reports_provider_outage` | Seed future defer, force provider-unavailable, click Retry. Assert dispatch despite defer, HTTP 200 `anonymous/provider_outage`, retained/capped watermark, zero log/meter increment, and release. |
| `tests/integration/test_promotion_sweep.py` | `test_promotion_sweep_is_deterministic_only_and_never_claims_lease` | UTM click promotes through deterministic evidence while spies fail on claim acquisition or paid-provider work; assert `deterministic_only=True` and `unexpected_paid == 0`. |

The concurrency outcome is deliberately two-part: **one winning top-level resolver dispatch** and **exactly one distinct daily-meter visitor**. A raw `ResolutionLog` count is never the global race oracle because one normal no-match can legitimately log multiple provider responses. A fixture may enable one provider to make a local row count deterministic, but that is test setup, not a production invariant.

### S5-5 — Checklist, evidence, and validation handoff

S7 supersedes these former `test_four_lane_*` names with its two explicit human-race names and separate
agent-domain tests. Phase-01 owns model/import/migration/cascade proof; Phase-04 owns four human-lane
edits, agent-domain defer/claim ordering, temporal provenance, deterministic promotion barrier, and
their gates. S4 outage-cap behavior remains unchanged. Fresh VALIDATE V1 must reject this plan unless
it traces every provider-capable caller to its correct boundary, proves promotion's
deterministic-only condition, proves `create_all()` registration/cascade, verifies the manual
immediate-outage response, proves the source census, and confirms race assertions use
distinct-meter accounting rather than a false one-log invariant.

---

## PVL Supplement 6 — historical five-lane census (superseded by S7) (11-08-26)

**Status:** `Gate: BLOCKED` pending a fresh VALIDATE V1 pass. **S7 supersedes S6's impossible
five-lane same-key claim/race model, its race names, and its census classifications.** S6 is retained
only as history for the valid Celery, promotion, mapped-table, manual-defer, and source-search work.

### S6-1 — Historical false five-lane lease boundary (superseded by S7-1)

The shared `reidentify_resolution_claims` lease has **five** provider-capable shared-claim lanes:

1. manual `POST /visitors/{site_id}/{visitor_id}/resolve`;
2. APScheduler `resolution_runner.run_resolution_for_site`;
3. registered Celery `resolution_tasks._process_site`;
4. registered APScheduler agent-company `agent_company_resolution.run_company_resolution_sweep`; and
5. new `reidentify_sweep_runner.run_reidentify_sweep_once`.

The agent-company lane is not excluded because its stable synthetic visitor reaches the same paid
waterfall. Preserve its AgentVisit selection and `_get_or_create_synthetic_visitor` candidate work.
Immediately before `resolver.resolve(visitor, source_agent_visit_id=...)`, acquire a claim for that
synthetic visitor's `(site_id, visitor_id)`; release the exact owner token in `finally` around
resolver plus company-upsert work. Busy means `claim_busy += 1` and continue only: no resolver or
provider call, no `_upsert_company`, no AgentVisit company link, and no billing/enrichment/defer/retry
mutation. `jobs/scheduler.py::_agent_verification_sweep_job` is trigger-only and takes no second
claim.

### S6-2 — Historical manual-defer policy (agent portion superseded by S7-2)

Manual Retry is deliberately immediate during an active defer. After current ownership, privacy,
candidate, and monthly-plan checks, it claims then invokes the existing
`IdentityResolver.resolve(visitor, force_retry=True)` path; it does **not** apply
`resolution_not_deferred_filter()`. If providers are unavailable, retain the resolver-owned defer
watermark and use existing endpoint `_resolution_skip_reason(...)` to return HTTP 200
`{status: "anonymous", skip_reason: "provider_outage"}`. Do not add a new manual result-return API.
Automatic selection lanes honor `resolution_not_deferred_filter()`; this split remains visible in the
endpoint test.

### S6-3 — Historical source-census classifications (superseded by S7-4)

Before EXECUTE and again before fresh VALIDATE V1, run and compare these source searches to AD-15:

1. `rg -n --glob '*.py' 'from apps\\.api\\.services\\.identity_resolver import IdentityResolver|IdentityResolver\\(' apps/api tests`
2. `rg -n --glob '*.py' -P 'await\\s+(?:IdentityResolver\\([^\\n]+\\)|[A-Za-z_][A-Za-z0-9_]*)\\.resolve\\(' apps/api tests`
3. `rg -n --glob '*.py' 'resolver\\._call_(leadpipe|capturify|rb2b|pdl_ip|ipinfo|hunter|apollo)' apps/api`
4. `rg -n --glob '*.py' 'run_resolution_for_site\\(|run_company_resolution_sweep\\(|_process_site\\(' apps/api/jobs apps/api/routers apps/api/services apps/api/tasks`

Classify every runtime source hit: shared claim (the five S6-1 entries), deterministic-only
(`promotion_sweep_runner.py`), or out of scope with its checked reason (public demo's stateless
private-helper wrapper, Leadpipe webhook's post-provider `_save_identified`, or trigger-only
delegate). A new direct `resolve()` caller or private provider wrapper is a VALIDATE failure until
this census, claim policy, and race coverage are updated. Test-only callers are coverage
infrastructure, not production lanes, but remain visible in command 2.

### S6-4 — Historical proof ownership and retired test names (superseded by S7-4)

`tests/integration/test_reidentify_resolution_leases.py` owns exactly these Hybrid races:

| Test | Required setup and proof |
|---|---|
| `test_five_lane_lease_race_identified_once` | Barrier-race manual API, `run_resolution_for_site`, Celery `_process_site`, `run_company_resolution_sweep`, and `run_reidentify_sweep_once` immediately before claim. Use one identifying provider. Prove one claim winner, one provider-capable dispatch, one `IdentifiedVisitor`, only winner-owned success effects, and release on all completion paths. |
| `test_five_lane_lease_race_no_match_one_distinct_daily_meter_visitor` | Same five competitors and one answering no-match provider. Prove one top-level dispatch and `get_resolution_attempts_today(...) == 1`; never assert a false global raw-`ResolutionLog` count. |
| `test_claim_model_registered_by_create_all_and_cascades` | Retained from S5: model registration and cascade proof only. |

`tests/integration/test_visitor_resolve_endpoint.py::test_manual_retry_runs_during_active_defer_and_reports_provider_outage`
is the endpoint-local policy proof: a future defer never prevents claimed manual dispatch; forced
provider unavailability returns existing `anonymous/provider_outage` with no log/distinct-meter
increment and retained/capped watermark. The T33 static guard is the automated completeness proof;
it fails if the five-lane manifest, promotion barrier, or out-of-scope reasons drift.

### S6-5 — Historical validation handoff (replaced by S7-5)

Fresh VALIDATE V1 must use S7-5, not this historical five-lane description. `Gate: BLOCKED` remains
unchanged until that pass succeeds; EXECUTE is not authorised.

---

## PVL Supplement 7 — claim-domain correction and historical-IP temporal provenance (11-08-26)

**Status:** `Gate: BLOCKED` pending a fresh VALIDATE V1 pass. This is authoritative where S6 modelled
agent-company as a human same-key competitor, omitted automatic defer after synthetic materialization,
or used global visitor activity for a selected historical IP. Earlier valid S3–S6 material remains in
force unless S7 explicitly replaces it.

### S7-1 — Two correct claim-safety domains (replaces S6-1 and S6-4)

`agent_company_resolution._get_or_create_synthetic_visitor()` assigns one synthetic key per AgentVisit
(`visitor_id = "agent:{AgentVisit.id}"`) and `is_agent_derived=True`. Manual, `resolution_runner`,
Celery, and the new reidentify sweep select with `human_only_visitor_filter()`. They can never same-key
contend with agent-company. Do not write, run, or accept a five-lane same-key race.

The shared TTL helper proves two domains:

1. **Human domain:** manual, APScheduler `run_resolution_for_site`, registered Celery `_process_site`,
   and `run_reidentify_sweep_once` race the same human key. The identified gate proves one top-level
   winner, one `IdentifiedVisitor`, winner-only success effects, and exact release. The no-match gate
   proves one winner and exactly one distinct-meter visitor; it never asserts a global `ResolutionLog`
   row count.
2. **Agent domain:** only concurrent agent-company work for the same synthetic key can contend. The
   held-claim/reentrancy gate proves exactly one agent winner. Busy increments only non-PII
   `claim_busy`; it performs no `resolve`, provider call, `_upsert_company`, AgentVisit company link,
   billing/enrichment/defer/retry mutation, or downstream side effect. A token-matched `finally`
   release occurs once on owned success, no-match, unavailable, and exception paths; busy non-owners
   never release another worker's claim.

This preserves AC-2 separation: human selectors never include `is_agent_derived=True`, and a
human-domain race fixture never uses a synthetic visitor to fake a cross-domain collision.

### S7-2 — Agent-company automatic defer placement (replaces S6-2 only for agent-company)

After `_get_or_create_synthetic_visitor()` returns but before `try_claim_resolution`, evaluate the
synthetic visitor using automatic defer semantics: eligible only when
`resolution_deferred_until IS NULL OR resolution_deferred_until <= now`, with the repo's naïve-UTC
rule. Manual Retry remains deliberately exempt.

Agent-company starts from `AgentVisit`, so this is the in-memory equivalent of
`resolution_not_deferred_filter()`, not an extra AgentVisit query predicate. Use a named local
predicate/helper whose condition exactly mirrors the SQL filter. A future defer increments only
`deferred` and continues before claim/provider/company/link work. An eligible agent winner that hits
all-provider outage preserves/advances the resolver-owned bounded watermark and adds no claim-owner
retry accounting; it becomes eligible again only when due. The Hybrid proof covers capped repeat.

### S7-3 — Selected-IP temporal provenance contract (new)

`IpEvidence.last_activity_at` comes only from `MAX(Event.created_at)` for the chosen unflagged
`(site_id, visitor_id, ip_address)` group. The pure ranker returns selected evidence (or its IP plus
timestamp), not only an IP string. The new sweep passes that exact value to `resolve_auto_retry`.

| Surface | Exact contract | Compatibility rule |
|---|---|---|
| `IdentityResolver.resolve` | defaulted `selected_ip_activity_at: datetime \| None = None` beside `override_ip` | ordinary callers omit it and preserve results/global activity |
| `resolve_auto_retry` | takes chosen `override_ip` and `selected_ip_activity_at` | only the retry sweep supplies selected event provenance |
| Leadpipe/Capturify | defaulted effective IP for equality plus defaulted selected activity for matching | only graph feeds use recency; other mixins gain no unused time parameter |
| `MatchingMixin._record_matches_visitor` | keyword-only `activity_at: datetime \| None = None`; normalize it as current visitor activity when non-null, else call `_visitor_activity_utc(visitor)` | direct and ordinary provider callers retain existing recency |

Leadpipe/Capturify compare record IP to the effective override IP and record time to the selected IP's
event time. Never mutate `Visitor.last_seen` (which can be current activity on different IP Y),
`Visitor.ip_address`, or the event. The 30-minute window, timestamp-required rule, tally, and
default-OFF/provider behavior are unchanged.

### S7-4 — Canonical proving scenarios and source census (replaces S6-3/S6-4 names)

| Owner | Exact scenario | Strategy | Proves SPEC criterion |
|---|---|---|---|
| `tests/integration/test_reidentify_resolution_leases.py` | `test_four_human_lane_lease_race_identified_once` | Hybrid | AC-4 / AC-7 — single-winner same-key human dispatch |
| same | `test_four_human_lane_lease_race_no_match_one_distinct_daily_meter_visitor` | Hybrid | AC-4 / AC-7 — no duplicate distinct-meter accounting |
| `tests/unit/test_agent_company_resolution.py` | `test_agent_company_held_claim_is_side_effect_free_and_releases_exact_token` | Fully-Automated | AC-8 / AC-7 — agent reentrancy, busy no-side-effect, exact release |
| `tests/integration/test_agent_company_resolution.py` | `test_agent_company_honors_defer_before_claim_with_outage_capped_repeat` | Hybrid | AC-8 / AC-7 — synthetic defer eligibility and capped outage repeat |
| `tests/unit/test_identity_enrich_correctness.py` | `test_selected_ip_activity_precedes_global_last_seen`; `test_no_selected_activity_keeps_global_last_seen` | Fully-Automated | AC-1 / AC-3 — context precedence and default fallback |
| `tests/integration/test_reidentify_sweep.py` | `test_historical_selected_ip_rejects_current_graph_record_outside_event_window`; `test_historical_selected_ip_allows_graph_record_inside_event_window` | Hybrid | AC-1 / AC-3 / AC-7 — X/Y/B provenance and no `last_seen` mutation |
| `tests/unit/test_resolution_deferral_watermark.py` | `TestProviderCapableResolverCallerCensus::test_provider_capable_resolver_census_is_exhaustive` | Fully-Automated | AC-4 / AC-7 — four-human, agent-domain, deterministic-only, out-of-scope census |

Before EXECUTE and fresh V1, re-run S6-3's four `rg` commands but classify runtime hits against the
S7 manifest: four human claim lanes; agent-domain claimant; deterministic-only promotion; public-demo
private wrapper; inbound Leadpipe webhook persistence; and trigger-only delegates. A new direct
`resolve()` or private provider wrapper is a VALIDATE failure until classified and proven. The census
also checks selected-IP time appears only in ranker result, sweep dispatch, resolver,
Leadpipe/Capturify call, and `MatchingMixin` path.

### S7-5 — Execution and fresh V1 handoff

Phase-04 order: (1) ranker event timestamp and unit tests; (2) default-compatible resolver/matching
threading; (3) temporal PostgreSQL gates; (4) four-human lease paths/races; (5) agent materialize →
defer → claim → resolver/upsert ordering and held-claim/outage tests; (6) static census. This prevents
a five-lane fixture or a global-last-seen workaround from becoming the implementation shape.

Fresh VALIDATE V1 must re-derive anchors and full census; reject same-key tests mixing human and
agent keys; confirm agent defer is after materialization but before claim; prove busy agent paths have
no resolver/company/link/downstream side effect and exact-token release; run four-human identified and
no-match races; and run the PostgreSQL X/Y/B provenance pair. `Gate: BLOCKED` remains unchanged until
V1 adjudicates these gates. EXECUTE is not authorised.

---

## PVL Supplement 8 — agent-company monthly plan parity and success metering (11-08-26)

**Status:** `Gate: BLOCKED` pending a fresh VALIDATE V1 pass. S8 preserves every valid S7 claim-domain,
defer, exact-token-release, and temporal-provenance rule. It adds the missing paid-provider monthly-plan
boundary for the agent-company automatic lane; it does not turn that lane into a fifth human-race
competitor and does not alter plan pricing or provider selection.

### S8-1 — Re-derived source anchors and exact sequence

The current source has the required canonical primitives but agent-company does not call them:

| Anchor | Verified current behavior | S8 required behavior |
|---|---|---|
| `apps/api/services/agent_company_resolution.py:89-164` | Materializes a synthetic visitor and directly calls `IdentityResolver.resolve(...)` at `:130-132`; it has neither `check_usage_allowed` nor `increment_usage`. The downstream `_upsert_company`/link region starts at `:136`. | Keep selection/materialization. After synthetic automatic-defer eligibility and before claim/provider work, load the site owner and call the canonical usage check. When resolver returns non-`None`, meter once before the downstream region. |
| `apps/api/services/resolution_runner.py:158-183` | Checks `check_usage_allowed(db, site.user_id)` at `:161`; a resolver row at `:172-175` is followed by `increment_usage` at `:176-179`, before enrichment. | Agent-company uses the same success predicate and placement: non-`None` resolver result ⇒ one increment before company/link downstream work. |
| `apps/api/tasks/resolution_tasks.py:117-137` | Its automatic path checks monthly allowance at `:118-128`, resolves at `:130`, and increments only after a successful result at `:131-135`. | This is the second behavioral donor; do not create a third usage model for agents. |
| `apps/api/services/billing.py:95-148` | `check_usage_allowed` applies current entitlement, referral bonus, lazy monthly reset, and current count; `increment_usage` is the canonical success-side increment. | Call both services unchanged. Do not duplicate plan limits, calculate price, or write `monthly_identified_count` directly. |

The per-AgentVisit order is mandatory:

1. select eligible `AgentVisit` and materialize/reuse its one `agent:{AgentVisit.id}` synthetic visitor;
2. apply S7 automatic defer eligibility; a future watermark increments only `deferred` and exits;
3. load `Site` from `agent_visit.site_id`; missing site or `site.user_id` is a fail-closed
   `billing_unavailable` skip with only safe observability;
4. call `check_usage_allowed(db, site.user_id)`; false is `skipped_plan_limit` and exits **before**
   claim, resolver/provider, company upsert, AgentVisit link, enrichment, or usage increment;
5. claim the synthetic key; busy increments only `claim_busy` and exits without billing or downstream
   work;
6. for the token owner, call `resolver.resolve(visitor, source_agent_visit_id=...)`;
7. whenever that call returns a non-`None` result, call `increment_usage(db, site.user_id)` exactly
   once **before** `_upsert_company` and `AgentVisit.resolved_company_id` linking. A resolver
   exception before that result increments zero; a later downstream upsert/link exception retains the
   one increment and retry must not duplicate it; and
8. release only the token owner in `finally` for every result and exception path.

The metered outcome is intentionally the existing automatic-path outcome — a non-`None`
`IdentifiedVisitor` result — rather than a company upsert/link, a provider-specific response, a
`ResolutionLog` row, or a computed price. Thus no-match, provider-unavailable, privacy/suppression/
daily-budget pre-provider skip, future defer, monthly-plan block, missing ownership, and busy claim
each meter **zero**. A **pre-success resolver exception** also meters zero. Conversely, once resolver
returns non-`None`, the canonical sequence immediately records **one** increment before company/link
work, so a **post-success downstream exception** retains that one increment; exact-token release and
retry handling must prevent a duplicate increment. This matches the canonical automatic paths'
success-side accounting rather than inventing a second definition of billable resolution.

### S8-2 — Concurrency, retry, and observability boundary

The S7 synthetic-key claim serializes concurrent work for the **same AgentVisit**. Therefore exactly
one owner can dispatch providers and invoke `increment_usage`; a losing/busy worker neither meters nor
releases the winner's token. The Hybrid same-synthetic-key race is the required proof. Do not assert a
global `ResolutionLog` count: normal provider fan-out makes that non-deterministic.

`check_usage_allowed` plus `increment_usage` are the existing canonical check-then-increment service,
not an atomic per-user quota reservation. S8 intentionally preserves that service contract for parity
with `resolution_runner` and `resolution_tasks`. It proves exact-once metering per claimed synthetic
resolution; it does **not** claim that independently claimed AgentVisits racing under the same user
can reserve the final remaining monthly slot atomically. If strict cross-visitor reservation is required,
that is a billing-service change outside this plan's locked blast radius and must return to SPEC/PLAN;
VALIDATE must not silently promote it to an unproven PASS criterion.

Safe observability is limited to aggregate `processed`, `resolved`, `companies`, `deferred`,
`claim_busy`, `skipped_plan_limit`, and `billing_unavailable` counters plus `site_id` and AgentVisit
id when a row-level event is necessary. Never log IP address, email, domain, provider payload, owner
id, claim token, or monthly count.

### S8-3 — Canonical proof, census, and fresh-V1 handoff (replaces only S7-4/S7-5 agent quota wording)

| Owner | Exact scenario | Strategy | Proves SPEC criterion |
|---|---|---|---|
| `tests/unit/test_agent_company_resolution.py` | `test_agent_company_plan_limit_skips_provider_claim_and_downstream` | Fully-Automated | AC-8a — blocked monthly quota reaches no provider, claim, upsert/link, or usage increment; only safe observability remains |
| same | `test_agent_company_success_increments_usage_once_before_downstream` | Fully-Automated | AC-8a — every non-`None` resolver result invokes `increment_usage` exactly once before company/link work |
| same | `test_agent_company_resolver_exception_does_not_meter_and_releases_exact_token` | Fully-Automated | AC-8a / AC-7 — pre-success resolver exception invokes `increment_usage` zero times and releases exactly the owner token |
| same | `test_agent_company_downstream_exception_meters_once_releases_exact_token_and_retry_does_not_duplicate` | Fully-Automated | AC-8a / AC-7 — post-success upsert/link exception retains one prior increment, exactly releases the owner token, and retry cannot increment again |
| `tests/integration/test_agent_company_resolution.py` | `test_agent_company_same_synthetic_claim_race_meters_once` | Hybrid | AC-8a / AC-7 — concurrent same-key agent work has one provider-capable winner, one canonical increment, zero loser side effects |
| `tests/unit/test_resolution_deferral_watermark.py` | `TestProviderCapableResolverCallerCensus::test_provider_capable_resolver_census_is_exhaustive` | Fully-Automated | AC-4 / AC-7 / AC-8a — agent claimant manifest requires defer → billing check → claim → resolver → immediate non-`None` success-only increment before downstream → exact-token finally markers |

Before EXECUTE and again for fresh V1, re-run S7's four resolver/provider searches **plus**:

1. `rg -n --glob '*.py' 'check_usage_allowed\\(|increment_usage\\(' apps/api/services apps/api/tasks apps/api/routers`
2. `rg -n --glob '*.py' 'run_company_resolution_sweep|IdentityResolver\\.resolve|resolver\\.resolve|try_claim_resolution|release_resolution_claim' apps/api/services/agent_company_resolution.py apps/api/jobs/scheduler.py`

The static census must classify the agent-company hit as `agent-domain claimant + monthly-plan parity`;
it fails if the source lacks canonical billing imports/calls, places the check after claim/resolve,
places the increment anywhere other than immediately after a non-`None` resolver result and before
upsert/link downstream work, meters a non-owner, or permits blocked rows to reach any provider or
downstream side effect. It must also retain S7's separate human-domain and deterministic-only
classifications. New direct resolver callers or private provider wrappers remain V1 failures until
classified.

Fresh V1 must re-derive the listed anchors; confirm this exact order; run the plan-limit and success
unit gates plus the two split exception gates: (1) a pre-success resolver exception has zero increment
and exact-token release; (2) a post-success downstream upsert/link exception has exactly one increment,
exact-token release, and no duplicate increment on retry. Also run the same-synthetic-key Hybrid race,
verify no PII-bearing field is captured by logs, and record the canonical cross-AgentVisit
check-then-increment limitation as an inherited billing boundary, not a pass-by-omission. `Gate:
BLOCKED` remains unchanged until V1 adjudicates S7 plus S8. EXECUTE is not authorised.

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
- Keep the resolver footprint to three defaulted parameters (`auto_retry`, `override_ip`, `selected_ip_activity_at`), five defaulted override-IP mixin params, and two matching-only activity params; keep `visitor_aggregator.py` to one flag guard. Anything beyond that is out of scope.
- S7 keeps the mapped claim model + `main.py` registration, lease helper, manual/APScheduler/Celery/new-sweep human lane closure, promotion's deterministic-only barrier, and static census. S8 extends the separately materialize → defer → canonical monthly check → synthetic-key claim → resolver → immediate non-`None` success-only canonical increment → company/upsert agent path. Its V1 proof splits a pre-success resolver exception (zero increment + exact-token release) from a post-success downstream exception (one increment + exact-token release + no duplicate retry meter); it remains never a fifth human-race competitor. Selected-IP activity must reach only Leadpipe/Capturify matching and must never be simulated by mutating visitor state.
Next phase: PVL SUPPLEMENT S9 — vc-plan-agent (supplement mode), then a fresh vc-validate-agent V1 pass. Cycle 7 (13-08-26) re-adjudicated S7 and S8 against live source on `main` and CLOSED cycle-6's last S8 gap: synthetic-key domain, agent-company billing absence, S8 donor anchors, four-human census exhaustiveness, manual-during-defer provider_outage reachability, tracking_enabled gate, defer-filter exclusivity, and the composite-FK ON DELETE CASCADE (empirically probed on a disposable postgres:16-alpine) all CONFIRMED. Cycle 7 raised one NEW root-cause FAIL, F-S4X: PVL Supplement 4's resolver outage change (S4-2 / S4-4 item 1) was never propagated into the plan body — it is absent from the Phase-03 checklist and T13, undisclosed in Public Contracts, unflagged, and it falsifies AC-1 and the Rollback 'no code revert needed' row. S9 must close all five surfaces in one coherent edit. The BLOCKED verdict stands; EXECUTE is not authorised.
Validate contract: inline in plan (process/features/visitors-identity/active/ip-best-selection-retrigger_09-08-26/ip-best-selection-retrigger_PLAN_09-08-26.md § Validate Contract)
Execute start: BLOCKED — not authorised. After the supplement cycle re-validates to PASS, start is: .venv/bin/python -m pytest tests/unit -m unit -q | integration spec: tests/integration/test_reidentify_sweep.py | probe scenario: browser check of "tried N/4" on list + detail | high-risk pack: yes (schema migration + identity status + paid-provider spend)
```

---

## Next Step

Plan complete. Review carefully. Say **"ENTER VALIDATE MODE"** when ready to proceed to plan
validation (required before EXECUTE). Do not say "ENTER EXECUTE MODE" until the validate-contract
exists — this plan touches schema, identity status, and paid-provider spend.

---

## Superseded (Phase-1 scope) — 13-08-26

**The Phase-1 scope of this plan is SUPERSEDED by:**
`process/features/visitors-identity/active/ip-best-selection-phase1_13-08-26/ip-best-selection-phase1_PLAN_13-08-26.md`

Reason: PVL cycle 7 closed at `Gate: BLOCKED` with 16 gaps (2 P0, 4 claim-vs-claim contradictions)
after seven cycles and eight supplements. The measured failure mode was structural, not
gap-by-gap — supplement decisions never propagated into the plan body, and supplements contradicted
each other, so an execute-agent produced a different implementation depending on which section it
read. Rather than write an S9 into a 244KB artifact, the user descoped Phase 1 into a small plan
where every decision lives in the body and there are no supplements.

The successor carries forward, as a closed `## Decision Record (inherited, closed)`, every decision
from cycles 1–7 (AD-1…AD-15, S3–S8), and resolves the four contradictions with a single normative
winner each (`## Contradiction Resolutions`: AD-7↔S3-1, AD-15↔S3-2, AC-1↔S4-2). It additionally
fixes the two cycle-7 P0s (no monthly-plan gate / no metering in the new sweep; `override_ip` never
reaching the three residential-capable mixins via `_resolve_identity_graphs_parallel`), the
cross-tenant Redis negative cache, and the partial-outage write-off.

**What remains live in THIS file:** nothing executable. Do not start EXECUTE from this plan, and do
not write an S9 supplement into it. Its Phase-2 surfaces stay backlogged at
`process/features/visitors-identity/backlog/ip-best-selection-phase2-deferred_NOTE_13-08-26.md`
(`vpn_filtered` Retry revival, relay/VPN accounting contract, `skip_count` reset semantics,
manual-retry leftover-`anonymous`, `provider_unavailable` budget-stamp accounting, the web UI
surface, and the full-repo negative-cache re-key).

This file is retained as read-only history: its PVL iteration reports, `results.tsv`, and the
cycle-1…7 findings are the provenance for the successor's Decision Record.
