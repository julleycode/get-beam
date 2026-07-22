---
name: plan:evallayer-phase-05-company-resolution
description: "EvalLayer — Phase 05: Company-resolution -> human-outreach feed (agent IP -> existing identity_resolver waterfall via a synthetic Visitor -> resolved company/lead enters existing enrichment/email pipeline, hard-excluded from outreach until Phase 7's guard clears it)"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-05
---

# Phase 05 — Company Resolution → Outreach Feed

**Program:** evallayer
**Umbrella plan:** process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md
**Phase status:** 🚧 PLAN-SUPPLEMENTED — design locked (Option B: full waterfall reuse via a synthetic
per-agent-visit `Visitor` row). Ready for PVL.
**Report destination:** process/features/evallayer/active/evallayer_22-07-26/phase-05-company-resolution_REPORT_22-07-26.md

---

## Fresh RESEARCH — resolved (supersedes the "mandatory-fresh, not yet done" note)

The prior placeholder research gap (agentId `acf7d043d1d675da7`) is now closed. This supplement pass
read the real code in full:

- `apps/api/services/identity_resolver.py` — `resolve(visitor: Visitor) -> IdentifiedVisitor | None`
  (line 382). Gate order: `do_not_resolve` → suppression → prior-signal free path →
  `was_recently_attempted` (line 421, 30-day no-retry, keyed by `(site_id, visitor_id)`) →
  `check_daily_budget` (line 425, per-site daily cap) → no-IP check → VPN/proxy/Tor suspicion check
  (line 436-450, via `company_resolver.check_ip_privacy` + `is_ip_suspicious`) → identity-graph
  parallel waterfall → IP→company parallel waterfall (PDL/IPinfo) → Hunter/Apollo. Returns
  `None` at any gate; returns an `IdentifiedVisitor` via `_save_identified` (line 676) on a hit.
- `_save_identified` (line 676-≈770) constructs `IdentifiedVisitor(visitor_id=, site_id=, email=,
  full_name=, city=, region=, country=, resolution_provider=, confidence_score=)` — it does **not**
  accept or set any agent-origin marker. IntegrityError → rollback → re-fetch existing row (the
  established idempotent-insert pattern this plan's synthetic-visitor path must mirror).
- `apps/api/models/visitor.py` — `Visitor` (site_id, visitor_id, ip_address, first_seen, last_seen,
  intent_score default 0.0, do_not_resolve default false, unique `(site_id, visitor_id)` via
  `uq_visitors_site_visitor`); `IdentifiedVisitor` (site_id, visitor_id, email, resolution_provider,
  confidence_score, unique `(site_id, visitor_id)` via `uq_identified_site_visitor`).
- `apps/api/models/agent_visit.py` — `AgentVisit.resolved_company_id` already exists
  (`UUID(as_uuid=True), nullable=True`), explicitly documented as "no FK constraint in Phase 1 —
  Phase 5 adds the FK once company-resolution exists" (line 41-43).
- `apps/api/models/company.py` — `Company.id` is the FK target (`UUID`, PK).
- `apps/api/services/identity_classification.py` — `is_emailable_identity(provider, source_agent_visit_id=None)`
  already implements the AC10 override (Phase 7, done): unconditional `if source_agent_visit_id is
  not None: return False` before the person-level check. Confirms the exact literal field name this
  phase's new column MUST use: `source_agent_visit_id`.
- `apps/api/jobs/scheduler.py` — `_agent_verification_sweep_job` (line 135) currently does one
  thing: `agent_verification.run_verification_sweep(db)`. This phase adds a second call inside the
  same `try` block, after verification, in the same job (no new scheduler job needed).
- `apps/api/services/resolution_runner.py` (`run_resolution_for_site`, line 40), `apps/api/routers/
  visitors.py` (`list_visitors` line 54, `count_query` line 75), `apps/api/routers/visitors_helpers.py`
  (`_compute_visitor_stat_counts` line 130), `apps/api/tasks/segmentation_tasks.py` (`_check_triggers`
  line 26, `_run_segmentation_for_site` line 54), `apps/api/services/visitor_aggregator.py`
  (`_resolve_companies` line 323) — all read `Visitor` rows filtered only by `site_id` +
  status/intent predicates; none currently exclude synthetic agent-derived rows. Exact call sites
  and line numbers confirmed live in this pass (see Touchpoints).
- Alembic head confirmed via `alembic heads`: **`d11b39a6c843`** (Phase 1's `add_agent_visits_table`
  migration). This phase's migration's `down_revision` MUST be `d11b39a6c843`.

**Design decision (Option B — full waterfall reuse via synthetic Visitor), locked this pass:**
create a throwaway, idempotent `Visitor` row per resolvable `AgentVisit` and run the UNMODIFIED
`IdentityResolver.resolve()` against it, so the same provider waterfall, budget, and no-retry logic
humans get is reused byte-for-byte — no parallel/forked resolution code path to maintain.

**VALIDATE Amendment (PVL, mandatory — supersedes "resolve() called UNMODIFIED" below):** PVL
found that `resolve()` is NOT fully unmodified — `_save_identified()` (identity_resolver.py:676-772)
commits the new `IdentifiedVisitor` row via its own `await self.db.commit()` (line 752) BEFORE
`resolve()` returns control to the sweep. If the marker is set in a SEPARATE commit AFTER `resolve()`
returns (as originally designed below), there is a real, mechanically-confirmed window — spanning at
least one DB round-trip — where a freshly committed, potentially person-level `IdentifiedVisitor` row
exists with NO `source_agent_visit_id` marker, durable and visible to ANY other DB connection
(a concurrently running `campaign_sender` send cycle, a live `csv_exporter` export, or an API call).
This is the "deferred/2nd-batch marker" failure mode — it does not satisfy D2 (BINDING: "no window
where an agent-origin IdentifiedVisitor row exists without the marker"). **Required fix:** thread an
optional `source_agent_visit_id: str | None = None` parameter through `resolve()` and
`_save_identified()` in `identity_resolver.py`, defaulting to `None` for every existing (human)
caller — zero behavior change for the human path — and set it directly on the `IdentifiedVisitor(...)`
constructor call inside `_save_identified` so the marker is part of the SAME initial INSERT+COMMIT
transaction as the row's creation. This makes `identity_resolver.py` a MODIFY target (small, additive,
backward-compatible), not read-only as originally stated — see Blast Radius and Step C2 below.

---

## Purpose

When an agent visit's IP resolves via Beam's existing identity-resolution waterfall to a real
company/person, create or update a normal company/lead record in the existing human enrichment +
email-outreach pipeline. The agent itself is never the contactable entity — only the resolved
human/company contact, reached through Beam's existing consent/suppression/approval gates (SPEC
AC9). This phase reuses the same provider waterfall as human visitor resolution and therefore
consumes the existing identity-resolution budget (SPEC Resolved Open Question 4). Every row this
phase creates is marked with an unforgeable agent-origin marker so Phase 7's guard
(`is_emailable_identity`) and this phase's own human-data exclusion (AC2) both hold from the
instant the row exists — never as an afterthought.

---

## Entry Gate

- Phase 3 exit gate passed (agent visits are queryable via `/agents`). — assumed passed per umbrella
  phase ordering; confirm at PVL if not yet marked VERIFIED.
- Phase 4 exit gate passed (verification/confidence field exists). — same.
- Phase 7 is COMPLETE and VERIFIED (`phase-07-outreach-exclusion_REPORT_22-07-26.md`,
  `Classification: ✅ VERIFIED`). Its guard (`is_emailable_identity`) and D1-D6 BINDING contract are
  the release gate this phase must honor — **entry gate satisfied**, this is no longer a scheduling
  risk, only an implementation-correctness obligation (see D1-D6 below).

---

## Phase 7 BINDING Contract (from `phase-07-outreach-exclusion_REPORT_22-07-26.md` — this plan MUST honor all 6)

- **D1** — add `IdentifiedVisitor.source_agent_visit_id: str | None` using the EXACT literal field
  name `source_agent_visit_id` (the `getattr` call sites and the C5 tripwire test read this exact
  string).
- **D2** — set this field on EVERY agent-derived company-resolution row this phase creates — no
  window where an agent-origin `IdentifiedVisitor` exists without the marker.
- **D3** — never assign a `PERSON_LEVEL_PROVIDERS` value as `resolution_provider` on an
  agent-resolved record in a way that bypasses the marker — the marker is the enforcement point, not
  provider choice; belt-and-suspenders only.
