---
name: plan:account-measurement
description: "Account-level rollup API + dashboard Accounts view from existing tables (gap #14), flag-gated, no migration"
date: 27-11-26
feature: campaigns-outreach
---
# Account Measurement — PLAN (SIMPLE)

TL;DR: new read-only service `services/account_rollup.py` aggregating existing tables by `visitors.company_domain`; new router `routers/accounts.py` (2 GETs, flag `account_rollup_enabled` default OFF → 404); new dashboard page `/dashboard/accounts`. **No migration.** Replies + CRM pipeline returned `null` as known-gaps.

Complexity: SIMPLE
Status: PLANNED — validate-contract PASS (outer PVL re-run after supplement cycle 2, 27-11-26; 0 FAIL / 0 CONCERN)

## Overview
Gap #14: today ranking is per-company intent (`routers/companies.py`) and outcomes are per-campaign (`routers/outcomes.py`); nothing rolls visitors, people, campaigns, clicks and conversions up per account.

Spec: `account-measurement_SPEC_27-11-26.md` (same folder).

## Decision Summary
### Chosen Approach
Read-time SQL aggregation keyed on `visitors.company_domain` (left-join `companies` for firmographics) — zero schema, always fresh, reversible.
### Why This Over Alternatives
| Alternative | Why Rejected |
|---|---|
| Materialized `account_rollups` table + sweep | Needs migration + job + staleness logic; not justified until AC8 latency fails |
| Extend `routers/companies.py` | `companies` row only exists post-resolution; mixes per-click ranking with rollup; changes an existing contract |
### Risk Predictions
- Perf: JSONB `pages_visited` scan per domain could be slow → compute in one grouped CTE, page by domain first, then metrics for the page's domains only.
- Correctness: `companies.site_id` vs `visitors.site_id` both String(50) — join on (site_id, domain); domains lower-cased.
- Privacy: counts only; never select email/name columns.
- Product: ISP/freemail domains pollute list → exclude `company_domain IS NULL`; freemail filter is known-gap if no list exists.
### Key Constraints Accepted
Replies/pipeline null; demo bookings = conversions on goals whose pattern matches `Site.booking_url` host (heuristic, documented in response `definitions`).

## Implementation Checklist
1. `apps/api/config.py`: add `account_rollup_enabled: bool = False`.
2. `apps/api/services/account_rollup.py` (new): `list_accounts(db, site_id, days, sort, page, page_size)` and `get_account(db, site_id, domain, days)`; one grouped query per metric family. Pinned rules (PVL cycle 1):
   - **Identified people** = `Visitor.identity_status == 'identified'` (`models/visitor.py:72`), NOT rows in `identified_visitors`. SPEC erratum: the SPEC's "identified_visitors" wording is superseded by this rule.
   - **Tenant scoping (SECURITY):** every query filters `site_id = :site_id`. `campaign_touchpoints` has no `site_id` column, so touchpoints/clicks MUST join `campaigns` and filter `campaigns.site_id = :site_id` AND join visitors on `(site_id, visitor_id)` — never on `visitor_id` alone.
   - **Merged-alias rule (PVL cycle 2, N2):** do NOT exclude `merged` rows — they carry the click-derived real traffic and the aggregator never folds them into the canonical (often a 0-pageview imported phantom). People = `COUNT(DISTINCT COALESCE(visitors.canonical_visitor_id, visitors.visitor_id))`; identified people = same distinct expression filtered to `identity_status IN ('identified','merged')`; sessions/pageviews/pricing visits SUM across ALL rows (merged included); clicks/touchpoints/conversions join on the full set of the domain's visitor_ids (canonical + merged), counted once per event row.
   - **Exclusions:** exclude agent-derived (`human_only_visitor_filter()`) and `is_abuse_flagged` rows; `is_bot_suspect` / `is_agent_operated` stay COUNTED (visibility-only) — U3.
   - **Pricing:** `pages_visited` stores full URLs (`visitor_aggregator.py:317`) → normalize each element by stripping scheme, host, query and fragment, then apply the `agent_intent_signals` `/pricing` prefix rule (exact `/pricing` or `/pricing/...`; not `/pricing-blog`); trailing slash tolerated. Python normalizer is the single source for the SQL predicate (tested in G1).
   - **Time windows (`days`):** visitors/sessions/pricing by `visitors.last_seen`; touchpoints by `sent_at` with `status = 'sent'` (`campaign_stats.py:62`); clicks by `clicked_at`; conversions by `occurred_at`.
   - **Demo bookings** = conversions on the existing "Demo booked" goal preset (`site-settings-dialog.tsx:328`) — U1, provisional.
   - **Freemail filter** via `enricher._FREE_MAIL_DOMAINS` — U2, provisional (switch to `company_exclusion.is_freemail()` if that plan lands first).
   - structlog logs site_id + counts only.
