---
name: plan:agent-gateway-umbrella
description: "Consent-link agent gateway — 4-phase program converting agent-driven demand into consented, emailable leads"
date: 26-07-26
feature: agent-gateway
phase: "complex"
---

# Agent Gateway — Consent-Link Handoff (4-Phase Program)

**Complexity classification: COMPLEX / PHASE PROGRAM (4 dependent phases, each independently
shippable, Phase 1+2 low-risk, Phase 3+4 high-risk touching identity guardrails).**

Source design (already approved, read in full — do not re-derive):
`/Users/apple/.claude/plans/resolve-the-human-company-behind-purring-russell.md`

This plan is a faithful conversion of that approved design into this repo's plan artifact
format. No new architecture decisions are made here. Where the source design states a fact,
citation, or file:line anchor, it is preserved verbatim below.

**Date**: 26-07-26
**Status**: DRAFT — pending VALIDATE
**Complexity**: COMPLEX (phase program, single umbrella-style plan file covering 4 sequential phases)

## Overview

Beam currently only identifies visitors who click through to a site and run the tracking pixel.
This plan adds a second capture channel: AI agents (ChatGPT, Claude, Perplexity, Gemini) acting on
a human's behalf, converted into a consented, emailable lead via a mandatory human-click consent
link (never a bare agent assertion). The program has 4 sequential phases — data model, public
agent-readable representation, action + consent, and identity capture — detailed below.

---

## Program Goal Charter

**North star:** Beam becomes the merchant's front door for agents — publishing what a business
sells in agent-readable form, giving an agent a sanctioned action to take on a user's behalf, and
converting that action into a consented, auditable, emailable lead that flows through Beam's
existing enrichment → segment → outreach pipeline.

**Why this exists (from source design, preserve verbatim thesis):**
> The agent protocols hand a merchant an identity only at the moment of a cart. Everything before
> the cart — and every business that has no cart at all — gets nothing.

Three hard structural limits proven by primary-source research (do not re-litigate these):

| Not possible | Why |
|---|---|
| Identify the human from a crawler fetch | Web Bot Auth architecture draft **mandates** the signing key "MUST NOT be tied to a specific human individual" |
| Identify the human from a signed agent request | `Signature-Agent` proves the *vendor*, never the principal |
| Have a platform hand over the user's email | ChatGPT Apps SDK is OAuth 2.1 **without OIDC** — no ID token, no claims, only an opaque `openai/subject` |

Therefore: **the platform supplies an opaque subject; the human supplies the identity.** The whole
program is organized around making that affirmative moment happen and turning it into a verifiable,
consented record.

**Core mechanism (consent-link handoff, preserve verbatim flow):**
```
1. Agent reads the site's Beam-hosted agent manifest → learns capabilities
   ("request_demo", "get_quote", "join_waitlist", "start_checkout")
2. Agent calls the capability with intent + context (NO user PII required)
3. Beam returns a short-lived, single-use CONSENT LINK
4. Agent shows the link to its user in chat ("here's the link to request that demo")
5. Human clicks → Beam-hosted, merchant-branded consent page → enters email / confirms
6. Beam writes a CONSENT RECEIPT + an emailable identity, attributed to the agent vendor
```

**Definition of done (program level):**
- A customer can describe what they sell (Phase 1) and it renders as a machine-readable
  manifest/offers/llms.txt + MCP surface (Phase 2).
- An agent can call a sanctioned action (Phase 3) and get back a consent link — never PII.
- A human who clicks that link and submits an email becomes a real, emailable
  `IdentifiedVisitor` with `resolution_provider="agent_consent"` and
  `source_agent_visit_id IS NULL` (Phase 4), visible on the Visitors list and a new Agents-tab
  conversions funnel.
- The existing agent-origin exclusion guardrail (`is_emailable_identity`,
  `tests/unit/test_agent_origin_exclusion.py`) is regression-proven UNCHANGED throughout.

**What "verified" means (program level):**
- Every phase has a green validate-contract (V1–V7) plus the automated test suite listed in
  `## Verification` below.
- Phase 4 additionally requires the end-to-end live smoke steps (real ChatGPT-driven action →
  consent → identified visitor) as a Hybrid/Agent-Probe gate — this is an operator-run step, not
  something CI can produce, and the program is NOT `✅ VERIFIED` until it has been run at least
  once and its outcome recorded in the Phase 4 report.
- `agent_gateway_enabled` and `AgentProfile.enabled` both stay default-OFF through code-complete;
  enabling in any real environment is an explicit human operator action (mirrors
  `agent_fetch_beacon_enabled`, `agent_detection_enabled`, etc. — see
  `process/context/all-context.md` Open Questions).

**Scope tiers → phase mapping:**
- Tier 1 (Foundation — agent-facing data model) → Phase 1
- Tier 2 (Public representation — agent reads) → Phase 2
- Tier 3 (Action + consent) → Phase 3
- Tier 4 (Identity capture + dashboard) → Phase 4
- This program retires Tiers 1–4. All four tiers are in scope; none deferred to a later program
  except the explicit out-of-scope items below.

**Explicitly out of scope (deferred tier):**
- Full ACP checkout (5 REST endpoints, Delegate Authentication, payment tokens) — `start_checkout`
  hands back the merchant's own checkout URL only; a real checkout integration is a separate future
  program if a DTC customer demands it.
