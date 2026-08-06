---
name: plan:social-context-merge
description: "Fix store_social_context wholesale overwrite (merge instead) and stop it inflating the deep-research daily budget"
date: 07-08-26
feature: visitors-identity
---

# Social Context Merge + Budget De-conflation — PLAN (SIMPLE)

**TL;DR** — Two one-line-class bugs in `apps/api/services/social_intelligence.py::store_social_context`. Bug-1: it assigns `social_context` wholesale, destroying sibling keys written moments earlier by `enrich_tier1` in the same Celery loop iteration. Bug-2: it stamps `social_context_updated_at`, which `usage_limits.get_enrich_usage()` counts as a deep-research quota slot the user never used. Fix = read-modify-write merge (matching the 6 other writers) + delete the timestamp write. No migration, no schema change, no new dependency.

**Date**: 07-08-26
**Status**: ACTIVE — plan written, awaiting VALIDATE
**Complexity**: SIMPLE
**Feature**: visitors-identity

---

## Overview

`apps/api/services/social_intelligence.py::store_social_context` (lines 94-102) carries two related defects on the same 3-line body.

**BUG-1 — wholesale overwrite destroys sibling keys.** Line 100 does `enrichment_profile.social_context = context`. Its caller `apps/api/tasks/resolution_tasks.py:130-142` (the Celery-beat resolution sweep) runs, in ONE loop iteration for the same visitor: `enrich_tier1(...)` (which writes `social_context` keys) and then, when `visitor.intent_score >= 60`, `store_social_context(...)` — which destroys them. Net effect: for every visitor with `intent_score >= 60`, every other top-level key in `social_context` is silently destroyed. It is the only one of 7 writers that overwrites; the other 6 all merge.

**BUG-2 — `social_context_updated_at` inflates the deep-research daily budget.** Line 101 stamps `social_context_updated_at`. `apps/api/services/usage_limits.py:101-110` (`get_enrich_usage()`) counts `EnrichmentProfile` rows where `social_context_updated_at >= today` to enforce the deep-research 3/day budget. So a social-intelligence write consumes a deep-research quota slot the user never used. `apps/api/routers/visitors_helpers.py:339-340` already establishes the correct precedent, with an explicit comment saying an OSINT scan must not count against that meter.

Both fixes follow existing in-repo convention exactly. No new pattern, no new infrastructure.

## Complexity

**SIMPLE.** Single function, ~4 lines changed, one new unit test file. No phases.

## Phase Completion Rules

This is a SIMPLE single-session plan with no phases. The single implementation unit is complete only when ALL of the following hold:

- Every checklist item 1-11 is done.
- Every Fully-Automated gate in Verification Evidence exits 0 (AC-1 to AC-6, AC-8, AC-9).
- The Hybrid gate (AC-7) has been run with Postgres+Redis up, or is explicitly recorded as a deferred known-gap with its reason in the phase report.
- All three Backlog Follow-Up notes exist on disk.
- Status may be promoted to `CODE DONE` when the code compiles and unit gates are green; promotion to `VERIFIED` additionally requires the AC-7 Hybrid gate to have actually run and passed. Code-only completion is never `VERIFIED`.

## INNOVATE Skip Record

INNOVATE was deliberately skipped. Rationale: the approach is settled by existing convention — 6 of the 7 writers to `EnrichmentProfile.social_context` already do a Python-level read-modify-write merge, and grep confirms **zero** `jsonb ||` / `jsonb_concat` precedent anywhere in the codebase. Introducing a Postgres-side merge would be new infrastructure with no precedent; there is no design decision left to make.

---

## Goals

1. `store_social_context` must preserve sibling top-level keys in `social_context` instead of destroying them.
2. `store_social_context` must stop consuming a deep-research quota slot.

## Non-Goals (explicit)

- Fixing the equivalent `social_context_updated_at` write at `apps/api/services/enricher.py:821` (content-reader path). Backlog only — see Backlog Follow-Ups.
- Any concurrency / lost-update / row-lock safety. Pre-existing, affects all 6 existing merge writers equally.
- Any purge/erasure path for `social_context`.
- Any migration or schema change.

---

## Touchpoints

