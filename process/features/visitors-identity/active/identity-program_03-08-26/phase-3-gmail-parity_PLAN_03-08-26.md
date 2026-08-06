---
name: plan:identity-program-phase-3-gmail-parity
description: "Identity honesty program — Phase 3: shared compose step gives Gmail-Connect sends the same link decoration and attribution as SendGrid"
date: 03-08-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: phase-3
---

# Phase 3 — Gmail Decoration Parity

**Program:** identity-program
**Umbrella plan:** process/features/visitors-identity/active/identity-program_03-08-26/identity-program-umbrella_PLAN_03-08-26.md
**Phase status:** 🟢 EXECUTE complete (gates green)
**Report destination:** process/features/visitors-identity/active/identity-program_03-08-26/phase-3-gmail-parity_REPORT_03-08-26.md

---

## VALIDATE Correction Notice (03-08-26)

vc-validate-agent read `apps/api/services/campaign_sender.py` directly and found the plan's
original premise (and the locked SPEC's research claim at SPEC lines 421-423) is **factually
incorrect against the current codebase**:

- `decorate_links(body_html, iv.email, site_host, touchpoint_id=str(tp_row.id))` runs at
  `campaign_sender.py:284` — **unconditionally, BEFORE** the channel fork
  (`if gmail_sender is not None:` at line 294). The resulting decorated `body_html` is what flows
  into BOTH `send_via_gmail(... body_html=body_html + unsub_footer ...)` (line 302) AND the
  SendGrid branch (`sender.send(... body_html=body_html ...)`, line 319). **Link decoration
  parity already exists today** — it is not a gap.
- The open-tracking pixel appended at lines 286-289 is likewise appended before the fork and
  already reaches both channels.
- The ONE genuine, verified gap is narrower: `custom_args={"site_id": ..., "visitor_id": vid}`
  (line 324) is passed only to `EmailSender.send()` (SendGrid). `send_via_gmail()`
  (`gmail_sender.py:83`) has no `custom_args`-equivalent parameter, and the underlying
  `gmail.send_message()` (`gmail.py:169`) has no such parameter either. This is real —
  SendGrid's `custom_args` exists specifically so its `open`/`click` webhook can echo it back
  into `IdentitySignal` (owned-data-layer, `identity_signals_enabled`); Beam has no equivalent
  Gmail-side webhook to consume any header/metadata even if one were added.

**Scope correction applied to this plan below:** Step B (shared compose step) is corrected from
"move decoration to run unconditionally" (already true, no code change needed) to "confirm +
regression-test the existing shared decoration path, then resolve only the `custom_args`
attribution-echo question per Step A." This narrows Phase 3's likely code footprint
substantially — the phase may end up being test-only plus a documented known-gap, which is a
valid and complete outcome for AC12's link-decoration half.

**Not in this plan's write scope:** the locked SPEC's research claim (lines 421-423) should be
corrected in a future SPEC amendment or the program's Open Gaps ledger — flagged here, not fixed
here (SPEC is a separate artifact this plan may not modify).

---

## Purpose

Close the ONE confirmed gap after correction: `gmail_sender.py::send_via_gmail()` and the
underlying `gmail.send_message()` have no mechanism equivalent to SendGrid's `custom_args`, so a
Gmail-Connect send today cannot be attributed by the SendGrid-webhook-based `IdentitySignal`
corroboration path the way a SendGrid send can. Link decoration (the `_bid` click→identity
mechanism, which is the channel-agnostic, deterministic identification path AC12 actually depends
on for Phase H's promotion sweep) is **already shared** between both channels via the existing
compose step in `campaign_sender.py` that runs once before the channel fork — confirmed by
direct code read at VALIDATE (see Correction Notice above). This phase's job is: (1) prove that
existing decoration parity with a regression test (it has none today), and (2) determine —
without building new webhook infrastructure (out of program scope) — whether any Gmail-side
attribution-echo equivalent is feasible, documenting a known-gap if not. This closes AC12 fully
for the part Phase H's promotion sweep actually needs (deterministic `_bid` click identification,
channel-agnostic) regardless of the attribution-echo answer.

---

## Entry Gate

- Program start — no phase dependency (parallel-safe with Phases 1 and 2).

---

## Blast Radius

- `apps/api/services/campaign_sender.py` — **Phase 3's owned region only**: lines ~282-325 (the
  shared compose step already producing one decorated `body_html` before the channel fork, plus
  the `custom_args` construction currently reached only by the SendGrid branch). No structural
  move is required for decoration (it is already unconditional/shared — see Correction Notice);
  the only potential edit here is passing an attribution-equivalent value into the Gmail branch
  IF Step A finds one exists. Does NOT touch Phase 2's owned personalization-guard region (~line
  248/250) or Phase 5's promotion-sweep logic.
