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
   `schemas/events.py` to confirm client/server key-name agreement, e.g. `_asig`).
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

This step exists specifically to catch the two failure modes INNOVATE flagged: (a) exceeding the
308B headroom, or (b) shrinking Stage 2 so far it never actually fires (reproducing WS2's
original dead-Stage-1 pathology in new form).

1. Re-measure current baseline BEFORE this step's edits are counted (already measured this
   session: `tracker.min.js` = 5782B gzip (re-verified post-rebase-resolution, supersedes
   earlier 5688-5692B pass-2 snapshot) / re-measure raw bytes live, do not trust this
   plan's snapshot):
   ```
   gzip -9 -c apps/pixel/src/tracker.min.js | wc -c
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
4. **If either condition fails:** first try trimming field precision (e.g. drop
   `ua_ch_headless` if UA-CH is unavailable in most browsers anyway, or reduce counter bit-width
   in the JSON key names). Only as a LAST RESORT, raise the gzip gate itself
   (`test_under_6kb_gzipped`'s `< 6000` threshold) — this requires explicit justification in the
   phase report with the measured byte count that forced it, and is a deviation from the SPEC's
   stated preference, not a default path.
5. Record the final measured byte count and headroom remaining in the phase report — this is
   AC-3's explicit evidence requirement, not optional bookkeeping.

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
3. Confirm all 3 existing call sites (`campaign_sender.py:283`, `csv_exporter.py:79`,
   `routers/campaigns.py:725`) are unmodified — grep each, diff against the pre-plan state, assert
   zero lines changed in this plan's blast radius at those 3 sites. This proves AC-8's "implemented
   consistently" requirement without touching production call-site code.

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
supersedes: 2026-08-07 (inner-pvl: phase-1) — PVL cycle 2 re-validation; cycle 1's
`SUPPLEMENT_APPLIED` folded E1–E7 into the plan body above, this pass re-verifies that folding
against live source and reports one NEW environmental finding (see below)

Parallel strategy: sequential
Rationale: Signal score 3/7 (S1 multi-package: pixel+api+web; S2 schema surface: 2 additive
migrations; S7: 13-15 files in blast radius) — MEDIUM by the threshold table, but the plan's 6
steps are sequentially dependent (Step 5's emailability proof depends on Step 4's classifier,
which depends on Step 3's persistence, which depends on Step 2's byte-budget shape). A single
sequential `vc-validate-agent` pass following the plan's own dependency chain was used both
passes, matching the plan's own Strategy Recommendation for VALIDATE.

## Cycle-2 Re-Verification of E1–E7 (all CONFIRMED correctly folded)

Every correction from cycle 1 was re-checked against live source in this pass. All 7 landed
correctly and none introduced a new defect:

| # | Cycle-1 fix | Cycle-2 confirmation |
|---|---|---|
| **E3** | Step 3.5 retargeted to `event_rows`/`pg_insert(Event)` block | **CONFIRMED CORRECT.** `event_rows = [` starts at devjulley-tip line 375, `link_marker=` at 404 — matches the plan's "~L375-422" citation exactly. `_process_signal_events()` (starts ~line 525 at devjulley tip, matches "~L540-606") independently confirmed to write `fp`/`fp3` onto the **Visitor** row via a `pg_insert(Visitor)...on_conflict_do_update` — a structurally different table, confirming the original E3 finding was correct and the retarget is safe. |
| E1 | `-m unit` stripped from Steps 1/2 gate commands | **CONFIRMED.** `grep -c "pytest.mark" tests/unit/test_pixel.py tests/unit/test_pixel_fingerprint.py` → 0/0. Both commands as written in the plan body now select tests correctly. |
| E2 | New `apps/pixel/e2e/agent-sig.spec.ts`, mirrors `fingerprint-v3.spec.ts` | **CONFIRMED ACHIEVABLE.** `fingerprint-v3.spec.ts` exists at devjulley tip using `interceptIngest`/`fixture`/`settle` imported from `./harness` — all three helpers confirmed exported live from `apps/pixel/e2e/harness.ts`. The pattern (goto fixture → drive interaction → poll intercepted ingest payload → assert field values) is directly reusable for the click-driven `agent_sig` assertions this step needs. Playwright config (`apps/pixel/playwright.config.ts`) confirmed compatible — zero-infra static server, chromium/webkit/firefox projects, `testMatch: /.*\.spec\.ts/` picks up any new file in `e2e/` automatically. |
| E4 | AC-6 reclassified Agent-Probe everywhere; 3 inline sites named; shared-component assumption removed | **CONFIRMED consistent across all 4 locations**: SPEC AC→Step traceability table (line 68), Verification Evidence (line 416), Step 6 test-gate header (line 397), and Touchpoints (dashboard badge bullet) all say Agent-Probe / inline-3-sites. No stray "Hybrid" or "shared component" language remains anywhere in the plan body. |
| E5 | Step 1 unconditionally requires a NEW behavioral test | **CONFIRMED.** Step 1's test-gate note now reads "No behavioral webdriver-exit assertion currently exists to 'update'... Write a NEW source-position regex test" — no longer conditional ("if such an assertion exists"). |
| E6 | Scheduler path/line confirmed, hedge removed | **CONFIRMED at devjulley tip**: `apps/api/jobs/scheduler.py`, `_cadence_bot_flag_sweep_job` at line 244, `id="cadence_bot_flag_sweep"` registration at line ~566-569 — matches the plan's "~565-569" citation. Step 4.6 no longer says "confirm exact path via grep." |
| E7 | `JSONB` (not `JSON`) + legacy `Column(...)` style | **CONFIRMED** in Step 3.3, Touchpoints, and Public Contracts (all three say `JSONB` / `Column(...)`, not `Mapped[...]`). |

## [NEW — pass 2] Environmental Pre-Condition: concurrent rebase invalidates live-tree line
citations at VALIDATE time (not a plan defect)

**Finding.** At the time of this VALIDATE pass (07-08-26), `git status` on the working tree at
`/Users/apple/getbeam` (the plan's own `Work context`) showed: `interactive rebase in progress;
onto 332b3a8` — branch `devjulley` is mid-replay of its own commit history onto a new base, with
HEAD currently detached at an intermediate checkpoint that has **not yet replayed** commit
`3528c00` ("feat(identity): fingerprint v3 with installed-font and audio probes" — the commit
`ORIG_HEAD` points at, i.e. devjulley's true pre-rebase tip).

This intermediate state is missing ~75 lines of `tracker.js` (the `fontFp()`/`audioFp()` probes)
and the accompanying `test_pixel_fingerprint.py` budget-raise (`5KB → 6KB` gzip). Effect,
independently confirmed for every touchpoint this plan cites:

| Touchpoint | Plan's citation (= devjulley tip / `ORIG_HEAD`) | Live tree right now (mid-rebase) | Verified match to `ORIG_HEAD`? |
|---|---|---|---|
| `tracker.js:4` (webdriver early-return) | line 4 | line 4 | Yes — unaffected |
| `tracker.js` consent-gate anchor | `consentDecision = GATED` at ~502, `OPTOUT` guard at ~503 (cited "501-504") | now at lines 411-412 | Yes, at `ORIG_HEAD` |
| `tracker.js` click listener | `addEventListener("click"` at line 628 | now at line 536 | Yes, at `ORIG_HEAD` |
| `tracker.js` `pushEvent`/`_fp3` site | lines 266-275 | unaffected (matches at both) | Yes |
| `apps/pixel/e2e/fingerprint-v3.spec.ts` | exists, pattern to mirror (E2) | **absent from live e2e/ dir** | Yes, exists at `ORIG_HEAD` |
| `tests/unit/test_pixel_fingerprint.py::TestPixelSizeLimit::test_under_6kb_gzipped`, `< 6000` | cited throughout (AC-3, Step 2, traceability, Verification Evidence) | live tree only has `test_under_5kb_gzipped`, `< 5000` (the pre-fingerprint-v3 test) | Yes, `test_under_6kb_gzipped` / `< 6000` exists at `ORIG_HEAD` line 222-224 |
| `tracker.min.js` gzip size | plan's own live measurement: 5688-5692B | live tree right now: **4842B** (matches the fingerprint-v3 commit message's stated pre-raise baseline, "4843B") | Yes — `ORIG_HEAD`'s `tracker.min.js` gzips to 5673B, consistent with the plan's 5688-5692B range |
| `alembic -c apps/api/alembic.ini heads` | expects single head | **currently reports 2 heads** (`c2f7a9d31b64`, `e9d2a4c71f68`) — rebase-intermediate migration-file set is incoherent | N/A — inherently unstable mid-rebase, must be re-run once the rebase resolves (Step 0 already mandates re-running this before each migration; this pass shows the instruction is genuinely load-bearing, not boilerplate) |
| `apps/api/jobs/scheduler.py` sweep-registration lines | "~565-569" | currently at ~553 (minor drift, same pattern) | Yes, at `ORIG_HEAD` (~565-569) |

**Root-cause conclusion:** every plan citation is **independently re-verified as correct** against
`git show ORIG_HEAD:<path>` (`ORIG_HEAD` = `3528c00`, devjulley's actual tip before this
unrelated rebase started). This is **not a plan defect** — it is a live, external git-state
hazard: an unrelated, concurrent operation on the shared working tree this plan's `Work context`
points at. The plan itself was written against, and is accurate for, devjulley's real tip.

**Why this matters for EXECUTE.** If `vc-execute-agent` started against the tree in its CURRENT
(mid-rebase) state, Step 1 would delete `tracker.js:4` and add `agent_sig` collection code onto a
version of the file that is missing the fingerprint-v3 probes — an edit that would either (a) get
silently lost/conflicted when the rebase later resumes and replays `3528c00`, or (b) leave the
repository in a state where `agent_sig` collection was added to the wrong base and the eventual
rebase completion re-introduces `fontFp()`/`audioFp()` on top without the classifier author ever
reconciling the two. Step 2's byte-budget gate would also be measured against the wrong baseline
(4842B, not 5673-5692B), and `test_under_6kb_gzipped` (the actual proving test) does not exist yet
in the live tree.

**Resolution — binding Execute-Agent Instruction, not a plan-body defect fix:** see **E8** below.
Given the fix required is "wait for/confirm resolution of an external git operation," not a plan
text correction, and it is fully mitigated by a single binding pre-flight check (same mechanism as
E1-E7), this is captured as an Execute-Agent Instruction rather than requiring a new
`SUPPLEMENT_APPLIED` fold into the checklist body — **see the Gate rationale below for why this
pass still routes through one more supplement cycle rather than treating E8 as sufficient on its
own.**

## Verification of Locked Decisions and Named Hazards (re-confirmed this pass)

- **G7 consent boundary** — CONFIRMED intact at `ORIG_HEAD`: `agent_sig` collection is specified
  to land after `consentDecision = GATED` (line ~502) and `consentBlocked()` (`return GATED &&
  consentDecision == null`, line 555) — both precede any point the plan's Step 1.2 could plausibly
  insert code, per the plan's own "before or interleaved with [the URL-param block], never before
  it" instruction. `pagehide`/beacon flush (`navigator.sendBeacon`, ~line 321-322;
  `addEventListener("pagehide", ...)`, ~line 706) confirmed present and unrelated to this plan's
  edits (task brief's "L238, L702" citations are in the right neighborhood — within a few lines of
  the confirmed real locations 238/706 — consistent with normal re-measurement variance, not a
  defect).
- **`is_emailable_identity()` exactly-3-parameters invariant** — CONFIRMED: signature at
  `apps/api/services/identity_classification.py:109-113` is exactly `provider,
  source_agent_visit_id=None, is_abuse_flagged=False`. This file shows as locally modified
  (`M`) in the current mid-rebase working tree, but the diff against `ORIG_HEAD` is purely
  **additive** (a new `PAID_PERSON_GRAPH_PROVIDERS` constant and a new helper function appended
  *after* `is_emailable_identity()`) — the guarded function itself is byte-identical. D1's
  guardrail is not at risk from the concurrent rebase.
- **3 call sites** (`campaign_sender.py:283`, `csv_exporter.py:79`, `routers/campaigns.py:725`)
  — all 3 confirmed present via live grep, matching the plan's citations exactly.
- **Migration safety / "live head moved once already"** — confirmed true, and moved again:
  pass-1 measured `f1a7c3e05b92` (single head); this pass finds 2 heads
  (`c2f7a9d31b64`, `e9d2a4c71f68`), a symptom of the same concurrent rebase above, not a second
  independent collision. Step 0's "re-verify before every migration, never assume stability
  across a session gap" instruction is reconfirmed as load-bearing.
- **Byte-budget gate falsifiability** — confirmed real and correctly specified: the gate is a
  genuine `assert len(compressed) < 6000` in `test_under_6kb_gzipped` (`ORIG_HEAD`, line 224), not
  a tautology; a regression would fail it.
- **Feasibility probe carry-forward** — `ws2-webdriver-assumption_FEASIBILITY_07-08-26.md`
  verdict **INCONCLUSIVE** re-confirmed still open; plan body re-scanned this pass for any claim of
  empirical support for the `navigator.webdriver` default-value assumption — none found. AC-14
  stays Known-Gap as before. Not re-probed (per task brief).

Test gates (C3 5-column table — ADDITIVE; existing consumers still parse the legacy line form below it):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | Tracker bootstrap does not short-circuit on webdriver alone; consent gating unchanged | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_pixel.py -q` (marker-drop now in plan body, confirmed correct) | A |
| AC-2 | agent_sig collection fires only after consentDecision/GATED resolution | Fully-Automated | same corrected command as AC-1 (new test case) | A |
| AC-3 | Pixel gzip size stays under 6000B/6144B | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_pixel_fingerprint.py::TestPixelSizeLimit::test_under_6kb_gzipped tests/unit/test_pixel.py -q` | A (once tree is off the concurrent rebase — see E8) |
| AC-3 (fires-at-all sub-check) | Stage-2 counters produce non-default values under simulated clicks | Hybrid | new `apps/pixel/e2e/agent-sig.spec.ts` (Playwright), mirrors confirmed-achievable `fingerprint-v3.spec.ts` pattern; precondition: built pixel + browser + tree off the concurrent rebase (E8) | A |
| AC-4 | agent_sig persists at ingest and round-trips | Hybrid (Docker-gated) | new integration test in `tests/integration/`; correct insertion site re-confirmed (event_rows/pg_insert(Event) block, plan body) | C |
| AC-5 | Sweep classifies real non-null agent_sig fixture | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_ws2_session_classifier.py tests/unit/test_ws2_zero_import.py -m unit` (marker present on both ported files, confirmed via `git show`) | B |
| AC-6 | Classification visible to site owner | Agent-Probe (reclassified, confirmed consistent everywhere) | manual visual check at the 3 inline sites | D |
| AC-7 | No session dropped/blocked by classification | Hybrid (Docker-gated) | new/extended integration test | C |
| AC-8 | is_emailable_identity() unaffected at all 3 call sites | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py tests/unit/test_visibility_only_flags_no_leak.py -m unit` | B |
| AC-9 | Visibility-only flags do not trip is_emailable_identity() | Fully-Automated | same command as AC-8 (new test file) | B |
| AC-10 | Migration re-chains onto live head | Fully-Automated (offline) | `alembic -c apps/api/alembic.ini heads` + `alembic upgrade <from>:<to> --sql` | A (offline, once concurrent rebase resolves — E8) / D (live round-trip) |
| AC-11 | Mock mode works end-to-end | Fully-Automated | targeted suite with `MOCK_EXTERNAL_APIS=true` | B |
| AC-12 | Live Playwright/CDP corpus true-positive rate | Agent-Probe | documented post-ship check | D |
| AC-13 | False-positive rate on real human fixtures | Agent-Probe | documented lab-corpus check | D |
| AC-14 | Live wild-session validation | Agent-Probe | documented live check | D |
| structural guardrail | ws2 modules import nothing from cadence_bot_flag/agent_classifier | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_ws2_zero_import.py -m unit` | B |

gap-resolution legend:
- A — proven now / correctness confirmed live against the plan's true target state (devjulley
  tip, `ORIG_HEAD`) this cycle; execution-ready once the concurrent rebase (E8) resolves
- B — fixed directly in the plan body (Implementation Checklist text), confirmed correct this
  cycle; Execute-Agent Instructions below retained as redundant confirmation only
- C — deferred to Docker-gated integration tier, repo-wide precedent, not this plan's defect
- D — known-gap residual: AC-6 (component-render test infra gap), AC-10 live round-trip
  (Docker-gated), AC-12/13/14 (pre-accepted SPEC Known-Gaps)

C-4 reconciliation: `strategy:` carries only Fully-Automated/Hybrid/Agent-Probe. AC-12/13/14 carry
`strategy: Agent-Probe` (a documented manual check is a real proving mechanism), `gap-resolution:
D` marks them as named residuals, not silent passes.

Legacy line form (retained so existing validate-contract consumers still parse):
- pixel bootstrap/consent (AC-1, AC-2): Fully-automated: `pytest tests/unit/test_pixel.py -q` (marker drop confirmed in plan body)
- pixel byte budget size (AC-3): Fully-automated: `pytest tests/unit/test_pixel_fingerprint.py::TestPixelSizeLimit::test_under_6kb_gzipped tests/unit/test_pixel.py -q`
- pixel byte budget fires-at-all (AC-3): Hybrid: new Playwright spec, pattern confirmed achievable
- ingest persistence (AC-4, AC-7): Hybrid: new integration test, correct insertion site re-confirmed; precondition: docker-compose Postgres/Redis up
- classifier sweep (AC-5): Fully-automated: `pytest tests/unit/test_ws2_session_classifier.py tests/unit/test_ws2_zero_import.py -m unit`
- dashboard badge (AC-6): Agent-probe: manual visual check, badge site(s) confirmed at 3 inline locations
- emailability guardrail (AC-8, AC-9): Fully-automated: `pytest tests/unit/test_agent_origin_exclusion.py tests/unit/test_visibility_only_flags_no_leak.py -m unit`
- migration chain (AC-10): Fully-automated (offline): `alembic heads` + `--sql` validation; known-gap: live round-trip Docker-gated
- mock mode (AC-11): Fully-automated: targeted suite with MOCK_EXTERNAL_APIS=true

Dimension findings:
- Infra fit: PASS — every touchpoint file path re-confirmed resolving against the plan's true
  target state (devjulley tip / `ORIG_HEAD`). No container/infra/runtime surface touched.
- Test coverage: PASS (was CONCERN pass-1, now resolved) — E1/E2/E4/E5 all confirmed correctly
  folded into the plan body and independently re-verified achievable against live source. The one
  residual item is not a test-coverage defect but the environmental pre-condition below (E8).
- Breaking changes: PASS — every schema/config/column change confirmed additive and
  nullable/default-OFF; `is_emailable_identity()`'s 3-parameter signature re-confirmed unchanged
  at the true target state.
- Security surface: PASS — D1's visibility-only design re-confirmed structurally sound this pass
  (zero-touch of the emailability guard, no 4th parameter, `is_agent_operated`/`is_bot_suspect`
  absent from the function body — even in the concurrently-modified `identity_classification.py`,
  the diff against the plan's true target state is purely additive after the guarded function).
- Environmental pre-condition (NEW this pass): CONCERN — see the dedicated section above. The
  working tree at the plan's own `Work context` path is mid an unrelated interactive rebase
  (`devjulley` rebasing onto `332b3a8`) that temporarily reverts several WS2 touchpoints
  (tracker.js, the pixel byte-budget test, events.py/scheduler.py line offsets, alembic head
  count) to a pre-fingerprint-v3 state. Every plan citation independently re-verified correct
  against the true target (`ORIG_HEAD`); this is an EXECUTE-time precondition, not a plan-body
  defect. See Execute-Agent Instruction **E8**.
- Cycle-1 supplement fold-in (E1-E7): PASS — see the dedicated re-verification table above; all
  7 corrections confirmed correctly present in the plan body with no new defects introduced.

Open gaps:
- AC-4/AC-7 integration test — Docker-gated, cannot run in this VALIDATE session (repo-wide
  precondition, not this plan's defect).
- AC-10 live migration round-trip — Docker-gated (repo-wide precedent).
- AC-6 full render check — Agent-Probe by necessity; tracked as a repo-wide backlog candidate in
  `cadence-bot-flag-deferred-gates_NOTE_26-07-26.md`, not a new gap this plan introduces.
- AC-12/AC-13/AC-14 — pre-accepted SPEC Known-Gaps, not new findings (per task brief, not
  re-raised here).
- **[NEW] Concurrent rebase in progress on the plan's `Work context` working tree** — see the
  dedicated section above and Execute-Agent Instruction E8. Transient/external to this plan;
  expected to resolve independently of this plan's own work, but MUST be confirmed resolved
  before Step 0 runs.

What this coverage does NOT prove:
- The Fully-Automated pixel unit tests (AC-1, AC-2) are string/regex-position checks against raw
  source text — they prove the collector code is textually positioned correctly, NOT that it
  executes correctly in a real browser. Real-browser execution proof is E2's Playwright spec
  (AC-3 fires-at-all) and AC-12 (Known-Gap, real automation products).
- The byte-budget gate (AC-3) proves the CURRENT measured size only; it does not guarantee future
  pixel edits stay under budget — every future change must re-run this gate.
- AC-5's ported unit test proves the classifier's pure-function logic against synthetic fixtures;
  it does not prove real Playwright/Selenium/Comet sessions actually trip Stage 1/Stage 2 in
  production (AC-12/AC-14, Known-Gap/Agent-Probe).
- AC-8/AC-9's unit tests prove the guard function's behavior in isolation with mocked sessions;
  they do not exercise a live campaign send or export against a real database.
- The offline `--sql` migration validation (AC-10) proves the DDL is syntactically valid and
  reversible; it does not prove a live round-trip against a real Postgres instance succeeds
  (Known-Gap, Docker-gated, consistent with every other pending migration in this codebase).
- AC-6's eventual Agent-Probe visual check proves the badge renders correctly for the person who
  performed the check, on the fixtures used; it does not prove correctness across all
  browsers/screen sizes, nor does it run automatically on any future change (no regression
  protection until component-render test infra exists — repo-wide backlog candidate).
- This pass's re-verification confirms the plan's citations are correct against devjulley's TRUE
  tip; it does NOT prove the concurrent rebase will resolve cleanly, nor does it prove no further
  concurrent drift occurs between now and EXECUTE start — E8's pre-flight check is the safeguard
  for that gap, not a guarantee against it recurring.

Execute-Agent Instructions (binding — apply these corrections instead of the literal checklist
text where they conflict; do not silently follow the plan's original wording where noted):

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Drop `-m unit` from the Step 1 and Step 2 test-gate commands. Now also present directly in the plan body (cycle-1 fold-in, confirmed cycle-2). Confirmed live: neither `tests/unit/test_pixel.py` nor `tests/unit/test_pixel_fingerprint.py` carries any `pytest.mark.unit` marker. | Step 1 and Step 2 test-gate execution |
| E2 | Add `apps/pixel/e2e/agent-sig.spec.ts` (Playwright), mirroring the `fingerprint-v3.spec.ts` pattern (`interceptIngest`/`fixture`/`settle` from `./harness`). Now also present directly in the plan body (cycle-1 fold-in). Confirmed cycle-2: pattern exists and is directly reusable at devjulley's true tip; helpers confirmed exported live. Proving command: `cd apps/pixel && npm run build && npx playwright test e2e/agent-sig.spec.ts`. | Step 2, "fires at all" pass condition |
| E3 | Persist `agent_sig` in the `event_rows` dict-list / `pg_insert(Event)` block in `apps/api/routers/events.py` (lines ~375-422 at devjulley tip — the block that also sets `link_marker` and `is_flagged_abuse`), NOT via the `fp3_value` pattern in `_process_signal_events()` (lines ~525-606). That function writes to the Visitor row (`fingerprint`/`fingerprint_v3` columns), a structurally different table and code path. Now also present directly in the plan body (cycle-1 fold-in). Re-confirmed cycle-2: this is the single highest-value correction in this plan — following the original literal Step 3.5 text would have silently failed AC-4 while every other gate looked green. | Step 3.5, ingest persistence site selection |
| E4 | AC-6/Step 6 reclassified to Agent-Probe (both legs). No shared badge component exists — `is_bot_suspect` is rendered inline at 3 confirmed sites. Now also present directly in the plan body (cycle-1 fold-in), confirmed consistent across all 4 locations cycle-2 (traceability table, Verification Evidence, Step 6, Touchpoints). | Step 6, badge target location + test tier |
| E5 | Write a NEW behavioral test for Step 1 (no existing assertion to "update" — `test_has_bot_detection` is a non-behavioral string check). Now also present directly in the plan body (cycle-1 fold-in), confirmed unconditional cycle-2. | Step 1 test-gate authoring |
| E6 | Scheduler registration file confirmed `apps/api/jobs/scheduler.py`, `cadence_bot_flag_sweep` pattern at lines ~565-569 at devjulley tip. Now also present directly in the plan body (cycle-1 fold-in), hedge removed, confirmed cycle-2. | Step 4.6 |
| E7 | Use `postgresql.JSONB` (not plain `JSON`) for the new `agent_sig` column, plain `Column(...)` declarative style. Now also present directly in the plan body (cycle-1 fold-in), confirmed cycle-2 in Step 3.3, Touchpoints, and Public Contracts. | Step 3.3, column type/style choice |
| **E8 (NEW this pass)** | **Before running Step 0 (or any edit), execute-agent MUST run `git status` on the plan's `Work context` working tree and confirm: (a) no `interactive rebase in progress` / `merge in progress` message appears, and (b) `git rev-parse --abbrev-ref HEAD` returns `devjulley` (not `HEAD`/detached). If either check fails, STOP IMMEDIATELY — do not touch any file, do not run `alembic heads`, do not edit `tracker.js`. Report BLOCKED with the exact `git status` output and wait for the concurrent operation to resolve (this is an external, unrelated git operation on a shared working tree — not something execute-agent should attempt to resolve itself, e.g. never run `git rebase --abort`/`--continue` on someone else's in-progress rebase without explicit human instruction). Once confirmed clean, re-verify EVERY line-number citation in this plan via grep (not by trusting the numbers literally) before editing, since line numbers can drift for reasons beyond this specific rebase.** | Before Step 0, and before any file edit if execution is interrupted and resumed |

Backlog artifacts: none new — AC-6's component-render test infra gap and the migration
live-round-trip gap are both already tracked in existing backlog notes referenced above. The
concurrent-rebase finding (E8) is transient/environmental, not a durable backlog item — no new
artifact needed.

Gate: CONDITIONAL

Accepted by: N/A — pass 2. All 7 pass-1 CONCERNs (E1-E7) are CONFIRMED resolved and correctly
folded into the plan body against live source, with no new defects introduced by the fold-in —
that part of this plan is execute-ready as-is. However, this pass surfaced ONE new, substantive,
safety-relevant finding not present in pass 1: the plan's own `Work context` working tree is
currently mid an unrelated interactive rebase that temporarily invalidates the live state of
several cited touchpoints (see the dedicated section above). Per this pass's loop protocol, a NEW
substantive gap routes through a SUPPLEMENT REQUEST rather than being silently accepted as
execute-eligible, specifically because the blast radius of getting this wrong is high (Step 1
would edit `tracker.js` against the wrong base if EXECUTE started blind against the current
transient state) and a permanent checklist-level pre-flight guard (not just a contract-only
instruction) is the more robust fix, mirroring cycle 1's own stated rationale for folding
contract-only instructions into the checklist body. Recommended resolution: fold Execute-Agent
Instruction **E8** into the plan body as an expansion of Step 0 (e.g. "Step 0a — confirm no
git rebase/merge in progress"), the same treatment cycle 1 gave E1-E7. This is a SUPPLEMENT
REQUEST for exactly one gap (see the SUPPLEMENT REQUEST block in the response accompanying this
contract write); once folded, or once a human/orchestrator confirms the concurrent rebase has
resolved, this plan is execute-ready — the underlying plan design has no other open concerns.

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
the Execute-Agent Instructions table (E1-E8) above and execution proceeds without pausing; BLOCKED
items go to backlog with continuation; irreversible/outward-facing actions without explicit
contract instruction are a hard stop.
Hard stop conditions / safety constraints:
- Never let `is_emailable_identity()` gain a 4th parameter or read `is_agent_operated`/
  `is_bot_suspect` — this is the plan's single highest-priority guardrail (D1), reconfirmed live.
- Never apply any migration against a real/shared environment — offline `--sql` validation only;
  live apply is a separate explicit human operator action.
- Never exceed the pixel's `<6000` gzip byte gate; if Step 2's budget check fails after trimming,
  stop and report rather than silently expanding the gate threshold.
- Never bypass the EU consent hold — `agent_sig` collection must stay strictly after the
  `GATED`/`consentDecision` assignment (tracker.js:507-508).
- Never merge or check out `feat/ws2-agent-session-classifier` — read via `git show` only (D4).
- Never introduce new component-render test infrastructure as a side effect of AC-6 (E4) — that
  is a named repo-wide backlog candidate, out of this plan's scope.
- Never attempt to resolve the concurrent interactive rebase found at VALIDATE pass 2 (`git
  rebase --abort`/`--continue`) — that is an unrelated, external git operation on a shared
  working tree; report BLOCKED and wait instead (E8).
- Follow Execute-Agent Instructions E1-E8 as binding — they correct the literal checklist text
  where the two conflict (E3 in particular: the checklist's Step 3.5 "grep fp3_value" instruction
  is wrong and must not be followed literally).
Next phase: EXECUTE — `process/features/pixel/active/ws2-agent-session-activation_07-08-26/ws2-agent-session-activation_PLAN_07-08-26.md`
Validate contract: inline in plan (see `## Validate Contract` section above)
Execute start: Step 0 (`alembic -c apps/api/alembic.ini heads`) → Step 1 (tracker.js edit, apply
E1/E5) → Step 2 (byte-budget checkpoint, apply E1/E2 — hard gate) → Step 3 (ingest persistence,
apply E3/E7) → Step 4 (classifier port, apply E6) → Step 5 (visibility-only wiring + AC-9 test) →
Step 6 (dashboard badge, apply E4). Fully-auto gates: corrected pixel unit test commands, ws2
classifier unit tests (`-m unit`, marker present), emailability guard tests (`-m unit`). New e2e
spec required: `apps/pixel/e2e/agent-sig.spec.ts` (E2). Probe scenario: AC-6 manual visual check
at the 3 sites named in E4. High-risk pack: no (no auth/billing/destructive-migration class
touched; migration is additive/offline-only this session).

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
