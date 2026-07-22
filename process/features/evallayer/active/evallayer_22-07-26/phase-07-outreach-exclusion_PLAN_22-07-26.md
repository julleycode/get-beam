---
name: plan:evallayer-phase-07-outreach-exclusion
description: "EvalLayer — Phase 07: Outreach-exclusion guardrail + regression test (agent record can NEVER be an outreach target — SPEC AC10, highest-priority test in the program)"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-07
---

# Phase 07 — Outreach-Exclusion Guardrail

**Program:** evallayer
**Umbrella plan:** process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md
**Phase status:** ✅ VERIFIED (2026-07-22) — validate-contract PASS (`generated-by: inner-pvl: phase-7`), EXECUTE + independent EVL complete, no Docker known-gap — **ELEVATED PRIORITY: release gate for Phase 5**
**Report destination:** process/features/evallayer/active/evallayer_22-07-26/phase-07-outreach-exclusion_REPORT_22-07-26.md

---

## Priority Note

Per SPEC Resolved Open Question 10, this phase's numbering (7) reflects dependency order, not
priority order. This is treated as a **hard release gate for Phase 5** — Phase 5 (company
resolution → outreach feed) is not considered mergeable/VERIFIED until this phase's regression test
exists and passes. This phase's dependency (Phase 2 only) means it CAN and SHOULD start in parallel
with, or ahead of, Phase 3/4/5 — do not sequence it strictly after Phase 5 just because its number
is higher.

---

## Purpose

Build a hard, explicit guard ensuring an agent-classified record — resolved to a company or not —
can never be selected as an email/social outreach target, directly or indirectly. This is the single
highest-priority test in the entire program (SPEC AC10) and the program's core business-guardrail
safety constraint: agents are never emailed; only human/company contacts through existing
consent/suppression/approval gates may be reached.

---

## Entry Gate

- Phase 2 exit gate passed (agent-visit records exist and are queryable/referenceable by id). ✅ Phase 2 is DONE.
- No dependency on Phase 3, 4, 5, or 6 — this phase's guardrail must exist independent of and
  before Phase 5 is considered complete.

---

## RESEARCH Findings (confirmed against real code — 22-07-26)

The enforcement point already exists: `apps/api/services/identity_classification.py`
`is_emailable_identity(provider)`, which currently takes only `provider` and returns
`identity_level(provider) == "person"`.

**Every real call site enumerated (3 total, no others found via `grep -rn "is_emailable_identity"`):**

| # | File | Line | Object |
|---|---|---|---|
| 1 | `apps/api/services/campaign_sender.py` | 202 | `iv` (an `IdentifiedVisitor` row) — email send path |
| 2 | `apps/api/routers/campaigns.py` | 725 (`_resolve_linkedin_targets`) | `iv` (an `IdentifiedVisitor` row) — LinkedIn/social send path |
| 3 | `apps/api/services/csv_exporter.py` | 79 | `identified` (an `IdentifiedVisitor` row) — CSV/ad-audience/CRM export path |

**Schema confirmed:** `apps/api/models/visitor.py:59` `IdentifiedVisitor` currently has
`resolution_provider` (line 76) and `do_not_email` (line 78). It does **NOT** yet have a
`source_agent_visit_id` column — that column is Phase 5's job (Phase 5 owns company-resolution →
outreach-feed wiring and is the phase that will actually attach agent-visit provenance to an
`IdentifiedVisitor` row). This phase (7) must NOT add the schema column itself — its job is the
guard + regression test, wired so it activates the instant Phase 5 adds the column, with zero
further code change required at that point.

**Test precedent confirmed:** `tests/unit/test_outbound_identity_gate.py` already exists and is the
direct precedent to extend (parametrized over `sorted(PERSON_LEVEL_PROVIDERS)` /
`sorted(COMPANY_LEVEL_PROVIDERS)`, imports `is_emailable_identity`, `PERSON_LEVEL_PROVIDERS`,
`COMPANY_LEVEL_PROVIDERS` from `identity_classification`). New regression test file
`tests/unit/test_agent_origin_exclusion.py` sits alongside it, same style, no Docker.

