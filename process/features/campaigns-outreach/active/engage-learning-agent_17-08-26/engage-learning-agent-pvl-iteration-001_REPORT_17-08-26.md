---
name: report:engage-learning-agent-pvl-iteration-001
description: "PVL cycle 1 — outer PVL fan-out (3 validators + adversarial cross-plan verifier) → all 3 phase plans BLOCKED; consolidated supplement applied (47 gaps)"
date: 17-08-26
feature: campaigns-outreach
metadata:
  node_type: report
  type: pvl-iteration
  cycle: 1
---

# PVL Iteration 001 — engage-learning-agent

## Cycle shape

Outer PVL, 4 parallel agents: 3 × vc-validate-agent (opus, one per phase plan, STOP-block hardened) + 1 adversarial cross-plan verifier (fable, read-only, REFUTE-default). Supplement: single vc-plan-agent (opus, resumed warm) amending all 4 artifacts in one session.

## Verdicts (first pass)

| Plan | Gate | FAILs | CONCERNs |
|---|---|---|---|
| phase-1-signal-acquisition | BLOCKED | 7 | 12 |
| phase-2-memory-privacy | BLOCKED | 5 | 8 |
| phase-3-learning-autonomy | BLOCKED | 7 | 9 |
| cross-plan adversarial | 8 REFUTED + 4 lesser | — | — |

None of the FAILs was the expected OQ-1 live-provider residual (recorded as accepted known-gap).

## Headline defects (all confirmed against source)

1. No draft→site key anywhere (Draft is user-scoped; multi-site ambiguous) — every per-site rail dangled.
2. Autonomous-send driver homeless — nothing licensed to call autonomy_gate()/write auto_approved/trigger send.
3. Erasure design silent no-op ×2: no `_process_claimed` dispatch branch (deletes nothing, still commits done) + sweep-time join whose source is deleted during the request.
4. engage_outcomes dedupe key couldn't dedupe (observed_at = sweep time) → Phase-3 positive-rate inflation.
5. AC-4 unachievable on real path (replies never carry site links) + `attributed_visit` had no producer.
6. Sibling drafts (1–3/post) double-post under autonomy — auto-reject lives only in the human approve endpoint.
7. AC-20 half-gate (grep missed `never auto-send` :742 + README.md:3).
8. DraftStatus consumer gate structurally unable to fail (real surface = web TABS/status-badge/draft-card/TS union).
9. Scheduler AST test (id+jitter+misfire_grace_time literals, hardcoded 26/22 counts) outside blast radius.
10. Enum migration: zero ALTER TYPE precedent, PG has no DROP VALUE, round-trip gate as written unrunnable (wrong DSN, heads-only).

## Orchestrator decisions (binding, D-O1..D-O10)

Nullable `Draft.site_id` + fail-closed-on-NULL for all site-keyed rails; AC-4 re-scoped to link-present path (no auto-append; length re-validation skips rewrite past platform cap); new Ph3 `services/engage_autonomous_sender.py` + scheduler job as named driver; umbrella registry re-classified 5 surfaces exclusive→shared-with-rule; sibling auto-reject reused in autonomous path; AC-20 = 3 greps; erasure = fingerprint_list-mirroring (author_bidx collected at enqueue, ARRAY column, func.any, dispatch branch); contact_bidx column enables DISTINCT-contact rates, segment dimension dropped v1 (no data source — SPEC deviation known-gap); platform_ref partial-unique dedupe; retweet_count naming, retry-status laundering fix, autocommit ALTER TYPE + type-recreate downgrade, DSN corrections, attributed_visit producer in routers/events.py.

## Supplement result

`SUPPLEMENT_APPLIED` — 47 gaps (39 contract + 8 adversarial). AC-18 flipped fail-open→fail-closed (stricter than SPEC, documented). Migration count 3→4. All artifact validators clean. Cycle-1 validate-contracts preserved (still read BLOCKED pending cycle 2).

## Carried questions

- C-A2 handle-rename drift = GDPR-adjacent residual → needs explicit user accept/reject at gate.
- "Drafting may offer site link" deferred, no home phase → backlog stub at closeout.
- If cycle 2 re-FAILs Phase 3 rails → consider 3a/3b split before third supplement.
