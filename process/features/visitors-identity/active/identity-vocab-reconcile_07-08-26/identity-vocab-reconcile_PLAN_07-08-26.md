---
name: plan:identity-vocab-reconcile
description: "Reconcile devjulley onto main — retire main's verified/provider_candidate identity vocabulary in favor of devjulley's identified/candidate, widen emailability per D2, re-chain 2 alembic forks, resolve 7 rebase conflicts"
date: 07-08-26
feature: visitors-identity
---

# Identity Vocabulary Reconciliation — devjulley → main

**Complexity: COMPLEX** (single plan, not a phase program). Rationale per
`process/context/planning/all-planning.md`: this is one bounded rebase-and-merge operation with a
hard sequencing dependency (2 clean commits → migration re-chain → 7 conflict resolutions → call-site
sweep → verify → push), not 3+ independently-phaseable workstreams. It stays COMPLEX-in-one-plan
rather than a phase program because every step gates the next and there is no meaningful "phase
boundary" a fresh agent could pick up mid-way without the full context in this file.

This plan is **downstream of, and must stay consistent with**, the existing locked SPEC and
umbrella at `process/features/visitors-identity/active/identity-program_03-08-26/`
(`identity-program_SPEC_03-08-26.md`, esp. AC2 "candidates are still emailable" and AC8's call-site
reconciliation table; `identity-program-umbrella_PLAN_03-08-26.md`). That SPEC was written against
the devjulley baseline BEFORE this cross-branch divergence was discovered — this plan does not
re-derive or contradict it, it is the mechanical branch-reconciliation needed to land it on `main`
without silently reverting `main`'s independently-built vocabulary. Read that SPEC before EXECUTE.

---

**Date**: 07-08-26

---

## UPDATE PROCESS closeout note (07-08-26)

**Classification: keep in `active/` — NOT archived.** Code is executed and user-accepted (see
`EXECUTED AND ACCEPTED` block below), but the plan-lifecycle bar for archival is not met:
`devjulley` is unpushed (`ahead 32, behind 5` vs `origin/devjulley`), and 3 human actions from the
execute report §9 remain outstanding (live prod pre-check, the push decision, and the migration
re-chain has not been applied — see "Migration head status" in `all-context.md`). Archive once
pushed and the prod pre-check is run. Bookkeeping backfilled this session: PVL iteration reports
007/008/009 were reconstructed from `results.tsv` (they never existed on disk — see each report's
`reconstructed_note`); the `is_privacy_relay_ip` known-gap has a backlog note:
`process/features/visitors-identity/backlog/resolver-privacy-relay-callsite-coverage_NOTE_07-08-26.md`.

## EXECUTED AND ACCEPTED — status block (PLAN supplement cycle 9, S23)

**Status: EXECUTED — result accepted by the user. Gate: CONDITIONAL, accepted.** The remaining
supplement items applied this cycle (S20, S21, S22) are **plan-text corrections for archival
accuracy and future reference — NOT outstanding code work.** The shipped code is correct on every
one of them; see the spot-verification table below.

**Governance record (factual):**

- The rebase was executed by a **concurrent session while PVL cycle 8 was still open** and the gate
  was `CONDITIONAL` with `Accepted by: PENDING`. That execute-agent self-flagged the discrepancy in
  its own report (`identity-vocab-reconcile-execute_REPORT_07-08-26.md`): it saw `results.tsv` row 7
  stating "EXECUTE is NOT yet unblocked" but the plan on disk still carried cycle 6's stale contract,
  and proceeded.
