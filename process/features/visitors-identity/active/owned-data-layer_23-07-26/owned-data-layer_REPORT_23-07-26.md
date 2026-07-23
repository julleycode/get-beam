---
name: report:owned-data-layer
description: "Owned identity data layer closeout — company_graph + identity_signals, code-complete, WITH_GAPS"
date: 23-07-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: owned-data-layer
phase: owned-data-layer
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/owned-data-layer_23-07-26/owned-data-layer_PLAN_23-07-26.md
---

# Owned Identity Data Layer — Phase Report

## What Was Done

**Phase 1 — durable company graph (commit `54cf384`):**
- New `apps/api/models/company_graph.py` — `CompanyGraphNode` (ip/domain/company_name/source/confidence/first_seen/last_verified, unique on `(ip, source)`).
- New migration `f8a2c1d9b3e7_add_company_graph.py`, chained after `b3f9a1d2c7e5` (the AI-referral head at plan time) — actual chain confirmed at EXECUTE now runs through `c4e8f1a9d2b7` first (see Plan Deviations D1).
- `apps/api/models/beam_identity.py` gained nullable `city`/`region`/`country` columns.
- `apps/api/services/company_resolver.py` extended with write-through (`_write_through_company_graph`) on every successful free-rDNS resolve, plus read-time staleness re-validation, both gated behind `company_graph_enabled` (default `False`).
- `apps/api/services/identity_resolver.py` — `_graph_node_by_email` broadened to return full profile fields.
- `apps/api/services/visitor_aggregator.py` — small touch-up (4 lines) alongside the resolver change.
- New `tests/unit/test_company_graph.py` (upsert-on-conflict, staleness window, flag-off no-op) and `tests/integration/test_company_graph_persistence.py` (Docker-gated, not run).

**Phase 2 — SendGrid open/click → identity_signals (commit `94852a9`):**
- New `apps/api/models/identity_signal.py` — `IdentitySignal` (site_id/ip/email ciphertext+bidx/signal_type/base_confidence).
- New migration `a3e9f1c7d2b5_add_identity_signals.py`, chained after `f8a2c1d9b3e7`.
- New `apps/api/services/identity_signals.py` — `record_signal()` (write gates: datacenter IP, proxy/VPN, suppression, `do_not_resolve`), `decay_confidence()` (pure, read-time), `corroborate_identity()` (join-only, zero write access to `IdentifiedVisitor`).
- `apps/api/routers/webhooks.py` — new `open`/`click` branch in the SendGrid handler, structurally separate from `_SUPPRESS_EVENTS`.
- `apps/api/services/email_sender.py` — `send()` gained optional `custom_args` param + always-on explicit `tracking_settings`.
- `apps/api/services/campaign_sender.py` — passes `custom_args={"site_id", "visitor_id"}` at the identified-visitor send call site.
- New `tests/unit/test_identity_signals.py`, `tests/unit/test_sendgrid_open_click_webhook.py`, extended `tests/unit/test_email_sender_branding.py`, new `tests/integration/test_identity_signals_persistence.py` (Docker-gated, not run).

**Both phases:** flags (`company_graph_enabled`, `identity_signals_enabled`, `company_graph_staleness_days`) confirmed present and defaulted OFF/75 in `apps/api/config.py`.

## What Was Skipped/Deferred

- Both Hybrid/integration test files (`test_company_graph_persistence.py`, `test_identity_signals_persistence.py`) — never run, no Docker daemon in this sandbox. → backlog note `owned-data-layer-docker-verification_NOTE_23-07-26.md`.
- Live `alembic upgrade head` round-trip against a disposable Postgres — never run. → same backlog note.
- SendGrid live payload shape / `custom_args` echo shape verification via `vc-docs-seeker` — not run this session; remains the plan's pre-accepted Agent-Probe known-gap, unchanged.
- Account-level SendGrid tracking-settings override check — needs-live-provider, not probed (accepted known-gap per VALIDATE policy, unchanged).
- Flipping either flag to `True` in any real environment — explicitly out of scope for this plan (operator action, post-migration-live-apply).

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| Full unit collection | `.venv/bin/python -m pytest tests/unit -q` | **875 passed, 2 skipped** |
| Marker-scoped unit | `.venv/bin/python -m pytest tests/unit -m unit -q` | 319 passed, 2 skipped, 556 deselected (vs. 270/2/554 baseline at VALIDATE) |
| Regression — agent-exclusion boundary | `.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -q` | **18 passed** (file unmodified, matches VALIDATE baseline) |
| Corroborating-only invariant | `grep -n "IdentifiedVisitor" apps/api/services/identity_signals.py` | Read-only SELECTs only; zero write-path import — invariant holds structurally |
| Hybrid — company_graph persistence | `tests/integration/test_company_graph_persistence.py` | **Skipped — Docker unavailable in sandbox** |
| Hybrid — identity_signals persistence | `tests/integration/test_identity_signals_persistence.py` | **Skipped — Docker unavailable in sandbox** |
| Hybrid — migration apply | `alembic upgrade head` (disposable container only) | **Skipped — Docker unavailable in sandbox** |
| Agent-Probe — SendGrid payload shape | `vc-docs-seeker` pull or live sandbox replay | **Not run — remains known-gap** |

