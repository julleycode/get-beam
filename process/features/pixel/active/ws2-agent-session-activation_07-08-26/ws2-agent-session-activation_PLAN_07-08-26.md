---
name: plan:ws2-agent-session-activation
description: "Close the pixel's agentic-browser blindspot (delete tracker.js webdriver early-return), restore a byte-budgeted agent_sig signal after the consent gate, persist it, port WS2's classifier off its frozen-spec-by-example test suite, and wire it visibility-only into the dashboard"
date: 07-08-26
feature: pixel
phase: "n/a — single COMPLEX plan, not a phase program"
---

# WS2 Agent-Session Activation — PLAN (COMPLEX)

**Date**: 07-08-26
**Status**: DRAFT — pending VALIDATE (not yet user-confirmed as VERIFIED)
**Complexity**: COMPLEX

## Overview

Today an agentic browser session either vanishes entirely (`tracker.js:4`'s
`navigator.webdriver` early-return kills the whole bootstrap before consent/cookie/event flow
ever runs) or, if it doesn't set that flag, is recorded as an ordinary unlabeled human and burns
paid identity-resolution/enrichment budget while entering the outreach pool. A classifier that
would catch the second case (`ws2_session_classifier.py`) already exists on the unmerged branch
`feat/ws2-agent-session-classifier`, unit-tested and EVL-green, but is permanently dormant because
its only input (`agent_sig`) was never restored to the pixel after being reverted for byte-budget
reasons.

This plan closes that gap in 6 sequenced steps: delete the dead early-return, add a
budget-fitted `agent_sig` collector strictly after the consent gate, persist the field additively
at ingest, port the classifier (frozen-spec-by-example from the branch's test file, re-derived —
never merged/cherry-picked) against current `main`, wire the resulting flag visibility-only
(never touching `is_emailable_identity()`), and surface it as a dashboard badge.

**Decisions locked by INNOVATE (not re-litigated here):**

- **D1 — visibility-only emailability tier.** `is_agent_operated` behaves exactly like
  `Visitor.is_bot_suspect` (cadence-bot-flag): a flag set on `Visitor`/`IdentifiedVisitor`, read
  nowhere by `is_emailable_identity()`. `is_emailable_identity()` keeps its exact current 3-parameter
  signature — this plan does not add a 4th guard parameter (see the locked invariant at
  `apps/api/migrations/versions/f3a7c9e21b48_add_internal_traffic_damping.py:21`).
- **D2 — trimmed `agent_sig` shape.** Stage 1: `navigator.webdriver` boolean + UA-CH
  `HeadlessChrome` brand check. Stage 2 proxies, piggybacked onto the EXISTING click listener
  (tracker.js:632) — no new `addEventListener` call: (a) one boolean "no `pointermove` observed
  before first interaction" and (b) two integer counters (dead-center clicks / total clicks).
  Raising the gzip gate is last resort only, after measuring the trimmed shape and recording the
  real byte count.
- **D3 — line 4 deleted outright**, no replacement at that position. The whole `agent_sig`
  collection block sits AFTER the `GATED`/`consentDecision` assignment (tracker.js:507-508),
  making G7 compliance structural.
- **D4 — port, do not merge.** `feat/ws2-agent-session-classifier` is read via `git show` only,
  never checked out or merged (it drags in out-of-scope commit `c2f9bad`). The branch's
  `tests/unit/test_ws2_session_classifier.py` (quadrant matrix) and
  `tests/unit/test_ws2_zero_import.py` (AST import-isolation guard) are treated as a frozen
  spec-by-example: ported with import-path updates only, then the implementation is (re-)written
  to satisfy those exact assertions.

## Acceptance Criteria

This plan carries all 14 numbered Acceptance Criteria from the locked SPEC (`ws2-agent-session-activation_SPEC_07-08-26.md`, AC-1 through AC-14) unchanged. Each is mapped to an implementation step and a proving test gate in the traceability table immediately below, and repeated with full detail in the Verification Evidence section further down. AC-12/AC-13/AC-14 are Known-Gap/Agent-Probe by SPEC design and do not block this plan reaching `✅ VERIFIED` (see Phase Completion Rules and Known-Gaps).

## SPEC AC → Step → Test Gate Traceability

| AC | Step(s) | proven by | strategy |
|---|---|---|---|
| AC-1 | Step 1 | unit: bootstrap doesn't short-circuit on webdriver alone; consent gating unchanged | Fully-Automated |
| AC-2 | Step 1, Step 2 | unit: agent_sig collection code executes only after consentDecision/GATED resolution | Fully-Automated |
| AC-3 | Step 2 | `test_under_6kb_gzipped` (<6000) + `test_pixel.py` size gate (<6144), both green; recorded byte count | Fully-Automated |
| AC-4 | Step 3 | integration: ingest payload with agent_sig persists and round-trips | Fully-Automated (Docker-gated) |
| AC-5 | Step 4 | unit: sweep extracts + classifies against a fixture row with populated agent_sig (not None short-circuit) | Fully-Automated |
| AC-6 | Step 6 | manual visual check at the 3 confirmed inline badge sites (E4) | Agent-Probe (no component-render test infra in `apps/web` — see Test Infra Improvement Notes) |
| AC-7 | Step 3 | integration: ingest of agent-indicating payload still returns success, row written | Fully-Automated |
| AC-8 | Step 5 | unit: `is_emailable_identity()` unaffected by is_agent_operated/is_bot_suspect at all 3 call sites | Fully-Automated |
| AC-9 | Step 5 | unit: is_bot_suspect / is_agent_operated do NOT trip is_emailable_identity() (new negative test) | Fully-Automated |
| AC-10 | Step 0, Step 3 | `alembic heads` single-head re-check immediately pre-authoring; offline `--sql` validation | Fully-Automated (offline); Known-Gap (live round-trip) |
| AC-11 | Steps 1-5 | unit/integration pass with MOCK_EXTERNAL_APIS=true, no skips | Fully-Automated |
| AC-12 | n/a | documented post-ship live-Playwright verification step | Agent-Probe / Known-Gap |
| AC-13 | n/a | documented lab-corpus false-positive check (accessibility + privacy-browser fixtures) | Agent-Probe / Known-Gap |
| AC-14 | n/a | documented live wild-session check (Comet/Claude-in-Chrome) | Agent-Probe / Known-Gap |

## Touchpoints

- `apps/pixel/src/tracker.js` — delete line 4; add `agent_sig` collector after consent gate;
  piggyback Stage-2 proxy counters onto the existing click listener (~line 632)
- `apps/pixel/src/tracker.min.js` — regenerated build artifact (byte-budget gate target)
- `apps/api/schemas/events.py` — new optional `agent_sig` field on `Event`
- `apps/api/models/event.py` — new `agent_sig` column: `postgresql.JSONB`, nullable, declared
  with plain `Column(...)` (legacy declarative style, matching `Event`'s existing columns — not
  `Mapped[...]`/`mapped_column`)
- `apps/api/routers/events.py` — persist `agent_sig` at ingest (additive, no existing behavior changed)
- `apps/api/migrations/versions/` — two new migrations: `events.agent_sig` column, and
  `visitors.is_agent_operated` / `identified_visitors.is_agent_operated` columns (re-authored,
  re-chained onto the live head — NOT copied byte-for-byte from the branch's orphaned file)
- `apps/api/services/ws2_session_classifier.py` — new file, re-derived from branch (pure functions)
- `apps/api/services/ws2_session_classifier_sweep.py` — new file, re-derived from branch
  (`_extract_agent_sig` now reads the real column)
- `apps/api/config.py` — new `ws2_classifier_enabled` (+ threshold) settings block, default OFF
- `apps/api/jobs/scheduler.py` (confirmed — `cadence_bot_flag_sweep` registration pattern at
  lines ~565-569 is the template to mirror) — register the sweep job, gated by
  `ws2_classifier_enabled`
- `apps/api/models/visitor.py` — `is_agent_operated` columns on `Visitor` and `IdentifiedVisitor`
- `apps/api/services/identity_classification.py` — NOT modified (D1: zero touch, proven by a
  negative/regression test, not a code change)
- Dashboard badge — NO shared component exists to extend; `is_bot_suspect` is rendered INLINE
  at 3 confirmed sites: `apps/web/src/app/dashboard/visitors/page.tsx:766`,
  `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx:545` and `:935`, plus the type at
  `apps/web/src/lib/api-types.ts:307`. Add `is_agent_operated` as a parallel inline block at each
  of the 3 sites, following the exact `is_bot_suspect` visual/copy pattern.
- `tests/unit/test_ws2_session_classifier.py`, `tests/unit/test_ws2_zero_import.py` — ported
- `tests/unit/test_pixel_fingerprint.py`, `tests/unit/test_pixel.py` — existing gates, re-run
- `tests/unit/test_agent_origin_exclusion.py` — pattern reference for AC-9's new test (new test
  file or appended section — confirm at Step 5)
- `tests/integration/` — new/extended ingest test for `agent_sig` round-trip (AC-4, AC-7)

## Public Contracts

- **Event ingest payload** gains an additive, optional `agent_sig` object
  (`{webdriver: bool, ua_ch_headless: bool, no_pointermove_before_click: bool,
  dead_center_ct: int, click_ct: int}` — exact key names finalized at Step 1). Older pixel
  builds that omit it are unaffected (field is optional, defaults to `None`/absent).
