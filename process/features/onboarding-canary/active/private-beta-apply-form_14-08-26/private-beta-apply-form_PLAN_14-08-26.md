---
name: plan:private-beta-apply-form
description: "Re-arm getbeam private beta (invite-only) behind a public /apply form, admin-reviewed, feeding the existing invite-token flow"
date: 14-08-26
feature: onboarding-canary
---

# PLAN — Private Beta Apply Form (COMPLEX)

## TL;DR
Six sections: (A) additive-nullable schema + migration (**7** nullable columns incl. `plan_interest`), (B) extend the zero-caller intake endpoint, (C) new public `/apply` React route, (D) admin waitlist UI surfaces the new fields, (E) rewire **7 static CTAs + 4 React pricing CTAs**, (F) invite-gate hardening (incl. the invite-URL/query-drop fix that makes AC-13 reachable at all) + operator flip. Nothing is enabled until the CTAs are rewired and `INVITE_ONLY=true` is set by an operator.

Related SPEC: `private-beta-apply-form_SPEC_14-08-26.md` (same task folder). Locked decisions and 14 ACs live there; this plan does not restate them.

---

## Plan Metadata

- **Date**: 14-08-26
- **Status**: PLANNED — not validated, not executed
- **Complexity**: COMPLEX
- **Feature**: onboarding-canary

## Overview / Context

getbeam currently allows uncontrolled account creation. This plan re-arms invite-only mode behind a public `/apply` form: applicants submit 8 fields, an admin reviews them in the existing dashboard waitlist page, and approval hands off to the **unchanged** invite-token flow. The `/onboarding` canary demo stays fully public so the aha-before-commit funnel survives. All code lands inert; nothing changes for users until the 6 CTAs are rewired (Section E) and an operator sets `INVITE_ONLY=true` (Section F.5).

## Implementation Checklist

1. Section A — add 6 nullable columns to `WaitlistSignup`; write and round-trip the additive-nullable migration off the live head.
2. Section B — extend `WaitlistRequest` and `join_waitlist` to sanitize, coerce, persist, and backfill the new fields; enrich the admin notify email.
3. Section C — create the public `/apply` route, add it to `isPublicRoute`, add the typed client method and types.
4. Section D — return the new fields from `list_waitlist` and render them in the admin waitlist page.
5. Section E — repoint the 5 `index.html` account-creation CTAs and the `onboarding-steps.js` end CTA at `/apply`.
6. Section F — pin the invite email at sign-up, make the invite-gate 403 legible, add the 2 missing invite-gate unit tests.
7. Run the Verification Evidence gates for each section as it completes (per-section, not batched to the end).
8. Hand the operator runbook (F.5) to a human — agents stop before the flag flip.

## Acceptance Criteria

The 14 acceptance criteria are **locked in the SPEC** (`private-beta-apply-form_SPEC_14-08-26.md`, AC-1 … AC-14) and are not restated here. Each is mapped to its proving gate in the `## Verification Evidence` table below via the `Proves SPEC criterion` column. Every AC has at least one named gate; AC-9 (production half) and AC-12 are Agent-Probe only and are recorded as known gaps with backlog stubs.

## Phase Completion Rules

- A section is **CODE DONE** when its edits are applied and its Fully-Automated gates exit 0.
- A section is **VERIFIED** only when its Fully-Automated *and* Hybrid gates are green, and any Agent-Probe gate has been run and its judgment recorded.
- A gate whose only strategy is Known-Gap never yields a PASS. AC-12 stays **CONDITIONAL** until either its probe is recorded or the Clerk Playwright harness lands.
- No section may be marked VERIFIED on the strength of a flag-off no-op. Sections A–D are inert until E and F.5, so their gates must exercise the code paths directly, not observe absence of change.
- The plan as a whole cannot be archived while `INVITE_ONLY` remains unflipped — the correct terminal state until then is "code-complete, operator step pending".

## Touchpoints

### Changed

| File | Change |
|---|---|
| `apps/api/models/waitlist.py` | +6 nullable columns on `WaitlistSignup` |
| `apps/api/migrations/versions/{new}.py` | NEW — additive-nullable migration |
| `apps/api/routers/demo.py` (`WaitlistRequest`, `join_waitlist`, ~L773-880) | extend request model + persist/backfill new fields; sanitize free text; enrich admin notify email |
| `apps/api/routers/waitlist.py` (`list_waitlist`, ~L43-79) | return the new fields (+ `x_handle`, currently omitted) |
| `apps/api/routers/waitlist.py` (`invite_url`, ~L194) | **CLOSES FAIL-A.** `https://getbeam.fyi/signup?invite={token}` -> `/sign-up?invite={token}`. Scoped deviation from the SPEC's "email templates out of scope": a one-line URL constant, not a template redesign, and without it the token never reaches the only page that stashes it. |
| `apps/web/src/app/signup/page.tsx` (~L30) | **CLOSES FAIL-A.** `router.replace("/sign-up")` drops the query string; preserve it so a hand-typed or legacy `/signup?invite=...` still delivers the token. |
| `apps/web/src/app/pricing/page.tsx` (L96, 102, 134, 280) | **CLOSES FAIL-B.** 4 account-creation CTAs repointed `/signup` -> `/apply`, preserving plan intent as `?plan=...`. |
| `apps/web/src/app/sitemap.ts` (`staticRoutes`, L15-19) | + `/apply` entry (NIT-5) |
| `apps/web/src/app/apply/page.tsx` | NEW — public application form |
| `apps/web/src/middleware.ts` (`isPublicRoute`) | + `"/apply(.*)"` |
| `apps/web/src/lib/api.ts` | + `submitApplication()` typed client method |
| `apps/web/src/lib/api-types.ts` | + application request/response + extended `WaitlistSignup` row type |
| `apps/web/src/app/dashboard/waitlist/page.tsx` | render the new fields per row |
| `apps/web/public/beam/index.html` (L116, 741, 753, 765, 847) | 5 CTA hrefs `/onboarding` → `/apply` |
| `apps/web/public/beam/letter.html` (L120) | account-creation CTA `<a class="cta" href="/onboarding">start beaming for free →</a>` → `/apply` (6th CTA, added per FAIL-2b) |
| `apps/web/public/beam/onboarding-steps.js` (L565) | end CTA `/sign-up` → `/apply` |
| `apps/web/src/app/sign-up/[[...sign-up]]/page.tsx` | pin/prefill the invite email from `validate-invite` |
| `apps/web/src/app/dashboard/layout.tsx` | surface the invite-gate 403 as a readable state |
| `tests/unit/test_invite_gate.py` | + approved-email-passes case (AC-9), + existing-user-never-blocked case (AC-11) |
| `tests/integration/test_apply_intake.py` | NEW — intake persistence, backfill, caps, sanitization |
| `apps/web/src/lib/signup-href.ts` | NEW — pure helper `buildSignUpHref(search: string): string`, the query-preserving redirect target extracted out of the component (gate F10a). No new module was invented where an existing one fit: `utils.ts` is `cn()`-only styling, `onboarding-flow.ts` is the onboarding chat reducer, `plans.ts` is billing metadata — none is a natural home. A dedicated single-concern `src/lib/` module matches the existing repo convention (`canary-format.ts`, `privacy-optout.ts`, `fetch-beacon.ts` each own one concern and one colocated test). |
| `apps/web/src/lib/signup-href.test.ts` | NEW — 3 vitest cases for `buildSignUpHref` (gate F10a) |

### Read-only (context, not modified)

`apps/api/dependencies.py` (`_is_email_allowlisted` L163-176; invite gate L299-312) · `apps/api/config.py` (`invite_only` L141) · `apps/api/agents/prompt_safety.py` (`clean_text`) · `apps/api/schemas/waitlist.py` · `apps/web/next.config.mjs` (rewrites L58) · `apps/web/public/beam/waitlisted.html` · `process/context/tests/all-tests.md` · `apps/web/playwright.config.ts` (`webServer` Clerk-blanking at `:53`, `reuseExistingServer` at `:56` — the stated precondition for known-gap F10b; **read for context only, never edited**) · `apps/web/vitest.config.ts` (`environment: "node"`, `include: ["src/**/*.test.ts"]` — the harness gate F10a runs inside)

**Explicitly NOT touched:** `apps/api/dependencies.py` gate logic, invite-token minting/TTL/one-use enforcement, `/onboarding` gating in middleware, `apps/pixel/`, **and `apps/web/playwright.config.ts`**.

**`apps/web/playwright.config.ts` — explicit non-touch decision (CLOSES CONCERN-9, cycle 5).** Cycle 5 flagged that this file was in neither the Changed nor the Read-only list while any Playwright-based fix to gate F10 would have had to edit its `webServer` block. The chosen F10 resolution is the **F10a/F10b split**: F10a moves the assertion below the Clerk boundary into a vitest unit test, and F10b is recorded as a named known gap rather than built. **Neither touches `playwright.config.ts`** — it stays out of the Changed table, contributes **0** to the blast radius, and its Clerk-blanking `webServer` block (`:53`) and `reuseExistingServer` setting (`:56`) are left exactly as they are. It is listed under Read-only below because F10b's precondition is stated in terms of it. No new Playwright project, no new port, no real Clerk key in the test environment.

---

## Public Contracts

| Contract | Change | Compatibility |
|---|---|---|
| `POST /api/v1/demo/waitlist` | request body gains 6 optional fields | **Additive.** All new fields optional; existing `{email, site_url, x_handle}` body still valid. Endpoint has **zero callers in the repo** (verified by grep), so there is no in-repo consumer to break. |
| `GET /api/v1/waitlist/` (admin) | response `signups[]` gains 7 fields (6 new + `x_handle`) | **Additive.** Only consumer is `apps/web/src/app/dashboard/waitlist/page.tsx`, updated in the same change. |
| `waitlist_signups` table | +6 nullable columns | **Additive-nullable.** No backfill, no default, no constraint. Existing rows read as `NULL`. |
| `settings.invite_only` | default stays `False` | **Unchanged.** Behavior flip is an env var, not a code change. |
| Invite token flow (`validate-invite`, `consume-invite`, `PATCH /approve`) | none | **Unchanged.** |

---

## Blast Radius

| Dimension | Value |
|---|---|
| Files changed | **21** — recounted at cycle 5 (was 20; **it moved, and here is why**). Derivation from the Touchpoints "Changed" table: the table has **22** rows, of which `apps/api/routers/waitlist.py` appears **twice** (once for `list_waitlist`, once for `invite_url`) → 22 − 1 duplicate = **21 distinct files**. Split: **3** new source files (`apps/web/src/app/apply/page.tsx`, `apps/web/src/lib/signup-href.ts`, `apps/web/src/lib/signup-href.test.ts`) + **1** new migration + **1** new test file (`tests/integration/test_apply_intake.py`) + **16** edits. **Delta from cycle 4's 20: −1 +2 = +1.** −1 = `apps/web/e2e/invite-token-delivery.spec.ts` is **removed** (it was the artifact of the unsatisfiable F10; under the cycle-5 F10a/F10b split the browser leg is a named known gap and no spec is written). +2 = `signup-href.ts` and `signup-href.test.ts` (gate F10a). **`apps/web/playwright.config.ts` contributes 0** — the chosen resolution does not touch it (see the explicit non-touch decision in Touchpoints), so CONCERN-9 closes at zero cost rather than via the rejected option that would have taken this to 21 by editing the Playwright harness. **`apps/api/dependencies.py` is NOT in this count and must not enter it** — CONCERN-4 makes the zero-touch verbatim-literal option the F.3 default precisely to keep that file read-only. History: 19 at cycle 3 entry → 20 (cycle 3, Playwright spec) → 21 (cycle 5, spec swapped for the two vitest files). +4 vs cycle 1: `pricing/page.tsx` (FAIL-B), `signup/page.tsx` + `routers/waitlist.py` invite_url (FAIL-A), `sitemap.ts` (NIT-5). |
| Packages | `apps/api`, `apps/web`, `tests` |
| Risk classes | **auth/identity** (invite gate behavior change via env), **schema/migration** (additive-nullable), **public API** (additive request/response) |
| Data risk | Low — no destructive writes, no backfill, no column drops |
| Runtime risk | **Medium-high on flip only.** `INVITE_ONLY=true` makes `get_current_user` 403 any Clerk identity with no matching `User` row. That dependency is on every authed route, so a bad flip fails site-wide at once. Code changes alone (flag off) are inert. |
| Rollback | Revert 6 static CTA hrefs + set `INVITE_ONLY=false`. Migration is additive-nullable and can be left applied. |

---

## Hard Guardrails

| # | Guardrail |
|---|---|
| G1 | `.env` `DATABASE_URL` points at **Supabase PROD**. Every alembic/DB command in this plan MUST pin `DATABASE_URL=postgresql+asyncpg://…@localhost:5433/…` in the command environment first. `apps/api/migrations/env.py` has NO local-host guard. |
| G2 | Do **not** hardcode a `down_revision`. Re-derive the live head at EXECUTE with `alembic -c apps/api/alembic.ini heads` (pinned per G1) and chain off whatever it returns then. |
| G2a | **Untracked-head rule (STOP AND SURFACE).** After deriving the head, check whether its migration file is tracked: `git status --porcelain apps/api/migrations/versions/<head>*.py`. If it reports `??` (untracked), **do NOT chain off it silently.** As of VALIDATE the sole live head is `c5e1a9b73d20` (`add_site_profile`) and it is UNTRACKED — it belongs to the concurrent, uncommitted `site-analysis-onboarding_13-08-26` work. Chaining off an uncommitted parent means that if the sibling file is rebased away, renamed, or dropped, this plan's migration dangles (repo memory `concurrent-program-migration-collision-rechain`, `concurrent-session-rebase-eats-uncommitted-work`). Required executor action, in order: (1) STOP and surface the untracked head to the orchestrator/user by name and owning plan; (2) prefer landing/committing the sibling migration first, then re-derive the head and chain off the now-tracked revision; (3) only if (2) is refused, chain anyway **and** record the dependency explicitly in the new migration's docstring (`depends on untracked <rev> owned by <plan>; re-verify before any deploy`) plus a line in this plan's Resume and Execution Handoff. Never proceed past step (1) without an explicit decision. |
| G3 | Do **not** re-gate `/onboarding` in `apps/web/src/middleware.ts`. The comment forbidding it stays. |
| G4 | Do **not** change `_is_email_allowlisted` or the gate block at `dependencies.py:299-312`. Out of scope per SPEC. |
| G5 | Free text is hostile input. Sanitize server-side on write with `apps/api/agents/prompt_safety.clean_text`; render escaped (default React behavior — never `dangerouslySetInnerHTML`). |
| G6 | Never log applicant free text or raw email. Use `mask_email`, matching the existing `join_waitlist` logging. |
| G7 | Flipping `INVITE_ONLY=true` in production is an **operator action**, never an agent action. |

---

## Implementation Sections

Execution order is A -> B -> C -> D -> E -> F. A must land before B (B writes the columns). E and F are the only sections with user-visible effect; both are last on purpose.

### Section A — Additive-nullable schema + migration

**Satisfies:** AC-3 (storage substrate), AC-14.

**Files:** `apps/api/models/waitlist.py`, `apps/api/migrations/versions/{new}.py` (NEW).

**New columns on `WaitlistSignup`** — all `nullable=True`, no server default, no constraint:

| Column | Type | Source field |
|---|---|---|
| `business_description` | `String(1000)` | "what your business does" (free text) |
| `use_case` | `String(1000)` | "how you plan to use Beam" (free text) |
| `monthly_visitors` | `String(32)` | visitor bucket value |
| `role` | `String(32)` | founder / marketer / agency / other |
| `company_size` | `String(32)` | company-size bucket value |
| `applied_at` | `DateTime(timezone=True)` | set when the extended form (not the bare email form) is submitted; distinguishes an application from a legacy email-only signup |
| `plan_interest` | `String(32)` | plan intent carried from the repointed pricing CTAs as `?plan=` (Section E step 5 → Section C step 5). **7th column — CLOSES CONCERN-2.** |

