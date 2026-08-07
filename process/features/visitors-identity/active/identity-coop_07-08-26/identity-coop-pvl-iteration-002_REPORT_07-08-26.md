---
name: identity-coop-pvl-iteration-002
description: PVL V1 re-run after F1 entry-gate clear — CONDITIONAL, EXECUTE unblocked, 5 doc-sync concerns to supplement
date: 2026-08-07
metadata:
  type: pvl-iteration-report
  plan: phase-1-ledger-substrate_PLAN_07-08-26.md
  cycle: 2
  loop: PVL
---

# PVL Iteration 002 — identity-coop phase-1 (post-F1-clear re-run)

**Verdict:** `Gate: CONDITIONAL` — BLOCKED → CONDITIONAL, EXECUTE unblocked, zero new behavioral FAILs.

## Entry gate — independently verified LIVE

14/14 erasure gates collect + commit `81eb4e6` in history (test-side-only repairs); `443ad5e` on both remotes (0/0); single alembic head `d1a6c4e93f27` (= SPEC A's own migration); resolver anchors unmoved (`identity_resolver.py` call site :1252, definition :1264).

## Re-verified

D-A..D-E all hold against live source. Docker 29.4.2 UP → every Hybrid gate re-tiered D→B (runnable + required). Gate table completed: added F12 + F14 + partial-index IntegrityError row; removed stale F6-widening row (test retired at cycle 1); diff guard corrected ≤6 → ≤12. Evidence pack = EXECUTE deliverable (E-5): `harness/` 5-artifact schema + APPROVE/REJECT + 2 adversarial scenarios (credit-without-write; erased-person-row-creation).

## Supplement scope (cycle 2 — P1-P8, all doc-sync)

- **P5/N5 (precondition):** clear `Dependency-BLOCKED` / "Do NOT spawn vc-execute-agent" from plan lines ~17-18/527/537-539 + `phase-blast-radius-registry.md:35`.
- **N1:** Exit Gate `<= 6 changed lines` → `<= 12` (D4 supersession applied to the copyable block).
- **N2:** add `coop_terms_version` to `## Config Settings`; B2 "four defaults" → five.
- **N3:** D5/D-A "three early-return guards" → real edit set: 4 return-value edits (returns :1271, :1285, except path, final) + signature + docstring.
- **N4:** D-C anchor `visitor.py:207` → real `Visitor.is_abuse_flagged:97` + `is_bot_suspect:105`.
- **P8:** umbrella §Stable Program Goal — remove stale "SPEC A not LIVE" HARD STOP + fix `START:` line + `## Current Execution State`.

**EXECUTE strategy (V4):** sequential 1× vc-execute-agent (opus) + vc-tester EVL — deviation from 4/7-HIGH stated: dependency chain A→G has no independent slices.
