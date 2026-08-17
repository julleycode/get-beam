---
name: report:engage-learning-agent-pvl-iteration-004
description: "PVL cycle 4 — split executed (4-phase program); P1 CONDITIONAL 0-FAIL; P2/3a/3b each 1 mechanical FAIL; 8 → 3 total"
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: report
  type: pvl-iteration
  cycle: 4
---

# PVL Iteration 004 — engage-learning-agent

## Verdicts (cycle 4; program now 4 phases after the 3a/3b split)

| Plan | Gate | FAILs | CONCERNs | Note |
|---|---|---|---|---|
| phase-1-signal-acquisition | **CONDITIONAL** | 0 | 4 (R1–R4 doc-label drift) | First non-BLOCKED verdict; EXECUTE-eligible once accepted; duplicate-block scan clean |
| phase-2-memory-privacy | BLOCKED | 1 | 5 | F4h gate says "delete" vs B5b UNLINK implementation + no non-vacuity control — test-name-drives-implementation risk on the GDPR surface |
| phase-3a-learning | BLOCKED | 1 | 3 | G24 inertness grep collides with 3a's own config keys — cannot pass on correct work |
| phase-3b-autonomy | BLOCKED | 1 | 2 | AC-20 five-grep fix survives only in Step F5; executable sections (Test Procedure, Exit Gate) still say three |

Trend: 19 → 11 → 8 → 3. All 3 remaining FAILs are text-mechanical. All cycle-1..3 design FAILs verified closed against source. Split verified: shared-sequential ai_reply.py rule HOLDS on real disjoint regions (:111-119 vs :204/:261); Ph2⟂3a parallel-safety verified against actual file sets.

## Orchestrator decisions for cycle-5 supplement (binding)

- 3a: MOVE the two tuning keys (`engage_autonomy_min_outcomes`, `engage_autonomy_min_positive_rate`) to 3b's config block (with the gate's first caller); `autonomy_gate()` takes thresholds as explicit arguments — resolves the G24 collision structurally AND purifies 3a inertness. G24 additionally asserts on the import, not the substring.
- Plan-agent standing rules adopted (this program): (1) Test Procedure sections are REGENERATED from the current checklist, never hand-patched (two findings from hand-patch drift); (2) supplement-time self-check that every "X covers/asserts Y" claim is honored AT X (three cycles produced this shape).
- P2: F4h → `test_erasure_unlinks_engage_outcomes_contact_bidx` with full non-vacuity set (row survives, contact_bidx IS NULL, non-PII columns unchanged, control contact untouched); B5b dup id → B5c; F4d renamed + both assertions; stale four-gate clause deleted; Exit Gate → 8 gates / FIVE objects; 9 stale Phase-3 refs disambiguated.
- 3b: three → five in all 5 locations; Test Procedure regenerated (npm run build, draft-card.tsx in the grep, literal component path).
- P1: R1–R4 applied (~6 line edits, incl. umbrella prose refs + one dual-label registry row); contract STANDS at CONDITIONAL — cycle-5 revalidation covers P2/3a/3b only (P1 fixes are non-instructional label edits).
- Umbrella: ai_reply.py shared rule gains no-reformat / append-only-imports sentence.

## Pending USER decisions (unchanged)

KG-1 handle-rename drift (accept bounded un-erasable-PII residual vs platform-stable author id); AC-4 site-link-offer backlog stub.
