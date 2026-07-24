---
name: plan:handoff-phase-04-watermark-feasibility
description: "Handoff Detection — Phase 04: citation-watermark feasibility probe, gated implementation (H4)"
date: 23-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: phase-04
---

# Phase 04 — Citation-Watermark Feasibility (H4)

**Program:** handoff
**Umbrella plan:** process/features/evallayer/active/handoff_23-07-26/handoff-umbrella_PLAN_23-07-26.md
**SPEC:** process/features/evallayer/active/handoff_23-07-26/handoff_SPEC_23-07-26.md (AC-H4-1, AC-H4-2)
**Phase status:** ✅ VALIDATED (Gate: CONDITIONAL — 0 FAILs, security concern fixed in plan text this pass, 2 named accepted known-gaps; see Validate Contract)
**Report destination:** process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_REPORT_23-07-26.md (flat in the program task folder)

---

## PLAN-SUPPLEMENT Note (written by vc-validate-agent, 24-07-26)

The PLAN-SUPPLEMENT agent (Step 3, plan-agent supplement mode) died mid-write twice on API
errors before it could commit the LOCKED PREP design to this file. Per orchestrator instruction,
vc-validate-agent wrote the missing content below directly (plan-write access, matches prior-phase
precedent of validate-agent fixing plan text at PVL — see H3's PVL confirmation note in the
blast-radius registry). This note records that provenance so the phase report can cite it.

The LOCKED design below resolves RESEARCH (test-page hosting = new `/pricing-overview` route,
reusing existing `llms.txt`/`sitemap.ts` "public Next.js Route Handler" pattern; no H1 event-tagging
reuse needed) and INNOVATE (marker scheme, probe page shape) — Steps 1 and 2 of the Phase Loop
Progress are marked done below on that basis. The live-provider dispatch (Step B) is untouched and
remains the hard stop.

---

## Purpose

Answer, honestly and cheaply, whether a Beam-controlled query-string marker survives into an AI
agent's returned citation link — BEFORE committing to building any watermarking mechanism. This
phase is a manual-first, double-opt-in live probe (VC-FEASIBILITY-PROBE-NEEDED, cost-class
`needs-live-provider`), not a normal implementation phase. "Done" for H4 means the VERDICT is
recorded — regardless of outcome. Implementation is a strictly separate, gated sub-scope that only
activates on a VIABLE verdict plus explicit user sign-off.

The PREP sub-scope (building the probe page itself) IS ordinary, autonomous, additive code — it is
gated only by "the page must exist and be deployed before dispatch," not by opt-in. Only the DISPATCH
(Step B: a founder asking a live AI agent to browse the page) requires double opt-in.

---

## Entry Gate

- Loosely depends on Phase 1 (H1) only if the probe reuses H1's event-tagging infrastructure for
  the Beam-owned test page — **RESOLVED at PLAN-SUPPLEMENT: no reuse needed.** The probe page is a
  plain public Route Handler (mirrors `llms.txt/route.ts` and `sitemap.ts`), not an event-tagged
  surface. H1 dependency is dropped.
- No hard phase dependency otherwise — this probe runs independently of H2/H3.
- **HARD STOP regardless of ordering:** the live-provider probe dispatch always requires explicit
  double opt-in from the user before it runs (SPEC Constraint 7). This is never bypassed under
  `/goal` autonomous execution. The PREP work below (route + middleware) has standing autonomous
  EXECUTE consent per the AUTOPILOT CONTEXT for this run — dispatch does not.

---

## Blast Radius

**PREP phase (additive-only, autonomous, no opt-in required):**
- `apps/web/src/app/pricing-overview/[t]/route.ts` (new — tokenized probe page, `force-dynamic`
  Route Handler returning HTML; mirrors `apps/web/src/app/llms.txt/route.ts` shape)
- `apps/web/src/app/pricing-overview/route.ts` (new — bare-path handler: mints a fresh token and
  302-redirects to `/pricing-overview/{token}`)
- `apps/web/src/middleware.ts` (additive, 1 line — add `"/pricing-overview(.*)"` to the
  `isPublicRoute` matcher array, same pattern as the existing `.well-known` entry; **this is the
  silent-failure trap** — without it, Clerk 302s every request to `/pricing-overview/*` to
  `/sign-in` and the probe fails invisibly)
