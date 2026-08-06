---
name: plan:social-context-merge
description: "Fix store_social_context wholesale overwrite (merge instead) and stop it inflating the deep-research daily budget"
date: 07-08-26
feature: visitors-identity
---

# Social Context Merge + Budget De-conflation — PLAN (SIMPLE)

**TL;DR** — Two one-line-class bugs in `apps/api/services/social_intelligence.py::store_social_context`. Bug-1: it assigns `social_context` wholesale, destroying sibling keys written moments earlier by `enrich_tier1` in the same Celery loop iteration. Bug-2: it stamps `social_context_updated_at`, which `usage_limits.get_enrich_usage()` counts as a deep-research quota slot the user never used. Fix = read-modify-write merge (matching the 8 other merge writers) + delete the timestamp write. No migration, no schema change, no new dependency.

**Date**: 07-08-26
**Status**: ACTIVE — plan written, awaiting VALIDATE
**Complexity**: SIMPLE
**Feature**: visitors-identity

---

## Overview

`apps/api/services/social_intelligence.py::store_social_context` (lines 94-102) carries two related defects on the same 3-line body.

**BUG-1 — wholesale overwrite destroys sibling keys.** Line 100 does `enrichment_profile.social_context = context`. Its caller `apps/api/tasks/resolution_tasks.py:130-142` (the Celery-beat resolution sweep) runs, in ONE loop iteration for the same visitor: `enrich_tier1(...)` (which writes `social_context` keys) and then, when `visitor.intent_score >= 60`, `store_social_context(...)` — which destroys them. Net effect: for every visitor with `intent_score >= 60`, every other top-level key in `social_context` is silently destroyed. It is the only one of 9 writers that overwrites; the other 8 all merge. (Count corrected across PVL cycles 1-2: `apps/api/routers/visitors.py:1511-1514` — the `social_resolution` "scanning" seed — and `apps/api/routers/visitors.py:1429-1432` — the `osint_scan` "scanning" seed — are both correct read-modify-write merge writers that the first draft did not enumerate; `apps/api/services/social_resolver.py:292-295` (`resolve_social` Stage D) is a ninth writer, also already a correct merge writer, enumerated in PVL cycle 2.)

**BUG-2 — `social_context_updated_at` inflates the deep-research daily budget.** Line 101 stamps `social_context_updated_at`. `apps/api/services/usage_limits.py:101-110` (`get_enrich_usage()`) counts `EnrichmentProfile` rows where `social_context_updated_at >= today` to enforce the deep-research 3/day budget. So a social-intelligence write consumes a deep-research quota slot the user never used. `apps/api/routers/visitors_helpers.py:339-340` already establishes the correct precedent, with an explicit comment saying an OSINT scan must not count against that meter.

Both fixes follow existing in-repo convention exactly. No new pattern, no new infrastructure.

## Complexity

**SIMPLE.** Single function, ~4 lines changed, one new unit test file. No phases.

## Phase Completion Rules

This is a SIMPLE single-session plan with no phases. The single implementation unit is complete only when ALL of the following hold:

