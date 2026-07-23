---
name: plan:handoff-phase-01-fetch-events-tiering
description: "Handoff Detection — Phase 01: per-hit fetch events + on-demand/index tiering (H1)"
date: 23-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-01
---

# Phase 01 — Per-Hit Fetch Events + Tiering (H1)

**Program:** handoff
**Umbrella plan:** process/features/evallayer/active/handoff_23-07-26/handoff-umbrella_PLAN_23-07-26.md
**SPEC:** process/features/evallayer/active/handoff_23-07-26/handoff_SPEC_23-07-26.md (AC-H1-1, AC-H1-2, AC-H1-3)
**Phase status:** ⏳ PLANNED (locked checklist — ready for PVL)
**Report destination:** process/features/evallayer/active/handoff_23-07-26/phase-01-fetch-events-tiering_REPORT_23-07-26.md (flat in the program task folder)

---

## Purpose

Lay the foundation every downstream phase (H2, H3, and optionally the backlogged daily-timeseries
chart) depends on: capture every AI-agent hit as its own timestamped row (not just the rolled-up
`agent_visits` upsert), and tag each hit `on-demand` vs `index` using the vendor tokens already
present in `agent_classifier.py::_VENDOR_TOKENS`. This phase adds no new token discovery — it is a
tier-split read of an existing dict plus a new additive table and write path. Must be fail-open
and add zero new synchronous calls to the ingest hot path (SPEC Constraint 4).

---

## Entry Gate