- **D4** — do not add a 4th send/export path bypassing `is_emailable_identity` (not applicable — this
  phase adds no new send/export path).
- **D5/D6** — this phase's exit gate MUST re-run `tests/unit/test_agent_origin_exclusion.py`
  (including C5) against a REAL row created by this phase's own sweep path (not a hand-built mock),
  and MUST keep C5 green if this phase touches any of the 4 guarded files (it does not touch them,
  but the column addition is what C5's tripwire and D1's getattr depend on).

---

## Blast Radius

**Risk class: HIGH** — schema migration + auth/outreach-adjacent surface + identity-resolution
budget consumption + 6 human-data query sites. VALIDATE (PVL) is mandatory and may never be
skipped (per umbrella Hard Safety Constraints).

- 1 new Alembic migration (`apps/api/migrations/versions/`).
- `apps/api/models/visitor.py` — add `Visitor.is_agent_derived`.
- `apps/api/models/agent_visit.py` — add FK constraint on `AgentVisit.resolved_company_id` →
  `companies.id`; update docstring (the "no FK in Phase 1" note is now stale).
- `apps/api/models/visitor.py` — add `IdentifiedVisitor.source_agent_visit_id`.
- New service file: `apps/api/services/agent_company_resolution.py` (sweep implementation).
- New shared filter module: `apps/api/services/agent_visitor_filters.py` (the `human_only_visitor_filter()` predicate, imported by all 7 exclusion sites below — avoids hand-copying the same literal).
- `apps/api/services/identity_resolver.py` — **MODIFY (VALIDATE amendment, no longer read-only)**:
  add optional `source_agent_visit_id: str | None = None` param to `resolve()` and
  `_save_identified()`, default `None` (zero behavior change for existing human callers), set at
  `IdentifiedVisitor(...)` INSERT time — closes the GUARD #1 atomicity gap (see VALIDATE Amendment
  above).
- `apps/api/jobs/scheduler.py` — extend `_agent_verification_sweep_job` (2nd step).
- 7 AC2 exclusion sites (all import the shared predicate, do not hand-copy):
  1. `apps/api/routers/visitors.py::list_visitors` — `query` (line 74) + `count_query` (line 75). **CRITICAL.**
  2. `apps/api/routers/visitors_helpers.py::_compute_visitor_stat_counts` (line 130-174, all 5 aggregate-filter counts). **CRITICAL.**
  3. `apps/api/services/resolution_runner.py::run_resolution_for_site` eligibility query (line 55). **CRITICAL — prevents double-resolution of the synthetic row.**
  4. `apps/api/tasks/segmentation_tasks.py::_check_triggers` count query (line 37) + `_run_segmentation_for_site` select (line 56). **CRITICAL — agent-origin rows never enter a segment→campaign.**
  5. `apps/api/services/visitor_aggregator.py::_resolve_companies` (line 328). **HIGH — prevents an uncoordinated 2nd resolution attempt on the same synthetic Visitor.**
  6. `apps/api/routers/visitors.py` country-facet query (line 227-232, **MEDIUM**) + `get_visitor_detail` (line 485, **LOW** — synthetic-id lookups should 404, matching the existing unknown-id convention; confirm at EXECUTE whether an explicit filter or the natural site-scoped 404 already covers this — do not add a redundant check if the existing `.where(site_id=, visitor_id=)` + not-found already 404s cleanly for a synthetic id an owner would never guess).
  7. **`apps/api/tasks/resolution_tasks.py::_process_site`** eligibility query (line ~54-60,
     **MEDIUM, added at VALIDATE — missed by original RESEARCH**). This is a Celery task
     (`process_all_pending_visitors`) actively scheduled via `celery_app.py`'s beat schedule
     (confirmed, not dead code) with the SAME `identity_status=="anonymous" AND intent_score>=40`
     eligibility shape as `resolution_runner.run_resolution_for_site` (site #3 above) — but it was
     not enumerated in the original Blast Radius. It also calls `Enricher.enrich_tier1` and
     `AutoDrafter` on any resolved visitor, a higher-stakes path than a read-only count. Today it is
     INCIDENTALLY protected because the synthetic Visitor's `intent_score` stays 0 (aggregation only
     recomputes `intent_score` for visitor_ids with real `Event` rows; the synthetic row is created
     directly, bypassing `/events/ingest`) — but incidental protection is not an explicit exclusion.
     Add the shared filter here too, mirroring D3's treatment of `resolution_runner.py`.
- New unit test file: `tests/unit/test_agent_company_resolution.py` (or extend an existing Phase-5
  test file if one exists — confirm at EXECUTE via `find tests/unit -iname '*agent*'`).
- Extension to `tests/unit/test_agent_origin_exclusion.py` (AC10 real-row re-run, D5/D6).

**Estimated file count: ~13** (1 migration, 3 model edits across 2 files, 1 new service file, 1 new
filter module, 1 modified identity_resolver.py [VALIDATE amendment], 1 scheduler edit, 7 query-site
edits across 6 files — some files hit twice, 2 test files). Confirms Blast Radius signal S7 (5+
files) and S6 (high-risk class) for `vc-agent-strategy-compare` scoring at PVL.

---

## LOCKED Design

### 1. Migration (ONE Alembic revision, `down_revision = 'd11b39a6c843'`)

- `visitors.is_agent_derived` — `BOOLEAN NOT NULL DEFAULT false` (`server_default='false'`) — mirrors
  the existing `do_not_resolve` column pattern exactly (same file, same style).
- `identified_visitors.source_agent_visit_id` — `VARCHAR NULL` — **store as a STRING of the
  `AgentVisit.id` UUID, not a UUID-typed column** (matches the `str | None` signature Phase 7's
  `getattr` calls and the C5 tripwire already assume; do not change the type to UUID).
- `agent_visits.resolved_company_id` — **ADD FOREIGN KEY CONSTRAINT** → `companies.id` (column
  already exists, nullable, no FK per Phase 1's docstring — this migration only adds the constraint,
  it does not add or rename the column). Use `op.create_foreign_key(...)`, matching whatever FK
  naming convention the most recent migration touching a FK uses — confirm exact `ondelete` behavior
  is `SET NULL` (a deleted Company must not cascade-delete the AgentVisit row) at EXECUTE by reading
  one other FK-adding migration in `apps/api/migrations/versions/` for the house convention.
- Add the 3 corresponding model attributes to `Visitor`, `IdentifiedVisitor`, `AgentVisit` (see Blast
  Radius). Update `AgentVisit`'s docstring line 41-43 — it currently says "Phase 5 adds the FK once
  company-resolution exists"; that sentence becomes stale the moment this migration lands.

### 2. Synthetic-Visitor sweep (Option B — full waterfall reuse)

