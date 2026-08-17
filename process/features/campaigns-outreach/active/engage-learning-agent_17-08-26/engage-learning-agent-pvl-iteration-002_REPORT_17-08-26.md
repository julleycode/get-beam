---
name: report:engage-learning-agent-pvl-iteration-002
description: "PVL cycle 2 — re-validation from V1 after 47-gap supplement: 19 FAILs → 11, all cycle-1 FAILs verified closed, 11 new FAILs in the amended surface"
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: report
  type: pvl-iteration
  cycle: 2
---

# PVL Iteration 002 — engage-learning-agent

## Verdicts (cycle 2, all contracts superseded with `supersedes:` notes)

| Plan | Gate | FAILs | CONCERNs | Cycle-1 closures |
|---|---|---|---|---|
| phase-1-signal-acquisition | BLOCKED | 6 (N1–N6) | 8 | 4 closed, 3 superseded by sharper findings |
| phase-2-memory-privacy | BLOCKED | 2 (F2-1, F2-2) | 4 | all 5 verified closed |
| phase-3-learning-autonomy | BLOCKED | 3 | 8 | all verifiable closed; 7→3 |

Trend: 19 → 11 FAILs; no restated findings; every new FAIL traces to text the 47-gap supplement introduced. Convergent, not plateaued.

## New FAILs

P1: N1 `Draft.site_id` UUID-vs-slug type mismatch (all existing site_id consumers are String(50) slugs); N2 dominant producer `routers/drafts.py:199` out of scope + registry-forbidden, sets no visitor_id; N3 ingest anchor inside a list comprehension (await impossible; internal commit would split the batch); N4 metrics day-key vs per-poll cadence violates own unique index; N5 contact_bidx needs Phase-2-owned blind_index() (circular); N6 contact_bidx = PII with no erasure path in its creating phase.

P2: F2-1 `graph_erasure.py:380` `if bidx or fps:` guard never widened — author-bidx-only request skips ALL deletion, still commits done; F2-2 enqueue-side derivation unpinned — write/enqueue key spaces can silently diverge.

P3: no durable autonomy marker survives send-failure paths (failed auto_approved ≡ failed approved); `_auto_reject_siblings` commits internally so same-transaction rail is impossible as written; AC-20 surface set misses `llms.txt/route.ts:30` + `page-help.tsx:93` (served product surfaces asserting never-auto-send).

## Orchestrator decisions for cycle-3 supplement (binding)

- N1: `Draft.site_id` = String(50) FK → `sites.site_id` (slug; matches every existing consumer).
- N5/N6: `contact_bidx` DEFERRED to Phase 2 (blind_index helper + ERASURE_TARGETS live there; Ph3 already depends on Ph2 — dependency graph unchanged; no un-erasable-PII window). Ph3 DISTINCT-contact rate documented Ph2-dependent.
- N4: metrics_snapshot = day-key + `ON CONFLICT DO UPDATE` latest-wins, cadence unchanged; counters are cumulative so latest-wins is correct; strict append-only retained for reply_received/attributed_visit.
- N2: `routers/drafts.py` → SHARED in registry with ONE licensed Ph1 edit (set site_id at manual-draft creation; user-single-site else NULL).
- N3: re-anchor ingest wiring after `events.py:474` commit, batch-deduped, fail-open.
- P3 marker: audit row written at FLIP time in the driver's transaction (decision record incl. sample_n/rate); second audit entry at send outcome (sent/failed/undone). Audit table IS the durable marker — retry check + eligibility predicate query it. No new Draft column; registry unchanged.
- P3 siblings: extract PURE selection helper (no commit, no side effects); human endpoint keeps byte-compatible behavior; driver applies rejections in its own transaction with the flip. Machine-rejected siblings do NOT feed voice_examples (human decisions only) + gate.
- AC-20 scope: llms.txt route + page-help.tsx ADDED to Step F + F5 greps; docs/* + marketing/* exclusions named deliberate (existing marketing-copy backlog note covers external copy).
- Dwell floor: NEW `engage_autonomy_min_draft_age_minutes` default 30 — driver only considers pending drafts older than this; gated.
- 3a/3b split: REJECTED — flag rollout order (capture → learning → autonomy) provides the operational staging the split targets; validator recommendation + this rationale recorded in umbrella.
- K1: jitter-only, any next_run_time capped strictly below 90s. K8: mocking mechanism named per surface (_FakeService monkeypatch for tests; service-layer mock branches per repo convention); umbrella constraint reconciled. P3 Gap 5/6: gate = `npm run build`; assumed manager npm (package-lock.json is tracked; stray pnpm files are ambient, not program-owned).

## Pending USER decisions (carried to gate summary, not blockers for plan text)

1. KG-1 handle-rename drift: bounded un-erasable-PII residual on a privacy feature — accept (documented residual + backlog stub) vs reject (requires platform-stable author id, scope increase into Phase 1).
2. AC-4 real-path ROI residual: "drafting may offer site link" has no home phase — parked as backlog stub.
