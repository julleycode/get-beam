---
name: report:ws3-agent-concierge-phase
description: "WS3 Agent Concierge — phase report: CODE DONE, EVL-green, AC-WS3-5/6 WS0-gated known-gap"
date: 31-07-26
metadata:
  node_type: memory
  type: report
  feature: agent-native-revenue
  phase: WS3
---

# WS3 — Agent Concierge — Phase Report

```yaml
phase: ws3-agent-concierge
date: 2026-07-31
status: COMPLETE_WITH_GAPS
feature: agent-native-revenue
plan: process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/ws3-agent-concierge_PLAN_30-07-26.md
```

## What Was Done

Flipped the existing read-only MCP gateway (`agent_mcp.py` / `agent_gateway.py`) from give-away-free
to trade-for-qualification, and added a genuine zero-click conversion path, per Steps 1-4 of the
plan:

- **Step 1 — `initialize` handshake.** Added a static, spec-shaped `initialize` JSON-RPC method to
  the existing dispatcher (no dynamic internal/version data leak); reused Gate 1 (tenancy/flags) and
  added it to the Gate 4 method allow-list.
- **Step 2 — param-gated tools + qualified content.** `get_offers`/`get_pricing`/`check_availability`
  now require `use_case`/`company_size`/`evaluating_against`; missing params degrade to a
  `needs_more_info` JSON-RPC *result* (not `-32602` — `-32602` reserved for malformed/wrong-typed
  params only, per AC-WS3-1). New `AgentProfile.qualified_content` JSONB column (migration
  `b4d9e1a7c052`) feeds a qualified pricing/comparison/security answer once params are complete.
  Qualification param values sanitized via `prompt_safety.clean_text` per-field (not
  `sanitize_profiles`, which doesn't cover these 3 fields — VALIDATE P1 correction).
- **Step 3 — conversion tool + isolated lead table + 3 must-fixes.** New `request_quote`/`book_demo`
  tools write an `AgentLead` row (migration `c5e0f2b8d163`, alongside `AgentToolCall` for metrics) —
  **zero imports of `IdentifiedVisitor`/`Visitor`, no `visitor_id` column** (structural isolation
  guarantee). Fail-open owner notification via `agent_lead_notify.py`
  (`email_sender.send(..., custom_args=...)`, monkeypatch-mocked in tests per this repo's
  established `daily_digest.py`/`outcome_digest.py` convention — no runtime `MOCK_EXTERNAL_APIS`
  branch, since `email_sender.py` has none). Company resolution is **free-only** (Must-Fix 3):
  `IdentityResolver.resolve()` / `run_company_resolution_sweep()` (the paid multi-provider waterfall)
  is never invoked synchronously from the request handler — resolved via a read-only lookup only,
  closing a self-discovered budget-exhaustion/DoS vector on this public unauthenticated write path.
  Dedicated tighter rate limit on the conversion tool via a manual `limiter.hit(...)` call in a
  distinct `"mcp_conversion_tool"` namespace (not a second route-level decorator — slowapi decorators
  apply to the whole route). Both `agent_concierge_qualification_enabled` and
  `agent_concierge_conversion_enabled` flags added to `config.py`, **default OFF**.
- **Step 4 — kill-test metrics + report helper.** New `AgentToolCall` table records
  discovery/call/param-fill signals the instant a concierge flag is ON. New
  `apps/api/services/agent_kill_test_report.py::assemble_kill_test_report()` — pure read-only
  aggregate (tool-discovery rate, tool-call rate, param-fill rate, lead-event count), unit-tested
  against a seeded fixture.
- **Security-review fix cycle** (post-EXECUTE, pre-EVL-final): `vc-code-reviewer` found H1 (HIGH) +
  M1/M2/M3/M4 (MEDIUM) + 3 LOW. All 5 fixed with proving tests, no new migration required:
  - **H1** — streaming body-size guard (`IngestBodySizeLimitMiddleware` pattern) extended to cover
    `/mcp` (closes a chunked-transfer DoS the original body cap missed on this route).
  - **M1** — read-tool metric write reordered to after the tool result is constructed (was causing
    an ORM-expiry 500 under certain session-state orderings).
  - **M2** — resolved rDNS domain sanitized before it is stored or interpolated into the
    notification email (closing a second injection surface distinct from the 3 qualification
    params).
  - **M3** — per-site daily cap + Redis-TTL idempotency added to the conversion tool path (defense
    against slow-drip abuse under the rate limit's per-minute window; deliberately Redis-TTL rather
    than a new migration/column).
  - **M4** — only *complete* conversion calls (all 3 params present) consume the tight rate budget —
    prevents an attacker from exhausting the conversion budget with incomplete calls that don't even
    produce a lead.
- **Kill-test report helper** — pure function, arithmetic-tested; no new API route added (per plan's
  default-to-no-new-route guidance — confirmed not needed for this cycle).

**Commits:** `2ba89bb` (Step 1-4 code) → `0d55e1a` (plan + backlog note docs) → `d4da9d1` (security
fix cycle: H1/M1/M2/M3/M4, code + proving tests).

## What Was Skipped/Deferred

- **AC-WS3-5 / AC-WS3-6** (the wild kill test itself: >=20 real wild ChatGPT/Claude queries over 1
  week on 1 pilot site, and the signed GO/NO-GO verdict from that data) — explicitly WS0-gated and
  out of this plan's buildable scope per the plan's own Step 5. Backlog note already written:
  `process/features/agent-native-revenue/backlog/ws3-wild-kill-test_NOTE_31-07-26.md` (dependency
  edge: `AC-WS3-5/6 ⟵ blocks-on ⟵ AC-WS0-5`, WS0's handoff exit metric on production).
- Live migration apply (both new migrations offline-`--sql`-validated only, per program hard stop —
  no live apply in this plan's scope).
- Flipping either new flag ON in any real environment (program precedent: code-complete + flag-OFF
  is the EXECUTE finish line, not live enablement).

## Test Gate Outcomes

Two EVL confirmation runs (orchestrator-driven, independent of execute-agent's internal claims):

| Run | Gate | Command | Result |
|---|---|---|---|
| 1 (post-Step-1-4 EXECUTE) | unit full suite | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` | green |
| 1 | WS3 integration | `.venv/bin/python3.11 -m pytest tests/integration/test_agent_mcp_concierge.py -m integration -q` | green (12 Hybrid gates) |
| 1 | emailability regression | `.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q` | green, 0 new failures |
| 1 | migration offline validate | `alembic heads` + `upgrade <head>:head --sql` / `downgrade head:<head> --sql`, explicit rev-range | clean both directions |
| 2 (post security-fix-cycle EVL-final) | unit full suite | same | **1451 passed**, no regression |
| 2 | WS3 integration | same | **66 passed**, no regression |
| 2 | migration head | `alembic -c apps/api/alembic.ini heads` | single head `c5e0f2b8d163`, no branching |
| 2 | guardrail check (code-read) | manual inspection: `AgentLead` imports, `is_emailable_identity` call sites, no synchronous `IdentityResolver.resolve()` call in `request_quote`/`book_demo` path | confirmed intact |

Zero EVL fix cycles were needed on the second (final) EVL run — the security-review fix commit
(`d4da9d1`) landed green on first confirmation.

## Plan Deviations

- **Must-Fix 3 added at VALIDATE, not in the original plan draft.** VALIDATE's Layer-2 security
  fan-out discovered a synchronous-paid-waterfall budget-exhaustion vector (calling
  `IdentityResolver.resolve()`/`run_company_resolution_sweep()` inline from an unauthenticated
  public write endpoint) that the plan draft had not anticipated — the plan assumed a
  `record_gateway_visit()` function that does not exist in this codebase. Resolved via a new
  mandatory constraint (free-only lookup or deferred-to-async-sweep) plus a new Fully-Automated test
  gate (`no_sync_waterfall`). This is documented in-plan (`## Validate Contract`, Plan Update P2 /
  Must-Fix 3) and confirmed closed in EXECUTE.
- **`sanitize_profiles` → `clean_text` correction (P1).** The plan initially named
  `sanitize_profiles` for the 3 new qualification-param fields; VALIDATE found this would silently
  no-op (the function's fixed field-cap table doesn't include these 3 field names). Execution used
  `clean_text` per-field, as corrected in-plan.
- **`MOCK_EXTERNAL_APIS` assumption corrected (P5).** Plan assumed `email_sender.py` had a runtime
  mock short-circuit; VALIDATE found it does not. Tests use the established
  `monkeypatch.setattr(EmailSender, "send", ...)` pattern instead, matching
  `daily_digest.py`/`outcome_digest.py` precedent.
- **Security-review fix cycle (5 findings, post-plan).** Not anticipated in the original VALIDATE
  pass — `vc-code-reviewer`'s adversarial pass on the merged code found H1/M1/M2/M3/M4, all fixed
  without a new migration (Redis-TTL idempotency chosen over a schema column for M3).
- **Metrics landed on a dedicated `AgentToolCall` table**, not folded into `AgentFetchEvent` columns
  as the plan's Step 4 originally sketched — this resolves the plan's own flagged open question (P4:
  `AgentFetchEvent.vendor` NOT NULL constraint has no sensible value for an MCP JSON-RPC caller with
  no classifiable UA) by avoiding the shoehorn entirely. Confirmed acceptable per the plan's own
  "Either is acceptable" framing in Step 4.2.

No other material deviations from the plan's Steps 1-4.

## Test Infra Gaps Found

None discovered this phase beyond what the plan itself already flagged (AC-WS3-5/6's wild-data
gate, which is a real-world-wait gap, not a test-infrastructure gap).

## SPEC Achievement

| AC | Criterion | Status | Proving gate |
|---|---|---|---|
| AC-WS3-1 | Param-gated tools; `needs_more_info` vs `-32602` distinction | **met** | Hybrid integration + Fully-Automated malformed-param unit test |
| AC-WS3-2 | Zero-click conversion tool creates lead + notifies owner, fail-open | **met** | Hybrid integration (mocked `EmailSender.send`) |
| AC-WS3-3 | Lead resolves to real company wherever possible (free-only) | **met** | Hybrid integration |
| AC-WS3-4 | No lead ever becomes emailable / merges into identity graph outside this consent path | **met** | Fully-Automated regression (`test_agent_origin_exclusion.py`) + new isolation unit test |
| AC-WS3-5 | >=20 real wild ChatGPT/Claude queries over 1 week, 1 pilot site | **unmet — known-gap** | Agent-Probe (needs-live-provider), WS0-gated; backlog note `ws3-wild-kill-test_NOTE_31-07-26.md` |
| AC-WS3-6 | Signed GO/NO-GO verdict from AC-WS3-5's data | **unmet — known-gap** | Same backlog note (depends on AC-WS3-5) |
| MF-1 | Dedicated tighter conversion-tool rate limit | **met** | Hybrid integration |
| MF-2 | Sanitization of all 3 qualification params, end-to-end | **met** | Hybrid integration (hostile-string injection test) |
| MF-3 | Never synchronously call the paid identity waterfall from the conversion tool | **met** | Fully-Automated unit (call-count assertion) |
| H1/M1/M2/M3/M4 (security-review) | Body-size guard on `/mcp`, metric-write ordering, domain sanitization, daily-cap+idempotency, complete-only rate consumption | **met** | `tests/unit/test_agent_mcp_review_fixes.py` (435 lines, new) |

**## SPEC Gaps:** AC-WS3-5 and AC-WS3-6 remain unmet — both are recorded, dated known-gaps (not
silently dropped), routed to
`process/features/agent-native-revenue/backlog/ws3-wild-kill-test_NOTE_31-07-26.md`, and explicitly
gated on `AC-WS0-5` (WS0's production handoff exit metric) plus a real 1-week wild-traffic
observation window that cannot be produced inside a PLAN/EXECUTE/VALIDATE cycle. This is why the
plan's classification is **CODE DONE, NOT VERIFIED** — not archivable per program guardrail 3 (see
Closeout Packet below).

## Closeout Packet

1. **Selected plan path:** `process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/ws3-agent-concierge_PLAN_30-07-26.md`
2. **Closeout classification:** **Keep in active/testing** — CODE DONE (Steps 1-4 lab-green), NOT
   VERIFIED (AC-WS3-5/6 wild kill test is WS0-gated and requires a real 1-week production
   observation window this plan cannot produce). Program guardrail 3 explicitly forbids marking this
   plan `✅ VERIFIED` before then.
3. **What was finished:** Steps 1-4 (initialize handshake, param-gated tools + qualified content,
   conversion tool + isolated lead table + 3 must-fixes, kill-test metrics + report helper) plus a
   full 5-item security-review fix cycle (H1/M1/M2/M3/M4). See §What Was Done above.
4. **Verified vs unverified:** Verified — 1451 unit + 66 WS3 integration tests green across 2 EVL
   confirmation runs, single migration head, emailability-isolation regression clean, guardrails
   confirmed intact by code-read. Unverified — real-MCP-client behavior (ChatGPT Developer
   Mode/Claude) against actual wild traffic (AC-WS3-5/6); production data-migration live-apply.
4b. **Validate-contract compliance:** present, inline in the plan (`## Validate Contract`, Gate:
   CONDITIONAL, `generated-by: inner-pvl: WS3`). Accepted per-session; Must-Fix 3 added and closed
   during EXECUTE. No unresolved FAILs.
5. **Cleanup done vs still needed:** Done — plan file, backlog note (Step 5 known-gap), this phase
   report, all written into the task folder. Still needed — this consolidation note
   (`program-branch-consolidation_NOTE_31-07-26.md`, written alongside this report) capturing the
   `all-context.md`/umbrella deltas that must land on `main` once the 4 program branches converge
   (this branch cannot edit those files directly — see task instructions).
6. **Single best next valid state:** Keep `ws3-agent-concierge_PLAN_30-07-26.md` in `active/` on
   this branch. Do NOT archive. Next action is branch consolidation (WS0 → main, then WS1/WS2/WS3
   merge/rebase), after which the wild kill test (Step 5) can begin once WS0's exit metric is live.
7. **Commit-checkpoint recommendation:** Process commit belongs after this UPDATE PROCESS pass — the
   remaining changes are exclusively this phase report + the consolidation note (both `process/`
   docs, no source). The 3 execution commits (`2ba89bb`/`0d55e1a`/`d4da9d1`) are already made;
   nothing further needs a source commit this session.
8. **Regression status:** `test_agent_origin_exclusion.py` (the program's highest-priority
   emailability guardrail) re-run clean both EVL passes, 0 new failures. Full unit suite (1451
   tests) re-run clean on the final EVL pass — no regression against any other program surface.
9. **SPEC achievement:** see §SPEC Achievement above — 8 of 10 WS3 criteria (including all 3
   must-fixes) **met**; 2 (**AC-WS3-5/6**) **unmet**, recorded as known-gaps routed to backlog, not
   silently dropped.

## Forward Preview

#### Test Infra Found
- `tests/integration/test_agent_mcp_concierge.py` (new) — 12 Hybrid gates for the MCP concierge
  surface (param-gate, conversion tool, company resolution, rate limit, sanitization, flag-gating,
  initialize handshake, isolation).
- `tests/integration/test_agent_mcp_concierge_no_sync_waterfall.py` (new) — MF-3's call-count
  assertion, pure monkeypatch, no live DB/network.
- `tests/unit/test_agent_kill_test_report.py` (new) — arithmetic test for the report helper.
- `tests/unit/test_agent_mcp_review_fixes.py` (new, 435 lines) — the 5 security-review fixes.

#### Blast Radius Changes
- Vs. plan's stated 11 direct touchpoints: actual diff touches `apps/api/config.py`,
  `apps/api/main.py` (new — the H1 body-size-guard extension, not originally in the touchpoints
  table), 2 new migrations, `apps/api/models/agent_lead.py` (new), `apps/api/models/agent_tool_call.py`
  (new — the plan's Step 4 originally sketched columns on existing tables; landed as its own table
  instead), `apps/api/models/agent_profile.py`, `apps/api/routers/agent_mcp.py`,
  `apps/api/schemas/agent_gateway.py`, `apps/api/services/agent_gateway.py`,
  `apps/api/services/agent_kill_test_report.py` (new), `apps/api/services/agent_lead_notify.py`
  (new — the plan's touchpoints table implied notification logic would live inline in
  `agent_mcp.py`; landed as its own module instead). Net: 14 files changed across the 3 commits,
  1974 insertions / 33 deletions total (per `git show --stat`).
- No change to `IdentifiedVisitor`, `Visitor` write paths, `identity_classification.py` logic, any
  auth/session surface, billing/credits — confirmed by diff scope.

#### Commands to Stay Green
- `.venv/bin/python3.11 -m pytest tests/unit -m unit -q`
- `.venv/bin/python3.11 -m pytest tests/integration/test_agent_mcp_concierge.py -m integration -q` (precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`)
- `.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q` (emailability regression — run before ANY future change touching agent/identity surfaces)
- `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` (confirm single head `c5e0f2b8d163` before any new migration on this branch)

#### Dependency Changes
None — no new third-party dependency was added this phase (Redis-TTL idempotency for M3 reused the
existing Redis client; no new package).