- Real UCP OAuth2+PKCE identity-linking endpoints (spec landed 2026-03-18, "most implementations
  remain incomplete") — Phase 2's manifest is shaped UCP-compatible for forward-compat only; actual
  identity-linking endpoints are future work.
- Gemini on-demand fetch UA verification (KG-3, pre-existing known-gap in `agent_classifier.py`) —
  `google` stays index-tier; out of scope to fix here.
- MCP server curated-directory *submission/approval* process — building `agent_mcp.py` is in
  scope; getting listed in OpenAI's/Anthropic's directories is an operator/business-development
  action outside this program's code scope.

**Hard safety constraints (non-negotiable, per phase):**
- `is_emailable_identity` in `apps/api/services/identity_classification.py` is **NEVER modified**
  — not its signature (3 params, asserted by `tests/unit/test_cadence_bot_flag.py:293`), not its
  body. `tests/unit/test_agent_origin_exclusion.py` must pass **unchanged** after every phase.
- A consent-derived identity **NEVER** sets `source_agent_visit_id`.
- The action endpoint (`POST /api/v1/agent/{site_id}/action`) **accepts no user PII** in its
  request body, ever — this is a permanent acceptance criterion, not a Phase 3-only concern.
- All writes to `IdentifiedVisitor`/`visitor_emails` from consent capture go through
  `IdentityResolver._save_identified` (`apps/api/services/identity_resolver.py:725`) — never the
  `manual` shortcut at `apps/api/routers/visitors.py:939-949`.
- Unknown/foreign `site_id` on any public agent-facing endpoint → noop/404, **never 403**.
- `agent_gateway_enabled` (global) AND `AgentProfile.enabled` (per-site) both gate every public
  agent-facing endpoint; default OFF.
- Every new source/provider value added to a closed enum (`PERSON_LEVEL_PROVIDERS`,
  `VISITOR_EMAIL_SOURCES`) must be added explicitly — these are refuse-by-default allowlists.
- Re-run `alembic heads` LIVE immediately before writing any new migration's `down_revision` —
  this repo has had repeated concurrent-session migration collisions (see Migration Guidance below).

---

## Current Execution State

- Last updated: 07-08-26 (UPDATE PROCESS reconciliation — this entry was stale; it still said
  "0 of 4, not yet started" while Phase 1+2 code has been live and EVL-green since 26-07-26)
- Current phase: 2 of 4 — CODE DONE (EVL-green with 2 known-gaps); Phase 3/4 SUPERSEDED (see
  `## Decision Record — Consent-Link (Design A) Superseded by Zero-Click AgentLead (Design B)`
  below)
- Phase 1 status: CODE DONE — EVL-green. Evidence: `AgentProfile` model registered
  (`apps/api/main.py:44`), `agent_profile` router mounted at `/api/v1/agent-profile`
  (`apps/api/main.py:52,515`); `apps/api/models/agent_profile.py` (58 lines) on disk;
  migration `a4f7c2e9d31b_add_agent_profile.py` present. Known-gap: migration live round-trip
  (Docker-gated, per `agent-gateway_REPORT_26-07-26.md`).
- Phase 1 EVL: cycle 2 HALTED_SUCCESS (`results.tsv` row 4) — full unit lane green, guardrail
  regression 36/36, boundary audit clean.
- Phase 1 report: `agent-gateway_REPORT_26-07-26.md` + `agent-gateway-evl-iteration-001_REPORT_26-07-26.md`
- Phase 2 status: CODE DONE — EVL-green. Evidence: `agent_gateway.router` mounted at
  `/api/v1/agent` (`apps/api/main.py:52,520`, live routes confirmed —
  `GET /{site_id}/manifest.json`, `/offers.json`, `/llms.txt` at
  `apps/api/routers/agent_gateway.py:67,84,129`); `agent_mcp.router` mounted at
  `/api/v1/agent` (`apps/api/main.py:52,521`) exposing exactly 3 read tools —
  `get_offers`/`get_pricing`/`check_availability` (`apps/api/routers/agent_mcp.py:99-109`), no
  action tool present (confirmed by `test_no_write_or_action_tool_is_exposed_in_phase_2`, per
  `agent-gateway_REPORT_26-07-26.md`). `agent_gateway_enabled` default OFF
  (`apps/api/config.py`).
- Phase 2 report: same two files as Phase 1 (joint EXECUTE + EVL pass).
- Phase 3 status: **SUPERSEDED, never implemented.** Confirmed on disk 07-08-26: no
  `apps/api/models/agent_action.py`, no `apps/api/models/consent_receipt.py`, no
  `apps/api/services/consent_capture.py`, no `apps/web/src/app/c/` route exist anywhere in this
  worktree. The consent-link design this plan's Phase 3/4 describe was never built — the user
  chose the alternative zero-click `AgentLead` design instead (see Decision Record below).
- Phase 4 status: **SUPERSEDED, never implemented.** Same verification method as Phase 3 —
  `identity_classification.py` on this worktree has NOT had `"agent_consent"` added to
  `PERSON_LEVEL_PROVIDERS` and `visitor_email.py` has NOT had `"agent_consent"` added to
  `VISITOR_EMAIL_SOURCES` (git history for these files, `git log --oneline -- apps/api/services/identity_classification.py`, shows no agent-gateway-attributed commit touching them).
- Next phase: none within this plan's original Phase 3/4 design — see Decision Record and the
  WS3 Merge Preconditions checklist below for the actual forward path (`feat/ws3-agent-concierge`,
  unmerged).

## Decision Record — Consent-Link (Design A) Superseded by Zero-Click AgentLead (Design B)

**Date:** 07-08-26. **Recorded by:** UPDATE PROCESS, at explicit user instruction. This section
documents a user architecture decision — it does not re-argue it.

**The situation:** two mutually incompatible, independently-built designs existed for the agent
gateway's action-taking surface (this program's Phase 3/4 vs. a separate branch's approach). The
user was presented with both and chose one.

**Design A — consent-link mandatory (REJECTED, this plan's own Phase 3/4, below).** A human must
click a consent link and submit an email; identity is then written via
`IdentityResolver._save_identified` (never the `manual` shortcut at
`apps/api/routers/visitors.py:939-949`), with `source_agent_visit_id` never set. Fully designed in
this plan's Phase 3 ("Action + Consent Link") and Phase 4 ("Identity Capture + Dashboard") sections
below — **never implemented** (confirmed on disk 07-08-26: no `agent_action.py`,
`consent_receipt.py`, `consent_capture.py`, or `apps/web/src/app/c/` exist in this worktree).

**Design B — zero-click `AgentLead` (CHOSEN).** Lives on branch `feat/ws3-agent-concierge`
(pushed to `origin/feat/ws3-agent-concierge`, **not merged** to `devjulley`/`main`). Exposes
`request_quote`/`book_demo` MCP tools that write a structurally isolated `AgentLead` row —
confirmed via `git ls-tree -r feat/ws3-agent-concierge`: `apps/api/models/agent_lead.py`,
migrations `c5e0f2b8d163_add_agent_leads_and_tool_calls.py` and `c9d2f7b4e1a6_add_consent_mode.py`,
extended `apps/api/routers/agent_gateway.py` / `agent_mcp.py`, `agent_lead_notify.py`. No
`visitor_id` column on `AgentLead`; zero imports of `IdentifiedVisitor`/`Visitor` from that model
(not independently re-verified line-by-line in this UPDATE PROCESS pass — read the branch file
directly before relying on this). No consent click at all — the agent's tool call itself creates
the lead. Code is reported DONE and EVL-green on that branch, gated behind an unrelated WS0 "wild
kill test" that never ran (see open question below).

**The accepted tradeoff (user's words, relayed verbatim — do not soften):** an agent-asserted lead
with no human confirmation click. The emailability guardrail (`is_emailable_identity`,
`tests/unit/test_agent_origin_exclusion.py`) survives because `AgentLead` is structurally
isolated from `IdentifiedVisitor`/`Visitor` — but lead quality now depends on the agent being
truthful, which this design does not verify. This is a real, accepted risk, not an oversight.

**Why Design A lost:** it required a human click-through before any lead is created, which is
higher-friction than Design B's zero-click tool call. The user weighed the resulting quality
guarantee (a human-confirmed email) against the friction cost and chose to accept lower
confidence-per-lead in exchange for a frictionless agent-to-lead path. Beam's outbound-safety
guardrails (no auto-send, human-approves-before-send) are unaffected either way — both designs
only ever produce a *draft* lead entering the existing enrichment → segment → outreach pipeline,
never an auto-sent message.

**Status of this plan's own Phase 3/4 sections below:** SUPERSEDED, not deleted, not completed.
The original design and rationale are preserved verbatim below for a future reader who needs to
understand why consent-link was the first design and what specifically it would have required
(the guardrail-preservation logic in Phase 4's Rationale section, in particular, remains a
correct and reusable reference even though this exact implementation was not built). Do not
resume EXECUTE on Phase 3/4 as written below without first re-opening this decision with the
user — it was explicitly superseded, not merely paused.

## WS3 Merge Preconditions (`feat/ws3-agent-concierge` — unmerged; do NOT perform any of these
here, checklist only)

1. **Branch is unmerged.** `feat/ws2-agent-session-classifier` is a sibling branch, and the
   `agent-native-revenue` program's umbrella docs live on the ws2 branch (per repo memory:
   `agent-native-revenue-branch-topology.md`). A merge of ws3 needs that reconciled separately —
   umbrella state currently lives split across two unpushed-to-main branches.
2. **Migration re-chain required at merge time.** The ws3 branch carries its own migrations
   (`c5e0f2b8d163_add_agent_leads_and_tool_calls.py`, `c9d2f7b4e1a6_add_consent_mode.py`) which
   must be re-chained onto the TRUE live alembic head at merge time — always re-run
   `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` live immediately before
   merging or writing any `down_revision`; never trust a value recorded in any plan or context
   doc, including this one. This repo has a documented pattern of concurrent-session migration
   collisions (see `concurrent-program-migration-collision-rechain.md` memory note).
3. **WS0 "wild kill test" gate status is an OPEN QUESTION — not decided here.** The gate
   (AC-WS3-5/6 on the ws3 branch, real ChatGPT/Claude calling a live tool over ~a week) never
   ran. This UPDATE PROCESS pass did not read the ws3 branch's own SPEC/VALIDATE artifacts in
   enough depth to determine whether the user's choice of Design B implies that gate still blocks
   merge, or is superseded by the architecture decision itself. **Do not assume either answer —
   whoever picks up the ws3 merge must explicitly resolve this against that branch's own
   validate-contract before treating the branch as merge-ready.**
4. **Regression tests that must pass unchanged after any merge:**
   - `tests/unit/test_agent_origin_exclusion.py`
   - `tests/unit/test_cadence_bot_flag.py` (asserts `is_emailable_identity` 3-param signature)
   - `tests/unit/test_handoff_emailability_separation.py`

## Pre-PVL Conflict Resolution

No phase plans have been created as separate files yet (this program uses one umbrella plan
covering all 4 phases inline, not a split-file phase program — see "Why one plan file, not four"
below). No package-conflict classification is needed at this time.

**Why one plan file, not four separate phase-plan files:** the 4 phases here are sequential and
tightly coupled (each phase's data model is a hard prerequisite for the next), not independently
parallelizable workstreams. Per `phase-programs.md`, a phase program's *artifact shape*
(umbrella + N phase files) is warranted when phases need independent concurrent validation or
independent teams. Here, Phase 2 cannot start meaningfully before Phase 1's `AgentProfile` model
exists, Phase 3 needs Phase 2's manifest, and Phase 4 needs Phase 3's `AgentAction`/consent flow —
a strict linear chain. This plan uses ONE file with 4 clearly separable, independently shippable
sections (each with its own checklist, exit gate, and Verification Evidence rows) rather than
splitting into 4 files that would have no coordination benefit. If VALIDATE or EXECUTE discovers
real parallelization opportunity (e.g., Phase 2 sub-surfaces can build concurrently), split at
that time — do not force it now.

---

## Phase Loop Progress (7-step inner loop, applies per phase)

Each phase below runs: RESEARCH → INNOVATE → PLAN-SUPPLEMENT → PVL → EXECUTE → EVL →
UPDATE-PROCESS. INNOVATE is a light confirmation step here (the design is pre-approved) rather
than an open exploration — supplement only if research surfaces a genuine option that needs
comparison.

- [ ] Phase 1 — Step 1 RESEARCH
- [ ] Phase 1 — Step 2 INNOVATE (confirm no deviation needed)
- [ ] Phase 1 — Step 3 PLAN-SUPPLEMENT
- [ ] Phase 1 — Step 4 PVL
- [ ] Phase 1 — Step 5 EXECUTE
- [ ] Phase 1 — Step 6 EVL
- [ ] Phase 1 — Step 7 UPDATE-PROCESS
- [ ] Phase 2 — Steps 1–7 (repeat)
- [ ] Phase 3 — Steps 1–7 (repeat)
- [ ] Phase 4 — Steps 1–7 (repeat)

---

## Migration Guidance (applies to ALL 3 new migrations in this program)

**Live head re-verified 26-07-26 at PLAN time:** `e6b2d4a1c837` (single head, confirmed via
`.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads`). This is already NEWER than the
`d5b1f7c3a908` recorded in `process/context/all-context.md` — the head has moved again, consistent
with the repeated concurrent-migration-collision pattern noted in memory
(`concurrent-program-migration-collision-rechain.md`).

**Mandatory rule for every migration written in this program:** immediately before writing
`down_revision` in any new migration file, re-run:
```bash
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads
```
and chain `down_revision` onto whatever the LIVE result is at that moment — never hardcode
`e6b2d4a1c837` from this plan without re-checking, since other concurrent work may move the head
again before EXECUTE runs.

**3 migrations required by this program, in dependency order:**
1. `add_agent_profile` — new `agent_profiles` table (Phase 1). Additive only.
2. `add_agent_action_consent_receipt` — new `agent_actions` + `consent_receipts` tables (Phase 3).
   Additive only. Chains after migration 1 (no dependency on migration 1's table, but keep program
   migrations chained sequentially to avoid multi-head branching within this program).
3. `extend_visitor_emails_source_check` — extends `ck_visitor_emails_source` CHECK constraint to
   add `"agent_consent"` (Phase 4). Must be lockstep with the `VISITOR_EMAIL_SOURCES` code change
   in the same phase (see `migrations/versions/a9f2c1e7b4d6_visitor_email_source_check.py:33`
   comment requiring lockstep). Offline `--sql` validate only in this sandbox; live round-trip on
   a disposable Postgres before this phase reaches VERIFIED (Docker-gated, matching the
   ingest-abuse-hardening / owned-data-layer precedent).

Each migration file must document, in its docstring: the `down_revision` value actually observed
at write time, and a note that it was re-verified live (not assumed from context docs).

---

# Phase 1 — Agent-Facing Site Content (the missing data model)

**Risk class: LOW.** New additive table + authed CRUD + a dashboard form. No public surface, no
identity writes, no auth/billing/schema-destructive risk.

## Rationale (from source design, preserved)

Today there is nowhere for a customer to declare what they sell. `Site` has only
`name/url/description/category`, and `SiteUpdate` (`apps/api/schemas/sites.py:34-46`) cannot even
edit `description`. This is the prerequisite for every later phase.

## Touchpoints

- New: `apps/api/models/agent_profile.py`
- New: Alembic migration `add_agent_profile` (see Migration Guidance above)
- New: `apps/api/schemas/agent_profile.py`
- New: `apps/api/routers/agent_profile.py` (authed CRUD, behind `verify_site_access`,
  `apps/api/dependencies.py:29`)
- New: `apps/api/routers/agent_profile.py` mounted in `apps/api/main.py`
- New: `apps/web/src/app/dashboard/agent/page.tsx` (profile editor)
- Modified: `apps/api/schemas/sites.py:34-46` (`SiteUpdate` — permit `description`/`category`,
  latent bug fix)
- Modified: `apps/web/src/lib/api.ts` + `apps/web/src/lib/api-types.ts` (client methods for the
  new authed CRUD)

## Public Contracts

- New authed endpoints (Clerk-session-gated, per-site-scoped via `verify_site_access`):
  - `GET /api/v1/agent-profile/{site_id}` — read own profile (creates empty default on first
    read, or 404 if none — decide during EXECUTE per existing CRUD conventions; not a
    creative decision left open for EXECUTE to invent, just an implementation detail to match
    existing patterns, e.g. `sites.py` router conventions)
  - `PUT /api/v1/agent-profile/{site_id}` — upsert profile fields
- `SiteUpdate` schema gains `description: Optional[str]` and `category: Optional[str]` fields
  (currently missing — this is a bug fix, not new surface, since `Site.description`/`category`
  already exist as columns).
- No public (unauthenticated) surface in this phase.

## Blast Radius

- Files: ~7 new/modified (1 model, 1 migration, 1 schema, 1 router, 1 web page, 2 client files)
- Packages: `apps/api` (models/schemas/routers/migrations), `apps/web` (dashboard page + api
  client)
- Risk class: LOW — no schema/auth/billing/migration-destructive risk (additive table only), no
  public unauthenticated endpoint, no identity-write path touched.

## Data Model

`AgentProfile` — one row per site:
- `id` (UUID, PK)
- `site_id` (FK → `sites.site_id`, unique — one profile per site. Use a real `ForeignKey("sites.site_id")` with `unique=True`, not the soft `site_id: str` no-FK pattern used by `agent_visit.py`/`campaign.py` — valid because `Site.site_id` is itself DB-unique, and appropriate here because `AgentProfile` is a genuine 1:1 record, not an append-only rollup. Document this rationale in the migration docstring so a future reader doesn't "fix" it to match the majority soft-reference style.)
- `enabled` (bool, default `False`)
- `tagline` (str, nullable)
- `long_description` (text, nullable)
- `offers` (JSONB, default `[]` — array of `{name, price, currency, billing_period,
  availability, url}`)
- `capabilities` (JSONB, default `[]` — which of `request_demo|get_quote|join_waitlist|
  start_checkout` this site exposes)
- `primary_cta` (str, nullable)
- `privacy_policy_url` (str, nullable)
- `tos_url` (str, nullable)
- `contact_email` (str, nullable)
- `created_at`, `updated_at` (standard timestamps per repo convention)

## Implementation Checklist

1. Confirm live alembic head via `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads`.
2. Create `apps/api/models/agent_profile.py` — `AgentProfile` SQLAlchemy model per Data Model
   above, following existing model conventions (UUID id, snake_case columns, FK to
   `sites.site_id`).
3. Generate the `add_agent_profile` Alembic migration (additive-only new table); document the
   observed `down_revision` in the docstring per Migration Guidance.
4. Create `apps/api/schemas/agent_profile.py` — Pydantic `AgentProfileRead`/`AgentProfileUpdate`
   models matching the fields above.
5. Fix the latent bug: extend `SiteUpdate` in `apps/api/schemas/sites.py:34-46` to permit
   `description: Optional[str]` and `category: Optional[str]`.
6. Create `apps/api/routers/agent_profile.py` — `GET`/`PUT /api/v1/agent-profile/{site_id}`,
   both behind `verify_site_access` (`apps/api/dependencies.py:29`).
7. Mount the new router in `apps/api/main.py`.
8. Add TypeScript types to `apps/web/src/lib/api-types.ts` and client methods to
   `apps/web/src/lib/api.ts` for the new authed CRUD endpoints.
9. Create `apps/web/src/app/dashboard/agent/page.tsx` — profile editor form, reusing existing
   dashboard form patterns (react-hook-form + zod, per repo convention).
10. Run Phase 1 test gates (see Verification Evidence) and fix until green.
11. Run the 5 core regression validators (`process/development-protocols/orchestration.md`
    §Regression Gate Validators) since this phase touches `apps/api/main.py` and schemas.

## Acceptance Criteria

- AC1: `AgentProfile` model exists with all fields in Data Model; migration applies cleanly
  offline (`--sql` dry-run) and round-trips on a disposable Postgres.
- AC2: `GET`/`PUT /api/v1/agent-profile/{site_id}` are reachable only by the owning user;
  requesting another user's `site_id` returns 404 (never 403, never leaks existence).
- AC3: `SiteUpdate` accepts `description` and `category` and persists them (regression test for
  the latent bug fix).
- AC4: Dashboard page at `/dashboard/agent` renders the form and successfully round-trips a save.
- AC5: No public (unauthenticated) route is introduced in this phase.

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `pytest tests/unit/test_agent_profile.py` (new) — CRUD round-trip, ownership 404 | Fully-Automated | AC1, AC2 |
| `pytest tests/unit/test_sites.py` (existing, extended) — `SiteUpdate` accepts description/category | Fully-Automated | AC3 |
| Migration offline `--sql` dry-run, EXPLICIT `<from-rev>:<to-rev>` range both directions (this repo's `upgrade head --sql`/`downgrade -1 --sql` shorthand fails mid-chain — confirmed at cadence-bot-flag EXECUTE 26-07-26, see `process/context/tests/all-tests.md`); e.g. `alembic -c apps/api/alembic.ini upgrade <live-head>:add_agent_profile --sql` and the matching downgrade range | Fully-Automated | AC1 |
| Migration live round-trip on disposable Postgres (Docker-gated) | Hybrid | AC1 |
| `cd apps/web && npm run build` — dashboard page compiles | Fully-Automated | AC4 |
| Manual dashboard smoke: fill form, save, reload, confirm persisted | Agent-Probe | AC4 |
| `grep` scan confirming no new route lacks `verify_site_access` | Fully-Automated | AC2, AC5 |

**Failing stub (Fully-Automated row 1):**
```
test("should round-trip AgentProfile CRUD and 404 on foreign site_id", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: agent profile CRUD ownership isolation")
})
```

## Test Infra Improvement Notes

(none identified yet)

## Exit Gate

Phase 1 is `VERIFIED` when: AC1–AC5 all green, the 5 core regression validators pass, and the
Phase 1 report documents migration round-trip evidence (or an explicit Docker-gated known-gap
matching the program's established precedent).

---

# Phase 2 — Public Representation Surface (agent reads)

**Risk class: LOW-MEDIUM.** All-new public read-only surface, no writes, no PII. Medium only
because it touches the anti-bot posture-reversal (see dedicated section below) and introduces the
first public agent-facing endpoints.

## Rationale (from source design, preserved)

Beam-hosted, per-site, derived entirely from Phase 1 data. All public, all cacheable.

- `GET /api/v1/agent/{site_id}/manifest.json` — capability manifest, shaped **UCP-compatible**
  (`/.well-known/ucp` conventions: declared capabilities, service versions, endpoints,
  reverse-domain namespacing) for forward-compatibility with the Google/Shopify/Amazon-backed
  standard rather than a Beam-only invention.
- `GET /api/v1/agent/{site_id}/offers.json` — ACP-feed-shaped product/offer feed (`item_id`,
  `title`, `description`, `url`, `price`, `availability`, `seller_*`).
- `GET /api/v1/agent/{site_id}/llms.txt` — narrative form for agents that read text.
- Public MCP server — `apps/api/routers/agent_mcp.py`, streamable-HTTP JSON-RPC, exposing read
  tools (`get_offers`, `get_pricing`, `check_availability`) and the action tools added in Phase 3.
  Necessary but not sufficient for distribution (both platforms use curated directories).
- Customer-side discovery snippet — one server-rendered `<link rel="alternate">` + a
  Beam-generated JSON-LD block, same copy-paste ergonomics as the pixel snippet, generated in the
  dashboard.

Reuse: route conventions and the shared cache header
`"public, max-age=0, s-maxage=3600, stale-while-revalidate=86400"` from
`apps/web/src/app/llms.txt/route.ts:53` and `.well-known/ai-plugin.json/route.ts:27`.

## Touchpoints

- New: `apps/api/routers/agent_gateway.py` (public manifest/offers endpoints — this file is
  shared with Phase 3's action endpoint; created here, extended there)
- New: `apps/api/routers/agent_mcp.py` (public MCP server, streamable-HTTP JSON-RPC)
- New: `apps/api/schemas/agent_gateway.py` (response shapes for manifest/offers)
- New: `apps/api/services/agent_gateway.py` (manifest/offers assembly from `AgentProfile` —
  shared with Phase 3's action→consent logic, extended there)
- Modified: `apps/api/main.py` (mount `agent_gateway.py` + `agent_mcp.py` routers; cache-header
  conventions)
- New: dashboard-generated discovery snippet (extends the Phase 1 dashboard page or a small
  addition to it — exact location decided at EXECUTE time following the existing pixel-snippet
  generator pattern)

## Public Contracts

- `GET /api/v1/agent/{site_id}/manifest.json` — public, unauthenticated, cached
  (`public, max-age=0, s-maxage=3600, stale-while-revalidate=86400`). Unknown/disabled site_id →
  404 or empty-but-valid manifest (decide per existing `agent_fetch_beacon_enabled` /
  `.well-known/ai-plugin.json` precedent: **404, endpoint not revealed**, matching
  `agent_gateway_enabled`/`AgentProfile.enabled` gating).
- `GET /api/v1/agent/{site_id}/offers.json` — same gating and cache posture.
- `GET /api/v1/agent/{site_id}/llms.txt` — same gating and cache posture, `text/plain`.
- MCP JSON-RPC endpoint — read-only tools (`get_offers`, `get_pricing`, `check_availability`)
  only in this phase; action tools stubbed/not-yet-wired until Phase 3 lands.
- All four endpoints gated behind `agent_gateway_enabled` (global) AND `AgentProfile.enabled`
  (per-site) — 404 when off, matching `agent_fetch_beacon_enabled` precedent
  (`apps/api/config.py:369`).

## Blast Radius

- Files: ~6 new/modified
- Packages: `apps/api` only (routers, schemas, services, main.py mount)
- Risk class: LOW-MEDIUM — first public unauthenticated agent-facing endpoints in this program,
  but strictly read-only, no PII, no writes. The posture-reversal (see below) is a documentation/
  policy risk, not a technical one.

## Explicit Posture Reversal (must be reconciled here, not silently broken)

`apps/web/src/app/.well-known/ai-plugin.json/route.ts:2-4` currently advertises **no**
machine-callable interface — "Anti-bot by design" — and
`process/features/evallayer/.../phase-00-discoverability_PLAN_22-07-26.md:60-62` records a grep
constraint asserting no `openapi`/`api.getbeam.fyi` string appears in the manifest. This phase
builds exactly such an interface.

**Resolution to write into this plan and the Phase-0 note (verbatim from source design):**
Beam's anti-bot brand means "never auto-send outreach; a human always approves" — it does not mean
"refuse to talk to agents." A structured, consented front door is the opposite of spam. Also note:
`api.getbeam.fyi/openapi.json` and `/docs` are already publicly served
(`apps/api/main.py:104-108`), so the existing posture is partly nominal already. Dogfooding the
gateway on getbeam.fyi requires updating that grep constraint deliberately, not silently.

**Checklist item for this phase:** update the Phase-0 discoverability grep constraint note
(`process/features/evallayer/.../phase-00-discoverability_PLAN_22-07-26.md`) with an explicit
annotation pointing to this program and the reconciled posture — do not edit the historical plan's
substance, append a dated cross-reference note instead (treat completed/archived plans as
read-only history per `plan-lifecycle.md`).

## Implementation Checklist

1. Create `apps/api/schemas/agent_gateway.py` — response shapes for manifest (UCP-compatible
   shape: capabilities, service versions, endpoints, reverse-domain namespacing per
   `/.well-known/ucp` conventions) and offers (ACP-feed shape: `item_id`, `title`, `description`,
   `url`, `price`, `availability`, `seller_*`).
2. Create `apps/api/services/agent_gateway.py` — pure assembly functions: `AgentProfile` row →
   manifest dict, `AgentProfile.offers` → ACP-feed offers list, → llms.txt narrative text.
3. Create `apps/api/routers/agent_gateway.py` — `GET /api/v1/agent/{site_id}/manifest.json`,
   `/offers.json`, `/llms.txt`. Public, rate-limited (reuse `@limiter.limit(...)` pattern from
   `apps/api/routers/demo.py:627`), gated by `agent_gateway_enabled` + `AgentProfile.enabled` →
   404 when off. Unknown site_id → 404 (still never 403 — 404 is correct here since these are
   genuinely-not-found resources, not tenant-owned private data; confirm this doesn't leak
   existence beyond what the manifest itself is designed to be public about).
4. Add cache headers matching `apps/web/src/app/llms.txt/route.ts:53` /
   `.well-known/ai-plugin.json/route.ts:27` convention.
5. Create `apps/api/routers/agent_mcp.py` — streamable-HTTP JSON-RPC MCP server exposing
   `get_offers`, `get_pricing`, `check_availability` read tools only (action tools added Phase 3).
   Same gating as above. Hand-write a minimal JSON-RPC 2.0 dispatcher (no new SDK dependency —
   confirmed no `mcp` package in `requirements.txt`; 3 read-only tools do not justify one). MUST
   also: apply the same `@limiter.limit(...)` pattern as the REST endpoints above (this is the
   only POST-body-accepting route in Phase 1+2 scope — do not leave it unrated); enforce a strict
   method allow-list (reject anything outside the 3 named tools with a proper JSON-RPC
   `{"error": {"code": -32601, ...}}` object); reject malformed/oversized request bodies before
   parsing (a small explicit per-route size cap suffices — no new dedicated ASGI middleware
   required); never echo raw unparsed request bytes back in an error response.
6. Mount both new routers in `apps/api/main.py`.
7. Add the customer-side discovery snippet generator (server-rendered `<link rel="alternate">` +
   JSON-LD block) to the Phase 1 dashboard page, reusing the pixel-snippet generator UX pattern.
8. Write the Phase-0 posture-reversal cross-reference note (see above).
9. Run Phase 2 test gates and fix until green.
10. Run the 5 core regression validators.

## Acceptance Criteria

- AC6: All 4 public endpoints (manifest/offers/llms.txt/MCP) return 404 when
  `agent_gateway_enabled=False` or `AgentProfile.enabled=False`, regardless of site_id validity.
- AC7: With both flags on, manifest/offers/llms.txt return correct, schema-valid content derived
  from `AgentProfile` data, with the specified cache headers.
- AC8: Unknown site_id never returns 403; returns 404.
- AC9: The MCP server's `get_offers`/`get_pricing`/`check_availability` tools return data
  matching the same `AgentProfile` source of truth as the REST endpoints (no drift between
  surfaces).
- AC10: The posture-reversal is explicitly reconciled in writing (this plan + the cross-reference
  note) — not silently contradicted.

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `pytest tests/unit/test_agent_gateway_public.py` (new) — flag-off 404, flag-on content shape, unknown-site 404 | Fully-Automated | AC6, AC7, AC8 |
| `pytest tests/unit/test_agent_mcp.py` (new) — MCP tool responses match REST responses | Fully-Automated | AC9 |
| `curl` manifest/offers/llms.txt against a locally enabled test site, inspect cache headers | Hybrid | AC7 |
| Manual review: posture-reversal note present and cross-referenced correctly | Agent-Probe | AC10 |
| `grep -c "openapi\|api.getbeam.fyi" apps/web/src/app/.well-known/ai-plugin.json/route.ts` — confirm deliberate, documented change if edited | Fully-Automated | AC10 |

**Failing stub (Fully-Automated row 1):**
```
test("should 404 all public agent endpoints when either enable flag is off", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: agent gateway public-surface flag gating")
})
```

## Test Infra Improvement Notes

(none identified yet)

## Exit Gate

Phase 2 is `VERIFIED` when AC6–AC10 are green, the 5 core regression validators pass, and the
posture-reversal note is written and cross-referenced.

---

# Phase 3 — Action + Consent Link (agent acts, human consents) — **SUPERSEDED 07-08-26**

> **SUPERSEDED, not deleted.** The user chose the zero-click `AgentLead` design
> (`feat/ws3-agent-concierge`) over this consent-link design — see
> `## Decision Record — Consent-Link (Design A) Superseded by Zero-Click AgentLead (Design B)`
> near the top of this plan. This section was never implemented (confirmed on disk 07-08-26: no
> `agent_action.py`, `consent_receipt.py`, or `apps/web/src/app/c/` exist). Preserved verbatim
> below as design history — do not resume EXECUTE on this section without re-opening the decision.

**Risk class: HIGH.** First public write-adjacent surface, first identity-adjacent data
(`AgentAction`, `ConsentReceipt`), new default-OFF flag, agent-attribution logic, and the consent
page becomes a new public route requiring a middleware change.

## Rationale (from source design, preserved)

- **`POST /api/v1/agent/{site_id}/action`** — the front door. Body: `action`
  (`request_demo|get_quote|join_waitlist|start_checkout`), `context` (free-text intent), optional
  `return_url`. **Accepts no user PII.** Returns `{consent_url, expires_at, action_id}`.
  - Auth: public + rate-limited, following `POST /api/v1/demo/waitlist`
    (`apps/api/routers/demo.py:627`) — `@limiter.limit(...)`, pydantic body, 200-with-status
    rather than 4xx for soft failures, `mask_email` logging.
  - Agent attribution: classify the caller via `classify_agent`/`classify_tier`
    (`apps/api/services/agent_classifier.py`), IP-verify where CIDR data exists
    (`agent_verification.py` — OpenAI + Perplexity only), and parse RFC 9421
    `Signature`/`Signature-Agent` headers when present (**Web Bot Auth: vendor attestation only —
    never treat as user identity**).
  - Tenant resolution: `select(Site.site_id).where(...)` → unknown ⇒ noop, **never 403**
    (`apps/api/services/agent_fetch_beacon.py:90-96`; `dependencies.py:29-42`).
  - Dormant behind `agent_gateway_enabled` *and* per-site `AgentProfile.enabled`, matching the
    `agent_fetch_beacon_enabled` precedent (`apps/api/config.py:369`) — 404 when off.
- New model `AgentAction` — `id`, `site_id`, `action`, `context`, `agent_vendor`,
  `verification_method`, `consent_token` (hashed), `expires_at`, `status`
  (`pending|consented|expired`), timestamps.
- Consent page `apps/web/src/app/c/[token]/page.tsx` — merchant-branded (name/logo/description
  from `AgentProfile`), states plainly "An AI assistant requested this on your behalf," shows the
  requested action, collects email (or confirms a prefilled one), requires an explicit submit.
  Must be added to `isPublicRoute` in `apps/web/src/middleware.ts:24-35`.
- New model `ConsentReceipt` — `action_id`, `site_id`, `email_bidx`, `email_ciphertext`,
  `agent_vendor`, `consent_text_shown` (verbatim), `ip`, `user_agent`, `consented_at`,
  `revoked_at`. This is the GDPR/CCPA compliance artifact and a genuine differentiator.

## Touchpoints

- New: `apps/api/models/agent_action.py` (`AgentAction`)
- New: `apps/api/models/consent_receipt.py` (`ConsentReceipt`)
- New: Alembic migration `add_agent_action_consent_receipt` (see Migration Guidance)
- New: `apps/api/schemas/agent_gateway.py` extended — action request/response shapes
- Modified: `apps/api/services/agent_gateway.py` — extended with action → consent-token logic
- Modified: `apps/api/routers/agent_gateway.py` — extended with `POST
  /api/v1/agent/{site_id}/action`
- Modified: `apps/api/routers/agent_mcp.py` — action tools wired (calling the same service logic)
- Modified: `apps/api/main.py` — `_PIXEL_PATHS`/CORS entry for the public action endpoint
- New: `apps/web/src/app/c/[token]/page.tsx` (consent page)
- Modified: `apps/web/src/middleware.ts:24-35` — `isPublicRoute` += `/c/(.*)`
- Modified: `apps/web/src/lib/api.ts` + `api-types.ts` — consent-page client calls

## Public Contracts

- `POST /api/v1/agent/{site_id}/action` — public, unauthenticated, rate-limited. Request body
  MUST NOT accept any PII field (no email/name/phone field in the schema at all — this is
  enforced by schema shape, not runtime validation, so it is structurally impossible to send PII
  through this endpoint). Response: `{consent_url: str, expires_at: datetime, action_id: str}`
  (or a soft-failure 200-with-status per the `demo.py:627` precedent, never a 4xx that leaks
  internal state).
- `GET /c/{token}` (web, public route) — renders the consent page; token is single-use,
  short-lived.
- `POST` from the consent page (new authed-by-token endpoint, e.g.
  `POST /api/v1/agent/consent/{token}`) — collects email, writes `ConsentReceipt`, marks
  `AgentAction.status="consented"`. This endpoint is the ONLY place in this phase that accepts
  PII, and it is gated by a valid, unexpired, unused token — not by the action endpoint.
- `is_emailable_identity` signature and behavior: UNCHANGED (verified by existing test suite,
  not touched by this phase — identity capture itself is Phase 4, but the guardrail must not be
  perturbed by any Phase 3 model addition either).

## Blast Radius

- Files: ~10 new/modified
- Packages: `apps/api` (models, migration, schemas, services, routers, main.py), `apps/web`
  (consent page, middleware, api client)
- Risk class: **HIGH** — public write-adjacent endpoint, new middleware public-route entry,
  agent-attribution/verification logic, new default-OFF flag gating a real action surface. Per
  `orchestration.md` §High-Risk Execution Handoff, this phase requires a manual-first evidence
  handoff before being treated as ready for finalize/review closure (see §High-Risk Evidence
  Pack below).

## No-PII-In-Action-Body: Structural Enforcement (permanent acceptance criterion)

This is the single most important acceptance criterion in the whole program. The action request
Pydantic schema (`apps/api/schemas/agent_gateway.py` extension) must have NO field capable of
carrying an email, name, or phone number — enforce by field allowlist (`action`, `context`,
`return_url` only) and by an explicit unit test that POSTs a payload with an `email` field and
confirms it is silently ignored/stripped (Pydantic's default extra-field behavior) rather than
accepted into any downstream write.

## Implementation Checklist

1. Confirm live alembic head (re-run `alembic heads`) before writing `down_revision`.
2. Create `apps/api/models/agent_action.py` — `AgentAction` model per Data Model above.
3. Create `apps/api/models/consent_receipt.py` — `ConsentReceipt` model per Data Model above,
   using `apps/api/services/pii_crypto.py` (`encrypt_pii`/`email_hash`) for
   `email_ciphertext`/`email_bidx` at write time.
4. Generate `add_agent_action_consent_receipt` migration (additive-only, 2 new tables); document
   observed `down_revision` per Migration Guidance.
5. Extend `apps/api/schemas/agent_gateway.py` with the action request/response shapes (strict
   field allowlist — no PII fields).
6. Extend `apps/api/services/agent_gateway.py` with: agent classification/verification call
   (`agent_classifier.py`, `agent_verification.py`), RFC 9421 `Signature`/`Signature-Agent`
   header parsing (vendor attestation only), consent-token generation (short-lived, single-use,
   hashed at rest), and `AgentAction` row creation.
7. Extend `apps/api/routers/agent_gateway.py` with `POST /api/v1/agent/{site_id}/action` —
   public, rate-limited (`@limiter.limit`, mirroring `demo.py:627`), gated by
   `agent_gateway_enabled` + `AgentProfile.enabled` → 404 when off, unknown site_id → noop
   (never 403).
8. Wire the action tools into `apps/api/routers/agent_mcp.py` (same service logic as REST).
9. Add `/c/(.*)`  to `isPublicRoute` in `apps/web/src/middleware.ts:24-35`.
10. Create `apps/web/src/app/c/[token]/page.tsx` — consent page: fetch action/profile context by
    token, render merchant branding + "An AI assistant requested this on your behalf" + the
    requested action, collect email, explicit submit button.
11. Create the token-consuming `POST` endpoint (e.g. `POST
    /api/v1/agent/consent/{token}`) — validates token (unused, unexpired), writes
    `ConsentReceipt`, marks `AgentAction.status="consented"`. **Note:** actually creating the
    `IdentifiedVisitor` from this consent is Phase 4's job — this phase's endpoint writes the
    receipt and marks status only, OR calls into a Phase-4-provided hook. Sequencing decision:
    build this endpoint's plumbing here, wire the actual identity-write call in Phase 4 once
    `consent_capture.py` exists (avoids a half-built cross-phase dependency sitting unresolved).
12. Add `_PIXEL_PATHS`/CORS entries in `apps/api/main.py` for the new public action endpoint.
13. Write the required unit test proving PII fields are structurally rejected/ignored by the
    action schema (see "No-PII-In-Action-Body" above).
14. Run Phase 3 test gates and fix until green.
15. Run the 5 core regression validators.
16. Produce the High-Risk Evidence Pack (see below) before this phase is treated as
    review-closeable.

## Acceptance Criteria

- AC11: `POST /api/v1/agent/{site_id}/action` accepts NO PII field — an `email`/`name`/`phone`
  field in the request body is structurally ignored (Pydantic extra-field behavior), never
  reaches any write path.
- AC12: Flag-off (`agent_gateway_enabled=False` or `AgentProfile.enabled=False`) → 404, endpoint
  not revealed.
- AC13: Unknown site_id → noop/404, never 403.
- AC14: Consent token is single-use (second use fails) and expiry-enforced (use after
  `expires_at` fails).
- AC15: Agent attribution correctly classifies the caller vendor via `classify_agent`/
  `classify_tier`, with IP-verification applied where CIDR data exists (OpenAI, Perplexity only)
  and `Signature-Agent` treated strictly as vendor attestation, never user identity.
- AC16: `/c/{token}` is reachable as a public route (added to `isPublicRoute`) without triggering
  Clerk auth redirect.
- AC17: Submitting the consent form writes a `ConsentReceipt` with `email_ciphertext`/`email_bidx`
  populated via `pii_crypto.py`, and marks `AgentAction.status="consented"`.
- AC18: `is_emailable_identity`'s test suite (`test_agent_origin_exclusion.py`,
  `test_cadence_bot_flag.py` arity test) passes unchanged — Phase 3 model additions do not
  perturb the guardrail.

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `pytest tests/unit/test_agent_gateway.py` (new) — flag off ⇒ 404; unknown site ⇒ noop never 403; consent token single-use; expiry enforced; no PII accepted in action body | Fully-Automated | AC11, AC12, AC13, AC14 |
| `pytest tests/unit/test_agent_classifier.py` (existing, extended) — vendor classification + IP-verify + Signature-Agent parsed as attestation only | Fully-Automated | AC15 |
| `pytest tests/unit/test_agent_origin_exclusion.py` — must still pass UNCHANGED | Fully-Automated | AC18 (regression proof) |
| `pytest tests/unit/test_cadence_bot_flag.py::test_arity` (or equivalent) — 3-param signature unchanged | Fully-Automated | AC18 |
| Playwright: `/c/{token}` loads without Clerk redirect, form submits successfully | Hybrid | AC16, AC17 |
| Migration offline `--sql` dry-run + live round-trip (Docker-gated) | Hybrid | AC11–AC17 (schema) |
| `pytest tests/integration/test_agent_gateway_integration.py` (new) — full action→consent loop against disposable Postgres | Hybrid | AC11–AC17 |

**Failing stub (Fully-Automated row 1):**
```
test("should accept no PII in action body, 404 when flag off, never 403 on unknown site, single-use expiring consent token", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: agent action endpoint core safety properties")
})
```

## High-Risk Evidence Pack (required before Phase 3 is review-closeable)

Per `orchestration.md` §High-Risk Execution Handoff, this phase touches auth-adjacent
(agent-attribution) and public-API-contract risk classes. Manual-first evidence required at
EXECUTE/EVL closeout:
1. Screenshot or transcript of the consent page rendering correctly with merchant branding.
2. `curl` transcript proving flag-off 404 and unknown-site noop.
3. `curl` transcript (or Playwright trace) proving a payload with an injected `email` field in
   the action body does not reach any write path.
4. Test run output for `test_agent_origin_exclusion.py` (proof of non-regression).
5. Migration round-trip log (or explicit documented Docker-gated known-gap).

## Test Infra Improvement Notes

(none identified yet)

## Exit Gate

Phase 3 is `VERIFIED` when AC11–AC18 are green, the 5 core regression validators pass, the
High-Risk Evidence Pack is produced, and `test_agent_origin_exclusion.py` is confirmed unchanged
and passing.

---

# Phase 4 — Identity Capture + Dashboard — **SUPERSEDED 07-08-26**

> **SUPERSEDED, not deleted.** The user chose the zero-click `AgentLead` design
> (`feat/ws3-agent-concierge`) over this consent-link design — see
> `## Decision Record — Consent-Link (Design A) Superseded by Zero-Click AgentLead (Design B)`
> near the top of this plan. This section was never implemented (confirmed on disk 07-08-26: no
> `"agent_consent"` in `PERSON_LEVEL_PROVIDERS`/`VISITOR_EMAIL_SOURCES`, no `consent_capture.py`).
> The guardrail-preservation reasoning below remains a correct, reusable reference even though
> this exact write path was not built — do not resume EXECUTE on this section without
> re-opening the decision with the user.

**Risk class: HIGH.** This phase writes to the identity system for the first time in this
program. The guardrail-preservation design is the single most load-bearing part of the whole
plan.

## Rationale (from source design, preserved verbatim — this is the load-bearing guardrail logic)

The existing guard is a boolean tripwire:

```python
# apps/api/services/identity_classification.py:81
if source_agent_visit_id is not None:   # checked FIRST, unconditional
    return False
```

Its semantics are **"this identity was INFERRED FROM agent traffic"** (resolving a company IP
yields *some employee*, not the actual visitor — a wrong-person risk). A human who clicked a
consent link and typed their own address is the **opposite** case. So:

- **Do not touch `is_emailable_identity`.** Its signature stays at exactly 3 parameters — a test
  asserts this (`tests/unit/test_cadence_bot_flag.py:293`), and the C5 literal-field-name
  tripwire (`tests/unit/test_agent_origin_exclusion.py:207-223`) will catch any rename.
- **Never set `source_agent_visit_id`** on a consent-derived identity. It was not inferred from
  agent traffic.
- **Add one new provider** `"agent_consent"` to `PERSON_LEVEL_PROVIDERS`
  (`identity_classification.py:12`). Unknown providers are refused by default
  (`tests/unit/test_outbound_identity_gate.py:31`), so this must be explicit.
- **Add one new source** `"agent_consent"` to `VISITOR_EMAIL_SOURCES`
  (`apps/api/models/visitor_email.py:20`) **plus a migration extending the
  `ck_visitor_emails_source` CHECK constraint** — the comment at
  `migrations/versions/a9f2c1e7b4d6_visitor_email_source_check.py:33` requires lockstep, and
  `normalize_source` silently rewrites unknown values to `"other"`.
- **Write through the safe path.** Use `IdentityResolver._save_identified`
  (`apps/api/services/identity_resolver.py:725`) — it validates the email, dedups/merges by
  `(site_id, lower(email))`, copies `is_abuse_flagged`, and writes ciphertext/blind index. **Do
  not copy the `manual` precedent** at `apps/api/routers/visitors.py:939-949`, which constructs
  `IdentifiedVisitor` directly and skips validation, dedup, `is_abuse_flagged` **and**
  `email_ciphertext`/`email_bidx`.
- **PII:** `encrypt_pii` + `email_hash` from `apps/api/services/pii_crypto.py` on every write
  (CORE inserts don't fire ORM hooks — see `apps/api/routers/events.py:657-662`).
- **Check suppression before anything** — `is_email_suppressed`
  (`apps/api/services/suppression.py:28`).
- **Visitor joining:** reuse the blind-index → `visitor_emails` lookup, else the deterministic
  `"ec" + email_hash(email)[:30]` visitor id, exactly as `apps/api/routers/click.py:80-137` and
  `apps/api/routers/outcomes.py:490-510` already do. This makes an agent-originated lead merge
  cleanly with the same person's later real visit.

**Dashboard** — extend the existing Agents tab (`apps/web/src/app/dashboard/agents/page.tsx`)
with an "Agent conversions" funnel: *action requested → consent link shown → consented →
enriched*, split by vendor. Plus an "Agent-sourced" filter on the Visitors list, reusing the
`ai_source` facet pattern (`apps/web/src/app/dashboard/visitors/page.tsx:547-568`).

## Touchpoints

- New: `apps/api/services/consent_capture.py` (consent → identity, the write path for this phase)
- New: Alembic migration `extend_visitor_emails_source_check` (see Migration Guidance)
- Modified: `apps/api/services/identity_classification.py` — **ONLY** add `"agent_consent"` to
  `PERSON_LEVEL_PROVIDERS` (line 12 area); `is_emailable_identity` itself (line 56) is untouched
- Modified: `apps/api/models/visitor_email.py:20` — add `"agent_consent"` to
  `VISITOR_EMAIL_SOURCES`
- Modified: Phase 3's consent-token-consuming endpoint (`POST /api/v1/agent/consent/{token}`) —
  now calls `consent_capture.py` to perform the actual identity write
- Modified: `apps/web/src/app/dashboard/agents/page.tsx` — Agent conversions funnel
- Modified: `apps/web/src/app/dashboard/visitors/page.tsx:547-568` — Agent-sourced filter (reuse
  `ai_source` facet pattern)

## Public Contracts

- No new public endpoints in this phase — this phase implements the write logic behind Phase 3's
  already-public consent-consuming endpoint.
- New provider value `"agent_consent"` added to `PERSON_LEVEL_PROVIDERS` (closed allowlist,
  explicit opt-in required).
- New source value `"agent_consent"` added to `VISITOR_EMAIL_SOURCES` (closed allowlist, CHECK
  constraint extended in lockstep).
- **`is_emailable_identity`'s public contract (3-param signature, behavior) is explicitly
  UNCHANGED** — this is itself a contract worth naming: any future phase or program that touches
  this function must re-read this plan's guardrail section first.

## Blast Radius

- Files: ~7 new/modified
- Packages: `apps/api` (services, models, migration), `apps/web` (2 dashboard pages)
- Risk class: **HIGH** — this is the identity-system write path. Per `orchestration.md`
  §High-Risk Execution Handoff, requires manual-first evidence before review closure.

## Implementation Checklist

1. Confirm live alembic head (re-run `alembic heads`) before writing `down_revision`.
2. Add `"agent_consent"` to `PERSON_LEVEL_PROVIDERS` in
   `apps/api/services/identity_classification.py` (near line 12) — **do not touch any other line
   of `identity_classification.py`, especially not `is_emailable_identity` at line 56**.
3. Add `"agent_consent"` to `VISITOR_EMAIL_SOURCES` in `apps/api/models/visitor_email.py:20`.
4. Generate `extend_visitor_emails_source_check` migration — extends `ck_visitor_emails_source`
   CHECK constraint to include `"agent_consent"`, in lockstep with step 3 (same commit/PR, per
   the `a9f2c1e7b4d6:33` lockstep comment). Document observed `down_revision` per Migration
   Guidance.
5. Create `apps/api/services/consent_capture.py`:
   a. Check `is_email_suppressed` (`apps/api/services/suppression.py:28`) first — abort if
      suppressed.
   b. Encrypt PII via `encrypt_pii`/`email_hash` (`apps/api/services/pii_crypto.py`).
   c. Resolve/join visitor via blind-index → `visitor_emails` lookup, else deterministic
      `"ec" + email_hash(email)[:30]` visitor id, exactly matching
      `apps/api/routers/click.py:80-137` / `apps/api/routers/outcomes.py:490-510`.
   d. Call `IdentityResolver._save_identified` (`apps/api/services/identity_resolver.py:725`)
      with `provider="agent_consent"`, `source_agent_visit_id=None` (explicit, never populated).
      **Do not** construct `IdentifiedVisitor` directly (do not replicate the `manual` shortcut
      at `apps/api/routers/visitors.py:939-949`).
6. Wire Phase 3's `POST /api/v1/agent/consent/{token}` endpoint to call
   `consent_capture.py` after writing the `ConsentReceipt`.
7. Extend `apps/web/src/app/dashboard/agents/page.tsx` with the "Agent conversions" funnel
   (action requested → consent link shown → consented → enriched, split by vendor).
8. Extend `apps/web/src/app/dashboard/visitors/page.tsx:547-568` with an "Agent-sourced" filter,
   reusing the `ai_source` facet pattern.
9. Write the new emailability regression test: an `agent_consent` identity IS emailable; an
   identity carrying `source_agent_visit_id` is STILL NOT, even with the new provider present.
10. Run the FULL existing identity-guardrail test suite unchanged and confirm all green:
    `test_agent_origin_exclusion.py`, `test_outbound_identity_gate.py`,
    `test_cadence_bot_flag.py` (arity tripwire).
11. Run Phase 4 test gates and fix until green.
12. Run the 5 core regression validators.
13. Produce the High-Risk Evidence Pack for this phase (see below).
14. Run the End-to-End Live Smoke (see below) — this is an operator-run Hybrid/Agent-Probe gate,
    not something CI produces; record outcome in the Phase 4 report.

## Acceptance Criteria

- AC19: `is_emailable_identity` signature and body are byte-for-byte unchanged from before this
  phase (diff review, not just tests).
- AC20: A consent-derived `IdentifiedVisitor` has `resolution_provider="agent_consent"` and
  `source_agent_visit_id IS NULL`.
- AC21: `is_emailable_identity(...)` returns `True` for an `agent_consent`-sourced identity.
- AC22: `is_emailable_identity(...)` returns `False` for ANY identity carrying
  `source_agent_visit_id`, even one that also happens to have `provider="agent_consent"`
  (defense-in-depth — should not be reachable via this phase's code paths, but the test proves
  the guardrail itself still wins regardless of provider).
- AC23: `consent_capture.py` checks `is_email_suppressed` before any write; a suppressed email is
  never written as an `IdentifiedVisitor`.
- AC24: All writes go through `IdentityResolver._save_identified` — verified by code review (no
  direct `IdentifiedVisitor(...)` construction in `consent_capture.py`) and by a test asserting
  dedup/merge behavior on duplicate consent for the same email.
- AC25: `ck_visitor_emails_source` CHECK constraint accepts `"agent_consent"` after migration;
  rejects arbitrary unlisted values (regression of existing constraint behavior).
- AC26: Dashboard "Agent conversions" funnel renders and reflects real `AgentAction`/
  `ConsentReceipt`/`IdentifiedVisitor` state.
- AC27: Visitors list "Agent-sourced" filter correctly isolates `agent_consent`-derived visitors.
- AC28: End-to-End Live Smoke (below) completes successfully at least once, with outcome recorded
  in the Phase 4 report.

## End-to-End Live Smoke (the real proof — preserved verbatim from source design)

1. Enable `agent_gateway_enabled` + `AgentProfile.enabled` for `beam_getbeam_fyi`.
2. `curl` the manifest and offers endpoints; confirm shape and cache headers.
3. Drive real ChatGPT: "Using getbeam.fyi's agent interface, request a demo for me." Confirm an
   `AgentAction` row with `agent_vendor=openai`.
4. Open the returned consent link in a browser, submit an email, and confirm: a `ConsentReceipt`
   row, an `IdentifiedVisitor` with `resolution_provider="agent_consent"` and
   `source_agent_visit_id IS NULL`, and `is_emailable_identity(...) is True`.
5. Confirm the lead appears on the Visitors list and the Agents tab conversions funnel.

**Operator note (preserved verbatim):** enabling in production is a human action (env flag +
per-site toggle). Claude cannot mutate Railway/Vercel config — the auto-mode classifier blocks
it. This step is Hybrid/Agent-Probe by necessity, not Fully-Automated.

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `pytest tests/unit/test_consent_capture.py` (new) — provider is `agent_consent`; `source_agent_visit_id` is None; ciphertext + blind index written; suppression checked first; duplicate consent merges | Fully-Automated | AC20, AC23, AC24 |
| `pytest tests/unit/test_agent_origin_exclusion.py` — must still pass UNCHANGED | Fully-Automated | AC19, AC22 (regression proof) |
| `pytest tests/unit/test_outbound_identity_gate.py` — unknown providers still refused by default | Fully-Automated | AC19 (regression proof, refuse-by-default) |
| `pytest tests/unit/test_cadence_bot_flag.py` — arity tripwire unchanged | Fully-Automated | AC19 |
| New emailability test: `agent_consent` identity IS emailable; `source_agent_visit_id`-carrying identity STILL NOT, even with new provider | Fully-Automated | AC21, AC22 |
| Migration offline `--sql` dry-run + live round-trip (Docker-gated) — CHECK constraint accepts new value, rejects arbitrary values | Hybrid | AC25 |
| `pytest tests/integration/test_agent_gateway_integration.py` — full loop against disposable Postgres | Hybrid | AC20, AC24 |
| Dashboard manual check: Agent conversions funnel + Agent-sourced filter render correctly against seeded data | Agent-Probe | AC26, AC27 |
| End-to-End Live Smoke (5 steps above, real ChatGPT + real consent submission) | Agent-Probe (operator-run) | AC28 |
| `npx vitest run` for any new pure web helper; `cd apps/web && npm run build` | Fully-Automated | AC26, AC27 (compile-time) |

**Failing stub (Fully-Automated row 1):**
```
test("should write agent_consent identity with source_agent_visit_id=None via _save_identified, checking suppression and dedup first", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: consent_capture identity write path")
})
```

**Failing stub (Fully-Automated row 5 — the guardrail-preservation test):**
```
test("should return True for agent_consent identity and False for any identity with source_agent_visit_id set, regardless of provider", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: is_emailable_identity guardrail unchanged under new provider")
})
```

## High-Risk Evidence Pack (required before Phase 4 is review-closeable)

Per `orchestration.md` §High-Risk Execution Handoff — this phase is the identity-write path,
the highest-risk phase in the program:
1. Diff of `identity_classification.py` showing ONLY the `PERSON_LEVEL_PROVIDERS` line changed —
   `is_emailable_identity` body byte-identical to before.
2. Full test run output for `test_agent_origin_exclusion.py`, `test_outbound_identity_gate.py`,
   `test_cadence_bot_flag.py` (all passing, unchanged).
3. New emailability test output (AC21/AC22).
4. Migration round-trip log for the CHECK constraint extension.
5. End-to-End Live Smoke outcome (real ChatGPT run) — screenshots/logs of each of the 5 steps, or
   an honest note if the operator has not yet run it (in which case Phase 4 is CODE DONE, not
   VERIFIED, until this is run).

## Test Infra Improvement Notes

(none identified yet)

## Exit Gate

Phase 4 — and the whole program — is `VERIFIED` when AC19–AC28 are green, all 3 identity-guardrail
regression suites pass unchanged, the High-Risk Evidence Pack is produced, and the End-to-End Live
Smoke has been run at least once with outcome recorded. Until the Live Smoke runs, phase status is
`CODE DONE`, not `VERIFIED` — this distinction must be stated honestly in the phase report.

---

## Risks and Honest Gaps (preserved verbatim from source design — do not soften)

- **Distribution is the real risk, not the build.** ChatGPT and Claude reach third-party MCP
  servers only through **curated directories** (OpenAI Plugin directory; Anthropic Connectors
  Directory with security review). There is no permissionless discovery path. Mitigation:
  per-merchant connectors with Beam as infrastructure (a single "Beam lead-harvesting" connector
  would likely be rejected under Anthropic's advertising-vehicle ban), plus the manifest/JSON-LD
  path which needs no approval.
- **UCP Identity Linking window is closing.** The OAuth2+PKCE identity-linking spec landed
  2026-03-18 with heavyweight backing and "most implementations remain incomplete." Google/Shopify
  will eventually make it one-click in Merchant Center. Shaping the Phase-2 manifest
  UCP-compatible buys forward-compatibility; a later phase can add real UCP identity-linking
  endpoints for merchants that have accounts.
- **Consent legality when a machine relays intent is untested.** No case law. This design
  deliberately requires the *human* to click and submit, which is the most defensible
  construction available and is why the agent is never trusted to assert consent.
- **Commerce side is deliberately thin.** Since March 2026 OpenAI routes purchases to the
  merchant's own checkout, so `start_checkout` should hand back the merchant's checkout URL rather
  than reimplement ACP payments — full ACP checkout (5 REST endpoints, Delegate Authentication,
  payment tokens) is a separate program if a DTC customer demands it.
- **Gemini on-demand fetches are still missed** (KG-3): the live Gemini browse UA is
  undocumented, so `google` is pinned index-tier in `agent_classifier.py`. Test with ChatGPT or
  Perplexity instead.
- **Anthropic/Google IP CIDR data does not ship**, so those vendors stay `ua-only` confidence.

None of these risks are blockers for shipping Phases 1–3; they inform Phase 4's End-to-End Live
Smoke choice of vendor (use ChatGPT/Perplexity, not Gemini) and set expectations for post-launch
distribution effort as separate, non-code work.

---

## Phase Completion Rules

- A phase may be marked `CODE DONE` when its Implementation Checklist is complete and its
  Fully-Automated + Hybrid Verification Evidence gates are green.
- A phase may be marked `✅ VERIFIED` only after: all Acceptance Criteria for that phase are met,
  the 5 core regression validators pass (`process/development-protocols/orchestration.md`
  §Regression Gate Validators), and — for Phase 3 and Phase 4 — the High-Risk Evidence Pack is
  produced. `✅ VERIFIED` additionally requires the phase report to state explicit
  user-confirmation language (the user has reviewed and confirmed the phase's outcome working as
  intended) before that status is written anywhere durable.
- Phase 4 (and therefore the whole program) may be marked `✅ VERIFIED` only after the End-to-End
  Live Smoke has been run at least once by a human operator and its outcome recorded in the Phase
  4 report, with explicit user confirmation. Before that, Phase 4 stays `CODE DONE`.
- Test context for all phases: consult `process/context/tests/all-tests.md` (the tests-group
  router) for runner selection, commands, and Docker/disposable-Postgres setup before running any
  Hybrid-tier gate in this plan — see `TESTING.md` (repo root) for the docker-compose setup this
  program's migration round-trips depend on.

## Validate Contract

**SCOPE OF THIS VALIDATE PASS: Phase 1 + Phase 2 ONLY.** Phase 3 (action/consent link) and
Phase 4 (identity capture + guardrail) are explicitly OUT OF SCOPE for this contract — they are
higher-risk (HIGH risk class each) and require their own dedicated VALIDATE pass before EXECUTE
touches them. Any gate, instruction, or acceptance criterion below that is not tagged Phase 1 or
Phase 2 does not apply here. EXECUTE must stop at the end of Phase 2's Exit Gate and return to
VALIDATE before starting Phase 3.

Status: CONDITIONAL
Date: 26-07-26
date: 2026-07-26
generated-by: outer-pvl

Parallel strategy: sequential
Rationale: Signal count 2/7 (S6 partial — Phase 1+2 alone are LOW/LOW-MEDIUM risk, not HIGH;
S7 — 13 files across the two in-scope phases). Two-agent Layer-2 read (Section A + Section B)
was run as lightweight parallel subagents; full-program strategy (agent team) is deferred to
when Phase 3/4 are validated, since those raise the risk class to HIGH.

Test gates (C3 5-column table — Phase 1 + Phase 2 only):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1 | `AgentProfile` CRUD round-trips; migration applies offline both directions | Fully-Automated | `pytest tests/unit/test_agent_profile.py` (new) + `alembic -c apps/api/alembic.ini upgrade <live-head>:add_agent_profile --sql` and matching downgrade range (explicit range required — see E4) | B |
| AC1 | Migration round-trips on a real Postgres | Hybrid | `alembic upgrade head` → `downgrade -1` → `upgrade head` on a disposable Postgres container | D |
| AC2 | Foreign `site_id` on authed CRUD returns 404, never 403 | Fully-Automated | `pytest tests/unit/test_agent_profile.py::test_foreign_site_404` (new) | A |
| AC3 | `SiteUpdate` persists `description`/`category` (latent bug fix) | Fully-Automated | `pytest tests/unit/test_sites.py` (existing, extended) | A |
| AC4 | Dashboard page compiles and round-trips a save | Fully-Automated + Agent-Probe | `cd apps/web && npm run build` + manual smoke: fill form, save, reload, confirm persisted | A |
| AC5 | No public route introduced in Phase 1 | Fully-Automated | `grep` scan confirming every new Phase 1 route carries `verify_site_access` | A |
| AC6 | All 4 Phase 2 public endpoints 404 when either flag is off | Fully-Automated | `pytest tests/unit/test_agent_gateway_public.py` (new) | B |
| AC7 | Flag-on: manifest/offers/llms.txt return correct schema-valid content + cache headers | Fully-Automated + Hybrid | `pytest tests/unit/test_agent_gateway_public.py` (schema) + `curl` against a locally enabled test site (headers) | A / D |
| AC8 | Unknown site_id never 403 | Fully-Automated | same suite, unknown-site case | A |
| AC9 | MCP tool responses match REST responses (no drift) | Fully-Automated | `pytest tests/unit/test_agent_mcp.py` (new) | B |
| AC9b (new, this contract) | MCP endpoint rejects unknown methods, oversized/malformed bodies, and is rate-limited | Fully-Automated | `pytest tests/unit/test_agent_mcp.py::test_method_allowlist_and_body_guard` (new — add to the same file per E3) | B |
| AC10 | Posture-reversal explicitly reconciled in writing | Agent-Probe | Manual review: cross-reference note present and linked from Phase-0 plan | A |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist, incl. the 3 edits this contract made)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

Legacy line form (retained so existing validate-contract consumers still parse):
- Phase 1 CRUD/migration: Fully-automated: `pytest tests/unit/test_agent_profile.py` | Hybrid: migration round-trip on disposable Postgres (precondition: Docker running) | known-gap: documented (Docker-gated, matches program precedent)
- Phase 2 public surface: Fully-automated: `pytest tests/unit/test_agent_gateway_public.py`, `pytest tests/unit/test_agent_mcp.py` | Hybrid: `curl` cache-header check (precondition: locally enabled test site) | agent-probe: posture-reversal note review

Dimension findings:
- Infra fit: PASS — additive table, authed CRUD reuses `verify_site_access`; public reads live on
  the API host (FastAPI), not the web app, so no Clerk-middleware exposure in this scope (that's
  Phase 3's `/c/{token}` concern only). No container/infra surface touched.
- Test coverage: CONCERN → resolved in this contract — migration offline dry-run gate was
  underspecified (vague "both directions"); this repo's alembic offline `--sql` shorthand
  (`upgrade head`/`downgrade -1`) fails mid-chain (confirmed at cadence-bot-flag EXECUTE
  26-07-26). Plan text fixed (P2) to require an explicit `<from-rev>:<to-rev>` range.
- Breaking changes: PASS — `SiteUpdate` extension is additive (fixes a latent bug, adds optional
  fields); no existing consumer of `SiteUpdate`/`Site` changes behavior. No existing public
  contract is altered.
- Security surface: CONCERN → resolved in this contract — the Phase 2 MCP JSON-RPC endpoint
  (`agent_mcp.py`) is the only POST-body-accepting route in Phase 1+2 scope and the plan's
  original checklist item 5 said only "same gating as above" (enabled-flag gating), with no
  rate-limit, method allow-list, or malformed/oversized-body handling named. Plan text fixed (P3)
  to require: `@limiter.limit(...)` parity with the REST endpoints, a strict 3-method allow-list
  with proper JSON-RPC error objects for anything else, a body-size guard before parsing, and no
  raw-input echo in error responses. Tenant-exposure rule (never 403, only 404/noop) is correctly
  and consistently applied across both phases (verified against `verify_site_access` and
  `agent_fetch_beacon.py`'s noop precedent).
- Section A feasibility (Phase 1): PASS with 1 concern resolved — mechanical feasibility HIGH
  (all touchpoint files exist, `SiteUpdate` line citation off by ~1 line — cosmetic drift, no
  gap — `verify_site_access` confirmed at `apps/api/dependencies.py:29`, returns 404 not 403).
  Gap found: `site_id` FK strategy was ambiguous against two competing repo precedents (soft
  `site_id: str` no-FK in `agent_visit.py`/`campaign.py` vs hard `ForeignKey("sites.id")` in
  `blog_post.py`) — neither matches the plan's stated "FK → sites.site_id" exactly. Resolved:
  plan text fixed (P1) to mandate a real `ForeignKey("sites.site_id")` with `unique=True` and a
  documented rationale, since `Site.site_id` is itself DB-unique and `AgentProfile` is a genuine
  1:1 record (not an append-only rollup like the soft-reference precedent). No conflicts found.
  Highest-risk edit: the `SiteUpdate` schema change — mitigated by AC3's explicit regression test.
- Section B feasibility (Phase 2): PASS with 2 concerns resolved (see Security surface above and
  Test coverage above overlap — MCP guard-rails). Mechanical feasibility HIGH: cache-header reuse
  from `apps/web/src/app/llms.txt/route.ts:53` / `.well-known/ai-plugin.json/route.ts:27` is sound
  even though this phase implements on the FastAPI side (Response object headers, not Next.js
  route handlers) — same string value, different transport. No dependency needed for the
  hand-written JSON-RPC dispatcher (confirmed: no `mcp` package anywhere in `requirements.txt`,
  69 lines, fully read). Gap found: cache staleness — the shared header's
  `stale-while-revalidate=86400` means a customer's dashboard edit (Phase 1) can take up to ~24h
  worst-case to reach public agent-facing content; this is consistent with existing
  `llms.txt`/`ai-plugin.json` precedent (ACCEPTED, not a defect) but should be surfaced in the
  dashboard save-confirmation copy (E6, execute-agent instruction — not a plan-text fix, since
  it's copy the executing agent will write anyway when building the editor UI). No conflicts
  found with Phase 1 data or other plan sections. Highest-risk edit: the flag-gating logic shared
  by 4 endpoints — mitigated by AC6/AC8's explicit 404-when-off / unknown-site tests.

Open gaps:
- Migration live round-trip on a disposable Postgres for `add_agent_profile` — Docker-gated,
  matches the program's established precedent (owned-data-layer, ingest-abuse-hardening, etc.);
  not a blocker, run before Phase 1 reaches `✅ VERIFIED`.
- `curl`-based cache-header confirmation against a locally enabled test site — Hybrid, requires a
  running local API + an `AgentProfile` row with `enabled=True`; not CI-portable, run manually.
- GET-before-any-PUT behavior for `/api/v1/agent-profile/{site_id}` (auto-create-empty vs 404) is
  an explicit implementation decision left to EXECUTE by the plan itself — bounded, low-risk, not
  a gap requiring resolution here (see E7 below for the recommended default).

What this coverage does NOT prove:
- `pytest tests/unit/test_agent_profile.py` proves CRUD shape and ownership isolation; it does
  NOT prove the migration applies cleanly against a real Postgres (that's the separate Hybrid
  gate, Docker-gated) nor that the dashboard form actually round-trips through a real browser
  (that's the Agent-Probe manual smoke).
- `pytest tests/unit/test_agent_gateway_public.py` / `test_agent_mcp.py` prove response shape and
  flag-gating logic in-process; they do NOT prove real CDN cache behavior (edge cache hit/miss,
  actual `s-maxage` honoring by Cloudflare) — that requires a live deploy, out of scope for this
  contract's automated gates.
- The `grep` scan for `verify_site_access` proves the literal decorator/call is present on every
  new Phase 1 route; it does NOT prove the dependency is wired correctly at runtime (that's
  covered by the ownership-404 unit test, AC2).
- None of these gates touch Phase 3/4 surfaces (`agent_action.py`, `consent_receipt.py`,
  `identity_classification.py`, `visitor_email.py`, `_save_identified`) — confirmed by reading
  the full Phase 1+2 Touchpoints/Implementation Checklist sections: zero references to those
  files or to any PII/identity write path in the in-scope sections.

Execute-Agent Instructions (apply during EXECUTE for Phase 1 + Phase 2 only):

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Tenant-exposure rule: every new Phase 1/2 endpoint must return 404 (never 403) for an unknown or foreign `site_id`. Authed CRUD uses `verify_site_access` (`apps/api/dependencies.py:29`); public reads use the same noop/404 pattern as `agent_fetch_beacon.py:90-96`. Confirm this before writing each router. | Every new router in Phase 1 and Phase 2 |
| E2 | Re-run `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` immediately before writing `down_revision` in `add_agent_profile`. Do NOT hardcode `e6b2d4a1c837` (this contract's confirmed value) without re-verifying live — concurrent work may move the head again (see `concurrent-program-migration-collision-rechain.md` memory note and this plan's own Migration Guidance section). | Before writing the `add_agent_profile` migration file |
| E3 | JSON-RPC decision (approved): hand-write a minimal JSON-RPC 2.0 dispatcher in `agent_mcp.py` — do NOT add an MCP SDK dependency (none exists in `requirements.txt`; 3 read-only tools do not justify one). MUST implement: strict method allow-list (`get_offers`/`get_pricing`/`check_availability` only, proper `{"error":{"code":-32601,...}}` for anything else), a body-size guard before JSON parsing, the same `@limiter.limit(...)` pattern as the REST endpoints in the same router, and no raw-input echo in any error response. | Writing `apps/api/routers/agent_mcp.py` |
| E4 | Migration offline `--sql` dry-run test gate MUST use an explicit `<from-rev>:<to-rev>` range (this repo's `upgrade head --sql`/`downgrade -1 --sql` shorthand fails mid-chain — confirmed cadence-bot-flag EXECUTE 26-07-26, `process/context/tests/all-tests.md`). Example: `alembic -c apps/api/alembic.ini upgrade <live-head-from-E2>:add_agent_profile --sql` and the matching downgrade range. | Running the AC1 migration dry-run gate |
| E5 | `AgentProfile.site_id` uses a real `ForeignKey("sites.site_id")` with `unique=True` (valid since `Site.site_id` is itself DB-unique) — deliberately NOT the soft `site_id: str` no-FK pattern used by `agent_visit.py`/`campaign.py`, because `AgentProfile` is a genuine 1:1 record. Document this rationale in the migration docstring. | Writing `apps/api/models/agent_profile.py` and its migration |
| E6 | Add one sentence to the Phase 1 dashboard editor's save-confirmation copy noting that public agent-facing content may take up to ~24h to reflect an edit (shared cache header `s-maxage=3600, stale-while-revalidate=86400`, same precedent as `llms.txt`/`ai-plugin.json`). This is an accepted trade-off, not a defect — do not attempt to shorten the cache window as part of this phase. | Building `apps/web/src/app/dashboard/agent/page.tsx` |
| E7 | Pick ONE first-read behavior for `GET /api/v1/agent-profile/{site_id}` (auto-create-empty-default vs 404-if-none) and apply it consistently with `PUT`'s upsert semantics; document the choice in the router docstring. Recommended default: 404 on GET before any PUT has happened, upsert on PUT (matches typical REST semantics elsewhere in this codebase; avoids surprising empty-profile row creation from a mere read). | Writing `apps/api/routers/agent_profile.py` |
| E8 | Hard boundary: do NOT implement any Phase 3 (`agent_action.py`, `consent_receipt.py`, `/c/{token}`, `isPublicRoute` change, the action endpoint) or Phase 4 (`consent_capture.py`, `identity_classification.py`/`visitor_email.py` changes, dashboard conversions funnel) work in this EXECUTE pass. If research/innovate work for Phase 1/2 surfaces a reason to start those early, STOP and return to VALIDATE for a fresh scoped pass — do not silently expand scope. Before closing EVL, `grep` for zero touches to `identity_classification.py`, `visitor_email.py`, `_save_identified`, `agent_action.py`, `consent_receipt.py`, and `apps/web/src/app/c/` — any hit is a scope violation. | End of Phase 1+2 EXECUTE, before EVL closeout |

High-Risk Evidence Pack: NOT REQUIRED for this contract. Phase 1 is risk class LOW (additive
table, authed CRUD only, no public surface, no identity writes). Phase 2 is risk class
LOW-MEDIUM (first public unauthenticated surface, but strictly read-only, no PII, no writes) —
this does not meet any of the 6 high-risk classes in `orchestration.md` §High-Risk Execution
Handoff (auth/identity, billing/credits, schema-destructive migration, public API *breaking*
change, deploy/runtime/proxy behavior, permission/secret/trust-boundary logic). The plan's own
High-Risk Evidence Pack requirements are correctly scoped to Phase 3 and Phase 4 only — this
contract does not gate EXECUTE on producing one for Phase 1/2. Do not let EXECUTE stall looking
for a Phase 1/2 evidence pack that this contract does not require.

Gate: CONDITIONAL (0 FAILs, 4 CONCERNs found — all 4 resolved via plan-text fixes P1–P3 applied
directly to this plan file during this VALIDATE pass, plus execute-agent instructions E1–E8 above
covering items that are EXECUTE-time decisions rather than plan-prose fixes)
Accepted by: session (autonomous VALIDATE pass, Auto Mode) — concerns C1 (MCP rate-limit/body-
guard/method-allowlist gap), C2 (migration dry-run command underspecified), C3 (FK strategy
ambiguity), C4 (cache-staleness UX callout) — all four folded into the plan text and/or
execute-agent instructions above rather than deferred; none left as an unresolved open item
requiring separate user sign-off before EXECUTE.

---

## Resume and Execution Handoff

1. **Selected plan file path:**
   `process/features/agent-gateway/active/agent-gateway_26-07-26/agent-gateway_PLAN_26-07-26.md`
2. **Last completed phase or step:** none yet — plan just written (PLAN phase complete for the
   whole program; no phase has entered RESEARCH yet).
3. **Validate-contract status:** pending (placeholder present; VALIDATE has not run).
4. **Supporting context files loaded during PLAN:** `process/context/all-context.md`,
   `process/development-protocols/plan-lifecycle.md`, `process/development-protocols/
   phase-programs.md`, live `alembic heads` output (`e6b2d4a1c837`), and direct grep confirmation
   of `PERSON_LEVEL_PROVIDERS`/`VISITOR_EMAIL_SOURCES`/`ck_visitor_emails_source` locations.
5. **Next step for a fresh agent picking up mid-execution:** Enter VALIDATE MODE for this plan
   (whole-program validate-contract, or at minimum Phase 1's exit gate) before any EXECUTE work
   begins. Phase 1 is the correct starting phase — RESEARCH first (re-confirm `Site`/`SiteUpdate`
   current shape and `verify_site_access` conventions haven't drifted since this plan was
   written), then proceed through the 7-step inner loop.

---

## Closeout Task Noted (per task instructions)

Per `process/development-protocols/plan-lifecycle.md`, a new feature folder was created for this
program (`process/features/agent-gateway/`). The **"Current Features" list in
`process/context/all-context.md` should be updated** to add an `agent-gateway` entry once Phase 1
ships (or now, if the convention prefers immediate registration at program kickoff — this repo's
convention, per `plan-lifecycle.md` §Feature Folder Lifecycle, is to update the features list
"whenever a new feature folder is created," so this is flagged as an outstanding UPDATE PROCESS
task rather than performed inline during PLAN, since PLAN mode is restricted to writing only the
plan artifact itself).

## Autonomous Goal Block

```
SESSION GOAL: Ship Phase 1 (AgentProfile data model + authed CRUD + dashboard editor + SiteUpdate
fix) and Phase 2 (public manifest/offers/llms.txt + hand-written JSON-RPC MCP read server +
discovery snippet) of the Agent Gateway program — Phase 3/4 explicitly excluded from this run.
Charter + umbrella plan: process/features/agent-gateway/active/agent-gateway_26-07-26/agent-gateway_PLAN_26-07-26.md
(single-file program plan; see its "Program Goal Charter" section for the full 4-phase north star)
Autonomy: CONDITIONAL gate accepted this session (session, autonomous VALIDATE pass) — EXECUTE may
proceed on Phase 1+2 without a further user gate. Standard PVL/EVL loop rules apply per
process/development-protocols/orchestration.md; BLOCKED at PVL/EVL still surfaces per that protocol.
Hard stop conditions / safety constraints:
- Do NOT implement Phase 3 or Phase 4 in this run (agent_action.py, consent_receipt.py,
  /c/{token}, isPublicRoute change, consent_capture.py, identity_classification.py,
  visitor_email.py, _save_identified are all out of bounds — grep-verify zero touches before EVL
  closeout).
- is_emailable_identity is never touched (it isn't in scope for Phase 1/2 anyway).
- Every new Phase 1/2 endpoint returns 404, never 403, for unknown/foreign site_id.
- agent_gateway_enabled and AgentProfile.enabled both stay default OFF.
- Re-run `alembic heads` live immediately before writing down_revision on add_agent_profile —
  never hardcode e6b2d4a1c837 without re-verifying (repeated concurrent-migration-collision
  pattern in this repo).
- The agent_mcp.py JSON-RPC endpoint must have method allow-list + rate-limit + body-size guard
  (see E3 in the validate-contract) before it is considered done.
Next phase: EXECUTE Phase 1 (Step 5), then Phase 2 (Step 5) — per the plan's Phase Loop Progress
checklist. Steps 1-4 (RESEARCH/INNOVATE/PLAN-SUPPLEMENT/PVL) are complete for the Phase 1+2 scope
as of this VALIDATE pass.
Validate contract: inline in plan, "## Validate Contract" section (Gate: CONDITIONAL, scoped to
Phase 1+2 only) — see above.
Execute start: pytest tests/unit/test_agent_profile.py, tests/unit/test_sites.py,
tests/unit/test_agent_gateway_public.py, tests/unit/test_agent_mcp.py (all new/extended, TDD
stubs first) | cd apps/web && npm run build | migration offline --sql dry-run with explicit
<from-rev>:<to-rev> range (see E4) | high-risk pack: no (Phase 1+2 do not meet any of the 6
high-risk classes — see contract's High-Risk Evidence Pack note)
```

---

## Next Instruction

VALIDATE complete for Phase 1 + Phase 2 (Gate: CONDITIONAL, concerns resolved — see "## Validate Contract" above). Phase 3 and Phase 4 remain unvalidated and out of scope for this pass. Say **"ENTER EXECUTE MODE"** to begin Phase 1, or request a separate VALIDATE pass for Phase 3/4 when ready to plan those.
