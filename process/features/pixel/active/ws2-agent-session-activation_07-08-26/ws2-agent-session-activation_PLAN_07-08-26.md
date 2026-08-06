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
  (tracker.js:628) — no new `addEventListener` call: (a) one boolean "no `pointermove` observed
  before first interaction" and (b) two integer counters (dead-center clicks / total clicks).
  Raising the gzip gate is last resort only, after measuring the trimmed shape and recording the
  real byte count.
- **D3 — line 4 deleted outright**, no replacement at that position. The whole `agent_sig`
  collection block sits AFTER the `GATED`/`consentDecision` assignment (tracker.js:501-504),
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
  piggyback Stage-2 proxy counters onto the existing click listener (~line 628)
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

### Step 1 — `tracker.js`: delete early-return, add byte-budgeted `agent_sig` collector (AC-1, AC-2, D3)

1. Delete `apps/pixel/src/tracker.js:4` (`if (navigator.webdriver === true) return;`) outright.
   No replacement statement at that line. Bootstrap continues unconditionally from
   `document.currentScript` onward, exactly as it does for every other visitor today.
2. Immediately AFTER `var consentDecision = GATED ? ... : "g";` and the `if (GATED &&
   consentDecision === "d") OPTOUT = true;` line (tracker.js:501-504 in the pre-change file — the
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
3. In the EXISTING click listener (tracker.js:628, `document.addEventListener("click", ...)`),
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
   session: `tracker.min.js` = 5688-5692B gzip / 13378B raw — re-measure live, do not trust this
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

Parallel strategy: sequential
Rationale: Signal score 3/7 (S1 multi-package: pixel+api+web; S2 schema surface: 2 additive
migrations; S7: 13-15 files in blast radius) — MEDIUM by the threshold table, but the plan's 6
steps are sequentially dependent (Step 5's emailability proof depends on Step 4's classifier,
which depends on Step 3's persistence, which depends on Step 2's byte-budget shape). A single
sequential `vc-validate-agent` pass following the plan's own dependency chain was used, matching
the plan's own Strategy Recommendation for VALIDATE.

Test gates (C3 5-column table — ADDITIVE; existing consumers still parse the legacy line form below it):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 | Tracker bootstrap does not short-circuit on webdriver alone; consent gating unchanged | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_pixel.py -q` — **see Execute-Agent Instruction E1: drop `-m unit`, neither test file carries that marker** | B |
| AC-2 | agent_sig collection fires only after consentDecision/GATED resolution | Fully-Automated | same corrected command as AC-1 (new test case) | B |
| AC-3 | Pixel gzip size stays under 6000B/6144B | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_pixel_fingerprint.py::TestPixelSizeLimit::test_under_6kb_gzipped tests/unit/test_pixel.py -q` — see E1 | A |
| AC-3 (fires-at-all sub-check) | Stage-2 counters produce non-default values under simulated clicks | Hybrid | see **Execute-Agent Instruction E2**: new `apps/pixel/e2e/agent-sig.spec.ts` (Playwright), precondition: built pixel + browser | B |
| AC-4 | agent_sig persists at ingest and round-trips | Hybrid (Docker-gated) | new integration test in `tests/integration/` — see **Execute-Agent Instruction E3** for correct insertion site | C |
| AC-5 | Sweep classifies real non-null agent_sig fixture | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_ws2_session_classifier.py tests/unit/test_ws2_zero_import.py -m unit` (marker present on both ported files — confirmed via `git show`, this command is correct as-is) | B |
| AC-6 | Classification visible to site owner | Agent-Probe (see **Execute-Agent Instruction E4** — reclassified) | manual visual check at the badge site(s) located per E4 | D |
| AC-7 | No session dropped/blocked by classification | Hybrid (Docker-gated) | new/extended integration test | C |
| AC-8 | is_emailable_identity() unaffected at all 3 call sites | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py tests/unit/test_visibility_only_flags_no_leak.py -m unit` | B |
| AC-9 | Visibility-only flags do not trip is_emailable_identity() | Fully-Automated | same command as AC-8 (new test file) | B |
| AC-10 | Migration re-chains onto live head | Fully-Automated (offline) | `alembic -c apps/api/alembic.ini heads` + `alembic upgrade <from>:<to> --sql` | A (offline) / D (live round-trip) |
| AC-11 | Mock mode works end-to-end | Fully-Automated | targeted suite with `MOCK_EXTERNAL_APIS=true` | B |
| AC-12 | Live Playwright/CDP corpus true-positive rate | Agent-Probe | documented post-ship check | D |
| AC-13 | False-positive rate on real human fixtures | Agent-Probe | documented lab-corpus check | D |
| AC-14 | Live wild-session validation | Agent-Probe | documented live check | D |
| structural guardrail | ws2 modules import nothing from cadence_bot_flag/agent_classifier | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_ws2_zero_import.py -m unit` | B |

gap-resolution legend:
- A — proven now (gate passes in this cycle, command verified live at VALIDATE)
- B — fixed via the Execute-Agent Instructions below (execute-agent must follow the corrected
  command/instruction, not the plan's literal original text where they conflict)
- C — deferred to Docker-gated integration tier, repo-wide precedent, not this plan's defect
- D — known-gap residual: AC-6 (component-render test infra gap, see E4), AC-10 live round-trip
  (Docker-gated), AC-12/13/14 (pre-accepted SPEC Known-Gaps)

C-4 reconciliation: `strategy:` carries only Fully-Automated/Hybrid/Agent-Probe. AC-12/13/14 carry
`strategy: Agent-Probe` (a documented manual check is a real proving mechanism), `gap-resolution:
D` marks them as named residuals, not silent passes.

Legacy line form (retained so existing validate-contract consumers still parse):
- pixel bootstrap/consent (AC-1, AC-2): Fully-automated: `pytest tests/unit/test_pixel.py -q` (marker dropped, see E1)
- pixel byte budget size (AC-3): Fully-automated: `pytest tests/unit/test_pixel_fingerprint.py::TestPixelSizeLimit::test_under_6kb_gzipped tests/unit/test_pixel.py -q`
- pixel byte budget fires-at-all (AC-3): Hybrid: new Playwright spec, see E2
- ingest persistence (AC-4, AC-7): Hybrid: new integration test, correct insertion site per E3; precondition: docker-compose Postgres/Redis up
- classifier sweep (AC-5): Fully-automated: `pytest tests/unit/test_ws2_session_classifier.py tests/unit/test_ws2_zero_import.py -m unit`
- dashboard badge (AC-6): Agent-probe: manual visual check, badge site(s) located per E4
- emailability guardrail (AC-8, AC-9): Fully-automated: `pytest tests/unit/test_agent_origin_exclusion.py tests/unit/test_visibility_only_flags_no_leak.py -m unit`
- migration chain (AC-10): Fully-automated (offline): `alembic heads` + `--sql` validation; known-gap: live round-trip Docker-gated
- mock mode (AC-11): Fully-automated: targeted suite with MOCK_EXTERNAL_APIS=true

Dimension findings:
- Infra fit: PASS — every touchpoint file path resolves (verified live: tracker.js, events.py,
  schemas/events.py, event.py, visitor.py, identity_classification.py, config.py, jobs/scheduler.py,
  campaign_sender.py:283, csv_exporter.py:79, routers/campaigns.py:725). No container/infra/runtime
  surface touched.
- Test coverage: CONCERN — two Step test-gate commands include `-m unit` against test files that
  carry NO pytest marker at all (confirmed live: `-m unit` against `tests/unit/test_pixel.py` or
  `tests/unit/test_pixel_fingerprint.py` deselects 100% of tests, exit code 5 "no tests ran").
  Step 2's "fires at all" structural check has no achievable Python-only proving test — the entire
  Python pixel suite is string/regex-only against raw source text (confirmed: no JS execution
  engine anywhere in the suite; the only place tracker.js DOM/click logic is actually exercised is
  `apps/pixel/e2e/*.spec.ts` via Playwright, e.g. the just-landed `fingerprint-v3.spec.ts`, whose
  own header comment states real-browser signals "can just [be grepped for] in the Python tests" —
  i.e. Python cannot prove behavior, only presence). AC-6's tier assignment ("component render is
  Fully-Automated") is not achievable in this repo: `apps/web` has zero React component-render
  test infrastructure (no `@testing-library/react`, no jsdom vitest project, zero `.test.tsx`
  files — confirmed live, `vitest.config.ts` is `environment: "node"`, `include:
  ["src/**/*.test.ts"]` only), an EXACT repeat of a gap the `cadence-bot-flag` plan already hit and
  corrected in its own PVL supplement cycle (see
  `process/features/pixel/backlog/cadence-bot-flag-deferred-gates_NOTE_26-07-26.md`, Gap 3). All
  three resolved via Execute-Agent Instructions E1, E2, E4 below.
- Breaking changes: PASS — every schema/config/column change is additive and nullable/default-OFF;
  `is_emailable_identity()`'s 3-parameter signature confirmed live unchanged
  (`identity_classification.py:109-113`); no public API contract removed.
- Security surface: PASS — D1's visibility-only design confirmed structurally sound (zero-touch of
  the emailability guard, confirmed live, no 4th parameter, `is_agent_operated`/`is_bot_suspect`
  absent from the function body); no PII in the new signal fields (booleans/counts only, matches
  the repo-wide no-PII-in-logs guardrail). The pre-sweep budget-burn residual is already named
  explicitly in the plan's own Known Limitation section — not a new finding.
