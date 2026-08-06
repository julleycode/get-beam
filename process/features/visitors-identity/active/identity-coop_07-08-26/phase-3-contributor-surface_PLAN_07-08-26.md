---
name: plan:identity-coop-phase-3-contributor-surface
description: "Identity Co-op — Phase 3: self-scoped contributor stats endpoint, opt-in acceptance flow, and model privacy-policy language"
date: 07-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: phase-3
---

# Phase 3 — Contributor Surface + Opt-In UX

**Program:** identity-coop
**Umbrella plan:** `process/features/visitors-identity/active/identity-coop_07-08-26/identity-coop-umbrella_PLAN_07-08-26.md`
Complexity: COMPLEX (phase of a 3-phase program)
Phase status: ⏳ PLANNED
Status: ⏳ PLANNED
Date: 07-08-26
**Report destination:** `process/features/visitors-identity/active/identity-coop_07-08-26/phase-3-contributor-surface_REPORT_07-08-26.md`

**TL;DR** — Make the co-op visible and joinable: a self-scoped stats endpoint (counts only, zero
cross-tenant PII), a dashboard panel, and an opt-in flow that shows the model privacy-policy
language and records an immutable acceptance before the flag can flip ON.

---

## Overview

See Purpose below for the narrative; this phase is one leg of the identity-coop phase program.
Ordering, gates, and program state live in the umbrella plan.

---

## Purpose

Phases 1-2 built a co-op nobody can see or join. This phase adds the two surfaces that make it a
product: the contributor stats view (AC-11) and the opt-in acceptance flow (AC-10). Both are
deliberately last — a stats surface built before spend/expiry existed would display numbers whose
meaning later changed.

---

## Entry Gate

- Phase 2 exit gate passed: consumption aggregation, spend, and expiry all proven; AC-8 reconciliation green.
- Fresh RESEARCH pass confirms the `auto_identify_enabled` 7-layer wiring precedent is still the
  current dashboard toggle shape.

---

## Precedents To Follow Exactly

| Layer | Precedent to imitate |
|---|---|
| Model | `Site.auto_identify_enabled` (`apps/api/models/site.py`) |
| Migration | `b7e1a2c9d4f0_add_auto_identify_enabled.py` |
| Schema | `apps/api/schemas/sites.py` |
| Router | `apps/api/routers/sites.py` |
| Service | `apps/api/services/identity_coop.py` |
| Dashboard toggle | `apps/web/src/app/dashboard/visitors/page.tsx` (the `auto_identify_enabled` toggle block) |
| API types/client | `apps/web/src/lib/api-types.ts` + `apps/web/src/lib/api.ts` |
| Endpoint shape | `GET /api/v1/sites/{site_id}/ingest-health` (`apps/api/routers/ingest_health.py`) — tenant-scoped, counts/ratios only, no PII |

Layers 1-4 for the flag itself landed in Phase 1. This phase adds the endpoint plus layers 6-7 (UI).

---

## Blast Radius

Risk class: **multi-tenancy (data isolation) + billing/credits display**. Hybrid gate minimum.

- `apps/api/routers/identity_coop.py` (NEW — stats endpoint)
- `apps/api/main.py` (MODIFIED — router registration)
- `apps/api/schemas/identity_coop.py` (NEW — response models)
- `apps/api/services/identity_coop.py` (MODIFIED — stats assembly function, read-only)
- `apps/api/routers/sites.py` (MODIFIED — acceptance-flow surface: expose current `terms_version`)
- `apps/api/services/coop_terms.py` (NEW — model policy text + its immutable snapshot hash)
- `apps/web/src/app/dashboard/visitors/page.tsx` (MODIFIED — opt-in panel + stats card)
- `apps/web/src/lib/api-types.ts`, `apps/web/src/lib/api.ts` (MODIFIED)
- `tests/integration/test_identity_coop_stats.py` (NEW)
- `tests/unit/test_coop_terms.py` (NEW)

~10 files. No migration expected in this phase; no `identity_resolver.py` change.

---

## Endpoint Contract

`GET /api/v1/sites/{site_id}/coop-stats`

