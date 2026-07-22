---
name: plan:evallayer-discoverability
description: "Frontend-only AI/LLM discoverability: expand JSON-LD offers to a real tiered array + add a .well-known/ai-plugin.json route handler"
date: 22-07-26
feature: marketing-site
---

# AI Discoverability — JSON-LD Offers + ai-plugin.json (SIMPLE)

**Date**: 22-07-26
**Status**: ✅ VERIFIED — shipped, committed (`5ae5bd7`), pushed to `main`
**Complexity**: SIMPLE
**Feature (conceptual)**: marketing-site (also Phase 0 of the `process/features/evallayer/` 8-phase program)

## Overview

Two independent frontend-only discoverability changes for the public marketing site. Both improve how AI/LLM crawlers and plugin-discovery agents understand Beam. Neither touches schema, auth, billing, or any API contract. SPEC and INNOVATE were intentionally skipped — the decisions are locked and the "how" is mechanical.


**TL;DR:** Two independent frontend-only changes. (1) Replace the single hardcoded `price:"0"` Offer in the homepage JSON-LD with an array of three `Offer`s (Free/Pro/Max) each carrying `availability`. (2) Add a new `.well-known/ai-plugin.json` Next.js Route Handler modeled on the existing `llms.txt/route.ts`. No schema/auth/billing/API surface. OpenAPI publishing is explicitly OUT of scope (anti-bot stance). SPEC + INNOVATE intentionally skipped — decisions are locked, the "how" is mechanical.

## Goals

1. The homepage structured data advertises all three real pricing tiers with `offers.availability` — not a single stale `$0` Offer.
2. AI agents / plugin discovery can find a valid Beam manifest at `/.well-known/ai-plugin.json`.

## Non-Goals / Out of Scope

- **OpenAPI publishing / proxy** — explicitly SKIPPED (locked decision 2). The ai-plugin manifest MUST NOT reference `api.getbeam.fyi/openapi.json` or any authenticated API endpoint. This is a deliberate anti-bot / security posture: Beam does not expose a machine-callable API surface to crawlers.
- Build-time injection of pricing values into the static HTML. The homepage is hand-authored static HTML (KISS) — values are duplicated by hand and kept in sync manually (see NOTE in Change 1).
- Any change to pricing logic, billing, or the pricing page itself.

## Touchpoints

| # | File | Lines | Change |
|---|------|-------|--------|
| 1 | `apps/web/public/beam/index.html` | JSON-LD block 25-55; `offers` object 34-39 | Replace single `Offer` object with an array of 3 `Offer`s, each adding `availability`. Hand-authored static HTML served at `/` via `next.config.mjs:10` rewrite `"/" -> "/beam/index.html"`. Not a React component. |
| 2 | `apps/web/src/app/.well-known/ai-plugin.json/route.ts` | new file | New Next.js 14 Route Handler returning the ai-plugin manifest JSON with `Content-Type: application/json`. Sibling pattern to `apps/web/src/app/llms.txt/route.ts`. |

Read-for-context (do not modify): `apps/web/src/app/llms.txt/route.ts` (route conventions), `apps/web/src/app/pricing/page.tsx:17-64` (tier source of truth), `apps/api/routers/billing.py:486-499` (charged-amount cross-check).

## Public Contracts

- **JSON-LD** (`index.html`): consumed by search engines / LLM crawlers reading `schema.org/SoftwareApplication`. Output must remain valid schema.org JSON-LD. Contract shape changes from a single `Offer` object to an array of `Offer` objects — both are valid per schema.org (`offers` accepts `Offer` or `AggregateOffer`, and an array of `Offer` is standard for multi-tier products).
- **`/.well-known/ai-plugin.json`**: new public HTTP GET endpoint returning `application/json`. New route on the public surface; no auth, no dynamic data, no PII. `"auth": { "type": "none" }`.

### Change 1 — JSON-LD offers array (exact target shape)

Replace lines 34-39 (`"offers": { ... }`) with an **array of `Offer` objects** (one per real tier), each with `price`, `priceCurrency:"USD"`, `availability:"https://schema.org/InStock"`, and a `name` for tier clarity:

```json
"offers": [
  { "@type": "Offer", "name": "Free", "price": "0",  "priceCurrency": "USD", "availability": "https://schema.org/InStock", "description": "Free to start — no credit card required" },
  { "@type": "Offer", "name": "Pro",  "price": "19", "priceCurrency": "USD", "availability": "https://schema.org/InStock", "description": "Pro — 50 identified visitors/mo" },
  { "@type": "Offer", "name": "Max",  "price": "49", "priceCurrency": "USD", "availability": "https://schema.org/InStock", "description": "Max — unlimited identified visitors" }
]
```

