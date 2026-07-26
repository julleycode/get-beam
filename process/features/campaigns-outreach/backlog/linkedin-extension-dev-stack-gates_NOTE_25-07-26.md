---
name: report:linkedin-extension-dev-stack-gates
date: 25-07-26
metadata:
  node_type: memory
  type: report
  feature: campaigns-outreach
---

# LinkedIn Extension — Dev-Stack-Gated Test Gaps (from UPDATE PROCESS, 25-07-26)

Source plan: `process/features/campaigns-outreach/active/linkedin-extension_25-07-26/linkedin-extension_PLAN_25-07-26.md`

## Problem

Four test gates for the LinkedIn Outreach Connect extension could not be independently re-run
during the 25-07-26 UPDATE PROCESS closeout session because the sandbox has no way to boot the
full dev stack (Next.js dev server + live backend + Postgres):

1. `apps/web/e2e/linkedin-outreach-extension.spec.ts` — AC6 dashboard-side leg (fabricated
   wrong-origin/missing-source/missing-nonce message → asserts no `enableLinkedInOutreach` call).
2. Same spec file — AC7 (ToS warning banner shown on the extension-connect path).
3. Same spec file — AC9 (Firefox/Safari / no-extension case → only manual form renders).
4. `tests/integration/test_social_accounts_list.py` — AC2 courtesy backend regression (needs
   Postgres; does not itself exercise `outreach-connect`/`outreach-status`, but is the plan's named
   regression check).

## Root Cause

Sandbox environment limitation, not a code defect. Execute-agent's EVL confirmation earlier in the
same working session reported these gates green; this UPDATE PROCESS Deep-Mode independent re-run
could not reproduce that because no dev server/Postgres is available in this environment.

## Fix

Re-run these 4 gates in an environment with a live dev stack + Postgres:

```
cd apps/web && npm run test:e2e -- linkedin-outreach-extension.spec.ts
.venv/bin/python -m pytest tests/integration/test_social_accounts_list.py -q
```

If both pass, update the plan's Verification Evidence / SPEC Achievement scoring to 10/10 met and
proceed toward archiving `linkedin-extension_25-07-26` once the human VERIFIED sign-off (real
LinkedIn session) also completes.

## Priority

Low — matches the plan's own "CODE DONE, not yet VERIFIED" classification; these are expected
residual gates, not surprises. Blocking only for final archival, not for continued use of the
shipped code.