- **`events.agent_sig` column** — new, nullable, additive (`JSONB`, per E7). No existing query
  changes shape. Persisted in the `event_rows` / `pg_insert(Event)` block in
  `apps/api/routers/events.py` (~L375-422, same block that sets `link_marker` and
  `is_flagged_abuse`) — NOT via the separate `_process_signal_events()` `fp`/`fp3` path
  (~L540-606), which writes to the Visitor row, a different table entirely (see Step 3.5).
- **`visitors.is_agent_operated` / `identified_visitors.is_agent_operated`** — new boolean
  columns, `NOT NULL server_default false`, sticky OR-merge write (never cleared), mirroring
  `is_bot_suspect`. Read by dashboard serialization; NOT read by `is_emailable_identity()` or any
  aggregate-exclusion path.
- **`is_emailable_identity(provider, source_agent_visit_id=None, is_abuse_flagged=False)`** —
  signature UNCHANGED. This is itself a public contract this plan must not break (locked invariant
  in `f3a7c9e21b48_add_internal_traffic_damping.py:21`).
- **New config settings** (`ws2_classifier_enabled` etc.) — additive, default OFF, no behavior
  change until an operator flips them post-migration-live-apply.
- **Dashboard visitor/session serialization** — additive `is_agent_operated` boolean field.

## Blast Radius

- **Risk class:** behavioral detection layer (visibility-only, non-destructive) + one additive
  schema surface (2 migrations) + one pixel byte-budget surface (hard gate, no headroom for
  drift). NOT auth, NOT billing, NOT a public API contract break, NOT a destructive migration.
- **Files touched:** ~13-15 (pixel: 2; backend: ~7; frontend: 1-2; migrations: 2; tests: ~4).
  Crosses the 5-file threshold — Strategy Compare should be invoked at PLAN→VALIDATE transition
  (see Strategy Recommendation below).
- **Shared/high-traffic surfaces touched:** `apps/pixel/src/tracker.js` (every customer site's
  pixel) and `apps/api/routers/events.py` (the `/ingest` hot path) — both additive-only changes,
  but any regression here is customer-visible immediately. Requires the existing pixel size-gate
  and ingest integration tests as hard pre-merge gates (already true repo-wide).
- **Concurrent-migration collision risk:** HIGH by project history (documented repeatedly in
  `process/context/all-context.md`). Step 0 (re-verify `alembic heads`) MUST be re-run
  immediately before EACH of the two migrations is authored, not just once at plan start.

## Phase Completion Rules (COMPLEX-lite — single plan, no phase program)

- A step is `CODE DONE` when its own gate(s) are green.
- A step is NOT `VERIFIED` until its Verification Evidence row's proving test passes AND any
  regression it could affect (existing `is_emailable_identity()` call sites, pixel size gate,
  existing pixel unit suite) is re-confirmed green.
- The whole plan cannot be marked `✅ VERIFIED` while any Fully-Automated-strategy AC gate is red.
  AC-12/13/14 (Known-Gap/Agent-Probe by SPEC) do not block `✅ VERIFIED` — they are carried forward
  explicitly (see Known-Gaps section).

## Implementation Checklist

### Step 0 — Re-verify migration head (mandatory pre-flight, run before Step 3 AND again before authoring each migration)