- `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_FEASIBILITY_{date}.md`
  (new VERDICT artifact, written by vc-debugger per the `vc-feasibility-test` playbook — DISPATCH
  phase only, not PREP)

**Explicitly NOT touched (confirmed at PLAN-SUPPLEMENT):**
- `apps/web/src/app/robots.ts` — unchanged (no robots.txt disallow needed; page relies on
  `noindex` meta + tokenized URL for discoverability control, not robots exclusion)
- `apps/pixel/` — unchanged (URL capture is free/ambient; the pixel is foreign-owned by a
  concurrent session — `first-party-capture_24-07-26` — and out of scope here)
- No new API route, no schema change, no auth change

**Conditional implementation phase (ONLY if VERDICT = VIABLE + explicit user sign-off):**
- watermark-generation logic (location TBD — depends entirely on the probe's findings about what
  survives)
- citation-link parsing/attribution extension (location TBD)
- NOTE: this sub-scope has NO planned file list here because it cannot be planned before the
  probe's VERDICT exists — if VIABLE + sign-off occurs, a NEW plan must be written (either as a
  supplement to this phase or a follow-up phase, per the PLAN-SUPPLEMENT step) before any
  implementation checklist item is executed.

**Registry cross-check:** disjoint from H1/H2/H3 (confirmed in
`phase-blast-radius-registry.md` §Phase 4). `apps/web/src/middleware.ts` has no other in-flight
claimant in the registry — no shared-file coordination needed.

---

## Implementation Checklist

### Step A — PREP: probe page (LOCKED design, additive, autonomous)

- [ ] A1. Create `apps/web/src/app/pricing-overview/[t]/route.ts`:
  - `export const dynamic = "force-dynamic";`
  - `GET(req, { params: { t } })` returns an `NextResponse`/`Response` with
    `Content-Type: text/html; charset=utf-8`.
  - HTML body is a REAL condensed Beam pricing/product summary, values hand-synced from
    `apps/web/src/app/pricing/page.tsx` (drift risk noted below, same pattern as the
    JSON-LD-static-file precedent):
    - Free — $0/mo — 10 identified visitors/mo
    - Pro — $19/mo ($15/mo billed yearly) — 50 identified visitors/mo
    - Max — $49/mo ($39/mo billed yearly) — unlimited identified visitors
  - `<title>` + `<meta name="description">` summarizing Beam + pricing.
  - `<link rel="canonical" href="https://getbeam.fyi/pricing-overview/{t}">` — **the tokenized
    canonical IS the experiment**: this is the exact marker whose survival into a citation link
    the probe measures.
  - `<meta name="robots" content="noindex, follow">`.
  - 1-2 self-links in the page body that also carry the token (e.g. the canonical URL repeated as
    an `<a href>`), so any crawler/agent that extracts links (not just canonical) also encounters
    the marked URL.
  - **No UA-conditional branching of any kind** — every requester (browser, curl, AI agent
    fetcher) gets byte-identical HTML. This is a hard SPEC boundary (no cloaking), and it also
    means the probe measures the real citation pipeline, not a special-cased one.
  - **[PVL security fix, applied in plan text this pass] Validate `params.t` before using it.**
    The token is interpolated into an HTML attribute (`href="…/{t}"`) and link text — an
    unvalidated path segment reflected into HTML is a classic reflected-XSS vector (OWASP
    A03:2021-Injection / STRIDE Tampering). Fix: reject the request before any interpolation if
    `t` does not match `/^p[0-9a-z]+$/` (the exact charset the mint function in A2 produces) —
    call Next.js `notFound()` (404) for anything else. Because only pre-validated safe strings
    reach the template after this check, no separate HTML-escaping step is needed. This also
    means the page never reflects arbitrary attacker-supplied strings, closing the injection
    vector at the input boundary rather than the output boundary.
- [ ] A2. Create `apps/web/src/app/pricing-overview/route.ts` (bare path, no token segment):
  - `export const dynamic = "force-dynamic";`
  - `GET(req)` mints a fresh token — self-describing scheme: `"p" + base36(unix-seconds)` (e.g.
    `p1abc2xy`) — and returns a 302 redirect to `/pricing-overview/{token}`.
  - Token is self-describing by design: decoding it (strip leading `p`, `parseInt(rest, 36)`,
    multiply by 1000) recovers the exact mint time. **No server-side logging is needed** — the
    token found in a returned citation link is sufficient to know when that particular fetch was
    served, which is the only observability this experiment requires. **Decode is a manual/optional
    analysis step performed by a human or vc-debugger during Step C1 if useful — it is NOT a
    required code path.** Do not add a `decodeToken()` function to the codebase (YAGNI) unless a
    later phase actually needs it; this keeps the PREP blast radius free of unproven/unused code.
