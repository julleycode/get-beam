---
name: plan:first-party-capture
description: "Widen tracker.js CLEAN first-party email capture (value-based match, mailto, URL param, autofill, shadow-DOM) feeding visitor_emails / owned identity graph"
date: 24-07-26
feature: visitors-identity
---

# First-Party Email Capture Expansion — PLAN

Source SPEC: `process/features/visitors-identity/active/first-party-capture_24-07-26/first-party-capture_SPEC_24-07-26.md`
(8 user stories, 15 ACs, 7 out-of-scope items, 3 open questions — all carried below.)

Shape: **COMPLEX, single cohesive plan, 4 staged internal phases** (not an umbrella phase-program —
one feature, one team, sequential dependency chain: harness must exist before any capture point ships).

**Date**: 24-07-26
**Status**: VERIFIED (24-07-26) — Docker/browser gates closed, archived to `completed/`
**Complexity**: COMPLEX (4 staged internal phases, single cohesive plan)

## Overview

Widen `tracker.js`'s first-party email capture surface (value-based field matching, mailto clicks,
URL-param capture, cross-browser autofill, same-origin shadow-DOM/iframe) to feed more clean,
consent-respecting emails into `visitor_emails`, which in turn feeds the owned company/identity
graph built by the sibling `owned-data-layer` plan. Every new capture point reuses the existing
OPTOUT/`validate_email`/dedup/`do_not_resolve` safety gates unchanged — see `all-context.md`
(AI-Agent-Traffic / owned-data-layer context) and `process/context/tests/all-tests.md` for the
Playwright/pytest routing this plan's test gates follow.

## Implementation Checklist

See the phased Implementation Checklist below: `## Phase 0` through `## Phase 3`, each with its own numbered checklist and test gates.

## Phase Completion Rules

A phase is **CODE DONE** when all its checklist items are checked and its test gates run at least
once (pass or documented known-gap). A phase is **VERIFIED** only after: (a) CODE DONE, (b) all
Fully-Automated/Hybrid test gates for that phase are green, and (c) for Phase 0 specifically, the
harness itself is proven to run (not just exist) via the baseline scenario. No phase may be marked
✅ VERIFIED without this evidence recorded in the phase report — code-complete-but-unverified stays
`CODE DONE`, never `VERIFIED`.

## Acceptance Criteria

This plan must satisfy all 15 SPEC acceptance criteria (AC1-AC15) — see the SPEC's own Acceptance
Criteria section for full text, and this plan's `## Verification Evidence` table below for the
gate-to-criterion mapping and proving strategy for each.

## TL;DR

Phase 0 builds the (currently nonexistent) Playwright harness for `tracker.js` capture logic —
hard SPEC prerequisite. Phases 1-3 add capture points in yield order (value-based matcher + mailto +
URL-param → autofill/shadow-DOM → per-site config + source-enum formalization), every new path
reusing the existing OPTOUT/`validate_email`/dedup/`do_not_resolve` gates unchanged. URL-param
plaintext-handling is decided in this plan (§Decision Log D1): reuse the already-shipped Phase-05
`pii_crypto` dual-write + domain-only logging — no new crypto invented. Nothing in
`company_graph`/`identity_signals` (owned-data-layer) is touched; this only widens the
`visitor_emails` feed.

---

## Grounded Facts (RESEARCH, cite file:line)

- `apps/pixel/src/tracker.js`:
  - Form submit capture-phase listener: `~296-301` (queries `input[type='email'], input[name*='email'], input[name*='Email']` within submitted form only).
  - `isEmailField()` name/type matcher: `~293-297`. `onFieldDone` blur/change handler: `~305-307` (blur uses capture phase since blur doesn't bubble).
  - `captureEmail(raw, source)`: `~275-282` — OPTOUT gate, `looksEmail()` format check (`~274`), client dedup via `_sent[email]` (`~278`), `pushEvent` + `flush()`.
  - `emailSource(el)` classifier by form id/class/action: `~283-292` → returns `login|checkout|newsletter|input`.
  - `window.beamIdentify`: `~309`.
  - `_bid` URL param block (opaque Fernet token, server-decoded via `decode_bid`): `~256-266`.
  - Generic click handler (`element_text`/`element_href`, no mailto special-case): `~421-435`.
  - `getUTM()` reads only `utm_*`: `~59-72`. `consentBlocked()`/`OPTOUT` gates `flush()`: `~348` region.
  - **Zero existing test coverage** for any of the above — confirmed via `find apps/web/e2e` (7 specs, none touch tracker capture logic beyond an onboarding snippet-text assertion).
- `apps/api/routers/events.py`: `_process_signal_events` upserts into `visitor_emails` via `pg_insert(...).on_conflict_do_nothing(constraint="uq_visitor_email_site_vid_email")` (~505-517); Phase-05 dual-write already populates `email_ciphertext`/`email_bidx` via `apps/api/services/pii_crypto.py::encrypt_pii`/`email_hash` on EVERY insert path (~503-507) — this already covers "never persisted unencrypted" for any new capture source, no new crypto needed. Logging uses `email_domain`-only pattern (existing convention).
- `apps/api/services/email_validator.py`: 3-layer `validate_email` (format regex + disposable-domain set + MX) — already source-agnostic, reused unchanged.
- `apps/api/models/visitor_email.py`: unique `(site_id, visitor_id, email)`; `source: Mapped[str] = mapped_column(String(20), default="form")`; docstring lists only `form/utm/manual` but tracker already emits `login/checkout/newsletter/input/identify` (drift — Phase 3 fixes this).
- `apps/api/routers/click.py`: server-side ESP click-bind path, `safe_dest` open-redirect guard — untouched by this plan (separate mechanism).
- `apps/pixel/package.json`: `beam-pixel`, vanilla JS, zero deps, `npm run build` → esbuild minify to `tracker.min.js` (must stay <5KB gzipped, checked via `npm run size`). No test script exists today.
- `apps/web/e2e/` — Playwright specs (7 files + `auth.setup.ts`), config at `apps/web/playwright.config.ts`. Pattern for a NEW pixel-capture harness: colocate inside `apps/pixel/` (own package, own lightweight Playwright config) rather than `apps/web/e2e/` — tracker.js has no dependency on the Next.js dashboard and a dashboard-scoped Playwright run would be the wrong blast radius. Confirmed via `process/context/tests/all-tests.md` routing (e2e lane = `apps/web/e2e/` Next.js-served Playwright; no existing pixel-only harness referenced anywhere in that doc).
- Config surface: script tag `data-*` attributes parsed via `getAttribute` exist as a pattern (`data-consent`, `data-stack-*`) but are not used for capture-mechanism gating today — Phase 3 extends this exact pattern.

---

## Decision Log

**D1 — URL-param email handling (SPEC Constraint: "must be hashed or encrypted immediately, mirroring `_bid` Fernet pattern"; resolves nothing new to invent).**
DECISION: Reuse the existing Phase-05 (`owned-data-layer`) `pii_crypto` dual-write path unchanged — send the URL-param email through the SAME `form_email_capture`-shaped event (new `source: "url_param"`), same as every other capture mechanism. Server-side `_process_signal_events` already calls `encrypt_pii`/`email_hash` on every row before persist (routers/events.py ~503-507) and logs only `email_domain`. "Never logged/persisted unencrypted" is therefore ALREADY satisfied by existing infra — no client-side crypto is needed.
WHY: `_bid`'s Fernet encryption exists because `_bid` is an OPAQUE token generated server-side for outbound campaign links (email address never appears in that URL at all — it's ciphertext from creation). A visitor-typed/arrived plaintext URL param (`?email=jane@co.com` on a magic-link/unsubscribe page) is structurally different: the plaintext already exists in the browser URL bar and referrer chain the instant the page loads — client-side hashing before transmission would protect nothing further (the plaintext is already exposed in-browser) while adding complexity and a second crypto scheme to maintain.
REJECTED: (a) client-side hash-before-send with a JS crypto lib — rejected, protects nothing the network layer (HTTPS) + existing server-side dual-write don't already cover, adds `tracker.min.js` bundle weight against the <5KB budget. (b) new Fernet client-encoding scheme — rejected, `_bid`'s Fernet key is server-side secret; client cannot encrypt without exposing the key, and there is no analogous need since transport is already HTTPS.
GUARDRAIL (still enforced, matches SPEC constraint intent): the raw URL param value is read ONCE, passed directly into the existing `captureEmail()` path (no `console.log`, no `localStorage` write, no additional query-string echo), and structlog log lines on the server MUST use `email_domain` only (AC14) — this is the actual mechanism that satisfies "never logged/persisted unencrypted," just via the already-shipped path rather than a new one.