- Phase 0 complete (umbrella + phase stubs created, validated)
- No upstream phase dependency (H1 is the program's foundation phase)

---

## LOCKED Decisions (RESEARCH + INNOVATE — confirmed against live code 23-07-26)

**Tier map — ALL 10 `_VENDOR_TOKENS` tokens have an explicit tier. No ambiguity remains.**

| Tier | Tokens |
|---|---|
| `on-demand` | `chatgpt-user`, `oai-searchbot`, `claude-user`, `claude-searchbot`, `perplexity-user` |
| `index` | `gptbot`, `claudebot`, `anthropic-ai`, `perplexitybot`, `bytespider` |

- `claude-searchbot` (previously flagged as ambiguous) is **on-demand** — it is Anthropic's
  live-fetch-on-user-query bot (analogous to `oai-searchbot`/`perplexity-user`), not a crawler.
  `anthropic-ai` (a separate, distinct token in the same `_VENDOR_TOKENS["anthropic"]` frozenset)
  is the crawler/index-tier token. Confirmed via `apps/api/services/agent_classifier.py:23-28` —
  both tokens coexist in the same vendor set; the tier split is orthogonal to vendor grouping.
- `classify_tier()` takes the raw UA token (`AgentClassification.product_or_ua_token`), not the
  vendor — this matches how `events.py` already calls `classify_agent()` and receives a
  `product_or_ua_token` field.
- No undocumented-vendor fallback path exists: `classify_agent()` returns `None` for anything not
  in `_VENDOR_TOKENS`, so `classify_tier()` is only ever called with one of the 10 known tokens.
  `classify_tier()` therefore has **no fallback/default branch** — it is a total function over a
  closed set of 10 literals, and a completeness test asserts the union of `_ON_DEMAND_TOKENS` and
  `_INDEX_TOKENS` equals every token flattened out of `_VENDOR_TOKENS.values()` (this is the
  "future token added without a tier decision" tripwire).
- Alembic head: **VALIDATE-corrected (23-07-26)** — the plan-authoring-time claim of "7 heads
  found via static revision-graph scan" was stale/inaccurate. Live-confirmed at VALIDATE via
  `cd apps/api && python -m alembic heads` (note: the console-script shebang for `alembic` itself
  is broken in this sandbox venv — use `python -m alembic`, not the `alembic` binary): exactly
  ONE head exists, `b3f9a1d2c7e5` (the AI-referral migration). `down_revision = "b3f9a1d2c7e5"` is
  therefore CONFIRMED correct right now, not just planned. Still re-run
  `cd apps/api && python -m alembic heads` immediately before EXECUTE writes the migration file,
  since another in-flight phase/program could add a competing head between VALIDATE and EXECUTE.
- Fail-open write pattern to mirror: `persist_agent_visit()` in `agent_visit_persistence.py`
  (try/except around the whole DB operation → `logger.warning(event, site_id=..., vendor=...,
  error=str(exc))` keys-only, no raw UA/IP/PII → `await db.rollback()` → `return None`). The new
  `persist_agent_fetch_event()` follows the exact same shape, with its own try/except (isolated
  from the rollup call — one insert failing must never roll back or block the other).

---

## Blast Radius

- `apps/api/models/agent_fetch_event.py` (new)
- `apps/api/migrations/versions/<hash>_add_agent_fetch_events_table.py` (new; additive-only,
  new table, no existing-table column changes; `down_revision = "b3f9a1d2c7e5"` — re-confirm via
  `alembic heads` immediately before EXECUTE writes the file)
- `apps/api/services/agent_classifier.py` — read-only tier lookup addition (`classify_tier()` +
  `_ON_DEMAND_TOKENS` frozenset); does NOT rewrite `_VENDOR_TOKENS` itself
- `apps/api/services/agent_visit_persistence.py` — additive per-hit write function, alongside
  (not replacing) the existing `persist_agent_visit()` rollup upsert
- `apps/api/routers/events.py` — one additive call into the new per-hit persistence path, inside
  the existing `if classification is not None:` agent branch (~line 142-145), wrapped fail-open
  (never raises into the 204 ingest response)
- `apps/api/config.py` — one new setting: `agent_fetch_event_retention_days: int = 90`
- `apps/api/services/retention.py` — extend the purge job to also delete `agent_fetch_events`
  rows older than the cutoff
- `apps/api/main.py` — register the new model import (mirror the existing `agent_visit` import
  line so the table is registered on `Base.metadata`)
- `tests/unit/test_agent_fetch_events.py` (new)
- `tests/integration/test_retention_purge.py` — extended, not replaced (VALIDATE-added E7; Hybrid,
  Docker-gated known-gap if infra unavailable)

---

## Public Contracts

- Existing `agent_visits` rollup table and its upsert contract are unchanged.
- `agent_classifier.py::classify_agent()`'s existing signature and return shape (`AgentClassification
  | None`) are unchanged — `classify_tier()` is a new, separate, pure function.
- No existing API response shape changes in this phase — ingest response stays `204`.

---

## Implementation Checklist

### Step A — Data model + migration

- [ ] A1. Create `apps/api/models/agent_fetch_event.py`:
  ```python
  class AgentFetchEvent(Base):
      __tablename__ = "agent_fetch_events"
      __table_args__ = (
          Index("idx_agent_fetch_events_site_created", "site_id", "created_at"),
          Index(
              "idx_agent_fetch_events_site_path_tier_created",
              "site_id", "page_path", "tier", "created_at",
          ),
      )
      site_id: Mapped[str] = mapped_column(String(50), nullable=False)
      vendor: Mapped[str] = mapped_column(String(30), nullable=False)
      raw_ua_token: Mapped[str] = mapped_column(String(50), nullable=False)
      tier: Mapped[str] = mapped_column(String(20), nullable=False)
      page_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
      ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
      verification_method: Mapped[str] = mapped_column(String(20), nullable=False, default="ua-only")
  ```
  `id: Mapped[uuid.UUID]` (pk, `default=uuid.uuid4`) and `created_at` come from the same base
  pattern as `AgentVisit` — read `apps/api/models/database.py::Base` to confirm whether
  `created_at`/`updated_at` are provided by a mixin or must be declared per-model (mirror
  whatever `AgentVisit` does; if `Base` forces an `updated_at` column, accept it — this table is
  logically append-only but do not fight the base-class contract). Do NOT declare a
  `ForeignKey()` on `site_id` — house convention (see `AgentVisit.resolved_company_id` comment)
  keeps cross-table FKs at the DB layer, not the ORM layer, for this model family.
- [ ] A2. Register the model import in `apps/api/main.py` — find the existing
      `from apps.api.models.agent_visit import AgentVisit  # noqa: F401 — register for create_all`
      line (confirmed real line, `apps/api/main.py:32`, at VALIDATE 23-07-26) and add a matching
      line immediately after it: `from apps.api.models.agent_fetch_event import AgentFetchEvent
      # noqa: F401 — register for create_all`.
- [ ] A3. Generate the Alembic migration: `create_table("agent_fetch_events", ...)` + both indexes
      from A1. `down_revision = "b3f9a1d2c7e5"` (re-confirm via `alembic heads` at EXECUTE time —
      see LOCKED Decisions above for the multi-head caveat). Clean, reversible `downgrade()` (drop
      indexes then table). Additive only — no changes to any existing table.

### Step B — Tier classification (LOCKED — no ambiguity remains, see LOCKED Decisions)

- [ ] B1. Add to `apps/api/services/agent_classifier.py`:
  ```python
  _ON_DEMAND_TOKENS: frozenset[str] = frozenset({
      "chatgpt-user", "oai-searchbot", "claude-user", "claude-searchbot", "perplexity-user",
  })


  def classify_tier(raw_ua_token: str) -> str:
      """Return "on-demand" or "index" for a known vendor token.

      Total function over the 10 tokens in ``_VENDOR_TOKENS`` — every token has
      an explicit tier (see module-level completeness test). Callers must only
      pass a token already confirmed non-None by ``classify_agent()``.
      """
      return "on-demand" if raw_ua_token in _ON_DEMAND_TOKENS else "index"
  ```
- [ ] B2. Add a module-level completeness assertion exercised by test (not a runtime assertion in
      the hot path): all tokens across every `_VENDOR_TOKENS` frozenset must appear in either
      `_ON_DEMAND_TOKENS` or be correctly classified `"index"` by `classify_tier`. Encode this as
      the `test_tier_map_covers_all_vendor_tokens` test in Step E (E2) — this is the tripwire that
      fails loudly if a future token is added to `_VENDOR_TOKENS` without a tier decision.

### Step C — Wire persistence + ingest

- [ ] C1. Add to `apps/api/services/agent_visit_persistence.py`:
  ```python
  async def persist_agent_fetch_event(
      db: AsyncSession,
      site_id: str,
      classification: AgentClassification,
      tier: str,
      ip_address: str | None,
      page_path: str | None,
  ) -> None:
      """Insert one append-only ``agent_fetch_events`` row. Fail-open, isolated
      from the ``persist_agent_visit`` rollup call — this insert's failure must
      never affect or be affected by the rollup upsert."""
      try:
          await db.execute(
              insert(AgentFetchEvent).values(
                  site_id=site_id,
                  vendor=classification.vendor,
                  raw_ua_token=classification.product_or_ua_token,
                  tier=tier,
                  page_path=page_path,
                  ip_address=ip_address or None,
                  verification_method=classification.verification_method,
              )
          )
          await db.commit()
      except Exception as exc:
          logger.warning(
              "agent_fetch_event_persist_failed",
              site_id=site_id,
              vendor=classification.vendor,
              error=str(exc),
          )
          await db.rollback()
          return None
  ```
  Use plain SQLAlchemy `insert()` (not `pg_insert(...).on_conflict_do_update`) — this is a plain
  append-only row insert, no upsert semantics needed.
- [ ] C2. Add `classify_tier` to the EXISTING top-level import line
      `from apps.api.services.agent_classifier import classify_agent` (confirmed real line,
      `apps/api/routers/events.py:15`) — becomes `from apps.api.services.agent_classifier import
      classify_agent, classify_tier`. Also add `from apps.api.services.agent_visit_persistence
      import persist_agent_visit, persist_agent_fetch_event` (extend the existing line at
      `events.py:16`). Do NOT use an inline/mid-function import — the file's convention is
      top-level imports only.
      Then, in the existing `if classification is not None:` agent branch (confirmed real lines
      142-145 at VALIDATE 23-07-26, immediately after the existing `await
      persist_agent_visit(...)` call and before `return Response(status_code=204)`):
  ```python
  tier = classify_tier(classification.product_or_ua_token)
  await persist_agent_fetch_event(
      db, batch.site_id, classification, tier, ip_address, agent_path
  )
  ```
  `ip_address` is confirmed already in scope (defined at `events.py:133`, before this branch).
  Gated by the same `agent_detection_enabled` check already wrapping this whole branch — no new
  gate needed. `agent_path` is the same variable already computed on the line above (first
  event's `page_path` in the batch — inherits the existing single-event-per-batch limitation,
  documented, not a new gap).
- [ ] C3. Confirm no new synchronous external call is introduced — this write is DB-only, same
      transaction/connection discipline as the existing rollup write. Two separate `db.commit()`
      calls per agent hit (one from `persist_agent_visit`, one from `persist_agent_fetch_event`)
      is ACCEPTED and documented — this trades one extra round-trip for full write-path isolation
      (a failure in one insert can never roll back or block the other).

### Step D — Retention

- [ ] D1. Add `agent_fetch_event_retention_days: int = 90` to `apps/api/config.py`, placed near
      the existing `event_retention_days: int = 90` setting (mirrors its convention exactly).
- [ ] D2. Extend `apps/api/services/retention.py`'s purge job: add a sibling function (or extend
      the existing purge job, matching whatever shape `purge_events_older_than` uses — table-exists
      check, dry-run support, batched delete, lock-guarded) that deletes `agent_fetch_events` rows
      older than `settings.agent_fetch_event_retention_days`. Confirm the exact function/job
      invocation shape (scheduler wiring, batch size constant, lock name) by reading
      `purge_events_older_than` in full during RESEARCH/EXECUTE before writing — do not guess the
      shape from this checklist alone. **VALIDATE-added:** this new purge function MUST get its own
      test (see E7 below) — do not close this item on E5's config-default check alone; E5 proves the
      setting exists, not that the purge behavior works.