- [ ] A3. Add `"/pricing-overview(.*)"` to the `isPublicRoute` matcher list in
  `apps/web/src/middleware.ts` (alongside the existing `/.well-known/(.*)` entry — same rationale:
  a public, unauthenticated agent-facing surface that must never 302 to `/sign-in`).
- [ ] A4. Confirm which live AI agent(s) the founder will manually query in Step B (ChatGPT is the
  default per orchestrator instruction; Perplexity/Claude/Copilot are backlog follow-ups, not
  in scope for this probe run).

### Step B — Dispatch (hard stop — requires explicit double opt-in)

- [ ] B1. Orchestrator surfaces `VC-FEASIBILITY-PROBE-NEEDED: citation-watermark survival —
      cost-class: needs-live-provider` per `orchestration.md`
      §VC-FEASIBILITY-PROBE-NEEDED Signal Routing. This ALWAYS pauses for explicit double opt-in
      — never auto-granted under `/goal`, even though PREP (Step A) has standing autonomous
      consent.
- [ ] B2. **Deploy prerequisite:** the PREP route must be live on `getbeam.fyi` (founder-controlled
      deploy step — outside this repo's automated scope) before dispatch.
- [ ] B3. On opt-in: founder pastes the following prompt into ChatGPT (or the confirmed agent from
      A4): *"Browse https://getbeam.fyi/pricing-overview and summarize Beam's pricing. Please cite
      your source."*
- [ ] B4. Founder pastes back the citation URL the agent returns (plus approximate ask time, for a
      sanity cross-check against the token's encoded mint time — informational only, not required
      for the verdict).
- [ ] B5. Optional secondary evidence: founder clicks the returned citation link — the Beam pixel
      captures the resulting page hit (path `/pricing-overview/{token}` + `ai_source=chatgpt` via
      the existing AI-referral classifier) as a corroborating signal, not the primary verdict input.

### Step C — Verdict

- [ ] C1. `vc-debugger` writes the VERDICT artifact to
      `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_FEASIBILITY_{date}.md`
      with an explicit `VIABLE` / `NOT-VIABLE` / `INCONCLUSIVE` keyword and the 3-part design
      constraint (what this licenses / what this forbids / what remains uncertain). Analysis rule:
      token present verbatim in the returned citation URL → VIABLE; token stripped/transformed →
      NOT-VIABLE; agent did not fetch or did not cite → INCONCLUSIVE (retry guidance: re-issue B3
      with a more explicit "cite your source with a URL" instruction).
- [ ] C2. Record the actual resolved `## Probe Cost Class` in the VERDICT (confirming
      `needs-live-provider` was the correct classification, per `orchestration.md`'s cost-class
      gate resolution step).

### Step D — Conditional implementation gate

- [ ] D1. If VERDICT = `NOT-VIABLE` or `INCONCLUSIVE`: phase is COMPLETE. No production
      watermark-write code is written. Program closeout confirms no watermark-write code path
      exists (AC-H4-2).
- [ ] D2. If VERDICT = `VIABLE`: STOP. Do not implement automatically. Surface the VERDICT to the
      user and request explicit sign-off for production rollout, per SPEC's US7/AC-H4-2 gating
      language ("even then requires explicit user sign-off before any production rollout, never
      automatic"). This gate is restated verbatim here because a PASS/CONDITIONAL validate-contract
      on the PREP work does NOT authorize skipping it.
- [ ] D3. If sign-off is granted: a NEW implementation checklist must be written (via
      PLAN-SUPPLEMENT to this phase or a new follow-up phase plan) before any code is written —
      this checklist does not exist yet and is intentionally not pre-authored here, since it
      depends entirely on what the VERDICT's design constraint licenses/forbids.

---

## Founder Instructions (paste-able)

Copy/paste block for the human dispatch step (Step B) — nothing here is automatable:

```
1. Confirm the pricing-overview page is deployed and reachable:
   https://getbeam.fyi/pricing-overview  (should 302 to a /pricing-overview/{token} URL)

2. Open ChatGPT (or your confirmed agent) and paste:
   "Browse https://getbeam.fyi/pricing-overview and summarize Beam's pricing.
    Please cite your source."

3. Note the time you asked (rough — for sanity-checking against the token, not required).

4. Copy the exact citation URL the agent returns (if any) and paste it back here.

5. Optional: click the citation link yourself — this generates a secondary pixel signal
   (path + ai_source=chatgpt) but is not required for the verdict.
```

Analysis (performed by vc-debugger in Step C1):
- Token present verbatim in the citation URL → **VIABLE**
- Token stripped or transformed → **NOT-VIABLE**
- No fetch, or no citation surfaced → **INCONCLUSIVE** (retry with a more explicit citation ask)

---

## Exit Gate

```bash
# PREP gate (Step A) — run before Step B dispatch is even requested
cd apps/web && npm run build
# Expected: exit 0 (route files compile, no type errors)

grep -q "rel=\"canonical\"" apps/web/src/app/pricing-overview/\[t\]/route.ts && echo "canonical: present"
grep -q "noindex" apps/web/src/app/pricing-overview/\[t\]/route.ts && echo "noindex: present"
grep -q "pricing-overview" apps/web/src/middleware.ts && echo "middleware exemption: present"
grep -qE "notFound\(\)|\^p\[0-9a-z\]" apps/web/src/app/pricing-overview/\[t\]/route.ts && echo "token validation: present"
# Expected: all four lines print

# Verdict gate (Step C) — only relevant after Step B dispatch
grep -E "VIABLE|NOT-VIABLE|INCONCLUSIVE" process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_FEASIBILITY_*.md
# Expected: exactly one recorded keyword

grep -rn "watermark" apps/api/ apps/web/src/ 2>/dev/null | grep -v test
# Expected (unless VIABLE + sign-off + follow-up implementation has occurred): no production
# watermark-write code path found
```

- Step A complete: build green, all 3 grep checks pass, route deployed by founder (outside repo
  scope)
- Step B-C complete: VERDICT artifact exists with a recorded keyword and the 3-part design
  constraint
- If VERDICT != VIABLE: phase is complete, no implementation attempted (Step D1)
- If VERDICT == VIABLE: explicit user sign-off recorded before any implementation checklist is
  authored (Step D2/D3)
- Phase report written to report destination above, regardless of verdict outcome

---

## Blockers That Would Justify BLOCKED Status

- User does not grant double opt-in for the live-provider probe — this is NOT a blocker in the
  traditional sense; the phase remains PENDING/paused (not BLOCKED) until the user opts in or
  explicitly defers the probe to backlog. **PREP (Step A) is unaffected and can still ship — only
  Step B/dispatch pauses.**
- The `pricing-overview` route fails to deploy on `getbeam.fyi` (founder-side, outside repo
  scope) — genuine blocker, escalate to user for an alternative hosting/deploy decision
- VERDICT = VIABLE but user declines sign-off for production rollout — phase is still COMPLETE
  per AC-H4-2 ("done" means VERDICT recorded, not that watermarking ships); this is NOT a blocker,
  it is an accepted terminal state for this phase

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop). **This
phase's PVL step is expected to itself trigger `VC-FEASIBILITY-PROBE-NEEDED` for the Step B/C
dispatch instructions — this is normal for H4, not an error; the PREP checklist (Step A) is
ordinary code and does NOT require a probe.**

- [x] 1. RESEARCH — test-page hosting resolved: new `/pricing-overview` route (no H1 event-tagging
      reuse needed); live-agent probe mechanics confirmed (a manual ChatGPT browse+cite request).
      Resolved via orchestrator-provided LOCKED design, written into this plan at PLAN-SUPPLEMENT.
- [x] 2. INNOVATE — marker scheme (`"p" + base36(unix-seconds)`, self-describing, no server log
      needed) and probe page shape (mirrors `llms.txt/route.ts`) decided. Decision Summary: chosen
      = query-string-free tokenized path segment (`/pricing-overview/{t}`) over a `?probe_id=`
      query param, because a path segment survives URL-canonicalization by search/AI crawlers more
      reliably than a query string (rejected alternative: `?beam_probe_id=<uuid>` — a query param
      is more likely to be stripped by a "clean URL" normalization step than a path segment).
      **Per orchestrator instruction, INNOVATE's `VC-FEASIBILITY-PROBE-NEEDED` was NOT re-triggered
      here for the page-shape decision itself — the LOCKED design already resolves it. The probe
      that IS still required (Step B/C, marker survival in a live citation) is unchanged and
      remains gated on double opt-in.**
- [x] 3. PLAN-SUPPLEMENT — plan-agent (via vc-validate-agent, see PLAN-SUPPLEMENT Note above) —
      phase plan updated with the confirmed PREP probe design (route, token, middleware, founder
      instructions, PREP-tier test gates).
- [x] 4. PVL — vc-validate-agent: full V1-V7 complete (24-07-26). Validate-contract records the
      PREP build as a normal fully-automated code gate (`npm run build` + 5 greps), and the Step
      B/C dispatch instructions as a separate Agent-Probe / needs-live-provider hard-stop entry.
      1 security CONCERN found and fixed in plan text this pass (reflected-XSS on `[t]`). Gate:
      CONDITIONAL (2 named, accepted known-gaps — see Validate Contract).
- [ ] 5. EXECUTE — Step A (PREP route + middleware) executed and gate-green; Step B (dispatch,
      requires opt-in) + Step C (VERDICT written) executed; Step D gate resolved.
- [ ] 6. EVL — confirm PREP build/greps green; confirm VERDICT artifact exists with a valid keyword
      (once dispatched); confirm no premature production implementation code was written.
- [ ] 7. UPDATE PROCESS — phase report written (recording the verdict outcome regardless of
      VIABLE/NOT-VIABLE/INCONCLUSIVE, or PREP-only status if dispatch is still pending opt-in),
      umbrella state updated, commit done.

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate
Contract` reads "(placeholder — vc-validate-agent writes this section before EXECUTE)",
orchestrator must spawn vc-validate-agent first. **The double-opt-in hard stop at Step B is
independent of and additional to the normal PVL gate — even a PASS validate-contract does not
authorize skipping the opt-in pause. PVL PASS/CONDITIONAL only licenses Step A (PREP) EXECUTE.**

---

## Touchpoints

- `apps/web/src/app/pricing-overview/[t]/route.ts` (new — tokenized probe page)
- `apps/web/src/app/pricing-overview/route.ts` (new — bare-path token mint + redirect)
- `apps/web/src/middleware.ts` (additive, 1 line — public-route exemption)
- `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_FEASIBILITY_{date}.md` (new VERDICT artifact — dispatch phase only)
- (conditional, only if VIABLE + sign-off) watermark-generation + citation-parsing code — not
  planned here, requires a follow-up plan

---

## Public Contracts

- **New public route, no API contract**: `GET /pricing-overview` and
  `GET /pricing-overview/{t}` return static HTML, no request body, no auth, no query-string
  parameters consumed beyond the path token itself. Not a data API — nothing to version.
- **Security boundary (PVL finding, fixed in plan text this pass)**: `{t}` is the one piece of
  external input this route accepts. It MUST be validated against `/^p[0-9a-z]+$/` and rejected
  (404 via `notFound()`) before any HTML interpolation — see Step A1. Without this check, an
  attacker-crafted token containing markup would be reflected unescaped into the HTML response
  (reflected XSS). No other input surface exists on this route.
- No schema changes, no auth changes, no billing/credit surface touched.
- Content is a hand-synced condensed copy of `apps/web/src/app/pricing/page.tsx` — **drift risk**:
  if pricing changes, this page will not auto-update (same known drift pattern as the homepage
  JSON-LD static file). Documented as a known-gap below, not blocking.
- (Conditional) any future watermark implementation would need its own Public Contracts section in
  a follow-up plan.

---

## Verification Evidence

**PREP tier (fully-automated, runs now):**

| Gate / Scenario | Strategy | Command | Proves |
|---|---|---|---|
| Route compiles, no type errors | Fully-Automated | `cd apps/web && npm run build` | Route files are syntactically/type-valid Next.js Route Handlers |
| Canonical link present with token var | Fully-Automated | `grep -q 'rel="canonical"' apps/web/src/app/pricing-overview/\[t\]/route.ts` | The tokenized-canonical marker mechanism exists in source |
| noindex meta present | Fully-Automated | `grep -q "noindex" apps/web/src/app/pricing-overview/\[t\]/route.ts` | Page is excluded from normal search indexing (SEO-safety boundary) |
| Middleware exemption present | Fully-Automated | `grep -q "pricing-overview" apps/web/src/middleware.ts` | The silent-failure trap (Clerk 302 to sign-in) is closed |
| Token validated before HTML interpolation | Fully-Automated | `grep -qE "notFound\(\)\|\^p\[0-9a-z\]" apps/web/src/app/pricing-overview/\[t\]/route.ts` | Reflected-XSS mitigation (PVL security fix) is present in source — unvalidated `params.t` is never reflected into the HTML response |

Failing stub:
```
test("should reject a non-token-shaped [t] segment with 404 before any HTML interpolation", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: token validation rejects malformed [t]")
})
```

**Dispatch tier (Agent-Probe, needs-live-provider, gated on double opt-in):**

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| VERDICT artifact exists with recorded keyword | Agent-Probe (cost-class: needs-live-provider) | AC-H4-1 |
| Program closeout manual review confirms no watermark-write code path exists unless VIABLE + sign-off on record | Agent-Probe | AC-H4-2 |

```bash
grep -E "VIABLE|NOT-VIABLE|INCONCLUSIVE" process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_FEASIBILITY_*.md
# Expected: exactly one recorded keyword
```

**Known-gap:** the token *mint* function (A2) has no dedicated automated unit test — `apps/web`
has no Vitest/Jest unit runner configured (confirmed via `process/context/tests/all-tests.md`;
only Playwright e2e + `next lint` exist for the web app). Coverage instead comes from: (1) the
`npm run build` type-check gate, (2) the grep structural checks above (including the new token-
validation check), (3) manual verification during the founder's live probe (an incorrectly-minted
token would fail the citation-URL match in Step C1 and surface as INCONCLUSIVE, not silently pass).
Decode is intentionally NOT implemented as code (see A2 YAGNI note) so there is no decode function
to leave untested. Resolution: accepted as known-gap — mint is a ~2-line pure transform with no
external I/O; a dedicated unit-test harness is not proportionate to add for this probe-only page.
If a JS unit runner is added to `apps/web` for other reasons later, this is a 5-minute backfill,
not a new investment.

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/evallayer/active/handoff_23-07-26/phase-04-watermark-feasibility_PLAN_23-07-26.md`
- Last completed step: PVL (Step 4) — validate-contract written, Gate: CONDITIONAL (accepted)
- Validate-contract status: written — see `## Validate Contract` below
- Next step: Spawn vc-execute-agent for Step A (PREP: route `[t]` handler → bare-path redirect
  route → middleware exemption → build + 5 grep gates). Step B (dispatch) stays gated on explicit
  double opt-in — surface `VC-FEASIBILITY-PROBE-NEEDED` and wait, regardless of this PVL gate.