**D2 — Open Question 1 (Safari/Firefox autofill).** DECISION: resolve empirically in Phase 2 via the Playwright cross-browser matrix (chromium/webkit/firefox projects) built in Phase 0/2 — this is exactly what AC5 requires as proof, so no separate `vc-feasibility-test` probe is needed before PLAN; the harness itself IS the probe. If Phase 2's matrix run reveals WebKit/Firefox fire `input` but not `change` on autofill (a documented cross-browser quirk), Phase 2's checklist item 2.1 already includes an `input`-event listener addition as a fallback — see Phase 2 below.

**D3 — Open Question 2 (multi-source provenance).** DECISION: carry forward first-writer-wins unchanged (no schema change to `visitor_emails`). RATIONALE: SPEC explicitly marks this "PLAN's job" and out-of-scope items forbid touching `company_graph`/`identity_signals` schema; extending `visitor_emails` provenance tracking is a genuinely separate schema decision with its own migration/backfill cost that doesn't block any of the 15 ACs. Documented here as the explicit product decision, not a silent gap.

**D4 — Open Question 3 (formal CLEAN/RED policy doc).** DECISION: out of this plan's scope, per SPEC's own routing ("backlog — recommend a follow-up documentation task, not blocking this SPEC"). A backlog NOTE is written during UPDATE PROCESS closeout (see Resume and Execution Handoff).

---

## Touchpoints

| File | Change |
|---|---|
| `apps/pixel/src/tracker.js` | New capture logic: value-based matcher, mailto click parsing, URL-param capture, autofill hardening, shadow-DOM/same-origin-iframe listeners, per-site `data-capture-*` config gates |
| `apps/pixel/package.json` | Add `test` script (Playwright) + `@playwright/test` devDependency |
| `apps/pixel/playwright.config.ts` | NEW — pixel-scoped Playwright config (separate from `apps/web/playwright.config.ts`) |
| `apps/pixel/e2e/*.spec.ts` | NEW — harness fixtures + capture scenario specs (Phase 0 baseline + Phase 1-3 additions) |
| `apps/pixel/e2e/fixtures/*.html` | NEW — static test-harness pages (forms, mailto links, shadow-DOM widget, cross-origin iframe stub, autofill-simulating forms) |
| `apps/api/models/visitor_email.py` | `source` docstring/type formalized to an explicit enum list (Phase 3); no column type change (stays `String(20)`) |
| `apps/api/schemas/events.py` | Add/confirm `source` field validation against the formalized enum (Phase 3) — read file first to confirm current shape before editing |
| `apps/api/routers/events.py` | `_process_signal_events` — extend accepted `source` values validation only; no change to encrypt/dedup/optout logic (already correct) |
| Migration (new, Alembic) | Optional CHECK constraint for `visitor_emails.source` enum (Phase 3) — chain after current head (VALIDATE-time live-confirmed via `.venv/bin/python -m alembic heads` as `e2a4c7f81b93`, NOT `a3e9f1c7d2b5` as originally scanned in RESEARCH — Phase 3 checklist item 5 already instructs re-confirming at EXECUTE time regardless, so this correction is informational only); **Docker-gated, offline-validate only, never live-apply in this sandbox** — offline dry-run confirmed working (`alembic upgrade head --sql` runs fully without a live DB connection) |

## Public Contracts

- No new public HTTP API surface. Existing `POST /api/v1/events` (or equivalent ingest endpoint used by `flush()`) accepts additional `type: "form_email_capture"` `source` string values (`url_param`, `mailto`, `autofill` if distinguished) — additive, non-breaking to the schema.
- New pixel-side config surface: `data-capture-mailto`, `data-capture-url-param`, `data-capture-shadow-dom` (exact attribute names finalized in Phase 3; default = current always-on behavior preserved, see Phase 3 guardrail).
- No change to `visitor_emails` table shape (column types unchanged); `source` value space is documented and validated, not widened structurally.

## Blast Radius

- **Packages touched:** `apps/pixel` (primary, new capture logic + new test harness), `apps/api` (source-enum validation + docstring only, Phase 3).
- **Risk class:** none of auth/billing/schema-migration(live)/public-API-contract-break/deploy — this is an additive capture-surface + validation-tightening change. The Alembic migration (Phase 3) is schema-adjacent but CHECK-constraint-only, additive, and explicitly not live-applied in this sandbox (Docker-gated, matches existing project convention for `owned-data-layer`'s pending migrations).
- **File count:** ~10-12 files across 4 phases (tracker.js edits are cumulative across phases 1-3, not new files each phase).
- **Bundle-size guardrail:** every `tracker.js` addition must be checked against the <5KB gzipped budget (`npm run size` in `apps/pixel`) — flagged as an explicit checklist/test-gate item.

---

## Hard Guardrails (explicit checklist items, not prose — apply to EVERY new capture path in Phases 1-2)

- [ ] G1. New capture call site is gated by the existing `OPTOUT` check (reuses `captureEmail()`'s existing `if(OPTOUT...)return` — no new capture path bypasses `flush()`'s consent gate).
- [ ] G2. New capture call site fires ONLY on an active visitor interaction this session (submit/blur/change/click/page-load-via-followed-link) — never reads a field's current value on page-load/mutation-observer/polling.
- [ ] G3. New capture call site routes through the existing `captureEmail(raw, source)` (format check + dedup + pushEvent), not a parallel capture pipeline.
- [ ] G4. Server-side: new `source` value passes through unchanged `validate_email` + `on_conflict_do_nothing` dedup + Phase-05 `encrypt_pii`/`email_hash` dual-write — verified by NOT touching `_process_signal_events`'s core insert logic, only its accepted-source validation (Phase 3).
- [ ] G5. `do_not_resolve` sticky exclusion path is untouched — no new capture path creates a second identity-resolution trigger route.
- [ ] G6. **DO NOT implement** (explicit out-of-scope guards, verified absent by code review + AC7/AC8 tests):
  - No reading of a field's value before any interaction event fires on it this session (no prefilled/hydrated-field scraping).
  - No `input[type="hidden"]` value is ever passed to `captureEmail`.
  - No `localStorage`/`sessionStorage`/`window.dataLayer` read anywhere in new code.
  - No cross-origin iframe DOM access attempted (same-origin-only `contentDocument` access, wrapped in try/catch that no-ops on `SecurityError`).
  - No keystroke-level (`keydown`/`keyup`/`input`-per-character) logging — the new `input` event listener added for autofill (D2) reads `.value` only on the debounced/settled event, never per-keystroke, and only for recognized email-shaped values (still routes through `looksEmail()`).
- [ ] G7. **[VALIDATE finding, 24-07-26]** URL-param capture (Phase 1 item 4) MUST be placed in `tracker.js` AFTER the `GATED`/`consentDecision` EU-consent-mode setup block (after the code at `~330-344`), NOT co-located with the `_bid` IIFE (`~256-266`) as the checklist's "same pattern as `_bid`" phrasing might suggest. Reason: `captureEmail()` calls `flush()` synchronously (unlike `_bid`'s bare `pushEvent()`), and `flush()`'s `consentBlocked()` guard reads `GATED`/`consentDecision` — if url-param capture runs before those `var`s are assigned, `consentBlocked()` evaluates against `undefined` (falsy) and the captured email is sent immediately, bypassing the EU consent-hold on GATED sites (the GPC/DNT OPTOUT check itself is unaffected — `OPTOUT` is initialized early and stays safe). Only url-param capture is affected; every other new capture point (value-match, mailto, autofill, shadow-DOM, iframe) is event-driven and fires long after the synchronous init block completes, so this ordering hazard does not apply to them.

---

## Phase 0 — Playwright Tracker Harness (PREREQUISITE, blocks all other phases)

**Proves:** AC15. **Blocks:** every other phase — SPEC Constraint "no new capture point may ship without an automated test proving its behavior, because none exists today."

### Checklist