- **The orchestrator spot-verified the executed result and reported the findings to the user**
  (privacy guard present; E-8 gate correct; E-9 clean; no duplicate test classes; `IntegrityError`
  handler correct). **On the basis of that report — not a personal review of the diff or code — the
  user directed that the result be kept and the plan text corrected**, instructing verbatim:
  *"giữ kết quả, sửa §3.2, xác nhận nốt MissingGreenlet"* ("keep the result, fix §3.2, confirm the
  MissingGreenlet item"). The Validate Contract's
  `Accepted by:` marker is set to record the user's acceptance of the CONDITIONAL gate this session,
  replacing `PENDING`. That acceptance is **retroactive to an already-completed EXECUTE**.

**Current state (re-derived live at PLAN supplement cycle 9, 07-08-26):**

| Fact | Value | Reproducing command |
|---|---|---|
| `devjulley` tip | `5293cbc` — rebased onto `main` | `git rev-parse --short devjulley` |
| `main` tip | `332b3a8` | `git rev-parse --short main` |
| Mid-rebase? | no — `HEAD` is `refs/heads/devjulley`, not detached | `git symbolic-ref -q HEAD` |
| Pushed? | **NO — nothing pushed** (`ahead 32, behind 5` vs `origin/devjulley`) | `git status --short --branch` |

**Orchestrator spot-verification of the executed result — all confirmed present/correct:**

| Item | Check | Result |
|---|---|---|
| `is_privacy_relay_ip` guard (S20) | `git grep -c "is_privacy_relay_ip" devjulley -- apps/api/services/identity_resolver.py` | **2 hits — the guard SURVIVED** |
| E-8 corrected gate | `apps/api/routers/events.py:591` | `if fp_value or fp3_value or svid:` — correct |
| E-9 vocabulary sweep | zero `VERIFIED_STATUSES` in `dashboard.py`, `visitors_helpers.py`, `kpi.py`, `timeseries.py` | clean |
| `IntegrityError` handler (S21) | `conflict_visitor_id`/`conflict_site_id` read BEFORE `try: await self.db.commit()` (~L1181-1185); devjulley upsert semantics + `save_identified_conflict_upsert` event name used inside the handler | **hybrid form shipped correctly** |
| `tests/integration/test_events_ingest.py` | 5 classes, zero duplicate class names | clean |

---

**Status (historical — pre-execution planning trail)**: DRAFT — PLAN supplement cycle 5 applied (S12-S15), resolving PVL cycle 4's Finding 7
(Gate: BLOCKED — `devjulley`'s real tip had moved past what the plan documented). The plan is now
**derivation-based**: every branch-tip fact (commit list, migration set, `main` head) is re-derived
live by EXECUTE rather than hardcoded, per explicit user decision (U2) — the branch is NOT frozen and
may move again. `ae7ffb9` (fingerprint v3) is folded into the Implementation Checklist, Touchpoints,
§3.2, and a new §3.10 conflict spec (U1 — absorbed into this reconciliation, not split off). Pending
VALIDATE re-run (PVL cycle 5, from V1). Do not proceed to EXECUTE until that cycle passes.
**Complexity**: COMPLEX

## Overview

`main` (as of PLAN supplement cycle 5: `332b3a8`, i.e. `f77085b` +1 unrelated commit) and
`devjulley` (as of this same session: `ae7ffb9`, one commit ahead of the `1c5ae32` this plan was
originally written against, and NOT pushed to `origin/devjulley`) independently built the same
"identity honesty" feature (unconfirmed-vs-confirmed visitor identity tiering) with incompatible
vocabularies and opposite emailability rules. **`devjulley` is not frozen for the duration of this
reconciliation — it may move again before EXECUTE runs.** Per explicit user decision (U2, PLAN
supplement cycle 5), this plan is written to DERIVE the branch tip at EXECUTE time rather than
hardcode it: every place below that states a commit list, a migration set, or a head hash is paired
with the exact `git`/`alembic` command that re-produces it live, and the currently-observed values
are recorded as informational snapshots only ("as of 07-08-26 this was X"). This plan reconciles
`devjulley` onto `main`: adopts devjulley's `identified`/`candidate` vocabulary (D1), adopts
devjulley's wide emailability rule behind a new default-OFF flag (D2/D5), re-chains devjulley's
Alembic migration sub-chain onto main's head, and resolves the 8 known rebase conflicts (7 original +
1 added at PLAN supplement cycle 5 for `ae7ffb9`, U1) plus the additional call-site sweep discovered
by reading the code. See "Locked Decisions" immediately below for the full decision set
this plan does not re-open (NOTE: D10 was SUSPENDED at PVL cycle 2 — see Validate Contract Findings
4-6 — and has now been REDESIGNED and re-locked at PLAN supplement cycle 3, per S6-S11 below. The
new design implements the confirm-gate as a wrapper check at 3 of the 5 named production call sites,
leaving `is_emailable_identity()` itself byte-for-byte unchanged. See Locked Decisions D10.).

## Acceptance Criteria

1. `devjulley` rebases (or merges) onto `main` cleanly — zero unresolved conflicts, one commit
   history the team can work from. **"devjulley" means whatever `git rev-parse devjulley` and
   `git log main..devjulley --oneline` resolve to at EXECUTE time (see the mandatory EXECUTE
   pre-flight re-derivation, Implementation Checklist step 0) — as of PLAN supplement cycle 5 that is
   6 commits (`ae7ffb9`, `1c5ae32`, `fe89466`, `626d643`, `a066006`, `e11a91d`), not the 5-commit list
   this plan originally shipped with. Do not treat either count as frozen.**
2. `alembic -c apps/api/alembic.ini heads` prints exactly one head after the re-chain (§5).
3. Zero references to `verified`/`provider_candidate`/`identity_status_for_provider`/
   `VERIFIED_STATUSES`/`STATUS_VERIFIED`/`STATUS_PROVIDER_CANDIDATE` remain anywhere in
   `apps/api/**` or `tests/**` (§4 sweep is exhaustive).
4. `candidate_outreach_enabled` flag exists, defaults `False`, and its OFF-state behavior is
   documented and tested (§6) — **redesigned at PLAN supplement cycle 3 (S6-S11) as a call-site
   wrapper, not a change to `is_emailable_identity()`'s own signature; pending VALIDATE re-confirmation
   that this satisfies the criterion.**
5. Every devjulley-only feature (confirm/reject, promotion sweep, orphan ingest metrics,
   `confirmed_at`, contact import, hot contacts, candidate funnel/series) still passes its own tests
   post-merge (D3) — **the PVL cycle 2 conflict with D10 is resolved by the cycle-3 redesign, which
   keeps `is_emailable_identity()` byte-for-byte unchanged; pending VALIDATE re-confirmation.**
6. Every main-only feature (Leadpipe webhook push, per-site Leadpipe pixels, provider-outage
   separation, resolution deferral watermark, RB2B rework, agent/EvalLayer surfaces) still passes
   its own tests post-merge (D4).
7. All verification gates in §7 are green (or explicitly Known-Gap per program precedent).
8. `devjulley` is pushed with `--force-with-lease` (never plain `--force`) after passing gates.

## Phase Completion Rules

This is a single-plan COMPLEX task, not a phase program — there is one completion state, not
per-phase ✅/🚧/⏳ tracking. The plan is CODE DONE when §2 steps 1-13 have all run and §7's gates are
green (or Known-Gap per precedent); it is VERIFIED only after the live pre-push re-check (§5 step 0,
second run) confirms no new `verified`/`provider_candidate` rows slipped in during EXECUTE and the
app-boot smoke test passes against the re-chained migration head.

**PLAN supplement cycle 3 note:** §3.1 (D5/D10 wiring), §3.7 (test rewrite list), §4 (call-site
sweep), and §6 (D10 OFF-state design) have been reworked per S6-S11 — the confirm-gate is now a
wrapper at 3 of the 5 named production call sites, and `is_emailable_identity()` itself is unchanged.
This is not yet re-validated — VALIDATE (PVL cycle 3, from V1) must confirm the redesign before
EXECUTE. See Validate Contract for the PVL cycle 2 evidence trail that drove this redesign.

## Implementation Checklist

**MANDATORY EXECUTE PRE-FLIGHT (run FIRST, before step 1, every time EXECUTE starts or resumes —
this is the anti-recurrence mechanism for PVL cycle 4's Finding 7, not a footnote):**
```bash
git rev-parse main
git rev-parse devjulley
git log main..devjulley --oneline
git diff --name-only main...devjulley -- apps/api/migrations/versions/
```
Compare the output against what this plan last recorded (as of PLAN supplement cycle 5: `main` =
`332b3a8`; `devjulley` = `ae7ffb9`, 6 commits `ae7ffb9,1c5ae32,fe89466,626d643,a066006,e11a91d`, 4
migration files `b1c9e7f24d83,c2f8a5d31e97,e9d2a4c71f68,f1a7c3e05b92`). **If the commit list, the
migration file set, or `main`'s head differs from what is recorded here: STOP. Do not proceed on the
stale assumption.** Return to PLAN (a fresh PLAN-supplement pass) to fold the delta into this
Checklist, Touchpoints, and the relevant `§3.x` conflict spec — exactly the same process this cycle
(S12-S15) just ran for `ae7ffb9`. Only proceed past this pre-flight when the live output matches (or
you have just finished re-deriving and re-locking a supplement for a fresh delta).

**Sequencing note (VALIDATE Finding 1 / Execute-Agent Instruction E1):** the order below is the
CORRECTED order. The migration file
`apps/api/migrations/versions/b1c9e7f24d83_add_identified_visitor_confirmed_at.py` is introduced by
rebasing commit `626d643` (step 3) — it does not exist in the working tree before that step
completes. Re-chaining its `down_revision` (step 5) therefore cannot run before step 3. Do not run
any `alembic` command (including `alembic heads`) between steps 2 and 3 — the tree will contain a
dangling `down_revision` reference in `c2f8a5d31e97_add_is_imported_contact.py` during that window,
which is expected and harmless as long as no alembic command runs.

**PVL cycle 2 — independently re-verified (05-08-26 session dated in error above, actually 07-08-26):
this sequencing note is CORRECT and sufficient.** Re-derived the true migration dependency chain via
the real `alembic history` tool (not hand-parsed): `626d643` introduces `b1c9e7f24d83` (parent =
fork point `a7d419e6c052`), `a066006` introduces `c2f8a5d31e97` (parent = `b1c9e7f24d83`), `e11a91d`
introduces `e9d2a4c71f68` (parent = `c2f8a5d31e97`). This confirms step 2 (`e11a91d`+`a066006`)
DOES land before step 3 (`626d643`) in this checklist, and BOTH of the migration files introduced in
step 2 have `down_revision` values that will not exist until step 3 completes — i.e. the "dangling
window" is two files deep (`c2f8a5d31e97` AND `e9d2a4c71f68`), not just one. The checklist's blanket
instruction ("do NOT run any alembic command between steps 2 and 3") already correctly covers this
wider window — re-confirmed safe, no change needed. No pre-commit hook or CI check in this repo
invokes alembic at import/collection time (checked `main.py`, `config.py`, test collection — clean),
so the window is genuinely inert as claimed.

1. Live pre-check: alembic head + `visitors.identity_status` row counts (§5 step 0).
2. Cherry-pick/rebase `e11a91d`, `a066006` onto `main` (git-mechanical only — do NOT run any
   `alembic` command until step 5 completes; see sequencing note above).
3. Rebase `626d643` (identity) — resolve `identity_classification.py` (§3.1), `identity_resolver.py`
   (§3.2), `kpi.py` (§3.3), `timeseries.py` (§3.4), `dashboard.py` (§3.5), `visitors_helpers.py`
   (§3.6), `test_identity_classification.py` (§3.7). **This step is what introduces
   `b1c9e7f24d83_add_identified_visitor_confirmed_at.py` — step 5 cannot run before this step
   completes. §3.1 is a pure vocabulary adopt-devjulley — `is_emailable_identity()` itself is
   UNCHANGED (D10 redesign, S6); do not add a `candidate_outreach_enabled` parameter here.**
4. Spot-check (E3): confirm `tests/unit/test_agent_origin_exclusion.py`,
   `tests/unit/test_handoff_emailability_separation.py`, and
   `tests/unit/test_outbound_identity_gate.py` do NOT reference the retired `EMAILABLE_PROVIDERS`
   symbol post-rebase (§3.7 tail). **Sufficient as of the D10 redesign (S6): since
   `is_emailable_identity()`'s signature and body are unchanged, all pre-existing
   `is_emailable_identity(<graph-candidate provider>) is True` assertions in these 3 files (plus
   `test_identity_classification.py`) require zero modification — confirm this spot-check plus a
   full unmodified pass of all 4 files (§7 gate) once §3.1 lands.**
5. NOW re-chain `b1c9e7f24d83`'s `down_revision` onto main's confirmed current head (§5 step 1) —
   only valid after step 3 has introduced the file.
6. Verify single alembic head offline (§5 step 3).
7. Offline `--sql` validate the full migration chain (§5 step 4).
8. Sweep the 3 test files that break without being git conflicts:
   `test_identity_quality_gates.py`, `test_leadpipe_webhook.py`,
   `test_leadpipe_webhook_persistence.py` (§3.7 tail, §4 table).
9. Rewrite `routers/visitors.py:1045` write path per §4's `STATUS_VERIFIED` row.
10. Rebase `fe89466` — resolve `status-badge.tsx` (§3.8) and `test_events_ingest.py` (§3.9, merge
    both test classes, do not pick a side).
11. Rebase `1c5ae32` (process artifacts — expect clean).
12. **(NEW at PLAN supplement cycle 5, S13)** Rebase whatever commit(s) the step-0 pre-flight shows
    beyond `1c5ae32` — as of this cycle that is `ae7ffb9` (fingerprint v3) alone. Resolve
    `identity_resolver.py` per the §3.2 extension (fp3-aware fingerprint match, additive — does not
    touch the `identity_status`/vocabulary write logic §3.2's original spec already covers) and
    `apps/pixel/src/tracker.js` per §3.10 (confirmed clean content-merge via `git merge-tree`, take
    both sides). This step also introduces migration `f1a7c3e05b92_add_fingerprint_v3.py`
    (`down_revision = "e9d2a4c71f68"`) — no re-chain action needed for this file itself (its parent is
    already correct), it simply extends the tail of the sub-chain step 14 re-points the ROOT of.
13. Implement the `candidate_outreach_enabled` confirm-gate as a WRAPPER at exactly 3 of the 5
    originally-named call sites — `services/campaign_sender.py` (send gate), `services/csv_exporter.py`
    (export), `routers/campaigns.py` (`_resolve_linkedin_targets`) — per §6's redesigned, per-site
    spec. **`services/hot_alert.py` and `services/outcome_digest.py` are explicitly EXCLUDED from the
    wrapper** — their `is_emailable_identity()` calls gate owner-facing name-reveal/ranking, not
    outreach-to-candidate; see §6 for the reasoning. `is_emailable_identity()`'s own signature and
    body are NOT touched by this step (D10 redesign, S6).
14. Add `candidate_outreach_enabled: bool = False` to `apps/api/config.py` (§6). (This step alone —
    the config setting — is NOT blocked; only the function-signature wiring in step 13 is blocked.)
    **Note:** the migration re-chain itself already happened at step 5 (before step 12 introduced the
    new tail migration `f1a7c3e05b92`) — step 5 only ever re-points the ROOT
    (`b1c9e7f24d83.down_revision`), which step 12's later-landing tail migration does not disturb; no
    additional re-chain action is needed here. Re-verify single head (§5 step 3) after step 12 lands,
    same as after step 6, to catch any drift the pre-flight didn't.
15. Live pre-push re-check: re-run §5 step 0; run contingency backfill only if new
    `verified`/`provider_candidate` rows appeared.
16. Run the full verification suite (§7) — including the new pixel/e2e gates added at PLAN supplement
    cycle 5 for `ae7ffb9` (§7 table); fix failures inline before proceeding.
17. Confirm the §10 open items remain closed before calling the plan CODE DONE.
18. `git push --force-with-lease origin devjulley`.

## Locked Decisions (from RESEARCH — not re-opened by this plan)

- **D1** — Canonical vocabulary = devjulley's: `identified` (confirmed) / `candidate` (unconfirmed).
  `main`'s `verified` / `provider_candidate` / `identity_status_for_provider()` / `VERIFIED_STATUSES`
  are retired.
- **D2** — Emailability = devjulley's WIDE rule (`identity_level(provider) == "person"`). RB2B /
  Leadpipe / Capturify identities become emailable, restrained instead by the personalization gate
  (generic copy only for candidates). This is SPEC AC2 (Locked Decision #2) of the existing locked
  program.
- **D3** — Everything devjulley adds must survive intact (candidate confirm/reject, promotion sweep,
  orphan ingest metrics, `confirmed_at`, contact import, hot contacts, candidate funnel/series, full
  new test suite). **Resolved at PLAN supplement cycle 3 (S6):** D10 is now redesigned as a call-site
  wrapper that leaves `is_emailable_identity()` byte-for-byte unchanged, so D3's "full new test suite"
  survives intact by construction — no conflict remains. Pending VALIDATE re-confirmation.
- **D4** — Everything main adds must survive intact (Leadpipe webhook push, per-site Leadpipe
  pixels, provider-outage/no-match separation, resolution deferral watermark, RB2B rework,
  agent/EvalLayer surfaces).
- **D5** — New flag `candidate_outreach_enabled` (default OFF, `agent_detection_enabled` precedent)
  gates the D2 WIDENING only. Merge must not change prod send behavior by itself. **The "zero
  production behavior change" promise is corrected at PLAN supplement cycle 3 (S9) — see §9 and the
  Hard Stop text for the precise, now-accurate wording of what the OFF-state does and does not permit
  (the human confirm action remains a real, deliberate exception, now named explicitly rather than
  contradicting this promise).**
- **D9 (this plan's own addition, see §9)** — the reconciliation, once merged AND the flag enabled,
  widens who Beam may email. This is the accept/reject decision already made in D2 — this plan makes
  it auditable (flag default OFF, explicit enable log, dated note) rather than re-litigating it.
- **D10 (originally decided at VALIDATE cycle 1 as an in-helper signature change; SUSPENDED at PVL
  cycle 2 — see Validate Contract Findings 4-6; REDESIGNED and RE-LOCKED at PLAN supplement cycle 3,
  S6/S10) — the `candidate_outreach_enabled` OFF-state adopts a confirm-gated posture, implemented as
  a WRAPPER check at 3 of the 5 named production call sites, ANDed with the result of the unchanged,
  3-parameter `is_emailable_identity()` — NOT as a parameter on that shared helper.** Cycle 1's
  original formulation (adding a 4th `candidate_outreach_enabled` parameter directly to
  `is_emailable_identity()`) was rejected at PVL cycle 2: it was not implementable as specified
  (Finding 4 — the binding signature omitted the `identity_status` parameter the body logic needed)
  and it directly broke devjulley's own pre-existing, intentional test suite (Finding 5 — including
  `test_is_emailable_identity_still_takes_exactly_three_params`, whose own docstring states it exists
  to catch exactly this kind of change), contradicting Locked Decision D3. The wrapper-based
  redesign matches the existing locked SPEC's explicit architectural guidance ("the new
  personalization-gating requirement lands in the campaign draft/send composition layer, not in
  `is_emailable_identity()` itself") and keeps `is_emailable_identity()` byte-for-byte unchanged, so
  D3 is satisfied by construction. See §3.1 and §6 for the full per-site wiring spec. This history is
  kept auditable rather than silently rewritten — the rejected in-helper formulation remains struck
  through in §3.1/§6 for the record.

---

## Touchpoints

(See also Blast Radius and Public Contracts below — this plan interleaves them in one table per touchpoint tier.)

### 1. Touchpoints and Blast Radius

Tier 0 = zero-conflict cherry-pick. Tier 1 = migration chain (structural, no logic risk but wrong
head = broken boot). Tier 2 = the 3 files that decide vocabulary + emailability (**highest risk —
these determine who gets emailed**). Tier 3 = downstream readers that must be swept but carry no new
decisions. Tier 4 = unrelated/incidental conflicts. Tier 5 (NEW, PLAN supplement cycle 5, S13) =
`ae7ffb9`'s (fingerprint v3) own additive footprint — unrelated to emailability, but must be carried
forward, not dropped.

**Commit/migration/conflict counts below are informational snapshots as of PLAN supplement cycle 5
(07-08-26) — always re-derive live per the Implementation Checklist's mandatory pre-flight before
trusting them.**

| Tier | File | Why touched | Risk |
|---|---|---|---|
| 0 | (whole commits `e11a91d`, `a066006`) | clean cherry-pick, no identity vocab overlap | Low |
| 1 | `apps/api/migrations/versions/b1c9e7f24d83_add_identified_visitor_confirmed_at.py` | re-chain `down_revision` onto main's live head (only after `626d643` lands — see Implementation Checklist sequencing note) | Medium (wrong head = 2 heads = boot failure) |
| 1 | `apps/api/migrations/versions/c2f8a5d31e97_add_is_imported_contact.py`, `e9d2a4c71f68_add_site_tombstones.py` | chain unchanged, downstream of the re-chained root | Low (mechanical) |
| 1 (NEW, S13) | `apps/api/migrations/versions/f1a7c3e05b92_add_fingerprint_v3.py` | introduced by `ae7ffb9`; `down_revision = "e9d2a4c71f68"` already correct — extends the tail, no re-chain edit needed, just confirm single-head after it lands | Low (mechanical, already-correct parent) |
| 2 | `apps/api/services/identity_classification.py` | vocabulary constants only — `is_emailable_identity()` itself is UNCHANGED (D10 redesign, S6) | High (vocabulary-only, no longer blocked) |
| 2 | `apps/api/services/identity_resolver.py` | writes `Visitor.identity_status`; must call the surviving classifier fns. **Extended at PLAN supplement cycle 5 (S13):** `ae7ffb9` adds a 43+/14- delta to this same file (fp3-aware fingerprint match + BeamIdentityNode fp3 backfill, confidence 0.80 vs 0.75) — verified purely additive and non-overlapping with the vocabulary write logic (`identity_status = "candidate" if is_graph_candidate_provider(...) else "identified"` at lines ~899/951 is untouched by `ae7ffb9`). See §3.2 extension. | **Highest** |
| 2 | `apps/api/services/campaign_sender.py` (send gate ~L283 + personalization gate ~L144/190) | emailability + personalization gates + NEW: confirm-gate wrapper (reorders the existing `identity_status` query from after the gate to before it — no new query, see §6) | **Highest — concrete reorder spec in §6, no longer speculative** |
| 3 | `apps/api/routers/visitors.py` | confirm/reject endpoints write `STATUS_VERIFIED`-shaped literal on main; must write `identified` | High |
| 3 | `apps/api/routers/visitors_helpers.py` | list/filter queries by status | High |
| 3 | `apps/api/routers/dashboard.py` | funnel counts | High |
| 3 | `apps/api/services/kpi.py` | funnel + qualified-lead rates | High |
| 3 | `apps/api/services/timeseries.py` | daily identified/candidate series | High |
| 3 | `apps/api/routers/campaigns.py:725`, `apps/api/services/csv_exporter.py:79` | 2 more genuine outreach-to-candidate call sites — each needs a NEW `Visitor.identity_status` query added (neither currently fetches it) plus the wrapper check, see §6 | Medium — concrete new-query spec in §6 |
| 3 (EXCLUDED from wrapper) | `apps/api/services/hot_alert.py:88`, `apps/api/services/outcome_digest.py:161` | **Re-scoped at PLAN supplement cycle 3 (S7):** both call sites use `is_emailable_identity()` for owner-facing name-reveal/ranking, not outreach-to-candidate — they are explicitly EXCLUDED from the confirm-gate wrapper. No code change. See §6 for the reasoning. | Low (no change) |
| 3 | `apps/web/src/components/ui/status-badge.tsx` | tone map: `verified`/`provider_candidate` → `candidate` | Medium |
| 3 | `apps/web/src/lib/api-types.ts` | devjulley's Phase 4 contact-import + hot-contacts types must survive; no `verified`/`provider_candidate` literal types to strip (both branches type `identity_status` as `string`) | Low |
| 3 | `tests/unit/test_identity_classification.py`, `tests/unit/test_identity_quality_gates.py`, `tests/unit/test_leadpipe_webhook.py`, `tests/integration/test_leadpipe_webhook_persistence.py` | assert retired `STATUS_VERIFIED`/`STATUS_PROVIDER_CANDIDATE` strings — must be rewritten to `identified`/`candidate` semantics. **Resolved at PLAN supplement cycle 3: `test_identity_classification.py`'s pre-existing `is_emailable_identity` assertions require ZERO modification — the D10 wrapper redesign (S6) does not touch that function, so only the vocabulary rewrite applies here, exactly as originally planned.** | High |
| 3 (NEW) | `tests/unit/test_candidate_outreach_gate.py` (new file — does not exist yet) | New dedicated unit tests for the wrapper behavior at the 3 in-scope call sites (§6/S8) | Medium (new test file, additive) |
| 4 | `tests/integration/test_events_ingest.py` | conflict is **unrelated to identity vocab** — main added `TestCookieFpPhase2` (CORS/cookie-fp), devjulley added `TestUnknownSiteObservability` (403 structured logging). Both test classes are additive and non-overlapping in behavior. | Low (content-merge, not override) |
| 5 (NEW, S13) | `apps/pixel/src/tracker.js` | **8th conflict — main (2 commits: XHR `withCredentials` block ~L232, Leadpipe vendor-config injection ~L629) and `ae7ffb9` (fingerprint v3 probes, `fontFp()`/`audioFp()`, ~L124-266) independently edited the same file. Confirmed via `git merge-tree` (not assumed): the two edits occupy disjoint line ranges and the merge tool reports "Auto-merging apps/pixel/src/tracker.js" with ZERO conflict markers — genuinely clean, unlike `test_events_ingest.py`'s manual-concatenate case. See §3.10 for the resolution spec.** | Low (confirmed clean content-merge, not assumed) |
| 5 (NEW, S13) | `apps/pixel/src/tracker.min.js` | build artifact — **rebuild via `npm run build` (`apps/pixel/package.json`'s `build` script, esbuild) after §3.10 lands; do NOT hand-merge or take one side.** Repo's committed gate: `<6KB gzipped` (raised from `<5KB` by `ae7ffb9` itself — `apps/pixel/package.json`'s description string + enforced in `tests/unit/test_pixel_fingerprint.py` `< 6000` bytes and `tests/unit/test_pixel.py` `< 6144` bytes; verify with `apps/pixel`'s `npm run size` script post-rebuild). | Medium (must rebuild, not merge; verify against the now-6KB, not the stale 5KB, gate) |
| 5 (NEW, S13) | `apps/pixel/package.json` | devjulley-only 1-line description-string edit (5KB→6KB gate wording) — confirmed clean via `git merge-tree` (not in the conflict list), take devjulley's version | Low |
| 5 (NEW, S13) | `apps/api/routers/events.py` | **9th conflict, genuinely non-trivial — NOT a simple content-merge, unlike `tracker.js`.** Confirmed via `git merge-tree`. Both branches independently rewrote the SAME `_process_signal_events` fingerprint-write block: main replaced the two separate `UPDATE...WHERE x IS NULL` statements with a single `pg_insert(...).on_conflict_do_update(...)` upsert-stub (fixes a race where the `Visitor` row doesn't exist yet when this runs — COALESCE write-once on `fingerprint`/`server_visitor_id`, `LEAST()` on `first_seen`); devjulley kept the original two-UPDATE shape but added a third write-once UPDATE for `fingerprint_v3`/fp3. **Concrete resolution (§3.11):** port devjulley's fp3 write-once logic INTO main's upsert-stub shape — add `fingerprint_v3=fp3_value` to the `pg_insert(...).values(...)` call and a third `"fingerprint_v3": sa_text("COALESCE(visitors.fingerprint_v3, EXCLUDED.fingerprint_v3)")` entry to the `on_conflict_do_update` `set_={}` dict, alongside the existing `fingerprint`/`server_visitor_id`/`first_seen` entries. Do not simply pick a side. | Medium-High (real logic merge, not content-concatenation) |
| 5 (NEW, S13) | `apps/api/schemas/events.py`, `apps/api/models/visitor.py`, `apps/api/models/beam_identity.py`, `.gitignore` | additive fp3 wiring (`fp3` event field, `fingerprint_v3` columns) — did not appear in the `git merge-tree` conflict list, confirmed clean, take devjulley's additions as-is | Low |
| 5 (NEW, S13) | `process/context/all-context.md` | `ae7ffb9` appended its own "Pixel size budget raised" section — additive, take both sides' additions (this reconciliation's own context updates, if any, land alongside it, not instead of it) | Low |
| 5 (NEW, S13, verification only) | `apps/pixel/e2e/fingerprint-v3.spec.ts` (new file), `tests/unit/test_pixel.py`, `tests/unit/test_pixel_fingerprint.py` | new/updated tests for fp3 — carry forward unmodified, add to §7 Verification Evidence | Low (additive test coverage) |
| — | `apps/api/config.py` | add `candidate_outreach_enabled: bool = False` (D5) | Low (additive) |
| — (read-only, no code change expected) | `tests/unit/test_agent_origin_exclusion.py`, `tests/unit/test_handoff_emailability_separation.py`, `tests/unit/test_outbound_identity_gate.py` | E3 spot-check confirms no `EMAILABLE_PROVIDERS` reference survives post-rebase (still true). **Resolved at PLAN supplement cycle 3: the wrapper-based D10 redesign (S6) leaves `is_emailable_identity()`'s own behavior untouched, so these files' pre-existing `is_emailable_identity(<graph-candidate-provider>) is True` assertions require zero changes — the original "no code change expected" framing is restored, now unconditionally (not "depends on redesign direction").** | Low |

## Public Contracts

**Public Contracts affected:** `Visitor.identity_status` string values (`identified`/`candidate`
replace `verified`/`provider_candidate`/`identity_status_for_provider` return values); `GET
/api/v1/dashboard*` funnel shape (devjulley's `candidates` key must be present — main's dashboard.py
did not have it); no wire-schema breaking change — `string` typed on the TS side both branches.

**`is_emailable_identity()` function signature — HARD CONSTRAINT, locked at PLAN supplement cycle 3
(S6):** this function's signature and body are NOT touched by this reconciliation. It stays exactly
as devjulley wrote it — 3 parameters (`provider`, `source_agent_visit_id=None`,
`is_abuse_flagged=False`) — enforced by devjulley's own
`tests/unit/test_identity_classification.py::test_is_emailable_identity_still_takes_exactly_three_params`,
which asserts this as a "Hard constraint: this phase must not widen the emailability signature."
Cycle 1's original design (adding a `candidate_outreach_enabled: bool = False` 4th parameter) is
REJECTED per PVL cycle 2 Findings 4-6 and is not re-attempted by this plan. The
`candidate_outreach_enabled` confirm-gate is implemented entirely as a wrapper at 3 of the 5 named
call sites instead — see §6.

## Blast Radius

**Blast radius total — RECOMPUTED at PLAN supplement cycle 3 (S8), superseding the ~35-figure above,
which was driven by a signature change that has now been reverted.** With `is_emailable_identity()`
unchanged (D10 redesign, S6), all 35 of the original callers (5 production + 30 test, both PVL cycles
independently confirmed via `git grep`) require **zero code change from the D10 wiring itself** — the
5-production/30-test split from cycle 1/2 is retained above purely as the "no change needed"
regression baseline, not as this reconciliation's active blast radius for the emailability work.

The ACTUAL new blast radius introduced by the D10 wrapper redesign, re-derived via `git grep
"is_emailable_identity" apps/api/services/campaign_sender.py apps/api/services/csv_exporter.py
apps/api/routers/campaigns.py` plus a fresh read of each site's surrounding code (not inferred):

- **3 production call sites receive the wrapper:** `services/campaign_sender.py` (send gate — reorder
  an EXISTING query, no new query), `services/csv_exporter.py` (export — 1 NEW query per segment
  member, 1 NEW import `Visitor`), `routers/campaigns.py` `_resolve_linkedin_targets` (1 NEW query per
  visitor in the loop; `Visitor` already imported).
- **2 named call sites are EXPLICITLY EXCLUDED** (`services/hot_alert.py`, `services/outcome_digest.py`
  — owner-facing name-reveal/ranking use of `is_emailable_identity()`, not outreach-to-candidate; see
  §6). Zero code change to either.
- **1 new test file:** `tests/unit/test_candidate_outreach_gate.py` (does not exist yet) covering the
  wrapper's OFF/ON behavior at the 3 in-scope sites.
- The ~17 vocabulary-rewrite files itemized above (5 Tier-2/3 backend logic files, 5 Tier-3 downstream
  backend readers, 4 test files, 2 web files, 1 config addition) are UNCHANGED by this recomputation —
  they were never part of the D10 signature-change blast radius in the first place.

No new dependency, no new runtime surface. Single feature area (visitors-identity) plus one config
addition. This recomputed figure (3 production sites + 1 new test file, vs. the original ~35) is the
accurate real-world footprint of the wrapper-based redesign — the 35-figure remains valid ONLY as a
"must stay green, zero modifications" regression count, never as "files this plan changes."**

**ADDITIONAL blast radius from `ae7ffb9` (fingerprint v3), folded in at PLAN supplement cycle 5
(S13) — unrelated to emailability, orthogonal to the D10 wrapper work above:** 1 new migration
(`f1a7c3e05b92`, tail-only, no re-chain-shape change), 1 extended conflict file
(`identity_resolver.py` — additive fp3 hunks, §3.2), 1 newly-discovered non-vocabulary conflict file
resolved as a clean content-merge (`tracker.js`, §3.10), 1 build artifact to rebuild not merge
(`tracker.min.js`), 1 newly-discovered NON-trivial conflict requiring an explicit combined-logic
resolution (`events.py`, §3.11 — race-fix + fp3-write-once merged), 5 additive/clean files
(`schemas/events.py`, `models/visitor.py`, `models/beam_identity.py`, `.gitignore`,
`apps/pixel/package.json`), 1 new e2e spec + 2 updated pixel unit test files (§7). **This is a real,
if narrow, expansion of the reconciliation's scope — it is not folded into the "zero code change"
framing above, which applies only to the D10 wrapper's own blast radius.**

---

## 2. Recommended Sequencing

The task's suggested ordering ("land the 2 clean commits first") is correct — endorsed, not revised.
Reasoning: `e11a91d` (pixel/site-id lifecycle) and `a066006` (contacts) are structurally independent
of the identity-vocabulary fork (they touch `apps/pixel`, `contact_importer.py`,
`routers/contacts.py` — none of which read `identity_status` vocabulary constants) and rebase clean.
Landing them first:

1. shrinks the remaining conflict surface to exactly the identity commits (`626d643`, `fe89466`,
   `1c5ae32`), so the harder work is isolated and reviewable on its own diff
2. gives an early, low-risk shippable checkpoint (both commits pass their own test suites
   unmodified) before the higher-risk vocabulary work begins
3. matches D3/D4 — neither commit touches a Tier-2 file, so there is no reason to interleave them
   with the migration re-chain

**PVL cycle 2 — independently re-verified via `git diff-tree`:** confirmed zero file overlap between
`e11a91d`/`a066006` and the Tier-2 files (`identity_classification.py`, `identity_resolver.py`,
`campaign_sender.py`). No pre-commit hooks or CI checks in this repo run `alembic` at import time.
The two-migration-file-deep dangling-reference window during steps 2-3 (both `c2f8a5d31e97` AND
`e9d2a4c71f68`, not just the one file previously named) is correctly covered by the checklist's
blanket "no alembic commands in this window" instruction — re-confirmed safe.

**Sequencing steps (must run in this order — CORRECTED at VALIDATE per Finding 1 / Execute-Agent
Instruction E1: the original draft ordered the migration re-chain before the `626d643` rebase that
introduces the migration file being re-chained, which is impossible. The end-state design below was
always correct; only the step order changed.):**

1. Live pre-check (§5 step 0) — confirm alembic head + zero `verified`/`provider_candidate` rows.
2. Cherry-pick/rebase `e11a91d`, `a066006` onto `main` (clean, zero conflicts expected; git-mechanical
   only — do not run any `alembic` command until step 5).
3. Rebase `626d643` (identity) — resolve the 5 conflicted backend files per §3. **This step
   introduces `b1c9e7f24d83_add_identified_visitor_confirmed_at.py` — the migration re-chain in
   step 5 cannot run before this step completes. §3.1 is now vocabulary-only —
   `is_emailable_identity()` is unchanged (D10 redesign, S6).**
4. Spot-check (§3.7/E3): confirm the 3 non-conflict test files
   (`test_agent_origin_exclusion.py`, `test_handoff_emailability_separation.py`,
   `test_outbound_identity_gate.py`) do not reference the retired `EMAILABLE_PROVIDERS` symbol
   post-rebase. **PVL cycle 2: insufficient alone — these files' own `is_emailable_identity(...)
   is True` assertions must ALSO be reconciled with whichever D10 redesign is chosen (see Finding 5).**
5. Migration re-chain (§5) — NOW re-point devjulley's `b1c9e7f24d83.down_revision` at main's current
   head; verify single head offline.
6. Offline `--sql` validate the full migration chain (§5 step 4).
7. Rebase `fe89466` (routers/jobs/nav wiring) — resolve `status-badge.tsx` +
   `test_events_ingest.py` per §3.
8. Rebase `1c5ae32` (process artifacts — docs only, expect clean or trivial).
9. **(NEW, S13)** Rebase any commit(s) the EXECUTE pre-flight (Implementation Checklist step 0) shows
   beyond `1c5ae32` — as of PLAN supplement cycle 5, `ae7ffb9` (fingerprint v3) — resolving
   `identity_resolver.py` (§3.2 extension) and `apps/pixel/src/tracker.js` (§3.10, confirmed clean
   content-merge).
10. Full call-site sweep (§4) as one commit on top, covering anything §3's per-file resolutions
   didn't already fix — includes adding the `candidate_outreach_enabled` confirm-gate WRAPPER (§6) at
   exactly 3 of the 5 originally-named call sites (`campaign_sender.py`, `csv_exporter.py`,
   `routers/campaigns.py`); `hot_alert.py` and `outcome_digest.py` are explicitly excluded (§6).
   `is_emailable_identity()` itself is not modified.
11. Add `candidate_outreach_enabled` flag (D5) as one commit. (The config-setting half of this step
    is unaffected by the block; only the function-wiring half in step 10 is blocked.)
12. Live pre-push re-check (§5 step 0, re-run) — if new `verified`/`provider_candidate` rows appeared
    since step 1, run the contingency backfill (§5) before push. **Also re-run the full step-0
    pre-flight one more time here** — devjulley may have moved again since the checklist started.
13. Run full verification suite (§7).
14. Force-push-with-lease `devjulley` (or land via PR/merge onto `main` per user's actual git
    workflow choice at EXECUTE time — this plan does not mandate rebase-vs-merge, see §8).

---

## 3. Per-Conflict-File Resolution Spec

For each of the **8 known conflicted files (5 identity + 2 from `fe89466` + 1 from `ae7ffb9`,
`tracker.js` — as of PLAN supplement cycle 5; `events.py` is a 9th real conflict but is resolved
below in §3.11 as an extension, not counted in the original "7 known" framing since it was
discovered, not originally enumerated)**, state exactly which side wins and what must be ported.
"Resolve manually" is never the instruction — every row below is concrete.

### 3.1 `apps/api/services/identity_classification.py`

> **AUTO-MERGE WARNING (added PLAN supplement cycle 9, S22 — see Execute-Agent Instruction E-11):**
> git will NOT stop on most of this file. Only the `identity_status_for_provider` vs
> `is_graph_candidate_provider`/`is_verified_identity` swap carries real conflict markers;
> `EMAILABLE_PROVIDERS`, the `STATUS_*`/`VERIFIED_STATUSES` family, and `is_emailable_identity()`'s
> body all auto-merge **silently to `main`'s content**. Apply this section's instructions explicitly
> regardless of what git reports. Read **E-11** before starting.

**STATUS: UNBLOCKED as of PLAN supplement cycle 3 (S6) — the D10 redesign moved the
`candidate_outreach_enabled` wiring entirely out of this file and into a wrapper at 3 call sites
(§6). This section is now pure vocabulary adopt-devjulley, no D5/D10 content remains here.**

**devjulley's structure wins wholesale** (D1+D2). Concretely:
- Keep `PERSON_LEVEL_PROVIDERS` from devjulley — it includes `"contact_import"` (main's version
  lacks this provider entirely, since contact import is a devjulley-only feature). **Port
  `"contact_import"` into the person-level set even after adopting devjulley's file as base** — this
  is automatic since devjulley's file is the base, just confirm it doesn't get lost in the merge tool.
- Keep `GRAPH_CANDIDATE_PROVIDERS` (`rb2b`, `leadpipe`, `capturify`, `beam_identity_network`) and
  `is_graph_candidate_provider()` from devjulley.
- Keep `is_verified_identity(status) -> status == "identified"` from devjulley — this is the sole
  "is this confirmed?" gate downstream code must call.
- **Delete** `STATUS_VERIFIED`, `STATUS_PROVIDER_CANDIDATE`, `STATUS_IDENTIFIED_LEGACY`,
  `VERIFIED_STATUSES`, `PROVIDER_CANDIDATE_STATUSES`, `RESOLVED_PERSON_STATUSES`,
  `identity_status_for_provider()` — all main-only, all retired per D1.
- **Keep `EMAILABLE_PROVIDERS` from main REMOVED** (do not port it forward) — D2 replaces the narrow
  emailable-providers-list gate with devjulley's `identity_level(provider) == "person"` gate. Do not
  leave `EMAILABLE_PROVIDERS` dangling as dead code; delete it.
- `identity_level()` — identical on both branches, no conflict, keep as-is.
- **`is_emailable_identity()` — devjulley's body wins (`identity_level(provider) == "person"`),
  SIGNATURE AND BODY 100% UNCHANGED. HARD CONSTRAINT, locked at PLAN supplement cycle 3 (S6): do
  NOT add a `candidate_outreach_enabled` parameter, or any other parameter, to this function.** This
  is enforced by devjulley's own
  `tests/unit/test_identity_classification.py::test_is_emailable_identity_still_takes_exactly_three_params`
  ("Hard constraint: this phase must not widen the emailability signature") and by
  `test_candidates_are_emailable_not_blocked_by_tier`, whose docstring explicitly states its purpose
  is "to catch a future change that 'helpfully' folds the candidate tier into
  `is_emailable_identity`" — exactly what the ORIGINAL (now rejected) D5/D10 wiring would have done.
  The existing locked program SPEC (`identity-program_SPEC_03-08-26.md`, Background/Research
  Findings) independently states: "the new personalization-gating requirement lands in the campaign
  draft/send composition layer, not in `is_emailable_identity()` itself" — devjulley's implementation
  already follows this rule; this reconciliation plan now follows it too.

  ~~**New code required (D5 wiring, per VALIDATE Execute-Agent Instruction E2):** `is_emailable_identity()`
  gains a new `candidate_outreach_enabled` parameter...~~ **REJECTED at PVL cycle 2 (Findings 4-5) —
  breaks D3 and is not implementable as specified. See Validate Contract for the evidence trail. The
  confirm-gate is implemented instead as a wrapper AT 3 of the 5 named call sites — see §6 for the
  full per-site spec. This is now the LOCKED design (PLAN supplement cycle 3, S6/S10), not a
  pending redesign.**

### 3.2 `apps/api/services/identity_resolver.py`

**EXTENDED at PLAN supplement cycle 5 (S13) for `ae7ffb9`'s 43+/14- delta to this same file — read in
full via `git diff 1c5ae32 ae7ffb9 -- apps/api/services/identity_resolver.py`, confirmed additive and
non-overlapping with the vocabulary write logic below.** `ae7ffb9` adds fp3 (fingerprint v3,
installed-font + audio probes) as a preferred, higher-confidence fingerprint-match signal: the
per-visitor fingerprint match (~line 368-411) now prefers `Visitor.fingerprint_v3` over
`Visitor.fingerprint` when present (confidence 0.80 vs 0.75, still below the 0.90 deterministic svid
path), the `BeamIdentityNode` upsert gains a `fingerprint_v3` column with a `COALESCE`-based
write-once merge (never blanks a stored value with a NULL from a visitor whose fp3 hasn't resolved
yet), and the graph lookup (`_graph_node_by_email`-adjacent path) tries fp3 first, falling back to
fp2. **None of this touches the vocabulary/emailability write logic** — `identity_status = "candidate"
if is_graph_candidate_provider(provider) else "identified"` (the two sites at ~line 899 and ~951 this
plan's original §3.2 spec targets) is byte-for-byte unchanged by `ae7ffb9`. Resolution: **take
devjulley's (post-vocabulary-rewrite) file as the base, as the original spec below already says, then
re-apply `ae7ffb9`'s fp3 additions on top** — they are independent hunks (fingerprint-match block,
`BeamIdentityNode` upsert block, graph-lookup block) that do not intersect the vocabulary rewrite's
hunks, so this is additive layering, not a 3-way semantic conflict.

**devjulley's writer logic wins** (line ~888/940: `"candidate" if is_graph_candidate_provider(provider)
else "identified"`, replacing main's `identity_status = identity_status_for_provider(provider)` at
line ~1098) — **with ONE explicit carve-out, added at PLAN supplement cycle 9 (S21): the
`_save_identified` `IntegrityError` handler. The blanket "devjulley wins" rule does NOT apply to that
hunk and must not be applied to it.**

> **§3.2 CARVE-OUT — `_save_identified` `IntegrityError` handler (S21). This is a HYBRID, not a
> side-pick.**
>
> **Why the blanket rule is unsafe here:** devjulley's version accesses `visitor.visitor_id[:8]` and
> `visitor.site_id` *inside* the `except IntegrityError:` block, i.e. **after
> `await self.db.rollback()`**. `rollback()` expires every instance in the session **regardless of
> `expire_on_commit`**, so that attribute access triggers a synchronous lazy refresh and raises
> `MissingGreenlet` — masking the real integrity conflict behind an unrelated, misleading error.
> `main`'s version documents exactly this hazard and reads the ids into locals **before** the commit
> attempt.
>
> **Correct resolution (hybrid):** read the ids into locals BEFORE `try: await self.db.commit()`
> (main's safety), then use devjulley's upsert semantics and devjulley's
> `save_identified_conflict_upsert` event name INSIDE the handler, referencing those pre-read locals.
>
> **Reference resolution — this is the form actually shipped and orchestrator-verified on
> `devjulley` (`git show devjulley:apps/api/services/identity_resolver.py`, ~L1181-1242):**
>
> ```
> conflict_visitor_id = visitor.visitor_id      # ~L1181  (pre-read, main's fix)
> conflict_site_id = visitor.site_id            # ~L1182
> try:
>     await self.db.commit()                    # ~L1184
> except IntegrityError:                        # ~L1185
>     ...                                        # devjulley upsert semantics +
>     "save_identified_conflict_upsert"          # ~L1212 devjulley event name
>     visitor_id=conflict_visitor_id[:8]         # ~L1213 uses the PRE-READ local, never visitor.*
> ```
>
> Confirm with `git show devjulley:apps/api/services/identity_resolver.py` around lines 1170-1215. Because this file has 3 large hunks (~130+ changed lines per branch — see diff summary
below), do NOT attempt a line-level 3-way auto-merge blind; resolve as: **take devjulley's full file
as the base**, then re-apply main's independent additions on top:
- Provider-outage vs no-match separation (main-only logic, D4) — must be ported into devjulley's
  resolver body; confirm by diffing main's outage-handling block (search for `outage` /
  `provider_outage` in main's version) against devjulley's file and re-inserting it.
- Resolution deferral watermark (main-only, D4) — same re-insertion approach.
- RB2B provider rework (main-only, D4) — same.
- **`is_privacy_relay_ip()` — the FOURTH main-only addition (ADDED at PLAN supplement cycle 9, S20;
  this porting checklist previously named only three, which was a plan-text defect).** `main` added a
  **fail-closed iCloud Private Relay check** (`is_privacy_relay_ip`, matching prefix
  `2a09:bac3::/32`) at ~main line 528-538, placed **before** the pre-existing
  `check_ip_privacy` / `is_ip_suspicious` IPinfo check, specifically so that an unset
  `settings.ipinfo_token` cannot let masked traffic reach paid identity providers. It sets
  `visitor.identity_status = "vpn_filtered"`.

  **Why this stayed invisible for 8 PVL cycles (recorded inline so it is not re-lost):** the guard
  sits **outside every real conflict hunk** in this file — the three real hunks are the import block,
  the vocabulary-write block, and the log-message/id-caching block — so `git` never surfaces it during
  a rebase; **and no test in the suite exercises the resolver's call site.**
  `tests/unit/test_identity_quality_gates.py` and `tests/unit/test_company_resolver.py` only test the
  standalone `company_resolver.is_privacy_relay_ip()` function, and
  `tests/unit/test_leadpipe_webhook.py` patches it on a different module. Verify all of this with
  `git grep -n "is_privacy_relay_ip" <ref> -- apps/api/services/identity_resolver.py tests/`.

  **Failure mode if dropped:** a masked Private Relay IP reaches paid RB2B/Leadpipe/Capturify
  lookups — burning budget and breaking the documented fail-closed guarantee — **with zero test
  failure.**

  **VERIFIED PRESENT on the executed result (S23 spot-check):**
  `git grep -c "is_privacy_relay_ip" devjulley -- apps/api/services/identity_resolver.py` → **2 hits
  (import at L37, call site at L602). The guard survived.** Only this plan's §3.2 text was wrong; the
  shipped code is correct.
- devjulley's origin-status-inherits-tier logic for `svid_reconcile`/`fingerprint_match` (mentioned
  in `GRAPH_CANDIDATE_PROVIDERS` docstring) must be preserved verbatim — this is new devjulley logic
  main never had.

This file is the single highest-effort resolution in the whole reconciliation — budget real review
time, not a mechanical merge-tool accept.

### 3.3 `apps/api/services/kpi.py`

**devjulley's structure wins** (D1): `identified = count(identity_status == "identified")`,
`candidates = count(identity_status == "candidate")`, both returned as separate funnel keys. Delete
main's `VERIFIED_STATUSES` import and the `.in_(VERIFIED_STATUSES)` filters — replace with plain
`== "identified"` equality per devjulley. No main-only KPI logic exists in this file (diff shows
100% of main's differences are the retired-vocabulary filters) — this file has **zero D4 content to
re-port**, pure adopt-devjulley.

### 3.4 `apps/api/services/timeseries.py`

Same as kpi.py: **devjulley's structure wins**, pure adopt — `identified_case`/`candidate_case`
split, both returned in the daily series row. No main-only content to re-port (confirmed via full
diff — 100% vocabulary-only).

### 3.5 `apps/api/routers/dashboard.py`

**devjulley's structure wins** for the funnel query (`identity_status == "identified"` /
`== "candidate"` / `== "anonymous"` filters replacing main's `VERIFIED_STATUSES` `.in_()` filter).
Delete main's `from apps.api.services.identity_classification import VERIFIED_STATUSES` import.
**Resolved at VALIDATE (full-file diff run, not just the funnel section):** confirmed the ENTIRE
diff between branches is the funnel-query block plus the additive `candidates` field — zero other
main-only dashboard sections exist in this file. devjulley's structure can be accepted wholesale;
no further re-diffing needed at EXECUTE time.

### 3.6 `apps/api/routers/visitors_helpers.py`

**devjulley's structure wins**: `Visitor.identity_status == identity_status` (parameterized single-
value filter) and explicit `== "identified"` / `== "candidate"` / `== "anonymous"` filters replace
main's `VERIFIED_STATUSES` `.in_()` calls at lines ~113 and ~179. Delete the `VERIFIED_STATUSES`
import.

### 3.7 `tests/unit/test_identity_classification.py`

**Rewrite, do not pick a side wholesale.** This file will exist in both branches with different
content (devjulley added `is_verified_identity`/`is_graph_candidate_provider` test cases; main added
`identity_status_for_provider`/`STATUS_VERIFIED`/`STATUS_PROVIDER_CANDIDATE` test cases pointing at
now-deleted symbols). Resolution:
- Keep every devjulley test case verbatim (they test the surviving canonical API) — **including
  `test_is_emailable_identity_still_takes_exactly_three_params`,
  `test_candidates_are_emailable_not_blocked_by_tier`, and
  `test_abuse_flag_default_false_preserves_existing_behavior`. These require NO modification — the
  D10 redesign (§3.1, S6) keeps `is_emailable_identity()` byte-for-byte unchanged, so these pass
  unmodified once §3.1's vocabulary-only changes land.**
- Delete every main test case that imports/asserts the retired symbols
  (`identity_status_for_provider`, `STATUS_VERIFIED`, `STATUS_PROVIDER_CANDIDATE`,
  `VERIFIED_STATUSES`, `PROVIDER_CANDIDATE_STATUSES`).
- **Do NOT add new test cases to this file for the confirm-gate wrapper.** Per the D10 redesign (§6,
  locked at PLAN supplement cycle 3), the wrapper lives at the 3 call sites, not inside
  `is_emailable_identity()` — its tests belong in the NEW file
  `tests/unit/test_candidate_outreach_gate.py` (§6/S8), not here. This file stays a pure vocabulary
  regression suite for the unchanged canonical API.

**Also sweep (not in the original 7-file conflict list, discovered via grep — §4):**
`tests/unit/test_identity_quality_gates.py` and `tests/unit/test_leadpipe_webhook.py` (unit) and
`tests/integration/test_leadpipe_webhook_persistence.py` (integration) all assert
`STATUS_PROVIDER_CANDIDATE`/`STATUS_VERIFIED`/`identity_status_for_provider` and will fail to import
once §3.1 lands. These 3 files exist ONLY on `main` (devjulley never created them) — they do not
appear as git rebase conflicts (no devjulley-side content to conflict with), but they WILL break at
EXECUTE time the moment `identity_classification.py` is rewritten. Rewrite each assertion to the
canonical vocabulary: `identity_status_for_provider("rb2b") == STATUS_PROVIDER_CANDIDATE` becomes an
assertion against `is_graph_candidate_provider("rb2b") is True` (or equivalent `identity_status`
value `"candidate"` produced by the resolver), and `== STATUS_VERIFIED` cases become `"identified"`
equivalents matched to whatever provider/status combination the test is actually exercising.

**Spot-check (E3, VALIDATE-required, mandatory checklist item — see Implementation Checklist step
4):** `tests/unit/test_agent_origin_exclusion.py`, `tests/unit/test_handoff_emailability_separation.py`,
and `tests/unit/test_outbound_identity_gate.py` all import `EMAILABLE_PROVIDERS` on `main`, but were
NOT in the original 7-file conflict list because `devjulley` never created git-conflicting content
for them (expected to rebase clean). **Independently confirmed at VALIDATE (both cycle 1 and cycle
2): all 3 files already use `PERSON_LEVEL_PROVIDERS`/`COMPANY_LEVEL_PROVIDERS` on `devjulley` and
contain zero `EMAILABLE_PROVIDERS` references** — they are expected to land clean with no code
change needed for that specific symbol. **PVL cycle 2 ADDITIONAL FINDING: these 3 files (plus
`test_identity_classification.py`) ALSO contain pre-existing `is_emailable_identity(<graph-candidate
provider>) is True` assertions (e.g. `test_person_level_is_emailable[rb2b]`,
`test_real_person_providers_stay_emailable`, `test_agent_origin_overrides_person_level[rb2b]`,
`test_non_agent_identity_unaffected`) that were about to silently break under the original D5/D10
signature change — independent of the `EMAILABLE_PROVIDERS` symbol question entirely. Now that the
signature change is SUSPENDED, these assertions require no code change and should be re-confirmed
green once §3.1's vocabulary-only rewrite lands — same "no change expected" status as before, but
for a different, now-understood reason.**

### 3.8 `apps/web/src/components/ui/status-badge.tsx`

**devjulley's structure wins.** Replace main's `verified: "success"` / `provider_candidate:
"warning"` keys with devjulley's `candidate: "warning"` key. Keep main's `vpn_filtered: "neutral"`
and `merged: "info"` keys — devjulley's diff shows these lines were REMOVED relative to main (the
diff shows `38,39d39 < vpn_filtered ... < merged ...` meaning main HAS these two keys and devjulley's
version does not include them in the same location). Both `vpn_filtered` and `merged` are confirmed
live, actively-assigned `identity_status`-adjacent values on `devjulley` (grepped across
`identity_resolver.py`/`promotion_sweep_runner.py`/`contact_importer.py`/`hot_contacts.py`/
`routers/visitors.py`) — **re-add both keys** to the final merged tone map. Net result: `candidate`
(from devjulley) + `vpn_filtered` + `merged` (preserved from main) all present; `verified`/
`provider_candidate` deleted.

### 3.9 `tests/integration/test_events_ingest.py`

**Not a vocabulary conflict — content-merge both classes, do not pick a side.** Main's
`TestCookieFpPhase2` (CORS/cookie-fp hardening tests) and devjulley's `TestUnknownSiteObservability`
(403 structured-logging tests) are unrelated, non-overlapping test classes that happen to occupy the
same line range because both were appended at the end of the file independently. Resolution: keep
BOTH classes in the final file (concatenate, do not choose). Rename nothing. This is the one conflict
in the set that is a git-diff-locality artifact, not a genuine semantic collision — flag it as such
during EXECUTE so nobody spends time trying to "pick a winner" that doesn't exist.

### 3.10 `apps/pixel/src/tracker.js` (NEW, PLAN supplement cycle 5, S13)

**Not a vocabulary conflict — content-merge both sides, confirmed genuinely clean, do not pick a
side.** Main (2 commits since the fork) added: (a) `xhr.withCredentials = true` on the primary
XHR send path (~L232, for the cross-origin `_rta_svid` HttpOnly cookie) and (b) a Leadpipe-only
vendor-config injection block (~L629, hands the pixel's `visitorId` to the Leadpipe SDK via a
`globalParams` JSON block written before the vendor script tag). `ae7ffb9` added the `fontFp()` and
`audioFp()` probe functions plus the `fpParts()`/`getFingerprint()` refactor and the async fp3
resolution wiring, all in the ~L124-266 range (fingerprint construction, well before either of
main's edit sites). **Verified via `git merge-tree --write-tree --merge-base=<fork-point> main
ae7ffb9`: the merge reports "Auto-merging apps/pixel/src/tracker.js" with ZERO conflict markers** —
the two sides' edits occupy genuinely disjoint regions of the file. Resolution: accept the 3-way
auto-merge result as-is (git's own merge machinery, not a hand merge); spot-check after rebase that
both the `withCredentials`/Leadpipe-config block AND the `fontFp`/`audioFp`/`fpParts` block are
present in the final file. **`tracker.min.js` is a build artifact — do NOT merge it. Rebuild via
`npm run build` (in `apps/pixel/`, runs `npx esbuild@0.24.0 ... --outfile=src/tracker.min.js`) after
`tracker.js` lands, then verify with `npm run size` (`gzip -c src/tracker.min.js | wc -c`) against
the current **6KB gzipped** gate — `ae7ffb9` itself raised this from 5KB, enforced in
`tests/unit/test_pixel_fingerprint.py` (`< 6000` bytes) and `tests/unit/test_pixel.py` (`< 6144`
bytes). Do not assume the old <5000B/5120B figure from prior program memory notes — it is stale as of
`ae7ffb9`.**

### 3.11 `apps/api/routers/events.py` (NEW, PLAN supplement cycle 5, S13 — discovered via
`git merge-tree`, not part of the original 7/8-file enumerated conflict list)

**Genuinely non-trivial — NOT a content-merge like `tracker.js`.** Both branches independently
rewrote the same `_process_signal_events` fingerprint-persistence block:
- **main** replaced the original two separate `update(Visitor).where(...IS_NULL...)` statements with
  a single `pg_insert(Visitor).values(...).on_conflict_do_update(index_elements=["site_id",
  "visitor_id"], set_={...})` upsert-stub — this fixes a real race (visitor aggregation creates the
  `Visitor` row asynchronously AFTER this function runs, so a bare `UPDATE` against a
  not-yet-existing row matches 0 rows and silently drops the fingerprint for one-shot visitors). The
  `set_={}` dict does write-once `COALESCE(visitors.fingerprint, EXCLUDED.fingerprint)`,
  `COALESCE(visitors.server_visitor_id, EXCLUDED.server_visitor_id)`, and
  `LEAST(visitors.first_seen, EXCLUDED.first_seen)`.
- **`ae7ffb9`** kept the original two-`UPDATE` shape but added a third write-once `UPDATE` for
  `fingerprint_v3` (scans `batch.events` for both `fp2_`/`fp_`-prefixed and `fp3_`-prefixed values
  independently, since fp3 can resolve on a later event than fp2).

**Concrete resolution — port devjulley's fp3 write-once logic INTO main's upsert-stub shape (do not
pick a side, do not re-introduce the race main just fixed):**
1. Take main's `pg_insert(...).on_conflict_do_update(...)` structure as the base (it is the correct,
   race-free shape and must not be reverted).
2. Add `fingerprint_v3=fp3_value` to the initial `.values(...)` call, alongside the existing
   `fingerprint=fp_value` and `server_visitor_id=svid`.
3. Add a third entry to the `set_={}` dict: `"fingerprint_v3": sa_text("COALESCE(visitors.fingerprint_v3, EXCLUDED.fingerprint_v3)")`, mirroring the existing `fingerprint` entry.
4. Port devjulley's dual fp2/fp3 scan loop (the `for event in batch.events` block that independently
   tracks `fp_value` and `fp3_value`, breaking early only once both are found) — this replaces main's
   single-fingerprint scan loop, since main never needed a second signal.
5. **Gate the whole block on `if fp_value or fp3_value or svid:`.** All three clauses are load-bearing.

   > ~~SUPERSEDED (PLAN supplement cycle 7, S16) — the original wording read: *"Gate the whole block
   > on `if fp_value or fp3_value:` (devjulley's condition), not main's `if fp_value:` alone."*~~
   > Struck for audit, matching how S10 preserved the rejected in-helper D10 form. It was wrong twice
   > over: it **dropped `or svid`**, and its parenthetical **misdescribed main's actual code**.

   Ground truth, re-derived live at supplement cycle 7 via
   `git show main:apps/api/routers/events.py` (line 557): main's real gate is
   **`if fp_value or svid:`** — not `if fp_value:` alone. devjulley's gate is
   `if fp_value or fp3_value:`. The merged gate is the union of both:
   **`if fp_value or fp3_value or svid:`**. This agrees exactly with Execute-Agent Instruction E-8
   in the Validate Contract, which stays in place as belt-and-braces; §3.11 and the contract must not
   disagree, and an execute-agent reading only §3.11 must not be able to implement the wrong gate.

   **Failure mode the `or svid` clause prevents (recorded so the reason survives):** an *svid-only
   batch* — the durable `_rta_svid` server cookie is present but neither `_fp` nor `_fp3` appears
   anywhere in the batch (e.g. a form-submission-only batch, or a batch that arrives before the
   pixel's fingerprint probes have resolved). On current `main` that batch reaches the
   `pg_insert(...).on_conflict_do_update(...)` path, which **creates the `Visitor` stub row if it is
   missing** — the exact aggregation race main's redesign exists to fix — and stamps
   `server_visitor_id`. Under the superseded step-5 wording that batch is skipped entirely: no stub
   row, no `server_visitor_id`. That is a **real regression against current `main`**, and it is
   **invisible to the existing test suite** (no test covers the svid-only-batch case). An fp3-only
   batch (the case the original wording was reaching for) is still covered — `or fp3_value` remains.

This is the correct combined design: race-free (main's fix) AND fp3-aware (devjulley's addition).
Do not ship either side's version unmodified.

---

## 4. Full Call-Site Sweep (retire `verified`/`provider_candidate`)

Enumerated by reading the code (git grep on `main`, confirmed exhaustive — not hand-waved, and
independently re-confirmed with a full symbol-by-symbol re-grep at PVL cycle 2):

| Symbol | File : line (main) | Action |
|---|---|---|
| `VERIFIED_STATUSES` | `identity_classification.py:66` (definition) | Delete definition |
| `VERIFIED_STATUSES` | `routers/dashboard.py:24` (import), `:92` (use) | §3.5 — rewrite to `== "identified"` |
| `VERIFIED_STATUSES` | `routers/visitors_helpers.py:26` (import), `:113`, `:179` (use) | §3.6 — rewrite to explicit equality |
| `VERIFIED_STATUSES` | `services/kpi.py:21` (import), `:57`, `:61`, `:70` (use) | §3.3 — rewrite |
| `VERIFIED_STATUSES` | `services/timeseries.py:15` (import), `:51`, `:54` (use) | §3.4 — rewrite |
| `STATUS_VERIFIED` | `routers/visitors.py:47` (import), `:1045` (assignment in confirm endpoint) | **NOT a devjulley conflict file, but main's confirm-adjacent code writes this literal** — rewrite `visitor.identity_status = STATUS_VERIFIED` to `visitor.identity_status = "identified"`. **Resolved at VALIDATE:** confirmed `visitors.py:1045` is inside `manually_identify_visitor` (residential-IP / site-owner self-identification endpoint) — a genuinely separate, live, distinct endpoint from devjulley's `confirm_candidate`/`reject_candidate` (different route, different trigger). Neither supersedes the other; both are live paths that need to exist post-merge. The plan's simple literal rewrite at this one line is sufficient — no path deletion or additional reconciliation required. |
| `identity_status_for_provider` | `identity_classification.py:80` (definition) | Delete definition (§3.1) |
| `identity_status_for_provider` | `services/identity_resolver.py:41` (import), `:1098` (use) | §3.2 — replaced by devjulley's `"candidate" if is_graph_candidate_provider(...) else "identified"` |
| `STATUS_PROVIDER_CANDIDATE` | `tests/integration/test_leadpipe_webhook_persistence.py:30,128` | §3.7 — rewrite assertion |
| `STATUS_PROVIDER_CANDIDATE`, `STATUS_VERIFIED`, `identity_status_for_provider` | `tests/unit/test_identity_quality_gates.py:13,14,16,67,68,71,72,73` | §3.7 — rewrite assertions |
| `STATUS_PROVIDER_CANDIDATE`, `identity_status_for_provider` | `tests/unit/test_leadpipe_webhook.py:24,25,428` | §3.7 — rewrite assertion |
| `PROVIDER_CANDIDATE_STATUSES`, `RESOLVED_PERSON_STATUSES` | `identity_classification.py:67,69` (definitions) | Delete — grep confirms zero external readers on `main` (definitions only, unused elsewhere) |

**`is_emailable_identity()` real blast radius — RESOLVED at PLAN supplement cycle 3 (S7/S8).** The
35 total call sites (5 production + 30 test, across 10 test files, independently re-confirmed twice
via `git grep`) require **zero change from this reconciliation's D10 wiring**, because
`is_emailable_identity()` itself is unchanged (§3.1, D10 redesign). The confirm-gate lives entirely
in a NEW wrapper layered at 3 of the 5 originally-named production call sites — see the per-site
table below, re-derived by reading each site's current code on `devjulley` (not assumed).

**3 of 5 named production call sites receive the wrapper (LOCKED design, PLAN supplement cycle 3):**

| Call site | File : line | Concrete wiring |
|---|---|---|
| Outreach send gate | `services/campaign_sender.py:283` (send loop) | **`identity_status` IS already fetched in this function, but AFTER the gate (query at line ~336-343, gate at line ~283).** Fix: hoist that EXISTING `select(Visitor.identity_status)` query to before line 283 (net zero new queries — it is a reorder, and the hoisted value is reused by the personalization gate at line ~347 exactly as today). Wrap the gate: `emailable = is_emailable_identity(iv.resolution_provider, ...); if emailable and is_graph_candidate_provider(iv.resolution_provider) and not settings.candidate_outreach_enabled: emailable = is_verified_identity(identity_status)`. |
| Personalization gate | `services/campaign_sender.py` (`is_verified_identity()` calls at `:144`, `:190`) | **No change** — unrelated to the confirm-gate flag; stays devjulley's mechanism that restrains candidates to generic copy regardless of `candidate_outreach_enabled`. |
| LinkedIn outreach target resolution | `routers/campaigns.py:725` (`_resolve_linkedin_targets`) | **NEW query required** — `iv` (an `IdentifiedVisitor` row) has no `identity_status` in scope today. Add `select(Visitor.identity_status).where(Visitor.site_id == site_id, Visitor.visitor_id == vid)` per visitor in the loop (same N+1 shape the function already has for `EnrichmentProfile`). `Visitor` is already imported in this file — zero new imports. Apply the same wrapper logic as the send gate. |
| CSV export | `services/csv_exporter.py:79` (`_get_segment_visitors`) | **NEW query required** — `identified` (an `IdentifiedVisitor` row) has no `identity_status` in scope today. Add `select(Visitor.identity_status).where(Visitor.site_id == member.site_id, Visitor.visitor_id == member.visitor_id)` per member in the loop. **`Visitor` is NOT currently imported in this file — add `from apps.api.models.visitor import Visitor`** (currently only `IdentifiedVisitor` is imported, line 11). Apply the same wrapper logic. |

**2 of 5 originally-named call sites are EXPLICITLY EXCLUDED from the wrapper (re-scoped at PLAN
supplement cycle 3, S7) — verified by reading each site's actual purpose, not assumed:**

| Call site | File : line | Why excluded |
|---|---|---|
| Hot-alert | `services/hot_alert.py:88` (`maybe_send_hot_alert`) | This function ALREADY has `visitor: Visitor` passed in as a parameter — `visitor.identity_status` is directly in scope, zero new query needed if the wrapper WERE applied here. But `is_emailable_identity()` at this call site gates whether the SITE OWNER's alert email reveals the visitor's guessed name — it is not outreach TO the candidate. Applying the confirm-gate here would incorrectly suppress a legitimate owner-facing alert. **Recommendation: leave line 88 unchanged; do not apply the wrapper.** |
| Outcome digest | `services/outcome_digest.py:161` (`_top_visitors_this_week`) | `is_emailable_identity(provider)` here buckets visitors (person-level first) for the OWNER's weekly digest email — a ranking/display use, not outreach to the candidate. The current query (`full_name`, `resolution_provider`, `job_title`, `company_name`) has no `identity_status` column selected; adding the wrapper would require a new join AND would incorrectly gate an internal ranking decision behind an outreach-consent flag. **Recommendation: leave line 161 unchanged; do not apply the wrapper.** |

Do not paper over these two — they were named in the original 5-site list but do not fit the
confirm-gate's actual purpose (gating outreach TO the candidate, not gating what the SITE OWNER sees
about the candidate).

**30 test call sites across 10 test files (confirmed — genuinely NO change required, now for the
correct reason: the signature change is suspended, not because a default absorbs a new parameter):**

| Test file | Call count |
|---|---|
| `tests/unit/test_identity_classification.py` | 8 |
| `tests/unit/test_outbound_identity_gate.py` | 6 |
| `tests/unit/test_agent_origin_exclusion.py` | 5 (**highest-priority guardrail regression test — the outreach-exclusion test the whole EvalLayer program depends on; must NOT break** — confirmed it does not, now because the function signature is unchanged, not because of a positional-arg default as previously reasoned) |
| `tests/unit/test_contact_importer.py` | 3 |
| `tests/integration/test_ingest_abuse_hardening.py` | 2 |
| `tests/unit/test_handoff_emailability_separation.py` | 2 |
| `tests/integration/test_cadence_bot_flag.py` | 1 |
| `tests/integration/test_candidate_endpoints.py` | 1 |
| `tests/integration/test_visitor_aggregation.py` | 1 |
| `tests/unit/test_svid_reconcile.py` | 1 |
| **Total** | **30** |

---

## 5. Migration Re-Chain

**Do NOT hardcode a planned head.** Run this exact sequence at the START of EXECUTE, live:

```bash
# Step 0 — mandatory live re-verification, do this FIRST and again immediately before push
railway run -s retarget-agent bash -c 'psql "${DATABASE_URL/postgresql+asyncpg/postgresql}" -t -A -c "select version_num from alembic_version;"'
alembic -c apps/api/alembic.ini heads
railway run -s retarget-agent bash -c 'psql "${DATABASE_URL/postgresql+asyncpg/postgresql}" -t -A -c "select identity_status, count(*) from visitors group by 1;"'
```

Expected (per RESEARCH, time-sensitive — re-confirm, do not assume): prod head `e6b2d4a1c837`
(single head), row counts `anonymous|1247`, `identified|89`, `candidate|0`.

**Two different "fork points" — do NOT conflate them (CORRECTED, PLAN supplement cycle 7, S17).**

> ~~SUPERSEDED — the PVL cycle 2 note previously asserted: *"Fork point `a7d419e6c052` confirmed to
> equal `git merge-base main devjulley`, which also exactly equals `backup/main-06-08-26` — three
> independent confirmations of the same fork point."*~~ **That claim is factually false** and is
> struck for audit. `a7d419e6c052` is an **Alembic revision ID** that merely *looks* like a short
> git hash. It is not a git object at all.

There are two unrelated identifiers, on two unrelated DAGs. An Alembic revision ID is **never** a git
commit; running a `git` command against one is a category error that would send an execute-agent to
the wrong place.

| Concept | Value (informational snapshot, 07-08-26 — re-derive live) | Command that reproduces it |
|---|---|---|
| **git-history fork point** (git DAG) | `db180c44d7cd273647c79b3093d7b7d10af2c5e2` | `git merge-base main devjulley` |
| **migration-DAG fork point** (Alembic DAG) | `a7d419e6c052` (`a7d419e6c052_add_events_link_marker.py`, the last revision common to both branches) | `git show devjulley:apps/api/migrations/versions/b1c9e7f24d83_add_identified_visitor_confirmed_at.py \| grep down_revision` |
| **proof `a7d419e6c052` is not a git object** | `fatal: Not a valid object name a7d419e6c052` | `git cat-file -t a7d419e6c052` |
| **`backup/main-06-08-26`** | `db180c44…` — equals the **git** merge-base (a git ref can only ever equal a git commit) | `git rev-parse backup/main-06-08-26` |

What the cycle-2 note got RIGHT and still holds (independently re-derived at cycle 7): `main`'s local
chain has exactly ONE head (`c2f7a9d31b64`), `devjulley`'s has exactly ONE head (`f1a7c3e05b92` — was
`e9d2a4c71f68` before `ae7ffb9` added the fp3 tail). Chain shapes: `main`:
`a7d419e6c052 → b4c9a71e35d8 → c2f7a9d31b64 (head)`. `devjulley`: `a7d419e6c052 → b1c9e7f24d83 →
c2f8a5d31e97 → e9d2a4c71f68 → f1a7c3e05b92 (head)`. Re-pointing `b1c9e7f24d83`'s `down_revision` from
`a7d419e6c052` to main's confirmed live head produces a single valid chain — the design is sound.
(Caution for future re-validation: a naive hand-rolled down_revision parser will falsely report
multiple "orphan" heads on `main` if it does not handle Alembic's multi-line tuple `down_revision`
merge-migration syntax, e.g. `d4c7b2a9e6f1_merge_heads_before_avatar_url.py` — always cross-check
against the real `alembic heads`/`alembic history` output, not a custom parser, before treating a
"multiple heads" finding as real.)

**Contingency (only if `verified` or `provider_candidate` rows are non-zero at this re-check):**
before deleting the vocabulary in code, run a backfill:
```sql
UPDATE visitors SET identity_status = 'identified' WHERE identity_status IN ('verified');
UPDATE visitors SET identity_status = 'candidate' WHERE identity_status IN ('provider_candidate');
```
Run this against the SAME environment the count query targeted (never guess an environment). Confirm
row counts are zero for the old values afterward before proceeding.

**Re-chain steps (CORRECTED SEQUENCING — see Implementation Checklist and §2; this section describes
the mechanical edit itself, run only after `626d643` has been rebased per step 3 of the checklist)**
(assuming prod head is confirmed, call it `<PROD_HEAD>` — do not literal-substitute
`e6b2d4a1c837` without re-confirming it is still current, per the note above about concurrent-program
migration collisions):

1. Edit `apps/api/migrations/versions/b1c9e7f24d83_add_identified_visitor_confirmed_at.py`:
   change `down_revision = "<devjulley's old parent, a7d419e6c052>"` to
   `down_revision = "<PROD_HEAD as re-confirmed in step 0>"`.
2. Leave `c2f8a5d31e97_add_is_imported_contact.py` and `e9d2a4c71f68_add_site_tombstones.py`
   unchanged — their `down_revision` chain (pointing at `b1c9e7f24d83` and `c2f8a5d31e97`
   respectively) is internally consistent and does not need editing, only the ROOT of the devjulley
   sub-chain needs re-pointing.
3. Verify single head offline:
   ```bash
   alembic -c apps/api/alembic.ini heads
   ```
   Must print exactly ONE line. If two heads print, the re-chain step above targeted the wrong
   revision or a NEW migration landed on `main` since step 0 — re-run step 0 and retry.
4. Offline `--sql` validate the full chain from prod head to new tip (mirror the known
   `d5b1f7c3a908:head` gotcha — `sa.inspect(bind)` calls in later migrations break an unscoped
   `alembic upgrade head --sql`, must use an explicit `<from>:<to>` range):
   ```bash
   alembic -c apps/api/alembic.ini upgrade <PROD_HEAD>:head --sql
   ```
5. **Do NOT attempt a live round-trip against the shared dev/prod Postgres in this plan.** Per
   repo convention (owned-data-layer precedent), a live round-trip on a **disposable** Postgres
   container is acceptable evidence; a round-trip against the shared instance is not. If no
   disposable Postgres is available in the EXECUTE environment, this is a documented known-gap
   (offline `--sql` validation only), consistent with prior migrations in this same chain.

**Confirmed migration-chain facts (PLAN supplement cycle 7, S18) — informational snapshots as of
07-08-26, ALWAYS re-derive live; never treat a head value below as fixed.** An external verifier
rebuilt the full Alembic DAG from raw `revision`/`down_revision` headers on both branches, parsing
tuple-aware (`d4c7b2a9e6f1` and `f7c2e9a4b1d3` carry multi-line merge tuples that a naive parser
misreads as extra heads — the same trap the cycle-2 caution note flags):

| Fact | Value (07-08-26 — re-derive live) | Re-derivation command |
|---|---|---|
| `main` revision count | 56 | `git ls-tree -r --name-only main -- apps/api/migrations/versions \| grep -c '\.py$'` |
| `devjulley` revision count | 58 | `git ls-tree -r --name-only devjulley -- apps/api/migrations/versions \| grep -c '\.py$'` |
| shared root (both branches) | `cd811a8b1f32` (single root) | `alembic -c apps/api/alembic.ini history \| tail -1` |
| `main` head | **`c2f7a9d31b64`** (`add_resolution_deferral_watermark`), single head | `alembic -c apps/api/alembic.ini heads` (on a `main` snapshot) |
| `devjulley` head | **`f1a7c3e05b92`** (`add_fingerprint_v3`), single head | `alembic -c apps/api/alembic.ini heads` (on a `devjulley` snapshot) |
| devjulley's own tail after the shared `a7d419e6c052` | `b1c9e7f24d83 → c2f8a5d31e97 → e9d2a4c71f68 → f1a7c3e05b92` | `alembic -c apps/api/alembic.ini history` |

**The re-chain is exactly ONE edit.** Change `b1c9e7f24d83.down_revision` from `a7d419e6c052` to
main's live head **as re-confirmed at EXECUTE time** (step 1 below). Nothing else is edited.
Simulated by the verifier: applying only that single edit to the combined 60-revision graph yields
**exactly one head (`f1a7c3e05b92`)** with **60/60 revisions reachable from the one root**. This
independently **CONFIRMS** the plan's existing claim that `c2f8a5d31e97`, `e9d2a4c71f68`, and
`f1a7c3e05b92` genuinely need no edit — their `down_revision` links are already internally correct
and only the ROOT of the devjulley sub-chain is re-pointed.

**Migration set — informational snapshot as of PLAN supplement cycle 5 (S13), always re-derive live
via the Implementation Checklist step-0 pre-flight (`git diff --name-only main...devjulley --
apps/api/migrations/versions/`):** the devjulley sub-chain is 4 files, not the original 3 — linear
and unbroken: `a7d419e6c052` (shared fork point) → `b1c9e7f24d83` → `c2f8a5d31e97` → `e9d2a4c71f68` →
`f1a7c3e05b92` (new tail, added by `ae7ffb9`, `down_revision = "e9d2a4c71f68"` already correct). Only
step 1 below (re-chaining `b1c9e7f24d83`'s `down_revision`) changes — the shape of the re-chain does
not change, it simply has one more already-correct link in the tail. Re-verify single head (step 3
below) AFTER `ae7ffb9` is rebased (Implementation Checklist step 12/§2 step 9), not only after step 3
of the original 5-commit sequence.

---

## 6. Feature Flag Design (D5)

```python
# apps/api/config.py — new setting, same block style as agent_detection_enabled
candidate_outreach_enabled: bool = False
```

**What it gates:** exactly the WIDENING described in D2 — whether a `GRAPH_CANDIDATE_PROVIDERS`
identity (`rb2b`/`leadpipe`/`capturify`/`beam_identity_network`) that is still `identity_status ==
"candidate"` (not yet human-confirmed) is emailable. See §3.1 for the exact `is_emailable_identity()`
logic change.

**STATUS: LOCKED as of PLAN supplement cycle 3 (S6/S7/S9/S10).** The
`candidate_outreach_enabled: bool = False` config setting (§ Implementation Checklist step 13)
remains valid and unblocked, and this section's OFF-state wiring is now a concrete, implementable
design — a WRAPPER at 3 call sites, not a parameter on `is_emailable_identity()`.

**Why the original in-helper design was rejected (history, kept for auditability — S10):** PVL cycle
2 found two independent, serious problems with the original confirm-gated design (adding a 4th
parameter directly to `is_emailable_identity()`):

1. **Not implementable as specified (Finding 4):** the "exact signature (binding)" originally given
   in §3.1 omitted the `identity_status` parameter that its own body-logic description
   (`not is_graph_candidate_provider(provider) or is_verified_identity(identity_status)`) required.
   `identity_status` was not in scope near the gate at any of the 5 named call sites.

2. **Breaks devjulley's own existing, intentional test suite (Finding 5, more severe):** the original
   design would have changed `is_emailable_identity("rb2b")` (and leadpipe/capturify) from
   unconditionally `True` to conditionally `False`, directly contradicting
   `test_is_emailable_identity_still_takes_exactly_three_params`,
   `test_candidates_are_emailable_not_blocked_by_tier`,
   `test_abuse_flag_default_false_preserves_existing_behavior`,
   `test_outbound_identity_gate.py::test_person_level_is_emailable` /
   `test_real_person_providers_stay_emailable`, and
   `test_agent_origin_exclusion.py::test_agent_origin_overrides_person_level` /
   `test_non_agent_identity_unaffected` — directly contradicting **Locked Decision D3** and the
   existing locked program SPEC's own architectural guidance ("the new personalization-gating
   requirement lands in the campaign draft/send composition layer, not in `is_emailable_identity()`
   itself").

**LOCKED design (PLAN supplement cycle 3, S6/S7/S10): wrapper check at 3 of the 5 named call sites,
ANDed with the result of the UNCHANGED, 3-param `is_emailable_identity()`:**
```python
emailable = is_emailable_identity(provider, source_agent_visit_id, is_abuse_flagged)
if emailable and is_graph_candidate_provider(provider) and not settings.candidate_outreach_enabled:
    emailable = is_verified_identity(identity_status)
```
This preserves `is_emailable_identity()` byte-for-byte (all of devjulley's existing tests pass
unmodified, satisfying D3), matches the SPEC's explicit architectural boundary, and delivers the
product intent of D9/D10 (a confirm-gated OFF state). Concretely, per §4's per-site table:
- **`campaign_sender.py` send gate** — reorder the EXISTING `identity_status` query to run before
  the gate (net zero new queries).
- **`routers/campaigns.py` `_resolve_linkedin_targets`** — add a NEW `identity_status` query per
  visitor in the loop (`Visitor` already imported).
- **`services/csv_exporter.py` `_get_segment_visitors`** — add a NEW `identity_status` query per
  member in the loop, plus a NEW `Visitor` import.
- **`services/hot_alert.py` and `services/outcome_digest.py` are EXPLICITLY EXCLUDED** — their
  `is_emailable_identity()` calls gate owner-facing name-reveal/ranking, not outreach-to-candidate;
  see §4 for the full reasoning. No change to either file.
- New unit tests live in `tests/unit/test_candidate_outreach_gate.py` (new file), written against the
  wrapper/call sites — never against `is_emailable_identity()` itself.
- This still satisfies AC3 of the locked SPEC ("Candidate-tier identity IS returned... Phase 0 does
  not block Candidates from outreach") for the ON state. For the OFF state, the "zero production
  behavior change" promise is corrected in §9/the Hard Stop text (S9) to name the confirm-path
  exception explicitly, rather than overstating parity with main's absolute-block posture.

**ON behavior:** full D2 rule — any `identity_level(provider) == "person"` identity is emailable
regardless of confirm status, restrained only by the personalization gate (generic copy for
unconfirmed candidates). Unaffected by this redesign — unchanged.

**Enabling is a separate deliberate operator action** — same posture as `agent_detection_enabled`,
`company_graph_enabled`, etc. This plan does NOT flip it on. Enabling requires: (a) all 3 pending
migrations for this program applied live, (b) the confirm-candidate endpoint proven in production
with real operator use, (c) explicit operator decision recorded in `all-context.md`'s "Open
Questions" section, matching precedent.

---

## Verification Evidence

### 7. Verification Evidence

Repo runner note: `.venv/bin/pytest`'s shebang is broken (points to a pre-move path) — use
`.venv/bin/python3.11 -m pytest` for every command below. Integration tests need
`docker compose -f infra/docker-compose.yml up -d postgres redis` first (see `TESTING.md`).

| Gate / Scenario | Strategy | Command | Proves SPEC criterion |
|---|---|---|---|
| Unit — identity classification (rewritten per §3.7, vocabulary-only — `is_emailable_identity()` itself unchanged, D10 redesign) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_identity_classification.py -v` | D1/D2 vocabulary correctness. **Must include the pre-existing `test_is_emailable_identity_still_takes_exactly_three_params`, `test_candidates_are_emailable_not_blocked_by_tier`, `test_abuse_flag_default_false_preserves_existing_behavior` cases passing UNMODIFIED — this is the regression gate proving the D10 wrapper redesign did NOT touch the shared helper.** |
| Unit — candidate outreach confirm-gate wrapper (NEW file, S6/S8) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_candidate_outreach_gate.py -v` | D5/D10 — OFF-state blocks unconfirmed graph-candidate outreach at the 3 wrapped call sites; ON-state restores D2's wide rule; non-graph-candidate providers unaffected either way |
| Unit — identity quality gates (rewritten) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_identity_quality_gates.py -v` | D1 — retired symbols fully gone, no import errors |
| Unit — Leadpipe webhook (rewritten) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_leadpipe_webhook.py -v` | D4 — Leadpipe webhook path survives with canonical vocabulary |
| Unit — outbound identity gate + agent origin exclusion (unchanged, regression only) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_outbound_identity_gate.py tests/unit/test_agent_origin_exclusion.py tests/unit/test_handoff_emailability_separation.py -v` | Direct regression gate for the D10 redesign — must pass with ZERO test modifications once §3.1 vocabulary-only changes land, proving `is_emailable_identity()` was correctly left untouched. |
| Unit — full identity/visitor suite regression | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/ -k "identity or visitor or campaign or kpi or timeseries" -v` | D1-D5 no regression across the full identity surface |
| Integration — Leadpipe webhook persistence (rewritten) | Hybrid — precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis` | `.venv/bin/python3.11 -m pytest tests/integration/test_leadpipe_webhook_persistence.py -v` | D4 — push-ingest path writes canonical vocabulary |
| Integration — events ingest (merged §3.9) | Hybrid — same precondition | `.venv/bin/python3.11 -m pytest tests/integration/test_events_ingest.py -v` | Both `TestCookieFpPhase2` (D4) and `TestUnknownSiteObservability` (D3) pass together, proving the merge kept both features |
| Integration — full suite regression | Hybrid — same precondition | `.venv/bin/python3.11 -m pytest tests/integration/ -v` | Full-branch regression before push |
| Migration chain integrity | Fully-Automated | `alembic -c apps/api/alembic.ini heads` (must print exactly 1 line) | §5 — single-head requirement |
| Migration chain offline validation | Fully-Automated | `alembic -c apps/api/alembic.ini upgrade <PROD_HEAD>:head --sql` (exit 0, no error) | §5 — chain applies cleanly |
| Migration live round-trip | Hybrid — precondition: disposable Postgres container available | `alembic upgrade head` → `alembic downgrade -1` → `alembic upgrade head` on a disposable container | §5 — known-gap if no disposable Postgres available, matches prior-migration precedent in this program |
| Web — status badge tone map | Agent-Probe | Manually render `StatusBadge` with `identity_status="candidate"`, confirm warning tone; confirm `vpn_flagged`/`merged` still render correctly | §3.8 |
| App boot smoke | Fully-Automated | `railway run -s retarget-agent -- python -c "import apps.api.main"` or local uvicorn boot | §5 — confirms migration re-chain didn't produce a boot-time crash (single-head is necessary but not sufficient) |
| Unit — fp3 fingerprint logic (NEW, S13, carried forward from `ae7ffb9`) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_pixel_fingerprint.py tests/unit/test_pixel.py -v` | §3.10/§3.11 — fp3 hashing + `<6144`/`<6000` byte pixel-size gate, must stay green post-rebuild |
| Pixel unit — full regression (NEW, S13) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/ -k "resolver or fingerprint" -v` | §3.2 extension — fp3-aware resolver logic does not regress vocabulary write path |
| E2E — pixel fingerprint v3 (NEW, S13) | Hybrid — precondition: `cd apps/pixel && npm run build` then Playwright browsers installed | `cd apps/pixel && npx playwright test e2e/fingerprint-v3.spec.ts` | §3.10 — fontFp/audioFp probes resolve correctly post-rebuild across chromium/webkit/firefox |
| Pixel size gate (NEW, S13) | Fully-Automated | `cd apps/pixel && npm run build && npm run size` (must print `< 6144`) | §3.10 — rebuilt `tracker.min.js` (both sides' additions) stays under the 6KB gate `ae7ffb9` itself set |

**Known-gap acceptance:** the migration live round-trip may be Known-Gap if no disposable Postgres is
reachable in the EXECUTE sandbox — matches the exact precedent already documented in this program
(5 prior migrations in the same live chain are offline-`--sql`-validated only). Do not treat this as
blocking; document it the same way `all-context.md`'s AI-Agent-Traffic Layer section already does.

---

## Resume and Execution Handoff

### 8. Resume Handoff and Rollback

**Selected plan file:** this file
(`process/features/visitors-identity/active/identity-vocab-reconcile_07-08-26/identity-vocab-reconcile_PLAN_07-08-26.md`).

**Last completed phase/step:** PLAN written; VALIDATE cycle 1 run (Gate: CONDITIONAL, 0 FAILs / 4
CONCERNs); PVL supplement cycle 1 folded E1-E4 into the plan body; VALIDATE cycle 2 run — Gate:
BLOCKED, 2 FAILs (Findings 4/5) + 1 CONCERN (Finding 6) in the original in-helper D5/D10 design; PLAN
supplement cycle 3 (S6-S11) redesigned §3.1/§3.7/§4/§6 as a call-site wrapper; VALIDATE cycle 4 run —
Gate: BLOCKED again, but for an UNRELATED reason (Finding 7: `devjulley`'s real tip had moved past
`1c5ae32` to `ae7ffb9`, unaccounted for in the Checklist/Touchpoints/§3.2) — the D10 wrapper design
itself was independently re-verified sound (Part A of that cycle's contract). **PLAN supplement cycle
5 (this pass, S12-S15) resolves Finding 7**: re-derived `devjulley`'s current tip live, folded
`ae7ffb9` into the Implementation Checklist (new rebase step), §3.2 (extended for the fp3 delta), and
two new conflict specs (§3.10 `tracker.js`, §3.11 `events.py` — the latter discovered as a genuine
non-trivial conflict via `git merge-tree`, going beyond what Finding 7's text itself named). Also
made the plan **derivation-based** throughout (S12) per user decision U2 — `devjulley` is not frozen
and the Implementation Checklist now opens with a mandatory step-0 pre-flight re-derivation. Do NOT
proceed to EXECUTE yet — VALIDATE (PVL cycle 5, from V1) must confirm this supplement before the gate
can move past BLOCKED.**

**Validate-contract status:** written (PVL cycle 4, Gate: BLOCKED, generated-by: outer-pvl — see
`## Validate Contract` below; that section is NOT modified by this supplement (per hard constraint)
and will be superseded by the PVL cycle 5 re-run).

**Rollback / abandon-again git state:** two backup refs exist and must NOT be deleted or moved by
this plan's execution: `backup/main-06-08-26` (main's state before this reconciliation began) and
`backup/devjulley-pre-rebase-06-08-26` (devjulley's state before the prior aborted rebase attempt).
If the rebase must be abandoned again: `git rebase --abort` if mid-rebase, then
`git reset --hard backup/devjulley-pre-rebase-06-08-26` to return `devjulley` to its pre-attempt
state. `main` is unaffected by an aborted rebase of `devjulley` (rebase target, never mutated by a
`git rebase <target>` on the source branch) — no rollback action needed on `main` unless commits were
separately cherry-picked onto it. **PVL cycle 2 re-confirmed both backup refs exist and are intact
(`backup/main-06-08-26` = `db180c44...`, exactly equal to `git merge-base main devjulley` — an
independent third confirmation of the correct fork point).**

**Force-push warning:** `devjulley` is ALREADY PUSHED to `origin/devjulley` (confirmed:
`## devjulley...origin/devjulley` with no divergence markers at RESEARCH time). Any successful
rebase of `devjulley` onto `main` requires `git push --force-with-lease origin devjulley` afterward
— never a plain `--force`. If another agent or the user has pushed to `origin/devjulley` since this
plan was written, `--force-with-lease` will correctly refuse and must not be overridden blindly.

**EXECUTE resume note for a fresh agent:** **DO NOT ENTER EXECUTE MODE for this plan yet.** The
`## Validate Contract` section below is PVL cycle 4's output (Gate: BLOCKED, Finding 7) and predates
this supplement — read it for the Finding 7 evidence trail (branch-tip drift, not a design problem),
then read §3.2's extension, §3.10, and §3.11 in the plan body for the concrete resolution. **ENTER
VALIDATE MODE (PVL cycle 5) must run and reach PASS or an accepted CONDITIONAL before EXECUTE.** Once
cleared, run the Implementation Checklist's **mandatory step-0 pre-flight** (re-derive `main`,
`devjulley`, the commit list, and the migration set live via `git`/`alembic` — do not reuse this
session's `ae7ffb9`/`332b3a8` as frozen facts) as the FIRST EXECUTE action regardless of how much
time has passed since this supplement was written — the branch is explicitly not frozen (U2) and may
have moved again. Follow the Implementation Checklist's CORRECTED step order — do not follow a
literal/older step order; the migration re-chain (step 5) runs AFTER the `626d643` rebase (step 3),
and the `ae7ffb9` rebase (new step 12) runs AFTER `1c5ae32` (step 11), not interleaved differently.

---

## 9. Auditability of the Emailability Widening (D2/D9)

This reconciliation, once merged AND `candidate_outreach_enabled` is flipped on by an operator,
**widens who Beam may email** — RB2B/Leadpipe/Capturify-sourced leads that are still unconfirmed
graph guesses become legitimate outreach targets (restrained to generic, non-personalized copy).
This is not a new decision made by this plan — it is D2, the user's explicit locked decision,
inherited from the existing SPEC's AC2. This plan's job is to make it **auditable**, not to
re-approve it:

- the `candidate_outreach_enabled` flag defaults OFF (§6) — merging this plan changes zero
  production behavior with respect to the FLAG toggle itself. **Corrected wording (PLAN supplement
  cycle 3, S9 — resolves Finding 6): this promise does NOT extend to the confirm-candidate action.**
  A human clicking "confirm" on devjulley's own confirm-candidate endpoint (D3, must survive intact)
  sets `identity_status = "identified"`, which makes that identity emailable under D2's WIDE rule
  REGARDLESS of `candidate_outreach_enabled` — this is D10's intentional confirm-gated design (§6),
  not a bug, and it is a REAL, deliberate exception to "zero behavior change." The accurate claim is:
  **merging this plan changes zero production behavior for any identity that is not explicitly
  human-confirmed via the confirm-candidate endpoint; a human-confirmed identity becomes emailable
  regardless of the flag, by design (that is the entire point of a confirm workflow — see §6's
  rationale).** The flag's OWN scope is narrower than the plan's earlier wording implied: it gates
  ONLY whether an UNCONFIRMED graph-candidate identity is emailable, not whether a CONFIRMED one is.
- enabling `candidate_outreach_enabled` (the WIDE, unconfirmed-candidate rule) requires an explicit
  operator action, to be logged in `process/context/all-context.md` "Open Questions / Outstanding
  Work" the same way `agent_detection_enabled` and siblings are logged — this is unchanged and
  unaffected by the confirm-path exception above, which is a separate, always-on pathway
- the OFF-state design (confirm-gated, per D10) was resolved at VALIDATE cycle 1, SUSPENDED at
  VALIDATE cycle 2 (implementability + D3 conflict), and REDESIGNED + RE-LOCKED at PLAN supplement
  cycle 3 (S6/S10) as a call-site wrapper — see §6 and the Validate Contract for the full history

---

## 10. Open Items for Closeout / VALIDATE

**Resolved at VALIDATE cycle 1 (folded into the plan body):**

1. ~~§6 OFF-state exactness question~~ — **RE-OPENED at PVL cycle 2, RESOLVED at PLAN supplement
   cycle 3.** Cycle 1's original in-helper D10 resolution was not implementable and broke devjulley's
   own test suite (Findings 4-6). Redesigned as a call-site wrapper (§6, S6/S7/S10) — pending VALIDATE
   cycle 3 re-confirmation.
2. ~~§3.5 `routers/dashboard.py` full-file diff~~ — **RESOLVED, still valid:** full-file diff run at
   VALIDATE, confirmed zero other main-only dashboard sections exist. devjulley's structure accepted
   wholesale.
3. ~~§4 `routers/visitors.py:1045` dead-path question~~ — **RESOLVED, still valid:** confirmed a
   genuinely separate, live endpoint (`manually_identify_visitor`) distinct from devjulley's
   confirm-candidate endpoint; simple literal rewrite is sufficient, no path deletion needed.

**Resolved at PLAN supplement cycle 3 (was blocking at PVL cycle 2):**

5. §3.1/§3.7/§4/§6 D10 redesign — **RESOLVED.** Wrapper check now locked at 3 of 5 named call sites
   (`campaign_sender.py`, `csv_exporter.py`, `routers/campaigns.py`); `hot_alert.py` and
   `outcome_digest.py` explicitly excluded (§4/§6). `is_emailable_identity()` itself is unchanged.
   **Still requires VALIDATE (PVL cycle 3, from V1) to confirm before EXECUTE — this is a plan
   redesign, not yet re-validated.**

**Resolved at PLAN supplement cycle 5 (was blocking at PVL cycle 4, Finding 7):**

6. `devjulley`'s real current tip (`ae7ffb9`, fingerprint v3) was unaccounted for by the
   Implementation Checklist, Touchpoints/Blast Radius, and §3.2 — **RESOLVED.** Fresh
   `git log main..devjulley --oneline` + `git diff --name-only main...devjulley -- .../migrations/`
   re-derived live (not reused from cycle 4's finding); folded into the Implementation Checklist
   (new step for `ae7ffb9`, plus a mandatory step-0 pre-flight so this class of drift cannot recur
   silently), §3.2 (extended for the fp3 delta), and two new conflict specs (§3.10 `tracker.js`,
   confirmed clean content-merge via `git merge-tree`; §3.11 `events.py`, a genuinely non-trivial
   race-fix + fp3 logic merge, discovered via the same `git merge-tree` run — NOT in the original
   Finding 7 text, found by going one level deeper than the finding asked for). **Still requires
   VALIDATE (PVL cycle 5, from V1) to confirm before EXECUTE.**

**Still open (not blocking, matches program precedent):**

4. §7 migration live round-trip — likely Known-Gap depending on EXECUTE sandbox Docker availability
   (confirmed UNAVAILABLE at all four VALIDATE cycles to date); accept per program precedent, do not
   block on it.
7. **Structural, not a one-time fix (S12):** `devjulley` is explicitly NOT frozen (user decision U2)
   — it may move again before EXECUTE actually runs. The Implementation Checklist's mandatory step-0
   pre-flight re-derivation is the standing anti-recurrence mechanism for this; it is not itself a
   closeable open item, it is a permanent feature of this plan going forward.

---

## Test Infra Improvement Notes

**KNOWN GAP (added PLAN supplement cycle 9, S20) — the `identity_resolver.py` `is_privacy_relay_ip`
call site has NO covering test.** `tests/unit/test_identity_quality_gates.py` and
`tests/unit/test_company_resolver.py` only exercise the standalone
`company_resolver.is_privacy_relay_ip()` function; `tests/unit/test_leadpipe_webhook.py` patches it
on a *different* module. Nothing asserts that the resolver actually calls the guard, that it fires
**before** the `check_ip_privacy` / `is_ip_suspicious` IPinfo check, or that it sets
`visitor.identity_status = "vpn_filtered"`.

This is a **real coverage hole independent of this reconciliation** — it is exactly why the guard was
invisible to 8 PVL cycles (see §3.2's fourth porting item): the guard could be silently dropped in
any future merge and **no test would fail**, while masked Private Relay IPs reached paid
RB2B/Leadpipe/Capturify lookups.

**Resolution: backlog (option D).** Write a follow-up backlog artifact —
`resolver-privacy-relay-callsite-coverage_NOTE_07-08-26.md` in
`process/features/visitors-identity/backlog/` — proposing a Fully-Automated unit test that asserts
(a) the resolver short-circuits on a `2a09:bac3::/32` IP, (b) it sets `identity_status ==
"vpn_filtered"`, and (c) no paid provider is invoked. Not in this plan's blast radius; recorded so it
is not lost.

## Autonomous Goal Block

```
SESSION GOAL: Reconcile devjulley onto main — retire main's verified/provider_candidate identity
vocabulary in favor of devjulley's identified/candidate, widen emailability behind a default-OFF
flag, re-chain devjulley's alembic sub-chain, resolve 8 rebase conflicts including devjulley's
real current tip (identity-vocab-reconcile_07-08-26).
Charter + umbrella plan: N/A — standalone task folder, not a phase of
identity-program-umbrella_PLAN_03-08-26.md (related context only).
Autonomy: Execute this plan's Implementation Checklist on its own recommendation once VALIDATE
passes. **Status: NOT yet accepted — PVL cycle 4 was Gate: BLOCKED (Finding 7: devjulley's tip had
moved past what the plan documented); PLAN supplement cycle 5 (S12-S15) resolved it and made the
plan derivation-based throughout. VALIDATE (PVL cycle 5, from V1) must run and pass before EXECUTE.**
Report conflicts, errors, and learnings in the EXECUTE report. Only pause for outward-facing /
irreversible / costful / destructive actions.
Hard stop conditions / safety constraints:
- The devjulley branch is NOT frozen and may move again — EXECUTE MUST re-derive the commit list
  and migration set live (Implementation Checklist step 0, mandatory pre-flight) before starting,
  and STOP if the live output differs from what this plan last recorded, rather than proceeding on
  a stale assumption.
- Any push to `main` is a production DDL + deploy event (Railway runs `alembic upgrade head` on
  every boot). Never push to `main` without explicit human sign-off.
- `railway` commands (the §5 step 0 live prod pre-check) are blocked for agents — must be run by
  the human, never simulated or skipped.
- Enabling `candidate_outreach_enabled` widens who Beam may email UNCONFIRMED graph-candidates —
  a separate deliberate operator action, never part of this merge. A human-CONFIRMED identity is
  emailable regardless of this flag, by design (§6/§9) — that exception is not a hard-stop violation.
- Never `git push --force` on `devjulley` — only `--force-with-lease`.
- Never delete or move the two backup refs (`backup/main-06-08-26`,
  `backup/devjulley-pre-rebase-06-08-26`).
Next phase: **VALIDATE (PVL cycle 5)** — re-run from V1 against the S12-S15 supplement
(derivation-based Checklist/Touchpoints, §3.2 extension, §3.10 tracker.js, §3.11 events.py).
EXECUTE is not next until that cycle reaches PASS or an accepted CONDITIONAL.
Validate contract: inline in plan (## Validate Contract) — PVL cycle 4's output (Gate: BLOCKED),
superseded by the PVL cycle 5 re-run.
Execute start: NOT YET — pending VALIDATE cycle 5. Once cleared: fully-auto commands —
`.venv/bin/python3.11 -m pytest tests/unit/test_identity_classification.py tests/unit/test_pixel_fingerprint.py -v`
+ `alembic -c apps/api/alembic.ini heads` | e2e spec —
`apps/pixel/e2e/fingerprint-v3.spec.ts` (new, post-rebuild) | probe scenario — manual StatusBadge
render (§3.8) | high-risk pack: yes (auth/identity emailability rule change + schema migration
re-chain — see §9 Auditability).
```

## Validate Contract

Status: CONDITIONAL
Date: 07-08-26
date: 2026-08-07
generated-by: outer-pvl
supersedes: 2026-08-07 (outer-pvl) — this is PVL cycle 8, re-validating from V1 after PLAN
supplement cycle 7 (S16-S19) fixed the §3.11 svid-gate wording, the fork-point conflation (§5),
the migration-facts labelling, and struck the cycle-6 self-acceptance. Cycle 8 independently
re-verifies cycle 7's fixes AND runs a fresh deep pass across the six under-verified conflict
files. It supersedes PVL cycle 6's `Gate: CONDITIONAL` contract (cycle 7 itself was a PLAN-
supplement pass and did not carry its own Gate verdict).

**PVL cycle: 8 of max 10.**

Parallel strategy: sequential
Rationale: Signal count re-scored this cycle: 1/7 (single feature area, no phase program, no
multi-package scope — unchanged since cycle 1). Sequential remains correct regardless of fan-out
availability. **Fan-out disclosure (explicit, not silently substituted): this validate-agent
invocation again has NO Agent/Task tool in its toolset (tools available: Read, Bash, Write only) —
the 7th consecutive cycle without the designed two-layer fan-out (4 Layer-1 dimension agents + N
Layer-2 per-section agents in parallel) running INSIDE this agent. Per the task brief, the
orchestrator is again running 2 external adversarial verifier agents in parallel outside this
session, scoped to the six under-verified conflict files this cycle names explicitly
(`identity_classification.py`, `identity_resolver.py`, `test_identity_classification.py`,
`kpi.py`, `timeseries.py`, `status-badge.tsx`, `test_events_ingest.py`); this contract records only
THIS agent's own single, sequential, deep-verification pass — it does not fabricate or anticipate
the external verifiers' findings. This cycle's pass was budgeted toward re-executing ground-truth
commands (`git show`/`diff`/`merge-tree`/`merge-file`/`ls-tree`/`reflog`/`rev-parse`, `alembic`)
against explicitly PINNED commit hashes rather than the floating `devjulley`/`main` branch names,
after this pass itself caught the `devjulley` ref moving mid-session (see Finding 13 below) and had
to discard and re-run several checks that had silently resolved against the wrong tree. Every one
of the 7 prior cycles that ran this same deep-single-pass substitution surfaced a real, previously
undetected finding; this cycle is no exception (Findings 12 and 13 below).**

### PVL Cycle 8 — Independent Verification (NEW findings, this cycle only)

**Method:** every claim below was re-derived live against explicitly PINNED commit hashes
(`main` = `332b3a8`, `devjulley` = `ae7ffb9e1be44c321152de0713fcfbb3c7b2b9a3` — the hash cycle 5-7
confirmed and the plan is written against), using `git show <hash>:<path>`, `git diff <hash>
<hash>`, `git merge-tree --write-tree --merge-base=<db180c44...> main <hash>`, and
`git merge-file` for literal conflict-marker reconstruction. Repo state note: the working tree is
mid an in-progress, unauthorized interactive rebase (detached HEAD, `UU
apps/api/services/identity_resolver.py`) that the orchestrator has already flagged as an incident
under user inspection — this validate pass did not touch git state and did not read the working
tree as branch content, per the task's explicit safety constraints.

**Re-verified and CONFIRMED HOLDING (no defect, high confidence):**

- `is_emailable_identity()` on pinned `devjulley` (`ae7ffb9`) has exactly 3 parameters (`provider`,
  `source_agent_visit_id`, `is_abuse_flagged`) — hard constraint from S6 intact.
- `identity_classification.py`: `PERSON_LEVEL_PROVIDERS` includes `"contact_import"`;
  `EMAILABLE_PROVIDERS` is absent from `devjulley`, present on `main` — matches §3.1 exactly.
- `kpi.py` / `timeseries.py` diffs (main vs pinned devjulley) are 100% vocabulary-only — zero D4
  content to re-port, confirming §3.3/§3.4's "pure adopt-devjulley" claim.
- `identity_resolver.py`: `ae7ffb9`'s 43+/14- fp3 delta (fingerprint-match block ~L368-430,
  `BeamIdentityNode` upsert ~L982-1013, graph-lookup ~L1070-1100+) is confirmed **fully disjoint**
  from the vocabulary write sites (L888/L940 at the pre-`ae7ffb9` `1c5ae32` snapshot §3.2 actually
  targets) — read every hunk of the real diff, not just trusted the plan's characterization.
- `identity_resolver.py` D4 content genuinely absent from pinned `devjulley`: provider-outage
  handling and the `resolution_deferred_until`/`resolution_defer_count` watermark columns (migration
  `c2f7a9d31b64`) exist only on `main` relative to pinned `ae7ffb9` — §3.2's "must be ported" claim
  holds. (This required a self-correction — see Finding 13 below; an initial pass against the
  floating `devjulley` branch NAME wrongly suggested this content was already shared, because the
  ref had moved mid-session to a post-rebase-merge tree that naturally includes main's history.)
- `status-badge.tsx`: `vpn_filtered` and `merged` confirmed absent from pinned `devjulley`'s tone
  map but confirmed LIVE-ASSIGNED (`identity_resolver.py:559,859`, `promotion_sweep_runner.py`,
  `routers/visitors.py:192`) — §3.8's "must re-add both keys" claim holds.
- `apps/api/routers/dashboard.py` / `visitors_helpers.py` (§3.5/§3.6, Findings 8/9's sibling,
  E-9): reconstructed the ACTUAL git 3-way auto-merge output tree (not just the conflict list) and
  confirmed E-9's precise claim — the clean auto-merge silently produces **main's verbatim old
  vocabulary** (`from apps.api.services.identity_classification import VERIFIED_STATUSES` still
  present, `.filter(Visitor.identity_status.in_(VERIFIED_STATUSES))` still present) for both files.
  E-9 is not just correctly diagnosed, it is now proven byte-for-byte accurate.
- `tests/integration/test_events_ingest.py` (§3.9): reconstructed the literal 3-way merge conflict
  markers via `git merge-file`. Confirmed the conflict is exactly as trivial as §3.9 describes —
  `main`'s side of the conflicted hunk is EMPTY (main added nothing beyond `TestCookieFpPhase2`,
  which is present byte-identically on both branches from a shared ancestor insertion point) and
  `devjulley`'s side has the full 93-line `TestUnknownSiteObservability` addition. "Concatenate,
  keep both" (§3.9) reduces to "accept devjulley's side wholesale" — verified via literal conflict
  reconstruction, not inferred from the diff summary.
- Full merge-tree conflict sweep, redone independently against the pinned hash: exactly 8
  CONFLICT files (`events.py`, `identity_classification.py`, `identity_resolver.py`, `kpi.py`,
  `timeseries.py`, `status-badge.tsx`, `test_events_ingest.py`, `test_identity_classification.py`).
  `tracker.js` auto-merges with zero conflict markers (§3.10 confirmed). 8-for-8 match the plan's
  §3 spec list — reproduces cycle 6's V1 verifier claim with a third independent method.
- §5 migration re-chain: `a7d419e6c052` confirmed NOT a git object (`git cat-file -t` fails);
  `git merge-base main devjulley` = `db180c44...`, distinct from the Alembic revision id — S17's
  correction holds. `b1c9e7f24d83.down_revision` on pinned `devjulley` = `a7d419e6c052`; `main`'s
  true head (nothing references it as a `down_revision`) = `c2f7a9d31b64`. One edit
  (`b1c9e7f24d83.down_revision` → `c2f7a9d31b64`) yields a single valid 60-revision chain — S18
  holds.
- §3.11 events.py gate: confirmed §3.11 step 5 now reads `if fp_value or fp3_value or svid:` in
  the plan body (S16's fix applied and intact) — no stale wording survives elsewhere.
- Confirm-gate wrapper call sites: exactly the 3 claimed production wrapper targets
  (`campaign_sender.py`, `routers/campaigns.py`, `csv_exporter.py`) plus the 2 claimed exclusions
  (`hot_alert.py`, `outcome_digest.py`) call `is_emailable_identity()` on pinned `devjulley` — S7/S8
  holds.
- `Accepted by: PENDING` marker intact; no self-acceptance language present (S19 holds).

**NEW Finding 12 (CONCERN) — plan cites a test function name that does not exist, in 4 places.**

`test_candidates_are_emailable_not_blocked_by_tier` is cited at §3.1 (line ~455), §3.7 (line ~546),
§6's historical rejection narrative (line ~908), and the Validate Contract's own Test Gates table
(line ~966) as a pre-existing `devjulley` regression test proving the D10 wrapper redesign left
`is_emailable_identity()` untouched. **This function does not exist anywhere in the codebase**,
confirmed via `git show ae7ffb9:tests/unit/test_identity_classification.py | grep -n
"candidates_are_emailable_not_blocked_by_tier"` (zero matches) and a full listing of the file's
test names. The real, similarly-purposed test in that exact file is
`test_candidates_remain_emailable` (line 115) — same docstring intent ("test exists to catch a
future change that 'helpfully' folds the candidate tier into `is_emailable_identity`"), different
name. A second, genuinely different test with an almost-identical name,
`test_graph_candidates_are_emailable_not_blocked_by_tier`, exists in a DIFFERENT file
(`tests/unit/test_outbound_identity_gate.py`, line 36). The plan's cited name appears to be a
conflation of these two real tests into a name that matches neither.

Impact: does not break the actual Fully-Automated gate (`pytest
tests/unit/test_identity_classification.py -v` runs the whole file regardless of individual test
names, and `test_candidates_remain_emailable` genuinely exists and genuinely proves the intended
regression). The risk is narrower but real: any execute-agent or reviewer trying to confirm "the
cited pre-existing test passed unmodified" by searching pytest output for the literal cited string
will find nothing, and could wrongly conclude the D10 safety-net test is missing or was deleted —
wasted investigation at best, an unnecessary duplicate-test "fix" at worst.

**Recorded as Execute-Agent Instruction E-10 below.**

**NEW Finding 13 (OBSERVATION, not counted as CONCERN) — `devjulley` branch ref moved again,
mid-validate-session, traced to the already-flagged unauthorized rebase.**

`git rev-parse devjulley` returned `ae7ffb9e1be44c321152de0713fcfbb3c7b2b9a3` early in this
session and `3528c00de20252ecda5ad9e82efa66315de6b57f` later in the SAME session. `git reflog show
devjulley` confirms the mechanism: `devjulley@{0}: branch: Reset to HEAD` — the branch pointer was
explicitly reset to track the in-progress rebase's current position. This is structurally
different from cycle 4's Finding 7 (a genuine new commit landing organically): `3528c00` carries
the SAME commit message as `ae7ffb9` ("feat(identity): fingerprint v3...") but its tree differs by
132 files / +281,130/-387 lines from `ae7ffb9`'s tree, because it now sits on top of `main`
(`332b3a8`) per the in-progress, unauthorized rebase, rather than on `devjulley`'s own pre-rebase
base.

This is not treated as a plan-content defect — no plan text needs to change, because S12's
derivation-based design (every fact paired with the live command that reproduces it) already
assumes the branch is not frozen. It is recorded because: (1) it is fresh, concrete, this-session
evidence that EXECUTE absolutely cannot begin while the rebase is unresolved, independently
corroborating cycle 7's `Accepted by: PENDING` / "EXECUTE is NOT yet unblocked" status rather than
introducing a new reason; (2) it is a **methodology correction for this validate pass itself** —
several of this cycle's initial checks (the D4-content-in-`identity_resolver.py` check, in
particular) were first run against the floating `devjulley:` ref NAME rather than the pinned hash,
and produced a WRONG intermediate result (D4 content appeared already-shared, when it is genuinely
main-only relative to the plan's actual target `ae7ffb9`) until this was caught and every affected
check was re-run against the pinned hash. All findings and confirmations in this contract are from
the pinned-hash re-run, not the contaminated intermediate pass. Any future validate or execute
pass against this repo, while any rebase might be in flight, MUST pin explicit commit hashes and
must not trust `main`/`devjulley` as stable ref names.

**Late-session addendum (same Finding 13, observed in the final minutes of this cycle):**
`devjulley` moved a **third** time within this single validate session — `git rev-parse devjulley`
now returns `5293cbc2de233a8431412ad1a4501a2a1eccfebb`, distinct from both the original pinned
`ae7ffb9` and the mid-session `3528c00...` this finding first documented. `git status` no longer
reports an in-progress rebase — the working tree is now a clean checkout of `devjulley` with a
large, unrelated set of modifications (agent `.md` files, `apps/api/config.py`,
`apps/api/main.py`, a new `job_change_event` model/migration/test, two `evallayer` plan files
moved from `active/` to `completed/`) that were not present at session start and are outside this
plan's blast radius. `main` is unchanged (`332b3a8`, matches every pinned value used throughout
this contract). This is read as the rebase having been resolved or aborted by the user during this
session, consistent with the task brief's statement that the user is personally inspecting and
resolving it — not as a new incident. It does not change any content-level finding above (all were
verified against immutable, explicitly pinned commit hashes, which remain true regardless of what
`devjulley` points to now); it is one more concrete data point that the branch is genuinely live
and the mandatory step-0 pre-flight in the Next Instruction section is not optional.

---

### Independent Verification Performed (PVL cycle 6 — re-derived from live git/alembic state,
cross-checked against source on both branches; nothing below is re-quoted from cycle 5's
supplement claims without independent confirmation)

**Part A — re-deriving branch state fresh (the exact anti-recurrence check PLAN supplement cycle 5
(S15) added to guard against repeating cycle 4's Finding 7):**

- `git rev-parse main` → `332b3a88af09e8ea3b55a1825b1a18da351c2546` (short `332b3a8`) — **exact
  match** to what PLAN supplement cycle 5 recorded.
- `git rev-parse devjulley` → `ae7ffb9e1be44c321152de0713fcfbb3c7b2b9a3` (short `ae7ffb9`) —
  **exact match**.
- `git log main..devjulley --oneline` → exactly the 6 commits the plan documents (`ae7ffb9`,
  `1c5ae32`, `fe89466`, `626d643`, `a066006`, `e11a91d`) — **exact match, same order**.
- `git diff --name-only main...devjulley -- apps/api/migrations/versions/` → exactly the 4
  migration files the plan documents (`b1c9e7f24d83`, `c2f8a5d31e97`, `e9d2a4c71f68`,
  `f1a7c3e05b92`) — **exact match**.
- `origin/devjulley` = `1c5ae32` (0 ahead / 1 behind local `devjulley`) — confirms `ae7ffb9` is
  still genuinely unpushed, as the plan states.
- Both backup refs intact and unmoved: `backup/main-06-08-26` = `db180c4` (still equals
  `git merge-base main devjulley`), `backup/devjulley-pre-rebase-06-08-26` = `1c5ae32`.

**Result: zero drift since PLAN supplement cycle 5. This is the first VALIDATE cycle in this plan's
history (cycles 1, 2, 4 all found some form of drift or defect) where the live branch-tip
re-derivation found NO delta at all.** Finding 7's underlying risk (the branch is not frozen) is
structural, not closed — but the S15 pre-flight discipline is doing its job: nothing has moved
between the supplement and this re-validation.

**Part B — verifying PLAN supplement cycle 5's S12-S15 claims (do not take on trust):**

- **S12 (derivation-based conversion) — VERIFIED TRUE.** Grepped the plan for every
  `down_revision = "..."` literal used as a binding instruction: the only two are
  `f1a7c3e05b92`'s and `b1c9e7f24d83`'s tail-of-chain lines, both stated as **already-correct,
  informational** ("already correct — extends the tail, no re-chain edit needed"), never as a
  target to write. The actual re-chain target is written as `<PROD_HEAD>` / `<PROD_HEAD as
  re-confirmed in step 0>` throughout §5 and the Implementation Checklist, with explicit language
  "do NOT hardcode a planned head" and "do not literal-substitute `e6b2d4a1c837` without
  re-confirming it is still current." No live binding step uses a hardcoded hash. Confirmed the
  mandatory EXECUTE step-0 pre-flight exists (Implementation Checklist, opening block) and
  contains an explicit hard-stop instruction ("If the commit list, the migration file set, or
  `main`'s head differs from what is recorded here: STOP. Do not proceed on the stale
  assumption.") — this is not a footnote, it is the first instruction in the checklist.
  **Additional confirmation this cycle: main's own local alembic head is `c2f7a9d31b64`, which is
  materially different from the `e6b2d4a1c837` figure `all-context.md` still documents as the
  "TRUE current head" (dated 26-07-26) — main has advanced significantly since then (confirmed via
  `alembic history`: `e6b2d4a1c837` is many revisions upstream of `c2f7a9d31b64`, not the current
  tip). This is exactly the scenario S12's derivation-based design exists to survive — a plan that
  had hardcoded `e6b2d4a1c837` as the re-chain target would be wrong today. The plan's own
  documented `<PROD_HEAD>` note about "concurrent-program migration collisions" is proven correct
  and necessary by this observation, not merely cautious prose.**
- **S13 (tracker.js / events.py / tracker.min.js) — VERIFIED TRUE, with one real correction found
  (see Part C).** Ran `git merge-tree --write-tree --merge-base=<merge-base> main devjulley`
  directly (not re-trusting the plan's prior report): `apps/pixel/src/tracker.js` reports
  "Auto-merging apps/pixel/src/tracker.js" with **zero CONFLICT lines** — confirms the clean
  auto-merge claim exactly as documented. `apps/api/routers/events.py` reports **CONFLICT
  (content): Merge conflict in apps/api/routers/events.py** — confirms the genuine-9th-conflict
  claim exactly. Read both branches' full `_process_signal_events` function bodies directly (`git
  show main:...` and `git show devjulley:...`) rather than trusting the plan's summary: main's
  `pg_insert(...).on_conflict_do_update(...)` upsert-stub structure and devjulley's dual-UPDATE
  fp2/fp3/svid structure are both confirmed exactly as the plan describes them. **However, the
  plan's §3.11 resolution spec step 5 contains a factual error about main's actual gating
  condition — see Part C, Finding 8, for the concrete correction.**
- **S13 pixel size gate — VERIFIED TRUE, exactly.** `devjulley`'s `apps/pixel/package.json`
  description string reads "...must stay <6KB gzipped)" (main's reads "<5KB"); `git grep` on the
  current `devjulley` checkout confirms `tests/unit/test_pixel.py:155` asserts `size < 6144` and
  `tests/unit/test_pixel_fingerprint.py:224` asserts `len(compressed) < 6000` — the 6KB figure is
  real, current, and not the stale 5KB the plan explicitly warns against assuming.
- **S13 migration chain — VERIFIED TRUE via the real alembic CLI, not a hand-parser.** Ran
  `python3.11 -m alembic -c apps/api/alembic.ini heads` on the current `devjulley` checkout:
  prints exactly **`f1a7c3e05b92 (head)`**, one line. Ran `alembic history` and confirmed the full
  linear chain: `a7d419e6c052 → b1c9e7f24d83 → c2f8a5d31e97 → e9d2a4c71f68 → f1a7c3e05b92 (head)` —
  matches the plan's S14 claim exactly ("only the first link re-chains onto main's live head").
  Separately extracted `main`'s tree into a disposable archive (`git archive main | tar -x`, no
  shared-container risk) and ran the same real CLI: prints exactly **`c2f7a9d31b64 (head)`**, one
  line, chain `a7d419e6c052 → b4c9a71e35d8 → c2f7a9d31b64 (head)` — matches the plan's own §5 PVL
  cycle 2 finding verbatim. Both branches independently single-headed, confirmed with the tool the
  task specifically asked for (not a hand-rolled parser).
- **S15 (goal block) — VERIFIED TRUE.** Measured the `## Autonomous Goal Block` fenced content
  programmatically: **3,030 characters**, under the 4,000 hard limit. Contains the explicit hard
  stop: "The devjulley branch is NOT frozen and may move again — EXECUTE MUST re-derive the commit
  list and migration set live... and STOP if the live output differs."

**All of PLAN supplement cycle 5's claims are independently verified TRUE, with one precise
correction (Finding 8, Part C) to a resolution-spec detail that PLAN supplement cycle 5 did not
itself get wrong in substance (the conflict was correctly identified as genuine and non-trivial)
but did characterize one sub-detail of incorrectly.**

**Part C — settled/locked decisions re-confirmed still true (per task instruction: "verify they
still hold, but do not redesign"):**

- **D10 wrapper mechanics, all 3 in-scope call sites** — re-grepped `is_emailable_identity(` across
  the current checkout: exactly 5 production call sites at the exact line numbers the plan states
  (`campaign_sender.py:283`, `csv_exporter.py:79`, `routers/campaigns.py:725`, `hot_alert.py:88`,
  `outcome_digest.py:161`). `campaign_sender.py`'s `identity_status` query is confirmed still at
  ~L336-338, still after the L283 gate. `is_emailable_identity()`'s own definition (line 109) is
  unchanged — 3-parameter form, as devjulley wrote it.
- **D10 exclusions (hot_alert.py, outcome_digest.py) — re-confirmed by tracing every `.send(...)`
  call in both files this cycle:** `hot_alert.py` sends to `to_email=owner.email` only (2 send call
  sites, lines 107-108 and 183-184); `outcome_digest.py` sends to `to_email=owner_email` only
  (line 274, sourced from a `owner_email` loop variable over `(site_id, site_name, owner_email)`
  rows). Neither file can cause an outbound message to a candidate visitor. Exclusions remain
  correct.
- **Call-site sweep completeness (dimension 3) — independently re-grepped every retired symbol on
  `main`** (`VERIFIED_STATUSES`, `STATUS_VERIFIED`, `STATUS_PROVIDER_CANDIDATE`,
  `PROVIDER_CANDIDATE_STATUSES`, `identity_status_for_provider`, `EMAILABLE_PROVIDERS`): every hit
  location matches the plan's §4 table exactly, no new hit locations found, no stale entries.
  Confirmed `is_verified_identity` / `is_graph_candidate_provider` have **zero** hits on `main`
  (devjulley-only symbols, nothing to reconcile). Confirmed all 4 of the "no code change expected"
  test files (`test_agent_origin_exclusion.py`, `test_handoff_emailability_separation.py`,
  `test_outbound_identity_gate.py`, `test_identity_classification.py`) are genuinely clean of
  `EMAILABLE_PROVIDERS` on the current `devjulley` checkout. Confirmed `test_identity_quality_gates.py`,
  `test_leadpipe_webhook.py`, `tests/integration/test_leadpipe_webhook_persistence.py` exist ONLY on
  `main`, not `devjulley` — exactly as the plan's §3.7 tail claims.
- **Emailability blast radius (dimension 1, HIGHEST RISK) — re-confirmed this cycle cannot
  implicitly widen the send audience.** The wrapper is additive-restrictive only (it can only
  narrow, via `emailable = is_verified_identity(identity_status)`, never widen beyond what
  `is_emailable_identity()` already allowed); the 2 exclusions are verified non-outreach paths
  (above); `is_emailable_identity()`'s own signature/body is unchanged (verified byte-identical
  this cycle via direct read of the function definition). No path in this reconciliation's own
  design change can cause an identity that was not previously emailable to become emailable except
  through the pre-existing, explicitly-disclosed confirm-candidate action (D9/§9), which is not new
  behavior introduced by this plan.
- **`tracker.min.js` and pixel test files** — re-confirmed as build artifacts / additive tests, not
  merge targets, per S13 above.

**Part D — NEW findings this cycle (real, not environmental; both are precise, scoped, and
resolvable via an inline Execute-Agent Instruction rather than requiring a further PLAN
supplement round-trip):**

**Finding 8 (CONCERN, new this cycle) — §3.11's resolution spec step 5 mischaracterizes main's
actual gating condition for the merged `events.py` fingerprint/svid write block.**

**[STATUS, PLAN supplement cycle 7, S16: FIXED IN PLAN BODY.** §3.11 step 5 has been rewritten to
prescribe `if fp_value or fp3_value or svid:` and to describe main's real gate correctly; the wording
quoted below is preserved as the historical defect record. E-8 stays in place as belt-and-braces.**]**

The plan's §3.11 step 5 *previously* read: *"Gate the whole block on `if fp_value or fp3_value:` (devjulley's
condition), not main's `if fp_value:` alone — an event carrying only fp3 ... must still trigger the
upsert-stub path."*

Read main's actual code directly (`git show main:apps/api/routers/events.py`, the
`_process_signal_events` function): **main's real gating condition is `if fp_value or svid:`, not
`if fp_value:` alone.** The `svid` parameter is deliberately included in main's gate because main's
whole redesign (the `pg_insert(...).on_conflict_do_update(...)` upsert-stub) exists specifically to
fix a race where the `Visitor` row doesn't exist yet — and that fix benefits `svid` persistence
just as much as `fingerprint` persistence (both are written inside the same single upsert
statement, in the same `.values(...)` call).

If EXECUTE follows step 5 literally and writes the merged gate as `if fp_value or fp3_value:`
(dropping `or svid`), the result is a genuine regression: an event batch that carries a durable
`_rta_svid` server-cookie value (`svid` truthy) but **no** fingerprint signal at all (neither fp2
nor fp3 — a real, non-hypothetical scenario, since svid resolution and fingerprint resolution are
independent client-side mechanisms) would silently stop creating/upserting the `Visitor` stub row.
That is precisely the race main's own upsert-stub fix exists to close — for `svid`-only batches,
the fix would be silently undone by the merge, reverting to the pre-fix behavior where a bare
`UPDATE ... WHERE ... IS NULL` matches 0 rows against a not-yet-created `Visitor` and the `svid`
stamp is silently dropped for that visitor. This is a genuine correctness defect in the letter of
the resolution spec, though the intent (steps 1-4, and the general design of porting fp3 logic into
main's upsert shape) is correct and does not need to change.

**This is not a redesign — it is a one-line correction to step 5's literal condition.** Recorded as
an Execute-Agent Instruction (E-8) below; does not require returning to PLAN.

**Finding 9 (CONCERN, new this cycle) — `dashboard.py` and `visitors_helpers.py` (§3.5/§3.6) will
NOT surface as git rebase conflicts, unlike the other 8 files in the conflict set — an execute-agent
relying on git's own conflict-stop behavior to know when manual vocabulary-rewrite work is required
could silently skip these two files.**

Ran `git merge-tree --write-tree --merge-base=<merge-base> main devjulley` (the same run used to
verify Finding 7/S13 in prior cycles) and inspected its full output rather than only the file names
already named in the plan's conflict list: `apps/api/routers/dashboard.py` and
`apps/api/routers/visitors_helpers.py` both report **"Auto-merging ..."** with **no CONFLICT
line** — git's 3-way merge resolves them cleanly on its own. Extracted the actual merged blob
content for both files from the merge-tree result (`git show <merged-tree>:<path>`) and confirmed
the auto-merge is a **structural union of both sides' edits, not a semantic replacement**: the
merged `dashboard.py` and `visitors_helpers.py` still contain
`from apps.api.services.identity_classification import VERIFIED_STATUSES` and
`Visitor.identity_status.in_(VERIFIED_STATUSES)` call sites, verbatim from main — because
devjulley's own diff to these two files never touched those specific lines (it only added new,
non-overlapping lines elsewhere in the same files), so git's line-level 3-way merge has nothing to
flag as conflicting and simply keeps both sides' non-overlapping edits, including main's now-to-be-
deleted `VERIFIED_STATUSES` usage.

**Consequence if unaddressed:** the Implementation Checklist step 3 already lists `dashboard.py`
(§3.5) and `visitors_helpers.py` (§3.6) explicitly as files requiring the manual "devjulley's
structure wins" rewrite, so an execute-agent that follows the checklist's file list literally is
not at risk. The risk is narrower and more procedural: an execute-agent that performs the rebase
mechanically (e.g. via `git rebase main` and treating "no conflict reported" as "no manual work
needed" for that file) would skip §3.5/§3.6's rewrite, and the resulting file would still import
`VERIFIED_STATUSES` from `identity_classification.py` — which §3.1 deletes. This surfaces loudly
(an `ImportError` at import/collection time, not a silent data-correctness bug — the App boot smoke
gate and every single pytest invocation would catch it immediately), so this is lower severity than
Finding 8, but it is a real gap in how the plan disambiguates "git conflict" from "checklist-named
manual resolution," and it is worth an explicit Execute-Agent Instruction so no execute-agent
wastes a cycle being confused by a boot-time `ImportError` that this VALIDATE pass could have
warned about directly.

**Recorded as Execute-Agent Instruction (E-9) below; does not require returning to PLAN.**

**Minor observation (not a CONCERN, informational only) — migration-boot-failure rollback is not
separately documented beyond the git-level rebase-abort procedure in §8.** The plan's §8 covers
rollback for an *aborted rebase* (git-level) but does not separately state a procedure for "the
push succeeded, Railway auto-deployed, and the app fails to boot against the re-chained migration
head in production." This matches the existing house pattern for every other migration in this
program family (`all-context.md`'s AI-Agent-Traffic Layer / Owned Identity Data Layer / Ingest
Abuse Hardening sections document the same gap class without a bespoke prod-rollback runbook per
migration) and the push itself is already hard-stopped behind explicit human sign-off (goal block
hard stop: "Any push to `main` is a production DDL + deploy event... Never push to `main` without
explicit human sign-off"), meaning a human is present at the moment of the actual deploy risk and
can react in real time. Not escalated to a CONCERN; noted for completeness per the task's migration
safety dimension.

### Findings Carried Forward as RESOLVED (cycle 2's Findings 4/5/6 and cycle 4's Finding 7 —
independently re-verified again this cycle; kept for the audit trail, not re-litigated)

- **Finding 4 (was FAIL, cycle 2)** — in-helper 4th-parameter signature not implementable.
  **RESOLVED**, re-confirmed this cycle: `is_emailable_identity()` untouched.
- **Finding 5 (was FAIL, cycle 2, most severe)** — in-helper design broke devjulley's own guardrail
  tests. **RESOLVED**, re-confirmed this cycle: devjulley's test suite unmodified by design.
- **Finding 6 (was CONCERN, cycle 2)** — "zero production behavior change" wording inaccurate.
  **RESOLVED**, re-confirmed this cycle: §9 and the goal block name the confirm-path exception.
- **Finding 7 (was FAIL, cycle 4)** — `devjulley`'s real tip (`ae7ffb9`) unaccounted for. **RESOLVED**
  by PLAN supplement cycle 5 (S12-S15) and independently re-verified this cycle: zero drift found,
  `ae7ffb9` fully absorbed into Checklist/Touchpoints/§3.2, plus the two conflict files it actually
  introduced (§3.10 tracker.js, §3.11 events.py) both correctly specified (with Finding 8's precise
  correction to one line of §3.11).

### PVL Cycle 8 additions to "Findings Carried Forward as RESOLVED"

- **Finding 8 (was CONCERN, cycle 6)** — §3.11 step 5's literal gating condition dropped `or svid`.
  **RESOLVED** by PLAN supplement cycle 7 (S16); re-confirmed this cycle: plan body now reads
  `if fp_value or fp3_value or svid:` verbatim, no stale wording survives elsewhere in the file.
- **Finding 9 (was CONCERN, cycle 6)** — `dashboard.py`/`visitors_helpers.py` auto-merge cleanly
  but silently retain main's retired vocabulary. **Not a plan-text defect** (E-9 already correctly
  diagnosed and worded this at cycle 6) — this cycle independently reconstructed the actual git
  auto-merge output tree and confirmed E-9's claim is byte-for-byte accurate. Status: E-9 stands
  as-is, re-confirmed sufficient, no further plan change needed.
- **Finding 10 (was CONCERN, cycle 6)** — §5 conflated the Alembic revision id `a7d419e6c052` with
  the git merge-base. **RESOLVED** by PLAN supplement cycle 7 (S17); re-confirmed this cycle via
  `git cat-file -t a7d419e6c052` (fails — not a git object) and `git merge-base main devjulley`
  (`db180c44...`, the correct value).
- **Finding 11 (was an out-of-scope observation, cycle 6)** — `process/context/all-context.md`
  records a stale Alembic head. Confirmed still true and still correctly out-of-scope for this
  plan (belongs to UPDATE PROCESS); this plan's own `<PROD_HEAD>` derivation design remains immune.

### Layer 1 dimensions (cycle 6 snapshot — kept as audit trail; see "PVL Cycle 8 additions" above for Findings 8/9's resolution and the cycle 8 totals immediately below this table for the CURRENT authoritative verdict)

| Layer 1 dimensions | Status |
|---|---|
| Infra fit | PASS — no new runtime surface; both branches' local migration chains independently re-confirmed single-headed via the real `alembic` CLI (`devjulley` → `f1a7c3e05b92`, `main` → `c2f7a9d31b64`); the plan's derivation-based `<PROD_HEAD>` design is confirmed necessary (main's local head has moved well past the `e6b2d4a1c837` figure still recorded in `all-context.md`, proving a hardcoded target would already be wrong) |
| Test coverage | CONCERN — test plan itself is sound and complete (fp3 gates present, wrapper test file planned), but two of the resolution specs it verifies against (§3.11, §3.5/§3.6) needed a precision correction this cycle (Findings 8/9) before the tests they gate would prove the intended behavior rather than a regression |
| Breaking changes | PASS — `is_emailable_identity()`'s public contract confirmed byte-identical; no other public-contract change introduced |
| Security surface | PASS — emailability blast radius re-verified this cycle: cannot implicitly widen the send audience; both exclusions confirmed genuinely owner-only sends; confirm-path exception remains the only, already-disclosed, deliberate exception |

### Layer 2 sections

| Layer 2 sections | Status |
|---|---|
| §3.1 identity_classification.py (vocabulary, D10 wrapper) | PASS — re-verified sound, signature/body byte-identical |
| §3.2 identity_resolver.py (fp3 extension) | PASS — re-verified this cycle: `ae7ffb9`'s 43+/14- diff confirmed disjoint from the vocabulary write logic at lines 899/951 (read the actual diff hunks; they land at lines ~368-430 and ~982-1090, nowhere near the vocabulary write sites) |
| §3.3/§3.4 kpi.py / timeseries.py | PASS — confirmed genuine git conflicts (present in `git merge-tree` CONFLICT list), unchanged, no new issue |
| §3.5 dashboard.py | **CONCERN (new this cycle, Finding 9)** — resolution content itself correct, but this file will NOT surface as a git conflict during rebase (clean auto-merge, verified via `git merge-tree`); needs an explicit Execute-Agent Instruction so the manual rewrite isn't skipped |
| §3.6 visitors_helpers.py | **CONCERN (new this cycle, Finding 9)** — same issue as §3.5, same file class |
| §3.7 test file rewrites | PASS — devjulley's pre-existing `is_emailable_identity` assertions confirmed to need zero modification |
| §3.8 status-badge.tsx | PASS — confirmed genuine git conflict, unchanged |
| §3.9 test_events_ingest.py | PASS — confirmed genuine git conflict, unchanged, both test classes additive |
| §3.10 tracker.js | PASS — re-confirmed clean auto-merge via direct `git merge-tree` run this cycle (not re-trusted from prior cycle's report) |
| §3.11 events.py | **CONCERN (new this cycle, Finding 8)** — genuine conflict confirmed, overall resolution direction (port fp3 into main's upsert shape) confirmed correct, but step 5's literal gating condition is factually wrong and would regress svid-only event handling if followed as written |
| §4 call-site sweep | PASS — independently re-derived, exact match, no drift |
| §5 migration re-chain | PASS (upgraded from cycle 4's CONCERN) — re-chain mechanism confirmed correct via the real `alembic` CLI this cycle; the stale-head problem that drove cycle 4's CONCERN is resolved by S12's derivation-based design, independently re-verified sufficient this cycle |
| §6 feature flag design (D5/D10 OFF-state) | PASS — wrapper design re-verified sound |
| Implementation Checklist / Touchpoints / Blast Radius | PASS (upgraded from cycle 4's FAIL) — re-derived live state matches exactly what is recorded; zero drift found this cycle |
| §10 open items | 6 of 7 prior items RESOLVED and re-confirmed stable; item 7 (structural "not frozen" caveat) remains a standing, non-closeable design feature, not a defect |

**Cycle 6 historical totals (superseded): 0 FAILs / 3 CONCERNs (Test coverage,
§3.5/§3.6 dashboard.py+visitors_helpers.py, §3.11 events.py) / 11 PASSes**

**PVL Cycle 8 current totals: 0 FAILs / 1 CONCERN (Finding 12 — non-existent test name cited 4×)
/ 1 OBSERVATION not counted (Finding 13 — branch ref instability, environmental, no plan-text
change required) / 14 PASSes (11 carried forward + §3.11 events.py, §3.5/§3.6 dashboard.py+
visitors_helpers.py, and §5 migration re-chain upgraded from CONCERN to PASS via cycle 7's fixes,
independently re-confirmed this cycle).**

**→ Net Gate: CONDITIONAL**

### Why this is CONDITIONAL, not BLOCKED

None of this cycle's 3 findings reopen a Locked Decision (D1-D10 all stand, all independently
re-verified this cycle), none of them expand scope or discover an un-scoped file (unlike cycle 4's
Finding 7), and none of them require a redesign. Both new findings (8 and 9) are precisely
diagnosed, narrowly scoped, single-point corrections that can be delivered as concrete Execute-Agent
Instructions embedded directly in this contract — an execute-agent that reads and follows E-8 and
E-9 below will not reproduce either defect. This is the documentable-gap category the gate
definitions reserve for CONDITIONAL, in contrast to cycle 4's Finding 7 (which changed the
definition of "done" for AC1 and introduced a wholly unscoped conflict file) or cycle 2's Findings
4/5 (which contradicted a Locked Decision). Per the task's explicit steer: reserve BLOCKED for real
plan defects that cannot be safely routed around by an execute-agent instruction — Findings 8 and 9
do not meet that bar; they are exactly the kind of defect an execute-agent instruction exists to
close.

### Execute-Agent Instructions (embedded fixes — read before or during Implementation Checklist
step 12/§3.11 and step 3/§3.5-§3.6 respectively)

| # | Instruction | Trigger condition |
|---|---|---|
| E-8 | When implementing §3.11's combined `events.py` resolution, gate the merged fingerprint/svid block on **`if fp_value or fp3_value or svid:`** — NOT `if fp_value or fp3_value:` as §3.11 step 5 literally states. Main's actual condition (confirmed via `git show main:apps/api/routers/events.py`) is `if fp_value or svid:`; the merged design must preserve the `or svid` clause so that an event batch carrying only the durable `_rta_svid` server-cookie value (no fp2/fp3 present) still creates/upserts the `Visitor` stub row via the `pg_insert(...).on_conflict_do_update(...)` path — this is the exact race main's redesign exists to fix, for `svid` as much as for `fingerprint`. | Implementation Checklist step 12, §3.11 conflict resolution |
| E-9 | `apps/api/routers/dashboard.py` (§3.5) and `apps/api/routers/visitors_helpers.py` (§3.6) will NOT stop a `git rebase` with a conflict marker — both auto-merge cleanly, and the clean auto-merge result still imports and uses `VERIFIED_STATUSES` from `identity_classification.py` (verbatim from `main`), which §3.1 deletes. Do not treat "git reported no conflict" as "no manual work needed" for these two files — apply §3.5/§3.6's "devjulley's structure wins" rewrite explicitly, as Implementation Checklist step 3 already lists them, regardless of what git's rebase machinery reports. If this step is accidentally skipped, the failure surfaces immediately and loudly as an `ImportError` at the App boot smoke gate or the first pytest collection — if that specific error appears, this is the cause. | Implementation Checklist step 3, §3.5/§3.6 conflict resolution |
| E-11 | **§3.1 `apps/api/services/identity_classification.py` carries the SAME auto-merge trap E-9 warns about for `dashboard.py`/`visitors_helpers.py`, and until PLAN supplement cycle 9 (S22) carried no warning — despite §3.1 being the highest-priority file in this plan.** The file's real conflict markers span ONLY the `identity_status_for_provider` vs `is_graph_candidate_provider`/`is_verified_identity` swap. `EMAILABLE_PROVIDERS`, the `STATUS_VERIFIED`/`STATUS_PROVIDER_CANDIDATE`/`STATUS_IDENTIFIED_LEGACY`/`VERIFIED_STATUSES` family, and **`is_emailable_identity()`'s own body** all sit **outside any conflict marker** and will **auto-merge silently to `main`'s content** (the merge base already had `identity_level(...) == "person"`; `main` changed it and `devjulley` did not, so a 3-way merge keeps `main`'s side). Do NOT treat "git reported no conflict for these symbols" as "§3.1 is done" — apply §3.1's deletions and devjulley-body retention **explicitly**, exactly as §3.1's prose specifies. §3.1's prose is symbol-correct and produces the right file if followed literally; the hazard is skipping it because git stayed quiet. **Partial mitigation (do not rely on it alone):** devjulley's own `test_abuse_flag_default_false_preserves_existing_behavior` asserts `is_emailable_identity("rb2b") is True`, which fails loudly if `main`'s body is kept. | Implementation Checklist step 3, §3.1 conflict resolution |
| E-10 | Wherever the plan text (§3.1, §3.7, §6) or this contract cites `test_candidates_are_emailable_not_blocked_by_tier` as a pre-existing regression test, treat it as a plan-text typo for **`test_candidates_remain_emailable`** (the real test, in `tests/unit/test_identity_classification.py`, docstring: "test exists to catch a future change that 'helpfully' folds the candidate tier into `is_emailable_identity`"). Do NOT create a new test under the cited-but-nonexistent name, and do NOT rename the real test to match the plan's wrong citation — the existing Fully-Automated gate (`pytest tests/unit/test_identity_classification.py -v`) already runs and already proves this test unmodified; only the plan's prose citation is wrong. A distinct, similarly-named test, `test_graph_candidates_are_emailable_not_blocked_by_tier`, exists in a DIFFERENT file (`tests/unit/test_outbound_identity_gate.py`) — do not conflate the two. | §3.1/§3.7 citation review, before or during Implementation Checklist step 4's spot-check |

### Test gates (C3 5-column table)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1-D1 | identity vocabulary rewritten to identified/candidate everywhere | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_identity_classification.py -v` | B — design independently re-verified sound this cycle |
| AC3/D2 | Candidate-tier identities emailable per D2 wide rule; D5/D10 wrapper-gated OFF/ON split | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_identity_classification.py tests/unit/test_outbound_identity_gate.py tests/unit/test_agent_origin_exclusion.py tests/unit/test_handoff_emailability_separation.py -v` | B — must pass with ZERO test modifications once §3.1 lands |
| NEW — wrapper behavior | confirm-gate wrapper at 3 in-scope call sites blocks/allows correctly OFF/ON | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_candidate_outreach_gate.py -v` (new file, confirmed does not exist yet) | B — fixed by this plan's checklist |
| Finding 8 — events.py svid gating | merged fingerprint/svid write block persists svid even when no fp2/fp3 is present in the batch | Fully-Automated (new assertion recommended) | Add (or extend an existing) case to `tests/integration/test_events_ingest.py` or `tests/unit/` asserting `Visitor.server_visitor_id` is written for an svid-only batch (no `fp`/`fp3` fields) after §3.11 lands, per E-8's corrected gate | B — execute-agent should add this assertion while implementing E-8; not currently a named test in §7 |
| Finding 9 — dashboard.py/visitors_helpers.py vocabulary sweep | both files import zero `VERIFIED_STATUSES` post-rebase, confirming E-9 was followed | Fully-Automated | `grep -rn "VERIFIED_STATUSES" apps/api/routers/dashboard.py apps/api/routers/visitors_helpers.py` must return no matches (or equivalently: `python -c "import apps.api.main"` / full pytest collection succeeds with zero `ImportError`) | B — App boot smoke gate already listed in §7 catches this if E-9 is missed; no new gate command needed, just confirm it is exercised |
| D3 | devjulley features (confirm/reject, promotion sweep, contact import, hot contacts) survive | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/ -k "identity or visitor or campaign or kpi or timeseries or contact or promotion or candidate" -v` | B |
| D4 | main features (Leadpipe webhook, deferral watermark, RB2B rework) survive | Hybrid — precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis` | `.venv/bin/python3.11 -m pytest tests/unit/test_leadpipe_webhook.py tests/integration/test_leadpipe_webhook_persistence.py -v` | B if Docker available in EXECUTE env, else D |
| §3.9 merge | both TestCookieFpPhase2 and TestUnknownSiteObservability classes present and pass | Hybrid — same precondition | `.venv/bin/python3.11 -m pytest tests/integration/test_events_ingest.py -v` | B if Docker available, else D |
| §5 AC2 | exactly one alembic head after corrected re-chain, including `ae7ffb9`'s migration | Fully-Automated | `alembic -c apps/api/alembic.ini heads` (must print exactly 1 line) | A — mechanism re-verified this cycle via the real CLI against both branches; must still be re-confirmed live at EXECUTE time (branch not frozen) |
| §5 | migration chain applies cleanly offline | Fully-Automated | `alembic -c apps/api/alembic.ini upgrade <PROD_HEAD>:head --sql` | B |
| §5 | migration live round-trip on disposable Postgres | Hybrid — precondition: disposable Postgres container | `alembic upgrade head` → `alembic downgrade -1` → `alembic upgrade head` | D — Docker confirmed UNAVAILABLE again this cycle (5th consecutive check across all VALIDATE cycles to date, `docker` command not found in this environment); matches program precedent, known-gap |
| App boot | migration re-chain does not crash app boot; also the E-9 regression detector | Fully-Automated | `python -c "import apps.api.main"` (or local uvicorn boot) | B |
| Full regression | no cross-branch regression across identity/campaign surface | Hybrid — precondition: docker compose postgres+redis | `.venv/bin/python3.11 -m pytest tests/integration/ -v` | B if Docker available, else D |
| §3.8 | status badge renders candidate/vpn_filtered/merged tones correctly | Agent-Probe | Manually render `StatusBadge` with each of `identity_status ∈ {candidate, vpn_filtered, merged}`, confirm tone matches §3.8 | B |
| §3.10/§3.11 fp3 | fp3 hashing + `<6144`/`<6000` byte pixel-size gate stays green post-rebuild | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_pixel_fingerprint.py tests/unit/test_pixel.py -v` | A — gate value confirmed current (6KB, not stale 5KB) this cycle |
| §3.10 e2e | fontFp/audioFp probes resolve correctly post-rebuild across browsers | Hybrid — precondition: `cd apps/pixel && npm run build` then Playwright browsers installed | `cd apps/pixel && npx playwright test e2e/fingerprint-v3.spec.ts` | B — spec file confirmed present on `devjulley` this cycle |
| Pixel size gate | rebuilt `tracker.min.js` stays under the 6KB gate | Fully-Automated | `cd apps/pixel && npm run build && npm run size` (must print `< 6144`) | B |

gap-resolution legend: A — proven now. B — fixed in this plan (checklist adds the gate, to be
proven once EXECUTE runs it — nothing in this VALIDATE session executes code). C — deferred to a
named later phase/plan. D — backlog test-building stub (named residual; keep-active; continue).

C-4 reconciliation: the `strategy:` column above carries only Fully-Automated / Hybrid / Agent-Probe.
No row uses Known-Gap as a strategy — rows without current proof use gap-resolution B or D.

Legacy line form (retained for existing consumers):
- identity vocabulary + emailability (wrapper design): Fully-automated:
  `.venv/bin/python3.11 -m pytest tests/unit/test_identity_classification.py tests/unit/test_outbound_identity_gate.py tests/unit/test_agent_origin_exclusion.py tests/unit/test_handoff_emailability_separation.py tests/unit/test_candidate_outreach_gate.py -v`
- D3/D4 feature survival: Fully-automated (unit) + hybrid (integration, precondition `docker compose -f infra/docker-compose.yml up -d postgres redis`): see full commands in §7 of the plan
- migration chain integrity: Fully-automated: `alembic -c apps/api/alembic.ini heads` (exactly 1 line) + `alembic -c apps/api/alembic.ini upgrade <PROD_HEAD>:head --sql`
- migration live round-trip: known-gap: documented — Docker unavailable in this validate session (5 consecutive cycles), matches program precedent
- status badge tone map: agent-probe: manual render check across candidate/vpn_filtered/merged
- events.py svid gating fix (Finding 8) / dashboard.py+visitors_helpers.py vocabulary-sweep reminder (Finding 9): execute-agent instructions E-8/E-9 above, no plan supplement needed

### What this coverage does NOT prove

- **Live prod migration state.** No test above confirms what `alembic_version` actually is in the
  deployed Railway Postgres right now, or current `visitors.identity_status` row counts. The
  plan's §5 step 0 live pre-check (`railway run ...`) is a mandatory human-in-the-loop gate this
  VALIDATE session could not and did not run (blocked for the agent, per this session's explicit
  tool restriction and per the task's own established facts) — EXECUTE must not skip it.
- **`devjulley`'s tip at EXECUTE time.** This cycle found zero drift since PLAN supplement cycle 5,
  but nothing prevents the branch moving again before EXECUTE actually runs — the mandatory
  step-0 pre-flight (S15) is the standing mitigation, not a one-time proof.
- **Live SendGrid/production email send behavior** for a real Candidate-tier recipient — unit/
  integration tests prove composition logic, not a live inbox render.
- **The migration live round-trip** on a real (disposable) Postgres — Docker unavailable in this
  and all prior VALIDATE sessions for this plan.
- **Finding 8's new svid-only-batch behavior** — no test currently exists for this scenario (E-8's
  recommended new assertion is not yet written; this VALIDATE session is static analysis, not a
  test run).
- **Whether the D10 wrapper design and the §3.11 combined write logic, though verified sound on
  paper this cycle, actually produce a passing test suite** — no code has been written or executed
  yet; this VALIDATE session re-ran `git`/`alembic`/`grep`/`merge-tree` against real branch state,
  it did not execute application code.
- **Full regression breadth beyond the identity/campaign/KPI/timeseries/contact/promotion/candidate
  filter** used in the D3 gate above — Hybrid tier, gap-resolution D if Docker is unavailable.

### Open gaps

- **Test-coverage known-gap (S20, PLAN supplement cycle 9):** the `identity_resolver.py`
  `is_privacy_relay_ip` call site has no covering test — see `## Test Infra Improvement Notes` above
  for the full statement and the backlog pointer. Classified **Known-Gap / backlog**, not a blocker
  for this already-executed reconciliation (the guard is verified present on `devjulley`, 2 hits).
- ~~Finding 8 (CONCERN, cycle 6) — §3.11 step 5's literal gating condition was wrong.~~
  **RESOLVED by PLAN supplement cycle 7 (S16), independently re-confirmed cycle 8.** E-8 remains
  in place as belt-and-braces.
- ~~Finding 9 (CONCERN, cycle 6) — `dashboard.py`/`visitors_helpers.py` will not surface as git
  conflicts.~~ **Not a plan-text defect; E-9's diagnosis independently proven byte-for-byte
  accurate at cycle 8** via literal reconstruction of git's auto-merge output tree. E-9 remains
  the operative instruction.
- **Finding 12 (CONCERN, NEW cycle 8) — plan cites a non-existent test function name
  (`test_candidates_are_emailable_not_blocked_by_tier`) in 4 places; corrected via Execute-Agent
  Instruction E-10 above.** No plan supplement strictly required (the underlying automated gate
  already passes under the test's real name, `test_candidates_remain_emailable`) — E-10 prevents
  an execute-agent or reviewer from being misled by the wrong citation. Low severity, but genuine.
- **Finding 13 (OBSERVATION, NEW cycle 8, not counted toward CONDITIONAL) — `devjulley` branch ref
  moved again mid-session** (`ae7ffb9` → `3528c00...`, confirmed via `git reflog show devjulley`:
  `Reset to HEAD`, traced to the already-flagged unauthorized in-progress rebase). No plan-text
  change required — S12's derivation-based design and the Next Instruction section's mandatory
  step-0 pre-flight (below) already exist specifically to catch this. Recorded because it is
  fresh, this-session evidence that EXECUTE cannot begin while the rebase is unresolved, and
  because it forced a mid-cycle methodology correction (see the PVL Cycle 8 findings section
  above) — a caution for any future agent working in this repo while a rebase might be live: pin
  explicit commit hashes, never trust `main`/`devjulley` as stable ref names until confirmed
  otherwise.
- Migration live round-trip on disposable Postgres — known-gap: documented (Docker unavailable at
  all 5 VALIDATE cycles to date for this plan), matches program precedent (owned-data-layer,
  ingest-abuse-hardening, cadence-bot-flag all share this acknowledged gap class in
  `process/context/all-context.md`).
- Live prod pre-check (`railway run` count query + alembic head) — human-in-the-loop gate, not
  agent-executable; must be run by the user immediately before EXECUTE begins, per plan §5 step 0
  and per this session's explicit tool/task restriction (`railway` commands are blocked for agents).
- Two-layer VALIDATE fan-out (4 Layer-1 + N Layer-2 parallel agents) has still not run in any of
  the 5 VALIDATE cycles for this plan — no Agent/Task tool has been available in any of them,
  stated plainly per the task's explicit instruction not to silently substitute. All findings in
  this contract come from a single sequential deep-verification pass, this cycle deliberately
  budgeted toward re-executing ground-truth commands rather than re-reading prose. If a future
  session has fan-out available, a true parallel pass (particularly independent eyes on §3.11's
  now-corrected resolution and a UI/copy read of §3.8's status-badge tones) would raise confidence
  further, though it is not expected to reverse any PASS verdict given how thoroughly this cycle's
  claims were re-derived from live tool output rather than from the plan's own prose.
- Migration-boot-failure rollback runbook — not separately documented beyond git-level rebase
  abort; noted as an informational observation (not a CONCERN) since it matches existing house
  practice across this program family and the push itself is already human-sign-off-gated.
- **`process/context/all-context.md` records a stale Alembic head (observation, PLAN supplement
  cycle 7, S18 — OUT OF SCOPE for this plan, do NOT fix here).** The context router states the
  current head is `e6b2d4a1c837`; live `main`'s head is **`c2f7a9d31b64`** — 9 migrations of drift.
  This is a real defect, but it belongs to **UPDATE PROCESS** (context maintenance), not to this
  reconciliation plan. Recorded here only so it is not lost. Pointer:
  `process/context/all-context.md` (AI-Agent-Traffic Layer section + "Open Questions / Outstanding
  Work" section both carry the stale `e6b2d4a1c837` figure). Re-derive with
  `alembic -c apps/api/alembic.ini heads`. This plan's own design is already immune to the drift —
  it uses a derivation-based `<PROD_HEAD>` placeholder (S12) and explicitly forbids
  literal-substituting `e6b2d4a1c837`.

Accepted by: **USER — accepted this session (PLAN supplement cycle 9, 07-08-26).** The acceptance
was made on the basis of the orchestrator's reported spot-verification of the executed result — not
a personal review of the diff or code by the user; the user's verbatim instruction was *"giữ kết
quả, sửa §3.2, xác nhận nốt MissingGreenlet"* ("keep the result, fix §3.2, confirm the
MissingGreenlet item"). This acceptance of the CONDITIONAL gate is therefore **retroactive to an
already-completed EXECUTE** (see the EXECUTED AND ACCEPTED status
block at the top of this plan for the full governance record). PVL cycle 8 had lowered the open
CONCERN count from 2 (cycle 6: Findings 8, 9) to 1 (cycle 8: Finding 12), with Findings 8/9 RESOLVED
and Finding 13 recorded as a non-counted environmental observation.

> ~~SUPERSEDED (PLAN supplement cycle 9, S23) — this line previously read *"Accepted by: **PENDING**
> — CONDITIONAL gaps not yet accepted by the user … Still requires explicit user acceptance (or a
> further supplement cycle) before EXECUTE."*~~ Struck: the user has now explicitly accepted. The
> cycle-7 (S19) correction that an **agent cannot accept its own CONDITIONAL verdict** stands
> unchanged — this acceptance is the user's, not an agent's.

> ~~SUPERSEDED (PLAN supplement cycle 7, S19) — this line previously read
> *"Accepted by: session (validate-agent, PVL cycle 6)"*.~~ Struck: **an agent cannot accept its own
> CONDITIONAL verdict.** Acceptance of CONDITIONAL gaps is the user's call. The findings themselves
> are untouched and stand — Findings 8 and 9, and Execute-Agent Instructions E-8 and E-9, are sound
> and were independently corroborated by two external adversarial verifiers.

Proposed acceptance rationale (for the user to accept or reject, not self-granted): the sole
remaining CONCERN (Finding 12) is addressable via the embedded Execute-Agent Instruction E-10
above, precise, scoped, and implementable without reopening any Locked Decision or returning to
PLAN — it is a plan-prose citation fix, not a code-behavior fix. Findings 8 and 9 (cycle 6) are now
RESOLVED, independently re-confirmed this cycle. Finding 13 (branch-ref instability) is an
environmental observation, not counted toward the CONDITIONAL gate, and does not require plan
acceptance — it requires the rebase to be resolved before EXECUTE, which the existing Next
Instruction section below already gates on via the mandatory step-0 pre-flight. Known-gaps
(migration live round-trip, live prod pre-check, fan-out unavailability) match established program
precedent and every prior cycle's treatment of the same environmental constraints.

Gate: CONDITIONAL

## Next Instruction

**EXECUTE is NOT yet unblocked — this is now doubly confirmed.** The gate is CONDITIONAL and its
gaps are **not yet accepted by the user** (see the `Accepted by: PENDING` marker above). EXECUTE
becomes appropriate once the PVL loop returns `Gate: PASS`, **or** once the user explicitly accepts
the CONDITIONAL gap (Finding 12). When it does, it remains subject to the 3 embedded Execute-Agent
Instructions above (E-8, E-9, E-10, E-11) being followed exactly as written during the relevant
Implementation Checklist steps. **Independent of the CONDITIONAL gate itself: PVL cycle 8 directly
observed the `devjulley` branch ref move mid-session** (see Finding 13), traced to the
already-flagged unauthorized in-progress rebase — this is live, this-session proof that step 1
below is not a theoretical precaution, it is currently load-bearing. EXECUTE must not begin while
that rebase remains unresolved, regardless of the CONDITIONAL gate's disposition.

**Before EXECUTE begins, in this exact order:**

1. Confirm the in-progress rebase (detached HEAD, `UU apps/api/services/identity_resolver.py` as
   of PVL cycle 7/8) has been resolved or aborted by the user — EXECUTE must not run against a
   mid-rebase working tree under any circumstances.
2. Run the Implementation Checklist's **mandatory step-0 pre-flight** (`git rev-parse main`,
   `git rev-parse devjulley`, `git log main..devjulley --oneline`,
   `git diff --name-only main...devjulley -- apps/api/migrations/versions/`) as the FIRST action —
   do not reuse this VALIDATE session's confirmed values (`main`=`332b3a8`, `devjulley`=`ae7ffb9`)
   as frozen facts. The branch is explicitly not frozen (U2), and PVL cycle 8 itself directly
   observed it move mid-session (Finding 13) — treat that as confirmation this step is necessary,
   not boilerplate.
4. If the pre-flight output differs from what is recorded in this plan: STOP, do not proceed on a
   stale assumption, return to PLAN for a fresh supplement cycle (same process PLAN supplement
   cycle 5 already ran once for `ae7ffb9`).
5. If the pre-flight output matches: proceed through the Implementation Checklist in the corrected
   order it specifies, applying **Execute-Agent Instruction E-8** at step 12/§3.11 (the merged
   `events.py` gating condition must be `if fp_value or fp3_value or svid:`, not the plan prose's
   literal `if fp_value or fp3_value:`), **Execute-Agent Instruction E-9** at step 3/§3.5-§3.6
   (apply the manual `VERIFIED_STATUSES` → `identity_status ==` rewrite to `dashboard.py` and
   `visitors_helpers.py` explicitly — git will not flag either file as a rebase conflict, so do not
   rely on git's conflict-stop behavior to know this work is needed), and **Execute-Agent
   Instruction E-10** wherever the plan cites `test_candidates_are_emailable_not_blocked_by_tier`
   (treat as a citation typo for the real test `test_candidates_remain_emailable`; do not create a
   duplicate test or rename the real one).
6. The live prod pre-check (`railway run ...`, §5 step 0) is a human-in-the-loop gate that must be
   run by the user, not simulated or skipped, both before EXECUTE begins (baseline) and immediately
   before the final push (§5 step 0, second run / Implementation Checklist step 15).
7. The migration live round-trip on a disposable Postgres remains a documented known-gap if Docker
   is unavailable in the EXECUTE environment (confirmed unavailable in every VALIDATE session to
   date) — do not block on it, matches program precedent.
8. Never `git push --force` on `devjulley` — only `--force-with-lease`. Never delete or move
   `backup/main-06-08-26` or `backup/devjulley-pre-rebase-06-08-26`. Any push to `main` requires
   explicit human sign-off (production DDL + deploy event via Railway's auto-apply-on-boot).

Testing context: see §7 Verification Evidence (as extended by this contract's Test gates table)
for exact commands, the `.venv/bin/python3.11 -m pytest` runner note (broken shebang, use the
explicit interpreter invocation), and `TESTING.md` / `process/context/tests/all-tests.md` for the
docker-compose precondition on the integration lane. Docker remains unavailable as of this session
(5th consecutive confirmation across all VALIDATE cycles) — the migration live round-trip stays a
documented known-gap, not a blocker.

## Validate Addendum (PVL cycle 6, second independent pass)

One additional precision detail on Finding 9, confirmed via `git log --oneline main..devjulley --
apps/api/routers/dashboard.py` / `-- apps/api/routers/visitors_helpers.py` and `git show fe89466 --
apps/api/routers/dashboard.py`: `dashboard.py`'s devjulley-side change (the `candidates` count field)
is introduced by commit `fe89466`, not `626d643` — even though Implementation Checklist step 3 and
§3.5 both attach it to the `626d643` rebase step. `626d643` does not touch `dashboard.py` at all.
`visitors_helpers.py` is touched by both commits, but its `VERIFIED_STATUSES`-affected lines
(`_build_visitor_filters`, ~L108-113) are touched by neither devjulley commit — that hunk is main-only
relative to the fork, confirming Finding 9's "no devjulley commit ever conflicts on these lines"
conclusion precisely, not just approximately.

This does not change the CONDITIONAL classification or invalidate E-9 (which already instructs
following the checklist's explicit per-file list regardless of git conflict status) — it sharpens the
evidence for *why* git conflict detection cannot be relied on for these two files, and confirms the
correct rebase step for `dashboard.py`'s content is step 10 (`fe89466`), not step 3, in case a future
plan supplement wants to correct the Implementation Checklist's step-to-file mapping for precision.
Not escalated to a new finding — E-9 already covers the actionable instruction regardless of which
step the file is nominally attached to.
