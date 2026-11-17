---
name: plan:ws3-agent-concierge
description: "WS3 — Agent Concierge kill test: param-gated MCP tools + zero-click conversion tool + agent-provenance lead table + wild kill-test metrics"
date: 30-07-26
feature: agent-native-revenue
phase: "WS3"
---

# WS3 — Agent Concierge Kill Test — Plan

Date: 30-07-26
Status: CODE DONE, NOT VERIFIED — Steps 1-4 EXECUTE + EVL-green (31-07-26, 1451 unit + 66
integration, 0 regressions); AC-WS3-5/6 wild kill test is WS0-gated known-gap (see
`ws3-agent-concierge-phase_REPORT_31-07-26.md` and
`process/features/agent-native-revenue/backlog/ws3-wild-kill-test_NOTE_31-07-26.md`). Plan stays
active — do not archive until AC-WS3-5/6 close on real wild data (program guardrail 3).
Complexity: **COMPLEX** (schema changes ×2, public unauthenticated JSON-RPC contract extension,
5+ files, 2 non-negotiable security must-fixes, sequential dependent steps)

Context loaded: `process/context/all-context.md` (AI-Agent-Traffic Layer / Owned Identity Data
Layer / Handoff Detection sections — the emailability-separation precedent this plan must never
weaken), `process/context/tests/all-tests.md` (integration test runner + marker conventions),
`agent-native-revenue_SPEC_30-07-26.md` (WS3 ACs, program guardrails — read via `git show
feat/ws2-agent-session-classifier:...` since this file has not yet landed on the current branch),
`agent-native-revenue-umbrella_PLAN_30-07-26.md` (WS3 stub, join conditions, Program Goal
Charter — same read path), `apps/api/routers/agent_mcp.py`, `apps/api/services/agent_gateway.py`,
`apps/api/models/agent_profile.py`, `apps/api/schemas/agent_gateway.py`,
`apps/api/services/agent_company_resolution.py`, `apps/api/services/daily_digest.py` +
`apps/api/services/outcome_digest.py` + `apps/api/services/email_sender.py` (notification
precedent), `apps/api/agents/prompt_safety.py`, `tests/unit/test_agent_origin_exclusion.py`,
`apps/api/config.py` (feature-flag/rate-limit precedent), `apps/api/services/rate_limiter.py`,
`apps/api/models/agent_fetch_event.py`, `apps/api/services/identity_classification.py`
(`is_emailable_identity`).