- `apps/api/services/email_providers/gmail_sender.py::send_via_gmail()` — currently accepts
  `db, sender, *, to_email, subject, body_html, unsubscribe_url` (no `custom_args`-equivalent
  param). If Step A finds a feasible mechanism (e.g. a custom MIME header via
  `gmail.py::_build_raw_message()`/`send_message()`), this signature gains an optional param;
  otherwise unchanged.
- `apps/api/services/email_providers/gmail.py::send_message()` / `_build_raw_message()` — only
  touched if Step A finds a header-based mechanism worth adding; otherwise unchanged. No existing
  Gmail-side webhook exists to read such a header back, so any header addition without a
  corresponding webhook is a documentation/future-proofing step, not a working attribution
  channel — do not build a new Gmail webhook (out of program scope, see Global Constraints).
- `tests/unit/` — new test(s) asserting the Gmail-Connect branch receives the same decorated
  `body_html` (same `_bid` token structure) the SendGrid branch would receive for the same send,
  and a regression test that the SendGrid `custom_args` construction is unaffected. Match the
  exit-gate `-k` filters below when naming test functions/files.
- `tests/integration/` (if Hybrid tier is used for the click-round-trip leg) — new test simulating
  a Gmail-Connect send's decorated link being clicked and resolving identically to a SendGrid
  send's link.

**Does NOT touch:** Phase 1's candidate-tier logic, Phase 2's personalization guard, any
import/promotion surface (Phases 4/5/6), `is_emailable_identity()` (3-param contract unchanged).

---

## Implementation Checklist

### Step A — Research the Gmail API attribution ceiling

- [x] A1. Confirm via research whether Gmail API / `gmail.py::send_message()` has ANY mechanism
  (custom header preserved end-to-end, or nothing at all) that could carry `site_id`/`visitor_id`
  metadata analogous to SendGrid's `custom_args`. Explicitly note: even if a header CAN be added,
  Beam has no Gmail-side open/click webhook today to read it back — so a header alone does not
  reproduce SendGrid's `IdentitySignal` corroboration mechanism; building that webhook is out of
  this phase's and this program's scope (see umbrella Global Constraints — no new
  dependencies/runtime surfaces). Document the finding plainly.
- [x] A2. Record the parity ceiling explicitly in the phase report: "link decoration parity:
  ALREADY ACHIEVED (confirmed pre-existing at VALIDATE, apps/api/services/campaign_sender.py:284
  runs before the channel fork at :294) / attribution-echo parity: [achievable via header only,
  still no webhook to consume it — documented known-gap | not achievable at all — Gmail API
  limitation, documented known-gap]."

### Step B — Confirm shared compose step + close the attribution-echo question

- [x] B1. Re-read `campaign_sender.py::send_campaign_emails()` at EXECUTE time (line numbers may
  have drifted) and re-confirm `decorate_links(...)` and the open-tracking-pixel append both
  execute BEFORE the `if gmail_sender is not None:` branch — i.e. still unconditional/shared. If a
  concurrent change has broken this invariant since VALIDATE (03-08-26), treat restoring it as a
  P0 regression fix within this phase, not a new feature.
  the SendGrid path" is not required — that invariant already holds. Do not restructure
  `send_campaign_emails()` unless B1 finds the invariant broken.
  is NOT wired through to `send_via_gmail()` today. If A1 found a feasible header mechanism, add
  it here (optional param on `send_via_gmail()`, threaded through to `gmail.send_message()`); if
  A1 found nothing feasible, do not add dead code — document the known-gap per A2 instead.

### Step C — Tests

- [x] C1. New regression/characterization test (unit): assert the `body_html` value passed into
  `send_via_gmail()` contains the same `_bid` token structure that `decorate_links()` would
  produce for an equivalent SendGrid send (i.e. prove today's shared-decoration behavior with a
  test, since none exists) — Fully-Automated, closes the link-decoration half of AC12.