**Schema choice — array of `Offer` vs `AggregateOffer` (decided, mechanical):** Use an **array of `Offer`**. Justification: `AggregateOffer` (with `lowPrice`/`highPrice`) is semantically for "a number of equivalent offers" — a range for the *same* product. Beam's tiers are distinct, differently-featured products, so three explicit `Offer`s represent the pricing accurately and let crawlers surface each tier. This is the standard representation for a multi-tier `SoftwareApplication`.

**Price values used (monthly headline prices, matching the pricing page display):** Free `0`, Pro `19`, Max `49`. Yearly-billed prices ($15/$39 → $180/$468 total) are intentionally omitted from JSON-LD to keep the structured data simple and unambiguous (KISS) — the headline monthly price is what crawlers expect in an `Offer.price`.

> **SYNC NOTE (must be added as an HTML comment above the JSON-LD `offers` array):** These prices duplicate `apps/web/src/app/pricing/page.tsx` (`PLANS`, lines 17-64) and the charged amounts in `apps/api/routers/billing.py` (lines 486-499). There is no build-time injection — the homepage is static hand-authored HTML. If pricing changes, this array MUST be updated by hand. Add a comment like: `<!-- Prices mirror pricing/page.tsx PLANS + billing.py — update by hand when tiers change -->`.

### Change 2 — .well-known/ai-plugin.json route (exact target shape)

New file `apps/web/src/app/.well-known/ai-plugin.json/route.ts`, matching `llms.txt/route.ts` conventions: `export const dynamic` declaration, `export async function GET(): Promise<Response>`, `new Response(JSON.stringify(manifest, null, 2), { headers: { "Content-Type": "application/json; charset=utf-8", ... } })`. The manifest content is fully static (no fetch), so use `export const dynamic = "force-static"` (differs from `llms.txt` which is `force-dynamic` only because it fetches live posts — this route has no dynamic data). Keep the same `Cache-Control` header style.

Manifest shape (ai-plugin.json spec):

```json
{
  "schema_version": "v1",
  "name_for_human": "Beam",
  "name_for_model": "beam",
  "description_for_human": "See who visits your site. Beam identifies anonymous website visitors, enriches their profiles, and drafts retargeting outreach.",
  "description_for_model": "Beam identifies anonymous website visitors, enriches their profiles (LinkedIn, Twitter, job and company info), and drafts retargeting outreach across email and social. Anti-bot by design: the AI drafts, the human approves and sends. For a human-readable site map see https://getbeam.fyi/llms.txt.",
  "contact_email": "hello@getbeam.fyi",
  "legal_info_url": "https://getbeam.fyi/privacy",
  "auth": { "type": "none" }
}
```

Constraints (locked):
- MUST NOT include an `api` section or any `url` pointing at `api.getbeam.fyi/openapi.json` or any authenticated endpoint (decision 2 — anti-bot / no published API spec).
- Reference the existing `https://getbeam.fyi/llms.txt` inside `description_for_model` (as above) so discovery agents get the curated site map instead of an API.
- `contact_email` / `legal_info_url`: EXECUTE should confirm the correct public values from the site (candidates: `hello@getbeam.fyi`, `https://getbeam.fyi/privacy`). If a canonical support email or legal URL cannot be confirmed from existing site content, use the values above as sensible defaults and note the assumption in the EVL report — do NOT invent a private/internal address.

## Blast Radius

- **Scope:** 2 files, 1 package (`apps/web`). One edited static HTML file, one new route handler.
- **Risk class:** LOW. Frontend-only. No schema, no auth, no billing, no API contract, no migration, no PII, no external calls.
- **Security note (out of scope, recorded):** The OpenAPI-publishing option was deliberately rejected. The ai-plugin manifest is constrained to `auth: none` and points only at public discovery surfaces (`llms.txt`). No machine-callable API surface is advertised. This preserves the repo's anti-bot posture.

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Parse the `<script type="application/ld+json">` block from `apps/web/public/beam/index.html`; assert `JSON.parse` succeeds AND `offers` is an array of length 3 with each element having `price`, `priceCurrency === "USD"`, and `availability === "https://schema.org/InStock"` | Fully-Automated | Goal 1 — homepage advertises all 3 tiers with availability |
| Manual: paste rendered `/` HTML into Google Rich Results Test / schema.org validator; confirm no errors and 3 offers detected | Agent-Probe | Goal 1 — structured data is crawler-valid |
| Run the `apps/web` dev server (or build) and GET `/.well-known/ai-plugin.json`; assert HTTP 200, `Content-Type` starts with `application/json`, body `JSON.parse`s, and has `schema_version` + `auth.type === "none"` and NO `api` key | Hybrid | Goal 2 — valid manifest served, no API advertised |
| Grep assert: `route.ts` contains no reference to `openapi` or `api.getbeam.fyi` | Fully-Automated | Out-of-scope constraint (decision 2) enforced |