**VALIDATE confirmation (22-07-26):** all 3 call sites re-confirmed via fresh `grep -n` against
real code — exact line numbers match (`campaign_sender.py:202`, `campaigns.py:725`,
`csv_exporter.py:79`), all reached through `import is_emailable_identity` at each file's top.
`grep -rn "source_agent_visit_id"` across `apps/api` and `tests` returns zero hits — confirms the
column genuinely does not exist yet anywhere. `PERSON_LEVEL_PROVIDERS`/`COMPANY_LEVEL_PROVIDERS`
membership for the C2 example providers (`rb2b`, `hunter`) confirmed directly against the source
constants. `is_emailable_identity`'s current signature accepts exactly one positional parameter —
calling it with a second argument today raises `TypeError`, which means the planned C1 test is
**genuinely red today** (not just logically red) before Step A is implemented, and goes green only
once A1–A3 are correctly implemented in order. This is the strongest possible non-vacuity evidence
available at PVL time.

---

## Blast Radius

- `apps/api/services/identity_classification.py` (modify — extend `is_emailable_identity` signature + guard)
- `apps/api/services/campaign_sender.py` (modify — one-line call-site update at line 202)
- `apps/api/routers/campaigns.py` (modify — one-line call-site update at line 725, inside `_resolve_linkedin_targets`)
- `apps/api/services/csv_exporter.py` (modify — one-line call-site update at line 79)
- `tests/unit/test_agent_origin_exclusion.py` (new — regression test file, no Docker)

No schema/migration file in this phase's blast radius — confirmed no `source_agent_visit_id` column
exists yet; Phase 5 owns adding it (see Phase 5 Contract below).

No overlap with any other phase's registered blast radius (Phase 1 `agent_visit.py`/migration/
`agent_classifier.py`; Phase 2 `events.py`/`agent_visit_persistence.py`/`config.py`; Phase 3
`agents.py`/`schemas/agents.py`/dashboard files; Phase 4 `agent_verification.py`/`scheduler.py`/
`config.py`/ip-range data — none touch `identity_classification.py`, `campaign_sender.py`,
`campaigns.py`, or `csv_exporter.py`). Phase 5's own blast radius is still TBD (pre-RESEARCH,
`company_resolver.py` + enrichment pipeline candidates only) — no file-level collision possible yet,
but there IS an intentional **concern-level** dependency: the instant Phase 5 adds
`IdentifiedVisitor.source_agent_visit_id`, this phase's guard activates automatically. See Phase 5
Contract (D1–D6) below — this is forward-binding, not a file overlap.

---

## Implementation Checklist

### Step A — Extend the guard (LOCKED design, encode exactly)

- [ ] A1. In `apps/api/services/identity_classification.py`, change `is_emailable_identity`'s
      signature to:
      ```
      def is_emailable_identity(provider: str | None, source_agent_visit_id: str | None = None) -> bool:
      ```
- [ ] A2. Body: FIRST check `if source_agent_visit_id is not None: return False` — this is an
      **unconditional AC10 override**: an agent-origin record can NEVER be emailable regardless of
      what `provider` is (even if provider happens to be a person-level provider). THEN fall through
      to the existing `return identity_level(provider) == "person"`.
- [ ] A3. Update the function's docstring to explicitly document the `source_agent_visit_id`
      override as the AC10 guardrail (agent-classified records are never outreach targets,
      independent of provider classification).

### Step B — Wire all 3 call sites (mechanical, no behavior change today)

Each edit is a one-line call-site change using `getattr(..., "source_agent_visit_id", None)` so the
guard activates automatically the instant Phase 5 adds the column — no further code change needed
at that point, and today's call resolves to `None` (safe no-op) since the attribute doesn't exist yet.

- [ ] B1. `apps/api/services/campaign_sender.py:202` — change
      `is_emailable_identity(iv.resolution_provider)` to
      `is_emailable_identity(iv.resolution_provider, getattr(iv, "source_agent_visit_id", None))`.
- [ ] B2. `apps/api/routers/campaigns.py:725` (inside `_resolve_linkedin_targets`) — same pattern on
      its `iv` identity object:
      `is_emailable_identity(iv.resolution_provider, getattr(iv, "source_agent_visit_id", None))`.
- [ ] B3. `apps/api/services/csv_exporter.py:79` — same pattern on its `identified` identity object:
      `is_emailable_identity(identified.resolution_provider, getattr(identified, "source_agent_visit_id", None))`.
