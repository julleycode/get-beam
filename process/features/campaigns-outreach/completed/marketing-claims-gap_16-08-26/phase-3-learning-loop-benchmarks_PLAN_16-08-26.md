---
name: plan:marketing-claims-gap-phase-3-learning-loop-benchmarks
description: "Marketing Claims Gap — Phase 3: measured campaign performance fed back into planning prompts, plus a zero-PII cross-tenant category benchmark"
date: 16-08-26
metadata:
  node_type: memory
  type: plan
  feature: campaigns-outreach
  phase: phase-3
---

# Phase 3 — Learning Loop + Benchmarks

**Program:** marketing-claims-gap
**Umbrella plan:** `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/marketing-claims-gap-umbrella_PLAN_16-08-26.md`
**Date**: 16-08-26
**Complexity**: COMPLEX
**Status**: 🔨 CODE DONE
**Report destination:** `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-3-learning-loop-benchmarks_REPORT_16-08-26.md`

---

## Overview

Beam's copy says campaigns "learn and adjust automatically." Today the raw material exists —
`CampaignTouchpoint.sent_at/opened_at/clicked_at`, SendGrid open/click webhooks, the `Conversion`
table, `/outcomes/{site_id}/report`, `EngagementAttribution` per utm_tag — but nothing reads it
back into planning. Nothing benchmarks a site against comparable sites either.

This phase makes the claim true in the only shape compatible with Beam's brand stance: measured
stats flow into the **planner and auto-drafter prompts** and into the **Monday outcome digest**.
Drafts still go through human approval. Nothing about a live campaign is auto-adjusted, and nothing
is auto-sent.

Two hazards drive the design.

**Hazard 1 — measurement honesty.** Campaign opens/clicks are recorded UNGATED: `open_pixel.py`
stamps `opened_at`, and `events.py:801-853` stamps `clicked_at`/`opened_at` from the `_tp` link
param. Neither touches a feature flag. (`webhooks.py:85`'s `identity_signals_enabled` gate covers
only `record_signal()` → the `IdentitySignal` table — identity corroboration, unrelated to campaign
measurement. `outcomes.py:281-330` already aggregates sent/opened/clicked ungated.) The real hazards
are therefore: (a) **no sends vs measured zero** — a site with zero sends must render "no data", not
"0% open rate"; and (b) **open-rate unreliability** — per `open_pixel.py:6-9`, Apple Mail Privacy
Protection prefetches images (overcount) and image blocking suppresses the pixel (undercount), so
clicks are the reliable signal and every open-rate surface must carry that caveat.

**Hazard 2 — cross-tenant sharing.** A benchmark is a new data-sharing surface; the safe shape is
aggregates with zero PII, which makes GDPR erasure moot rather than adding another table for
`graph_erasure.py` to sweep. It also requires its OWN purpose-scoped consent (see D3).

Context: `process/context/all-context.md` (router), `process/context/tests/all-tests.md`,
`process/features/campaigns-outreach/_GUIDE.md`,
`process/features/visitors-identity/active/identity-coop_07-08-26/` (reuse its privacy invariants).

---

## Entry Gate

- Phase 1 exit gate passed — this phase consumes the "Demo booked" conversion signal Phase 1
  introduces.
- Local Postgres reachable on `:5433` (`lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`).
- Phase 2 is NOT required. If Phase 2 shipped, `icp_fit` may be included as an additional reported
  dimension; if not, omit it.

**MANDATORY PRE-EDIT RULE (PVL cycle 3, N4) — concurrent uncommitted work occupies this phase's targets:**

1. **Re-read `apps/api/models/site.py`, `apps/api/routers/sites.py`, `apps/api/schemas/sites.py`, and `apps/api/agents/campaign_planner.py` IMMEDIATELY before editing them.** All four differ from HEAD and have TWO concurrent churn sources: (a) the site-analysis-onboarding program holds uncommitted changes to `models/site.py` (new `site_profile` / `site_profile_candidate` JSONB columns and `site_profile_status`) and a large uncommitted delta to `routers/sites.py`; (b) **Phase 1 of this program** touches `agents/campaign_planner.py` and the conversion-goal surface. Do not edit from a cached read. **NO LINE NUMBER in this plan for `routers/sites.py` is trustworthy** — every citation there is stale by hundreds of lines; locate code BY SYMBOL, never by line. **Append** `benchmark_contribution_enabled` rather than inserting inside the site-analysis block.
2. **Before writing the migration:** re-run `alembic heads` LIVE with `DATABASE_URL` pinned to `localhost:5433`, AND check whether the **untracked** revision `apps/api/migrations/versions/c5e1a9b73d20_add_site_profile.py` has been applied to the target DB (`SELECT version_num FROM alembic_version;`). An untracked revision can move the head between plan-write and EXECUTE. Chain off the TRUE live head only.
3. **FORBIDDEN:** `git stash`, `git stash pop`, `git checkout --`, `git revert`, `git rebase`, or any other command that would discard or relocate the concurrent program's uncommitted work. Read-only git only. If the worktree state blocks progress, STOP and report — do not clean it.

---

## Locked Decisions

