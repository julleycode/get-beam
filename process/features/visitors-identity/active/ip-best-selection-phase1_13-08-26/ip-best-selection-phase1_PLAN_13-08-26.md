---
name: plan:ip-best-selection-phase1
description: "COMPLEX PLAN — Phase 1 of best-IP re-identify: IP ranker, override_ip through BOTH orchestrators, billing parity, capped cadence, claim table, site-scoped negative cache, per-tier outage verdict"
date: 13-08-26
feature: visitors-identity
metadata:
  node_type: plan
  type: plan
  feature: visitors-identity
  supersedes: plan:ip-best-selection-retrigger (Phase-1 scope only)
---

# Best-IP Selection + Capped Automatic Re-Identify — Phase 1

**Date**: 13-08-26
**Status**: ⏳ PLANNED
**Complexity**: COMPLEX (single execution stream, 8 phases, one plan file — not a phase program)
**Feature**: visitors-identity
**SPEC**: `process/features/visitors-identity/active/ip-best-selection-retrigger_09-08-26/ip-best-selection-retrigger_SPEC_09-08-26.md`
**Supersedes**: the Phase-1 scope of `process/features/visitors-identity/active/ip-best-selection-retrigger_09-08-26/ip-best-selection-retrigger_PLAN_09-08-26.md` (244KB, 8 supplements, PVL cycle 7 `Gate: BLOCKED`, 16 gaps). Its Phase-2 surfaces stay backlogged — see §Deferred to Phase 2.
**Context loaded**: `process/context/all-context.md`, `process/context/tests/all-tests.md`, `process/development-protocols/communication-standards.md`

---

## TL;DR

A visitor browses from several IPs; Beam stores only the newest one and spends its one paid attempt
on whatever was last. Phase 1 (a) ranks the visitor's known IPs and resolves the **best untried**
one, (b) gives every visitor **4 lifetime automatic attempts, one per 7 days**, each on a distinct
IP, and (c) closes four spend/correctness defects the old plan's PVL loop found but never fixed:
the new lane had no monthly-plan gate, `override_ip` never reached the residential-capable
providers, the negative IP cache was cross-tenant, and the resolver wrote a visitor off during a
partial provider outage.

Everything sits behind default-OFF `auto_reidentify_enabled` **except two unconditional bug-fix
slices** (per-tier outage verdict; agent-company monthly-plan parity) — see CR-3 and SN-1.

**Why a new plan:** the predecessor's measured failure mode was supplement decisions never reaching
the plan body plus claim-vs-claim contradictions across eight appendices. Here every decision lives
in the body. There are no supplements.

---

## Overview

### The miss (verified chain, re-derived live on `main` @ `3e2ddb5`)

| Step | Live anchor | What goes wrong |
|---|---|---|
| Rollup overwrites with the NEWEST IP | `apps/api/services/visitor_aggregator.py:315`, incremental `:619` | "latest", never "best" |
| Resolver reads that one IP; `resolve()` takes no IP argument | `apps/api/services/identity_resolver.py:544` | no way to choose |
| 30-day gate is IP-blind | `identity_resolver.py:169`, enforced `:625`; `ResolutionLog` has no IP column | one bad IP writes the person off |
| Failure forks | `:644` (`vpn_filtered`) / `:790-793` (`unresolvable`) | `vpn_filtered` is a fact about an IP stored as a fact about a VISITOR |
| Partial outage writes the visitor off | `:762` ORs across two independent tiers | a dead person-graph tier terminalises a visitor whose IP tier answered |

### What Phase 1 does NOT do

Relay/VPN Retry-button revival, relay accounting contract, `skip_count` reset semantics,
manual-retry leftover-`anonymous`, the "tried N/4" UI, and the site-settings toggle are **out**.
See §Deferred to Phase 2 and `process/features/visitors-identity/backlog/ip-best-selection-phase2-deferred_NOTE_13-08-26.md`.

### Locked policy (user decisions — never re-litigated in EXECUTE or PVL)

| Policy | Value |
|---|---|
| Automatic attempts | **4 per visitor, LIFETIME.** First identify counts as attempt #1. |
| Cadence | one attempt per **7 days**, automatic |
| Per attempt | ONE best untried IP, ONE resolve call |
| Cycle with no untried IP | **SKIPPED — consumes no attempt** (`next_at` and `skip_count` still advance) |
| After 4 | permanently done; columns only, no new `identity_status` value |
| Coverage | **every site**; NOT gated on `auto_identify_enabled` |
| Manual Retry | exempt from the cap; never resets the counter |
| Budget | the **existing** 50/site/day identify budget; no separate Redis allowance |

---

## Goals / Non-Goals

**Goals**

1. Resolve the visitor's most resolvable known IP, not the newest one.
2. Automatically re-open a failed visitor when a genuinely new untried IP appears — bounded to 4
   lifetime attempts at 7-day cadence, on every site.
3. The new lane observes the same monthly-plan gate and the same success meter as every other
   provider-capable lane (P0-1).
4. The chosen IP actually reaches **all five** IP-reading providers, including the three
   residential-capable ones (P0-2).
5. Bounded, non-self-annihilating spend: no unbounded outage re-dispatch, no cross-tenant cache
   suppression, no write-off during partial outage.

**Non-Goals**

- Provider selection / order / pricing changes.
- Re-running the **paid** waterfall on non-IP evidence (fingerprint, cross-tenant graph, email
  capture) as if it were new evidence. See CR-1 for the exact rule.
- `ip_org_lookup_enabled` / fused-confidence dependency — operator runbook, not this plan.
- Changing the `auto_identify_enabled` default or auto-enrolling sites.
- Per-IP identity-status re-model.
- IP encryption / blind-indexing at rest (owned by the held pii-at-rest plan).
- Everything in §Deferred to Phase 2.

---

## Decision Record (inherited, closed)

Every row below is a **closed** decision carried forward from PVL cycles 1–7 of the predecessor
plan. PVL must not re-litigate these; it may only find that the plan body contradicts one.

| ID | Decision | One-line rationale | Source |
|---|---|---|---|
| DR-1 | State lives in **4 additive columns on `Visitor`**, no index/constraint/backfill | inherits the visitor row's GDPR erasure + retention for free; follows `c2f7a9d31b64:19-25` | AD-1 |
| DR-2 | `tried_ips` is **JSONB on the visitor row**, not a new table | ≤4 entries by cap; erasure is already `DELETE FROM visitors` (`routers/visitors.py:448-474`) | AD-1 |
| DR-3 | REJECTED: an `ip_address` column on `ResolutionLog` | revive DELETEs failed rows; logs are billing-immutable; outage attempts write no row | AD-1 |
| DR-4 | Ranker is a **pure module**, clock injected via `now=None`; no DB/network at module scope | no freezegun in repo; mirrors `ip_org_fusion.fuse_org_hypothesis` | AD-2 |
| DR-5 | Evidence = ONE `GROUP BY ip_address` over events, index-supported by `ix_events_site_visitor`; `NOT is_flagged_abuse` | no index on `ip_address` alone — never write a cross-visitor IP-keyed query | AD-2 |
| DR-6 | Engagement aggregates are `MAX(scroll_depth)` + `AVG(time_on_page) FILTER (>0)` | those fields are non-zero only on their own event rows (`routers/events.py:390-391`) | AD-2 |
| DR-7 | **MANDATORY** `lookup_asn` returns `asn is None` → tier `"unknown"`, `classify_ip_org_kind` never called | `classify_ip_org_kind(None, None)` returns `"org"`, collapsing the ladder to a constant | AD-2 / G8 |
| DR-8 | Ladder `org → unknown → eyeball → cdn → datacenter`; `unknown` ranks **second** | no mmdb in repo/CI ⇒ every IP is genuinely `unknown`; ranking it last would be worse than "newest wins" | AD-3 |
| DR-9 | SPEC's five-value `org_kind` (incl. `registry`) is **STALE** — four values only | `registry` is written only by `ip_org_rir_ingest.py:162`, not on this path | AD-3 / G13 |
| DR-10 | Nothing is filtered by tier — it is a **priority queue** | with 4 attempts `eyeball` still gets its turn; rb2b/leadpipe/capturify do resolve residential IPs | AD-3 |
| DR-11 | Hard exclusions: already-tried, `is_privacy_relay_ip`, malformed/private/reserved/loopback, all-events-flagged | AD-4 | AD-4 |
| DR-12 | 8-key tiebreak chain, total order; business-hours ratio **abstains** (dropped from numerator AND denominator) on NULL `country_code` | `country_code` is denormalised at ingest — never call `resolve_geoip` in a ranker | AD-5 |
| DR-13 | Ordering is **recomputed every cycle**, not frozen; `tried_ips` is monotonic | evidence changes as events arrive/age; guarantee is "≤4 attempts, each on a distinct IP" — NOT "the 4 best IPs are tried" | AD-5 / G5 |
| DR-14 | Sweep is shaped on `promotion_sweep_runner.py` (advisory lock **fail-open**, `run_X_once(db)` + `run_X()`, per-row try/except/continue) but enumerates sites like `resolution_runner.py` | the donor issues one GLOBAL query — copying it makes the per-site budget reserve and site gates unimplementable | AD-6 |
| DR-15 | Two-pool selection: 10 NULL `next_at` + 10 due + deterministic spillover to 20; no within-tick refill after a busy claim | a large NULL backlog cannot crowd out already-due rows; no row appears twice | AD-6 (S3-3) |
| DR-16 | Resolver deferral is **retained, never restored**; no `resolution_defer_count = 0` term; the resolver is the sole writer of its defer fields | inferring outage from a before/after counter turns sustained failure into a hot loop | AD-8 (S3-1) |
| DR-17 | All new gates are **columns in the WHERE clause** | sweep starvation is a proven, already-reverted trap (`resolution_eligibility.py:85-99` docstring) | AD-6 |
| DR-18 | Mandatory PRE-CHECKS (`check_daily_budget`, `do_not_resolve`, suppression) BEFORE `resolve()`; an attempt is consumed only when the IP was actually sent to a provider | otherwise a budget-exhausted site blacklists all 4 IPs with zero provider calls — self-annihilation on exactly the busy sites this targets | AD-6 / G2b |
| DR-19 | Per-site budget **reserve at 70%**, re-evaluated **per visitor** immediately before each `resolve()`; threshold `ceil(0.70 × budget)` = **35** at the default 50 | a once-per-tick check leaks to ~80% within two ticks | AD-6 / C13 / ND-3a |
| DR-20 | A budget refusal **stamps NOTHING** — no `skip_count`, no `next_at`, no `tried_ips`, no attempt | mapping it onto the skip row retires a busy site's whole candidate set in 8 weeks with zero IPs evaluated | AD-6 / ND-3b |
| DR-21 | `skip_count < 8` retirement bound, incremented ONLY on futile-IP evaluations | a single-IP visitor would otherwise be re-evaluated forever at a `GROUP BY` + N `lookup_asn` cost each time | AD-6 / G5 |
| DR-22 | `Site.tracking_enabled IS true` is a REQUIRED, independent site gate | commit `b2a7eef`: a paused site must not burn provider credits draining its backlog (`resolution_runner.py:260`) | AD-6 / F6 |
| DR-23 | No `auto_identify_enabled` gate; per-site `auto_reidentify_opt_out` column, **default false** | every-site coverage stays the default; the column is a consent escape hatch, not an opt-in gate | AD-14 / D-D / G9 |
| DR-24 | `override_ip` is a **PARAMETER**; `visitor.ip_address` is NEVER assigned | `IdentityResolver` shares the sweep's `AsyncSession`, so the "in-memory override" was a committed write corrupting a plaintext PII column | AD-8 / D-A / G1 |
| DR-25 | Terminal marker is **columns only** — no new `identity_status` value | five readers fail open in the wrong direction, incl. the detail page enabling OSINT (`[visitorId]/page.tsx:466-469`) | AD-10 |
| DR-26 | `revive_returning_unresolvable` becomes a **no-op early-return when the flag is on** | exactly one owner; its failed-log DELETE (`visitor_aggregator.py:417-423`) stops firing, which is what lets `tried_ips` mean anything | AD-9 |
| DR-27 | Scheduler job registered inside `if settings.auto_reidentify_enabled:`, boot offset **smaller than `aggregation_sweep`'s 90s** | matches `test_scheduler_job_config.py:80-100` | AD-12 |
| DR-28 | Migration is additive, no backfill, chained off a **live-derived** head with `DATABASE_URL` pinned to `localhost:5433` | repo `.env` points at Supabase PROD and `migrations/env.py` has no local-host guard | AD-13 |
| DR-29 | Claim table is a **mapped `Base` model** with inherited UUID PK, `UNIQUE(site_id, visitor_id)`, opaque `owner_token`, `expires_at`, and a composite FK to `visitors(site_id, visitor_id) ON DELETE CASCADE`; imported in `apps/api/main.py` | `tests/conftest.py` imports `apps.api.main` immediately before `Base.metadata.create_all()`; a lazily-imported model is absent from Hybrid fixtures | AD-15 / S5-2 |
| DR-30 | Composite FK → plain UNIQUE INDEX + `ON DELETE CASCADE` is **empirically proven viable** | cycle 7 probe on disposable `postgres:16-alpine`: FK created, parent delete cascaded 1→0, duplicate claim rejected. Do NOT re-derive. | cycle-7 verifier |
| DR-31 | **Four human same-key lanes** share the claim: manual retry, APScheduler `resolution_runner`, registered Celery `resolution_tasks`, new reidentify sweep | agent-company uses synthetic `agent:{AgentVisit.id}` + `is_agent_derived=True` and cannot same-key contend (`agent_company_resolution.py:69`) | AD-15 / S7-1 |
| DR-32 | `promotion_sweep_runner` must call `resolve(..., deterministic_only=True)` and takes no lease | it is currently provider-capable; the barrier keeps it out of the paid race | AD-15 / S7-1 |
| DR-33 | `demo.py::demo_identify` and `leadpipe_webhook.py::_save_identified` are **out of scope** for the lease | demo uses a `SimpleNamespace` and the demo budget; the webhook is post-request persistence, not a dispatcher | AD-15 |
| DR-34 | Selected-IP **event-time provenance**: ranker carries `MAX(Event.created_at)` per IP → sweep → `selected_ip_activity_at` → Leadpipe/Capturify `MatchingMixin` only. **Never mutate `Visitor.last_seen`.** | a historical override must not be matched against the visitor's current global recency | AD-15 / S7-3 |
| DR-35 | Agent-company gets canonical monthly-plan parity: `check_usage_allowed` fail-closed before claim/provider work; `increment_usage` exactly once on a non-`None` result **before** `_upsert_company`/link work | census run live: zero `check_usage_allowed`/`increment_usage` hits in that file; donor anchors exact at `resolution_runner.py:161→172→178` | S8-1 |
| DR-36 | Cross-`AgentVisit` atomic reservation stays the inherited `billing.py:94/140` boundary — explicitly **not claimed** by this plan | disclaimed deliberately, not overclaimed | S8-2 |
| DR-37 | `force_retry` bypasses **exactly one** line (`identity_resolver.py:625`); six other gates sit on separate statements (`:590 :600 :631 :635 :644 :653`) | verified live; `auto_retry` is a separate flag so the two lanes stay independently auditable | AD-7 / cycle-7 |
| DR-38 | Live alembic head on `main` is **`f4b9d2a71c68`** as of 13-08-26 — recorded as a fact, **still re-derive at EXECUTE** | the predecessor's AD-13 named two wrong values; heads move as concurrent programs land migrations | cycle-7 V10 |
| DR-39 | Redis negative-cache prefix is `resolution:` (`identity_providers/base.py:16`) — there is **no** `beam:` client-side prefix | the predecessor wrote `beam:resolution:{ip}` twice | cycle-7 V10 |
| DR-40 | No gate in this plan is environment-blocked: Docker + PG 5433 + Redis 6379 are live; detect Docker by port, not `which docker` | cycle-7 measured baselines: unit **1762 passed / 2 skipped**, scoped Hybrid **11 passed** | cycle-7 |

---

## Contradiction Resolutions

Each contradiction below is resolved by exactly ONE normative rule stated here in the body. The
losing statement is marked SUPERSEDED and must not be implemented.

### CR-1 — `auto_retry` bypass scope (AD-7 ↔ S3-1)

