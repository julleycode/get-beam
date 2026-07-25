---
name: plan:ad-audiences-phase-2-meta-live
description: "Ad Audiences — Phase 2: Meta live (real OAuth, Custom Audience create/upload, ToS error surfacing, min-size warning)"
date: 25-07-26
metadata:
  node_type: memory
  type: plan
  feature: ads-audiences
  phase: phase-2
---

# Phase 2 — Meta Live

**Program:** ad-audiences
**Umbrella plan:** process/features/ads-audiences/active/ad-audiences_25-07-26/ad-audiences-umbrella_PLAN_25-07-26.md
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/ads-audiences/active/ad-audiences_25-07-26/phase-2-meta-live_REPORT_{dd-mm-yy}.md (flat in the program task folder)

**Complexity:** COMPLEX
Complexity: COMPLEX
Date: 25-07-26
Status: PLANNED

## Overview

Replace the Phase 1 Meta stub with real Meta Marketing API integration: Limited Access OAuth, Custom Audience create/upload, fire-and-forget status model, ToS-precondition error surfacing, and min-size warning wiring. See process/context/all-context.md for repo conventions and process/context/tests/all-tests.md for the test-runner routing this phase's Exit Gate commands follow.

## Acceptance Criteria

See the ## Verification Evidence table below — each row maps a test gate to the exact SPEC acceptance criterion it proves; this phase's Exit Gate is 'done' only when every AC row in that table is Fully-Automated-green or its declared Hybrid/Agent-Probe evidence is recorded in the phase report.

## Phase Completion Rules

CODE DONE = all Implementation Checklist items checked and automated Exit Gate commands exit 0. TESTING = Hybrid/Agent-Probe evidence being gathered. VERIFIED = validate-contract Gate is PASS (or explicitly-accepted CONDITIONAL) AND every row in Verification Evidence has real recorded evidence (not a placeholder) AND the phase report is written. A phase may not be marked VERIFIED on code completion alone.

---

## Purpose

Replace `services/ads/meta.py`'s Phase-1 mock stub with real Meta Marketing API integration:
Limited Access OAuth (ads_management + business_management scopes), Custom Audience creation
(`POST /act_{id}/customeraudiences`), member upload (`POST /{audience_id}/users`, async), the
fire-and-forget status model (v1 decision — no polling task), ToS-precondition error surfacing
(AC13), and min-size warning wiring (AC7). Covers SPEC ACs 2, 6, 7, 13.

---

## Entry Gate

- Phase 1 exit gate passed: ACs 1,4,5,9,10,11,12 provable in mock mode; `services/ads/` registry
  pattern stable and unchanged in shape
- `services/ads/meta.py`'s Phase-1 stub methods (marked `# PHASE 2:`) exist and are the sole
  edit target for this phase's service-layer work

---

## Blast Radius

- `apps/api/services/ads/meta.py` (edit — replace stub bodies with real logic; file already
  exists from Phase 1, owned by Phase 1 for creation, owned by Phase 2 for the real
  implementation — see blast-radius registry for the exact extension-point declaration)
- `apps/api/tasks/ads_tasks.py` (edit — add the Celery async member-upload leg for Meta, if the
  synchronous request/response path proves too slow for large segments; extension point, not a
  new file)
- `apps/api/routers/ads.py` (edit — surface AC13's ToS-precondition error shape and AC7's
  min-size warning payload field on the `push` endpoint response)
- `apps/web/src/components/ad-connect-panel.tsx` (edit — render the AC13 error message and AC7
  warning text returned by the push endpoint; no new component)
- Test files: `tests/unit/test_ads_meta.py` (new), `tests/integration/test_ads_meta_live.py`
  (new — mocked-callback integration), `apps/web/e2e/connectors-ads-push-warning.spec.ts` (new
  — AC7 e2e)

**Not touched:** anything in `apps/api/services/ads/google.py`, `apps/api/services/ads/linkedin.py`,
`apps/api/services/ads/base.py`, `apps/api/services/ads/factory.py` (Phase 1-owned, shared —
Phase 2 may only READ these, never edit; if a shared-file change is genuinely required, declare
it explicitly per the blast-radius registry's extension-point rule and flag as a
Potential Blast Radius Conflict). Zero CRM/csv_exporter edits (program-wide hard constraint).

---

## Implementation Checklist