1. Read `apps/pixel/package.json`, `apps/pixel/src/tracker.js` in full, and `apps/web/playwright.config.ts` (as a config-shape reference only — do not extend it; pixel gets its own config).
2. Create `apps/pixel/playwright.config.ts` — projects: `chromium`, `webkit`, `firefox` (needed by Phase 2 / AC5); `testDir: './e2e'`; serves fixture HTML via Playwright's built-in static server or a tiny `http-server`/`serve` devDependency — decide the simplest zero-infra option (no Next.js dev server dependency).
3. Add `apps/pixel/e2e/fixtures/base.html` — a minimal HTML page that loads `tracker.js` (unminified, from `src/`) against a mock `/t` ingest endpoint (Playwright route interception, no real API server needed — asserts on the captured payload the pixel POSTs).
4. Add `apps/pixel/e2e/fixtures/form-email.html` — a form with a literal `name="email"` field (baseline regression fixture for AC2).
5. Write `apps/pixel/e2e/capture-baseline.spec.ts` — ONE passing scenario proving an EXISTING (pre-SPEC) capture mechanism works: submit `form-email.html`, assert the intercepted POST body contains `type: "form_email_capture"`, correct email, `source: "form"`.
6. Add `apps/pixel/package.json` `"test": "playwright test"` script + `@playwright/test` devDependency; add `"test:e2e"` alias matching repo convention (`process/context/tests/all-tests.md` pattern) if useful for discoverability.
7. Run `npx playwright install` (browsers) — note in report if sandboxed/offline (known-gap fallback: chromium-only run, document webkit/firefox as pending).

### Test Gates (Phase 0)
| Gate | Command | Proves |
|---|---|---|
| Harness exists + runs | `cd apps/pixel && npx playwright test` | AC15 |
| Baseline scenario green | same command, `capture-baseline.spec.ts` passes | AC15 (existing mechanism proof) |

---

## Phase 1 — Cold-Start Wins: Value-Based Matcher + Mailto + URL-Param

**Proves:** AC1, AC2 (regression), AC3, AC4, AC13(partial — new source strings emitted, not yet enum-validated until Phase 3), AC14.

### Checklist