**Coverage note:** Both target files currently have ZERO test coverage. No existing test harness asserts JSON-LD validity or the ai-plugin route. Test gates below are proportionate lightweight additions, not a new suite.

### Test gate suggestion (proportionate — do not over-engineer)

A single lightweight Node/parse assertion is sufficient for the automated tier. Suggested minimal check (EXECUTE decides exact placement — a standalone `node` script under the task folder or a small `apps/web` test file):

```
// JSON-LD offers assertion (pseudo)
const html = read("apps/web/public/beam/index.html");
const ld = JSON.parse(extract between <script type="application/ld+json"> ... </script>);
assert(Array.isArray(ld.offers) && ld.offers.length === 3);
ld.offers.forEach(o => assert(o.priceCurrency === "USD" && o.availability === "https://schema.org/InStock"));
```

The ai-plugin route is verified by the Hybrid GET check above; a full automated E2E is not warranted for a static manifest (KISS).

## Test Infra Improvement Notes

- No JSON-LD structured-data validity check exists anywhere in `apps/web`. If structured data becomes load-bearing for SEO, consider a small parse-assertion test as a durable gate. (Recorded, not required by this plan.)
- No route-handler smoke test harness exists for the `.well-known/*` and `llms.txt` public routes. A shared lightweight "public route returns valid content-type" test could cover both. (Recorded, not required by this plan.)

## Implementation Checklist

1. In `apps/web/public/beam/index.html`, replace the `"offers"` object (lines 34-39) with the 3-element `Offer` array specified in Change 1 (Free/Pro/Max, each with `availability: "https://schema.org/InStock"`).
2. Add the `<!-- Prices mirror pricing/page.tsx PLANS + billing.py — update by hand when tiers change -->` HTML comment immediately above the `"offers"` array.
3. Verify the full JSON-LD block still `JSON.parse`s cleanly (no trailing-comma / bracket errors).
4. Create new file `apps/web/src/app/.well-known/ai-plugin.json/route.ts` following `llms.txt/route.ts` conventions (`export const dynamic = "force-static"`, `GET(): Promise<Response>`, `application/json` content-type, matching `Cache-Control`).
5. Populate the manifest with the Change 2 shape; confirm no `api` section and no `openapi`/`api.getbeam.fyi` reference; reference `https://getbeam.fyi/llms.txt` in `description_for_model`.
6. Confirm `contact_email` / `legal_info_url` values against existing site content; if unconfirmed, use the documented defaults and note the assumption.
7. Run the automated JSON-LD parse assertion (Verification Evidence row 1 + grep row 4).
8. Run the Hybrid GET check against `/.well-known/ai-plugin.json` (dev server or build) — assert 200 + content-type + valid JSON + `auth.type: none`.

## Resume and Execution Handoff

1. **Selected plan file:** `process/general-plans/completed/evallayer-discoverability_22-07-26/evallayer-discoverability_PLAN_22-07-26.md` (archived 22-07-26)
2. **Last completed step:** EXECUTE + live verification complete. Committed `5ae5bd7` (`feat(seo): tiered JSON-LD offers + public ai-plugin.json manifest`), pushed to `main`.
3. **Validate-contract status:** VALIDATE explicitly skipped (see `## Validate Contract` above); gates verified directly during EXECUTE — PASS.
4. **Supporting context loaded:** `process/context/all-context.md`, `process/context/tests/all-tests.md`, `apps/web/public/beam/index.html`, `apps/web/src/app/llms.txt/route.ts`, `apps/web/src/app/pricing/page.tsx`, `apps/api/routers/billing.py`, `apps/web/src/middleware.ts` (added mid-execution).
5. **Next step:** none for this plan — archived. Follow-up discoverability/detection work continues under `process/features/evallayer/active/evallayer_22-07-26/` (Phase 0 of that 8-phase program is this plan; Phase 1+ picks up detection/storage/dashboard work).

## Closeout Report (UPDATE PROCESS, 22-07-26)

**What shipped:** 3 files, committed `5ae5bd7`, pushed to `main`.
1. `apps/web/public/beam/index.html` — JSON-LD `offers`: single `price:"0"` → 3-element `Offer` array (Free $0 / Pro $19 / Max $49), each with `availability: "https://schema.org/InStock"`. Sync-note HTML comment added above the array.
2. `apps/web/src/app/.well-known/ai-plugin.json/route.ts` — new Route Handler, `force-static`, `auth: {type: "none"}`, references `llms.txt`, no `api`/`openapi` reference (anti-bot constraint honored).
3. `apps/web/src/middleware.ts` — `"/.well-known/(.*)"` added to Clerk `isPublicRoute` (unplanned supplement, see Deviations).