### Step A — Real Meta OAuth

- [ ] A1. Docs-fetch (cheap, cost-class `docs-fetch`) to confirm the exact Meta OAuth
      authorization URL shape, scope string format (`ads_management,business_management`), and
      token-exchange endpoint/response shape. Confirm redirect_uri registration requirements.
      **Also confirm the CURRENT Meta Graph API version.** Do NOT copy the `v19.0` constant
      already used in `apps/api/services/platforms/facebook.py` / `instagram.py` verbatim —
      that version was pinned circa early 2024 and Meta typically deprecates a Graph API version
      roughly 2 years after release, so it is very likely already retired by 25-07-26. Pick the
      current, docs-confirmed version, define it as a single named module-level constant in
      `meta.py` (never an inline literal repeated across call sites), and add a one-line upgrade
      note (e.g. `# Meta deprecates Graph API versions ~2yr after release — recheck before
      <today + ~2yr>`) so a future maintainer knows to re-verify before it goes stale again.
- [ ] A2. Implement `MetaAdsProvider.get_oauth_url(state)` for real (non-mock) mode: build the
      `https://www.facebook.com/v{version}/dialog/oauth` URL (using the A1-confirmed version
      constant) with `client_id`, `redirect_uri`, `state` (from `oauth_state.py`, reused
      verbatim), `scope`.
- [ ] A3. Implement `MetaAdsProvider.exchange_code(code)` for real mode: `GET
      /oauth/access_token` (or `POST`, per confirmed docs) exchange, extract access_token,
      expires_in, and ad-account/business info via a follow-up `/me/adaccounts` call. Encrypt
      and store via `services/encryption.py` (imported, not modified).
      **Router note (corrects a plan-drafting ambiguity found in VALIDATE):** `routers/ads.py`'s
      OAuth callback handler is provider-AGNOSTIC — it mirrors `routers/crm.py`'s
      `oauth_callback`, which resolves the connector polymorphically via
      `get_provider(provider)` and calls `.exchange_code(...)` on it; it does **not** branch on
      `if provider == "meta":` inside the router. Do NOT add provider-specific branching logic
      to the callback handler — it should need ZERO structural changes from what Phase 1 built.
      The mock-vs-real branch lives entirely inside `MetaAdsProvider.exchange_code()` itself (see
      A4), matching every `services/crm/*.py` connector's own `if settings.mock_external_apis:`
      check. The callback handler is NOT a declared Phase 2 extension point in the blast-radius
      registry (only the `push` endpoint's additive fields are — see C2/D2 below); if RESEARCH
      later finds the callback handler genuinely needs a structural change, stop and update the
      registry first rather than silently expanding scope.
- [ ] A4. Preserve the Phase-1 mock branch unchanged — `if settings.mock_external_apis:` must
      still short-circuit to the deterministic fake path for every method touched in this phase.

### Step B — Custom Audience create + upload

- [ ] B1. Implement `MetaAdsProvider.create_or_update_audience(connection, link, hashed_contacts)`:
      if `link.platform_audience_id` is None (first push), `POST /act_{ad_account_id}/customeraudiences`
      with `subtype=CUSTOM`, `customer_file_source` set per Meta's documented enum, capture the
      returned audience id. If `link.platform_audience_id` already set (repeat push — AC6),
      skip creation and go straight to member upload against the existing id.
- [ ] B2. Implement the member-upload leg: `POST /{audience_id}/users` with the SHA256-hashed
      `hashed_contacts` (already hashed by `ads_push.py` in Phase 1 via `_sha256` — this method
      never re-hashes, never receives plaintext). This call is asynchronous on Meta's side.
- [ ] B3. **Fire-and-forget status model (locked INNOVATE decision, v1):** treat Meta's sync
      acknowledgment (the upload call returning 200 with a `num_received`/`num_invalid_entries`
      style body) as the terminal result for this push. Do NOT add a polling task. Reconcile
      opportunistically: the NEXT time the user views this connection or pushes again, if Meta's
      API exposes an approximate-audience-size field on a lightweight `GET
      /{audience_id}` call, surface it — but this is best-effort, not a guarantee, and must be
      explicitly labeled in the UI (Step D) as "Beam-side matched/queued", never
      "platform-confirmed". Document this as a named known-limitation in the phase report.
- [ ] B4. Wire `push_segment_to_ads`'s async threshold branch (Phase-1-built,
      `ads_async_push_threshold`) so Meta pushes above the threshold enqueue via
      `ads_tasks.push_segment_to_ads_task` — no new Celery task needed, Phase 1's task already
      calls into `ads_push.py` which now has real Meta logic.