```
{
  "contribution_enabled": bool,
  "terms_version_accepted": str | null,
  "accepted_at": datetime | null,
  "contribution_count": int,          // period-scoped, excluded_reason IS NULL only
  "consumption_count": int,           // graph-served identifications for THIS site
  "credit_balance": int,              // spendable now (past hold, unexpired)
  "credit_pending_hold": int,         // accrued but inside the 24h hold
  "credit_expiring_30d": int,
  "ledger": [ { "entry_type", "amount", "reason", "created_at" } ]   // this site only, paginated
}
```

**Hard rules:**
- Every query filters `Site.user_id == current_user.id`. A foreign or unknown `site_id` returns
  **404**, never 403 — do not leak id existence.
- Counts and integers only. **Zero** cross-tenant data, zero emails, zero blind indexes, zero
  `email_bidx` values in the response or in any log line.
- Read-only. This endpoint must never write, accrue, spend, or expire anything.

---

## Model Policy Language (AC-10)

- Lives in `apps/api/services/coop_terms.py` as a module constant, with
  `COOP_TERMS_VERSION = sha256(COOP_TERMS_TEXT)[:16]` — an **immutable snapshot hash of the exact
  text**, computed at import, never a live pointer to editable copy.
- Changing the text changes the hash, so an old acceptance never silently covers new terms.
- The text states the customer's obligation: they will obtain their own visitors' consent to
  cross-tenant sharing and offer those visitors an opt-out. Beam supplies the language; the
  customer adopts it. **Beam's own pixel consent banner is NOT modified** (locked decision #3).
- The text carries a visible "not legal advice; review with your own counsel" line, and the phase
  report must record that qualified privacy-counsel review remains a hard prerequisite for
  production enablement.

---

## Implementation Checklist

### Step A — Terms module

- [ ] A1. Create `apps/api/services/coop_terms.py` with `COOP_TERMS_TEXT` (the model policy language) and `COOP_TERMS_VERSION` derived as a truncated sha256 of that text.
- [ ] A2. `tests/unit/test_coop_terms.py::test_version_is_content_hash` — mutating the text changes the version; the version is stable across imports.
- [ ] A3. `tests/unit/test_coop_terms.py::test_terms_text_states_required_obligations` — assert the text contains the consent-obtaining obligation, the opt-out obligation, and the not-legal-advice notice.

### Step B — Stats service + endpoint

- [ ] B1. Add `async def coop_stats(db, site_id, *, period) -> dict` to `apps/api/services/identity_coop.py`, composing `contribution_count`, `consumption_count`, `spendable_balance`, pending-hold and expiring-30d aggregates from Phases 1-2. Read-only.
- [ ] B2. Create `apps/api/schemas/identity_coop.py` with the Pydantic response models matching the Endpoint Contract above.
- [ ] B3. Create `apps/api/routers/identity_coop.py` implementing `GET /api/v1/sites/{site_id}/coop-stats`, modeled on `apps/api/routers/ingest_health.py`. Resolve the site with `Site.user_id == user.id`; raise 404 on miss.
- [ ] B4. Register the router in `apps/api/main.py`.
- [ ] B5. Verify no structlog call in this path logs PII — keys/ids only.

### Step C — Acceptance flow (backend surface)

- [ ] C1. Expose the current `COOP_TERMS_VERSION` and the full terms text via the site read response (or a dedicated `GET /api/v1/coop/terms`), so the UI can render exactly what will be accepted.
- [ ] C2. Confirm the Phase 1 guard still holds: `contribution_enabled=True` is rejected unless a matching `terms_version` is supplied and an acceptance row is written in the SAME transaction. Add a regression test if Phase 1's test did not cover a stale/unknown `terms_version`.
- [ ] C3. Reject an acceptance whose `terms_version` does not equal the current `COOP_TERMS_VERSION` — an old acceptance cannot activate under new terms.

### Step D — Dashboard (layers 6-7)