- Step 0 (migration head) feasibility: PASS — mechanical; `alembic heads` re-verified live this
  session returns single head `f1a7c3e05b92`, but the chain DID move once already between the
  SPEC session and this VALIDATE session (a new intervening migration,
  `e9d2a4c71f68_add_site_tombstones`, landed from a concurrent plan) — empirically validating why
  the plan's own "re-verify before each migration" instruction is load-bearing, not boilerplate.
- Step 1 (tracker.js edit) feasibility: CONCERN — mechanical targets confirmed exact
  (line 4, consent-gate anchor lines 501-504 byte-identical after the concurrent fingerprint-v3
  commit; `pushEvent()` at lines 266-275 confirmed as the exact `_fp`/`_fp3` attachment site, so
  Step 1's "grep `_fp3` before wiring" instruction resolves to a single unambiguous location — no
  gap there). Two real gaps: (a) test-gate marker bug (see Test coverage above); (b) the existing
  `test_has_bot_detection` test (`tests/unit/test_pixel.py:24-25`) only asserts the STRING
  `"navigator.webdriver"` is present — it is NOT a behavioral exit-check and will keep passing
  trivially after this edit; the plan's "if such an assertion exists, it must be updated" framing
  is imprecise (no behavioral assertion currently exists to update — a NEW one must be written).
  Resolved via E1 and E5. No existing `pointermove`/`mousemove` listener exists anywhere in
  tracker.js (confirmed via grep) — the plan's own fallback branch (new one-shot listener) is
  therefore the only viable path; this is confirmatory, not a new gap.