---

## Test Infra Improvement Notes

- `apps/web` has no JS/TS unit-test runner (Vitest/Jest) — only Playwright e2e and `next lint`.
  Not a blocker for this phase (see Known-gap above), but worth flagging for the program closeout:
  any future pure-TS-logic phase in `apps/web` will hit the same gap.

---

## Validate Contract

Status: CONDITIONAL
Date: 24-07-26
date: 2026-07-24
generated-by: inner-pvl: phase-h4

Plan updates applied:
- PLAN-SUPPLEMENT content (Step 3) was missing entirely (dead PLAN-SUPPLEMENT agent, 2x API-error
  crash) — vc-validate-agent wrote the full LOCKED PREP design directly into the plan per
  orchestrator instruction (route `[t]` + bare-path redirect + middleware exemption + founder
  instructions + PREP-tier test gates). See "## PLAN-SUPPLEMENT Note" at top of plan.
- Security surface CONCERN found and fixed in plan text this pass: `params.t` was interpolated
  into HTML (canonical href + link text) with no validation — reflected-XSS vector
  (OWASP A03:2021-Injection). Fix: reject any `t` not matching `/^p[0-9a-z]+$/` via `notFound()`
  before interpolation (Step A1). Added a matching grep gate + Fully-Automated table row + TDD
  failing stub, and a Public Contracts note documenting the boundary.
