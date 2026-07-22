---
phase: phase-07-outreach-exclusion
date: 2026-07-22
status: COMPLETE
feature: evallayer
plan: process/features/evallayer/active/evallayer_22-07-26/phase-07-outreach-exclusion_PLAN_22-07-26.md
---

# Phase 07 — Outreach-Exclusion Guardrail — EXECUTE Report

**AC10 (SPEC's highest-priority safety gate) is implemented, wired at all 3 real send/export
entry points, and proven green.** An agent-classified record can never be an outreach target.

## What Was Done

**Step A — Guard extended** (`apps/api/services/identity_classification.py`):
- `is_emailable_identity(provider: str | None, source_agent_visit_id: str | None = None) -> bool`.
- Body FIRST line is the unconditional AC10 override: `if source_agent_visit_id is not None: return False`, checked before the existing `identity_level(provider) == "person"` return.
- Docstring updated to document the AC10 guardrail (agent-origin records are never outreach targets, regardless of provider; genuine defense-in-depth).

**Step B — 3 call sites wired** (behavior-neutral today via `getattr`, activates the instant Phase 5 adds the column):
- `campaign_sender.py:202` → `is_emailable_identity(iv.resolution_provider, getattr(iv, "source_agent_visit_id", None))`.
- `campaigns.py:725` (`_resolve_linkedin_targets`) → same on `iv`.
- `csv_exporter.py:79` → same on `identified`.

**Step C — Regression tests** (`tests/unit/test_agent_origin_exclusion.py`, new; `pytestmark = pytest.mark.unit`; no Docker):
- C1 `test_agent_origin_overrides_person_level` — parametrized over all 9 `PERSON_LEVEL_PROVIDERS`; each is emailable with no marker, non-emailable with `source_agent_visit_id="fake-uuid"`.
- C2 `test_non_agent_identity_unaffected` — `rb2b`/`None` True; `hunter`/`None` False.
- C3 — 3 site-level tests (`campaign_sender` / `_resolve_linkedin_targets` / `csv_exporter`) exercising each site's REAL code path with a mocked `AsyncSession` (AsyncMock `db.execute` side_effect chain; Phase 4 no-Docker precedent). Each uses an agent-origin mock with a person-level provider on purpose, so exclusion proves the AC10 override (not the pre-existing company-level filter) does the work. All Fully-Automated — no Hybrid/known-gap fallback needed.
- C5 `test_source_agent_visit_id_literal_field_name_tripwire` — parametrized text-search tripwire asserting the literal `"source_agent_visit_id"` is present in the guard file + all 3 call-site files.

**C4 non-vacuity (verified by reasoning per plan/E3, line not physically deleted):** against pre-Phase-07 code the 2-arg call raised `TypeError` (single-positional signature) — C1 was genuinely red. Removing the A2 override line makes C1 fail red for every person-level provider.

## Test Gate Outcomes

```
.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q
17 passed in 0.53s
```
```
.venv/bin/python -m pytest tests/unit -q
752 passed, 2 skipped, 1 warning in 7.31s
```
Baseline was 735 passed / 2 skipped → +17 = 752, exactly the new tests. No regression. The 1 warning is pre-existing in `test_optout.py` (unrelated coroutine-never-awaited).

```
.venv/bin/python -m pytest tests/unit/test_outbound_identity_gate.py test_content_campaign.py test_csv_injection.py test_linkedin_sync.py -q
45 passed
```
The 3 call-site edits break no existing campaign/outreach/csv/linkedin tests.

## Phase 5 Contract (BINDING — forward-looking, Phase 5 must honor)

1. **D1** — Phase 5 MUST add `IdentifiedVisitor.source_agent_visit_id: str | None` using the EXACT literal field name `source_agent_visit_id`. The `getattr` calls (Step B) and the C5 tripwire read this exact string; any rename silently disables the guard unless C5 is updated in the same commit (now test-enforced — a rename fails CI loudly).
2. **D2** — Phase 5 MUST set this field on every agent-derived company-resolution row it creates.
3. **D3** — Phase 5 MUST NOT assign any `PERSON_LEVEL_PROVIDERS` value as `resolution_provider` on an agent-resolved record (the A2 override is belt-and-suspenders, not a substitute for correct classification).
4. **D4** — No future phase may add a 4th send/export path bypassing `is_emailable_identity`; any new path must call it with the `source_agent_visit_id` marker wired the same way. (Currently a written contract, not a central chokepoint — accepted narrow-scope residual; a centralizing wrapper is backlog-worthy.)
5. **D5/D6** — Phase 5's exit gate MUST re-run `tests/unit/test_agent_origin_exclusion.py` (incl. the C5 tripwire) against REAL Phase-5-created rows (not mocks) before Phase 5 is marked VERIFIED, and MUST keep the C5 tripwire green if it touches any of the 4 guarded files.

## What Was Skipped or Deferred

Nothing in this phase's scope was skipped. No schema column added (D1 is Phase 5's job). `known_hash.py` untouched. No commit made (per instructions).

