---
name: report:program-branch-consolidation-note
description: "agent-native-revenue — 4-branch inventory + deltas to apply to main/umbrella once WS0 lands"
date: 31-07-26
metadata:
  node_type: memory
  type: report
  feature: agent-native-revenue
  phase: consolidation
---

# agent-native-revenue — Branch Consolidation Note

**Why this note exists:** the `agent-native-revenue` phase program is split across 4 branches, each
built in its own isolated worktree. The umbrella plan and `process/context/all-context.md` only
exist on `feat/ws2-agent-session-classifier` — they are NOT on `main` and NOT on this checkout
(`feat/ws3-agent-concierge`). This note records every delta that must be applied to those files
**once**, at consolidation time, so no workstream's learnings are lost and nothing gets silently
forked or overwritten.

**Do not apply these edits from this branch.** Editing `all-context.md` or the umbrella plan here
would fork them from the copy on `feat/ws2-agent-session-classifier`, creating a merge conflict or
silent divergence. This note is deliberately a passive record, not an action.

## Branch Inventory (as of 31-07-26, all off `main` tip `717cd64`, none pushed/merged)

| Branch | Holds |
|---|---|
| `feat/ws0-...` (WS0 — not directly inspected from this branch; name inferred from Join Conditions references in the WS3 plan) | WS0 handoff-exit-metric work — the umbrella's blocking dependency for WS1/WS3's wild kill tests |
| `feat/ws1-ai-evaluation-timeline` | WS1 code + WS1 plan/report |
| `feat/ws2-agent-session-classifier` | WS2 code (dormant, per prior memory note `agent-native-revenue-ws2-dormant.md`) + **ALL program docs**: `agent-native-revenue_SPEC_30-07-26.md`, `agent-native-revenue-umbrella_PLAN_30-07-26.md`, `process/context/all-context.md` |
| `feat/ws3-agent-concierge` (this branch) | WS3 code (Steps 1-4, CODE DONE, EVL-green) + WS3 plan + WS3 phase report + WS3 backlog note (this note) |

None of the 4 branches are merged into `main` or pushed to origin as of this session.

## `all-context.md` Migration-Chain Delta (apply at consolidation)

The migration chain documented in `all-context.md`'s "AI-Agent-Traffic Layer" section currently ends
at `e6b2d4a1c837` (add_cadence_bot_flag — WS2-era current head, per that file's last update).

**Append** (WS3's 2 new migrations, chained off that point on `feat/ws3-agent-concierge`):

```
... → e6b2d4a1c837 (add_cadence_bot_flag) → b4d9e1a7c052 (agent_profile qualified_content)
    → c5e0f2b8d163 (agent_leads + agent_tool_calls, WS3 current head)
```

**Caveat:** this chain was traced independently on `feat/ws3-agent-concierge` only. WS1's branch may
have landed its own migrations in between `e6b2d4a1c837` and `b4d9e1a7c052` that are invisible from
this worktree — **re-run `alembic heads` on the actual merged branch at consolidation time** before
trusting this chain order as final. Do not hardcode it into `all-context.md` without that
re-confirmation (same discipline the WS3 plan itself repeatedly applied).

**New feature flags to add to `all-context.md`'s flag inventory** (both default OFF, same
operator-gated posture as every other flag in this program):
- `agent_concierge_qualification_enabled` — gates the param-gating behavior on the 3 existing free
  MCP tools (get_offers/get_pricing/check_availability). When OFF, those tools behave exactly as
  before this workstream (ungated).
- `agent_concierge_conversion_enabled` — gates whether `request_quote`/`book_demo` are exposed in
  `tools/list` and callable at all.

(WS2's already-noted flags from the `e6b2d4a1c837`-era commit are unaffected by this delta — no
change needed to that part of the file.)

## Umbrella `## Current Execution State` Deltas (apply at consolidation)

The umbrella plan (`agent-native-revenue-umbrella_PLAN_30-07-26.md`, on
`feat/ws2-agent-session-classifier` only) needs its `## Current Execution State` table updated with:

| Workstream | Status (apply at consolidation) |
|---|---|
| WS1 | **CODE DONE** — endpoint + UI implemented; wild-data AC is WS0-gated (per WS1's own plan/report on `feat/ws1-ai-evaluation-timeline`) |
| WS2 | **dormant** — already recorded on the `feat/ws2-agent-session-classifier` branch itself (server scaffolding only, `agent_sig` unpersisted; see prior memory note `agent-native-revenue-ws2-dormant.md`); no change needed from this note |
| WS3 | **CODE DONE** — Steps 1-4 (concierge param-gate, conversion tool, isolated lead table, kill-test metrics) implemented and EVL-green (1451 unit + 66 integration, 31-07-26); wild kill test (AC-WS3-5/6) is WS0-gated per this note's Recommended Consolidation Sequence below; see `ws3-agent-concierge-phase_REPORT_31-07-26.md` for full detail |

None of WS1/WS2/WS3 should be marked `✅ VERIFIED` in the umbrella until each workstream's own
wild-data acceptance criteria close (this mirrors the program's guardrail 3 wild-test discipline,
applied identically across all 3 workstreams that have one).

## Recommended Consolidation Sequence

1. Land WS0 (whichever branch holds it) onto `main` first — its production handoff exit metric
   (`AC-WS0-5`) is the blocking dependency for both WS1's and WS3's wild-data acceptance criteria.
2. Merge or rebase `feat/ws1-ai-evaluation-timeline`, `feat/ws2-agent-session-classifier`, and
   `feat/ws3-agent-concierge` onto `main`, in whatever order avoids the most conflict — none of the
   3 branches' code surfaces overlap significantly (WS1 = eval-timeline endpoint/UI, WS2 = session
   classifier, WS3 = MCP concierge/lead table), so ordering between them should be low-risk. Re-run
   `alembic heads` after each merge to confirm chain integrity before merging the next.
3. Apply the `all-context.md` migration-chain + flag-inventory delta above **once**, on `main`, after
   all 3 branches are merged (re-confirm the real chain order per the caveat above).
4. Apply the umbrella `## Current Execution State` delta above **once**, on `main`.
5. Only then: begin the wild kill test operator steps for WS1 and WS3 (see each workstream's own
   backlog note — WS3's is `ws3-wild-kill-test_NOTE_31-07-26.md` in this same folder) once WS0's
   exit metric is confirmed live in production.

## Cross-Reference

- WS3 phase report: `process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/ws3-agent-concierge-phase_REPORT_31-07-26.md`
- WS3 wild-kill-test known-gap: `process/features/agent-native-revenue/backlog/ws3-wild-kill-test_NOTE_31-07-26.md`
- WS2 dormancy: Claude cross-session memory note `agent-native-revenue-ws2-dormant.md` (2026-07-30)