## Plan Deviations

**D1 — migration chain advanced past what the plan anticipated.** The plan's Grounded Facts table listed 3 pending migrations (`d11b39a6c843` → `a1c7e4f92b83` → `b3f9a1d2c7e5`) as the alembic head at VALIDATE time. By EXECUTE, a parallel session (Handoff Detection Phase H1, commit `231e4c0`) had landed a 4th migration, `c4e8f1a9d2b7` (agent_fetch_events), ahead of this plan's own migrations. Execute-agent correctly re-confirmed the actual head at EXECUTE time (per the plan's own explicit instruction not to hardcode) and chained `f8a2c1d9b3e7` (company_graph) after `c4e8f1a9d2b7`, then `a3e9f1c7d2b5` (identity_signals) after that. Verified this session by reading each migration file's `revision`/`down_revision` header — the chain is linear and correct: `d11b39a6c843 → a1c7e4f92b83 → b3f9a1d2c7e5 → c4e8f1a9d2b7 → f8a2c1d9b3e7 → a3e9f1c7d2b5` (current head). This is a benign deviation — the plan explicitly anticipated and licensed this re-confirmation step.

**D2 — `apps/api/services/visitor_aggregator.py` touched (not in original Touchpoints list).** Phase 1's commit includes a 4-line change to `visitor_aggregator.py` alongside `company_resolver.py`, not listed in the plan's Touchpoints section. Small and consistent with the company-graph write-through wiring; not flagged as a concern, but noted as an undeclared touchpoint for future closeout accuracy.

**D3 — config.py / main.py listed in touched-files context but carry no diff from this plan's commits.** `apps/api/config.py` and `apps/api/main.py` were included in the execute-agent's `touched_files` list handed to this UPDATE PROCESS session, but `git show --stat` on both `54cf384` and `94852a9` shows neither file appears in either commit's diff. Root cause, confirmed this session: `company_graph_enabled`, `company_graph_staleness_days`, and `identity_signals_enabled` already existed in `apps/api/config.py` as of commit `231e4c0` — landed by the parallel Handoff Detection (H1) session before this plan's own EXECUTE ran. This plan's config flags were correctly *present* at EXECUTE time (satisfying the plan's own checklist items 1) but were never *written* by this plan's commits — they were inherited. Not a defect; documenting so the commit history isn't misread as this plan introducing those flags. `main.py`'s inclusion in touched_files appears to be the same false-positive — no diff in either commit, no functional claim depends on it.

**Correction to a stale claim carried in execute-agent's self-report:** `tests/unit/test_sendgrid_open_click_webhook.py` has **6** test functions (`test_existing_suppress_events_unchanged`, `test_soft_bounce_ignored`, `test_open_click_flag_off_noop`, `test_records_when_site_id_present`, `test_skips_when_site_id_absent`, `test_skips_when_ip_absent`), not 8 as an earlier session note claimed. Both of the plan's named contract tests (`test_existing_suppress_events_unchanged`, `test_open_click_flag_off_noop`) are present and pass. `test_site_id_from_custom_args_or_skip` from the validate-contract's test-gate table is realized as the two separately-named tests `test_records_when_site_id_present` / `test_skips_when_site_id_absent` — same coverage, different function names than the contract literally listed.

## Test Infra Gaps Found

- No disposable-Postgres harness available in this sandbox for Hybrid-tier gates — this is the same environment gap already tracked at the program level for EvalLayer (`process/features/evallayer/backlog/program-docker-verification-gaps_NOTE_23-07-26.md`); this plan's equivalent is the new backlog note below.
- No SendGrid sandbox/replay harness exists in-repo for Agent-Probe-tier payload-shape verification — resolution path B (docs-seeker schema pull) remains the cheapest unresolved option per the plan's Known Gap section.

## SPEC Achievement

This plan is a single-feature plan, not phase-program-governed by an umbrella SPEC — the plan's own `## Acceptance Criteria` (AC1-AC8) function as its SPEC.

