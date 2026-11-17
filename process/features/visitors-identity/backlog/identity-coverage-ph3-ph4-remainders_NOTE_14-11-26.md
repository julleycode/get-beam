---
name: note:identity-coverage-ph3-ph4-remainders
description: "Open remainders of the archived identity-coverage-pixel-fppro program: Phase 3 Fingerprint Pro device continuity (never started) and Phase 4 US ground-truth benchmark measurement (docs done, panel never run)"
date: 14-11-26
feature: visitors-identity
---

# Identity coverage (pixel → Fingerprint Pro) — Phase 3 / Phase 4 remainders

**Status:** open — deferred. Parent task folder archived 14-11-26 by the repo audit:
`process/features/visitors-identity/completed/identity-coverage-pixel-fppro_02-08-26/`.

## What is closed

- Phase 1 (vendor pixel PoC, Leadpipe stack attrs) — done; its manual live gate was transferred to
  the recovery program.
- Phase 2 (wire candidate ingest) — superseded by `plans/260805-1543-identity-coverage-recovery/`
  (lives outside `process/`, so plan-discovery does not see it).
- Phase 4 docs half — `benchmark-template.csv` + `benchmark-runbook.md` written 07-08-26 (both now
  in the archived task folder).

## What is still open

| Item | Why open | Blocker type |
|---|---|---|
| Phase 3 — Fingerprint Pro device continuity | Never started. fp3 (fonts + audio, shipped 07-08-26) may make it unnecessary — measure fp3 continuity first. | needs-live-provider (paid Fingerprint Pro account) + product decision |
| Phase 4 — US benchmark measurement | Needs a 30-50 person US residential tester panel and a working vendor pixel. | human panel + operator: Leadpipe org + pixel must be revived first |

## Before starting either

1. Operator: confirm Leadpipe account/org + pixel are live (the 05-08-26 live check found the
   account expired, `pixels_active=0`).
2. Run the 5-session US smoke before recruiting a full panel.
3. Decide Phase 3 from measured fp3 continuity, not from the vendor claim.
4. Any new build work goes through PLAN + VALIDATE as a fresh task folder — do not reopen the
   archived one.

Related notes: `fingerprint-pro-device-continuity_NOTE_02-08-26.md`,
`vendor-pixel-benchmark_NOTE_02-08-26.md`.
