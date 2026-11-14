---
phase: 4
title: "US ground-truth benchmark pack"
status: pending
priority: P2
dependencies: [1, 2, 3]
---

# Phase 4: US ground-truth benchmark pack

## Overview

Process + spreadsheet (not product UI) to measure Coverage / Precision / FPR for: RB2B API, Customers.ai pixel, Fingerprint Pro continuity — on **US residential** testers only.

## Requirements

- Functional: template CSV + runbook for 30–50 US testers; columns for truth name/email, VPN/Relay, each provider output, verdict
- Metrics: Coverage = matched/total; Precision = correct/matched; FPR = wrong/matched
- Non-functional: no PII committed to git — template only with fake rows

## Related Code Files

- Create: `process/features/visitors-identity/active/identity-coverage-pixel-fppro_02-08-26/benchmark-template.csv`
- Create: `.../benchmark-runbook.md` (how to recruit, no VPN, record results)
- Optional: small script to export Lab visitors for a site into the sheet

## Implementation Steps

1. Write CSV template + runbook (residential US, no VPN/Relay, record Candidate/Verified).
2. Define pass bar (example: Precision ≥ 0.7 for pixel path before enabling more sites).
3. Optional export helper from Lab DB (hashed emails ok).
4. After first 30 testers, write REPORT with numbers — decide keep/kill Customers.ai vs RB2B API.

## Success Criteria

- [ ] Template + runbook checked in (no real PII)
- [ ] Clear metric definitions
- [ ] Slot for Fingerprint Pro “same visitorId across incognito?” yes/no column

## Risk Assessment

- Too few testers → noise; enforce N≥30 before product decision
- Friends on Private Relay invalidate person-graph cells — mark network_type