- [x] C2. If A1/B4 find an attribution mechanism, add a test proving it round-trips; if not
  feasible, write a Known-Gap test (or a clearly labeled `pytest.mark.skip(reason=...)` /
  documentation block) stating exactly what does NOT get echoed back for Gmail-Connect sends, so
  the gap is visible in the test suite, not silently invisible.
- [x] C3. Regression: existing SendGrid decoration/`custom_args` tests (via
  `tests/unit/test_agent_origin_exclusion.py::test_campaign_sender_excludes_agent_origin` and
  `tests/unit/test_link_decoration.py`) remain green — confirms no behavior change to the
  SendGrid path from any edits in this phase.

---

## Exit Gate

```bash
.venv/bin/python3.11 -m pytest tests/unit -k "gmail_sender or campaign_sender" -q
# Expected: 0 failures (includes new Step C1/C3 tests plus the pre-existing
# test_campaign_sender_excludes_agent_origin regression test)

.venv/bin/python3.11 -m pytest tests/integration -k "gmail or decoration" -q
# Expected: 0 failures, OR 0 collected or deselected (currently 0 tests match this filter,
# confirmed at VALIDATE — exit code 0 either way; add a Hybrid-tier test here only if Step A
# finds a click-round-trip worth covering at the integration level)
```

- SPEC AC12 has a passing proving test for the link-decoration half (Fully-Automated, C1) and a
  documented, scoped known-gap OR a passing test for the attribution-echo half, per Step A's
  finding — link decoration parity must be fully proven either way (it already exists in
  production code; C1 is the regression proof that was previously missing).
- Phase report written to report destination above, and MUST include the A1/A2 finding verbatim
  plus a note flagging the SPEC-vs-code discrepancy found at VALIDATE (see Correction Notice) for
  the umbrella/SPEC-owner to reconcile.

---

## Blockers That Would Justify BLOCKED Status

- If Step B1's re-confirmation finds the shared-decoration invariant has been broken by
  concurrent work since VALIDATE (03-08-26) in a way that is not a small, obviously-safe fix —
  would require re-scoping/re-research before executing further.
- If Gmail-Connect's OAuth send mechanism turns out to not support any body/header pass-through
  comparable to what's assumed (unlikely — `gmail.py::_build_raw_message()` already constructs a
  raw MIME message and could carry a custom header technically) — would require re-scoping to
  research further before executing.

---

## Phase Loop Progress

- [ ] 1. RESEARCH — research-agent: prior phase reports read; test context loaded; confirm Gmail
  API attribution ceiling (Step A); re-confirm the VALIDATE Correction Notice's line-number claims
  still hold in the current file
- [ ] 2. INNOVATE — innovate-agent: approach decided (largely pre-decided by program INNOVATE
  Fork 5 as corrected by VALIDATE — confirm/refine only; INNOVATE should explicitly ratify the
  narrowed scope from the Correction Notice)
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written
- [x] 5. EXECUTE — all checklist items done; per-section test gates run and green (or gaps documented)
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.**

---

## Touchpoints

- `apps/api/services/campaign_sender.py` (shared compose step region only — see Blast Radius)
- `apps/api/services/email_providers/gmail_sender.py`
- `apps/api/services/email_providers/gmail.py` (only if Step A finds a header mechanism worth adding)

---

## Public Contracts

- SendGrid send path behavior unchanged (decoration/custom_args timing and values unchanged; no
  code move is expected to be needed per the Correction Notice).
- No change to how a customer chooses SendGrid vs Gmail-Connect (out of scope per SPEC).
- `send_via_gmail()`'s existing 6 parameters (`db, sender, to_email, subject, body_html,
  unsubscribe_url`) remain backward compatible — any new parameter (if Step A licenses one) must
  be optional with a safe default so no other caller breaks.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Gmail-Connect send receives identically decorated body_html as SendGrid (regression proof of existing behavior) | Fully-Automated | AC12 (link-decoration half) |
| Gmail-Connect send passes attribution equivalently, OR documented known-gap if Gmail API cannot | Agent-Probe / Known-Gap (contingent on Step A) | AC12 (attribution-echo half) |
| SendGrid decoration/custom_args regression-free after any Step B edits | Fully-Automated | (regression guard) |

Failing stub (example):
```
test("should decorate links identically for Gmail-Connect and SendGrid sends", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: gmail decoration parity")
})
```

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/visitors-identity/active/identity-program_03-08-26/phase-3-gmail-parity_PLAN_03-08-26.md`
- Last completed step: VALIDATE (V1-V7 complete, this section)
- Validate-contract status: written (see below) — Gate: PASS
- Supporting context files loaded: umbrella plan, SPEC, INNOVATE Decision Summary (Fork 5), research-phaseH.md, direct read of `apps/api/services/campaign_sender.py` / `gmail_sender.py` / `gmail.py`
- Next step: Spawn vc-research-agent for RESEARCH (Step 1) — can run in parallel with Phases 1 and 2's research; RESEARCH should re-confirm the Correction Notice's line-number claims against the file as it exists at that time