**Section A creates SEVEN columns, in ONE migration.** `plan_interest` is the 7th and is specified here, in the section that executes first, precisely so an executor never has to reach Section C to learn it exists. Execution order is A → B → C, so a Section-A-only reader must still build the correct table. Every "6 nullable columns" phrasing elsewhere in this plan (Sections A/B, Touchpoints, Public Contracts, Blast Radius) reads as **7**. Do **not** add a second migration for `plan_interest`, and do **not** defer it to a follow-up — the recovery from a 6-column migration is one step away from the forbidden one.

Enum values are validated in Python (Section B), **not** as a DB CHECK constraint — a CHECK is not additive-nullable-safe on a table with existing rows and would violate the SPEC's additive-only rule (AC-14).

**Steps:**
1. Add the **7** `mapped_column` declarations to `WaitlistSignup` (the 6 SPEC-locked fields **plus `plan_interest`**), matching the existing `x_handle` comment style (state that the free-text columns hold untrusted input, sanitized on write).
2. Pin `DATABASE_URL` to `localhost:5433` (G1), then run `alembic -c apps/api/alembic.ini heads` to read the **live** head. Do not reuse `c5e1a9b73d20` from the SPEC — it was untracked at SPEC time and the chain may have moved (G2, SPEC C3).
3. Write the migration chaining `down_revision` off that observed head. `upgrade()` = **7** × `op.add_column(..., nullable=True)`. `downgrade()` = **7** × `op.drop_column`. (Seven, not six — `plan_interest` is included; see the column table above.)
4. Verify additive-only: the generated file must contain no `alter_column`, no `create_check_constraint`, no `create_index`, and no `drop_*` inside `upgrade()`.
5. Round-trip live on the local disposable DB (`upgrade head` → `downgrade -1` → `upgrade head`), still pinned per G1.

**Do not:** backfill any existing row, add defaults, or touch `email` / `status` / `invite_token` / `approved_at` / `used_at` / `used_by_clerk_user_id`.

### Section B — Extend `POST /api/v1/demo/waitlist`

**Satisfies:** AC-3, AC-4, AC-5.

**Files:** `apps/api/routers/demo.py` (`WaitlistRequest` and `join_waitlist`, ~L773-880).

The endpoint has **zero in-repo callers** (grep-verified, recorded in Public Contracts), so extending it is contract-safe. It stays the single intake path — do not add a second endpoint.

**Steps:**
1. **Extend `WaitlistRequest`** with the 6 new fields, all `| None = None`, so the legacy `{email, site_url, x_handle}` body stays valid:
   - `business_description: str | None`, `use_case: str | None` — free text.
   - `monthly_visitors`, `role`, `company_size` — `str | None`, validated against module-level allow-lists.
2. **Add module-level allow-lists** next to the existing `_X_HANDLE_INVALID` constant: `_ROLE_VALUES`, `_VISITOR_BUCKETS`, `_COMPANY_SIZE_BUCKETS` (frozen tuples). Add `_coerce_choice(raw, allowed) -> str | None` that strips, lower-cases, and returns `None` for anything not in `allowed`. **An unrecognized enum value is dropped to `None` — never stored, never a 422.** `join_waitlist` currently never raises and returns `{"status": ...}`; one bad select must not discard the whole application.
3. **Add `_clean_free_text(raw, limit) -> str | None`** applying, in this order: `None`/empty short-circuit → `strip()` → `apps.api.agents.prompt_safety.clean_text(raw, limit)` (G5 — `clean_text` takes `max_len` as a **required positional** and already truncates *after* stripping `<`/`>` and collapsing whitespace; call it once with the limit, do not call it bare and do not truncate twice) → return `None` if empty.

3b. **Add `_clean_url(raw) -> str | None`** — CLOSES FAIL-1. `site_url` is the one hostile input the current code never handles: it is **required** on the new public form, arrives from an unauthenticated endpoint, and today is persisted as `site_url=body.site_url or None` with no sanitization, no scheme check, and no length cap. Apply, in this order:
   - `None`/empty → `None`.
   - `strip()`.
   - **Scheme guard.** Parse with `urllib.parse.urlparse`. Accept **only** `http` and `https`. A scheme-less value (`example.com`) is accepted and normalized to `https://` + value. Anything else — `javascript:`, `data:`, `vbscript:`, `file:`, or an unparseable value — returns `None`. Never stored, never a 422 (same drop-to-`None` rule as `_coerce_choice`, so one bad field cannot discard the whole application).
   - **Cap at 2000 chars** (the column width). An over-length value today raises inside the `except Exception` swallow and silently discards the entire application.
   - Call `_clean_url(body.site_url)` at BOTH the insert branch (step 4) and the backfill branch (step 5), replacing the current raw `body.site_url or None`.
4. **Persist on the insert branch:** pass all 6 values into the `WaitlistSignup(...)` constructor. Set `applied_at = datetime.now(timezone.utc)` only when at least one of the 5 application fields is non-`None` — a bare-email legacy POST leaves it `NULL`.
5. **Backfill on the existing branch (AC-4):** extend the current `if body.X and not existing.X` pattern to each new column using the sanitized/coerced values, keeping the `changed` flag and the single conditional `commit()`. A resubmission never overwrites a non-empty stored value; it only fills blanks. Set `applied_at` on backfill only if it is currently `NULL` and an application field was just filled.
6. **Enrich the admin notify email** (existing block, ~L860): append role, company size, visitor bucket, and both free-text fields under the existing `site_info` line. Wrap each with `html.escape()` before interpolating — this f-string body is the one place applicant text lands outside React's auto-escaping.
   **Also escape the pre-existing `site_info` interpolation (CLOSES FAIL-1).** The current code builds `site_info = f" (site: {body.site_url})"` from the RAW request value and drops it into the `body_html` f-string unescaped. Escaping only the new fields while leaving an unescaped applicant-controlled value in the same HTML string is internally inconsistent and leaves the injection open. Build it from the sanitized value and escape it: `site_info = f" (site: {html.escape(clean_site_url)})" if clean_site_url else ""`. Escaping is defence-in-depth on top of `_clean_url` — the scheme guard is the primary control, the escape is the second.
7. **Logging (G6):** keep `logger.info("waitlist_signup", email=mask_email(email))` exactly as-is. Add no log field carrying free text or a raw email.

**Do not:** change the `5/minute` rate limit, the `{"status": "invalid"}` early return, the confirmation-email body, or the `except Exception` DB-error swallow.

### Section C — Public `/apply` React route

**Satisfies:** AC-1, AC-2, plus the client half of AC-3 and AC-5.

**Files:** `apps/web/src/app/apply/page.tsx` (NEW), `apps/web/src/middleware.ts`, `apps/web/src/lib/api.ts`, `apps/web/src/lib/api-types.ts`.

**Steps:**
1. **`api-types.ts`** — add `ApplicationRequest` (8 fields; `x_handle` optional) and `ApplicationResponse` (`{ status: string }`). Extend the existing `WaitlistSignup` row type with the 6 new nullable fields plus `x_handle` (currently absent from the type).
2. **`api.ts`** — add `submitApplication(body: ApplicationRequest): Promise<ApplicationResponse>` POSTing to `/api/v1/demo/waitlist`. Unauthenticated — do not attach a Clerk token. POSTs get no client timeout, per repo convention.
3b. **`sitemap.ts`** — add `/apply` to `staticRoutes` (NIT-5): `{ url: \`${SITE_URL}/apply\`, changeFrequency: "monthly", priority: 0.8 }`, alongside the existing `/`, `/pricing`, `/blog` entries. `/apply` is now the sole public account-creation entry point, so it must be crawlable — otherwise the CTAs repointed in Section E lead to a page search engines never index.

3. **`middleware.ts`** — add `"/apply(.*)"` to the `isPublicRoute` matcher array (currently L18-20), immediately after the `"/onboarding(.*)"` entry. Leave the `/onboarding` comment block at L5 untouched (G3, AC-2).
4. **`apply/page.tsx`** — a `"use client"` component with local `useState` form state (8 fields does not justify pulling react-hook-form into a route that must render with zero auth context):
   - Required: email, website URL, business description, use case, monthly visitors, role, company size. Optional: X handle. **Consent copy must NOT promise the Founders Wall (NIT-1)** — commit `1b5e808` replaced it with a used-by logo carousel and `index.html` no longer renders any Founders Wall. Promising a surface that does not exist is a false consent representation. Use non-specific wording instead, e.g. "optional — sharing this means we may credit you publicly when we feature early users." Do not name a specific surface unless one demonstrably exists at EXECUTE time (re-check `index.html` before writing the copy).
   - Client-side: `maxLength={1000}` on both textareas, `type="email"` plus non-empty checks, and native `<select>` for the 3 enums whose option values are **string-identical** to `_ROLE_VALUES` / `_VISITOR_BUCKETS` / `_COMPANY_SIZE_BUCKETS` in Section B. Client validation is UX only — the server is the authority (AC-5).
   - On submit: disable the button, call `submitApplication`, then swap to a "you're on the list" confirmation state in place. On network failure show a retryable error and preserve the entered values.
   - Render every value through normal JSX interpolation. **Never `dangerouslySetInnerHTML`** (G5).