- AD-7: bypasses "exactly the same line as `force_retry` and nothing else."
- S3-1: "skips `_check_prior_signals` completely."

**WINNER: AD-7. S3-1's `_check_prior_signals` clause is SUPERSEDED and must not be implemented.**

**Normative rule.** `auto_retry: bool = False` on `IdentityResolver.resolve()` bypasses
**exactly one statement** — the `was_recently_attempted` gate at `identity_resolver.py:625` — and
nothing else. `_check_prior_signals` (`:608`) still runs on every automatic retry. It does NOT
bypass `do_not_resolve` (`:590`), suppression (`:600`), budget (`:631`), no-IP (`:635`), privacy
relay (`:644`), the IPinfo VPN check (`:653`), or the Redis IP cache.

**Why this does not violate §Non-Goals.** The Non-Goal forbids re-running non-IP evidence *as if it
were new evidence* — i.e. spending a paid attempt on it. `_check_prior_signals` is free,
deterministic, and idempotent, and the live docstring at `:603-607` states its purpose: a visitor
who failed a paid lookup but LATER submits an email via a form must still be identified. The
correct guard is therefore in the **accounting**, not the bypass:

> When `_check_prior_signals` returns a result on an automatic retry, the sweep records a
> **SUCCESS that consumes NO attempt and appends NO `tried_ips` entry** — no provider was contacted
> and nothing was learned about the chosen IP. `next_at` is not advanced (the visitor is now
> identified and leaves the status set anyway).

Gate: `::prior_signal_hit_consumes_no_attempt` (Fully-Automated).

### CR-2 — FK orphan preflight (AD-15 ↔ S3-2)

- AD-15: an orphan preflight is "neither meaningful nor permitted."
- S3-2: the migration "must preflight."

**WINNER: AD-15. S3-2's preflight requirement is SUPERSEDED.**

**Normative rule.** The migration creates `reidentify_resolution_claims` **empty**, with its
composite `ForeignKeyConstraint([site_id, visitor_id] → visitors(site_id, visitor_id),
ondelete="CASCADE")` in the same `create_table` DDL. There is no pre-existing claim data, no
backfill, and **no orphan preflight query**. Viability is not re-derived — cycle 7 empirically
proved it on a disposable `postgres:16-alpine` (FK created against the non-partial
`uq_visitors_site_visitor` at `models/visitor.py:18`, parent delete cascaded 1→0, duplicate claim
rejected). Downgrade drops the child table **before** dropping the new parent columns.

Gate: `::test_claim_model_registered_by_create_all_and_cascades` (Hybrid).

### CR-3 — flag-off byte-identical behavior (AC-1 ↔ S4-2)

- AC-1: with the flag OFF, "no new behavior is observable anywhere"; Rollback says "no code revert
  needed."
- S4-2: the resolver's outage branch must stop falling through to the terminal write-off — a change
  that is nowhere flag-gated and affects all four provider-capable lanes.

**WINNER: S4-2 shipped UNCONDITIONALLY (user decision 13-08-26, Option B). AC-1 is REWRITTEN and the
old "no code revert needed" Rollback row is SUPERSEDED.**

**Normative rule (the new flag-OFF invariant).** With `auto_reidentify_enabled = False`:

1. The sweep job is never registered; the ranker, claim helper, and sweep module are never called.
2. `resolve()` receives `auto_retry=False`, `override_ip=None`, `selected_ip_activity_at=None`; the
   five mixins and `MatchingMixin` behave exactly as today.
3. `revive_returning_unresolvable` behaves exactly as today.
4. The new columns sit unread.
5. **EXCEPTION — the two unconditional bug-fix slices DO change behavior** (SN-1):
   - the per-tier outage verdict + no-write-off change (P1-AD-4), for all four lanes;
   - agent-company monthly-plan parity + success metering (DR-35).

**Rollback for the unconditional slices is a REVERT COMMIT, not a flag flip.** Keep each slice in
its own commit so it can be reverted independently — see §Rollback.

### SN-1 — Scope note: why two slices are unconditional (narrow extension of locked item 8)

Locked scope item 8 says the flag gates everything except the outage fix. This plan extends that by
exactly one slice — agent-company monthly-plan parity — because a **billing limit cannot
meaningfully be gated behind a feature flag**: flag-OFF would mean "keep bypassing the customer's
plan limit." Both unconditional slices are spend-**reducing** correctness fixes that widen nothing.
This is the only extension of locked scope in this plan and is flagged for PVL adjudication.

---

## Touchpoints

Every `path:line` below was re-derived live on `main` @ `3e2ddb5` on 13-08-26.
**EXECUTE rule: re-derive every anchor before editing** — concurrent plans hold unexecuted edits to
`identity_resolver.py` and `visitor_aggregator.py`.

| # | Path | Change | Why |
|---|---|---|---|
| P1 | `apps/api/models/visitor.py` | **+4 columns** on `Visitor` | attempt state (DR-1) |
| P2 | `apps/api/models/site.py` | **+1 column** `auto_reidentify_opt_out` | consent escape hatch (DR-23) |
| P3 | `apps/api/models/reidentify_resolution_claim.py` | **new** mapped model | TTL lease (DR-29) |
| P4 | `apps/api/main.py` | import `ReidentifyResolutionClaim` beside existing create-all imports | `Base.metadata.create_all()` must create it (DR-29) |
| P5 | `apps/api/migrations/versions/<new>.py` | **new** additive migration: 4 visitor cols + 1 site col + claim table | schema (DR-28, CR-2) |
| P6 | `apps/api/services/reidentify_ranker.py` | **new** pure module | IP ranking (DR-4…DR-13) |
| P7 | `apps/api/services/reidentify_claims.py` | **new** atomic claim helper | `try_claim_resolution` / `release_resolution_claim` only |
| P8 | `apps/api/services/reidentify_sweep_runner.py` | **new** sweep owner: two-pool selection, pre-checks, reserve, claim, billing parity, result-aware accounting | the sweep (DR-14…DR-21) |
| P9 | `apps/api/services/identity_resolver.py` | `resolve()` gains 3 defaulted params; effective IP at `:635 :644 :653 :694 :709 :677`; `override_ip` threaded into **BOTH** orchestrators (`:677` graphs, `:709` ip-company); per-tier outage verdict at `:761-793`; site-scoped cache key at `:694`; new `resolve_auto_retry()` | P0-2, P1-4, P1-5, DR-24 |
| P10 | `apps/api/services/identity_providers/pdl.py:62,74` | `_call_pdl_ip_enrich(self, visitor, *, override_ip=None)` | reads the IP itself |
| P11 | `apps/api/services/identity_providers/ipinfo.py:135,144` | `_call_ipinfo_api(self, visitor, *, override_ip=None)` | reads the IP itself |
| P12 | `apps/api/services/identity_providers/rb2b.py:158,182` | `_call_rb2b_api(self, visitor, *, override_ip=None)` | **residential-capable** (P0-2) |
| P13 | `apps/api/services/identity_providers/capturify.py:29,82,98` | `_call_capturify_api(self, visitor, *, override_ip=None, selected_ip_activity_at=None)` | **residential-capable** (P0-2) + DR-34 |
| P14 | `apps/api/services/identity_providers/leadpipe.py:97,175` | `_call_leadpipe_api(self, visitor, *, override_ip=None, selected_ip_activity_at=None)` | **residential-capable** (P0-2) + DR-34 |
| P15 | `apps/api/services/identity_providers/matching.py:138,175` | `_record_matches_visitor(..., *, activity_at: datetime \| None = None)` | DR-34; `None` retains `_visitor_activity_utc` (`:126`) exactly |
| P16 | `apps/api/services/resolution_runner.py:161-178` | acquire the shared claim after `check_usage_allowed` (`:161`) and before `processed += 1` / `resolve()` (`:172`); release the exact token in `finally` | DR-31 |
| P17 | `apps/api/tasks/resolution_tasks.py:118-130` | acquire/release the same claim after the billing gate (`:118`) and before `resolve()` (`:130`) | DR-31 |
| P18 | `apps/api/routers/visitors.py:953-963` | acquire the claim after `check_usage_allowed` (`:953`) and **before** any retryable terminal-state mutation or `resolve(force_retry=…)` (`:960`); busy ⇒ 409 `retry_in_progress` with no state write | DR-31 |
| P19 | `apps/api/services/agent_company_resolution.py:125-136` | monthly-plan parity + `increment_usage` once before `_upsert_company`/link work; acquire/release its synthetic-key claim | DR-35, SN-1 |
| P20 | `apps/api/services/promotion_sweep_runner.py` | call `resolve(visitor, deterministic_only=True)` | DR-32 |
| P21 | `apps/api/services/visitor_aggregator.py:365-431` | **+1 flag guard** — early-return in `revive_returning_unresolvable` | DR-26 |
| P22 | `apps/api/config.py` | **+1 flag block**: `auto_reidentify_enabled` (default **False**) + interval/cap/cadence/reserve constants | DR-27 |
| P23 | `apps/api/jobs/scheduler.py` | **+1 job** inside `if settings.auto_reidentify_enabled:` | DR-27 |
| P24 | `apps/api/schemas/sites.py:16-28,48-62` | `+auto_reidentify_opt_out` on `SiteOut` and `SiteUpdate` | the column is unreachable without them |
| P25 | `apps/api/routers/sites.py:330-389` | **+1 independent `if body.auto_reidentify_opt_out is not None:`** — must NOT touch `auto_paused_at` in either direction (contrast `:347-353`) | `update_site` copies fields one-by-one; unhandled fields are silently dropped |
| P26 | `tests/unit/test_reidentify_ranker.py` | **new** | ranker coverage |
| P27 | `tests/unit/test_reidentify_sweep.py` | **new** | accounting/log coverage |
| P28 | `tests/integration/test_reidentify_sweep.py` | **new** | selection/PG coverage |
| P29 | `tests/integration/test_reidentify_resolution_leases.py` | **new** four-human-lane race owner | DR-31 |
| P30 | `tests/integration/test_agent_company_resolution.py` | **new file — does NOT exist on disk today** | DR-35 (closes cycle-7 G5) |
| P31 | `tests/unit/test_agent_company_resolution.py:515-520` | append `apps/api/services/reidentify_sweep_runner.py` to the hardcoded `_AC2_FILES`; add plan-limit / metering / split-exception assertions | the AC-8 tripwire cannot discover a new module otherwise |
| P32 | `tests/unit/test_resolution_deferral_watermark.py:340` | **replace** `test_past_the_last_step_writes_off_and_resets` with `test_past_the_last_step_repeats_capped_defer_and_never_writes_off`; strengthen sweep discovery; add the provider-capable caller census guard | P1-AD-4 inverts this test's asserted behavior (closes cycle-7 G2) |
| P33 | `tests/unit/test_identity_resolver_parallel.py` | add per-tier outage matrix + `override_ip` reaches both orchestrators | P1-4, P0-2 |
| P34 | `tests/unit/test_scheduler_job_config.py:176-223` | 24/21/3 → **25/22/3** add-job/interval/cron, with provenance paragraph | DR-27 |
| P35 | `tests/integration/test_unresolvable_revive.py:97-120` | flag-parametrise | DR-26 |
| P36 | `tests/integration/test_visitor_resolve_endpoint.py` | add the 409-without-state-write case | P18 |
| P37 | `tests/integration/test_promotion_sweep.py` | add the deterministic-only condition gate | DR-32 |
| P38 | `tests/unit/test_identity_enrich_correctness.py` | pure matching precedence/fallback coverage | DR-34 |

**Read-only (consulted, never edited):** `apps/api/services/asn_lookup.py:61`,
`apps/api/services/ip_org_ingest.py:116`, `apps/api/services/company_resolver.py:233` / `:455`,
`apps/api/services/resolution_eligibility.py:85-106`,
`apps/api/services/agent_visitor_filters.py:19-65`,
`apps/api/services/usage_limits.py`, `apps/api/models/event.py:74`,
`apps/api/services/identity_providers/base.py:16-25`, `tests/conftest.py`.

---

## Public Contracts

| Contract | Change | Compatibility |
|---|---|---|
| `Visitor` ORM | **+4** defaulted columns (`auto_reidentify_count`, `auto_reidentify_next_at`, `auto_reidentify_tried_ips`, `auto_reidentify_skip_count`) | additive; no reader breaks |
| `Site` ORM / `sites` table | **+1** column `auto_reidentify_opt_out` (default **false**) | additive; every-site coverage preserved |
| DB schema | +4 on `visitors`, +1 on `sites`, + `reidentify_resolution_claims` (UUID PK, `UNIQUE(site_id, visitor_id)`, `owner_token`, `expires_at`, composite FK `ON DELETE CASCADE`) | additive, identifier-only, expiring, erased with its visitor |
| `IdentityResolver.resolve()` | +3 defaulted kwargs (`auto_retry=False`, `override_ip=None`, `selected_ip_activity_at=None`); return type unchanged (`IdentifiedVisitor \| None`) | all existing callers unchanged |
| `IdentityResolver.resolve_auto_retry()` | **new** public method returning `ResolutionAttemptResult` (`outcome` ∈ `match` / `no_match` / `provider_unavailable`, plus the identified row) | new surface only |
| 5 provider mixins | all gain defaulted `override_ip`; Leadpipe + Capturify additionally gain defaulted `selected_ip_activity_at` | defaulted ⇒ existing callers unchanged; PDL/IPinfo/RB2B gain no unused time argument |
| `MatchingMixin._record_matches_visitor()` | keyword-only `activity_at: datetime \| None = None`; when non-null, normalise by the existing naive/aware UTC rule and compare against it; when null, retain `_visitor_activity_utc(visitor)` | internal additive; no `Visitor.last_seen` mutation |
| `visitors.ip_address` | **NEVER written by this feature on any path** | the override is a parameter (DR-24); gated by `::sweep_does_not_persist_chosen_ip` |
| **Outage terminal state — UNCONDITIONAL CHANGE (CR-3)** | The resolver no longer writes `identity_status = "unresolvable"`, `resolution_defer_count = 0`, `resolution_deferred_until = None` after ramp exhaustion. It caps the count at `len(RESOLUTION_DEFER_BACKOFF)` and re-arms a 24h watermark, retaining the current status. **Outage is now entered only when EVERY applicable tier is `all_unavailable`** (was: OR across tiers). | **BREAKING for terminal-state expectations in all four lanes** — see the caller disclosure table below |
| **Redis negative cache key** | site-scoped **for automatic-retry calls only**: `resolution:{site_id}:{ip}` when `auto_retry=True`; legacy `resolution:{ip}` for every other caller | closes cross-tenant suppression for the new lane; the legacy leak for default lanes is Phase 2 (backlog) |
| **Agent-company monthly gate + metering — UNCONDITIONAL CHANGE (SN-1)** | `check_usage_allowed` fail-closed before claim/provider work; `increment_usage` exactly once on a non-`None` result before `_upsert_company` / `AgentVisit.resolved_company_id` work | **BREAKING for callers relying on the agent lane bypassing the monthly plan limit** — it never should have |
| Shared claim service | `try_claim_resolution(...) -> ResolutionClaim \| None`, `release_resolution_claim(...) -> None`; owner token compared on release | four human lanes same-key contend (DR-31); agent-company contends only with itself |
| `POST /{site_id}/{visitor_id}/resolve` | returns **409 `retry_in_progress`** on a live claim, with no visitor-state write | new failure code; success/limit responses unchanged |
| Promotion sweep | `run_promotion_sweep_once()` calls `resolve(visitor, deterministic_only=True)` | paid-provider work becomes structurally unreachable; takes no lease |
| `SiteUpdate` / `SiteOut` + `PATCH /sites/{id}` | +1 optional request field, +1 response field | additive, defaulted ⇒ existing clients unchanged |
| `revive_returning_unresolvable()` | early-return when the flag is on | flag off ⇒ byte-identical |
| `identity_status` vocabulary | **UNCHANGED — no new value** (DR-25) | zero vocabulary blast radius |
| New public functions | `rank_candidate_ips`, `resolve_auto_retry`, `run_reidentify_sweep_once(db)`, `run_reidentify_sweep()`, `try_claim_resolution`, `release_resolution_claim` | new surface only |
| Settings | `+auto_reidentify_enabled` (default **False**) + interval/cap/cadence/reserve constants | inert by default |

### Terminal-state change — disclosure to all four provider-capable lanes