New service: `apps/api/services/agent_company_resolution.py::run_company_resolution_sweep(db:
AsyncSession, limit: int = 20) -> dict[str, int]` (mirror `run_verification_sweep`'s shape and
`run_resolution_for_site`'s `limit` convention). Wired as a 2nd step inside
`_agent_verification_sweep_job` (scheduler.py line 135-148), same `try` block, after the existing
verification-sweep call — no new scheduler job.

**Eligibility query:**
```python
select(AgentVisit).where(
    AgentVisit.resolved_company_id.is_(None),
    AgentVisit.ip_address.isnot(None),
).limit(limit)
```
Do **NOT** additionally gate on `verification_method` — `resolve()`'s own IP-quality gates (below)
are the correct and sufficient filter; a `verification_method == "ip-verified"` gate would be
redundant AND would wrongly exclude legitimate ua-only agent traffic from real (non-datacenter)
company networks.

**IP-quality — NO allowlist carve-out.** `resolve()` already skips suspicious/datacenter IPs via
`company_resolver.is_ip_suspicious` (identity_resolver.py line 436-450). This is **correct, not a
gap**: most recognized-vendor traffic (OpenAI/Anthropic/Perplexity crawler IPs) originates from the
vendor's own datacenter — resolving it would identify the AI vendor as "the company," not a real
customer. Only agent visits whose IP genuinely belongs to a real company's own (non-datacenter)
network should resolve. **Document this in the phase report, not just here:** "Most datacenter/
vendor agent traffic will NOT produce a lead — by design. Only agent visits from real company
networks (e.g. an employee's corporate NAT egress that happens to run an agentic tool) resolve."

**Per-row processing:**
1. Insert-or-fetch a synthetic `Visitor`, idempotent on `uq_visitors_site_visitor`, mirroring
   `_save_identified`'s IntegrityError → rollback → re-fetch pattern (identity_resolver.py line
   751-765):
   - `visitor_id = f"agent:{agent_visit.id}"`
   - `site_id = agent_visit.site_id`
   - `ip_address = agent_visit.ip_address`
   - `first_seen = agent_visit.first_seen_at`, `last_seen = agent_visit.last_seen_at`
   - `is_agent_derived = True`
   - `intent_score` left at model default `0.0` — deliberate defense-in-depth: `resolution_runner.
     run_resolution_for_site`'s own eligibility query already requires `intent_score >= 40`, and even
     with the new `_human_only()` filter added there (below), an `intent_score` of 0 means a synthetic
     row would never independently qualify for that separate sweep even if the exclusion filter were
     ever accidentally removed later.
2. **[VALIDATE amendment — supersedes the original "call resolve() UNMODIFIED" design]** Call
   `await resolve(synthetic_visitor, source_agent_visit_id=str(agent_visit.id))`. `resolve()` and
   `_save_identified()` in `identity_resolver.py` gain one new optional keyword parameter,
   `source_agent_visit_id: str | None = None`, threaded through every internal call site
   (`_check_prior_signals`, `_resolve_identity_graphs_parallel`, the direct Hunter/Apollo branches,
   `_check_beam_identity_network`) down to the single `IdentifiedVisitor(...)` constructor call in
   `_save_identified`. Every EXISTING (human) caller of `resolve()`/`_save_identified()` omits the
   argument and gets `None` — byte-identical behavior, zero regression risk.
3. **GUARD #1 (mandatory — now genuinely atomic, not deferred):** `_save_identified()` sets
   `source_agent_visit_id=source_agent_visit_id` directly on the `IdentifiedVisitor(...)` constructor
   call, so the marker is part of the SAME `self.db.add(identified)` + `await self.db.commit()`
   transaction that creates the row (identity_resolver.py line ~737-752) — there is no second,
   deferred commit and therefore no window where an unmarked row is ever durable. **Original design
   rejected at PVL:** setting the marker via a separate `UPDATE`/re-fetch AFTER `resolve()` returns
   was found to leave a real window (the row commits inside `_save_identified` at line 752, before
   `resolve()` returns) during which a concurrently running `campaign_sender`/`csv_exporter`/API read
   could observe an unmarked, potentially-emailable row — the "deferred/2nd-batch marker" failure
   mode. The one exception: `_save_identified`'s pre-existing email-dedup MERGE path (an agent-
   resolved email already matches a DIFFERENT, pre-existing `IdentifiedVisitor`) returns that existing
   `canonical` row WITHOUT creating a new one — the marker parameter has no row to attach to in this
   branch and nothing is set; note this as a documented Known Gap below (cross-contamination via
   email collision), not a GUARD #1 violation (no NEW unmarked agent-derived row is created either way).
4. Set `agent_visit.resolved_company_id` (the actual company/lead the human pipeline created —
   confirm at EXECUTE exactly which table/id the existing `_save_identified` → downstream
   enrichment path treats as "the company" for a resolved identity; if `IdentifiedVisitor` itself has
   no direct company FK, resolve via the existing `company_domain`/`Company` upsert path used by
   `visitor_aggregator._upsert_company`, calling the same helper against the synthetic visitor so the
   company record this phase creates is the SAME kind of `Company` row human resolution creates —
   not a parallel shape).
5. Budget/recency: consumed purely via `resolve()`'s own `check_daily_budget` /
   `was_recently_attempted` — the synthetic `visitor_id` debits the same shared per-site daily budget
   and inherits the same 30-day no-retry rule automatically. **No separate budget bucket, no new
   config flag.**

**Person-level results are allowed to fire and are non-emailable, not filtered out beforehand.** Do
not special-case `PERSON_LEVEL_PROVIDERS` at resolution time (D3 is about the marker being the
enforcement point, not about blocking certain providers from firing). Add an inline code comment at
the marker-setting call site: "A person-level match on an agent-originated IP is likely a company
employee, not the actual visitor — expected data-quality caveat; the `source_agent_visit_id` marker
makes it non-emailable regardless of provider (Phase 7 AC10 guard), so this is safe to allow."

### 3. AC2 exclusion — shared predicate (GUARD #2, mandatory)

New module `apps/api/services/agent_visitor_filters.py`:
```python
def human_only_visitor_filter():
    """SQLAlchemy predicate: Visitor.is_agent_derived.is_(False).

    Import this at every human-data query site instead of hand-copying the
    literal — single choke point if the exclusion semantics ever change.
    """
    from apps.api.models.visitor import Visitor
    return Visitor.is_agent_derived.is_(False)
```
Reference `human_only_visitor_filter()` at ALL 7 sites listed in Blast Radius (including the
VALIDATE-added `resolution_tasks.py::_process_site` site). Do not hand-copy
`Visitor.is_agent_derived.is_(False)` inline at each site — import and call the shared function so a
future semantics change (e.g. adding a second exclusion condition) touches one place.

At EXECUTE time, confirm each file:line still matches (line numbers may have drifted by the time
EXECUTE runs) before editing — this plan's line numbers are current as of this RESEARCH pass
(22-07-26).

---

## Implementation Checklist

### Step A — Research (COMPLETE this pass — see "Fresh RESEARCH — resolved" above)

- [x] A1. Read `identity_resolver.py` in full — confirmed `resolve(visitor)` signature, gate order,
      and `_save_identified` shape.
- [x] A2. Read the existing enrichment/lead-creation pipeline (`visitor_aggregator._resolve_companies`
      / `_upsert_company`, `resolution_runner.run_resolution_for_site`) — confirmed how a resolved
      identity enters the human pipeline.
- [x] A3. Confirmed identity-resolution budget accounting semantics — reused automatically via
      `check_daily_budget`/`was_recently_attempted`, no new bucket.