| File | Change |
|---|---|
| `apps/api/services/social_intelligence.py` (lines 94–102, `store_social_context`) | **MODIFY** — merge instead of overwrite; remove `social_context_updated_at` write; add explanatory comment mirroring `visitors_helpers.py:336-341` style |
| `tests/unit/test_social_intelligence.py` | **CREATE** — new unit test file (does not currently exist) |
| `apps/api/services/usage_limits.py` | **READ ONLY** — verify `get_enrich_usage()` semantics; no edit |
| `apps/api/tasks/resolution_tasks.py` (lines 130–142) | **READ ONLY** — the calling site that manifests BUG-1; no edit |
| `apps/api/routers/visitors_helpers.py` (lines 336–341, 381–386) | **READ ONLY** — the precedent comment + merge pattern to mirror; no edit |

## Public Contracts

- `store_social_context(enrichment_profile: EnrichmentProfile, context: dict) -> None` — **signature unchanged**. Callers need no update.
- `EnrichmentProfile.social_context` (nullable JSONB) — column unchanged; write semantics change from replace to merge.
- `EnrichmentProfile.social_context_updated_at` — column unchanged; this function stops writing it. Other writers (`enricher.py:821`, `enricher.py:1010`) unchanged.
- `get_enrich_usage(db, site_id) -> int` — code unchanged; the *observed count* will drop for sites where social-intelligence previously stamped the column. This is the intended correction (in the user's favour: they regain slots they were wrongly charged).

## Blast Radius

- **Files changed:** 2 (1 modify, 1 create).
- **Packages:** `apps/api` only. No web, no pixel, no migrations.
- **Risk class:** quota/credit accounting (touches a column read by the budget meter). Per repo policy this is a high-risk class → requires at minimum automated tier coverage of the accounting behaviour; hybrid tier assigned for the DB-level count.
- **Reader safety:** all `social_context` readers verified defensive (`.get()`, `isinstance` guards, falsy checks) — a merge that *adds* keys cannot break any of them: `enricher.py:154-166`, `enricher.py:838-896`, `content_reader.py:446-471`, `content_reader.py:529-588`, `agents/segmenter.py:128`, `agents/workspace_tools.py:406`, `services/auto_drafter.py:56-70`, `routers/visitors.py:705`/`:1334`/`:1420`, `schemas/visitors.py:85`.
- **No consumer depends on the overwrite clearing data** — verified: `retention.py` purges only `events`/`agent_fetch_events`/`request_logs`; `do_not_resolve` gates whether enrichment *runs*, not what happens to already-written `social_context`; no GDPR/erasure path touches this column.
- **Existing test impact:** zero. No existing test exercises `store_social_context` or `fetch_social_context`. `tests/unit/test_content_enrich.py:151` asserts `social_context_updated_at is not None` on the **enricher** path (`enricher.py:821`), which this plan does not touch — that assertion continues to pass.

---

## Guardrails (must hold)

| ID | Guardrail |
|---|---|
| G1 | Merge at the Python level (`{**(existing or {}), **context}`), matching the 6 existing writers. Do **NOT** introduce a Postgres `jsonb \|\|` pattern — zero precedent; that would be new infra. |
| G2 | `social_context` is a nullable column. Merging when it is `None` must not raise. |
| G3 | Do **NOT** fix `enricher.py:821`'s equivalent `social_context_updated_at` write. Backlog note only. |
| G4 | Do **NOT** attempt concurrency / lost-update safety. Known-gap, pre-existing, shared with 6 other writers. |
| G5 | No migration. No schema change. Column exists and is nullable JSONB. |
| G6 | Before finalizing, confirm no code reads `social_context_updated_at` expecting social-intelligence to have set it. **Already verified during PLAN:** the only reader is `usage_limits.py:110`; the only other writers are `enricher.py:821` and `enricher.py:1010`, both untouched. |
| G7 | The last-write-wins-per-key semantic must be preserved: keys present in the incoming `context` overwrite same-named existing keys. Only *absent* keys are preserved. |
| G8 | The SQLAlchemy JSONB attribute must be **reassigned** (not mutated in place) so the ORM marks the field dirty. Build a new dict and assign it. |

---

## Acceptance Criteria

| AC | Criterion | proven by | strategy |
|---|---|---|---|
| AC-1 | `store_social_context` preserves pre-existing sibling top-level keys not present in the incoming `context` | `test_store_merges_preserving_sibling_keys` | Fully-Automated |
| AC-2 | New keys present in the incoming `context` are written | `test_store_writes_new_keys` | Fully-Automated |
| AC-3 | A key present in BOTH existing and incoming resolves to the incoming value (last write wins per key) | `test_store_incoming_key_wins` | Fully-Automated |
| AC-4 | `social_context is None` start state merges without raising and yields exactly `context` | `test_store_handles_none_start_state` | Fully-Automated |
| AC-5 | Regression for the reported bug: an `enrich_tier1`-shaped write followed by `store_social_context` in the same `resolution_tasks.py` loop iteration retains the `enrich_tier1` keys | `test_resolution_sweep_same_iteration_preserves_enrich_keys` | Fully-Automated |
| AC-6 | `store_social_context` does NOT modify `social_context_updated_at` (a pre-set value is unchanged; a `None` value stays `None`) | `test_store_does_not_touch_updated_at` | Fully-Automated |
| AC-7 | `get_enrich_usage()` does not count a profile whose only write today was social-intelligence | `test_enrich_usage_ignores_social_intelligence_only_write` (integration, real DB count) | Hybrid |
| AC-8 | No migration is required — `alembic heads` is unchanged by this plan and no new revision file is added | `git status` shows no file under `apps/api/migrations/versions/`; `alembic -c apps/api/alembic.ini heads` output identical pre/post | Fully-Automated |
| AC-9 | No existing test regresses — in particular `tests/unit/test_content_enrich.py` (which asserts the enricher path still stamps `social_context_updated_at`) stays green | full unit lane | Fully-Automated |

---

## Implementation Checklist

1. Read `apps/api/services/social_intelligence.py` lines 90–105 and `apps/api/routers/visitors_helpers.py` lines 330–345 + 381–386 to confirm the current code and the comment style to mirror.
2. In `apps/api/services/social_intelligence.py::store_social_context`, replace the body's assignment with a read-modify-write merge:
   - read `enrichment_profile.social_context`, coalescing `None` to `{}` (G2);
   - build a NEW dict merging existing then incoming so incoming wins per key (G7, G8);
   - assign the new dict back to `enrichment_profile.social_context`.
3. In the same function, DELETE the `enrichment_profile.social_context_updated_at = datetime.now(timezone.utc)` line (BUG-2).
4. Add a docstring/comment on `store_social_context` in the style of `visitors_helpers.py:336-341`, stating: (a) it read-modify-writes, preserving sibling keys written by `enrich_tier1` and the other 6 writers; (b) it deliberately does NOT touch `social_context_updated_at` because that column drives the deep-research daily meter in `usage_limits.get_enrich_usage()` and a social-intelligence write must not count against it.
5. Check whether `datetime`/`timezone` imports in `social_intelligence.py` become unused after step 3; remove only if genuinely unused (grep the file first) — do not remove imports still referenced elsewhere in the module.
6. Create `tests/unit/test_social_intelligence.py` covering AC-1 through AC-6. Follow the fixture/style patterns in `tests/unit/test_content_enrich.py:100,145-151` and `tests/unit/test_social_resolver.py:174`. Construct a real `EnrichmentProfile`; stub `self.db.commit()` (an `AsyncMock`) since the unit lane has no DB. Remember the ORM-mapper gotcha: `import apps.api.main` before constructing ORM objects, or SQLAlchemy raises `InvalidRequestError`.
7. Add the AC-7 integration test — a `test_social_context_budget` case asserting `get_enrich_usage()` returns 0 after a social-intelligence-only write. Place it alongside existing integration tests; pattern reference `tests/integration/test_osint_scan_endpoint.py:87`.
8. Run the unit gate; fix to green.
9. Run the touched-file integration gate, then the full unit lane as regression (AC-9).
10. Confirm AC-8: `git status --short apps/api/migrations/` is empty.
11. Write the three backlog follow-up notes listed below.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py -q` exits 0 | Fully-Automated | AC-1, AC-2, AC-3, AC-4, AC-5, AC-6 |
| `.venv/bin/python3.11 -m pytest tests/integration/test_usage_limits.py -q` (or the file the AC-7 test lands in) exits 0 — **precondition:** `docker compose -f infra/docker-compose.yml up -d postgres redis` | Hybrid | AC-7 |
| `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` exits 0 (full unit lane, includes `test_content_enrich.py`) | Fully-Automated | AC-9 |
| `git status --short apps/api/migrations/versions/` produces no output | Fully-Automated | AC-8 |
| `alembic -c apps/api/alembic.ini heads` output identical before and after | Fully-Automated | AC-8 |

**Runner note:** use `.venv/bin/python3.11 -m pytest`. The `.venv/bin/pytest` console-script shebang in this repo points at a stale pre-move path and fails. `process/context/tests/all-tests.md` lists `.venv/bin/python -m pytest`; `python3.11` is the confirmed-working interpreter name.

**Docker note:** confirmed against `process/context/tests/all-tests.md` — the **unit lane needs no Docker** (pure logic, mocks/monkeypatch only, ~1.5s). Only the AC-7 integration gate requires local PostgreSQL + Redis, which is why AC-7 is tiered Hybrid rather than Fully-Automated.

### TDD stubs (Fully-Automated rows only)

```
Failing stub:
test("store_social_context preserves pre-existing sibling keys", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-1 merge preserves siblings")
})
test("store_social_context writes new keys", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-2 new keys written")
})
test("store_social_context incoming key wins on collision", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-3 last write wins per key")
})
test("store_social_context handles social_context is None", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-4 None start state")
})
test("resolution sweep same-iteration enrich keys survive store_social_context", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-5 reported-bug regression")
})
test("store_social_context does not modify social_context_updated_at", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-6 no timestamp write")
})
```

---

## Test Infra Gaps

| Gap | Why | Resolution chosen |
|---|---|---|
| No test file existed for `social_intelligence.py` at all before this plan | Module was never unit-tested | A) Write new — `tests/unit/test_social_intelligence.py` created by this plan (~30 min) |
| Concurrent-writer lost-update behaviour is untestable in the unit lane and unreliable in the integration lane (no locking exists to assert on) | No row-level locking or OCC anywhere in this call graph | C) Accept as known-gap — pre-existing, affects the 6 other merge writers identically; backlog note written |
| `get_enrich_usage()` count assertion requires a real Postgres | `func.count()` over a real table | B) Set up infra — `docker compose -f infra/docker-compose.yml up -d postgres redis`; tiered Hybrid (AC-7) |

## Test Infra Improvement Notes

(none identified yet)

---

## Backlog Follow-Ups

1. **`enricher.py:821` `social_context_updated_at` conflation.** The content-reader path (`_fetch_and_store_content`) also stamps `social_context_updated_at`, inflating the same deep-research daily meter for a non-deep-research write. Arguably the same bug as BUG-2. Explicitly OUT OF SCOPE here (G3). Note: `tests/unit/test_content_enrich.py:151` currently *asserts* that stamp, so fixing it requires updating that test — a separate, deliberate change. Write `enricher-updated-at-conflation_NOTE_07-08-26.md` in `process/features/visitors-identity/backlog/`.
2. **Concurrency lost-update known-gap.** No row-level locking or OCC exists anywhere in the `social_context` call graph. The Celery-beat resolution sweep and API-triggered background tasks open independent sessions and can race; a read-modify-write merge can lose the loser's keys. This exposure is **pre-existing and shared by all 6 existing merge writers** — this plan neither introduces nor worsens it (it moves writer #7 from "always destroys" to "usually preserves"). Write `social-context-lost-update_NOTE_07-08-26.md`.
3. **`social_context` has NO purge path at all today.** `retention.py` purges only `events`, `agent_fetch_events`, `request_logs`. Nothing — including any GDPR/erasure route — deletes or redacts `EnrichmentProfile.social_context`, which holds scraped post content and derived topics. **Flag to the owner of `process/features/visitors-identity/active/graph-erasure-compliance_07-08-26/`**: that SPEC and PLAN contain zero references to `social_context` or `EnrichmentProfile`, so this surface appears unaccounted for in the erasure program. Write `social-context-no-purge-path_NOTE_07-08-26.md` and cross-reference it from the erasure plan's follow-ups.

---

## Risks

| Risk | Mitigation |
|---|---|
| Merge silently retains stale keys that a caller intended to clear | Verified no consumer depends on the clear (`retention.py` read in full; `do_not_resolve` gates whether enrichment runs, not stored data; no erasure path touches the column). All readers are defensive. |
| Quota accounting shifts | Shifts strictly in the user's favour (they regain wrongly-charged slots). Only reader is `usage_limits.py:110`; verified at PLAN time (G6). |
| In-place dict mutation not persisted by SQLAlchemy | G8 requires reassigning a NEW dict, not mutating the JSONB attribute in place. |
| Unused-import lint failure after removing the timestamp write | Checklist step 5 explicitly grep-checks before removing imports. |

## Rollback

Single-file revert of `apps/api/services/social_intelligence.py`. No migration, no data change, no schema change — nothing to undo in the database. Written `social_context` blobs are strictly supersets of what the old code would have written, so reverting the code leaves no incompatible data behind.

---

## Resume and Execution Handoff

1. **Selected plan file path:** `process/features/visitors-identity/active/social-context-merge_07-08-26/social-context-merge_PLAN_07-08-26.md`
2. **Last completed phase or step:** PLAN written. No implementation started. INNOVATE deliberately skipped (rationale recorded above).
3. **Validate-contract status:** pending — vc-validate-agent has not run.
4. **Supporting context files loaded:** `process/context/all-context.md`, `process/context/tests/all-tests.md`, `process/features/visitors-identity/_GUIDE.md`, plus source reads of `social_intelligence.py`, `resolution_tasks.py`, `usage_limits.py`, `visitors_helpers.py`, `enricher.py` (grep).
5. **Next step for a fresh agent:** run VALIDATE on this plan. After a PASS/accepted-CONDITIONAL contract, EXECUTE starts at Implementation Checklist step 1. Do not widen scope to `enricher.py:821` (G3) or to concurrency safety (G4).

## Validate Contract

Status: CONDITIONAL
Date: 07-08-26
date: 2026-08-07
generated-by: outer-pvl

Parallel strategy: parallel-subagents
Rationale: 2/7 signals (S2 quota/credit-accounting surface touched; S6 high-risk class in Blast Radius). MEDIUM band — Layer 1 four dimension agents plus 5 Layer 2 section agents, no cross-agent communication needed.

### Test gates

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | Merge preserves pre-existing sibling top-level keys | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py::test_store_merges_preserving_sibling_keys -q` | B |
| AC-2 | New incoming keys are written | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py::test_store_writes_new_keys -q` | B |
| AC-3 | Key present in both resolves to incoming (last-write-wins per key, G7) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py::test_store_incoming_key_wins -q` | B |
| AC-4 | `social_context is None` start state merges without raising (G2) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py::test_store_handles_none_start_state -q` | B |
| AC-5 | Reported regression: enrich_tier1-shaped keys survive a following `store_social_context` | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py::test_resolution_sweep_same_iteration_preserves_enrich_keys -q` | B |
| AC-6 | `store_social_context` never modifies `social_context_updated_at` (BUG-2) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py::test_store_does_not_touch_updated_at -q` | B |
| AC-10 (NEW — required) | G8 dirty-tracking: the JSONB attribute is REASSIGNED, not mutated in place | Fully-Automated | `assert profile.social_context is not original_dict` inside the AC-1 test | B |
| AC-7 | `get_enrich_usage()` returns 0 after a social-intelligence-only write | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_usage_limits.py -q` — precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis` | D |
| AC-8 | No migration is added by this plan | Fully-Automated | `git status --short apps/api/migrations/versions/` produces no output | A |
| AC-9 | No existing test regresses (esp. `tests/unit/test_content_enrich.py`) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` exits 0 | B |