The unconditional outage change (P1-AD-4) alters what each lane observes when providers are down.
This is the disclosure cycle-7 G3 found missing.

| Lane | Entry point | Before | After |
|---|---|---|---|
| APScheduler | `resolution_runner.py::run_resolution_for_site` | partial outage → 4 defers, then `unresolvable` with defer state cleared | partial outage → **immediate** `unresolvable` (the answering tier's verdict is respected); full outage → capped 24h re-defer, status retained, **never** written off |
| Registered Celery | `resolution_tasks.py::_process_site` | same | same |
| Manual retry | `routers/visitors.py::resolve_one_visitor` | a full outage could terminalise the visitor | full outage returns HTTP 200 `{status: "anonymous", skip_reason: "provider_outage"}`; status retained |
| Agent-company sweep | `agent_company_resolution.py::run_company_resolution_sweep` | same as APScheduler, plus no monthly-plan gate | same outage semantics, **plus** the monthly-plan gate and success meter (SN-1) |

**Accepted trade-off, disclosed:** replacing the OR with "every applicable tier unavailable" means a
visitor whose person-graph tier is down but whose IP tier answered no-match is terminalised
immediately instead of after four 15m/1h/6h/24h defers. Net effect is **fewer** paid dispatches and
faster settling; the recovery path is this plan's own 4-attempt sweep, not the outage ramp. Under
the CURRENT live config (Leadpipe 403, RB2B 402) this is the difference between ~365 dispatches per
visitor per year and one.

---

## Blast Radius

| Dimension | Value |
|---|---|
| Files changed | **38 paths** (P1–P38): 25 source, 13 test |
| Packages | `apps/api` only (models, services, migrations, config, jobs, schemas, routers) + `tests`. **No `apps/web` changes in Phase 1.** |
| Risk classes | **schema/data migration**, **identity/PII surface**, **paid-provider spend**, **billing/credits**, **scheduler** |
| High-risk verdict | YES — Hybrid-tier minimum applies to every area (see §Verification Evidence) |
| Contested files | `identity_resolver.py` (3 params + outage branch + cache key), `visitor_aggregator.py` (1 guard) |
| PII columns written | **none.** `visitors.ip_address` is read-only to this feature by construction (DR-24) |
| Unconditional (non-flag-gated) surface | exactly 2 slices: `identity_resolver.py:761-793` outage branch; `agent_company_resolution.py:125-136` billing parity |
| Rollback | flag OFF for the gated surface; **revert commit** for the 2 unconditional slices; migration additive and down-reversible |

---

## Architecture Decisions

### P1-AD-1 — Schema (P1–P5)

Four columns on `Visitor`, following `c2f7a9d31b64` exactly (additive, defaulted, no index, no
constraint, no backfill — its docstring `:19-25` carries the rationale).

| Column | Type | Purpose |
|---|---|---|
| `auto_reidentify_count` | `Integer NOT NULL server_default "0"` | lifetime attempts; **MONOTONIC** — no code path resets it |
| `auto_reidentify_next_at` | naive `DateTime NULL` | cadence watermark; **NULL = evaluate now**, NULL pool bounded to half the batch |
| `auto_reidentify_tried_ips` | `JSONB NULL` | IPs already spent; ≤4 entries by construction |
| `auto_reidentify_skip_count` | `Integer NOT NULL server_default "0"` | futile-evaluation counter; retirement bound `< 8` |

Naive datetimes to match `Visitor`'s convention (`resolution_deferred_until` is naive;
`ErasureRequest` is aware — **never mix the two in one comparison**). Plus
`sites.auto_reidentify_opt_out Boolean NOT NULL server_default "false"` and the claim table per CR-2.

### P1-AD-2 — Pure ranker (P6)

```python
def rank_candidate_ips(
    candidates: list[IpEvidence],
    *,
    tried_ips: frozenset[str],
    now: datetime | None = None,
    weights: Weights = DEFAULT_WEIGHTS,
) -> RankResult:   # {"ranked": [...], "chosen": IpEvidence | None, "excluded": [...], "evidence": [...]}
```

Returns the FULL ordering plus the chosen candidate, so attempt N takes the Nth-ranked untried IP
and the decision is auditable. `IpEvidence` carries `last_activity_at` (= `MAX(Event.created_at)`
for that IP, DR-34) and the ranker **preserves it on the chosen candidate without modification**.

Per DR-4…DR-13: pure core, injected clock, mandatory `asn is None → "unknown"` short-circuit
(carry the traced proof as an inline comment so it survives future edits), ladder with `unknown`
second, hard exclusions, 8-key total-order tiebreak with the business-hours abstain rule.

**Blocking-call note:** `lookup_asn` is synchronous. Harmless today (no mmdb ⇒ immediate return) but
it will block the event loop once an mmdb is installed — memoise per tick and wrap in
`asyncio.to_thread` if one ever ships.

### P1-AD-3 — `override_ip` reaches BOTH orchestrators and all five IP-reading mixins (P9–P15) — closes P0-2

**This is the defect that made the predecessor's central feature a no-op at the only
residential-capable tier.** There are **two** parallel orchestrators, not one, and both dispatch
`call_fn(visitor)`:

| Orchestrator | Live anchor | Dispatch | Mixins carried | IP-reading anchor |
|---|---|---|---|---|
| `_resolve_identity_graphs_parallel` | `:801`, called at `:677` | `:841` `call_fn(visitor)` | leadpipe, capturify, rb2b — **the residential-capable tier** | `leadpipe.py:175`, `capturify.py:82`, `rb2b.py:182` |
| `_resolve_ip_company_parallel` | `:973`, called at `:709` | `:994` `call_fn(visitor)` | pdl, ipinfo | `pdl.py:74`, `ipinfo.py:144` |

**Normative rule.** `resolve()` computes `effective_ip = override_ip or visitor.ip_address` once and
uses it at every gate and dispatch: `:635` (no-IP), `:644` (relay), `:653` (IPinfo VPN), `:694`
(cache key), `:677` (graphs orchestrator), `:709` (ip-company orchestrator). BOTH orchestrators gain
a keyword-only `override_ip: str | None = None` and forward it to their `call_fn` as
`call_fn(visitor, override_ip=override_ip)`. Each mixin uses `override_ip or visitor.ip_address` for
its own query and for its `!= visitor.ip_address` equality comparisons.

Exact signature changes (enumerated so no mixin can be missed):

| File | Current signature | New signature |
|---|---|---|
| `pdl.py:62` | `_call_pdl_ip_enrich(self, visitor)` | `_call_pdl_ip_enrich(self, visitor, *, override_ip=None)` |
| `ipinfo.py:135` | `_call_ipinfo_api(self, visitor)` | `_call_ipinfo_api(self, visitor, *, override_ip=None)` |
| `rb2b.py:158` | `_call_rb2b_api(self, visitor)` | `_call_rb2b_api(self, visitor, *, override_ip=None)` |
| `capturify.py:29` | `_call_capturify_api(self, visitor)` | `_call_capturify_api(self, visitor, *, override_ip=None, selected_ip_activity_at=None)` |
| `leadpipe.py:97` | `_call_leadpipe_api(self, visitor)` | `_call_leadpipe_api(self, visitor, *, override_ip=None, selected_ip_activity_at=None)` |
| `matching.py:138` | `_record_matches_visitor(self, record, visitor, …)` | `… , *, activity_at: datetime \| None = None` |
| `identity_resolver.py:801` | `_resolve_identity_graphs_parallel(self, visitor, *, tier_verdicts=None)` | `… , override_ip=None, selected_ip_activity_at=None` |
| `identity_resolver.py:973` | `_resolve_ip_company_parallel(self, visitor)` | `… , *, override_ip=None` |

Hunter and Apollo take a **domain**, not an IP, and are deliberately unchanged.

**Never assign `visitor.ip_address` or `visitor.last_seen`** (DR-24, DR-34). `resolve()` commits on
every exit path, so an assignment is a committed write to a plaintext PII column.

### P1-AD-4 — Per-tier outage verdict, no write-off (P9, P32, P33) — closes P1-4, UNCONDITIONAL

Live code at `identity_resolver.py:761-793`:

```python
person_verdict = tier_verdicts.get("person_graph", TIER_NOT_APPLICABLE)
if TIER_ALL_UNAVAILABLE in (person_verdict, ip_verdict):     # ← OR across independent tiers
    attempt = (visitor.resolution_defer_count or 0) + 1
    if attempt <= len(RESOLUTION_DEFER_BACKOFF): ... return None
    logger.warning("resolution_defer_exhausted", ...)
# falls through:
visitor.resolution_deferred_until = None
visitor.resolution_defer_count = 0
visitor.identity_status = "unresolvable"
```

Two independent bugs live here. Fix both in one slice — fixing only the write-off yields unbounded
re-dispatch of the live tier every 24h.

**Normative rule 1 — outage requires ALL applicable tiers dead.** `tier_verdict()`
(`identity_resolver.py:100-112`) already distinguishes `not_applicable` (nobody looked) from
`answered` and `all_unavailable`. Replace the OR with:

```python
applicable = [v for v in (person_verdict, ip_verdict) if v != TIER_NOT_APPLICABLE]
is_outage = bool(applicable) and all(v == TIER_ALL_UNAVAILABLE for v in applicable)
```

A tier that **answered** has its verdict respected and is never re-dispatched by outage logic. When
no tier is applicable (nothing configured), `is_outage` is False and today's terminal path is
retained unchanged.

**Normative rule 2 — the outage branch NEVER falls through to the terminal reset.** Compute the
delay with `min(current_defer_count, len(RESOLUTION_DEFER_BACKOFF) - 1)`; cap the persisted count at
`len(RESOLUTION_DEFER_BACKOFF)`. Stages 1–4 use each configured delay once (15m, 1h, 6h, 24h); every
later full outage keeps the count at the cap and writes a fresh
`resolution_deferred_until = now + RESOLUTION_DEFER_BACKOFF[-1]`, **retains the current
`identity_status`**, and returns `None`. Only a real answer / no-match reaches the terminal reset.

**Normative rule 3 — nobody else writes the defer fields.** The resolver is the sole writer
(DR-16). No sweep, claim helper, or endpoint resets, restores, or clears
`resolution_defer_count` / `resolution_deferred_until`.

**Invariants at every outage stage, including the capped repeat:** all four
`auto_reidentify_*` columns unchanged; no `ResolutionLog` row for that outage; distinct-visitor daily
meter unchanged; zero provider dispatch before the recorded watermark is due.

**P32 is mandatory, not cosmetic.** `tests/unit/test_resolution_deferral_watermark.py:340`
(`test_past_the_last_step_writes_off_and_resets`) asserts exactly the behavior this rule inverts. It
must be **replaced**, not deleted silently.

### P1-AD-5 — Site-scoped negative cache for the automatic lane (P9) — closes P1-5

Live key: `cache_key = f"{REDIS_RESOLUTION_PREFIX}{visitor.ip_address}"` at `:694`, prefix
`resolution:` (`identity_providers/base.py:16`, DR-39). No `site_id` ⇒ site A's `__none__` sentinel
suppresses site B's dispatch for 30 days on a shared NAT/CGNAT IP, while site B's attempt is still
counted and the IP appended to `tried_ips` — a verbatim re-entry of the self-annihilation path
DR-18/DR-20 exist to close.

**Normative rule.**

```python
cache_key = (
    f"{REDIS_RESOLUTION_PREFIX}{visitor.site_id}:{effective_ip}"
    if auto_retry
    else f"{REDIS_RESOLUTION_PREFIX}{effective_ip}"
)
```

Automatic-retry calls read and write the site-scoped key only; every other caller keeps the legacy
key byte-for-byte, so this change stays inside the flag boundary per CR-3.

**Accepted, disclosed:** the cross-tenant leak still exists for the three default lanes. Re-keying
the whole cache is a behavior change for every lane and is **Phase 2** (backlog note, item D-7).
Legacy keys are never deleted — they simply expire at their existing 30-day TTL.

### P1-AD-6 — Sweep selection, reserve, and accounting (P8)

Authoritative selection algorithm (DR-14, DR-15). Shared base predicate in **every** pool:

```
site_id = :site
AND identity_status IN ('unresolvable', 'vpn_filtered')
AND auto_reidentify_count < 4
AND auto_reidentify_skip_count < 8
AND do_not_resolve IS false
AND <site.auto_reidentify_opt_out IS false>
AND <site.tracking_enabled IS true>
AND <resolution_not_deferred_filter()>
AND <human_only_visitor_filter()>
AND <resolution_candidate_filter(...)>
AND NOT EXISTS active reidentify_resolution_claims row for this visitor

null_base = base AND auto_reidentify_next_at IS NULL
  ORDER BY intent_score DESC, visitor_id ASC                            LIMIT 10
due_base  = base AND auto_reidentify_next_at <= :now
  ORDER BY auto_reidentify_next_at ASC, intent_score DESC, visitor_id ASC LIMIT 10
spillover = base AND visitor NOT IN (null_base UNION due_base)
  ORDER BY CASE WHEN auto_reidentify_next_at IS NULL THEN 0 ELSE 1 END,
           auto_reidentify_next_at ASC NULLS FIRST, intent_score DESC, visitor_id ASC
  LIMIT (20 - count(null_base) - count(due_base))
batch = null_base UNION ALL due_base UNION ALL spillover
```

This is the **only** selection shape. No within-tick refill after a busy claim: a busy row is
skipped without a stamp and the next tick re-runs the same algorithm.

**Site enumeration** follows `resolution_runner.py` — `select(Site).where(Site.tracking_enabled.is_(True))`
plus the opt-out term — then the candidate query once per site with `site_id` bound. The module
*skeleton* comes from `promotion_sweep_runner.py`; the *query* does not (that donor is a single
global scan, DR-14).

**Budget reserve (DR-19/DR-20):** refuse when
`get_resolution_attempts_today(db, site_id) >= ceil(0.70 * get_site_daily_budget(db, site_id))` —
threshold **35** at the default budget of 50 (34 allowed, 35 refused). Re-evaluated immediately
before **each** `resolve()` inside the per-visitor loop; the site-level read at the top of the site's
turn is a cheap early-out only. Both refusals behave identically and **stamp nothing**.

> **70% is an explicitly-labelled PLACEHOLDER**, to be tuned from measured per-site data before any
> prod flag flip — the same posture as `job_change_recheck_daily_cap`. Accepted N+1 cost: up to ~21
> `COUNT(DISTINCT …)` per site per tick. Accepted residual TOCTOU: the main sweep consumes the same
> unlocked meter, so the day total can land a few resolves past 70% (~82% worst case). The honest
> guarantee is on when retries *start*.

**Accounting table (final; no supplement overrides it).**

| Situation | `count` | `skip_count` | `next_at` | `tried_ips` |
|---|---|---|---|---|
| Chosen IP actually sent to a provider | **+1** | unchanged | `now + 7d` | append the IP |
| `_check_prior_signals` hit — free deterministic success, no provider call (CR-1) | unchanged | unchanged | unchanged | unchanged |
| Evaluated, no untried IP (SKIP) | unchanged | **+1** | `now + 7d` | unchanged |
| Pre-check miss — `do_not_resolve` / suppressed | unchanged | **+1** | `now + 7d` | unchanged |
| **Budget refusal** (reserve or `check_daily_budget`) | unchanged | unchanged | unchanged | unchanged — **stamps NOTHING** |
| `outcome == "provider_unavailable"` (any stage, incl. the capped repeat) | unchanged | unchanged | unchanged | unchanged — retain the resolver's defer state; release only the claim |
| The call raised | unchanged | unchanged | **`now + backoff`** | unchanged |

An exception is our fault, not evidence about the IP — it consumes nothing but **must** advance
`next_at`, or a deterministic exception re-selects the same visitor every tick forever.

### P1-AD-7 — Billing parity in the new sweep (P8) — closes P0-1

`check_resolution_attempt_budget` (the 50/site/day distinct-visitor meter) is **not** a plan gate.
Every other provider-capable lane also checks `check_usage_allowed(db, site.user_id)` against
`User.monthly_identified_count` and calls `increment_usage` on success. Without both, a free-tier
site at 10/10 would have the main sweep and manual retry refuse while the new sweep dispatches the
full paid waterfall — and, because `increment_usage` is never called, the counter freezes and
**silently raises the effective cap for every other lane**.

