---
name: report:private-beta-apply-form-pvl-iteration-002
description: "PVL supplement cycle 2 — closed 3 FAILs / 3 CONCERNs / 6 NITs found by an independent adversarial verifier"
date: 15-08-26
feature: onboarding-canary
metadata:
  node_type: report
  type: pvl-iteration
  cycle: 2
  domain: plan
---

# PVL Iteration 002 — private-beta-apply-form

## Input

Cycle 1 closed 8 gaps and the plan validated clean. An **independent adversarial
verifier** (spawned in parallel, instructed to REFUTE and to ignore the known 8)
then found 3 new EXECUTE-blocking FAILs, 3 CONCERNs, and 6 NITs.

This is the single most important data point of the run: a plan that had just
passed a full V1–V7 validation still contained three blocking defects. Repo memory
already records that single-pass PVL misses defects an external refuter catches —
this cycle is a second confirmation.

## FAILs closed

| ID | Defect | Why it mattered |
|---|---|---|
| A | Invite email links to `/signup?invite=…`; that page's `router.replace("/sign-up")` drops the query. Only writer of `localStorage["beam_invite"]` reads `window.location.search`, empty by then. | The token never reached storage on the **primary path** (real invite-email click). Consume no-ops, `used_at` stays NULL forever, AC-13 one-use enforcement never engages end-to-end, and gate F5 was vacuous (NULL in every scenario). Validation cycle 1 confirmed the F.1 trace without tracing the URL the email actually sends. |
| B | Four uninventoried account-creation CTAs in `pricing/page.tsx` (96, 102, 134, 280) on a public, sitemapped (priority 0.8) route. | Post-flip the highest-traffic conversion surface routes users into Clerk → 403 → error screen instead of `/apply`. |
| C | Gate F1 collects **zero** tests — proven live: `-m unit --collect-only` → "no tests collected (2 deselected)". No `pytestmark` on `test_invite_gate.py`. | F1 exits 5 against a correct implementation. Collaterally, the `-m unit` regression lane has been silently excluding this file all along, so the AC-8/AC-10 coverage the plan leaned on never ran in the standard lane. |

## Resolutions

- **A** — both fixes specified (query-preserving redirect + `invite_url` → `/sign-up`,
  the latter recorded as a narrow scoped SPEC deviation). F5 de-vacuumed to a
  positive control (`used_at` NULL → set) plus negative control. New gates F9, F10.
  New subsection F.6.
- **B** — all 4 CTAs repointed preserving `?plan=`; a 7th nullable column
  (`plan_interest`) folded into the **existing** Section A migration, Section B
  coercion/backfill, Section D admin column. New gates E4 (grep scoped to the whole
  `pricing/` dir, covering the untracked `layout.tsx`) and E5.
- **C** — `pytestmark` mandated in both the existing and the new test file;
  collection preconditions added to F1 and B1; new gate F11.

## CONCERNs closed

- **A (Gumroad):** `billing.py:662-676` mints a `User` for any purchasing email with
  no invite check; that email is then "existing" and the gate is structurally never
  reached. Refund doesn't undo it. **User decision: ACCEPTED** — buyers self-invite.
  Recorded in F.5 as a known accepted uncontrolled-account-creation path. `billing.py`
  explicitly not a Touchpoint.
- **B (transient 403):** fabricated `{clerk_user_id}@clerk.user` on Clerk-profile-fetch
  failure 403s a correctly approved applicant, and F.3 rendered it as terminal.
  Manual user-initiated "try again" added; auto-retry banned; server-side suffix
  recognition noted as G4-forbidden.
- **C (sibling collision):** attribution corrected — the real collision is
  `canary-onboarding_10-08-26` Phases 2-4 (which retire `onboarding-steps.js`), not
  `site-analysis-onboarding_13-08-26`. Cross-plan constraint recorded so it survives
  this plan's archival.

## NITs applied (orchestrator decisions)

Founders Wall consent copy corrected (surface deleted in `1b5e808`) · pinned email
rendered masked · E2 count made coherent (7) · `/apply` added to `sitemap.ts` ·
allowlist has no TTL/`used_at` check recorded in F.5 · reapplication invisibility
noted as SPEC-locked.

## Dominant defect class (three instances now)

**Gate commands that a correct implementation fails.** E1 (comment lines), A1
(whole-file grep hitting `downgrade()`), F1 (zero collection). Standing rule now in
the plan: verify a gate collects/matches what it claims *before* trusting it. An
execute-agent iterating to green against such a gate damages correct code.

## Scope delta

Blast radius 15 → 19 files. Two widenings need explicit ack at re-validate:
the `plan_interest` 7th column (a schema change driven by a CTA fix) and the
`waitlist.py` invite-email URL edit (recorded SPEC deviation).

## Validator state

`validate-plan-artifact.mjs` → 0 failures, 0 warnings (736 lines).

## Next step

Re-spawn vc-validate-agent from V1 against the twice-supplemented plan.