### Step C — AC13: ToS-precondition error surfacing

- [ ] C1. Docs-fetch + best-effort research on the actual Meta error response shape for an
      ad-account that has not accepted the Custom Audience Terms of Service. If a concrete error
      code/message cannot be confirmed from docs alone, treat this as intentionally
      Agent-Probe-tier per the SPEC's own declared strategy for AC13 — do not fabricate a
      fixture; document what IS knowable (any generic Meta Graph API error envelope shape) and
      what remains unverified.
      Escalate `VC-FEASIBILITY-PROBE-NEEDED: [Meta Custom Audience ToS-acceptance error shape] —
      cost-class: needs-live-provider` ONLY if a sandbox/live probe is genuinely required to make
      a design decision (e.g. whether the error is distinguishable from other 400s) — otherwise
      proceed with best-effort mapping and record the gap.
- [ ] C2. Implement a specific, actionable error message path in `MetaAdsProvider` (and
      surfaced through `routers/ads.py`'s push endpoint) for any Graph API error response that
      matches the ToS-precondition signature identified in C1, distinct from a generic failure
      message. If the exact signature is unconfirmed, implement the best-effort mapping now and
      leave a `# TODO Agent-Probe: confirm real error code against live sandbox` marker.

### Step D — AC7: min-size warning wiring

- [ ] D1. Confirm Meta's practical minimum audience size threshold via the SPEC's already-
      researched figure (~1000 practical, 100 technical minimum) — cheap docs-fetch to confirm
      whether a more precise, currently-documented number should replace the placeholder `1000`
      constant Phase 1 left in `routers/ads.py`.
- [ ] D2. Wire the push endpoint's response to include a `below_minimum: bool` +
      `minimum_threshold: int` field when the post-safety-filter contact count is below the
      confirmed Meta threshold; `ad-connect-panel.tsx`'s confirm dialog renders the warning but
      does not block the push (SPEC: "warned... not blocked").

### Step E — Test coverage

- [ ] E1. `tests/unit/test_ads_meta.py`: unit tests for `MetaAdsProvider` methods in mock mode
      (Fully-Automated) — OAuth URL shape, exchange response parsing, audience create/update
      branch logic (first push vs repeat push via `link.platform_audience_id`).
- [ ] E2. `tests/integration/test_ads_meta_live.py`: integration test against a MOCKED Meta OAuth
      callback (Fully-Automated, same pattern as the existing CRM OAuth callback test
      `test_hubspot_oauth_roundtrip` in `tests/integration/test_crm_push.py`) — full connect →
      push → repeat-push flow, asserting `platform_audience_id` reuse (AC6).
- [ ] E3. Hybrid manual smoke against Meta's real sandbox app (documented procedure in the phase
      report, run once before this phase can be marked VERIFIED — not part of the automated
      suite; requires a real Meta developer app + test Business Manager, which is a one-time
      manual setup step outside this plan's scope to provision).
- [ ] E4. `apps/web/e2e/connectors-ads-push-warning.spec.ts`: Playwright e2e (Fully-Automated) —
      mock a small segment via the API layer, assert warning text renders in the confirm dialog
      before the push button is enabled/clicked (AC7).
- [ ] E5. Agent-Probe: manually exercise the AC13 error path against whatever real-or-simulated
      error shape was confirmed in Step C, record judgment on whether the surfaced message is
      "specific and actionable" per the SPEC wording.

---

## Exit Gate

```bash
# Zero CRM/csv_exporter drift (program-wide constraint, re-checked every phase)
git diff --stat main -- apps/api/models/crm_connection.py apps/api/routers/crm.py \
  apps/api/services/crm.py apps/api/services/crm/ apps/api/services/crm_push.py \
  apps/api/services/crm_rate_limiter.py apps/api/tasks/crm_tasks.py apps/api/services/csv_exporter.py
# Expected: empty output

# Backend (VALIDATE-corrected: use the venv interpreter per process/context/tests/all-tests.md —
# bare `pytest` is not guaranteed on PATH, and CI does not source .venv/bin/activate)
.venv/bin/python -m pytest tests/unit -k ads_meta -m unit -q
.venv/bin/python -m pytest tests/integration -k ads_meta -m integration -q

# Frontend e2e (VALIDATE-corrected: this repo has no pnpm workspace at the root — apps/web is a
# standalone npm package, confirmed via absence of any pnpm-lock.yaml/root package.json and the
# `test:e2e` script in apps/web/package.json using `npx playwright test`)
cd apps/web && npx playwright test connectors-ads-push-warning
# Expected: all green
```

- ACs 2, 6, 7 pass at Fully-Automated tier; Hybrid sandbox smoke (E3) recorded in phase report
- AC13 Agent-Probe judgment recorded in phase report
- Phase report written to report destination above

---

## Blockers That Would Justify BLOCKED Status

- Meta developer app / test Business Manager for the Hybrid sandbox smoke (E3) is not available
  in this environment — record as a known-gap, do not block the whole phase; automated tiers
  (E1, E2, E4) can still reach green and the phase can proceed to CONDITIONAL/PASS with E3
  documented as pending manual execution before first production enable
- C1's docs-fetch is genuinely inconclusive AND a live-provider probe is refused/unavailable —
  proceed with best-effort mapping (per C2) rather than blocking; AC13 stays Agent-Probe as SPEC
  already anticipates

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: Phase 1 report read in full; test context loaded; Meta docs-fetch for OAuth shape + ToS error shape + min-size threshold
- [ ] 2. INNOVATE — innovate-agent: approach decided for AC13's error-mapping strategy if RESEARCH leaves ambiguity; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated with docs-fetch findings; Inner Loop Refresh Note if sections changed (or "n/a — research clean")
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md` (outer-PVL pass, run ahead of Phase 1 execution per the umbrella's agent-team outer-PVL fan-out — Steps 1-3 above remain unchecked and will run for real once Phase 1 lands; if RESEARCH/INNOVATE materially change this plan, plan-agent must add an `## Inner Loop Refresh Note` to trigger a fresh inner-PVL pass)
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green (or gaps documented)
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate Contract`
reads "(placeholder — vc-validate-agent writes this section before EXECUTE)", orchestrator must
spawn vc-validate-agent first. A partial contract missing Plan updates applied / Execute-agent
instructions / Test gates sections is treated as a placeholder.

---

## Touchpoints

`apps/api/services/ads/meta.py` (edit, Phase-2-owned real logic), `apps/api/tasks/ads_tasks.py`
(edit — extension point only), `apps/api/routers/ads.py` (edit — extension point only), frontend
`ad-connect-panel.tsx` (edit — extension point only), plus new test files listed in Blast Radius.

---

## Public Contracts

- `POST /api/v1/ads/{site_id}/connections/meta/push` response gains two additive fields:
  `below_minimum: bool`, `minimum_threshold: int` — no existing field removed or renamed.
- No change to any CRM or CSV export public contract.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Integration test: mocked Meta OAuth callback completes, connection shows status=connected | Fully-Automated | AC2 (automated leg) |
| Hybrid manual smoke: real Meta sandbox app connect flow | Hybrid | AC2 (live leg, before first production enable) |
| Integration test: push twice, `platform_audience_id` reused on second call | Fully-Automated | AC6 |
| Playwright e2e: small-segment warning renders before push confirm | Fully-Automated | AC7 |
| Agent-Probe: ToS-precondition error message judged specific/actionable | Agent-Probe | AC13 |
| `git diff --stat` on CRM/csv_exporter files empty | Fully-Automated | Hard safety constraint |

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/ads-audiences/active/ad-audiences_25-07-26/phase-2-meta-live_PLAN_25-07-26.md`
- Last completed step: VALIDATE (outer-PVL) — Gate: PASS
- Validate-contract status: PASS (outer-pvl, 25-07-26) — see `## Validate Contract` below
- Next step: This phase cannot EXECUTE until Phase 1's exit gate passes (registry dependency).
  Once Phase 1 lands, spawn vc-research-agent for this phase's Step 1 RESEARCH (re-check
  `alembic heads`/registry state; if Phase 1 changed the `services/ads/meta.py` stub shape or
  the callback handler in a way that conflicts with this contract's assumptions, plan-agent must
  add an `## Inner Loop Refresh Note` and this contract is re-run as inner-PVL before EXECUTE).