**Normative rule.** Inside `run_reidentify_sweep_once`, per site, mirroring the donor sequence
`resolution_runner.py:161 → 172 → 178` exactly:

1. `if not await check_usage_allowed(db, site.user_id):` → record
   `counters["skipped_plan_limit"]`, log non-PII, and `break` out of this site's visitor loop
   (fail-closed; a missing site or owner is also a skip).
2. reserve re-check → claim → pre-checks → rank → `resolve_auto_retry(...)`.
3. On a **claimed non-`None` success**: `await increment_usage(db, site.user_id)` **exactly once**,
   before any downstream enrichment/link work.
4. Busy claim, budget refusal, SKIP, `provider_unavailable`, exception, and CR-1 prior-signal hits
   all meter **zero**.
5. Release the exact owner token in `finally`.

Same rule applied to `agent_company_resolution.py` per DR-35 / SN-1: a pre-success resolver
exception meters zero and releases its exact token; a post-success `_upsert_company` / link exception
retains the one increment, releases its token, and a retry adds no second increment.

### P1-AD-8 — Claim lease across four human lanes (P3, P4, P7, P16–P19) — DR-29…DR-33

`reidentify_claims.py` exposes exactly two entry points, `try_claim_resolution(...)` and
`release_resolution_claim(...)`. No caller may open-code insert / expiry-replace / delete. The four
human same-key lanes are manual retry (P18), APScheduler (P16), registered Celery (P17), and the new
sweep (P8). Agent-company (P19) holds the same kind of claim only against another agent-company
execution for its synthetic `agent:{AgentVisit.id}` key. `promotion_sweep_runner` (P20) takes no
lease and is barred from paid providers by `deterministic_only=True`.

Every winner releases its **exact** token in `finally`. A busy claim produces no resolver, provider,
billing, enrichment, link, or state side effect — only a non-PII `claim_busy` counter (and, for the
manual endpoint, a 409).

### P1-AD-9 — Flag, scheduler, revive subordination (P21–P23)

`auto_reidentify_enabled: bool = False` in `apps/api/config.py`, following the house block style
(`:622-647` promotion sweep, `:722-731` ip-org): section header, multi-paragraph rationale, default-OFF
posture with precedents named. Plus `auto_reidentify_interval_minutes`, the cap/cadence constants,
and the reserve fraction. Scheduler: thin wrapper with lazy import inside, `try/except → logger.exception`,
registered inside `if settings.auto_reidentify_enabled:`, explicit `id`, literal positive `jitter`
and `misfire_grace_time`, boot offset **smaller than `aggregation_sweep`'s 90s**.
`revive_returning_unresolvable` becomes a no-op early-return when the flag is on (DR-26).

---

## High-level Data Flow

```
APScheduler (every N min, flag ON)
  └─ run_reidentify_sweep()                      [own advisory lock, FAIL OPEN]
       └─ run_reidentify_sweep_once(db)
            ├─ enumerate sites: tracking_enabled AND NOT auto_reidentify_opt_out
            └─ per site:
                 ├─ PLAN GATE: check_usage_allowed(user) is False ─► break (skipped_plan_limit)
                 ├─ SITE EARLY-OUT: attempts_today >= ceil(.70*budget) ─► next site
                 ├─ SELECT ≤20 visitors (two-pool query, P1-AD-6)
                 └─ per visitor (try/except/continue):
                      ├─ RESERVE RE-CHECK  ─► refuse: STAMP NOTHING
                      ├─ TRY CLAIM         ─► busy: no stamp, claim_busy++
                      ├─ PRE-CHECKS (budget / do_not_resolve / suppression)
                      │      ─► budget: stamp nothing | else SKIP: skip_count+1, next_at+7d
                      ├─ GROUP BY ip_address over events  [ix_events_site_visitor, NOT is_flagged_abuse,
                      │                                    MAX(created_at) per IP]
                      ├─ asn is None ─► tier "unknown"    [SHORT-CIRCUIT, classify_ip_org_kind NOT called]
                      ├─ lookup_asn → classify_ip_org_kind ; _read_company_graph (if enabled)
                      ├─ rank_candidate_ips(...)          [PURE]
                      ├─ chosen is None ─► SKIP: skip_count+1, next_at+7d
                      └─ chosen ─► resolve_auto_retry(auto_retry=True,
                                       override_ip=chosen.ip,
                                       selected_ip_activity_at=chosen.last_activity_at)
                                   ├─ prior-signal hit ─► success, NO attempt (CR-1)
                                   ├─ provider_unavailable ─► retain defer watermark, no accounting
                                   ├─ raised ─────────────► next_at = now + backoff only
                                   └─ provider work ──────► count+1, next_at+7d, tried_ips.append,
                                                            increment_usage ONCE
                                   finally ──────────────► release exact claim token
```

Flag OFF ⇒ the job is never registered, revive behaves as today, `resolve()` receives all three
defaults, and the four columns sit unread — **except** the two unconditional slices (CR-3).

---

## Phase Completion Rules

A phase is complete ONLY when all five hold:

1. **Integration test** — works end-to-end with the pieces around it.
2. **Manual test** — a human (or agent probe) can observe the intended behavior.
3. **Database/state check** — the four new `Visitor` columns actually hold the values the P1-AD-6
   accounting table specifies.
4. **Error handling** — outage, exception, missing mmdb, missing `country_code`, empty candidate set,
   busy claim, plan-limit refusal all behave as specified (fail-safe, nothing consumed).
5. **User confirmation** — the user confirms it works before any `✅ VERIFIED` marker is written.

Status markers: ⏳ PLANNED · 🔨 CODE DONE · 🧪 TESTING · ✅ VERIFIED · 🚧 BLOCKED.
**Never** mark ✅ VERIFIED on "build succeeds" / "no type errors" / "files created".

---

## Implementation Checklist

Commands (repo-verified, `process/context/tests/all-tests.md`):
`.venv/bin/python -m pytest tests/unit -m unit -q` · `.venv/bin/python -m pytest tests/ -m integration -q`.
**Never bare `pytest`.** Integration precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`
(PG **5433**, Redis **6379**); detect Docker by `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`,
**not** `which docker`.

### Phase-01 — Schema + claim table (P1–P5) — ⏳ PLANNED

- [ ] 1.1 Add the 4 columns to `Visitor` (`apps/api/models/visitor.py`) per P1-AD-1 — naive
      datetimes, no index, no constraint.
- [ ] 1.2 Add `auto_reidentify_opt_out Boolean NOT NULL server_default "false"` to `Site`
      (`apps/api/models/site.py`).
- [ ] 1.3 Create `apps/api/models/reidentify_resolution_claim.py` per DR-29 / CR-2: inherited UUID
      PK, `UNIQUE(site_id, visitor_id)`, opaque UUID `owner_token`, naive-UTC `expires_at`,
      `ForeignKeyConstraint([site_id, visitor_id], ["visitors.site_id", "visitors.visitor_id"],
      ondelete="CASCADE")`.
- [ ] 1.4 Import that model in `apps/api/main.py` beside its existing create-all imports. Do NOT
      rely on `apps/api/models/__init__.py` — `main.py` does not import it.
- [ ] 1.5 **Derive the live head:** `DATABASE_URL=postgresql+asyncpg://…@localhost:5433/… .venv/bin/python -m alembic -c apps/api/alembic.ini heads`.
      DR-38 records `f4b9d2a71c68` as of 13-08-26 — **verify, never hardcode**. Never run alembic
      with the repo `.env` DSN (Supabase PROD, no local-host guard).
- [ ] 1.6 Write the additive migration chained off that head: 4 visitor columns, 1 site column, and
      the empty `reidentify_resolution_claims` table with the exact FK/UQ shape. **No backfill and no
      orphan preflight** (CR-2). Downgrade drops the child table BEFORE the parent columns. Docstring
      follows `c2f7a9d31b64:19-25`.
- [ ] **Test gate 1 (Hybrid + Fully-Automated):** migration up→down→up clean on a **disposable**
      Postgres (never the shared dev container); `.venv/bin/python -m pytest tests/unit -m unit -q`
      green; `tests/integration/test_reidentify_resolution_leases.py::test_claim_model_registered_by_create_all_and_cascades`
      green (proves CR-2 + DR-29 in one gate).

### Phase-02 — Pure ranker (P6, P26) — ⏳ PLANNED

- [ ] 2.1 Create `apps/api/services/reidentify_ranker.py`: `IpEvidence` (including
      `last_activity_at`), `Weights`, `DEFAULT_WEIGHTS`, `RankResult`, `rank_candidate_ips`. No
      DB/network imports at module scope; clock via `now=None`.
- [ ] 2.2 Hard exclusions (DR-11): already-tried, `is_privacy_relay_ip`, malformed/private/
      reserved/loopback, all-events-flagged.
- [ ] 2.3 Tier ladder with `unknown` **second** and the **mandatory `asn is None → "unknown"`
      short-circuit** — never call `classify_ip_org_kind(None, …)`. Carry the traced proof as an
      inline comment (DR-7).
- [ ] 2.4 8-key tiebreak chain (DR-12) including the business-hours **abstain** rule.
- [ ] 2.5 Preserve `last_activity_at` unmodified on the chosen candidate (DR-34).
- [ ] 2.6 Write `tests/unit/test_reidentify_ranker.py` — table-driven, no DB, no mmdb. Assert total
      order by **permuting the input list and requiring identical output**.
- [ ] **Test gate 2 (Fully-Automated):** `.venv/bin/python -m pytest tests/unit/test_reidentify_ranker.py -q`
      green, including `::asn_none_short_circuits_to_unknown` and
      `::total_order_under_permutation`.

### Phase-03 — Resolver params + `override_ip` through BOTH orchestrators (P9–P15, P33, P38) — ⏳ PLANNED — **closes P0-2**

- [ ] 3.1 Re-derive anchors `:544 :590 :600 :608 :625 :631 :635 :644 :653 :677 :694 :709 :801 :841 :973 :994`
      (file contested by concurrent plans).
- [ ] 3.2 Add `auto_retry: bool = False`. Bypass **only** `was_recently_attempted` at `:625` (CR-1).
      Extend the docstring to state it bypasses that one statement and nothing else.
- [ ] 3.3 Add `override_ip: str | None = None` and `selected_ip_activity_at: datetime | None = None`.
      Compute `effective_ip = override_ip or visitor.ip_address` once; use it at `:635 :644 :653 :694`.
      **Assert by review that no path assigns `visitor.ip_address` or `visitor.last_seen`.**
- [ ] 3.4 Thread `override_ip` into `_resolve_identity_graphs_parallel` (`:801`, dispatch `:841`) —
      **the leg the predecessor missed** — and into `_resolve_ip_company_parallel` (`:973`, dispatch
      `:994`). Both forward `call_fn(visitor, override_ip=…)`.
- [ ] 3.5 Add the defaulted `override_ip` parameter to all five IP-reading mixins per the P1-AD-3
      signature table; Leadpipe and Capturify additionally take `selected_ip_activity_at`. Each mixin
      uses `override_ip or visitor.ip_address` for its query **and** for its equality comparison
      (`leadpipe.py:175`, `capturify.py:82`). Hunter and Apollo are unchanged.
- [ ] 3.6 Add keyword-only `activity_at=None` to `MatchingMixin._record_matches_visitor`
      (`matching.py:138`); when non-null, normalise by the existing naive/aware rule and compare
      against it at `:175`; when null, retain `_visitor_activity_utc(visitor)` (`:126`) exactly.
- [ ] 3.7 Add `resolve_auto_retry(...) -> ResolutionAttemptResult` as a thin public wrapper over the
      shared private core; `resolve()` keeps its `IdentifiedVisitor | None` return for all existing
      callers.
- [ ] 3.8 Extend `tests/unit/test_identity_resolver_parallel.py` with
      `::override_ip_reaches_graph_orchestrator_mixins` (leadpipe/capturify/rb2b receive the override,
      NOT `visitor.ip_address`) and `::override_ip_reaches_ip_company_orchestrator_mixins`; add
      matching precedence/fallback coverage to `tests/unit/test_identity_enrich_correctness.py`.
- [ ] **Test gate 3 (Fully-Automated):** `.venv/bin/python -m pytest tests/unit/test_identity_resolver_parallel.py tests/unit/test_identity_enrich_correctness.py -q`
      green, including the existing `deterministic_only` invariant (`check_daily_budget.assert_not_called()`
      + `_resolve_identity_graphs_parallel.assert_not_called()`) which **must stay green**.

### Phase-04 — Per-tier outage verdict, no write-off (P9, P32, P33) — ⏳ PLANNED — **UNCONDITIONAL, closes P1-4**

- [ ] 4.1 Replace the OR at `identity_resolver.py:762` with the `applicable` / `is_outage` computation
      from P1-AD-4 normative rule 1.
- [ ] 4.2 Cap the persisted count at `len(RESOLUTION_DEFER_BACKOFF)`, compute the delay with
      `min(current_defer_count, len(...) - 1)`, write a fresh 24h watermark on every later full
      outage, retain `identity_status`, and **return before the terminal reset** (rule 2).
- [ ] 4.3 Verify by review that no other module writes `resolution_defer_count` /
      `resolution_deferred_until` (rule 3).
- [ ] 4.4 **Replace** `tests/unit/test_resolution_deferral_watermark.py:340`
      `test_past_the_last_step_writes_off_and_resets` with
      `test_past_the_last_step_repeats_capped_defer_and_never_writes_off`. Do not delete it silently.
- [ ] 4.5 Add the per-tier matrix to `tests/unit/test_identity_resolver_parallel.py`:
      `answered × all_unavailable`, `all_unavailable × answered`, `all_unavailable × all_unavailable`,
      `not_applicable × not_applicable`.
- [ ] 4.6 Commit this slice **alone** so it can be reverted independently (CR-3 / §Rollback).
- [ ] **Test gate 4 (Fully-Automated + Hybrid):** unit lane green including the replaced watermark
      test and the 4-cell matrix; `.venv/bin/python -m pytest tests/integration/test_resolution_deferral_sweep.py -q`
      green (no regression in the existing deferral integration surface).

### Phase-05 — Site-scoped negative cache (P9) — ⏳ PLANNED — **closes P1-5**

- [ ] 5.1 Apply the P1-AD-5 conditional key at `identity_resolver.py:694`. Use the live prefix
      `resolution:` from `identity_providers/base.py:16` — **not** `beam:resolution:` (DR-39).
- [ ] 5.2 Add `tests/unit/test_reidentify_sweep.py::cache_key_is_site_scoped_only_for_auto_retry` —
      assert the exact key string on both branches.
- [ ] 5.3 Add `tests/integration/test_reidentify_sweep.py::site_a_negative_cache_does_not_suppress_site_b` —
      seed site A's `__none__` for a shared IP, run site B's sweep, assert a provider WAS contacted.
- [ ] **Test gate 5 (Fully-Automated + Hybrid):** both new tests green; existing cache tests unchanged.

### Phase-06 — Sweep runner, claim lease, billing parity (P7, P8, P16–P20, P27–P31, P36, P37) — ⏳ PLANNED — **closes P0-1**

- [ ] 6.1 Create `apps/api/services/reidentify_claims.py` per P1-AD-8 — exactly two public entry
      points; exact-token release.
- [ ] 6.2 Create `apps/api/services/reidentify_sweep_runner.py` on the `promotion_sweep_runner.py`
      module shape (own `_SWEEP_LOCK_KEY`, `pg_try_advisory_lock` **fail-open**, `run_X_once(db)` +
      `run_X()`, per-row try/except/continue) with the `resolution_runner.py` site enumeration.
- [ ] 6.3 Implement the P1-AD-6 two-pool selection query verbatim. No other selection shape.
- [ ] 6.4 Implement the P1-AD-7 billing parity sequence: `check_usage_allowed` → break; reserve
      re-check → claim → pre-checks → rank → `resolve_auto_retry` → `increment_usage` **once** on a
      non-`None` success before downstream work; exact-token release in `finally`.
- [ ] 6.5 Implement the P1-AD-6 accounting table exactly, including the CR-1 prior-signal row and the
      DR-20 stamp-nothing budget row.