### Step E — Tests

- [ ] E1. `tests/unit/test_agent_fetch_events.py::test_tier_classification` — parametrized: all 5
      on-demand tokens return `"on-demand"`, all 5 index tokens return `"index"` (proves AC-H1-2).
- [ ] E2. `tests/unit/test_agent_fetch_events.py::test_tier_map_covers_all_vendor_tokens` —
      flattens every token out of `agent_classifier._VENDOR_TOKENS.values()` and asserts each one
      is classified by `classify_tier()` without raising, and that the on-demand/index split
      matches the LOCKED tier map above exactly (this is the completeness tripwire from B2).
- [ ] E3. `tests/unit/test_agent_fetch_events.py::test_row_created_per_hit` — mocked
      `AsyncSession`: one call to `persist_agent_fetch_event` issues exactly one insert with the
      expected column values (site_id, vendor, raw_ua_token, tier, page_path, ip_address,
      verification_method); does not touch/duplicate the existing rollup path (proves AC-H1-1).
- [ ] E4. `tests/unit/test_agent_fetch_events.py::test_write_failure_isolated` — mocked
      `AsyncSession` raising on the fetch-event insert: function returns `None`, no exception
      propagates, `db.rollback()` called, no PII/raw-UA/IP in the logged warning (proves AC-H1-3).
- [ ] E5. `tests/unit/test_agent_fetch_events.py::test_retention_config_present` — asserts
      `settings.agent_fetch_event_retention_days == 90` by default.
- [ ] E6. Regression: `tests/unit/test_agent_classifier.py` and existing agent-visit persistence
      tests must pass unmodified (zero-regression program constraint).