1. In `tracker.js`, add `looksLikeEmailValue(v)` reuse of existing `looksEmail()` (no duplicate regex) — add a new field-scan path: on `submit`/`blur`/`change`, if `isEmailField(el)` is false, additionally check `el.value` via `looksEmail()` when `el.nodeName==="INPUT"` and `el.type` is a text-shaped type (`text`, `email`, `""`/unset, `search`) — capture with `source: emailSource(el)` unchanged (G1-G3).
2. Explicit non-regression check: keep the existing `isEmailField()` fast-path first (name/type match still tried first, same `source` classification) — value-based check is additive, not a replacement, so AC2 stays provably unchanged (same code path, same source values for name/type matches).
3. Add mailto click handling: inside the existing click handler (`~421-435`), parse `el.href` for a `mailto:` scheme match — extract the address portion (before `?`), validate via `looksEmail()`, call `captureEmail(addr, "mailto_click")`. Reuses the SAME click listener (no new listener registered — G6 keystroke/new-surface minimization).
4. Add URL-param capture: read a configurable param name (default `email`) via `URLSearchParams`, validate via `looksEmail()`, call `captureEmail(value, "url_param")` — per D1, no client-side crypto; reuses `captureEmail`'s existing OPTOUT+dedup+pushEvent path verbatim. **Placement (G7, VALIDATE finding):** place this code AFTER the `GATED`/`consentDecision` setup block (after `~330-344`), NOT co-located with the `_bid` IIFE — see G7 guardrail above for why (`captureEmail()`'s synchronous `flush()` call needs `GATED`/`consentDecision` already assigned or the EU consent-hold is bypassed).
5. Confirm no `console.log`/plaintext echo anywhere in the new URL-param code path (grep the diff for `console.` and the param variable name before considering this item done).
6. Run `cd apps/pixel && npm run build && npm run size` — confirm still <5KB gzipped; if over budget, minify-check specific additions (value-based matcher reuses existing `looksEmail`, should be near-zero marginal cost; mailto parse is a small regex; URL-param reuses `_bid`-pattern IIFE shape).
7. Server-side (AC14 verification only, no server code change needed): confirm via read of `apps/api/routers/events.py` that the existing `email_domain`-only logging pattern already covers these 3 new `source` values (no new log call sites to add).
8. **[VALIDATE finding, 24-07-26 — new test, no checklist item existed for this]** Write a new backend unit test (e.g. `tests/unit/test_url_param_email_logging.py`, or a new test class in an existing file) asserting: (a) the log call sites at `apps/api/routers/events.py` handling a `source: "url_param"` event log only `email_domain`-shaped values (no `@`-containing string in any logger call's kwargs) — model this on the existing domain-only logging pattern already live at `events.py:388,403,414,426`; (b) name the test so `pytest -k email_domain_logging` matches it (per the Phase 1 Test Gates table below) — e.g. `def test_email_domain_logging_url_param(...)`.

### Test Gates (Phase 1)
| Gate | Scenario | Command | Proves |
|---|---|---|---|
| Value-based match | Login form, `name="username"` holding valid email | `cd apps/pixel && npx playwright test e2e/value-match.spec.ts` | AC1 |
| Regression: name/type match unchanged | Existing `form-email.html` fixture still captures via `source:"form"`/classifier unchanged | same suite, `capture-baseline.spec.ts` still green | AC2 |
| Mailto click | `<a href="mailto:jane@co.com">` clicked | `e2e/mailto.spec.ts` | AC3 |
| URL-param capture + no-plaintext-log | Page loaded with `?email=jane@co.com`; assert captured AND assert no server log call receives the raw string (unit test on log call args) | `e2e/url-param.spec.ts` (pixel) + `.venv/bin/python -m pytest tests/unit -k email_domain_logging -q` (backend) | AC4 (Hybrid — automated capture + automated log-scan, no manual step needed given existing structlog test pattern) |
| URL-param + GATED EU consent-hold (G7) | `data-consent="all"` (or `"eu"` + EU timezone), page loaded with `?email=jane@co.com`, consent NOT yet decided; assert the event is queued (`_rta_q` in localStorage) but assert ZERO network calls/beacons until `window.beamConsent(true)` (or banner Accept) fires | `e2e/url-param-consent-gated.spec.ts` | G7 (VALIDATE finding — placement/ordering hazard) |
| Bundle size | — | `cd apps/pixel && npm run size` | Constraint (non-AC, hard budget) |

---

## Phase 2 — Autofill Hardening + Shadow-DOM / Same-Origin-Iframe Coverage

**Proves:** AC5, AC6, AC7, AC8, AC9.

### Checklist

1. Cross-browser autofill probe (resolves D2/Open Question 1): extend `apps/pixel/e2e/fixtures/form-email.html`-style fixture with a `webkit`/`firefox`/`chromium` matrix run using Playwright's autofill simulation (`page.fill` triggers `input`+`change` in most engines; if WebKit/Firefox project runs show `change` not firing reliably, this item's DONE condition becomes: add a debounced `input` event listener alongside existing `blur`/`change` in `onFieldDone` registration, deduped via the same `_sent[email]` cache so it never double-fires against a submit/blur/change that already captured it).
2. Add `input` event registration only if step 1's matrix proves it's needed (do not add unconditionally — G6 keystroke-minimization concern: `input` fires per-keystroke, so the new listener MUST call `looksEmail()` first and treat every non-matching keystroke as a silent no-op, never logging or queuing partial values — this satisfies the "no keystroke-level logging" guard because only a fully-formed, already-typed email value ever reaches `captureEmail`).
3. Add shadow-DOM support: register the SAME `submit`/`blur`/`change`/`click` listeners with `{capture:true}` on `document`, PLUS use `event.composedPath()[0]` (not `event.target`, which shadow DOM retargets to the host) to find the true originating element inside an open shadow root — no new listeners on individual shadow roots (avoids a MutationObserver-based shadow-root-discovery pattern that could drift toward reading things visitors didn't touch).
4. Add same-origin iframe support: for iframes where `iframe.contentDocument` is accessible (same-origin only — cross-origin throws `SecurityError`, caught and no-op'd per G6), attach the same listener set to `iframe.contentDocument` on a `load` event; wrap in try/catch explicitly documented as the cross-origin boundary enforcement mechanism (not a workaround — it IS the mechanism proving AC7).
5. Write the AC8 guardrail fixture: a page where JS sets `input.value = "prefilled@co.com"` on load WITHOUT dispatching any interaction event, plus a `type="hidden"` field with an email value — assert ZERO capture events from either.
6. Write the AC9 guardrail fixture: OPTOUT/GPC flag set, then exercise ALL Phase 1+2 mechanisms (value-match, mailto, url-param, autofill, shadow-DOM) on one page — assert zero captured emails AND zero network calls (Playwright route-call-count assertion).

### Test Gates (Phase 2)
| Gate | Scenario | Command | Proves |
|---|---|---|---|
| Cross-browser autofill | autofill-simulated email field, 3 browser projects | `cd apps/pixel && npx playwright test e2e/autofill.spec.ts --project=chromium --project=webkit --project=firefox` | AC5 |
| Shadow-DOM capture | email typed inside open shadow-DOM widget fixture | `e2e/shadow-dom.spec.ts` | AC6 |
| Cross-origin iframe silence | cross-origin iframe fixture (served from a different Playwright-mocked origin), assert 0 capture events | `e2e/cross-origin-iframe.spec.ts` | AC7 |
| Prefilled/hidden-field silence | prefilled-untouched + hidden-field fixture, assert 0 capture events | `e2e/no-scrape-guardrail.spec.ts` | AC8 |
| OPTOUT blocks all new mechanisms | GPC/DNT set, exercise all Phase 1+2 mechanisms, assert 0 events/calls | `e2e/optout-guardrail.spec.ts` | AC9 |

---

## Phase 3 — Per-Site Capture Config + Source-Enum Formalization

**Proves:** AC10, AC11, AC12, AC13.

### Checklist

1. Design per-site config: extend the existing `data-*` script-tag attribute pattern with `data-capture-mailto`, `data-capture-url-param`, `data-capture-shadow-dom` (values `"on"`/`"off"`; DEFAULT = `"on"` for all three — preserves current always-on behavior per SPEC constraint "new mechanisms must be configurable... where more consent-sensitive than baseline," read as opt-OUT not opt-IN, since Phase 1/2 already shipped these as always-on and no SPEC AC requires them to default off). Value-based matcher and autofill/shadow-DOM-in-general stay non-configurable (lower consent sensitivity per SPEC — only mailto/URL-param singled out in SPEC's own examples).
2. Read each config flag once at tracker init (mirrors existing `data-consent`/`data-stack-*` read pattern), gate the Phase 1 mailto/URL-param call sites with a simple `if(!cfg.mailto)return;`-style early return — no runtime re-parsing per event.
3. Backend: read `apps/api/schemas/events.py` and `apps/api/models/visitor_email.py` in full before editing. Formalize `source` as a `Literal[...]` (or equivalent enum construct matching the file's existing pattern) covering ALL actual emitted values: `form, utm, manual, login, checkout, newsletter, input, identify, mailto_click, url_param` (+ any autofill-distinct value if Phase 2 step 2 fired). Update `VisitorEmail`'s docstring to match reality (fixes the documented drift).
4. Add server-side validation: unrecognized `source` values are normalized to a safe fallback (e.g. `"other"`) rather than stored as arbitrary free text — decide via reading `apps/api/routers/events.py`'s current handling first; implement the minimal-diff version (reject at schema-validation layer if Pydantic already enforces this once the Literal is added, vs. an explicit normalize-in-router step if the field is looser).
5. Write the Alembic migration for an optional `CHECK` constraint on `visitor_emails.source` (chain after current head — run `.venv/bin/python -m alembic heads` first to confirm the exact parent revision id at execution time; VALIDATE-time live check on 24-07-26 shows `e2a4c7f81b93`, do not assume this or `a3e9f1c7d2b5` is still current without re-checking — other work may land first, same drift pattern seen in the `owned-data-layer` and `handoff` sibling programs). **Offline-validate only** (`alembic upgrade head --sql` dry-run / `alembic check`) — never live-apply against a real Postgres in this sandbox, matching the project's existing Docker-gated migration convention (see `process/features/visitors-identity/backlog/owned-data-layer-docker-verification_NOTE_23-07-26.md` for the precedent).
6. **[VALIDATE finding, 24-07-26 — new test, no checklist item existed for this]** Write a new backend unit test asserting the formalized `source` enum/`Literal` rejects or normalizes an unrecognized value while accepting all confirmed-live values (`form, utm, login, checkout, newsletter, input, identify, mailto_click, url_param` + any Phase 2 autofill-distinct value). Extend the existing `TestEmailCaptureSource` class pattern in `tests/integration/test_events_ingest.py` (`test_source_label_stored`/`test_source_defaults_to_form`, ~line 177-235) rather than inventing a new fixture pattern. Name the test so `pytest -k source_enum` matches it (per the Phase 3 Test Gates table below) — e.g. `def test_source_enum_rejects_unknown(...)`.
7. Do NOT touch `company_graph`/`identity_signals` schema or resolution logic anywhere in this phase (explicit SPEC out-of-scope boundary check before closing).

### Test Gates (Phase 3)
| Gate | Scenario | Command | Proves |
|---|---|---|---|
| Server validation/dedup unchanged for new sources | New source types through `_process_signal_events`, invalid + duplicate cases | `.venv/bin/python -m pytest tests/unit -k visitor_email -q` + `.venv/bin/python -m pytest tests/ -m integration -k visitor_email -q` (requires local PG/Redis per `all-tests.md`) | AC10 |
| `do_not_resolve` still excludes new-mechanism captures | `do_not_resolve` visitor + new-source capture event | `.venv/bin/python -m pytest tests/ -m integration -k do_not_resolve -q` | AC11 |
| Per-site config toggles one mechanism only | `data-capture-mailto="off"`, assert mailto silent, url-param/value-match unaffected | `cd apps/pixel && npx playwright test e2e/per-site-config.spec.ts` | AC12 |
| Source enum validated | Known sources accepted; unknown source rejected/normalized | `.venv/bin/python -m pytest tests/unit -k source_enum -q` | AC13 |
| Migration offline-validate only | `alembic heads` then `alembic upgrade head --sql` (dry-run, no live DB write) | N/A — offline check, not an AC gate | Constraint (migration safety) |

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Harness exists + baseline scenario green | Fully-Automated | AC15 |
| Value-based field matching (non-email-named field) | Fully-Automated | AC1 |
| Regression: name/type-based matching unchanged | Fully-Automated | AC2 |
| Mailto click capture | Fully-Automated | AC3 |
| URL-param capture + no-plaintext-in-logs | Hybrid | AC4 |
| Cross-browser autofill matrix (chromium/webkit/firefox) | Fully-Automated | AC5 |
| Same-origin shadow-DOM capture | Fully-Automated | AC6 |
| Cross-origin iframe explicitly silent | Fully-Automated | AC7 |
| Prefilled/hidden-field guardrail (zero capture) | Fully-Automated | AC8 |
| OPTOUT blocks all new mechanisms | Fully-Automated | AC9 |
| Server validation/dedup unchanged for new sources | Fully-Automated | AC10 |
| `do_not_resolve` sticky exclusion unaffected | Fully-Automated | AC11 |
| Per-site config toggle isolates one mechanism | Fully-Automated | AC12 |
| Source enum validated, unknowns rejected/normalized | Fully-Automated | AC13 |
| PII-safe logging (no full email in log args) | Fully-Automated | AC14 |
| Bundle size stays <5KB gzipped | Fully-Automated | Constraint (non-AC) |
| Migration offline-validate (no live apply) | Fully-Automated (dry-run) | Constraint (migration safety) |

## Test Infra Improvement Notes

(none identified yet — Phase 0 IS the test-infra build-out this plan requires; if Phase 0 discovers the pixel-scoped Playwright config needs a shared static-file server not yet in the repo, record that gap here during EXECUTE rather than inventing an unplanned dependency.)

## Open Questions Carried From SPEC (unresolved by this plan, explicitly)

1. **Safari/Firefox autofill event behavior** — resolved procedurally via D2: Phase 2 step 1's cross-browser matrix run IS the probe; the plan does not pre-commit to whether an extra `input` listener is needed until that matrix runs.
2. **Multi-source provenance** — resolved as a product decision (D3): first-writer-wins unchanged, no schema change. Not a blocker.
3. **Formal CLEAN/RED policy doc** — explicitly deferred to backlog (D4); write a backlog NOTE during UPDATE PROCESS closeout (not blocking EXECUTE).

---

## Resume and Execution Handoff

1. **Selected plan file path:** `process/features/visitors-identity/active/first-party-capture_24-07-26/first-party-capture_PLAN_24-07-26.md`
2. **Last completed phase or step:** none — plan just written, no EXECUTE work started.
3. **Validate-contract status:** written, Gate: PASS (24-07-26) — see `## Validate Contract` section below.
4. **Supporting context files loaded:** `process/context/all-context.md`, `process/context/tests/all-tests.md`, SPEC file (above), `apps/pixel/src/tracker.js` (full read), `apps/api/models/visitor_email.py`, `apps/api/routers/events.py` (~480-530), `apps/api/services/{email_validator,pii_crypto,link_decorator}.py`, `apps/pixel/package.json`, sibling `owned-data-layer_PLAN_23-07-26.md` (for graph-relationship context) and its Docker-verification backlog NOTE (for the offline-migration precedent).
5. **Next step for a fresh agent picking up mid-execution:** run VALIDATE on this plan (V1-V7), then start Phase 0 (harness) — Phase 0 is a hard blocker for Phases 1-3, confirm it is marked done (checklist items 1-7 all checked + both Phase 0 test gates green) before starting Phase 1.

## Phase Loop Progress

- [x] Phase 0 — Playwright harness (PREREQUISITE) — chromium green (baseline spec passes)
- [x] Phase 1 — Value-based matcher + mailto + URL-param — green
- [x] Phase 2 — Autofill hardening + shadow-DOM/same-origin-iframe — chromium green; webkit/firefox DEFERRED-to-EVL (binaries not cached)
- [x] Phase 3 — Per-site config + source-enum formalization — green (migration offline-validated)
- [x] VALIDATE (validate-contract written — Gate: PASS, 24-07-26)
- [x] EXECUTE (all runnable in-scope test gates green — 24-07-26)
- [x] EVL confirmation run — independently re-ran by vc-tester/orchestrator 24-07-26: chromium e2e
  11/11 green, backend unit 367 passed / 2 skipped, gate-specific tests 19, full regression 47/47
  (incl. `test_agent_origin_exclusion.py` 18/18), migration `a9f2c1e7b4d6` offline dry-run
  re-confirmed (head verified: `a9f2c1e7b4d6`), bundle size 4811B gzipped (<5KB budget), guardrails
  G6/G7/G8 re-checked structurally (file:line). Two gates could not be independently re-confirmed
  in this environment (see Closeout below) — DEFERRED, not failed.
- [x] UPDATE PROCESS (archive + backlog NOTE for D4 CLEAN/RED policy doc)

## Closeout (UPDATE PROCESS, 24-07-26; promoted to VERIFIED 24-07-26)

**Classification: VERIFIED** — code-complete, and the 2 previously-deferred environment-only gaps
are now closed by an independent EVL final run. Archived to `completed/`.

**Docker/browser-gate closure (EVL final run, 24-07-26 — independent):**
- AC5 webkit/firefox autofill legs — `e2e/autofill.spec.ts --project=webkit --project=firefox`:
  2/2 passed (chromium leg was already green; all 3 browser projects now confirmed).
- AC11 `do_not_resolve` integration re-confirm — 1/1 passed, **non-vacuous**: exercises a real
  `Visitor(do_not_resolve=True)` row, calls the real `record_signal()` write path, and asserts the
  resulting `identity_signals` insert count is `0` (not a mock/stub assertion).
- Backend unit regression (source enum + URL-param logging) — 19/19 passed.
- 3 test-infra fixes landed in commit `8c7ac6e` (session `expire_all`, the AC11 integration test
  itself, and a Redis mock shared with the owned-data-layer fix) unblocked this closure — see the
  `post-docker-gate-followups_NOTE_24-07-26.md` backlog note for what remains open.

**Note for future readers — code pre-existed this RIPER pass:** at session start, `tracker.js`,
`events.py`, `visitor_email.py`, the `apps/pixel/e2e/` harness, and the source-enum migration were
already present/modified on disk (a prior/parallel session implemented them) — this RIPER flow
(SPEC → PLAN → VALIDATE → EXECUTE → EVL) formalized, verified, and backed the pre-existing
implementation with a SPEC, a validated plan, and an independent EVL confirmation run. The plan
therefore post-dates the code; this is intentional, not a process violation — VALIDATE and EVL both
ran against the real, already-written implementation rather than a not-yet-written one.

**Commits already landed on main:**
- `aad64c0` — feat(pixel): first-party email capture (value-matcher, mailto, URL-param, autofill/shadow-DOM/iframe)
- `68d2e22` — feat(identity): visitor_email source enum + CHECK constraint migration
- `c3d0e03` — process(visitors-identity): first-party-capture SPEC + plan + validate-contract

**EVL numbers (independent re-run, not execute-agent's internal claim):**
- `cd apps/pixel && npx playwright test` (chromium project): 11/11 passed
- `.venv/bin/python -m pytest tests/unit -q`: 367 passed, 2 skipped
- Gate-specific tests (`-k email_domain_logging`, `-k source_enum`, etc.): 19 passed
- Full regression: 47/47 passed, including `tests/unit/test_agent_origin_exclusion.py` 18/18 (EvalLayer guardrail, confirms no cross-feature regression)
- `cd apps/api && ../../.venv/bin/python -m alembic heads`: `a9f2c1e7b4d6 (head)` — offline dry-run (`alembic upgrade head --sql`) re-confirmed working, no live DB touched
- `cd apps/pixel && npm run size`: 4811B gzipped, under the 5KB budget
- Guardrails G6 ("DO NOT implement" list), G7 (URL-param consent-hold placement), G8 (n/a — plan only defines G1-G7; re-verified G1-G7 structurally, file:line, all present as coded)

**Deferred (environment gates, not code gaps):**
1. **AC5 webkit/firefox autofill legs** — `npx playwright install` for webkit/firefox binaries was
   not cacheable in this sandbox (install exceeds a 120s cap / no cached binaries). Chromium leg
   (Fully-Automated) is green and proves AC5's core mechanism; webkit/firefox legs remain
   Hybrid/pending per the plan's own Phase 0 checklist item 7 documented fallback. See backlog NOTE.
2. **Phase 3 integration re-confirm** (`tests/ -m integration -k "visitor_email or do_not_resolve"`)
   — EXECUTE ran this green with PG+Redis up; EVL could not independently re-confirm because Docker
   was down at EVL time (15s health-check cap exceeded). Same Docker-gate posture as the sibling
   `owned-data-layer` plan. See backlog NOTE.

**Keep-in-active rationale:** per the vacuous-green ban, a plan cannot move CODE DONE → VERIFIED (or
archive) while any Fully-Automated/Hybrid gate depends on an environment precondition (browser
binary, live DB) that was never actually exercised in THIS closeout pass. Both residuals here are
environment-only (not design or code defects) and have a documented, executable close command in
the companion backlog NOTE — this plan stays in `active/` until those are run for real.

**Backlog note (env-gaps + D4 CLEAN/RED policy doc pointer):** written the prior session, see
`process/features/visitors-identity/backlog/first-party-capture-deferred-gates_NOTE_24-07-26.md`
— marked RESOLVED this session (Gaps 1 and 2 closed; Gap 3 migration live-apply status: the
round-trip was proven on a disposable Postgres this session, but a REAL/production live-apply
remains a separate explicit operator action, unchanged from the note's original scope; D4 doc
pointer remains open, tracked in the new followups note).

**Promoted to VERIFIED and archived 24-07-26.** Commits `aad64c0`/`68d2e22`/`c3d0e03` (prior
implementation/process) plus `8c7ac6e` (test-infra fixes this session). Task folder moved
`active/` → `completed/` this session.

### EXECUTE Deviations (within-blast-radius, documented per protocol)
- **D-E1** AC13 source-enum test authored as dedicated unit file `tests/unit/test_visitor_email_source_enum.py` (6 tests on pure `normalize_source`) instead of extending integration `TestEmailCaptureSource` per Phase 3 item 6. Reason: `normalize_source` is pure/DB-free (plan's own code comment says "unit-testable in the fast lane"); faster lane, matches the `-k source_enum` gate. Integration `TestEmailCaptureSource` retained (storage-path coverage). Within test blast radius — no source/schema deviation.
- **D-E2 (out of scope, NOT this plan)** `apps/api/services/known_hash.py` + `tests/unit/test_known_hash.py` are modified in the working tree but are NOT in this plan's Touchpoints. Left untouched by EXECUTE; flagged for orchestrator (pre-existing uncommitted change, security-adjacent blind-index refactor).

## Validate Contract

Status: PASS
Date: 24-07-26
date: 2026-07-24
generated-by: outer-pvl

Parallel strategy: sequential
Rationale: Score 3/7 (S2 schema-adjacent migration touch, S6 privacy-sensitive PII capture surface, S7 8-row Touchpoints table) → MEDIUM band nominally recommends parallel subagents for the Layer 1/Layer 2 fan-out, but this VALIDATE pass ran as a single sequential agent against source (tracker.js, events.py, models, migrations, tests) because the plan is one cohesive non-phase-program artifact with a single sequential Phase 0→3 dependency chain (Phase 0 blocks everything) — there is no independent-direction fan-out to parallelize; every finding required cross-referencing the same files. EXECUTE strategy recommendation: sequential (Phase 0 hard-blocks Phase 1-3; each phase's checklist depends on the prior phase's harness/capture points existing).

### Layer 1 dimensions

| Layer 1 dimensions | Status |
|---|---|
| Infra fit | CONCERN → fixed in plan |
| Test coverage | CONCERN → fixed in plan |
| Breaking changes | PASS |
| Security surface | CONCERN → fixed in plan |

### Layer 2 sections

| Layer 2 sections | Status |
|---|---|
| Phase 0 — Playwright harness | PASS |
| Phase 1 — Value-match/mailto/URL-param | CONCERN → fixed in plan |
| Phase 2 — Autofill/shadow-DOM/iframe | PASS |
| Phase 3 — Per-site config + source-enum | CONCERN → fixed in plan |

**Totals: 0 FAILs / 4 CONCERNs (all 4 fixed directly in plan text this cycle) / 4 PASSes**

**→ Net Gate: PASS**

All 4 CONCERNs found were fixable in plan text without descoping or a supplement loop — applied directly below (V6), consistent with a single-pass VALIDATE→PASS outcome.

### Findings

| Finding | Severity | Proposed fix |
|---|---|---|
| Touchpoints/Phase 3 checklist cited alembic `down_revision` head as `a3e9f1c7d2b5`; live-confirmed via `.venv/bin/python -m alembic heads` (works fully offline, verified this session) the actual current head is `e2a4c7f81b93` — 4 more migrations landed since RESEARCH scanned the codebase | CONCERN | **Fixed in plan.** Touchpoints table + Phase 3 checklist item 5 updated with the live-confirmed head and an explicit note that this is informational (the checklist already instructs re-verifying via `alembic heads` at EXECUTE time regardless — self-correcting design, same drift pattern already documented in the `owned-data-layer` and `handoff` sibling plans' reports). |
| AC4 (Phase 1) and AC13 (Phase 3) Test Gates reference backend unit tests (`-k email_domain_logging`, `-k source_enum`) that do not exist and have no corresponding "write this test" checklist item — confirmed via repo grep, no match for either pattern anywhere in `tests/` | CONCERN | **Fixed in plan.** Added explicit checklist item 8 (Phase 1) and item 6 (Phase 3) instructing the exact test to write, which existing pattern to extend (`TestEmailCaptureSource` in `tests/integration/test_events_ingest.py` for AC13; the `email_domain`-only logging pattern already live at `events.py:388,403,414,426` for AC4), and the exact test-name convention so the `-k` filter in the Test Gates table matches. |
| URL-param capture (Phase 1 item 4) instructed to be placed "same pattern as the existing `_bid` IIFE (~256-266)" — but unlike `_bid` (bare `pushEvent`), the new code calls `captureEmail()` which calls `flush()` synchronously; `flush()`'s `consentBlocked()` guard reads `GATED`/`consentDecision`, which are not assigned until `~330-344` (later in the file). If placed at the `_bid` location, `consentBlocked()` evaluates against `undefined` (falsy) and the captured email is sent immediately on GATED/EU sites, bypassing the intended consent-hold before the visitor has decided (GPC/DNT OPTOUT itself is unaffected — that var is initialized earlier and stays safe) | CONCERN | **Fixed in plan.** Added Hard Guardrail G7 (explicit checklist item, same status as G1-G6), updated Phase 1 checklist item 4 with the correct placement instruction, and added a new Phase 1 Test Gates row + Playwright scenario (`e2e/url-param-consent-gated.spec.ts`) proving the GATED-consent-hold behavior specifically. |
| ✅ D1 (URL-param plaintext handling) mechanism-level claim — verified by reading `apps/api/routers/events.py` (~503-517): `encrypt_pii`/`email_hash` dual-write fires on every `visitor_emails` insert row unconditionally, and all 4 log call sites touching captured emails (`events.py:388,403,414,426`) already log `email_domain`-only, never full address | ✅ PASS | — |
| ✅ Source enum superset claim (AC13) — verified the full confirmed-live value set (`form, login, checkout, newsletter, input, identify, utm` via `emailSource()` + `events.py:392,420`) is a proper subset of the plan's proposed enum list; no data-loss risk on existing rows | ✅ PASS | — |
| ✅ G1-G6 field-scraping guardrails (AC8/G6) — verified every new Phase 1-2 capture path is registered as a `submit`/`blur`/`change`/`click`/`load` event listener, never a poll/MutationObserver/read-on-mount; value-based matcher's text-shaped-type allowlist (`text`/`email`/`""`/`search`) structurally excludes `type="hidden"` | ✅ PASS | — |
| ✅ Cross-origin iframe boundary (AC7) — `contentDocument` access wrapped in try/catch on `SecurityError`, matches the plan's own stated mechanism | ✅ PASS | — |
| ✅ Bundle-size test command (`npm run size`) — verified exists and matches `package.json` exactly | ✅ PASS | — |
| ✅ Offline migration dry-run mechanism — verified `alembic upgrade head --sql` runs fully offline (no DB connection attempted) this session, confirming the Phase 3 test gate command is genuinely executable in this sandbox | ✅ PASS | — |
| ✅ Phase 0 harness architecture (own `apps/pixel/e2e/` + own `playwright.config.ts`, no `apps/web` Next.js dependency) — feasible via `file://` + Playwright route interception (zero-infra option exists); chromium browser binary already cached locally (`chromium-1223`/`1228`), webkit/firefox not cached — carried forward as a known execution-environment risk, not a plan defect (Phase 0 checklist item 7 already documents the chromium-only fallback) | ✅ PASS | — |

### Plan Updates Applied (this VALIDATE cycle)

| # | What changed | Where in plan | Why |
|---|---|---|---|
| P1 | Migration head reference corrected (`a3e9f1c7d2b5` → live-confirmed `e2a4c7f81b93`, informational) | Touchpoints table; Phase 3 checklist item 5 | RESEARCH-time scan was stale by 4 migrations; self-correcting design already in place, just fixing the written claim |
| P2 | Added Hard Guardrail G7 (URL-param consent-hold placement) | Hard Guardrails section (after G6) | New structural safety requirement found — same severity class as G1-G6 |
| P3 | Corrected Phase 1 checklist item 4 (URL-param placement instruction) | Phase 1 checklist | Prevents the EU-consent-hold bypass described in G7 |
| P4 | Added Phase 1 checklist item 8 (write AC4 log-scan backend test) | Phase 1 checklist | Test Gates table referenced a test with no authoring step |
| P5 | Added Phase 1 Test Gates row (GATED consent-hold scenario, G7) | Phase 1 Test Gates table | Proves the new G7 guardrail, not just documents it |
| P6 | Added Phase 3 checklist item 6 (write AC13 source-enum backend test) | Phase 3 checklist (renumbered old item 6→7) | Test Gates table referenced a test with no authoring step |

No execute-agent-only instructions were needed beyond what's now in the plan text itself — all 4 CONCERNs were resolvable as direct plan edits, not deferred judgment calls.

### Backlog Artifacts

| Artifact | Location | What it tracks |
|---|---|---|
| CLEAN/RED capture-technique policy doc (D4, SPEC Open Question 3) | to be written during UPDATE PROCESS closeout per plan's existing `## Resume and Execution Handoff` step | Formal documented policy future capture-point proposals can be checked against — already scoped out of this plan by product decision D4, not a new gap found at VALIDATE |

## III. Test Coverage Plan

Test context loaded: `process/context/tests/all-tests.md` (unit/integration/e2e lanes, command conventions) + existing test files discovered: `tests/unit/test_pixel.py` (structural-marker tests, confirmed NOT capture-behavior coverage), `tests/integration/test_events_ingest.py::TestEmailCaptureSource` (existing source-label backend pattern, extended by Phase 3), `tests/unit/test_optout.py` / `tests/integration/test_optout_flow.py` (existing OPTOUT pattern, extended by Phase 2 AC9), `tests/unit/test_backfill_pii_ciphertext.py` (existing `pii_crypto` pattern referenced by D1).

**Area: apps/pixel (Phase 0 — harness)**

| Tier | Scenario | Command / Steps | What it proves | What it does NOT prove |
|---|---|---|---|---|
| Fully-Automated | Harness exists + runs | `cd apps/pixel && npx playwright test` | AC15 — a working Playwright harness for tracker.js capture logic exists | Nothing about capture behavior itself — Phase 0 only proves the harness runs |
| Fully-Automated | Baseline scenario green (existing form-submit mechanism) | same command, `capture-baseline.spec.ts` | AC15 baseline proof | Any of the NEW mechanisms (Phases 1-3) |

Failing stub:
```
test("should run the tracker Playwright harness and prove it executes", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: Harness exists + runs")
})
```

Failing stub:
```
test("should capture an email via the existing form-submit mechanism (baseline regression fixture)", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: Baseline scenario green")
})
```

**Area: apps/pixel (Phase 1 — value-match/mailto/url-param)**

| Tier | Scenario | Command / Steps | What it proves | What it does NOT prove |
|---|---|---|---|---|
| Fully-Automated | Value-based match on non-email-named field | `cd apps/pixel && npx playwright test e2e/value-match.spec.ts` | AC1 | Whether a real-world site's field naming conventions are covered beyond the fixture |
| Fully-Automated | Regression: name/type match unchanged | same suite, `capture-baseline.spec.ts` still green | AC2 | Nothing new — pure regression guard |
| Fully-Automated | mailto: click capture | `cd apps/pixel && npx playwright test e2e/mailto.spec.ts` | AC3 | `mailto:` links with unusual encodings/params beyond the fixture |
| Hybrid | URL-param capture + no-plaintext-log | `cd apps/pixel && npx playwright test e2e/url-param.spec.ts` (capture) + `.venv/bin/python -m pytest tests/unit -k email_domain_logging -q` (log-scan; precondition: Phase 1 checklist item 8 test written) | AC4 | Log-scan test does not inspect infra/platform-level access logs (e.g. uvicorn/Railway request logs) — mitigated by default browser `Referrer-Policy: strict-origin-when-cross-origin` stripping the query string on the cross-origin POST to the ingest endpoint, but this is browser-default behavior, not code-enforced; out of this plan's control boundary |
| Fully-Automated | URL-param + GATED EU consent-hold (G7) | `cd apps/pixel && npx playwright test e2e/url-param-consent-gated.spec.ts` | G7 guardrail (VALIDATE finding) | Non-EU/non-GATED sites are unaffected by this specific ordering hazard — not re-tested here, covered by AC9 |
| Fully-Automated | Bundle size stays <5KB gzipped | `cd apps/pixel && npm run size` | Constraint (non-AC, hard budget) | — |

Failing stub:
```
test("should capture an email typed into a non-email-named field via value-based matching", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: Value-based match on non-email-named field")
})
```

Failing stub:
```
test("should still capture via name/type-based matching unchanged (regression)", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: Regression: name/type match unchanged")
})
```

Failing stub:
```
test("should capture the address from a clicked mailto: link", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: mailto: click capture")
})
```

Failing stub:
```
test("should capture a URL email param and never log it as plaintext", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: URL-param capture + no-plaintext-log")
})
```

Failing stub:
```
test("should hold URL-param capture until EU consent is granted (G7 ordering guardrail)", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: URL-param + GATED EU consent-hold")
})
```

Failing stub:
```
test("should keep tracker.min.js under the 5KB gzipped budget", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: Bundle size stays under budget")
})
```

**Area: apps/pixel (Phase 2 — autofill/shadow-DOM/iframe)**

| Tier | Scenario | Command / Steps | What it proves | What it does NOT prove |
|---|---|---|---|---|
| Hybrid | Cross-browser autofill (chromium/webkit/firefox) | `cd apps/pixel && npx playwright test e2e/autofill.spec.ts --project=chromium --project=webkit --project=firefox` — precondition: webkit/firefox browser binaries installed (`npx playwright install`; chromium already cached locally, webkit/firefox are NOT — confirmed this session) | AC5 (chromium leg is effectively Fully-Automated; webkit/firefox legs are Hybrid on binary availability) | If `playwright install` cannot reach the network at EXECUTE time, webkit/firefox legs become a documented known-gap (Phase 0 checklist item 7 already specifies this exact fallback) — chromium leg still proves the core mechanism |
| Fully-Automated | Shadow-DOM capture | `e2e/shadow-dom.spec.ts` | AC6 | Closed shadow roots (out of scope — SPEC only requires same-origin, open-shadow-DOM coverage per the widget/checkout use case) |
| Fully-Automated | Cross-origin iframe silence | `e2e/cross-origin-iframe.spec.ts` | AC7 | — |
| Fully-Automated | Prefilled/hidden-field silence | `e2e/no-scrape-guardrail.spec.ts` | AC8 | Synthetic `dispatchEvent()`-faked interaction events from a malicious/buggy site script (pre-existing gap, not introduced by this plan — `event.isTrusted` is not checked anywhere in the current tracker) |
| Fully-Automated | OPTOUT blocks all new mechanisms | `e2e/optout-guardrail.spec.ts` | AC9 | GATED-EU-consent-pending state specifically (that's G7's new dedicated test in Phase 1, not this one — AC9 tests GPC/DNT OPTOUT, a different gate) |

Failing stub:
```
test("should capture an autofilled email consistently across chromium, webkit, and firefox", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: Cross-browser autofill")
})
```

Failing stub:
```
test("should capture an email typed inside a same-origin shadow-DOM widget", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: Shadow-DOM capture")
})
```

Failing stub:
```
test("should produce zero capture events from a cross-origin iframe", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: Cross-origin iframe silence")
})
```

Failing stub:
```
test("should produce zero capture events for a prefilled-untouched field and a hidden field", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: Prefilled/hidden-field silence")
})
```

Failing stub:
```
test("should produce zero capture events or network calls when OPTOUT is set, across all new mechanisms", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: OPTOUT blocks all new mechanisms")
})
```

**Area: apps/api (Phase 3 — per-site config + source-enum)**

| Tier | Scenario | Command / Steps | What it proves | What it does NOT prove |
|---|---|---|---|---|
| Fully-Automated | Server validation/dedup unchanged for new sources | `.venv/bin/python -m pytest tests/unit -k visitor_email -q` + `.venv/bin/python -m pytest tests/ -m integration -k visitor_email -q` (integration leg needs local PG/Redis per `all-tests.md`) | AC10 | Production-scale concurrent-write dedup races (existing gap, out of this plan's scope) |
| Fully-Automated | `do_not_resolve` still excludes new-mechanism captures | `.venv/bin/python -m pytest tests/ -m integration -k do_not_resolve -q` | AC11 | — |
| Fully-Automated | Per-site config toggles one mechanism only | `cd apps/pixel && npx playwright test e2e/per-site-config.spec.ts` | AC12 | Config attributes not yet defined for Phase 1 mechanisms other than mailto/url-param (value-match/autofill/shadow-DOM are non-configurable by design per plan Phase 3 item 1) |
| Fully-Automated | Source enum validated (precondition: Phase 3 checklist item 6 test written) | `.venv/bin/python -m pytest tests/unit -k source_enum -q` | AC13 | — |
| Fully-Automated | Migration offline-validate only | `.venv/bin/python -m alembic heads` then `.venv/bin/python -m alembic upgrade head --sql` (dry-run — verified this session to run fully offline, no live DB connection attempted) | Constraint (migration safety) | Whether the CHECK constraint itself is syntactically valid Postgres DDL until the migration file is actually written (Phase 3 item 5) — the dry-run only proves the MECHANISM (offline SQL generation) works, not the not-yet-written migration's content |

Failing stub:
```
test("should validate/dedup new-source visitor_email events the same as existing form-source events", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: Server validation/dedup unchanged for new sources")
})
```

Failing stub:
```
test("should skip identity-resolution work for a do_not_resolve visitor even with a new-mechanism capture event", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: do_not_resolve still excludes new-mechanism captures")
})
```

Failing stub:
```
test("should silence only the disabled mechanism when a per-site config flag is off, leaving others active", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: Per-site config toggles one mechanism only")
})
```

Failing stub:
```
test("should reject or normalize an unrecognized source value while accepting all known sources", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: Source enum validated")
})
```

### Missing Test Areas

| Area | Why untestable in this plan | Resolution chosen |
|---|---|---|
| Infra/platform-level access-log Referer-header leakage for URL-param capture | Requires inspecting Railway/uvicorn platform request logs, not application-level structlog — outside this plan's blast radius and outside Beam's control boundary for the customer's own originating page | C) Accept as known-gap — mitigated by default browser `Referrer-Policy: strict-origin-when-cross-origin` (strips query string on cross-origin POST), not code-enforced; documented here rather than silently assumed safe |
| Cross-browser autofill webkit/firefox legs if `playwright install` has no network access at EXECUTE time | Sandbox network availability is unknown until EXECUTE runs; chromium binary already cached, webkit/firefox are not (confirmed this session) | C) Accept as known-gap if it occurs — Phase 0 checklist item 7 already documents the chromium-only fallback; chromium leg alone still proves AC5's core mechanism (not vacuously green) |
| Formal CLEAN/RED capture-technique policy doc (SPEC Open Question 3 / D4) | Explicitly out of this plan's scope by product decision D4 | D) Backlog artifact — NOTE written during UPDATE PROCESS closeout per the plan's own `## Resume and Execution Handoff` |

## Test gates (legacy line form)

- Phase 0 harness: Fully-automated: `cd apps/pixel && npx playwright test` (baseline scenario proves AC15)
- Phase 1 value-match/mailto/url-param: Fully-automated: `cd apps/pixel && npx playwright test e2e/value-match.spec.ts e2e/mailto.spec.ts e2e/url-param.spec.ts e2e/url-param-consent-gated.spec.ts` | Hybrid: `.venv/bin/python -m pytest tests/unit -k email_domain_logging -q` (precondition: Phase 1 item 8 test written)
- Phase 2 autofill/shadow-DOM/iframe: Fully-automated: `cd apps/pixel && npx playwright test e2e/shadow-dom.spec.ts e2e/cross-origin-iframe.spec.ts e2e/no-scrape-guardrail.spec.ts e2e/optout-guardrail.spec.ts` | Hybrid: `cd apps/pixel && npx playwright test e2e/autofill.spec.ts --project=chromium --project=webkit --project=firefox` (precondition: webkit/firefox binaries installed)
- Phase 3 per-site config/source-enum: Fully-automated: `.venv/bin/python -m pytest tests/unit -k "visitor_email or source_enum" -q && .venv/bin/python -m pytest tests/ -m integration -k "visitor_email or do_not_resolve" -q && cd apps/pixel && npx playwright test e2e/per-site-config.spec.ts` | Fully-automated (dry-run): `.venv/bin/python -m alembic heads && .venv/bin/python -m alembic upgrade head --sql` (precondition: Phase 3 item 5 migration file written)

## Dimension findings

- Infra fit: PASS (fixed in plan) — Phase 0 harness architecture confirmed mechanically feasible (own Playwright config, zero Next.js dependency, chromium cached); one stale migration-head reference found and corrected.
- Test coverage: PASS (fixed in plan) — two missing test-authoring checklist items added (AC4 log-scan, AC13 source-enum); all tier assignments verified against real existing test file patterns (`test_pixel.py`, `TestEmailCaptureSource`, `test_optout.py`).
- Breaking changes: PASS — no public API contract break; additive source values and config attrs only; `visitor_emails` column shapes unchanged; migration is CHECK-constraint-only, offline-validate, never live-applied in this sandbox.
- Security surface: PASS (fixed in plan) — D1's dual-write/domain-only-logging mechanism verified sound by reading the actual encrypt path; OPTOUT-gate replication confirmed structurally safe (single `captureEmail()` funnel per G1/G3); one genuine new consent-ordering hazard found (URL-param placement vs. `GATED` init) and fixed via new Hard Guardrail G7 + dedicated test gate.

## Open gaps

- Infra/platform access-log Referer leakage for URL-param capture — known-gap, mitigated by browser-default `Referrer-Policy`, not code-enforced (see Missing Test Areas above).
- Cross-browser webkit/firefox binaries not yet cached in this sandbox — known-gap risk at EXECUTE time only if `playwright install` cannot reach network; chromium leg (Fully-Automated) still proves AC5's mechanism regardless.
- D4 CLEAN/RED policy doc — deferred to backlog NOTE at UPDATE PROCESS closeout by explicit product decision (D4), not a gap found at VALIDATE.

## What this coverage does NOT prove

- The Phase 1 Hybrid AC4 log-scan test proves Beam's own `structlog` application logs stay domain-only; it does NOT inspect infra/platform request-level access logs (uvicorn, Railway, any CDN/WAF) for Referer-header leakage — that residual relies on browser-default `Referrer-Policy` behavior, not this plan's code.
- The Phase 2 Hybrid AC5 test's webkit/firefox legs prove nothing if browser binaries cannot be installed at EXECUTE time (network-dependent); only the chromium leg is unconditionally guaranteed to run in this sandbox as confirmed this session.
- The AC8 prefilled/hidden-field guardrail test does not cover a site script that fakes a trusted user interaction via `el.dispatchEvent(new Event('change'))` — `event.isTrusted` is not checked anywhere in the current or planned tracker.js code (pre-existing characteristic, not introduced by this plan).
- The Phase 3 migration offline dry-run (`alembic upgrade head --sql`) proves the DRY-RUN MECHANISM works in this sandbox; it does not validate the actual CHECK-constraint DDL syntax until Phase 3's migration file is written, nor does it prove the migration applies cleanly against a real Postgres (Docker-gated, explicitly out of scope for live-apply in this sandbox, matching the `owned-data-layer` precedent).
- None of these test gates prove production-scale concurrent-write behavior, real third-party CMP/consent-tool integration edge cases beyond the `window.beamConsent()` hook contract, or actual visitor conversion/business-outcome impact of the wider capture surface.

Gate: PASS (no FAILs, plan updated)
Accepted by: N/A — Gate is PASS, no CONDITIONAL concerns to accept

---

## Autonomous Goal Block

```
SESSION GOAL: Widen tracker.js first-party email capture (value-match, mailto, URL-param,
autofill, shadow-DOM/same-origin-iframe) feeding visitor_emails / owned identity graph, via a
new Playwright harness (Phase 0 hard-blocks Phase 1-3).
Charter + umbrella plan: N/A — single plan, not a phase program.
Autonomy: standard /goal autonomous execution rules apply (orchestration.md §Autonomy Mode) —
CONDITIONAL findings apply-and-proceed, BLOCKED items go to backlog and continue, irreversible/
outward-facing actions without explicit contract instruction are a hard stop.
Hard stop conditions / safety constraints:
- No capture path may bypass the OPTOUT (GPC/DNT) gate — all new mechanisms MUST route through
  the existing captureEmail() funnel (G1/G3).
- URL-param capture MUST be placed after the GATED/consentDecision setup block, never at the
  _bid IIFE's location (G7 — new VALIDATE finding, prevents EU consent-hold bypass).
- No reading of a field's value before an interaction event fires on it this session (G6) — no
  prefilled/hidden-field/localStorage/sessionStorage/dataLayer reads, no cross-origin iframe DOM
  access outside a try/catch SecurityError boundary, no keystroke-level logging.
- Migration is Docker-gated, offline-validate only (alembic upgrade head --sql dry-run) — never
  live-apply against a real Postgres in this sandbox.
- Bundle size must stay under 5KB gzipped (npm run size).
- Do NOT touch company_graph / identity_signals schema or resolution logic (owned-data-layer
  plan's territory) — this plan only widens the visitor_emails upstream feed.
Next phase: EXECUTE — process/features/visitors-identity/active/first-party-capture_24-07-26/first-party-capture_PLAN_24-07-26.md
(start at Phase 0 — Playwright harness, hard prerequisite for Phases 1-3).
Validate contract: inline in plan (## Validate Contract section above), Gate: PASS.
Execute start: `cd apps/pixel && npx playwright test` (Phase 0 baseline, once harness exists) |
e2e spec: apps/pixel/e2e/capture-baseline.spec.ts | probe scenario: cross-browser autofill
matrix (AC5, Hybrid on webkit/firefox binary availability) | high-risk pack: no (no auth/
billing/schema-migration-live/public-API-break/deploy surface touched).
```

---

## Next Step

Plan complete. Review carefully. Say **"ENTER VALIDATE MODE"** when ready to proceed to plan validation (required before implementation) — see RIPER-5 phase table in CLAUDE.md.
