---
name: plan:site-analysis-onboarding
description: "COMPLEX plan — auto site analysis at onboarding Add-Site: sync fetch/extract at the site step, async grounded AI company-profile/ICP/competitor analysis fired from create_site, editable review panel on the install step, JSONB profile on sites, flag OFF by default"
date: 13-08-26
feature: onboarding-canary
metadata:
  node_type: plan
  type: plan
  complexity: COMPLEX
---

# PLAN — Auto Site Analysis at Add-Site (Onboarding)

**Date**: 13-08-26
**Status**: PLANNED — **PVL cycle 4 re-validated 13-08-26**: all five cycle-3 CONCERNs (C16–C20) and all twelve second-verifier findings (VF1–VF3 / VC4–VC9 / N10–N12) verified CLOSED; contract below is **Gate: CONDITIONAL, 0 FAILs, 4 NEW CONCERNs (C21–C24)** + 3 nits, not yet accepted
**Complexity**: COMPLEX
**Feature**: onboarding-canary
**SPEC**: `process/features/onboarding-canary/active/site-analysis-onboarding_13-08-26/site-analysis-onboarding_SPEC_13-08-26.md`

> **TL;DR:** Three internal work blocks behind one new flag (`site_analysis_enabled`, default OFF).
> **(1) Backend:** one migration adding 5 columns to `sites` (incl. `site_profile_candidate`, the
> review-staging slot); a NEW fetch/extract helper
> (`services/site_content.py`, new code only — `platform_detector.py` is NOT refactored) using
> `url_guard` with the DNS-pinned client posture (`pixel_verifier.py:122-124`); a two-call Gemini service (grounded prose →
> non-grounded JSON structuring); three flag-gated endpoints (`GET`/`PUT`/`POST /sites/{site_id}/analysis`);
> a Redis 3/day/site budget mirroring `usage_limits.check_osint_budget`; `asyncio.create_task` fire
> from `create_site` mirroring `routers/events.py:562`. **(2) Segmenter pre-seed:** verification only
> — zero prompt code changes. **(3) Frontend:** one self-contained `SiteAnalysisPanel` (own ~4s poll)
> inserted into `install-step.tsx` and reused in `site-settings-dialog.tsx`.
> Flag OFF ⇒ byte-identical behavior, new endpoints 404.

---

## Overview

Beam's Add-Site step today learns nothing about the business behind the URL: `Site.category` is
never filled and the downstream AI segmenter runs on near-empty context. This plan makes that step
smart — a fast sync fetch/extract when the URL is entered, then a grounded AI company-profile /
ICP / competitor analysis fired asynchronously from `create_site` and reviewed on the install step
in an editable panel. The confirmed profile is persisted as JSONB on `sites` and pre-seeds
`Site.description` / `Site.category`.

The work is one COMPLEX plan artifact (not a phase program) split into 3 ordered internal blocks —
Backend, Segmenter pre-seed verification, Frontend panel — sharing one validate-contract and one
EVL pass. Everything sits behind `site_analysis_enabled` (default **OFF**): flag OFF is
byte-identical to today and all new endpoints 404.

**Testing context:** verification follows `process/context/tests/all-tests.md` (runner selection,
the `.venv/bin/python3.11 -m pytest` invocation gotcha, and the local Postgres/Redis preconditions
for the integration lane). Per-block test gates plus a final regression gate are defined in
§Implementation Checklist; every gate maps to a SPEC acceptance criterion in
§Verification Evidence.

---

## Complexity

**COMPLEX** — single plan artifact (NOT a phase program). 3 dependent internal blocks, one
migration, new public API surface, prompt-injection + SSRF surfaces, **13** touched/created backend
files (8 created — 3 source + 1 migration + 4 tests — plus 5 modified: 4 source + `test_ssrf_guard.py`;
reconciles with §Touchpoints and §Blast Radius, N14) and ~8 web files (7 modified incl. the e2e spec + 1 created). Blocks are ordered but share one validate-contract and one EVL pass.

---

## Goals

| # | Goal | SPEC anchor |
|---|---|---|
| G1 | A site's HTML is fetched + text-extracted once at the site step, never blocking Continue | AC-1 |
| G2 | Grounded AI analysis runs async after site creation, surfacing pending/ready/failed on the install step | AC-2, AC-3, AC-4 |
| G3 | Results are shown editable; the user's edits (not raw AI output) are persisted | AC-5 |
| G4 | Confirm auto-fills `Site.description` / `Site.category` without silent overwrite | AC-6 |
| G5 | Segmenter prompt carries real description/category (verification only) | AC-7 |
| G6 | Owner can re-run analysis from site settings, budget-capped | AC-8, AC-10 |
| G7 | Flag OFF is byte-identical; mock mode works keylessly; hostile input is fenced; no PII/prompt logging | AC-9, AC-11, AC-12, AC-13 |

---

## Scope

**In:** the 3 blocks above, one alembic migration, one new service module + one shared extraction
helper, 3 endpoints, 1 flag + 2 settings, 1 React panel + 2 insertion points, unit + integration tests.

**Out (verbatim from SPEC §Out Of Scope):** no auto-outreach; no pixel/visitor/ingest/identity
changes; no `AgentProfile` coupling; no billing/plan/credit changes; no competitor monitoring; no
campaign-planner prompt work; no backfill of existing sites; no language special-casing.

---

## Locked Decisions Carried From SPEC + INNOVATE (do NOT redesign)

| ID | Decision | Rationale / evidence |
|---|---|---|
| D1 | Hybrid timing: sync fetch/extract at site step; async analysis via `asyncio.create_task` inside `create_site` | Precedent `apps/api/routers/events.py:562` (`_background_aggregate` + `_background_tasks` set + `add_done_callback`). Celery is NOT usable — no worker deployed, `config.py:106-114` drops tasks silently. No APScheduler sweep. |
| D2 | FAILED is derived at read time: `status == "pending"` AND `site_profile_started_at` older than `site_analysis_stale_seconds` ⇒ report FAILED. **The three timing constants are deliberately ordered and the ordering is load-bearing (C14): panel poll cap (60 polls × 4 s = 240 s) > stale threshold (`site_analysis_stale_seconds` = 180 s) > worst-case grounded latency (~120 s).** The panel must still be polling when the row crosses into stale, so a genuinely dead run resolves to `failed` on screen without a reload; and the stale threshold must sit above real latency so a live run is never derived FAILED mid-flight. Changing one constant without the other two is a regression (E13). | A process restart loses the in-memory task; without this the UI hangs on pending forever. |
| D3 | Split LLM calls: call 1 `gemini_generate(grounding=True)` prose research; call 2 `gemini_generate_json` (non-grounded, repair loop) structuring prose → JSON | `gemini_client.py:116-124` — `responseMimeType` is only set when `grounding` is False; JSON mode is ignored under grounding. |
| D4 | **(REVISED — PVL cycle 2, V1 option (a))** Storage is **two-slot**: JSONB `sites.site_profile` (the CONFIRMED profile, written ONLY by `PUT`) plus JSONB `sites.site_profile_candidate` (the un-reviewed run awaiting review, written ONLY by the analysis task), + status/timestamp columns. One migration, 5 additive nullable columns. No new table. No `AgentProfile` reuse. | SPEC C-2. The single-slot draft made AC-8 ("prior profile intact until the new run confirms") unimplementable — one slot cannot hold both the confirmed profile and the in-flight re-run (V1). |
| D5 | Endpoints `GET`/`PUT`/`POST /sites/{site_id}/analysis`; all 404 when flag OFF; tenant gate via `verify_site_access` (404-not-403) | SPEC C-10 + repo flag-off convention |
| D6 | **(REVISED — PVL cycle 1, F1 option (a))** The sync site-step path is UNCHANGED: it stays platform-detect only. `site_content.fetch_site_content` is new code used **only** by the async analysis. `platform_detector.py` is NOT refactored and NOT touched. | The two postures genuinely differ today (`platform_detector.py:174,223` use a bare `httpx.AsyncClient`; the pinned transport is used only by `pixel_verifier.py:124` and `crm/generic_webhook.py:45`). Delegating would silently upgrade `detect_platform` bare→pinned — a real behavior change that breaks AC-9's byte-identical guarantee, against zero behavioral test coverage. Smallest blast radius. |
| D7 | UI: one self-contained `SiteAnalysisPanel` with its own polling hook; inserted as a panel in install step AND reused in site settings | SPEC C-3 + AC-8 |
| D8 | Flag `site_analysis_enabled: bool = False`; budget 3 **analyses** (not Gemini calls) per site per day | SPEC C-4, C-5, AC-10 |
| D9 | `MOCK_EXTERNAL_APIS=true` short-circuits at the **service layer** with a deterministic profile | SPEC C-6, repo convention |
| D10 | Segmenter pre-seed is verification-only — no prompt change | `agents/segmenter.py:21-24` already interpolates `{site_description}`/`{site_category}` |
| D11 | **(NEW — PVL cycle 2, F5/V2)** The analysis budget has exactly ONE owner: `run_site_analysis` performs check + increment. The `POST` endpoint **checks only** (to shape the capped response) and never increments; `create_site` does no budget work at all. | Two owners = double-count on the re-run path, halving the documented 3/day cap; and both AC-10 gates were structurally blind to it (F5). One owner makes auto-start and re-run behave identically. Accepted residual: the check→increment window is a TOCTOU race (see R11) — acceptable for a best-effort free-tier guard, not a billing meter. |
| D12 | **(NEW — PVL cycle 2, V4)** `POST` carries a server-side in-flight guard: while the derived status is `pending`, the endpoint returns the current state + `already_running: true` and does **not** increment, re-stamp `started_at`, or fire a task. | Precedent `apps/api/routers/events.py:75` (`_aggregating: set[str]`) + `:560-567` (add / `discard` in the done-callback). Without it, repeated clicks re-arm `started_at` (defeating D2's stale derivation) and stack overlapping tasks that race on the same row. **Placement (VC6, rationale corrected — cycle 5, N13): the `_analysis_inflight: set[str]` container lives in `apps/api/services/site_analysis.py`, NOT in the router.** The original import-cycle argument is **stale**: under the final design the *service never discards* (the router's done-callback does), so a router-side set would touch only the router and would create no cycle either. The placement stands on a different and still-valid ground — the set is analysis-domain state that the service owns and that any future non-router caller must be able to read, and it keeps the container next to `run_site_analysis` rather than in a router that already carries three unrelated endpoints. **Cleanup is the `add_done_callback` registered by the fire helper, mirroring `events.py:560-567` exactly — NOT a `finally` inside the coroutine**: a done-callback fires on every outcome including cancellation, a coroutine `finally` does not run if the task is cancelled before it starts. |
| D13 | **(NEW — PVL cycle 2, V3; case table completed VC7)** `apply_description` is **fail-safe**. Full case table, authoritative — the panel and §Public Contracts must not diverge from it: (a) `currentDescription === undefined` / prop absent / unknown ⇒ **`false`**; (b) `currentDescription === null` ⇒ **known-empty** (a *server-asserted* value — `Site.description` is `string \| null` in `api-types.ts:156`, so `null` means "the server says there is no description", not "unknown") ⇒ `true` is permitted; (c) `currentDescription === ""` ⇒ known-empty ⇒ `true` permitted; (d) non-empty string ⇒ default **`false`**, keep/replace choice shown, and **the user's explicit "replace" choice MAY set `apply_description=true`** — that is a deliberate human decision, not a silent overwrite. Cases (b)+(c) are what make auto-fill actually reachable on the reliable settings path. | The `useState` plumbing from F3 is lost on reload/resume (`PersistedFlow` carries no description field), so "unknown" is a routine runtime state, not an edge case. Defaulting `true` on unknown re-introduces exactly the silent overwrite AC-6 exists to prevent (V3). The `useState` path stays as a best-effort enhancement, not a correctness dependency. |
| D15 | **(NEW — PVL cycle 3, VF1; rule restated as a precedence — cycle 5, C21)** `SiteAnalysisOut.message` is **derived at read time, never persisted**, by a **single helper** shared by `GET` and `POST`. Rule is a top-down precedence on `(allowed, derived status)`, not a status switch: (1) `allowed == false` ⇒ the cap copy **regardless of status**; (2) `allowed == true` AND `failed` ⇒ the generic copy; (3) otherwise `null`. See §Public Contracts for the authoritative statement. **Accepted residual (R13):** a non-budget failure while the counter is exhausted reports the cap copy — the deliberate price of not adding a sixth column. | A stored message would need a 6th column the migration does not have, so two named gates (`test_budget_denied_run_sets_terminal_failed_with_message`, `test_budget_denied_run_does_not_linger_pending`) were literally unimplementable as written (VF1). Deriving it keeps the schema at five columns and keeps the cap copy truthful — it re-reads the live counter rather than replaying a stale string. |
| D16 | **(NEW — PVL cycle 3, C18/VC4 + VC9)** `PUT` is **status-preserving and promotion-optional**: it never downgrades an in-flight `pending`; it never stamps `analyzed_at` (single writer = the task, meaning "when the run that produced the candidate finished"); it is legal with `candidate = NULL`; and it carries `promote: bool = True`, where `false` NULLs the candidate and touches nothing else. | Unconditionally setting `status="ready"` erased the exact state D2's stale derivation and D12's cross-process guard both read, reopening the double-run hole D12 was created to close (VC4). `promote:false` supplies the missing dismiss path — without it a candidate shadows the confirmed profile forever with no exit but confirming it (VC9). |
| D17 | **(NEW — PVL cycle 3, VF3 + VC5)** The panel has **four** states, not three: `none` (never analyzed — "Beam hasn't analyzed this site yet" + a budget-gated **Analyze** button) joins pending/failed/ready; and the review UI renders whenever `(candidate ?? profile)` is non-null **regardless of status**, with `failed` shown as a banner ABOVE it. **(EXTENDED — cycle 5, C22):** slot emptiness is decided **before** the status switch — both slots empty ⇒ the `none` presentation whatever `status` says, which closes the `promote:false`-dismiss-of-a-first-ever-candidate cell (`status="ready"`, both slots empty) that otherwise fell into the `ready` branch; and the review/edit UI is **owned by the render rule alone**, with status branches contributing only a banner / indicator / empty-state strip above it. | Every site created before the flag flip has `site_profile_status = NULL`, and the re-run button lived only on the `failed` branch — so AC-8 ("owner can re-run from site settings") was unreachable for the entire existing fleet (VF3). Separately, `status` describes the last *run*, not which slots hold data: rendering `failed` instead of the review UI hides an already-confirmed profile behind an error screen (VC5). |
| D14 | **(NEW — PVL cycle 2, V7)** The analysis budget is **NOT BYOK-exempt** — `check_site_analysis_budget` caps unconditionally. | The analysis runs on the SYSTEM Gemini key (the operator pays), so the correct precedent is the paid-OSINT meter, whose own comment states it verbatim: `usage_limits.py` — "NOT BYOK-exempt: the paid key is a SYSTEM key (operator pays), so the cap always applies." Copying the BYOK-uncapped `check_osint_budget` shape would let any BYOK user run unlimited system-key grounded calls (V7). |

---

## Touchpoints

### Backend — create

| File | Purpose |
|---|---|
| `apps/api/services/site_content.py` | Shared fetch + text-extraction helper (SSRF-guarded); returns raw text + title + meta description + platform-detect passthrough |
| `apps/api/services/site_analysis.py` | The 2-call analysis service, mock branch, sanitization, persistence, budget consumption |
| `apps/api/schemas/site_analysis.py` | `SiteProfile`, `SiteAnalysisOut`, `SiteAnalysisConfirm` Pydantic models |
| `apps/api/migrations/versions/<rev>_add_site_profile.py` | **Five** additive nullable columns on `sites` (incl. `site_profile_candidate`) — C19/N10 |
| `tests/unit/test_site_content.py` | Extraction + SSRF-posture + adversarial-HTML unit tests |
| `tests/unit/test_site_analysis.py` | Prompt assembly, sanitization, mock-mode, log-hygiene, status derivation |
| `tests/unit/test_site_analysis_segmenter_preseed.py` | AC-7 segmenter prompt assembly with a profiled site fixture |
| `tests/integration/test_site_analysis_api.py` | Endpoint lifecycle, flag-off, tenant, budget, PUT precedence |

### Backend — modify

| File | Change |
|---|---|
| `apps/api/models/site.py` | +5 columns (`site_profile`, **`site_profile_candidate`**, `site_profile_status`, `site_profile_started_at`, `site_profile_analyzed_at`) |
| `apps/api/config.py` | +`site_analysis_enabled`, `site_analysis_daily_budget`, `site_analysis_stale_seconds`, `site_analysis_fetch_timeout_seconds` |
| `apps/api/routers/sites.py` | 3 new endpoints + flag-gated `asyncio.create_task` fire in `create_site` (after `await db.refresh(site)` — anchor text, currently ~`sites.py:187`) (the in-flight guard set itself lives in `services/site_analysis.py` per VC6, not here). **`detect_platform_endpoint` is NOT modified.** |
| `apps/api/services/usage_limits.py` | +`_site_analysis_count_key`, `get_site_analysis_usage`, `increment_site_analysis_usage`, `check_site_analysis_budget` (shape copied from the OSINT block, lines 163-201, but **NOT BYOK-exempt** per D14 — the paid-OSINT block below it is the correct posture precedent) |

**Why a new module and not `content_reader.py` (recorded decision, C7):** `content_reader.py` already
does fetch + extract + Redis cache + mock + rate limit, but for a different purpose and with a
different guard posture (it carries yt-dlp / Reddit / transcript coupling and its own cache
semantics). `site_content.py` is a deliberately small, single-posture (DNS-pinned, no-redirect,
no-cache) choke point for the analysis path. The duplication is intentional, not an oversight.

**Not touched (PVL cycle 1, F1 option (a)):** `apps/api/services/platform_detector.py` and
`apps/api/schemas/sites.py` — the sync `detect-platform` path keeps today's exact behavior and
response shape.

### Web — create

| File | Purpose |
|---|---|
| `apps/web/src/components/site-analysis-panel.tsx` | Self-contained panel: own polling hook, pending/ready/failed states, editable fields, confirm, re-run |

### Web — modify

| File | Change |
|---|---|
| `apps/web/src/components/onboarding/steps/install-step.tsx` | **EDITED (F3):** add one optional prop `currentDescription?: string \| null` to the props type and forward it; render `<SiteAnalysisPanel siteId={siteId} variant="onboarding" currentDescription={currentDescription} />` inside `<div className="ob-bubble plain wide">`, immediately **after the `detecting` ternary block** |
| `apps/web/src/components/onboarding/onboarding-flow.tsx` | **EDITED (F3 + V5):** (a) capture the submitted description in a component-local `useState` inside `handleCreateSite` (`:143-149`) and pass it down as `currentDescription` to `<InstallStep>` (`:355-365`) — best-effort only, D13 makes correctness independent of it; (b) **mount the panel a second time on the `done` step** inside the existing `{queue.done && state.step === "done" && (…)}` block (`:367-369`, beside `<DoneStep …>`), because `VERIFIED` unmounts `InstallStep` and would otherwise destroy the results surface mid-analysis (V5). No `flowReducer` field, no new `StepId`/`FlowEvent` — reducer surface stays untouched. |
| `apps/web/src/components/site-settings-dialog.tsx` | Render `<SiteAnalysisPanel siteId={site.site_id} variant="settings" currentDescription={site.description} />` with the re-run button. **Target scope (C13/V3): the inner `SiteSettingsBody` (`:63`), BELOW its `if (!site)` early return (`:165`) — e.g. after the "Site details" block (`:173`).** The exported `SiteSettingsDialog` (`:29`) receives only `{ siteId }` and has no `site` object; rendering there is impossible. This call site is the one that reliably supplies `currentDescription` (`Site.description`, `api-types.ts:156`) — the onboarding one is best-effort per D13. |
| `apps/web/src/lib/api.ts` | +`getSiteAnalysis`, `confirmSiteAnalysis`, `rerunSiteAnalysis` |
| `apps/web/src/lib/api-types.ts` | +`SiteProfile`, `SiteAnalysis` types; `Site` unchanged |
| `apps/web/src/styles/onboarding-chat.css` | `.ob-analysis*` classes for the onboarding variant |
| `apps/web/e2e/onboarding.spec.ts` | **EDITED (N4):** the `E2E_SITE_ANALYSIS`-guarded Playwright legs of step 3.7 (previously uncounted in §Blast Radius) |

---

## Public Contracts

### New endpoints (all under the existing `/api/v1/sites` router)

All three: `Depends(get_current_user)` → `verify_site_access(db, site_id, user)` (404 for foreign
site ids, never 403). All three return **404** when `settings.site_analysis_enabled` is False, with
the flag check FIRST (before any DB read), so flag-off leaks nothing.

**`GET /sites/{site_id}/analysis` → `SiteAnalysisOut`**

```
{ "site_id": str,
  "status": "none" | "pending" | "ready" | "failed",
  "profile": SiteProfile | null,      # the CONFIRMED profile (sites.site_profile)
  "candidate": SiteProfile | null,    # an un-reviewed run awaiting confirm (sites.site_profile_candidate)
  "analyzed_at": iso8601 | null,
  "message": str | null,              # DERIVED at read time, NEVER persisted (VF1); null normally
  "already_running": bool,            # POST-only signal; always false on GET
  "budget": { "used": int, "limit": int | null, "allowed": bool } }
```

`status` is **derived** per D2: stored `"pending"` whose `site_profile_started_at` is older than
`site_analysis_stale_seconds` reports `"failed"` (the DB row is NOT mutated on read).

- **Review payload = `candidate` when non-null, else `profile`** (V1 option (a)). The panel reviews
  the candidate; `profile` is what the site actually uses today. A first-ever analysis lands in
  `candidate` too — one uniform path, no special-casing.
- **Render rule (VC5/C22), binding on the panel — and its ONLY owner:** slot emptiness is decided
  FIRST — both slots null ⇒ the `none` presentation whatever `status` says (reachable via a
  `promote:false` dismiss of a first-ever candidate, which leaves `status="ready"` with both slots
  empty). Otherwise the review/edit UI is shown whenever
  `(candidate ?? profile)` is non-null, **regardless of `status`**. The review/edit UI is rendered
  exactly once, by this rule; `status` contributes only a banner / indicator / empty-state strip
  above it and never renders that UI itself. A `failed` status renders as a
  **banner ABOVE** that review UI, never *instead* of it. Otherwise a failed re-run would hide an
  already-confirmed profile behind an error screen — `status` is a single field describing the last
  run, not a description of which slots hold data.