## Plan Deviations

None. Implemented exactly per the validate-contract, order A → B → C1/C2 → C3 → C5.

## Test Infra Gaps Found

None blocking. All 3 site-level tests stayed Fully-Automated via mocked AsyncSession (no Hybrid/known-gap fallback required).

## EVL Confirmation

Independent `vc-tester` re-run (not relying on execute-agent's internal claim of green):

- AC10 gate: `.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q` → **17/17 passed**.
- Full unit regression: `.venv/bin/python -m pytest tests/unit -q` → **752 passed, 2 skipped** (baseline 735 + 17 new = exact match, 0 regressions).
- Adjacent-surface check: `.venv/bin/python -m pytest tests/unit/test_outbound_identity_gate.py -q` → **18/18 passed** (the pre-existing outbound identity gate this phase extends is unbroken).
- **Non-vacuity confirmed by independent code inspection** (not just plan-time reasoning): the `source_agent_visit_id` override in `is_emailable_identity` is the first, unconditional statement in the function body — physically deleting it would flip `test_agent_origin_overrides_person_level` (C1) to red for every `PERSON_LEVEL_PROVIDERS` value. All gates Fully-Automated, zero Docker dependency.
- **EVL note (non-blocking):** this confirmation relied on aggregate pass counts and a targeted code-inspection of the override's position, rather than re-grepping each of the 3 call sites and the C5 tripwire body line-by-line independently. Accepted as sufficient because the 17-test suite (C1-C5) already exercises every call site and the tripwire directly — re-deriving the same coverage by hand would be redundant, not additive.

## Closeout Packet

- Selected plan: `process/features/evallayer/active/evallayer_22-07-26/phase-07-outreach-exclusion_PLAN_22-07-26.md`
- Finished: guard override (first + unconditional), 3 call sites wired, 5 test groups (17 tests) green, regression clean.
- Verified: AC10 gate 17/17; full unit 752 passed/2 skipped; no existing campaign/outreach test broken.
- Unverified (out of scope): real-Postgres round-trip behavior (D5 — deferred to Phase 5 with real rows).
- Classification: **✅ VERIFIED** — EVL confirmation run complete (independent `vc-tester` re-run, see EVL Confirmation section above); no Docker known-gap in this phase (unlike Phases 1-4); the only residual (D5, real-Phase-5-row re-verification) is a forward dependency on Phase 5's own exit gate, not a gap in this phase's own proof.

## Forward Preview

- **Test Infra Found:** `-m unit` deselects unmarked files; new unit test files must set `pytestmark = pytest.mark.unit` to be collected by the exit-gate command. Mocked-AsyncSession side_effect chains are the established no-Docker pattern for exercising DB-reading service functions.
- **Blast Radius Changes:** `identity_classification.py` (guard), `campaign_sender.py`, `campaigns.py`, `csv_exporter.py` (call sites), new `tests/unit/test_agent_origin_exclusion.py`.
- **Commands to Stay Green:** `.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q` and `.venv/bin/python -m pytest tests/unit -q`.
- **Dependency Changes:** none. `is_emailable_identity` gained one optional kwarg with a safe default — fully backward-compatible.

## Follow-up Stubs / CONTEXT_PARTIAL

- No follow-up plan stubs created.
- No CONTEXT_PARTIAL items.
- Two accepted non-blocking known gaps (per PVL, not backlog artifacts): skip-counter miscategorization (agent-origin skips share the existing company-level counter — observability-only), and D4 centralization (written contract, not a code-enforced chokepoint).
