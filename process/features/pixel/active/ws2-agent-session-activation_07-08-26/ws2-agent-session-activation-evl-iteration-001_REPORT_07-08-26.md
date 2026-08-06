---
name: ws2-agent-session-activation-evl-iteration-001
description: EVL cycle 1 — webkit pointer-entropy gate failure; possible Safari false-positive risk, not just test scoping
date: 2026-08-07
metadata:
  node_type: report
  type: evl-iteration
  iteration: 1
  domain: tests
  plan: process/features/pixel/active/ws2-agent-session-activation_07-08-26/ws2-agent-session-activation_PLAN_07-08-26.md
---

# EVL Iteration 001 — WS2 Agent-Session Activation

**Cycle:** 1 of 10 (cap)
**Trigger:** independent `vc-tester` EVL confirmation run reported 1 failing gate
**Loop driver:** orchestrator

## What EVL reproduced exactly

Every numeric claim in the execute report was independently reproduced:

| Gate | Result |
|---|---|
| `test_pixel.py` | 33 passed |
| size-gate combo | 34 passed |
| `test_ws2_session_classifier.py` + `test_ws2_zero_import.py` | 33 passed |
| `test_agent_origin_exclusion.py` + `test_visibility_only_flags_no_leak.py` | 59 passed |
| `test_agent_sig_ingest_boundary.py` | 9 passed |
| Full unit lane | **2015 passed, 2 skipped, 0 failed** |
| Web `tsc --noEmit` | exit 0 |
| Pixel size (gate's own `gzip.compress`) | 14070B raw / **5959B gzip**, 41B headroom |
| Alembic | single head `c9f4a7b31e85`; offline `--sql` clean both directions over `a4f2b8c15d70:c9f4a7b31e85` |
| Pixel e2e, chromium-only | 18 passed |

Additional independent confirmations:

- `identity_classification.py` **byte-unchanged** (`git diff` empty), signature still 3 parameters.
  True call-site count is **5**, not the plan's 3 — `campaigns.py`, `campaign_sender.py`,
  `csv_exporter.py`, `outcome_digest.py`, `hot_alert.py`. All 5 byte-unchanged. Confirms
  execute-agent's correction, refutes the plan's number.
- **G7 structurally intact**: `AS` collector assigned at `tracker.js:528`, strictly after the
  `GATED`/`consentDecision` setup (L507-510). `pushEvent` only *calls* `AS` at runtime, so
  hoisting cannot leak. `flush()`'s `consentBlocked()` guard (L308) unchanged.
- `tracker.js:4` `navigator.webdriver` early-return **deleted**, not commented out.
- The AC-7 `mode="before"` sanitizer fix is real and correctly placed: `isinstance` guard,
  5-key whitelist, bounded/coerced scalars, never raises.
- Docker genuinely unavailable (`docker info` fails) — the Docker-gated known-gaps are legitimate,
  not convenience skips.

## The failing gate

The validate-contract's literal AC-3 command is `npx playwright test e2e/agent-sig.spec.ts` with
**no `--project` flag**. Run as written it executes across all 3 configured projects and **1 of 12
fails**:

```
[webkit] pointer movement flips the entropy proxy off its agent-like default
  expected p === 1, got p === 0
```

Execute-agent's reported "4 passed" was **chromium-only** (4 tests × 1 project) — not the literal
contract command. That is the reporting gap EVL exists to catch.

## Why this is not obviously "just webkit flakiness"

EVL noted a **pre-existing, unrelated** spec (`per-site-config.spec.ts`) also fails on webkit in
this sandbox, and `apps/pixel/playwright.config.ts:8-11` already documents webkit/firefox as a
sandbox known-gap when binaries are not cached. Both point toward environment flakiness.

**But the failure mode has a real product consequence if it is genuine.** The collector is:

```js
document.addEventListener("pointermove", function() { APM = 1; }, { once: 1, passive: 1 });
```

`p` (the `APM` entropy proxy) defaults to `0` = agent-like, and flips to `1` when a pointer moves.
If WebKit does not fire `pointermove` for this listener, then **every real human Safari session
reports `p = 0` permanently** — the agent-like value. Stage 2's AND-gate would then see
low-pointer-entropy on all Safari traffic, exactly the false-positive class that drove D1 to
visibility-only in the first place.

So the two candidate diagnoses have very different consequences:

| Diagnosis | Consequence |
|---|---|
| Sandbox binary/flakiness | Test-scoping issue. Scope to `--project=chromium`, document the webkit leg as a known-gap matching the config's existing precedent |
| Real WebKit `pointermove` gap | **Product defect.** All Safari humans read as agent-like. Needs a fallback (e.g. also bind `mousemove`) before this ships, flag-off or not |

Distinguishing these is cheap and must be done before EVL closes. Closing on the assumption of
flakiness without evidence would ship the second case silently.

## Routing

One EVL cycle opens. `vc-execute-agent` (supplement mode) is scoped to exactly this gate:
diagnose which of the two cases holds, then either fix the listener or scope the command and
document the known-gap — with the evidence recorded either way.

No other gate is in scope. All others confirmed green.

## Resolution — neither (A) nor (B): a third cause

The scoped fix cycle root-caused it to a **Playwright harness transport blind spot**. The product
is correct on every engine.

**(A) ruled out:** `--project=webkit` alone → **3 of 4 tests passed**, only the pointer assertion
failed. A missing/uncached binary fails everything, not one assertion. WebKit launches and drives
input fine — the dead-centre *click* test passes on it.

**(B) ruled out** by three escalating probes:

1. WebKit does fire `pointermove` — 2 hits on `page.mouse.move`.
2. Pre-load registration using the tracker's exact numeric options `{ once: 1, passive: 1 }` fires
   too — options parsing and timing are fine.
3. Replicating AC-3 verbatim with an independent counter: `pointermove` fired **twice** in webkit,
   yet webkit captured only **2 ingest calls** vs chromium's **3**. The signal flipped; there was
   simply no carrier event to observe it on.

**Root cause:** `tracker.js`'s `flush()` uses a readable XHR only for the **first** flush of a
session and `navigator.sendBeacon` for every flush after. `page.route` intercepts `sendBeacon` in
chromium but **not** in webkit/firefox. So webkit recorded one ingest call for the whole session
and `sigs().at(-1)` kept returning the stale pre-move signal.

Confirmed by stubbing `sendBeacon → false`: `p` flips to `1` on webkit **and** firefox, identical
to chromium. **No Safari false-positive risk.** The product concern that justified this cycle is
retired on evidence, not assumption.

## Fix applied

One file — `apps/pixel/e2e/agent-sig.spec.ts`: a `test.beforeEach` init script forcing
`sendBeacon` to return false so `flush()` falls through to its own XHR path. Same payload, same
`_asig`, now observable. Shared `e2e/harness.ts` deliberately untouched.

Chosen over scoping to `--project=chromium` because it keeps the contract command literal **and**
gains real webkit+firefox coverage that was previously silently vacuous.

| Gate | Result |
|---|---|
| `npx playwright test e2e/agent-sig.spec.ts` (literal, no `--project`) | **12 passed** (4 × 3 engines) |
| `pytest tests/unit/test_pixel.py tests/unit/test_pixel_fingerprint.py` | **77 passed** |
| Pixel size (`gzip.compress`) | 14070B raw / **5959B gzip**, **41B headroom** — before == after |

**Zero bytes spent.** No product code changed during this cycle; `apps/pixel/src/` is byte-identical
to the EVL baseline. No new listener added.

## New gap found — reported, not fixed (out of scope)

Every **other** pixel e2e spec that asserts on post-first-flush batches is **silently vacuous on
webkit/firefox** for the same reason: it observes only the first XHR batch, because every
subsequent flush goes out via an un-interceptable `sendBeacon`. `agent-sig.spec.ts` is now the only
immune spec.

Candidate fix: lift the `sendBeacon` stub into `harness.ts`'s `interceptIngest()`. Left alone here
because it changes transport behaviour for ~13 specs — a separate, deliberate change.

This means the pixel suite's cross-browser coverage has been **weaker than its green checkmarks
implied** for some time. Worth a follow-up on its own merits, independent of WS2.