- [ ] E7. **VALIDATE-added (closes a real test-coverage gap found at PVL):**
      `tests/integration/test_retention_purge.py::test_purges_old_agent_fetch_events` — mirror the
      existing `test_purges_old_keeps_recent` pattern in that same file (confirmed real file/pattern
      at VALIDATE 23-07-26: `patched_retention` fixture pointing `retention.async_session` at the
      test engine, `test_db` fixture for a live Postgres). Proves the D2 purge extension actually
      deletes old `agent_fetch_events` rows and keeps recent ones. Tier: Hybrid — same Docker/live-DB
      precondition as every other test in `test_retention_purge.py`; if Docker is unavailable in the
      execution environment, this is a Docker-gated known-gap (same class already accepted for the
      Alembic migration cycle below), NOT silently skipped — record it in the phase report's
      Docker-gap list alongside the migration cycle gap.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_tier_classification` (parametrized, all 10 documented tokens) | Fully-Automated | AC-H1-2 |
| `test_tier_map_covers_all_vendor_tokens` (completeness tripwire) | Fully-Automated | AC-H1-2 (regression-proof) |
| `test_row_created_per_hit` | Fully-Automated | AC-H1-1 |
| `test_write_failure_isolated` (mocked AsyncSession raising on insert) | Fully-Automated | AC-H1-3 |
| `test_retention_config_present` | Fully-Automated | Retention/PII guardrail (90-day cap) |
| Existing agent-visit/classifier regression suite re-run | Fully-Automated | Zero-regression program constraint |
| Ingest hot-path latency spot-check (manual timing comparison vs pre-phase baseline) | Agent-Probe | SPEC Constraint 4 (fail-open, no latency regression) |
| `test_purges_old_agent_fetch_events` (E7, mirrors `test_retention_purge.py`) | Hybrid (Docker-gated known-gap if infra unavailable) | D2 retention-purge extension (closes a PVL-found test-coverage gap — see Validate Contract) |
| Alembic migration cycle (upgrade/downgrade against live Postgres) | Hybrid (Docker-gated known-gap) | Migration correctness — deferred, see `program-docker-verification-gaps_NOTE_23-07-26.md` |

```bash
cd /Users/apple/getbeam && .venv/bin/python -m pytest tests/unit/test_agent_fetch_events.py -v
# Expected: all 6 test cases pass (tier classification, completeness, row-per-hit, fail-open, retention config)

cd /Users/apple/getbeam && .venv/bin/python -m pytest tests/unit/ -k "agent_visit or agent_classifier" -v
# Expected: existing EvalLayer agent-visit/classifier tests unaffected (zero regressions)

