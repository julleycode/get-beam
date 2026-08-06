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
- [ ] B3. Create `apps/api/routers/identity_coop.py` implementing `GET /api/v1/sites/{site_id}/coop-stats`, modeled on `apps/api/routers/ingest_health.py`. **Resolve the site via the shared `verify_site_access(db, site_id, user)` helper in `apps/api/dependencies.py`** (the same helper `ingest_health.py` uses) — do NOT hand-roll a second `Site.user_id == user.id` check; reusing the shared helper is what makes the 404-not-403 guarantee structural rather than per-router.
- [ ] B3a. Define the `ledger` array's pagination shape explicitly before EXECUTE: `?limit=<int, default 50, max 200>&cursor=<opaque token | created_at offset>`, newest-first. State the exact param names and default/max in the response schema (B2) and endpoint contract above — do not leave this to execute-agent's judgment; an ad-hoc shape here becomes a breaking change to fix later.
- [ ] B4. Register the router in `apps/api/main.py` (pattern: `app.include_router(identity_coop.router, prefix="/api/v1/sites", tags=["identity-coop"])`, alongside the existing `ingest_health.router` registration).
- [ ] B5. Verify no structlog call in this path logs PII — keys/ids only.

### Step C — Acceptance flow (backend surface)

- [ ] C1. **Decide now, do not leave as an either/or:** expose the current `COOP_TERMS_VERSION` and full terms text by adding `coop_terms_version: str` and `coop_terms_text: str` fields to `SiteOut` in `apps/api/schemas/sites.py` (matches the existing per-field pattern on that schema — e.g. `auto_identify_enabled`). Do NOT add a separate `GET /api/v1/coop/terms` endpoint — a second endpoint is unnecessary surface for two static, non-tenant-scoped values already available wherever the site is read, and it would need its own auth/tenant story for no benefit.
- [ ] C2. **What Phase 1 already enforces (confirm only, no new work):** `contribution_enabled=True` is rejected via the API unless a `terms_version` value is supplied AND an acceptance row is written in the SAME transaction as the flag flip (Phase 1 Step E2). Phase 1's guard checks *presence*, not *correctness* — it has no canonical version to compare against, since `coop_terms.py` does not exist until this phase. Add a regression test in this phase's suite (E4) confirming that behavior still holds against the Phase 1+2 codebase as of this phase's entry.
- [ ] C3. **New work this phase actually adds:** reject an acceptance whose `terms_version` does not exactly equal the current `COOP_TERMS_VERSION` from `coop_terms.py` — this is the first point in the program where a canonical version exists to validate against. An old acceptance (or any string that isn't the live hash) cannot activate the flag. Exact string equality only, no fuzzy/prefix matching.

### Step D — Dashboard (layers 6-7)

- [ ] D1. Add `contribution_enabled`, `coop_terms_version`, `coop_terms_text`, and the coop-stats response type (including the `limit`/`cursor` pagination params from B3a) to `apps/web/src/lib/api-types.ts`; add the client calls to `apps/web/src/lib/api.ts`.
- [ ] D2. Add an "Identity Co-op" panel to `apps/web/src/app/dashboard/visitors/page.tsx`, following the existing `auto_identify_enabled` toggle block's placement/layout conventions only — NOT its `ToggleChip` optimistic-mutate behavior (D3 below is a deliberate, required divergence, not an inconsistency with D2).
- [ ] D3. The toggle must not flip optimistically: turning it ON opens a modal showing the model policy language, requires an explicit acknowledgement action, and only then issues the PATCH carrying `terms_version`. Turning it OFF is a plain PATCH. On PATCH failure (network/validation error), the modal stays open showing the error and the toggle visibly remains OFF — never show ON while the request is unconfirmed or failed.
- [ ] D4. Render contribution count, consumption count, credit balance, pending-hold, and expiring-soon. Show ledger history as a simple table using the B3a pagination params.
- [ ] D5. Empty/flag-off state: when `identity_coop_enabled` is globally OFF, render an explanatory state rather than zeros that look like a bug (follow the `/dashboard/agents` `detection_enabled` empty-state branching precedent — confirmed present at `apps/web/src/app/dashboard/agents/page.tsx`: `stats?.detection_enabled === false ? <specific copy> : <default empty copy>`).
- [ ] D6. `cd apps/web && npm run lint` clean.

### Step E — Tests

- [ ] E1. `tests/integration/test_identity_coop_stats.py::test_stats_are_self_scoped` — called with Site A's auth, the endpoint returns ONLY Site A's numbers even while Site B has active ledger and contribution rows (**AC-11**).
- [ ] E2. `tests/integration/test_identity_coop_stats.py::test_foreign_site_id_returns_404` — a `site_id` belonging to another user returns 404, never 403, and the body leaks no existence signal (**AC-11**).
- [ ] E3. `tests/integration/test_identity_coop_stats.py::test_stats_response_contains_no_pii` — assert no email, no `email_bidx`, no visitor identifier appears anywhere in the serialized response.
- [ ] E4. `tests/integration/test_identity_coop_stats.py::test_flag_on_requires_acceptance_in_same_transaction` — PATCH setting `contribution_enabled=True` without `terms_version` is rejected and writes NO acceptance row and NO flag change (**AC-10 automated leg**; regression-confirms the Phase 1 guard per C2).
- [ ] E5. `tests/integration/test_identity_coop_stats.py::test_stale_terms_version_rejected` — an acceptance carrying an outdated `terms_version` is rejected (**AC-10**; proves C3's new equality check).
- [ ] E6. `tests/integration/test_identity_coop_stats.py::test_stats_endpoint_writes_nothing` — snapshot row counts of all three co-op tables before and after the call; assert unchanged.
- [ ] E7. **Agent-Probe (AC-10 judgment leg):** a reviewer reads `COOP_TERMS_TEXT` plus the rendered acceptance modal copy and judges whether they convey the intended contractual meaning (customer obtains visitor consent; customer offers opt-out; Beam supplies language only). Record the judgment verbatim in the phase report. This is NOT a Known-Gap — it is a proving strategy, and its outcome must be recorded.
- [ ] E8. **If the Playwright auth harness is unavailable when this phase executes** (repo-wide known gap — see `process/features/pixel/backlog/cadence-bot-flag-deferred-gates_NOTE_26-07-26.md`), write the backlog stub `process/features/visitors-identity/backlog/identity-coop-phase3-playwright-gap_NOTE_[execute-date].md` naming exactly which D3 behavior (modal-gates-the-PATCH; failure keeps toggle OFF) has zero automated/hybrid coverage as a result, and confirm the gate stays CONDITIONAL, not PASS, until that stub is either resolved or explicitly accepted. Do not let this residual pass silently — E4/E5/E7 cover the API and copy, but nothing in this suite exercises the frontend modal-gating interaction itself.

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
- Playwright auth-harness unavailability ⇒ Known-Gap + backlog stub (E8); gate stays **CONDITIONAL**.
- All flags remain OFF at phase completion; production enablement is out of scope.

---

## Blockers That Would Justify BLOCKED Status

- Phase 2 exit gate not passed (balances would display values whose semantics are unproven).
- Playwright auth-harness gap blocks a browser-level leg of D3 — this is a known repo-wide gap
  (`process/features/pixel/backlog/cadence-bot-flag-deferred-gates_NOTE_26-07-26.md`, ads-audiences
  Phase 1/2). If it blocks: record a Known-Gap + backlog stub (E8), keep the gate **CONDITIONAL**, and
  cover the flow with the integration tests in Step E instead.
- The Agent-Probe reviewer judges the policy language materially wrong — fix the text and re-probe;
  do not ship the surface on an unresolved judgment.

---

## Phase Loop Progress

- [ ] 1. RESEARCH — research-agent: Phase 2 report read; dashboard toggle precedent re-confirmed; test context loaded
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: this plan updated; Inner Loop Refresh Note if sections changed (or "n/a — research clean")
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md` (this pass: Gate CONDITIONAL, cycle 0 — supplement cycle required before EXECUTE)
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
- `apps/api/schemas/sites.py`
- `apps/api/main.py`
- `apps/web/src/app/dashboard/visitors/page.tsx`
- `apps/web/src/lib/api-types.ts`
- `apps/web/src/lib/api.ts`
- `apps/api/dependencies.py` (READ ONLY — `verify_site_access` shared helper, per B3)
- `apps/api/routers/ingest_health.py` (READ ONLY — endpoint shape precedent)
- `tests/integration/test_identity_coop_stats.py` (NEW)
- `tests/unit/test_coop_terms.py` (NEW)

---

## Public Contracts

- `GET /api/v1/sites/{site_id}/coop-stats` is NEW and additive; no existing endpoint changes shape.
- `PATCH /api/v1/sites/{site_id}` behavior for `contribution_enabled` is unchanged from Phase 1
  (acceptance required to set ON); this phase only adds the terms-version validation.
- `SiteOut`/`GET /api/v1/sites/{site_id}` gains two additive fields (`coop_terms_version`,
  `coop_terms_text`); existing fields unchanged (decided by C1 — no separate terms endpoint).
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
| Browser-level opt-in modal flow (D3 modal-gates-PATCH behavior) | Hybrid (precondition: Playwright auth harness — known repo-wide gap) → Known-Gap + backlog stub per E8 if unavailable | AC-10 UX leg; CONDITIONAL if harness unavailable |

---

## Test Infra Improvement Notes

(none identified yet)

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-coop_07-08-26/phase-3-contributor-surface_PLAN_07-08-26.md`
- Last completed step: PVL cycle 0 (this pass) — Gate CONDITIONAL, supplement cycle required
- Validate-contract status: written (Gate: CONDITIONAL, generated-by: outer-pvl)
- Supporting context files loaded: umbrella plan, Phase 1 + Phase 2 plans, blast-radius registry,
  SPEC, `process/context/tests/all-tests.md` routing, direct reads of `apps/api/routers/sites.py`,
  `apps/api/schemas/sites.py`, `apps/api/dependencies.py`, `apps/api/routers/ingest_health.py`,
  `apps/api/main.py`, `apps/api/models/api_usage.py`, `apps/web/src/app/dashboard/visitors/page.tsx`,
  `apps/web/src/app/dashboard/agents/page.tsx`
- Next step: orchestrator runs a PLAN-supplement cycle against the SUPPLEMENT REQUEST below, then
  re-spawns vc-validate-agent from V1. **Independent of this phase's own gate:** the umbrella's hard
  sequencing constraint is NOT yet satisfied — see Dimension findings below — so EXECUTE for this
  phase cannot legally begin regardless of this contract's outcome until Phase 1 and Phase 2 both
  complete EXECUTE, which themselves cannot begin until both upstream dependencies clear.

---

## Validate Contract

Status: CONDITIONAL
Date: 07-08-26
date: 2026-08-07
generated-by: outer-pvl

Fan-out disclosure: no Agent tool available in this validate session — single sequential
deep-verification pass covering all 4 Layer-1 dimensions and all 5 Layer-2 sections directly
against live repo state (files read, patterns grep-confirmed), not a multi-agent parallel fan-out.

Parallel strategy: sequential (this pass) — recommend parallel-subagents (4 Layer-1 + 5 Layer-2 =
9 agents) for the next PVL cycle if Agent tool becomes available, to get independent-eyes coverage
on the Section B/C gaps identified below.
Rationale: single-agent env constraint this session, not a scope/complexity signal — the plan
itself scores MEDIUM (score 3/7: S2 schema-adjacent via SiteOut fields, S6 high-risk class
present, S7 ~10 blast-radius files), which would normally recommend parallel subagents.

Test gates (C3 5-column table — ADDITIVE; existing consumers still parse the legacy line form below it):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-10 (immutable version) | terms text hash is stable, changes only when text changes | Fully-Automated | `tests/unit/test_coop_terms.py::test_version_is_content_hash` | B |
| AC-10 (required content) | terms text states consent-obtain + opt-out + not-legal-advice | Fully-Automated | `tests/unit/test_coop_terms.py::test_terms_text_states_required_obligations` | B |
| AC-11 (self-scoping) | Site A auth returns only Site A's numbers even with Site B active | Fully-Automated | `tests/integration/test_identity_coop_stats.py::test_stats_are_self_scoped` | B |
| AC-11 (tenant isolation) | foreign site_id returns 404, never 403, no existence leak | Fully-Automated | `tests/integration/test_identity_coop_stats.py::test_foreign_site_id_returns_404` | B |
| AC-11 (PII containment) | response contains zero email/email_bidx/visitor identifiers | Fully-Automated | `tests/integration/test_identity_coop_stats.py::test_stats_response_contains_no_pii` | B |
| AC-10 (atomicity, regression) | flag ON without terms_version rejected, zero partial writes | Fully-Automated | `tests/integration/test_identity_coop_stats.py::test_flag_on_requires_acceptance_in_same_transaction` | B |
| AC-10 (stale version rejected) | acceptance with outdated terms_version is rejected | Fully-Automated | `tests/integration/test_identity_coop_stats.py::test_stale_terms_version_rejected` | B |
| Read-only contract | stats endpoint writes nothing (row counts unchanged) | Fully-Automated | `tests/integration/test_identity_coop_stats.py::test_stats_endpoint_writes_nothing` | B |
| AC-10 (judgment leg) | model policy + modal copy convey intended contractual meaning | Agent-Probe | E7 reviewer judgment, recorded verbatim in phase report | B |
| Web quality gate | dashboard panel builds and lints clean | Fully-Automated | `cd apps/web && npm run lint` | B |
| AC-10 (UX leg) | modal gates the PATCH; failure keeps toggle visibly OFF | Hybrid (precondition: Playwright auth harness) | browser-level D3 flow test | D (Known-Gap + backlog stub per E8 if harness unavailable — repo-wide precedent) |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: the `strategy:` column carries ONLY the 3 proving strategies (Fully-Automated / Hybrid / Agent-Probe). Known-Gap is NEVER a `strategy:` value — it is a named residual row carried via gap-resolution D, never a strategy that proves a behavior.

Legacy line form (retained so existing validate-contract consumers still parse):
- Stats endpoint (AC-11): Fully-automated: `.venv/bin/python3.11 -m pytest tests/integration/test_identity_coop_stats.py -m integration -q` | known-gap: none
- Terms module (AC-10 automated leg): Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_coop_terms.py -m unit -q`
- AC-10 judgment leg: agent-probe: reviewer reads `COOP_TERMS_TEXT` + modal copy, records judgment in phase report
- Web surface: Fully-automated: `cd apps/web && npm run lint`
- D3 browser modal-gating flow: hybrid: Playwright, precondition Clerk auth harness (known repo-wide gap) | known-gap: documented via E8 backlog stub if harness unavailable at EXECUTE time

Dimension findings:
- Infra fit: PASS — Router registration pattern verified byte-for-byte against the live `ingest_health.router` registration in `apps/api/main.py`; the endpoint shape precedent (`GET .../ingest-health`) verified to exist and use the exact `verify_site_access` tenant-scoping helper this plan should also use (now specified explicitly at B3). No migration in this phase (correctly stated). No container/infra/deploy surface touched.
- Test coverage: CONCERN — All ACs get Fully-Automated or Agent-Probe coverage except D3's frontend "modal gates the PATCH" behavior, which has zero Fully-Automated/Hybrid proof and rests entirely on a Known-Gap (Playwright auth harness, repo-wide unavailable) plus code review. Per the VALIDATE net-gate vacuous-green rule, this alone forces CONDITIONAL, not PASS — the plan's own Phase Completion Rules already anticipate this ("gate stays CONDITIONAL"), and E8 (added this cycle) makes the backlog-stub requirement an explicit checklist item instead of an implied policy line.
- Breaking changes: PASS — `GET .../coop-stats` is new/additive; `PATCH` behavior for the flag is unchanged from Phase 1, only tightened; `SiteOut` gains two additive fields (C1 decision). No existing consumer's shape changes.
- Security surface: PASS — Tenant isolation verified against the live `verify_site_access` implementation (404-not-403 by construction). Zero PII fields in the Endpoint Contract, backed by an explicit test (E3). `COOP_TERMS_VERSION` as an import-time content hash correctly prevents a live-editable-pointer drift (the exact failure mode the task brief flagged). Model policy language is correctly scoped as a draft-with-required-disclaimer needing counsel review before production enablement, not treated as engineering-complete — matches the SPEC's own locked decision #3 and Out-of-Scope section, which require the PLAN to draft placeholder-but-substantive text since AC-10 needs real content to test against.
- Section A (Terms module): PASS — clean new-file creation, no conflicts, content-hash design sound.
- Section B (Stats service + endpoint): CONCERN (resolved this cycle) — B3 did not originally cite the shared `verify_site_access` helper (now added); the `ledger` array's pagination shape was described as "paginated" with no param names/defaults specified (now added at B3a). Highest-risk edit: B3's router — tenant-scoping is the security boundary; mitigate by writing E1/E2 first (TDD) and using the shared helper, not a hand-rolled check.
- Section C (Acceptance flow): CONCERN (resolved this cycle) — C1 originally left "site read response OR a dedicated GET /api/v1/coop/terms" undecided (now decided: additive `SiteOut` fields, no new endpoint). C2's original wording implied Phase 1 already validates terms_version *correctness*, when Phase 1 can only validate *presence* (no canonical version exists until this phase) — now split into C2 (confirm-only) and C3 (the actual new equality-check work).
- Section D (Dashboard): PASS — `ToggleChip` precedent and the `/dashboard/agents` `detection_enabled` empty-state precedent both verified live in the repo and match the plan's description; D3's deliberate divergence from `ToggleChip`'s optimistic-mutate behavior is necessary (AC-10 requires an acknowledgement gate) and is now explicitly reconciled against D2 so it doesn't read as a contradiction. Minor addition: D3 now specifies the PATCH-failure UX (modal stays open with error, toggle stays visibly OFF).
- Section E (Tests): PASS — all named test files/functions are new and non-colliding; E7's Agent-Probe scope is precise; E8 added this cycle to make the Known-Gap backlog-stub requirement mechanical rather than implied.

Open gaps:
- **Upstream dependency chain NOT satisfied as of this VALIDATE pass.** Per the umbrella's Hard
  Sequencing Constraints and `## Current Execution State`: `identity-vocab-reconcile_07-08-26` is
  at PVL cycle 9, `Gate: CONDITIONAL`, `Accepted by: USER` (retroactive to an already-completed,
  originally-unauthorized EXECUTE that the user elected to keep) — this is a de facto resolution
  but not a literal `Gate: PASS`. `graph-erasure-compliance_07-08-26` (SPEC A) is confirmed **CODE
  DONE, NOT EVL GREEN** — its own report states plainly "Docker unavailability blocks the entire
  Hybrid tier," 14 integration gates are collected-but-never-run, and the migration has never been
  applied anywhere. SPEC A is therefore **not LIVE** by the umbrella's own definition ("must
  complete EXECUTE and be LIVE, not merely planned"). Neither condition of the umbrella's hard stop
  is fully satisfied. This does not invalidate this phase's plan artifact (outer-PVL validates plan
  quality ahead of and independent of execution readiness — this is the documented, expected
  pattern for a 3-phase strictly-sequential program), but it means: even after this contract
  reaches PASS, Phase 3 EXECUTE cannot legally begin — Phase 1 and Phase 2 must both complete
  EXECUTE first, and neither can begin until the chain above clears. This is a program-level fact,
  not a Phase 3 plan defect, and is recorded here rather than fixed here (out of this file's write
  scope).
- Section B/C concerns above are resolved in this same PVL cycle (plan text updated in place, per
  V6 "apply accepted-concern mitigations first, then write contract") — carried in Dimension
  findings for audit trail, not re-listed as open.
- D3's frontend modal-gating behavior: Known-Gap pending E8's conditional backlog stub, contingent
  on Playwright auth-harness availability at EXECUTE time (repo-wide gap, not phase-specific).

What this coverage does NOT prove:
- The 9 Fully-Automated backend tests prove API-level correctness (tenant isolation, atomicity,
  PII absence, read-only contract) but do NOT prove the frontend actually renders the modal, blocks
  the PATCH until acknowledgement, or keeps the toggle visibly OFF on failure — that is D3's own
  behavior, covered only by the deferred Hybrid/Known-Gap row.
- The Agent-Probe (E7) proves the TEXT conveys the intended meaning to a careful reader; it does
  NOT prove or substitute for qualified privacy-counsel legal sufficiency review, which remains a
  hard, separate prerequisite for production enablement per the umbrella and SPEC.
- None of this phase's gates prove anything about Phase 1's or Phase 2's own correctness (ledger
  accrual, spend, expiry) — this phase only displays numbers those phases are responsible for
  producing correctly; Phase 1/2's own validate-contracts own that proof.
- `test_stats_endpoint_writes_nothing` proves this endpoint specifically writes nothing; it does
  not prove no OTHER code path can mutate these tables concurrently (a general isolation-level
  assumption, not tested here).

Gate: CONDITIONAL
Accepted by: PENDING