---

## Test Infra Improvement Notes

- Both this phase's Exit Gate and Phase 1's Exit Gate originally specified
  `pnpm --filter web exec playwright test ...` — this repo has no pnpm workspace (no root
  `package.json`, no `pnpm-lock.yaml`; `apps/web` is a standalone npm package). Corrected here to
  `cd apps/web && npx playwright test ...`. Phase 1's plan carries the same bug and should be
  corrected the next time its validate-contract is written (out of this phase's edit scope).

---

## Validate Contract

Status: PASS
Date: 25-07-26
date: 2026-07-25
generated-by: outer-pvl

Parallel strategy: sequential (single-agent direct analysis this pass)
Rationale: 7-signal score 4/7 (S1 multi-package, S2 auth/API surface, S6 high-risk class, S7 5+
blast-radius files) → HIGH tier nominally recommends parallel-subagents/agent-team fan-out for
the Layer 1+2 investigation; this VALIDATE pass ran as a single sequential agent (no Agent-tool
fan-out available in this session) but achieved equivalent depth via direct source reads,
donor-code comparison (`services/crm/hubspot.py`, `crm_push.py`, `tasks/crm_tasks.py`,
`oauth_state.py`, `routers/crm.py`), live repo checks (package-manager/lockfile confirmation,
Graph API version grep, `alembic`/venv presence), and the structural plan-artifact validator.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC2 | Meta OAuth connect completes, connection shows status=connected (mocked callback leg) | Fully-Automated | `.venv/bin/python -m pytest tests/integration -k ads_meta_live -m integration -q` (mirrors `test_hubspot_oauth_roundtrip`) | A |
| AC2 | Meta OAuth connect completes against Meta's real sandbox app | Hybrid | Manual smoke procedure recorded in phase report; precondition: real Meta developer app + test Business Manager (not available in this environment) | D |
| AC6 | Re-pushing a segment reuses `platform_audience_id` instead of creating a duplicate | Fully-Automated | `.venv/bin/python -m pytest tests/integration -k ads_meta_live -m integration -q` (push twice, assert `AdAudienceLink.platform_audience_id` reused) | A |
| AC7 | Small-segment warning renders before push confirm; does not block | Fully-Automated | `cd apps/web && npx playwright test connectors-ads-push-warning` | A |
| AC13 | ToS-precondition push failure surfaces a specific, actionable error (not generic/silent) | Agent-Probe | Manual scenario: exercise the confirmed-or-best-effort error path from Step C; judge message specificity per SPEC wording; record verdict in phase report | A (best-effort mapping proven now; upgrade to Fully-Automated once a real fixture is confirmed — non-blocking backlog item, tracked via the `# TODO Agent-Probe:` marker at C2) |
| Hard safety constraint | Zero CRM/csv_exporter file drift | Fully-Automated | `git diff --stat main -- apps/api/models/crm_connection.py apps/api/routers/crm.py apps/api/services/crm.py apps/api/services/crm/ apps/api/services/crm_push.py apps/api/services/crm_rate_limiter.py apps/api/tasks/crm_tasks.py apps/api/services/csv_exporter.py` (expect empty) | A |
| Unit coverage | `MetaAdsProvider` method-level logic in mock mode (OAuth URL shape, exchange parsing, create-vs-reuse branch) | Fully-Automated | `.venv/bin/python -m pytest tests/unit -k ads_meta -m unit -q` | A |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

Legacy line form (retained so existing validate-contract consumers still parse):
- Meta OAuth + Custom Audience push (AC2/AC6/AC7): Fully-automated: `.venv/bin/python -m pytest tests/integration -k ads_meta_live -m integration -q` | hybrid: manual sandbox smoke, precondition: real Meta dev app + test Business Manager | agent-probe: AC13 ToS-error judgment | known-gap: none blocking
- Hard safety constraint: Fully-automated: `git diff --stat` on the 7 CRM/csv_exporter files, expect empty

Dimension findings:
- Infra fit: PASS — registry/factory pattern (Phase-1-owned) is respected; router/config/task
  additions stay within the blast-radius registry's declared extension points; no new
  ports/containers/runtime surfaces introduced.
- Test coverage: PASS (fixed this cycle) — Fully-Automated/Hybrid/Agent-Probe tiers correctly
  match SPEC's per-AC declared strategy; two Exit Gate command bugs found and corrected in this
  plan-text edit: (1) `pnpm --filter web exec ...` doesn't work in this repo (no pnpm workspace —
  confirmed via absent root `package.json`/`pnpm-lock.yaml`; `apps/web`'s own `test:e2e` script
  uses `npx playwright test`), replaced with `cd apps/web && npx playwright test ...`; (2) bare
  `pytest` isn't guaranteed on PATH (confirmed: `which pytest` → not found; `.venv` exists but CI
  does not source it per `all-tests.md`'s own documented gotcha), replaced with
  `.venv/bin/python -m pytest ...` matching the canonical command in `all-tests.md`.