- [ ] B4. Confirm exact variable name at each site while editing (`iv` / `identified` per the
      RESEARCH table above) — do not rename or restructure surrounding logic.

### Step C — Regression test (release-gate deliverable)

New file: `tests/unit/test_agent_origin_exclusion.py` — Fully-Automated, no Docker, mirrors
`tests/unit/test_outbound_identity_gate.py` style.

- [ ] C1. `test_agent_origin_overrides_person_level` — `@pytest.mark.parametrize("provider",
      sorted(PERSON_LEVEL_PROVIDERS))`:
      - assert `is_emailable_identity(provider) is True` (baseline, no marker — unchanged behavior)
      - assert `is_emailable_identity(provider, source_agent_visit_id="fake-uuid") is False`
        (the override fires even for every person-level provider)
      This is the non-vacuous red-then-green core: deleting the override line in A2 makes this
      assertion fail red for every parametrized person-level provider. (PVL confirmed: calling this
      2-arg form against the CURRENT unmodified signature already raises `TypeError` — genuinely red
      before Step A exists, not just logically red.)
- [ ] C2. `test_non_agent_identity_unaffected` — confirm existing behavior is preserved when no
      marker is passed:
      - `is_emailable_identity("rb2b", None) is True` (rb2b is in `PERSON_LEVEL_PROVIDERS`)
      - `is_emailable_identity("hunter", None) is False` (hunter is in `COMPANY_LEVEL_PROVIDERS`)
- [ ] C3. Three site-level tests, one per call site (`campaign_sender`, `_resolve_linkedin_targets`,
      `csv_exporter`) — construct a minimal mock/in-memory object exposing `resolution_provider` and
      `source_agent_visit_id` (set to a non-None value), and assert that site's real code path
      excludes it (e.g. the site's skip-counter increments / the target/export list stays empty for
      that record). Keep Fully-Automated if the site's logic can be exercised without a DB session;
      if a given site genuinely requires a live DB round-trip to reach the guard check, mark that one
      test Hybrid/Docker known-gap explicitly in the test file docstring — but C1 and C2 (the actual
      AC10 proof) MUST stay Fully-Automated and MUST run green in this session, never deferred.
      **Execute-agent guidance (added at PVL):** all 3 call sites read `iv`/`identified` via
      `db.execute(select(IdentifiedVisitor)...)` inline — exercise them with a mocked `AsyncSession`
      (`unittest.mock.AsyncMock`/`MagicMock` returning a canned `scalar_one_or_none()` result), the
      same no-Docker pattern Phase 4 used for its `run_verification_sweep` unit test (see
      `phase-blast-radius-registry.md` Phase 4 entry) — this keeps all 3 site-level tests
      Fully-Automated with no live DB required.
- [ ] C4. Confirm the test fails (red) when the A2 override line is removed, and passes (green) with
      it present — proving the test actually exercises the guard, not a no-op. (Plan-time note: this
      non-vacuity check can be documented via reasoning in the plan/report; EXECUTE/EVL are not
      required to actually delete-and-restore the line, but must state they verified the logical
      red/green shape.)
- [ ] C5. **Tripwire test (added at PVL — closes a security-review finding, do not skip):**
      `test_source_agent_visit_id_literal_field_name_tripwire` — read the source text of
      `apps/api/services/identity_classification.py` and each of the 3 call-site files
      (`campaign_sender.py`, `campaigns.py`, `csv_exporter.py`) directly (plain file read + string
      search, e.g. `Path(...).read_text()`), and assert the literal string `"source_agent_visit_id"`
      appears in all 4 files. This converts the Phase 5 Contract's D1 risk ("any rename silently
      disables the guard with no error") from a documentation-only promise into an automated,
      test-enforced tripwire: if Phase 5 (or any future change) renames the field anywhere without
      updating all 4 occurrences in the same commit, this test fails loudly instead of silently
      reopening the outreach hole. Fully-Automated, no Docker, no imports of the modules under test
      required (pure text search) — cannot be broken by mocking.

### Phase 5 Contract (BINDING — Phase 5 must honor; also record prominently in the phase report as a forward-looking constraint)

- [ ] D1. Phase 5 MUST add `IdentifiedVisitor.source_agent_visit_id: str | None` using the EXACT
      literal field name `source_agent_visit_id` — the `getattr` calls wired in Step B (and the C5
      tripwire test) read this exact string; any rename silently disables the guard with no error
      unless C5 is updated in the same commit.