3. `apps/api/schemas/account_rollup.py` (new — NOT `schemas/accounts.py`, which already holds social-account schemas imported by 3 routers; never touch it, PVL N1): `AccountRow`, `AccountListResponse`, `AccountDetail` (+ `campaigns: list[{campaign_id,name,touched,clicks,conversions}]`), `replies: int|None`, `pipeline_value_cents: int|None`, `known_gaps: list[str]`.
4. `apps/api/routers/accounts.py` (new) (imports from `schemas.account_rollup`) + mount in `apps/api/main.py` at `/api/v1/accounts`; `get_current_user` + `verify_site_access`; flag OFF → 404; unknown domain → 404.
5. `apps/web/src/lib/api-types.ts` + `apps/web/src/lib/api.ts`: types + `api.listAccounts/getAccount`.
6. `apps/web/src/app/dashboard/accounts/page.tsx` (new) + nav link in `dashboard/layout.tsx`: TanStack table, sort select, days select, detail drawer, flag-off/empty states.
7. Tests: `tests/unit/test_account_rollup.py` (pricing prefix rule, sort/paging param validation, response shape nulls); `tests/integration/test_accounts_api.py` (flag-ON fixtures → exact counts, agent/abuse exclusion with bot_suspect still counted, foreign site 404, flag-OFF 404; cross-tenant same `visitor_id` on 2 sites → zero bleed; merged-alias: canonical+merged child counted as ONE person while the merged child's sessions/pageviews/clicks/conversions ARE counted; full-URL `https://host/pricing?x=1` counted and `/pricing-blog` not; `days` boundary per metric; recursive response-key allow-list rejecting `email`/`full_name`/`phone`/`ip_address`/`visitor_id`); `apps/web/e2e/accounts.spec.ts` smoke (auth-harness-gated skip). Perf: `seed_10k` helper fixture in `tests/integration/test_accounts_api.py` (10,000 visitors over 500 domains, plus clicks/conversions), test `test_accounts_perf` marked `@pytest.mark.perf` and skipped unless `ACCOUNTS_PERF=1`; it runs `EXPLAIN (ANALYZE, BUFFERS)` on the list query and times 20 calls of `list_accounts` (p95).
8. Performance fallback (N3, no migration ever): list query aggregates all domain metrics in one CTE then sorts + `LIMIT/OFFSET` (paging-by-domain-first is NOT used for metric sorts). If G6 p95 >= 500ms: (a) cap `days` at 90 in the router validator, then (b) restrict `sort` to `last_seen|visitors|identified`; record which fallback fired in the EXECUTE report. Adding an index/migration is forbidden in this plan → backlog note instead.

## Acceptance Criteria
AC1–AC8 as defined in the SPEC (flag-OFF 404, tenant 404, exact counts, bot/abuse exclusion, null known-gap fields, no PII, dashboard renders, latency probe).

## Phase Completion Rules
CODE DONE when G1–G4 green; VERIFIED only after G2 flag-ON run by independent vc-tester (EVL) and G5/G6 resolved or accepted as known-gaps.

## Touchpoints
New: `services/account_rollup.py`, `schemas/account_rollup.py`, `routers/accounts.py`, `dashboard/accounts/page.tsx`, 3 test files. Edited: `config.py`, `main.py`, `api.ts`, `api-types.ts`, `dashboard/layout.tsx`. Read-only (must NOT be modified): `schemas/accounts.py` (social-account schemas), `models/{visitor,company,campaign,outcome,site}.py`, `services/agent_visitor_filters.py`, `services/agent_intent_signals.py`.

## Public Contracts
New additive endpoints `GET /api/v1/accounts/{site_id}` and `/{site_id}/{domain}`; no existing contract changed. No schema change.

## Blast Radius
~12 files, 2 packages (api, web). Risk class: public API (additive, flag-gated). Not auth/billing/schema/migration. Parallel agents' areas (exclusion list, greeting, CTA, conversion APIs, lookalikes, SEO) may also edit `config.py`/`main.py`/`api.ts`/`layout.tsx` — append-only edits, rebase on conflict.

## Verification Evidence
| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| G1 `.venv/bin/python -m pytest tests/unit/test_account_rollup.py -q` (pricing normalizer, param validation, null known-gap fields) | Fully-Automated | AC3-pricing, AC5, AC6-shape |
| G2 `DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test REDIS_URL=redis://localhost:6379/15 .venv/bin/python -m pytest tests/integration/test_accounts_api.py -q` — cases: flag-OFF 404, foreign site 404, unknown domain 404, flag-ON exact counts, cross-tenant same visitor_id, merged alias (one person; child activity counted), full-URL pricing, Demo-booked conversions, days boundary, recursive no-PII key allow-list | Hybrid | AC1, AC2, AC3, AC4, AC6 |
| G3 `.venv/bin/python -m pytest tests/unit -m unit -q` | Fully-Automated | regression |
| G4 `cd apps/web && npx tsc --noEmit && npm run lint` | Fully-Automated | AC7-compile |
| G5 `cd apps/web && npx playwright test e2e/accounts.spec.ts` (Clerk auth-harness skip-guard; residual → backlog, gate CONDITIONAL) | Hybrid | AC7-render |
| G6 `ACCOUNTS_PERF=1 DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test REDIS_URL=redis://localhost:6379/15 .venv/bin/python -m pytest tests/integration/test_accounts_api.py -m perf -q -s` (seed_10k, EXPLAIN ANALYZE output + p95 printed; p95 < 500ms else apply checklist item 8 fallback) | Agent-Probe | AC8 |
| G7 `! grep -nE "IdentifiedVisitor\.(email\|full_name\|phone)\|Visitor\.ip_address\|_ciphertext\|email_bidx" apps/api/services/account_rollup.py apps/api/schemas/account_rollup.py && git diff --quiet HEAD -- apps/api/schemas/accounts.py` | Fully-Automated | AC6-static |
| G8 `grep -n 'accounts.router, prefix="/api/v1/accounts"' apps/api/main.py` | Fully-Automated | route-wired (AC1) |

**Preconditions (run before G1–G3, G6):**
- `.venv` does not exist — build it: `/opt/homebrew/bin/python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`. `.venv/bin/pytest` is not assumed; always `.venv/bin/python -m pytest`.
- Docker CLI is off PATH: `/Applications/Docker.app/Contents/Resources/bin/docker compose -f infra/docker-compose.yml up -d`, then confirm `lsof -nP -iTCP -sTCP:LISTEN | grep -E '5433|6379'` shows both.
- **DATABASE_URL MUST be pinned inline to localhost:5433 for G2/G6. Never rely on `.env` — it points at Supabase PROD.** No alembic, no DB scripts.
- G2 must run the flag-ON path (flag-OFF-only evidence is vacuous).

## Open User Decisions
All pending user confirmation; plan proceeds on these PROVISIONAL defaults.
- **U1 (pending user confirmation):** demo bookings = conversions on the existing "Demo booked" goal preset (`site-settings-dialog.tsx:328`), not a `booking_url` host match.
- **U2 (pending user confirmation):** freemail filter uses `enricher._FREE_MAIL_DOMAINS` now; switch to `company_exclusion.is_freemail()` if company-exclusion-list ships first. Note: the EXECUTE order places company-exclusion-list FIRST, so EXECUTE must check whether `is_freemail()` exists and prefer it.
- **U3 (pending user confirmation):** exclude agent-derived + abuse-flagged rows only; `is_bot_suspect` / `is_agent_operated` stay counted (visibility-only flags).

## Test Infra Improvement Notes
(none identified yet) — Clerk Playwright auth harness remains a cross-feature gap.

## Resume and Execution Handoff
1. Plan: `process/features/campaigns-outreach/active/account-measurement_27-11-26/account-measurement_PLAN_27-11-26.md`
2. Last completed: PLAN + VALIDATE (outer PVL re-run after supplement cycle 2, vc-validate-agent, 27-11-26) — PASS
3. Validate-contract: written below (PASS, supersedes cycle-1 re-run BLOCKED)
4. Context: `process/context/all-context.md`, `process/context/tests/all-tests.md`, `process/features/campaigns-outreach/_GUIDE.md`
5. Next: `ENTER EXECUTE MODE` → vc-execute-agent (opus), sequential; then EVL via vc-tester (opus).

## Validate Contract

Status: PASS
Date: 27-11-26
date: 2026-11-27
generated-by: outer-pvl
supersedes: 2026-11-27 (outer-pvl, re-run after cycle 1: BLOCKED 1 FAIL / 2 CONCERN) — outer PVL re-run after supplement cycle 2 has current code-read evidence

Parallel strategy: sequential
Rationale: 4/7 signals (S2 public API, S5 depth, S6 public-API risk class, S7 ~12 files). Dominant fit signal: one plan, 2 packages, 5 files shared with sibling plans. EXECUTE runs 1 vc-execute-agent (opus) then 1 vc-tester (opus) for EVL. This validate pass ran inline in one opus session (no Agent tool available); all 4 Layer 1 dimensions and 3 Layer 2 sections were assessed by reading code at HEAD 6ef19f7.

### Cycle-2 gap closure (verified against code)
- CLOSED N1 (was FAIL) schema collision: `apps/api/schemas/accounts.py` exists and holds social-account schemas; the plan now creates `apps/api/schemas/account_rollup.py` (does not exist yet), lists `schemas/accounts.py` as read-only, and G7 adds `git diff --quiet HEAD -- apps/api/schemas/accounts.py`. `routers/accounts.py`, `services/account_rollup.py` and `dashboard/accounts/` do not exist; `main.py:55` imports no `accounts` name (only `social_accounts`, mounted at `/api/v1/social`), so G8's grep cannot match the wrong router.
- CLOSED N2 merged rule: matches code. `models/visitor.py:106-117` and `services/agent_visitor_filters.py` confirm merged children are the click-derived rows pointing `canonical_visitor_id` at an untouched phantom; `human_only_visitor_filter()` keeps phantoms that have a merged child, so it does not conflict with counting merged rows.
- CLOSED N3 perf: `seed_10k` fixture, `ACCOUNTS_PERF=1 ... -m perf -q -s` command, EXPLAIN (ANALYZE, BUFFERS) + p95 over 20 calls, and a no-migration fallback ladder (cap days 90, then restrict sort keys, then backlog note).
- Cycle-1 fixes re-confirmed: touchpoints have no site_id (`models/campaign.py:58-67`) and are scoped via `campaigns.site_id` + (site_id, visitor_id) join; `campaign_clicks`/`conversions` carry site_id with site-leading indexes (`models/outcome.py:75,95`); `verify_site_access` (`dependencies.py:30`) returns 404; pricing normalizer strips scheme/host/query/fragment before the `/pricing` prefix rule; recursive no-PII key allow-list + G7 static guard.
- CLOSED validator WARN: exact path `process/context/all-context.md` added to the Resume section.

### New findings (this pass) — notes only, no FAIL/CONCERN
- `pytest.mark.perf` is not registered in `pyproject.toml` markers: `-m perf` still selects correctly and only emits `PytestUnknownMarkWarning` (no `--strict-markers` in addopts). Handled by E8.
- Only 106/179 unit files carry `pytestmark = pytest.mark.unit`; an unmarked new file would be skipped by G3. Handled by E9.
- `human_only_visitor_filter()` references the `Visitor` class directly, not an alias. Handled by E10.
- A phantom canonical and its merged child can carry different `company_domain` values, so that person appears once in each domain. Within a domain the count stays distinct. Handled by E11 (documented in response `definitions`).
- `services/company_exclusion.py` does not exist yet (U2 fallback to `enricher._FREE_MAIL_DOMAINS`, `services/enricher.py:70`, stands). No sibling plan creates `account_rollup`, `routers/accounts.py`, `/dashboard/accounts` or `listAccounts`.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC5/AC6-shape | null replies/pipeline with known_gaps reasons; params validated (days 1..365, sort enum, page_size cap) | Fully-Automated | G1 `.venv/bin/python -m pytest tests/unit/test_account_rollup.py -q` | B |

Failing stub:
test("should return null replies and pipeline with known_gap reasons and reject out-of-range params", () => { throw new Error("NOT IMPLEMENTED — TDD stub: null known-gap fields + param validation") })

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC3-pricing | normalizer matches `/pricing` on full URLs with query/fragment/trailing slash, rejects `/pricing-blog` | Fully-Automated | G1 (same file) | B |

Failing stub:
test("should match /pricing on full URLs with query and trailing slash but not /pricing-blog", () => { throw new Error("NOT IMPLEMENTED — TDD stub: pricing path parity") })

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC6-static | rollup service + rollup schema never reference PII columns; social `schemas/accounts.py` untouched | Fully-Automated | G7 `! grep -nE "IdentifiedVisitor\.(email\|full_name\|phone)\|Visitor\.ip_address\|_ciphertext\|email_bidx" apps/api/services/account_rollup.py apps/api/schemas/account_rollup.py && git diff --quiet HEAD -- apps/api/schemas/accounts.py` | B |

Failing stub:
test("should contain no PII column references in account_rollup service or schema and leave schemas/accounts.py unchanged", () => { throw new Error("NOT IMPLEMENTED — TDD stub: static PII grep guard") })

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC1-AC4, AC6 | flag-OFF/foreign-site/unknown-domain 404; flag-ON exact counts; agent+abuse excluded, bot_suspect counted; cross-tenant same visitor_id zero bleed; canonical+merged child = one person while child sessions/pageviews/clicks/conversions counted; full-URL pricing; Demo-booked conversions; days boundary per metric; recursive no-PII key allow-list | Hybrid | G2 `DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test REDIS_URL=redis://localhost:6379/15 .venv/bin/python -m pytest tests/integration/test_accounts_api.py -q` — precondition: `lsof -nP -iTCP -sTCP:LISTEN \| grep -E '5433\|6379'` shows both, and `.venv` is built | B |
| regression | unit lane green, incl. social routers importing `schemas/accounts.py` | Fully-Automated | G3 `.venv/bin/python -m pytest tests/unit -m unit -q` | A |

Failing stub:
test("should keep the full unit lane green", () => { throw new Error("NOT IMPLEMENTED — TDD stub: unit regression") })

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC7-compile | web types/client/page compile and lint | Fully-Automated | G4 `cd apps/web && npx tsc --noEmit && npm run lint` | B |

Failing stub:
test("should typecheck and lint the accounts page, api client and types", () => { throw new Error("NOT IMPLEMENTED — TDD stub: web compile") })

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| route-wired | router mounted at `/api/v1/accounts` | Fully-Automated | G8 `grep -n 'accounts.router, prefix="/api/v1/accounts"' apps/api/main.py` | B |

Failing stub:
test("should mount accounts router at /api/v1/accounts", () => { throw new Error("NOT IMPLEMENTED — TDD stub: router mount") })

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC7-render | list, empty and flag-off states render | Hybrid | G5 `cd apps/web && npx playwright test e2e/accounts.spec.ts` (Clerk auth-harness skip-guard) | D |
| AC8 | p95 < 500ms on a 10k-visitor / 500-domain fixture; EXPLAIN printed | Agent-Probe | G6 `ACCOUNTS_PERF=1 DATABASE_URL=postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test REDIS_URL=redis://localhost:6379/15 .venv/bin/python -m pytest tests/integration/test_accounts_api.py -m perf -q -s` (checklist item 8 fallback if p95 >= 500ms) | B |

Named residual rows (Known-Gap is never a strategy):
- replies: no visitor-keyed reply data; returned null. gap-resolution D.
- CRM pipeline: owned by the closed-won read-back plan; returned null. gap-resolution C.
- G5 Clerk Playwright auth harness: cross-feature residual. gap-resolution D.
- Python 3.11 syntax: tests run on the 3.12 venv, Dockerfile is 3.11; avoid 3.12-only syntax. gap-resolution D.
- Environment (not a plan gap): `.venv` absent and :5433/:6379 not listening at validate time; preconditions documented, executed by E6.

Legacy line form:
- unit: Fully-automated: G1, G3, G7, G8
- api integration: hybrid: G2 + precondition :5433/:6379 listening and `.venv` built
- web: Fully-automated: G4 | hybrid: G5 (auth-harness skip-guard)
- perf: agent-probe: G6 EXPLAIN ANALYZE + p95
- replies / CRM pipeline / Clerk harness / py3.11 syntax: known-gap: documented

Dimension findings:
- Infra fit: PASS — no migration, no new runtime; exact gate commands, DSN pinned to localhost:5433, venv/docker preconditions documented.
- Test coverage: PASS — G2 lists every correctness case incl. corrected merged expectation; G6 has fixture, command, threshold and fallback.
- Breaking changes: PASS — new `schemas/account_rollup.py` avoids the social-schema collision; G7 guards `schemas/accounts.py` unchanged; endpoints additive and flag-gated.
- Security surface: PASS — every table scoped through an owned site_id (touchpoints via `campaigns.site_id`), `verify_site_access` 404, counts only, recursive key allow-list + static guard.
- Section: Service/aggregation: PASS — identified, merged, exclusion, pricing, window and demo-booking rules pinned and consistent with `human_only_visitor_filter()`.
- Section: Router/schema: PASS — new file names free; `main.py:55` import list has no `accounts` clash; pattern matches `routers/companies.py`.
- Section: Web page + shared files: PASS — no `/dashboard/accounts` route or `listAccounts` clash; append-only shared edits.

Execute-agent instructions:
- E1 Use `Visitor.identity_status` for identity. Never select `IdentifiedVisitor` columns.
- E2 Scope touchpoints via `campaigns.site_id = :site_id`; clicks, conversions and conversion_goals filter on their own site_id; visitor joins on (site_id, visitor_id).
- E3 People = distinct `COALESCE(canonical_visitor_id, visitor_id)`; activity sums and activity-table joins include merged rows.
- E4 Exclude `company_domain IS NULL OR ''` plus the freemail filter (prefer `company_exclusion.is_freemail()` if it exists at EXECUTE time, else `enricher._FREE_MAIL_DOMAINS`).
- E5 Never run alembic or DB scripts against the repo env-file DATABASE_URL (Supabase PROD). Pin localhost:5433. No migration: if one is needed, STOP and return to PLAN.
- E6 Build `.venv` and start local PG/Redis first; G2 must exercise the flag-ON path.
- E7 Append-only shared-file edits. Never touch `apps/api/schemas/accounts.py`.
- E8 Do not add `--strict-markers`; the unregistered `perf` marker warning is accepted (no `pyproject.toml` edit needed).
- E9 Put `pytestmark = pytest.mark.unit` in `tests/unit/test_account_rollup.py` and `pytestmark = pytest.mark.integration` in `tests/integration/test_accounts_api.py`.
- E10 Use `human_only_visitor_filter()` against the un-aliased `Visitor` entity in the base CTE.
- E11 Group people under each row's own `company_domain`; state in response `definitions` that a phantom and its merged child on different domains appear in both.

Open gaps: none blocking. Named residuals above. U1-U3 provisional user decisions (not blockers).

What This Coverage Does NOT Prove:
- G1/G3: real SQL behavior, tenant scoping, live counts.
- G7: runtime response content (static references only).
- G2: prod data shapes or volume, Supabase pooler behavior, prod flag flips.
- G4: runtime render or data binding.
- G5 (skipped): any browser behavior until the auth harness lands.
- G6: p95 under real concurrency or with prod-size `pages_visited`.
- G8: that the mounted router actually answers (G2 does).
- None: correctness of IP-derived `company_domain` attribution for any visitor.

Gate: PASS (0 FAIL, 0 CONCERN; after 2 validate-fix loops)
Accepted by: session (outer-pvl, 27-11-26) — no CONDITIONAL concerns; residuals and U1-U3 recorded above.

## Autonomous Goal Block

SESSION GOAL: Account Measurement (gap #14) — read-only per-company-domain rollup API + Accounts dashboard, flag account_rollup_enabled default OFF, no migration.
Charter + umbrella plan: N/A — single plan
Autonomy: auto-proceed on reversible steps; subagent delegation mandatory; sonnet banned (opus execute/tester).
Hard stop conditions / safety constraints:
- Never run alembic or any DB script without DATABASE_URL pinned to localhost:5433 (the repo env file points at Supabase PROD).
- No migration. If one becomes necessary, stop and return to PLAN.
- Never modify apps/api/schemas/accounts.py (social-account schemas). New schemas go in apps/api/schemas/account_rollup.py.
- No PII in responses or logs (counts only). Foreign site and unknown domain return 404. Flag OFF returns 404.
- No flag flip in any real environment.
Next phase: EXECUTE: process/features/campaigns-outreach/active/account-measurement_27-11-26/account-measurement_PLAN_27-11-26.md
Validate contract: inline in plan (Gate: PASS, 27-11-26)
Execute start: G1 .venv/bin/python -m pytest tests/unit/test_account_rollup.py -q; G3 .venv/bin/python -m pytest tests/unit -m unit -q; G4 cd apps/web && npx tsc --noEmit && npm run lint; G7/G8 greps | G2 integration on localhost:5433 (flag-ON) | G6 ACCOUNTS_PERF=1 EXPLAIN ANALYZE p95 probe | high-risk pack: no (additive, flag-gated, read-only)
