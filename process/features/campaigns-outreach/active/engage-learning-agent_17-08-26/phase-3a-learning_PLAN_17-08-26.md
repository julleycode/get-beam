---
name: plan:engage-learning-agent-phase-3a-learning
description: "Engage Learning Agent — Phase 3a: outcome-driven strategy selection plus the pure autonomy-gate function (no schema, no migration, no send path, no web file)"
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: memory
  type: plan
  feature: campaigns-outreach
  phase: phase-3a
---

# Phase 3a — Learning (pure functions only)

**Date**: 17-08-26
**Complexity**: COMPLEX
**Status**: ⏳ PLANNED
**Program:** engage-learning-agent
**Umbrella plan:** `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/engage-learning-agent-umbrella_PLAN_17-08-26.md`
**Report destination:** `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-3a-learning_REPORT_17-08-26.md`
**Covers SPEC ACs:** AC-13
**Origin:** split out of the former Phase 3 on 17-08-26 (PVL cycle 4). Steps A + B produced **zero validator findings across three PVL cycles** and were carried over **with three additive amendments plus cross-reference corrections** — not verbatim (see the Refresh Note for the exact list).

**TL;DR:** Build the two pure functions the program's learning depends on — the outcome-driven strategy selector and the evidence-anchored autonomy gate — behind one flag, touching no schema, no migration, no send path, and no web file. Nothing in production calls the gate until Phase 3b.

---

## Inner Loop Refresh Note

**17-08-26 — PVL cycle 4 / program restructure (split creation).** This plan is NEW, created by
splitting the former `phase-3-learning-autonomy_PLAN_17-08-26.md` into 3a (this file) and 3b. The
split-revisit signal encoded in the umbrella at cycle 2 TRIGGERED: the cycle-3 validator confirmed
two consecutive cycles of fix-introduced FAILs, **all of them in Steps C–G**, while Steps A and B
drew zero findings in three cycles. Steps A and B are carried over faithfully here — deliberately
NOT rewritten, because rewriting working text is how the last two cycles manufactured new defects.
**(cycle-4 3a-C2) "Carried over verbatim" was overstated — here is the exact deviation list.** Steps A
and B were carried over with **three additive amendments plus cross-reference corrections**:

*Additive amendments:* (1) the Q6 slug-join rule; (2) the Entry Gate rebased onto Phase 1 only; (3) A8 —
an explicit statement, plus a gate, that `autonomy_gate()` ships unreachable.

*Cross-reference corrections (A2, A4, A5, A6, A7 all touched; A5 substantively rewritten):* A5's
`contact_bidx` attribution now points at **Phase 2 item A2b** rather than the stale "Phase 1 A2 adds it",
matching Phase 1's N5/N6 deferral; A2 now says the four values flow into the audit row **3b** writes;
A4/A6/A7 carry phase-label and gate-location corrections. Every deviation was verified correct by the
cycle-4 validator.

**Why this matters:** the Refresh Note leans on "we did not rewrite it" as the argument for skipping
re-derivation. That argument is only honest if the deviations are enumerated — so they are.

*Cycle-5 amendment (FAIL 3a-1 / 3a-C1):* the two threshold config keys moved OUT of 3a into 3b, and
`autonomy_gate()` now takes them as explicit function arguments. 3a reads no config at all.

---

## Overview / Context and Goals

The former Phase 3 bundled two very different kinds of work: pure decision functions (no side
effects, no schema) and the entire outward-facing autonomy surface (enum widening, a send driver,
six safety rails, a first-of-kind `ALTER TYPE`, five doc surfaces, five web files). Three PVL cycles
showed the risk was concentrated entirely in the second group.

Phase 3a is the first group. It delivers:

- `select_strategy_from_outcomes(stats)` — a deterministic, seedable selector that shifts the reply
  approach toward whatever measurably worked for this site.
- `autonomy_gate(stats, min_outcomes, min_positive_rate)` — the pure, evidence-anchored decision
  function whose signature structurally excludes model output. Thresholds arrive as explicit
  arguments; this module reads no config at all (Phase 3b owns the config keys and passes them in).