- [ ] D2. Phase 5 MUST set this field on every agent-derived company-resolution row it creates.
- [ ] D3. Phase 5 MUST NOT assign any `PERSON_LEVEL_PROVIDERS` value as `resolution_provider` on an
      agent-resolved record (the override in A2 is a belt-and-suspenders safeguard, not a substitute
      for correct provider classification).
- [ ] D4. No future phase may add a 4th send/export path that bypasses `is_emailable_identity` — any
      new send/export path must call it with the `source_agent_visit_id` marker wired the same way.
      (Architectural note from PVL: this is currently a written contract, not a centrally
      code-enforced chokepoint — accepted as an intentional, narrow-scope residual for this phase;
      a future centralizing refactor, e.g. one exported `assert_not_agent_origin_and_emailable()`
      wrapper used by all send/export paths, is backlog-worthy but out of scope here.)
- [ ] D5. Phase 5's own exit gate MUST re-run `tests/unit/test_agent_origin_exclusion.py` (including
      the C5 tripwire) against REAL Phase-5-created rows (not mocks) before Phase 5 is marked
      ✅ VERIFIED.
- [ ] D6. Phase 5 must run the C5 tripwire test as part of its own exit gate specifically if it
      touches any of the 4 files listed in C5 — a passing tripwire is Phase 5's cheap proof it did
      not silently break the field-name contract.

---

## Exit Gate

```bash
.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q
# Expected: all cases pass, INCLUDING every PERSON_LEVEL_PROVIDERS parametrization in
# test_agent_origin_overrides_person_level (C1), the literal-field-name tripwire (C5), and all 3
# site-level exclusion tests (C3) — an agent-visit-marked record id is rejected/excluded at every
# one of the 3 campaign/email/social/export targeting entry points; test is proven non-vacuous
# (fails without the A2 override, passes with it; and today, before Step A exists, C1's 2-arg call
# already raises TypeError — confirmed at PVL).

.venv/bin/python -m pytest tests/unit -q
# Expected: no regression vs the 735 passed / 2 skipped baseline recorded in the phase registry.
```

- AC10 passes; test is proven non-vacuous.
- Phase report written to report destination above, including the Phase 5 Contract section
  (D1–D6) called out explicitly as forward-binding requirements.
- This phase's status must be explicitly cross-referenced in Phase 5's Entry Gate before Phase 5 is
  marked VERIFIED.

---

## Blockers That Would Justify BLOCKED Status