- [ ] 6.6 Log non-PII only: site/visitor id prefixes and counters. **No IP, no email.**
- [ ] 6.7 Add the claim acquire/release to `resolution_runner.py` (P16), `resolution_tasks.py` (P17),
      and `routers/visitors.py` (P18 — before any terminal-state mutation; busy ⇒ 409
      `retry_in_progress` with no state write).
- [ ] 6.8 Apply DR-35 / SN-1 to `agent_company_resolution.py` (P19): plan gate before claim/provider
      work; `increment_usage` once on a non-`None` result before `_upsert_company` / link work;
      synthetic-key claim with exact-token release. **Commit this slice alone** (CR-3).
- [ ] 6.9 Set `deterministic_only=True` in `promotion_sweep_runner.py` (P20) and add the condition
      gate to `tests/integration/test_promotion_sweep.py`.
- [ ] 6.10 Append `apps/api/services/reidentify_sweep_runner.py` to the hardcoded `_AC2_FILES` list at
      `tests/unit/test_agent_company_resolution.py:515-520` — the AC-8 tripwire cannot discover a new
      module otherwise.
- [ ] 6.11 **Create** `tests/integration/test_agent_company_resolution.py` (does not exist today) and
      add the four unit metering/exception cases to `tests/unit/test_agent_company_resolution.py`.
- [ ] 6.12 Add the provider-capable caller census guard to
      `tests/unit/test_resolution_deferral_watermark.py` — every live `IdentityResolver.resolve` source
      must classify as four-human-claim, agent-domain claimant, deterministic-only, or out-of-scope
      with a checked reason (DR-31…DR-33).
- [ ] **Test gate 6 (Fully-Automated + Hybrid):** full unit lane green (baseline 1762 passed / 2
      skipped, DR-40); `.venv/bin/python -m pytest tests/integration/test_reidentify_sweep.py tests/integration/test_reidentify_resolution_leases.py tests/integration/test_agent_company_resolution.py tests/integration/test_visitor_resolve_endpoint.py tests/integration/test_promotion_sweep.py -q`
      green.

### Phase-07 — Flag, scheduler, revive subordination, opt-out API (P21–P25, P34, P35) — ⏳ PLANNED

- [ ] 7.1 Add the `apps/api/config.py` flag block per P1-AD-9 — default **False**.
- [ ] 7.2 Register the scheduler job inside `if settings.auto_reidentify_enabled:` with explicit `id`,
      positive `jitter` / `misfire_grace_time`, and a boot offset **< 90s**.
- [ ] 7.3 Update `tests/unit/test_scheduler_job_config.py:176-223` from 24/21/3 to **25/22/3** with a
      provenance paragraph.
- [ ] 7.4 Add the `revive_returning_unresolvable` flag guard (`visitor_aggregator.py:365-431`) and
      flag-parametrise `tests/integration/test_unresolvable_revive.py:97-120` — flag-OFF assertions
      byte-unchanged, flag-ON revive inert.
- [ ] 7.5 Add `auto_reidentify_opt_out` to `SiteOut` and `SiteUpdate` (`apps/api/schemas/sites.py`)
      and one **independent** `if body.auto_reidentify_opt_out is not None:` in
      `routers/sites.py::update_site` that touches `auto_paused_at` in **neither** direction.
- [ ] **Test gate 7 (Fully-Automated + Hybrid):** scheduler unit test green at 25/22/3; revive
      integration green on both flag branches; `PATCH /sites/{id}` round-trip green with
      `auto_paused_at` unchanged.

### Phase-08 — Full regression + rollout gate — ⏳ PLANNED

- [ ] 8.1 Full unit lane with the flag unset — compare against the DR-40 baseline (1762 passed / 2
      skipped / 0 failed).
- [ ] 8.2 Full integration lane with the flag unset.
- [ ] 8.3 Confirm the only observable flag-OFF changes are the two unconditional slices (CR-3) — no
      third behavior change anywhere.
- [ ] 8.4 Record the eligible-backlog COUNT per site and the distinct-IPs-per-visitor distribution
      **before** any prod flag flip (§Rollout Gate).
