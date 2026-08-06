---
name: plan:job-change-detection
description: "Detect a same-tenant identified visitor's company change against the site's own EnrichmentProfile baseline, gate on corroboration, record a minimal before/after event, and surface it as a draft outreach trigger — flag-off by default"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
---

# Job-Change Detection — Plan

Date: 07-08-26
Status: VALIDATED — Gate: PASS — pending EXECUTE
Complexity: COMPLEX (single plan, 3 internal phases — not a phase program: phases are small,
tightly interdependent, and share one migration/one validate-contract)
**Feature:** visitors-identity
**SPEC:** `process/features/visitors-identity/active/job-change-detection_07-08-26/job-change-detection_SPEC_07-08-26.md`
(14 ACs, all mapped below)

---

## Decisions Locked at INNOVATE (restated for EXECUTE — no re-litigation)

1. New service `apps/api/services/job_change_detector.py` owns the whole detect→corroborate→record
   pipeline. Budget gate (Redis daily counter) → 4 safety gates (mirrors `identity_signals.py`
   pattern: datacenter IP / proxy-VPN / suppression / `do_not_resolve`) run BEFORE any provider
   call, not after.
2. New model `apps/api/models/job_change_event.py` — `job_change_events` table, minimal
   before/after row, no email column, `(site_id, visitor_id)` string-pair convention matching
   `EnrichmentProfile`.
3. Two new Celery tasks in new module `apps/api/tasks/job_change_tasks.py` — Trigger A
   (event-driven, higher-frequency beat) and Trigger B (staleness sweep, low-frequency beat).
4. Corroboration = fixed source-tier confidence constants + at least one independent corroborating
   signal. Personal-email-only never confirms alone.
5. Surfacing = new function in `hot_contacts.py`/`hot_contacts` router (NOT literally reusing the
   phantom-pointer imported-contacts logic — see Phase 3 note on why this is additive, not a reuse
   of that specific query family) + additive segmenter signal + existing `AutoDrafter` draft path.
6. Erasure: `job_change_events` added to `delete_visitor_data`'s existing DELETE-loop table tuple.
7. Config: new `## ─── Job-change detection ───` block in `config.py`, default-OFF, following the
   `agent_detection_enabled` precedent exactly.
8. Known-gaps (recorded, not solved): confidence table is an uncalibrated heuristic;
   `company_graph` coverage is sparse (recall tradeoff accepted, documented); migration live
   round-trip is Docker-gated (offline `--sql` validation only, matching every other migration in
   this program).

---

## Context Envelope

| Field | Value |
|---|---|
| feature | visitors-identity |
| phase | PLAN |
| session-goal | Ship job-change detection v1 (same-tenant, flag-off) per locked SPEC |
| branch | devjulley |
| worktree | main (no separate worktree) |
| context-group | tests/all-tests.md, planning/all-planning.md |
| blast-radius-packages | apps/api (models, services, tasks, routers, config, migrations) |
| active-plan | this file |
| test-runner | `.venv/bin/python3.11 -m pytest` (unit) \| same runner, `-m integration` (integration, needs docker compose postgres+redis) |
| validate-contract | PASS — see `## Validate Contract` below |

---

## Touchpoints

| File | Change |
|---|---|
| `apps/api/models/job_change_event.py` | **NEW** — `JobChangeEvent` model |
| `apps/api/migrations/versions/<gen>_add_job_change_events.py` | **NEW** — create table + indexes, chained on TRUE current alembic head (re-verify via `alembic -c apps/api/alembic.ini heads` at EXECUTE time — context docs say `f1a7c3e05b92` as of 07-08-26 but this program and 3 concurrent programs (`identity-vocab-reconcile`, `graph-erasure-compliance`, `identity-coop`) may move it further before this plan's EXECUTE runs; **VALIDATE session 07-08-26 observed TWO heads in this worktree's git snapshot** — see Validate Contract Execute-Agent Instructions E-2 for the merge-migration handling rule) |
| `apps/api/services/job_change_detector.py` | **NEW** — `check_job_change_recheck_budget()`, 4 safety gates (`_passes_recheck_gates()`), `run_recheck(db, visitor, site)`, `compare_company(prior, new) -> bool` (normalization), `corroborate(pdl_data, work_email_domain) -> tuple[bool, float]`, `record_job_change(db, ...)` |
| `apps/api/tasks/job_change_tasks.py` | **NEW** — `recheck_returning_visitor(visitor_id, site_id)` (Trigger A, called from event path) + `sweep_stale_profiles()` (Trigger B, Celery beat task) |
| `apps/api/services/enricher.py` | **READ ONLY** — reuse `_enrich_pdl` / `_enrich_apollo` / `_FREE_MAIL_DOMAINS` as library calls from the new detector service; no signature change |
| `apps/api/services/company_resolver.py` | **READ ONLY** — reuse `CompanyGraphNode` IP-attribution lookup as an optional corroboration signal |
| `apps/api/services/celery_app.py` (`beat_schedule`, `:55-67`) | **MODIFY** — add `sweep-job-change-stale-profiles` entry |
| `apps/api/routers/events.py` or existing ingest event-handling path (Trigger A hookup point — confirm exact call site in Phase 2 research sub-step) | **MODIFY** — fire `recheck_returning_visitor.delay(...)` when an identified visitor with an existing `EnrichmentProfile` produces a new `Event` row, flag-gated |
| `apps/api/services/hot_contacts.py` | **MODIFY (additive)** — new read-only query function `get_job_change_events(db, site_id, limit=...)`, structurally separate from the phantom-pointer imported-contacts logic (different table, no pointer semantics) |
| `apps/api/routers/hot_contacts.py` | **MODIFY (additive)** — new endpoint or extend existing response shape to include job-change events, site-scoped. **VALIDATE note:** this router's own module docstring documents a real FastAPI route-registration-order landmine (a route appended after a conflicting prefix route in another file is silently unreachable) — read it before adding the new route (see Execute-Agent Instruction E-4). |
| `apps/api/agents/segmenter.py` | **MODIFY (additive)** — add `job_changed_at` as a readable signal input, following the `ai_source` precedent (signal, not intent-score bypass) |
| `apps/api/services/auto_drafter.py` (or the campaign draft-generation entry point it exposes) | **READ ONLY / call site** — `record_job_change()` calls the existing `AutoDrafter.generate_for_visitor`-equivalent path to create a `draft`-status campaign; no change to `AutoDrafter` itself unless Phase 3 research finds the entry point needs a new trigger-reason parameter (if so: additive optional param only). **VALIDATE confirmed:** the only existing caller is `apps/api/tasks/resolution_tasks.py:158` — use its call shape (`enrichment_data` dict, `social_context` dict, `user`) as the template. |
| `apps/api/routers/visitors.py` (`delete_visitor_data`, `:405-437`, table tuple starting `:422`) | **MODIFY** — add `"job_change_events"` to the existing table tuple in the DELETE loop. **VALIDATE confirmed:** the tuple is 6 hardcoded string literals (`resolution_logs`, `identified_visitors`, `enrichment_profiles`, `events`, `segment_members`, `visitors`) inside a raw-SQL loop — table names are not user input, so appending a 7th literal carries no injection risk. |
| `apps/api/config.py` | **MODIFY** — new `## ─── Job-change detection ───` block: `job_change_detection_enabled: bool = False`, `job_change_recheck_daily_cap: int`, `job_change_staleness_days: int = 75`, confidence/corroboration constants (or keep those as service-level constants — decide in Phase 1, document choice) |
| `tests/unit/test_job_change_detector.py` | **NEW** |
| `tests/unit/test_job_change_config.py` (or folded into the above) | **NEW** |
| `tests/integration/test_job_change_detection.py` | **NEW** |
| `tests/unit/test_agent_origin_exclusion.py` | **READ ONLY** — regression reference pattern for "structurally cannot X" tests; not modified |