---

## Validate Contract

Status: PASS
Date: 03-08-26
date: 2026-08-03
generated-by: outer-pvl

Parallel strategy: sequential
Rationale: single-phase plan, 3 files in blast radius, no cross-agent coordination needed for this VALIDATE pass — score 1/7 (S7 not met, <5 files; S6 not met, no high-risk class; S1/S2/S3/S4/S5 not met). Sequential fan-out (this single vc-validate-agent pass, Layer 1 + Layer 2 reasoned inline) was appropriate; no additional agents spawned.

Test gates (C3 5-column table — ADDITIVE; existing consumers still parse the legacy line form below it):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC12-link-decoration | Gmail-Connect send's body_html carries the same decorate_links()-produced `_bid` token structure as the SendGrid send for an equivalent recipient | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -k "gmail_sender or campaign_sender" -q` (new Step C1 test) | A |
| AC12-regression-sendgrid | Existing SendGrid decoration + custom_args behavior is unaffected by any Phase 3 edit | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py tests/unit/test_link_decoration.py -q` | A |
| AC12-attribution-echo | Gmail-Connect send carries a custom_args-equivalent attribution signal, OR the absence of one is explicitly documented as a known-gap | Agent-Probe (Step A research finding) | Phase report Step A1/A2 finding; `.venv/bin/python3.11 -m pytest tests/integration -k "gmail or decoration" -q` (currently 0 tests collected — confirmed at VALIDATE, exits 0; a new Hybrid test is optional here, contingent on Step A) | D (documented known-gap, unless Step A finds a trivial header mechanism, in which case B) |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: the `strategy:` column carries ONLY the 3 proving strategies (Fully-Automated / Hybrid / Agent-Probe). Known-Gap is NEVER a `strategy:` value — it is a named residual row carried via gap-resolution D, never a strategy that proves a behavior. (AC12-attribution-echo's strategy is Agent-Probe — the research finding itself is the proving artifact; its gap-resolution is D only if that research concludes "not achievable.")

Legacy line form (retained so existing validate-contract consumers still parse):
- Gmail link-decoration parity: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit -k "gmail_sender or campaign_sender" -q`]
- Gmail attribution-echo parity: [agent-probe: Step A1/A2 research finding recorded in phase report] | [known-gap: documented if Gmail API has no equivalent mechanism and no consuming webhook exists]
- SendGrid regression: [Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py tests/unit/test_link_decoration.py -q`]

Dimension findings:
- Infra fit: PASS — no container/worker/proxy/runtime surface touched; pure service-layer edit in an existing async function; no new deploy surface.
- Test coverage: CONCERN → RESOLVED via plan update — original plan's exit-gate premise assumed decoration was un-shared; corrected to reflect that C1 is a regression/characterization test (proving pre-existing behavior) rather than new-feature verification. Both exit-gate commands verified to run cleanly against the current repo (`tests/unit -k "gmail_sender or campaign_sender"` collects 2 existing tests today; `tests/integration -k "gmail or decoration"` collects 0, deselects 442, exits 0 — both safe as written).
- Breaking changes: PASS — `send_via_gmail()`'s public signature stays backward-compatible (any new param must be optional per corrected Public Contracts section); no schema, no API contract, no auth surface touched.
- Security surface: PASS — no new external input, no new endpoint, no PII exposure change (if a `custom_args`-equivalent header is ever added, it carries the same `site_id`/`visitor_id` values already sent to SendGrid today — no new data class introduced); `is_emailable_identity()` 3-param contract untouched; no auto-send, suppression/do_not_email/rate-cap/unsubscribe chain untouched (Phase 3 sits entirely downstream of those checks in `send_campaign_emails()`, after the suppression/rate-cap gates at lines ~197-237).
- Section A feasibility (Research Gmail attribution ceiling): PASS — mechanically feasible; A1/A2 are research/documentation tasks with a clear phase-report output format; no code risk.
- Section B feasibility (Shared compose step): CONCERN → RESOLVED via plan update. Mechanical feasibility: the ORIGINAL plan text (checklist items B1-B3, "move decoration/custom_args to run unconditionally before the channel fork") describes a code change that is **already true in the current codebase** — `decorate_links()` runs at `campaign_sender.py:284`, unconditionally, before the `if gmail_sender is not None:` fork at line 294; the resulting `body_html` already reaches `send_via_gmail()` (line 302) identically to the SendGrid branch (line 319). Gaps found: none remaining after correction — the plan now correctly scopes Step B to (a) re-confirming this invariant at EXECUTE time (line numbers may drift) and (b) only wiring an attribution-echo mechanism if Step A licenses one. Conflicts found: the locked SPEC (lines 421-423) asserts Gmail-Connect "does not call decorate_links() ... ships raw, undecorated links today" — this contradicts direct code evidence and is flagged as an Open Gap for SPEC reconciliation, not fixed in this plan (out of write-scope). Highest-risk edit + mitigation: IF Step A licenses a header-based attribution mechanism, the highest-risk edit is threading a new optional parameter through `send_via_gmail()` → `gmail.send_message()` → `_build_raw_message()`; mitigate by keeping the parameter optional with a safe default and covering it with the Step C2 test before merging.
- Section C feasibility (Tests): PASS — target files/functions (`tests/unit/test_agent_origin_exclusion.py`, `tests/unit/test_link_decoration.py`, new test file(s) matching the exit-gate `-k` filters) exist and are correctly named to be collected by the stated pytest `-k` filters (verified via `--collect-only` at VALIDATE: `gmail_sender or campaign_sender` → 2 tests collected today; `gmail or decoration` integration → 0 collected/442 deselected, exit 0).

Open gaps:
- SPEC discrepancy (non-blocking, not fixed in this plan): `identity-program_SPEC_03-08-26.md` lines 421-423 state the Gmail-Connect path "does not call decorate_links() or pass custom_args — it ships raw, undecorated links today" — this is contradicted by direct code read of `campaign_sender.py` (decoration is already unconditional/shared, confirmed at lines 284 vs 294). Recommend the umbrella/SPEC-owner correct this at the next SPEC touch or record it in the program's Open Gaps ledger; it does not block Phase 3 because Phase 3's corrected scope (regression-test the existing parity + resolve only the attribution-echo question) remains fully valid and actionable regardless of the SPEC's phrasing.
- known-gap: documented as NEW PLAN REQUIRED — N/A (no gap requires a new plan; the attribution-echo outcome, if "not achievable," is a within-phase documented known-gap per Step A2/C2, not a deferred-to-backlog item).

What this coverage does NOT prove:
- `tests/unit -k "gmail_sender or campaign_sender"` proves body_html structure equivalence between channels and SendGrid regression safety; it does NOT prove a real Gmail send actually delivers (no live Gmail API call in unit tests — mocked/monkeypatched per existing `test_gmail_connect.py` conventions).
- `tests/integration -k "gmail or decoration"` (if a new Hybrid test is added per Step A) proves the click→identify round-trip against a local Postgres/Redis fixture; it does NOT prove behavior against Gmail's live API or a live OAuth grant — that remains an Agent-Probe/manual-verification residual, consistent with how `gmail_sender.py`'s existing token-refresh logic is tested today (mocked, per `test_gmail_connect.py`).
- Neither gate proves whether Gmail message headers (if added) survive Gmail's own server-side processing untouched in production — that would require a live-send probe, which is out of scope for this phase (no live-provider test budget allocated; documented as inherent to any header-based approach, not a gap unique to this plan).

Gate: PASS (no FAILs; the one Section B CONCERN was resolved via an in-plan correction applied during this VALIDATE pass — plan text now matches verified ground truth; the attribution-echo item is carried as a properly named, non-blocking residual with a Fully-Automated proving gate covering the behavior this phase actually delivers)
Accepted by: session (autonomous outer-PVL pass — plan corrected in-place per V6; no unresolved concerns remain requiring separate user acceptance)