- Step 2 (byte budget) feasibility: CONCERN — resolved via E2 (Playwright spec required for the
  "fires at all" check). Byte baseline re-measured live: 5688B gzip / 13378B raw, 312B headroom —
  matches the plan's recorded range.
- Step 3 (ingest persistence) feasibility: CONCERN — the plan's Step 3.5 instruction ("grep
  `fp3_value`... persist at the same point fp/fp3 are currently persisted") points at the WRONG
  code path. Confirmed live: `fp`/`fp3` are NOT stored on the `events` table at all — they are
  extracted from the batch and written onto the **Visitor** row (`fingerprint`/`fingerprint_v3`
  columns) via a separate best-effort `UPDATE` in `_process_signal_events()` (routers/events.py
  lines 540-606). AC-4's proving test requires the value on the **Event** row specifically. The
  correct precedent — which the plan's OWN Touchpoints section already correctly names
  ("link_marker/is_flagged_abuse additive-column comment style") — is the `event_rows` dict-list /
  `pg_insert(Event)` block (lines 375-422), a different code path entirely. Following the literal
  Step 3.5 grep instruction would misdirect an execute-agent into writing `agent_sig` onto the
  wrong table, silently failing AC-4. Resolved via **Execute-Agent Instruction E3** (binding —
  overrides Step 3.5's literal text).
- Step 4 (classifier port) feasibility: PASS — all 4 pure functions
  (`is_deterministic_agent`, `compute_dead_center_rate`, `evaluate_behavioral_and_gate`,
  `evaluate_session_classifier`), the sweep's already-forward-compatible `_extract_agent_sig`
  (`getattr(event, "agent_sig", None)`), the WS2 config block, and both frozen test files (both
  already carrying `pytest.mark.unit`) confirmed present on the branch via `git show`. Scheduler
  file confirmed as `apps/api/jobs/scheduler.py`, registration pattern at lines ~565-569
  (`cadence_bot_flag_sweep`) — resolves the plan's own "confirm exact path" hedge; see E6.
  Migration `f4c1a9e2d3b8`'s `down_revision` confirmed stale (`a2f8d61c9e37`, not in current
  main's chain) — the plan's own re-chain instruction is correct, no gap.
- Step 5 (visibility-only wiring) feasibility: PASS — signature and all 3 call sites confirmed
  live at the exact cited locations; `is_bot_suspect` column template confirmed at
  `visitor.py:105` (Visitor) and `:175` (IdentifiedVisitor); `test_agent_origin_exclusion.py`
  confirmed as a strong structural template (mocked AsyncSession, no DB, layered proof style).
- Step 6 (dashboard badge) feasibility: CONCERN — no shared component exists to "extend" (the
  plan's Step 6.1 assumption). Confirmed live: `is_bot_suspect` is rendered INLINE at 3 sites
  (`apps/web/src/app/dashboard/visitors/page.tsx:766`,
  `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx:545` and `:935`), plus
  `apps/web/src/lib/api-types.ts:307`. The plan's "grep under
  `apps/web/src/components/visitors/`" guess does not resolve (zero hits there). Resolved via E4.

Open gaps:
- AC-4/AC-7 integration test — Docker-gated, cannot run in this VALIDATE session (repo-wide
  precondition, not this plan's defect).
- AC-10 live migration round-trip — Docker-gated (repo-wide precedent).
- AC-6 full render check — Agent-Probe by necessity; tracked as a repo-wide backlog candidate in
  `cadence-bot-flag-deferred-gates_NOTE_26-07-26.md`, not a new gap this plan introduces.
- AC-12/AC-13/AC-14 — pre-accepted SPEC Known-Gaps, not new findings (per task brief, not
  re-raised here).

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

Execute-Agent Instructions (binding — apply these corrections instead of the literal checklist
text where they conflict; do not silently follow the plan's original wording where noted):

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Drop `-m unit` from the Step 1 and Step 2 test-gate commands. Confirmed live: neither `tests/unit/test_pixel.py` nor `tests/unit/test_pixel_fingerprint.py` carries any `pytest.mark.unit` marker (no module-level `pytestmark`, no per-test decorator) — running with `-m unit` deselects every test in either file (exit code 5, "no tests ran"). Use `.venv/bin/python3.11 -m pytest tests/unit/test_pixel.py -q` and `.venv/bin/python3.11 -m pytest tests/unit/test_pixel_fingerprint.py::TestPixelSizeLimit::test_under_6kb_gzipped tests/unit/test_pixel.py -q` instead. | Step 1 and Step 2 test-gate execution |
| E2 | Add `apps/pixel/e2e/agent-sig.spec.ts` (Playwright), mirroring the `fingerprint-v3.spec.ts` pattern (`interceptIngest`/`fixture`/`settle` from `./harness`). Step 2's "fires at all" structural check (simulated clicks producing non-default `dead_center_ct`/`click_ct`/`no_pointermove_before_click`) cannot be proven as a Python pytest assertion — the entire Python pixel suite is string/regex-only against raw source text with zero JS execution capability. Drive several clicks near element centers in the new spec, then assert the intercepted ingest payload's `agent_sig` object has non-default values. Proving command: `cd apps/pixel && npm run build && npx playwright test e2e/agent-sig.spec.ts`. | Step 2, "fires at all" pass condition |
| E3 | Persist `agent_sig` in the `event_rows` dict-list / `pg_insert(Event)` block in `apps/api/routers/events.py` (lines 375-422 as of this VALIDATE session — the block that also sets `link_marker` and `is_flagged_abuse`), NOT via the `fp3_value` pattern in `_process_signal_events()` (lines 540-606). That function writes to the Visitor row (`fingerprint`/`fingerprint_v3` columns), a structurally different table and code path. AC-4's proving test requires the value on the Event row specifically — following the literal Step 3.5 "grep fp3_value" instruction silently fails that test. | Step 3.5, ingest persistence site selection |
| E4 | Reclassify AC-6/Step 6 to Agent-Probe (both legs, not just the auth-harness leg) — `apps/web` has zero component-render test infrastructure (confirmed live: no `@testing-library/react`/jsdom in package.json, `vitest.config.ts` `include` globs `.ts` only, zero `.test.tsx` files repo-wide), an exact repeat of the gap `cadence-bot-flag` already hit and reclassified in its own PVL supplement (see backlog note referenced above). Also: no shared badge component exists to "extend" — `is_bot_suspect` is rendered inline at 3 confirmed sites: `apps/web/src/app/dashboard/visitors/page.tsx:766`, `apps/web/src/app/dashboard/visitors/[visitorId]/page.tsx:545` and `:935`, plus the type at `apps/web/src/lib/api-types.ts:307`. Add `is_agent_operated` as a parallel inline block at each site (or explicitly call out extracting a shared component as a small scope addition in the phase report — do not do it silently). Prove via a manual visual check at these 3 sites against `is_agent_operated: true`/`false` fixtures; do not attempt to build new component-render test infra as part of this plan (repo-wide backlog candidate, out of scope). | Step 6, badge target location + test tier |
| E5 | Step 1's test-gate note ("if such an assertion exists, it must be updated") is imprecise: no behavioral webdriver-exit assertion currently exists. `test_has_bot_detection` (`tests/unit/test_pixel.py:24-25`) only asserts the string `"navigator.webdriver"` is present — it will keep passing trivially after this edit and must not be mistaken for AC-1 proof. Write a NEW test (source-position regex, matching this suite's existing style): confirm no early-return pattern precedes `document.currentScript`, and that `agent_sig` collection code appears strictly after the line containing `consentDecision = GATED` (also proves AC-2's ordering). | Step 1 test-gate authoring |
| E6 | Scheduler registration file is confirmed `apps/api/jobs/scheduler.py`; the `cadence_bot_flag_sweep` registration pattern to mirror is at lines ~565-569 (`scheduler.add_job(_cadence_bot_flag_sweep_job, ..., id="cadence_bot_flag_sweep")`). No further grep needed — Step 4.6's "confirm exact scheduler file path via grep" is already resolved. | Step 4.6 |
| E7 | Use `postgresql.JSONB` for the new `agent_sig` column (not plain `JSON`) — every existing JSON-shaped column in this codebase (`agent_profile.py`, `agent_visit.py`, `api_usage.py`, `campaign.py`, `crm_connection.py`, `enrichment.py`, `request_log.py`) uses `JSONB`, none use plain `JSON`. Declare it with plain `Column(...)` (not `Mapped[...]`/`mapped_column`) — `Event` in `apps/api/models/event.py` uses the legacy declarative style throughout, confirmed live. | Step 3.3, column type/style choice |

Backlog artifacts: none new — AC-6's component-render test infra gap and the migration
live-round-trip gap are both already tracked in existing backlog notes referenced above; no new
artifact needed from this VALIDATE pass.

Gate: CONDITIONAL
Accepted by: N/A — first-pass CONDITIONAL. Per write-scope constraint, this VALIDATE pass writes
only the Validate Contract section (no edits to the Implementation Checklist/Touchpoints text
above), so the 7 corrections (E1-E7) are recorded here as binding Execute-Agent Instructions
rather than folded into the checklist body. None are FAILs; none block feasibility; all have a
concrete, evidence-backed fix. Recommended resolution: either (a) route through one
plan-validate-fix supplement cycle so E1-E7 get folded directly into the Implementation Checklist
text (cleanest for a fresh EXECUTE reader), or (b) accept this CONDITIONAL as-is and have
execute-agent follow the Execute-Agent Instructions table as binding overrides — both are valid
per the CONDITIONAL gate definition (concerns documented, execution can proceed).

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
the Execute-Agent Instructions table (E1-E7) above and execution proceeds without pausing; BLOCKED
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
  `GATED`/`consentDecision` assignment (tracker.js:501-504).
- Never merge or check out `feat/ws2-agent-session-classifier` — read via `git show` only (D4).
- Never introduce new component-render test infrastructure as a side effect of AC-6 (E4) — that
  is a named repo-wide backlog candidate, out of this plan's scope.
- Follow Execute-Agent Instructions E1-E7 as binding — they correct the literal checklist text
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