**Provenance note on SPEC/umbrella location:** as of this plan's drafting, `agent-native-revenue_SPEC_30-07-26.md`
and `agent-native-revenue-umbrella_PLAN_30-07-26.md` exist on branch `feat/ws2-agent-session-classifier`
(commit `560fe53`/`24448cd`) but not yet on the current branch/worktree
(`feat/ws1-ai-evaluation-timeline`, `HEAD` at write time `cc149fd`; this worktree's alembic head
`a2f8d61c9e37`). This plan was drafted by reading those files via `git show
feat/ws2-agent-session-classifier:<path>`. **Before EXECUTE, confirm these two files exist on the
branch this plan will execute against** (they should merge in from WS1/WS2 branches per the
program's branch-per-workstream discipline) — if they are still missing, re-fetch them the same
way rather than reconstructing WS3 scope from memory.

---

## Overview

Flip the existing read-only MCP gateway (`agent_mcp.py` / `agent_gateway.py`, 3 free GET-style
tools: `get_offers`, `get_pricing`, `check_availability`) from "give away everything for free" to
"trade a real answer for qualification info," and add a genuine zero-click conversion path
(`request_quote` / `book_demo`) that turns an AI agent's structured query into a real sales lead —
without ever letting that lead become an emailable identity through any path other than this
explicit tool-call consent event. This is the workstream that produces WS3's binary kill-test
verdict: does any real AI agent actually use a tool like this, measured against >=20 real wild
ChatGPT/Claude queries over 1 week on exactly one pilot site (AC-WS3-5/6 — explicitly WS0- and
wild-data-gated, NOT buildable/closeable in this plan; see Step 5 below).

This plan extends the existing hand-written JSON-RPC 2.0 dispatcher in place — it does **not**
introduce an MCP SDK, does **not** build a parallel OpenAPI surface, and does **not** replace any
of the 3 existing free read tools. All new capability slots into the same `MCP_TOOLS` registry and
the same 4-guard dispatcher (`agent_mcp.py`: rate-limit / body-cap / method-allowlist / no-echo).

## Goals

1. Add a spec-shaped, static `initialize` JSON-RPC method (MCP lifecycle handshake) — no dynamic
   internal/version data leak.
2. Gate `tools/call` for `get_offers`/`get_pricing`/`check_availability` behind 3 required
   qualification params (`use_case`, `company_size`, `evaluating_against`); missing params degrade
   gracefully to a `needs_more_info` RESULT (not a JSON-RPC error), matching AC-WS3-1.
3. Add a new, isolated JSONB column for qualified content (pricing/comparison/security answers),
   separate from `offers`, keyed by `use_case`/`evaluating_against`.
4. Add a zero-click conversion tool (`request_quote` / `book_demo`) that writes a new
   agent-provenance lead row (new table, new migration) — structurally isolated from
   `IdentifiedVisitor`, zero shared write path — and fires a fail-open owner notification email.
5. Add kill-test metric fields (tool-discovery rate / tool-call rate / param-fill rate /
   lead-event count) as new columns on `agent_fetch_events`/`agent_visits` and the new lead table,
   plus a GO/NO-GO report-assembly helper.
6. Enforce both non-negotiable must-fixes: a dedicated tighter rate limit on the conversion tool,
   and mandatory `prompt_safety` sanitization of all 3 qualification params before they reach any
   email body or the stored lead row.

## Scope

**In scope:** `agent_mcp.py` dispatcher extension (`initialize`, param-gating, conversion tool
dispatch), `agent_gateway.py` tool-function signature change (accept `params`), new
`AgentProfile.qualified_content` JSONB column + migration, new `AgentLead` model + migration, new
`prompt_safety`-gated sanitization call sites, new dedicated conversion-tool rate limiter, new
notification wiring via `email_sender.send(..., custom_args=...)` fail-open, new metric columns on
`AgentFetchEvent`/`AgentVisit` + the new lead table, GO/NO-GO report-assembly helper (pure
function, no new endpoint required unless RESEARCH at EXECUTE time finds one is needed), test
coverage for AC-WS3-1 through AC-WS3-4 + emailability regression.

**Out of scope (explicitly deferred, backlog stub — see Step 5):** the actual wild kill-test week
(AC-WS3-5), the signed GO/NO-GO verdict itself (AC-WS3-6), any live MCP client discovery/listing
mechanics (Apps Directory review, `llms.txt` pickup — per SPEC Out Of Scope), any dedicated
`/mcp/*` transport route beyond the existing `POST /{site_id}/mcp` (confirm at EXECUTE RESEARCH
whether a distinct route is actually required — SPEC flags this as an open item, not assumed
here), any change to the 3 existing free tools' *shape* beyond adding the param gate, any prod flag
flip / live provider spend / publish action (program hard stops).

---

## Touchpoints

| File | Change |
|---|---|
| `apps/api/routers/agent_mcp.py` | Add `initialize` method handler (static, spec-shaped). Extend `tools/call` dispatch to pass `params.get("arguments")` (or `params` itself, per MCP inputSchema convention — confirm exact param-passing key against the MCP lifecycle spec at EXECUTE time) into the tool function. Add dispatch branch for the new conversion tool(s) with a SEPARATE, tighter rate-limit decorator/check. Wrap all 3 qualification-param values through `prompt_safety.clean_text`/`sanitize_profiles` BEFORE they reach any downstream call (tool response construction, lead-row write, or email body). |
| `apps/api/services/agent_gateway.py` | Change `MCP_TOOLS` value signature from `(site, profile) -> dict` to `(site, profile, params) -> dict` (or a `needs_more_info` sentinel) for the 3 existing gated tools; add `tool_request_quote` / `tool_book_demo` (new, params -> lead-write + notification); add `_REQUIRED_QUALIFICATION_PARAMS = ("use_case", "company_size", "evaluating_against")` + a shared `_missing_params(params) -> list[str]` helper; add `resolve_qualified_content(profile, use_case, evaluating_against) -> dict \| None` reading the new `qualified_content` JSONB column. |
| `apps/api/schemas/agent_gateway.py` | Add response schemas: `NeedsMoreInfoOut` (`missing_params: list[str]`), `AgentLeadRequestIn`/`AgentLeadOut` for the conversion tool params/result shape, `QualifiedContentOut` for the new pricing/comparison/security answer shape. |
| `apps/api/models/agent_profile.py` | Add `qualified_content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)` — a SEPARATE column from `offers`/`capabilities`, keyed by `use_case`/`evaluating_against` combinations (customer-authored content, same "world-readable once enabled" posture as the rest of this model). |
| `apps/api/models/agent_lead.py` (**new file**) | New `AgentLead` model: append-only, one row per conversion-tool call. Fields (draft, confirm exact set at EXECUTE RESEARCH against the MCP lifecycle spec + program precedent): `id`, `site_id` (no ORM FK, house convention), `tool_name` (`request_quote`\|`book_demo`), `use_case`, `company_size`, `evaluating_against` (all post-sanitization), `resolved_company_id` (nullable, set by read-only company resolution, mirrors `AgentVisit.resolved_company_id`), `notified_at` (nullable — set only on notification success, fail-open), `created_at`/`updated_at` (from `Base`). **No `visitor_id`, no `email` column, no FK to `IdentifiedVisitor`/`Visitor` anywhere in this file or its imports** — this is the structural isolation guarantee (mirrors `IdentitySignal`'s separation pattern). |
| `apps/api/models/agent_fetch_event.py` | Add 3 new nullable boolean/string columns for kill-test metrics: `tool_name` (which tool this fetch event's call was for, nullable — only set for `tools/call` events), `params_provided` (JSONB or boolean-per-param, TBD at EXECUTE), `params_complete` (bool, nullable). Additive only — no existing column changed. |
| `apps/api/models/agent_visit.py` | Confirm at EXECUTE RESEARCH whether rollup-level aggregates (e.g. `tool_call_count`, `param_complete_count`) are needed here vs. computed via a query over `agent_fetch_events` — default to NOT adding new columns here unless a specific GO/NO-GO metric cannot be cheaply computed from `agent_fetch_events` alone (avoid redundant state). |
| `apps/api/services/agent_kill_test_report.py` (**new file**, pure helper, no new endpoint unless RESEARCH finds one required) | `assemble_kill_test_report(db, site_id, window_start, window_end) -> KillTestReport` — computes tool-discovery rate (tools/list calls), tool-call rate (tools/call calls / discovery calls), param-fill rate (calls with `params_complete=True` / total tools/call), lead-event count (`AgentLead` rows in window) from the metric columns above. Read-only aggregate query, mirrors `agent_aggregator.py`'s read-only posture. |
| `apps/api/services/rate_limiter.py` | No code change expected — reuse `limiter` instance; add a new named limit string constant in `agent_mcp.py` (e.g. `CONVERSION_TOOL_RATE_LIMIT = "5/minute"`, confirm exact value at EXECUTE — see Must-Fix 1 below) rather than modifying the limiter itself. |
| `apps/api/config.py` | Add new settings, default OFF/permissive per program precedent: `agent_concierge_qualification_enabled: bool = False` (gates the param-gating behavior itself — when OFF, tools behave exactly as today, ungated), `agent_concierge_conversion_enabled: bool = False` (gates whether `request_quote`/`book_demo` are exposed in `tools/list` and callable at all). |
| Migration (**new file**, name TBD, chains off current head — RE-RUN `alembic heads` at EXECUTE, do not hardcode) | Adds `agent_profiles.qualified_content` JSONB column (additive, nullable-with-default) AND creates `agent_leads` table. Confirm at EXECUTE whether these should be 2 separate migrations (cleaner rollback granularity) or 1 combined migration — default to 2 separate migrations, matching program precedent of one migration per logical schema change. |
| `tests/integration/test_agent_mcp_concierge.py` (**new file**) | Integration tests for AC-WS3-1 (param-gate with/without required params, `needs_more_info` shape), AC-WS3-2 (conversion tool call -> lead row + notification dispatch, mock-mode), AC-WS3-3 (lead resolves to company, read-only), rate-limit test for the conversion tool, prompt_safety-sanitization test (inject a hostile string in a qualification param, assert it never reaches the email body / lead row unsanitized), `initialize` handshake unit/integration test. |
| `tests/unit/test_agent_origin_exclusion.py` | Regression run only — NO new test added inside this file. A NEW test asserting WS3 leads never become emailable and never gain a `visitor_id`/`IdentifiedVisitor` link goes in the new `test_agent_mcp_concierge.py` file instead (per AC-WS3-4's "plus a new unit test" wording — keep it colocated with the rest of WS3's new surface, not inside the existing regression file). |

## Public Contracts

- **Existing surface extended, not replaced or broken**: `POST /api/v1/agent/{site_id}/mcp` gains
  a new `initialize` method and 2 new `tools/call` tool names (`request_quote`, `book_demo`). The 3
  existing tool names (`get_offers`, `get_pricing`, `check_availability`) keep their existing
  names and JSON-RPC envelope shape; their RESULT payload gains a new possible shape
  (`needs_more_info` with `missing_params`) alongside the existing success shape — this is an
  additive union type on the result, not a breaking change to a documented contract (no MCP client
  has shipped against this endpoint yet per SPEC's confirmed-gap framing).
- **New unauthenticated write path**: the conversion tool is the FIRST write-capable action this
  public, unauthenticated MCP surface exposes (all prior tools are pure GET-shaped reads). This is
  the single highest-risk change in this plan and is why VALIDATE is mandatory, not optional (see
  Verification Evidence + the two must-fixes below).
- **Same 404-not-403 tenancy posture**: `resolve_public_profile` gating is unchanged and reused
  verbatim for every new method — an unknown/disabled/flagged-off site still answers with the
  identical 404, no new distinguishing signal.
- **No existing contract elsewhere in the codebase changes.** `identity_classification.py`'s
  `is_emailable_identity` signature and logic are read-only referenced (for the isolation guarantee
  test) but not modified by this plan.

## Blast Radius

- **Risk classes present**: public API contract extension (new unauthenticated write action) +
  schema/migration (2 new pieces of schema). **2 of the 6 program high-risk classes are present** —
  this plan requires a full V1-V7 validate-contract before EXECUTE per guardrail 5 (no shortcut
  lane), and per program guardrail 1 the new write path must be regression-tested against the
  emailability-separation guarantee.
- **Files touched**: 11 direct touchpoints (2 new models/schemas files effectively — `agent_lead.py`
  new, `agent_kill_test_report.py` new — plus edits across `agent_mcp.py`, `agent_gateway.py`,
  `agent_profile.py`, `agent_fetch_event.py`, `agent_visit.py` (confirm-only), `schemas/agent_gateway.py`,
  `config.py`, 1-2 new migrations, 1 new integration test file) — well past the 5-file COMPLEX
  threshold named in the task instructions.
- **No change to**: `IdentifiedVisitor`, `Visitor` write paths, `identity_classification.py` logic,
  the 3 existing free tools' RESULT shape when qualification params ARE present (backward-compatible
  success case unchanged), any auth/session surface (this route has none — it's public by design),
  billing/credits.
- **Mock-mode**: the conversion tool's notification call must work under `MOCK_EXTERNAL_APIS=true`
  — confirm `email_sender.py`'s existing mock short-circuit covers this call site with no new code
  (SendGrid client is already mocked at the transport layer per program convention); if not, add
  the mock branch at EXECUTE time, do not skip mock-mode parity. **[VALIDATE P5]** Confirmed at
  VALIDATE: this assumption is **wrong** — `email_sender.py`'s `send()` has NO `MOCK_EXTERNAL_APIS`
  short-circuit today (0 matches for `mock_external_apis`/`MOCK_EXTERNAL_APIS` in that file, or
  anywhere else in the SendGrid call chain). The established test-level pattern for SendGrid-dependent
  code in this repo (`daily_digest.py`/`outcome_digest.py`) is `monkeypatch.setattr(EmailSender,
  "send", ...)` directly inside the test (see `tests/integration/test_outcome_digest.py`), NOT a
  runtime mock branch. WS3's new tests must follow this SAME monkeypatch pattern — do not add a
  new mock-mode branch inside `email_sender.py`; that would diverge from the file's established
  convention and is out of this plan's scope.

---

## Program Sequencing Note (read before EXECUTE)

Per the umbrella's Join Conditions: **WS3 MUST NOT begin its wild kill-test week (Step 5 below)
until WS0's exit metric (AC-WS0-5, >=1 real `identified_visitors` row via handoff on prod) is
met.** Steps 1-4 of this plan (the buildable code) have **no hard dependency on WS0** — the MCP
gateway extension is fully independent, testable code. Step 3's lead-to-company resolution reuses
`agent_company_resolution.py`'s existing read-only resolver, which does not require WS0's handoff
marker to function (it resolves via IP -> company, a separate mechanism from the marker/handoff
path) — confirm this independence explicitly at EXECUTE RESEARCH before treating Steps 1-4 as
fully unblocked. Step 5 (the wild kill test itself) is explicitly WS0-gated AND out of this plan's
buildable scope regardless (see Step 5 below).

---

## Implementation Checklist

Sequential, dependent steps as instructed — each step depends on the prior step's schema/dispatch
additions.

### Step 1 — `initialize` handler + spec-conformance (no dependencies)

1.1. **Before writing code**, read the current MCP lifecycle specification (`initialize` request/
   response shape: `protocolVersion`, `capabilities`, `serverInfo`) via `vc-docs-seeker` or direct
   spec fetch at EXECUTE time — do not hand-write the shape from memory; confirm the exact field
   names and the current protocol version string.
1.2. Add `initialize` to `agent_mcp.py`'s method dispatch (alongside `tools/list`/`tools/call`),
   returning a **STATIC** result: fixed `protocolVersion` (whatever the spec's current stable
   value is, confirmed in 1.1), a `capabilities` object declaring only `tools: {}` (this server
   only exposes tools, no resources/prompts), and a `serverInfo` object with a **static site-generic
   name** (e.g. `"beam-agent-concierge"`) and a static version string — **never** the real
   internal service version, build hash, or any per-site dynamic data (no internal/version data
   leak, per instruction).
1.3. `initialize` does NOT require `resolve_public_profile` gating to differ from existing
   methods — reuse Gate 1 (tenancy + flags) exactly as today; an unknown/disabled site still 404s
   before `initialize` is ever answered.
1.4. Add `initialize` to the strict method allow-list check (Gate 4) alongside the existing 2
   generic methods + `MCP_TOOLS` keys.

### Step 2 — Param-gated `tools/call` + qualified-content column + migration (depends on Step 1)

2.1. Add the new `agent_profiles.qualified_content` JSONB column via a new Alembic migration.
   **Re-run `alembic heads` immediately before writing the migration's `down_revision`** — do not
   hardcode a parent revision id; confirm the true current head on the branch this plan executes
   against (this worktree's head at drafting time was `a2f8d61c9e37`, but re-confirm live).
   Offline `--sql` validate both directions (`upgrade`/`downgrade`) before treating the migration as
   done; live apply is out of scope (program hard stop). **[VALIDATE — infra fit, confirmed]**
   Independently re-verified during VALIDATE (30-07-26): `a2f8d61c9e37` (`add_request_logs`) IS
   the true, single head of this worktree's migration chain — no branching (traced the full
   `revision`/`down_revision` graph across all 51 migration files, including the 2 merge-migration
   files with multi-line tuple `down_revision`s). Nothing else in this checkout chains off it. This
   confirms the plan's stated head was accurate at drafting time; still re-run `alembic heads` live
   at EXECUTE per the plan's own instruction, since other concurrent work may have advanced it since.
2.2. Add `_REQUIRED_QUALIFICATION_PARAMS = ("use_case", "company_size", "evaluating_against")` and
   `_missing_params(params: dict) -> list[str]` to `agent_gateway.py`.
2.3. Change the 3 existing tool functions' signatures from `(site, profile) -> dict` to
   `(site, profile, params) -> dict`. Inside each, call `_missing_params(params)` FIRST; if
   non-empty, return a `needs_more_info` shaped RESULT (`{"needs_more_info": True,
   "missing_params": [...]}`) — this is a JSON-RPC **result**, not an error (AC-WS3-1: "a clear
   request-for-params response, not a silent failure or a free answer" — explicitly NOT `-32602`).
   Reserve `-32602 Invalid params` strictly for malformed/wrong-typed params (e.g. `params` is not
   a dict at all, or `use_case` is present but not a string) — this distinction must be tested
   explicitly (see Verification Evidence).
2.4. When params ARE complete, apply the qualification-gated content: read
   `resolve_qualified_content(profile, use_case, evaluating_against)` (new function reading the
   Step 2.1 column) and merge/prefer it over (or alongside — confirm exact blending rule at
   EXECUTE RESEARCH against the SPEC's "structured real answer (configured pricing, comparisons,
   security questionnaire)" wording) the existing `build_offers`-derived content.
2.5. **Sanitize all 3 qualification param VALUES via `prompt_safety.clean_text` (or
   `sanitize_profiles` if the shape fits its existing signature better — confirm at EXECUTE) BEFORE
   they are used in `_missing_params`'s presence check echo-back, before they are logged, and before
   they reach ANY downstream consumer.** This is Must-Fix 2 (see below) — apply it here at the
   earliest point params enter the system, not only at the Step 3 lead-write/email site, so a
   sanitized value is what flows through the rest of the pipeline. Confirm `agent_mcp.py`'s
   existing "no raw-input echo" guard (module docstring point 4) is not weakened by any new
   response shape that might otherwise reflect an unsanitized qualification value.
   **[VALIDATE P1]** Resolved at VALIDATE: use `prompt_safety.clean_text(value, max_len)` directly,
   per-field — NOT `sanitize_profiles`. `sanitize_profiles` operates on a list of full
   visitor-profile dicts against its fixed `_TEXT_FIELD_CAPS` table, which does not include
   `use_case`/`company_size`/`evaluating_against`; calling it here would silently no-op (fields
   absent from that cap table pass straight through, unsanitized). Define new caps for these 3
   fields (design guidance: `use_case<=200`, `company_size<=100`, `evaluating_against<=200`) and
   call `clean_text(value, cap)` on each individually — this is the correct, existing primitive
   (it already strips `<`/`>`, which is this codebase's established sufficient mitigation for the
   email-body-interpolation risk; see `email_sender.py`'s `send()`, which does not itself
   HTML-escape `body_html`).
2.6. Update `agent_mcp.py`'s `tools/call` dispatch to extract `params.get("arguments")` (confirm
   exact MCP convention key at EXECUTE — some MCP clients nest tool args under `arguments`, others
   pass them flat under `params`; resolve against the spec read in Step 1.1) and pass it as the
   3rd positional arg to the tool function.
2.7. Update `_tools_list()`'s static tool declarations to add `inputSchema.required:
   ["use_case", "company_size", "evaluating_against"]` for the 3 existing tools, so a
   spec-conformant MCP client can pre-validate before calling (advisory only — the server-side gate
   in 2.3 is the actual enforcement; the client-side schema is documentation, not security).

### Step 3 — Conversion tool + lead table + migration + notification + BOTH must-fixes (depends on Step 2)

3.1. Add the `AgentLead` model (`apps/api/models/agent_lead.py`) per the Touchpoints table above.
   **Zero imports of `IdentifiedVisitor`, `Visitor`, or any write-capable identity module in this
   file** — this is the structural isolation guarantee; a code reviewer (or the regression test in
   3.9) must be able to confirm isolation by inspecting this file's import list alone.
3.2. Add the corresponding migration (creates `agent_leads` table). Same re-run-`alembic-heads`
   discipline as 2.1; chains AFTER the qualified_content migration (or is combined per the 2.1
   decision). Offline `--sql` validate both directions. **[VALIDATE note]** the codebase's
   documented offline-`--sql` gotcha (`b7d3e9f1a4c2`'s `sa.inspect(bind)` call breaks the unscoped
   `upgrade head --sql` shorthand) sits UPSTREAM of this worktree's head (`a2f8d61c9e37`), not
   between it and the new WS3 migrations — so validating with an explicit incremental range
   (`alembic upgrade <true-head-at-EXECUTE>:head --sql`, per the plan's own re-run-heads
   discipline) avoids the gotcha entirely; do not run the unscoped `upgrade head --sql` shorthand
   regardless.
3.3. Add `tool_request_quote` / `tool_book_demo` to `agent_gateway.py`'s `MCP_TOOLS` registry —
   both gated behind `_missing_params` exactly like the 3 read tools (a quote/demo request without
   qualification context is not useful to the site owner either). On complete params: **sanitize
   again defensively** (params were already sanitized at Step 2.5's entry point, but this is the
   write boundary — apply `clean_text`/`sanitize_profiles` a second time immediately before
   constructing the `AgentLead` row and the email body, treating Step 2.5 as defense-in-depth, not
   the only gate) → insert an `AgentLead` row → attempt read-only company resolution via
   `agent_company_resolution.py`'s existing resolver (confirm the exact function name/signature at
   EXECUTE — it currently operates on `AgentVisit` rows; confirm whether it needs a thin adapter to
   accept an IP directly, or whether the conversion tool call already has an associated
   `AgentVisit`/`AgentFetchEvent` row via `record_gateway_visit` that can be threaded through) → set
   `resolved_company_id` on the new lead row if resolution succeeds (still read-only — no
   `IdentifiedVisitor` write, no `Visitor` write).

   **[VALIDATE P2 — MANDATORY, security]** `record_gateway_visit` does not exist anywhere in this
   codebase (confirmed via repo-wide grep, 0 matches). The real plumbing is
   `persist_agent_visit`/`persist_agent_fetch_event` (`apps/api/services/agent_visit_persistence.py`
   — the same functions `events.py` and `agent_fetch_beacon.py` already call). Both REQUIRE an
   `AgentClassification` object from `agent_classifier.classify_agent(user_agent)`, which returns
   `None` for any UA that does not match a known crawler pattern — an MCP JSON-RPC tool-call (a
   machine-to-machine POST, not a page-fetch crawler hit) may well return `None` here, so wiring
   this is a genuine design decision for EXECUTE's own RESEARCH sub-step, not a naming lookup.

   **Separately, and more importantly:** `agent_company_resolution.py`'s ONLY existing resolver is
   `run_company_resolution_sweep()`, an async BATCH job that internally calls
   `IdentityResolver.resolve()` — the SAME multi-provider PAID waterfall (Leadpipe/Capturify/RB2B
   in parallel, then PDL/IPinfo, then Hunter/Apollo — real external HTTP calls) used for organic
   visitor identification, budget-gated at 50/day/site. Calling this SYNCHRONOUSLY inside the
   conversion-tool's request/response cycle would let an unauthenticated caller — even at the
   tighter Must-Fix-1 rate limit — drain a site's ENTIRE daily identity-resolution budget via
   repeated `request_quote`/`book_demo` calls from a resolvable (non-datacenter) IP, starving
   legitimate visitor resolution for the rest of that day. This is a real, previously-unaddressed
   abuse vector, distinct from and NOT mitigated by Must-Fix 1's rate limit (which limits request
   RATE, not shared-budget consumption per accepted request) — this codebase has already solved
   the same class of problem for a different endpoint (`/ingest`'s rotating-IP-flood hardening,
   `site_ingest_limit_enabled`); this plan must apply the same lesson here.

   **MANDATORY: EXECUTE must choose exactly ONE of:**
   - **(a)** Resolve `resolved_company_id` synchronously using ONLY already-free/cached signals
     (e.g. a read-only `CompanyGraphNode` lookup by IP, or rDNS only — zero paid-provider spend)
     and leave it `null` when no free hit exists. Never invoke `IdentityResolver.resolve()` inline.
   - **(b)** Defer resolution entirely to the EXISTING async `run_company_resolution_sweep` batch
     job: create a corresponding `AgentVisit` row for the lead's IP and leave `resolved_company_id`
     `null` at lead-creation time (populated later by the next sweep run, subject to the sweep's
     own `limit`/budget/30-day-no-retry gates — same treatment as all other agent traffic).

   Do **NOT** call `IdentityResolver.resolve()` (or `run_company_resolution_sweep()`) synchronously
   from the JSON-RPC request handler under any circumstance. This is now a third non-negotiable
   must-fix (Must-Fix 3), on the same footing as Must-Fix 1/2 below — see the new mandatory test
   gate in the Validate Contract.
3.4. **ACCEPT-AND-RETURN pattern**: write the `AgentLead` row synchronously (fast, DB-only) FIRST,
   return the JSON-RPC success result to the caller, THEN fire the owner-notification email
   fail-open (wrapped in try/except, logged-on-failure via keys only per PII/GDPR guard, never
   raises, never blocks or delays the JSON-RPC response) — mirror `record_gateway_visit`'s
   fail-open pattern exactly. Confirm at EXECUTE whether "synchronous then fire-and-forget" is
   achievable within a single FastAPI request handler without a background-task primitive (e.g.
   `BackgroundTasks`) — if the notification must not block the response at all, use
   `BackgroundTasks.add_task`; if a few hundred ms of synchronous SendGrid latency is acceptable
   before responding (matching `daily_digest.py`/`outcome_digest.py`'s synchronous `sender.send`
   precedent), a plain awaited call wrapped in try/except is simpler and sufficient — default to
   the simpler synchronous-but-fail-open call unless RESEARCH finds a latency budget requirement.
3.5. Notification content: `sender.send(to_email=<site owner email, joined via Site.user_id ->
   User.email exactly like daily_digest.py/outcome_digest.py>, subject=..., body_html=..., db=db,
   branding=False, custom_args={"site_id": site_id, "lead_id": str(lead.id)})` — the sanitized
   qualification fields (use_case/company_size/evaluating_against) are interpolated into
   `body_html` ONLY after Step 2.5 + 3.3's double-sanitization; never interpolate the raw
   JSON-RPC params dict directly into an f-string body.
3.6. **Must-Fix 1 — dedicated conversion-tool rate limit.** Add a SEPARATE, tighter
   `@limiter.limit(...)` (or an equivalent manual check using the same `limiter` instance keyed
   the same way as the existing per-site/per-IP pattern) scoped ONLY to the `request_quote`/
   `book_demo` dispatch branch inside `agent_mcp.py`'s `mcp_endpoint`, distinct from the shared
   `MCP_RATE_LIMIT = "60/minute"` read-tool budget. Confirm the exact tighter value at EXECUTE —
   design guidance: an order of magnitude tighter than the read budget (e.g. `5/minute` per the
   same key), matching the "prevent an abuser spamming the owner's inbox up to 60 leads/min" intent
   from the task instructions. Mirror the per-site-ceiling precedent's key strategy
   (`request.state.site_id` or the resolved IP, confirm which is more appropriate for an
   unauthenticated public route with no prior `Depends()`-injected site_id state — `agent_mcp.py`'s
   `site_id` is a path param already, so keying on it directly is likely simplest; confirm no
   collision with slowapi's existing per-route key function).
   **[VALIDATE P3]** Confirmed mechanically feasible: mirror `rate_limiter.py`'s existing
   `site_ceiling_tripped()` precedent — a manual `limiter.hit(RateLimitItemPerMinute(N),
   "mcp_conversion_tool", site_id)` call (NOT a second `@limiter.limit(...)` route decorator, since
   slowapi decorators apply to the WHOLE route, not one dispatch branch inside it). Use a distinct
   namespace string (`"mcp_conversion_tool"`) so this never collides with the existing
   `"site_ingest"` namespace already hit against the same limiter instance for a different purpose.
3.7. **Must-Fix 2 — mandatory prompt_safety sanitization, confirmed end-to-end.** Add an explicit
   integration test (see Verification Evidence) that injects a hostile string (e.g. containing
   `<script>`, prompt-injection framing like "ignore previous instructions", or raw `<>` fence
   characters) into each of the 3 qualification params, calls the conversion tool, and asserts: (a)
   the stored `AgentLead` row's fields do NOT contain the raw hostile string (sanitized form only),
   and (b) the constructed email `body_html` (assert via a test hook / mock on `email_sender.send`
   capturing the call args, NOT a live send) does NOT contain the raw hostile string either. This
   is the proof that Step 2.5 + 3.3's double-sanitization actually holds end-to-end, not just that
   the functions were called.
3.8. Add `agent_concierge_conversion_enabled` flag check (from `config.py`) as an EARLY gate in the
   conversion-tool dispatch branch — when OFF, `request_quote`/`book_demo` are absent from
   `_tools_list()` output AND return `-32601 Method not found` if called directly (same posture as
   an unrecognized method today), matching program precedent of flag-gated new surfaces defaulting
   OFF and behaving as if they don't exist.
3.9. Add the isolation-regression test (belongs in the new `test_agent_mcp_concierge.py` file, not
   inside `test_agent_origin_exclusion.py` itself — see Touchpoints table): assert an `AgentLead`
   row has no `visitor_id` column at all (schema-level proof) and that
   `tests/unit/test_agent_origin_exclusion.py`'s full existing suite stays green with zero new
   failures (regression run only, no edits to that file).

### Step 4 — Kill-test metric fields + report-assembly helper (depends on Step 3)

4.1. Add the new nullable columns to `AgentFetchEvent` per the Touchpoints table (`tool_name`,
   `params_provided`, `params_complete`) via a migration — confirm whether this can be folded into
   the Step 3.2 migration (same logical "add WS3 tracking columns" change) or needs its own; default
   to folding it in with Step 3.2's migration if both are additive/nullable to keep migration count
   minimal, unless RESEARCH finds a reason to separate them (e.g. wanting independent rollback
   granularity for the lead table vs. the metric columns).
4.2. Wire `record_gateway_visit` (or a thin new call site inside `agent_mcp.py`'s `tools/call`
   dispatch, confirm which is cleaner) to populate the new `tool_name`/`params_provided`/
   `params_complete` columns on the `AgentFetchEvent` row it already creates for every recognized
   MCP tool call — this is additive instrumentation on an existing write path, not a new write path.
   **[VALIDATE P4]** Correction: there is NO existing write path today — confirmed via grep,
   `agent_mcp.py`/`agent_gateway.py` call neither `persist_agent_visit` nor
   `persist_agent_fetch_event` anywhere; MCP tool calls currently create zero `AgentVisit`/
   `AgentFetchEvent` rows. This wiring depends on Step 3.3(P2)'s `AgentClassification`/vendor
   question: `AgentFetchEvent.vendor` and `AgentVisit.vendor` are both NOT NULL, so populating a
   row for an MCP call (which may have no classifiable UA at all — `classify_agent()` returns
   `None` for unrecognized UAs) requires EXECUTE's own RESEARCH to pick a literal vendor value for
   JSON-RPC-originated rows (e.g. a new fixed string distinct from the existing UA-classified
   vendor names), or to decide the kill-test metrics should be computed from a different source
   (e.g. new counters colocated on `AgentLead`/a dedicated counter table) instead of shoehorning
   into the vendor-classified `AgentFetchEvent` table. Either is acceptable; leaving this
   unresolved is not — Step 4's entire report-helper deliverable depends on this being decided.
4.3. Add `apps/api/services/agent_kill_test_report.py` with `assemble_kill_test_report(db, site_id,
   window_start, window_end) -> KillTestReport` (pure read-only aggregate query function, mirrors
   `agent_aggregator.py`'s posture): computes tool-discovery rate (count of `tools/list` calls in
   window), tool-call rate (count of `tools/call` calls / discovery calls), param-fill rate (count
   of `params_complete=True` rows / total `tools/call` rows), lead-event count (`AgentLead` row
   count in window). No new endpoint required for this plan's scope — confirm at EXECUTE RESEARCH
   whether Step 5's eventual GO/NO-GO report needs this exposed via an API route (likely not — it's
   an operator-run script/notebook query during the wild week, matching WS0's Agent-Probe
   evidence-gathering posture) or whether a thin `GET` route is worth adding now for convenience.
   Default to NOT adding a new route in this plan unless RESEARCH finds a concrete need — avoid
   growing the public/auth surface further than necessary for a helper that exists to support a
   manual review process.
4.4. Unit test `agent_kill_test_report.py`'s math against a seeded fixture (2-3 sites, mixed
   discovery/call/param-fill/lead counts) — Fully-Automated, no wild data needed to test the
   ARITHMETIC (the wild data itself is Step 5's job).

### Step 5 — BACKLOG STUB (WS0-gated, NOT buildable in this plan)

**Do not attempt to build or test this step now.** Record as an explicit, dated known-gap.

- **AC-WS3-5** (>=20 real wild ChatGPT/Claude queries over 1 week against 1 real pilot site,
  measured via the Step 4.3 report helper) and **AC-WS3-6** (signed GO/NO-GO verdict from that
  data) are gated on: (a) WS0's exit metric (AC-WS0-5) being met on production, (b) this plan's
  Steps 1-4 being merged and live on that pilot site, and (c) an actual 1-week wild observation
  window with a real MCP client (ChatGPT Developer Mode / Claude) pointed at the pilot site's MCP
  URL. None of these can be satisfied inside this PLAN/EXECUTE/VALIDATE cycle — this is a real-world
  waiting period + manual review, not a code deliverable.
- Write a backlog note at UPDATE PROCESS time (`process/features/agent-native-revenue/backlog/
  ws3-wild-kill-test_NOTE_[date].md`) documenting: the exact operator steps to run the wild week
  once WS0 is live (get the pilot site's MCP URL into ChatGPT Developer Mode / Claude, wait 1 week,
  run `assemble_kill_test_report`, write the GO/NO-GO), and the explicit dependency on WS0(d)'s
  exit metric.
- AC-WS3-1 through AC-WS3-4 (Steps 1-4's code + tests) are closeable NOW and do not wait on this
  step. This plan reaches **CODE DONE**, not **VERIFIED**, per the program's wild-test discipline
  (guardrail 3) — do not mark this plan `✅ VERIFIED` in any phase report or the umbrella status
  table until AC-WS3-5/6 close on real wild data.

---

## Acceptance Criteria

Direct mapping from the program SPEC's WS3 section (`agent-native-revenue_SPEC_30-07-26.md`):

1. **AC-WS3-1** — MCP tools (`get_offers`/`get_pricing`/`check_availability` or successors) are
   gated to return a structured real answer only when the caller supplies required qualification
   params; missing params produce a clear request-for-params response, not a silent failure or a
   free answer. Testable now: integration test with/without required params (Step 2).
2. **AC-WS3-2** — New zero-click conversion tool (`request_quote`/`book_demo`) is callable and, on
   sufficient context, creates a real lead event with qualification context, delivered to the site
   owner's inbox. Testable now: integration test asserting lead record + notification dispatch
   (mock-mode) (Step 3).
3. **AC-WS3-3** — Every lead resolves through the existing identity path (WS0's
   `agent_company_resolution.py`) to a real company wherever possible — not merely a tool-call log.
   Testable now: integration test asserting `resolved_company_id` set when the caller's IP is
   resolvable (Step 3).
4. **AC-WS3-4** — No lead/contact record created through this path is ever automatically merged
   into or made emailable through the existing agent-exclusion-guarded identity graph without
   passing through this explicit tool/form-submission consent path; `source_agent_visit_id`
   exclusion never weakened. Testable now: `test_agent_origin_exclusion.py` regression + new
   isolation-proof unit test (Step 3.9).
5. **AC-WS3-5** — >=20 real wild ChatGPT/Claude queries over 1 week on 1 pilot site, measured
   tool-discovery/tool-call/param-fill/lead-count rates. **WS0-gated known-gap — not closeable in
   this plan** (Step 5, backlog stub).
6. **AC-WS3-6** — Signed GO/NO-GO verdict from AC-WS3-5's data. **WS0-gated known-gap — not
   closeable in this plan** (Step 5, backlog stub).

Plan is considered complete for EXECUTE purposes when AC-WS3-1 through AC-WS3-4 are green (all
Fully-Automated / Hybrid gates pass) and AC-WS3-5/6 are recorded as explicit, dated known-gaps with
a written backlog note (not silently dropped).

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Integration test: `initialize` method returns static `protocolVersion`/`capabilities`/`serverInfo`, no internal version/build data present | Fully-Automated | Spec-conformance guardrail (task instruction D1) |
| Integration test: `tools/call` for `get_pricing` with 0 of 3 required params returns `needs_more_info` RESULT (not `-32602`) listing all 3 missing fields | Fully-Automated | AC-WS3-1 |
| Integration test: `tools/call` for `get_pricing` with all 3 required params (valid types) returns the qualified-content-blended structured answer, `-32602` reserved only for malformed/wrong-typed params (separate test case: `use_case` as an int) | Fully-Automated | AC-WS3-1 |
| Integration test: `tools/call` for `request_quote` with complete params creates an `AgentLead` row, calls `email_sender.send` (mocked/asserted, `MOCK_EXTERNAL_APIS=true`), response returns before/independent of email outcome (fail-open) | Fully-Automated | AC-WS3-2 |
| Integration test: `email_sender.send` raises inside the fail-open wrapper — assert the JSON-RPC response is STILL a success result (lead row committed), not a 500 | Fully-Automated | AC-WS3-2 (fail-open guarantee) |
| Integration test: `request_quote` call from a resolvable non-datacenter IP sets `resolved_company_id` on the lead row via `agent_company_resolution.py`'s existing resolver; from a datacenter/unresolvable IP, `resolved_company_id` stays null (no invented company) | Fully-Automated | AC-WS3-3 |
| Regression: `tests/unit/test_agent_origin_exclusion.py` full suite, zero new failures | Fully-Automated | AC-WS3-4 / AC-G-1 |
| New unit/integration test: `AgentLead` model has no `visitor_id` FK/column; a lead row can never be joined into `IdentifiedVisitor`/`is_emailable_identity` (import-list assertion + schema introspection) | Fully-Automated | AC-WS3-4 |
| Integration test: conversion-tool rate limit — Nth+1 call within the window from the same site_id/key is rejected (429 or JSON-RPC error, confirm shape at EXECUTE), distinct from and tighter than the shared 60/min read budget | Fully-Automated | Must-Fix 1 |
| Integration test: hostile string (`<script>`, prompt-injection framing) injected into each of the 3 qualification params via `request_quote` — assert neither the stored `AgentLead` row nor the captured email `body_html` contains the raw hostile string | Fully-Automated | Must-Fix 2 |
| Integration test: `agent_concierge_conversion_enabled=False` — `request_quote`/`book_demo` absent from `tools/list`, direct call returns `-32601` | Fully-Automated | Flag-gated-default-OFF program precedent |
| Unit test: `assemble_kill_test_report` arithmetic against a seeded fixture (2-3 sites, mixed counts) | Fully-Automated | Step 4 metric correctness (supports AC-WS3-5/6, does not itself close them) |
| Migration offline `--sql` validate both directions (`upgrade`/`downgrade`) for both new migrations, against the TRUE current `alembic heads` re-confirmed at EXECUTE | Fully-Automated | Schema-change safety (no live apply in scope) |
| Wild-query journal + GO/NO-GO report | Agent-Probe (needs-live-provider) | AC-WS3-5 (known-gap, WS0-gated — Step 5 backlog stub, NOT closeable in this plan) |
| Signed GO/NO-GO verdict document | Agent-Probe (needs-live-provider) | AC-WS3-6 (known-gap, WS0-gated — Step 5 backlog stub, NOT closeable in this plan) |

**[VALIDATE — tier reclassification note]** Every row above whose "Strategy" says "Fully-Automated"
and whose evidence lives in the NEW `tests/integration/test_agent_mcp_concierge.py` file actually
requires local Postgres+Redis (`docker compose -f infra/docker-compose.yml up -d postgres redis`)
per this repo's `pytest -m integration` lane — per this repo's established validate-contract
convention (see `cadence-bot-flag`'s validate-contract), that precondition makes these rows
**Hybrid**, not Fully-Automated. The authoritative, corrected tier assignment is in the
`## Validate Contract` → Test Gates table below; this table is left as originally drafted
(historical) rather than edited row-by-row.

**C-4 reconciliation**: the `strategy` column above carries only the 3 proving strategies
(Fully-Automated / Hybrid / Agent-Probe). AC-WS3-5/6 are Agent-Probe (a real, fully-specified
proving strategy — the wild-query journal and GO/NO-GO report format are defined), not Known-Gap;
they are simply gated (WS0 dependency + real-world wait time) and out of this plan's buildable
scope. The developed behavior in this plan (Steps 1-4: the gateway extension, lead table,
notification, metrics) is proven now by Fully-Automated gates — the vacuous-green ban does not
apply, since no developed behavior in Steps 1-4 rests on Known-Gap alone. Step 5 is explicitly
carved out as a backlog stub per the task instructions, not silently dropped.

## Test Infra Improvement Notes

(none identified yet)

---

## Validate Contract

Status: CONDITIONAL
Date: 30-07-26
date: 2026-07-30
generated-by: inner-pvl: WS3

Parallel strategy: sequential
Rationale: 7-signal score 3/7 (S2 schema/API/auth surface — public unauthenticated write path + 2
migrations; S6 high-risk class in plan — public API contract extension + schema/migration both
explicitly named; S7 5+ files in blast radius — 11 direct touchpoints). This would normally
recommend parallel subagents for the Layer 1/Layer 2 fan-out, but per explicit orchestrator
instruction this VALIDATE ran as ONE deep-mode analytical pass (no Agent/Task tool available in
this session to spawn parallel sub-agents) — all 4 Layer 1 dimensions and all 5 Implementation
Checklist step-sections were analyzed sequentially with equivalent rigor: direct source reads of
every touchpoint file, independent reconstruction of the full alembic migration graph (51 files,
confirming the true single head), repo-wide greps confirming/refuting the plan's own factual
claims (`record_gateway_visit` existence, `email_sender.py` mock-mode short-circuit existence),
and cross-referencing this repo's established validate-contract conventions (`cadence-bot-flag`,
`ws1-ai-evaluation-timeline` in this same program) for tier-classification and schema consistency.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC-WS3-1 | `tools/call` for the 3 read tools with 0/3 required params returns `needs_more_info` (not `-32602`), listing all missing fields; with all 3 valid-typed params returns the qualified-content answer; malformed/wrong-typed params (e.g. `use_case` as int) get `-32602` | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_agent_mcp_concierge.py -k "param_gate or needs_more_info or invalid_params" -m integration -q` (new file; precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`) | A |
| AC-WS3-2 | `request_quote`/`book_demo` with complete params creates an `AgentLead` row + calls `email_sender.send` (mocked/asserted via `monkeypatch.setattr(EmailSender, "send", ...)`, per P5 correction below — NOT `MOCK_EXTERNAL_APIS`); response returns independent of email outcome; `send` raising does not turn the JSON-RPC response into a 500 | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_agent_mcp_concierge.py -k "conversion_tool or fail_open" -m integration -q` (precondition: docker-compose postgres+redis) | A |
| AC-WS3-3 | Lead from a resolvable non-datacenter IP gets `resolved_company_id` set via a FREE-ONLY lookup or the deferred async sweep (per Must-Fix 3 below — never the synchronous paid waterfall); datacenter/unresolvable IP stays null | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_agent_mcp_concierge.py -k "company_resolution" -m integration -q` (precondition: docker-compose postgres+redis) | A |
| AC-WS3-4 | `test_agent_origin_exclusion.py` full suite, zero new failures; `AgentLead` has no `visitor_id` column (schema introspection) and no import of `IdentifiedVisitor`/`Visitor`/any write-capable identity module (import-list grep) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q` + `.venv/bin/python3.11 -m pytest tests/integration/test_agent_mcp_concierge.py -k "isolation" -m integration -q` (2nd command is Hybrid; 1st is Fully-Automated — see split below) | A |
| MF-1 | Conversion-tool rate limit: Nth+1 call within the window from the same site_id is rejected, distinct from and tighter than the shared 60/min read budget; implemented via a manual `limiter.hit(...)` call (P3), never a 2nd route-level decorator | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_agent_mcp_concierge.py -k "rate_limit" -m integration -q` (precondition: docker-compose postgres+redis) | A |
| MF-2 | Hostile string (`<script>`, prompt-injection framing) in each of the 3 qualification params never reaches the stored `AgentLead` row or the captured email `body_html` unsanitized, via `prompt_safety.clean_text` (P1), called directly per-field (not `sanitize_profiles`) | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_agent_mcp_concierge.py -k "sanitiz" -m integration -q` (precondition: docker-compose postgres+redis) | A |
| MF-3 (VALIDATE-added) | `request_quote`/`book_demo` NEVER synchronously invokes `IdentityResolver.resolve()` (or `run_company_resolution_sweep()`) inline in the request/response cycle — asserted by a call-count/monkeypatch check on the identity-provider mixins (e.g. assert zero calls to any `identity_providers/*` HTTP mixin during a `request_quote` call) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/integration/test_agent_mcp_concierge.py -k "no_sync_waterfall" -m unit -q` (new test; pure monkeypatch/call-count assertion, no live DB or network needed) | B |
| FLAG | `agent_concierge_conversion_enabled=False` — tools absent from `tools/list`, direct call returns `-32601` | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_agent_mcp_concierge.py -k "flag_disabled" -m integration -q` (precondition: docker-compose postgres+redis) | A |
| initialize | `initialize` returns static `protocolVersion`/`capabilities`/`serverInfo`; no internal version/build-hash leak | Hybrid | `.venv/bin/python3.11 -m pytest tests/integration/test_agent_mcp_concierge.py -k "initialize" -m integration -q` (precondition: docker-compose postgres+redis) | A |
| KTR | `assemble_kill_test_report` arithmetic correct against a seeded fixture (2-3 sites, mixed discovery/call/param-fill/lead counts) | Fully-Automated | `.venv/bin/python3.11 -m pytest tests/unit/test_agent_kill_test_report.py -m unit -q` (new file) | A |
| MIG | Both new migrations offline `--sql` validate both directions, against the TRUE `alembic heads` re-confirmed at EXECUTE, using an explicit incremental rev-range (never the unscoped `upgrade head --sql` shorthand — see gotcha note at Step 3.2) | Fully-Automated | `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` (re-confirm) THEN `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade <confirmed-head>:head --sql` AND `downgrade head:<confirmed-head> --sql` | A |
| AC-WS3-5 | >=20 real wild ChatGPT/Claude queries over 1 week on 1 pilot site | Agent-Probe (needs-live-provider) | Wild-query journal, per Step 5 backlog stub | D |
| AC-WS3-6 | Signed GO/NO-GO verdict from AC-WS3-5's data | Agent-Probe (needs-live-provider) | Written GO/NO-GO report citing the AC-WS3-5 journal, per Step 5 backlog stub | D |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist — MF-3 is a NEW gate this VALIDATE
  pass added directly to the checklist via Plan Update P2)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: the `strategy:` column above carries ONLY the 3 proving strategies
(Fully-Automated / Hybrid / Agent-Probe). AC-WS3-5/6 are Agent-Probe (fully-specified, gated), not
Known-Gap — consistent with the plan's own C-4 reconciliation note. Known-Gap is never used as a
`strategy:` value here; it is carried via gap-resolution D against those two rows only.

Legacy line form (retained so existing validate-contract consumers still parse):
- AC-WS3-1/2/3/MF-1/MF-2/FLAG/initialize/isolation-part-2: Hybrid: `.venv/bin/python3.11 -m pytest tests/integration/test_agent_mcp_concierge.py -m integration -q` (new file, one full-file run covers all of the above; precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`)
- AC-WS3-4 regression: Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py -m unit -q`
- MF-3 (VALIDATE-added): Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_agent_mcp_concierge_no_sync_waterfall.py -m unit -q` (new file, or a `-k` subset of the integration file run in unit mode via full mocking)
- KTR: Fully-automated: `.venv/bin/python3.11 -m pytest tests/unit/test_agent_kill_test_report.py -m unit -q`
- MIG: Fully-automated: `.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini heads` + offline `--sql` upgrade/downgrade, explicit rev-range
- AC-WS3-5/6: known-gap: documented as backlog stub (Step 5) — WS0-gated, not closeable in this plan

Failing stub (MF-3, Fully-Automated — the one genuinely NEW gate this VALIDATE pass added):
```
test("should never synchronously call IdentityResolver.resolve() from request_quote/book_demo", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: monkeypatch every identity_providers/* HTTP mixin method to raise-if-called; call request_quote with a resolvable IP; assert zero mixin calls occurred and resolved_company_id is either null or set via the free-only/deferred-sweep path only")
})
```

Failing stub (AC-WS3-1, Fully-Automated portion only — the malformed-params `-32602` case, which
needs no DB/network and is safely unit-testable against the pure `_missing_params`/type-check logic):
```
test("should return -32602 Invalid params only for malformed/wrong-typed params, never for missing-but-well-typed params", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub: call _missing_params / the tool-call type-check path with use_case=123 (wrong type), assert -32602; with use_case absent, assert needs_more_info result, not -32602")
})
```

(Hybrid and Agent-Probe rows do not receive stubs per policy.)

Dimension findings:
- Infra fit: CONCERN — migration head (`a2f8d61c9e37`) independently re-confirmed accurate and
  single (no branching); the offline-`--sql` `sa.inspect` gotcha sits upstream of it, so an
  incremental rev-range validate avoids it cleanly. CONCERN because Steps 3.3/4.2 assumed an
  existing `record_gateway_visit`/AgentVisit-per-MCP-call wiring that does not exist (0 grep
  matches) and cannot be added without a design decision on `AgentClassification`/vendor for a
  caller type the existing UA classifier was never built to see — resolved via mandatory Plan
  Updates P2/P4 above; not a FAIL because the fix is a scoped, in-touchpoint design decision, not
  new architecture.
- Test coverage: CONCERN — tier assignments in the plan's own Verification Evidence table mislabel
  every new-integration-test row as Fully-Automated when this repo's own convention (docker-compose
  Postgres+Redis precondition = Hybrid, see `cadence-bot-flag`'s validate-contract) puts them at
  Hybrid; corrected in the Test Gates table above. AC-WS3-5/6 correctly recorded as Agent-Probe
  known-gaps (not silently dropped), matching the C-4/vacuous-green rules.
- Breaking changes: PASS — additive union-type result shape on the 3 existing tools (
  `needs_more_info` alongside existing success shape); 2 new tool names; no existing method,
  schema, or client-visible contract is altered or removed. `resolve_public_profile`'s 404-not-403
  posture is reused verbatim for every new method.
- Security surface: CONCERN (resolved via mandatory plan updates, would otherwise be FAIL) — the
  2 explicitly named must-fixes (rate limit, sanitization) ARE mechanically feasible and now
  concretely specified (P1/P3 above, both confirmed against real precedent already in this
  codebase: `site_ceiling_tripped()` and `prompt_safety.clean_text()`). A THIRD, self-discovered
  gap — synchronous invocation of the paid identity-resolution waterfall from an unauthenticated
  write endpoint, an unmitigated budget-exhaustion/DoS vector distinct from the rate-limit — was
  found and is now closed via the mandatory Must-Fix 3 constraint + new test gate (P2 above,
  gap-resolution B). `initialize`'s no-version-leak requirement is already correctly specified in
  Step 1.2 (static site-generic name/version). No emailability-guardrail weakening found;
  `AgentLead`'s structural isolation (no `visitor_id`, no identity-module imports) is
  well-specified and independently testable.
- Section — Step 1 (`initialize` handler): PASS — mechanically feasible; reuses Gate 1/Gate 4
  verbatim; the only open item (exact MCP `initialize` field names/protocol version string) is
  correctly deferred to EXECUTE's own spec-fetch RESEARCH sub-step, consistent with this plan's
  established "confirm at EXECUTE" pattern elsewhere. No conflicts found.
- Section — Step 2 (param-gating + qualified-content column): CONCERN, resolved — the
  `clean_text`-vs-`sanitize_profiles` ambiguity (2.5) is now resolved (P1): `sanitize_profiles`
  does not cover these 3 fields at all and would have silently no-op'd sanitization; `clean_text`
  called per-field is correct and mechanically confirmed. Migration head handling is sound
  (re-confirmed accurate). Highest-risk edit: the `-32602`-vs-`needs_more_info` distinction in 2.3
  — already correctly test-planned in Verification Evidence and the Test Gates table above.
- Section — Step 3 (conversion tool + lead table + must-fixes): CONCERN, resolved via mandatory
  instructions — this section carried the plan's single most significant gap (the synchronous
  paid-waterfall budget-exhaustion vector, P2/Must-Fix 3) plus a factual error (`record_gateway_visit`
  does not exist). Both are now closed with concrete, mechanically-grounded instructions (reusing
  real existing precedents: `persist_agent_visit`/`persist_agent_fetch_event`, `CompanyGraphNode`,
  `site_ceiling_tripped()`). The structural isolation guarantee (3.1/3.9) is well-specified and
  needs no changes. Highest-risk edit: 3.3's company-resolution call site — mitigated by Must-Fix 3.
- Section — Step 4 (kill-test metrics): CONCERN, resolved — depends entirely on Step 3(P2)'s
  resolution; flagged the `AgentFetchEvent.vendor`/`AgentVisit.vendor` NOT NULL constraint against
  an MCP caller with no classifiable UA (P4) as a genuine open design decision, not a naming
  question. Arithmetic itself (4.3/4.4) is well-scoped and testable with a seeded fixture,
  independent of the wiring question.
- Section — Step 5 (backlog stub): PASS — correctly scoped as a WS0-gated, real-world-wait-time
  known-gap; matches the program's wild-test discipline and the C-4/vacuous-green rules exactly.
  No changes needed.

Open gaps:
- AC-WS3-5/6: known-gap: documented as backlog stub — gated on WS0's exit metric (AC-WS0-5)
  landing live in production, plus a real 1-week wild observation window (Step 5). Not counted
  toward CONDITIONAL/BLOCKED — explicitly named, dated, and cross-referenced to the plan's own
  Step 5 section and the future backlog note path
  (`process/features/agent-native-revenue/backlog/ws3-wild-kill-test_NOTE_[date].md`).
- Exact MCP transport wiring / `initialize` protocol version string / `arguments` vs flat `params`
  key: correctly deferred to EXECUTE's own spec-fetch RESEARCH sub-step (Step 1.1/2.6) — not a
  VALIDATE-blocking gap, this is the plan's own established pattern for implementation-detail
  confirmation, consistent with the program SPEC's own "Open Questions... deferred to each
  workstream's own RESEARCH step" framing.
- Whether Step 2.1/3.2's migrations are 1 combined or 2 separate files: correctly deferred to
  EXECUTE, non-blocking either way (both are additive/nullable).

What this coverage does NOT prove:
- The Hybrid integration gates (AC-WS3-1/2/3, MF-1/2, FLAG, initialize) prove correct behavior
  against seeded fixtures in a local Postgres+Redis environment — they do not prove behavior
  against a REAL MCP client's actual request shape (ChatGPT Developer Mode / Claude), which is
  exactly what Step 5's wild kill test (AC-WS3-5/6) exists to close, and is out of this plan's
  buildable scope.
- MF-3's call-count assertion proves the code path structurally cannot reach the paid waterfall —
  it does not itself prove which of options (a)/(b) EXECUTE chose is the RIGHT product behavior
  for AC-WS3-3 (i.e., whether leaving `resolved_company_id` null more often than the plan's
  original synchronous-resolution framing implied is an acceptable product tradeoff) — that is an
  EXECUTE-time design decision this VALIDATE pass deliberately leaves open (both options are safe;
  neither is mandated over the other).
- The `test_agent_origin_exclusion.py` regression proves this plan's additions do not weaken
  existing emailability exclusion — it does not re-verify the exclusion logic's own correctness
  (that suite's existing, unchanged scope).
- KTR's arithmetic test proves the report-helper's MATH is correct against a seeded fixture — it
  does not prove the underlying counters (`tool_name`/`params_provided`/`params_complete`) are
  populated correctly in production, which depends on Step 4's still-open wiring decision (P4)
  and is not independently gated here (would need a live/wild-traffic check, folded into Step 5).
- MIG's offline `--sql` validation proves migration syntax correctness in both directions — it
  does NOT prove a live round-trip against a real Postgres instance (out of scope per program
  hard-stop; no live apply in this plan) and does not prove data-migration correctness for any
  pre-existing rows (both new migrations are additive/nullable, so this residual risk is low, not
  zero).

Gate: CONDITIONAL (0 unresolved FAILs — the one FAIL-severity gap found, synchronous paid-waterfall
budget exhaustion, was resolved in-plan via mandatory Must-Fix 3 + Plan Updates P1-P5 above, not
left open; remaining items are CONCERNs with concrete execute-agent instructions attached, plus 2
correctly-scoped, pre-approved known-gaps)
Accepted by: session (single-pass deep-mode VALIDATE per explicit orchestrator instruction — no
interactive user turn was available in this subagent invocation; every CONCERN identified during
the fan-out was either (1) fixed directly in the plan text as a Plan Update [P1-P5] or (2) carried
forward as a MANDATORY execute-agent instruction with a corresponding new test gate [Must-Fix 3 /
MF-3], per this system's standard "concerns that cannot be fixed in plan text are written to the
validate-contract for execute-agent to follow" rule. Orchestrator/user should re-confirm acceptance
of Must-Fix 3's two resolution options (a)/(b) at EXECUTE kickoff if either is contentious — neither
is mandated over the other by this VALIDATE pass.)

---

## Autonomous Goal Block

SESSION GOAL: WS3 Agent Concierge kill test — param-gate the 3 free MCP tools behind qualification
info, add a zero-click request_quote/book_demo conversion tool + isolated lead table, prove it
never weakens emailability separation or drains identity-resolution budget, then (WS0-gated, out
of this plan) run a real 1-week wild kill test to decide GO/NO-GO on this product direction.
Charter + umbrella plan: N/A on this checkout — `agent-native-revenue-umbrella_PLAN_30-07-26.md`
exists only on branch `feat/ws2-agent-session-classifier` (not present on disk here); re-fetch via
`git show feat/ws2-agent-session-classifier:process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/agent-native-revenue-umbrella_PLAN_30-07-26.md`
before EXECUTE if a Program Goal Charter is needed for cross-workstream context.
Autonomy: Steps 1-4 (buildable code) have no WS0 dependency and may proceed once EXECUTE begins;
Step 5 (wild kill test) is a hard stop — do not attempt it in this plan/EXECUTE cycle regardless of
autonomy level; program hard stops (no live merge to main beyond normal PR flow, no prod flag flip,
no provider spend, no public-site publish) apply unconditionally.
Hard stop conditions / safety constraints:
- Never synchronously call `IdentityResolver.resolve()` / `run_company_resolution_sweep()` from the
  conversion-tool request handler (Must-Fix 3) — budget-exhaustion vector on a public write path.
- Never weaken `source_agent_visit_id` / `is_emailable_identity` exclusion; `AgentLead` must never
  import `IdentifiedVisitor`/`Visitor` or gain a `visitor_id` column.
- Never flip `agent_concierge_qualification_enabled` / `agent_concierge_conversion_enabled` to True
  in any real environment as part of this plan — code-complete + flag-OFF is the EXECUTE finish
  line, not a live enablement.
- Never live-apply either new migration; offline `--sql` validation only, explicit incremental
  rev-range (never the unscoped `upgrade head --sql` shorthand — see Step 3.2 gotcha note).
- Do not attempt Step 5 (wild kill test / AC-WS3-5/6) in this cycle; write the backlog note instead.
Next phase: EXECUTE — `process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/ws3-agent-concierge_PLAN_30-07-26.md`
Validate contract: inline in this plan, section `## Validate Contract` above (Gate: CONDITIONAL).
Execute start: `.venv/bin/python3.11 -m pytest tests/integration/test_agent_mcp_concierge.py -m integration -q`
(once written) | Hybrid precondition: `docker compose -f infra/docker-compose.yml up -d postgres
redis` | Agent-Probe scenario: N/A for Steps 1-4 (all Fully-Automated/Hybrid) | high-risk pack:
yes — public unauthenticated write path + 2 schema migrations; manual-first evidence pack
recommended before treating Steps 1-4 as fully closed, per `vc-risk-evidence-pack`.

---

## Phase Completion Rules

- **PLAN → VALIDATE**: complete — Gate: CONDITIONAL, see Validate Contract section above.
- **PLAN → EXECUTE**: requires explicit "ENTER EXECUTE MODE" regardless of VALIDATE outcome.
- **EXECUTE → done (for Steps 1-4 only)**: complete when AC-WS3-1 through AC-WS3-4's Fully-Automated/
  Hybrid gates are green (per the corrected Test Gates table above, including the new MF-3 gate),
  the migration offline-validate passes both directions, and `test_agent_origin_exclusion.py` stays
  green with zero new failures.
- **Not VERIFIED until AC-WS3-5/6 close** — per the program's wild-test discipline (guardrail 3),
  this plan can reach `CODE DONE` (Steps 1-4 implemented and lab-tested) but not `VERIFIED` until
  the wild kill test (Step 5) runs against real production traffic and a signed GO/NO-GO exists. Do
  not mark this plan `✅ VERIFIED` in any phase report or the umbrella status table until then.
- **Known-gap handling**: AC-WS3-5/6's known-gap status (and the WS0 dependency) must be written
  into the phase report at UPDATE PROCESS, with the backlog note path named explicitly, not
  silently dropped.

## Resume and Execution Handoff

1. **Selected plan file path:** `process/features/agent-native-revenue/active/agent-native-revenue_30-07-26/ws3-agent-concierge_PLAN_30-07-26.md`
2. **Last completed phase/step:** VALIDATE (this document) — Gate: CONDITIONAL, validate-contract
   written. Not yet executed.
3. **Validate-contract status:** written, Gate: CONDITIONAL (see Validate Contract section above,
   `generated-by: inner-pvl: WS3`). 5 Plan Updates applied in-line (P1-P5) + 1 new mandatory
   Must-Fix (MF-3, with its own test gate) — no unresolved FAILs remain.
4. **Supporting context files loaded:** `agent-native-revenue_SPEC_30-07-26.md` (WS3 ACs +
   constraints, read via `git show feat/ws2-agent-session-classifier:...` — confirm on-branch
   before EXECUTE, see Provenance note above), `agent-native-revenue-umbrella_PLAN_30-07-26.md`
   (WS3 stub, join conditions, Program Goal Charter, same read path — confirmed NOT present on
   this checkout's disk at VALIDATE time), `apps/api/routers/agent_mcp.py`,
   `apps/api/services/agent_gateway.py`, `apps/api/models/agent_profile.py`,
   `apps/api/schemas/agent_gateway.py`, `apps/api/services/agent_company_resolution.py`,
   `apps/api/services/daily_digest.py` + `apps/api/services/outcome_digest.py` +
   `apps/api/services/email_sender.py` (notification precedent, `custom_args` param confirmed;
   NO `MOCK_EXTERNAL_APIS` short-circuit exists — confirmed at VALIDATE, see P5),
   `apps/api/agents/prompt_safety.py` (`clean_text`/`sanitize_profiles`/`wrap_untrusted` confirmed
   present; `clean_text` confirmed as the correct call for the 3 new qualification fields, see P1),
   `tests/unit/test_agent_origin_exclusion.py` (structure confirmed, 6 existing test
   functions), `apps/api/config.py` (flag-default-OFF precedent confirmed, e.g.
   `site_ingest_limit_enabled`), `apps/api/services/rate_limiter.py` (`limiter`/`site_limiter`
   instances + `site_ceiling_tripped()` precedent confirmed as the Must-Fix-1 implementation
   pattern, see P3), `apps/api/models/agent_fetch_event.py` + `apps/api/models/agent_visit.py`
   (existing columns/indexes confirmed; `vendor` NOT NULL on both — flagged, see P4),
   `apps/api/services/identity_classification.py` (`is_emailable_identity` guard confirmed,
   read-only referenced), `apps/api/services/agent_visit_persistence.py` (the REAL
   `persist_agent_visit`/`persist_agent_fetch_event` functions — `record_gateway_visit` does not
   exist anywhere in the repo, see P2), `apps/api/services/agent_classifier.py`
   (`classify_agent()` returns `None` for unrecognized UAs — feeds the P2/P4 vendor-value
   decision), `apps/api/services/identity_resolver.py` + `apps/api/services/agent_company_resolution.py`
   (confirmed `run_company_resolution_sweep()` is the only resolver and internally calls the full
   paid multi-provider waterfall — the basis of Must-Fix 3), alembic migration chain independently
   re-traced at VALIDATE (30-07-26): true single head `a2f8d61c9e37` confirmed, no branching.
5. **Next step for a fresh agent:** invoke `vc-docs-seeker` (or fetch directly) to confirm the exact
   MCP `initialize` request/response shape and current protocol version string before writing Step
   1's handler (do not hand-write from memory); confirm the SPEC/umbrella files exist on the
   execution branch (merge or re-fetch via `git show` if not); on "ENTER EXECUTE MODE", implement
   Steps 1 -> 2 -> 3 -> 4 in order INCLUDING the VALIDATE-added corrections (P1-P5, MF-3), running
   the per-section test gates from the Validate Contract's Test Gates table as each step completes;
   write the Step 5 backlog note at UPDATE PROCESS regardless of how Steps 1-4 land.

---

PHASE_COMPLETE: VALIDATE — validate-contract written (Gate: CONDITIONAL). Proceed to EXECUTE.