- [ ] 8.5 User confirmation before any `✅ VERIFIED` marker.
- [ ] **Test gate 8 (Fully-Automated + Agent-Probe):** both full lanes green; rollout-gate numbers
      recorded in the phase report.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_reidentify_ranker.py::org_over_eyeball` | Fully-Automated | AC-2 (best IP wins) |
| `test_reidentify_ranker.py::relay_excluded` | Fully-Automated | AC-3 (relays never chosen) |
| `test_reidentify_ranker.py::asn_none_short_circuits_to_unknown` — `classify_ip_org_kind` **never called** | Fully-Automated | AC-2 (DR-7; without it the ladder returns `"org"` for everything) |
| `test_reidentify_ranker.py::unknown_ranks_second` | Fully-Automated | AC-2 (DR-8) |
| `test_reidentify_ranker.py::total_order_under_permutation` | Fully-Automated | AC-2/AC-3 (determinism) |
| `test_reidentify_ranker.py::chosen_preserves_last_activity_at` | Fully-Automated | AC-2 (DR-34 provenance carried, not recomputed) |
| `integration/test_reidentify_sweep.py::best_ip_selection` — seeded events; attempted IP is the office IP | Hybrid (PG) | AC-2 |
| `integration/test_reidentify_sweep.py::new_ip_revives` | Hybrid (PG) | AC-4 (untried IP re-opens a failed visitor, no click) |
| `integration/test_reidentify_sweep.py::tried_ip_not_looped` | Hybrid (PG) | AC-5 |
| `integration/test_reidentify_sweep.py::vpn_filtered_pickup` — picked up only on a new non-relay IP | Hybrid (PG) | AC-5 (D4-B) |
| `integration/test_reidentify_sweep.py::cap_enforced` — a 4-attempt visitor is never selected again | Hybrid (PG) | AC-6 (bounded spend) |
| `integration/test_reidentify_sweep.py::skip_consumes_no_attempt_but_advances_next_at` | Hybrid (PG) | AC-6 (cadence + SKIP semantics) |
| `unit/test_reidentify_sweep.py::prior_signal_hit_consumes_no_attempt` | Fully-Automated | AC-7 (**CR-1** — the one rule the AD-7/S3-1 contradiction hinged on) |
| **`unit/test_reidentify_sweep.py::plan_limit_refuses_before_claim_and_provider`** — `check_usage_allowed` False ⇒ no claim, no resolver, no provider, no `increment_usage` | Fully-Automated | AC-8 (**P0-1** monthly-plan gate) |
| **`unit/test_reidentify_sweep.py::success_increments_usage_exactly_once_before_downstream`** | Fully-Automated | AC-8 (**P0-1** meter advances ⇒ the cap is no longer silently raised for other lanes) |
| `unit/test_reidentify_sweep.py::non_success_paths_meter_zero` — busy / budget-refused / SKIP / `provider_unavailable` / raised / prior-signal | Fully-Automated | AC-8 |
| **`unit/test_identity_resolver_parallel.py::override_ip_reaches_graph_orchestrator_mixins`** — leadpipe/capturify/rb2b receive the override, NOT `visitor.ip_address` | Fully-Automated | AC-2 (**P0-2** — the residential-capable tier; without it the feature is a no-op there) |
| `unit/test_identity_resolver_parallel.py::override_ip_reaches_ip_company_orchestrator_mixins` | Fully-Automated | AC-2 (P0-2, pdl/ipinfo leg) |
| `integration/test_reidentify_sweep.py::sweep_does_not_persist_chosen_ip` — fresh session after `expire_all()`; `visitors.ip_address` unchanged on success, outage **and** exception paths | Hybrid (PG) | AC-13 (DR-24 — the override must not be a committed PII write) |
| **`unit/test_resolution_deferral_watermark.py::test_past_the_last_step_repeats_capped_defer_and_never_writes_off`** (replaces `::test_past_the_last_step_writes_off_and_resets`) | Fully-Automated | AC-7 (**P1-4** rule 2) |
| **`unit/test_identity_resolver_parallel.py::per_tier_outage_matrix`** — 4 cells: answered×dead, dead×answered, dead×dead, n/a×n/a | Fully-Automated | AC-7 (**P1-4** rule 1 — an answering tier is never re-dispatched by outage logic) |
| `integration/test_reidentify_sweep.py::provider_unavailable_defers_through_ramp_and_repeats_cap` — force all tiers unavailable through 15m/1h/6h/24h plus one capped repeat; assert zero attempt/count/log/meter accounting and no pre-watermark dispatch | Hybrid (PG) | AC-7 (P1-4 end-to-end) |
| `integration/test_resolution_deferral_sweep.py` (existing) stays green | Hybrid (PG) | AC-12 (no regression on the deferral surface) |
| **`unit/test_reidentify_sweep.py::cache_key_is_site_scoped_only_for_auto_retry`** — exact key string on both branches | Fully-Automated | AC-9 (**P1-5**) |
| **`integration/test_reidentify_sweep.py::site_a_negative_cache_does_not_suppress_site_b`** | Hybrid (PG) | AC-9 (P1-5 behavioural) |
| `integration/test_reidentify_sweep.py::reserve_blocks_second_batch_at_70pct` — seed `attempts_today = 34`; the next `resolve()` is allowed (34 < 35), the one after refused | Hybrid (PG) | AC-10 (DR-19) |
| `integration/test_reidentify_sweep.py::budget_refusal_stamps_nothing` — `count`, `skip_count`, `next_at`, `tried_ips` ALL unchanged; row re-selected next tick | Hybrid (PG) | AC-10 (DR-20 — a refusal must not feed the retirement ledger) |
| `integration/test_reidentify_sweep.py::retries_do_not_exhaust_first_identify_budget` — run to the reserve threshold, then the main sweep still resolves ≥1 `anonymous` visitor | Hybrid (PG) | AC-10 |
| `integration/test_reidentify_sweep.py::paused_site_never_swept` — `tracking_enabled = false`, manual toggle AND auto-pause | Hybrid (PG) | AC-11 (DR-22, commit `b2a7eef`) |
| `integration/test_reidentify_sweep.py::opt_out_site_never_selected` — default-false sites still swept | Hybrid (PG) | AC-11 (DR-23) |
| `integration/test_reidentify_sweep.py::do_not_resolve_never_retried` | Hybrid (PG) | AC-14 (privacy hold honored) |
| `integration/test_reidentify_sweep.py::agent_origin_never_selected` — behavioural, not text-match | Hybrid (PG) | AC-14 (agent-origin exclusion) |
| `unit/test_agent_company_resolution.py` `_AC2_FILES` tripwire **after appending the new sweep module** | Fully-Automated | AC-14 (the hardcoded list cannot discover a new module otherwise) |
| `unit/test_reidentify_sweep.py::no_pii_in_logs` — log-capture assertion, no IP/email in structlog output | Fully-Automated | AC-15 |
| `unit/test_reidentify_sweep.py::exception_advances_next_at` | Fully-Automated | AC-6 (prevents a per-tick hot loop) |
| `integration/test_reidentify_resolution_leases.py::test_four_human_lane_lease_race_identified_once` — manual + APScheduler + Celery + new sweep barrier-race one visitor; exactly one winner, one `IdentifiedVisitor`, only the winner's side effects | Hybrid (PG) | AC-8/AC-13 (DR-31) |
| `integration/test_reidentify_resolution_leases.py::test_four_human_lane_lease_race_no_match_one_distinct_daily_meter_visitor` — assert `get_resolution_attempts_today(...) == 1`, **not** a global `ResolutionLog` row count | Hybrid (PG) | AC-8 (DR-31; avoids a false fixture invariant) |
| **`integration/test_reidentify_resolution_leases.py::test_claim_model_registered_by_create_all_and_cascades`** — insert a claim, delete the parent visitor, fresh session sees zero claims | Hybrid (PG) | AC-13 (**CR-2** + DR-29/DR-30) |
| `integration/test_visitor_resolve_endpoint.py::test_live_claim_returns_retry_in_progress_without_state_write` | Hybrid (PG) | AC-13 (manual 409 contract) |
| **`unit/test_agent_company_resolution.py::test_agent_company_plan_limit_skips_provider_claim_and_downstream`** | Fully-Automated | AC-8a (**SN-1** / DR-35) |
| **`unit/test_agent_company_resolution.py::test_agent_company_success_increments_usage_once_before_downstream`** | Fully-Automated | AC-8a |
| `unit/test_agent_company_resolution.py::test_agent_company_resolver_exception_does_not_meter_and_releases_exact_token` | Fully-Automated | AC-8a |
| `unit/test_agent_company_resolution.py::test_agent_company_downstream_exception_meters_once_releases_exact_token_and_retry_does_not_duplicate` | Fully-Automated | AC-8a |
| `integration/test_agent_company_resolution.py::test_agent_company_same_synthetic_claim_race_meters_once` — **new file** | Hybrid (PG) | AC-8a (reentrancy cannot double-meter) |
| `integration/test_promotion_sweep.py::test_promotion_sweep_is_deterministic_only_and_never_claims_lease` — spies fail if a paid provider or the claim helper is reached | Hybrid (PG) | AC-12 (DR-32) |
| `unit/test_resolution_deferral_watermark.py::TestProviderCapableResolverCallerCensus::test_provider_capable_resolver_census_is_exhaustive` | Fully-Automated | AC-8 (DR-31…DR-33; a new paid path cannot silently evade its claim boundary) |
| `integration/test_reidentify_sweep.py::historical_selected_ip_rejects_current_graph_record_outside_event_window` + `::…allows_graph_record_inside_event_window` — PG-seeded historical X / current Y; never writes `Visitor.last_seen` | Hybrid (PG) | AC-2/AC-13 (DR-34) |
| `unit/test_identity_enrich_correctness.py` matching precedence/fallback — injected activity supersedes visitor activity only when supplied | Fully-Automated | AC-2 (DR-34 unit leg) |
| `unit/test_scheduler_job_config.py:176-223` updated to 25/22/3 with provenance | Fully-Automated | AC-12 (scheduler registration) |
| `integration/test_unresolvable_revive.py:97-120` flag-parametrised — flag OFF byte-unchanged, flag ON revive inert | Hybrid (PG) | AC-1/AC-12 (DR-26, single owner) |
| `PATCH /sites/{id}` with `auto_reidentify_opt_out: true` round-trips `SiteUpdate → update_site → SiteOut`, and `auto_paused_at` is unchanged | Hybrid (PG) | AC-11 (`update_site` copies fields one-by-one; the `tracking_enabled` branch's side effect must not be disturbed) |
| `tests/integration/test_resolution_budget.py::TestResolutionAttemptCounting::test_counts_distinct_visitors_not_rows` stays green | Fully-Automated | AC-12 (budget non-regression) |
| Existing `deterministic_only` invariant in `unit/test_identity_resolver_parallel.py` stays green | Fully-Automated | AC-12 |
| Full unit + integration lanes with the flag unset, compared to the DR-40 baseline | Fully-Automated | AC-1/AC-12 (flag-off invariant apart from the 2 disclosed slices) |
| Migration up→down→up on a **disposable** Postgres, head re-derived live with `DATABASE_URL` pinned to `localhost:5433` | Hybrid (disposable container) | AC-16 |
| Erasure check — deleting the visitor row removes `auto_reidentify_tried_ips` and cascades its claim | Hybrid (PG) | AC-13 |
| Whether a given corporate IP actually resolves via paid providers | Agent-Probe (residual; live-provider double-opt-in policy applies) | AC-17 (explicitly-justified residual) |
| Eligible-backlog COUNT per site + distinct-IPs-per-visitor distribution on real data | **Known-Gap → rollout gate** (backlog stub required; keeps the rollout gate CONDITIONAL) | Quantifies the value of attempts #2–#4 and the cold-start drain time |

**Vacuous-green note:** exactly one row is Known-Gap. It is a **rollout** gate, not a behavior gate,
and it carries a required backlog stub (§Rollout Gate). Every developed behavior above — including
all four P0/P1 fixes — is proven by a Fully-Automated, Hybrid, or Agent-Probe row.

---

## Test Infra Improvement Notes

- The repo has **no freezegun/time-machine** — the ranker takes `now` as a parameter. Adding one
  would simplify every 7-day cadence test.
- **No mmdb in the repo or CI**, so every ranker unit test exercises the `unknown` tier. A fixture
  `.mmdb` (or a shared `lookup_asn` monkeypatch helper) would let the org/eyeball ladder be tested
  for real.
- `_AC2_FILES` in `tests/unit/test_agent_company_resolution.py:515-520` is a **hardcoded list** — it
  cannot discover a new module and nothing warns when a sweep is added. A registry/AST-based
  discovery would end this class of silent miss.
- `tests/unit/test_resolution_deferral_watermark.py`'s sweep discovery is a **string-match
  heuristic** — it silently misses any sweep lacking the literal `identity_status == "anonymous"`.
  This plan strengthens it once; structural (AST) discovery would end the recurring drift.
- `Base.metadata.create_all()` depends on `apps/api/main.py`'s explicit import list, so a mapped
  table referenced only by a lazily-imported service is silently absent from Hybrid fixtures. The
  registration/cascade gate stays mandatory until the repo adopts automatic model discovery.
- `routers/sites.py::update_site` copies fields one-by-one, so a `SiteUpdate` field with no handler
  line is silently dropped and no test catches it. A schema-field-vs-handler parity test over
  `SiteUpdate` would end the class.
- No harness asserts that a **site-level** gate is honored by a sweep; `::paused_site_never_swept`
  and `::opt_out_site_never_selected` will each be built ad hoc. A shared "site-gate matrix" fixture
  would cover both plus the two gates `resolution_runner.py` already has.
- No harness asserts "this SQL puts group A before group B under a LIMIT" — the two-pool allocation
  and the reserve gate are both constructed ad hoc.
- The provider fan-out can write multiple `ResolutionLog` rows for one top-level no-match. Cross-lane
  tests must prove one top-level winner and one **distinct-meter visitor**, never a false global
  "one `ResolutionLog`" invariant.
- `tests/integration/test_agent_company_resolution.py` **does not exist**; the existing mocked unit
  surface cannot prove retained defer state across commits, so the file must be created (P30).
- There is no harness for "assert an exact Redis key string" — P1-AD-5's gate builds one; a shared
  cache-key assertion helper would prevent the `beam:resolution:` class of drift (DR-39).

---

## Open Risks (call these out for VALIDATE)

| # | Risk | Why it is thin / how it is bounded |
|---|---|---|
| R1 | The 70% reserve threshold is unmeasured | Explicitly a **PLACEHOLDER**, tuned before any prod flag flip; same posture as `job_change_recheck_daily_cap`. Too high starves retries; too low starves first-time identifies. |
| R2 | The `skip_count < 8` retirement bound is unmeasured | ~56 days of futile evaluation. A retired single-IP visitor is never re-evaluated even if a new IP later appears — accepted; the reset semantics are **Phase 2**. |
| R3 | `is_privacy_relay_ip` covers only `2a09:bac3:` (iCloud **IPv6**) | So `unresolvable → vpn_filtered` remains reachable via the IPinfo check. Disclosed in Public Contracts. The IPv4 relay gap is **Phase 2** and is why the Retry-button revival is deferred. |
| R4 | Residual TOCTOU on the unlocked daily meter | The main sweep consumes the same counter, so the day total can land a few resolves past 70% (~82% worst case). The guarantee is on when retries *start*. |
| R5 | Accepted N+1: up to ~21 `COUNT(DISTINCT …)` per site per tick | Same site-scoped meter the main sweep already runs; any cached alternative re-opens the leak the check exists to close. |
| R6 | **Cold-start backlog** — at flag flip every eligible visitor has `next_at IS NULL` | Bounded, not eliminated: the NULL pool is capped at 10 rows/site/tick, so a 5,000-row backlog drains in ~21 days at 24 ticks/day. The eligible-backlog COUNT is a named rollout-gate measurement. |
| R7 | **The unconditional outage slice changes behavior with the flag OFF** | Deliberate (CR-3, user Option B). Bounded by: it only ever *reduces* dispatches; it is committed alone and revertable; it is proven by a 4-cell matrix plus an end-to-end ramp gate; the test asserting the old behavior is replaced, not deleted. |
| R8 | **The unconditional agent-company slice is a scope extension** (SN-1) | Narrow, spend-reducing, and un-gateable in principle (a billing limit cannot be flag-gated). Flagged for PVL adjudication; committed alone and revertable. |
| R9 | The legacy negative cache stays cross-tenant for the three default lanes | Deliberately scoped so P1-AD-5 stays inside the flag boundary. Backlogged as Phase-2 item D-7 with the full-repo re-key. |
| R10 | `auto_reidentify_tried_ips` JSONB has no index | It appears in no predicate and no ORDER BY; read per-row on ≤20 already-materialised rows. **Standing guard: never put `jsonb_array_length(...)` in an ORDER BY.** |
| R11 | No `apps/web` surface in Phase 1 ⇒ the opt-out toggle is API-only | Operators can `PATCH /sites/{id}`. **The web toggle is a prod-enable precondition**, tracked as Phase-2 item D-6. |

---

## Acceptance Criteria

1. **(REWRITTEN per CR-3 — the old "no new behavior observable anywhere" is SUPERSEDED.)** With
   `auto_reidentify_enabled = False`, the ONLY observable behavior changes anywhere in the system are
   the two disclosed unconditional slices: (a) the per-tier outage verdict + no-write-off change
   (P1-AD-4), and (b) agent-company monthly-plan parity + success metering (SN-1). Every other
   surface is byte-identical: the job is unregistered, the ranker/claim/sweep modules are never
   called, `resolve()` receives all three defaults, `revive_returning_unresolvable` behaves as today,
   and the new columns sit unread. No third behavior change is permitted; Phase-08 step 8.3 proves it.
2. With the flag ON, a visitor seen from an office-classified and a residential-classified IP is
   attempted on the **office** IP.
3. A privacy-relay IP is never the attempted IP when a non-relay IP is known.
4. A previously-failed (`unresolvable` **or** `vpn_filtered`) visitor who later appears from a
   never-tried non-relay IP is automatically re-attempted with no dashboard click.
5. An IP already in `tried_ips` is never re-attempted.
6. A visitor is evaluated at most once per 7 days; a cycle with no untried IP consumes **no
   attempt**; after **4** consumed attempts the visitor is never selected again. **Qualified:** "4
   attempts ⇒ 4 distinct IPs" holds only when new IPs arrive at ≥7-day intervals. A perpetual skipper
   retires after 8 skips.
7. `provider_unavailable`, a pre-check miss, a `_check_prior_signals` hit (CR-1), or an exception
   consumes **no** attempt and appends **no** `tried_ips` entry. On provider-unavailable the resolver
   retains its defer watermark, caps it, and re-arms 24h — it **never** writes the visitor off and
   never clears the watermark; an answering tier's verdict is respected and never re-dispatched by
   outage logic. An exception additionally advances `next_at`.
   **`visitors.ip_address` is never written by this feature on any path.**
8. The new sweep observes `check_usage_allowed` **before** claim and provider work, and calls
   `increment_usage` **exactly once** on a claimed non-`None` success before downstream work. Busy,
   budget-refused, SKIP, `provider_unavailable`, raised, and prior-signal paths meter **zero**. The
   four human lanes cannot same-key double-dispatch; a busy claim produces no side effect.
8a. An agent-company row passes the canonical monthly-plan check after synthetic materialization and
   defer eligibility, before claim/provider work. A blocked / missing-site / missing-owner row makes
   no resolver, provider, claim, upsert, link, or meter side effect and logs only safe ids/counters.
   A pre-success resolver exception meters zero and releases its exact token; a post-success
   downstream exception keeps the one increment, releases its token, and a retry adds no duplicate.
9. Site A's `__none__` negative-cache entry cannot suppress site B's automatic-retry dispatch. The
   cache key is exactly `resolution:{site_id}:{ip}` for automatic retries and exactly
   `resolution:{ip}` for every other caller.
10. Auto-retries **stop starting** once a site reaches `attempts_today >= ceil(0.70 × budget)`
    (threshold **35** at the default 50), re-evaluated before every individual `resolve()`. **A
    budget refusal stamps nothing.** The main sweep still resolves ≥1 `anonymous` visitor after
    retries have run. Disclosed bound: concurrent main-sweep interleaving can land the day total a
    few resolves past 70%.
11. A site with `tracking_enabled = false` (manual **or** inactivity auto-pause) or with
    `auto_reidentify_opt_out = true` is never selected and consumes no budget. `auto_reidentify_opt_out`
    defaults to **false** and round-trips `SiteUpdate → update_site → SiteOut` without disturbing
    `auto_paused_at`.
12. Existing invariants stay green: distinct-visitor budget meter; `deterministic_only` never
    consults the budget and never reaches the graph orchestrator; promotion sweep cannot reach a paid
    provider or the claim helper; the existing deferral integration surface is unregressed.
13. `identity_status` gains **no new value**; the five readers listed in DR-25 are provably
    unaffected. The manual endpoint returns 409 `retry_in_progress` against a live claim with no
    state write. Deleting a visitor cascades its claim row to zero.
14. Agent-origin and `do_not_resolve` visitors are never selected.
15. No IP and no email appears in structlog output from any new path.
16. The migration round-trips down→up on a **disposable** Postgres, chained off a **live-derived**
    head, with the claim table dropped before the parent columns on downgrade.
17. The rollout-gate measurements (eligible-backlog COUNT per site; distinct-IPs-per-visitor
    distribution) are recorded **before** any prod flag flip.
18. **User confirms** the observable behavior before any phase is marked ✅ VERIFIED.

---

## Rollback

| Situation | Action |
|---|---|
| Gated behavior wrong in dev/prod | Flip `auto_reidentify_enabled` to **False**. The job unregisters at next boot; revive resumes; `resolve()` receives all three defaults; the new columns become inert data. **No code revert needed for this surface.** |
| **Per-tier outage slice wrong** | **REVERT THE COMMIT** — this slice is NOT flag-gated (CR-3). It must be committed alone (step 4.6) so `git revert` restores the old OR + write-off without touching anything else. The replaced watermark test reverts with it. |
| **Agent-company billing slice wrong** | **REVERT THE COMMIT** — likewise unconditional (SN-1), committed alone (step 6.8). |
| Schema must go | The migration is additive and reversible — `alembic downgrade -1` with `DATABASE_URL` pinned local. Dropping the columns loses only attempt bookkeeping; the claim table drops first. |
| Budget burn observed | Flag OFF is the immediate lever; the 50/site/day cap, the monthly plan gate, and the 70% reserve are the standing backstops. Per-site: `PATCH /sites/{id}` with `auto_reidentify_opt_out: true` without touching the global flag. |

**Rollback of the gated surface is zero-cost only because DR-24 holds.** Under a
`visitor.ip_address`-assignment design, flipping the flag OFF would un-gate
`revive_returning_unresolvable`, whose snapshot (`visitor_aggregator.py:345-359`) would hold the
**corrupted** IP while the upsert wrote the real latest IP (`:315`) — so `pre_snapshot.get(vid) != new_ip`
(`:402`) would be True for every touched visitor, mass-flipping them to `anonymous` (`:415`) and
DELETEing failed `ResolutionLog` rows (`:417-423`), defeating both the 30-day gate and the daily
meter. With `override_ip` no corruption occurs. `::sweep_does_not_persist_chosen_ip` is therefore a
rollback gate as well as a correctness gate.

---

## Rollout Gate (named, CONDITIONAL)

Before any prod `auto_reidentify_enabled = True`:

1. Record the **eligible-backlog COUNT per site** (the P1-AD-6 base predicate, counted, flag OFF) so
   the operator sees the cold-start drain time before the flip, not after (R6).
2. Record the **distinct-IPs-per-visitor distribution** for the terminal population — this
   quantifies whether attempts #2–#4 are worth anything at all.
3. Tune the 70% reserve from measured per-site data (R1).
4. Ship the web opt-out toggle (Phase-2 item D-6) or confirm the operator will use
   `PATCH /sites/{id}`.

Both measurements are Known-Gap at plan time; the backlog stub is
`process/features/visitors-identity/backlog/ip-best-selection-phase2-deferred_NOTE_13-08-26.md`.

---

## Deferred to Phase 2

Excluded from this plan by locked scope. Full detail:
`process/features/visitors-identity/backlog/ip-best-selection-phase2-deferred_NOTE_13-08-26.md`.

| ID | Item | Blocked on |
|---|---|---|
| D-1 | `vpn_filtered` Retry button revival | `is_privacy_relay_ip` IPv4 coverage (R3) — today the button would be dead for the relay-dominated surviving population |
| D-2 | Relay/VPN accounting contract | the predecessor's Public Contracts `:175` and S3-1 `:1919` contradict on whether a relay exit counts an attempt; needs one decision |
| D-3 | `auto_reidentify_skip_count` reset semantics | a single-IP visitor retires at 8 skips and is excluded even when new org-tier IPs later appear |
| D-4 | Manual-retry leftover-`anonymous` | `routers/visitors.py:911-914` flips terminal → `anonymous` before `resolve()`; a subsequent budget refusal leaves the row permanently `anonymous` and outside the sweep's status set |
| D-5 | `provider_unavailable` budget-stamp accounting beyond P1-AD-4 | the distinct-visitor meter still counts an outage-only attempt |
| D-6 | Web UI: "tried N/4" counter, `VisitorOut.auto_reidentify_count`, site-settings opt-out toggle | Phase 1 is backend-only; flag OFF means nothing is observable. **D-6 is a prod-enable precondition (R11).** |
| D-7 | Full-repo negative-cache re-key (site-scope the three default lanes) | changes behavior for every lane, so it cannot ride inside this plan's flag boundary (R9) |

---

## Resume and Execution Handoff

1. **Selected plan file path:**
   `process/features/visitors-identity/active/ip-best-selection-phase1_13-08-26/ip-best-selection-phase1_PLAN_13-08-26.md`
2. **Last completed phase or step:** none — plan written 13-08-26; all 8 phases ⏳ PLANNED.
3. **Validate-contract status:** **PENDING.** This is a new artifact; PVL has never run against it.
   The predecessor's cycle-7 `Gate: BLOCKED` does not transfer — it applied to a different file.
   A fresh PVL from V1 is required before EXECUTE.
4. **Supporting context files loaded:**
   - `process/features/visitors-identity/active/ip-best-selection-retrigger_09-08-26/ip-best-selection-retrigger_SPEC_09-08-26.md`
   - `process/features/visitors-identity/active/ip-best-selection-retrigger_09-08-26/ip-best-selection-retrigger-pvl-iteration-003_REPORT_13-08-26.md`
   - `process/context/all-context.md`
   - `process/context/tests/all-tests.md`
   - `process/development-protocols/communication-standards.md`
5. **Next step for a fresh agent picking up mid-execution:**
   - Run `vc-context-discovery` + `vc-plan-discovery` (feature `visitors-identity`) first.
   - Read §Decision Record and §Contradiction Resolutions **before** any other section — they are
     the reason this plan exists. Never re-open a DR row or re-litigate a CR winner.
   - **Re-derive every `path:line` anchor in §Touchpoints** — concurrent plans hold unexecuted edits
     to `identity_resolver.py` and `visitor_aggregator.py`.
   - **Re-derive the alembic head live** with `DATABASE_URL` pinned to `localhost:5433` (DR-38).
     The repo `.env` points at Supabase PROD and `migrations/env.py` has no local-host guard.
   - Detect Docker by port (`lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`), not `which docker`.
   - Start at the first unchecked box in Phase-01 and run that phase's test gate before advancing.
   - Keep steps 4.6 and 6.8 in their **own commits** — rollback of the unconditional slices depends
     on it.

---

## Validate Contract

Status: BLOCKED
Date: 13-08-26
date: 2026-08-13
generated-by: inner-pvl: phase-1

Parallel strategy: sequential (single validate-agent; no Agent tool available in this
environment, so the designed Layer 1 / Layer 2 fan-out ran sequentially against live source —
same coverage limitation recorded at predecessor cycle 7)
Rationale: signal count 5/7 (multi-package NO; schema/API/auth YES; 3+ directions YES;
phase-program NO; user-depth YES; high-risk class YES; 5+ files YES). Dominant signal:
high-risk class (schema migration + billing + paid-provider spend + identity/PII).

Verification performed live at HEAD `372e00b` (the plan cites `3e2ddb5`; `git diff 3e2ddb5..HEAD`
is EMPTY for `identity_resolver.py`, `visitor_aggregator.py`, `routers/visitors.py`, so the
one-commit drift is immaterial). Alembic head re-derived with `DATABASE_URL` pinned to
`localhost:5433`: **`f4b9d2a71c68`** — matches DR-38 exactly. Docker/PG 5433/Redis 6379 live via
`lsof`. Unit lane collects **1764** at HEAD = DR-40's 1762 passed + 2 skipped — baseline VALID.

### Test gates (C3 5-column table)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-2 | best untried IP is chosen, deterministically | Fully-Automated | `.venv/bin/python -m pytest tests/unit/test_reidentify_ranker.py -q` (`::org_over_eyeball`, `::unknown_ranks_second`, `::total_order_under_permutation`, `::asn_none_short_circuits_to_unknown`) | B |
| AC-2 / P0-2 | `override_ip` reaches BOTH orchestrators and all 5 IP-reading mixins | Fully-Automated | `pytest tests/unit/test_identity_resolver_parallel.py -q` (`::override_ip_reaches_graph_orchestrator_mixins`, `::override_ip_reaches_ip_company_orchestrator_mixins`) | B |
| AC-2 / P0-2 | `override_ip` reaches the `:733` cross-tenant `_write_through_company_graph` call with the IP that was actually queried | **NO GATE — undeveloped** | none (defect F1) | B — plan must add the rule + gate |
| AC-3 | privacy-relay IP never chosen | Fully-Automated | `pytest tests/unit/test_reidentify_ranker.py::relay_excluded -q` | B |
| AC-4 / AC-5 / AC-6 | untried-IP revive, no re-loop, cap + cadence + SKIP | Hybrid (PG 5433) | `pytest tests/integration/test_reidentify_sweep.py -q` (`::new_ip_revives`, `::tried_ip_not_looped`, `::cap_enforced`, `::skip_consumes_no_attempt_but_advances_next_at`) | B |
| AC-7 / CR-1 | prior-signal hit consumes no attempt | Fully-Automated | `pytest tests/unit/test_reidentify_sweep.py::prior_signal_hit_consumes_no_attempt -q` | B |
| AC-7 / P1-4 rule 1 | per-tier outage verdict — an answering tier is never re-dispatched | Fully-Automated | `pytest tests/unit/test_identity_resolver_parallel.py::per_tier_outage_matrix -q` (4 cells) | B |
| AC-7 / P1-4 rule 2 | capped re-defer, never written off | Fully-Automated | `pytest tests/unit/test_resolution_deferral_watermark.py -q` (`::test_past_the_last_step_repeats_capped_defer_and_never_writes_off`, REPLACING live `::test_past_the_last_step_writes_off_and_resets` at `:340`) | B |
| AC-7 / P1-4 | aggregate daily-budget consumption under a SUSTAINED full outage (1 dispatch/24h/visitor forever vs today's bounded 4) | **NO GATE — undeveloped** | none (defect F2) | B — plan must bound + gate |
| AC-8 / P0-1 | monthly-plan gate before claim/provider; `increment_usage` exactly once | Fully-Automated | `pytest tests/unit/test_reidentify_sweep.py -q` (`::plan_limit_refuses_before_claim_and_provider`, `::success_increments_usage_exactly_once_before_downstream`, `::non_success_paths_meter_zero`) | B |
| AC-8 / DR-31 | four human lanes cannot same-key double-dispatch | Hybrid (PG 5433) | `pytest tests/integration/test_reidentify_resolution_leases.py -q` | B |
| AC-8a / SN-1 | agent-company plan gate + metering | Fully-Automated | `pytest tests/unit/test_agent_company_resolution.py -q` (4 new metering/exception cases) | **C — adjudicated needs-change (defect F5); the `increment_usage` half must be re-decided before a gate is written** |
| AC-9 / P1-5 | cache key exactly site-scoped for `auto_retry`, legacy otherwise | Fully-Automated | `pytest tests/unit/test_reidentify_sweep.py::cache_key_is_site_scoped_only_for_auto_retry -q` | B |
| AC-9 / P1-5 | site A `__none__` cannot suppress site B | Hybrid (PG 5433) | `pytest tests/integration/test_reidentify_sweep.py::site_a_negative_cache_does_not_suppress_site_b -q` | B |
| AC-9 / D-7 | the auto lane has ZERO dedup against its own site's prior negative result on the same IP (30-day gate bypassed AND key space diverged) | **NO GATE — undeveloped** | none (defect F4) | B — plan must disclose + bound + gate |
| AC-10 | 70% reserve; a budget refusal stamps nothing | Hybrid (PG 5433) | `pytest tests/integration/test_reidentify_sweep.py -q` (`::reserve_blocks_second_batch_at_70pct`, `::budget_refusal_stamps_nothing`, `::retries_do_not_exhaust_first_identify_budget`) | B |
| AC-11 | paused / opted-out site never swept; `PATCH` round-trip leaves `auto_paused_at` alone | Hybrid (PG 5433) | `pytest tests/integration/test_reidentify_sweep.py -q` (`::paused_site_never_swept`, `::opt_out_site_never_selected`) + the `PATCH /sites/{id}` round-trip | B |
| AC-12 | existing invariants unregressed | Fully-Automated | `pytest tests/unit -m unit -q` (1762 passed / 2 skipped baseline) + `pytest tests/integration/test_resolution_deferral_sweep.py tests/integration/test_resolution_budget.py tests/integration/test_promotion_sweep.py -q` | A (baseline re-measured green this cycle: 1764 collected) |
| AC-13 / DR-24 | `visitors.ip_address` never written | Hybrid (PG 5433) | `pytest tests/integration/test_reidentify_sweep.py::sweep_does_not_persist_chosen_ip -q` | B |
| AC-13 | manual endpoint 409 `retry_in_progress` **with no state write** | Hybrid (PG 5433) | `pytest tests/integration/test_visitor_resolve_endpoint.py::test_live_claim_returns_retry_in_progress_without_state_write -q` | **B — currently UNSATISFIABLE at the claim placement P18 prescribes (defect F3)** |
| AC-13 / CR-2 | claim table created by `create_all`, parent delete cascades | Hybrid (PG 5433) | `pytest tests/integration/test_reidentify_resolution_leases.py::test_claim_model_registered_by_create_all_and_cascades -q` | B |
| AC-14 | agent-origin + `do_not_resolve` never selected | Hybrid (PG 5433) | `pytest tests/integration/test_reidentify_sweep.py -q` (`::agent_origin_never_selected`, `::do_not_resolve_never_retried`) | B |
| AC-15 | no IP / no email in structlog from any new path | Fully-Automated | `pytest tests/unit/test_reidentify_sweep.py::no_pii_in_logs -q` | B |
| AC-16 | migration up→down→up on a DISPOSABLE Postgres, head live-derived | Hybrid (disposable container) | `docker run --rm -d postgres:16-alpine` then `DATABASE_URL=<disposable> .venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head` → `downgrade -1` → `upgrade head` | B |
| AC-17 | whether a given corporate IP actually resolves via paid providers | Agent-Probe | live-provider probe; `cost-class: needs-live-provider` — double opt-in required, NOT auto-granted | C (explicitly-justified residual) |
| AC-17 (rollout) | eligible-backlog COUNT per site; distinct-IPs-per-visitor distribution | Known-Gap (named residual) | — | D — backlog stub on disk: `process/features/visitors-identity/backlog/ip-best-selection-phase2-deferred_NOTE_13-08-26.md` ✓ verified present |

gap-resolution legend: A proven now · B fixed in this plan · C deferred to a named later phase · D backlog test-building stub.

Legacy line form:
- ranker: [Fully-automated: `.venv/bin/python -m pytest tests/unit/test_reidentify_ranker.py -q`]
- resolver params / override_ip / outage: [Fully-automated: `.venv/bin/python -m pytest tests/unit/test_identity_resolver_parallel.py tests/unit/test_resolution_deferral_watermark.py tests/unit/test_identity_enrich_correctness.py -q`]
- sweep accounting / billing / cache key / logs: [Fully-automated: `.venv/bin/python -m pytest tests/unit/test_reidentify_sweep.py tests/unit/test_agent_company_resolution.py -q`]
- scheduler: [Fully-automated: `.venv/bin/python -m pytest tests/unit/test_scheduler_job_config.py -q` — live counts are 24/21/3, plan's 25/22/3 arithmetic VERIFIED correct]
- sweep selection / leases / PG behavior: [hybrid: `.venv/bin/python -m pytest tests/integration/test_reidentify_sweep.py tests/integration/test_reidentify_resolution_leases.py tests/integration/test_agent_company_resolution.py tests/integration/test_visitor_resolve_endpoint.py tests/integration/test_promotion_sweep.py tests/integration/test_unresolvable_revive.py -q` + precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis` (PG 5433, Redis 6379 — both LIVE, verified via `lsof`)]
- migration round-trip: [hybrid: alembic up→down→up + precondition: a DISPOSABLE `postgres:16-alpine`, never the shared dev container; `DATABASE_URL` pinned]
- live corporate-IP resolvability: [agent-probe: needs-live-provider, double opt-in]
- rollout measurements: [known-gap: documented, backlog stub present]