- [ ] D1. Add `contribution_enabled`, the coop-stats response type, and the terms payload to `apps/web/src/lib/api-types.ts`; add the client calls to `apps/web/src/lib/api.ts`.
- [ ] D2. Add a "Identity Co-op" panel to `apps/web/src/app/dashboard/visitors/page.tsx`, following the existing `auto_identify_enabled` toggle block structure.
- [ ] D3. The toggle must not flip optimistically: turning it ON opens a modal showing the model policy language, requires an explicit acknowledgement action, and only then issues the PATCH carrying `terms_version`. Turning it OFF is a plain PATCH.
- [ ] D4. Render contribution count, consumption count, credit balance, pending-hold, and expiring-soon. Show ledger history as a simple table.
- [ ] D5. Empty/flag-off state: when `identity_coop_enabled` is globally OFF, render an explanatory state rather than zeros that look like a bug (follow the `/dashboard/agents` `detection_enabled` empty-state branching precedent).
- [ ] D6. `cd apps/web && npm run lint` clean.

### Step E — Tests

- [ ] E1. `tests/integration/test_identity_coop_stats.py::test_stats_are_self_scoped` — called with Site A's auth, the endpoint returns ONLY Site A's numbers even while Site B has active ledger and contribution rows (**AC-11**).
- [ ] E2. `tests/integration/test_identity_coop_stats.py::test_foreign_site_id_returns_404` — a `site_id` belonging to another user returns 404, never 403, and the body leaks no existence signal (**AC-11**).
- [ ] E3. `tests/integration/test_identity_coop_stats.py::test_stats_response_contains_no_pii` — assert no email, no `email_bidx`, no visitor identifier appears anywhere in the serialized response.
- [ ] E4. `tests/integration/test_identity_coop_stats.py::test_flag_on_requires_acceptance_in_same_transaction` — PATCH setting `contribution_enabled=True` without `terms_version` is rejected and writes NO acceptance row and NO flag change (**AC-10 automated leg**).
- [ ] E5. `tests/integration/test_identity_coop_stats.py::test_stale_terms_version_rejected` — an acceptance carrying an outdated `terms_version` is rejected.
- [ ] E6. `tests/integration/test_identity_coop_stats.py::test_stats_endpoint_writes_nothing` — snapshot row counts of all three co-op tables before and after the call; assert unchanged.
- [ ] E7. **Agent-Probe (AC-10 judgment leg):** a reviewer reads `COOP_TERMS_TEXT` plus the rendered acceptance modal copy and judges whether they convey the intended contractual meaning (customer obtains visitor consent; customer offers opt-out; Beam supplies language only). Record the judgment verbatim in the phase report. This is NOT a Known-Gap — it is a proving strategy, and its outcome must be recorded.

---

## Exit Gate

```bash
# Unit lane
.venv/bin/python3.11 -m pytest tests/unit -m unit -q
# Expected: exit 0

# Integration lane
.venv/bin/python3.11 -m pytest tests/ -m integration -q
# Expected: exit 0, including all 6 new stats/acceptance tests

# Web lint
cd apps/web && npm run lint
# Expected: exit 0

# Read-only guard — this phase touches neither the resolver nor the ledger write path
git diff apps/api/services/identity_resolver.py
# Expected: EMPTY
```

- All checklist items checked.
- AC-11 self-scoping and 404-not-403 both proven.
- AC-10 automated leg green AND the Agent-Probe judgment recorded in the phase report.
- Phase report explicitly restates that qualified privacy-counsel review remains a hard
  prerequisite for production enablement, and that all flags remain OFF.

---

## Acceptance Criteria

- **AC-10** — `contribution_enabled` cannot be set ON via API without a matching current `terms_version` and an acceptance row written in the same transaction; a stale terms_version is rejected. Agent-Probe leg: a reviewer confirms the model policy + modal copy convey the intended contractual meaning.
- **AC-11** — the stats endpoint called with Site A's auth returns only Site A's numbers; a foreign site_id returns 404 (never 403); the response contains zero PII.
- The stats endpoint writes nothing (row counts unchanged before/after).
- `COOP_TERMS_VERSION` is an immutable content hash of the exact policy text.
- `cd apps/web && npm run lint` exits 0.
- Beam's pixel-facing consent banner is unchanged.

---

## Phase Completion Rules

- 🔨 **CODE DONE** — all checklist items checked, no test evidence yet.
- 🧪 **TESTING** — pytest lanes + web lint running; failures fixed inline.
- ✅ **VERIFIED** — both pytest lanes exit 0, web lint exit 0, the AC-10 Agent-Probe judgment is
  recorded verbatim in the phase report, and the validate-contract is written (non-placeholder).