| AC | Criterion | Status | Evidence |
|---|---|---|---|
| AC1 | `company_graph` populated write-through on rDNS resolve, read before new lookup when fresh | **met** (unit) / gate-unrun (Hybrid persistence) | `test_company_graph.py::test_upsert_on_conflict` — unit logic proven; real-PG durability unproven this session |
| AC2 | `company_graph_enabled=False` byte-identical to current behavior | **met** | `test_company_graph.py::test_flag_off_is_noop` |
| AC3 | `_graph_node_by_email` returns full profile, not name-only | **met** | new unit test in Phase 1 unit file |
| AC4 | `identity_signals` receives events only when flag ON + all 4 write gates pass | **met** | `test_identity_signals.py` write-gate rejection tests (datacenter/proxy/suppressed/do_not_resolve) |
| AC5 | `corroborate_identity()` never independently creates/upgrades `IdentifiedVisitor` | **met** | `test_identity_signals.py::test_corroborate_never_creates_identified_visitor` + structural grep-verify this session |
| AC6 | Existing bounce/dropped/spamreport suppression unchanged | **met** | `test_sendgrid_open_click_webhook.py::test_existing_suppress_events_unchanged` |
| AC7 | `test_agent_origin_exclusion.py` stays green unmodified | **met** | 18 passed, file unmodified (confirmed this session) |
| AC8 | Both new migrations apply cleanly, chained after pending migrations, non-destructive | **unmet — Docker-gated, unrun** | migration chain structurally verified (revision headers) but `alembic upgrade head` never executed against any Postgres this session → backlog note |

**Unmet criterion → backlog:** AC8 → `process/features/visitors-identity/backlog/owned-data-layer-docker-verification_NOTE_23-07-26.md` (also covers the two Hybrid persistence gates for AC1/AC3's durability half, which are formally proving-tier Hybrid in the validate-contract, not separately-numbered ACs).

## Closeout Packet

1. **Selected plan path:** `process/features/visitors-identity/active/owned-data-layer_23-07-26/owned-data-layer_PLAN_23-07-26.md`
2. **Closeout classification: Keep in active/testing** — code-complete, unit-verified (875 passed), regression-clean (18 passed), but Hybrid-tier persistence + migration-apply gates never ran (Docker unavailable). Per this plan's own `## Phase Completion Rules`, CODE DONE ≠ VERIFIED.
3. **What was finished:** both internal phases (company_graph + identity_signals) fully implemented per Touchpoints, both migrations chained correctly, both flags default OFF, corroborating-only invariant structurally enforced.
4. **Verified:** unit logic (875 passed), regression (18 passed, agent-exclusion boundary), migration chain linearity (revision-header read). **Unverified:** real-Postgres persistence/conflict-update behavior, live migration apply/downgrade round-trip, SendGrid live payload shape.
4b. **Validate-contract:** present, inline in plan, `Gate: PASS` (23-07-26, `generated-by: outer-pvl`).
5. **Cleanup done:** plan Phase Loop Progress ticked through Step 7; this report written; backlog note to be written next; context docs to be updated next. **Still needed:** context (`all-context.md`, `_GUIDE.md`) updates, Tier-1 audits, process commit.
6. **Next valid state:** keep this task folder in `active/`; when a disposable Postgres+Redis becomes available, run the close sequence in the Docker-verification backlog note, re-run EVL for the two Hybrid gates + migration apply, then re-enter UPDATE PROCESS to move this folder to `completed/`.
7. **Commit checkpoint:** execution commits (`54cf384`, `94852a9`) and the plan/validate-contract commit (`24a0dcd`) already landed on `main` before this session started. This session's commit is process-only (report, backlog note, context, `_GUIDE.md`) — belongs after this UPDATE PROCESS pass, not before.
8. **Regression status:** `test_agent_origin_exclusion.py` (18 passed, unmodified) and `test_identity_resolver.py`-equivalent full-suite pass (875 passed) both checked and green; no fixes needed.
9. **SPEC achievement:** see table above — 7 of 8 ACs met; AC8 (+ the Hybrid persistence half of AC1/AC3) unmet pending Docker verification, routed to backlog, not silently marked done (vacuous-green ban honored).

### Forward Preview

**Test Infra Found:** none new this session (Docker gap already known and tracked repo-wide).

**Blast Radius Changes vs. plan:** `visitor_aggregator.py` (4 lines) was touched but not listed in the plan's Touchpoints (see D2) — still within the plan's declared MEDIUM blast-radius risk class, no schema/auth/billing surface added beyond what was planned.

**Commands to Stay Green:**
```bash
.venv/bin/python -m pytest tests/unit -q
.venv/bin/python -m pytest tests/unit/test_agent_origin_exclusion.py -q
```

**Dependency Changes:** none — no new package added; migration chain grew by 2 revisions (`f8a2c1d9b3e7`, `a3e9f1c7d2b5`), both additive/non-destructive.

## Drift Signal Scoring

Signals: (a) files touched ≥10 across both commits → +2; (b1) no `.claude/`/`.codex/` harness file touched → +0; (b2) no `README.md`/`AGENTS.md`/`process/development-protocols/` touched → +0; (c) 3+ memory-worthy observations this session (migration-chain drift D1, config-flag provenance D3, stale test-count claim correction) → +1; (d) no new task folder created/archived this session (existing folder updated in place) → +0; (e) no validate-contract deviation (execution matched the contract; Hybrid gates were always known-deferred, not a new deviation) → +0.

**Score: 3 (MEDIUM).**

Recommend UPDATE PROCESS -- significant changes detected.
