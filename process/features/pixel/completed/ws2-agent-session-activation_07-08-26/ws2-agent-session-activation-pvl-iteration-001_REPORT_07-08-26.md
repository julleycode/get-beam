---
name: ws2-agent-session-activation-pvl-iteration-001
description: PVL supplement cycle 1 — folded 7 VALIDATE CONCERNs (E1–E7) into the plan body
date: 2026-08-07
metadata:
  node_type: report
  type: pvl-iteration
  iteration: 1
  domain: plan
  plan: process/features/pixel/active/ws2-agent-session-activation_07-08-26/ws2-agent-session-activation_PLAN_07-08-26.md
---

# PVL Iteration 001 — WS2 Agent-Session Activation

**Cycle:** 1 of 10 (cap)
**Trigger:** `Gate: CONDITIONAL` first-pass from vc-validate-agent (0 FAILs, 7 CONCERNs)
**Applied by:** vc-plan-agent, PVL-supplement mode
**Signal:** `SUPPLEMENT_APPLIED: … — 7 gap(s) addressed`

## Entry state

| Field | Value |
|---|---|
| Gate verdict | CONDITIONAL (first-pass — not terminal) |
| FAILs | 0 |
| CONCERNs | 7 (E1–E7) |
| SUPPLEMENT REQUEST gaps | 5 (E1–E5); E6/E7 informational |
| Validate-contract | written, `generated-by: inner-pvl: phase-1`, `date: 2026-08-07` |
| Plan validator | 0 failures, 0 warnings |

## Why a supplement cycle ran at all

vc-validate-agent's write scope was restricted to the `## Validate Contract` section, so all 7
corrections landed there as Execute-Agent Instructions rather than in the checklist body. An
execute-agent reading the checklist text alone would still have followed the uncorrected
instructions — most consequentially E3. This cycle moves the corrections into the body so the
checklist is self-sufficient.

## Gaps addressed

| # | Finding | Fix applied |
|---|---|---|
| **E3** | **Wrong persistence site.** Step 3.5 pointed at the `fp3_value` path, but `fp`/`fp3` are written to the **Visitor** row (`_process_signal_events`, `apps/api/routers/events.py` ~L540-606), not the Event row. AC-4's test asserts on the **Event** row → following the literal instruction would have silently failed AC-4 while every gate looked green. | Step 3.5 retargeted to the `event_rows` / `pg_insert(Event)` block (~L375-422), naming `link_marker` as the pattern to copy; failure mode spelled out inline |
| E1 | Dead test gate. Steps 1–2 used `-m unit` against `tests/unit/test_pixel.py` / `test_pixel_fingerprint.py`, which carry **zero** pytest markers — deselects 100%, exit code 5, a gate that passes without running anything | `-m unit` stripped from both commands |
| E2 | Unachievable "fires at all" check. The pixel Python suite is string/regex-only; no JS execution engine exists in the repo, so the second pass condition could not be a pytest assertion | New Playwright spec `apps/pixel/e2e/agent-sig.spec.ts`, mirroring `fingerprint-v3.spec.ts`. Two-part pass condition preserved — only the proving mechanism changed |
| E4 | AC-6 mis-tiered "Hybrid / component-render Fully-Automated leg". `apps/web` has **zero** component-render infra (same gap cadence-bot-flag hit and reclassified). Also no shared badge component exists — badges are inline at 3 sites | AC-6 → Agent-Probe across traceability table, Verification Evidence, Step 6, Touchpoints; 3 inline sites named; shared-component assumption removed; missing infra routed to `## Test Infra Improvement Notes` per the cadence-bot-flag precedent |
| E5 | Imprecise instruction — "if such an assertion exists, update it". Only `test_has_bot_detection` exists, a non-behavioral string check | Clarified: a NEW behavioral test must be written; no longer conditional |
| E6 | Scheduler job-registration path had been deliberately deferred to EXECUTE-time grep | Confirmed `apps/api/jobs/scheduler.py` ~L565-569; folded into Step 4.6 + Touchpoints, hedge removed |
| E7 | Column type unspecified as plain JSON | `JSONB` + legacy `Column(...)` style, matching every other JSON-shaped column; updated in Step 3.3, Touchpoints, Public Contracts |

## Not re-litigated

INNOVATE's D1–D4 stand unchanged: D1 visibility-only (`is_emailable_identity` untouched; the
"exactly 3 parameters" invariant at
`apps/api/migrations/versions/f3a7c9e21b48_add_internal_traffic_damping.py:21` holds), D2 trimmed
proxy signals on the existing click listener, D3 delete `tracker.js:4` outright with collection
after the consent gate, D4 fresh port via `git show`.

No scope added. SPEC Out-of-Scope items remain out.

## Carried forward unchanged

- Feasibility probe `ws2-webdriver-assumption_FEASIBILITY_07-08-26.md` — verdict **INCONCLUSIVE**.
  Whether agentic browsers set `navigator.webdriver = true` by default is still open. AC-14 stays a
  Known-Gap; the plan may not claim empirical support for the assumption anywhere.
- AC-12, AC-13 — Known-Gap, unmeasurable pre-ship.
- Visibility-only does not stop pre-sweep identity-resolution budget burn — same limitation
  `cadence_bot_flag` accepted. Named in the plan's Known Limitation section.
- Migration live round-trip — Docker-gated, standing repo-wide constraint.

## Exit state

| Field | Value |
|---|---|
| Gaps addressed | 7 |
| Plan validator | 0 failures, 0 warnings |
| `## Validate Contract` | untouched (vc-validate-agent's artifact) |
| `## Inner Loop Refresh Note` | not added — supplement, not a fresh R+I pass |
| Next action | re-spawn vc-validate-agent from V1 against the updated plan |