### Dimension findings

- Infra fit: CONCERN — every one of the 30 existing referenced paths exists; the 2 absent ones (`tests/integration/test_agent_company_resolution.py`, `tests/unit/test_reidentify_ranker.py`) are correctly declared as new-create targets. Alembic head, Docker/PG/Redis, `ix_events_site_visitor`, the 90s `aggregation_sweep` offset, the 24/21/3 scheduler counts, and the 1762+2 unit baseline all VERIFIED exact. BUT `visitor_aggregator.py` anchors are stale by ~+10 lines throughout (`latest_ip` is `:324` not `:315`; `revive_returning_unresolvable` is `:375` not `:365`; `pre_snapshot.get(vid) != new_ip` is `:412` not `:402`; `identity_status="anonymous"` is `:425` not `:415`; `delete(ResolutionLog)` is `:428-432` not `:417-423`) and BOTH `config.py` style-precedent anchors are wrong (`:622-647` is the outlier-damping block, not promotion sweep; `:722-731` is promotion-window + graph-erasure, not ip-org). The file is byte-identical to `3e2ddb5`, so these anchors were never re-derived — falsifying §Touchpoints' opening assertion.
- Test coverage: CONCERN — coverage is dense and non-vacuous (exactly one Known-Gap row, correctly a rollout gate with a real on-disk backlog stub). Gaps: (a) step 6.11 creates a brand-new PG-backed integration file with ZERO fixture-shape guidance, in a feature whose measured failure mode was invented model fields — verified live that `IdentifiedVisitor` has NO `first_seen`/`last_seen` and `Site` has `name`+`url` with NO `domain`; (b) the `_AC2_FILES` row is over-claimed — live it is `assert "human_only_visitor_filter" in text`, a literal string-presence check, not agent-origin proof (behavioural proof exists separately via `::agent_origin_never_selected`); (c) three behaviors have NO gate at all (F1, F2, F4 below).
- Breaking changes: FAIL — the unconditional outage slice's own disclosure table and R7 state the change "only ever *reduces* dispatches"; this is FALSE in the full-outage direction (see F2). Plus F3's contradictory claim placement.
- Security surface: CONCERN — PII posture is genuinely strong: DR-24 verified against a resolver that commits on every exit path; `auto_retry` provably does NOT bypass `do_not_resolve` (`:590`), suppression (`:600`), budget (`:631`), no-IP (`:635`), relay (`:644`) or the IPinfo VPN check (`:653`) — all six are separate statements before/after the single `:625` line it bypasses (DR-37 CONFIRMED). Erasure inherits via the empirically-proven composite-FK CASCADE. BUT the `:733` `_write_through_company_graph(self.db, visitor.ip_address, company_domain, ...)` call writes a **cross-tenant durable** `CompanyGraphNode` row at `source="paid_ip"`, `confidence=0.7` keyed on the WRONG IP under override (F1) — cross-tenant data-integrity, not a leak, but it poisons an asset every tenant reads.
- Section: Decision Record (DR-1…DR-40) — PASS. Spot-verified live: DR-7 (`lookup_asn` → `(None, None)` with no mmdb; `classify_ip_org_kind(None, …)` → `"org"`, and its signature is typed `asn: int` so `None` is also a type violation — the mandatory short-circuit is load-bearing and correct), DR-11 (`is_privacy_relay_ip` is iCloud-v6-prefix-only), DR-19 (`get_site_daily_budget(db, site_id)` / `get_resolution_attempts_today(db, site_id)` exist as cited), DR-22 (`resolution_runner.py:260`), DR-27, DR-29 (`uq_visitors_site_visitor` non-partial at `models/visitor.py:18`), DR-31 (synthetic `agent:{AgentVisit.id}` at `:52`, `is_agent_derived=True` at `:69`), DR-35 (census re-run live: `check_usage_allowed`/`increment_usage` imported at `agent_company_resolution.py:44` and NEVER called; donor sequence `resolution_runner.py:161→172→178` EXACT), DR-37, DR-38, DR-39, DR-40. No DR contradicts live source.
- Section: Contradiction Resolutions (CR-1…CR-3) — PASS. Each names one winner, marks the loser SUPERSEDED, and states one normative rule. CR-1's premise verified (`_check_prior_signals` at `:294`, called `:608`, before the `:625` gate). CR-2's FK target verified. CR-3's flag-OFF invariant is internally coherent.
- Section: Phase-01 / 02 / 07 / 08 — PASS. Mechanically feasible; every edit target uniquely matchable.
- Section: Phase-03 (resolver params) — CONCERN. `:544 :590 :600 :608 :625 :631 :635 :644 :653 :677 :694 :709 :801 :841 :973 :994` ALL verified exact; all 8 mixin/orchestrator signature rows verified exact. Highest-risk edit: the `effective_ip` substitution list is incomplete (F1).
- Section: Phase-04 (per-tier outage) — FAIL. The redesign IS implementable against `tier_verdict()` at `:99-112` with no new column exactly as claimed (verified: three-valued return; the `applicable`/`is_outage` computation and the `min(count, len-1)` delay index both reproduce stages 15m/1h/6h/24h then repeat at the cap). But the consequence is unanalysed and mis-disclosed (F2).
- Section: Phase-05 (site-scoped cache) — FAIL. Key string and prefix verified (`:694`, `REDIS_RESOLUTION_PREFIX = "resolution:"` at `identity_providers/base.py:16`). The D-7 scoping creates an undisclosed duplicate-spend path (F4).
- Section: Phase-06 (sweep + claim + billing) — FAIL. Base predicate is coherent (verified `resolution_candidate_filter` / `resolution_intent_filter` / `human_only_visitor_filter` / `resolution_not_deferred_filter` impose NO `identity_status` predicate, so `IN ('unresolvable','vpn_filtered')` is not self-contradictory). But F3 (claim placement) and F5 (SN-1 metering) both land here. Additional CONCERN: the two-pool `ORDER BY` drops `resolution_runner.py:112`'s `internal_override.is_distinct_from("internal")` damping term, so the ONE new lane orders by raw `intent_score DESC` — re-entering the measured pattern where <20 heavy/self-traffic visitors ate 37.5% of a site's identify budget.

### Open gaps