- Breaking changes: PASS — `below_minimum`/`minimum_threshold` are additive-only fields on the
  push endpoint response; zero existing route removed/renamed; CRM/csv_exporter non-edit is a
  hard automated gate, not advisory.
- Security surface: CONCERN → resolved as execute-agent instructions (E1/E2 below), not a plan
  blocker: (1) STRIDE-lite pass — Spoofing/Tampering/Repudiation/Elevation-of-Privilege all PASS
  (state-param CSRF reused verbatim from `oauth_state.py`; Fernet-encrypted token storage; tokens
  never returned to client; scopes correctly limited to Limited-Access self-serve tier); (2)
  Information Disclosure — the plan does not explicitly forbid logging raw access_token/
  refresh_token/authorization-code values in structlog calls (repo-wide "never log PII/secrets"
  convention exists but isn't restated for this new external-secret surface); (3) Denial-of-
  Service resilience — the plan doesn't explicitly cite `crm/base.py`'s `HTTP_TIMEOUT=10.0` +
  `_http_retry` pattern for the new Meta httpx calls, even though every other external
  integration in the repo follows it (per `all-context.md` "every external call has timeout +
  retry/backoff"). Both closed via Execute-Agent Instructions E1/E2.
- Section A feasibility (Real Meta OAuth): CONCERN → resolved via plan-text fix this cycle: (1)
  A3's original wording described adding `if provider == "meta":`-style branching inside
  `routers/ads.py`'s callback handler — this contradicts the actual provider-agnostic
  polymorphic-factory pattern already established by `routers/crm.py`'s `oauth_callback` (which
  Phase 1 is building `routers/ads.py`'s callback handler to mirror) and is NOT a declared Phase
  2 extension point in the blast-radius registry; corrected to clarify the callback handler needs
  zero structural change, and the mock/real branch lives inside `MetaAdsProvider.exchange_code()`
  itself, matching A4. (2) A1 didn't require confirming a current Meta Graph API version — the
  only two existing Graph API version constants in this repo (`facebook.py`/`instagram.py`, both
  `v19.0`) are ~2+ years old and Meta typically deprecates a Graph API version ~2 years after
  release, so reusing that constant would very likely target an already-retired version;
  corrected to require a fresh docs-confirmed version + a named constant + an upgrade-reminder
  comment.
- Section B feasibility (Custom Audience create/upload): PASS — mechanically feasible via the
  Phase-1-built `AdAudienceLink.platform_audience_id` reuse check; AC6 is provable via DB-state
  assertion without needing to poll Meta's real async completion; the fire-and-forget INNOVATE
  decision is well-documented with a correctly-scoped known-limitation UI-labeling requirement
  ("Beam-side matched/queued", never "platform-confirmed").
- Section C feasibility (AC13 ToS error): PASS — correctly self-limits to Agent-Probe/best-effort
  per SPEC's own declared strategy rather than over-claiming provability; the conditional
  `VC-FEASIBILITY-PROBE-NEEDED` escalation is appropriately gated behind "genuinely required to
  make a design decision," not fired reflexively. No live-provider probe was triggered by this
  VALIDATE pass — the plan already routes the genuinely-unverifiable mechanism through the
  correct tier instead of guessing at a fixture.
- Section D feasibility (AC7 min-size warning): PASS — docs-fetch-resolvable threshold
  confirmation, additive response fields, non-blocking per SPEC ("warned... not blocked").
- Section E feasibility (Test coverage / Exit Gate): CONCERN → resolved via plan-text fix (see
  Test coverage dimension above); E1-E5 test assignments themselves are correctly tiered and
  mechanically feasible (E2's donor precedent `test_hubspot_oauth_roundtrip` confirmed to exist
  at `tests/integration/test_crm_push.py:187`).

Plan updates applied (this VALIDATE cycle):
| # | What changed | Where | Why |
|---|---|---|---|
| P1 | Exit Gate commands corrected: `.venv/bin/python -m pytest ...` (was bare `pytest`); `cd apps/web && npx playwright test ...` (was `pnpm --filter web exec playwright test ...`) | Exit Gate section | Repo has no pnpm workspace and bare `pytest` isn't guaranteed on PATH — both confirmed live this session; commands as originally written would not run |
| P2 | A3 rewritten to remove the `if provider == "meta":`-in-router-callback description and clarify the callback handler needs zero structural change | Step A, item A3 | Contradicted the provider-agnostic factory pattern already established by `routers/crm.py` and was not a declared Phase 2 extension point in the blast-radius registry |
| P3 | A1 extended to require confirming and naming a current Meta Graph API version (not reusing the repo's existing stale `v19.0` constant) | Step A, item A1 | Only existing Graph API version precedent in this repo (`facebook.py`/`instagram.py`) is ~2+ years old and Meta versions typically retire on a ~2yr cadence |

Execute-agent instructions:
| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Never log raw `access_token`, `refresh_token`, or the OAuth `code` param in any structlog call added in this phase — log only outcome/status/provider/site_id, matching the repo-wide "never log PII/secrets" convention already applied to every other external integration | Any structlog call added inside `MetaAdsProvider` or the callback handler's new logging (if any) |
| E2 | Every new httpx call to Meta's Graph API (A2/A3/B1/B2) must use an explicit timeout and retry/backoff wrapper, matching `apps/api/services/crm/base.py`'s `HTTP_TIMEOUT=10.0` + `_http_retry` pattern (reuse `services/ads/base.py` if Phase 1 already centralized an equivalent there; otherwise replicate the pattern locally in `meta.py`) | Every new `httpx.AsyncClient` call site added in Step A/B |

Open gaps:
- E3 Hybrid Meta sandbox smoke requires a real Meta developer app + test Business Manager — not
  available in this environment; deferred to before-first-production-enable, matching the
  program's `needs-live-provider` double-opt-in policy. Non-blocking known-gap.
- AC13's real Meta ToS-acceptance error shape remains unconfirmed pending either a successful
  docs-fetch or an explicitly-opted-in live-provider probe; Agent-Probe/best-effort mapping
  proceeds now per SPEC's own declared strategy. Non-blocking known-gap; upgrade-to-
  Fully-Automated tracked via the `# TODO Agent-Probe:` marker at C2.
What this coverage does NOT prove:
- AC2 Fully-Automated (mocked callback) does NOT prove Meta's real OAuth consent screen, real
  token exchange, or the real `/me/adaccounts` response shape — only the Hybrid sandbox smoke
  (E3, deferred known-gap) would prove that.
- AC6 Fully-Automated does NOT prove Meta's real member-upload endpoint treats a reused
  `audience_id` as expected server-side — it only proves Beam's own DB-side reuse logic
  (`AdAudienceLink.platform_audience_id`), not Meta's live behavior.
- AC7 Playwright e2e does NOT prove the numeric threshold (1000) matches Meta's real current
  documented minimum — that depends on D1's docs-fetch outcome, not an empirical probe.
- AC13 Agent-Probe does NOT prove the real Meta error code/shape for an unaccepted-ToS ad
  account — genuinely unverified without a live sandbox call; this is the named residual, not a
  silent gap.
- The hard safety constraint gate (`git diff --stat` on 8 named files) does NOT prove no OTHER
  unlisted file gained CRM-like logic — it only proves those specific files are untouched;
  broader enforcement relies on the blast-radius registry's Hard-forbidden list plus review.
- The unit coverage gate does NOT exercise real Meta Graph API error responses, real rate
  limiting, or real network failure/timeout behavior — those paths are mocked/synthetic only.
(Required until C3 is implemented — temporary C3 mitigation)
Gate: PASS (no FAILs; all 3 CONCERNs resolved via plan-text fixes P1-P3 or execute-agent
instructions E1-E2 in this same VALIDATE cycle)
Accepted by: session (outer-PVL VALIDATE pass, 25-07-26) — no user-facing CONDITIONAL
concessions were needed; every finding was closed in-cycle.