cd /Users/apple/getbeam && .venv/bin/python -m pytest tests/unit -q
# Expected: no regression vs pre-phase baseline count
```

---

## Test Infra Improvement Notes

(none identified yet)

---

## Exit Gate

```bash
cd /Users/apple/getbeam && .venv/bin/python -m pytest tests/unit/test_agent_fetch_events.py -v
cd /Users/apple/getbeam && .venv/bin/python -m pytest tests/unit/ -k "agent_visit or agent_classifier" -v
```

- All checklist items (A1-E6) checked
- `agent_fetch_events` table exists via migration; rollup `agent_visits` upsert path unchanged
- No new synchronous external call added to the ingest hot path (confirmed by code review during
  EXECUTE, not just by test pass)
- Phase report written to report destination above

---

## Blockers That Would Justify BLOCKED Status

- Alembic head conflicts with another in-flight migration — re-run `alembic heads` immediately
  before writing the migration; if `b3f9a1d2c7e5` is no longer a head, adjust `down_revision` to
  the correct current head instead of blocking
- Reading `retention.py`'s purge-job shape reveals a fundamentally different pattern than
  `purge_events_older_than` (e.g. requires new scheduler registration infra not covered by this
  checklist) — escalate rather than guess
- Ingest hot-path latency regression detected during EXECUTE testing — would require redesigning
  the write path (e.g. moving to a queue) before this phase can close; do not silently accept a
  latency regression

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop — already
locked at `handoff_SPEC_23-07-26.md`).

- [x] 1. RESEARCH — research-agent: prior phase reports read (none yet — this is the program's
      first phase); confirmed `_VENDOR_TOKENS` current tier membership incl. `claude-searchbot`
      (on-demand) vs `anthropic-ai` (index, distinct token); confirmed 7 pre-existing alembic
      heads incl. `b3f9a1d2c7e5`; test context loaded (`tests/unit/test_agent_classifier.py` style)
- [x] 2. INNOVATE — innovate-agent: approach decided (plain insert, not upsert, for the append-only
      table; separate `db.commit()` per write for full isolation); `claude-searchbot` tier bucket
      resolved (on-demand); fail-open write pattern confirmed to mirror `persist_agent_visit`;
      Decision Summary written (see LOCKED Decisions section above)
- [x] 3. PLAN-SUPPLEMENT — plan-agent: checklist rewritten to exact executable form encoding the
      locked tier map, model DDL, persistence function body, ingest wiring call site, and
      retention wiring; ambiguity from Step B2 closed
- [x] 4. PVL — vc-validate-agent: full V1-V7 complete 23-07-26; validate-contract written per
      `.claude/skills/vc-validate-findings/references/example-validate-output.md` (Status / Gate /
      Plan updates applied / Execute-agent instructions / Test gates / High-risk pack / Backlog
      artifacts / Known gaps / Accepted by); Gate: CONDITIONAL (see Validate Contract below)
- [x] 5. EXECUTE — all checklist items A1-E7 done 23-07-26; 6 fully-automated gates green (15 new
      unit + 24 classifier regression; full suite 839 passed, no regression vs 824 baseline; table
      registered on Base.metadata); 2 Hybrid gates (Alembic cycle + E7) Docker-gated known-gaps,
      written + collect clean. Report:
      phase-01-fetch-events-tiering_REPORT_23-07-26.md
- [x] 6. EVL — independent confirmation run (orchestrator, not execute-agent's internal loop):
      `test_agent_fetch_events.py` 15/15 PASS, `test_agent_classifier.py` 24/24 PASS (regression),
      full unit suite green (no product-affecting regressions vs baseline — the observed count
      delta is a parallel session's tests, not H1's). Model registration + both indexes confirmed
      on `Base.metadata`. Alembic chain confirmed linear single-head: `b3f9a1d2c7e5 →
      c4e8f1a9d2b7 (H1) → f8a2c1d9b3e7 (owned-data-layer, foreign) → a3e9f1c7d2b5 (owned-data-layer,
      foreign)` — the parallel visitors-identity "owned-data-layer" program chained its
      `company_graph`/`identity_signals` migrations directly onto H1's revision, i.e. that
      program's live-apply is now blocked on H1's migration being committed. 2 Hybrid gates
      (Alembic upgrade/downgrade cycle, E7 retention-purge live run) remain Docker-gated
      known-gaps — tracked in
      `backlog/handoff-program-docker-verification-gaps_NOTE_23-07-26.md`. No follow-up stubs
      beyond the existing backlog note.
- [x] 7. UPDATE PROCESS — phase report augmented with EVL results + foreign-migration
      observation; umbrella `## Current Execution State` + Program Status Table updated;
      blast-radius registry already `DONE`; commit intentionally deferred to vc-git-manager next.

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate
Contract` reads "(placeholder — vc-validate-agent writes this section before EXECUTE)",
orchestrator must spawn vc-validate-agent first. A partial contract missing Plan updates applied /
Execute-agent instructions / Test gates sections is treated as a placeholder.

---

## Touchpoints

- `apps/api/models/agent_fetch_event.py` (new)
- `apps/api/migrations/versions/` (new migration file)
- `apps/api/services/agent_classifier.py` (additive tier-lookup helper)
- `apps/api/services/agent_visit_persistence.py` (additive write function)
- `apps/api/routers/events.py` (one additive, fail-open call)
- `apps/api/config.py` (new retention setting)
- `apps/api/services/retention.py` (extended purge job)
- `apps/api/main.py` (model registration)
- `tests/unit/test_agent_fetch_events.py` (new)
- `tests/integration/test_retention_purge.py` (extended — VALIDATE-added E7)

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/handoff_23-07-26/phase-01-fetch-events-tiering_PLAN_23-07-26.md`
- Last completed step: Step 4 (PVL) — full V1-V7 complete 23-07-26; Gate: CONDITIONAL
- Validate-contract status: written (see below) — CONDITIONAL, 1 accepted concern (Docker-gated
  Hybrid test infra), autonomous /goal acceptance
- Supporting context files loaded: `handoff_SPEC_23-07-26.md` (AC-H1-1/2/3), umbrella plan hard
  safety constraints, `apps/api/services/agent_classifier.py`, `apps/api/services/agent_visit_persistence.py`,
  `apps/api/models/agent_visit.py`, `apps/api/routers/events.py`, `apps/api/services/retention.py`,
  `apps/api/config.py`, `apps/api/models/database.py`, `apps/api/main.py`,
  `tests/unit/test_agent_classifier.py`, `tests/unit/test_agent_visit_persistence.py`,
  `tests/unit/test_agent_verification.py`, `tests/integration/test_retention_purge.py`
- Next step: Spawn vc-execute-agent for Step 5 (EXECUTE), in the exact order: classifier tier fn
  (B) → model + registration (A) → migration (A3) → persist fn (C1) → events.py wiring (C2) →
  config + retention (D) → tests (E)

---

## Validate Contract

Status: CONDITIONAL
Date: 23-07-26
date: 2026-07-23
generated-by: inner-pvl: phase-h1

Parallel strategy: sequential
Rationale: single self-contained phase plan, one Layer-1+Layer-2 validate pass fit in one agent
context; no independent directions to fan out (score 1/7 — S7 only, 9 blast-radius files).

## Layer 1 dimensions

| Layer 1 dimensions | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | CONCERN (found + fixed in plan) |
| Breaking changes | PASS |
| Security surface | PASS |

## Layer 2 sections

| Layer 2 sections | Status |
|---|---|
| Implementation Checklist (Steps A-E) | CONCERN (found + fixed in plan) |

**Totals: 0 FAILs / 1 CONCERN (resolved via Plan Updates before this contract was written) / 3 PASSes**