- `message` (V10, **revised VF1; rule restated as a precedence — PVL cycle 5, C21**) is **DERIVED
  at read time and is NEVER a stored column** — the migration stays at five columns.
  **This bullet is the SINGLE definition of the rule.** It is implemented **once**, in one helper,
  and that same helper produces `message` for `GET`, for the `POST` capped response and for every
  other `POST` response. No other section of this plan may state a second derivation; where any
  other text disagrees, this bullet wins.
  **Derivation is a PRECEDENCE over the `(budget.allowed, derived status)` pairs — evaluated
  top-down, first match wins — NOT a switch on `status`:**
  1. `budget.allowed == false` ⇒ `message` = "Daily analysis limit reached — try again tomorrow"
     (the cap copy) — **regardless of `status`**, including `none`, `pending`, `ready` and
     `failed`. This single cell is what the `POST` capped response needs (where the stored status
     is normally `ready` or `none`) AND what the panel's budget-disabled **Analyze**/re-run button
     needs for its copy (where a never-analyzed site is `none`);
  2. `budget.allowed == true` **AND** derived `status == "failed"` ⇒ the generic copy
     "We couldn't analyze your site — you can add details yourself.";
  3. otherwise ⇒ `null`.
  Nothing in the write path ever stores a message string; a budget-denied run is recorded solely as
  `site_profile_status = "failed"` and is re-described at read time from the live budget counter.
  **Named residual (accepted, R13 — the deliberate price of D15's no-sixth-column decision):**
  because rule 1 keys only on `allowed`, a run that failed for a *non-budget* reason (fetch error,
  Gemini error) while the counter happens to be exhausted is reported with the **cap** copy,
  misattributing the cause. Distinguishing the two would require persisting the failure reason —
  the sixth column D15 deliberately avoids. Accepted, not a defect to "fix" during EXECUTE.
- `budget` deliberately **omits `is_byok`** (V10): this meter is not BYOK-exempt (D14), so the field
  would always be `false` and would invite a future reader to re-introduce an exemption.
- `budget` is computed from a **single plain Redis GET** of the day counter — no `user_api_keys`
  SELECT, so a 4 s poll costs one Redis read and **zero extra DB round-trips** (N5). This is only
  possible because of D14; a BYOK-exempt meter would require the DB lookup on every poll.

**`PUT /sites/{site_id}/analysis` → `SiteAnalysisOut`** — body `SiteAnalysisConfirm`:

```
{ "profile": SiteProfile,            # the user's (possibly edited) version — this WINS
  "apply_description": bool,          # fail-safe default false unless the client can prove the
                                      #   current description is empty or the user explicitly
                                      #   chose "replace" (D13/VC7)
  "apply_category": bool,             # default true
  "promote": bool }                   # default TRUE. false ⇒ DISMISS-only (VC9): NULL the
                                      #   candidate and touch nothing else
```

- **`promote: true` (default) — promote candidate → confirmed:** persists `profile`
  verbatim-after-sanitization into `sites.site_profile` and **sets
  `sites.site_profile_candidate = NULL`**. **`PUT` is the ONLY writer of `sites.site_profile`**
  (V1 option (a)); the analysis task never touches it.
- **`promote: false` — DISMISS only (VC9):** sets `sites.site_profile_candidate = NULL` and
  **touches nothing else** — `site_profile`, `site_profile_status`, `site_profile_started_at` and
  `site_profile_analyzed_at` are all left exactly as they are, and neither `Site.description` nor
  `Site.category` is written. This is the "keep what I have, throw away this re-run" path; without
  it a candidate shadows the confirmed profile forever with no way out but confirming it.
- **`PUT` must NOT downgrade an in-flight run (C18/VC4).** Status handling is conditional:
  - derived status is `pending` ⇒ **leave `site_profile_status` and `site_profile_started_at`
    untouched**. The row stays `pending`, so D2's stale derivation still fires on a dead run and
    D12's cross-process in-flight check still sees the run. The confirmed profile is written all
    the same — the two slots are independent.
  - derived status is anything else ⇒ set `site_profile_status = "ready"`.
- **`PUT` with `site_profile_candidate = NULL` is ALLOWED and is a normal path (C18/VC4):** it is
  how the owner edits the confirmed profile directly (from settings, or after a dismiss), and it is
  also legal when `status == "none"` (a user-authored profile with no analysis behind it). The body
  carries the full profile, so nothing about the candidate slot is required.
- **`analyzed_at` means exactly one thing (C18/VC4): the completion time of the ANALYSIS RUN that
  produced the candidate.** It is stamped by the analysis task at step (6) and **never by `PUT`**.
  A `PUT` that promotes a candidate leaves the task's timestamp in place (it is still the time that
  content was analyzed); a `PUT` on a never-analyzed or user-authored profile leaves it `NULL`. No
  second timestamp column is added.
- Sets `Site.description` from `profile.summary` (truncated to 1000) only when `apply_description`
  is True. Sets `Site.category` from `profile.category` (truncated to 100) only when
  `apply_category` is True. **AC-6 no-silent-overwrite is enforced client-side by the panel** (D13
  fail-safe, VC7 case table: it sends `apply_description=false` whenever `currentDescription` is
  non-empty **or unknown/`undefined`**; `true` is permitted when the value is **known-empty —
  `null` (server-asserted "no description") or `""`** — or when the user explicitly chose
  "replace" on a non-empty description) **and
  server-side by honoring the booleans literally** — the server never infers.
- Marks `profile.meta.user_edited = true`.

**`POST /sites/{site_id}/analysis` → `SiteAnalysisOut` (202-shaped body, HTTP 200)** — re-run.

- **In-flight guard (D12/V4), checked FIRST:** if the derived status is `pending`, return HTTP 200
  with the current state unchanged plus `already_running: true` — **no budget increment, no
  `started_at` re-stamp, no task fired.** In-process half = a module-level `_analysis_inflight:
  set[str]` mirroring `events.py:75` + `:560-567`; cross-process half = the derived-pending check.
- **Budget: the endpoint CHECKS but never increments (D11/F5).** When
  `check_site_analysis_budget(...)["allowed"]` is False, returns HTTP **200** with `status`
  unchanged and `budget.allowed=false`. Never 4xx, never a partial profile (AC-10).
  **`message` is NOT restated here (C21):** it comes from the single derivation helper defined in
  the `GET` `message` bullet above, whose rule 1 (`allowed == false` ⇒ cap copy, regardless of
  status) already yields the cap copy for this response. Do not re-derive it in the `POST`
  handler.
- On allow: sets `status="pending"` + `started_at=now` and fires the task **via
  `_fire_site_analysis` (1.10) — never a bare `asyncio.create_task`** (C23). That helper is the only
  place the `site_id` is added to `_analysis_inflight`, the task is added to `_analysis_tasks`, and
  the single `add_done_callback` performing **both** discards is registered. A direct
  `asyncio.create_task(run_site_analysis(...))` breaks three things at once: the `site_id` is never
  discarded, so every later `POST` returns `already_running` forever in-process and AC-8's re-run is
  permanently dead; the task is absent from `_analysis_tasks`, so `await asyncio.gather(*_analysis_tasks)`
  (the C17(d) hardening) awaits nothing; and the strong reference is dropped, so the task can be
  garbage-collected mid-run. **`run_site_analysis` performs the single authoritative
  check + increment**, so auto-start and re-run consume the counter identically — exactly one
  increment per user-visible run, end to end (E7).
- **The confirmed `site_profile` is never touched by a re-run** — the new run lands in
  `site_profile_candidate`; only `PUT` promotes it (AC-8 "never silently discards edits").

### Unmodified contract — `PlatformDetectResponse` (PVL cycle 1)

**No change.** The earlier draft added two optional fields (`content_available`, `extracted_chars`)
to the sync detect-platform response. That is **dropped from scope v1** together with the
`platform_detector` refactor (F1 option (a)). The sync path stays platform-detect only; ALL content
extraction happens in the async analysis fetch. This also removes the internal field-name
contradiction (C2) and the `PlatformResult` passthrough problem (C3) by deletion — `PlatformResult`
(`platform_detector.py:32-37`) is not extended and not read by any new code.

### `SiteProfile` shape (JSONB, per SPEC §Constraints data table)

```
{ "summary": str,                       # 2-3 sentences
  "sells": [str],                       # <= 8
  "category": str,                      # <= 100 chars, usable as Site.category
  "sub_industry": str | null,
  "icp": { "personas": [ {"role": str, "pain": str} ],           # <= 3
           "firmographics": {"size_band": str|null,
                             "industries": [str],
                             "geography": [str]} },
  "competitors": [ {"name": str, "domain": str|null, "how": str} ],   # <= 5
  "meta": { "v": 1,                       # JSONB schema version (V8) — bump on any shape change
            "analyzed_at": iso8601, "model": str, "mode": "grounded"|"mock",
            "confidence": {"summary": float|null, "icp": float|null,
                           "competitors": float|null},
            "unknown": [str],           # section names the model declined to fill
            "user_edited": bool } }
```

Every string field is capped and `clean_text`-ed before storage (see §Security).
`competitors[].domain` is additionally **hostname-validated with a POSITIVE check** (V6, tightened
VC8): it is LLM-controlled free text, so `sanitize_profile` keeps it **only if BOTH hold** —
(a) `urlsplit(domain).scheme in {"", "http", "https"}`, and (b) the derived host (the `netloc`
when present, else the whole trimmed string) matches a plain hostname regex
(`^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$`, case-insensitive, no port,
no path, no userinfo, no whitespace). Anything else becomes `null`. **The old "survives
`strip_url`" phrasing is REMOVED (VC8): `strip_url` is not a validator** — it returns its input
unchanged when there is no `netloc`, so `javascript:alert(1)` passes straight through it. The UI renders competitor domains as **plain text, never as an anchor/`href`** — no reader
is ever one click from a model-chosen URL.
`meta.v` is written on every persisted profile (candidate and confirmed) and by `mock_profile`.

---

## Blast Radius

| Dimension | Value |
|---|---|
| Files created | 3 backend source + 1 migration + 4 test files + 1 web component = 9 |
| Files modified | 4 backend (`models/site.py`, `config.py`, `routers/sites.py`, `services/usage_limits.py`) + 1 existing test file (`tests/unit/test_ssrf_guard.py`) + **7 web** (6 + `apps/web/e2e/onboarding.spec.ts`, N4) = **12** |
| Packages/surfaces | `apps/api` (routers, services, models, schemas, migrations), `apps/web` (onboarding + dashboard settings), `tests/` |
| Risk classes present | **public API contract change** (3 new endpoints; no change to any existing response shape); **schema migration** (**five** additive nullable columns — C19/N10); **outbound fetch of user-supplied URL** (SSRF surface); **LLM prompt boundary** (injection surface) |
| NOT touched | pixel (`apps/pixel/`), event ingest, identity resolution, billing, `AgentProfile`, campaign planner, segmenter prompt text, **`services/platform_detector.py`**, **`schemas/sites.py`**, **`flowReducer` (`lib/onboarding-flow.ts`)** |
| Regression surfaces to re-prove | existing `create_site` tests, `tests/unit/test_site_limit.py`, `tests/integration/test_onboarding_canary_api.py`, `tests/unit/test_prompt_safety.py`, `tests/unit/test_ssrf_guard.py` |

**Baselines (no regression allowed):** **measured at EXECUTE start on the actual working tree,
before any source edit, using the canonical lane commands, and recorded verbatim in the phase
report.** Gate = **zero NEW failures vs that measured baseline** (not a hard-coded pass count).
Numbers quoted from context docs are explicitly FORBIDDEN as a baseline — the previously quoted
`1280` / `537` figures were ~6 days and several hundred tests stale, which would let hundreds of new
regressions satisfy the gate. Canonical commands (`process/context/tests/all-tests.md`):

```bash
.venv/bin/python3.11 -m pytest tests/unit -m unit -q
.venv/bin/python3.11 -m pytest tests/ -m integration -q
```

