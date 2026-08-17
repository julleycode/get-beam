---
name: report:coop-terms-repin-runbook
description: Operator runbook for re-pinning coop_terms_version — every prior acceptance is invalidated and every owner must re-accept
date: 16-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: phase-1-supplement
---

# Runbook — re-pinning `coop_terms_version`

**TL;DR** — At any re-pin of `coop_terms_version`, run
`UPDATE sites SET contribution_enabled = false;`. The digest change invalidates all prior
acceptances, and every owner must re-accept before contributing again.

## Why

`routers/sites.py::update_site` constant-compares the submitted `terms_version` against
`settings.coop_terms_version` and writes a `ContributionConsentAcceptance` row in the SAME
transaction as the flag flip. Once the pinned digest changes, every existing acceptance row records
consent to *superseded* terms — but `Site.contribution_enabled` is a plain boolean and does not
re-check the digest on its own. Without the reset, sites keep contributing under stale consent.

## Steps

1. Pin the new digest (`COOP_TERMS_VERSION` env / `settings.coop_terms_version`) and deploy.
2. Immediately run, with `DATABASE_URL` pinned to the intended target (the repo `.env` points at
   Supabase PROD — verify before running):

   ```sql
   UPDATE sites SET contribution_enabled = false;
   ```

3. Notify owners that re-acceptance is required.

No code change is needed for the reset: the M2 global-flag guard plus the digest comparison already
block any re-enable without a fresh, current acceptance. Opting OUT is never gated, so the mass
reset can never be blocked by the guards.

## Notes

- The acceptance rows are **not** deleted — they are an append-only legal audit trail (plan decision
  H1-D) and remain the evidence of lawful basis for contributions already made.
- The reset is idempotent and safe to re-run.