- [x] A4. Confirmed the mechanism ensuring the created record's contactable identity is never the
      agent-visit record — the `source_agent_visit_id` marker + Phase 7's `is_emailable_identity`
      override, set unconditionally per row (GUARD #1) before the sweep function returns.

### Step B — Migration

- [ ] B1. Write the Alembic migration: `visitors.is_agent_derived` (bool, not null, default false,
      server_default 'false'), `identified_visitors.source_agent_visit_id` (varchar, nullable), FK
      constraint on `agent_visits.resolved_company_id` → `companies.id` (`ondelete='SET NULL'` —
      confirm house convention against one recent FK migration first). `down_revision =
      'd11b39a6c843'`.
- [ ] B2. Add `Visitor.is_agent_derived: Mapped[bool]` to `apps/api/models/visitor.py`.
- [ ] B3. Add `IdentifiedVisitor.source_agent_visit_id: Mapped[str | None]` to
      `apps/api/models/visitor.py`.
- [ ] B4. Update `apps/api/models/agent_visit.py` — remove/replace the stale "no FK in Phase 1"
      docstring comment (line 41-43); the FK now exists at the DB level (SQLAlchemy model itself
      doesn't need a `ForeignKey()` declaration change unless the house convention elsewhere declares
      FKs at the ORM level too — confirm by checking one other FK'd column in an existing model).
- [ ] B5. **(VALIDATE amendment, mandatory — closes GUARD #1 atomicity gap).** In
      `apps/api/services/identity_resolver.py`: add `source_agent_visit_id: str | None = None` to
      `resolve()`'s signature and thread it through every internal path that can call
      `_save_identified` (`_check_prior_signals` incl. its 3 sub-checks, `_resolve_identity_graphs_parallel`,
      the direct Hunter/Apollo branches at the bottom of `resolve()`, `_check_beam_identity_network`).
      Add the same optional param to `_save_identified(...)` and set it directly on the
      `IdentifiedVisitor(...)` constructor call (line ~737-747) so the marker is part of the initial
      INSERT, not a later UPDATE. Every existing call site (human path) omits the argument → `None` →
      byte-identical behavior. This is the ONLY change to `identity_resolver.py` in this phase.

### Step C — Synthetic-visitor sweep implementation

- [ ] C1. Create `apps/api/services/agent_visitor_filters.py` with `human_only_visitor_filter()`.
- [ ] C2. Create `apps/api/services/agent_company_resolution.py` with
      `run_company_resolution_sweep(db, limit=20) -> dict[str, int]` implementing the eligibility
      query, per-row synthetic-Visitor insert-or-fetch, the
      `resolve(synthetic_visitor, source_agent_visit_id=str(agent_visit.id))` call (marker now set
      atomically inside `_save_identified` per B5 — no separate marker-setting step needed after
      `resolve()` returns), and `resolved_company_id` update, all per the LOCKED Design section above.
      Wrap per-row logic in isolated try/except (mirror `run_resolution_for_site`'s "one failure
      can't abort the batch" pattern) — one bad row must not block the rest of the sweep.
- [ ] C3. Wire `run_company_resolution_sweep` as a 2nd step inside `_agent_verification_sweep_job`
      (`apps/api/jobs/scheduler.py` line 135-148), same try block, after the existing verification
      call.

### Step D — AC2 exclusion (7 sites, all via `human_only_visitor_filter()`)

- [ ] D1. `apps/api/routers/visitors.py::list_visitors` — add filter to `query` (line 74) AND
      `count_query` (line 75).
- [ ] D2. `apps/api/routers/visitors_helpers.py::_compute_visitor_stat_counts` — add filter to the
      `.where(Visitor.site_id == site_id)` clause (line ~174) so all 5 conditional-aggregate counts
      inherit it.
- [ ] D3. `apps/api/services/resolution_runner.py::run_resolution_for_site` — add filter to the
      eligibility `select(Visitor).where(...)` (line 55).
- [ ] D4. `apps/api/tasks/segmentation_tasks.py` — add filter to `_check_triggers`'s count query
      (line 37) AND `_run_segmentation_for_site`'s select (line 56).
- [ ] D5. `apps/api/services/visitor_aggregator.py::_resolve_companies` — add filter to the
      `select(Visitor).where(...)` (line 328).
- [ ] D6. `apps/api/routers/visitors.py` country-facet query — add filter (line 227-232). For
      `get_visitor_detail` (line 485): confirm at EXECUTE whether the existing
      `site_id + visitor_id` lookup already 404s cleanly for an unguessable synthetic id, or whether
      an explicit filter is needed to avoid ever rendering a synthetic row in the UI if an id is
      somehow guessed/enumerated — add the filter defensively either way (LOW risk, cheap to add).
- [ ] D7. **(VALIDATE amendment, mandatory — 7th site, missed by original RESEARCH).**
      `apps/api/tasks/resolution_tasks.py::_process_site` — add filter to the eligibility
      `select(Visitor).where(...)` (line ~54-60). This is a scheduled Celery task
      (`process_all_pending_visitors`, confirmed live in `celery_app.py`'s beat schedule) that also
      triggers `Enricher.enrich_tier1` + `AutoDrafter` on resolved rows — higher stakes than a
      read-only count, so an explicit filter is required even though `intent_score=0` incidentally
      protects it today.

### Step E — Tests

- [ ] E1. New `tests/unit/test_agent_company_resolution.py` (Fully-Automated, mocked `AsyncSession` +
      monkeypatched `identity_resolver.resolve` per the `test_company_resolver.py` mocking
      convention — confirm exact fixture pattern by reading that file at EXECUTE):
      - AC9: synthetic-visitor path creates a `Company`/lead record; the contactable identity is the
        resolved human/company, never the `AgentVisit` record itself.
      - GUARD #1: `source_agent_visit_id` is set on every `IdentifiedVisitor` row created by the
        sweep, before the sweep function returns — assert directly on the persisted row, not just on
        a return value.
      - AC2 exclusion: 1 human `Visitor` + 1 agent-derived `Visitor` (`is_agent_derived=True`) in the
        same site → assert `list_visitors`, `_compute_visitor_stat_counts`,
        `run_resolution_for_site`'s eligibility query, `_run_segmentation_for_site`'s select, AND
        `resolution_tasks.py::_process_site`'s eligibility query (D7) all return/count only the human
        row (before/after count assertion — SPEC AC2's own phrasing).
      - GUARD #1 atomicity: assert `_save_identified` sets `source_agent_visit_id` on the
        `IdentifiedVisitor` in the SAME call that creates the row (e.g. assert the constructor/insert
        call received the kwarg, or assert no `UPDATE` statement targeting `source_agent_visit_id` is
        issued after the row's initial commit) — proves the marker is atomic, not deferred.
      - Budget/recency reuse: synthetic `visitor_id` debits the shared per-site daily budget and
        respects the 30-day no-retry rule — assert via `check_daily_budget`/`was_recently_attempted`
        mocks, not a new code path.
      - AC14 mock mode: sweep runs fully offline under `MOCK_EXTERNAL_APIS=true` with no live network
        access.
      - C5-style tripwire: parametrized text-search asserting the literal `"source_agent_visit_id"`
        string is present in this phase's new/touched files (mirrors Phase 7's C5 pattern —
        confirm exact assertion shape by reading `test_agent_origin_exclusion.py`'s C5 test).

      **Failing stub (TDD red-first, per `vc-test-coverage-plan`):**
      ```
      test("should set source_agent_visit_id on every IdentifiedVisitor row the sweep creates", () => {
        throw new Error("NOT IMPLEMENTED — TDD stub for: GUARD #1 marker-setting")
      })
      ```
      (Python/pytest equivalent — write as `def test_guard1_marker_always_set(): raise
      NotImplementedError(...)` at EXECUTE time; the JS-style block above is the tier-assignment
      convention placeholder, not literal syntax to paste into a `.py` file.)

- [ ] E2. **AC10 real-row re-run (Phase 7 D5/D6 — BINDING):** extend
      `tests/unit/test_agent_origin_exclusion.py` (or add a Phase-5-specific test in the new file)
      to insert a REAL `IdentifiedVisitor(source_agent_visit_id=<real AgentVisit.id str>)` created by
      calling the ACTUAL `run_company_resolution_sweep` path (not a hand-built mock row), then assert
      `is_emailable_identity(...)` returns `False` for it AND the existing C5 tripwire test stays
      green. This is the phase's own exit-gate obligation to Phase 7, not optional cleanup.
- [ ] E3. Integration (Docker-gated known-gap, documented not skipped): end-to-end sweep against a
      real Postgres — confirms the FK constraint, the unique constraints, and a real commit round-trip.
      Mark as known-gap in the plan's test coverage table (per `vc-test-coverage-plan` waterfall) with
      explicit rationale: no disposable Postgres available in this environment; the migration apply
      step below is the closest available proxy.

---

## Exit Gate

```bash
# Company/lead record created from a qualifying agent visit (AC9)
.venv/bin/python -m pytest tests/unit/test_agent_company_resolution.py -m unit -q
# Expected: all pass; a Company/lead record is created downstream of a synthetic-visitor
# resolution, and its contactable identity is the resolved human/company — never the
# AgentVisit record itself.

# AC10 real-row re-run (Phase 7 D5/D6 BINDING obligation)
.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q
# Expected: all pass (17+), including a REAL row created by this phase's own sweep path.

# Full regression (no pollution of human-side test suite)
.venv/bin/python -m pytest tests/unit -q
# Expected: 752 + N new passed, 2 skipped, 0 regressions vs Phase 7's EVL baseline.

# Mock mode coverage (AC14, this phase's reused external call)
MOCK_EXTERNAL_APIS=true .venv/bin/python -m pytest tests/unit/test_agent_company_resolution.py -m unit -q
# Expected: unit tests run fully offline under MOCK_EXTERNAL_APIS=true
```

- AC9, AC2, AC10 (real-row re-run), and the mock-mode portion of AC14 all pass.
- Phase 7's outreach-exclusion regression test (`test_agent_origin_exclusion.py`, incl. C5) stays
  green — release-gate condition already satisfied by Phase 7 itself; this phase's job is to not
  break it.
- Phase report written to report destination above.

---

## Public Contracts

- No new externally-visible API surface. Existing campaign/segment/email API contracts remain
  unchanged in shape; only new data enters via the existing pipeline, gated by Phase 7's
  already-VERIFIED guardrail. `IdentifiedVisitor` and `Visitor` gain new nullable/defaulted columns
  (additive, backward-compatible — no existing caller reads or writes them today, matching the
  pattern Phase 7 itself already established with `getattr(iv, "source_agent_visit_id", None)`).
- **(VALIDATE amendment)** `IdentityResolver.resolve()` and `_save_identified()` gain one new
  optional keyword parameter, `source_agent_visit_id: str | None = None` — fully backward-compatible;
  every existing (human) call site omits it and behaves identically. This is the same additive-kwarg
  pattern Phase 7 used for `is_emailable_identity(provider, source_agent_visit_id=None)`.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `.venv/bin/python -m pytest tests/unit/test_agent_company_resolution.py -m unit -q` | Fully-Automated | AC9 (lead created via synthetic-visitor path, contactable identity ≠ agent record) |
| Same file — GUARD #1 marker-set assertion | Fully-Automated | AC9 / D2 (BINDING) |
| Same file — AC2 before/after count assertion across all 7 exclusion sites (incl. D7) | Fully-Automated | AC2 |
| Same file — GUARD #1 atomicity assertion (marker set in the same INSERT as the row's creation, no deferred UPDATE) | Fully-Automated | D2 (BINDING) |
| Same file — budget/recency reuse assertion | Fully-Automated | SPEC Resolved Open Question 4 (shared budget, no new bucket) |
| Same file — mock-mode offline run | Fully-Automated | AC14 |
| Same file — C5-style literal-field tripwire | Fully-Automated | D1/D6 (BINDING) — literal `source_agent_visit_id` field name persists |
| `.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q` (extended with a real Phase-5-created row) | Fully-Automated | AC10 (real-row re-run, D5/D6 BINDING) — MUST stay green, 17+ passed |
| `.venv/bin/python -m pytest tests/unit -q` (full regression) | Fully-Automated | No regression vs the current 752-passed baseline (Phase 7 EVL) |
| Migration apply/rollback cycle (`alembic upgrade head` / `alembic downgrade -1`) against a disposable Postgres | Hybrid — Docker known-gap | Schema/FK correctness (no automated proof available in this environment; documented gap, not silently dropped) |
| Full sweep run against a real disposable Postgres | Hybrid — Docker known-gap | End-to-end round-trip proof beyond mocked-session unit coverage |

---

## Test Infra Improvement Notes

- No existing test file directly covers agent→company synthetic-visitor resolution — this phase's
  `tests/unit/test_agent_company_resolution.py` is new scaffolding, not an extension of prior
  coverage. Confirm at EXECUTE whether `find tests/unit -iname '*agent*'` turns up anything to
  extend instead of creating fresh (the umbrella's Phase 1-4 test files are candidates: `test_agent_
  classifier.py`, `test_agent_verification.py` if they exist under those or similar names).
- The Docker-gated migration-apply and full-sweep-integration gaps (Verification Evidence table,
  last 2 rows) are the only known-gaps this phase accepts, both because no disposable Postgres is
  available in this execution environment — not because a test could not conceivably be written.

---

## Known Gaps (Resolved via Backlog)

Both found at PVL (`vc-security` STRIDE pass). Neither blocks this phase's Gate — both err toward
the SAFE direction (lead-loss / staleness, never an outreach leak) and neither is fixable within
this phase's locked blast radius without expanding scope beyond company-resolution.

- **Cross-contamination via `_save_identified`'s email-dedup merge path.** Company-level providers
  (Hunter/Apollo) return "an arbitrary employee" at a resolved domain, so the same employee email can
  recur across different visitors from the same company network. If a REAL human visitor's later
  `resolve()` call returns an email that already matches an EARLIER agent-derived
  `IdentifiedVisitor.canonical` row (marked `source_agent_visit_id` non-None), `_save_identified`'s
  existing email-dedup logic (identity_resolver.py:704-731, unmodified by this phase) merges the
  human visitor into that canonical row — the human's identity then inherits the agent-origin marker
  and becomes permanently non-emailable. This is a lead-loss/data-quality bug, not a safety violation
  (it errs toward exclusion, never toward emailing an agent). known-gap: documented as NEW PLAN
  REQUIRED — see backlog/phase-05-identity-merge-collision_NOTE_22-07-26.md.
- **`AgentVisit` rollup staleness.** `AgentVisit` is an aggregate ROLLUP row per
  `(site_id, vendor, product_or_ua_token)` (confirmed: `agent_visit_persistence.py`'s
  `ON CONFLICT DO UPDATE` overwrites `ip_address` on every subsequent visit), not one row per
  individual visit. Once this phase's sweep sets `resolved_company_id` (non-null), the eligibility
  query (`resolved_company_id IS NULL`) permanently excludes that row from any future re-resolution
  attempt — even if later visits from the same vendor/token roll in from a DIFFERENT company's IP
  (e.g. a different employee's corporate egress). The company/lead created can go stale; this phase
  intentionally does not re-resolve on IP change (out of scope — would require re-architecting the
  eligibility query and budget accounting). known-gap: documented as NEW PLAN REQUIRED — see
  backlog/phase-05-rollup-staleness_NOTE_22-07-26.md.

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/evallayer_22-07-26/phase-05-company-resolution_PLAN_22-07-26.md`
- Last completed step: PLAN-SUPPLEMENT (Step 3 of the 7-step inner loop) — fresh RESEARCH done this
  pass, design locked (Option B), full checklist written (Steps B-E above).
- Validate-contract status: **written 22-07-26, Gate: PASS** (`generated-by:
  inner-pvl: phase-5`). PVL found and fixed 2 mandatory FAILs in-plan (GUARD #1 atomicity —
  `identity_resolver.py` gains an optional `source_agent_visit_id` kwarg; a 7th AC2 exclusion site,
  `resolution_tasks.py::_process_site`, D7) and recorded 2 non-blocking Known Gaps (identity-merge
  collision, AgentVisit rollup staleness — both backlog-noted, both safe-direction, excluded from the
  CONCERN/FAIL count per the Known-Gap exclusion rule).
- Supporting context files loaded: `evallayer-umbrella_PLAN_22-07-26.md` (Hard Safety Constraints,
  Stable Program Goal), `evallayer_SPEC_22-07-26.md` (AC2, AC9, AC10, AC14, Resolved Open Questions
  4 and 10), `phase-07-outreach-exclusion_REPORT_22-07-26.md` (BINDING D1-D6 contract), plus direct
  reads of `identity_resolver.py`, `visitor.py`, `agent_visit.py`, `company.py`,
  `identity_classification.py`, `scheduler.py`, `resolution_runner.py`, `visitors.py`,
  `visitors_helpers.py`, `segmentation_tasks.py`, `visitor_aggregator.py`, and the migrations
  directory (head confirmed: `d11b39a6c843`).
- Next step: **spawn `vc-execute-agent`** with the plan + validate-contract (Gate: PASS).
  Execute-agent instructions in the Validate Contract below specify the exact build order
  (migration+models → identity_resolver.py kwarg → sweep service → 7-site AC2 exclusion → tests).

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — research-agent: fresh pass complete this session — read `identity_resolver.py`,
      `visitor.py`, `agent_visit.py`, `company.py`, `identity_classification.py`, `scheduler.py`,
      `resolution_runner.py`, `visitors.py`, `visitors_helpers.py`, `segmentation_tasks.py`,
      `visitor_aggregator.py`, migrations head — all confirmed live, not inferred.
- [x] 2. INNOVATE — innovate-agent: Decision Summary — **Option B (full waterfall reuse via
      synthetic Visitor)** chosen over a parallel/forked resolution path, because it reuses budget,
      recency, and provider logic byte-for-byte with zero drift risk between human and agent
      resolution semantics. Rejected alternative: a standalone agent-specific resolution function
      duplicating `resolve()`'s gate logic — rejected for maintenance-drift risk (two copies of the
      same budget/recency/suspicion logic diverging over time).
- [x] 3. PLAN-SUPPLEMENT — plan-agent: full checklist written (Steps B-E above), all design
      questions from the prior placeholder-research gap resolved with concrete file/line-level
      detail.
- [x] 4. PVL — vc-validate-agent: full V1-V7 complete; validate-contract written; `vc-security`
      STRIDE scan run (GUARD #1 + GUARD #2 + synthetic-visitor cross-contamination surface); 2
      mandatory plan updates applied (GUARD #1 atomicity fix, 7th AC2 exclusion site); 2 non-blocking
      Known Gaps recorded (identity-merge collision, AgentVisit rollup staleness — both backlog-noted,
      excluded from the CONCERN/FAIL count). Gate: PASS.

**Validate-contract required before execute.** Satisfied — see `## Validate Contract` below.

- [x] 5. EXECUTE — all checklist items (B1-E3) done; exit-gate commands run and green
      (AC10 suite 18 passed, Phase-5 suite 25 passed, full regression 778 passed/2 skipped vs
      752/2 baseline = 0 regressions, AC14 mock-mode 25 passed). Migration chain valid offline
      (single head a1c7e4f92b83). 2 within-blast-radius deviations recorded (see ## Deviations).

## Deviations

Both within the declared blast radius; recorded per EXECUTE deviation-handling (autonomous /goal).

- **DEV-1 (GUARD #1 threading mechanism).** Plan P1/E2 prescribed threading the
  `source_agent_visit_id` kwarg through every intermediate resolve() helper
  (`_check_prior_signals`, `_resolve_identity_graphs_parallel`, the Hunter/Apollo branches,
  `_check_beam_identity_network`) down to `_save_identified`. **Implemented instead** via resolver
  instance state: `resolve()` stashes the value on `self._active_source_agent_visit_id` at the top of
  every call; `_save_identified` reads it (explicit kwarg still wins) and sets it on the
  `IdentifiedVisitor(...)` constructor. **Both `resolve()` and `_save_identified()` keep the optional
  kwarg** (public-contract change honored). **Rationale:** the Hunter/Apollo/PDL `_save_identified`
  calls live in separate mixin files (`identity_providers/hunter.py|apollo.py|pdl.py`) that are NOT in
  the declared Blast Radius/Touchpoints ("the ONLY change to identity_resolver.py"). Kwarg-threading
  would force editing 3 undeclared files, EXPANDING the blast radius. Instance state keeps every change
  inside `identity_resolver.py` AND covers all resolution paths including the mixins — strictly more
  complete for the D2 atomicity guarantee. Impact: none negative; marker still atomic (asserted by the
  GUARD #1 atomicity test); zero human-path behavior change (default None). Within-blast-radius
  (implementation detail / same semantic operation).

- **DEV-2 (AC2 sites D1 + D6-facet via the shared helper).** Plan D1/D6 listed adding the filter at
  `list_visitors` `query`+`count_query` and the country-facet query. **Implemented** by seeding
  `human_only_visitor_filter()` once inside the shared `_build_visitor_filters()` helper, which both
  `list_visitors` (query+count) and the country-facet endpoint consume — a single edit covers both.
  `get_visitor_detail` (D6 second part) got its own explicit filter. **Rationale:** explicitly
  sanctioned by the validate-contract Section C ("adding human_only_visitor_filter() INSIDE that helper
  … would cover both with one edit and reduce future drift risk; left as an EXECUTE-time discretionary
  choice"). Impact: DRY choke point, less drift risk; behavior identical. Within-blast-radius.
- [x] 6. EVL — independent `vc-tester` re-run confirmed all Fully-Automated gates GREEN: AC10 suite
      18/18 (incl. real-row re-run), Phase-5 suite 25/25, full regression 778 passed/2 skipped (0
      regressions vs 752/2 baseline), AC14 mock-mode 25/25. Static review confirmed GUARD #1 atomic
      + no instance-state leak, all 7 AC2 sites via the shared helper, no agent-email path. 2
      Docker known-gaps carried forward (migration apply/rollback, integration sweep) — no new
      follow-up stubs (2 pre-existing backlog notes already cover the safe-direction residuals).
      EVL HANDOFF SUMMARY written; CONTEXT_PARTIAL: none.
- [x] 7. UPDATE PROCESS — phase report finalized (Phase 7 D1-D6 contract fulfillment recorded),
      umbrella `## Current Execution State` + Program Status Table updated, blast-radius registry
      finalized. Commit NOT done this session (vc-git-manager next, per task instruction).

---

## Touchpoints

- `apps/api/migrations/versions/` — 1 new migration file, `down_revision = 'd11b39a6c843'`.
- `apps/api/models/visitor.py` — add `Visitor.is_agent_derived`, `IdentifiedVisitor.source_agent_visit_id`.
- `apps/api/models/agent_visit.py` — FK constraint + stale-docstring update.
- `apps/api/models/company.py` — read-only (FK target, no edit).
- `apps/api/services/agent_company_resolution.py` — new file.
- `apps/api/services/agent_visitor_filters.py` — new file.
- `apps/api/services/identity_resolver.py` — **MODIFY (VALIDATE amendment)**: add optional
  `source_agent_visit_id` param to `resolve()` + `_save_identified()`, default `None`, set at INSERT
  time (closes GUARD #1 atomicity gap; zero behavior change for existing human callers).
- `apps/api/services/identity_classification.py` — read-only (Phase 7's guard, consumed not edited).
- `apps/api/jobs/scheduler.py` — extend `_agent_verification_sweep_job`.
- `apps/api/routers/visitors.py` — `list_visitors`, country-facet query, `get_visitor_detail`.
- `apps/api/routers/visitors_helpers.py` — `_compute_visitor_stat_counts`.
- `apps/api/services/resolution_runner.py` — `run_resolution_for_site`.
- `apps/api/tasks/segmentation_tasks.py` — `_check_triggers`, `_run_segmentation_for_site`.
- `apps/api/services/visitor_aggregator.py` — `_resolve_companies`.
- `apps/api/tasks/resolution_tasks.py` — **(VALIDATE amendment)** `_process_site` eligibility query
  (7th AC2 exclusion site, D7).
- `tests/unit/test_agent_company_resolution.py` — new.
- `tests/unit/test_agent_origin_exclusion.py` — extended (AC10 real-row re-run).

---

## Validate Contract

Status: PASS
Date: 22-07-26
date: 2026-07-22
generated-by: inner-pvl: phase-5

Parallel strategy: sequential
Rationale: Signal score 4/7 (S4 phase-program, S5 user-requested rigor/depth, S6 highest-risk class
in the program — schema + outreach-adjacent + billing-budget surface, S7 13 blast-radius files)
formally clears the parallel-subagents threshold, but strategy-by-fit overrides: this VALIDATE pass
required deep, sequential code-tracing across a single dependency chain (`identity_resolver.py` →
`agent_company_resolution.py` → the 7 exclusion sites → the registry/umbrella cross-references) where
each finding depended on having read the previous file — no independent, parallelizable slices.
Simple Mode single-pass synthesis was used (Layer 1 4 dimensions + Layer 2 1 section, performed
directly in this session via direct file reads rather than spawned parallel Agent-tool calls),
consistent with `vc-validate-findings` Simple Mode guidance, but with substantially deeper mechanical
verification than Simple Mode's baseline given the HIGH risk class (every file:line claim in the
plan was re-confirmed against live code, not taken on trust).

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC9-1 | Qualifying agent visit creates/updates a Company/lead via the existing human pipeline; contactable identity is never the AgentVisit record | Fully-Automated | tests/unit/test_agent_company_resolution.py (AC9 assertions) | A |
| D2-1 (GUARD #1, plan update B5/C2) | source_agent_visit_id is set atomically in the SAME INSERT+COMMIT that creates the IdentifiedVisitor row — no deferred/2nd-batch marker | Fully-Automated | tests/unit/test_agent_company_resolution.py (GUARD #1 atomicity assertion, added at PVL) | B |
| AC2-1 (7 sites, plan update D7) | Human Visitor/Event data, stats, resolution eligibility, segmentation eligibility all exclude agent-derived rows at every enumerated site including the VALIDATE-added 7th (resolution_tasks.py) | Fully-Automated | tests/unit/test_agent_company_resolution.py (AC2 before/after count assertion across 7 sites) | B |
| OQ4-1 | Synthetic visitor_id debits the shared per-site daily budget and inherits the 30-day no-retry rule — no new bucket | Fully-Automated | tests/unit/test_agent_company_resolution.py (budget/recency reuse assertion) | A |
| AC14-1 | Sweep runs fully offline under MOCK_EXTERNAL_APIS=true | Fully-Automated | tests/unit/test_agent_company_resolution.py (mock-mode offline run) | A |
| D1/D6-1 (tripwire) | Literal field name source_agent_visit_id persists across all touched files | Fully-Automated | tests/unit/test_agent_company_resolution.py (C5-style tripwire) | A |
| AC10-1 (D5/D6 BINDING) | Agent-origin override holds against a REAL Phase-5-created row (not a mock) | Fully-Automated | tests/unit/test_agent_origin_exclusion.py (extended, real-row re-run) | A |
| — | No regression vs the 752-passed/2-skipped baseline | Fully-Automated | pytest tests/unit -m unit -q | A |
| — | Migration apply/rollback correctness | Hybrid | alembic upgrade head / alembic downgrade -1 against a disposable Postgres | D — Docker unavailable in this sandbox; documented, not silently dropped |
| — | Full sweep round-trip against a real Postgres | Hybrid | end-to-end sweep run against a disposable Postgres | D — Docker unavailable in this sandbox |

gap-resolution legend: A — proven now (gate passes in this cycle); B — fixed in this plan (gate
added by this plan's checklist, this PVL cycle); C — deferred to a named later phase/plan; D —
backlog test-building stub (named residual; keep-active; continue).

C-4 reconciliation: the `strategy:` column above carries only the 3 proving strategies
(Fully-Automated / Hybrid / Agent-Probe). The 2 Docker-gated Hybrid rows are named residuals with a
documented reason (no disposable Postgres in this sandbox), not silently passed.

Legacy line form:
- Company-resolution sweep + GUARD #1/#2 (agent_company_resolution.py + agent_visitor_filters.py
  + 7 exclusion sites + identity_resolver.py kwarg): Fully-automated:
  pytest tests/unit/test_agent_company_resolution.py -m unit -q | Fully-automated
  AC10 real-row re-run: pytest tests/unit/test_agent_origin_exclusion.py -m unit -q
  | Fully-automated full regression: pytest tests/unit -m unit -q (baseline 752
  passed / 2 skipped) | known-gap: migration apply/rollback + full sweep integration, both Docker-gated
  (no disposable Postgres in this sandbox).

Dimension findings:
- Infra fit: PASS — backend-only (apps/api/models, apps/api/services, apps/api/routers,
  apps/api/tasks, apps/api/jobs, tests/unit); no container/worker/proxy/runtime surface beyond
  the existing scheduler job pattern (Phase 4 precedent); FK ondelete='SET NULL' confirmed as the
  house convention (re-verified against a2e6c9b4d1f8_add_referral_fields.py and
  cd811a8b1f32_baseline_schema.py); alembic head re-confirmed live via `alembic heads` = d11b39a6c843,
  matching the plan's down_revision.
- Test coverage: CONCERN → resolved via plan updates. The originally-planned GUARD #1 assertion only
  checked the post-state (marker present on the persisted row) — this proves the END STATE but not
  ATOMICITY (that no separate UPDATE created the window). Added an explicit atomicity assertion
  (E1 update) requiring the test to confirm the marker is part of the INSERT call, not a follow-up
  UPDATE. Docker-gated known-gaps (migration apply/rollback, full sweep integration) are consistent
  with the identical environment-gap pattern already accepted in Phases 1-4 — not phase-5-specific.
- Breaking changes: PASS (after plan update) — IdentifiedVisitor/Visitor gain additive
  nullable/defaulted columns; AgentVisit.resolved_company_id gains a FK on an already-existing
  nullable column (no shape change); IdentityResolver.resolve()/_save_identified() gain one
  optional kwarg defaulting to None — every existing (human) call site is unaffected, same additive
  pattern Phase 7 established for is_emailable_identity. No public API/contract shape change.
- Security surface (vc-security STRIDE lens on GUARD #1, GUARD #2, the synthetic Visitor, the FK,
  and the marker literal-name tripwire): **FAIL → resolved via 2 mandatory plan updates.**
  - **Tampering / Elevation-of-Privilege — GUARD #1 atomicity (CRITICAL, found and fixed):** the
    original design ("call resolve() UNMODIFIED, set the marker via a separate UPDATE/re-fetch
    after resolve() returns") does NOT achieve "same commit boundary." Direct code inspection of
    identity_resolver.py::_save_identified (lines 737-772) confirms it commits the new
    IdentifiedVisitor row via its own `await self.db.commit()` (line 752) BEFORE resolve() returns
    control to the sweep. This creates a real, mechanically-confirmed window — spanning at least one
    DB round-trip — during which a freshly committed, potentially person-level IdentifiedVisitor row
    is durable and visible to ANY other DB connection (a concurrently running campaign_sender send
    cycle, a live csv_exporter export, or an API read) with NO source_agent_visit_id marker set.
    Since is_emailable_identity returns True for person-level providers when the marker is None,
    this is exactly the "deferred/2nd-batch marker" failure mode — a genuine violation of D2 (BINDING).
    **Fixed via Plan Update P1** (see below): thread an optional source_agent_visit_id kwarg through
    resolve()/_save_identified(), set at IdentifiedVisitor(...) construction time so the marker
    is part of the initial INSERT+COMMIT — closes the race entirely, zero behavior change for existing
    (human) callers.
  - **Info-disclosure / Repudiation — cross-contamination via email-dedup merge (found, accepted as
    Known Gap, non-blocking):** _save_identified's pre-existing email-dedup merge path can, in
    either temporal order, merge a real human's resolved identity into an agent-marked canonical row
    (or vice versa) if the SAME employee email is returned by a company-level provider for both an
    agent-derived and a human-derived visitor from the same company network. This errs toward the
    SAFE direction (a real human's identity may become incorrectly non-emailable — lead loss — never
    an agent record becoming emailable). Accepted as a documented, backlog-noted residual; does not
    threaten the AC10/D2 core guarantee.
  - **Elevation-of-Privilege — GUARD #2 completeness (found and fixed):** re-confirmed all 6
    originally-listed AC2 exclusion sites against live code (file:line matches confirmed for
    list_visitors, _compute_visitor_stat_counts, run_resolution_for_site, segmentation_tasks.py both
    functions, visitor_aggregator._resolve_companies, and the country-facet query). Found a 7th,
    previously unenumerated site: apps/api/tasks/resolution_tasks.py::_process_site — a LIVE,
    Celery-beat-scheduled task (confirmed via celery_app.py) with the same intent_score >= 40
    eligibility shape as resolution_runner.py (already fixed at D3), that ALSO triggers
    Enricher.enrich_tier1 + AutoDrafter on any resolved row. Today it is incidentally protected
    because the synthetic Visitor's intent_score stays 0 (confirmed: visitor_aggregator.py's
    intent-score recompute only touches visitor_ids with real Event rows; the synthetic row bypasses
    /events/ingest entirely) — but incidental protection is not an explicit, named exclusion.
    **Fixed via Plan Update P2** (D7): add human_only_visitor_filter() to this query too.
  - **Tampering (defense-in-depth, already covered by Phase 7):** the literal-field-name tripwire
    (test_source_agent_visit_id_literal_field_name_tripwire, Phase 7 C5) already guards against a
    silent rename; re-confirmed this phase's D1 column name matches the exact literal Phase 7 expects.
  - **Denial-of-Service:** not applicable — this is a data-write/read-exclusion surface, no new
    unbounded-cost operation (the sweep's limit=20 mirrors the existing sweep convention).
- Section A (Migration + Models, Step B): PASS — down_revision='d11b39a6c843' re-confirmed live via
  `alembic heads`; FK ondelete='SET NULL' matches house convention (2 other migrations checked);
  field name source_agent_visit_id (str, nullable) matches Phase 7's getattr expectation exactly.
  Gaps found: none beyond the general house-convention confirmation already noted as an EXECUTE-time
  task in the plan. Conflicts found: none. Highest-risk edit: the FK constraint addition on an
  existing column — mitigated by SET NULL (a deleted Company never cascade-deletes an AgentVisit).
- Section B (Synthetic-visitor sweep, Step C): CONCERN → FAIL until Plan Update P1 applied (GUARD #1
  atomicity, above) — now resolved. Mechanical feasibility: eligibility query, per-row idempotent
  insert-or-fetch, and budget/recency reuse are all correct relative to the code as read. Gap found
  (accepted as Known Gap, not blocking): AgentVisit is confirmed (via agent_visit_persistence.py)
  to be an aggregate ROLLUP row per (site_id, vendor, product_or_ua_token), not one row per visit —
  once resolved_company_id is set, the eligibility query permanently excludes that row from
  re-resolution even as new visits from a different company/IP roll into the same row over time. This
  is a data-quality/business-value gap (SPEC AC9's lead-value metric), not a safety gap — documented
  as a backlog note, not silently accepted. Highest-risk edit + mitigation: the GUARD #1 marker-setting
  call site — mitigated by Plan Update P1 (atomic INSERT-time marker) plus the E1 atomicity test.
- Section C (AC2 exclusion, Step D): CONCERN → resolved via Plan Update P2 (7th site, above).
  Mechanical feasibility: all 7 sites' edit targets confirmed present and uniquely matchable via
  fresh reads of live code (not re-derived from the plan's claims alone). Gaps found: the missed 7th
  site (above, now fixed); a minor DRY observation (list_visitors and the country-facet query both
  already call the shared _build_visitor_filters() helper — adding human_only_visitor_filter()
  INSIDE that helper instead of at 2 separate query-assembly points would cover both with one edit and
  reduce future drift risk; left as an EXECUTE-time discretionary choice, not a mandatory plan change,
  since the plan's per-site approach is still correct if followed exactly). Conflicts found: none.
  Highest-risk edit: resolution_tasks.py's query (D7, newly added) — mitigate by confirming the
  Celery beat schedule entry at EXECUTE time so the fix lands on the actually-scheduled task.
- Section D (Tests, Step E): PASS (after plan update) — the AC10 real-row re-run (E2) is well
  specified and directly proves the crux (a REAL row from this phase's own sweep path, not a mock).
  Added an explicit GUARD #1 atomicity assertion (E1 update, above) so the test proves the marker is
  atomic, not merely present in the end state.

Plan updates applied:
- P1 (mandatory — closes GUARD #1 atomicity gap): apps/api/services/identity_resolver.py gains an
  optional source_agent_visit_id: str | None = None parameter threaded through resolve() and
  _save_identified(), set directly on the IdentifiedVisitor(...) constructor call so the marker is
  part of the initial INSERT+COMMIT. Zero behavior change for existing (human) callers. Added as
  Blast Radius item, Step B5, rewritten Step C2/C3 language, updated Public Contracts, updated
  Touchpoints, updated Verification Evidence table (new GUARD #1 atomicity row), updated Step E1 test
  checklist (atomicity assertion).
- P2 (mandatory — closes GUARD #2 completeness gap): apps/api/tasks/resolution_tasks.py::_process_site
  added as the 7th AC2 exclusion site (Step D7); Blast Radius renumbered 6→7 sites; Touchpoints
  updated; Verification Evidence table updated (7-site count); Step E1 updated to assert this site too.

Execute-agent instructions:
- E1: Implement in this exact order — Step B (migration + 3 model attrs) → **B5 FIRST within the
  identity_resolver.py edit** (the source_agent_visit_id kwarg must land before Step C's sweep code
  calls resolve(..., source_agent_visit_id=...), otherwise the call raises TypeError) → Step C
  (filter module, sweep service, scheduler wiring) → Step D (all 7 exclusion sites, D1-D7) → Step E
  (tests). Do not reorder — C depends on B5; D's tests depend on C existing.
- E2: When editing identity_resolver.py, thread source_agent_visit_id through EVERY internal path
  that can reach _save_identified — _check_prior_signals (all 3 sub-checks: svid_reconcile, email
  capture, fingerprint match), _resolve_identity_graphs_parallel, the direct Hunter/Apollo branches
  near the bottom of resolve(), and _check_beam_identity_network. Missing even one path re-opens
  the atomicity gap for that specific resolution route. Grep for every _save_identified( call site
  after editing to confirm all pass the parameter through (or explicitly omit it for the human path,
  which is correct — only the sweep's own call passes a non-None value).
- E3: For D7 (resolution_tasks.py), confirm at EXECUTE time whether the process_all_pending_visitors
  Celery beat entry in celery_app.py is still live before editing — if the schedule entry has been
  removed since this PVL pass, downgrade D7's priority note in the phase report (still add the filter
  defensively, just note the reduced live-risk).
- E4: Do not attempt to "fix" the identity-merge-collision Known Gap in this phase — it is explicitly
  out of scope (see Known Gaps section) and would expand the blast radius into _save_identified's
  email-dedup logic beyond what P1 already touches.
- E5: Run the full exit-gate command set (test_agent_company_resolution.py, test_agent_origin_exclusion.py
  extended, full tests/unit) and paste all 3 result lines into the phase report before declaring DONE.
- E6 (High-risk pack): given schema + outreach-adjacent + billing-budget surface, invoke
  vc-risk-evidence-pack before treating this phase as ready for finalize — at minimum populate
  risk-gate.json (riskClass: schema/migration AND outreach/trust-boundary, dual-classed),
  context-snippets.json (the GUARD #1 atomicity fix + all 7 exclusion sites), verification.json
  (all Fully-Automated gate results), and review-decision.json. adversarial-validation.json is
  warranted given the outreach-exclusion attack surface — document the identity-merge-collision
  scenario there even though it is accepted as a Known Gap (ruled_out: false, rationale: accepted
  residual, safe-direction, backlog-tracked).

Backlog artifacts:
- process/features/evallayer/backlog/phase-05-identity-merge-collision_NOTE_22-07-26.md — real
  human lead can inherit an agent-origin non-emailable marker via email-dedup collision (lead-loss,
  safe-direction, not a safety violation).
- process/features/evallayer/backlog/phase-05-rollup-staleness_NOTE_22-07-26.md — AgentVisit's
  rollup semantics mean resolved_company_id sticks forever once set, even as the underlying IP
  changes across later visits (data-quality/business-value gap, not a safety gap).

Known gaps:
- Identity-merge collision (see backlog note above) — known-gap: documented as NEW PLAN REQUIRED.
- AgentVisit rollup staleness (see backlog note above) — known-gap: documented as NEW PLAN REQUIRED.
- Migration apply/rollback cycle unrun against a live Postgres (Docker unavailable in this sandbox) —
  same environment-gap pattern as Phases 1-4; close-the-gap command:
  `docker compose -f infra/docker-compose.yml up -d postgres redis` then run `alembic upgrade head`,
  `alembic downgrade -1`, `alembic upgrade head` in sequence.
- Full sweep integration round-trip against a live Postgres unrun (Docker unavailable) — close-the-gap
  command: `docker compose -f infra/docker-compose.yml up -d postgres redis` then
  `MOCK_EXTERNAL_APIS=true pytest tests/integration/test_agent_company_resolution_sweep.py -m integration -q`
  (integration test file to be authored at EXECUTE if not already scaffolded).

What this coverage does NOT prove:
- The GUARD #1 atomicity fix (P1) proves the marker is set in the same INSERT as the row's creation
  by code inspection + a unit-level assertion on the call; it does NOT prove, under real concurrent
  load against a live Postgres, that no OTHER isolation-level anomaly (e.g. a read-committed
  transaction reading an in-flight, uncommitted row) could observe a partial state — that class of
  behavior requires a live Postgres concurrency test, out of scope for this phase (Docker known-gap).
- The 7-site AC2 exclusion proof (mocked AsyncSession) does not prove query-plan/index-usage
  correctness against a real Postgres, nor does it prove the ABSENCE of an 8th site this pass did not
  find — mitigated by the same exhaustive-grep discipline Phase 7 used (grep -rn for
  select(Visitor) and Visitor.site_id patterns), re-run at PVL, but grep-based enumeration cannot
  formally prove completeness.
- The identity-merge-collision Known Gap is documented but NOT tested — no test asserts the described
  collision scenario occurs or is bounded; this is a genuine, accepted testing gap, not merely an
  implementation gap.
- The AgentVisit rollup-staleness Known Gap is documented but NOT tested — no test asserts that a
  changed IP on a subsequent visit fails to trigger re-resolution; this is a genuine, accepted
  documentation-only proof, not a regression-tested guarantee.
- Full unit regression proves no regression in the existing 752/2-skipped suite; it does not prove
  the absence of every possible interaction with code paths this phase does not touch (Playwright e2e
  dashboard flows, ClickHouse aggregation paths) — out of this phase's blast radius entirely.
(Required until C3 is implemented — temporary C3 mitigation)

Gate: PASS (2 mandatory FAILs found via `vc-security` STRIDE scan — GUARD #1 atomicity, GUARD #2
7th site — were fixed in-plan this same PVL cycle via Plan Updates P1/P2; no unresolved FAILs or
CONCERNs remain. The 2 Known Gaps below are pre-classified `known-gap: documented as NEW PLAN
REQUIRED` and are excluded from the CONCERN/FAIL count per the Known-Gap exclusion rule — both are
non-blocking, safe-direction residuals (never an outreach leak), both backlog-noted. This mirrors
Phase 7's own PVL precedent: Gate: PASS with 3 accepted Known Gaps, none touching the core safety
proof.)
Accepted by: session (autonomous, /goal execution) — the 2 Known Gaps (identity-merge collision,
AgentVisit rollup staleness) are recorded per the Known-Gap exclusion rule, not "accepted despite
blocking" — neither affects the AC2 pollution guarantee or the AC10/D2 outreach-exclusion guardrail
(both err toward the safe/exclusion direction). The 2 mandatory security-surface FAILs (GUARD #1
atomicity, GUARD #2 7th site) were fixed in-plan via P1/P2 before this Gate was set, per the Hard
Safety Constraints' zero-tolerance framing for the outreach-exclusion guardrail — they were not left
as accepted CONCERNs.
