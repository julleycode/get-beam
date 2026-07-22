---
name: plan:evallayer-phase-03-read-api-dashboard
description: "EvalLayer — Phase 03: Read API /agents + dashboard 'Agents' tab (clone Visitors list/detail/stats)"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-03
---

# Phase 03 — Read API + Dashboard Tab

**Program:** evallayer
**Umbrella plan:** process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/evallayer/active/evallayer_22-07-26/phase-03-read-api-dashboard_REPORT_22-07-26.md

---

## Purpose

Give users a place to see agent visits: a new `/agents` API router (list/detail/stats, structurally
cloning `apps/api/routers/visitors.py` and reusing `verify_site_access`), plus a new top-level
"Agents" dashboard tab (structurally cloning the Visitors list/detail pages and widget shell). Per
SPEC decision D1/nav resolution, this is a separate top-level tab, not a filter on Visitors.

---

## Entry Gate

- Phase 2 exit gate passed (agent visits are persisted and queryable).

---

## Blast Radius

- `apps/api/routers/agents.py` (new)
- `apps/api/schemas/agents.py` (new)
- `apps/web/src/app/dashboard/agents/*` (new — list + detail pages)
- `apps/web/src/app/dashboard/layout.tsx` (new nav item)
- `apps/web/src/lib/api.ts`, `apps/web/src/lib/api-types.ts` (new typed methods/types)

---

## Implementation Checklist

### Step A — Backend read API

- [ ] A1. Create `apps/api/routers/agents.py` cloning `visitors.py`'s list/detail/stats pattern,
      reusing `verify_site_access` (multi-tenancy unchanged: `Site.user_id == user.id`, 404 not 403
      on foreign ids).
- [ ] A2. Create `apps/api/schemas/agents.py` Pydantic response models including the
      verification-method/confidence field.

### Step B — Frontend dashboard tab

- [ ] B1. Add "Agents" `NavItem` to `apps/web/src/app/dashboard/layout.tsx`.
- [ ] B2. Clone `apps/web/src/app/dashboard/visitors/page.tsx` and
      `.../visitors/[visitorId]/page.tsx` structure into `apps/web/src/app/dashboard/agents/*`.
- [ ] B3. Render a confidence/verification-method badge on every agent-visit row/detail (SPEC AC7).

### Step C — Frontend API client

- [ ] C1. Add typed methods to `apps/web/src/lib/api.ts` mirroring `listVisitors`.
- [ ] C2. Add typed types to `apps/web/src/lib/api-types.ts` mirroring `Visitor`.

---

## Exit Gate

```bash
# Tab separation (AC6)
{command}
# Expected: Agents tab shows agent visits only; Visitors tab shows no agent-classified records

# Confidence badge (AC7)
{command}
# Expected: badge renders and matches underlying verification_method field
```

- Both exit-gate criteria (AC6, AC7) pass.
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Phase 2 exit gate not yet passed (no agent-visit data to read).
- Confidence field shape from Phase 1 schema is ambiguous or missing.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: prior phase reports read; test context loaded; plan drift checked
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated; Inner Loop Refresh Note if sections changed (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** New public API surface — VALIDATE may never be
skipped for this phase.

---

## Touchpoints

- `apps/api/routers/agents.py` (new)
- `apps/api/schemas/agents.py` (new)
- `apps/web/src/app/dashboard/agents/*` (new)
- `apps/web/src/app/dashboard/layout.tsx`
- `apps/web/src/lib/api.ts`, `apps/web/src/lib/api-types.ts`

---

## Public Contracts

- New `/agents` API surface (net-new public contract, mirrors `/visitors` shape).
- Existing `/visitors` API and "Visitors" tab behavior unchanged.

---

## Verification Evidence

```bash
# {verification command — run after phase complete, exact command written at PLAN step}
{command}
# Expected: {expected output}
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/evallayer_22-07-26/phase-03-read-api-dashboard_PLAN_22-07-26.md`
- Last completed step: not started
- Validate-contract status: pending
- Next step: Confirm Phase 2 exit gate passed, then spawn vc-research-agent for RESEARCH (Step 1).

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