| # | Decision | Alternative considered (rejected) |
|---|---|---|
| D1 | Benchmark table stores ONLY `(category_normalized, period, sends, opens, clicks, conversions, site_count)`. **Zero PII, zero site_id, zero visitor reference.** This makes GDPR erasure moot by construction. **The only statistic this schema supports is a pooled ratio — a category AVERAGE (mean). All copy says "category average"; the word "median" is banned** (sums + a tenant count cannot yield a median). Extending the schema with distribution stats is explicitly rejected: it re-opens the privacy analysis for a cosmetic gain. | A site_id-keyed ledger (identity-coop's shape) — rejected here: unnecessary for aggregates, and it would create a new surface `graph_erasure.py` must sweep. |
| D2 | **k-floor = `site_count >= 5`.** A category with fewer than 5 contributing sites produces NO row. Rationale: `traffic_fit.py:31` uses `MIN_SAMPLE=50` for per-site sample size, but that is a different unit (events, not tenants). Beam is a young product with a handful of sites per category; k=50 tenants would yield zero rows forever, i.e. a feature that never ships. k=5 is the smallest floor that still prevents a single-tenant readback. Revisit upward as tenant count grows. | k=50 sites — rejected: guarantees buckets-of-zero. k=2 or 3 — rejected: too easy to infer a competitor's numbers. |
| D3 | **NEW distinct opt-in flag `Site.benchmark_contribution_enabled`** (nullable, default `False`, additive migration) with its own explicit opt-in surface. A site that has not opted in contributes nothing and its numbers never enter any aggregate. Write-nothing-when-blocked, per identity-coop's invariant. **Consent audit decision, LOCKED (orchestrator decision, PVL cycle 2, C11): the flag flip is AUDITED via the existing structlog audit pattern — event `benchmark_contribution_toggled` with `site_id`, `user_id`, and the new boolean value, no PII. No new acceptance table and no `terms_version` coupling.** Rationale: benchmark data is a zero-PII, k≥5 aggregate, so a structlog audit line is proportionate; identity-coop's `identity_contribution_consent_acceptances` table exists because that flag authorizes PII-bearing cross-tenant identity sharing against specific policy text — a heavier artifact for a heavier purpose. Rationale: `Site.contribution_enabled` is purpose-scoped to the identity co-op — in `apps/api/routers/sites.py`, the block beginning `if body.contribution_enabled is not None:` (locate BY SYMBOL — line numbers are stale, see Entry Gate) requires `terms_version == settings.coop_terms_version` and writes an `identity_contribution_consent_acceptances` audit row against that exact policy text. Reusing it for campaign-performance aggregation is a purpose-limitation breach. **Do not touch the co-op terms or `contribution_enabled` in this phase.** | (a) Reusing `Site.contribution_enabled` — rejected: purpose-limitation breach, enrolls sites in a purpose they never saw. (b) A rewritten combined `terms_version` covering both purposes — rejected: forces re-acceptance on every existing co-op site and couples this phase to identity-coop Phase 3's `coop_terms.py` version history. |
| D4 | **Stat injection targets `apps/api/agents/campaign_planner.py` `CAMPAIGN_PLANNING_PROMPT` (`:16`) ONLY.** `apps/api/services/auto_drafter.py` (NOTE: it lives under `services/`, NOT `agents/`) is explicitly EXCLUDED: it is a SOCIAL-REPLY drafter (module docstring — generates a comment/reply to an identified visitor's recent social post via `ai_reply.generate_draft`; `:143` is the `_generate_draft_text` def, prompt context is `context_hint` at `:159-163`). Email-campaign metrics are semantically unrelated to a social reply and would degrade draft quality. | Injecting into `apps/api/services/auto_drafter.py` as well — rejected: category error (email metrics into a social-reply prompt). |
| D4b | Category normalization: a small controlled vocabulary + a deterministic pure mapper (`normalize_category`). `Site.category` is free text `String(100)`, so raw grouping yields buckets-of-one. Unmappable categories map to `"other"` and are still counted (never dropped silently). | LLM categorization — rejected: nondeterministic grouping key. Raw free-text grouping — rejected: buckets-of-one defeat the k-floor. |
| D5 | Weekly **APScheduler** job (`jobs/scheduler.py`, 24 existing jobs), flag-gated + try/except + a structlog crash line, matching the existing job pattern. NOT Celery. | Celery task — rejected: the scheduled-sweep pattern in this repo is APScheduler. |
| D6 | Learning loop v1 = (a) inject per-site measured stats into `campaign_planner.CAMPAIGN_PLANNING_PROMPT` (`:16`) — **and nowhere else** (see D4); (b) add a benchmark line to the Monday digest; (c) add a ranked "what's working" panel to the outcomes report. Drafts still require approval. | Auto-adjusting live campaign cadence/subject lines — **rejected, permanently out of scope for this program.** |
| D7 | The benchmark line reports the **category average** (pooled mean), never a median (D1). The Monday digest (`outcome_digest.send_weekly_outcome_digests`, cron at `jobs/scheduler.py:842-847`, `outcomes_digest_enabled` default OFF) is the natural host for the benchmark line. `build_digest_email` is PURE and unit-tested — extend it purely, keep the advisory lock and the 6-day throttle via `Site.last_outcome_digest_sent_at` untouched. The digest is built to be forwardable, so it must stay PII-free. | A new email — rejected: another send surface for no gain. |
| D8 | **Reply tracking is OUT OF SCOPE.** No reply model exists anywhere in the repo; building one is its own phase. Write a backlog note. | Inferring replies from SendGrid events — rejected: SendGrid does not report inbound replies on this integration. |
| D9 | New flag `campaign_benchmark_enabled`, default OFF. Every test gate names its flag-ON precondition explicitly. | Shipping ON — rejected: violates the program's flag posture. |

---

## Blast Radius

Risk class: schema/migration (one new table) + **cross-tenant data aggregation** (highest-risk
element of the program) + public API contract (additive report fields). No auth, no billing.
The send path is READ-ONLY and regression-gated.

- `apps/api/models/campaign_benchmark.py` — NEW table (D1 shape)
- `apps/api/migrations/versions/<new>_add_campaign_benchmark.py` — new revision
- `apps/api/services/campaign_stats.py` — NEW: per-site rollup, pure where possible
- `apps/api/services/campaign_benchmark.py` — NEW: `normalize_category` (pure) + the aggregation job body
- `apps/api/jobs/scheduler.py` — register the weekly job
- `apps/api/services/outcome_digest.py` — benchmark line in `build_digest_email` (pure)
- `apps/api/agents/campaign_planner.py` — stats injected into the planning prompt (SOLE injection site)
- `apps/api/models/site.py` — NEW `benchmark_contribution_enabled` column (D3); same migration as C2
- `apps/api/routers/sites.py` — additive opt-in field on the site-update body (benchmark-scoped; co-op consent path UNTOUCHED)
- `apps/api/routers/outcomes.py` — "what's working" ranked panel data + import of the shared count expressions (B2a)
- `apps/api/config.py` — NEW `campaign_benchmark_enabled` flag (D9), default OFF (precedent: `outcomes_digest_enabled` at `config.py:183`, `identity_signals_enabled` at `:922`)
- `apps/api/schemas/sites.py` — `SiteUpdate` (`:48`) gains the additive benchmark opt-in field for C0, AND `SiteOut` (`:39`) `field_validator(..., mode="before")` must be extended to coerce `None → False` for the new nullable `benchmark_contribution_enabled` (same fail-safe treatment as `contribution_enabled`/`internal_damping_enabled`)
- `apps/api/schemas/outcomes.py` — `OutcomesReportResponse` (`:130-134`) gains D2's additive `whats_working` / optional `benchmark` fields
- `apps/web` — outcomes report panel
- `tests/unit/test_campaign_benchmark.py`, `tests/unit/test_normalize_category.py`,
  `tests/unit/test_outcome_digest_benchmark.py`, `tests/integration/test_campaign_benchmark_job.py` — NEW

Approx 12 files + 1 migration (`apps/api/services/auto_drafter.py` — under `services/`, NOT `agents/` — is NOT touched, D4).

---

## Touchpoints

Same as Blast Radius. Read-only touchpoints: `apps/api/routers/open_pixel.py` (ungated `opened_at`
stamp + the MPP/image-blocking caveat at `:6-9`), `apps/api/routers/events.py:801-853` (ungated
`_tp` click/open stamp), `apps/api/routers/outcomes.py:281-330` (existing funnel aggregation,
refactor target per B5), `apps/api/routers/sites.py` (co-op consent path — the `if body.contribution_enabled is not None:` block through its
`coop_terms_version` check and `identity_contribution_consent_acceptances` write; located BY SYMBOL, not by line —
read-only, MUST NOT be modified), `apps/api/models/outcome.py`,
`apps/api/services/campaign_sender.py` (send gate — inspected for the regression test only),
`process/features/visitors-identity/active/identity-coop_07-08-26/` (privacy invariants),
`apps/api/services/traffic_fit.py:31` (k-floor precedent), `apps/api/config.py`,
`apps/api/schemas/sites.py`, `apps/api/schemas/outcomes.py` (all three now WRITE touchpoints — see Blast Radius).

---

## Public Contracts

- `DigestStats` (`outcome_digest.py:43-48`) is UNCHANGED — no `opened` field is added; open-rate data rides inside the new keyword-only benchmark argument.
- New table `campaign_benchmarks` — contains no PII, no site identifier, no visitor reference.
- New additive `Site.benchmark_contribution_enabled` column + additive opt-in field on the site-update
  body. `Site.contribution_enabled` and the co-op consent path are UNCHANGED.
- `build_digest_email` gains a **keyword-only argument with a default**; its positional signature
  (`site_name, stats, visitors=()`) and its `tuple[str, str]` return shape are unchanged.
- `/api/v1/outcomes/{site_id}/report` gains additive fields (`whats_working`, optional
  `benchmark`). No field removed or retyped.
- `build_digest_email` remains PURE and its existing unit tests must still pass unchanged.
- The Monday digest remains forwardable — no PII added.
- `campaign_sender.send_campaign_emails` is UNCHANGED and remains reachable only after human
  approval. Prompt injection changes affect DRAFT generation only.
- With `campaign_benchmark_enabled=False`, no job runs, no rows are written, and the digest and
  report render exactly as today.

---

## Implementation Checklist

### Step A — Category normalization

- [x] A1. **The vocabulary is AUTHORED in this plan/code as a controlled list — it is not enumerable from any existing source.** Verified (PVL cycle 2): (a) no onboarding category option list exists — `grep -rn category apps/web/src` returns only unrelated costs/changelog categories and `api-types.ts:122` types it as free `string`; (b) the site-analysis path is unbounded model free text, not a vocabulary — `site_analysis.py:171` prompts for `"category": "<= 100 chars"` and `:288` stores whatever comes back. Therefore: SAMPLE both surfaces for coverage (does the authored list cover what they actually emit?), do not treat either as the source of truth. The local dev DB is a freshly-migrated 0-row database — a read-only query is a sanity check only. Record in the phase report what was actually found, explicitly including that source (a) does not exist. Design safety is unaffected: D4b's `"other"` bucket catches everything unmapped and nothing is dropped.
- [x] A2. Define a small controlled vocabulary (target ~8-15 buckets) covering those values, plus `"other"`.
- [x] A3. Implement `normalize_category(raw: str | None) -> str` — pure, deterministic, case/whitespace insensitive, returns `"other"` for unknown or `None`. No LLM.
- [x] A4. Note in the module docstring that this mapper is intended to be reusable by `agents/segmenter.py` later; do not wire it there in this phase.

### Step B — Per-site stats rollup

- [x] B1. Implement `apps/api/services/campaign_stats.py`: for a site and a period, compute sends / opens / clicks / conversions from `CampaignTouchpoint` (`sent_at`/`opened_at`/`clicked_at`) and `Conversion`.
- [x] B2. **LOCKED refactor shape (orchestrator decision, PVL cycle 3, N2 — do not re-litigate during EXECUTE).** `campaign_stats.py` exports TWO things:
  - **(a) Shared SQL count expressions** — the `sent` / `opened` / `clicked` `func.count().filter(...)` predicates, factored out as reusable expressions (e.g. `sent_count_expr(cutoff)`, `opened_count_expr(cutoff)`, `clicked_count_expr(cutoff)`). `/outcomes` **imports and reuses these expressions inside its existing grouped aggregate** (`outcomes.py:282-310`) — it does NOT switch to fetching rows into Python. Its no-row-materialization shape, its per-campaign `group_by(Campaign.id, Campaign.name)`, and its query cost are all preserved exactly. "Single funnel definition" means **one predicate set**, not one Python function.
  - **(b) A PURE `summarize(rows, *, channel: str | None = None) -> CampaignStats`** used by the **BENCHMARK path ONLY** — a bounded weekly per-site row fetch, whose materialization cost is accepted because it is an offline weekly job over one site's period, not an authed request path. The benchmark rollup calls it with `channel="email"`; `channel=None` remains available but `/outcomes` does not use it.
  - **`conv_rows` (`outcomes.py:316-330`, the `Conversion` counts merged in Python) is explicitly OUT OF SCOPE of this refactor.** Leave it exactly as it is. B1's conversion count is the benchmark path's own concern.
- [x] B3. Distinguish **no sends** from **measured zero**: with 0 sends the rollup returns "no data" (never "0% open rate"); with N sends and 0 opens it returns a measured 0. Do NOT gate any of this on `identity_signals_enabled` — that flag does not touch campaign open/click (see Overview Hazard 1).
- [x] B3b. Attach an unreliability caveat to every open-rate value the rollup emits, citing `open_pixel.py:6-9` (Apple MPP prefetch overcounts; image blocking undercounts; clicks are the reliable signal). Surfaces must render the caveat, not bury it.
- [x] B4b. The BENCHMARK rollup passes `channel="email"` to `summarize`. **This filter is DEFENSIVE / FORWARD-LOOKING, not a fix for a live bug (PVL cycle 3, N1).** As of this plan, **no application path emits a non-email touchpoint**: `campaign_sender.py:397` is the SOLE `CampaignTouchpoint(` constructor in all of `apps/api` and hardcodes `channel="email"`; social channels exist only as `Campaign.plan` dicts (`campaigns.py:160`). The filter protects the invariant against future social-send work — the column is free `String(50)` (`models/campaign.py:64`) and the unique constraint is `(campaign_id, visitor_id, channel)`, so social rows are structurally permitted. `CampaignType` (`models/campaign.py:12-16`) already names `social_reply`/`social_dm`/`paid_ads`. Assert the filter in the rollup unit test. ⚠️ **HARD SCOPE GUARD:** do NOT "fix" `campaign_sender.py` to emit social touchpoint rows in order to make B5b's fixture producible. The send path is READ-ONLY in this phase (E1/AC-10); modifying it is a scope breach and a BLOCKED condition. **Citation correction (PVL cycle 2):** the real `channel == "email"` filters live at `campaigns.py:215`, `campaigns.py:245`, and `campaign_sender.py:347` — NOT `outcomes.py:215` (which is `select(`). `grep -n channel apps/api/routers/outcomes.py` returns **zero matches**: `/outcomes` has never filtered on channel, which is exactly why `/outcomes` must keep calling `summarize` unfiltered.
- [x] B5. `campaign_stats.py` is the **single definition of the campaign funnel** — as a shared PREDICATE SET (B2a), not as a shared Python function. Refactor `outcomes.py:282-310` to import the three shared count expressions in the same change, keeping its grouped-aggregate shape and per-campaign grouping intact (no row materialization, no behavior change, no cost change). Existing `/outcomes` response values must be unchanged (regression-asserted: compare the `/outcomes` response before and after the refactor). The shared expressions must reproduce `outcomes.py`'s existing asymmetry exactly: `sent` carries `status == "sent"` AND `sent_at >= cutoff`, while `opened`/`clicked` carry only their `is_not(None)` predicate plus `sent_at >= cutoff`. `conv_rows` is untouched.
- [x] B5b. The `/outcomes` regression fixture MUST contain at least one `social_reply` or `social_dm` touchpoint. Without one the "values unchanged" assertion is vacuously green — a channel filter leaking into the `/outcomes` path would go undetected. **That row is CONSTRUCTED DIRECTLY VIA THE ORM in the fixture. No application path produces one, and that is EXPECTED — do not go hunting for a producer and do not create one (see B4b's scope guard).**
- [x] B4. Include a `demo_booked` count derived from the Phase 1 "Demo booked" conversion goal, when present.

### Step C — Benchmark table + job

- [x] C0. Add `Site.benchmark_contribution_enabled` (nullable, default `False`) in the same revision as C1, plus an explicit benchmark-scoped opt-in surface on the site-update path. **Emit a structlog audit line `benchmark_contribution_toggled` (site_id, user_id, new value; no PII) on every flip — this is the consent artifact (D3), and no acceptance table is created.** Do NOT read, write, or re-scope `Site.contribution_enabled`, `terms_version`, or `identity_contribution_consent_acceptances`.
- [x] C0b. **Schema plumbing for C0 (easily-missed failure mode, PVL cycles 3-4, N3):** in `apps/api/schemas/sites.py` (locate BY SYMBOL — line numbers are stale, see Entry Gate) do BOTH of the following, in this order:
  - **(i) DECLARE the field on `SiteOut`:** add `benchmark_contribution_enabled: bool = False`, mirroring the existing `contribution_enabled: bool = False` declaration.
  - **(ii) THEN add its name to the existing `SiteOut` `@field_validator(..., mode="before")`** (currently `("internal_damping_enabled", "contribution_enabled")`) so `None → False`.
  - ⚠️ **(ii) WITHOUT (i) is a hard import failure, not a soft bug.** Pydantic v2 raises at CLASS-DEFINITION time when a `field_validator` names a field that is not declared, so `apps/api/schemas/sites.py` would fail to import and every route importing it would 500 at startup. Never add the validator name alone.
  - **(iii)** add the opt-in field to `SiteUpdate` in the same file (NOT inline in `routers/sites.py`).
  - Without the (i)+(ii) coercion, readback of any `Site` row predating the migration will error instead of failing safe. Also declare `campaign_benchmark_enabled` (default `False`) in `apps/api/config.py` — every gate's flag precondition depends on it existing.
- [x] C1. Define `apps/api/models/campaign_benchmark.py` with exactly the D1 columns: `category_normalized`, `period`, `sends`, `opens`, `clicks`, `conversions`, `site_count`, plus `id`/`created_at`/`updated_at`. Unique on `(category_normalized, period)`. **No site_id, no visitor reference, no email, no free text from a tenant.**
- [x] C2. Re-derive the live head FIRST (`DATABASE_URL` pinned to `localhost:5433`; Phases 1 and 2 each landed a revision). Chain the new revision off the LIVE head, never a recorded one.
- [x] C3. Live round-trip on `:5433`: `upgrade head` → `downgrade -1` → `upgrade head`. Never bare alembic — repo `.env` points at Supabase PROD.
- [x] C4. Implement the weekly aggregation in `apps/api/services/campaign_benchmark.py`: for each site with `benchmark_contribution_enabled = True` (D3 — NOT `contribution_enabled`), compute its period stats, group by `normalize_category(site.category)`, sum, and count contributing sites.
- [x] C5. Enforce the k-floor: **write no row for a category whose `site_count < 5`.** Discard, do not write a suppressed/partial row.
- [x] C6. Write-nothing-when-blocked: a site with `benchmark_contribution_enabled` false/NULL contributes nothing and leaves no trace anywhere (not even a skipped-site counter keyed by site).
- [x] C7. Register the job in `apps/api/jobs/scheduler.py` following the existing pattern: flag-gated on `campaign_benchmark_enabled`, wrapped in try/except, with a structlog crash line. Weekly cadence, scheduled clear of the Monday digest cron so the digest reads fresh rows.

### Step D — Surfaces

- [x] D1. **`DigestStats` MUST NOT be mutated.** `outcome_digest.py:43-48` is `DigestStats(sent, clicked, conversions, attributed, attributed_revenue_cents)` — it has NO `opened` field, and the digest has never rendered an open rate. The open-rate value (and its MPP caveat) travels INSIDE the new keyword-only benchmark argument, not as a new `DigestStats` field; extending `DigestStats` would be an undeclared shape change to a second public structure and would force a change in its producer `send_weekly_outcome_digests`. Extend `outcome_digest.build_digest_email` (PURE) with a **keyword-only benchmark argument carrying a default** (existing positional signature `site_name, stats, visitors=()` and the `tuple[str, str]` return shape must not change) rendering an optional benchmark line: "your open rate vs the {category} average". Render nothing when the flag is off, when no benchmark row exists, or when the site has not opted in. Keep the existing unit tests passing unchanged. The word "median" must not appear (D1).
- [x] D2. Add a ranked "what's working" panel to `/api/v1/outcomes/{site_id}/report` — ranked by **campaign and segment ONLY**, derived from `campaign_stats`. Additive fields only. **Subject-line ranking is a NAMED DEFERRAL, decided now (orchestrator decision, PVL cycle 2 — the previous mid-EXECUTE conditional is deleted; nothing about this is resolved during EXECUTE).** The panel copy must say campaign/segment, never "subject". Both extraction paths are verified and recorded here for the follow-up phase, so no rediscovery is needed:
  - `CampaignTouchpoint.content['subject']` — the RENDERED subject actually sent, written at `campaign_sender.py:403` as `content={"subject": subject}`.
  - `Campaign.plan` touchpoints carrying `"subject"` — planned (not necessarily sent) subject; schema at `campaign_planner.py:75`, read at `campaign_sender.py:64` and `:213`.
  Either path, when built, must pass the tenant-derived subject text through `clean_text` per D5.
- [x] D3. Inject the site's measured stats into `campaign_planner.CAMPAIGN_PLANNING_PROMPT` (`:16`) as context ("your last N sends had X% open, Y conversions; the highest-converting segment was Z"). Drafts remain drafts.
- [x] D4. **REMOVED (D4 decision):** no injection into `apps/api/services/auto_drafter.py` (under `services/`, NOT `agents/`). It is a social-reply drafter; campaign metrics do not belong in its prompt. `campaign_planner` is the sole injection site.
- [x] D5. Any tenant-derived free text entering a prompt (e.g. subject lines) must pass through `agents/prompt_safety.py` (`clean_text` / `wrap_untrusted`). Note that `sanitize_profiles` only covers its fixed field table — new fields pass through unsanitized, so use `clean_text` per field.
- [x] D6. Add the web panel for D2 in the outcomes report view.

### Step E — Safety + backlog

- [x] E1. Regression test: assert no code path added in this phase reaches `campaign_sender.send_campaign_emails`. The learning loop writes PROMPTS and REPORTS only.
- [x] E2. Privacy test: assert the `campaign_benchmarks` model has no column referencing a site, visitor, or email, and that a written row round-trips with no tenant-identifying value.
- [x] E2b. Add a privacy note to this plan's record and the phase report: published aggregates are **irreversible under GDPR erasure** (a conversion already summed cannot be un-counted) — acceptable by design because the rows are k-anonymous and PII-free, so `graph_erasure.py` has nothing to sweep. **Period-differencing risk:** when a category hovers near the k-floor, comparing consecutive periods can narrow an individual tenant's numbers. Mitigations, both required: (1) suppress any row with `site_count < 5`; (2) publish no period-over-period delta for a category whose `site_count` is below 2× the floor (i.e. < 10). Keep `site_count` out of every tenant-visible surface. **Mitigation (2) is gated, not merely asserted (PVL cycle 2, C10):** AC-14 plus a Fully-Automated grep/AST assertion that no benchmark surface computes a period-over-period difference.
- [x] E3. Backlog note `process/features/campaigns-outreach/backlog/reply-tracking_NOTE_16-08-26.md` — reply tracking is unbuilt and out of scope (D8); record what a v1 would need.
- [x] E4. Backlog note `process/features/campaigns-outreach/backlog/benchmark-k-floor-review_NOTE_16-08-26.md` — revisit k=5 upward as tenant count grows.
- [x] E5. Record in the phase report that marketing copy implying auto-send or auto-adjustment ("coordinated automatically") must be REWORDED, and that this phase deliberately did not implement it (umbrella checklist P4).

---

## Acceptance Criteria

| # | Criterion |
|---|---|
| AC-1 | `normalize_category` is pure and deterministic; unknown input maps to `"other"` and is still counted. |
| AC-2 | Zero sends renders as "no data" (never "0% open rate"); N sends with 0 opens renders as a measured 0; every open-rate value carries the MPP/image-blocking unreliability caveat (`open_pixel.py:6-9`). No dependence on `identity_signals_enabled`. |
| AC-3 | The benchmark table contains no site identifier, visitor reference, email, or tenant free text — asserted by test. |
| AC-4 | A category with `site_count < 5` produces NO benchmark row. |
| AC-5 | A site without `benchmark_contribution_enabled = True` contributes nothing and leaves no per-site trace. `Site.contribution_enabled` and the co-op consent path are untouched. |
| AC-6 | The weekly job is registered in APScheduler, flag-gated, and logs a structlog line on crash without killing the scheduler. |
| AC-7 | With `campaign_benchmark_enabled=False`, no rows are written and the digest/report render exactly as today. |
| AC-8 | `build_digest_email` stays pure with a keyword-only defaulted benchmark arg (`DigestStats` unchanged); its existing unit tests pass unchanged; the digest stays PII-free and says "category average", never "median"; **the RENDERED digest benchmark line carries the MPP/image-blocking open-rate caveat** (the digest is built to be forwarded, so an uncaveated open rate would travel outside the account). |
| AC-8b | The D2/D6 web "what's working" panel renders the same MPP/image-blocking caveat on any open-rate value it displays. **Proof shape LOCKED (orchestrator decision, PVL cycle 4):** the caveat copy is extracted into a PURE module under `apps/web/src/lib/` and asserted by the EXISTING vitest lane (`npm test` → `vitest run` in `apps/web`), mirroring Phase 2's approach. `apps/web` has NO `@testing-library/react`, no `jsdom`, and no `happy-dom`, and Playwright is blocked by the unresolved Clerk auth-harness gap — **do NOT install a component-testing stack in this phase.** Visual placement of the caveat on the rendered page is a NAMED Agent-Probe residual, not a Fully-Automated gate. |
| AC-9 | Measured stats appear in the `campaign_planner` prompt context with the flag ON. `apps/api/services/auto_drafter.py` (under `services/`, NOT `agents/`) is unmodified (asserted). |
| AC-10 | No new path reaches `send_campaign_emails`; drafts still require human approval. |
| AC-11 | The migration applies and reverses cleanly against local Postgres on `:5433`. |
| AC-12 | Reply-tracking and k-floor-review backlog notes exist. |
| AC-14 | No benchmark surface (digest builder, outcomes report, benchmark service) computes or publishes a period-over-period delta — asserted by a Fully-Automated grep/AST gate over the digest builder output and the new modules. This is E2b mitigation (2) made non-vacuous. |
| AC-13 | `campaign_stats.py` is the sole funnel definition as a shared PREDICATE SET: `outcomes.py:282-310` imports the shared count expressions and **keeps its grouped-aggregate, no-row-materialization shape** (asserted: no row-fetch introduced, per-campaign grouping preserved, `conv_rows` untouched); the BENCHMARK rollup calls the pure `summarize(..., channel="email")`. The `/outcomes` response is byte-equivalent before and after the refactor, with a regression fixture containing ≥1 ORM-constructed social touchpoint (non-vacuous). |

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `.venv/bin/python3.11 -m pytest tests/unit/test_normalize_category.py -q` exits 0 | Fully-Automated | AC-1 |
| `.venv/bin/python3.11 -m pytest tests/unit/test_campaign_benchmark.py -q` exits 0 (k-floor, opt-out, pure summarize) | Fully-Automated | AC-4, AC-5 |
| Model-introspection test: `campaign_benchmarks` columns contain no site/visitor/email reference | Fully-Automated | AC-3 |
| `.venv/bin/python3.11 -m pytest tests/unit/test_outcome_digest_benchmark.py -q` + the pre-existing digest tests both exit 0; asserts the rendered benchmark line contains the MPP caveat and that `DigestStats` is unchanged | Fully-Automated | AC-8 |
| `cd apps/web && npm test` (existing `vitest run` lane) asserts the pure `apps/web/src/lib/` caveat module returns the MPP/image-blocking text used by the "what's working" panel — no DOM render, no new test dependency | Fully-Automated | AC-8b (copy correctness) |
| Agent probe: open the outcomes report page and judge that the MPP caveat is visibly placed next to the open-rate value (not buried) | Agent-Probe | AC-8b (visual placement — named residual; no jsdom/testing-library in `apps/web`, Playwright blocked by the Clerk auth harness) |
| `CAMPAIGN_BENCHMARK_ENABLED=true .venv/bin/python3.11 -m pytest tests/integration/test_campaign_benchmark_job.py -q` — **precondition: flag ON, seeded multi-site fixture with ≥5 opted-in sites in one category and <5 in another; PG :5433 up** | Hybrid | AC-4, AC-5, AC-6, AC-9 |
| Same suite re-run with `CAMPAIGN_BENCHMARK_ENABLED=false` — asserts zero rows written | Fully-Automated | AC-7 |
| Rollup test: 0 sends → "no data"; N sends / 0 opens → measured 0; open-rate value carries the MPP caveat | Fully-Automated | AC-2 |
| Rollup test asserts `summarize(channel="email")` excludes social rows; `/outcomes` funnel regression test asserts unchanged values after the `campaign_stats` refactor, **with a fixture containing ≥1 `social_reply`/`social_dm` touchpoint** | Fully-Automated | AC-13 |
| Grep/AST assertion: `apps/api/services/auto_drafter.py` (path is under `services/`, NOT `agents/` — a gate globbing `apps/api/agents/auto_drafter.py` is vacuously green) is byte-unchanged and no new module imports it | Fully-Automated | AC-9 |
| Grep assertion: new modules contain no reference to `send_campaign_emails` | Fully-Automated | AC-10 |
| `DATABASE_URL=<localhost:5433> ... alembic upgrade head / downgrade -1 / upgrade head` | Hybrid — precondition: local PG up; `DATABASE_URL` pinned (bare alembic hits PROD) | AC-11 |
| Grep/AST assertion: no benchmark surface computes a period-over-period delta (digest builder output + new modules) | Fully-Automated | AC-14 |
| `ls process/features/campaigns-outreach/backlog/reply-tracking_NOTE_16-08-26.md ...benchmark-k-floor-review_NOTE_16-08-26.md` | Fully-Automated | AC-12 |
| Agent probe: read a generated digest email and a generated draft; judge whether the benchmark line and the "what's working" claims are truthful given the underlying numbers and do not imply auto-send | Agent-Probe | AC-8, AC-10 (claim truthfulness — cannot be mechanically asserted) |

Failing stub (AC-4/AC-5, fully-automated):

```
test("benchmark job writes no row below the k-floor and ignores opted-out sites", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: benchmark k-floor and opt-in gating")
})
```

Failing stub (AC-3, fully-automated):

```
test("campaign_benchmarks model exposes no tenant-identifying column", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: benchmark zero-PII shape")
})
```

Failing stub (AC-2, fully-automated):

```
test("rollup renders no-data for zero sends and a measured zero for N sends with no opens", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: no-sends vs measured-zero distinction")
})
```

Failing stub (AC-10, fully-automated):

```
test("learning loop modules never reach send_campaign_emails", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: send-gate regression")
})
```

---

## Test Infra Improvement Notes

- Flag-off vacuity is the sharpest risk in this phase: `campaign_benchmark_enabled` gates whether
  the benchmark data under test exists at all. Every gate must name which flags are ON. A benchmark
  suite run entirely flag-off proves nothing (ip-org errata G8/G10). Note `identity_signals_enabled`
  is NOT a precondition for any gate here — it does not gate campaign open/click.
- The multi-site fixture needed for the k-floor test (≥5 opted-in sites in one category, <5 in
  another) does not exist yet — building it is real test-infra work, not incidental.
- Docker IS available at `/Applications/Docker.app/Contents/Resources/bin/docker` (off `PATH`);
  detect via `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`. Do NOT classify container gates
  environment-blocked without that check.
- Integration conftest calls `drop_all`/`create_all` — never point `DATABASE_URL` at the dev DB
  while running the integration lane.

---

## Exit Gate

```bash
lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'
# Expected: listener on 5433

.venv/bin/python3.11 -m pytest tests/unit -q
# Expected: exit 0, no new failures vs this session's baseline

CAMPAIGN_BENCHMARK_ENABLED=true .venv/bin/python3.11 -m pytest tests/integration -q
# Expected: exit 0, and the benchmark job tests actually exercised the ON path

CAMPAIGN_BENCHMARK_ENABLED=false .venv/bin/python3.11 -m pytest tests/integration/test_campaign_benchmark_job.py -q
# Expected: exit 0 with zero benchmark rows written

DATABASE_URL=postgresql+asyncpg://USER:PW@localhost:5433/DB .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads
# Expected: single head equal to the new campaign_benchmark revision

node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-3-learning-loop-benchmarks_PLAN_16-08-26.md
# Expected: failures: []
```

- All checklist items checked
- AC-1..AC-14 met or recorded as known-gaps with rationale
- Both backlog notes written
- Phase report written; execution changes committed; umbrella `## Current Execution State` updated

---

## Phase Completion Rules

- 🔨 CODE DONE — checklist complete, unit tests green.
- 🧪 TESTING — Fully-Automated + Hybrid gates run with the benchmark flag ON for the job path.
- ✅ VERIFIED — all gates green with their flag preconditions satisfied, validate-contract recorded,
  AND the user has user-confirmed the digest/report claims read truthfully (AC-8/AC-10 agent probe).
  A gate that passes only because `campaign_benchmark_enabled` is OFF does not count.
- 🚧 BLOCKED — see Blockers below.

Code-only completion is `CODE DONE`, never `VERIFIED`.

---

## Blockers That Would Justify BLOCKED Status

- Fewer than 5 opted-in sites exist in ANY category in every reachable environment, making AC-4's
  positive case unprovable outside a synthetic fixture. Resolution: prove with the synthetic
  fixture, record the live-data gap as a known-gap; do NOT lower the k-floor to make a test pass.
- Any pressure to authorize benchmark contribution via `Site.contribution_enabled` or the co-op
  `terms_version` — stop. That is a purpose-limitation breach (D3); add the benchmark-scoped flag instead.
- A design pressure to store a site identifier in the benchmark table to make the aggregation
  tractable — stop. That is a hard safety constraint (D1); re-scope the aggregation instead.
- Any pressure to auto-adjust a live campaign or bypass draft approval — stop immediately;
  permanently out of scope.
- `alembic heads` returns more than one head — re-chain off the true live head; stop if ambiguous.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner
loop `R → I → P → PVL → E → EVL → UP` SKIPS SPEC.

- [ ] 1. RESEARCH — research-agent: prior phase reports read; test context loaded; plan drift checked
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: this phase plan updated; Inner Loop Refresh Note if sections changed (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1–V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`
- [x] 5. EXECUTE — all checklist items done; per-section test gates run and green (or gaps documented)
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate Contract`
reads "(placeholder — vc-validate-agent writes this section before EXECUTE)", the orchestrator must
spawn vc-validate-agent first. A partial contract missing Plan updates applied / Execute-agent
instructions / Test gates is treated as a placeholder.

---

## Resume and Execution Handoff

1. Selected plan file path: `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/phase-3-learning-loop-benchmarks_PLAN_16-08-26.md`
2. Last completed step: not started (gated on Phase 1 exit)
3. Validate-contract status: CONDITIONAL (PVL cycle 4, 16-08-26) — see `## Validate Contract` below; not yet accepted
4. Supporting context files loaded: `process/context/all-context.md`,
   `process/context/tests/all-tests.md`, umbrella plan, Phase 1 report,
   `process/features/visitors-identity/active/identity-coop_07-08-26/` (privacy invariants)
5. Next step: confirm Phase 1's exit gate passed, then spawn vc-research-agent for RESEARCH
   (Step 1). Do not `ENTER EXECUTE MODE` until PVL writes a full validate-contract.

---

## Next Step

Phase 3 plan complete. Confirm the Phase 1 exit gate, then run the inner loop from RESEARCH.
`ENTER EXECUTE MODE` only after the validate-contract below is written.

---

## Execute Anchor Note

This file IS the primary execute anchor for this phase (filename begins with `phase-` but this is a
direct `*_PLAN_*.md` artifact, not a legacy multi-file plan). Supporting phase files: the umbrella
plan `marketing-claims-gap-umbrella_PLAN_16-08-26.md` and the sibling phase plans in the same task
folder — pass them as context only, never as the execute target.

---

## Validate Contract

Status: CONDITIONAL
Date: 16-08-26
date: 2026-08-16
generated-by: outer-pvl
supersedes: 2026-08-16 (outer-pvl) — PVL cycle 4 re-validation from V1; all four cycle-3 CONCERNs (N1–N4) verified CLOSED against source

Parallel strategy: sequential (executed sequentially — see Method note)
Rationale: 5/7 signals (S1 multi-package apps/api+apps/web+tests, S2 schema+API surface, S4 phase
program, S6 high-risk schema/migration + cross-tenant aggregation, S7 12 files + 1 migration) → HIGH
by score, but strategy-by-fit overrides the threshold: EXECUTE here is one plan with strongly ordered
legs (config flag → migration head re-derivation → model/table → campaign_stats → /outcomes refactor →
surfaces), so a single sequential vc-execute-agent (opus) is the correct fit. Dominant signal:
cross-tenant data aggregation.
Method note: this validate-agent has no Agent tool grant in this environment, so the
`vc-validate-findings` Layer 1 / Layer 2 role specs were executed sequentially by one agent against
real source rather than fanned out. Record this as reduced adversarial breadth (single-pass), not as a
completed parallel fan-out. Structural gate `validate-plan-artifact.mjs` run this session:
`failures: []`, `warnings: []`, 547 lines (pre-rewrite).

### Cycle 3 supplement verification — all 4 CONCERNs CLOSED against source

| Prior finding | Verdict | Evidence re-checked this session |
|---|---|---|
| **N1** — B4b overstated the channel hazard as live; B5b's fixture necessarily synthetic | **CLOSED** | B4b is now explicitly framed defensive/forward-looking and carries the ⚠️ HARD SCOPE GUARD forbidding a "fix" to the sender. Verified: `grep -rn "CampaignTouchpoint(" apps/api/` returns exactly two hits — the class definition at `models/campaign.py:38` and the SOLE constructor call at `campaign_sender.py:397`, which hardcodes `channel="email"` at `:400`. Social channels appear only as `Campaign.plan` dicts (`campaigns.py:160` `tp.get("channel") in ("social_reply","social_dm")`). Real ORM channel filters confirmed exact at `campaigns.py:215`, `campaigns.py:245`, `campaign_sender.py:347`; the plan-dict read at `campaign_sender.py:64` is `tp.get("channel") == "email"`. `grep -n channel apps/api/routers/outcomes.py` → **zero matches**. B5b now states the social row is ORM-constructed in the fixture and that no producer exists by design. |
| **N2** — `/outcomes` refactor shape unspecified; a pure `summarize(rows)` would force unbounded materialization | **CLOSED** | B2 now pins the LOCKED dual-export shape. Verified against source: `outcomes.py:282-310` is exactly one grouped `select(Campaign.id, Campaign.name, func.count().filter(...)×3).join(CampaignTouchpoint).where(Campaign.site_id==site_id).group_by(Campaign.id, Campaign.name)` — no row materialization, and the JOIN carries no cutoff (confirming the hazard the fix avoids). `conv_rows` is exactly `outcomes.py:316-330` and is now declared explicitly OUT OF SCOPE. B5's asymmetry statement is line-for-line accurate: all three counters carry `sent_at >= cutoff`; `sent` additionally carries `status == "sent"`; `opened`/`clicked` carry only `is_not(None)`. Exporting the three `func.count().filter(...)` predicates for SQL reuse is mechanically feasible and preserves the aggregate shape and cost. |
| **N3** — Blast Radius omitted `config.py`, `schemas/sites.py`, `schemas/outcomes.py` | **CLOSED** (one residual → M3) | All three are now in Blast Radius, and C0b was added. Citations verified exact: `config.py:183` `outcomes_digest_enabled`, `config.py:922` `identity_signals_enabled`, `campaign_benchmark_enabled` absent (correct — new); `schemas/sites.py:48` is `class SiteUpdate(BaseModel):`; `schemas/sites.py:39` is `@field_validator("internal_damping_enabled", "contribution_enabled", mode="before")`; `schemas/outcomes.py:130-134` is `class OutcomesReportResponse` with `days/totals/campaigns/goals`. Residual: C0b instructs extending the validator but never declaring the new field on `SiteOut` — see M3. |
| **N4** — concurrent uncommitted program occupies the C0 target files | **CLOSED** (one residual → M1) | The MANDATORY PRE-EDIT RULE is present with all three clauses including the FORBIDDEN git list. State re-verified live: `apps/api/models/site.py` modified (+24), `apps/api/routers/sites.py` modified (+204), untracked `apps/api/migrations/versions/c5e1a9b73d20_add_site_profile.py` present, 76 revision files on disk. Authoritative `alembic heads` (DSN pinned to `localhost:5433`) returns a **single head `d7e2b4c81f93`** — the plan's "more than one head" BLOCKED condition is NOT triggered. Residual: the re-read list omits two more files that will shift, and the plan's own `sites.py:NNN` citations are already stale — see M1. |

No previously-closed finding regressed. All cycle-0 and cycle-2 FAILs remain closed. 0 FAILs this cycle.

### Net Gate Derivation

| Layer 1 dimension | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | CONCERN |
| Breaking changes | CONCERN |
| Security surface | PASS |

| Layer 2 section | Status |
|---|---|
| Step A — Category normalization | PASS |
| Step B — Per-site stats rollup | PASS |
| Step C — Benchmark table + job | CONCERN |
| Step D — Surfaces | CONCERN |
| Step E — Safety + backlog | PASS |

Totals: 0 FAILs / 4 CONCERNs / 5 PASSes → **Net Gate: CONDITIONAL**

Vacuous-green check (V3 Step A1): AC-1..AC-14 each carry a Fully-Automated or Hybrid proving gate, and
E2b mitigation (2) remains gated by AC-14. One gate is at risk of silently degrading to Known-Gap at
EXECUTE — AC-8b's web-panel caveat assertion, tiered Fully-Automated with no web-render test capability
in the repo (M4). Per A1 that is named here explicitly as a residual requiring a decided resolution
before EXECUTE, not left silent — so CONDITIONAL is a genuine verdict, not a vacuous-green mask.
Step B moves CONCERN → PASS this cycle: both of its cycle-3 findings are closed and no new Step B
defect was found.

### CONCERN findings (new this cycle)

| # | Finding | Severity | Proposed fix |
|---|---|---|---|
| M1 | **Every `routers/sites.py` line citation in the plan is stale, and the pre-edit re-read list omits two more files that will shift.** The co-op consent path is cited as `sites.py:417-438` in four places (Touchpoints, AC-5's gate, the security dimension, the coverage-limits list). Verified live: `if body.contribution_enabled is not None:` sits at **`:422`** in the working tree and at **`:364`** at HEAD — `:417` matches neither (in the working tree `:417` is `site.auto_paused_at = None`, part of the `tracking_enabled` branch). The audit precedents cited as `:378`/`:878`/`:215` are actually `:383`/`:890`/`:215`. This matters because **AC-5's Fully-Automated leg says "assert `sites.py:417-438` … are unmodified"** — a line-range-anchored assertion would check the wrong code and pass vacuously. The root cause is structural, not clerical: the site-analysis-onboarding program holds +204 uncommitted lines in this file (the plan itself recorded +185, already stale), so **any** line-range anchor into it drifts again before EXECUTE. Compounding it, Entry Gate rule 1 names only `models/site.py` and `routers/sites.py` for mandatory re-read — it omits `apps/api/schemas/sites.py` (whose `:39`/`:48` anchors C0b depends on, and which **sibling Phase 1 also claims** for `booking_url`) and `apps/api/agents/campaign_planner.py` (whose `CAMPAIGN_PLANNING_PROMPT` Phase 1 also edits for the booking token). There is no `phase-blast-radius-registry.md` in this program folder, unlike ads-audiences/evallayer/handoff. | CONCERN | (a) Re-express the co-op-untouched assertion by SYMBOL/anchor — the `if body.contribution_enabled is not None:` block through the `coop_terms_version` compare and the `identity_contribution_consent_acceptances` write — or as a `git diff` check on that hunk. Never a line range. (b) Strike or mark-as-indicative all `sites.py:NNN` numbers in the plan. (c) Extend Entry Gate rule 1's re-read list to `apps/api/schemas/sites.py` and `apps/api/agents/campaign_planner.py`, naming sibling Phase 1 as the second source of churn alongside site-analysis-onboarding. |
| M2 | **`auto_drafter.py` has no resolvable path in the plan, and the implied one is wrong.** D4 reads "Stat injection targets `agents/campaign_planner.py` … `auto_drafter.py` is explicitly EXCLUDED", pairing the two as siblings; Blast Radius (`auto_drafter.py` is NOT touched), checklist D4, AC-9, and the AC-9 gate row all use the bare filename. `apps/api/agents/` contains only `__init__.py`, `campaign_planner.py`, `prompt_safety.py`, `segmenter.py`, `workspace_tools.py` — the module actually lives at **`apps/api/services/auto_drafter.py`** (211 lines). AC-9's Fully-Automated leg ("`auto_drafter.py` byte-unchanged and no new module imports it") therefore has no target path to grep. The D4 CONTENT citations are all exact and re-verified: the module docstring is a social-reply drafter ("Generates a contextual comment/reply draft"), `_generate_draft_text` is at `:143`, the `context_hint` block is `:159-163`, and it calls `ai_reply.generate_draft`. Only the directory is missing. | CONCERN | Write the full path `apps/api/services/auto_drafter.py` in D4, in the Blast Radius parenthetical, in checklist D4, and in the AC-9 gate row. |
| M3 | **C0b tells the executor to extend the `SiteOut` validator but never to declare the field — following it literally breaks the API import.** C0b and Blast Radius both say "extend the existing `SiteOut` `field_validator(..., mode="before")` at `apps/api/schemas/sites.py:39` to include `benchmark_contribution_enabled`". Verified: `SiteOut` declares `internal_damping_enabled: bool = False` at `:32` and `contribution_enabled: bool = False` at `:35` as REAL fields, and the `:39` validator names both. In Pydantic v2 a `@field_validator` naming an undeclared field raises at class-definition time, so adding the name to the validator without adding the field to `SiteOut` raises on import of `apps/api/schemas/sites.py` — i.e. the whole API fails to start. This is the exact "easily-missed failure mode" C0b was added to prevent, one step short. | CONCERN | Reword C0b: "declare `benchmark_contribution_enabled: bool = False` on `SiteOut` (mirroring `contribution_enabled` at `:35`) **and** add its name to the `mode="before"` validator" — both halves, in that order. |
| M4 | **AC-8b is tiered Fully-Automated with gap-resolution B, but `apps/web` has no component-render test capability.** The proving test is "Panel render assertion in the outcomes report view test". Verified: `apps/web` has vitest (`"test": "vitest run"`, `vitest.config.ts`) but **all 10 existing test files live under `src/lib/` and are pure module tests**; `@testing-library/react`, `jsdom`, and `happy-dom` are all absent from `apps/web/package.json`. Rendering `apps/web/src/app/dashboard/outcomes/page.tsx` (client component, hooks, dialogs, TanStack Query) is not possible with the installed toolchain. The only alternative — Playwright against the authed dashboard — hits the repo-wide Clerk auth-harness gap already blocking gates in ads-audiences P1/P2, cadence-bot-flag, and privacy-hold-clear. This matters more than it looks: the outcomes page today renders only `Conv. rate` (`:292`/`:313`) and already carries "Email opens alone never count." (`:260`), so D6 introduces that page's FIRST open-rate value and AC-8b is the only gate on its caveat. Left as-is, AC-8b degrades silently to Known-Gap during EXECUTE — the vacuous-green pattern V3 Step A1 bans. | CONCERN | Decide the resolution NOW, in plan text, not mid-EXECUTE. Cheapest and most consistent with the existing 10 `src/lib/*.test.ts` files: **(c)** extract the caveat copy into a pure `apps/web/src/lib/` module and assert it with the existing vitest lane, keeping AC-8b Fully-Automated. Alternatives: (a) re-tier AC-8b to Agent-Probe and record it as a named residual; (b) add an explicit Step D test-infra checklist item to install `@testing-library/react` + a DOM env, budgeted as real work like B5b's fixture. Do not leave the tier unchanged without picking one. |

Nits (no action required):
- `models/campaign.py:64` is cited for the `channel` column; the actual line is `:62`.
- Entry Gate records `routers/sites.py +185`; the live diff is now `+204` — the concurrent program grew since cycle 3, which validates the re-read rule rather than undermining it.
- Entry Gate rule 2 names `c5e1a9b73d20` as "the" untracked revision. There are now TWO untracked revisions and the true live head is `d7e2b4c81f93` (`add_waitlist_application_fields`), which chains off `c5e1a9b73d20`. Rule 2's first clause ("re-run `alembic heads` LIVE") already covers this, so no change is needed.
- `prompt_safety.clean_text` (`:44`) takes a REQUIRED `max_len` argument; D5 cites it without one. Immaterial while D2's subject path stays deferred.
- The Acceptance Criteria table still lists AC-14 before AC-13 (carried cosmetic nit).

### Test gates (5-column)

Flag posture verified in source this session: `campaign_benchmark_enabled` does not yet exist (new, D9 —
must be added to `config.py` per C0b); `outcomes_digest_enabled` = False (`config.py:183`);
`identity_signals_enabled` = False (`config.py:922`) and is IRRELEVANT to campaign open/click — not a
precondition for any gate here. PG `:5433` and Redis `:6379` confirmed LISTENING this session, so every
Hybrid precondition is satisfiable now.

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | `normalize_category` pure/deterministic; unknown → `"other"`, still counted | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_normalize_category.py -q` (no flag precondition — pure function) | B |
| AC-2 | 0 sends → "no data"; N sends / 0 opens → measured 0; every open-rate value carries the MPP/image-blocking caveat | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_campaign_stats.py -q` — rollup legs. No `identity_signals_enabled` precondition; gate is non-vacuous | B |
| AC-3 | `campaign_benchmarks` exposes no site/visitor/email/tenant-free-text column | Fully-Automated | Model-introspection test over `CampaignBenchmark.__table__.columns` (no flag precondition — schema shape) | B |
| AC-4 | `site_count < 5` writes NO row | Hybrid | `CAMPAIGN_BENCHMARK_ENABLED=true .venv/bin/python3.11 -m pytest tests/integration/test_campaign_benchmark_job.py -q` — **preconditions: flag ON; PG :5433 listening (verified live this session); seeded fixture with ≥5 opted-in sites in one category and <5 in another** | B |
| AC-5 | `benchmark_contribution_enabled` false/NULL site contributes nothing, leaves no per-site trace; co-op path untouched | Hybrid | Same suite, opt-out leg — **precondition: flag ON**. Plus a Fully-Automated assertion that the co-op consent block and `Site.contribution_enabled` are unmodified — **anchored by SYMBOL, not line range (M1): the `if body.contribution_enabled is not None:` block through the `coop_terms_version` compare and the `identity_contribution_consent_acceptances` write** | B |
| AC-6 | Weekly job registered, flag-gated, structlog line on crash, scheduler survives | Hybrid | Same suite, scheduler-registration leg — **precondition: `campaign_benchmark_enabled=true`**; pattern re-confirmed at `jobs/scheduler.py:842-850` (flag gate + `CronTrigger(day_of_week="mon", hour=15, timezone="UTC")` + `replace_existing=True`), so "clear of the Monday cron" is actionable | B |
| AC-7 | Flag OFF → zero rows, digest/report unchanged | Fully-Automated | `CAMPAIGN_BENCHMARK_ENABLED=false .venv/bin/python3.11 -m pytest tests/integration/test_campaign_benchmark_job.py -q` — **only meaningful paired with the AC-4 flag-ON run; alone it is vacuous (ip-org G8/G10 errata)** | A/B |
| AC-8 | `build_digest_email` stays pure with a keyword-only defaulted arg (`DigestStats` unchanged); existing tests pass unchanged; digest PII-free; "category average" never "median"; rendered benchmark line carries the MPP caveat | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_outcome_digest_benchmark.py tests/unit/test_outcome_digest.py -q`. Re-verified: `DigestStats` at `outcome_digest.py:43-48` has no `opened`; `build_digest_email(site_name, stats, visitors=()) -> tuple[str,str]` at `:68`; all 6 existing call sites positional (`tests/unit/test_outcome_digest.py:15,26,32,46,57,63`); sole producer call `outcome_digest.py:271`. Must additionally assert the literal string "median" is absent and the caveat IS rendered | B |
| AC-8b | Web "what's working" panel renders the MPP caveat on any open-rate value | **AT RISK — tier unachievable as written (M4)** | Stated as "panel render assertion in the outcomes report view test", but `apps/web` has no `@testing-library/react` / jsdom / happy-dom and all 10 existing vitest files are pure `src/lib/` module tests; Playwright is blocked by the repo-wide Clerk auth harness. **Resolution must be chosen in plan text before EXECUTE** — preferred: extract the caveat copy into a pure `apps/web/src/lib/` module and assert it in the existing vitest lane | **B, contingent on M4's resolution — otherwise D** |
| AC-9 | Measured stats reach the `campaign_planner` prompt context; `auto_drafter.py` byte-unchanged | Hybrid + Fully-Automated | Planner-prompt assertion with **`campaign_benchmark_enabled=true`** (`CAMPAIGN_PLANNING_PROMPT` re-confirmed at `campaign_planner.py:16`); plus a Fully-Automated grep/AST leg asserting **`apps/api/services/auto_drafter.py`** (full path — M2) is unmodified and unimported by new modules | B |
| AC-10 | No new path reaches `send_campaign_emails` | Fully-Automated | Grep/AST assertion over the new modules; `send_campaign_emails` confirmed at `campaign_sender.py:201` and read-only for this phase | B |
| AC-11 | Migration applies and reverses cleanly | Hybrid | `DATABASE_URL=postgresql+asyncpg://…@localhost:5433/… .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` then `upgrade head` → `downgrade -1` → `upgrade head`. **Preconditions: `DATABASE_URL` PINNED to localhost:5433 (bare alembic hits Supabase PROD); `alembic heads` re-run LIVE. Verified this session: 76 revision files, SINGLE head `d7e2b4c81f93`, TWO untracked revisions at the tip (`c5e1a9b73d20` → `d7e2b4c81f93`); Phases 1-2 will each land one more before this phase** | B |
| AC-12 | Both backlog notes exist | Fully-Automated | `ls` on the two note paths (`process/features/campaigns-outreach/backlog/` confirmed to exist and be writable) | B |
| AC-13 | `campaign_stats.py` is the sole funnel definition as a shared PREDICATE SET; `/outcomes` keeps its grouped-aggregate shape; benchmark calls `summarize(..., channel="email")`; fixture holds ≥1 social touchpoint | Fully-Automated | `/outcomes` funnel regression test asserting unchanged values after the refactor, fixture containing ≥1 ORM-constructed `social_reply`/`social_dm` touchpoint (no application path produces one — expected); plus a rollup test asserting `channel="email"` excludes social rows; plus assertions that no row-fetch was introduced, `group_by(Campaign.id, Campaign.name)` is preserved, and `conv_rows` (`outcomes.py:316-330`) is untouched. **Shape now fully specified and mechanically verified feasible** | B |
| AC-14 | No benchmark surface computes or publishes a period-over-period delta | Fully-Automated | Grep/AST gate over the digest builder output and the new modules (E2b mitigation (2) made non-vacuous) | B |
| AC-8/AC-10 | Digest + draft copy is truthful and implies no auto-send | Agent-Probe | Read a generated digest email and a generated draft; judge claim truthfulness against the underlying numbers. Must check the rendered statistic matches what the schema can compute (pooled mean) and that the open rate carries its caveat | A |

Legacy line form:
- category normalization: [Fully-automated: `pytest tests/unit/test_normalize_category.py -q`]
- benchmark job k-floor/opt-in: [hybrid: `CAMPAIGN_BENCHMARK_ENABLED=true pytest tests/integration/test_campaign_benchmark_job.py -q` + precondition PG :5433 and a ≥5-site seeded fixture]
- migration round-trip: [hybrid: pinned-`DATABASE_URL` alembic up/down/up + precondition local PG :5433, single head `d7e2b4c81f93` re-derived live]
- send-gate regression: [Fully-automated: grep/AST assertion for `send_campaign_emails`]
- co-op-path-untouched assertion: [Fully-automated: SYMBOL-anchored diff on the `contribution_enabled` block — NOT a line range (M1)]
- period-over-period differencing suppression: [Fully-automated: AC-14 grep/AST gate]
- web panel MPP caveat: [known-gap pending M4's resolution: no web-render test capability in `apps/web` today]
- claim truthfulness: [agent-probe: read digest + draft, judge against underlying numbers]
- open/click measurement reliability under Apple MPP and image blocking: [known-gap: documented]

gap-resolution legend: A — proven now; B — fixed in this plan; C — deferred to a named later phase; D — backlog residual.

Dimension findings:
- Infra fit: PASS — PG `:5433` and Redis `:6379` confirmed LISTENING this session; authoritative `alembic heads` (DSN pinned to localhost) returns a SINGLE head `d7e2b4c81f93`, so the "more than one head" BLOCKED condition is not triggered; 76 revision files on disk with two untracked at the tip; APScheduler flag-gate + `CronTrigger(mon, 15:00 UTC)` + `replace_existing` re-confirmed at `jobs/scheduler.py:842-850`; the `.env`→Supabase-PROD hazard and chain-off-live-head requirement are correctly stated; `traffic_fit.py:31 MIN_SAMPLE = 50` re-confirmed as the cited k-floor precedent; `process/features/campaigns-outreach/backlog/` exists for E3/E4.
- Test coverage: CONCERN — AC-1..AC-7 and AC-9..AC-14 all carry achievable Fully-Automated or Hybrid gates, and AC-13's gate is now fully specified and mechanically feasible after the B2a lock. The single defect is AC-8b: tiered Fully-Automated with gap-resolution B, but `apps/web` has vitest with only pure `src/lib/` module tests and no `@testing-library/react`/jsdom/happy-dom, and the Playwright route is blocked by the repo-wide Clerk auth harness (M4). Flag-off vacuity remains correctly called out and paired.
- Breaking changes: CONCERN — `build_digest_email` compat is pinned and re-verified against all 6 positional call sites and its sole producer; `DigestStats` is frozen; the `/outcomes` refactor now preserves the grouped-aggregate shape by construction; the three previously-missing contract files are in Blast Radius with exact citations. Remaining: C0b would break `apps/api/schemas/sites.py` on import if followed literally, because it extends the `SiteOut` validator without declaring the field (M3); and `auto_drafter.py`'s path is unresolvable, leaving AC-9's grep leg without a target (M2).
- Security surface: PASS — the benchmark has its own purpose-scoped consent basis (`benchmark_contribution_enabled`), the co-op path is explicitly read-only and confirmed unmodified in the working tree, the zero-PII k-anonymous schema keeps GDPR erasure moot by construction, write-nothing-when-blocked is preserved, and the structlog consent audit is precedented in the same router (`site_id_reuse_collision`, `site_deleted`, `shopify_connected` — all three located this session). Period-differencing is gated by AC-14. M1 affects how the untouched-assertion is ANCHORED, not the security design itself.
- Step A — Category normalization: PASS — A1's AUTHORED/SAMPLED framing is accurate and `Site.category` is re-confirmed free `String(100)` at `models/site.py:20`; D4b's `"other"` bucket keeps the design safe regardless of the sampling outcome.
- Step B — Per-site stats rollup: PASS (promoted from CONCERN) — N1 and N2 are both closed against source. The sole-constructor claim, the channel-filter citations, the `outcomes.py:282-310` aggregate shape, the `conv_rows` boundary at `:316-330`, and the `sent`-vs-`opened`/`clicked` asymmetry all verify line-for-line. The B4b scope guard removes the send-path breach hazard, and B5b's synthetic-fixture instruction removes the "hunt for a producer" hazard. No new Step B defect found.
- Step C — Benchmark table + job: CONCERN — the D1 schema shape, k-floor, write-nothing-when-blocked, the structlog consent audit, and the migration protocol are all mechanically sound and correctly cited, and the live head is single. Remaining: C0b's `SiteOut` instruction is one step short of correct and would break the API import (M3); the plan's `routers/sites.py` line citations are stale and the mandatory re-read list omits `schemas/sites.py` and `agents/campaign_planner.py`, both of which sibling Phase 1 also claims (M1).
- Step D — Surfaces: CONCERN — D1's keyword-only argument correctly avoids mutating `DigestStats` (re-verified `:43-48` has no `opened`), D2's subject deferral is decided with both JSONB extraction paths recorded and verified (`campaign_sender.py:403` `content={"subject": subject}`; `campaign_planner.py:75` plan schema), and D3's injection target `CAMPAIGN_PLANNING_PROMPT` is exact at `campaign_planner.py:16`. Remaining: `auto_drafter.py`'s path is wrong-by-implication and absent-in-fact (M2), and AC-8b's web gate is untierable with current infra (M4).
- Step E — Safety + backlog: PASS — E1's send-gate regression is well-formed (`send_campaign_emails` confirmed at `campaign_sender.py:201`), E2/E2b's privacy reasoning is sound, E2b mitigation (2) is gated by AC-14, and both backlog note paths are writable.

Open gaps:
- Open-rate reliability: Apple Mail Privacy Protection prefetch overcounts and image blocking undercounts (`open_pixel.py:6-9`, verbatim re-verified). No test can make open rate accurate; surfaces must caveat it. known-gap: documented.
- Web-panel caveat assertion (AC-8b): no component-render test capability exists in `apps/web` and Playwright is blocked by the Clerk auth harness. known-gap: documented — **must be converted to a decided resolution by M4 before EXECUTE.**
- Live-data proof of AC-4's positive case: `benchmark_contribution_enabled` does not exist yet and no web opt-in UI is planned beyond the `PATCH /sites/{id}` API path, so the positive case is provable only against a synthetic fixture. known-gap: documented.
- Social-channel touchpoints: no application path writes one (`campaign_sender.py:397` is the sole constructor, hardcoding `channel="email"`), so AC-13's non-vacuity fixture row must be ORM-constructed. known-gap: documented.
- Reply tracking: out of scope by D8. known-gap: documented as NEW PLAN REQUIRED — backlog note required by E3.
- Subject-line ranking: extractable via `CampaignTouchpoint.content['subject']` (`campaign_sender.py:403`) and `Campaign.plan` touchpoints (`campaign_planner.py:75`), deferred by the D2 decision. known-gap: documented.
- No cross-phase blast-radius registry exists for this program, unlike ads-audiences / evallayer / handoff. Phase 1 and Phase 3 both claim `models/site.py`, `routers/sites.py`, `schemas/sites.py`, and `agents/campaign_planner.py`; sequencing (Phase 1 exit gates Phase 3) plus M1's extended re-read rule is the mitigation in lieu of a registry. known-gap: documented.

What this coverage does NOT prove:
- The unit and integration gates do NOT prove any real tenant's opens/clicks are accurate — they prove rollup arithmetic over seeded rows. Apple MPP and image blocking are unmodelled.
- The k-floor gate does NOT prove k=5 is sufficient anonymity for the live tenant population; it proves the code discards sub-threshold buckets. AC-14 proves no delta surface is built — it does NOT prove differencing is impossible for anyone holding two published snapshots.
- The migration round-trip on `:5433` does NOT prove the migration is safe against Supabase PROD (different data volume; prod head must be re-derived at apply time), and the head verified this session (`d7e2b4c81f93`) will have moved by EXECUTE — Phases 1 and 2 each land a revision and two untracked revisions already sit at the tip.
- The flag-OFF gate (AC-7) does NOT prove the feature works — only that it is inert. It is meaningless unless the paired flag-ON run passes.
- The model-introspection privacy test does NOT prove the aggregation pipeline holds no per-site state in memory or logs; it proves the persisted schema shape.
- The `/outcomes` regression assertion does NOT prove channel-filter correctness against real data — its social touchpoint is synthetic, because no application path emits one.
- The `/outcomes` values-unchanged assertion alone does NOT prove query COST is preserved; that is why AC-13 now additionally asserts no row-fetch was introduced and that per-campaign grouping survives. Those are structural assertions, not performance measurements — no gate measures actual query time.
- The co-op-untouched assertion proves only what its anchor selects. A line-range anchor (as currently written at `sites.py:417-438`) selects the WRONG code in the present working tree and would pass vacuously — M1's symbol anchor is what makes this gate real.
- The structlog consent audit is NOT transactional and NOT durable in the way the co-op's acceptance row is (the co-op writes the acceptance in the same transaction as the flip, so "flag ON" can never exist without a matching row). A log line can be lost or rotated. This is the accepted, locked D3 tradeoff — no gate proves it is sufficient for a legal review.
- No gate proves the concurrent site-analysis-onboarding program's uncommitted work and this phase's edits compose cleanly; the pre-edit re-read rule is a procedure, not a test.
- The Agent-Probe does NOT mechanically prove claim truthfulness; it is agent judgment on sampled output.

Gate: CONDITIONAL
Accepted by: NOT ACCEPTED BY THIS AGENT — a validate-agent may not self-accept its own CONDITIONAL.
0 FAILs remain, all four cycle-3 CONCERNs (N1–N4) are verified CLOSED against source, and Step B is
promoted to PASS. The 4 new CONCERNs (M1–M4) are all resolvable by plan-text supplement with no
descope: M2 and M3 are one-line corrections, M1 is an anchor-and-re-read-list change, and M4 requires
one named decision among three stated options. `results.tsv` records ≥1 prior fix cycle (18 lines), so
acceptance is mechanically available to the orchestrator/user — but it must be an explicit orchestrator
or user decision, recorded here by name, before EXECUTE begins.