- Every checklist item 1-11 is done.
- Every Fully-Automated gate in Verification Evidence exits 0 (AC-1 to AC-6, AC-8, AC-9, AC-10).
- The Hybrid gate (AC-7) has been run with Postgres+Redis up, or is explicitly recorded as a deferred known-gap with its reason in the phase report.
- All four Backlog Follow-Up notes exist on disk (see the Validate Contract's authoritative Backlog artifacts table, per E11).
- Status may be promoted to `CODE DONE` when the code compiles and unit gates are green; promotion to `VERIFIED` additionally requires the AC-7 Hybrid gate to have actually run and passed. Code-only completion is never `VERIFIED`.

## INNOVATE Skip Record

INNOVATE was deliberately skipped. Rationale: the approach is settled by existing convention — 8 of the 9 writers to `EnrichmentProfile.social_context` already do a Python-level read-modify-write merge, and grep confirms **zero** `jsonb ||` / `jsonb_concat` precedent anywhere in the codebase. Introducing a Postgres-side merge would be new infrastructure with no precedent; there is no design decision left to make.

---

## Goals

1. `store_social_context` must preserve sibling top-level keys in `social_context` instead of destroying them.
2. `store_social_context` must stop consuming a deep-research quota slot.

## Non-Goals (explicit)

- Fixing the equivalent `social_context_updated_at` writes at `apps/api/services/enricher.py:825` (`_fetch_and_store_content`, content-reader path) **and** `apps/api/services/enricher.py:881` (`_fetch_and_store_github`, github-reader path). Backlog only — see Backlog Follow-Ups.
- Any concurrency / lost-update / row-lock safety. Pre-existing, affects all 8 existing merge writers equally.
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
| `apps/api/routers/visitors.py` (lines 1429–1432 `osint_scan` seed, 1511–1514 `social_resolution` seed) | **READ ONLY** — two additional correct merge writers found during PVL (`sc = dict(profile.social_context or {})` … reassign). Already correct; do NOT edit (G9) |
| `apps/api/services/social_resolver.py` (lines 292–295, `resolve_social` Stage D) | **READ ONLY** — ninth writer, found during PVL cycle 2. Writes BOTH the `osint_scan` and `social_resolution` blobs via `merged = dict(profile.social_context or {})` → reassign. Live and reachable (`visitors_helpers.py:35` imports `resolve_social`; `visitors_helpers.py:437` awaits it inside `_run_social_resolution_job`). Already correct; do NOT edit (G9) |

## Public Contracts

- `store_social_context(enrichment_profile: EnrichmentProfile, context: dict) -> None` — **signature unchanged**. Callers need no update.
- `EnrichmentProfile.social_context` (nullable JSONB) — column unchanged; write semantics change from replace to merge.
- `EnrichmentProfile.social_context_updated_at` — column unchanged; this function stops writing it. It has FOUR writers in total, all others unchanged: `enricher.py:825` (`_fetch_and_store_content`, content-reader) and `enricher.py:881` (`_fetch_and_store_github`, github-reader) — both the same non-deep-research conflation class as BUG-2, backlog only — plus `enricher.py:1070` (`deep_research`), which is a **legitimate** deep-research stamp that must stay.
- `get_enrich_usage(db, site_id) -> int` — code unchanged; the *observed count* will drop for sites where social-intelligence previously stamped the column. This is the intended correction (in the user's favour: they regain slots they were wrongly charged).

## Blast Radius

- **Files changed:** 2 (1 modify, 1 create).
- **Writer census (corrected during PVL cycles 1-2):** **9 total** writers to `EnrichmentProfile.social_context` — **8 already merge**, 1 (`store_social_context`) overwrites. The 8 merge writers, all verified line-by-line against the working tree: `apps/api/routers/visitors.py:1429-1432` (`osint_scan` seed), `apps/api/routers/visitors.py:1511-1514` (`social_resolution` seed), `apps/api/routers/visitors_helpers.py:396-398` (`_run_osint_scan_job`), `apps/api/routers/visitors_helpers.py:440-445` (`_run_social_resolution_job` error path), `apps/api/services/enricher.py:822-824` (`_fetch_and_store_content`), `apps/api/services/enricher.py:878-880` (`_fetch_and_store_github`), `apps/api/services/enricher.py:1063-1069` (`deep_research`), and `apps/api/services/social_resolver.py:292-295` (`resolve_social` Stage D — found in PVL cycle 2). All 8 use the reassign-a-new-dict pattern; none has a latent in-place-mutation bug. The pattern audit — not the count — is the load-bearing claim.
- **Packages:** `apps/api` only. No web, no pixel, no migrations.
- **Risk class:** quota/credit accounting (touches a column read by the budget meter). Per repo policy this is a high-risk class → requires at minimum automated tier coverage of the accounting behaviour; hybrid tier assigned for the DB-level count.
- **Reader safety:** all `social_context` readers verified defensive (`.get()`, `isinstance` guards, falsy checks) — a merge that *adds* keys cannot break any of them: `enricher.py:154-166`, `enricher.py:838-896`, `content_reader.py:446-471`, `content_reader.py:529-588`, `agents/segmenter.py:128`, `agents/workspace_tools.py:406`, `services/auto_drafter.py:56-70`, `routers/visitors.py:705`/`:1334`/`:1420`, `schemas/visitors.py:85`.
- **No consumer depends on the overwrite clearing data** — verified: `retention.py` purges only `events`/`agent_fetch_events`/`request_logs`; `do_not_resolve` gates whether enrichment *runs*, not what happens to already-written `social_context`; no GDPR/erasure path touches this column.
- **Existing test impact:** zero. No existing test exercises `store_social_context` or `fetch_social_context`. `tests/unit/test_content_enrich.py:151` asserts `social_context_updated_at is not None` on the **enricher** path (`enricher.py:825`, `_fetch_and_store_content`), which this plan does not touch — that assertion continues to pass.

---

## Guardrails (must hold)

| ID | Guardrail |
|---|---|
| G1 | Merge at the Python level (`{**(existing or {}), **context}`), matching the 8 existing merge writers. Do **NOT** introduce a Postgres `jsonb \|\|` pattern — zero precedent; that would be new infra. |
| G2 | `social_context` is a nullable column. Merging when it is `None` must not raise. |
| G3 | Do **NOT** fix the equivalent `social_context_updated_at` writes in `enricher.py`. This covers **BOTH** sites by name: `enricher.py:825` (`_fetch_and_store_content`) and `enricher.py:881` (`_fetch_and_store_github`). Backlog note only. `enricher.py:1070` (`deep_research`) is a legitimate deep-research stamp and must also stay. |
| G4 | Do **NOT** attempt concurrency / lost-update safety. Known-gap, pre-existing, shared with the 8 other merge writers. |
| G9 | Do **NOT** edit `apps/api/routers/visitors.py:1429-1432`, `:1511-1514`, or `apps/api/services/social_resolver.py:292-295`. All three were found during PVL (the last in cycle 2) and are already correct merge writers. |
| G5 | No migration. No schema change. Column exists and is nullable JSONB. |
| G6 | Before finalizing, confirm no code reads `social_context_updated_at` expecting social-intelligence to have set it. **Verified during PLAN and re-verified in PVL cycle 2:** the only functional reader is `usage_limits.py:110`; the three other writers are `enricher.py:825`, `enricher.py:881`, and `enricher.py:1070`, all untouched. |
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
| AC-5 | Regression for the reported bug, seeded with the REAL key sets: prior state carries the `enrich_tier1` → `_fetch_and_store_content` keys (`youtube` / `reddit` / `company_content` — verified: `content_reader.fetch_content_for_handles` returns `{"youtube": …, "reddit": …}`, and the company fallback writes `{"company_content": …}` at `enricher.py:810`); the incoming `store_social_context` context carries `recent_posts` / `topics` / `sentiment` (verified `social_intelligence.py:60-62`). The two sets are **DISJOINT**, so the real-world bug is pure destruction with no key collision — AC-3's collision case is synthetic but is kept deliberately to pin G7. Assert the prior keys survive verbatim. | `test_resolution_sweep_same_iteration_preserves_enrich_keys` | Fully-Automated |
| AC-6 | `store_social_context` does NOT modify `social_context_updated_at` (a pre-set value is unchanged; a `None` value stays `None`) | `test_store_does_not_touch_updated_at` | Fully-Automated |
| AC-7 | `get_enrich_usage()` does not count a profile whose only write today was social-intelligence | `tests/integration/test_usage_limits.py::test_enrich_usage_ignores_social_intelligence_only_write` — **NEW file** (`tests/integration/test_usage_limits.py` does not exist today; no test anywhere references `get_enrich_usage`). Real DB count. | Hybrid |
| AC-8 | No migration is required — `alembic heads` is unchanged by this plan and no new revision file is added | `git status` shows no file under `apps/api/migrations/versions/`; `alembic -c apps/api/alembic.ini heads` output identical pre/post | Fully-Automated |
| AC-9 | No existing test regresses — in particular `tests/unit/test_content_enrich.py` (which asserts the enricher path still stamps `social_context_updated_at`) stays green | full unit lane | Fully-Automated |
| AC-10 | **G8 dirty-tracking proof.** The JSONB attribute is REASSIGNED to a new object, not mutated in place: capture `original = profile.social_context` before the call, then after the call `assert profile.social_context is not original`. One added line inside the AC-1 test. Necessary because `apps/api/models/enrichment.py:59` declares `social_context` as a plain `mapped_column(JSONB, nullable=True)` with NO `MutableDict.as_mutable()` — an in-place `.update()` would be silently unflushed and AC-1..AC-6 would all still pass. | `test_store_merges_preserving_sibling_keys` (added assertion) | Fully-Automated |

---

## Implementation Checklist

1. Read `apps/api/services/social_intelligence.py` lines 90–105 and `apps/api/routers/visitors_helpers.py` lines 330–345 + 381–386 to confirm the current code and the comment style to mirror.
2. In `apps/api/services/social_intelligence.py::store_social_context`, replace the body's assignment with a read-modify-write merge:
   - read `enrichment_profile.social_context`, coalescing `None` to `{}` (G2);
   - build a NEW dict merging existing then incoming so incoming wins per key (G7, G8);
   - assign the new dict back to `enrichment_profile.social_context`.
3. In the same function, DELETE the `enrichment_profile.social_context_updated_at = datetime.now(timezone.utc)` line (BUG-2).
4. Add a docstring/comment on `store_social_context` in the style of `visitors_helpers.py:336-341`, stating: (a) it read-modify-writes, preserving sibling keys written by `enrich_tier1` and the other merge writers (do NOT put a writer count in the docstring); (b) it deliberately does NOT touch `social_context_updated_at` because that column drives the deep-research daily meter in `usage_limits.get_enrich_usage()` and a social-intelligence write must not count against it.
5. Check whether `datetime`/`timezone` imports in `social_intelligence.py` become unused after step 3; remove only if genuinely unused (grep the file first) — do not remove imports still referenced elsewhere in the module.
6. Create `tests/unit/test_social_intelligence.py` covering AC-1 through AC-6 **and AC-10**. Stub `self.db.commit()` (an `AsyncMock`) since the unit lane has no DB.
   - **Profile-object choice is PERMITTED either way** (GAP-4): the lighter `types.SimpleNamespace` precedent from `tests/unit/test_content_enrich.py:10,97` is explicitly acceptable and needs no ORM guard. Zero unit tests in `tests/unit/` currently construct a real `EnrichmentProfile`. If you DO choose a real `EnrichmentProfile`, then `import apps.api.main` first or SQLAlchemy raises `InvalidRequestError` (ORM-mapper gotcha). Neither choice affects AC-10's provability — identity comparison works on both.
   - **AC-10 is mandatory** (GAP-2): inside `test_store_merges_preserving_sibling_keys`, capture `original = profile.social_context` before calling `store_social_context`, and after the call assert `profile.social_context is not original`.
   - Seed AC-5 with the real disjoint key sets named in AC-10's neighbour row AC-5 (`youtube`/`reddit`/`company_content` prior state; `recent_posts`/`topics`/`sentiment` incoming).
7. **Create the NEW file `tests/integration/test_usage_limits.py`** (GAP-5) holding `test_enrich_usage_ignores_social_intelligence_only_write`: assert `get_enrich_usage(db, site_id)` returns 0 after a social-intelligence-only write. Pattern reference `tests/integration/test_osint_scan_endpoint.py:87`. Create the file even though the gate is deferred (Docker down) so the gate is real and runnable later — mark it skipped-loud (e.g. an explicit `pytest.mark.integration` + skip-on-no-DB), never silently absent.
8. Run the unit gate; fix to green.
9. Run the touched-file integration gate, then the full unit lane as regression (AC-9).
10. Confirm AC-8: `git status --short apps/api/migrations/` is empty.
11. Write the four backlog follow-up notes listed below (the Validate Contract's Backlog artifacts table is authoritative — E11).

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py -q` exits 0 | Fully-Automated | AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-10 |
| `.venv/bin/python3.11 -m pytest tests/integration/test_usage_limits.py -q` (NEW file, created by checklist step 7) exits 0 — **precondition:** `docker compose -f infra/docker-compose.yml up -d postgres redis` | Hybrid | AC-7 |
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
test("store_social_context reassigns the JSONB attribute (not in-place mutation)", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-10 G8 dirty-tracking")
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
| Concurrent-writer lost-update behaviour is untestable in the unit lane and unreliable in the integration lane (no locking exists to assert on) | No row-level locking or OCC anywhere in this call graph | C) Accept as known-gap — pre-existing, affects the 8 other merge writers identically; backlog note written |
| `get_enrich_usage()` count assertion requires a real Postgres | `func.count()` over a real table | B) Set up infra — `docker compose -f infra/docker-compose.yml up -d postgres redis`; tiered Hybrid (AC-7) |

## Test Infra Improvement Notes

- `tests/integration/test_usage_limits.py` does not exist and no test anywhere references `get_enrich_usage()` — the entire budget-meter module is untested. This plan creates the file (step 7) as the first coverage beachhead; broader `usage_limits.py` coverage is a separate follow-up.
- No unit test in `tests/unit/` constructs a real `EnrichmentProfile`; the only precedent is `SimpleNamespace`. A shared ORM-profile fixture (with the `import apps.api.main` guard applied once) would remove the per-test choice this plan has to leave open.

---

## Backlog Follow-Ups

1. **`enricher.py` `social_context_updated_at` conflation — TWO sites, not one.** Both `enricher.py:825` (`_fetch_and_store_content`, content-reader) and `enricher.py:881` (`_fetch_and_store_github`, github-reader — landed this session by the github-reader plan) stamp `social_context_updated_at`, inflating the same deep-research daily meter for a non-deep-research write. Arguably the same bug as BUG-2, twice. Both are explicitly OUT OF SCOPE here (G3). `enricher.py:1070` (`deep_research`) is a legitimate stamp and must stay. Note: `tests/unit/test_content_enrich.py:151` currently *asserts* the `:825` stamp, so fixing that one requires updating that test — a separate, deliberate change. Write `enricher-updated-at-conflation_NOTE_07-08-26.md` in `process/features/visitors-identity/backlog/`.
2. **Concurrency lost-update known-gap.** No row-level locking or OCC exists anywhere in the `social_context` call graph. The Celery-beat resolution sweep and API-triggered background tasks open independent sessions and can race; a read-modify-write merge can lose the loser's keys. This exposure is **pre-existing and shared by all 8 existing merge writers** — this plan neither introduces nor worsens it (it moves writer #9 from "always destroys" to "usually preserves"). Write `social-context-lost-update_NOTE_07-08-26.md`.
3. **AC-7 deferred (Docker daemon down) — `social-context-ac7-deferred_NOTE_07-08-26.md`.** Landing file is the NEW `tests/integration/test_usage_limits.py`, created by checklist step 7 but not run this session. The note must record these TWO SPECIFIC residuals, not a vague "run AC-7":
   - (a) **NULL-exclusion under three-valued logic.** `usage_limits.py:106-111` counts rows where `EnrichmentProfile.social_context_updated_at >= today` and nothing else. A row whose `social_context_updated_at` is `NULL` must be EXCLUDED (`NULL >= today` evaluates to NULL, not TRUE). Correct in principle, never executed against real Postgres here.
   - (b) **`_today_start()` naive-vs-`timestamptz` mismatch — concrete form.** `usage_limits.py:34-39` `_today_start()` returns a NAIVE datetime (`tzinfo=None`) and carries an inline comment (`usage_limits.py:35-36`) asserting "DB columns are TIMESTAMP WITHOUT TIME ZONE". That comment is **FALSE for this column**: `apps/api/models/enrichment.py:60` declares `social_context_updated_at` as `DateTime(timezone=True)` (i.e. `timestamptz`), and baseline migration `cd811a8b1f32:79` agrees. So `usage_limits.py:110` compares a naive Python datetime against a tz-aware column, which Postgres resolves by implicitly casting the naive value using the session `TimeZone`. Almost certainly fine in practice (project timezone is UTC) but a real pre-existing mismatch that AC-7 would exercise. Pre-existing and OUT OF SCOPE — `usage_limits.py` is READ ONLY per Touchpoints and this plan changes no line of it.
   Both are pre-existing SQL semantics this plan RELIES on but does not modify. AC-6 plus the unchanged read-only counting predicate makes the logic-level inference airtight; (a) and (b) are the only genuine residuals.
4. **`social_context` has NO purge path at all today.** `retention.py` purges only `events`, `agent_fetch_events`, `request_logs`. Nothing — including any GDPR/erasure route — deletes or redacts `EnrichmentProfile.social_context`, which holds scraped post content and derived topics. **Flag to the owner of `process/features/visitors-identity/active/graph-erasure-compliance_07-08-26/`**: that SPEC and PLAN contain zero references to `social_context` or `EnrichmentProfile`, so this surface appears unaccounted for in the erasure program. Write `social-context-no-purge-path_NOTE_07-08-26.md` and cross-reference it from the erasure plan's follow-ups.

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
3. **Validate-contract status:** written — `## Validate Contract`, `Gate: CONDITIONAL`, generated-by outer-pvl, 07-08-26. Two PVL supplement cycles applied: cycle 1 closed GAP-1..GAP-5; cycle 2 closed GAP-6..GAP-9 (writer census normalized to 9 total / 8 merge, `social_resolver.py:292-295` enumerated, `enricher.py:881` named, counts made consistent plan-wide, backlog residuals sharpened).
4. **Supporting context files loaded:** `process/context/all-context.md`, `process/context/tests/all-tests.md`, `process/features/visitors-identity/_GUIDE.md`, plus source reads of `social_intelligence.py`, `resolution_tasks.py`, `usage_limits.py`, `visitors_helpers.py`, `enricher.py` (grep).
5. **Next step for a fresh agent:** re-run PVL from V1 against this supplemented plan; on PASS/accepted-CONDITIONAL, EXECUTE starts at Implementation Checklist step 1. After a PASS/accepted-CONDITIONAL contract, EXECUTE starts at Implementation Checklist step 1. Do not widen scope to `enricher.py:825` or `enricher.py:881` (G3, both sites) or to concurrency safety (G4).

## Validate Contract

Status: CONDITIONAL
Date: 07-08-26
date: 2026-08-07
generated-by: outer-pvl
supersedes: 2026-08-07 (outer-pvl) — outer PVL pass 3, re-run after supplement cycle 2; this contract carries the current evidence and supersedes both prior outer-pvl contracts (pass 1 and pass 2)
PVL cycle: 2 recorded supplement cycles in `results.tsv` (`wc -l` = 5 → header + baseline + 3 cycle rows)

Parallel strategy (this VALIDATE pass): sequential single-pass
Rationale: `vc-validate-agent` has no `Agent` tool grant in this environment, so the designed Layer 1 / Layer 2 parallel fan-out cannot run internally. All four Layer 1 dimensions and all six Layer 2 sections were executed sequentially in-session, verified against the **working tree** (worktree is dirty with unrelated uncommitted work — deliberately NOT verified against HEAD).
Recommended strategy for EXECUTE: **sequential, one `vc-execute-agent` (opus)**. Signal score 1/7 (S6 only — high-risk class quota/credit accounting named in Blast Radius; S1 no, single package; S2 no schema/API/auth change; S3 no, INNOVATE skipped; S4 no; S5 no; S7 no, 3 files). LOW band. One function body + two new test files — no independent legs to parallelize, so parallel-subagents / workflow / agent-team would add coordination cost with zero parallelism to exploit. Cost guard: not triggered (1 agent).

### Test gates

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | Merge preserves pre-existing sibling top-level keys | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py::test_store_merges_preserving_sibling_keys -q` | B |
| AC-2 | New incoming keys are written | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py::test_store_writes_new_keys -q` | B |
| AC-3 | Key present in both resolves to incoming (last-write-wins per key, G7) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py::test_store_incoming_key_wins -q` | B |
| AC-4 | `social_context is None` start state merges without raising (G2) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py::test_store_handles_none_start_state -q` | B |
| AC-5 | Reported regression: `enrich_tier1`-shaped keys survive a following `store_social_context` | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py::test_resolution_sweep_same_iteration_preserves_enrich_keys -q` | B |
| AC-6 | `store_social_context` never modifies `social_context_updated_at` (BUG-2) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py::test_store_does_not_touch_updated_at -q` | B |
| AC-10 | G8 dirty-tracking: the JSONB attribute is REASSIGNED, not mutated in place | Fully-Automated | `assert profile.social_context is not original` inside `test_store_merges_preserving_sibling_keys` | B |
| AC-7 | `get_enrich_usage()` returns 0 after a social-intelligence-only write | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_usage_limits.py -q` — precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis` | D |
| AC-8 | No migration is added by this plan | Fully-Automated | `git status --short apps/api/migrations/versions/` produces no output | A |
| AC-9 | No existing test regresses (esp. `tests/unit/test_content_enrich.py`) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` exits 0 | B |

Failing stubs (Fully-Automated rows only — red-first starting point for EXECUTE):

```
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
test("store_social_context reassigns the JSONB attribute (not in-place mutation)", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: AC-10 G8 dirty-tracking")
})
```

gap-resolution legend: A — proven now; B — gate added by this plan's checklist; C — deferred to a named later phase; D — backlog test-building stub (named residual; keep-active).

C-4 reconciliation: the `strategy:` column carries ONLY Fully-Automated / Hybrid / Agent-Probe. Known-Gap is never a strategy value; AC-7's residual is carried via gap-resolution D.

Net-gate vacuous-green check: **PASSED.** Every developed behavior has at least one Fully-Automated or Hybrid proving gate. BUG-1 (merge) → AC-1..AC-5 + AC-10 Fully-Automated. BUG-2 (timestamp de-conflation) → AC-6 Fully-Automated at the unit tier plus AC-7 Hybrid at the DB tier. No behavior rests on Known-Gap alone.

Legacy line form (for existing validate-contract consumers):

- merge semantics (AC-1..AC-5, AC-10): `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py -q`
- quota de-conflation, unit tier (AC-6): `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py -q`
- quota de-conflation, DB tier (AC-7): `hybrid: .venv/bin/python3.11 -m pytest tests/integration/test_usage_limits.py -q + precondition docker compose up -d postgres redis` — DEFERRED, Docker re-confirmed DOWN this pass (`docker info` exits non-zero), accepted known-gap
- regression lane (AC-9): `Fully-automated: .venv/bin/python3.11 -m pytest tests/unit -m unit -q`
- no-migration (AC-8): `Fully-automated: git status --short apps/api/migrations/versions/` empty
- concurrency / lost-update: `known-gap: documented` — pre-existing, shared with all 8 other merge writers, backlog note required

### Supplement cycle 2 verification (focus item 1) — ALL FIVE ITEMS CONFIRMED APPLIED

Every cycle-2 fix was independently re-verified against the working tree.

| Gap | Supplement claim | Independent verdict |
|---|---|---|
| GAP-6 | `social_resolver.py:292-295` enumerated as the ninth writer (READ ONLY) and G9 extended to forbid editing it | **CLOSED — CORRECT.** Touchpoints row present (plan line 73), Blast Radius enumerates it as merge writer #8 (line 85), G9 (line 102) now names all three PVL-found sites including `social_resolver.py:292-295`. Source re-read: `social_resolver.py:292-295` is `merged = dict(profile.social_context or {})` → `merged["osint_scan"]` → `merged["social_resolution"]` → `profile.social_context = merged` at `:295`. Correct reassign pattern, live and reachable. |
| GAP-7 | All FOUR `social_context_updated_at` writers named; G3 + Follow-Up #1 cover BOTH conflation sites | **CLOSED — CORRECT.** Public Contracts (line 79) names `:825`, `:881`, `:1070` plus this function = 4. G3 (line 100) explicitly names BOTH `:825` and `:881` by name, closing the "literal reading makes `:881` fair game" hole. G6 (line 104) names all three others. Follow-Up #1 (line 209) covers both conflation sites. Source re-verified: `enricher.py:881` is `profile.social_context_updated_at = datetime.now(timezone.utc)` inside `_fetch_and_store_github`. |
| GAP-8 | Counts normalized plan-wide; checklist step 4 made countless | **CLOSED — CORRECT, and this was the highest-value fix.** Checklist step 4 (line 135) now reads "preserving sibling keys written by `enrich_tier1` and the other merge writers **(do NOT put a writer count in the docstring)**" — no number can ship into source. Every count in the plan BODY is now consistent: `grep -oE "[0-9]+ (other |existing |total )?(merge )?writers?"` returns only `8 merge` / `8 existing` / `8 other` / `9 writers` / `9 total` across lines 10, 23, 45, 57, 85, 98, 101, 197, 210. The only surviving `6`/`7` strings are inside the SUPERSEDED contract section (its own historical GAP-8 description at old line 385 and E10's warning at old line 419) — audit records, now replaced by this contract. |
| GAP-9 | Stale `visitors.py:1443-1447` anchor corrected | **CLOSED.** No `visitors.py:1443` reference survives in the plan body; the only occurrences were in the superseded contract's audit rows, replaced here. |
| Stale `:821` anchors | Corrected to `:825` | **CLOSED.** `grep -n "enricher.py:821\|enricher.py:1010"` returns zero hits in the plan body (only in superseded-contract audit prose, now replaced). |

### Independent writer census (focus item 2 — re-derived from scratch, third consecutive pass)

Method: `grep -rn "\.social_context\s*=" apps/api --include='*.py'`, raw output below, every hit read in full against the working tree.

```
apps/api/routers/visitors.py:1432:    profile.social_context = sc
apps/api/routers/visitors.py:1514:    profile.social_context = sc
apps/api/routers/visitors_helpers.py:398:        profile.social_context = merged
apps/api/routers/visitors_helpers.py:445:            profile.social_context = merged
apps/api/services/social_resolver.py:295:    profile.social_context = merged
apps/api/services/social_intelligence.py:100:        enrichment_profile.social_context = context
apps/api/services/enricher.py:824:            profile.social_context = merged
apps/api/services/enricher.py:880:            profile.social_context = merged
apps/api/services/enricher.py:1069:        profile.social_context = merged
```

**TRUE TOTAL: 9 writers — 8 merge, 1 overwrite. This EXACTLY MATCHES the plan's current claim.** The census is correct for the first time in three passes. Nine raw hits, nine writers, zero exclusions needed (the previously-excluded `job_change_detector.py:505` `social_context={}` is a function argument, not a `.social_context =` attribute assignment, so it does not even appear in this grep). All 8 merge writers use `dict(... or {})` → reassign; **zero latent in-place-mutation bugs exist anywhere in the census** — the load-bearing pattern claim is confirmed accurate.

`social_context_updated_at` census, re-derived: `grep -rn "social_context_updated_at\s*=" apps/api --include='*.py'` → exactly **4** writers (`social_intelligence.py:101` BUG-2 deleted by this plan; `enricher.py:825` content-reader conflation; `enricher.py:881` github-reader conflation; `enricher.py:1070` legitimate deep-research stamp). **Matches the plan exactly.** Exactly ONE functional reader: `usage_limits.py:110`.

### Refreshed live evidence (this pass)

| Check | Result |
|---|---|
| `.venv/bin/python3.11 --version` | `Python 3.11.15` — Infra fit PASS, `.vcignore` `!.venv` fix holds |
| `docker info` | non-zero exit — **Docker DOWN**, AC-7 Hybrid gate still cannot run |
| `ls tests/unit/test_social_intelligence.py tests/integration/test_usage_limits.py` | both ABSENT — neither create step can collide |
| `grep -rn "get_enrich_usage" tests/ apps/` | only `usage_limits.py:104` (def) + `:149` (internal caller) — zero test refs, AC-7 landing file genuinely new |
| `grep -rn MutableDict apps/api` | ZERO matches — G8 / AC-10 confirmed NECESSARY |
| `grep -n "datetime\|timezone" apps/api/services/social_intelligence.py` | imported at `:11`, referenced at exactly ONE other line (`:101`) — checklist step 5 is precisely correct: both imports DO become unused after step 3 and must be removed |
| `pytest tests/unit/test_content_enrich.py -q` | **19 passed in 0.30s** — AC-9 donor baseline green |
| `models/enrichment.py:59-60` | `social_context` = plain `mapped_column(JSONB, nullable=True)` (no `MutableDict`); `social_context_updated_at` = `DateTime(timezone=True)` — confirms both AC-10 provability and Follow-Up #3(b)'s naive-vs-`timestamptz` claim |
| `validate-plan-artifact.mjs` | **0 failures, 0 warnings**, 458 lines |

### New-gap scan on the cycle-2 supplement (focus item 3)

The supplement introduced no incorrect technical claim, no scope creep, and re-opened no previously-accepted concern. Every edit was text-only as reported. **One pre-existing inconsistency surfaced that no prior pass caught (GAP-10, below) — it predates both supplements and is NOT a regression introduced by cycle 2.**

### Net gate derivation

| Layer 1 dimension | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | PASS |
| Breaking changes | PASS |
| Security surface | CONCERN (previously accepted) |

| Layer 2 section | Status |
|---|---|
| Section A — `store_social_context` modification (checklist 1-5) | PASS |
| Section B — test creation (checklist 6-7) | PASS |
| Section C — AC-7 budget accounting | CONCERN (previously accepted) |
| Section D — backlog notes (checklist 11) | CONCERN (GAP-10 — pinned by E11) |
| Section E — AC-8 no-migration | PASS |
| Blast Radius accuracy | PASS (upgraded — GAP-6/7/8/9 all closed and independently re-verified) |

**Totals: 0 FAILs / 3 CONCERNs (2 previously accepted by user, 1 new and pinned) / 7 PASSes**

**→ Net Gate: CONDITIONAL**

Dimension findings:

- Infra fit: **PASS.** `.venv/bin/python3.11` executes (`Python 3.11.15`); the `.vcignore` `!.venv` fix holds. Every Fully-Automated gate command is runnable in this environment as written. Docker re-confirmed DOWN, so only the AC-7 Hybrid gate is blocked — expected and accepted.
- Test coverage: **PASS.** All ten ACs have a named proving gate at a real tier; nine are Fully-Automated and runnable now. AC-10 is provable and discriminating (identity comparison works on both `SimpleNamespace` and a real `EnrichmentProfile`; no `MutableDict` repo-wide means an in-place `.update()` would fail the assert), and its placement is pinned to the AC-1 non-empty-seed test by E8. AC-5's real disjoint key sets are verified. AC-7's landing file is named concretely and confirmed absent, so the deferred gate is real rather than notional. AC-9 donor baseline green at 19/19.
- Breaking changes: **PASS.** `store_social_context` signature unchanged. `social_context_updated_at` has exactly ONE functional reader (`usage_limits.py:110`); the other repo-wide matches are the model declaration, the baseline migration, and a prose comment — no Pydantic schema, no API response field, no dashboard surface, no staleness gate. The plan's writer lists are now complete and independently confirmed accurate (9 `social_context` writers, 4 `social_context_updated_at` writers). The change removes exactly one timestamp writer and adds none.
- Security surface: **CONCERN (previously accepted).** Risk class is quota/credit accounting; the change strictly REDUCES over-counting, in the user's favour, so there is no adversarial exposure. No auth, no secrets, no new external call, no trust boundary touched. The merge does make `social_context` blobs strict supersets of what the old code wrote, and Backlog Follow-Up #4 establishes there is NO purge/erasure path for that column at all — a small, real increase in retained scraped-PII residency. Accepted; cross-flagged to the erasure program.
- Section A (`store_social_context` modification, checklist 1-5): **PASS.** Edit targets confirmed unique and matchable against the working tree: `def store_social_context` at `social_intelligence.py:94`, docstring at `:99`, `enrichment_profile.social_context = context` at `:100`, `enrichment_profile.social_context_updated_at = datetime.now(timezone.utc)` at `:101`, `await self.db.commit()` at `:102`. Checklist step 5 is precisely correct (imports at `:11`, sole other reference at `:101` → both become unused and must be removed). Merge direction `{**existing, **incoming}` matches all 8 existing merge writers. G8 independently confirmed necessary.
- Section B (test creation, checklist 6-7): **PASS.** Both target files confirmed absent, so neither create step can collide. `SimpleNamespace` precedent verified present and sufficient (`test_content_enrich.py:10,97`, passes with no ORM-mapper guard). AC-10 placement pinned by E8.
- Section C (AC-7 budget accounting): **CONCERN (previously accepted).** The AC-6-sufficiency inference holds — see Open gaps for the predicate description and the two sharpened residuals. Docker DOWN re-confirmed this pass.
- Section D (backlog notes, checklist 11): **CONCERN (GAP-10 — pinned).** All four notes are correctly scoped and note #4's cross-flag to `graph-erasure-compliance_07-08-26/` remains the right handling; Follow-Up #1 now correctly covers BOTH enricher conflation sites and #3(b) carries the concrete naive-vs-`timestamptz` form. But checklist step 11 and Phase Completion Rules both say "**three** backlog follow-up notes" while FOUR are enumerated and four are required by this contract's artifact table. Neutralized by mandatory instruction E11 below, which makes the four-note requirement authoritative.
- Section E (AC-8 no-migration): **PASS.** Only assignment statements change; no column definition is touched. `git status --short apps/api/migrations/versions/` is a real load-bearing gate. The `alembic heads` half remains logically redundant (heads cannot move without a new revision file) — optional.
- Blast Radius accuracy: **PASS (upgraded from CONCERN).** The writer census now matches an independent from-scratch re-derivation exactly (9 total / 8 merge / 1 overwrite), the `social_context_updated_at` writer list matches exactly (4), every count in the plan body is internally consistent, and checklist step 4 can no longer ship a number into source. Three passes of census correction have converged.

Open gaps:

- **GAP-10 (new this pass — execution-correctness, PINNED not deferred):** the plan says "**three** backlog follow-up notes" in two places — Phase Completion Rules (plan line 40, a completion criterion) and Implementation Checklist step 11 (plan line 145) — while the Backlog Follow-Ups section enumerates **FOUR** (items 1-4) and the Autonomous Goal Block correctly says "four". Raw risk: an execute-agent reading step 11 literally writes 3 of 4 notes and Phase Completion Rules then reports the plan complete with a required artifact missing — and the missing one would most plausibly be #4, the `social_context` purge-path note that the accepted Security-surface CONCERN and the cross-flag to `graph-erasure-compliance_07-08-26/` both rest on. This is pre-existing (it predates both supplements), text-only, and is fully neutralized by mandatory instruction **E11**, which declares this contract's four-row Backlog artifacts table authoritative and overrides the stale "three". Accepted under the orchestrator convergence rule with the pin in place rather than spending a third supplement cycle on a two-word edit.
- AC-7 deferral: known-gap: documented as accepted. Docker re-confirmed DOWN this pass. Backlog note required.
  - Sufficiency assessment: `get_enrich_usage` at `usage_limits.py:104-113` filters on exactly TWO predicates — `EnrichmentProfile.site_id == site_id` AND `EnrichmentProfile.social_context_updated_at >= today`. The `site_id` predicate is orthogonal tenant scoping, so the inference is unaffected: if AC-6 proves the column is never written by `store_social_context`, and the counting predicate is read-only and unchanged, a social-intelligence-only write cannot increment the count. There is no third variable; the inference is airtight at the logic level.
  - Residual (a) — NULL-exclusion under SQL three-valued logic: a row whose `social_context_updated_at` is `NULL` must be EXCLUDED by `>= today` (`NULL >= today` evaluates to NULL, not TRUE). Correct in principle, never executed against real Postgres here.
  - Residual (b) — concrete type mismatch: `_today_start()` (`usage_limits.py:34-39`) returns a NAIVE datetime (`tzinfo=None`) and carries an inline comment asserting "DB columns are TIMESTAMP WITHOUT TIME ZONE". That premise is **FALSE for this column** — `models/enrichment.py:60` declares `social_context_updated_at` as `DateTime(timezone=True)` (re-verified this pass) and baseline migration `cd811a8b1f32:79` agrees. So `usage_limits.py:110` compares a naive Python datetime against a tz-aware column, resolved by Postgres via an implicit cast using the session `TimeZone`. Almost certainly fine (project timezone is UTC) but a real pre-existing mismatch AC-7 would exercise. **Pre-existing and OUT OF SCOPE** — `usage_limits.py` is READ ONLY per Touchpoints and this plan changes no line of it.
- Concurrency / lost-update: known-gap: documented. Pre-existing, shared identically by all 8 existing merge writers; this plan neither introduces nor worsens it (it moves writer #9 from "always destroys" to "usually preserves"). Backlog note required (Follow-Up #2).
- `social_context` has no purge/erasure path: known-gap: documented as NEW PLAN REQUIRED — cross-flagged to `process/features/visitors-identity/active/graph-erasure-compliance_07-08-26/` via Backlog Follow-Up #4.
- `enricher.py` equivalent `social_context_updated_at` conflation at TWO sites (`:825`, `:881`): known-gap: documented as out of scope by G3 (both named). Backlog Follow-Up #1.
- No automated gate enforces the merge PATTERN across the other 8 writers: known-gap: documented. The census proves the pattern by full source read, but a future writer could introduce an in-place mutation with nothing to catch it. Out of scope here.

What this coverage does NOT prove:

- `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py -q` (AC-1..AC-6, AC-10) does NOT prove: that the merged dict is actually FLUSHED to Postgres (no session, no DB in the unit lane — AC-10 proves reassignment, the necessary precondition for the flush, but not the flush itself); that `resolution_tasks.py:130-142` wires `enrich_tier1` and `store_social_context` in the asserted order at runtime (the test hand-seeds prior state instead of running the sweep); that concurrent writers do not lose each other's keys; that the real `fetch_social_context` output shape matches the shape the test feeds in; that the `intent_score >= 60` gate behaves as assumed.
- `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` (AC-9) does NOT prove: any integration-lane or e2e behavior; that the enricher path's own `social_context_updated_at` stamps are correct (only that they are unchanged); that no integration test regresses.
- `git status --short apps/api/migrations/versions/` (AC-8) does NOT prove: that the live database schema matches the model; that the current alembic head is applied anywhere; only that THIS plan added no revision file.
- AC-7 (deferred) leaves unproven: real-Postgres exclusion of `NULL` `social_context_updated_at` rows from the `>= today` count; and that the naive-vs-`timestamptz` comparison at `usage_limits.py:110` resolves to the intended UTC day boundary under the live session `TimeZone`.
- No gate at any tier proves: that removing the timestamp write does not change any operator-facing budget display (verified by grep to have no reader beyond `usage_limits.py:110`, but never exercised end-to-end); that the 8 other merge writers keep working after this change (none is touched, and no gate covers them).
- The census work in this contract proves the PATTERN (all 8 merge writers reassign a new dict) by full source read, but no automated gate enforces it.
- Nothing in this contract proves the four backlog notes were actually written — that is a manual checklist item (step 11) pinned by E11, not a gate.

Plan updates applied by VALIDATE: NONE. The validate-agent made zero edits to the plan body — only this `## Validate Contract` section and the `## Autonomous Goal Block` below were written. GAP-10 is neutralized via execute-agent instruction E11 rather than a plan-body edit, under the orchestrator convergence rule.

Execute-agent instructions:

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | The `.venv` PreToolUse blocker is ALREADY RESOLVED — `/Users/apple/getbeam/.claude/.vcignore` contains `!.venv` and `.venv/bin/python3.11 --version` returned `Python 3.11.15` during VALIDATE. No action needed. If a gate command is nonetheless denied, that is a hook regression: re-check `.claude/.vcignore` rather than working around the hook, and never silently skip a gate you could not run — report it. | Session start |
| E2 | Use `.venv/bin/python3.11 -m pytest`, never `.venv/bin/pytest` — the console-script shebang points at a stale pre-move path and fails. | Every pytest invocation |
| E3 | AC-10 is mandatory, not optional. Capture the original dict object, call `store_social_context`, then assert `profile.social_context is not original`. `enrichment.py:59` has no `MutableDict` (zero repo-wide, re-verified), so an in-place `.update()` would be silently unflushed and every other AC would still pass. | Checklist step 6 |
| E8 | **AC-10 must live in the AC-1 test (`test_store_merges_preserving_sibling_keys`), which seeds a NON-EMPTY pre-existing dict.** Do NOT place it in the AC-4 `None`-start-state test: there `original` is `None`, so the assert would pass vacuously against every implementation including the buggy in-place variant, and the gate would be worthless. | Checklist step 6 |
| E4 | Seed AC-5 with the REAL key names: prior state `{"company_content": {...}}` (or `youtube` / `reddit`), incoming `{"recent_posts": [...], "topics": [...], "sentiment": None}`. Assert the prior key survives verbatim. | Checklist step 6 |
| E5 | Creating the AC-7 test file is still required even though the gate is deferred — create `tests/integration/test_usage_limits.py` so the gate exists and is runnable once Docker is up. Mark it skipped/failing-loud, never silently absent. | Checklist step 7 |
| E6 | Do NOT widen scope. `enricher.py` stays untouched (G3) — BOTH `enricher.py:825` and `enricher.py:881`, see E9. Concurrency safety stays untouched (G4). The 8 existing merge writers are all correct as-is — do not edit `visitors.py:1429-1432`, `visitors.py:1511-1514`, `social_resolver.py:292-295` (all three covered by G9), `visitors_helpers.py:396-398`, `visitors_helpers.py:440-445`, `enricher.py:822-824`, `enricher.py:878-880`, or `enricher.py:1063-1069`. | Throughout |
| E9 | **G3's protection covers TWO sites, not one.** `enricher.py:825` (`_fetch_and_store_content`) AND `enricher.py:881` (`_fetch_and_store_github`) both stamp `social_context_updated_at` for a non-deep-research write. Both are out of scope. `enricher.py:1070` (`deep_research`) is a legitimate stamp and must also stay. Change exactly one line's worth of timestamp behavior in this plan: the deletion at `social_intelligence.py:101`. | Throughout |
| E7 | Record the AC-7 deferral in the phase report with its two SPECIFIC residuals: (a) NULL-exclusion under `>= today` three-valued logic; (b) the naive-`_today_start()`-vs-`timestamptz`-column comparison at `usage_limits.py:110` (`models/enrichment.py:60` is `DateTime(timezone=True)`, contradicting the inline comment at `usage_limits.py:35-36`). A vague "AC-7 not run" is insufficient. | Checklist step 11 |
| E10 | Checklist step 4 correctly instructs you to put NO writer count in the docstring — follow it literally. Write "the other merge writers" with no number. If you nonetheless name a count, the VERIFIED number is **9 total writers, 8 of which merge** (`store_social_context` is the ninth and the only overwriter), independently re-derived three times. | Checklist step 4 |
| E11 | **WRITE ALL FOUR BACKLOG NOTES.** Checklist step 11 and Phase Completion Rules both say "three" — that number is STALE (GAP-10). The Backlog Follow-Ups section enumerates FOUR items and the Backlog artifacts table in this contract is the AUTHORITATIVE list: `enricher-updated-at-conflation_NOTE_07-08-26.md`, `social-context-lost-update_NOTE_07-08-26.md`, `social-context-no-purge-path_NOTE_07-08-26.md`, `social-context-ac7-deferred_NOTE_07-08-26.md`. Do not treat the plan as complete with three. Note #4 (purge path) is the one most likely to be dropped and is the one the accepted Security-surface concern rests on — it must exist and must cross-reference `process/features/visitors-identity/active/graph-erasure-compliance_07-08-26/`. Also correct the two stale "three" strings (plan lines 40 and 145) to "four" while you are in the file. | Checklist step 11 — MANDATORY |

Backlog artifacts required (AUTHORITATIVE list — four, per E11):

| Artifact | Location | What it tracks |
|---|---|---|
| `enricher-updated-at-conflation_NOTE_07-08-26.md` | `process/features/visitors-identity/backlog/` | **TWO** sites stamp the meter column for a non-deep-research write: `enricher.py:825` (`_fetch_and_store_content`) and `enricher.py:881` (`_fetch_and_store_github`). Fixing the first also requires updating `tests/unit/test_content_enrich.py:151`, which currently asserts that stamp. `enricher.py:1070` (`deep_research`) is legitimate and must stay. |
| `social-context-lost-update_NOTE_07-08-26.md` | `process/features/visitors-identity/backlog/` | Concurrency lost-update, pre-existing across all 8 merge writers (incl. `social_resolver.py:292-295`) |
| `social-context-no-purge-path_NOTE_07-08-26.md` | `process/features/visitors-identity/backlog/` | No purge/erasure path for `social_context`; NEW PLAN REQUIRED; cross-flag to `graph-erasure-compliance_07-08-26/` |
| `social-context-ac7-deferred_NOTE_07-08-26.md` | `process/features/visitors-identity/backlog/` | AC-7 deferred (Docker re-confirmed down). Residuals: (a) NULL-exclusion under `>= today` 3VL; (b) `_today_start()` returns naive `tzinfo=None` while `enrichment.py:60` is `DateTime(timezone=True)` — the inline comment at `usage_limits.py:35-36` is false for this column |

Gate: CONDITIONAL

Accepted by: orchestrator convergence rule, autopilot run 07-08-26 — plus user (prior session). Accepted concerns, by name: (1) AC-7 Hybrid gate deferred, Docker daemon re-confirmed DOWN this pass [user, prior session]; (2) `enricher.py` `social_context_updated_at` conflation out of scope at BOTH sites `:825` and `:881` [user, prior session]; (3) concurrency / lost-update out of scope [user, prior session]; (4) `social_context` purge-path absence deferred to the erasure program [user, prior session]; (5) no automated gate enforces the merge pattern across the other 8 writers [orchestrator convergence rule]; (6) **GAP-10** — the stale "three backlog notes" strings at plan lines 40 and 145, accepted with the mandatory E11 pin that makes the four-note requirement authoritative [orchestrator convergence rule, autopilot run 07-08-26].

Note on terminality: `results.tsv` records TWO completed supplement cycles (`wc -l` = 5 → header + baseline + 3 cycle rows), so the mechanical N≥1 condition for `PHASE_COMPLETE: VALIDATE` is satisfied. Cycle 2's five fixes are all independently verified applied and correct, the writer census converged and now matches an independent from-scratch re-derivation exactly, and the sole new finding (GAP-10) is a two-word documentation staleness whose execution-correctness edge is fully pinned by mandatory instruction E11. Zero FAILs at any layer. Per the orchestrator convergence rule this contract is TERMINAL: no supplement cycle 3.

---

## Autonomous Goal Block

```
SESSION GOAL: Fix store_social_context wholesale overwrite (merge instead) and stop it inflating the deep-research daily budget.
Charter + umbrella plan: N/A — single standalone plan (no umbrella with ## Stable Program Goal governs this task folder)
Autonomy: Proceed without approval pauses on reversible work. Write the two test files, apply the two-part code fix, run gates, write the FOUR backlog notes. Blocked items go to backlog — always find a path to proceed.
Hard stop conditions / safety constraints:
- Do not touch apps/api/services/enricher.py at all (G3). Protection covers BOTH conflation sites: :825 (_fetch_and_store_content) and :881 (_fetch_and_store_github). :1070 (deep_research) is a legitimate stamp and must stay.
- Do not attempt concurrency / row-lock / lost-update safety (G4 — pre-existing, shared with the 8 other merge writers).
- Do not introduce a Postgres jsonb || merge (G1 — zero precedent in this repo; would be new infrastructure).
- Do not add any migration or schema change (G5).
- Do not edit any of the 8 existing merge writers — all already correct: visitors.py:1429-1432, visitors.py:1511-1514, social_resolver.py:292-295 (all three under G9), visitors_helpers.py:396-398, visitors_helpers.py:440-445, enricher.py:822-824, enricher.py:878-880, enricher.py:1063-1069.
- Change exactly one line's worth of timestamp behavior: the deletion at social_intelligence.py:101.
- Put NO writer count in the new docstring (checklist step 4, E10).
- Write ALL FOUR backlog notes (E11) — the plan's "three" at lines 40 and 145 is stale.
- Do not mark the plan VERIFIED while AC-7 is deferred — CODE DONE is the ceiling until Docker is up.
- Any irreversible or outward-facing action not named in this contract: stop and ask.
Next phase: EXECUTE — sequential, one vc-execute-agent (opus). Signal score 1/7 (S6 only). Gate CONDITIONAL with 2 recorded supplement cycles and all concerns accepted; EXECUTE is unblocked.
Validate contract: inline in plan (## Validate Contract), generated-by outer-pvl, pass 3, 2 supplement cycles
Execute start: fully-auto — `.venv/bin/python3.11 -m pytest tests/unit/test_social_intelligence.py -q`, then `.venv/bin/python3.11 -m pytest tests/unit -m unit -q`, then `git status --short apps/api/migrations/versions/` (must be empty) | hybrid (deferred): `.venv/bin/python3.11 -m pytest tests/integration/test_usage_limits.py -q` needs `docker compose -f infra/docker-compose.yml up -d postgres redis` | probe scenario: none | high-risk pack: no (quota accounting, but the change strictly reduces over-counting, in the user's favour)
NOTE: the .venv PreToolUse blocker is already fixed — /Users/apple/getbeam/.claude/.vcignore contains !.venv, verified Python 3.11.15 during VALIDATE. No prerequisite action needed.
```