5. **Read the optional `?plan=` param (CLOSES FAIL-B).** The four repointed pricing CTAs (Section E step 5) arrive as `/apply?plan=pro`. The route reads the param client-side (`useSearchParams`, wrapped per Next's Suspense requirement if lint demands it), carries it into the `submitApplication` payload as `plan_interest`, and surfaces it read-only in the form ("You're applying with **Pro** in mind") so the applicant can see what was captured. An absent, empty, or unrecognized value is simply omitted from the payload — never a client-side error, never a blocked submit.

6. Do not add a `layout.tsx` under `/apply` — the root layout suffices, and adding one risks pulling auth providers into a public route.

**`plan_interest` field — cross-section wiring (FAIL-B).** This is a **7th nullable column**, folded into the existing Section A migration and the existing Section B field work. Do **not** add a second migration or a second endpoint for it.

- **Section A:** `plan_interest: str | None` becomes the 7th nullable column on `WaitlistSignup`, added in the same additive-nullable migration. Every "6 nullable columns" statement elsewhere in this plan reads as **7** from here on.
- **Section B:** `plan_interest` is added to `WaitlistRequest` as `str | None = None`, coerced through `_coerce_choice` against a new module-level `_PLAN_VALUES` allow-list sourced from the plan slugs already rendered by `pricing/page.tsx`. Unrecognized -> `None` (never a 422, same drop rule as the other enums). It participates in the insert branch, the blank-only backfill branch, and the `applied_at` trigger set.
- **Section D:** `list_waitlist` returns it, and the admin table renders it as a scannable column ("plan interest"), em-dash when `NULL`.

### Section D — Admin waitlist UI surfaces the new fields

**Satisfies:** AC-6.

**Files:** `apps/api/routers/waitlist.py` (`list_waitlist`, ~L43-79), `apps/web/src/app/dashboard/waitlist/page.tsx`.

**Steps:**
1. **`list_waitlist`** — extend the per-signup dict with `x_handle` (present on the model but currently omitted from the response) plus the 6 new columns, and `applied_at` ISO-formatted with the same `if … else None` guard already used for `created_at` / `approved_at`. Do not change the ordering, the `counts` aggregation, or the `require_admin` dependency.
2. **`dashboard/waitlist/page.tsx`** — render the new fields per row. Keep the existing table for scannable columns (email, site, role, company size, visitors, status, dates) and place the two free-text fields in an expandable/secondary block per row so long text does not destroy the table layout.
3. **Legacy rows** have `NULL` in every new column — render an em-dash placeholder, never `"null"` or `"undefined"`.
4. Free text renders as plain JSX children (React auto-escapes). No `dangerouslySetInnerHTML` anywhere in this file (G5).
5. **Scheme-guard the `site_url` link (CLOSES FAIL-1).** `page.tsx:133-138` renders `<a href={s.site_url} target="_blank">`. **React does NOT escape or sanitize `href` values** — it escapes text children only. A stored `javascript:alert(1)` therefore becomes a clickable link executing in an **authenticated admin session**. `_clean_url` (Section B step 3b) blocks this on write for all NEW rows, but legacy rows predate it, so the render path needs its own guard:
   - Add a small local helper `safeHref(url: string | null): string | null` — returns the url only when it starts with `http://` or `https://` (case-insensitive), otherwise `null`.
   - Render `<a href={...}>` **only** when `safeHref(s.site_url)` is non-null. Otherwise render the raw value as **plain text** (React escapes text children), never as a link.
   - Keep `target="_blank"` paired with `rel="noopener noreferrer"`.
   - This is a render-path guard, additive to the existing element; it does not change the table layout or any handler.
6. Leave the Approve / Reject / Grant actions and their handlers untouched — token minting and the invite email are out of scope (SPEC Out of Scope, AC-13).

### Section E — Rewire the 7 static CTAs

**Satisfies:** AC-7.

**Files:** `apps/web/public/beam/index.html` (L116, 741, 753, 765, 847), `apps/web/public/beam/letter.html` (L120), `apps/web/public/beam/onboarding-steps.js` (L565).

These are **static assets** served via `next.config.mjs` rewrites, not React (SPEC C2). Editing them is a plain-text href change with no build step beyond the normal static serve.

**Steps:**
1. Re-derive the exact lines at EXECUTE with `grep -n 'href="/onboarding"\|/sign-up' apps/web/public/beam/index.html apps/web/public/beam/letter.html apps/web/public/beam/onboarding-steps.js`. The recorded line numbers are from PLAN time and these files are under concurrent edit.

   **`letter.html` is in the file list — CLOSES CONCERN-8 (cycle 5).** It was previously absent, so `letter.html:120` — a confirmed rewire target named in step 2 and asserted by gates E1, E2 and E3 — was invisible to the very command that tells the executor which lines to rewire. This is a **DISCOVERY** command, not an assertion gate: it has no expected count and cannot go red against correct code, which is why the omission was a CONCERN rather than the strict unsatisfiable-gate class. **Measured live at cycle 5 with the corrected file list: 9 hits** — `index.html` L116/741/753/765/847 (5 account-creation CTAs), `letter.html` L120 (1), `onboarding-steps.js` L9 + L555 (**prose describing Clerk's hosted page — expected noise in a discovery command; do NOT edit these**) + L565 (the 1 real executable target). **7 rewire targets, 2 prose hits.** The distinction matters: a discovery command is deliberately wider than gate E1's assertion pattern, which excludes the prose by design. Do not "fix" the noise by narrowing this command to E1's pattern — you would then miss the `href="/onboarding"` CTAs entirely.

   **Attribution correction (CONCERN-C).** Earlier text in this plan attributed concurrent `apps/web/public/beam/` edits to `site-analysis-onboarding_13-08-26`. That is **wrong** — that plan touches none of `index.html`, `onboarding-steps.js`, or `middleware.ts`. The real collision is with **`canary-onboarding_10-08-26` Phases 2-4**, which replace the entire static onboarding funnel (`onboarding-steps.js` and its signup flow) with a **React chat shell**. Section E edits `onboarding-steps.js:565` — a line that plan deletes outright — and the React successor's end CTA lives outside every E-gate's grep scope, so E1/E2/E4 would all pass green while the actual user-facing CTA silently reverts to open signup.

   **Cross-plan constraint — a REQUIRED DELIVERABLE of Section E, not an intention (CLOSES CONCERN-3).** While the `INVITE_ONLY` posture holds, the canary React shell's end CTA MUST target `/apply`, not `/sign-up` or `/signup`. Cycle 3 measured that this constraint existed only as an instruction to record it later, with no gate — so it would have died with this task folder on archival, which is the exact failure the paragraph was written to prevent.

   **Deliverable (write this file; it is gated by E6):** `process/features/onboarding-canary/backlog/canary-react-shell-cta-invite-only_NOTE_{date}.md`, stating: while `INVITE_ONLY` holds, the `canary-onboarding_10-08-26` React chat shell's end CTA MUST target `/apply`; `onboarding-steps.js:565` is deleted outright by that plan, so E1/E2/E4 all pass green while the live user-facing CTA silently reverts to open signup; whichever plan lands second owns reconciling the CTA. Also record it in the `canary-onboarding_10-08-26` plan's own text if that plan is writable at EXECUTE time — but the backlog NOTE is the durable artifact and is mandatory either way.
2. Point the 5 `index.html` **account-creation** CTAs at `/apply`, **and `letter.html:120`** — `<a class="cta" href="/onboarding">start beaming for free →</a>`. Per the user decision recorded at supplement time, `letter.html:120` is an **ACCOUNT-CREATION** CTA, not a demo CTA, so it is repointed like the other five; it is not left as an odd sibling. It is publicly reachable — the middleware matcher at `middleware.ts:57-62` excludes `.html`, so `/beam/letter.html` bypasses Clerk entirely. That makes **6 account-creation `/onboarding` CTAs** across the two HTML files. **Only account-creation CTAs.** Any link whose purpose is "try the demo" must keep pointing at `/onboarding` — the canary demo stays public and reachable (AC-2). Judge each link's intent before editing; never blanket-replace.
3. Point the `onboarding-steps.js` end CTA (`/sign-up` → `/apply`), preserving any surrounding query string or tracking parameter.
4. Re-grep **all three** files afterwards and confirm zero residual executable `/sign-up` navigation (gate E1's corrected pattern) and zero account-creation `"/onboarding"` hrefs.

5. **Rewire the 4 React CTAs on the public pricing page (CLOSES FAIL-B).** `apps/web/src/app/pricing/page.tsx` contains four uninventoried account-creation entry points that Section E originally missed entirely: nav "Get started" (L96), free-plan `router.push("/signup")` (L102), signed-out paid-plan `/signup?plan=...` (L134), bottom CTA (L280). `"/pricing(.*)"` is public (`middleware.ts:25`) and `/pricing` is in `sitemap.ts` `staticRoutes` at priority 0.8 — so this is an indexed, crawlable, fully open signup funnel that would survive the entire rest of this plan.

   **USER DECISION (locked at supplement time — do not re-litigate):** repoint all four at `/apply`, **preserving plan intent as a query param** (e.g. `/apply?plan=pro`). No paid self-serve during the beta; the applicant's plan interest is captured and shown to the admin at review time instead of being thrown away.

   Re-derive the four line numbers at EXECUTE — `pricing/page.tsx` and the untracked `pricing/layout.tsx` are concurrent work.

6. **Concurrency note.** `apps/web/src/app/pricing/layout.tsx` is **untracked** (`??`) — it belongs to concurrent, uncommitted work. Same hazard class as the static HTML files: re-grep before editing and do not assume the file set is stable.

**Rollback:** revert exactly these 7 static hrefs **plus the 4 pricing-page CTAs**. That alone restores the current open-signup funnel even with everything else deployed.

### Section F — Invite-gate hardening + operator flip

**Satisfies:** AC-8, AC-9, AC-10, AC-11, AC-12, AC-13.

**Files:** `apps/web/src/app/sign-up/[[...sign-up]]/page.tsx`, `apps/web/src/app/dashboard/layout.tsx`, `tests/unit/test_invite_gate.py`, `apps/web/src/lib/signup-href.ts` (NEW — gate F10a), `apps/web/src/lib/signup-href.test.ts` (NEW — gate F10a).

**Cycle-5 correction (FAIL-D):** this list previously named `apps/web/e2e/invite-token-delivery.spec.ts`. **Do NOT write that spec.** It could never pass: `apps/web/playwright.config.ts:53` blanks the Clerk env for the whole e2e `webServer`, and both of its assertions sit behind `HAS_CLERK` guards, so it went red against fully correct code. The browser leg is now known-gap **F10b** (not built, backlog stub shared with F4/F5); the automated proof is now **F10a**, a vitest unit test of the pure `buildSignUpHref` helper — below the Clerk boundary and therefore deterministic. See gates F10a/F10b in Verification Evidence for the exact commands and the pre-fix measurement.

#### F.1 — The ordering hazard, stated concretely

Two mechanisms fire at two different moments, and they do **not** key on the same thing:

- **Gate (server, at account creation):** `apps/api/dependencies.py:299-312` — inside `get_current_user`, on the genuinely-new-account branch only: `if settings.invite_only and not await _is_email_allowlisted(db, email): raise 403`.
- **Token consume (client, after first sign-in):** `apps/web/src/app/dashboard/layout.tsx:249-276` — reads `localStorage["beam_invite"]` (stashed by the sign-up page from `?invite=…`) and calls `POST /consume-invite` to enforce one-use.

The token is consumed **strictly after** the gate has already passed. The gate never sees the token.

**Does an approved applicant's own invite link pass the gate? Yes — confirmed by reading `_is_email_allowlisted` at `dependencies.py:163-176`.** It runs `SELECT WaitlistSignup.id WHERE lower(email) = lower(:email) AND status IN ('approved','granted')` and returns `True` on any hit. Trace for SPEC UC3:

1. Admin clicks Approve → `PATCH /approve` sets `status='approved'`, mints `invite_token`, sets `approved_at`, sends the invite email.
2. Applicant opens `/sign-up?invite=…`; the page stashes the token in `localStorage` and renders Clerk.
3. Clerk account is created; the first authed API call reaches `get_current_user`. No `User` row exists → new-account branch → `invite_only=True` → `_is_email_allowlisted(db, email)` is awaited.
4. That email's waitlist row is `status='approved'` → the SELECT matches → returns **True** → `not True` is False → **no 403**. The `User` row is created.
5. Only then does `dashboard/layout.tsx` consume the token, setting `used_at` / `used_by_clerk_user_id`.

So the token is not what passes the gate; **the email is**. No change to `_is_email_allowlisted` is needed, and none is permitted (G4).

**The real hazard is the email mismatch (SPEC UC4).** The gate's `email` comes from the Clerk profile, not from the invite link. If the applicant applied as `a@gmail.com` but completes Clerk signup as `a@work.com`, step 4 misses, they take a permanent 403, and they now hold a live Clerk identity with no Beam `User` row — an unrecoverable-looking dead end. Their `localStorage` token is worthless to them because nothing consults it at gate time. The uninvited stranger (UC5) hits the identical 403. F.2 and F.3 exist solely to close this without touching the gate.

#### F.2 — Pin the invite email at sign-up (prevention)

**File:** `apps/web/src/app/sign-up/[[...sign-up]]/page.tsx`.

The page already reads `?invite=…` into `localStorage` (~L38). Extend the same `useEffect`:

1. When an `invite` param is present, call the existing public `GET /validate-invite?token=…` — it already returns `{valid, email}`, built for exactly this purpose.
2. On `valid`, hold the returned email in state and pass it to Clerk as `<SignUp initialValues={{ emailAddress }} />`. Render a visible line above the widget — **with the address MASKED (NIT-2)**: "This invite is for **a\*\*\*@gmail.com** — sign up with this address." Anyone holding a forwarded invite link can load this page, so rendering the full address discloses it to a non-owner. Masking preserves the entire pinning UX (the owner recognizes their own address instantly; Clerk still receives the full value via `initialValues`) while disclosing nothing useful to a stranger. Reuse the existing masking convention (`mask_email` shape: first character + `***` + domain).
3. On invalid / expired / network failure, fall through to today's behavior unchanged. This is a UX guardrail, never a blocker.

Converts most of UC4 from a dead end into a non-event. Changes no server behavior and consumes nothing.

#### F.3 — Make the 403 legible (recovery, AC-12)

**File:** `apps/web/src/app/dashboard/layout.tsx`.

**Mechanism correction (CLOSES FAIL-3).** The earlier "branch on status `403` and the `detail` body" instruction was unimplementable — neither half is available at the call site. Verified by reading the source:

- `api.ts request()` (`:194-206`): for a **string** `detail` it throws a bare `new Error(body.detail || ...)`. A `status` property is attached **only** on the object-`detail` path (`Object.assign(err, { detail })` at `:199-203`). The invite gate raises a **string** detail, so the thrown error carries the message text and **no status code**.
- `dashboard/layout.tsx:481-485` destructures only `{ data: me, isError: meError }`. The one `meError` consumer is the `useEffect` at `:530-538`, which opens with `if (HAS_CLERK) return;` — under Clerk the error is never inspected at all, `me` stays `undefined`, `userEmail` falls back to `""`, and the dashboard renders empty. **That is the UC4 blank-dashboard dead end.**

**Chosen fix — option (a), message-constant match, render-time branch.** This is the in-scope option: it touches only `dashboard/layout.tsx` (already a declared Touchpoint) and does NOT widen `api.ts`'s shared error contract, which every API caller depends on and whose Touchpoint entry is `+ submitApplication()` only.

1. **DEFAULT (do this — CLOSES CONCERN-4): zero-touch verbatim match. Do NOT edit `apps/api/dependencies.py`.** In `dashboard/layout.tsx`, match the existing literal `"Access is invite-only. Join the waitlist to request access."` verbatim, with a comment naming `apps/api/dependencies.py:308` as the source of truth. This keeps the blast radius at **19 files** and keeps the Touchpoints "Read-only (context, not modified)" declaration for `dependencies.py` **true by construction** rather than true by argument.

   **Rejected alternative (recorded, do not silently adopt):** extracting a module-level `INVITE_ONLY_DETAIL` constant in `apps/api/dependencies.py` and importing/mirroring it. It was measured at cycle 3 to have **identical proving power** — gate F8's `grep -c "Access is invite-only" apps/api/dependencies.py` returns `1` under **both** options — while raising the blast radius to 20 files and contradicting this plan's own read-only Touchpoint declaration. The drift risk it guards against is covered instead by F8's cross-file equality assertion. If an executor believes the constant extraction is necessary, that is a scope-widening decision to surface to the orchestrator, not to make inline.
2. In `layout.tsx`, extend the existing `useQuery` destructure to `const { data: me, isError: meError, error: meErrorObj } = useQuery(...)` — additive, no new query, no new fetch.
3. Add a **render-time** branch (in the component's returned JSX, **not** inside the `useEffect` at `:530`, which early-returns under Clerk and therefore can never render this state): when `meError` is true and `meErrorObj?.message` equals the constant, return the dedicated terminal state instead of the normal dashboard shell. Leave the existing legacy-auth `useEffect` untouched.

Rejected alternative (recorded, do not silently adopt): extending `request()`'s `!res.ok` string branch with `Object.assign(err, { status: res.status })` is additive and no current caller reads `.status`, but it changes the shared error contract for every API consumer and falls outside this plan's declared `api.ts` Touchpoint and Blast Radius. If an executor believes it is necessary, that is a scope-widening decision to surface — not to make inline.

The terminal state renders:

- Headline: this email isn't on the invite list.
- Show the signed-in Clerk email so the mismatch is self-diagnosable.
- Primary action → `/apply`. Secondary action → Clerk sign-out, so they can retry with the invited address.
- Do **not** *automatically* retry the fetch on this branch (no 403 loop), and do **not** attempt `consume-invite` — the token stays unconsumed and valid for the correct email, preserving AC-13.
- **Manual "try again" affordance (CLOSES CONCERN-B).** The gate at `dependencies.py:266-272` evaluates a **fabricated** `f"{clerk_user_id}@clerk.user"` address whenever the JWT carries no email claim *and* `_fetch_clerk_profile` fails (it swallows exceptions and returns a `None` email). A fabricated address never matches the allowlist, so a **correctly approved applicant hits the same terminal 403 on a transient network blip** — while their real, approved email is visible to them client-side. Rendering that as a permanent "your email isn't on the list" is a false terminal state.
  - Add a third, **user-initiated** action to the terminal state: a "try again" button that re-invokes the existing query (`refetch()`), plus one line of copy: "If you were approved, this can also happen after a temporary connection problem — try again."
  - This is a manual button only. Do **not** add an automatic retry loop, backoff timer, or `retry:` option to the query — an auto-retrying 403 is the loop this section exists to prevent.
  - Server-side recognition of the `@clerk.user` suffix would be the cleaner fix but is **forbidden by G4** (no changes to the gate block). The fix stays client-side and in scope.

#### F.4 — Test coverage delta

`tests/unit/test_invite_gate.py` today contains exactly two cases (verified by reading the file):

| Existing test | Covers |
|---|---|
| `test_open_signup_creates_new_account` (`invite_only=False`, `allowlisted=False`) | **AC-10** |
| `test_invite_only_blocks_non_allowlisted` (`invite_only=True`, `allowlisted=False`) | **AC-8** |

**BLOCKER FIRST — the file collects zero tests under `-m unit` (CLOSES FAIL-C).** Measured live: `.venv/bin/python3.11 -m pytest tests/unit/test_invite_gate.py -m unit --collect-only -q` reports **"no tests collected (2 deselected)"**. The file has no `pytestmark`, no per-test markers, and no conftest auto-marking. Two consequences:

- Gate **F1 as originally written exits 5 against a fully correct implementation** — an unsatisfiable gate. This is the **third instance of this class** in this plan (after A1's whole-file grep and E1's prose-matching grep), so treat it as a standing pattern, not a one-off.
- Collaterally, the **`-m unit` regression lane has been silently excluding this file all along**, meaning the AC-8/AC-10 coverage this plan leans on has never actually run in the standard lane.

**Required first edit in F.4:** add `pytestmark = pytest.mark.unit` at module level in `tests/unit/test_invite_gate.py`, before adding either new case. Re-run the `--collect-only` command above and confirm it reports **4 collected**, not 0.

**Same trap on the new integration file.** `tests/integration/test_apply_intake.py` (Section B) MUST declare `pytestmark = pytest.mark.integration` at module level. Gate B1 invokes it by path (so it would pass standalone), but gate F3's `-m integration` lane would silently exclude it — a green B1 next to a lane that never ran it.

**Standing rule for this plan:** before marking any gate green, run its command with `--collect-only -q` (pytest gates) or verify the grep actually matches on a known-good file. A gate that collects zero tests is a FAIL, not a PASS.

Uncovered: **AC-9** and **AC-11**. Add two cases on the existing `_patch_clerk` / `_mock_db_new_user` scaffolding:

1. `test_invite_only_allows_allowlisted` — `_patch_clerk(invite_only=True, allowlisted=True)` against a new-user DB mock; assert no `HTTPException` and that a `User` was added. **Closes AC-9.**
2. `test_existing_user_never_blocked` — `invite_only=True`, `allowlisted=False`, but the DB mock returns an existing `User` on the `clerk_user_id` lookup (and, in a second parametrization, on the email lookup); assert no 403 and that `_is_email_allowlisted` is never awaited. **Closes AC-11** — it proves the grandfather path short-circuits *before* the gate, which is the exact property that stops a flip from locking out every current user.

Per Test Infra Improvement Notes: refactor `_mock_db_new_user()` into a parameterized factory (e.g. `_mock_db(*, existing_user=None, allowlist_hit=False)`) rather than adding a second bespoke mock — the new cases need the allowlist SELECT and the user SELECT to return different things.

AC-12 and AC-13 are not reachable from this unit file (they are React-side and Clerk-dependent) — see Verification Evidence for their tiers.

#### F.6 — The invite token never reaches localStorage (CLOSES FAIL-A)

**Severity: highest.** On the primary path — a real applicant clicking the link in the invite email — the token is silently discarded before anything can read it. Traced through live source:

1. `apps/api/routers/waitlist.py:194` builds `invite_url = f"https://getbeam.fyi/signup?invite={invite_token}"` — **no hyphen**.
2. `apps/web/src/app/signup/page.tsx:30` runs `router.replace("/sign-up")` — a **literal string**, so the `?invite=` query is dropped on the hop.
3. The only writer of `localStorage["beam_invite"]` is `apps/web/src/app/sign-up/[[...sign-up]]/page.tsx:38`, which reads `window.location.search` — empty by the time it runs.

Consequence chain: token never stashed -> `dashboard/layout.tsx:256` consume is a no-op -> `used_at` stays `NULL` forever -> **AC-13 one-use enforcement never engages end-to-end**, and gate F5's "confirm `used_at` is still `NULL`" was vacuous (it asserted a value that can never change).

**Both fixes are required — they are defence in depth, not alternatives.**

1. **`apps/web/src/app/signup/page.tsx`** — preserve the query on the redirect, **via the extracted pure helper**: `router.replace(buildSignUpHref(window.location.search))`, importing `buildSignUpHref` from `@/lib/signup-href`. Keep the `HAS_CLERK` guard (`:18`), the `useEffect` at `:28-32`, and the interim "Redirecting…" render (`:34-40`) exactly as they are — **do not delete the guards**; they are the only thing keeping local-dev-without-Clerk and the legacy JWT path working, and removing them breaks `auth.setup.ts` and with it every existing e2e spec. This covers hand-typed `/signup?invite=`, any already-sent invite email, and any third-party link still pointing at the legacy path.

   **The helper is mandatory, not stylistic (FAIL-D, cycle 5).** Inlining a template literal here would leave AC-13 with no automated behavioral proof: the browser-level assertion cannot run in this repo (gate F10b, known gap — the e2e `webServer` blanks the Clerk env), so the ONLY way to prove query preservation automatically is to test the computation directly, below the Clerk boundary. Hence:

   1a. **`apps/web/src/lib/signup-href.ts`** (NEW) — export `buildSignUpHref(search: string): string`. Pure: no `window`, no React, no imports beyond types, so it runs under vitest's `environment: "node"`. Contract: empty/absent `search` → `"/sign-up"`; a non-empty `search` (with or without its leading `?`) → `"/sign-up"` + the normalized query, **preserving every parameter, not just `invite`**. Handle the leading `?` exactly once — do not emit `/sign-up??invite=abc`.

   1b. **`apps/web/src/lib/signup-href.test.ts`** (NEW) — the 3 cases asserted by gate F10a. Colocated beside the module, matching the existing `src/lib/*.test.ts` convention.

   Gate **F9** stays satisfiable under this shape: the call site still contains `window.location.search` on the `router.replace` line, and the bare `router.replace("/sign-up")` literal is still gone.
2. **`apps/api/routers/waitlist.py:194`** — change `invite_url` to point at `/sign-up?invite={invite_token}` directly, removing the hop entirely.

**Scoped-deviation note (SPEC compliance).** The SPEC lists email templates as Out of Scope. This edit is recorded as an explicit, narrow deviation: it changes a **single URL constant**, not template copy, structure, or styling, and the SPEC's AC-13 cannot be satisfied without it. No other line of the invite email is touched.

**Do not** change the token itself, its TTL, minting, or `consume-invite` — those stay untouched (SPEC Out of Scope).

#### F.5 — Operator flip (never an agent action, G7)

**ACCEPTED RISK — the Gumroad webhook bypasses the invite gate entirely (CONCERN-A).** `apps/api/routers/billing.py:662-676` creates a `User(email=...)` for an unknown purchasing email with **no invite check**. That email is thereafter "existing", so the grandfather short-circuit at `dependencies.py:283-296` fires and the gate at `:299-312` is **structurally never reached** for that identity. A refund does not undo the created `User`.

**USER DECISION (locked at supplement time — do not gate the webhook, do not re-litigate):** this is **intended behavior**. Buyers self-invite; paying is treated as its own admission ticket. It is recorded here explicitly because *silent* uncontrolled account creation is what was forbidden — an accepted, documented path is not.

Operator implications:
- `INVITE_ONLY=true` closes the `/apply` funnel, **not** the purchase funnel. Account creation remains possible via Gumroad purchase at all times.
- Anyone auditing "who can create an account during the beta" must be told **two** answers: approved waitlist emails, and Gumroad purchasers.
- No code change is made here. `billing.py` is **not** a Touchpoint of this plan.

Ordered runbook for a human, after Sections A–E are deployed and verified:

1. Confirm the Section A migration is applied on the target DB (`alembic current`).
2. Confirm all 6 CTAs point at `/apply` in production (view-source on the live site, not local files).
3. Confirm at least one `approved` waitlist row exists and its holder can complete signup (dry run on the real deploy).
4. Set `INVITE_ONLY=true` and restart the API.
5. Immediately verify an **existing** user can still load the dashboard (AC-11 in production). If not, set `INVITE_ONLY=false` at once — this is the site-wide failure mode named in Blast Radius.

**Operator fact — approvals NEVER expire (NIT-6).** The "invite TTL is 14 days" statement applies **only** to `validate-invite` / `consume-invite` (the token). The gate at `dependencies.py:299-312` calls `_is_email_allowlisted`, which is a plain `SELECT ... WHERE lower(email)=... AND status IN ('approved','granted')` — it checks **no TTL and no `used_at`**. Therefore:

- An applicant approved 6 months ago, whose token expired long since and who never used it, **still passes the gate forever** and can create an account at any time.
- One-use enforcement (`used_at`) constrains the **token**, not the **email**. The same approved email can create an account after the token is spent or dead.
- An operator reading "TTL 14 days" will otherwise wrongly assume approvals lapse. **They do not.** Revoking access means changing the row's `status` away from `approved`/`granted` — nothing else does it.

This is recorded, not changed: modifying `_is_email_allowlisted` is forbidden by G4.

**Awareness note — reapplication is invisible (NIT-4).** A rejected applicant who reapplies produces **no new record and no admin signal**: Section B's backfill branch only fills blank columns on the existing row, and `status` is untouched, so a rejected row stays rejected and silent. The admin sees nothing new. This is SPEC-locked behavior and is **not** changed by this plan — recorded so nobody later reads the silence as a bug.

Agents may implement and verify the preconditions for steps 1-3. **Agents never perform steps 4-5.**

---

## Verification Evidence

Runner facts from `process/context/tests/all-tests.md`: unit lane `.venv/bin/python -m pytest tests/unit -m unit -q` (~1.5s, no deps); integration lane `.venv/bin/python -m pytest tests/ -m integration -q` (needs local Postgres + Redis); e2e `cd apps/web && npm run test:e2e`; web lint `cd apps/web && npm run lint`.

**Container availability — 3-step daemon ladder (corrected per CONCERN-8).** The earlier text asserted "Docker IS running on this machine." That was measured FALSE at VALIDATE time: `lsof` returned nothing and the CLI returned `Cannot connect to the Docker daemon`. What is durably true is narrower — the **binary exists** at `/Applications/Docker.app/Contents/Resources/bin/docker` but is off `PATH` (so `which docker` misleads agents into declaring the runtime absent), and the **daemon may be down**. Run this ladder before any Hybrid gate; never skip a step, never assume a step's outcome:

1. **Check.** `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'`. Non-empty → services are up, proceed to the gate.
2. **Start the daemon if step 1 is empty.** `open -a Docker`, then poll `/Applications/Docker.app/Contents/Resources/bin/docker info` until it exits 0 (allow ~60s; the daemon is slow to accept connections after launch). Do not proceed to step 3 while `docker info` is still failing — `compose up` against a dead daemon produces a misleading error.
3. **Bring up the services.** `/Applications/Docker.app/Contents/Resources/bin/docker compose -f infra/docker-compose.yml up -d postgres redis`, then re-run step 1 to confirm 5433 and 6379 are listening.

**No gate below may be marked environment-blocked for want of a container** — that rule stands and is unchanged. What changes is that "the daemon is down" is now an expected state to be *resolved by step 2*, not evidence that the gate is unrunnable. Only if step 2 fails after a genuine attempt may a Hybrid gate be reported blocked, and then the failure output must be quoted.

**G1 applies to every DB command below:** prefix with `DATABASE_URL=postgresql+asyncpg://…@localhost:5433/…`. An unpinned alembic invocation hits Supabase PROD.

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| **A1** — migration additive-only, scoped to `upgrade()` (corrected per CONCERN-6): `awk '/^def upgrade/,/^def downgrade/' apps/api/migrations/versions/{new}.py \| grep -E 'alter_column\|create_check_constraint\|create_index\|drop_'` returns nothing. **The awk range extraction is load-bearing.** The old whole-file grep matched the 6 × `op.drop_column` calls in a *correct* `downgrade()` — a correct implementation reddened, so an execute-agent iterating to green would have deleted a required downgrade. The extracted range ends at the `def downgrade` line, so downgrade bodies are excluded while any real `drop_`/`alter_column` inside `upgrade()` still fails the gate. | Fully-Automated | AC-14 |
| **A2** — live round-trip on local disposable DB (G1-pinned): `alembic -c apps/api/alembic.ini upgrade head && … downgrade -1 && … upgrade head` all exit 0 | Hybrid (precondition: Postgres on 5433) | AC-14 |
| **A3** — single head after chaining: `alembic -c apps/api/alembic.ini heads` prints exactly one revision | Fully-Automated | AC-14 (G2) |
| **B1** — full application POST persists all 9 fields (8 form fields + `plan_interest`) with `status='pending'`: `.venv/bin/python -m pytest tests/integration/test_apply_intake.py -q`. **Precondition (FAIL-C): the file must declare `pytestmark = pytest.mark.integration`** — B1 invokes it by path and would pass without the marker, while gate F3's `-m integration` lane silently excludes it. Confirm with `--collect-only -q` under `-m integration`. | Hybrid (precondition: Postgres + Redis) | AC-3 |
| **B2** — resubmit same email: no error, blanks filled, non-empty values unchanged (same file, backfill case) | Hybrid (same precondition) | AC-4 |
| **B3** — free text >1000 chars is truncated and `<script>`-style markup is stripped by `clean_text` before storage (same file, sanitization case) | Hybrid (same precondition) | AC-5 |
| **B4** — unknown enum value stored as `NULL`, request still returns `{"status": "ok"}` (same file) | Hybrid (same precondition) | AC-3, AC-5 |
| **B5** — legacy `{email}`-only body still accepted, `applied_at` stays `NULL` (same file) | Hybrid (same precondition) | AC-4 (back-compat) |
| **B6** — `site_url` scheme guard (FAIL-1): POST `site_url="javascript:alert(1)"` → the stored row's `site_url` is `NULL`; POST `"data:text/html,x"` → `NULL`; POST `"example.com"` → stored as `https://example.com`; POST `"https://ok.com"` → stored unchanged; POST a 3000-char url → request still returns `{"status":"ok"}` **and the other 7 fields persist** (proves the over-length value no longer discards the whole application). Same integration file. | Hybrid (precondition: Postgres + Redis) | AC-5 |
| **B7** — notify-email escaping (FAIL-1): with a `site_url` and free-text values containing `&`/quote characters, assert the composed `body_html` contains the `html.escape`d form and no raw applicant substring. Unit-testable if the compose step is extracted; otherwise assert inside the same integration case. | Hybrid (same precondition) | AC-5 (G5) |
| **D3** — admin `href` guard (FAIL-1): `grep -n 'safeHref' apps/web/src/app/dashboard/waitlist/page.tsx` matches, and no `href={s.site_url}` (raw, unguarded) remains: `grep -n 'href={s\.site_url}' apps/web/src/app/dashboard/waitlist/page.tsx` returns nothing | Fully-Automated | AC-5, AC-6 (G5) |
| **C1** — `/apply` is public: `grep -n '"/apply(.\*)"' apps/web/src/middleware.ts` matches inside `isPublicRoute` | Fully-Automated | AC-1 |
| **C2** — `/onboarding` un-gated and its comment intact: `grep -n '/onboarding(.\*)' apps/web/src/middleware.ts` still matches and `git diff apps/web/src/middleware.ts` shows only the one added line | Fully-Automated | AC-2 |
| **C3** — web typecheck + lint clean: `cd apps/web && npm run lint` exits 0 | Fully-Automated | AC-1, AC-6 |
| **C4** — no unsafe HTML on either new/changed surface: `grep -rn 'dangerouslySetInnerHTML' apps/web/src/app/apply/ apps/web/src/app/dashboard/waitlist/` returns nothing | Fully-Automated | AC-5 (G5) |
| **C5** — form renders unauthenticated, submits, shows the confirmation state | Agent-Probe (load `/apply` in a browser with no session; submit a filled form; judge that the confirmation state replaces the form and no auth redirect occurs) | AC-1, AC-3 |
| **D1** — admin list returns the new fields: assert the `signups[]` shape in the same integration file against a seeded row | Hybrid (precondition: Postgres + Redis) | AC-6 |
| **D2** — legacy `NULL` row renders as em-dash, not `"null"`/`"undefined"` | Agent-Probe (admin dashboard `/dashboard/waitlist` with one legacy and one full row; judge both render legibly) | AC-6 |
| **E1** — no residual account-creation **navigation** (rescoped per FAIL-2a): `grep -nE "location\.href *= *['\"]/sign-up\|href=\"/sign-up\"" apps/web/public/beam/index.html apps/web/public/beam/onboarding-steps.js apps/web/public/beam/letter.html` returns nothing. **Must match executable navigation only.** The old whole-file `/sign-up` grep matched two prose lines (`onboarding-steps.js:9`, `:555`) that describe Clerk's hosted page and must NOT be deleted — a correctly rewired file failed that gate, so an execute-agent iterating to green would have mangled accurate comments. Verified against the live files: the corrected pattern matches only `onboarding-steps.js:565` (`window.location.href = '/sign-up'`) today and matches nothing after the rewire. `href="/sign-in"` at `:564` is correct and must survive — the pattern does not match it. | Fully-Automated | AC-7 |
| **E2** — exactly **7** `/apply` hrefs across the three static files. **Coherence fix (NIT-3): the file list and the expected count now agree.** The earlier phrasing said "sums to 6 (7 if letter.html is repointed)" while `letter.html` was not in the command's file list — an incoherent gate. `letter.html` IS a rewire target (Section E step 2), so it is in the list and the single expected count is **7**: `grep -c '/apply' apps/web/public/beam/index.html apps/web/public/beam/letter.html apps/web/public/beam/onboarding-steps.js` sums to 7 (5 + 1 + 1). **Count is DERIVED, not guessed** — measured at supplement time against the live files: `index.html` has 5 account-creation `href="/onboarding"` CTAs (L116, 741, 753, 765, 847), `letter.html` has 1 (L120), `onboarding-steps.js` has 1 executable `/sign-up` navigation (L565) = 7 rewire targets, and all three files currently contain **zero** `/apply` occurrences (verified: `grep -c '/apply'` = 0/0/0). Re-derive at EXECUTE with the same command before asserting the number — these files are concurrently edited by `site-analysis-onboarding_13-08-26`. If the pre-edit `/onboarding`+`/sign-up` target count differs from 6+1, the expected post-edit count changes with it; the gate asserts *targets rewired*, never a hardcoded literal. | Fully-Automated | AC-7 |
| **E4** — no residual React account-creation CTAs (FAIL-B): ``grep -rnE "['\"\`]/signup" apps/web/src/app/pricing/`` returns nothing, and `grep -rn '/apply' apps/web/src/app/pricing/page.tsx` matches 4 times. **The backtick in the character class is load-bearing (CONCERN-1, closed cycle 3).** The earlier class `['\"]` admitted only `'` and `"`, so it matched L96/L134/L280 and was **blind to L102** — the paid-plan signed-out CTA, written as a template literal `` `/signup?plan=${planId}&interval=${interval}` ``, i.e. precisely the CTA the locked `?plan=` decision exists for. Measured live at cycle 3: old pattern **3 hits**, corrected pattern **4 hits**. **Pre-fix confirmation is mandatory:** run the corrected command against the current tree BEFORE the rewire and confirm it reports **4**, not 3. A gate that cannot see the pre-fix defect cannot prove the post-fix state. **E1/E2 grep only the two static HTML files plus `onboarding-steps.js` and would never have caught these** — that blind spot is exactly how 4 open signup CTAs on an indexed public page survived the first validation pass. Scope the grep to the whole `pricing/` directory, not just `page.tsx`, because `pricing/layout.tsx` is untracked concurrent work. | Fully-Automated | AC-7 |
| **E6** — cross-plan constraint is durable (CONCERN-3): `ls process/features/onboarding-canary/backlog/canary-react-shell-cta-invite-only_NOTE_*.md` exits 0. Proves the canary-React-shell CTA constraint was written as a durable artifact rather than left as an intention that dies on this task folder's archival. | Fully-Automated | AC-7 |
| **E5** — plan intent survives the hop (FAIL-B): from `/pricing`, click the paid-plan CTA and confirm the browser lands on `/apply?plan=<slug>`, the form acknowledges the plan, a submitted application persists `plan_interest`, and the admin row displays it. | Agent-Probe | AC-6, AC-7 |
| **E3** — demo CTAs still point at `/onboarding` (not blanket-replaced): manual read of each remaining `/onboarding` href across `index.html`, **`letter.html`**, and `onboarding-steps.js` to confirm intent. Probe scope extended per FAIL-2b to cover `letter.html`. | Agent-Probe | AC-2, AC-7 |
| **F1** — `.venv/bin/python -m pytest tests/unit/test_invite_gate.py -m unit -q` — all 4 cases green. **Precondition (FAIL-C): `pytestmark = pytest.mark.unit` must exist at module level.** Without it this command collects **zero** tests and exits 5 against a correct implementation (measured live: "no tests collected (2 deselected)"). Assert collection explicitly first: `... --collect-only -q` reports **4 collected**. A zero-collection run is a FAIL, never a PASS. | Fully-Automated | AC-8, AC-9, AC-10, AC-11 |
| **F11** — marker presence (FAIL-C): `grep -n 'pytestmark = pytest.mark.unit' tests/unit/test_invite_gate.py` matches AND `grep -n 'pytestmark = pytest.mark.integration' tests/integration/test_apply_intake.py` matches. Guards both files against the silent-lane-exclusion trap. | Fully-Automated | AC-8, AC-10 |
| **F7** — AC-9 **substance**, real DB (closes the vacuous-green hole, CONCERN-3): in `tests/integration/test_apply_intake.py`, seed real `WaitlistSignup` rows and call the REAL `_is_email_allowlisted` (no monkeypatch) — assert `("a@x.com", status="approved") -> True`; `("A@X.COM")` -> `True` (case-insensitive); `("b@x.com")` -> `False` (absent); `("c@x.com", status="pending")` -> `False`; `("d@x.com", status="granted")` -> `True`. **Why this is required:** `tests/unit/test_invite_gate.py:_patch_clerk` monkeypatches `deps._is_email_allowlisted` to an `AsyncMock`, so gate F1 proves only the branch expression `if invite_only and not <constant>` — it mocks the very function under test and proves nothing about the allowlist SQL, case handling, or `status` filtering. Without F7, AC-9 is vacuously green and the single behavior this plan's whole safety case rests on (F.1) has no non-mocked proof. | Hybrid (precondition: Postgres + Redis) | AC-9 |
| **F2** — full unit lane no regression: `.venv/bin/python -m pytest tests/unit -m unit -q` | Fully-Automated | AC-10 (regression) |
| **F3** — full integration lane no regression: `.venv/bin/python -m pytest tests/ -m integration -q` | Hybrid (precondition: Postgres + Redis) | AC-10, AC-13 |
| **F4** — invite email pinned at sign-up: `/sign-up?invite=<valid>` prefills the invited address and shows the "this invite is for…" line | Agent-Probe (needs a real Clerk instance; no Playwright auth harness exists) | AC-9 (prevention half of UC4) |
| **F5** — 403 renders the legible recovery state with a link to `/apply` and a manual "try again" affordance, does not auto-loop, and does not consume the token. **De-vacuumed per FAIL-A:** the old "confirm `used_at` is still `NULL`" assertion was unfalsifiable, because before F.6 no code path could ever set it. The probe now has two halves and BOTH must be recorded: (a) **positive control** — the *invited* address completes sign-up and `used_at` transitions `NULL` -> set (proves the token actually arrives and is consumed); (b) **negative control** — a *non-allowlisted* address hits the 403 state and that row's `used_at` is still `NULL`. Half (b) alone proves nothing. | Agent-Probe (needs a real Clerk instance) | AC-12, AC-13 |
| **F9** — query preservation across the legacy hop (FAIL-A): `grep -n 'window.location.search' apps/web/src/app/signup/page.tsx` matches on the `router.replace` line, and `grep -n 'router.replace("/sign-up")' apps/web/src/app/signup/page.tsx` returns nothing (the bare literal is gone). Additionally `grep -n 'signup?invite=' apps/api/routers/waitlist.py` returns nothing and `grep -n 'sign-up?invite=' apps/api/routers/waitlist.py` matches. | Fully-Automated | AC-13 |
| **F10a** — query-preserving redirect target, below the Clerk boundary (**REPLACES the unsatisfiable F10; closes FAIL-D, cycle 5**). Extract the redirect-target computation out of the component into a PURE helper `buildSignUpHref(search: string): string` in the NEW module `apps/web/src/lib/signup-href.ts`; `apps/web/src/app/signup/page.tsx` calls it instead of the bare literal. Test it directly in `apps/web/src/lib/signup-href.test.ts` — **exactly 3 cases**: `buildSignUpHref("")` → `"/sign-up"`; `buildSignUpHref("?invite=abc")` → `"/sign-up?invite=abc"`; `buildSignUpHref("?invite=abc&ref=x")` → preserves **both** params. Command: `cd apps/web && npx vitest run src/lib/signup-href.test.ts` — must report **3 passed** (a bare exit-0 is not sufficient; see the zero-collection trap below). PLUS `grep -n 'buildSignUpHref' apps/web/src/app/signup/page.tsx` must match — a pure helper nothing calls is dead code, and this assertion is what makes the unit test a proof about the app rather than about an orphan function. **Pre-fix measured live at cycle 5:** `npx vitest run src/lib/signup-href.test.ts` exits **non-zero** with `No test files found, exiting with code 1`, and `ls apps/web/src/lib/signup-href.ts` → `No such file or directory` — red now, for the right reason, and green only once the module, the test, and the call site all land. **Why a unit test and not a browser test:** the assertion is moved BELOW the Clerk boundary, so it is unaffected by `playwright.config.ts:53` blanking the Clerk env and by the `HAS_CLERK` guards at `signup/page.tsx:18,28-32`. It is deterministic, CI-safe, and immune to `reuseExistingServer` ambient state. **Harness facts (measured, not assumed):** `apps/web` already runs vitest — `package.json` `"test": "vitest run"`, `vitest.config.ts` `environment: "node"`, `include: ["src/**/*.test.ts"]`, `@` aliased to `./src`; 10 colocated `src/lib/*.test.ts` files already exist and the full lane measured **167 passed / 10 files in 1.03s** at cycle 5. Re-run `cd apps/web && npm test` after the change and confirm **170 passed** (167 + 3) — no regression. | Fully-Automated | AC-13 |
| **F10b** — end-to-end token delivery in a real browser: `/signup?invite=X` → URL becomes `/sign-up?invite=X` → `localStorage["beam_invite"] === "X"` → consume → `used_at` transitions. **KNOWN GAP — not built by this plan; no spec file is written.** **Named precondition:** a Playwright web server started with a REAL Clerk publishable key. The repo does not have one — `apps/web/playwright.config.ts:53` deliberately blanks the Clerk publishable-key and secret-key env vars for the whole e2e `webServer` (comment: *"Disable Clerk auth for E2E — fall back to JWT-based auth"*), and both halves of this assertion are behind `HAS_CLERK` guards (`signup/page.tsx:18,28-32`; `sign-up/[[...sign-up]]/page.tsx:11,28,36`), so with the key empty **no redirect fires and `beam_invite` is never written**. This is the same missing-Clerk-harness gap that already makes F4 and F5 Agent-Probes; F10b is recorded the same way rather than being written as a spec that cannot pass. Backlog stub: `clerk-playwright-auth-harness_NOTE_{date}.md` under `process/features/onboarding-canary/backlog/` (shared with F4/F5 — one stub, three gates). **Do NOT skip-guard a spec into the suite to make this green** — a skip-guard re-vacuums the gate, which is exactly what cycle 3 was trying to close. | Hybrid (precondition: Clerk-enabled Playwright web server — **absent in this repo**) | AC-13 |
| **F8** — F.3 branch is reachable under Clerk (FAIL-3): `grep -n 'error: meErrorObj\|meErrorObj' apps/web/src/app/dashboard/layout.tsx` matches, AND the invite-only branch does NOT sit inside the `if (HAS_CLERK) return;` effect — confirm by reading that the match is in the returned JSX, not within the `useEffect` block at ~:530. Also assert the message string is identical across the two files: `grep -c "Access is invite-only" apps/api/dependencies.py apps/web/src/app/dashboard/layout.tsx` returns 1 for each. **This gate passes identically under both F.3 options** (measured cycle 3: `dependencies.py` returns `1` today, and returns `1` whether the literal stays inline — the default — or is moved into a module-level constant). It therefore never pressures an executor toward the rejected `dependencies.py` edit. | Fully-Automated (grep) + Agent-Probe (placement read) | AC-12 |
| **F6** — `PATCH /approve` → `validate-invite` → `consume-invite` one-use still enforced (second consume rejected) | Hybrid (precondition: Postgres + Redis; existing integration coverage re-run under F3) | AC-13 |

**Known gaps (not marked PASS-able; tracked, not silently dropped):**

- **AC-12 has no automated leg.** F5 is Agent-Probe because the repo has no Clerk Playwright auth harness (recurring, see Test Infra Improvement Notes). Backlog stub: `clerk-playwright-auth-harness_NOTE_{date}.md` under `process/features/onboarding-canary/backlog/`. AC-12's gate stays **CONDITIONAL** until either the probe is run and recorded or the harness lands.
- **AC-9's production half (F4)** is likewise Agent-Probe for the same reason. Its **branch** half (F1 case 1) is Fully-Automated but mocks `_is_email_allowlisted`, so it proves the branch expression only; its **substance** half is proven by the new Hybrid gate **F7** against a real DB. AC-9 is therefore no longer vacuously green: F1 (branch) + F7 (match) together prove it, with only the browser/Clerk prevention leg (F4) remaining a probe.
- **AC-13's browser leg (F10b) is a known gap** (cycle 5, FAIL-D). Same root cause as AC-12/AC-9's probes: no Clerk-enabled Playwright harness. AC-13 is **not** vacuous — F10a proves the query-preservation computation automatically and unconditionally, and F9 proves the two string edits landed; what remains unproven automatically is the browser-level hop (redirect fires → `localStorage` written → token consumed). Backlog stub: the shared `clerk-playwright-auth-harness_NOTE_{date}.md` under `process/features/onboarding-canary/backlog/` — **one stub covering F4, F5 and F10b**. AC-13's browser leg stays **CONDITIONAL** until the harness lands.
- No load/abuse test on `/apply` beyond the inherited `5/minute` limiter. Accepted — the limiter is pre-existing and unchanged.


## Test Infra Improvement Notes

- No Clerk Playwright auth harness exists in this repo (recurring gap across features). Any e2e leg touching authed dashboard state must be skip-guarded.
- **LOOP LESSON (cycle 5, the most important note in this file): a fix that introduces a NEW gate must have that gate EXECUTED in the same cycle that writes it.** Auditing only pre-existing gates is precisely how instances 5 and 6 of the unsatisfiable-gate class survived. Instance 6 (**F10**) was *created by cycle 3's own CONCERN-5 fix* — promoting an Agent-Probe to Fully-Automated by inventing a Playwright spec — and then survived cycle 4's audit, because cycle 4 re-checked the same surface cycle 3 had (probes + the existing gate table) and never ran the *new* gate's runtime preconditions. The defect class did not recur at the pattern level; it recurred one level up, as an **audit-scope gap**. Standing rule, in addition to the pre-fix-measurement rule below: **a gate you cannot run is a gate you must not write.** Before recording any new or modified gate command, execute it against the live tree and record the measured pre-fix result in the gate text. This applies to the *supplement* agent's own new text, not only to inherited text — every supplement cycle must re-audit what it just wrote, not merely what it was asked to fix.
- **Playwright cannot prove any Clerk-dependent browser behavior in this repo, and that is structural, not incidental.** `apps/web/playwright.config.ts:53` blanks the Clerk publishable/secret keys for the whole e2e `webServer`, so every `HAS_CLERK`-guarded code path is dead under `npm run test:e2e`. Compounding it, `:56`'s `reuseExistingServer: !process.env.CI` means a developer with a Clerk-enabled `npm run dev` on :3000 gets the *opposite* behavior locally — such a gate is non-deterministic, which is worse than reliably red. Any future gate touching a Clerk-gated path must be either (a) moved below the Clerk boundary into a vitest unit test (the **F10a pattern** — `apps/web` already has vitest: `environment: "node"`, `include: ["src/**/*.test.ts"]`, 10 lib test files, 167 tests, ~1s), or (b) declared Hybrid with the harness named as an explicit precondition (the **F10b pattern**). Never a Playwright spec asserting Clerk-gated behavior.
- **Unsatisfiable-gate class, 4 instances in this plan** (A1 whole-file grep matching a correct `downgrade()`; E1 whole-file grep matching accurate prose comments; F1 collecting zero tests for want of a `pytestmark`; and — found at cycle 3 — the Resume-and-Execution-Handoff probe for Section E reusing the *same* unsatisfiable `/sign-up` pattern E1 had already been corrected away from, plus a bare `*` glob widening scope to a fourth file). **The recurrence is the finding:** a pattern removed from a gate was left alive in a probe, because only gates were re-audited. Any correction to a gate pattern must be grepped for across the WHOLE plan, not just the gate table. Cycle 3 audited every probe and every remaining gate command by executing them; one additional instance was found and fixed, none remain. Every one would have driven an execute-agent to damage correct code while "iterating to green". Standing mitigation: verify each gate command against the current (pre-fix) tree and confirm it fails for the RIGHT reason before trusting it.
- **Cycle-5 supplement self-audit (the loop lesson applied to this cycle's OWN new text).** Every command written or modified by the cycle-5 supplement was executed against the live tree before being recorded, and the measured pre-fix result is quoted in the gate text: F10a's `npx vitest run src/lib/signup-href.test.ts` → exit non-zero, `No test files found, exiting with code 1`; F10a's call-site `grep -n 'buildSignUpHref' apps/web/src/app/signup/page.tsx` → rc=1 (absent); `ls apps/web/src/lib/signup-href.ts` → `No such file or directory`; the regression baseline `cd apps/web && npm test` → **167 passed / 10 files** (so post-fix must read 170); Section E step 1's corrected 3-file re-derivation grep → **9 hits** (7 rewire targets + 2 prose). All five fail in the **correct** direction — red now because the artifact does not exist yet, green once it lands — and none can go red against a correct implementation. F10b deliberately has **no command**: it is a named residual, not a gate. No new command was recorded unexecuted.
- **Pytest marker discipline is unenforced.** `tests/unit/test_invite_gate.py` carried no marker and was therefore silently excluded from the `-m unit` lane indefinitely. Nothing in CI or the conftest catches an unmarked test file. Backlog candidate: a conftest hook or lint rule that fails on any file under `tests/unit/` or `tests/integration/` lacking the matching module-level `pytestmark`.
- **React CTA surfaces are invisible to static-asset greps.** E1/E2 scanned only `apps/web/public/beam/`; four open signup CTAs on the indexed public `/pricing` page went unnoticed for a whole validation cycle. Any future "close the signup funnel" work must grep `apps/web/src/app/` too.
- `tests/unit/test_invite_gate.py` mocks the DB session wholesale. Adding the approved-email-passes case requires a mock that returns a row for the allowlist SELECT but `None` for the user SELECT — extend `_mock_db_new_user()` rather than writing a second bespoke mock.

## Resume and Execution Handoff

1. **Selected plan file:** `process/features/onboarding-canary/active/private-beta-apply-form_14-08-26/private-beta-apply-form_PLAN_14-08-26.md`
2. **Last completed phase/step:** PLAN complete; **PVL supplement cycle 2 applied** (3 FAILs, 3 CONCERNs, 6 NITs from the adversarial verifier closed in plan text). No source file has been touched. Nothing in Sections A–F has been executed.

   **Cycle-2 scope changes an executor must not miss:** the invite email's URL now points at `/sign-up` and `signup/page.tsx` preserves its query (F.6, FAIL-A); 4 pricing-page CTAs are repointed to `/apply?plan=...` (Section E step 5, FAIL-B) which adds a **7th** nullable column `plan_interest` to the SAME Section A migration; `pytestmark` must be added to both test files before any pytest gate is trusted (FAIL-C); the Gumroad webhook bypass is an ACCEPTED, documented account-creation path (F.5, CONCERN-A); the real concurrent collision is `canary-onboarding_10-08-26`, not `site-analysis-onboarding_13-08-26` (CONCERN-C).
3. **Validate-contract status:** WRITTEN — see `## Validate Contract` below. PVL cycle 3 (outer-pvl) closed **CONDITIONAL**: 0 FAILs, 6 CONCERNs, each carried into EXECUTE as a named one-step instruction.
4. **Context files to load before resuming:**
   - `private-beta-apply-form_SPEC_14-08-26.md` (same folder) — the 14 ACs and locked decisions; this plan does not restate them.
   - `process/context/all-context.md` — repo router; note the Supabase-PROD `.env` warning and the Docker-CLI-off-PATH gotcha.
   - `process/context/tests/all-tests.md` — runner commands quoted in Verification Evidence.
   - Read-only source context listed in Touchpoints, especially `apps/api/dependencies.py:163-176` and `:299-312`.
5. **Next step for a fresh agent:** EXECUTE Section A first. **All 7 cycle-3 CONCERN fixes are now applied in this plan's text — you do not need to apply them, only to follow the plan as written.** Where each landed: CONCERN-2 → Section A now specifies **7** columns incl. `plan_interest` (`String(32)`) with 7× add/drop; CONCERN-1 → gate E4's pattern now includes the backtick (confirm **4** hits pre-fix); CONCERN-3 → the canary backlog NOTE is a Section E deliverable gated by new **E6**; CONCERN-4 → F.3 step 1's default is the zero-touch verbatim match, `dependencies.py` stays read-only; CONCERN-5 → **SUPERSEDED at cycle 5**: F10 was split into **F10a** (Fully-Automated vitest unit test of the pure `buildSignUpHref` helper) and **F10b** (browser leg, known gap). The Playwright spec `apps/web/e2e/invite-token-delivery.spec.ts` is **NOT to be written** — it could never pass, see FAIL-D and the correction in Section F's Files list; CONCERN-6 → the ratified `invite_url` deviation is now recorded in the SPEC's Out of Scope; CONCERN-7 → the resume probe for Section E uses E1's corrected pattern. Blast radius is now **21** files — see the Blast Radius derivation (22 Changed rows − 1 duplicate). **Cycle-5 supplement, additionally applied:** FAIL-D closed by the F10a/F10b split (Verification Evidence + Section F.6 steps 1/1a/1b); CONCERN-8 closed by adding `letter.html` to Section E step 1's re-derivation command (measured: 9 hits — 7 targets + 2 prose); CONCERN-9 closed by an explicit `playwright.config.ts` **non-touch** decision in Touchpoints (it contributes 0 to the blast radius).

**Cold-start facts an executor must not re-derive wrong:**

- **Do not hardcode `down_revision`.** Re-run `alembic -c apps/api/alembic.ini heads` with `DATABASE_URL` pinned to `localhost:5433` (G1/G2). Re-measured at VALIDATE cycle 3: sole head is `c5e1a9b73d20` and it is **UNTRACKED** (`??`) — G2a's stop-and-surface fires. Do not chain silently.
- **Every alembic/DB command must pin `DATABASE_URL` to localhost first.** `migrations/env.py` has no local-host guard and `.env` points at Supabase PROD.
- **Docker: binary present, daemon measured DOWN at VALIDATE cycle 3.** CLI at `/Applications/Docker.app/Contents/Resources/bin/docker` (off `PATH`). Compose services are named `postgres` (5433) and `redis` (6379) — both verified. Run the 3-step ladder in the Verification Evidence preamble; do not defer container gates.
- **Use `.venv/bin/python3.11 -m pytest`** — the `.venv/bin/pytest` shebang is broken.
- **The endpoint being extended has zero in-repo callers.** Do not go hunting for consumers besides `dashboard/waitlist/page.tsx`.
- **The invite gate keys on email, not token** (F.1). Any resumed reasoning that assumes token-at-signup is wrong.
- **`INVITE_ONLY=true` is never set by an agent** (G7). Section F.5 is an operator runbook.
- **Section A creates 7 columns, not 6** (CONCERN-2). `plan_interest` is the 7th, `String(32)`, in the SAME migration.
- **Static CTA line numbers are stale by design.** Re-grep at EXECUTE. The real concurrent collision is **`canary-onboarding_10-08-26`** (not `site-analysis-onboarding_13-08-26`) — see Section E step 1 and CONCERN-3.

**Resume mid-execution:** sections are independently verifiable. Determine position with these probes, in order. **Every probe below was executed against the live tree at cycle 3 and confirmed satisfiable** — see the audit note that follows.

| # | Section | Probe (run verbatim) | "done" signal |
|---|---|---|---|
| 1 | A | `grep -n 'business_description' apps/api/models/waitlist.py` | matches (and `grep -c 'mapped_column' ` shows the **7** new columns incl. `plan_interest`) |
| 2 | B | `grep -n 'use_case' apps/api/routers/demo.py` | matches inside `WaitlistRequest` |
| 3 | C | `ls apps/web/src/app/apply/page.tsx` | exits 0 |
| 4 | D | `grep -n 'x_handle' apps/api/routers/waitlist.py` | matches inside `list_waitlist` |
| 5 | E | `grep -nE "location\.href *= *['\"]/sign-up\|href=\"/sign-up\"" apps/web/public/beam/index.html apps/web/public/beam/onboarding-steps.js apps/web/public/beam/letter.html` | returns **nothing** |
| 6 | F | `.venv/bin/python3.11 -m pytest tests/unit/test_invite_gate.py -m unit --collect-only -q` | reports **4 collected** (not 2, not 0) |

**Probe 5 was UNSATISFIABLE before cycle 3 (CLOSES CONCERN-7) — this is the FOURTH instance of the unsatisfiable-gate class in this plan.** The old probe was `grep '/sign-up' apps/web/public/beam/*` → "returns nothing". Measured live at cycle 3: it returns **4 hits**, and can never return nothing, because three are immortal prose — `onboarding-steps.js:9` and `:555` are accurate comments describing Clerk's hosted page (the exact lines gate E1 was rewritten in cycle 1 to stop matching), and the bare `*` glob additionally drags in a **fourth file outside E1's declared scope**, `onboarding-app.js:11`. An agent resuming mid-execution would have concluded Section E was incomplete after correctly completing it, and "fixed" it by deleting accurate comments. The probe is now the corrected executable-navigation pattern already proven by gate E1 (measured: matches only `onboarding-steps.js:565` pre-rewire, nothing post-rewire; `href="/sign-in"` at `:564` correctly not matched).

**Gate-class audit performed at cycle 3 (scope: every probe in this ladder + every remaining gate command in Verification Evidence).** Each was executed against the live tree, not read. Probe 5 was the only additional instance found; no other unsatisfiable gate remains.

| Checked | Result |
|---|---|
| Ladder probes 1, 2, 3, 4, 6 | Satisfiable — each asserts a positive artifact that appears only after its section lands. Probe 6 tightened to name the exact `--collect-only` command and the exact expected count, since a bare "has 4 tests" reads green under a marker-less file that the `-m unit` lane silently excludes (the FAIL-C trap). |
| A3 | `alembic … heads` → `c5e1a9b73d20 (head)`, exactly one. ✅ |
| C1 / C2 | BRE patterns valid; C2 measured matching `middleware.ts:20`. ✅ |
| C4 | `grep -rn 'dangerouslySetInnerHTML' …` returns nothing today (rc=1) and after. ✅ |
| D3 | `href={s\.site_url}` matches L135 today (defect real), returns nothing after `safeHref`. ✅ |
| E1 | Corrected pattern measured: matches only `onboarding-steps.js:565`; prose L9/L555 and `href="/sign-in"` L564 all correctly unmatched. ✅ |
| E2 | `/apply` counts measured **0 / 0 / 0** today across all three files, so the post-rewire target of 7 is derived, not guessed. ✅ |
| E4 | **Was blind to L102** — fixed this cycle by adding the backtick to the character class (3 hits → 4 hits, measured). ✅ |
| E6 (new) | `ls …canary-react-shell-cta-invite-only_NOTE_*.md` — fails now (file absent, by design), passes once Section E writes the deliverable. Correct direction. ✅ |
| F1 / F11 | `-m unit --collect-only` measured "no tests collected (2 deselected)"; `grep -c 'pytestmark'` = **0**. Defect real, fix mandated in three places. ✅ |
| F8 | `grep -c "Access is invite-only" apps/api/dependencies.py` = `1`, and returns `1` under **both** F.3 options — so the gate never pressures an executor into the rejected `dependencies.py` edit. ✅ |
| F9 | Both negative patterns re-checked: neither can false-match the post-fix form (double-quoted literal vs template literal; `signup?invite=` vs `sign-up?invite=`). ✅ |

---

## Validate Contract

Status: CONDITIONAL
Date: 15-08-26
date: 2026-08-15
generated-by: outer-pvl
supersedes: 2026-08-15 (outer-pvl) — cycle 7 re-validation after 6 supplement cycles. The cycle-5 BLOCKED FAIL (gate F10) is verified closed by the F10a/F10b split, and this is the **first cycle in seven to find zero instances of the plan's dominant defect class**.

Parallel strategy: sequential (forced)
Rationale: 7-signal score 5/7 (S1 multi-package, S2 schema/API/auth, S5 depth requested, S6 high-risk classes, S7 21 files) -> HIGH, which recommends fan-out. This agent has **no Agent tool** in this environment, so Layer 1 (4 dimensions) and Layer 2 (6 sections) ran sequentially in-session. Mitigation carried forward from cycles 3 and 5 and applied again: **every gate command, every resume probe, and every load-bearing source claim below was EXECUTED against the live tree, never read.** That method found FAIL-D at cycle 5 and CONCERN-10 at this cycle; inspection-only passes have missed every instance.

### Verification method (cycle 7)

Cycle 6 was the first supplement to self-audit its own new text, and its self-audit holds up: every command it wrote executes in the correct direction, and its one self-caught defect (F10a's call-site assertion being unsatisfiable as first drafted) is genuinely fixed. This cycle widened the audit scope once more, to the surface that has hidden every prior instance — **command strings living outside the gate table and the probe ladder**. Method: enumerate *every* command-shaped string in the plan body mechanically (`grep -noE` for `grep|awk|ls|pytest|npm|npx|alembic|lsof|docker|git`), then execute each one. That enumeration is what surfaced CONCERN-10 (gate C4 was recorded in cycle 5's audit table with one of its two path arguments silently dropped, so C4 **as written** had never been executed by any cycle).

### Net Gate Derivation

| Layer 1 dimension | Status |
|---|---|
| Infra fit | PASS |
| Test coverage | CONCERN |
| Breaking changes | PASS |
| Security surface | PASS |

| Layer 2 section | Status |
|---|---|
| A — schema + migration | PASS |
| B — intake endpoint | PASS |
| C — `/apply` route | CONCERN |
| D — admin UI | PASS |
| E — CTA rewire | CONCERN |
| F — invite-gate hardening | PASS |

**Totals: 0 FAILs / 3 CONCERNs / 7 PASSes**

**-> Net Gate: CONDITIONAL**

Two independent things force CONDITIONAL rather than PASS, and only the first is a finding:

1. Three CONCERN-level items remain (CONCERN-10, -11, -12 below). None is an executable gate that reds against correct code; all three are one-line text corrections.
2. **The vacuous-green ban (V3 Step A1) applies structurally.** `F10b` — end-to-end browser token delivery — is a **developed** behavior (Section F.6 builds the redirect and the `localStorage` write) whose only coverage is a Known-Gap residual. Under the ban, a developed behavior resting on Known-Gap alone can never yield a terminal PASS. **Even with zero findings, this plan's ceiling is CONDITIONAL** until a Clerk-enabled Playwright harness exists. This is a classification fact, not a defect — the gap is named, justified, and carries a backlog stub.

### Cycle-6 claim verification (all 5 verified by execution — none taken on trust)

| # | Cycle-6 claim | Command executed now | Measured result | Verdict |
|---|---|---|---|---|
| 1 | No unsatisfiable F10 command survives; F10a replaces it and F10b carries no command | `grep -n 'F10' <plan>`; `grep -n 'invite-token-delivery' <plan>`; `ls apps/web/e2e/` | Every surviving `F10` mention in the plan body is a **prohibition** or a reference to F10a/F10b; the only bare-`F10` occurrences are inside the superseded contract this section replaces. `invite-token-delivery.spec.ts` appears **only** in "do NOT write" prohibitions and is **absent from disk** (13 specs present, not that one). F10b's row contains **no executable command** — it is a named residual. | ✅ **CONFIRMED** |
| 2 | F10a fails in the correct direction pre-fix | `cd apps/web && npx vitest run src/lib/signup-href.test.ts`; `grep -n 'buildSignUpHref' apps/web/src/app/signup/page.tsx`; `ls apps/web/src/lib/signup-href.ts` | `No test files found, exiting with code 1`; call-site grep **rc=1**; helper **No such file or directory**. Red now because the artifact does not exist; green only once module + test + call site all land. | ✅ **CONFIRMED — correct direction** |
| 3 | F10a's call-site assertion is satisfiable — Section F.6 step 1 genuinely instructs the executor to call `buildSignUpHref` from `signup/page.tsx` | read Section F.6 step 1 + read `apps/web/src/app/signup/page.tsx` in full | F.6 step 1 mandates `router.replace(buildSignUpHref(window.location.search))` with an import from `@/lib/signup-href`. Live source confirms the exact shape the instruction assumes: `HAS_CLERK` at **:18**, `useEffect` at **:28-32**, bare `router.replace("/sign-up")` at **:30**, interim render at **:34-40**. The instruction is implementable, and it satisfies gate **F9** simultaneously (`window.location.search` lands on the `router.replace` line; the bare literal disappears). | ✅ **CONFIRMED — self-caught defect really is fixed** |
| 4 | Section E discovery command includes `letter.html`; 9 hits | ran the command verbatim | **exactly 9 hits** — `index.html` L116/741/753/765/847 (5), `letter.html` L120 (1), `onboarding-steps.js` L9 + L555 (prose) + L565 (1 real target). Composition matches cycle 6's claim line for line. The plan correctly labels L9/L555 as expected prose noise **for a discovery command** and forbids narrowing it to E1's assertion pattern. | ✅ **CONFIRMED — 9, and correctly characterised** |
| 5 | Blast radius is 21 | counted the Touchpoints "Changed" table mechanically | **22 rows**; `apps/api/routers/waitlist.py` appears **twice** (`list_waitlist`, `invite_url`) → **21 distinct files**. `apps/web/playwright.config.ts` **absent** from Changed (0 occurrences). `apps/api/dependencies.py` **absent** from Changed (0 occurrences). | ✅ **CONFIRMED — 21 is correct** |

**Verdict on cycle 6's work:** sound in full. Every fix it applied is real, correctly applied, and independently reproduced here. Unlike cycles 3, 4 and 5, its closing claims contain no over-generalization — it did not assert "no further instances remain."

### CONCERN-10 — gate C4's command errors pre-Section-C, and had never been executed as written

**Severity: CONCERN** (loose form — safe failure direction; **cannot** red against correct code).

Gate C4 as written is:

```
grep -rn 'dangerouslySetInnerHTML' apps/web/src/app/apply/ apps/web/src/app/dashboard/waitlist/
```

`apps/web/src/app/apply/` does not exist until Section C creates it. Measured now:

- **As written, today:** `ugrep: warning: apps/web/src/app/apply/: No such file or directory`, **rc=2**.
- **Simulated post-Section-C** (both directories present, no match): **rc=1**, clean, no output → **PASS**.

So the gate is genuinely satisfiable against a correct implementation and its failure direction is safe. It is recorded because of *how* it was missed: **cycle 5's audit table lists C4 as `grep -rn 'dangerouslySetInnerHTML' apps/web/src/app/dashboard/waitlist/` — one of the two path arguments silently dropped.** C4 as actually written has therefore never been executed by any of the six prior cycles. That is the same audit-scope mechanism that produced instances 5 and 6, this time with a benign outcome.

**Executor instruction (one line, no plan edit strictly required):** run C4 only after Section C lands, per the plan's own per-section gate rule (Implementation Checklist item 7). If you run it earlier, `rc=2` + `No such file or directory` is an **ordering** signal, not a gate failure — do not "fix" it by deleting the `apply/` path from the command.

### CONCERN-11 — stale CTA counts, including in the pre-flip operator runbook

**Severity: CONCERN.** Not an executable gate; cannot red against correct code. Recorded because one of the four locations has **no gate backstop**.

Section E rewires **7 static** CTAs (`index.html` 5 + `letter.html` 1 + `onboarding-steps.js` 1) **plus 4 React CTAs** on `pricing/page.tsx` = **11 total**. Gates E2 (asserts 7) and E4 (asserts 4) encode this correctly, as does Section E's own Rollback line ("revert exactly these 7 static hrefs **plus the 4 pricing-page CTAs**"). Four other places still say 6:

| Location | Current text | Correct |
|---|---|---|
| Overview / Context (~L26) | "until the **6** CTAs are rewired (Section E)" | 7 static + 4 React = 11 |
| Blast Radius → Rollback (~L111) | "Revert **6** static CTA hrefs" | 7 static hrefs + the 4 pricing CTAs |
| **F.5 operator runbook step 2 (~L412)** | "Confirm all **6** CTAs point at `/apply` in production" | **11** — 7 static + the 4 `pricing/page.tsx` CTAs |
| Implementation Checklist item 5 (~L34) | "repoint the **5** `index.html` … and the `onboarding-steps.js` end CTA" | omits `letter.html` **and** the 4 pricing CTAs |

**Why the runbook line is the one that matters.** Items 1, 2 and 4 are gate-protected: an executor who under-delivers is caught red by E2 (expects 7) or E4 (expects 4, and the backtick in its character class is specifically what makes L102 visible). The **operator runbook has no gate** — Section F.5 steps 4-5 are human-only, run after every agent has stopped. A human following "confirm all 6 CTAs" verifies 6 of 11, misses the entire `/pricing` funnel, and flips `INVITE_ONLY=true` with an **indexed, crawlable, fully open signup path still live**. That is exactly the FAIL-B defect that cost a full validation cycle to find, re-entering through the one door no gate watches.

**Executor instruction:** when executing Section F.5, read step 2 as **"confirm all 11 account-creation CTAs point at `/apply` in production — the 7 static (`index.html` ×5, `letter.html` ×1, `onboarding-steps.js` ×1) and the 4 on `/pricing`"**. Correct the four locations above while editing Sections E and F.5; the numbers in gates E2/E4 and in Section E's Rollback are the authority.

### CONCERN-12 — Implementation Checklist item 6 omits F.6, the highest-severity item in Section F

**Severity: CONCERN.** Gate-protected (F9 and F10a both red if F.6 is skipped), so it cannot survive to EXECUTE completion — but it can waste a cycle.

Checklist item 6 reads: *"Section F — pin the invite email at sign-up, make the invite-gate 403 legible, add the 2 missing invite-gate unit tests."* That is F.2, F.3 and F.4. It **omits F.6 entirely** — the FAIL-A fix: the `invite_url` constant change at `waitlist.py:194`, the query-preserving redirect in `signup/page.tsx`, and the two new files `signup-href.ts` / `signup-href.test.ts`. F.6 is the item the plan itself calls *"Severity: highest"*, it is the reason gate F10a exists at all, and it contributes 2 of the 21 blast-radius files.

**Executor instruction:** treat Section F as **four** work items — F.2 (pin), F.3 (legible 403), F.4 (unit tests + `pytestmark`), **F.6 (invite URL + `buildSignUpHref` helper + call site)**. Section F's own Files list and F.6's body are correct and complete; only the one-line checklist summary is short.

### Minor notes (no fix required — executor awareness only)

- **NIT-F.** F.3's justification (~L318) states *"A `status` property is attached **only** on the object-`detail` path (`Object.assign(err, { detail })`)."* Measured in live `apps/web/src/lib/api.ts`: **neither** path attaches `status` — the object path attaches `detail`, the string path throws a bare `new Error(body.detail || …)`. The operative conclusion is unchanged and in fact stronger: **no status code is available at the call site on the string-detail path**, which is the invite gate's shape. The chosen message-constant fix (F.3 step 1, zero-touch) stands unaltered.
- **NIT-G.** Open Gaps says *"AC-12 has no automated leg."* Precisely: AC-12 has an automated **structural** leg (gate F8's greps, both measured satisfiable) and no automated **behavioral** leg (F5 is Agent-Probe). Read it that way.
- **NIT-C (carried, re-measured).** Resume probe 1's parenthetical `grep -c 'mapped_column'` shows the **total**, not the delta: measured **10** today, so **17** after Section A. `grep -n 'business_description'` is the actual signal.
- **NIT-E (carried, re-confirmed).** `.venv/bin/python -m pytest` and `.venv/bin/python3.11 -m pytest` both work; only the bare `.venv/bin/pytest` entry point is broken. No fix needed.

### Gate-command audit (cycle 7 — every command executed against the live tree)

Independent re-run, not a read of any prior cycle's table. Scope widened beyond gates + probes to **every command-shaped string in the plan body**, enumerated mechanically.

| Gate / probe | Command executed | Measured result | Verdict |
|---|---|---|---|
| **A1** | `awk '/^def upgrade/,/^def downgrade/'` + `grep -cE 'alter_column\|create_check_constraint\|create_index\|drop_'`, against the real additive migration `c5e1a9b73d20_add_site_profile.py` | whole-file form → **5** hits (false red on a correct `downgrade()`); awk-range form → **0** | ✅ correction independently re-proven |
| **A3** | `alembic -c apps/api/alembic.ini heads` (G1-pinned to `localhost:5433`) | `c5e1a9b73d20 (head)` — exactly one, no branching | ✅ satisfiable |
| **C1** | `grep -n '"/apply(.\*)"' apps/web/src/middleware.ts` | rc=1 (absent today) — correct direction; BRE escaping valid | ✅ satisfiable |
| **C2** | `grep -n '/onboarding(.\*)' apps/web/src/middleware.ts` | matches **L20** (`"/onboarding(.*)",  // public aha-before-commit onboarding`) | ✅ escaping correct |
| **C3** | `cd apps/web && npm run lint` | `✔ No ESLint warnings or errors`, **exit 0** — green on the current tree, so the gate asserts "stays green", not "becomes green" | ✅ satisfiable |
| **C4** | `grep -rn 'dangerouslySetInnerHTML' apps/web/src/app/apply/ apps/web/src/app/dashboard/waitlist/` — **run verbatim, both paths, for the first time in seven cycles** | today **rc=2** + `No such file or directory` (the `apply/` dir does not exist yet); simulated post-Section-C → **rc=1** clean → PASS | ⚠️ **CONCERN-10** — satisfiable against correct code, but ordering-sensitive |
| **D3** | `grep -n 'safeHref' …page.tsx` / `grep -n 'href={s\.site_url}' …page.tsx` | `safeHref` absent (rc=1); raw `href={s.site_url}` matches **L135** — defect real | ✅ both halves correct direction |
| **E1** | corrected `-E` pattern across all 3 static files | matches **only** `onboarding-steps.js:565`; prose L9/L555 and `href="/sign-in"` L564 correctly unmatched | ✅ confirmed |
| **E2** | `grep -c '/apply'` on the 3 files | **0 / 0 / 0** today; targets = `index.html` 5 + `letter.html` 1 + `onboarding-steps.js` 1 = **7** | ✅ post-rewire 7 is derived, not guessed |
| **E4** | corrected backtick class vs old class, on `apps/web/src/app/pricing/` | corrected **4** (L96, L102, L134, L280) / old **3** (blind to L102) | ✅ backtick is load-bearing, confirmed |
| **E6** | `ls …canary-react-shell-cta-invite-only_NOTE_*.md` | no match (rc=1) — fails now by design, passes once Section E writes it | ✅ correct direction |
| **F1 / probe 6** | `pytest tests/unit/test_invite_gate.py -m unit --collect-only -q` | `no tests collected (2 deselected)` — defect real | ✅ correct direction |
| **F11** | `grep -n 'pytestmark = pytest.mark.unit' …`; integration file | rc=1; `tests/integration/test_apply_intake.py` absent | ✅ correct direction |
| **F2** | `.venv/bin/python3.11 -m pytest tests/unit -m unit -q` | **1835 passed, 2 skipped, 962 deselected, 0 failed** in 7.4s | ✅ clean pre-EXECUTE baseline (re-measured, unchanged from cycle 5) |
| **F8** | `grep -n 'meErrorObj' …layout.tsx`; `grep -c "Access is invite-only" …` | `meErrorObj` absent (rc=1); `dependencies.py` = **1**, `layout.tsx` = **0** (becomes 1 after F.3) | ✅ satisfiable, and neutral between both F.3 options |
| **F9** | all four sub-assertions | `window.location.search` absent (rc=1); bare `router.replace("/sign-up")` matches **L30**; `signup?invite=` matches `waitlist.py:194`; `sign-up?invite=` absent (rc=1) | ✅ all four correct direction |
| **F10a** | `cd apps/web && npx vitest run src/lib/signup-href.test.ts`; call-site grep; `ls` the helper | `No test files found, exiting with code 1`; grep rc=1; helper absent | ✅ **red now for the right reason** — replaces the unsatisfiable F10 |
| **F10a regression baseline** | `cd apps/web && npm test` | **167 passed / 10 test files** in 1.13s | ✅ post-fix target of **170** (167+3) is arithmetically derived |
| **F10b** | — | **no command by design**; named residual, not a gate | ✅ correctly recorded |
| **Probes 1-4** | run verbatim | P1 `business_description` rc=1; P2 `use_case` rc=1; P3 `apply/page.tsx` absent; P4 `x_handle` **absent from `waitlist.py`** (not a false-done probe) | ✅ all correct direction |
| **Probe 5** | corrected pattern | matches only `onboarding-steps.js:565` | ✅ confirmed |
| **Section E step 1** | discovery command, verbatim, 3 files | **9 hits** — 7 rewire targets + 2 prose | ✅ CONCERN-8 fix confirmed |
| **G2a check** | `git status --porcelain apps/api/migrations/versions/c5e1a9b73d20*.py` | `?? …c5e1a9b73d20_add_site_profile.py` | ⚠️ still untracked — see below |

**Load-bearing source claims independently re-confirmed this cycle** (all read from live source, not carried forward):

- `apps/web/src/app/signup/page.tsx` — `HAS_CLERK` **:18**, `useEffect` **:28-32**, bare `router.replace("/sign-up")` **:30**, interim render **:34-40**. F.6 step 1 is implementable exactly as written.
- `apps/web/playwright.config.ts` — the e2e `webServer` command is literally `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY= CLERK_SECRET_KEY= npm run dev` under the comment *"Disable Clerk auth for E2E"*, with `reuseExistingServer: !process.env.CI`. **F10b's named precondition is accurate**, and the F10a-vs-Playwright decision is correct.
- `apps/web/src/middleware.ts` — `if (process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY)` guards the whole Clerk block, so with the key blank Clerk middleware is never installed; `isPublicRoute` holds `/onboarding(.*)` L20, `/signup(.*)` L22, `/sign-up(.*)` L24, `/pricing(.*)` L25.
- `apps/web/src/app/sign-up/[[...sign-up]]/page.tsx` — `HAS_CLERK` **:11**, `if (!HAS_CLERK)` early-return **:28**, `window.location.search` → `localStorage` **:36**. Both F10b halves are genuinely Clerk-gated.
- `apps/web/src/app/dashboard/layout.tsx` — `const { data: me, isError: meError } = useQuery({` at **:481**; `if (HAS_CLERK) return;` at **:533**. F.3's render-time-branch mechanism (not the effect) is required and correct.
- `apps/api/agents/prompt_safety.py:44` — `def clean_text(value: Any, max_len: int)`, `max_len` a **required positional**, exactly as Section B step 3 states.
- `apps/web/vitest.config.ts` — `environment: "node"`, `include: ["src/**/*.test.ts"]`, `@` → `./src`; `package.json` `"test": "vitest run"`; **10** existing `src/lib/*.test.ts` files. Every harness fact F10a rests on is true.
- `apps/web/src/lib/utils.ts` — 6 lines, 1 export (`cn`). The Touchpoints module-choice justification for the new `signup-href.ts` is accurate.
- `apps/web/src/app/sitemap.ts` — `staticRoutes` holds `/`, `/pricing`, `/blog`; NIT-5's `/apply` addition is coherent.

### Environment verification (cycle 7, re-measured — do not assume)

- **Docker daemon is DOWN.** `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'` returns **nothing**. Unchanged from cycles 3 and 5. This is an expected, **resolvable** state — the plan's 3-step ladder (check → `open -a Docker` + poll `docker info` → `compose up -d postgres redis`) is the executor's first action before any Hybrid gate. **No Hybrid gate may be reported environment-blocked without quoting a genuine step-2 failure.** Every Hybrid gate (A2, B1-B7, D1, F3, F6, F7) proves **nothing at all** until this is resolved.
- **Test runners re-verified:** unit lane `1835 passed / 2 skipped / 0 failed`; web vitest `167 passed / 10 files`; `npm run lint` exit 0.

### G2a — the alembic head is STILL UNTRACKED; the executor is NOT unblocked

Re-measured this cycle, all three halves:

- `alembic -c apps/api/alembic.ini heads` (G1-pinned) → `c5e1a9b73d20 (head)`, sole head, no branching.
- `git status --porcelain apps/api/migrations/versions/c5e1a9b73d20*.py` → `?? apps/api/migrations/versions/c5e1a9b73d20_add_site_profile.py`
- `git log --oneline -1 --` on that path → **empty**: the file has never been committed.

**Nothing has changed since cycle 3.** G2a's stop-and-surface **fires**. The executor must halt at Section A step 2 and surface the untracked head by name and owning plan (`site-analysis-onboarding_13-08-26`) before chaining `down_revision`. Chaining off an uncommitted parent risks a dangling migration if the sibling is rebased away — repo memories `concurrent-program-migration-collision-rechain` and `concurrent-session-rebase-eats-uncommitted-work`. **Keep G2a as written.** This is a live environment condition, not a plan defect.

### Test gates (C3 5-column form)

`strategy` carries only the three proving strategies (Fully-Automated / Hybrid / Agent-Probe). Known-Gap is never a strategy — it is a named residual carried as gap-resolution **D**.
gap-resolution legend: **A** proven now · **B** fixed by this plan's checklist · **C** deferred to a named later phase · **D** backlog test-building stub (named residual).

| criterion id | behavior proven | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-14 | migration is additive-only inside `upgrade()` | Fully-Automated | A1 (awk-range + grep) | B |
| AC-14 | migration round-trips live | Hybrid | A2 (`upgrade head` → `downgrade -1` → `upgrade head`, Postgres 5433) | B |
| AC-14 / G2 | single alembic head after chaining | Fully-Automated | A3 (`alembic heads`) | A |
| AC-3 | full application POST persists all 9 fields | Hybrid | B1 (`test_apply_intake.py`, PG+Redis) | B |
| AC-4 | resubmit fills blanks only, never overwrites | Hybrid | B2 | B |
| AC-5 | free text truncated + `<>` stripped before storage | Hybrid | B3 | B |
| AC-3, AC-5 | unknown enum → `NULL`, request still `ok` | Hybrid | B4 | B |
| AC-4 | legacy `{email}`-only body still accepted, `applied_at` `NULL` | Hybrid | B5 | B |
| AC-5 | `site_url` scheme guard + length cap | Hybrid | B6 | B |
| AC-5 (G5) | notify-email escaping of applicant text | Hybrid | B7 | B |
| AC-5, AC-6 (G5) | admin `href` scheme guard on render | Fully-Automated | D3 (`safeHref` present, raw `href={s.site_url}` gone) | B |
| AC-1 | `/apply` is public | Fully-Automated | C1 | B |
| AC-2 | `/onboarding` un-gated, comment intact | Fully-Automated | C2 | A |
| AC-1, AC-6 | web lint/typecheck clean | Fully-Automated | C3 (`npm run lint`, green today) | A |
| AC-5 (G5) | no `dangerouslySetInnerHTML` on new/changed surfaces | Fully-Automated | C4 (run **after** Section C — see CONCERN-10) | A |
| AC-1, AC-3 | unauthenticated render + submit + confirmation state | Agent-Probe | C5 | C |
| AC-6 | admin list returns the new fields | Hybrid | D1 | B |
| AC-6 | legacy `NULL` row renders as em-dash | Agent-Probe | D2 | C |
| AC-7 | no residual account-creation navigation in static assets | Fully-Automated | E1 | B |
| AC-7 | exactly 7 `/apply` hrefs across the 3 static files | Fully-Automated | E2 | B |
| AC-7 | no residual React account-creation CTAs on `/pricing` | Fully-Automated | E4 (backtick class; 4 hits pre-fix) | B |
| AC-7 | cross-plan canary CTA constraint is a durable artifact | Fully-Automated | E6 (`ls` the backlog NOTE) | B |
| AC-2, AC-7 | demo CTAs still point at `/onboarding` (no blanket replace) | Agent-Probe | E3 | C |
| AC-6, AC-7 | plan intent survives `/pricing` → `/apply?plan=` → admin row | Agent-Probe | E5 | C |
| AC-8, AC-9, AC-10, AC-11 | 4 invite-gate branch cases green under `-m unit` | Fully-Automated | F1 (with `--collect-only` = 4 asserted first) | B |
| AC-8, AC-10 | both test files carry the correct `pytestmark` | Fully-Automated | F11 | B |
| AC-9 | allowlist SQL: case-insensitivity + `status` filtering, **unmocked** | Hybrid | F7 (real `_is_email_allowlisted` vs seeded rows) | B |
| AC-10 | unit lane no regression | Fully-Automated | F2 (baseline re-measured: 1835 passed / 2 skipped / 0 failed) | A |
| AC-10, AC-13 | integration lane no regression | Hybrid | F3 | B |
| AC-9 | invite email pinned + masked at sign-up | Agent-Probe | F4 (needs a real Clerk instance) | C |
| AC-12, AC-13 | 403 renders legible recovery; token stays unconsumed (positive + negative control) | Agent-Probe | F5 (needs a real Clerk instance) | C |
| AC-12 | F.3 branch reachable under Clerk (destructure + placement) | Fully-Automated (grep) + Agent-Probe (placement read) | F8 | B |
| AC-13 | invite URL + query-preservation edits landed | Fully-Automated | F9 | B |
| AC-13 | query-preserving redirect target (`buildSignUpHref`), proven below the Clerk boundary | Fully-Automated | F10a (`npx vitest run src/lib/signup-href.test.ts` → 3 passed, + call-site grep; baseline 167 → 170) | B |
| AC-13 | **end-to-end token delivery in a browser** (`/signup?invite=` → `localStorage` → consume) | Hybrid | F10b — **known gap: requires a Clerk-enabled Playwright web server, absent in this repo; not built, no spec written** | D |
| AC-13 | one-use enforcement (second consume rejected) | Hybrid | F6 (re-run under F3) | B |

**Vacuous-green check (V3 Step A1).** All 14 SPEC ACs now carry at least one Fully-Automated or Hybrid gate — AC-13 included, since F10a proves the query-preservation computation unconditionally and F9 proves the two string edits landed. **One developed behavior still rests on a Known-Gap alone: F10b's browser-level token hop** (redirect fires → `localStorage` written → token consumed). Section F.6 *builds* that behavior, so under the vacuous-green ban the net gate **cannot** be a terminal PASS regardless of findings. It is named, justified (`playwright.config.ts:53` blanks the Clerk env repo-wide), and carries a backlog stub — a permitted residual, never a silent pass.

### Dimension findings

- **Infra fit:** PASS — the Docker 3-step ladder, compose service names (`postgres` 5433 / `redis` 6379), alembic head derivation, G1 pinning, and both `.venv` runner forms are re-verified accurate. The Playwright concern that made this CONCERN at cycle 5 is **resolved**: `playwright.config.ts` is now an explicit non-touch decision under Read-only, contributing 0 to the blast radius, and no gate depends on a Clerk-enabled e2e server any more.
- **Test coverage:** CONCERN — tier assignments are sound and **every executed gate now fails in the correct direction**, including the previously-unsatisfiable F10 (replaced by F10a). Downgraded from FAIL. Remaining concern is twofold: gate C4 is ordering-sensitive and had never been executed as written (CONCERN-10), and AC-13's browser leg plus AC-12's user-visible state have no automated behavioral proof (named residuals, gap-resolution D and C).
- **Breaking changes:** PASS — all three public-contract changes are additive (6+1 optional request fields, 7 added response keys, 7 nullable columns with no backfill/default/constraint). The intake endpoint has zero in-repo callers; the admin response has exactly one consumer, updated in the same change. `settings.invite_only` default stays `False`.
- **Security surface:** PASS — the four hostile-input paths each have a named control: `_clean_url` scheme guard + 2000-char cap on write (B6), `html.escape` on the notify email **including** the pre-existing `site_info` interpolation (B7), `safeHref` on the admin render path for legacy rows (D3, defect confirmed live at `page.tsx:135`), and `clean_text` + no `dangerouslySetInnerHTML` for free text (C4). The invite gate itself is untouched (G4); the F.1 email-not-token trace is re-verified against live source. G6 logging discipline preserved. The Gumroad self-invite path is an explicitly accepted, documented risk (F.5 / CONCERN-A), not a silent one.
- **Section A — schema + migration:** PASS — self-sufficient at 7 columns; A1's awk-range correction independently re-proven (whole-file 5 hits vs awk-range 0 on a real additive migration).
- **Section B — intake endpoint:** PASS — `clean_text` signature, the drop-to-`None` rule, and backfill semantics all re-verified against live source.
- **Section C — `/apply` route:** CONCERN — middleware entry, sitemap entry, `?plan=` wiring and the no-`layout.tsx` rule are all coherent; the sole item is gate C4's ordering sensitivity (CONCERN-10).
- **Section D — admin UI:** PASS — `x_handle` omission from `list_waitlist` confirmed real; `safeHref` gate correct in both directions.
- **Section E — CTA rewire:** CONCERN — target inventory measured correct (5+1+1 static, 4 React), the discovery command now includes `letter.html` (9 hits confirmed), and every E gate is satisfiable. The concern is the stale "6 CTAs" count surviving in the Overview, the Blast Radius rollback, the Implementation Checklist, and — with no gate backstop — the **F.5 pre-flip operator runbook** (CONCERN-11).
- **Section F — invite-gate hardening:** PASS — upgraded from FAIL. F10 is genuinely gone; F10a is satisfiable and its call-site assertion is backed by a real instruction in F.6 step 1; F10b is a correctly-recorded residual with an accurate precondition. F.1-F.9 re-verified sound. The one blemish is the checklist summary omitting F.6 (CONCERN-12), which both F9 and F10a would catch red.

### Open gaps

- **CONCERN-10** — gate C4 errors (rc=2) if run before Section C creates `apps/web/src/app/apply/`. Satisfiable post-Section-C; carried as an executor instruction.
- **CONCERN-11** — stale "6 CTAs" in the Overview, Blast Radius rollback, Implementation Checklist item 5, and **F.5 operator runbook step 2** (the only one with no gate backstop). Correct total is 11: 7 static + 4 React.
- **CONCERN-12** — Implementation Checklist item 6 omits F.6 (invite URL + `buildSignUpHref` helper + call site).
- **G2a still fires** — the sole alembic head `c5e1a9b73d20` remains **untracked and never committed**. The executor must stop and surface at Section A step 2. Not a plan defect; a live environment condition unchanged since cycle 3.
- **Docker daemon is down** — every Hybrid gate (A2, B1-B7, D1, F3, F6, F7) proves nothing until the 3-step ladder is run. Resolvable, not blocking.
- **AC-13's browser leg (F10b) is a known gap** — no Clerk-enabled Playwright harness exists in this repo. Backlog stub: `clerk-playwright-auth-harness_NOTE_{date}.md` under `process/features/onboarding-canary/backlog/` — **one stub covering F4, F5 and F10b**. Stays CONDITIONAL until the harness lands.
- **AC-12 has no automated *behavioral* leg** — F8's greps are automated and structural; F5 is Agent-Probe. Same harness root cause, same shared stub.
- **AC-9's browser prevention leg (F4)** is Agent-Probe for the same reason. Its branch half (F1) and its substance half (F7, unmocked, real DB) are automated, so AC-9 is not vacuous.
- **No load/abuse test on `/apply`** beyond the inherited `5/minute` limiter. Accepted — the limiter is pre-existing and unchanged.
- **Nothing proves the flipped state.** Every gate runs with `INVITE_ONLY=false`. AC-11 in production is operator runbook step 5, not an agent gate.
- **Cross-plan hazard is documented, not resolved.** `canary-onboarding_10-08-26` deletes `onboarding-steps.js:565` outright; E1/E2/E4 all pass green while the live CTA reverts to open signup. E6 proves only that a backlog NOTE describing the hazard exists.

### What this coverage does NOT prove

- **F2 (unit lane, 1835 passed)** does not prove any new behavior — it is a regression baseline only, and `test_invite_gate.py` is currently excluded from it entirely (F11 fixes that).
- **F1** mocks `_is_email_allowlisted`, so it proves the branch expression `if invite_only and not <constant>` and **nothing** about the allowlist SQL, case handling, or `status` filtering. F7 is what proves those.
- **F9** proves two string literals changed. It does not prove a token reaches `localStorage`, that any redirect occurs, or that `used_at` can transition.
- **F10a proves the pure function `buildSignUpHref` computes the right href, plus that `signup/page.tsx` references it.** It does **not** prove the redirect fires in a browser, that `localStorage["beam_invite"]` is written, or that the token is consumed — that whole hop is F10b, a known gap. AC-13's end-to-end delivery remains **unproven by any automated gate**.
- **A1** proves the absence of four forbidden call shapes inside `upgrade()`. It does not prove the 7 columns are the *right* 7, that types match the model, or that the migration applies. A2 proves application; nothing proves type parity between model and migration.
- **A3** proves a single head exists. It does **not** prove the parent is tracked — that is G2a's stop-and-surface, a human judgment, not a gate. The parent is currently untracked.
- **C1/C2/C4/D3/E1/E2/E4/E6/F8/F11** are greps: they prove a string is present or absent. None executes a code path. E2 in particular counts hrefs, not that any CTA navigates correctly.
- **C3 (`npm run lint`)** proves the tree compiles and lints. It does not prove the `/apply` form submits, validates, or renders the `?plan=` acknowledgement.
- **E1/E2/E4** are blind to the `canary-onboarding_10-08-26` React chat shell, which deletes `onboarding-steps.js:565` outright. All three can pass green while the live user-facing CTA reverts to open signup. E6 proves only that a **backlog note describing** this hazard exists — not that the hazard is resolved.
- **No gate covers the `/pricing` CTAs in production.** E4 greps source. The pre-flip production check is human (F.5 step 2) and currently understates the count (CONCERN-11).
- **B1-B7, D1, F3, F6, F7** are Hybrid: they prove nothing at all while the Docker daemon is down. **It is down right now**; the 3-step ladder must be run first.
- **Agent-Probes (C5, D2, E3, E5, F4, F5)** record a judgment, not an assertion. None can fail a CI run.
- **Nothing anywhere proves the `INVITE_ONLY=true` state.** The site-wide 403 failure mode named in Blast Radius is covered only by operator runbook step 5.

Gate: CONDITIONAL (0 FAILs; 3 CONCERNs, all carried into EXECUTE as named one-step instructions; 7 PASSes. All 5 cycle-6 claims verified closed by execution. **First cycle in seven with zero instances of the dominant defect class.** Terminal PASS is structurally unreachable while F10b's developed behavior rests on a Known-Gap alone — see the vacuous-green check. Route to EXECUTE.)
Accepted by: session (autonomous, /goal execution) — accepted concerns, each as an executor instruction, not a plan-blocking defect:
- **CONCERN-10** (gate C4 ordering): run C4 only after Section C creates `apps/web/src/app/apply/`; `rc=2` + `No such file or directory` before then is an ordering signal, not a gate failure. Never delete the `apply/` path to silence it.
- **CONCERN-11** (stale CTA counts): the authoritative total is **11** — 7 static (`index.html` ×5, `letter.html` ×1, `onboarding-steps.js` ×1) + 4 on `pricing/page.tsx`. Correct the Overview, the Blast Radius rollback line, Implementation Checklist item 5, and **F.5 operator runbook step 2** while editing Sections E and F.5. Gates E2 (7) and E4 (4) and Section E's own Rollback line are the authority.
- **CONCERN-12** (checklist omits F.6): treat Section F as four work items — F.2, F.3, F.4 and **F.6**. Section F's Files list and F.6's body are complete; only the one-line checklist summary is short. F9 and F10a both go red if F.6 is skipped.
- **Known gaps accepted as named residuals** (unchanged, all with the shared `clerk-playwright-auth-harness_NOTE_{date}.md` backlog stub): F10b (AC-13 browser hop, gap-resolution D), F5 (AC-12 user-visible recovery state), F4 (AC-9 browser prevention leg).

## Autonomous Goal Block

```
SESSION GOAL: Re-arm getbeam private beta — public /apply form → admin review in the existing
dashboard waitlist page → approval feeds the UNCHANGED invite-token flow. /onboarding demo stays
public. Code lands inert until all 11 account-creation CTAs are rewired (Section E — 7 static +
4 on /pricing) and an operator sets INVITE_ONLY=true.
Charter + umbrella plan: N/A — single plan (the onboarding-canary umbrella at
public-canary-funnel_11-08-26 governs a different task folder and does NOT govern this plan).
Autonomy: /goal autonomous execution — self-decide at V5-class gates; CONDITIONAL → apply fixes and
proceed; BLOCKED → backlog note + continue; subagent delegation stays mandatory (no inline
execution); irreversible/outward-facing actions without explicit contract instruction = hard stop.
Hard stop conditions / safety constraints:
- Never set INVITE_ONLY=true. That is an operator action (G7). Section F.5 steps 4-5 are human-only.
- Never run an alembic or DB command without pinning DATABASE_URL to localhost:5433 first. The repo
  environment file points at Supabase PROD and migrations/env.py has no local-host guard (G1).
- Never change _is_email_allowlisted or the gate block at dependencies.py:299-312 (G4).
- Never re-gate /onboarding in middleware.ts; the comment forbidding it stays (G3).
- Never use dangerouslySetInnerHTML on any applicant-derived value (G5).
- Never log applicant free text or a raw email; use mask_email (G6).
- If the live alembic head is still the UNTRACKED c5e1a9b73d20, stop and surface it before chaining.
Next phase: EXECUTE — gate is CONDITIONAL after 6 supplement cycles (0 FAILs, 3 CONCERNs, all carried
as executor instructions). Route to vc-execute-agent with this plan path. Start at Section A, and
expect G2a to fire at Section A step 2 (the sole alembic head c5e1a9b73d20 is still untracked).
Carry these 3 executor instructions:
- CONCERN-10: run gate C4 only AFTER Section C creates apps/web/src/app/apply/. rc=2 with
  "No such file or directory" before then is an ordering signal, not a gate failure. Never delete
  the apply/ path from the command to silence it.
- CONCERN-11: the authoritative account-creation CTA total is 11 (7 static: index.html x5,
  letter.html x1, onboarding-steps.js x1; plus 4 on pricing/page.tsx). Correct the stale "6" in the
  Overview, the Blast Radius rollback line, Implementation Checklist item 5, and F.5 operator runbook
  step 2. Gates E2 (expects 7) and E4 (expects 4) are the authority.
- CONCERN-12: Section F is FOUR work items — F.2, F.3, F.4 and F.6. Checklist item 6 omits F.6
  (invite_url constant + buildSignUpHref helper + call site), the highest-severity item in Section F.
Validate contract: inline in this plan (## Validate Contract) — Gate: CONDITIONAL, 0 FAILs /
3 CONCERNs; all 5 cycle-6 claims verified closed by execution; first cycle in seven with zero
instances of the dominant unsatisfiable-gate defect class. Terminal PASS is structurally unreachable
while F10b's developed behavior (browser token delivery) rests on a Known-Gap alone.
Execute start: [fully-auto] .venv/bin/python -m pytest tests/unit -m unit -q;
cd apps/web && npm run lint | [hybrid] docker compose -f infra/docker-compose.yml up -d postgres redis
then .venv/bin/python -m pytest tests/ -m integration -q | [probe] /apply unauthenticated render +
403 recovery state | high-risk pack: yes (auth/identity + schema/migration + public API).
```