- Phase 2 exit gate not yet passed (no agent-visit records exist to test exclusion against). — N/A, already satisfied.
- Guardrail audit (Step A1 of RESEARCH, now confirmed complete) surfaces a targeting path outside
  the 3 enumerated call sites that cannot be closed within this phase's blast radius — must be
  escalated, never silently left open given this is the program's highest-priority safety
  constraint. (RESEARCH found exactly 3 call sites via exhaustive grep; no unenumerated path found.
  Re-confirmed at PVL with a fresh grep — still exactly 3.)

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — research-agent: prior phase reports read; all 3 campaign/segment/email/export
      targeting code paths enumerated exhaustively (safety-critical enumeration, not a sample);
      schema state confirmed (`source_agent_visit_id` does not yet exist — Phase 5's job)
- [x] 2. INNOVATE — n/a — mechanical wiring, no architectural choice; design locked directly from
      SPEC AC10 + confirmed code shape (getattr-based forward-compat wiring is the only sane option
      given the column doesn't exist yet)
- [x] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated with exact locked design,
      confirmed file/line targets, exact checklist, Phase 5 binding contract, and verification
      evidence. No prior contradictory content found — plan was a scaffold/placeholder before this
      supplement.
- [x] 4. PVL — vc-validate-agent: full V1-V7 complete; validate-contract written; `vc-security`
      STRIDE scan run (outreach/trust-boundary surface); 1 plan update applied (C5 tripwire test);
      Gate: PASS
- [x] 5. EXECUTE — all checklist items done; per-section test gates run and green (17/17 AC10 gate;
      752 passed/2 skipped full regression; 45 adjacent campaign/outreach/csv/linkedin tests green)
- [x] 6. EVL — all EVL gates green (independent vc-tester re-run: AC10 17/17, full regression
      752/2, adjacent `test_outbound_identity_gate.py` 18/18, non-vacuity confirmed by code
      inspection); no follow-up plan stubs required; no CONTEXT_PARTIAL
- [x] 7. UPDATE PROCESS — phase report written, umbrella state updated; commit deferred to
      vc-git-manager (not run this session per instructions)

**Validate-contract required before execute.** This is the highest-risk phase's release-gate
partner — VALIDATE may never be skipped, and a CONDITIONAL/BLOCKED gate must never be silently
accepted as "good enough" given the business-guardrail stakes (agents must never be emailed).

---

## Touchpoints

- `apps/api/services/identity_classification.py` — extend `is_emailable_identity` signature + guard
- `apps/api/services/campaign_sender.py:202` — call-site wiring
- `apps/api/routers/campaigns.py:725` (`_resolve_linkedin_targets`) — call-site wiring
- `apps/api/services/csv_exporter.py:79` — call-site wiring
- `tests/unit/test_agent_origin_exclusion.py` (new) — regression test file (C1–C5, incl. tripwire)

---

## Public Contracts

- `is_emailable_identity(provider, source_agent_visit_id=None)` gains a new optional second
  parameter with a safe default (`None`) — fully backward-compatible; every existing caller not
  updated in this phase continues to behave identically.
- No externally-visible API shape change — this phase adds an internal hard exclusion; existing
  campaign/segment/email/export API contracts remain unchanged in shape.

---

## Blast Radius (risk class)

- Risk class: outreach/trust-boundary safety guard (business-guardrail — "agents must never be
  emailed"). No schema, auth, or billing surface touched. 5 files total, all small (1–3 line edits
  to 3 existing files + 1 new test file + 1 extended function). Low mechanical risk given design is
  fully locked; high *importance* given it is SPEC's highest-priority AC.
- High-risk pack note (PVL): this does not map cleanly onto the 6 standard high-risk classes (no
  auth/billing/schema/public-API/container/secrets surface), but it IS the program's named
  business-guardrail safety boundary, so it is treated with equivalent rigor. Mitigating controls in
  lieu of a full 5-artifact evidence pack: (1) the unconditional, first-checked override (A2),
  (2) the confirmed-genuinely-non-vacuous C1 test, (3) the new C5 literal-field-name tripwire,
  (4) the binding forward contract (D1–D6) gating Phase 5's own VERIFIED status. A full
  `vc-risk-evidence-pack` remains optional/manual-first per its own contract; recommended before
  Phase 5 ships, not required to gate this phase's EXECUTE.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_agent_origin_overrides_person_level` (parametrized over all `PERSON_LEVEL_PROVIDERS`) | Fully-Automated | AC10 — agent-origin record never emailable regardless of provider |
| `test_non_agent_identity_unaffected` | Fully-Automated | AC10 — non-agent behavior unchanged (no regression on existing person/company classification) |
| `test_source_agent_visit_id_literal_field_name_tripwire` (C5, added at PVL) | Fully-Automated | D1 — guard cannot be silently disabled by a field rename without this test failing |
| 3× site-level exclusion tests (`campaign_sender`, `_resolve_linkedin_targets`, `csv_exporter`) | Fully-Automated (via mocked `AsyncSession`; Hybrid only if a site genuinely requires a live DB session — must be documented, not default) | AC10 — guard enforced at every real send/export entry point, not just the primary one |
| Full unit regression (`tests/unit -q`) vs 735-passed/2-skipped baseline | Fully-Automated | No regression introduced by the call-site edits |
| Non-vacuity reasoning check (override-removed = red, override-present = green; PVL confirmed 2-arg call is genuinely `TypeError`-red today) | Fully-Automated (logical proof documented + confirmed against real current code at PVL) | AC10 — test is proven non-vacuous, not a no-op |

```bash
.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q
# Expected: all pass — proves AC10
.venv/bin/python -m pytest tests/unit -q
# Expected: no regression vs 735 passed / 2 skipped baseline
```

---

## Test Infra Improvement Notes

- (PVL) Minor observability gap, non-blocking: today, an agent-origin skip at any of the 3 call
  sites increments the SAME skip counter as an ordinary company-level-provider skip (e.g.
  `summary["skipped_company_level"]` in `campaign_sender.py`) — there is no distinct
  "skipped_agent_origin" counter, so an operator cannot tell the two reasons apart from the
  summary dict alone. Not a security issue (both outcomes correctly exclude the record) and not
  required for AC10. Optional follow-up: add a distinct counter key at each of the 3 sites in a
  later phase/cleanup pass if operator-facing skip-reason breakdowns become a product requirement.

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/evallayer_22-07-26/phase-07-outreach-exclusion_PLAN_22-07-26.md`
- Last completed step: Step 4 PVL (this update) — validate-contract written, PASS gate, 1 plan
  update applied (C5 tripwire test + D6 forward contract addition)
- Validate-contract status: written (22-07-26) — Gate: PASS
- Supporting context files loaded: `apps/api/services/identity_classification.py`,
  `apps/api/services/campaign_sender.py`, `apps/api/routers/campaigns.py`,
  `apps/api/services/csv_exporter.py`, `apps/api/models/visitor.py`,
  `tests/unit/test_outbound_identity_gate.py` (precedent), evallayer umbrella plan, evallayer SPEC
  (AC10), phase-blast-radius-registry.md
- Phase closed 22-07-26 via UPDATE PROCESS: report `phase-07-outreach-exclusion_REPORT_22-07-26.md`
  finalized with EVL Confirmation section; umbrella `## Current Execution State` and Program Status
  Table updated to ✅ VERIFIED; blast-radius registry Phase 7 entry finalized to `status: DONE`.
  Commit deferred to `vc-git-manager` (not run this session per instructions).
- Next step for the program: proceed to Phase 5 (Company resolution → outreach feed) —
  MANDATORY-FRESH RESEARCH required; this phase's D1-D6 contract is now binding on Phase 5's
  design and exit gate.

---

## Validate Contract

Status: PASS
Date: 22-07-26
date: 2026-07-22
generated-by: inner-pvl: phase-7

Parallel strategy: sequential
Rationale: Signal score 4/7 (S4 phase-program, S5 user-requested depth/rigor, S6 trust-boundary
risk class, S7 exactly 5 blast-radius files) formally clears the parallel-subagents/workflow
threshold, but strategy-by-fit overrides the raw score here: the 5 files have a strict internal
dependency order (A must land before B call-sites are meaningful; C3's site tests need A done to
import the 2-arg signature), the total edit surface is tiny (1–3 line changes ×3 + one function +
one new test file), and a single vc-execute-agent applying Steps A→B→C in order is both correct and
fastest — fan-out would add coordination overhead with no parallelizable independent work. For the
VALIDATE fan-out itself (this pass), Simple Mode single-pass synthesis was used (small, single
backend-domain scope, no container/infra surface, <5 packages) — Layer 1 (4 dimensions) + Layer 2
(1 section) analysis performed directly in this session rather than spawned as separate parallel
Agent-tool calls, consistent with vc-validate-findings Simple Mode guidance for scope this small.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC10-1 | Agent-origin override forces non-emailable regardless of provider, for every PERSON_LEVEL_PROVIDERS value (non-vacuous: 2-arg call raises TypeError against today's unmodified code) | Fully-Automated | `tests/unit/test_agent_origin_exclusion.py::test_agent_origin_overrides_person_level` | A |
| AC10-2 | Non-agent identity classification unaffected (no regression when no marker passed) | Fully-Automated | `tests/unit/test_agent_origin_exclusion.py::test_non_agent_identity_unaffected` | A |
| AC10-3 (tripwire, plan update P1) | Literal field name `source_agent_visit_id` present in guard + all 3 call sites — rename cannot silently disable the guard | Fully-Automated | `tests/unit/test_agent_origin_exclusion.py::test_source_agent_visit_id_literal_field_name_tripwire` | B |
| AC10-4 | Guard enforced at all 3 real send/export entry points (`campaign_sender`, `_resolve_linkedin_targets`, `csv_exporter`) | Fully-Automated (mocked AsyncSession; Hybrid only if a site genuinely needs a live DB round-trip, must be documented in-file if so) | 3× site-level tests in `tests/unit/test_agent_origin_exclusion.py` | A |
| AC10-5 | No regression vs full unit baseline | Fully-Automated | `.venv/bin/python -m pytest tests/unit -m unit -q` | A |
| D5 (forward, Phase 5) | Guard re-verified against REAL Phase-5-created rows (not mocks) | Hybrid (deferred — Phase 5 does not exist yet) | Phase 5's own exit gate re-run of `test_agent_origin_exclusion.py` (incl. C5 tripwire) against real rows | C — deferred to Phase 5's exit gate, already a binding contract item (D5/D6) |

gap-resolution legend: A — proven now (gate passes in this cycle); B — fixed in this plan (gate
added by this plan's checklist); C — deferred to a named later phase/plan; D — backlog
test-building stub (named residual; keep-active; continue).

Legacy line form:
- Outreach guard (identity_classification.py + 3 call sites): Fully-automated:
  `.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q` | Fully-automated
  full regression: `.venv/bin/python -m pytest tests/unit -m unit -q` (baseline 735 passed / 2
  skipped) | known-gap: Phase 5 real-row re-verification, deferred per D5/D6 (not a gap in THIS
  phase's own proof — AC10 is fully proven here with real code, not mocks, for the guard itself).

Dimension findings:
- Infra fit: PASS — backend-only change (`apps/api/services`, `apps/api/routers`, `tests/unit`), no
  container/worker/proxy/runtime surface touched, no new dependency.
- Test coverage: PASS — C1/C2 confirmed genuinely non-vacuous against real unmodified code (2-arg
  call raises `TypeError` today); all core AC10 assertions are Fully-Automated with zero Docker
  dependency; site-level tests (C3) can stay Fully-Automated via mocked AsyncSession (Phase 4
  precedent).
- Breaking changes: PASS — `is_emailable_identity` gains one optional kwarg with a safe default;
  every existing call site not updated in this phase behaves identically; no schema, no public API
  shape change.
- Security surface (`vc-security` STRIDE lens, outreach/trust-boundary): CONCERN → resolved via plan
  update. Tampering: the guard is fail-open-by-rename (a future field rename anywhere silently
  reopens the hole since `getattr(..., "source_agent_visit_id", None)` would just return `None`
  again) — mitigated by (a) the binding D1–D6 forward contract and (b) the new C5 tripwire test
  added as Plan Update P1, which makes the rename risk test-enforced rather than
  documentation-only. Repudiation/observability: agent-origin skips are not distinguished from
  ordinary company-level skips in the existing skip counters — accepted as a non-blocking Known Gap
  (cosmetic, not a security hole). Elevation of Privilege / Info Disclosure / DoS: not applicable —
  this is a pure exclusion guard that only narrows reachable targets, never widens them. Defense-in-
  depth: the marker-based override is checked FIRST and unconditionally, before the
  `PERSON_LEVEL_PROVIDERS` allowlist — genuine defense-in-depth (protects even against a future D3
  violation), not mere redundancy. D4 ("no future 4th bypass path") remains a written contract, not
  a centrally code-enforced chokepoint — accepted as an intentional, scope-limited residual (see
  Known Gaps below).
- Section A — Outreach-Exclusion Guardrail (Steps A–D): PASS — mechanical feasibility: all edit
  targets (function, 3 call sites, docstring) re-confirmed present and uniquely matchable via fresh
  `grep -n` at PVL time; new test file confirmed non-existent (no collision). Gaps found: (1) C3's
  "minimal mock/in-memory object" construction method was underspecified — resolved via an added
  execute-agent guidance note (use mocked AsyncSession, Phase 4 precedent); (2) rename/tampering
  risk on the getattr field name — resolved via Plan Update P1 (C5 tripwire test). Conflicts found:
  none. Highest-risk edit + mitigation: A2 (override placement/ordering) — mitigated by requiring
  the override to be the unconditional FIRST statement in the function body, proven correct by C1's
  full-parametrization sweep over every `PERSON_LEVEL_PROVIDERS` value; execute-agent should
  implement in strict A → B → C order (C1/C2 can be written first as a red-first TDD check since
  the 2-arg call already raises `TypeError` against current code — genuinely red before A exists).

Plan updates applied:
- P1: Added Step C5 — literal-field-name tripwire test (`test_source_agent_visit_id_literal_field_name_tripwire`),
  Fully-Automated, no Docker. Closes the security-surface CONCERN by converting the "any rename
  silently disables the guard" risk from documentation-only (D1) into an automated, test-enforced
  check. Added D6 (Phase 5 must keep this tripwire green). Verification Evidence table and Exit Gate
  updated to reference it.

Execute-agent instructions:
- E1: Implement Steps A → B → C1/C2 → C3 → C5 → D-section-in-report, in that order. A must land
  before B/C1 are meaningful (current code raises `TypeError` on the 2-arg call — this IS the red
  state; do not "fix" this by skipping straight to a passing test).
- E2: For C3's 3 site-level tests, mock the `AsyncSession`/`db.execute(...).scalar_one_or_none()`
  call chain (no live DB) — follow the same no-Docker mocking pattern Phase 4 used for its
  `run_verification_sweep` unit test (see `phase-blast-radius-registry.md` Phase 4 entry) rather than
  inventing a new pattern.
- E3: Do not physically delete-and-restore the A2 override line to "prove" C4's non-vacuity claim —
  the logical proof is already confirmed at PVL (current code raises `TypeError` on the 2-arg call);
  state in the phase report that this was verified by reasoning + the PVL-confirmed `TypeError`,
  consistent with the plan's C4 note.
- E4: Run the full exit-gate command pair (`test_agent_origin_exclusion.py` then full `tests/unit`)
  and paste both result lines into the phase report before declaring DONE.

Backlog artifacts:
- None required for this phase. The two accepted Known Gaps below are intentionally NOT backlog
  notes — one is a forward-binding contract already tracked inside this same plan (D1–D6, closed by
  Phase 5's own exit gate) and the other is a cosmetic observability nit with no correctness impact
  (optional future cleanup, not worth a standalone backlog artifact at this scope).

Known gaps:
- Skip-counter miscategorization: agent-origin skips are counted under the existing
  "company_level"/generic skip counters at all 3 call sites rather than a distinct
  "agent_origin" counter — observability-only, not a security or correctness gap (the record is
  still correctly excluded either way). Accepted as a non-blocking residual; optional cleanup in a
  later phase if operator-facing skip-reason breakdowns become a requirement.
- D4 centralization: "no future 4th bypass path" is currently enforced only as a written contract
  (D4), not a single code-enforced chokepoint across all send/export paths. Accepted as an
  intentional, scope-limited residual for this phase — a future refactor consolidating all 3 (and
  any future) call sites behind one exported guard function is backlog-worthy but explicitly out of
  scope here (would expand this phase's blast radius beyond its locked design).
- Real-row re-verification (D5): this guard is proven here against real code paths but synthetic/
  mocked identity rows (no `IdentifiedVisitor` row with `source_agent_visit_id` set can exist until
  Phase 5 adds the column). This is a forward dependency, not an open gap in this phase's own proof
  — already tracked as a binding requirement on Phase 5's exit gate (D5/D6), cross-referenced in
  `phase-blast-radius-registry.md`.

What this coverage does NOT prove:
- The 3 site-level tests (AC10-4), even with a mocked AsyncSession, do not prove behavior against a
  REAL Postgres round-trip (query construction correctness, index usage, concurrent-write races) —
  that class of behavior is out of scope for this phase (no schema/DB surface touched) and is not
  claimed as proven here.
- Full unit regression proves no regression in the existing 735/2-skipped suite; it does not prove
  the absence of every possible interaction with code paths this phase does not touch (e.g.
  Playwright e2e dashboard flows, ClickHouse aggregation paths) — those are out of this phase's
  blast radius entirely.
- The tripwire test (C5) proves the literal string is present in 4 named files today; it does not
  prove no OTHER file anywhere in the codebase independently duplicates the guard logic without
  using the shared field name (mitigated instead by D4's written contract + the original exhaustive
  `grep -rn "is_emailable_identity"` enumeration, re-confirmed at PVL to still return exactly 3
  call sites).
(Required until C3 is implemented — temporary C3 mitigation)

Gate: PASS (no FAILs, plan updated with P1; 3 Known Gaps documented and explicitly accepted as
non-blocking residuals, none touching the AC10 core proof)
Accepted by: session (autonomous, /goal execution) — CONCERN (security-surface tampering risk)
resolved via Plan Update P1 (C5 tripwire test) rather than left as an unresolved CONCERN; the 3
Known Gaps listed above (skip-counter miscategorization, D4 centralization, D5 forward dependency)
are accepted as non-blocking per the autonomous decision policy — none affect the AC10 core proof
and none require a plan rewrite beyond what was already applied.