## Public Contracts

- `job_change_detector.run_recheck(db, visitor, site) -> JobChangeEvent | None` — new function,
  no existing caller signature changes.
- `JobChangeEvent` ORM model — new table, no FK constraint onto `visitors`/`enrichment_profiles`
  (matches the string-pair, no-hard-FK convention already used by `EnrichmentProfile`,
  `IdentitySignal`, `CompanyGraphNode` in this codebase — avoids migration-order coupling).
- `GET /api/v1/hot-contacts/{site_id}` (or new sibling endpoint) — additive response field/route;
  existing hot-contacts response shape for imported contacts is unchanged.
- `config.Settings.job_change_detection_enabled` etc. — new settings, default OFF, no existing
  setting's default changes.
- Segmenter signal `job_changed_at` — additive input to segment-building; does not alter existing
  segment definitions or intent-score defaults (per SPEC's explicit "signal, not bypass" framing).
- Erasure: `job_change_events` added to `delete_visitor_data`'s DELETE-loop tuple — additive to an
  existing endpoint's already-multi-table behavior; response shape unchanged.

## Blast Radius

- **Files:** ~15 (5 new: model, migration, detector service, tasks module, 3 new test files —
  actually 8 new counting tests; ~7 modified: celery_app beat schedule, event-ingest hookup,
  hot_contacts service+router, segmenter, visitors.py delete loop, config.py).
- **Packages:** `apps/api` only. No `apps/web`, no `apps/pixel`.
- **Risk class:** HIGH — three named classes present: (1) PII-adjacent history table (mitigated by
  AC-14 no-plaintext-email schema + erasure cascade AC-12), (2) budget/credit accounting surface
  (AC-4, dedicated Redis counter, must not touch `Site.daily_resolution_budget`), (3) outreach
  trigger generation (AC-8, must land in `draft` status only, zero send-path calls).
- **Shared-surface conflict check (per SPEC Constraints — sequencing):**
  - `identity-vocab-reconcile_07-08-26` touches `identity_resolver.py` §3.2 — **this plan does
    NOT touch `identity_resolver.py` anywhere.** No overlap.
  - `graph-erasure-compliance_07-08-26` touches `apps/api/routers/visitors.py` `delete_visitor_data`
    (`:403-439`) to make it a producer for a new erasure queue, and touches
    `identity_resolver.py`. **This plan also edits `delete_visitor_data`'s table tuple at
    `:423`.** Direct file/function overlap — see Constraint C-1 below for the resolution rule this
    plan follows.
  - `social-context-merge_07-08-26` touches `apps/api/services/social_intelligence.py` and reads
    `EnrichmentProfile.social_context`/`social_context_updated_at` — **this plan does not touch
    `social_context` at all**, only `company_name`/`job_title`/`enriched_at`. No overlap.
  - `identity-coop_07-08-26` touches ledger/consumption/contributor-surface files, none of which
    intersect this plan's touchpoints. No overlap.

**Constraint C-1 (erasure sequencing — hard gate before EXECUTE):** Both this plan and
`graph-erasure-compliance_07-08-26` edit `delete_visitor_data` at the same line range (`:403-439`).
At the start of EXECUTE for this plan, re-read
`process/features/visitors-identity/active/graph-erasure-compliance_07-08-26/graph-erasure-compliance_PLAN_07-08-26.md`
and check whether that plan has already EXECUTEd its edit to that function:
- If graph-erasure-compliance has NOT yet executed: this plan's Phase 3 checklist item may proceed
  first — it is a pure additive tuple entry (`"job_change_events"` appended to the existing
  6/7-table tuple), a small, easily-rebased hunk.
- If graph-erasure-compliance HAS already executed (function now restructured into an
  enqueue-then-DELETE-loop shape per that plan's Touchpoint #4): add `"job_change_events"` to
  whatever the DELETE-loop table collection has become at that point — do not blindly diff-apply
  against the pre-restructure line numbers. Re-read the live file before editing.
- Either way: this plan's SPEC-mandated erasure requirement (AC-12) is satisfied by table-tuple
  inclusion — it does not depend on graph-erasure-compliance's queue mechanism existing.

**VALIDATE confirmation (07-08-26):** re-read `graph-erasure-compliance_07-08-26`'s plan directly —
its own status line reads "ACTIVE — PLAN written, VALIDATE pending, EXECUTE blocked on §0
sequencing constraint" (blocked behind `identity-vocab-reconcile_07-08-26` reaching `Gate: PASS`,
which per that program's own PVL cycle 6 report has not yet happened). So as of this VALIDATE
session, the "NOT yet executed" branch above is the live, correct branch — Constraint C-1's
resolution is real and current, not a stale assumption. EXECUTE for this plan must still re-check
live state per the instruction above (both plans are independently active and either could execute
first), but there is no live conflict today.

---

## Implementation Checklist — Phase 1: Model, Migration, Config, Safety Gates

1. Write `apps/api/models/job_change_event.py`:
   - `JobChangeEvent(Base)`, `__tablename__ = "job_change_events"`
   - Columns: `id` (UUID PK), `site_id` (String(50)), `visitor_id` (String(100)),
     `prior_company` (String(200)), `new_company` (String(200)), `prior_job_title` (String(200),
     nullable), `new_job_title` (String(200), nullable), `confidence` (Float),
     `corroboration_signal` (String(100) — e.g. `"work_email_domain"` / `"company_graph_ip"`),
     `detected_at` (DateTime, server_default=func.now()), `created_at`, `updated_at`
     (standard timestamp pair per repo convention).
   - `Index` on `(site_id, visitor_id)` for the erasure DELETE and the dashboard query — NOT
     unique (a visitor can have multiple confirmed transitions over time per AC-7's "one row per
     detected transition").
   - No email column, no FK constraint (matches `EnrichmentProfile`/`IdentitySignal` convention).
2. Re-verify true alembic head: `alembic -c apps/api/alembic.ini heads` (run inside the venv/container
   with DB access — NOT the sandboxed `.venv` path blocked by this session's tool guard; use
   whatever the execute-agent's actual runtime allows). Generate migration
   `apps/api/migrations/versions/<gen>_add_job_change_events.py` chained on that TRUE head via
   `alembic revision --autogenerate` (or hand-write if autogenerate is unavailable, matching the
   `add_identity_signal`/`add_fingerprint_v3` precedent style). Validate offline:
   `alembic -c apps/api/alembic.ini upgrade <observed-head>:head --sql` and the downgrade direction,
   per the repo's known offline-validation-only posture (no live Docker round-trip in this
   environment — recorded as Known-Gap #1, see below). **VALIDATE note (see Execute-Agent
   Instruction E-2): if `alembic heads` reports more than one head at EXECUTE time, do not pick one
   arbitrarily — this repo has an established merge-migration precedent
   (`d4c7b2a9e6f1_merge_heads_before_avatar_url.py`, `abc5f2a8867d_merge_crm_connections_and_dashboard_.py`)
   for exactly this situation.**
3. Add to `apps/api/config.py`, in a new `## ─── Job-change detection (v1, same-tenant) ───` block
   (mirroring the `agent_detection_enabled` block's inline-comment style, including the "flipping
   this in a real environment is an explicit post-migration-live-apply operator action" comment):
   - `job_change_detection_enabled: bool = False`
   - `job_change_recheck_daily_cap: int = 200` (placeholder — tune from observed per-site
     resolution-budget sizing before enabling live, same posture as `site_ingest_limit_per_minute`)
   - `job_change_staleness_days: int = 75` (matches `company_graph_staleness_days` precedent —
     same number, deliberately not re-derived, since both represent "how stale is too stale to
     trust a cached professional-data snapshot")
   - `job_change_min_confidence: float = 0.5` (corroboration-gate threshold; see step 5)
4. Write the 4 safety gates in `apps/api/services/job_change_detector.py`, mirroring
   `identity_signals.py`'s structure exactly (datacenter IP / proxy-VPN / suppression /
   `do_not_resolve`):
   - `_passes_recheck_gates(db, visitor, email) -> bool` — reuses
     `company_resolver.is_datacenter_ip` / `is_proxy_or_vpn`, `suppression.is_email_suppressed`,
     and a direct `Visitor.do_not_resolve` check (no need for `identity_signals.py`'s
     `_visitor_do_not_resolve` cross-join helper — this module already HAS the `Visitor` row in
     hand, unlike `identity_signals.py` which only has an email at write time). Any gate failure
     is a silent skip (never raises), matching `identity_signals.py`'s posture — a re-check must
     never break the calling event/task path.
5. Write `check_job_change_recheck_budget(site_id) -> bool` using a Redis counter key
   `job_change_recheck:{site_id}:{yyyy-mm-dd}` (UTC date), `INCR` + `EXPIRE` pattern. **VALIDATE
   correction:** `Site.daily_resolution_budget`'s own check
   (`usage_limits.check_identify_budget` → `get_identify_usage`) is DB-row-COUNT-based, not Redis —
   there is nothing to literally mirror there. The real Redis `INCR`+`EXPIRE` idiom already in this
   codebase is `usage_limits.py`'s OSINT scan counter (`_osint_count_key` /
   `get_osint_usage` / `increment_osint_usage`, `usage_limits.py:160-188`) — copy that shape
   (self-expiring TTL via `if count == 1: expire(...)`, fail-open to 0 on Redis error). This also
   means AC-4's budget isolation is structural, not just parallel bookkeeping: the two budgets live
   in entirely different stores (Redis key vs. DB row count), so there is no shared code path that
   could accidentally let one counter influence the other. Returns `False` (budget exhausted)
   without incrementing further once the cap is hit.
6. Write `compare_company(prior: str, new: str) -> bool` — normalize both (lowercase, strip
   whitespace, strip common legal suffixes: "Inc", "Inc.", "LLC", "Ltd", "Corp", "Co" — use a
   small fixed suffix list, not a fuzzy-match library — no new dependency), return `True` only if
   normalized strings differ.
7. Write `corroborate(pdl_data: dict, work_email_domain: str | None, company_graph_hit: bool) ->
   tuple[bool, float, str]` — fixed source-tier confidence constants (PDL=0.8, Apollo=0.7,
   domain-fallback-only=0.2), returns `(passes_gate, confidence, corroboration_signal_label)`.
   Rule: passes only if `confidence >= job_change_min_confidence` AND at least one of
   (`work_email_domain` present and not in `_FREE_MAIL_DOMAINS`, `company_graph_hit is True`).
   A personal-email-only result (domain in `_FREE_MAIL_DOMAINS`, no `company_graph_hit`) always
   returns `passes_gate=False` regardless of numeric confidence — hard rule per AC-6, not just a
   threshold effect.
8. **Per-section test gate:** run `.venv/bin/python3.11 -m pytest tests/unit/test_job_change_detector.py -k "compare_company or corroborate or gates or budget" -q` — write these unit tests alongside steps 6/7/4/5 (TDD: write the failing test first per each function, then implement). Must be green before Phase 2.

## Implementation Checklist — Phase 2: Detection Pipeline + Triggers

9. Write `run_recheck(db, visitor, site) -> JobChangeEvent | None` in `job_change_detector.py`:
   - short-circuit `False` immediately if `not settings.job_change_detection_enabled` (belt +
     suspenders — callers should already gate on the flag, but the service itself must also
     refuse to run with the flag off, matching `agent_detection_enabled`'s pattern where the
     classifier itself checks the flag).
   - `check_job_change_recheck_budget(site.site_id)` → return `None` if exhausted.
   - `_passes_recheck_gates(...)` → return `None` if any gate fails.
   - fetch existing `EnrichmentProfile` for `(site.site_id, visitor.visitor_id)` — if none exists,
     return `None` (nothing to compare against; first-time enrichment is the existing
     `resolution_tasks.py` path, untouched).
   - call `_enrich_pdl` (fallback `_enrich_apollo` on PDL miss, matching the existing waterfall
     order in `enricher.py`) using the visitor's stored identified email — **read-only reuse, no
     signature change to either function**.
   - `compare_company(existing.company_name, fresh_result["company_name"])` → if `False`, return
     `None` (no material change, no row written — matches AC-5/AC-7's "no event written" branch).
   - `corroborate(...)` → if gate fails, return `None` (noise filtered, matches AC-6).
   - **AC-11 hard rule:** this entire function must make zero `beam_identity_graph` reads or
     writes. Do not import `_upsert_beam_identity` or any `beam_identity_graph`-touching function
     from `identity_resolver.py` — the only cross-file reuse in this function is `enricher.py`'s
     `_enrich_pdl`/`_enrich_apollo` (provider calls) and `company_resolver.py`'s
     `CompanyGraphNode` read (same-request corroboration lookup, which is `company_graph`, NOT
     `beam_identity_graph` — these are two structurally distinct tables; confirm this distinction
     explicitly in the unit test for AC-11, do not conflate them).
   - if all gates pass: call `record_job_change(db, site, visitor, existing, fresh_result,
     confidence, signal_label)`.
10. Write `record_job_change(...)`:
    - insert one `JobChangeEvent` row (before/after pair, per AC-7 — no history log).
    - update the existing `EnrichmentProfile.company_name`/`.job_title` in place (existing
      overwrite behavior continues for "current" fields — this is the same `_upsert_profile`-style
      write, either by calling `enricher._upsert_profile` directly if its signature permits, or by
      inline `setattr` matching its pattern — decide based on what `_upsert_profile`'s actual
      signature allows without modification; do not modify `_upsert_profile`).
    - trigger the draft-outreach path (Phase 3, step 15) and the segmenter-signal write (Phase 3,
      step 16) as the last two sub-steps, inside the same function, after the `JobChangeEvent` row
      is committed — so a failure in draft-creation never blocks the event record itself (wrap the
      draft-trigger call in try/except + `logger.warning`, matching the
      `graph-erasure-compliance` plan's C-12 defensive-wrap precedent for a non-critical
      side-effect).
11. Write `apps/api/tasks/job_change_tasks.py`:
    - `recheck_returning_visitor(visitor_id: str, site_id: str)` — Celery task, thin wrapper:
      loads `Visitor`+`Site`, calls `run_recheck`, commits.
    - `sweep_stale_profiles()` — Celery task (Trigger B): query `EnrichmentProfile` rows where
      `enriched_at < now - job_change_staleness_days`, joined to `Visitor` where
      `identity_status` indicates identified (mirror `resolution_tasks.py`'s exact
      `identity_status` filter value for "already identified", found via that file's read at
      research time — likely `!= "anonymous"` or an explicit identified-tier value depending on
      whatever `identity-vocab-reconcile` has landed by EXECUTE time; **re-check the live
      `identity_status` vocabulary at EXECUTE time** since that program is actively reconciling
      it — **VALIDATE confirmed the live value today is the literal string `"anonymous"`**
      (`resolution_tasks.py:80`, `Visitor.identity_status` default `"anonymous"`,
      `models/visitor.py:61`) — use `!= "anonymous"` unless `identity-vocab-reconcile` has landed
      a replacement vocabulary by EXECUTE time, in which case follow that program's new filter
      exactly), bounded to a per-run cap (reuse `job_change_recheck_daily_cap` as the same bound, or a
      separate sweep-specific cap constant — decide and document at EXECUTE), calls `run_recheck`
      per selected visitor, commits per-visitor (not one giant transaction, to avoid one bad row
      blocking the whole sweep).
12. Add `sweep-job-change-stale-profiles` entry to `celery_app.py`'s `beat_schedule` dict — low
    frequency (e.g. daily `crontab(hour=3, minute=0)`, off-peak, distinct from the existing hourly
    `process-pending-visitors-hourly` entry — do not collide cadence with that task since both
    touch `EnrichmentProfile`).
13. Hook Trigger A into the event-ingest path: locate the exact call site where a new `Event` row
    is persisted for an already-identified visitor (research sub-step — likely
    `apps/api/routers/events.py` or wherever `services/event_ingest.py`-equivalent lives; confirm
    exact file/function before editing). Add a flag-gated call:
    `if settings.job_change_detection_enabled and visitor.identity_status indicates identified:
    job_change_tasks.recheck_returning_visitor.delay(visitor.visitor_id, site.site_id)` —
    fire-and-forget, async task dispatch, must not add latency or a hard dependency to the ingest
    request path (matches the existing pattern where heavy work is always deferred to Celery, not
    inlined into the ingest handler).
14. **Per-section test gate:** `.venv/bin/python3.11 -m pytest tests/unit/test_job_change_detector.py tests/unit/test_job_change_config.py -q` green, plus new integration tests for AC-2/AC-3/AC-4/AC-11 (see Verification Evidence table) run against `docker compose -f infra/docker-compose.yml up -d postgres redis`.

## Implementation Checklist — Phase 3: Surfacing, Erasure, Regression

15. Wire `record_job_change`'s draft-trigger sub-step to the existing `AutoDrafter` entry point
    (`apps/api/services/auto_drafter.py`) — call whatever its `generate_for_visitor`-equivalent
    method is (confirm exact method name/signature at research time; do not assume), passing
    enough context (visitor, site, trigger reason = job-change) for it to draft a
    re-engagement-flavored email. Assert the resulting campaign/draft record lands with
    `status == "draft"` and that zero SendGrid/send-path calls occur in the same code path
    (AC-8's structural requirement — same "structurally cannot send" pattern already proven for
    `is_emailable_identity`/agent-exclusion, reused here as a design precedent, not a copy of that
    specific guard). **VALIDATE confirmed:** `AutoDrafter.generate_for_visitor(visitor,
    enrichment_data, social_context, user)` has exactly one existing caller today
    (`apps/api/tasks/resolution_tasks.py:158`) — use its exact call shape as the template rather
    than guessing the signature.
16. Add `job_changed_at` as a readable segmenter signal in `apps/api/agents/segmenter.py` —
    additive input field only (mirrors the `ai_source` precedent cited in Decision #5): the
    segmenter's existing prompt-construction / tool-loop input assembly gains one more optional
    field per visitor, sourced from the most recent `JobChangeEvent.detected_at` for that
    `(site_id, visitor_id)` if any exists. **Do not touch intent-score defaults or bypass any
    existing scoring path** — this is purely an additional signal, per SPEC's explicit
    "signal not bypass" framing. **VALIDATE confirmed:** `segmenter.py`'s per-visitor `profile`
    dict already carries additive signal fields in exactly this shape (`ai_source`,
    `identity_status`) — add `job_changed_at` as one more dict key beside them, same pattern.
17. Add `get_job_change_events(db, site_id, limit=50) -> list[JobChangeEvent]` to
    `apps/api/services/hot_contacts.py` — a plain read-only query on `JobChangeEvent` ordered by
    `detected_at DESC`, site-scoped. **This is deliberately NOT a reuse of the phantom-pointer
    imported-contact "active this week" query family** (`has_merged_child` correlated subquery
    etc.) — that logic solves a different problem (counting activity on phantom-vs-merged-child
    rows) that does not apply here; `JobChangeEvent` rows are already directly attributable to a
    real `(site_id, visitor_id)`. Document this distinction inline as a module comment so a future
    reader doesn't assume the two query families should be unified.
18. Extend `apps/api/routers/hot_contacts.py` with a new endpoint (or an additive field on the
    existing response, per the plan's own PLAN-level judgment call — INNOVATE left exact shape
    open) exposing `get_job_change_events` results, site-scoped via the existing
    `_verify_site_access`-equivalent auth dependency this router already uses (reuse, don't
    reinvent). **VALIDATE confirmed:** the actual dependency is
    `apps.api.dependencies.verify_site_access` (not a router-local `_verify_site_access`) — reuse
    that import. **Also read `hot_contacts.py`'s own module docstring before adding a route**: it
    documents a real FastAPI route-registration-order hazard (a route in one file can silently
    swallow a route in another file registered later if a prefix collides) — confirm the new
    route/field does not reintroduce that hazard.
19. Edit `apps/api/routers/visitors.py` `delete_visitor_data` — add `"job_change_events"` to the
    DELETE-loop table tuple, per Constraint C-1's live-state-check rule above.
20. **Regression checkpoint** — run the narrowest representative check against every overlapping
    previously-verified surface:
    - `EnrichmentProfile` overwrite path: `.venv/bin/python3.11 -m pytest tests/unit/test_content_enrich.py -q` (confirms `_upsert_profile`/enricher path unaffected)
    - `identity_signals.py` 4-gate pattern precedent: `.venv/bin/python3.11 -m pytest tests/unit/test_identity_signals.py -q` (**VALIDATE confirmed this file exists** with exactly the 4-gate test shape — `test_rejects_datacenter_ip` / `test_rejects_proxy_vpn` / `test_rejects_suppressed_email` / `test_rejects_do_not_resolve` — use it as the literal structural template named in Test Infra Improvement Notes below) to ensure this plan's new gates don't accidentally share/collide with that module's Redis keys or suppression calls
    - `is_emailable_identity` exclusion regression: `.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py -q` (confirms no accidental interaction with agent-origin exclusion — this plan never touches that guard, but it's a cheap high-value check given both modules write near identity/outreach eligibility)
    - `delete_visitor_data` existing cascade: **VALIDATE confirmed no existing test file
      (`tests/integration/*.py`) references `delete_visitor_data` today** — `grep -rl
      "delete_visitor_data" tests/integration/*.py` returns zero matches. This is a real,
      pre-existing test-infra gap, not a maybe — do not spend EXECUTE time searching for a file
      that isn't there. Instead: this plan's own new AC-12 integration test (seed a
      `job_change_events` row, call `DELETE /{site_id}/{visitor_id}/data`, assert the row is gone)
      is upgraded to also assert every pre-existing table in the 6-table tuple
      (`resolution_logs`/`identified_visitors`/`enrichment_profiles`/`events`/`segment_members`/`visitors`)
      still deletes correctly — making it double as the first-ever automated regression proof for
      the erasure endpoint, closing the gap this plan discovered instead of merely working around it.
    - full unit regression: `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` exits 0
21. **Per-section test gate:** full AC matrix (see Verification Evidence table below) green.

---

## Acceptance Criteria

This plan carries all 14 SPEC acceptance criteria (AC-1 .. AC-14) verbatim from
`job-change-detection_SPEC_07-08-26.md`. Each is proven by name in the Verification Evidence
table below (`proven by:` = the named gate row, `strategy:` = Fully-Automated / Hybrid /
Agent-Probe per row). No SPEC AC is dropped, descoped, or silently merged — AC-9 and AC-14 each
carry one supplementary Agent-Probe row in addition to their Fully-Automated/Hybrid proof, matching
the SPEC's own stated strategy for those two rows.

## Phase Completion Rules

- **Phase 1 (Model/Migration/Config/Safety Gates) complete when:** step 8's per-section test gate
  is green (`compare_company` / `corroborate` / gates / budget unit tests pass) AND the migration
  offline `--sql` validation (step 2) is clean in both directions.
- **Phase 2 (Detection Pipeline + Triggers) complete when:** step 14's per-section test gate is
  green — unit tests plus the AC-2/AC-3/AC-4/AC-11 integration tests pass against
  `docker compose -f infra/docker-compose.yml up -d postgres redis`.
- **Phase 3 (Surfacing, Erasure, Regression) complete when:** step 21's full AC matrix (all rows in
  Verification Evidence) is green AND step 20's regression checkpoint shows PASS/FIXED for every
  overlapping surface (no BLOCKED regression left open).
- **Plan-level VERIFIED bar:** all three phases complete per above, validate-contract gates
  recorded, AND Known-Gaps #1-#4 are explicitly carried forward into the phase report as
  documented residuals (not silently dropped) — this plan cannot reach `✅ VERIFIED` while flag
  defaults to OFF everywhere per AC-1; "VERIFIED" here means "code-complete and test-proven with
  flag off," not "enabled in production" (enabling is explicitly Out Of Scope per SPEC).

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Unit: flag default `False` in `Settings()` | Fully-Automated | AC-1 |
| Integration: returning identified visitor, flag OFF → zero recheck activity, zero `job_change_events` rows | Fully-Automated | AC-1 |
| Integration: seed `EnrichmentProfile(company_name="Acme")`, simulate return-visit `Event`, mocked provider → recheck call fires via existing enrichment path | Fully-Automated | AC-2 |
| Integration: multiple identified visitors with stale `EnrichmentProfile` + no recent visit; run `sweep_stale_profiles()` directly → selects bounded subset | Fully-Automated | AC-3 |
| Integration: drive recheck volume for one site past `job_change_recheck_daily_cap` → further rechecks refused; `Site.daily_resolution_budget` counter unaffected (asserted directly) | Fully-Automated | AC-4 |
| Unit: `compare_company()` fed (stored, re-checked) pairs — true differences flagged; normalization-equivalent pairs ("Acme Inc." vs "Acme, Inc") not flagged | Fully-Automated | AC-5 |
| Unit: `corroborate()` — (a) high-confidence + work-email-domain match → passes; (b) low-confidence → rejected; (c) company differs, only personal-email domain, no other signal → rejected | Fully-Automated | AC-6 |
| Integration: trigger confirmed job change → exactly one `JobChangeEvent` row with correct before/after values; `EnrichmentProfile.company_name` updated to new value | Fully-Automated | AC-7 |
| Integration: trigger confirmed job change → campaign/draft record created with `status == "draft"`; assert zero SendGrid call occurs in the same flow | Fully-Automated | AC-8 |
| Playwright: job-change trigger element present/visible on dashboard for a site with a seeded confirmed event | Hybrid | AC-9 (automated presence check) |
| Agent-Probe: UX/content placement judgment on the job-change dashboard surface | Agent-Probe | AC-9 (supplementary) |
| Unit/integration: visitor with confirmed job-change event is identifiable via segmenter's signal-reading path (mocked segmenter input, no live Gemini call) | Fully-Automated | AC-10 |
| Integration: job-change detection run makes zero `beam_identity_graph` reads/writes (spy/mock on graph access functions), even when a cross-tenant graph row exists for the same person | Fully-Automated | AC-11 |
| Integration: seed `JobChangeEvent` row for a visitor, call `DELETE /{site_id}/{visitor_id}/data`, assert row is gone after commit — extended per step 20 to also assert the pre-existing 6-table tuple still deletes correctly (closes the pre-existing regression-coverage gap) | Fully-Automated | AC-12 |
| Unit: `do_not_resolve=True` visitor with stored `EnrichmentProfile` → recheck selection query/function excludes them | Fully-Automated | AC-13 |
| Static/schema: no `String` column named/shaped like a plaintext email field on `JobChangeEvent` | Fully-Automated | AC-14 (schema assertion) |
| Agent-Probe: schema review confirming `visitor_emails`/`EnrichmentProfile` remain sole PII holders, `JobChangeEvent` referenced by ID only | Agent-Probe | AC-14 (supplementary) |
| Regression: `EnrichmentProfile` overwrite path unaffected — `test_content_enrich.py` | Fully-Automated | Regression (non-AC) |
| Regression: `is_emailable_identity`/agent-exclusion untouched — `test_agent_origin_exclusion.py` | Fully-Automated | Regression (non-AC) |
| Regression: existing erasure DELETE-loop tables still delete correctly with new table appended | Fully-Automated | Regression (non-AC) |
| Offline migration validation: `alembic upgrade <head>:head --sql` + downgrade, both directions clean | Fully-Automated | Migration correctness (non-AC; Known-Gap #1 covers the live round-trip gap) |

## Test Infra Improvement Notes

- No existing test file directly covers a "4-gate safety check" pattern reused as a standalone
  unit under test — `identity_signals.py`'s equivalent tests (if they exist) should be located at
  research time and used as the structural template for this plan's own gate tests, to keep the
  two gate implementations testably consistent even though they are separate functions.
  **VALIDATE confirmed:** `tests/unit/test_identity_signals.py` exists and carries exactly this
  shape (`test_rejects_datacenter_ip`, `test_rejects_proxy_vpn`, `test_rejects_suppressed_email`,
  `test_rejects_do_not_resolve`) — copy its structure directly.
- `tests/integration/test_visitor_deletion.py` (or whatever the real erasure integration test file
  is named) should be confirmed to exist before Phase 3 step 20 — if it does not exist, that is
  itself a pre-existing test-infra gap this plan should flag in its final report rather than
  silently skip the regression check. **VALIDATE confirmed: it does not exist** (zero matches for
  `delete_visitor_data` anywhere in `tests/integration/`). Handled per step 20's updated
  instruction — this plan's own new AC-12 test closes the gap instead of working around it.

---

## Known-Gaps (recorded per INNOVATE decision, not solved by this plan)

1. **Migration live round-trip is Docker-gated.** Offline `--sql` validation only in this
   environment — matches every other migration in this program (see `all-context.md`'s repeated
   "NOT live-round-tripped" notes for the last 5 migrations in the chain). Do not claim this
   migration is live-verified; it is not, until an operator runs it against a disposable Postgres.
2. **Confidence table is an uncalibrated heuristic.** PDL=0.8/Apollo=0.7/domain-fallback=0.2 are
   placeholder numbers chosen for internal ordering consistency (matching provider tier order
   elsewhere in the codebase), not empirically tuned against real job-change ground truth. Flagged
   explicitly so a future operator does not mistake these for validated thresholds.
3. **`company_graph` coverage is sparse** (per `all-context.md`'s existing description of that
   table's coverage). Using it as one of two possible corroboration signals means real job-changes
   without a `company_graph` hit AND without a work-email domain will be under-detected (recall
   tradeoff, not a precision problem) — accepted per SPEC's explicit corroboration-requirement
   design (false negatives are the safe failure mode; false positives are the one AC-6 exists to
   prevent).
4. **`identity_status` vocabulary is in flux** — `identity-vocab-reconcile_07-08-26` is actively
   reconciling this exact field's values across two branches. Step 11's sweep filter and step 13's
   event-hook filter both reference `identity_status`; both must be re-checked against the live
   vocabulary at EXECUTE time, not hardcoded from this plan's draft-time assumption. **VALIDATE
   confirmed the live value today is `"anonymous"`** (see step 11 note) — this is the current
   baseline to diff against if the vocab has moved by EXECUTE time.

---

## Resume and Execution Handoff

1. **Selected plan file path:** `process/features/visitors-identity/active/job-change-detection_07-08-26/job-change-detection_PLAN_07-08-26.md` (this file)
2. **Last completed phase or step:** VALIDATE — Gate: PASS. Not yet executed.
3. **Validate-contract status:** written below — Gate: PASS, 07-08-26.
4. **Supporting context files loaded:** `process/features/visitors-identity/active/job-change-detection_07-08-26/job-change-detection_SPEC_07-08-26.md` (locked SPEC), `process/context/all-context.md`, `apps/api/models/enrichment.py`, `apps/api/services/identity_signals.py`, `apps/api/services/enricher.py` (partial), `apps/api/services/celery_app.py`, `apps/api/routers/visitors.py` (delete_visitor_data region), `apps/api/services/hot_contacts.py`, `apps/api/config.py` (flag-block precedents), and the other 3 active visitors-identity plans (identity-vocab-reconcile, graph-erasure-compliance, social-context-merge) for blast-radius conflict-checking. VALIDATE session additionally read `graph-erasure-compliance_PLAN_07-08-26.md` in full, `apps/api/services/usage_limits.py`, `apps/api/routers/hot_contacts.py`, `apps/api/services/auto_drafter.py`, `apps/api/tasks/resolution_tasks.py`, `apps/api/agents/segmenter.py`, and ran a live `alembic -c apps/api/alembic.ini heads` check.
5. **Next step for a fresh agent picking up mid-execution:** this plan's VALIDATE has run and produced `Gate: PASS` (see `## Validate Contract` below); proceed to EXECUTE. If EXECUTE was interrupted mid-phase, re-read the Phase [1/2/3] Implementation Checklist above to find the last-ticked step, re-verify the true alembic head (mind the multi-head note in Touchpoints/E-2) and the live `identity_status` vocabulary (Known-Gap #4) before continuing, and re-check Constraint C-1's live-state of `delete_visitor_data` before touching that function again.

## Validate Contract

Status: PASS
Date: 07-08-26
date: 2026-08-07
generated-by: outer-pvl

Parallel strategy: sequential (single-agent VALIDATE fan-out folded into one pass; EXECUTE
recommendation below)
Rationale: 3-phase single plan, blast radius confined to `apps/api`, no multi-package or
adversarial-coordination need — Layer 1 (4 dimensions) + Layer 2 (3 phase sections) were each
evaluated directly against source; no signal reached the parallel-subagent threshold (score 1/7 —
only S7 "5+ files in blast radius" present; S1/S2/S3/S4/S5/S6 absent since this is not a phase
program, has no 3+ viable competing directions left open, and no explicit user depth request).

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | flag defaults OFF; flag-off → zero recheck activity, zero rows written | Fully-Automated | `tests/unit/test_job_change_config.py::test_flag_defaults_false` + `tests/integration/test_job_change_detection.py::test_flag_off_zero_activity` | B |
| AC-2 | event-driven re-check fires on a returning identified visitor | Fully-Automated | `tests/integration/test_job_change_detection.py::test_event_driven_recheck_fires` | B |
| AC-3 | scheduled sweep selects a bounded subset of stale, non-returning visitors | Fully-Automated | `tests/integration/test_job_change_detection.py::test_sweep_selects_bounded_subset` | B |
| AC-4 | dedicated Redis budget cap, isolated from `Site.daily_resolution_budget` | Fully-Automated | `tests/integration/test_job_change_detection.py::test_budget_cap_isolated_from_resolution_budget` | B |
| AC-5 | `compare_company()` normalization-aware diff detection | Fully-Automated | `tests/unit/test_job_change_detector.py::test_compare_company_normalization` | B |
| AC-6 | `corroborate()` confidence + personal-email-exclusion gate | Fully-Automated | `tests/unit/test_job_change_detector.py::test_corroborate_gate_cases` | B |
| AC-7 | one minimal before/after row per confirmed transition; profile updated in place | Fully-Automated | `tests/integration/test_job_change_detection.py::test_confirmed_change_writes_minimal_row` | B |
| AC-8 | confirmed change → draft-status campaign, zero SendGrid calls in-flow | Fully-Automated | `tests/integration/test_job_change_detection.py::test_confirmed_change_creates_draft_only` | B |
| AC-9 | dashboard surface shows job-change trigger for a seeded event | Hybrid | Playwright smoke — `apps/web/e2e/job-change-dashboard.spec.ts` (precondition: seeded confirmed event + running app) | B |
| AC-9 (supplementary) | UX/content placement judgment | Agent-Probe | manual/agent review of dashboard placement against SPEC US-1/US-2 | B |
| AC-10 | job-change event readable as a segmenter signal | Fully-Automated | `tests/unit/test_segmenter.py::test_job_changed_at_signal_readable` (mocked segmenter input) | B |
| AC-11 | zero `beam_identity_graph` reads/writes during detection | Fully-Automated | `tests/integration/test_job_change_detection.py::test_no_beam_identity_graph_access` (spy/mock on graph functions) | B |
| AC-12 | erasure cascade includes `job_change_events`; regression-extended to cover the full 6-table tuple | Fully-Automated | `tests/integration/test_job_change_detection.py::test_erasure_cascade_deletes_job_change_events` | B |
| AC-13 | `do_not_resolve=True` visitors excluded from re-check selection | Fully-Automated | `tests/unit/test_job_change_detector.py::test_do_not_resolve_excluded` | B |
| AC-14 | no plaintext-email-shaped column on `JobChangeEvent` | Fully-Automated | `tests/unit/test_job_change_detector.py::test_no_plaintext_email_column` | B |
| AC-14 (supplementary) | schema review — PII stays in `visitor_emails`/`EnrichmentProfile` only | Agent-Probe | manual/agent schema review | B |
| Regression | `EnrichmentProfile` overwrite path unaffected | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_content_enrich.py -q` | A |
| Regression | `is_emailable_identity`/agent-exclusion untouched | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py -q` | A |
| Regression | 4-gate structural template consistency | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_identity_signals.py -q` | A |
| Migration | offline `--sql` upgrade/downgrade clean | Fully-Automated | `alembic -c apps/api/alembic.ini upgrade <observed-head>:head --sql` (both directions) | B |
| Migration (live round-trip) | schema applies cleanly on a disposable Postgres | Hybrid | Docker-gated live round-trip — Known-Gap #1 | D |

gap-resolution legend:
- A — proven now (gate passes in this cycle; these 3 regression suites already exist and are green pre-EXECUTE)
- B — fixed in this plan (gate added by this plan's checklist as a TDD stub, to be implemented at EXECUTE)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue) — see Known-Gap #1

C-4 reconciliation: the `strategy:` column above carries only Fully-Automated / Hybrid /
Agent-Probe. Known-Gap is never a strategy value — it appears only as gap-resolution `D` on the
migration live-round-trip row, a named residual, never the reason any AC passes.

Legacy line form (retained for existing validate-contract consumers):
- Unit/service logic (`compare_company`, `corroborate`, 4 safety gates, budget counter): Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_job_change_detector.py -q`
- Config defaults: Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_job_change_config.py -q`
- Detection pipeline + triggers (integration): Fully-automated: `.venv/bin/python3.11 -m pytest tests/integration/test_job_change_detection.py -m integration -q` | precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`
- Dashboard surface: Hybrid: Playwright `apps/web/e2e/job-change-dashboard.spec.ts` + precondition seeded confirmed event
- Migration: Fully-automated: `alembic -c apps/api/alembic.ini upgrade <observed-head>:head --sql` (offline) | known-gap: live round-trip Docker-gated (Known-Gap #1)
- Regression: Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_content_enrich.py tests/unit/test_agent_origin_exclusion.py tests/unit/test_identity_signals.py -q`

Failing stub (Fully-Automated rows):

```
test("should default job_change_detection_enabled to False in Settings()", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-1 flag default")
})
test("should write zero job_change_events rows when flag is off despite a qualifying return visit", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-1 flag-off no-op")
})
test("should fire a re-check via the existing enrichment path when a returning identified visitor has a stored EnrichmentProfile", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-2 event-driven recheck")
})
test("should select a bounded subset of stale non-returning identified visitors in sweep_stale_profiles()", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-3 scheduled sweep")
})
test("should refuse further rechecks once job_change_recheck_daily_cap is hit while leaving Site.daily_resolution_budget untouched", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-4 budget isolation")
})
test("should flag true company-name differences and ignore normalization-equivalent pairs in compare_company()", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-5 compare_company")
})
test("should pass corroborate() only with sufficient confidence plus a non-personal-email or company_graph signal, and reject personal-email-only", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-6 corroborate gate")
})
test("should write exactly one JobChangeEvent row with correct before/after values and update EnrichmentProfile.company_name on a confirmed change", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-7 minimal event row")
})
test("should create a draft-status campaign with zero SendGrid calls when a job change is confirmed", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-8 draft-only outreach")
})
test("should show the job-change trigger element visible on the dashboard for a site with a seeded confirmed event", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-9 dashboard presence")
})
test("should expose a confirmed job-change event as a segmenter-readable signal via mocked segmenter input", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-10 segmenter signal")
})
test("should make zero beam_identity_graph reads or writes during a job-change detection run, even with a matching cross-tenant graph row present", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-11 same-tenant-only")
})
test("should delete the job_change_events row (and the pre-existing 6-table tuple) on DELETE /{site_id}/{visitor_id}/data", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-12 erasure cascade")
})
test("should exclude do_not_resolve=True visitors from recheck selection", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-13 opt-out respected")
})
test("should have no String column named or shaped like a plaintext email field on JobChangeEvent", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-14 no plaintext PII")
})
```

Dimension findings:
- Infra fit: PASS — all referenced functions/files/precedents confirmed present on disk
  (`is_datacenter_ip`, `is_proxy_or_vpn`, `is_email_suppressed`, `_enrich_pdl`, `_enrich_apollo`,
  `CompanyGraphNode`, `generate_for_visitor`, `verify_site_access`, celery `beat_schedule`);
  backend-only blast radius, no port/container/proxy surface touched.
- Test coverage: CONCERN → resolved — the plan's own regression-checkpoint reference
  (`tests/integration/test_visitor_deletion.py`) does not exist on disk (confirmed via grep); the
  plan already anticipated this and has been updated (step 20) so AC-12's own new integration test
  closes the gap instead of depending on a file that isn't there. `identity_signals.py`'s 4-gate
  test file DOES exist and is confirmed usable as the literal structural template.
- Breaking changes: PASS — every touchpoint is additive (new table, new settings, new endpoint/
  field, one hardcoded-literal tuple append); zero existing function signatures change
  (`_enrich_pdl`, `_enrich_apollo`, `_upsert_profile`, `generate_for_visitor`, `is_email_suppressed`
  all confirmed untouched by this plan).
- Security surface: PASS — no plaintext PII column (AC-14), erasure cascade covered (AC-12) via a
  hardcoded string-literal tuple append (no injection surface — table names are not user input),
  auto-send guardrail enforced structurally (AC-8, zero SendGrid calls asserted), budget isolation
  is structural (separate Redis vs. DB stores, not just parallel counters), 4 safety gates reuse
  proven `identity_signals.py`-pattern functions. STRIDE quick pass found no new spoofing/
  tampering/repudiation/disclosure/DoS/elevation vector beyond what AC-4/AC-8/AC-11/AC-12/AC-13/
  AC-14 already gate.
- Phase 1 (Model/Migration/Config/Safety Gates) feasibility: PASS — mechanical feasibility
  confirmed for every referenced import; one CONCERN found and fixed in-plan (step 5's Redis
  budget-counter precedent pointed at the wrong existing helper — corrected to
  `usage_limits.py`'s OSINT counter, the real `INCR`+`EXPIRE` idiom in this codebase).
- Phase 2 (Detection Pipeline + Triggers) feasibility: PASS — `run_recheck`/AC-11 design is
  coherent and testable (structurally-cannot-touch-graph pattern mirrors
  `test_agent_origin_exclusion.py`, confirmed on disk); `identity_status` live value confirmed as
  `"anonymous"` today (Known-Gap #4 re-check instruction preserved for EXECUTE-time drift); Trigger
  A's exact ingest call site is correctly left as a research sub-step (not resolvable from static
  reads alone without tracing the live ingest router, and AC-2 tests the observable outcome, not
  the specific line).
- Phase 3 (Surfacing, Erasure, Regression) feasibility: PASS — `AutoDrafter.generate_for_visitor`'s
  one real caller and exact call shape confirmed (`resolution_tasks.py:158`); `delete_visitor_data`'s
  6-table tuple confirmed at `apps/api/routers/visitors.py:405-437`; Constraint C-1 re-confirmed
  live-current (graph-erasure-compliance plan's own status line: EXECUTE not yet started, blocked
  on identity-vocab-reconcile); `hot_contacts.py`'s real dependency name
  (`apps.api.dependencies.verify_site_access`) and its own route-ordering-hazard docstring
  cross-referenced as an execute-agent instruction.

Execute-Agent Instructions:
- E-1: Step 5 — use `usage_limits.py`'s OSINT Redis counter (`_osint_count_key` /
  `get_osint_usage` / `increment_osint_usage`, lines ~160-188) as the literal shape template for
  `check_job_change_recheck_budget`, not `Site.daily_resolution_budget`'s DB-count-based check.
  (Already applied as a plan-text correction above — this instruction pins it as binding.)
- E-2: If `alembic -c apps/api/alembic.ini heads` reports more than one head at EXECUTE time
  (observed live in this VALIDATE session — two heads present in this worktree's snapshot), do NOT
  arbitrarily chain onto either head. Either wait for a merge migration to land from whichever
  concurrent program produces one, or generate an explicit merge migration
  (`alembic merge heads -m "merge heads before add_job_change_events"`) before chaining this plan's
  own migration on top — this repo has direct precedent for this exact situation
  (`d4c7b2a9e6f1_merge_heads_before_avatar_url.py`,
  `abc5f2a8867d_merge_crm_connections_and_dashboard_.py`). Re-run `alembic heads` again immediately
  before generating the migration — do not trust a value observed earlier in the same session.
- E-3: Step 20/AC-12 — write the erasure regression assertion as part of the new AC-12 integration
  test (assert all 6 pre-existing tables plus the new `job_change_events` table are empty after
  the DELETE call), rather than searching for or assuming the existence of
  `tests/integration/test_visitor_deletion.py` (confirmed absent).
- E-4: Before adding the new `hot_contacts.py` route/field, read that file's own module docstring
  in full — it documents a live FastAPI route-registration-order hazard from a past incident in
  this exact router file. Confirm the new addition does not reintroduce a similar collision.
- E-5: Step 11/13 — the live `identity_status` value for "not yet identified" is confirmed today as
  the literal string `"anonymous"` (`apps/api/models/visitor.py:61`,
  `apps/api/tasks/resolution_tasks.py:80`). Re-check this against `identity-vocab-reconcile`'s
  landed state before EXECUTE, per Known-Gap #4 — do not silently reuse this session's snapshot
  without re-verifying.

Backlog Artifacts: none new — all 4 Known-Gaps are already recorded plan-internal residuals per
INNOVATE decision (see `## Known-Gaps` above); no separate backlog note is required since none of
them are silent or newly discovered by this VALIDATE pass.