- YAGNI clarification added: token *decode* is documented as a manual/optional analysis step for
  Step C1, not a required code path — closes a potential vacuous-green gap (no unimplemented
  "developed behavior" left uncovered) and keeps blast radius minimal.
- Known-gap note (token mint has no JS unit test — `apps/web` has no Vitest/Jest runner) reworded
  to match the decode-is-not-code clarification; resolution unchanged (accepted, backfillable).
- 0 FAILs, 0 unresolved CONCERNs remain after the above fixes.

Execute-agent instructions:
1. Sequence: `apps/web/src/app/pricing-overview/[t]/route.ts` (with token validation FIRST in the
   handler body, before any HTML string is built) → `apps/web/src/app/pricing-overview/route.ts`
   (bare-path mint+redirect) → `apps/web/src/middleware.ts` (1-line `isPublicRoute` addition) →
   run the PREP Exit Gate (build + 4 greps).
2. Do NOT implement a `decodeToken()` function — mint only (YAGNI, see A2 note). If a future phase
   needs decode, add it then with its own test.
3. Do NOT touch `apps/web/src/app/robots.ts` or any file under `apps/pixel/` — explicitly out of
   scope for this phase (see Blast Radius "Explicitly NOT touched").
4. Step B (dispatch) is a HARD STOP independent of this PVL gate — CONDITIONAL/PASS here licenses
   Step A (PREP) EXECUTE only. Do not proceed to Step B without the orchestrator surfacing
   `VC-FEASIBILITY-PROBE-NEEDED` and receiving explicit double opt-in, even under `/goal`.
