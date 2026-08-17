---
name: report:marketing-claims-gap-program-closeout
description: "Program-level UPDATE PROCESS closeout for the 3-phase marketing-claims-gap program — all phases EXECUTED + EVL-green, classification WITH_GAPS, plans kept in active/ pending container-gate closure"
date: 16-08-26
phase: program-closeout
status: COMPLETE_WITH_GAPS
feature: campaigns-outreach
plan: process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/marketing-claims-gap-umbrella_PLAN_16-08-26.md
metadata:
  node_type: memory
  type: report
  feature: campaigns-outreach
  phase: program-closeout
---

# Marketing Claims Gap — Program Closeout Report

**TL;DR:** All 3 phases are code-complete with every Fully-Automated gate green and zero
regressions (unit lane 2832 → 2863 → 2926, each delta exactly the new tests). No plan is
archived: every Hybrid/integration gate across all 3 phases is unrun because the Docker daemon
was down all session, so **no flag-ON path has ever executed** — per the ip-org G8/G10 vacuity
precedent, flag-OFF-only evidence does not prove the features work. Classification:
**WITH_GAPS / Keep in active/testing** for all 3 phase plans and the umbrella.

---

## Closeout Packet (program level)

1. **Selected plan path:** `process/features/campaigns-outreach/active/marketing-claims-gap_16-08-26/marketing-claims-gap-umbrella_PLAN_16-08-26.md` (umbrella) + 3 phase plans in the same task folder.
2. **Closeout classification:** **Keep in active/testing** — all three phase plans and the umbrella. NOT ready for UPDATE PROCESS archival.
3. **What was finished:** see §Per-Phase Summary below.
4. **Verified vs unverified:** Fully-Automated gates verified green by independent spawned vc-tester (EVL) for all 3 phases. Unverified: every integration/Hybrid gate, every migration live round-trip, and — critically — every flag-ON positive-path behavior. See §Known-Gap Inventory.
4b. **Validate-contract compliance:** all 3 phase plans carry a full `## Validate Contract` (Gate: CONDITIONAL, accepted). PVL was never skipped; 4 validate + 4 supplement cycles recorded in `results.tsv`.
5. **Cleanup done:** umbrella `## Current Execution State` rewritten (8-field); consolidated container-gate backlog note written; `all-context.md` updated (feature entry + stale Docker-claim correction); memory note written. **Still needed:** execution commit (vc-git-manager pass — deliberately not done here), container-gate closure, then re-classification toward VERIFIED and archival.
6. **Single best next valid state:** Invoke vc-git-manager for the execution commit, then run the container-gate closure per `process/features/campaigns-outreach/backlog/marketing-claims-gap-container-gates_NOTE_16-08-26.md` once Docker is up. Keep all plans active until then.
7. **Commit checkpoint:** Execution commit recommended before any further work — source changes across all 3 phases are uncommitted (hard safety constraint in the charter: "do not leave a phase's output uncommitted"). Process commit (this report, umbrella update, backlog note, context edits) follows separately.
8. **Regression status:** unit-lane full-suite run at each phase exit: Phase 1 → 2832/2skip, Phase 2 → 2863/2skip (+31 exactly), Phase 3 → 2926/2skip (+63 exactly) — zero regressions. vitest 174 → 185, tsc clean, alembic single head at each phase. Send-gate caller census re-run each phase: no new caller of `send_campaign_emails`.
9. **SPEC achievement:** program-level definition-of-done items 1–3 (umbrella charter) are each **unmet** at the "provable" bar — the code paths exist and are unit-proven, but no criterion's flag-ON automated/E2E gate has passed (all Hybrid gates blocked). Each unmet criterion is covered by the consolidated backlog note (test-building stubs = the exact re-run commands). Known-Gap is not a basis for "met" — hence no phase is VERIFIED.

---

## Per-Phase Summary (what shipped)

### Phase 1 — Demo booking (`phase-1-demo-booking_PLAN_16-08-26.md`)
- `Site.booking_url` (data field, not a flag) + migration `e4b1d78c3a05`; `{{booking_link}}` token threaded through `campaign_sender._personalize` and the campaign planner prompt; "Demo booked" ConversionGoal preset endpoint; third-party-link non-decoration hole test-locked as documented behavior.
- **Important provenance note:** the source code PRE-EXISTED this program's EXECUTE — migration `e4b1d78c3a05` was untracked at session start, authored by a concurrent session. The execute pass was a full source-verified audit and found an exact plan match; no defects.
- Gates green: unit-targeted 67, unit-full 2832/2skip, `send_campaign_emails` caller-census, validate-plan-artifact, non-vacuity spot-check. Closeout: WITH_GAPS.

### Phase 2 — ICP-fit scoring (`phase-2-icp-fit-scoring_PLAN_16-08-26.md`)
- Pure deterministic `icp_fit` 0–100 scorer against `Site.site_profile`; persisted on `IdentifiedVisitor`; surfaced in conviction copy; flag `icp_fit_enabled` (default OFF); migration `f6a3c81d5e27`.
- Beyond-plan wins: H-7 exception containment landed; H-9 tooltip gate upgraded Agent-Probe → Fully-Automated.
- Gates green: unit-targeted 31, unit-full 2863/2skip (+31 exactly, zero regressions), vitest 174, tsc clean, alembic single head `f6a3c81d5e27`, no new send caller, AC-2/AC-11 greps, AC-6 flag declared. Closeout: WITH_GAPS.
- Named known-gap: since-is-None gating + raise containment verified by source read only; the pinning tests live in the blocked integration lane.