Open gaps:
- Known-Gap #1 (migration live round-trip, Docker-gated) — carried forward, gap-resolution D.
- Known-Gap #2 (confidence table uncalibrated heuristic) — accepted design tradeoff, not a test gap.
- Known-Gap #3 (`company_graph` sparse coverage, recall tradeoff) — accepted design tradeoff, not a test gap.
- Known-Gap #4 (`identity_status` vocabulary in flux) — re-check-at-EXECUTE instruction (E-5), not a blocking gap.

What this coverage does NOT prove:
- The Fully-Automated unit/integration gates prove correctness of the pure functions
  (`compare_company`, `corroborate`) and the DB-backed flows under mocked providers — they do NOT
  prove real-world PDL/Apollo response quality or that the placeholder confidence numbers
  (Known-Gap #2) correctly separate real job-changes from noise in production traffic.
- The Hybrid Playwright gate (AC-9) proves the dashboard element is present and visible — it does
  NOT prove the copy/placement is good UX (that is the paired Agent-Probe row's job, and that row
  is itself a judgment call, not a mechanical proof).
- The AC-11 "zero beam_identity_graph access" gate proves the code path taken in the test scenario
  makes no such call — it does NOT prove no future refactor could reintroduce one; ongoing
  protection depends on the regression suite continuing to run this test on every change to
  `job_change_detector.py`.
- The offline migration `--sql` validation proves the DDL is syntactically well-formed and both
  directions parse cleanly — it does NOT prove the migration applies cleanly against a real
  Postgres with live data and constraints (Known-Gap #1, gap-resolution D).
- The Redis-budget-isolation test proves `Site.daily_resolution_budget`'s counter is unaffected in
  the test scenario exercised — it does not prove no other undiscovered code path could someday
  couple the two counters; the structural separation (different stores) makes this unlikely but not
  impossible to regress via a future unrelated change.

Gate: PASS (no FAILs; one CONCERN found and resolved via in-plan correction (step 5) plus 5
Execute-Agent Instructions (E-1..E-5); all 14 SPEC ACs carry a Fully-Automated or Hybrid proving
gate — vacuous-green check passes; the 4 pre-existing Known-Gaps are accepted, argued residuals
carried forward per INNOVATE, not new findings)

## Autonomous Goal Block

```
SESSION GOAL: Ship job-change detection v1 (same-tenant, flag-off) per locked SPEC — detect a
returning identified visitor's company change against the site's own EnrichmentProfile baseline,
gate on corroboration, record a minimal before/after event, and surface it as a draft outreach
trigger. 14 SPEC ACs, all validate-contract-gated.
Charter + umbrella plan: N/A — single plan, not a phase program (3 tightly-coupled internal
phases sharing one migration/one validate-contract, not independent phase-plan files).
Autonomy: standard /goal autonomous execution rules apply (see
process/development-protocols/orchestration.md §Autonomy Mode + §BLOCKED Escalation Path).
CONDITIONAL findings → apply fixes, proceed. BLOCKED → backlog + continue where safe;
irreversible/outward-facing action without explicit contract instruction → hard stop.
Hard stop conditions / safety constraints:
- Never auto-send outreach — every job-change trigger must land as a `draft`-status campaign only
  (AC-8); zero SendGrid/send-path calls in the detection flow, no exception for "hot" signals.
- Never read or write `beam_identity_graph` from this feature's code path (AC-11) — v1 is
  same-tenant only; cross-tenant detection is explicitly out of scope until identity-coop ships.
- Never store plaintext email or any PII beyond `visitor_id`/`site_id` references on
  `JobChangeEvent` (AC-14).
- Never let the Redis recheck-budget counter touch or influence `Site.daily_resolution_budget`
  (AC-4) — the two must remain structurally separate stores.
- Never skip the `do_not_resolve`/suppression re-check gates (AC-13) — same guard as first-time
  identification, no weaker rule for re-checks.
- Never generate the migration without first re-running `alembic -c apps/api/alembic.ini heads`
  live and confirming a single head (or resolving a multi-head state per Execute-Agent
  Instruction E-2) — never hardcode a head value.
- Never enable `job_change_detection_enabled` (or any related setting) in a real environment —
  shipping flag-OFF is the deliverable; enabling is a separate, later, explicit operator action.
- Re-check Constraint C-1's live state of `delete_visitor_data` (graph-erasure-compliance overlap)
  before editing that function, every time EXECUTE touches it.
Test gates:
- `.venv/bin/python3.11 -m pytest tests/unit/test_job_change_detector.py -q`
- `.venv/bin/python3.11 -m pytest tests/unit/test_job_change_config.py -q`
- `.venv/bin/python3.11 -m pytest tests/integration/test_job_change_detection.py -m integration -q` (precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`)
- `.venv/bin/python3.11 -m pytest tests/unit/test_content_enrich.py tests/unit/test_agent_origin_exclusion.py tests/unit/test_identity_signals.py -q` (regression)
- `alembic -c apps/api/alembic.ini upgrade <observed-head>:head --sql` (offline migration validation, both directions)
- Playwright `apps/web/e2e/job-change-dashboard.spec.ts` (AC-9 presence check)
Next phase: EXECUTE — `process/features/visitors-identity/active/job-change-detection_07-08-26/job-change-detection_PLAN_07-08-26.md`
Validate contract: inline in plan (see `## Validate Contract` above), Gate: PASS, 07-08-26
Execute start: Phase 1 checklist item 1 (`apps/api/models/job_change_event.py`) | full AC matrix in Verification Evidence | high-risk pack: yes (PII-adjacent table, budget/credit surface, outreach-trigger generation — see Blast Radius §Risk class)
```
