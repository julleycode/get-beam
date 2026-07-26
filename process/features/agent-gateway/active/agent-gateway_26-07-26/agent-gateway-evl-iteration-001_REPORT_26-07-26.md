---
name: report:agent-gateway-evl-iteration-001
description: "EVL cycle 1 — agent-gateway Phase 1+2: full-unit-lane failure caught by independent EVL run (rate-limiter test isolation)"
date: 26-07-26
metadata:
  node_type: memory
  type: report
  feature: agent-gateway
  phase: "P1-P2"
  loop: evl
  cycle: 1
---

# EVL Iteration 001 — agent-gateway Phase 1+2

**Plan:** `agent-gateway_PLAN_26-07-26.md`
**Loop:** execute-validate-fix (EVL), domain `tests`
**Driver:** orchestrator (vc-autoresearch bookkeeping)

## Why this cycle exists

vc-execute-agent reported `PHASE_COMPLETE: EXECUTE` with "full unit lane PASS — 676 passed, 2
skipped". The independent EVL run (vc-tester) contradicted it:

```
.venv/bin/python3.11 -m pytest tests/unit -q
→ 1299 passed, 2 skipped, 5 FAILED
```

Two discrepancies:

1. **5 real failures** the execute-agent did not report.
2. **Test count mismatch** (676 vs 1299) — consistent with other concurrent sessions landing test
   files in this repo between the two runs. Worth noting for future EVL passes: an execute-agent's
   remembered totals are not a reliable baseline in a repo with concurrent agent sessions.

This is exactly the failure mode the EVL gate exists to catch — an execute-agent's internal
"iterate until green" loop is not a substitute for an independent confirmation run.

## The failure

All 5 failures in `tests/unit/test_agent_mcp.py`:

- `test_oversized_body_rejected_with_forged_content_length`
- `test_body_just_under_cap_is_accepted`
- `test_oversized_request_id_is_not_reflected`
- `test_structured_request_id_is_not_reflected`
- `test_normal_scalar_request_id_is_echoed`

Reproducible across 2 consecutive full-suite runs — **deterministic, not flaky**. The same file
passes **31/31 in isolation**.

**Root cause (EVL diagnosis):** the slowapi rate limiter guarding the `/mcp` route holds shared
in-process state. Earlier test files exhaust the `60 per 1 minute` budget, so by the time
`test_agent_mcp.py` runs these requests receive `429` where the test expects `200`.

**Classification:** test-isolation gap, NOT a logic defect in the gateway. The production rate limit
is a validate-contract requirement (E3) and must NOT be weakened to make tests pass.

## Gates that DID pass in the EVL run

| Gate | Result |
|---|---|
| Targeted agent-gateway tests in isolation | PASS 64/64 |
| Guardrail regression (`test_agent_origin_exclusion` + `test_outbound_identity_gate`) | PASS 36/36 |
| `cd apps/web && npm run build` | PASS |
| Migration offline `--sql`, explicit ranges both directions | PASS |
| `alembic heads` | Single head `a4f7c2e9d31b`, parent `e6b2d4a1c837` confirmed |
| Migration live round-trip | KNOWN-GAP — Docker unavailable, not faked |

## Independent boundary audit (did not trust the execute-agent's claim)

- `git status --porcelain` on `identity_classification.py`, `visitor_email.py`,
  `identity_resolver.py`, `middleware.ts` → clean, none modified.
- `MCP_TOOLS` exposes read tools only; `test_no_write_or_action_tool_is_exposed_in_phase_2` passes.
- Unknown/foreign site returns **404, never 403** — asserted by passing tests in all three routers.

Phase 3 / Phase 4 remain unimplemented and untouched, as required.

## Fix dispatched

vc-execute-agent (opus), scoped to `tests/unit/test_agent_mcp.py` isolation only, with explicit
instructions to reuse any existing limiter-reset pattern already in the suite and to NOT weaken the
production rate limit.

## Next

Re-spawn vc-tester to re-run gates 1–3 after the fix. Cycle 2 only if failures remain.
