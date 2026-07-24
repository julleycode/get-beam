---
phase: phase-04-watermark-feasibility
date: 2026-07-24
status: COMPLETE_WITH_GAPS
feature: evallayer
plan: process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_PLAN_23-07-26.md
---

# Phase H4 — Citation-Watermark Feasibility — EXECUTE Exit Summary (Step A / PREP only)

**Scope this pass:** Step A (PREP) ONLY. Step B (founder dispatch) is a HARD STOP — not attempted,
no dispatch automation added. Verdict (Step C) not written (requires dispatch). Phase remains
PENDING opt-in for Step B; PREP code is shipped and gate-green.

## What Was Done

- **`apps/web/src/app/pricing-overview/[t]/route.ts`** (new) — `force-dynamic` GET Route Handler.
  Validates `params.t` against `/^p[0-9a-z]+$/` and calls `notFound()` on mismatch as the FIRST
  action inside the handler (line 61-62), BEFORE any HTML string is built (line 65). Returns
  byte-identical `text/html` for every requester (zero UA branching). HTML carries: `<title>` +
  meta description, `<link rel="canonical" href="https://getbeam.fyi/pricing-overview/{t}">`,
  `<meta name="robots" content="noindex, follow">`, condensed real Beam pricing (hand-synced from
  `pricing/page.tsx` PLANS, drift risk commented), and 2 self-links in the body carrying the token.
- **`apps/web/src/app/pricing-overview/route.ts`** (new) — `force-dynamic` bare-path GET. Mints
  `"p" + base36(unix-seconds)` and 302-redirects to `/pricing-overview/{token}`. Mint only; no
  `decodeToken()` (YAGNI per plan A2).
- **`apps/web/src/middleware.ts`** (1 line) — added `"/pricing-overview(.*)"` to `isPublicRoute`,
  directly below the `/.well-known/(.*)` entry (mirrors that pattern exactly). Closes the
  silent-failure trap (Clerk 302 to `/sign-in`).

## Test Gate Outcomes

- `cd apps/web && npm run build` → exit 0. Both routes emitted: `/pricing-overview` (ƒ Dynamic) and
  `/pricing-overview/[t]` (ƒ Dynamic).
- `grep rel="canonical"` → present (tokenized canonical, `${token}` interpolated).
- `grep noindex` → present.
- `grep pricing-overview` in middleware.ts → present.
- `grep -E "notFound()|^p[0-9a-z]"` → present; validation at line 61-62 precedes HTML at line 65.
- UA-branching check (`grep -ic "user-agent|userAgent"` both route files) → 0 and 0.
- `.venv/bin/python -m pytest tests/unit -q` → 941 passed, 2 skipped, 1 failed. The single failure
  (`test_pixel.py::TestPixelSize::test_source_under_20kb`) is PRE-EXISTING and FOREIGN — the pixel
  is owned by the concurrent `first-party-capture_24-07-26` session (modified in git status). A pure
  `apps/web` addition cannot affect Python tests. No new failure caused by this change.

## What Was Skipped or Deferred

- **Step B (dispatch)** — HARD STOP. Requires double opt-in (`VC-FEASIBILITY-PROBE-NEEDED`,
  cost-class needs-live-provider). Never auto-granted under /goal. Also requires founder-side
  deploy of the route to `getbeam.fyi` (outside repo scope).
- **Step C (VERDICT artifact)** — depends on Step B; not written.
- **Step D (conditional implementation)** — no watermark-write code exists (correct; only licensed
  on VIABLE + explicit sign-off).

## Plan Deviations

None. Implemented exactly per Validate Contract Execute-agent instructions (sequence, token
validation first, no decodeToken, robots.ts/pixel untouched).

## Test Infra Gaps Found

- Token mint (A2) has no dedicated JS unit test — `apps/web` has no Vitest/Jest runner (accepted
  known-gap per validate-contract; covered by build type-check + grep + live-probe failure mode).
- Pricing values hand-synced from `pricing/page.tsx` — drift risk, no automated diff (accepted
  known-gap, matches homepage JSON-LD static-file precedent).

## Closeout Packet

- Selected plan: `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_PLAN_23-07-26.md`
- Finished: Step A (PREP) — 3 files, all PREP fully-automated gates green.
- Verified: build compiles, 5 grep structural gates, zero UA branching, XSS gate before HTML,
  pytest unit regression clean.
- Unverified (deferred, not blockers): runtime header serving + middleware runtime exemption
  (needs running server / founder deploy — Step B2 de facto check); live citation survival
  (Step B/C, needs-live-provider, double opt-in).
- Classification: **Keep in active/testing** — PREP is code-complete and gate-green, but the phase
  is not COMPLETE until the Step B/C verdict is recorded (or the probe is explicitly deferred to
  backlog by the user). Not archivable yet.
- Best next state: orchestrator surfaces `VC-FEASIBILITY-PROBE-NEEDED: citation-watermark survival
  — cost-class: needs-live-provider` and waits for user double opt-in. Do NOT auto-dispatch.

## Forward Preview

- **Test Infra Found:** no JS unit runner in `apps/web` (Playwright e2e + `next lint` only).
- **Blast Radius Changes:** 2 new route files under `apps/web/src/app/pricing-overview/`, 1 line in
  `apps/web/src/middleware.ts`. Additive; disjoint from H1/H2/H3.
- **Commands to Stay Green:** `cd apps/web && npm run build`; the 5 greps in the plan Exit Gate.
- **Dependency Changes:** none.
