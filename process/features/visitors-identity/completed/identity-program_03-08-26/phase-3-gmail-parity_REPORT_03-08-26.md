---
phase: phase-3-gmail-parity
date: 2026-08-04
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/identity-program_03-08-26/phase-3-gmail-parity_PLAN_03-08-26.md
---

# Phase 3 — Gmail Decoration Parity — EXECUTE report

## What Was Done

Test-only phase, exactly as the PVL-corrected scope predicted. No production code changed.

- **B1 (re-confirm invariant)** — re-read `apps/api/services/campaign_sender.py` at EXECUTE time.
  Line numbers drifted (Phase 1/2 edits) but the invariant **holds**:
  `decorate_links(body_html, iv.email, site_host, touchpoint_id=str(tp_row.id))` at **line 389**,
  open-tracking pixel append at **lines 391-394**, channel fork `if gmail_sender is not None:` at
  **line 399**, `send_via_gmail(... body_html=body_html + unsub_footer ...)` at line 402,
  SendGrid `sender.send(... body_html=body_html, custom_args={...})` at lines 421-429.
  Decoration + pixel are shared. No P0 regression fix needed; no restructure performed.
- **C1/C3 tests** — new file `tests/unit/test_gmail_sender_decoration_parity.py` (5 tests).
  Named so the contract's exact `-k "gmail_sender or campaign_sender"` filter collects it.
- **A1/A2 research** — recorded verbatim below; conclusion is "not achievable", so **no dead code
  was added** to `gmail_sender.py` / `gmail.py` (both unchanged).

## Step A finding (verbatim, per A1/A2)

**A1.** The Gmail API has **no** `custom_args` equivalent. `users.messages.send`
(`gmail.py::send_message`, POST `{"raw": <base64 RFC-822>}`) accepts only a raw MIME message — no
metadata envelope. A custom MIME header *could* technically be injected in
`gmail._build_raw_message()` (it already sets `List-Unsubscribe` the same way), but that would be
dead code: **Gmail emits no open/click event stream at all**, so there is nothing for a header to
be echoed back to. SendGrid's `custom_args` is meaningful only because SendGrid's open/click
webhook echoes it into `IdentitySignal` (owned-data-layer, `identity_signals_enabled`). Building a
Gmail-side webhook is out of program scope (umbrella Global Constraints — no new
dependencies/runtime surfaces). Therefore: no header added.

**A2. Parity ceiling.** "link decoration parity: **ALREADY ACHIEVED** (confirmed pre-existing at
VALIDATE and re-confirmed at EXECUTE — `apps/api/services/campaign_sender.py:389` runs before the
channel fork at `:399`) / attribution-echo parity: **not achievable at all — Gmail API limitation
(no open/click event stream to echo to), documented known-gap**."

Mitigating fact worth recording: Beam's **own** first-party attribution — the
`/o/{touchpoint_id}` open pixel and the `_bid` / `_tp` decorated links — is already shared across
both channels and is unaffected. The gap is narrowly the SendGrid-webhook→`IdentitySignal`
corroboration path, not attribution as a whole. AC12's deterministic `_bid` click→identity
mechanism (what Phase H's promotion sweep actually depends on) is fully channel-agnostic today.

## What Was Skipped or Deferred

- No edit to `gmail_sender.py::send_via_gmail()` or `gmail.py` (A1 licensed none). Signature stays
  at its existing 6 params — Public Contracts unchanged.
- No new integration test: with no attribution mechanism to round-trip, the Hybrid leg the plan
  made optional ("contingent on Step A") has nothing to cover. Gate 3 stays at 0-collected.

## Test Gate Outcomes

| Gate (verbatim from validate-contract) | Result |
|---|---|
| `.venv/bin/python3.11 -m pytest tests/unit -k "gmail_sender or campaign_sender" -q` | **7 passed**, 1584 deselected, exit 0 |
| `.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py tests/unit/test_link_decoration.py -q` | **26 passed**, exit 0 |
| `.venv/bin/python3.11 -m pytest tests/integration -k "gmail or decoration" -q` | 0 collected, 453 deselected, exit 0 (as VALIDATE predicted) |

AC12 mapping: `AC12-link-decoration` → **A (proven now)**; `AC12-regression-sendgrid` → **A**;
`AC12-attribution-echo` → **D (documented known-gap)**, made visible in the suite by
`test_known_gap_gmail_has_no_custom_args_equivalent`, which asserts the gap's exact shape
(`custom_args` absent from both `send_via_gmail` and `gmail.send_message` signatures) so it fails
loudly the day the gap is closed and this note goes stale.

Non-vacuity note: `test_gmail_and_sendgrid_receive_identical_decorated_body` drives the real
`send_campaign_emails()` loop through a successful send on each channel and compares the actual
`body_html` handed to each; moving `decorate_links` or the pixel append inside the SendGrid branch
makes it red. Fernet ciphertext is nondeterministic, so `_bid`/unsub tokens are normalized before
the structural comparison and separately proven decodable back to the recipient's address.

## Plan Deviations

None. (One naming detail: the new test file is `test_gmail_sender_decoration_parity.py` rather
than a bare `..._decoration_parity.py`, specifically so the contract's exact
`-k "gmail_sender or campaign_sender"` filter collects it — this satisfies the plan's Blast Radius
instruction "Match the exit-gate `-k` filters below when naming test functions/files.")

## Test Infra Gaps Found

- No Docker in this environment → integration lane and migration round-trip not exercised
  (pre-named known-gaps, not FAILs). Gate 3 collects 0 tests regardless, so nothing was skipped.

## Flag for umbrella / SPEC owner (required by plan Exit Gate)

`identity-program_SPEC_03-08-26.md` **lines 421-423** state the Gmail-Connect path "does not call
`decorate_links()` or pass `custom_args` — it ships raw, undecorated links today." The
`decorate_links` half of that claim is **factually wrong** against the codebase (re-verified at
EXECUTE: shared at `:389`, before the fork at `:399`). The `custom_args` half is correct. Needs a
SPEC amendment or an Open Gaps ledger entry — out of this plan's write scope.

## Closeout Packet

- Selected plan: `process/features/visitors-identity/active/identity-program_03-08-26/phase-3-gmail-parity_PLAN_03-08-26.md`
- Finished: A1, A2, B1, C1, C2, C3 — all checklist items.
- Verified: all 3 contract gates green (cold worktree).
- Unverified: nothing in scope. Gmail live-send behavior remains an Agent-Probe residual, as the
  contract's "What this coverage does NOT prove" already records.
- Remaining: EVL confirmation run; umbrella state update; SPEC discrepancy reconciliation.
- Classification: **Ready for UPDATE PROCESS archival** (with the AC12-attribution-echo known-gap
  on record).

## Forward Preview

- **Test Infra Found:** `tests/unit/test_gmail_sender_decoration_parity.py` provides a reusable
  no-DB harness (`_run_send`) that drives a full `send_campaign_emails()` iteration to a real send
  on either channel with 6 mocked `db.execute` results. Phases 5/6 touching the send loop can
  reuse it; if the loop gains another `db.execute`, extend that `side_effect` list.
- **Blast Radius Changes:** none — zero production files modified by this phase.
- **Commands to Stay Green:** the 3 gate commands above.
- **Dependency Changes:** none.
