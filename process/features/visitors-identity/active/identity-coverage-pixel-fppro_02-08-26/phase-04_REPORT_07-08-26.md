---
phase: phase-04-us-ground-truth-benchmark-pack
date: 2026-08-07
status: COMPLETE_WITH_GAPS
feature: visitors-identity
plan: process/features/visitors-identity/active/identity-coverage-pixel-fppro_02-08-26/phase-04-us-ground-truth-benchmark-pack.md
---

# Phase 4 — US ground-truth benchmark pack (docs half)

**TL;DR** — Both docs artifacts written; zero source code touched; zero tests run (docs only). The
measurement itself (30-50 human US testers) is a live-provider human activity and stays unrun by
design. Phase cannot reach `✅ VERIFIED` until a panel runs, and it cannot run until the recovery
program clears the dead Leadpipe account.

## What Was Done

1. `benchmark-template.csv` — 33 columns, 6 FAKE example rows (all emails `*.invalid`). Column count
   verified identical on every row. Covers: tester/network/device identity, both continuity arms
   (`beam_fp3` + `fppro_visitor_id`), the phase-required
   `fppro_same_visitorid_across_incognito` y/n slot, vendor output, ground truth, derived
   `name_match`/`email_match`/`verdict`, and an `exclude_from_metrics` + reason pair for
   VPN/relay/bot rows.
2. `benchmark-runbook.md` — recruitment criteria (30-50 US residential, no VPN/Relay, browser+device
   +geo spread, ≥24h follow-up), verbatim tester script (2-3 visits), operator per-visit procedure,
   derived-column rules, exact formulas (Coverage = M/T, Precision = C/M, FPR = W/M) with 5
   eligibility rules, pass bar (Precision ≥ 0.70, N ≥ 30), both decisions, PII rules, out-of-scope.

Design choices worth flagging:

- **Beam fp3 recorded as an explicit comparison arm on every row**, not a footnote. The buy case for
  Fingerprint Pro only exists if fp3 (fonts+audio, shipped 07-08-26) measurably fails where Pro
  holds. Encoded as a numeric no-buy rule: Safari delta < 0.10 → no-buy.
- **VPN/Relay rows excluded from the three headline metrics but kept in the file** — they are the
  only rows that can score `fppro_vpn_signal` accuracy. Including them in Coverage would fabricate
  a bad vendor number.
- **Metrics split by browser family** is mandated, because an overall continuity number hides a
  Safari/ITP collapse — which is the exact gap under evaluation.
- `Precision + FPR = 1` by construction; documented so a mismatch is read as a bad row, not a new
  finding.

## What Was Skipped or Deferred

- **Lab DB export helper (phase step 3, marked "Optional")** — deliberately NOT written, per task
  scope and YAGNI. With no panel recruited it would have nothing to export and would be built
  against guessed column needs. Recorded in the runbook §8.
- **The actual benchmark run (phase step 4)** — human panel, `needs-live-provider`, out of scope.
- Phases 1-3 files untouched. No source code touched.

## Test Gate Outcomes

None applicable — docs-only phase, no validate-contract, no test gates. Only mechanical check run:
CSV column-count consistency (33 on all 7 lines, via `csv` parse). Passed.

## Plan Deviations

None material. Two within-blast-radius elaborations of the phase file's column spec:

- Added `exclude_from_metrics` / `exclusion_reason` columns (not named in the phase file). Needed to
  make the phase's own stated risk — "friends on Private Relay invalidate person-graph cells" —
  mechanically actionable rather than a prose warning.
- Added `beam_fp3` / `beam_fp3_stable_vs_prev_visit` columns. Directed by the task prompt as the
  comparison arm; not in the original phase file (which predates fp3 shipping).

## Test Infra Gaps Found

None. No test surface exists for docs artifacts, and none should be invented for them.

## Closeout Packet

- **Selected plan:** `.../identity-coverage-pixel-fppro_02-08-26/phase-04-us-ground-truth-benchmark-pack.md`
- **Finished:** both docs deliverables (phase steps 1 + 2).
- **Verified:** file contents and CSV structural consistency. Nothing empirical — no panel ran.
- **Unverified:** every number the instrument is meant to produce. The pass bar (Precision ≥ 0.70) is
  the phase file's own example bar, not an empirically calibrated one.
- **Remaining:** run the panel (blocked on recovery program), then write the numbers REPORT and
  record Decisions A + B.
- **Classification:** `Keep in active/testing` — the phase's docs half is done, but its measurement
  half is unrun and its success criteria are only partly satisfiable without a panel.

## Forward Preview

**Test Infra Found** — none created; none needed.

**Blast Radius Changes** — 2 new files in the task folder. Zero source files, zero migrations, zero
config, zero other phase files.

**Commands to Stay Green** — none. No code changed, so no gate can regress from this phase.

**Dependency Changes** — none. Confirms an existing sequencing dependency rather than adding one:
recovery program unblocks Leadpipe → panel runs → Decision B (keep/kill Leadpipe). Decision A
(Fingerprint Pro buy/no-buy) also gates Phase 3, which stays `pending`.

## Follow-up Stubs Created

None. Deferred items are recorded in-place (runbook §8 + this report) rather than as separate
backlog artifacts, since both are already tracked as phase steps in the phase file.

## CONTEXT_PARTIAL

`CONTEXT_PARTIAL: fingerprint-pro-pricing` — the buy/no-buy rule references per-identification cost
as a decision input, but no Fingerprint Pro price point was available in repo context. The operator
must supply it at decision time.