**→ Net Gate: CONDITIONAL**

Rationale: 0 FAILs. The 1 CONCERN found (D2's retention-purge extension had zero test assigned)
was fixed in-plan (new E7 test item + Verification Evidence row added — see Plan Updates Applied
below), so it is not an open gap. Net Gate is CONDITIONAL rather than PASS solely because two
Hybrid-tier gates in this phase (the pre-existing Alembic migration cycle + the newly-added E7
retention-purge test) require a live Postgres/Docker precondition unavailable in this sandbox
(`docker ps` timed out during this VALIDATE pass) — both are named, justified residuals per the
vacuous-green ban (Hybrid tier assigned, not Known-Gap-only), consistent with the umbrella
charter's explicit "Docker known-gaps allowed" framing and the predecessor EvalLayer program's
identical accepted pattern.

## Plan Updates Applied

| # | What changed | Where | Why |
|---|---|---|---|
| P1 | Corrected `main.py` model-registration import-line reference to the real line (`from apps.api.models.agent_visit import AgentVisit  # noqa: F401 — register for create_all`, confirmed `main.py:32`) | Step A2 | Plan's original text (`from apps.api.models import agent_visit`) does not match the real line; execute-agent would search for a non-existent string |
| P2 | Changed Step C2 from a mid-function inline import to extending the file's existing top-level imports (`agent_classifier` line 15, `agent_visit_persistence` line 16); confirmed `ip_address` is in scope at the call site (defined `events.py:133`) | Step C2 | Inline imports mid-function deviate from the file's own top-level-import convention; a real defect an execute-agent could otherwise copy verbatim |
| P3 | Added a Hybrid test obligation note to Step D2 pointing at the new E7 test item | Step D2 | D2 modified `retention.py`'s purge job but the original checklist had zero test coverage assigned to that specific change (E5 only tests the config default, not the purge behavior) |
| P4 | Added E7 — `tests/integration/test_retention_purge.py::test_purges_old_agent_fetch_events`, mirroring the existing `test_purges_old_keeps_recent` pattern in that file (`patched_retention` + `test_db` fixtures) | Step E, Verification Evidence table | Closes the test-coverage gap named in P3; assigns a real Hybrid proving strategy instead of leaving the behavior vacuously covered by nothing |
| P5 | Corrected the LOCKED Decisions' Alembic-head claim: live-confirmed via `python -m alembic heads` (not just static scan) that exactly ONE head exists (`b3f9a1d2c7e5`), not "7 heads" | LOCKED Decisions | Original claim was stale/inaccurate (it did not block anything since `down_revision` was already correct, but would have sent execute-agent hunting for phantom heads) |
| P6 | Added `tests/integration/test_retention_purge.py` to Blast Radius and Touchpoints lists | Blast Radius, Touchpoints | Consistency — the file is now genuinely touched by this phase (E7) |

## Execute-Agent Instructions

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Re-run `cd apps/api && python -m alembic heads` immediately before writing the migration file (not the `alembic` console script — its shebang is broken in this sandbox venv; use `python -m alembic`). If a second head has appeared since 23-07-26, adjust `down_revision` to the new correct head and note it in the phase report — do not silently keep `b3f9a1d2c7e5` if it is no longer a head. | Step A3, before writing migration |
| E2 | Read `apps/api/services/retention.py::purge_events_older_than` in full (already confirmed to use: advisory lock via `pg_try_advisory_lock`, `_events_table_exists` check, `dry_run` counting path, `_PURGE_BATCH_SIZE`-batched delete loop) before writing the sibling function for Step D2 — do not guess the shape. | Step D2 |
| E3 | Write E7 by copying `tests/integration/test_retention_purge.py`'s existing `patched_retention` fixture pattern (confirmed real fixture: points `retention.async_session` at the `test_db` engine) — do not invent a new mocking approach for this one test. | Step E7 |
| E4 | Confirm the Step E ingest-hot-path test that exercises the fail-open isolation (E4 in Step E, `test_write_failure_isolated`) asserts the log line contains only `site_id`/`vendor`/`error` keys — no raw UA, IP, or PII — matching the exact pattern already used by `persist_agent_visit`'s existing warning log. | Step E4 |
| E5 | Confirm no second `db.commit()` failure mode: `persist_agent_fetch_event`'s own try/except must not let a failure in its insert roll back or affect the already-committed `persist_agent_visit` call above it in `events.py` (they are two separate transactions by design — C3 already documents this trade-off; do not "optimize" it into one transaction). | Step C2/C3 |

## Test gates (5-column table)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-H1-1 | Per-hit fetch event row created, rollup unaffected | Fully-Automated | `pytest tests/unit/test_agent_fetch_events.py::test_row_created_per_hit -v` | A |
| AC-H1-2 | Tier classification correct for all 10 documented tokens | Fully-Automated | `pytest tests/unit/test_agent_fetch_events.py::test_tier_classification -v` | A |
| AC-H1-2 (regression-proof) | Tier map covers every `_VENDOR_TOKENS` token (completeness tripwire) | Fully-Automated | `pytest tests/unit/test_agent_fetch_events.py::test_tier_map_covers_all_vendor_tokens -v` | A |
| AC-H1-3 | Ingest hot-path fail-open isolation (insert raises, no propagation, no PII in log) | Fully-Automated | `pytest tests/unit/test_agent_fetch_events.py::test_write_failure_isolated -v` | A |
| Retention/PII guardrail | 90-day retention config default present | Fully-Automated | `pytest tests/unit/test_agent_fetch_events.py::test_retention_config_present -v` | A |
| Zero-regression constraint | Existing agent-visit/classifier suites unaffected | Fully-Automated | `pytest tests/unit/ -k "agent_visit or agent_classifier" -v` | A |
| D2 retention-purge extension (PVL-added) | Purge job correctly deletes old `agent_fetch_events` rows, keeps recent | Hybrid | `pytest tests/integration/test_retention_purge.py -k agent_fetch_events -m integration -q` (precondition: live Postgres via `docker compose -f infra/docker-compose.yml up -d postgres`) | D |
| SPEC Constraint 4 | No ingest hot-path latency regression | Agent-Probe | Manual timing comparison of `/events` p50/p95 vs pre-phase baseline during EXECUTE | A |
| Migration correctness | Alembic upgrade/downgrade cycle against live Postgres | Hybrid | `cd apps/api && python -m alembic upgrade head && python -m alembic downgrade -1 && python -m alembic upgrade head` (precondition: live Postgres) | D |

gap-resolution legend: A — proven now (gate passes in this cycle) | D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: `strategy:` carries only Fully-Automated / Hybrid / Agent-Probe. The two `D`
rows above are Hybrid gates blocked on an unmet Docker precondition, not Known-Gap rows — the
behavior IS proven by a real test, that test simply cannot execute in this sandbox right now.

### Legacy line form (retained for existing consumers)

- Fetch-event capture + tiering + fail-open isolation: Fully-automated: `pytest tests/unit/test_agent_fetch_events.py -v` (expect 6 cases pass)
- Zero-regression: Fully-automated: `pytest tests/unit/ -k "agent_visit or agent_classifier" -v`
- Retention-purge extension: Hybrid: `pytest tests/integration/test_retention_purge.py -k agent_fetch_events -m integration -q` + precondition: live Postgres
- Ingest latency: Agent-probe: manual p50/p95 timing comparison during EXECUTE
- Alembic migration cycle: Hybrid: `alembic upgrade head && downgrade -1 && upgrade head` + precondition: live Postgres — known-gap: documented as backlog, see `handoff-program-docker-verification-gaps_NOTE_23-07-26.md`

### TDD stubs (Fully-Automated rows)

```
test("should create one agent_fetch_events row per hit without touching the rollup path", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_row_created_per_hit")
})
test("should classify all 5 on-demand tokens as on-demand and all 5 index tokens as index", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_tier_classification")
})
test("should classify every _VENDOR_TOKENS token without raising and match the locked tier map", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_tier_map_covers_all_vendor_tokens")
})
test("should isolate a fetch-event insert failure: return None, no exception, rollback, no PII in log", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_write_failure_isolated")
})
test("should default agent_fetch_event_retention_days to 90", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: test_retention_config_present")
})
```

(Note: stub syntax is JS-style per the harness template even though this codebase is Python —
execute-agent translates each stub 1:1 to a `pytest` `def test_...(): ...` skeleton with
`pytest.fail("NOT IMPLEMENTED — TDD stub: <name>")` before writing the real assertion body.)

## Structural Plan Validators (V1 Step 3b, mandatory)

- `node .claude/skills/vc-generate-phase-program/scripts/validate-phase-stub.mjs <this file>` —
  **0 failures, 0 warnings** (this is the correct validator for this file's actual shape — a
  phase-program per-phase stub, not a standalone SIMPLE/COMPLEX plan).
- `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs <this file>` — 4
  FAILs / 5 warnings reported (missing overview/context section, Complexity metadata, Phase
  Completion Rules, Acceptance Criteria). **These are expected shape mismatches, not real
  defects** — this validator checks the standalone SIMPLE/COMPLEX plan template
  (`Date:`/`Status:`/`Complexity:` frontmatter-style metadata + an `## Overview` section), which
  this phase-stub file deliberately does not use (it uses `## Purpose`, `## Entry Gate`,
  `## LOCKED Decisions`, `## Blockers That Would Justify BLOCKED Status`, and `## Phase Loop
  Progress` instead, per `phase-programs.md`'s phase-stub template — the same shape as every
  other phase plan in both the EvalLayer and Handoff Detection programs). Reported per protocol
  as mandatory, not treated as blocking.

## Dimension findings

- Infra fit: PASS — ingest hot-path change stays inside the existing `agent_detection_enabled` +
  `classification is not None` gate; DB-only writes; no new container/runtime surface. `Base`
  confirmed (read `apps/api/models/database.py`) to auto-provide `id`/`created_at`/`updated_at` to
  every model, so `AgentFetchEvent` needs no extra declaration for those three columns.
- Test coverage: CONCERN found, fixed in plan — D2's retention-purge extension originally had zero
  test assigned (only its config default was tested); added E7 mirroring the existing
  `test_retention_purge.py` pattern (see Plan Updates P3/P4).
- Breaking changes: PASS — no existing table/API/schema contract altered; `agent_visits` upsert,
  `classify_agent()` signature/return shape, and the `204` ingest response are all unchanged;
  `agent_fetch_events` and `classify_tier()` are net-new/additive.
- Security surface: PASS — no new auth/billing/secret surface; IP address storage is not a new PII
  class (already stored in `agent_visits`); 90-day retention now applies to the new table too;
  ORM-parameterized insert (no injection risk); fail-open write pattern isolates the new insert's
  failure from the existing rollup write in both directions (confirmed in `agent_visit_persistence.py`
  precedent and this phase's C1/C3 checklist).
- Implementation Checklist feasibility: PASS after fixes — all edit targets (models/database.py
  Base, agent_visit.py precedent, agent_classifier.py's 10-token `_VENDOR_TOKENS`, the exact
  fail-open pattern in `agent_visit_persistence.py`, the `events.py:142-145` call site and
  `ip_address` scope at `events.py:133`, `main.py:32` registration line, `config.py`'s retention
  section, `retention.py`'s purge-job shape) were read and confirmed live during this VALIDATE
  pass. Highest-risk edit: Step C2 (ingest hot-path wiring) — mitigated by keeping the new call
  strictly after the existing `persist_agent_visit` call and before the `204` return, relying on
  `persist_agent_fetch_event`'s own internal try/except (never letting the new insert affect the
  204 response), and running the Agent-Probe latency spot-check before declaring EXECUTE done.

## High-risk pack

Risk classes touched: schema/data migration (additive-only — new table, zero changes to any
existing table/column) and ingest hot-path (deploy/runtime-adjacent, not itself a container/proxy/
gateway change). Per the umbrella charter and this VALIDATE session's explicit framing, no hard
stop applies here — additive, fail-open, no live external calls, no auth/billing/destructive-write
surface. The full 5-artifact `vc-risk-evidence-pack` (risk-gate.json / context-snippets.json /
verification.json / review-decision.json / adversarial-validation.json) is manual-first/opt-in per
that skill's own contract, not required to reach this Gate; RECOMMENDED but not blocking, given the
schema-migration class, that execute-agent produce at minimum `context-snippets.json` +
`verification.json` in `{task_folder}/harness/` documenting the migration file content and the
`alembic heads` re-check (E1) before this phase is marked ✅ VERIFIED.

## Backlog artifacts

| Artifact | Location | What it tracks |
|---|---|---|
| `handoff-program-docker-verification-gaps_NOTE_23-07-26.md` (new) | `process/features/evallayer/backlog/` | Alembic migration cycle + E7 retention-purge test — both Hybrid, both Docker-gated, unrun in this sandbox |

## Known gaps

- Alembic migration cycle (upgrade/downgrade against live Postgres): Hybrid tier assigned;
  known-gap: documented as backlog — see `handoff-program-docker-verification-gaps_NOTE_23-07-26.md`.
  Structural correctness confirmed offline (`python -m alembic heads` shows a single, correct head).
- E7 retention-purge test (`test_purges_old_agent_fetch_events`): Hybrid tier assigned; known-gap:
  documented as backlog — same note as above. Not a design gap — the test is written into the
  plan (P4), it simply cannot execute without a live Postgres in this sandbox
  (`docker ps` timed out during this VALIDATE session).
- Ingest hot-path latency spot-check: Agent-Probe tier, to be recorded by execute-agent during
  EXECUTE (manual timing, not a Docker gap — just not yet run since code doesn't exist yet).

## What this coverage does NOT prove

- `test_agent_fetch_events.py`'s unit suite proves per-hit row creation, tier classification
  (including completeness), and fail-open isolation with a MOCKED `AsyncSession` — it does NOT
  prove the migration actually creates a working table against a real Postgres, nor that the ORM
  model's column types round-trip correctly at the DB level (that's the Alembic Hybrid gate,
  currently a known-gap).
- The retention-purge Fully-Automated check (E5) proves only that the config DEFAULT VALUE is 90
  — it does NOT prove the purge job actually deletes old rows or preserves recent ones (that's
  E7's Hybrid gate, currently a known-gap).
- The Agent-Probe latency spot-check is a manual, one-time comparison during EXECUTE — it does NOT
  constitute a regression-proof performance gate for future changes; no automated latency
  regression test exists in this blast radius.
- No test in this phase proves multi-event-batch behavior beyond "first event's page_path only" —
  that limitation is accepted/documented (C2), not tested for correctness beyond the single-event
  case.

Gate: CONDITIONAL (0 FAILs; 1 CONCERN found and resolved via Plan Updates before this contract was
written; 2 named Hybrid known-gaps remain, both Docker-precondition-blocked, both pre-authorized by
the umbrella charter's "Docker known-gaps allowed" framing)
Accepted by: session (autonomous, /goal execution) — accepted concerns: (1) Alembic migration
cycle unrun in this sandbox (Docker unavailable, `docker ps` timed out); (2) E7 retention-purge
test unrun in this sandbox (same Docker precondition). Both tracked in
`handoff-program-docker-verification-gaps_NOTE_23-07-26.md`; neither touches an SPEC hard-stop
class (H1 has none — additive, fail-open, no live-provider calls).
