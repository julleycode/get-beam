---
name: report:engage-learning-agent-pvl-iteration-003
description: "PVL cycle 3 — 11 → 8 FAILs; all prior findings closed at root; residue = stale cross-refs (P1), absorption propagation (P2), audit-marker schema (P3); 3a/3b split triggered"
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: report
  type: pvl-iteration
  cycle: 3
---

# PVL Iteration 003 — engage-learning-agent

## Verdicts (cycle 3)

| Plan | Gate | FAILs | CONCERNs | Character of residue |
|---|---|---|---|---|
| phase-1-signal-acquisition | BLOCKED | 3 | 7 | Pure stale cross-references (one-line fixes); all 14 cycle-2 gaps closed at root. Validator: "last real cycle." |
| phase-2-memory-privacy | BLOCKED | 3 | 6 | contact_bidx absorption written into Step A only — Entry Gate contradiction, missing second dispatch branch (silent-no-op class again), half backfill |
| phase-3-learning-autonomy | BLOCKED | 2 | 4 | Audit-as-marker schema lacks draft_id/entry_type; failed/undone outcome entries have no licensed write site. **Split-revisit signal TRIGGERED** (2 consecutive cycles of fix-introduced FAILs, all in Steps C–G; Steps A+B three-cycles-clean) |

Trend: 19 → 11 → 8. No restated findings any cycle.

## Orchestrator decisions for cycle-4 supplement (binding)

- **Split ACCEPTED per the umbrella's own recorded rule:** Phase 3 → **3a (learning: Steps A+B, AC-13)** + **3b (autonomy + rails: Steps C–G, AC-11/12/14–20)**. Deps: 3a ← Ph1; 3b ← 3a + Ph2. Umbrella becomes a 4-phase program; registry rows, AC table, Stable Program Goal, Current Execution State updated.
- P3 audit schema: `engage_autonomy_audit` gains `draft_id` (FK → drafts.id, indexed) + `entry_type` discriminator (decision | outcome | undo).
- P3 outcome rows: written by the DRIVER after `send_draft` returns (driver-owned file — no registry change, no fifth sender.py edit).
- Re-eligibility: kill-switch-reverted drafts re-enter autonomy when the switch re-enables; drafts with sent/failed/undone outcome entries are permanently autonomy-excluded (failed → human queue; prevents auto-retry loops). Gate both directions.
- Human retry of a formerly-auto draft: restore `pending` (never approved, never auto_approved) — human re-approves through the normal path. Gate it.
- Driver commit boundary stated in C5; G10 gains failed-send audit assertion.
- P2: Entry Gate asserts site_id + platform_ref only (contact_bidx absent-by-design note); B1/B5/B6 each cover BOTH tables; `engage_outcomes` erasure = `UPDATE … SET contact_bidx = NULL` cross-tenant (unlink the person, keep the non-PII outcome fact — preserves track records; deletion reserved for engage_contact_memory rows); A5b backfills both target names; contact_bidx on NEW rows only (no backfill minting post-erasure bidx); engage_outcome.py added as SHARED touchpoint; counts reconciled to FIVE; F10 + AC-5 lists = all 8 erasure gates.
- P1: delete D3 contact_bidx clause; registry stale `drafts.py` row struck; E6 rewritten "distinct jitter literal per C1 — no next_run_time"; A3b/E4 gain `index_where=text("platform_ref IS NOT NULL")` (precedent agent_visit_persistence.py:221, NOT events.py:687); scheduler counts → re-derive-only wording everywhere (also P2 Gap 9, Entry Gates); config block lists all 4 keys; F2b "(5 cases, both producers)"; slug join rule propagated into Ph2 + 3a/3b plan texts; C4 names _process_signal_events explicitly.

## Pending USER decisions (unchanged, for gate summary)

1. KG-1 handle-rename drift — now spans two tables (engage_contact_memory + engage_outcomes.contact_bidx). Accept bounded un-erasable-PII residual vs require platform-stable author id (scope increase).
2. AC-4 real-path ROI residual — site-link-offer work parked as backlog stub (no home phase).