1. **F1 (FAIL) — `override_ip` never reaches the cross-tenant company-graph write-through.** `identity_resolver.py:733-737` runs INSIDE `resolve()` after the ip-company orchestrator: `if settings.company_graph_enabled and visitor.ip_address: await _write_through_company_graph(self.db, visitor.ip_address, company_domain, None, "paid_ip", 0.7)`. The domain came from `effective_ip`; the key written is `visitor.ip_address`. On the auto lane those differ by construction, so every successful auto-retry writes a WRONG `IP → company_domain` pair into the durable **cross-tenant** `company_graph` at confidence 0.7, which `company_resolver.py` then serves to every other tenant for up to `company_graph_staleness_days` (75). The plan's effective-IP substitution list (P9, P1-AD-3 normative rule, step 3.3) enumerates `:635 :644 :653 :677 :694 :709` and **omits `:733`/`:737`**. This is a REGRESSION from the superseded plan — cycle 7 recorded "`_write_through_company_graph` risk mapped and covered" among the claims its adversarial verifier could not refute. No gate exists. Required: add `:733`/`:737` to the effective-IP rule, add the anchor to P9, and add a gate asserting the graph row is keyed on the queried IP (or that the write-through is suppressed when `override_ip` is set).
2. **F2 (FAIL) — the unconditional outage slice is unbounded in the full-outage direction, and R7's bound claim is false.** Today: 4 defers then `identity_status = "unresolvable"`, which removes the visitor from both sweeps' `anonymous` population — total 4 dispatches, then zero forever. Under P1-AD-4 rule 2 the visitor is NEVER written off and a fresh 24h watermark is re-armed on every later full outage — 1 dispatch per 24h per visitor, forever, each consuming a daily distinct-visitor budget slot (D-5 explicitly defers fixing that meter). §Terminal-state change says "Net effect is **fewer** paid dispatches"; R7 says the slice "only ever *reduces* dispatches"; AC-1(5a)/CR-3 ship it with the flag OFF for all four lanes. Both statements hold only for the mixed-verdict case; for a genuinely full outage the direction INVERTS and the aggregate is unbounded — with a 50/day budget and a few thousand eligible rows the budget saturates on outage retries and no first-time identify ever runs. Required: either add an outage-repeat bound / eventual terminal, or replace the false "only ever reduces" claim with an honest signed disclosure plus a gate on aggregate budget behavior under sustained full outage.
3. **F3 (FAIL) — claim placement in `routers/visitors.py` is self-contradictory, and AC-13's "no state write" is falsifiable.** P9/P18 say "acquire the claim after `check_usage_allowed` (`:953`) and **before** any retryable terminal-state mutation or `resolve(force_retry=…)` (`:960`)"; step 6.7 says only "before any terminal-state mutation". Verified live: the retryable terminal-state mutation `visitor.identity_status = "anonymous"` is at **`:914`** — 39 lines BEFORE `:953`. So P18 as written is mechanically unsatisfiable, and the two body statements prescribe DIFFERENT code (claim at `:952` vs claim before `:911`), with different observable behavior in the four-lane race (whether a claim is held while the intent/privacy/plan gates run). Worse, the `:953` placement falsifies AC-13's "409 `retry_in_progress` with no state write": `check_usage_allowed` itself calls `await db.commit()` when `user.billing_cycle_reset_at is None`, and `reset_monthly_usage` commits on a month rollover (`billing.py:118`, `:124`) — so on a first-ever or new-month billing check the `:914` mutation is COMMITTED before the 409 is returned, leaving the row permanently `anonymous` and outside the sweep's status set. That is exactly the deferred D-4 leftover-`anonymous` bug, newly reachable through a path this plan itself adds. Required: pick ONE placement in the body, and make AC-13's promise match it.
4. **F4 (FAIL) — the D-7 cache scoping leaves the auto lane with ZERO dedup, undisclosed.** `auto_retry=True` bypasses `was_recently_attempted` (`:625`, the 30-day `ResolutionLog` gate) AND reads/writes `resolution:{site_id}:{ip}` while every other lane reads/writes `resolution:{ip}`. The two key spaces never intersect, so the auto lane cannot see its OWN site's legitimate `__none__` written by that site's default lane; and because `tried_ips` records only IPs the auto lane spent, an IP the default lane already proved negative is a valid auto-lane candidate. Both dedup mechanisms are therefore off simultaneously and the auto lane pays for a duplicate provider dispatch on an IP the same site already resolved negative — a spend INCREASE on the primary new path. §P1-AD-5 discloses only the residual cross-tenant leak for the three default lanes. Required: disclose and bound it (e.g. write BOTH keys on a negative auto-lane result so the legacy space stays warm, capping the duplicate at one per site+IP), or pull the full re-key (D-7) into Phase 1, plus a gate.
5. **F5 (FAIL / adjudication) — SN-1's `increment_usage` half is not sound as unconditional parity.** See the SN-1 adjudication below.
6. CONCERN — `visitor_aggregator.py` anchors stale by ~+10 lines and both `config.py` style-precedent anchors wrong, despite §Touchpoints asserting every anchor was re-derived live at `3e2ddb5` (the file is byte-identical to `3e2ddb5`, so they were never re-derived). Low blast radius (the edit is one guard in a uniquely-named function) but it is the same claim-vs-reality class that ended the predecessor.
7. CONCERN — step 6.11 creates a new PG-backed integration file with no fixture-shape guidance. Verified live: `IdentifiedVisitor` (in `apps/api/models/visitor.py:190`) has NO `first_seen`/`last_seen`; `Site` has `name`+`url` and NO `domain`. The feature's own `backlog/docker-gate-run-findings_NOTE_07-08-26.md` records 8 of 14 integration gates blocked on exactly these invented fields. Add the real fixture shapes to step 6.11.
8. CONCERN — the `_AC2_FILES` Verification-Evidence row over-claims: live it is `assert "human_only_visitor_filter" in text` (string presence), and its list spans `:513-521` not the cited `:515-520`. Relabel as a rename tripwire; AC-14's behavioural proof is `::agent_origin_never_selected`.
9. CONCERN — the two-pool `ORDER BY` omits `resolution_runner.py:112`'s `internal_override.is_distinct_from("internal").desc()` damping term. A site with `internal_damping_enabled = true` gets damping in every lane EXCEPT this new one, re-entering the measured self-traffic budget-eating pattern. Either carry the term or state why the new lane deliberately does not.
10. CONCERN — `resolution_candidate_filter(...)` is written with elided arguments in the P1-AD-6 base predicate, but step 6.3 says "implement verbatim". Live it needs `all_us_site_ids` (from `site_resolves_all_us(site.url)`) and `no_floor_site_ids` (from `first_win_boost_site_ids(db, [site_id])`). Name both.
11. CONCERN — R11 / D-6 assert "D-6 is a prod-enable **precondition**" while §Rollout Gate step 4 offers "ship the toggle **or** confirm the operator will use `PATCH /sites/{id}`". Pick one rule.
12. Known-gap (documented, EXCLUDED from the gate count) — rollout-gate measurements (eligible-backlog COUNT per site; distinct-IPs-per-visitor distribution). Backlog stub verified present at `process/features/visitors-identity/backlog/ip-best-selection-phase2-deferred_NOTE_13-08-26.md`.
13. Known-gap (documented, EXCLUDED) — AC-17 live corporate-IP resolvability: `cost-class: needs-live-provider`, double opt-in required, not auto-granted.

### PVL adjudications requested by the plan

**SN-1 (agent-company monthly-plan parity as a second unconditional slice) — NEEDS-CHANGE. Split it.**
- The `check_usage_allowed` half is **SOUND** and should ship unconditionally: it is fail-closed, purely spend-reducing, and the census confirms the lane is the only provider-capable lane with no plan gate (`agent_company_resolution.py:44` imports both helpers and calls neither).
- The `increment_usage` half is **NOT sound as unconditional parity.** `check_usage_allowed`/`increment_usage` operate on `User.monthly_identified_count` vs the plan limit (free 10 / pro 50) — the customer's monthly IDENTIFIED-PERSON quota. Every row this lane produces carries `source_agent_visit_id`, and `identity_classification.py:142-144` refuses emailability on that marker FIRST and unconditionally. So metering agent rows charges the customer's paid quota for rows they can never contact, and — because the meter is shared — directly REDUCES the human identifications they bought. A free-tier site receiving 10 agent visits would have its entire monthly human quota consumed by non-emailable rows, with no flag, no UI, and no disclosure.
- The plan's justification transfers V1's "frozen counter silently raises the effective cap" argument from the new sweep to this lane, but the premise does not transfer: the new sweep's rows ARE emailable humans, so metering them is correct there.
- SN-1's claim that both slices are "spend-**reducing** correctness fixes that widen nothing" is therefore false for this half — it narrows what the customer receives, which is a customer-visible billing change, a different risk class from the outage fix.
- Required: pick ONE and write it in the body — (a) ship `check_usage_allowed` unconditionally and explicitly do NOT `increment_usage` for agent-derived rows, documenting the asymmetry and its rationale; (b) meter agent visits against a separate counter; or (c) flag-gate the metering half and surface the decision to the user. Option (a) is the smallest change consistent with every other invariant in this plan.

**D-6 (web UI descoped to Phase 2 as a prod-enable precondition) — SOUND, one wording fix.**
Descoping is correct and self-consistent: with the flag OFF nothing is observable, so a Phase-1 UI would be untestable, and the "tried N/4" counter needs columns that only carry data after the flag flips. The opt-out is genuinely reachable — P24/P25 ship `SiteUpdate`/`SiteOut` + an independent `update_site` branch, and the live `routers/sites.py:329-389` one-by-one copy confirms both the need for the explicit branch and the `auto_paused_at` hazard the plan calls out. Only defect: R11/D-6 say "precondition" while §Rollout Gate step 4 says "toggle **or** operator `PATCH`". Keep the Rollout-Gate "or" (an authenticated owner-scoped PATCH is a legitimate operator surface) and downgrade R11/D-6 from "precondition" to "usability follow-up; operator PATCH is the accepted Phase-1 surface."

**D-7 (negative-cache site-scoping applied only to the auto_retry lane) — NEEDS-CHANGE.**
The *direction* is right and the flag-boundary reasoning is legitimate: re-keying all four lanes is a behavior change for every lane and cannot ride inside a flag-OFF-invariant plan, so deferring the full re-key is defensible. Two things must change before it is safe:
1. The disclosure is incomplete in the costly direction. §P1-AD-5 and R9 disclose only the residual cross-tenant leak for the default lanes. They do not disclose that the auto lane simultaneously loses its 30-day `was_recently_attempted` gate (bypassed by `auto_retry`) AND its own site's negative-cache visibility (diverged key space) — leaving it the ONLY lane with zero dedup against a same-site prior negative on the same IP. See F4.
2. It must be bounded and gated. Minimal fix consistent with the flag boundary: on a negative auto-lane result write BOTH `resolution:{site_id}:{ip}` and the legacy `resolution:{ip}` (read site-scoped only), which caps the duplicate at one dispatch per site+IP and keeps the default lanes' behavior byte-identical. Add `::auto_retry_negative_result_seeds_both_keys` alongside the existing exact-key-string gate.

### What this coverage does NOT prove

- The Fully-Automated ranker gates run with NO mmdb in the repo or CI, so `lookup_asn` returns `(None, None)` for every input and every ranker test exercises the `unknown` tier only. The org / eyeball / cdn / datacenter ladder ordering is NOT proven by any gate — only the `asn is None → "unknown"` short-circuit is.
- `::override_ip_reaches_graph_orchestrator_mixins` proves the override reaches the three mixins' own queries. It does NOT prove the override reaches the `:733` cross-tenant `company_graph` write-through (F1), nor that the existing log lines at `:648`/`:700`/`:703` stop reporting `visitor.ip_address` while a different IP was queried.
- `::per_tier_outage_matrix` + `::test_past_the_last_step_repeats_capped_defer_and_never_writes_off` prove per-call outage semantics. They do NOT prove anything about AGGREGATE dispatch or daily-budget consumption across many visitors over many days under a sustained full outage (F2), and they do not prove the direction claim in R7.
- `::site_a_negative_cache_does_not_suppress_site_b` proves cross-tenant suppression is closed for the auto lane. It does NOT prove the auto lane still benefits from its OWN site's prior negative result (F4) — no gate covers same-site duplicate dispatch.
- `::test_live_claim_returns_retry_in_progress_without_state_write` cannot pass at the claim placement P18 prescribes when `user.billing_cycle_reset_at is None` or on a month rollover, because `check_usage_allowed` commits (F3). A green result would mean the fixture never exercised those two branches.
- The `_AC2_FILES` tripwire proves only that the literal string `human_only_visitor_filter` appears in the new module's text. It proves NO behavior.
- The full-lane regression gates prove the DR-40 baseline is unmoved. They do NOT prove the flag-OFF invariant (AC-1) beyond the two disclosed slices — step 8.3 is a review assertion, not a mechanical gate; nothing greps for a third unconditional behavior change.
- The Hybrid PG gates run against the local dev Postgres on `localhost:5433`. They prove nothing about Supabase PROD, where `company_graph_enabled` and every other flag in this surface remain OFF and the prod alembic head must be re-checked independently.
- No gate proves the 70% reserve threshold or the `skip_count < 8` bound are the right NUMBERS — both are explicitly labelled placeholders (R1, R2).
- AC-17's live-provider probe was NOT run this cycle: `cost-class: needs-live-provider` requires double opt-in, which was not granted, so the verdict for "does a given corporate IP actually resolve" is INCONCLUSIVE.
- **Coverage limitation:** this validate-agent has no Agent tool in this environment, so the designed Layer 1 / Layer 2 parallel fan-out could not run internally. All dimensions were covered sequentially against live source at HEAD `372e00b`. At predecessor cycles 2, 6 and 8 an orchestrator-spawned external adversarial verifier found the top defect that sequential passes missed — recommend pairing one with the next cycle.

Gate: BLOCKED (5 unresolved FAILs: F1 cross-tenant graph write-through under override; F2 unbounded full-outage re-dispatch with a false bound claim; F3 contradictory claim placement + falsifiable AC-13; F4 undisclosed same-site duplicate spend; F5 SN-1 metering unsound. 8 CONCERNs. 2 known-gaps EXCLUDED from the count per §Known Gaps rule.)
Accepted by: n/a — Gate is BLOCKED, not CONDITIONAL. No concern was accepted by user or session this cycle. Self-acceptance is forbidden.

---

## Autonomous Goal Block

```
SESSION GOAL: Phase 1 of best-IP re-identify — rank a visitor's known IPs, spend 4 lifetime
automatic attempts (one per 7 days) on distinct best-untried IPs, and close four spend/correctness
defects: no monthly-plan gate on the new lane, override_ip never reaching the residential-capable
providers, a cross-tenant negative IP cache, and a write-off during partial provider outage.
Charter + umbrella plan: N/A — single plan (COMPLEX, 8 phases, one file; explicitly NOT a phase
program; no umbrella with a Stable Program Goal governs it).
Autonomy: /goal autonomous execution per process/development-protocols/orchestration.md
§Autonomy Mode. Self-decide at V5 gates. BLOCKED → backlog note + continue. Subagent delegation
stays mandatory: the orchestrator never edits source and never runs gate commands itself.
Hard stop conditions / safety constraints:
- Never run alembic or any DB script without DATABASE_URL pinned to localhost:5433 or a
  disposable container DSN. The repo .env points at Supabase PROD and migrations/env.py has NO
  local-host guard, so a bare alembic command applies DDL to production.
- Migration round-trips run on a DISPOSABLE postgres:16-alpine only. Never docker exec into the
  shared dev container or the shared dev Postgres.
- Never assign visitor.ip_address or visitor.last_seen. resolve() commits on every exit path, so
  any assignment is a committed write to a plaintext PII column (DR-24, DR-34).
- Steps 4.6 and 6.8 each go in their OWN commit — the two unconditional slices are not
  flag-gated and rollback is a git revert, not a flag flip.
- auto_reidentify_enabled ships default False. Flipping it in any real environment is a separate
  explicit operator action after the Rollout Gate measurements are recorded.
- The live-provider feasibility probe (AC-17) is billed: needs-live-provider requires explicit
  double opt-in. Never auto-grant.
- Read-only git for validate and fix agents. No rebase, stash, checkout, or commit outside the
  named commit steps.
Next phase: RETURN TO PLAN — vc-plan-agent PVL-supplement mode addressing the 5 FAILs + 8
CONCERNs in the SUPPLEMENT REQUEST block, then re-spawn vc-validate-agent from V1.
Validate contract: inline in
process/features/visitors-identity/active/ip-best-selection-phase1_13-08-26/ip-best-selection-phase1_PLAN_13-08-26.md
§Validate Contract (Gate: BLOCKED, generated-by inner-pvl: phase-1, 2026-08-13).
Execute start: NOT AUTHORISED — gate is BLOCKED. When it clears:
[fully-auto] .venv/bin/python -m pytest tests/unit -m unit -q
[hybrid] docker compose -f infra/docker-compose.yml up -d postgres redis && .venv/bin/python -m pytest tests/ -m integration -q
[e2e spec] n/a — no apps/web surface in Phase 1
[probe scenario] AC-17 corporate-IP resolvability (needs-live-provider, double opt-in)
high-risk pack: yes — schema migration + billing/credits + identity/PII + paid-provider spend
```

---

## Next Step

PVL from V1 against this file. EXECUTE is not authorised until the gate clears. When it does, the
orchestrator emits the `/goal` block and the user says **ENTER EXECUTE MODE** with this exact plan
path.