```
alembic -c apps/api/alembic.ini heads
```
Confirm single head. Do NOT hardcode `f1a7c3e05b92` (this session's measured value) into any
migration's `down_revision` without re-running this command first — the project has a documented
history of concurrent-migration collisions (see `process/context/all-context.md`).

### Step 0a — Standing pre-flight guard: confirm clean git state before ANY file edit (folds E8 permanently into the checklist, not just the contract)

This repo demonstrably runs concurrent sessions on the same shared working tree (VALIDATE pass 2
caught an unrelated interactive rebase mid-flight; other sessions have independently modified
`apps/api/config.py`, `apps/api/services/campaign_sender.py`, and migration files during this very
plan's lifecycle). Before Step 0's `alembic heads` check, and again before any resumed edit after a
session gap, execute-agent MUST:

1. Run `git status` — confirm there is NO `interactive rebase in progress`, `merge in progress`,
   or `cherry-pick in progress` message.
2. Run `git rev-parse --abbrev-ref HEAD` — confirm it returns `devjulley` (or the branch named in
   this session's Work context), never `HEAD` (detached).
3. **If either check fails: STOP IMMEDIATELY.** Do not touch any file, do not run
   `alembic heads`, do not edit `tracker.js`. Report BLOCKED with the exact `git status` output and
   wait for the concurrent operation to resolve. Never run `git rebase --abort`/`--continue`,
   `git merge --abort`, or any other mutating git command to "fix" another session's in-progress
   operation — it is not execute-agent's to resolve.
4. Once confirmed clean, **re-verify every line-number citation in this plan by grep, not by
   trusting the hardcoded numbers** — the numbers below are a convenience for orientation; the
   grep is the actual contract. Line numbers drift for reasons beyond any single rebase
   (concurrent unrelated edits, prior commits in this same session).


### Step 1 — `tracker.js`: delete early-return, add byte-budgeted `agent_sig` collector (AC-1, AC-2, D3)

1. Delete `apps/pixel/src/tracker.js:4` (`if (navigator.webdriver === true) return;`) outright.
   No replacement statement at that line. Bootstrap continues unconditionally from
   `document.currentScript` onward, exactly as it does for every other visitor today.
2. Immediately AFTER `var consentDecision = GATED ? ... : "g";` and the `if (GATED &&
   consentDecision === "d") OPTOUT = true;` line (tracker.js:507-508 in the pre-change file — the
   URL-param capture block already sits after this point as the established G7-compliant
   placement pattern; add `agent_sig` collection in the same region, before or interleaved with
   that block, never before it), add a small IIFE or inline block that computes:
   - `webdriver`: `navigator.webdriver === true` (read once, cheap — already-existing browser
     property, no new API surface).
   - `ua_ch_headless`: best-effort UA-CH brand check. If `navigator.userAgentData` and
     `.brands` are available, look for a `"HeadlessChrome"` brand entry; wrap in try/catch,
     default `false`/`undefined` on any failure or absence (older browsers, Firefox, Safari).
   - Store these two booleans in a session-scoped variable (e.g. `var agentSig = {webdriver:
     ..., ua_ch_headless: ...};`) that later gets merged with Stage-2 counters and attached to
     outgoing event payloads (reuse the existing `_fp`/`_fp3` attachment pattern in `pushEvent`/
     `flush` — find the exact attachment site by grepping `_fp3` usage before Step 2 wiring).
3. In the EXISTING click listener (tracker.js:632, `document.addEventListener("click", ...)`),
   piggyback two Stage-2 counters WITHOUT adding a new listener:
   - `clickCount` already exists (bounds at 25) — reuse it as `total click count`.
   - Add a `dead_center_ct` counter: on each click, compute whether the click landed within a
     small tolerance of the clicked element's bounding-box center (`el.getBoundingClientRect()`);
     increment if so. Keep the tolerance/math minimal — this is a proxy, not a precision
     measurement (mirrors the branch's `evaluate_behavioral_and_gate` consumer contract: caller
     supplies a rate, not raw coordinates).
   - Add a `no_pointermove_before_click` boolean: track whether ANY `pointermove` event fired
     before the FIRST click. Do NOT add a dedicated `pointermove` listener if it can be avoided —
     prefer a cheap one-shot check (e.g. a single `{ once: true }` listener registered once at
     bootstrap, OR reuse of an existing mousemove-adjacent listener if one exists — confirm via
     grep before implementing; if none exists, a single minimal one-shot listener is acceptable
     as the smallest addition that satisfies D2's "proxy signal" framing).
4. Attach the merged `agent_sig` object (webdriver, ua_ch_headless, no_pointermove_before_click,
   dead_center_ct, click_ct) to the outgoing payload on the same channel `_fp`/`_fp3` already use
   (confirm the exact `pushEvent`/batch-payload shape before wiring — grep `_fp3` and `alias=` in
   `schemas/events.py` to confirm client/server key-name agreement, e.g. `_asig`). **Pass-3
   VALIDATE guidance (non-blocking, advisory — see the Byte-Budget Falsifiability Assessment
   below): given the 233B live headroom, prefer short/abbreviated wire-key names (e.g. single- or
   two-letter keys) over the full descriptive names shown for illustration in the Public
   Contracts section, on the FIRST implementation attempt — do not spend a trim-and-remeasure
   cycle discovering this the hard way.**
5. **Regenerate `tracker.min.js`** using the project's existing minify/build step (confirm exact
   command via `package.json` scripts in `apps/pixel/` before running — do not hand-edit the
   `.min.js` file).

**Test gate (run immediately after this step):**
```
.venv/bin/python3.11 -m pytest tests/unit/test_pixel.py -q
```
(NOTE: drop `-m unit` — `tests/unit/test_pixel.py` carries no pytest markers at all; `-m unit`
deselects every test in the file, exit code 5 "no tests ran", a gate that silently passes without
running anything.)

No behavioral webdriver-exit assertion currently exists to "update" — the only existing related
test, `test_has_bot_detection` (`tests/unit/test_pixel.py:24-25`), only asserts the STRING
`"navigator.webdriver"` is present in source text; it is not behavioral and will keep passing
trivially after this edit. Write a NEW source-position regex test (matching this suite's existing
style) asserting: (a) no early-return pattern precedes `document.currentScript`, and (b) the
`agent_sig` collection code appears strictly after the line containing `consentDecision = GATED`
(this also proves AC-2's ordering).

### Step 2 — Byte-budget checkpoint (AC-2, AC-3 — the riskiest element, hard pass/fail gate)

This step exists specifically to catch the two failure modes INNOVATE flagged: (a) exceeding
available headroom, or (b) shrinking Stage 2 so far it never actually fires (reproducing WS2's
original dead-Stage-1 pathology in new form).

1. Re-measure current baseline BEFORE this step's edits are counted (already measured this
   session, re-confirmed live at VALIDATE pass 3 07-08-26: `tracker.min.js` = 13626B raw / 5767B
   gzip via the TEST'S OWN method — `gzip.compress(path.read_bytes())`, matching
   `tests/unit/test_pixel_fingerprint.py:290` exactly — 233B headroom remaining to the binding
   `<6000` gate. **Do not use `gzip -9 -c file | wc -c` to self-check — it reads 5782B on the
   same file, a 15B discrepancy from the test's method that matters at this margin. Measure the
   way the gate measures.**):
   ```
   .venv/bin/python3.11 -c "import gzip,pathlib; d=pathlib.Path('apps/pixel/src/tracker.min.js').read_bytes(); print(len(d), len(gzip.compress(d)))"
   ```
2. After Step 1's edits + rebuild, re-run the same command. Compute delta.
3. **Pass condition (both must hold):**
   - `new_gzip_bytes < 6000` (binding gate) — record the exact number in the phase report.
   - **"Fires at all" check**: this CANNOT be proven as a Python pytest assertion — the entire
     Python pixel suite is string/regex-only against raw source text, with no JS execution engine
     anywhere in the repo. Add a new Playwright spec `apps/pixel/e2e/agent-sig.spec.ts`, mirroring
     the `fingerprint-v3.spec.ts` pattern (`interceptIngest`/`fixture`/`settle` from `./harness`):
     drive several deterministic clicks near element centers, then assert the intercepted ingest
     payload's `agent_sig` object has NON-DEFAULT values for `dead_center_ct` / `click_ct` /
     `no_pointermove_before_click` (i.e., not silently stuck at their initial state). This is a
     structural sanity check, not a claim about real-world detection accuracy (that remains
     AC-12's Known-Gap).
4. **If either condition fails:** first try trimming field precision (start with short wire-key
   names per the Step 1.4 pass-3 guidance above; then drop `ua_ch_headless` if UA-CH is
   unavailable in most browsers anyway, or reduce counter bit-width). Only as a LAST RESORT, raise
   the gzip gate itself (`test_under_6kb_gzipped`'s `< 6000` threshold) — this requires explicit
   justification in the phase report with the measured byte count that forced it, and is a
   deviation from the SPEC's stated preference, not a default path.
5. Record the final measured byte count and headroom remaining in the phase report — this is
   AC-3's explicit evidence requirement, not optional bookkeeping. **Re-measure at Step 2 start
   regardless of any number cited anywhere in this plan or its validate-contract — the 233B figure
   is a live pass-3 snapshot, not a guarantee; this repo's shared tree has already shown it move
   twice within one plan's VALIDATE lifecycle (312B → 233B).**

**Test gate:**
```
.venv/bin/python3.11 -m pytest tests/unit/test_pixel_fingerprint.py::TestPixelSizeLimit::test_under_6kb_gzipped tests/unit/test_pixel.py -q
```
(NOTE: drop `-m unit` for the same reason as Step 1 — neither file carries pytest markers.)

Plus, for the "fires at all" sub-check:
```
cd apps/pixel && npm run build && npx playwright test e2e/agent-sig.spec.ts
```

### Step 3 — Persist `agent_sig` at ingest (AC-4, AC-7, AC-10)

1. Re-run Step 0's `alembic heads` check immediately before authoring migrations.
2. Add `agent_sig: dict | None = Field(None, alias="_asig")` (or the exact key agreed in Step 1.4)
   to `Event` in `apps/api/schemas/events.py`, following the `fp`/`fp3` alias pattern exactly.
3. Add `agent_sig: dict | None = Column(postgresql.JSONB, nullable=True)` to the `Event` ORM
   model in `apps/api/models/event.py`, following the `link_marker`/`is_flagged_abuse`
   additive-column comment style (nullable, no default needed since it's nullable not boolean).
   Use `JSONB`, not plain `JSON` — every existing JSON-shaped column in this codebase
   (`agent_profile.py`, `agent_visit.py`, `api_usage.py`, `campaign.py`, `crm_connection.py`,
   `enrichment.py`, `request_log.py`) uses `JSONB`, none use plain `JSON`. Declare with plain
   `Column(...)` (legacy declarative style), matching `Event`'s existing columns — not
   `Mapped[...]`/`mapped_column`.
4. Write migration `add_events_agent_sig` chained onto the LIVE head confirmed in step 1 — additive
   `ALTER TABLE events ADD COLUMN agent_sig JSON NULL` (or `JSONB`), no data migration, `downgrade()`
   drops the column. Offline-validate:
   ```
   alembic -c apps/api/alembic.ini upgrade <prior_head>:<new_revision> --sql
   ```
5. In `apps/api/routers/events.py`, persist `agent_sig` onto the `Event` row inside the
   `event_rows` dict-list / `pg_insert(Event)` block (~L375-422 as of this VALIDATE session — the
   same block that sets `link_marker` and `is_flagged_abuse`). Do NOT follow a `fp3_value`-style
   grep into `_process_signal_events()` (~L540-606) — that function writes `fp`/`fp3` onto the
   **Visitor** row (`fingerprint`/`fingerprint_v3` columns), a structurally different table and
   code path. AC-4's proving test requires the value on the **Event** row specifically; persisting
   it via the Visitor-row path would silently fail AC-4. Purely additive at the correct site: no
   existing field, no existing branch logic changes.
6. Confirm the `is_bot()` / bot-drop early-return in `ingest_events()` (routers/events.py ~L145)
   is UNCHANGED — a session carrying `agent_sig` must still be able to reach persistence (AC-7:
   classification never causes a drop). This is a read-only confirmation, not a code change.

**Test gate (integration, Docker-gated):**
New or extended integration test in `tests/integration/` posting a batch with a populated
`agent_sig` object and asserting: (a) `POST /ingest` returns `204`, (b) the persisted `events` row
has the same `agent_sig` value on read-back.

### Step 4 — Port `ws2_session_classifier.py` + sweep (AC-5, D4)

1. Read `feat/ws2-agent-session-classifier:apps/api/services/ws2_session_classifier.py` via
   `git show` — copy the pure-function module (`is_deterministic_agent`,
   `compute_dead_center_rate`, `evaluate_behavioral_and_gate`, `evaluate_session_classifier`)
   verbatim into `apps/api/services/ws2_session_classifier.py` on current `main`. Zero imports
   outside stdlib — preserved unchanged (this is the module's own stated structural guarantee).
2. Read `feat/ws2-agent-session-classifier:apps/api/services/ws2_session_classifier_sweep.py`
   via `git show`. Port the sweep, updating ONLY:
   - `_extract_agent_sig(event)` — change from unconditional `return None` to
     `return getattr(event, "agent_sig", None)` reading the now-real column (already the branch's
     own forward-looking implementation — no logic change needed beyond confirming the column
     exists).
   - Any import paths that drifted between the branch's base commit and current `main` (confirm
     via a diff of shared surrounding files, e.g. `apps/api/models/visitor.py`,
     `apps/api/models/event.py`, before assuming zero drift).
3. Add config settings block to `apps/api/config.py`, ported from the branch's
   `## ─── WS2 agent-driven session classifier ───` section: `ws2_classifier_enabled: bool =
   False`, `ws2_classifier_sweep_interval_minutes: int = 60`, `ws2_classifier_lookback_days: int =
   90`, `ws2_classifier_min_clicks: int = 5`, `ws2_classifier_max_pointer_entropy: float = 0.15`,
   `ws2_classifier_min_dead_center_rate: float = 0.6`. Default OFF, matching
   `agent_detection_enabled` / `cadence_bot_flag_enabled` precedent.
4. Add `is_agent_operated` boolean columns to `Visitor` and `IdentifiedVisitor` in
   `apps/api/models/visitor.py` (mirror `is_bot_suspect`'s exact column definition style —
   `nullable=False, server_default=sa.false()`, sticky, VISIBILITY-ONLY comment block).
5. Author migration `add_visitors_is_agent_operated` — RE-CHAINED onto the live head confirmed
   at Step 0 immediately before writing this file (do NOT reuse the branch's orphaned
   `f4c1a9e2d3b8_add_ws2_agent_operated_flag.py` `down_revision` — it points at a stale
   `a2f8d61c9e37` from the branch's own history). Content (columns, nullability, server_default)
   may be copied from the branch file; the `revision`/`down_revision` header must be freshly
   authored against current `main`'s live head. Offline-validate with `--sql` and an explicit
   `<from>:<to>` range.
6. Register the sweep as an APScheduler job, gated by `ws2_classifier_enabled`, in
   `apps/api/jobs/scheduler.py`, mirroring the `cadence_bot_flag_sweep` registration pattern at
   lines ~565-569 (`scheduler.add_job(_cadence_bot_flag_sweep_job, ..., id="cadence_bot_flag_sweep")`).
   File and line range are confirmed — no further grep needed.
7. Port `tests/unit/test_ws2_session_classifier.py` and `tests/unit/test_ws2_zero_import.py` from
   the branch via `git show`, updating only import paths if module locations drifted. These are
   the frozen spec-by-example — the ported implementation from steps 1-2 above must make them pass
   without modifying the test assertions themselves. If a test genuinely cannot pass without an
   assertion change, that is a plan deviation requiring explicit justification in the phase
   report, not a silent edit.

**Test gate:**
```
.venv/bin/python3.11 -m pytest tests/unit/test_ws2_session_classifier.py tests/unit/test_ws2_zero_import.py -m unit
```

### Step 5 — Visibility-only wiring + AC-9 negative test (AC-8, AC-9, D1)

1. **Zero-touch confirmation, not a code change**: grep `apps/api/services/identity_classification.py`
   to confirm `is_emailable_identity()`'s signature is untouched (still exactly `provider,
   source_agent_visit_id=None, is_abuse_flagged=False`) and that neither `is_agent_operated` nor
   `is_bot_suspect` appears anywhere in the function body. Record this confirmation in the phase
   report — this IS the AC-8 evidence for the visibility-only tier, structurally (absence of a
   4th parameter), not just by assertion.
2. Write a new regression test (new file, e.g. `tests/unit/test_visibility_only_flags_no_leak.py`,
   or append a clearly-marked section to `tests/unit/test_agent_origin_exclusion.py` — confirm the
   better home at implementation time) mirroring `test_agent_origin_exclusion.py`'s structure:
   construct an `IdentifiedVisitor` with `is_bot_suspect=True` and/or `is_agent_operated=True` set,
   and assert `is_emailable_identity(provider=...)` returns the SAME result as an otherwise-
   identical visitor with neither flag set, for every `PERSON_LEVEL_PROVIDERS` entry. This closes
   AC-9's previously-identified gap (no existing test proves visibility-only flags don't leak).
3. Confirm all 3 existing call sites (`campaign_sender.py`, `csv_exporter.py`,
   `routers/campaigns.py`) are unmodified — grep each, diff against the pre-plan state, assert
   zero lines changed in this plan's blast radius at those 3 sites. This proves AC-8's "implemented
   consistently" requirement without touching production call-site code. **Pass-3 note: exact line
   numbers drift session to session (currently `campaign_sender.py:313`, `csv_exporter.py:84`,
   `routers/campaigns.py:730`, all re-confirmed present at VALIDATE pass 3) — locate by grepping
   `is_emailable_identity(`, never by trusting a hardcoded line number.**

**Test gate:**
```
.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py tests/unit/test_visibility_only_flags_no_leak.py -m unit
```

### Step 6 — Dashboard badge (AC-6)

1. NO shared badge component exists to extend — `is_bot_suspect` is rendered INLINE at 3
   confirmed sites: `apps/web/src/app/dashboard/visitors/page.tsx:766`,
   `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx:545` and `:935`, plus the type at
   `apps/web/src/lib/api-types.ts:307`. Do not search for a shared component under
   `apps/web/src/components/visitors/` — it does not exist there.
2. Add `is_agent_operated` as a parallel inline block at each of the 3 sites, following the exact
   visual/copy pattern already established for `is_bot_suspect`. This is explicitly NOT a new page
   or new export-only field (Out of Scope). If extracting a shared component turns out to be
   materially cheaper at implementation time, that is a small scope addition — call it out
   explicitly in the phase report rather than doing it silently.
3. Confirm the backend serialization path (visitor list/detail API response) includes the new
   `is_agent_operated` field — additive field on an existing response shape, confirm via grep of
   the serializer/schema used by the visitor list/detail endpoints.

**Test gate (Agent-Probe — reclassified from the original Hybrid tier; `apps/web` has zero
component-render test infrastructure — no `@testing-library/react`/jsdom, `vitest.config.ts`
`include` globs `.ts` only, zero `.test.tsx` files repo-wide; an exact repeat of the gap
`cadence-bot-flag` already hit and reclassified, see
`process/features/pixel/backlog/cadence-bot-flag-deferred-gates_NOTE_26-07-26.md`):**
Manual visual check at the 3 sites named in point 1 above, against `is_agent_operated: true` and
`false`/absent fixtures — confirm the badge renders/is absent accordingly. Do not attempt to build
new component-render test infra as part of this plan (repo-wide backlog candidate, out of scope).

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `tests/unit/test_pixel.py` — bootstrap doesn't short-circuit on webdriver alone; consent gating unchanged | Fully-Automated | AC-1 |
| `tests/unit/test_pixel.py` (new/updated case) — agent_sig collection fires only after consentDecision/GATED resolves | Fully-Automated | AC-2 |
| `tests/unit/test_pixel_fingerprint.py::TestPixelSizeLimit::test_under_6kb_gzipped` + `tests/unit/test_pixel.py` size gate (no `-m unit`) | Fully-Automated | AC-2, AC-3 |
| `apps/pixel/e2e/agent-sig.spec.ts` (new Playwright spec, mirrors `fingerprint-v3.spec.ts`) — Stage-2 counters fire under simulated clicks | Hybrid | AC-3 (fires-at-all sub-check) |
| New integration test — ingest payload with agent_sig round-trips to persisted event row | Fully-Automated (Docker-gated) | AC-4 |
| `tests/unit/test_ws2_session_classifier.py` (ported) — sweep classifies real non-null agent_sig fixture | Fully-Automated | AC-5 |
| Manual visual check at the 3 confirmed inline badge sites — badge renders/absent by `is_agent_operated` | Agent-Probe (no component-render test infra in `apps/web`) | AC-6 |
| New/extended integration test — ingest with agent-indicating agent_sig still returns success, row written | Fully-Automated | AC-7 |
| New unit test — `is_emailable_identity()` at all 3 call sites unaffected by is_agent_operated/is_bot_suspect | Fully-Automated | AC-8 |
| New unit test (AC-9) — is_bot_suspect / is_agent_operated do not trip `is_emailable_identity()` | Fully-Automated | AC-9 |
| `alembic -c apps/api/alembic.ini heads` (single head, re-run pre-authoring each migration) + offline `--sql` validation | Fully-Automated (offline) | AC-10 |
| Full suite re-run with `MOCK_EXTERNAL_APIS=true` | Fully-Automated | AC-11 |
| Documented post-ship live-Playwright classification check | Agent-Probe / Known-Gap | AC-12 |
| Documented lab-corpus false-positive check (accessibility + privacy-browser fixtures) | Agent-Probe / Known-Gap | AC-13 |
| Documented live wild-session check (Comet / Claude-in-Chrome) | Agent-Probe / Known-Gap | AC-14 |
| `tests/unit/test_ws2_zero_import.py` (ported) — structural import-isolation from cadence_bot_flag/agent_classifier | Fully-Automated | (structural guardrail, not a numbered AC — carried from branch precedent) |

## High-Risk Class Table

| Area | High-risk class | Minimum tier | Gap rationale if known-gap accepted |
|---|---|---|---|
| `apps/api/services/identity_classification.py` (is_emailable_identity call sites) | outreach/emailability eligibility | Fully-Automated | — (no known-gap accepted; this is the highest-scrutiny surface in the plan) |
| Migration chain (`events.agent_sig`, `visitors/identified_visitors.is_agent_operated`) | schema/migration | Fully-Automated (offline) | Live round-trip on a disposable Postgres is a Known-Gap — Docker-gated, consistent with every other pending migration in this codebase's history (see `process/context/all-context.md` migration chain notes) |
| `apps/pixel/src/tracker.js` (public-facing tracking script, every customer site) | none of the 6 named classes, but customer-visible-immediately on deploy | Fully-Automated (size gate + unit) | — |

## Known Limitation — Explicitly Named, Not Buried

**D1 (visibility-only) does NOT stop identity-resolution budget burn.** WS2 classifies via a
periodic sweep (`ws2_classifier_sweep_interval_minutes`, default 60 min); identity resolution
fires near ingest time. By the time the sweep flags a session, the identity-resolution spend for
that session has already happened. Visibility-only only prevents outreach-pool pollution
(the flag never being read by `is_emailable_identity()` protects downstream campaign targeting),
it does NOT prevent the upstream budget spend. This is the exact same limitation
`cadence_bot_flag` already accepted (same batch-sweep-vs-ingest-time timing gap). A
resolution-time gate that checks `agent_sig`'s deterministic Stage-1 signals BEFORE triggering
identity resolution is a separate future SPEC — explicitly NOT scoped in this plan (see Out of
Scope in the SPEC), named here only so it is not mistaken for delivered.

## Release Note (for the phase report / changelog)

Customers running their own Playwright/Selenium QA against their own site will now SEE that
traffic as agent-flagged visitor rows on their dashboard where it was previously either invisible
(webdriver-set sessions) or silently counted as an ordinary human (non-webdriver-set sessions).
This is a desired, intended behavior change per AC-1/AC-7 — it must be documented as such in the
phase report and any customer-facing changelog entry, not treated as an unannounced side effect.

## Test Infra Improvement Notes

- `apps/web` has zero component-render test infrastructure (no `@testing-library/react`/jsdom,
  `vitest.config.ts` `include` globs `.ts` only, zero `.test.tsx` files repo-wide). This forces
  AC-6's badge-render check to Agent-Probe instead of Fully-Automated — the exact same gap
  `cadence-bot-flag` hit and reclassified (see
  `process/features/pixel/backlog/cadence-bot-flag-deferred-gates_NOTE_26-07-26.md`, Gap 3).
  Building this infra is out of scope for this plan; tracked as a repo-wide backlog candidate.
- `tests/unit/test_pixel.py` and `tests/unit/test_pixel_fingerprint.py` carry no pytest markers
  at all — any test-gate command using `-m unit` against these two files silently runs zero tests
  (exit code 5). Fixed in this plan's Steps 1-2 test gates by dropping `-m unit`; worth a repo-wide
  audit of other test-gate commands that may have the same bug.

## Resume and Execution Handoff

1. **Selected plan file path:** `process/features/pixel/active/ws2-agent-session-activation_07-08-26/ws2-agent-session-activation_PLAN_07-08-26.md`
2. **Last completed phase or step:** PLAN written; no EXECUTE steps started.
3. **Validate-contract status:** pending — `## Validate Contract` placeholder below; VALIDATE has
   not yet run.
4. **Supporting context files loaded during PLAN:** SPEC at
   `ws2-agent-session-activation_SPEC_07-08-26.md`; `process/context/all-context.md`;
   `process/context/tests/all-tests.md`; `process/features/pixel/active/cadence-bot-flag_26-07-26/cadence-bot-flag_PLAN_26-07-26.md`
   (structural precedent); `process/features/pixel/backlog/cadence-bot-flag-deferred-gates_NOTE_26-07-26.md`;
   `feat/ws2-agent-session-classifier` branch files read via `git show` (never checked out):
   `ws2_session_classifier.py`, `ws2_session_classifier_sweep.py`,
   `test_ws2_session_classifier.py`, `test_ws2_zero_import.py`,
   `f4c1a9e2d3b8_add_ws2_agent_operated_flag.py`.
5. **Next step for a fresh agent picking up mid-execution:** run `ENTER VALIDATE MODE` on this
   plan file next. If resuming mid-EXECUTE, re-run Step 0 (`alembic heads`) FIRST regardless of
   which step was last completed — the migration head is a moving target in this repo and must
   never be assumed stable across a session gap.

## Validate Contract

Status: CONDITIONAL
Date: 07-08-26
date: 2026-08-07
generated-by: inner-pvl: phase-1
supersedes: 2026-08-07 (inner-pvl: phase-1) — PVL pass 3, re-validation from V1 against the
twice-supplemented plan (cycle 1 folded E1-E7; cycle 2 folded E8 + 3 citation refreshes). This
pass re-verifies both cycles' fold-ins against a FRESH live tree (HEAD `5293cbc2de233a8431412ad1a4501a2a1eccfebb`,
branch `devjulley`, clean working tree — no rebase/merge/cherry-pick in progress) and finds 0 new
design gaps.

Parallel strategy: sequential
Rationale: Signal score 3/7 (S1 multi-package: pixel+api+web; S2 schema surface: 2 additive
migrations; S7: 13-15 files in blast radius) — MEDIUM by the threshold table, but the plan's 6
steps are sequentially dependent (Step 5's emailability proof depends on Step 4's classifier,
which depends on Step 3's persistence, which depends on Step 2's byte-budget shape). A single
sequential `vc-validate-agent` pass following the plan's own dependency chain was used all three
passes, matching the plan's own Strategy Recommendation for VALIDATE.

## Cycle-1/Cycle-2 Continuity Re-Verification (pass 3, against fresh HEAD `5293cbc`)

Both prior supplement cycles were re-checked against live source in this pass, independent of the
prior passes' own citations. All land correctly; no regressions from either fold-in:

| # | What pass 3 checked | Live evidence (this pass) |
|---|---|---|
| E1 | `-m unit` dropped from Step 1/Step 2 gate commands | `grep -c "pytest.mark" tests/unit/test_pixel.py tests/unit/test_pixel_fingerprint.py` → 0/0. Both files still carry zero markers. Ran the corrected command live: `pytest tests/unit/test_pixel.py tests/unit/test_pixel_fingerprint.py -q` → **72 passed**. |
| E2 | New `apps/pixel/e2e/agent-sig.spec.ts` pattern achievability | `fingerprint-v3.spec.ts` present; `interceptIngest`/`fixture`/`settle` all confirmed exported live from `apps/pixel/e2e/harness.ts` (`grep -n "^export"` — 3 matching function/interface exports). `playwright.config.ts` `testMatch: /.*\.spec\.ts/` auto-picks up any new file dropped in `e2e/`. |
| E3 | `agent_sig` persistence site: `event_rows`/`pg_insert(Event)`, NOT `_process_signal_events()` | Re-confirmed independently at the true current line numbers: `event_rows = [` at L375, `link_marker=` at L404, `pg_insert(Event)` at L419 (inside the cited ~L375-422 range). `_process_signal_events()` starts L525, `pg_insert(Visitor)` at L602 — confirmed writing to the Visitor row via a structurally separate `pg_insert(Visitor)...on_conflict_do_update`, not the Event row. The retarget remains correct and load-bearing. |
| E4 | AC-6 Agent-Probe reclassification + 3 inline badge sites, no shared component | Unchanged in plan body (traceability table, Verification Evidence, Step 6, Touchpoints) — confirmed no stray "Hybrid" language remains. Not independently re-scanned for site line numbers this pass (frontend files outside this pass's read list; no code in this plan's blast radius depends on their exact line numbers being current, only on the pattern existing, which E4 already established). |
| E5 | Step 1 unconditionally requires a NEW behavioral test | Text unchanged and still unconditional in the plan body. |
| E6 | Scheduler registration file/line pattern | `apps/api/jobs/scheduler.py`: `_cadence_bot_flag_sweep_job` at L244, `id="cadence_bot_flag_sweep"` registration at L566-569 — matches the plan's "~565-569" citation almost exactly (1-line drift, non-blocking). |
| E7 | `JSONB` (not `JSON`) + legacy `Column(...)` style | Confirmed unchanged in Step 3.3, Touchpoints, Public Contracts. |
| E8 | Step 0a pre-flight guard exists and is actionable | Confirmed present in the checklist body (numbered 4-step procedure: check rebase/merge state, check branch, STOP-BLOCKED on failure with explicit "never auto-resolve" instruction, re-verify citations by grep). Live-tested this pass: `git status --short --branch` → clean, `devjulley...origin/devjulley [ahead 32, behind 5]`, no rebase-merge/rebase-apply/MERGE_HEAD markers; `git rev-parse --abbrev-ref HEAD` → `devjulley` (not detached). **Step 0a would PASS cleanly if run right now.** |

**Consent boundary G7 (re-confirmed at fresh HEAD):** `consentDecision = GATED` at L507,
`OPTOUT = true` decline-guard at L508 — matches the plan's own citation exactly (this is the
figure cycle 2 already corrected from the earlier L501-504; still correct at this pass's HEAD, no
further drift). `tracker.js:4`'s webdriver early-return is still present, single reference, as
expected pre-EXECUTE. Click listener at L632 — matches cycle 2's grep-found correction exactly, no
further drift. `pagehide` listener at L710 (plan cites "~706" from an earlier snapshot — 4-line
drift, cosmetic, non-blocking, does not affect any edit target).

**`is_emailable_identity()` invariant (re-confirmed at fresh HEAD):** signature at
`apps/api/services/identity_classification.py:119-123` is exactly `provider,
source_agent_visit_id=None, is_abuse_flagged=False`; grepped the function body for
`is_agent_operated`/`is_bot_suspect` — zero matches. This file is no longer in `git status`'s
modified list (it was mid-diff during pass 2; it is now committed/clean) — the D1 guardrail check
this pass performed is against a stable, non-transient state, strictly stronger evidence than pass
2's "diff is purely additive" argument.

**3 call sites (re-confirmed, line numbers drifted, all present):** `campaign_sender.py:313`
(was cited 283), `csv_exporter.py:84` (was cited 79), `routers/campaigns.py:730` (was cited 725).
Drift is consistent, small, and expected — these are grep-confirm targets in the plan, never
hardcoded edit anchors, so the drift is cosmetic and does not require a plan-body fix.

**Migration head (re-confirmed at fresh HEAD):** `alembic -c apps/api/alembic.ini heads` →
single head `f1a7c3e05b92` — matches iteration-002's post-rebase-resolution figure exactly. No new
collision since cycle 2.

**Pixel build script (re-confirmed):** `apps/pixel/package.json` `"build"` script is
`npx --yes esbuild@0.24.0 src/tracker.js --minify --target=es2017 --outfile=src/tracker.min.js` —
matches Step 1.5's "confirm via package.json scripts" instruction; `npm run build` is the correct
invocation.

**WS2 branch source (re-confirmed reachable via `git show`, not checked out):**
`git cat-file -e feat/ws2-agent-session-classifier:apps/api/services/ws2_session_classifier.py`
succeeds. `test_ws2_session_classifier.py` and `test_ws2_zero_import.py` on the branch both carry
`pytestmark = pytest.mark.unit` at module scope (confirmed via `git show`) — the `-m unit` gate
commands for AC-5/AC-8/AC-9/structural-guardrail will correctly select these tests once ported.
None of the WS2 implementation files exist yet on `main`/`devjulley` (confirmed: zero hits for
`ws2_classifier|is_agent_operated|agent_sig` across `config.py`, `models/visitor.py`,
`models/event.py`, `schemas/events.py`) — EXECUTE has not started, as expected.

## [NEW — pass 3] Byte-Budget Falsifiability Assessment (advisory CONCERN, non-blocking)

**Live re-measurement (test's own method, `gzip.compress(path.read_bytes())`):** `tracker.min.js`
= 13626B raw / **5767B gzip** → **233B headroom** to the binding `<6000` gate. Identical to
iteration-002's figure — stable, no further drift since cycle 2 (the concurrent-session
`tracker.min.js` rebuild that shrank headroom from 312B→233B has itself settled: the file is no
longer in `git status`'s modified list, i.e. it is now committed).

**Falsifiability judgment (explicitly requested this pass):** the gate itself
(`assert len(compressed) < 6000`) remains a genuine, non-tautological assertion — a regression
would fail it. The question is whether D2's trimmed Stage-1+Stage-2 signal set can plausibly fit
inside 233B of GZIPPED headroom. This cannot be answered with certainty without implementing the
code, but a reasoned estimate: the plan's own Public Contracts section illustrates the wire shape
with full descriptive keys (`webdriver`, `ua_ch_headless`, `no_pointermove_before_click`,
`dead_center_ct`, `click_ct`) — those 5 key names alone sum to ~90 raw ASCII characters before any
JS detection logic (UA-CH brand try/catch, dead-center bounding-box math, one-shot pointermove
listener, object merge/attach). Gzip compresses repeated tokens well (many of the surrounding JS
keywords — `function`, `document`, `addEventListener`, `navigator` — already recur elsewhere in
the file and cost little marginally), but genuinely NEW distinct tokens (the 5 field names, plus
`userAgentData`, `HeadlessChrome`, `getBoundingClientRect` if not already present, `pointermove`)
compress far less efficiently on first occurrence. **Judgment: plausible tight fit, real risk of a
first-attempt gate failure, not a certain failure.** This is a CONCERN worth surfacing explicitly
with reasoning (as instructed), but it is NOT a plan design defect requiring a new SUPPLEMENT — the
plan's own Step 2 already designs exactly the self-correcting mechanism this risk calls for
(mandatory live re-measure against the test's own method, explicit trim-first fallback ladder,
gate-raise only as a justified last resort). This pass adds one concrete, actionable refinement
directly into Step 1.4 and Step 2.4 above (prefer short/abbreviated wire-key names on the FIRST
attempt, not as a reactive fallback after a failed measurement) — a cheap, low-risk plan-body
clarification, not a design change, and not something requiring a SUPPLEMENT REQUEST cycle to
apply (it doesn't touch any Step's sequencing, dependencies, or test gates — it only tightens
existing Step 1.4/Step 2.4 guidance that already pointed at the same trim-first strategy).

`grep -n "6000\|6144\|gzip.compress" tests/unit/test_pixel_fingerprint.py tests/unit/test_pixel.py`
reconfirms the gate anchors exactly: `test_pixel_fingerprint.py:290-291` (`gzip.compress`, `< 6000`),
`test_pixel.py:154-155` (`gzip.compress`, `< 6144`).

## [NEW — pass 3] Feasibility Probe Correction: verdict updated from INCONCLUSIVE to a real,
partial empirical result (informational — not a design gap, does not require SUPPLEMENT)

**Correction to prior contract text.** Pass 2's contract (and the task brief that spawned this
pass) both stated the feasibility probe `ws2-webdriver-assumption_FEASIBILITY_07-08-26.md`
returned **INCONCLUSIVE**. Reading the file fresh this pass (per instructions: read-only, no
re-probe performed), it now contains a **materially different, populated verdict**:
`verdict: NOT-VIABLE`, with real browser measurements the coordinator captured after the prior
pass's citation was written. This is a genuine external-evidence update this pass discovered
mid-flight (the same class of "concurrent session editing files under this VALIDATE run" hazard
the task brief warned about generally — this instance just landed on the feasibility file, not a
plan/config/migration file).

**What the file now actually says:** for the ONE real agentic-browsing surface the probe could
reach this session — Claude-in-Chrome (extension-driven browser automation, not CDP/WebDriver) —
`navigator.webdriver` measured `false` and `userAgentData.brands` was byte-identical to a plain
human Chrome session (no `HeadlessChrome` entry). Comet, Operator, and Atlas remain entirely
unmeasured (not installed on the probe machine) — the hypothesis is NOT settled globally, only for
this one product class.

**Why this does not block PASS/CONDITIONAL or require a plan-body SUPPLEMENT:**
1. It does not touch any Step, AC, or test gate's mechanics — AC-14 was already, deliberately,
   scoped as `Agent-Probe`/Known-Gap in both the SPEC and this plan, not blocking `✅ VERIFIED`.
2. It does not contradict D1-D4 — if anything it **reinforces** D2's own design choice: the
   VERDICT's "Resulting Design Constraint" states explicitly that Stage 1 (webdriver + UA-CH) is
   now confirmed insufficient for extension-driven agentic browsers, and Stage 2 (behavioral
   AND-gate) is "confirmed as load-bearing, not a nice-to-have fallback" for that class — this is
   exactly the shape D2 already committed to (Stage 2 proxies as a real, piggybacked signal, not
   an afterthought).
3. It does not change any implementation instruction — no Step needs new text as a result.
4. Per this pass's write-scope, this is a contract-accuracy correction (the validate-agent's own
   prior characterization of external evidence), not a plan-body defect — it is fixed here, in the
   contract, not routed to plan-agent.

**Carried forward, corrected:** AC-14 remains Known-Gap/Agent-Probe as SPEC'd — genuinely
unresolved for Comet/Operator/Atlas, and this new evidence should NOT be extrapolated to those
products (the VERDICT file's own "What this forbids" section says so explicitly). The prior
"INCONCLUSIVE... not re-probed" contract language is superseded by this correction; no further
probing was performed this pass, matching the task's "do not re-probe" instruction — this is a
read-only accuracy fix, not new investigation.

## Verification of Locked Decisions and Named Hazards (re-confirmed across all 3 passes)

- **G7 consent boundary** — CONFIRMED intact, three passes running, now against a stable
  post-rebase HEAD: `agent_sig` collection is specified to land after `consentDecision = GATED`
  (L507) and before `pagehide`/beacon flush (L710, unrelated to this plan's edits).
- **`is_emailable_identity()` exactly-3-parameters invariant** — CONFIRMED, and now against a
  clean (non-mid-diff) file for the first time across all 3 passes — the strongest form of this
  check yet.
- **3 call sites** — all 3 confirmed present via live grep at fresh HEAD, line numbers drifted
  cosmetically, targets unchanged.
- **Migration safety** — single head `f1a7c3e05b92` confirmed stable since cycle 2's
  post-rebase-resolution measurement; no new collision this pass.
- **Byte-budget gate falsifiability** — confirmed real (non-tautological); see the dedicated
  pass-3 assessment above for the new advisory-CONCERN reasoning on the 233B margin.
- **Feasibility probe carry-forward** — CORRECTED this pass (see dedicated section above): was
  cited as INCONCLUSIVE, is now NOT-VIABLE (partial, one product class) with real measurements;
  reinforces rather than undermines D2; AC-14 stays Known-Gap.

Test gates (C3 5-column table — ADDITIVE; existing consumers still parse the legacy line form below it):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | Tracker bootstrap does not short-circuit on webdriver alone; consent gating unchanged | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_pixel.py -q` (re-run live pass 3: 72 passed) | A |
| AC-2 | agent_sig collection fires only after consentDecision/GATED resolution | Fully-Automated | same corrected command as AC-1 (new test case) | A |
| AC-3 | Pixel gzip size stays under 6000B/6144B | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_pixel_fingerprint.py::TestPixelSizeLimit::test_under_6kb_gzipped tests/unit/test_pixel.py -q` | A — 233B live headroom confirmed stable; see Byte-Budget Falsifiability Assessment for the advisory margin CONCERN |
| AC-3 (fires-at-all sub-check) | Stage-2 counters produce non-default values under simulated clicks | Hybrid | new `apps/pixel/e2e/agent-sig.spec.ts` (Playwright), mirrors confirmed-achievable `fingerprint-v3.spec.ts` pattern; precondition: built pixel + browser | A |
| AC-4 | agent_sig persists at ingest and round-trips | Hybrid (Docker-gated) | new integration test in `tests/integration/`; correct insertion site re-confirmed live pass 3 (event_rows/pg_insert(Event) block, L375-422) | C |
| AC-5 | Sweep classifies real non-null agent_sig fixture | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_ws2_session_classifier.py tests/unit/test_ws2_zero_import.py -m unit` (marker present on both branch files, confirmed via `git show` pass 3) | B |
| AC-6 | Classification visible to site owner | Agent-Probe (reclassified, confirmed consistent everywhere) | manual visual check at the 3 inline sites | D |
| AC-7 | No session dropped/blocked by classification | Hybrid (Docker-gated) | new/extended integration test | C |
| AC-8 | is_emailable_identity() unaffected at all 3 call sites | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py tests/unit/test_visibility_only_flags_no_leak.py -m unit` | B |
| AC-9 | Visibility-only flags do not trip is_emailable_identity() | Fully-Automated | same command as AC-8 (new test file) | B |
| AC-10 | Migration re-chains onto live head | Fully-Automated (offline) | `alembic -c apps/api/alembic.ini heads` (confirmed single head `f1a7c3e05b92` live pass 3) + `alembic upgrade <from>:<to> --sql` | A / D (live round-trip) |
| AC-11 | Mock mode works end-to-end | Fully-Automated | targeted suite with `MOCK_EXTERNAL_APIS=true` | B |
| AC-12 | Live Playwright/CDP corpus true-positive rate | Agent-Probe | documented post-ship check | D |
| AC-13 | False-positive rate on real human fixtures | Agent-Probe | documented lab-corpus check | D |
| AC-14 | Live wild-session validation | Agent-Probe | documented live check — partial real evidence now exists for Claude-in-Chrome (NOT-VIABLE, see correction above); Comet/Operator/Atlas remain fully unmeasured | D |
| structural guardrail | ws2 modules import nothing from cadence_bot_flag/agent_classifier | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_ws2_zero_import.py -m unit` | B |

gap-resolution legend:
- A — proven now / correctness confirmed live against a stable, clean current tree (HEAD `5293cbc`,
  no rebase/merge in progress) this cycle; fully execution-ready
- B — fixed directly in the plan body (Implementation Checklist text), confirmed correct across
  all 3 cycles; Execute-Agent Instructions below retained as redundant confirmation only
- C — deferred to Docker-gated integration tier, repo-wide precedent, not this plan's defect
- D — known-gap residual: AC-6 (component-render test infra gap), AC-10 live round-trip
  (Docker-gated), AC-12/13/14 (pre-accepted SPEC Known-Gaps, AC-14 now partially informed by real
  evidence for one product class — see correction above)

C-4 reconciliation: `strategy:` carries only Fully-Automated/Hybrid/Agent-Probe. AC-12/13/14 carry
`strategy: Agent-Probe` (a documented manual check is a real proving mechanism), `gap-resolution:
D` marks them as named residuals, not silent passes.

Legacy line form (retained so existing validate-contract consumers still parse):
- pixel bootstrap/consent (AC-1, AC-2): Fully-automated: `pytest tests/unit/test_pixel.py -q` (marker drop confirmed in plan body, re-run live pass 3: 72 passed)
- pixel byte budget size (AC-3): Fully-automated: `pytest tests/unit/test_pixel_fingerprint.py::TestPixelSizeLimit::test_under_6kb_gzipped tests/unit/test_pixel.py -q`
- pixel byte budget fires-at-all (AC-3): Hybrid: new Playwright spec, pattern confirmed achievable
- ingest persistence (AC-4, AC-7): Hybrid: new integration test, correct insertion site re-confirmed; precondition: docker-compose Postgres/Redis up
- classifier sweep (AC-5): Fully-automated: `pytest tests/unit/test_ws2_session_classifier.py tests/unit/test_ws2_zero_import.py -m unit`
- dashboard badge (AC-6): Agent-probe: manual visual check, badge site(s) confirmed at 3 inline locations
- emailability guardrail (AC-8, AC-9): Fully-automated: `pytest tests/unit/test_agent_origin_exclusion.py tests/unit/test_visibility_only_flags_no_leak.py -m unit`
- migration chain (AC-10): Fully-automated (offline): `alembic heads` + `--sql` validation; known-gap: live round-trip Docker-gated
- mock mode (AC-11): Fully-automated: targeted suite with MOCK_EXTERNAL_APIS=true

Dimension findings:
- Infra fit: PASS — every touchpoint file path re-confirmed resolving against a clean, stable
  live tree (HEAD `5293cbc`, no rebase/merge in progress). No container/infra/runtime surface
  touched.
- Test coverage: PASS — all 7 cycle-1 corrections (E1-E7) and both cycle-2 corrections
  (E8 + citation refresh) independently re-verified correct and stable this pass. 72/72 pixel
  tests pass live.
- Breaking changes: PASS — every schema/config/column change confirmed additive and
  nullable/default-OFF; `is_emailable_identity()`'s 3-parameter signature re-confirmed unchanged,
  now against a clean (non-mid-diff) file — the strongest form of this check across all 3 passes.
- Security surface: PASS — D1's visibility-only design re-confirmed structurally sound: zero-touch
  of the emailability guard, no 4th parameter, `is_agent_operated`/`is_bot_suspect` absent from
  the function body.
- Environmental pre-condition (from pass 2): RESOLVED — the interactive rebase found mid-pass-2 has
  fully completed; the shared tree is now stable and every WS2-relevant citation matches the
  plan's true target state. E8's Step 0a guard remains a permanent, correct standing safeguard
  (not a live blocker) given this repo's demonstrated concurrent-session history.
- [NEW pass 3] Byte-budget margin: CONCERN (advisory, non-blocking) — 233B live headroom is real
  and tight; plausible but not certain first-attempt gate failure; already handled by the plan's
  own Step 2 trim-first design; this pass adds one concrete refinement (prefer short wire-key
  names from the start) directly into Step 1.4/Step 2.4 above.
- [NEW pass 3] Feasibility probe accuracy: INFORMATIONAL (non-blocking) — corrected a stale
  INCONCLUSIVE citation to the file's actual current NOT-VIABLE (partial) verdict; reinforces D2,
  does not require any plan-body change beyond this contract's own correction.

Open gaps:
- AC-4/AC-7 integration test — Docker-gated, cannot run in this VALIDATE session (repo-wide
  precondition, not this plan's defect).
- AC-10 live migration round-trip — Docker-gated (repo-wide precedent).
- AC-6 full render check — Agent-Probe by necessity; tracked as a repo-wide backlog candidate in
  `cadence-bot-flag-deferred-gates_NOTE_26-07-26.md`, not a new gap this plan introduces.
- AC-12/AC-13/AC-14 — pre-accepted SPEC Known-Gaps; AC-14 now has partial real evidence for one
  product class (Claude-in-Chrome, NOT-VIABLE) — see correction above; still Known-Gap overall
  since Comet/Operator/Atlas remain unmeasured.
- [advisory, pass 3] Byte-budget margin (233B, live-verified) — real risk of a first-attempt Step 2
  gate failure; mitigated by the plan's own trim-first design, sharpened by this pass's Step
  1.4/Step 2.4 refinement (prefer short wire-key names from the start).
- The concurrent-rebase hazard from pass 2 is now RESOLVED, not open — retained only as historical
  record in the Cycle-1/Cycle-2 Continuity Re-Verification table above and as the permanent Step 0a
  standing guard (which is a checklist item, not an open gap).

What this coverage does NOT prove:
- The Fully-Automated pixel unit tests (AC-1, AC-2) are string/regex-position checks against raw
  source text — they prove the collector code is textually positioned correctly, NOT that it
  executes correctly in a real browser. Real-browser execution proof is E2's Playwright spec
  (AC-3 fires-at-all) and AC-12 (Known-Gap, real automation products).
- The byte-budget gate (AC-3) proves the CURRENT measured size only; it does not guarantee future
  pixel edits stay under budget — every future change must re-run this gate. This pass additionally
  does NOT prove the exact byte cost of the not-yet-written Stage-1/Stage-2 collector code — the
  233B-headroom falsifiability judgment above is a reasoned estimate, not a measurement of code
  that does not exist yet; Step 2's live re-measure is the actual proof, required regardless.
- AC-5's ported unit test proves the classifier's pure-function logic against synthetic fixtures;
  it does not prove real Playwright/Selenium/Comet sessions actually trip Stage 1/Stage 2 in
  production (AC-12/AC-14, Known-Gap/Agent-Probe) — though AC-14 now has one real negative data
  point (Claude-in-Chrome does not trip Stage 1) that the pre-implementation classifier logic
  cannot itself demonstrate.
- AC-8/AC-9's unit tests prove the guard function's behavior in isolation with mocked sessions;
  they do not exercise a live campaign send or export against a real database.
- The offline `--sql` migration validation (AC-10) proves the DDL is syntactically valid and
  reversible; it does not prove a live round-trip against a real Postgres instance succeeds
  (Known-Gap, Docker-gated, consistent with every other pending migration in this codebase).
- AC-6's eventual Agent-Probe visual check proves the badge renders correctly for the person who
  performed the check, on the fixtures used; it does not prove correctness across all
  browsers/screen sizes, nor does it run automatically on any future change (no regression
  protection until component-render test infra exists — repo-wide backlog candidate).
- This pass's re-verification confirms the plan's citations are correct against a clean, stable
  HEAD right now; it does NOT prove no further concurrent drift occurs between now and EXECUTE
  start — E8's Step 0a pre-flight check is the standing safeguard for that, not a one-time
  guarantee.

Execute-Agent Instructions (binding — apply these corrections instead of the literal checklist
text where they conflict; do not silently follow the plan's original wording where noted):

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Drop `-m unit` from the Step 1 and Step 2 test-gate commands. Present directly in the plan body; confirmed correct across all 3 cycles — live-run pass 3, 72 passed. | Step 1 and Step 2 test-gate execution |
| E2 | Add `apps/pixel/e2e/agent-sig.spec.ts` (Playwright), mirroring the `fingerprint-v3.spec.ts` pattern (`interceptIngest`/`fixture`/`settle` from `./harness`). Present directly in the plan body. Re-confirmed pass 3: pattern exists and is directly reusable; all 3 helpers confirmed exported live from `harness.ts`. Proving command: `cd apps/pixel && npm run build && npx playwright test e2e/agent-sig.spec.ts`. | Step 2, "fires at all" pass condition |
| E3 | Persist `agent_sig` in the `event_rows` dict-list / `pg_insert(Event)` block in `apps/api/routers/events.py` (L375-422 at fresh pass-3 HEAD — the block that also sets `link_marker` and `is_flagged_abuse`), NOT via the `fp3_value` pattern in `_process_signal_events()` (L525-606 at fresh HEAD, writes `pg_insert(Visitor)`). Present directly in the plan body. Re-confirmed pass 3 as the single highest-value correction in this plan — following the original literal Step 3.5 text would have silently failed AC-4 while every other gate looked green. | Step 3.5, ingest persistence site selection |
| E4 | AC-6/Step 6 reclassified to Agent-Probe (both legs). No shared badge component exists — `is_bot_suspect` is rendered inline at 3 confirmed sites. Present directly in the plan body, confirmed consistent across all 4 locations across all 3 passes. | Step 6, badge target location + test tier |
| E5 | Write a NEW behavioral test for Step 1 (no existing assertion to "update" — `test_has_bot_detection` is a non-behavioral string check). Present directly in the plan body, confirmed unconditional across all 3 passes. | Step 1 test-gate authoring |
| E6 | Scheduler registration file confirmed `apps/api/jobs/scheduler.py`, `cadence_bot_flag_sweep` pattern at L566-569 at fresh pass-3 HEAD (1-line drift from "~565-569," non-blocking). Present directly in the plan body, hedge removed. | Step 4.6 |
| E7 | Use `postgresql.JSONB` (not plain `JSON`) for the new `agent_sig` column, plain `Column(...)` declarative style. Confirmed unchanged in Step 3.3, Touchpoints, and Public Contracts across all 3 passes. | Step 3.3, column type/style choice |
| E8 | Before running Step 0 (or any edit), execute-agent MUST run `git status` on the plan's `Work context` working tree and confirm: (a) no `interactive rebase in progress` / `merge in progress` message appears, and (b) `git rev-parse --abbrev-ref HEAD` returns `devjulley` (not `HEAD`/detached). If either check fails, STOP IMMEDIATELY — report BLOCKED with the exact `git status` output and wait; never `git rebase --abort`/`--continue` on someone else's in-progress operation. Once confirmed clean, re-verify EVERY line-number citation in this plan via grep before editing. **Now folded permanently into the checklist body as Step 0a (confirmed present, pass 2). Live-tested pass 3: Step 0a would PASS cleanly right now (clean tree, HEAD `5293cbc`, branch `devjulley`, not detached).** | Before Step 0, and before any file edit if execution is interrupted and resumed |
| [NEW E9, advisory] | When writing Step 1.4's wire-key JSON shape, prefer short/abbreviated key names (e.g. single- or two-letter keys) over the full descriptive names shown for illustration in Public Contracts, on the FIRST implementation attempt. Re-measure with the test's own method (`gzip.compress`, not `gzip -9 -c \| wc -c` — a confirmed 15B discrepancy at this margin) before assuming a trim cycle is needed. This is advisory guidance tightening Step 1.4/Step 2.4, not a new checklist step — see the Byte-Budget Falsifiability Assessment above for the reasoning. | Step 1.4, Step 2 first measurement |

Backlog artifacts: none new — AC-6's component-render test infra gap and the migration
live-round-trip gap are both already tracked in existing backlog notes referenced above. The
concurrent-rebase finding (E8) is now resolved and needs no new artifact; the byte-budget margin
and feasibility-probe correction are both fully captured inline in this contract, not durable
backlog items.

Gate: CONDITIONAL

Accepted by: session (autonomous /goal execution) — pass 3, 2 completed supplement cycles behind
this plan. All 8 prior corrections (E1-E8) independently re-verified correct against a clean,
stable HEAD with zero new design gaps found this pass. The 2 residual items this pass surfaced —
(1) the 233B byte-budget margin (advisory CONCERN, already handled by the plan's own Step 2
trim-first design, sharpened with one concrete refinement E9) and (2) the feasibility-probe
citation correction (informational, reinforces D2, requires no plan change) — are both
non-blocking: neither is a design defect, both are execute-time-relevant context rather than
checklist gaps. This plan is execute-ready. Convergence judgment: **CONVERGED.** Cycle 1 found 7
real design-quality gaps and fixed them; cycle 2 found 1 real environmental/process gap (E8) and
turned it into a permanent standing guard; this pass (cycle 3) found 0 new design gaps — only
confirmations that the prior fixes hold, one informational evidence correction, and one advisory
execution-time risk note that the plan already structurally anticipates. Further PVL passes on
this plan would very likely either re-confirm this same stable state or surface the same class of
environmental noise (byte-count drift, migration-head drift) that Steps 0/0a/2 are already
explicitly designed to absorb — marginal value of a pass 4 is low. Recommended: proceed to EXECUTE.

## Strategy Recommendation for VALIDATE

**Recommended: Sequential, single `vc-validate-agent` (sonnet).** Signal count: S1 (multi-package:
pixel + api + web = 3 packages, present), S2 (schema surface touched — 2 additive migrations,
present), S6 absent (no auth/billing/destructive-migration class), S7 present (13-15 files in
blast radius) → score 3/7 (MEDIUM by the threshold table, but the work is NOT naturally
parallelizable — the emailability-tier proof (Step 5) structurally depends on the classifier
existing (Step 4), which depends on persistence (Step 3), which depends on the byte-budget shape
being locked (Step 2). A single sequential validate pass following the plan's own dependency chain
is more coherent than fanning out 6 validators who would each need the same upstream context).
Alternatives considered: **parallel subagents** (rejected — steps are sequentially dependent, not
independent investigation branches); **agent team** (rejected — no adversarial or cross-file
coordination need beyond what a single validator can reason through sequentially); **workflow**
(rejected — 6 fixed steps with no repeated sub-task shape, doesn't benefit from a pipeline
template).

## Autonomous Goal Block

SESSION GOAL: Activate WS2's dormant agent-session classifier — close tracker.js's
navigator.webdriver blindspot, restore a byte-budgeted agent_sig signal after the consent gate,
persist it on the Event row (per E3), port the classifier from
feat/ws2-agent-session-classifier, wire it visibility-only (never touching
is_emailable_identity()), surface a dashboard badge at the 3 confirmed inline sites (per E4).
Charter + umbrella plan: N/A — single standalone COMPLEX plan, not a phase program. No umbrella
plan with `## Stable Program Goal` exists for this work (confirmed: no
`process/features/agent-native-revenue/` folder exists on disk; no other umbrella references this
plan).
Autonomy: standard /goal autonomous execution rules apply — CONDITIONAL findings get applied via
the Execute-Agent Instructions table (E1-E9) above and execution proceeds without pausing; BLOCKED
items go to backlog with continuation; irreversible/outward-facing actions without explicit
contract instruction are a hard stop.
Hard stop conditions / safety constraints:
- Never let `is_emailable_identity()` gain a 4th parameter or read `is_agent_operated`/
  `is_bot_suspect` — this is the plan's single highest-priority guardrail (D1), reconfirmed live
  at pass 3 against a clean, non-mid-diff file.
- Never apply any migration against a real/shared environment — offline `--sql` validation only;
  live apply is a separate explicit human operator action.
- Never exceed the pixel's `<6000` gzip byte gate; if Step 2's budget check fails after trimming,
  stop and report rather than silently expanding the gate threshold. Given the live-confirmed 233B
  margin, budget for at least one trim-and-remeasure cycle as a normal, expected outcome (E9).
- Never bypass the EU consent hold — `agent_sig` collection must stay strictly after the
  `GATED`/`consentDecision` assignment (tracker.js:507-508, reconfirmed at pass 3's fresh HEAD).
- Never merge or check out `feat/ws2-agent-session-classifier` — read via `git show` only (D4).
- Never introduce new component-render test infrastructure as a side effect of AC-6 (E4) — that
  is a named repo-wide backlog candidate, out of this plan's scope.
- Follow Execute-Agent Instructions E1-E9 as binding — they correct the literal checklist text
  where the two conflict (E3 in particular: the checklist's Step 3.5 "grep fp3_value" instruction
  is wrong and must not be followed literally).
Next phase: EXECUTE — `process/features/pixel/active/ws2-agent-session-activation_07-08-26/ws2-agent-session-activation_PLAN_07-08-26.md`
Validate contract: inline in plan (see `## Validate Contract` section above)
Execute start: Step 0 (`alembic -c apps/api/alembic.ini heads`) → Step 0a (git-state pre-flight
guard, E8) → Step 1 (tracker.js edit, apply E1/E5/E9) → Step 2 (byte-budget checkpoint, apply
E1/E2/E9 — hard gate, expect at least one trim cycle) → Step 3 (ingest persistence, apply E3/E7) →
Step 4 (classifier port, apply E6) → Step 5 (visibility-only wiring + AC-9 test) → Step 6
(dashboard badge, apply E4). Fully-auto gates: corrected pixel unit test commands (72 passing
live at pass 3), ws2 classifier unit tests (`-m unit`, marker present on branch), emailability
guard tests (`-m unit`). New e2e spec required: `apps/pixel/e2e/agent-sig.spec.ts` (E2). Probe
scenario: AC-6 manual visual check at the 3 sites named in E4. High-risk pack: no (no
auth/billing/destructive-migration class touched; migration is additive/offline-only this
session).

---

**Status:** DONE
**Summary:** COMPLEX plan written for WS2 Agent-Session Activation at
`process/features/pixel/active/ws2-agent-session-activation_07-08-26/ws2-agent-session-activation_PLAN_07-08-26.md`
— 6 sequenced steps (tracker.js edit → byte-budget checkpoint → ingest persistence → classifier
port → visibility-only wiring → dashboard badge), all 14 SPEC ACs traced to a step and a test gate,
INNOVATE's 4 decisions (D1-D4) carried forward without re-litigation, live-measured constraints
re-confirmed this session (alembic head `f1a7c3e05b92` single-head; tracker.min.js 5688-5692B
gzip, ~308-312B headroom), the riskiest element (D2's Stage-2 proxy shape) given an explicit
"fires at all AND under budget" pass condition in Step 2, the known limitation (visibility-only
doesn't stop pre-sweep budget burn) stated explicitly rather than buried, and the customer-visible
release-note item called out.
**Concerns/Blockers:** None blocking. Two items require live confirmation at implementation time
rather than plan time (both explicitly flagged inline, not silently assumed): (1) `alembic heads`
must be re-run immediately before each migration is authored — this repo has a documented history
of concurrent-migration collisions; (2) the exact scheduler-registration file path and the exact
dashboard-badge component file path are named as "confirm via grep before implementing" rather
than hardcoded, since neither was directly inspected during PLAN (out of this plan's read list,
consistent with COMPLEX-plan practice of not over-specifying implementation details grep can
resolve cheaply at EXECUTE time).

PHASE_COMPLETE: PLAN — process/features/pixel/active/ws2-agent-session-activation_07-08-26/ws2-agent-session-activation_PLAN_07-08-26.md written. Proceed to VALIDATE.