gap-resolution legend: A — proven now; B — gate added by this plan's checklist; C — deferred to a named later phase; D — backlog test-building stub (named residual; keep-active).

C-4 reconciliation: the `strategy:` column carries ONLY Fully-Automated / Hybrid / Agent-Probe. Known-Gap is never a strategy value; AC-7's residual is carried via gap-resolution D.

Legacy line form (for existing validate-contract consumers):

- merge semantics (AC-1..AC-5, AC-10): `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py -q`
- quota de-conflation, unit tier (AC-6): `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py -q`
- quota de-conflation, DB tier (AC-7): `hybrid: .venv/bin/python3.11 -m pytest tests/integration/test_usage_limits.py -q + precondition docker compose up -d postgres redis` — DEFERRED, Docker confirmed down, user-accepted known-gap
- regression lane (AC-9): `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit -m unit -q`
- no-migration (AC-8): `Fully-automated: git status --short apps/api/migrations/versions/` empty
- concurrency / lost-update: `known-gap: documented` — pre-existing, shared with all 7 other writers, backlog note required

Dimension findings:

- Infra fit: CONCERN — Docker confirmed DOWN (`docker info` fails), so the AC-7 Hybrid gate cannot run this session (user-accepted). Separately, every Fully-Automated gate command literally contains `.venv`, which this repo's own `.claude/hooks/scout-block.cjs` PreToolUse hook DENIES for Bash calls; the execute-agent will be blocked from running its own gates until the documented remedy is applied (see E1).
- Test coverage: CONCERN — G8 (the plan's own top Risk, "in-place dict mutation not persisted by SQLAlchemy") has ZERO proving gate as written; AC-1..AC-6 pass identically whether the code reassigns or mutates in place. AC-10 added above closes it. AC-5 is a hand-seeded simulation rather than a caller-sequence run. AC-7's landing file does not exist and no test anywhere references `get_enrich_usage`.
- Breaking changes: PASS — `store_social_context` signature unchanged. Repo-wide grep across `.py`/`.ts`/`.tsx` confirms `social_context_updated_at` has exactly ONE reader (`apps/api/services/usage_limits.py:110`); no Pydantic schema, no API response field, no dashboard surface, no staleness/re-fetch gate reads it. Remaining writers after this change: `enricher.py:821`, `enricher.py:1010` (both untouched). `tests/unit/test_content_enrich.py:151` verified to exercise `Enricher._fetch_and_store_content` via a `SimpleNamespace` profile — the enricher path, untouched — so it stays green exactly as the plan claims.
- Security surface: CONCERN — risk class is quota/credit accounting; the change strictly REDUCES over-counting, in the user's favour, so no adversarial exposure. But the merge makes `social_context` blobs strict supersets of what the old code wrote, and Backlog Follow-Up #3 establishes there is NO purge/erasure path for that column at all. The plan frames this only as a rollback-safety point; it is also a small, real increase in retained scraped-PII residency. No auth, no secrets, no new external call, no trust boundary touched.
- Section A (store_social_context modification, checklist 1-5): PASS — mechanical feasibility confirmed, edit targets at `social_intelligence.py:100-101` unique and matchable. G8 independently verified NECESSARY: `apps/api/models/enrichment.py:59` declares `social_context` as plain `mapped_column(JSONB, nullable=True)` with NO `MutableDict.as_mutable()` (zero `MutableDict` matches repo-wide), so an in-place `.update()` would be silently unflushed. All existing merge writers verified to use the reassign-new-dict pattern — no latent in-place-mutation bug exists anywhere. Merge direction `{**existing, **incoming}` confirmed to match every existing writer. Checklist step 5 verified precisely correct: `datetime`/`timezone` are imported at line 11 and used ONLY at line 101, so they do become fully unused.
- Section B (test creation, checklist 6-7): CONCERN — see Test coverage above; GAP-2, GAP-3, GAP-4, GAP-5 below.
- Section C (AC-7 budget accounting): CONCERN (accepted) — see the AC-6-sufficiency assessment in Open gaps.
- Section D (backlog notes, checklist 11): PASS — all three notes correctly scoped; note #3's cross-flag to `graph-erasure-compliance_07-08-26/` is a genuine unaccounted-for surface and is the right handling.
- Section E (AC-8 no-migration): PASS — no schema change is implied; only assignment statements change and column definitions are untouched. `git status --short apps/api/migrations/versions/` is a real load-bearing gate. The `alembic heads` half of AC-8 is logically redundant (heads cannot move without a new revision file) and is blocked by the same `.venv` hook — demoted to optional.
- Blast Radius accuracy: CONCERN — the plan says "6 of 7 writers merge". Actual count is 7 merge writers plus `store_social_context` = 8. `apps/api/routers/visitors.py:1443-1447` (the `social_resolution` "scanning" seed) is a correct merge writer that the plan does not enumerate. It uses the right pattern, so no conclusion changes; the count and the Blast Radius list are simply off by one.

Open gaps:

- GAP-1 (accuracy): Blast Radius omits merge writer `apps/api/routers/visitors.py:1443-1447`; the "6 of 7" count should be "7 of 8". No behavioural consequence.
- GAP-2 (highest value): G8 has no proving gate. Add AC-10 — assert the JSONB attribute is a different object after the call (`assert profile.social_context is not original`). One line inside the AC-1 test; fully-automated; works with either a `SimpleNamespace` or a real ORM profile.
- GAP-3: AC-5 should name the real key sets so it represents the reported bug rather than placeholders. Verified shapes — `enrich_tier1` → `_fetch_and_store_content` writes `youtube` / `reddit` / `company_content`; `store_social_context`'s incoming `context` carries `recent_posts` / `topics` / `sentiment`. The two sets are DISJOINT, which means the real-world bug is pure destruction with no key collision, and AC-3's collision case is synthetic (still correct to pin per G7).
- GAP-4: checklist step 6 mandates a real `EnrichmentProfile` plus the `import apps.api.main` ORM-mapper guard. Zero unit tests in `tests/unit/` construct a real `EnrichmentProfile`; the nearest precedent (`test_content_enrich.py`) uses `SimpleNamespace` and needs no guard. Either is acceptable — the choice does not affect AC-10's provability — but the plan should permit the lighter precedent.
- GAP-5: AC-7's landing file is unresolved. `tests/integration/test_usage_limits.py` does not exist and no test anywhere references `get_enrich_usage`. Name it concretely as a new file so the deferred gate is real and runnable later.
- AC-7 deferral: known-gap: documented as accepted this session. Docker daemon confirmed down. Backlog note required.
  - Sufficiency assessment (explicit, as requested): AC-6 plus the unchanged counting logic DOES genuinely cover the mechanism this plan changes. `get_enrich_usage()` counts exactly and only `EnrichmentProfile.social_context_updated_at >= today` (verified verbatim at `usage_limits.py:106-111`, no other predicate). If AC-6 proves the column is never written by `store_social_context`, and the counting predicate is read-only and unchanged, a social-intelligence-only write cannot increment the count. There is no third variable; the inference is airtight at the logic level.
  - What AC-7 would still add, and therefore what remains genuinely unproven: (a) that a row whose `social_context_updated_at` is `NULL` is EXCLUDED by the `>= today` predicate under SQL three-valued logic (correct in principle — `NULL >= today` is NULL, not TRUE — but never executed against real Postgres here); and (b) that `_today_start()`'s timezone handling puts the boundary where intended. Both are pre-existing SQL semantics that this plan relies on but does not modify. The backlog note must record these two specific residuals, not a vague "run AC-7".
- Concurrency / lost-update: known-gap: documented. Pre-existing, shared identically by all 7 existing merge writers; this plan neither introduces nor worsens it. Backlog note required (Follow-Up #2).
- `social_context` has no purge/erasure path: known-gap: documented as NEW PLAN REQUIRED — cross-flagged to `process/features/visitors-identity/active/graph-erasure-compliance_07-08-26/` via Backlog Follow-Up #3.
- `enricher.py:821` equivalent `social_context_updated_at` conflation: known-gap: documented as out of scope by G3. Backlog Follow-Up #1.

What this coverage does NOT prove:

- `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py -q` (AC-1..AC-6, AC-10) does NOT prove: that the merged dict is actually FLUSHED to Postgres (no session, no DB in the unit lane — AC-10 proves reassignment, which is the necessary precondition for the flush, but not the flush itself); that `resolution_tasks.py:130-142` wires the two calls in the asserted order (the test hand-seeds the prior state instead of running the sweep); that concurrent writers do not lose each other's keys; that the real `fetch_social_context` output shape matches the shape the test feeds in.
- `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` (AC-9) does NOT prove: any integration-lane or e2e behaviour; that the enricher path's own `social_context_updated_at` stamp is correct (only that it is unchanged); that no integration test regresses.
- `git status --short apps/api/migrations/versions/` (AC-8) does NOT prove: that the live database schema matches the model; that the current alembic head is applied anywhere; only that THIS plan added no revision file.
- AC-7 (deferred) leaves unproven: real-Postgres exclusion of `NULL` `social_context_updated_at` rows from the `>= today` count, and `_today_start()` timezone-boundary correctness.
- No gate at any tier proves: that removing the timestamp write does not change any operator-facing budget display (verified by grep to have no reader, but never exercised end-to-end).

Plan updates applied by VALIDATE: NONE. The validate-agent made zero edits to the plan body — only this `## Validate Contract` section and the `## Autonomous Goal Block` below were appended. All five gaps are routed through the SUPPLEMENT REQUEST to vc-plan-agent so the fix cycle is recorded rather than silently absorbed.

Execute-agent instructions:

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | BEFORE running any test gate: the repo's `.claude/hooks/scout-block.cjs` PreToolUse hook denies any Bash command containing `.venv`, which is every Fully-Automated gate in this contract. Apply the hook's own documented remedy — add `!.venv` to `/Users/apple/getbeam/.claude/.vcignore` (the file exists and is empty; the hook supports `!` negation, see its header comment line 18). Do NOT work around the hook by other means, and do NOT silently skip a gate you could not run — report it. | Session start, before checklist step 8 |
| E2 | Use `.venv/bin/python3.11 -m pytest`, never `.venv/bin/pytest` — the console-script shebang points at a stale pre-move path and fails. | Every pytest invocation |
| E3 | AC-10 is mandatory, not optional. The merge must be proven to REASSIGN: capture the original dict object, call `store_social_context`, then assert `profile.social_context is not original`. `enrichment.py:59` has no `MutableDict`, so an in-place `.update()` would be silently unflushed and every other AC would still pass. | Checklist step 6 |
| E4 | Seed AC-5 with the REAL key names: prior state `{"company_content": {...}}` (or `youtube` / `reddit`), incoming `{"recent_posts": [...], "topics": [...], "sentiment": None}`. Assert the prior key survives. | Checklist step 6 |
| E5 | Creating the AC-7 test file is still required even though the gate is deferred — create `tests/integration/test_usage_limits.py` so the gate exists and is runnable once Docker is up. Mark it so it is skipped/failing-loud rather than silently absent. | Checklist step 7 |
| E6 | Do NOT widen scope: `enricher.py:821` stays untouched (G3), concurrency safety stays untouched (G4), and `apps/api/routers/visitors.py:1443-1447` (the 8th writer found during VALIDATE) is correct as-is — do not edit it. | Throughout |
| E7 | Record the AC-7 deferral in the phase report with its two SPECIFIC residuals: NULL-exclusion under `>= today`, and `_today_start()` timezone boundary. A vague "AC-7 not run" is insufficient. | Checklist step 11 |

Backlog artifacts required:

| Artifact | Location | What it tracks |
|---|---|---|
| `enricher-updated-at-conflation_NOTE_07-08-26.md` | `process/features/visitors-identity/backlog/` | `enricher.py:821` stamps the same meter column for a non-deep-research write; fixing it also requires updating `test_content_enrich.py:151` |
| `social-context-lost-update_NOTE_07-08-26.md` | `process/features/visitors-identity/backlog/` | Concurrency lost-update, pre-existing across all 7 merge writers |
| `social-context-no-purge-path_NOTE_07-08-26.md` | `process/features/visitors-identity/backlog/` | No purge/erasure path for `social_context`; NEW PLAN REQUIRED; cross-flag to `graph-erasure-compliance_07-08-26/` |
| `social-context-ac7-deferred_NOTE_07-08-26.md` | `process/features/visitors-identity/backlog/` | AC-7 deferred (Docker down). Residuals: NULL-exclusion under `>= today`; `_today_start()` tz boundary |

Gate: CONDITIONAL (0 FAILs, 5 CONCERNs — GAP-2 requires a plan supplement before EXECUTE; AC-7 deferral and the three pre-existing known-gaps accepted by user this session)

Accepted by: user (this session) — accepted concerns, by name: (1) AC-7 Hybrid gate deferred, Docker daemon confirmed down; (2) `enricher.py:821` conflation out of scope; (3) concurrency / lost-update out of scope; (4) `social_context` purge-path absence deferred to the erasure program. NOT accepted / requires supplement: GAP-2 (G8 unproven), GAP-3, GAP-4, GAP-5, GAP-1.

---

## Autonomous Goal Block

```
SESSION GOAL: Fix store_social_context wholesale overwrite (merge instead) and stop it inflating the deep-research daily budget.
Charter + umbrella plan: N/A — single plan (standalone RIPER-5)
Autonomy: Proceed without approval pauses on reversible work. Write the test file, apply the two-part code fix, run gates, write backlog notes. Blocked items go to backlog — always find a path to proceed.
Hard stop conditions / safety constraints:
- Do not touch apps/api/services/enricher.py:821 (G3 — separate deliberate change, would break test_content_enrich.py:151).
- Do not attempt concurrency / row-lock / lost-update safety (G4 — pre-existing, shared with 7 other writers).
- Do not introduce a Postgres jsonb || merge (G1 — zero precedent in this repo; would be new infrastructure).
- Do not add any migration or schema change (G5).
- Do not edit apps/api/routers/visitors.py:1443-1447 (correct merge writer found during VALIDATE).
- Do not mark the plan VERIFIED while AC-7 is deferred — CODE DONE is the ceiling until Docker is up.
- Any irreversible or outward-facing action not named in this contract: stop and ask.
Next phase: EXECUTE — but only AFTER the PVL supplement cycle closes GAP-2/3/4/5.
Validate contract: inline in plan (## Validate Contract)
Execute start: fully-auto — `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py -q`, then `.venv/bin/python3.11 -m pytest tests/unit -m unit -q`, then `git status --short apps/api/migrations/versions/` (must be empty) | hybrid (deferred): `.venv/bin/python3.11 -m pytest tests/integration/test_usage_limits.py -q` needs `docker compose -f infra/docker-compose.yml up -d postgres redis` | probe scenario: none | high-risk pack: no (quota accounting, but change is strictly in the user's favour and reduces over-counting)
PREREQUISITE: add `!.venv` to /Users/apple/getbeam/.claude/.vcignore or every gate command above is denied by the scout-block hook.
```