**Deviations from plan (reconciled, not re-litigated):**
- Sync-note comment placement: plan said "immediately above the offers array"; JSON has no comment syntax, so it was placed above the enclosing `<script>` block instead. Correct call — keeps `JSON.parse` valid.
- `legal_info_url`: plan default was `/privacy`; EXECUTE used the confirmed real value `https://getbeam.fyi/beam/privacy.html`.
- **Unplanned supplement — Clerk middleware exemption.** Not in the original plan; discovered live-verifying the new route (302 → sign-in instead of 200). User-approved, then applied. Process learning: a new public `.json` route can pull in an auth-surface change (middleware config) even when the route file itself contains no auth logic — see memory `clerk-well-known-json-auth-wall`. The plan's "no auth surface" VALIDATE-skip reason was accurate for the two originally-scoped files but incomplete for the feature as a whole; caught by live verification, not by a validate-contract.

**Verified:** JSON-LD parses, 3-offer array, all fields correct (automated). Route returns 200 + correct content-type + valid manifest shape (Hybrid, live-verified localhost:3000). Grep constraint (no `openapi`/`api.getbeam.fyi`) — automated pass.
**Not verified (open, non-blocking):** Google Rich Results Test / schema.org validator manual paste-check (Agent-Probe row 2 of Verification Evidence) was not run this session.

**SPEC achievement:** No standalone `*_SPEC_*.md` governs this plan (SPEC was intentionally skipped per plan Overview — "decisions are locked, the how is mechanical"). All 4 Acceptance Criteria in this plan are met (see Verified above); criterion 4 (price sync) confirmed against `pricing/page.tsx` current tiers.


## Acceptance Criteria

1. The homepage JSON-LD `offers` is an array of exactly 3 `Offer` objects (Free/Pro/Max); each has `price`, `priceCurrency === "USD"`, and `availability === "https://schema.org/InStock"`. The full JSON-LD block `JSON.parse`s without error.
2. `GET /.well-known/ai-plugin.json` returns HTTP 200 with `Content-Type: application/json`, a body that `JSON.parse`s, `schema_version` present, and `auth.type === "none"`.
3. The ai-plugin manifest contains NO `api` section and NO reference to `openapi` / `api.getbeam.fyi` (anti-bot constraint, decision 2).
4. Prices in the JSON-LD match the current tiers in `pricing/page.tsx` (Free 0 / Pro 19 / Max 49) and a sync HTML comment is present above the offers array.

## Phase Completion Rules

This is a single-phase SIMPLE plan. It is complete only when all 4 Acceptance Criteria pass their Verification Evidence gates (automated JSON-LD parse assertion + grep constraint check green; Hybrid ai-plugin GET check green). Code-only completion is `CODE DONE`, not `VERIFIED` — mark `VERIFIED` only after the gates run green and the user confirms. Next step: `ENTER VALIDATE MODE`, then `ENTER EXECUTE MODE`.

## Validate Contract

**VALIDATE explicitly skipped** — per §VALIDATE Gate skip conditions: single-purpose frontend-only change, no new dependencies/agents/runtime surfaces initially identified, user accepted the trivial/low-risk classification (Blast Radius: 2 files, 1 package, LOW risk). Stated reason at PLAN time: "no auth surface" (the JSON-LD edit and the new static route handler file were, in isolation, correctly assessed as auth-free).

**Post-hoc correction (see Deviations below):** this skip reason turned out INCOMPLETE. Live-verifying the new `/.well-known/ai-plugin.json` route surfaced a 302 redirect to sign-in — the route itself has no auth code, but Clerk's middleware matcher runs on all `.json` paths by default (see memory `clerk-well-known-json-auth-wall`), so a new public `.json` route implicitly pulled in an auth-config change (`apps/web/src/middleware.ts` `isPublicRoute` list). This was caught by live verification (Hybrid gate in Verification Evidence table), not by a validate-contract, and was user-approved before applying. No FAIL/BLOCKED state occurred — the gap was closed within the same EXECUTE pass.

Gate outcomes actually run (Verification Evidence table rows 1, 3, 4 — Fully-Automated + Hybrid):
- JSON-LD `offers` array: `JSON.parse` succeeds, 3 `Offer` elements, each `priceCurrency: "USD"` + `availability: "https://schema.org/InStock"` — PASS
- `route.ts` grep check: no `openapi` / `api.getbeam.fyi` reference — PASS
- `GET /.well-known/ai-plugin.json` on localhost:3000: HTTP 200, `Content-Type: application/json`, valid JSON, `schema_version` present, `auth.type === "none"`, no `api` key — PASS (after the middleware exemption was added)
- Row 2 (Agent-Probe: paste into Google Rich Results Test / schema.org validator) — not run this session; recorded as an open manual-verification item, non-blocking (structural JSON-LD validity was confirmed programmatically).

**Gate:** PASS (with one documented post-hoc supplement — the middleware exemption — applied and verified within the same EXECUTE pass, no separate PVL cycle needed).
