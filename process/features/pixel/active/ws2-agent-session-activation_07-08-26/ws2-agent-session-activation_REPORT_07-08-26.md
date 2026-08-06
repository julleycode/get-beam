---
phase: ws2-agent-session-activation-evl-supplement-1
date: 2026-08-07
status: COMPLETE
feature: pixel
plan: process/features/pixel/active/ws2-agent-session-activation_07-08-26/ws2-agent-session-activation_PLAN_07-08-26.md
---

# EXECUTE supplement — EVL cycle 1, AC-3 webkit pointer gate

**TL;DR** Neither diagnosis (A) nor (B) as framed. The real cause is a **third
thing**: a Playwright harness transport limitation. `page.route` does not
intercept `navigator.sendBeacon` in webkit/firefox, and `tracker.js` uses XHR
only for the *first* flush of a session and sendBeacon for every flush after.
So on webkit/firefox every post-first batch was invisible to the recorder and
`sigs().at(-1)` returned the stale pre-interaction signal. **The product is
fine — `p` flips to 1 on webkit and firefox exactly as on chromium.** Fixed in
the spec only; the literal contract command is now 12/12 green.

## What Was Done

### Evidence that ruled out (A)

Ran `--project=webkit` alone: **3 of 4 tests passed**, only the pointer
assertion failed. A missing/broken binary fails everything, not one assertion.
Webkit launches and drives input fine (the dead-centre *click* test passes).
(A) is dead.

### Evidence that ruled out (B)

Three probes, escalating:

1. Post-load `document.addEventListener("pointermove", …)` in webkit →
   `pointermove: 2, mousemove: 2`. WebKit fires the event.
2. Pre-load registration via `addInitScript`, using the tracker's exact
   numeric options `{ once: 1, passive: 1 }` → fired. Numeric-truthy options
   parse correctly in WebKit; registration timing is not the issue.
3. Replicated the AC-3 flow verbatim with instrumentation:

   | Engine | events captured | last `_asig` |
   |---|---|---|
   | webkit | `pageview`, `form_email_capture` | `p:0` (stale) |
   | chromium | `pageview`, `form_email_capture`, `form_email_capture` | `p:1` |

   An independent counter showed `pointermove` fired **twice in webkit**. The
   signal flipped; there was simply no carrier event to observe it on.

### Root cause

`apps/pixel/src/tracker.js` `flush()`:

```js
if ((onUnload || !firstFlush) && navigator.sendBeacon &&
    navigator.sendBeacon(ENDPOINT, new Blob([payload], { type: "text/plain" }))) {
```

First flush → readable XHR (intercepted by `page.route`). Every later flush →
`sendBeacon`, which `page.route` intercepts in chromium but **not** in
webkit/firefox. Webkit therefore recorded exactly one ingest call for the whole
session. `captureEmail`'s `_sent[email]` dedupe was not involved — the two probe
emails differ.

### Confirmation

Stubbing `navigator.sendBeacon` to return `false` makes `flush()` fall through
to its own XHR path — same payload, same `_asig`:

| Engine | last `_asig` with sendBeacon stubbed |
|---|---|
| webkit | `{w:false,h:false,p:1,d:0,c:0}` |
| firefox | `{w:false,h:false,p:1,d:0,c:0}` |
| chromium | `{w:false,h:true,p:1,d:0,c:0}` |

**No Safari false-positive risk. The pointer-entropy proxy is engine-agnostic.**

### The change

One file: `apps/pixel/e2e/agent-sig.spec.ts` — a `test.beforeEach` adding an
init script that forces `navigator.sendBeacon` to return `false`, with a comment
recording the reasoning. Scoped to this spec only; the shared `e2e/harness.ts`
is untouched so no other spec's transport behavior changes.

This is strictly better than the fallback of scoping AC-3 to
`--project=chromium`: it keeps the contract command literal *and* gains real
webkit + firefox coverage that was previously silently vacuous.

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| AC-3 (literal contract, no `--project`) | `npx playwright test e2e/agent-sig.spec.ts` | **12 passed** (4 tests x 3 engines) |
| Pixel unit + size gate | `.venv/bin/python3.11 -m pytest tests/unit/test_pixel.py tests/unit/test_pixel_fingerprint.py -q` | **77 passed** |
| Pixel size budget | `gzip.compress` on `tracker.min.js` | 14070B raw / **5959B gzip**, 41B headroom — unchanged |

## Plan Deviations

None. No product code touched; no byte budget consumed; no listener added.

## What Was Skipped or Deferred

- No tracker source change — `git diff` on `apps/pixel/src/` is byte-identical
  to the EVL baseline. The 41B headroom was never spent.
- No migration authored (none needed; alembic single head `c9f4a7b31e85`).
- Deliberately left alone: the pre-existing unrelated webkit failure in
  `per-site-config.spec.ts`, all other uncommitted work in the tree, and every
  settled decision D1-D4 / E1-E9.

## Test Infra Gaps Found

**New, reported not fixed (out of scope):** every other pixel e2e spec that
asserts on post-first-flush batches is **silently vacuous on webkit/firefox** —
it observes only the first XHR batch and can pass without proving anything about
later ones. `agent-sig.spec.ts` is now the only spec immune. Candidate follow-up:
lift the sendBeacon stub into `e2e/harness.ts` `interceptIngest()` so all specs
get full-session observability. Not done here — it changes transport for ~13
other specs and is outside this cycle's single-gate scope.

## Forward Preview

- **Test Infra Found:** sendBeacon/`page.route` webkit+firefox blind spot (above).
- **Blast Radius Changes:** none — `apps/pixel/e2e/agent-sig.spec.ts` only.
- **Commands to Stay Green:** `npx playwright test e2e/agent-sig.spec.ts` (from
  `apps/pixel/`); `.venv/bin/python3.11 -m pytest tests/unit/test_pixel.py
  tests/unit/test_pixel_fingerprint.py -q` (from repo root, no `-m unit`).
- **Dependency Changes:** none.

## Closeout Packet

- **Selected plan:** `ws2-agent-session-activation_PLAN_07-08-26.md`
- **Finished:** the one failing EVL gate, root-caused and resolved.
- **Verified:** AC-3 literal command 12/12; pixel units 77/77; size budget unchanged.
- **Unverified:** independent vc-tester re-confirmation (orchestrator-owned).
- **Classification:** `Keep in active/testing` pending EVL re-confirmation.
