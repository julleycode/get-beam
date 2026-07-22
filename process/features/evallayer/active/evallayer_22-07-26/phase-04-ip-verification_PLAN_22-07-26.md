---
name: plan:evallayer-phase-04-ip-verification
description: "EvalLayer — Phase 04: IP-range/rDNS verification + confidence field (OpenAI/Perplexity published ranges; Anthropic stays UA-only; mock path)"
date: 22-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-04
---

# Phase 04 — IP/rDNS Verification

**Program:** evallayer
**Umbrella plan:** process/features/evallayer/active/evallayer_22-07-26/evallayer-umbrella_PLAN_22-07-26.md
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/evallayer/active/evallayer_22-07-26/phase-04-ip-verification_REPORT_22-07-26.md

---

## Purpose

Upgrade agent-visit confidence beyond UA-only by cross-checking published vendor IP ranges
(OpenAI: gptbot.json/chatgpt-user.json/searchbot.json; Perplexity: perplexitybot.json/
perplexity-user.json), mirroring `company_resolver.py`'s async/cached/fail-open IP-classification
pattern. Anthropic (Claude) publishes no IP ranges by design and must never exceed `ua-only`
confidence regardless of IP. Ships with a `MOCK_EXTERNAL_APIS=true` deterministic fixture path
(SPEC AC14).

---

## Entry Gate

- Phase 2 exit gate passed (agent visits are classified and persisted).
- Parallel-safe with Phase 3 — disjoint blast radius (verification service vs. read API/dashboard).

---

## Blast Radius

- `apps/api/services/agent_verification.py` (or equivalent — new)
- Static vendor IP-range JSON fixtures (real OpenAI/Perplexity data + mock fixtures) — new
- `apps/api/config.py` (verification-related flags/toggles)

---

## Implementation Checklist

### Step A — Verification service

- [ ] A1. Build async/cached/fail-open IP-range verification mirroring `company_resolver.py`'s
      `classify_org_kind`/`is_datacenter_ip` pattern.
- [ ] A2. Confirm Anthropic/Claude traffic is structurally excluded from ever reaching
      `ip-verified` — hardcode the "no published ranges" constraint, not an incidental omission.
- [ ] A3. Run verification async/best-effort AFTER the synchronous UA-only classification (SPEC
      Resolved Open Question 2) — never add latency to the `/ingest` hot path.

### Step B — Mock path

- [ ] B1. Build deterministic mock fixtures for OpenAI/Perplexity IP ranges under
      `MOCK_EXTERNAL_APIS=true` (SPEC AC14).
- [ ] B2. Static vendor-list dataset checked into repo (SPEC Resolved Open Question 6) — refreshed
      by a scheduled task; new/unconfirmed vendors (Amazonbot, cohere-ai) tracked as backlog, not
      built in v1.

---

## Exit Gate

```bash
# Mock IP-range verification upgrades confidence (AC8)
{command}
# Expected: matching mocked IP -> confidence upgraded to ip-verified

# Anthropic ceiling (AC8)
{command}
# Expected: ClaudeBot-UA visit never exceeds ua-only regardless of IP

# Mock mode coverage (AC14, this phase's external call)
{command}
# Expected: unit tests run fully offline under MOCK_EXTERNAL_APIS=true
```

- All exit-gate criteria pass; live-provider (non-mocked) verification remains explicitly
  Agent-Probe/Known-Gap per SPEC AC8 note — not required for this phase's VERIFIED status.
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Phase 2 exit gate not yet passed (no classified visits to verify).
- No real vendor IP-range fixture available and mock-only path insufficient for confidence in
  correctness (should not block VERIFIED per SPEC, but must be documented as Known-Gap, not
  silently dropped).

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

**Validate-contract required before execute.** New external-call surface — VALIDATE may never be
skipped for this phase.

---

## Touchpoints

- `apps/api/services/agent_verification.py` (new)
- Static vendor IP-range JSON fixtures (new)
- `apps/api/config.py`

---

## Public Contracts

- No new externally-visible API surface — this phase enriches the confidence field already
  exposed by Phase 3's `/agents` API; no shape change to that contract.

---

## Verification Evidence

```bash
# {verification command — run after phase complete, exact command written at PLAN step}
{command}
# Expected: {expected output}
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/evallayer_22-07-26/phase-04-ip-verification_PLAN_22-07-26.md`
- Last completed step: not started
- Validate-contract status: pending
- Next step: Confirm Phase 2 exit gate passed, then spawn vc-research-agent for RESEARCH (Step 1);
  may run in parallel with Phase 3.

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
