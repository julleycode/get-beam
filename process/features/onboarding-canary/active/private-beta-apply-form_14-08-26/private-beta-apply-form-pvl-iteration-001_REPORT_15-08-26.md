---
name: report:private-beta-apply-form-pvl-iteration-001
description: "PVL supplement cycle 1 — closed 3 FAILs / 4 CONCERNs from validate cycle 1"
date: 15-08-26
feature: onboarding-canary
metadata:
  node_type: report
  type: pvl-iteration
  cycle: 1
  domain: plan
---

# PVL Iteration 001 — private-beta-apply-form

## Input verdict

Validate cycle 1: `Gate: BLOCKED` — 3 FAIL / 4 CONCERN (8 gaps total, one of which
carried an open user decision).

## Gaps addressed

| Gap | Severity | Section | Resolution |
|---|---|---|---|
| 1 | FAIL | implementation-sections | `_clean_url()` scheme guard + 2000-char cap on write (insert and backfill); `html.escape()` on the pre-existing `site_info` interpolation; `safeHref()` render guard in admin UI. New gates B6, B7, D3. |
| 2 | FAIL | verification-evidence | E1 rescoped to executable navigation only — matches `onboarding-steps.js:565`, ignores prose at `:9`/`:555` and `href="/sign-in"` at `:564`. |
| 3 | FAIL | touchpoints | `letter.html:120` inventoried and repointed to `/apply`; Section E now 7 CTAs; E3 probe extended; rollback count updated. |
| 4 | FAIL | implementation-sections | F.3 rewritten against real mechanics (`api.ts:194-206`, `layout.tsx:530`). Message-constant match + render-time branch. `api.ts` error contract NOT widened. New gate F8. |
| 5 | CONCERN | hard-guardrails | New G2a: untracked live alembic head → STOP and surface by name and owning plan. |
| 6 | CONCERN | verification-evidence | A1 scoped to `upgrade()` via awk range extraction. |
| 7 | CONCERN | verification-evidence | New Hybrid gate F7 — real-DB `_is_email_allowlisted` assertions, closing the vacuous-green hole where F1 mocks the function under test. |
| 8 | CONCERN | verification-evidence | "Docker IS running" replaced with a 3-step daemon ladder; never-environment-blocked rule retained. |

## Orchestrator decision applied this cycle

`letter.html:120` (`start beaming for free`) classified as an **account-creation**
CTA, not a demo CTA, and repointed to `/apply` — consistent with the locked
"demo open, signup gated" decision. Raises the static `/apply` link count to 7.

## Defect classes worth carrying forward

1. **Grep gates that match outside their intended region** (gaps 2 and 6, same
   class). A gate a correct implementation fails is worse than no gate — an
   execute-agent iterating to green will damage correct code to satisfy it.
2. **Plan asserting a mechanism that does not exist in source** (gap 4). The
   403-detection branch was specified against an API shape the client never
   produces for string details.
3. **Sanitization applied only to new fields**, leaving a pre-existing field on
   the same sink unescaped (gap 1). `site_url` was pre-existing but became
   *required* under this change, which is what made it reachable.

## Validator state

`validate-plan-artifact.mjs` → 0 failures, 0 warnings (647 lines). All required
sections intact.

## Open item carried to re-validate

Gap 4's preferred fix extracts the invite-only detail string to a module constant
in `dependencies.py` — a file marked "explicitly NOT touched" for *gate logic*. A
literal→constant extraction changes no logic and a zero-touch fallback is
specified, so it was not treated as scope expansion. Re-validate should confirm.

## Next step

Adversarial verifier findings pending. Re-spawn vc-validate-agent from V1 once
they land.