**Both ship inert.** `select_strategy_from_outcomes` is consulted only when
`engage_outcome_learning_enabled` is ON (default OFF). `autonomy_gate()` has **no production
caller at all in this phase** — the driver that calls it is Phase 3b. That is deliberate: it lets
the gate's purity be proven, and lets real outcome history accumulate, before any autonomy surface
exists to consume it.

Context loaded: `process/context/all-context.md` (§Business Guardrails, §Key Patterns) and
`process/context/tests/all-tests.md` (runner selection, port detection).

### Goals

1. Outcome-driven approach selection, additive to `voice_examples` (AC-13).
2. The pure autonomy-gate function, proven pure and unspoofable at the function boundary.

### Non-goals

The `DraftStatus` enum value, the autonomous-send driver, any of the six rails, the prompt-safety
fence, the guardrail-text amendment, and every web surface. All of those are Phase 3b. **No schema
change, no migration, no `sender.py` edit, no `apps/web` edit occurs in this phase.**

### Binding join rule inherited from Phase 1 (Q6)

`Draft.site_id` is `String(50)` referencing `sites.site_id` — the **slug**, not the UUID PK. Every
aggregate this phase reads (`engage_outcomes.site_id` via Phase 2's `compute_track_record`) carries
that same slug and joins to `sites.site_id` directly, never to `sites.id`.

---

## Entry Gate

**Mechanical, not prose.** Phase 1's deliverable must import:

```bash
.venv/bin/python3.11 -c "from apps.api.models.engage_outcome import EngageOutcome; print(EngageOutcome.__table__.c.keys())"
```

- Phase 1 exit gate met; the command above exits 0 and lists `site_id` and `platform_ref`.
  **`contact_bidx` is absent by design at this point** — Phase 2 adds it (Phase 2 item A2b) together
  with its erasure registration. Do not treat its absence as a Phase 1 failure.
- Phase 2 is NOT required to start 3a. 3a reads only `engage_outcomes` shape and writes pure
  functions; its DISTINCT-contact leg is gated behind the Phase-2 dependency noted in A5.

---

## Touchpoints

**Owned exclusively by Phase 3a:**

- `apps/api/services/engage_autonomy.py` — NEW, pure `autonomy_gate()`. No production caller in this
  phase.
- `apps/api/services/ai_reply.py` — adds `select_strategy_from_outcomes` and the
  `determine_draft_mode` consult. Does NOT touch `_sanitize_content` (Phase 3b owns AC-19).
- `tests/unit/test_engage_autonomy.py` — NEW (the purity + gate-arithmetic gates).
- `tests/unit/test_engage_strategy_selection.py` — NEW (AC-13).

**Shared, with binding rules:**

- `apps/api/config.py` — appends the `# ─── Engage learning (Phase 3a) ───` block only. **Exactly ONE
  key: `engage_outcome_learning_enabled`.** Every `engage_autonomy_*` key — both kill switches, the
  ceiling, the dwell floor, AND the two gate thresholds — belongs to Phase 3b's block (cycle-4 3a-C1).

**Explicitly NOT touched:** `models/draft.py`, `models/site.py`, `services/sender.py`,
`routers/drafts.py`, `jobs/scheduler.py`, any migration, any file under `apps/web/`, and any
context/doc surface.

---

## Public Contracts

- `services/ai_reply.determine_draft_mode` — behavior UNCHANGED while
  `engage_outcome_learning_enabled` is False (the default). When ON, it prefers the outcome-derived
  strategy and otherwise falls through to the existing `_get_preferred_strategy` unchanged.
- `voice_examples` — NOT rebuilt. The existing explore→exploit loop and its human
  approve/edit/reject signal keep working exactly as today; regression-gated.
- `services/engage_autonomy.autonomy_gate(stats, min_outcomes: int, min_positive_rate: float) -> AutonomyDecision`
  — NEW public function. **Thresholds are explicit arguments; the module reads no config** (the caller
  supplies them). It is **not wired to anything** in this phase; Phase 3b's driver is its first caller.
- No schema, no API route, no enum, no migration, and no web type changes in this phase.

---

## Blast Radius

- **NEW (3):** `services/engage_autonomy.py`, 2 test files.
- **EDITED (2):** `services/ai_reply.py`, `apps/api/config.py`.
- 0 new tables, 0 migrations, 0 enum changes, 0 web files, 0 doc surfaces.
- Risk class: **LOW for the program** — no schema, no migration, no outward-facing surface, no public
  contract widening. The only behavior change is flag-gated strategy preference inside drafting.
  This is precisely why the split was approved: the highest-risk work is now isolated in Phase 3b.

---

## Implementation Checklist

### Step A — The pure autonomy gate (function only; AC-11/AC-12 are PROVEN in Phase 3b)

*(Carried over from the former Phase 3 Step A — zero validator findings in 3 cycles. NOT verbatim: A2/A4/A5/A6/A7 carry cross-reference corrections, A5 substantively so, plus the cycle-5 threshold-argument change to A1/A3. Full deviation list in the Inner Loop Refresh Note.)*

- [ ] A1. Create `apps/api/services/engage_autonomy.py` with
  `autonomy_gate(stats, min_outcomes: int, min_positive_rate: float) -> AutonomyDecision`.
  **(cycle-4 3a-C1/FAIL 3a-1) The thresholds are EXPLICIT FUNCTION ARGUMENTS — 3a reads no config at
  all.** Inputs are ONLY the outcome-history aggregate and the two numeric thresholds. **No model
  output, no confidence field, no draft object, and no `settings` import may appear in the signature or
  the module.** The caller (3b's driver) supplies the thresholds from its own config block.
- [ ] A2. Return `{allowed: bool, reason: str, sample_n: int, positive_rate: float}` — these four values
  flow VERBATIM into the audit row that Phase 3b writes.
- [ ] A3. **(cycle-4 3a-C1 + FAIL 3a-1) NO config keys in this phase.** The two tuning values
  (`engage_autonomy_min_outcomes` default 20, `engage_autonomy_min_positive_rate` default 0.4) live in
  **Phase 3b's** config block, with the gate's first caller — alongside the two kill-switch flags and the
  ceiling. Two reasons: (i) a threshold with no caller is dead config; (ii) putting `engage_autonomy_*`
  keys in `config.py` made 3a's own inertness gate (G24) impossible to pass, because the substring
  matched them. 3a's config block therefore carries exactly ONE key,
  `engage_outcome_learning_enabled` (item B5). Document the defaults here as the values 3b must use,
  and mark them placeholder-conservative, tune-from-observed.
- [ ] A4. Positive outcome = `reply_received` OR `attributed_visit`. Likes alone never unlock autonomy.
  **Import the definition from Phase 2's `engage_track_record`** — do not redefine it.
  `playbook == Draft.strategy`, pinned here; gate keying is **playbook × site only**
  (segment dropped per D-O8).
- [ ] A5. Positive-rate uses DISTINCT-CONTACT counting over `engage_outcomes.contact_bidx`.
  **Dependency note (N5/N6):** `contact_bidx` is added by **Phase 2** (item A2b), not Phase 1 — the
  blind-index helper and the erasure registration land together there. If 3a executes before Phase 2,
  implement the DISTINCT-contact path against the column contract and gate it as a Phase-2-dependent
  leg; do not invent a substitute key.
- [ ] A6. Zero history → `allowed=False, reason="insufficient_history"` (the AC-12 cold-start guarantee
  that Phase 3b proves end-to-end).
- [ ] A7. Structural purity: the module imports no model, no session, and no mutable global config
  (roster-ranking AST-purity precedent). Asserted by an explicit test in Step G (G17), not merely
  declared here.
- [ ] A8. **(Split addition)** Assert the gate ships UNREACHABLE: no module under `apps/api` imports
  `engage_autonomy` in this phase. Gate it (G24). Phase 3b's driver is the first and only caller.

### Step B — Outcome-driven strategy selection (AC-13)

*(Carried over verbatim from the former Phase 3 Step B — zero validator findings in 3 cycles; no deviations.)*

- [ ] B1. Add pure `select_strategy_from_outcomes(stats) -> str | None` in `services/ai_reply.py`.
  Deterministic and seedable.
- [ ] B2. Consult it from `determine_draft_mode` ONLY when `engage_outcome_learning_enabled` is ON;
  otherwise fall through to the existing `_get_preferred_strategy` unchanged.
- [ ] B3. The outcome signal outranks the human approve/edit/reject signal once the outcome sample clears
  a small floor; below that floor the approval signal still wins.
- [ ] B4. `voice_examples` is NOT rebuilt; existing explore→exploit behavior is regression-gated.
- [ ] B5. Config: `engage_outcome_learning_enabled: bool = False`.

### Step G — Tests

- [ ] G1. `tests/unit/test_engage_autonomy.py::test_autonomy_gate_pure_function_of_outcome_history`
  — exhaustive: below-N, at-N-below-R, at-N-at-R. (Proves the FUNCTION; AC-11's end-to-end falsifier
  runs in Phase 3b through the driver.)
- [ ] G4. `tests/unit/test_engage_strategy_selection.py::test_approach_selection_shifts_with_outcome_history`
  (AC-13) — deterministic seed; assert the selection distribution moves toward the winner.
- [ ] G4b. `…::test_selection_unchanged_when_learning_flag_off` — flag-OFF control; existing
  `_get_preferred_strategy` behavior is byte-identical.
- [ ] G4c. `…::test_approval_signal_wins_below_outcome_floor` (B3 boundary).
- [ ] G17. `…::test_autonomy_gate_module_is_pure` — AST/import assertion that `engage_autonomy.py`
  imports no model, session, or mutable global config.
- [ ] G24. **(Split addition; rewritten per cycle-4 FAIL 3a-1)**
  `tests/unit/test_engage_autonomy.py::test_autonomy_gate_has_no_production_caller` — **the pytest test
  is the authoritative gate**; it asserts on the IMPORT, not on the substring. The old substring form
  (`grep -rn "engage_autonomy" apps/api`) was guaranteed to go RED on a correct implementation, because
  it also matched the `engage_autonomy_min_*` config keys — a gate that fails on correct work burns an
  EVL cycle editing the gate instead of the code. (A3 has now moved those keys to 3b, so the collision
  is doubly closed.) The test walks `apps/api/**/*.py` and asserts no module contains
  `from apps.api.services.engage_autonomy` or `import engage_autonomy`, excluding the module itself and
  `tests/`. The shell form below is an advisory cross-check only, never the gate:
  `grep -rn "from apps.api.services.engage_autonomy\|import engage_autonomy" apps/api --include="*.py"`
  → expect no match.
- [ ] G25. Flag-ON leg (MANDATORY): run G4 and G4c with `ENGAGE_OUTCOME_LEARNING_ENABLED=true`.
  Flag-OFF-only evidence is vacuous — this repo has shipped two silent no-ops behind exactly that.
- [ ] G16. Regression: full unit lane green; `voice_examples` behavior unchanged;
  `is_emailable_identity` unchanged.

---

## Acceptance Criteria

| AC | Criterion | proven by | strategy |
|---|---|---|---|
| AC-13 | Measured outcomes change future behavior | `test_approach_selection_shifts_with_outcome_history` + `test_approval_signal_wins_below_outcome_floor` (G4, G4c, flag-ON via G25) | Fully-Automated |

**Deliberately NOT claimed here:** AC-11 (confidence is observed history) and AC-12 (cold start is
always human-approved) are BUILT here (Step A) but **PROVEN in Phase 3b**, because their falsifiers
require an end-to-end path — a fabricated model confidence must be shown not to authorize a real
send, and that send path does not exist until 3b. Asserting them on the bare function would be a
vacuous gate of exactly the class this program's charter bans.

---

## Phase Completion Rules

- 🔨 **CODE DONE** — checklist applied, gates unrun.
- 🧪 **TESTING** — gates running; any red gate keeps the phase here.
- ✅ **VERIFIED** — AC-13 green INCLUDING the flag-ON leg (G25), the purity gate (G17) and the
  no-caller gate (G24) green, unit-lane regression green, validate-contract recorded, and the user
  confirmed. Code-only completion is never VERIFIED.
- 🚧 **BLOCKED** — see blockers below.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_approach_selection_shifts_with_outcome_history` (flag-ON) | Fully-Automated | AC-13 |
| `test_approval_signal_wins_below_outcome_floor` | Fully-Automated | AC-13 boundary |
| `test_selection_unchanged_when_learning_flag_off` | Fully-Automated | AC-13 flag-OFF control |
| `test_autonomy_gate_pure_function_of_outcome_history` | Fully-Automated | AC-11 groundwork (AC-11 itself is proven in 3b) |
| `test_autonomy_gate_module_is_pure` (AST) | Fully-Automated | Gate purity invariant |
| `test_autonomy_gate_has_no_production_caller` (pytest is authoritative; import-based, not substring) | Fully-Automated | 3a inertness (no autonomy surface ships here) |
| Unit-lane regression incl. `voice_examples` | Fully-Automated | No behavior regression |

### Test Procedure / Post-Phase Testing

```bash
# Entry gate (Phase 1 landed?) — contact_bidx is expected ABSENT here (Phase 2 adds it)
.venv/bin/python3.11 -c "from apps.api.models.engage_outcome import EngageOutcome; print(EngageOutcome.__table__.c.keys())"

.venv/bin/python3.11 -m pytest tests/unit/test_engage_autonomy.py tests/unit/test_engage_strategy_selection.py -m unit -q
# Expected: 0 failed

# Flag-ON leg (MANDATORY)
ENGAGE_OUTCOME_LEARNING_ENABLED=true \
  .venv/bin/python3.11 -m pytest tests/unit/test_engage_strategy_selection.py -m unit -q
# Expected: 0 failed, and the selection distribution actually shifts

# Inertness gate — the pytest test above is authoritative. This grep is an advisory cross-check.
grep -rn "from apps.api.services.engage_autonomy\|import engage_autonomy" apps/api --include="*.py"
# Expected: no match (3a ships the gate function with no production caller)

.venv/bin/python3.11 -m pytest tests/unit -m unit -q
# Expected: 0 failed
```

Note: this phase needs no integration lane and no container — it writes no schema and no migration.
Ports 5433/6379 are irrelevant here.

---

## Test Infra Improvement Notes

- The DISTINCT-contact leg (A5) cannot be fully exercised until Phase 2 lands `contact_bidx`; write
  it against the column contract and mark the leg Phase-2-dependent rather than substituting a key.
- No new fixture infrastructure is required — this phase is unit-lane only.

---

## Blockers That Would Justify BLOCKED Status

- `compute_track_record` (Phase 2) cannot be imported for the positive-outcome definition AND no
  stable contract for it exists — A4 forbids redefining it locally.
- `determine_draft_mode` cannot consult the new selector without restructuring `ai_reply.py`'s
  existing `voice_examples` loop (that would break B4's regression guarantee).

---

## Phase Loop Progress

- [ ] 1. RESEARCH — Phase 1 report read; plan drift checked
- [ ] 2. INNOVATE — approach confirmed against locked D7 + the split rationale; Decision Summary written
- [x] 3. PLAN-SUPPLEMENT — created 17-08-26 by the PVL cycle-4 split; Steps A+B carried over faithfully; Inner Loop Refresh Note written
- [ ] 4. PVL — vc-validate-agent: full V1–V7 (this plan has never been validated as a standalone artifact)
- [ ] 5. EXECUTE — all checklist items done; per-section gates green
- [ ] 6. EVL — independent vc-tester re-run; follow-up stubs registered
- [ ] 7. UPDATE PROCESS — phase report written; umbrella state updated; commit done

**Validate-contract required before execute.**

---

## Exit Gate

- AC-13 green including the flag-ON leg.
- Purity gate (G17) and no-production-caller gate (G24) green.
- Unit lane shows no new failures vs baseline; `voice_examples` behavior unchanged.
- Phase report written to the report destination.
- **Nothing in this phase enables autonomous sending.** `engage_outcome_learning_enabled` remains OFF
  in every real environment until a separate operator action.

---

## Execute Anchor

This file IS the primary execute anchor for its phase — pass this exact path to vc-execute-agent.
Supporting phase files (read-only context, never the execute target): the umbrella plan, the sibling
phase plans, and the locked SPEC in this task folder.

---

## Resume and Execution Handoff

1. Selected plan file path: `process/features/campaigns-outreach/active/engage-learning-agent_17-08-26/phase-3a-learning_PLAN_17-08-26.md`
2. Last completed phase or step: created 17-08-26 (PVL cycle-4 split); no PVL run yet against this file.
3. Validate-contract status: pending — this plan has never been validated as a standalone artifact.
4. Supporting context files loaded: `process/context/all-context.md`, `process/context/tests/all-tests.md`, the SPEC, the umbrella plan, Phase 1 plan.
5. Next step for a fresh agent: run PVL from V1 against this plan. Do NOT run EXECUTE — no validate-contract exists.

---

## Next Step

Run PVL from V1 (`ENTER VALIDATE MODE`) against this newly split plan. Never ENTER EXECUTE MODE before
the validate-contract is written.

---

## Validate Contract

Status: PASS
Date: 17-08-26
date: 2026-08-17
generated-by: outer-pvl
supersedes: 2026-08-17 (outer-pvl, PVL cycle 5) — cycle-5 FAIL 3a-2 and CONCERN 3a-C4 re-derived against the files and real source; both CLOSED. No new findings.

Parallel strategy: sequential (no Agent tool in this environment — Layer 1 dimensions and Layer 2 sections executed sequentially in-agent against real source)
Rationale: signal score 2/7 (S4 phase program, S5 depth requested). No schema, no migration, no send path, no web file, no config read beyond one flag.

### Net Gate Derivation

| Layer 1 dimension | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | PASS |
| Breaking changes | PASS |
| Security surface | PASS |

| Layer 2 section | Status |
|---|---|
| Step A — pure autonomy gate | PASS |
| Step B — outcome-driven strategy selection | PASS |
| Step G — tests | PASS |

**Totals: 0 FAILs / 0 CONCERNs / 7 PASSes → Net Gate: PASS**

Trajectory for this artifact: cycle 4 = 1 FAIL / 3 CONCERNs → cycle 5 = 1 FAIL / 1 CONCERN → cycle 6 = **0 / 0**. Proceed to EXECUTE.

---

### Cycle-5 closures — RE-DERIVED

| Cycle-5 finding | Verdict | Evidence re-checked this cycle |
|---|---|---|
| **FAIL 3a-2** — explicit-argument signature applied in A1 only | **CLOSED** | The new form now appears in all three places: Overview/Goals `:67` `autonomy_gate(stats, min_outcomes, min_positive_rate)`; **Public Contracts `:145`** `services/engage_autonomy.autonomy_gate(stats, min_outcomes: int, min_positive_rate: float) -> AutonomyDecision`; A1 `:170` identical. A mechanical scan of the plan **body** for the superseded string `autonomy_gate(stats, config)` returns **zero hits** in 3a — and zero prescriptive hits in 3b (its single occurrence is inside the deliberate why-note recording what was deleted). |
| **3a-C4** — umbrella listed `engage_autonomy.py` under 3b | **CLOSED** | Umbrella `:305` now lists `apps/api/services/engage_autonomy.py` under Phase 3a ("new — pure `autonomy_gate()`, **no production caller in this phase**"), and `:317` records it as "**READ-ONLY in 3b** (created by 3a; 3b imports it)". Ownership and the read-only consumption rule are both explicit. |

---

### PASSes (verified against real source)

- **Config-key move is structurally complete.** Touchpoints `:128-129`: "appends the `# ─── Engage learning (Phase 3a) ───` block only. **Exactly ONE key: `engage_outcome_learning_enabled`.** Every `engage_autonomy_*` key — both kill switches, the ceiling, the dwell floor and the two thresholds — belongs to 3b." A3 `:178` records the default values as documentation of what 3b must use, not as keys 3a adds. Blast Radius still counts 2 edited files, consistent.
- **The signature change is coherent end-to-end.** With thresholds as explicit arguments, A7's "imports no mutable global config" is now trivially satisfiable rather than aspirational, and G24's inertness assertion cannot collide with config-key names. The three cycle-4/5 findings on this phase were all facets of one design problem that the argument form dissolves.
- **G24 is a real, passable gate.** The pytest test `test_autonomy_gate_has_no_production_caller` is authoritative and asserts on the IMPORT (walks `apps/api/**/*.py`, asserts no `from apps.api.services.engage_autonomy` / `import engage_autonomy`, excluding the module itself and `tests/`); the shell grep is explicitly demoted to advisory.
- **Step B mechanically feasible.** `_get_preferred_strategy(db, user_id, platform)` at `ai_reply.py:204`; `determine_draft_mode(platform, db, user_id) -> tuple[str, list[str], Optional[str]]` at `:261`. Fall-through leaves both untouched when the flag is OFF.
- **Q6 slug rule correct.** `apps/api/models/site.py:15` is `site_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)` — unique, so Phase 1's `String(50)` FK → `sites.site_id` is legal.
- **AC-13 non-vacuous** — G4 (deterministic seed, distribution shifts), G4b (flag-OFF control, byte-identical), G4c (below-floor boundary), G25 (mandatory flag-ON leg). Control + boundary + flag-ON.
- **AC-11/AC-12 deliberately not claimed here** — built in Step A, proven in 3b through the driver (3b's AC-11 row now credits G2 **and** G28 jointly). Correctly avoids the vacuous-gate class.
- **Cross-plan duplicate scan (new dimension) is clean.** Gate ids: 3a holds `G1, G4, G4b, G4c, G16, G17, G24, G25`; the only id shared with 3b is **`G16`**, which is the deliberate per-phase regression sweep. Shared source files are `config.py`, `ai_reply.py`, `engage_autonomy.py` — all three governed by explicit umbrella rules (per-phase config block; SHARED-SEQUENTIAL with named regions and a no-reformat clause; created-by-3a / read-only-in-3b). No ungoverned overlap.
- **Structural validator:** 0 failures, 0 warnings. **No duplicate headings.** **No stale "Phase 3" references** — all body hits are deliberate "the former Phase 3" history.
- **Infra available now:** PG:5433 and Redis:6379 LISTENing; `.venv/bin/python3.11` resolves (this phase needs neither).

---

### Test gates (C3 5-column)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-13 | Selection shifts toward the measured winner | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_engage_strategy_selection.py::test_approach_selection_shifts_with_outcome_history -m unit -q` | A/B |
| AC-13 (control) | Selection unchanged when the flag is OFF | Fully-Automated | `…::test_selection_unchanged_when_learning_flag_off -m unit -q` | B |
| AC-13 (boundary) | Approval signal wins below the outcome floor | Fully-Automated | `…::test_approval_signal_wins_below_outcome_floor -m unit -q` | B |
| AC-13 (flag-ON) | Both legs re-run with learning enabled | Fully-Automated | `ENGAGE_OUTCOME_LEARNING_ENABLED=true .venv/bin/python3.11 -m pytest tests/unit/test_engage_strategy_selection.py -m unit -q` | B |
| AC-11 groundwork | Gate arithmetic: below-N, at-N-below-R, at-N-at-R | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_engage_autonomy.py::test_autonomy_gate_pure_function_of_outcome_history -m unit -q` | B — proves the FUNCTION; AC-11 itself is proven in 3b by G2+G28 |
| Purity | Gate module imports no model/session/mutable global config | Fully-Automated | `…::test_autonomy_gate_module_is_pure -m unit -q` | B |
| Inertness | Gate function has no production caller | Fully-Automated | `…::test_autonomy_gate_has_no_production_caller -m unit -q` (pytest authoritative, import-based); advisory cross-check `grep -rn "from apps.api.services.engage_autonomy\|import engage_autonomy" apps/api --include="*.py"` | B |
| Regression | Full unit lane; `voice_examples` unchanged | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` | A |
| Entry | Phase 1 deliverable importable | Fully-Automated | `.venv/bin/python3.11 -c "from apps.api.models.engage_outcome import EngageOutcome; print(EngageOutcome.__table__.c.keys())"` | A |

gap-resolution legend: A — proven now; B — fixed in this plan; C — deferred to a named later phase; D — backlog stub.

No integration lane and no container are required — this phase writes no schema and no migration.

---

### Dimension findings

- Infra fit: PASS — unit-lane only; both `ai_reply.py` anchors real; `models/site.py:15` confirms the slug FK; no ports, container or migration.
- Test coverage: PASS — every developed behavior in this phase carries a Fully-Automated gate (AC-13 ×4 legs, purity, inertness, regression). No behavior rests on a Known-Gap.
- Breaking changes: PASS — Public Contracts, Overview and A1 now agree on the function signature; `determine_draft_mode` is unchanged while the flag is OFF; `voice_examples` is not rebuilt and is regression-gated; no enum, schema, web type or API route.
- Security surface: PASS — no auth, billing, PII, migration or trust-boundary surface. The gate ships unreachable and, with thresholds as arguments, cannot read operator config at all.
- Step A / Step B / Step G: PASS.

---

### Execute-agent instructions

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | `autonomy_gate` takes `(stats, min_outcomes, min_positive_rate)`. It must NOT import or read `apps.api.config`. | Step A entry |
| E2 | Edit ONLY `select_strategy_from_outcomes` and the `determine_draft_mode` consult in `ai_reply.py`. Do not touch `_sanitize_content` (`:111-119`) — 3b owns it. Do not reformat, reorder or re-indent the file; import additions are append-only. | Step B entry |
| E3 | Do not import `engage_autonomy` from any module under `apps/api`. The gate ships unreachable in this phase. | Step A entry |
| E4 | Add exactly ONE key to `config.py` (`engage_outcome_learning_enabled`). Every `engage_autonomy_*` key belongs to 3b. | Step B5 entry |
| E5 | Import the positive-outcome definition from Phase 2's `engage_track_record`; never redefine it locally. | A4 entry |
| E6 | Implement the DISTINCT-contact leg against the `contact_bidx` column contract and mark it Phase-2-dependent. Do not substitute another key. | A5 entry |
| E7 | Touch no schema, no migration, no `sender.py`, no `apps/web` file and no doc surface. Any need to do so is a BLOCKED condition to surface. | Any step |
| E8 | 3a lands BEFORE 3b. Do not begin 3b work from this plan. | Any step |

---

Open gaps: none.

Known gaps (accepted postures — named residuals with written justification, excluded from the FAIL/CONCERN count):
- `N=20` / `R=0.4` — placeholder-conservative, tune-from-observed operator values. After cycle 5 these are 3b's config keys, passed into this phase's function as arguments; this phase ships no defaults of its own.
- DISTINCT-contact positive-rate counting — Phase-2-dependent (`engage_outcomes.contact_bidx`, Phase 2 item A2b). The gate's arithmetic IS covered by G1 (which feeds `stats` directly, no DB); only the real-column integration is deferred, and it is written against the column contract.

Neither residual leaves a developed behavior of this phase ungated, so the PASS is not vacuously green.

What this coverage does NOT prove:
- Everything here is unit-lane. No gate touches a database, Redis, a container or a browser.
- The gate-arithmetic test proves the FUNCTION's arithmetic. It proves nothing about whether a fabricated model confidence can authorize a real send (3b G2), nor that the operator's configured thresholds are the ones applied (3b G28).
- The inertness gate proves no module imports `engage_autonomy` at the moment it runs. It proves nothing about 3b, which legitimately adds the first caller.
- The purity gate proves the module's import surface, not the caller's behavior.
- The flag-ON leg proves the selector shifts under real config. It does not prove the resulting drafts are better; reply quality is outside this phase.
- `voice_examples` regression rests on the existing unit lane; no gate here exercises the live explore→exploit loop against a real database.
- PG:5433 and Redis:6379 were confirmed LISTENing at validate time (17-08-26); this phase needs neither, and that is not a CI-runnability guarantee.

Gate: PASS
Accepted by: n/a — PASS gate, no concerns to accept. This is a factual 0-FAIL / 0-CONCERN determination, not a self-acceptance.