(The `-m` markers are mandatory; dropping `-m unit` pulls ~961 non-unit tests into the unit lane, and
`tests/integration` is a different set from `tests/ -m integration`. The `python3.11` form is this
machine's correct runner — the `.venv/bin/pytest` shebang is broken.)

---

## Architecture Note — data flow (prose, per vc-sequential-thinking + vc-scenario)

1. **Site step (sync) — UNCHANGED (PVL cycle 1).** Web calls `POST /sites/detect-platform` (existing
   effect, `onboarding-flow.tsx:172-190`) and the backend runs `detect_platform(url)` exactly as it
   does today: its own bare-client fetch, its own scoring, its own response shape. **No content
   extraction happens on this path and no new field is returned.** Continue is never gated on this
   call (the web effect already tolerates failure via `PLATFORM_FAILED`). The hybrid timing (D1) is
   therefore: **sync platform-detect (existing, untouched) + async fetch+extract+analysis**.
2. **Continue.** `api.createSite` → `create_site` runs unchanged through dedup/limit/tombstone/commit.
   After `await db.refresh(site)` and BEFORE the return, when the flag is ON: set
   `site_profile_status="pending"`, `site_profile_started_at=now`, commit, then
   `asyncio.create_task(run_site_analysis(site.site_id))` registered in a module-level
   `_analysis_tasks: set` with an `add_done_callback` discard (exact `events.py:558-570` shape). The
   task takes its **own DB session** — `async with async_session() as db:`
   (`from apps.api.models.database import async_session`, defined at `models/database.py:78`, used
   this way at `events.py:946`). It must never reuse the request session, which is closed when the
   response returns. (The earlier draft named `async_session_maker`; that symbol does not exist — C4.)
3. **Analysis task.** `run_site_analysis(site_id)`: **`settings.mock_external_apis` short-circuit
   FIRST — before the budget check and before any fetch** (F4) — returning the deterministic
   `mock_profile(site)` and persisting it **into `site_profile_candidate`** (V1: the task never writes
   `site_profile`); only then, in the non-mock path: **the single authoritative budget check +
   increment (D11 — this is the ONLY increment in the system; the POST endpoint checked but did not
   increment). If the check DENIES, the task sets a terminal state immediately — `status="failed"`,
   commit, RETURN — and writes **no message string at all** (VF1: `message` is derived at read time
   from `status == "failed"` + a still-exhausted budget counter). It must never leave the row
   `pending` for the full stale window, which would surface a budget denial as a mysterious
   3-minute-late failure (C15/V-gap 9).** Then → fetch via
   `site_content.fetch_site_content` → extract text → **call 1** `gemini_generate(prompt1,
   grounding=True, max_output_tokens=2048)` where `prompt1` embeds the extracted text through
   per-field `clean_text` + `wrap_untrusted` → **call 2** `gemini_generate_json(prompt2, validate=...)`
   where `prompt2` embeds **the call-1 prose, itself re-fenced** (the prose is model output derived
   from hostile input — it is untrusted at the second boundary too) → validate → sanitize every
   string field → persist **`site_profile_candidate`** (NOT `site_profile`), `status="ready"`,
   `analyzed_at=now` → commit. Any
   exception → `status="failed"`, commit, log `site_analysis_failed` with `site_id` + `error_class`
   only. Defence in depth: `fetch_site_content` ALSO carries its own `settings.mock_external_apis`
   branch returning a deterministic fixture (mirroring `content_reader.py:262,356,744`), so no code
   path can issue a live outbound request under mock mode. This is the only fetch of the site — the
   earlier "accepted double fetch" is gone with the sync-path extraction (D6 revised).
4. **Install step (poll).** `SiteAnalysisPanel` polls `GET .../analysis` every 4 s, stops on
   `ready`/`failed` or after **60 polls (≈240 s)** — deliberately **longer than the 180 s stale
   threshold**, which is itself longer than the ~120 s worst-case grounded latency (D2/C14). A dead
   run therefore resolves to `failed` on screen while the panel is still polling; no reload needed.
   Onboarding completion is never gated on the panel state. **The panel is mounted twice (V5):** on
   the `install` step AND on the `done` step (`onboarding-flow.tsx:367-369`), because `VERIFIED`
   unmounts `InstallStep` — a pixel that verifies in ~20 s would otherwise destroy the results
   surface ~100 s before the analysis lands, silently no-op'ing the whole AC-3→AC-7 chain.
5. **Confirm.** `PUT` **promotes** the reviewed candidate: writes the user's edited profile into
   `site_profile`, NULLs `site_profile_candidate`, and conditionally fills description/category
   (fail-safe per D13 — `apply_description=false` whenever the current description is non-empty *or
   unknown*).
6. **Downstream.** `agents/segmenter.py` reads `Site.description`/`Site.category` through its
   existing interpolation — no code change.

**Cross-service failure modes considered:** Redis down → budget helper fails **open to 0 used**
(matches `get_osint_usage`; this is a free-tier internal guard, not a billable credit guard — the
fail-closed `osint_paid` posture does not apply). Gemini down/keyless → `status="failed"`, onboarding
unaffected. Process restart mid-analysis → row stuck `pending` → D2 read-time derivation reports
`failed`. Concurrent re-run + in-flight run → **the server-side in-flight guard (D12) is the real
defence**: a `POST` while the derived status is `pending` returns `already_running: true` and fires
nothing, so overlapping tasks do not stack and `started_at` is never re-armed (which would defeat
D2's stale derivation). The panel's disabled-while-pending button is a UX nicety, not the control.
Even if two tasks did overlap, last writer wins on **`site_profile_candidate` only** — the confirmed
`site_profile` is unreachable from the task path (V1), so no confirmed user edit can be lost.
Budget check→increment is a best-effort TOCTOU window (R11), not a billing meter.

---

## Security (vc-security STRIDE scan — outbound fetch + LLM boundary)

| Threat | Surface | Mitigation (mandatory, in the checklist) |
|---|---|---|
| **SSRF / information disclosure** | Analysis fetches a user-supplied URL server-side | **Reuse `apps/api/services/url_guard.py` with the DNS-PINNED client posture** — `await is_safe_public_url(url)` pre-check, then `safe_get(client, url)` on a `pinned_client` (DNS-pin closes the rebinding TOCTOU; ports restricted to 80/443; private/loopback/link-local/metadata rejected incl. IPv4-mapped v6). `follow_redirects=False`. **The guard already exists and is adequate — the mandate is to REUSE it, not to write a second one.** **Correct precedent: `apps/api/services/pixel_verifier.py:122-124`** (also `crm/generic_webhook.py:45`). **NOT `platform_detector.py`** — that module constructs a bare `httpx.AsyncClient` (`:174`, `:223`) and therefore has the pre-check + per-hop revalidation but *not* the rebinding-TOCTOU close; the earlier draft's citation was factually wrong (F1). `site_content.fetch_site_content` is the single choke point; `site_analysis.py` MUST NOT construct a bare `httpx.AsyncClient`. |
| **Prompt injection (boundary 1)** | Extracted site HTML → call-1 prompt | Per-field `clean_text(value, max_len)` on every extracted string (title, meta description, body text), then `wrap_untrusted(...)`. `sanitize_profiles` is NOT reusable — it only covers the fixed `_TEXT_FIELD_CAPS` table (`prompt_safety.py:27,69-82`); new field names pass through untouched. |
| **Prompt injection (boundary 2)** | Call-1 grounded prose → call-2 prompt | The prose is model output derived from hostile input. `clean_text` + `wrap_untrusted` again before embedding in prompt 2. |
| **Stored-injection / tampering** | AI output → JSONB → UI | `clean_text` every string in the validated profile before persistence AND on the `PUT` path (user-supplied bodies are equally untrusted). Caps: summary 1000, category 100, each list item 300, list lengths per §Public Contracts. **`competitors[].domain` gets an extra POSITIVE hostname check (V6, tightened VC8):** it is a fully LLM-controlled string today with no validation — `sanitize_profile` keeps it only if `urlsplit(domain).scheme in {"", "http", "https"}` **AND** the derived host matches a plain hostname regex; anything else becomes `null`. **Do not use `strip_url` as the validator (VC8)** — it returns its input unchanged when there is no `netloc`, so `javascript:` survives it. **The UI renders it as plain text, never an anchor/`href`**, so a model-chosen `javascript:`/attacker URL is never one click away. |
| **Information disclosure via logs** | structlog | Log **keys/ids/counts only**: `site_analysis_started/complete/failed` with `site_id`, `chars`, `duration_ms`, `error_class`. **Never** log the prompt, the extracted body, the prose, or the profile. |
| **DoS / cost burn** | Unbounded grounded calls | 3 analyses/day/site Redis counter (**not BYOK-exempt** — D14); timeout `site_analysis_fetch_timeout_seconds=10`; extracted text truncated to ~12 000 chars before the prompt. **Real body-cap posture (corrected, C11):** `safe_get` (`url_guard.py:130-151`) does `resp = await client.get(url)` — the body is **fully buffered** before it returns and there is no streaming hook. So the achievable cap is (a) a `Content-Length` **pre-check** rejecting anything > 512 KB with `ok=False`, plus (b) **post-hoc truncation** of `resp.text`. **Accepted residual:** a chunked response with no `Content-Length` is still buffered in full before we can refuse it. Bounded blast: authed endpoint, 3 runs/day/site, 10 s timeout. Adding a streaming variant to `url_guard` is larger scope and explicitly out of scope here. |
| **Elevation / tenancy** | New endpoints | `verify_site_access` on all three; foreign ids 404. |

---

## Risk Predictions (vc-predict, 5-persona)

| # | Risk | Severity | Mitigation in checklist |
|---|---|---|---|
| R1 | ~~`platform_detector` refactor changes flag-OFF fetch behavior~~ **RETIRED (PVL cycle 1, F1 option (a))** — the refactor is removed from scope, so the risk does not exist. `platform_detector.py` is not touched. Its pre-existing zero behavioral test coverage (C1) and the bare-client posture of `_probe_shopify_api` (`:223`) are recorded as pre-existing repo gaps in a backlog note, explicitly NOT inherited or altered here. | — (retired) | Step 1.6 is REMOVED; §Touchpoints lists `platform_detector.py` under NOT touched |
| R2 | Background task reuses the request DB session → `MissingGreenlet`/closed-session error | HIGH | Step 1.9 mandates `async with async_session() as db:` inside the task (`models/database.py:78`; pattern `events.py:946`); unit test asserts the task opens its own session |
| R3 | Budget counts Gemini calls (2/analysis) instead of analyses → effective 1.5/day | MED | Step 1.7/1.9 increment exactly once per `run_site_analysis` entry, before call 1; unit test asserts 1 increment per run |
| R4 | Grounded call 2 returns prose not JSON (JSON mode silently ignored) | HIGH | D3 splits the calls; call 2 is non-grounded. Integration mock test asserts the structuring call receives `grounding=False` |
| R5 | Canary phases 2-4 rewrite `install-step.tsx` and drop the panel | MED | Named re-insertion point below + §Coordination |
| R6 | Analysis stuck `pending` forever after a deploy | MED | D2 read-time FAILED derivation + integration test with a backdated `started_at` |
| R7 | AC-6 silently clobbers a user-typed description | MED | **(REVISED — PVL cycle 2, V3) The correctness guarantee no longer depends on the `useState` plumbing.** D13 makes the panel **fail-safe**: absent/unknown `currentDescription` ⇒ `apply_description=false`; only a *known-empty* description permits `true`. This matters because the F3 `useState` value is lost on reload/resume (`PersistedFlow` has no description field), so "unknown" is a routine state. The plumbing (`onboarding-flow.tsx` local state → `InstallStep` → panel) stays as a best-effort enhancement; the **settings** call site (`SiteSettingsBody`, below the `if (!site)` guard) is the one that reliably supplies a real value. Server honors explicit booleans only and never infers. Both server branches integration-tested; a frontend assertion covers the known-empty, non-empty AND unknown/undefined cases. |
| R8 | Alembic run hits Supabase PROD | CRITICAL | Step 1.1 pins `DATABASE_URL=localhost:5433` in the command environment; bare alembic is FORBIDDEN |
| R9 | Migration chained off a stale head (concurrent programs move it) | MED | Step 1.1 derives the head LIVE and records it in the report |
| R10 | A "green" mock-mode gate that silently made a live outbound request | HIGH | **F4 fix:** mock short-circuit is the FIRST statement of `run_site_analysis`, AND `fetch_site_content` carries its own mock branch; step 1.14/1.15 gates assert **zero outbound requests** under mock (fetch not called / no-mock transport guard) |
| R11 | **(NEW — cycle 2, F5/V2)** Budget check→increment is not atomic: two simultaneous runs can both read `used = limit - 1` and both proceed, over-spending by one. | LOW — **ACCEPTED** | Deliberate. This is a best-effort free-tier guard on a system key (3/day/site), **not a billing meter**; the same non-atomic shape is what every existing meter in `usage_limits.py` uses. D12's in-flight guard removes the realistic double-click path. An `INCR`-then-compare rewrite would diverge from the repo's meter idiom for a bounded 1-run overspend — not worth it here. Recorded so a later reader does not mistake it for an oversight. |
| R13 | **(NEW — cycle 5, C21)** `message` misattributes the cause when a run fails for a **non-budget** reason (fetch/Gemini error) while the daily counter happens to be exhausted: the C21 precedence keys the cap copy on `allowed == false` alone, so the user is told "Daily analysis limit reached" for a failure the cap did not cause. | LOW — **ACCEPTED (named residual)** | Deliberate and unfixable without persisting a failure reason — the **sixth column D15 explicitly avoids** (a stored message re-introduces the staleness VF1 removed). The alternative precedence (status first) is strictly worse: it leaves the `POST` capped response and the disabled Analyze button on a `none`/`ready` row with **no copy at all** — the C21 defect. Recorded so a later reader does not mistake it for an oversight; do NOT "fix" it during EXECUTE. |
| R12 | **(NEW — cycle 2, V5)** The panel unmounts before results arrive because the pixel verified first, so the entire review/confirm flow silently never happens. | HIGH | Panel mounted on BOTH the `install` and `done` steps (`onboarding-flow.tsx:367-369`); the AC-7 gate is rebuilt as an honest end-to-end integration leg (create → analysis ready under mock → `PUT` confirm → segmenter prompt carries the values) instead of a pre-confirmed fixture that could not observe the break. |

---

## Coordination — canary phases 2-4

`canary-onboarding_10-08-26` Phase 1 (backend) shipped; its phases 2-4 own the React wizard, and
`install-step.tsx` / `onboarding-flow.tsx` already exist on disk in their rebuilt form.

**Named re-insertion point (state this verbatim in any canary phase 2-4 handoff):**
> In `apps/web/src/components/onboarding/steps/install-step.tsx`, `<SiteAnalysisPanel siteId={siteId}
> variant="onboarding" currentDescription={currentDescription} />` renders **inside
> `<div className="ob-bubble plain wide">`, immediately AFTER the `detecting` ternary block** — i.e.
> as the last child of that div, sibling to the ternary, not inside either of its branches.
> (Restated per C9: the earlier wording said "after `<PixelInstallGuide>` … OUTSIDE the ternary",
> which is self-contradictory — `PixelInstallGuide` is the ternary's else-branch at `:53-60`;
> `CrossTenantDisclosure` at `:39` is the element outside it.) If that file is rewritten, re-insert
> at the same position. **A SECOND mount is mandatory (V5):** the same panel also renders on the
> `done` step, inside `onboarding-flow.tsx`'s `{queue.done && state.step === "done" && (…)}` block
> (`:367-369`), beside `<DoneStep …>`. `VERIFIED` unmounts `InstallStep`, so without the second
> mount a fast pixel verification destroys the results surface before a ~120 s analysis lands.
> The panel takes one required prop (`siteId`), one variant string, and one
> optional `currentDescription` (which it treats fail-safe when absent, D13); it owns all of its own
> fetching and state, so it survives any restructure of the surrounding wizard.

The panel deliberately does **not** enter the `flowReducer` state machine (`lib/onboarding-flow.ts`)
— no new `StepId`, no new `FlowEvent`, no persisted flow field. That keeps this feature's blast
radius out of the canary program's reducer test surface (`onboarding-flow.test.ts`).

---

## Implementation Checklist

### Block 1 — Backend (migration → service → endpoints → budget), mock-first

1. **1.1 — Derive the alembic head LIVE and write the migration.**
   Run, with `DATABASE_URL` pinned (bare alembic hits Supabase PROD — repo standing rule C-9):
   ```bash
   DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5433/postgres' \
     .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads
   ```
   Record the printed head in the phase report. Create
   `apps/api/migrations/versions/<rev>_add_site_profile.py` with `down_revision = "<that head>"`,
   adding to `sites` **five** columns: `site_profile` (`JSONB`, nullable — the CONFIRMED profile),
   **`site_profile_candidate` (`JSONB`, nullable — the un-reviewed run awaiting confirm; V1 option
   (a))**, `site_profile_status` (`String(20)`, nullable), `site_profile_started_at` (`DateTime`,
   nullable), `site_profile_analyzed_at` (`DateTime`, nullable). All additive + nullable;
   `downgrade()` drops all five. No index on either JSONB column (never queried by content).
2. **1.2 — Live round-trip the migration** on the local dev DB only:
   ```bash
   DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5433/postgres' \
     .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head
   DATABASE_URL='...localhost:5433...' .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini downgrade -1
   DATABASE_URL='...localhost:5433...' .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head
   ```
   (Docker IS available on this machine — detect via `lsof -nP -iTCP -sTCP:LISTEN | grep 5433`; the
   CLI is at `/Applications/Docker.app/Contents/Resources/bin/docker`, off `PATH`.)
3. **1.3 — Add the 5 columns to `apps/api/models/site.py`** (including `site_profile_candidate`) with the same comment discipline as the
   surrounding columns (state what NULL means and that all **five** are flag-gated — C19/N10).
4. **1.4 — Add settings to `apps/api/config.py`** in a new `# ─── Site analysis (onboarding) ───`
   block: `site_analysis_enabled: bool = False`, `site_analysis_daily_budget: int = 3`,
   `site_analysis_stale_seconds: int = 180`, `site_analysis_fetch_timeout_seconds: int = 10`.
   Inline comments, both mandatory: (a) flipping `site_analysis_enabled` in a real environment is a
   separate operator action after the migration is live; (b) **`site_analysis_stale_seconds` (180 s)
   must stay BELOW the panel's poll cap (60 polls × 4 s = 240 s, step 3.3) and ABOVE the ~120 s
   worst-case grounded latency — see D2/C14. Changing one without the other is a regression (E13).**
5. **1.5 — Create `apps/api/services/site_content.py`.** One public function
   `async def fetch_site_content(url: str) -> SiteContent` (TypedDict: `ok`, `html`, `headers`,
   `status_code`, `title`, `meta_description`, `text`). It performs the URL normalization,
   `await is_safe_public_url(url)` pre-check, and `safe_get(client, url)` on the pinned client with
   `follow_redirects=False`, `timeout=settings.site_analysis_fetch_timeout_seconds`, and the existing
   `BROWSER_HEADERS` — **imported read-only as `from apps.api.services.platform_detector import
   BROWSER_HEADERS`** (C12/N3). That constant is defined only at `platform_detector.py:18`;
   `pixel_verifier.py:24` defines a *different* constant (`BROWSER_UA`). An import does not modify the
   file, so the `git diff --stat apps/api/services/platform_detector.py` gate stays empty — but
   **editing that module remains forbidden (E11)**. The coupling is deliberate and named here so an
   execute-agent does not "helpfully" relocate the constant and trip its own gate. **First statement of the function: `if settings.mock_external_apis:` return a
   deterministic fixture `SiteContent` — no network at all (mirror `content_reader.py:262,356,744`)**
   (F4, defence in depth).    **Body cap, real posture (C11):** `safe_get` fully buffers the response before returning, so
   implement (a) a `Content-Length` **pre-check** — refuse > 512 KB with `ok=False` before reading —
   and (b) **post-hoc truncation** of `resp.text`. Record in a code comment that a chunked response
   with no `Content-Length` is still buffered in full (accepted residual: authed, 3 runs/day/site,
   10 s timeout). Do **not** claim a streaming cap that this call path cannot deliver.
   Text extraction: strip `<script>`/`<style>`/comments,
   drop tags, collapse whitespace, truncate to 12 000 chars. **Pure-stdlib regex extraction — do not
   add a new dependency.** Never raises: failures return `ok=False`.
6. **1.6 — REMOVED (PVL cycle 1, F1 option (a)). Do NOT refactor `platform_detector.py`.**
   The earlier draft had `detect_platform` delegate its fetch to `fetch_site_content`. That is
   deleted from scope: the two modules genuinely have different postures today (bare client at
   `platform_detector.py:174,223` vs the DNS-pinned client this plan mandates), so delegation would
   be a real, untested behavior change breaking AC-9's byte-identical guarantee — against a module
   with **zero** behavioral test coverage (the `-k platform` "gate" collects 4 tests, only one of
   which touches `detect_platform`; C1). **Execute-agent gate: `git diff --stat
   apps/api/services/platform_detector.py apps/api/schemas/sites.py` must be EMPTY.** The pre-existing
   coverage gap and `_probe_shopify_api`'s bare-client posture are recorded in
   `platform-detector-uncovered_NOTE_13-08-26.md`, not fixed here.
7. **1.7 — Add the budget block to `apps/api/services/usage_limits.py`**, copying the OSINT block
   (`usage_limits.py:163-201`) verbatim in shape: `_site_analysis_count_key(site_id)` →
   `f"site_analysis:count:{site_id}:{YYYYMMDD}"`, `get_site_analysis_usage` (fail-open to 0),
   `increment_site_analysis_usage` (2-day TTL on first incr),
   **`check_site_analysis_budget(site_id)` — that signature exactly (N12)**: no `db`, no `user_id`.
   D14 removed the only consumers of those two parameters (`is_full_byok` needs a DB session and a
   user id); carrying them forward would be dead params that re-invite a BYOK exemption and a
   per-poll DB round-trip. It returns the `_budget_result` dict, of which the API projects
   **exactly three fields — `used`, `limit`, `allowed`** — into `SiteAnalysisOut.budget`;
   `is_byok` is dropped at the projection boundary (N12/V10), not merely unread. **NOT BYOK-exempt (D14/V7):** call
   `_budget_result(used, settings.site_analysis_daily_budget, byok=False)` — i.e. the cap applies
   unconditionally, because the analysis burns the SYSTEM Gemini key. The posture precedent is the
   **paid-OSINT** block immediately below the OSINT one in the same file, whose comment states it
   verbatim: "NOT BYOK-exempt: the paid key is a SYSTEM key (operator pays), so the cap always
   applies." Copying `check_osint_budget`'s BYOK-uncapped shape would hand any BYOK user unlimited
   grounded runs on the operator's key. Do **not** call `is_full_byok` here at all — that also keeps
   `GET .../analysis` free of a per-poll DB round-trip (N5).
   **One increment per analysis run, never per Gemini call, and never in more than one layer (D11).**
8. **1.8 — Create `apps/api/schemas/site_analysis.py`** with `SiteProfile`, `SiteAnalysisOut`,
   `SiteAnalysisConfirm` exactly matching §Public Contracts, including list-length and string-length
   caps as Pydantic constraints. Explicitly:
   - `SiteProfile.meta` carries **`v: int = 1`** (V8) — the JSONB schema version, written on every
     persisted profile (candidate and confirmed) and by `mock_profile`.
   - `SiteAnalysisOut` carries **`candidate: SiteProfile | None = None`**,
     **`message: str | None = None`** (V10 — **response-only, derived at read time; there is no
     `message` column and nothing persists it**, VF1) and **`already_running: bool = False`** (V4).
   - `SiteAnalysisConfirm` carries **`promote: bool = True`** (VC9). `promote=False` means
     dismiss-only: NULL the candidate, touch nothing else.
   - `SiteAnalysisOut.budget` **omits `is_byok`** — the meter is not BYOK-exempt (D14), so the field
     would be a permanently-false invitation to re-introduce an exemption.
   - `SiteAnalysisConfirm.apply_description` defaults **`False`** (D13 fail-safe, VC7 case table);
     `apply_category` defaults `True`.
9. **1.9 — Create `apps/api/services/site_analysis.py`.** Public surface:
   - `def derive_status(site, now) -> str` — pure; implements D2 (`pending` + `started_at` older than
     `site_analysis_stale_seconds` ⇒ `"failed"`). Unit-testable with zero I/O.
   - `def build_research_prompt(content: SiteContent) -> str` — per-field `clean_text` +
     `wrap_untrusted` on title/meta/text (D-note: `sanitize_profiles` is NOT usable here).
   - `def build_structuring_prompt(prose: str) -> str` — `clean_text` + `wrap_untrusted` the prose.
   - `def sanitize_profile(raw: dict) -> dict` — per-field `clean_text` on every string, enforce caps
     and list lengths, drop unknown keys, stamp `meta.v = 1` (V8), and **hostname-validate
     `competitors[].domain` with a POSITIVE check (V6, tightened VC8)** — keep it only if
     `urlsplit(domain).scheme in {"", "http", "https"}` **AND** the derived host matches a plain
     hostname regex (no port, path, userinfo or whitespace); otherwise set it to `None`. **Do not
     use `strip_url` as the validator** — it returns its input unchanged when there is no `netloc`,
     so `javascript:alert(1)` passes it.
     Never let an unvalidated model-chosen string reach the UI as a URL.
   - `def mock_profile(site) -> dict` — deterministic fixture used when `settings.mock_external_apis`.
   - `async def analyze_site(site) -> dict` — mock short-circuit; else call 1
     `gemini_generate(build_research_prompt(...), grounding=True, max_output_tokens=2048)`, call 2
     `gemini_generate_json(build_structuring_prompt(prose))` (grounding defaulted OFF), then
     `sanitize_profile`.
   - `async def run_site_analysis(site_id: str) -> None` — the background entrypoint. Opens **its own
     session**: `async with async_session() as db:` (`from apps.api.models.database import
     async_session`; symbol at `models/database.py:78`, pattern at `events.py:946`) — **never
     `async_session_maker`, which does not exist** (C4). Order of operations (F4 + cycle-2 fixes):
     **(1) `if settings.mock_external_apis:` → persist `mock_profile(site)` into
     `site_profile_candidate` + `status="ready"` and RETURN — before the budget check and before any
     fetch**; (2) re-load the site; (3) **the single authoritative budget check + increment — this is
     the ONLY increment in the system (D11/F5); the POST endpoint checked but did not increment.
     On DENY: set `status="failed"`, commit, and RETURN immediately (C15) — and write **no message
     string**: `message` is derived at read time (VF1), so the deny branch persists status only.
     Never leave the row `pending` for the full 180 s stale window, which would surface a budget
     denial as a mysterious late failure**;
     (4) fetch; (5) `analyze_site`; (6) **persist the profile into `site_profile_candidate` (NOT
     `site_profile` — only `PUT` writes the confirmed slot, V1)** + `status="ready"` +
     `analyzed_at`; (7) **nothing** — the
     in-flight discard is NOT done here (VC6). On any exception set `status="failed"` and commit.
     **Module-level container (VC6): `_analysis_inflight: set[str] = set()` is declared in THIS
     module**, mirroring `events.py:75`, and is imported read/write by the router. It is discarded
     from **only** in the `add_done_callback` registered by the router's fire helper (1.10) —
     mirroring `events.py:560-567` exactly — because a done-callback fires on every outcome
     including cancellation, whereas a coroutine `finally` never runs if the task is cancelled
     before it starts. Logs `site_analysis_started` / `_complete` / `_failed` with
     `site_id`, `chars`, `duration_ms`, `error_class` **only**.
     **Mock-mode counter behavior, stated deliberately (F5):** the mock short-circuit returns at step
     (1), i.e. **before** the task's increment, so under `mock_external_apis=True` a run increments
     **zero** times. That is intentional (mock must burn no budget) and it is exactly why the
     whole-cycle counter gate in 1.15 must run with `mock_external_apis=False` and the Gemini/fetch
     calls patched — see 1.15's `test_budget_counter_delta_is_one_per_post_cycle`.
10. **1.10 — Wire the fire-and-forget task in `apps/api/routers/sites.py`.** Add a module-level
    `_analysis_tasks: set[asyncio.Task] = set()`. Add a helper
    `def _fire_site_analysis(site: Site) -> None` that creates the task and registers the
    `add_done_callback(_analysis_tasks.discard)` — exact shape of `events.py:558-570`. Call it inside
    `create_site` **after `await db.refresh(site)` and before the `return SiteOut.model_validate(site)`**
    (anchor text — currently `sites.py:187` and `:191`; match on the anchor, not the number, C8), guarded by `if settings.site_analysis_enabled:` and preceded by setting
    `status="pending"` + `started_at=now` + commit. The dedup-return and 409 branches must NOT fire it.
    **`create_site` does NO budget work at all** (D11) — the task owns check+increment.
    **In-flight guard wiring (VC6 — corrected placement):** the container is
    `site_analysis._analysis_inflight` (declared in `apps/api/services/site_analysis.py`, 1.9), NOT
    in this router. **(Rationale corrected, N13:** the old "a router-side set would force
    `services → routers`" argument no longer holds — the service never discards, the router's
    done-callback does, so a router-side set would create no cycle. The service-side placement
    stands because the set is analysis-domain state owned by the service, co-located with
    `run_site_analysis`.**)** `_fire_site_analysis` adds the
    `site_id` **before** creating the task and registers **one** `add_done_callback` that does both
    `_analysis_tasks.discard(task)` and `_analysis_inflight.discard(site_id)` — the exact
    `events.py:560-567` shape. **The discard must live in the done-callback, never in a `finally`
    inside the coroutine**: the callback fires on every outcome including cancellation, a `finally`
    does not run if the task is cancelled before it starts (a permanently-stuck guard).
11. **1.11 — Add the three endpoints to `apps/api/routers/sites.py`** per §Public Contracts. Order of
    checks in every handler: flag → `verify_site_access` → logic. Place them after
    `detect_platform_endpoint` and before `verify_pixel_endpoint`. The flag check is the first
    statement **inside** the handler body (`return 404`), following the `routers/onboarding.py:53-56`
    `_require_flag()` precedent — **not** a `Depends`, which resolves after auth and cannot run
    first (N1). Accepted consequence, matching repo posture everywhere else: an *unauthenticated*
    probe gets 401 from `get_current_user` before ever reaching the flag check, so flag-off hides the
    endpoint from authenticated users but not from an unauthenticated 401-vs-404 oracle.
    `POST` specifics: **(a0)** on allow, fire **via `_fire_site_analysis` (1.10)** — the same helper
    `create_site` uses — **never a bare `asyncio.create_task`**; it is the sole registrar of the
    done-callback that discards from `_analysis_inflight` and `_analysis_tasks` (C23); **(a)**
    in-flight guard FIRST — derived status `pending` (or `site_id in
    _analysis_inflight`) ⇒ return current state + `already_running=True`, no increment, no
    `started_at` re-stamp, no task (D12/V4); **(b)** budget **check only**, never increment (D11);
    **(c)** never touch `site_profile`. `PUT` specifics (C18/VC4 + VC9): body carries `promote: bool = True`. When `promote` is
    **true**, write the sanitized profile into `site_profile` and NULL the candidate (V1); when
    **false**, NULL the candidate and touch nothing else (dismiss). **Status handling is
    conditional in both cases:** if the derived status is `pending`, leave `site_profile_status`
    and `site_profile_started_at` **untouched** (never downgrade an in-flight run — that would
    erase the state D2's stale derivation and D12's cross-process check both read); otherwise set
    `site_profile_status="ready"`. **`PUT` never stamps `site_profile_analyzed_at`** — that field
    means "when the analysis run that produced the candidate finished" and has exactly one writer,
    the task (C18). A `PUT` with `site_profile_candidate = NULL` (or `status="none"`) is **allowed
    and normal** — it is the edit-the-confirmed-profile path. `GET` specifics: return `candidate` and `profile` as
    separate fields; compute `budget` from a single Redis GET with no `is_full_byok`/DB lookup (N5).
12. **1.12 — REMOVED (PVL cycle 1, F1 option (a)).** No fields are added to `PlatformDetectResponse`
    and `detect_platform_endpoint` is not modified. This also closes C2 (the field-name
    contradiction) and C3 (`PlatformResult` carries no text field and is not extended) by deletion.
13. **1.13 — Write `tests/unit/test_site_content.py`**: extraction correctness on a fixture HTML;
    script/style stripping; truncation cap; `ok=False` on non-HTML, on timeout, on 5xx; **SSRF
    posture test** asserting `fetch_site_content("http://169.254.169.254/")` and
    `http://localhost:8000/` return `ok=False` without any outbound request; adversarial-HTML fixture
    (`ignore previous instructions…`, a forged `</untrusted_visitor_data>` closing fence) asserting
    the fence survives (AC-12). **Placement (C6):** the SSRF-posture test goes in the EXISTING
    `tests/unit/test_ssrf_guard.py` as `test_fetch_site_content_refuses_metadata_without_fetch`,
    beside its two siblings (`test_detect_platform_refuses_metadata_without_fetch`,
    `test_verify_pixel_refuses_metadata_without_fetch`). Extraction and adversarial-HTML tests stay
    in the new `tests/unit/test_site_content.py`.
14. **1.14 — Write `tests/unit/test_site_analysis.py`**: `derive_status` truth table (none/pending/
    stale-pending/ready/failed); prompt builders fence every field; `sanitize_profile` caps and drops;
    mock-mode determinism (two calls, identical output, zero Gemini calls **and zero outbound HTTP —
    assert `fetch_site_content`'s network path is never entered, e.g. patch the transport to raise on
    any request**, F4/R10); call 2 invoked with
    `grounding` not set/False (R4); **`test_budget_incremented_once_per_run` — MUST run with `mock_external_apis=False`
   (C20)**, patching the same **consumer bindings** named in 1.15
   (`apps.api.services.site_analysis.fetch_site_content`, `.gemini_generate`,
   `.gemini_generate_json`) with the same raise-on-any-outbound transport guard (E12/E15). Under
   mock the short-circuit returns at 1.9 step (1), *before* the increment, so a mock-mode version
   of this assertion observes **zero** increments and is vacuous by exactly the F5 mechanism.
   Assert the run reached terminal `ready` alongside the single increment; log capture asserts
    no prompt/body/profile text in any emitted event (AC-13). **Added in cycle 2:**
    `test_sanitize_profile_nulls_invalid_competitor_domain` (a `javascript:` / free-text /
    space-bearing domain becomes `None`; a plain hostname survives — V6);
    `test_sanitize_profile_stamps_schema_version` (`meta.v == 1` on every path incl. `mock_profile`,
    V8); `test_budget_denied_run_sets_terminal_failed_with_message` — **re-pointed at the DERIVED
    behavior (VF1)**: assert the task's deny branch sets `status="failed"`, commits, returns
    immediately (row is NOT left `pending`, C15) **and persists no message string anywhere**; then
    assert the read-time derivation produces the cap copy for that row while the budget counter is
    still exhausted, and the generic copy once it is not. The row must never be asserted to *hold*
    a message — there is no column for one;
    `test_task_writes_candidate_never_confirmed_profile` (assert `site_profile` is untouched and
    `site_profile_candidate` holds the run — V1).
15. **1.15 — Write `tests/integration/test_site_analysis_api.py`** (real PG + Redis). **Mock mode
    must be set explicitly** — `tests/conftest.py` pins `DATABASE_URL`/`REDIS_URL`/`GEMINI_API_KEY`
    but NOT `MOCK_EXTERNAL_APIS` (`config.py:1021` default `False`), so use the repo pattern
    `monkeypatch.setattr(settings, "mock_external_apis", True)` (precedent
    `tests/integration/test_ads_flag.py:46`) in a module-level autouse fixture (C5).
    **Per-test override (N15) — required for the two mock-OFF gates in this same module:** the
    autouse fixture sets `mock_external_apis=True` for every test here, so
    `test_budget_counter_delta_is_one_per_post_cycle` and any other mock-OFF gate must re-apply
    `monkeypatch.setattr(settings, "mock_external_apis", False)` **inside the test body**. That is
    mechanically sound — a function-scoped `monkeypatch` applied in the body runs after the autouse
    fixture and wins — but it must be written explicitly: omitting it silently re-mocks the run and
    makes both gates vacuous by exactly the F5/C20 mechanism. Per E20, assert
    `settings.mock_external_apis is False` as the **first statement** of each such test. Cases: flag-OFF ⇒ all three endpoints 404 **and** `create_site` writes no
    profile columns; foreign `site_id` ⇒ 404 (never 403); full lifecycle create → GET pending →
    (await task) → GET ready with persisted profile; forced-failure path ⇒ `failed`; backdated
    `started_at` ⇒ derived `failed` (R6); `PUT` with edited fields ⇒ edited values persisted, AI
    values gone (AC-5); `PUT` AC-6 both branches (`apply_description` true on empty description ⇒
    filled; false with user-typed description ⇒ preserved); `POST` re-run lifecycle with prior
    profile intact until confirm (AC-8 — assert the CONFIRMED `sites.site_profile` is byte-identical
    before and after the re-run while `site_profile_candidate` holds the new output, and that `PUT`
    then promotes it and NULLs the candidate); `POST` 4th call same day ⇒ `budget.allowed=false`,
    HTTP 200, profile unchanged, zero additional analysis runs (AC-10). **Added in cycle 2:**
    - `test_budget_counter_delta_is_one_per_post_cycle` (F5, the gate both old AC-10 tests were blind
      to): read the raw Redis key `site_analysis:count:{site_id}:{YYYYMMDD}` before and after a
      **full `POST` → task completion** cycle and assert the delta is **exactly 1**. This case must
      run with `mock_external_apis=False`, because mock short-circuits before the task's increment
      and would make the assertion vacuous — the precise blindness F5 identified. **Five mandatory
      hardenings (C17 + VF2) — the gate is not accepted without all five:**
      **(a) Patch the CONSUMER bindings, named exactly:**
      `monkeypatch.setattr("apps.api.services.site_analysis.fetch_site_content", …)`,
      `…site_analysis.gemini_generate`, `…site_analysis.gemini_generate_json`. `site_analysis.py`
      imports these with `from … import name`, so **patching the defining module
      (`site_content` / `gemini_client`) has no effect** — the classic mis-patch, and the one that
      would let this gate pass while issuing a real outbound request (E15).
      **(b) Transport-level backstop, mandatory for THIS gate too:** patch the httpx transport to
      **raise on any outbound request** other than the explicitly patched call sites. E12's
      raise-on-any-request rule was scoped to the mock-mode gates; **VF2 extends it here**, because
      the increment happens at 1.9 step (3) *before* the fetch, so without the backstop a
      mis-patched fetch hits the network and the delta assertion still passes.
      **(c) Open the delta window AFTER the create-time auto-fired task has settled.** `create_site`
      fires its own analysis task when the flag is ON; a window opened at create time measures two
      runs and can never read 1. Create the site, await the auto-fired task to completion, THEN
      read the "before" counter value, THEN issue the `POST`.
      **(d) Await via the named handle:** `await asyncio.gather(*site_analysis_tasks)` where
      `site_analysis_tasks` is the router's module-level **`_analysis_tasks`** set declared in 1.10
      (`from apps.api.routers.sites import _analysis_tasks`; copy the set before gathering, since
      the done-callback mutates it). There is no other supported way to know a fire-and-forget task
      finished — do not sleep.
      **(e) Assert the run reached terminal `ready`**, not just `delta == 1`. A mis-patch that
      leaves the row `failed` must fail loudly instead of passing on the arithmetic alone.
    - `test_concurrent_post_while_pending_returns_already_running` (V4, **+ C23 post-settle leg**):
      a second `POST` while the row is `pending` returns HTTP 200 with `already_running=true`, does
      **not** change `site_profile_started_at`, does **not** increment the counter, and fires no
      second task. **Then, in the same test (C23):** await the POST-fired run to completion (via
      `asyncio.gather` over a copy of the router's `_analysis_tasks`, as in (d) above) and assert a
      further `POST` is **accepted** — `already_running` is `false`. This is the only gate that
      proves the done-callback discard actually ran, i.e. that the fire path went through
      `_fire_site_analysis` and not a bare `asyncio.create_task`.
    - `test_budget_denied_run_does_not_linger_pending` (C15, **re-pointed at the derived behavior,
      VF1**): with the counter pre-exhausted, an allowed-by-race task run terminates as `failed`
      immediately rather than after the stale window, **and the subsequent `GET` RETURNS the cap
      message** ("Daily analysis limit reached — try again tomorrow"). Assert the message on the
      **GET response**, never on the DB row — nothing persists it.
    - `test_put_promote_false_dismisses_candidate_only` (VC9): a `PUT` with `promote=false` NULLs
      `site_profile_candidate` and leaves `site_profile`, `site_profile_status`,
      `site_profile_started_at`, `site_profile_analyzed_at`, `Site.description` and `Site.category`
      byte-identical.
    - `test_put_during_pending_preserves_pending_status` (C18/VC4): a `PUT` issued while the derived
      status is `pending` writes `site_profile`, NULLs the candidate, and leaves
      `site_profile_status="pending"` + `site_profile_started_at` untouched, so a later backdated
      read still derives `failed` and a concurrent `POST` still returns `already_running`.
    - `test_put_with_no_candidate_is_allowed` (C18/VC4): a `PUT` on a site with
      `site_profile_candidate = NULL` (and `status="none"`) succeeds and persists the user-authored
      profile.
    - `test_get_returns_candidate_and_confirmed_separately` (V1): both fields present and distinct.
    - `test_message_derivation_truth_table` (**C25 — added in cycle 6; the gate that can fail on the
      defect C21 named**). Every other message assertion in this plan sits on a `failed` row, so an
      implementation using the pre-C21 status-switch reading (`failed` ⇒ cap copy, else `null`) would
      ship a capped `POST` with `message: null` and a disabled Analyze button with no copy — and pass
      every gate. **Purpose of this gate: it MUST fail against a pre-C21 status-switch implementation.**
      Assert all four `(allowed, derived-status)` cells of the E17/C21 precedence rule:
      **(i)** `allowed=false` + `ready` (and the same for a `none` row) ⇒ the cap copy
      "Daily analysis limit reached — try again tomorrow" on the `GET` **and** on the `POST` capped
      response body (this is the cell no existing gate covers — it is the whole point of the case);
      **(ii)** `allowed=false` + `failed` ⇒ cap copy;
      **(iii)** `allowed=true` + `failed` ⇒ the generic failure copy;
      **(iv)** `allowed=true` + `ready` ⇒ `message` is `null`.
      Drive `allowed` by pre-setting the raw Redis counter key (exhausted vs fresh) and drive the
      status by writing the `sites` row directly; assert the message on the **response**, never on the
      DB row — nothing persists it (VF1). Extending
      `test_budget_exhaustion_returns_capped_response_no_extra_runs` with cell (i) instead of writing
      the standalone case is acceptable only if all four cells end up asserted; do not write two
      overlapping gates (E21).

**Block 1 test gate (run before Block 2):**
```bash
.venv/bin/python3.11 -m pytest tests/unit/test_site_content.py tests/unit/test_site_analysis.py tests/unit/test_ssrf_guard.py -m unit -q
.venv/bin/python3.11 -m pytest tests/integration/test_site_analysis_api.py -q
.venv/bin/python3.11 -m pytest tests/unit -m unit -q      # zero NEW failures vs the EXECUTE-start baseline
git diff --stat apps/api/services/platform_detector.py apps/api/schemas/sites.py   # MUST be empty
```

### Block 2 — Segmenter pre-seed verification (no production code change)

16. **2.1 — Verify, do not modify.** Confirm `apps/api/agents/segmenter.py:21-23` (anchor text, not line number — C8) still interpolates
    `{site_description}` and `{site_category}` and that its call site passes `Site.description` /
    `Site.category`. If either is NOT wired at the call site, that is a **finding to report** — fix
    it in this block only if the fix is a one-line argument pass; anything larger becomes a backlog
    note, not scope creep.
17. **2.2 — Write the AC-7 coverage in TWO layers (V5).** The pre-confirmed-fixture test alone is
    not an honest AC-7 gate: it starts from a `Site` that already has a description/category, so it
    is structurally incapable of noticing that the panel unmounted and the user never got to confirm.
    - **(a) Unit complement** — `tests/unit/test_site_analysis_segmenter_preseed.py`: build a `Site`
      fixture with a confirmed description + category, assemble the segmentation prompt, assert both
      slots are non-empty and carry the exact fixture values. Proves the interpolation only.
    - **(b) End-to-end integration leg (the real AC-7 gate)** —
      `tests/integration/test_site_analysis_api.py::test_confirmed_profile_reaches_segmenter_prompt`:
      create a site with an EMPTY description → let the analysis complete under mock → `PUT` confirm
      with `apply_description=true` / `apply_category=true` → re-read the `Site` row → assemble the
      segmentation prompt from it and assert it carries the confirmed values. This traverses
      create → candidate → confirm → promote → segmenter, so a broken link anywhere in the chain
      fails the gate.

**Block 2 test gate:**
```bash
.venv/bin/python3.11 -m pytest tests/unit/test_site_analysis_segmenter_preseed.py -m unit -q
.venv/bin/python3.11 -m pytest tests/integration/test_site_analysis_api.py::test_confirmed_profile_reaches_segmenter_prompt -q
```

### Block 3 — Frontend panel + insertion points

18. **3.1 — Add types to `apps/web/src/lib/api-types.ts`**: `SiteProfile`, `SiteAnalysis`
    (mirroring §Public Contracts). Do **not** change the `Site` interface.
19. **3.2 — Add three methods to `apps/web/src/lib/api.ts`**: `getSiteAnalysis(siteId)`,
    `confirmSiteAnalysis(siteId, body)`, `rerunSiteAnalysis(siteId)` — following the existing method
    shape near `detectPlatform` (`api.ts:851`).
20. **3.3 — Create `apps/web/src/components/site-analysis-panel.tsx`.** Props:
    `{ siteId: string; variant: "onboarding" | "settings"; currentDescription?: string | null }`.
    `currentDescription` is supplied by both call sites (3.4 / 3.5) but is **explicitly allowed to be
    `undefined` at runtime** — see the fail-safe rule below. The F3 defect was the prop being
    undefined-by-construction *while the default was `true`*; D13 removes the dependency instead of
    pretending the value is always present.
    Internals: a `useEffect` poll at 4 s, cleared on `ready`/`failed`/unmount, hard-capped at
    **60 polls (≈240 s)** — deliberately longer than `site_analysis_stale_seconds` (180 s) so a dead
    run resolves to `failed` on screen while the panel is still polling (D2/C14; if either constant
    moves, move both — E13). A 404 response (flag OFF) renders **nothing at all** (return `null`),
    the poll is **not** retried, and no error surfaces — the component is inert when the feature is
    off. **Honest scope note (N2):** flag-off is byte-identical on the BACKEND; on the web the panel
    still issues exactly one `GET` that 404s and then renders nothing. Step 3.7/WEB gate asserts that
    one-shot-then-silent behavior rather than claiming zero requests.
    **Slot emptiness is evaluated BEFORE the status switch (C22) — this is the outermost branch:**
    if **both** `profile` and `candidate` are null, render the **`none`** presentation (empty-state
    copy + budget-gated Analyze button) **whatever `status` says**, and stop. `status="ready"` with
    both slots empty is genuinely reachable — a `PUT` with `promote:false` dismissing a *first-ever*
    candidate NULLs the only populated slot while D16 leaves `site_profile_status` untouched — and
    without this ordering that row falls through to the `ready` branch and renders editable controls
    over absent data. Ordering emptiness first also makes `none` correct for **every** row shape
    rather than only for pre-flag-flip rows.
    **Render rule (VC5), evaluated next and BEFORE the status switch:** the review/edit UI is shown
    whenever `(candidate ?? profile)` is non-null, **regardless of `status`**; a `failed` status
    renders as a **banner ABOVE** that UI, never *instead* of it. A failed re-run must never hide an
    already-confirmed profile behind an error screen.
    **Ownership (C22b) — the review/edit UI is owned by the render rule ALONE.** It is implemented
    **once**, driven by `(candidate ?? profile)`, and the status branches below **never** render it.
    The status branches contribute **only** a strip ABOVE it: a banner (`failed`), a quiet indicator
    (`pending`), or the empty-state copy (`none`). The `ready` branch's "editable controls" listed
    below describe **the content of that single render-rule UI**, not a second copy of it — do not
    render it once per branch, and do not omit it on composite states (e.g. `failed` with a
    confirmed profile still present).
    States (four — `none` is NEW, VF3 — each is the strip ABOVE the render-rule UI, never a
    replacement for it):
    - **`none`** (**both slots empty — see the emptiness-before-status rule above; `status` is not
      consulted**) → "Beam hasn't analyzed this site yet." plus an **Analyze** button that issues
      the same `POST .../analysis`, **disabled when `budget.allowed === false`**. When disabled,
      show the server's `message` verbatim — this is well-defined for the `none` state because the
      derivation is a precedence on `allowed`, not a switch on `status` (C21): `allowed === false`
      always yields the cap copy. Never synthesize cap copy client-side; if `message` is `null` the
      button is not disabled. **Without this state AC-8
      is unreachable for every pre-existing site** — such rows have `site_profile_status = NULL`
      and would render nothing, while the re-run button lived only on the `failed` branch (VF3).
      This is the entry point for the whole feature on any site created before the flag flip.
    - `pending` → "Analyzing your site…" with a quiet indicator, never blocking. (If a profile or
      candidate exists, it still renders below per the render rule.)
    - `failed` → banner showing the server's `message` verbatim — the generic copy
      "We couldn't analyze your site — you can add details yourself." when `allowed === true`, or
      the cap copy when `allowed === false` (C21 precedence rule 1 outranks rule 2; the panel never
      chooses between them) — plus a re-run button (disabled when `budget.allowed === false`).
      **Banner only — never a replacement for the review UI (VC5/C22).**
    - `ready` → an "AI-generated — please review" label over the render-rule UI (the label is the
      status branch's only contribution; the controls below are that one UI's content, not a second
      instance) — editable controls for summary, sells,
      category, sub-industry, ICP personas/firmographics, competitors; a Confirm button, and — when
      a `candidate` is present alongside a confirmed `profile` — a **"Keep current" action that
      issues `PUT` with `promote: false`** (dismiss the re-run, change nothing else; VC9).
    **Confirm — fail-safe `apply_description` (D13/V3), the rule that replaces the old default:**
    - `currentDescription` **known non-empty** → present the keep/replace choice; default **keep**
      (`apply_description=false`).
    - `currentDescription` **absent / `undefined` / unknown** (the routine case after a reload or
      resume — `PersistedFlow` carries no description field, so the F3 `useState` value is gone) →
      send `apply_description=false`. **Never `true` on unknown.** Show the same keep/replace choice
      so the user can still opt in explicitly.
    - `currentDescription` **known-empty — `null` OR `""`** → `apply_description=true` is
      permitted (VC7). **`null` counts as known-empty**, not unknown: it is the *server-asserted*
      value of `Site.description` (`string | null`, `api-types.ts:156`), which is exactly what the
      settings call site passes. Treating `null` as unknown would make auto-fill dead on the one
      call site that reliably supplies a real value.
    - **Explicit user choice always wins (VC7, reconciled one direction):** on a known non-empty
      description, if the user picks "replace" in the keep/replace control, the panel sends
      `apply_description=true`. That is a deliberate human decision, not the silent overwrite AC-6
      forbids. §Public Contracts and D13 state this identically.
    `apply_category` defaults `true` in all cases (there is no user-typed category to clobber).
    **Competitor rendering (V6):** `competitors[].domain` renders as **plain text only — never an
    `<a href>`, never a link.** The value is model-controlled and is already null-on-invalid from
    `sanitize_profile`; the plain-text rule is the second layer so no reader is one click from a
    model-chosen URL.
21. **3.4 — Insert into `apps/web/src/components/onboarding/steps/install-step.tsx`** at the exact
    position named in §Coordination, and **plumb the description (F3)**:
    (a) add `currentDescription?: string | null` to `InstallStep`'s props type/destructuring
        (`install-step.tsx:19-34`) and forward it to the panel;
    (b) in `apps/web/src/components/onboarding/onboarding-flow.tsx`, add a component-local
        `const [submittedDescription, setSubmittedDescription] = useState<string | null>(null)` and
        set it from `values.description` inside `handleCreateSite` (`:143-149`), then pass
        `currentDescription={submittedDescription}` at the `<InstallStep …>` call site (`:355-365`).
    (c) **Mount the panel a SECOND time on the `done` step (V5/R12)** — inside the existing
        `{queue.done && state.step === "done" && (…)}` block at `onboarding-flow.tsx:367-369`,
        beside `<DoneStep onFinish={handleFinish} />`, with `variant="onboarding"` and the same
        `currentDescription`. **Why this is not optional:** `onVerified` dispatches `VERIFIED`, which
        moves `state.step` to `done` and **unmounts `InstallStep` — and the panel with it**. A pixel
        that verifies in ~20 s therefore destroys the results surface ~100 s before a ~120 s grounded
        analysis lands, so the user never sees results, never confirms, and the whole AC-3 → AC-5 →
        AC-6 → AC-7 chain silently no-ops. One extra conditional mount closes it.
    **Do NOT add a `flowReducer` field, `StepId`, or `FlowEvent`** — the reducer test surface
    (`onboarding-flow.test.ts`) stays untouched. Note (D13): the (b) plumbing is a **best-effort
    enhancement**, not a correctness dependency — the fail-safe default in 3.3 means a missing
    `currentDescription` can no longer cause the silent overwrite that R7/AC-6 exist to prevent.
22. **3.5 — Insert into `apps/web/src/components/site-settings-dialog.tsx`** with
    `variant="settings"`, `currentDescription={site.description}` (`Site.description` exists at
    `api-types.ts:156`), and the re-run button visible (AC-8).
    **Exact target scope (C13/V3) — do not guess:** render inside the inner **`SiteSettingsBody`**
    (`site-settings-dialog.tsx:63`), **below its `if (!site)` early return (`:165`)** — e.g. directly
    after the "Site details" block (`:173`). The exported `SiteSettingsDialog` (`:29`) receives only
    `{ siteId }` and renders `<SiteSettingsBody siteId={siteId} />` at `:55`; it has **no `site`
    object at all**, so `site.description` / `site.site_id` are unresolvable there. There is exactly
    one valid scope. This is also the call site that reliably supplies a real `currentDescription`
    (it comes from `useQuery` at `:66`, not from ephemeral wizard state).
23. **3.6 — Add `.ob-analysis*` styles** to `apps/web/src/styles/onboarding-chat.css`, scoped under
    `.ob-root`, matching the existing `.ob-bubble` idiom.
24. **3.7 — Add the Playwright legs** to the existing `apps/web/e2e/onboarding.spec.ts` (counted in
    §Blast Radius per N4): Continue stays enabled during detect-platform; onboarding completes while
    analysis is pending; **the panel is still mounted after the pixel verifies and the wizard moves to
    the `done` step (V5)**; edit-a-field-and-confirm persists; **flag-off renders nothing after a
    single 404 `GET`, with no retry loop (N2)**. These legs are **CONDITIONAL** behind the standing
    Clerk auth-harness gap and carry a skip-guard (`E2E_SITE_ANALYSIS`) in the same style as
    `E2E_PRIVACY_HOLD_VISITOR`. The flag-off leg additionally has a Fully-Automated counterpart in the
    Block-3 gate (a component-level assertion that a 404 yields `null` and exactly one fetch), so the
    N2 claim does not rest on a blocked Hybrid leg.

**Block 3 test gate:**
```bash
cd apps/web && npx tsc --noEmit
cd apps/web && npx next lint --file src/components/site-analysis-panel.tsx
```

### Final regression gate (all blocks)

```bash
.venv/bin/python3.11 -m pytest tests/unit -m unit -q        # zero NEW failures vs the EXECUTE-start baseline
.venv/bin/python3.11 -m pytest tests/ -m integration -q     # zero NEW failures vs the EXECUTE-start baseline
git diff --stat apps/pixel/                                  # MUST be empty
git diff --stat apps/api/services/platform_detector.py apps/api/schemas/sites.py   # MUST be empty
```

Both baselines are the counts measured at EXECUTE start (before any source edit) with these exact
commands and recorded in the phase report. Never compare against a number quoted from a plan or
context doc (F2).

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `test_site_content.py::test_extraction_*`, `::test_fetch_failure_paths` | Fully-Automated | AC-1 (backend half) |
| `git diff --stat apps/api/services/platform_detector.py apps/api/schemas/sites.py` empty (sync detect-platform path untouched, F1 option (a)) | Fully-Automated | AC-1, AC-9 (sync-path half) |
| Playwright: Continue stays enabled while detect-platform is in flight | Hybrid (Clerk auth-harness gap) | AC-1 (UI half) |
| `test_site_analysis_api.py::test_create_site_starts_analysis_pending` | Fully-Automated | AC-2 (backend) |
| Playwright: pending indicator visible on install step | Hybrid | AC-2 (UI) |
| `test_site_analysis_api.py::test_full_lifecycle_pending_to_ready_persisted` | Fully-Automated | AC-3, AC-11 |
| `test_site_analysis_api.py::test_failure_path_sets_failed`, `::test_stale_pending_derives_failed` | Fully-Automated | AC-4 (backend) |
| Playwright: complete onboarding while analysis pending | Hybrid | AC-4 (UI) |
| `test_site_analysis_api.py::test_put_edited_profile_overwrites_ai_values` | Fully-Automated | AC-5 (backend) |
| Playwright: edit a field, confirm, reload, value persists | Hybrid | AC-5 (UI) |
| `test_site_analysis_api.py::test_confirm_fills_empty_description`, `::test_confirm_preserves_user_typed_description` | Fully-Automated | AC-6 (server half) |
| `test_site_analysis_segmenter_preseed.py` (unit complement — interpolation only) | Fully-Automated | AC-7 (partial) |
| `test_site_analysis_api.py::test_confirmed_profile_reaches_segmenter_prompt` — end-to-end: create with empty description → analysis ready (mock) → `PUT` confirm → segmenter prompt carries the values (V5: replaces the pre-confirmed-fixture-only gate, which could not observe the unmount defect) | Fully-Automated | AC-7 (the real gate) |
| `test_site_analysis_api.py::test_rerun_lifecycle_preserves_prior_profile_until_confirm` — **restated for the two-slot schema (V1):** the CONFIRMED `sites.site_profile` is byte-identical before and after a re-run while `site_profile_candidate` holds the new output; `PUT` then promotes the candidate and NULLs it | Fully-Automated | AC-8 (backend) |
| `test_site_analysis_api.py::test_concurrent_post_while_pending_returns_already_running` — second POST during `pending` ⇒ `already_running=true`, `started_at` unchanged, counter unchanged, no second task (V4) | Fully-Automated | AC-8, AC-10 (in-flight guard) |
| Settings-dialog re-run UI leg | Hybrid | AC-8 (UI) |
| `test_site_analysis_api.py::test_flag_off_endpoints_404_and_no_profile_written`; full unit+integration lanes at baseline; `git diff --stat apps/pixel/` empty | Fully-Automated | AC-9 |
| `test_site_analysis_api.py::test_budget_exhaustion_returns_capped_response_no_extra_runs`; `test_site_analysis.py::test_budget_incremented_once_per_run` | Fully-Automated | AC-10 (per-layer only — NOT sufficient alone) |
| **`test_site_analysis_api.py::test_budget_counter_delta_is_one_per_post_cycle`** — raw Redis key delta across a full POST → task cycle is exactly 1, run with `mock_external_apis=False`. **All five C17/VF2 hardenings required:** patch the `apps.api.services.site_analysis` **consumer bindings** (not the defining modules); transport raises on any other outbound request; the delta window opens **after** the create-time auto-fired task settles; the await handle is `asyncio.gather(*_analysis_tasks)` (router set, 1.10); and the run is asserted terminal `ready` alongside `delta == 1` | Fully-Automated | AC-10 (the non-vacuous gate) |
| `test_site_analysis.py::test_budget_incremented_once_per_run` — same mock-OFF treatment and the same consumer-binding patch targets (C20); vacuous under mock, so it is explicitly non-mock | Fully-Automated | AC-10 (per-layer, hardened) |
| `test_site_analysis_api.py::test_budget_denied_run_does_not_linger_pending` — a budget-denied task terminates `failed` immediately (not after the 180 s stale window, C15) and the **GET response** carries the derived cap copy; nothing is persisted (VF1) | Fully-Automated | AC-10, AC-4 |
| `test_site_analysis.py::test_budget_denied_run_sets_terminal_failed_with_message` — deny branch persists status only, no message string; read-time derivation yields cap copy while exhausted, generic copy otherwise (VF1) | Fully-Automated | AC-4, AC-10 |
| **`test_site_analysis_api.py::test_message_derivation_truth_table`** (C25) — all four `(allowed, derived-status)` cells of the E17/C21 precedence rule: `allowed=false` + `ready`/`none` ⇒ cap copy on the `GET` **and** on the `POST` capped response; `allowed=false` + `failed` ⇒ cap copy; `allowed=true` + `failed` ⇒ generic copy; `allowed=true` + `ready` ⇒ `null`. **Must fail against a pre-C21 status-switch implementation** — the non-`failed` cell is the one no other gate covers | Fully-Automated | AC-10, AC-4 (message-precedence, non-vacuous) |
| Panel `none`-state assertion: `status` null/`"none"` with both slots empty — and any row with both slots empty whatever its status, incl. `status="ready"` after a `promote:false` dismiss (C22) — renders "Beam hasn't analyzed this site yet" + an **Analyze** button that is disabled when `budget.allowed === false` (VF3 — the only entry point for pre-existing sites) | Fully-Automated | AC-8 (pre-existing-site half) |
| Panel render-rule assertion: `(candidate ?? profile)` non-null renders the review UI even when `status === "failed"`, with the failure shown as a banner ABOVE it (VC5) | Fully-Automated | AC-5, AC-8 |
| `test_site_analysis_api.py::test_put_promote_false_dismisses_candidate_only` — `promote:false` NULLs the candidate and leaves profile/status/timestamps/description/category byte-identical (VC9 dismiss path) | Fully-Automated | AC-8 |
| `test_site_analysis_api.py::test_put_during_pending_preserves_pending_status` — a `PUT` mid-run writes the confirmed slot but leaves `status="pending"` + `started_at` untouched, so stale-derivation and the cross-process in-flight check still work (C18/VC4) | Fully-Automated | AC-4, AC-8 |
| `test_site_analysis_api.py::test_put_with_no_candidate_is_allowed` — `PUT` with `candidate = NULL` / `status="none"` succeeds as the edit-the-confirmed-profile path (C18/VC4) | Fully-Automated | AC-5 |
| `test_site_analysis.py::test_sanitize_profile_nulls_invalid_competitor_domain` extended for the POSITIVE check (VC8): `javascript:alert(1)` (no netloc — passes `strip_url` unchanged) becomes `None`; scheme not in {"", http, https} becomes `None`; host failing the hostname regex becomes `None` | Fully-Automated | AC-12 (stored-injection half) |
| Whole `test_site_analysis_api.py` suite with `monkeypatch.setattr(settings, "mock_external_apis", True)`; `test_site_analysis.py::test_mock_profile_deterministic`; **`::test_mock_mode_issues_zero_outbound_requests`** (transport patched to raise on any request — proves the F4 fix) | Fully-Automated | AC-11 |
| `test_site_content.py::test_adversarial_html_cannot_escape_fence`; `test_site_analysis.py::test_prompt_builders_fence_every_field`, `::test_sanitize_profile_strips_injection_strings` | Fully-Automated | AC-12 |
| `test_site_analysis.py::test_no_pii_or_prompt_bodies_in_logs` (structlog capture) | Fully-Automated | AC-13 |
| `test_site_analysis.py::test_sanitize_profile_nulls_invalid_competitor_domain` + the panel's plain-text (never `<a href>`) competitor rendering assertion (V6) | Fully-Automated | AC-12 (stored-injection half) |
| `test_site_analysis.py::test_sanitize_profile_stamps_schema_version` (`meta.v == 1` on every persisted path incl. mock, V8) | Fully-Automated | C-2 (JSONB forward-compat) |
| `test_site_analysis.py::test_task_writes_candidate_never_confirmed_profile`; `test_site_analysis_api.py::test_get_returns_candidate_and_confirmed_separately` (V1 two-slot invariant) | Fully-Automated | AC-5, AC-8 |
| Unit test on the `Content-Length` pre-check + post-hoc truncation path (SEC-2, gate now specified — C11 named the achievable posture) | Fully-Automated | Security mandate 2 (plan-level guard) |
| Panel component assertion: a 404 `GET` renders `null`, fires exactly one request, and starts no retry loop (N2 — the honest flag-off web claim) | Fully-Automated | AC-9 (web half) |
| Panel confirm-payload assertion across THREE cases: `currentDescription` known-non-empty ⇒ `apply_description=false`; **absent/undefined ⇒ `false` (fail-safe, D13/V3)**; known-empty ⇒ `true` permitted | Fully-Automated | AC-6 (client half) |
| Manual grounded run against a documented panel of real sites (coherence, no fabricated competitors, sparse-not-invented on low-signal sites) | Agent-Probe (needs-live-provider) | AC-14 |
| SSRF: `test_ssrf_guard.py::test_fetch_site_content_refuses_metadata_without_fetch` (placed beside its two existing siblings, C6) | Fully-Automated | Security mandate 1 (not an AC — plan-level guard) |
| Frontend: `currentDescription` is supplied by the settings call site (`SiteSettingsBody`, below the `if (!site)` guard — C13) and by the onboarding call site on a best-effort basis (D13) | Fully-Automated | AC-6 (client half, F3) |
| Playwright: panel still mounted after the pixel verifies and the wizard advances to the `done` step (V5) | Hybrid (Clerk auth-harness gap) | AC-3, AC-5 (results-surface survival) |
| Migration live down/up round-trip on `localhost:5433` | Hybrid (needs local PG) | C-2, C-9 |

**Known-gap residuals (recorded, NOT terminal PASS):** AC-14 is Agent-Probe by necessity
(live-provider, non-deterministic) — it stays CONDITIONAL and gets a backlog stub if the probe is not
run before archive. All Hybrid Playwright legs inherit the standing repo-wide Clerk auth-harness gap
and are CONDITIONAL, not skipped-and-forgotten; each has a Fully-Automated backend counterpart above,
so no AC rests on a Hybrid leg alone.

---

## Test Infra Improvement Notes

- **Pre-existing, inherited (not created here):** the Clerk Playwright auth-harness gap and the
  live-provider Agent-Probe tier.
- **Found during PVL cycle 1:** `apps/api/services/platform_detector.py` has **zero** behavioral test
  coverage — no test exercises platform scoring, the 403-header branch, the Shopify API probe, or GTM
  extraction (`pytest tests/ -k platform` collects 4 tests, only one of which touches
  `detect_platform`). This is why the refactor was dropped from scope. Backlog stub:
  `platform-detector-uncovered_NOTE_13-08-26.md`.
- **Found during PVL cycle 1:** `tests/conftest.py` pins `DATABASE_URL`/`REDIS_URL`/`GEMINI_API_KEY`
  but not `MOCK_EXTERNAL_APIS`, so every integration test must set it per-module. A shared autouse
  fixture would remove a recurring footgun (a mock-mode gate can otherwise pass while making live
  calls). Recorded as an improvement idea, not in scope here.
- **Found during PVL cycle 2 (F5, generalizable):** mock mode short-circuits *before* the code under
  test in several services, so any gate that asserts a **counter/quota/side-effect** must either run
  with `mock_external_apis=False` (patching the specific outbound calls) or state explicitly that it
  is only proving the mock path. There is no repo-wide helper for "mock the network but not the
  business logic"; every module hand-rolls it. A shared `patch_outbound` fixture would make
  side-effect gates non-vacuous by default. Recorded, not in scope here.
- **Found during PVL cycle 2 (V5, generalizable):** no test in `apps/web` exercises a component
  across a wizard step transition, so "the component unmounted before its async result arrived" is a
  whole class of defect the current web test surface cannot see. The AC-7 end-to-end integration leg
  added by step 2.2 covers the backend chain but not the React unmount itself; that half still rests
  on a Clerk-blocked Playwright leg. Recorded as a structural web-test gap.

---

## Dependencies and Blockers

| Dependency | Status |
|---|---|
| Local Postgres on `:5433` for the migration round-trip + integration lane | Available (Docker CLI off `PATH` — use `lsof` to confirm, not `which docker`) |
| Redis on `:6379` for the budget counter integration tests | Available |
| Gemini API key | **Not required** — all automated gates run under `MOCK_EXTERNAL_APIS=true`. Only AC-14 needs a live key. |
| Canary phases 2-4 | **Not a blocker** — the panel is self-contained and takes one prop. Coordination note only. |
| Alembic head | Must be derived LIVE at execute time (Step 1.1); do not trust any head recorded in context docs |

**No blockers.**

---

## Backwards Compatibility and Rollback

- All **5** columns are additive + nullable; existing rows read as `status="none"` with both
  `site_profile` and `site_profile_candidate` NULL.
- `SiteOut` is unchanged — no existing client sees a new field.
- **`PlatformDetectResponse` is unchanged — no new fields** (corrected, C10/V9: the previous sentence
  claimed "gains only OPTIONAL fields", a leftover from the scope deleted by F1 option (a); it
  contradicted §Public Contracts, D6, step 1.12 and the `git diff --stat … schemas/sites.py` gate).
  §Blast Radius already reads "3 new endpoints; no change to any existing response shape" and needed
  no correction; the only other surviving mention of the old wording lives inside the
  validator-owned `## Validate Contract`, which this supplement does not edit.
- **Rollback:** set `site_analysis_enabled=false` — every new endpoint 404s, no task fires, no fetch,
  no AI call. The columns can stay (inert). Full rollback: `alembic downgrade -1` with `DATABASE_URL`
  pinned to the local DB.

---

## Success Criteria (measurable)

1. All 14 SPEC ACs have a green gate in the Verification Evidence table, or a recorded CONDITIONAL
   with a named residual (AC-14, Hybrid UI legs).
2. Both lanes show **zero NEW failures vs the baseline measured at EXECUTE start** with
   `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` and
   `.venv/bin/python3.11 -m pytest tests/ -m integration -q`; both baseline and final counts are
   recorded verbatim in the phase report.
3. `git diff --stat apps/pixel/` is empty, and so is
   `git diff --stat apps/api/services/platform_detector.py apps/api/schemas/sites.py`.
4. Migration down/up round-trip proven on `localhost:5433` (all **5** columns, incl.
   `site_profile_candidate`), head recorded in the phase report.
5. `settings.site_analysis_enabled` is `False` in committed code.
6. `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs <this file>` reports no FAIL.

---

## Acceptance Criteria

Authoritative text lives in the SPEC (`site-analysis-onboarding_SPEC_13-08-26.md` §Acceptance
Criteria). This plan carries all 14 verbatim-by-reference; each is `proven by` a named gate with an
explicit strategy in §Verification Evidence.

> **AC-1 is AMENDED (F6).** F1 option (a) removed the site-step content read from scope, so AC-1 v1
> ("a fast platform + **basic-content read** … proven by integration test on the site-step
> fetch/extract endpoint") describes a behavior this plan does not build. Rather than silently
> re-point its proving gate, the amendment is recorded in the SPEC file itself under
> `## Amendments` and restated in §Plan Deviations / PVL Cycle 2. AC-1 v2 is the row below.

| AC | One-line criterion (see SPEC for full text) | proven by / strategy |
|---|---|---|
| AC-1 **(AMENDED 13-08-26 — see the SPEC's `## Amendments` section and §Plan Deviations / PVL Cycle 2)** | **v2:** platform detect at the site step never delays or disables Continue; the **content read happens asynchronously post-creation**, not at the site step | Sync half: `git diff --stat apps/api/services/platform_detector.py apps/api/schemas/sites.py` empty + Playwright Continue leg. Async half: `test_site_content.py` extraction/failure tests — Fully-Automated + Hybrid. **These gates now match the amended criterion; before the amendment they proved a different behavior than AC-1 v1 stated (F6).** |
| AC-2 | Analysis auto-starts after site creation; PENDING visible on install step | `test_create_site_starts_analysis_pending` + Playwright pending leg — Fully-Automated + Hybrid |
| AC-3 | Completed analysis persisted on the Site record; UI PENDING → READY | `test_full_lifecycle_pending_to_ready_persisted` — Fully-Automated |
| AC-4 | Failure/timeout ⇒ FAILED with plain-language copy; never blocks the wizard | `test_failure_path_sets_failed`, `test_stale_pending_derives_failed` + Playwright leg — Fully-Automated + Hybrid |
| AC-5 | Every section editable, labeled AI-generated; the user's edits are what is saved | `test_put_edited_profile_overwrites_ai_values` + Playwright edit/confirm leg — Fully-Automated + Hybrid |
| AC-6 | Confirm auto-fills description/category with no silent overwrite | `test_confirm_fills_empty_description`, `test_confirm_preserves_user_typed_description` (server half) + the `currentDescription`-supplied assertion (client half, F3) — Fully-Automated |
| AC-7 | Segmenter prompt carries the confirmed description + category | **primary:** `test_site_analysis_api.py::test_confirmed_profile_reaches_segmenter_prompt` (end-to-end: create with empty description → ready under mock → `PUT` confirm → segmenter prompt carries the values) — Fully-Automated. **Complement (per-layer/partial only, NOT sufficient alone):** `test_site_analysis_segmenter_preseed.py` (interpolation). Re-pointed C16. |
| AC-8 | Owner can re-run from site settings; prior edits never silently discarded | `test_rerun_lifecycle_preserves_prior_profile_until_confirm` + settings re-run UI leg — Fully-Automated + Hybrid |
| AC-9 | Flag defaults OFF; flag-off behavior byte-identical, new endpoints 404 | `test_flag_off_endpoints_404_and_no_profile_written`, full lanes at baseline, empty `apps/pixel/` diff — Fully-Automated |
| AC-10 | Budget-capped 3/day/site; graceful cap response, never an error or partial profile | **primary:** `test_site_analysis_api.py::test_budget_counter_delta_is_one_per_post_cycle` (raw Redis key delta across a full POST → task cycle is exactly 1, run with `mock_external_apis=False`) — Fully-Automated. **Per-layer/partial only, NOT sufficient alone:** `test_budget_exhaustion_returns_capped_response_no_extra_runs`, `test_budget_incremented_once_per_run`. Re-pointed C16. |
| AC-11 | `MOCK_EXTERNAL_APIS=true` runs the whole flow keylessly and deterministically | whole `test_site_analysis_api.py` under mock + `test_mock_profile_deterministic` — Fully-Automated |
| AC-12 | Site HTML and AI output are fenced per field; injection cannot escape | `test_adversarial_html_cannot_escape_fence`, `test_prompt_builders_fence_every_field`, `test_sanitize_profile_strips_injection_strings` — Fully-Automated |
| AC-13 | No PII and no prompt bodies logged | `test_no_pii_or_prompt_bodies_in_logs` — Fully-Automated |
| AC-14 | Grounded output on a real-site panel is coherent and does not fabricate | manual grounded panel run — Agent-Probe (needs-live-provider), CONDITIONAL residual |

---

## Plan Deviations / PVL Cycle 1

Applied 13-08-26 in PVL supplement mode against the `Gate: BLOCKED` validate-contract (4 FAILs,
9 CONCERNs). Orchestrator decision on F1 was **option (a)**.

| Gap | Resolution |
|---|---|
| F1 | **Scope reduced.** `platform_detector.py` is NOT refactored and NOT touched; `site_content.py` is new code only, using `url_guard` with the DNS-pinned posture. Precedent citation corrected to `pixel_verifier.py:122-124`. Step 1.6 REMOVED. **Sync-path content extraction is DROPPED from scope v1** — the sync fetch at the site step stays exactly what it is today (platform detect only) and ALL extraction happens in the async analysis fetch. Hybrid timing (D1) is now: sync platform-detect (existing, unchanged) + async fetch+analysis. |
| F2 | All gate commands rewritten to the canonical lanes (`-m unit` / `-m integration`). Hard-coded `1280`/`537` baselines replaced with "measure at EXECUTE start, record in the phase report; gate = zero NEW failures vs measured baseline". |
| F3 | `currentDescription` plumbed for real: `onboarding-flow.tsx` local state → `InstallStep` prop → panel; settings passes `site.description`. Touchpoints line for `onboarding-flow.tsx` changed from "verify only" to EDITED. |
| F4 | Mock short-circuit moved to the TOP of `run_site_analysis` (before budget and fetch); `fetch_site_content` also gets its own mock branch (`content_reader.py:262,356,744`). AC-11 gate now asserts zero outbound requests. New risk row R10. |
| C1, C2, C3 | Resolved **by deletion** under F1 option (a): no `platform_detector` refactor ⇒ no need for characterization tests as a regression net; no `PlatformDetectResponse` fields ⇒ no field-name contradiction; no `PlatformResult` passthrough problem. The pre-existing coverage gap is still recorded as a backlog note. |
| C4 | `async_session_maker` → `async_session` (`models/database.py:78`, pattern `events.py:946`). |
| C5 | Step 1.15 sets mock mode explicitly via `monkeypatch.setattr(settings, "mock_external_apis", True)` (`tests/integration/test_ads_flag.py:46`). |
| C6 | SSRF-posture test placed in the existing `tests/unit/test_ssrf_guard.py`; extraction/adversarial tests stay in `test_site_content.py`. |
| C7 | One Touchpoints paragraph records why `site_content.py` is separate from `content_reader.py` (different guard posture, no yt-dlp/Reddit coupling). |
| C8 | Drifted anchors refreshed (`db.refresh` :187, `model_validate` :191, segmenter :21-23) + explicit "match on anchor text, not line numbers" instruction. |
| C9 | Insertion point restated: inside `<div className='ob-bubble plain wide'>`, immediately **after the `detecting` ternary block**. |

**Net effect on scope:** 1 fewer created file, 2 fewer modified backend files, 1 more modified web
file, 1 more modified test file; one public-contract change removed; one HIGH risk (R1) retired and
one HIGH risk (R10) added.

---

## Plan Deviations / PVL Cycle 2

Applied 13-08-26 in PVL supplement mode against the cycle-2 `Gate: BLOCKED` validate-contract
(2 FAILs F5–F6, 6 CONCERNs C10–C15) **plus an independent adversarial verifier leg** (V1–V10 +
N1–N5, recorded in `site-analysis-onboarding-pvl-iteration-002_REPORT_13-08-26.md`). Orchestrator
decisions were binding; the resolutions below implement them verbatim.

| Gap | Resolution |
|---|---|
| **F5 / V2** — budget incremented twice on the re-run path; both AC-10 gates blind to it | **Single owner named: the TASK.** New D11. `POST` **checks only** (for the capped response) and never increments; `run_site_analysis` owns the one check+increment; `create_site` does no budget work. New gate `test_budget_counter_delta_is_one_per_post_cycle` observes the **raw Redis key delta across a full POST → task cycle** and must run with `mock_external_apis=False`. **Mock-mode counter behavior is now stated explicitly** in 1.9 (mock returns before the increment ⇒ zero increments — intentional, and precisely why the new gate cannot use mock). Check-then-increment TOCTOU accepted and recorded as **R11** (best-effort free-tier guard, not a billing meter). |
| **F6** — SPEC AC-1 requires a behavior option (a) deleted | **Explicit SPEC amendment written** into the SPEC file's new `## Amendments` section (AC-1 v2: sync site-step = platform-detect only; content read is async post-creation). §Acceptance Criteria carries a blockquote pointing at it and the AC-1 row is re-pointed **honestly** to the async-fetch gates + the sync-path diff gate, labelled as proving the amended criterion. |
| **V1** — AC-8 unimplementable on a one-slot schema | **Option (a): fifth column `site_profile_candidate` (JSONB, nullable).** D4 revised to two-slot storage. The task writes ONLY the candidate (incl. the first-ever run and the mock path — one uniform path); `GET` returns `profile` and `candidate` separately; `PUT` promotes candidate → `site_profile` and NULLs the candidate, and is the ONLY writer of the confirmed slot. AC-8's gate restated: confirmed profile byte-identical across a re-run. Migration/model/schema/checklist counts all moved 4 → 5. |
| **V3** — `useState` description lost on reload ⇒ silent overwrite returns | **Fail-safe default (D13):** absent/unknown `currentDescription` ⇒ `apply_description=false`; only known-empty permits `true`. `SiteAnalysisConfirm.apply_description` now defaults `False`. The `useState` plumbing stays as a best-effort enhancement, not a correctness dependency (R7 rewritten). Settings variant supplies the reliable value from `SiteSettingsBody`. Client gate now asserts THREE cases incl. undefined. |
| **V4** — no server-side in-flight guard | **D12:** `POST` while derived-pending returns `already_running: true` with no increment, no `started_at` re-stamp, no task fired; in-process half is a module-level `_analysis_inflight: set[str]` mirroring `events.py:75` / `:560-567` (`_aggregating`), discarded in the task's `finally`. New integration gate `test_concurrent_post_while_pending_returns_already_running`. |
| **V5** — results surface destroyed when the pixel verifies before the analysis lands | **Panel mounted twice:** `install` step AND `done` step (`onboarding-flow.tsx:367-369`, beside `<DoneStep …>`). New risk **R12**. The AC-7 gate is rebuilt as an **honest end-to-end integration leg** (create with empty description → ready under mock → `PUT` confirm → segmenter prompt carries the values); the pre-confirmed-fixture unit test is retained only as a complement. |
| **V6** — competitor domain is an unvalidated LLM-controlled string | `sanitize_profile` hostname-validates `competitors[].domain` (plain hostname, or survives `strip_url` with an `http`/`https` scheme), else `None`. **UI renders competitor domains as plain text, never as an anchor/`href`.** One unit assertion + the §Security stored-injection row. |
| **V7** — budget wrongly BYOK-exempt | **D14: NOT BYOK-exempt.** `check_site_analysis_budget` caps unconditionally (`byok=False`), because the analysis burns the SYSTEM Gemini key; the precedent is the paid-OSINT block's own comment in `usage_limits.py`. `is_full_byok` is not called at all — which also removes the per-poll DB round-trip (N5). |
| **V8** — no JSONB schema version | `meta.v = 1` added to §Public Contracts, step 1.8, `sanitize_profile`, and `mock_profile`, with a unit gate. |
| **V9 / C10** — stale `PlatformDetectResponse` claim | §Backwards Compatibility corrected to "unchanged — no new fields". The second cited instance does not exist in the plan body: §Blast Radius already reads "3 new endpoints; no change to any existing response shape"; the only other mention lives inside the validator-owned `## Validate Contract`, which this supplement does not edit. |
| **V10** — `SiteAnalysisOut` missing `message`, and `is_byok` posture | `message: str \| None = None` added (budget-cap copy, budget-denied run). `is_byok` **deliberately omitted** from the `budget` sub-object — moot under D14 and stated so it is not re-added. `already_running: bool = False` also added (V4). |
| **C11** — 512 KB cap unachievable via `safe_get` | Real posture stated in both §Security and step 1.5: `Content-Length` **pre-check** + **post-hoc truncation**, with the chunked/no-Content-Length full-buffering case recorded as an accepted residual (authed, 3/day/site, 10 s timeout). SEC-2 now has a named gate. |
| **C12 / N3** — `BROWSER_HEADERS` source unnamed | Named: read-only `from apps.api.services.platform_detector import BROWSER_HEADERS` (`platform_detector.py:18`; `pixel_verifier.py:24` is a *different* constant, `BROWSER_UA`). An import leaves the diff gate empty; **editing that module remains forbidden (E11)**. |
| **C13** — step 3.5 targeted the wrong component scope | Retargeted to the inner `SiteSettingsBody` (`:63`), below the `if (!site)` early return (`:165`), e.g. after the "Site details" block (`:173`). The exported `SiteSettingsDialog` (`:29`) has no `site` object. |
| **C14** — incoherent timing constants | Ordered deliberately and stated in D2 + step 1.4 + step 3.3: **poll cap 240 s (60 × 4 s) > stale 180 s > ~120 s worst-case latency**. E13 already binds the two to move together. |
| **C15** — budget-denied task leaves the row `pending` | The task sets a terminal state immediately on denial (`status="failed"` + the cap `message`) and returns; added to 1.9, to the AC-10 integration cases, and to §Verification Evidence. |
| **N1** — "flag check before any DB read" was not literally achievable | Reworded: `_require_flag()` **inside the handler body** per `routers/onboarding.py:53-56`; accepted and stated consequence — an unauthenticated probe gets 401 before the flag check (matches repo posture everywhere else). |
| **N2** — flag-off not byte-identical on the web | Claim scoped honestly: **byte-identical on the BACKEND**; the web panel still issues exactly one `GET` that 404s and renders nothing. New assertion: 404 ⇒ `null`, exactly one request, no retry loop. |
| **N4** — blast-radius count off by one | `apps/web/e2e/onboarding.spec.ts` added to §Touchpoints and the modified-file count (11 → 12). |
| **N5** — per-poll DB round-trip via `is_full_byok` | Removed by D14: `budget` is computed from a **single plain Redis GET**, no `user_api_keys` SELECT. Stated in §Public Contracts and step 1.7. |

**Net effect on scope:** +1 migration column (4 → 5), +1 modified web file (11 → 12 modified),
+4 locked decisions (D11–D14), +2 risks (R11 accepted, R12 HIGH mitigated), +9 named test gates
(whole-cycle counter delta, in-flight guard, budget-denial terminal state, candidate/confirmed
separation, competitor-domain nulling, schema version, SEC-2 body cap, flag-off web 404,
AC-7 end-to-end). One SPEC criterion (AC-1) formally amended. No new files created, no new
endpoints, no scope added outside the blast radius already declared.

---

## Plan Deviations / PVL Cycle 3

Applied 13-08-26 in PVL supplement mode against the cycle-3 `Gate: CONDITIONAL` validate-contract
(0 FAILs, 5 CONCERNs C16–C20) **plus a second independent adversarial verifier leg** (VF1–VF3,
VC4–VC9, N10–N12, recorded in `site-analysis-onboarding-pvl-iteration-004_REPORT_13-08-26.md`).
Orchestrator decisions were binding; the resolutions below implement them verbatim. The
validator-owned `## Validate Contract` was NOT edited, and neither was `results.tsv`.

| Gap | Resolution |
|---|---|
| **C16** — §Acceptance Criteria points AC-7 / AC-10 at gates the plan itself calls insufficient | Both rows re-pointed to the honest primary gates — AC-7 → `test_confirmed_profile_reaches_segmenter_prompt`, AC-10 → `test_budget_counter_delta_is_one_per_post_cycle` — with the superseded gates relabelled "per-layer/partial only, NOT sufficient alone". |
| **C17 + VF2** — the one mock-OFF gate has unnamed patch targets, no zero-outbound backstop, no terminal assertion, an unsound delta window and an unnamed await handle | Five mandatory hardenings written into 1.15: (a) patch the **consumer bindings** `apps.api.services.site_analysis.{fetch_site_content,gemini_generate,gemini_generate_json}` — patching the defining module does nothing against a `from … import` binding; (b) **E12's raise-on-any-outbound transport guard extended to this non-mock gate**, since the increment happens before the fetch and a mis-patch would otherwise pass while hitting the network; (c) the delta window opens **after** the create-time auto-fired task settles; (d) the await handle is named: `asyncio.gather(*_analysis_tasks)` (the router set from 1.10, copied before gathering); (e) assert the run reached terminal `ready` alongside `delta == 1`. |
| **C20** — the unit sibling is vacuous under mock by the same F5 mechanism | `test_budget_incremented_once_per_run` given the **same mock-OFF treatment and the same consumer-binding patch targets** (chosen over renaming, for consistency with 1.15), plus the terminal-`ready` assertion. |
| **VF1** — `message` has no storage; two named gates unimplementable | **Read-time derivation, no 6th column (D15).** 1.9's DENY branch now persists status only; §Public Contracts documents `message` as derived; both gates re-pointed to assert the message on the **GET response**, never on the DB row. |
| **VF3** — no `none` panel state ⇒ AC-8 unreachable for every pre-existing site | Fourth panel state added (D17): status NULL/`"none"` renders "Beam hasn't analyzed this site yet" + an **Analyze** button (`POST`), disabled when `budget.allowed === false`. New Verification Evidence row. |
| **C18 / VC4** — `PUT` erases in-flight `pending`; `candidate = NULL` undefined; `analyzed_at` two-writer ambiguity | **D16.** `PUT` leaves `status`/`started_at` untouched when the derived status is `pending`; `PUT` with `candidate = NULL` is explicitly **allowed** (edit-the-confirmed-profile path); `analyzed_at` is defined as the **candidate-analysis completion time with exactly one writer (the task)** — `PUT` never stamps it and no second column is added. Two new integration gates. |
| **VC5** — `failed` re-run hides an already-confirmed profile | Render rule stated in §Public Contracts and 3.3: review UI whenever `(candidate ?? profile)` is non-null regardless of status; `failed` is a **banner ABOVE**, never instead. New assertion row. |
| **VC6** — `_analysis_inflight` placement causes a router↔service import cycle; `finally` is the wrong cleanup hook | Container moved to **`apps/api/services/site_analysis.py`** (the router already imports the service, so no cycle). Discard happens **only** in the `add_done_callback` registered by the router's fire helper, mirroring `events.py:560-567` — a done-callback fires on every outcome incl. cancellation; a coroutine `finally` does not. 1.9's step (7) `finally` discard removed. |
| **VC7** — D13 case table omits `null`, and explicit-replace was ambiguous | D13 rewritten as a four-case table: `undefined`/absent ⇒ `false`; **`null` ⇒ known-empty (server-asserted — `Site.description` is `string \| null`)** ⇒ `true` permitted; `""` ⇒ `true` permitted; non-empty ⇒ `false` by default but the user's explicit "replace" **MAY** set `true`. §Public Contracts and 3.3 restate it identically. |
| **VC8** — `strip_url` is not a validator (`javascript:` passes it unchanged) | Replaced with a **positive** check in all three places (§Public Contracts, §Security, 1.9): keep the domain only if `urlsplit(domain).scheme in {"", "http", "https"}` **AND** the derived host matches a plain hostname regex. The "survives `strip_url`" phrasing is removed. Gate extended with the `javascript:` case. (The cycle-2 deviations row for V6 records the superseded wording as history.) |
| **VC9** — a candidate shadows the confirmed profile with no dismiss path | `PUT` gains **`promote: bool = True`** (D16); `promote: false` NULLs the candidate and touches nothing else. Surfaced in the panel as a "Keep current" action, with one new integration gate. |
| **C19 / N10** — three stale "4 columns" / "four" strings | Corrected to five in §Touchpoints (migration row), §Blast Radius (risk classes) and checklist 1.3. |
| **N11** — SPEC narrative §What The User Wants item 1 still promised "platform + basic content" | Struck in place in the SPEC with a pointer to `## Amendments` row A-1, per the SPEC's own amendment discipline (the AC table was already amended by F6; the narrative was not). |
| **N12** — dead params + `is_byok` projection | 1.7 now mandates **`check_site_analysis_budget(site_id)`** exactly — no `db`, no `user_id` (D14 removed their only consumers) — and states the explicit three-field projection into `SiteAnalysisOut.budget` (`used`/`limit`/`allowed`; `is_byok` dropped at the boundary). |

**Net effect on scope:** **no new columns, no new files, no new endpoints** — the migration stays at
five columns because VF1 was resolved by derivation rather than storage. One new request field
(`SiteAnalysisConfirm.promote`), one new panel state (`none`), one module-level container relocated
service-side, +3 locked decisions (D15–D17), +6 named test gates (`promote:false` dismiss,
`PUT`-during-pending, `PUT`-with-no-candidate, panel `none` state, panel render rule, the re-pointed
derived-message pair), and 5 mandatory hardenings on the existing mock-OFF counter gate.

---

## Plan Deviations / PVL Cycle 4

Supplement cycle 5 — closes C21–C24 + nits N13–N15 from the cycle-4 validate contract. **No new
columns, files, endpoints, request fields or panel states.** Every change is a specification fix.

| Finding | Resolution |
|---|---|
| **C21** — the derived-`message` rule contradicted the `POST` capped-response bullet, and left the `none`-state disabled-Analyze copy undefined | The rule is restated in §Public Contracts as a **top-down precedence over `(allowed, derived status)`**, evaluated by a **single shared helper**: (1) `allowed == false` ⇒ cap copy **regardless of status**; (2) `allowed == true` AND `failed` ⇒ generic copy; (3) else `null`. The contradicting `message` clause is **deleted** from the `POST` budget bullet (it now points at the single definition). D15 restated. 3.3's `none` and `failed` branches now render the server `message` verbatim instead of choosing copy client-side. |
| **C21 residual** (unfixable) | Recorded as **R13** in §Risk Predictions and in D15: a non-budget failure while the counter is exhausted reports the cap copy. Accepted price of D15's no-sixth-column decision; explicitly marked "do NOT fix during EXECUTE". |
| **C22** — `status="ready"` with both slots empty (reachable via `promote:false` dismiss of a first-ever candidate) fell into the `ready` branch; review-UI ownership stated twice | 3.3 and §Public Contracts now evaluate **slot emptiness BEFORE the status switch** (both slots empty ⇒ the `none` presentation whatever `status` says), and state that the review/edit UI is **owned by the render rule `(candidate ?? profile)` alone** — status branches contribute only a banner (`failed`), a quiet indicator (`pending`), or the empty-state copy (`none`) ABOVE it. D17 extended. |
| **C23** — the `POST` fire path was not bound to `_fire_site_analysis`, the only registrar of the discard callback | §Public Contracts (`POST`) and checklist 1.11 now say "fires via **`_fire_site_analysis` (1.10)** — never a bare `asyncio.create_task`", with the three named failure modes. `test_concurrent_post_while_pending_returns_already_running` gains a **post-settle leg**: after the POST-fired run completes, a further `POST` must NOT return `already_running` — the only gate that proves the discard ran. |
| **C24** — SPEC §Constraints C-1 and §Background still described the deleted sync content extraction | C-1 struck in place with the `## Amendments` A-1 pointer (same discipline as `SPEC:32`); the §Background "sync half" sentence annotated as pre-amendment research context; A-1's scope note extended to name C-1 and §Background. |
| **N13** | VC6's stale import-cycle justification corrected in both places (D12 and 1.10): the service never discards, so a router-side set would create no cycle either — the service-side placement now stands on domain-ownership/co-location grounds. |
| **N14** | §Complexity's "~11 touched/created backend files" corrected to **13**, reconciling with §Touchpoints and §Blast Radius. |
| **N15** | 1.15 now states the **per-test override**: the two mock-OFF gates must re-apply `monkeypatch.setattr(settings, "mock_external_apis", False)` inside the test body (function-scoped monkeypatch beats the module autouse fixture), asserting `settings.mock_external_apis is False` first (E20). Omitting it re-mocks the run and makes both gates vacuous by the F5/C20 mechanism. |

---

## Phase Completion Rules

This plan's 3 blocks are internal work blocks, not program phases; the whole artifact advances as
one unit through the inner loop recorded in §Phase Loop Progress.

- **CODE DONE** — every checklist item in a block is implemented and that block's test gate is
  green locally. This is NOT completion.
- **🧪 TESTING** — code complete, but at least one gate is still unrun, CONDITIONAL, or awaiting a
  precondition (live provider, Clerk auth harness, local Postgres).
- **✅ VERIFIED** — reachable only when ALL of: (a) every Fully-Automated gate in
  §Verification Evidence is green in an independent EVL run by `vc-tester`; (b) every Hybrid gate is
  either green or recorded as a named CONDITIONAL residual with a Fully-Automated backend
  counterpart; (c) every Agent-Probe / Known-Gap residual has a backlog stub; (d) the final
  regression gate passes at the recorded baselines; and (e) the user confirms the behavior. A block
  may never be marked ✅ VERIFIED on Known-Gap coverage alone.
- **BLOCKED** — a gate cannot be run or a fix would widen scope; record the blocker plus the safest
  next action in the phase report and route per the escalation ladder rather than silently
  downgrading the gate.
- No block advances past its own gate: Block 1's gate runs before Block 2 starts, Block 2's before
  Block 3, and the final regression gate runs after all three.

---

## Phase Loop Progress

- [x] Step 1 — RESEARCH (13-08-26; file:line ground truth in the SPEC §Background)
- [x] Step 2 — INNOVATE (Decision Summary locked; D1–D10 above)
- [x] Step 3 — PLAN (this artifact)
- [x] Step 4 — PVL (vc-validate-agent; contract below is `Gate: PASS`, cycle 6)
- [~] Step 5 — EXECUTE (**Block 1 DONE 14-08-26** — see
      `site-analysis-onboarding_REPORT_14-08-26.md`; Blocks 2 and 3 not started)
- [ ] Step 6 — EVL (independent vc-tester confirmation run)
- [ ] Step 7 — UPDATE PROCESS

---

## Resume and Execution Handoff

1. **Selected plan file:**
   `process/features/onboarding-canary/active/site-analysis-onboarding_13-08-26/site-analysis-onboarding_PLAN_13-08-26.md`
2. **Last completed phase/step:** PLAN (Step 3) + **PVL supplement cycle 3** (13-08-26 — the 5
   CONCERNs C16–C20 from the cycle-3 CONDITIONAL contract plus all 12 second-verifier findings
   (VF1–VF3, VC4–VC9, N10–N12) addressed; see §Plan Deviations / PVL Cycle 3. Historical: **cycle 2**
   (13-08-26 — the 2 FAILs
   (F5, F6) and 6 CONCERNs (C10–C15) from the cycle-2 BLOCKED contract, plus all 10 adversarial
   verifier findings (V1–V10) and 5 nits (N1–N5), addressed; see §Plan Deviations / PVL Cycle 2.
   Cycle 1's F1–F4 + C1–C9 were closed in the previous supplement and re-verified CLOSED by the
   cycle-2 contract.) Checklist items 1.1–3.7 all unstarted (1.6 and 1.12 are REMOVED by design).
3. **Validate-contract status:** written, **`Gate: CONDITIONAL`** (13-08-26, `generated-by:
   outer-pvl`, **PVL cycle 3**) — 0 FAILs, 5 CONCERNs (C16–C20). **All five are now CLOSED by
   supplement cycle 3**, together with the 12 second-verifier findings; the contract itself is
   STALE-BY-DESIGN and awaits cycle-4 re-validation. **Not yet accepted:** the validate-agent does
   not self-accept a CONDITIONAL. (Historical: cycle 2's `Gate: BLOCKED`) The contract section is owned by vc-validate-agent and was NOT edited by this
   supplement; neither was `results.tsv`. No git state was changed.
4. **Supporting context loaded:** `process/context/all-context.md` (AI Layer, business guardrails,
   flag conventions, Supabase-PROD `.env` hazard, Docker-off-PATH gotcha);
   `site-analysis-onboarding_SPEC_13-08-26.md` (14 ACs — the contract);
   `canary-onboarding_10-08-26/canary-onboarding_PLAN_10-08-26.md` (coordination);
   source ground truth: `routers/sites.py`, `services/platform_detector.py`, `services/url_guard.py`,
   `services/gemini_client.py`, `services/usage_limits.py`, `agents/prompt_safety.py`,
   `agents/segmenter.py`, `models/site.py`, `config.py`, `routers/events.py:550-570`,
   `components/onboarding/onboarding-flow.tsx`, `components/onboarding/steps/install-step.tsx`,
   `components/site-settings-dialog.tsx`, `lib/api.ts`, `lib/api-types.ts`.
5. **Next step for a fresh agent:** re-run VALIDATE (`vc-validate-agent`) from V1 against this
   **cycle-3** supplemented plan — re-check specifically: the derived-`message` rule (no 6th
   column, GET-side assertions only), the four panel states incl. `none`, the status-preserving
   `PUT` + `promote:false` dismiss path, the service-side `_analysis_inflight` with done-callback
   cleanup, the positive competitor-domain check, and the five hardenings on the mock-OFF counter
   gate. Prior guidance (still valid) was: re-validate against this
   cycle-2 supplemented plan — and **pair it with an independent adversarial verifier leg again**:
   that leg found the top defect (V1, the unimplementable AC-8) which the single-pass validate leg
   missed. Re-check specifically: the two-slot candidate/confirm invariant, the single budget-increment
   owner under a NON-mock gate, the fail-safe `apply_description` default, the `done`-step second
   mount, and that the SPEC `## Amendments` block and the plan's AC-1 row agree. After a
   PASS/accepted-CONDITIONAL contract, EXECUTE starts at checklist item **1.1** — and item 1.1's
   FIRST action is deriving the alembic head live with `DATABASE_URL` pinned to `localhost:5433`.
   Never run a bare alembic command in this repo.

---

## Validate Contract

Status: PASS
Date: 13-08-26
date: 2026-08-13
generated-by: outer-pvl
supersedes: 2026-08-13 (outer-pvl) — PVL cycle 5 CONDITIONAL contract; cycle 6 re-validate has current evidence

**Gate: PASS** — **0 FAILs, 0 CONCERNs.** The two open items from the cycle-5 contract (**C25**, the
only CONCERN, and nit **N16**) are both verified CLOSED against the plan text. Supplement cycle 6
applied exactly the two requested edits and nothing else; they contradict nothing.

This was a **scoped re-validate**, not a full V-sequence re-run. Cycles 2–5 already verified the rest
of the artifact; this pass re-read only the two edit sites, their referenced rules, and the
surrounding coherence surface. Gap trend across the loop: **13 → 22 → 17 → 6 → 1 → 0**. Three
consecutive FAIL-free cycles precede this one; no FAIL has been open since cycle 2.

Structural validator run in-session on the current file
(`node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs …`): **0 failures** — both
before and after this contract was written. The single advisory warning it emits is expected and not
a defect: the plan uses `✅ VERIFIED`, and §Phase Completion Rules already defines that marker as
requiring explicit **user confirmation** (the linter only checks that the phrase appears somewhere in
the artifact). Only FAIL output stops advancement; warnings are advisory.

---

### Cycle-6 closure verification (the only two items in scope)

| # | Verdict | Evidence |
|---|---|---|
| **C25** — the C21 message-derivation rule had no gate that could fail on the defect C21 named | **CLOSED** | New gate `test_message_derivation_truth_table` is specified in checklist **1.15** (`PLAN:809-826`) and carries a matching **§Verification Evidence** row (`PLAN:1038`). Four checks, all satisfied: **(a)** all four `(allowed, derived-status)` cells are asserted — (i) `allowed=false` + `ready`/`none` ⇒ cap copy, (ii) `allowed=false` + `failed` ⇒ cap copy, (iii) `allowed=true` + `failed` ⇒ generic copy, (iv) `allowed=true` + `ready` ⇒ `null`; **(b)** cell (i) is explicitly required on the **`GET`** *and* on the **`POST` capped response body** — the exact cell no prior gate covered; **(c)** the **discriminating purpose is stated in the plan text**, not left implicit: "Purpose of this gate: it MUST fail against a pre-C21 status-switch implementation" (`PLAN:813`); **(d)** the two sites agree with each other and with the rule they gate (`PLAN:205-220`, the single definition) — same four cells, same copy strings, same `GET`+`POST` requirement. Mechanism is feasible and repo-consistent: `allowed` is driven by pre-setting the raw counter key `site_analysis:count:{site_id}:{YYYYMMDD}` (established at `PLAN:575`, already used by `test_budget_counter_delta_is_one_per_post_cycle` at `PLAN:757`), status by writing the `sites` row directly; the message is asserted on the **response**, never on the DB row (VF1). Anti-duplication is handled: extending `test_budget_exhaustion_returns_capped_response_no_extra_runs` instead is allowed **only if all four cells end up asserted**, with "do not write two overlapping gates" stated inline (`PLAN:823-826`) and matching E21. |
| **N16** — §Verification Evidence's panel `none`-state row was narrower than the C22 rule | **CLOSED** | `PLAN:1039` now reads "`status` null/`\"none\"` with both slots empty — **and any row with both slots empty whatever its status, incl. `status=\"ready\"` after a `promote:false` dismiss (C22)**". This matches, word for word in substance: the C22 emptiness-before-status rule (`PLAN:884-891`), the panel `none` bullet (`PLAN:905-914`), this contract's Test-gates row `AC-8 (pre-existing sites)`, and the TDD stub. All four now say the same thing; the drift the nit flagged is gone. |

**Scope discipline:** no other finding was opened this cycle. The two edits touch two lines/blocks
and introduce no new claim requiring proof. Nothing else in the artifact was re-litigated, and no
new finding is manufactured to justify another cycle.

---

### Coherence sweep of the two edits

| Check | Verdict | Detail |
|---|---|---|
| Truth-table gate vs the single `message` definition | **COHERENT** | `PLAN:205-220` states the precedence as three top-down rules; the gate's four cells are exactly that precedence's truth table (rule 1 covers cells (i)+(ii), rule 2 cell (iii), rule 3 cell (iv)). No fifth cell, no contradiction. |
| Truth-table gate vs the three call sites | **COHERENT** | `GET` (`:205-220`), `POST` (`:289-292`, "`message` is NOT restated here … Do not re-derive it in the `POST` handler"), panel 3.3 (`:905-914`, renders the server string verbatim). The gate asserts against `GET` and `POST` responses — the two server surfaces — and never against the DB row. |
| Truth-table gate vs the existing message gates | **NO OVERLAP CONFLICT** | `test_budget_denied_run_does_not_linger_pending` (`:792-796`) and `test_budget_denied_run_sets_terminal_failed_with_message` (`:1037`) both exercise the `failed` row = cell (ii)/(iii); the new gate adds the non-`failed` cell they structurally cannot reach. `PLAN:823-826` + E21 forbid writing a second overlapping gate. |
| Truth-table gate vs mock mode | **SOUND** | The gate needs no mock-OFF override: the capped `POST` returns before any task fires and the `GET` derivation is independent of mock, so the module's autouse `mock_external_apis=True` fixture (`PLAN:735-746`) is harmless here. Correctly, the gate does not claim the N15/E20 mock-OFF treatment — that requirement stays scoped to the two counter gates that actually need it. |
| N16 edit vs C22 / D17 / panel / stub | **COHERENT** | Four statements of the same rule, now aligned (`:109` D17, `:884-891` checklist 3.3, `:1039` evidence row, TDD stub). §Public Contracts render rule (`:195-204`) unchanged and still agrees. |
| Residual-claim check | **CLEAN** | No text anywhere in the plan body still describes C25 or N16 as open; every remaining mention sits inside the superseded cycle-5 contract text, which this contract replaces. |

---

### Net gate derivation

| Layer 1 dimensions | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | PASS |
| Breaking changes | PASS |
| Security surface | PASS |

| Layer 2 sections | Status |
|---|---|
| §Public Contracts (3 endpoints, `SiteProfile`, message derivation, render rule) | PASS |
| Block 1 — Backend (migration → service → endpoints → budget) | PASS |
| Block 2 — Segmenter pre-seed verification | PASS |
| Block 3 — Frontend panel + insertion points | PASS |
| §Verification Evidence + §Test Infra Notes | PASS |
| SPEC ↔ plan AC reconciliation (14 ACs, A-1 amendment) | PASS |

**Totals: 0 FAILs / 0 CONCERNs / 10 PASSes**

**→ Net Gate: PASS**

**Vacuous-green check (mandatory):** every developed behavior in the blast radius has at least one
Fully-Automated or Hybrid gate; no behavior rests on Known-Gap alone. The cycle-5 exception is now
closed: the message-derivation precedence — the one developed behavior whose distinguishing cell had
no gate at any tier — is proven by `test_message_derivation_truth_table`, which is written to **fail**
against the wrong implementation rather than merely pass against the right one. AC-14 (Agent-Probe,
`needs-live-provider`) and the five Clerk-blocked Playwright legs each retain a Fully-Automated
backend counterpart, so no AC rests on a Hybrid or Agent-Probe leg alone. This PASS is not vacuously
green.

---

### Dimension findings

- **Infra fit: PASS** — 3 endpoints land in the existing `/api/v1/sites` router after
  `detect_platform_endpoint`; the fire helper mirrors `events.py:558-570`; the task opens its own
  `async_session`; all outbound fetching funnels through `site_content.fetch_site_content`
  (`pinned_client` + `safe_get`). Runner is this machine's `.venv/bin/python3.11 -m pytest` (the
  `.venv/bin/pytest` shebang is broken); PG on `localhost:5433` confirmed LISTENING.
  `DATABASE_URL` pinning is mandated at every DB touchpoint (E1/E2/R8) against the standing
  Supabase-PROD `.env` hazard.
- **Test coverage: PASS** (was CONCERN in cycle 5) — 31 Fully-Automated gates, 7 Hybrid (5
  Clerk-blocked Playwright + the live migration round-trip), 1 Agent-Probe, 0 Known-Gap-only
  behaviors. Every vacuous-gate hardening this loop produced is present: the five on the
  counter-delta gate, the transport backstop, the consumer-binding patch targets, the terminal-`ready`
  assertion, the explicit mock-OFF override with assert-first (E20/N15), the C23 post-settle leg, and
  now the C25 four-cell message truth table with its stated must-fail purpose.
- **Breaking changes: PASS** — additive only. Five nullable columns; three new endpoints; no existing
  response shape changes; `PlatformDetectResponse` explicitly unmodified and diff-gated;
  `platform_detector.py` and `schemas/sites.py` are edit-forbidden (E11) with empty-diff gates at
  every checkpoint. `site_analysis_enabled` ships **False**.
- **Security surface: PASS** — three of six high-risk classes present (public API contract, schema
  migration, trust boundary: SSRF + two prompt-injection boundaries). SSRF closed at one choke point
  with a no-request-issued gate; per-field `clean_text` + fence mandated (the `sanitize_profiles`
  fixed-field-table limitation named); competitor domains nulled unless scheme AND hostname both
  pass, rendered as plain text only; logging is keys/ids/counts only. Residuals named and unchanged
  (see Open gaps).
- **§Public Contracts feasibility: PASS** — mechanically implementable; every anchor matchable
  (`await db.refresh(site)` disambiguated to `create_site` by E4); highest-risk edit is the `POST`
  handler (in-flight guard order + fire path + no-increment), fully specified.
- **Block 1 feasibility: PASS** — highest-risk edit is the migration (E1/E2/E16: live head, pinned
  DSN, five columns, round-trip).
- **Block 2 feasibility: PASS** — verify-only, no production code change.
- **Block 3 feasibility: PASS** — highest-risk edit is 3.3's branch ordering, specified
  emptiness-first with E19 as the execute-side restatement.

---

### FAILs

**None.** No FAIL has been open since cycle 2.

### CONCERNs

**None.** C25 — the last one — is closed above.

### Nits

**None open.** N16 is closed above.

---

### Parallel strategy

7-signal score: **5/7** — S1 multi-package (apps/api + apps/web + tests), S2 schema/API surface,
S3 (3 blocks), S6 high-risk classes present, S7 blast radius ≫ 5 files. S4 absent (single COMPLEX
plan, not a phase program). Dominant signal: **S6 + S2**.

- **This validate pass:** sequential, 1 agent (opus). Correct — a two-item scoped closure check on
  one artifact; a fan-out would re-read 1,862 lines N times to verify two edits. Cost guard not
  triggered (1 agent).
- **Recommended for EXECUTE (full 4-option suite, per phase-END rule):**

  | Strategy | Agent count | Fit |
  |---|---|---|
  | **Sequential (recommended)** | 1 `vc-execute-agent` (opus), 3 block gates + final regression | Blocks are strictly ordered (migration → service → endpoints → panel); Block 3 is written against Block 1's exact response shape; one plan, one contract, one EVL pass. |
  | Parallel subagents | 2 (backend / frontend) | Rejected: the panel depends on the endpoints' exact shape and both halves share one regression baseline — fire-and-forget legs cannot reconcile a mid-flight contract correction. |
  | Workflow | ~6 steps × 1 | Overkill for 3 ordered blocks with a known item count. |
  | Agent team | 3 members × 2 rounds | Rejected: no mid-run cross-talk needed once the contract is fixed; cost unjustified. |
  | **EVL (after EXECUTE, mandatory)** | 1 `vc-tester` (opus) | Independent confirmation run of this contract's gate commands. Execute-agent's own green claim never substitutes for it. |

---

### Plan updates applied

**None by this contract.** C25 and N16 were closed by supplement cycle 6 before this pass ran (two
anchored edits, verified above). This validate-agent edited only its own contract section and the
goal block's next-phase / validate-contract annotation lines.

---

### Execute-agent instructions

Binding now that the gate is PASS. **E1–E20 carry forward unchanged** from prior cycles and remain in
force verbatim; they are also stated in the plan body, and where the two agree the plan body wins on
any future divergence (E17).

| # | Instruction | Trigger condition |
|---|---|---|
| E21 (restated, now plan-backed) | **Prove the message precedence over all four cells, not just the `failed` one — and write it exactly once.** The plan now specifies `test_message_derivation_truth_table` (checklist 1.15 + §Verification Evidence): follow the plan text, do **not** write a second overlapping gate, and do **not** narrow it to the `failed` row. Non-negotiable content: with the counter exhausted, the cap copy "Daily analysis limit reached — try again tomorrow" must be asserted on a **non-`failed`** row on BOTH the `GET` **and** the `POST` capped response body; with the counter available, a `failed` row must carry the generic copy and a `ready` row must carry `null`. Assert on the response, never on the DB row (VF1). A gate that exercises only the `failed` row passes under the pre-C21 status-switch reading E17 forbids — the F5/C20 vacuity mechanism. Write this gate RED first and confirm it fails against a status-switch implementation before making it green. | Checklist 1.15 (`::test_message_derivation_truth_table`) |

---

### Test gates

C3 5-column table. Commands are canonical per `process/context/tests/all-tests.md` §Commands, adapted
to this machine's runner (`.venv/bin/python3.11 -m pytest`; the `.venv/bin/pytest` shebang is broken).
**Every command below is currently unproven** — no gate has been run; all are `B` (built by this
plan's checklist) unless marked.

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-1 (async half) | Fetch + text extraction works and never raises; failures return `ok=False` | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_site_content.py -m unit -q` | B |
| AC-1 (sync half) | Site step stays platform-detect only; Continue never gated — **matches AC-1 v2 as amended in the SPEC's `## Amendments` A-1** | Fully-Automated | `git diff --stat apps/api/services/platform_detector.py apps/api/schemas/sites.py` empty | B |
| AC-1 (UI) | Continue stays enabled while detect-platform is in flight | Hybrid | Playwright leg in `apps/web/e2e/onboarding.spec.ts`; precondition: Clerk auth harness (`E2E_SITE_ANALYSIS` skip-guard) — **unmet, standing repo gap** | D |
| AC-2 | `create_site` starts the analysis and stamps `pending` | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_site_analysis_api.py::test_create_site_starts_analysis_pending -q` | B |
| AC-3 | Completed analysis persists on the Site row; pending → ready | Fully-Automated | `… ::test_full_lifecycle_pending_to_ready_persisted -q` | B |
| AC-4 | Failure and stale-pending both derive FAILED; wizard never blocked | Fully-Automated | `… ::test_failure_path_sets_failed ::test_stale_pending_derives_failed -q` | B |
| AC-5 | The user's edited profile is what is persisted, not raw AI output | Fully-Automated | `… ::test_put_edited_profile_overwrites_ai_values -q` | B |
| AC-5/AC-8 (two-slot invariant) | The task writes `site_profile_candidate` only; `GET` returns candidate and confirmed separately | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_site_analysis.py::test_task_writes_candidate_never_confirmed_profile -m unit -q`; `… tests/integration/test_site_analysis_api.py::test_get_returns_candidate_and_confirmed_separately -q` | B |
| AC-6 (server) | Confirm fills an empty description but never clobbers a user-typed one | Fully-Automated | `… ::test_confirm_fills_empty_description ::test_confirm_preserves_user_typed_description -q` | B |
| AC-6 (client) | Panel sends `apply_description=false` for non-empty **and for absent/undefined** `currentDescription`; `true` only when known-empty (`null` or `""`, D13/VC7 fail-safe) | Fully-Automated | Panel confirm-payload assertion across all **three** cases | B |
| AC-7 | Segmenter prompt carries the confirmed description + category — **end to end** | Fully-Automated | `… tests/integration/test_site_analysis_api.py::test_confirmed_profile_reaches_segmenter_prompt -q` (**primary**); `.venv/bin/python3.11 -m pytest tests/unit/test_site_analysis_segmenter_preseed.py -m unit -q` (interpolation complement only) | B |
| AC-8 | A re-run preserves the confirmed profile until `PUT` promotes the new candidate | Fully-Automated | `… ::test_rerun_lifecycle_preserves_prior_profile_until_confirm -q` | B |
| AC-8/AC-10 (in-flight) | A second `POST` while `pending` returns `already_running=true` — no increment, no `started_at` re-stamp, no second task — **and after the run settles a further `POST` is accepted again** (C23: the only gate proving the done-callback discard ran) | Fully-Automated | `… ::test_concurrent_post_while_pending_returns_already_running -q` | B |
| AC-8 (pre-existing sites) | A row with `site_profile_status = NULL` and both slots empty renders the `none` copy + an Analyze button, disabled when `budget.allowed === false`; **and so does any row with both slots empty whatever its status — including `status="ready"` after a `promote:false` dismiss of a first-ever candidate** (C22 emptiness-before-status; the plan-body evidence row now states this identically — N16 closed) | Fully-Automated | Panel `none`-state component assertion | B |
| AC-8 (UI) | Re-run button works from site settings | Hybrid | Playwright settings-dialog leg; precondition: Clerk auth harness — **unmet** | D |
| AC-5/AC-8 (render rule) | `(candidate ?? profile)` non-null renders the review UI even when `status === "failed"`, with the failure as a banner ABOVE it; the review UI is rendered **once**, by the render rule, never per status branch (C22b) | Fully-Automated | Panel render-rule component assertion (VC5) | B |
| AC-8 (dismiss) | `promote:false` NULLs the candidate and leaves profile / status / both timestamps / description / category byte-identical | Fully-Automated | `… ::test_put_promote_false_dismisses_candidate_only -q` | B |
| AC-4/AC-8 (`PUT` × in-flight) | A `PUT` mid-run writes the confirmed slot but leaves `status="pending"` + `started_at` untouched | Fully-Automated | `… ::test_put_during_pending_preserves_pending_status -q` | B |
| AC-5 (`PUT` × no candidate) | `PUT` with `candidate = NULL` / `status="none"` succeeds as the edit-the-confirmed-profile path | Fully-Automated | `… ::test_put_with_no_candidate_is_allowed -q` | B |
| AC-9 | Flag OFF ⇒ all three endpoints 404, no profile columns written, lanes at baseline | Fully-Automated | `… ::test_flag_off_endpoints_404_and_no_profile_written -q`; `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` and `.venv/bin/python3.11 -m pytest tests/ -m integration -q` vs the **E3-measured** baseline; `git diff --stat apps/pixel/` empty | B |
| AC-9 (web half) | Flag-off panel renders `null` after exactly one 404 `GET`, with no retry loop | Fully-Automated | Panel component assertion (N2 — flag-off is byte-identical on the BACKEND only) | B |
| AC-10 (end to end) | The counter moves **exactly once** per user-visible run across a full `POST` → task cycle | Fully-Automated | `… ::test_budget_counter_delta_is_one_per_post_cycle -q`, with all five C17/VF2 hardenings: `mock_external_apis=False` (overridden **inside the test body**, asserted as the first statement — E20/N15), `apps.api.services.site_analysis` **consumer bindings** patched, transport raising on any other outbound request, the delta window opened after the create-time task settles, and terminal `ready` asserted alongside `delta == 1` | B |
| AC-10 (per-layer) | Cap response is HTTP 200 with `budget.allowed=false`, never partial; task increments once per entry | Fully-Automated | `… ::test_budget_exhaustion_returns_capped_response_no_extra_runs -q`; `… tests/unit/test_site_analysis.py::test_budget_incremented_once_per_run -m unit -q` (**mock-OFF, same consumer bindings, terminal-`ready` asserted — C20**) — per-layer only, not sufficient alone | B |
| **AC-10/AC-4 (message precedence — C25, NOW CLOSED)** | The derived `message` follows the precedence over all four `(allowed, derived-status)` cells, not a status switch: `allowed=false` + **non-`failed`** row (`ready`/`none`) ⇒ cap copy on the `GET` **and** on the `POST` capped response; `allowed=false` + `failed` ⇒ cap copy; `allowed=true` + `failed` ⇒ generic copy; `allowed=true` + `ready` ⇒ `null`. **The gate must FAIL against a pre-C21 status-switch implementation** — that is its stated purpose in the plan | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_site_analysis_api.py::test_message_derivation_truth_table -q` — **specified in checklist 1.15 (`PLAN:809-826`) + §Verification Evidence (`PLAN:1038`)**. Execute-side binding: **E21** | B |
| AC-10/AC-4 (denial) | A budget-denied run terminates `failed` immediately (not after the 180 s stale window) and the **GET response** carries the derived cap copy; nothing is persisted | Fully-Automated | `… ::test_budget_denied_run_does_not_linger_pending -q`; `… tests/unit/test_site_analysis.py::test_budget_denied_run_sets_terminal_failed_with_message -m unit -q` | B |
| AC-11 | The whole flow runs keylessly and deterministically under mock, with **zero** outbound requests | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_site_analysis_api.py -q` with `monkeypatch.setattr(settings, "mock_external_apis", True)`; `… tests/unit/test_site_analysis.py::test_mock_profile_deterministic ::test_mock_mode_issues_zero_outbound_requests -m unit -q` (transport patched to raise) | B |
| AC-12 | Hostile site HTML and model output cannot escape the untrusted fence | Fully-Automated | `… tests/unit/test_site_content.py::test_adversarial_html_cannot_escape_fence`; `… tests/unit/test_site_analysis.py::test_prompt_builders_fence_every_field ::test_sanitize_profile_strips_injection_strings -m unit -q` | B |
| AC-12 (stored-injection) | A model-chosen `competitors[].domain` is nulled unless BOTH the scheme is in `{"", http, https}` AND the host matches the plain-hostname regex (`javascript:alert(1)` ⇒ `None`), and is never rendered as a link | Fully-Automated | `… tests/unit/test_site_analysis.py::test_sanitize_profile_nulls_invalid_competitor_domain -m unit -q` + the panel plain-text (never `<a href>`) assertion | B |
| AC-13 | No PII, prompt bodies, or profile text in any emitted log event | Fully-Automated | `… tests/unit/test_site_analysis.py::test_no_pii_or_prompt_bodies_in_logs -m unit -q` (structlog capture) | B |
| AC-14 | Grounded output on real sites is coherent and does not fabricate competitors | Agent-Probe | Manual grounded run against a documented site panel; `cost-class: needs-live-provider` (billed — **requires explicit user opt-in**, never auto-run) | D |
| C-2 (forward-compat) | Every persisted profile carries `meta.v == 1`, including the mock path | Fully-Automated | `… tests/unit/test_site_analysis.py::test_sanitize_profile_stamps_schema_version -m unit -q` | B |
| SEC-1 | The outbound fetch refuses metadata / loopback / private targets **without issuing a request** | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_ssrf_guard.py -m unit -q` with a new `test_fetch_site_content_refuses_metadata_without_fetch` beside its two siblings (`:82`, `:96`) | B |
| SEC-2 | Oversized response bodies are refused (`Content-Length` pre-check) or bounded (post-hoc truncation) | Fully-Automated | Unit test on the `Content-Length` pre-check + truncation path in `tests/unit/test_site_content.py` | B |
| MIG-1 | The migration applies and reverses cleanly with all **five** columns | Hybrid | `DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5433/postgres' .venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade head` → `downgrade -1` → `upgrade head`. Precondition: PG on 5433 (**confirmed LISTENING 13-08-26**) and `DATABASE_URL` pinned | B |
| WEB-1 | Web types and the panel compile and lint clean | Fully-Automated | `cd apps/web && npx tsc --noEmit`; `cd apps/web && npx next lint --file src/components/site-analysis-panel.tsx` | B |
| REG-1 | No new failures in either lane; pixel and the two protected backend files untouched | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q`; `.venv/bin/python3.11 -m pytest tests/ -m integration -q`; `git diff --stat apps/pixel/`; `git diff --stat apps/api/services/platform_detector.py apps/api/schemas/sites.py` | B |

gap-resolution legend: A — proven now; B — gate added by this plan's checklist; C — deferred to a
named later phase; D — backlog test-building stub (named residual, keep-active).

Legacy line form (retained for existing validate-contract consumers):
- backend service/extraction: `[Fully-automated: .venv/bin/python3.11 -m pytest tests/unit/test_site_content.py tests/unit/test_site_analysis.py -m unit -q]`
- backend API lifecycle: `[Fully-automated: .venv/bin/python3.11 -m pytest tests/integration/test_site_analysis_api.py -q]`
- budget end-to-end: `[Fully-automated: .venv/bin/python3.11 -m pytest tests/integration/test_site_analysis_api.py::test_budget_counter_delta_is_one_per_post_cycle -q — mock OFF asserted first, site_analysis consumer bindings patched, transport raises, terminal ready asserted]`
- message precedence (C25, closed): `[Fully-automated: .venv/bin/python3.11 -m pytest tests/integration/test_site_analysis_api.py::test_message_derivation_truth_table -q — all four (allowed, status) cells; cap copy on a NON-failed row on BOTH the GET and the POST capped response; must fail against a status-switch implementation]`
- migration: `[hybrid: alembic upgrade/downgrade/upgrade + precondition: PG on localhost:5433 AND DATABASE_URL pinned]`
- sync-path non-regression: `[Fully-automated: git diff --stat apps/api/services/platform_detector.py apps/api/schemas/sites.py must be empty]`
- regression lanes: `[Fully-automated: .venv/bin/python3.11 -m pytest tests/unit -m unit -q; .venv/bin/python3.11 -m pytest tests/ -m integration -q — vs an EXECUTE-start-measured baseline]`
- web: `[Fully-automated: npx tsc --noEmit; npx next lint --file src/components/site-analysis-panel.tsx]`
- onboarding UI legs: `[hybrid: Playwright, E2E_SITE_ANALYSIS skip-guard + precondition: Clerk auth harness — unmet]`
- grounded quality: `[agent-probe: manual real-site panel, needs-live-provider]`

**Failing stubs (Fully-Automated rows only — TDD red-first starting points for EXECUTE):**

```
test("should refuse metadata and loopback targets without issuing a request", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: fetch_site_content refuses 169.254.169.254 and localhost with ok=False and zero outbound requests")
})
test("should derive FAILED from a stale pending row without mutating the row", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: derive_status truth table incl. backdated site_profile_started_at")
})
test("should increment the analysis counter exactly once across a full POST to task cycle", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: mock OFF asserted first, site_analysis consumer bindings patched, transport raises, Redis delta == 1 AND run reaches terminal ready")
})
test("should derive the cap copy on a non-failed row whenever the budget is exhausted", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: C25 message precedence truth table — allowed=false + ready/none => cap copy on GET and on the POST capped response; allowed=false + failed => cap; allowed=true + failed => generic; allowed=true + ready => null; MUST fail against a status-switch implementation")
})
test("should write only site_profile_candidate from the task and never the confirmed profile", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: V1 two-slot invariant, including the mock and first-ever-run paths")
})
test("should return already_running and fire no second task when a POST arrives while pending", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: D12 in-flight guard, started_at unchanged, counter unchanged, and a further POST accepted after the run settles (C23 discard proof)")
})
test("should terminate a budget-denied run as failed immediately and derive the cap copy on GET", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: C15 no lingering pending, VF1 message never persisted")
})
test("should return 404 from all three endpoints when the flag is off and write no profile columns", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: flag-off 404 + create_site writes no site_profile columns")
})
test("should preserve a user-typed description when apply_description is false", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: AC-6 no-silent-overwrite, both server branches")
})
test("should send apply_description false when currentDescription is non-empty or undefined", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: AC-6 client half, D13 fail-safe, all three cases")
})
test("should carry the confirmed description and category into the segmenter prompt end to end", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: create empty -> ready under mock -> PUT confirm -> prompt assembly")
})
test("should keep the untrusted fence intact against adversarial site HTML", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: forged </untrusted_visitor_data> close tag cannot escape")
})
test("should null an invalid competitor domain and never render it as a link", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: VC8 positive scheme plus hostname check, javascript: case, plain-text rendering")
})
test("should stamp meta.v equal to 1 on every persisted profile including the mock path", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: V8 JSONB schema version")
})
test("should emit no prompt bodies, extracted text, or profile text in any log event", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: structlog capture across started/complete/failed")
})
test("should produce an identical profile on two mock-mode runs with zero outbound requests", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: mock determinism AND transport patched to raise on any request")
})
test("should refuse or bound an oversized response body", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: Content-Length pre-check plus post-hoc truncation, per C11")
})
test("should render nothing and fire exactly one request when the flag is off", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: N2 web flag-off, 404 yields null with no retry loop")
})
test("should render the none state whenever both profile slots are empty, whatever the status says", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: C22 emptiness-before-status, incl. status=ready after a promote:false dismiss")
})
test("should render the review UI above a failed banner whenever candidate or profile is present", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: VC5 render rule owns the review UI once, status branches contribute banners only")
})
test("should leave profile, status, timestamps, description and category untouched on a promote false PUT", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: VC9 dismiss-only path")
})
test("should keep status pending and started_at untouched when a PUT lands mid-run", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: C18/VC4, stale-derivation and cross-process in-flight check still work afterwards")
})
```

---

### High-risk pack

Required before this work is finalized — 3 of the 6 high-risk classes are present: **public API
contract change** (3 new endpoints; no change to any existing response shape), **schema migration**
(5 additive nullable columns), **permission / trust-boundary logic** (server-side fetch of a
user-supplied URL = SSRF surface; two LLM prompt-injection boundaries).

Manual-first evidence pack, colocated in this task folder at
`process/features/onboarding-canary/active/site-analysis-onboarding_13-08-26/harness/`:
`risk-gate.json`, `context-snippets.json`, `verification.json`, `review-decision.json`,
`adversarial-validation.json` (required here — the SSRF and prompt-injection paths are
attack-sensitive). Do not treat the work as ready to finalize until the pack exists and the reviewer
decision is recorded; if it is missing, say so explicitly rather than implying the work is proven.

---

### Backlog artifacts to create during durable capture

| Artifact | Location | What it tracks |
|---|---|---|
| `site-analysis-grounded-quality-probe_NOTE_13-08-26.md` | `process/features/onboarding-canary/backlog/` | AC-14 Agent-Probe residual — grounded coherence / no-fabrication panel run; `cost-class: needs-live-provider`, requires explicit user opt-in |
| `site-analysis-e2e-auth-harness_NOTE_13-08-26.md` | `process/features/onboarding-canary/backlog/` | The `E2E_SITE_ANALYSIS`-guarded Playwright legs, blocked on the standing repo-wide Clerk auth-harness gap (same class as `E2E_PRIVACY_HOLD_VISITOR`) |
| `platform-detector-uncovered_NOTE_13-08-26.md` | `process/features/onboarding-canary/backlog/` | Pre-existing: `detect_platform` scoring, the 403-header branch, the Shopify API probe and GTM extraction have **zero** behavioral test coverage; `_probe_shopify_api` (`platform_detector.py:223`) uses a bare client. Explicitly NOT inherited or altered by this plan |
| `conftest-mock-external-apis-fixture_NOTE_13-08-26.md` | `process/features/onboarding-canary/backlog/` | `tests/conftest.py` pins `DATABASE_URL`/`REDIS_URL`/`GEMINI_API_KEY` but not `MOCK_EXTERNAL_APIS`; and there is no repo-wide "mock the network but not the business logic" helper, so every side-effect gate hand-rolls its patching (the F5/C17/C20 class) |
| `web-component-unmount-test-gap_NOTE_13-08-26.md` | `process/features/onboarding-canary/backlog/` | No test in `apps/web` exercises a component across a wizard step transition, so "the component unmounted before its async result arrived" (V5/R12) is a defect class the web test surface cannot see. The install→done second mount is a *new component instance*, so any un-confirmed editor edits are discarded at the transition — same blind spot, different symptom |

---

### Open gaps

**No FAILs and no CONCERNs.** All cycle-1 (F1–F4) and cycle-2 (F5–F6) FAILs remain verified CLOSED
against live source, as do all cycle-3 CONCERNs (C16–C20), all twelve second-verifier findings
(VF1–VF3, VC4–VC9, N10–N12), all four cycle-4 CONCERNs (C21–C24) with nits N13–N15, and now cycle-5's
C25 and N16.

**ACCEPTED named residuals, recorded for the record (design decisions already accepted in the plan —
each is a named residual with written justification, not a silent gap; none blocks the gate):**

| Residual | Where | Why accepted |
|---|---|---|
| **R11** — budget check→increment TOCTOU | `PLAN:475`, LOW — ACCEPTED | Best-effort free-tier guard, not a billing meter; closing it would need a lock on a 3/day counter. |
| **R13** — message misattribution: a non-budget failure while the counter is exhausted reports the **cap** copy | `PLAN:476` + `PLAN:223-227`, LOW — ACCEPTED, "do NOT fix during EXECUTE" | Distinguishing the two requires persisting the failure reason — the sixth column D15 deliberately avoids. The alternative precedence ordering is strictly worse. |
| **Clerk-blocked Playwright legs** (AC-1/2/4/5/8 UI halves) | Hybrid, gap-resolution **D**, backlog stub above | Standing repo-wide auth-harness gap (same class as `E2E_PRIVACY_HOLD_VISITOR`). Every one has a Fully-Automated backend counterpart, so no AC rests on a Hybrid leg alone. **CONDITIONAL status on these legs specifically; unchanged from prior cycles.** |
| **AC-14 grounded-quality probe** | Agent-Probe, `cost-class: needs-live-provider`, gap-resolution **D**, backlog stub above | Billed live-provider run; requires explicit user opt-in, never auto-run. |
| **Chunked response with no `Content-Length`** is buffered in full before it can be refused | C11 | SEC-2 proves the `Content-Length` pre-check plus post-hoc truncation; the no-header chunked case is bounded only after buffering. |
| Redis-down fail-open to `used = 0` | repo-wide posture, matching `get_osint_usage` | Consistent with the existing meter posture; the cap is absent for the duration of an outage. |
| Unauthenticated 401-before-404 flag-off oracle (N1); the web panel's one flag-off `GET` (N2) | named in the plan | Accepted, honest-scope-noted. |

**Pre-existing, explicitly not inherited:** `detect_platform` has zero behavioral test coverage and
`_probe_shopify_api` (`platform_detector.py:223`) uses a bare client. Out of scope; both files are
diff-gated and recorded in a backlog note.

### What this coverage does NOT prove

- `pytest tests/unit -m unit -q` / `tests/ -m integration -q` prove no *test-visible* regression only.
  They do not exercise `detect_platform` at all, so any future edit to that module stays invisible to
  every lane (it is protected here only by a diff gate).
- The `git diff --stat` gates prove those two files were not **edited**. They do not prove nothing
  *depends* on them: the read-only `BROWSER_HEADERS` import leaves the diff empty while creating a
  real coupling.
- `tests/unit/test_ssrf_guard.py` proves the guard rejects known-bad targets. It does **not** prove the
  DNS-rebinding TOCTOU window is closed on the new path (no test performs a mid-flight re-resolve), and
  SEC-2 proves only a `Content-Length` pre-check plus truncation — a chunked response with no
  `Content-Length` is still buffered in full before it can be refused.
- `tests/integration/test_site_analysis_api.py` under mock proves the state machine and persistence. It
  does **not** prove the real grounded Gemini path: real latency (~120 s worst case against the 180 s
  stale threshold and 240 s poll cap), real token consumption, real 429/quota behavior, or that the
  grounded model returns a structurable prose shape at all.
- `test_budget_counter_delta_is_one_per_post_cycle` proves the counter **arithmetic** across a full
  cycle, and — with the five C17/VF2 hardenings — that it did so offline. It does **not** prove the
  budget holds when Redis is unavailable: the helper fails open to `used = 0`, so the cap is absent
  for the duration of an outage, and no gate exercises that path.
- `test_message_derivation_truth_table` proves the derivation follows the **precedence** over all four
  `(allowed, derived-status)` cells and would fail a status-switch implementation. It does **not**
  distinguish a budget denial from an unrelated failure that happened while the counter was exhausted
  (**R13**) — by construction, since nothing records the cause. It also asserts only the two server
  surfaces (`GET`, `POST`); that the panel *displays* the returned string verbatim is covered by the
  panel assertions, not by this gate.
- The in-flight gate proves both that a second `POST` during `pending` is refused **and** that the
  guard is released after the run settles (C23). It does **not** prove cross-process behavior: the
  `_analysis_inflight` set is per-process, and the cross-process half rests on the derived-`pending`
  check alone, which no gate exercises across two workers.
- The two-slot and panel gates prove the task never writes `site_profile`, that `PUT` promotes and
  NULLs the candidate, that a mid-run `PUT` preserves `pending`, that `promote:false` dismisses only,
  and (with the now-aligned C22 wording) that both-slots-empty renders `none` whatever the status.
  They do **not** prove the review UI is *structurally* rendered once rather than duplicated per
  branch — that is a code-shape property E19 binds but no assertion can see.
- The AC-12 fence tests prove *known* injection strings cannot escape. They do **not** prove fence
  integrity against unicode/homoglyph or multi-byte breakout attempts, nor that the grounded model
  ignores instructions it read from the live web via its own search tool — a channel entirely outside
  the fence.
- The migration round-trip on `localhost:5433` proves the DDL is reversible on a local dev DB. It does
  **not** prove a production apply on Supabase, nor behavior against non-empty `sites` rows at
  production row counts.
- `npx tsc --noEmit` proves types compile. It does **not** prove the polling hook is leak-free across
  the install→done transition and remount, that un-confirmed editor state survives that remount (it
  does not — the second mount is a new component instance), nor that the panel survives a canary
  phase-2-4 rewrite of `install-step.tsx`. That whole defect class (V5/R12) has no automated web gate.
- The AC-6 client assertion proves the panel sends the right boolean for all three
  `currentDescription` states. It does **not** prove the onboarding call site actually supplies a real
  value after a reload — by design (D13 makes correctness independent of it), but the enhancement
  itself is unproven.
- **Nothing in this contract has been RUN.** Every gate is `B` — specified, not executed. PASS means
  the plan is executable and its gate set is non-vacuous, not that the feature works.

### Accepted by

**Gate is PASS — no CONCERN required acceptance, and this agent accepted nothing on the user's
behalf.** C25 was closed by a plan edit, not by acceptance.

Residuals listed under Open gaps (**R11**, **R13**, the Clerk-blocked Hybrid Playwright legs, the
AC-14 Agent-Probe grounded-quality run, the chunked/no-`Content-Length` buffering case, Redis-down
fail-open, N1/N2) were **already accepted in the plan body as recorded design decisions in earlier
cycles**; they are re-listed here for the record and are not re-litigated. Each carries a written
justification and, where applicable, a backlog test-building stub. None is a silent gap and none
blocks the gate.

Note for the orchestrator: `results.tsv` holds a header + baseline + **9** cycle rows
(`wc -l` = **11** ≥ 3), and this gate is PASS, so both condition (a) and condition (b) of the
VALIDATE → EXECUTE gate are mechanically satisfied. This cycle-6 re-validate row is not yet written;
the orchestrator owns the TSV and the per-cycle iteration report.

---

## Autonomous Goal Block

```
SESSION GOAL: Auto site analysis at onboarding Add-Site (site-analysis-onboarding) — platform detect only at the site step (the content read moved to the async run, SPEC Amendments A-1), async grounded AI company-profile/ICP/competitor analysis, editable review panel, JSONB profile on sites, flag site_analysis_enabled OFF by default.
Charter + umbrella plan: N/A — single COMPLEX plan (not a phase program).
Reference for latest state: process/features/onboarding-canary/active/site-analysis-onboarding_13-08-26/site-analysis-onboarding_PLAN_13-08-26.md
Autonomy: PVL supplement cycles run without user approval (feedback_autonomous_phase_execution). CONDITIONAL -> apply fixes and proceed. BLOCKED -> backlog note + continue. Subagent delegation stays mandatory; the orchestrator never edits source or runs gate commands itself.
Hard stop conditions / safety constraints:
- Never run a bare alembic (or DB-script) command. The repo .env points at Supabase PRODUCTION and migrations/env.py has no local-host guard. Always pin DATABASE_URL to localhost:5433 first.
- Never flip site_analysis_enabled to true. It ships False; flipping it is a separate operator action after the migration is live.
- Never construct a bare httpx client for a user-supplied URL. All outbound fetching goes through the single site_content.fetch_site_content choke point.
- Never log prompts, extracted page text, grounded prose, or the profile. Keys, ids and counts only.
- The AC-14 grounded-quality probe is billed (needs-live-provider). Requires explicit user opt-in; do not auto-run.
- Do not touch apps/pixel/. `git diff --stat apps/pixel/` must stay empty.
Next phase: EXECUTE. PVL cycle 6 (scoped re-validate) returned **Gate: PASS — 0 FAILs, 0 CONCERNs**. The two open cycle-5 items are CLOSED: C25 (checklist 1.15 + Verification Evidence now specify `test_message_derivation_truth_table` — all four (allowed, derived-status) cells, cap copy required on a NON-failed row on BOTH the GET and the POST capped response, with the discriminating purpose stated in the plan: it MUST fail against a pre-C21 status-switch implementation) and N16 (the panel none-state evidence row now covers any row with both slots empty whatever its status, incl. status="ready" after a promote:false dismiss). The two edits contradict nothing — the message rule's three call sites, the C22 emptiness-before-status rule and the existing failed-row message gates all remain coherent, and no second overlapping gate is introduced. Validator 0 failures / 0 warnings. Gap trend 13->22->17->6->1->0; four consecutive FAIL-free cycles. ACCEPTED named residuals carried into EXECUTE (previously accepted in the plan, not re-litigated): R11 budget check->increment TOCTOU; R13 message misattribution on a non-budget failure while the counter is exhausted (do NOT "fix" during EXECUTE); the five Clerk-blocked Hybrid Playwright legs (CONDITIONAL, each with a Fully-Automated backend counterpart); AC-14 grounded-quality Agent-Probe (needs-live-provider, explicit opt-in only); the chunked / no-Content-Length full-buffering case (C11). Every gate is still unproven (B) — PASS means the plan is executable and its gate set non-vacuous, not that the feature works.
Validate contract: inline in plan (## Validate Contract) — Gate: PASS, generated-by: outer-pvl, date 2026-08-13, PVL cycle 6, supersedes the cycle-5 CONDITIONAL contract. Accepted by: n/a — PASS, no CONCERN required acceptance; named residuals were accepted in earlier cycles and are re-listed for the record.
Execute start: measure both lane baselines first (.venv/bin/python3.11 -m pytest tests/unit -m unit -q; .venv/bin/python3.11 -m pytest tests/ -m integration -q), then checklist item 1.1 — derive the alembic head LIVE with DATABASE_URL pinned to localhost:5433. Strategy: sequential, 1 vc-execute-agent (opus), 3 block gates + final regression; EVL afterwards is a mandatory independent vc-tester run of this contract's gate commands. High-risk pack: yes (public API contract + schema migration + SSRF/prompt-injection trust boundary).
```
