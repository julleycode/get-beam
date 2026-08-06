---
name: note:site-id-lifecycle-ac6-playwright-auth-harness
description: "AC6 delete-dialog pixel warning — authed Playwright leg deferred on the repo-wide Clerk auth-harness gap"
date: 04-08-26
feature: pixel
---

# AC6 deferred e2e leg — site-id-lifecycle (04-08-26)

Created per the plan's Validate Contract §VI. Matches the ads-audiences Phase 1/2 and
cadence-bot-flag precedent for the same repo-wide gap.

## What shipped

`apps/web/src/app/dashboard/page.tsx` — the delete dialog now renders, inside
`DialogHeader` and above `DialogFooter` (i.e. before the user can press Delete):

> Your installed pixel will also stop working — the tracking snippet on your website will
> start being rejected until you re-add this site or install a new snippet.

Styled `text-sm text-destructive`, visually distinct from the existing
"This can't be undone." sentence, which is unchanged.

## What is NOT proven

The authed Playwright leg. `apps/web/e2e/dashboard.spec.ts` has **no delete-flow coverage
at all** today, and adding one requires reaching an authenticated dashboard with a site
present — blocked by the repo-wide Clerk auth-harness gap. No e2e assertion was added,
deliberately: an unrunnable spec is worse than a named gap.

Verification actually performed at EXECUTE: static source read confirming the copy exists
and sits above `DialogFooter` within the same dialog, plus `npm run lint` green. That is
the plan's documented Agent-Probe fallback — it proves the copy is in the component, NOT
the full authed user journey.

Per the plan's vacuous-green note: **AC6 must not be marked PASS on this fallback alone.**
The gate stays CONDITIONAL.

## To close

1. Land the Clerk auth harness for Playwright (shared blocker across 3 features).
2. Add to `apps/web/e2e/dashboard.spec.ts`: open the delete dialog and assert it contains
   both `can't be undone` and `/pixel will also stop working/i` before Delete is clickable.
3. `cd apps/web && npm run test:e2e`