### Phase 3 — Learning loop + benchmarks (`phase-3-learning-loop-benchmarks_PLAN_16-08-26.md`)
- Per-site campaign stats rollup; zero-PII cross-tenant category benchmark (k-floor 5, opt-in via `Site.contribution_enabled`); stats injected into planner/auto-drafter prompts + Monday digest; flag `campaign_benchmark_enabled` (default OFF); migration `a8c2f47e91b6` (current head).
- Non-vacuity verified: zero-PII table has no FKs; k-floor 5 enforced in code not comment; co-op consent block untouched; `/outcomes` grouped-aggregate shape preserved; scheduler guards re-derived NOT relaxed.
- Gates green: targeted-unit 75, unit-full 2926/2skip (+63, zero regressions), vitest 185/12files, tsc clean, alembic single head `a8c2f47e91b6`, no new send caller, validate-plan-artifact 0/0, contract grep/AST gates. Closeout: WITH_GAPS.

---

## PVL Trajectory

Baseline (outer PVL, 3 plans validated in one pass): **11 FAILs** (Phase 1: 5, Phase 2: 2,
Phase 3: 4) + 19 CONCERNs → after **4 validate cycles + 4 supplement cycles** (28 `results.tsv`
rows total): **0 FAILs, 0 open CONCERNs**, all three contracts closed
`CONDITIONAL-concerns-closed` (accepted). Full per-cycle detail: 7 PVL iteration reports per
phase family in this folder + `results.tsv`.

The two highest-value PVL catches — both of the "feature ships invisible with all gates green"
class that single-pass validation misses:
1. **Phase 1 send-path threading omission** — `{{booking_link}}` token would have been defined but never threaded through the actual send path; every gate would have passed while the shipped feature rendered nothing.
2. **Phase 2 detail-endpoint VisitorOut-seed unreachability** — `icp_fit` would have been persisted but unreachable from the detail endpoint (the exact P0 `GET /visitors` schema-class precedent), again with all planned gates green.

Captured as a durable memory note: `pvl-loop-catches-invisible-ship-defects.md`.

## EVL Results

Each phase's EVL was an independent spawned vc-tester re-run of the contract gates — all landed
`PASS-WITH-GAPS / HALTED_SUCCESS` in 1 cycle each (no fix cycles needed). Gate detail per phase
is in the three `*-evl-iteration-001_REPORT_16-08-26.md` files.

## Known-Gap Inventory (program-wide)

**Root blocker:** Docker daemon down all session (`~/.docker/run/docker.sock` missing); Postgres
`:5433` and Redis `:6379` both absent; only native `:5432` exists, which is FORBIDDEN (conftest
`drop_all` destroys the dev DB). Note this is a NEW failure mode vs. the documented
"CLI off PATH" gotcha — the lsof check was run and genuinely showed nothing.

| Phase | Blocked gate | What it must prove |
|---|---|---|
| 1 | integration AC-1/5/6 | booking-URL CRUD, draft render with real DB, goal-preset endpoint |
| 1 | migration round-trip AC-8 | `e4b1d78c3a05` live down/up on :5433 |
| 2 | `test_icp_fit_persistence.py` AC-6/7/8/9/15/16 | flag-ON scoring + persistence + detail-endpoint surface |
| 2 | AC-10 migration round-trip | `f6a3c81d5e27` live down/up on :5433 |
| 3 | AC-4/5/6/7 integration flag-ON+OFF pairing | benchmark job k-floor, digest line, prompt injection with flag ON |
| 3 | AC-11 migration round-trip | `a8c2f47e91b6` live down/up on :5433 |

**Vacuity precedent (why WITH_GAPS is mandatory):** per ip-org contract errata G8/G10,
flag-OFF-only evidence is vacuous. `icp_fit_enabled` and `campaign_benchmark_enabled` shipped
default OFF and **no flag-ON positive case has ever executed**. Re-run commands:
`process/features/campaigns-outreach/backlog/marketing-claims-gap-container-gates_NOTE_16-08-26.md`.

Additional open items (pre-existing, registered during this program):
- `backlog/emailsender-no-mock-branch_NOTE_16-08-26.md` — `EmailSender.send` ignores `MOCK_EXTERNAL_APIS`.
- `backlog/benchmark-k-floor-review_NOTE_16-08-26.md` — revisit k=5 as tenant count grows.
- Umbrella checklist P4 (marketing copy reconciliation pass) and P0 (site-analysis commit decision recorded in Phase 2 report) — P4 not yet done.

## Explicit Archival Decision

**The three phase plans and the umbrella are NOT archived to `completed/`.** All are classified
WITH_GAPS / "keep in active/testing". Rationale: the archival gate (vacuous-green ban) requires
every developed-behavior criterion to be met by a PASSING automated/E2E gate — here, no flag-ON
path has ever executed, so archiving would declare vacuously-green work done. The task folder
stays in `active/` until the container gates in the backlog note are green.

## Drift Signal Score

Signals: (a) ≥1 and ≥10 files touched (+2), (c) 3+ memory-worthy observations (+1),
(d) backlog NOTEs written (+1), (e) validate-contract deviations recorded (Phase 1 pre-existing
code; Hybrid gates unrun vs contract) (+1) → **HIGH (5 signals)**.
Strongly recommend UPDATE PROCESS -- harness/protocol files touched.
(This report IS that UPDATE PROCESS pass.)

## Next Valid State

`Invoke vc-git-manager for a logical execution commit, then close the container gates per the
backlog note; keep all marketing-claims-gap plans active until flag-ON gates pass.`