- 🚧 **BLOCKED** — Phase 2 exit gate unmet, or the Agent-Probe reviewer judges the policy language
  materially wrong (fix and re-probe; do not ship on an unresolved judgment).
- Playwright auth-harness unavailability ⇒ Known-Gap + backlog stub; gate stays **CONDITIONAL**.
- All flags remain OFF at phase completion; production enablement is out of scope.

---

## Blockers That Would Justify BLOCKED Status

- Phase 2 exit gate not passed (balances would display values whose semantics are unproven).
- Playwright auth-harness gap blocks a browser-level leg of D3 — this is a known repo-wide gap
  (`process/features/pixel/backlog/cadence-bot-flag-deferred-gates_NOTE_26-07-26.md`, ads-audiences
  Phase 1/2). If it blocks: record a Known-Gap + backlog stub, keep the gate **CONDITIONAL**, and
  cover the flow with the integration tests in Step E instead.
- The Agent-Probe reviewer judges the policy language materially wrong — fix the text and re-probe;
  do not ship the surface on an unresolved judgment.

---

## Phase Loop Progress

- [ ] 1. RESEARCH — research-agent: Phase 2 report read; dashboard toggle precedent re-confirmed; test context loaded
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: this plan updated; Inner Loop Refresh Note if sections changed (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** A placeholder `## Validate Contract` = blocked.

---

## Touchpoints

- `apps/api/routers/identity_coop.py` (NEW)
- `apps/api/schemas/identity_coop.py` (NEW)
- `apps/api/services/coop_terms.py` (NEW)
- `apps/api/services/identity_coop.py`
- `apps/api/routers/sites.py`
- `apps/api/main.py`
- `apps/web/src/app/dashboard/visitors/page.tsx`
- `apps/web/src/lib/api-types.ts`
- `apps/web/src/lib/api.ts`
- `apps/api/routers/ingest_health.py` (READ ONLY — endpoint shape precedent)
- `tests/integration/test_identity_coop_stats.py` (NEW)
- `tests/unit/test_coop_terms.py` (NEW)

---

## Public Contracts

- `GET /api/v1/sites/{site_id}/coop-stats` is NEW and additive; no existing endpoint changes shape.
- `PATCH /api/v1/sites/{site_id}` behavior for `contribution_enabled` is unchanged from Phase 1
  (acceptance required to set ON); this phase only adds the terms-version validation.
- Beam's pixel-facing consent banner UNCHANGED.
- Dashboard changes are additive — existing panels and toggles unchanged.
- All flags remain default OFF; nothing in this phase enables the co-op.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_stats_are_self_scoped` | Fully-Automated | AC-11 |
| `test_foreign_site_id_returns_404` | Fully-Automated | AC-11 (multi-tenancy guardrail) |
| `test_stats_response_contains_no_pii` | Fully-Automated | AC-11 / PII guardrail |
| `test_flag_on_requires_acceptance_in_same_transaction` | Fully-Automated | AC-10 (automated leg) |
| `test_stale_terms_version_rejected` | Fully-Automated | AC-10 (terms immutability) |
| `test_stats_endpoint_writes_nothing` | Fully-Automated | Read-only endpoint contract |
| `test_version_is_content_hash` | Fully-Automated | AC-10 (immutable snapshot hash) |
| Reviewer judgment of model policy + acceptance modal copy | Agent-Probe | AC-10 (judgment leg) |
| `cd apps/web && npm run lint` exits 0 | Fully-Automated | Web surface quality gate |
| Browser-level opt-in modal flow | Hybrid (precondition: Playwright auth harness — known repo-wide gap) | AC-10 UX leg; CONDITIONAL if harness unavailable |

---

## Test Infra Improvement Notes

(none identified yet)

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-coop_07-08-26/phase-3-contributor-surface_PLAN_07-08-26.md`
- Last completed step: not started
- Validate-contract status: pending
- Supporting context files loaded: umbrella plan, Phase 1 + Phase 2 plans and reports, `process/context/tests/all-tests.md`
- Next step: confirm Phase 2 exit gate passed, then spawn vc-research-agent for RESEARCH (Step 1)

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