5. If VERDICT (Step C) = VIABLE: STOP per Step D2 — do not write any watermark implementation code
   without a new PLAN-SUPPLEMENT/follow-up plan and explicit user sign-off.

Test gates (5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-H4-1 (PREP) | Probe page route compiles and is type-valid | Fully-Automated | `cd apps/web && npm run build` | A |
| AC-H4-1 (PREP) | Tokenized canonical link present in source | Fully-Automated | `grep -q 'rel="canonical"' apps/web/src/app/pricing-overview/\[t\]/route.ts` | A |
| AC-H4-1 (PREP) | noindex meta present | Fully-Automated | `grep -q "noindex" apps/web/src/app/pricing-overview/\[t\]/route.ts` | A |
| AC-H4-1 (PREP) | Middleware public-route exemption present | Fully-Automated | `grep -q "pricing-overview" apps/web/src/middleware.ts` | A |
| Security (PVL-added) | `[t]` validated / rejected before HTML interpolation | Fully-Automated | `grep -qE "notFound\(\)\|\^p\[0-9a-z\]" apps/web/src/app/pricing-overview/\[t\]/route.ts` | A |
| — | Token mint function correctness (round-trip) | Known-Gap (no JS unit runner in apps/web) | — | D |
| AC-H4-1 (dispatch) | Live citation link carries the marker | Agent-Probe (cost-class: needs-live-provider) | Founder-run ChatGPT probe per "Founder Instructions" | C (deferred to Step B, requires double opt-in) |
| AC-H4-2 | No production watermark-write code path exists unless VIABLE + sign-off | Agent-Probe | `grep -rn "watermark" apps/api/ apps/web/src/ 2>/dev/null \| grep -v test` (manual review) | A |

gap-resolution legend: A — proven now. C — deferred to Step B/dispatch (named later step in this
same plan, not a separate phase). D — backlog test-building stub (named residual; keep-active).

Legacy line form:
- PREP route/middleware: Fully-automated: `cd apps/web && npm run build` + 4 grep checks above |
  known-gap: token mint has no dedicated JS unit test (no Vitest/Jest runner in apps/web; documented)
- Dispatch/verdict: agent-probe: founder-run live ChatGPT browse+cite probe, cost-class
  needs-live-provider, gated on double opt-in (never auto-granted under `/goal`)

Dimension findings:
- Infra fit: PASS — plain Next.js Route Handler + middleware matcher addition; no container,
  port, or worker-lifecycle surface touched.
- Test coverage: PASS — PREP tier fully-automated (build + 5 greps + TDD stub), dispatch tier
  correctly Agent-Probe/needs-live-provider (not silently downgraded to known-gap); the one
  Known-Gap (token mint unit test) is a named, justified residual, not the sole proof for any
  in-scope behavior — net gate is not vacuously green.
- Breaking changes: PASS — additive only (2 new route files, 1 new line in middleware.ts); no
  existing route path collision (`apps/web/src/app/pricing-overview` confirmed absent before this
  plan); no schema/API/auth contract changes.
- Security surface: CONCERN → FIXED in plan text this pass — reflected-XSS via unvalidated `[t]`
  path segment; mitigated with strict-format validation + `notFound()` before interpolation, plus
  a dedicated grep gate and TDD stub.
- Section A (PREP: route/token/middleware) feasibility: PASS — edit targets confirmed absent
  (no collision), `apps/web/src/middleware.ts` isPublicRoute array confirmed at the exact insertion
  point (mirrors the `.well-known` entry pattern), `llms.txt/route.ts` confirmed as the shape
  precedent to mirror. Highest-risk edit: the `[t]` HTML interpolation (mitigated above) — sequence
  the validation check as the FIRST line inside the handler, before any template string is built.
- Section B/C/D (Dispatch/Verdict/Gate) feasibility: PASS — VERDICT artifact path pattern matches
  `vc-feasibility-test` playbook convention; hard-stop gate correctly independent of this PVL
  verdict; Step D1-D3 conditional-implementation gate is unambiguous and self-enforcing (no new
  code authored without a fresh plan + sign-off).

High-risk pack:
- Public surface: YES — this phase adds a new unauthenticated, publicly reachable route
  (`/pricing-overview` + `/pricing-overview/{t}`) and an additive change to the auth-routing
  trust boundary (`middleware.ts` `isPublicRoute` list). Classified under orchestration.md's
  "public API or external contract changes" + "permission/secret/trust-boundary logic" high-risk
  classes.
- Controls in place (why a full 5-artifact `vc-risk-evidence-pack` is not required for PREP itself):
  1. `noindex, follow` — page is deliberately excluded from normal search indexing; only reachable
     via the tokenized URL itself, not general crawl discovery.
  2. No-cloaking — byte-identical HTML for every requester; nothing UA-conditional to hide or
     exploit differently per caller.
  3. Additive-only middleware diff — 1 line added to an existing, already-reviewed pattern
     (`.well-known` precedent); no existing route's protection is removed or weakened.
  4. Token-format validation (this pass's fix) closes the one real input-injection surface.
  5. The genuinely irreversible/outward-facing action — a founder-initiated live query to a
     third-party AI agent, which cannot be un-asked — is Step B, and it is hard-gated on explicit
     double opt-in independent of this PVL gate, per SPEC Constraint 7.
- Recommendation: if EXECUTE wants a formal `vc-risk-evidence-pack` regardless, generate it at
  Step B (dispatch) time — that is the actual irreversible/outward-facing action — not for the
  PREP code, which is small, additive, mechanical, and covered by the fully-automated gates above.

Open gaps:
- Token mint function has no dedicated JS unit test (no Vitest/Jest runner in `apps/web`) —
  known-gap: documented, accepted, 5-minute backfill if a unit runner is added later for other
  reasons. Not a high-risk-class gap (pure ~2-line transform, no external I/O).
- Content drift risk: pricing values on this page are hand-synced from `pricing/page.tsx`, not
  computed — known-gap: documented as an accepted pattern (matches the existing homepage JSON-LD
  static-file precedent), not blocking this phase.

What this coverage does NOT prove:
- `npm run build` proves the route compiles and type-checks. It does NOT prove the HTML renders
  correctly in a real browser, that the pricing values are currently accurate vs `pricing/page.tsx`
  (hand-sync, no automated diff check), or that Next.js actually serves the route at runtime
  with the expected headers (that requires a running dev/prod server — not probed per policy, left
  to the founder's live-deploy confirmation in Step B2).
- The grep checks prove specific strings exist in source. They do NOT prove the middleware
  actually exempts the route at runtime (would require a running server + a real HTTP request —
  Hybrid-tier, not attempted here; the founder's Step B2 "confirm reachable" step is the de facto
  runtime check).
- The Agent-Probe dispatch gate proves ONE live citation outcome from ONE agent (ChatGPT, per A4).
  It does NOT prove generalization to Perplexity/Claude/Copilot/other agents — those are explicitly
  out of scope for this probe run (see A4), backlog candidates if VIABLE.
- No test proves the token-validation regex handles every conceivable malformed input beyond the
  structural grep check that the validation code exists — no fuzz/property test was added
  (disproportionate for a probe-only page; the format is narrow and self-generated).

Gate: CONDITIONAL (0 FAILs; concerns found this pass were fixed directly in plan text, not left
open; 2 named known-gaps remain, both documented with rationale, neither in a high-risk class
requiring Hybrid minimum)
Accepted by: session (autonomous, /goal execution) — accepted concerns: (1) token-mint known-gap
(no JS unit runner in apps/web), (2) pricing-content hand-sync drift risk. Both are named,
low-severity, non-high-risk-class residuals per the criteria above.
